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
        leisureSession: null,
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
        document.querySelectorAll('.want-tab').forEach(button => {
            const active = button.dataset.tab === selected;
            button.classList.toggle('active', active);
            button.setAttribute('aria-selected', String(active));
        });
        document.getElementById('learn-panel').hidden = selected !== 'learn';
        document.getElementById('leisure-panel').hidden = selected !== 'leisure';
        if (updateUrl) history.replaceState(null, '', `want.html?ui=4&tab=${selected}`);
    }

    function requestId() {
        return window.crypto?.randomUUID?.() || `progress-${Date.now()}-${Math.random().toString(36).slice(2)}`;
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
        if (!state.books.length) {
            list.innerHTML = '<div class="empty-state">书架暂时是空的</div>';
            status.textContent = '暂无读物';
            return;
        }
        const sortedBooks = [...state.books].sort((first, second) => {
            const firstTime = Date.parse(state.progressByBook.get(first.book_id)?.last_read_at_utc || '') || 0;
            const secondTime = Date.parse(state.progressByBook.get(second.book_id)?.last_read_at_utc || '') || 0;
            return secondTime - firstTime || String(first.title).localeCompare(String(second.title), 'zh-CN');
        });
        sortedBooks.forEach(renderBook);
        const readingCount = sortedBooks.filter(book => progressPercent(state.progressByBook.get(book.book_id)) > 0).length;
        status.textContent = readingCount ? `${sortedBooks.length} 本读物 · ${readingCount} 本有进度` : `${sortedBooks.length} 本内置读物`;
    }

    function renderBook(book) {
        const progress = state.progressByBook.get(book.book_id);
        const percent = progressPercent(progress);
        const buttonText = percent >= 100 ? '重新阅读' : percent > 0 ? '继续阅读' : '开始阅读';
        const progressText = percent >= 100 ? '已读完' : percent > 0 ? `已读 ${percent}%` : '还没开始';
        const item = document.createElement('article');
        item.className = 'book-item';
        item.innerHTML = `<div class="book-cover" aria-hidden="true">阅</div><div class="book-info"><small>${escapeHtml(book.author || 'QAgent')}</small><h3>${escapeHtml(book.title)}</h3><p>${escapeHtml(book.description || '')}</p><div class="book-progress"><div><span style="width:${percent}%"></span></div><small>${progressText}</small></div><button type="button">${buttonText}</button></div>`;
        item.querySelector('button').addEventListener('click', () => openBook(book));
        document.getElementById('book-list').appendChild(item);
    }

    async function openBook(book) {
        const status = document.getElementById('leisure-status');
        status.textContent = '正在打开…';
        try {
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
            document.getElementById('leisure-library').hidden = true;
            document.getElementById('novel-reader').hidden = false;
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
        document.getElementById('novel-reader').hidden = true;
        document.getElementById('leisure-library').hidden = false;
        renderLibrary();
    }

    function bindEvents() {
        document.querySelectorAll('.want-tab').forEach(button => button.addEventListener('click', () => selectTab(button.dataset.tab)));
        document.getElementById('start-learning').addEventListener('click', () => {
            window.location.href = `learn.html?pet_id=${encodeURIComponent(state.petId)}`;
        });
        document.getElementById('close-reader').addEventListener('click', closeReader);
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
    }

    init();
})();
