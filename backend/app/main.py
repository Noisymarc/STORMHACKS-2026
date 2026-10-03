import logging
from pathlib import Path

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import tts
from .config import settings
from .pipeline import run_session
from .store import Store
from .translator import Translator

logging.basicConfig(level=logging.INFO)
app = FastAPI(title="StormHacks Live Translator")
store = Store(settings.database_url)
translator = Translator(settings.gemini_api_key, settings.gemini_model)


@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket, src: str = "auto", tgt: str = "en"):
    await ws.accept()

    async def receive():
        try:
            msg = await ws.receive()
        except WebSocketDisconnect:
            return None
        if msg.get("type") == "websocket.disconnect" or msg.get("text") == "stop":
            return None
        return msg.get("bytes")

    async def receive_audio():
        while True:
            data = await receive()
            if data is None or data:     # None = stop; skip non-audio frames
                return data

    try:
        await run_session(ws.send_json, receive_audio, src=src, tgt=tgt,
                          translator=translator, store=store, settings=settings)
    except WebSocketDisconnect:
        pass
    finally:
        try:
            await ws.close()
        except RuntimeError:
            pass


class Correction(BaseModel):
    segment_id: int
    translation: str


@app.post("/api/corrections")
def add_correction(c: Correction):
    if not store.add_correction(c.segment_id, c.translation.strip()):
        raise HTTPException(404, "unknown segment")
    return {"ok": True}


class TTSRequest(BaseModel):
    text: str


@app.post("/api/tts")
async def speak(req: TTSRequest):
    if not settings.elevenlabs_api_key:
        raise HTTPException(503, "ELEVENLABS_API_KEY not set")
    audio = await tts.synthesize(req.text, api_key=settings.elevenlabs_api_key,
                                 voice_id=settings.elevenlabs_voice_id,
                                 model_id=settings.elevenlabs_model)
    return Response(audio, media_type="audio/mpeg")


@app.get("/api/stats")
def stats():
    return store.stats()


app.mount("/", StaticFiles(directory=Path(__file__).resolve().parents[2] / "frontend", html=True))
