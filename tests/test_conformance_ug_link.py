"""A UG link pasted into the library page's search box, for the phone's lane ug-link to replay (an area of its own,
``ug-link``): server/routes/UgLinkRoutes.kt (both routes), core/lookup/sites/UgLinkCommands.kt and
server/lookups/UgLinkRunner.kt (``caracole ug --link``), as caracole serve's web/ug_link_routes.py, ug_urls.py,
ug/link.py and commands/ug.py answer (docs/superpowers/plans/2026-11-17-ug-link.md).

**vectors/web/ug_link.jsonl**, after its header:

- ``{"fn": "caracole.ug_urls.read_link", "args": [text], "out": {kind, url, tab_id, type} | null}``: every shape of
  tests/helpers/ug_links.py, the one list library.js's ``ugLink`` is held to too.
- ``{"fn": "fixture", "scene", "records", "cache"}``: a scene, a library in a fresh database dumped whole with its
  library folder's files (``helpers.corpus.dump_fixture``; overrides.toml as the phone's ``phone_overrides`` rows,
  never as a file) and Ultimate Guitar's
  answers in caracole's HTTP cache (``cache``: ``{"GET <url>": {status, fetched_at, headers, body}}``, as
  helpers/scenario.py's records carry one), which the replay loads; every record after it names the scene it asks
  over. ``empty``: nothing read. ``read``: ``caracole ug --link`` run over 宋冬野's tab 4180894 (its page and its
  artist's lists), a tab UG answers 404 for (999) and a Guitar Pro tab's page (7001); 宋冬野 - 董小姐 in the library, its
  sheet UG's tab 3016223 and a ``[pin]`` of 3204647; Soda Stereo's slugged tab 85053 in the index. ``cooling``: UG
  cooling down after a block. ``spent``: the hour's lookups to UG spent (``events``). ``failed``: tab 4180894's read
  failed within the hour (kv ``ug:link-failed``), tab 5555's page won't parse until it is due (kv
  ``ug:unreadable:5555``).
- ``{"fn": "GET /api/ug/link", "scene", "case", "url", "out": {"status", "body"}}``: the answer (``link_answer``) at
  ``NOW``, or a refusal's ``{"status", "title", "message"}``.
- ``{"fn": "POST /ug/link", "scene", "case", "url", "out": ...}``: the form posted to a fresh queue that runs nothing
  (``read_ug_link``, its script's: JSON), at ``NOW``: ``{"status", "body", "job": {title, key, steps, display,
  stages}}``, or a refusal.

**vectors/lookup/commands_ug_link.jsonl**: ``caracole ug --link`` (commands/ug.py ``_read``, ``kw.link`` its
argument, ``kw.progress`` its ``--progress``), scenario records (helpers/scenario.py ``record``, as
commands_harptabs.jsonl's), each in a world of its own: a client of provider ``ug`` (the record's budget, no pause)
and UG's answers, every request with caracole's own user agent (``agent``). ``out.result`` the lines it printed, its
last the line caracole serve's request line shows; what it read and recorded (rows, kv: ``ug:artist_url:``,
``ug:link-failed``, ``ug:unreadable:``, ``provider:ug``); and ``noted``, the artist pages the phone notes for its
next push (kv ``phone:read:ug:<page>``, the store's time or the read's where later: scenario.py's ``noted``), which
Python doesn't write.

Regenerate with ``CARACOLE_CORPUS=write nix develop -c pytest -q -n 0 tests/test_conformance_ug_link.py``.
"""

from __future__ import annotations

import gzip
import json
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterator
from unittest import mock

import pytest
from helpers.corpus import VECTORS, check, dump_fixture, jsonl, phone_schema
from helpers.scenario import _noting, record
from helpers.ug_links import SHAPES
from helpers.ug_pages import (
    NOT_FOUND,
    SONG_DONGYE_CHORDS_URL,
    SONG_DONGYE_TABS_URL,
    SONG_DONGYE_URL,
    FakeUG,
    make_tab_page_html,
    song_dongye_tab,
    version_dict,
)

