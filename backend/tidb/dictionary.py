"""Dictionary file: copy the saved phrases to / from a plain text file.

    python -m backend.tidb.dictionary export --user-id <uuid> -o dictionary.txt
    python -m backend.tidb.dictionary export --all -o everything.txt
    python -m backend.tidb.dictionary import dictionary.txt              # keeps the owners in the file
    python -m backend.tidb.dictionary import dictionary.txt --user-id <uuid>   # re-own for this user

The "dictionary" is the `memories` table: each saved phrase with its context, explanation and
languages. Embeddings are *not* exported: TiDB generates them itself from the phrase on insert,
so the text is all that is needed to rebuild the same database on another cluster or device.

File format (UTF-8 text, one entry per line so any character, including newlines inside
a value, survives):

    # STORMHACKS-DICTIONARY v1
    # exported: 2026-10-04T05:12:00Z
    # entries: 2
    {"user_id": "...", "phrase": "exponential growth", "context": "...", "explanation": "...", ...}

Lines starting with `#` and blank lines are ignored. Importing is idempotent: an entry whose
phrase, context and target language already exist for that user is skipped, so importing the
same file twice (or into the database it came from) adds nothing.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import text

from .schema import MEMORIES_TABLE
from .store import MemoryStore

FORMAT_NAME = "STORMHACKS-DICTIONARY"
FORMAT_VERSION = 1
_HEADER = re.compile(rf"^#\s*{FORMAT_NAME}\s+v(\d+)\s*$")

# Upper bounds. user_id / kind / language fields match the table's VARCHAR sizes; the text fields
# are generous so that anything the database already holds (via any route) can be copied back.
MAX_PHRASE, MAX_CONTEXT, MAX_EXPLANATION, MAX_USER_ID = 1000, 10000, 10000, 64
DEFAULT_KIND = "not_understood"


class DictionaryError(ValueError):
    """The file cannot be imported. `errors` lists every problem found, with line numbers."""

    def __init__(self, errors: list[str]):
        super().__init__("; ".join(errors[:5]) + (f" (+{len(errors) - 5} more)" if len(errors) > 5 else ""))
        self.errors = errors


@dataclass(frozen=True)
class Entry:
    phrase: str
    context: str | None = None
    explanation: str | None = None
    user_id: str | None = None
    kind: str = DEFAULT_KIND
    source_lang: str | None = None
    target_lang: str | None = None
    metadata: dict[str, Any] | None = None
    saved_at: datetime | None = None          # naive, as stored in the DATETIME column


@dataclass
class ParseResult:
    entries: list[Entry] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    fatal: bool = False          # the file is not a (readable) dictionary file at all


@dataclass
class ImportResult:
    added: int = 0
    skipped_duplicates: int = 0
    invalid: list[str] = field(default_factory=list)
    dry_run: bool = False


# ---- writing -------------------------------------------------------------------------------
def _entry_line(memory) -> str:
    record = {
        "user_id": memory.user_id,
        "phrase": memory.content,
        "context": memory.context,
        "explanation": memory.note,
        "kind": memory.kind,
        "source_lang": memory.source_lang,
        "target_lang": memory.target_lang,
        "metadata": memory.metadata,
        "saved_at": memory.created_at.isoformat() if memory.created_at else None,
    }
    return json.dumps(record, ensure_ascii=False)


def format_dictionary(memories, *, now: datetime | None = None) -> str:
    """Render memories (see MemoryStore.list_memories) as dictionary-file text."""
    now = now or datetime.now(timezone.utc)
    lines = [
        f"# {FORMAT_NAME} v{FORMAT_VERSION}",
        "# Saved phrases and their explanations. One JSON entry per line; lines starting with # are ignored.",
        f"# exported: {now.strftime('%Y-%m-%dT%H:%M:%SZ')}",
        f"# entries: {len(memories)}",
    ]
    lines += [_entry_line(m) for m in memories]
    return "\n".join(lines) + "\n"


def all_user_ids(store: MemoryStore) -> list[str]:
    with store.engine.connect() as conn:
        rows = conn.execute(text(f"SELECT DISTINCT user_id FROM {MEMORIES_TABLE} ORDER BY user_id")).all()
    return [row.user_id for row in rows]


def export_dictionary(store: MemoryStore, user_id: str | None = None) -> str:
    """Text for one user's saved phrases, or for every user when `user_id` is None."""
    users = [user_id] if user_id is not None else all_user_ids(store)
    memories = [m for u in users for m in store.list_memories(u)]
    return format_dictionary(memories)


