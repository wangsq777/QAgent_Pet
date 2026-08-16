const { app, BrowserWindow, Tray, Menu, ipcMain, dialog, nativeImage, shell, powerMonitor } = require('electron');
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
let setupWindow = null;
let tray = null;
let backendProcess = null;
let backendBaseUrl = null;
let config = null;
let sessionInitPromise = null;
let isQuitting = false;
let coreStarted = false;
let proactiveTimer = null;
let proactiveClaimInFlight = false;

const desktopRoot = __dirname;
const projectRoot = app.isPackaged ? process.resourcesPath : path.resolve(desktopRoot, '..');
const rendererRoot = path.join(desktopRoot, 'renderer');
const frontendRoot = path.join(projectRoot, 'frontend');
const configPath = () => path.join(app.getPath('userData'), 'config.json');
const runtimeEnvPath = () => path.join(app.getPath('userData'), 'runtime.env');
const backendLogPath = () => path.join(app.getPath('userData'), 'backend.log');
const backendErrLogPath = () => path.join(app.getPath('userData'), 'backend_err.log');
const databasePath = () => path.join(app.getPath('userData'), 'qagent_pet.db');

function parseEnvFile(filePath) {
  try {
    const result = {};
    const content = fs.readFileSync(filePath, 'utf8');
    for (const rawLine of content.split(/\r?\n/)) {
      const line = rawLine.trim();
      if (!line || line.startsWith('#') || !line.includes('=')) continue;
      const separator = line.indexOf('=');
      const key = line.slice(0, separator).trim();
      const value = line.slice(separator + 1).trim().replace(/^['"]|['"]$/g, '');
      result[key] = value;
    }
    return result;
  } catch (error) {
    return {};
  }
}

function effectiveEnvPath() {
  if (fs.existsSync(runtimeEnvPath())) return runtimeEnvPath();
  const developmentEnv = path.join(projectRoot, '.env');
  if (!app.isPackaged && fs.existsSync(developmentEnv)) return developmentEnv;
  return runtimeEnvPath();
}

function effectiveRuntimeSettings() {
  return {
    ...parseEnvFile(effectiveEnvPath()),
    ...Object.fromEntries(
      ['LLM_API_KEY', 'LLM_BASE_URL', 'LLM_MODEL'].filter((key) => process.env[key])
        .map((key) => [key, process.env[key]])
    )
  };
}

function hasRuntimeConfiguration() {
  return Boolean(effectiveRuntimeSettings().LLM_API_KEY);
}

function publicRuntimeInfo() {
  const values = effectiveRuntimeSettings();
  return {
    configured: Boolean(values.LLM_API_KEY),
    llm_base_url: values.LLM_BASE_URL || 'https://api.minimaxi.com/anthropic',
    llm_model: values.LLM_MODEL || 'MiniMax-M2.5',
    data_dir: app.getPath('userData'),
    database_path: databasePath(),
    app_version: app.getVersion(),
    packaged: app.isPackaged
  };
}

function validateRuntimeSettings(input = {}) {
  const existing = effectiveRuntimeSettings();
  const apiKey = String(input.llm_api_key || existing.LLM_API_KEY || '').trim();
  const baseUrl = String(input.llm_base_url || existing.LLM_BASE_URL || 'https://api.minimaxi.com/anthropic').trim();
  const model = String(input.llm_model || existing.LLM_MODEL || 'MiniMax-M2.5').trim();

  if (!apiKey || apiKey.length > 500 || /[\r\n]/.test(apiKey)) {
    throw new Error('请输入有效的 LLM API Key');
  }
  if (!model || model.length > 100 || /[\r\n]/.test(model)) {
    throw new Error('请输入有效的模型名称');
  }

  let parsedUrl;
  try {
    parsedUrl = new URL(baseUrl);
  } catch (error) {
    throw new Error('请输入有效的 API 地址');
  }
  const isLocal = ['localhost', '127.0.0.1', '::1'].includes(parsedUrl.hostname);
  if (parsedUrl.protocol !== 'https:' && !(isLocal && parsedUrl.protocol === 'http:')) {
    throw new Error('远程 API 地址必须使用 HTTPS');
  }

  return { apiKey, baseUrl: baseUrl.replace(/\/$/, ''), model };
}

function writeRuntimeSettings(input) {
  const values = validateRuntimeSettings(input);
  const existing = parseEnvFile(runtimeEnvPath());
  const preservedKeys = [
    'WEATHER_API_KEY',
    'EMBEDDING_API_URL',
    'EMBEDDING_API_KEY',
    'EMBEDDING_MODEL'
  ];
  fs.mkdirSync(app.getPath('userData'), { recursive: true });
  const body = [
    '# QAgent Pet desktop runtime settings',
    `LLM_API_KEY=${values.apiKey}`,
    `LLM_BASE_URL=${values.baseUrl}`,
    `LLM_MODEL=${values.model}`,
    ...preservedKeys
      .filter((key) => existing[key] && !/[\r\n]/.test(existing[key]))
      .map((key) => `${key}=${existing[key]}`),
    'PORT=10000',
    'CORS_ORIGINS=http://localhost:10000,http://127.0.0.1:10000',
    'LOG_LEVEL=INFO',
    ''
  ].join('\n');
  fs.writeFileSync(runtimeEnvPath(), body, { encoding: 'utf8', mode: 0o600 });
  try {
    fs.chmodSync(runtimeEnvPath(), 0o600);
  } catch (error) {
    // Windows does not implement Unix file modes; the per-user directory is
    // still the correct storage boundary there.
  }
  return publicRuntimeInfo();
}

function nowId() {
  return Date.now().toString(36);
}

function createDefaultConfig() {
  return {
    user_id: `desktop_${nowId()}`,
    pet_type: DEFAULT_PET_TYPE,
    custom_pet_id: null,
    custom_pet_raw_type: null,
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
    const health = await response.json().catch(() => null);
    if (health?.app !== 'qagent-pet') return false;
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

function resolveBackendCommand() {
  const isWin = process.platform === 'win32';
  if (app.isPackaged) {
    const executable = path.join(process.resourcesPath, 'backend', isWin ? 'qagent-backend.exe' : 'qagent-backend');
    if (!fs.existsSync(executable)) {
      throw new Error(`安装包缺少后端程序：${executable}`);
    }
    return { command: executable, args: [] };
  }

  const configuredPython = process.env.QAGENT_PYTHON || process.env.PYTHON;
  const virtualenvPython = path.join(projectRoot, '.venv', isWin ? 'Scripts/python.exe' : 'bin/python');
  const pythonCommand = configuredPython || (fs.existsSync(virtualenvPython) ? virtualenvPython : (isWin ? 'py' : 'python3'));
  const args = isWin && path.basename(pythonCommand).toLowerCase() === 'py'
    ? ['-3', 'main.py']
    : ['main.py'];
  return { command: pythonCommand, args };
}

function backendEnvironment() {
  const legacyDatabase = path.join(projectRoot, 'qagent_pet.db');
  return {
    ...process.env,
    QAGENT_DATA_DIR: app.getPath('userData'),
    QAGENT_ENV_FILE: effectiveEnvPath(),
    QAGENT_FRONTEND_DIR: frontendRoot,
    ...(fs.existsSync(legacyDatabase) ? { QAGENT_LEGACY_DATABASE_PATH: legacyDatabase } : {})
  };
}

function spawnBackend() {
  if (backendProcess) return;

  fs.mkdirSync(app.getPath('userData'), { recursive: true });
  const out = fs.openSync(backendLogPath(), 'a');
  const err = fs.openSync(backendErrLogPath(), 'a');
  const backend = resolveBackendCommand();
  backendProcess = spawn(backend.command, backend.args, {
    cwd: app.isPackaged ? app.getPath('userData') : projectRoot,
    env: backendEnvironment(),
    shell: false,
    windowsHide: true,
    detached: false,
    stdio: ['ignore', out, err]
  });
  fs.closeSync(out);
  fs.closeSync(err);

  backendProcess.on('error', (error) => {
    fs.appendFileSync(backendErrLogPath(), `[desktop] ${error.message}\n`, 'utf8');
    backendProcess = null;
  });
  backendProcess.on('exit', () => {
    backendProcess = null;
  });
}

async function ensureBackendReady() {
  if (await detectBackend()) return { ok: true, baseUrl: getBackendUrl(), started: false };

  try {
    spawnBackend();
  } catch (error) {
    return { ok: false, error: error.message };
  }
  for (let i = 0; i < 30; i += 1) {
    await new Promise((resolve) => setTimeout(resolve, 500));
    if (await detectBackend()) {
      return { ok: true, baseUrl: getBackendUrl(), started: true };
    }
  }

  return {
    ok: false,
    error: `后端启动失败。请检查 ${backendLogPath()} 和 ${backendErrLogPath()}。`
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
    pet_type: session.pet_type || body.pet_type,
    custom_pet_id: session.custom_pet_id || body.custom_pet_id || null
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

function getPetImagePath(petType = DEFAULT_PET_TYPE, rawPetType = null) {
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
  // 自定义宠物：优先使用原始动物类型查找对应图片；找不到时再用默认狗狗兜底
  const lookupType = (petType === 'custom' && rawPetType) ? rawPetType : petType;
  return path.join(frontendRoot, 'images', imageMap[lookupType] || imageMap.hot_dog);
}

function getTrayIcon() {
  const cfg = readConfig();
  const iconPath = getPetImagePath(cfg.pet_type, cfg.custom_pet_raw_type);
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
    { label: 'AI 服务设置', click: () => createSetupWindow() },
    { label: '打开数据目录', click: () => shell.openPath(app.getPath('userData')) },
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

function createSetupWindow({ required = false } = {}) {
  if (setupWindow && !setupWindow.isDestroyed()) {
    setupWindow.show();
    setupWindow.focus();
    return setupWindow;
  }

  setupWindow = new BrowserWindow({
    width: 560,
    height: 680,
    minWidth: 520,
    minHeight: 620,
    resizable: true,
    title: required ? '开始使用 QAgent Pet' : 'QAgent Pet AI 服务设置',
    webPreferences: {
      preload: path.join(desktopRoot, 'preload_setup.js'),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: false
    }
  });

  setupWindow.loadFile(path.join(rendererRoot, 'setup.html'), {
    query: { required: required ? '1' : '0' }
  });
  setupWindow.on('closed', () => {
    setupWindow = null;
  });
  return setupWindow;
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
  const backend = await ensureBackendReady();
  if (!backend.ok) {
    dialog.showErrorBox(APP_NAME, backend.error || '后端启动失败');
    return;
  }
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

async function claimProactiveEvent() {
  if (proactiveClaimInFlight || !backendBaseUrl || readConfig().dnd) return null;
  proactiveClaimInFlight = true;
  try {
    const cfg = await ensureSession();
    const timezone = Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC';
    const result = await requestJson('/api/proactive/events/claim', {
      method: 'POST',
      body: { session_id: cfg.session_id, timezone, client_id: `desktop-${app.getPath('userData')}` }
    });
    if (result?.event) {
      sendToWindows('proactive-event', result.event);
    }
    return result?.event || null;
  } catch (error) {
    fs.appendFileSync(backendErrLogPath(), `[proactive] ${error.message}\n`, 'utf8');
    return null;
  } finally {
    proactiveClaimInFlight = false;
  }
}

function startProactivePolling() {
  if (proactiveTimer) clearInterval(proactiveTimer);
  claimProactiveEvent();
  proactiveTimer = setInterval(() => claimProactiveEvent(), 60 * 1000);
}

function registerIpc() {
  ipcMain.handle('app:get-config', async () => readConfig());
  ipcMain.handle('app:get-runtime-info', async () => publicRuntimeInfo());
  ipcMain.handle('app:save-runtime-settings', async (_event, input) => writeRuntimeSettings(input || {}));
  ipcMain.handle('app:complete-setup', async () => {
    const restarting = coreStarted;
    setTimeout(() => {
      if (setupWindow && !setupWindow.isDestroyed()) setupWindow.close();
      if (restarting) {
        isQuitting = true;
        app.relaunch();
        app.exit(0);
      } else {
        startCoreApp();
      }
    }, 150);
    return { restarting };
  });
  ipcMain.handle('app:open-setup', async () => {
    createSetupWindow();
    return true;
  });
  ipcMain.handle('app:open-data-dir', async () => shell.openPath(app.getPath('userData')));
  ipcMain.handle('app:set-config', async (_event, partial) => {
    const next = patchConfig(partial || {});
    updateTrayMenu();
    sendToWindows('config-updated', next);
    return next;
  });
  ipcMain.handle('app:toggle-chat', async () => toggleChatWindow());
  ipcMain.handle('app:show-pet', async () => showPetWindow());
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
  ipcMain.handle('app:get-pet-image', async () => {
    const cfg = readConfig();
    return getPetImagePath(cfg.pet_type, cfg.custom_pet_raw_type);
  });
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
  ipcMain.handle('api:proactive-delivered', async (_event, eventId, claimToken) => requestJson(`/api/proactive/events/${eventId}/delivered`, { method: 'POST', body: { claim_token: claimToken } }));
  ipcMain.handle('api:proactive-opened', async (_event, eventId, claimToken) => requestJson(`/api/proactive/events/${eventId}/opened`, { method: 'POST', body: { claim_token: claimToken } }));
  ipcMain.handle('api:proactive-action', async (_event, eventId, action, claimToken) => requestJson(`/api/proactive/events/${eventId}/action`, { method: 'POST', body: { action, claim_token: claimToken } }));
}

async function startCoreApp() {
  if (coreStarted) return;
  coreStarted = true;
  createPetWindow();
  createChatWindow();

  const backend = await ensureBackendReady();
  if (backend.ok) {
    ensureSession()
      .then(() => {
        updateTrayMenu();
        sendToWindows('config-updated', readConfig());
        sendToWindows('pet-refresh');
        startProactivePolling();
      })
      .catch((error) => {
        dialog.showErrorBox(APP_NAME, `创建桌宠会话失败：${error.message}`);
      });
  } else {
    dialog.showErrorBox(APP_NAME, backend.error || '后端启动失败');
    sendToWindows('backend-error', backend.error || '后端启动失败');
  }
}

app.whenReady().then(async () => {
  app.setName(APP_NAME);
  readConfig();
  registerIpc();
  createTray();

  if (hasRuntimeConfiguration()) {
    await startCoreApp();
  } else {
    createSetupWindow({ required: true });
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
  if (proactiveTimer) clearInterval(proactiveTimer);
});

powerMonitor.on('resume', () => {
  if (coreStarted) claimProactiveEvent();
});
