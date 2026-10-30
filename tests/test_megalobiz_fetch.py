"""The Megalobiz step: which songs it asks, what it keeps, and errors that are never misses.

Megalobiz is played by ``FakeMegalobiz`` behind a real ``PoliteClient`` (tests/helpers/megalobiz_site.py), so the
forever cache, the budget and a block are the client's real behaviour.
"""

from __future__ import annotations

import json
from datetime import timedelta

import httpx
import pytest
from conftest import add_song
from helpers.megalobiz_site import NOW, FakeMegalobiz, record

from caracole.db import kv_get, kv_set
from caracole.http import ProviderBlocked
from caracole.lyrics import Lyrics, lyrics_from_json
from caracole.megalobiz_fetch import CHECKED, FAILED, MegalobizStats, megalobiz_lyrics
from caracole.songs import get_song, update_song

STAMP = "2026-10-30T03:30:00Z"
EARLIER = "2026-10-29T03:30:00Z"


def run(site: FakeMegalobiz, conn, tmp_path, now=NOW, *, budget: int = 60, **kw) -> MegalobizStats:
    """One pass, as one nightly run makes it: a fresh client on the shared cache."""
    client = site.client(tmp_path / "cache", budget=budget, now=now)
    return megalobiz_lyrics(conn, client, tmp_path / "lib", now, **kw)


def eagles(conn, *, status="missing", lyrics=None, **kw):
    """Eagles – Hotel California, 391 s long, as LRCLIB's pass left it: missing by default."""
    song = add_song(conn, "Eagles", "Hotel California", duration_ms=391000, **kw)
    update_song(conn, song.id, lyrics_status=status, lyrics_at=EARLIER if status != "pending" else None,
                lyrics_json=lyrics.to_json() if lyrics is not None else None)
    return get_song(conn, song.id)


PLAIN = Lyrics(plain="Una línea de prueba\nOtra línea", synced=None, instrumental=False, duration=391.0,
               lrclib_id=3, raw={"id": 3})
TIMED = Lyrics(plain="Una línea", synced="[00:01.00]Una línea", instrumental=False, duration=391.0, lrclib_id=4,
               raw={"id": 4})


def folder(tmp_path):
    return tmp_path / "lib" / "Eagles" / "Hotel California"


# --- what it keeps ---------------------------------------------------------------------------------------------------


def test_a_song_lrclib_missed_gets_megalobizs_timed_lyrics(conn, tmp_path):
    site = FakeMegalobiz([None])
    song = eagles(conn)
    stats = run(site, conn, tmp_path)
    assert stats == MegalobizStats(tried=1, found=1)
    assert site.endpoints() == ["search", "lrc"]
    assert (folder(tmp_path) / "lyrics.lrc").read_text(encoding="utf-8").startswith("[ar:Eagles]\n")
    assert (folder(tmp_path) / "lyrics.txt").read_text(encoding="utf-8").startswith("Línea uno de prueba")
    stored = get_song(conn, song.id)
    assert (stored.lyrics_status, stored.lyrics_at) == ("found", STAMP)
    lyrics = lyrics_from_json(stored.lyrics_json)
    assert (lyrics.provider, lyrics.url) == ("megalobiz", "https://megalobiz.com/lrc/24519/hotel-california")
    assert lyrics.synced.startswith("[ar:Eagles]") and lyrics.duration == 391.55
    assert "lrc" not in lyrics.raw and lyrics.raw["id"] == 24519  # the lyrics are kept once, in ``synced``
    info = json.loads((folder(tmp_path) / "info.json").read_text(encoding="utf-8"))
    assert info["lyrics_from"] == {"source": "megalobiz", "href": "https://megalobiz.com/lrc/24519/hotel-california"}


def test_the_search_asks_by_the_songs_names_and_length(conn, tmp_path):
    site = FakeMegalobiz([None])
    eagles(conn)
    run(site, conn, tmp_path)
    assert site.requests[0] == ("search", {"title": "Hotel California", "artist": "Eagles", "duration": "391",
                                           "limit": "10"})


