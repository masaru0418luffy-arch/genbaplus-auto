const { app, BrowserWindow, Tray, Menu, ipcMain, Notification, nativeImage } = require('electron');
const path = require('path');
const cron = require('node-cron');
const Store = require('electron-store');
const { generateWeeklyMessage, generateMonthlyMessage } = require('./templates');
const { postToGenbaPlus } = require('./automation');

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