MADE_BY = "tests/test_conformance_ug_link.py"
WEB_FILE = VECTORS / "web" / "ug_link.jsonl"
COMMANDS_FILE = VECTORS / "lookup" / "commands_ug_link.jsonl"
NOW = datetime(2026, 11, 17, 12, 0, tzinfo=UTC)
STAMP = "2026-11-17T12:00:00Z"
ADDED = "2026-10-01T00:00:00Z"
TAB = "https://tabs.ultimate-guitar.com/tab/"
FOUND = f"{TAB}4180894"
HTML = [["content-type", "text/html; charset=utf-8"]]
PRO = make_tab_page_html(version_dict(7001, type="Pro", song="One", artist="Metallica",
                                      artist_url="https://www.ultimate-guitar.com/artist/metallica_1"),
                         [], meta={"fileExtension": ".gp5"})
CSRF = "tok"


def ok(body: str) -> dict[str, Any]:
    return {"status": 200, "headers": HTML, "body": body}


def status(code: int, body: str = NOT_FOUND) -> dict[str, Any]:
    return {"status": code, "headers": HTML, "body": body}


def song_dongye() -> dict[str, dict[str, Any]]:
    """UG's answers for 宋冬野 (helpers/ug_pages.py ``FakeUG``), by address."""
    return {url: ok(html) for url, html in FakeUG().pages.items()}


@contextmanager
def _clock() -> Iterator[None]:
    with mock.patch("caracole.songs.utc_now_iso", lambda: ADDED):
        yield


class _Kept:
    """A connection whose close() is a command's ``closing(open_db(cfg))``'s alone: the world keeps it open."""

    def __init__(self, conn):
        self.conn = conn

    def __getattr__(self, name: str):
        return getattr(self.conn, name)

    def close(self) -> None:
        pass


