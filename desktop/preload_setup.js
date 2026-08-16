const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('setupAPI', {
  getRuntimeInfo: () => ipcRenderer.invoke('app:get-runtime-info'),
  saveRuntimeSettings: (input) => ipcRenderer.invoke('app:save-runtime-settings', input),
  completeSetup: () => ipcRenderer.invoke('app:complete-setup'),
  openDataDir: () => ipcRenderer.invoke('app:open-data-dir')
});
