"""
Google スプレッドシート書き込みモジュール

セットアップ手順:
  1. Google Cloud Console でプロジェクト作成 / Sheets API 有効化
  2. サービスアカウントを作成し JSON キーを credentials.json として保存
  3. スプレッドシートをサービスアカウントのメールアドレスに共有（編集者権限）
  4. config.yaml の sheets.spreadsheet_id にスプレッドシート ID を設定
"""

from __future__ import annotations

import logging
import time
from dataclasses import asdict
from pathlib import Path
from typing import Optional

logger = logging.getLogger("gmaps_scraper.sheets")

SPREADSHEET_ID = "1gd4-WX_57Ctb2jLO9v3fuGFCqUi6c_zN1wWv3z1vGcU"
CREDENTIALS_FILE = Path(__file__).parent / "credentials.json"
SHEET_NAME = "営業リスト"

HEADER = [
    "店舗名", "業種", "住所", "電話番号", "Instagram URL",
    "ウェブサイト URL", "口コミ件数", "最新写真投稿日",
    "ドメイン取得日", "Google マップ URL", "取得日時",
]

# StoreData フィールド名 → スプレッドシート列の対応
FIELD_ORDER = [
    "company_name", "industry", "address", "phone", "instagram_url",
    "website_url", "review_count", "last_photo_posted_date",
    "website_domain_creation_date", "google_maps_url", "scraped_at",
]


def _get_client():
    """gspread クライアントを返す。credentials.json がなければ None を返す。"""
    if not CREDENTIALS_FILE.exists():
        return None
    try:
        import gspread
        from google.oauth2.service_account import Credentials

        scopes = [
            "https://www.googleapis.com/auth/spreadsheets",
        ]
        creds = Credentials.from_service_account_file(str(CREDENTIALS_FILE), scopes=scopes)
        return gspread.authorize(creds)
    except Exception as e:
        logger.error(f"Google Sheets クライアント初期化失敗: {e}")
        return None


class GoogleSheetsWriter:
    """スプレッドシートに1行ずつ追記する。既存行の重複は google_maps_url で判定。"""

    def __init__(self, spreadsheet_id: str = SPREADSHEET_ID):
        self.spreadsheet_id = spreadsheet_id
        self._gc = _get_client()
        if not self._gc:
            raise RuntimeError(
                "credentials.json が見つかりません。\n"
                "Google Cloud Console でサービスアカウントを作成し、\n"
                f"{CREDENTIALS_FILE} として保存してください。"
            )
        self._sheet = self._open_sheet()

    def _open_sheet(self):
        sh = self._gc.open_by_key(self.spreadsheet_id)
        # シート名が存在しなければ作成
        try:
            sheet = sh.worksheet(SHEET_NAME)
        except Exception:
            sheet = sh.add_worksheet(title=SHEET_NAME, rows=5000, cols=len(HEADER))

        # ヘッダー行が空ならセット
        existing = sheet.row_values(1)
        if not existing or existing[0] != HEADER[0]:
            sheet.insert_row(HEADER, 1)
            logger.info(f"スプレッドシートにヘッダー行を追加しました")

        return sheet

    def write_row(self, store) -> None:
        d = asdict(store)
        row = [str(d.get(f, "") or "") for f in FIELD_ORDER]
        try:
            self._sheet.append_row(row, value_input_option="USER_ENTERED")
            logger.debug(f"Sheets 書き込み: {d.get('company_name')}")
        except Exception as e:
            logger.error(f"Sheets 書き込みエラー: {e}")
            raise

    def count_rows(self) -> int:
        try:
            return max(0, len(self._sheet.get_all_values()) - 1)
        except Exception:
            return 0

    def is_url_saved(self, google_maps_url: str) -> bool:
        try:
            col_idx = FIELD_ORDER.index("google_maps_url") + 1
            urls = self._sheet.col_values(col_idx)[1:]  # ヘッダーを除く
            return google_maps_url in urls
        except Exception:
            return False


def is_available() -> bool:
    """credentials.json が存在し gspread が使えるか確認する。"""
    return CREDENTIALS_FILE.exists() and _get_client() is not None
