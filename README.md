# Live lecture translation

Our goal is real-time translation with personalized help for concepts the user
finds confusing. The current demo provides live captions, optional spoken
translation of those captions, and spoken explanations on demand. Recognizing
saved concepts is a planned feature.

## Repository layout

```text
backend/
  live_app.py           FastAPI server, live translation, explanations and speech
  tts.py                ElevenLabs text-to-speech for spoken live translation
  gemini_resilience.py  429 retries and recovery when a Gemini model is retired
  tidb/                 Teammate's standalone memory/search module
frontend/
  live.html             Plain browser demo
  speech.js             Sentence splitting, echo guard and playback queue for spoken translation
scripts/
  translate_demo.py     Earlier terminal translation demo
docs/
  ARCHITECTURE.md        Architecture diagram
  design-document.md    Project design notes
tests/
  tidb/                 Existing database tests
  test_tts.py, test_gemini_resilience.py   Python tests (mocked services, no keys needed)
  js/speech.test.js     Node tests for frontend/speech.js (run by test_speech_js.py)
.env.example            Safe template for local settings
requirements.txt        Demo dependencies
live_app.py             Launcher preserving the original run command
```

## Local demo: Japanese captions and spoken explanations

This demo runs on your own computer. You need Git, Python 3.10 or newer,
a microphone, and a Gemini API key with access to the configured models.
An ElevenLabs API key is needed for spoken explanations. These are API keys,
not ChatGPT or other chat subscriptions. The steps below use Windows PowerShell.

### 1. Get the code

For a first-time setup:

```powershell
git clone https://github.com/Noisymarc/STORMHACKS-2026.git
cd STORMHACKS-2026
```

If you already have the repository, open PowerShell in its folder and update it:

```powershell
git switch main
git pull origin main
```

### 2. Install the libraries

