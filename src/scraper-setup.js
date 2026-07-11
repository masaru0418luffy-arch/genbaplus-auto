'use strict';
/**
 * スクレイパー Python 環境のセットアップ管理
 * - 初回起動時に venv 作成 + pip install を自動実行
 * - ユーザーデータは ~/Library/Application Support/現場Plus自動投稿/gmaps-scraper/ に保存
 */

const { execFile, execFileSync } = require('child_process');
const path = require('path');
const fs = require('fs');
const { app } = require('electron');

// ----------------------------------------------------------------
// パス定義
// ----------------------------------------------------------------

/** アプリに同梱された gmaps-scraper ソースコード（読み取り専用） */
const CODE_DIR = app.isPackaged
  ? path.join(process.resourcesPath, 'gmaps-scraper')
  : path.join(__dirname, '..', 'gmaps-scraper');

/** ユーザーデータ置き場（書き込み可能） */
const USER_DIR = path.join(app.getPath('userData'), 'gmaps-scraper');

/** Python venv */
const VENV_DIR = path.join(USER_DIR, '.venv');
const PYTHON   = path.join(VENV_DIR, 'bin', 'python3');
const PIP      = path.join(VENV_DIR, 'bin', 'pip3');

// ----------------------------------------------------------------
// 公開 API
// ----------------------------------------------------------------

/** セットアップ済みか（venv が存在するか） */
function isReady() {
  return fs.existsSync(PYTHON);
}

/**
 * 初回セットアップを実行する。
 * @param {(step: string, pct: number) => void} onProgress - 進捗コールバック
 * @returns {Promise<void>}
 */
async function setup(onProgress = () => {}) {
  fs.mkdirSync(USER_DIR, { recursive: true });

  // ── Step 1: 設定ファイルをユーザーデータにコピー（初回のみ） ──
  onProgress('設定ファイルを初期化しています...', 5);
  _copyIfNotExists(path.join(CODE_DIR, 'config.yaml'),    path.join(USER_DIR, 'config.yaml'));
  _copyIfNotExists(path.join(CODE_DIR, '.env.example'),   path.join(USER_DIR, '.env'));
  ['output', 'logs'].forEach(d => fs.mkdirSync(path.join(USER_DIR, d), { recursive: true }));

  // ── Step 2: Python 3 を探す ──
  onProgress('Python を確認しています...', 10);
  const python3 = _findPython3();
  if (!python3) throw new Error('Python 3.10 以上が見つかりません。\nhttps://www.python.org からインストールしてください。');

  // ── Step 3: venv 作成 ──
  onProgress('Python 仮想環境を作成しています...', 20);
  await _exec(python3, ['-m', 'venv', VENV_DIR]);

  // ── Step 4: pip install ──
  onProgress('パッケージをインストールしています（数分かかります）...', 35);
  const req = path.join(CODE_DIR, 'requirements.txt');
  await _exec(PIP, ['install', '-r', req, '--quiet', '--disable-pip-version-check']);

  // ── Step 5: Playwright ブラウザ ──
  onProgress('Chromium ブラウザをインストールしています（初回のみ・100MB）...', 70);
  const playwrightBin = path.join(VENV_DIR, 'bin', 'playwright');
  await _exec(playwrightBin, ['install', 'chromium']);

  onProgress('セットアップ完了！', 100);
}

/**
 * スクレイパー実行用のパラメータを返す
 */
function getRunParams() {
  // パッケージ済み: CODE_DIR のスクリプト + USER_DIR のデータ
  // 開発中: 両方 gmaps-scraper/ を使う
  return {
    python: isReady() ? PYTHON : _findPython3() || 'python3',
    script: path.join(CODE_DIR, 'scraper.py'),
    cwd:    CODE_DIR,
    userDir: USER_DIR,
    configPath: path.join(USER_DIR, 'config.yaml'),
    progressPath: path.join(USER_DIR, 'progress.json'),
    csvPath: path.join(USER_DIR, 'output', 'results.csv'),
    logPath: path.join(USER_DIR, 'logs', 'scraper.log'),
    envPath: path.join(USER_DIR, '.env'),
    credPath: path.join(USER_DIR, 'credentials.json'),
  };
}

module.exports = { isReady, setup, getRunParams, CODE_DIR, USER_DIR };

// ----------------------------------------------------------------
// 内部ヘルパー
// ----------------------------------------------------------------

function _copyIfNotExists(src, dst) {
  if (!fs.existsSync(dst) && fs.existsSync(src)) {
    fs.copyFileSync(src, dst);
  }
}

function _findPython3() {
  const candidates = [
    '/opt/homebrew/bin/python3.12',
    '/opt/homebrew/bin/python3.11',
    '/opt/homebrew/bin/python3.10',
    '/opt/homebrew/bin/python3',
    '/usr/local/bin/python3.12',
    '/usr/local/bin/python3.11',
    '/usr/local/bin/python3',
    '/usr/bin/python3',
  ];
  for (const p of candidates) {
    if (fs.existsSync(p)) return p;
  }
  // PATH から探す
  try { execFileSync('python3', ['--version']); return 'python3'; } catch {}
  return null;
}

function _exec(bin, args) {
  return new Promise((resolve, reject) => {
    const proc = execFile(bin, args, { env: { ...process.env } }, (err) => {
      if (err) reject(err);
      else resolve();
    });
  });
}
