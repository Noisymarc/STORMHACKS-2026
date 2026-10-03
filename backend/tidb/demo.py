"""End-to-end check against a real TiDB Cloud Starter cluster.

    python -m backend.tidb.demo            # creates the table, runs, cleans up
    python -m backend.tidb.demo --keep     # leave the demo rows in place

Stores memories for two users, then searches with a transcript that shares no
exact wording with the stored memory, and shows that only the target user's
memories come back.
"""
import argparse
import uuid

from . import MemoryStore

ALICE_MEMORIES = [
    ("exponential growth", "Our revenue shows exponential growth."),
    ("compound interest", "Savings grow faster with compound interest."),
    ("photosynthesis", "Plants make energy through photosynthesis."),
    ("latency", "The API latency went up after the deploy."),
]
BOB_MEMORIES = [
    ("growing exponentially", "The virus is growing exponentially."),
]
TRANSCRIPT = "The number of users is growing exponentially."


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--keep", action="store_true", help="do not delete demo rows")
    args = parser.parse_args()

    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass

    store = MemoryStore.from_env()
    store.init_schema()

    run = uuid.uuid4().hex[:8]
    alice, bob = f"demo-alice-{run}", f"demo-bob-{run}"
    try:
        for content, context in ALICE_MEMORIES:
            store.add_memory(alice, content, context=context)
        for content, context in BOB_MEMORIES:
            store.add_memory(bob, content, context=context)

        print(f"Transcript: {TRANSCRIPT!r}")
        print(f"Relevant memories for {alice}:")
        results = store.search_relevant_memories(alice, TRANSCRIPT, limit=5)
        for m in results:
            print(f"  {m.similarity:.3f}  {m.content!r}  (user={m.user_id})")

        assert results, "no memories returned"
        assert all(m.user_id == alice for m in results), "another user's memory leaked"
        assert results[0].content == "exponential growth", "top hit is not the related memory"
        print("OK: related memory ranked first, only the target user's memories returned.")
    finally:
        if not args.keep:
            store.delete_user_memories(alice)
            store.delete_user_memories(bob)


if __name__ == "__main__":
    main()
