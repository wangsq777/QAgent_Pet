const { app, BrowserWindow, Tray, Menu, ipcMain, dialog, nativeImage, shell, powerMonitor, globalShortcut, session, screen } = require('electron');
const path = require('path');
const fs = require('fs');
const https = require('https');
const crypto = require('crypto');
const { fileURLToPath } = require('url');
const { spawn } = require('child_process');

// 视频小窗允许页面免手势自动播放(小窗刷视频不该每次先点一下)。
app.commandLine.appendSwitch('autoplay-policy', 'no-user-gesture-required');

const APP_NAME = 'QAgent Pet';
const DEFAULT_PET_TYPE = 'hot_dog';
const PRESET_PETS = ['hot_dog', 'cold_cat', 'mouse'];
const HEALTH_PORTS = [8080, 10000];
// 摸鱼·视频小窗默认载入的平台网页版。独立 partition 保存登录态,与主面板隔离。
const FEED_DEFAULT_URL = 'https://www.bilibili.com';
// 摸鱼·刷一刷小窗可切换的网页渠道(B站 / 小红书 / 抖音 / 快手 / 淘宝),与 feed_preload.js 的导航栏保持一致。
// mobile=true 的渠道改用手机 UA:竖屏信息流天然适配小窗尺寸,无需手动缩放;bounds 可给渠道自定义默认窗尺寸。
const FEED_DEFAULT_UA = app.userAgentFallback || '';
const FEED_MOBILE_UA = 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_6_1 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.6.1 Mobile/15E148 Safari/604.1';
const FEED_CHANNELS = {
  bilibili: { name: 'B站', url: 'https://www.bilibili.com', host: 'www.bilibili.com', mobile: false },
  xiaohongshu: { name: '小红书', url: 'https://www.xiaohongshu.com/explore', host: 'www.xiaohongshu.com', mobile: true },
  douyin: { name: '抖音', url: 'https://www.douyin.com/?recommend=1', host: 'www.douyin.com', mobile: false },
  // 快手桌面网页版首页即竖屏短视频流,免登录可刷,保持桌面 UA 即可。
  kuaishou: { name: '快手', url: 'https://www.kuaishou.com/short-video', host: 'www.kuaishou.com', mobile: false },
  // 淘宝网页版是桌面宽布局(登录后首页即「猜你喜欢」商品流):保持桌面 UA,bounds 给宽窗
  // (滑块验证在窄窗拖不动,且宽窗容纳桌面布局);手机 H5 强引导打开 App,弃用。
  taobao: { name: '淘宝', url: 'https://www.taobao.com', host: 'www.taobao.com', mobile: false, bounds: { width: 960, height: 700 } }
};
// 老板键:全局快捷键,一键隐藏小窗并暂停声音;再按恢复显示。选冷门组合避免抢占常用软件快捷键。
const FEED_BOSS_KEY = 'CommandOrControl+Shift+Y';
const FEED_MOBILE_BOUNDS = { width: 420, height: 700 };
const FEED_DESKTOP_BOUNDS = { width: 640, height: 480 };
// 渠道专属布局:信息流与播放态分开记忆,避免 B 站点进视频后仍停留在信息流尺寸。
// 这不是强制全屏,而是把网页内容约束在适合摸鱼小窗的比例内。
const FEED_LAYOUTS = {
  bilibili: {
    feed: { width: 760, height: 560 },
    player: { width: 960, height: 540 }
  },
  douyin: {
    feed: { ...FEED_MOBILE_BOUNDS },
    player: { ...FEED_MOBILE_BOUNDS }
  }
};

// 「打开App/下载App」横幅的声明式遮盖:每个导航按当前域名注入一次 CSS,
// 零常驻开销;文字级兜底仍由 feed_preload.js 的节流扫描负责。
const FEED_HIDE_CSS_COMMON = `
  [class*="open-app"],[class*="openApp"],[class*="open_app"],
  [class*="app-download"],[class*="download-app"],[class*="downloadApp"],[class*="download-entry"],
  [class*="app-guide"],[class*="launch-app"],[class*="callup"],[class*="call-app"],[class*="wake-app"],
  [id*="open-app"],[id*="download-app"],[data-download-app]
  { display: none !important; }
`;
const FEED_HIDE_CSS = {
  bilibili: `
    .launch-app-btn,.eva-banner,.bili-app-download,.openapp-dialog,.activity-banner-wrap
    { display: none !important; }
  `,
  xiaohongshu: `
    .interact-container,[class*="top-guide"],[class*="entry-bar"]
    { display: none !important; }
  `,
  douyin: `
    .login-guide-container,[class*="guidance-pop"],[class*="web-download"]
    { display: none !important; }
  `,
  kuaishou: `
    .download-tip,.download-dialog,[class*="guide-download"],[class*="app-lead"],.index-footer
    { display: none !important; }
  `,
  // 淘宝 DOM 类名混淆严重,专用选择器实测后填充;先用通用组兜底,文字变体由 preload 扫描。
  taobao: ''
};
// B 站视频页「裁剪模式」专用 CSS(独立成组,便于改版后单独热修):
// 只保留播放器与标题,隐藏顶栏 / 右侧推荐 / 评论区;仅在播放模式的完整页兜底下注入,
// 不影响普通刷信息流时点进视频页的完整浏览体验。
const FEED_HIDE_CSS_BILI_VIDEO = `
  .bili-header,#commentapp,.right-container,.activity-m-v1,.video-special-guide,
  .video-pod, .video-info-container .video-info-detail-list
  { display: none !important; }
  .left-container,.video-container-v1,.plp-l
  { width: 100% !important; max-width: 100% !important; }
`;

