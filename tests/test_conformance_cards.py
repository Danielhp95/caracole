"""The library page's cards, for the phone: what android/server's ``PhonePageData`` makes of the phone's own library.

``vectors/web/cards_full.jsonl`` holds, after its header:

- ``{"library": NAME, "fixture": [...], "overrides": TEXT}``: a library (``LIBRARIES``) as the computer holds it,
  ``helpers.corpus.dump_fixture``'s records of its database and its folder (its overrides as the phone holds them,
  ``phone_overrides`` rows, beside the computer's overrides.toml as written, ``overrides``), stamped alike every run;
- ``{"fn": "caracole.library_page.song_cards", "library": NAME, "now": STAMP, "songs": [ids] | null,
  "config": {"off": [provider, ...]}, "out": [card, ...]}``: ``song_cards`` of every song (``songs`` null) or of
  those, at ``now``, with the providers ``off`` turned off (``Config.provider(...).enabled`` false), each card as the
  page's data holds it (``key``, ``files`` with their sources, guitar and harmonica pages and download names, UG's
  ``versions`` and LaCuerda's, the auto sheet, a review's ``candidates`` with search.index_song, ``notFound``,
  ``sites`` with the misses' kv, MuseScore's links, ``links`` and ``buy`` by todo.songs_to_buy, ``hanzi``,
  ``progressions``);
- ``{"fn": "caracole.library_page.build_library_page", "library": NAME, "now": STAMP, "out": DATA}``: the page's
  data with no controls (the file's), but its ``sites``, the Sites tab's, which the phone takes from the mirror;
- ``{"fn": "caracole.web.app.WebApp.handle", "library": NAME, "args": ["GET", PATH], "out": {"progression",
  "library"}}``: /api/search's ``progression`` for a query over the library and its ``library`` rows (``[id, via,
  score]``), those the progression adds after your songs the words found.

What the phone can't be told apart from the computer by is left out of the libraries: no YouTube route (the
suite's yt-dlp is no program: ``youtube_fetch.route_problem`` is not None, so ``song_cards`` asks for no state), no
icons kept, no songbooks.toml. A Chinese song's sheet names its script in the computer's render record (kv
``render:<id>``, ``render.chinese_songs``) and in the phone's beside it (kv ``render:<id>:phone``, phone-render's),
so that each side reads its own.

A change to what library_page.py writes of a card, or to the helpers it calls, makes this stale: regenerate it with
``CARACOLE_CORPUS=write`` (tests/conformance/README.md), and the phone's CardsReplay reads it again.
"""

from __future__ import annotations

import dataclasses
import json
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from unittest import mock
from urllib.parse import urlencode

from caracole import canonical
from caracole.db import kv_delete, kv_set, kv_set_json
from caracole.library import keep_file, song_dir
from caracole.library_page import build_library_page, song_cards
from caracole.overrides import (
    SONG_TABLES,
    add_block,
    add_ignore,
    add_lacuerda,
    add_pin,
    add_version,
    load_overrides,
    put_song_entries,
    song_entries,
)
from caracole.songs import get_song, list_songs, update_song
from caracole.versions import upsert_version
from conftest import add_song
from helpers.corpus import VECTORS, check, dump_fixture, jsonl, phone_schema
from helpers.library_songs import TABS, hotel_california, with_versions

MADE_BY = "tests/test_conformance_cards.py"
CARDS = VECTORS / "web" / "cards_full.jsonl"
NOW = datetime(2026, 11, 3, 12, 0, tzinfo=UTC)
LATER = datetime(2026, 12, 20, 12, 0, tzinfo=UTC)  # 30 days and more after the artist pages were read
STAMP = "2026-10-19T00:00:00Z"
CHECKED = "2026-10-20T08:00:00Z"
UG = "https://tabs.ultimate-guitar.com/tab"
PROGRESSIONS = "{title: Let It Be}\n[C]When I [G]find my[Am]self in [F]times\n[C]Mother [G]Mary [F]comes to [C]me\n" \
               "{start_of_chorus}\n[Am]Let it [G]be, let it [F]be, let it [C]be\n[Am]Let it [G]be, let it [F]be, " \
               "let it [C]be\n{end_of_chorus}\n"
