"""Keep Gemini translation working when quota is hit or a model is retired.

* 429 / RESOURCE_EXHAUSTED  -> retry with backoff (2 s, 4 s, 8 s).
* model not found / retired -> list the models this key can use, switch to the best fast one
  (stable over preview, Flash-Lite over Flash, then highest version) and carry on.
"""
import logging
import re
import threading
import time

log = logging.getLogger("gemini_resilience")

# Names containing any of these are not text-generation models we want for translation.
_NOT_TEXT = ("image", "tts", "audio", "live", "native", "embedding", "robotics", "computer",
             "imagen", "veo", "gemma", "learnlm", "aqa", "exp", "customtools", "translate")


def is_rate_limit(exc: Exception) -> bool:
    code = getattr(exc, "code", None) or getattr(exc, "status_code", None)
    text = str(exc)
    return code == 429 or "RESOURCE_EXHAUSTED" in text or "429" in text[:40]


def is_model_not_found(exc: Exception) -> bool:
    """The configured model was retired / renamed / is not available to this key."""
    if is_rate_limit(exc):
        return False
    code = getattr(exc, "code", None) or getattr(exc, "status_code", None)
    text = str(exc).lower()
    return code == 404 or "not_found" in text or "no longer available" in text \
        or "is not found" in text


def pick_model(models: list[tuple[str, list[str] | None]], exclude: set[str] = frozenset()) -> str | None:
    """Choose a fast text model from (name, supported_actions) pairs.

    Prefers stable over preview, then Flash-Lite (cheapest, highest free-tier limits), then the
    highest version number. Returns the bare id (no 'models/' prefix) or None.
    """
    best, best_key = None, None
    for name, actions in models:
        n = name.removeprefix("models/")
        if n in exclude or not n.startswith("gemini-") or "flash" not in n:
            continue
        if actions is not None and "generateContent" not in actions:
            continue
        if any(x in n for x in _NOT_TEXT):
            continue
        m = re.search(r"gemini-(\d+(?:\.\d+)?)", n)
        key = ("preview" not in n, "lite" in n, float(m.group(1)) if m else 0.0)
        if best_key is None or key > best_key:
            best, best_key = n, key
    return best


class ResilientGemini:
    """Synchronous `generate_content` wrapper (it is called through asyncio.to_thread)."""

    def __init__(self, client, model: str, max_retries: int = 3, sleep=time.sleep):
        self.client, self.model = client, model
        self.max_retries, self._sleep = max_retries, sleep
        self._dead: set[str] = set()
        self._lock = threading.Lock()
        self.note = ""          # set after an automatic model switch

    def _switch(self, failed: str) -> bool:
        with self._lock:
            if failed != self.model:         # another thread already switched
                return True
            self._dead.add(failed)
            try:
                found = [(m.name or "", list(m.supported_actions) if m.supported_actions else None)
                         for m in self.client.models.list()]
                new = pick_model(found, exclude=self._dead)
            except Exception:
                log.exception("Could not list Gemini models")
                new = None
            if not new:
                return False
            log.warning("Gemini model %s unavailable; switching to %s", failed, new)
            self.note = f"Gemini model '{failed}' is unavailable; using '{new}'. Update GEMINI_MODEL."
            self.model = new
            return True

    def generate(self, contents, **kwargs) -> str:
        switched = False
        for attempt in range(self.max_retries + 1):
            used = self.model
            try:
                response = self.client.models.generate_content(model=used, contents=contents, **kwargs)
                return (response.text or "").strip()
            except Exception as exc:
                if is_model_not_found(exc):
                    if not switched and self._switch(used):
                        switched = True
                        continue
                    raise RuntimeError(
                        f"Gemini model '{used}' is not available and no replacement was found. "
                        "Update GEMINI_MODEL in live_app.py.") from exc
                if is_rate_limit(exc) and attempt < self.max_retries:
                    delay = 2 ** (attempt + 1)
                    log.warning("Gemini rate limit, retrying in %ss", delay)
                    self._sleep(delay)
                    continue
                raise
        raise RuntimeError("unreachable")