def test_plain_lyrics_from_lrclib_become_timed_ones_from_megalobiz(conn, tmp_path):
    site = FakeMegalobiz([None])
    song = eagles(conn, status="found", lyrics=PLAIN)
    assert run(site, conn, tmp_path) == MegalobizStats(tried=1, timed=1)
    lyrics = lyrics_from_json(get_song(conn, song.id).lyrics_json)
    assert lyrics.provider == "megalobiz" and lyrics.synced
    assert (folder(tmp_path) / "lyrics.lrc").is_file()


def test_a_song_with_no_length_of_its_own_is_asked_with_lrclibs(conn, tmp_path):
    site = FakeMegalobiz([None])
    song = add_song(conn, "Eagles", "Hotel California", duration_ms=None)
    update_song(conn, song.id, lyrics_status="found", lyrics_json=PLAIN.to_json(), lyrics_at=EARLIER)
    run(site, conn, tmp_path)
    assert site.requests[0][1]["duration"] == "391"


def test_a_length_given_for_a_song_with_none_goes_to_megalobiz(conn, tmp_path):
    # A sheet from a YouTube video asks with its audio's length, as of LRCLIB.
    site = FakeMegalobiz([None])
    song = add_song(conn, "Eagles", "Hotel California", duration_ms=None)
    update_song(conn, song.id, lyrics_status="missing", lyrics_at=EARLIER)
    run(site, conn, tmp_path, durations={song.id: 390.6})
    assert site.requests[0][1]["duration"] == "391"


# --- which songs -----------------------------------------------------------------------------------------------------


def test_songs_lrclib_answered_well_or_never_asked_are_left_alone(conn, tmp_path):
    site = FakeMegalobiz([None])
    eagles(conn, status="found", lyrics=TIMED, added_at="2026-10-01T00:00:00Z")
    instrumental = add_song(conn, "Eagles", "Interlude", added_at="2026-10-02T00:00:00Z")
    update_song(conn, instrumental.id, lyrics_status="instrumental", lyrics_at=EARLIER)
    add_song(conn, "Eagles", "Desperado", added_at="2026-10-03T00:00:00Z")  # pending: LRCLIB hasn't answered yet
    ignored = add_song(conn, "Eagles", "Take It Easy", added_at="2026-10-04T00:00:00Z")
    update_song(conn, ignored.id, status="ignored", lyrics_status="missing", lyrics_at=EARLIER)
    assert run(site, conn, tmp_path) == MegalobizStats()
    assert site.requests == []


def test_a_song_lrclib_failed_on_is_asked(conn, tmp_path):
    site = FakeMegalobiz([None])
    song = eagles(conn, status="pending")
    kv_set(conn, f"{FAILED}{song.id}", EARLIER)
    assert run(site, conn, tmp_path) == MegalobizStats(tried=1, found=1)
    assert get_song(conn, song.id).lyrics_status == "found"
    assert kv_get(conn, f"{FAILED}{song.id}") is None


def test_only_the_songs_asked_for(conn, tmp_path):
    site = FakeMegalobiz([None])
    song = eagles(conn)
    other = add_song(conn, "Eagles", "Desperado")
    update_song(conn, other.id, lyrics_status="missing", lyrics_at=EARLIER)
    run(site, conn, tmp_path, only={song.id})
    assert all(params["title"] == "Hotel California" for endpoint, params in site.requests if endpoint == "search")


def test_songs_with_no_lyrics_come_before_those_with_plain_ones(conn, tmp_path):
    site = FakeMegalobiz([None, record(lrc_id=2, title="Desperado", duration=213.0)])
    eagles(conn, status="found", lyrics=PLAIN, added_at="2026-10-05T00:00:00Z")
    desperado = add_song(conn, "Eagles", "Desperado", added_at="2026-10-01T00:00:00Z")
    update_song(conn, desperado.id, lyrics_status="missing", lyrics_at=EARLIER)
    stats = run(site, conn, tmp_path, budget=2)
    assert stats == MegalobizStats(tried=1, found=1, budget_exhausted=True)
    assert get_song(conn, desperado.id).lyrics_status == "found"


