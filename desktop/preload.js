const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('desktopAPI', {
  getConfig: () => ipcRenderer.invoke('app:get-config'),
  getRuntimeInfo: () => ipcRenderer.invoke('app:get-runtime-info'),
  setConfig: (partial) => ipcRenderer.invoke('app:set-config', partial),
  ensureBackend: () => ipcRenderer.invoke('app:ensure-backend'),
  ensureSession: () => ipcRenderer.invoke('app:ensure-session'),
  getPetImage: () => ipcRenderer.invoke('app:get-pet-image'),
  toggleChat: () => ipcRenderer.invoke('app:toggle-chat'),
  showPet: () => ipcRenderer.invoke('app:show-pet'),
  movePet: (dx, dy) => ipcRenderer.invoke('app:move-pet', dx, dy),
  openWebPanel: () => ipcRenderer.invoke('app:open-web'),
  openSetup: () => ipcRenderer.invoke('app:open-setup'),
  openDataDir: () => ipcRenderer.invoke('app:open-data-dir'),
  quit: () => ipcRenderer.invoke('app:quit'),
  notifyChatDone: () => ipcRenderer.invoke('app:notify-chat-done'),

  getMessages: () => ipcRenderer.invoke('api:get-messages'),
  getPetStatus: () => ipcRenderer.invoke('api:get-pet-status'),
  chat: (content) => ipcRenderer.invoke('api:chat', content),
  shareDaily: () => ipcRenderer.invoke('api:share-daily'),
  simulateTime: (mode) => ipcRenderer.invoke('api:simulate-time', mode),
  proactiveDelivered: (eventId, claimToken) => ipcRenderer.invoke('api:proactive-delivered', eventId, claimToken),
  proactiveOpened: (eventId, claimToken) => ipcRenderer.invoke('api:proactive-opened', eventId, claimToken),
  proactiveAction: (eventId, action, claimToken) => ipcRenderer.invoke('api:proactive-action', eventId, action, claimToken),

  onConfigUpdated: (callback) => {
    ipcRenderer.on('config-updated', (_event, config) => callback(config));
  },
  onPetRefresh: (callback) => {
    ipcRenderer.on('pet-refresh', () => callback());
  },
  onBackendError: (callback) => {
    ipcRenderer.on('backend-error', (_event, message) => callback(message));
  },
  onProactiveEvent: (callback) => {
    ipcRenderer.on('proactive-event', (_event, proactiveEvent) => callback(proactiveEvent));
  }
});
