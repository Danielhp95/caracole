"""The Songbooks tab's forms on the phone: what android/server's ``SongbookRoutes`` (lane songbook-routes) answers,
written for its replay (``SongbookRoutesReplay``) to agree with: each ``POST /songbook/*`` form queued as its
``caracole songbook`` command (web/songbooks.py, web/songbook_routes.py), or refused in caracole serve's words.

**The library** (``build_library``): songs of the cases' own (one with a sheet caracole rendered, its .cho and kv
``render:files:<id>`` as render.py records them; others with none, one ignored by overrides.toml and one by its status,
one matched to an Ultimate Guitar song, one of an artist whose name holds " - ", a Chinese one), overrides.toml as the
phone holds it (``phone_overrides``, ``test_conformance_overrides.rows_of``), and its songbooks both in songbooks.toml
and in ``phone_songbooks``, as the phone keeps them (each ``peer_sync.songbook_value``'s songs in canonical JSON). Its
stamps are fixed, so the fixture is the same on every run. Dumped whole into the vector's first record
(``helpers.corpus.dump_fixture``, the library folder's sheet files with it), which the replay loads into a fresh
database and library folder.

**vectors/songbook/routes.jsonl**: a header, then:

- ``{"fn": "fixture", "records": [...]}``: the library, as above;
- a record a scenario, ``{"fn": "songbook_routes", "case", "limit", "asked": [{"path", "form": [[name, value], ...]},
  ...], "out": [...], "queue": [...]}``: each form posted in turn to caracole serve's route (``songbook_routes.change``
  for make, add, move, remove, set, rename and delete; ``get_missing`` for ``/songbook/get``; ``add_song`` for
  ``/songbook/add-song``), over one queue of ``limit`` jobs that runs nothing, the library as the fixture holds it.
  ``out``, one answer a form: a refusal, ``{status, title, message, wanted}``, or what was queued, ``{status,
  location, job, jobs, left, wanted}``: the answer's status and ``Location`` (the songbook job's line in the Requests
  tab), the id of the songbook's job, the ids of the lookups it queued first (Get the missing songs' and Add a song's
  ``jobs``, in order) and how many songs wait for another tap (Get the missing songs' ``left``, else null), and
  ``views``, the songbook job's view and its lookups', as the answer gives them to the page's script (``job``, then
  ``jobs``: jobs_routes.view, the queue never started, so each waits).
  ``wanted``: the form named a song new to the library, so caracole serve wrote wanted.txt
  (``library_routes.wanted_line``), which its lookup's ``note`` and a full queue's refusal tell of; the phone writes no
  wanted.txt (its lookup's ``caracole get`` adds the song), so its note says nothing then, and its queue-full words
  are its own ("nothing was added"). ``queue``: every job the queue holds once the forms are posted, by id, ``{id,
  title, key, steps: [[label, [args]]], fetching, note, display, together}``, ``wanted`` on a lookup of a song new to
  the library.

**vectors/songbook/routes_runner.jsonl**: what each ``caracole songbook`` command those forms queue says and does
(commands/songbook.py through typer's CliRunner, its command line as SongbookRoutes queues it), for the phone's
``SongbookRunner`` to say and do the same, over test_conformance_songbook_tab.py's library
(``songbook/fixtures/entries-library.jsonl``: sheets in keys major and minor, with a capo, in Chinese, with no key,
songs with none, songbooks with settings of every kind) and its overrides (``overrides_json``), with
``songbook.render_songbooks`` making nothing and the library pages written by none (``write_pages``): the files the
fixture holds are what the command says it wrote. A header, then:

- ``{"fn": "overrides", "out": ...}``: the overrides every command reads, as entries.jsonl's first record writes them;
- a record a case, ``{"fn": "songbook_runner", "case", "commands": [{"args", "lines", "code"}, ...], "songbooks"}``:
  its commands run in turn over the fixture's songbooks.toml as it is, ``args`` each command line after
  ``caracole``, ``lines`` what it wrote (stdout and stderr as they came, its ``error:`` line and the lines after it of
  a message of several; the library folder's path written ``{library}``), ``code`` its exit code; ``songbooks`` every
  songbook once the last is over, ``peer_sync.songbook_value``'s. typer's own usage errors (a missing argument, an
  option that isn't one, a value out of range) are not held: typer draws them in a box the phone words its own way.

Regenerate with ``CARACOLE_CORPUS=write nix develop -c pytest -q -n 0 tests/test_conformance_songbook_routes.py``.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator
from contextlib import closing, contextmanager
from pathlib import Path
from typing import Any

import pytest
from helpers.corpus import VECTORS, check, dump_fixture, jsonl

from caracole import db
from caracole.web.pages import Refused

MADE_BY = "tests/test_conformance_songbook_routes.py"
ROUTES = VECTORS / "songbook" / "routes.jsonl"
RUNNER = VECTORS / "songbook" / "routes_runner.jsonl"
STAMP = "2026-11-03T10:00:00Z"
SLUGGED = "https://tabs.ultimate-guitar.com/tab/{}-chords-{}"

# --- the library ---------------------------------------------------------------------------------------------------

SONGS = (
    ("Soda Stereo", "De Música Ligera"),  # its sheet rendered: nothing to get
    ("Oasis", "Wonderwall"),
    ("Muse", "Hysteria"),
    ("Radiohead", "Creep"),  # ignored by overrides.toml
    ("Blur", "Song 2"),  # ignored by its status
    ("Eagles", "Hotel California"),
    ("Earth - Wind - Fire", "September"),
    ("宋冬野", "斑马，斑马"),
    ("Radiohead UK", "Paranoid Android"),  # matched to Ultimate Guitar's radiohead-uk/paranoid-android
)

OVERRIDES = """\
[ignore]
songs = ["Radiohead - Creep"]
"""

# The songbooks, in order: each song "Artist - Title", or (that, its setting's parts)
SONGBOOKS: tuple[tuple[str, tuple[Any, ...]], ...] = (
    ("Campfire", ("Soda Stereo - De Música Ligera", "oasis - WONDERWALL", "Muse - Hysteria", "Nobody - Nothing",
                  "Radiohead - Creep", "Blur - Song 2", ("Eagles - Hotel California", {"key": "D", "capo": 2}))),
    ("Road trip #1", ("Earth - Wind - Fire - September", ("宋冬野 - 斑馬，斑馬", {"instrument": "ukulele"}))),
    ("All-sheets", ("Soda Stereo - De Música Ligera", "Nobody - Nothing")),
    ("Empty", ()),
)

CHO = "{title: De Música Ligera}\n{artist: Soda Stereo}\n[Am]Ella du[F]rmió\n".encode()


def _phone_songbooks(conn, books) -> None:
    """The songbooks as the phone keeps them, phone_songbooks' rows (core.library.SongbookStore)."""
    from caracole.canonical import dumps
    from caracole.peer_sync import songbook_value
    from caracole.songbook import name_key

    for position, book in enumerate(books):
        conn.execute("INSERT INTO phone_songbooks (key, name, songs, position) VALUES (?, ?, ?, ?)",
                     (name_key(book.name), book.name, dumps(songbook_value(book)["songs"]), position))


