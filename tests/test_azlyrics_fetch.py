"""The AZLyrics step: which songs it asks, what it keeps, its two requests, and errors that are never misses.

AZLyrics is played by ``FakeAzLyrics`` behind a real ``PoliteClient`` (tests/helpers/azlyrics_site.py), so the forever
cache, a block and the robots rules are the client's real behaviour.
"""

from __future__ import annotations

import json
from datetime import timedelta

import pytest
from conftest import add_song
from helpers.azlyrics_site import ARTIST, NOW, SONG, FakeAzLyrics, artist_page, lyrics_page

from caracole.azlyrics_fetch import CHECKED, FAILED, AzLyricsStats, azlyrics_lyrics
from caracole.db import kv_get, kv_set
from caracole.http import ProviderBlocked
from caracole.library import lyrics_from
from caracole.lyrics import Lyrics, lyrics_from_json
from caracole.overrides import override_key
from caracole.songs import get_song, update_song

STAMP = "2026-10-30T03:30:00Z"
EARLIER = "2026-10-29T03:30:00Z"
PAGE = "https://www.azlyrics.com/lyrics/pomme/mononoke.html"


def run(site: FakeAzLyrics, conn, tmp_path, now=NOW, **kw) -> AzLyricsStats:
    """One pass, as one nightly run makes it: a fresh client on the shared cache."""
    return azlyrics_lyrics(conn, site.client(tmp_path / "cache", now=now), tmp_path / "lib", now, **kw)


def mononoke(conn, *, status="missing", lyrics=None, artist="pomme", title="mononoke"):
    """pomme – mononoke, as the sites before it left it: missing by default."""
    song = add_song(conn, artist, title)
    update_song(conn, song.id, lyrics_status=status, lyrics_at=EARLIER if status != "pending" else None,
                lyrics_json=lyrics.to_json() if lyrics is not None else None)
    return get_song(conn, song.id)


def folder(tmp_path):
    return tmp_path / "lib" / "pomme" / "mononoke"


def test_a_song_the_sites_before_it_missed_gets_its_lyrics_in_two_requests(conn, tmp_path):
    song = mononoke(conn)
    site = FakeAzLyrics()
    stats = run(site, conn, tmp_path)
    assert (stats.tried, stats.found, stats.missing) == (1, 1, 0)
    assert site.requests == [ARTIST, SONG]
    now = get_song(conn, song.id)
    assert now.lyrics_status == "found" and now.lyrics_at == STAMP
    kept = lyrics_from_json(now.lyrics_json)
    assert kept.provider == "azlyrics" and kept.url == PAGE and kept.synced is None
    assert kept.plain.startswith("[Couplet 1]\nDes mots inventés")
    assert (folder(tmp_path) / "lyrics.txt").read_text(encoding="utf-8") == kept.plain + "\n"
    assert not (folder(tmp_path) / "lyrics.lrc").exists()


def test_the_lyrics_credit_their_page(conn, tmp_path):
    song = mononoke(conn)
    run(FakeAzLyrics(), conn, tmp_path)
    assert lyrics_from(get_song(conn, song.id)) == {"source": "azlyrics", "href": PAGE}
    info = json.loads((folder(tmp_path) / "info.json").read_text(encoding="utf-8"))
    assert info["lyrics_from"] == {"source": "azlyrics", "href": PAGE}


def test_the_two_requests_come_one_right_after_the_other_as_configured():
    from caracole.config import DEFAULT_PROVIDERS, NO_BUDGET

    policy = DEFAULT_PROVIDERS["azlyrics"]
    assert policy.delay == (0.0, 0.0) and policy.lookup_delay == (0.0, 0.0) and policy.budget == NO_BUDGET


def test_a_song_lrclib_failed_on_is_asked(conn, tmp_path):
    song = mononoke(conn, status="pending")
    kv_set(conn, f"{FAILED}{song.id}", EARLIER)
    run(FakeAzLyrics(), conn, tmp_path)
    assert get_song(conn, song.id).lyrics_status == "found"
    assert kv_get(conn, f"{FAILED}{song.id}") is None


@pytest.mark.parametrize("status", ["pending", "instrumental"])
def test_a_song_never_asked_of_lrclib_or_an_instrumental_is_left_alone(conn, tmp_path, status):
    mononoke(conn, status=status)
    site = FakeAzLyrics()
    assert run(site, conn, tmp_path).tried == 0
    assert site.requests == []


def test_a_song_with_plain_lyrics_is_left_alone(conn, tmp_path):
    plain = Lyrics(plain="Une ligne", synced=None, instrumental=False, duration=None, lrclib_id=3, raw={"id": 3})
    mononoke(conn, status="found", lyrics=plain)
    site = FakeAzLyrics()
    assert run(site, conn, tmp_path).tried == 0
    assert site.requests == []


