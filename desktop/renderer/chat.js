const messagesEl = document.getElementById('messages');
const form = document.getElementById('chatForm');
const input = document.getElementById('messageInput');
const sendBtn = document.getElementById('sendBtn');
const thinking = document.getElementById('thinking');
const dndToggle = document.getElementById('dndToggle');
const openWeb = document.getElementById('openWeb');
const petTitle = document.getElementById('petTitle');
let proactiveEvent = null;

const PET_NAMES = {
  hot_dog: 'Hot Dog',
  cold_cat: 'Cold Cat',
  mouse: '鼠鼠'
};

function escapeHtml(value) {
  return String(value)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#039;');
}

function renderMessages(messages) {
  messagesEl.innerHTML = '';
  if (!messages.length) {
    messagesEl.innerHTML = '<div class="empty-tip">这里会显示桌宠轻聊天内容。<br>桌面气泡只提示「找你」「想你」等概括，完整内容在这里查看。</div>';
    return;
  }

  const fragment = document.createDocumentFragment();
  messages.slice(-30).forEach((message) => {
    const item = document.createElement('div');
    item.className = `message ${message.role === 'user' ? 'user' : 'assistant'}${message.is_proactive ? ' proactive' : ''}`;
    item.innerHTML = escapeHtml(message.content || '').replace(/\n/g, '<br>');
    fragment.appendChild(item);
  });
  messagesEl.appendChild(fragment);
  messagesEl.scrollTop = messagesEl.scrollHeight;
}

function appendMessage(role, content, extraClass = '') {
  const item = document.createElement('div');
  item.className = `message ${role} ${extraClass}`.trim();
  item.innerHTML = escapeHtml(content).replace(/\n/g, '<br>');
  messagesEl.appendChild(item);
  messagesEl.scrollTop = messagesEl.scrollHeight;
}

async function syncHeader() {
  const config = await window.desktopAPI.getConfig();
  petTitle.textContent = PET_NAMES[config.pet_type] || 'QAgent Pet';
  dndToggle.textContent = config.dnd ? '勿扰：开' : '勿扰：关';
}

async function loadMessages() {
  try {
    await window.desktopAPI.ensureBackend();
    await window.desktopAPI.ensureSession();
    await syncHeader();
    const data = await window.desktopAPI.getMessages();
    renderMessages(data.messages || []);
  } catch (error) {
    renderMessages([]);
    appendMessage('assistant', `连接失败：${error.message}`);
  }
}

function setLoading(loading) {
  thinking.hidden = !loading;
  input.disabled = loading;
  sendBtn.disabled = loading;
}

async function sendMessage(content) {
  appendMessage('user', content);
  setLoading(true);
  try {
    const result = await window.desktopAPI.chat(content);
    if (result?.reply) appendMessage('assistant', result.reply);
    if (result?.daily_share?.content) appendMessage('assistant', result.daily_share.content, 'proactive');
    await window.desktopAPI.notifyChatDone();
  } catch (error) {
    appendMessage('assistant', `发送失败：${error.message}`);
  } finally {
    setLoading(false);
    input.focus();
  }
}

form.addEventListener('submit', (event) => {
  event.preventDefault();
  const content = input.value.trim();
  if (!content) return;
  input.value = '';
  sendMessage(content);
});

input.addEventListener('keydown', (event) => {
  if (event.key === 'Enter' && !event.shiftKey) {
    event.preventDefault();
    form.requestSubmit();
  }
});

dndToggle.addEventListener('click', async () => {
  const config = await window.desktopAPI.getConfig();
  await window.desktopAPI.setConfig({ dnd: !config.dnd });
  await syncHeader();
});

openWeb.addEventListener('click', () => window.desktopAPI.openWebPanel());

window.desktopAPI.onProactiveEvent(async (event) => {
  proactiveEvent = event;
  appendMessage('assistant', event.full_message || '我来看看你。', 'proactive');
  try { await window.desktopAPI.proactiveOpened(event.event_id, event.claim_token); } catch (error) {}
  const actions = document.createElement('div');
  actions.className = 'proactive-actions';
  [['知道了', 'acknowledge'], ['晚点提醒', 'snooze_10m'], ['完成', 'complete'], ['不再提醒', 'dismiss']].forEach(([label, action]) => {
    const button = document.createElement('button');
    button.type = 'button'; button.textContent = label;
    button.addEventListener('click', async () => {
      button.disabled = true;
      try { await window.desktopAPI.proactiveAction(event.event_id, action, event.claim_token); actions.remove(); }
      catch (error) { button.disabled = false; appendMessage('assistant', `操作失败：${error.message}`); }
    });
    actions.appendChild(button);
  });
  messagesEl.appendChild(actions);
  messagesEl.scrollTop = messagesEl.scrollHeight;
});

window.desktopAPI.onConfigUpdated(syncHeader);
window.desktopAPI.onPetRefresh(loadMessages);

loadMessages();
