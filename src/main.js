const { app, BrowserWindow, Tray, Menu, ipcMain, Notification, nativeImage, dialog, shell } = require('electron');
const path = require('path');
const fs = require('fs');
const { spawn } = require('child_process');
const cron = require('node-cron');
const Store = require('electron-store');
const { generateWeeklyMessage, generateMonthlyMessage } = require('./templates');
const { postToGenbaPlus } = require('./automation');
const scraperSetup = require('./scraper-setup');

// scraper ウィンドウ管理
let scraperWindow = null;
let scraperProcess = null;

// 後方互換用（開発中は旧パスを使う）
const SCRAPER_DIR = scraperSetup.CODE_DIR;

// 設定の永続化
const store = new Store({
  defaults: {
    genbaplus: {
      url: 'https://apg.kensetsu-cloud.jp',
      tenantId: 'X572D51',
      loginId: '',
      password: ''
    },
    schedule: {
      weeklyBaseDate: '2026-07-03', // 週次の基準日（4週間ごと）
      hour: 14,
      minute: 50
    }
  }
});

let tray = null;
let confirmWindow = null;
let settingsWindow = null;
let pendingPost = null; // 確認待ちの投稿データ

// -------------------------------------------------------
// アプリ初期化
// -------------------------------------------------------
app.whenReady().then(() => {
  app.setName('現場Plus自動投稿');

  // Dockアイコンを非表示（トレイアプリとして動作）
  if (process.platform === 'darwin') {
    app.dock.hide();
  }

  createTray();
  startScheduler();
});

app.on('window-all-closed', (e) => {
  // ウィンドウを全部閉じてもアプリを終了しない（トレイで動き続ける）
  e.preventDefault();
});

// -------------------------------------------------------
// システムトレイ
// -------------------------------------------------------
function createTray() {
  const iconPath = path.join(__dirname, '..', 'assets', 'tray-icon.png');
  const icon = nativeImage.createFromPath(iconPath).resize({ width: 16, height: 16 });
  tray = new Tray(icon);
  tray.setToolTip('現場Plus自動投稿');
  updateTrayMenu();
}

function updateTrayMenu() {
  const config = store.get('genbaplus');
  const isConfigured = config.loginId && config.password;

  const menu = Menu.buildFromTemplate([
    {
      label: '現場Plus自動投稿',
      enabled: false
    },
    { type: 'separator' },
    {
      label: isConfigured ? '✅ 設定済み' : '⚠️ 未設定',
      enabled: false
    },
    {
      label: '今すぐ週次投稿を確認',
      click: () => showConfirmWindow('weekly')
    },
    {
      label: '今すぐ月次投稿を確認',
      click: () => showConfirmWindow('monthly')
    },
    { type: 'separator' },
    {
      label: '設定',
      click: () => openSettingsWindow()
    },
    { type: 'separator' },
    {
      label: '📋 営業リスト抽出',
      click: () => openScraperWindow()
    },
    { type: 'separator' },
    {
      label: '終了',
      click: () => app.exit(0)
    }
  ]);

  tray.setContextMenu(menu);
}

// -------------------------------------------------------
// スケジューラー
// -------------------------------------------------------
function startScheduler() {
  const { hour, minute, weeklyBaseDate } = store.get('schedule');

  // 毎週金曜日に実行
  cron.schedule(`${minute} ${hour} * * 5`, async () => {
    const today = new Date();
    const isLastFriday = isLastFridayOfMonth(today);
    const isWeekly4 = isEvery4WeekFriday(today, weeklyBaseDate);

    if (isLastFriday) {
      showConfirmWindow('monthly');
    } else if (isWeekly4) {
      showConfirmWindow('weekly');
    }
    // どちらでもない週はスキップ
  }, { timezone: 'Asia/Tokyo' });
}

function isLastFridayOfMonth(date) {
  const nextWeek = new Date(date);
  nextWeek.setDate(date.getDate() + 7);
  return date.getMonth() !== nextWeek.getMonth();
}

function isEvery4WeekFriday(date, baseDateStr) {
  const base = new Date(baseDateStr);
  const diffMs = date - base;
  const diffDays = Math.round(diffMs / (1000 * 60 * 60 * 24));
  return diffDays >= 0 && diffDays % 28 === 0;
}

