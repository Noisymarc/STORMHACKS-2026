# Design document: live lecture translation and remembered help

Updated: October 3, 2026. This document describes the code currently merged into main.

## Purpose

Help students follow a lecture in another language and understand unfamiliar concepts.
A student sees live translated captions, selects confusing text after stopping the
microphone, and hears an explanation in their chosen language. Saved explanations
can be suggested when related concepts appear in a later session.

The long-term goal is personalized support: show help for concepts this particular
student struggles with, rather than treating every student identically. The current
implementation remembers concepts the student explicitly selects. It does not infer
their overall language ability or automatically decide which other words they know.

## Implementation status

- Live original transcript and Japanese captions: implemented; user reported working.
- Selected-phrase explanations and ElevenLabs speech: implemented; user reported working.
- TiDB saving and remembered-help panel: merged through PR #8. Real database persistence,
  matching quality and latency still need verification with configured TiDB credentials.
- Full captions continue alongside remembered help. Translating only saved phrases,
  automatic hover highlighting, and locating paraphrases within the transcript are future work.
- Continuous spoken translation is a separate proposed feature; it is not part of this flow.

### What the MVP does today

**Speak -> original transcript + Japanese captions -> Stop -> select confusing text
-> written explanation + ElevenLabs speech -> save the concept -> suggest saved help
when it appears again.**

There are two independent types of help: full translated captions, and remembered
concept explanations. A saved explanation is not a direct translation of the current
sentence. We do not yet suppress all other translations when a saved concept appears.

See [the architecture diagram](ARCHITECTURE.md) and [setup instructions](../README.md).

## User flows

### 1. Follow live speech

1. Start the microphone and grant permission.
2. Browser JavaScript captures mono audio and converts it to PCM16 at 16 kHz.
3. Audio is sent in approximately 100 ms packets through a WebSocket to FastAPI.
4. FastAPI relays audio to Gemini Live Translate using one ongoing live connection.
5. Gemini's original and translated transcription fragments are forwarded to the page.
6. JavaScript appends the fragments immediately. There is no five-second timer on this route.

The original transcript follows the speaker's language; English input remains English.
Live captions are currently fixed to Japanese. Packet size does not guarantee caption
latency. The model also generates audio internally, which this captions flow discards.
Microphone sessions do not currently save a recording or a complete transcript to TiDB.

### 2. Understand a selected phrase

1. Stop and wait until the page says **Microphone is off**.
2. Select up to 300 characters in the original transcript.
3. Choose Japanese, French, Arabic, Hindi or English and click **Explain and listen**.
4. The browser sends the phrase and nearby context to `POST /api/explain`.
5. Gemini produces a short explanation in the selected language. For Japanese,
   English-only output is rejected by a script-presence guard; this is not complete language verification.
6. Text appears on the page. Saving to TiDB starts independently in the background.
7. `POST /api/explanation-audio` sends the explanation to ElevenLabs and returns MP3 audio.
8. The browser plays the speech, with manual controls if automatic playback is blocked.

Cache results by phrase, context and language in browser memory. Repeated clicks reuse
text/audio during that session. If audio fails, retain the text and retry only speech.
A new microphone session clears that cache. Hovering or live transcript updates do not
generate explanations. Phrase selection remains manual browser text selection.

### 3. Remember a concept in later speech

1. A browser-local UUID identifies the local demo user across page refreshes.
2. Saved memories load from TiDB at page/session start without delaying microphone capture.
3. On each transcript update, JavaScript checks the latest 600 characters for saved
   phrases, ignoring capitalization and punctuation. This recognizes familiar wording locally.
4. TiDB semantic searches run in the background, at most one ongoing search per page
   and no more frequently than every 2.5 seconds. Unchanged text is skipped and results
   from an earlier session are discarded.
5. Exact matches appear as **Recognized**. Meaning-based results appear as **Possibly related**.
6. After stopping, the student can listen to a saved explanation without another Gemini
   explanation request. ElevenLabs still generates speech unless session audio is cached.

Example: a saved concept, **exponential growth**, may be suggested when the speaker
says **the population is growing exponentially**. Similarity is a ranking score, not
confidence or proof that the explanation fits this new context. The current TiDB
threshold is provisional and needs real lecture examples.

### How we avoid repeating the earlier rate-limit problem

The previous transcription-to-translation approach created a Gemini text-generation
request for frequent transcript updates. The current caption flow uses a continuous
Gemini audio session. Recognizing a saved exact phrase happens in JavaScript, and
semantic matching happens in TiDB; neither adds a Gemini generation request.

Gemini generates a new explanation only when the user requests one that is not in
the current session cache. Clicking a remembered-help entry uses its stored explanation.
This reduces repeated generation but does not remove Gemini Live or TiDB usage limits.
Semantic searches can still be delayed or fail, so they never gate caption display.

## Backend and frontend contract

All browser requests go through the local FastAPI server. API keys and database
credentials are never sent to the browser.

| Connection or endpoint | Input | Result |
| --- | --- | --- |
| WebSocket `/ws/continuous` | Binary PCM16 mono audio at 16 kHz; text `stop` ends the stream. | `source_delta`, `translation_delta`, `status` and `error` events. |
| POST `/api/explain` | Selected phrase, surrounding context, explanation language. | Phrase, language and explanation text. |
| POST `/api/explanation-audio` | Explanation text and language. | MP3 audio bytes. |
| GET `/api/memories` | Browser demo user UUID in `user_id`. | Saved concepts and explanations for that ID. |
| POST `/api/memories` | User UUID, phrase, context, explanation and language. | Saved memory ID as a string. |
| POST `/api/memories/search` | User UUID and up to 600 characters of recent transcript. | Up to three related saved memories. |
| GET `/api/memories/status` | No input. | Whether database settings are present; this is not a live connection test. |

