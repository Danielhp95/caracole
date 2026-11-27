"""``caracole lyrics --song X --record SITE:ID --progress`` for the phone: whole picks recorded, for :server's
``LyricsRunner`` (the chords-on-the-phone design's §8.5, the plan's E30) to agree with.

**Vectors** (``vectors/lookup/lyrics_pick.jsonl``), a header, then a record a line, each a scenario record
(helpers/scenario.py ``record_lookup``) of a world of test_conformance_lookup_scenarios.py's (``World``), whose song
was searched first (``caracole lyrics --as``, outside the record: its fixture holds the kept search, kv
``lyrics-search:<id>``, and its cache the search's answers), each with:

- ``fn``: ``caracole.lyrics_pick.pick_lyrics`` as ``caracole lyrics --record --progress`` runs it (``kw``: ``song``,
  ``record``, ``providers``);
- ``out.result``: ``{result, progress, python}``, the job's ends (``states``, ``details``), the song, the files
  readable, the stages as told in order, worded as the phone words them (test_conformance_lookup_scenarios.py
  ``in_phone_words``: the pdf ``get.NO_PDFS``, the pages ``get.LIBRARY_PAGE``), ``python`` Python's own ends of what was
  so rewritten;
- the requests (none for an LRCLIB record the search's cached answer holds; one for Megalobiz's ``/lrc/{id}`` or
  AZLyrics' page), the rows (the song's lyrics, ``phone_overrides``' ``[lyrics]`` record, a re-laid auto sheet's
  version and file), the kv and the library's files (the lyric files, the sheet).

The cases: LRCLIB's record from the search's cache over an auto sheet that keeps what was heard (re-laid, no model);
Megalobiz's record, one request, a song with no audio (no chords); AZLyrics' page; a record the search didn't list
(refused); Megalobiz cooling down (a wait, nothing kept).

Regenerate with ``CARACOLE_CORPUS=write nix develop -c pytest -q -n 0 tests/test_conformance_lyrics_pick.py``.
"""

from __future__ import annotations

import json
from contextlib import nullcontext
from datetime import timedelta
from pathlib import Path
from typing import Any
from unittest import mock

import pytest
from helpers.corpus import VECTORS, check, fixture_ref, jsonl
from helpers.scenario import record_lookup
from test_conformance_lookup_scenarios import NOW, STAMP, Heard, World, clock
from test_conformance_lyrics_search import NAME, POMME, POMME_PAGE, _cached, answered, lrc, mz, sites

MADE_BY = "tests/test_conformance_lyrics_pick.py"
VECTOR = VECTORS / "lookup" / "lyrics_pick.jsonl"
HTML = [["content-type", "text/html; charset=utf-8"]]
SEARCHED = NOW - timedelta(hours=1)
LENGTH = 200.0
CHORDS = [(0.0, 10.0, "Am"), (10.0, 20.0, "F"), (20.0, 30.0, "C"), (30.0, 40.0, "G")]
BEATS = [i * 0.5 for i in range(81)]
DOWNBEATS = [i * 2.0 for i in range(21)]
MEGALOBIZ_LRC = "https://api.megalobiz.com/api/public/v1/lrc/5001"
POMME_SONG = "https://www.azlyrics.com/lyrics/pomme/mononoke.html"


def _searched(w: World, display: str, typed: str, answers) -> dict[str, Any]:
    """``caracole lyrics --as`` of the song an hour before, outside any record: its kept search, and its answers as
    the HTTP cache keeps them, which the pick's record carries as its cache."""
    from caracole.commands import lyrics as cmd

    made = record_lookup(w.cfg, fn="search", call=lambda: _run_search(cmd, w, display, typed), answers=answers,
                         now=SEARCHED, settle=w.settled(SEARCHED))
    return _cached(made, SEARCHED.strftime("%Y-%m-%dT%H:%M:%SZ"))


def _run_search(cmd, w: World, display: str, typed: str) -> None:
    with mock.patch.object(cmd, "exclusive", lambda *a, **k: nullcontext()), mock.patch("typer.echo", lambda _: None):
        cmd._lyrics_as(w.cfg, display, typed)


