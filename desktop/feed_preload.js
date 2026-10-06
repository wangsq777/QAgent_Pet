// 摸鱼·视频小窗的浮条:在外部页面顶部注入一条可拖拽的迷你工具栏。
// 只通过 IPC 与主进程通信,不读取或改写页面脚本与数据。
// 样式一律走 CSSOM(style.setProperty),避免被第三方页面 CSP 拦截。
const { ipcRenderer } = require('electron');

const HOME_URL = 'https://www.bilibili.com';
const BAR_HEIGHT = 34;
const NAV_HEIGHT = 30;
const BAR_ID = 'qagent-feed-bar';
const NAV_ID = 'qagent-feed-nav';
let pinned = true;
let collapsed = false;

// 导航栏站点:切换到对应平台的网页版(全部是普通浏览行为,无接口依赖)。
// 小红书导航直指 /explore 信息流;抖音/快手首页即信息流(快手直达 /short-video 竖屏流);淘宝为桌面宽布局网页版。
const NAV_SITES = [
  { name: 'B站', host: 'www.bilibili.com', url: 'https://www.bilibili.com' },
  { name: '小红书', host: 'www.xiaohongshu.com', url: 'https://www.xiaohongshu.com/explore' },
  { name: '抖音', host: 'www.douyin.com', url: 'https://www.douyin.com/?recommend=1' },
  { name: '快手', host: 'www.kuaishou.com', url: 'https://www.kuaishou.com/short-video' },
  { name: '淘宝', host: 'www.taobao.com', url: 'https://www.taobao.com' }
];

function applyStyle(element, styles) {
  Object.keys(styles).forEach((key) => element.style.setProperty(key, styles[key]));
}

function makeButton(label, title, onClick) {
  const button = document.createElement('button');
  button.textContent = label;
  button.title = title;
  button.type = 'button';
  applyStyle(button, {
    '-webkit-app-region': 'no-drag',
    background: 'rgba(255,255,255,0.08)',
    border: '1px solid rgba(255,255,255,0.14)',
    'border-radius': '6px',
    height: '22px',
    'min-width': '26px',
    padding: '0 7px',
    cursor: 'pointer',
    color: 'inherit',
    'line-height': '1',
    'font-size': '12px'
  });
  button.addEventListener('click', onClick);
  return button;
}

function renderBars(bar, nav, collapse) {
  if (collapsed) {
    applyStyle(bar, { height: '12px', overflow: 'hidden', padding: '0 4px' });
    if (nav) applyStyle(nav, { display: 'none' });
  } else {
    applyStyle(bar, { height: `${BAR_HEIGHT}px`, overflow: 'visible', padding: '0 8px' });
    if (nav) applyStyle(nav, { display: 'flex' });
  }
  collapse.textContent = collapsed ? '▣' : '—';
  collapse.title = collapsed ? '展开浮条' : '收起浮条';
}

function makeNavButton(site) {
  const button = makeButton(site.name, `前往 ${site.name} 网页版`, () => ipcRenderer.invoke('feed:navigate', site.url));
  applyStyle(button, {
    background: 'transparent',
    border: '1px solid transparent',
    'border-radius': '14px',
    height: '20px',
    'min-width': '0',
    padding: '0 10px',
    opacity: '0.75'
  });
  return button;
}

// 隐藏平台页的「下载App / 打开App」横幅。纯客户端 UI 行为(等同广告拦截,不读取/不改写数据)。
// 覆盖 B站 / 小红书 / 抖音 / 淘宝 网页版的常见提示文案;要求带「app」或平台名,避免误伤正常标题。
const APP_PROMPT_PATTERN = /下载\s*(哔哩哔哩|b站|小红书|抖音|(?:手机)?淘宝|app)|打开\s*(哔哩哔哩|b站|小红书|抖音|(?:手机)?淘宝)\s*app|打开手机淘宝|打开\s*app|在\s*app\s*中\s*打开|app\s*内\s*打开|前往\s*app/i;

