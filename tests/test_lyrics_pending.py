"""Lyrics for pending songs: which songs are looked up, what is stored, and errors.

LRCLIB is played by ``FakeLrclib`` behind a real ``PoliteClient`` (through
``httpx.MockTransport``), so the forever cache, the budget and the re-check of
an old miss are the client's real behaviour. Records come from the fixtures in
``tests/fixtures/lrclib/`` (real structure, synthetic lyrics).
"""

from __future__ import annotations

import json
import os
import stat
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest
from conftest import add_song

from caracole.config import ProviderPolicy
from caracole.http import PoliteClient, ProviderBlocked
from caracole.lyrics import LyricsStats, fetch_pending_lyrics, lyrics_from_json
from caracole.songs import get_song, update_song

FIXTURES = Path(__file__).parent / "fixtures" / "lrclib"
NOW = datetime(2026, 10, 18, 3, 30, tzinfo=UTC)
STAMP = "2026-10-18T03:30:00Z"


def load(name: str):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def record(**fields):
    """The get_hit record (Soda Stereo – De Música Ligera, 213 s) with fields replaced."""
    return {**load("get_hit.json"), **fields}


class FakeLrclib:
    """LRCLIB's ``/api/get`` and ``/api/search``, answering from a list of records.

    ``/api/get`` finds a record by artist and track, and by album and duration
    (±2 s) when they are sent; a miss answers ``get_miss``, which is LRCLIB's
    503 today (spike) and its documented 404 otherwise. ``/api/search`` lists
    the records with that track name. ``broken`` maps an artist, and
    ``failing`` an endpoint ("get", "search"), to the status every request
    about it gets. Every request that reaches it is recorded.
    """

    def __init__(self, records=(), *, get_miss: int = 503, broken=None, failing=None):
        self.records = list(records)
        self.get_miss = get_miss
        self.broken = dict(broken or {})
        self.failing = dict(failing or {})
        self.requests: list[tuple[str, dict]] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        endpoint = request.url.path.removeprefix("/api/")
        params = dict(request.url.params)
        self.requests.append((endpoint, params))
        if params.get("artist_name") in self.broken:
            return httpx.Response(self.broken[params["artist_name"]], json={"name": "Error"})
        if endpoint in self.failing:
            return httpx.Response(self.failing[endpoint], text="Bad Gateway")
        if endpoint == "get":
            for r in self.records:
                if self._gets(r, params):
                    return httpx.Response(200, json=r)
            return httpx.Response(self.get_miss, json={"name": "TrackNotFound"})
        if endpoint == "search":
            named = [r for r in self.records if r["trackName"] == params["track_name"]]
            return httpx.Response(200, json=named)
        raise AssertionError(f"unexpected request: {request.url}")

    @staticmethod
    def _gets(r: dict, params: dict) -> bool:
        if (r["artistName"], r["trackName"]) != (params["artist_name"], params["track_name"]):
            return False
        if "album_name" in params and r["albumName"].casefold() != params["album_name"].casefold():
            return False
        return "duration" not in params or abs(r["duration"] - int(params["duration"])) <= 2

    def endpoints(self) -> list[str]:
        return [endpoint for endpoint, _ in self.requests]

    def client(self, cache_dir: Path, *, budget: int = 200, now: datetime = NOW) -> PoliteClient:
        return PoliteClient(
            "lrclib",
            ProviderPolicy(budget=budget, delay=(0.0, 0.0)),
            cache_dir,
            user_agent="caracole-test",
            transport=httpx.MockTransport(self.handler),
            sleep=lambda seconds: None,
            wall_clock=lambda: now,
        )


def run(lrclib: FakeLrclib, conn, tmp_path: Path, now: datetime = NOW, *, budget: int = 200, **kw):
    """One pass, as one nightly run would make it: a fresh client on the shared cache."""
    client = lrclib.client(tmp_path / "cache", budget=budget, now=now)
    return fetch_pending_lyrics(conn, client, tmp_path / "lib", now, **kw)


def folder(tmp_path: Path, artist: str, title: str) -> Path:
    return tmp_path / "lib" / artist / title


# --- what is stored ------------------------------------------------------------


