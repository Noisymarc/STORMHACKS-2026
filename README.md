# Live lecture translation

Our goal is real-time translation with personalized help for concepts the user
finds confusing. The current demo provides live captions and spoken explanations
on demand. TiDB now supports saved confusing concepts and remembered-help suggestions.
Reading all live translations aloud is a planned feature.

## Repository layout

```text
backend/
  live_app.py           FastAPI server, live translation, explanations and speech
  memory_api.py         Saved-phrase and semantic-search endpoints
  tidb/                 TiDB memory/search module
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
in the root environment template. Database settings are optional for captions and
explanations, but required for remembering confusing phrases.

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
clicking again retries just the audio.
Phrase selection is manual text selection; automatic hover highlighting is future work.

## Remember confusing phrases with TiDB

Add `TIDB_HOST`, `TIDB_USER`, `TIDB_PASSWORD`, `TIDB_PORT` and `TIDB_DB_NAME`
to your existing `.env` using the database's Connect settings, then restart the
server. This module uses TiDB Cloud Starter on AWS with Auto Embedding support.
Do not overwrite your Gemini/ElevenLabs keys when adding database settings.
The app creates the memories table if it is missing.

1. Stop recording, select a phrase and request an explanation.
2. The phrase, its context, explanation and explanation language are saved to TiDB
   in the background. Check the **Remembered help** status for confirmation.
3. Start a new session in the same browser. Your saved concepts load automatically.
4. Repeat a saved phrase to see **Recognized** help, or use related wording to see
   a **Possibly related** suggestion.
5. After stopping the microphone, click **Listen to saved explanation**. This reuses
   the saved text without a Gemini explanation request. ElevenLabs generates audio
   if that explanation has not already been played during this browser session.

Exact matching ignores capitalization and punctuation and runs locally on transcript
updates. Meaning-based searches use TiDB in the background, at most one ongoing
search per page and no more frequently than every 2.5 seconds. Unchanged text is
not searched again. Captions do not wait for search results; no Gemini generation
requests are added for matching. TiDB search still has network/model latency and
usage limits. Its provisional similarity threshold needs testing with real lectures.

Full Japanese captions remain enabled. Remembered help is a separate panel; it
does not yet replace captions with translations of only saved phrases or locate
paraphrased words for inline highlighting. Saved explanations can be unsuitable
in a different context, so semantic matches are labeled as suggestions.

This local demo uses a random ID saved in browser storage, not a login. The same
browser retains its ID across sessions; another browser or cleared storage uses a
different ID. This is not authenticated access control and must be replaced before
public deployment. Saved text goes to the configured database. Audio is cached in
browser memory only. If TiDB is unconfigured or fails, captions and new explanations
still work; the page reports the save/search failure separately.

## Technologies in plain language

- **HTML and JavaScript:** display the page, capture microphone audio, and play explanations.
- **Python, FastAPI and Uvicorn:** run the local server and coordinate requests to the AI services.
- **WebSockets:** keep the live audio/caption connection open so updates can arrive while you speak.
- **Gemini:** translates live microphone audio and generates explanations when you click Explain.
- **ElevenLabs:** reads the selected phrase's explanation aloud; it does not currently read all live captions aloud.
- **TiDB:** stores confusing phrases and explanations, and finds saved concepts related to incoming speech.

### Backend contract (for frontend integration)

- `POST /api/explain`: JSON `{ "phrase": "...", "context": "...", "language": "Japanese" }`;
  returns `{ "phrase": "...", "language": "Japanese", "explanation": "..." }`.
  The phrase must occur in the context; phrase limit is 300 characters and context limit is 4000.
- `POST /api/explanation-audio`: JSON `{ "explanation": "...", "language": "Japanese" }`;
  returns MP3 bytes with `audio/mpeg`. Explanation limit is 1600 characters.
- `GET /api/memories/export?user_id=<uuid>`: the user's saved phrases as a downloadable text file
  (`text/plain`); `POST /api/memories/import`: JSON `{ "user_id": "<uuid>", "text": "<file contents>" }`
  adds the phrases in such a file to that user and returns `{ "added": n, "skipped_duplicates": m }`
  (up to 200 phrases; a file with any problem is refused with a 422 and nothing is imported).
  See [backend/tidb/README.md](backend/tidb/README.md#dictionary-file-copy-the-saved-phrases-to-another-device).
- Explanation languages: Japanese, French, Arabic, Hindi, English. Live captions are fixed to Japanese.
- Explanation and explanation-audio requests happen on click. Live translation continuously
  sends microphone audio to Gemini. Both providers' usage limits still apply.
- `GET /api/memories?user_id=<uuid>` lists that demo user's saved help.
- `POST /api/memories` accepts `user_id`, `phrase`, `context`, `explanation` and `language`;
  returns a string `id`. Repeated saves of the same phrase/context/language reuse a row
  in the normal single-client flow; simultaneous clients can still create duplicates.
- `POST /api/memories/search` accepts `user_id` and `transcript` (up to 600 characters);
  returns related memories. It uses TiDB's semantic search, not Gemini.
- The demo remains local and has no authentication. Configure access controls before public deployment.

Automated local checks used simulated AI responses. A team member has also reported
that the real selected-phrase explanation flow works. Each teammate should try it
with their own keys; exact latency, explanation quality and sustained usage limits
have not been independently benchmarked.
The new database connection was checked with simulated stores and browser responses;
real TiDB search accuracy, persistence and latency still need a trial with configured credentials.

### Troubleshooting

Unexpected AI-service failures show a reference ID on the page. Find the same ID
in the server terminal to see the failing service, error type, status code and
code locations. Diagnostics omit provider response bodies, API keys and transcript
text. Explanation and speech requests have a 45-second server timeout; the browser
also catches network failures and has a 60-second request timeout. These timeouts
do not add a delay to live captions. Rate-limit errors are shown without automatic retries.
  
