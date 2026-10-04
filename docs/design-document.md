# Design document: live lecture translation and personal glossary

Updated: October 3, 2026.

## What we are building

Help students follow lectures in another language and understand unfamiliar concepts.
The app displays live translated captions, explains confusing phrases on request,
and remembers those explanations for later lectures.

Personalization comes from phrases the student chooses. The app does not yet infer
their language ability or automatically identify everything they find confusing.

## What works today

- Live original transcript and Japanese captions: implemented; user reported working.
- Selected-phrase explanations and ElevenLabs speech: implemented; user reported working.
- The earlier TiDB flow passed real persistence and matching checks on a small sample.
- Personal glossary: implemented; syntax/structure checked.
  Its new AI response format, UI, updates and removal need an end-to-end trial.

Full Japanese captions remain enabled. Saved terms are highlighted in the original
transcript, with brief translated help nearby. This is not a saved-phrases-only caption mode.

## The three user flows

### 1. Follow a live lecture

The student starts the microphone. Browser JavaScript streams audio through the
Python/FastAPI server to Gemini Live Translate. Original transcript fragments and
Japanese captions appear as Gemini returns them.

English speech produces an English original transcript. Live-caption language is
currently fixed to Japanese. The app does not save a recording or full transcript
to TiDB, and it does not play Gemini's generated audio.

### 2. Understand a confusing phrase

After stopping the microphone, the student selects words in the original transcript,
chooses an explanation language, and clicks **Explain and listen**.

Gemini returns a short translation and explanation using nearby context in one request.
ElevenLabs reads that explanation aloud. Available help languages are Japanese,
French, Arabic, Hindi and English;
this selector does not change the live captions.

The phrase, context, translation, explanation and language are saved to TiDB in the background.
If saving fails, the explanation remains usable. Repeated requests reuse text and
audio cached during the current microphone session; if speech fails, text remains.

### 3. Recognize a remembered concept

Saved concepts in the selected help language load when a session starts:

- JavaScript recognizes saved wording locally, ignoring capitalization and punctuation,
  and highlights exact terms. Hover, click or keyboard focus shows their short translation.
- TiDB searches by meaning in the background to suggest concepts expressed differently,
  and checks the saved source example to reduce matches caused by a shared word alone.
- Help follows the current sentence; semantic suggestions appear as **Possibly related**
  without claiming a precise location. Active help clears after 12 seconds of silence.

For example, saved **exponential growth** may be suggested when a later speaker says
**the population is growing exponentially**. This is a possible match, not a guarantee
that the old explanation fits the new context.

Saved explanations are collapsed behind **View saved explanation**, with their original
example. After stopping, listen without another Gemini request, or use **Explain this
occurrence** to request fresh help for an exact term's current context. ElevenLabs generates
speech unless cached. **My glossary** retains all saved terms and lets the student remove them.
Help defaults to Japanese on every page load. A different selection applies during
that session; saved browser language preferences cannot override the Japanese default.
Old entries without translations can be upgraded on request; audio uses the selected
help language and Japanese speech requires Japanese explanation text.

## What each technology does

| Technology | Role |
| --- | --- |
| HTML and JavaScript | Capture microphone audio, display captions, select phrases, match saved wording and play speech. |
| Python, FastAPI and Uvicorn | Run the local server and coordinate AI and database requests. |
| WebSockets | Maintain the continuous audio and caption connection. |
| Gemini Live Translate | Produce the original transcript and Japanese captions directly from microphone audio. |
| Gemini Flash Lite | Generate a short translation and contextual explanation in one requested response. |
| ElevenLabs | Read explanation text aloud in the selected language. |
| TiDB with Titan Auto Embedding | Store the glossary in the cloud and find related concepts by meaning. |

## How remembered help avoids extra Gemini requests

The earlier approach sent frequent transcript updates to Gemini as separate translation
requests and hit a rate limit. Captions now use an ongoing Gemini Live audio connection.
Local phrase matching and TiDB semantic search add no Gemini generation requests.

Semantic searches examine recent transcript text no more frequently than every
750 milliseconds, with only one search running per page. After a brief caption pause,
search can start after 150 milliseconds; during continuous speech it runs roughly once
a second when the database is keeping up. Semantic searches need four words of context.
Unchanged text is skipped. Exact phrase highlights update directly on caption packets.
Captions never wait for a search or save to finish.

Translations are stored in existing memory metadata; no table migration is required.
The shared cloud database filters active entries by browser ID and help language.
That ID persists locally, but does not authenticate the user or sync across devices.

Provider usage limits still apply. Semantic help can arrive later than captions,
and its matching threshold needs tuning with real lecture examples.

## Current limits and next steps

1. **Verify the real AI services together:** the synthetic browser replay with real
   TiDB recalled all eight intended matches and rejected three negative sentences.
   Save/refresh, Japanese help, browser identity separation and removal passed; the
   replay supplied caption messages, so real Gemini and ElevenLabs output still needs
   a combined run. Semantic help settled 213–332 ms after the last packet in this small
   fixture, not a general latency or accuracy benchmark.
2. **Improve phrase interaction:** new phrases are selected manually after stopping.
   Locating paraphrases precisely and recognizing unfamiliar concepts remain future work.
3. **Decide on phrase-only translation:** the current app provides full captions plus
   saved explanations. Showing translations only for remembered phrases needs a
   separate design and implementation.
4. **Add authentication before public deployment:** a browser-local random ID currently
   identifies the demo user. It is not a login or secure ownership check.

Continuous spoken translation is a separate proposed feature. Current ElevenLabs
audio is for explanations requested after stopping the microphone.

## Where to find technical details

- [README: setup, API contracts and troubleshooting](../README.md)
- [TiDB module: database setup and implementation](../backend/tidb/README.md)
- [Architecture diagram](ARCHITECTURE.md)

Main implementation files are `backend/live_app.py`, `backend/memory_api.py`,
`backend/tidb/` and `frontend/live.html`.
