# Live lecture translation

Our goal is real-time translation with personalized help for concepts the user
finds confusing. The demo provides live captions and spoken explanations on demand.
A personal glossary stores confusing phrases, short translations and explanations in TiDB.
Reading all live translations aloud is a planned feature.

## Current features

- Live original transcript and Japanese captions.
- Select a confusing phrase after stopping to get a translation and spoken explanation.
- Save phrases in a personal glossary and highlight exact terms in later speech.
- Show short help in the selected language; expand explanations when needed.
- Update an explanation for the current lecture or remove a phrase from the glossary.

The glossary code has syntax and structure checks. Its full microphone/AI/database
flow still needs a demo trial; merging the code does not verify those runtime results.

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
git pull --ff-only origin main
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
Press Ctrl+C in the terminal to stop the server. Restart it after pulling new code
or changing settings, then refresh the browser to load the latest page.
The original
`& ".\.venv\Scripts\python.exe" ".\live_app.py"` command still works.

The separate TiDB module keeps its own dependencies and setup instructions in
[backend/tidb/README.md](backend/tidb/README.md). Optional TiDB settings are included
in the root environment template. Database settings are optional for captions and
explanations, but required for remembering confusing phrases.

### 5. Try the feature

1. Click **Start microphone**, allow microphone access, and speak in English.
   The original transcript stays in English; translated captions appear in Japanese.
2. **Help language** defaults to Japanese each time the page loads; choose another
   language for this session when desired. Live captions remain Japanese.
   Click **Stop** and wait until the page says **Microphone is off**.
   Then select a confusing phrase in the original transcript. Selection while listening is disabled.
3. Click **Explain and listen**.
4. Read Gemini's short phrase translation and explanation, and hear ElevenLabs speak
   the explanation. Use the audio controls if the browser blocks automatic playback.

Repeated requests for the same selected phrase, surrounding context and language
reuse the explanation and audio in browser memory. Starting a new microphone
session clears those results. If speech fails, the explanation text remains and
clicking again retries just the audio.
New phrases are selected manually. Saved phrases are highlighted automatically in
the original transcript; click, hover or focus a highlighted term to see its saved help.

## Remember confusing phrases with TiDB

Add `TIDB_HOST`, `TIDB_USER`, `TIDB_PASSWORD`, `TIDB_PORT` and `TIDB_DB_NAME`
to your existing `.env` using the database's Connect settings, then restart the
server. This module uses TiDB Cloud Starter on AWS with Auto Embedding support.
Do not overwrite your Gemini/ElevenLabs keys when adding database settings.
The app creates the memories table if it is missing.

For a repeatable demo, say **“Today we are studying exponential growth”**, stop,
select **exponential growth**, and request Japanese help. Wait for the save message,
refresh, then start a new session and say the phrase again. Expect a highlighted term
and Japanese translation. In separate fresh sessions, try **“The population is growing
exponentially”** and an unrelated sentence such as **“The chef is chopping onions.”**
Paraphrases may be missed; they are suggestions, not guaranteed matches.

1. Stop recording, select a phrase and request an explanation.
2. The phrase, its context, translation, explanation and help language are saved to TiDB
   in the background. Check the **My glossary** status for confirmation.
3. Start a new session in the same browser. Your saved concepts load automatically.
4. Repeat a saved phrase to see a highlighted term and its short translation under
   **Phrase help**, or use related wording (for example "growing exponentially" for
   "exponential growth") to see **Same idea as …** with those words highlighted.
5. Open **View saved explanation**. After stopping the microphone, click
   **Listen to saved explanation**. This reuses
   the saved text without a Gemini explanation request. ElevenLabs generates audio
   if that explanation has not already been played during this browser session.

Only memories in the selected help language are displayed and searched. Changing
language does not automatically translate old entries or change Japanese live captions.
Older entries without short translations can be upgraded using **Add translation and listen**
after stopping; this makes one new Gemini request and updates the existing glossary entry.
Repeated saves update the same normalized phrase/language entry in the normal single-client flow.

Exact matching ignores capitalization and punctuation and runs locally on transcript
updates. Active help follows the current sentence and clears after 12 seconds of
silence while listening. Historical highlights remain clickable. Meaning-based searches
use TiDB in the background, at most one ongoing
search per page and no more frequently than every 2.5 seconds. Unchanged text is
not searched again. Captions do not wait for search results. TiDB search still has
network/model latency and usage limits.

### Checking related wording with Gemini

TiDB's meaning search also matches sentences that only share words ("The train arrived
late" for "latency") or a neighbouring topic. When it finds candidates for the current
sentence, one small Gemini request checks whether the sentence really uses each saved
concept and returns the words that express it. Confirmed matches are highlighted and
labelled **Same idea as …**; rejected ones are hidden. Sentences without candidates make
no Gemini request, and repeated checks of the same sentence reuse the earlier answer.

To protect the Gemini quota shared with captions and explanations, checks are capped
(set in `.env`): `CONCEPT_JUDGE_PER_MINUTE` (default 4) and `CONCEPT_JUDGE_DAILY_LIMIT`
(default 150 per server run per UTC day). After a rate-limit error, checks pause for a minute.
`CONCEPT_JUDGE=off` disables them. Whenever a check is off, over a cap or fails, the page
falls back to unchecked **Possibly related** suggestions above a stricter similarity.

### Help fades as a concept keeps coming back