// 信息流布局的第一层兜底。页面结构改版时,feed_preload.js 会再给识别到的卡片
// 添加 qagent-bili-feed-card 类;这里同时保留基于属性/class 的宽松选择器,
// 避免因为 B 站某一次 class hash 变化而完全失效。
const FEED_LAYOUT_CSS = {
  bilibili: `
    html,body,#app,#i_cecream { min-width: 0 !important; overflow-x: hidden !important; }
    #i_cecream, #i_cecream > .bili-feed4, [class*="feed4-layout"], [class*="feed-grid"] {
      max-width: none !important;
      width: 100% !important;
    }
    [class*="feed-card"], [class*="video-card"], .qagent-bili-feed-card {
      min-width: 0 !important;
      max-width: none !important;
    }
    .qagent-bili-feed-grid {
      display: grid !important;
      grid-template-columns: repeat(2, minmax(0, 1fr)) !important;
      gap: 12px !important;
      align-items: start !important;
    }
    .qagent-bili-feed-grid > .qagent-bili-feed-card {
      width: auto !important;
      margin: 0 !important;
    }
  `,
  douyin: `
    /* 抖音电脑版的推荐流会保留 72px 左侧导航和 628px 的最小根布局。
       小窗不能只隐藏横向溢出，否则视频会被裁掉；这里把真实播放器重排到可用视口。 */
    html,body,#root,#dark {
      width: 100vw !important;
      min-width: 0 !important;
      max-width: none !important;
      height: 100% !important;
      overflow: hidden !important;
      background: #000 !important;
    }
    #douyin-navigation,
    #douyin-header,
    #douyin-right-container > .douyin-header,
    .douyin-header,
    /* 登录弹层的外层是随机 id/class；只隐藏内层 article 会留下整屏遮罩。 */
    [id^="login-full-panel-"],
    [class*="fe8GGOyG"],
    #login-panel-new,
    #douyin-login-new-id,
    #douyin_login_comp_flat_panel,
    #douyin_login_landing_flat_container {
      display: none !important;
    }
    #douyin-right-container {
      position: fixed !important;
      inset: 0 !important;
      width: 100vw !important;
      min-width: 0 !important;
      max-width: none !important;
      height: 100vh !important;
      margin: 0 !important;
      padding: 0 !important;
      display: block !important;
    }
    /* 当前抖音精选页不再使用旧版 #slidelist，而是两列瀑布流。
       把真实内容根节点固定到小窗内，避免 668px 桌面最小宽度把右半列裁掉。 */
    #douyin-right-container > .live-detail-portal-anchor-wrapper,
    #douyin-right-container > [class*="portal-anchor-wrapper"],
    #douyin-right-container > [class*="FJW1IOm9"] {
      position: fixed !important;
      top: 64px !important;
      right: 0 !important;
      bottom: 0 !important;
      left: 0 !important;
      width: 100vw !important;
      height: calc(100vh - 64px) !important;
      min-width: 0 !important;
      max-width: none !important;
      margin: 0 !important;
      padding: 0 !important;
      overflow: hidden !important;
    }
    #slidelist,
    #slidelist [data-e2e="slideList"],
    .recommend-slidelist {
      position: fixed !important;
      top: 64px !important;
      right: 0 !important;
      bottom: 0 !important;
      left: 0 !important;
      width: 100vw !important;
      height: calc(100vh - 64px) !important;
      min-width: 0 !important;
      max-width: none !important;
      margin: 0 !important;
      padding: 0 !important;
      overflow: hidden !important;
    }
    /* 抖音当前精选页的内部滚动层和网格。窄窗只保留单列，卡片与图片宽度随视口收缩。 */
    #douyin-right-container [class*="parent-route-container"],
    #douyin-right-container [class*="discover-tab-container"],
    #douyin-right-container [class*="semi-tabs-content"],
    #douyin-right-container [class*="semi-tabs-pane"],
    #douyin-right-container [class*="jingxuan-scroll-element"],
    #douyin-right-container [class*="jingxuanFeedList"] {
      width: 100% !important;
      min-width: 0 !important;
      max-width: none !important;
      box-sizing: border-box !important;
    }
    #douyin-right-container [class*="parent-route-container"],
    #douyin-right-container [class*="semi-tabs-content"] {
      height: 100% !important;
      min-height: 0 !important;
      overflow-x: hidden !important;
      overflow-y: auto !important;
    }
    #douyin-right-container [class*="jingxuan-scroll-element"],
    #douyin-right-container [class*="jingxuanFeedList"] {
      height: auto !important;
      min-height: 100% !important;
      overflow: visible !important;
    }
    #douyin-right-container [class*="vg6ZqNFG"] {
      display: grid !important;
      grid-template-columns: minmax(0, 1fr) !important;
      width: 100% !important;
      min-width: 0 !important;
      max-width: none !important;
      box-sizing: border-box !important;
      gap: 16px !important;
      padding: 0 12px 24px !important;
    }
    #douyin-right-container [class*="discover-video-card-item"],
    #douyin-right-container [class*="waterfall-videoCardContainer"] {
      width: 100% !important;
      min-width: 0 !important;
      max-width: none !important;
      box-sizing: border-box !important;
    }
    #douyin-right-container [class*="videoImage"],
    #douyin-right-container img[class*="discover-video-card-img"] {
      width: 100% !important;
      max-width: none !important;
      aspect-ratio: 16 / 9 !important;
      height: auto !important;
      object-fit: cover !important;
    }
    #slidelist > *,
    #slidelist [data-e2e="slideList"] > *,
    .recommend-slidelist > * {
      width: 100% !important;
      min-width: 0 !important;
      max-width: none !important;
    }
    #slidelist .xg-video-container,
    #slidelist .xgplayer,
    #slidelist .basePlayerContainer,
    #slidelist .slider-video {
      width: 100% !important;
      height: 100% !important;
      min-width: 0 !important;
      max-width: none !important;
      max-height: none !important;
    }
    #slidelist video,
    #slidelist .xg-video-container video {
      display: block !important;
      width: 100% !important;
      height: 100% !important;
      max-width: none !important;
      max-height: none !important;
      object-fit: cover !important;
    }
    [class*="video-card"], [class*="feed-card"], [data-e2e*="feed"] {
      max-width: 100vw !important;
      min-width: 0 !important;
    }
  `
};

// ---- B 站本地播放:官方外链播放器优先 + 官方视频页裁剪兜底 ----
// 解析只做本地字符串处理;短链仅跟随官方 302 跳转,不调用任何非官方接口。
const BILI_PLAYER_PAGE_BASE = 'https://player.bilibili.com/player.html';
const BILI_VIDEO_PAGE_BASE = 'https://www.bilibili.com/video';

function parseBiliVideoInput(rawInput) {
  const input = String(rawInput || '').trim();
  if (!input) return null;
  // b23.tv 短链:标记为待跟随 302,拿到最终 URL 后再走一遍解析。
  const shortMatch = input.match(/(?:https?:\/\/)?b23\.tv\/[A-Za-z0-9]+/i);
  if (shortMatch) {
    return { shortUrl: shortMatch[0].startsWith('http') ? shortMatch[0] : `https://${shortMatch[0]}` };
  }
  const pageMatch = input.match(/[?&]p=(\d+)/);
  const page = pageMatch ? Math.max(1, parseInt(pageMatch[1], 10)) : 1;
  // 完整链接或裸 BV 号(BV 号大小写敏感,不转小写)。
  const bvidMatch = input.match(/BV[0-9A-Za-z]{8,12}/);
  if (bvidMatch) return { bvid: bvidMatch[0], page };
  // av 号:官方外链播放器原生支持 aid,无需换算 BV。
  const aidMatch = input.match(/av(\d{2,})/i);
  if (aidMatch) return { aid: aidMatch[1], page };
  return null;
}