function looksLikeAppPrompt(element) {
  if (element.id === BAR_ID || element.id === NAV_ID) return false;
  if (!element.textContent || element.textContent.length > 120) return false;
  if (!APP_PROMPT_PATTERN.test(element.textContent)) return false;
  const style = getComputedStyle(element);
  return style.position === 'fixed' || style.position === 'sticky'
    || element.matches('a,button,[role="button"]')
    || (element.tagName === 'DIV' && element.children.length <= 4);
}

// 兜底扫描:主进程已按域名注入声明式 CSS 遮盖横幅,这里只处理 CSS 覆盖不到的文字变体。
// 抖音/小红书是虚拟列表,DOM 高频变动,必须节流 + 先做廉价过滤再碰 getComputedStyle。
const SWEEP_MIN_INTERVAL = 900;
const SWEEP_MAX_NODES = 1500;
let sweepScheduled = false;
let lastSweepAt = 0;

function sweepAppPrompts() {
  let hidden = 0;
  let visited = 0;
  document.querySelectorAll('a,button,[role="button"],div').forEach((element) => {
    if (hidden >= 20 || visited >= SWEEP_MAX_NODES) return;
    visited += 1;
    if (element.dataset.qfeedHidden) return;
    // 廉价预过滤:零尺寸(不可见/已隐藏)的直接跳过,避免逐个触发样式计算。
    if (!element.offsetWidth && !element.offsetHeight) return;
    if (!looksLikeAppPrompt(element)) return;
    element.style.display = 'none';
    element.dataset.qfeedHidden = '1';
    hidden += 1;
  });
}

function scheduleSweep() {
  if (sweepScheduled) return;
  sweepScheduled = true;
  const wait = Math.max(0, SWEEP_MIN_INTERVAL - (Date.now() - lastSweepAt));
  setTimeout(() => {
    sweepScheduled = false;
    lastSweepAt = Date.now();
    sweepAppPrompts();
  }, wait);
}

function initPromptHiding() {
  sweepAppPrompts();
  lastSweepAt = Date.now();
  // MutationObserver 只负责"排班",实际扫描按最小间隔节流执行。
  const observer = new MutationObserver(scheduleSweep);
  observer.observe(document.documentElement, { childList: true, subtree: true });
  // SPA 异步渲染的横幅再补扫一次。
  setTimeout(sweepAppPrompts, 1500);
}