The explanation language selector does not change live-caption language. Live captions
remain Japanese. The browser caches explanations by phrase, context and language;
changing language clears the displayed result and requires another Explain click.

## Technology responsibilities

| Technology | Responsibility |
| --- | --- |
| HTML and JavaScript | Microphone controls, text selection, caption display, local matching, background requests and audio playback. |
| Python/FastAPI | Serve the page; coordinate live audio, explanations, speech and database endpoints. |
| Uvicorn | Run the local FastAPI server on 127.0.0.1:8000. |
| WebSockets | Carry continuous microphone audio and caption fragments. |
| Gemini Live Translate | Process audio directly and return original/Japanese transcription fragments. Model: gemini-3.5-live-translate-preview. |
| Gemini Flash Lite | Generate on-demand contextual explanations. Model: gemini-3.1-flash-lite. |
| ElevenLabs | Speak explanation text using eleven_multilingual_v2. It does not transcribe the main continuous flow. |
| TiDB with Titan Auto Embedding | Persist confusing concepts and compare transcript wording by meaning. |
| SQLAlchemy/PyMySQL | Connect Python to TiDB using verified TLS and bounded connection/read/write timeouts. |
| python-dotenv | Load ignored local .env settings; process environment variables take priority. |

The older ElevenLabs transcription -> Gemini text-translation route remains available
at `/ws/live`; it is not used by the current browser demo.

## Stored data and boundaries

Each TiDB memory stores the demo user ID, phrase, original context, explanation in
`note`, source/target language, language metadata, timestamps, active status and an
embedding generated from the phrase's `content`. Context is stored but not embedded.
The module uses TiDB Cloud Starter on AWS with its configured Titan embedding model.
No additional Gemini call is made to match saved concepts.

| Memory field | What it means |
| --- | --- |
| `user_id` | Browser demo identity used to filter that user's rows. |
| `content` | Original confusing phrase; this is the text embedded for semantic matching. |
| `context` | Nearby original transcript text used when the explanation was created. |
| `note` | Saved explanation text in the chosen language. |
| `source_lang`, `target_lang` | Source and explanation language codes. The current English-input demo saves source as `en`. |
| `metadata` | Includes the explanation language's display name. |
| `embedding` | TiDB-generated numerical representation of the phrase's meaning. |
| `status`, timestamps | Active status and creation/update information. |

Search filters active rows by user ID, ranks them by cosine similarity, and drops
results below the provisional threshold of 0.15. That value is not 15% confidence.
The database currently embeds the phrase only, not its context, so ambiguous phrases
and broad lecture passages can produce unsuitable suggestions.

Memory IDs are returned as strings because database BIGINT values may exceed
JavaScript's safe integer range. Normal repeated saves reuse a matching
phrase/context/language row; simultaneous clients can still create duplicates.
Audio is not stored in TiDB. API keys remain on the server and are excluded from Git.

The browser UUID is not authentication. Another browser or cleared browser storage
uses a different ID. Before public deployment, add authenticated users and server-side
ownership checks. The current demo binds only to the local computer.

## Reliability and latency

- Caption delivery never awaits a memory save or search.
- Database operations run outside the async event loop; errors appear in a separate panel.
- Missing TiDB settings leave captions and new explanations available, without persistence.
- Explanations and speech have timeouts and readable quota/access errors. Unexpected provider
  errors have matching page/terminal reference IDs; raw responses and transcript text are omitted.
- Exact matching requires enough transcript words to identify the phrase. Semantic matching
  adds database/network/embedding delay; instantaneous paraphrase recognition is not guaranteed.
- Gemini, ElevenLabs and TiDB usage limits still apply. Background matching avoids extra
  Gemini generation requests but does not make database searches unlimited.

## Verification and next acceptance check

Simulated backend and Chromium checks cover saving/listing memories, user filtering,
cache reuse, exact recognition, semantic suggestions, throttling, invalid input and
failure isolation. Simulated caption updates continued during a delayed database search.
The local TiDB connection settings were unavailable, so real persistence, search
accuracy and latency have not been verified for this integration.

The next real-database acceptance check:

1. Configure TiDB and save a selected phrase; confirm the page reports success.
2. Refresh/start a later session in the same browser; confirm the phrase is retained.
3. Repeat its wording, then a paraphrase; observe recognition and any irrelevant suggestions.
4. Listen to the saved explanation and confirm no new Gemini explanation is requested.
5. Try unavailable database settings and confirm live captions still function.
6. Measure caption lag and time to remembered help during a continuous conversation.

## Next milestones

1. Verify the existing TiDB integration with the team's actual database and tune matching
   using both related and unrelated lecture examples.
2. Highlight/select meaningful phrases on hover; current selection is manual.
3. Locate where a related concept appears in the new transcript, rather than only showing
   a suggested saved concept in the separate panel.
4. Decide whether to retain full captions or implement a separate saved-phrases-only mode.
   That mode requires explicit design work; it is not enabled by the current memory search.
5. Add authenticated user identity before sharing a publicly reachable deployment.

## Repository ownership

- `backend/live_app.py`: live-caption and explanation/speech routes.
- `backend/memory_api.py`: website endpoints for memory storage and search.
- `backend/tidb/`: database connection, schema and semantic-search implementation.
- `frontend/live.html`: plain demo, client matching and playback.
- `docs/`: design and architecture; root README provides setup and endpoint contracts.
