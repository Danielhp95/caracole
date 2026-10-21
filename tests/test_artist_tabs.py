"""ug/artist_tabs.py: the tabs UG's artist pages list, kept as caracole reads them, and found by a search.

UG's sitemaps list every tab of 宋冬野 by a bare id, so the offline index has no name for them; the
artist page caracole reads for a song of theirs names every one (helpers.ug_pages, as read live on
2026-10-19). Ultimate Guitar is a fake behind ``httpx.MockTransport``: nothing reaches the network.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import httpx
import pytest
from conftest import add_song
from helpers.ug_pages import (
    BANMA_TRADITIONAL_LINES,
    BANMA_UG,
    DONG_XIAOJIE_LINES,
    SONG_DONGYE_URL,
    make_artist_page_html,
    make_tab_page_html,
    song_dongye_chords,
    song_dongye_page_html,
    song_dongye_sheet,
    song_dongye_tab,
    version_dict,
)
from typer.testing import CliRunner

from caracole import db
from caracole.cli import build_app
from caracole.config import ProviderPolicy, RankPolicy
from caracole.http import PoliteClient
from caracole.lyrics import Lyrics
from caracole.overrides import Overrides
from caracole.search import bare_id_hint, find_index
from caracole.songs import get_song, update_song
from caracole.ug import artist_tabs
from caracole.ug.artist import artist_page_url
from caracole.ug.fetch import FetchContext, process_song

NOW = datetime(2026, 10, 19, 3, 30, tzinfo=UTC)
TAB = "https://tabs.ultimate-guitar.com/tab/"
CHORDS = artist_page_url(SONG_DONGYE_URL, kind="chords")
TABS = artist_page_url(SONG_DONGYE_URL, kind="tabs")
PASTED = Overrides(artist_url={"宋冬野": SONG_DONGYE_URL})
NOT_FOUND = "<!DOCTYPE html><html><head><title>Oops! We couldn't find that page.</title></head></html>"
RATED = {"t4180894": (4.8, 120), "t4689017": (4.6, 40), "t3016223": (4.7, 90), "t3204647": (4.1, 9)}
ALL_IDS = [3016223, 3204647, 3392735, 4041916, 4180894, 4689017, 5000001, 6613886]


class FakeUG:
    """Ultimate Guitar as it answered for 宋冬野: its chords and tabs lists, and the sheets of 斑马斑马."""

    def __init__(self, chords=None):
        self.requests: list[str] = []
        self.pages: dict[str, tuple[int, str]] = {}
        self.list(chords if chords is not None else song_dongye_chords(**RATED))
        self.pages[TABS] = (200, song_dongye_page_html([song_dongye_tab(5000001, "安和桥 Anhe Bridge", type="Tabs")]))
        for tab_id, other, version in ((4180894, 4689017, 1), (4689017, 4180894, 2)):
            tab = song_dongye_tab(tab_id, BANMA_UG, version=version)
            self.pages[f"{TAB}{tab_id}"] = (200, make_tab_page_html(
                tab, [song_dongye_tab(other, BANMA_UG, version=3 - version)],
                content=song_dongye_sheet(BANMA_TRADITIONAL_LINES), artist_url=SONG_DONGYE_URL))
        for tab_id, version in ((3016223, 1), (3204647, 2)):
            self.pages[f"{TAB}{tab_id}"] = (200, make_tab_page_html(
                song_dongye_tab(tab_id, "董小姐", version=version), [], content=song_dongye_sheet(DONG_XIAOJIE_LINES),
                artist_url=SONG_DONGYE_URL))

    def list(self, tabs, url=CHORDS):
        self.pages[url] = (200, song_dongye_page_html(tabs))

    def handler(self, request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        self.requests.append(url)
        status, body = self.pages.get(url, (404, NOT_FOUND))
        return httpx.Response(status, text=body)

    def client(self, cache_dir, *, now=NOW):
        return PoliteClient("ug", ProviderPolicy(budget=60, delay=(0.0, 0.0)), cache_dir, user_agent="caracole-test",
                            transport=httpx.MockTransport(self.handler), sleep=lambda s: None, wall_clock=lambda: now)


def refusing(cache_dir):
    """A UG client that may read caracole's HTTP cache and fails any request."""
    def refuse(request):
        raise AssertionError(f"a request was sent: {request.url}")

    return PoliteClient("ug", ProviderPolicy(budget=60, delay=(0.0, 0.0)), cache_dir, user_agent="caracole-test",
                        transport=httpx.MockTransport(refuse), sleep=lambda s: None, wall_clock=lambda: NOW)