// ---- 平台专属布局适配 ----
// 这里只做页面表现层适配,不读取接口、不解析账号数据。平台改版时只需要调整这组
// 选择器,不会影响主进程的窗口/播放状态。
const LAYOUT_STYLE_ID = 'qagent-feed-layout-style';
const LAYOUT_CSS = `
  html.qagent-douyin-feed, html.qagent-douyin-feed body,
  html.qagent-douyin-feed #root, html.qagent-douyin-feed #dark {
    width: 100vw !important;
    min-width: 0 !important;
    max-width: none !important;
    height: 100% !important;
    overflow: hidden !important;
    background: #000 !important;
  }
  html.qagent-douyin-feed #douyin-navigation,
  html.qagent-douyin-feed #douyin-header,
  html.qagent-douyin-feed #douyin-right-container > .douyin-header,
  html.qagent-douyin-feed .douyin-header,
  /* 登录弹层的外层是随机 id/class；只隐藏内层 article 会留下整屏遮罩。 */
  html.qagent-douyin-feed [id^="login-full-panel-"],
  html.qagent-douyin-feed [class*="fe8GGOyG"],
  html.qagent-douyin-feed #login-panel-new,
  html.qagent-douyin-feed #douyin-login-new-id,
  html.qagent-douyin-feed #douyin_login_comp_flat_panel,
  html.qagent-douyin-feed #douyin_login_landing_flat_container {
    display: none !important;
  }
  html.qagent-douyin-feed #douyin-right-container {
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
  html.qagent-douyin-feed #douyin-right-container > .live-detail-portal-anchor-wrapper,
  html.qagent-douyin-feed #douyin-right-container > [class*="portal-anchor-wrapper"],
  html.qagent-douyin-feed #douyin-right-container > [class*="FJW1IOm9"] {
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
  html.qagent-douyin-feed #slidelist,
  html.qagent-douyin-feed #slidelist [data-e2e="slideList"],
  html.qagent-douyin-feed .recommend-slidelist {
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
  html.qagent-douyin-feed #douyin-right-container [class*="parent-route-container"],
  html.qagent-douyin-feed #douyin-right-container [class*="discover-tab-container"],
  html.qagent-douyin-feed #douyin-right-container [class*="semi-tabs-content"],
  html.qagent-douyin-feed #douyin-right-container [class*="semi-tabs-pane"],
  html.qagent-douyin-feed #douyin-right-container [class*="jingxuan-scroll-element"],
  html.qagent-douyin-feed #douyin-right-container [class*="jingxuanFeedList"] {
    width: 100% !important;
    min-width: 0 !important;
    max-width: none !important;
    box-sizing: border-box !important;
  }
  html.qagent-douyin-feed #douyin-right-container [class*="parent-route-container"],
  html.qagent-douyin-feed #douyin-right-container [class*="semi-tabs-content"] {
    height: 100% !important;
    min-height: 0 !important;
    overflow-x: hidden !important;
    overflow-y: auto !important;
  }
  html.qagent-douyin-feed #douyin-right-container [class*="jingxuan-scroll-element"],
  html.qagent-douyin-feed #douyin-right-container [class*="jingxuanFeedList"] {
    height: auto !important;
    min-height: 100% !important;
    overflow: visible !important;
  }
  html.qagent-douyin-feed #douyin-right-container [class*="vg6ZqNFG"] {
    display: grid !important;
    grid-template-columns: minmax(0, 1fr) !important;
    width: 100% !important;
    min-width: 0 !important;
    max-width: none !important;
    box-sizing: border-box !important;
    gap: 16px !important;
    padding: 0 12px 24px !important;
  }
  html.qagent-douyin-feed #douyin-right-container [class*="discover-video-card-item"],
  html.qagent-douyin-feed #douyin-right-container [class*="waterfall-videoCardContainer"] {
    width: 100% !important;
    min-width: 0 !important;
    max-width: none !important;
    box-sizing: border-box !important;
  }
  html.qagent-douyin-feed #douyin-right-container [class*="videoImage"],
  html.qagent-douyin-feed #douyin-right-container img[class*="discover-video-card-img"] {
    width: 100% !important;
    max-width: none !important;
    aspect-ratio: 16 / 9 !important;
    height: auto !important;
    object-fit: cover !important;
  }
  html.qagent-douyin-feed #slidelist > *,
  html.qagent-douyin-feed #slidelist [data-e2e="slideList"] > *,
  html.qagent-douyin-feed .recommend-slidelist > * {
    width: 100% !important;
    min-width: 0 !important;
    max-width: none !important;
  }
  html.qagent-douyin-feed #slidelist .xg-video-container,
  html.qagent-douyin-feed #slidelist .xgplayer,
  html.qagent-douyin-feed #slidelist .basePlayerContainer,
  html.qagent-douyin-feed #slidelist .slider-video {
    width: 100% !important;
    height: 100% !important;
    min-width: 0 !important;
    max-width: none !important;
    max-height: none !important;
  }
  html.qagent-douyin-feed #slidelist video,
  html.qagent-douyin-feed #slidelist .xg-video-container video {
    display: block !important;
    width: 100% !important;
    height: 100% !important;
    max-width: none !important;
    max-height: none !important;
    object-fit: cover !important;
  }
  html.qagent-douyin-feed [class*="video-card"],
  html.qagent-douyin-feed [class*="feed-card"],
  html.qagent-douyin-feed [data-e2e*="feed"] {
    max-width: 100vw !important;
    min-width: 0 !important;
  }
  html.qagent-bilibili-feed .qagent-bili-feed-grid {
    display: grid !important;
    grid-template-columns: repeat(2, minmax(0, 1fr)) !important;
    gap: 12px !important;
    align-items: start !important;
  }
  html.qagent-bilibili-feed .qagent-bili-feed-card {
    width: auto !important;
    min-width: 0 !important;
    margin: 0 !important;
  }
`;


