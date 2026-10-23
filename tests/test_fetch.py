"""Per-song UG fetch, rank and keep (plan Task 15, amendment A6).

A fake Ultimate Guitar answers through ``httpx.MockTransport``, keyed by URL,
the way the live site does: a slugged tab only at its slugged URL, and UG's
404 page (which has no js-store) for anything else.
"""

from __future__ import annotations

import dataclasses
import json
import os
import re
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest
from conftest import add_song
from helpers.ug_pages import (
    ARTIST_FILTERS,
    BANMA_UG,
    DONG_XIAOJIE_LINES,
    SONG_DONGYE_URL,
    artist_path,
    make_tab_page_html,
    name_stripped,
    song_dongye_chords,
    song_dongye_page_html,
    song_dongye_sheet,
    song_dongye_tab,
    store_page_html,
    version_dict,
)

import caracole.http
from caracole.config import MatchPolicy, ProviderPolicy, RankPolicy
from caracole.db import kv_get, kv_set
from caracole.http import PoliteClient, ProviderBlocked
from caracole.library import drop_file, keep_file, kept_files, song_dir
from caracole.lyrics import Lyrics
from caracole.match import match_all
from caracole.normalize import slug_key
from caracole.overrides import Overrides, load_overrides
from caracole.render import render_all
from caracole.songs import get_song, update_song
from caracole.ug.artist import artist_page_url
from caracole.ug.fetch import (
    FetchContext,
    FetchStats,
    SongFetchOutcome,
    artist_is_known,
    fetch_songs,
    needs_artist_page,
    pasted_page_problem,
    process_song,
    rescore_kept_sheets,
    songs_to_fetch,
)
from caracole.ug.lookup import (
    IndexTab,
    artist_tabs,
    index_tab,
    learned_artist_url,
    remember_artist_url,
    tab_url_for,
)
from caracole.ug.page import strip_markup
from caracole.versions import (
    get_version,
    picks,
    set_coverage,
    set_picks,
    song_versions,
    upsert_version,
)

NOW = datetime(2026, 10, 18, 3, 30, tzinfo=UTC)
TAB = "https://tabs.ultimate-guitar.com/tab/"
SODA_URL = "https://www.ultimate-guitar.com/artist/soda_stereo_2946"
BANMA_ARTIST = "https://www.ultimate-guitar.com/artist/song_dongye_1234567"
NOT_FOUND = (
    '<!DOCTYPE html>\n<html><head><meta charset="utf-8"><title>Oops! We couldn\'t find that page.</title>'
    "</head><body><h1>Oops!</h1></body></html>\n"
)
UG_TYPES = {"chords": "Chords", "tabs": "Tabs", "guitar-pro": "Pro", "power": "Power", "official": "Official"}

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


def index(conn, *rows):
    """Insert ug_index rows ``(tab_id, artist_key, song_key, type)`` with their sitemap paths."""
    conn.executemany(
        "INSERT INTO ug_index (tab_id, artist_key, song_key, type, sitemap, first_seen, path) "
        "VALUES (?, ?, ?, ?, 'last', '2026-10-01T00:00:00Z', ?)",
        [(t, a, s, k, f"{a}/{s}-{k}-{t}") for t, a, s, k in rows],
    )


def slugged(tab_id, kind="chords", artist="soda-stereo", song="persiana-americana"):
    return f"{TAB}{artist}/{song}-{kind}-{tab_id}"


def v(tab_id, kind="chords", **kw):
    """A Persiana Americana version as UG lists it, at its slugged URL unless ``tab_url`` is given."""
    kw.setdefault("tab_url", slugged(tab_id, kind))
    kw.setdefault("song_id", 67624)
    return version_dict(tab_id, type=UG_TYPES.get(kind, kind), song="Persiana Americana", artist="Soda Stereo", **kw)


def sheet(tag, lines):
    """A chords-over-lyrics sheet in UG markup; the line ``tag`` tells which version it is."""
    rows = ["[Intro]", tag, ""]
    for line in lines:
        rows += ["[tab][ch]Am[/ch]       [ch]F[/ch]       [ch]C[/ch]", f"{line}[/tab]"]
    return "\r\n".join(rows)


class FakeUG:
    """Ultimate Guitar through a transport: known pages by URL, UG's 404 page for the rest."""

    def __init__(self):
        self.pages: dict[str, tuple[int, str]] = {}
        self.moved: dict[str, str] = {}
        self.requests: list[str] = []

    def add(self, url, html, status=200):
        self.pages[str(httpx.URL(url))] = (status, html)

    def redirect(self, url, location):
        """Answer ``url`` with a 301 to ``location``."""
        self.moved[str(httpx.URL(url))] = location

    def tab(self, tab, versions=(), *, content=None, meta=None, artist_url=SODA_URL):
        """Serve a tab page at the tab's own ``tab_url``."""
        self.add(tab["tab_url"], make_tab_page_html(tab, list(versions), content=content, meta=meta,
                                                    artist_url=artist_url))

    def handler(self, request):
        url = str(request.url)
        self.requests.append(url)
        if url in self.moved:
            return httpx.Response(301, headers={"Location": self.moved[url]})
        status, html = self.pages.get(url, (404, NOT_FOUND))
        return httpx.Response(status, text=html)

    def client(self, cache_dir, budget=60, *, now=NOW):
        """A client for one run at ``now``, which is also the age the HTTP cache is judged by."""
        return PoliteClient("ug", ProviderPolicy(budget=budget, delay=(0.0, 0.0)), cache_dir,
                            user_agent="caracole-test", transport=httpx.MockTransport(self.handler),
                            sleep=lambda s: None, wall_clock=lambda: now)


def lyrics_json(plain):
    record = {"id": 1, "plainLyrics": plain, "syncedLyrics": None, "instrumental": False, "duration": 213.0}
    return Lyrics.from_record(record).to_json()


def accepted(conn, artist="Soda Stereo", title="Persiana Americana", akey="soda-stereo",
             skey="persiana-americana", *, plain=LYRICS, **kw):
    """A song the matcher accepted, with LRCLIB lyrics (``plain=None`` leaves them pending)."""
    song = add_song(conn, artist, title, **kw)
    fields = {"match_decision": "accept", "match_step": "exact", "match_score": 100.0,
              "match_artist_key": akey, "match_song_key": skey, "ug_dirty": True}
    if plain is not None:
        fields.update(lyrics_status="found", lyrics_json=lyrics_json(plain))
    update_song(conn, song.id, **fields)
    return get_song(conn, song.id)


def context(conn, client, tmp_path, overrides=None, *, now=NOW, **kw):
    return FetchContext(conn=conn, client=client, overrides=overrides or Overrides(), rank=RankPolicy(),
                        library_dir=tmp_path / "lib", now=now, **kw)


def read(tmp_path, song, name):
    """A kept file's exact text (UG's \\r\\n line ends included)."""
    return (song_dir(tmp_path / "lib", song) / name).read_bytes().decode("utf-8")


def coverages(conn, song):
    return {int(r.tab_id): r.coverage for r in song_versions(conn, song.id)}


def pick_ids(conn, song, *kinds):
    return [int(r.tab_id) for r in picks(conn, song.id, kinds)]


def soda_chords(ug, *entries):
    """Soda Stereo's chords list on its UG artist page; by default it lists only "Signos" chords.

    A song whose index lists no chords tab has its sheet looked for there.
    """
    entries = entries or (version_dict(901, song="Signos", artist="Soda Stereo", tab_url=slugged(901, song="signos")),)
    ug.add(artist_list(SODA_URL), artist_page(2946, "Soda Stereo", list(entries)))


def three_chords(ug):
    """101 is the best rated but charts only the first verse; 102 and 103 are complete."""
    a = v(101, version=1, rating=4.9, votes=100)
    b = v(102, version=2, rating=4.6, votes=50)
    c = v(103, version=3, rating=4.2, votes=20)
    ug.tab(a, [b, c], content=sheet("sheet 101", LINES[:3]))
    ug.tab(b, [a, c], content=sheet("sheet 102", LINES))
    ug.tab(c, [a, b], content=sheet("sheet 103", LINES))


# --- lookup helpers -------------------------------------------------------------


def test_tab_url_for_uses_the_slugged_path_else_bare(conn):
    index(conn, (1081462, "soda-stereo", "persiana-americana", "tabs"))
    assert tab_url_for(conn, 1081462) == f"{TAB}soda-stereo/persiana-americana-tabs-1081462"
    assert tab_url_for(conn, 85053) == f"{TAB}85053"


def test_index_tab_reads_one_row_with_its_variant_label(conn):
    index(conn, (3, "oasis", "wonderwall-intro", "tabs"))
    assert index_tab(conn, 3) == IndexTab(3, "tabs", "wonderwall-intro", "intro", "oasis/wonderwall-intro-tabs-3")
    assert index_tab(conn, 4) is None


def test_artist_tabs_lists_slugged_tabs_oldest_first(conn):
    index(conn, (10, "soda-stereo", "persiana-americana", "tabs"), (7, "soda-stereo", "signos", "chords"),
          (8, "other", "song", "chords"))
    assert artist_tabs(conn, "soda-stereo", limit=5) == [
        IndexTab(7, "chords", "signos", None, "soda-stereo/signos-chords-7"),
        IndexTab(10, "tabs", "persiana-americana", None, "soda-stereo/persiana-americana-tabs-10"),
    ]
    assert [t.tab_id for t in artist_tabs(conn, "soda-stereo", limit=1)] == [7]


# --- the sheet slot -------------------------------------------------------------------


def test_sheet_chosen_by_coverage_then_rating(conn, tmp_path):
    song = accepted(conn)
    index(conn, *[(t, "soda-stereo", "persiana-americana", "chords") for t in (101, 102, 103)])
    ug = FakeUG()
    three_chords(ug)

    process_song(context(conn, ug.client(tmp_path / "cache"), tmp_path), song)

    text = read(tmp_path, song, "sheet.txt")
    assert "sheet 102" in text and LINES[9] in text and "[ch]" not in text and "[tab]" not in text
    assert coverages(conn, song) == {101: pytest.approx(0.3), 102: 1.0, 103: 1.0}
    assert pick_ids(conn, song, "chords") == [102]
    doc = json.loads(read(tmp_path, song, "sheet.json"))
    assert doc["url"] == f"{TAB}soda-stereo/persiana-americana-chords-102"
    assert doc["version"]["id"] == 102 and doc["version"]["rating"] == 4.6
    assert doc["content"].startswith("[Intro]\r\nsheet 102\r\n")


def test_only_top_three_sheets_scored(conn, tmp_path):
    song = accepted(conn)
    index(conn, *[(t, "soda-stereo", "persiana-americana", "chords") for t in range(201, 206)])
    ug = FakeUG()
    ratings = {201: (3.5, 5), 202: (4.0, 5), 203: (4.7, 60), 204: (4.8, 80), 205: (4.9, 100)}
    tabs = {t: v(t, version=t - 200, rating=r, votes=n) for t, (r, n) in ratings.items()}
    for t, tab in tabs.items():
        ug.tab(tab, [o for o in tabs.values() if o is not tab], content=sheet(f"sheet {t}", LINES))

    process_song(context(conn, ug.client(tmp_path / "cache"), tmp_path), song)

    # One page to rate them all (the lowest id), then the content of the three best rated.
    assert ug.requests == [slugged(201), slugged(205), slugged(204), slugged(203)]
    assert coverages(conn, song) == {201: None, 202: None, 203: 1.0, 204: 1.0, 205: 1.0}
    assert "sheet 205" in read(tmp_path, song, "sheet.txt")


def test_own_tab_recorded_from_page_tab(conn, tmp_path):
    # The spike's tab 85053: UG's versions list leaves the page's own tab out.
    song = accepted(conn, "Soda Stereo", "De Música Ligera", "soda-stereo", "de-musica-ligera")
    index(conn, (85053, "soda-stereo", "de-musica-ligera", "chords"))
    dml = {"song": "De Música Ligera", "artist": "Soda Stereo", "song_id": 67588}
    own = version_dict(85053, version=2, rating=4.54038, votes=7,
                       tab_url=f"{TAB}soda-stereo/de-musica-ligera-chords-85053", **dml)
    others = [version_dict(85042, version=1, rating=4.83354, votes=277, **dml),
              version_dict(1601635, version=3, rating=4.85005, votes=81, **dml)]
    ug = FakeUG()
    ug.tab(own, others, content=sheet("sheet 85053", LINES))
    for o in others:  # served without version lists, so 85053 can only come from its own page
        ug.tab(o, [], content=sheet(f"sheet {o['id']}", LINES))

    process_song(context(conn, ug.client(tmp_path / "cache"), tmp_path), song)

    rows = {int(r.tab_id): (r.version, r.rating, r.votes, r.url) for r in song_versions(conn, song.id)}
    assert rows[85053] == (2, 4.54038, 7, f"{TAB}soda-stereo/de-musica-ligera-chords-85053")
    assert rows[85042] == (1, 4.83354, 277, f"{TAB}85042")
    assert set(rows) == {85053, 85042, 1601635}


def test_official_and_non_public_skipped(conn, tmp_path):
    song = accepted(conn)
    index(conn, (101, "soda-stereo", "persiana-americana", "chords"))
    official = v(3891914, "official", rating=4.84, votes=77)  # UG marks Official versions "public" too
    hidden = v(104, access="private", rating=5.0, votes=500)
    public = v(102, rating=4.0, votes=10)
    ug = FakeUG()
    ug.tab(v(101, rating=3.0, votes=10), [official, hidden, public], content=sheet("sheet 101", LINES))
    ug.tab(public, [], content=sheet("sheet 102", LINES))
    ug.tab(hidden, [], content=sheet("sheet 104", LINES))
    ug.tab(official, [], content=sheet("official", LINES))

    process_song(context(conn, ug.client(tmp_path / "cache"), tmp_path), song)

    assert {int(r.tab_id) for r in song_versions(conn, song.id, include_gone=True)} == {101, 102}
    assert slugged(104) not in ug.requests and slugged(3891914, "official") not in ug.requests
    assert "sheet 102" in read(tmp_path, song, "sheet.txt")


@pytest.mark.parametrize("tab_url", [
    "https://tabs.ultimate-guitar.com/tab/download?id=102",  # robots.txt: Disallow /tab/download
    "https://tabs.ultimate-guitar.com/tab/print?id=102",  # robots.txt: Disallow /tab/print?
    "https://www.ultimate-guitar.com/pro/?tab_id=102",  # UG's paid app
])
def test_versions_whose_link_is_no_tab_page_are_never_fetched(conn, tmp_path, tab_url):
    song = accepted(conn)
    index(conn, (101, "soda-stereo", "persiana-americana", "chords"))
    odd = v(102, rating=5.0, votes=500, tab_url=tab_url)
    ug = FakeUG()
    ug.tab(v(101, rating=3.0, votes=10), [odd], content=sheet("sheet 101", LINES))

    process_song(context(conn, ug.client(tmp_path / "cache"), tmp_path), song)

    assert ug.requests == [slugged(101)]
    assert {int(r.tab_id) for r in song_versions(conn, song.id, include_gone=True)} == {101}


MOVED = "https://www.ultimate-guitar.com/tab/soda-stereo/persiana-americana-chords-{}"  # UG moved tab pages


def test_links_that_all_changed_shape_are_an_error_not_a_miss(conn, tmp_path):
    # Review Focus 4: shape drift is a provider error. Not one version links to a tab page any more.
    song = accepted(conn)
    index(conn, (101, "soda-stereo", "persiana-americana", "chords"))
    ug = FakeUG()
    ug.add(slugged(101), make_tab_page_html(v(101, tab_url=MOVED.format(101)),
                                            [v(102, version=2, tab_url=MOVED.format(102))],
                                            content=sheet("sheet 101", LINES), artist_url=SODA_URL))

    stats = fetch_songs(context(conn, ug.client(tmp_path / "cache"), tmp_path), [song])

    assert (stats.songs_done, stats.songs_failed) == (0, 1)
    failed = get_song(conn, song.id)  # neither found nor checked: never on the buy list
    assert (failed.status, failed.ug_dirty, failed.ug_checked_at) == ("wanted", True, None)


def test_a_pages_own_tab_is_recorded_at_the_address_it_was_read_from(conn, tmp_path):
    song = accepted(conn)
    index(conn, (101, "soda-stereo", "persiana-americana", "chords"))
    own, other = v(101, rating=4.9, votes=100, tab_url=MOVED.format(101)), v(102, version=2, rating=4.0, votes=5)
    ug = FakeUG()
    ug.add(slugged(101), make_tab_page_html(own, [other], content=sheet("sheet 101", LINES), artist_url=SODA_URL))
    ug.tab(other, [own], content=sheet("sheet 102", LINES))

    process_song(context(conn, ug.client(tmp_path / "cache"), tmp_path), song)

    assert {int(r.tab_id): r.url for r in song_versions(conn, song.id)} == {101: slugged(101), 102: slugged(102)}
    assert "sheet 101" in read(tmp_path, song, "sheet.txt")


# --- the tab slot ---------------------------------------------------------------------


def test_ultimate_guitars_guitar_pro_and_power_tab_versions_are_never_read_nor_picked(conn, tmp_path):
    # caracole picks no Guitar Pro or Power Tab version on Ultimate Guitar for you to download: the index's
    # tabs of those types cost no request, and no version of theirs is recorded for the song.
    song = accepted(conn)
    index(conn, (301, "soda-stereo", "persiana-americana", "guitar-pro"),
          (303, "soda-stereo", "persiana-americana", "power"),
          (401, "soda-stereo", "persiana-americana", "tabs"))
    ug = FakeUG()
    ug.tab(v(301, "guitar-pro", rating=4.5, votes=20), meta={"fileExtension": ".gp5", "duration": 213})
    ug.tab(v(303, "power", rating=4.3, votes=15), meta={"fileExtension": ".ptb"})
    ug.tab(v(401, "tabs"), content=riff("tab 401"))
    soda_chords(ug)  # the index lists no chords of the song, so the artist's chords list is read

    out = process_song(context(conn, ug.client(tmp_path / "cache"), tmp_path), song)

    assert out.tab == 401 and "tab 401" in read(tmp_path, song, "tab.txt")
    assert sorted(ug.requests) == sorted([slugged(401, "tabs"), artist_list(SODA_URL)])
    assert {r.kind for r in song_versions(conn, song.id, include_gone=True)} == {"tabs"}
    assert not list((tmp_path / "lib").rglob("guitar-*"))


def test_a_pin_of_a_guitar_pro_page_pins_nothing_and_costs_no_request(conn, tmp_path):
    # A [pin] written when caracole still picked Guitar Pro versions on Ultimate Guitar: the index says what
    # it is, so its page isn't asked for, and the song's slots are filled as if it weren't there.
    song = accepted(conn)
    index(conn, (101, "soda-stereo", "persiana-americana", "chords"),
          (301, "soda-stereo", "persiana-americana", "guitar-pro"))
    ug = FakeUG()
    ug.tab(v(101), content=sheet("sheet 101", LINES))
    ug.tab(v(301, "guitar-pro"), meta={"fileExtension": ".gp5"})
    pinned = Overrides(pin={song.key: (301,)})

    out = process_song(context(conn, ug.client(tmp_path / "cache"), tmp_path, pinned), song)

    assert out.sheet == 101 and ug.requests == [slugged(101)]
    assert {r.kind for r in song_versions(conn, song.id, include_gone=True)} == {"chords"}


def test_a_pin_ultimate_guitar_answers_with_a_guitar_pro_page_pins_nothing(conn, tmp_path):
    # A bare id the index doesn't know: its page tells, once read, and it is no candidate of any slot.
    song = accepted(conn)
    index(conn, (101, "soda-stereo", "persiana-americana", "chords"))
    ug = FakeUG()
    ug.tab(v(101), content=sheet("sheet 101", LINES))
    ug.tab(v(3333333, "guitar-pro", tab_url=f"{TAB}3333333"), meta={"fileExtension": ".gp5"})
    pinned = Overrides(pin={song.key: (3333333,)})

    out = process_song(context(conn, ug.client(tmp_path / "cache"), tmp_path, pinned), song)

    assert out.sheet == 101 and pick_ids(conn, song, "chords") == [101]
    assert {r.kind for r in song_versions(conn, song.id, include_gone=True)} == {"chords"}


def riff(tag):
    return f"[tab]e|-----0-----3-----|\r\nB|---1---1-------1-|[/tab]\r\n{tag}"


def test_tab_kept(conn, tmp_path):
    song = accepted(conn)
    index(conn, (401, "soda-stereo", "persiana-americana", "tabs"), (402, "soda-stereo", "persiana-americana", "tabs"))
    ug = FakeUG()
    low, high = v(401, "tabs", rating=4.0, votes=10), v(402, "tabs", version=2, rating=4.8, votes=40)
    ug.tab(low, [high], content=riff("tab 401"))
    ug.tab(high, [low], content=riff("tab 402"))
    soda_chords(ug)

    out = process_song(context(conn, ug.client(tmp_path / "cache"), tmp_path), song)

    assert out.tab == 402 and pick_ids(conn, song, "tabs") == [402]
    assert read(tmp_path, song, "tab.txt") == "e|-----0-----3-----|\r\nB|---1---1-------1-|\r\ntab 402"
    doc = json.loads(read(tmp_path, song, "tab.json"))
    assert (doc["version"]["id"], doc["url"], doc["content"]) == (402, slugged(402, "tabs"), riff("tab 402"))
    # 401's page, read first, names the artist page, whose chords list has no "Persiana Americana".
    assert ug.requests == [slugged(401, "tabs"), artist_list(SODA_URL), slugged(402, "tabs")]


# --- finishing a song -------------------------------------------------------------------


def test_finished_song_is_found_clean_and_described(conn, tmp_path):
    song = accepted(conn)
    index(conn, (101, "soda-stereo", "persiana-americana", "chords"), (401, "soda-stereo", "persiana-americana", "tabs"))
    ug = FakeUG()
    ug.tab(v(101), content=sheet("sheet 101", LINES))
    ug.tab(v(401, "tabs"), content=riff("tab 401"))

    process_song(context(conn, ug.client(tmp_path / "cache"), tmp_path), song)

    done = get_song(conn, song.id)
    assert (done.status, done.ug_dirty, done.ug_checked_at) == ("found", False, "2026-10-18T03:30:00Z")
    info = json.loads(read(tmp_path, song, "info.json"))
    assert info["status"] == "found"
    assert sorted(f["name"] for f in info["files"]) == ["sheet.json", "sheet.txt", "tab.json", "tab.txt"]


def test_song_without_any_sheet_stays_wanted_but_is_checked(conn, tmp_path):
    song = accepted(conn)
    index(conn, (401, "soda-stereo", "persiana-americana", "tabs"))
    ug = FakeUG()
    ug.tab(v(401, "tabs"), content=riff("tab 401"))

    process_song(context(conn, ug.client(tmp_path / "cache"), tmp_path), song)

    done = get_song(conn, song.id)
    assert (done.status, done.ug_dirty, done.ug_checked_at) == ("wanted", False, "2026-10-18T03:30:00Z")


# --- deleted tabs, pins and blocks ----------------------------------------------------------