// -------------------------------------------------------
// 確認ウィンドウ
// -------------------------------------------------------
async function showConfirmWindow(type) {
  const config = store.get('genbaplus');

  if (!config.loginId || !config.password) {
    showNotification('設定が必要です', 'トレイアイコン → 設定 でログイン情報を入力してください');
    return;
  }

  // メッセージ生成
  const message = type === 'weekly'
    ? await generateWeeklyMessage()
    : await generateMonthlyMessage();

  const title = type === 'weekly'
    ? '【全体連絡】写真格納・進捗報告のお願い'
    : '【全体連絡】出荷証明書の格納について';

  pendingPost = { type, title, message };

  // 通知を出す
  showNotification(
    '📋 現場Plus投稿の確認',
    `${type === 'weekly' ? '週次' : '月次'}メッセージの確認が必要です。クリックして確認してください。`
  );

  // 確認ウィンドウを開く
  if (confirmWindow && !confirmWindow.isDestroyed()) {
    confirmWindow.focus();
  } else {
    confirmWindow = new BrowserWindow({
      width: 620,
      height: 600,
      title: '投稿内容の確認',
      resizable: false,
      alwaysOnTop: true,
      webPreferences: {
        preload: path.join(__dirname, 'preload.js'),
        contextIsolation: true
      }
    });
    confirmWindow.loadFile(path.join(__dirname, '..', 'renderer', 'confirm', 'index.html'));
    confirmWindow.once('ready-to-show', () => {
      confirmWindow.show();
      confirmWindow.webContents.send('set-post-data', { title, message, type });
    });
  }
}

// -------------------------------------------------------
// 設定ウィンドウ
// -------------------------------------------------------
function openSettingsWindow() {
  if (settingsWindow && !settingsWindow.isDestroyed()) {
    settingsWindow.focus();
    return;
  }

  settingsWindow = new BrowserWindow({
    width: 520,
    height: 680,
    title: '設定',
    resizable: true,
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true
    }
  });

  settingsWindow.loadFile(path.join(__dirname, '..', 'renderer', 'settings', 'index.html'));
  settingsWindow.once('ready-to-show', () => {
    settingsWindow.show();
    settingsWindow.webContents.send('load-settings', store.get('genbaplus'));
  });
}

// -------------------------------------------------------
// IPC（ウィンドウとのやりとり）
// -------------------------------------------------------

// 確認ウィンドウ → 投稿実行
ipcMain.on('post-confirmed', async (event, editedMessage) => {
  if (!pendingPost) return;

  const { title, type } = pendingPost;
  const finalMessage = editedMessage || pendingPost.message;
  const config = store.get('genbaplus');

  if (confirmWindow && !confirmWindow.isDestroyed()) {
    confirmWindow.webContents.send('posting-started');
  }

  try {
    await postToGenbaPlus(config, title, finalMessage);

    if (confirmWindow && !confirmWindow.isDestroyed()) {
      confirmWindow.webContents.send('posting-success');
    }
    showNotification('✅ 投稿完了', `現場Plusへの${type === 'weekly' ? '週次' : '月次'}投稿が完了しました`);
  } catch (err) {
    if (confirmWindow && !confirmWindow.isDestroyed()) {
      confirmWindow.webContents.send('posting-error', err.message);
    }
    showNotification('❌ 投稿失敗', err.message);
  } finally {
    pendingPost = null;
  }
});

// 確認ウィンドウ → キャンセル
ipcMain.on('post-cancelled', () => {
  if (confirmWindow && !confirmWindow.isDestroyed()) {
    confirmWindow.close();
  }
  pendingPost = null;
});

// 設定保存
ipcMain.on('save-settings', (event, settings) => {
  store.set('genbaplus', settings);
  updateTrayMenu();
  if (settingsWindow && !settingsWindow.isDestroyed()) {
    settingsWindow.webContents.send('settings-saved');
  }
});

// 設定読み込み（レンダラーから要求）
ipcMain.handle('get-settings', () => store.get('genbaplus'));

// -------------------------------------------------------
// 通知
// -------------------------------------------------------
function showNotification(title, body) {
  if (Notification.isSupported()) {
    new Notification({ title, body }).show();
  }
}

// -------------------------------------------------------
// 営業リスト抽出ウィンドウ
// -------------------------------------------------------
function openScraperWindow() {
  if (scraperWindow && !scraperWindow.isDestroyed()) {
    scraperWindow.focus();
    return;
  }
  scraperWindow = new BrowserWindow({
    width: 1100,
    height: 720,
    minWidth: 800,
    minHeight: 560,
    title: '営業リスト抽出',
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
    },
  });
  scraperWindow.loadFile(path.join(__dirname, '..', 'renderer', 'scraper', 'index.html'));
  scraperWindow.on('closed', () => {
    scraperWindow = null;
    if (scraperProcess) { scraperProcess.kill(); scraperProcess = null; }
  });
}

// -------------------------------------------------------
// Scraper IPC ハンドラ
// -------------------------------------------------------

