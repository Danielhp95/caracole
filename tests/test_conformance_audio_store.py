"""audio_store.py on the phone, for :core's ``core.library.AudioStore``: the store's rules as data, and its answers as
vectors, so that the phone stages and keeps a file the computer's way.

**Data** (``data/caracole/library/audio_store.json``, ``audio_store_json``): every constant of audio_store.py the
phone's store reads (the folder, ``NAME_KEY``, ``AUDIO_MAX``, ``MAX_SECONDS``, ``ROOM``, ``EXPIRES``, ``MARKED``,
``HEAD``, ``_RECORD_MAX``, ``FORMATS`` in order, ``_MP4_BRANDS``, ``DISPLAY_MOST``, ``TAGS``), its name patterns
(``ID``, ``_PIECE``, ``_STAGED_AUDIO``, ``_MARKER``, ``KEPT``, ``_PART``, ``_SHA256`` and ``_SPLIT``: Python's, for
``PyRegex``), the names it builds them of, the members of a staged upload's record and of a marker (``MARKER_FIELDS``),
and every refusal's words with the status caracole serve answers it with, each found by provoking the refusal
(``statuses``); and removal.py's words of a removal that deletes the file you
gave (``UPLOADED_GOES``, ``UPLOADED_BRIEF``).

**Vectors** (``vectors/library/audio_store.jsonl``), a header, then a record a line:

- ``sniff``, ``_mpeg_frame``, ``_mp4_audio``: ``args`` ``[head base64]``, ``out`` the answer, over every head
  tests/test_audio_store.py builds (its parametrized heads, each format's file made by helpers/audio_files.py and the
  same tagged, cut to ``HEAD``) and the edges of ``EDGE_HEADS``.
- ``_display_name``: ``args`` ``[name]``, ``out`` the name to show, over the test's names and ``EDGE_NAMES``.
- ``names``: ``args`` ``[name]``, ``out`` ``{id, piece, staged_audio, marker, kept, part}``: whether ``ID``, ``KEPT``
  and ``_PART`` match the name whole, and ``_PIECE``'s ``[id, ext]``, ``_STAGED_AUDIO``'s and ``_MARKER``'s id (null:
  no match), over ``NAMES``.
- ``kept_name``: ``kw`` ``{song, sha256, format}``, ``out`` the kept file's name ``keep`` gives: each format's file
  kept for a song by ``keep``, its digest recorded.
- ``record``: ``kw`` a staged upload's fields (no id or path), ``out`` ``.upload-<id>.json``'s text as ``stage``
  writes it (``json.dumps(up.record())``); ``_read_record``: ``args`` ``[text]``, ``out`` whether it reads as a record
  (``RECORDS``, besides each ``record``'s own text).
- ``marker``: ``kw`` ``{kept, song, at}``, ``out`` ``.upload-<id>.kept``'s text as ``_write_marker`` writes it;
  ``_read_marker``: ``args`` ``[text]``, ``out`` ``{kept, song, at}`` or null (``MARKERS``).
- ``given_file``: ``kw`` ``{entries: [[path, kind]…], path}``, the tree under a folder (``kind`` file, link to the first
  file, or folder), ``path`` relative to it (null: none), ``out`` ``given_file`` of it there.
- ``merge``: ``kw`` ``{songs: [row…], files: [path…], kv: {key: value}}``, two songs an older normalizer kept apart
  (test_audio_store.py's ``_two_spellings``), each row's ``audio_path`` written ``{state}/…`` and each file of
  ``files`` there, regular; ``out`` ``{songs: [{id, audio_path, audio_mtime}…], kv: {key: value}}`` once
  ``ensure_current_keys`` merged them (songs.py ``_merge``'s ``_given_audio``), the ``audio:name:`` records alone.

The answers are the same on every run. Regenerate with ``CARACOLE_CORPUS=write`` (tests/conformance/README.md).
"""

from __future__ import annotations

import base64
import hashlib
import json
import re
import struct
from pathlib import Path

import pytest
from helpers.audio_files import FORMATS as MADE
from helpers.audio_files import audio, write
from helpers.corpus import DATA, VECTORS, check, jsonl

from caracole import audio_store, removal
from caracole.audio_store import FORMATS, HEAD, Staged

MADE_BY = "tests/test_conformance_audio_store.py"
AUDIO_STORE_JSON = DATA / "library" / "audio_store.json"
VECTOR = VECTORS / "library" / "audio_store.jsonl"


