"""Whole lookups, for the phone's lane lookup-scenarios (core.lookup's ``Lookup.run`` over every site stage) to replay:
``caracole get`` and the ``caracole versions`` commands that are lookups, each recorded from a caracole over a fixture
library, a cache and fake sites (tests/helpers/scenario.py ``record_lookup``, the corpus spec's "Scenario records").

**The world.** Each record its own caracole: a database with the phone's tables (``phone_schema``), a library folder,
an offline Ultimate Guitar index (complete, ``ug:index:built_at``) of "Calla Lake - River Road" (its chords 101 and
102, its text tab 201, at their slugged pages) and a few other songs, and the songs the case puts in it; its
``caracole.toml`` the defaults with ``kw.providers``' fields over each provider's (config.py's names:
``enabled``, ``lookup_requests``, ``lookup_per_hour``). overrides.toml and wanted.txt live beside the library, never in
it: the phone keeps neither, its overrides being the rows of ``phone_overrides`` (``test_conformance_overrides
.rows_of``), written into the database before and after each case from the file overrides.py's writers wrote. The
fake sites (``Sites``) answer by address: UG's tab and artist pages (tests/helpers/ug_pages.py), LRCLIB's
``/api/get`` and ``/api/search``, Megalobiz's search, AZLyrics' and LaCuerda's pages (tests/fixtures/, by
reference); an address none of them answers fails the generator.

**What runs.** get.py's ``look_up`` (``caracole get``), or versions_cmd.py's ``choose`` and ``clear`` (``caracole
versions --choose`` and ``--clear``, each ``caracole get`` in the end), at ``now``, with chordpro absent and the
library page, the PDFs and the songbooks stood still (``record_lookup``), as the phone of milestone 4 makes none.

**The phone's words.** Four stages are worded by what a caracole makes, and the phone of milestone 4 makes no
wanted.txt line, no PDF, no index.html and no songbook: the record carries the stage stream as the phone says it,
get.py's own words for a caracole with no ChordPro (``get.ADDED``, ``NO_PDFS``, ``LIBRARY_PAGE``) and, while its
songbooks are ``SongbookPages.NONE``, ``SONGBOOKS``, in place of Python's:

- ``song``: "added to wanted.txt, line N" is ``get.ADDED`` (the picks recorded after it as they are);
- ``pdf``: a pass that made the PDF or found it up to date is ``["skipped", get.NO_PDFS]`` (no sheet yet is no sheet
  yet on both);
- ``pages``: "_todo.md and index.html rewritten" is ``get.LIBRARY_PAGE``;
- ``songbooks``: "no songbook lists it" (no songbooks.toml) is ``["skipped", SONGBOOKS]``.

``out.result.python`` keeps what Python said of each stage so rewritten (``{stage: [state, detail]}``).

**Vectors** (``vectors/lookup/``), a header, then a record a line:

- ``get.jsonl``: ``{fn: "caracole.get.look_up", case, fixture, kw: {request, providers}, now, cache, answers,
  leaves_out, out: {result: {result, progress, python}, requests, rows, kv, library, events, pauses}}``:
  ``kw.request`` every field of ``get.LookupRequest`` by Python's names; ``out.result.result`` what the lookup came to
  (``LookupResult``'s ``song_id``, ``display``, ``states``, ``details``, ``files``, ``seconds_to_sheet``, ``seconds``,
  ``requests``, ``bug``, ``refused``), ``progress`` what it told as it went, in order (``["stage", name, state,
  detail]``, ``["song", id, display]``, ``["readable", files]``). The cases: a new song found and its sheet kept, a
  tab picked, a LaCuerda sheet picked, a block on Ultimate Guitar that cools it while the other sites are asked, an
  hour's lookups spent, the half kept for sheets, two refusals (an ignored song, a tab of a kind caracole doesn't
  use), the lyrics put together from LRCLIB's miss, Megalobiz's and AZLyrics' answers, a song through its artist's
  page, and an error that ends a site's part.
- ``commands_get.jsonl``: ``{fn: "caracole.versions_cmd.choose" | "caracole.versions_cmd.clear", case, fixture, kw:
  {display, tab, providers}, …, out: {result: {result, progress, python, said, address}, …}}``: the same, of a song
  a lookup filled before (its fixture), ``said`` the command's own line (``--clear``'s) and get's totals line
  (commands/get.py ``_totals``), ``address`` the tab address ``--choose`` looked the song up with (null for
  ``--clear``).

Stamps: songs.py's and match.py's clocks are the record's ``now`` while a world is made and a case runs.
library.keep_file stamps ``created_at`` with SQLite's clock, which no record can fix: every ``files`` row is given the
record's ``now`` before what a case did is read, the time the phone's ``Kept.keepFile`` is given.

Regenerate with ``CARACOLE_CORPUS=write nix develop -c pytest -q -n 0 tests/test_conformance_lookup_scenarios.py``.
"""

