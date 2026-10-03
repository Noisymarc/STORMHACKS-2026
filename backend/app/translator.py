"""Gemini translation + light cleanup (fillers, stutters, terminology)."""
import logging
import time

log = logging.getLogger("translator")

SYSTEM = (
    "You are a live-captioning translator. Translate the speech transcript from "
    "{src} into {tgt}. Remove filler words and stutters, fix obvious speech-"
    "recognition errors using the context, keep names and technical terms intact. "
    "Output ONLY the translation, no quotes or commentary."
)


def build_prompt(text: str, context: list[str], examples: list[dict]) -> str:
    parts = []
    if examples:
        parts.append("Approved corrections from earlier sessions (follow their style/terminology):")
        for e in examples:
            parts.append(f"- {e['source_text']!r} => {e['good_translation']!r}")
    if context:
        parts.append("Previous lines (context only, do not translate): " + " | ".join(context))
    parts.append(f"Transcript to translate: {text}")
    return "\n".join(parts)


class Translator:
    def __init__(self, api_key: str, model: str):
        self.model = model
        self._client = None
        if api_key:
            from google import genai
            self._client = genai.Client(api_key=api_key)

    @property
    def enabled(self) -> bool:
        return self._client is not None

    async def translate(self, text: str, src: str, tgt: str,
                        context: list[str] | None = None,
                        examples: list[dict] | None = None) -> tuple[str, int]:
        """Returns (translation, latency_ms). Empty translation on failure."""
        if not self._client:
            return "", 0
        from google.genai import types
        t0 = time.perf_counter()
        try:
            resp = await self._client.aio.models.generate_content(
                model=self.model,
                contents=build_prompt(text, context or [], examples or []),
                config=types.GenerateContentConfig(
                    system_instruction=SYSTEM.format(src=src, tgt=tgt),
                    temperature=0.2))
            out = (resp.text or "").strip()
        except Exception:
            log.exception("Gemini translation failed")
            out = ""
        return out, int((time.perf_counter() - t0) * 1000)
