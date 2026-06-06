const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('electronAPI', {
  // 窗口控制
  minimize: () => ipcRenderer.send('window-minimize'),
  maximize: () => ipcRenderer.send('window-maximize'),
  close: () => ipcRenderer.send('window-close'),

  // 文件操作
  openFileDialog: () => ipcRenderer.invoke('open-file-dialog'),
  openDocxDialog: () => ipcRenderer.invoke('open-docx-dialog'),
  saveFileDialog: (defaultName, filters) => ipcRenderer.invoke('save-file-dialog', defaultName, filters),
  writeFileBase64: (filePath, base64) => ipcRenderer.invoke('write-file-base64', filePath, base64),
  writeFileText: (filePath, content) => ipcRenderer.invoke('write-file-text', filePath, content),
  saveTextDialog: (defaultName, content) => ipcRenderer.invoke('save-text-dialog', defaultName, content),
  writeThoughtLog: (fileName, content) => ipcRenderer.invoke('write-thought-log', fileName, content),
  openFileExternal: (filePath) => ipcRenderer.invoke('open-file-external', filePath),
  openExternalUrl: (url) => ipcRenderer.invoke('open-external-url', url),
  readFileBase64: (filePath) => ipcRenderer.invoke('read-file-base64', filePath),
  detectTerminalEnv: (currentFilePath) => ipcRenderer.invoke('detect-terminal-env', currentFilePath),

  // 服务器
  getServerPort: () => ipcRenderer.invoke('get-server-port'),

  // API Key 加密存储（主进程 safeStorage）
  isApiKeyEncryptionAvailable: () => ipcRenderer.invoke('settings-store:is-encryption-available'),
  encryptApiKey: (plainText) => ipcRenderer.invoke('settings-store:encrypt-api-key', plainText),
  decryptApiKey: (base64) => ipcRenderer.invoke('settings-store:decrypt-api-key', base64),

  // 事件监听
  onServerReady: (callback) => ipcRenderer.on('server-ready', callback),
  onServerError: (callback) => ipcRenderer.on('server-error', (event, msg) => callback(msg)),
});