Saving a phrase marks that the student needed help with it at that time; the app never
asks the student to say they understood. While listening, each new sentence that uses a
saved concept (the exact phrase or a Gemini-confirmed paraphrase) counts as one encounter,
stored in TiDB's `memory_exposures` table. Full help appears on encounters 1, 2, 4, 8, 16, ...;
in between, the phrase is only underlined and its help opens on click. Help therefore becomes
rarer as the student keeps meeting the concept but never stops completely. Explaining the
phrase again starts the count over, and **Remove from glossary** stops it. Unchecked
**Possibly related** suggestions are not counted.

`scripts/eval_search.py` (TiDB) and `scripts/eval_need.py` (Gemini, same prompt as the app)
measure this. On their sample sentences, single-sentence search at similarity 0.12 found
20 of 22 related memories and the Gemini check judged 25 of 25 candidates correctly.
These are small hand-written samples, not real lecture transcripts.

Full Japanese captions remain enabled. Exact terms and Gemini-confirmed wording are
highlighted; unchecked **Possibly related** suggestions do not claim a precise location. Saved explanations show their
original example because they can be unsuitable in a different context. For an exact
term, **Explain this occurrence** requests a fresh translation/explanation using the
current lecture context after stopping. **Remove from glossary** retires a saved entry;
it stops appearing in loads and searches. Neither action runs automatically.

This local demo uses a random ID saved in browser storage, not a login. The same
browser retains its ID across sessions; another browser or cleared storage uses a
different ID. This is not authenticated access control and must be replaced before
public deployment. Saved text goes to the configured database. Audio is cached in
browser memory only. If TiDB is unconfigured or fails, captions and new explanations
still work; the page reports the save/search failure separately.

### Where the information is saved

Phrases, translations, context and explanations are saved in the configured TiDB
Cloud database. The team can share a database, while the app filters records by each
browser's demo ID. Database credentials grant access to the shared database; the demo
ID is not a security boundary. Another browser/device has a different ID and does
not automatically load your glossary.

Only the demo ID and help-language preference persist in browser storage. Generated
audio and explanation caches are temporary; a new microphone session clears them.
There is no local database backup if a cloud save fails.

## Technologies in plain language

- **HTML and JavaScript:** display the page, capture microphone audio, and play explanations.
- **Python, FastAPI and Uvicorn:** run the local server and coordinate requests to the AI services.
- **WebSockets:** keep the live audio/caption connection open so updates can arrive while you speak.
- **Gemini:** translates live microphone audio and generates phrase translations/explanations when requested.
- **ElevenLabs:** reads the selected phrase's explanation aloud; it does not currently read all live captions aloud.
- **TiDB:** stores the personal glossary and finds saved concepts related to incoming speech.

### Backend contract (for frontend integration)

- `POST /api/explain`: JSON `{ "phrase": "...", "context": "...", "language": "Japanese" }`;
  returns `{ "phrase": "...", "language": "Japanese", "translation": "...", "explanation": "..." }`.
  The phrase must occur in the context; phrase limit is 300 characters and context limit is 4000.
- `POST /api/explanation-audio`: JSON `{ "explanation": "...", "language": "Japanese" }`;
  returns MP3 bytes with `audio/mpeg`. Explanation limit is 1600 characters.
- Explanation languages: Japanese, French, Arabic, Hindi, English. Live captions are fixed to Japanese.
- Explanation and explanation-audio requests happen on click. Live translation continuously
  sends microphone audio to Gemini. Both providers' usage limits still apply.
- `GET /api/memories?user_id=<uuid>&language=Japanese` lists active entries in that language.
- `POST /api/memories` accepts `user_id`, `phrase`, `context`, `translation`, `explanation` and `language`;
  returns a string `id`. Repeated saves of the same normalized phrase/language update a row
  in the normal single-client flow; simultaneous clients can still create duplicates.
- `POST /api/memories/search` accepts `user_id`, `language` and `transcript` (up to 600 characters);
  filters by language before ranking related memories with TiDB's semantic search. Each result
  adds `confirmed` (`true` when Gemini confirmed it, with `expression` = the matching words;
  `null` when unchecked). Candidates Gemini rejected are omitted.
- `DELETE /api/memories/<id>?user_id=<uuid>` retires only that demo user's entry.
- The demo remains local and has no authentication. Configure access controls before public deployment.

Automated local checks used simulated AI responses. A team member has also reported
that the real selected-phrase explanation flow works. Each teammate should try it
with their own keys; exact latency, explanation quality and sustained usage limits
have not been independently benchmarked.
The earlier memory flow passed a real TiDB trial: persistence, browser refresh and
exact matching worked; two of three paraphrases matched, and three unrelated sentences
were rejected. Searches took 51–489 ms in that small sample, plus any browser scheduling
wait. The glossary rework has syntax/structure checks; its new UI, structured AI output,
entry updates and removal still need an end-to-end trial. The earlier results do not
verify this new flow.

### Troubleshooting

Unexpected AI-service failures show a reference ID on the page. Find the same ID
in the server terminal to see the failing service, error type, status code and
code locations. Diagnostics omit provider response bodies, API keys and transcript
text. Explanation and speech requests have a 45-second server timeout; the browser
also catches network failures and has a 60-second request timeout. These timeouts
do not add a delay to live captions. Rate-limit errors are shown without automatic retries.
  
