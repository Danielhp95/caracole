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
from helpers.scenario import LEAVES_OUT, record_lookup
from test_conformance_lookup_scenarios import NOW, STAMP, Heard, World, clock
from test_conformance_lyrics_search import NAME, POMME, POMME_PAGE, SONG, _cached, answered, lrc, mz, sites

MADE_BY = "tests/test_conformance_lyrics_pick.py"
# What the phone never writes, beside LEAVES_OUT's: the to-do page's record of an auto-chords pass.
LEAVES = {"kv": [*LEAVES_OUT["kv"], "autochords:status"], "files": LEAVES_OUT["files"]}
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


def pick(w: World, case: str, display: str, record: str | None, answers, cache: dict[str, Any], *,
         row: int | None = None, models: bool = False) -> dict[str, Any]:
    """``caracole lyrics --song DISPLAY --record RECORD --progress`` at ``NOW``, recorded."""
    from caracole import lyrics_pick

    artist, _, title = display.partition(" - ")
    heard = Heard()

    def call() -> dict[str, Any]:
        from contextlib import ExitStack

        with ExitStack() as stack:
            stack.enter_context(mock.patch("caracole.lyrics_pick.write_info", lambda *a, **k: None, create=True))
            stack.enter_context(mock.patch("caracole.library.write_info", lambda *a, **k: None))
            if models:  # auto-chords here, its models never to run (a sheet up to date asks none)
                stack.enter_context(mock.patch("caracole.youtube_fetch.autochords_problem", lambda cfg: None))
            result = lyrics_pick.pick_lyrics(w.cfg, lyrics_pick.PickRequest(artist, title, pick=row, record=record),
                                             heard, now=NOW, clock=lambda: 0.0, recognizer=NoModel(),
                                             beats_fn=NoModel())
        return {"result": {"song_id": result.song_id, "display": result.display, "states": dict(result.states),
                           "details": dict(result.details), "files": dict(result.files),
                           "exit": 0 if result.ok else 1}, "progress": heard.events}

    made = record_lookup(w.cfg, fn="caracole.lyrics_pick.pick_lyrics", call=call, answers=answers, now=NOW, case=case,
                         kw={"song": display, "record": record, "pick": row, "models": models,
                             "providers": w.providers}, cache=cache, leaves_out=LEAVES,
                         settle=w.settled(NOW))
    assert "out" in made, made.get("raises")
    made["out"]["result"] = phone_words(made["out"]["result"])
    return made


def phone_words(said: dict[str, Any]) -> dict[str, Any]:
    """The job's ends and stages as the phone words them: the pdf of a caracole that makes none (get.NO_PDFS), the
    pages get.LIBRARY_PAGE; a stage that made nothing ("no sheet", "no new lyrics") the same on both. Python's own
    ends of what was so rewritten in ``python``."""
    from caracole import get

    from caracole.lyrics_pick import PHONE_NOT_HERE
    from test_conformance_library_page import AUDIO_PROBLEM

    def end(name: str, state: str, detail: str) -> tuple[str, str] | None:
        if name == "chords" and state == "skipped" and detail.startswith("auto-chords isn't here ("):
            return "skipped", PHONE_NOT_HERE.format(problem=AUDIO_PROBLEM)  # a phone with no chords (the replay's)
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


class NoModel:
    """auto-chords' models where none may run: a sheet up to date, or laid out again, asks none."""

    name = "no model"

    def recognize(self, path):
        raise AssertionError(f"a model ran on {path}")

    def __call__(self, path):
        raise AssertionError(f"a model ran on {path}")


AUDIO = "tests/fixtures/audio/tone.m4a"  # the song's own audio, relative to the repository's root (the replay's too)


def own_audio(w: World, song_id: int) -> None:
    """The song's audio its own file, its auto sheet (when it has one) made of it."""
    w.conn.execute("UPDATE songs SET audio_path = ?, audio_mtime = 1.0, autochords_mtime = "
                   "CASE WHEN EXISTS (SELECT 1 FROM files WHERE song_id = songs.id) THEN 1.0 END WHERE id = ?",
                   (AUDIO, song_id))


