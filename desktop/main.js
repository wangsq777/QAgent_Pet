const { app, BrowserWindow, Tray, Menu, ipcMain, dialog, nativeImage } = require('electron');
const path = require('path');
const fs = require('fs');
const { spawn } = require('child_process');

const APP_NAME = 'QAgent Pet';
const DEFAULT_PET_TYPE = 'hot_dog';
const PRESET_PETS = ['hot_dog', 'cold_cat', 'mouse'];
const HEALTH_PORTS = [8080, 10000];

let petWindow = null;
let chatWindow = null;
let webWindow = null;
let tray = null;
let backendProcess = null;
let backendBaseUrl = null;
let config = null;
let sessionInitPromise = null;
let isQuitting = false;

const desktopRoot = __dirname;
const projectRoot = app.isPackaged ? process.resourcesPath : path.resolve(desktopRoot, '..');
const rendererRoot = path.join(desktopRoot, 'renderer');
const frontendRoot = path.join(projectRoot, 'frontend');
const configPath = () => path.join(app.getPath('userData'), 'config.json');
const backendLogPath = () => path.join(desktopRoot, 'backend.log');
const backendErrLogPath = () => path.join(desktopRoot, 'backend_err.log');

function nowId() {
  return Date.now().toString(36);
}

function createDefaultConfig() {
  return {
    user_id: `desktop_${nowId()}`,
    pet_type: DEFAULT_PET_TYPE,
    custom_pet_id: null,
    session_id: null,
    dnd: false,
    backend_port: null,
    last_proactive_date: null,
    last_bubble_at: 0
  };
}

function readConfig() {
  if (config) return config;
  try {
    const raw = fs.readFileSync(configPath(), 'utf8');
    config = { ...createDefaultConfig(), ...JSON.parse(raw) };
  } catch (error) {
    config = createDefaultConfig();
    writeConfig(config);
  }
  return config;
}

function writeConfig(nextConfig) {
  config = { ...createDefaultConfig(), ...nextConfig };
  fs.mkdirSync(path.dirname(configPath()), { recursive: true });
  fs.writeFileSync(configPath(), JSON.stringify(config, null, 2), 'utf8');
  return config;
}

function patchConfig(partial) {
  return writeConfig({ ...readConfig(), ...partial });
}

function getBackendUrl() {
  if (backendBaseUrl) return backendBaseUrl;
  const cfg = readConfig();
  if (cfg.backend_port) return `http://127.0.0.1:${cfg.backend_port}`;
  return 'http://127.0.0.1:8080';
}

async function requestJson(pathname, options = {}) {
  const cfg = readConfig();
  const baseUrl = getBackendUrl();
  const headers = {
    'X-User-Id': cfg.user_id || 'anonymous',
    ...(options.body ? { 'Content-Type': 'application/json' } : {}),
    ...(options.headers || {})
  };

  const response = await fetch(`${baseUrl}${pathname}`, {
    ...options,
    headers,
    body: options.body && typeof options.body !== 'string'
      ? JSON.stringify(options.body)
      : options.body
  });

  let data = null;
  const text = await response.text();
  if (text) {
    try {
      data = JSON.parse(text);
    } catch (error) {
      data = { detail: text };
    }
  }

  if (!response.ok) {
    const message = data?.detail || data?.message || `HTTP ${response.status}`;
    throw new Error(message);
  }

  return data;
}

async function checkHealthOnPort(port) {
  const url = `http://127.0.0.1:${port}/health`;
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 1200);
  try {
    const response = await fetch(url, { signal: controller.signal });
    if (!response.ok) return false;
    await response.json().catch(() => null);
    backendBaseUrl = `http://127.0.0.1:${port}`;
    patchConfig({ backend_port: port });
    return true;
  } catch (error) {
    return false;
  } finally {
    clearTimeout(timer);
  }
}

async function detectBackend() {
  const preferred = readConfig().backend_port;
  const ports = preferred
    ? [preferred, ...HEALTH_PORTS.filter((port) => port !== preferred)]
    : HEALTH_PORTS;

  for (const port of ports) {
    if (await checkHealthOnPort(port)) return true;
  }
  return false;
}

