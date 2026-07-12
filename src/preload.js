const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('electronAPI', {
  // 確認ウィンドウ用
  onSetPostData:    (cb) => ipcRenderer.on('set-post-data',     (_, data) => cb(data)),
  onPostingStarted: (cb) => ipcRenderer.on('posting-started',   () => cb()),
  onPostingSuccess: (cb) => ipcRenderer.on('posting-success',   () => cb()),
  onPostingError:   (cb) => ipcRenderer.on('posting-error',     (_, msg) => cb(msg)),
  postConfirmed:    (msg) => ipcRenderer.send('post-confirmed', msg),
  postCancelled:    ()   => ipcRenderer.send('post-cancelled'),

  // 設定画面用
  onLoadSettings:   (cb) => ipcRenderer.on('load-settings',    (_, data) => cb(data)),
  onSettingsSaved:  (cb) => ipcRenderer.on('settings-saved',   () => cb()),
  saveSettings:     (s)  => ipcRenderer.send('save-settings',  s),
  getSettings:      ()   => ipcRenderer.invoke('get-settings'),
});