// b23.tv 短链解析:HTTPS GET 只读 302 的 Location 头随即断开,不下载目标页面,
// 不调用任何非官方接口。不成功时提示用户粘贴完整链接。
// (不用 net.fetch:manual 模式会抛「Redirect was cancelled」,follow 模式拿不到最终 URL。)
function resolveBiliShortUrl(shortUrl) {
  return new Promise((resolve) => {
    let settled = false;
    const finish = (value) => {
      if (!settled) {
        settled = true;
        resolve(value);
      }
    };
    try {
      const request = https.request(shortUrl, {
        method: 'GET',
        headers: { 'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36' }
      }, (response) => {
        const location = response.headers?.location;
        const isRedirect = response.statusCode >= 300 && response.statusCode < 400;
        request.destroy();
        finish(isRedirect && location && /^https?:\/\//i.test(location) ? location : null);
      });
      request.on('error', () => finish(null));
      request.end();
    } catch (error) {
      finish(null);
    }
  });
}

function buildBiliPlaybackUrl(video) {
  if (!video || (!video.bvid && !video.aid)) return null;
  if (video.mode === 'page') {
    const base = video.bvid
      ? `${BILI_VIDEO_PAGE_BASE}/${video.bvid}`
      : `${BILI_VIDEO_PAGE_BASE}/av${video.aid}`;
    return video.page > 1 ? `${base}?p=${video.page}` : base;
  }
  const params = new URLSearchParams();
  if (video.bvid) params.set('bvid', video.bvid);
  if (video.aid) params.set('aid', video.aid);
  if (video.page > 1) params.set('page', String(video.page));
  params.set('high_quality', '1');
  params.set('danmaku', video.danmaku ? '1' : '0');
  params.set('autoplay', video.autoplay === false ? '0' : '1');
  return `${BILI_PLAYER_PAGE_BASE}?${params.toString()}`;
}

function resolveFeedChannelKey(urlString) {
  if (typeof urlString !== 'string') return null;
  try {
    const host = new URL(urlString).hostname.toLowerCase();
    for (const [key, meta] of Object.entries(FEED_CHANNELS)) {
      if (host === meta.host || host.endsWith(`.${meta.host}`)) return key;
    }
  } catch (error) { /* 非法地址不归属任何渠道 */ }
  return null;
}

// ---- 视频小窗状态记忆(persist 在 config.json 的 feed 字段) ----
function ensureFeedState() {
  const raw = readConfig().feed;
  const feed = raw && typeof raw === 'object' ? raw : {};
  const prevVideo = feed.video && typeof feed.video === 'object' ? feed.video : {};
  const channels = {};
  for (const key of Object.keys(FEED_CHANNELS)) {
    const prev = feed.channels && typeof feed.channels[key] === 'object' ? feed.channels[key] : {};
    channels[key] = {
      url: typeof prev.url === 'string' ? prev.url : null,
      zoom: Number(prev.zoom) || 1,
      bounds: prev.bounds && typeof prev.bounds === 'object' ? prev.bounds : null,
      layoutBounds: prev.layoutBounds && typeof prev.layoutBounds === 'object'
        ? {
          feed: prev.layoutBounds.feed && typeof prev.layoutBounds.feed === 'object' ? prev.layoutBounds.feed : null,
          player: prev.layoutBounds.player && typeof prev.layoutBounds.player === 'object' ? prev.layoutBounds.player : null
        }
        : { feed: null, player: null }
    };
  }
  return {
    pinned: feed.pinned !== false,
    channel: FEED_CHANNELS[feed.channel] ? feed.channel : 'bilibili',
    channels,
    // B 站本地播放状态:上次播放的视频、分 P 与播放模式(player=外链播放器 / page=官方视频页裁剪)。
    // 重开小窗时恢复;弹幕与自动播放作为持久化偏好。
    video: {
      active: Boolean(prevVideo.active),
      bvid: typeof prevVideo.bvid === 'string' && prevVideo.bvid ? prevVideo.bvid : null,
      aid: prevVideo.aid != null && String(prevVideo.aid).match(/^\d+$/) ? String(prevVideo.aid) : null,
      page: Math.max(1, Number(prevVideo.page) || 1),
      mode: prevVideo.mode === 'page' ? 'page' : 'player',
      danmaku: prevVideo.danmaku === true,
      autoplay: prevVideo.autoplay !== false
    }
  };
}

function patchFeedVideo(partial) {
  const state = ensureFeedState();
  patchFeedMeta({ video: { ...state.video, ...partial } });
}

function patchFeedMeta(partial) {
  patchConfig({ feed: { ...ensureFeedState(), ...partial } });
}

function patchFeedChannel(channelKey, partial) {
  if (!FEED_CHANNELS[channelKey]) return;
  const state = ensureFeedState();
  state.channels[channelKey] = { ...state.channels[channelKey], ...partial };
  patchFeedMeta({ channels: state.channels });
}

let petWindow = null;
let chatWindow = null;
let novelWindow = null;
let feedWindow = null;
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
// 久坐/喝水/睡觉信号：每 60s 采样系统空闲时间，连续活跃（空闲<5 分钟视为仍在活跃）
// 的分钟数随每次 proactive claim 上报后端物化对应事件。独立于 claim 与勿扰状态，
// core 启动后一直累计，供 claim 随时取当前值。
let activeStreakMinutes = 0;
let idleStreakTimer = null;
// 自定义宠物列表(从后端 GET /api/custom_pets 拉取):null=尚未拉取,数组=拉取结果,
// 拉取失败时保持 null/旧值,托盘「切换宠物」菜单静默退回三只预置。
let customPetList = null;
let petBoundsSaveTimer = null;

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

// 桌面端与本地后端之间的共享令牌：首次启动时生成并持久化到生效的 env 文件(0600)。
// 后端据此拒绝其他本机进程/网页(如 DNS rebinding 过来的浏览器请求)对 API 的未授权访问。
function ensureBackendApiKey() {
  const envPath = effectiveEnvPath();
  const existing = parseEnvFile(envPath).API_KEY || process.env.API_KEY;
  if (existing) return existing;
  const key = crypto.randomBytes(32).toString('hex');
  const current = fs.existsSync(envPath) ? fs.readFileSync(envPath, 'utf8') : '';
  const separator = current && !current.endsWith('\n') ? '\n' : '';
  fs.mkdirSync(path.dirname(envPath), { recursive: true });
  fs.writeFileSync(envPath, `${current}${separator}API_KEY=${key}\n`, { encoding: 'utf8', mode: 0o600 });
  try {
    fs.chmodSync(envPath, 0o600);
  } catch (error) {
    // Windows does not implement Unix file modes.
  }
  return key;
}

function getBackendApiKey() {
  return parseEnvFile(effectiveEnvPath()).API_KEY || process.env.API_KEY || '';
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
    'API_KEY',
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
    // file:// 面板直连本机 API 时 Origin 为 null;有 API_KEY 鉴权兜底,放行 null 源无额外风险
    'CORS_ORIGINS=http://localhost:10000,http://127.0.0.1:10000,null',
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
    autostart: false,
    pet_bounds: null,
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
  // 原子写入:先写临时文件再 rename,避免进程中途被杀留下半个 JSON,
  // 否则下次 readConfig 解析失败会把配置整体重置成默认值(pet_type 回退 hot_dog)。
  const tmpPath = `${configPath()}.tmp`;
  fs.writeFileSync(tmpPath, JSON.stringify(config, null, 2), 'utf8');
  fs.renameSync(tmpPath, configPath());
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
  const apiKey = getBackendApiKey();
  const headers = {
    'X-User-Id': cfg.user_id || 'anonymous',
    ...(apiKey ? { Authorization: `Bearer ${apiKey}` } : {}),
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
    // 环境变量优先级高于 env 文件,保证后端与本进程持有同一令牌
    API_KEY: ensureBackendApiKey(),
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

async function ensureSessionInternal(depth = 0) {
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

  // 并发共享 sessionInitPromise 期间用户可能又切换了宠物(如托盘快速连点):
  // 配置身份已变则不落地本次旧宠物会话,以最新身份重试(限两次,避免极端抖动死循环)。
  const latest = readConfig();
  const identityChanged = latest.pet_type !== body.pet_type
    || (latest.custom_pet_id || null) !== (body.custom_pet_id || null);
  if (identityChanged && depth < 2) {
    return ensureSessionInternal(depth + 1);
  }

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

// 托盘图标:软件徽标(企鹅)剪影,做成 macOS template image——
// 浅色菜单栏自动显示深色,深色菜单栏自动显示浅色,选中高亮态也由系统处理。
function getTrayIcon() {
  const source = nativeImage.createFromPath(path.join(desktopRoot, 'assets', 'tray-icon.png'));
  if (source.isEmpty()) return nativeImage.createEmpty();
  const icon = nativeImage.createEmpty();
  icon.addRepresentation({ scaleFactor: 1, width: 18, height: 18, buffer: source.resize({ width: 18 }).toPNG() });
  icon.addRepresentation({ scaleFactor: 2, width: 18, height: 18, buffer: source.resize({ width: 36 }).toPNG() });
  icon.setTemplateImage(true);
  return icon;
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
  // 当前宠物显示名:自定义宠物优先用拉取到的 pet_name,未拉取到时退回 pet_id。
  const currentPetName = cfg.pet_type === 'custom' && cfg.custom_pet_id
    ? (customPetList?.find((pet) => pet.pet_id === cfg.custom_pet_id)?.pet_name || cfg.custom_pet_id)
    : (cfg.pet_type || DEFAULT_PET_TYPE);
  // 自定义宠物 radio 项(预置项全部未选中时,这些项也不选中,天然互斥)。
  const customPetItems = Array.isArray(customPetList) && customPetList.length
    ? [
        { type: 'separator' },
        ...customPetList.map((pet) => ({
          label: pet.pet_name,
          type: 'radio',
          checked: cfg.pet_type === 'custom' && cfg.custom_pet_id === pet.pet_id,
          click: async () => {
            patchConfig({
              pet_type: 'custom',
              custom_pet_id: pet.pet_id,
              // 沿用 custom_pet_raw_type 约定:自定义宠物的原始动物类型,用于头像图片查找
              custom_pet_raw_type: pet.pet_type || null,
              session_id: null
            });
            if (webWindow && !webWindow.isDestroyed()) {
              webWindow.close();
            }
            await ensureSession().catch(() => null);
            updateTrayMenu();
            sendToWindows('config-updated', readConfig());
            sendToWindows('pet-refresh');
          }
        }))
      ]
    : [];
  const template = [
    { label: '显示桌宠', click: () => showPetWindow() },
    { label: '打开完整 Web 面板', click: () => openWebPanel() },
    { label: '摸鱼·小说阅读', click: () => toggleNovelWindow() },
    {
      label: '摸鱼·刷一刷',
      submenu: [
        { label: 'B站', click: () => openFeedChannel('bilibili') },
        { label: '小红书', click: () => openFeedChannel('xiaohongshu') },
        { label: '抖音', click: () => openFeedChannel('douyin') },
        { label: '快手', click: () => openFeedChannel('kuaishou') },
        { label: '淘宝', click: () => openFeedChannel('taobao') },
        { type: 'separator' },
        { label: '播放 B 站链接…', click: () => openFeedVideoPrompt() },
        { label: `老板键·隐藏/显示小窗 (${FEED_BOSS_KEY})`, click: () => toggleFeedBossKey() },
        { label: '显示/隐藏视频小窗', click: () => toggleFeedWindow() }
      ]
    },
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
      label: `切换宠物（当前：${currentPetName}）`,
      submenu: [
        ...PRESET_PETS.map((petType) => ({
          label: petType,
          type: 'radio',
          checked: (cfg.pet_type || DEFAULT_PET_TYPE) === petType,
          click: async () => {
            patchConfig({ pet_type: petType, custom_pet_id: null, custom_pet_raw_type: null, session_id: null });
            if (webWindow && !webWindow.isDestroyed()) {
              webWindow.close();
            }
            await ensureSession().catch(() => null);
            updateTrayMenu();
            sendToWindows('config-updated', readConfig());
            sendToWindows('pet-refresh');
          }
        })),
        ...customPetItems
      ]
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

// 异步拉取后端自定义宠物列表刷新托盘「切换宠物」菜单。
// 后端就绪前托盘可能已创建:拉取失败静默退回预置三只,不阻塞、不弹错。
async function refreshCustomPetList() {
  try {
    const result = await requestJson('/api/custom_pets');
    const pets = Array.isArray(result?.pets) ? result.pets : [];
    customPetList = pets
      .filter((pet) => pet && typeof pet.pet_id === 'string' && pet.pet_id)
      .map((pet) => ({ pet_id: pet.pet_id, pet_name: String(pet.pet_name || pet.pet_id), pet_type: pet.pet_type || null }));
  } catch (error) {
    // 静默:菜单退回预置三只(拉取成功后会有真实列表)。
    return;
  }
  updateTrayMenu();
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
      sandbox: true
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
    width: 152,
    height: 176,
    show: false,
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
      sandbox: true
    }
  });

  petWindow.setAlwaysOnTop(true, 'floating');
  // 恢复上次拖拽到的位置:show:false 创建,setPosition 之后再 show,避免先闪一下默认位置。
  const savedBounds = clampBoundsToDisplays(readConfig().pet_bounds);
  if (savedBounds) {
    petWindow.setPosition(savedBounds.x, savedBounds.y);
  }
  petWindow.show();
  // 拖拽(及程序化移动)都会触发 move:节流 400ms 落盘,与 feed 小窗的 queueSaveFeedBounds 同款。
  petWindow.on('move', queueSavePetBounds);
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
      sandbox: true
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

function createNovelWindow() {
  if (novelWindow && !novelWindow.isDestroyed()) return novelWindow;

  novelWindow = new BrowserWindow({
    width: 420,
    height: 560,
    show: false,
    resizable: false,
    alwaysOnTop: true,
    skipTaskbar: true,
    transparent: true,
    frame: false,
    hasShadow: false,
    title: '摸鱼·小说阅读',
    webPreferences: {
      preload: path.join(desktopRoot, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true
    }
  });

  novelWindow.setAlwaysOnTop(true, 'floating');
  novelWindow.loadFile(path.join(rendererRoot, 'novel.html'));
  novelWindow.on('close', (event) => {
    if (!isQuitting) {
      event.preventDefault();
      novelWindow.hide();
    }
  });
  novelWindow.on('closed', () => {
    novelWindow = null;
  });
}

function toggleNovelWindow() {
  if (!novelWindow) createNovelWindow();

  if (novelWindow.isVisible()) {
    novelWindow.hide();
    return;
  }

  const petBounds = petWindow?.getBounds();
  if (petBounds) {
    novelWindow.setPosition(Math.max(0, petBounds.x - 440), Math.max(0, petBounds.y - 60));
  }
  novelWindow.show();
  novelWindow.focus();
}

let pendingNovelBookId = null;

function showNovelWindow() {
  if (!novelWindow) createNovelWindow();
  if (!novelWindow.isVisible()) {
    const petBounds = petWindow?.getBounds();
    if (petBounds) {
      novelWindow.setPosition(Math.max(0, petBounds.x - 440), Math.max(0, petBounds.y - 60));
    }
    novelWindow.show();
  }
  novelWindow.focus();
}

function openNovelBook(bookId) {
  // 从 Web 面板跳转「桌面阅读」:显示阅读窗并把书交给渲染进程。
  // 窗口可能尚未加载完,先把 bookId 暂存,加载完成后再投递。
  pendingNovelBookId = bookId || null;
  if (!novelWindow) createNovelWindow();
  const deliver = () => {
    if (pendingNovelBookId && novelWindow && !novelWindow.isDestroyed()) {
      novelWindow.webContents.send('novel-open-book', pendingNovelBookId);
      pendingNovelBookId = null;
    }
  };
  if (novelWindow.webContents.isLoading()) {
    novelWindow.webContents.once('did-finish-load', deliver);
  } else {
    deliver();
  }
  showNovelWindow();
}

// 摸鱼·视频小窗:置顶、可拖拽、可缩到很小的小窗,直接加载外部视频站页面。
// 登录态保存在独立 partition(persist:feed) 中,与主面板隔离;不碰接口与凭证。
let feedSessionConfigured = false;
function configureFeedSession() {
  if (feedSessionConfigured) return;
  feedSessionConfigured = true;
  const allow = new Set(['media', 'mediaKeySystem', 'fullscreen', 'pointerLock', 'clipboard-sanitized-write']);
  const feedSession = session.fromPartition('persist:feed');
  // 播放/全屏等放行,通知/地理位置等一律拒绝:摸鱼小窗不需要这些权限。
  feedSession.setPermissionRequestHandler((_contents, permission, callback) => callback(allow.has(permission)));
  feedSession.setPermissionCheckHandler((_contents, permission) => allow.has(permission));
}

function clampFeedBounds(bounds) {
  const minWidth = 400;
  const minHeight = 300;
  if (!bounds || !Number.isFinite(bounds.width) || !Number.isFinite(bounds.height)) return null;
  return {
    x: Math.max(0, Math.round(Number(bounds.x) || 0)),
    y: Math.max(0, Math.round(Number(bounds.y) || 0)),
    width: Math.max(minWidth, Math.round(bounds.width)),
    height: Math.max(minHeight, Math.round(bounds.height))
  };
}

// ---- 多显示器适配 ----
// screen 只能在 app ready 之后使用;以下函数均只在运行期(窗口创建/事件回调)被调用。
function rectsIntersect(a, b) {
  return a.x < b.x + b.width && a.x + a.width > b.x && a.y < b.y + b.height && a.y + a.height > b.y;
}

// bounds 与任一显示器 workArea 相交(含被包含)则原样返回;
// 否则(拔掉显示器后位置悬空)保持尺寸移入主显示器 workArea,必要时缩到放得下。
function clampBoundsToDisplays(bounds) {
  if (!bounds || !Number.isFinite(bounds.x) || !Number.isFinite(bounds.y)) return null;
  const normalized = {
    x: Math.round(bounds.x),
    y: Math.round(bounds.y),
    width: Math.max(1, Math.round(Number(bounds.width) || 1)),
    height: Math.max(1, Math.round(Number(bounds.height) || 1))
  };
  const displays = screen.getAllDisplays();
  for (const display of displays) {
    if (rectsIntersect(normalized, display.workArea)) return normalized;
  }
  const primary = screen.getPrimaryDisplay().workArea;
  if (normalized.width > primary.width) normalized.width = primary.width;
  if (normalized.height > primary.height) normalized.height = primary.height;
  normalized.x = Math.min(Math.max(normalized.x, primary.x), primary.x + primary.width - normalized.width);
  normalized.y = Math.min(Math.max(normalized.y, primary.y), primary.y + primary.height - normalized.height);
  return normalized;
}

// 桌宠 bounds 保存前的合理性检查:坐标/尺寸必须是有限数(负坐标合法,副屏可以在主屏左侧)。
function clampPetBounds(bounds) {
  if (!bounds) return null;
  const x = Number(bounds.x);
  const y = Number(bounds.y);
  const width = Number(bounds.width);
  const height = Number(bounds.height);
  if (![x, y, width, height].every(Number.isFinite)) return null;
  return { x: Math.round(x), y: Math.round(y), width: Math.round(width), height: Math.round(height) };
}

function queueSavePetBounds() {
  clearTimeout(petBoundsSaveTimer);
  petBoundsSaveTimer = setTimeout(() => {
    if (!petWindow || petWindow.isDestroyed()) return;
    const bounds = clampPetBounds(petWindow.getBounds());
    if (bounds) patchConfig({ pet_bounds: bounds });
  }, 400);
}

// 显示器移除/分辨率变化后,把仍可见的桌宠窗与小窗拉回有效屏幕内。
function clampWindowsToDisplays() {
  if (petWindow && !petWindow.isDestroyed() && petWindow.isVisible()) {
    const next = clampBoundsToDisplays(petWindow.getBounds());
    if (next) petWindow.setBounds(next);
  }
  if (feedWindow && !feedWindow.isDestroyed() && feedWindow.isVisible()) {
    const next = clampBoundsToDisplays(feedWindow.getBounds());
    if (next) feedWindow.setBounds(next);
  }
}

function defaultFeedBounds(channelKey) {
  const meta = FEED_CHANNELS[channelKey];
  // 渠道自定义默认尺寸(如淘宝 960×700)优先于 mobile/桌面分组默认。
  if (meta?.bounds) return { ...meta.bounds };
  return meta?.mobile ? { ...FEED_MOBILE_BOUNDS } : { ...FEED_DESKTOP_BOUNDS };
}

function getFeedLayoutMode(channelKey = feedActiveChannel) {
  return channelKey === 'bilibili' && ensureFeedState().video.active ? 'player' : 'feed';
}

function getFeedLayoutDefaultBounds(channelKey, mode = 'feed') {
  const layout = FEED_LAYOUTS[channelKey]?.[mode];
  return layout ? { ...layout } : defaultFeedBounds(channelKey);
}

function isCompatibleFeedLayoutBounds(channelKey, mode, bounds) {
  if (!bounds || !Number.isFinite(Number(bounds.width)) || !Number.isFinite(Number(bounds.height))) return false;
  const width = Number(bounds.width);
  const height = Number(bounds.height);
  if (channelKey === 'douyin') return height >= width * 1.25;
  if (channelKey === 'bilibili' && mode === 'player') return width >= height * 1.45;
  if (channelKey === 'bilibili' && mode === 'feed') return width >= height * 1.15;
  return true;
}

function getRememberedFeedLayoutBounds(channelKey, mode) {
  const state = ensureFeedState();
  const channel = state.channels[channelKey] || {};
  const remembered = channel.layoutBounds?.[mode];
  if (isCompatibleFeedLayoutBounds(channelKey, mode, remembered)) return remembered;
  // 非专属布局渠道继续兼容旧版本只有 channels[key].bounds 的配置。
  // B站/抖音必须使用新的 feed/player 适配尺寸,不能把旧的通用 640×480 误当成布局记忆。
  if (!FEED_LAYOUTS[channelKey] && !channel.layoutBounds?.[mode]
    && isCompatibleFeedLayoutBounds(channelKey, mode, channel.bounds)) {
    return channel.bounds;
  }
  return null;
}

function saveFeedLayoutBounds(channelKey, mode, bounds) {
  if (!FEED_CHANNELS[channelKey] || !bounds) return;
  const state = ensureFeedState();
  const channel = state.channels[channelKey] || {};
  patchFeedChannel(channelKey, {
    bounds,
    layoutBounds: {
      ...(channel.layoutBounds || {}),
      [mode]: bounds
    }
  });
}

function applyFeedLayoutBounds(mode = getFeedLayoutMode(), { preserveCenter = true } = {}) {
  if (!feedWindow || feedWindow.isDestroyed()) return;
  const channelKey = feedActiveChannel;
  const target = getRememberedFeedLayoutBounds(channelKey, mode) || getFeedLayoutDefaultBounds(channelKey, mode);
  const current = feedWindow.getBounds();
  const x = preserveCenter ? current.x + Math.round((current.width - target.width) / 2) : current.x;
  const y = preserveCenter ? current.y + Math.round((current.height - target.height) / 2) : current.y;
  const next = clampBoundsToDisplays(clampFeedBounds({ x, y, ...target }));
  if (next) feedWindow.setBounds(next);
}

// 按当前渠道应用 UA(手机版竖屏 / 桌面版),跨渠道切换时自动切换。
let feedActiveChannel = 'bilibili';

function applyFeedChannelContext(channelKey) {
  patchFeedMeta({ channel: channelKey });
  feedActiveChannel = channelKey;
  if (!feedWindow || feedWindow.isDestroyed()) return;
  const targetUa = FEED_CHANNELS[channelKey]?.mobile ? FEED_MOBILE_UA : FEED_DEFAULT_UA;
  const contents = feedWindow.webContents;
  if (targetUa && contents.getUserAgent() !== targetUa) contents.setUserAgent(targetUa);
}

function applyFeedHideCss(contents) {
  if (!contents || contents.isDestroyed()) return;
  const key = resolveFeedChannelKey(contents.getURL());
  let css = FEED_HIDE_CSS_COMMON + (key ? (FEED_HIDE_CSS[key] || '') : '');
  if (key && !ensureFeedState().video.active) css += FEED_LAYOUT_CSS[key] || '';
  // 完整页裁剪兜底:仅在播放模式(page)下对 B 站视频页追加裁剪 CSS,
  // 普通刷信息流时点进视频页不受影响(维持完整浏览体验)。
  const playback = ensureFeedState().video;
  if (playback.active && playback.mode === 'page' && isBiliVideoPageUrl(contents.getURL())) {
    css += FEED_HIDE_CSS_BILI_VIDEO;
  }
  contents.insertCSS(css, { cssOrigin: 'user' }).catch(() => {});
}

function applyFeedZoomForActiveChannel() {
  if (!feedWindow || feedWindow.isDestroyed()) return;
  const state = ensureFeedState();
  feedWindow.webContents.setZoomFactor(state.channels[state.channel]?.zoom || 1);
}

let locationSaveTimer = null;
function saveFeedLocation(urlString) {
  const key = resolveFeedChannelKey(urlString);
  if (!key || !/^https?:\/\//i.test(urlString)) return;
  // 渠道切换立即生效;URL 落盘做节流,避免刷信息流时每划一条视频都写一次 config.json。
  if (feedActiveChannel !== key) {
    feedActiveChannel = key;
    patchFeedMeta({ channel: key });
  }
  clearTimeout(locationSaveTimer);
  locationSaveTimer = setTimeout(() => patchFeedChannel(key, { url: urlString }), 800);
}

let boundsSaveTimer = null;
function queueSaveFeedBounds() {
  clearTimeout(boundsSaveTimer);
  boundsSaveTimer = setTimeout(() => {
    if (!feedWindow || feedWindow.isDestroyed()) return;
    saveFeedLayoutBounds(feedActiveChannel, getFeedLayoutMode(), feedWindow.getBounds());
  }, 400);
}

function createFeedWindow() {
  if (feedWindow && !feedWindow.isDestroyed()) return feedWindow;
  configureFeedSession();

  const state = ensureFeedState();
  feedActiveChannel = state.channel;

  feedWindow = new BrowserWindow({
    width: 640,
    height: 480,
    minWidth: 400,
    minHeight: 300,
    show: false,
    frame: false,
    resizable: true,
    alwaysOnTop: state.pinned,
    skipTaskbar: true,
    hasShadow: false,
    title: '摸鱼·视频小窗',
    webPreferences: {
      preload: path.join(desktopRoot, 'feed_preload.js'),
      partition: 'persist:feed',
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true
    }
  });

  if (state.pinned) feedWindow.setAlwaysOnTop(true, 'floating');
  applyFeedChannelContext(feedActiveChannel);

  // 新窗口/弹窗一律留在小窗内打开,避免登录或播放流程被弹到外部中断。
  const win = feedWindow;
  win.webContents.setWindowOpenHandler(({ url }) => {
    if (/^https?:\/\//i.test(url)) {
      win.webContents.loadURL(url).catch(() => {});
    }
    return { action: 'deny' };
  });

  // SPA 路由(douyin/xhs 刷信息流不整页跳转)也要记录位置;整页导航后重注入遮盖 CSS 与记忆缩放。
  win.webContents.on('did-navigate', (_event, url) => {
    saveFeedLocation(url);
    applyFeedZoomForActiveChannel();
  });
  win.webContents.on('did-navigate-in-page', (_event, url) => saveFeedLocation(url));
  win.webContents.on('dom-ready', () => applyFeedHideCss(win.webContents));

  // 记住每个渠道的窗口位置/尺寸,下次打开即回。
  win.on('resize', queueSaveFeedBounds);
  win.on('move', queueSaveFeedBounds);

  // 关闭即真关闭:不拦截 close,销毁渲染进程即停止后台视频/网络播放;
  // 之后想再看,从托盘/Web 面板重新点入口会重建窗口。
  feedWindow.on('closed', () => {
    feedWindow = null;
  });

  // 上次在小窗里播放 B 站视频:直接恢复播放(外链播放器/完整页裁剪),否则恢复上次渠道页面。
  const playbackUrl = state.video.active ? buildBiliPlaybackUrl(state.video) : null;
  const rememberedUrl = state.channels[feedActiveChannel]?.url;
  win.loadURL(playbackUrl || rememberedUrl || FEED_CHANNELS[feedActiveChannel].url).catch(() => {});
  return feedWindow;
}

function positionFeedWindowNearPet() {
  if (!feedWindow || feedWindow.isDestroyed()) return;
  const petBounds = petWindow?.getBounds();
  const layoutMode = getFeedLayoutMode(feedActiveChannel);
  // 记忆位置先过基础钳制,再过显示器钳制:拔掉显示器后旧坐标可能完全悬空。
  const savedBounds = clampBoundsToDisplays(clampFeedBounds(
    getRememberedFeedLayoutBounds(feedActiveChannel, layoutMode)
  ));
  if (savedBounds) {
    // 该渠道/模式有记忆位置:原样恢复。
    feedWindow.setBounds(savedBounds);
  } else if (FEED_LAYOUTS[feedActiveChannel] || FEED_CHANNELS[feedActiveChannel]?.mobile || FEED_CHANNELS[feedActiveChannel]?.bounds) {
    // 抖音/B站按布局模式使用竖屏/双列/横屏默认尺寸,淘宝继续使用渠道自定义宽窗。
    const preferred = getFeedLayoutDefaultBounds(feedActiveChannel, layoutMode);
    const anchor = petBounds || { x: 800, y: 200 };
    const next = clampBoundsToDisplays({
      ...preferred,
      x: anchor.x - preferred.width - 40,
      y: anchor.y - 60
    });
    if (next) feedWindow.setBounds(next);
  } else if (petBounds) {
    // 按实际窗口宽度摆放:让弹窗右缘落在桌宠左缘附近,避免 520 是给旧尺寸写死的。
    const width = feedWindow.getBounds().width;
    feedWindow.setPosition(Math.max(0, petBounds.x - (width - 80)), Math.max(0, petBounds.y - 120));
  }
}

function showFeedWindow() {
  if (!feedWindow || feedWindow.isDestroyed()) createFeedWindow();
  if (!feedWindow.isVisible()) {
    positionFeedWindowNearPet();
  }
  feedWindow.show();
  feedWindow.focus();
  // 老板键隐藏时会静音;通过托盘菜单 / playBiliVideo / toggleFeedWindow 重新显示也恢复声音。
  resumeFeedMedia();
}

function toggleFeedWindow() {
  if (!feedWindow || feedWindow.isDestroyed()) {
    createFeedWindow();
  }
  if (feedWindow.isVisible()) {
    feedWindow.hide();
    return;
  }
  showFeedWindow();
}

// 「播放 B 站链接」小输入窗:托盘菜单没有输入框,用一个极简窗口接收 BV / av / 短链。
let videoPromptWindow = null;
function openFeedVideoPrompt() {
  if (videoPromptWindow && !videoPromptWindow.isDestroyed()) {
    videoPromptWindow.show();
    videoPromptWindow.focus();
    return;
  }
  videoPromptWindow = new BrowserWindow({
    width: 460,
    height: 210,
    resizable: false,
    minimizable: false,
    maximizable: false,
    fullscreenable: false,
    title: '播放 B 站视频',
    webPreferences: {
      preload: path.join(desktopRoot, 'preload_video_prompt.js'),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true
    }
  });
  videoPromptWindow.setMenuBarVisibility(false);
  videoPromptWindow.on('closed', () => {
    videoPromptWindow = null;
  });
  videoPromptWindow.loadFile(path.join(rendererRoot, 'video_prompt.html'));
}

// 老板键:小窗可见时立即静音暂停并隐藏;不可见时恢复显示。声音停得比窗口消失更早。
// audioMuted 确定性停声:跨域 iframe(官方外链播放器)内的 video 无法被父页面 JS pause,
// 但 webContents.audioMuted 对整个页面(含跨域 iframe)生效,作为兜底保证摸鱼隐蔽性。
function pauseFeedMedia() {
  if (!feedWindow || feedWindow.isDestroyed()) return;
  try { feedWindow.webContents.audioMuted = true; } catch (error) { /* 最佳努力 */ }
  feedWindow.webContents.executeJavaScript(
    '(function(){var m=document.querySelectorAll("video,audio");for(var i=0;i<m.length;i++){try{m[i].pause()}catch(e){}}return true})()'
  ).catch(() => {});
}

// 老板键显示小窗后恢复声音:audioMuted 状态会被复用 feedWindow 记住,显式恢复避免静音残留。
function resumeFeedMedia() {
  if (!feedWindow || feedWindow.isDestroyed()) return;
  try { feedWindow.webContents.audioMuted = false; } catch (error) { /* 最佳努力 */ }
}

function toggleFeedBossKey() {
  if (feedWindow && !feedWindow.isDestroyed() && feedWindow.isVisible()) {
    pauseFeedMedia();
    feedWindow.hide();
    return;
  }
  showFeedWindow();
  resumeFeedMedia();
}

// 打开视频小窗并直达指定网页渠道(B站/小红书/抖音/快手/淘宝)。托盘与 IPC 共用。
function openFeedChannel(channel) {
  const meta = FEED_CHANNELS[channel];
  if (!meta) return;
  clearFeedPlayback();
  // 先切渠道上下文(UA/激活渠道),新建小窗也会直接按目标渠道载入页面与默认尺寸。
  applyFeedChannelContext(channel);
  showFeedWindow();
  // 小窗已可见时 showFeedWindow 不会重新布局:按目标渠道的记忆/默认尺寸补齐(与浮条导航一致)。
  const savedBounds = clampFeedBounds(ensureFeedState().channels[channel]?.bounds);
  if (feedWindow.isVisible() && (savedBounds || FEED_LAYOUTS[channel] || meta.mobile || meta.bounds)) {
    positionFeedWindowNearPet();
  }
  const state = ensureFeedState();
  const url = state.channels[channel]?.url || meta.url;
  feedWindow.webContents.loadURL(url).catch(() => {});
}

// 是否为 B 站官方视频页(www.bilibili.com/video/…)。
function isBiliVideoPageUrl(urlString) {
  if (typeof urlString !== 'string') return false;
  try {
    const url = new URL(urlString);
    return /(^|\.)bilibili\.com$/.test(url.hostname.toLowerCase()) && url.pathname.startsWith('/video/');
  } catch (error) {
    return false;
  }
}

// 摸鱼·B 站本地播放(feed:play-video 入口):本地解析链接 → 官方外链播放器直载。
// 外链播放器被 UP 主关闭时,由浮条「完整页面」按钮切到官方视频页裁剪兜底。
async function playBiliVideo(rawInput) {
  if (typeof rawInput !== 'string' || !rawInput.trim()) {
    return { ok: false, error: '请输入 B 站视频链接或 BV / av 号' };
  }
  let video = parseBiliVideoInput(rawInput);
  if (!video) {
    return { ok: false, error: '无法识别的链接。支持 BV / av / 分 P 链接与 b23.tv 短链' };
  }
  if (video.shortUrl) {
    const finalUrl = await resolveBiliShortUrl(video.shortUrl);
    video = finalUrl ? parseBiliVideoInput(finalUrl) : null;
    if (!video) {
      return { ok: false, error: '短链解析失败，请粘贴完整视频链接（www.bilibili.com/video/…）' };
    }
  }
  // 先切回 B 站桌面渠道上下文(UA/位置),再落盘播放状态,保证新开小窗时也按播放模式恢复。
  applyFeedChannelContext('bilibili');
  const state = ensureFeedState();
  const nextVideo = {
    active: true,
    bvid: video.bvid || null,
    aid: video.aid || null,
    page: video.page || 1,
    mode: 'player',
    danmaku: state.video.danmaku,
    autoplay: state.video.autoplay
  };
  patchFeedVideo(nextVideo);

  // 已存在的小窗直接换 URL;新建小窗会按 video.active 自动恢复播放地址,避免二次加载。
  const windowExisted = Boolean(feedWindow && !feedWindow.isDestroyed());
  showFeedWindow();
  applyFeedLayoutBounds('player');
  if (windowExisted && feedWindow && !feedWindow.isDestroyed()) {
    feedWindow.webContents.loadURL(buildBiliPlaybackUrl(nextVideo)).catch(() => {});
  }
  return { ok: true };
}

// 浮条「完整页面 / 外链播放器」:两种播放模式手动切换,不做脆弱的 DOM 自动检测。
function toggleBiliPlayMode() {
  const video = ensureFeedState().video;
  if (!video.active || (!video.bvid && !video.aid)) {
    return { ok: false, error: '当前没有正在播放的 B 站视频' };
  }
  const nextMode = video.mode === 'player' ? 'page' : 'player';
  patchFeedVideo({ mode: nextMode });
  if (feedWindow && !feedWindow.isDestroyed()) {
    feedWindow.webContents.loadURL(buildBiliPlaybackUrl({ ...video, mode: nextMode })).catch(() => {});
  }
  return { ok: true, mode: nextMode };
}

// 播放偏好(弹幕 / 自动播放):持久化记忆;外链播放器模式下重载即热生效。
function setBiliPlayPref(partial) {
  const video = ensureFeedState().video;
  const next = {
    danmaku: typeof partial.danmaku === 'boolean' ? partial.danmaku : video.danmaku,
    autoplay: typeof partial.autoplay === 'boolean' ? partial.autoplay : video.autoplay
  };
  patchFeedVideo(next);
  if (video.active && video.mode === 'player' && feedWindow && !feedWindow.isDestroyed()) {
    feedWindow.webContents.loadURL(buildBiliPlaybackUrl({ ...video, ...next })).catch(() => {});
  }
  return { ok: true, danmaku: next.danmaku, autoplay: next.autoplay };
}

// 离开播放模式(切渠道 / 浮条导航回信息流):清除播放态,小窗回到普通刷视频记忆。
function clearFeedPlayback() {
  if (!ensureFeedState().video.active) return;
  patchFeedVideo({ active: false });
  if (feedActiveChannel === 'bilibili' && feedWindow && !feedWindow.isDestroyed()) {
    applyFeedLayoutBounds('feed');
  }
}

// 统一导航入口:preload 浮条/手动跳转都走这里,自动识别渠道、切 UA、记位置。
function navigateFeed(rawUrl) {
  if (!feedWindow || feedWindow.isDestroyed() || typeof rawUrl !== 'string' || !/^https?:\/\//i.test(rawUrl)) return false;
  // 浮条导航回各平台网页 = 离开播放模式,清除播放态恢复普通刷视频记忆。
  clearFeedPlayback();
  const key = resolveFeedChannelKey(rawUrl);
  if (key && key !== feedActiveChannel) {
    applyFeedChannelContext(key);
    const savedBounds = clampFeedBounds(ensureFeedState().channels[key]?.bounds);
    if (savedBounds || FEED_LAYOUTS[key] || FEED_CHANNELS[key].mobile || FEED_CHANNELS[key].bounds) {
      positionFeedWindowNearPet();
    }
  } else if (!key) {
    // 离开已知平台(如搜索结果跳转外站):恢复桌面 UA,避免手机版样式污染普通网页。
    if (feedWindow.webContents.getUserAgent() !== FEED_DEFAULT_UA) {
      feedWindow.webContents.setUserAgent(FEED_DEFAULT_UA);
    }
  }
  feedWindow.webContents.loadURL(rawUrl).catch(() => {});
  return true;
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
  const apiKey = getBackendApiKey();
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
        sandbox: true,
        // 面板从打包文件加载(file://)时跨源直连本机 API;后端 CORS 已放行 null 源,
        // 且 API 需 Bearer 令牌(经启动参数注入 preload),无需关闭同源校验。
        additionalArguments: [
          `--qagent-user-id=${cfg.user_id || ''}`,
          `--qagent-session-id=${cfg.session_id || ''}`,
          `--qagent-pet-type=${cfg.pet_type || DEFAULT_PET_TYPE}`,
          `--qagent-custom-pet-id=${cfg.custom_pet_id || ''}`,
          `--qagent-api-base=${baseUrl}`,
          `--qagent-api-key=${apiKey}`
        ]
      }
    });

    webWindow.on('closed', () => {
      webWindow = null;
    });
  }

  webWindow.loadFile(path.join(projectRoot, 'frontend', 'chat.html'));
  webWindow.show();
  webWindow.focus();
}

function sendToWindows(channel, payload) {
  for (const win of [petWindow, chatWindow, webWindow]) {
    if (win && !win.isDestroyed()) {
      win.webContents.send(channel, payload);
    }
  }
}

function tickActiveStreak() {
  try {
    activeStreakMinutes = powerMonitor.getSystemIdleTime() < 300 ? activeStreakMinutes + 1 : 0;
  } catch (error) {
    // 个别平台拿不到系统空闲时间时保持原值，不阻塞后续 claim
  }
}

function startIdleStreakTracking() {
  if (idleStreakTimer) clearInterval(idleStreakTimer);
  tickActiveStreak();
  idleStreakTimer = setInterval(tickActiveStreak, 60 * 1000);
}

async function claimProactiveEvent() {
  if (proactiveClaimInFlight || !backendBaseUrl || readConfig().dnd) return null;
  proactiveClaimInFlight = true;
  try {
    const cfg = await ensureSession();
    const timezone = Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC';
    let idleSeconds = 0;
    try { idleSeconds = powerMonitor.getSystemIdleTime(); } catch (error) { /* 取不到时按 0 上报 */ }
    const result = await requestJson('/api/proactive/events/claim', {
      method: 'POST',
      body: {
        session_id: cfg.session_id, timezone, client_id: `desktop-${app.getPath('userData')}`,
        idle_state: { idle_seconds: idleSeconds, active_streak_minutes: activeStreakMinutes }
      }
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

// IPC 来源白名单：app:*/api:* 只允许本项目打包内的本地页面(file://)调用;
// feed:* 额外放行摸鱼小窗自身(其 preload 运行在第三方远程页面上,属设计使然)。
// 防止被注入的页面借 IPC 改写运行时配置(如 LLM_BASE_URL)或调用本地 API。
function isLocalPanelFrame(event) {
  try {
    const frameUrl = event.senderFrame && event.senderFrame.url;
    if (!frameUrl || !frameUrl.startsWith('file:')) return false;
    const filePath = path.resolve(fileURLToPath(frameUrl));
    return filePath.startsWith(path.resolve(projectRoot) + path.sep);
  } catch (error) {
    return false;
  }
}

function isFeedFrame(event) {
  return Boolean(feedWindow && !feedWindow.isDestroyed() && event.sender === feedWindow.webContents);
}

function guardedHandle(channel, handler, { allowFeed = false } = {}) {
  ipcMain.handle(channel, async (event, ...args) => {
    if (!isLocalPanelFrame(event) && !(allowFeed && isFeedFrame(event))) {
      throw new Error('Untrusted IPC sender');
    }
    return handler(event, ...args);
  });
}

function registerIpc() {
  // preload_web.js 在面板每次页面跳转时同步取实时配置,不能用启动参数(窗口创建后就不再更新)
  ipcMain.on('app:get-config-sync', (event) => {
    event.returnValue = isLocalPanelFrame(event) ? readConfig() : {};
  });
  guardedHandle('app:get-config', async () => readConfig());
  guardedHandle('app:get-runtime-info', async () => publicRuntimeInfo());
  guardedHandle('app:save-runtime-settings', async (_event, input) => writeRuntimeSettings(input || {}));
  guardedHandle('app:complete-setup', async () => {
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
  guardedHandle('app:open-setup', async () => {
    createSetupWindow();
    return true;
  });
  guardedHandle('app:open-data-dir', async () => shell.openPath(app.getPath('userData')));
  guardedHandle('app:get-autostart', async () => Boolean(readConfig().autostart));
  guardedHandle('app:set-autostart', async (_event, enabled) => {
    const next = Boolean(enabled);
    patchConfig({ autostart: next });
    try {
      app.setLoginItemSettings({ openAtLogin: next, openAsHidden: true });
    } catch (error) { /* 非 macOS/受限环境下静默失败,配置已落盘 */ }
    return next;
  });
  guardedHandle('app:set-config', async (_event, partial) => {
    const next = patchConfig(partial || {});
    updateTrayMenu();
    sendToWindows('config-updated', next);
    return next;
  });
  guardedHandle('app:toggle-chat', async () => toggleChatWindow());
  guardedHandle('app:show-pet', async () => showPetWindow());
  guardedHandle('app:move-pet', async (_event, dx, dy) => {
    if (!petWindow || petWindow.isDestroyed()) return;
    const bounds = petWindow.getBounds();
    petWindow.setPosition(bounds.x + Math.round(dx || 0), bounds.y + Math.round(dy || 0));
  });
  guardedHandle('app:open-web', async () => openWebPanel());
  guardedHandle('app:quit', async () => {
    isQuitting = true;
    app.quit();
  });
  guardedHandle('app:ensure-backend', async () => ensureBackendReady());
  guardedHandle('app:ensure-session', async () => ensureSession());
  guardedHandle('app:get-pet-image', async () => {
    const cfg = readConfig();
    return getPetImagePath(cfg.pet_type, cfg.custom_pet_raw_type);
  });
  guardedHandle('app:notify-chat-done', async () => {
    sendToWindows('pet-refresh');
  });

  guardedHandle('api:get-messages', async () => {
    const cfg = await ensureSession();
    return requestJson(`/api/sessions/${cfg.session_id}/messages`);
  });
  guardedHandle('api:get-pet-status', async () => {
    const cfg = await ensureSession();
    return requestJson(`/api/sessions/${cfg.session_id}/pet-status`);
  });
  guardedHandle('api:chat', async (_event, content) => {
    const cfg = await ensureSession();
    return requestJson(`/api/sessions/${cfg.session_id}/chat`, {
      method: 'POST',
      body: { content }
    });
  });
  guardedHandle('api:share-daily', async () => {
    const cfg = await ensureSession();
    return requestJson(`/api/sessions/${cfg.session_id}/share-daily`, { method: 'POST' });
  });
  guardedHandle('api:simulate-time', async (_event, mode) => {
    const cfg = await ensureSession();
    return requestJson(`/api/sessions/${cfg.session_id}/simulate-time`, {
      method: 'POST',
      body: { mode }
    });
  });
  guardedHandle('api:proactive-delivered', async (_event, eventId, claimToken) => requestJson(`/api/proactive/events/${eventId}/delivered`, { method: 'POST', body: { claim_token: claimToken } }));
  guardedHandle('api:proactive-opened', async (_event, eventId, claimToken) => requestJson(`/api/proactive/events/${eventId}/opened`, { method: 'POST', body: { claim_token: claimToken } }));
  guardedHandle('api:proactive-action', async (_event, eventId, action, claimToken) => requestJson(`/api/proactive/events/${eventId}/action`, { method: 'POST', body: { action, claim_token: claimToken } }));
  // 穿衣建议：桌面聊天窗「看看怎么穿」按钮复用，city 为空时后端读用户画像 region，400 文案原样上抛
  guardedHandle('api:outfit-advice', async (_event, city) => {
    await ensureSession();
    return requestJson('/api/weather/outfit-advice', { method: 'POST', body: city ? { city } : {} });
  });

  // 摸鱼·小说阅读窗
  guardedHandle('app:open-novel', async () => { showNovelWindow(); return true; });
  guardedHandle('app:open-novel-book', async (_event, bookId) => {
    openNovelBook(typeof bookId === 'string' ? bookId : null);
    return true;
  });
  guardedHandle('app:hide-novel', async () => {
    if (novelWindow && !novelWindow.isDestroyed()) novelWindow.hide();
    return true;
  });
  guardedHandle('app:novel-import', async () => {
    const { canceled, filePaths } = await dialog.showOpenDialog({
      title: '导入小说',
      filters: [{ name: '小说文件', extensions: ['txt', 'epub', 'docx'] }],
      properties: ['openFile']
    });
    if (canceled || !filePaths.length) return { canceled: true };
    const filePath = filePaths[0];
    const cfg = await ensureSession();
    const bytes = fs.readFileSync(filePath);
    const filename = path.basename(filePath);
    const form = new FormData();
    form.append('file', new Blob([bytes], { type: 'application/octet-stream' }), filename);
    const response = await fetch(`${getBackendUrl()}/api/leisure/novels/import`, {
      method: 'POST',
      headers: {
        'X-User-Id': cfg.user_id || 'anonymous',
        ...(getBackendApiKey() ? { Authorization: `Bearer ${getBackendApiKey()}` } : {})
      },
      body: form
    });
    const data = await response.json().catch(() => null);
    if (!response.ok) {
      throw new Error(data?.detail || `HTTP ${response.status}`);
    }
    return data;
  });

  // 摸鱼·视频小窗
  guardedHandle('app:open-feed', async () => { showFeedWindow(); return true; });
  // 打开小窗并直达指定渠道(B站/小红书/抖音),供托盘/Web 面板调用。
  guardedHandle('app:open-feed-channel', async (_event, channel) => { openFeedChannel(channel); return true; });
  // 真正关闭小窗:立即销毁渲染进程,停止后台视频/网络播放。
  guardedHandle('app:close-feed', async () => {
    if (feedWindow && !feedWindow.isDestroyed()) feedWindow.destroy();
    return true;
  }, { allowFeed: true });
  guardedHandle('feed:nav', async (_event, kind) => {
    if (!feedWindow || feedWindow.isDestroyed()) return false;
    const contents = feedWindow.webContents;
    if (kind === 'back') {
      // 从 B 站播放态返回信息流时,同步清理持久化播放态并恢复双列窗口尺寸。
      if (ensureFeedState().video.active) clearFeedPlayback();
      contents.goBack();
    }
    else if (kind === 'forward') contents.goForward();
    else if (kind === 'reload') contents.reload();
    return true;
  }, { allowFeed: true });
  guardedHandle('feed:navigate', async (_event, url) => navigateFeed(url), { allowFeed: true });
  // preload 浮条初始化时读取持久化的置顶状态,保持按钮高亮与真实状态一致。
  guardedHandle('feed:get-pinned', async () => ensureFeedState().pinned, { allowFeed: true });
  guardedHandle('feed:set-pinned', async (_event, pinned) => {
    const next = Boolean(pinned);
    patchFeedMeta({ pinned: next });
    if (feedWindow && !feedWindow.isDestroyed()) feedWindow.setAlwaysOnTop(next, 'floating');
    return feedWindow && !feedWindow.isDestroyed() ? feedWindow.isAlwaysOnTop() : next;
  }, { allowFeed: true });
  guardedHandle('feed:zoom', async (_event, action) => {
    if (!feedWindow || feedWindow.isDestroyed()) return null;
    const contents = feedWindow.webContents;
    const current = contents.getZoomFactor();
    const next = action === 'reset'
      ? 1
      : Math.max(0.3, Math.min(2, current + (action === 'in' ? 0.2 : -0.2)));
    contents.setZoomFactor(next);
    // 缩放按渠道记忆:手机版竖屏流通常无需缩放,桌面版(B站)可记住适配值。
    if (feedActiveChannel) patchFeedChannel(feedActiveChannel, { zoom: next });
    return next;
  }, { allowFeed: true });

  // 摸鱼·B 站本地播放:托盘输入窗 / Web 面板 / 浮条共用同一组入口。
  // feed:play-video 解析 BV / av / 分 P / b23.tv 短链后用官方外链播放器直载。
  guardedHandle('feed:play-video', async (_event, input) => playBiliVideo(typeof input === 'string' ? input : ''), { allowFeed: true });
  // 浮条初始化时读取播放模式,决定是否隐藏站点导航栏并显示「完整页面」按钮。
  guardedHandle('feed:get-playback', async () => {
    const video = ensureFeedState().video;
    return { active: video.active, mode: video.mode, danmaku: video.danmaku, autoplay: video.autoplay };
  }, { allowFeed: true });
  // 「完整页面 / 外链播放器」手动切换(两级回退),不做 DOM 自动检测。
  guardedHandle('feed:toggle-play-mode', async () => toggleBiliPlayMode(), { allowFeed: true });
  // 弹幕 / 自动播放偏好持久化;外链播放器模式下重载热生效。
  guardedHandle('feed:set-play-pref', async (_event, partial) => setBiliPlayPref(partial && typeof partial === 'object' ? partial : {}), { allowFeed: true });

  const novelApi = (method, path, body) => requestJson(path, { method, body });
  guardedHandle('api:novel-list', async () => novelApi('GET', '/api/leisure/novels'));
  guardedHandle('api:novel-mine', async () => novelApi('GET', '/api/leisure/novels/mine'));
  guardedHandle('api:novel-chapters', async (_event, bookId) => novelApi('GET', `/api/leisure/novels/${bookId}/chapters`));
  guardedHandle('api:novel-chapter', async (_event, bookId, chapterId) => novelApi('GET', `/api/leisure/novels/${bookId}/chapters/${chapterId}`));
  guardedHandle('api:novel-progress-get', async (_event, bookId) => novelApi('GET', `/api/leisure/novels/${bookId}/progress`));
  guardedHandle('api:novel-progress-save', async (_event, bookId, body) => novelApi('PUT', `/api/leisure/novels/${bookId}/progress`, body));
  guardedHandle('api:novel-session-open', async (_event, bookId) => {
    await ensureSession();
    return novelApi('POST', '/api/leisure/sessions', { module_id: 'builtin.novel', content_ref_id: bookId });
  });
  guardedHandle('api:novel-session-close', async (_event, sessionId) => novelApi('POST', `/api/leisure/sessions/${sessionId}/close?reason=user_exit`));
  guardedHandle('api:novel-delete', async (_event, bookId) => novelApi('DELETE', `/api/leisure/novels/${bookId}`));
}

async function startCoreApp() {
  if (coreStarted) return;
  coreStarted = true;
  startIdleStreakTracking();
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
        // 会话就绪说明后端可用:拉取自定义宠物列表刷新「切换宠物」菜单(失败静默)。
        refreshCustomPetList();
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
  // 开机自启:按配置同步登录项设置(openAsHidden 不在 Dock 抢占焦点)。
  try {
    app.setLoginItemSettings({ openAtLogin: Boolean(readConfig().autostart), openAsHidden: true });
  } catch (error) { /* 平台不支持时静默跳过 */ }
  // 老板键常驻注册:任何界面下一键隐藏(并暂停)视频小窗。
  globalShortcut.register(FEED_BOSS_KEY, toggleFeedBossKey);
  // 显示器移除/参数变化后,把仍可见的桌宠窗与视频小窗拉回有效屏幕。
  screen.on('display-removed', clampWindowsToDisplays);
  screen.on('display-metrics-changed', clampWindowsToDisplays);

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
  globalShortcut.unregisterAll();
  if (backendProcess) {
    backendProcess.kill();
    backendProcess = null;
  }
  if (proactiveTimer) clearInterval(proactiveTimer);
  if (idleStreakTimer) clearInterval(idleStreakTimer);
});

powerMonitor.on('resume', () => {
  if (coreStarted) claimProactiveEvent();
});
