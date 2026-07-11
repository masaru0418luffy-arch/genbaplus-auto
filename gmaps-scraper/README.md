# Google マップ営業リスト自動抽出システム

業種・エリアを指定して Google マップから営業候補リスト（CSV）を自動抽出する社内ツールです。

---

## ⚠️ 重要な注意事項（必ずお読みください）

| 項目 | 説明 |
|------|------|
| **利用規約** | Google マップのスクレイピングは ToS 上のグレーゾーンです。大量・高頻度・商用の自動アクセスは規約違反となりうるため、**社内利用に限定**し、アクセス頻度を最小限に抑えた設定で運用してください。 |
| **WHOIS情報** | `website_domain_creation_date` は WHOIS 登録情報に基づきます。プライバシー保護設定のドメインでは「取得不可」となります。 |
| **CAPTCHA** | reCAPTCHA 等を検知した場合、自動突破は**行いません**。安全に停止し、次回実行から再開します。1回の実行で必ず全件取得できることは保証しません。ただし逐次保存・再開機能により、複数晩の実行を重ねることでリストは継続的に積み上がります。 |
| **バックグラウンド実行** | `scraper.py` は Playwright をヘッドレスモードで起動するため、実行中にブラウザウィンドウは表示されません。他のアプリを操作しながらバックグラウンドで動作します。 |
| **夜間自動実行** | PC がスリープしているとタスクスケジューラが起動しません。夜間実行には「スリープしない」電源設定が必要です。 |

---

## 機能

- **業種・エリア指定検索** — `config.yaml` または UI 上で複数キーワード・複数エリアを指定
- **口コミ件数フィルタ** — 指定件数以下の店舗のみ抽出（デフォルト: 10件以下）
- **写真投稿日フィルタ** — 直近1年以内に写真投稿がある店舗のみ抽出
- **WHOIS照会** — ウェブサイトのドメイン取得日を自動取得
- **Instagram URL 抽出** — プロフィールに掲載された Instagram リンクを取得
- **逐次 CSV 保存** — 1件ごとに CSV へ追記（途中停止時もデータが失われない）
- **再開機能** — 取得済み店舗をスキップして未取得分から再開
- **Streamlit UI** — 社員がブラウザから操作できる Web アプリ

---

## ファイル構成

```
gmaps-scraper/
├── scraper.py        # スクレイピング本体・CLI
├── app.py            # Streamlit UI
├── config.yaml       # 設定ファイル（キーワード・エリア・閾値・セレクタ）
├── progress.json     # 再開用の進捗管理ファイル（自動生成）
├── requirements.txt  # Python 依存パッケージ
├── README.md         # このファイル
├── output/
│   └── results.csv   # 出力 CSV（自動生成）
└── logs/
    └── scraper.log   # ログファイル（自動生成）
```

---

## セットアップ

### 1. Python 3.11 以上を確認

```bash
python --version
# Python 3.11.x 以上であること
```

### 2. 仮想環境を作成して有効化（推奨）

```bash
python -m venv .venv

# macOS / Linux
source .venv/bin/activate

# Windows
.venv\Scripts\activate
```

### 3. 依存パッケージをインストール

```bash
pip install -r requirements.txt
```

### 4. Playwright ブラウザをインストール

```bash
playwright install chromium
```

### 5. （任意）playwright-stealth をインストール

ヘッドレスブラウザの検出軽減効果があります。入れておくことを推奨します。

```bash
pip install playwright-stealth
```

---

## 使い方

### CLI モード

```bash
# config.yaml の設定で実行
python scraper.py

# キーワード・エリアを CLI 引数で上書き
python scraper.py --keyword 美容室 --area 東京都渋谷区

# 最大取得件数を指定
python scraper.py --keyword 飲食店 --area 大阪市北区 --max-items 20

# 出力先を指定
python scraper.py --output output/osaka_list.csv

# 設定ファイルを別ファイルで指定
python scraper.py --config my_config.yaml
```

### Streamlit UI モード

```bash
streamlit run app.py
```

ブラウザで `http://localhost:8501` を開きます。
社内サーバーで起動する場合は `streamlit run app.py --server.address 0.0.0.0` でアクセス可能になります。

---

## 出力 CSV の列

| 列名 | 説明 |
|------|------|
| `company_name` | 店舗名 |
| `industry` | 検索に使った業種キーワード |
| `instagram_url` | Instagram URL（なければ空） |
| `website_url` | ウェブサイト URL（なければ空） |
| `review_count` | 口コミ件数 |
| `last_photo_posted_date` | 最新写真の相対日付（例: 3週間前） |
| `website_domain_creation_date` | ドメイン取得日（WHOIS）|
| `google_maps_url` | Google マップの店舗 URL |
| `scraped_at` | 取得日時（ISO 8601） |

