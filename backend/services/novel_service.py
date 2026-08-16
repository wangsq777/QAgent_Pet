from __future__ import annotations

from datetime import datetime
from .time_service import ensure_utc, utc_iso


async def get_book(db, book_id: str, *, published_only: bool = True):
    query = "SELECT * FROM novel_books WHERE book_id=?" + (" AND status='published'" if published_only else "")
    cursor = await db.execute(query, (book_id,))
    return await cursor.fetchone()


async def save_progress(db, *, user_id: str, book_id: str, chapter_id: str | None, position: int, percent: float,
                        content_version: str, client_updated_at_utc: datetime, request_id: str) -> dict:
    book = await get_book(db, book_id)
    if not book:
        raise KeyError("book not found")
    if chapter_id:
        cursor = await db.execute("SELECT chapter_id FROM novel_chapters WHERE chapter_id=? AND book_id=?", (chapter_id, book_id))
        if not await cursor.fetchone():
            raise ValueError("chapter does not belong to book")
    incoming = ensure_utc(client_updated_at_utc)
    cursor = await db.execute("SELECT * FROM novel_progress WHERE user_id=? AND book_id=?", (user_id, book_id))
    current = await cursor.fetchone()
    if current and current["request_id"] == request_id:
        return dict(current)
    if current and current["last_read_at_utc"] and ensure_utc(current["last_read_at_utc"]) > incoming:
        return dict(current)
    status = "completed" if percent >= 1 else "reading"
    await db.execute("""INSERT INTO novel_progress(user_id,book_id,last_chapter_id,position,percent,status,content_version,last_read_at_utc,updated_at_utc,request_id)
                      VALUES(?,?,?,?,?,?,?,?,?,?) ON CONFLICT(user_id,book_id) DO UPDATE SET last_chapter_id=excluded.last_chapter_id,position=excluded.position,percent=excluded.percent,status=excluded.status,content_version=excluded.content_version,last_read_at_utc=excluded.last_read_at_utc,updated_at_utc=excluded.updated_at_utc,request_id=excluded.request_id""",
                     (user_id, book_id, chapter_id, position, percent, status, content_version, utc_iso(incoming), utc_iso(), request_id))
    await db.commit()
    cursor = await db.execute("SELECT * FROM novel_progress WHERE user_id=? AND book_id=?", (user_id, book_id))
    return dict(await cursor.fetchone())