def test_deleted_tab_404_skipped(conn, tmp_path):
    song = accepted(conn)
    index(conn, (501, "soda-stereo", "persiana-americana", "chords"), (502, "soda-stereo", "persiana-americana", "chords"))
    ug = FakeUG()  # 501 and 503 are gone: UG answers its 404 page, which has no js-store
    ug.tab(v(502, rating=4.2, votes=10), [v(503, version=2, rating=4.9, votes=90)], content=sheet("sheet 502", LINES))

    process_song(context(conn, ug.client(tmp_path / "cache"), tmp_path), song)

    assert "sheet 502" in read(tmp_path, song, "sheet.txt")
    gone = {int(r.tab_id): r.gone for r in song_versions(conn, song.id, include_gone=True)}
    assert gone == {501: True, 502: False, 503: True}
    assert slugged(503) in ug.requests  # it was the best rated, so its content was asked for
    assert get_song(conn, song.id).ug_dirty is False


def test_slugged_tabs_fetched_at_their_slugged_url(conn, tmp_path):
    # Live: /tab/1081462 answers 404; only /tab/soda-stereo/persiana-americana-tabs-1081462 has the page.
    song = accepted(conn)
    index(conn, (1081462, "soda-stereo", "persiana-americana", "tabs"))
    ug = FakeUG()
    ug.tab(v(1081462, "tabs", part="intro"), content=riff("intro riff"))
    soda_chords(ug)

    out = process_song(context(conn, ug.client(tmp_path / "cache"), tmp_path), song)

    assert out.tab == 1081462 and "intro riff" in read(tmp_path, song, "tab.txt")
    assert ug.requests == [f"{TAB}soda-stereo/persiana-americana-tabs-1081462", artist_list(SODA_URL)]


def test_pins_restrict_slot(conn, tmp_path):
    song = accepted(conn)
    index(conn, (601, "soda-stereo", "persiana-americana", "chords"), (602, "soda-stereo", "persiana-americana", "chords"),
          (603, "soda-stereo", "persiana-americana", "tabs"))
    best, pinned = v(601, rating=4.9, votes=100), v(602, version=2, rating=4.0, votes=10)
    ug = FakeUG()
    ug.tab(best, [pinned], content=sheet("sheet 601", LINES))
    ug.tab(pinned, [best], content=sheet("sheet 602", LINES))
    ug.tab(v(603, "tabs"), content=riff("tab 603"))
    overrides = Overrides(pin={song.key: (602,)})

    out = process_song(context(conn, ug.client(tmp_path / "cache"), tmp_path, overrides), song)

    assert "sheet 602" in read(tmp_path, song, "sheet.txt") and pick_ids(conn, song, "chords") == [602]
    assert out.tab == 603  # a pinned chords tab leaves the guitar slot alone
    assert ug.requests == [slugged(602), slugged(603, "tabs")]  # the pin at its slugged URL; 601 never read


def test_pinned_tab_outside_the_index_is_fetched_bare(conn, tmp_path):
    song = accepted(conn, "Soda Stereo", "De Música Ligera", "soda-stereo", "de-musica-ligera")
    pinned = version_dict(85053, version=2, rating=4.54, votes=7, song="De Música Ligera", artist="Soda Stereo")
    ug = FakeUG()
    ug.tab(pinned, content=sheet("sheet 85053", LINES))

    out = process_song(context(conn, ug.client(tmp_path / "cache"), tmp_path, Overrides(pin={song.key: (85053,)})), song)

    assert out.sheet == 85053 and ug.requests == [f"{TAB}85053"]


def pins_from_toml(tmp_path, display, *urls):
    """Overrides read from an overrides.toml that pins ``urls`` for the song ``display``."""
    path = tmp_path / "overrides.toml"
    path.write_text(f"[pin]\n{json.dumps(display)} = {json.dumps(list(urls))}\n", encoding="utf-8")
    return load_overrides(path)


def test_a_pinned_slugged_tab_outside_the_index_is_fetched_at_the_url_you_pasted(conn, tmp_path):
    # Live: a slugged tab answers 404 at its bare /tab/{id}. Tonight's sitemaps don't list it yet.
    song = accepted(conn)
    url = slugged(1081460)
    ug = FakeUG()
    ug.tab(v(1081460, rating=4.6, votes=12), content=sheet("sheet 1081460", LINES))
    overrides = pins_from_toml(tmp_path, "Soda Stereo - Persiana Americana", url)

    out = process_song(context(conn, ug.client(tmp_path / "cache"), tmp_path, overrides), song)

    assert out.sheet == 1081460 and "sheet 1081460" in read(tmp_path, song, "sheet.txt")
    assert ug.requests == [url]  # never the bare /tab/1081460
    assert [(r.tab_id, r.gone) for r in song_versions(conn, song.id, include_gone=True)] == [("1081460", False)]


def test_a_pasted_bare_url_of_a_slugged_tab_is_fetched_at_its_slugged_url(conn, tmp_path):
    song = accepted(conn)
    index(conn, (1081460, "soda-stereo", "persiana-americana", "chords"))
    ug = FakeUG()
    ug.tab(v(1081460), content=sheet("sheet 1081460", LINES))
    overrides = pins_from_toml(tmp_path, "Soda Stereo - Persiana Americana", f"{TAB}1081460")

    out = process_song(context(conn, ug.client(tmp_path / "cache"), tmp_path, overrides), song)

    assert out.sheet == 1081460 and ug.requests == [slugged(1081460)]


@pytest.mark.parametrize("closed", ["download", "print"])
def test_a_pasted_url_under_a_closed_path_is_never_requested(conn, tmp_path, closed):
    # robots.txt closes /tab/download and /tab/print; the pin falls back to the tab's own page.
    song = accepted(conn, "Soda Stereo", "De Música Ligera", "soda-stereo", "de-musica-ligera")
    pinned = version_dict(85053, version=2, rating=4.54, votes=7, song="De Música Ligera", artist="Soda Stereo")
    ug = FakeUG()
    ug.tab(pinned, content=sheet("sheet 85053", LINES))
    overrides = pins_from_toml(tmp_path, "Soda Stereo - De Música Ligera", f"{TAB}{closed}/85053")

    out = process_song(context(conn, ug.client(tmp_path / "cache"), tmp_path, overrides), song)

    assert out.sheet == 85053 and ug.requests == [f"{TAB}85053"]


def test_pins_keep_their_urls_in_pinned_order_around_blocked_ones(conn, tmp_path):
    song = accepted(conn)
    ug = FakeUG()
    ug.tab(v(1081460, rating=4.0, votes=5), content=sheet("sheet 1081460", LINES))
    ug.tab(v(1081470, rating=4.9, votes=90), content=sheet("sheet 1081470", LINES))
    toml = pins_from_toml(tmp_path, "Soda Stereo - Persiana Americana",
                          slugged(1081450), slugged(1081460), slugged(1081470))
    overrides = Overrides(pin=toml.pin, pin_urls=toml.pin_urls, block=frozenset({1081450}))

    out = process_song(context(conn, ug.client(tmp_path / "cache"), tmp_path, overrides), song)

    assert out.sheet == 1081460  # the first pin you haven't blocked, at its own URL
    assert ug.requests == [slugged(1081460), slugged(1081470)]


def test_blocked_ids_excluded(conn, tmp_path):
    song = accepted(conn)
    index(conn, (701, "soda-stereo", "persiana-americana", "chords"), (702, "soda-stereo", "persiana-americana", "chords"))
    blocked_best, ok = v(701, rating=4.9, votes=100), v(702, version=2, rating=4.2, votes=10)
    listed_blocked = v(703, version=3, rating=5.0, votes=300)
    ug = FakeUG()
    ug.tab(blocked_best, [ok, listed_blocked], content=sheet("sheet 701", LINES))
    ug.tab(ok, [blocked_best, listed_blocked], content=sheet("sheet 702", LINES))
    ug.tab(listed_blocked, [blocked_best, ok], content=sheet("sheet 703", LINES))
    overrides = Overrides(block=frozenset({701, 703}), pin={song.key: (703,)})  # a blocked pin is no pin

    out = process_song(context(conn, ug.client(tmp_path / "cache"), tmp_path, overrides), song)

    assert out.sheet == 702 and "sheet 702" in read(tmp_path, song, "sheet.txt")
    assert ug.requests == [slugged(702)]
    assert {int(r.tab_id) for r in song_versions(conn, song.id, include_gone=True)} == {702}


def test_kept_sheet_blocked_later_is_replaced(conn, tmp_path):
    song = accepted(conn)
    index(conn, (701, "soda-stereo", "persiana-americana", "chords"), (702, "soda-stereo", "persiana-americana", "chords"))
    best, other = v(701, rating=4.9, votes=100), v(702, version=2, rating=4.2, votes=10)
    ug = FakeUG()
    ug.tab(best, [other], content=sheet("sheet 701", LINES))
    ug.tab(other, [best], content=sheet("sheet 702", LINES))
    process_song(context(conn, ug.client(tmp_path / "cache"), tmp_path), song)
    assert "sheet 701" in read(tmp_path, song, "sheet.txt")

    update_song(conn, song.id, ug_dirty=True)  # you added 701 to [block]; the next run re-ranks
    out = process_song(context(conn, ug.client(tmp_path / "cache"), tmp_path, Overrides(block=frozenset({701}))),
                       get_song(conn, song.id))

    assert out.sheet == 702 and "sheet 702" in read(tmp_path, song, "sheet.txt")
    assert pick_ids(conn, song, "chords") == [702]


def test_a_kept_sheet_blocked_after_the_fetch_sends_its_song_back_and_unblocking_does_too(conn, tmp_path):
    song = accepted(conn)
    index(conn, *[(t, "soda-stereo", "persiana-americana", "chords") for t in (101, 102, 103)])
    ug = FakeUG()
    three_chords(ug)
    process_song(context(conn, ug.client(tmp_path / "cache"), tmp_path), song)
    assert "sheet 102" in read(tmp_path, song, "sheet.txt") and songs_to_fetch(conn, Overrides(), NOW) == []

    blocked = Overrides(block=frozenset({102}))  # "this sheet is wrong, never use it"
    assert [s.id for s in songs_to_fetch(conn, blocked, NOW)] == [song.id]
    process_song(context(conn, ug.client(tmp_path / "cache"), tmp_path, blocked), get_song(conn, song.id))
    assert "sheet 103" in read(tmp_path, song, "sheet.txt") and songs_to_fetch(conn, blocked, NOW) == []

    # You take it out of [block] again: it competes again, and wins.
    assert [s.id for s in songs_to_fetch(conn, Overrides(), NOW)] == [song.id]
    process_song(context(conn, ug.client(tmp_path / "cache"), tmp_path), get_song(conn, song.id))
    assert "sheet 102" in read(tmp_path, song, "sheet.txt") and songs_to_fetch(conn, Overrides(), NOW) == []
    assert ug.requests == [slugged(101), slugged(102), slugged(103)]  # all of it from the cache since


def test_blocking_a_guitar_pro_tab_of_the_song_sends_nothing_back(conn, tmp_path):
    # caracole uses no Guitar Pro tab of Ultimate Guitar's: blocking one changes nothing it keeps.
    song = accepted(conn)
    index(conn, (101, "soda-stereo", "persiana-americana", "chords"),
          (301, "soda-stereo", "persiana-americana", "guitar-pro"))
    ug = FakeUG()
    ug.tab(v(101), content=sheet("sheet 101", LINES))
    process_song(context(conn, ug.client(tmp_path / "cache"), tmp_path), song)

    assert songs_to_fetch(conn, Overrides(block=frozenset({301})), NOW) == []


def test_blocking_a_tab_the_song_doesnt_use_sends_nothing_back(conn, tmp_path):
    song = accepted(conn)
    index(conn, *[(t, "soda-stereo", "persiana-americana", "chords") for t in (101, 102, 103, 104)])
    ug = FakeUG()
    three_chords(ug)
    ug.tab(v(104, version=4, rating=3.0, votes=5), content=sheet("sheet 104", LINES))
    process_song(context(conn, ug.client(tmp_path / "cache"), tmp_path), song)  # keeps 102, and 101 and 103 beside
    assert songs_to_fetch(conn, Overrides(block=frozenset({104})), NOW) == []


# --- fetch_songs: budget, errors and blocks -----------------------------------------------


def test_budget_exhausted_mid_song_resumes(conn, tmp_path):
    song = accepted(conn)
    index(conn, *[(t, "soda-stereo", "persiana-americana", "chords") for t in (101, 102, 103)],
          (401, "soda-stereo", "persiana-americana", "tabs"))
    ug = FakeUG()
    three_chords(ug)
    low, high = v(401, "tabs", rating=4.0, votes=10), v(402, "tabs", version=2, rating=4.8, votes=40)
    ug.tab(low, [high], content=riff("tab 401"))
    ug.tab(high, [low], content=riff("tab 402"))

    first = fetch_songs(context(conn, ug.client(tmp_path / "cache", budget=2), tmp_path), [song])

    assert first == FetchStats(songs_done=0, songs_failed=0, budget_exhausted=True)
    half = get_song(conn, song.id)  # neither found nor not found: still dirty, never checked
    assert (half.status, half.ug_dirty, half.ug_checked_at, half.match_decision) == ("wanted", True, None, "accept")
    assert ug.requests == [slugged(101), slugged(102)]

    ug.requests.clear()
    second = fetch_songs(context(conn, ug.client(tmp_path / "cache"), tmp_path), [half])

    assert (second.songs_done, second.budget_exhausted) == (1, False)
    assert ug.requests == [slugged(103), slugged(401, "tabs"), slugged(402, "tabs")]  # 101 and 102 from the cache
    done = get_song(conn, song.id)
    assert (done.status, done.ug_dirty) == ("found", False)
    assert "sheet 102" in read(tmp_path, song, "sheet.txt") and "tab 402" in read(tmp_path, song, "tab.txt")


BROKEN = "<!DOCTYPE html>\n<html><head><title>Ultimate-Guitar.Com</title></head><body><div id=\"app\"></div></body></html>\n"


def signos(conn, ug, *, added_at="2026-09-01T00:00:00Z"):
    """A second accepted song, older than Persiana Americana, with one complete sheet (tab 901)."""
    song = accepted(conn, "Soda Stereo", "Signos", "soda-stereo", "signos", added_at=added_at)
    index(conn, (901, "soda-stereo", "signos", "chords"))
    ug.tab(version_dict(901, song="Signos", artist="Soda Stereo", tab_url=slugged(901, song="signos")),
           content=sheet("sheet 901", LINES))
    return song


@pytest.mark.parametrize("status,body", [(200, BROKEN), (500, "Internal Server Error")])
def test_parse_error_is_not_a_miss(conn, tmp_path, status, body):
    # A page whose js-store is gone (layout drift, a maintenance page) or a server error: provider errors.
    song = accepted(conn)
    index(conn, (101, "soda-stereo", "persiana-americana", "chords"))
    ug = FakeUG()
    ug.add(slugged(101), body, status=status)
    other = signos(conn, ug)

    stats = fetch_songs(context(conn, ug.client(tmp_path / "cache"), tmp_path), [song, other])

    assert stats == FetchStats(songs_done=1, songs_failed=1, budget_exhausted=False, sheets_done=1)
    failed = get_song(conn, song.id)  # neither found nor not found: dirty, accepted, never checked
    assert (failed.status, failed.ug_dirty, failed.ug_checked_at, failed.match_decision) == (
        "wanted", True, None, "accept")
    assert get_song(conn, other.id).status == "found"


def test_a_song_an_error_left_is_named_with_its_error(conn, tmp_path):
    # For the run's summary, which says why in words, and counts the songs of each cause.
    song = accepted(conn)
    index(conn, (101, "soda-stereo", "persiana-americana", "chords"))
    ug = FakeUG()
    ug.add(slugged(101), "Internal Server Error", status=500)
    other = signos(conn, ug)
    stats = fetch_songs(context(conn, ug.client(tmp_path / "cache"), tmp_path), [song, other])
    [(failed, error)] = stats.failures
    assert (failed.id, error.provider, error.status) == (song.id, "ug", 500)


RODRIGO = ("Concierto de Aranjuez para guitarra y orquesta, segundo movimiento, arreglo para guitarra sola de Narciso "
           "Yepes, grabado en Madrid")


def rodrigo(conn, ug, tab_id, part):
    """A part of a long work with its sheet on UG: the parts' titles agree for longer than a folder's name keeps."""
    slug = f"concierto-de-aranjuez-{part}"
    song = accepted(conn, "Joaquín Rodrigo", f"{RODRIGO}, part {part}", "joaquin-rodrigo", slug)
    index(conn, (tab_id, "joaquin-rodrigo", slug, "chords"))
    ug.tab(version_dict(tab_id, song=f"Concierto de Aranjuez part {part}", artist="Joaquín Rodrigo",
                        tab_url=slugged(tab_id, artist="joaquin-rodrigo", song=slug)),
           content=sheet(f"sheet of part {part}", LINES))
    return song


def test_a_song_whose_sheet_goes_where_another_songs_is_waits_and_the_others_are_fetched(conn, tmp_path):
    ug = FakeUG()
    one, two = rodrigo(conn, ug, 501, "one"), rodrigo(conn, ug, 502, "two")
    assert one.key != two.key and song_dir(tmp_path / "lib", one) == song_dir(tmp_path / "lib", two)
    other = signos(conn, ug)

    stats = fetch_songs(context(conn, ug.client(tmp_path / "cache"), tmp_path), [one, two, other])

    assert (stats.sheets_done, stats.songs_done, stats.songs_failed, stats.failures) == (2, 2, 0, [])
    [shared] = stats.shared
    assert (shared.song.id, shared.other.id, shared.name) == (two.id, one.id, "sheet.txt")
    assert "sheet of part one" in read(tmp_path, one, "sheet.txt")  # never written over
    assert kept_files(conn, two.id) == [] and get_song(conn, two.id).ug_dirty  # it waits, as after an error
    assert get_song(conn, other.id).status == "found"


def test_block_is_reraised_and_leaves_the_song_dirty(conn, tmp_path):
    song = accepted(conn)
    index(conn, (101, "soda-stereo", "persiana-americana", "chords"))
    ug = FakeUG()
    ug.add(slugged(101), "<html><body>Forbidden</body></html>", status=403)
    other = signos(conn, ug)

    with pytest.raises(ProviderBlocked):
        fetch_songs(context(conn, ug.client(tmp_path / "cache"), tmp_path), [song, other])

    assert ug.requests == [slugged(101)]  # nothing more is asked of UG this run
    assert (get_song(conn, song.id).ug_dirty, get_song(conn, song.id).match_decision) == (True, "accept")
    assert get_song(conn, other.id).ug_dirty is True


def test_broken_cached_page_is_fetched_again(conn, tmp_path):
    # Every 200 is cached forever, so a broken body would otherwise fail the song on every run.
    song = accepted(conn)
    index(conn, (101, "soda-stereo", "persiana-americana", "chords"))
    ug = FakeUG()
    ug.add(slugged(101), BROKEN)
    assert fetch_songs(context(conn, ug.client(tmp_path / "cache"), tmp_path), [song]).songs_failed == 1

    ug.requests.clear()
    ug.tab(v(101), content=sheet("sheet 101", LINES))  # UG serves the page properly again
    stats = fetch_songs(context(conn, ug.client(tmp_path / "cache"), tmp_path), [get_song(conn, song.id)])

    assert (stats.songs_done, stats.songs_failed) == (1, 0)
    assert ug.requests == [slugged(101)]
    assert "sheet 101" in read(tmp_path, song, "sheet.txt")


def unreadable_11(conn, ug):
    """Persiana Americana: UG keeps serving chords tab 11 with HTTP 200 and no js-store (a removed-tab
    notice, say); tab 12 is a good sheet."""
    song = accepted(conn)
    index(conn, (11, "soda-stereo", "persiana-americana", "chords"),
          (12, "soda-stereo", "persiana-americana", "chords"))
    ug.add(slugged(11), BROKEN)
    ug.tab(v(12), content=sheet("sheet 12", LINES))
    return song


def night(conn, ug, tmp_path, day):
    """One nightly fetch, ``day`` days after NOW: its stats and the requests it made."""
    ug.requests.clear()
    when = NOW + timedelta(days=day)
    stats = fetch_songs(context(conn, ug.client(tmp_path / "cache", now=when), tmp_path, now=when),
                        songs_to_fetch(conn, Overrides(), when))
    return stats, list(ug.requests)


def test_a_page_that_never_parses_is_skipped_and_the_song_goes_on(conn, tmp_path):
    ug = FakeUG()
    song = unreadable_11(conn, ug)

    first, asked = night(conn, ug, tmp_path, 0)
    assert first.songs_failed == 1 and asked == [slugged(11)]  # one bad answer may be a passing fault

    second, asked = night(conn, ug, tmp_path, 1)
    assert second.songs_failed == 0 and asked == [slugged(11), slugged(12)]  # fetched again: still unreadable
    assert "sheet 12" in read(tmp_path, song, "sheet.txt") and get_song(conn, song.id).status == "found"

    for day in (2, 3):
        stats, asked = night(conn, ug, tmp_path, day)
        assert stats.songs_failed == 0 and asked == []  # waits for its retry date: no request a night
    assert "sheet 12" in read(tmp_path, song, "sheet.txt")
    # Never gone, never a miss: the song is neither clean nor checked while tab 11 waits to be read.
    assert [r.tab_id for r in song_versions(conn, song.id, include_gone=True)] == ["12"]
    done = get_song(conn, song.id)
    assert (done.ug_dirty, done.ug_checked_at) == (True, None)


def test_an_unreadable_page_is_asked_for_again_after_its_retry_date(conn, tmp_path):
    ug = FakeUG()
    song = unreadable_11(conn, ug)
    night(conn, ug, tmp_path, 0)
    night(conn, ug, tmp_path, 1)

    assert night(conn, ug, tmp_path, 7)[1] == []
    assert night(conn, ug, tmp_path, 8)[1] == [slugged(11)]  # a week on: still unreadable
    assert night(conn, ug, tmp_path, 21)[1] == []  # and next time it waits twice as long
    ug.tab(v(11, rating=4.9, votes=200), [v(12)], content=sheet("sheet 11", LINES))  # UG serves it again
    assert night(conn, ug, tmp_path, 22)[1] == [slugged(11)]

    assert "sheet 11" in read(tmp_path, song, "sheet.txt")
    done = get_song(conn, song.id)
    assert (done.ug_dirty, done.ug_checked_at) == (False, "2026-11-09T03:30:00Z")
    assert night(conn, ug, tmp_path, 23)[0] == FetchStats()


# --- upgrades ---------------------------------------------------------------------------------


def kept_version(conn, song, name):
    return {f.name: f.version_id for f in kept_files(conn, song.id)}[name]


def two_chords(conn, ug):
    """101 (4.5, 20 votes) beats 102 (4.0, 10 votes); both complete."""
    index(conn, (101, "soda-stereo", "persiana-americana", "chords"), (102, "soda-stereo", "persiana-americana", "chords"))
    a, b = v(101, rating=4.5, votes=20), v(102, version=2, rating=4.0, votes=10)
    ug.tab(a, [b], content=sheet("sheet 101", LINES))
    ug.tab(b, [a], content=sheet("sheet 102", LINES))