from __future__ import annotations

import contextlib
import dataclasses
import io
import json
import re
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from unittest import mock
from urllib.parse import urlsplit

import pytest

from helpers.corpus import VECTORS, check, fixture_ref, jsonl, phone_schema
from helpers.scenario import record_lookup
from helpers.ug_pages import make_artist_page_html, make_tab_page_html, version_dict

MADE_BY = "tests/test_conformance_lookup_scenarios.py"
LOOKUP = VECTORS / "lookup"
GET = LOOKUP / "get.jsonl"
COMMANDS = LOOKUP / "commands_get.jsonl"

NOW = datetime(2026, 11, 3, 12, 0, tzinfo=UTC)
STAMP = "2026-11-03T12:00:00Z"
ADDED = "2026-10-01T00:00:00Z"
EARLIER = "2026-11-03T11:40:00Z"  # within the hour before NOW: the hour's lookups
BEFORE = datetime(2026, 11, 3, 11, 30, tzinfo=UTC)  # a lookup before a case's, within its hour
HTML = [["content-type", "text/html; charset=utf-8"]]
JSON = [["content-type", "application/json"]]

# While the phone's songbooks are SongbookPages.NONE, its songbooks stage says so (core.lookup.sites.NotYet.WORDS).
SONGBOOKS = "not on the phone yet"

TAB = "https://tabs.ultimate-guitar.com/tab/"
WWW = "https://www.ultimate-guitar.com"
LRCLIB = "https://lrclib.net/api/"
MEGALOBIZ = "https://api.megalobiz.com/api/public/v1/"
AZLYRICS = "https://www.azlyrics.com/"
LACUERDA = "https://acordes.lacuerda.net/"

ARTIST, TITLE = "Calla Lake", "River Road"
ARTIST_KEY, SONG_KEY = "calla-lake", "river-road"
DISPLAY = f"{ARTIST} - {TITLE}"
LAKE_URL = f"{WWW}/artist/calla_lake_5150"

LINES = [
    "walking down the river road tonight",
    "counting every lantern on the shore",
    "the wind is singing softly in the pines",
    "and nobody remembers what we were",
    "hold the silver morning in your hands",
    "every window glowing like a promise",
]
PLAIN = "\n".join(LINES[:3]) + "\n\n" + "\n".join(LINES[3:])
SYNCED = "\n".join(f"[00:{10 + 5 * i:02d}.00] {line}" for i, line in enumerate(LINES))


def ok(body: Any, headers: list[list[str]] | None = None) -> dict[str, Any]:
    return {"status": 200, "headers": HTML if headers is None else headers, "body": body}


def status(code: int, body: str = "") -> dict[str, Any]:
    return {"status": code, "headers": HTML, "body": body}


# --- Ultimate Guitar's pages of the world ---------------------------------------------------------------------


def slugged(tab_id: int, kind: str = "chords", song: str = SONG_KEY, artist: str = ARTIST_KEY) -> str:
    return f"{TAB}{artist}/{song}-{kind}-{tab_id}"


def sheet_markup(tag: str, lines: list[str]) -> str:
    rows = ["[Intro]", tag, ""]
    for line in lines:
        rows += ["[tab][ch]Am[/ch]       [ch]F[/ch]       [ch]C[/ch]", f"{line}[/tab]"]
    return "\r\n".join(rows)


def tab_markup(tag: str) -> str:
    return "\r\n".join(["[Riff]", tag, "[tab]e|-----0-----|", "B|---1---1---|[/tab]"])


UG_TYPES = {"chords": "Chords", "tabs": "Tabs", "pro": "Pro"}


@dataclasses.dataclass(frozen=True)
class Version:
    """One version of a song as UG lists it, and its page's text."""

    tab_id: int
    kind: str
    rating: float
    votes: int
    number: int
    content: str | None
    url: str
    song: str = TITLE
    artist: str = ARTIST

    def listed(self) -> dict[str, Any]:
        return version_dict(self.tab_id, type=UG_TYPES[self.kind], version=self.number, rating=self.rating,
                            votes=self.votes, song=self.song, artist=self.artist, song_id=4242, tab_url=self.url)