const send = (channel, msg) => {
  if (scraperWindow && !scraperWindow.isDestroyed()) {
    scraperWindow.webContents.send(channel, msg);
  }
};

// 初回セットアップ確認
ipcMain.handle('scraper-check-setup', () => scraperSetup.isReady());

// 初回セットアップ実行
ipcMain.on('scraper-run-setup', async () => {
  try {
    await scraperSetup.setup((step, pct) => {
      send('scraper-setup-progress', { step, pct });
    });
    send('scraper-setup-done', null);
  } catch (err) {
    send('scraper-setup-error', err.message);
  }
});

// Python scraper 起動
ipcMain.on('scraper-start', (event, params) => {
  if (scraperProcess) {
    scraperProcess.kill();
    scraperProcess = null;
  }

  const { python, script, userDir, envPath } = scraperSetup.getRunParams();

  // 一時 config を userDir に書き出す
  const tmpConfigPath = path.join(userDir, '_tmp_config.yaml');
  fs.writeFileSync(tmpConfigPath, buildTempConfig(params, userDir), 'utf-8');

  // .env と credentials.json を userDir から読むよう環境変数を設定
  const env = {
    ...process.env,
    DOTENV_PATH: envPath,
  };

  scraperProcess = spawn(python, [script, '--config', tmpConfigPath], {
    cwd: scraperSetup.CODE_DIR,
    env,
  });

  let outputBuffer = '';

  scraperProcess.stdout.on('data', (data) => {
    const lines = (outputBuffer + data.toString()).split('\n');
    outputBuffer = lines.pop();
    lines.forEach(line => { if (line.trim()) send('scraper-log', line.trim()); });
  });

  scraperProcess.stderr.on('data', (data) => {
    data.toString().split('\n').filter(l => l.trim())
      .forEach(line => send('scraper-log', '⚠️ ' + line));
  });

  scraperProcess.on('close', () => {
    scraperProcess = null;
    try { fs.unlinkSync(tmpConfigPath); } catch {}
    const csvPath = path.join(userDir, 'output', 'results.csv');
    const rows = readCSV(csvPath);
    const summary = readSummaryFromLog(userDir);
    summary.rows = rows.slice(-100);
    summary.csvContent = fs.existsSync(csvPath) ? fs.readFileSync(csvPath, 'utf-8') : '';
    send('scraper-done', summary);
  });

  scraperProcess.on('error', (err) => {
    scraperProcess = null;
    send('scraper-error', `Python 起動エラー: ${err.message}`);
  });
});

// 停止
ipcMain.on('scraper-stop', () => {
  if (scraperProcess) { scraperProcess.kill('SIGINT'); scraperProcess = null; }
});

// 進捗リセット
ipcMain.on('scraper-reset-progress', () => {
  const { userDir } = scraperSetup.getRunParams();
  const p = path.join(userDir, 'progress.json');
  const init = { version: 1, searches: [], completed_urls: [], last_run_at: null, interrupted: false, interrupt_reason: null };
  fs.mkdirSync(userDir, { recursive: true });
  fs.writeFileSync(p, JSON.stringify(init, null, 2), 'utf-8');
});

// Supabase 設定の保存・読み込み
ipcMain.on('scraper-save-settings', (event, settings) => {
  const { userDir } = scraperSetup.getRunParams();
  fs.mkdirSync(userDir, { recursive: true });
  const envPath = path.join(userDir, '.env');
  const content = [
    `SUPABASE_URL=${settings.supabaseUrl || ''}`,
    `SUPABASE_ANON_KEY=${settings.supabaseKey || ''}`,
  ].join('\n') + '\n';
  fs.writeFileSync(envPath, content, 'utf-8');
});

ipcMain.on('scraper-get-settings', () => {
  const { userDir } = scraperSetup.getRunParams();
  const envPath = path.join(userDir, '.env');
  const settings = { supabaseUrl: '', supabaseKey: '' };
  if (fs.existsSync(envPath)) {
    fs.readFileSync(envPath, 'utf-8').split('\n').forEach(line => {
      const [k, ...rest] = line.split('=');
      const v = rest.join('=').trim();
      if (k === 'SUPABASE_URL') settings.supabaseUrl = v;
      if (k === 'SUPABASE_ANON_KEY') settings.supabaseKey = v;
    });
  }
  send('scraper-settings', settings);
});

// CSV ダウンロード（保存ダイアログ）
ipcMain.on('scraper-download-csv', async (event, content) => {
  const { filePath } = await dialog.showSaveDialog({
    title: 'CSV を保存',
    defaultPath: `results_${new Date().toISOString().slice(0,10)}.csv`,
    filters: [{ name: 'CSV', extensions: ['csv'] }],
  });
  if (filePath) fs.writeFileSync(filePath, '﻿' + content, 'utf-8');
});

