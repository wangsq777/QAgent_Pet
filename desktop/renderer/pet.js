const petImage = document.getElementById('petImage');
const petButton = document.getElementById('petButton');
const petBubble = document.getElementById('petBubble');
const petMood = document.getElementById('petMood');
const backendHint = document.getElementById('backendHint');

const BUBBLE_HIDE_MS = 6000;
const REFRESH_MS = 60 * 1000;
const MIN_BUBBLE_INTERVAL_MS = 20 * 60 * 1000;
let bubbleTimer = null;
let currentConfig = null;
let dragState = null;
let clickMoved = false;
let currentProactive = null;

function todayKey() {
  const parts = new Intl.DateTimeFormat('en-CA', {
    timeZone: Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC',
    year: 'numeric', month: '2-digit', day: '2-digit'
  }).formatToParts(new Date()).reduce((result, item) => {
    if (item.type !== 'literal') result[item.type] = item.value;
    return result;
  }, {});
  return `${parts.year}-${parts.month}-${parts.day}`;
}

function setHint(message) {
  if (!message) {
    backendHint.hidden = true;
    backendHint.textContent = '';
    return;
  }
  backendHint.textContent = message;
  backendHint.hidden = false;
}

function twoCharTopic(status) {
  const now = new Date();
  const hour = now.getHours();
  if (status?.status === 'studying') return '陪学';
  if (status?.status === 'lonely') return '想你';
  if (status?.status === 'sleepy' || hour >= 23 || hour < 7) return '困了';
  if (status?.status === 'happy') return '开心';

  const lastAt = status?.last_interaction_at ? new Date(status.last_interaction_at) : null;
  if (lastAt && !Number.isNaN(lastAt.getTime())) {
    const minutes = Math.floor((Date.now() - lastAt.getTime()) / 60000);
    if (minutes >= 180) return '找你';
    if (minutes >= 60) return '等待';
  }

  if (hour >= 8 && hour <= 11) return '早呀';
  if (hour >= 19 && hour <= 22) return '想你';
  return '无聊';
}

function showBubble(text) {
  if (!text || currentConfig?.dnd) return;
  petBubble.textContent = text.slice(0, 2);
  petBubble.hidden = false;
  clearTimeout(bubbleTimer);
  bubbleTimer = setTimeout(() => {
    petBubble.hidden = true;
  }, BUBBLE_HIDE_MS);
}

async function refreshPetImage() {
  try {
    const imagePath = await window.desktopAPI.getPetImage();
    petImage.src = `file:///${imagePath.replace(/\\/g, '/')}`;
  } catch (error) {
    petImage.alt = 'QAgent Pet';
  }
}

async function refreshStatus({ allowBubble = false } = {}) {
  try {
    currentConfig = await window.desktopAPI.getConfig();
    const status = await window.desktopAPI.getPetStatus();
    petMood.textContent = status?.status_label || '待机';

    if (currentConfig?.dnd) {
      petBubble.hidden = true;
      return;
    }

    const now = Date.now();
    const canShowByTime = !currentConfig.last_bubble_at || now - currentConfig.last_bubble_at > MIN_BUBBLE_INTERVAL_MS;
    if (allowBubble && canShowByTime) {
      showBubble(twoCharTopic(status));
      await window.desktopAPI.setConfig({ last_bubble_at: now });
      currentConfig = await window.desktopAPI.getConfig();
    }
  } catch (error) {
    setHint(`连接失败：${error.message}`);
  }
}

async function maybeProactiveGreeting() {
  currentConfig = await window.desktopAPI.getConfig();
  if (currentConfig.dnd) return;
  if (currentConfig.last_proactive_date === todayKey()) return;

  try {
    await window.desktopAPI.shareDaily();
    await window.desktopAPI.setConfig({
      last_proactive_date: todayKey(),
      last_bubble_at: Date.now()
    });
    showBubble('找你');
    window.desktopAPI.notifyChatDone();
  } catch (error) {
    // 主动问候失败不影响桌宠常驻，只静默等待用户主动聊天。
  }
}

async function init() {
  petButton.addEventListener('pointerdown', (event) => {
    clickMoved = false;
    dragState = { x: event.screenX, y: event.screenY };
    petButton.setPointerCapture(event.pointerId);
  });
  petButton.addEventListener('pointermove', async (event) => {
    if (!dragState) return;
    const dx = event.screenX - dragState.x;
    const dy = event.screenY - dragState.y;
    if (Math.abs(dx) + Math.abs(dy) < 2) return;
    clickMoved = true;
    dragState = { x: event.screenX, y: event.screenY };
    await window.desktopAPI.movePet(dx, dy);
  });
  petButton.addEventListener('pointerup', (event) => {
    dragState = null;
    try { petButton.releasePointerCapture(event.pointerId); } catch (error) {}
    if (!clickMoved) window.desktopAPI.toggleChat();
  });
  petBubble.addEventListener('click', () => window.desktopAPI.toggleChat());

  window.desktopAPI.onProactiveEvent(async (event) => {
    currentProactive = event;
    showBubble(event.bubble_text || '提醒');
    try { await window.desktopAPI.proactiveDelivered(event.event_id, event.claim_token); } catch (error) {}
  });

  window.desktopAPI.onConfigUpdated((config) => {
    currentConfig = config;
    refreshPetImage();
    refreshStatus({ allowBubble: false });
  });
  window.desktopAPI.onPetRefresh(() => refreshStatus({ allowBubble: true }));
  window.desktopAPI.onBackendError((message) => setHint(message));

  setHint('正在连接后端...');
  const backend = await window.desktopAPI.ensureBackend();
  if (!backend.ok) {
    setHint(backend.error || '后端启动失败');
    return;
  }

  await window.desktopAPI.ensureSession();
  setHint('');
  await refreshPetImage();
  await refreshStatus({ allowBubble: true });
  maybeProactiveGreeting();
  setInterval(() => refreshStatus({ allowBubble: true }), REFRESH_MS);
}

init().catch((error) => {
  setHint(`启动失败：${error.message}`);
});