def build_library(conn, cfg) -> dict[str, Any]:
    """The cases' library in ``conn`` (a fresh database) and ``cfg``'s library folder; the songs by their title."""
    from conftest import add_song
    from test_conformance_overrides import rows_of

    from caracole.db import kv_set_json
    from caracole.library import keep_file, song_dir
    from caracole.songbook import SongbookSong, check_setting, load_songbooks, put_songbook, songbooks_file
    from caracole.songs import get_song
    from caracole.versions import upsert_version

    from helpers.corpus import phone_schema

    phone_schema(conn)
    songs = {}
    for n, (artist, title) in enumerate(SONGS):
        song = add_song(conn, artist, title, added_at=f"2026-10-02T00:{n:02d}:00Z")
        songs[title] = song
    conn.execute("UPDATE songs SET status = 'ignored' WHERE id = ?", (songs["Song 2"].id,))
    android = songs["Paranoid Android"]
    conn.execute("UPDATE songs SET match_decision = 'accept', match_step = 'alias', match_score = 100.0, "
                 "match_artist_key = 'radiohead-uk', match_song_key = 'paranoid-android', match_candidates = '[]', "
                 "matched_at = ?, review = 0 WHERE id = ?", (STAMP, android.id))
    soda = get_song(conn, songs["De Música Ligera"].id)
    version = upsert_version(conn, provider="ug", tab_id="85053", song_id=soda.id, slot="sheet", kind="chords",
                             rating=4.8, votes=900, version=1, label=None,
                             url=SLUGGED.format("soda-stereo/de-musica-ligera", 85053), raw={"id": 85053}, now=STAMP)
    keep_file(conn, cfg.library_dir, song=soda, version_id=version, name="sheet.txt", data=b"[Am]Ella\n", rank=1)
    folder = song_dir(cfg.library_dir, soda)
    (folder / "sheet.cho").write_bytes(CHO)
    kv_set_json(conn, f"render:files:{soda.id}",
                {"sheet.cho": {"sha256": hashlib.sha256(CHO).hexdigest(), "size": len(CHO)}})
    conn.execute("UPDATE songs SET created_at = ?, updated_at = ?", (STAMP, STAMP))
    conn.execute("UPDATE files SET created_at = ?", (STAMP,))
    cfg.overrides_file.parent.mkdir(parents=True, exist_ok=True)
    cfg.overrides_file.write_text(OVERRIDES, encoding="utf-8")
    for row in rows_of(cfg.overrides_file):
        conn.execute("INSERT INTO phone_overrides (tbl, key, written, value) VALUES (?, ?, ?, ?)",
                     (row["tbl"], row["key"], row["written"], row["value"]))
    path = songbooks_file(cfg.library_dir)
    for name, entries in SONGBOOKS:
        put_songbook(path, name, [SongbookSong(e) if isinstance(e, str) else
                                  SongbookSong(e[0], check_setting(**e[1])) for e in entries])
    _phone_songbooks(conn, load_songbooks(path))
    return {title: get_song(conn, s.id) for title, s in songs.items()}


@contextmanager
def _library(tmp: Path) -> Iterator[tuple[Any, Any, dict[str, Any]]]:
    """A config over ``tmp`` and its database with the cases' library: (cfg, conn, songs by title)."""
    from caracole.config import load_config

    cfg = load_config(None, env={"HOME": str(tmp / "home"), "STATE_DIRECTORY": str(tmp / "state"),
                                 "CACHE_DIRECTORY": str(tmp / "cache")})
    cfg.state_dir.mkdir(parents=True, exist_ok=True)
    cfg.library_dir.mkdir(parents=True, exist_ok=True)
    with closing(db.connect(cfg.db_path)) as conn:
        songs = build_library(conn, cfg)
        yield cfg, conn, songs


def _fixture(conn, cfg) -> list[dict[str, Any]]:
    """The library as fixture records: the database, and the songs' files of the library folder (not songbooks.toml
    nor overrides.toml, which the phone holds as rows)."""
    own = {"songbooks.toml", "overrides.toml", "wanted.txt"}
    return [r for r in dump_fixture(conn, cfg.library_dir) if r.get("file") not in own]


# --- the scenarios -------------------------------------------------------------------------------------------------


def _app(cfg, limit: int):
    from caracole.web.app import WebApp
    from caracole.web.jobs import JobQueue

    def runner(args, emit):  # nothing runs: the queue is never started
        raise AssertionError(f"a route ran {args}")

    queue = JobQueue(runner, limit=limit)
    return WebApp(cfg, queue, allowed=frozenset({"localhost"}), csrf="tok", searches_lacuerda=False,
                  searches_youtube=False)


def _route(path: str):
    from caracole.web import songbook_routes, songbooks

    if path == songbooks.GET_MISSING:
        return songbook_routes.get_missing
    if path == songbooks.ADD_SONG:
        return songbook_routes.add_song
    assert path in songbooks.ROUTES, path
    return lambda app, form: songbook_routes.change(app, form, route=path)