POP = "[C]one [G]two [Am]three [F]four\n[C]one [G]two [Am]three [F]four\n"


def _version(conn, song, provider, tab, slot, kind, *, raw=None, url="", rating=0.0, votes=0):
    return upsert_version(conn, provider=provider, tab_id=str(tab), song_id=song.id, slot=slot, kind=kind,
                          rating=rating, votes=votes, version=1, label=None, url=url, raw=raw or {}, now=STAMP)


def _keep(conn, cfg, song, version, name, data=b"x", rank=1):
    keep_file(conn, cfg.library_dir, song=song, version_id=version, name=name, data=data, rank=rank)


def _write(cfg, song, *names):
    folder = song_dir(cfg.library_dir, song)
    folder.mkdir(parents=True, exist_ok=True)
    for name in names:
        (folder / name).write_bytes(b"x")


def _index(conn, *rows):
    for tab, artist, title, kind in rows:
        conn.execute("INSERT INTO ug_index (tab_id, artist_key, song_key, type, sitemap, first_seen, path) "
                     "VALUES (?, ?, ?, ?, 'tabs1', ?, ?)",
                     (tab, artist, title, kind, STAMP, f"tab/{artist}/{title}-{kind}-{tab}"))


@dataclasses.dataclass
class Library:
    conn: Any
    cfg: Any
    displays: dict[str, str] = dataclasses.field(default_factory=dict)

    @property
    def overrides_file(self) -> Path:
        return self.cfg.overrides_file

    def song(self, artist, title, *, added, **more):
        song = add_song(self.conn, artist, title, added_at=added, artists=more.pop("artists", None))
        if more:
            update_song(self.conn, song.id, **more)
        self.displays[song.key] = song.display
        return get_song(self.conn, song.id)


