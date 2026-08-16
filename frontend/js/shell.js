function initAppShell(activeKey) {
    if (document.querySelector('.app-rail')) return;

    document.body.classList.add('app-shell-enabled');

    // Lucide-compatible line icons keep navigation consistent across platforms.
    const icons = {
        index: '<path d="m3 9 9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/><polyline points="9 22 9 12 15 12 15 22"/>',
        chat: '<path d="M21 15a4 4 0 0 1-4 4H8l-5 3V7a4 4 0 0 1 4-4h10a4 4 0 0 1 4 4z"/>',
        want: '<path d="m12 3-1.9 5.8a2 2 0 0 1-1.3 1.3L3 12l5.8 1.9a2 2 0 0 1 1.3 1.3L12 21l1.9-5.8a2 2 0 0 1 1.3-1.3L21 12l-5.8-1.9a2 2 0 0 1-1.3-1.3Z"/>',
        desktop_pet: '<rect width="20" height="14" x="2" y="3" rx="2"/><line x1="8" x2="16" y1="21" y2="21"/><line x1="12" x2="12" y1="17" y2="21"/>',
        settings: '<line x1="4" x2="4" y1="21" y2="14"/><line x1="4" x2="4" y1="10" y2="3"/><line x1="12" x2="12" y1="21" y2="12"/><line x1="12" x2="12" y1="8" y2="3"/><line x1="20" x2="20" y1="21" y2="16"/><line x1="20" x2="20" y1="12" y2="3"/><line x1="1" x2="7" y1="14" y2="14"/><line x1="9" x2="15" y1="8" y2="8"/><line x1="17" x2="23" y1="16" y2="16"/>'
    };
    const iconSvg = key => `<svg viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">${icons[key]}</svg>`;
    const navItems = [
        { key: 'index', label: '广场', href: 'index.html?ui=4' },
        { key: 'chat', label: '聊天', href: 'chat.html?ui=4' },
        { key: 'want', label: '你想要的', href: 'want.html?ui=4' },
        { key: 'desktop_pet', label: '桌宠', href: 'desktop_pet.html?ui=4' },
        { key: 'settings', label: '设置', href: 'settings.html?ui=4' }
    ];
    const activeItem = navItems.find(item => item.key === activeKey) || navItems[0];

    const rail = document.createElement('nav');
    rail.className = 'app-rail';
    rail.setAttribute('aria-label', 'QAgent Pet 主导航');
    rail.innerHTML = `
        <a class="app-rail-brand" href="index.html?ui=4" aria-label="QAgent Pet 首页">
            <strong>Q</strong>
        </a>
        <div class="app-rail-links">
            ${navItems.map(item => `
                <a class="app-rail-link ${item.key === activeKey ? 'active' : ''}" href="${item.href}" title="${item.label}" data-key="${item.key}">
                    <span class="app-rail-icon">${iconSvg(item.key)}</span>
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
            <span>${activeItem.label} · 你的桌面电子宠物伙伴</span>
        </div>
        <div class="app-topbar-actions">
            <button type="button" id="shell-dnd-toggle" class="app-topbar-pill">勿扰：关</button>
            <a class="app-topbar-pill primary" href="desktop_pet.html?ui=4">打开桌宠预览</a>
        </div>
    `;

    document.body.prepend(topbar);
    document.body.prepend(rail);

    const dndBtn = document.getElementById('shell-dnd-toggle');
    const syncDnd = async () => {
        let enabled = localStorage.getItem('qagent_dnd_mode') === 'true';
        if (window.desktopAPI?.getConfig) {
            const config = await window.desktopAPI.getConfig();
            enabled = Boolean(config.dnd);
            localStorage.setItem('qagent_dnd_mode', String(enabled));
        }
        dndBtn.textContent = enabled ? '勿扰：开' : '勿扰：关';
        dndBtn.classList.toggle('enabled', enabled);
    };
    dndBtn.addEventListener('click', async () => {
        const enabled = localStorage.getItem('qagent_dnd_mode') === 'true';
        localStorage.setItem('qagent_dnd_mode', String(!enabled));
        if (window.desktopAPI?.setConfig) {
            await window.desktopAPI.setConfig({ dnd: !enabled });
        }
        await syncDnd();
    });
    syncDnd();
}

window.initAppShell = initAppShell;