def _wanted(cfg) -> str:
    return cfg.wanted_file.read_text("utf-8") if cfg.wanted_file.exists() else ""


def scenario(cfg, case: str, asked: list[tuple[str, list[tuple[str, str]]]], *, limit: int = 20) -> dict[str, Any]:
    """The forms ``asked`` posted in turn to one fresh queue of ``limit`` jobs: each answer, and the queue after."""
    app = _app(cfg, limit)
    before = _wanted(cfg)
    out = []
    wanted_jobs: set[int] = set()
    try:
        for path, form in asked:
            ids = {job.id for job in app.queue.snapshot()}
            written = _wanted(cfg)
            try:
                response = _route(path)(app, dict(form))
            except Refused as e:
                out.append({"status": e.status, "title": e.title, "message": e.message,
                            "wanted": _wanted(cfg) != written})
                continue
            data = response.data or {}
            lookups = [view["id"] for view in data.get("jobs", [])]
            wanted = _wanted(cfg) != written
            if wanted:
                wanted_jobs |= {job.id for job in app.queue.snapshot() if job.id not in ids and job.looks_up}
            location = next((v for k, v in response.headers if k == "Location"), None)
            out.append({"status": response.status, "location": location, "job": data["job"]["id"], "jobs": lookups,
                        "left": data.get("left"), "wanted": wanted,
                        "views": [data["job"], *data.get("jobs", [])]})
    finally:
        if before:
            cfg.wanted_file.write_text(before, encoding="utf-8")
        elif cfg.wanted_file.exists():
            cfg.wanted_file.unlink()
    queue = []
    for job in sorted(app.queue.snapshot(), key=lambda j: j.id):
        held = {"id": job.id, "title": job.title, "key": job.song_key,
                "steps": [[s.label, list(s.args)] for s in job.steps], "fetching": job.fetching, "note": job.note,
                "display": job.display, "together": list(job.together)}
        if job.id in wanted_jobs:
            held["wanted"] = True
        queue.append(held)
    return {"fn": "songbook_routes", "case": case, "limit": limit,
            "asked": [{"path": path, "form": [list(f) for f in form]} for path, form in asked], "out": out,
            "queue": queue}


MAKE, ADD, REMOVE, MOVE, SET = "/songbook/make", "/songbook/add", "/songbook/remove", "/songbook/move", "/songbook/set"
RENAME, DELETE, GET, ADD_SONG = "/songbook/rename", "/songbook/delete", "/songbook/get", "/songbook/add-song"


