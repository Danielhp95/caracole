"""A song's lyrics looked up under a name typed, for the phone's routes (the chords-on-the-phone plan's E31,
server/routes/LyricsRoutes.kt): web/lyrics_routes.py's ``POST /lyrics/search``, ``GET /api/lyrics/search``,
``POST /lyrics/pick`` and ``POST /lyrics/clear``, as caracole serve answers them.

**vectors/web/lyrics_routes.jsonl**, after its header:

- ``{"fn": "fixture", "scene", "records"}``: a scene, a library in a fresh database dumped whole with its library
  folder's files (``helpers.corpus.dump_fixture``; overrides.toml as the phone's ``phone_overrides`` rows), which the
  replay loads; every record after it names the scene it asks over. ``kept``: Nick Cani - Vikingos veganos (Video
  Oficial), missing, searched an hour before (its kept search: four rows, LRCLIB's best); Pomme - Mononoké, found,
  searched nine days before (past its week); Calla Lake - River Road, pending under a ``[lyrics]`` name and a record of
  no lyrics yet; an ignored song. ``off``: the same, Megalobiz turned off (kv ``phone:settings``, the computer's
  ``enabled = false``).
- ``{"fn": "GET /api/lyrics/search", "scene", "case", "query", "out": {"status", "body"} | refusal}``: the answer at
  ``NOW`` (``api_search``).
- ``{"fn": "POST /lyrics/search" | "POST /lyrics/pick" | "POST /lyrics/clear", "scene", "case", "form", "out"}``: the form posted to a fresh
  queue that runs nothing, at ``NOW`` (``search``, its script's: JSON; ``pick``): ``{"status", "body"?, "location"?,
  "job": {title, key, steps, display, stages}}``, or a refusal ``{"status", "title", "message"}``; a record's
  ``queued`` the jobs queued before it in the same queue (a search or a pick on its way).

Regenerate with ``CARACOLE_CORPUS=write nix develop -c pytest -q -n 0 tests/test_conformance_lyrics_routes.py``.
"""

from __future__ import annotations

import json
from contextlib import nullcontext
from datetime import timedelta
from pathlib import Path
from typing import Any
from unittest import mock

import pytest
from helpers.corpus import VECTORS, check, dump_fixture, jsonl
from helpers.scenario import record_lookup
from test_conformance_lookup_scenarios import NOW, World
from test_conformance_lyrics_search import NAME, POMME, POMME_PAGE, SONG, lrc, mz, sites

MADE_BY = "tests/test_conformance_lyrics_routes.py"
VECTOR = VECTORS / "web" / "lyrics_routes.jsonl"
CSRF = "tok"
ADDED = "2026-10-01T00:00:00Z"
DISPLAY = f"{SONG[0]} - {SONG[1]}"


def _search_at(w: World, display: str, typed: str, at, answers) -> None:
    from caracole.commands import lyrics as cmd

    def call() -> None:
        with mock.patch.object(cmd, "exclusive", lambda *a, **k: nullcontext()), mock.patch("typer.echo",
                                                                                              lambda _: None):
            cmd._lyrics_as(w.cfg, display, typed)

    record_lookup(w.cfg, fn="search", call=call, answers=answers, now=at, settle=w.settled(at))


