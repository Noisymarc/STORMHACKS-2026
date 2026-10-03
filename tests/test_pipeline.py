import asyncio
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.app.config import Settings
from backend.app.pipeline import Session
from backend.app.store import Store
from backend.app.translator import Translator, build_prompt


class FakeTranslator(Translator):
    model = "fake"
    enabled = True

    def __init__(self):
        self.calls = []

    async def translate(self, text, src, tgt, context=None, examples=None):
        self.calls.append((text, examples))
        return f"<{text}>", 5


def make(tmp_path):
    sent = []

    async def send(m):
        sent.append(m)

    store = Store(f"sqlite:///{tmp_path/'t.db'}")
    tr = FakeTranslator()
    s = Session(send, src="en", tgt="es", translator=tr, store=store,
                settings=Settings(interim_interval=0))
    return s, sent, store, tr


def wlk(lines, buf=""):
    return {"status": "active_transcription", "buffer_transcription": buf,
            "lines": [{"speaker": 1, "text": t} for t in lines]}


@pytest.mark.asyncio
async def test_lines_finalize_only_after_next_line_starts(tmp_path):
    s, sent, store, _ = make(tmp_path)
    await s.on_wlk(wlk(["hello there"], buf="how"))
    assert s.final == [] and s.live["source"] == "hello there how"
    await s.on_wlk(wlk(["hello there", "second"]))
    await asyncio.gather(*s._tasks.values())
    assert [e["source"] for e in s.final] == ["hello there"]
    assert s.final[0]["translation"] == "<hello there>" and s.final[0]["segment_id"]
    # re-sent snapshot must not re-translate
    await s.on_wlk(wlk(["hello there", "second"]))
    assert len(s._tasks) == 1
    assert store.stats()["segments"] == 1


@pytest.mark.asyncio
async def test_ready_to_stop_flushes_tail(tmp_path):
    s, sent, *_ = make(tmp_path)
    await s.on_wlk(wlk(["only line"]))
    await s.on_wlk({"type": "ready_to_stop"})
    assert s.final[0]["translation"] == "<only line>"
    assert sent[-1] == {"type": "done"}


@pytest.mark.asyncio
async def test_correction_is_replayed_as_example(tmp_path):
    s, _, store, tr = make(tmp_path)
    await s.on_wlk(wlk(["the tidb cluster", "x"]))
    await asyncio.gather(*s._tasks.values())
    assert store.add_correction(s.final[0]["segment_id"], "el clúster de TiDB")
    ex = store.examples_for("en", "es", "restart the tidb cluster", 3)
    assert ex and ex[0]["good_translation"] == "el clúster de TiDB"
    assert "el clúster de TiDB" in build_prompt("restart the tidb cluster", [], ex)
