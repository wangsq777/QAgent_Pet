"""Parse user-imported novel files (TXT / EPUB / DOCX) into chapter structures.

The functions here are pure: they read bytes and return a dict with
``title``, ``author`` and ``chapters``.  No database access, no I/O beyond the
in-memory bytes.  This keeps the parsing easy to test and reuse.

Chapter identity maps onto ``novel_chapters``: ordered ``chapter_index``,
``title`` and ``content`` with ``word_count`` being the character count
(``len(content)``) since most imports are Chinese fiction.
"""
from __future__ import annotations

import re
import zipfile
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field

MAX_CHAPTER_CHARS = 50000
MAX_CHAPTERS = 2000
# EPUB 解压上限：压缩包 20MB 解压后可能膨胀数十倍（zip bomb），按总解压字节数兜底
MAX_EPUB_DECOMPRESSED_BYTES = 200 * 1024 * 1024
SUPPORTED_FORMATS = ("txt", "epub", "docx")


@dataclass
class ParsedChapter:
    title: str
    content: str
    word_count: int = 0


@dataclass
class ParsedBook:
    title: str = ""
    author: str = ""
    description: str = ""
    chapters: list[ParsedChapter] = field(default_factory=list)
    source_format: str = ""


class NovelImportError(ValueError):
    """Raised when a file cannot be parsed into a readable novel."""


# ---------- format detection ----------

def detect_format(filename: str, raw: bytes) -> str:
    name = (filename or "").lower()
    ext = ""
    if "." in name:
        ext = name.rsplit(".", 1)[-1]

    # Prefer the real container type when the extension lies.  Both EPUB and
    # DOCX are zip archives; disambiguate by their signature members.
    if zipfile.is_zipfile(_bytes_io(raw)):
        try:
            with zipfile.ZipFile(_bytes_io(raw)) as zf:
                names = set(zf.namelist())
            if "word/document.xml" in names:
                return "docx"
            if "META-INF/container.xml" in names or "mimetype" in names:
                return "epub"
        except zipfile.BadZipFile:
            pass
        if ext == "docx":
            return "docx"
        if ext == "epub":
            return "epub"

    if ext in SUPPORTED_FORMATS:
        return ext
    if ext == "pdf":
        raise NovelImportError("PDF 暂不支持，请导入 TXT / EPUB / DOCX")
    raise NovelImportError("无法识别的文件格式，仅支持 TXT / EPUB / DOCX")


# ---------- TXT ----------

# A chapter heading occupies its own line.  Covers 第X章/节/回/卷, 序章/楔子,
# and English Chapter N / CHAPTER N.  Trailing title text after the marker
# (e.g. "第十二章 风起") is kept as part of the title.
_CHAPTER_RE = re.compile(
    r"""^(?:
        第[零一二三四五六七八九十百千万两〇0-9]+[章节回卷集部篇话]
      | (?:序章|楔子|引子|前言|序言|终章|尾声|后记|番外篇?)
      | [Cc]hapter\s+[0-9IVXLCDM]+
        )(?:[\s 　、:：．·\-].{0,60})?$""",
    re.MULTILINE | re.VERBOSE,
)


def _decode_txt(raw: bytes) -> str:
    # Try UTF-8 first (strict); most modern files are UTF-8.  Fall back to
    # charset-normalizer which reliably returns gb18030/gbk for Chinese TXT.
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        pass
    try:
        from charset_normalizer import from_bytes
    except ImportError as exc:  # pragma: no cover - dependency must be present
        raise NovelImportError("缺少 charset-normalizer 依赖，无法识别文本编码") from exc
    result = from_bytes(raw).best()
    if result is None:
        raise NovelImportError("无法识别文本编码")
    return str(result)