def test_upgrade_replaces_when_outranked(conn, tmp_path):
    song = accepted(conn)
    ug = FakeUG()
    two_chords(conn, ug)
    process_song(context(conn, ug.client(tmp_path / "cache"), tmp_path), song)
    assert "sheet 101" in read(tmp_path, song, "sheet.txt")

    # The nightly index refresh finds 103 and marks the song dirty. 103's page also
    # carries fresh ratings for the versions seen before.
    index(conn, (103, "soda-stereo", "persiana-americana", "chords"))
    new = v(103, version=3, rating=4.9, votes=200)
    ug.tab(new, [v(101, rating=4.6, votes=30), v(102, version=2, rating=4.0, votes=10)],
           content=sheet("sheet 103", LINES))
    update_song(conn, song.id, ug_dirty=True)
    ug.requests.clear()

    out = process_song(context(conn, ug.client(tmp_path / "cache"), tmp_path), get_song(conn, song.id))

    assert out.sheet == 103 and "sheet 103" in read(tmp_path, song, "sheet.txt")
    assert pick_ids(conn, song, "chords") == [103]
    assert ug.requests == [slugged(103)]  # the new page only; 101 and 102 come from the cache
    rows = {int(r.tab_id): (r.rating, r.votes) for r in song_versions(conn, song.id)}
    assert rows[101] == (4.6, 30)


def test_kept_sheet_stays_when_not_outranked(conn, tmp_path):
    song = accepted(conn)
    ug = FakeUG()
    two_chords(conn, ug)
    process_song(context(conn, ug.client(tmp_path / "cache"), tmp_path), song)
    path = song_dir(tmp_path / "lib", song) / "sheet.txt"
    before = (path.stat().st_ino, kept_version(conn, song, "sheet.txt"))

    index(conn, (103, "soda-stereo", "persiana-americana", "chords"))
    ug.tab(v(103, version=3, rating=3.9, votes=12), [v(101, rating=4.5, votes=20)], content=sheet("sheet 103", LINES))
    update_song(conn, song.id, ug_dirty=True)
    out = process_song(context(conn, ug.client(tmp_path / "cache"), tmp_path), get_song(conn, song.id))

    assert out.sheet == 101 and pick_ids(conn, song, "chords") == [101]
    assert (path.stat().st_ino, kept_version(conn, song, "sheet.txt")) == before  # not even rewritten


# --- kept files the library lost ---------------------------------------------------------------------


def damage(path, how):
    """What the library may do to a kept file between two runs."""
    data = path.read_bytes()
    if how == "deleted":  # on a synced device, say
        path.unlink()
    elif how == "emptied":  # the rename of a write a power cut caught, with no data behind it
        path.write_bytes(b"")
    elif how == "same-size":
        path.write_bytes(bytes(len(data)))
    elif how == "linked":  # to a file with the very bytes kept, which is no reason to trust it
        twin = path.with_name("elsewhere")
        twin.write_bytes(data)
        path.unlink()
        path.symlink_to(twin)


def fetched_persiana(conn, tmp_path):
    """Persiana Americana fetched, kept and clean: sheet 101 and tab 401."""
    song = accepted(conn)
    index(conn, (101, "soda-stereo", "persiana-americana", "chords"), (401, "soda-stereo", "persiana-americana", "tabs"))
    ug = FakeUG()
    ug.tab(v(101), content=sheet("sheet 101", LINES))
    ug.tab(v(401, "tabs"), content=riff("tab 401"))
    process_song(context(conn, ug.client(tmp_path / "cache"), tmp_path), song)
    ug.requests.clear()
    return get_song(conn, song.id), ug


@pytest.mark.parametrize("how", ["deleted", "emptied", "same-size", "linked"])
def test_a_kept_file_the_library_lost_is_written_again_and_no_other(conn, tmp_path, how):
    song, ug = fetched_persiana(conn, tmp_path)
    folder = song_dir(tmp_path / "lib", song)
    kept = (folder / "sheet.json").read_bytes()
    others = {name: (folder / name).stat().st_ino for name in ("sheet.txt", "tab.txt", "tab.json")}
    damage(folder / "sheet.json", how)
    update_song(conn, song.id, ug_dirty=True)

    process_song(context(conn, ug.client(tmp_path / "cache"), tmp_path), get_song(conn, song.id))

    assert not (folder / "sheet.json").is_symlink() and (folder / "sheet.json").read_bytes() == kept
    assert {name: (folder / name).stat().st_ino for name in others} == others  # still kept: not rewritten
    assert ug.requests == []


@pytest.mark.parametrize("how", ["deleted", "emptied", "same-size", "linked"])
@pytest.mark.parametrize("name", ["sheet.txt", "sheet.json", "tab.txt", "tab.json"])
def test_a_clean_song_whose_kept_file_the_library_lost_is_fetched_again_at_the_next_run(conn, tmp_path, name, how):
    # The docs' case: a link planted at sheet.json removed, and the song's render failing every night.
    song, ug = fetched_persiana(conn, tmp_path)
    folder = song_dir(tmp_path / "lib", song)
    rescore_kept_sheets(conn, tmp_path / "lib", RankPolicy())  # what the nightly fetch step does first
    assert songs_to_fetch(conn, Overrides(), NOW) == []  # all there: nothing to do
    kept = (folder / name).read_bytes()
    damage(folder / name, how)

    rescore_kept_sheets(conn, tmp_path / "lib", RankPolicy())
    assert [s.id for s in songs_to_fetch(conn, Overrides(), NOW)] == [song.id]
    fetch_songs(context(conn, ug.client(tmp_path / "cache"), tmp_path), songs_to_fetch(conn, Overrides(), NOW))

    assert (folder / name).read_bytes() == kept and ug.requests == []  # from the HTTP cache
    rescore_kept_sheets(conn, tmp_path / "lib", RankPolicy())
    assert songs_to_fetch(conn, Overrides(), NOW) == []


def test_a_guitar_pro_file_you_filed_and_deleted_sends_nothing_back(conn, tmp_path):
    # caracole never downloads Guitar Pro files from Ultimate Guitar, so it can't write one again: here one filed
    # for a version it picked there when it still did (schema 9 keeps a version that has a file).
    song, _ = fetched_persiana(conn, tmp_path)
    gp = upsert_version(conn, provider="ug", tab_id="301", song_id=song.id, slot="guitar", kind="guitar-pro",
                        rating=4.5, votes=20, version=1, label=None, url=slugged(301, "guitar-pro"), raw={},
                        now="2026-10-18T03:30:00Z")
    keep_file(conn, tmp_path / "lib", song=song, version_id=gp, name="guitar-1.gp5", data=b"GP5 bytes", rank=1)
    (song_dir(tmp_path / "lib", song) / "guitar-1.gp5").unlink()

    rescore_kept_sheets(conn, tmp_path / "lib", RankPolicy())

    assert songs_to_fetch(conn, Overrides(), NOW) == []


# --- a corrected match ------------------------------------------------------------------------------


def signos_tab(tab_id, kind="chords", **kw):
    """A tab of Soda Stereo's "Signos": another song than Persiana Americana."""
    kw.setdefault("tab_url", slugged(tab_id, kind, song="signos"))
    return version_dict(tab_id, type=UG_TYPES[kind], song="Signos", artist="Soda Stereo", **kw)


def correct_to(conn, tmp_path, song_key):
    """You correct Persiana Americana's match in overrides.toml (as the to-do page tells you), then match."""
    path = tmp_path / "overrides.toml"
    path.write_text(f'[match]\n"Soda Stereo - Persiana Americana" = "soda-stereo/{song_key}"\n', encoding="utf-8")
    overrides = load_overrides(path)
    match_all(conn, overrides, MatchPolicy())
    assert get_song(conn, 1).match_song_key == song_key
    return overrides


@pytest.mark.parametrize("plain", [None, LYRICS])
def test_a_corrected_match_leaves_the_old_songs_sheets_out_of_the_running(conn, tmp_path, plain):
    # Persiana Americana was wrongly accepted as "Signos", whose 901 is rated 4.9 from 200 votes. Without
    # lyrics it wins on rating; with them it covers nothing, but so does no complete sheet.
    song = accepted(conn, akey="soda-stereo", skey="signos", plain=plain)
    index(conn, (901, "soda-stereo", "signos", "chords"), (101, "soda-stereo", "persiana-americana", "chords"))
    ug = FakeUG()
    ug.tab(signos_tab(901, rating=4.9, votes=200), content=sheet("sheet 901", ["completely other words here"]))
    ug.tab(v(101, rating=4.0, votes=10), content=sheet("sheet 101", LINES[:5]))  # half the lyrics
    process_song(context(conn, ug.client(tmp_path / "cache"), tmp_path), song)
    assert "sheet 901" in read(tmp_path, song, "sheet.txt")

    overrides = correct_to(conn, tmp_path, "persiana-americana")
    assert [s.id for s in songs_to_fetch(conn, overrides, NOW)] == [song.id]
    ug.requests.clear()
    process_song(context(conn, ug.client(tmp_path / "cache"), tmp_path, overrides), get_song(conn, song.id))

    assert "sheet 101" in read(tmp_path, song, "sheet.txt") and pick_ids(conn, song, "chords") == [101]
    assert [r.tab_id for r in song_versions(conn, song.id)] == ["101"] and ug.requests == [slugged(101)]


def test_a_corrected_match_leaves_the_old_songs_tab_out_of_the_running(conn, tmp_path):
    song = accepted(conn, akey="soda-stereo", skey="signos")
    index(conn, (901, "soda-stereo", "signos", "chords"), (921, "soda-stereo", "signos", "tabs"),
          (101, "soda-stereo", "persiana-americana", "chords"))
    ug = FakeUG()
    ug.tab(signos_tab(901), content=sheet("sheet 901", LINES))
    ug.tab(signos_tab(921, "tabs"), content=riff("tab 921"))
    ug.tab(v(101), content=sheet("sheet 101", LINES))
    process_song(context(conn, ug.client(tmp_path / "cache"), tmp_path), song)
    assert pick_ids(conn, song, "tabs") == [921] and "tab 921" in read(tmp_path, song, "tab.txt")

    overrides = correct_to(conn, tmp_path, "persiana-americana")
    assert pick_ids(conn, song, "tabs") == []
    process_song(context(conn, ug.client(tmp_path / "cache"), tmp_path, overrides), get_song(conn, song.id))

    assert pick_ids(conn, song, "tabs") == []
    assert names(conn, song) == {"sheet.txt", "sheet.json"}  # Persiana Americana has no tab: Signos's goes
    assert not (song_dir(tmp_path / "lib", song) / "tab.txt").exists()


def fake_chordpro(cmd, **kwargs):
    """Stands in for the chordpro program in the nightly render step: a PDF where --output= says."""
    out = next(a.split("=", 1)[1] for a in cmd if a.startswith("--output="))
    Path(out).write_bytes(b"%PDF-1.4 fake")
    return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")


def render_library(conn, cfg, tmp_path, overrides):
    return render_all(conn, dataclasses.replace(cfg, library_dir=tmp_path / "lib"), overrides,
                      runner=fake_chordpro, now=NOW)


@pytest.mark.parametrize("correction", [
    '[match]\n"Soda Stereo - Persiana Americana" = "soda-stereo/persiana-americana"\n',
    '[pin]\n"Soda Stereo - Persiana Americana" = ["https://tabs.ultimate-guitar.com/tab/999"]\n',  # gone
], ids=["match", "pin"])
def test_a_correction_whose_fetch_finds_no_sheet_leaves_none_of_the_old_ones(conn, cfg, tmp_path, correction):
    # Persiana Americana was wrongly accepted as "Signos"; corrected, UG has no sheet of it caracole can see.
    song = accepted(conn, akey="soda-stereo", skey="signos")
    index(conn, (901, "soda-stereo", "signos", "chords"))
    ug = FakeUG()
    ug.tab(signos_tab(901), content=sheet("sheet 901", LINES))
    soda_chords(ug)  # Soda Stereo's chords list has only "Signos"
    process_song(context(conn, ug.client(tmp_path / "cache"), tmp_path), song)
    render_library(conn, cfg, tmp_path, Overrides())
    folder = song_dir(tmp_path / "lib", song)
    assert {"sheet.txt", "sheet.json", "sheet.cho", "sheet.pdf"} <= {p.name for p in folder.iterdir()}

    overrides = overrides_from(tmp_path, correction)
    match_all(conn, overrides, MatchPolicy())
    fetch_songs(context(conn, ug.client(tmp_path / "cache"), tmp_path, overrides),
                songs_to_fetch(conn, overrides, NOW))
    render_library(conn, cfg, tmp_path, overrides)

    assert names(conn, song) == set() and get_song(conn, song.id).status == "wanted"
    assert sorted(p.name for p in folder.iterdir()) == ["info.json"]
    assert json.loads(read(tmp_path, song, "info.json"))["render"] is None


def test_unblocking_a_tab_only_an_earlier_match_found_sends_nothing_back(conn, tmp_path):
    song = accepted(conn, akey="soda-stereo", skey="signos")
    index(conn, (901, "soda-stereo", "signos", "chords"), (101, "soda-stereo", "persiana-americana", "chords"))
    ug = FakeUG()
    ug.tab(signos_tab(901), content=sheet("sheet 901", LINES))
    ug.tab(v(101), content=sheet("sheet 101", LINES))
    process_song(context(conn, ug.client(tmp_path / "cache"), tmp_path), song)
    correct_to(conn, tmp_path, "persiana-americana")
    blocked = Overrides(match={song.key: ("soda-stereo", "persiana-americana")}, block=frozenset({901}))
    process_song(context(conn, ug.client(tmp_path / "cache"), tmp_path, blocked), get_song(conn, song.id))

    unblocked = Overrides(match=blocked.match)
    assert songs_to_fetch(conn, unblocked, NOW) == []  # 901 is Signos's: it competes either way for nothing


def test_versions_the_old_and_new_match_share_come_back_from_the_cache(conn, tmp_path):
    # The match covered the variant slug "persiana-americana-acoustic"; you narrow it to that variant.
    song = accepted(conn)
    index(conn, (101, "soda-stereo", "persiana-americana", "chords"),
          (102, "soda-stereo", "persiana-americana-acoustic", "chords"))
    ug = FakeUG()
    ug.tab(v(101, rating=4.9, votes=100), content=sheet("sheet 101", LINES))
    ug.tab(v(102, version=2, rating=4.0, votes=10, tab_url=slugged(102, song="persiana-americana-acoustic")),
           content=sheet("sheet 102", LINES))
    process_song(context(conn, ug.client(tmp_path / "cache"), tmp_path), song)
    assert "sheet 101" in read(tmp_path, song, "sheet.txt")

    overrides = correct_to(conn, tmp_path, "persiana-americana-acoustic")
    ug.requests.clear()
    process_song(context(conn, ug.client(tmp_path / "cache"), tmp_path, overrides), get_song(conn, song.id))

    assert ug.requests == []
    assert "sheet 102" in read(tmp_path, song, "sheet.txt") and coverages(conn, song) == {102: 1.0}


# --- learning artist pages ------------------------------------------------------------------------


def test_artist_url_learned_from_every_tab_page(conn, tmp_path):
    song = accepted(conn)
    index(conn, (101, "soda-stereo", "persiana-americana", "chords"))
    ug = FakeUG()
    ug.tab(v(101), content=sheet("sheet 101", LINES))  # its data.tab.artist_url is Soda Stereo's page

    process_song(context(conn, ug.client(tmp_path / "cache"), tmp_path), song)

    assert learned_artist_url(conn, "soda-stereo") == SODA_URL


@pytest.mark.parametrize("linked", [
    "https://www.ultimate-guitar.com/artist/2946",
    "https://www.ultimate-guitar.com/artist/2946/?filter=chords#top",
    "/artist/2946",
])
def test_an_artist_page_addressed_by_its_number_alone_is_learned(conn, tmp_path, linked):
    # UG links some tabs to /artist/<id> alone, as 宋冬野's tabs to /artist/634073 (checked live).
    song = accepted(conn)
    index(conn, (101, "soda-stereo", "persiana-americana", "chords"))
    ug = FakeUG()
    ug.tab(v(101), content=sheet("sheet 101", LINES), artist_url=linked)

    process_song(context(conn, ug.client(tmp_path / "cache"), tmp_path), song)

    assert learned_artist_url(conn, "soda-stereo") == "https://www.ultimate-guitar.com/artist/2946"


@pytest.mark.parametrize("linked", ["https://www.ultimate-guitar.com/artist/soda_stereo",
                                    "https://www.ultimate-guitar.com/artist/_2946"])
def test_an_artist_link_without_a_number_teaches_nothing(conn, tmp_path, linked):
    song = accepted(conn)
    index(conn, (101, "soda-stereo", "persiana-americana", "chords"))
    ug = FakeUG()
    ug.tab(v(101), content=sheet("sheet 101", LINES), artist_url=linked)

    process_song(context(conn, ug.client(tmp_path / "cache"), tmp_path), song)

    assert learned_artist_url(conn, "soda-stereo") is None


def test_another_artists_page_is_not_learned_for_the_song(conn, tmp_path):
    # A pinned cover: its artist page belongs to the cover's artist, not to Soda Stereo.
    song = accepted(conn)
    cover = version_dict(777, song="Persiana Americana", artist="Los Imitadores")
    ug = FakeUG()
    ug.tab(cover, content=sheet("sheet 777", LINES),
           artist_url="https://www.ultimate-guitar.com/artist/los_imitadores_99")

    process_song(context(conn, ug.client(tmp_path / "cache"), tmp_path, Overrides(pin={song.key: (777,)})), song)

    assert learned_artist_url(conn, "soda-stereo") is None
    assert learned_artist_url(conn, "los-imitadores") == "https://www.ultimate-guitar.com/artist/los_imitadores_99"


# --- which songs a run fetches ------------------------------------------------------------------


def matched(conn, artist, title, decision, *, added_at, dirty=True, **fields):
    song = add_song(conn, artist, title, added_at=added_at)
    update_song(conn, song.id, match_decision=decision, ug_dirty=dirty, **fields)
    return get_song(conn, song.id)


def test_songs_to_fetch_dirty_accepted_and_pinned_newest_first(conn):
    old = matched(conn, "Soda Stereo", "Signos", "accept", added_at="2026-09-01T00:00:00Z")
    pinned = matched(conn, "Soda Stereo", "Ameba", "pinned", added_at="2026-09-15T00:00:00Z")
    new = matched(conn, "Soda Stereo", "Persiana Americana", "accept", added_at="2026-10-10T00:00:00Z")
    matched(conn, "Soda Stereo", "Cae El Sol", "accept", added_at="2026-10-11T00:00:00Z", dirty=False)
    matched(conn, "Soda Stereo", "Zoom", "review", added_at="2026-10-12T00:00:00Z")
    matched(conn, "Soda Stereo", "Ella Uso Mi Cabeza", "accept", added_at="2026-10-13T00:00:00Z", status="ignored")
    skipped = matched(conn, "Soda Stereo", "Coral", "accept", added_at="2026-10-14T00:00:00Z")

    songs = songs_to_fetch(conn, Overrides(ignore=frozenset({skipped.key})), NOW)

    assert [s.id for s in songs] == [new.id, pinned.id, old.id]


def test_songs_to_fetch_not_found_whose_artist_is_known(conn):
    # A6: the index can't see bare-id tabs, but the artist's UG page lists them.
    index(conn, (7, "soda-stereo", "signos", "chords"))
    indexed = matched(conn, "Soda Stereo", "De Música Ligera", "not_found", added_at="2026-10-05T00:00:00Z")
    pasted = matched(conn, "宋冬野", "斑马，斑马", "not_found", added_at="2026-10-04T00:00:00Z")
    learned = matched(conn, "Joaquín Sabina", "19 Días y 500 Noches", "not_found", added_at="2026-10-03T00:00:00Z")
    matched(conn, "Héroes del Silencio", "Entre Dos Tierras", "not_found", added_at="2026-10-02T00:00:00Z")
    remember_artist_url(conn, "joaquin-sabina", "https://www.ultimate-guitar.com/artist/joaquin_sabina_12345")
    overrides = Overrides(artist_url={"宋冬野": BANMA_ARTIST})

    songs = songs_to_fetch(conn, overrides, NOW)

    assert [s.id for s in songs] == [indexed.id, pasted.id, learned.id]


def test_artist_page_checks_wait_thirty_days(conn):
    index(conn, (7, "soda-stereo", "signos", "chords"))
    song = matched(conn, "Soda Stereo", "De Música Ligera", "not_found", added_at="2026-10-05T00:00:00Z")
    kv_set(conn, f"ug:artist_page_checked:{song.id}", "2026-09-20T03:30:00Z")
    assert songs_to_fetch(conn, Overrides(), NOW) == []
    assert [s.id for s in songs_to_fetch(conn, Overrides(), NOW + timedelta(days=2))] == [song.id]


# --- the artist-page route (A6) ---------------------------------------------------------------------

# Invented lines, not the song's lyrics: Simplified for the sheets, Traditional for
# LRCLIB (as its 斑马斑马 records are). Each pair reads the same in pinyin.
BANMA_LINES = ["河边的小路通向远方", "我在窗前数星星", "秋天的风吹过山岗",
               "旧信封里有一个夏天", "火车开往没有名字的城", "灯光照亮回家的桥"]
BANMA_TRADITIONAL_LINES = ["河邊的小路通向遠方", "我在窗前數星星", "秋天的風吹過山崗",
                           "舊信封裡有一個夏天", "火車開往沒有名字的城", "燈光照亮回家的橋"]
BANMA_TRADITIONAL = "\n".join(BANMA_TRADITIONAL_LINES)
KIND_TYPES = {"chords": "Chords", "tabs": "Tabs", "guitar-pro": "Pro", "power": "Power"}


def artist_page(artist_id, name, tabs, *, page=1, pages=1, kinds=("chords",), path=None):
    """One page of an artist's filtered tab list: ``tabs`` are this page's entries, in UG's order.

    UG's filter bar offers a filter per type the artist has, whichever filter is
    showing; ``kinds`` are those types. ``path`` is the page's own, as UG's links
    write it: ``/artist/<name>_<id>`` by default, or the bare ``/artist/<id>``.
    """
    path = path or artist_path(artist_id, name)
    types = [{"name": "all", "url": path, "count": len(tabs)}]
    for kind in kinds:
        label, value = ARTIST_FILTERS[KIND_TYPES[kind]]
        types.append({"name": label, "url": f"{path}?filter={value}", "count": len(tabs)})
    return store_page_html({
        "artist": {"id": artist_id, "name": name, "name_stripped": name_stripped(name)},
        "other_tabs": list(tabs),
        "current_page": page,
        "pagination": {"pages": [{"page": n, "url": path if n == 1 else f"{path}?page={n}"}
                                 for n in range(1, pages + 1)], "current": page},
        "filters": {"types": types, "current_filters": {"types": "new_tab_type"}},
    })


def artist_list(base, kind="chords", page=1):
    return artist_page_url(base, kind=kind, page=page)


def banma(conn, *, added_at="2026-10-18T00:00:00Z"):
    """宋冬野 - 斑马，斑马: UG lists 宋冬野 only by bare ids, so the matcher found nothing."""
    song = add_song(conn, "宋冬野", "斑马，斑马", album="安和桥北", duration_ms=253000, added_at=added_at)
    update_song(conn, song.id, match_decision="not_found", lyrics_status="found",
                lyrics_json=lyrics_json(BANMA_TRADITIONAL))
    return get_song(conn, song.id)


def banma_tab(tab_id, **kw):
    """A tab of 宋冬野 as UG lists it: a bare /tab/{id} URL."""
    kw.setdefault("song", "斑马斑马")
    return version_dict(tab_id, artist="宋冬野", **kw)


