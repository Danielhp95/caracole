"""``caracole audio --upload`` for the phone: the job's words as data, and whole jobs recorded, for :server's
``AudioRunner`` (the chords-on-the-phone design's §3.2, the plan's E21) to agree with.

**Data** (``data/caracole/library/audio_sheet.json``, ``audio_sheet_json``): audio_sheet.py's ``STAGES``, run.py's
``STEPS``, youtube_sheet.py's ``HOLDS``, and every word of the job the phone says as the computer does, by its
constant: audio_sheet.py's (``SAME_FILE``, ``KEPT_AS``, ``REPLACES``, ``GIVEN_BEFORE``, ``CANT_KEEP``,
``THE_UPLOAD``), youtube_sheet.py's (``IGNORED``, ``HAS_SHEET``, ``IN_BOOK``, ``NOT_OFFERED``, ``NOT_HERE``,
``NO_AUDIO``), transcript.py's (``PHONE``, ``LYRICS_ARE``), transcribe_job.py's ``NO_VOCALS``, staged.py's (``LEFT``
with ``StagedRun.MAKING``, ``BUG``, ``UP_TO_DATE``, ``NO_SHEET``, ``RELAY_FAILED``) and commands/audio.py's
(``NO_CHORDS``, ``REFUSED``).

**Vectors** (``vectors/lookup/audio_sheet.jsonl``), a header, then a record a line, each a scenario record
(helpers/scenario.py ``record_lookup``) of a world of test_conformance_lookup_scenarios.py's (``World``: Calla Lake's
River Road, the fake lyrics sites by address), each with:

- ``kw``: ``request`` (``artist``, ``title``, ``album``, ``duration``, ``upload``: audio_sheet.AudioRequest's, the
  upload's id), ``heard`` (what the fake models heard: ``sheet.heard_record`` of the fake recognizer's chords, its
  beats, and the length music.py reads, which the phone's fake ChordModels answers), ``hearing`` ("ok", "audio": the
  recognizer raising, a file the models can't read; "setup": no recognizer, the models' setup failing), ``audio``
  (``{format, duration, tags}``, what the phone's examiner reads of the file: the store's record's), and ``store``
  (``{name: {"base64"} | {"text"}, …}``, the files of ``state_dir/audio/`` before the job, with ``mtime``, the
  staged file's, fixed so that the song's ``audio_mtime`` is the same on both sides);
- ``out.result``: ``{result, progress, python}``, the job's ends (``states``, ``details``), the song, the files
  readable, the stages as told in order, worded as the phone words them (``phone_end``: the song stage of a song
  added ``get.ADDED``; vocals and words the phone's skip, ``transcript.PHONE``; the pdf ``get.NO_PDFS``, the pages
  ``get.LIBRARY_PAGE``), ``python`` Python's own ends of what was so rewritten;
- ``out.store``: the folder's files after, each audio file by its SHA-256, a record or a marker by ``"record"`` or
  ``"marker"``;
- ``out.maker``: the version's maker members Python wrote (``made_on``, ``made_by``, ``models``, ``runtime``), each
  side's own, taken out of the ``versions`` rows' raw (``audio_name`` and ``audio_sha16`` stay: the same file);
- ``apart``: what the replay compares apart, by design (the brief's): ``lyrics``, whose words on the phone are
  get.py's at the lookup pace where the computer's job asks at the bulk pace in youtube_sheet.py's; ``chords`` for a
  hearing that fails (the phone's words, ``audio the phone can't read: …`` and the setup's, are its own); the
  events' runs and the pauses (the bulk pace's against the lookup's); and ``kv`` prefixes Python writes and the
  phone doesn't (``autochords:status``, the to-do page's; ``autochords:failed:``, which the phone never records).

Every path under the world's state folder is written ``{state}``, which the replay reads as its own.

The cases: a song new to the library, its timed lyrics found and the chords over them; one the library has, its line
of no length (LRCLIB asked with the file's), plain lyrics; no lyrics anywhere (chords only); an instrumental; an
ignored song and one with a human sheet, refused; the same job again once done (its file's audio already, the sheet
up to date); the same job again after a keep cut off between its move and the song's row (``adopt``); the models
failing on the file, and their setup failing. And ``fn: "caracole.autochords.sheet_lyrics.relay_onto_sheets"``: a
sheet the phone made (its ``made_by`` the phone's id, ``kw.own``), chords only, then the song's lyrics found and the
sheet laid out again on the computer: the phone's own re-lay of it (its kv ``sync:id`` the sheet's maker) must be the
same rows and bytes, as the phone notes no transcript or nothing-sung verdict of its own (Relay.notedOf's fallback is
the sheet's own record).

Regenerate with ``CARACOLE_CORPUS=write nix develop -c pytest -q -n 0 tests/test_conformance_audio_sheet.py``.
"""