def scenarios(cfg, songs) -> list[dict[str, Any]]:
    ids = {title: str(song.id) for title, song in songs.items()}
    soda, wonder, muse, creep = ids["De Música Ligera"], ids["Wonderwall"], ids["Hysteria"], ids["Creep"]
    sept, zh = ids["September"], ids["斑马，斑马"]
    out = []

    def a(case: str, *asked: tuple[str, list[tuple[str, str]]], limit: int = 20) -> None:
        out.append(scenario(cfg, case, list(asked), limit=limit))

    # POST /songbook/make: the Select bar's songs, in the order picked
    a("make: two songs", (MAKE, [("name", "Beach"), ("songs", f"{wonder},{soda}")]))
    a("make: a song picked twice is in it once", (MAKE, [("name", "Beach"), ("songs", f"{wonder},{soda},{wonder}")]))
    a("make: the ids' spaces aside, the name's collapsed",
      (MAKE, [("name", "  Late \t night  "), ("songs", f" {muse} , {sept} ")]))
    a("make: songs of every kind", (MAKE, [("name", "篝火"), ("songs", f"{zh},{creep},{sept}")]))
    a("make: the same form twice is queued once", (MAKE, [("name", "Beach"), ("songs", wonder)]),
      (MAKE, [("name", "Beach"), ("songs", wonder)]))
    a("make: the same name, other songs, is another job", (MAKE, [("name", "Beach"), ("songs", wonder)]),
      (MAKE, [("name", "Beach"), ("songs", muse)]))
    a("make: a name taken, in any case", (MAKE, [("name", "campfire"), ("songs", wonder)]))
    a("make: a name taken, its spaces aside", (MAKE, [("name", "  Road  trip #1 "), ("songs", wonder)]))
    a("make: a name whose folder another songbook's is", (MAKE, [("name", "All/sheets"), ("songs", wonder)]))
    a("make: no name", (MAKE, [("songs", wonder)]))
    a("make: a name of spaces", (MAKE, [("name", "   "), ("songs", wonder)]))
    a("make: a name with a line break", (MAKE, [("name", "Camp\nfire"), ("songs", wonder)]))
    a("make: a name too long", (MAKE, [("name", "x" * 81), ("songs", wonder)]))
    a("make: a hidden name", (MAKE, [("name", ".Beach"), ("songs", wonder)]))
    a("make: a name taken before no songs", (MAKE, [("name", "Campfire")]))
    a("make: no songs", (MAKE, [("name", "Beach")]))
    a("make: songs of spaces", (MAKE, [("name", "Beach"), ("songs", "  ")]))
    a("make: a list that isn't ids", (MAKE, [("name", "Beach"), ("songs", f"{wonder},x")]))
    a("make: an empty id", (MAKE, [("name", "Beach"), ("songs", f"{wonder},,{soda}")]))
    a("make: an id no song has", (MAKE, [("name", "Beach"), ("songs", f"{wonder},9999")]))
    a("make: a song the phone hasn't got (a negative id, a mirror's card)",
      (MAKE, [("name", "Beach"), ("songs", f"-1,{wonder}")]))
    a("make: an id with a sign", (MAKE, [("name", "Beach"), ("songs", f"+{wonder}")]))
    a("make: a full queue", (MAKE, [("name", "Beach"), ("songs", wonder)]), limit=0)
    # POST /songbook/add
    a("add: to a songbook found in any case", (ADD, [("name", "CAMPFIRE"), ("songs", f"{sept},{zh}")]))
    a("add: songs it has already", (ADD, [("name", "Campfire"), ("songs", f"{soda},{wonder}")]))
    a("add: to a songbook that isn't there", (ADD, [("name", "Picnic"), ("songs", wonder)]))
    a("add: to a songbook of no songs", (ADD, [("name", "empty"), ("songs", wonder)]))
    a("add: no songs", (ADD, [("name", "Campfire")]))
    a("add: an id no song has", (ADD, [("name", "Campfire"), ("songs", "9999")]))
    a("add: no name", (ADD, [("songs", wonder)]))
    a("add: a full queue", (ADD, [("name", "Campfire"), ("songs", wonder)]), limit=0)
    # POST /songbook/remove: a song as songbooks.toml writes it
    a("remove: as the songbook writes it", (REMOVE, [("name", "Campfire"), ("song", "Oasis - Wonderwall")]))
    a("remove: its spaces collapsed, in another case", (REMOVE, [("name", "campfire"), ("song", "  muse -  HYSTERIA ")]))
    a("remove: a song gone from the library", (REMOVE, [("name", "Campfire"), ("song", "Nobody - Nothing")]))
    a("remove: a song the songbook hasn't got", (REMOVE, [("name", "Campfire"), ("song", "Earth - Wind - Fire - September")]))
    a("remove: no song", (REMOVE, [("name", "Campfire")]))
    a("remove: a song of spaces", (REMOVE, [("name", "Campfire"), ("song", "   ")]))
    a("remove: from a songbook that isn't there", (REMOVE, [("name", "Picnic"), ("song", "Oasis - Wonderwall")]))
    a("remove: Traditional for Simplified", (REMOVE, [("name", "Road trip #1"), ("song", "宋冬野 - 斑马，斑马")]))
    # POST /songbook/move
    a("move: to the first place", (MOVE, [("name", "Campfire"), ("song", "Muse - Hysteria"), ("position", "1")]))
    for position in ("0", "-1", "abc", "", "100000", "100001", " 3 ", "+2", "٣", "2.0"):
        a(f"move: to the position {position!r}",
          (MOVE, [("name", "Campfire"), ("song", "Muse - Hysteria"), ("position", position)]))
    a("move: no position", (MOVE, [("name", "Campfire"), ("song", "Muse - Hysteria")]))
    a("move: a song the songbook hasn't got",
      (MOVE, [("name", "Campfire"), ("song", "Earth - Wind - Fire - September"), ("position", "1")]))
    a("move: an artist with a dash in the name",
      (MOVE, [("name", "Road trip #1"), ("song", "earth - wind - fire - september"), ("position", "2")]))
    # POST /songbook/set: a song's chip
    for case, fields in (
        ("a key", [("key", "g")]),
        ("a key and its spaces", [("key", "  f#  ")]),
        ("a flat key", [("key", "bb")]),
        ("a key and a mode, with the capo", [("key", "G"), ("mode", "Dorian"), ("capo", "0")]),
        ("a mode alone", [("mode", "aeolian")]),
        ("a capo alone", [("capo", "3")]),
        ("no capo", [("capo", "0")]),
        ("an instrument alone", [("instrument", "Piano")]),
        ("a key, a capo and an instrument", [("key", "a"), ("capo", "0"), ("instrument", "ukulele-low-g")]),
        ("a key and an instrument", [("key", "C"), ("instrument", "harmonica")]),
        ("a capo and an instrument", [("capo", "2"), ("instrument", "baritone")]),
        ("its own version", [("clear", "1")]),
        ("its own version, on", [("clear", "on"), ("key", "G")]),
        ("its own version, yes", [("clear", "yes")]),
        ("clear that isn't one, nothing else", [("clear", "true")]),
        ("nothing", []),
        ("fields of spaces", [("key", " "), ("mode", " "), ("capo", " "), ("instrument", " ")]),
        ("a key that isn't one", [("key", "H")]),
        ("a key with a mode in it", [("key", "Am")]),
        ("a mode that isn't one", [("mode", "funky")]),
        ("a capo past 11", [("capo", "12")]),
        ("a capo below 0", [("capo", "-1")]),
        ("a capo that isn't a number", [("capo", "two")]),
        ("a capo of a digit that isn't ASCII", [("capo", "³")]),
        ("an instrument that isn't one", [("instrument", "banjo")]),
        ("a key whose first letter grows when made upper case", [("key", "ßb")]),
    ):
        a(f"set: {case}", (SET, [("name", "Campfire"), ("song", "Eagles - Hotel California"), *fields]))
    a("set: the song as typed, its spaces collapsed",
      (SET, [("name", "campfire"), ("song", " eagles  -  hotel california "), ("key", "E")]))
    a("set: the same setting twice is queued once",
      (SET, [("name", "Campfire"), ("song", "Oasis - Wonderwall"), ("key", "G")]),
      (SET, [("name", "Campfire"), ("song", "Oasis - Wonderwall"), ("key", "G")]))
    a("set: another setting of the same song is another job",
      (SET, [("name", "Campfire"), ("song", "Oasis - Wonderwall"), ("key", "G")]),
      (SET, [("name", "Campfire"), ("song", "Oasis - Wonderwall"), ("key", "A")]))
    a("set: a song the songbook hasn't got", (SET, [("name", "Campfire"), ("song", "Earth - Wind - Fire - September"),
                                                    ("key", "G")]))
    a("set: a song checked before the setting", (SET, [("name", "Campfire"), ("song", "A - B"), ("key", "H")]))
    a("set: no song", (SET, [("name", "Campfire"), ("key", "G")]))
    a("set: a Chinese song", (SET, [("name", "Road trip #1"), ("song", "宋冬野 - 斑马，斑马"), ("capo", "1")]))
    # POST /songbook/rename
    a("rename: to a new name", (RENAME, [("name", "Campfire"), ("new", "  Fogata  ")]))
    a("rename: in another case", (RENAME, [("name", "campfire"), ("new", "CAMPFIRE")]))
    a("rename: to its own folder", (RENAME, [("name", "all-sheets"), ("new", "All/sheets")]))
    a("rename: to a name another has", (RENAME, [("name", "Campfire"), ("new", "road trip #1")]))
    a("rename: to a folder another's is", (RENAME, [("name", "Campfire"), ("new", "all/SHEETS")]))
    a("rename: to no name", (RENAME, [("name", "Campfire"), ("new", "")]))
    a("rename: to a hidden name", (RENAME, [("name", "Campfire"), ("new", ".x")]))
    a("rename: a songbook that isn't there", (RENAME, [("name", "Picnic"), ("new", "Lunch")]))
    a("rename: no new name given", (RENAME, [("name", "Campfire")]))
    # POST /songbook/delete
    a("delete: a songbook", (DELETE, [("name", " campfire ")]))
    a("delete: a songbook of no songs", (DELETE, [("name", "Empty")]))
    a("delete: a songbook that isn't there", (DELETE, [("name", "Picnic")]))
    a("delete: no name", (DELETE, []))
    a("delete: twice is queued once", (DELETE, [("name", "Empty")]), (DELETE, [("name", "Empty")]))
    a("delete: a full queue", (DELETE, [("name", "Empty")]), limit=0)
    # POST /songbook/get: Get the missing songs now, and a set list's Get it
    a("get: its songs without a sheet, then the songbook", (GET, [("name", "Campfire")]))
    a("get: found in any case", (GET, [("name", "campfire")]))
    a("get: a queue with room for some: the first ones", (GET, [("name", "Campfire")]), limit=3)
    a("get: a queue with room for one: none", (GET, [("name", "Campfire")]), limit=1)
    a("get: a full queue", (GET, [("name", "Campfire")]), limit=0)
    a("get: tapped again while they wait", (GET, [("name", "Campfire")]), (GET, [("name", "Campfire")]))
    a("get: tapped again after the first ones, room for the rest", (GET, [("name", "Campfire")]),
      (GET, [("name", "Campfire")]), limit=3)
    a("get: every song has a sheet", (GET, [("name", "All-sheets")]))
    a("get: a songbook of no songs", (GET, [("name", "Empty")]))
    a("get: a set list's Get it", (GET, [("name", "Campfire"), ("song", wonder)]))
    a("get: a set list's Get it, then the songbook's", (GET, [("name", "Campfire"), ("song", wonder)]),
      (GET, [("name", "Campfire")]))
    a("get: one song with a sheet", (GET, [("name", "Campfire"), ("song", soda)]))
    a("get: one song ignored", (GET, [("name", "Campfire"), ("song", creep)]))
    a("get: one song the songbook hasn't got", (GET, [("name", "Campfire"), ("song", sept)]))
    a("get: a song that isn't an id", (GET, [("name", "Campfire"), ("song", "x")]))
    a("get: a song of spaces is the songbook's", (GET, [("name", "Campfire"), ("song", "  ")]))
    a("get: a songbook that isn't there", (GET, [("name", "Picnic")]))
    a("get: no name", (GET, []))
    a("get: after another lookup of one of them", (ADD_SONG, [("name", "Road trip #1"), ("song", muse)]),
      (GET, [("name", "Campfire")]))
    # POST /songbook/add-song: the Songbooks tab's search
    a("add-song: a song of the library by its id", (ADD_SONG, [("name", "Road trip #1"), ("song", muse)]))
    a("add-song: one the songbook has already", (ADD_SONG, [("name", "Campfire"), ("song", wonder)]))
    a("add-song: a song of the library by its names", (ADD_SONG, [("name", "road trip #1"), ("artist", "oasis"),
                                                                  ("title", "wonderwall")]))
    a("add-song: a song of the library by its Ultimate Guitar pick",
      (ADD_SONG, [("name", "Campfire"), ("ug", "radiohead-uk/paranoid-android"), ("artist", "Radiohead UK"),
                  ("title", "Paranoid Android")]))
    a("add-song: a song new to the library, looked up first",
      (ADD_SONG, [("name", "Campfire"), ("artist", "Fito Páez"), ("title", "Mariposa Tecknicolor")]))
    a("add-song: a new song with its picks",
      (ADD_SONG, [("name", "Campfire"), ("artist", "Radiohead"), ("title", "Street Spirit"),
                  ("ug", "radiohead/street-spirit"), ("tab", "https://tabs.ultimate-guitar.com/tab/radiohead/"
                                                             "street-spirit-chords-4170")]))
    a("add-song: a new song to two songbooks: one lookup", (ADD_SONG, [("name", "Campfire"), ("artist", "Fito Páez"),
                                                                     ("title", "Mariposa Tecknicolor")]),
      (ADD_SONG, [("name", "Empty"), ("artist", "Fito Páez"), ("title", "Mariposa Tecknicolor")]))
    a("add-song: the same twice is queued once", (ADD_SONG, [("name", "Campfire"), ("artist", "Fito Páez"),
                                                            ("title", "Mariposa Tecknicolor")]),
      (ADD_SONG, [("name", "Campfire"), ("artist", "Fito Páez"), ("title", "Mariposa Tecknicolor")]))
    a("add-song: one text alone names no song", (ADD_SONG, [("name", "Campfire"), ("q", "Fito Páez - Mariposa")]))
    a("add-song: no song", (ADD_SONG, [("name", "Campfire")]))
    a("add-song: an artist and no title", (ADD_SONG, [("name", "Campfire"), ("artist", "Fito Páez")]))
    a("add-song: an id no song has", (ADD_SONG, [("name", "Campfire"), ("song", "9999")]))
    a("add-song: an id that isn't one", (ADD_SONG, [("name", "Campfire"), ("song", "x")]))
    a("add-song: a pick that isn't one", (ADD_SONG, [("name", "Campfire"), ("ug", "radiohead"), ("artist", "A"),
                                                     ("title", "B")]))
    a("add-song: to a songbook that isn't there", (ADD_SONG, [("name", "Picnic"), ("song", muse)]))
    a("add-song: a title too long", (ADD_SONG, [("name", "Campfire"), ("artist", "A"), ("title", "x" * 301)]))
    a("add-song: a full queue, a song of the library", (ADD_SONG, [("name", "Campfire"), ("song", muse)]), limit=0)
    a("add-song: a full queue, a new song", (ADD_SONG, [("name", "Campfire"), ("artist", "Fito Páez"),
                                                       ("title", "Mariposa Tecknicolor")]), limit=0)
    a("add-song: room for the lookup alone: neither", (ADD_SONG, [("name", "Campfire"), ("artist", "Fito Páez"),
                                                                 ("title", "Mariposa Tecknicolor")]), limit=1)
    a("add-song: a lookup that joins one queued needs no room", (ADD_SONG, [("name", "Campfire"),
                                                                           ("artist", "Fito Páez"),
                                                                           ("title", "Mariposa Tecknicolor")]),
      (ADD_SONG, [("name", "Empty"), ("artist", "Fito Páez"), ("title", "Mariposa Tecknicolor")]), limit=3)
    return out