# ---- reading -------------------------------------------------------------------------------
def _text_field(record: dict, key: str, limit: int, required: bool = False) -> str | None:
    value = record.get(key)
    if value is None:
        if required:
            raise ValueError(f'"{key}" is required')
        return None
    if not isinstance(value, str):
        raise ValueError(f'"{key}" must be text')
    value = value.strip()
    if not value:
        if required:
            raise ValueError(f'"{key}" cannot be blank')
        return None
    if len(value) > limit:
        raise ValueError(f'"{key}" is longer than {limit} characters')
    return value


def _parse_time(value: Any) -> datetime | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError('"saved_at" must be a date/time string')
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise ValueError('"saved_at" is not a valid date/time') from None
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
    return parsed


def _parse_entry(record: Any) -> Entry:
    if not isinstance(record, dict):
        raise ValueError("each entry must be a JSON object")
    metadata = record.get("metadata")
    if metadata is not None and not isinstance(metadata, dict):
        raise ValueError('"metadata" must be an object')
    return Entry(
        phrase=_text_field(record, "phrase", MAX_PHRASE, required=True),
        context=_text_field(record, "context", MAX_CONTEXT),
        explanation=_text_field(record, "explanation", MAX_EXPLANATION),
        user_id=_text_field(record, "user_id", MAX_USER_ID),
        kind=_text_field(record, "kind", 32) or DEFAULT_KIND,
        source_lang=_text_field(record, "source_lang", 16),
        target_lang=_text_field(record, "target_lang", 16),
        metadata=metadata,
        saved_at=_parse_time(record.get("saved_at")),
    )


def parse_dictionary(content: str) -> ParseResult:
    """Parse file text. Never raises for bad entries: problems are collected in `errors`."""
    result = ParseResult()
    seen_header = False
    for number, raw in enumerate(content.lstrip("﻿").splitlines(), start=1):
        line = raw.strip()
        if not line:
            continue
        if not seen_header:
            header = _HEADER.match(line)
            if not header:
                result.errors.append(f"line {number}: not a {FORMAT_NAME} file (the first line must be "
                                     f"'# {FORMAT_NAME} v{FORMAT_VERSION}')")
                result.fatal = True
                return result
            if int(header.group(1)) > FORMAT_VERSION:
                result.errors.append(f"line {number}: this file is version {header.group(1)}; "
                                     f"this app understands up to v{FORMAT_VERSION}. Update the app.")
                result.fatal = True
                return result
            seen_header = True
            continue
        if line.startswith("#"):
            continue
        try:
            result.entries.append(_parse_entry(json.loads(line)))
        except json.JSONDecodeError as exc:
            result.errors.append(f"line {number}: not valid JSON ({exc.msg})")
        except ValueError as exc:
            result.errors.append(f"line {number}: {exc}")
    if not seen_header:
        result.errors.append(f"the file is empty or not a {FORMAT_NAME} file")
        result.fatal = True
    return result


# ---- importing -----------------------------------------------------------------------------
def _key(phrase: str | None, context: str | None, target_lang: str | None) -> tuple[str, str, str]:
    return ((phrase or "").strip(), (context or "").strip(), (target_lang or "").strip())


