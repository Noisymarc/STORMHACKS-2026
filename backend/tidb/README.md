# backend/tidb — Personalized Memory on TiDB

Per-user memory (expressions a user didn't understand, notes, …) with semantic
search, built on **TiDB Cloud Starter (AWS) Auto Embedding**. TiDB generates
every embedding itself (`EMBED_TEXT` with `tidbcloud_free/amazon/titan-embed-text-v2`),
so this module never calls an embedding API.

```
transcript + user_id
  → WHERE user_id = ? (only that user's rows)
  → exact VEC_EMBED_COSINE_DISTANCE(embedding, transcript)
  → closest memories first
```

## Use

```python
from backend.tidb import MemoryStore

store = MemoryStore.from_env()
store.init_schema()
store.add_memory("user-1", "exponential growth", context="Revenue shows exponential growth.")
store.search_relevant_memories("user-1", "The number of users is growing exponentially.")
# -> [Memory(content='exponential growth', similarity=0.6..., ...), ...]
```

## Run

From the repository root, after creating the Python environment described in
the main README, install the database libraries:

```powershell
& ".\.venv\Scripts\python.exe" -m pip install -r backend/tidb/requirements.txt
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
```

Edit the existing root `.env` and fill its `TIDB_*` fields using TiDB Cloud's
Connect settings. Keep any Gemini and ElevenLabs keys already there.
Do not copy `backend/tidb/.env.example` over your existing `.env`:
that would erase the other settings. That example is a reference for the database fields.

Then run the demo or integration tests:

```powershell
& ".\.venv\Scripts\python.exe" -m backend.tidb.demo
& ".\.venv\Scripts\python.exe" -m pytest tests/tidb
& ".\.venv\Scripts\python.exe" -m unittest discover -s tests -p test_glossary_matching.py -v
```

Database integration tests skip without TiDB credentials. The demo creates a table,
adds temporary example memories, and deletes those example rows afterward.

Semantic suggestions first rank the stored phrase vectors, then confirm candidates
against their saved English source example using `EMBED_TEXT` and `VEC_COSINE_DISTANCE`.
If needed, the example is compared again with the term included. The provisional
thresholds are 0.15 for the phrase and 0.28 for its context; entries without an example
require phrase similarity of 0.30. Passing `min_similarity=None` returns diagnostic
rankings without these guards. There is no schema migration, and changing a saved
example affects the next search. Context checks add TiDB embedding work and latency.

## Files

- `client.py` – TLS connection to TiDB Cloud from `TIDB_*` env vars
- `schema.py` – `memories` table; `embedding` is a generated Auto Embedding column
- `store.py` – `MemoryStore` (`add_memory`, `search_relevant_memories`, `list_memories`, `delete_user_memories`)
- `demo.py` – the exponential-growth example, including a user-isolation check

Not yet: `feedback_events`, `save_feedback`, merging duplicate memories, strength/ranking.