On first setup, create a virtual environment (a folder for this project's Python libraries):

```powershell
python -m venv .venv
```

Then install or update the libraries:

```powershell
& ".\.venv\Scripts\python.exe" -m pip install -r requirements.txt
```

### 3. Add your API keys

Create your settings file only if it does not already exist:

```powershell
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
```

Open `.env` in your editor and replace the empty values with your own keys:

```dotenv
GEMINI_API_KEY=your_gemini_key
ELEVENLABS_API_KEY=your_elevenlabs_key
```

Save the file before starting the server. Do not overwrite an existing `.env`.
The server loads it from the repository root,
regardless of its working directory. Process environment variables take priority.
Missing keys fall back to hidden prompts; ElevenLabs can be blank for captions-only use.
`.env` is ignored by Git. Never put real keys in `.env.example` or commit them.

### 4. Start the website

```powershell
& ".\.venv\Scripts\python.exe" -m backend.live_app
```

Keep the terminal open and visit [http://127.0.0.1:8000](http://127.0.0.1:8000)
in Chrome or Edge. This address opens the app on your computer.
Press Ctrl+C in the terminal to stop the server. Restart it after changing settings.
The original
`& ".\.venv\Scripts\python.exe" ".\live_app.py"` command still works.

The separate TiDB module keeps its own dependencies and setup instructions in
[backend/tidb/README.md](backend/tidb/README.md). Optional TiDB settings are included
in the root environment template; this demo does not yet call the database.

### 5. Try the feature

1. Click **Start microphone**, allow microphone access, and speak in English.
   The original transcript stays in English; translated captions appear in Japanese.
2. Click **Stop** and wait until the page says **Microphone is off**.
   Then select a confusing phrase in the original transcript. Selection while listening is disabled.
3. Choose an explanation language (Japanese by default) and click **Explain and listen**.
4. Read Gemini's short explanation and hear ElevenLabs speak it. Use the audio
   controls if the browser blocks automatic playback.

Repeated requests for the same selected phrase, surrounding context and language
reuse the explanation and audio in browser memory. Starting a new microphone
session clears those results. If speech fails, the explanation text remains and
clicking again retries just the audio. There is no database integration yet.
Phrase selection is manual text selection; automatic hover highlighting is future work.

## Technologies in plain language

- **HTML and JavaScript:** display the page, capture microphone audio, and play explanations.
- **Python, FastAPI and Uvicorn:** run the local server and coordinate requests to the AI services.
- **WebSockets:** keep the live audio/caption connection open so updates can arrive while you speak.
- **Gemini:** translates live microphone audio and generates explanations when you click Explain.
- **ElevenLabs:** reads the selected phrase's explanation aloud, and (optionally) reads the live Japanese captions aloud.
- **TiDB:** stores and searches saved concepts in a separate module. It is not yet connected to the website.

### Backend contract (for frontend integration)

- `POST /api/explain`: JSON `{ "phrase": "...", "context": "...", "language": "Japanese" }`;
  returns `{ "phrase": "...", "language": "Japanese", "explanation": "..." }`.
  The phrase must occur in the context; phrase limit is 300 characters and context limit is 4000.
- `POST /api/explanation-audio`: JSON `{ "explanation": "...", "language": "Japanese" }`;
  returns MP3 bytes with `audio/mpeg`. Explanation limit is 1600 characters.
- Explanation languages: Japanese, French, Arabic, Hindi, English. Live captions and spoken live translation are fixed to Japanese.
- Explanation and explanation-audio requests happen on click. Live translation continuously
  sends microphone audio to Gemini. Both providers' usage limits still apply.
- The demo remains local and has no authentication. Configure access controls before public deployment.

Automated local checks used simulated AI responses. A team member has also reported
that the real selected-phrase explanation flow works. Each teammate should try it
with their own keys; exact latency, explanation quality and sustained usage limits
have not been independently benchmarked.

### Troubleshooting

Unexpected AI-service failures show a reference ID on the page. Find the same ID
in the server terminal to see the failing service, error type, status code and
code locations. Diagnostics omit provider response bodies, API keys and transcript
text. Explanation and speech requests have a 45-second server timeout; the browser
also catches network failures and has a 60-second request timeout. These timeouts
do not add a delay to live captions. Rate-limit errors are shown without automatic retries.


## Spoken translation (live captions read aloud)

Tick **Speak translation** on the page to hear the Japanese captions read aloud by ElevenLabs.
This is separate from **Explain and listen**, which reads an explanation of a selected phrase.
It needs `ELEVENLABS_API_KEY` in `.env` (the controls are disabled with an explanation without it).

**Use headphones if you can.** The microphone keeps listening while the voice plays, so a lecturer
who keeps talking is not missed. Without headphones the microphone can hear the voice; three things
reduce that:

1. The browser's echo cancellation is on, which removes the page's own audio from the recording.
2. **Echo guard:** if Gemini "translates" our own voice back into Japanese, text that matches what was
   just spoken is not spoken again (captions still show it). A lecturer who repeats a sentence
   word for word within about 25 seconds will not hear it read twice.
3. **Pause microphone while the voice plays** is available but **off by default**: it sends silence to
   Gemini while the voice plays, so words spoken in that time are *not* captured or translated.

How it behaves:

- Translation text streams in without sentence boundaries. Japanese `。！？` end a sentence immediately
  (no space needed), a long clause is spoken early at `、`, nothing is longer than 200 characters, and
  an unfinished sentence is spoken after 1.5 s of quiet or when the microphone stops.
- **Stop voice** clears the queue, cancels a request that is still loading and cuts the current audio,
  so nothing starts playing after you click it.
- Phrases play one at a time; the next is requested while the current one plays. At most 3 wait, and
  the oldest is dropped if speech falls behind the lecture. Repeated phrases are cached.
- The **voice picker** lists the voices on your ElevenLabs account (the default voice is used if the key
  may not list voices). Failures (bad key, no credits, rate limit) show next to the controls; upstream
  errors carry a reference ID that matches a line in the server terminal.
- Optional `.env` settings: `ELEVENLABS_VOICE_ID` (default George) and `ELEVENLABS_TTS_MODEL`
  (default `eleven_flash_v2_5`, which is also told the target language, `ja`).
- Endpoints: `GET /api/tts/config`, `GET /api/voices`, `POST /api/tts` (JSON `{ "text": "...", "voice_id": null }`,
  text up to 1000 characters; returns `audio/mpeg`).

## Gemini resilience (`/ws/live` translation)

`backend/gemini_resilience.py` wraps the per-sentence translate call. On a 429 it retries after 2, 4 and
8 s. If the model is reported retired/not found it lists the models the key can use, switches to the
best fast one (stable over preview, Flash-Lite over Flash, then highest version) and keeps going, and
logs which model it moved to. If `LIVE_TRANSLATION_MODEL` (the preview live model) is retired, the page
now says so instead of showing a bare error.

## Tests

```powershell
& ".\.venv\Scripts\python.exe" -m pip install pytest httpx
& ".\.venv\Scripts\python.exe" -m pytest tests
```

TiDB integration tests skip without credentials. `tests/test_speech_js.py` runs the Node tests for
`frontend/speech.js` and skips if Node.js is not installed. These tests use simulated services; they
do not replace trying the real microphone, speakers and API keys.
