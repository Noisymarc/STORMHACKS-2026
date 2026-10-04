"""Dictionary export/import (backend/tidb/dictionary.py).

These run against throwaway SQLite files: every query the dictionary code issues is plain SQL.
(TiDB's generated vector column is not needed for copying text.) tests/tidb/test_dictionary_tidb.py
repeats the round trip against a real TiDB Cloud cluster when credentials are set.
"""
import json
import sqlite3
import sys
import uuid
from datetime import datetime
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.tidb import MemoryStore, dictionary as d

SCHEMA = """
CREATE TABLE memories (
    id INTEGER PRIMARY KEY AUTOINCREMENT, user_id VARCHAR(64) NOT NULL, kind VARCHAR(32) NOT NULL,
    content TEXT NOT NULL, context TEXT, note TEXT, source_lang VARCHAR(16), target_lang VARCHAR(16),
    metadata TEXT, status VARCHAR(16) NOT NULL DEFAULT 'active',
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CHECK (content <> 'bad')            -- lets a test make one row of a batch fail
)"""


@pytest.fixture(autouse=True, scope="module")
def sqlite_datetimes():
    sqlite3.register_adapter(datetime, lambda v: v.isoformat(" "))
    sqlite3.register_converter("TIMESTAMP", lambda b: datetime.fromisoformat(b.decode()))


def make_store(tmp_path, name="db.sqlite") -> MemoryStore:
    engine = create_engine(f"sqlite:///{tmp_path / name}", connect_args={"detect_types": sqlite3.PARSE_DECLTYPES})
    with engine.begin() as conn:
        conn.execute(text(SCHEMA))
    return MemoryStore(engine)


def snapshot(store):
    """Everything that makes two databases 'the same' (ids differ by design)."""
    rows = []
    for user in d.all_user_ids(store):
        for m in store.list_memories(user):
            rows.append((m.user_id, m.kind, m.content, m.context, m.note, m.source_lang, m.target_lang,
                         json.dumps(m.metadata, sort_keys=True), m.created_at))
    return sorted(rows, key=lambda r: (r[0], r[8], r[2]))


ALICE, BOB = "11111111-1111-4111-8111-111111111111", "22222222-2222-4222-8222-222222222222"


@pytest.fixture
def source(tmp_path):
    """A database with awkward but realistic content, as the app itself would have written it."""
    store = make_store(tmp_path, "source.sqlite")
    store.add_memory(ALICE, "exponential growth", context="Revenue shows exponential growth.\nIt doubles.",
                     note="Growth that speeds up as the amount gets bigger.", source_lang="en", target_lang="ja",
                     metadata={"language": "Japanese"})
    store.add_memory(ALICE, "指数関数的成長", context="売上は「指数関数的成長」を示す。", note='説明: "速くなる"、🙂',
                     source_lang="ja", target_lang="en", metadata={"language": "English"})
    store.add_memory(ALICE, "latency")                                  # only the required field
    store.add_memory(BOB, "photosynthesis", context="Plants make energy.", note="Light into sugar.",
                     target_lang="fr", metadata={"language": "French"})
    with store.engine.begin() as conn:                                    # distinct, known times
        for i, content in enumerate(["exponential growth", "指数関数的成長", "latency", "photosynthesis"]):
            conn.execute(text("UPDATE memories SET created_at = :t WHERE content = :c"),
                         {"t": datetime(2026, 10, 1, 12, 0, 0, 123456 + i), "c": content})
    return store


# ---- the file format -----------------------------------------------------------------------
def test_format_round_trips_through_the_parser(source):
    parsed = d.parse_dictionary(d.export_dictionary(source))
    assert parsed.errors == [] and not parsed.fatal
    by_phrase = {e.phrase: e for e in parsed.entries}
    assert set(by_phrase) == {"exponential growth", "指数関数的成長", "latency", "photosynthesis"}
    e = by_phrase["exponential growth"]
    assert e.context == "Revenue shows exponential growth.\nIt doubles."      # newline survived
    assert e.explanation == "Growth that speeds up as the amount gets bigger."
    assert (e.user_id, e.source_lang, e.target_lang, e.metadata) == (ALICE, "en", "ja", {"language": "Japanese"})
    assert e.saved_at == datetime(2026, 10, 1, 12, 0, 0, 123456)
    assert by_phrase["指数関数的成長"].explanation == '説明: "速くなる"、🙂'
    assert by_phrase["latency"].context is None and by_phrase["latency"].metadata is None