文字コードは **UTF-8 BOM 付き**（Excel で開いても文字化けしません）。

---

## config.yaml の主要設定

```yaml
search:
  keywords:           # 検索する業種（複数指定可）
    - 美容室
    - 飲食店
  areas:              # 検索エリア（複数指定可）
    - 東京都渋谷区
  max_items_per_run: 30   # 1回の実行で最大何件保存するか

filters:
  max_review_count: 10    # 口コミ件数の上限

delays:
  min_seconds: 5          # 各店舗間の最小待機時間（秒）
  max_seconds: 15         # 各店舗間の最大待機時間（秒）
  cooldown_every_n_items: 10   # N件ごとにクールダウンを挟む
  cooldown_min_seconds: 60     # クールダウン最小時間（秒）
  cooldown_max_seconds: 120    # クールダウン最大時間（秒）
```

---

## 夜間自動実行（タスクスケジューラ設定例）

### Windows タスクスケジューラ

1. 「タスクスケジューラ」を起動 → 「タスクの作成」
2. **全般タブ**: 名前を設定、「ユーザーがログオンしているかどうかにかかわらず実行する」を選択
3. **トリガータブ**: 「新規」→「毎日」→ 実行時刻（例: 23:00）を設定
4. **操作タブ**: 「プログラム/スクリプト」に Python パスを設定
   ```
   プログラム: C:\Users\ユーザー名\gmaps-scraper\.venv\Scripts\python.exe
   引数:       scraper.py --config config.yaml
   開始場所:   C:\Users\ユーザー名\gmaps-scraper
   ```
5. **条件タブ**: 「コンピューターをAC電源で使用している場合のみタスクを開始する」のチェックを外す
6. PC の電源設定でスリープを無効化する（「電源とスリープ」→「スリープ」→「なし」）

### macOS / Linux (cron)

```bash
# crontab を編集
crontab -e

# 毎日 23:00 に実行する例
0 23 * * * /Users/ユーザー名/gmaps-scraper/.venv/bin/python \
    /Users/ユーザー名/gmaps-scraper/scraper.py \
    --config /Users/ユーザー名/gmaps-scraper/config.yaml \
    >> /Users/ユーザー名/gmaps-scraper/logs/cron.log 2>&1
```

> **注意**: Mac はスリープ中にcronが起動しません。  
> 「システム設定」→「ロック画面」→「スリープ」をオフにするか、  
> `pmset -a sleep 0` でスリープを無効にしてください。

---

## CAPTCHA が発生したときは

1. `logs/scraper.log` に「CAPTCHA を検知しました」と記録されます
2. `progress.json` の `interrupted: true` を確認できます
3. **1〜2日おいて**から再実行してください（同じコマンドで OK）
4. `progress.json` が残っている限り、取得済み店舗をスキップして未取得分から再開します

---

## セレクタのメンテナンス

Google マップの DOM 構造は予告なく変更されます。  
取得できなくなった場合は `config.yaml` の `selectors` セクションを更新してください。

```yaml
selectors:
  store_name_list:        # 店舗名の CSS セレクタ（上から順に試す）
    - 'h1.DUwDvf'
    - 'h1[class*="fontHeadlineLarge"]'
  review_count_list:      # 口コミ件数
    - 'button[aria-label*="件の口コミ"]'
  website_link_list:      # ウェブサイトリンク
    - 'a[data-item-id="authority"]'
```

複数セレクタを上から順に試す仕組みのため、1つが壊れても残りで取得を試みます。

---

## 既知の制約・注意点

- Google マップの仕様変更により、一部の情報が取得できなくなる場合があります
- 写真投稿日は Google マップの「相対表記」のため、取得不可になることがあります
- WHOIS プライバシー保護（ドメインプロキシ等）が設定されているドメインはドメイン取得日を取得できません
- 1回の実行で全件取得が保証されているわけではありません。複数晩の実行を前提にした設計です

---

## 将来的な Google Places API 移行に向けたメモ

現在は Playwright によるスクレイピングですが、将来的に公式 Google Places API（有料）への移行も選択肢の一つです。

| 比較項目 | 本ツール（スクレイピング） | Google Places API |
|----------|--------------------------|-------------------|
| コスト | 無料（PCリソースのみ） | 有料（リクエスト課金） |
| 口コミ件数 | 全件取得可 | **最大5件まで**（制約あり） |
| 写真投稿日 | 取得可（相対日付） | **取得不可**（制約あり） |
| 安定性 | DOM変更で壊れる可能性あり | 安定 |
| ToS | グレーゾーン | 公式対応 |

口コミ件数・写真投稿日のフィルタが業務上不可欠であるため、Places API では代替が困難な点に注意してください。