function spawnBackend() {
  if (backendProcess) return;

  const out = fs.openSync(backendLogPath(), 'a');
  const err = fs.openSync(backendErrLogPath(), 'a');
  // 安全启动：不经 shell 直接 spawn，避免 shell 注入风险。
  // 可通过 QAGENT_PYTHON / PYTHON 指定打包后的 Python 可执行文件；
  // Windows 默认使用 py 启动器，其他平台优先 python3。
  const isWin = process.platform === 'win32';
  const pythonCommand = process.env.QAGENT_PYTHON || process.env.PYTHON || (isWin ? 'py' : 'python3');
  const pythonArgs = isWin && path.basename(pythonCommand).toLowerCase() === 'py'
    ? ['-3', 'main.py']
    : ['main.py'];
  backendProcess = spawn(pythonCommand, pythonArgs, {
    cwd: projectRoot,
    shell: false,
    windowsHide: true,
    detached: false,
    stdio: ['ignore', out, err]
  });

  backendProcess.on('exit', () => {
    backendProcess = null;
  });
}

async function ensureBackendReady() {
  if (await detectBackend()) return { ok: true, baseUrl: getBackendUrl(), started: false };

  spawnBackend();
  for (let i = 0; i < 30; i += 1) {
    await new Promise((resolve) => setTimeout(resolve, 500));
    if (await detectBackend()) {
      return { ok: true, baseUrl: getBackendUrl(), started: true };
    }
  }

  return {
    ok: false,
    error: `后端启动失败。请检查 ${backendLogPath()} 和 ${backendErrLogPath()}，或手动运行 python main.py。`
  };
}

async function ensureSessionInternal() {
  const cfg = readConfig();
  if (cfg.session_id) {
    try {
      await requestJson(`/api/sessions/${cfg.session_id}`);
      return readConfig();
    } catch (error) {
      patchConfig({ session_id: null });
    }
  }

  const body = {
    user_id: cfg.user_id,
    pet_type: cfg.pet_type || DEFAULT_PET_TYPE
  };
  if (cfg.custom_pet_id) body.custom_pet_id = cfg.custom_pet_id;

  const session = await requestJson('/api/sessions', {
    method: 'POST',
    body
  });

  return patchConfig({
    session_id: session.session_id,
    pet_type: session.pet_type || body.pet_type
  });
}

async function ensureSession() {
  if (!sessionInitPromise) {
    sessionInitPromise = ensureSessionInternal()
      .finally(() => {
        sessionInitPromise = null;
      });
  }
  return sessionInitPromise;
}

function getPetImagePath(petType = DEFAULT_PET_TYPE) {
  const imageMap = {
    hot_dog: 'hot_dog.png',
    cold_cat: 'cold_cat.png',
    mouse: 'mouse.png',
    dog: 'hot_dog.png',
    cat: 'cold_cat.png',
    hamster: 'mouse.png',
    panda: 'panda.png',
    tiger: 'tiger.png',
    lion: 'lion.png',
    snake: 'snake.png',
    cheetah: 'cheetah.png',
    deer: 'deer.png',
    lamb: 'lamb.png',
    pig: 'pig.png',
    horse: 'horse.png'
  };
  return path.join(frontendRoot, 'images', imageMap[petType] || imageMap.hot_dog);
}

function getTrayIcon() {
  const iconPath = getPetImagePath(readConfig().pet_type);
  const image = nativeImage.createFromPath(iconPath);
  if (image.isEmpty()) return nativeImage.createEmpty();
  return image.resize({ width: 18, height: 18 });
}

function createTray() {
  if (tray) return;
  tray = new Tray(getTrayIcon());
  tray.setToolTip(APP_NAME);
  tray.on('double-click', () => showPetWindow());
  updateTrayMenu();
}