from __future__ import annotations

import base64
import hashlib
import itertools
import json
import os
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest import mock

import pytest
from helpers.audio_files import audio
from helpers.corpus import DATA, VECTORS, check, fixture_ref, jsonl
from helpers.scenario import LEAVES_OUT, record_lookup
from test_conformance_lookup_scenarios import (
    AZLYRICS,
    JSON,
    NOW,
    STAMP,
    Heard,
    Sites,
    World,
    clock,
    lrclib_record,
    ok,
    phone_end,
    status,
)

MADE_BY = "tests/test_conformance_audio_sheet.py"
AUDIO_SHEET_JSON = DATA / "library" / "audio_sheet.json"
VECTOR = VECTORS / "lookup" / "audio_sheet.jsonl"

ARTIST, TITLE = "Calla Lake", "River Road"
LENGTH = 213.0
MTIME = 1764000000  # the staged file's time on the disk, the song's audio_mtime once kept
STAGED_AT = 1764000100.25  # time.time() as the store stages and keeps
MAKER = ("made_on", "made_by", "models", "runtime")
PHONE_ID = "a1b2c3d4e5f60718"
OWN = "c0ffee0000000001"  # each world's kv sync:id, the side the job runs on: the replay's own too


def audio_sheet_json() -> str:
    from caracole import audio_sheet, staged, transcribe_job, youtube_sheet
    from caracole.autochords import run, transcript
    from caracole.commands import audio as audio_cmd

    words = {
        "same_file": audio_sheet.SAME_FILE, "kept_as": audio_sheet.KEPT_AS, "replaces": audio_sheet.REPLACES,
        "given_before": audio_sheet.GIVEN_BEFORE, "cant_keep": audio_sheet.CANT_KEEP,
        "the_upload": audio_sheet.THE_UPLOAD,
        "ignored": youtube_sheet.IGNORED, "has_sheet": youtube_sheet.HAS_SHEET, "in_book": youtube_sheet.IN_BOOK,
        "not_offered": youtube_sheet.NOT_OFFERED, "not_here": youtube_sheet.NOT_HERE,
        "no_audio": youtube_sheet.NO_AUDIO,
        "phone": transcript.PHONE, "lyrics_are": transcript.LYRICS_ARE, "no_vocals": transcribe_job.NO_VOCALS,
        "left": staged.LEFT, "making": staged.StagedRun.MAKING, "bug": staged.BUG, "up_to_date": staged.UP_TO_DATE,
        "no_sheet": staged.NO_SHEET, "relay_failed": staged.RELAY_FAILED,
        "no_chords": audio_cmd.NO_CHORDS, "refused": audio_cmd.REFUSED,
    }
    data = {"stages": [list(s) for s in audio_sheet.STAGES], "steps": list(run.STEPS),
            "holds": dict(youtube_sheet.HOLDS), "words": words,
            "pdf": {"no_pdfs": staged.NO_PDFS, "pages_made": staged.PAGES_MADE, "library_page": staged.LIBRARY_PAGE}}
    return json.dumps(data, ensure_ascii=False, indent=1) + "\n"