def test_file_is_human_readable_utf8_text(source):
    text_ = d.export_dictionary(source)
    assert text_.startswith("# STORMHACKS-DICTIONARY v1\n") and "# entries: 4" in text_
    assert "指数関数的成長" in text_ and "\\u" not in text_              # real characters, not escapes
    assert all(line.startswith("#") or line.startswith("{") for line in text_.splitlines())
    assert text_.encode("utf-8").decode("utf-8") == text_


def test_export_one_user_or_everyone(source):
    one = d.parse_dictionary(d.export_dictionary(source, ALICE))
    assert {e.user_id for e in one.entries} == {ALICE} and len(one.entries) == 3
    assert len(d.parse_dictionary(d.export_dictionary(source)).entries) == 4
    nobody = d.export_dictionary(source, "no-such-user")
    assert "# entries: 0" in nobody and d.parse_dictionary(nobody).entries == []


def test_comments_blank_lines_bom_and_windows_line_endings_are_fine():
    body = '﻿# STORMHACKS-DICTIONARY v1\r\n# a comment\r\n\r\n{"phrase": "latency", "user_id": "u"}\r\n\r\n'
    parsed = d.parse_dictionary(body)
    assert parsed.errors == [] and [e.phrase for e in parsed.entries] == ["latency"]


@pytest.mark.parametrize("body,fragment", [
    ("", "empty"),
    ("hello\n", "not a STORMHACKS-DICTIONARY file"),
    ('{"phrase": "x"}\n', "not a STORMHACKS-DICTIONARY file"),
    ("# STORMHACKS-DICTIONARY v2\n", "version 2"),
])
def test_files_that_are_not_dictionaries_are_rejected_even_when_skipping_invalid(tmp_path, body, fragment):
    store = make_store(tmp_path)
    with pytest.raises(d.DictionaryError, match=fragment):
        d.import_dictionary(store, body, user_id="u", skip_invalid=True)
    assert snapshot(store) == []


BAD_LINES = [
    ("not json at all", "line 3: not valid JSON"),
    ('["a list"]', "line 3: each entry must be a JSON object"),
    ('{"context": "no phrase"}', 'line 3: "phrase" is required'),
    ('{"phrase": "   "}', 'line 3: "phrase" cannot be blank'),
    ('{"phrase": 5}', 'line 3: "phrase" must be text'),
    ('{"phrase": "x", "metadata": "no"}', 'line 3: "metadata" must be an object'),
    ('{"phrase": "x", "saved_at": "yesterday"}', 'line 3: "saved_at" is not a valid date/time'),
    ('{"phrase": "x", "user_id": "' + "u" * 65 + '"}', '"user_id" is longer than 64'),
    ('{"phrase": "' + "x" * 1001 + '"}', '"phrase" is longer than 1000'),
]


@pytest.mark.parametrize("line,message", BAD_LINES)
def test_each_kind_of_bad_line_is_reported_with_its_line_number(line, message):
    parsed = d.parse_dictionary(f"# STORMHACKS-DICTIONARY v1\n# note\n{line}\n")
    assert parsed.entries == [] and len(parsed.errors) == 1 and message in parsed.errors[0]


def test_strict_import_writes_nothing_when_any_line_is_bad(tmp_path):
    store = make_store(tmp_path)
    body = ('# STORMHACKS-DICTIONARY v1\n{"phrase": "good", "user_id": "u"}\nbroken\n'
            '{"phrase": "also good", "user_id": "u"}\n')
    with pytest.raises(d.DictionaryError) as caught:
        d.import_dictionary(store, body)
    assert caught.value.errors == ["line 3: not valid JSON (Expecting value)"]
    assert snapshot(store) == []


def test_skip_invalid_imports_the_good_lines_and_lists_the_bad(tmp_path):
    store = make_store(tmp_path)
    body = ('# STORMHACKS-DICTIONARY v1\n{"phrase": "good", "user_id": "u"}\nbroken\n'
            '{"phrase": "also good", "user_id": "u"}\n')
    result = d.import_dictionary(store, body, skip_invalid=True)
    assert (result.added, result.skipped_duplicates) == (2, 0) and len(result.invalid) == 1
    assert [m.content for m in store.list_memories("u")] == ["good", "also good"]     # file order kept