function buildAppMenu() {
  const cfg = readConfig();
  const template = [
    { label: '显示桌宠', click: () => showPetWindow() },
    { label: '打开完整 Web 面板', click: () => openWebPanel() },
    { type: 'separator' },
    {
      label: cfg.dnd ? '关闭勿扰模式' : '开启勿扰模式',
      click: () => {
        patchConfig({ dnd: !readConfig().dnd });
        updateTrayMenu();
        sendToWindows('config-updated', readConfig());
      }
    },
    {
      label: `切换宠物（当前：${cfg.pet_type || DEFAULT_PET_TYPE}）`,
      submenu: PRESET_PETS.map((petType) => ({
        label: petType,
        type: 'radio',
        checked: (cfg.pet_type || DEFAULT_PET_TYPE) === petType,
        click: async () => {
          patchConfig({ pet_type: petType, custom_pet_id: null, session_id: null });
          if (webWindow && !webWindow.isDestroyed()) {
            webWindow.close();
          }
          await ensureSession().catch(() => null);
          updateTrayMenu();
          sendToWindows('config-updated', readConfig());
          sendToWindows('pet-refresh');
        }
      }))
    },
    { type: 'separator' },
    {
      label: '退出 QAgent Pet',
      click: () => {
        isQuitting = true;
        app.quit();
      }
    }
  ];
  return Menu.buildFromTemplate(template);
}

function updateTrayMenu() {
  if (!tray) return;
  tray.setContextMenu(buildAppMenu());
}

function showPetWindow() {
  if (!petWindow) return;
  petWindow.show();
  petWindow.focus();
}

