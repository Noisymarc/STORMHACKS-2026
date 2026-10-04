# System architecture

This diagram shows the current live-caption flow and the on-demand personal glossary.
Live captions stay visible in Japanese; saved explanations are separate, and ElevenLabs
speaks explanations only when requested.

```mermaid
flowchart LR
    subgraph browser[Browser]
        direction TB
        mic[Microphone audio]
        captions[Original transcript<br/>Japanese captions]
        selection[Student selects a phrase<br/>and help language]
        exact[Local exact-phrase matcher<br/>selected help language]
        help[Current phrase help<br/>and glossary]
        playback[Explanation text and<br/>audio playback]
        identity[Browser-local demo ID]
    end

    subgraph server[Python app - FastAPI]
        direction TB
        livews[WebSocket<br/>/ws/continuous]
        explain[POST /api/explain]
        speech[POST /api/explanation-audio]
        memories[Memory API<br/>load, save, search, remove]
    end

    subgraph providers[AI services]
        direction TB
        live[Gemini Live Translate<br/>speech to transcript and Japanese captions]
        flash[Gemini Flash Lite<br/>phrase translation and explanation]
        tts[ElevenLabs<br/>spoken explanation]
    end

    subgraph cloud[TiDB Cloud]
        direction TB
        table[(Glossary entries<br/>phrase, translation, explanation, context<br/>Titan-generated phrase vector)]
    end

    mic -->|PCM audio over WebSocket| livews
    livews --> live
    live -->|Transcript and Japanese caption fragments| livews
    livews --> captions

    captions --> exact
    table -->|Loaded for this browser ID| memories
    memories --> help
    identity --> memories
    exact -->|Exact wording highlights| help
    captions -->|Current sentence, in background| memories
    memories -->|Meaning-based suggestions| help

    selection --> explain
    explain --> flash
    flash -->|Structured translation and explanation| explain
    explain -->|Text in the selected help language| playback
    playback -->|Save phrase and generated help| memories
    memories -->|Persist phrase and help| table

    playback -->|When speech is requested| speech
    speech --> tts
    tts -->|MP3 audio| speech
    speech --> playback

```

## Main boundaries

- **Browser:** captures audio, displays captions, recognizes exact saved wording locally,
  and presents explanations. The demo ID is stored in that browser; it is not a login.
- **FastAPI:** holds provider/database credentials and coordinates WebSocket audio,
  explanations, speech requests, and glossary endpoints.
- **Gemini Live Translate:** handles the continuous caption stream. Generated audio from
  this live-caption route is discarded.
- **Gemini Flash Lite:** creates a short phrase translation and contextual explanation
  only when the student requests help. Exact and semantic recognition do not call Gemini.
- **ElevenLabs:** speaks explanation text in the selected help language. It does not
  currently speak the continuous live captions.
- **TiDB Cloud:** stores active glossary entries and retrieves related phrases. Its Titan
  stored Auto Embedding vector represents the saved phrase (`content`). Searches also
  compare the new sentence with the saved source example using TiDB embeddings; this
  needs no table migration or Gemini call. Semantic matches remain suggestions and may
  not fit the current lecture.

Glossary searches run in the background; captions do not wait for database results.
Saved entries are scoped by browser demo ID and selected help language. The shared demo
database has no authenticated account boundary.
