"""Evaluate stage 2: can Gemini tell whether an utterance really uses a saved concept?

    python -m scripts.eval_need                 # needs GEMINI_API_KEY in the repo-root .env
    python -m scripts.eval_need --repeat 2      # run each case twice to check stability

The product only records what a student did NOT understand (phrases they asked
to have explained). Stage 1 (TiDB semantic search) finds glossary entries that
are close in meaning to the current sentence, but it also lets through sentences
that merely share words or a related topic. Stage 2 asks Gemini, for each
candidate, whether the utterance actually uses or paraphrases that concept and
which words express it. The prompt and request settings are imported from
backend/concept_judge.py, so this measures exactly what the app sends.
Uses Gemini only (no TiDB).

Requests are spaced --gap seconds apart (default 5 s, under the 15/min free-tier
cap noted in backend/live_app.py). 22 cases ~ 2 minutes per repeat.
"""
import argparse
import json
import os
import statistics
import time
from pathlib import Path

from dotenv import load_dotenv
from google import genai

from backend.concept_judge import build_payload, request_config

DEFAULT_MODEL = "gemini-3.1-flash-lite"  # same as backend/live_app.py GEMINI_MODEL

# The glossary: phrase and the sentence where the student first asked about it.
GLOSSARY = {
    "exp": ("exponential growth", "Our revenue shows exponential growth this year."),
    "lat": ("latency", "We measured the latency of every request."),
    "ovf": ("overfitting", "Our model is overfitting the training data."),
    "pho": ("photosynthesis", "Photosynthesis happens in the chloroplasts."),
    "sup": ("supply and demand", "Prices depend on supply and demand."),
    "rec": ("recursion", "This function uses recursion to walk the tree."),
    "std": ("standard deviation", "Compute the standard deviation of the scores."),
}

# (case name, utterance, [(memory_id, expected same_concept)])
# Candidates are what stage 1 let through (sentence query, threshold 0.12, see eval_search).
CASES = [
    ("paraphrase", "The number of users is growing exponentially.", [("exp", True)]),
    ("far paraphrase", "The bacteria population doubles every twenty minutes.", [("exp", True)]),
    ("far paraphrase", "Each step multiplies the total by the same factor, so it explodes quickly.", [("exp", True)]),
    ("different concept", "The response time doubled after the update.", [("exp", False)]),
    ("paraphrase", "The response time got much worse after the update.", [("lat", True)]),
    ("far paraphrase", "There is a delay between clicking and seeing the result.", [("lat", True)]),
    ("shared word, other sense", "The train arrived late this morning.", [("lat", False)]),
    ("paraphrase", "It memorized the training set and fails on new examples.", [("ovf", True)]),
    ("far paraphrase", "Training accuracy is high but test accuracy is poor.", [("ovf", True)]),
    ("shared word, other sense", "The jacket fits too tightly around the shoulders.", [("ovf", False)]),
    ("paraphrase", "Plants turn sunlight into chemical energy.", [("pho", True)]),
    ("far paraphrase", "Leaves absorb carbon dioxide and release oxygen.", [("pho", True)]),
    ("related topic", "Solar panels convert light into electricity.", [("pho", False)]),
    ("paraphrase", "When fewer tickets are available, people pay more for them.", [("sup", True)]),
    ("shared words, other sense", "Please supply your student ID when you demand a refund.", [("sup", False)]),
    ("paraphrase", "The function calls itself until it reaches the base case.", [("rec", True)]),
    ("related topic", "Mirrors facing each other create an endless tunnel of reflections.", [("rec", False)]),
    ("paraphrase", "How spread out are the values around the average?", [("std", True)]),
    ("shared words, idiom", "He deviated from the standard procedure.", [("std", False)]),
    ("exact term + unrelated", "We measured the latency of every request.", [("lat", True), ("exp", False)]),
    ("mixed candidates", "When fewer tickets are available people pay more, and the train arrived late.",
     [("sup", True), ("lat", False)]),
    ("two real concepts", "Prices settle where buyers and sellers agree, and they are spread far from the average.",
     [("sup", True), ("std", True)]),
]


