const { contextBridge, ipcRenderer } = require('electron');

const argValue = (prefix) => {
  const found = process.argv.find((arg) => arg.startsWith(prefix));
  return found ? decodeURIComponent(found.slice(prefix.length)) : '';
};

// 面板内每次页面跳转都会重跑 preload,而启动参数只在窗口创建时捕获一次,
// 直接用它们回写会把 localStorage 刷回旧宠物。以主进程实时配置为准,启动参数仅作兜底。
let liveConfig = null;
try {
  liveConfig = ipcRenderer.sendSync('app:get-config-sync');
} catch (error) {
  liveConfig = null;
}

const userId = (liveConfig && liveConfig.user_id) || argValue('--qagent-user-id=');
const sessionId = (liveConfig && liveConfig.session_id) || argValue('--qagent-session-id=');
const petType = (liveConfig && liveConfig.pet_type) || argValue('--qagent-pet-type=');
const customPetId = (liveConfig && liveConfig.custom_pet_id) || argValue('--qagent-custom-pet-id=');
const apiBase = argValue('--qagent-api-base=');
const apiKey = argValue('--qagent-api-key=');

if (userId) localStorage.setItem('qagent_user_id', userId);
if (sessionId) localStorage.setItem('qagent_session_id', sessionId);
if (petType) localStorage.setItem('qagent_pet_type', petType);
if (liveConfig) {
  // 实时配置确认没有自定义宠物时清掉残留,否则切回预置宠物后仍会被当成自定义
  if (customPetId) localStorage.setItem('qagent_custom_pet_id', customPetId);
  else localStorage.removeItem('qagent_custom_pet_id');
} else if (customPetId) {
  localStorage.setItem('qagent_custom_pet_id', customPetId);
}

// 向 Web 面板暴露 desktopAPI，使前端可以同步更新 Electron 主进程配置

// 运行时信息(本地打包面板 file:// 加载时,前端需要绝对后端地址来调用 API)
contextBridge.exposeInMainWorld('__QAGENT_RUNTIME__', {
  apiBase,
  apiKey,
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
  playBiliVideo: (input) => ipcRenderer.invoke('feed:play-video', input),
  openSetup: () => ipcRenderer.invoke('app:open-setup'),
  openDataDir: () => ipcRenderer.invoke('app:open-data-dir'),
  getAutostart: () => ipcRenderer.invoke('app:get-autostart'),
  setAutostart: (enabled) => ipcRenderer.invoke('app:set-autostart', enabled),
  onConfigUpdated: (callback) => {
    ipcRenderer.on('config-updated', (_event, config) => callback(config));
  },
  onPetRefresh: (callback) => {
    ipcRenderer.on('pet-refresh', () => callback());
  },
  // 主进程 proactive 轮询到事件时广播给所有窗口，Web 面板据此渲染主动消息与操作按钮
  onProactiveEvent: (callback) => {
    ipcRenderer.on('proactive-event', (_event, proactiveEvent) => callback(proactiveEvent));
  }
});