def banma(conn):
    """宋冬野 - 斑马斑马, with its lyrics; the offline index can't see the artist."""
    song = add_song(conn, "宋冬野", "斑马斑马", added_at="2026-10-18T00:00:00Z")
    lyrics = Lyrics.from_record({"id": 1, "plainLyrics": "\n".join(BANMA_TRADITIONAL_LINES), "syncedLyrics": None,
                                 "instrumental": False, "duration": 253.0}).to_json()
    update_song(conn, song.id, match_decision="not_found", lyrics_status="found", lyrics_json=lyrics)
    return get_song(conn, song.id)


def fetch(conn, ug, tmp_path, song, *, now=NOW, overrides=PASTED, **kw):
    ctx = FetchContext(conn=conn, client=ug.client(tmp_path / "cache", now=now), overrides=overrides,
                       rank=RankPolicy(), library_dir=tmp_path / "lib", now=now, **kw)
    return process_song(ctx, get_song(conn, song.id))


def listed_ids(conn):
    return [r[0] for r in conn.execute("SELECT DISTINCT tab_id FROM ug_artist_tabs ORDER BY tab_id")]


@pytest.fixture
def read(conn, tmp_path):
    """A fetch of 宋冬野 - 斑马斑马 read 宋冬野's artist page; the index holds another artist's banma song."""
    conn.execute("INSERT INTO ug_index (tab_id, artist_key, song_key, type, sitemap, first_seen, path) VALUES "
                 "(9001, 'anju-panta', 'banma-phulyo-fullai-ful', 'chords', '1', 'x', "
                 "'anju-panta/banma-phulyo-fullai-ful-chords-9001')")
    ug = FakeUG()
    song = banma(conn)
    assert fetch(conn, ug, tmp_path, song).sheet == 4180894
    return ug, song


# --- what a fetch keeps --------------------------------------------------------------------------


def test_a_fetch_keeps_every_tab_the_artist_page_lists_with_its_names_rating_and_page(conn, read):
    assert listed_ids(conn) == ALL_IDS
    row = conn.execute("SELECT page, type, artist, title, rating, votes, url FROM ug_artist_tabs "
                       "WHERE tab_id = 4180894").fetchone()
    assert tuple(row) == (SONG_DONGYE_URL, "chords", "Song Dongye (宋冬野)", BANMA_UG, 4.8, 120, f"{TAB}4180894")
    assert conn.execute("SELECT type FROM ug_artist_tabs WHERE tab_id = 5000001").fetchone()[0] == "tabs"


@pytest.mark.parametrize("query", ["斑马", "banma", "斑马斑马", "斑馬斑馬"])
def test_a_search_finds_banma_on_the_artist_page_caracole_read(conn, read, query):
    found = find_index(conn, query)
    first = found.songs[0]
    assert (first.artist, first.title, first.url) == ("宋冬野", "斑马斑马", f"{TAB}4180894")
    assert dict(first.counts) == {"chords": 2} and first.rating == 4.8 and first.votes == 120
    assert first.page == SONG_DONGYE_URL
    assert first.score >= 90 and found.best == first  # what Enter acts on: the song, by its title
    assert [h.title for h in found.songs].count("斑马斑马") == 1


def test_no_bare_id_hint_for_a_query_the_artist_pages_tabs_answer_well(conn, read):
    found = find_index(conn, "斑马")
    assert bare_id_hint("斑马", [*found.songs, *found.artists]) is None
    # A query nothing answers well still gets it.
    assert bare_id_hint("安和桥北", [*find_index(conn, "安和桥北").songs]) is not None