def test_found_lyrics_are_written_and_stored(conn, tmp_path):
    hit = load("get_hit.json")
    song = add_song(conn, "Soda Stereo", "De Música Ligera")
    stats = run(FakeLrclib([hit]), conn, tmp_path)
    assert stats == LyricsStats(tried=1, found=1)
    here = folder(tmp_path, "Soda Stereo", "De Música Ligera")
    assert (here / "lyrics.txt").read_text(encoding="utf-8") == hit["plainLyrics"] + "\n"
    assert (here / "lyrics.lrc").read_text(encoding="utf-8").startswith("[00:23.62] Línea uno")
    stored = get_song(conn, song.id)
    assert (stored.lyrics_status, stored.lyrics_at) == ("found", STAMP)
    assert lyrics_from_json(stored.lyrics_json).lrclib_id == 1040023


def test_lookup_uses_the_first_artist_the_clean_title_the_album_and_the_duration(conn, tmp_path):
    lrclib = FakeLrclib([record(albumName="Canción Animal")])
    add_song(conn, artists=["Soda Stereo", "Andrea Echeverri"],
             title="De Música Ligera - Remasterizado 2007", album="Canción Animal",
             duration_ms=212600)
    run(lrclib, conn, tmp_path)
    assert lrclib.requests == [("get", {
        "artist_name": "Soda Stereo",
        "track_name": "De Música Ligera",
        "album_name": "Canción Animal",
        "duration": "213",
    })]


def test_a_length_given_for_a_song_with_none_of_its_own_goes_to_lrclib(conn, tmp_path):
    # A sheet from a YouTube video: LRCLIB is asked with the audio's length, so the timed lyrics it gives fit it.
    lrclib = FakeLrclib([record(duration=240.0), record(id=7, duration=213.0)])
    own = add_song(conn, "Soda Stereo", "De Música Ligera", duration_ms=None)
    run(lrclib, conn, tmp_path, durations={own.id: 212.6})
    assert lrclib.requests == [("get", {"artist_name": "Soda Stereo", "track_name": "De Música Ligera",
                                        "duration": "213"})]
    assert lyrics_from_json(get_song(conn, own.id).lyrics_json).lrclib_id == 7


def test_a_songs_own_length_wins_over_one_given(conn, tmp_path):
    lrclib = FakeLrclib([record()])
    add_song(conn, "Soda Stereo", "De Música Ligera", duration_ms=213000)
    song = get_song(conn, 1)
    run(lrclib, conn, tmp_path, durations={song.id: 240.0})
    assert lrclib.requests[0][1]["duration"] == "213"


def test_a_miss_is_recorded_with_its_time_and_writes_nothing(conn, tmp_path):
    lrclib = FakeLrclib([load("get_hit.json")])
    song = add_song(conn, "Soda Stereo", "Canción Inexistente")
    stats = run(lrclib, conn, tmp_path)
    assert stats == LyricsStats(tried=1, missing=1)
    assert lrclib.endpoints() == ["get", "search"]
    stored = get_song(conn, song.id)
    assert (stored.lyrics_status, stored.lyrics_at, stored.lyrics_json) == ("missing", STAMP, None)
    assert not (tmp_path / "lib").exists()


def test_an_instrumental_is_stored_without_lyric_files(conn, tmp_path):
    song = add_song(conn, "Conjunto de Prueba", "Interludio de Prueba", duration_ms=184000)
    stats = run(FakeLrclib([load("get_instrumental.json")]), conn, tmp_path)
    assert stats == LyricsStats(tried=1, instrumental=1)
    stored = get_song(conn, song.id)
    assert (stored.lyrics_status, stored.lyrics_at) == ("instrumental", STAMP)
    assert lyrics_from_json(stored.lyrics_json).lrclib_id == 4242424
    assert not (tmp_path / "lib").exists()


def test_banma_banma_plain_lyrics_are_saved_without_an_lrc(conn, tmp_path):
    # 宋冬野's records have plain lyrics only. A line may write the title 斑马，斑马, which
    # /api/get doesn't know; /api/search finds it as 斑马斑马, and the album's cut wins.
    song = add_song(conn, "宋冬野", "斑马，斑马", album="安和桥北", duration_ms=253000)
    stats = run(FakeLrclib(load("search_banma.json")), conn, tmp_path)
    assert stats == LyricsStats(tried=1, found=1)
    here = folder(tmp_path, "宋冬野", "斑马，斑马")
    assert (here / "lyrics.txt").read_text(encoding="utf-8").startswith("範例歌詞 第一行")
    assert not (here / "lyrics.lrc").exists()
    assert lyrics_from_json(get_song(conn, song.id).lyrics_json).lrclib_id == 29499942


