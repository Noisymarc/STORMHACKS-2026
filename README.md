# Live Translator (StormHacks 2026)

Mic → streaming speech-to-text → Gemini translation → live captions.

```
Browser mic (AudioWorklet, 16 kHz PCM)
   │ WebSocket /ws
   ▼
FastAPI backend ──WebSocket──▶ WhisperLiveKit (/asr, --pcm-input)   STT + VAD
   │   final lines ──▶ Gemini (translate + clean up, with context + past corrections)
   │   every segment ──▶ DB (SQLite / TiDB / Tiger Data)
   ▼
Captions UI: interim text while speaking, final text per sentence
   ├─ click a line to correct it → stored → replayed to Gemini as examples
   └─ optional ElevenLabs voice reads the translation aloud
```

## Run it

```bash
pip install -r requirements.txt
pip install whisperlivekit            # STT server (see its README for GPU/CPU extras)
cp .env.example .env                  # add GEMINI_API_KEY (+ ELEVENLABS_API_KEY)

wlk --pcm-input --model base --language auto     # terminal 1, :8000
uvicorn backend.app.main:app --port 8080         # terminal 2 (run from repo root)
```

Open http://localhost:8080. Mic access needs `localhost` or HTTPS.

Tests: `pytest`

## How it "learns"

No fine-tuning needed to start. Each finalized segment is logged (`segments`:
text, translation, model, latency). When a user corrects a line, it lands in
`corrections`; for every new line, the best-matching corrections for that
language pair are injected into the Gemini prompt (`Store.examples_for`).
`GET /api/stats` shows counts and average translation latency.

## Database choice (TiDB vs Tiger Data)

Code is SQLAlchemy, so it's just `DATABASE_URL`:

| | URL | Pick it if |
|---|---|---|
| TiDB Cloud | `mysql+pymysql://…:4000/db` | you want MySQL-style OLTP + built-in analytics (TiFlash) |
| Tiger Data (Timescale) | `postgresql+psycopg://…` | you care about time-series analysis of `segments` (latency, volume over time) |

Switch by changing the env var; tables are created on startup.

## Layout

- `backend/app/pipeline.py` – session logic: WLK proxy, final/interim handling, Gemini calls
- `backend/app/translator.py` – Gemini prompt + call
- `backend/app/store.py` – DB tables, corrections → few-shot retrieval
- `backend/app/tts.py` – ElevenLabs
- `frontend/` – static UI + PCM AudioWorklet