class World:
    """A phone's library: its database, its folder, its config (its cache the client's too) and its overrides."""

    def __init__(self, tmp: Path, name: str):
        from caracole import db
        from caracole.config import load_config

        self.dir = tmp / name
        self.dir.mkdir(parents=True)
        (self.dir / "library").mkdir()
        (self.dir / "caracole.toml").write_text(
            f'library_dir = "{self.dir / "library"}"\nstate_dir = "{self.dir / "state"}"\n'
            f'cache_dir = "{self.dir / "cache"}"\n', encoding="utf-8")
        self.cfg = load_config(self.dir / "caracole.toml", env={"HOME": str(self.dir / "home")})
        self.cfg.state_dir.mkdir(parents=True, exist_ok=True)
        self.conn = db.connect(self.cfg.db_path)  # the one the routes open too
        phone_schema(self.conn)

    def run(self, case: str, link: str, answers: dict[str, dict[str, Any]], *, progress: bool = False,
            budget: int = 6) -> dict[str, Any]:
        """``caracole ug --link`` over this world, recorded (the module's docstring)."""
        from caracole.commands import ug
        from caracole.config import DEFAULT_USER_AGENT
        from caracole.ug_urls import read_link

        noted: dict[str, str] = {}

        def call(made):
            lines: list[str] = []
            patches = [mock.patch.object(ug, "make_client", lambda *a, **k: made["ug"]),
                       mock.patch.object(ug, "open_db", lambda cfg: _Kept(self.conn)),
                       mock.patch.object(ug, "utcnow", lambda: NOW),
                       mock.patch("typer.echo", lambda message="", **k: lines.append(str(message)))]
            patches += [mock.patch.object(module, name, wrapper) for module, name, wrapper in _noting(noted, STAMP)]
            for p in patches:
                p.start()
            try:
                found = read_link(link)
                assert found is not None, link
                ug._read(self.cfg, found, progress=progress)
            finally:
                for p in reversed(patches):
                    p.stop()
            return lines

        with _clock():
            made = record(self.conn, self.cfg.library_dir, fn="caracole.commands.ug._read", case=case, call=call,
                          kw={"link": link, "progress": progress}, now=NOW,
                          clients={"ug": {"budget": budget, "delay": [0.0, 0.0]}},
                          answers={f"GET {u}": a for u, a in answers.items()}, cache_dir=self.cfg.cache_dir)
        done = made.get("out") or made["after"]
        made["answers"] = {r: a for r, a in made["answers"].items() if r in done["requests"]}  # what was asked alone
        made["agent"] = DEFAULT_USER_AGENT
        done["noted"] = dict(sorted(noted.items()))
        return made

    def song(self, artist: str, title: str):
        from conftest import add_song

        with _clock():
            return add_song(self.conn, artist, title, added_at=ADDED)

    def overrides(self, toml: str) -> None:
        from test_conformance_overrides import rows_of

        self.cfg.overrides_file.write_text(toml, encoding="utf-8")
        self.conn.execute("DELETE FROM phone_overrides")
        for row in rows_of(self.cfg.overrides_file):
            self.conn.execute("INSERT INTO phone_overrides (tbl, key, written, value) VALUES (?, ?, ?, ?)",
                              (row["tbl"], row["key"], row["written"], row["value"]))

    def cache(self) -> dict[str, dict[str, Any]]:
        """UG's answers in the HTTP cache, as a scenario record carries one."""
        root = self.cfg.cache_dir / "http" / "ug"
        held = {}
        for meta in sorted(root.rglob("*.json")) if root.is_dir() else []:
            said = json.loads(meta.read_text(encoding="utf-8"))
            body = gzip.decompress(meta.with_suffix(".body").read_bytes()).decode("utf-8")
            held[f"GET {said['url']}"] = {"status": said["status"], "fetched_at": said["fetched_at"],
                                          "headers": said.get("headers", {}), "body": {"text": body}}
        return dict(sorted(held.items()))

    def fixture(self, scene: str) -> dict[str, Any]:
        self.conn.execute("UPDATE songs SET created_at = ?, updated_at = ?", (ADDED, ADDED))
        self.conn.execute("UPDATE files SET created_at = ?", (ADDED,))
        # The library's files too (a song's sheet.txt, which its card's links and the song's sheet link read), but
        # overrides.toml, which the phone holds as its phone_overrides rows.
        records = [r for r in dump_fixture(self.conn, self.cfg.library_dir) if r.get("file") != "overrides.toml"]
        return {"fn": "fixture", "scene": scene, "records": records, "cache": self.cache()}

    def app(self):
        from caracole.web.app import WebApp
        from caracole.web.jobs import JobQueue

        def runner(args, emit):  # nothing runs: the queue is never started
            raise AssertionError(f"a route ran {args}")

        return WebApp(self.cfg, JobQueue(runner, limit=20), allowed=frozenset({"localhost"}), csrf=CSRF,
                      searches_lacuerda=False, searches_youtube=False)

    def close(self) -> None:
        self.conn.close()


def _refusal(e) -> dict[str, Any]:
    return {"status": e.status, "title": e.title, "message": str(e)}


def asked(w: World, scene: str, case: str, url: str) -> dict[str, Any]:
    from caracole.web.pages import Refused
    from caracole.web.ug_link_routes import api_ug_link

    try:
        response = api_ug_link(w.app(), {"url": [url]}, now=NOW)
        out: dict[str, Any] = {"status": response.status, "body": json.loads(response.body)}
    except Refused as e:
        out = _refusal(e)
    return {"fn": "GET /api/ug/link", "scene": scene, "case": case, "url": url, "out": out}


def posted(w: World, scene: str, case: str, url: str) -> dict[str, Any]:
    from caracole.web.pages import Refused
    from caracole.web.ug_link_routes import read_ug_link

    app = w.app()
    try:
        response = read_ug_link(app, {"csrf": CSRF, "url": url}, json=True, now=NOW)
    except Refused as e:
        return {"fn": "POST /ug/link", "scene": scene, "case": case, "url": url, "out": _refusal(e)}
    [job] = app.queue.snapshot()
    return {"fn": "POST /ug/link", "scene": scene, "case": case, "url": url,
            "out": {"status": response.status, "body": json.loads(response.body),
                    "job": {"title": job.title, "key": job.song_key, "steps": [[s.label, list(s.args)] for s in job.steps],
                            "display": job.display, "stages": [[s.name, s.label] for s in job.stages]}}}


