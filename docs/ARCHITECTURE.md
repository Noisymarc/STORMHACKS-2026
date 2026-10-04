# System architecture

This diagram describes the current demo plus the TiDB website integration in PR #8.
That integration has simulated checks; real database persistence and latency still
need verification. See [the design document](design-document.md) for limitations.

```mermaid
flowchart LR
    subgraph Browser[Browser client]
        Mic[Microphone]
        Captions[Original transcript and Japanese captions]
        Selection[Select phrase after Stop]
        Explain[Explanation text and audio player]
        Matcher[Local exact phrase matching]
        Help[Remembered help panel]
        Saved[Loaded saved concepts]
    end
    subgraph Server[Python FastAPI server]
        Live[Live audio and caption relay]
        ExplainAPI[Explanation endpoint]
        SpeechAPI[Speech endpoint]
        MemoryAPI[Memory save and background search]
    end
    subgraph Services[External services]
        LiveGemini[Gemini Live Translate]
        TextGemini[Gemini explanation generation]
        Eleven[ElevenLabs explanation speech]
        DB[(TiDB memories and Titan embeddings)]
    end
    Mic -->|PCM audio over WebSocket| Live
    Live -->|Continuous audio| LiveGemini
    LiveGemini -->|Original and translated text| Live
    Live --> Captions
    Captions -->|After Stop, select text| Selection
    Captions -->|Transcript updates| Matcher
    Saved --> Matcher
    Matcher -->|Recognized phrase| Help
    Captions -.->|Latest text in background| MemoryAPI
    MemoryAPI -->|Semantic query| DB
    DB -->|Related saved help| MemoryAPI
    MemoryAPI --> Help
    MemoryAPI -->|Load memories at session start| Saved
    Selection -->|Phrase and context| ExplainAPI
    ExplainAPI --> TextGemini
    TextGemini -->|Selected-language explanation| ExplainAPI
    ExplainAPI --> Explain
    Explain -->|Save independently of playback| MemoryAPI
    MemoryAPI -->|Persist phrase and explanation| DB
    Explain -->|Request explanation speech| SpeechAPI
    SpeechAPI --> Eleven
    Eleven -->|MP3| SpeechAPI
    SpeechAPI --> Explain
    Help -->|After Stop, reuse saved explanation| Explain
```

## Reading the diagram

- The live-caption path runs continuously and does not wait for database searches.
- Selection sends an explanation request only when the user clicks Explain.
- Recognized wording uses local matching; paraphrases use TiDB search and are suggestions.
- Saved explanation text can be reused without Gemini generation. Speech may still need ElevenLabs.
- TiDB stores concepts/explanations, not audio recordings. The browser holds temporary audio caches.
- Full Japanese captions remain enabled. Phrase-only translation and automatic inline highlighting are future work.
- API keys stay server-side. The persistent browser ID is for the local demo, not authenticated access.