def test_lyrics_go_into_the_library_folder_even_for_unsafe_names(conn, tmp_path):
    lrclib = FakeLrclib([record(artistName="AC/DC", trackName="Live: Wire?", duration=213.0)])
    add_song(conn, "AC/DC", "Live: Wire?")
    run(lrclib, conn, tmp_path)
    assert (folder(tmp_path, "AC-DC", "Live - Wire") / "lyrics.txt").is_file()


def test_lyric_files_stay_group_readable_under_the_service_umask(conn, tmp_path):
    # The service runs with UMask=0007; Syncthing reads the library through the group.
    add_song(conn, "Soda Stereo", "De Música Ligera")
    old = os.umask(0o007)
    try:
        run(FakeLrclib([load("get_hit.json")]), conn, tmp_path)
    finally:
        os.umask(old)
    here = folder(tmp_path, "Soda Stereo", "De Música Ligera")
    assert stat.S_IMODE((here / "lyrics.txt").stat().st_mode) == 0o660
    assert stat.S_IMODE((here / "lyrics.lrc").stat().st_mode) == 0o660
    assert stat.S_IMODE(here.stat().st_mode) == 0o770


# --- errors are never misses -----------------------------------------------------


def test_an_error_leaves_the_song_pending_and_the_pass_goes_on(conn, tmp_path):
    lrclib = FakeLrclib([load("get_hit.json")], broken={"Artista Roto": 500})
    broken = add_song(conn, "Artista Roto", "Canción Rota", added_at="2026-10-02T00:00:00Z")
    fine = add_song(conn, "Soda Stereo", "De Música Ligera", added_at="2026-10-01T00:00:00Z")
    stats = run(lrclib, conn, tmp_path)
    assert stats == LyricsStats(tried=2, found=1, errors=1)
    stored = get_song(conn, broken.id)
    assert (stored.lyrics_status, stored.lyrics_at) == ("pending", None)
    assert get_song(conn, fine.id).lyrics_status == "found"


def test_an_error_on_the_search_fallback_is_not_a_miss(conn, tmp_path):
    lrclib = FakeLrclib(failing={"search": 502})
    song = add_song(conn, "Soda Stereo", "Canción Inexistente")
    stats = run(lrclib, conn, tmp_path)
    assert stats == LyricsStats(tried=1, errors=1)
    assert lrclib.endpoints() == ["get", "search"]
    stored = get_song(conn, song.id)
    assert (stored.lyrics_status, stored.lyrics_at) == ("pending", None)


class Glitchy(FakeLrclib):
    """``FakeLrclib`` whose endpoints ("get", "search") answer their first requests from
    ``first``, as ``(status, text)``, before they answer as LRCLIB does."""

    def __init__(self, records=(), *, first, **kw):
        super().__init__(records, **kw)
        self.first = {endpoint: list(answers) for endpoint, answers in first.items()}

    def handler(self, request: httpx.Request) -> httpx.Response:
        endpoint = request.url.path.removeprefix("/api/")
        if not self.first.get(endpoint):
            return super().handler(request)
        self.requests.append((endpoint, dict(request.url.params)))
        status, text = self.first[endpoint].pop(0)
        return httpx.Response(status, text=text)


NOTICE = (200, "<html><title>Maintenance</title></html>")  # a 200, so cached like a record


@pytest.mark.parametrize("glitch", [NOTICE, (200, "[]")], ids=["not JSON", "no object"])
def test_a_cached_answer_that_isnt_json_is_asked_for_once_more(conn, tmp_path, glitch):
    # Answers are cached forever: the notice would fail the song, from the cache, every night.
    lrclib = Glitchy([record()], first={"get": [glitch]})
    song = add_song(conn, "Soda Stereo", "De Música Ligera", duration_ms=213000)
    assert run(lrclib, conn, tmp_path) == LyricsStats(tried=1, errors=1)
    assert run(lrclib, conn, tmp_path) == LyricsStats(tried=1, found=1)
    assert lrclib.endpoints() == ["get", "get"]
    assert get_song(conn, song.id).lyrics_status == "found"


