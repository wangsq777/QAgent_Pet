from fastapi import APIRouter, HTTPException, Request
from backend.database import get_db
from backend.schemas import LeisureSessionCreateRequest, LeisureSettingsRequest, NovelProgressRequest
from backend.services.leisure_session_service import close_session, open_session, pause_session, resume_session
from backend.services.module_registry import get_module, list_modules
from backend.services.novel_service import get_book, save_progress
from backend.services.time_service import utc_iso

router = APIRouter(prefix="/api/leisure", tags=["leisure"])


@router.get("/modules")
async def modules():
    return {"modules": list_modules()}


@router.get("/modules/{module_id}")
async def module(module_id: str):
    value = get_module(module_id)
    if not value:
        raise HTTPException(status_code=404, detail="Module not found")
    return value


@router.post("/sessions")
async def create_session(body: LeisureSessionCreateRequest, request: Request):
    async with get_db() as db:
        try:
            return await open_session(db, user_id=request.state.user_id, module_id=body.module_id, content_ref_id=body.content_ref_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))


@router.get("/sessions/active")
async def active_session(request: Request):
    async with get_db() as db:
        cursor = await db.execute("SELECT * FROM leisure_sessions WHERE user_id=? AND status IN ('active','paused','crashed') ORDER BY updated_at_utc DESC LIMIT 1", (request.state.user_id,))
        row = await cursor.fetchone()
        return {"session": dict(row) if row else None}


async def _session_action(session_id: str, request: Request, operation):
    async with get_db() as db:
        try:
            return await operation(db, user_id=request.state.user_id, session_id=session_id)
        except KeyError:
            raise HTTPException(status_code=404, detail="Session not found")
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc))


@router.post("/sessions/{session_id}/pause")
async def pause(session_id: str, request: Request):
    return await _session_action(session_id, request, pause_session)


@router.post("/sessions/{session_id}/resume")
async def resume(session_id: str, request: Request):
    return await _session_action(session_id, request, resume_session)


@router.post("/sessions/{session_id}/close")
async def close(session_id: str, request: Request, reason: str = "user_exit"):
    return await _session_action(session_id, request, lambda db, **kwargs: close_session(db, reason=reason, **kwargs))


@router.get("/novels")
async def novels():
    async with get_db() as db:
        cursor = await db.execute("SELECT * FROM novel_books WHERE status='published' ORDER BY title")
        return {"books": [dict(row) for row in await cursor.fetchall()]}


@router.get("/novels/{book_id}")
async def novel(book_id: str):
    async with get_db() as db:
        row = await get_book(db, book_id)
        if not row:
            raise HTTPException(status_code=404, detail="Book not found")
        return dict(row)


@router.get("/novels/{book_id}/chapters")
async def chapters(book_id: str):
    async with get_db() as db:
        if not await get_book(db, book_id):
            raise HTTPException(status_code=404, detail="Book not found")
        cursor = await db.execute("SELECT chapter_id,book_id,chapter_index,title,word_count,created_at_utc,updated_at_utc FROM novel_chapters WHERE book_id=? ORDER BY chapter_index", (book_id,))
        return {"chapters": [dict(row) for row in await cursor.fetchall()]}


@router.get("/novels/{book_id}/chapters/{chapter_id}")
async def chapter(book_id: str, chapter_id: str):
    async with get_db() as db:
        if not await get_book(db, book_id):
            raise HTTPException(status_code=404, detail="Book not found")
        cursor = await db.execute("SELECT * FROM novel_chapters WHERE book_id=? AND chapter_id=?", (book_id, chapter_id))
        row = await cursor.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Chapter not found")
        return dict(row)


@router.get("/novels/{book_id}/progress")
async def progress(book_id: str, request: Request):
    async with get_db() as db:
        if not await get_book(db, book_id):
            raise HTTPException(status_code=404, detail="Book not found")
        cursor = await db.execute("SELECT * FROM novel_progress WHERE user_id=? AND book_id=?", (request.state.user_id, book_id))
        row = await cursor.fetchone()
        return {"progress": dict(row) if row else None}


@router.put("/novels/{book_id}/progress")
async def update_progress(book_id: str, body: NovelProgressRequest, request: Request):
    async with get_db() as db:
        try:
            return await save_progress(db, user_id=request.state.user_id, book_id=book_id, chapter_id=body.chapter_id, position=body.position, percent=body.percent, content_version=body.content_version, client_updated_at_utc=body.client_updated_at_utc, request_id=body.request_id)
        except KeyError:
            raise HTTPException(status_code=404, detail="Book not found")
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc))


@router.post("/novels/{book_id}/shelf")
async def shelf_add(book_id: str, request: Request):
    async with get_db() as db:
        if not await get_book(db, book_id):
            raise HTTPException(status_code=404, detail="Book not found")
        await db.execute("INSERT INTO novel_shelves(user_id,book_id,added_at_utc,updated_at_utc) VALUES(?,?,?,?) ON CONFLICT(user_id,book_id) DO UPDATE SET updated_at_utc=excluded.updated_at_utc", (request.state.user_id, book_id, utc_iso(), utc_iso()))
        await db.commit()
        return {"ok": True}


@router.delete("/novels/{book_id}/shelf")
async def shelf_remove(book_id: str, request: Request):
    async with get_db() as db:
        await db.execute("DELETE FROM novel_shelves WHERE user_id=? AND book_id=?", (request.state.user_id, book_id))
        await db.commit()
        return {"ok": True}


@router.get("/settings")
async def leisure_settings(request: Request):
    async with get_db() as db:
        cursor = await db.execute("SELECT * FROM leisure_settings WHERE user_id=?", (request.state.user_id,))
        row = await cursor.fetchone()
        if not row:
            await db.execute("INSERT INTO leisure_settings(user_id,updated_at_utc) VALUES(?,?)", (request.state.user_id, utc_iso()))
            await db.commit()
            cursor = await db.execute("SELECT * FROM leisure_settings WHERE user_id=?", (request.state.user_id,))
            row = await cursor.fetchone()
        return dict(row)


@router.put("/settings")
async def update_leisure_settings(body: LeisureSettingsRequest, request: Request):
    async with get_db() as db:
        await db.execute("INSERT INTO leisure_settings(user_id,pet_interaction_enabled,interaction_frequency,save_progress_enabled,privacy_level,updated_at_utc) VALUES(?,?,?,?,?,?) ON CONFLICT(user_id) DO UPDATE SET pet_interaction_enabled=excluded.pet_interaction_enabled,interaction_frequency=excluded.interaction_frequency,save_progress_enabled=excluded.save_progress_enabled,privacy_level=excluded.privacy_level,updated_at_utc=excluded.updated_at_utc", (request.state.user_id, int(body.pet_interaction_enabled), body.interaction_frequency, int(body.save_progress_enabled), body.privacy_level, utc_iso()))
        await db.commit()
        cursor = await db.execute("SELECT * FROM leisure_settings WHERE user_id=?", (request.state.user_id,))
        return dict(await cursor.fetchone())