# --- the fake models ----------------------------------------------------------------------------------------------

CHORDS = [(0.0, 10.0, "Am"), (10.0, 20.0, "F"), (20.0, 30.0, "C"), (30.0, 40.0, "G")]
BEATS = [i * 0.5 for i in range(81)]
DOWNBEATS = [i * 2.0 for i in range(21)]


class Recognizer:
    name = "btc_large_voca@1673d23f8f9a55ae"
    runtime = "torch 2.13.0"

    def __init__(self, fail: bool = False):
        self.fail = fail

    def recognize(self, path):
        from caracole.autochords.merge import ChordSegment

        if self.fail:
            raise RuntimeError("Error opening the file: Format not recognised.")
        return [ChordSegment(*c) for c in CHORDS]


class Beats:
    name = "beat_this final0@8c328b45f59d8dd3"

    def __call__(self, path):
        return BEATS, DOWNBEATS


def heard_of(length: float) -> dict[str, Any]:
    from caracole.autochords.merge import ChordSegment
    from caracole.autochords.sheet import Heard as Hearing
    from caracole.autochords.sheet import heard_record

    return heard_record(Hearing([ChordSegment(*c) for c in CHORDS], BEATS, DOWNBEATS, length))


# --- a world with a staged upload ---------------------------------------------------------------------------------


class Ids:
    """audio_store's ``secrets`` with ids of a count (the same on every run)."""

    def __init__(self) -> None:
        self.count = itertools.count(1)

    def token_hex(self, n: int) -> str:
        return f"{next(self.count):0{2 * n}x}"


def frozen_store():
    """audio_store's clock and ids fixed, and room on the disk (its ``ROOM`` is a GiB)."""
    from caracole import audio_store

    return [mock.patch.object(audio_store, "secrets", Ids()),
            mock.patch.object(audio_store, "time", SimpleNamespace(time=lambda: STAGED_AT)),
            mock.patch.object(audio_store, "disk_usage",
                              lambda path: SimpleNamespace(total=10**15, used=0, free=10**15))]


class Patched:
    def __init__(self, patches):
        self.patches = patches

    def __enter__(self):
        for p in self.patches:
            p.start()

    def __exit__(self, *exc):
        for p in reversed(self.patches):
            p.stop()


def staged(w: World, fmt: str = "M4A", name: str = "river road.m4a", **tags: str) -> str:
    """An upload staged as caracole serve stages one, its file's time [MTIME]; its id."""
    from caracole import audio_store
    from helpers.audio_files import write

    data = audio(fmt, LENGTH)
    if tags:
        data = write(w.dir / "tagged" / name, fmt, LENGTH, **tags).read_bytes()
    with Patched(frozen_store()):
        up = audio_store.stage(w.cfg, data, name, named=set())
    os.utime(up.path, (MTIME, MTIME))
    return up.id


def store_files(w: World) -> dict[str, Any]:
    """The folder's files as a record carries them: each with its bytes (a text as text) and its time."""
    root = w.cfg.state_dir / "audio"
    out: dict[str, Any] = {}
    for path in sorted(root.iterdir()) if root.is_dir() else []:
        data = path.read_bytes()
        try:
            body: dict[str, Any] = {"text": data.decode("utf-8")} if path.suffix in (".json", ".kept") else {
                "base64": base64.b64encode(data).decode("ascii")}
        except UnicodeDecodeError:
            body = {"base64": base64.b64encode(data).decode("ascii")}
        out[path.name] = {**body, "mtime": path.stat().st_mtime} if "base64" in body else body
    return out


def store_after(w: World) -> dict[str, str]:
    root = w.cfg.state_dir / "audio"
    out: dict[str, str] = {}
    for path in sorted(root.iterdir()) if root.is_dir() else []:
        if path.name.endswith(".json"):
            out[path.name] = "record"
        elif path.name.endswith(".kept"):
            out[path.name] = "marker"
        else:
            out[path.name] = hashlib.sha256(path.read_bytes()).hexdigest()
    return out