def _pattern(p: re.Pattern[str]) -> str:
    assert p.flags & ~re.UNICODE == 0, f"{p.pattern!r}: a flag the phone doesn't read"
    return p.pattern


WORDS = ("NOT_AUDIO", "TOO_BIG", "TOO_LONG", "NO_ROOM", "EMPTY", "NO_NAME", "WHICH", "GONE", "NOT_IN_BOOK",
         "NOT_A_STORE")


def statuses(tmp_path: Path) -> dict[str, int]:
    """Each refusal's status, as audio_store.py raises it: every refusal provoked, its words checked to be the
    constant's (``NOT_IN_BOOK`` and ``NOT_A_STORE`` formatted), so a status changed there changes the data."""
    from types import SimpleNamespace
    from unittest import mock

    from conftest import add_song, migrated_database

    from caracole import db
    from caracole.config import load_config

    def config(home: Path):
        return load_config(None, env={"HOME": str(home / "home"), "STATE_DIRECTORY": str(home / "state"),
                                      "CACHE_DIRECTORY": str(home / "cache")})

    root = tmp_path / "statuses"
    cfg = config(root)
    cfg.state_dir.mkdir(parents=True)
    (root / "db.sqlite").write_bytes(migrated_database())
    conn = db.connect(root / "db.sqlite")
    roomy = mock.patch.object(audio_store, "disk_usage", lambda p: SimpleNamespace(total=10**15, used=0, free=10**15))
    found: dict[str, int] = {}

    def refusal(name: str, call, words: str | None = None) -> None:
        with pytest.raises(audio_store.AudioError) as e:
            call()
        assert str(e.value) == (words or getattr(audio_store, name)), (name, str(e.value))
        found[name.lower()] = e.value.status

    with roomy:
        refusal("NOT_AUDIO", lambda: audio_store.stage(cfg, b"not really audio" * 10, "a.mp3", named=()))
        refusal("TOO_LONG", lambda: audio_store.stage(cfg, audio("FLAC", audio_store.MAX_SECONDS + 1), "a.flac",
                                                      named=()))
        with mock.patch.object(audio_store, "AUDIO_MAX", 10):
            refusal("TOO_BIG", lambda: audio_store.stage(cfg, audio("MP3"), "a.mp3", named=()))
        refusal("EMPTY", lambda: audio_store.stage(cfg, b"", "a.mp3", named=()))
        refusal("NO_NAME", lambda: audio_store.stage(cfg, audio("MP3"), "\x00/", named=()))
        refusal("WHICH", lambda: audio_store.staged(cfg, "nope"))
        refusal("GONE", lambda: audio_store.staged(cfg, "0123456789abcdef"))
        song = add_song(conn, "Radiohead", "Creep")
        conn.execute("DELETE FROM songs WHERE id = ?", (song.id,))
        up = audio_store.stage(cfg, audio("MP3"), "a.mp3", named=())
        refusal("NOT_IN_BOOK", lambda: audio_store.keep(cfg, conn, song, up.path, move=True),
                audio_store.NOT_IN_BOOK.format(song=song.display))
    with mock.patch.object(audio_store, "disk_usage", lambda p: SimpleNamespace(total=10**15, used=0, free=0)):
        refusal("NO_ROOM", lambda: audio_store.stage(cfg, audio("MP3"), "a.mp3", named=()))
    cfg_linked = config(root / "linked")
    cfg_linked.state_dir.mkdir(parents=True)
    (cfg_linked.state_dir / audio_store.FOLDER).symlink_to(root)
    with roomy:
        store = cfg_linked.state_dir / audio_store.FOLDER
        refusal("NOT_A_STORE", lambda: audio_store.stage(cfg_linked, audio("MP3"), "a.mp3", named=()),
                audio_store.NOT_A_STORE.format(path=store))
    conn.close()
    assert set(found) == {w.lower() for w in WORDS}
    return {w.lower(): found[w.lower()] for w in WORDS}


