"""Defects found by attacking UG's names in two scripts and its bare artist pages (branch w7-ug-names).

Each test is an input a real user or UG would produce, and fails on the branch: it is marked
``xfail(strict=True)`` with its defect's id, so the suite stays green and a fix shows up as an
XPASS. The attacks that passed are not kept here. Nothing reaches the network: UG is a fake behind
``httpx.MockTransport`` that answers the way the live site does (its 404 page for anything else).
"""

from __future__ import annotations

import wave
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import urlsplit

import httpx
import pytest
from conftest import add_song
from helpers.ug_pages import make_artist_page_html, make_tab_page_html, store_page_html, version_dict
from mutagen.id3 import TIT2, TPE1
from mutagen.wave import WAVE

from caracole.config import ProviderPolicy, RankPolicy
from caracole.http import PoliteClient
from caracole.inbox import file_inbox
from caracole.library import kept_files
from caracole.lyrics import Lyrics
from caracole.music import scan_music
from caracole.normalize import slug_key
from caracole.overrides import Overrides, load_overrides
from caracole.songs import get_song, update_song
from caracole.ug.artist import artist_page_url
from caracole.ug.fetch import FetchContext, fetch_songs, process_song
from caracole.ug.lookup import learned_artist_url
from caracole.versions import set_picks, song_versions, upsert_version

NOW = datetime(2026, 10, 19, 3, 30, tzinfo=UTC)
WWW = "https://www.ultimate-guitar.com"
TAB = "https://tabs.ultimate-guitar.com/tab/"
ARTIST = f"{WWW}/artist/634073"  # 宋冬野's page, as UG addresses it (checked live)
FOUND = f"{TAB}4180894"  # the tab page the user found for 宋冬野 - 斑马斑马
NOT_FOUND = "<!DOCTYPE html><html><head><title>Oops! We couldn't find that page.</title></head></html>"
LINES = ("walking down the river road tonight", "counting every lantern on the shore",
         "the wind is singing softly in the pines", "and nobody remembers what we were")


class FakeUG:
    """Ultimate Guitar through a transport: known pages by URL, UG's 404 page for the rest."""

    def __init__(self):
        self.pages: dict[str, str] = {}
        self.requests: list[str] = []

    def add(self, url, html):
        self.pages[str(httpx.URL(url))] = html

    def tab(self, tab, *, artist_url=ARTIST):
        """Serve a tab page, with a sheet, at the tab's own (bare) ``tab_url``."""
        self.add(tab["tab_url"], make_tab_page_html(tab, [], content=sheet(), artist_url=artist_url))

    def handler(self, request):
        url = str(request.url)
        self.requests.append(url)
        return httpx.Response(200, text=self.pages[url]) if url in self.pages else httpx.Response(404, text=NOT_FOUND)

    def client(self, cache_dir, *, now=NOW):
        return PoliteClient("ug", ProviderPolicy(budget=60, delay=(0.0, 0.0)), cache_dir, user_agent="caracole-test",
                            transport=httpx.MockTransport(self.handler), sleep=lambda s: None, wall_clock=lambda: now)


def sheet():
    return "\n".join(f"[tab][ch]C[/ch] [ch]G[/ch]\n{line}[/tab]" for line in LINES)


def context(conn, client, tmp_path, overrides, *, now=NOW):
    return FetchContext(conn=conn, client=client, overrides=overrides, rank=RankPolicy(),
                        library_dir=tmp_path / "lib", now=now)


def wanted(conn, artist, title, *, decision="not_found"):
    """A song with lyrics that the index didn't find (or that you pinned)."""
    song = add_song(conn, artist, title, added_at="2026-10-18T00:00:00Z")
    record = {"id": 1, "plainLyrics": "\n".join(LINES), "syncedLyrics": None, "instrumental": False}
    update_song(conn, song.id, match_decision=decision, match_step="pin" if decision == "pinned" else None,
                lyrics_status="found", lyrics_json=Lyrics.from_record(record).to_json())
    return get_song(conn, song.id)


def serve_artist(ug, name, listed, *, base=ARTIST, artist_id=634073):
    """The artist's chords list at ``base``: ``listed`` is (tab id, song_name) in UG's order, each tab
    at its bare /tab/<id> with a sheet, as UG lists every tab of an artist with a non-Latin name."""
    tabs = [version_dict(t, song=s, artist=name, artist_id=artist_id, artist_url=base) for t, s in listed]
    ug.add(artist_page_url(base, kind="chords"),
           make_artist_page_html(artist_id, name, tabs, path=urlsplit(base).path, stripped=""))
    for tab in tabs:
        ug.tab(tab, artist_url=base)


