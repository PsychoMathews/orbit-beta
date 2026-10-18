const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('setup', {
  test: (kind, args) => ipcRenderer.invoke('setup-test', kind, args),
  load: () => ipcRenderer.invoke('setup-load'),
  save: (data) => ipcRenderer.invoke('setup-save', data),
  google: () => ipcRenderer.invoke('setup-google'),
  open: (url) => ipcRenderer.send('setup-open', url),
});