@pytest.mark.parametrize("query", ["宋冬野", "song dongye", "Song Dongye (宋冬野)"])
def test_the_artist_of_a_page_caracole_read_is_an_artist_hit(conn, read, query):
    found = find_index(conn, query)
    assert found.lead == "artist"
    (artist,) = found.artists
    assert (artist.artist, artist.songs, artist.tabs, artist.page) == ("宋冬野", 6, 8, SONG_DONGYE_URL)
    assert [(h.title, h.url) for h in artist.top][:2] == [("斑马斑马", f"{TAB}4180894"), ("董小姐", f"{TAB}3016223")]


def test_a_title_the_artist_page_lists_is_found_with_its_best_rated_tab(conn, read):
    first = find_index(conn, "董小姐").songs[0]
    assert (first.artist, first.title, first.url, dict(first.counts)) == (
        "宋冬野", "董小姐", f"{TAB}3016223", {"chords": 2})
    assert find_index(conn, "lilian").songs[0].url == f"{TAB}4041916"  # "莉莉安 Lilian": either script


def test_the_artist_is_named_as_your_songs_name_them(conn):
    artist_tabs.store(conn, SONG_DONGYE_URL, "Song Dongye (宋冬野)", [_version(t) for t in song_dongye_chords()],
                      read_at="2026-10-18T00:00:00Z")
    assert find_index(conn, "董小姐").songs[0].artist == "宋冬野"  # the original of UG's two names
    # Your song of theirs is written "Song Dong Ye", so a hit of theirs is too.
    add_song(conn, "Song Dong Ye", "郭源潮")
    assert find_index(conn, "董小姐").songs[0].artist == "Song Dong Ye"


def test_a_list_read_again_without_a_tab_drops_it(conn, read, tmp_path):
    ug, song = read
    ug.list([t for t in song_dongye_chords(**RATED) if t["id"] != 6613886])  # UG took 与我交谈 down
    later = NOW + timedelta(days=31)  # the lists are read again once 30 days have passed

    fetch(conn, ug, tmp_path, song, now=later)

    assert CHORDS in ug.requests[-3:] and 6613886 not in listed_ids(conn)
    assert not [h for h in find_index(conn, "与我交谈").songs if h.page]


def test_a_list_the_page_cap_cuts_short_adds_and_drops_nothing(conn, tmp_path):
    # The chords list has two pages; this run may read one of them: what it read is added, the rest stays.
    artist_tabs.store(conn, SONG_DONGYE_URL, "Song Dongye (宋冬野)",
                      [_version(song_dongye_tab(7777777, "南方姑娘 Southern Girl"))], read_at="2026-10-01T00:00:00Z")
    ug = FakeUG()
    first = [*song_dongye_chords(**RATED)][:3]  # ends with 斑马斑马's two versions
    ug.pages[CHORDS] = (200, make_artist_page_html(634073, "Song Dongye (宋冬野)", first, pages=2,
                                                   path="/artist/634073", stripped="", types=["Chords", "Tabs"]))
    song = banma(conn)

    fetch(conn, ug, tmp_path, song, artist_pages_per_kind=1)

    assert listed_ids(conn) == [4180894, 4689017, 6613886, 7777777]


def test_an_artist_page_ug_answers_404_for_loses_its_tabs(conn, read, tmp_path):
    ug, song = read
    ug.pages.clear()  # every list, and the artist page itself: 404
    update_song(conn, song.id, match_decision="not_found", match_step=None)

    fetch(conn, ug, tmp_path, song, now=NOW + timedelta(days=31))

    assert listed_ids(conn) == []


def test_keys_are_made_again_from_the_names_when_caracoles_keys_change(conn, read):
    conn.execute("UPDATE ug_artist_tabs SET artist_key = 'old', song_key = 'old', artist_forms = '', title_forms = ''")
    db.kv_set(conn, artist_tabs.KEYS_KEY, "0")

    assert artist_tabs.ensure_current_keys(conn) == len(ALL_IDS)

    assert find_index(conn, "斑马").songs[0].url == f"{TAB}4180894"
    row = conn.execute("SELECT artist_key, song_key FROM ug_artist_tabs WHERE tab_id = 4180894").fetchone()
    assert tuple(row) == ("song-dongye-宋冬野", "斑马斑马-banma-banma-zebra-zebra")
    assert artist_tabs.ensure_current_keys(conn) == 0  # once