# --- the commands ----------------------------------------------------------------------------------------------------


def command_records(tmp: Path) -> list[dict[str, Any]]:
    n = iter(range(1, 1000))
    worlds: list[World] = []

    def world() -> World:
        worlds.append(World(tmp, f"command-{next(n)}"))
        return worlds[-1]

    out = []
    pages = song_dongye()
    out.append(world().run("a tab's page, then its artist's lists", FOUND, pages, progress=True))
    w = world()
    out.append(w.run("a tab's page, then its artist's lists, with no progress", FOUND, pages))
    out.append(w.run("the same link read again: nothing asked", f"{FOUND}?ref=share", pages))
    out.append(world().run("an artist's page: their lists alone", f"{SONG_DONGYE_URL}?filter=chords", pages,
                           progress=True))
    out.append(world().run("a page gone", f"{TAB}999", {f"{TAB}999": status(404)}))
    out.append(world().run("an artist's page gone", "https://www.ultimate-guitar.com/artist/1", {
        "https://www.ultimate-guitar.com/artist/1?filter=chords": status(404),
        "https://www.ultimate-guitar.com/artist/1": status(404)}))
    out.append(world().run("a slug of a type caracole keeps nothing of: nothing asked",
                           f"{TAB}metallica/one-guitar-pro-225441", {}))
    out.append(world().run("a Guitar Pro tab's page: read, its artist's page never", f"{TAB}7001",
                           {f"{TAB}7001": ok(PRO)}))
    alone = song_dongye_tab(7002, "新歌 New Song")
    del alone["artist_url"]
    out.append(world().run("a tab that links to no artist page", f"{TAB}7002",
                           {f"{TAB}7002": ok(make_tab_page_html(alone, [], content="[ch]C[/ch]"))}))
    out.append(world().run("a block", FOUND, {FOUND: status(403, "Forbidden")}))
    out.append(world().run("an error", FOUND, {FOUND: status(500, "oops")}))
    out.append(world().run("a block of the artist's page, the tab read", FOUND,
                           {**pages, SONG_DONGYE_CHORDS_URL: status(403, "Forbidden")}))
    out.append(world().run("an error on the artist's page, the tab read", FOUND,
                           {**pages, SONG_DONGYE_TABS_URL: status(500, "oops")}))
    out.append(world().run("the budget spent after the tab's page", FOUND, pages, budget=1))
    out.append(world().run("a page that won't parse", f"{TAB}5555",
                           {f"{TAB}5555": ok("<html><body>half a page</body></html>")}))
    w = world()
    w.conn.execute("INSERT INTO kv (key, value) VALUES ('provider:ug', ?)", (json.dumps(
        {"strikes": 1, "cooldown_until": "2026-11-18T14:00:00Z", "last_ok": None, "last_error": "403",
         "last_error_at": "2026-11-17T10:00:00Z"}),))
    out.append(w.run("cooling down after a block", FOUND, {}))
    w = world()
    w.conn.execute("INSERT INTO kv (key, value) VALUES ('ug:link-failed', ?)", (json.dumps(
        {FOUND: {"at": "2026-11-17T11:30:00Z", "error": "ug: 500: oops"}}),))
    out.append(w.run("a read that failed within the hour, run again by hand", FOUND, pages))
    for w in worlds:
        w.close()
    return out


@pytest.fixture(scope="module")
def commands(tmp_path_factory) -> list[dict[str, Any]]:
    return command_records(tmp_path_factory.mktemp("ug-link-commands"))


def test_commands_ug_link_jsonl(commands):
    check(COMMANDS_FILE, jsonl(commands, corpus="lookup/commands_ug_link", made_by=MADE_BY))