def placed(value: Any, state: str) -> Any:
    """Every text of ``value`` with the world's state folder written ``{state}``."""
    if isinstance(value, str):
        return value.replace(state, "{state}")
    if isinstance(value, list):
        return [placed(v, state) for v in value]
    if isinstance(value, dict):
        return {k: placed(v, state) for k, v in value.items()}
    return value


def phone_words(said: dict[str, Any]) -> dict[str, Any]:
    """The job's ends and stages as the phone words them (the module's docstring), Python's kept in ``python``."""
    from caracole.autochords import transcript
    from caracole.transcribe_job import NO_VOCALS
    from caracole.youtube_sheet import NOT_HERE

    result, progress = said["result"], said["progress"]
    python: dict[str, list[str]] = {}

    def end(name: str, state: str, detail: str) -> tuple[str, str] | None:
        if name == "vocals" and state == "skipped" and result["details"].get("vocals", "").startswith(
                ("not transcribed: turned off", "not transcribed here:")):
            return "skipped", NOT_HERE.format(reason=transcript.PHONE)
        if name == "words" and state == "skipped" and detail:
            return "skipped", NO_VOCALS
        if name == "pdf" and (state, detail) == ("skipped", "no sheet"):
            return None  # no sheet made: the same on both
        if name in ("song", "pdf", "pages"):
            return phone_end(name, state, detail)
        return None

    for name in list(result["details"]):
        e = end(name, result["states"][name], result["details"][name])
        if e is not None and list(e) != [result["states"][name], result["details"][name]]:
            python[name] = [result["states"][name], result["details"][name]]
            result["states"][name], result["details"][name] = e
    for event in progress:
        if event[0] == "stage" and event[2] != "running":
            e = end(event[1], event[2], event[3])
            if e is not None:
                event[2], event[3] = e
    return {**said, "python": python}


def lake_sites(**kw: Any) -> Sites:
    """River Road's lyrics on LRCLIB (timed, 213 s), none on Megalobiz or AZLyrics."""
    defaults = {"lrclib_get": ok(lrclib_record(ARTIST, TITLE, LENGTH), JSON),
                "lrclib_search": ok(fixture_ref("lrclib/search_empty.json"), JSON),
                "megalobiz_search": ok(fixture_ref("megalobiz/search_empty.json"), JSON),
                "pages": {f"{AZLYRICS}c/callalake.html": status(404, "<html><title>Not found</title></html>")}}
    return Sites(**{**defaults, **kw})


def none_found() -> dict[str, Any]:
    return {"status": 404, "headers": JSON, "body": '{"code":404,"name":"TrackNotFound","message":"Failed to find '
            'specified track"}'}