# --- the sitemap index's rows of the same song --------------------------------------------------------


SODA = "https://www.ultimate-guitar.com/artist/soda_stereo_2946"
ACDC = "https://www.ultimate-guitar.com/artist/ac_dc_1234"


def index_rows(conn, *rows):
    conn.executemany("INSERT INTO ug_index (tab_id, artist_key, song_key, type, sitemap, first_seen, path) "
                     "VALUES (?, ?, ?, ?, '1', 'x', ?)", [(t, a, s, k, f"{a}/{s}-{k}-{t}") for t, a, s, k in rows])


def _version(d):
    from caracole.ug.page import parse_version

    return parse_version(d)


def test_an_artist_pages_tabs_merge_with_the_index_rows_of_the_same_song(conn):
    index_rows(conn, (1081460, "soda-stereo", "persiana-americana", "chords"),
               (1081462, "soda-stereo", "persiana-americana", "tabs"))
    slugged = f"{TAB}soda-stereo/persiana-americana-chords-1081460"
    artist_tabs.store(conn, SODA, "Soda Stereo", [
        _version(version_dict(1081460, song="Persiana Americana", artist="Soda Stereo", rating=4.9, votes=300,
                              tab_url=slugged)),
        _version(version_dict(2001, song="Persiana Americana", artist="Soda Stereo", rating=4.1, votes=8)),
    ], read_at="2026-10-18T00:00:00Z")

    (hit,) = [h for h in find_index(conn, "persiana americana").songs]
    assert (hit.artist_key, hit.song_key, dict(hit.counts)) == ("soda-stereo", "persiana-americana",
                                                                  {"chords": 2, "tabs": 1})
    assert (hit.url, hit.rating, hit.title) == (slugged, 4.9, "Persiana Americana")
    (artist,) = find_index(conn, "soda stereo").artists
    assert (artist.songs, artist.tabs) == (1, 3)


def test_a_page_whose_slugs_differ_from_its_names_merges_through_the_tabs_the_index_lists(conn):
    # UG's slug is acdc, but "AC/DC" makes ac-dc: the page's slugged tab tells which artist and song it is.
    index_rows(conn, (9001, "acdc", "highway-to-hell", "chords"))
    artist_tabs.store(conn, ACDC, "AC/DC", [
        _version(version_dict(9001, song="Highway To Hell", artist="AC/DC",
                              tab_url=f"{TAB}acdc/highway-to-hell-chords-9001")),
        _version(version_dict(9002, song="Highway to Hell", artist="AC/DC", type="Tabs")),
        _version(version_dict(9003, song="Thunderstruck", artist="AC/DC")),
    ], read_at="2026-10-18T00:00:00Z")

    (hit,) = find_index(conn, "highway to hell").songs
    assert (hit.artist_key, hit.song_key, dict(hit.counts)) == ("acdc", "highway-to-hell", {"chords": 1, "tabs": 1})
    assert [(h.artist_key, h.song_key) for h in find_index(conn, "thunderstruck").songs] == [("acdc", "thunderstruck")]


def test_chinese_counts_as_pinyin_only_in_whole_words_of_a_pages_names(conn):
    # 斑马 is "ban ma": never the letters inside Bohemia Suburbana, Band-Maid or El Bananero.
    for page, artist, title in ((SODA, "Bohemia Suburbana", "Suburban Male"), (ACDC, "Band-Maid", "Domination"),
                                (f"{SODA}0", "El Bananero", "Banana Man")):
        artist_tabs.store(conn, page, artist, [_version(version_dict(len(page), song=title, artist=artist))],
                          read_at="2026-10-18T00:00:00Z")
    found = find_index(conn, "斑马")
    assert (found.songs, found.artists) == ((), ())
    assert [h.title for h in find_index(conn, "suburban male").songs] == ["Suburban Male"]