def _heard_sheet(w: World, song_id: int) -> None:
    """An auto sheet made here, chords only, keeping what was heard, its song of no audio of its own."""
    from caracole.autochords import run
    from caracole.autochords.merge import ChordSegment
    from caracole.autochords.sheet import Heard as Hearing
    from caracole.autochords.sheet import make_sheet
    from caracole.songs import get_song

    with clock(STAMP):
        song = get_song(w.conn, song_id)
        heard = Hearing([ChordSegment(*c) for c in CHORDS], BEATS, DOWNBEATS, LENGTH)
        made = make_sheet(song, heard)
        with mock.patch.object(run, "write_info", lambda *a, **k: None):
            run._keep(w.conn, w.cfg, song, made.text, made.used, made.key, STAMP, heard=made.heard)
        w.conn.execute("UPDATE files SET created_at = ?", (STAMP,))
        w.conn.execute("UPDATE versions SET url = 'file://' WHERE provider = 'auto'")


def pick(w: World, case: str, display: str, record: str, answers, cache: dict[str, Any]) -> dict[str, Any]:
    """``caracole lyrics --song DISPLAY --record RECORD --progress`` at ``NOW``, recorded."""
    from caracole import lyrics_pick

    artist, _, title = display.partition(" - ")
    heard = Heard()

    def call() -> dict[str, Any]:
        with mock.patch("caracole.lyrics_pick.write_info", lambda *a, **k: None, create=True), \
                mock.patch("caracole.library.write_info", lambda *a, **k: None):
            result = lyrics_pick.pick_lyrics(w.cfg, lyrics_pick.PickRequest(artist, title, record=record), heard,
                                             now=NOW, clock=lambda: 0.0)
        return {"result": {"song_id": result.song_id, "display": result.display, "states": dict(result.states),
                           "details": dict(result.details), "files": dict(result.files),
                           "exit": 0 if result.ok else 1}, "progress": heard.events}

    made = record_lookup(w.cfg, fn="caracole.lyrics_pick.pick_lyrics", call=call, answers=answers, now=NOW, case=case,
                         kw={"song": display, "record": record, "providers": w.providers}, cache=cache,
                         settle=w.settled(NOW))
    assert "out" in made, made.get("raises")
    made["out"]["result"] = phone_words(made["out"]["result"])
    return made


def phone_words(said: dict[str, Any]) -> dict[str, Any]:
    """The job's ends and stages as the phone words them: the pdf of a caracole that makes none (get.NO_PDFS), the
    pages get.LIBRARY_PAGE; a stage that made nothing ("no sheet", "no new lyrics") the same on both. Python's own
    ends of what was so rewritten in ``python``."""
    from caracole import get

    def end(name: str, state: str, detail: str) -> tuple[str, str] | None:
        if name == "pdf" and state == "done" and detail in ("made", "up to date"):
            return "skipped", get.NO_PDFS
        if name == "pages" and state == "done":
            return "done", get.LIBRARY_PAGE
        return None

    result, progress = said["result"], said["progress"]
    python: dict[str, list[str]] = {}
    for name in list(result["details"]):
        e = end(name, result["states"][name], result["details"][name])
        if e is not None:
            python[name] = [result["states"][name], result["details"][name]]
            result["states"][name], result["details"][name] = e
    for event in progress:
        if event[0] == "stage" and event[2] != "running":
            e = end(event[1], event[2], event[3])
            if e is not None:
                event[2], event[3] = e
    return {**said, "python": python}


def megalobiz_record() -> dict[str, Any]:
    from helpers.megalobiz_site import record

    return answered(record(lrc_id=5001, title="Vikingos veganos", artist="Nick Cani", duration=201.5))