def test_an_ignored_song_is_left_alone(conn, tmp_path):
    song = mononoke(conn)
    update_song(conn, song.id, status="ignored")
    site = FakeAzLyrics()
    run(site, conn, tmp_path)
    assert site.requests == []


def test_only_the_songs_asked_for(conn, tmp_path):
    song = mononoke(conn)
    other = mononoke(conn, artist="Soda Stereo", title="Sobredosis de TV")
    site = FakeAzLyrics()
    run(site, conn, tmp_path, only={other.id})
    assert site.requests == ["/s/sodastereo.html"]
    assert get_song(conn, song.id).lyrics_status == "missing"


def test_two_songs_of_an_artist_read_their_page_once(conn, tmp_path):
    mononoke(conn)
    mononoke(conn, title="2019")
    site = FakeAzLyrics()
    run(site, conn, tmp_path)
    assert site.requests.count(ARTIST) == 1


def test_no_such_artist_is_a_miss_of_one_request(conn, tmp_path):
    song = mononoke(conn, artist="Misc Musicals", title="Hadestown Wait For Me")
    site = FakeAzLyrics()
    stats = run(site, conn, tmp_path)
    assert (stats.found, stats.missing, stats.errors) == (0, 1, 0)
    assert site.requests == ["/m/miscmusicals.html"]
    assert get_song(conn, song.id).lyrics_status == "missing"
    assert kv_get(conn, f"{CHECKED}{song.id}") == STAMP


def test_a_name_with_no_address_is_a_miss_of_no_request(conn, tmp_path):
    song = mononoke(conn, artist="宋冬野", title="斑马斑马")
    site = FakeAzLyrics()
    assert run(site, conn, tmp_path).missing == 1
    assert site.requests == []
    assert kv_get(conn, f"{CHECKED}{song.id}") == STAMP


def test_a_song_not_on_its_artists_page_is_a_miss_of_one_request(conn, tmp_path):
    song = mononoke(conn, title="Grandiose")
    site = FakeAzLyrics()
    assert run(site, conn, tmp_path).missing == 1
    assert site.requests == [ARTIST]
    assert kv_get(conn, f"{CHECKED}{song.id}") == STAMP


def test_a_lyrics_page_gone_is_a_miss(conn, tmp_path):
    song = mononoke(conn)
    site = FakeAzLyrics({ARTIST: artist_page()})
    assert run(site, conn, tmp_path).missing == 1
    assert get_song(conn, song.id).lyrics_status == "missing"


def test_a_miss_isnt_asked_again_for_30_days_then_past_the_cache(conn, tmp_path):
    mononoke(conn, title="Grandiose")
    site = FakeAzLyrics()
    run(site, conn, tmp_path)
    assert run(site, conn, tmp_path, NOW + timedelta(days=29)).tried == 0
    assert site.requests == [ARTIST]
    run(site, conn, tmp_path, NOW + timedelta(days=31))
    assert site.requests == [ARTIST, ARTIST]


def test_a_song_the_site_gains_is_found_when_its_miss_is_asked_again(conn, tmp_path):
    song = mononoke(conn, title="Grandiose")
    site = FakeAzLyrics()
    run(site, conn, tmp_path)
    site.pages[ARTIST] = artist_page().replace("mononoke</a>", "Grandiose</a>")
    site.pages[SONG] = lyrics_page()
    run(site, conn, tmp_path, NOW + timedelta(days=31))
    assert get_song(conn, song.id).lyrics_status == "found"
    assert kv_get(conn, f"{CHECKED}{song.id}") is None


def test_a_page_you_named_takes_one_request_whoever_it_credits(conn, tmp_path):
    song = mononoke(conn, artist="Misc Musicals", title="Mononoke At Night")
    site = FakeAzLyrics()
    run(site, conn, tmp_path, picks={override_key(song.display): PAGE})
    assert site.requests == [SONG]
    assert lyrics_from_json(get_song(conn, song.id).lyrics_json).url == PAGE


def test_a_page_you_named_is_asked_after_a_miss_and_for_a_song_lrclib_hasnt_failed_on(conn, tmp_path):
    missed = mononoke(conn, artist="Misc Musicals", title="One")
    kv_set(conn, f"{CHECKED}{missed.id}", EARLIER)
    waiting = mononoke(conn, artist="Misc Musicals", title="Two", status="pending")
    site = FakeAzLyrics()
    run(site, conn, tmp_path, picks={override_key(s.display): PAGE for s in (missed, waiting)})
    assert get_song(conn, missed.id).lyrics_status == "found"
    assert get_song(conn, waiting.id).lyrics_status == "found"


def test_a_page_you_named_is_not_asked_for_a_song_with_lyrics(conn, tmp_path):
    plain = Lyrics(plain="Une ligne", synced=None, instrumental=False, duration=None, lrclib_id=3, raw={"id": 3})
    song = mononoke(conn, status="found", lyrics=plain)
    site = FakeAzLyrics()
    run(site, conn, tmp_path, picks={override_key(song.display): PAGE})
    assert site.requests == []


