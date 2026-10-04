"""Concept check and search filtering, with fake Gemini and TiDB (no network)."""
import asyncio
import json
import types
import uuid

import pytest

from backend import concept_judge as cj
from backend import memory_api
from backend.tidb.store import Memory


class FakeGemini:
    """client.aio.models.generate_content returning canned items."""

    def __init__(self, verdicts=None, error=None):
        self.verdicts = verdicts or {}
        self.error = error
        self.calls = []
        self.aio = types.SimpleNamespace(models=self)

    async def generate_content(self, model, contents, config):
        self.calls.append(json.loads(contents))
        if self.error:
            raise self.error
        items = [{"memory_id": c["memory_id"], "same_concept": self.verdicts[c["memory_id"]][0],
                  "expression": self.verdicts[c["memory_id"]][1], "reason": "test"}
                 for c in self.calls[-1]["candidates"]]
        return types.SimpleNamespace(text=json.dumps({"items": items}))


def make_judge(client):
    judge = cj.ConceptJudge()
    judge.configure(client, "test-model")
    return judge


@pytest.fixture(autouse=True)
def judge_env(monkeypatch):
    for key in ("CONCEPT_JUDGE", "CONCEPT_JUDGE_PER_MINUTE", "CONCEPT_JUDGE_DAILY_LIMIT"):
        monkeypatch.delenv(key, raising=False)


UTTERANCE = "The number of users is growing exponentially."
CANDIDATES = [("1", "exponential growth", "Revenue shows exponential growth."),
              ("2", "latency", "We measured the latency.")]


def test_parse_keeps_only_expressions_found_in_the_utterance():
    text = json.dumps({"items": [
        {"memory_id": "1", "same_concept": True, "expression": "GROWING exponentially", "reason": ""},
        {"memory_id": "2", "same_concept": True, "expression": "invented words", "reason": ""},
    ]})
    assert cj.parse_items(text, UTTERANCE, ["1", "2"]) == {
        "1": (True, "GROWING exponentially"), "2": (True, "")}


def test_parse_rejects_missing_judgements():
    text = json.dumps({"items": [{"memory_id": "1", "same_concept": True, "expression": "", "reason": ""}]})
    with pytest.raises(ValueError):
        cj.parse_items(text, UTTERANCE, ["1", "2"])


def test_saved_sentence_is_trimmed_around_the_phrase():
    context = "x" * 1000 + " exponential growth " + "y" * 1000
    trimmed = cj.saved_sentence("exponential growth", context)
    assert len(trimmed) == cj.SAVED_SENTENCE_CHARS and "exponential growth" in trimmed


def test_judge_returns_verdicts_and_caches_them():
    client = FakeGemini({"1": (True, "growing exponentially"), "2": (False, "")})
    judge = make_judge(client)
    first = asyncio.run(judge.judge(UTTERANCE, CANDIDATES))
    second = asyncio.run(judge.judge(UTTERANCE, CANDIDATES))
    assert first == second == {"1": (True, "growing exponentially"), "2": (False, "")}
    assert len(client.calls) == 1


def test_growing_sentence_reuses_earlier_verdicts():
    client = FakeGemini({"1": (True, "growing exponentially"), "2": (False, "")})
    judge = make_judge(client)
    asyncio.run(judge.judge("The number of users is growing exponentially", CANDIDATES))
    longer = asyncio.run(judge.judge("The number of users is growing exponentially this", CANDIDATES))
    assert longer == {"1": (True, "growing exponentially"), "2": (False, "")}
    assert len(client.calls) == 1
    # Much later in the same sentence, only the earlier rejection is checked again.
    asyncio.run(judge.judge("The number of users is growing exponentially this year, "
                            "and the delay before each page loads keeps rising", CANDIDATES))
    assert len(client.calls) == 2
    assert [c["memory_id"] for c in client.calls[1]["candidates"]] == ["2"]


def test_judge_can_be_switched_off(monkeypatch):
    monkeypatch.setenv("CONCEPT_JUDGE", "off")
    client = FakeGemini({"1": (True, "")})
    assert asyncio.run(make_judge(client).judge(UTTERANCE, CANDIDATES[:1])) is None
    assert client.calls == []


def test_judge_respects_per_minute_and_daily_limits(monkeypatch):
    monkeypatch.setenv("CONCEPT_JUDGE_PER_MINUTE", "2")
    client = FakeGemini({"1": (True, "")})
    judge = make_judge(client)
    results = [asyncio.run(judge.judge(f"sentence {i}", CANDIDATES[:1])) for i in range(3)]
    assert results[2] is None and len(client.calls) == 2

    monkeypatch.setenv("CONCEPT_JUDGE_PER_MINUTE", "100")
    monkeypatch.setenv("CONCEPT_JUDGE_DAILY_LIMIT", "1")
    judge = make_judge(FakeGemini({"1": (True, "")}))
    assert asyncio.run(judge.judge("a", CANDIDATES[:1])) is not None
    assert asyncio.run(judge.judge("b", CANDIDATES[:1])) is None