def audio_store_json(tmp_path: Path) -> str:
    words = {name.lower(): getattr(audio_store, name) for name in WORDS}
    data = {
        "folder": audio_store.FOLDER,
        "name_key": audio_store.NAME_KEY,
        "audio_max": audio_store.AUDIO_MAX,
        "max_seconds": audio_store.MAX_SECONDS,
        "room": audio_store.ROOM,
        "expires": audio_store.EXPIRES,
        "marked": audio_store.MARKED,
        "head": audio_store.HEAD,
        "record_max": audio_store._RECORD_MAX,
        "formats": dict(FORMATS),
        "mp4_brands": sorted(b.decode("latin-1") for b in audio_store._MP4_BRANDS),
        "patterns": {"id": _pattern(audio_store.ID), "piece": _pattern(audio_store._PIECE),
                     "staged_audio": _pattern(audio_store._STAGED_AUDIO), "marker": _pattern(audio_store._MARKER),
                     "kept": _pattern(audio_store.KEPT), "part": _pattern(audio_store._PART),
                     "sha256": _pattern(audio_store._SHA256), "display_split": _pattern(audio_store._SPLIT)},
        "names": {"staged": audio_store._STAGED, "record": audio_store._RECORD, "marker": audio_store._MARK,
                  "part": audio_store._COPY, "part_end": audio_store._COPY_END},
        "display_most": audio_store.DISPLAY_MOST,
        "record_fields": [f for f in Staged.__dataclass_fields__ if f not in ("id", "path")],
        "tags": list(audio_store.TAGS),
        "marker_fields": list(audio_store.MARKER_FIELDS),
        "words": words,
        "statuses": statuses(tmp_path),
        "removal": {"goes": removal.UPLOADED_GOES, "brief": removal.UPLOADED_BRIEF},
    }
    return json.dumps(data, ensure_ascii=False, indent=1) + "\n"


def test_audio_store_json_is_audio_store_pys_rules(tmp_path):
    check(AUDIO_STORE_JSON, audio_store_json(tmp_path))


def test_the_record_fields_are_what_a_record_holds(tmp_path):
    up = Staged("0" * 16, Path("x"), "a", 1, "0" * 64, "MP3", 1.0, {"artist": None, "title": None, "album": None}, 2.0)
    assert list(up.record()) == json.loads(audio_store_json(tmp_path))["record_fields"]


# --- the heads ------------------------------------------------------------------------------------------------------


def _ftyp(major: bytes, *compatible: bytes, size: int | None = None) -> bytes:
    body = major + b"\x00\x00\x00\x00" + b"".join(compatible)
    return struct.pack(">I", size if size is not None else 8 + len(body)) + b"ftyp" + body


EDGE_HEADS = [
    b"ID3\x04\x00\x00\x00\x00\x00\x0a" + b"\x00" * 10 + b"\xff\xfb\x90\xc0",  # an ID3v2 tag, then a frame
    b"ID3", b"ID", b"I", b"\xff", b"\xff\xfb", b"\xff\xfb\x90",
    b"\xff\xfb\x00\xc0",  # bitrate 0: the free format, a bitrate that exists
    b"\xff\xfb\xe0\xc0", b"\xff\xfb\xf0\xc0", b"\xff\xfb\x9c\xc0", b"\xff\xfb\x98\xc0", b"\xff\xfb\x94\xc0",
    b"\xff\xf9\x90\xc0",  # layer 0
    b"\xff\xff\x90\xc0", b"\xff\xe0\x90\xc0", b"\xff\xdf\x90\xc0", b"\xfe\xfb\x90\xc0",
    b"\xff" * 64, b"\xff" * 3, b"\xff\xff\xfe" + b"\x00" * 61,
    _ftyp(b"M4A ", b"isom", size=1000), _ftyp(b"qt  ", b"M4A ", size=1000), _ftyp(b"qt  ", b"M4A ", size=12),
    _ftyp(b"qt  ", b"M4A ", size=19), _ftyp(b"qt  ", b"M4A ", size=20), _ftyp(b"qt  ", b"qt  ", b"mp42", size=0),
    _ftyp(b"m4a ", b"MP42"), _ftyp(b"mp42")[:11], b"\x00\x00\x00\x18ftyp", b"\x00\x00\x00\x18ftypM4A",
    (_ftyp(b"qt  ", *[b"qt  "] * 20) + b"x" * 8)[:HEAD] + b"tail", _ftyp(b"qt  ", *[b"qt  "] * 11, b"M4A "),
    b"RIFF\x00\x00\x00\x00WAVE", b"RIFF\x00\x00\x00\x00WAV", b"RIFF\x00\x00\x00\x00wave", b"RIFX\x00\x00\x00\x00WAVE",
    b"OggS", b"Ogg", b"oggS\x00", b"fLaC", b"fLa", b"FLAC",
    b"FORM\x00\x00\x00\x00AIFF", b"FORM\x00\x00\x00\x00AIFC", b"FORM\x00\x00\x00\x00AIF", b"FORM\x00\x00\x00\x00aiff",
    b"", b"\x00" * 64, bytes(range(64)), bytes(range(255, 191, -1)),
]


