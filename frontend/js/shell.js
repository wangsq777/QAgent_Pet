function initAppShell(activeKey) {
    if (document.querySelector('.app-rail')) return;

    document.body.classList.add('app-shell-enabled');

    const petType = localStorage.getItem('qagent_pet_type');
    const customPetId = localStorage.getItem('qagent_custom_pet_id');
    const learnPetId = petType === 'custom' ? customPetId : petType;
    const learnHref = learnPetId ? `learn.html?pet_id=${encodeURIComponent(learnPetId)}` : 'index.html';

    const navItems = [
        { key: 'index', icon: '🏠', label: '广场', href: 'index.html' },
        { key: 'chat', icon: '💬', label: '聊天', href: 'chat.html' },
        { key: 'learn', icon: '📚', label: '陪学', href: learnHref },
        { key: 'custom_pet', icon: '🐾', label: '创建', href: 'custom_pet.html' },
        { key: 'desktop_pet', icon: '🖥️', label: '桌宠', href: 'desktop_pet.html' },
        { key: 'settings', icon: '⚙️', label: '设置', href: 'settings.html' }
    ];

    const rail = document.createElement('nav');
    rail.className = 'app-rail';
    rail.setAttribute('aria-label', 'QAgent Pet 主导航');
    rail.innerHTML = `
        <a class="app-rail-brand" href="index.html" aria-label="QAgent Pet 首页">
            <span>🐾</span>
            <strong>Q</strong>
        </a>
        <div class="app-rail-links">
            ${navItems.map(item => `
                <a class="app-rail-link ${item.key === activeKey ? 'active' : ''}" href="${item.href}" title="${item.label}" data-key="${item.key}">
                    <span class="app-rail-icon">${item.icon}</span>
                    <span class="app-rail-label">${item.label}</span>
                </a>
            `).join('')}
        </div>
    `;

    const topbar = document.createElement('header');
    topbar.className = 'app-topbar';
    topbar.innerHTML = `
        <div>
            <strong>QAgent Pet</strong>
            <span>你的桌面电子宠物伙伴</span>
        </div>
        <div class="app-topbar-actions">
            <button type="button" id="shell-dnd-toggle" class="app-topbar-pill">勿扰：关</button>
            <a class="app-topbar-pill primary" href="desktop_pet.html">打开桌宠预览</a>
        </div>
    `;

    document.body.prepend(topbar);
    document.body.prepend(rail);

    const dndBtn = document.getElementById('shell-dnd-toggle');
    const syncDnd = () => {
        const enabled = localStorage.getItem('qagent_dnd_mode') === 'true';
        dndBtn.textContent = enabled ? '勿扰：开' : '勿扰：关';
        dndBtn.classList.toggle('enabled', enabled);
    };
    dndBtn.addEventListener('click', () => {
        const enabled = localStorage.getItem('qagent_dnd_mode') === 'true';
        localStorage.setItem('qagent_dnd_mode', String(!enabled));
        syncDnd();
    });
    syncDnd();
}

window.initAppShell = initAppShell;
