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

  // 摸鱼·小说阅读
  openNovel: () => ipcRenderer.invoke('app:open-novel'),
  openNovelBook: (bookId) => ipcRenderer.invoke('app:open-novel-book', bookId),
  hideNovel: () => ipcRenderer.invoke('app:hide-novel'),
  importNovel: () => ipcRenderer.invoke('app:novel-import'),
  listNovels: () => ipcRenderer.invoke('api:novel-list'),
  listMyNovels: () => ipcRenderer.invoke('api:novel-mine'),
  listNovelChapters: (bookId) => ipcRenderer.invoke('api:novel-chapters', bookId),
  getNovelChapter: (bookId, chapterId) => ipcRenderer.invoke('api:novel-chapter', bookId, chapterId),
  getNovelProgress: (bookId) => ipcRenderer.invoke('api:novel-progress-get', bookId),
  saveNovelProgress: (bookId, body) => ipcRenderer.invoke('api:novel-progress-save', bookId, body),
  openNovelSession: (bookId) => ipcRenderer.invoke('api:novel-session-open', bookId),
  closeNovelSession: (sessionId) => ipcRenderer.invoke('api:novel-session-close', sessionId),
  deleteNovel: (bookId) => ipcRenderer.invoke('api:novel-delete', bookId),

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
  },
  onOpenNovelBook: (callback) => {
    ipcRenderer.on('novel-open-book', (_event, bookId) => callback(bookId));
  }
});
