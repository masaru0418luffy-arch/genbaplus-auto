# 現場Plus 自動投稿アプリ

## 開発環境での起動

```bash
cd genbaplus-desktop
npm install
npm start
```

## アプリのビルド（納品用）

```bash
# Mac (.app)
npm run build:mac

# Windows (.exe)
npm run build:win

# 両方同時
npm run build:all
```

ビルド後は `dist/` フォルダに成果物が作成されます。

## 使い方（お客様向け）

1. アプリを起動すると、メニューバー（Mac）またはタスクトレイ（Windows）にアイコンが表示されます
2. アイコンをクリック → **「設定」** でログイン情報を入力・保存
3. 毎週金曜14:50に確認ウィンドウが自動で表示されます
4. 内容を確認（必要なら編集）して「投稿する」をクリック

## ファイル構成

```
genbaplus-desktop/
├── src/
│   ├── main.js          # メインプロセス（トレイ・スケジューラー）
│   ├── preload.js       # IPC橋渡し
│   ├── automation.js    # 現場Plus自動操作
│   └── templates.js     # メッセージテンプレート
├── renderer/
│   ├── confirm/         # 投稿確認ウィンドウ
│   └── settings/        # 設定画面
├── assets/              # アイコン画像を配置
└── package.json
```

## アイコンの準備（ビルド前に必要）

- `assets/icon.icns` — Mac用アイコン（1024×1024 PNG → icns変換）
- `assets/icon.ico`  — Windows用アイコン
- `assets/tray-icon.png` — メニューバー用（16×16 PNG、黒または白）