ipcMain.on('scraper-open-csv-folder', () => {
  const { userDir } = scraperSetup.getRunParams();
  shell.openPath(path.join(userDir, 'output'));
});

// -------------------------------------------------------
// ヘルパー関数
// -------------------------------------------------------

// YAML の文字列値をシングルクォートで安全にエスケープする
function yamlStr(s) {
  return "'" + String(s).replace(/'/g, "''") + "'";
}

// 一時 config.yaml を生成（YAML 特殊文字に対応、userDir の絶対パスで出力先を指定）
function buildTempConfig(params, userDir) {
  const ud = userDir || scraperSetup.USER_DIR;
  const kw = params.keywords.map(k => `  - ${yamlStr(k)}`).join('\n');
  const ar = params.areas.map(a => `  - ${yamlStr(a)}`).join('\n');
  return [
    'sheets:',
    `  spreadsheet_id: '1gd4-WX_57Ctb2jLO9v3fuGFCqUi6c_zN1wWv3z1vGcU'`,
    'search:',
    `  keywords:\n${kw}`,
    `  areas:\n${ar}`,
    `  max_items_per_run: ${parseInt(params.maxItems) || 30}`,
    'filters:',
    `  max_review_count: ${parseInt(params.maxReview) || 10}`,
    '  require_photo_within_year: true',
    'delays:',
    `  min_seconds: ${parseFloat(params.delayMin) || 5}`,
    `  max_seconds: ${parseFloat(params.delayMax) || 15}`,
    '  cooldown_every_n_items: 10',
    '  cooldown_min_seconds: 60',
    '  cooldown_max_seconds: 120',
    'output:',
    `  csv_file: ${yamlStr(path.join(ud, 'output', 'results.csv'))}`,
    `  progress_file: ${yamlStr(path.join(ud, 'progress.json'))}`,
    `  log_file: ${yamlStr(path.join(ud, 'logs', 'scraper.log'))}`,
    '  log_level: INFO',
  ].join('\n');
}

// RFC 4180 準拠の簡易 CSV パーサー（カンマ・改行を含むフィールドに対応）
function readCSV(csvPath) {
  if (!fs.existsSync(csvPath)) return [];
  try {
    const raw = fs.readFileSync(csvPath, 'utf-8').replace(/^﻿/, ''); // BOM 除去
    const rows = parseCSVRFC(raw);
    if (rows.length < 2) return [];
    const headers = rows[0];
    return rows.slice(1).filter(r => r.some(c => c)).map(vals => {
      const obj = {};
      headers.forEach((h, i) => { obj[h] = vals[i] || ''; });
      return obj;
    });
  } catch { return []; }
}

function parseCSVRFC(text) {
  const rows = [];
  let row = [], cell = '', inQuote = false;
  for (let i = 0; i < text.length; i++) {
    const c = text[i];
    if (inQuote) {
      if (c === '"' && text[i + 1] === '"') { cell += '"'; i++; }
      else if (c === '"') { inQuote = false; }
      else { cell += c; }
    } else {
      if (c === '"') { inQuote = true; }
      else if (c === ',') { row.push(cell); cell = ''; }
      else if (c === '\n') { row.push(cell); rows.push(row); row = []; cell = ''; }
      else if (c !== '\r') { cell += c; }
    }
  }
  if (cell || row.length) { row.push(cell); rows.push(row); }
  return rows;
}

function readSummaryFromLog(userDir) {
  const ud = userDir || scraperSetup.USER_DIR;
  const logPath = path.join(ud, 'logs', 'scraper.log');
  const summary = { new_count: 0, total_count: 0, filtered_count: 0, error_count: 0, captcha_interrupted: false };
  try {
    summary.total_count = readCSV(path.join(ud, 'output', 'results.csv')).length;
    if (fs.existsSync(logPath)) {
      const log = fs.readFileSync(logPath, 'utf-8');
      const last = (pattern) => {
        const all = log.match(pattern);
        return all ? parseInt(all[all.length - 1].match(/\d+/)[0]) : 0;
      };
      summary.new_count      = last(/新規取得件数\s*:\s*\d+/g);
      summary.filtered_count = last(/フィルタ除外\s*:\s*\d+/g);
      summary.error_count    = last(/取得失敗\s*:\s*\d+/g);
      summary.captcha_interrupted = log.includes('CAPTCHA により途中終了');
    }
  } catch {}
  return summary;
}
