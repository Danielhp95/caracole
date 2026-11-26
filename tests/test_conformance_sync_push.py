"""A give's pushes, for the phone: what the computer takes of a push at most, as its routes declare it, and how
peer_push.py cuts a give into pushes within those limits (``_cut``), written for the Kotlin give (core/sync's
SyncEngine.give, Give.cut) to agree with: the phone's limits are PeerClient's constants, held to these.

**Vectors**: sync/push.jsonl, ``helpers.corpus.jsonl``'s, a header, then a record a line:

- ``limits``: ``out`` each push route's body limit in bytes, as web/peer_routes.py declares it (``{"<METHOD>
  <path>": limit}``), and ``push`` a push's files' bytes at most (``peer_push.PUSH_MAX``);
- ``words``: ``out`` why a unit is left out of a give, ``TOO_LONG``, ``TOO_HEAVY`` (peer_push.py's) and ``TOO_BIG``
  (peer_file.py's: a kept file past 64 MiB, one wording wherever a file is too big);
- ``cut``, a ``case`` each: ``kw`` ``{header, take, files_of, sizes, from, limits}``, the push document with no
  unit to take, the units given (each ``{id, expected, digest, unit}``), each song's files by SHA-256, each file's
  size, the pusher's id and the limits it is cut within (``{new, document, files}``); ``out`` ``{pushes, left}``,
  each push's unit ids in order and each unit left ``[id, why]``. Lengths are of the bytes sent, whatever the
  order of a document's keys (the corpus writes them sorted).

Regenerate with ``CARACOLE_CORPUS=write`` (tests/conformance/README.md).
"""

from __future__ import annotations

import hashlib

from helpers.corpus import VECTORS, check, jsonl

from caracole import peer_file, peer_push
from caracole import peer_sync as sync
from caracole.web import peer_routes

PUSH = VECTORS / "sync" / "push.jsonl"
MADE_BY = "tests/test_conformance_sync_push.py"
FROM = "0123456789abcdef"
HEADER = {"format": sync.FORMAT, "from": FROM, "name": "Phone · 手机", "caracole": "0.1.0", "key_version": 1,
          "at": "2026-11-03T00:00:00Z", "units": {"song/a/b": {"label": "A - B", "digest": "ab" * 32}}, "take": []}


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def _entry(unit_id: str, words: int | None = 10, files=(), text: str = "x") -> dict:
    unit = None if words is None else {"names": text * words, "versions": [
        {"files": [{"name": f"f-{n}", "sha256": f, "kept_rank": 0} for n, f in enumerate(files)]}]}
    return {"id": unit_id, "expected": None, "digest": None if unit is None else _sha(unit_id), "unit": unit}


def _case(case: str, take: list, limits: dict, sizes: dict | None = None) -> dict:
    files_of = {e["id"]: sorted({f["sha256"] for v in e["unit"]["versions"] for f in v["files"]})
                for e in take if e["unit"] is not None and e["id"].startswith("song/")}
    sizes = sizes or {}
    pushes, left = peer_push._cut(HEADER, take, {k: set(v) for k, v in files_of.items()}, sizes, FROM,
                                  document_max=limits["document"], new_max=limits["new"], files_max=limits["files"])
    return {"fn": "cut", "case": case,
            "kw": {"header": HEADER, "take": take, "files_of": files_of, "sizes": sizes, "from": FROM,
                   "limits": limits},
            "out": {"pushes": [[e["id"] for e in batch] for batch in pushes], "left": [list(x) for x in left]}}


def records() -> list[dict]:
    limits = {f"{r.method} {r.path}": r.limit for r in peer_routes.ROUTES if r.path.startswith("/peer/push")}
    small = {"new": 1000, "document": 4000, "files": 1000}
    out = [
        {"fn": "limits", "out": {**limits, "push": peer_push.PUSH_MAX}},
        {"fn": "words", "out": {"TOO_LONG": peer_push.TOO_LONG, "TOO_HEAVY": peer_push.TOO_HEAVY,
                                "TOO_BIG": peer_file.TOO_BIG}},
        _case("one_push", [_entry("song/a/one"), _entry("songbook/campfire"), _entry("song/a/two")], small),
        _case("by_document", [_entry(f"song/a/s{n}", 700) for n in range(12)], small),
        _case("non_ascii_counted_in_bytes", [_entry(f"song/a/s{n}", 600, text="é") for n in range(12)], small),
        _case("a_song_with_its_tombstone", [_entry("song/a/s0", 900), _entry("removed/a/s3", None)]
              + [_entry(f"song/a/s{n}", 1100) for n in (1, 2, 3)], small),
        _case("too_long_alone", [_entry("song/a/short"), _entry("song/a/long", 5000), _entry("song/a/after")], small),
        _case("by_files_named", [_entry(f"song/a/s{n}", 10, [_sha(f"{n}-{k}") for k in range(5)])
                                 for n in range(6)], small),
        _case("a_file_shared_is_named_once", [_entry(f"song/a/s{n}", 10, [_sha("shared"), _sha(str(n))])
                                              for n in range(8)], small),
        _case("by_files_bytes", [_entry(f"song/a/s{n}", 10, [_sha(str(n))]) for n in range(5)], small,
              {_sha(str(n)): 400 for n in range(5)}),
        _case("too_heavy_alone", [_entry("song/a/heavy", 10, [_sha("heavy")]), _entry("song/a/light", 10)], small,
              {_sha("heavy"): 1001}),
    ]
    return out


def test_push_jsonl_is_what_peer_push_answers():
    check(PUSH, jsonl(records(), corpus="sync/push", made_by=MADE_BY))


def test_the_cases_show_what_they_name():
    by = {r.get("case"): r["out"] for r in records() if r["fn"] == "cut"}
    assert len(by["one_push"]["pushes"]) == 1 and len(by["by_document"]["pushes"]) > 2
    assert len(by["non_ascii_counted_in_bytes"]["pushes"]) > len(by["by_document"]["pushes"])  # 1,200 bytes, not 600
    tombstone = by["a_song_with_its_tombstone"]["pushes"]
    assert len(tombstone) > 1 and any(p[p.index("removed/a/s3") + 1] == "song/a/s3" for p in tombstone
                                      if "removed/a/s3" in p)  # the two in one push, as the first came
    assert by["too_long_alone"]["left"] == [["song/a/long", peer_push.TOO_LONG]]
    assert len(by["by_files_named"]["pushes"]) > 1 and len(by["by_files_bytes"]["pushes"]) == 3
    assert len(by["a_file_shared_is_named_once"]["pushes"]) == 1
    assert by["too_heavy_alone"]["left"] == [["song/a/heavy", peer_push.TOO_HEAVY]]
    limits = next(r["out"] for r in records() if r["fn"] == "limits")
    assert limits["POST /peer/push"] == peer_push.DOCUMENT_MAX and limits["POST /peer/push/new"] == peer_push.NEW_MAX
    assert limits["POST /peer/push/file"] == peer_push.FILE_MAX == peer_file.FILE_MAX