def test_a_merged_song_keeps_the_index_sample_of_a_better_type_than_the_page_lists(conn):
    index_rows(conn, (1081460, "soda-stereo", "persiana-americana", "chords"))
    artist_tabs.store(conn, SODA, "Soda Stereo", [_version(version_dict(
        3001, song="Persiana Americana", artist="Soda Stereo", type="Pro", rating=4.9))], read_at="2026-10-18T00:00:00Z")

    (hit,) = find_index(conn, "persiana americana").songs
    assert hit.url == f"{TAB}soda-stereo/persiana-americana-chords-1081460" and hit.rating is None
    assert dict(hit.counts) == {"chords": 1, "guitar-pro": 1} and hit.page == SODA


def test_official_non_public_and_untracked_types_are_not_kept(conn):
    artist_tabs.store(conn, SODA, "Soda Stereo", [_version(d) for d in (
        version_dict(1, song="Signos", artist="Soda Stereo", type="Official"),
        version_dict(2, song="Signos", artist="Soda Stereo", access="pro"),
        version_dict(3, song="Signos", artist="Soda Stereo", type="Ukulele Chords"),
        version_dict(4, song="Signos", artist="Soda Stereo", tab_url="https://www.ultimate-guitar.com/pro/4"),
        version_dict(5, song="Signos", artist="Soda Stereo", type="Pro"),
    )], read_at="2026-10-18T00:00:00Z")
    assert [tuple(r) for r in conn.execute("SELECT tab_id, type FROM ug_artist_tabs")] == [(5, "guitar-pro")]


def test_an_older_read_never_overwrites_a_newer_one(conn):
    def rated(rating, at):
        artist_tabs.store(conn, SODA, "Soda Stereo",
                          [_version(version_dict(1, song="Signos", artist="Soda Stereo", rating=rating))], read_at=at)

    rated(4.5, "2026-10-18T00:00:00Z")
    rated(3.0, "2026-10-01T00:00:00Z")
    assert conn.execute("SELECT rating FROM ug_artist_tabs").fetchone()[0] == 4.5
    rated(4.7, "2026-10-19T00:00:00Z")
    assert conn.execute("SELECT rating FROM ug_artist_tabs").fetchone()[0] == 4.7


# --- the backfill ------------------------------------------------------------------------------------


@pytest.mark.parametrize("known", ["learned", "artist_url"])
def test_the_backfill_reads_what_the_cache_holds_of_each_known_artist_page_and_sends_nothing(conn, read, tmp_path,
                                                                                             known):
    # As a database from before the table: the cache holds the lists, the table nothing.
    conn.execute("DELETE FROM ug_artist_tabs")
    if known == "artist_url":
        conn.execute("DELETE FROM kv WHERE key LIKE 'ug:artist%'")
        overrides = PASTED
    else:
        overrides = Overrides()
        assert db.kv_get(conn, "ug:artist_url:宋冬野") == SONG_DONGYE_URL  # learned from a tab page
    db.kv_delete(conn, artist_tabs.BACKFILL_KEY)

    assert artist_tabs.backfill(conn, refusing(tmp_path / "cache"), overrides) == len(ALL_IDS)

    assert listed_ids(conn) == ALL_IDS
    assert find_index(conn, "斑马").songs[0].url == f"{TAB}4180894"
    conn.execute("DELETE FROM ug_artist_tabs")
    assert artist_tabs.backfill(conn, refusing(tmp_path / "cache"), overrides) == 0  # once
    assert listed_ids(conn) == []


def test_the_backfill_takes_only_what_the_cache_holds(conn, tmp_path):
    db.kv_set(conn, "ug:artist_url:宋冬野", SONG_DONGYE_URL)
    assert artist_tabs.backfill(conn, refusing(tmp_path / "cache"), Overrides()) == 0
    assert listed_ids(conn) == []