def job(w: World, case: str, upload: str, sites: Sites, *, hearing: str = "ok",
        apart: dict[str, Any] | None = None) -> dict[str, Any]:
    """``caracole audio --upload`` of River Road, recorded (the module's docstring): the request as the command makes
    it, its album the staged upload's tag, its length the upload's (or, an upload its marker says was kept, the kept
    file's)."""
    from caracole import audio_store
    from caracole.audio_sheet import AudioRequest, make_audio_sheet

    heard = Heard()
    before = store_files(w)
    found = audio_store.staged(w.cfg, upload) if not audio_store.gone(w.cfg, upload) else None
    album = found.tags.get("album") if found is not None else None
    duration = found.duration if found is not None else LENGTH
    request = AudioRequest(ARTIST, TITLE, upload=upload, album=album, duration=duration)

    def call() -> dict[str, Any]:
        recognizer = None if hearing == "setup" else Recognizer(fail=hearing == "audio")
        result = make_audio_sheet(w.cfg, request, heard, runner=None, recognizer=recognizer, beats_fn=Beats(),
                                  hears=False, now=NOW, clock=lambda: 0.0)
        return {"result": {"song_id": result.song_id, "display": result.display, "states": dict(result.states),
                           "details": dict(result.details), "files": dict(result.files),
                           "exit": 0 if result.ok else 1}, "progress": heard.events}

    leaves = {"kv": [*LEAVES_OUT["kv"], "autochords:status", "autochords:failed:"], "files": LEAVES_OUT["files"]}
    with Patched(frozen_store()):
        made = record_lookup(w.cfg, fn="caracole.audio_sheet.make_audio_sheet", call=call, answers=sites, now=NOW,
                             case=case, kw={}, settle=w.settled(NOW), leaves_out=leaves)
    state = str(w.cfg.state_dir)
    record = found.duration if found is not None else LENGTH
    made["kw"] = {"own": OWN, "request": {"artist": ARTIST, "title": TITLE, "album": album, "duration": duration,
                              "upload": upload},
                  "heard": heard_of(record), "hearing": hearing,
                  "audio": {"format": found.format if found else "M4A", "duration": record,
                            "tags": dict(found.tags) if found else {}},
                  "store": before}
    assert "out" in made, made.get("raises")
    out = made["out"]
    out["result"] = phone_words(out["result"])
    out["store"] = store_after(w)
    out["maker"] = None
    for row in out["rows"].get("versions", []):
        raw = json.loads(row["raw"])
        if "made_on" in raw:
            out["maker"] = {k: raw.pop(k) for k in MAKER if k in raw}

            row["raw"] = json.dumps(raw, ensure_ascii=False)
    made["apart"] = {"lyrics": True, "events_run": True, "pauses": True, "kv": leaves["kv"][1:], **(apart or {})}
    return placed(made, state)


def world(tmp: Path, name: str) -> World:
    from caracole import db

    w = World(tmp, name)
    w.cfg.state_dir.mkdir(parents=True, exist_ok=True)
    db.kv_set(w.conn, "sync:id", OWN)
    return w


def new_song(tmp: Path) -> dict[str, Any]:
    w = world(tmp, "new")
    up = staged(w, album="Pruebas")
    return job(w, "a song new to the library: added with the file's album and length, its timed lyrics found and "
                  "the chords over them", up, lake_sites())


def known_song(tmp: Path) -> dict[str, Any]:
    w = world(tmp, "known")
    w.song(duration_ms=None)
    up = staged(w)
    sites = lake_sites(lrclib_get=ok(lrclib_record(ARTIST, TITLE, LENGTH, synced=False), JSON))
    return job(w, "a song of the library with no length on its line: LRCLIB asked with the file's, its plain lyrics, "
                  "Megalobiz none timed", up, sites)


def no_lyrics(tmp: Path) -> dict[str, Any]:
    w = world(tmp, "none")
    w.song()
    up = staged(w)
    return job(w, "no lyrics on any site: chords only", up, lake_sites(lrclib_get=none_found()))


def instrumental(tmp: Path) -> dict[str, Any]:
    w = world(tmp, "instrumental")
    w.song()
    up = staged(w)
    record = json.loads(lrclib_record(ARTIST, TITLE, LENGTH))
    record.update(instrumental=True, plainLyrics=None, syncedLyrics=None)
    return job(w, "LRCLIB says it is instrumental: chords only, no other site asked", up,
               lake_sites(lrclib_get=ok(json.dumps(record), JSON)))


def ignored(tmp: Path) -> dict[str, Any]:
    from caracole.overrides import add_ignore

    w = world(tmp, "ignored")
    w.song()
    w.overrides(lambda path: add_ignore(path, f"{ARTIST} - {TITLE}"))
    up = staged(w)
    return job(w, "an ignored song: refused, nothing kept", up, lake_sites())