# --- the runner -----------------------------------------------------------------------------------------------------

# Each case's commands, each its words after ``caracole songbook`` as SongbookRoutes queues them (the names after
# "--"), run in turn over the fixture's songbooks (test_conformance_songbook_tab.SONGBOOKS: Campfire, Settings,
# Road trip #1, Empty).
RUNNER_CASES: tuple[tuple[str, tuple[tuple[str, ...], ...]], ...] = (
    # make
    ("make: two songs", (("make", "--", "Beach", "Oasis - Wonderwall", "Soda Stereo - De Música Ligera"),)),
    ("make: a song named twice is in it once", (("make", "--", "Beach", "Oasis - Wonderwall", "oasis - WONDERWALL"),)),
    ("make: songs found by a search", (("make", "--", "Beach", "wonderwall", "ban ma ban ma"),)),
    ("make: a song in Traditional characters", (("make", "--", "篝火", "宋冬野 - 斑馬，斑馬"),)),
    ("make: songs the library hasn't got, with what they may mean",
     (("make", "--", "Beach", "Nobody - Nothing", "Oasis", "zzzz qqqq"),)),
    ("make: a song typed with a typo", (("make", "--", "Beach", "Oasis - Wonderwal"),)),
    ("make: a name another songbook has", (("make", "--", "  CAMPFIRE ", "Oasis - Wonderwall"),)),
    ("make: a hidden name", (("make", "--", ".Beach", "Oasis - Wonderwall"),)),
    ("make: then add to it", (("make", "--", "Beach", "Muse - Hysteria"),
                              ("add", "--", "beach", "Radiohead - Creep", "Muse - Hysteria"))),
    # add
    ("add: songs, one in it already", (("add", "--", "campfire", "Earth - Wind - Fire - September",
                                        "Oasis - Wonderwall"),)),
    ("add: to a songbook of none", (("add", "--", "Empty", "AC/DC - T.N.T. (Live)"),)),
    ("add: to a songbook that isn't there", (("add", "--", "  Pic   nic ", "Oasis - Wonderwall"),)),
    ("add: a song the library hasn't got", (("add", "--", "Campfire", "Fito Páez - Mariposa Tecknicolor"),)),
    ("add: a song found by a search", (("add", "--", "Road trip #1", "hysteria"),)),
    # remove
    ("remove: as the songbook writes it", (("remove", "--", "Campfire", "oasis - WONDERWALL"),)),
    ("remove: a song gone from the library", (("remove", "--", "Campfire", "Nobody - Nothing"),)),
    ("remove: one in it, one not", (("remove", "--", "Campfire", "Muse - Hysteria",
                                     "Earth - Wind - Fire - September"),)),
    ("remove: none in it", (("remove", "--", "Campfire", "Earth - Wind - Fire - September"),)),
    ("remove: a song found by a search", (("remove", "--", "Campfire", "wonderwall"),)),
    ("remove: Traditional for Simplified", (("remove", "--", "Settings", "宋冬野 - 斑馬，斑馬"),)),
    ("remove: from a songbook that isn't there", (("remove", "--", "Picnic", "Oasis - Wonderwall"),)),
    # move
    ("move: to the first place", (("move", "--", "Campfire", "Muse - Hysteria", "1"),)),
    ("move: past the end", (("move", "--", "Campfire", "Muse - Hysteria", "100000"),)),
    ("move: a song the songbook hasn't got", (("move", "--", "Campfire", "Earth - Wind - Fire - September", "1"),)),
    ("move: an artist with a dash in the name", (("move", "--", "Road trip #1", "earth - wind - fire - september",
                                                  "3"),)),
    ("move: a song gone from the library", (("move", "--", "Campfire", "Nobody - Nothing", "1"),)),
    # set: a song with no setting, with a sheet
    ("set: a key", (("set", "--key", "g", "--", "Campfire", "Soda Stereo - De Música Ligera"),)),
    ("set: a key with a sharp", (("set", "--key", "f#", "--", "Campfire", "Oasis - Wonderwall"),)),
    ("set: a mode alone", (("set", "--mode", "Dorian", "--", "Campfire", "Soda Stereo - De Música Ligera"),)),
    ("set: a key and a mode", (("set", "--key", "D", "--mode", "dorian", "--", "Campfire",
                                "Eagles - Hotel California (Live)"),)),
    ("set: a capo alone", (("set", "--capo", "3", "--", "Campfire", "Soda Stereo - De Música Ligera"),)),
    ("set: no capo", (("set", "--capo", "0", "--", "Campfire", "Oasis - Wonderwall"),)),
    ("set: a key with a capo", (("set", "--key", "A", "--capo", "2", "--", "Campfire", "Oasis - Wonderwall"),)),
    ("set: an instrument alone", (("set", "--instrument", "Piano", "--", "Campfire", "Oasis - Wonderwall"),)),
    ("set: an instrument and a key", (("set", "--instrument", "piano", "--key", "C", "--", "Campfire",
                                       "Oasis - Wonderwall"),)),
    ("set: an instrument and a capo", (("set", "--instrument", "ukulele", "--capo", "1", "--", "Campfire",
                                        "Oasis - Wonderwall"),)),
    ("set: the harmonica", (("set", "--instrument", "harmonica", "--", "Campfire", "Soda Stereo - De Música Ligera"),)),
    ("set: a song with no sheet", (("set", "--key", "G", "--", "Campfire", "Muse - Hysteria"),)),
    ("set: a sheet with no key", (("set", "--key", "G", "--", "Settings", "Nobody - Keyless"),)),
    ("set: a Chinese song", (("set", "--capo", "1", "--", "Campfire", "宋冬野 - 斑马，斑马"),)),
    ("set: an auto sheet", (("set", "--key", "D", "--", "Campfire", "Placeholder Band - Synthetic Song"),)),
    # set: a song with a setting
    ("set: a key over a key", (("set", "--key", "A", "--", "Settings", "Soda Stereo - De Música Ligera"),)),
    ("set: a capo over a mode", (("set", "--capo", "2", "--", "Settings", "Oasis - Wonderwall"),)),
    ("set: another instrument over a key and a mode", (("set", "--instrument", "piano", "--", "Settings",
                                                       "Eagles - Hotel California"),)),
    ("set: back to the guitar from the piano", (("set", "--instrument", "guitar", "--", "Settings",
                                                 "Earth - Wind - Fire - September"),)),
    ("set: the guitar from the piano, a capo given", (("set", "--instrument", "guitar", "--capo", "3", "--",
                                                       "Settings", "Earth - Wind - Fire - September"),)),
    ("set: the guitar from the piano, a key given", (("set", "--instrument", "guitar", "--key", "E", "--",
                                                      "Settings", "Earth - Wind - Fire - September"),)),
    ("set: the ukulele from the baritone", (("set", "--instrument", "ukulele", "--", "Road trip #1",
                                             "AC/DC - T.N.T."),)),
    ("set: a key on the harmonica", (("set", "--key", "G", "--", "Settings", "Placeholder Band - Synthetic Song"),)),
    ("set: a mode over a key and no capo", (("set", "--mode", "mixolydian", "--", "Settings", "Muse - Hysteria"),)),
    ("set: its setting cleared", (("set", "--clear", "--", "Settings", "Eagles - Hotel California"),)),
    ("set: a song gone from the library", (("set", "--key", "D", "--", "Settings", "Nobody - Nothing"),)),
    ("set: a key, then an instrument at the pitch it plays at",
     (("set", "--key", "G", "--capo", "3", "--", "Campfire", "Soda Stereo - De Música Ligera"),
      ("set", "--instrument", "piano", "--", "Campfire", "Soda Stereo - De Música Ligera"),
      ("set", "--instrument", "baritone", "--", "Campfire", "Soda Stereo - De Música Ligera"))),
    # set: refused
    ("set: nothing to set", (("set", "--", "Campfire", "Oasis - Wonderwall"),)),
    ("set: both a part and clear", (("set", "--clear", "--key", "G", "--", "Campfire", "Oasis - Wonderwall"),)),
    ("set: a key that isn't one", (("set", "--key", "H", "--", "Campfire", "Oasis - Wonderwall"),)),
    ("set: a key whose first letter grows made upper case", (("set", "--key", "ßb", "--", "Campfire",
                                                              "Oasis - Wonderwall"),)),
    ("set: a mode that isn't one", (("set", "--mode", "funky", "--", "Campfire", "Oasis - Wonderwall"),)),
    ("set: an instrument that isn't one", (("set", "--instrument", "banjo", "--", "Campfire", "Oasis - Wonderwall"),)),
    ("set: a song the songbook hasn't got", (("set", "--key", "G", "--", "Campfire",
                                              "Earth - Wind - Fire - September"),)),
    ("set: in a songbook that isn't there", (("set", "--key", "G", "--", "Picnic", "Oasis - Wonderwall"),)),
    # rename
    ("rename: to a new name", (("rename", "--", "Campfire", "  Fogata  "),)),
    ("rename: in another case", (("rename", "--", "campfire", "CAMPFIRE"),)),
    ("rename: to a name another has", (("rename", "--", "Campfire", "road trip #1"),)),
    ("rename: to a hidden name", (("rename", "--", "Campfire", ".x"),)),
    ("rename: a songbook that isn't there", (("rename", "--", "Picnic", "Lunch"),)),
    # delete
    ("delete: a songbook", (("delete", "--", " campfire "),)),
    ("delete: a songbook of none", (("delete", "--", "Empty"),)),
    ("delete: a songbook that isn't there", (("delete", "--", "Picnic"),)),
    # render
    ("render: every songbook", (("render",),)),
    ("render: one", (("render", "--", "campfire"),)),
    ("render: one that isn't there", (("render", "--", "Picnic"),)),
)


