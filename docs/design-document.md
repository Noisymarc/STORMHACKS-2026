# Main idea


[ Micro / Audio Stream ] 
       │ (WebSocket / WebRTC)
       
       ▼
[ 1. Voice Activity Detection (VAD) & Chunking ]
       │

       ▼
[ 2. Streaming Speech-to-Text (STT) ] ──▶ Partial/Final Transcripts
       │

       ▼
[ 3. Translation Engine ] (or End-to-End Multilingual STT)
       │

       ▼
[ 4. AI Post-Processing & Context Polisher ] (Optional LLM Step)
       │

       ▼
[ Frontend Display ] (Subtitles / Captions UI)


## the main process

1. Audio Capture & Streaming: The client app records audio input (e.g., via Web Audio API) and streams PCM audio chunks to your server or API endpoint over WebSockets or WebRTC for sub-second latency.

2. Speech-to-Text (STT): Converts raw audio chunks into text tokens in real time.

3. Translation & AI Context Correction: Converts source-language text to target-language text and cleans up speech anomalies (filler words, stuttering, domain-specific terminology).

4. Subtitles UI Engine: Renders streaming "interim" text as the speaker is talking, then updates it to "finalized" text once a sentence or pause is completed.

Language: Python

API's: Google Gemini, ElevenLabs, 