def human_sheet(tmp: Path) -> dict[str, Any]:
    from caracole.library import keep_file
    from caracole.songs import get_song
    from caracole.versions import upsert_version

    w = world(tmp, "human")
    song = get_song(w.conn, w.song())
    vid = upsert_version(w.conn, provider="ug", tab_id="101", song_id=song.id, slot="sheet", kind="chords",
                         rating=4.8, votes=120, version=1, label=None, url="https://tabs.ultimate-guitar.com/tab/x",
                         raw={}, now=STAMP)
    keep_file(w.conn, w.cfg.library_dir, song=song, version_id=vid, name="sheet.txt", data=b"[ch]G[/ch]\nHi", rank=1)
    w.conn.execute("UPDATE files SET created_at = ?", (STAMP,))
    up = staged(w)
    return job(w, "a song with a human sheet: refused, nothing kept", up, lake_sites())


def again_done(tmp: Path) -> dict[str, Any]:
    w = world(tmp, "again")
    w.song()
    up = staged(w)
    job(w, "the first run", up, lake_sites())
    w.conn.execute("UPDATE files SET created_at = ?", (STAMP,))
    return job(w, "the same job again once it was done: the file's audio already, its sheet up to date", up,
               lake_sites())


def again_moved(tmp: Path) -> dict[str, Any]:
    """A keep cut off after its move, before the song's row named the file: the marker, the kept file, the record."""
    from caracole import audio_store
    from caracole.songs import get_song

    w = world(tmp, "moved")
    song = get_song(w.conn, w.song())
    up = staged(w)
    with Patched(frozen_store()):
        source = audio_store.staged(w.cfg, up).path
        root = source.parent
        digest = hashlib.sha256(source.read_bytes()).hexdigest()[:16]
        kept = root / f"{song.id}-{digest}{source.suffix}"
        audio_store._write_marker(root, up, kept, song.id)
        os.replace(source, kept)
    return job(w, "the same job again after a keep cut off between its move and the song's row: the keep finished "
                  "by its marker", up, lake_sites())


def models_fail(tmp: Path, hearing: str) -> dict[str, Any]:
    w = world(tmp, f"fails-{hearing}")
    w.song()
    up = staged(w)
    said = {"audio": "the models fail on the file (one they can't decode): the chords fail, the song stays as it "
                     "was but its audio and lyrics",
            "setup": "the models' setup fails: the chords fail, nothing recorded against the song"}[hearing]
    return job(w, said, up, lake_sites(), hearing=hearing, apart={"chords": True})


def phone_made_relaid(tmp: Path) -> dict[str, Any]:
    """A sheet the phone made, chords only, then its song's lyrics found: laid out again on the computer."""
    from caracole.autochords import run
    from caracole.autochords.merge import ChordSegment
    from caracole.autochords.sheet import Heard as Hearing
    from caracole.autochords.sheet import Maker, make_sheet
    from caracole.autochords.sheet_lyrics import relay_onto_sheets
    from caracole.lyrics import Lyrics, LyricsResult, _record
    from caracole.overrides import load_overrides
    from caracole.songs import get_song, update_song
    from helpers.audio_files import given

    w = world(tmp, "relaid")
    with clock(STAMP):
        song = get_song(w.conn, w.song())
        path = given(w.conn, w.cfg.state_dir, song, "M4A", LENGTH)
        os.utime(path, (MTIME, MTIME))
        update_song(w.conn, song.id, audio_mtime=float(MTIME))
        song = get_song(w.conn, song.id)
        heard = Hearing([ChordSegment(*c) for c in CHORDS], BEATS, DOWNBEATS, LENGTH)
        made = make_sheet(song, heard)
        maker = Maker("phone", PHONE_ID, {"chords": Recognizer.name, "beats": Beats.name + " fp16"},
                      "onnxruntime 1.32.0", "river road.m4a", hashlib.sha256(path.read_bytes()).hexdigest()[:16])
        run._keep(w.conn, w.cfg, song, made.text, made.used, made.key, STAMP, heard=made.heard, maker=maker)
        w.conn.execute("UPDATE files SET created_at = ?", (STAMP,))
        song = get_song(w.conn, song.id)
        found = Lyrics.from_record(json.loads(lrclib_record(ARTIST, TITLE, LENGTH)))
        _record(w.conn, w.cfg.library_dir, song, LyricsResult("found", found), STAMP)

    def call() -> list[int]:
        return [s.id for s in relay_onto_sheets(w.conn, w.cfg, load_overrides(w.cfg.overrides_file))]

    made_record = record_lookup(w.cfg, fn="caracole.autochords.sheet_lyrics.relay_onto_sheets", call=call,
                                answers={}, now=NOW, case="a sheet the phone made, chords only, its song's lyrics "
                                "found since: laid out again over them alike on the computer and on the phone",
                                kw={}, settle=w.settled(NOW))
    made_record["kw"] = {"own": PHONE_ID}
    return placed(made_record, str(w.cfg.state_dir))