def scene(tmp: Path, name: str, *, megalobiz_off: bool = False) -> World:
    from caracole import db
    from caracole.overrides import add_ignore, set_lyrics_name, set_lyrics_record

    w = World(tmp, name)
    w.song(*SONG, duration_ms=200000, lyrics_status="missing")
    w.song("Pomme", "Mononoké", duration_ms=None, lyrics_status="found")
    w.song("Calla Lake", "River Road", duration_ms=213000, lyrics_status="pending")
    w.song("Nobody", "Nothing", duration_ms=None)
    w.song("Harbour Lights", "Paper Boats", duration_ms=None, lyrics_status="missing")
    listing = sites([lrc(77), lrc(78, artist="Somebody Else")],
                    megalobiz=mz((5001, "Vikingos veganos", "Nick Cani", 201.5), (5002, "Otra cosa", "Nadie", None)))
    _search_at(w, DISPLAY, NAME, NOW - timedelta(hours=1), listing)
    _search_at(w, "Pomme - Mononoké", "Pomme - Mononoke", NOW - timedelta(days=9), sites(pages={POMME_PAGE: POMME}))
    w.overrides(lambda path: (set_lyrics_name(path, "Calla Lake - River Road", "Calla Lake - River Road Live"),
                              set_lyrics_record(path, "Calla Lake - River Road", "lrclib:9"),
                              add_ignore(path, "Nobody - Nothing"),
                              set_lyrics_record(path, "Harbour Lights - Paper Boats", "megalobiz:42")))
    w.conn.execute("UPDATE songs SET lyrics_status = 'pending', lyrics_at = NULL WHERE title = 'River Road'")
    if megalobiz_off:  # turned off after the search: the phone's settings as a sync brings them
        import dataclasses

        from caracole.politeness import settings_document

        providers = {**w.cfg.providers, "megalobiz": dataclasses.replace(w.cfg.provider("megalobiz"), enabled=False)}
        w.cfg = dataclasses.replace(w.cfg, providers=providers)
        db.kv_set_json(w.conn, "phone:settings", settings_document(w.cfg))
    w.conn.execute("UPDATE songs SET created_at = ?, updated_at = ?", (ADDED, ADDED))
    return w


def fixture(w: World, name: str) -> dict[str, Any]:
    records = [r for r in dump_fixture(w.conn, w.cfg.library_dir) if r.get("file") != "overrides.toml"
               and not (r.get("kv") or "").startswith(("wanted:first_seen:",))]
    return {"fn": "fixture", "scene": name, "records": records}


def app(w: World):
    from caracole.web.app import WebApp
    from caracole.web.jobs import JobQueue

    def runner(args, emit):  # nothing runs: the queue is never started
        raise AssertionError(f"a route ran {args}")

    return WebApp(w.cfg, JobQueue(runner, limit=20), allowed=frozenset({"localhost"}), csrf=CSRF,
                  searches_lacuerda=False, searches_youtube=False)


def _refusal(e) -> dict[str, Any]:
    return {"status": e.status, "title": e.title, "message": str(e)}


def song_id(w: World, title: str) -> int:
    return w.conn.execute("SELECT id FROM songs WHERE title = ?", (title,)).fetchone()[0]


def key_of(w: World, title: str) -> str:
    return w.conn.execute("SELECT key FROM songs WHERE title = ?", (title,)).fetchone()[0]


def asked(w: World, name: str, case: str, query: dict[str, str]) -> dict[str, Any]:
    from caracole.web.lyrics_routes import api_search
    from caracole.web.pages import Refused

    try:
        response = api_search(app(w), {k: [v] for k, v in query.items()}, now=NOW)
        body = json.loads(response.body)
        out: dict[str, Any] = {"status": response.status, "body": body, "order": order(body)}
    except Refused as e:
        out = _refusal(e)
    return {"fn": "GET /api/lyrics/search", "scene": name, "case": case, "query": query, "out": out}


def order(value: Any) -> Any:
    """The members' order of a JSON value (the vector is written with its keys sorted): an object's ``[[key, order of
    its value], …]``, a list's each element's, anything else null."""
    if isinstance(value, dict):
        return [[k, order(v)] for k, v in value.items()]
    if isinstance(value, list):
        return [order(v) for v in value]
    return None


def _job(job) -> dict[str, Any]:
    return {"title": job.title, "key": job.song_key, "steps": [[s.label, list(s.args)] for s in job.steps],
            "display": job.display, "stages": [[s.name, s.label] for s in job.stages]}


