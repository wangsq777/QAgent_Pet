// 「播放 B 站链接」输入窗的 preload:只暴露播放与关闭两个动作,不接触页面数据。
const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('videoPromptAPI', {
  play: (input) => ipcRenderer.invoke('feed:play-video', input)
});