def import_entries(store: MemoryStore, entries: list[Entry], *, user_id: str | None = None,
                   dry_run: bool = False) -> ImportResult:
    """Insert entries in ONE transaction (all or nothing). `user_id` re-owns every entry; without
    it each entry must carry its own. Entries already present for that user are skipped."""
    if user_id is not None and not user_id.strip():
        raise ValueError("user_id cannot be blank")
    result = ImportResult(dry_run=dry_run)
    base = datetime.now(timezone.utc).replace(tzinfo=None)
    rows: list[dict[str, Any]] = []
    owners: dict[str, list[tuple[int, Entry]]] = {}
    for index, entry in enumerate(entries):
        owner = user_id or entry.user_id
        if not owner:
            raise DictionaryError([f"entry {index + 1} ('{entry.phrase}') has no user_id; "
                                   "pass a user id to import it for"])
        owners.setdefault(owner, []).append((index, entry))

    with store.engine.begin() as conn:
        for owner, items in owners.items():
            existing = {_key(r.content, r.context, r.target_lang) for r in conn.execute(
                text(f"SELECT content, context, target_lang FROM {MEMORIES_TABLE} WHERE user_id = :u"),
                {"u": owner})}
            for index, entry in items:
                key = _key(entry.phrase, entry.context, entry.target_lang)
                if key in existing:
                    result.skipped_duplicates += 1
                    continue
                existing.add(key)
                rows.append({
                    "user_id": owner, "kind": entry.kind, "content": entry.phrase,
                    "context": entry.context, "note": entry.explanation,
                    "source_lang": entry.source_lang, "target_lang": entry.target_lang,
                    "metadata": json.dumps(entry.metadata, ensure_ascii=False) if entry.metadata is not None else None,
                    # keep the original time; entries without one keep file order
                    "created_at": entry.saved_at or base + timedelta(microseconds=index),
                })
        result.added = len(rows)
        if rows and not dry_run:
            conn.execute(text(f"""
                INSERT INTO {MEMORIES_TABLE}
                    (user_id, kind, content, context, note, source_lang, target_lang, metadata, created_at)
                VALUES (:user_id, :kind, :content, :context, :note, :source_lang, :target_lang,
                        :metadata, :created_at)
            """), rows)
    return result


def import_dictionary(store: MemoryStore, content: str, *, user_id: str | None = None,
                      skip_invalid: bool = False, dry_run: bool = False) -> ImportResult:
    """Parse and import file text. Invalid lines abort the import (nothing is written) unless
    `skip_invalid`, in which case they are skipped and listed in the result."""
    parsed = parse_dictionary(content)
    if parsed.fatal or (parsed.errors and not skip_invalid):
        raise DictionaryError(parsed.errors)
    result = import_entries(store, parsed.entries, user_id=user_id, dry_run=dry_run)
    result.invalid = parsed.errors
    return result


# ---- command line --------------------------------------------------------------------------
def _store_from_env() -> MemoryStore:
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass
    store = MemoryStore.from_env()
    store.init_schema()
    return store


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m backend.tidb.dictionary", description=__doc__.split("\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)

    out = sub.add_parser("export", help="write saved phrases to a text file")
    who = out.add_mutually_exclusive_group(required=True)
    who.add_argument("--user-id", help="export this user's phrases (the browser's id is shown by --list-users)")
    who.add_argument("--all", action="store_true", help="export every user's phrases")
    who.add_argument("--list-users", action="store_true", help="list the user ids in the database and exit")
    out.add_argument("-o", "--output", default=None, help="file to write (default dictionary-YYYY-MM-DD.txt)")

    inc = sub.add_parser("import", help="add the phrases in a text file")
    inc.add_argument("file", help="dictionary file to import")
    inc.add_argument("--user-id", help="give every entry to this user (default: keep each entry's owner)")
    inc.add_argument("--skip-invalid", action="store_true", help="import the valid lines even if some are invalid")
    inc.add_argument("--dry-run", action="store_true", help="show what would be added without writing")

    args = parser.parse_args(argv)
    try:
        store = _store_from_env()
        if args.command == "export":
            if args.list_users:
                for user in all_user_ids(store):
                    print(f"{user}  ({len(store.list_memories(user))} phrases)")
                return 0
            content = export_dictionary(store, None if args.all else args.user_id)
            path = Path(args.output or f"dictionary-{datetime.now():%Y-%m-%d}.txt")
            path.write_text(content, encoding="utf-8", newline="\n")
            count = sum(1 for line in content.splitlines() if line and not line.startswith("#"))
            print(f"Wrote {count} phrase(s) to {path}")
            return 0
        content = Path(args.file).read_text(encoding="utf-8-sig")
        result = import_dictionary(store, content, user_id=args.user_id,
                                   skip_invalid=args.skip_invalid, dry_run=args.dry_run)
        verb = "Would add" if result.dry_run else "Added"
        print(f"{verb} {result.added} phrase(s); skipped {result.skipped_duplicates} already saved.")
        for problem in result.invalid:
            print(f"  skipped invalid {problem}")
        return 0
    except DictionaryError as exc:
        print("Nothing was imported:", file=sys.stderr)
        for problem in exc.errors:
            print(f"  {problem}", file=sys.stderr)
        return 2
    except (OSError, RuntimeError) as exc:      # unreadable file, missing TIDB_* settings
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