def posted(w: World, name: str, case: str, path: str, form: dict[str, str],
           before: list[dict[str, str]] = (), *, json_asked: bool = True,
           raw_before: list[str] = ()) -> dict[str, Any]:
    from caracole.web import lyrics_routes
    from caracole.web.pages import Refused

    a = app(w)
    queued = []
    record: dict[str, Any] = {"fn": f"POST {path}", "scene": name, "case": case, "form": form}
    if not json_asked:
        record["json"] = False
    from caracole.web.jobs import LYRICS_SEARCH, lyrics_search_steps

    for typed in raw_before:  # a search queued under a name read as none now (an older caracole's, by hand)
        nick = w.conn.execute("SELECT key, artist, title FROM songs WHERE title LIKE 'Vikingos%'").fetchone()
        a.submit("Lyrics", LYRICS_SEARCH + nick[0], lyrics_search_steps(f"{nick[1]} - {nick[2]}", typed),
                 display=f"{nick[1]} - {nick[2]}")
    if raw_before:
        record["raw_queued"] = list(raw_before)
    for earlier in before:  # a search or a pick on its way, in the same queue
        (lyrics_routes.search(a, {"csrf": CSRF, **earlier}, json=True) if path == "/lyrics/search"
         else lyrics_routes.pick(a, {"csrf": CSRF, **earlier}, now=NOW))
        queued.append(earlier)
    if queued:
        record["queued"] = queued
    try:
        if path == "/lyrics/search":
            response = lyrics_routes.search(a, {"csrf": CSRF, **form}, json=json_asked)
        elif path == "/lyrics/clear":
            response = lyrics_routes.clear(a, {"csrf": CSRF, **form})
        else:
            response = lyrics_routes.pick(a, {"csrf": CSRF, **form}, now=NOW)
    except Refused as e:
        record["out"] = _refusal(e)
        return record
    jobs = a.queue.snapshot()
    out: dict[str, Any] = {"status": response.status}
    if response.body and response.status == 202:
        out["body"] = json.loads(response.body)
        out["order"] = order(out["body"])
    if response.data is not None:  # the page's script's answer of a job queued in place: its view
        out["data"] = response.data
    location = next((v for k, v in response.headers if k.lower() == "location"), None)
    if location:
        out["location"] = location
    out["job"] = _job(jobs[-1] if len(jobs) > len(queued) else jobs[0])
    out["jobs"] = len(jobs)
    record["out"] = out
    return record


