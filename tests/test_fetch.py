"""Per-song UG fetch, rank and keep (plan Task 15, amendment A6).

A fake Ultimate Guitar answers through ``httpx.MockTransport``, keyed by URL,
the way the live site does: a slugged tab only at its slugged URL, and UG's
404 page (which has no js-store) for anything else.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

import httpx
import pytest
from helpers.ug_pages import make_tab_page_html, version_dict

from conftest import add_song
from tabarr.config import ProviderPolicy, RankPolicy
from tabarr.http import PoliteClient
from tabarr.library import song_dir
from tabarr.lyrics import Lyrics
from tabarr.overrides import Overrides
from tabarr.songs import get_song, update_song
from tabarr.ug.fetch import FetchContext, FetchStats, fetch_songs, process_song
from tabarr.ug.lookup import IndexTab, artist_tabs, index_tab, tab_url_for
from tabarr.versions import picks, song_versions

NOW = datetime(2026, 10, 18, 3, 30, tzinfo=UTC)
TAB = "https://tabs.ultimate-guitar.com/tab/"
SODA_URL = "https://www.ultimate-guitar.com/artist/soda_stereo_2946"
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
        self.requests: list[str] = []

    def add(self, url, html, status=200):
        self.pages[str(httpx.URL(url))] = (status, html)

    def tab(self, tab, versions=(), *, content=None, meta=None, artist_url=SODA_URL):
        """Serve a tab page at the tab's own ``tab_url``."""
        self.add(tab["tab_url"], make_tab_page_html(tab, list(versions), content=content, meta=meta,
                                                    artist_url=artist_url))

    def handler(self, request):
        url = str(request.url)
        self.requests.append(url)
        status, html = self.pages.get(url, (404, NOT_FOUND))
        return httpx.Response(status, text=html)

    def client(self, cache_dir, budget=60):
        return PoliteClient("ug", ProviderPolicy(budget=budget, delay=(0.0, 0.0)), cache_dir,
                            user_agent="tabarr-test", transport=httpx.MockTransport(self.handler),
                            sleep=lambda s: None)


def lyrics_json(plain):
    record = {"id": 1, "plainLyrics": plain, "syncedLyrics": None, "instrumental": False, "duration": 213.0}
    return Lyrics.from_record(record).to_json()


def accepted(conn, artist="Soda Stereo", title="Persiana Americana", akey="soda-stereo",
             skey="persiana-americana", *, plain=LYRICS, **kw):
    """A song the matcher accepted, with LRCLIB lyrics (``plain=None`` leaves them pending)."""
    song = add_song(conn, artist, title, **kw)
    fields = dict(match_decision="accept", match_step="exact", match_score=100.0, match_artist_key=akey,
                  match_song_key=skey, ug_dirty=True)
    if plain is not None:
        fields.update(lyrics_status="found", lyrics_json=lyrics_json(plain))
    update_song(conn, song.id, **fields)
    return get_song(conn, song.id)


def context(conn, client, tmp_path, overrides=None, **kw):
    return FetchContext(conn=conn, client=client, overrides=overrides or Overrides(), rank=RankPolicy(),
                        library_dir=tmp_path / "lib", now=NOW, **kw)


def read(tmp_path, song, name):
    """A kept file's exact text (UG's \\r\\n line ends included)."""
    return (song_dir(tmp_path / "lib", song) / name).read_bytes().decode("utf-8")


def coverages(conn, song):
    return {int(r.tab_id): r.coverage for r in song_versions(conn, song.id)}


def pick_ids(conn, song, *kinds):
    return [int(r.tab_id) for r in picks(conn, song.id, kinds)]


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
    dml = dict(song="De Música Ligera", artist="Soda Stereo", song_id=67588)
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


# --- the guitar slot ------------------------------------------------------------------


def test_guitar_pro_picks_with_penalty_no_download(conn, tmp_path):
    song = accepted(conn)
    index(conn, (301, "soda-stereo", "persiana-americana", "guitar-pro"),
          (302, "soda-stereo", "persiana-americana", "guitar-pro"),
          (303, "soda-stereo", "persiana-americana", "power"))
    ug = FakeUG()
    # UG lists versions per type and part, so each of these is its own one-page group.
    ug.tab(v(301, "guitar-pro", rating=4.5, votes=20), meta={"fileExtension": ".gp5", "duration": 213})
    ug.tab(v(302, "guitar-pro", part="solo", rating=4.9, votes=30), meta={"fileExtension": ".gp5", "duration": 40})
    ug.tab(v(303, "power", rating=4.3, votes=15), meta={"fileExtension": ".ptb"})

    out = process_song(context(conn, ug.client(tmp_path / "cache"), tmp_path), song)

    # Unpenalized, the solo (4.83) would lead; the 0.5 penalty puts it behind both.
    assert pick_ids(conn, song, "guitar-pro", "power") == [301, 303]
    assert out.guitar_pro == (301, 303)
    assert sorted(ug.requests) == sorted(
        [slugged(301, "guitar-pro"), slugged(302, "guitar-pro"), slugged(303, "power")]
    )
    assert not list((tmp_path / "lib").rglob("guitar-*"))


def riff(tag):
    return f"[tab]e|-----0-----3-----|\r\nB|---1---1-------1-|[/tab]\r\n{tag}"


def test_tab_kept(conn, tmp_path):
    song = accepted(conn)
    index(conn, (401, "soda-stereo", "persiana-americana", "tabs"), (402, "soda-stereo", "persiana-americana", "tabs"))
    ug = FakeUG()
    low, high = v(401, "tabs", rating=4.0, votes=10), v(402, "tabs", version=2, rating=4.8, votes=40)
    ug.tab(low, [high], content=riff("tab 401"))
    ug.tab(high, [low], content=riff("tab 402"))

    out = process_song(context(conn, ug.client(tmp_path / "cache"), tmp_path), song)

    assert out.tab == 402 and pick_ids(conn, song, "tabs") == [402]
    assert read(tmp_path, song, "tab.txt") == "e|-----0-----3-----|\r\nB|---1---1-------1-|\r\ntab 402"
    doc = json.loads(read(tmp_path, song, "tab.json"))
    assert (doc["version"]["id"], doc["url"], doc["content"]) == (402, slugged(402, "tabs"), riff("tab 402"))
    assert ug.requests == [slugged(401, "tabs"), slugged(402, "tabs")]


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

    out = process_song(context(conn, ug.client(tmp_path / "cache"), tmp_path), song)

    assert out.tab == 1081462 and "intro riff" in read(tmp_path, song, "tab.txt")
    assert ug.requests == [f"{TAB}soda-stereo/persiana-americana-tabs-1081462"]


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
