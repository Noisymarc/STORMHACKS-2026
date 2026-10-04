"""TiDB-backed personalized memory.

    from backend.tidb import MemoryStore

    store = MemoryStore.from_env()
    store.init_schema()
    store.add_memory("user-1", "exponential growth", context="...")
    store.search_relevant_memories("user-1", "Users are growing exponentially.")
"""
from .store import Memory, MemoryStore

__all__ = ["Memory", "MemoryStore"]