PASTED = Overrides(artist_url={"宋冬野": BANMA_ARTIST})


def serve_banma(ug, entries, *, pages=None, kinds=("chords",)):
    """宋冬野's chords list (one page per list in ``pages``, else just ``entries``), and its two sheets."""
    best = banma_tab(2001234, rating=4.7, votes=50)
    other = banma_tab(2001235, version=2, rating=4.2, votes=5)
    for n, tabs in enumerate(pages or [entries], start=1):
        ug.add(artist_list(BANMA_ARTIST, page=n),
               artist_page(1234567, "宋冬野", tabs, page=n, pages=len(pages or [entries]), kinds=kinds))
    ug.tab(best, [other], content=sheet("sheet 2001234", BANMA_LINES), artist_url=BANMA_ARTIST)
    ug.tab(other, [best], content=sheet("sheet 2001235", BANMA_LINES[:3]), artist_url=BANMA_ARTIST)
    return best, other


def test_a_pasted_artist_page_addressed_by_its_number_alone_is_read(conn, tmp_path):
    song = banma(conn)
    base = "https://www.ultimate-guitar.com/artist/634073"
    ug = FakeUG()
    best = banma_tab(2001234, rating=4.7, votes=50)
    ug.add(artist_list(base), artist_page(634073, "宋冬野", [best], path="/artist/634073"))
    ug.tab(best, content=sheet("sheet 2001234", BANMA_LINES), artist_url=base)
    pasted = Overrides(artist_url={"宋冬野": base})

    out = process_song(context(conn, ug.client(tmp_path / "cache"), tmp_path, pasted), song)

    assert ug.requests == [f"{base}?filter=chords", f"{TAB}2001234"]
    assert out.sheet == 2001234 and get_song(conn, song.id).status == "found"


def test_banma_found_on_its_artist_page_once_its_url_is_pasted(conn, tmp_path):
    song = banma(conn)
    ug = FakeUG()
    best = banma_tab(2001234, rating=4.7, votes=50)
    other = banma_tab(2001235, version=2, rating=4.2, votes=5)
    elsewhere = banma_tab(2001300, song="安和桥", rating=4.9, votes=80)
    serve_banma(ug, [elsewhere, best, other])
    assert [s.id for s in songs_to_fetch(conn, PASTED, NOW)] == [song.id]

    out = process_song(context(conn, ug.client(tmp_path / "cache"), tmp_path, PASTED), song)

    done = get_song(conn, song.id)
    assert (done.match_decision, done.match_step, done.match_artist_key, done.match_song_key) == (
        "accept", "artist_page", "宋冬野", "斑马斑马")
    assert (done.status, done.ug_dirty, done.ug_checked_at) == ("found", False, "2026-10-18T03:30:00Z")
    assert out.sheet == 2001234 and "sheet 2001234" in read(tmp_path, song, "sheet.txt")
    assert coverages(conn, song) == {2001234: 1.0, 2001235: 0.5}  # Traditional lyrics, Simplified sheets
    assert ug.requests == [artist_list(BANMA_ARTIST), f"{TAB}2001234", f"{TAB}2001235"]
    assert kv_get(conn, f"ug:artist_page_checked:{song.id}") == "2026-10-18T03:30:00Z"
    assert songs_to_fetch(conn, PASTED, NOW) == []


def soda_dml(conn):
    """Soda Stereo - De Música Ligera: every one of its tabs is a bare id, so the matcher found nothing."""
    song = matched(conn, "Soda Stereo", "De Música Ligera", "not_found", added_at="2026-10-17T00:00:00Z")
    update_song(conn, song.id, lyrics_status="found", lyrics_json=lyrics_json(LYRICS))
    return get_song(conn, song.id)


def serve_dml(ug):
    dml = {"song": "De Música Ligera", "artist": "Soda Stereo", "song_id": 67588}
    v1 = version_dict(85042, version=1, rating=4.83354, votes=277, **dml)
    v2 = version_dict(85053, version=2, rating=4.54038, votes=7, **dml)
    persiana = v(1601640, rating=4.8, votes=40)
    ug.add(artist_list(SODA_URL), artist_page(2946, "Soda Stereo", [v1, v2, persiana]))
    ug.tab(v1, [v2], content=sheet("sheet 85042", LINES))
    ug.tab(v2, [v1], content=sheet("sheet 85053", LINES))


def test_artist_page_learned_from_a_slugged_tab_of_the_artist(conn, tmp_path):
    # Soda Stereo's "Persiana Americana" tabs are slugged, so the index knows the artist.
    index(conn, (1081462, "soda-stereo", "persiana-americana", "tabs"))
    song = soda_dml(conn)
    ug = FakeUG()
    ug.tab(v(1081462, "tabs"), [v(1081470, "tabs", version=2)], content=riff("persiana riff"))
    serve_dml(ug)

    process_song(context(conn, ug.client(tmp_path / "cache"), tmp_path), song)

    assert ug.requests[:2] == [slugged(1081462, "tabs"), artist_list(SODA_URL)]
    assert learned_artist_url(conn, "soda-stereo") == SODA_URL
    # The tab read to learn the page is another song's: none of its versions are this song's.
    assert {int(r.tab_id) for r in song_versions(conn, song.id, include_gone=True)} == {85042, 85053}
    done = get_song(conn, song.id)
    assert (done.match_step, done.match_artist_key, done.match_song_key) == (
        "artist_page", "soda-stereo", "de-musica-ligera")
    assert "sheet 85042" in read(tmp_path, song, "sheet.txt")


def test_artist_page_learned_while_fetching_another_song_is_reused(conn, tmp_path):
    persiana = accepted(conn, added_at="2026-10-01T00:00:00Z")
    index(conn, (101, "soda-stereo", "persiana-americana", "chords"))
    dml = soda_dml(conn)
    ug = FakeUG()
    ug.tab(v(101), content=sheet("sheet 101", LINES))  # it links to Soda Stereo's artist page
    serve_dml(ug)

    fetch_songs(context(conn, ug.client(tmp_path / "cache"), tmp_path), [persiana, dml])

    assert ug.requests == [slugged(101), artist_list(SODA_URL), f"{TAB}85042", f"{TAB}85053"]
    assert get_song(conn, dml.id).status == "found"


def test_title_missing_from_the_artist_page_stays_not_found_for_thirty_days(conn, tmp_path):
    song = banma(conn)
    ug = FakeUG()
    serve_banma(ug, [banma_tab(2001300, song="安和桥", rating=4.9, votes=80)])

    out = process_song(context(conn, ug.client(tmp_path / "cache"), tmp_path, PASTED), song)

    assert (out.sheet, out.tab) == (None, None)
    done = get_song(conn, song.id)
    assert (done.match_decision, done.status, done.ug_checked_at) == ("not_found", "wanted", None)
    assert song_versions(conn, song.id, include_gone=True) == []
    assert songs_to_fetch(conn, PASTED, NOW + timedelta(days=29)) == []
    assert [s.id for s in songs_to_fetch(conn, PASTED, NOW + timedelta(days=31))] == [song.id]


def test_title_straddling_two_artist_pages(conn, tmp_path):
    # Lists are sorted by title, 100 to a page, so a title's versions can run onto the next page.
    song = banma(conn)
    ug = FakeUG()
    best, other = banma_tab(2001234, rating=4.7, votes=50), banma_tab(2001235, version=2, rating=4.2, votes=5)
    serve_banma(ug, None, pages=[
        [banma_tab(2001100, song="安和桥"), best],
        [other, banma_tab(2001400, song="鸽子")],
        [banma_tab(2001500, song="早晨")],
    ])

    process_song(context(conn, ug.client(tmp_path / "cache"), tmp_path, PASTED), song)

    assert {int(r.tab_id) for r in song_versions(conn, song.id)} == {2001234, 2001235}
    assert artist_list(BANMA_ARTIST, page=2) in ug.requests
    assert artist_list(BANMA_ARTIST, page=3) not in ug.requests  # the title's entries ended on page 2


def test_artist_pages_are_capped_per_kind_per_run(conn, tmp_path):
    song = banma(conn)
    ug = FakeUG()
    best, other = banma_tab(2001234, rating=4.7, votes=50), banma_tab(2001235, version=2, rating=4.2, votes=5)
    filler = [[banma_tab(2001100 + n, song=f"歌{n}")] for n in range(4)]
    serve_banma(ug, None, pages=[*filler, [best, other]])

    first = process_song(context(conn, ug.client(tmp_path / "cache"), tmp_path, PASTED), song)

    assert ug.requests == [artist_list(BANMA_ARTIST, page=n) for n in (1, 2, 3)]
    pending = get_song(conn, song.id)  # not a miss: the rest of the list is read next run
    assert (first.sheet, pending.match_decision) == (None, "not_found")
    assert kv_get(conn, f"ug:artist_page_checked:{song.id}") is None

    ug.requests.clear()
    second = process_song(context(conn, ug.client(tmp_path / "cache"), tmp_path, PASTED), pending)

    assert ug.requests[:2] == [artist_list(BANMA_ARTIST, page=4), artist_list(BANMA_ARTIST, page=5)]
    assert second.sheet == 2001234 and get_song(conn, song.id).match_step == "artist_page"


def test_artist_page_kinds_fill_the_tab_slot_and_its_guitar_pro_lists_are_never_read(conn, tmp_path):
    song = banma(conn)
    ug = FakeUG()
    kinds = ("chords", "guitar-pro", "power", "tabs")
    serve_banma(ug, [banma_tab(2001234, rating=4.7, votes=50)], kinds=kinds)
    pro = banma_tab(2002000, type="Pro", rating=4.5, votes=12)
    intro = banma_tab(2003000, type="Tabs", part="intro", rating=4.0, votes=3)
    guitar_pro = f"{BANMA_ARTIST}?filter=guitar_pro"  # UG's Guitar Pro list, which caracole never asks for
    ug.add(guitar_pro, artist_page(1234567, "宋冬野", [pro], kinds=kinds))
    ug.add(artist_list(BANMA_ARTIST, "tabs"), artist_page(1234567, "宋冬野", [intro], kinds=kinds))
    ug.tab(intro, content=riff("intro riff"), artist_url=BANMA_ARTIST)

    out = process_song(context(conn, ug.client(tmp_path / "cache"), tmp_path, PASTED), song)

    assert out.tab == 2003000
    assert ug.requests == [artist_list(BANMA_ARTIST), artist_list(BANMA_ARTIST, "tabs"), f"{TAB}2001234",
                           f"{TAB}2003000"]
    assert "intro riff" in read(tmp_path, song, "tab.txt")
    assert {r.kind for r in song_versions(conn, song.id, include_gone=True)} == {"chords", "tabs"}


@pytest.mark.parametrize("listed", ["斑馬斑馬", "Ban Ma Ban Ma", "Banma Banma"])
def test_titles_match_across_scripts_and_in_pinyin(conn, tmp_path, listed):
    song = banma(conn)
    ug = FakeUG()
    entry = banma_tab(2001234, song=listed, rating=4.7, votes=50)
    ug.add(artist_list(BANMA_ARTIST), artist_page(1234567, "宋冬野", [entry]))
    ug.tab(entry, content=sheet("sheet 2001234", BANMA_LINES), artist_url=BANMA_ARTIST)

    assert process_song(context(conn, ug.client(tmp_path / "cache"), tmp_path, PASTED), song).sheet == 2001234


LIVE_PASTED = Overrides(artist_url={"宋冬野": SONG_DONGYE_URL})


def serve_song_dongye(ug, *, lines=BANMA_TRADITIONAL_LINES):
    """宋冬野's chords list as UG showed it live (/artist/634073?filter=chords), and the sheets of its
    two 斑马斑马 versions and its two 董小姐 ones."""
    ug.add(artist_list(SONG_DONGYE_URL), song_dongye_page_html(
        song_dongye_chords(t4180894=(4.8, 120), t4689017=(4.6, 40), t3016223=(4.7, 90), t3204647=(4.1, 9))))
    for tab_id, version in ((4180894, 1), (4689017, 2)):
        other = song_dongye_tab(4689017 if version == 1 else 4180894, BANMA_UG, version=3 - version)
        ug.tab(song_dongye_tab(tab_id, BANMA_UG, version=version), [other],
               content=song_dongye_sheet(lines), artist_url=SONG_DONGYE_URL)
    for tab_id, version in ((3016223, 1), (3204647, 2)):
        ug.tab(song_dongye_tab(tab_id, "董小姐", version=version), [],
               content=song_dongye_sheet(DONG_XIAOJIE_LINES), artist_url=SONG_DONGYE_URL)


def song_by_song_dongye(conn, title, lines=BANMA_TRADITIONAL_LINES, *, decision="not_found"):
    """A song of 宋冬野's with LRCLIB lyrics; the matcher found it nowhere in the index, unless pinned."""
    song = add_song(conn, "宋冬野", title, added_at="2026-10-18T00:00:00Z")
    step = "pin" if decision == "pinned" else None
    update_song(conn, song.id, match_decision=decision, match_step=step, lyrics_status="found",
                lyrics_json=lyrics_json("\n".join(lines)))
    return get_song(conn, song.id)


@pytest.mark.parametrize("title", ["斑马斑马", "斑马，斑马", "斑馬斑馬", "Banma Banma", "Ban Ma Ban Ma"])
def test_the_live_artist_page_lists_banma_in_two_scripts_and_a_translation(conn, tmp_path, title):
    # UG lists it as "斑马 斑马 Banma Banma Zebra Zebra": the original, its pinyin, a translation.
    song = song_by_song_dongye(conn, title)
    ug = FakeUG()
    serve_song_dongye(ug)

    out = process_song(context(conn, ug.client(tmp_path / "cache"), tmp_path, LIVE_PASTED), song)

    assert {int(r.tab_id) for r in song_versions(conn, song.id)} == {4180894, 4689017}
    done = get_song(conn, song.id)
    assert (done.match_step, done.match_artist_key, done.match_song_key) == (
        "artist_page", "song-dongye-宋冬野", "斑马斑马-banma-banma-zebra-zebra")
    assert out.sheet == 4180894 and done.status == "found"
    assert coverages(conn, song) == {4180894: 1.0, 4689017: 1.0}


@pytest.mark.parametrize("title,ids", [
    ("莉莉安", {4041916}), ("Lilian", {4041916}), ("与我交谈", {6613886}), ("Speak With Me", {6613886}),
    ("董小姐", {3016223, 3204647}),
])
def test_an_original_title_meets_its_listing_with_a_translation(conn, tmp_path, title, ids):
    song = song_by_song_dongye(conn, title)
    ug = FakeUG()
    serve_song_dongye(ug)

    process_song(context(conn, ug.client(tmp_path / "cache"), tmp_path, LIVE_PASTED), song)

    assert {int(r.tab_id) for r in song_versions(conn, song.id, include_gone=True)} == ids
    assert get_song(conn, song.id).match_step == "artist_page"


def test_a_title_the_live_artist_page_doesnt_list_stays_not_found(conn, tmp_path):
    # The page's other songs, in either script, never stand in for 安和桥北.
    song = song_by_song_dongye(conn, "安和桥北")
    ug = FakeUG()
    serve_song_dongye(ug)

    process_song(context(conn, ug.client(tmp_path / "cache"), tmp_path, LIVE_PASTED), song)

    assert song_versions(conn, song.id, include_gone=True) == []
    assert get_song(conn, song.id).match_decision == "not_found"


def test_a_tab_page_of_the_artist_in_two_scripts_teaches_the_page_under_the_songs_artist(conn, tmp_path):
    # UG's "Song Dongye (宋冬野)" is 宋冬野, so a pin of its tab page files the page under the song's
    # artist too: the artist's other songs are then looked for there.
    song = song_by_song_dongye(conn, "斑马斑马", decision="pinned")
    ug = FakeUG()
    serve_song_dongye(ug)

    process_song(context(conn, ug.client(tmp_path / "cache"), tmp_path, Overrides(pin={song.key: (4180894,)})), song)

    for key in ("宋冬野", "song-dong-ye", "song-dongye", "song-dongye-宋冬野"):
        assert learned_artist_url(conn, key) == SONG_DONGYE_URL, key


def test_a_tab_page_of_another_artist_in_two_scripts_teaches_nothing_for_the_song(conn, tmp_path):
    song = song_by_song_dongye(conn, "斑马斑马", decision="pinned")
    cover = version_dict(777, song=BANMA_UG, artist="Li Zhi (李志)")
    ug = FakeUG()
    ug.tab(cover, content=song_dongye_sheet(BANMA_TRADITIONAL_LINES),
           artist_url="https://www.ultimate-guitar.com/artist/99")

    process_song(context(conn, ug.client(tmp_path / "cache"), tmp_path, Overrides(pin={song.key: (777,)})), song)

    assert learned_artist_url(conn, "宋冬野") is None
    assert learned_artist_url(conn, "李志") == "https://www.ultimate-guitar.com/artist/99"


@pytest.mark.parametrize("pair", [
    "Li Zhi (feat. 宋冬野)", "Li Zhi feat. Song Dongye", "Li Zhi (feat. 宋冬野 Song Dongye)",
    "Song Dongye (宋冬野) feat. Li Zhi",
])
def test_a_tab_of_a_pair_teaches_its_page_to_neither_artist(conn, tmp_path, pair):
    # UG may give a pair a page of its own, which lists neither artist's other songs: filed under either
    # one's name, it would stand in for that artist's own page, and their songs would be missed there.
    song = song_by_song_dongye(conn, "斑马斑马", decision="pinned")
    remember_artist_url(conn, "李志", "https://www.ultimate-guitar.com/artist/li_zhi_5")
    duet = version_dict(778, song=BANMA_UG, artist=pair)
    ug = FakeUG()
    ug.tab(duet, content=song_dongye_sheet(BANMA_TRADITIONAL_LINES), artist_url="https://www.ultimate-guitar.com/artist/99")

    process_song(context(conn, ug.client(tmp_path / "cache"), tmp_path, Overrides(pin={song.key: (778,)})), song)

    for key in ("宋冬野", "song-dong-ye", "song-dongye", "song-dongye-宋冬野", "li-zhi"):
        assert learned_artist_url(conn, key) is None, key
    assert learned_artist_url(conn, "李志") == "https://www.ultimate-guitar.com/artist/li_zhi_5"
    assert learned_artist_url(conn, slug_key(pair)) == "https://www.ultimate-guitar.com/artist/99"  # the pair's


# --- a tab page pasted under [artist_url] --------------------------------------------------------

FOUND_TAB = f"{TAB}4180894"  # the page the user found on UG for 宋冬野 - 斑马斑马 (2026-10-19)
TAB_PASTED = Overrides(artist_url={"宋冬野": FOUND_TAB})


def test_a_tab_page_pasted_under_artist_url_is_read_once_for_its_artist_page(conn, tmp_path):
    song = song_by_song_dongye(conn, "斑马斑马")
    later = song_by_song_dongye(conn, "董小姐", DONG_XIAOJIE_LINES)
    ug = FakeUG()
    serve_song_dongye(ug)
    assert {s.id for s in songs_to_fetch(conn, TAB_PASTED, NOW)} == {song.id, later.id}  # the artist is known

    out = process_song(context(conn, ug.client(tmp_path / "cache"), tmp_path, TAB_PASTED), song)

    # The tab page is one request, through the run's client; the sheet slot reads it from the cache.
    assert ug.requests == [FOUND_TAB, artist_list(SONG_DONGYE_URL), artist_list(SONG_DONGYE_URL, "tabs"),
                           f"{TAB}4689017"]
    assert out.sheet == 4180894 and get_song(conn, song.id).status == "found"
    assert learned_artist_url(conn, "宋冬野") == SONG_DONGYE_URL
    ug.requests.clear()

    process_song(context(conn, ug.client(tmp_path / "cache"), tmp_path, TAB_PASTED), later)

    # Remembered: the artist's other songs cost no request for the tab page, nor for the lists.
    assert ug.requests == [f"{TAB}3016223", f"{TAB}3204647"]
    assert get_song(conn, later.id).status == "found"


@pytest.mark.parametrize("linked", ["", "https://www.ultimate-guitar.com/artist/song_dongye", "https://example.com/a/1"])
def test_a_pasted_tab_page_without_an_artist_page_is_no_crash_and_no_miss(conn, tmp_path, linked):
    song = song_by_song_dongye(conn, "斑马斑马")
    ug = FakeUG()
    ug.tab(song_dongye_tab(4180894, BANMA_UG, artist_url=linked), content=song_dongye_sheet(BANMA_TRADITIONAL_LINES),
           artist_url=None)

    stats = fetch_songs(context(conn, ug.client(tmp_path / "cache"), tmp_path, TAB_PASTED), [song])

    assert ug.requests == [FOUND_TAB] and (stats.songs_done, stats.songs_failed) == (1, 0)
    assert kv_get(conn, f"ug:artist_page_checked:{song.id}") is None  # never looked for: not a miss
    assert get_song(conn, song.id).match_decision == "not_found"
    assert pasted_page_problem(conn, song, TAB_PASTED) == (FOUND_TAB, "it doesn't link to its artist's page")
    assert not artist_is_known(conn, song, TAB_PASTED)
    assert songs_to_fetch(conn, TAB_PASTED, NOW + timedelta(days=1)) == []  # until you paste another page
    other = Overrides(artist_url={"宋冬野": SONG_DONGYE_URL})
    assert [s.id for s in songs_to_fetch(conn, other, NOW + timedelta(days=1))] == [song.id]


def test_a_pasted_tab_page_ug_answers_404_for_says_so(conn, tmp_path):
    song = song_by_song_dongye(conn, "斑马斑马")
    ug = FakeUG()  # UG's 404 page for everything

    process_song(context(conn, ug.client(tmp_path / "cache"), tmp_path, TAB_PASTED), song)

    assert ug.requests == [FOUND_TAB]
    assert pasted_page_problem(conn, song, TAB_PASTED) == (FOUND_TAB, "UG answers 404 for it")
    assert kv_get(conn, f"ug:artist_page_checked:{song.id}") is None


def test_a_pasted_tab_page_robots_txt_closes_is_never_asked_for(conn, tmp_path):
    song = song_by_song_dongye(conn, "斑马斑马")
    closed = Overrides(artist_url={"宋冬野": CLOSED})
    ug = FakeUG()

    process_song(context(conn, ug.client(tmp_path / "cache"), tmp_path, closed), song)

    assert ug.requests == []
    assert pasted_page_problem(conn, song, closed) == (CLOSED, "robots.txt closes it to caracole")


def test_a_pasted_bare_tab_url_of_a_slugged_tab_is_read_at_its_slugged_url(conn, tmp_path):
    # UG answers 404 for a slugged tab at its bare /tab/{id}: the index's path is where it is.
    index(conn, (1081462, "soda-stereo", "persiana-americana", "tabs"))
    song = soda_dml(conn)
    ug = FakeUG()
    ug.tab(v(1081462, "tabs"), content=riff("persiana riff"))
    serve_dml(ug)
    pasted = Overrides(artist_url={"soda-stereo": f"{TAB}1081462"})

    process_song(context(conn, ug.client(tmp_path / "cache"), tmp_path, pasted), song)

    assert ug.requests[:2] == [slugged(1081462, "tabs"), artist_list(SODA_URL)]
    assert get_song(conn, song.id).match_step == "artist_page"