RIVER = {v.tab_id: v for v in [
    Version(101, "chords", 4.8, 120, 1, sheet_markup("version 101", LINES), slugged(101)),
    Version(102, "chords", 4.1, 12, 2, sheet_markup("version 102", LINES[:3]), slugged(102)),
    Version(201, "tabs", 4.6, 40, 1, tab_markup("tab 201"), slugged(201, "tabs")),
]}
# The offline index: (tab id, artist key, song key, type, path). River Road's three tabs, and other artists' songs so
# that a song the index lacks is not found in a complete index.
INDEX = [
    (101, ARTIST_KEY, SONG_KEY, "chords", f"{ARTIST_KEY}/{SONG_KEY}-chords-101"),
    (102, ARTIST_KEY, SONG_KEY, "chords", f"{ARTIST_KEY}/{SONG_KEY}-chords-102"),
    (201, ARTIST_KEY, SONG_KEY, "tabs", f"{ARTIST_KEY}/{SONG_KEY}-tabs-201"),
    (301, "harbour-lights", "paper-boats", "chords", "harbour-lights/paper-boats-chords-301"),
    (302, "harbour-lights", "silver-morning", "chords", "harbour-lights/silver-morning-chords-302"),
]


def tab_page(versions: dict[int, Version], tab_id: int) -> str:
    """The page of ``tab_id``: its own tab and the other versions of its type."""
    own = versions[tab_id]
    others = [v.listed() for v in versions.values() if v.kind == own.kind and v.tab_id != tab_id]
    return make_tab_page_html(own.listed(), others, content=own.content, artist_url=LAKE_URL)


# --- the fake sites -------------------------------------------------------------------------------------------


def lrclib_record(artist: str, title: str, duration: float, *, synced: bool = True) -> str:
    return json.dumps({"id": 7700, "name": title, "trackName": title, "artistName": artist, "albumName": None,
                       "duration": duration, "instrumental": False, "plainLyrics": PLAIN,
                       "syncedLyrics": SYNCED if synced else None}, ensure_ascii=False)


@dataclasses.dataclass
class Sites:
    """What each fake site answers, by address (None: it answers nothing there, and the generator fails)."""

    ug: dict[str, dict[str, Any]] = dataclasses.field(default_factory=dict)
    lrclib_get: dict[str, Any] | None = None  # /api/get's answer for any song
    lrclib_search: dict[str, Any] | None = None
    megalobiz_search: dict[str, Any] | None = None
    pages: dict[str, dict[str, Any]] = dataclasses.field(default_factory=dict)  # AZLyrics', LaCuerda's, any other

    def __call__(self, said: str) -> dict[str, Any] | None:
        method, url = said.split(" ", 1)
        if method != "GET":
            return None
        if url in self.ug:
            return self.ug[url]
        if url in self.pages:
            return self.pages[url]
        path = urlsplit(url)._replace(query="").geturl()
        if path == LRCLIB + "get":
            return self.lrclib_get
        if path == LRCLIB + "search":
            return self.lrclib_search
        if path == MEGALOBIZ + "search":
            return self.megalobiz_search
        return None


def river_sites(**kw: Any) -> Sites:
    """River Road's pages on UG and its lyrics on LRCLIB."""
    sites = Sites(ug={v.url: ok(tab_page(RIVER, t)) for t, v in RIVER.items()},
                  lrclib_get=ok(lrclib_record(ARTIST, TITLE, 213.0), JSON))
    return dataclasses.replace(sites, **kw)


# --- the world ------------------------------------------------------------------------------------------------


@contextmanager
def clock(stamp: str) -> Iterator[None]:
    with mock.patch("caracole.songs.utc_now_iso", lambda: stamp), \
            mock.patch("caracole.match.utc_now_iso", lambda: stamp):
        yield


def _request(request) -> dict[str, Any]:
    return dataclasses.asdict(request)


def _result(result) -> dict[str, Any]:
    return {"song_id": result.song_id, "display": result.display, "states": dict(result.states),
            "details": dict(result.details), "files": dict(result.files), "seconds_to_sheet": result.seconds_to_sheet,
            "seconds": result.seconds, "requests": dict(result.requests), "bug": result.bug,
            "refused": result.refused}


class Heard:
    """A lookup's progress, as the phone's Progress hears it."""

    def __init__(self) -> None:
        self.events: list[list[Any]] = []

    def stage(self, name: str, state: str, detail: str = "") -> None:
        self.events.append(["stage", name, state, detail])

    def readable(self, files, seconds: float) -> None:
        self.events.append(["readable", dict(files)])

    def song(self, song_id: int, display: str) -> None:
        self.events.append(["song", song_id, display])


_ADDED_LINE = re.compile(r"added to wanted\.txt, line \d+")


