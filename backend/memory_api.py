"""Local-demo endpoints connecting phrase explanations to the TiDB memory store."""

import asyncio
import logging
import os
import uuid
from datetime import date
from uuid import UUID

from fastapi import APIRouter, HTTPException
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field

from .tidb import MemoryStore, dictionary

router = APIRouter(prefix="/api/memories")
store = None
store_lock = asyncio.Lock()
logger = logging.getLogger("uvicorn.error")
LANGUAGES = {"Japanese": "ja", "French": "fr", "Arabic": "ar", "Hindi": "hi", "English": "en"}


def configured():
    return all(os.getenv(key, "").strip() for key in ("TIDB_HOST", "TIDB_USER", "TIDB_PASSWORD"))


async def run_database(operation):
    try:
        return await asyncio.wait_for(asyncio.to_thread(operation), timeout=20)
    except Exception as exc:
        reference = uuid.uuid4().hex[:8]
        logger.error("[%s] TiDB failed: %s", reference, type(exc).__name__)
        raise HTTPException(503, f"Saved help is unavailable. Live captions still work. Reference: {reference}") from exc


async def get_store():
    global store
    if store is not None:
        return store
    if not configured():
        raise HTTPException(503, "Add TIDB_HOST, TIDB_USER and TIDB_PASSWORD to .env and restart to enable saved help.")
    async with store_lock:
        if store is None:
            def initialize():
                candidate = MemoryStore.from_env()
                try:
                    candidate.init_schema()
                except Exception:
                    candidate.engine.dispose()
                    raise
                return candidate
            store = await run_database(initialize)
    return store


def public_memory(memory):
    return {
        # TiDB AUTO_RANDOM BIGINT values may exceed JavaScript's safe integer range.
        "id": str(memory.id), "phrase": memory.content,
        "context": memory.context, "explanation": memory.note or "",
        "language": (memory.metadata or {}).get("language", memory.target_lang),
        "similarity": memory.similarity,
    }


class SaveMemory(BaseModel):
    user_id: UUID
    phrase: str = Field(min_length=1, max_length=300)
    context: str = Field(min_length=1, max_length=4000)
    explanation: str = Field(min_length=1, max_length=1600)
    language: str


# Browser imports run inside run_database()'s 20-second limit, so they are capped; bigger files
# go through the command line (python -m backend.tidb.dictionary import FILE), which has no limit.
MAX_IMPORT_ENTRIES = 200
MAX_IMPORT_CHARS = 1_000_000


class ImportDictionary(BaseModel):
    user_id: UUID
    text: str = Field(min_length=1, max_length=MAX_IMPORT_CHARS)


class SearchMemory(BaseModel):
    user_id: UUID
    transcript: str = Field(min_length=1, max_length=600)


@router.get("/status")
async def status():
    return {"configured": configured() or store is not None}


@router.get("")
async def list_saved(user_id: UUID):
    database = await get_store()
    memories = await run_database(lambda: database.list_memories(str(user_id)))
    return {"memories": [public_memory(memory) for memory in memories]}


@router.post("")
async def save_phrase(request: SaveMemory):
    phrase, context = request.phrase.strip(), request.context.strip()
    if not phrase or phrase not in context or not request.explanation.strip():
        raise HTTPException(422, "A phrase in its context and a nonblank explanation are required.")
    if request.language not in LANGUAGES:
        raise HTTPException(422, "Choose a supported explanation language.")
    database = await get_store()
    def save():
        # Avoid replay duplicates; simultaneous independent clients can still race.
        for memory in database.list_memories(str(request.user_id)):
            if (memory.content, memory.context, memory.target_lang) == (phrase, context, LANGUAGES[request.language]):
                return str(memory.id)
        return str(database.add_memory(
            str(request.user_id), phrase, context=context, note=request.explanation.strip(),
            source_lang="en", target_lang=LANGUAGES[request.language],
            metadata={"language": request.language},
        ))
    return {"id": await run_database(save)}


@router.get("/export")
async def export_dictionary(user_id: UUID):
    """The user's saved phrases as a plain text file that /import (or the command line) can read."""
    database = await get_store()
    content = await run_database(lambda: dictionary.export_dictionary(database, str(user_id)))
    return PlainTextResponse(content, media_type="text/plain; charset=utf-8", headers={
        "Content-Disposition": f'attachment; filename="dictionary-{date.today().isoformat()}.txt"',
        "Cache-Control": "no-store",
    })


@router.post("/import")
async def import_dictionary(request: ImportDictionary):
    """Add the phrases in a dictionary file to this user. Already-saved phrases are skipped."""
    parsed = dictionary.parse_dictionary(request.text)
    if parsed.fatal or parsed.errors:
        shown = "; ".join(parsed.errors[:5]) + (f" (+{len(parsed.errors) - 5} more)" if len(parsed.errors) > 5 else "")
        raise HTTPException(422, f"Nothing was imported. The file has problems: {shown}")
    if len(parsed.entries) > MAX_IMPORT_ENTRIES:
        raise HTTPException(422, f"The file has {len(parsed.entries)} phrases; the browser imports up to "
                                 f"{MAX_IMPORT_ENTRIES}. Use: python -m backend.tidb.dictionary import FILE --user-id {request.user_id}")
    database = await get_store()
    result = await run_database(lambda: dictionary.import_entries(
        database, parsed.entries, user_id=str(request.user_id)))
    return {"added": result.added, "skipped_duplicates": result.skipped_duplicates}


@router.post("/search")
async def search_saved(request: SearchMemory):
    database = await get_store()
    if not request.transcript.strip():
        return {"memories": []}
    memories = await run_database(lambda: database.search_relevant_memories(
        str(request.user_id), request.transcript, limit=3,
    ))
    return {"memories": [public_memory(memory) for memory in memories]}
