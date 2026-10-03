"""Integration tests for backend.tidb against a real TiDB Cloud Starter (AWS).

Skipped unless TIDB_HOST / TIDB_USER / TIDB_PASSWORD are set.
"""
import os
import uuid

import pytest
from sqlalchemy import create_engine

from backend.tidb import MemoryStore


def test_user_id_is_required_without_touching_the_db():
    # create_engine is lazy, so nothing connects here.
    store = MemoryStore(create_engine("mysql+pymysql://u:p@127.0.0.1:1/db"))
    with pytest.raises(ValueError):
        store.search_relevant_memories("", "anything")
    with pytest.raises(ValueError):
        store.add_memory(" ", "exponential growth")
    with pytest.raises(ValueError):
        store.add_memory("user", "")


def test_blank_transcript_returns_nothing_without_touching_the_db():
    store = MemoryStore(create_engine("mysql+pymysql://u:p@127.0.0.1:1/db"))
    assert store.search_relevant_memories("user", "   ") == []


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
    ids = (f"test-a-{run}", f"test-b-{run}")
    yield ids
    for u in ids:
        store.delete_user_memories(u)


@needs_tidb
def test_semantic_search_finds_related_memory(store, users):
    alice, _ = users
    store.add_memory(alice, "exponential growth", context="Revenue shows exponential growth.")
    store.add_memory(alice, "photosynthesis")
    store.add_memory(alice, "latency")

    results = store.search_relevant_memories(
        alice, "The number of users is growing exponentially.", limit=3, min_similarity=None)

    assert results[0].content == "exponential growth"
    assert results[0].similarity > results[-1].similarity


@needs_tidb
def test_default_threshold_drops_unrelated_memories(store, users):
    alice, _ = users
    store.add_memory(alice, "exponential growth")
    store.add_memory(alice, "photosynthesis")
    store.add_memory(alice, "latency")

    results = store.search_relevant_memories(
        alice, "The number of users is growing exponentially.")

    assert [m.content for m in results] == ["exponential growth"]


@needs_tidb
def test_search_is_limited_to_the_user(store, users):
    alice, bob = users
    store.add_memory(alice, "photosynthesis")
    store.add_memory(bob, "exponential growth")

    results = store.search_relevant_memories(
        alice, "The number of users is growing exponentially.")

    assert [m.user_id for m in results] == [alice]


@needs_tidb
def test_add_and_list_round_trip(store, users):
    alice, _ = users
    store.add_memory(alice, "compound interest", note="interest on interest",
                     source_lang="en", target_lang="ja", metadata={"level": 2})

    [m] = store.list_memories(alice)
    assert (m.content, m.note, m.metadata) == ("compound interest", "interest on interest", {"level": 2})
