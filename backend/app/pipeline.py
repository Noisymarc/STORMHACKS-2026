"""One live session: browser PCM -> WhisperLiveKit -> Gemini -> browser captions.

WhisperLiveKit sends the full list of committed `lines` plus a volatile
`buffer_transcription` on every update. A line is treated as final once WLK has
started another line (or a silence marker) after it; the last line + buffer is
shown as interim text.
"""
import asyncio
import json
import logging
import time
import uuid
from typing import Awaitable, Callable

import websockets

from .config import Settings
from .store import Store
from .translator import Translator

log = logging.getLogger("pipeline")
SILENCE = -2


class Session:
    def __init__(self, send: Callable[[dict], Awaitable[None]], *, src: str, tgt: str,
                 translator: Translator, store: Store, settings: Settings):
        self.send, self.src, self.tgt = send, src, tgt
        self.translator, self.store, self.cfg = translator, store, settings
        self.id = uuid.uuid4().hex[:12]
        self.final: list[dict] = []            # {source, translation, segment_id}
        self._tasks: dict[int, asyncio.Task] = {}
        self.live = {"source": "", "translation": ""}
        self._live_task: asyncio.Task | None = None
        self._last_live_ts = 0.0
        self._lock = asyncio.Lock()

    # ---- WLK -> state -------------------------------------------------
    async def on_wlk(self, msg: dict) -> None:
        kind = msg.get("type")
        if kind == "config":
            return
        if kind == "ready_to_stop":
            await self._finalize_all()
            return
        raw = msg.get("lines") or []
        for i, line in enumerate(raw):
            text = (line.get("text") or "").strip()
            if line.get("speaker") == SILENCE or not text:
                continue
            is_final = i < len(raw) - 1
            idx = self._index_of(i, raw)
            if is_final:
                self._commit(idx, text)
        tail = self._tail(raw, msg.get("buffer_transcription") or "")
        if tail != self.live["source"]:
            self.live["source"] = tail
            if not tail:
                self.live["translation"] = ""
            else:
                self._maybe_translate_live(tail)
        await self._push()

    @staticmethod
    def _index_of(i: int, raw: list[dict]) -> int:
        """Position of raw[i] among the non-silent lines."""
        return sum(1 for l in raw[:i] if l.get("speaker") != SILENCE and (l.get("text") or "").strip())

    @staticmethod
    def _tail(raw: list[dict], buffer: str) -> str:
        last = ""
        if raw and raw[-1].get("speaker") != SILENCE:
            last = (raw[-1].get("text") or "").strip()
        return f"{last} {buffer.strip()}".strip()

    def _commit(self, idx: int, text: str) -> None:
        if idx < len(self.final) or idx in self._tasks:
            return
        entry = {"source": text, "translation": "", "segment_id": None}
        self.final.append(entry)
        context = [e["source"] for e in self.final[max(0, idx - 3):idx]]
        self._tasks[idx] = asyncio.create_task(self._translate_final(entry, context))

    async def _finalize_all(self) -> None:
        tail = self.live["source"]
        if tail:
            self._commit(len(self.final), tail)
            self.live = {"source": "", "translation": ""}
        await asyncio.gather(*self._tasks.values(), return_exceptions=True)
        await self._push()
        await self.send({"type": "done"})

    # ---- translation ---------------------------------------------------
    async def _translate_final(self, entry: dict, context: list[str]) -> None:
        examples = await asyncio.to_thread(
            self.store.examples_for, self.src, self.tgt, entry["source"], self.cfg.max_examples)
        text, ms = await self.translator.translate(entry["source"], self.src, self.tgt, context, examples)
        entry["translation"] = text
        entry["segment_id"] = await asyncio.to_thread(
            self.store.add_segment, session_id=self.id, source_lang=self.src, target_lang=self.tgt,
            source_text=entry["source"], translation=text, model=self.translator.model, latency_ms=ms)
        await self._push()

    def _maybe_translate_live(self, tail: str) -> None:
        now = time.monotonic()
        if (self._live_task and not self._live_task.done()) or \
                now - self._last_live_ts < self.cfg.interim_interval:
            return
        self._last_live_ts = now
        self._live_task = asyncio.create_task(self._translate_live(tail))

    async def _translate_live(self, tail: str) -> None:
        context = [e["source"] for e in self.final[-3:]]
        text, _ = await self.translator.translate(tail, self.src, self.tgt, context)
        if self.live["source"] == tail:        # drop stale results
            self.live["translation"] = text
            await self._push()

    # ---- state -> browser -------------------------------------------------
    async def _push(self) -> None:
        async with self._lock:
            await self.send({"type": "update", "lines": self.final, "live": self.live})

    async def close(self) -> None:
        for t in [*self._tasks.values(), self._live_task]:
            if t and not t.done():
                t.cancel()


async def run_session(ws_send_json, ws_receive, *, src: str, tgt: str, translator: Translator,
                      store: Store, settings: Settings) -> None:
    """Pump audio browser->WLK and results WLK->browser until either side ends.

    `ws_receive()` yields bytes (PCM) or None when the browser disconnects/stops.
    """
    session = Session(ws_send_json, src=src, tgt=tgt, translator=translator, store=store, settings=settings)
    url = f"{settings.wlk_url}?language={src}"
    try:
        async with websockets.connect(url, max_size=None) as wlk:
            await ws_send_json({"type": "ready", "session_id": session.id,
                                "gemini": translator.enabled})

            async def up():
                while (chunk := await ws_receive()) is not None:
                    await wlk.send(chunk)
                await wlk.send(b"")            # end-of-audio -> WLK drains, sends ready_to_stop

            async def down():
                async for raw in wlk:
                    await session.on_wlk(json.loads(raw))
                    if isinstance(raw, str) and '"ready_to_stop"' in raw:
                        return

            up_t, down_t = asyncio.create_task(up()), asyncio.create_task(down())
            await asyncio.wait({up_t, down_t}, return_when=asyncio.FIRST_COMPLETED)
            if up_t.done() and not down_t.done():   # browser stopped: let WLK drain
                await asyncio.wait_for(down_t, timeout=20)
            up_t.cancel()
    except (OSError, websockets.WebSocketException) as e:
        await ws_send_json({"type": "error", "error": f"Cannot reach WhisperLiveKit at {settings.wlk_url}: {e}"})
    except asyncio.TimeoutError:
        await session._finalize_all()
    finally:
        await session.close()
