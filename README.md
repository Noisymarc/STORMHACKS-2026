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
- **ElevenLabs:** reads the selected phrase's explanation aloud; it does not currently read all live captions aloud.
- **TiDB:** stores and searches saved concepts in a separate module. It is not yet connected to the website.

### Backend contract (for frontend integration)

- `POST /api/explain`: JSON `{ "phrase": "...", "context": "...", "language": "Japanese" }`;
  returns `{ "phrase": "...", "language": "Japanese", "explanation": "..." }`.
  The phrase must occur in the context; phrase limit is 300 characters and context limit is 4000.
- `POST /api/explanation-audio`: JSON `{ "explanation": "...", "language": "Japanese" }`;
  returns MP3 bytes with `audio/mpeg`. Explanation limit is 1600 characters.
- Explanation languages: Japanese, French, Arabic, Hindi, English. Live captions are fixed to Japanese.
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
  
