"""Evaluate stage 1: does TiDB semantic search surface the right memory?

    python -m scripts.eval_search            # needs TIDB_* in the repo-root .env

Stores a fixed set of glossary phrases for a temporary user, then searches with
labelled lecture sentences in two query modes and prints, per threshold, how
many expected memories were found and how many false alarms appeared.
Query modes:
  sentence  - only the current sentence
  window600 - the last 600 characters of a running transcript, as
              frontend/live.html sends today (unrelated lecture text + sentence)
The temporary rows are deleted at the end. Uses TiDB only (no Gemini calls).
"""
import argparse
import statistics
import time
import uuid
from pathlib import Path

from dotenv import load_dotenv

from backend.tidb import MemoryStore

MEMORIES = [
    "exponential growth",
    "latency",
    "overfitting",
    "photosynthesis",
    "supply and demand",
    "recursion",
    "standard deviation",
]

# (sentence, memory it relates to or None, expected, category)
# expected: "yes" should surface, "no" should not surface, "maybe" = product decision.
CASES = [
    ("Our revenue shows exponential growth this year.", "exponential growth", "yes", "same term"),
    ("The number of users is growing exponentially.", "exponential growth", "yes", "paraphrase"),
    ("The bacteria population doubles every twenty minutes.", "exponential growth", "yes", "far paraphrase"),
    ("Each step multiplies the total by the same factor, so it explodes quickly.", "exponential growth", "yes", "far paraphrase"),
    ("Interest is added to the interest you already earned.", "exponential growth", "maybe", "related concept"),
    ("We measured the latency of every request.", "latency", "yes", "same term"),
    ("The response time got much worse after the update.", "latency", "yes", "paraphrase"),
    ("There is a delay between clicking and seeing the result.", "latency", "yes", "far paraphrase"),
    ("The train arrived late this morning.", "latency", "no", "tricky negative"),
    ("Our model is overfitting the training data.", "overfitting", "yes", "same term"),
    ("It memorized the training set and fails on new examples.", "overfitting", "yes", "paraphrase"),
    ("Training accuracy is high but test accuracy is poor.", "overfitting", "yes", "far paraphrase"),
    ("The jacket fits too tightly around the shoulders.", "overfitting", "no", "tricky negative"),
    ("Photosynthesis happens in the chloroplasts.", "photosynthesis", "yes", "same term"),
    ("Plants turn sunlight into chemical energy.", "photosynthesis", "yes", "paraphrase"),
    ("Leaves absorb carbon dioxide and release oxygen.", "photosynthesis", "yes", "far paraphrase"),
    ("Solar panels convert light into electricity.", "photosynthesis", "maybe", "related concept"),
    ("Prices depend on supply and demand.", "supply and demand", "yes", "same term"),
    ("When fewer tickets are available, people pay more for them.", "supply and demand", "yes", "paraphrase"),
    ("The market price settles where buyers and sellers agree.", "supply and demand", "yes", "far paraphrase"),
    ("Please supply your student ID when you demand a refund.", "supply and demand", "no", "tricky negative"),
    ("This function uses recursion to walk the tree.", "recursion", "yes", "same term"),
    ("The function calls itself until it reaches the base case.", "recursion", "yes", "paraphrase"),
    ("We solve the big problem by solving smaller copies of it.", "recursion", "yes", "far paraphrase"),
    ("Mirrors facing each other create an endless tunnel of reflections.", "recursion", "maybe", "related concept"),
    ("Compute the standard deviation of the scores.", "standard deviation", "yes", "same term"),
    ("How spread out are the values around the average?", "standard deviation", "yes", "paraphrase"),
    ("Most results fall within a narrow range of the mean.", "standard deviation", "yes", "far paraphrase"),
    ("He deviated from the standard procedure.", "standard deviation", "no", "tricky negative"),
    ("The weather is nice today.", None, "no", "unrelated"),
    ("Let's take a ten minute break.", None, "no", "unrelated"),
    ("Please submit your essays by Friday.", None, "no", "unrelated"),
    ("The museum opens at nine in the morning.", None, "no", "unrelated"),
    ("My favourite food is ramen.", None, "no", "unrelated"),
    ("Can everyone in the back hear me clearly?", None, "no", "unrelated"),
    ("The novel was written in the nineteenth century.", None, "no", "unrelated"),
]

# Neutral lecture chatter used to pad the window600 query. It must not relate
# to any memory above.
FILLER = (
    "Good morning everyone, thanks for coming today. Before we start, a quick note "
    "about the course: the reading list is on the website and office hours are on "
    "Tuesdays in room two hundred. If you missed last week, the slides are posted. "
    "Please put your phones on silent and grab a handout from the front table. "
    "Some of you asked about the group project, so I will talk about teams at the end. "
    "The library also has extra copies of the textbook if you need one. "
    "Okay, let's get going with today's topic. "
)

