so the main idea is we have real time translation and then depending on user feedback we only translate words that the user does not know already.
extra features:  
  reading out of the translation in real time (with an on/off switch)

## Local demo: Japanese captions and spoken explanations

With the project's Python virtual environment installed, run in PowerShell:

```powershell
& ".\.venv\Scripts\python.exe" -m pip install -r requirements.txt
& ".\.venv\Scripts\python.exe" ".\live_app.py"
```

Enter the Gemini and ElevenLabs keys at the hidden prompts, or set
`GEMINI_API_KEY` and `ELEVENLABS_API_KEY` in the server process environment.
The ElevenLabs prompt accepts a blank key for captions-only use. Never commit keys.
Open http://127.0.0.1:8000.

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
  
