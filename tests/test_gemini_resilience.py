import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

from backend import live_app
from backend.gemini_resilience import ResilientGemini, is_model_not_found, is_rate_limit, pick_model


class Err429(Exception):
    code = 429


class Err404(Exception):
    code = 404


MODELS = [
    ("models/gemini-3.1-flash-lite", ["generateContent"]),
    ("models/gemini-3.6-flash", ["generateContent"]),
    ("models/gemini-3.6-flash-preview-0901", ["generateContent"]),
    ("models/gemini-3.1-flash-image", ["generateContent"]),
    ("models/gemini-3.5-live-translate-preview", ["bidiGenerateContent"]),
    ("models/gemini-2.5-flash-lite", ["generateContent"]),
    ("models/gemini-3.6-pro", ["generateContent"]),
    ("models/gemini-embedding-001", ["embedContent"]),
    ("models/gemma-3-27b", ["generateContent"]),
]


class FakeClient:
    """Stands in for genai.Client: `outcomes(model)` returns text or raises."""

    def __init__(self, outcomes, models=MODELS):
        self.calls, self._outcomes, self._models = [], outcomes, models
        self.models = SimpleNamespace(generate_content=self._gen, list=self._list)

    def _gen(self, model, contents, **kw):
        self.calls.append(model)
        out = self._outcomes(model)
        if isinstance(out, Exception):
            raise out
        return SimpleNamespace(text=out)

    def _list(self):
        return [SimpleNamespace(name=n, supported_actions=a) for n, a in self._models]


def test_pick_model():
    assert pick_model(MODELS) == "gemini-3.1-flash-lite"
    assert pick_model(MODELS, exclude={"gemini-3.1-flash-lite"}) == "gemini-2.5-flash-lite"
    assert pick_model([m for m in MODELS if "lite" not in m[0]]) == "gemini-3.6-flash"  # stable > preview
    assert pick_model([("models/gemini-3.6-flash-preview-0901", ["generateContent"])]) \
        == "gemini-3.6-flash-preview-0901"
    assert pick_model([("models/gemini-3.6-pro", ["generateContent"])]) is None
    assert pick_model([]) is None


def test_error_classification():
    assert is_rate_limit(Err429()) and is_rate_limit(Exception("429 RESOURCE_EXHAUSTED"))
    assert is_model_not_found(Err404()) and is_model_not_found(Exception("model is no longer available"))
    assert not is_model_not_found(Err429()) and not is_model_not_found(ValueError("boom"))


def test_retries_rate_limit_then_succeeds():
    sleeps, state = [], {"n": 0}

    def outcomes(model):
        state["n"] += 1
        return Err429() if state["n"] < 3 else " hola "

    g = ResilientGemini(FakeClient(outcomes), "gemini-3.1-flash-lite", sleep=sleeps.append)
    assert g.generate("hi") == "hola" and sleeps == [2, 4]


def test_gives_up_after_max_retries():
    sleeps = []
    g = ResilientGemini(FakeClient(lambda m: Err429()), "m", max_retries=3, sleep=sleeps.append)
    with pytest.raises(Err429):
        g.generate("hi")
    assert sleeps == [2, 4, 8] and len(g.client.calls) == 4


def test_other_errors_are_raised_immediately():
    g = ResilientGemini(FakeClient(lambda m: ValueError("bad request")), "m", sleep=lambda s: None)
    with pytest.raises(ValueError):
        g.generate("hi")
    assert len(g.client.calls) == 1


def retired_client(models=MODELS):
    return FakeClient(lambda m: Err404("404 NOT_FOUND") if m == "gemini-2.5-flash" else f"ok:{m}", models)


def test_switches_model_when_configured_one_is_retired():
    g = ResilientGemini(retired_client(), "gemini-2.5-flash")
    assert g.generate("hi") == "ok:gemini-3.1-flash-lite"
    assert g.client.calls == ["gemini-2.5-flash", "gemini-3.1-flash-lite"]
    assert "Update GEMINI_MODEL" in g.note
    assert g.generate("again") == "ok:gemini-3.1-flash-lite"          # stays on the new model
    assert g.client.calls[-1] == "gemini-3.1-flash-lite"


def test_no_replacement_gives_clear_error():
    g = ResilientGemini(retired_client([("models/gemma-3-27b", ["generateContent"])]), "gemini-2.5-flash")
    with pytest.raises(RuntimeError, match="no replacement was found"):
        g.generate("hi")


def test_live_app_translate_uses_the_resilient_wrapper(monkeypatch):
    client = retired_client()
    monkeypatch.setattr(live_app, "gemini_client", client)
    monkeypatch.setattr(live_app, "gemini_resilient", None)
    assert live_app._translate("hello") == "ok:gemini-3.1-flash-lite"
