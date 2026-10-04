so the main idea is we have real time translation and then depending on user feedback we only translate words that the user does not know already.
extra features:  
  reading out of the translation in real time (with an on/off switch)
  


## Running the live demo

```bash
pip install -r requirements.txt
export GEMINI_API_KEY=...          # asked for (hidden) if not set
export ELEVENLABS_API_KEY=...      # optional: speech-to-text on /ws/live and spoken translation
python live_app.py                 # http://127.0.0.1:8000
```

## Spoken translation (ElevenLabs text-to-speech)

Tick **Speak translation** on the page to hear the translated captions read out. Translation text
streams in without sentence boundaries, so the page speaks each sentence as it completes and the
unfinished tail once the text has been quiet for 1.5 s.

- **Voice picker** lists the voices on your ElevenLabs account (falls back to the default voice if the
  key may not list voices). **Stop voice** clears the queue and cuts the current audio.
- **Pause mic while speaking** (on by default) sends silence to Gemini while the voice plays, so the
  microphone doesn't hear the voice and translate it again. Turn it off when using headphones.
- The queue holds at most 3 phrases (oldest dropped) so speech stays close to live; repeated phrases
  are cached; failures (bad key, no credits, rate limit) show next to the controls.
- Without `ELEVENLABS_API_KEY` the controls are disabled with an explanation.
- Optional settings: `ELEVENLABS_VOICE_ID` (default George) and `ELEVENLABS_TTS_MODEL`
  (default `eleven_flash_v2_5`, which also gets the target language as a hint).
- Code: `backend/tts.py`; endpoints `GET /api/tts/config`, `GET /api/voices`, `POST /api/tts` in `live_app.py`.

## Gemini resilience (`/ws/live` translation)

`backend/gemini_resilience.py` wraps the per-sentence translate call. On a 429 it retries after 2, 4 and
8 s. If the model is reported as retired/not found it lists the models the key can use, switches to the
best fast one (stable over preview, Flash-Lite over Flash, then highest version) and keeps going, and
logs which model it moved to. If `LIVE_TRANSLATION_MODEL` (the preview live model) is retired, the page
now says so instead of showing a bare error.

## Tests

```bash
pip install pytest httpx
pytest tests            # TiDB integration tests skip without credentials
```
