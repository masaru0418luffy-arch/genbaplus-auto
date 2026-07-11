"""
ストレージ抽象化レイヤー

CSV（ローカル）と Supabase（クラウド）を同一インターフェースで扱う。
環境変数 SUPABASE_URL / SUPABASE_ANON_KEY が設定されていれば Supabase を使用し、
未設定の場合は CSV + progress.json にフォールバックする。
"""

from __future__ import annotations

import csv
import json
import logging
import os
from abc import ABC, abstractmethod
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

# .env ファイルを自動読み込み
load_dotenv(Path(__file__).parent / ".env")

logger = logging.getLogger("gmaps_scraper.storage")


# ---------------------------------------------------------------------------
# 抽象基底クラス
# ---------------------------------------------------------------------------
class StoreWriter(ABC):
    @abstractmethod
    def write_row(self, store) -> None: ...

    @abstractmethod
    def count_rows(self) -> int: ...

    @abstractmethod
    def is_url_saved(self, google_maps_url: str) -> bool: ...


class ProgressStore(ABC):
    @abstractmethod
    def is_url_completed(self, url: str) -> bool: ...

    @abstractmethod
    def mark_url_completed(self, url: str) -> None: ...

    @abstractmethod
    def get_search_state(self, keyword: str, area: str) -> dict: ...

    @abstractmethod
    def update_search_state(self, keyword: str, area: str, **kwargs) -> None: ...

    @abstractmethod
    def set_interrupted(self, reason: str) -> None: ...

    @abstractmethod
    def set_completed(self) -> None: ...

    @abstractmethod
    def get_status(self) -> dict: ...


# ---------------------------------------------------------------------------
# CSV バックエンド（ローカル保存）
# ---------------------------------------------------------------------------
FIELDNAMES = [
    "company_name", "industry", "address", "phone", "instagram_url", "website_url",
    "review_count", "last_photo_posted_date", "website_domain_creation_date",
    "google_maps_url", "scraped_at",
]


