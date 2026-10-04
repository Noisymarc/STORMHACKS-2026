# Design document: live lecture translation and remembered help

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
- TiDB saving and remembered-help suggestions: merged; real database persistence,
  matching quality and latency still need verification with configured credentials.

Full Japanese captions remain enabled. Remembered explanations appear in a separate
panel; they are not translations of only the saved phrases.

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

Gemini explains the phrase using nearby context. ElevenLabs reads that explanation
aloud. Available explanation languages are Japanese, French, Arabic, Hindi and English;
this selector does not change the live captions.

The phrase, context, explanation and language are saved to TiDB in the background.
If saving fails, the explanation remains usable. Repeated requests reuse text and
audio cached during the current microphone session; if speech fails, text remains.

### 3. Recognize a remembered concept

Saved concepts load when a session starts. As new transcript text arrives:

- JavaScript recognizes saved wording locally, ignoring capitalization and punctuation.
- TiDB searches by meaning in the background to suggest concepts expressed differently.
- Exact matches appear as **Recognized**; semantic suggestions appear as **Possibly related**.

For example, saved **exponential growth** may be suggested when a later speaker says
**the population is growing exponentially**. This is a possible match, not a guarantee
that the old explanation fits the new context.

After stopping, the student can listen to a saved explanation without asking Gemini
to generate it again. ElevenLabs generates speech unless that audio is already cached.

## What each technology does

| Technology | Role |
| --- | --- |
| HTML and JavaScript | Capture microphone audio, display captions, select phrases, match saved wording and play speech. |
| Python, FastAPI and Uvicorn | Run the local server and coordinate AI and database requests. |
| WebSockets | Maintain the continuous audio and caption connection. |
| Gemini Live Translate | Produce the original transcript and Japanese captions directly from microphone audio. |
| Gemini Flash Lite | Generate contextual explanations when the student requests them. |
| ElevenLabs | Read explanation text aloud in the selected language. |
| TiDB with Titan Auto Embedding | Store confusing phrases and explanations, and find related concepts by meaning. |

## How remembered help avoids extra Gemini requests

The earlier approach sent frequent transcript updates to Gemini as separate translation
requests and hit a rate limit. Captions now use an ongoing Gemini Live audio connection.
Local phrase matching and TiDB semantic search add no Gemini generation requests.

Semantic searches examine recent transcript text no more frequently than every
2.5 seconds, with only one search running per page. Unchanged text is skipped.
Captions never wait for a search or save to finish.

Provider usage limits still apply. Semantic help can arrive later than captions,
and its matching threshold needs tuning with real lecture examples.

## Current limits and next steps

1. **Verify TiDB with the team's database:** save a phrase, refresh, recognize it in
   later speech, try paraphrases and unrelated sentences, and measure response time.
   Existing database integration checks used simulated responses.
2. **Improve phrase interaction:** selection is currently manual and only available
   after stopping. Hover highlighting and locating paraphrases in the transcript
   remain future work.
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
