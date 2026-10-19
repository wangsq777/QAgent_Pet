(function () {
    'use strict';

    const PETS = {
        hot_dog: { name: 'Hot Dog', image: 'images/hot_dog.png' },
        cold_cat: { name: 'Cold Cat', image: 'images/cold_cat.png' },
        mouse: { name: '鼠鼠', image: 'images/mouse.png' }
    };
    const READER_SETTINGS_KEY = 'qagent_reader_settings';
    const DEFAULT_READER_SETTINGS = { fontSize: '18', lineHeight: '1.85', theme: 'paper' };
    const state = {
        petId: 'hot_dog',
        pet: PETS.hot_dog,
        books: [],
        progressByBook: new Map(),
        chapters: [],
        chapterIndex: 0,
        book: null,
        query: '',
        leisureSession: null,
        embeddedBrowserCard: null,
        embeddedBrowserView: null,
        readerSettings: loadReaderSettings()
    };

    function loadReaderSettings() {
        try {
            const saved = JSON.parse(localStorage.getItem(READER_SETTINGS_KEY) || '{}');
            return {
                fontSize: ['16', '18', '20', '22'].includes(String(saved.fontSize)) ? String(saved.fontSize) : DEFAULT_READER_SETTINGS.fontSize,
                lineHeight: ['1.65', '1.85', '2.05'].includes(String(saved.lineHeight)) ? String(saved.lineHeight) : DEFAULT_READER_SETTINGS.lineHeight,
                theme: ['light', 'paper', 'dark'].includes(saved.theme) ? saved.theme : DEFAULT_READER_SETTINGS.theme
            };
        } catch (error) {
            return { ...DEFAULT_READER_SETTINGS };
        }
    }

    function applyReaderSettings() {
        const reader = document.getElementById('novel-reader');
        reader.dataset.theme = state.readerSettings.theme;
        reader.style.setProperty('--reader-font-size', `${state.readerSettings.fontSize}px`);
        reader.style.setProperty('--reader-line-height', state.readerSettings.lineHeight);
        document.getElementById('font-size-select').value = state.readerSettings.fontSize;
        document.getElementById('line-height-select').value = state.readerSettings.lineHeight;
        document.querySelectorAll('[data-reader-theme]').forEach(button => {
            const active = button.dataset.readerTheme === state.readerSettings.theme;
            button.classList.toggle('active', active);
            button.setAttribute('aria-pressed', String(active));
        });
        localStorage.setItem(READER_SETTINGS_KEY, JSON.stringify(state.readerSettings));
    }

    function currentPet() {
        const type = localStorage.getItem('qagent_pet_type') || 'hot_dog';
        if (type === 'custom') {
            const id = localStorage.getItem('qagent_custom_pet_id');
            const name = localStorage.getItem('qagent_custom_pet_name') || '我的宠物';
            const image = localStorage.getItem('qagent_custom_avatar') || 'images/custom_pet.svg';
            if (id) return { id, name, image };
        }
        return { id: PETS[type] ? type : 'hot_dog', ...(PETS[type] || PETS.hot_dog) };
    }

    function setPet(pet) {
        state.petId = pet.id;
        state.pet = pet;
        document.getElementById('want-pet-name').textContent = pet.name;
        document.getElementById('want-pet-avatar').src = pet.image;
        document.getElementById('learn-pet-image').src = pet.image;
        document.querySelectorAll('.pet-option').forEach(button => button.classList.toggle('active', button.dataset.petId === pet.id));
    }

    function renderPetOptions() {
        const options = document.getElementById('pet-options');
        const choices = Object.entries(PETS).map(([id, pet]) => ({ id, ...pet }));
        const selected = currentPet();
        if (!PETS[selected.id]) choices.unshift(selected);
        choices.forEach(pet => {
            const button = document.createElement('button');
            button.type = 'button';
            button.className = 'pet-option';
            button.dataset.petId = pet.id;
            const image = document.createElement('img');
            image.src = pet.image; image.alt = '';
            const label = document.createElement('span');
            label.textContent = pet.name;
            button.append(image, label);
            button.addEventListener('click', () => setPet(pet));
            options.appendChild(button);
        });
        setPet(selected);
    }

    function selectTab(name, updateUrl = true) {
        const selected = name === 'leisure' ? 'leisure' : 'learn';
        if (selected !== 'leisure') closeEmbeddedBrowser();
        document.querySelectorAll('.want-tab').forEach(button => {
            const active = button.dataset.tab === selected;
            button.classList.toggle('active', active);
            button.setAttribute('aria-selected', String(active));
        });
        document.getElementById('learn-panel').hidden = selected !== 'learn';
        document.getElementById('leisure-panel').hidden = selected !== 'leisure';
        document.body.classList.toggle('leisure-mode', selected === 'leisure');
        document.title = selected === 'leisure' ? 'Codex - 项目资料' : '你想要的 - QAgent Pet';
        if (updateUrl) history.replaceState(null, '', `want.html?ui=4&tab=${selected}`);
    }

    function requestId() {
        return window.crypto?.randomUUID?.() || `progress-${Date.now()}-${Math.random().toString(36).slice(2)}`;
    }

    // 串门入口与聊天页顶栏按钮共用同一套前置条件:至少创建过一只自定义宠物。
    async function initVisitEntry() {
        const card = document.getElementById('visit-entry-card');
        if (!card) return;
        let hasCustomPets = false;
        try {
            const data = await API.listCustomPets();
            hasCustomPets = (data.pets || []).length >= 1;
        } catch (error) {
            hasCustomPets = false;
        }
        if (hasCustomPets) {
            card.addEventListener('click', () => {
                window.location.href = 'chat.html?ui=4&visit=open';
            });
        } else {
            card.classList.add('disabled');
            document.getElementById('visit-entry-desc').textContent = '先在广场创建一只自定义宠物，就能邀请它来串门';
            card.addEventListener('click', () => {
                window.location.href = 'index.html?ui=4';
            });
        }
    }

    async function loadLibrary() {
        const status = document.getElementById('leisure-status');
        const list = document.getElementById('book-list');
        try {
            const [modules, books] = await Promise.all([API.leisureModules(), API.listLeisureNovels()]);
            state.books = books.books || [];
            if (!(modules.modules || []).some(item => item.module_id === 'builtin.novel')) {
                throw new Error('小说模块当前不可用');
            }
            const progressEntries = await Promise.all(state.books.map(async book => {
                try {
                    const response = await API.getNovelProgress(book.book_id);
                    return [book.book_id, response.progress || null];
                } catch (error) {
                    return [book.book_id, null];
                }
            }));
            state.progressByBook = new Map(progressEntries);
            renderLibrary();
        } catch (error) {
            status.textContent = '加载失败';
            list.innerHTML = `<div class="empty-state">${escapeHtml(error.message)}</div>`;
        }
    }

    function escapeHtml(value) {
        const element = document.createElement('div');
        element.textContent = value == null ? '' : String(value);
        return element.innerHTML;
    }

    function progressPercent(progress) {
        const value = Number(progress?.percent || 0);
        return Math.max(0, Math.min(100, Math.round(value * 100)));
    }

    function renderLibrary() {
        const list = document.getElementById('book-list');
        const status = document.getElementById('leisure-status');
        list.innerHTML = '';
        const recent = document.getElementById('recent-book-list');
        recent.replaceChildren();
        if (!state.books.length) {
            list.innerHTML = '<div class="empty-state">暂无资料</div>';
            status.textContent = '暂无资料';
            return;
        }
        const sortedBooks = [...state.books].sort((first, second) => {
            const firstTime = Date.parse(state.progressByBook.get(first.book_id)?.last_read_at_utc || '') || 0;
            const secondTime = Date.parse(state.progressByBook.get(second.book_id)?.last_read_at_utc || '') || 0;
            return secondTime - firstTime || String(first.title).localeCompare(String(second.title), 'zh-CN');
        });
        sortedBooks.filter(book => state.progressByBook.get(book.book_id)?.last_read_at_utc).slice(0, 6).forEach(book => {
            const button = document.createElement('button');
            button.type = 'button';
            button.textContent = book.title;
            button.title = book.title;
            button.addEventListener('click', () => openBook(book));
            recent.appendChild(button);
        });
        const matches = sortedBooks.filter(book => `${book.title} ${book.author || ''} ${book.description || ''}`.toLowerCase().includes(state.query.toLowerCase()));
        matches.forEach(renderBook);
        if (!matches.length) list.innerHTML = '<div class="empty-state">没有找到匹配的资料</div>';
        const readingCount = sortedBooks.filter(book => progressPercent(state.progressByBook.get(book.book_id)) > 0).length;
        status.textContent = state.query ? `${matches.length} 条匹配结果` : readingCount ? `${sortedBooks.length} 份资料 · ${readingCount} 份有进度` : `${sortedBooks.length} 份资料`;
    }

    function canDesktopRead() {
        return Boolean(window.desktopAPI && typeof window.desktopAPI.openNovelBook === 'function');
    }

    function canDesktopFeed() {
        return Boolean(window.desktopAPI && typeof window.desktopAPI.resolveEmbeddedFeedTarget === 'function');
    }

    function closeEmbeddedBrowser() {
        if (state.embeddedBrowserCard) state.embeddedBrowserCard.remove();
        state.embeddedBrowserCard = null;
        state.embeddedBrowserView = null;
    }

    function appendUserTurn(text) {
        const turn = document.createElement('article');
        turn.className = 'workspace-message workspace-user';
        const bubble = document.createElement('div');
        bubble.className = 'workspace-bubble';
        bubble.textContent = text;
        turn.appendChild(bubble);
        document.getElementById('workspace-messages').insertBefore(turn, document.getElementById('novel-reader'));
    }

    function showEmbeddedBrowser(target) {
        // Electron 的 webview guest 销毁是异步的。切换链接时复用现有 guest，
        // 避免旧 guest 的原生表面还未销毁就与新 guest 重叠，造成 Codex 页面空白遮挡。
        if (state.embeddedBrowserCard && state.embeddedBrowserView && state.embeddedBrowserView.isConnected) {
            const title = state.embeddedBrowserCard.querySelector('.embedded-browser-toolbar strong');
            const status = state.embeddedBrowserCard.querySelector('.embedded-browser-status');
            if (title) title.textContent = target.name || '网页';
            if (status) status.textContent = '正在加载…';
            state.embeddedBrowserView.setAttribute('src', target.url);
            state.embeddedBrowserCard.scrollIntoView({ block: 'start' });
            return;
        }

        const card = document.createElement('article');
        card.className = 'workspace-message workspace-assistant embedded-browser-message';

        const avatar = document.createElement('div');
        avatar.className = 'workspace-avatar';
        avatar.setAttribute('aria-hidden', 'true');
        avatar.textContent = '✳';

        const response = document.createElement('div');
        response.className = 'workspace-response';
        const heading = document.createElement('div');
        heading.className = 'workspace-message-heading';
        heading.textContent = 'Codex';

        const browser = document.createElement('div');
        browser.className = 'embedded-browser';
        const toolbar = document.createElement('div');
        toolbar.className = 'embedded-browser-toolbar';
        const title = document.createElement('strong');
        title.textContent = target.name || '网页';
        const status = document.createElement('span');
        status.className = 'embedded-browser-status';
        status.textContent = '正在加载…';
        const controls = document.createElement('div');
        controls.className = 'embedded-browser-controls';
        const makeButton = (label, name) => {
            const button = document.createElement('button');
            button.type = 'button';
            button.className = 'icon-command';
            button.textContent = label;
            button.title = name;
            button.setAttribute('aria-label', name);
            return button;
        };
        const back = makeButton('←', '后退');
        const forward = makeButton('→', '前进');
        const reload = makeButton('↻', '刷新');
        const close = makeButton('×', '关闭网页');
        controls.append(back, forward, reload, close);
        toolbar.append(title, status, controls);

        const view = document.createElement('webview');
        view.className = 'embedded-browser-view';
        view.setAttribute('partition', 'persist:feed');
        view.setAttribute('src', target.url);
        view.setAttribute('allowpopups', 'false');
        if (target.userAgent) view.setAttribute('useragent', target.userAgent);

        const updateNavButtons = () => {
            try {
                back.disabled = !view.canGoBack();
                forward.disabled = !view.canGoForward();
            } catch (error) {
                back.disabled = true;
                forward.disabled = true;
            }
        };
        back.addEventListener('click', () => { if (view.canGoBack()) view.goBack(); });
        forward.addEventListener('click', () => { if (view.canGoForward()) view.goForward(); });
        reload.addEventListener('click', () => view.reload());
        close.addEventListener('click', closeEmbeddedBrowser);
        view.addEventListener('did-start-loading', () => { status.textContent = '正在加载…'; });
        view.addEventListener('dom-ready', () => { status.textContent = '已就绪'; updateNavButtons(); });
        view.addEventListener('did-stop-loading', () => { status.textContent = '已就绪'; updateNavButtons(); });
        view.addEventListener('did-navigate', updateNavButtons);
        view.addEventListener('did-navigate-in-page', updateNavButtons);
        view.addEventListener('did-fail-load', event => {
            if (!event.isMainFrame) return;
            status.textContent = '网页加载失败，请稍后重试';
        });

        const viewWrap = document.createElement('div');
        viewWrap.className = 'embedded-browser-view-wrap';
        viewWrap.appendChild(view);

        browser.append(toolbar, viewWrap);
        response.append(heading, browser);
        card.append(avatar, response);
        document.getElementById('workspace-messages').insertBefore(card, document.getElementById('novel-reader'));
        state.embeddedBrowserCard = card;
        state.embeddedBrowserView = view;
        card.scrollIntoView({ block: 'start' });
    }

    async function openEmbeddedFeed(request, prompt) {
        if (!canDesktopFeed()) return;
        const result = await window.desktopAPI.resolveEmbeddedFeedTarget(request);
        if (!result || !result.ok) {
            const status = document.getElementById('leisure-status');
            if (status) status.textContent = result?.error || '网页打开失败';
            return result;
        }
        if (state.leisureSession) await closeReader();
        document.getElementById('workspace-title').textContent = result.name || '摸鱼网页';
        appendUserTurn(prompt || `打开${result.name || '网页'}`);
        showEmbeddedBrowser(result);
        return result;
    }

    function readOnDesktop(book) {
        if (!canDesktopRead()) return;
        window.desktopAPI.openNovelBook(book.book_id).catch(() => {});
        const status = document.getElementById('leisure-status');
        if (status) status.textContent = `《${book.title}》已在桌面阅读窗打开`;
    }

    function renderBook(book) {
        const progress = state.progressByBook.get(book.book_id);
        const percent = progressPercent(progress);
        const buttonText = percent >= 100 ? '重新查看' : percent > 0 ? '继续查看' : '打开资料';
        const progressText = percent >= 100 ? '已读完' : percent > 0 ? `已读 ${percent}%` : '还没开始';
        const isImported = book.content_source === 'user';
        const desktopBtn = canDesktopRead() ? '<button type="button" data-desktop>桌面阅读</button>' : '';
        const item = document.createElement('article');
        item.className = 'book-item';
        item.innerHTML = `<div class="book-cover" aria-hidden="true">▤</div><div class="book-info"><small>${escapeHtml(book.author || '本地资料')}</small><h3>${escapeHtml(book.title)}</h3><p>${escapeHtml(book.description || '')}</p><div class="book-progress"><div><span style="width:${percent}%"></span></div><small>${progressText}</small></div><div class="book-actions"><button type="button" data-read>${buttonText}</button>${desktopBtn}${isImported ? '<button type="button" class="danger-command" data-delete>删除</button>' : ''}</div></div>`;
        item.querySelector('[data-read]').addEventListener('click', () => openBook(book));
        const desktopReadBtn = item.querySelector('[data-desktop]');
        if (desktopReadBtn) {
            desktopReadBtn.addEventListener('click', (event) => {
                event.stopPropagation();
                readOnDesktop(book);
            });
        }
        const deleteBtn = item.querySelector('[data-delete]');
        if (deleteBtn) {
            deleteBtn.addEventListener('click', async (event) => {
                event.stopPropagation();
                if (!confirm(`删除《${book.title}》？导入的进度会一并清除。`)) return;
                try {
                    await API.deleteNovel(book.book_id);
                    state.books = state.books.filter(b => b.book_id !== book.book_id);
                    state.progressByBook.delete(book.book_id);
                    renderLibrary();
                } catch (error) {
                    alert(error.message || '删除失败');
                }
            });
        }
        document.getElementById('book-list').appendChild(item);
    }

    async function openBook(book) {
        const status = document.getElementById('leisure-status');
        status.textContent = '正在打开…';
        try {
            closeEmbeddedBrowser();
            if (state.leisureSession) await closeReader();
            const [chapters, progress, session] = await Promise.all([
                API.listNovelChapters(book.book_id),
                API.getNovelProgress(book.book_id),
                API.openLeisureSession('builtin.novel', book.book_id)
            ]);
            state.book = book;
            state.chapters = chapters.chapters || [];
            state.leisureSession = session;
            const savedChapter = progress.progress?.last_chapter_id;
            const savedIndex = state.chapters.findIndex(chapter => chapter.chapter_id === savedChapter);
            state.chapterIndex = savedIndex >= 0 ? savedIndex : 0;
            populateChapterSelect();
            document.getElementById('workspace-title').textContent = book.title;
            const turn = document.createElement('article');
            turn.className = 'workspace-message workspace-user';
            const bubble = document.createElement('div');
            bubble.className = 'workspace-bubble';
            bubble.textContent = `打开《${book.title}》`;
            turn.appendChild(bubble);
            document.getElementById('workspace-messages').insertBefore(turn, document.getElementById('novel-reader'));
            document.getElementById('novel-reader').hidden = false;
            const desktopBtn = document.getElementById('desktop-read-btn');
            if (desktopBtn) desktopBtn.hidden = !canDesktopRead();
            await renderChapter();
        } catch (error) {
            status.textContent = error.message;
        }
    }

    async function renderChapter() {
        const chapterMeta = state.chapters[state.chapterIndex];
        if (!chapterMeta) return;
        const chapter = await API.getNovelChapter(state.book.book_id, chapterMeta.chapter_id);
        document.getElementById('reader-book-title').textContent = state.book.title;
        document.getElementById('reader-chapter-title').textContent = chapter.title;
        document.getElementById('reader-content').textContent = chapter.content;
        document.getElementById('reader-progress').textContent = `${state.chapterIndex + 1} / ${state.chapters.length}`;
        document.getElementById('chapter-select').value = chapterMeta.chapter_id;
        document.getElementById('previous-chapter').disabled = state.chapterIndex === 0;
        document.getElementById('next-chapter').disabled = state.chapterIndex >= state.chapters.length - 1;
        document.getElementById('next-chapter').textContent = state.chapterIndex >= state.chapters.length - 1 ? '已读完' : '下一章';
        document.getElementById('novel-reader').scrollIntoView({ block: 'start' });
        try { await saveProgress(chapterMeta.chapter_id); } catch (error) { /* reading remains available offline */ }
    }

    function populateChapterSelect() {
        const select = document.getElementById('chapter-select');
        select.innerHTML = '';
        state.chapters.forEach((chapter, index) => {
            const option = document.createElement('option');
            option.value = chapter.chapter_id;
            option.textContent = `${index + 1}. ${chapter.title}`;
            select.appendChild(option);
        });
    }

    async function saveProgress(chapterId) {
        if (!state.book || !chapterId) return;
        const percent = state.chapters.length ? (state.chapterIndex + 1) / state.chapters.length : 0;
        const saved = await API.saveNovelProgress(state.book.book_id, {
            chapter_id: chapterId,
            position: 0,
            percent,
            content_version: state.book.content_version,
            client_updated_at_utc: new Date().toISOString(),
            request_id: requestId()
        });
        state.progressByBook.set(state.book.book_id, saved);
    }

    async function closeReader() {
        if (state.leisureSession?.session_id) {
            try { await API.closeLeisureSession(state.leisureSession.session_id); } catch (error) { /* keep local UI responsive */ }
        }
        state.leisureSession = null;
        closeEmbeddedBrowser();
        document.getElementById('novel-reader').hidden = true;
        document.getElementById('workspace-title').textContent = '项目资料整理';
        renderLibrary();
    }

    function bindEvents() {
        document.querySelectorAll('.want-tab').forEach(button => button.addEventListener('click', () => selectTab(button.dataset.tab)));
        const showLibrary = async (newTask = false) => {
            closeEmbeddedBrowser();
            if (state.leisureSession) await closeReader();
            state.query = '';
            document.getElementById('workspace-query').value = '';
            if (newTask) document.querySelectorAll('#workspace-messages .workspace-user:not(:first-child)').forEach(turn => turn.remove());
            renderLibrary();
            document.getElementById('workspace-messages').insertBefore(document.getElementById('leisure-library'), document.getElementById('novel-reader'));
            document.getElementById('leisure-library').scrollIntoView({ block: 'start' });
        };
        document.getElementById('workspace-home').addEventListener('click', () => showLibrary(true));
        document.getElementById('workspace-library').addEventListener('click', () => showLibrary());
        const composer = document.getElementById('workspace-composer');
        const queryInput = document.getElementById('workspace-query');
        composer.addEventListener('submit', async event => {
            event.preventDefault();
            const query = queryInput.value.trim();
            if (!query) return;
            if (state.leisureSession) await closeReader();
            closeEmbeddedBrowser();
            appendUserTurn(`查找资料：${query}`);
            const messages = document.getElementById('workspace-messages');
            messages.insertBefore(document.getElementById('leisure-library'), document.getElementById('novel-reader'));
            state.query = query;
            queryInput.value = '';
            renderLibrary();
            document.getElementById('leisure-library').scrollIntoView({ block: 'start' });
        });
        queryInput.addEventListener('keydown', event => {
            if (event.key === 'Enter' && !event.shiftKey && !event.isComposing) {
                event.preventDefault();
                composer.requestSubmit();
            }
        });
        document.getElementById('start-learning').addEventListener('click', () => {
            window.location.href = `learn.html?pet_id=${encodeURIComponent(state.petId)}`;
        });
        const feedSelect = document.getElementById('feed-channel-select');
        if (feedSelect) {
            feedSelect.hidden = !canDesktopFeed();
            feedSelect.addEventListener('change', async () => {
                const channel = feedSelect.value;
                if (channel) {
                    const option = feedSelect.options[feedSelect.selectedIndex];
                    await openEmbeddedFeed({ type: 'channel', channel }, `打开${option?.textContent || '网页'}`);
                }
                feedSelect.value = '';
            });
        }
        // 摸鱼·B 站视频作为一条新的 Codex 回复嵌入当前会话,不再弹出独立窗口。
        const playBiliBtn = document.getElementById('play-bili-video-btn');
        const biliBar = document.getElementById('bili-video-bar');
        const biliInput = document.getElementById('bili-video-input');
        const biliGo = document.getElementById('bili-video-go');
        if (playBiliBtn && biliBar && biliInput && biliGo && canDesktopFeed()) {
            playBiliBtn.hidden = false;
            playBiliBtn.addEventListener('click', () => {
                biliBar.hidden = !biliBar.hidden;
                if (!biliBar.hidden) biliInput.focus();
            });
            const playBiliNow = async () => {
                const value = biliInput.value.trim();
                if (!value) {
                    biliInput.focus();
                    return;
                }
                const status = document.getElementById('leisure-status');
                biliGo.disabled = true;
                if (status) status.textContent = '正在解析链接…';
                try {
                    const result = await openEmbeddedFeed({ type: 'video', input: value }, `播放 B 站视频：${value}`);
                    if (result && result.ok) {
                        biliInput.value = '';
                        biliBar.hidden = true;
                        if (status) status.textContent = '已嵌入 Codex 回复';
                    } else {
                        if (status) status.textContent = (result && result.error) || '链接解析失败';
                    }
                } catch (error) {
                    if (status) status.textContent = '播放请求失败：' + error.message;
                } finally {
                    biliGo.disabled = false;
                }
            };
            biliGo.addEventListener('click', playBiliNow);
            biliInput.addEventListener('keydown', (event) => {
                if (event.key === 'Enter') playBiliNow();
            });
        } else if (playBiliBtn) {
            playBiliBtn.hidden = true;
        }
        const importBtn = document.getElementById('import-novel-btn');
        const fileInput = document.getElementById('novel-file-input');
        if (importBtn && fileInput) {
            importBtn.addEventListener('click', () => fileInput.click());
            fileInput.addEventListener('change', async () => {
                const file = fileInput.files && fileInput.files[0];
                fileInput.value = '';
                if (!file) return;
                const status = document.getElementById('leisure-status');
                status.textContent = '正在导入…';
                try {
                    const result = await API.importNovel(file);
                    status.textContent = `已导入《${result.book.title}》(${result.book.chapter_count} 章)`;
                } catch (error) {
                    status.textContent = error.message || '导入失败';
                }
                await loadLibrary();
            });
        }
        document.getElementById('close-reader').addEventListener('click', closeReader);
        const desktopReadBtn = document.getElementById('desktop-read-btn');
        if (desktopReadBtn) {
            desktopReadBtn.addEventListener('click', () => {
                if (state.book) readOnDesktop(state.book);
            });
        }
        document.getElementById('previous-chapter').addEventListener('click', async () => {
            if (state.chapterIndex > 0) { state.chapterIndex -= 1; await renderChapter(); }
        });
        document.getElementById('next-chapter').addEventListener('click', async () => {
            if (state.chapterIndex < state.chapters.length - 1) { state.chapterIndex += 1; await renderChapter(); }
        });
        document.getElementById('chapter-select').addEventListener('change', async event => {
            const index = state.chapters.findIndex(chapter => chapter.chapter_id === event.target.value);
            if (index >= 0) { state.chapterIndex = index; await renderChapter(); }
        });
        document.getElementById('font-size-select').addEventListener('change', event => {
            state.readerSettings.fontSize = event.target.value;
            applyReaderSettings();
        });
        document.getElementById('line-height-select').addEventListener('change', event => {
            state.readerSettings.lineHeight = event.target.value;
            applyReaderSettings();
        });
        document.querySelectorAll('[data-reader-theme]').forEach(button => button.addEventListener('click', () => {
            state.readerSettings.theme = button.dataset.readerTheme;
            applyReaderSettings();
        }));
    }

    function init() {
        initAppShell('want');
        renderPetOptions();
        bindEvents();
        applyReaderSettings();
        selectTab(new URLSearchParams(location.search).get('tab') || 'learn', false);
        loadLibrary();
        initVisitEntry();
    }

    init();
})();
