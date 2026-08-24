const argValue = (prefix) => {
  const found = process.argv.find((arg) => arg.startsWith(prefix));
  return found ? decodeURIComponent(found.slice(prefix.length)) : '';
};

const userId = argValue('--qagent-user-id=');
const sessionId = argValue('--qagent-session-id=');
const petType = argValue('--qagent-pet-type=');
const customPetId = argValue('--qagent-custom-pet-id=');
const apiBase = argValue('--qagent-api-base=');

if (userId) localStorage.setItem('qagent_user_id', userId);
if (sessionId) localStorage.setItem('qagent_session_id', sessionId);
if (petType) localStorage.setItem('qagent_pet_type', petType);
if (customPetId) localStorage.setItem('qagent_custom_pet_id', customPetId);

// 向 Web 面板暴露 desktopAPI，使前端可以同步更新 Electron 主进程配置
const { contextBridge, ipcRenderer } = require('electron');

// 运行时信息(本地打包面板 file:// 加载时,前端需要绝对后端地址来调用 API)
contextBridge.exposeInMainWorld('__QAGENT_RUNTIME__', {
  apiBase,
  userId,
  sessionId,
  petType,
  customPetId
});

contextBridge.exposeInMainWorld('desktopAPI', {
  getConfig: () => ipcRenderer.invoke('app:get-config'),
  getRuntimeInfo: () => ipcRenderer.invoke('app:get-runtime-info'),
  setConfig: (partial) => ipcRenderer.invoke('app:set-config', partial),
  ensureBackend: () => ipcRenderer.invoke('app:ensure-backend'),
  ensureSession: () => ipcRenderer.invoke('app:ensure-session'),
  getPetImage: () => ipcRenderer.invoke('app:get-pet-image'),
  toggleChat: () => ipcRenderer.invoke('app:toggle-chat'),
  showPet: () => ipcRenderer.invoke('app:show-pet'),
  openWebPanel: () => ipcRenderer.invoke('app:open-web'),
  openNovelBook: (bookId) => ipcRenderer.invoke('app:open-novel-book', bookId),
  openFeed: () => ipcRenderer.invoke('app:open-feed'),
  openFeedChannel: (channel) => ipcRenderer.invoke('app:open-feed-channel', channel),
  openSetup: () => ipcRenderer.invoke('app:open-setup'),
  openDataDir: () => ipcRenderer.invoke('app:open-data-dir'),
  onConfigUpdated: (callback) => {
    ipcRenderer.on('config-updated', (_event, config) => callback(config));
  },
  onPetRefresh: (callback) => {
    ipcRenderer.on('pet-refresh', () => callback());
  }
});
