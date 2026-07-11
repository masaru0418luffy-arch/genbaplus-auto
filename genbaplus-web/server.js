const express = require('express');
const cron = require('node-cron');
const path = require('path');
const fs = require('fs');
const { chromium } = require('playwright');
const { generateWeeklyMessage, generateMonthlyMessage } = require('./src/templates');

const app = express();
const PORT = process.env.PORT || 3000;
const DATA_FILE = path.join(__dirname, 'data', 'app-data.json');
const ADMIN_PASSWORD = process.env.ADMIN_PASSWORD || 'genbaplus2024';

// data/ ディレクトリを作成
if (!fs.existsSync(path.join(__dirname, 'data'))) {
  fs.mkdirSync(path.join(__dirname, 'data'), { recursive: true });
}

// -------------------------------------------------------
// データ永続化
// -------------------------------------------------------
function loadData() {
  try {
    return JSON.parse(fs.readFileSync(DATA_FILE, 'utf8'));
  } catch {
    return {
      settings: {
        url: 'https://apg.kensetsu-cloud.jp',
        tenantId: '',
        loginId: '',
        password: '',
        weeklyBaseDate: '2026-07-03'
      },
      pendingPost: null,
      lastPost: null
    };
  }
}

function saveData(data) {
  fs.writeFileSync(DATA_FILE, JSON.stringify(data, null, 2));
}

// -------------------------------------------------------
// ミドルウェア
// -------------------------------------------------------
app.use(express.json());
app.use(express.static(path.join(__dirname, 'public')));

// -------------------------------------------------------
// API: 設定
// -------------------------------------------------------
app.get('/api/settings', (req, res) => {
  const data = loadData();
  const s = data.settings;
  res.json({
    url: s.url,
    tenantId: s.tenantId,
    loginId: s.loginId,
    password: s.password,  // 設定ページ表示用
    weeklyBaseDate: s.weeklyBaseDate
  });
});

app.post('/api/settings', (req, res) => {
  const { adminPassword, ...settings } = req.body;
  if (adminPassword !== ADMIN_PASSWORD) {
    return res.status(401).json({ error: '管理パスワードが違います' });
  }
  const data = loadData();
  data.settings = { ...data.settings, ...settings };
  saveData(data);
  res.json({ ok: true });
});

// -------------------------------------------------------
// API: 投稿管理
// -------------------------------------------------------
app.get('/api/pending', (req, res) => {
  const data = loadData();
  res.json({
    pending: data.pendingPost,
    lastPost: data.lastPost
  });
});

// 確認して投稿
app.post('/api/confirm', async (req, res) => {
  const { message, title } = req.body;
  const data = loadData();

  if (!data.pendingPost) {
    return res.status(400).json({ error: '投稿待ちのデータがありません' });
  }
  if (!data.settings.loginId || !data.settings.password) {
    return res.status(400).json({ error: 'ログイン情報が設定されていません。設定ページで入力してください。' });
  }

  const finalTitle = title || data.pendingPost.title;
  const finalMessage = message || data.pendingPost.message;

  try {
    await postToGenbaPlus(data.settings, finalTitle, finalMessage);
    data.lastPost = {
      title: finalTitle,
      message: finalMessage,
      type: data.pendingPost.type,
      postedAt: new Date().toISOString()
    };
    data.pendingPost = null;
    saveData(data);
    res.json({ ok: true });
  } catch (err) {
    console.error('投稿エラー:', err.message);
    res.status(500).json({ error: err.message });
  }
});

// キャンセル
app.post('/api/cancel', (req, res) => {
  const data = loadData();
  data.pendingPost = null;
  saveData(data);
  res.json({ ok: true });
});

// 手動トリガー（テスト用）
app.post('/api/trigger', async (req, res) => {
  const { type } = req.body;
  try {
    await triggerPost(type || 'weekly');
    res.json({ ok: true });
  } catch (err) {
    res.status(500).json({ error: err.message });
  }
});