def test_an_answer_still_not_json_when_asked_again_is_an_error_for_one_more_request(conn, tmp_path):
    lrclib = Glitchy([record()], first={"get": [NOTICE, NOTICE]})
    song = add_song(conn, "Soda Stereo", "De Música Ligera", duration_ms=213000)
    run(lrclib, conn, tmp_path)
    assert run(lrclib, conn, tmp_path) == LyricsStats(tried=1, errors=1)
    assert lrclib.endpoints() == ["get", "get"]
    stored = get_song(conn, song.id)
    assert (stored.lyrics_status, stored.lyrics_at) == ("pending", None)


def test_a_503_that_isnt_json_when_asked_again_still_falls_back_to_the_search(conn, tmp_path):
    # LRCLIB answers a miss with 503; a proxy's 503 page is no JSON, and is no error either.
    lrclib = Glitchy([record()], first={"get": [NOTICE, (503, "Service Unavailable")]})
    song = add_song(conn, "Soda Stereo", "De Música Ligera", duration_ms=213000)
    run(lrclib, conn, tmp_path)
    assert run(lrclib, conn, tmp_path) == LyricsStats(tried=1, found=1)
    assert lrclib.endpoints() == ["get", "get", "search"]
    assert get_song(conn, song.id).lyrics_status == "found"


def test_a_cached_search_that_isnt_json_is_asked_for_once_more(conn, tmp_path):
    lrclib = Glitchy([record()], first={"search": [NOTICE]})
    song = add_song(conn, "Soda Stereo", "De Música Ligera", album="Otro Disco", duration_ms=213000)
    assert run(lrclib, conn, tmp_path) == LyricsStats(tried=1, errors=1)  # /api/get misses: another album
    assert run(lrclib, conn, tmp_path) == LyricsStats(tried=1, found=1)
    assert lrclib.endpoints() == ["get", "search", "get", "search"]  # the second search: once more
    assert get_song(conn, song.id).lyrics_status == "found"


def test_a_block_propagates_and_marks_nothing(conn, tmp_path):
    song = add_song(conn, "Soda Stereo", "De Música Ligera")
    with pytest.raises(ProviderBlocked):
        run(FakeLrclib(broken={"Soda Stereo": 429}), conn, tmp_path)
    stored = get_song(conn, song.id)
    assert (stored.lyrics_status, stored.lyrics_at) == ("pending", None)


def test_an_exhausted_budget_ends_the_pass_newest_song_first(conn, tmp_path):
    lrclib = FakeLrclib([load("get_hit.json")])
    older = add_song(conn, "Soda Stereo", "Persiana Americana", added_at="2026-10-01T00:00:00Z")
    newer = add_song(conn, "Soda Stereo", "De Música Ligera", added_at="2026-10-02T00:00:00Z")
    stats = run(lrclib, conn, tmp_path, budget=1)
    assert stats == LyricsStats(tried=1, found=1, budget_exhausted=True)
    assert get_song(conn, newer.id).lyrics_status == "found"
    stored = get_song(conn, older.id)
    assert (stored.lyrics_status, stored.lyrics_at) == ("pending", None)
    assert len(lrclib.requests) == 1


def test_three_errors_in_a_row_end_the_pass(conn, tmp_path):
    # PoliteClient stops asking a provider after three errors in a row in one run.
    names = ["Uno", "Dos", "Tres", "Cuatro", "Cinco"]
    lrclib = FakeLrclib(broken={name: 500 for name in names})
    songs = [
        add_song(conn, name, "Canción", added_at=f"2026-10-0{i + 1}T00:00:00Z")
        for i, name in enumerate(names)
    ]
    stats = run(lrclib, conn, tmp_path)
    assert stats == LyricsStats(tried=3, errors=3)
    assert len(lrclib.requests) == 3
    assert {get_song(conn, s.id).lyrics_status for s in songs} == {"pending"}


