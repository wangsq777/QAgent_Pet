"""Persist user-imported novels with owner scoping.

Imported books carry ``content_source='user'`` and an ``owner_user_id`` so the
listing/read endpoints can keep them private to their owner while the built-in
books (``owner_user_id IS NULL``) stay shared with everyone.
"""
from __future__ import annotations

import uuid
from typing import Any

from .novel_import_service import ParsedBook
from .time_service import utc_iso


async def import_book(db, *, user_id: str, parsed: ParsedBook, source_filename: str = "") -> dict[str, Any]:
    """Insert an imported book and its chapters; auto-add to the owner's shelf.

    The caller owns the transaction boundary; we ``commit`` here to match the
    other leisure service functions which each commit their own writes.
    """
    now = utc_iso()
    book_id = f"user_{user_id[:8]}_{uuid.uuid4().hex[:8]}"
    await db.execute(
        """INSERT INTO novel_books(book_id,title,author,description,cover_url,content_source,content_version,status,owner_user_id,source_format,source_filename,created_at_utc,updated_at_utc)
           VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            book_id,
            parsed.title[:200],
            (parsed.author or "")[:100],
            (parsed.description or "")[:500],
            "",
            "user",
            "1.0.0",
            "published",
            user_id,
            parsed.source_format,
            (source_filename or "")[:255],
            now,
            now,
        ),
    )
    for index, chapter in enumerate(parsed.chapters):
        await db.execute(
            """INSERT INTO novel_chapters(chapter_id,book_id,chapter_index,title,content,word_count,created_at_utc,updated_at_utc)
               VALUES(?,?,?,?,?,?,?,?)""",
            (f"{book_id}.{index}", book_id, index, chapter.title, chapter.content, chapter.word_count, now, now),
        )
    # Auto-shelf so the book appears immediately in the reader.
    await db.execute(
        "INSERT INTO novel_shelves(user_id,book_id,added_at_utc,updated_at_utc) VALUES(?,?,?,?) "
        "ON CONFLICT(user_id,book_id) DO UPDATE SET updated_at_utc=excluded.updated_at_utc",
        (user_id, book_id, now, now),
    )
    await db.commit()
    return {
        "book_id": book_id,
        "title": parsed.title,
        "author": parsed.author,
        "chapter_count": len(parsed.chapters),
        "source_format": parsed.source_format,
        "source_filename": source_filename,
        "owner_user_id": user_id,
        "content_source": "user",
    }


async def list_user_books(db, user_id: str) -> list[dict[str, Any]]:
    cursor = await db.execute(
        "SELECT * FROM novel_books WHERE owner_user_id=? AND status='published' ORDER BY created_at_utc DESC",
        (user_id,),
    )
    return [dict(row) for row in await cursor.fetchall()]


async def get_owned_book(db, user_id: str, book_id: str) -> dict[str, Any] | None:
    """Return the book only if it is published and owned by (or shared with) the user."""
    cursor = await db.execute(
        "SELECT * FROM novel_books WHERE book_id=? AND status='published' "
        "AND (owner_user_id IS NULL OR owner_user_id=?)",
        (book_id, user_id),
    )
    row = await cursor.fetchone()
    return dict(row) if row else None


async def delete_user_book(db, user_id: str, book_id: str) -> bool:
    """Soft-delete an imported book owned by the user. Built-in books cannot be deleted."""
    cursor = await db.execute(
        "SELECT content_source, owner_user_id FROM novel_books WHERE book_id=?",
        (book_id,),
    )
    row = await cursor.fetchone()
    if not row:
        raise KeyError("book not found")
    if row["content_source"] != "user" or row["owner_user_id"] != user_id:
        raise PermissionError("cannot delete this book")
    now = utc_iso()
    await db.execute("UPDATE novel_books SET status='hidden', updated_at_utc=? WHERE book_id=?", (now, book_id))
    await db.execute("DELETE FROM novel_chapters WHERE book_id=?", (book_id,))
    await db.execute("DELETE FROM novel_progress WHERE book_id=?", (book_id,))
    await db.execute("DELETE FROM novel_shelves WHERE book_id=?", (book_id,))
    await db.commit()
    return True