def test_a_pasted_tab_page_waits_for_the_budget_like_any_page(conn, tmp_path):
    song = song_by_song_dongye(conn, "斑马斑马")
    ug = FakeUG()
    serve_song_dongye(ug)

    first = fetch_songs(context(conn, ug.client(tmp_path / "cache", budget=0), tmp_path, TAB_PASTED), [song])

    assert first.budget_exhausted and ug.requests == []
    assert pasted_page_problem(conn, song, TAB_PASTED) is None and artist_is_known(conn, song, TAB_PASTED)
    assert get_song(conn, song.id).match_decision == "not_found"
    fetch_songs(context(conn, ug.client(tmp_path / "cache"), tmp_path, TAB_PASTED), [get_song(conn, song.id)])
    assert get_song(conn, song.id).status == "found"


def test_a_block_on_a_pasted_tab_page_is_a_block(conn, tmp_path):
    song = song_by_song_dongye(conn, "斑马斑马")
    ug = FakeUG()
    ug.add(FOUND_TAB, "Too many requests", status=429)

    with pytest.raises(ProviderBlocked):
        fetch_songs(context(conn, ug.client(tmp_path / "cache"), tmp_path, TAB_PASTED), [song])

    assert pasted_page_problem(conn, song, TAB_PASTED) is None  # tried again once the cooldown is over
    assert kv_get(conn, f"ug:artist_page_checked:{song.id}") is None


def test_a_pasted_tab_page_that_wont_parse_waits_for_its_retry_date_like_any_tab_page(conn, tmp_path):
    # UG answers 200 with a page caracole can't read: an error, never a miss, asked for again on the
    # dates of the tab-page rule (UNREADABLE_RETRY), and named on the to-do page meanwhile.
    song = song_by_song_dongye(conn, "斑马斑马")
    ug = FakeUG()
    ug.add(FOUND_TAB, BROKEN)

    def night(day):
        ug.requests.clear()
        when = NOW + timedelta(days=day)
        stats = fetch_songs(context(conn, ug.client(tmp_path / "cache", now=when), tmp_path, TAB_PASTED, now=when),
                            songs_to_fetch(conn, TAB_PASTED, when))
        return stats, list(ug.requests)

    first, asked = night(0)
    assert first.songs_failed == 1 and asked == [FOUND_TAB]  # one bad answer may be a passing fault
    second, asked = night(1)
    assert second.songs_failed == 0 and asked == [FOUND_TAB]  # fetched again: still unreadable
    assert pasted_page_problem(conn, song, TAB_PASTED) == (
        FOUND_TAB, "UG's copy of it can't be read; caracole asks for it again after 2026-10-26")
    assert artist_is_known(conn, song, TAB_PASTED)  # an error: the song keeps waiting for the page
    assert [night(day)[1] for day in (2, 5, 7)] == [[], [], []]
    assert kv_get(conn, f"ug:artist_page_checked:{song.id}") is None  # never looked for: not a miss
    assert get_song(conn, song.id).match_decision == "not_found"

    serve_song_dongye(ug)  # UG serves the page properly again
    assert night(8)[1][0] == FOUND_TAB
    assert get_song(conn, song.id).status == "found" and pasted_page_problem(conn, song, TAB_PASTED) is None


def test_bare_id_chords_with_a_tab_page_you_pasted(conn, tmp_path):
    ug = FakeUG()
    song = persiana_with_bare_chords(conn, ug)
    pasted = Overrides(artist_url={"soda-stereo": slugged(1081462, "tabs")})

    out = process_song(context(conn, ug.client(tmp_path / "cache"), tmp_path, pasted), song)

    assert ug.requests == [slugged(1081462, "tabs"), artist_list(SODA_URL), f"{TAB}1601640", f"{TAB}1601641"]
    assert out.sheet == 1601640


def test_an_entry_written_as_ug_names_the_artist_serves_the_songs_artist(conn, tmp_path):
    # Copied from UG: "Song Dongye (宋冬野)" = …, for songs of 宋冬野's.
    song = song_by_song_dongye(conn, "斑马斑马")
    ug = FakeUG()
    serve_song_dongye(ug)
    pasted = Overrides(artist_url={"song-dongye-宋冬野": SONG_DONGYE_URL},
                       artist_url_names={"song-dongye-宋冬野": "Song Dongye (宋冬野)"})  # as load_overrides keeps it

    out = process_song(context(conn, ug.client(tmp_path / "cache"), tmp_path, pasted), song)

    assert out.sheet == 4180894


@pytest.mark.parametrize("listed,found", [
    ("De Musica Ligera (Unplugged)", True),  # the same title once Spotify-style suffixes go
    ("De Música Ligeras", True),  # rapidfuzz ratio 97
    ("De Música", False),  # ratio 72: another song
])
def test_titles_match_exactly_or_at_90(conn, tmp_path, listed, found):
    remember_artist_url(conn, "soda-stereo", SODA_URL)
    song = soda_dml(conn)
    ug = FakeUG()
    entry = version_dict(85042, song=listed, artist="Soda Stereo", rating=4.8, votes=277)
    ug.add(artist_list(SODA_URL), artist_page(2946, "Soda Stereo", [entry]))
    ug.tab(entry, content=sheet("sheet 85042", LINES))

    out = process_song(context(conn, ug.client(tmp_path / "cache"), tmp_path), song)

    assert (out.sheet == 85042) is found
    assert get_song(conn, song.id).match_decision == ("accept" if found else "not_found")


def test_exact_titles_win_over_fuzzy_ones(conn, tmp_path):
    remember_artist_url(conn, "soda-stereo", SODA_URL)
    song = soda_dml(conn)
    ug = FakeUG()
    near = version_dict(85000, song="De Música Ligeras", artist="Soda Stereo", rating=5.0, votes=900)
    exact = version_dict(85042, song="De Música Ligera", artist="Soda Stereo", rating=4.0, votes=10)
    ug.add(artist_list(SODA_URL), artist_page(2946, "Soda Stereo", [exact, near]))
    ug.tab(exact, content=sheet("sheet 85042", LINES))

    process_song(context(conn, ug.client(tmp_path / "cache"), tmp_path), song)

    assert {int(r.tab_id) for r in song_versions(conn, song.id)} == {85042}


class Recording:
    """A client that notes the options of every ``get`` before passing it on."""

    def __init__(self, client):
        self.client = client
        self.calls: list[tuple[str, dict]] = []

    @property
    def requests_made(self):
        return self.client.requests_made

    def get(self, url, **options):
        self.calls.append((url, options))
        return self.client.get(url, **options)


def test_artist_pages_are_cached_thirty_days_and_tab_pages_forever(conn, tmp_path):
    song = banma(conn)
    ug = FakeUG()
    serve_banma(ug, [banma_tab(2001234, rating=4.7, votes=50)])
    client = Recording(ug.client(tmp_path / "cache"))

    process_song(context(conn, client, tmp_path, PASTED), song)

    (list_url, listing), (tab_url, tab) = client.calls
    assert (list_url, listing["max_age"]) == (artist_list(BANMA_ARTIST), timedelta(days=30))
    assert 404 in listing["accept"] and 404 in tab["accept"]
    assert (tab_url, tab.get("max_age")) == (f"{TAB}2001234", None)


def test_blocked_ids_are_no_artist_page_candidates(conn, tmp_path):
    song = banma(conn)
    ug = FakeUG()
    serve_banma(ug, [banma_tab(2001234, rating=4.7, votes=50), banma_tab(2001235, version=2, rating=4.2, votes=5)])

    out = process_song(context(conn, ug.client(tmp_path / "cache"), tmp_path,
                               Overrides(artist_url=PASTED.artist_url, block=frozenset({2001234}))), song)

    assert out.sheet == 2001235 and f"{TAB}2001234" not in ug.requests


def test_artist_page_match_resumes_after_the_budget_runs_out(conn, tmp_path):
    song = banma(conn)
    ug = FakeUG()
    serve_banma(ug, [banma_tab(2001234, rating=4.7, votes=50), banma_tab(2001235, version=2, rating=4.2, votes=5)])

    first = fetch_songs(context(conn, ug.client(tmp_path / "cache", budget=2), tmp_path, PASTED), [song])

    half = get_song(conn, song.id)  # matched on the artist page, then the budget ran out
    assert first.budget_exhausted and (half.match_decision, half.match_step, half.ug_dirty) == (
        "accept", "artist_page", True)
    assert [s.id for s in songs_to_fetch(conn, PASTED, NOW)] == [song.id]
    ug.requests.clear()

    fetch_songs(context(conn, ug.client(tmp_path / "cache"), tmp_path, PASTED), [half])

    assert ug.requests == [f"{TAB}2001235"]  # the artist page and the first sheet come from the cache
    assert get_song(conn, song.id).status == "found"


def test_a_learned_artist_page_that_is_gone_is_forgotten(conn, tmp_path):
    index(conn, (1081462, "soda-stereo", "persiana-americana", "tabs"))
    stale = "https://www.ultimate-guitar.com/artist/soda_stereo_1"
    remember_artist_url(conn, "soda-stereo", stale)
    song = soda_dml(conn)
    ug = FakeUG()  # UG answers its 404 page for the stale address, filtered or not

    process_song(context(conn, ug.client(tmp_path / "cache"), tmp_path), song)

    assert ug.requests == [artist_list(stale), artist_page_url(stale)]
    assert learned_artist_url(conn, "soda-stereo") is None  # the next check learns it again
    assert get_song(conn, song.id).match_decision == "not_found"


def test_an_artist_without_chords_is_read_from_its_other_lists(conn, tmp_path):
    # Should UG answer 404 for an empty ?filter=chords, the unfiltered page still names the lists.
    song = banma(conn)
    ug = FakeUG()
    riff_tab = banma_tab(2003000, type="Tabs", rating=4.0, votes=3)
    ug.add(artist_page_url(BANMA_ARTIST), artist_page(1234567, "宋冬野", [riff_tab], kinds=("tabs",)))
    ug.add(artist_list(BANMA_ARTIST, "tabs"), artist_page(1234567, "宋冬野", [riff_tab], kinds=("tabs",)))
    ug.tab(riff_tab, content=riff("banma riff"), artist_url=BANMA_ARTIST)

    out = process_song(context(conn, ug.client(tmp_path / "cache"), tmp_path, PASTED), song)

    assert ug.requests == [artist_list(BANMA_ARTIST), artist_page_url(BANMA_ARTIST),
                           artist_list(BANMA_ARTIST, "tabs"), f"{TAB}2003000"]
    assert out.tab == 2003000 and get_song(conn, song.id).match_step == "artist_page"


def test_artist_list_links_that_all_changed_shape_are_an_error_not_a_miss(conn, tmp_path):
    song = banma(conn)
    ug = FakeUG()
    moved = [banma_tab(2001234, rating=4.7, votes=50, tab_url="https://www.ultimate-guitar.com/tab/2001234"),
             banma_tab(2001300, song="安和桥", tab_url="https://www.ultimate-guitar.com/tab/2001300")]
    ug.add(artist_list(BANMA_ARTIST), artist_page(1234567, "宋冬野", moved))

    stats = fetch_songs(context(conn, ug.client(tmp_path / "cache"), tmp_path, PASTED), [song])

    assert stats.songs_failed == 1
    assert kv_get(conn, f"ug:artist_page_checked:{song.id}") is None  # no check recorded: tried next run
    assert get_song(conn, song.id).match_decision == "not_found"


def test_broken_cached_artist_page_is_fetched_again(conn, tmp_path):
    song = banma(conn)
    ug = FakeUG()
    ug.add(artist_list(BANMA_ARTIST), BROKEN)
    first = fetch_songs(context(conn, ug.client(tmp_path / "cache"), tmp_path, PASTED), [song])
    assert first.songs_failed == 1  # a provider error, not a miss: no check is recorded
    assert kv_get(conn, f"ug:artist_page_checked:{song.id}") is None

    ug.requests.clear()
    serve_banma(ug, [banma_tab(2001234, rating=4.7, votes=50)])
    second = fetch_songs(context(conn, ug.client(tmp_path / "cache"), tmp_path, PASTED), [get_song(conn, song.id)])

    assert (second.songs_done, second.songs_failed) == (1, 0)
    assert ug.requests[0] == artist_list(BANMA_ARTIST)
    assert get_song(conn, song.id).status == "found"


# --- artist-page songs, thirty days on ----------------------------------------------------------

LATER = NOW + timedelta(days=31)


def banma_found(conn, ug, tmp_path, *, kinds=("chords",)):
    """斑马斑马 matched on 宋冬野's artist page (A6) on NOW: 2001234 is kept, 2001235 covers half."""
    song = banma(conn)
    serve_banma(ug, [banma_tab(2001234, rating=4.7, votes=50), banma_tab(2001235, version=2, rating=4.2, votes=5)],
                kinds=kinds)
    process_song(context(conn, ug.client(tmp_path / "cache"), tmp_path, PASTED), song)
    assert "sheet 2001234" in read(tmp_path, song, "sheet.txt")
    ug.requests.clear()
    return get_song(conn, song.id)


def relist_banma(ug, *tabs, kinds=("chords",), page=1, pages=1):
    """宋冬野's chords list as UG shows it thirty days on."""
    ug.add(artist_list(BANMA_ARTIST, page=page),
           artist_page(1234567, "宋冬野", list(tabs), page=page, pages=pages, kinds=kinds))


def test_artist_page_songs_are_checked_again_after_thirty_days(conn, tmp_path):
    # The index can't see a bare id, so no index refresh ever makes 斑马斑马 dirty again.
    song = banma_found(conn, FakeUG(), tmp_path)
    assert get_song(conn, song.id).ug_dirty is False
    assert songs_to_fetch(conn, PASTED, NOW + timedelta(days=29)) == []
    assert [s.id for s in songs_to_fetch(conn, PASTED, NOW + timedelta(days=30))] == [song.id]
    assert [s.id for s in songs_to_fetch(conn, PASTED, LATER)] == [song.id]


def test_ignored_artist_page_songs_are_not_checked_again(conn, tmp_path):
    song = banma_found(conn, FakeUG(), tmp_path)
    assert songs_to_fetch(conn, Overrides(artist_url=PASTED.artist_url, ignore=frozenset({song.key})), LATER) == []


def test_an_artist_page_song_upgrades_on_the_fresh_ratings(conn, tmp_path):
    ug = FakeUG()
    song = banma_found(conn, ug, tmp_path)
    newer = banma_tab(2001236, version=3, rating=4.9, votes=300)
    relist_banma(ug, banma_tab(2001234, rating=4.5, votes=60), banma_tab(2001235, version=2, rating=4.2, votes=6),
                 newer)
    ug.tab(newer, content=sheet("sheet 2001236", BANMA_LINES), artist_url=BANMA_ARTIST)
    (due,) = songs_to_fetch(conn, PASTED, LATER)

    out = process_song(context(conn, ug.client(tmp_path / "cache", now=LATER), tmp_path, PASTED, now=LATER), due)

    # The list is read again (its cached copy is 31 days old); of the tab pages only the new one is asked for.
    assert ug.requests == [artist_list(BANMA_ARTIST), f"{TAB}2001236"]
    assert out.sheet == 2001236 and "sheet 2001236" in read(tmp_path, song, "sheet.txt")
    assert pick_ids(conn, song, "chords") == [2001236]
    rows = {int(r.tab_id): (r.rating, r.votes) for r in song_versions(conn, song.id)}
    assert rows == {2001234: (4.5, 60), 2001235: (4.2, 6), 2001236: (4.9, 300)}
    done = get_song(conn, song.id)
    assert (done.match_decision, done.match_step, done.ug_checked_at) == (
        "accept", "artist_page", "2026-11-18T03:30:00Z")
    assert kv_get(conn, f"ug:artist_page_checked:{song.id}") == "2026-11-18T03:30:00Z"
    assert songs_to_fetch(conn, PASTED, LATER) == []


def test_an_artist_page_song_keeps_its_sheet_when_not_outranked(conn, tmp_path):
    ug = FakeUG()
    song = banma_found(conn, ug, tmp_path)
    path = song_dir(tmp_path / "lib", song) / "sheet.txt"
    before = (path.stat().st_ino, kept_version(conn, song, "sheet.txt"))
    relist_banma(ug, banma_tab(2001234, rating=4.8, votes=80), banma_tab(2001235, version=2, rating=4.6, votes=40))

    out = process_song(context(conn, ug.client(tmp_path / "cache", now=LATER), tmp_path, PASTED, now=LATER),
                       get_song(conn, song.id))

    assert ug.requests == [artist_list(BANMA_ARTIST)]  # both sheets come from the cache
    assert out.sheet == 2001234 and (path.stat().st_ino, kept_version(conn, song, "sheet.txt")) == before
    assert {int(r.tab_id): r.votes for r in song_versions(conn, song.id)} == {2001234: 80, 2001235: 40}


def test_an_artist_page_song_picks_up_a_new_list_of_tabs(conn, tmp_path):
    ug = FakeUG()
    song = banma_found(conn, ug, tmp_path)
    kinds = ("chords", "guitar-pro", "tabs")  # 宋冬野 has a tabs list now, and a Guitar Pro one, never read
    relist_banma(ug, banma_tab(2001234, rating=4.7, votes=50), banma_tab(2001235, version=2, rating=4.2, votes=5),
                 kinds=kinds)
    intro = banma_tab(2003000, type="Tabs", rating=4.0, votes=3)
    ug.add(artist_list(BANMA_ARTIST, "tabs"), artist_page(1234567, "宋冬野", [intro], kinds=kinds))
    ug.tab(intro, content=riff("tab 2003000"), artist_url=BANMA_ARTIST)

    out = process_song(context(conn, ug.client(tmp_path / "cache", now=LATER), tmp_path, PASTED, now=LATER),
                       get_song(conn, song.id))

    assert ug.requests == [artist_list(BANMA_ARTIST), artist_list(BANMA_ARTIST, "tabs"), f"{TAB}2003000"]
    assert out.tab == 2003000 and out.sheet == 2001234


def test_a_stale_artist_page_is_no_answer_once_the_budget_is_spent(conn, tmp_path):
    # PoliteClient serves a copy past its 30 days only when the budget is spent: that is no fresh rating.
    ug = FakeUG()
    song = banma_found(conn, ug, tmp_path)

    stats = fetch_songs(context(conn, ug.client(tmp_path / "cache", budget=0, now=LATER), tmp_path, PASTED,
                                now=LATER), [get_song(conn, song.id)])

    assert stats == FetchStats(songs_done=0, songs_failed=0, budget_exhausted=True)
    assert kv_get(conn, f"ug:artist_page_checked:{song.id}") == "2026-10-18T03:30:00Z"  # still due
    assert [s.id for s in songs_to_fetch(conn, PASTED, LATER)] == [song.id]


def test_a_cached_list_of_unknown_age_is_no_answer_once_the_budget_is_spent(conn, tmp_path):
    # PoliteClient counts a cached copy without its fetch time as stale, and so does the fetch.
    ug = FakeUG()
    song = banma_found(conn, ug, tmp_path)
    for meta in (tmp_path / "cache" / "http" / "ug").rglob("*.json"):
        record = json.loads(meta.read_text(encoding="utf-8"))
        if record["url"] == artist_list(BANMA_ARTIST):
            del record["fetched_at"]
            meta.write_text(json.dumps(record), encoding="utf-8")

    stats = fetch_songs(context(conn, ug.client(tmp_path / "cache", budget=0), tmp_path, PASTED),
                        [get_song(conn, song.id)])

    assert stats.budget_exhausted and ug.requests == []


def test_a_recheck_cut_short_by_the_page_cap_resumes_next_run(conn, tmp_path):
    ug = FakeUG()
    song = banma_found(conn, ug, tmp_path)
    newer = banma_tab(2001236, version=3, rating=4.9, votes=300)
    relist_banma(ug, banma_tab(2001234, rating=4.7, votes=50), banma_tab(2001235, version=2, rating=4.2, votes=5),
                 page=1, pages=2)
    relist_banma(ug, newer, banma_tab(2001400, song="鸽子"), page=2, pages=2)
    ug.tab(newer, content=sheet("sheet 2001236", BANMA_LINES), artist_url=BANMA_ARTIST)

    first = process_song(context(conn, ug.client(tmp_path / "cache", now=LATER), tmp_path, PASTED, now=LATER,
                                 artist_pages_per_kind=1), get_song(conn, song.id))

    assert ug.requests == [artist_list(BANMA_ARTIST)] and first.sheet is None
    assert "sheet 2001234" in read(tmp_path, song, "sheet.txt")  # untouched
    assert [s.id for s in songs_to_fetch(conn, PASTED, LATER)] == [song.id]

    ug.requests.clear()
    second = process_song(context(conn, ug.client(tmp_path / "cache", now=LATER), tmp_path, PASTED, now=LATER,
                                  artist_pages_per_kind=1), get_song(conn, song.id))

    assert ug.requests == [artist_list(BANMA_ARTIST, page=2), f"{TAB}2001236"]
    assert second.sheet == 2001236 and songs_to_fetch(conn, PASTED, LATER) == []


def test_a_recheck_the_budget_cuts_short_resumes_next_run(conn, tmp_path):
    # Live, the budget usually runs out in the middle of a song: here after the list, before the new
    # version's page. The list was read, so the check is recorded; the song must come back anyway.
    ug = FakeUG()
    song = banma_found(conn, ug, tmp_path)
    newer = banma_tab(2001236, version=3, rating=4.9, votes=300)
    relist_banma(ug, banma_tab(2001234, rating=4.7, votes=50), banma_tab(2001235, version=2, rating=4.2, votes=5),
                 newer)
    ug.tab(newer, content=sheet("sheet 2001236", BANMA_LINES), artist_url=BANMA_ARTIST)

    first = fetch_songs(context(conn, ug.client(tmp_path / "cache", budget=1, now=LATER), tmp_path, PASTED,
                                now=LATER), songs_to_fetch(conn, PASTED, LATER))

    assert first.budget_exhausted and ug.requests == [artist_list(BANMA_ARTIST)]
    tomorrow = LATER + timedelta(days=1)
    assert [s.id for s in songs_to_fetch(conn, PASTED, tomorrow)] == [song.id]

    ug.requests.clear()
    fetch_songs(context(conn, ug.client(tmp_path / "cache", now=tomorrow), tmp_path, PASTED, now=tomorrow),
                songs_to_fetch(conn, PASTED, tomorrow))

    assert ug.requests == [f"{TAB}2001236"]  # yesterday's list comes from the cache
    assert "sheet 2001236" in read(tmp_path, song, "sheet.txt")
    assert songs_to_fetch(conn, PASTED, tomorrow) == []


def test_a_recheck_that_no_longer_lists_the_title_leaves_the_match(conn, tmp_path):
    # What the list says no longer is no miss: the versions and the sheet you have stay.
    ug = FakeUG()
    song = banma_found(conn, ug, tmp_path)
    relist_banma(ug, banma_tab(2001300, song="安和桥", rating=4.9, votes=80))

    out = process_song(context(conn, ug.client(tmp_path / "cache", now=LATER), tmp_path, PASTED, now=LATER),
                       get_song(conn, song.id))

    assert out.sheet == 2001234 and ug.requests == [artist_list(BANMA_ARTIST)]
    done = get_song(conn, song.id)
    assert (done.match_decision, done.match_step, done.status) == ("accept", "artist_page", "found")
    assert {int(r.tab_id) for r in song_versions(conn, song.id)} == {2001234, 2001235}
    assert songs_to_fetch(conn, PASTED, LATER) == []  # checked; again in thirty days