function createPetWindow() {
  petWindow = new BrowserWindow({
    width: 190,
    height: 220,
    transparent: true,
    frame: false,
    resizable: false,
    alwaysOnTop: true,
    skipTaskbar: true,
    hasShadow: false,
    webPreferences: {
      preload: path.join(desktopRoot, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: false
    }
  });

  petWindow.setAlwaysOnTop(true, 'floating');
  petWindow.loadFile(path.join(rendererRoot, 'pet.html'));
  petWindow.webContents.on('context-menu', () => {
    buildAppMenu().popup({ window: petWindow });
  });
  petWindow.on('close', (event) => {
    if (!isQuitting) {
      event.preventDefault();
      petWindow.hide();
    }
  });
  petWindow.on('closed', () => {
    petWindow = null;
  });
}

function createChatWindow() {
  if (chatWindow && !chatWindow.isDestroyed()) return chatWindow;

  chatWindow = new BrowserWindow({
    width: 360,
    height: 500,
    show: false,
    resizable: true,
    alwaysOnTop: true,
    skipTaskbar: true,
    title: 'QAgent Pet 轻聊天',
    webPreferences: {
      preload: path.join(desktopRoot, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: false
    }
  });

  chatWindow.loadFile(path.join(rendererRoot, 'chat.html'));
  chatWindow.on('close', (event) => {
    if (!isQuitting) {
      event.preventDefault();
      chatWindow.hide();
    }
  });
  chatWindow.on('closed', () => {
    chatWindow = null;
  });
}

function toggleChatWindow() {
  if (!chatWindow) createChatWindow();

  if (chatWindow.isVisible()) {
    chatWindow.hide();
    return;
  }

  const petBounds = petWindow?.getBounds();
  if (petBounds) {
    chatWindow.setPosition(Math.max(0, petBounds.x - 380), Math.max(0, petBounds.y - 40));
  }
  chatWindow.show();
  chatWindow.focus();
}

async function openWebPanel() {
  await ensureBackendReady();
  await ensureSession();
  const cfg = readConfig();
  const baseUrl = getBackendUrl();
  if (!webWindow) {
    webWindow = new BrowserWindow({
      width: 1180,
      height: 780,
      minWidth: 960,
      minHeight: 640,
      title: 'QAgent Pet 控制中心',
      webPreferences: {
        preload: path.join(desktopRoot, 'preload_web.js'),
        contextIsolation: true,
        nodeIntegration: false,
        sandbox: false,
        additionalArguments: [
          `--qagent-user-id=${cfg.user_id || ''}`,
          `--qagent-session-id=${cfg.session_id || ''}`,
          `--qagent-pet-type=${cfg.pet_type || DEFAULT_PET_TYPE}`,
          `--qagent-custom-pet-id=${cfg.custom_pet_id || ''}`
        ]
      }
    });

    webWindow.on('closed', () => {
      webWindow = null;
    });
  }

  webWindow.loadURL(`${baseUrl}/frontend/chat.html`);
  webWindow.show();
  webWindow.focus();
}

function sendToWindows(channel, payload) {
  for (const win of [petWindow, chatWindow]) {
    if (win && !win.isDestroyed()) {
      win.webContents.send(channel, payload);
    }
  }
}

function registerIpc() {
  ipcMain.handle('app:get-config', async () => readConfig());
  ipcMain.handle('app:set-config', async (_event, partial) => {
    const next = patchConfig(partial || {});
    updateTrayMenu();
    sendToWindows('config-updated', next);
    return next;
  });
  ipcMain.handle('app:toggle-chat', async () => toggleChatWindow());
  ipcMain.handle('app:move-pet', async (_event, dx, dy) => {
    if (!petWindow || petWindow.isDestroyed()) return;
    const bounds = petWindow.getBounds();
    petWindow.setPosition(bounds.x + Math.round(dx || 0), bounds.y + Math.round(dy || 0));
  });
  ipcMain.handle('app:open-web', async () => openWebPanel());
  ipcMain.handle('app:quit', async () => {
    isQuitting = true;
    app.quit();
  });
  ipcMain.handle('app:ensure-backend', async () => ensureBackendReady());
  ipcMain.handle('app:ensure-session', async () => ensureSession());
  ipcMain.handle('app:get-pet-image', async () => getPetImagePath(readConfig().pet_type));
  ipcMain.handle('app:notify-chat-done', async () => {
    sendToWindows('pet-refresh');
  });

  ipcMain.handle('api:get-messages', async () => {
    const cfg = await ensureSession();
    return requestJson(`/api/sessions/${cfg.session_id}/messages`);
  });
  ipcMain.handle('api:get-pet-status', async () => {
    const cfg = await ensureSession();
    return requestJson(`/api/sessions/${cfg.session_id}/pet-status`);
  });
  ipcMain.handle('api:chat', async (_event, content) => {
    const cfg = await ensureSession();
    return requestJson(`/api/sessions/${cfg.session_id}/chat`, {
      method: 'POST',
      body: { content }
    });
  });
  ipcMain.handle('api:share-daily', async () => {
    const cfg = await ensureSession();
    return requestJson(`/api/sessions/${cfg.session_id}/share-daily`, { method: 'POST' });
  });
  ipcMain.handle('api:simulate-time', async (_event, mode) => {
    const cfg = await ensureSession();
    return requestJson(`/api/sessions/${cfg.session_id}/simulate-time`, {
      method: 'POST',
      body: { mode }
    });
  });
}

app.whenReady().then(async () => {
  app.setName(APP_NAME);
  readConfig();
  registerIpc();
  createTray();
  createPetWindow();
  createChatWindow();

  const backend = await ensureBackendReady();
  if (backend.ok) {
    ensureSession()
      .then(() => {
        updateTrayMenu();
        sendToWindows('config-updated', readConfig());
        sendToWindows('pet-refresh');
      })
      .catch((error) => {
        dialog.showErrorBox(APP_NAME, `创建桌宠会话失败：${error.message}`);
      });
  } else {
    dialog.showErrorBox(APP_NAME, backend.error || '后端启动失败');
    sendToWindows('backend-error', backend.error || '后端启动失败');
  }
});

app.on('window-all-closed', () => {
  // 桌宠关闭窗口时进入托盘驻留；仅通过菜单“退出”结束进程。
});

app.on('before-quit', () => {
  isQuitting = true;
  if (backendProcess) {
    backendProcess.kill();
    backendProcess = null;
  }
});