def test_the_pass_names_each_song_an_error_left_with_its_error(conn, tmp_path):
    # For the run's summary, which says why in words, and counts the songs of each cause.
    lrclib = FakeLrclib([load("get_hit.json")], broken={"Artista Roto": 500})
    broken = add_song(conn, "Artista Roto", "Canción Rota", added_at="2026-10-02T00:00:00Z")
    add_song(conn, "Soda Stereo", "De Música Ligera", added_at="2026-10-01T00:00:00Z")
    [(song, error)] = run(lrclib, conn, tmp_path).failures
    assert (song.id, error.provider, error.status) == (broken.id, "lrclib", 500)


def test_the_songs_left_once_lrclib_is_given_up_on_are_named_too(conn, tmp_path):
    names = ["Uno", "Dos", "Tres", "Cuatro", "Cinco"]
    lrclib = FakeLrclib(broken={name: 500 for name in names})
    for i, name in enumerate(names):
        add_song(conn, name, "Canción", added_at=f"2026-10-0{i + 1}T00:00:00Z")
    stats = run(lrclib, conn, tmp_path)
    assert stats == LyricsStats(tried=3, errors=3)  # the songs never asked about are no errors
    assert [(song.artist, type(error).__name__) for song, error in stats.failures] == [
        ("Cinco", "ProviderError"), ("Cuatro", "ProviderError"), ("Tres", "ProviderError"),
        ("Dos", "ProviderUnavailable"), ("Uno", "ProviderUnavailable"),
    ]


# --- which songs ----------------------------------------------------------------


def test_ignored_songs_are_not_looked_up(conn, tmp_path):
    song = add_song(conn, "Soda Stereo", "De Música Ligera")
    update_song(conn, song.id, status="ignored")
    lrclib = FakeLrclib([load("get_hit.json")])
    assert run(lrclib, conn, tmp_path) == LyricsStats()
    assert lrclib.requests == []


def test_settled_songs_are_left_alone(conn, tmp_path):
    old = "2026-01-01T00:00:00Z"
    recent = (NOW - timedelta(days=29)).strftime("%Y-%m-%dT%H:%M:%SZ")
    settled = [("Uno", "found", old), ("Dos", "instrumental", old), ("Tres", "missing", recent)]
    for title, status, at in settled:
        song = add_song(conn, "Soda Stereo", title)
        update_song(conn, song.id, lyrics_status=status, lyrics_at=at)
    lrclib = FakeLrclib()
    assert run(lrclib, conn, tmp_path) == LyricsStats()
    assert lrclib.requests == []


def test_a_miss_is_asked_again_past_the_cache_after_30_days(conn, tmp_path):
    # Misses answered 404 are cached forever, like the search's [], so only a
    # lookup that gets past the cache can see what LRCLIB has since added.
    lrclib = FakeLrclib(get_miss=404)
    song = add_song(conn, "Soda Stereo", "De Música Ligera")
    assert run(lrclib, conn, tmp_path) == LyricsStats(tried=1, missing=1)
    lrclib.records.append(load("get_hit.json"))

    assert run(lrclib, conn, tmp_path, NOW + timedelta(days=29)) == LyricsStats()
    assert lrclib.endpoints() == ["get", "search"]

    later = NOW + timedelta(days=31)
    assert run(lrclib, conn, tmp_path, later) == LyricsStats(tried=1, found=1)
    assert lrclib.endpoints() == ["get", "search", "get"]
    stored = get_song(conn, song.id)
    assert (stored.lyrics_status, stored.lyrics_at) == ("found", "2026-11-18T03:30:00Z")
    assert (folder(tmp_path, "Soda Stereo", "De Música Ligera") / "lyrics.txt").is_file()


def test_a_miss_still_missing_after_30_days_gets_a_new_time(conn, tmp_path):
    lrclib = FakeLrclib()
    song = add_song(conn, "Soda Stereo", "Canción Inexistente")
    run(lrclib, conn, tmp_path)
    later = NOW + timedelta(days=31)
    assert run(lrclib, conn, tmp_path, later) == LyricsStats(tried=1, missing=1)
    assert lrclib.endpoints() == ["get", "search", "get", "search"]
    assert get_song(conn, song.id).lyrics_at == "2026-11-18T03:30:00Z"


