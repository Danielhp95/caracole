"""UG's lookup path for a matched song, for the phone's lane ug-fetch-sheet (core.ug's ``UgFetch.processSong`` and
``keepVersion``, ``internal/fetch/``) to replay: scenario records (tests/helpers/scenario.py, the corpus spec's
"Scenario records") of ``ug/fetch.py``'s ``process_song`` and ``keep_version`` over a fake Ultimate Guitar.

**The world.** One song, "Soda Stereo - Persiana Americana", matched to ``soda-stereo/persiana-americana`` with ten
synthetic lyric lines, and the offline index's tabs of it, whose pages (helpers/ug_pages.py, at their slugged URLs)
each list the other versions of their type: chords 101 (every line), 102 (half of them, the best rated), 103 (nine
lines, an acoustic slug), 104 and 105 (listed alone), the text tabs 201 and 202, and versions rated low that
``keep_version``'s cases ask for. The real page of tests/fixtures/ug/tab_chords.html, by fixture reference, is a pin's
sheet, so that ``sheet.json`` is UG's raw in UG's key order, its floats as ``repr`` writes them.

**Vectors** (``vectors/lookup/``):

- ``ug_sheet.jsonl``: ``{fn: "caracole.ug.fetch.process_song", case, fixture, kw: {song, passes}, now, clients,
  cache, answers, out | raises + after}``: each pass of ``passes`` (``{guitar, max_pages_per_group,
  guitar_pages_per_group, versions, rank}``, ``rank`` every field of ``RankPolicy`` by Python's names) is
  ``process_song(FetchContext(…), song, guitar=…)`` in turn, through one client, as a lookup's sheet stage then its
  ug stage ask (get.py ``_fetch_context``: the first pass ``max_pages_per_group`` 1, ``scored_sheets`` 1,
  ``versions`` False); ``out.result`` each pass's ``SongFetchOutcome``.
- ``ug_keep.jsonl``: ``{fn: "caracole.ug.fetch.keep_version", case, fixture, kw: {song, tabs, pass}, …}``:
  ``keep_version`` of each of ``tabs`` in turn (a context of its own each, ``pass`` as above), over a library the
  lookup filled, through one client: each of its answers (kept, same, held, sheet, gone, unreadable, closed, no text,
  unknown), ``out.result`` the list of them.

The overrides of a case (pins, ``[block]``, ``[lacuerda]``) are written to an overrides.toml with overrides.py's
writers and read back by ``load_overrides``; the fixture carries them as the phone holds them, ``phone_overrides``
rows (``tbl``, the key, the name written, the canonical JSON of ``overrides.song_entries``' value), which
``Overrides.read`` reads.

Stamps: songs.py's clock (``utc_now_iso``) is the record's ``now`` while the world is made and each pass runs.
library.keep_file stamps ``created_at`` with SQLite's clock, which no record can fix: a ``files`` row a pass wrote is
checked to hold a time of that form now, then recorded as the record's ``now``, the time the phone's
``Kept.keepFile`` is given (tests/test_conformance_library_writes.py's rule). ``write_info`` (info.json) is the
viewer's, M5's: no pass writes it here (``ug.fetch.write_info`` stands still), as the phone writes none.

Regenerate with ``CARACOLE_CORPUS=write`` (tests/conformance/README.md).
"""

from __future__ import annotations

import dataclasses
import json
import re
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Iterator
from unittest import mock

import httpx
import pytest

from helpers.corpus import VECTORS, check, fixture_ref, jsonl, phone_schema
from helpers.scenario import record
from helpers.ug_pages import make_tab_page_html, version_dict

MADE_BY = "tests/test_conformance_ug_fetch.py"
LOOKUP = VECTORS / "lookup"
SHEET = LOOKUP / "ug_sheet.jsonl"
KEEP = LOOKUP / "ug_keep.jsonl"

