"""Persistence + the "learning" loop.

SQLAlchemy keeps this portable: the same code runs on SQLite (dev), TiDB
(mysql+pymysql://) and Tiger Data / TimescaleDB (postgresql+psycopg://).

Learning without fine-tuning: every user correction is stored, and the most
relevant ones for the language pair are replayed to Gemini as few-shot examples.
"""
import re
import time

from sqlalchemy import (Column, Float, Integer, MetaData, String, Table, Text,
                        create_engine, insert, select, update)

metadata = MetaData()

segments = Table(
    "segments", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("session_id", String(64), index=True),
    Column("ts", Float, index=True),
    Column("source_lang", String(16)),
    Column("target_lang", String(16)),
    Column("source_text", Text),
    Column("translation", Text),
    Column("model", String(64)),
    Column("latency_ms", Integer),
)

corrections = Table(
    "corrections", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("ts", Float, index=True),
    Column("source_lang", String(16), index=True),
    Column("target_lang", String(16), index=True),
    Column("source_text", Text),
    Column("bad_translation", Text),
    Column("good_translation", Text),
)

_WORD = re.compile(r"\w+", re.UNICODE)


def _tokens(text: str) -> set[str]:
    return {w.lower() for w in _WORD.findall(text)}


class Store:
    def __init__(self, url: str):
        self.engine = create_engine(url, pool_pre_ping=True)
        metadata.create_all(self.engine)

    def add_segment(self, *, session_id, source_lang, target_lang, source_text,
                    translation, model, latency_ms) -> int:
        with self.engine.begin() as c:
            res = c.execute(insert(segments).values(
                session_id=session_id, ts=time.time(), source_lang=source_lang,
                target_lang=target_lang, source_text=source_text,
                translation=translation, model=model, latency_ms=latency_ms))
            return int(res.inserted_primary_key[0])

    def add_correction(self, segment_id: int, good_translation: str) -> bool:
        with self.engine.begin() as c:
            seg = c.execute(select(segments).where(segments.c.id == segment_id)).mappings().first()
            if not seg:
                return False
            c.execute(insert(corrections).values(
                ts=time.time(), source_lang=seg["source_lang"], target_lang=seg["target_lang"],
                source_text=seg["source_text"], bad_translation=seg["translation"],
                good_translation=good_translation))
            c.execute(update(segments).where(segments.c.id == segment_id)
                      .values(translation=good_translation))
            return True

    def examples_for(self, source_lang: str, target_lang: str, text: str, limit: int) -> list[dict]:
        """Past corrections for this language pair, best keyword overlap first
        (ties broken by recency)."""
        with self.engine.connect() as c:
            rows = c.execute(
                select(corrections)
                .where(corrections.c.target_lang == target_lang)
                .order_by(corrections.c.ts.desc()).limit(200)).mappings().all()
        want = _tokens(text)
        scored = sorted(
            ((len(want & _tokens(r["source_text"])), -i, r) for i, r in enumerate(rows)),
            key=lambda t: (t[0], t[1]), reverse=True)
        return [dict(r) for score, _, r in scored[:limit] if score > 0 or len(scored) <= limit]

    def stats(self) -> dict:
        from sqlalchemy import func
        with self.engine.connect() as c:
            n_seg = c.execute(select(func.count()).select_from(segments)).scalar_one()
            n_cor = c.execute(select(func.count()).select_from(corrections)).scalar_one()
            avg = c.execute(select(func.avg(segments.c.latency_ms))).scalar()
        return {"segments": n_seg, "corrections": n_cor,
                "avg_translation_latency_ms": round(avg) if avg else None}