def build_full(conn, cfg) -> Library:
    """Every kind of song a card says something of, in one library (the module's docstring)."""
    lib = Library(conn, cfg)
    phone_schema(conn)
    # Ultimate Guitar's index, read whole: a not-found song may go on the buy list
    _index(conn, (2001, "soda-stereo", "de-musica-ligera", "chords"), (2002, "soda-stereo", "de-musica-ligera", "chords"),
           (2003, "soda-stereo", "de-musica-ligera", "tabs"), (2004, "misc-originals", "de-musica-ligera", "chords"),
           (int(TABS[0]), "eagles", "hotel-california", "chords"), (3001, "radiohead", "creep", "chords"))
    kv_set(conn, "ug:index:built_at", STAMP)
    conn.execute("INSERT INTO musescore_index (page_id, path, title_key, sitemap) VALUES "
                 "(7, 'song/unknown_song-7', 'unknown-song', '1'), (3, 'song/unknown_song-3', 'unknown-song', '1')")

    # 1. Hotel California: one of everything, its versions, its harmonica tab's page, pinned and a tab blocked
    hotel = hotel_california(conn, cfg)
    with_versions(conn, cfg, hotel)
    _write(cfg, hotel, "harmonica-1.html")
    update_song(conn, hotel.id, match_decision="accept", match_step="exact", match_score=100.0,
                match_artist_key="eagles", match_song_key="hotel-california", matched_at=CHECKED,
                ug_checked_at=CHECKED)
    lib.displays[hotel.key] = hotel.display
    add_pin(lib.overrides_file, hotel.display, [f"{UG}/eagles/hotel-california-chords-{TABS[0]}"])
    add_block(lib.overrides_file, int(TABS[5]))

    # 2. In review: candidates the index has, one it no longer has, a catch-all's, a step of no words, one with no keys
    candidates = [
        {"artist_key": "soda-stereo", "song_key": "de-musica-ligera", "score": 88.6, "step": "fuzzy_artist"},
        {"artist_key": "soda-stereo-tribute", "song_key": "de-musica-ligera-live", "score": 80.2,
         "step": "title_only"},
        {"artist_key": "misc-originals", "song_key": "de-musica-ligera", "score": 79.5, "step": "catch_all"},
        {"artist_key": "soda", "song_key": "musica", "score": None, "step": "a-new-step"},
        {"artist_key": "", "song_key": "de-musica-ligera", "score": 70, "step": "exact"},
    ]
    lib.song("Soda Stereo", "De Música Ligera", added="2026-10-02T00:00:00Z", status="wanted", review=True,
             match_decision="review", match_step="fuzzy_artist", match_score=88.6, match_candidates=candidates,
             matched_at=CHECKED)

    # 3. Not found, a wanted song: its search and buy links, MuseScore's pages of its title
    nobody = lib.song("Nobody Band", "Unknown Song", added="2026-10-03T00:00:00Z", status="wanted",
                      match_decision="not_found", matched_at=CHECKED, lyrics_status="missing", lyrics_at=CHECKED)
    _index(conn, (3101, "nobody-band", "another-song", "chords"))
    kv_set(conn, f"ug:artist_page_checked:{nobody.id}", CHECKED)  # its artist's page: read again after 30 days

    # 4. Fetched, no sheet: for buying; the misses of gtptabs.com and harptabs.com, and a pick that is no miss
    creep = lib.song("Radiohead", "Creep", added="2026-10-04T00:00:00Z", status="wanted", match_decision="accept",
                     match_step="artist_page", match_artist_key="radiohead", match_song_key="creep", matched_at=CHECKED,
                     ug_checked_at=CHECKED, ug_dirty=False, lyrics_status="instrumental", lyrics_at=CHECKED,
                     lacuerda_checked_at=CHECKED)
    kv_set(conn, f"gtptabs:checked:{creep.id}", CHECKED)
    kv_set(conn, f"harptabs:checked:{creep.id}", "2026-10-21T09:30:00Z")
    kv_set(conn, f"gametabs:checked:{creep.id}:pick", "x")
    kv_set(conn, f"ug:artist_page_checked:{creep.id}", CHECKED)

    # 5. Fetched but dirty: caracole fetches it first
    oasis = lib.song("Oasis", "Wonderwall", added="2026-10-05T00:00:00Z", status="wanted", match_decision="accept",
                     match_artist_key="oasis", match_song_key="wonderwall", matched_at=CHECKED,
                     ug_checked_at=CHECKED, ug_dirty=True)
    kv_set(conn, f"gametabs:checked:{oasis.id}", CHECKED)

    # 6. A sheet picked on LaCuerda, still to come; lyrics from Megalobiz, which ask a link back
    camaron = lib.song("Estopa", "Como Camarón", added="2026-10-06T00:00:00Z", status="wanted",
                       match_decision="not_found", matched_at=CHECKED, lyrics_status="found", lyrics_at=CHECKED,
                       lyrics_json=json.dumps({"provider": "megalobiz", "plain": "Como camarón",
                                               "url": "https://megalobiz.com/lrc/maker/estopa-como-camaron.123"}))
    _write(cfg, camaron, "lyrics.txt")
    add_lacuerda(lib.overrides_file, camaron.display, "https://acordes.lacuerda.net/estopa/como_camaron")

    # 7. Ignored, with a sheet kept
    photo = lib.song("Nickelback", "Photograph", added="2026-10-07T00:00:00Z", status="found")
    sheet = _version(conn, photo, "ug", 5001, "sheet", "chords", url=f"{UG}/nickelback/photograph-chords-5001")
    _keep(conn, cfg, photo, sheet, "sheet.txt")
    add_ignore(lib.overrides_file, photo.display)

    # 8. Chinese: its names in either script, its progressions
    zebra = lib.song("宋冬野", "斑马斑马", added="2026-10-08T00:00:00Z", status="found")
    sheet = _version(conn, zebra, "ug", 6001, "sheet", "chords", raw={"tonality_name": "C"},
                     url=f"{UG}/song-dongye/banma-banma-chords-6001")
    _keep(conn, cfg, zebra, sheet, "sheet.txt", POP.encode())
    _write(cfg, zebra, "sheet.html", "sheet.cho")
    kv_set_json(conn, f"render:{zebra.id}", {"script": "simplified", "transpose": 0})
    kv_set_json(conn, f"render:{zebra.id}:phone", {"unit": "x", "build": "y", "script": "simplified"})

    # 9. UG's Ukulele Chords as its sheet
    rainbow = lib.song("Israel Kamakawiwo'ole", "Over the Rainbow", added="2026-10-09T00:00:00Z", status="found")
    sheet = _version(conn, rainbow, "ug", 7001, "sheet", "ukulele",
                     url=f"{UG}/israel-kamakawiwoole/over-the-rainbow-ukulele-7001")
    _keep(conn, cfg, rainbow, sheet, "sheet.txt")
    _write(cfg, rainbow, "sheet.html", "sheet.pdf", "sheet.cho")

    # 10. An auto sheet alone, from audio taken from YouTube; gametabs.net's tab
    lost = lib.song("Unknown Artist", "Lost Song", added="2026-10-10T00:00:00Z", status="found",
                    lyrics_status="found", lyrics_json=json.dumps({"provider": "lrclib", "plain": "la"}))
    auto = _version(conn, lost, "auto", "auto", "sheet", "auto",
                    raw={"youtube": {"id": "abcdefghijk", "title": "Lost Song", "channel": "Somebody"}})
    _keep(conn, cfg, lost, auto, "sheet (auto).txt")
    game = _version(conn, lost, "gametabs", 801, "guitar", "gametab", url="https://gametabs.net/x/801")
    _keep(conn, cfg, lost, game, "gametab-1.txt")
    _write(cfg, lost, "sheet (auto).html", "lyrics.txt")

    # 11. Your own version: a move from the sheet (t=), and one kept by its key, the PDF made 5 up
    letitbe = lib.song("The Beatles", "Let It Be", added="2026-10-11T00:00:00Z", status="found")
    sheet = _version(conn, letitbe, "ug", 9001, "sheet", "chords", url=f"{UG}/the-beatles/let-it-be-chords-9001")
    _keep(conn, cfg, letitbe, sheet, "sheet.txt", PROGRESSIONS.encode())
    put_song_entries(lib.overrides_file, letitbe.display, {"transpose": 2})
    add_version(lib.overrides_file, letitbe.display, "t=-3&mode=dorian")
    queen = lib.song("Queen", "Bohemian Rhapsody", added="2026-10-12T00:00:00Z", status="found")
    sheet = _version(conn, queen, "ug", 9101, "sheet", "chords", url=f"{UG}/queen/bohemian-rhapsody-chords-9101")
    _keep(conn, cfg, queen, sheet, "sheet.txt")
    add_version(lib.overrides_file, queen.display, "key=Gm&mode=dorian&capo=0")
    kv_set_json(conn, f"render:{queen.id}", {"transpose": 5})

    # 12. Its audio a purchase, no sheet yet
    roads = lib.song("Portishead", "Roads", added="2026-10-13T00:00:00Z", status="wanted",
                     match_decision="not_found", matched_at=CHECKED)
    conn.execute("UPDATE songs SET audio_path = 'Portishead/Dummy/Roads.flac' WHERE id = ?", (roads.id,))

    # 13. Accepted, fetched, its index tabs no chords: its artist's page read again after 30 days
    blur = lib.song("Blur", "Song 2", added="2026-10-14T00:00:00Z", status="wanted", match_decision="accept",
                    match_step="exact", match_artist_key="blur", match_song_key="song-2", matched_at=CHECKED,
                    ug_checked_at=CHECKED, ug_dirty=False)
    _index(conn, (3201, "blur", "song-2", "tabs"))
    kv_set(conn, f"ug:artist_page_checked:{blur.id}", CHECKED)

    # 14. Its match undone (rejected, say), still keeping the tab it found: the next fetch drops it
    muse = lib.song("Muse", "Uprising", added="2026-10-15T00:00:00Z", status="wanted", match_decision="not_found",
                    matched_at=CHECKED)
    tab = _version(conn, muse, "ug", 3301, "guitar", "tabs", url=f"{UG}/muse/uprising-tabs-3301")
    _keep(conn, cfg, muse, tab, "tab.txt")
    conn.execute("UPDATE versions SET gone = 2 WHERE id = ?", (tab,))

    # Progressions, as each song's last render read its sheet
    from caracole.progressions import record

    record(conn, letitbe.id, PROGRESSIONS, "C")
    record(conn, zebra.id, POP, "C")
    record(conn, hotel.id, POP, "C")
    _settle(conn, lib)
    return lib