def heads(tmp_path: Path) -> list[bytes]:
    import test_audio_store as t

    (marked,) = [m for m in t.test_sniff_reads_the_bytes_alone.pytestmark if m.name == "parametrize"]
    found = [head for head, _ in marked.args[1]]
    for fmt in MADE:
        found.append(audio(fmt)[:HEAD])
        tagged = write(tmp_path / f"tagged{FORMATS[fmt]}", fmt, artist="Radiohead", title="Creep")
        found.append(tagged.read_bytes()[:HEAD])
    found += EDGE_HEADS
    return list(dict.fromkeys(found))


def head_records(tmp_path: Path) -> list[dict]:
    out = []
    for head in heads(tmp_path):
        arg = [base64.b64encode(head).decode("ascii")]
        out.append({"fn": "sniff", "args": arg, "out": audio_store.sniff(head)})
        out.append({"fn": "_mpeg_frame", "args": arg, "out": audio_store._mpeg_frame(head)})
        out.append({"fn": "_mp4_audio", "args": arg, "out": audio_store._mp4_audio(head)})
    return out


# --- the names ------------------------------------------------------------------------------------------------------

EDGE_NAMES = [
    "", " ", "\t\n", "a/b/", "a\\", "/", "\\\\server\\share\\song.mp3", "x/../y.mp3", "\x7f\x80\x9f song\u0085.mp3",
    "\u00a0 song \u3000", "\u2028song\u2029", "\u200bsong\u200b", "\ufeffsong.mp3", "\U0001f3b8" * 300,
    "a" * 254 + "\U0001f3b8" + "b", "a" * 300, " " + "a" * 300, "Ünïcödé – Fïlé.flac", "日本語の歌.m4a",
    "song\r\n.mp3", "  \x00  ", "song.mp3\x00.exe", "Cafe\u0301.wav",
]


def display_names() -> list[str]:
    from_tests = ["../../Music/01 Creep.mp3", "C:\\Users\\me\\a\x00b\x1f\n" + "x" * 300 + ".wav", "\x00\x1f/",
                  "song.mp3", "C:\\Users\\me\\creep\x07 take 2.wav", "Creep (Live).flac", "creep take 3.mp3",
                  "wonderwall.opus", "yt.webm", "clip.mp4"]
    return list(dict.fromkeys(from_tests + EDGE_NAMES))


ID16 = "0123456789abcdef"
NAMES = [
    ID16, ID16.upper(), ID16[:15], ID16 + "0", ID16 + "\n", "０１２３４５６７８９ａｂｃｄｅｆ", "",
    *(f".upload-{ID16}{ext}" for ext in (*FORMATS.values(), ".json", ".kept", ".part", ".aif", ".MP3", ".mp3.json")),
    f".upload-{ID16.upper()}.mp3", f".upload-{ID16[:15]}.mp3", f"x.upload-{ID16}.mp3", f".upload-{ID16}.mp3\n",
    f"upload-{ID16}.mp3", f".upload-{ID16}", f".upload-{ID16}.kept\n",
    *(f"12-{ID16}{ext}" for ext in (*FORMATS.values(), ".json", ".kept")), f"0-{ID16}.mp3", f"-{ID16}.mp3",
    f"١٢-{ID16}.mp3", f"12-{ID16.upper()}.mp3", f"12-{ID16[:15]}.mp3", f"12a-{ID16}.mp3", f"12-{ID16}.mp3\n",
    f"999999999999999999999999-{ID16}.flac", f"12-{ID16}.ogg.part",
    f".keep-{ID16}.part", f".keep-{ID16}.part\n", f".keep-{ID16[:15]}.part", f".keep-{ID16.upper()}.part",
    f"keep-{ID16}.part", f".keep-{ID16}.mp3",
]


def _group(m: re.Match | None, *names: str):
    if m is None:
        return None
    return m.group(*names) if len(names) == 1 else list(m.group(*names))


def name_records() -> list[dict]:
    out = [{"fn": "_display_name", "args": [name], "out": audio_store._display_name(name)} for name in display_names()]
    for name in NAMES:
        out.append({"fn": "names", "args": [name], "out": {
            "id": audio_store.ID.fullmatch(name) is not None,
            "piece": _group(audio_store._PIECE.fullmatch(name), "id", "ext"),
            "staged_audio": _group(audio_store._STAGED_AUDIO.fullmatch(name), "id"),
            "marker": _group(audio_store._MARKER.fullmatch(name), "id"),
            "kept": audio_store.KEPT.fullmatch(name) is not None,
            "part": audio_store._PART.fullmatch(name) is not None,
        }})
    return out


