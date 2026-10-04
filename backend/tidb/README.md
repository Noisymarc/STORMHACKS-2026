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
```

Database integration tests skip without TiDB credentials. The demo creates a table,
adds temporary example memories, and deletes those example rows afterward.

## Dictionary file: copy the saved phrases to another device

The saved phrases (the `memories` table) can be written to a plain `.txt` "dictionary" file and
imported somewhere else, to give another device or database the same phrases.

**In the browser** (page section *Remembered help* → *Dictionary file*):

- **Download dictionary (.txt)** saves this browser's phrases.
- **Import dictionary file** adds the phrases in a file to *this browser's* saved phrases. Phrases
  already saved (same phrase, context and language) are skipped, so importing twice is harmless.
  A file with any problem is refused with the line number and nothing is imported.
  Browser imports are limited to 200 phrases / 1 MB; use the command line for bigger files.

Each browser has its own random user id, so a phrase file has to be *imported* on the other device
(that gives the entries to that browser). Pointing two devices at the same TiDB cluster does not
make them share phrases by itself.

**On the command line** (from the repository root; uses the `TIDB_*` settings in `.env`):

```powershell
& ".\.venv\Scripts\python.exe" -m backend.tidb.dictionary export --list-users
& ".\.venv\Scripts\python.exe" -m backend.tidb.dictionary export --user-id <uuid> -o dictionary.txt
& ".\.venv\Scripts\python.exe" -m backend.tidb.dictionary export --all -o everything.txt
& ".\.venv\Scripts\python.exe" -m backend.tidb.dictionary import dictionary.txt --dry-run
& ".\.venv\Scripts\python.exe" -m backend.tidb.dictionary import dictionary.txt
& ".\.venv\Scripts\python.exe" -m backend.tidb.dictionary import dictionary.txt --user-id <uuid>
```

Without `--user-id`, import keeps the owner written in each entry (use this to rebuild a whole
database from `--all`); with it, every entry is given to that user. `--skip-invalid` imports the
good lines of a file that has bad ones. The import is a single transaction: it either adds
everything or nothing.

**File format.** UTF-8 text. The first line is `# STORMHACKS-DICTIONARY v1`; lines starting
with `#` and blank lines are ignored; every other line is one JSON entry (so any character,
including a newline inside a value, survives), for example:

```text
# STORMHACKS-DICTIONARY v1
# exported: 2026-10-04T05:12:00Z
# entries: 1
{"user_id": "...", "phrase": "exponential growth", "context": "Revenue shows exponential growth.", "explanation": "Growth that speeds up.", "kind": "not_understood", "source_lang": "en", "target_lang": "ja", "metadata": {"language": "Japanese"}, "saved_at": "2026-10-04T05:10:00.123456"}
```

Only `phrase` is required. What is copied: the text fields, languages, metadata and the original
save time. What is not: the embedding (TiDB generates it again from the phrase, so semantic search
works on imported rows), the row id (new ids are assigned) and `status` (imported rows are active).
The file contains the user's phrases and the lecture sentences around them: treat it as personal data.

## Files

- `client.py` – TLS connection to TiDB Cloud from `TIDB_*` env vars
- `schema.py` – `memories` table; `embedding` is a generated Auto Embedding column
- `store.py` – `MemoryStore` (`add_memory`, `search_relevant_memories`, `list_memories`, `delete_user_memories`)
- `demo.py` – the exponential-growth example, including a user-isolation check
- `dictionary.py` – export/import of the saved phrases as a text file (also a command-line tool)

Not yet: `feedback_events`, `save_feedback`, merging duplicate memories, strength/ranking.