def build_partial(conn, cfg) -> Library:
    """The full library with Ultimate Guitar's index read in part: no song not found is for buying."""
    lib = build_full(conn, cfg)
    kv_delete(conn, "ug:index:built_at")
    return lib


def _settle(conn, lib: Library) -> None:
    """Every stamp of the library made alike, whenever it is built, and the phone's overrides of overrides.toml."""
    conn.execute("UPDATE songs SET created_at = ?, updated_at = ?", (STAMP, STAMP))
    conn.execute("UPDATE files SET created_at = ?", (STAMP,))
    conn.execute("UPDATE versions SET fetched_at = ?", (STAMP,))
    conn.execute("DELETE FROM phone_overrides")
    for row in phone_rows(load_overrides(lib.overrides_file), lib.displays):
        conn.execute("INSERT INTO phone_overrides (tbl, key, written, value) VALUES (?, ?, ?, ?)",
                     (row["tbl"], row["key"], row["written"], row["value"]))


def phone_rows(o, displays: dict[str, str]) -> list[dict[str, str]]:
    """The phone's ``phone_overrides`` rows of ``o`` (phone.sql): each song's tables (and ``ignore``) by identity key,
    written as its display, ``block`` by tab id."""
    rows = []
    for key in sorted({k for t in SONG_TABLES for k in getattr(o, t)} | set(o.ignore)):
        entries = song_entries(o, key)
        for table in (*SONG_TABLES, "ignore"):
            if table in entries:
                rows.append({"tbl": table, "key": key, "written": displays[key],
                             "value": canonical.dumps(entries[table])})
    for tab in sorted(o.block):
        rows.append({"tbl": "block", "key": str(tab), "written": str(tab), "value": canonical.dumps(True)})
    return rows