# --- a miss ---------------------------------------------------------------------------------------------------------


def test_no_result_that_fits_is_a_miss_and_the_song_stays_missing(conn, tmp_path):
    # Megalovania's live search: another of Toby Fox's titles, a fan's "Vocal cover" credited to no one.
    site = FakeMegalobiz([record(lrc_id=17267, title="Undertale - Megalovania (Original lyricsVocal cover)", artist=""),
                          record(lrc_id=25483, title="The Field of Hopes and Dreams", artist="Toby Fox")])
    song = add_song(conn, "Toby Fox", "Megalovania", duration_ms=None)
    update_song(conn, song.id, lyrics_status="missing", lyrics_at=EARLIER)
    assert run(site, conn, tmp_path) == MegalobizStats(tried=1, missing=1)
    assert site.endpoints() == ["search"]
    stored = get_song(conn, song.id)
    assert (stored.lyrics_status, stored.lyrics_at) == ("missing", EARLIER)  # both sites answered a miss
    assert kv_get(conn, f"{CHECKED}{song.id}") == STAMP


def test_a_record_gone_is_a_miss(conn, tmp_path):
    # The search still lists it; its record answers 404.
    site = FakeMegalobiz([None])
    listed = site.handler

    def handler(request):
        if request.url.path.startswith("/api/public/v1/lrc/"):
            site.records = []
        return listed(request)

    site.handler = handler
    song = eagles(conn)
    assert run(site, conn, tmp_path) == MegalobizStats(tried=1, missing=1)
    assert site.endpoints() == ["search", "lrc"]
    assert get_song(conn, song.id).lyrics_status == "missing"


def test_a_miss_isnt_asked_again_for_30_days_then_past_the_cache(conn, tmp_path):
    site = FakeMegalobiz()
    song = eagles(conn)
    run(site, conn, tmp_path)
    site.records.append(record())
    assert run(site, conn, tmp_path, NOW + timedelta(days=29)) == MegalobizStats()
    assert run(site, conn, tmp_path, NOW + timedelta(days=31)) == MegalobizStats(tried=1, found=1)
    assert site.endpoints() == ["search", "search", "lrc"]  # the second search went past the cached miss
    assert get_song(conn, song.id).lyrics_status == "found"


def test_plain_lyrics_megalobiz_has_no_timing_for_are_kept(conn, tmp_path):
    site = FakeMegalobiz()
    song = eagles(conn, status="found", lyrics=PLAIN)
    assert run(site, conn, tmp_path) == MegalobizStats(tried=1, missing=1)
    stored = get_song(conn, song.id)
    assert stored.lyrics_status == "found" and lyrics_from_json(stored.lyrics_json) == PLAIN


def test_a_song_lrclib_failed_on_and_megalobiz_lacks_stays_pending(conn, tmp_path):
    # LRCLIB's error is never a miss: the song waits for LRCLIB's answer.
    site = FakeMegalobiz()
    song = eagles(conn, status="pending")
    kv_set(conn, f"{FAILED}{song.id}", EARLIER)
    assert run(site, conn, tmp_path) == MegalobizStats(tried=1, missing=1)
    assert (get_song(conn, song.id).lyrics_status, get_song(conn, song.id).lyrics_at) == ("pending", None)


# --- errors are never misses ------------------------------------------------------------------------------------------


@pytest.mark.parametrize("failing", [{"search": 503}, {"lrc": 502}], ids=["search", "record"])
def test_an_error_on_a_song_lrclib_missed_puts_it_back_to_pending(conn, tmp_path, failing):
    # A song is missing only once every site asked answered a miss: the next run asks both again, LRCLIB from its
    # cache.
    site = FakeMegalobiz([None], failing=failing)
    song = eagles(conn)
    stats = run(site, conn, tmp_path)
    assert (stats.tried, stats.errors, stats.found, stats.missing) == (1, 1, 0, 0)
    stored = get_song(conn, song.id)
    assert (stored.lyrics_status, stored.lyrics_at) == ("pending", None)
    assert kv_get(conn, f"{CHECKED}{song.id}") is None
    [(failed, error)] = stats.failures
    assert (failed.id, error.provider) == (song.id, "megalobiz")


