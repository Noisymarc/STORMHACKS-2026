# Live lecture translation

Our goal is real-time translation with personalized help for concepts the user
finds confusing. The current demo provides live captions and spoken explanations
on demand. Recognizing saved concepts and reading live translations aloud are
planned features.

## Repository layout

```text
backend/
  live_app.py           FastAPI server, live translation, explanations and speech
  tidb/                 Teammate's standalone memory/search module
frontend/
  live.html             Plain browser demo
scripts/
  translate_demo.py     Earlier terminal translation demo
docs/
  ARCHITECTURE.md        Architecture diagram
  design-document.md    Project design notes
tests/
  tidb/                 Existing database tests
.env.example            Safe template for local settings
requirements.txt        Demo dependencies
live_app.py             Launcher preserving the original run command
```

## Local demo: Japanese captions and spoken explanations

With the project's Python virtual environment installed, run in PowerShell:

```powershell
& ".\.venv\Scripts\python.exe" -m pip install -r requirements.txt
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
& ".\.venv\Scripts\python.exe" -m backend.live_app
```

Copy `.env.example` only on first setup, then fill `GEMINI_API_KEY` and
`ELEVENLABS_API_KEY` in your local `.env` before starting the server. Do not
overwrite an existing `.env`. The server loads it from the repository root,
regardless of its working directory. Process environment variables take priority.
Missing keys fall back to hidden prompts; ElevenLabs can be blank for captions-only use.
`.env` is ignored by Git. Never put real keys in `.env.example` or commit them.
Restart the server after changing settings. The original
`& ".\.venv\Scripts\python.exe" ".\live_app.py"` command still works.
Open http://127.0.0.1:8000.

The separate TiDB module keeps its own dependencies and setup instructions in
[backend/tidb/README.md](backend/tidb/README.md). Optional TiDB settings are included
in the root environment template; this demo does not yet call the database.

1. Start the microphone and speak in English to see live Japanese captions.
2. Stop, then select a confusing phrase in the original transcript.
3. Choose an explanation language (Japanese by default) and click **Explain and listen**.
4. Read Gemini's short explanation and hear ElevenLabs speak it. Use the audio
   controls if the browser blocks automatic playback.

Repeated requests for the same selected phrase, surrounding context and language
reuse the explanation and audio in browser memory. Starting a new microphone
session clears those results. If speech fails, the explanation text remains and
clicking again retries just the audio. There is no database integration yet.
Phrase selection is manual text selection; automatic hover highlighting is future work.

### Backend contract

- `POST /api/explain`: JSON `{ "phrase": "...", "context": "...", "language": "Japanese" }`;
  returns `{ "phrase": "...", "language": "Japanese", "explanation": "..." }`.
  The phrase must occur in the context; phrase limit is 300 characters and context limit is 4000.
- `POST /api/explanation-audio`: JSON `{ "explanation": "...", "language": "Japanese" }`;
  returns MP3 bytes with `audio/mpeg`. Explanation limit is 1600 characters.
- Explanation languages: Japanese, French, Arabic, Hindi, English. Live captions are fixed to Japanese.
- Requests happen on click, not on transcript updates. Provider quotas still apply.
- The demo remains local and has no authentication. Configure access controls before public deployment.

Local checks used simulated AI responses; actual explanation quality and ElevenLabs
playback require testing with real keys.

### Troubleshooting

Unexpected AI-service failures show a reference ID on the page. Find the same ID
in the server terminal to see the failing service, error type, status code and
code locations. Diagnostics omit provider response bodies, API keys and transcript
text. Explanation and speech requests have a 45-second server timeout; the browser
also catches network failures and has a 60-second request timeout. These timeouts
do not add a delay to live captions. Rate-limit errors are shown without automatic retries.
  