# ---- the actual point: the same database on another device ---------------------------------
def test_export_then_import_into_an_empty_database_gives_the_same_database(tmp_path, source):
    other = make_store(tmp_path, "other-device.sqlite")
    result = d.import_dictionary(other, d.export_dictionary(source))
    assert (result.added, result.skipped_duplicates, result.invalid) == (4, 0, [])
    assert snapshot(other) == snapshot(source)                      # every field, owners and times included
    assert [m.content for m in other.list_memories(ALICE)] == ["exponential growth", "指数関数的成長", "latency"]
    # and it can be copied again (device -> device -> device) without change
    third = make_store(tmp_path, "third.sqlite")
    d.import_dictionary(third, d.export_dictionary(other))
    assert snapshot(third) == snapshot(source)


def test_importing_is_idempotent(tmp_path, source):
    other = make_store(tmp_path, "other.sqlite")
    exported = d.export_dictionary(source)
    d.import_dictionary(other, exported)
    again = d.import_dictionary(other, exported)
    assert (again.added, again.skipped_duplicates) == (0, 4)
    assert snapshot(other) == snapshot(source)
    into_origin = d.import_dictionary(source, exported)             # importing into where it came from
    assert (into_origin.added, into_origin.skipped_duplicates) == (0, 4)


def test_import_only_adds_what_is_missing(tmp_path, source):
    other = make_store(tmp_path, "other.sqlite")
    other.add_memory(ALICE, "latency")                              # already has one of them
    result = d.import_dictionary(other, d.export_dictionary(source))
    assert (result.added, result.skipped_duplicates) == (3, 1)
    assert sorted(m.content for m in other.list_memories(ALICE)) == ["exponential growth", "latency", "指数関数的成長"]


def test_duplicates_inside_one_file_collapse(tmp_path):
    store = make_store(tmp_path)
    line = '{"phrase": "latency", "context": "c", "user_id": "u"}\n'
    result = d.import_dictionary(store, "# STORMHACKS-DICTIONARY v1\n" + line * 3)
    assert (result.added, result.skipped_duplicates) == (1, 2)


def test_same_phrase_with_different_context_or_language_is_a_different_entry(tmp_path):
    store = make_store(tmp_path)
    body = ("# STORMHACKS-DICTIONARY v1\n"
            '{"phrase": "bank", "context": "river bank", "user_id": "u"}\n'
            '{"phrase": "bank", "context": "money bank", "user_id": "u"}\n'
            '{"phrase": "bank", "context": "money bank", "target_lang": "fr", "user_id": "u"}\n')
    assert d.import_dictionary(store, body).added == 3


def test_import_for_a_specific_user_re_owns_every_entry(tmp_path, source):
    """What the browser does: the new device has its own id, so the entries become this browser's."""
    other = make_store(tmp_path, "other.sqlite")
    mine = "33333333-3333-4333-8333-333333333333"
    result = d.import_dictionary(other, d.export_dictionary(source), user_id=mine)
    assert result.added == 4 and d.all_user_ids(other) == [mine]
    assert len(other.list_memories(mine)) == 4
    assert d.import_dictionary(other, d.export_dictionary(source), user_id=mine).added == 0


def test_entries_without_an_owner_need_a_user_id(tmp_path):
    store = make_store(tmp_path)
    body = '# STORMHACKS-DICTIONARY v1\n{"phrase": "latency"}\n'
    with pytest.raises(d.DictionaryError, match="no user_id"):
        d.import_dictionary(store, body)
    assert d.import_dictionary(store, body, user_id="u").added == 1
    with pytest.raises(ValueError):
        d.import_dictionary(store, body, user_id="  ")


def test_entries_without_a_time_keep_file_order(tmp_path):
    store = make_store(tmp_path)
    body = "# STORMHACKS-DICTIONARY v1\n" + "".join(f'{{"phrase": "p{i}", "user_id": "u"}}\n' for i in range(5))
    d.import_dictionary(store, body)
    assert [m.content for m in store.list_memories("u")] == [f"p{i}" for i in range(5)]