THRESHOLDS = [0.05, 0.08, 0.10, 0.12, 0.15, 0.20, 0.25, 0.30]
MODES = ["sentence", "window600"]


def query_for(mode: str, sentence: str) -> str:
    if mode == "sentence":
        return sentence
    # frontend/live.html: sourceText.slice(-600)
    return (FILLER * 3 + sentence)[-600:]


def run(store: MemoryStore, user_id: str) -> tuple[dict, list[float]]:
    """{(case index, mode): {memory phrase: similarity}} and per-search latencies."""
    scores, latencies = {}, []
    for i, (sentence, _, _, _) in enumerate(CASES):
        for mode in MODES:
            start = time.perf_counter()
            found = store.search_relevant_memories(
                user_id, query_for(mode, sentence), limit=len(MEMORIES), min_similarity=None)
            latencies.append(time.perf_counter() - start)
            scores[(i, mode)] = {m.content: m.similarity for m in found}
    return scores, latencies


def report(scores: dict, latencies: list[float]) -> None:
    print("\n## Per case (similarity of the related memory / best other memory)")
    print(f"{'#':>2} {'exp':5} {'category':16} {'sentence':>9} {'window600':>9}  sentence text")
    for i, (sentence, memory, expected, category) in enumerate(CASES):
        cells = []
        for mode in MODES:
            sims = scores[(i, mode)]
            target = sims.get(memory) if memory else None
            other = max((s for m, s in sims.items() if m != memory), default=0.0)
            cells.append(f"{target:.3f}/{other:.3f}" if target is not None else f"  -  /{other:.3f}")
        print(f"{i:>2} {expected:5} {category:16} {cells[0]:>11} {cells[1]:>11}  {sentence[:60]}")

    yes = [i for i, c in enumerate(CASES) if c[2] == "yes"]
    no = [i for i, c in enumerate(CASES) if c[2] == "no"]
    print(f"\n## By threshold ({len(yes)} should-surface, {len(no)} should-not-surface)")
    print("found    = should-surface cases whose related memory is >= threshold")
    print("top1     = ...and that memory is also the closest one")
    print("false    = should-not-surface cases where any memory is >= threshold")
    print("wrongmem = should-surface cases where some other memory is >= threshold")
    for mode in MODES:
        print(f"\n[{mode}]")
        print(f"{'thr':>5} {'found':>7} {'top1':>7} {'false':>7} {'wrongmem':>9}")
        for t in THRESHOLDS:
            found = top1 = wrong = 0
            for i in yes:
                sims = scores[(i, mode)]
                memory = CASES[i][1]
                if sims.get(memory, 0.0) >= t:
                    found += 1
                    if max(sims, key=sims.get) == memory:
                        top1 += 1
                if any(s >= t for m, s in sims.items() if m != memory):
                    wrong += 1
            false = sum(1 for i in no if any(s >= t for s in scores[(i, mode)].values()))
            print(f"{t:>5.2f} {found:>3}/{len(yes):<3} {top1:>3}/{len(yes):<3} "
                  f"{false:>3}/{len(no):<3} {wrong:>4}/{len(yes):<4}")

    print("\n## Separation per mode (related memory similarity)")
    for mode in MODES:
        pos = [scores[(i, mode)].get(CASES[i][1], 0.0) for i in yes]
        neg = [max(scores[(i, mode)].values(), default=0.0) for i in no]
        print(f"[{mode}] should-surface min/median {min(pos):.3f}/{statistics.median(pos):.3f}"
              f"  |  should-not-surface max/median {max(neg):.3f}/{statistics.median(neg):.3f}")

    ms = sorted(x * 1000 for x in latencies)
    print(f"\n## Search latency: median {statistics.median(ms):.0f} ms, "
          f"p90 {ms[int(len(ms) * 0.9) - 1]:.0f} ms over {len(ms)} searches")


def main() -> None:
    argparse.ArgumentParser(description=__doc__,
                            formatter_class=argparse.RawDescriptionHelpFormatter).parse_args()
    load_dotenv(Path(__file__).resolve().parents[1] / ".env", override=False)
    store = MemoryStore.from_env()
    store.init_schema()
    user_id = f"eval-search-{uuid.uuid4().hex[:8]}"
    try:
        for phrase in MEMORIES:
            store.add_memory(user_id, phrase, kind="not_understood")
        print(f"Stored {len(MEMORIES)} memories for {user_id}; "
              f"running {len(CASES) * len(MODES)} searches...")
        scores, latencies = run(store, user_id)
        report(scores, latencies)
    finally:
        store.delete_user_memories(user_id)


if __name__ == "__main__":
    main()