@pytest.mark.parametrize("status,body", [(500, "Internal Server Error"), (200, BROKEN)])
def test_an_error_on_the_recheck_changes_nothing(conn, tmp_path, status, body):
    ug = FakeUG()
    song = banma_found(conn, ug, tmp_path)
    ug.add(artist_list(BANMA_ARTIST), body, status=status)

    stats = fetch_songs(context(conn, ug.client(tmp_path / "cache", now=LATER), tmp_path, PASTED, now=LATER),
                        [get_song(conn, song.id)])

    assert stats.songs_failed == 1
    same = get_song(conn, song.id)
    assert (same.match_decision, same.match_step, same.status) == ("accept", "artist_page", "found")
    assert "sheet 2001234" in read(tmp_path, song, "sheet.txt")
    assert kv_get(conn, f"ug:artist_page_checked:{song.id}") == "2026-10-18T03:30:00Z"  # still due
    assert [s.id for s in songs_to_fetch(conn, PASTED, LATER)] == [song.id]


# --- bare-id chords of a song the index matched -----------------------------------------------------


def bare_chords(*specs):
    """Persiana Americana chords as UG lists bare-id tabs: ``(tab_id, version, rating, votes)`` each."""
    return [v(t, version=n, rating=r, votes=c, tab_url=f"{TAB}{t}") for t, n, r, c in specs]


def persiana_with_bare_chords(conn, ug):
    """Persiana Americana: its tabs are slugged, so the index matched it, but its chords are bare ids."""
    song = accepted(conn)
    index(conn, (1081462, "soda-stereo", "persiana-americana", "tabs"))
    ug.tab(v(1081462, "tabs"), content=riff("persiana riff"))
    best, other = bare_chords((1601640, 1, 4.8, 40), (1601641, 2, 4.1, 9))
    signos = version_dict(1601700, song="Signos", artist="Soda Stereo", tab_url=f"{TAB}1601700")
    soda_chords(ug, best, other, signos)  # sorted by title, as UG lists them
    ug.tab(best, [other], content=sheet("sheet 1601640", LINES))
    ug.tab(other, [best], content=sheet("sheet 1601641", LINES[:3]))
    return song


def test_bare_id_chords_of_a_matched_song_come_from_its_artist_page(conn, tmp_path):
    ug = FakeUG()
    song = persiana_with_bare_chords(conn, ug)

    out = process_song(context(conn, ug.client(tmp_path / "cache"), tmp_path), song)

    # The song's own tab page names the artist page; the tab slot needs that page anyway.
    assert ug.requests == [slugged(1081462, "tabs"), artist_list(SODA_URL), f"{TAB}1601640", f"{TAB}1601641"]
    assert out.sheet == 1601640 and out.tab == 1081462
    assert "sheet 1601640" in read(tmp_path, song, "sheet.txt")
    assert coverages(conn, song) == {1081462: None, 1601640: 1.0, 1601641: pytest.approx(0.3)}
    done = get_song(conn, song.id)
    assert (done.status, done.match_step, done.ug_dirty) == ("found", "exact", False)  # still the index's match
    assert kv_get(conn, f"ug:artist_page_checked:{song.id}") == "2026-10-18T03:30:00Z"


def test_bare_id_chords_with_the_artist_page_you_pasted(conn, tmp_path):
    ug = FakeUG()
    song = persiana_with_bare_chords(conn, ug)
    overrides = Overrides(artist_url={"soda-stereo": SODA_URL})

    out = process_song(context(conn, ug.client(tmp_path / "cache"), tmp_path, overrides), song)

    assert ug.requests == [artist_list(SODA_URL), f"{TAB}1601640", f"{TAB}1601641", slugged(1081462, "tabs")]
    assert out.sheet == 1601640


def test_one_chords_list_serves_every_song_by_the_artist(conn, tmp_path):
    ug = FakeUG()
    persiana = persiana_with_bare_chords(conn, ug)
    signos = accepted(conn, "Soda Stereo", "Signos", "soda-stereo", "signos", added_at="2026-09-01T00:00:00Z")
    index(conn, (1081500, "soda-stereo", "signos", "tabs"))
    ug.tab(version_dict(1081500, type="Tabs", song="Signos", artist="Soda Stereo",
                        tab_url=slugged(1081500, "tabs", song="signos")), content=riff("signos riff"))
    ug.tab(version_dict(1601700, song="Signos", artist="Soda Stereo", tab_url=f"{TAB}1601700"),
           content=sheet("sheet 1601700", LINES))

    stats = fetch_songs(context(conn, ug.client(tmp_path / "cache"), tmp_path), [persiana, signos])

    assert stats.songs_done == 2 and ug.requests.count(artist_list(SODA_URL)) == 1  # cached for 30 days
    assert "sheet 1601700" in read(tmp_path, signos, "sheet.txt")


def test_when_every_indexed_chords_tab_is_gone_the_artist_page_is_read(conn, tmp_path):
    ug = FakeUG()
    song = persiana_with_bare_chords(conn, ug)
    index(conn, (101, "soda-stereo", "persiana-americana", "chords"))  # UG has removed it: its 404 page
    remember_artist_url(conn, "soda-stereo", SODA_URL)

    out = process_song(context(conn, ug.client(tmp_path / "cache"), tmp_path), song)

    assert ug.requests[:3] == [slugged(101), artist_list(SODA_URL), f"{TAB}1601640"]
    assert out.sheet == 1601640


def test_indexed_chords_keep_the_artist_page_out_of_it(conn, tmp_path):
    song = accepted(conn)
    index(conn, (101, "soda-stereo", "persiana-americana", "chords"),
          (1081462, "soda-stereo", "persiana-americana", "tabs"))
    remember_artist_url(conn, "soda-stereo", SODA_URL)
    ug = FakeUG()
    ug.tab(v(101), content=sheet("sheet 101", LINES))
    ug.tab(v(1081462, "tabs"), content=riff("persiana riff"))

    process_song(context(conn, ug.client(tmp_path / "cache"), tmp_path), song)

    assert ug.requests == [slugged(101), slugged(1081462, "tabs")]


def test_without_a_known_or_learnable_artist_page_the_sheet_slot_waits(conn, tmp_path):
    # The song's own pages don't link the artist page: nothing more is asked, and the song is
    # looked up again in thirty days.
    song = accepted(conn)
    index(conn, (1081462, "soda-stereo", "persiana-americana", "tabs"))
    ug = FakeUG()
    ug.tab(v(1081462, "tabs"), content=riff("persiana riff"), artist_url=None)

    out = process_song(context(conn, ug.client(tmp_path / "cache"), tmp_path), song)

    assert ug.requests == [slugged(1081462, "tabs")] and (out.sheet, out.tab) == (None, 1081462)
    assert get_song(conn, song.id).ug_dirty is False
    assert songs_to_fetch(conn, Overrides(), NOW + timedelta(days=29)) == []
    assert [s.id for s in songs_to_fetch(conn, Overrides(), LATER)] == [song.id]


def test_songs_with_bare_id_chords_are_checked_again_after_thirty_days(conn, tmp_path):
    ug = FakeUG()
    song = persiana_with_bare_chords(conn, ug)
    process_song(context(conn, ug.client(tmp_path / "cache"), tmp_path), song)
    # A song whose chords the index lists keeps no reason to be checked, even with an old check
    # from the days it was not found.
    signos = accepted(conn, "Soda Stereo", "Signos", "soda-stereo", "signos", added_at="2026-09-01T00:00:00Z")
    index(conn, (901, "soda-stereo", "signos", "chords"))
    update_song(conn, signos.id, ug_dirty=False)
    kv_set(conn, f"ug:artist_page_checked:{signos.id}", "2026-08-01T03:30:00Z")

    assert songs_to_fetch(conn, Overrides(), NOW + timedelta(days=29)) == []
    assert [s.id for s in songs_to_fetch(conn, Overrides(), LATER)] == [song.id]


def test_a_song_with_bare_id_chords_upgrades_from_the_fresh_chords_list(conn, tmp_path):
    ug = FakeUG()
    song = persiana_with_bare_chords(conn, ug)
    process_song(context(conn, ug.client(tmp_path / "cache"), tmp_path), song)
    newer = bare_chords((1601650, 3, 4.95, 500))[0]
    soda_chords(ug, *bare_chords((1601640, 1, 4.7, 44), (1601641, 2, 4.1, 9)), newer)
    ug.tab(newer, content=sheet("sheet 1601650", LINES))
    ug.requests.clear()
    (due,) = songs_to_fetch(conn, Overrides(), LATER)

    out = process_song(context(conn, ug.client(tmp_path / "cache", now=LATER), tmp_path, now=LATER), due)

    assert ug.requests == [artist_list(SODA_URL), f"{TAB}1601650"]
    assert out.sheet == 1601650 and "sheet 1601650" in read(tmp_path, song, "sheet.txt")
    assert {int(r.tab_id): r.votes for r in song_versions(conn, song.id, kinds=["chords"])} == {
        1601640: 44, 1601641: 9, 1601650: 500}
    assert songs_to_fetch(conn, Overrides(), LATER) == []


def test_a_chords_list_cut_short_leaves_the_song_for_the_next_run(conn, tmp_path):
    song = accepted(conn)
    index(conn, (1081462, "soda-stereo", "persiana-americana", "tabs"))
    remember_artist_url(conn, "soda-stereo", SODA_URL)
    ug = FakeUG()
    ug.tab(v(1081462, "tabs"), content=riff("persiana riff"))
    best, other = bare_chords((1601640, 1, 4.8, 40), (1601641, 2, 4.1, 9))
    ug.add(artist_list(SODA_URL), artist_page(2946, "Soda Stereo", [best], pages=2))
    ug.add(artist_list(SODA_URL, page=2), artist_page(2946, "Soda Stereo", [other], page=2, pages=2))
    ug.tab(best, [other], content=sheet("sheet 1601640", LINES))

    first = process_song(context(conn, ug.client(tmp_path / "cache"), tmp_path, artist_pages_per_kind=1), song)

    assert ug.requests == [artist_list(SODA_URL)] and first == SongFetchOutcome(song.id, None, None, 1)
    pending = get_song(conn, song.id)  # neither checked nor clean: the rest of the list next run
    assert pending.ug_dirty is True and kv_get(conn, f"ug:artist_page_checked:{song.id}") is None

    ug.requests.clear()
    second = process_song(context(conn, ug.client(tmp_path / "cache"), tmp_path, artist_pages_per_kind=1),
                          pending)

    assert ug.requests[0] == artist_list(SODA_URL, page=2)
    assert second.sheet == 1601640 and get_song(conn, song.id).ug_dirty is False


def test_an_error_on_the_chords_list_is_no_miss(conn, tmp_path):
    ug = FakeUG()
    song = persiana_with_bare_chords(conn, ug)
    ug.add(artist_list(SODA_URL), "Internal Server Error", status=500)

    stats = fetch_songs(context(conn, ug.client(tmp_path / "cache"), tmp_path), [song])

    assert stats.songs_failed == 1
    failed = get_song(conn, song.id)
    assert (failed.match_decision, failed.ug_dirty, failed.ug_checked_at) == ("accept", True, None)
    assert kv_get(conn, f"ug:artist_page_checked:{song.id}") is None


# --- sheets from elsewhere: auto-chords, LaCuerda, and blocks ----------------------------------------


def keep_other_sheet(conn, tmp_path, song, *, provider, kind, name, coverage=None, tab_id=None):
    """A sheet another step kept: auto-chords' 'sheet (auto).txt', or LaCuerda's sheet.txt."""
    vid = upsert_version(conn, provider=provider, tab_id=tab_id or f"{provider}-1", song_id=song.id, slot="sheet",
                         kind=kind,
                         rating=0, votes=0, version=1, label=None, url=f"https://example.invalid/{provider}",
                         raw={}, now="2026-10-01T00:00:00Z")
    set_coverage(conn, vid, coverage)
    keep_file(conn, tmp_path / "lib", song=song, version_id=vid, name=name, data=f"{provider} sheet".encode(), rank=1)
    set_picks(conn, song.id, (kind,), [vid])
    return vid


def names(conn, song):
    return {f.name for f in kept_files(conn, song.id)}


@pytest.mark.parametrize("lines,dropped", [(LINES, True), (LINES[:3], False)])
def test_auto_sheet_dropped_when_a_complete_human_sheet_arrives(conn, tmp_path, lines, dropped):
    song = accepted(conn)
    keep_other_sheet(conn, tmp_path, song, provider="auto", kind="auto", name="sheet (auto).txt")
    index(conn, (101, "soda-stereo", "persiana-americana", "chords"))
    ug = FakeUG()
    ug.tab(v(101), content=sheet("sheet 101", lines))

    process_song(context(conn, ug.client(tmp_path / "cache"), tmp_path), song)

    assert "sheet.txt" in names(conn, song)
    assert ("sheet (auto).txt" not in names(conn, song)) is dropped
    assert (song_dir(tmp_path / "lib", song) / "sheet (auto).txt").exists() is not dropped
    # Either way the human sheet is the slot's only pick; a partial one leaves the auto file as a fallback.
    assert pick_ids(conn, song, "chords", "acordes", "auto") == [101]
    info = json.loads(read(tmp_path, song, "info.json"))
    assert ("sheet (auto).txt" in {f["name"] for f in info["files"]}) is not dropped


def test_a_kept_sheet_found_complete_later_retires_the_auto_sheet(conn, tmp_path):
    # Kept beside the auto sheet while the lyrics were pending; with them it proves complete.
    song = accepted(conn, plain=None)
    keep_other_sheet(conn, tmp_path, song, provider="auto", kind="auto", name="sheet (auto).txt")
    index(conn, (101, "soda-stereo", "persiana-americana", "chords"))
    ug = FakeUG()
    ug.tab(v(101), content=sheet("sheet 101", LINES))
    process_song(context(conn, ug.client(tmp_path / "cache"), tmp_path), song)
    assert names(conn, song) == {"sheet.txt", "sheet.json", "sheet (auto).txt"}

    update_song(conn, song.id, lyrics_status="found", lyrics_json=lyrics_json(LYRICS), ug_dirty=True)
    ug.requests.clear()
    process_song(context(conn, ug.client(tmp_path / "cache"), tmp_path), get_song(conn, song.id))

    assert ug.requests == []  # the sheet's page comes from the cache
    assert names(conn, song) == {"sheet.txt", "sheet.json"}
    assert not (song_dir(tmp_path / "lib", song) / "sheet (auto).txt").exists()
    assert pick_ids(conn, song, "chords", "acordes", "auto") == [101]


@pytest.mark.parametrize("lacuerda,ug_lines,replaced", [
    (1.0, LINES[:3], False),  # a complete LaCuerda sheet beats a partial UG one (0.3)
    (1.0, None, False),  # ...and one of unknown coverage
    (1.0, LINES, False),  # ratings can't be compared across sites: a tie keeps what you have
    (0.5, LINES, True),  # a complete UG sheet beats a partial LaCuerda one
    (None, LINES, True),  # ...and one of unknown coverage, which isn't complete
    (0.2, LINES[:3], True),  # of two partial sheets, the one covering more wins
    (0.5, LINES[:3], False),
    (0.3, LINES[:3], False),  # a tie keeps what you have
    (None, LINES[:3], False),  # a partial sheet never displaces one that may be complete
    (0.5, None, False),  # unknown coverage never displaces a known partial sheet
    (None, None, False),
])
def test_a_ug_sheet_meets_a_lacuerda_sheet_on_coverage_alone(conn, tmp_path, lacuerda, ug_lines, replaced):
    # ug_lines=None: the song has no lyrics yet, so UG's sheet can't be scored.
    song = accepted(conn, plain=None) if ug_lines is None else accepted(conn)
    keep_other_sheet(conn, tmp_path, song, provider="lacuerda", kind="acordes", name="sheet.txt", coverage=lacuerda)
    index(conn, (101, "soda-stereo", "persiana-americana", "chords"))
    ug = FakeUG()
    ug.tab(v(101), content=sheet("sheet 101", ug_lines or LINES))

    out = process_song(context(conn, ug.client(tmp_path / "cache"), tmp_path), song)

    text = read(tmp_path, song, "sheet.txt")
    assert ("sheet 101" in text) is replaced and ("lacuerda sheet" in text) is not replaced
    assert (out.sheet == 101) is replaced
    assert pick_ids(conn, song, "chords") == ([101] if replaced else [])
    assert len(picks(conn, song.id, ("acordes",))) == (0 if replaced else 1)


def test_a_ug_sheet_you_pinned_replaces_even_a_complete_lacuerda_sheet(conn, tmp_path):
    # [pin] is your decision: the coverage rule only settles what caracole chooses itself.
    song = accepted(conn)
    keep_other_sheet(conn, tmp_path, song, provider="lacuerda", kind="acordes", name="sheet.txt", coverage=1.0)
    index(conn, (101, "soda-stereo", "persiana-americana", "chords"))
    ug = FakeUG()
    ug.tab(v(101), content=sheet("sheet 101", LINES[:3]))

    out = process_song(context(conn, ug.client(tmp_path / "cache"), tmp_path, Overrides(pin={song.key: (101,)})),
                       song)

    assert out.sheet == 101 and "sheet 101" in read(tmp_path, song, "sheet.txt")
    assert pick_ids(conn, song, "chords", "acordes", "auto") == [101]


def test_a_lacuerda_sheet_you_picked_stays_whatever_ugs_covers(conn, tmp_path):
    # [lacuerda] is your decision too: UG's complete sheet never replaces the partial one you picked there.
    from caracole.overrides import LaCuerdaPick

    song = accepted(conn)
    keep_other_sheet(conn, tmp_path, song, provider="lacuerda", kind="acordes", name="sheet.txt", coverage=0.2,
                     tab_id="soda_stereo/persiana_americana-2")
    index(conn, (101, "soda-stereo", "persiana-americana", "chords"))
    ug = FakeUG()
    ug.tab(v(101), content=sheet("sheet 101", LINES))
    picked = Overrides(lacuerda={song.key: LaCuerdaPick("soda_stereo", "persiana_americana")})

    out = process_song(context(conn, ug.client(tmp_path / "cache"), tmp_path, picked), song)

    assert out.sheet is None and read(tmp_path, song, "sheet.txt") == "lacuerda sheet"
    assert len(picks(conn, song.id, ("acordes",))) == 1
    # Another version than the one picked is LaCuerda's like any: the coverage decides.
    other = Overrides(lacuerda={song.key: LaCuerdaPick("soda_stereo", "persiana_americana", 3)})
    update_song(conn, song.id, ug_dirty=True)
    out = process_song(context(conn, ug.client(tmp_path / "cache"), tmp_path, other), get_song(conn, song.id))
    assert out.sheet == 101 and "sheet 101" in read(tmp_path, song, "sheet.txt")


def test_a_kept_ug_sheet_becomes_the_only_pick_of_the_sheet_slot(conn, tmp_path):
    # Picks are cleared across every sheet kind: chords, acordes and auto.
    song = accepted(conn)
    keep_other_sheet(conn, tmp_path, song, provider="lacuerda", kind="acordes", name="sheet.txt", coverage=0.2)
    keep_other_sheet(conn, tmp_path, song, provider="auto", kind="auto", name="sheet (auto).txt")
    index(conn, (101, "soda-stereo", "persiana-americana", "chords"))
    ug = FakeUG()
    ug.tab(v(101), content=sheet("sheet 101", LINES[:5]))

    process_song(context(conn, ug.client(tmp_path / "cache"), tmp_path), song)

    assert "sheet 101" in read(tmp_path, song, "sheet.txt")
    assert pick_ids(conn, song, "chords", "acordes", "auto") == [101]
    assert "sheet (auto).txt" in names(conn, song)  # a partial sheet leaves the auto sheet's file in place


def test_kept_files_of_a_tab_blocked_later_are_dropped_when_nothing_replaces_them(conn, tmp_path):
    song = accepted(conn)
    index(conn, (101, "soda-stereo", "persiana-americana", "chords"), (401, "soda-stereo", "persiana-americana", "tabs"))
    ug = FakeUG()
    ug.tab(v(101), content=sheet("sheet 101", LINES))
    ug.tab(v(401, "tabs"), content=riff("tab 401"))
    process_song(context(conn, ug.client(tmp_path / "cache"), tmp_path), song)
    assert names(conn, song) == {"sheet.txt", "sheet.json", "tab.txt", "tab.json"}

    update_song(conn, song.id, ug_dirty=True)  # you added both to [block]
    process_song(context(conn, ug.client(tmp_path / "cache"), tmp_path, Overrides(block=frozenset({101, 401}))),
                 get_song(conn, song.id))

    assert names(conn, song) == set()
    assert not (song_dir(tmp_path / "lib", song) / "sheet.txt").exists()
    assert get_song(conn, song.id).status == "wanted"
    assert pick_ids(conn, song, "chords", "tabs") == []


def test_sheet_json_carries_the_page_meta(conn, tmp_path):
    # The renderer reads the capo from it.
    song = accepted(conn)
    index(conn, (101, "soda-stereo", "persiana-americana", "chords"))
    ug = FakeUG()
    ug.tab(v(101), content=sheet("sheet 101", LINES), meta={"capo": 2, "tonality": "Am"})

    process_song(context(conn, ug.client(tmp_path / "cache"), tmp_path), song)

    assert json.loads(read(tmp_path, song, "sheet.json"))["meta"] == {"capo": 2, "tonality": "Am"}


TITLE_ONLY_COVER = [{"artist_key": "os-paralamas-do-sucesso", "song_key": "de-musica-ligeira", "score": 97.0,
                     "step": "title_only"}]


def test_title_only_reviews_are_tried_on_the_artist_page(conn):
    # On the real index De Música Ligera ends as a title-only review of a Portuguese cover,
    # because every tab of Soda Stereo's own song is a bare id.
    index(conn, (7, "soda-stereo", "signos", "chords"))
    cover = matched(conn, "Soda Stereo", "De Música Ligera", "review", added_at="2026-10-05T00:00:00Z",
                    match_candidates=TITLE_ONLY_COVER)
    matched(conn, "Soda Stereo", "Zoom", "review", added_at="2026-10-06T00:00:00Z", match_candidates=[
        {"artist_key": "soda-stereo", "song_key": "zoom-2", "score": 80.0, "step": "fuzzy_title"}])
    assert [s.id for s in songs_to_fetch(conn, Overrides(), NOW)] == [cover.id]


def test_reviews_of_names_not_quite_ugs_are_tried_on_the_artist_page_too(conn):
    # A review made only of the matcher's tolerant steps (match.REVIEW_ONLY_STEPS) is no more sure than
    # one on the title alone: the artist's page, with its bare-id tabs, may still have the song itself.
    index(conn, (7, "soda-stereo", "signos", "chords"))
    near = [{"artist_key": "misc-soundtrack", "song_key": "soda-stereo-de-musica-ligera", "score": 100.0,
             "step": "catch_all"},
            {"artist_key": "soda-stereo", "song_key": "de-musica-ligera-en-vivo-1997", "score": 85.0,
             "step": "word_title"},
            {"artist_key": "soda-stereos", "song_key": "de-musica-ligera", "score": 100.0, "step": "typo_artist"},
            *TITLE_ONLY_COVER]
    tolerant = matched(conn, "Soda Stereo", "De Música Ligera", "review", added_at="2026-10-05T00:00:00Z",
                       match_candidates=near)
    matched(conn, "Soda Stereo", "Zoom", "review", added_at="2026-10-06T00:00:00Z", match_candidates=[
        {"artist_key": "soda-stereo", "song_key": "zoom-2", "score": 80.0, "step": "fuzzy_title"}, *near])
    assert needs_artist_page(tolerant)
    assert [s.id for s in songs_to_fetch(conn, Overrides(), NOW)] == [tolerant.id]


