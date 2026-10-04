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

```bash
pip install -r backend/tidb/requirements.txt
cp backend/tidb/.env.example .env      # fill in from TiDB Cloud -> Connect
python -m backend.tidb.demo            # end-to-end check against TiDB Cloud
pytest tests/tidb                      # integration tests skip without credentials
```

## Files

- `client.py` – TLS connection to TiDB Cloud from `TIDB_*` env vars
- `schema.py` – `memories` table; `embedding` is a generated Auto Embedding column
- `store.py` – `MemoryStore` (`add_memory`, `search_relevant_memories`, `list_memories`, `delete_user_memories`)
- `demo.py` – the exponential-growth example, including a user-isolation check

Not yet: `feedback_events`, `save_feedback`, merging duplicate memories, strength/ranking.
