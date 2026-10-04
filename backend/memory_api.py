"""Local-demo endpoints connecting phrase explanations to the TiDB memory store."""

import asyncio
import logging
import os
import re
import unicodedata
import uuid
from uuid import UUID

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from .tidb import MemoryStore

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
    metadata = memory.metadata or {}
    language = next((name for name, code in LANGUAGES.items() if code == memory.target_lang), metadata.get("language"))
    return {
        # TiDB AUTO_RANDOM BIGINT values may exceed JavaScript's safe integer range.
        "id": str(memory.id), "phrase": memory.content,
        "context": memory.context, "explanation": memory.note or "",
        "language": language, "translation": metadata.get("translation", ""),
        "similarity": memory.similarity,
    }


class SaveMemory(BaseModel):
    user_id: UUID
    phrase: str = Field(min_length=1, max_length=300)
    context: str = Field(min_length=1, max_length=4000)
    explanation: str = Field(min_length=1, max_length=1600)
    language: str
    translation: str = Field(default="", max_length=300)


class SearchMemory(BaseModel):
    user_id: UUID
    transcript: str = Field(min_length=1, max_length=600)
    language: str | None = None


def language_code(language):
    if language is not None and language not in LANGUAGES:
        raise HTTPException(422, "Choose a supported glossary language.")
    return LANGUAGES.get(language)


def normalized_phrase(phrase):
    text = unicodedata.normalize("NFKC", phrase).lower()
    return " ".join(re.sub(r"[^\w]+|_", " ", text).split())


@router.get("/status")
async def status():
    return {"configured": configured() or store is not None}


@router.get("")
async def list_saved(user_id: UUID, language: str | None = None):
    code = language_code(language)
    database = await get_store()
    memories = await run_database(lambda: database.list_memories(str(user_id)))
    return {"memories": [public_memory(memory) for memory in memories if not code or memory.target_lang == code]}


@router.post("")
async def save_phrase(request: SaveMemory):
    phrase, context = request.phrase.strip(), request.context.strip()
    if not phrase or phrase not in context or not request.explanation.strip():
        raise HTTPException(422, "A phrase in its context and a nonblank explanation are required.")
    if request.language not in LANGUAGES:
        raise HTTPException(422, "Choose a supported explanation language.")
    if request.language == "Japanese" and not re.search(r"[\u3040-\u30ff\u3400-\u9fff]", request.explanation):
        raise HTTPException(422, "A Japanese glossary entry needs a Japanese explanation.")
    database = await get_store()
    metadata = {"language": request.language, "translation": request.translation.strip()}
    def save():
        # Avoid replay duplicates; simultaneous independent clients can still race.
        for memory in database.list_memories(str(request.user_id)):
            if normalized_phrase(memory.content) == normalized_phrase(phrase) and memory.target_lang == LANGUAGES[request.language]:
                if metadata["translation"] or memory.context != context or memory.note != request.explanation.strip():
                    if not metadata["translation"]:
                        metadata["translation"] = (memory.metadata or {}).get("translation", "")
                    database.update_memory(str(request.user_id), memory.id, context=context,
                                           note=request.explanation.strip(), metadata=metadata)
                return str(memory.id)
        return str(database.add_memory(
            str(request.user_id), phrase, context=context, note=request.explanation.strip(),
            source_lang="en", target_lang=LANGUAGES[request.language],
            metadata=metadata,
        ))
    return {"id": await run_database(save)}


@router.post("/search")
async def search_saved(request: SearchMemory):
    code = language_code(request.language)
    database = await get_store()
    if not request.transcript.strip():
        return {"memories": []}
    memories = await run_database(lambda: database.search_relevant_memories(
        str(request.user_id), request.transcript, limit=3, target_lang=code,
    ))
    return {"memories": [public_memory(memory) for memory in memories]}


@router.delete("/{memory_id}")
async def forget_saved(memory_id: str, user_id: UUID):
    if not re.fullmatch(r"[0-9]{1,19}", memory_id) or not 0 < int(memory_id) < 2**63:
        raise HTTPException(422, "Choose a valid glossary entry.")
    database = await get_store()
    removed = await run_database(lambda: database.forget_memory(str(user_id), int(memory_id)))
    if not removed:
        raise HTTPException(404, "This glossary entry was not found for this browser.")
    return {"forgotten": True}
