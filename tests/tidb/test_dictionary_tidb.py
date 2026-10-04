"""Dictionary export/import against a real TiDB Cloud Starter cluster.

Skipped unless TIDB_HOST / TIDB_USER / TIDB_PASSWORD are set. Uses throwaway users and deletes their
rows afterwards. This covers what the SQLite tests in tests/test_dictionary.py cannot: TiDB generating
embeddings for bulk-inserted rows, DATETIME(6) timestamps and the JSON column.
"""
import os
import uuid

import pytest

from backend.tidb import MemoryStore, dictionary

needs_tidb = pytest.mark.skipif(
    not all(os.getenv(k) for k in ("TIDB_HOST", "TIDB_USER", "TIDB_PASSWORD")),
    reason="TiDB Cloud credentials not set",
)


@pytest.fixture
def store():
    s = MemoryStore.from_env()
    s.init_schema()
    return s


@pytest.fixture
def users(store):
    run = uuid.uuid4().hex[:8]
    ids = (f"test-dict-a-{run}", f"test-dict-b-{run}")
    yield ids
    for u in ids:
        store.delete_user_memories(u)


def fields(memories):
    return [(m.content, m.context, m.note, m.source_lang, m.target_lang, m.metadata, m.created_at)
            for m in memories]


@needs_tidb
def test_round_trip_to_another_user_keeps_every_field_and_search_still_works(store, users):
    alice, bob = users
    store.add_memory(alice, "exponential growth", context="Revenue shows exponential growth.\nIt doubles.",
                     note="Growth that speeds up.", source_lang="en", target_lang="ja",
                     metadata={"language": "Japanese"})
    store.add_memory(alice, "指数関数的成長", context="売上は「指数関数的成長」を示す。", note="説明、🙂",
                     source_lang="ja", target_lang="en", metadata={"language": "English"})
    store.add_memory(alice, "photosynthesis")
    original = fields(store.list_memories(alice))

    exported = dictionary.export_dictionary(store, alice)
    result = dictionary.import_dictionary(store, exported, user_id=bob)

    assert (result.added, result.skipped_duplicates) == (3, 0)
    assert fields(store.list_memories(bob)) == original              # text, JSON and DATETIME(6) all identical
    # TiDB generated the embeddings for the imported rows itself, so semantic search works
    hits = store.search_relevant_memories(bob, "The number of users is growing exponentially.",
                                          limit=3, min_similarity=None)
    assert hits and hits[0].content in ("exponential growth", "指数関数的成長")
    # idempotent
    again = dictionary.import_dictionary(store, exported, user_id=bob)
    assert (again.added, again.skipped_duplicates) == (0, 3)


@needs_tidb
def test_restoring_to_the_original_owner_after_the_data_is_gone(store, users):
    alice, _ = users
    store.add_memory(alice, "latency", context="The API latency went up.", note="Delay.", target_lang="ja")
    original = fields(store.list_memories(alice))
    exported = dictionary.export_dictionary(store, alice)

    store.delete_user_memories(alice)                                # a new, empty database
    assert store.list_memories(alice) == []
    result = dictionary.import_dictionary(store, exported)           # owners come from the file
    assert result.added == 1
    assert fields(store.list_memories(alice)) == original