LIBRARIES: dict[str, Callable[..., Library]] = {"full": build_full, "partial": build_partial}


def _off(cfg, names: tuple[str, ...]):
    """``cfg`` with the providers ``names`` turned off."""
    if not names:
        return cfg
    providers = {name: dataclasses.replace(p, enabled=False) if name in names else p
                 for name, p in cfg.providers.items()}
    return dataclasses.replace(cfg, providers=providers)


def _search(cfg, q: str) -> dict[str, Any]:
    """/api/search's answer to ``q`` over the library of ``cfg``, as caracole serve gives it (no LaCuerda search, no
    YouTube)."""
    from caracole.web.app import WebApp
    from caracole.web.jobs import JobQueue
    from test_web_app import ALLOWED, get

    def runner(args, emit):  # nothing is queued by a read
        raise AssertionError(f"a search queued {args}")

    app = WebApp(cfg, JobQueue(runner, limit=1), allowed=ALLOWED, csrf="tok", searches_lacuerda=False,
                 searches_youtube=False)
    answer = get(app, f"/api/search?{urlencode({'q': q, 'box': 'corpus'})}", **{"sec-fetch-site": "same-origin"})
    assert answer.status == 200, answer.body
    return json.loads(answer.body)


# Queries of a progression, typed and named, the same in another rotation, one no song plays, and words.
QUERIES = ("I V vi IV", "vi IV I V", "the pop progression", "I–V–vi–IV", "vi IV I V creep", "ii V I", "I IV V",
           "Let It Be", "creep")
# Cards of a few songs, as /jobs.json asks for one: their artists.
FEW = (("Eagles",), ("Soda Stereo", "Estopa"), ("宋冬野",))