# --- what a keep names, and what a stage and a keep write -----------------------------------------------------------


def kept_records(conn, cfg, tmp_path: Path, monkeypatch) -> list[dict]:
    from types import SimpleNamespace

    from conftest import add_song

    monkeypatch.setattr(audio_store, "disk_usage", lambda path: SimpleNamespace(total=10**15, used=0, free=10**15))
    out = []
    for n, fmt in enumerate(MADE):
        song = add_song(conn, "Radiohead", f"Creep {n}")
        source = write(tmp_path / "given" / f"song{FORMATS[fmt]}", fmt, 1.5)
        kept = audio_store.keep(cfg, conn, song, source, move=False)
        digest = hashlib.sha256(source.read_bytes()).hexdigest()
        out.append({"fn": "kept_name", "kw": {"song": song.id, "sha256": digest, "format": fmt}, "out": kept.name})
    return out


TAGS = [{"artist": None, "title": None, "album": None}, {"artist": "Radiohead", "title": "Creep", "album": "Pablo"},
        {"artist": "Ünïcödé \U0001f3b8", "title": "日本語", "album": None}, {"artist": "\"quoted\"\\", "title": "a\u2028b",
                                                                          "album": "\x7f\x00"}]
STAGED = [
    ("01 Creep.mp3", 1234, "MP3", 1.0, 1764245000.0),
    ("Créep \U0001f3b8.flac", 0, "FLAC", 2.0000000001, 1764245000.123456),
    ("a\"b\\c.wav", 128 * 1024 * 1024, "WAV", 1799.9999999999998, 1e-07),
    ("", 1, "Ogg", 1800.0, 1764245012.5),
    ("日本語の歌.m4a", 99, "M4A", 0.1, 17642450001.25),
    ("x" * 255, 5, "AIFF", 3.0e-5, 1.0e16),
]

RECORDS = [
    "", "{}", "[]", "null", "1", "{", "not json",
    *(json.dumps(change) for change in (
        {"name": "a", "size": True, "sha256": "0" * 64, "format": "MP3", "duration": 1.0, "tags": TAGS[0], "at": 1.0},
        {"name": "a", "size": 1.0, "sha256": "0" * 64, "format": "MP3", "duration": 1.0, "tags": TAGS[0], "at": 1.0},
        {"name": "a", "size": 1, "sha256": "0" * 63, "format": "MP3", "duration": 1.0, "tags": TAGS[0], "at": 1.0},
        {"name": "a", "size": 1, "sha256": "A" * 64, "format": "MP3", "duration": 1.0, "tags": TAGS[0], "at": 1.0},
        {"name": "a", "size": 1, "sha256": "0" * 64, "format": "mp3", "duration": 1.0, "tags": TAGS[0], "at": 1.0},
        {"name": "a", "size": 1, "sha256": "0" * 64, "format": "MP3", "duration": True, "tags": TAGS[0], "at": 1.0},
        {"name": "a", "size": 1, "sha256": "0" * 64, "format": "MP3", "duration": "1", "tags": TAGS[0], "at": 1.0},
        {"name": "a", "size": 1, "sha256": "0" * 64, "format": "MP3", "duration": 2, "tags": TAGS[0], "at": 3},
        {"name": "a", "size": 1, "sha256": "0" * 64, "format": "MP3", "duration": 1.0, "tags": TAGS[0], "at": None},
        {"name": "a", "size": 1, "sha256": "0" * 64, "format": "MP3", "duration": 1.0, "tags": TAGS[0], "at": False},
        {"name": "a", "size": 1, "sha256": "0" * 64, "format": "MP3", "duration": 1.0, "tags": TAGS[0]},
        {"name": 5, "size": 1, "sha256": "0" * 64, "format": "MP3", "duration": 1.0, "tags": TAGS[0], "at": 1.0},
        {"name": "a", "size": 1, "sha256": "0" * 64, "format": "MP3", "duration": 1.0, "tags": [], "at": 1.0},
        {"name": "a", "size": 1, "sha256": "0" * 64, "format": "MP3", "duration": 1.0,
         "tags": {"artist": None, "title": None}, "at": 1.0},
        {"name": "a", "size": 1, "sha256": "0" * 64, "format": "MP3", "duration": 1.0,
         "tags": {"artist": None, "title": None, "album": None, "year": None}, "at": 1.0},
        {"name": "a", "size": 1, "sha256": "0" * 64, "format": "MP3", "duration": 1.0,
         "tags": {"artist": 1, "title": None, "album": None}, "at": 1.0},
        {"name": "a", "size": -1, "sha256": "0" * 64, "format": "MP3", "duration": -1.0, "tags": TAGS[0], "at": -1.0,
         "more": "kept"},
    )),
    '{"name": "a", "size": 100000000000000000000000000000, "sha256": "' + "0" * 64 + '", "format": "MP3", '
    '"duration": NaN, "tags": {"artist": null, "title": null, "album": null}, "at": Infinity}',
    '{"name": "a", "size": 1, "sha256": "' + "0" * 64 + '", "format": "MP3", "duration": 1e400, '
    '"tags": {"artist": null, "title": null, "album": null}, "at": -0.0, "name": 3}',
    '{"name": "a", "size": 1, "sha256": "' + "0" * 64 + '\\n", "format": "MP3", "duration": 1.0, '
    '"tags": {"artist": null, "title": null, "album": null}, "at": 1.0}',
    '{"name": "\\ud800", "size": 1, "sha256": "' + "0" * 64 + '", "format": "MP3", "duration": 1.0, '
    '"tags": {"artist": null, "title": null, "album": null}, "at": 1.0}',
]