NOW = datetime(2026, 11, 3, 12, 0, tzinfo=UTC)
STAMP = "2026-11-03T12:00:00Z"
ADDED = "2026-10-01T00:00:00Z"
STAMP_SHAPE = re.compile(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ")
TAB = "https://tabs.ultimate-guitar.com/tab/"
SODA_URL = "https://www.ultimate-guitar.com/artist/soda_stereo_2946"
ARTIST, TITLE = "Soda Stereo", "Persiana Americana"
ARTIST_KEY, SONG_KEY = "soda-stereo", "persiana-americana"
DISPLAY = f"{ARTIST} - {TITLE}"
HTML = [["content-type", "text/html; charset=utf-8"]]
UG_TYPES = {"chords": "Chords", "tabs": "Tabs", "pro": "Pro", "official": "Official"}

# Synthetic lyrics: ten distinct lines, in two stanzas.
LINES = [
    "walking down the river road tonight",
    "counting every lantern on the shore",
    "the wind is singing softly in the pines",
    "and nobody remembers what we were",
    "hold the silver morning in your hands",
    "every window glowing like a promise",
    "we kept the summer folded in a letter",
    "until the rain forgot to say goodbye",
    "carry me across the sleeping valley",
    "where the paper boats are waiting still",
]
LYRICS = "\n".join(LINES[:5]) + "\n\n" + "\n".join(LINES[5:])

# UG's 404 page has no js-store; a page that won't parse (a maintenance page) has none either.
NOT_FOUND = "<!DOCTYPE html>\n<html><head><title>Oops! We couldn't find that page.</title></head><body></body></html>\n"
UNREADABLE = "<!DOCTYPE html>\n<html><head><title>Maintenance</title></head><body>Back soon</body></html>\n"

# The passes a lookup makes (get.py ``_fetch_context``): the sheet stage's, then the ug stage's.
FIRST = {"guitar": False, "max_pages_per_group": 1, "guitar_pages_per_group": 1, "versions": False, "scored_sheets": 1}
REST = {"guitar": True, "max_pages_per_group": 3, "guitar_pages_per_group": 1, "versions": True, "scored_sheets": 3}


# --- the world ------------------------------------------------------------------------------------------------


def slugged(tab_id: int, kind: str = "chords", song: str = SONG_KEY) -> str:
    return f"{TAB}{ARTIST_KEY}/{song}-{kind}-{tab_id}"


def sheet_markup(tag: str, lines: list[str]) -> str:
    """A chords-over-lyrics sheet in UG markup; the line ``tag`` tells which version it is."""
    rows = ["[Intro]", tag, ""]
    for line in lines:
        rows += ["[tab][ch]Am[/ch]       [ch]F[/ch]       [ch]C[/ch]", f"{line}[/tab]"]
    return "\r\n".join(rows)


def tab_markup(tag: str) -> str:
    return "\r\n".join(["[Riff]", tag, "[tab]e|-----0-----|", "B|---1---1---|[/tab]"])


@dataclasses.dataclass
class Version:
    """One version of the world's song as UG lists it, and its page's text (None: a page with no text)."""

    tab_id: int
    kind: str = "chords"
    rating: float = 4.5
    votes: int = 10
    number: int = 1
    content: str | None = None
    url: str | None = None  # its tab_url: by default its slugged page
    extra: dict[str, Any] = dataclasses.field(default_factory=dict)

    def listed(self) -> dict[str, Any]:
        return version_dict(self.tab_id, type=UG_TYPES[self.kind], version=self.number, rating=self.rating,
                            votes=self.votes, song=TITLE, artist=ARTIST, song_id=67624,
                            tab_url=self.url or slugged(self.tab_id, self.kind), **self.extra)


VERSIONS = {v.tab_id: v for v in [
    Version(101, rating=4.5, votes=50, number=1, content=sheet_markup("version 101", LINES)),
    Version(102, rating=4.9, votes=200, number=2, content=sheet_markup("version 102", LINES[:5])),
    Version(103, rating=4.7, votes=30, number=3, content=sheet_markup("version 103", LINES[:9]),
            url=slugged(103, song=f"{SONG_KEY}-acoustic")),
    Version(104, rating=4.2, votes=5, number=4, content=sheet_markup("version 104", LINES)),
    Version(105, rating=1.0, votes=1, number=5, content=sheet_markup("version 104", LINES)),  # 104's very text
    Version(107, rating=1.0, votes=1, number=7, content=tab_markup("tab 202")),  # the text tab 202's text
    Version(108, rating=1.0, votes=1, number=8, content=sheet_markup("version 108", LINES[:2])),
    Version(109, rating=1.0, votes=1, number=9, content=sheet_markup("version 109", LINES[:2])),
    Version(110, rating=1.0, votes=1, number=10, content=sheet_markup("version 110", LINES[:2])),
    Version(111, rating=1.0, votes=1, number=11, content=sheet_markup("version 111", LINES[:2])),
    Version(201, kind="tabs", rating=4.6, votes=40, number=1, content=tab_markup("tab 201")),
    Version(202, kind="tabs", rating=4.8, votes=90, number=2, content=tab_markup("tab 202")),
]}
# The versions the sheet's cases list (the rest are keep_version's).
CORE = {k: VERSIONS[k] for k in (101, 102, 103, 104, 108, 201, 202)}
OFFICIAL = Version(9001, kind="official", rating=4.9, votes=900, url=f"{TAB}{ARTIST_KEY}/{SONG_KEY}-official-9001")
# The index's tabs of the song: (tab id, song key, type). 104 and the rest are listed on the pages alone.
INDEX = [(101, SONG_KEY, "chords"), (102, SONG_KEY, "chords"), (103, f"{SONG_KEY}-acoustic", "chords"),
         (201, SONG_KEY, "tabs"), (202, SONG_KEY, "tabs")]


def page_of(tab_id: int, *, versions: dict[int, Version] | None = None, content: str | None | bool = True,
            type_: str | None = None) -> str:
    """The tab page of ``tab_id``: its own tab and the other versions of its type, UG's Official among them."""
    versions = versions or CORE
    own = versions[tab_id]
    tab = own.listed()
    if type_ is not None:
        tab["type"] = type_
    others = [v.listed() for v in versions.values() if v.kind == own.kind and v.tab_id != tab_id]
    if own.kind == "chords":
        others.append(OFFICIAL.listed())
    text = own.content if content is True else content
    return make_tab_page_html(tab, others, content=text, artist_url=SODA_URL)


def ok(body: Any) -> dict[str, Any]:
    return {"status": 200, "headers": HTML, "body": body}


def answer_of(tab_id: int, **kw: Any) -> tuple[str, dict[str, Any]]:
    v = VERSIONS[tab_id]
    return f"GET {v.url or slugged(tab_id, v.kind)}", ok(page_of(tab_id, **kw))


def answers_of(*tab_ids: int, versions: dict[int, Version] | None = None) -> dict[str, dict[str, Any]]:
    return dict(answer_of(t, versions=versions) for t in tab_ids)


def cached(answers: dict[str, dict[str, Any]], fetched_at: str = "2026-11-03T11:00:00Z") -> dict[str, Any]:
    """Answers as the HTTP cache holds them."""
    return {"ug": {r: {"status": a["status"], "fetched_at": fetched_at, "body": a["body"]} for r, a in answers.items()}}


@contextmanager
def clock() -> Iterator[None]:
    """songs.py's clock at the record's ``now``, and no info.json (the viewer's, M5's)."""
    with mock.patch("caracole.songs.utc_now_iso", lambda: STAMP), \
            mock.patch("caracole.ug.fetch.write_info", lambda *a, **k: None):
        yield


def canonical(value: Any) -> str:
    from caracole import canonical as c

    return c.dumps(value)


class World:
    """A library of one song, its database, its overrides.toml and its offline index."""

    def __init__(self, tmp: Path, name: str, *, index: list[tuple[int, str, str]] | None = None,
                 artist: str = ARTIST, title: str = TITLE, match: tuple[str, str] = (ARTIST_KEY, SONG_KEY),
                 lyrics: str | None = LYRICS):
        from caracole import db
        from caracole.lyrics import Lyrics
        from caracole.normalize import identity_key
        from caracole.songs import update_song, upsert_song

        self.dir = tmp / name
        self.dir.mkdir(parents=True)
        self.conn = db.connect(self.dir / "caracole.sqlite")
        phone_schema(self.conn)
        self.library = self.dir / "library"
        self.library.mkdir()
        self.overrides_file = self.dir / "overrides.toml"
        self.display = f"{artist} - {title}"
        self.records = 0
        with clock():
            self.song_id, _ = upsert_song(self.conn, artists=[artist], title=title, album=None, duration_ms=213000,
                                          isrc=None, source="wanted", source_id=identity_key(artist, title),
                                          added_at=ADDED)
            fields: dict[str, Any] = {"match_decision": "accept", "match_step": "exact", "match_score": 100.0,
                                      "match_artist_key": match[0], "match_song_key": match[1],
                                      "matched_at": ADDED, "ug_dirty": True}
            if lyrics is not None:
                found = Lyrics(plain=lyrics, synced=None, instrumental=False, duration=213.0, lrclib_id=7)
                fields |= {"lyrics_status": "found", "lyrics_json": found.to_json(), "lyrics_at": ADDED}
            update_song(self.conn, self.song_id, **fields)
        for tab_id, song_key, kind in INDEX if index is None else index:
            path = f"{match[0]}/{song_key}-{kind}-{tab_id}" if song_key else ""
            self.conn.execute(
                "INSERT INTO ug_index (tab_id, artist_key, song_key, type, sitemap, first_seen, path) "
                "VALUES (?, ?, ?, ?, 'last', ?, ?)", (tab_id, match[0], song_key or match[1], kind, ADDED, path))

    @property
    def song(self):
        from caracole.songs import get_song

        return get_song(self.conn, self.song_id)

    def overrides(self):
        from caracole.overrides import load_overrides

        return load_overrides(self.overrides_file)

    def write_overrides(self, edit) -> None:
        """``edit(path)`` writes overrides.toml with overrides.py's writers; the phone's rows of it follow."""
        edit(self.overrides_file)
        self.conn.execute("DELETE FROM phone_overrides")
        for row in rows_of(self.overrides(), self.display):
            self.conn.execute("INSERT INTO phone_overrides (tbl, key, written, value) VALUES (?, ?, ?, ?)",
                              (row["tbl"], row["key"], row["written"], row["value"]))

    def context(self, client, spec: dict[str, Any]):
        from caracole.config import RankPolicy
        from caracole.ug.fetch import FetchContext

        return FetchContext(conn=self.conn, client=client, overrides=self.overrides(),
                            rank=dataclasses.replace(RankPolicy(), scored_sheets=spec["scored_sheets"]),
                            library_dir=self.library, now=NOW, max_pages_per_group=spec["max_pages_per_group"],
                            guitar_pages_per_group=spec["guitar_pages_per_group"], versions=spec["versions"])

    def settle(self) -> None:
        """The files' ``created_at`` at the record's ``now`` (SQLite's clock wrote them)."""
        self.conn.execute("UPDATE files SET created_at = ?", (STAMP,))

    def run(self, passes: list[dict[str, Any]], pages: dict[str, dict[str, Any]]) -> None:
        """``passes`` of ``process_song`` before a case, through a client answering ``pages``: the library a lookup
        left."""
        from caracole.ug.fetch import process_song

        with self.client(pages) as client, clock():
            for spec in passes:
                process_song(self.context(client, spec), self.song, guitar=spec["guitar"])
        self.settle()

    def keep(self, tab_id: int, pages: dict[str, dict[str, Any]]) -> str:
        from caracole.ug.fetch import keep_version

        with self.client(pages) as client, clock():
            said = keep_version(self.context(client, REST), self.song, tab_id)
        self.settle()
        return said

    @contextmanager
    def client(self, pages: dict[str, dict[str, Any]]):
        from caracole import config
        from caracole.http import PoliteClient

        def handler(request: httpx.Request) -> httpx.Response:
            a = pages.get(f"GET {request.url}")
            if a is None:
                return httpx.Response(404, content=NOT_FOUND.encode())
            return httpx.Response(a["status"], headers=[tuple(h) for h in a.get("headers", [])],
                                  content=a["body"].encode("utf-8"))

        client = PoliteClient("ug", dataclasses.replace(config.DEFAULT_PROVIDERS["ug"], budget=100, delay=(0.0, 0.0)),
                              self.dir / "setup-cache", user_agent=config.DEFAULT_USER_AGENT,
                              transport=httpx.MockTransport(handler), sleep=lambda s: None, clock=lambda: 0.0,
                              wall_clock=lambda: NOW)
        try:
            yield client
        finally:
            client.close()

    def record(self, fn: str, case: str, call, kw: dict[str, Any], answers: dict[str, dict[str, Any]],
               cache: dict[str, Any] | None = None, budget: int = 6) -> dict[str, Any]:
        self.records += 1
        with clock():
            made = record(self.conn, self.library, fn=fn, case=case, call=call, kw=kw, now=NOW,
                          clients={"ug": {"budget": budget, "delay": [0.0, 0.0]}}, answers=answers, cache=cache,
                          cache_dir=self.dir / f"cache-{self.records}")
        _stamped(made)
        done = made.get("out") or made["after"]
        made["answers"] = {r: a for r, a in made["answers"].items() if r in done["requests"]}  # what was asked alone
        self.settle()
        return made

    def process(self, case: str, passes: list[dict[str, Any]], answers: dict[str, dict[str, Any]],
                cache: dict[str, Any] | None = None, budget: int = 6) -> dict[str, Any]:
        from caracole.config import RankPolicy
        from caracole.ug.fetch import process_song

        def call(clients):
            return [process_song(self.context(clients["ug"], spec), self.song, guitar=spec["guitar"])
                    for spec in passes]

        def written(spec: dict[str, Any]) -> dict[str, Any]:
            rank = dataclasses.asdict(dataclasses.replace(RankPolicy(), scored_sheets=spec["scored_sheets"]))
            return {k: v for k, v in spec.items() if k != "scored_sheets"} | {"rank": rank}

        return self.record("caracole.ug.fetch.process_song", case, call,
                           {"song": self.song_id, "passes": [written(p) for p in passes]}, answers, cache, budget)

    def keep_record(self, case: str, tabs: list[int], answers: dict[str, dict[str, Any]],
                    cache: dict[str, Any] | None = None) -> dict[str, Any]:
        """``keep_version`` of each of ``tabs`` in turn, through one client, each with a context of its own."""
        from caracole.config import RankPolicy
        from caracole.ug.fetch import keep_version

        spec = {k: v for k, v in REST.items() if k != "scored_sheets"} | {
            "rank": dataclasses.asdict(RankPolicy())}
        return self.record("caracole.ug.fetch.keep_version", case,
                           lambda clients: [keep_version(self.context(clients["ug"], REST), self.song, t)
                                            for t in tabs],
                           {"song": self.song_id, "tabs": tabs, "pass": spec}, answers, cache, budget=10)

    def close(self) -> None:
        self.conn.close()


def rows_of(o, display: str) -> list[dict[str, str]]:
    """The phone's ``phone_overrides`` rows of ``o``, whose one song is ``display``, as the phone holds overrides.toml
    (phone.sql): the song tables (and ``ignore``) by identity key, ``block`` by tab id."""
    from caracole.overrides import SONG_TABLES, song_entries

    rows = []
    keys = sorted({k for t in SONG_TABLES for k in getattr(o, t)} | set(o.ignore))
    for key in keys:
        entries = song_entries(o, key)
        for table in (*SONG_TABLES, "ignore"):
            if table in entries:
                rows.append({"tbl": table, "key": key, "written": display, "value": canonical(entries[table])})
    for tab in sorted(o.block):
        rows.append({"tbl": "block", "key": str(tab), "written": str(tab), "value": canonical(True)})
    return sorted(rows, key=lambda r: (r["tbl"], r["key"]))


def _stamped(made: dict[str, Any]) -> None:
    """keep_file's ``created_at``, SQLite's clock: each ``files`` row a pass wrote holds a time of that form now,
    recorded as the record's ``now``; a table whose rows are then as before is no change."""
    done = made.get("out") or made["after"]
    rows = done["rows"]
    if "files" not in rows:
        return
    before = [r["row"] for r in made["fixture"] if r.get("table") == "files"]
    old = {r["id"]: r for r in before}
    for row in rows["files"]:
        was = old.get(row["id"])
        if was is not None and was["created_at"] == row["created_at"]:
            continue
        stamp = row["created_at"]
        assert STAMP_SHAPE.fullmatch(stamp), stamp
        at = datetime.strptime(stamp, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
        assert abs(datetime.now(UTC) - at) < timedelta(minutes=5), stamp
        row["created_at"] = STAMP
    if rows["files"] == before:
        del rows["files"]


# --- process_song's cases ---------------------------------------------------------------------------------------


def two_passes(tmp: Path) -> list[dict[str, Any]]:
    """A lookup's two passes: the sheet stage's (one versions page, one sheet scored, nothing kept beside it), then
    the ug stage's (the rest scored, kept beside the sheet, which a complete one replaces; the auto sheet retired;
    the tab slot)."""
    from caracole.library import keep_file
    from caracole.versions import set_picks, upsert_version

    w = World(tmp, "two-passes")
    try:
        auto = upsert_version(w.conn, provider="auto", tab_id=str(w.song_id), song_id=w.song_id, slot="sheet",
                              kind="auto", rating=0, votes=0, version=1, label=None, url="file:///audio.m4a",
                              raw={"model": "btc"}, now=ADDED)
        keep_file(w.conn, w.library, song=w.song, version_id=auto, name="sheet (auto).txt", data=b"Am F C\n", rank=1)
        set_picks(w.conn, w.song_id, ("auto",), [auto])
        w.settle()
        return [w.process("a lookup's sheet pass, then the rest: versions kept beside, the tab, the auto sheet "
                          "retired", [FIRST, REST], answers_of(101, 102, 103, 104, 201, 202))]
    finally:
        w.close()


def pins(tmp: Path) -> list[dict[str, Any]]:
    """Pins: the pasted bare address of a slugged tab read at its slugged page, a pin UG answers 404 for and a Guitar
    Pro file's pin pin nothing, a blocked pin is none; the pinned sheet keeps the top versions beside it from the
    cache alone (no request), and the tab slot goes on unpinned."""
    from caracole.overrides import add_block, add_pin

    w = World(tmp, "pins")
    try:
        def edit(path):
            add_pin(path, DISPLAY, [f"{TAB}101", f"{TAB}102", f"{TAB}999", f"{TAB}301"])
            add_block(path, 101)

        w.write_overrides(edit)
        pro = version_dict(301, type="Pro", song=TITLE, artist=ARTIST, tab_url=f"{TAB}301")
        answers = answers_of(102, 201, 202) | {
            f"GET {TAB}999": {"status": 404, "headers": HTML, "body": NOT_FOUND},
            f"GET {TAB}301": ok(make_tab_page_html(pro, [], content=None, meta={"fileExtension": ".gp5"})),
        }
        made = [w.process("pins: a bare address read at the slugged page, a 404 and a Guitar Pro page pin nothing, "
                          "a blocked pin is none; the versions beside it from the cache alone",
                          [REST], answers, cache=cached(answers_of(103, 104)))]
    finally:
        w.close()
    w = World(tmp, "pin-own-page", index=[(85053, "", "chords")], title="De Música Ligera",
              match=(ARTIST_KEY, "de-musica-ligera"))
    try:
        w.write_overrides(lambda path: add_pin(path, f"{ARTIST} - De Música Ligera", [f"{TAB}85053"]))
        page = {f"GET {TAB}85053": ok(fixture_ref("ug/tab_chords.html"))}
        made.append(w.process("a pin's sheet is UG's own page: its raw in UG's order, its floats as repr",
                              [REST], page))
    finally:
        w.close()
    return made


def rating(tmp: Path) -> list[dict[str, Any]]:
    """Rating pages: the lowest unrated id first, a slug naming no part before one that does, a stale version read
    again, ``max_pages_per_group`` pages of the type at most."""
    from caracole.versions import STALE, upsert_version

    versions = {
        105: Version(105, rating=4.0, votes=3, content=sheet_markup("an intro", LINES[:1]), extra={"part": "intro"},
                     url=slugged(105, song=f"{SONG_KEY}-intro")),
        110: Version(110, rating=4.6, votes=40, content=sheet_markup("version 110", LINES)),
        111: Version(111, rating=4.8, votes=60, content=sheet_markup("version 111", LINES[:6])),
        112: Version(112, rating=4.1, votes=8, content=sheet_markup("version 112", LINES[:9])),
    }
    w = World(tmp, "rating", index=[(105, f"{SONG_KEY}-intro", "chords"), (110, SONG_KEY, "chords"),
                                    (111, SONG_KEY, "chords"), (112, SONG_KEY, "chords")])
    try:
        stale = upsert_version(w.conn, provider="ug", tab_id="110", song_id=w.song_id, slot="sheet", kind="chords",
                               rating=3.0, votes=2, version=1, label=None, url=slugged(110), raw={"id": 110},
                               now=ADDED)
        w.conn.execute("UPDATE versions SET gone = ? WHERE id = ?", (STALE, stale))
        intro = versions[105].listed()
        answers = {f"GET {slugged(110)}": ok(page_of(110, versions={k: v for k, v in versions.items() if k != 105})),
                   f"GET {slugged(105, song=f'{SONG_KEY}-intro')}": ok(make_tab_page_html(
                       intro, [], content=versions[105].content, artist_url=SODA_URL)),
                   f"GET {slugged(111)}": ok(page_of(111, versions={k: v for k, v in versions.items() if k != 105})),
                   f"GET {slugged(112)}": ok(page_of(112, versions={k: v for k, v in versions.items() if k != 105}))}
        spec = FIRST | {"max_pages_per_group": 2, "scored_sheets": 2}
        return [w.process("rating pages: the lowest unrated id first, a slug naming no part before one that does, a "
                          "stale version read again", [spec], answers)]
    finally:
        w.close()


def yours(tmp: Path) -> list[dict[str, Any]]:
    """The versions you kept: one the scoring passed over kept beside the sheet from the cache, one with no page
    there whose files stay as they are."""
    w = World(tmp, "yours")
    try:
        pages = answers_of(101, 102, 103, 104, 201, 202)
        w.run([FIRST, REST], pages)
        assert w.keep(108, answers_of(108)) == "kept"
        from caracole.db import kv_set_json
        from caracole.sheet_versions import yours_key

        kv_set_json(w.conn, yours_key(w.song_id), ["101", "108"])
        cache = cached(answers_of(101, 102, 103, 104, 201, 202))
        return [w.process("yours: one kept beside the sheet from the cache, one with no page there held as it is",
                          [REST], {}, cache=cache)]
    finally:
        w.close()


def unreadable(tmp: Path) -> list[dict[str, Any]]:
    """A cached page that won't parse, fetched again and still not: noted, asked for again after 7 days, doubling to
    90; due, it is asked again; not due, nothing is sent; the song stays dirty, never a miss."""
    from caracole.db import kv_set_json

    bad = {"status": 200, "headers": HTML, "body": UNREADABLE}
    made = []
    for name, record_, answer, case in [
        ("unreadable-first", None, bad, "a cached page that won't parse, nor fetched again: asked again in 7 days"),
        ("unreadable-again", {"until": "2026-11-02T12:00:00Z", "strikes": 1, "error": "ug: x"}, bad,
         "due again and still unreadable: twice as long"),
        ("unreadable-most", {"until": "2026-11-01T00:00:00Z", "strikes": 4, "error": "ug: x"}, bad,
         "unreadable a fifth time: 90 days at most"),
        ("unreadable-waits", {"until": "2026-11-05T00:00:00Z", "strikes": 1, "error": "ug: x"}, None,
         "not due yet: nothing is sent, the song stays dirty"),
        ("unreadable-read", {"until": "2026-11-02T00:00:00Z", "strikes": 2, "error": "ug: x"},
         answer_of(101)[1], "due and read at last: the note goes"),
    ]:
        index = [(101, SONG_KEY, "chords"), (102, SONG_KEY, "chords")]
        w = World(tmp, name, index=index)
        try:
            if record_ is not None:
                kv_set_json(w.conn, "ug:unreadable:101", record_)
            versions = {k: VERSIONS[k] for k in (101, 102)}
            answers = {f"GET {slugged(102)}": ok(page_of(102, versions=versions))}
            if answer is not None:
                answers[f"GET {slugged(101)}"] = (answer if answer is bad
                                                  else ok(page_of(101, versions=versions)))
            cache = cached({f"GET {slugged(101)}": bad})
            made.append(w.process(case, [REST], answers, cache=cache))
        finally:
            w.close()
    return made


def closed(tmp: Path) -> list[dict[str, Any]]:
    """robots.txt: a version UG moved where robots.txt closes is passed over (neither gone nor unreadable, the song
    checked clean), and listed versions at closed links are never recorded."""
    versions = {k: VERSIONS[k] for k in (101, 102)} | {
        113: Version(113, rating=4.0, votes=4, url=f"{TAB}download/113"),
        114: Version(114, rating=4.0, votes=4, url=f"{TAB}track/{SONG_KEY}-chords-114"),
    }
    w = World(tmp, "closed", index=[(101, SONG_KEY, "chords"), (102, SONG_KEY, "chords")])
    try:
        answers = {f"GET {slugged(101)}": ok(page_of(101, versions=versions)),
                   f"GET {slugged(102)}": {"status": 301, "headers": [["location", f"{TAB}print?id=102"]],
                                           "body": ""}}
        return [w.process("a version UG moved where robots.txt closes is passed over; closed links never recorded",
                          [REST], answers)]
    finally:
        w.close()


def gone(tmp: Path) -> list[dict[str, Any]]:
    """UG answers 404: a recorded version is gone, and an id the index alone knows gets a row to say so."""
    versions = {k: VERSIONS[k] for k in (101, 102, 103)}
    w = World(tmp, "gone", index=[(101, SONG_KEY, "chords"), (102, SONG_KEY, "chords"), (106, SONG_KEY, "chords")])
    try:
        answers = {f"GET {slugged(101)}": ok(page_of(101, versions=versions)),
                   f"GET {slugged(102)}": ok(page_of(102, versions=versions)),
                   f"GET {slugged(106)}": {"status": 404, "headers": HTML, "body": NOT_FOUND},
                   f"GET {versions[103].url}": {"status": 404, "headers": HTML, "body": NOT_FOUND}}
        return [w.process("a 404 marks a version gone, and gives an id the index alone knows a row", [REST], answers)]
    finally:
        w.close()


def stopped(tmp: Path) -> list[dict[str, Any]]:
    """A block raises (nothing marked), and so does a spent budget, with what came before kept."""
    made = []
    w = World(tmp, "blocked", index=[(101, SONG_KEY, "chords")])
    try:
        made.append(w.process("a block raises: nothing is marked", [REST],
                              {f"GET {slugged(101)}": {"status": 403, "headers": HTML, "body": "Forbidden"}}))
    finally:
        w.close()
    w = World(tmp, "spent")
    try:
        made.append(w.process("a spent budget raises, what came before kept", [REST],
                              answers_of(101, 102, 103), budget=2))
    finally:
        w.close()
    return made


def other_site(tmp: Path) -> list[dict[str, Any]]:
    """Another site's sheet stays when UG's covers no more of the lyrics, and LaCuerda's you picked whatever UG's."""
    from caracole.library import keep_file
    from caracole.overrides import add_lacuerda
    from caracole.versions import set_coverage, set_picks, upsert_version

    made = []
    for name, pick, index, case in [
        ("lacuerda-stays", False, [(102, SONG_KEY, "chords")],
         "another site's complete sheet stays: UG's covers no more"),
        ("lacuerda-picked", True, [(101, SONG_KEY, "chords")],
         "LaCuerda's sheet you picked stays, whatever UG's"),
    ]:
        w = World(tmp, name, index=index)
        try:
            lc = upsert_version(w.conn, provider="lacuerda", tab_id="soda_stereo/persiana_americana-1",
                                song_id=w.song_id, slot="sheet", kind="acordes", rating=4.0, votes=3, version=1,
                                label=None, url="https://acordes.lacuerda.net/soda_stereo/persiana_americana.shtml",
                                raw={"title": TITLE}, now=ADDED)
            set_coverage(w.conn, lc, 0.7 if pick else 1.0)
            keep_file(w.conn, w.library, song=w.song, version_id=lc, name="sheet.txt", data=b"LaCuerda's sheet\n", rank=1)
            set_picks(w.conn, w.song_id, ("acordes",), [lc])
            if pick:
                w.write_overrides(lambda path: add_lacuerda(
                    path, DISPLAY, "https://acordes.lacuerda.net/soda_stereo/persiana_americana"))
            w.settle()
            versions = {k: VERSIONS[k] for k, _, _ in index}
            answers = {f"GET {slugged(t)}": ok(page_of(t, versions=versions)) for t, _, _ in index}
            made.append(w.process(case, [REST], answers))
        finally:
            w.close()
    return made


def left_over(tmp: Path) -> list[dict[str, Any]]:
    """What a fetch leaves behind it: a tab you have blocked since goes with nothing to replace it (the block
    remembered), and the files of a match undone go, with no request."""
    from caracole.overrides import add_block
    from caracole.songs import update_song
    from caracole.versions import mark_stale

    made = []
    only = {101: VERSIONS[101]}
    pair = {101: VERSIONS[101], 201: VERSIONS[201]}
    w = World(tmp, "blocked-since", index=[(101, SONG_KEY, "chords"), (201, SONG_KEY, "tabs")])
    try:
        w.run([REST], answers_of(101, 201, versions=pair))
        w.write_overrides(lambda path: add_block(path, 201))
        made.append(w.process("a tab you have blocked since goes, nothing replacing it, the block remembered",
                              [REST], answers_of(101, versions=pair)))
    finally:
        w.close()
    w = World(tmp, "undone", index=[(101, SONG_KEY, "chords")])
    try:
        w.run([REST], answers_of(101, versions=only))
        with clock():
            update_song(w.conn, w.song_id, match_decision="review", match_step="exact", match_artist_key=None,
                        match_song_key=None, match_candidates=[{"artist_key": "soda-stereo-tribute",
                                                                "song_key": SONG_KEY, "score": 80.0, "step": "exact"}])
            mark_stale(w.conn, w.song_id, "ug")
        made.append(w.process("a match undone loses what it kept, with no request", [REST], {}))
    finally:
        w.close()
    return made


def ukulele(tmp: Path) -> list[dict[str, Any]]:
    """Your pin of a ukulele version is your choice of sheet: UG's own page (tests/fixtures/ug/tab_ukulele.html), its
    meta (the capo) in sheet.json."""
    from caracole.overrides import add_pin

    page = f"{TAB}vance-joy/riptide-ukulele-1391193"
    w = World(tmp, "ukulele-pin", artist="Vance Joy", title="Riptide", match=("vance-joy", "riptide"),
              index=[(1391193, "riptide", "ukulele")])
    try:
        w.write_overrides(lambda path: add_pin(path, "Vance Joy - Riptide", [page]))
        return [w.process("a ukulele pin chooses the sheet: UG's own page, its meta kept", [REST],
                          {f"GET {page}": ok(fixture_ref("ug/tab_ukulele.html"))})]
    finally:
        w.close()


def sheet_records(tmp: Path) -> list[dict[str, Any]]:
    return [*two_passes(tmp), *pins(tmp), *rating(tmp), *yours(tmp), *unreadable(tmp), *closed(tmp), *gone(tmp),
            *stopped(tmp), *other_site(tmp), *left_over(tmp), *ukulele(tmp)]


# --- keep_version's answers -------------------------------------------------------------------------------------


def keep_records(tmp: Path) -> list[dict[str, Any]]:
    """keep_version over a library a lookup filled (the sheet 103, 104 and 102 beside it, the tab 202): each of its
    answers in turn, in one library, so that each finds what the ones before kept."""
    bad = {"status": 200, "headers": HTML, "body": UNREADABLE}
    no_text = ok(page_of(111, versions=VERSIONS, content=None, type_="Pro"))
    turns = [
        (101, answers_of(101, versions=VERSIONS), {}),  # kept
        (105, answers_of(105, versions=VERSIONS), {}),  # same: its text is 104's, kept beside: 104's page shows it
        (107, answers_of(107, versions=VERSIONS), {}),  # held: its text is the tab's, which no page shows
        (103, {}, answers_of(103, versions=VERSIONS)),  # sheet: it is the sheet already (its page from the cache)
        (108, {f"GET {slugged(108)}": {"status": 404, "headers": HTML, "body": NOT_FOUND}}, {}),  # gone
        (109, {f"GET {slugged(109)}": bad}, {f"GET {slugged(109)}": bad}),  # unreadable, cached and fetched again
        (110, {f"GET {slugged(110)}": {"status": 302, "headers": [["location", f"{TAB}download/110"]], "body": ""}},
         {}),  # closed: UG moved its page where robots.txt closes
        (111, {f"GET {slugged(111)}": no_text}, {}),  # no text: its page is another type's, with none
        (201, {}, {}),  # unknown: a text tab is no sheet's version
        (999, {}, {}),  # unknown: a tab the song has no version of
    ]
    w = World(tmp, "keep")
    try:
        w.run([FIRST, REST], answers_of(101, 102, 103, 104, 201, 202, versions=VERSIONS))
        answers = {r: a for _, given, _ in turns for r, a in given.items()}
        cache = cached({r: a for _, _, held in turns for r, a in held.items()})
        return [w.keep_record("each answer in turn: kept, same, held, sheet, gone, unreadable, closed, no text, "
                              "unknown", [t for t, _, _ in turns], answers, cache)]
    finally:
        w.close()


# --- the tests --------------------------------------------------------------------------------------------------


def every_file(tmp: Path) -> dict[Path, str]:
    return {SHEET: jsonl(sheet_records(tmp / "sheet"), corpus="lookup/ug_sheet", made_by=MADE_BY),
            KEEP: jsonl(keep_records(tmp / "keep"), corpus="lookup/ug_keep", made_by=MADE_BY)}


@pytest.fixture(scope="module")
def made(tmp_path_factory) -> dict[Path, str]:
    return every_file(tmp_path_factory.mktemp("ug-fetch"))


@pytest.mark.parametrize("path", [SHEET, KEEP], ids=lambda p: p.name)
def test_the_vector_is_what_ug_fetch_does(made, path):
    check(path, made[path])


def test_the_vectors_are_the_same_on_another_run(made, tmp_path):
    assert every_file(tmp_path) == made


def _records(text: str) -> list[dict[str, Any]]:
    return [json.loads(line) for line in text.splitlines()[1:]]


def test_every_answer_of_keep_version_is_recorded(made):
    [turns] = _records(made[KEEP])
    assert turns["out"]["result"] == ["kept", "same", "held", "sheet", "gone", "unreadable", "closed", "no text",
                                      "unknown", "unknown"]


def test_the_lookups_passes_ask_as_get_py_does(made):
    two = next(r for r in _records(made[SHEET]) if r["case"].startswith("a lookup's sheet pass"))
    first, rest = two["out"]["result"]
    assert (first["settled"], first["tab"], first["kept_versions"]) == (True, None, [])
    assert rest["kept_versions"] and rest["tab"] == 202 and rest["sheet"] != first["sheet"]
    assert two["out"]["library"]["Soda Stereo/Persiana Americana/sheet (auto).txt"] is None
    files = {f["name"] for f in two["out"]["rows"]["files"]}
    assert {"sheet.txt", "sheet.json", "tab.txt", "tab.json"} <= files
    assert any(n.startswith("version-") and n.endswith(".json") for n in files)


def test_the_unreadable_notes_double_to_ninety_days(made):
    key = "ug:unreadable:101"
    out = {r["case"]: r.get("out") or r["after"] for r in _records(made[SHEET])}
    first = out["a cached page that won't parse, nor fetched again: asked again in 7 days"]
    noted = [json.loads(out[case]["kv"][key]) for case in (
        "a cached page that won't parse, nor fetched again: asked again in 7 days",
        "due again and still unreadable: twice as long", "unreadable a fifth time: 90 days at most")]
    assert [(n["until"], n["strikes"]) for n in noted] == [
        ("2026-11-10T12:00:00Z", 1), ("2026-11-17T12:00:00Z", 2), ("2027-02-01T12:00:00Z", 5)]
    waits = out["not due yet: nothing is sent, the song stays dirty"]
    assert key not in waits["kv"] and not any("chords-101" in r for r in waits["requests"])
    assert out["due and read at last: the note goes"]["kv"][key] is None
    song = first["rows"]["songs"][0]
    assert (song["ug_dirty"], song["ug_checked_at"]) == (1, None)


def test_a_block_and_a_spent_budget_raise_as_the_phone_must(made):
    raised = {r["case"]: r["raises"]["type"] for r in _records(made[SHEET]) if "raises" in r}
    assert sorted(raised.values()) == ["BudgetExhausted", "ProviderBlocked"]


def test_every_body_is_a_text_or_a_fixture_reference(made):
    for text in made.values():
        for r in _records(text):
            for entry in [*r["answers"].values(), *r["cache"].get("ug", {}).values()]:
                assert set(entry["body"]) <= {"text", "fixture"}