def look_up(conn, tmp_path, ug, song, *, base=ARTIST):
    """The artist-page route with the artist's page pasted under [artist_url]: the song as it ends,
    and the tab ids it took as its versions."""
    pasted = Overrides(artist_url={slug_key(song.artist): base})
    process_song(context(conn, ug.client(tmp_path / "cache"), tmp_path, pasted), song)
    return get_song(conn, song.id), {int(r.tab_id) for r in song_versions(conn, song.id, include_gone=True)}


def toml(tmp_path, text):
    path = tmp_path / "overrides.toml"
    path.write_text(text, encoding="utf-8")
    return load_overrides(path)


# --- addresses pasted into overrides.toml (an invalid file stops the nightly run) -------------------


@pytest.mark.parametrize("table", ["artist_url", "pin"])
def test_w7_1_a_tab_page_on_ugs_spanish_host_is_taken(tmp_path, table):
    # Read live on 2026-10-19: /tab/4180894 has store.i18n.links.es = "https://es.ultimate-guitar.com/tab/4180894".
    if table == "artist_url":
        o = toml(tmp_path, '[artist_url]\n"宋冬野" = "https://es.ultimate-guitar.com/tab/4180894"\n')
        assert o.artist_url == {"宋冬野": FOUND}
    else:
        o = toml(tmp_path, '[pin]\n"宋冬野 - 斑马斑马" = ["https://es.ultimate-guitar.com/tab/4180894"]\n')
        assert list(o.pin.values()) == [(4180894,)] and list(o.pin_urls.values()) == [(FOUND,)]


@pytest.mark.parametrize("pasted", [
    "ultimate-guitar.com/artist/634073",
    "www.ultimate-guitar.com/artist/634073",
    "https://ultimate-guitar.com/artist/634073",
])
def test_w7_2_an_artist_page_as_the_address_bar_shows_it_is_taken(tmp_path, pasted):
    assert toml(tmp_path, f'[artist_url]\n"宋冬野" = "{pasted}"\n').artist_url == {"宋冬野": ARTIST}


@pytest.mark.parametrize("pasted,stored", [
    ("https://www.Ultimate-Guitar.com/artist/634073", ARTIST),
    ("https://WWW.ULTIMATE-GUITAR.COM/artist/634073", ARTIST),
    ("https://tabs.Ultimate-Guitar.com/tab/4180894", FOUND),
])
def test_w7_3_an_address_with_capitals_in_its_host_is_taken(tmp_path, pasted, stored):
    assert toml(tmp_path, f'[artist_url]\n"宋冬野" = "{pasted}"\n').artist_url == {"宋冬野": stored}


# --- false positives: a part of a name in two scripts stands in for another song or artist ----------


@pytest.mark.parametrize("title,listed,expected", [
    ("对不起", [(9000001, "对不起"), (9000002, "Baby 对不起")], {9000001}),
    ("Baby 对不起", [(9000001, "对不起"), (9000002, "Baby 对不起")], {9000002}),
    ("Baby 对不起", [(9000001, "对不起")], set()),  # not on UG: another song's sheet is kept as its own
    ("Baby", [(9000001, "我的Baby")], set()),
])
def test_w7_4_a_title_with_latin_in_it_is_not_another_song_of_the_artist(conn, tmp_path, title, listed, expected):
    ug = FakeUG()
    serve_artist(ug, "周杰伦", listed)

    _, ids = look_up(conn, tmp_path, ug, wanted(conn, "周杰伦", title))

    assert ids == expected


@pytest.mark.parametrize("featuring", ["Ma Di (feat. 宋冬野)", "Ma Di feat. 宋冬野"])
def test_w7_5_a_tab_of_an_artist_featuring_him_keeps_his_learned_page(conn, tmp_path, featuring):
    banma = wanted(conn, "宋冬野", "斑马斑马", decision="pinned")
    nanshan = wanted(conn, "马頔", "南山南", decision="pinned")
    ug = FakeUG()
    ug.tab(version_dict(4180894, song="斑马 斑马 Banma Banma Zebra Zebra", artist="Song Dongye (宋冬野)"))
    ug.tab(version_dict(9001, song="南山南", artist=featuring), artist_url=f"{WWW}/artist/99")
    pins = Overrides(pin={banma.key: (4180894,), nanshan.key: (9001,)})

    process_song(context(conn, ug.client(tmp_path / "cache"), tmp_path, pins), banma)
    assert learned_artist_url(conn, "宋冬野") == ARTIST
    process_song(context(conn, ug.client(tmp_path / "cache"), tmp_path, pins), nanshan)

    assert learned_artist_url(conn, "宋冬野") == ARTIST  # still his own page, not the other artist's


