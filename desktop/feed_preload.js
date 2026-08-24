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
// 小红书导航直指 /explore 信息流;抖音首页即信息流。
const NAV_SITES = [
  { name: 'B站', host: 'www.bilibili.com', url: 'https://www.bilibili.com' },
  { name: '小红书', host: 'www.xiaohongshu.com', url: 'https://www.xiaohongshu.com/explore' },
  { name: '抖音', host: 'www.douyin.com', url: 'https://www.douyin.com' }
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
    applyStyle(nav, { display: 'none' });
  } else {
    applyStyle(bar, { height: `${BAR_HEIGHT}px`, overflow: 'visible', padding: '0 8px' });
    applyStyle(nav, { display: 'flex' });
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
// 覆盖 B站 / 小红书 / 抖音 网页版的常见提示文案;要求带「app」或平台名,避免误伤正常标题。
const APP_PROMPT_PATTERN = /下载\s*(哔哩哔哩|b站|小红书|抖音|app)|打开\s*(哔哩哔哩|b站|小红书|抖音)\s*app|打开\s*app|在\s*app\s*中\s*打开|app\s*内\s*打开|前往\s*app/i;

function looksLikeAppPrompt(element) {
  if (element.id === BAR_ID || element.id === NAV_ID) return false;
  if (!element.textContent || element.textContent.length > 120) return false;
  if (!APP_PROMPT_PATTERN.test(element.textContent)) return false;
  const style = getComputedStyle(element);
  return style.position === 'fixed' || style.position === 'sticky'
    || element.matches('a,button,[role="button"]')
    || (element.tagName === 'DIV' && element.children.length <= 4);
}

function sweepAppPrompts() {
  let hidden = 0;
  document.querySelectorAll('a,button,[role="button"],div').forEach((element) => {
    if (element.dataset.qfeedHidden) return;
    if (looksLikeAppPrompt(element)) {
      element.style.display = 'none';
      element.dataset.qfeedHidden = '1';
      hidden += 1;
    }
  });
  if (hidden > 0) console.log(`[qagent-feed] 已隐藏 ${hidden} 个下载/打开App提示`);
}

function initPromptHiding() {
  sweepAppPrompts();
  const observer = new MutationObserver(() => sweepAppPrompts());
  observer.observe(document.documentElement, { childList: true, subtree: true });
  // SPA 异步渲染的横幅再补扫两次。
  setTimeout(sweepAppPrompts, 1500);
  setTimeout(sweepAppPrompts, 5000);
}

function injectBar() {
  if (document.getElementById(BAR_ID)) return;

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

  const nav = document.createElement('div');
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

  const home = makeButton('⌂', '回到首页', () => ipcRenderer.invoke('feed:navigate', HOME_URL));
  const back = makeButton('‹', '后退', () => ipcRenderer.invoke('feed:nav', 'back'));
  const forward = makeButton('›', '前进', () => ipcRenderer.invoke('feed:nav', 'forward'));
  const reload = makeButton('↻', '刷新', () => ipcRenderer.invoke('feed:nav', 'reload'));

  // 桌面站不随小窗收缩,用缩放按钮手动适配。
  const zoomOut = makeButton('−', '缩小', () => ipcRenderer.invoke('feed:zoom', 'out'));
  const zoomReset = makeButton('100', '恢复 100%', () => ipcRenderer.invoke('feed:zoom', 'reset'));
  const zoomIn = makeButton('＋', '放大', () => ipcRenderer.invoke('feed:zoom', 'in'));

  const title = document.createElement('span');
  title.textContent = '摸鱼小窗';
  applyStyle(title, {
    flex: '1',
    'text-align': 'center',
    opacity: '0.7',
    overflow: 'hidden',
    'text-overflow': 'ellipsis',
    'white-space': 'nowrap'
  });

  const pin = makeButton('📌', '切换置顶', async () => {
    pinned = await ipcRenderer.invoke('feed:set-pinned', !pinned);
    applyStyle(pin, { opacity: pinned ? '1' : '0.4' });
  });
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
      applyStyle(nav, { display: 'flex' });
    }
  };
  const collapseHover = (event) => {
    if (!collapsed) return;
    const navRect = nav.getBoundingClientRect();
    if (!(event.clientY >= navRect.top && event.clientY <= navRect.bottom)) {
      renderBars(bar, nav, collapse);
    }
  };
  bar.addEventListener('mouseenter', expand);
  nav.addEventListener('mouseenter', expand);
  bar.addEventListener('mouseleave', collapseHover);
  nav.addEventListener('mouseleave', collapseHover);

  // 导航栏:快速切换平台网页版,当前站点高亮。
  const navButtons = NAV_SITES.map(makeNavButton);
  const currentHost = (window.location.hostname || '').toLowerCase();
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

  bar.append(home, back, forward, reload, zoomOut, zoomReset, zoomIn, title, pin, collapse, close);
  document.documentElement.appendChild(bar);
  document.documentElement.appendChild(nav);
  renderBars(bar, nav, collapse);
}

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', () => {
    injectBar();
    initPromptHiding();
  }, { once: true });
} else {
  injectBar();
  initPromptHiding();
}