def records(tmp: Path) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    w = scene(tmp, "kept")
    nick, pomme, calla, nobody = (song_id(w, t) for t in ("Vikingos veganos (Video Oficial)", "Mononoké", "River Road",
                                                           "Nothing"))
    nick_key = key_of(w, "Vikingos veganos (Video Oficial)")
    out.append(fixture(w, "kept"))
    out.append(asked(w, "kept", "a search kept within its week: its rows, words and last line",
                     {"song": str(nick), "identity": nick_key}))
    out.append(asked(w, "kept", "a search past its week: the name and the day alone",
                     {"song": str(pomme)}))
    out.append(asked(w, "kept", "asked again under its name, its record of no lyrics yet",
                     {"song": str(calla)}))
    out.append(asked(w, "kept", "no search kept", {"song": str(nobody)}))
    out.append(asked(w, "kept", "a record picked that gave no lyrics: picked_why",
                     {"song": str(song_id(w, "Paper Boats"))}))
    out.append(asked(w, "kept", "with its card, as the page draws it now", {"song": str(nick), "card": "1"}))
    out.append(asked(w, "kept", "another song's identity", {"song": str(nick), "identity": "x/y"}))
    out.append(asked(w, "kept", "no such song", {"song": "999"}))
    out.append(asked(w, "kept", "no song named", {"song": "x"}))
    names = {"song": str(nick), "identity": nick_key}
    out.append(posted(w, "kept", "a name typed: the search queued, the name the command reads",
                      "/lyrics/search", {**names, "artist": "Nick Cani", "title": "Vikingos veganos (Video Oficial)"}))
    out.append(posted(w, "kept", "another name while one is on its way: that one, said", "/lyrics/search",
                      {**names, "artist": "Nick Cani", "title": "Vikingos"},
                      before=[{**names, "artist": "Nick Cani", "title": "Vikingos veganos"}]))
    out.append(posted(w, "kept", "no title", "/lyrics/search", {**names, "artist": "Nick Cani", "title": ""}))
    out.append(posted(w, "kept", "an artist holding a dash", "/lyrics/search",
                      {**names, "artist": "Nick - Cani", "title": "Vikingos"}))
    out.append(posted(w, "kept", "an ignored song", "/lyrics/search",
                      {"song": str(nobody), "artist": "A", "title": "B"}))
    out.append(posted(w, "kept", "a row of the kept search picked", "/lyrics/pick", {**names, "record": "lrclib:77"}))
    out.append(posted(w, "kept", "the same record again while its pick is on its way: that pick", "/lyrics/pick",
                      {**names, "record": "lrclib:77"}, before=[{**names, "record": "lrclib:77"}]))
    out.append(posted(w, "kept", "another record while a pick is on its way: refused", "/lyrics/pick",
                      {**names, "record": "megalobiz:5001"}, before=[{**names, "record": "lrclib:77"}]))
    out.append(posted(w, "kept", "a record the search didn't list", "/lyrics/pick", {**names, "record": "lrclib:1"}))
    out.append(posted(w, "kept", "the record picked taken back", "/lyrics/clear",
                      {"song": str(calla), "identity": key_of(w, "River Road")}))
    out.append(posted(w, "kept", "a song with no record picked: nothing to clear", "/lyrics/clear",
                      {"song": str(nick)}))
    out.append(posted(w, "kept", "a name typed from a form: to its request's line", "/lyrics/search",
                      {**names, "artist": "Nick Cani", "title": "Vikingos veganos"}, json_asked=False))
    out.append(posted(w, "kept", "a search under a name of no song: 404", "/lyrics/search",
                      {"song": "999", "artist": "A", "title": "B"}))
    out.append(posted(w, "kept", "a search on its way under a name read as none now: said, its as null",
                      "/lyrics/search", {**names, "artist": "Nick Cani", "title": "Vikingos"}, raw_before=["Nope"]))
    out.append(posted(w, "kept", "a pick of an ignored song", "/lyrics/pick", {"song": str(nobody), "record": "lrclib:77"}))
    out.append(posted(w, "kept", "a clear of an ignored song", "/lyrics/clear", {"song": str(nobody)}))
    out.append(posted(w, "kept", "a search past its week", "/lyrics/pick",
                      {"song": str(pomme), "record": "azlyrics:pomme/mononoke"}))
    w.conn.close()

    w = scene(tmp, "off", megalobiz_off=True)
    out.append(fixture(w, "off"))
    out.append(posted(w, "off", "a record of a site turned off", "/lyrics/pick",
                      {"song": str(song_id(w, "Vikingos veganos (Video Oficial)")), "record": "megalobiz:5001"}))
    w.conn.close()
    return out


@pytest.fixture(scope="module")
def made(tmp_path_factory) -> list[dict[str, Any]]:
    return records(tmp_path_factory.mktemp("lyrics-routes"))


def test_lyrics_routes_jsonl(made):
    check(VECTOR, jsonl(made, corpus="web/lyrics_routes", made_by=MADE_BY))


def test_the_vector_is_the_same_on_another_run(made, tmp_path):
    assert jsonl(records(tmp_path), corpus="web/lyrics_routes", made_by=MADE_BY) == jsonl(
        made, corpus="web/lyrics_routes", made_by=MADE_BY)


def test_the_routes_answer_each_case(made):
    by = {r["case"]: r for r in made if "case" in r}
    kept = by["a search kept within its week: its rows, words and last line"]["out"]["body"]["search"]
    assert kept["pickable"] and kept["rows"][0]["record"] == "lrclib:77" and kept["line"].startswith("Searched: ")
    assert by["a search past its week: the name and the day alone"]["out"]["body"]["search"]["rows"] == []
    assert by["asked again under its name, its record of no lyrics yet"]["out"]["body"]["picked"] == "lrclib:9"
    assert by["another song's identity"]["out"]["status"] == 409
    assert by["a name typed: the search queued, the name the command reads"]["out"]["body"]["as"] == {
        "artist": "Nick Cani", "title": "Vikingos veganos"}
    assert "said" in by["another name while one is on its way: that one, said"]["out"]["body"]
    assert by["another record while a pick is on its way: refused"]["out"]["status"] == 409
    assert by["a record of a site turned off"]["out"]["status"] == 409
    assert by["a row of the kept search picked"]["out"]["job"]["steps"][0][1][-1] == "--progress"