def test_dry_run_counts_but_writes_nothing(tmp_path, source):
    other = make_store(tmp_path, "other.sqlite")
    result = d.import_dictionary(other, d.export_dictionary(source), dry_run=True)
    assert (result.added, result.dry_run) == (4, True) and snapshot(other) == []


def test_import_is_all_or_nothing(tmp_path):
    store = make_store(tmp_path)
    body = ('# STORMHACKS-DICTIONARY v1\n{"phrase": "fine", "user_id": "u"}\n'
            '{"phrase": "bad", "user_id": "u"}\n')           # the table refuses 'bad' (CHECK)
    with pytest.raises(Exception):
        d.import_dictionary(store, body)
    assert snapshot(store) == [], "the good row must not survive a failed batch"


def test_a_large_file_imports_in_one_go(tmp_path):
    store = make_store(tmp_path)
    body = "# STORMHACKS-DICTIONARY v1\n" + "".join(
        f'{{"phrase": "phrase {i}", "context": "ctx {i}", "user_id": "u"}}\n' for i in range(1500))
    assert d.import_dictionary(store, body).added == 1500 and len(store.list_memories("u")) == 1500


# ---- command line --------------------------------------------------------------------------
@pytest.fixture
def cli(monkeypatch, tmp_path, source):
    monkeypatch.setattr(d, "_store_from_env", lambda: source)
    monkeypatch.chdir(tmp_path)
    return source


def test_cli_export_writes_a_utf8_file_and_import_reads_it_back(cli, tmp_path, monkeypatch, capsys):
    assert d.main(["export", "--user-id", ALICE, "-o", "alice.txt"]) == 0
    assert "Wrote 3 phrase(s) to alice.txt" in capsys.readouterr().out
    raw = (tmp_path / "alice.txt").read_bytes()
    assert raw.decode("utf-8").startswith("# STORMHACKS-DICTIONARY v1") and "指数関数的成長".encode() in raw
    assert b"\r\n" not in raw                                         # same bytes on Windows and Mac

    other = make_store(tmp_path, "other.sqlite")
    monkeypatch.setattr(d, "_store_from_env", lambda: other)
    assert d.main(["import", "alice.txt", "--dry-run"]) == 0
    assert "Would add 3 phrase(s); skipped 0 already saved." in capsys.readouterr().out
    assert snapshot(other) == []
    assert d.main(["import", "alice.txt"]) == 0
    assert "Added 3 phrase(s); skipped 0 already saved." in capsys.readouterr().out
    assert d.main(["import", "alice.txt"]) == 0
    assert "Added 0 phrase(s); skipped 3 already saved." in capsys.readouterr().out


def test_cli_export_all_list_users_and_default_filename(cli, tmp_path, capsys):
    assert d.main(["export", "--list-users"]) == 0
    listing = capsys.readouterr().out
    assert f"{ALICE}  (3 phrases)" in listing and f"{BOB}  (1 phrases)" in listing
    assert d.main(["export", "--all"]) == 0
    (name,) = [p.name for p in tmp_path.glob("dictionary-*.txt")]
    assert len(d.parse_dictionary((tmp_path / name).read_text(encoding="utf-8")).entries) == 4


def test_cli_reports_every_problem_and_imports_nothing(cli, tmp_path, capsys):
    (tmp_path / "bad.txt").write_text('# STORMHACKS-DICTIONARY v1\nnope\n{"context": "x"}\n', encoding="utf-8")
    assert d.main(["import", "bad.txt", "--user-id", "u"]) == 2
    err = capsys.readouterr().err
    assert "Nothing was imported" in err and "line 2" in err and "line 3" in err


def test_cli_missing_file_and_missing_settings_are_friendly(monkeypatch, tmp_path, capsys, source):
    monkeypatch.setattr(d, "_store_from_env", lambda: source)
    assert d.main(["import", str(tmp_path / "missing.txt")]) == 1
    assert "Error:" in capsys.readouterr().err

    def no_settings():
        raise RuntimeError("Missing TiDB settings: TIDB_HOST")
    monkeypatch.setattr(d, "_store_from_env", no_settings)
    assert d.main(["export", "--all"]) == 1
    assert "Missing TiDB settings" in capsys.readouterr().err