def judge(client, model, utterance, memory_ids):
    """Same prompt and request settings as the app (backend/concept_judge.py)."""
    payload = build_payload(utterance, [(m, GLOSSARY[m][0], GLOSSARY[m][1]) for m in memory_ids])
    start = time.perf_counter()
    response = client.models.generate_content(model=model, contents=payload, config=request_config())
    elapsed = time.perf_counter() - start
    usage = response.usage_metadata
    tokens = (getattr(usage, "prompt_token_count", None) or 0,
              getattr(usage, "candidates_token_count", None) or 0)
    items = json.loads(response.text or "")["items"]
    return {item["memory_id"]: item for item in items}, elapsed, tokens


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--repeat", type=int, default=1, help="runs per case (stability check)")
    parser.add_argument("--gap", type=float, default=5.0, help="seconds between requests")
    args = parser.parse_args()

    load_dotenv(Path(__file__).resolve().parents[1] / ".env", override=False)
    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    if not api_key:
        raise SystemExit("Set GEMINI_API_KEY in the repo-root .env")
    client = genai.Client(api_key=api_key)

    # results[(case index, memory_id)] = list of (same_concept, expression, reason) per run
    results, failures, latencies, prompt_tokens, output_tokens = {}, [], [], [], []
    total = len(CASES) * args.repeat
    print(f"Model {args.model}: {total} requests, {args.gap:.0f}s apart\n")
    for run in range(args.repeat):
        for i, (name, utterance, candidates) in enumerate(CASES):
            if latencies or failures:
                time.sleep(args.gap)
            print(f"  [{run * len(CASES) + i + 1}/{total}] {name}", flush=True)
            memory_ids = [m for m, _ in candidates]
            try:
                items, elapsed, (p_tok, o_tok) = judge(client, args.model, utterance, memory_ids)
            except Exception as exc:  # report and keep going
                failures.append(f"run {run + 1} case {i} ({name}): {type(exc).__name__}: {str(exc)[:120]}")
                continue
            latencies.append(elapsed)
            prompt_tokens.append(p_tok)
            output_tokens.append(o_tok)
            for m in memory_ids:
                item = items.get(m)
                if item is None:
                    failures.append(f"run {run + 1} case {i} ({name}): no item for {m}")
                    continue
                results.setdefault((i, m), []).append(
                    (bool(item["same_concept"]), item["expression"].strip(), item["reason"]))

    print(f"\n{'#':>2} {'case':26} {'memory':18} {'exp':3} {'got':5} ok  expression / reason (last run)")
    counts = {"tp": 0, "missed": 0, "tn": 0, "false_accept": 0}
    expr_ok = expr_checked = 0
    for i, (name, utterance, candidates) in enumerate(CASES):
        for m, expected in candidates:
            runs = results.get((i, m), [])
            phrase = GLOSSARY[m][0]
            if not runs:
                print(f"{i:>2} {name:26} {phrase:18} {'T' if expected else 'F':3} (no result)")
                continue
            for same, expression, _ in runs:
                key = ("tp" if same else "missed") if expected else ("false_accept" if same else "tn")
                counts[key] += 1
                if expected and same:
                    expr_checked += 1
                    expr_ok += bool(expression) and expression.lower() in utterance.lower()
            got = ",".join("T" if s else "F" for s, _, _ in runs)
            ok = all(s == expected for s, _, _ in runs)
            last_same, last_expr, last_reason = runs[-1]
            detail = f'"{last_expr}"' if last_same else last_reason
            print(f"{i:>2} {name:26} {phrase:18} {'T' if expected else 'F':3} {got:5} "
                  f"{'✅' if ok else '❌'}  {detail[:70]}")

    should, should_not = counts["tp"] + counts["missed"], counts["tn"] + counts["false_accept"]
    print(f"\nSame concept found:     {counts['tp']}/{should}   (missed {counts['missed']})")
    print(f"Wrong match rejected:   {counts['tn']}/{should_not}   (accepted by mistake {counts['false_accept']})")
    print(f"Expression found in utterance: {expr_ok}/{expr_checked}")
    if args.repeat > 1:
        unstable = [k for k, r in results.items() if len({s for s, _, _ in r}) > 1]
        print(f"Unstable judgements across runs: {len(unstable)}")
    if latencies:
        print(f"Latency: median {statistics.median(latencies):.2f}s, max {max(latencies):.2f}s "
              f"over {len(latencies)} requests")
        print(f"Tokens per request: prompt ~{statistics.mean(prompt_tokens):.0f}, "
              f"output ~{statistics.mean(output_tokens):.0f}")
    print(f"Failures (errors / missing items / bad JSON): {len(failures)}")
    for f in failures:
        print(f"  - {f}")


if __name__ == "__main__":
    main()
