"""/api/memories/export and /api/memories/import, through the real FastAPI app on a throwaway DB."""
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend import live_app, memory_api
from backend.tidb import MemoryStore, dictionary as d
from test_dictionary import SCHEMA, snapshot

ME = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
OTHER = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"


@pytest.fixture(autouse=True, scope="module")
def sqlite_datetimes():
    sqlite3.register_adapter(datetime, lambda v: v.isoformat(" "))
    sqlite3.register_converter("TIMESTAMP", lambda b: datetime.fromisoformat(b.decode()))


@pytest.fixture
def api(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'api.sqlite'}", connect_args={"detect_types": sqlite3.PARSE_DECLTYPES})
    with engine.begin() as conn:
        conn.execute(text(SCHEMA))
    store = MemoryStore(engine)
    store.add_memory(ME, "exponential growth", context="Revenue shows exponential growth.",
                     note="Growth that speeds up.", source_lang="en", target_lang="ja", metadata={"language": "Japanese"})
    store.add_memory(ME, "指数関数的成長", note="説明", metadata={"language": "Japanese"})
    store.add_memory(OTHER, "secret of someone else")
    monkeypatch.setattr(memory_api, "store", store)          # get_store() returns it as-is
    return TestClient(live_app.app), store


def test_export_is_a_downloadable_text_file_of_only_this_users_phrases(api):
    client, _ = api
    response = client.get("/api/memories/export", params={"user_id": ME})
    assert response.status_code == 200
    assert response.headers["content-type"] == "text/plain; charset=utf-8"
    assert response.headers["content-disposition"].startswith('attachment; filename="dictionary-')
    assert response.headers["content-disposition"].endswith('.txt"')
    assert response.headers["cache-control"] == "no-store"
    parsed = d.parse_dictionary(response.text)
    assert parsed.errors == [] and {e.phrase for e in parsed.entries} == {"exponential growth", "指数関数的成長"}
    assert "someone else" not in response.text                # another user's phrases never leak


def test_export_needs_a_valid_user_id(api):
    client, _ = api
    assert client.get("/api/memories/export").status_code == 422
    assert client.get("/api/memories/export", params={"user_id": "not-a-uuid"}).status_code == 422


def test_import_adds_phrases_to_the_requesting_user_not_the_original_owner(api, tmp_path):
    client, store = api
    exported = client.get("/api/memories/export", params={"user_id": ME}).text
    new_device = "cccccccc-cccc-4ccc-8ccc-cccccccccccc"
    result = client.post("/api/memories/import", json={"user_id": new_device, "text": exported})
    assert result.status_code == 200 and result.json() == {"added": 2, "skipped_duplicates": 0}
    assert [m.content for m in store.list_memories(new_device)] == ["exponential growth", "指数関数的成長"]
    assert len(store.list_memories(ME)) == 2                  # the original is untouched
    # the page lists them right away, and importing again changes nothing
    assert len(client.get("/api/memories", params={"user_id": new_device}).json()["memories"]) == 2
    again = client.post("/api/memories/import", json={"user_id": new_device, "text": exported})
    assert again.json() == {"added": 0, "skipped_duplicates": 2}


def test_import_ignores_the_owner_written_in_the_file(api):
    client, store = api
    body = '# STORMHACKS-DICTIONARY v1\n{"phrase": "planted", "user_id": "%s"}\n' % OTHER
    client.post("/api/memories/import", json={"user_id": ME, "text": body})
    assert "planted" in [m.content for m in store.list_memories(ME)]
    assert "planted" not in [m.content for m in store.list_memories(OTHER)]     # cannot write into another user


def test_bad_files_are_refused_with_a_readable_reason_and_nothing_is_written(api):
    client, store = api
    before = snapshot(store)
    cases = {
        "not a STORMHACKS-DICTIONARY file": "hello",
        "line 2: not valid JSON": '# STORMHACKS-DICTIONARY v1\nbroken\n',
        '"phrase" is required': '# STORMHACKS-DICTIONARY v1\n{"context": "x"}\n',
        "version 9": "# STORMHACKS-DICTIONARY v9\n",
    }
    for message, body in cases.items():
        response = client.post("/api/memories/import", json={"user_id": ME, "text": body})
        assert response.status_code == 422, message
        assert isinstance(response.json()["detail"], str) and message in response.json()["detail"]
        assert response.json()["detail"].startswith("Nothing was imported")
    assert snapshot(store) == before


def test_one_bad_line_among_good_ones_refuses_the_whole_file(api):
    client, store = api
    before = snapshot(store)
    body = '# STORMHACKS-DICTIONARY v1\n{"phrase": "good"}\nbroken\n'
    assert client.post("/api/memories/import", json={"user_id": ME, "text": body}).status_code == 422
    assert snapshot(store) == before


def test_the_browser_import_is_capped_and_points_to_the_command_line(api):
    client, store = api
    lines = "".join(f'{{"phrase": "p{i}"}}\n' for i in range(memory_api.MAX_IMPORT_ENTRIES + 1))
    response = client.post("/api/memories/import", json={"user_id": ME, "text": "# STORMHACKS-DICTIONARY v1\n" + lines})
    assert response.status_code == 422 and "python -m backend.tidb.dictionary import" in response.json()["detail"]
    assert len(store.list_memories(ME)) == 2
    ok = "".join(f'{{"phrase": "p{i}"}}\n' for i in range(memory_api.MAX_IMPORT_ENTRIES))
    assert client.post("/api/memories/import", json={"user_id": ME, "text": "# STORMHACKS-DICTIONARY v1\n" + ok}).json()["added"] == 200


def test_request_validation(api):
    client, _ = api
    assert client.post("/api/memories/import", json={"user_id": ME, "text": ""}).status_code == 422
    assert client.post("/api/memories/import", json={"user_id": "nope", "text": "x"}).status_code == 422
    too_big = "x" * (memory_api.MAX_IMPORT_CHARS + 1)
    assert client.post("/api/memories/import", json={"user_id": ME, "text": too_big}).status_code == 422


def test_database_trouble_becomes_the_usual_friendly_503(api, monkeypatch):
    client, _ = api

    def boom(*args, **kwargs):
        raise RuntimeError("password=secret")

    monkeypatch.setattr(d, "export_dictionary", boom)
    response = client.get("/api/memories/export", params={"user_id": ME})
    assert response.status_code == 503 and "Reference:" in response.json()["detail"] and "secret" not in response.text


def test_without_tidb_settings_the_endpoints_explain_what_to_add(monkeypatch):
    monkeypatch.setattr(memory_api, "store", None)
    for key in ("TIDB_HOST", "TIDB_USER", "TIDB_PASSWORD"):
        monkeypatch.delenv(key, raising=False)
    client = TestClient(live_app.app)
    r = client.get("/api/memories/export", params={"user_id": ME})
    assert r.status_code == 503 and "TIDB_HOST" in r.json()["detail"]
    r = client.post("/api/memories/import", json={"user_id": ME, "text": "# STORMHACKS-DICTIONARY v1\n{\"phrase\": \"x\"}\n"})
    assert r.status_code == 503 and "TIDB_HOST" in r.json()["detail"]


def test_existing_memory_endpoints_still_work(api):
    client, _ = api
    assert len(client.get("/api/memories", params={"user_id": ME}).json()["memories"]) == 2
    assert client.get("/api/memories/status").json()["configured"] is True