def runner_records(tmp: Path) -> list[dict[str, Any]]:
    """RUNNER_CASES' commands through caracole's CLI, as the module's docstring says."""
    from test_conformance_songbook_tab import _Library, _overrides, overrides_json
    from typer.testing import CliRunner

    from caracole.cli import build_app
    from caracole.peer_sync import songbook_value
    from caracole.songbook import SongbookStats, load_songbooks, songbooks_file

    (tmp / "library").mkdir()
    lib = _Library(tmp / "library")
    try:
        cfg = lib.cfg
        toml = tmp / "caracole.toml"
        toml.write_text(f"library_dir = {json.dumps(str(cfg.library_dir))}\n"
                        f"state_dir = {json.dumps(str(cfg.state_dir))}\n"
                        f"cache_dir = {json.dumps(str(cfg.cache_dir))}\n", encoding="utf-8")
        path = songbooks_file(cfg.library_dir)
        original = path.read_bytes()
        library = str(cfg.library_dir)
        env = {name: None for name in ("CARACOLE_CONFIG", "JOURNAL_STREAM", "INVOCATION_ID", "NO_COLOR",
                                       "FORCE_COLOR", "CARACOLE_CJK_FONT")}
        out: list[dict[str, Any]] = [{"fn": "overrides", "out": overrides_json()}]
        with pytest.MonkeyPatch.context() as patch:
            patch.setattr("caracole.songbook.render_songbooks", lambda *a, **k: SongbookStats())
            patch.setattr("caracole.commands.songbook.write_pages", lambda *a, **k: None)
            patch.setattr("caracole.commands.songbook.load_ovr", lambda cfg: _overrides())
            for case, commands in RUNNER_CASES:
                path.write_bytes(original)
                said = []
                for args in commands:
                    result = CliRunner().invoke(build_app(), ["--config", str(toml), "songbook", *args], env=env)
                    assert result.exception is None or isinstance(result.exception, SystemExit), (
                        case, args, result.output)
                    lines = result.output.replace(library, "{library}").splitlines()
                    assert not any(line.startswith(("Usage:", "Try ", "╭")) for line in lines), (case, lines)
                    said.append({"args": ["songbook", *args], "lines": lines, "code": result.exit_code})
                out.append({"fn": "songbook_runner", "case": case, "commands": said,
                            "songbooks": [songbook_value(b) for b in load_songbooks(path)]})
        path.write_bytes(original)
        return out
    finally:
        lib.conn.close()


