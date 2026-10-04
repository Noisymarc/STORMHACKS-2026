"""ElevenLabs text-to-speech: speak the translated captions aloud.

Short phrases are synthesized in one request (flash models answer in a fraction of a second).
Results are cached in memory so repeating a phrase doesn't spend credits twice, and ElevenLabs
failures are turned into `TTSError(status, message)` so the page can show a useful message.
"""
import re
from collections import OrderedDict

import httpx

API = "https://api.elevenlabs.io"
DEFAULT_VOICE_ID = "JBFqnCBsd6RMkjVDRZzb"      # George, the voice translate_demo.py uses
DEFAULT_MODEL = "eleven_flash_v2_5"            # low latency; honours language_code
MAX_TEXT = 1000
VOICE_ID_RE = re.compile(r"^[A-Za-z0-9]{10,40}$")     # voice_id goes into a URL path
LANG_RE = re.compile(r"^[a-z]{2,3}$")

_cache: OrderedDict[tuple, bytes] = OrderedDict()
_CACHE_MAX = 64


class TTSError(Exception):
    """Raised with an HTTP status to return to the browser and a human-readable message."""

    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status, self.message = status, message


def _upstream_error(r: httpx.Response) -> TTSError:
    detail = ""
    try:
        d = r.json().get("detail")
        detail = d.get("message", "") if isinstance(d, dict) else str(d or "")
    except Exception:
        pass
    if r.status_code in (401, 403):
        return TTSError(502, f"ElevenLabs rejected the API key or its permissions. {detail}".strip())
    if r.status_code == 402:
        return TTSError(502, "ElevenLabs: out of credits or plan doesn't allow this. " + detail)
    if r.status_code == 429:
        return TTSError(429, "ElevenLabs is rate limiting (too many requests/concurrent audio).")
    return TTSError(502, f"ElevenLabs error {r.status_code}. {detail}".strip())


def supports_language_code(model_id: str) -> bool:
    """language_code is only honoured by the v2.5 / v3 families."""
    return "v2_5" in model_id or "v3" in model_id


async def synthesize(text: str, *, api_key: str, voice_id: str, model_id: str,
                     language_code: str | None = None,
                     client: httpx.AsyncClient | None = None) -> bytes:
    text = text.strip()
    if not text:
        raise TTSError(422, "empty text")
    if len(text) > MAX_TEXT:
        raise TTSError(422, f"text too long (max {MAX_TEXT} characters)")
    if not VOICE_ID_RE.match(voice_id):
        raise TTSError(422, "invalid voice id")
    lang = language_code if language_code and LANG_RE.match(language_code) else None
    if lang and not supports_language_code(model_id):
        lang = None

    key = (text, voice_id, model_id, lang)
    if key in _cache:
        _cache.move_to_end(key)
        return _cache[key]

    body = {"text": text, "model_id": model_id}
    if lang:
        body["language_code"] = lang
    own = client is None
    client = client or httpx.AsyncClient(timeout=30)
    try:
        r = await client.post(
            f"{API}/v1/text-to-speech/{voice_id}",
            params={"output_format": "mp3_44100_64"},
            headers={"xi-api-key": api_key, "accept": "audio/mpeg"}, json=body)
    except httpx.TimeoutException:
        raise TTSError(504, "ElevenLabs text-to-speech timed out")
    except httpx.HTTPError as e:
        raise TTSError(502, f"Could not reach ElevenLabs: {e}")
    finally:
        if own:
            await client.aclose()
    if r.status_code != 200:
        raise _upstream_error(r)

    _cache[key] = r.content
    if len(_cache) > _CACHE_MAX:
        _cache.popitem(last=False)
    return r.content


async def list_voices(api_key: str, client: httpx.AsyncClient | None = None) -> list[dict]:
    """Voices available to this key. Needs the 'voices read' permission on restricted keys."""
    own = client is None
    client = client or httpx.AsyncClient(timeout=15)
    try:
        r = await client.get(f"{API}/v2/voices", params={"page_size": 100},
                             headers={"xi-api-key": api_key})
    except httpx.HTTPError as e:
        raise TTSError(502, f"Could not reach ElevenLabs: {e}")
    finally:
        if own:
            await client.aclose()
    if r.status_code != 200:
        raise _upstream_error(r)
    out = []
    for v in r.json().get("voices", []):
        labels = v.get("labels") or {}
        out.append({"id": v["voice_id"], "name": v.get("name") or v["voice_id"],
                    "category": v.get("category"),
                    "description": ", ".join(x for x in (labels.get("gender"), labels.get("accent"),
                                                         labels.get("use_case")) if x)})
    return out