def records(tmp: Path) -> list[dict[str, Any]]:
    from caracole.health import record_block

    made: list[dict[str, Any]] = []
    listing = sites([lrc(77)], megalobiz=mz((5001, "Vikingos veganos", "Nick Cani", 201.5)))

    w = World(tmp, "lrclib")
    song_id = w.song("Nick Cani", "Vikingos veganos", duration_ms=200000, lyrics_status="missing")
    _heard_sheet(w, song_id)
    cache = _searched(w, NAME, NAME, listing)
    made.append(pick(w, "LRCLIB's record from the search's cache, over an auto sheet that keeps what was heard: no "
                        "request, the sheet laid out again over the words, no model", NAME, "lrclib:77", {}, cache))

    w = World(tmp, "megalobiz")
    w.song("Nick Cani", "Vikingos veganos", duration_ms=200000, lyrics_status="missing")
    cache = _searched(w, NAME, NAME, listing)
    made.append(pick(w, "Megalobiz's record, one request, a song of no audio: no chords", NAME, "megalobiz:5001",
                     {f"GET {MEGALOBIZ_LRC}": megalobiz_record()}, cache))

    w = World(tmp, "azlyrics")
    w.song("Pomme", "Mononoké", duration_ms=None, lyrics_status="missing")
    cache = _searched(w, "Pomme - Mononoké", "Pomme - Mononoke", sites(pages={POMME_PAGE: POMME}))
    made.append(pick(w, "AZLyrics' page, one request", "Pomme - Mononoké", "azlyrics:pomme/mononoke",
                     {f"GET {POMME_SONG}": {"status": 200, "headers": HTML,
                                            "body": fixture_ref("azlyrics/lyrics_mononoke.html")}}, cache))

    w = World(tmp, "unlisted")
    w.song("Nick Cani", "Vikingos veganos", duration_ms=200000, lyrics_status="missing")
    cache = _searched(w, NAME, NAME, listing)
    made.append(pick(w, "a record its last search didn't list: refused, nothing kept", NAME, "lrclib:99", {}, cache))

    w = World(tmp, "cooling")
    w.song("Nick Cani", "Vikingos veganos", duration_ms=200000, lyrics_status="missing")
    cache = _searched(w, NAME, NAME, listing)
    record_block(w.conn, "megalobiz", NOW - timedelta(minutes=10), "429 Too Many Requests")
    made.append(pick(w, "Megalobiz cooling down: a wait, nothing kept", NAME, "megalobiz:5001", {}, cache))
    return made


@pytest.fixture(scope="module")
def made(tmp_path_factory) -> list[dict[str, Any]]:
    return records(tmp_path_factory.mktemp("lyrics-pick"))


def test_the_vector_is_what_caracole_lyrics_record_does(made):
    check(VECTOR, jsonl(made, corpus="lookup", made_by=MADE_BY))


def test_the_vector_is_the_same_on_another_run(made, tmp_path):
    assert jsonl(records(tmp_path), corpus="lookup", made_by=MADE_BY) == jsonl(made, corpus="lookup",
                                                                               made_by=MADE_BY)


def _ends(record: dict[str, Any]) -> dict[str, list[str]]:
    r = record["out"]["result"]["result"]
    return {k: [r["states"][k], r["details"][k]] for k in r["states"]}


def test_the_cases_come_to_what_they_say(made):
    by = {r["case"].split(":")[0]: r for r in made}
    lrclib = by["LRCLIB's record from the search's cache, over an auto sheet that keeps what was heard"]
    assert lrclib["out"]["requests"] == []
    assert _ends(lrclib)["lyrics"][0] == "done" and _ends(lrclib)["chords"] == ["done", "chords over the lyrics"]
    raw = json.loads(next(v for v in lrclib["out"]["rows"]["versions"] if v["provider"] == "auto")["raw"])
    assert raw["lyrics"] == "synced" and raw["heard"]
    mega = by["Megalobiz's record, one request, a song of no audio"]
    assert len(mega["out"]["requests"]) == 1
    assert _ends(mega)["chords"] == ["skipped", "no audio to make an auto sheet from"]
    assert len(by["AZLyrics' page, one request"]["out"]["requests"]) == 1
    assert _ends(by["a record its last search didn't list"])["song"][0] == "failed"
    assert _ends(by["Megalobiz cooling down"])["lyrics"][0] == "skipped"