# --- the vectors ---------------------------------------------------------------------------------------------------


@pytest.fixture(scope="module")
def made(tmp_path_factory) -> list[dict[str, Any]]:
    tmp = tmp_path_factory.mktemp("songbook_routes")
    with _library(tmp / "library") as (cfg, conn, songs):
        return [{"fn": "fixture", "records": _fixture(conn, cfg)}, *scenarios(cfg, songs)]


def test_the_routes_vectors_are_caracole_serves_answers(made):
    check(ROUTES, jsonl(made, corpus="songbook/routes", made_by=MADE_BY))


def test_every_route_answers_a_job_and_a_refusal(made):
    by: dict[str, set[bool]] = {}
    for r in made[1:]:
        for asked, out in zip(r["asked"], r["out"], strict=True):
            by.setdefault(asked["path"], set()).add("job" in out)
    assert set(by) == {MAKE, ADD, REMOVE, MOVE, SET, RENAME, DELETE, GET, ADD_SONG}
    assert all(seen == {True, False} for seen in by.values()), by


def test_the_cases_meet_what_they_name(made):
    out = {r["case"]: r for r in made[1:]}
    twice = out["make: the same form twice is queued once"]
    assert [o["job"] for o in twice["out"]] == [1, 1] and len(twice["queue"]) == 1
    assert out["make: a full queue"]["out"][0]["status"] == 503
    assert out["make: a song the phone hasn't got (a negative id, a mirror's card)"]["out"][0]["message"] == (
        "A song you picked isn't in the library any more: reload the library and pick again.")
    assert out["make: a name whose folder another songbook's is"]["out"][0]["status"] == 409
    get = out["get: its songs without a sheet, then the songbook"]
    assert [j["display"] for j in get["queue"][:-1]] == ["Oasis - Wonderwall", "Muse - Hysteria",
                                                         "Eagles - Hotel California"]
    assert get["out"][0]["left"] == 0 and get["queue"][-1]["key"].endswith("\x1f3")
    some = out["get: a queue with room for some: the first ones"]
    assert some["out"][0]["left"] == 1 and len(some["queue"]) == 3
    assert out["get: a queue with room for one: none"]["out"][0]["status"] == 503
    again = out["get: tapped again while they wait"]
    assert again["out"][0]["job"] == again["out"][1]["job"] and len(again["queue"]) == 4
    new = out["add-song: a song new to the library, looked up first"]
    assert new["out"][0]["wanted"] and new["queue"][0]["wanted"] and new["queue"][0]["together"] == [1, 2]
    assert new["queue"][1]["steps"][0][1][:3] == ["songbook", "add", "--"]
    joins = out["add-song: a lookup that joins one queued needs no room"]
    assert len(joins["queue"]) == 3 and "job" in joins["out"][1]
    neither = out["add-song: room for the lookup alone: neither"]
    assert neither["out"][0]["status"] == 503 and neither["queue"] == []
    sets = {r["case"]: r["out"][0] for r in made[1:] if r["case"].startswith("set: ")}
    assert sets["set: a key whose first letter grows when made upper case"]["status"] == 400
    assert "job" in sets["set: its own version, on"]


