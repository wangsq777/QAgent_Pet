"""User-visible, scoped memory management; every endpoint resolves session ownership."""
from typing import Optional
from fastapi import APIRouter, Request, HTTPException, Query
from backend.schemas import MemoryEditRequest
from backend.services.memory_store import memory_store
from backend.services.memory_worker import memory_worker

router = APIRouter(prefix='/api/sessions', tags=['memories'])


async def owned(session_id, request):
    try:
        return await memory_store.identity(session_id,request.state.user_id)
    except PermissionError:
        raise HTTPException(404,'Session not found')


@router.get('/{session_id}/memories')
async def memories(session_id: str, request: Request, before: Optional[int] = Query(None,ge=1),
                   limit: int = Query(50,ge=1,le=100), history: bool = False):
    return await memory_store.list(await owned(session_id,request),before=before,limit=limit,history=history)


@router.get('/{session_id}/memories/{memory_id}')
async def detail(session_id: str, memory_id: str, request: Request):
    try:
        item = await memory_store.get(await owned(session_id,request),memory_id)
        if item['status']=='forgotten':
            raise KeyError(memory_id)
        return item
    except KeyError:
        raise HTTPException(404,'Memory not found')


@router.patch('/{session_id}/memories/{memory_id}')
async def edit(session_id: str, memory_id: str, body: MemoryEditRequest, request: Request):
    changes = body.model_dump(exclude_unset=True)
    if not changes or any(value is None for value in changes.values()):
        raise HTTPException(422,'Provide non-null changes')
    try:
        mid = await memory_store.edit(await owned(session_id,request),memory_id,changes)
        if mid is None:
            raise ValueError('This value is suppressed by a previous forget operation')
        memory_worker.notify()
        return {'memory_id':mid}
    except KeyError:
        raise HTTPException(404,'Memory not found')
    except ValueError as exc:
        raise HTTPException(422,str(exc))
    except Exception as exc:
        if 'UNIQUE constraint' in str(exc):
            raise HTTPException(409,'An equivalent memory already exists in the target scope')
        raise


@router.delete('/{session_id}/memories/{memory_id}')
async def forget(session_id: str, memory_id: str, request: Request):
    try:
        await memory_store.forget(await owned(session_id,request),memory_id)
        return {'ok':True}
    except KeyError:
        raise HTTPException(404,'Memory not found')
