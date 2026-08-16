const form = document.getElementById('setupForm');
const title = document.getElementById('setupTitle');
const apiKey = document.getElementById('apiKey');
const keyHint = document.getElementById('keyHint');
const baseUrl = document.getElementById('baseUrl');
const model = document.getElementById('model');
const dataDir = document.getElementById('dataDir');
const status = document.getElementById('status');
const submitButton = document.getElementById('submitButton');
const showKey = document.getElementById('showKey');

async function load() {
  const info = await window.setupAPI.getRuntimeInfo();
  baseUrl.value = info.llm_base_url;
  model.value = info.llm_model;
  dataDir.textContent = info.data_dir;
  dataDir.title = info.data_dir;
  if (info.configured) {
    title.textContent = '调整 AI 服务设置';
    apiKey.placeholder = '留空则继续使用当前 API Key';
    keyHint.textContent = '已保存 API Key。留空不会覆盖现有密钥。保存后应用会自动重启。';
    submitButton.textContent = '保存并重启桌宠';
  }
}

showKey.addEventListener('click', () => {
  const visible = apiKey.type === 'text';
  apiKey.type = visible ? 'password' : 'text';
  showKey.textContent = visible ? '显示' : '隐藏';
});

document.getElementById('openDataDir').addEventListener('click', () => {
  window.setupAPI.openDataDir();
});

form.addEventListener('submit', async (event) => {
  event.preventDefault();
  status.className = 'status';
  status.textContent = '';
  submitButton.disabled = true;
  submitButton.textContent = '正在保存…';
  try {
    await window.setupAPI.saveRuntimeSettings({
      llm_api_key: apiKey.value,
      llm_base_url: baseUrl.value,
      llm_model: model.value
    });
    status.className = 'status success';
    status.textContent = '设置已安全保存，正在启动 QAgent Pet…';
    await window.setupAPI.completeSetup();
  } catch (error) {
    status.textContent = error.message || '保存失败，请检查输入';
    submitButton.disabled = false;
    submitButton.textContent = '保存并启动桌宠';
  }
});

load().catch((error) => {
  status.textContent = error.message || '无法读取当前设置';
});