// -------------------------------------------------------
// 投稿トリガー（スケジューラーから呼ばれる）
// -------------------------------------------------------
async function triggerPost(type) {
  const message = type === 'weekly'
    ? generateWeeklyMessage()
    : generateMonthlyMessage();

  const title = type === 'weekly'
    ? '【全体連絡】写真格納・進捗報告のお願い'
    : '【全体連絡】出荷証明書の格納について';

  const data = loadData();
  data.pendingPost = {
    type,
    title,
    message,
    createdAt: new Date().toISOString()
  };
  saveData(data);
  console.log(`[${new Date().toLocaleString('ja-JP')}] ${type} 投稿が確認待ちになりました`);
}

// -------------------------------------------------------
// スケジューラー
// -------------------------------------------------------
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

function startScheduler() {
  // 毎週金曜 14:50 JST
  cron.schedule('50 14 * * 5', async () => {
    const data = loadData();
    const today = new Date();
    const { weeklyBaseDate } = data.settings;

    const isLastFriday = isLastFridayOfMonth(today);
    const isWeekly4 = isEvery4WeekFriday(today, weeklyBaseDate || '2026-07-03');

    if (isLastFriday) {
      await triggerPost('monthly');
    } else if (isWeekly4) {
      await triggerPost('weekly');
    }
  }, { timezone: 'Asia/Tokyo' });

  console.log('スケジューラー起動: 毎週金曜 14:50 JST');
}

// -------------------------------------------------------
// 現場Plus 自動投稿
// -------------------------------------------------------
async function postToGenbaPlus(config, title, message) {
  const browser = await chromium.launch({
    headless: true,
    args: ['--no-sandbox', '--disable-setuid-sandbox']
  });
  const context = await browser.newContext();
  const page = await context.newPage();

  try {
    // ログイン
    const loginUrl = `${config.url}/main/dyapp/t/${config.tenantId}/memberlogin`;
    console.log('ログイン:', loginUrl);
    await page.goto(loginUrl, { waitUntil: 'domcontentloaded', timeout: 30000 });

    // ログインID入力（2番目のテキスト入力）
    const textInputs = page.locator('input[type="text"], input:not([type="password"]):not([type="hidden"]):not([type="submit"])');
    await textInputs.nth(1).fill(config.loginId);
    await page.locator('input[type="password"]').fill(config.password);
    await page.locator('button[type="submit"], input[type="submit"]').first().click();
    await page.waitForLoadState('networkidle', { timeout: 15000 });
    console.log('ログイン完了');

    // 掲示板作成ページへ
    const createUrl = `${config.url}/main/dyapp/t/${config.tenantId}/member/bbs/create`;
    await page.goto(createUrl, { waitUntil: 'domcontentloaded', timeout: 15000 });
    await page.waitForLoadState('networkidle', { timeout: 10000 });
    console.log('作成ページ到達');

    // グループ選択 (BK-0028)
    const selectEl = page.locator('select').first();
    await selectEl.waitFor({ timeout: 5000 });
    const options = await selectEl.locator('option').allTextContents();
    const targetOption = options.find(o => o.includes('BK-0028') || o.includes('標準納まり'));
    if (targetOption) {
      await selectEl.selectOption({ label: targetOption });
    }

    // タイトル入力
    const titleInput = page.locator('input[name="title"], input[placeholder*="タイトル"], input[placeholder*="件名"]').first();
    await titleInput.waitFor({ timeout: 5000 });
    await titleInput.fill(title);

    // 本文入力
    const bodyInput = page.locator('textarea[name="body"], textarea[placeholder*="内容"], textarea[placeholder*="本文"]').first();
    await bodyInput.waitFor({ timeout: 5000 });
    await bodyInput.fill(message);

    // 投稿ボタンクリック
    await page.locator('button:has-text("作成"), button[type="submit"]').first().click();
    await page.waitForLoadState('networkidle', { timeout: 15000 });
    console.log('投稿完了');

  } finally {
    await browser.close();
  }
}

// -------------------------------------------------------
// サーバー起動
// -------------------------------------------------------
startScheduler();
app.listen(PORT, () => {
  console.log(`現場Plus 自動投稿サーバー起動: http://localhost:${PORT}`);
});
