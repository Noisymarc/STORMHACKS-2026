import asyncio
import json
import sys
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend import live_app, tts

VOICE = "JBFqnCBsd6RMkjVDRZzb"


@pytest.fixture(autouse=True)
def clear_cache():
    tts._cache.clear()


def ok(request):
    return httpx.Response(200, content=b"MP3DATA")


def run(text="hola", model="eleven_flash_v2_5", lang=None, voice=VOICE, handler=ok):
    async def go():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await tts.synthesize(text, api_key="k", voice_id=voice, model_id=model,
                                        language_code=lang, client=client)
    return asyncio.run(go())


def test_request_shape_and_language_code():
    seen = {}

    def handler(request):
        seen["url"], seen["key"] = str(request.url), request.headers["xi-api-key"]
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, content=b"MP3DATA")

    assert run("hola", lang="es", handler=handler) == b"MP3DATA"
    assert seen["url"].startswith(f"https://api.elevenlabs.io/v1/text-to-speech/{VOICE}")
    assert seen["key"] == "k"
    assert seen["body"] == {"text": "hola", "model_id": "eleven_flash_v2_5", "language_code": "es"}


def test_language_code_omitted_when_model_does_not_support_it():
    seen = {}

    def handler(request):
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, content=b"x")

    run("hola", model="eleven_multilingual_v2", lang="es", handler=handler)
    assert "language_code" not in seen["body"]


def test_results_are_cached():
    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(200, content=b"x")

    run("same", handler=handler)
    run("same", handler=handler)
    assert len(calls) == 1
    run("different", handler=handler)
    assert len(calls) == 2


@pytest.mark.parametrize("kwargs", [
    {"text": "   "}, {"text": "x" * 1001}, {"voice": "../../etc/passwd"}, {"voice": "short"}])
def test_input_validation(kwargs):
    with pytest.raises(tts.TTSError) as e:
        run(**kwargs)
    assert e.value.status == 422


@pytest.mark.parametrize("status,expected", [(401, 502), (402, 502), (429, 429), (500, 502)])
def test_upstream_errors_are_mapped(status, expected):
    def handler(request):
        return httpx.Response(status, json={"detail": {"message": "nope"}})

    with pytest.raises(tts.TTSError) as e:
        run(handler=handler)
    assert e.value.status == expected


def test_timeout_maps_to_504():
    def handler(request):
        raise httpx.ReadTimeout("slow")

    with pytest.raises(tts.TTSError) as e:
        run(handler=handler)
    assert e.value.status == 504


def test_list_voices_parses():
    def handler(request):
        assert request.url.path == "/v2/voices"
        return httpx.Response(200, json={"voices": [
            {"voice_id": "abc", "name": "Rachel", "category": "premade",
             "labels": {"gender": "female", "accent": "american", "use_case": "narration"}},
            {"voice_id": "def"}]})

    async def go():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await tts.list_voices("k", client=client)

    v = asyncio.run(go())
    assert v[0] == {"id": "abc", "name": "Rachel", "category": "premade",
                    "description": "female, american, narration"}
    assert v[1]["name"] == "def"


# ---- HTTP endpoints in live_app.py ---------------------------------------------------
@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(live_app, "elevenlabs_api_key", "k")
    monkeypatch.delenv("ELEVENLABS_VOICE_ID", raising=False)
    monkeypatch.delenv("ELEVENLABS_TTS_MODEL", raising=False)
    return TestClient(live_app.app)


def test_config_and_missing_key(client, monkeypatch):
    cfg = client.get("/api/tts/config").json()
    assert cfg == {"enabled": True, "default_voice": tts.DEFAULT_VOICE_ID, "model": tts.DEFAULT_MODEL}
    monkeypatch.setattr(live_app, "elevenlabs_api_key", None)
    assert client.get("/api/tts/config").json()["enabled"] is False
    assert client.post("/api/tts", json={"text": "hi"}).status_code == 503


def test_tts_endpoint_success_and_error(client, monkeypatch):
    captured = {}

    async def fake(text, **kw):
        captured.update(kw, text=text)
        return b"AUDIO"

    monkeypatch.setattr(live_app.tts, "synthesize", fake)
    r = client.post("/api/tts", json={"text": "hola", "voice_id": "customvoice1"})
    assert r.status_code == 200 and r.content == b"AUDIO" and r.headers["content-type"] == "audio/mpeg"
    assert captured["voice_id"] == "customvoice1" and captured["language_code"] == "ja"  # target language is Japanese
    client.post("/api/tts", json={"text": "hola"})            # falls back to the configured voice
    assert captured["voice_id"] == tts.DEFAULT_VOICE_ID

    async def boom(text, **kw):
        raise tts.TTSError(429, "slow down")

    monkeypatch.setattr(live_app.tts, "synthesize", boom)
    r = client.post("/api/tts", json={"text": "hola"})
    # upstream problems carry a reference ID that matches a server-log line (as provider_failure does)
    assert r.status_code == 429 and r.json()["detail"].startswith("slow down Reference: ")

    async def bad_input(text, **kw):
        raise tts.TTSError(422, "invalid voice id")

    monkeypatch.setattr(live_app.tts, "synthesize", bad_input)
    r = client.post("/api/tts", json={"text": "hola"})
    assert r.status_code == 422 and r.json()["detail"] == "invalid voice id"   # no reference for user errors

    async def unexpected(text, **kw):
        raise RuntimeError("secret-key-in-message")

    monkeypatch.setattr(live_app.tts, "synthesize", unexpected)
    r = client.post("/api/tts", json={"text": "hola"})
    assert r.status_code == 502 and "secret-key-in-message" not in r.text and "Reference:" in r.json()["detail"]


def test_request_validation(client):
    assert client.post("/api/tts", json={"text": ""}).status_code == 422
    assert client.post("/api/tts", json={"text": "あ" * 1001}).status_code == 422
    assert client.post("/api/tts", json={}).status_code == 422


def test_page_and_speech_script_are_served(client):
    page = client.get("/")
    assert page.status_code == 200 and '<script src="speech.js">' in page.text
    script = client.get("/speech.js")
    assert script.status_code == 200 and "javascript" in script.headers["content-type"]
    assert "SpeechQueue" in script.text


def test_existing_explanation_endpoints_are_untouched(client):
    # validation still comes from main's request models
    assert client.post("/api/explain", json={"phrase": "x", "context": "y", "language": "Japanese"}).status_code in (422, 503)
    assert client.post("/api/explanation-audio", json={"explanation": "", "language": "Japanese"}).status_code == 422


def test_voices_endpoint_falls_back_to_default_voice(client, monkeypatch):
    async def fail(key):
        raise tts.TTSError(502, "missing voices_read permission")

    monkeypatch.setattr(live_app.tts, "list_voices", fail)
    d = client.get("/api/voices").json()
    assert d["voices"][0]["id"] == tts.DEFAULT_VOICE_ID and "voices_read" in d["error"]

    async def good(key):
        return [{"id": "other12345", "name": "Other", "description": ""}]

    monkeypatch.setattr(live_app.tts, "list_voices", good)
    d = client.get("/api/voices").json()
    assert [v["id"] for v in d["voices"]] == [tts.DEFAULT_VOICE_ID, "other12345"] and d["error"] is None