def phone_end(name: str, state: str, detail: str) -> tuple[str, str] | None:
    """The phone's end of a stage Python ended so (the module's docstring), or None when it says the same."""
    from caracole import get

    if name == "song" and state == "done" and _ADDED_LINE.match(detail):
        return state, get.ADDED + detail[_ADDED_LINE.match(detail).end():]
    if name == "pdf" and state == "done" and detail in ("made", "up to date"):
        return "skipped", get.NO_PDFS
    if name == "pages" and (state, detail) == ("done", "_todo.md and index.html rewritten"):
        return "done", get.LIBRARY_PAGE
    if name == "songbooks" and (state, detail) == ("skipped", "no songbook lists it"):
        return "skipped", SONGBOOKS
    assert name not in ("pdf", "pages", "songbooks") or state == "running" or (name, detail) in (
        ("pdf", "no sheet yet"), ("pdf", ""), ("pages", ""), ("songbooks", "")), (name, state, detail)
    return None


def in_phone_words(said: dict[str, Any]) -> dict[str, Any]:
    """A lookup's result and progress, the four stages worded as the phone words them (``phone_end``)."""
    result, progress = said["result"], said["progress"]
    python: dict[str, list[str]] = {}
    for name in list(result["details"]):
        end = phone_end(name, result["states"][name], result["details"][name])
        if end is not None:
            python[name] = [result["states"][name], result["details"][name]]
            result["states"][name], result["details"][name] = end
    for event in progress:
        if event[0] == "stage" and event[2] != "running":
            end = phone_end(event[1], event[2], event[3])
            if end is not None:
                event[2], event[3] = end
    return {**said, "python": python}


def current_keys(conn) -> None:
    """Every index keyed as this caracole keys it (the nightly run's doing), so that a lookup keys none again."""
    from caracole import gametabs_index, harptabs_fetch, harptabs_index, lacuerda_index
    from caracole.ug import artist_tabs

    for index in (harptabs_fetch, harptabs_index, gametabs_index, lacuerda_index, artist_tabs):
        index.ensure_current_keys(conn)


