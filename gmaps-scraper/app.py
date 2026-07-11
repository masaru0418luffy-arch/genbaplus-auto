"""
Google マップ営業リスト自動抽出システム - Streamlit UI

起動方法:
    streamlit run app.py

社員はこのアプリをブラウザから開いて業種・エリア・閾値を入力し、
実行ボタンを押すだけで CSV 形式の営業リストを取得できます。
"""

from __future__ import annotations

import asyncio
import io
import json
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

import pandas as pd
import streamlit as st
import yaml

# プロジェクトルートを sys.path に追加（scraper を import するため）
ROOT = Path(__file__).parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scraper import (
    CSVWriter,
    JapaneseDateParser,
    ProgressManager,
    load_config,
    run_scraper,
    setup_logging,
)

# ---------------------------------------------------------------------------
# ページ設定
# ---------------------------------------------------------------------------
st.set_page_config(
    page_title="Google マップ営業リスト抽出",
    page_icon="🗺️",
    layout="wide",
)

DEFAULT_CONFIG = "config.yaml"

# ---------------------------------------------------------------------------
# セッション状態の初期化
# ---------------------------------------------------------------------------
def init_session_state() -> None:
    defaults = {
        "running": False,
        "progress_msgs": [],
        "summary": None,
        "result_csv_path": None,
        "log": [],
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v


# ---------------------------------------------------------------------------
# 設定ファイル読み込み（なければデフォルト）
# ---------------------------------------------------------------------------
def load_ui_config() -> dict:
    config_path = ROOT / DEFAULT_CONFIG
    if config_path.exists():
        return load_config(str(config_path))
    return {
        "search": {"keywords": ["美容室"], "areas": ["東京都渋谷区"], "max_items_per_run": 30},
        "filters": {"max_review_count": 10, "require_photo_within_year": True},
        "delays": {
            "min_seconds": 5,
            "max_seconds": 15,
            "cooldown_every_n_items": 10,
            "cooldown_min_seconds": 60,
            "cooldown_max_seconds": 120,
        },
        "output": {
            "csv_file": "output/results.csv",
            "progress_file": "progress.json",
            "log_file": "logs/scraper.log",
        },
        "user_agents": [
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        ],
        "selectors": {},
    }


# ---------------------------------------------------------------------------
# スクレイパーをバックグラウンドスレッドで実行する
# ---------------------------------------------------------------------------
class ScraperRunner:
    """asyncio スクレイパーを別スレッドで走らせ、進捗を queue 経由で受け取る。"""

    def __init__(self, config: dict):
        self.config = config
        self.progress_msgs: list[str] = []
        self.summary: dict | None = None
        self.done = False
        self.error: str | None = None
        self._thread: threading.Thread | None = None

    def _ui_callback(self, current: int, total: int, msg: str) -> None:
        self.progress_msgs.append(f"[{current}/{total}] {msg}")

    def _run(self) -> None:
        out = self.config.get("output", {})
        log_file = out.get("log_file", "logs/scraper.log")
        csv_file = out.get("csv_file", "output/results.csv")
        progress_file = out.get("progress_file", "progress.json")

        logger = setup_logging(log_file)
        progress_manager = ProgressManager(progress_file)
        csv_writer = CSVWriter(csv_file)

        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            self.summary = loop.run_until_complete(
                run_scraper(
                    self.config,
                    progress_manager,
                    csv_writer,
                    logger,
                    ui_callback=self._ui_callback,
                )
            )
        except Exception as e:
            self.error = str(e)
        finally:
            self.done = True

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def is_done(self) -> bool:
        return self.done


# ---------------------------------------------------------------------------
# UI
# ---------------------------------------------------------------------------
def main() -> None:
    init_session_state()
    config_base = load_ui_config()

    st.title("🗺️ Google マップ 営業リスト自動抽出")
    st.caption(
        "業種・エリアを指定して Google マップから営業候補リストを CSV で出力します。"
        "口コミ10件以下 + 直近1年以内に写真投稿ありの店舗を抽出します。"
    )

    # ──────────────────────────────────────────────────
    # サイドバー: 設定入力
    # ──────────────────────────────────────────────────
    with st.sidebar:
        st.header("⚙️ 検索設定")

        keywords_raw = st.text_area(
            "業種（1行1キーワード）",
            value="\n".join(config_base["search"].get("keywords", ["美容室"])),
            height=100,
        )
        areas_raw = st.text_area(
            "エリア（1行1エリア）",
            value="\n".join(config_base["search"].get("areas", ["東京都渋谷区"])),
            height=100,
        )

        st.subheader("フィルタ条件")
        max_review = st.number_input(
            "口コミ件数の上限",
            min_value=0,
            max_value=1000,
            value=int(config_base["filters"].get("max_review_count", 10)),
            step=1,
        )
        max_items = st.number_input(
            "1回の最大取得件数",
            min_value=1,
            max_value=200,
            value=int(config_base["search"].get("max_items_per_run", 30)),
            step=5,
        )

        st.subheader("待機時間（秒）")
        col1, col2 = st.columns(2)
        with col1:
            delay_min = st.number_input("最小", value=float(config_base["delays"].get("min_seconds", 5)), step=1.0)
        with col2:
            delay_max = st.number_input("最大", value=float(config_base["delays"].get("max_seconds", 15)), step=1.0)

        st.subheader("CSV 出力先")
        csv_file = st.text_input("ファイルパス", value=config_base["output"].get("csv_file", "output/results.csv"))

        st.divider()
        st.info(
            "**注意**: Google マップの利用規約により、"
            "大量・高頻度・商用の自動アクセスは禁止されています。"
            "本ツールは社内利用に限定してください。"
        )

    # ──────────────────────────────────────────────────
    # メインエリア
    # ──────────────────────────────────────────────────
    tabs = st.tabs(["▶ 実行", "📊 結果プレビュー", "📄 進捗・ログ"])

    # ─── タブ1: 実行 ───────────────────────────────
    with tabs[0]:
        st.subheader("実行")

        keywords = [k.strip() for k in keywords_raw.splitlines() if k.strip()]
        areas = [a.strip() for a in areas_raw.splitlines() if a.strip()]

        if not keywords or not areas:
            st.warning("業種とエリアを1つ以上入力してください。")

        # 実行ボタン
        run_col, reset_col = st.columns([3, 1])
        with run_col:
            run_btn = st.button(
                "🚀 実行開始",
                disabled=st.session_state.running or not keywords or not areas,
                use_container_width=True,
                type="primary",
            )
        with reset_col:
            reset_btn = st.button(
                "🔄 進捗リセット",
                disabled=st.session_state.running,
                use_container_width=True,
                help="progress.json を削除して最初からやり直します",
            )

        if reset_btn:
            prog_file = ROOT / config_base["output"].get("progress_file", "progress.json")
            if prog_file.exists():
                prog_file.unlink()
                st.success("進捗ファイルをリセットしました。次回実行から最初から取得します。")
            else:
                st.info("進捗ファイルがありません（すでにリセット済み）。")

        if run_btn:
            # ランタイム設定を組み立てる
            runtime_config = dict(config_base)
            runtime_config["search"] = {
                **config_base.get("search", {}),
                "keywords": keywords,
                "areas": areas,
                "max_items_per_run": int(max_items),
            }
            runtime_config["filters"] = {
                **config_base.get("filters", {}),
                "max_review_count": int(max_review),
            }
            runtime_config["delays"] = {
                **config_base.get("delays", {}),
                "min_seconds": float(delay_min),
                "max_seconds": float(delay_max),
            }
            runtime_config["output"] = {
                **config_base.get("output", {}),
                "csv_file": csv_file,
            }

            st.session_state.running = True
            st.session_state.progress_msgs = []
            st.session_state.summary = None
            st.session_state.result_csv_path = csv_file
            st.session_state._runner = ScraperRunner(runtime_config)
            st.session_state._runner.start()

        # 実行中の進捗表示
        if st.session_state.running:
            runner: ScraperRunner = st.session_state.get("_runner")

            progress_placeholder = st.empty()
            status_placeholder = st.empty()

            with status_placeholder:
                st.info("⏳ スクレイピング実行中... ページを閉じても処理は続行されます。")

            # ポーリングループ（Streamlit の実験的機能でリアルタイム更新）
            while runner and not runner.is_done():
                msgs = runner.progress_msgs[-20:]  # 最新20件
                with progress_placeholder.container():
                    if msgs:
                        st.text("\n".join(msgs))
                time.sleep(2)
                st.rerun()

            # 完了
            if runner:
                if runner.error:
                    st.error(f"エラーが発生しました: {runner.error}")
                else:
                    st.session_state.summary = runner.summary
                    st.success("✅ 実行完了！")
            st.session_state.running = False

        # サマリー表示
        if st.session_state.summary:
            summary = st.session_state.summary
            st.subheader("実行サマリー")

            col1, col2, col3, col4 = st.columns(4)
            col1.metric("新規取得", f"{summary.get('new_count', 0)}件")
            col2.metric("累計取得", f"{summary.get('total_count', 0)}件")
            col3.metric("フィルタ除外", f"{summary.get('filtered_count', 0)}件")
            col4.metric("取得失敗", f"{summary.get('error_count', 0)}件")

            if summary.get("captcha_interrupted"):
                st.warning(
                    f"⚠️ CAPTCHA により途中終了しました。\n"
                    f"理由: {summary.get('interrupt_reason', '')}\n\n"
                    "翌日以降に再実行すると、取得済み分をスキップして続きから再開します。"
                )

            # CSV ダウンロード
            csv_path = Path(st.session_state.result_csv_path or "output/results.csv")
            if csv_path.exists():
                with open(csv_path, "rb") as f:
                    st.download_button(
                        label="📥 CSV をダウンロード",
                        data=f.read(),
                        file_name=csv_path.name,
                        mime="text/csv",
                        use_container_width=True,
                    )

    # ─── タブ2: 結果プレビュー ────────────────────────
    with tabs[1]:
        st.subheader("取得済みデータのプレビュー")
        csv_path = Path(st.session_state.result_csv_path or config_base["output"].get("csv_file", "output/results.csv"))

        if csv_path.exists():
            try:
                df = pd.read_csv(csv_path, encoding="utf-8-sig")
                st.metric("取得件数合計", f"{len(df)}件")
                st.dataframe(df, use_container_width=True, height=500)

                with open(csv_path, "rb") as f:
                    st.download_button(
                        label="📥 CSV をダウンロード",
                        data=f.read(),
                        file_name=csv_path.name,
                        mime="text/csv",
                    )
            except Exception as e:
                st.error(f"CSV 読み込みエラー: {e}")
        else:
            st.info("まだ実行していないか、出力ファイルがありません。")

    # ─── タブ3: 進捗・ログ ────────────────────────────
    with tabs[2]:
        st.subheader("進捗ファイル (progress.json)")
        prog_path = ROOT / config_base["output"].get("progress_file", "progress.json")
        if prog_path.exists():
            try:
                with open(prog_path, encoding="utf-8") as f:
                    prog_data = json.load(f)
                st.json(prog_data)
            except Exception as e:
                st.error(f"進捗ファイル読み込みエラー: {e}")
        else:
            st.info("進捗ファイルがありません（未実行または全完了済み）。")

        st.subheader("最新ログ (直近100行)")
        log_path = ROOT / config_base["output"].get("log_file", "logs/scraper.log")
        if log_path.exists():
            try:
                with open(log_path, encoding="utf-8") as f:
                    lines = f.readlines()
                last_100 = "".join(lines[-100:])
                st.code(last_100, language=None)
            except Exception as e:
                st.error(f"ログ読み込みエラー: {e}")
        else:
            st.info("ログファイルがありません（未実行）。")

        if st.button("🔃 更新"):
            st.rerun()


if __name__ == "__main__":
    main()
