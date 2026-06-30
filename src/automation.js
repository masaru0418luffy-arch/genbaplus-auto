const { BrowserWindow } = require('electron');

/**
 * 現場PlusへElectronの隠しウィンドウで自動投稿
 * Playwrightは不要 — Electronのwebcontentsで直接操作
 */
async function postToGenbaPlus(config, title, message) {
  const { url, tenantId, loginId, password } = config;

  return new Promise((resolve, reject) => {
    const win = new BrowserWindow({
      width: 1280,
      height: 800,
      show: false, // 画面には表示しない
      webPreferences: {
        contextIsolation: false,
        nodeIntegration: false
      }
    });

    const loginUrl = `${url}/main/dyapp/t/${tenantId}/memberlogin`;

    win.loadURL(loginUrl);

    win.webContents.once('did-finish-load', async () => {
      try {
        // ---- Step 1: ログイン ----
        await win.webContents.executeJavaScript(`
          (async () => {
            // 2番目のtextフィールドにログインIDを入力
            const inputs = document.querySelectorAll('input[type="text"]');
            if (inputs.length >= 2) {
              inputs[1].value = ${JSON.stringify(loginId)};
              inputs[1].dispatchEvent(new Event('input', { bubbles: true }));
            } else if (inputs.length === 1) {
              inputs[0].value = ${JSON.stringify(loginId)};
              inputs[0].dispatchEvent(new Event('input', { bubbles: true }));
            }

            // パスワード入力
            const pwInput = document.querySelector('input[type="password"]');
            if (pwInput) {
              pwInput.value = ${JSON.stringify(password)};
              pwInput.dispatchEvent(new Event('input', { bubbles: true }));
            }

            // ログインボタンをクリック
            const btn = document.querySelector('button[type="submit"]');
            if (btn) btn.click();
          })();
        `);

        // ページ遷移を待つ
        await waitForNavigation(win);

        // ---- Step 2: 投稿フォームへ移動 ----
        const createUrl = `${url}/main/dyapp/t/${tenantId}/member/bbs/create`;
        win.loadURL(createUrl);
        await waitForNavigation(win);

        // ---- Step 3: フォームに入力して投稿 ----
        await win.webContents.executeJavaScript(`
          (async () => {
            // 現場選択：「全体連絡事項」(BK-0028)
            const sel = document.querySelector('select');
            if (sel) {
              sel.value = 'BK-0028';
              sel.dispatchEvent(new Event('change', { bubbles: true }));
            }

            // 少し待って動的UIの更新を待つ
            await new Promise(r => setTimeout(r, 800));

            // タイトル入力
            const titleInput = document.querySelector('input[type="text"]');
            if (titleInput) {
              titleInput.value = ${JSON.stringify(title)};
              titleInput.dispatchEvent(new Event('input', { bubbles: true }));
            }

            // 本文入力
            const textarea = document.querySelector('textarea');
            if (textarea) {
              textarea.value = ${JSON.stringify(message)};
              textarea.dispatchEvent(new Event('input', { bubbles: true }));
            }

            // 「作成」ボタンをクリック
            // mainタグ内の「作成」テキストのリンク
            const links = document.querySelectorAll('main a, a');
            for (const link of links) {
              if (link.textContent.trim() === '作成') {
                link.click();
                break;
              }
            }
          })();
        `);

        // 投稿完了を待つ（URLが変わるまで）
        await waitForNavigation(win, 8000);

        win.close();
        resolve();
      } catch (err) {
        win.close();
        reject(err);
      }
    });

    win.webContents.on('did-fail-load', (event, errorCode, errorDescription) => {
      win.close();
      reject(new Error(`ページの読み込みに失敗しました: ${errorDescription}`));
    });
  });
}

/**
 * ページ遷移完了を待つ
 */
function waitForNavigation(win, timeout = 10000) {
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => {
      reject(new Error('ページの読み込みがタイムアウトしました'));
    }, timeout);

    win.webContents.once('did-finish-load', () => {
      clearTimeout(timer);
      setTimeout(resolve, 500); // DOMの描画を少し待つ
    });
  });
}

module.exports = { postToGenbaPlus };
