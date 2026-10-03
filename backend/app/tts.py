"""ElevenLabs text-to-speech: speak the translation aloud."""
import httpx


async def synthesize(text: str, *, api_key: str, voice_id: str, model_id: str) -> bytes:
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.post(
            f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}",
            params={"output_format": "mp3_44100_64"},
            headers={"xi-api-key": api_key, "accept": "audio/mpeg"},
            json={"text": text, "model_id": model_id})
        r.raise_for_status()
        return r.content