MARKERS = [
    json.dumps({"kept": f"3-{ID16}.mp3", "song": 3, "at": 1764245000.5}),
    json.dumps({"kept": f"3-{ID16}.mp3", "song": 3, "at": 2}),
    json.dumps({"kept": f"3-{ID16}.mp3", "song": True, "at": 2.0}),
    json.dumps({"kept": f"3-{ID16}.mp3", "song": 3.0, "at": 2.0}),
    json.dumps({"kept": f"3-{ID16}.mp3", "song": 3, "at": "2"}),
    json.dumps({"kept": f"3-{ID16}.mp3", "song": 3, "at": None}),
    json.dumps({"kept": f"3-{ID16}.json", "song": 3, "at": 2.0}),
    json.dumps({"kept": f"../3-{ID16}.mp3", "song": 3, "at": 2.0}),
    json.dumps({"kept": 3, "song": 3, "at": 2.0}),
    json.dumps({"song": 3, "at": 2.0}),
    json.dumps({"kept": f"3-{ID16}.mp3", "song": -4, "at": -2.0, "other": 1}),
    json.dumps([f"3-{ID16}.mp3", 3, 2.0]), "", "{", "null",
]


def record_records() -> list[dict]:
    out = []
    for (name, size, fmt, duration, at), tags in zip(STAGED, TAGS * 2, strict=False):
        up = Staged(ID16, Path("x"), name, size, hashlib.sha256(name.encode()).hexdigest(), fmt, duration, tags, at)
        text = json.dumps(up.record())  # stage's
        kw = {"name": name, "size": size, "sha256": up.sha256, "format": fmt, "duration": duration, "tags": tags,
              "at": at}
        out.append({"fn": "record", "kw": kw, "out": text})
        out.append({"fn": "_read_record", "args": [text], "out": True})
    for text in RECORDS:
        out.append({"fn": "_read_record", "args": [text], "out": _reads_as_record(text)})
    for kept, song, at in ((f"3-{ID16}.mp3", 3, 1764245000.123456), (f"12-{'f' * 16}.aiff", 12, 1e-07),
                           (f"7-{ID16}.ogg", 7, 17642450001.0)):
        text = json.dumps({"kept": kept, "song": song, "at": at})  # _write_marker's
        out.append({"fn": "marker", "kw": {"kept": kept, "song": song, "at": at}, "out": text})
        out.append({"fn": "_read_marker", "args": [text], "out": _marker_read(text)})
    for text in MARKERS:
        out.append({"fn": "_read_marker", "args": [text], "out": _marker_read(text)})
    return out


def _reads_as_record(text: str) -> bool:
    import tempfile

    with tempfile.TemporaryDirectory() as d:
        path = Path(d) / ".upload-0123456789abcdef.json"
        path.write_bytes(text.encode("utf-8", "surrogatepass"))
        return audio_store._read_record(path) is not None