def test_title_only_review_resolved_on_the_artist_page(conn, tmp_path):
    index(conn, (1081462, "soda-stereo", "persiana-americana", "tabs"))
    song = soda_dml(conn)
    update_song(conn, song.id, match_decision="review", review=True, match_candidates=TITLE_ONLY_COVER)
    song = get_song(conn, song.id)
    ug = FakeUG()
    ug.tab(v(1081462, "tabs"), [v(1081470, "tabs", version=2)], content=riff("persiana riff"))
    serve_dml(ug)

    process_song(context(conn, ug.client(tmp_path / "cache"), tmp_path), song)

    done = get_song(conn, song.id)
    assert (done.match_decision, done.match_step, done.review) == ("accept", "artist_page", False)
    assert "sheet 85042" in read(tmp_path, song, "sheet.txt")


# --- [reject] on the artist page, and what an undone match kept ----------------------------------

REJECT_DML = '[reject]\n"Soda Stereo - De Música Ligera" = "soda-stereo/de-musica-ligera"\n'


def overrides_from(tmp_path, toml):
    path = tmp_path / "overrides.toml"
    path.write_text(toml, encoding="utf-8")
    return load_overrides(path)


def test_a_ug_song_you_rejected_is_no_match_on_the_artist_page(conn, tmp_path):
    # "None of these" in `caracole review` leaves the song not found, and its artist's page is read for it.
    index(conn, (1081462, "soda-stereo", "persiana-americana", "tabs"))
    song = soda_dml(conn)
    ug = FakeUG()
    ug.tab(v(1081462, "tabs"), content=riff("persiana riff"))
    serve_dml(ug)

    out = process_song(context(conn, ug.client(tmp_path / "cache"), tmp_path, overrides_from(tmp_path, REJECT_DML)),
                       song)

    done = get_song(conn, song.id)
    assert (done.match_decision, out.sheet, names(conn, song)) == ("not_found", None, set())
    assert kv_get(conn, f"ug:artist_page_checked:{song.id}") == "2026-10-18T03:30:00Z"  # again in 30 days


def test_the_artist_pages_other_titles_still_compete_once_you_reject_one(conn, tmp_path):
    # As in the matcher, a rejected UG song drops out before the title is chosen: here the near title
    # is left to lead, where the exact one you rejected would have hidden it.
    song = matched(conn, "Soda Stereo", "Persiana Americana", "not_found", added_at="2026-10-17T00:00:00Z")
    remember_artist_url(conn, "soda-stereo", SODA_URL)
    exact = v(1601640, tab_url=f"{TAB}1601640")
    near = version_dict(1601700, song="Persiana Americanas", artist="Soda Stereo")
    ug = FakeUG()
    ug.add(artist_list(SODA_URL), artist_page(2946, "Soda Stereo", [exact, near]))
    ug.tab(near, content=sheet("sheet 1601700", LINES))
    overrides = overrides_from(tmp_path, '[reject]\n"Soda Stereo - Persiana Americana" = "soda-stereo/persiana-americana"\n')

    process_song(context(conn, ug.client(tmp_path / "cache"), tmp_path, overrides), song)

    done = get_song(conn, song.id)
    assert (done.match_decision, done.match_step, done.match_song_key) == ("accept", "artist_page", "persiana-americanas")


def dml_found_on_its_artist_page(conn, tmp_path, ug):
    """De Música Ligera accepted on Soda Stereo's artist page (A6): sheet 85042, which covers half the
    lyrics so the auto sheet stays beside it, and tab 85100. A Guitar Pro file you filed from the inbox is
    there too, and a file of yours caracole doesn't track."""
    song = soda_dml(conn)
    remember_artist_url(conn, "soda-stereo", SODA_URL)
    dml = {"song": "De Música Ligera", "artist": "Soda Stereo", "song_id": 67588}
    chords, tab = version_dict(85042, **dml), version_dict(85100, type="Tabs", **dml)
    kinds = ("chords", "tabs")
    ug.add(artist_list(SODA_URL), artist_page(2946, "Soda Stereo", [chords], kinds=kinds))
    ug.add(artist_list(SODA_URL, "tabs"), artist_page(2946, "Soda Stereo", [tab], kinds=kinds))
    ug.tab(chords, content=sheet("sheet 85042", LINES[:5]))
    ug.tab(tab, content=riff("tab 85100"))
    keep_other_sheet(conn, tmp_path, song, provider="auto", kind="auto", name="sheet (auto).txt")
    process_song(context(conn, ug.client(tmp_path / "cache"), tmp_path), song)
    gp = upsert_version(conn, provider="inbox", tab_id="guitar-pro", song_id=song.id, slot="guitar",
                        kind="guitar-pro", rating=0, votes=0, version=1, label=None, url="", raw={},
                        now="2026-10-18T03:30:00Z")
    keep_file(conn, tmp_path / "lib", song=song, version_id=gp, name="guitar-1.gp5", data=b"GP5 bytes", rank=1)
    (song_dir(tmp_path / "lib", song) / "notes.txt").write_text("yours", encoding="utf-8")
    done = get_song(conn, song.id)
    assert (done.match_step, names(conn, song)) == (
        "artist_page", {"sheet.txt", "sheet.json", "tab.txt", "tab.json", "sheet (auto).txt", "guitar-1.gp5"})
    ug.requests.clear()
    return done


def test_a_match_you_reject_takes_its_sheet_and_tab_with_it(conn, tmp_path):
    ug = FakeUG()
    song = dml_found_on_its_artist_page(conn, tmp_path, ug)
    folder = song_dir(tmp_path / "lib", song)
    overrides = overrides_from(tmp_path, REJECT_DML)
    match_all(conn, overrides, MatchPolicy())
    assert get_song(conn, song.id).match_decision == "not_found"

    # Its artist page was read today, so no check is due: what the undone match kept brings it back.
    assert [s.id for s in songs_to_fetch(conn, overrides, NOW)] == [song.id]
    fetch_songs(context(conn, ug.client(tmp_path / "cache"), tmp_path, overrides),
                songs_to_fetch(conn, overrides, NOW))

    done = get_song(conn, song.id)
    assert (done.match_decision, done.status) == ("not_found", "found")  # the auto sheet is what is left
    assert names(conn, song) == {"sheet (auto).txt", "guitar-1.gp5"}  # the Guitar Pro file is yours
    assert sorted(p.name for p in folder.iterdir()) == ["guitar-1.gp5", "info.json", "notes.txt", "sheet (auto).txt"]
    assert json.loads(read(tmp_path, song, "info.json"))["status"] == "found"
    assert ug.requests == [] and songs_to_fetch(conn, overrides, NOW) == []

    # Thirty days on its artist page is read again, and what you rejected is still not the song.
    later = NOW + timedelta(days=31)
    assert [s.id for s in songs_to_fetch(conn, overrides, later)] == [song.id]
    fetch_songs(context(conn, ug.client(tmp_path / "cache", now=later), tmp_path, overrides, now=later),
                songs_to_fetch(conn, overrides, later))
    assert artist_list(SODA_URL) in ug.requests
    assert (get_song(conn, song.id).match_decision, names(conn, song)) == ("not_found", {"sheet (auto).txt", "guitar-1.gp5"})


def test_a_match_you_reject_for_a_review_loses_its_sheet_without_a_request(conn, tmp_path):
    # What the matcher has left is a near title of the song's own artist, for you to review: nothing to
    # fetch, and the rejected UG song's sheet and tab are no sheet of this song.
    from caracole.ug.index import mark_built

    song, ug = fetched_persiana(conn, tmp_path)
    index(conn, (102, "soda-stereo", "persiana-am", "chords"))  # 76 against persiana-americana
    mark_built(conn, NOW)
    overrides = overrides_from(tmp_path, '[reject]\n"Soda Stereo - Persiana Americana" = "soda-stereo/persiana-americana"\n')
    match_all(conn, overrides, MatchPolicy())
    assert (get_song(conn, song.id).match_decision, get_song(conn, song.id).match_song_key) == ("review", "persiana-am")

    assert [s.id for s in songs_to_fetch(conn, overrides, NOW)] == [song.id]
    fetch_songs(context(conn, ug.client(tmp_path / "cache"), tmp_path, overrides),
                songs_to_fetch(conn, overrides, NOW))

    assert (names(conn, song), get_song(conn, song.id).status) == (set(), "wanted")
    assert ug.requests == [] and songs_to_fetch(conn, overrides, NOW) == []


def test_a_lacuerda_sheet_stays_when_a_rejected_match_takes_its_tab(conn, tmp_path):
    from caracole.ug.index import mark_built

    song = accepted(conn)
    index(conn, (401, "soda-stereo", "persiana-americana", "tabs"))
    mark_built(conn, NOW)
    keep_other_sheet(conn, tmp_path, song, provider="lacuerda", kind="acordes", name="sheet.txt", coverage=1.0)
    ug = FakeUG()
    ug.tab(v(401, "tabs"), content=riff("tab 401"))
    soda_chords(ug)
    process_song(context(conn, ug.client(tmp_path / "cache"), tmp_path), song)
    assert names(conn, song) == {"sheet.txt", "tab.txt", "tab.json"}
    overrides = overrides_from(tmp_path, '[reject]\n"Soda Stereo - Persiana Americana" = "soda-stereo/persiana-americana"\n')
    match_all(conn, overrides, MatchPolicy())

    fetch_songs(context(conn, ug.client(tmp_path / "cache"), tmp_path, overrides),
                songs_to_fetch(conn, overrides, NOW))

    assert names(conn, song) == {"sheet.txt"} and read(tmp_path, song, "sheet.txt") == "lacuerda sheet"
    assert (get_song(conn, song.id).match_decision, get_song(conn, song.id).status) == ("not_found", "found")


def test_a_rejected_match_leaves_a_song_without_any_sheet_wanted(conn, tmp_path):
    ug = FakeUG()
    song = dml_found_on_its_artist_page(conn, tmp_path, ug)
    drop_file(conn, tmp_path / "lib", song=song, name="sheet (auto).txt")
    overrides = overrides_from(tmp_path, REJECT_DML)
    match_all(conn, overrides, MatchPolicy())

    fetch_songs(context(conn, ug.client(tmp_path / "cache"), tmp_path, overrides),
                songs_to_fetch(conn, overrides, NOW))

    assert (get_song(conn, song.id).status, names(conn, song)) == ("wanted", {"guitar-1.gp5"})


# --- sheets kept before their lyrics -------------------------------------------------------------


def keep_sheet(conn, tmp_path, song, content, *, coverage=None):
    """A LaCuerda sheet as its step keeps it: sheet.json (with the markup) and sheet.txt."""
    url = "https://acordes.lacuerda.net/soda_stereo/persiana_americana-2.shtml"
    vid = upsert_version(conn, provider="lacuerda", tab_id="soda_stereo/persiana_americana-2", song_id=song.id,
                         slot="sheet", kind="acordes", rating=0, votes=0, version=2, label=None, url=url,
                         raw={}, now="2026-10-01T00:00:00Z")
    set_coverage(conn, vid, coverage)
    doc = {"provider": "lacuerda", "url": url, "content": content, "version": 2}
    files = {"sheet.json": json.dumps(doc, ensure_ascii=False), "sheet.txt": strip_markup(content)}
    for name, text in files.items():
        keep_file(conn, tmp_path / "lib", song=song, version_id=vid, name=name, data=text.encode(), rank=1)
    set_picks(conn, song.id, ("acordes",), [vid])
    return vid


def rescore(conn, tmp_path, **policy):
    return rescore_kept_sheets(conn, tmp_path / "lib", RankPolicy(**policy))


def sheet_kinds_picked(conn, song):
    return [r.kind for r in picks(conn, song.id, ("chords", "acordes", "auto"))]


def test_a_sheet_kept_before_its_lyrics_is_scored_once_they_arrive(conn, tmp_path):
    song = accepted(conn, plain=None)  # LRCLIB hadn't answered when the sheet was kept
    index(conn, (101, "soda-stereo", "persiana-americana", "chords"))
    ug = FakeUG()
    ug.tab(v(101), content=sheet("sheet 101", LINES[:3]))
    process_song(context(conn, ug.client(tmp_path / "cache"), tmp_path), song)
    assert coverages(conn, song) == {101: None}

    update_song(conn, song.id, lyrics_status="found", lyrics_json=lyrics_json(LYRICS))
    assert rescore(conn, tmp_path) == 1  # no client: nothing is asked of any site

    assert coverages(conn, song) == {101: pytest.approx(0.3)}
    info = json.loads(read(tmp_path, song, "info.json"))
    assert {f["name"]: f["coverage"] for f in info["files"]}["sheet.txt"] == pytest.approx(0.3)
    assert rescore(conn, tmp_path) == 0  # scored once


def test_banma_kept_before_its_lyrics_is_scored_in_pinyin(conn, tmp_path):
    # LRCLIB's 斑马斑马 has plain lyrics only, in Traditional characters; UG's sheet is Simplified.
    song = banma(conn)
    update_song(conn, song.id, lyrics_status="pending", lyrics_json=None)
    ug = FakeUG()
    serve_banma(ug, [banma_tab(2001234, rating=4.7, votes=50)])
    process_song(context(conn, ug.client(tmp_path / "cache"), tmp_path, PASTED), get_song(conn, song.id))
    assert coverages(conn, song) == {2001234: None, 2001235: None}

    update_song(conn, song.id, lyrics_status="found", lyrics_json=lyrics_json(BANMA_TRADITIONAL))
    assert rescore(conn, tmp_path) == 1

    assert coverages(conn, song) == {2001234: 1.0, 2001235: None}  # only the kept sheet is scored


def test_a_partial_sheet_kept_before_its_lyrics_sends_its_song_back_to_be_ranked(conn, tmp_path):
    # LRCLIB failed the night the song was fetched, so its sheets were ranked on rating alone:
    # 101, the best rated, charts only the first verse; 102 and 103 are complete, and cached.
    song = accepted(conn, plain=None)
    index(conn, *[(t, "soda-stereo", "persiana-americana", "chords") for t in (101, 102, 103)])
    ug = FakeUG()
    three_chords(ug)
    process_song(context(conn, ug.client(tmp_path / "cache"), tmp_path), song)
    assert "sheet 101" in read(tmp_path, song, "sheet.txt") and get_song(conn, song.id).ug_dirty is False

    update_song(conn, song.id, lyrics_status="found", lyrics_json=lyrics_json(LYRICS))
    assert rescore(conn, tmp_path) == 1
    assert [s.id for s in songs_to_fetch(conn, Overrides(), NOW + timedelta(days=1))] == [song.id]

    ug.requests.clear()
    process_song(context(conn, ug.client(tmp_path / "cache"), tmp_path), get_song(conn, song.id))

    assert ug.requests == []  # ranked again from the cache
    assert "sheet 102" in read(tmp_path, song, "sheet.txt") and pick_ids(conn, song, "chords") == [102]
    assert coverages(conn, song) == {101: pytest.approx(0.3), 102: 1.0, 103: 1.0}
    assert songs_to_fetch(conn, Overrides(), NOW + timedelta(days=1)) == []


@pytest.mark.parametrize("contents", [
    {101: LINES, 102: LINES[:3]},  # the kept sheet proves complete: no other sheet can beat it
    {101: LINES[:3]},  # partial, but no other sheet to rank it against
])
def test_a_rescored_sheet_leaves_its_song_alone_when_ranking_again_cant_help(conn, tmp_path, contents):
    song = accepted(conn, plain=None)
    index(conn, *[(t, "soda-stereo", "persiana-americana", "chords") for t in contents])
    ug = FakeUG()
    tabs = {t: v(t, version=n, rating=4.9 - n / 10, votes=50) for n, t in enumerate(contents, start=1)}
    for t, lines in contents.items():
        ug.tab(tabs[t], [o for o in tabs.values() if o is not tabs[t]], content=sheet(f"sheet {t}", lines))
    process_song(context(conn, ug.client(tmp_path / "cache"), tmp_path), song)
    assert "sheet 101" in read(tmp_path, song, "sheet.txt")

    update_song(conn, song.id, lyrics_status="found", lyrics_json=lyrics_json(LYRICS))
    assert rescore(conn, tmp_path) == 1

    assert get_song(conn, song.id).ug_dirty is False
    assert songs_to_fetch(conn, Overrides(), NOW + timedelta(days=1)) == []


@pytest.mark.parametrize("status,plain", [("pending", None), ("instrumental", "")])
def test_rescore_leaves_sheets_whose_song_has_no_lyrics(conn, tmp_path, status, plain):
    song = accepted(conn, plain=None)
    update_song(conn, song.id, lyrics_status=status, lyrics_json=None if plain is None else lyrics_json(plain))
    vid = keep_sheet(conn, tmp_path, song, sheet("lacuerda sheet", LINES))
    assert rescore(conn, tmp_path) == 0
    assert get_version(conn, vid).coverage is None


def test_rescore_leaves_sheets_already_scored(conn, tmp_path):
    song = accepted(conn)
    vid = keep_sheet(conn, tmp_path, song, sheet("lacuerda sheet", LINES), coverage=0.4)
    assert rescore(conn, tmp_path) == 0
    assert get_version(conn, vid).coverage == 0.4


def test_rescore_reads_the_markup_any_site_kept_in_sheet_json(conn, tmp_path):
    song = accepted(conn)
    vid = keep_sheet(conn, tmp_path, song, sheet("lacuerda sheet", LINES[:5]))
    assert rescore(conn, tmp_path) == 1
    assert get_version(conn, vid).coverage == 0.5


@pytest.mark.parametrize("line_match,expected", [(85, 1.0), (100, 0.9)])
def test_rescore_follows_the_rank_policy(conn, tmp_path, line_match, expected):
    # Demanding exact lines, a typo in the sheet ("waitin") no longer covers its lyric line.
    song = accepted(conn)
    content = sheet("lacuerda sheet", [*LINES[:9], "where the paper boats are waitin still"])
    vid = keep_sheet(conn, tmp_path, song, content)
    assert rescore(conn, tmp_path, line_match=line_match) == 1
    assert get_version(conn, vid).coverage == pytest.approx(expected)


@pytest.mark.parametrize("damage", ["corrupt", "nested too deep", "missing", "no content"])
def test_rescore_skips_a_sheet_json_it_cannot_read(conn, tmp_path, damage):
    song = accepted(conn)
    vid = keep_sheet(conn, tmp_path, song, sheet("lacuerda sheet", LINES))
    doc = song_dir(tmp_path / "lib", song) / "sheet.json"
    if damage == "corrupt":
        doc.write_text("{not json", encoding="utf-8")
    elif damage == "nested too deep":  # any synced device can write one: RecursionError, not ValueError
        doc.write_text("[" * 100_000 + "]" * 100_000, encoding="utf-8")
    elif damage == "missing":
        doc.unlink()
    else:
        doc.write_text(json.dumps({"provider": "lacuerda"}), encoding="utf-8")
    assert rescore(conn, tmp_path) == 0
    assert get_version(conn, vid).coverage is None


@pytest.mark.parametrize("planted", ["link", "fifo"])
def test_rescore_reads_nothing_through_a_sheet_json_planted_in_the_library(conn, tmp_path, planted):
    # Every synced device can write to the library: a sheet.json swapped for a link to a private file
    # (the database, a credential) must not be read, nor a FIFO left to hang the run. Either is
    # no sheet, as a missing one is.
    song = accepted(conn)
    vid = keep_sheet(conn, tmp_path, song, sheet("lacuerda sheet", LINES))
    doc = song_dir(tmp_path / "lib", song) / "sheet.json"
    private = tmp_path / "private.json"
    private.write_text(doc.read_text(encoding="utf-8"), encoding="utf-8")  # it would score as the sheet
    doc.unlink()
    if planted == "link":
        doc.symlink_to(private)
    else:
        os.mkfifo(doc)

    assert rescore(conn, tmp_path) == 0
    assert get_version(conn, vid).coverage is None


def test_rescore_never_scores_one_versions_text_for_another(conn, tmp_path):
    # sheet.json belongs to another version than sheet.txt (a keep cut short): no grounds to score.
    song = accepted(conn)
    vid = keep_sheet(conn, tmp_path, song, sheet("lacuerda sheet", LINES))
    other = upsert_version(conn, provider="ug", tab_id="101", song_id=song.id, slot="sheet", kind="chords",
                           rating=4.5, votes=20, version=1, label=None, url=slugged(101), raw={},
                           now="2026-10-01T00:00:00Z")
    keep_file(conn, tmp_path / "lib", song=song, version_id=other, name="sheet.json",
              data=json.dumps({"content": sheet("sheet 101", LINES)}).encode(), rank=1)
    assert rescore(conn, tmp_path) == 0
    assert get_version(conn, vid).coverage is None


@pytest.mark.parametrize("lines,retired", [(LINES, True), (LINES[:3], False)])
def test_a_sheet_rescored_complete_retires_the_auto_sheet(conn, tmp_path, lines, retired):
    song = accepted(conn)
    keep_other_sheet(conn, tmp_path, song, provider="auto", kind="auto", name="sheet (auto).txt")
    keep_sheet(conn, tmp_path, song, sheet("lacuerda sheet", lines))

    assert rescore(conn, tmp_path) == 1

    assert ("sheet (auto).txt" in names(conn, song)) is not retired
    assert (song_dir(tmp_path / "lib", song) / "sheet (auto).txt").exists() is not retired
    assert ("auto" in sheet_kinds_picked(conn, song)) is not retired
    info = json.loads(read(tmp_path, song, "info.json"))
    assert ("sheet (auto).txt" in {f["name"] for f in info["files"]}) is not retired


# --- throughput: sheets first, one ratings page per guitar group --------------------------------


def test_sheets_for_every_song_before_any_guitar_part(conn, tmp_path):
    # Live, 8-12 requests per song bought six songs a night. A singer needs the sheet most, so
    # every waiting song's sheet is settled before the budget goes to guitar parts.
    ug = FakeUG()
    persiana = accepted(conn, added_at="2026-10-10T00:00:00Z")
    index(conn, (101, "soda-stereo", "persiana-americana", "chords"),
          (401, "soda-stereo", "persiana-americana", "tabs"))
    ug.tab(v(101, rating=4.8, votes=40), content=sheet("sheet 101", LINES))
    ug.tab(v(401, "tabs"), content=riff("tab 401"))
    older = signos(conn, ug)

    stats = fetch_songs(context(conn, ug.client(tmp_path / "cache", budget=2), tmp_path), [persiana, older])

    assert ug.requests == [slugged(101), slugged(901, song="signos")]
    assert "sheet 101" in read(tmp_path, persiana, "sheet.txt")
    assert "sheet 901" in read(tmp_path, older, "sheet.txt")
    # Signos has no guitar parts to rate, so it finishes from the cache; Persiana's tab waits.
    assert (stats.sheets_done, stats.songs_done, stats.budget_exhausted) == (2, 1, True)
    assert get_song(conn, persiana.id).ug_dirty and not get_song(conn, older.id).ug_dirty