def records(tmp_path: Path) -> list[dict[str, Any]]:
    from caracole.config import load_config
    from caracole.db import connect

    out: list[dict[str, Any]] = []
    for name, build in LIBRARIES.items():
        home = tmp_path / name
        cfg = load_config(None, env={"HOME": str(home / "home"), "STATE_DIRECTORY": str(home / "state"),
                                     "CACHE_DIRECTORY": str(home / "cache")})
        cfg.library_dir.mkdir(parents=True, exist_ok=True)
        (home / "state").mkdir(parents=True, exist_ok=True)
        conn = connect(home / "state" / "caracole.sqlite")
        with mock.patch("caracole.songs.utc_now_iso", lambda: STAMP):
            lib = build(conn, cfg)
        overrides = load_overrides(lib.overrides_file)
        out.append({"library": name, "fixture": dump_fixture(conn, cfg.library_dir),
                    "overrides": lib.overrides_file.read_text("utf-8")})
        songs = list_songs(conn)
        cases: list[tuple[datetime, tuple[str, ...], list[Any] | None]] = [(NOW, (), None)]
        if name == "full":
            cases += [(LATER, (), None), (NOW, ("musescore",), None), (NOW, ("gtptabs", "harptabs", "lacuerda"), None)]
            cases += [(NOW, (), [s for s in songs if s.artist in few]) for few in FEW]
        for now, off, only in cases:
            cards = song_cards(conn, _off(cfg, off), overrides, now, only)
            out.append({"fn": "caracole.library_page.song_cards", "library": name, "now": _stamp(now),
                        "songs": None if only is None else [s.id for s in only], "config": {"off": list(off)},
                        "out": cards})
        html = build_library_page(conn, cfg, overrides, NOW)
        data = json.loads(html.split('<script type="application/json" id="songs">', 1)[1].split("</script>", 1)[0])
        out.append({"fn": "caracole.library_page.build_library_page", "library": name, "now": _stamp(NOW),
                    "out": {k: v for k, v in data.items() if k != "sites"}})
        if name == "full":
            for q in QUERIES:
                answer = _search(cfg, q)
                out.append({"fn": "caracole.web.app.WebApp.handle", "library": name,
                            "args": ["GET", f"/api/search?{urlencode({'q': q, 'box': 'corpus'})}"],
                            "out": {"progression": answer["progression"],
                                    "library": [[r["id"], r["via"], r["score"]] for r in answer["library"]]}})
        conn.close()
    return out


def _stamp(t: datetime) -> str:
    return t.strftime("%Y-%m-%dT%H:%M:%SZ")


def test_cards_full_jsonl_is_song_cards_over_each_library(tmp_path):
    check(CARDS, jsonl(records(tmp_path), corpus="web/cards_full", made_by=MADE_BY))


def test_the_libraries_hold_what_each_card_says_something_of(tmp_path):
    # Every field a card may hold is said by some song of the libraries: none is checked only in its default.
    made = records(tmp_path)
    found = [r for r in made if r.get("fn") == "caracole.library_page.song_cards"]
    cards = [c for r in found for c in r["out"]]
    said = {field for c in cards for field, value in c.items() if value not in (None, [], False, 0, "")}
    assert {"key", "transpose", "lyricsFrom", "auto", "instruments", "versions", "autoSheet", "museScore", "links",
            "buy", "lacuerda", "lacuerdaVersions", "lacuerdaSheet", "candidates", "notFound", "hanzi",
            "progressions", "youtubeSheet", "initials", "sites"} <= said
    files = [f for c in cards for f in c["files"]]
    assert {"guitarPage", "harmonicaPage", "download", "version"} <= {k for f in files for k in f}
    states = {m["state"] for c in cards for m in c["sites"]}
    assert states == {"have", "none", "unasked"}
    progression = [r for r in made if r.get("fn") == "caracole.web.app.WebApp.handle"]
    assert any(r["out"]["progression"] and r["out"]["progression"]["songs"] for r in progression)
    assert any(via == "progression" for r in progression for _, via, _ in r["out"]["library"])


def test_the_corpus_is_the_same_each_time_it_is_made(tmp_path):
    first = jsonl(records(tmp_path / "a"), corpus="web/cards_full", made_by=MADE_BY)
    second = jsonl(records(tmp_path / "b"), corpus="web/cards_full", made_by=MADE_BY)
    assert first == second