def make_wav(path: Path, *, artist, title) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(8000)
        w.writeframes(b"\x00\x00" * 8000)
    f = WAVE(path)
    f.add_tags()
    f.tags.add(TPE1(encoding=3, text=artist))
    f.tags.add(TIT2(encoding=3, text=title))
    f.save()
    return path


def test_w7_6_a_purchase_of_another_song_holding_the_title_is_not_linked(conn, tmp_path):
    s = add_song(conn, "周杰伦", "对不起", duration_ms=None)
    make_wav(tmp_path / "music" / "a.wav", artist="周杰伦", title="Baby 对不起")

    scan_music(conn, tmp_path / "music")

    assert get_song(conn, s.id).audio_path is None


def pick(conn, song, tab_id):
    return upsert_version(conn, provider="ug", tab_id=str(tab_id), song_id=song.id, slot="guitar", kind="guitar-pro",
                          rating=4.5, votes=10, version=1, label=None, url=f"{TAB}{tab_id}", raw={}, now="x")


def drop(cfg, name):
    inbox = cfg.library_dir / "_inbox"
    inbox.mkdir(parents=True, exist_ok=True)
    (inbox / name).write_bytes(b"GP-DATA")


def test_w7_7_a_download_of_a_title_with_latin_in_it_files_into_its_own_song(conn, cfg):
    sorry = add_song(conn, "周杰伦", "对不起")
    baby = add_song(conn, "周杰伦", "Baby 对不起")
    set_picks(conn, sorry.id, ["guitar-pro", "power"], [pick(conn, sorry, 7)])
    set_picks(conn, baby.id, ["guitar-pro", "power"], [pick(conn, baby, 8)])
    drop(cfg, "周杰伦 - Baby 对不起 Baby Dui Bu Qi (ver 1).gp5")

    file_inbox(conn, cfg.library_dir)

    assert kept_files(conn, sorry.id) == [] and [f.name for f in kept_files(conn, baby.id)] == ["guitar-1.gp5"]


# --- a tab page pasted under [artist_url] -------------------------------------------------------------


def test_w7_8_an_unreadable_pasted_tab_page_is_not_asked_for_by_every_song_every_night(conn, tmp_path):
    ug = FakeUG()
    # A 200 whose data has no tab_view (a page shape UG drifted to): it doesn't parse, fetched again or not.
    ug.add(FOUND, store_page_html({"tab": version_dict(4180894, song="斑马斑马", artist="Song Dongye (宋冬野)")}))
    pasted = Overrides(artist_url={"宋冬野": FOUND})
    songs = [wanted(conn, "宋冬野", "斑马斑马"), wanted(conn, "宋冬野", "董小姐")]

    for night in range(3):
        at = NOW + timedelta(days=night)
        stats = fetch_songs(context(conn, ug.client(tmp_path / "cache", now=at), tmp_path, pasted, now=at),
                            [get_song(conn, s.id) for s in songs])
        assert stats.songs_done + stats.songs_failed == 2

    # A tab page that won't parse, fetched again, waits a week (ug.fetch UNREADABLE_RETRY): two requests.
    assert ug.requests.count(FOUND) <= 2


# --- misses: formats of N3 the fix doesn't read --------------------------------------------------------


@pytest.mark.parametrize("artist,title,listed", [
    ("Звери", "Ты", "Ты (Ty)"),
    ("Αντώνης Ρέμος", "Σε", "Σε (Se)"),
    ("עומר אדם", "לב", "לב (Lev)"),
    ("عمرو دياب", "حب", "حب (Hob)"),
    ("Bodyslam", "ใจ", "ใจ (Jai)"),
])
def test_w7_9_a_short_original_title_meets_its_listing_in_two_scripts(conn, tmp_path, artist, title, listed):
    ug = FakeUG()
    serve_artist(ug, artist, [(9000001, "Another Song"), (9000002, listed)])

    song, ids = look_up(conn, tmp_path, ug, wanted(conn, artist, title))

    assert ids == {9000002} and song.match_step == "artist_page"


@pytest.mark.xfail(strict=True, raises=AssertionError,
                   reason="W7-10: after a Korean or Japanese original, an unbracketed romanization "
                          "and translation stay one part, so neither one alone meets")