class CSVStoreWriter(StoreWriter):
    def __init__(self, csv_file: str):
        self.csv_path = Path(csv_file)
        self.csv_path.parent.mkdir(parents=True, exist_ok=True)
        if not self.csv_path.exists():
            with open(self.csv_path, "w", newline="", encoding="utf-8-sig") as f:
                csv.DictWriter(f, fieldnames=FIELDNAMES).writeheader()

    def write_row(self, store) -> None:
        with open(self.csv_path, "a", newline="", encoding="utf-8-sig") as f:
            csv.DictWriter(f, fieldnames=FIELDNAMES).writerow(asdict(store))

    def count_rows(self) -> int:
        if not self.csv_path.exists():
            return 0
        with open(self.csv_path, encoding="utf-8-sig") as f:
            return max(0, sum(1 for _ in f) - 1)

    def is_url_saved(self, google_maps_url: str) -> bool:
        if not self.csv_path.exists():
            return False
        with open(self.csv_path, encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            return any(row.get("google_maps_url") == google_maps_url for row in reader)


class JSONProgressStore(ProgressStore):
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

    def _save(self) -> None:
        self.progress_file.parent.mkdir(parents=True, exist_ok=True)
        with open(self.progress_file, "w", encoding="utf-8") as f:
            json.dump(self.data, f, ensure_ascii=False, indent=2)

    def is_url_completed(self, url: str) -> bool:
        return url in self.data["completed_urls"]

    def mark_url_completed(self, url: str) -> None:
        if url not in self.data["completed_urls"]:
            self.data["completed_urls"].append(url)
        self._save()

    def get_search_state(self, keyword: str, area: str) -> dict:
        key = f"{keyword}_{area}"
        for s in self.data["searches"]:
            if s["query_key"] == key:
                return s
        new_state = {"keyword": keyword, "area": area, "query_key": key,
                     "status": "pending", "processed_count": 0}
        self.data["searches"].append(new_state)
        self._save()
        return new_state

    def update_search_state(self, keyword: str, area: str, **kwargs) -> None:
        key = f"{keyword}_{area}"
        for s in self.data["searches"]:
            if s["query_key"] == key:
                s.update(kwargs)
        self._save()

    def set_interrupted(self, reason: str) -> None:
        self.data.update(interrupted=True, interrupt_reason=reason,
                         last_run_at=datetime.now().isoformat())
        self._save()

    def set_completed(self) -> None:
        self.data.update(interrupted=False, interrupt_reason=None,
                         last_run_at=datetime.now().isoformat())
        self._save()

    def get_status(self) -> dict:
        return {
            "interrupted": self.data.get("interrupted", False),
            "interrupt_reason": self.data.get("interrupt_reason"),
            "last_run_at": self.data.get("last_run_at"),
            "completed_url_count": len(self.data.get("completed_urls", [])),
        }


# ---------------------------------------------------------------------------
# Supabase バックエンド
# ---------------------------------------------------------------------------
def _get_supabase_client():
    """Supabase クライアントを生成する。未設定なら None を返す。"""
    url = os.environ.get("SUPABASE_URL", "").strip()
    key = os.environ.get("SUPABASE_ANON_KEY", "").strip()
    if not url or not key or url.startswith("https://xxxx"):
        return None
    try:
        from supabase import create_client  # type: ignore
        return create_client(url, key)
    except ImportError:
        logger.warning("supabase-py が見つかりません。pip install supabase を実行してください。")
        return None
    except Exception as e:
        logger.error(f"Supabase 接続エラー: {e}")
        return None


class SupabaseStoreWriter(StoreWriter):
    """stores テーブルに1件ずつ upsert する。"""

    def __init__(self):
        self._client = _get_supabase_client()
        if not self._client:
            raise RuntimeError("Supabase クライアントの初期化に失敗しました。.env を確認してください。")

    def write_row(self, store) -> None:
        data = asdict(store)
        # review_count は integer
        data["review_count"] = int(data.get("review_count") or 0)
        try:
            self._client.table("stores").upsert(
                data, on_conflict="google_maps_url"
            ).execute()
        except Exception as e:
            logger.error(f"Supabase insert エラー: {e}")
            raise

    def count_rows(self) -> int:
        try:
            res = self._client.table("stores").select("id", count="exact").execute()
            return res.count or 0
        except Exception as e:
            logger.error(f"Supabase count エラー: {e}")
            return 0

    def is_url_saved(self, google_maps_url: str) -> bool:
        try:
            res = (
                self._client.table("stores")
                .select("google_maps_url")
                .eq("google_maps_url", google_maps_url)
                .limit(1)
                .execute()
            )
            return len(res.data) > 0
        except Exception as e:
            logger.error(f"Supabase URL 確認エラー: {e}")
            return False


class SupabaseProgressStore(ProgressStore):
    """
    completed_urls / progress テーブルで進捗を管理する。
    複数 PC から同時実行しても重複しない。
    """

    def __init__(self):
        self._client = _get_supabase_client()
        if not self._client:
            raise RuntimeError("Supabase クライアントの初期化に失敗しました。")
        self._interrupted = False
        self._interrupt_reason: Optional[str] = None
        self._last_run_at: Optional[str] = None

    def is_url_completed(self, url: str) -> bool:
        try:
            res = (
                self._client.table("completed_urls")
                .select("url")
                .eq("url", url)
                .limit(1)
                .execute()
            )
            return len(res.data) > 0
        except Exception as e:
            logger.error(f"Supabase completed_urls 確認エラー: {e}")
            return False

    def mark_url_completed(self, url: str) -> None:
        try:
            self._client.table("completed_urls").upsert(
                {"url": url, "completed_at": datetime.now().isoformat()},
                on_conflict="url",
            ).execute()
        except Exception as e:
            logger.error(f"Supabase completed_urls insert エラー: {e}")

    def get_search_state(self, keyword: str, area: str) -> dict:
        key = f"{keyword}_{area}"
        try:
            res = (
                self._client.table("search_progress")
                .select("*")
                .eq("query_key", key)
                .limit(1)
                .execute()
            )
            if res.data:
                return res.data[0]
        except Exception as e:
            logger.error(f"Supabase search_progress 取得エラー: {e}")

        new_state = {"keyword": keyword, "area": area, "query_key": key,
                     "status": "pending", "processed_count": 0}
        try:
            self._client.table("search_progress").upsert(
                new_state, on_conflict="query_key"
            ).execute()
        except Exception as e:
            logger.error(f"Supabase search_progress insert エラー: {e}")
        return new_state

    def update_search_state(self, keyword: str, area: str, **kwargs) -> None:
        key = f"{keyword}_{area}"
        try:
            self._client.table("search_progress").update(
                {**kwargs, "updated_at": datetime.now().isoformat()}
            ).eq("query_key", key).execute()
        except Exception as e:
            logger.error(f"Supabase search_progress 更新エラー: {e}")

    def set_interrupted(self, reason: str) -> None:
        self._interrupted = True
        self._interrupt_reason = reason
        self._last_run_at = datetime.now().isoformat()
        try:
            self._client.table("run_status").upsert({
                "id": 1,
                "interrupted": True,
                "interrupt_reason": reason,
                "last_run_at": self._last_run_at,
            }, on_conflict="id").execute()
        except Exception as e:
            logger.error(f"Supabase run_status 更新エラー: {e}")

    def set_completed(self) -> None:
        self._interrupted = False
        self._interrupt_reason = None
        self._last_run_at = datetime.now().isoformat()
        try:
            self._client.table("run_status").upsert({
                "id": 1,
                "interrupted": False,
                "interrupt_reason": None,
                "last_run_at": self._last_run_at,
            }, on_conflict="id").execute()
        except Exception as e:
            logger.error(f"Supabase run_status 更新エラー: {e}")

    def get_status(self) -> dict:
        return {
            "interrupted": self._interrupted,
            "interrupt_reason": self._interrupt_reason,
            "last_run_at": self._last_run_at,
        }


# ---------------------------------------------------------------------------
# ファクトリ関数（自動選択）
# ---------------------------------------------------------------------------
class CompositeStoreWriter(StoreWriter):
    """複数のライターに同時書き込みする。一部が失敗しても他は継続する。"""

    def __init__(self, writers: list):
        self.writers = writers

    def write_row(self, store) -> None:
        for w in self.writers:
            try:
                w.write_row(store)
            except Exception as e:
                logger.error(f"{type(w).__name__} 書き込みエラー（スキップ）: {e}")

    def count_rows(self) -> int:
        counts = []
        for w in self.writers:
            try:
                counts.append(w.count_rows())
            except Exception:
                pass
        return max(counts) if counts else 0

    def is_url_saved(self, google_maps_url: str) -> bool:
        return any(w.is_url_saved(google_maps_url) for w in self.writers)


def create_store_writer(config: dict) -> StoreWriter:
    """
    利用可能なストレージを全部束ねて返す。
    - Supabase (.env 設定済み) → SupabaseStoreWriter
    - Google Sheets (credentials.json 存在) → GoogleSheetsWriter
    - どちらもなければ CSV
    複数が有効な場合は CompositeStoreWriter で同時書き込み。
    """
    writers = []

    # Supabase
    client = _get_supabase_client()
    if client:
        writers.append(SupabaseStoreWriter())
        logger.info("ストレージ: Supabase を使用します")

    # Google Sheets
    try:
        from sheets import GoogleSheetsWriter, is_available
        if is_available():
            sheets_id = config.get("sheets", {}).get(
                "spreadsheet_id", "1gd4-WX_57Ctb2jLO9v3fuGFCqUi6c_zN1wWv3z1vGcU"
            )
            writers.append(GoogleSheetsWriter(sheets_id))
            logger.info("ストレージ: Google Sheets を使用します")
    except Exception as e:
        logger.debug(f"Google Sheets 初期化スキップ: {e}")

    # フォールバック: CSV
    if not writers:
        csv_file = config.get("output", {}).get("csv_file", "output/results.csv")
        writers.append(CSVStoreWriter(csv_file))
        logger.info(f"ストレージ: CSV を使用します ({csv_file})")

    return writers[0] if len(writers) == 1 else CompositeStoreWriter(writers)


def create_progress_store(config: dict) -> ProgressStore:
    """
    Supabase が使えれば SupabaseProgressStore、なければ JSONProgressStore を返す。
    """
    client = _get_supabase_client()
    if client:
        logger.info("進捗管理: Supabase を使用します")
        return SupabaseProgressStore()
    else:
        progress_file = config.get("output", {}).get("progress_file", "progress.json")
        logger.info(f"進捗管理: JSON ファイルを使用します ({progress_file})")
        return JSONProgressStore(progress_file)