def _marker_read(text: str) -> dict | None:
    import tempfile

    with tempfile.TemporaryDirectory() as d:
        (Path(d) / f".upload-{ID16}.kept").write_text(text, encoding="utf-8")
        (Path(d) / f".upload-{ID16}.json").write_text("{}", encoding="utf-8")
        found = audio_store._read_marker(Path(d), ID16)
        return None if found is None else {"kept": found.path.name, "song": found.song, "at": found.at}


# --- given_file -----------------------------------------------------------------------------------------------------

KEPT_NAME = f"3-{ID16}.mp3"
GIVEN = [
    ([["state/audio/" + KEPT_NAME, "file"]], "state/audio/" + KEPT_NAME),
    ([["elsewhere/audio/" + KEPT_NAME, "file"]], "elsewhere/audio/" + KEPT_NAME),
    ([["audio/" + KEPT_NAME, "file"]], "audio/" + KEPT_NAME),
    ([["real/x.mp3", "file"], ["state/audio/" + KEPT_NAME, "link"]], "state/audio/" + KEPT_NAME),
    ([["state/audio/" + KEPT_NAME, "folder"]], "state/audio/" + KEPT_NAME),
    ([["state/audio/other.mp3", "file"]], "state/audio/" + KEPT_NAME),
    ([["state/audios/" + KEPT_NAME, "file"]], "state/audios/" + KEPT_NAME),
    ([["state/Audio/" + KEPT_NAME, "file"]], "state/Audio/" + KEPT_NAME),
    ([["state/audio/notes.mp3", "file"]], "state/audio/notes.mp3"),
    ([["state/audio/.upload-" + ID16 + ".mp3", "file"]], "state/audio/.upload-" + ID16 + ".mp3"),
    ([["state/audio/" + KEPT_NAME, "file"]], "state/audio/../audio/" + KEPT_NAME),
    ([["state/audio/" + KEPT_NAME, "file"]], None),
    ([], "state/audio/" + KEPT_NAME),
]


def given_records(tmp_path: Path) -> list[dict]:
    out = []
    for n, (entries, path) in enumerate(GIVEN):
        root = tmp_path / f"given-{n}"
        first = None
        for rel, kind in entries:
            at = root / rel
            at.parent.mkdir(parents=True, exist_ok=True)
            if kind == "file":
                at.write_bytes(b"audio")
                first = first or at
            elif kind == "link":
                at.symlink_to(first)
            else:
                at.mkdir()
        answer = audio_store.given_file(str(root / path) if path is not None else None)
        out.append({"fn": "given_file", "kw": {"entries": entries, "path": path}, "out": answer})
    return out


# --- a merge keeps the file given -----------------------------------------------------------------------------------

# Who holds what before the merge: the older record's audio, the newer's, each an upload ("given", its mtime), a
# purchase ("bought") or none; and the names they were given under.
MERGES = [
    ("given on the newer", None, ("given", 5.0), {"newer": "given to the newer.mp3"}),
    ("given on the older", ("given", 5.0), None, {"older": "given to the older.mp3"}),
    ("given on the newer over a purchase", ("bought", 9.0), ("given", 5.0), {"newer": "newer.mp3"}),
    ("given on the older, a purchase on the newer", ("given", 5.0), ("bought", 9.0), {"older": "older.mp3"}),
    ("two given, the newer's later", ("given", 5.0), ("given", 7.5), {"older": "first.mp3", "newer": "last.wav"}),
    ("two given, the older's later", ("given", 7.5), ("given", 5.0), {"older": "last.wav", "newer": "first.mp3"}),
    ("two given at once", ("given", 5.0), ("given", 5.0), {"older": "older.mp3", "newer": "newer.mp3"}),
    ("given on the newer, its name none", None, ("given", 5.0), {"older": "an old name.mp3"}),
    ("given on the newer, its file gone", None, ("gone", 5.0), {"newer": "gone.mp3"}),
    ("given on the newer, its mtime none", ("given", 5.0), ("given", None), {"newer": "newer.mp3"}),
    ("a purchase on the newer", None, ("bought", 5.0), {}),
]