class World:
    """One caracole: its config, database, library, offline index and overrides (the module's docstring)."""

    def __init__(self, tmp: Path, name: str, *, providers: dict[str, dict[str, Any]] | None = None,
                 index: list[tuple[int, str, str, str, str]] = INDEX):
        from caracole import db
        from caracole.config import load_config
        from caracole.songs import ensure_current_keys
        from caracole.ug.index import BUILT_KEY

        self.dir = tmp / name
        self.dir.mkdir(parents=True)
        base = load_config(None, env={"HOME": str(self.dir / "home"), "STATE_DIRECTORY": str(self.dir / "state"),
                                      "CACHE_DIRECTORY": str(self.dir / "cache")})
        self.providers = providers or {}
        configured = dict(base.providers)
        for provider, fields in self.providers.items():
            configured[provider] = dataclasses.replace(configured[provider], **fields)
        self.cfg = dataclasses.replace(base, overrides_file=self.dir / "overrides.toml",
                                       wanted_file=self.dir / "wanted.txt", providers=configured)
        self.cfg.library_dir.mkdir(parents=True)
        self.conn = db.connect(self.cfg.db_path)
        phone_schema(self.conn)
        with clock(ADDED):
            ensure_current_keys(self.conn)
        for tab_id, artist_key, song_key, kind, path in index:
            self.conn.execute(
                "INSERT INTO ug_index (tab_id, artist_key, song_key, type, sitemap, first_seen, path) "
                "VALUES (?, ?, ?, ?, 'last', ?, ?)", (tab_id, artist_key, song_key, kind, ADDED, path))
        db.kv_set(self.conn, BUILT_KEY, ADDED)
        current_keys(self.conn)

    def song(self, artist: str = ARTIST, title: str = TITLE, *, duration_ms: int | None = 213000,
             **fields: Any) -> int:
        """A song of the library, as wanted.txt's sync adds one, with ``fields`` of its record."""
        from caracole.normalize import identity_key
        from caracole.songs import update_song, upsert_song

        with clock(ADDED):
            song_id, _ = upsert_song(self.conn, artists=[artist], title=title, album=None, duration_ms=duration_ms,
                                     isrc=None, source="wanted", source_id=identity_key(artist, title),
                                     added_at=ADDED)
            if fields:
                update_song(self.conn, song_id, **fields)
        return song_id

    def overrides(self, edit: Callable[[Path], None]) -> None:
        """overrides.toml written with overrides.py's writers (``edit(path)``); the phone's rows of it follow."""
        edit(self.cfg.overrides_file)
        self.phone_overrides(self.conn)

    def phone_overrides(self, conn) -> None:
        from test_conformance_overrides import rows_of

        conn.execute("DELETE FROM phone_overrides")
        if self.cfg.overrides_file.is_file():
            for row in rows_of(self.cfg.overrides_file):
                conn.execute("INSERT INTO phone_overrides (tbl, key, written, value) VALUES (?, ?, ?, ?)",
                             (row["tbl"], row["key"], row["written"], row["value"]))

    def lookups(self, provider: str, n: int, at: str = EARLIER) -> None:
        """``n`` requests to ``provider`` by an earlier lookup of the hour."""
        for i in range(n):
            self.conn.execute(
                "INSERT INTO events (run, at, provider, url, status, decision, message) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (f"lookup:{at}", at, provider, f"https://example.invalid/{provider}/{i}", 200, "ok", None))

    def settled(self, now: datetime) -> Callable[[Any], None]:
        """Before what a case at ``now`` did is read: the phone's rows of overrides.toml, and each file kept then at
        ``now``, as the phone's ``Kept.keepFile`` is given the lookup's time."""
        stamp = now.strftime("%Y-%m-%dT%H:%M:%SZ")
        before = dict(self.conn.execute("SELECT id, created_at FROM files").fetchall())

        def settle(conn) -> None:
            self.phone_overrides(conn)
            for file_id, created in conn.execute("SELECT id, created_at FROM files").fetchall():
                if before.get(file_id) != created:  # SQLite's clock, now
                    assert abs((datetime.now(UTC) - datetime.strptime(created, "%Y-%m-%dT%H:%M:%SZ").replace(
                        tzinfo=UTC)).total_seconds()) < 300, created
                    conn.execute("UPDATE files SET created_at = ? WHERE id = ?", (stamp, file_id))

        return settle

    def record(self, case: str, request, sites: Sites, *, cache: dict[str, Any] | None = None,
               now: datetime = NOW) -> dict[str, Any]:
        """``caracole get`` of ``request`` at ``now``, recorded."""
        from caracole import get

        heard = Heard()

        def call() -> dict[str, Any]:
            result = get.look_up(self.cfg, request, heard, now=now, clock=lambda: 0.0)
            return {"result": _result(result), "progress": heard.events}

        made = record_lookup(self.cfg, fn="caracole.get.look_up", call=call, answers=sites, now=now, case=case,
                             kw={"request": _request(request), "providers": self.providers}, cache=cache,
                             settle=self.settled(now))
        made["out"]["result"] = in_phone_words(made["out"]["result"])
        return made

    def command(self, fn: str, case: str, run: Callable[[], None], sites: Sites, kw: dict[str, Any], *,
                cache: dict[str, Any] | None = None) -> dict[str, Any]:
        """A ``caracole versions`` command that looks the song up (``run``), recorded: the lookup it made, its own
        line and get's totals."""
        from caracole import get
        from caracole.commands import get as get_cmd

        heard = Heard()
        looked: list[Any] = []
        real_look_up, real_lines = get.look_up, get_cmd._Lines

        def look_up(cfg, request, progress=None, **k):
            looked.append(request)
            result = real_look_up(cfg, request, progress, now=NOW, clock=lambda: 0.0)
            looked.append(result)
            return result

        class Lines(real_lines):
            def stage(self, name, state, detail=""):
                heard.stage(name, state, detail)
                super().stage(name, state, detail)

            def readable(self, files, seconds):
                heard.readable(files, seconds)
                super().readable(files, seconds)

            def song(self, song_id, display):
                heard.song(song_id, display)
                sup = getattr(super(), "song", None)
                if sup is not None:
                    sup(song_id, display)

        def call() -> dict[str, Any]:
            out = io.StringIO()
            with mock.patch("caracole.get.look_up", look_up), mock.patch("caracole.commands.get._Lines", Lines), \
                    contextlib.redirect_stdout(out):
                run()
            lines = out.getvalue().splitlines()
            request, result = looked
            own = [line for line in lines if line.startswith(("Took ", "No [pin] "))]
            return {"result": _result(result), "progress": heard.events, "said": own + [get_cmd._totals(result)],
                    "address": request.tab}

        made = record_lookup(self.cfg, fn=fn, call=call, answers=sites, now=NOW, case=case,
                             kw={**kw, "providers": self.providers}, cache=cache, settle=self.settled(NOW))
        made["out"]["result"] = in_phone_words(made["out"]["result"])
        return made

    def look_up(self, request, sites: Sites, *, keeps_cache: bool = False) -> None:
        """A lookup at ``BEFORE``, not recorded: the library it leaves is the case's fixture, and its HTTP cache too
        when it ``keeps_cache`` (``cached``), else none."""
        import shutil

        self.record("before", request, sites, now=BEFORE)
        if not keeps_cache:
            shutil.rmtree(self.cfg.cache_dir / "http", ignore_errors=True)

    def cached(self) -> dict[str, dict[str, Any]]:
        """The HTTP cache as a record carries it (scenario.py's ``cache``), read from the files http.py wrote; each
        body a text."""
        import gzip

        out: dict[str, dict[str, Any]] = {}
        root = self.cfg.cache_dir / "http"
        for meta_file in sorted(root.glob("*/*/*.json")):
            provider = meta_file.parent.parent.name
            meta = json.loads(meta_file.read_text("utf-8"))
            body = gzip.decompress(meta_file.with_suffix(".body").read_bytes()).decode("utf-8")
            out.setdefault(provider, {})[f"GET {meta['url']}"] = {
                "status": meta["status"], "fetched_at": meta["fetched_at"], "headers": meta["headers"],
                "body": {"text": body}}
        return out

    def close(self) -> None:
        self.conn.close()


def _request_of(**kw: Any):
    from caracole.get import LookupRequest

    return LookupRequest(**{"artist": ARTIST, "title": TITLE, **kw})


# --- caracole get's cases -------------------------------------------------------------------------------------


def new_song(tmp: Path) -> dict[str, Any]:
    w = World(tmp, "new-song")
    try:
        return w.record("a new song found and its sheet kept: added, matched, UG's sheet, LRCLIB's lyrics, the "
                        "versions scored and the text tab, a good run of each site",
                        _request_of(duration_ms=213000), river_sites())
    finally:
        w.close()


def picked_tab(tmp: Path) -> dict[str, Any]:
    w = World(tmp, "picked-tab")
    try:
        w.song()
        return w.record("a tab picked: pinned in overrides.toml, its page the sheet",
                        _request_of(tab=RIVER[102].url), river_sites())
    finally:
        w.close()


def picked_lacuerda(tmp: Path) -> dict[str, Any]:
    w = World(tmp, "picked-lacuerda")
    try:
        w.song("Soda Stereo", "De Música Ligera")
        sites = Sites(lrclib_get=ok(lrclib_record("Soda Stereo", "De Música Ligera", 213.0), JSON),
                      pages={DML_3: ok(fixture_ref("lacuerda/version.html")),
                             f"{LACUERDA}soda_stereo/": ok(fixture_ref("lacuerda/artist.html"))})
        return w.record("a LaCuerda sheet picked: recorded under [lacuerda], its version the sheet, asked once",
                        _request_of(artist="Soda Stereo", title="De Música Ligera", lacuerda=DML_3), sites)
    finally:
        w.close()


def blocked(tmp: Path) -> dict[str, Any]:
    w = World(tmp, "blocked")
    try:
        w.song(match_decision="accept", match_step="exact", match_score=100.0, match_artist_key=ARTIST_KEY,
               match_song_key=SONG_KEY, matched_at=ADDED, ug_dirty=False, ug_checked_at=ADDED)
        sites = river_sites()
        sites.ug[RIVER[101].url] = status(403, "<html><body>Access denied</body></html>")
        return w.record("a block on Ultimate Guitar: it cools down, the song is owed a fetch, the other sites are "
                        "asked and have a good run", _request_of(), sites)
    finally:
        w.close()


def failed(tmp: Path) -> dict[str, Any]:
    w = World(tmp, "failed")
    try:
        w.song()
        sites = river_sites()
        sites.ug[RIVER[101].url] = status(500, "<html><body>Server error</body></html>")
        return w.record("an error on Ultimate Guitar: counted, the sheet stage failed, the ug stage skips it",
                        _request_of(), sites)
    finally:
        w.close()


def spent_hour(tmp: Path) -> dict[str, Any]:
    w = World(tmp, "spent-hour", providers={"ug": {"lookup_per_hour": 4}})
    try:
        w.song()
        w.lookups("ug", 4)
        return w.record("this hour's lookups spent on Ultimate Guitar: nothing asked of it, LRCLIB still asked",
                        _request_of(), river_sites())
    finally:
        w.close()


def kept_for_sheets(tmp: Path) -> dict[str, Any]:
    w = World(tmp, "kept-for-sheets", providers={"ug": {"lookup_per_hour": 8}})
    try:
        w.song()
        w.lookups("ug", 2)
        return w.record("what follows the sheet held to the half of the hour's lookups not kept for sheets: one "
                        "request more, then spent", _request_of(), river_sites())
    finally:
        w.close()


def ignored(tmp: Path) -> dict[str, Any]:
    from caracole.overrides import add_ignore

    w = World(tmp, "ignored")
    try:
        w.song()
        w.overrides(lambda path: add_ignore(path, DISPLAY))
        return w.record("an ignored song refused: the song stage failed, the rest skipped, nothing asked",
                        _request_of(), Sites())
    finally:
        w.close()


def unused_kind(tmp: Path) -> dict[str, Any]:
    w = World(tmp, "unused-kind")
    try:
        return w.record("a tab of a kind caracole doesn't use refused before anything is written",
                        _request_of(tab=f"{TAB}{ARTIST_KEY}/{SONG_KEY}-guitar-pro-401"), Sites())
    finally:
        w.close()


def lyrics_then(tmp: Path) -> dict[str, Any]:
    w = World(tmp, "lyrics-then")
    try:
        sites = Sites(lrclib_get=status(404, '{"code":404,"name":"TrackNotFound","message":"Failed to find '
                                             'specified track"}'),
                      lrclib_search=ok(fixture_ref("lrclib/search_empty.json"), JSON),
                      megalobiz_search=ok(fixture_ref("megalobiz/search_empty.json"), JSON),
                      pages={f"{AZLYRICS}p/pomme.html": ok(fixture_ref("azlyrics/artist_pomme.html")),
                             f"{AZLYRICS}lyrics/pomme/mononoke.html": ok(fixture_ref("azlyrics/lyrics_mononoke.html"))})
        return w.record("lyrics put together: LRCLIB has none, Megalobiz no timed ones, AZLyrics' plain lyrics; the "
                        "offline index doesn't know the song", _request_of(artist="Pomme", title="mononoke",
                                                                          duration_ms=None), sites)
    finally:
        w.close()


LANTERN = {v.tab_id: v for v in [
    Version(401, "chords", 4.7, 30, 1, sheet_markup("version 401", LINES), f"{TAB}401", song="Paper Lantern"),
    Version(402, "tabs", 4.4, 9, 1, tab_markup("tab 402"), f"{TAB}402", song="Paper Lantern"),
]}


def artist_page(tmp: Path) -> dict[str, Any]:
    w = World(tmp, "artist-page")
    try:
        w.song("Calla Lake", "Paper Lantern", duration_ms=198000)
        w.conn.execute("INSERT INTO kv (key, value) VALUES (?, ?)", (f"ug:artist_url:{ARTIST_KEY}", LAKE_URL))
        listed = [v.listed() for v in LANTERN.values()] + [v.listed() for v in RIVER.values()]

        def page(kind: str | None) -> dict[str, Any]:
            tabs = [t for t in listed if kind is None or t["type"] == UG_TYPES[kind]]
            return ok(make_artist_page_html(5150, ARTIST, tabs, types=["Chords", "Tabs"]))

        sites = river_sites(lrclib_get=ok(lrclib_record(ARTIST, "Paper Lantern", 198.0), JSON))
        sites.ug |= {LAKE_URL: page(None), f"{LAKE_URL}?filter=chords": page("chords"),
                     f"{LAKE_URL}?filter=tabs": page("tabs")}
        sites.ug |= {v.url: ok(tab_page(LANTERN, t)) for t, v in LANTERN.items()}
        return w.record("a song the offline index lacks, through its artist's page on Ultimate Guitar: a bare-id "
                        "sheet", _request_of(title="Paper Lantern", duration_ms=198000), sites)
    finally:
        w.close()


DML_3 = f"{LACUERDA}soda_stereo/de_musica_ligera-3.shtml"


def scenarios(tmp: Path) -> list[dict[str, Any]]:
    return [new_song(tmp), picked_tab(tmp), picked_lacuerda(tmp), blocked(tmp), failed(tmp), spent_hour(tmp),
            kept_for_sheets(tmp), ignored(tmp), unused_kind(tmp), lyrics_then(tmp), artist_page(tmp)]


# --- the versions commands' cases ----------------------------------------------------------------------------


def looked_up(tmp: Path, name: str, *, keeps_cache: bool = False) -> World:
    """River Road looked up once before: its sheet 101, 102 kept beside it, its tab 201."""
    w = World(tmp, name)
    w.song()
    w.look_up(_request_of(), river_sites(), keeps_cache=keeps_cache)
    return w


def choose(tmp: Path) -> dict[str, Any]:
    from caracole import versions_cmd

    w = looked_up(tmp, "choose", keeps_cache=True)
    try:
        return w.command("caracole.versions_cmd.choose", "--choose: get --tab at the version's own address, "
                         "pinned, the sheet it, every page from the cache the lookup before left",
                         lambda: versions_cmd.choose(w.cfg, DISPLAY, 102), river_sites(),
                         {"display": DISPLAY, "tab": 102}, cache=w.cached())
    finally:
        w.close()


def clear(tmp: Path) -> dict[str, Any]:
    from caracole import versions_cmd

    w = looked_up(tmp, "clear")
    try:
        w.look_up(_request_of(tab=RIVER[102].url), river_sites())  # its pin, by --choose's lookup
        return w.command("caracole.versions_cmd.clear", "--clear: the chords pin taken out of [pin], then get: "
                         "caracole's pick the sheet again", lambda: versions_cmd.clear(w.cfg, DISPLAY), river_sites(),
                         {"display": DISPLAY, "tab": None})
    finally:
        w.close()


def commands(tmp: Path) -> list[dict[str, Any]]:
    return [choose(tmp), clear(tmp)]


# --- the vectors ----------------------------------------------------------------------------------------------


def every_file(tmp: Path) -> dict[Path, str]:
    return {GET: jsonl(scenarios(tmp / "get"), corpus="lookup", made_by=MADE_BY),
            COMMANDS: jsonl(commands(tmp / "commands"), corpus="lookup", made_by=MADE_BY)}


@pytest.fixture(scope="module")
def made(tmp_path_factory) -> dict[Path, str]:
    return every_file(tmp_path_factory.mktemp("lookup-scenarios"))


@pytest.mark.parametrize("path", [GET, COMMANDS], ids=lambda p: p.name)
def test_the_vector_is_what_caracole_get_does(made, path):
    check(path, made[path])


def test_the_vectors_are_the_same_on_another_run(made, tmp_path):
    assert every_file(tmp_path) == made


def _records(text: str) -> list[dict[str, Any]]:
    return [r for r in map(json.loads, text.splitlines()) if not r.get("header")]


def _ends(record: dict[str, Any]) -> dict[str, tuple[str, str]]:
    result = record["out"]["result"]["result"]
    return {name: (result["states"][name], result["details"][name]) for name in result["details"]}


def test_the_stage_stream_is_the_phones_words(made):
    """No record says what only a caracole with wanted.txt, ChordPro, index.html and songbooks says."""
    for record in _records(made[GET]) + _records(made[COMMANDS]):
        said = json.dumps(record["out"]["result"]["progress"]) + json.dumps(record["out"]["result"]["result"])
        for words in ("wanted.txt", "_todo.md", "no songbook lists it", '"up to date"'):
            assert words not in said, (record["case"], words)


def test_the_cases_come_to_what_they_say(made):
    from caracole import get

    cases = {r["case"].split(":")[0]: r for r in _records(made[GET]) + _records(made[COMMANDS])}
    new = cases["a new song found and its sheet kept"]
    assert _ends(new)["song"] == ("done", get.ADDED) and _ends(new)["sheet"] == ("done", "tab 101 from Ultimate Guitar")
    assert {"provider:ug", "provider:lrclib", "lookup:songs"} <= set(new["out"]["kv"])
    picked = cases["a tab picked"]
    assert [r["tbl"] for r in picked["out"]["rows"]["phone_overrides"]] == ["pin"]
    lacuerda = cases["a LaCuerda sheet picked"]
    assert [r["tbl"] for r in lacuerda["out"]["rows"]["phone_overrides"]] == ["lacuerda"]
    assert _ends(lacuerda)["sheet"] == ("done", "sheet kept from LaCuerda")
    block = cases["a block on Ultimate Guitar"]
    assert json.loads(block["out"]["kv"]["provider:ug"])["cooldown_until"] is not None
    assert "provider:lrclib" in block["out"]["kv"] and block["out"]["rows"]["songs"][0]["ug_dirty"] == 1
    assert _ends(cases["an error on Ultimate Guitar"])["sheet"][0] == "failed"
    spent = cases["this hour's lookups spent on Ultimate Guitar"]
    assert not any("ultimate-guitar" in r for r in spent["out"]["requests"])
    assert "lookup requests to Ultimate Guitar are spent" in _ends(spent)["sheet"][1]
    kept = cases["what follows the sheet held to the half of the hour's lookups not kept for sheets"]
    assert "kept for sheets" in _ends(kept)["ug"][1]
    for refused in ("an ignored song refused", "a tab of a kind caracole doesn't use refused before anything is written"):
        r = cases[refused]
        assert r["out"]["result"]["result"]["refused"] and not r["out"]["requests"] and not r["out"]["rows"]
    assert _ends(cases["lyrics put together"])["lyrics"] == (
        "done", "LRCLIB has none; Megalobiz has no timed ones; lyrics from AZLyrics")
    artist = cases["a song the offline index lacks, through its artist's page on Ultimate Guitar"]
    assert artist["out"]["requests"][0].startswith(f"GET {LAKE_URL}?filter=")
    choose_, clear_ = cases["--choose"], cases["--clear"]
    assert choose_["out"]["result"]["address"] == RIVER[102].url and not choose_["out"]["requests"]
    assert clear_["out"]["result"]["said"][0].startswith("Took tab 102 out of [pin]")
    assert clear_["out"]["rows"]["phone_overrides"] == []