@pytest.mark.parametrize("artist,title,listed", [
    ("BTS", "Spring Day", "봄날 Bomnal Spring Day"),  # Spotify's title for 봄날
    ("BTS", "Blood Sweat & Tears", "피 땀 눈물 Pi Ttam Nunmul Blood Sweat & Tears"),
    ("YOASOBI", "Yoru ni Kakeru", "夜に駆ける Yoru ni Kakeru Racing Into The Night"),
])
def test_w7_10_a_romanization_or_translation_after_a_korean_or_japanese_original(conn, tmp_path, artist, title,
                                                                                  listed):
    ug = FakeUG()
    serve_artist(ug, artist, [(9000001, "Another Song"), (9000002, listed)])

    song, ids = look_up(conn, tmp_path, ug, wanted(conn, artist, title))

    assert ids == {9000002} and song.match_step == "artist_page"


@pytest.mark.xfail(strict=True, raises=AssertionError,
                   reason="W7-11: a listing in Latin letters only, a romanization with its "
                          "translation bracketed, is never split, so the song is missed")
@pytest.mark.parametrize("artist,title,listed", [
    ("王菲", "红豆", "Hong Dou (Red Bean)"),
    ("Sơn Tùng M-TP", "Nơi này có anh", "Nơi Này Có Anh (Where This Is You)"),
])
def test_w7_11_a_romanization_with_its_translation_bracketed(conn, tmp_path, artist, title, listed):
    ug = FakeUG()
    serve_artist(ug, artist, [(9000001, "Another Song"), (9000002, listed)])

    song, ids = look_up(conn, tmp_path, ug, wanted(conn, artist, title))

    assert ids == {9000002} and song.match_step == "artist_page"


@pytest.mark.parametrize("artist,title,download", [
    ("周杰伦", "晴天", "Jay Chou (周杰倫) - 晴天 Qing Tian Sunny Day (ver 1).gp5"),
    ("米津玄師", "Lemon", "Kenshi Yonezu (米津玄師) - Lemon (ver 1).gp5"),
])
def test_w7_12_a_download_named_after_ugs_artist_in_two_scripts_is_filed(conn, cfg, artist, title, download):
    s = add_song(conn, artist, title)
    set_picks(conn, s.id, ["guitar-pro", "power"], [pick(conn, s, 7)])
    drop(cfg, download)

    file_inbox(conn, cfg.library_dir)

    assert [f.name for f in kept_files(conn, s.id)] == ["guitar-1.gp5"]


@pytest.mark.parametrize("artist,ug_name", [("IU", "IU (아이유)"), ("Би-2", "Би-2 (Bi-2)")])
def test_w7_13_a_short_artist_name_meets_ugs_name_in_two_scripts(conn, tmp_path, artist, ug_name):
    song = wanted(conn, artist, "Some Song", decision="pinned")
    page = f"{WWW}/artist/5550001"
    ug = FakeUG()
    ug.tab(version_dict(5001, song="Some Song", artist=ug_name), artist_url=page)

    process_song(context(conn, ug.client(tmp_path / "cache"), tmp_path, Overrides(pin={song.key: (5001,)})), song)

    assert learned_artist_url(conn, slug_key(artist)) == page


def test_w7_14_digits_between_the_original_and_its_romanization(conn, tmp_path):
    ug = FakeUG()
    serve_artist(ug, "刘德华", [(9000001, "Another Song"), (9000002, "17岁 17 Sui")])

    song, ids = look_up(conn, tmp_path, ug, wanted(conn, "刘德华", "17岁"))

    assert ids == {9000002} and song.match_step == "artist_page"


@pytest.mark.parametrize("listed", ["南山南（feat. 宋冬野）", "南山南 feat. 宋冬野"])
def test_w7_15_a_title_with_a_featured_artist_in_cjk_brackets(conn, tmp_path, listed):
    ug = FakeUG()
    serve_artist(ug, "马頔", [(9000001, "Another Song"), (9000002, listed)])

    song, ids = look_up(conn, tmp_path, ug, wanted(conn, "马頔", "南山南"))

    assert ids == {9000002} and song.match_step == "artist_page"


@pytest.mark.xfail(strict=True, raises=AssertionError,
                   reason="W7-16: a romanization is split from its translation only where pypinyin "
                          "reads the characters the same; 重来 is chong lai, pypinyin says zhong lai")
def test_w7_16_a_romanization_of_a_polyphonic_character(conn, tmp_path):
    ug = FakeUG()
    serve_artist(ug, "宋冬野", [(9000001, "Another Song"), (9000002, "重来 Chong Lai Start Over")])

    song, ids = look_up(conn, tmp_path, ug, wanted(conn, "宋冬野", "Chong Lai"))

    assert ids == {9000002} and song.match_step == "artist_page"