def test_the_commands_end_as_caracole_serve_reads_them(commands):
    from caracole.get import read_progress_line

    last = {r["case"]: [line for line in r["out"]["result"] if read_progress_line(line) is None][-1]
            for r in commands}
    assert {said.split(": ")[0] for said in last.values()} == {"Read", "Not found", "Not read"}
    assert last["a tab's page, then its artist's lists"] == (
        "Read: 斑马 斑马 Banma Banma Zebra Zebra by Song Dongye (宋冬野), chords; their page lists 8 tabs.")
    first = next(r for r in commands if r["case"] == "a tab's page, then its artist's lists")
    assert first["out"]["requests"] == [f"GET {FOUND}", f"GET {SONG_DONGYE_CHORDS_URL}", f"GET {SONG_DONGYE_TABS_URL}"]
    assert first["out"]["noted"] == {f"phone:read:ug:{SONG_DONGYE_URL}": STAMP}
    [again] = [r for r in commands if r["case"] == "the same link read again: nothing asked"]
    assert again["out"]["requests"] == [] and again["out"]["kv"] == {}


# --- the routes ------------------------------------------------------------------------------------------------------


def web_records(tmp: Path) -> list[dict[str, Any]]:
    from caracole.library import keep_file
    from caracole.versions import upsert_version

    out: list[dict[str, Any]] = [{"fn": "caracole.ug_urls.read_link", "args": [text],
                                  "out": None if read is None else dict(zip(("kind", "url", "tab_id", "type"), read))}
                                 for text, read in SHAPES]

    empty = World(tmp, "empty")
    out.append(empty.fixture("empty"))
    for case, url in (("a tab never read", "tabs.ultimate-guitar.com/tab/4180894?ref=share"),
                      ("an artist's page never read", f"{SONG_DONGYE_URL}?filter=chords"),
                      ("a slug of a type caracole keeps nothing of", f"{TAB}metallica/one-guitar-pro-225441"),
                      ("a slug that names a kind caracole keeps", f"{TAB}radiohead/creep-chords-4169"),
                      ("no UG link", "https://www.ultimate-guitar.com/explore"),
                      ("a link too long", FOUND + "?x=" + "x" * 600)):
        out.append(asked(empty, "empty", case, url))
    for case, url in (("a tab never read", FOUND), ("an artist's page never read", SONG_DONGYE_URL),
                      ("a slug of a type caracole keeps nothing of", f"{TAB}metallica/one-guitar-pro-225441"),
                      ("no UG link", "banma")):
        out.append(posted(empty, "empty", case, url))
    empty.close()

    w = World(tmp, "read")
    w.run("", FOUND, song_dongye())
    w.run("", f"{TAB}999", {f"{TAB}999": status(404)})
    w.run("", f"{TAB}7001", {f"{TAB}7001": ok(PRO)})
    dong = w.song("宋冬野", "董小姐")
    version = upsert_version(w.conn, provider="ug", tab_id="3016223", song_id=dong.id, slot="sheet", kind="chords",
                             rating=4.7, votes=90, version=1, label=None, url=f"{TAB}3016223", raw={}, now=ADDED)
    keep_file(w.conn, w.cfg.library_dir, song=dong, version_id=version, name="sheet.txt", data=b"[ch]C[/ch]\n",
              rank=1)
    w.overrides(f'[pin]\n"宋冬野 - 董小姐" = ["{TAB}3204647"]\n')
    w.conn.execute("INSERT INTO ug_index (tab_id, artist_key, song_key, type, sitemap, first_seen, path) VALUES "
                   "(85053, 'soda-stereo', 'de-musica-ligera', 'chords', 'last', ?, "
                   "'soda-stereo/de-musica-ligera-chords-85053')", (ADDED,))
    out.append(w.fixture("read"))
    for case, url in (("a tab read: its names, its artist's page, its song's hit", FOUND),
                      ("its other version, which its artist's page names", f"{TAB}4689017"),
                      ("their artist's page read: their songs", SONG_DONGYE_URL),
                      ("a song of the library's sheet", f"{TAB}3016223"),
                      ("a song of the library's pick", f"{TAB}3204647"),
                      ("a page gone", f"{TAB}999"),
                      ("a Guitar Pro tab's page read", f"{TAB}7001"),
                      ("a slugged tab of the index", f"{TAB}soda-stereo/de-musica-ligera-chords-85053"),
                      ("the bare page of a slugged tab of the index", f"{TAB}85053")):
        out.append(asked(w, "read", case, url))
    for case, url in (("a tab read", FOUND), ("a page gone", f"{TAB}999"), ("a Guitar Pro tab", f"{TAB}7001")):
        out.append(posted(w, "read", case, url))
    w.close()

    w = World(tmp, "cooling")
    w.conn.execute("INSERT INTO kv (key, value) VALUES ('provider:ug', ?)", (json.dumps(
        {"strikes": 1, "cooldown_until": "2026-11-18T14:00:00Z", "last_ok": None, "last_error": "403",
         "last_error_at": "2026-11-17T10:00:00Z"}),))
    out.append(w.fixture("cooling"))
    out.append(asked(w, "cooling", "UG cooling down", FOUND))
    out.append(posted(w, "cooling", "UG cooling down", FOUND))
    w.close()

    w = World(tmp, "spent")
    w.conn.executemany("INSERT INTO events (run, at, provider, url, status, decision) VALUES (?, ?, 'ug', ?, 200, 'ok')",
                       [(f"lookup:2026-11-17T11:{n:02d}:00Z", f"2026-11-17T11:{n:02d}:00Z", f"{TAB}{n}")
                        for n in range(60)])
    out.append(w.fixture("spent"))
    out.append(asked(w, "spent", "the hour's lookups spent", FOUND))
    out.append(posted(w, "spent", "the hour's lookups spent", FOUND))
    w.close()

    w = World(tmp, "failed")
    w.conn.execute("INSERT INTO kv (key, value) VALUES ('ug:link-failed', ?)", (json.dumps(
        {FOUND: {"at": "2026-11-17T11:30:00Z", "error": "ug: 500: oops"},
         f"{TAB}1": {"at": "2026-11-17T10:30:00Z", "error": "an hour and a half ago"}}),))
    w.conn.execute("INSERT INTO kv (key, value) VALUES ('ug:unreadable:5555', ?)", (json.dumps(
        {"until": "2026-11-24T12:00:00Z", "strikes": 1, "error": "ug: no js-store"}),))
    out.append(w.fixture("failed"))
    for case, url in (("a read that failed within the hour", FOUND), ("one that failed before it", f"{TAB}1"),
                      ("a tab page that won't parse until it is due", f"{TAB}5555")):
        out.append(asked(w, "failed", case, url))
    out.append(posted(w, "failed", "a read that failed within the hour", FOUND))
    w.close()
    return out