def test_a_miss_without_a_time_is_asked_again(conn, tmp_path):
    song = add_song(conn, "Soda Stereo", "De Música Ligera")
    update_song(conn, song.id, lyrics_status="missing")
    assert run(FakeLrclib([load("get_hit.json")]), conn, tmp_path) == LyricsStats(tried=1, found=1)


def test_the_recheck_window_can_be_shortened(conn, tmp_path):
    lrclib = FakeLrclib()
    add_song(conn, "Soda Stereo", "Canción Inexistente")
    run(lrclib, conn, tmp_path)
    later = NOW + timedelta(days=8)
    assert run(lrclib, conn, tmp_path, later, recheck_missing_after=timedelta(days=7)).missing == 1
    assert lrclib.endpoints() == ["get", "search", "get", "search"]


def test_songs_never_looked_up_come_before_old_misses(conn, tmp_path):
    lrclib = FakeLrclib([load("get_hit.json")])
    miss = add_song(conn, "Soda Stereo", "Canción Inexistente", added_at="2026-10-05T00:00:00Z")
    update_song(conn, miss.id, lyrics_status="missing", lyrics_at="2026-01-01T00:00:00Z")
    pending = add_song(conn, "Soda Stereo", "De Música Ligera", added_at="2026-10-01T00:00:00Z")
    assert run(lrclib, conn, tmp_path, budget=1) == LyricsStats(tried=1, found=1, budget_exhausted=True)
    assert get_song(conn, pending.id).lyrics_status == "found"
    assert get_song(conn, miss.id).lyrics_at == "2026-01-01T00:00:00Z"


def test_a_recheck_the_budget_cannot_pay_for_changes_nothing(conn, tmp_path):
    # Once the budget is spent the client may still serve an old cached answer;
    # the old miss must not pass for a fresh one.
    lrclib = FakeLrclib(get_miss=404)
    miss = add_song(conn, "Soda Stereo", "Canción Inexistente", added_at="2026-10-01T00:00:00Z")
    run(lrclib, conn, tmp_path)
    add_song(conn, "Soda Stereo", "De Música Ligera", added_at="2026-10-02T00:00:00Z")
    lrclib.records.append(load("get_hit.json"))
    later = NOW + timedelta(days=31)
    stats = run(lrclib, conn, tmp_path, later, budget=1)
    assert stats == LyricsStats(tried=1, found=1, budget_exhausted=True)
    stored = get_song(conn, miss.id)
    assert (stored.lyrics_status, stored.lyrics_at) == ("missing", STAMP)


# --- in the nightly run -----------------------------------------------------------


def test_the_nightly_lyrics_step_reports_the_counts(conn, cfg, tmp_path):
    from caracole.notify import Notifier
    from caracole.pipeline import Services, default_steps, run_pipeline

    add_song(conn, "Soda Stereo", "De Música Ligera")
    add_song(conn, "Soda Stereo", "Canción Inexistente")
    lrclib = FakeLrclib([load("get_hit.json")])
    services = Services(clients={"lrclib": lrclib.client(tmp_path / "cache")}, notifier=Notifier(None))
    steps = [s for s in default_steps() if s.name == "lyrics"]
    report = run_pipeline(cfg, conn=conn, services=services, steps=steps, now=NOW)
    assert report.steps == {"lyrics": "1 found, 1 missing, 0 instrumental, 0 errors"}
    assert (cfg.library_dir / "Soda Stereo" / "De Música Ligera" / "lyrics.txt").is_file()


def test_a_lookup_asks_for_its_own_songs_lyrics_alone(conn, tmp_path):
    # `caracole get`: one song asked for now; the others wait for the nightly run.
    wanted = add_song(conn, "Soda Stereo", "De Música Ligera", added_at="2026-10-01T00:00:00Z")
    newer = add_song(conn, "Soda Stereo", "Canción Inexistente", added_at="2026-10-05T00:00:00Z")
    lrclib = FakeLrclib([load("get_hit.json")])
    stats = run(lrclib, conn, tmp_path, only={wanted.id})
    assert stats == LyricsStats(tried=1, found=1)
    assert get_song(conn, newer.id).lyrics_status == "pending"
    assert all(params["track_name"] == "De Música Ligera" for _, params in lrclib.requests)