def test_rate_limit_error_pauses_requests():
    error = Exception("quota")
    error.code = 429
    client = FakeGemini(error=error)
    judge = make_judge(client)
    assert asyncio.run(judge.judge("a", CANDIDATES[:1])) is None
    client.error = None
    client.verdicts = {"1": (True, "")}
    assert asyncio.run(judge.judge("b", CANDIDATES[:1])) is None
    assert len(client.calls) == 1


def memory(memory_id, phrase, similarity):
    return Memory(id=memory_id, user_id="u", kind="not_understood", content=phrase, context=phrase,
                  note="説明", source_lang="en", target_lang="ja", metadata={"language": "Japanese"},
                  created_at=None, similarity=similarity)


class FakeStore:
    def __init__(self, memories):
        self.memories = memories
        self.min_similarity = None

    def search_relevant_memories(self, user_id, transcript, *, limit, target_lang, min_similarity):
        self.min_similarity = min_similarity
        return [m for m in self.memories if m.similarity >= min_similarity][:limit]


class FakeJudge:
    def __init__(self, verdicts):
        self.verdicts = verdicts

    async def judge(self, utterance, candidates):
        return self.verdicts


def search(monkeypatch, memories, verdicts):
    monkeypatch.setattr(memory_api, "store", FakeStore(memories))
    monkeypatch.setattr(memory_api, "concept_judge", FakeJudge(verdicts))
    request = memory_api.SearchMemory(user_id=uuid.uuid4(), transcript=UTTERANCE, language="Japanese")
    return asyncio.run(memory_api.search_saved(request))["memories"]


def test_search_keeps_confirmed_and_drops_rejected(monkeypatch):
    found = search(monkeypatch, [memory(1, "exponential growth", 0.13), memory(2, "latency", 0.30)],
                   {"1": (True, "growing exponentially"), "2": (False, "")})
    assert [(m["phrase"], m["confirmed"], m["expression"]) for m in found] == [
        ("exponential growth", True, "growing exponentially")]
    assert memory_api.store.min_similarity == memory_api.CANDIDATE_SIMILARITY


def test_search_without_check_shows_only_closer_matches_as_unconfirmed(monkeypatch):
    found = search(monkeypatch, [memory(1, "exponential growth", 0.13), memory(2, "latency", 0.30)], None)
    assert [(m["phrase"], m["confirmed"]) for m in found] == [("latency", None)]


def test_help_fades_but_never_stops():
    shown = [n for n in range(1, 40) if memory_api.help_due(n)]
    assert shown == [1, 2, 4, 8, 16, 32]


class ExposureStore:
    def __init__(self):
        self.counts = {}
        self.resets = []

    def record_exposure(self, user_id, memory_id):
        if memory_id == 404:
            return None
        self.counts[memory_id] = self.counts.get(memory_id, 0) + 1
        return self.counts[memory_id]

    def reset_exposures(self, user_id, memory_id):
        self.resets.append(memory_id)
        self.counts.pop(memory_id, None)

    def list_memories(self, user_id):
        return [memory(7, "exponential growth", None)]

    def update_memory(self, *args, **kwargs):
        pass


def test_seen_counts_encounters_and_decides_help(monkeypatch):
    monkeypatch.setattr(memory_api, "store", ExposureStore())
    request = memory_api.SeenMemory(user_id=uuid.uuid4())
    replies = [asyncio.run(memory_api.seen_in_sentence("7", request)) for _ in range(4)]
    assert [(r["exposures"], r["show_help"]) for r in replies] == [(1, True), (2, True), (3, False), (4, True)]
    with pytest.raises(memory_api.HTTPException) as missing:
        asyncio.run(memory_api.seen_in_sentence("404", request))
    assert missing.value.status_code == 404


def test_asking_again_resets_the_count(monkeypatch):
    fake = ExposureStore()
    fake.counts[7] = 9
    monkeypatch.setattr(memory_api, "store", fake)
    request = memory_api.SaveMemory(user_id=uuid.uuid4(), phrase="exponential growth",
                                    context="exponential growth", explanation="説明", language="Japanese")
    assert asyncio.run(memory_api.save_phrase(request)) == {"id": "7"}
    assert fake.resets == [7] and 7 not in fake.counts