def _split_chapters_txt(text: str) -> list[ParsedChapter]:
    matches = list(_CHAPTER_RE.finditer(text))
    if not matches:
        return [_make_chapter("正文", text)]
    chapters: list[ParsedChapter] = []
    # Text before the first heading (简介/作者的话) becomes a leading chapter.
    if matches[0].start() > 0:
        head = text[: matches[0].start()].strip()
        if head:
            chapters.append(_make_chapter("序", head))
    for index, match in enumerate(matches):
        title = match.group(0).strip()
        body_start = match.end()
        body_end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        body = text[body_start:body_end].strip()
        if body or index == 0:
            chapters.append(_make_chapter(title, body))
    return chapters or [_make_chapter("正文", text)]


def parse_txt(raw: bytes, *, filename: str = "") -> ParsedBook:
    text = _decode_txt(raw)
    title, author = _metadata_from_filename(filename)
    return ParsedBook(
        title=title,
        author=author,
        chapters=_split_chapters_txt(text),
        source_format="txt",
    )


# ---------- EPUB (stdlib only, no ebooklib) ----------

_OPF_NS = {"opf": "http://www.idpf.org/2007/opf", "dc": "http://purl.org/dc/elements/1.1/"}
_CONTAINER_NS = {"c": "urn:oasis:names:tc:opendocument:xmlns:container"}
_TAG_RE = re.compile(r"<[^>]+>")


def _strip_html(xhtml: bytes) -> str:
    # Decode, strip tags, collapse whitespace.  Good enough for novel prose;
    # avoids pulling in an HTML parser dependency.
    try:
        text = xhtml.decode("utf-8", "ignore")
    except Exception:
        text = xhtml.decode("latin-1", "ignore")
    text = text.replace("&nbsp;", " ").replace("&amp;", "&")
    text = text.replace("&lt;", "<").replace("&gt;", ">").replace("&quot;", '"')
    text = _TAG_RE.sub("\n", text)
    lines = [line.strip() for line in text.splitlines()]
    return "\n".join(line for line in lines if line).strip()


def _first_heading(xhtml: bytes) -> str:
    try:
        text = xhtml.decode("utf-8", "ignore")
    except Exception:
        return ""
    for pattern in (r"<h1[^>]*>(.*?)</h1>", r"<title>(.*?)</title>"):
        m = re.search(pattern, text, re.IGNORECASE | re.DOTALL)
        if m:
            return _TAG_RE.sub("", m.group(1)).strip()
    return ""


def parse_epub(raw: bytes, *, filename: str = "") -> ParsedBook:
    try:
        zf = zipfile.ZipFile(_bytes_io(raw))
    except zipfile.BadZipFile as exc:
        raise NovelImportError("EPUB 文件损坏") from exc
    try:
        total_decompressed = sum(info.file_size for info in zf.infolist())
        if total_decompressed > MAX_EPUB_DECOMPRESSED_BYTES:
            raise NovelImportError("EPUB 解压后体积过大，疑似压缩炸弹")

        def read_entry(name: str) -> bytes:
            info = zf.getinfo(name)
            if info.file_size > MAX_EPUB_DECOMPRESSED_BYTES:
                raise NovelImportError("EPUB 内部文件体积异常")
            return zf.read(name)

        container = ET.fromstring(read_entry("META-INF/container.xml"))
        rootfile = container.find(".//c:rootfile", _CONTAINER_NS)
        if rootfile is None or not rootfile.get("full-path"):
            raise NovelImportError("EPUB 缺少 OPF 入口")
        opf_path = rootfile.get("full-path")
        opf_dir = opf_path.rsplit("/", 1)[0] + "/" if "/" in opf_path else ""
        opf = ET.fromstring(read_entry(opf_path))

        title_node = opf.find(".//dc:title", _OPF_NS)
        creator_node = opf.find(".//dc:creator", _OPF_NS)
        title = (title_node.text or "").strip() if title_node is not None and title_node.text else ""
        author = (creator_node.text or "").strip() if creator_node is not None and creator_node.text else ""

        manifest = {item.get("id"): opf_dir + item.get("href") for item in opf.findall(".//opf:item", _OPF_NS)}
        spine_ids = [ref.get("idref") for ref in opf.findall(".//opf:itemref", _OPF_NS) if ref.get("idref")]

        chapters: list[ParsedChapter] = []
        for index, sid in enumerate(spine_ids):
            href = manifest.get(sid)
            if not href:
                continue
            try:
                xhtml = read_entry(href)
            except KeyError:
                continue
            body = _strip_html(xhtml)
            if not body:
                continue
            chapter_title = _first_heading(xhtml) or f"第{index + 1}章"
            chapters.append(_make_chapter(chapter_title, body))

        if not chapters:
            raise NovelImportError("EPUB 中未找到可读章节")
        if not title:
            title, _ = _metadata_from_filename(filename)
        return ParsedBook(title=title or "未命名", author=author, chapters=chapters, source_format="epub")
    finally:
        zf.close()


