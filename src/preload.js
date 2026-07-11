const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('electronAPI', {
  // 確認ウィンドウ用
  onSetPostData:    (cb) => ipcRenderer.on('set-post-data',     (_, data) => cb(data)),
  onPostingStarted: (cb) => ipcRenderer.on('posting-started',   () => cb()),
  onPostingSuccess: (cb) => ipcRenderer.on('posting-success',   () => cb()),
  onPostingError:   (cb) => ipcRenderer.on('posting-error',     (_, msg) => cb(msg)),
  postConfirmed:    (msg) => ipcRenderer.send('post-confirmed', msg),
  postCancelled:    ()  => ipcRenderer.send('post-cancelled'),

  // 設定画面用
  onLoadSettings:   (cb) => ipcRenderer.on('load-settings',    (_, data) => cb(data)),
  onSettingsSaved:  (cb) => ipcRenderer.on('settings-saved',   () => cb()),
  saveSettings:     (s)  => ipcRenderer.send('save-settings',  s),
  getSettings:      ()   => ipcRenderer.invoke('get-settings'),

  // 営業リスト抽出ウィンドウ用
  startScraper:         (params)  => ipcRenderer.send('scraper-start', params),
  stopScraper:          ()        => ipcRenderer.send('scraper-stop'),
  resetProgress:        ()        => ipcRenderer.send('scraper-reset-progress'),
  onScraperLog:         (cb)      => ipcRenderer.on('scraper-log',      (_, msg) => cb(msg)),
  onScraperDone:        (cb)      => ipcRenderer.on('scraper-done',     (_, s)   => cb(s)),
  onScraperError:       (cb)      => ipcRenderer.on('scraper-error',    (_, msg) => cb(msg)),
  saveScraperSettings:  (s)       => ipcRenderer.send('scraper-save-settings', s),
  getScraperSettings:   ()        => ipcRenderer.send('scraper-get-settings'),
  onScraperSettings:    (cb)      => ipcRenderer.on('scraper-settings', (_, s)   => cb(s)),
  downloadCSV:          (content) => ipcRenderer.send('scraper-download-csv', content),
  openCSVFolder:        ()        => ipcRenderer.send('scraper-open-csv-folder'),
});