@pytest.fixture(scope="module")
def web(tmp_path_factory) -> list[dict[str, Any]]:
    return web_records(tmp_path_factory.mktemp("ug-link-web"))


def test_ug_link_jsonl(web):
    check(WEB_FILE, jsonl(web, corpus="web/ug_link", made_by=MADE_BY))


def test_the_routes_cover_every_state_both_kinds_and_the_refusals(web):
    answers = [r["out"] for r in web if r["fn"] == "GET /api/ug/link"]
    from caracole.ug.link import STATES

    assert {a["body"]["state"] for a in answers if "body" in a} == set(STATES)
    assert {a["body"]["kind"] for a in answers if "body" in a} == {"tab", "artist"}
    assert {r["out"]["status"] for r in web if r["fn"] in ("GET /api/ug/link", "POST /ug/link")} == {
        200, 202, 400, 409, 429}
    [found] = [r["out"]["body"] for r in web if r["fn"] == "GET /api/ug/link" and r["scene"] == "read"
               and r["url"] == FOUND]
    assert found["guess"] == {"artist": "宋冬野", "title": "斑马斑马"} and found["hits"][0]["title"] == "斑马斑马"
    # The read scene carries its library's files: the song's sheet link and its hits' links read them.
    [scene] = [r for r in web if r["fn"] == "fixture" and r["scene"] == "read"]
    assert [rec["file"] for rec in scene["records"] if "file" in rec] == ["宋冬野/董小姐/sheet.txt"]
    [sheet] = [r["out"]["body"]["song"] for r in web if r["fn"] == "GET /api/ug/link" and r["url"] == f"{TAB}3016223"]
    assert sheet["has_sheet"] is True and sheet["sheet"] and sheet["this_tab"] is True