function installLayoutStyle() {
  if (!document.documentElement || document.getElementById(LAYOUT_STYLE_ID)) return;
  const style = document.createElement('style');
  style.id = LAYOUT_STYLE_ID;
  style.textContent = LAYOUT_CSS;
  (document.head || document.documentElement).appendChild(style);
}

function markDouyinLayout() {
  if ((window.location.hostname || '').toLowerCase().endsWith('douyin.com')) {
    document.documentElement.classList.add('qagent-douyin-feed');
  }
}

function findBiliCard(anchor) {
  let node = anchor;
  for (let depth = 0; node && depth < 6; depth += 1, node = node.parentElement) {
    if (!(node instanceof HTMLElement)) continue;
    const rect = node.getBoundingClientRect();
    if (rect.width >= 180 && rect.height >= 110 && rect.width < window.innerWidth * 0.95) {
      return node;
    }
  }
  return null;
}

function markBilibiliCards() {
  if (!(window.location.hostname || '').toLowerCase().endsWith('bilibili.com')) return;
  document.documentElement.classList.add('qagent-bilibili-feed');
  const cards = [];
  document.querySelectorAll('a[href*="/video/"],a[href*="/av"]').forEach((anchor) => {
    const card = findBiliCard(anchor);
    if (!card || card.id === BAR_ID || card.closest(`#${BAR_ID},#${NAV_ID}`)) return;
    card.classList.add('qagent-bili-feed-card');
    cards.push(card);
  });
  const uniqueCards = Array.from(new Set(cards));
  const parents = new Map();
  uniqueCards.forEach((card) => {
    const parent = card.parentElement;
    if (parent) parents.set(parent, (parents.get(parent) || 0) + 1);
  });
  let bestParent = null;
  let bestCount = 1;
  parents.forEach((count, parent) => {
    const rect = parent.getBoundingClientRect();
    if (count > bestCount && rect.width >= 420) {
      bestParent = parent;
      bestCount = count;
    }
  });
  if (bestParent) bestParent.classList.add('qagent-bili-feed-grid');
}