def site_sheet(w: World, song_id: int) -> None:
    """A sheet of Ultimate Guitar's, kept as the fetch keeps one."""
    from caracole.library import keep_file
    from caracole.songs import get_song
    from caracole.versions import upsert_version

    with clock(STAMP):
        song = get_song(w.conn, song_id)
        version = upsert_version(w.conn, provider="ug", tab_id="101", song_id=song_id, slot="sheet", kind="chords",
                                 rating=4.8, votes=120, version=1, label=None,
                                 url="https://tabs.ultimate-guitar.com/tab/101", raw={}, now=STAMP)
        keep_file(w.conn, w.cfg.library_dir, song=song, version_id=version, name="sheet.txt",
                  data=b"[ch]Am[/ch] walking\n", rank=1)
        w.conn.execute("UPDATE files SET created_at = ?", (STAMP,))


def clear(w: World, case: str, display: str) -> dict[str, Any]:
    """``caracole lyrics --song DISPLAY --clear`` at ``NOW`` (commands/lyrics.py ``_lyrics_clear``), recorded:
    ``out.result`` ``{"lines", "exit", "error"}``, its line, its exit status and its error's words (``fail``'s)."""
    import typer

    from caracole.commands import _common
    from caracole.commands import lyrics as cmd

    def call() -> dict[str, Any]:
        lines: list[str] = []
        errors: list[str] = []
        code = 0
        with mock.patch.object(cmd, "exclusive", lambda *a, **k: nullcontext()), \
                mock.patch("typer.echo", lines.append), \
                mock.patch.object(_common.logs, "say", lambda level, message: errors.append(message)), \
                mock.patch("caracole.library.write_info", lambda *a, **k: None):
            try:
                cmd._lyrics_clear(w.cfg, display)
            except typer.Exit as e:
                code = e.exit_code
        return {"result": {"lines": lines, "exit": code, "error": errors[-1] if errors else None}, "progress": []}

    return record_lookup(w.cfg, fn="caracole.commands.lyrics._lyrics_clear", call=call, answers={}, now=NOW, case=case,
                         kw={"song": display}, leaves_out=LEAVES, settle=w.settled(NOW))


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

    lrc_url = "https://api.megalobiz.com/api/public/v1/lrc/5001"
    for case, answer in (("Megalobiz blocks the pick: a wait, nothing kept", {"status": 429, "headers": HTML,
                                                                              "body": "{}"}),
                         ("Megalobiz fails at the pick: its stage failed, the job ends 0",
                          {"status": 502, "headers": HTML, "body": "Bad Gateway"}),
                         ("Megalobiz's record gone: no lyrics now, nothing kept",
                          {"status": 404, "headers": HTML, "body": '{"error": "not found"}'})):
        w = World(tmp, case.split(":")[0].replace(" ", "-").replace("'", ""))
        w.song("Nick Cani", "Vikingos veganos", duration_ms=200000, lyrics_status="missing")
        cache = _searched(w, NAME, NAME, listing)
        made.append(pick(w, case, NAME, "megalobiz:5001", {f"GET {lrc_url}": answer}, cache))

    w = World(tmp, "row")
    w.song("Nick Cani", "Vikingos veganos", duration_ms=200000, lyrics_status="missing")
    cache = _searched(w, NAME, NAME, listing)
    made.append(pick(w, "--pick 2: the search's second row", NAME, None, {f"GET {lrc_url}": megalobiz_record()}, cache,
                     row=2))

    w = World(tmp, "not-here")
    song_id = w.song("Nick Cani", "Vikingos veganos", duration_ms=200000, lyrics_status="missing")
    own_audio(w, song_id)
    cache = _searched(w, NAME, NAME, listing)
    made.append(pick(w, "a song of its own audio and no sheet, auto-chords not here: the chords skipped", NAME,
                     "lrclib:77", {}, cache))

    w = World(tmp, "up-to-date")
    song_id = w.song("Nick Cani", "Vikingos veganos", duration_ms=200000, lyrics_status="missing")
    cache = _searched(w, NAME, NAME, listing)
    first = pick(w, "", NAME, "lrclib:77", {}, cache)  # the sheet laid out over them once
    own_audio(w, song_id)
    _heard_sheet(w, song_id)
    w.conn.execute("UPDATE songs SET autochords_mtime = 1.0 WHERE id = ?", (song_id,))
    assert first
    made.append(pick(w, "the same record again, its sheet of its own audio up to date: no model", NAME, "lrclib:77", {},
                     cache, models=True))

    w = World(tmp, "elsewhere")
    song_id = w.song("Nick Cani", "Vikingos veganos", duration_ms=200000, lyrics_status="missing")
    cache = _searched(w, NAME, NAME, listing)
    pick(w, "", NAME, "lrclib:77", {}, cache)
    _heard_sheet(w, song_id)
    raw = json.loads(w.conn.execute("SELECT raw FROM versions WHERE provider = 'auto'").fetchone()[0])
    w.conn.execute("UPDATE versions SET raw = ? WHERE provider = 'auto'",
                   (json.dumps({**raw, "made_by": "another-caracole"}, ensure_ascii=False),))
    made.append(pick(w, "the same record again over a sheet another caracole made: its words re-lay it, no model", NAME,
                     "lrclib:77", {}, cache))

    w = World(tmp, "site-sheet")
    song_id = w.song("Nick Cani", "Vikingos veganos", duration_ms=200000, lyrics_status="missing")
    site_sheet(w, song_id)
    cache = _searched(w, NAME, NAME, listing)
    made.append(pick(w, "a pick over a site's sheet: no auto sheet to make", NAME, "lrclib:77", {}, cache))

    # --clear
    from caracole.overrides import set_lyrics_record

    video = f"{SONG[0]} - {SONG[1]}"
    w = World(tmp, "clear-lrclib")
    w.song(*SONG, duration_ms=200000, lyrics_status="missing")
    cache = _searched(w, video, NAME, listing)
    pick(w, "", video, "lrclib:77", {}, cache)
    made.append(clear(w, "--clear of LRCLIB's record that gave the lyrics: they go, its as kept and said", video))

    w = World(tmp, "clear-megalobiz")
    song_id = w.song("Nick Cani", "Vikingos veganos", duration_ms=200000, lyrics_status="missing")
    cache = _searched(w, NAME, NAME, listing)
    _heard_sheet(w, song_id)
    raw = json.loads(w.conn.execute("SELECT raw FROM versions WHERE provider = 'auto'").fetchone()[0])
    w.conn.execute("UPDATE versions SET raw = ? WHERE provider = 'auto'",
                   (json.dumps({k: v for k, v in raw.items() if k != "heard"}, ensure_ascii=False),))
    pick(w, "", NAME, "megalobiz:5001", {f"GET {lrc_url}": megalobiz_record()}, cache)
    w.conn.execute("UPDATE songs SET autochords_mtime = 1.0, audio_mtime = 1.0 WHERE id = ?", (song_id,))
    made.append(clear(w, "--clear of Megalobiz's record that gave the lyrics over a sheet of no heard: made due", NAME))

    w = World(tmp, "clear-azlyrics")
    w.song("Pomme", "Mononoké", duration_ms=None, lyrics_status="missing")
    cache = _searched(w, "Pomme - Mononoké", "Pomme - Mononoke", sites(pages={POMME_PAGE: POMME}))
    pick(w, "", "Pomme - Mononoké", "azlyrics:pomme/mononoke",
         {f"GET {POMME_SONG}": {"status": 200, "headers": HTML, "body": fixture_ref("azlyrics/lyrics_mononoke.html")}},
         cache)
    made.append(clear(w, "--clear of AZLyrics' page that gave the lyrics", "Pomme - Mononoké"))

    w = World(tmp, "clear-elsewhere")
    w.song("Nick Cani", "Vikingos veganos", duration_ms=200000, lyrics_status="missing")
    cache = _searched(w, NAME, NAME, listing)
    pick(w, "", NAME, "megalobiz:5001", {f"GET {lrc_url}": megalobiz_record()}, cache)
    w.overrides(lambda path: set_lyrics_record(path, NAME, "lrclib:77"))
    made.append(clear(w, "--clear of a record whose lyrics came from elsewhere: they stay", NAME))

    w = World(tmp, "clear-none")
    w.song("Nick Cani", "Vikingos veganos", duration_ms=200000, lyrics_status="missing")
    made.append(clear(w, "--clear of a song with no record picked: exit 1", NAME))

    w = World(tmp, "clear-stuck")
    w.song("Nick Cani", "Vikingos veganos", duration_ms=200000, lyrics_status="missing")
    cache = _searched(w, NAME, NAME, listing)
    pick(w, "", NAME, "lrclib:77", {}, cache)
    folder = w.cfg.library_dir / "Nick Cani" / "Vikingos veganos"
    (folder / "lyrics.lrc").unlink()
    (folder / "lyrics.lrc").mkdir()
    (folder / "lyrics.lrc" / "x").write_text("x", encoding="utf-8")
    made.append(clear(w, "--clear with a lyric file that can't be removed: said, the clear standing", NAME))
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