def test_guitar_groups_read_one_ratings_page_starting_with_the_full_song(conn, tmp_path):
    song = accepted(conn)
    index(conn, (101, "soda-stereo", "persiana-americana", "chords"),
          (401, "soda-stereo", "persiana-americana-intro", "tabs"),
          (403, "soda-stereo", "persiana-americana", "tabs"),
          (404, "soda-stereo", "persiana-americana", "tabs"))
    ug = FakeUG()
    ug.tab(v(101), content=sheet("sheet 101", LINES))
    intro = v(401, "tabs", part="intro", tab_url=slugged(401, "tabs", song="persiana-americana-intro"))
    full = v(403, "tabs", rating=4.8, votes=60)
    other = v(404, "tabs", version=2, rating=4.1, votes=5)
    ug.tab(intro, content=riff("tab 401"))
    ug.tab(full, [other], content=riff("tab 403"))
    ug.tab(other, [full], content=riff("tab 404"))

    process_song(context(conn, ug.client(tmp_path / "cache"), tmp_path), song)

    assert [u for u in ug.requests if "-tabs-" in u] == [slugged(403, "tabs")]
    assert "tab 403" in read(tmp_path, song, "tab.txt")


# --- pages robots.txt closes -------------------------------------------------------------------------

# robots.txt on the tabs host closes /tab/track/ and every path that starts with /tab/download, so the
# pages UG files under the band Track's slug (or Download Kids Worship's) may never be read. The live
# index held four such tabs.
TRACK_ARTIST = "https://www.ultimate-guitar.com/artist/track_4242"
CLOSED = f"{TAB}track/se-que-es-tarde-chords-1126580"
OPEN = f"{TAB}the-track/se-que-es-tarde-chords-2000001"  # The Track's: the index files it as track/ too


def index_at(conn, *rows):
    """Insert ug_index rows ``(tab_id, artist_key, song_key, type, url)``: a page the keys don't spell."""
    conn.executemany(
        "INSERT INTO ug_index (tab_id, artist_key, song_key, type, sitemap, first_seen, path) "
        "VALUES (?, ?, ?, ?, 'last', '2026-10-01T00:00:00Z', ?)",
        [(t, a, s, k, url.removeprefix(TAB)) for t, a, s, k, url in rows],
    )


def track_tab(url, kind="chords", song="Se Que Es Tarde", **kw):
    """A tab by Track as UG lists it, at the slugged ``url`` its id ends."""
    tab_id = int(url.rsplit("-", 1)[1])
    return version_dict(tab_id, type=UG_TYPES[kind], song=song, artist="Track", tab_url=url, **kw)


def se_que_es_tarde(conn):
    """Track - Se Que Es Tarde, accepted under the UG keys track/se-que-es-tarde."""
    return accepted(conn, "Track", "Se Que Es Tarde", "track", "se-que-es-tarde")


def test_a_candidate_robots_txt_closes_gives_way_to_the_songs_other_versions(conn, tmp_path):
    # The review's repro: the song failed every night ("robots.txt disallows it (/tab/track/)") and
    # stayed dirty, without ever trying the version it could read.
    song = se_que_es_tarde(conn)
    index_at(conn, (1126580, "track", "se-que-es-tarde", "chords", CLOSED),
             (2000001, "track", "se-que-es-tarde", "chords", OPEN))
    ug = FakeUG()
    ug.tab(track_tab(OPEN), content=sheet("sheet 2000001", LINES))
    client = Recording(ug.client(tmp_path / "cache"))

    stats = fetch_songs(context(conn, client, tmp_path), [song])

    assert (stats.songs_done, stats.songs_failed) == (1, 0)
    assert ug.requests == [OPEN] and CLOSED not in {url for url, _ in client.calls}  # not even asked of the client
    assert "sheet 2000001" in read(tmp_path, song, "sheet.txt")
    done = get_song(conn, song.id)
    assert (done.status, done.ug_dirty, done.ug_checked_at) == ("found", False, "2026-10-18T03:30:00Z")


def test_a_version_ug_links_where_robots_txt_closes_is_no_candidate(conn, tmp_path):
    # The page caracole reads lists the best-rated version at its closed address.
    song = se_que_es_tarde(conn)
    index_at(conn, (2000001, "track", "se-que-es-tarde", "chords", OPEN))
    ug = FakeUG()
    ug.tab(track_tab(OPEN, rating=4.0, votes=5), [track_tab(CLOSED, version=2, rating=4.9, votes=300)],
           content=sheet("sheet 2000001", LINES))

    stats = fetch_songs(context(conn, ug.client(tmp_path / "cache"), tmp_path), [song])

    assert (stats.songs_done, stats.songs_failed) == (1, 0) and ug.requests == [OPEN]
    assert [r.tab_id for r in song_versions(conn, song.id, include_gone=True)] == ["2000001"]
    assert "sheet 2000001" in read(tmp_path, song, "sheet.txt")


def test_a_pin_pasted_where_robots_txt_closes_pins_nothing(conn, tmp_path):
    # UG serves a slugged tab only at its slugged URL, so the pinned page can't be read anywhere: neither
    # there nor at the bare /tab/1126580, a 404 for a slugged tab. The song's other versions compete.
    song = se_que_es_tarde(conn)
    index_at(conn, (2000001, "track", "se-que-es-tarde", "chords", OPEN))
    ug = FakeUG()
    ug.tab(track_tab(OPEN), content=sheet("sheet 2000001", LINES))
    overrides = pins_from_toml(tmp_path, "Track - Se Que Es Tarde", CLOSED)

    stats = fetch_songs(context(conn, ug.client(tmp_path / "cache"), tmp_path, overrides), [song])

    assert (stats.songs_done, stats.songs_failed) == (1, 0) and ug.requests == [OPEN]
    assert "sheet 2000001" in read(tmp_path, song, "sheet.txt")


def test_a_pin_whose_indexed_page_robots_txt_closes_pins_nothing(conn, tmp_path):
    song = se_que_es_tarde(conn)
    index_at(conn, (1126580, "track", "se-que-es-tarde", "chords", CLOSED),
             (2000001, "track", "se-que-es-tarde", "chords", OPEN))
    ug = FakeUG()
    ug.tab(track_tab(OPEN), content=sheet("sheet 2000001", LINES))
    overrides = Overrides(pin={song.key: (1126580,)})

    stats = fetch_songs(context(conn, ug.client(tmp_path / "cache"), tmp_path, overrides), [song])

    assert (stats.songs_done, stats.songs_failed) == (1, 0) and ug.requests == [OPEN]
    assert "sheet 2000001" in read(tmp_path, song, "sheet.txt")


def test_a_song_whose_every_candidate_robots_txt_closes_is_done_without_a_request(conn, tmp_path):
    # The live index lists Track's "Ave Fénix" only under /tab/track/: two Guitar Pro files and no
    # chords, so its own tabs can't name the artist page either.
    song = accepted(conn, "Track", "Ave Fénix", "track", "ave-fenix")
    index_at(conn, (1149792, "track", "ave-fenix", "guitar-pro", f"{TAB}track/ave-fenix-guitar-pro-1149792"),
             (1765760, "track", "ave-fenix", "guitar-pro", f"{TAB}track/ave-fenix-guitar-pro-1765760"))
    ug = FakeUG()

    stats = fetch_songs(context(conn, ug.client(tmp_path / "cache"), tmp_path), [song])

    assert (stats.songs_done, stats.songs_failed) == (1, 0) and ug.requests == []
    done = get_song(conn, song.id)  # checked and clean, so not fetched again every night
    assert (done.status, done.ug_dirty, done.ug_checked_at) == ("wanted", False, "2026-10-18T03:30:00Z")
    assert songs_to_fetch(conn, Overrides(), NOW + timedelta(days=1)) == []


def test_an_artist_page_is_learned_past_a_tab_robots_txt_closes(conn, tmp_path):
    # A not-found song by Track: the oldest of the artist's indexed tabs is closed; the next names the page.
    index_at(conn, (1126580, "track", "se-que-es-tarde", "chords", CLOSED),
             (2000001, "track", "se-que-es-tarde", "chords", OPEN))
    song = matched(conn, "Track", "Ave Fénix", "not_found", added_at="2026-10-17T00:00:00Z")
    ug = FakeUG()
    ug.tab(track_tab(OPEN), content=sheet("sheet 2000001", LINES), artist_url=TRACK_ARTIST)
    bare = version_dict(3000001, song="Ave Fénix", artist="Track", rating=4.5, votes=9)
    ug.add(artist_list(TRACK_ARTIST), artist_page(4242, "Track", [bare]))
    ug.tab(bare, content=sheet("sheet 3000001", LINES), artist_url=TRACK_ARTIST)

    stats = fetch_songs(context(conn, ug.client(tmp_path / "cache"), tmp_path), [song])

    assert (stats.songs_done, stats.songs_failed) == (1, 0)
    assert ug.requests == [OPEN, artist_list(TRACK_ARTIST), f"{TAB}3000001"]
    assert get_song(conn, song.id).match_step == "artist_page"
    assert "sheet 3000001" in read(tmp_path, song, "sheet.txt")


def test_an_artist_page_that_links_every_tab_where_robots_txt_closes_lists_nothing_to_use(conn, tmp_path):
    # No change of shape (an error): the links are the tabs' own pages, which caracole may not read.
    song = matched(conn, "Track", "Se Que Es Tarde", "not_found", added_at="2026-10-17T00:00:00Z")
    ug = FakeUG()
    ug.add(artist_list(TRACK_ARTIST), artist_page(4242, "Track", [track_tab(CLOSED, rating=4.9, votes=80)]))
    overrides = Overrides(artist_url={"track": TRACK_ARTIST})

    stats = fetch_songs(context(conn, ug.client(tmp_path / "cache"), tmp_path, overrides), [song])

    assert (stats.songs_done, stats.songs_failed) == (1, 0) and ug.requests == [artist_list(TRACK_ARTIST)]
    assert get_song(conn, song.id).match_decision == "not_found"
    assert kv_get(conn, f"ug:artist_page_checked:{song.id}") == "2026-10-18T03:30:00Z"  # again in thirty days


def test_a_song_whose_indexed_chords_robots_txt_closes_finds_its_sheet_on_its_artist_page(conn, tmp_path):
    # Closed chords are no chords: the artist's chords list may hold a bare-id version caracole can read.
    song = se_que_es_tarde(conn)
    index_at(conn, (1126580, "track", "se-que-es-tarde", "chords", CLOSED))
    remember_artist_url(conn, "track", TRACK_ARTIST)
    ug = FakeUG()
    bare = version_dict(3000002, song="Se Que Es Tarde", artist="Track", rating=4.5, votes=9)
    ug.add(artist_list(TRACK_ARTIST), artist_page(4242, "Track", [track_tab(CLOSED, rating=4.9, votes=80), bare]))
    ug.tab(bare, content=sheet("sheet 3000002", LINES), artist_url=TRACK_ARTIST)

    out = process_song(context(conn, ug.client(tmp_path / "cache"), tmp_path), song)

    assert out.sheet == 3000002 and "sheet 3000002" in read(tmp_path, song, "sheet.txt")
    assert ug.requests == [artist_list(TRACK_ARTIST), f"{TAB}3000002"]


def test_versions_recorded_where_robots_txt_closes_never_compete(conn, tmp_path):
    # Recorded before caracole checked robots.txt (an artist page listed them): no slot asks for or picks one.
    song = accepted(conn)
    index(conn, (101, "soda-stereo", "persiana-americana", "chords"),
          (401, "soda-stereo", "persiana-americana", "tabs"))
    for tab_id, kind, slot in ((1126580, "chords", "sheet"), (1149792, "tabs", "guitar")):
        upsert_version(conn, provider="ug", tab_id=str(tab_id), song_id=song.id, slot=slot, kind=kind, rating=5.0,
                       votes=900, version=9, label=None, url=f"{TAB}track/persiana-americana-{kind}-{tab_id}",
                       raw={}, now="2026-10-01T00:00:00Z")
    ug = FakeUG()
    ug.tab(v(101), content=sheet("sheet 101", LINES))
    ug.tab(v(401, "tabs"), content=riff("tab 401"))

    stats = fetch_songs(context(conn, ug.client(tmp_path / "cache"), tmp_path), [song])

    assert (stats.songs_done, stats.songs_failed) == (1, 0)
    assert pick_ids(conn, song, "chords") == [101] and pick_ids(conn, song, "tabs") == [401]
    assert ug.requests == [slugged(101), slugged(401, "tabs")]


def test_an_artist_page_robots_txt_closes_is_never_asked_for(conn, tmp_path, monkeypatch):
    # robots.txt leaves artist pages open today. Should it close them, a song is looked up there without a
    # request, and checked with nothing found: never failed.
    www = "www.ultimate-guitar.com"
    monkeypatch.setitem(caracole.http._ROBOTS, www, [*caracole.http._ROBOTS[www], ("/artist/", re.compile("/artist/"))])
    song = banma(conn)
    ug = FakeUG()
    serve_banma(ug, [banma_tab(2001234, rating=4.7, votes=50)])

    stats = fetch_songs(context(conn, ug.client(tmp_path / "cache"), tmp_path, PASTED), [song])

    assert (stats.songs_done, stats.songs_failed) == (1, 0) and ug.requests == []
    assert get_song(conn, song.id).match_decision == "not_found"
    assert kv_get(conn, f"ug:artist_page_checked:{song.id}") == "2026-10-18T03:30:00Z"


OPEN_TOO = f"{TAB}the-track/se-que-es-tarde-chords-2000002"


def test_a_listed_version_whose_page_redirects_where_robots_txt_closes_is_no_candidate(conn, tmp_path):
    # Not seen live (UG answers 404 for a slugged tab's bare URL). Should UG move a page under a closed
    # path, the song goes on with its other versions, as for a closed link, instead of failing every night.
    song = se_que_es_tarde(conn)
    index_at(conn, (2000002, "track", "se-que-es-tarde", "chords", OPEN_TOO))
    ug = FakeUG()
    ug.tab(track_tab(OPEN_TOO, rating=4.0, votes=5), [track_tab(OPEN, version=2, rating=4.9, votes=300)],
           content=sheet("sheet 2000002", LINES))
    ug.redirect(OPEN, CLOSED)

    stats = fetch_songs(context(conn, ug.client(tmp_path / "cache"), tmp_path), [song])

    assert (stats.songs_done, stats.songs_failed) == (1, 0) and CLOSED not in ug.requests
    assert "sheet 2000002" in read(tmp_path, song, "sheet.txt")
    done = get_song(conn, song.id)
    assert (done.status, done.ug_dirty, done.ug_checked_at) == ("found", False, "2026-10-18T03:30:00Z")


def test_an_indexed_tab_whose_page_redirects_where_robots_txt_closes_is_no_candidate(conn, tmp_path):
    song = se_que_es_tarde(conn)
    index_at(conn, (2000001, "track", "se-que-es-tarde", "chords", OPEN),
             (2000002, "track", "se-que-es-tarde", "chords", OPEN_TOO))
    ug = FakeUG()
    ug.redirect(OPEN, CLOSED)
    ug.tab(track_tab(OPEN_TOO), content=sheet("sheet 2000002", LINES))

    stats = fetch_songs(context(conn, ug.client(tmp_path / "cache"), tmp_path), [song])

    assert (stats.songs_done, stats.songs_failed) == (1, 0) and CLOSED not in ug.requests
    assert "sheet 2000002" in read(tmp_path, song, "sheet.txt")
    assert [r.tab_id for r in song_versions(conn, song.id, include_gone=True)] == ["2000002"]


# --- strings that aren't URLs -------------------------------------------------------------------
#
# UG's JSON and the sitemaps are data: one link httpx or urllib can't parse costs that version,
# never the night's fetch (which an httpx.InvalidURL or a ValueError would end). Built with chr()
# so no editor or tool turns them into invisible literals.

BROKEN_LINKS = {
    "control-character": f"{TAB}soda-stereo/persiana-americana{chr(0)}-chords-102",
    "over-64-KiB": f"{TAB}soda-stereo/{'x' * 70_000}-chords-102",
    "broken-host": "https://[tabs.ultimate-guitar.com/tab/soda-stereo/persiana-americana-chords-102",
}


@pytest.mark.parametrize("tab_url", BROKEN_LINKS.values(), ids=BROKEN_LINKS.keys())
def test_a_version_ug_links_at_a_string_that_isnt_a_url_is_no_candidate(conn, tmp_path, tab_url):
    song = accepted(conn)
    index(conn, (101, "soda-stereo", "persiana-americana", "chords"))
    ug = FakeUG()
    ug.tab(v(101, rating=3.0, votes=10), [v(102, rating=5.0, votes=500, tab_url=tab_url)],
           content=sheet("sheet 101", LINES))

    stats = fetch_songs(context(conn, ug.client(tmp_path / "cache"), tmp_path), [song])

    assert (stats.songs_done, stats.songs_failed) == (1, 0) and ug.requests == [slugged(101)]
    assert [r.tab_id for r in song_versions(conn, song.id, include_gone=True)] == ["101"]
    assert "sheet 101" in read(tmp_path, song, "sheet.txt")


def test_an_indexed_path_that_isnt_a_url_is_no_candidate(conn, tmp_path):
    # A sitemap <loc> may hold a control character: the index keeps whatever its pattern matches.
    song = accepted(conn)
    index(conn, (101, "soda-stereo", "persiana-americana", "chords"))
    index_at(conn, (102, "soda-stereo", "persiana-americana", "chords",
                    f"{TAB}soda-stereo/persiana{chr(1)}-americana-chords-102"))
    ug = FakeUG()
    ug.tab(v(101), content=sheet("sheet 101", LINES))

    stats = fetch_songs(context(conn, ug.client(tmp_path / "cache"), tmp_path), [song])

    assert (stats.songs_done, stats.songs_failed) == (1, 0) and ug.requests == [slugged(101)]
    assert "sheet 101" in read(tmp_path, song, "sheet.txt")


def test_a_tab_page_whose_artist_link_isnt_a_url_teaches_nothing(conn, tmp_path):
    song = accepted(conn)
    index(conn, (101, "soda-stereo", "persiana-americana", "chords"))
    ug = FakeUG()
    ug.tab(v(101), content=sheet("sheet 101", LINES), artist_url="https://[www.ultimate-guitar.com/artist/x_1")

    stats = fetch_songs(context(conn, ug.client(tmp_path / "cache"), tmp_path), [song])

    assert (stats.songs_done, stats.songs_failed) == (1, 0)
    assert learned_artist_url(conn, "soda-stereo") is None
    assert "sheet 101" in read(tmp_path, song, "sheet.txt")


# --- bulk work that handed caracole's lock to a lookup --------------------------------------------------


class HandingOver(Recording):
    """The nightly run's client: before asking for ``at``, it hands the lock to a lookup, ``lookup()``."""

    def __init__(self, client, at, lookup):
        super().__init__(client)
        self.at, self.lookup, self.handoffs = at, lookup, 0

    def get(self, url, **options):
        if url == self.at and self.lookup is not None:
            self.lookup()
            self.lookup, self.handoffs = None, self.handoffs + 1
        return super().get(url, **options)


def test_a_song_a_lookup_fetched_meanwhile_is_not_fetched_again(conn, tmp_path):
    ug = FakeUG()
    persiana = accepted(conn, added_at="2026-10-10T00:00:00Z")
    index(conn, (101, "soda-stereo", "persiana-americana", "chords"))
    ug.tab(v(101), content=sheet("sheet 101", LINES))
    older = signos(conn, ug)

    def lookup():  # `caracole get "Soda Stereo - Signos"`, while the run paused before Persiana's page
        update_song(conn, older.id, ug_dirty=False, ug_checked_at="2026-10-18T03:31:00Z")

    client = HandingOver(ug.client(tmp_path / "cache"), slugged(101), lookup)
    stats = fetch_songs(context(conn, client, tmp_path), [persiana, older])

    assert slugged(901, song="signos") not in ug.requests
    assert stats.songs_done == 1 and "sheet 101" in read(tmp_path, persiana, "sheet.txt")


def test_a_song_gone_while_the_run_let_a_lookup_go_first_is_passed_over_in_the_guitar_pass(conn, tmp_path):
    # In the pause before Persiana's guitar tab, a lookup that the run let go first merged Signos into another song:
    # Signos' guitar turn passes it over, as its sheet turn would, and the fetch goes on.
    ug = FakeUG()
    persiana = accepted(conn, added_at="2026-10-10T00:00:00Z")
    index(conn, (101, "soda-stereo", "persiana-americana", "chords"),
          (401, "soda-stereo", "persiana-americana", "tabs"))
    ug.tab(v(101), content=sheet("sheet 101", LINES))
    ug.tab(v(401, "tabs"), content=riff("tab 401"))
    older = signos(conn, ug)
    client = HandingOver(ug.client(tmp_path / "cache"), slugged(401, "tabs"),
                         lambda: conn.execute("DELETE FROM songs WHERE id = ?", (older.id,)))

    stats = fetch_songs(context(conn, client, tmp_path), [persiana, older])

    assert slugged(401, "tabs") in ug.requests and (stats.songs_done, stats.songs_failed) == (1, 0)
    assert "tab 401" in read(tmp_path, persiana, "tab.txt")


def test_after_a_handoff_the_fetch_reads_overrides_toml_again(conn, tmp_path):
    # The lookup's pick, recorded as a [pin] while the run waited, is the song's sheet.
    ug = FakeUG()
    persiana = accepted(conn, added_at="2026-10-10T00:00:00Z")
    index(conn, (101, "soda-stereo", "persiana-americana", "chords"))
    ug.tab(v(101), content=sheet("sheet 101", LINES))
    older = signos(conn, ug)
    index(conn, (902, "soda-stereo", "signos", "chords"))
    ug.tab(version_dict(902, song="Signos", artist="Soda Stereo", tab_url=slugged(902, song="signos"), rating=1.0,
                        votes=1), content=sheet("sheet 902", LINES))
    pinned = Overrides(pin={older.key: (902,)})
    client = HandingOver(ug.client(tmp_path / "cache"), slugged(101), lambda: None)

    fetch_songs(context(conn, client, tmp_path, reload_overrides=lambda: pinned), [persiana, older])

    assert "sheet 902" in read(tmp_path, older, "sheet.txt")


def test_a_song_a_lookup_fetched_in_the_middle_of_its_fetch_is_fetched_again_next_run(conn, tmp_path):
    # The run had read Persiana's state before the lookup changed it: what it kept may not be the
    # lookup's pick, so the next run ranks the song again, from the cache.
    from caracole.ug.fetch import note_looked_up

    ug = FakeUG()
    song = accepted(conn)
    index(conn, (101, "soda-stereo", "persiana-americana", "chords"),
          (401, "soda-stereo", "persiana-americana", "tabs"))
    ug.tab(v(101), content=sheet("sheet 101", LINES))
    ug.tab(v(401, "tabs"), content=riff("tab 401"))
    client = HandingOver(ug.client(tmp_path / "cache"), slugged(401, "tabs"),
                         lambda: note_looked_up(conn, song.id))

    fetch_songs(context(conn, client, tmp_path), [song])

    assert get_song(conn, song.id).ug_dirty is True