function installBilibiliVideoClick() {
  if (!(window.location.hostname || '').toLowerCase().endsWith('bilibili.com')) return;
  if (document.documentElement.dataset.qagentBiliClickBound === '1') return;
  document.documentElement.dataset.qagentBiliClickBound = '1';
  document.addEventListener('click', (event) => {
    if (event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
    const anchor = event.composedPath().find((item) => item instanceof HTMLAnchorElement);
    const href = anchor?.href || '';
    if (!href || !/bilibili\.com\/(video\/|av\d+)/i.test(href)) return;
    if (anchor.closest(`#${BAR_ID},#${NAV_ID}`)) return;
    event.preventDefault();
    event.stopPropagation();
    ipcRenderer.invoke('feed:play-video', href).catch(() => {});
  }, true);
}

function initSiteLayout() {
  installLayoutStyle();
  markDouyinLayout();
  markBilibiliCards();
  installBilibiliVideoClick();
  // B站和抖音都是 SPA/虚拟列表,页面加载后卡片还会继续出现。
  const observer = new MutationObserver(() => {
    markDouyinLayout();
    markBilibiliCards();
  });
  observer.observe(document.documentElement, { childList: true, subtree: true });
  window.addEventListener('resize', markBilibiliCards, { passive: true });
}

function injectBar(playback) {
  if (document.getElementById(BAR_ID)) return;
  const currentHost = (window.location.hostname || '').toLowerCase();
  // 播放模式(外链播放器 / 官方视频页裁剪):单一视频无需切站,隐藏平台切换导航栏。
  const playbackActive = Boolean(playback && playback.active);
  const playbackMode = playbackActive && playback.mode === 'page' ? 'page' : 'player';

  const bar = document.createElement('div');
  bar.id = BAR_ID;
  applyStyle(bar, {
    position: 'fixed',
    top: '0',
    left: '0',
    right: '0',
    height: `${BAR_HEIGHT}px`,
    'z-index': '2147483647',
    display: 'flex',
    'align-items': 'center',
    gap: '6px',
    padding: '0 8px',
    'box-sizing': 'border-box',
    background: 'rgba(20,22,26,0.92)',
    color: '#e6e6e6',
    'font-size': '12px',
    'font-family': "-apple-system, 'PingFang SC', 'Microsoft YaHei', sans-serif",
    '-webkit-app-region': 'drag',
    'user-select': 'none'
  });

  // 站点导航栏仅在普通刷信息流模式下出现。
  let nav = null;
  if (!playbackActive) {
    nav = document.createElement('div');
    nav.id = NAV_ID;
    applyStyle(nav, {
      position: 'fixed',
      top: `${BAR_HEIGHT}px`,
      left: '0',
      right: '0',
      height: `${NAV_HEIGHT}px`,
      'z-index': '2147483646',
      display: 'flex',
      'align-items': 'center',
      gap: '6px',
      padding: '0 8px',
      'box-sizing': 'border-box',
      background: 'rgba(14,16,20,0.9)',
      color: '#cfd3d8',
      'font-size': '12px',
      'font-family': "-apple-system, 'PingFang SC', 'Microsoft YaHei', sans-serif",
      '-webkit-app-region': 'drag',
      'user-select': 'none',
      'border-bottom': '1px solid rgba(255,255,255,0.08)'
    });
  }

  // 首页按钮跟随当前平台:B站页面回 B 站首页,抖音页面回抖音首页。
  // 播放模式下它也是离开播放模式、回到信息流的出口(导航会清除播放态)。
  const homeSite = NAV_SITES.find((site) => currentHost === site.host);
  const home = makeButton('⌂', '回到首页', () => ipcRenderer.invoke('feed:navigate', homeSite ? homeSite.url : HOME_URL));
  const back = makeButton('‹', '后退', () => ipcRenderer.invoke('feed:nav', 'back'));
  const forward = makeButton('›', '前进', () => ipcRenderer.invoke('feed:nav', 'forward'));
  const reload = makeButton('↻', '刷新', () => ipcRenderer.invoke('feed:nav', 'reload'));

  // 桌面站不随小窗收缩,用缩放按钮手动适配(仅信息流模式显示;播放器自适应窗口大小)。
  const zoomOut = makeButton('−', '缩小', () => ipcRenderer.invoke('feed:zoom', 'out'));
  const zoomReset = makeButton('100', '恢复 100%', () => ipcRenderer.invoke('feed:zoom', 'reset'));
  const zoomIn = makeButton('＋', '放大', () => ipcRenderer.invoke('feed:zoom', 'in'));

  const title = document.createElement('span');
  title.textContent = playbackActive ? '摸鱼小窗 · 播放中' : '摸鱼小窗';
  applyStyle(title, {
    flex: '1',
    'text-align': 'center',
    opacity: '0.7',
    overflow: 'hidden',
    'text-overflow': 'ellipsis',
    'white-space': 'nowrap'
  });

  // 播放模式切换按钮:外链播放器被 UP 主关闭等场景,手动回退到官方视频页(裁剪模式);反之切回。
  const modeSwitch = playbackActive
    ? makeButton(
      playbackMode === 'player' ? '完整页面' : '外链播放器',
      playbackMode === 'player' ? '外链播放器无法播放？切换到官方视频页（裁剪模式）' : '返回官方外链播放器',
      () => ipcRenderer.invoke('feed:toggle-play-mode')
    )
    : null;
  if (modeSwitch) applyStyle(modeSwitch, { color: '#8fd6ca', 'border-color': 'rgba(143,214,202,0.4)' });

  // 弹幕偏好开关(仅外链播放器模式:官方视频页用 B 站原生弹幕开关)。
  let danmakuOn = Boolean(playback && playback.danmaku);
  const danmaku = playbackActive && playbackMode === 'player'
    ? makeButton('弹幕', '切换弹幕显示（保存为偏好）', () => {
      ipcRenderer.invoke('feed:set-play-pref', { danmaku: !danmakuOn }).then((result) => {
        if (result && typeof result.danmaku === 'boolean') {
          danmakuOn = result.danmaku;
          applyStyle(danmaku, { opacity: danmakuOn ? '1' : '0.4' });
        }
      }).catch(() => {});
    })
    : null;
  if (danmaku) applyStyle(danmaku, { opacity: danmakuOn ? '1' : '0.4' });

  const pin = makeButton('📌', '切换置顶', async () => {
    pinned = await ipcRenderer.invoke('feed:set-pinned', !pinned);
    applyStyle(pin, { opacity: pinned ? '1' : '0.4' });
  });
  // 与主进程记忆的置顶状态对齐(重启后按钮高亮反映真实状态)。
  ipcRenderer.invoke('feed:get-pinned').then((value) => {
    pinned = value !== false;
    applyStyle(pin, { opacity: pinned ? '1' : '0.4' });
  }).catch(() => {});
  const collapse = makeButton('—', '收起浮条', () => {
    collapsed = !collapsed;
    renderBars(bar, nav, collapse);
  });
  // 关闭即真关闭:销毁小窗渲染进程,停止后台视频/网络播放。
  const close = makeButton('✕', '关闭小窗（停止后台播放）', () => ipcRenderer.invoke('app:close-feed'));

  // 收起时悬停临时展开,移出后恢复,尽量不遮挡播放画面。
  const expand = () => {
    if (collapsed) {
      applyStyle(bar, { height: `${BAR_HEIGHT}px`, overflow: 'visible', padding: '0 8px' });
      if (nav) applyStyle(nav, { display: 'flex' });
    }
  };
  const collapseHover = (event) => {
    if (!collapsed || !nav) return;
    const navRect = nav.getBoundingClientRect();
    if (!(event.clientY >= navRect.top && event.clientY <= navRect.bottom)) {
      renderBars(bar, nav, collapse);
    }
  };
  bar.addEventListener('mouseenter', expand);
  if (nav) nav.addEventListener('mouseenter', expand);
  bar.addEventListener('mouseleave', collapseHover);
  if (nav) nav.addEventListener('mouseleave', collapseHover);

  if (nav) {
    // 导航栏:快速切换平台网页版,当前站点高亮。
    const navButtons = NAV_SITES.map(makeNavButton);
    navButtons.forEach((button, index) => {
      if (NAV_SITES[index].host === currentHost) {
        applyStyle(button, {
          background: 'rgba(255,255,255,0.14)',
          border: '1px solid rgba(255,255,255,0.3)',
          opacity: '1'
        });
      }
    });
    nav.append(...navButtons);
  }

  bar.append(home, back, forward, reload);
  if (!playbackActive) bar.append(zoomOut, zoomReset, zoomIn);
  if (danmaku) bar.append(danmaku);
  if (modeSwitch) bar.append(modeSwitch);
  bar.append(title, pin, collapse, close);
  document.documentElement.appendChild(bar);
  if (nav) document.documentElement.appendChild(nav);
  renderBars(bar, nav, collapse);
}

// 播放状态由主进程持久化(config.json feed.video):preload 每次加载时读取,
// 决定本次文档按信息流模式还是播放模式渲染浮条。
function injectBarWithPlayback() {
  ipcRenderer.invoke('feed:get-playback')
    .then((playback) => injectBar(playback))
    .catch(() => injectBar(null));
}

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', () => {
    injectBarWithPlayback();
    initPromptHiding();
    initSiteLayout();
  }, { once: true });
} else {
  injectBarWithPlayback();
  initPromptHiding();
  initSiteLayout();
}
