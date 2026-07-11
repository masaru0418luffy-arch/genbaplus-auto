"""
Google マップ営業リスト自動抽出システム - スクレイピング本体

【注意】
Google マップのスクレイピングは利用規約(ToS)上のグレーゾーンです。
本ツールは社内利用のみを前提とし、アクセス頻度を最小限に抑える設計となっています。
商用・大量・高頻度の自動アクセスは規約違反となりうるため、運用ルールを遵守してください。
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
import logging
import random
import re
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional
from urllib.parse import quote, urlparse

import yaml

# ストレージ抽象化（CSV / Supabase を自動選択）
from storage import create_store_writer, create_progress_store

# ---------------------------------------------------------------------------
# ロギング設定
# ---------------------------------------------------------------------------
LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s - %(message)s"


def setup_logging(log_file: str, level: str = "INFO") -> logging.Logger:
    logger = logging.getLogger("gmaps_scraper")
    if logger.handlers:
        return logger  # already configured (e.g., called from Streamlit)
    logger.setLevel(getattr(logging, level.upper(), logging.INFO))

    ch = logging.StreamHandler()
    ch.setLevel(logging.INFO)
    ch.setFormatter(logging.Formatter(LOG_FORMAT))
    logger.addHandler(ch)

    log_path = Path(log_file)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    fh = logging.FileHandler(log_file, encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(logging.Formatter(LOG_FORMAT))
    logger.addHandler(fh)

    return logger


# ---------------------------------------------------------------------------
# データクラス
# ---------------------------------------------------------------------------
@dataclass
class StoreData:
    company_name: str = ""
    industry: str = ""
    instagram_url: str = ""
    website_url: str = ""
    review_count: int = 0
    last_photo_posted_date: str = ""
    website_domain_creation_date: str = ""
    google_maps_url: str = ""
    scraped_at: str = ""


# ---------------------------------------------------------------------------
# 進捗管理
# ---------------------------------------------------------------------------
class ProgressManager:
    """取得済みURL・検索状態を progress.json で管理する。再開機能の核。"""

    def __init__(self, progress_file: str):
        self.progress_file = Path(progress_file)
        self.data = self._load()

    def _load(self) -> dict:
        if self.progress_file.exists():
            try:
                with open(self.progress_file, encoding="utf-8") as f:
                    return json.load(f)
            except (json.JSONDecodeError, IOError):
                pass
        return {
            "version": 1,
            "searches": [],
            "completed_urls": [],
            "last_run_at": None,
            "interrupted": False,
            "interrupt_reason": None,
        }

    def save(self) -> None:
        self.progress_file.parent.mkdir(parents=True, exist_ok=True)
        with open(self.progress_file, "w", encoding="utf-8") as f:
            json.dump(self.data, f, ensure_ascii=False, indent=2)

    def is_url_completed(self, url: str) -> bool:
        return url in self.data["completed_urls"]

    def mark_url_completed(self, url: str) -> None:
        if url not in self.data["completed_urls"]:
            self.data["completed_urls"].append(url)
        self.save()

    def get_search_state(self, keyword: str, area: str) -> dict:
        key = f"{keyword}_{area}"
        for s in self.data["searches"]:
            if s["query_key"] == key:
                return s
        new_state = {
            "keyword": keyword,
            "area": area,
            "query_key": key,
            "status": "pending",
            "processed_count": 0,
        }
        self.data["searches"].append(new_state)
        self.save()
        return new_state

    def update_search_state(self, keyword: str, area: str, **kwargs) -> None:
        key = f"{keyword}_{area}"
        for s in self.data["searches"]:
            if s["query_key"] == key:
                s.update(kwargs)
        self.save()

    def set_interrupted(self, reason: str) -> None:
        self.data["interrupted"] = True
        self.data["interrupt_reason"] = reason
        self.data["last_run_at"] = datetime.now().isoformat()
        self.save()

    def set_completed(self) -> None:
        self.data["interrupted"] = False
        self.data["interrupt_reason"] = None
        self.data["last_run_at"] = datetime.now().isoformat()
        self.save()


# ---------------------------------------------------------------------------
# CSV ライター（逐次追記）
# ---------------------------------------------------------------------------
class CSVWriter:
    """1件ごとに CSV へ追記する。途中停止時もそれまでの成果が失われない。"""

    FIELDNAMES = [
        "company_name",
        "industry",
        "instagram_url",
        "website_url",
        "review_count",
        "last_photo_posted_date",
        "website_domain_creation_date",
        "google_maps_url",
        "scraped_at",
    ]

    def __init__(self, csv_file: str):
        self.csv_path = Path(csv_file)
        self.csv_path.parent.mkdir(parents=True, exist_ok=True)
        if not self.csv_path.exists():
            with open(self.csv_path, "w", newline="", encoding="utf-8-sig") as f:
                csv.DictWriter(f, fieldnames=self.FIELDNAMES).writeheader()

    def write_row(self, store: StoreData) -> None:
        with open(self.csv_path, "a", newline="", encoding="utf-8-sig") as f:
            csv.DictWriter(f, fieldnames=self.FIELDNAMES).writerow(asdict(store))

    def count_rows(self) -> int:
        if not self.csv_path.exists():
            return 0
        with open(self.csv_path, encoding="utf-8-sig") as f:
            return max(0, sum(1 for _ in f) - 1)  # subtract header


# ---------------------------------------------------------------------------
# 日本語相対日付パーサー
# ---------------------------------------------------------------------------
class JapaneseDateParser:
    """Google マップに表示される日本語相対日付を解析し、1年以内か判定する。"""

    @staticmethod
    def is_within_one_year(date_str: str) -> tuple[bool, str]:
        """
        Returns:
            (within_one_year: bool, original_or_normalized_str: str)
            date_str が空または判定不能の場合は (False, "取得不可") を返す。
        """
        if not date_str:
            return False, "取得不可"

        s = date_str.strip()

        # 今日 / 昨日 / 今週 / 先週 / 今月 / 先月 → 1年以内
        if any(t in s for t in ["今日", "昨日", "今週", "先週", "今月", "先月"]):
            return True, s

        # X日前 → 1年以内
        if re.search(r"\d+\s*日前", s):
            return True, s

        # X週間前 → 1年以内（最大52週≒1年）
        if re.search(r"\d+\s*週間前", s):
            return True, s

        # Xか月前 → 1〜11か月 は1年以内
        m = re.search(r"(\d+)\s*か月前", s)
        if m:
            months = int(m.group(1))
            return months <= 11, s

        # X年前 → 1年以内ではない（1年前も含む）
        if re.search(r"\d+\s*年前", s):
            return False, s

        return False, "取得不可"


# ---------------------------------------------------------------------------
# WHOIS ルックアップ
# ---------------------------------------------------------------------------
def get_domain_creation_date(url: str, logger: logging.Logger) -> str:
    """python-whois でドメイン取得日を調べる。取得できない場合は '取得不可' を返す。"""
    if not url:
        return "取得不可"
    try:
        import whois as python_whois  # lazy import

        parsed = urlparse(url)
        domain = parsed.netloc or parsed.path
        domain = domain.split(":")[0].lstrip("www.")

        if not domain or "." not in domain:
            return "取得不可"

        logger.debug(f"WHOIS lookup: {domain}")
        w = python_whois.whois(domain)
        creation_date = w.creation_date
        if isinstance(creation_date, list):
            creation_date = creation_date[0]
        if creation_date:
            if isinstance(creation_date, datetime):
                return creation_date.strftime("%Y-%m-%d")
            return str(creation_date)[:10]
        return "取得不可"
    except Exception as e:
        logger.debug(f"WHOIS failed ({url}): {e}")
        return "取得不可"


# ---------------------------------------------------------------------------
# Instagram URL 抽出
# ---------------------------------------------------------------------------
_INSTAGRAM_PATTERN = re.compile(
    r"https?://(?:www\.)?instagram\.com/[a-zA-Z0-9_./?=&#%@+-]+"
)


def extract_instagram_url(text: str) -> str:
    m = _INSTAGRAM_PATTERN.search(text)
    return m.group(0).rstrip("/?") if m else ""


# ---------------------------------------------------------------------------
# Google マップ スクレイパー（Playwright）
# ---------------------------------------------------------------------------
class GoogleMapsScraper:
    """
    Playwright (headless Chromium) を使って Google マップをスクレイピングする。
    ヘッドレスブラウザの検出軽減のため playwright-stealth を利用する（任意）。
    """

    def __init__(self, config: dict, logger: logging.Logger):
        self.config = config
        self.logger = logger
        self.selectors = config.get("selectors", {})
        self.delays = config.get("delays", {})
        self.user_agents = config.get("user_agents", [
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        ])
        self._playwright = None
        self.browser = None
        self.context = None
        self.page = None
        self._captcha_detected = False
        self._items_processed = 0

    async def __aenter__(self) -> "GoogleMapsScraper":
        from playwright.async_api import async_playwright

        self._playwright = await async_playwright().start()
        self.browser = await self._playwright.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-dev-shm-usage",
                "--disable-blink-features=AutomationControlled",
                "--lang=ja",
            ],
        )
        ua = random.choice(self.user_agents)
        self.context = await self.browser.new_context(
            user_agent=ua,
            locale="ja-JP",
            timezone_id="Asia/Tokyo",
            viewport={"width": 1280, "height": 800},
            java_script_enabled=True,
        )
        self.page = await self.context.new_page()

        # playwright-stealth（インストール済みの場合のみ適用）
        try:
            from playwright_stealth import stealth_async  # type: ignore

            await stealth_async(self.page)
            self.logger.info("playwright-stealth を適用しました")
        except ImportError:
            self.logger.debug("playwright-stealth が見つかりません（ステルスなしで続行）")

        return self

    async def __aexit__(self, *args) -> None:
        if self.context:
            await self.context.close()
        if self.browser:
            await self.browser.close()
        if self._playwright:
            await self._playwright.stop()

    # ------------------------------------------------------------------
    # 内部ユーティリティ
    # ------------------------------------------------------------------
    async def _random_delay(self, min_s: float | None = None, max_s: float | None = None) -> None:
        min_s = min_s if min_s is not None else float(self.delays.get("min_seconds", 5))
        max_s = max_s if max_s is not None else float(self.delays.get("max_seconds", 15))
        wait = random.uniform(min_s, max_s)
        self.logger.debug(f"待機: {wait:.1f}秒")
        await asyncio.sleep(wait)

    async def _cooldown_if_needed(self) -> None:
        every_n = int(self.delays.get("cooldown_every_n_items", 10))
        if every_n <= 0:
            return
        if self._items_processed > 0 and self._items_processed % every_n == 0:
            min_cd = float(self.delays.get("cooldown_min_seconds", 60))
            max_cd = float(self.delays.get("cooldown_max_seconds", 120))
            cd = random.uniform(min_cd, max_cd)
            self.logger.info(
                f"クールダウン中 ({self._items_processed}件処理済み) ... {cd:.0f}秒待機"
            )
            await asyncio.sleep(cd)

    async def _check_captcha(self) -> bool:
        try:
            content = await self.page.content()
            indicators = self.selectors.get("captcha_indicators", [
                "異常なトラフィック", "自動化されたクエリ", "reCAPTCHA",
                "I'm not a robot", "ロボットではありません", "unusual traffic",
            ])
            for ind in indicators:
                if ind in content:
                    return True
            # reCAPTCHA iframe
            if await self.page.query_selector("iframe[src*='recaptcha']"):
                return True
        except Exception:
            pass
        return False

    async def _accept_consent(self) -> None:
        consent_sels = self.selectors.get("consent_buttons", [
            'button:has-text("すべて同意")',
            'button:has-text("同意する")',
            'button:has-text("Accept all")',
            "#L2AGLb",
        ])
        for sel in consent_sels:
            try:
                btn = await self.page.query_selector(sel)
                if btn:
                    await btn.click()
                    self.logger.debug("同意ダイアログを閉じました")
                    await asyncio.sleep(2)
                    return
            except Exception:
                continue

    async def _try_selectors(self, selector_key: str, attr: str | None = None) -> str:
        """複数のセレクタを順に試し、最初にマッチした要素のテキスト or 属性値を返す。"""
        sels = self.selectors.get(selector_key, [])
        if isinstance(sels, str):
            sels = [sels]
        for sel in sels:
            try:
                el = await self.page.query_selector(sel)
                if el:
                    if attr:
                        val = await el.get_attribute(attr)
                    else:
                        val = await el.text_content()
                    if val and val.strip():
                        return val.strip()
            except Exception:
                continue
        return ""

    # ------------------------------------------------------------------
    # 検索結果 URL リスト取得
    # ------------------------------------------------------------------
    async def search_and_get_urls(
        self, keyword: str, area: str, max_items: int
    ) -> list[str]:
        query = f"{keyword} {area}"
        url = f"https://www.google.com/maps/search/{quote(query)}?hl=ja"
        self.logger.info(f"検索URL: {url}")

        try:
            await self.page.goto(url, wait_until="domcontentloaded", timeout=30000)
        except Exception as e:
            self.logger.error(f"ページ読み込みエラー: {e}")
            return []
        await asyncio.sleep(3)

        await self._accept_consent()

        if await self._check_captcha():
            self.logger.warning("検索ページで CAPTCHA を検知しました")
            self._captcha_detected = True
            return []

        feed_sel = self.selectors.get("results_feed", 'div[role="feed"]')
        try:
            await self.page.wait_for_selector(feed_sel, timeout=15000)
        except Exception:
            self.logger.warning(f"結果フィードが見つかりません (selector: {feed_sel})")
            await asyncio.sleep(5)

        store_urls: list[str] = []
        no_new_count = 0
        item_sel = self.selectors.get("result_item", 'a[href*="/maps/place/"]')

        while len(store_urls) < max_items + 20:
            links = await self.page.query_selector_all(item_sel)
            new_urls = []
            for link in links:
                href = await link.get_attribute("href") or ""
                if "/maps/place/" in href and href not in store_urls:
                    new_urls.append(href)

            prev_len = len(store_urls)
            store_urls = list(dict.fromkeys(store_urls + new_urls))

            if len(store_urls) >= max_items + 20:
                break

            # スクロールで追加読み込み
            try:
                feed = await self.page.query_selector(feed_sel)
                if feed:
                    await feed.evaluate("el => el.scrollTop += 800")
                else:
                    await self.page.keyboard.press("End")
            except Exception:
                await self.page.keyboard.press("End")

            await asyncio.sleep(2)

            # 末尾判定
            content = await self.page.content()
            if any(t in content for t in ["リストの末尾", "You've reached the end"]):
                self.logger.info("検索結果の末尾に達しました")
                break

            if len(store_urls) == prev_len:
                no_new_count += 1
                if no_new_count >= 3:
                    self.logger.info("新たな結果が取得できなくなりました")
                    break
            else:
                no_new_count = 0

        self.logger.info(f"{len(store_urls)} 件の店舗URLを取得")
        return store_urls[: max_items + 20]

    # ------------------------------------------------------------------
    # 店舗詳細取得
    # ------------------------------------------------------------------
    async def get_store_details(
        self, store_url: str, keyword: str
    ) -> Optional[StoreData]:
        store = StoreData(industry=keyword, google_maps_url=store_url)

        try:
            await self.page.goto(store_url, wait_until="domcontentloaded", timeout=30000)
            await asyncio.sleep(2)

            if await self._check_captcha():
                self.logger.warning(f"店舗ページで CAPTCHA を検知: {store_url[:60]}")
                self._captcha_detected = True
                return None

            # 店舗名
            store.company_name = await self._try_selectors("store_name_list")

            # 口コミ件数
            store.review_count = await self._get_review_count()

            # ウェブサイトURL
            store.website_url = await self._get_website_url()

            # Instagram URL
            store.instagram_url = await self._get_instagram_url(store.website_url)

            # 最新写真投稿日
            store.last_photo_posted_date = await self._get_last_photo_date(store_url)

            store.scraped_at = datetime.now().isoformat()

        except Exception as e:
            self.logger.error(f"店舗詳細取得エラー ({store_url[:60]}): {e}")
            return None

        return store

    async def _get_review_count(self) -> int:
        # aria-label 属性から数字を抽出
        sels = self.selectors.get("review_count_list", [])
        if isinstance(sels, str):
            sels = [sels]
        for sel in sels:
            try:
                el = await self.page.query_selector(sel)
                if el:
                    text = (
                        await el.get_attribute("aria-label")
                        or await el.text_content()
                        or ""
                    )
                    nums = re.findall(r"[\d,]+", text.replace(",", ""))
                    for n in nums:
                        count = int(n)
                        if count >= 0:
                            return count
            except Exception:
                continue

        # フォールバック: ページ全体から "X件の口コミ" を探す
        try:
            content = await self.page.content()
            m = re.search(r"([\d,]+)\s*件の口コミ", content)
            if m:
                return int(m.group(1).replace(",", ""))
        except Exception:
            pass
        return 0

    async def _get_website_url(self) -> str:
        sels = self.selectors.get("website_link_list", [])
        if isinstance(sels, str):
            sels = [sels]
        for sel in sels:
            try:
                el = await self.page.query_selector(sel)
                if el:
                    href = await el.get_attribute("href") or ""
                    if href.startswith("http") and "google.com" not in href:
                        return href
            except Exception:
                continue
        return ""

    async def _get_instagram_url(self, website_url: str) -> str:
        # ウェブサイトURL自体が Instagram の場合
        if website_url and "instagram.com" in website_url:
            return website_url

        # ページ内の Instagram リンクを探す
        try:
            links = await self.page.query_selector_all('a[href*="instagram.com"]')
            for link in links:
                href = await link.get_attribute("href") or ""
                if "instagram.com" in href:
                    return extract_instagram_url(href) or href
        except Exception:
            pass

        # ページ全文から抽出
        try:
            content = await self.page.content()
            return extract_instagram_url(content)
        except Exception:
            pass
        return ""

    async def _get_last_photo_date(self, store_url: str) -> str:
        """写真セクションから最新の投稿日（相対表記）を取得する。"""
        date_patterns = [
            r"\d+\s*日前",
            r"\d+\s*週間前",
            r"\d+\s*か月前",
            r"\d+\s*年前",
            r"今日",
            r"昨日",
            r"今週",
            r"先週",
            r"今月",
            r"先月",
        ]

        def find_date_in_text(text: str) -> str:
            for pat in date_patterns:
                m = re.search(pat, text)
                if m:
                    return m.group(0)
            return ""

        # 写真ボタンをクリック
        photo_sels = self.selectors.get("photos_button_list", [])
        if isinstance(photo_sels, str):
            photo_sels = [photo_sels]

        clicked = False
        for sel in photo_sels:
            try:
                el = await self.page.query_selector(sel)
                if el:
                    await el.click()
                    await asyncio.sleep(2)
                    clicked = True
                    break
            except Exception:
                continue

        if not clicked:
            # /photos URL に直接アクセスを試みる
            base = re.sub(r"\?.*", "", store_url)
            photos_url = base.rstrip("/") + "/photos"
            try:
                await self.page.goto(photos_url, wait_until="domcontentloaded", timeout=15000)
                await asyncio.sleep(2)
            except Exception:
                pass

        # 日付テキストを探す
        date_sels = self.selectors.get("photo_date_list", [])
        if isinstance(date_sels, str):
            date_sels = [date_sels]

        for sel in date_sels:
            try:
                els = await self.page.query_selector_all(sel)
                for el in els:
                    text = await el.text_content() or ""
                    date = find_date_in_text(text)
                    if date:
                        # 元のページに戻る
                        try:
                            await self.page.go_back()
                            await asyncio.sleep(1)
                        except Exception:
                            pass
                        return date
            except Exception:
                continue

        # ページ全文から抽出（最初にマッチしたもの＝最新に近い）
        try:
            content = await self.page.content()
            date = find_date_in_text(content)
            if date:
                try:
                    await self.page.go_back()
                    await asyncio.sleep(1)
                except Exception:
                    pass
                return date
        except Exception:
            pass

        # 元ページへ戻る
        try:
            await self.page.goto(store_url, wait_until="domcontentloaded", timeout=15000)
            await asyncio.sleep(1)
        except Exception:
            pass

        return "取得不可"

    @property
    def captcha_detected(self) -> bool:
        return self._captcha_detected


# ---------------------------------------------------------------------------
# メインスクレイピング処理
# ---------------------------------------------------------------------------
async def run_scraper(
    config: dict,
    progress_manager,  # ProgressStore (JSON or Supabase)
    csv_writer,        # StoreWriter (CSV or Supabase)
    logger: logging.Logger,
    ui_callback=None,  # Streamlit 等から進捗を受け取るコールバック (省略可)
) -> dict:
    """
    スクレイピングのメインループ。
    Returns: 実行サマリー dict
    """
    search_cfg = config.get("search", {})
    filters = config.get("filters", {})

    keywords = search_cfg.get("keywords", [])
    areas = search_cfg.get("areas", [])
    max_items = int(search_cfg.get("max_items_per_run", 30))
    max_review = int(filters.get("max_review_count", 10))

    date_parser = JapaneseDateParser()

    new_count = 0
    skipped_count = 0
    filtered_count = 0
    error_count = 0
    captcha_interrupted = False

    async with GoogleMapsScraper(config, logger) as scraper:
        for keyword in keywords:
            for area in areas:
                if new_count >= max_items:
                    logger.info(f"最大取得件数 {max_items} に達しました")
                    break

                logger.info(f"=== 検索: [{keyword}] [{area}] ===")

                state = progress_manager.get_search_state(keyword, area)
                if state.get("status") == "completed":
                    logger.info(f"この検索条件は完了済みです: {keyword} / {area}")
                    continue

                progress_manager.update_search_state(keyword, area, status="in_progress")

                # 取得上限より少し多めにURLを取って、フィルタ後に max_items に収める
                fetch_limit = max_items - new_count + 30
                store_urls = await scraper.search_and_get_urls(keyword, area, fetch_limit)

                if scraper.captcha_detected:
                    captcha_interrupted = True
                    progress_manager.set_interrupted("CAPTCHA detected during search")
                    break

                for url in store_urls:
                    if new_count >= max_items:
                        break

                    # 取得済みスキップ
                    if progress_manager.is_url_completed(url):
                        self_msg = f"スキップ (取得済み): {url[:70]}"
                        logger.debug(self_msg)
                        skipped_count += 1
                        continue

                    logger.info(f"取得中 [{new_count + 1}/{max_items}]: {url[:70]}")

                    store = await scraper.get_store_details(url, keyword)
                    scraper._items_processed += 1

                    if scraper.captcha_detected:
                        captcha_interrupted = True
                        progress_manager.set_interrupted("CAPTCHA detected during detail fetch")
                        break

                    if store is None:
                        error_count += 1
                        await scraper._random_delay()
                        continue

                    # 口コミ件数フィルタ
                    if store.review_count > max_review:
                        logger.debug(
                            f"除外 (口コミ {store.review_count}件 > {max_review}件): {store.company_name}"
                        )
                        filtered_count += 1
                        progress_manager.mark_url_completed(url)
                        await scraper._random_delay()
                        await scraper._cooldown_if_needed()
                        continue

                    # 写真投稿日フィルタ
                    within_year, photo_str = date_parser.is_within_one_year(
                        store.last_photo_posted_date
                    )
                    store.last_photo_posted_date = photo_str

                    if photo_str == "取得不可":
                        logger.debug(f"除外 (写真日付取得不可): {store.company_name}")
                        filtered_count += 1
                        progress_manager.mark_url_completed(url)
                        await scraper._random_delay()
                        await scraper._cooldown_if_needed()
                        continue

                    if not within_year:
                        logger.debug(
                            f"除外 (写真が1年以上前: {photo_str}): {store.company_name}"
                        )
                        filtered_count += 1
                        progress_manager.mark_url_completed(url)
                        await scraper._random_delay()
                        await scraper._cooldown_if_needed()
                        continue

                    # WHOIS
                    store.website_domain_creation_date = (
                        get_domain_creation_date(store.website_url, logger)
                        if store.website_url
                        else "取得不可"
                    )

                    # CSV 保存（逐次追記）
                    csv_writer.write_row(store)
                    progress_manager.mark_url_completed(url)
                    new_count += 1

                    log_line = (
                        f"  保存 #{new_count}: {store.company_name} | "
                        f"口コミ:{store.review_count}件 | "
                        f"写真:{store.last_photo_posted_date} | "
                        f"WS:{store.website_url[:40] if store.website_url else 'なし'}"
                    )
                    logger.info(log_line)

                    if ui_callback:
                        ui_callback(new_count, max_items, log_line)

                    progress_manager.update_search_state(
                        keyword,
                        area,
                        processed_count=state.get("processed_count", 0) + 1,
                    )

                    await scraper._random_delay()
                    await scraper._cooldown_if_needed()

                if captcha_interrupted:
                    break

                if new_count < max_items:
                    progress_manager.update_search_state(keyword, area, status="completed")

            if captcha_interrupted:
                break

    if captcha_interrupted:
        progress_manager.set_interrupted("CAPTCHA detected")
    else:
        progress_manager.set_completed()

    status = progress_manager.get_status()
    return {
        "new_count": new_count,
        "total_count": csv_writer.count_rows(),
        "skipped_count": skipped_count,
        "filtered_count": filtered_count,
        "error_count": error_count,
        "captcha_interrupted": captcha_interrupted,
        "interrupt_reason": status.get("interrupt_reason"),
    }


# ---------------------------------------------------------------------------
# 設定読み込み
# ---------------------------------------------------------------------------
def load_config(config_path: str) -> dict:
    with open(config_path, encoding="utf-8") as f:
        return yaml.safe_load(f)


# ---------------------------------------------------------------------------
# サマリー出力
# ---------------------------------------------------------------------------
def print_summary(summary: dict, elapsed: float, logger: logging.Logger) -> None:
    lines = [
        "=" * 55,
        "【実行サマリー】",
        f"  実行時間        : {elapsed:.1f}秒",
        f"  新規取得件数    : {summary['new_count']}件",
        f"  累計取得件数    : {summary['total_count']}件",
        f"  スキップ(取得済): {summary['skipped_count']}件",
        f"  フィルタ除外    : {summary['filtered_count']}件",
        f"  取得失敗        : {summary['error_count']}件",
    ]
    if summary["captcha_interrupted"]:
        lines.append(f"  *** CAPTCHA により途中終了 ***")
        lines.append(f"  理由: {summary['interrupt_reason']}")
    else:
        lines.append("  正常終了")
    lines.append("=" * 55)

    for line in lines:
        logger.info(line)
        print(line)


# ---------------------------------------------------------------------------
# CLI エントリーポイント
# ---------------------------------------------------------------------------
def main() -> int:
    parser = argparse.ArgumentParser(
        description="Google マップ営業リスト自動抽出システム",
        formatter_class=argparse.RawTextHelpFormatter,
    )
    parser.add_argument("--config", default="config.yaml", help="設定ファイルのパス (default: config.yaml)")
    parser.add_argument("--keyword", help="検索キーワード（config.yaml を上書き）")
    parser.add_argument("--area", help="エリア（config.yaml を上書き）")
    parser.add_argument("--max-items", type=int, help="最大取得件数（config.yaml を上書き）")
    parser.add_argument("--output", help="CSV 出力先（config.yaml を上書き）")
    args = parser.parse_args()

    config = load_config(args.config)

    if args.keyword:
        config.setdefault("search", {})["keywords"] = [args.keyword]
    if args.area:
        config.setdefault("search", {})["areas"] = [args.area]
    if args.max_items:
        config.setdefault("search", {})["max_items_per_run"] = args.max_items
    if args.output:
        config.setdefault("output", {})["csv_file"] = args.output

    out = config.get("output", {})
    log_file = out.get("log_file", "logs/scraper.log")
    log_level = out.get("log_level", "INFO")

    logger = setup_logging(log_file, log_level)
    logger.info("=== Google マップ営業リスト抽出 開始 ===")

    # ストレージバックエンドを自動選択（Supabase .env 設定済み → Supabase、未設定 → CSV）
    progress_manager = create_progress_store(config)
    csv_writer = create_store_writer(config)

    start = datetime.now()
    try:
        summary = asyncio.run(run_scraper(config, progress_manager, csv_writer, logger))
    except KeyboardInterrupt:
        logger.warning("Ctrl+C により中断")
        progress_manager.set_interrupted("ユーザーによる中断 (Ctrl+C)")
        summary = {
            "new_count": 0,
            "total_count": csv_writer.count_rows(),
            "skipped_count": 0,
            "filtered_count": 0,
            "error_count": 0,
            "captcha_interrupted": False,
            "interrupt_reason": "Ctrl+C",
        }
    except Exception as e:
        logger.critical(f"予期しないエラー: {e}", exc_info=True)
        progress_manager.set_interrupted(f"エラー: {e}")
        raise

    elapsed = (datetime.now() - start).total_seconds()
    print_summary(summary, elapsed, logger)

    return 1 if summary.get("captcha_interrupted") else 0


if __name__ == "__main__":
    raise SystemExit(main())