def merge_records(conn_factory, tmp_path: Path) -> list[dict]:
    from test_songs import older_song

    from caracole.songs import ensure_current_keys, get_song, update_song

    out = []
    for n, (case, older_audio, newer_audio, names) in enumerate(MERGES):
        conn = conn_factory()
        state = tmp_path / f"merge-{n}"
        records = {}
        older = older_song(conn, "Los Enanitos Verdes", "Lamento Boliviano", "los-enanitos-verdes/lamento-boliviano",
                           source="wanted", source_id="los-enanitos-verdes/lamento-boliviano")
        newer = older_song(conn, "Enanitos Verdes", "Lamento Boliviano", "enanitos-verdes/lamento-boliviano",
                           source="wanted", source_id="enanitos-verdes/lamento-boliviano",
                           added_at="2026-09-05T00:00:00Z")
        files = []
        for who, song_id, held in (("older", older, older_audio), ("newer", newer, newer_audio)):
            if held is None:
                continue
            kind, mtime = held
            if kind == "bought":
                rel = f"Music/{who}.flac"
            else:
                rel = f"audio/{song_id}-{hashlib.sha256(who.encode()).hexdigest()[:16]}.mp3"
            if kind != "gone":
                (state / rel).parent.mkdir(parents=True, exist_ok=True)
                (state / rel).write_bytes(audio("MP3"))
                files.append(rel)
            update_song(conn, song_id, audio_path=str(state / rel), audio_mtime=mtime)
            records[who] = song_id
        kv = {}
        for who, name in names.items():
            song_id = older if who == "older" else newer
            conn.execute("INSERT INTO kv (key, value) VALUES (?, ?)", (f"{audio_store.NAME_KEY}{song_id}", name))
            kv[f"{audio_store.NAME_KEY}{song_id}"] = name
        rows = []
        for song_id in (older, newer):
            s = get_song(conn, song_id)
            rows.append({"id": s.id, "key": s.key, "artist": s.artist, "title": s.title,
                         "artists": json.dumps(s.artists), "source_ids": json.dumps(s.source_ids),
                         "added_at": s.added_at, "created_at": s.added_at, "updated_at": s.added_at,
                         "audio_path": _spelled(s.audio_path, state), "audio_mtime": s.audio_mtime})
        ensure_current_keys(conn)
        after = [{"id": s.id, "audio_path": _spelled(s.audio_path, state), "audio_mtime": s.audio_mtime}
                 for s in (get_song(conn, i) for (i,) in conn.execute("SELECT id FROM songs ORDER BY id"))]
        names_after = dict(conn.execute("SELECT key, value FROM kv WHERE key LIKE 'audio:name:%' ORDER BY key"))
        out.append({"fn": "merge", "case": case, "kw": {"songs": rows, "files": files, "kv": kv},
                    "out": {"songs": after, "kv": names_after}})
        conn.close()
    return out


def _spelled(path: str | None, state: Path) -> str | None:
    if path is None:
        return None
    assert path.startswith(str(state) + "/"), path
    return "{state}/" + path[len(str(state)) + 1:]


# --- the vector -----------------------------------------------------------------------------------------------------


def records(conn, cfg, tmp_path: Path, monkeypatch, conn_factory) -> list[dict]:
    return (head_records(tmp_path) + name_records() + kept_records(conn, cfg, tmp_path, monkeypatch)
            + record_records() + given_records(tmp_path) + merge_records(conn_factory, tmp_path))


@pytest.fixture
def conn_factory(tmp_path):
    """Fresh databases, one a call, as conftest's ``conn`` makes one."""
    from conftest import migrated_database

    from caracole import db

    made = []

    def fresh():
        path = tmp_path / "databases" / f"{len(made)}.sqlite"
        path.parent.mkdir(exist_ok=True)
        path.write_bytes(migrated_database())
        made.append(path)
        return db.connect(path)

    return fresh


def test_the_audio_store_vectors(conn, cfg, tmp_path, monkeypatch, conn_factory):
    check(VECTOR, jsonl(records(conn, cfg, tmp_path, monkeypatch, conn_factory), corpus="library/audio_store",
                        made_by=MADE_BY))


def test_the_heads_reach_every_format_and_none(tmp_path):
    answers = {r["out"] for r in head_records(tmp_path) if r["fn"] == "sniff"}
    assert answers == {*FORMATS, None}


def test_the_merges_reach_each_rule(conn_factory, tmp_path):
    by_case = {r["case"]: r for r in merge_records(conn_factory, tmp_path)}
    newer = by_case["given on the newer"]["out"]
    assert len(newer["songs"]) == 1 and newer["songs"][0]["audio_path"].startswith("{state}/audio/")
    assert by_case["two given, the newer's later"]["out"]["kv"] == {f"{audio_store.NAME_KEY}1": "last.wav"}
    assert by_case["given on the newer, its file gone"]["out"]["songs"][0]["audio_path"] is None
    assert by_case["a purchase on the newer"]["out"]["songs"][0]["audio_path"] is None