def test_a_song_lrclib_failed_on_and_azlyrics_lacks_stays_pending(conn, tmp_path):
    song = mononoke(conn, status="pending", title="Grandiose")
    kv_set(conn, f"{FAILED}{song.id}", EARLIER)
    run(FakeAzLyrics(), conn, tmp_path)
    assert get_song(conn, song.id).lyrics_status == "pending"
    assert kv_get(conn, f"{CHECKED}{song.id}") == STAMP


@pytest.mark.parametrize("failing", [ARTIST, SONG])
def test_an_error_on_a_song_the_others_missed_puts_it_back_to_pending(conn, tmp_path, failing):
    song = mononoke(conn)
    stats = run(FakeAzLyrics(failing={failing: 500}), conn, tmp_path)
    assert (stats.errors, stats.found, stats.missing) == (1, 0, 0)
    assert get_song(conn, song.id).lyrics_status == "pending"
    assert kv_get(conn, f"{CHECKED}{song.id}") is None


@pytest.mark.parametrize(("path", "page"), [
    (ARTIST, "<html>a maintenance notice</html>"),
    (SONG, "<html>a maintenance notice</html>"),
])
def test_a_page_that_wont_parse_is_an_error_never_a_miss(conn, tmp_path, path, page):
    song = mononoke(conn)
    site = FakeAzLyrics({**FakeAzLyrics().pages, path: page})
    stats = run(site, conn, tmp_path)
    assert (stats.errors, stats.missing) == (1, 0)
    assert get_song(conn, song.id).lyrics_status == "pending"
    assert kv_get(conn, f"{CHECKED}{song.id}") is None


def test_a_cached_page_that_wont_parse_is_asked_for_once_more(conn, tmp_path):
    song = mononoke(conn)
    site = FakeAzLyrics({**FakeAzLyrics().pages, SONG: "<html>a maintenance notice</html>"})
    run(site, conn, tmp_path)
    update_song(conn, song.id, lyrics_status="missing")
    site.pages[SONG] = lyrics_page()
    run(site, conn, tmp_path)
    assert site.requests == [ARTIST, SONG, SONG]
    assert get_song(conn, song.id).lyrics_status == "found"


@pytest.mark.parametrize("failing", [ARTIST, SONG])
def test_its_block_page_a_200_is_a_block_and_marks_nothing(conn, tmp_path, failing):
    song = mononoke(conn)
    with pytest.raises(ProviderBlocked):
        run(FakeAzLyrics(failing={failing: "block"}), conn, tmp_path)
    now = get_song(conn, song.id)
    assert now.lyrics_status == "missing" and kv_get(conn, f"{CHECKED}{song.id}") is None


def test_its_block_page_is_never_kept_in_the_cache(conn, tmp_path):
    mononoke(conn)
    site = FakeAzLyrics(failing={ARTIST: "block"})
    with pytest.raises(ProviderBlocked):
        run(site, conn, tmp_path)
    site.failing.clear()
    assert run(site, conn, tmp_path).found == 1
    assert site.requests == [ARTIST, ARTIST, SONG]


def test_a_403_is_a_block_and_nothing_more_is_sent(conn, tmp_path):
    mononoke(conn)
    mononoke(conn, artist="Soda Stereo", title="Sobredosis de TV")
    site = FakeAzLyrics(failing={ARTIST: 403, "/s/sodastereo.html": 403})
    with pytest.raises(ProviderBlocked):
        run(site, conn, tmp_path)
    assert len(site.requests) == 1


def test_three_errors_in_a_row_end_the_pass_and_name_the_songs_left(conn, tmp_path):
    for n in range(5):
        mononoke(conn, artist=f"Band {n}", title="Song")
    site = FakeAzLyrics(failing={f"/b/band{n}.html": 500 for n in range(5)})
    stats = run(site, conn, tmp_path)
    assert len(site.requests) == 3
    assert len(stats.failures) == 5


def test_caracole_asks_with_its_own_user_agent(conn, tmp_path):
    mononoke(conn)
    site = FakeAzLyrics()
    client = site.client(tmp_path / "cache", user_agent="caracole/0.1 (personal tab library)")
    azlyrics_lyrics(conn, client, tmp_path / "lib", NOW)
    assert set(site.agents) == {"caracole/0.1 (personal tab library)"}


def test_megalobiz_may_time_azlyrics_lyrics_later(conn, tmp_path):
    from caracole.megalobiz_fetch import songs_to_ask

    song = mononoke(conn)
    run(FakeAzLyrics(), conn, tmp_path)
    assert [s.id for s in songs_to_ask(conn, NOW)] == [song.id]


def test_its_miss_goes_with_the_song():
    from caracole.songs import _PER_SONG_KV

    assert CHECKED in _PER_SONG_KV
