(function () {
  'use strict';

  const BG_OPACITY_KEY = 'qagent_novel_bg_opacity';
  const TEXT_OPACITY_KEY = 'qagent_novel_text_opacity';
  const FONT_SIZE_KEY = 'qagent_novel_font_size';
  const TEXT_COLOR_KEY = 'qagent_novel_text_rgb';
  const state = {
    books: [],
    book: null,
    chapters: [],
    chapterIndex: 0,
    session: null
  };

  const els = {
    shell: document.querySelector('.novel-shell'),
    bookTitle: document.getElementById('novel-book-title'),
    library: document.getElementById('novel-library'),
    libraryStatus: document.getElementById('novel-library-status'),
    bookList: document.getElementById('novel-book-list'),
    reader: document.getElementById('novel-reader'),
    chapterTitle: document.getElementById('reader-chapter-title'),
    chapterSelect: document.getElementById('chapter-select'),
    readerContent: document.getElementById('reader-content'),
    readerProgress: document.getElementById('reader-progress'),
    prevChapter: document.getElementById('prev-chapter'),
    nextChapter: document.getElementById('next-chapter'),
    backBtn: document.getElementById('novel-back'),
    importBtn: document.getElementById('novel-import'),
    closeBtn: document.getElementById('novel-close'),
    bgOpacityInput: document.getElementById('novel-bg-opacity'),
    textOpacityInput: document.getElementById('novel-text-opacity'),
    fontSizeInput: document.getElementById('novel-font-size'),
    swatches: document.querySelectorAll('.swatch')
  };

  function requestId() {
    return (crypto.randomUUID ? crypto.randomUUID() : `r-${Date.now()}-${Math.random().toString(36).slice(2)}`);
  }

  function escapeHtml(value) {
    const div = document.createElement('div');
    div.textContent = value == null ? '' : String(value);
    return div.innerHTML;
  }

  // 背景与文字透明度分离:直接改 CSS 变量,窗口本身保持不透明,
  // 避免 setOpacity 把文字一起变淡。
  function setBgOpacity(value) {
    const v = Math.max(0.05, Math.min(0.95, Number(value) || 0.55));
    if (els.bgOpacityInput) els.bgOpacityInput.value = String(v);
    els.shell.style.setProperty('--panel-alpha', String(v));
    try { localStorage.setItem(BG_OPACITY_KEY, String(v)); } catch (_) {}
  }

  function setTextOpacity(value) {
    const v = Math.max(0.2, Math.min(1, Number(value) || 0.92));
    if (els.textOpacityInput) els.textOpacityInput.value = String(v);
    els.shell.style.setProperty('--text-alpha', String(v));
    try { localStorage.setItem(TEXT_OPACITY_KEY, String(v)); } catch (_) {}
  }

  function setFontSize(value) {
    const px = Math.max(13, Math.min(26, Math.round(Number(value) || 15)));
    if (els.fontSizeInput) els.fontSizeInput.value = String(px);
    els.shell.style.setProperty('--reader-font-size', `${px}px`);
    try { localStorage.setItem(FONT_SIZE_KEY, String(px)); } catch (_) {}
  }

  function setTextColor(rgb) {
    const valid = /^\d{1,3},\s?\d{1,3},\s?\d{1,3}$/.test(rgb || '');
    if (!valid) return;
    els.shell.style.setProperty('--text-rgb', rgb);
    els.swatches.forEach(btn => btn.classList.toggle('active', btn.dataset.textRgb === rgb));
    try { localStorage.setItem(TEXT_COLOR_KEY, rgb); } catch (_) {}
  }

  function restoreReadingPrefs() {
    let bg = 0.55;
    let text = 0.92;
    let fontSize = 15;
    let color = '245,245,250';
    try {
      const savedBg = parseFloat(localStorage.getItem(BG_OPACITY_KEY) || '');
      const savedText = parseFloat(localStorage.getItem(TEXT_OPACITY_KEY) || '');
      const savedSize = parseInt(localStorage.getItem(FONT_SIZE_KEY) || '', 10);
      const savedColor = localStorage.getItem(TEXT_COLOR_KEY);
      if (Number.isFinite(savedBg)) bg = savedBg;
      if (Number.isFinite(savedText)) text = savedText;
      if (Number.isFinite(savedSize)) fontSize = savedSize;
      if (savedColor) color = savedColor;
    } catch (_) {}
    setBgOpacity(bg);
    setTextOpacity(text);
    setFontSize(fontSize);
    setTextColor(color);
  }

  async function ensureBackend() {
    if (!window.desktopAPI) return false;
    const result = await window.desktopAPI.ensureBackend();
    if (!result.ok) {
      els.libraryStatus.textContent = result.error || '后端启动失败';
      return false;
    }
    await window.desktopAPI.ensureSession();
    return true;
  }

  async function loadLibrary() {
    els.libraryStatus.textContent = '正在加载…';
    els.bookList.innerHTML = '';
    try {
      const response = await window.desktopAPI.listNovels();
      state.books = response.books || [];
      renderLibrary();
    } catch (error) {
      els.libraryStatus.textContent = error.message || '加载失败';
    }
  }

  function renderLibrary() {
    els.bookList.innerHTML = '';
    if (!state.books.length) {
      els.libraryStatus.textContent = '书架暂时是空的，点右上角 + 导入小说';
      return;
    }
    els.libraryStatus.textContent = `${state.books.length} 本读物`;
    for (const book of state.books) {
      const li = document.createElement('li');
      li.className = 'book-item';
      li.innerHTML = `
        <div class="book-cover">阅</div>
        <div class="book-info">
          <h3>${escapeHtml(book.title)}</h3>
          <small>${escapeHtml(book.author || '')}</small>
          <p>${escapeHtml(book.description || '')}</p>
          <div class="book-progress">
            <div class="bar"><span style="width:0%"></span></div>
            <small data-progress></small>
          </div>
        </div>`;
      li.addEventListener('click', () => openBook(book));
      els.bookList.appendChild(li);
      window.desktopAPI.getNovelProgress(book.book_id)
        .then(res => {
          const progress = res.progress;
          const percent = progress ? Math.round((progress.percent || 0) * 100) : 0;
          const bar = li.querySelector('.book-progress .bar span');
          const text = li.querySelector('[data-progress]');
          if (bar) bar.style.width = `${percent}%`;
          if (text) text.textContent = percent >= 100 ? '已读完' : percent > 0 ? `已读 ${percent}%` : '';
        })
        .catch(() => {});
    }
  }

  async function openBook(book) {
    try {
      els.libraryStatus.textContent = '正在打开…';
      const [chaptersRes, progressRes, session] = await Promise.all([
        window.desktopAPI.listNovelChapters(book.book_id),
        window.desktopAPI.getNovelProgress(book.book_id),
        window.desktopAPI.openNovelSession(book.book_id)
      ]);
      state.book = book;
      state.chapters = chaptersRes.chapters || [];
      state.session = session;
      const savedChapter = progressRes.progress && progressRes.progress.last_chapter_id;
      const savedIndex = state.chapters.findIndex(ch => ch.chapter_id === savedChapter);
      state.chapterIndex = savedIndex >= 0 ? savedIndex : 0;

      els.library.hidden = true;
      els.reader.hidden = false;
      els.backBtn.hidden = false;
      els.bookTitle.textContent = book.title;
      populateChapterSelect();
      await renderChapter();
    } catch (error) {
      els.libraryStatus.textContent = error.message || '打开失败';
    }
  }

  function populateChapterSelect() {
    els.chapterSelect.innerHTML = '';
    state.chapters.forEach((chapter, index) => {
      const option = document.createElement('option');
      option.value = chapter.chapter_id;
      option.textContent = `${index + 1}. ${chapter.title}`;
      els.chapterSelect.appendChild(option);
    });
  }

  async function renderChapter() {
    const meta = state.chapters[state.chapterIndex];
    if (!meta || !state.book) return;
    try {
      const chapter = await window.desktopAPI.getNovelChapter(state.book.book_id, meta.chapter_id);
      els.chapterTitle.textContent = chapter.title;
      els.readerContent.textContent = chapter.content;
      els.readerProgress.textContent = `${state.chapterIndex + 1} / ${state.chapters.length}`;
      els.chapterSelect.value = meta.chapter_id;
      els.prevChapter.disabled = state.chapterIndex === 0;
      els.nextChapter.disabled = state.chapterIndex >= state.chapters.length - 1;
      els.nextChapter.textContent = state.chapterIndex >= state.chapters.length - 1 ? '已读完' : '下一章';
      els.readerContent.scrollTop = 0;
      await saveProgress(meta.chapter_id);
    } catch (error) {
      els.readerContent.textContent = '加载章节失败: ' + (error.message || '');
    }
  }

  async function saveProgress(chapterId) {
    if (!state.book || !chapterId) return;
    const percent = state.chapters.length ? (state.chapterIndex + 1) / state.chapters.length : 0;
    try {
      await window.desktopAPI.saveNovelProgress(state.book.book_id, {
        chapter_id: chapterId,
        position: 0,
        percent,
        content_version: state.book.content_version || '1.0.0',
        client_updated_at_utc: new Date().toISOString(),
        request_id: requestId()
      });
    } catch (_) {
      // 离线时保持本地可读,不阻塞阅读
    }
  }

  async function closeSessionIfAny() {
    if (state.session && state.session.session_id) {
      try { await window.desktopAPI.closeNovelSession(state.session.session_id); } catch (_) {}
      state.session = null;
    }
  }

  async function openBookById(bookId) {
    if (!bookId) return;
    if (!state.books.length) {
      const ok = await ensureBackend();
      if (!ok) return;
      await loadLibrary();
    }
    const book = state.books.find(item => item.book_id === bookId);
    if (!book) {
      // 书籍可能属于另一个账号(归属隔离),桌宠端不可见
      els.reader.hidden = true;
      els.library.hidden = false;
      els.backBtn.hidden = true;
      els.libraryStatus.textContent = '这本书在当前桌面账号下不可见,请在桌宠端导入后再读';
      return;
    }
    if (state.book && state.book.book_id === book.book_id && !els.reader.hidden) {
      return; // 已经在读这本,不打断当前位置
    }
    await closeSessionIfAny();
    await openBook(book);
  }

  function showLibrary() {
    closeSessionIfAny();
    state.book = null;
    state.chapters = [];
    els.reader.hidden = true;
    els.library.hidden = false;
    els.backBtn.hidden = true;
    els.bookTitle.textContent = '小说';
    loadLibrary();
  }

  async function importNovel() {
    try {
      els.libraryStatus.textContent = '正在导入…';
      const result = await window.desktopAPI.importNovel();
      if (result && result.canceled) {
        loadLibrary();
        return;
      }
      if (result && result.book) {
        els.libraryStatus.textContent = `已导入《${result.book.title}》(${result.book.chapter_count} 章)`;
      }
      await loadLibrary();
    } catch (error) {
      els.libraryStatus.textContent = error.message || '导入失败';
      loadLibrary();
    }
  }

  function bindEvents() {
    els.backBtn.addEventListener('click', showLibrary);
    els.closeBtn.addEventListener('click', () => {
      closeSessionIfAny();
      if (window.desktopAPI.hideNovel) window.desktopAPI.hideNovel();
    });
    els.importBtn.addEventListener('click', importNovel);
    els.bgOpacityInput.addEventListener('input', () => setBgOpacity(els.bgOpacityInput.value));
    els.textOpacityInput.addEventListener('input', () => setTextOpacity(els.textOpacityInput.value));
    els.fontSizeInput.addEventListener('input', () => setFontSize(els.fontSizeInput.value));
    els.swatches.forEach(btn => btn.addEventListener('click', () => setTextColor(btn.dataset.textRgb)));

    els.prevChapter.addEventListener('click', async () => {
      if (state.chapterIndex > 0) {
        state.chapterIndex -= 1;
        await renderChapter();
      }
    });
    els.nextChapter.addEventListener('click', async () => {
      if (state.chapterIndex < state.chapters.length - 1) {
        state.chapterIndex += 1;
        await renderChapter();
      }
    });
    els.chapterSelect.addEventListener('change', async event => {
      const index = state.chapters.findIndex(ch => ch.chapter_id === event.target.value);
      if (index >= 0) {
        state.chapterIndex = index;
        await renderChapter();
      }
    });

    // 键盘左右切换章节
    window.addEventListener('keydown', async event => {
      if (els.reader.hidden) return;
      if (event.key === 'ArrowLeft' && state.chapterIndex > 0) {
        state.chapterIndex -= 1;
        await renderChapter();
      } else if (event.key === 'ArrowRight' && state.chapterIndex < state.chapters.length - 1) {
        state.chapterIndex += 1;
        await renderChapter();
      }
    });
  }

  async function init() {
    restoreReadingPrefs();
    bindEvents();
    if (window.desktopAPI.onOpenNovelBook) {
      window.desktopAPI.onOpenNovelBook((bookId) => { openBookById(bookId); });
    }
    const ok = await ensureBackend();
    if (ok) await loadLibrary();
  }

  init();
})();