# ---------- DOCX (python-docx) ----------

def parse_docx(raw: bytes, *, filename: str = "") -> ParsedBook:
    try:
        from docx import Document
    except ImportError as exc:  # pragma: no cover - dependency must be present
        raise NovelImportError("缺少 python-docx 依赖，无法解析 DOCX") from exc
    try:
        doc = Document(_bytes_io(raw))
    except Exception as exc:
        raise NovelImportError("DOCX 文件无法解析") from exc

    title, author = _metadata_from_filename(filename)
    core = doc.core_properties
    if not title and core.title:
        title = core.title.strip()
    if not author and core.author:
        author = core.author.strip()

    chapters: list[ParsedChapter] = []
    current_title: str | None = None
    current_lines: list[str] = []

    def flush():
        nonlocal current_title, current_lines
        if current_title is not None and current_lines:
            chapters.append(_make_chapter(current_title, "\n".join(current_lines).strip()))
        elif current_title is None and current_lines:
            # Front-matter before any heading.
            chapters.append(_make_chapter("序", "\n".join(current_lines).strip()))
        current_title = None
        current_lines = []

    for para in doc.paragraphs:
        style = (para.style.name or "").strip()
        text = (para.text or "").strip()
        if not text:
            continue
        if style in {"Title", "Heading 1", "Heading 2", "标题 1", "标题 2"} or style.startswith("Heading"):
            flush()
            current_title = text
        else:
            current_lines.append(text)
    flush()

    if not chapters:
        raise NovelImportError("DOCX 中未找到正文内容")
    return ParsedBook(title=title or "未命名", author=author, chapters=chapters, source_format="docx")


# ---------- public entry ----------

def parse_novel(raw: bytes, *, filename: str = "") -> ParsedBook:
    fmt = detect_format(filename, raw)
    if fmt == "txt":
        book = parse_txt(raw, filename=filename)
    elif fmt == "epub":
        book = parse_epub(raw, filename=filename)
    elif fmt == "docx":
        book = parse_docx(raw, filename=filename)
    else:
        raise NovelImportError("不支持的格式")
    return _normalize(book)


# ---------- helpers ----------

def _make_chapter(title: str, content: str) -> ParsedChapter:
    content = (content or "").strip()
    if len(content) > MAX_CHAPTER_CHARS:
        content = content[:MAX_CHAPTER_CHARS]
    return ParsedChapter(title=(title or "正文")[:120], content=content, word_count=len(content))


def _normalize(book: ParsedBook) -> ParsedBook:
    if len(book.chapters) > MAX_CHAPTERS:
        book.chapters = book.chapters[:MAX_CHAPTERS]
    if not book.title:
        book.title = "未命名"
    return book


def _metadata_from_filename(filename: str) -> tuple[str, str]:
    import os
    base = os.path.basename(filename or "")
    name, _ = os.path.splitext(base)
    return (name.strip() or "未命名", "")


def _bytes_io(raw: bytes):
    import io
    return io.BytesIO(raw)