def test_an_error_leaves_plain_lyrics_as_they_were(conn, tmp_path):
    site = FakeMegalobiz([None], failing={"search": 500})
    song = eagles(conn, status="found", lyrics=PLAIN)
    assert run(site, conn, tmp_path).errors == 1
    stored = get_song(conn, song.id)
    assert stored.lyrics_status == "found" and lyrics_from_json(stored.lyrics_json) == PLAIN
    assert kv_get(conn, f"{CHECKED}{song.id}") is None


def test_an_answer_that_isnt_json_is_an_error_and_asked_once_more_from_the_cache(conn, tmp_path):
    site = FakeMegalobiz([None])
    listed, notices = site.handler, [True]

    def handler(request):
        if notices and request.url.path.endswith("/search"):
            notices.pop()
            site.requests.append(("search", dict(request.url.params)))
            return httpx.Response(200, text="<html>Maintenance</html>")
        return listed(request)

    site.handler = handler
    song = eagles(conn)
    assert run(site, conn, tmp_path).errors == 1
    assert get_song(conn, song.id).lyrics_status == "pending"
    eagles_again = get_song(conn, song.id)
    update_song(conn, eagles_again.id, lyrics_status="missing", lyrics_at=EARLIER)  # LRCLIB's answer, from its cache
    assert run(site, conn, tmp_path) == MegalobizStats(tried=1, found=1)
    assert site.endpoints() == ["search", "search", "lrc"]  # the cached notice asked for once more


def test_a_429_is_a_block_and_marks_nothing(conn, tmp_path):
    site = FakeMegalobiz([None], failing={"search": 429})
    song = eagles(conn)
    with pytest.raises(ProviderBlocked):
        run(site, conn, tmp_path)
    stored = get_song(conn, song.id)
    assert (stored.lyrics_status, stored.lyrics_at) == ("missing", EARLIER)
    assert kv_get(conn, f"{CHECKED}{song.id}") is None


def test_three_errors_in_a_row_end_the_pass_and_name_the_songs_left(conn, tmp_path):
    site = FakeMegalobiz(failing={"search": 500})
    for n in range(5):
        song = add_song(conn, "Eagles", f"Song {n}", added_at=f"2026-10-0{n + 1}T00:00:00Z")
        update_song(conn, song.id, lyrics_status="missing", lyrics_at=EARLIER)
    stats = run(site, conn, tmp_path)
    assert (stats.tried, stats.errors, len(site.requests), len(stats.failures)) == (3, 3, 3, 5)


def test_a_spent_budget_ends_the_pass_and_marks_nothing(conn, tmp_path):
    site = FakeMegalobiz([None])
    song = eagles(conn)
    assert run(site, conn, tmp_path, budget=1) == MegalobizStats(budget_exhausted=True)
    stored = get_song(conn, song.id)
    assert (stored.lyrics_status, stored.lyrics_at) == ("missing", EARLIER)


def test_caracole_asks_with_its_own_user_agent(conn, tmp_path):
    from caracole.config import DEFAULT_USER_AGENT

    site = FakeMegalobiz([None])
    eagles(conn)
    client = site.client(tmp_path / "cache", user_agent=DEFAULT_USER_AGENT)
    megalobiz_lyrics(conn, client, tmp_path / "lib", NOW)
    assert set(site.agents) == {DEFAULT_USER_AGENT}


def test_the_record_is_stored_as_json_with_its_page(conn, tmp_path):
    site = FakeMegalobiz([None])
    song = eagles(conn)
    run(site, conn, tmp_path)
    stored = json.loads(get_song(conn, song.id).lyrics_json)
    assert (stored["provider"], stored["url"]) == ("megalobiz", "https://megalobiz.com/lrc/24519/hotel-california")