@pytest.fixture(scope="module")
def ran(tmp_path_factory) -> list[dict[str, Any]]:
    return runner_records(tmp_path_factory.mktemp("songbook_runner"))


def test_the_runner_vectors_are_caracole_songbooks(ran):
    check(RUNNER, jsonl(ran, corpus="songbook/routes_runner", made_by=MADE_BY))


def test_the_runner_cases_meet_what_they_name(ran):
    out = {r["case"]: r for r in ran[1:]}
    assert len(out) == len(RUNNER_CASES)
    codes = {r["commands"][-1]["code"] for r in ran[1:]}
    assert codes == {0, 1, 2}, codes
    unknown = out["make: songs the library hasn't got, with what they may mean"]["commands"][0]
    assert unknown["code"] == 1 and unknown["lines"][0].startswith('error: No song "Nobody - Nothing"')
    assert len(unknown["lines"]) == 4 and not unknown["lines"][1].startswith("error:"), unknown
    assert "did you mean" in unknown["lines"][1], unknown
    made = out["make: two songs"]["commands"][0]["lines"]
    assert made[0] == 'Made the songbook "Beach": 2 songs.' and made[-1].startswith("Nothing written in {library}/")
    assert out["render: one"]["commands"][0]["lines"][-1] == "0 rendered, 0 up to date, 0 failed"
    wrote = out["add: songs, one in it already"]["commands"][0]["lines"][-1]
    assert wrote == "Wrote {library}/_songbooks/Campfire: songbook.pdf, songbook.html, songbook.cho", wrote
    steps = out["set: a key, then an instrument at the pitch it plays at"]
    assert [c["code"] for c in steps["commands"]] == [0, 0, 0]
    sets = [r for r in ran[1:] if r["case"].startswith("set: ") and r["commands"][-1]["code"] == 0]
    assert any("In the songbook: " in line for r in sets for c in r["commands"] for line in c["lines"])


def test_the_vectors_are_the_same_on_another_run(made, tmp_path_factory):
    tmp = tmp_path_factory.mktemp("again")
    with _library(tmp / "library") as (cfg, conn, songs):
        assert [{"fn": "fixture", "records": _fixture(conn, cfg)}, *scenarios(cfg, songs)] == made