def records(tmp: Path) -> list[dict[str, Any]]:
    return [new_song(tmp), known_song(tmp), no_lyrics(tmp), instrumental(tmp), ignored(tmp), human_sheet(tmp),
            again_done(tmp), again_moved(tmp), models_fail(tmp, "audio"), models_fail(tmp, "setup"),
            phone_made_relaid(tmp)]


@pytest.fixture(scope="module")
def made(tmp_path_factory) -> list[dict[str, Any]]:
    return records(tmp_path_factory.mktemp("audio-sheet"))


def test_audio_sheet_json_is_the_jobs_words():
    check(AUDIO_SHEET_JSON, audio_sheet_json())


def test_the_vector_is_what_caracole_audio_does(made):
    check(VECTOR, jsonl(made, corpus="lookup", made_by=MADE_BY))


def test_the_vector_is_the_same_on_another_run(made, tmp_path):
    assert jsonl(records(tmp_path), corpus="lookup", made_by=MADE_BY) == jsonl(made, corpus="lookup",
                                                                               made_by=MADE_BY)


def _ends(record: dict[str, Any]) -> dict[str, list[str]]:
    r = record["out"]["result"]["result"]
    return {k: [r["states"][k], r["details"][k]] for k in r["states"]}


def test_the_cases_come_to_what_they_say(made):
    from caracole.autochords import transcript

    by = {r["case"].split(":")[0]: r for r in made}
    new = _ends(by["a song new to the library"])
    assert new["song"] == ["done", "added to the book"]
    assert new["audio"] == ["done", "kept as its audio: M4A, 3:33"]
    assert new["lyrics"] == ["done", "found, timed"]
    assert new["vocals"] == ["skipped", "not transcribed: its lyrics are found"]
    assert new["chords"] == ["done", "chords over the lyrics"]
    assert new["pdf"] == ["skipped", "no PDFs on this scribe"]
    assert _ends(by["a song of the library with no length on its line"])["chords"] == ["done", "chords, then the lyrics"]
    none = _ends(by["no lyrics on any site"])
    assert none["vocals"] == ["skipped", f"not transcribed here: {transcript.PHONE}"]
    assert none["chords"] == ["done", "chords only, no lyrics"]
    assert _ends(by["an ignored song"])["song"][0] == "failed"
    assert _ends(by["a song with a human sheet"])["song"] == ["failed", "Calla Lake - River Road already has a sheet"]
    again = _ends(by["the same job again once it was done"])
    assert again["audio"] == ["done", "has this file's audio already"]
    assert again["chords"][1].startswith("up to date: ")
    assert _ends(by["the same job again after a keep cut off between its move and the song's row"])["audio"] == [
        "done", "kept as its audio: M4A, 3:33"]
    assert _ends(by["the models fail on the file (one they can't decode)"])["chords"][0] == "failed"
    assert _ends(by["the models' setup fails"])["chords"][0] == "failed"
    relaid = by["a sheet the phone made, chords only, its song's lyrics found since"]
    raw = json.loads(relaid["out"]["rows"]["versions"][0]["raw"])
    assert raw["made_by"] == PHONE_ID and raw["lyrics"] == "synced"
    new_store = by["a song new to the library"]["out"]["store"]
    assert [n for n, v in new_store.items() if v == "marker"] and not [n for n, v in new_store.items() if v == "record"]