def test_the_nightly_run_backfills_while_ug_cools_down(conn, read, tmp_path, cfg):
    from caracole.health import is_cooling, record_block
    from caracole.notify import Notifier
    from caracole.pipeline import Services, default_steps, run_pipeline
    from caracole.ug.index import mark_built

    conn.execute("DELETE FROM ug_artist_tabs")
    db.kv_delete(conn, artist_tabs.BACKFILL_KEY)
    mark_built(conn, NOW - timedelta(days=1))
    record_block(conn, "ug", NOW, "HTTP 429")
    assert is_cooling(conn, "ug", NOW)
    cfg.cache_dir.mkdir(parents=True, exist_ok=True)
    services = Services(clients={"ug": refusing(tmp_path / "cache")}, spotify=None, notifier=Notifier(None, None))

    report = run_pipeline(cfg, conn=conn, services=services, now=NOW,
                          steps=[s for s in default_steps() if s.name in ("match", "fetch")])

    assert report.ok, report.errors
    assert report.steps["fetch"].startswith("skipped: ug cooling down")
    assert listed_ids(conn) == ALL_IDS


# --- caracole search ---------------------------------------------------------------------------------


def config(tmp_path):
    p = tmp_path / "caracole.toml"
    p.write_text(f'library_dir = "{tmp_path / "lib"}"\nmusic_dir = "{tmp_path / "music"}"\n'
                 f'state_dir = "{tmp_path / "state"}"\ncache_dir = "{tmp_path / "cache"}"\n', encoding="utf-8")
    return p


def search(tmp_path, *args):
    result = CliRunner().invoke(build_app(), ["--config", str(config(tmp_path)), "search", *args])
    assert result.exit_code == 0, result.output
    return result.output, result.output.partition("On Ultimate Guitar (offline index)")[2].partition("On LaCuerda")[0]


def test_caracole_search_prints_the_tab_with_the_line_that_adds_it_under_your_songs_names(conn, read, tmp_path):
    out, ug = search(tmp_path, "董小姐")
    assert "1. [UG] 宋冬野 - 董小姐 · chords×2 · rated 4.7 (90 votes)" in ug
    assert f"{TAB}3016223\n" in ug and 'caracole add "宋冬野" "董小姐"' in ug
    assert "bare id" not in out

    out, ug = search(tmp_path, "斑马")
    assert f"1. [UG] 宋冬野 - 斑马斑马 · chords×2 · rated 4.8 (120 votes)\n     {TAB}4180894\n     in your library" in ug
    assert "bare id" not in out


def test_the_owners_case_a_removed_song_ug_lists_by_bare_ids_is_found_with_the_line_that_brings_it_back(conn, read,
                                                                                                        tmp_path):
    # 宋冬野 - 斑马斑马, removed on 2026-10-20: 斑马 finds it removed, and on UG, at the page UG gives it.
    from caracole.removal import plan_removal, remove_song
    from caracole.config import load_config

    _, song = read
    cfg = load_config(config(tmp_path), env={"HOME": str(tmp_path / "home")})
    remove_song(conn, cfg, plan_removal(conn, cfg, get_song(conn, song.id)))

    for query in ("斑马", "banma", "斑马斑马"):
        out, ug = search(tmp_path, query)
        assert "Removed from your library\n  宋冬野 - 斑马斑马" in out, query
        assert f"1. [UG] 宋冬野 - 斑马斑马 · chords×2 · rated 4.8 (120 votes)\n     {TAB}4180894\n" \
               '     caracole add "宋冬野" "斑马斑马"' in ug, query
        assert "bare id" not in out, query


def test_caracole_search_lists_the_artists_songs_from_their_page(conn, read, tmp_path):
    result = CliRunner().invoke(build_app(), ["--config", str(config(tmp_path)), "search", "--artist", "宋冬野"])

    assert result.exit_code == 0, result.output
    ug = result.output.partition("On Ultimate Guitar (offline index)")[2].partition("On LaCuerda")[0]
    assert "宋冬野: 6 songs (8 tabs)" in ug
    assert 'caracole add "宋冬野" "董小姐"' in ug and "[artist_url]" not in result.output
