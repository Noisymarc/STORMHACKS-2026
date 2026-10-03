"""Personalized memory: per-user storage + semantic search on TiDB.

Search always filters by `user_id` first and then computes the exact cosine
distance for that user's rows only. A vector index is deliberately not used:
TiDB cannot use it together with a WHERE pre-filter, and "KNN first, filter
after" could drop a user's memories entirely. Per-user row counts are small,
so the exact scan is cheap and never mixes in other users' data.
"""
import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import Engine, text

from .client import engine_from_env
from .schema import MEMORIES_TABLE, init_schema

# Titan v2 cosine similarity between a short memory ("exponential growth") and a
# full transcript sentence is low in absolute terms: ~0.26 for the related
# memory vs <0.08 for unrelated ones in the demo. 0.15 sits between the two.
# Provisional; re-tune as more real memories come in.
DEFAULT_MIN_SIMILARITY = 0.15


@dataclass(frozen=True)
class Memory:
    id: int
    user_id: str
    kind: str
    content: str
    context: str | None
    note: str | None
    source_lang: str | None
    target_lang: str | None
    metadata: dict[str, Any] | None
    created_at: datetime
    # Only set on search results: 1 - cosine distance (higher is closer).
    similarity: float | None = None


_COLUMNS = ("id, user_id, kind, content, context, note, source_lang, "
            "target_lang, metadata, created_at")


def _require_user_id(user_id: str) -> None:
    if not user_id or not user_id.strip():
        raise ValueError("user_id is required")


def _to_memory(row, similarity: float | None = None) -> Memory:
    metadata = row.metadata
    if isinstance(metadata, str):
        metadata = json.loads(metadata)
    return Memory(
        id=int(row.id), user_id=row.user_id, kind=row.kind, content=row.content,
        context=row.context, note=row.note, source_lang=row.source_lang,
        target_lang=row.target_lang, metadata=metadata, created_at=row.created_at,
        similarity=similarity,
    )


class MemoryStore:
    def __init__(self, engine: Engine):
        self.engine = engine

    @classmethod
    def from_env(cls) -> "MemoryStore":
        return cls(engine_from_env())

    def init_schema(self) -> None:
        init_schema(self.engine)

    def add_memory(
        self,
        user_id: str,
        content: str,
        *,
        kind: str = "not_understood",
        context: str | None = None,
        note: str | None = None,
        source_lang: str | None = None,
        target_lang: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> int:
        """Store one memory. TiDB generates its embedding from `content`."""
        _require_user_id(user_id)
        if not content or not content.strip():
            raise ValueError("content is required")
        with self.engine.begin() as conn:
            result = conn.execute(
                text(f"""
                    INSERT INTO {MEMORIES_TABLE}
                        (user_id, kind, content, context, note,
                         source_lang, target_lang, metadata)
                    VALUES (:user_id, :kind, :content, :context, :note,
                            :source_lang, :target_lang, :metadata)
                """),
                {
                    "user_id": user_id, "kind": kind, "content": content.strip(),
                    "context": context, "note": note, "source_lang": source_lang,
                    "target_lang": target_lang,
                    "metadata": json.dumps(metadata) if metadata is not None else None,
                },
            )
            return int(result.lastrowid)

    def search_relevant_memories(
        self,
        user_id: str,
        transcript: str,
        *,
        limit: int = 5,
        min_similarity: float | None = DEFAULT_MIN_SIMILARITY,
    ) -> list[Memory]:
        """Memories of `user_id` closest in meaning to `transcript`, closest first.

        Memories below `min_similarity` are dropped; pass None to keep all.
        """
        _require_user_id(user_id)
        if not transcript or not transcript.strip():
            return []
        # The query text is embedded by TiDB with the same model as the column.
        with self.engine.connect() as conn:
            rows = conn.execute(
                text(f"""
                    SELECT {_COLUMNS},
                           VEC_EMBED_COSINE_DISTANCE(embedding, :transcript) AS distance
                    FROM {MEMORIES_TABLE}
                    WHERE user_id = :user_id AND status = 'active'
                    ORDER BY distance
                    LIMIT :limit
                """),
                {"user_id": user_id, "transcript": transcript, "limit": int(limit)},
            ).all()
        memories = [_to_memory(r, similarity=1.0 - float(r.distance)) for r in rows]
        if min_similarity is not None:
            memories = [m for m in memories if m.similarity >= min_similarity]
        return memories

    def list_memories(self, user_id: str) -> list[Memory]:
        _require_user_id(user_id)
        with self.engine.connect() as conn:
            rows = conn.execute(
                text(f"SELECT {_COLUMNS} FROM {MEMORIES_TABLE} "
                     "WHERE user_id = :user_id ORDER BY created_at"),
                {"user_id": user_id},
            ).all()
        return [_to_memory(r) for r in rows]

    def delete_user_memories(self, user_id: str) -> int:
        _require_user_id(user_id)
        with self.engine.begin() as conn:
            result = conn.execute(
                text(f"DELETE FROM {MEMORIES_TABLE} WHERE user_id = :user_id"),
                {"user_id": user_id},
            )
            return result.rowcount
