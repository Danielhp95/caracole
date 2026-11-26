"""lyrics_search.py: what the three lyrics sites list under a name you type, for a song whose own name finds nothing.

LRCLIB is a fake here (``/api/search`` answers ``search``, ``/api/get`` ``got``), Megalobiz and AZLyrics
tests/helpers/' fakes, each behind a real ``PoliteClient`` made by ``_common.make_client`` (``transport_for``): nothing
reaches the network. The records are real response shapes with invented words.
"""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from conftest import add_song
from helpers.azlyrics_site import FakeAzLyrics, artist_page
from helpers.megalobiz_site import FakeMegalobiz
from helpers.megalobiz_site import record as mz_record

from caracole import db
from caracole.commands import _common
from caracole.health import get_state, is_cooling
from caracole.lyrics_search import KV, MOST_ROWS, PICKABLE_FOR, kept_search, row_of, search_lyrics
from caracole.overrides import load_overrides, override_key, set_lyrics_record
from caracole.songs import get_song, update_song

NOW = datetime(2026, 11, 25, 13, 0, tzinfo=UTC)
SONG = ("Nick Cani", "Vikingos veganos (Video Oficial)")
NAME = ("Nick Cani", "Vikingos veganos")
SYNCED = "[00:24.80]Somos vikingos de prueba\n[00:30.10]comemos lechuga de prueba"


def lrc(lrclib_id=77, *, track="Vikingos veganos", artist="Nick Cani", album="Pruebas", duration=200.0,
        synced=SYNCED, plain="Somos vikingos de prueba\ncomemos lechuga de prueba", instrumental=False) -> dict:
    return {"id": lrclib_id, "name": track, "trackName": track, "artistName": artist, "albumName": album,
            "duration": duration, "instrumental": instrumental, "plainLyrics": plain, "syncedLyrics": synced}


class Lrclib:
    """``/api/search`` answers ``search``, ``/api/get`` ``got`` (its 404 for None); ``status`` answers every request
    with it. Every request kept, with its parameters."""

    def __init__(self, search=(), got=None, status=None):
        self.search, self.got, self.status = list(search), got, status
        self.failing: dict[str, int] = {}  # an endpoint ("search", "get") and the status it answers
        self.requests: list[tuple[str, dict]] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        endpoint = request.url.path.removeprefix("/api/")
        self.requests.append((endpoint, dict(request.url.params)))
        status = self.failing.get(endpoint, self.status)
        if status is not None:
            return httpx.Response(status, text="Bad Gateway")
        if endpoint == "search":
            return httpx.Response(200, json=self.search)
        if endpoint == "get":
            return httpx.Response(200, json=self.got) if self.got else httpx.Response(404, json={"name": "NotFound"})
        raise AssertionError(f"unexpected request: {request.url}")


class Sites:
    def __init__(self):
        self.lrclib = Lrclib()
        self.megalobiz = FakeMegalobiz()
        self.azlyrics = FakeAzLyrics({})
        self.made: list[str] = []

    def requests(self) -> int:
        return len(self.lrclib.requests) + len(self.megalobiz.requests) + len(self.azlyrics.requests)


@pytest.fixture
def sites(monkeypatch):
    s = Sites()

    def transport(provider):
        handlers = {"lrclib": lambda r: s.lrclib.handler(r), "megalobiz": lambda r: s.megalobiz.handler(r),
                    "azlyrics": lambda r: s.azlyrics.handler(r)}
        if provider not in handlers:
            pytest.fail(f"a client for {provider} was made")
        s.made.append(provider)
        return httpx.MockTransport(handlers[provider])

    monkeypatch.setattr(_common, "transport_for", transport)
    monkeypatch.setattr(_common, "sleep", lambda seconds: None)
    return s


@pytest.fixture
def song(cfg, conn):
    cfg.library_dir.mkdir(parents=True, exist_ok=True)
    s = add_song(conn, *SONG, duration_ms=200000)
    update_song(conn, s.id, lyrics_status="missing", lyrics_at="2026-11-20T00:00:00Z")
    return get_song(conn, s.id)


def search(cfg, conn, song, name=NAME, now=NOW):
    return search_lyrics(cfg, conn, get_song(conn, song.id), name, now=now)


def off(cfg, *sites):
    """``cfg`` with ``sites`` turned off, as ``enabled = false`` in caracole.toml turns them off."""
    return replace(cfg, providers={**cfg.providers,
                                   **{site: replace(cfg.provider(site), enabled=False) for site in sites}})


def age_the_cache(cfg, by: timedelta) -> None:
    """Every answer the HTTP cache holds made ``by`` older, as if it had been fetched then."""
    for meta in (cfg.cache_dir / "http").rglob("*"):
        if meta.is_file():
            try:
                data = json.loads(meta.read_text(encoding="utf-8"))
            except (ValueError, UnicodeDecodeError):
                continue
            if isinstance(data, dict) and "fetched_at" in data:
                when = datetime.strptime(data["fetched_at"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC) - by
                data["fetched_at"] = when.strftime("%Y-%m-%dT%H:%M:%SZ")
                meta.write_text(json.dumps(data), encoding="utf-8")


def records(found) -> list[str]:
    return [row.record for row in found.rows]


# --- the name ----------------------------------------------------------------------------------------------------


def test_the_name_is_noted_under_lyrics_before_any_site_is_asked(cfg, conn, song, sites):
    seen: list[tuple[str, str] | None] = []
    asked = sites.lrclib.handler

    def handler(request):
        pick = load_overrides(cfg.overrides_file).lyrics.get(override_key(" - ".join(SONG)))
        seen.append(pick.asked if pick else None)
        return asked(request)

    sites.lrclib.handler = handler
    search(cfg, conn, song)
    assert seen and set(seen) == {NAME}
    [pick] = load_overrides(cfg.overrides_file).lyrics.values()
    assert pick.asked == NAME and pick.record is None


def test_the_songs_own_name_takes_as_out_and_keeps_the_record(cfg, conn, song, sites):
    set_lyrics_record(cfg.overrides_file, " - ".join(SONG), "lrclib:5")
    search(cfg, conn, song, NAME)
    [pick] = load_overrides(cfg.overrides_file).lyrics.values()
    assert pick.asked == NAME
    search(cfg, conn, song, SONG)  # the song's own name: no name kept, the record you picked stays
    [pick] = load_overrides(cfg.overrides_file).lyrics.values()
    assert pick.asked is None and pick.record.text == "lrclib:5"


def test_a_song_not_in_the_book_or_ignored_is_refused(tmp_path, monkeypatch, sites):
    from test_commands_lyrics import run

    (tmp_path / "lib").mkdir()
    (tmp_path / "state").mkdir()
    result = run(tmp_path, "lyrics", "--song=Nobody - Nothing", "--as=Somebody - Something")
    assert result.exit_code == 1 and "No song" in result.output
    (tmp_path / "lib" / "overrides.toml").write_text('[ignore]\nsongs = ["Nick Cani - Vikingos veganos"]\n',
                                                     encoding="utf-8")
    conn = db.connect(tmp_path / "state" / "caracole.sqlite")
    try:
        add_song(conn, *NAME)
    finally:
        conn.close()
    result = run(tmp_path, "lyrics", "--song=Nick Cani - Vikingos veganos", "--as=Nick Cani - Vikingos")
    assert result.exit_code == 1 and "ignored" in result.output
    assert sites.requests() == 0
    assert "[lyrics]" not in (tmp_path / "lib" / "overrides.toml").read_text(encoding="utf-8")


# --- what each site is asked, and what becomes rows -------------------------------------------------------------


def test_lrclibs_search_is_one_request_and_each_record_with_lyrics_a_row(cfg, conn, song, sites):
    sites.lrclib.search = [lrc(77), lrc(78, track="Vikingos veganos (Live)", album="En vivo", duration=271.0,
                                      synced=None)]
    found = search(cfg, conn, song)
    assert sites.lrclib.requests == [("search", {"track_name": "Vikingos veganos", "artist_name": "Nick Cani"})]
    assert records(found)[:2] == ["lrclib:77", "lrclib:78"]
    first, live = found.rows[:2]
    assert (first.site, first.artist, first.title, first.album, first.duration, first.timed) == (
        "lrclib", "Nick Cani", "Vikingos veganos", "Pruebas", 200.0, True)
    assert (live.title, live.album, live.duration, live.timed, live.fits) == (
        "Vikingos veganos (Live)", "En vivo", 271.0, False, True)  # the same names, 71 s off: fits' last band
    assert found.lrclib == {"track_name": "Vikingos veganos", "artist_name": "Nick Cani"}
    assert found.said["lrclib"] == "listed 2"


def test_lrclibs_get_is_asked_only_when_no_record_of_the_search_fits(cfg, conn, song, sites):
    sites.lrclib.search = [lrc(77)]
    search(cfg, conn, song)
    assert [e for e, _ in sites.lrclib.requests] == ["search"]
    sites.lrclib.requests.clear()
    sites.lrclib.search = [lrc(90, track="Otra canción", artist="Otro")]
    sites.lrclib.got = lrc(77)
    found = search(cfg, conn, song, ("Nick Cani", "Vikingos"))
    assert sites.lrclib.requests[1] == ("get", {"artist_name": "Nick Cani", "track_name": "Vikingos",
                                                "duration": "200"})
    assert records(found)[0] == "lrclib:77" and found.rows[0].best


def test_instrumental_records_are_counted_never_listed(cfg, conn, song, sites):
    sites.lrclib.search = [lrc(77), lrc(5, instrumental=True, plain=None, synced=None),
                           lrc(6, plain="", synced="")]
    found = search(cfg, conn, song)
    assert "lrclib:5" not in records(found) and "lrclib:6" not in records(found)
    assert found.instrumental == 2


def test_megalobizs_results_are_rows_with_no_lyrics_asked(cfg, conn, song, sites):
    sites.megalobiz.records = [mz_record(lrc_id=24519, title="Vikingos veganos", artist="Nick Cani", duration=201.0),
                               mz_record(lrc_id=31, title="Vikingos veganos", artist="", duration=200.0)]
    found = search(cfg, conn, song)
    assert sites.megalobiz.endpoints() == ["search"]
    assert sites.megalobiz.requests[0][1] == {"title": "Vikingos veganos", "artist": "Nick Cani", "duration": "200",
                                              "limit": "10"}
    rows = {row.record: row for row in found.rows}
    assert rows["megalobiz:24519"].timed and rows["megalobiz:24519"].fits and rows["megalobiz:24519"].best
    assert rows["megalobiz:31"].artist == "" and not rows["megalobiz:31"].fits  # a fan's upload: never the best
    assert found.said["megalobiz"] == "listed 2"


def test_azlyrics_lists_the_songs_of_the_typed_artist_whose_title_fits(cfg, conn, song, sites):
    sites.azlyrics.pages = {"/p/pomme.html": artist_page()}
    found = search(cfg, conn, song, ("Pomme", "Je t'emmènerai bien"))
    assert sites.azlyrics.requests == ["/p/pomme.html"]  # its artist page alone: no lyrics page, never its search
    assert records(found) == ["azlyrics:pomme/jetemmeneraibien"]
    [row] = found.rows
    assert (row.site, row.artist, row.title, row.timed, row.fits, row.best) == (
        "azlyrics", "Pomme", "Je T'emmènerai Bien", False, True, True)


def test_a_name_with_no_latin_letter_asks_azlyrics_nothing(cfg, conn, song, sites):
    found = search(cfg, conn, song, ("孟维来", "野人"))
    assert sites.azlyrics.requests == [] and "azlyrics" not in sites.made
    assert found.said["azlyrics"] == "no artist page for 孟维来"


def test_an_id_of_another_shape_is_never_a_row(cfg, conn, song, sites):
    sites.lrclib.search = [lrc(77), lrc("78"), lrc(0), lrc(10**13), lrc(True)]
    found = search(cfg, conn, song)
    assert [r for r in records(found) if r.startswith("lrclib:")] == ["lrclib:77"]


# --- the best fit, the order -------------------------------------------------------------------------------------


def test_the_best_fit_is_the_record_todays_rules_keep_and_comes_first(cfg, conn, song, sites):
    sites.megalobiz.records = [mz_record(lrc_id=24519, title="Vikingos veganos", artist="Nick Cani", duration=200.0)]
    sites.lrclib.search = [lrc(78, duration=230.0, synced=None), lrc(77)]
    found = search(cfg, conn, song)
    assert records(found)[0] == "lrclib:77" and [r.record for r in found.rows if r.best] == ["lrclib:77"]


def test_without_lrclibs_the_best_fit_is_megalobizs_then_azlyrics(cfg, conn, song, sites):
    sites.megalobiz.records = [mz_record(lrc_id=40, title="Vikingos veganos (karaoke)", artist="Nick Cani"),
                               mz_record(lrc_id=41, title="Vikingos veganos", artist="Nick Cani", duration=200.0)]
    found = search(cfg, conn, song)
    assert records(found)[0] == "megalobiz:41" and [r.record for r in found.rows if r.best] == ["megalobiz:41"]
    sites.azlyrics.pages = {"/p/pomme.html": artist_page()}
    found = search(cfg, conn, song, ("Pomme", "mononoke"))
    assert records(found) == ["azlyrics:pomme/mononoke"] and found.rows[0].best


def test_rows_that_fit_come_before_those_that_dont(cfg, conn, song, sites):
    sites.lrclib.search = [lrc(70, track="Otra", artist="Otro"), lrc(77), lrc(71, track="Otra más", artist="Otro")]
    sites.megalobiz.records = [mz_record(lrc_id=40, title="Vikingos veganos (karaoke)", artist="Nick Cani"),
                               mz_record(lrc_id=41, title="Vikingos veganos", artist="Nick Cani", duration=200.0)]
    found = search(cfg, conn, song)
    assert records(found) == ["lrclib:77", "megalobiz:41", "lrclib:70", "lrclib:71", "megalobiz:40"]
    assert [row.fits for row in found.rows] == [True, True, False, False, False]


def test_at_most_most_rows_are_listed(cfg, conn, song, sites):
    sites.lrclib.search = [lrc(100 + i, track=f"Otra {i}", artist="Otro") for i in range(MOST_ROWS + 5)]
    assert len(search(cfg, conn, song).rows) == MOST_ROWS


# --- what is kept ------------------------------------------------------------------------------------------------


def test_the_search_is_kept_in_kv_and_replaced_by_the_next(cfg, conn, song, sites):
    sites.lrclib.search = [lrc(77), lrc(5, instrumental=True, plain=None, synced=None)]
    search(cfg, conn, song)
    kept = db.kv_get_json(conn, f"{KV}{song.id}")
    assert kept["at"] == "2026-11-25T13:00:00Z" and kept["as"] == list(NAME) and kept["length"] == 200.0
    assert kept["lrclib"] == {"track_name": "Vikingos veganos", "artist_name": "Nick Cani"}
    assert kept["rows"][0] == {"record": "lrclib:77", "site": "lrclib", "artist": "Nick Cani",
                               "title": "Vikingos veganos", "album": "Pruebas", "duration": 200.0, "timed": True,
                               "best": True, "fits": True}
    assert kept["said"] == {"lrclib": "listed 1", "megalobiz": "nothing listed",
                            "azlyrics": "no artist page for Nick Cani"}
    assert kept["instrumental"] == 1
    back = kept_search(conn, song.id, NOW + timedelta(days=1))
    assert row_of(back, "lrclib:77").title == "Vikingos veganos" and row_of(back, "lrclib:78") is None
    sites.lrclib.search = [lrc(78, track="Vikingos")]
    search(cfg, conn, song, ("Nick Cani", "Vikingos"), now=NOW + timedelta(hours=1))
    back = kept_search(conn, song.id, NOW + timedelta(hours=1))
    assert row_of(back, "lrclib:77") is None and row_of(back, "lrclib:78") is not None
    assert kept_search(conn, song.id, NOW + timedelta(hours=1) + PICKABLE_FOR + timedelta(seconds=1)) is None


def test_a_kept_row_of_another_shape_is_never_given(cfg, conn, song, sites):
    db.kv_set_json(conn, f"{KV}{song.id}", {
        "at": "2026-11-25T13:00:00Z", "as": list(NAME), "length": None, "lrclib": {}, "instrumental": 0, "said": {},
        "state": {"lrclib": "rows", "megalobiz": "none", "azlyrics": "none"},
        "rows": [{"record": "azlyrics:../x", "site": "azlyrics", "artist": "", "title": "", "album": "",
                  "duration": None, "timed": False, "best": False, "fits": False},
                 {"record": "megalobiz:8", "site": "lrclib", "artist": "", "title": "", "album": "",
                  "duration": None, "timed": False, "best": False, "fits": False}]})
    back = kept_search(conn, song.id, NOW)
    assert back.rows == () and row_of(back, "azlyrics:../x") is None


def test_a_kept_search_without_each_sites_state_is_none_to_pick_from(cfg, conn, song, sites):
    search(cfg, conn, song)
    kept = db.kv_get_json(conn, f"{KV}{song.id}")
    assert kept["state"] == {"lrclib": "none", "megalobiz": "none", "azlyrics": "none"}
    del kept["state"]
    db.kv_set_json(conn, f"{KV}{song.id}", kept)
    assert kept_search(conn, song.id, NOW) is None


def test_each_sites_state_is_kept_and_a_kept_searchs_last_line_is_the_one_it_printed(cfg, conn, song, sites):
    from caracole.lyrics_search import last_line

    sites.lrclib.failing = {"search": 502}
    sites.megalobiz.records = [mz_record(lrc_id=24519, title="Vikingos veganos", artist="Nick Cani")]
    found = search_lyrics(off(cfg, "azlyrics"), conn, get_song(conn, song.id), NAME, now=NOW)
    assert found.state == {"lrclib": "failed", "megalobiz": "rows", "azlyrics": "off"}
    back = kept_search(conn, song.id, NOW)
    assert back.state == found.state and last_line(back) == last_line(found)
    sites.lrclib.failing = {}
    sites.megalobiz.records = []
    found = search(cfg, conn, song, ("Nick Cani", "Otra"))
    assert last_line(kept_search(conn, song.id, NOW)) == last_line(found)
    assert last_line(found).startswith("Nothing found: ")


def test_a_search_changes_no_lyrics(cfg, conn, song, sites):
    sites.lrclib.search = [lrc(77)]
    sites.megalobiz.records = [mz_record(lrc_id=24519, title="Vikingos veganos", artist="Nick Cani")]
    before = get_song(conn, song.id)
    search(cfg, conn, song)
    after = get_song(conn, song.id)
    assert (after.lyrics_status, after.lyrics_json, after.lyrics_at) == (
        before.lyrics_status, before.lyrics_json, before.lyrics_at)
    assert not any(path.name.startswith("lyrics") for path in cfg.library_dir.rglob("*"))
    assert [e for e, _ in sites.megalobiz.requests] == ["search"]  # no record read to list it
    assert load_overrides(cfg.overrides_file).lyrics[override_key(" - ".join(SONG))].record is None


# --- errors are never misses -------------------------------------------------------------------------------------


def test_one_site_failing_lists_the_others_and_says_it(cfg, conn, song, sites):
    from caracole.lyrics_search import last_line

    sites.lrclib.status = 502
    sites.megalobiz.records = [mz_record(lrc_id=24519, title="Vikingos veganos", artist="Nick Cani")]
    found = search(cfg, conn, song)
    assert records(found) == ["megalobiz:24519"]
    assert found.said["lrclib"].startswith("LRCLIB failed (")
    assert get_state(conn, "lrclib").last_error
    assert last_line(found) == "Searched: Megalobiz lists 1 record for “Nick Cani - Vikingos veganos”."


def test_no_rows_and_a_failure_is_not_searched_never_nothing_found(cfg, conn, song, sites):
    from caracole.lyrics_search import last_line

    sites.lrclib.status = 502
    found = search(cfg, conn, song)
    assert found.rows == ()
    assert last_line(found).startswith("Not searched: LRCLIB failed (")
    assert last_line(found).endswith("; try again later.")
    assert get_song(conn, song.id).lyrics_status == "missing"


def test_a_block_cools_the_site_down_with_no_alert_and_a_cooling_site_isnt_asked(cfg, conn, song, sites):
    from caracole.lyrics_search import last_line

    sites.megalobiz.failing = {"search": 429}
    found = search(cfg, conn, song)
    assert is_cooling(conn, "megalobiz", NOW)
    assert found.said["megalobiz"].startswith("Megalobiz turned us back; no asks until ")
    asked = len(sites.megalobiz.requests)
    found = search(cfg, conn, song)
    assert len(sites.megalobiz.requests) == asked  # waited out: not asked
    assert found.said["megalobiz"].startswith("waiting out Megalobiz until ")
    assert last_line(found).startswith("Not searched: waiting out Megalobiz until ")


def test_every_site_answering_none_is_nothing_found_and_the_name_is_kept(cfg, conn, song, sites):
    from caracole.lyrics_search import last_line

    found = search(cfg, conn, song)
    assert found.rows == ()
    assert last_line(found) == ("Nothing found: LRCLIB, Megalobiz and AZLyrics list nothing for "
                                "“Nick Cani - Vikingos veganos”.")
    [pick] = load_overrides(cfg.overrides_file).lyrics.values()
    assert pick.asked == NAME


# --- politeness --------------------------------------------------------------------------------------------------


def test_a_search_sends_two_to_four_requests_at_a_lookups_pace(cfg, conn, song, sites):
    sites.azlyrics.pages = {"/n/nickcani.html": artist_page().replace("Pomme Lyrics", "Nick Cani Lyrics")}
    sites.lrclib.search = [lrc(90, track="Otra", artist="Otro")]  # none fits: /api/get too
    search(cfg, conn, song)
    assert sites.requests() == 4
    runs = {run for (run,) in conn.execute("SELECT DISTINCT run FROM events")}
    assert runs and all(run.startswith(_common.LOOKUP_RUN) for run in runs)


def test_the_same_name_again_within_a_kept_searchs_life_asks_nothing(cfg, conn, song, sites):
    sites.azlyrics.pages = {"/n/nickcani.html": artist_page().replace("Pomme Lyrics", "Nick Cani Lyrics")}
    sites.lrclib.search = [lrc(90, track="Otra", artist="Otro")]
    first = search(cfg, conn, song)
    asked = sites.requests()
    assert asked == 4
    age_the_cache(cfg, PICKABLE_FOR - timedelta(hours=1))
    again = search(cfg, conn, song)
    assert sites.requests() == asked and records(again) == records(first)  # the cache's answers, a 404 too


def test_the_same_name_after_a_kept_searchs_life_asks_again_and_lists_what_came_since(cfg, conn, song, sites):
    sites.azlyrics.pages = {"/n/nickcani.html": artist_page().replace("Pomme Lyrics", "Nick Cani Lyrics")}
    sites.lrclib.search = [lrc(90, track="Otra", artist="Otro")]  # none fits, and /api/get's 404
    search(cfg, conn, song)
    asked = sites.requests()
    age_the_cache(cfg, PICKABLE_FOR + timedelta(hours=1))
    sites.lrclib.search = [lrc(90, track="Otra", artist="Otro"), lrc(77)]  # added since
    sites.megalobiz.records = [mz_record(lrc_id=24519, title="Vikingos veganos", artist="Nick Cani")]
    found = search(cfg, conn, song)
    assert sites.requests() - asked == 3  # past the cache: LRCLIB's search (fits now: no get), Megalobiz, AZLyrics
    assert records(found)[:2] == ["lrclib:77", "megalobiz:24519"]


def test_a_spent_hour_is_said_and_asks_nothing(cfg, conn, song, sites):
    now = _common.utcnow()  # the hour is the clock's, as every lookup's
    conn.executemany("INSERT INTO events (run, at, provider, url, status, decision) VALUES (?, ?, ?, ?, ?, ?)",
                     [(_common.lookup_run_id(now), now.strftime("%Y-%m-%dT%H:%M:%SZ"), "lrclib", f"u{i}", 200, "ok")
                      for i in range(cfg.provider("lrclib").lookup_per_hour)])
    found = search(cfg, conn, song)
    assert sites.lrclib.requests == []
    assert found.said["lrclib"] == f"no more asks of LRCLIB this hour ({cfg.provider('lrclib').lookup_per_hour} spent)"


def test_lookups_go_first_in_the_searchs_pauses(cfg, conn, song, sites, monkeypatch):
    turns: list[str] = []

    def turn(cfg_, conn_=None) -> bool:
        turns.append(sites.lrclib.requests[-1][0] if sites.lrclib.requests else "")
        return False

    monkeypatch.setattr(_common, "pass_turn", turn)
    sites.lrclib.search = [lrc(90, track="Otra", artist="Otro")]  # LRCLIB's search, then its get
    with _common.exclusive(cfg, "lyrics --as", lane=True):
        search(cfg, conn, song)
    assert turns == ["search"]  # before LRCLIB's second request: each client's first goes at once


def test_a_block_cools_the_site_down_once_and_sends_no_alert(cfg, conn, song, sites, monkeypatch):
    from caracole import notify

    alerts: list[tuple] = []
    monkeypatch.setattr(_common, "alert_block", lambda *args, **kwargs: alerts.append(args))
    monkeypatch.setattr(notify.Notifier, "send", lambda self, *args, **kwargs: alerts.append(args) or True)
    sites.lrclib.status = 403
    found = search(cfg, conn, song)
    assert found.state["lrclib"] == "blocked" and alerts == []
    state = get_state(conn, "lrclib")
    assert state.strikes == 1 and is_cooling(conn, "lrclib", NOW)
    assert [e for e, _ in sites.lrclib.requests] == ["search"]  # nothing more sent once it turned us back


# --- a site turned off is not asked, and never a wait ------------------------------------------------------------


def test_a_site_off_and_the_others_answering_none_is_nothing_found(cfg, conn, song, sites):
    from caracole.lyrics_search import last_line

    found = search_lyrics(off(cfg, "megalobiz"), conn, get_song(conn, song.id), NAME, now=NOW)
    assert sites.megalobiz.requests == [] and found.said["megalobiz"] == "Megalobiz is off (caracole.toml)"
    assert last_line(found) == "Nothing found: LRCLIB and AZLyrics list nothing for “Nick Cani - Vikingos veganos”."


def test_a_site_off_and_one_erring_is_not_searched_naming_the_one_that_erred(cfg, conn, song, sites):
    from caracole.lyrics_search import last_line

    sites.lrclib.status = 502
    found = search_lyrics(off(cfg, "megalobiz"), conn, get_song(conn, song.id), NAME, now=NOW)
    line = last_line(found)
    assert line.startswith("Not searched: LRCLIB failed (") and line.endswith("; try again later.")
    assert "Megalobiz" not in line


def test_every_site_off_asks_nothing_and_says_so(cfg, conn, song, sites):
    from caracole.lyrics_search import last_line

    found = search_lyrics(off(cfg, "lrclib", "megalobiz", "azlyrics"), conn, get_song(conn, song.id), NAME, now=NOW)
    assert sites.requests() == 0 and sites.made == []
    assert last_line(found) == "Not searched: every lyrics site is off (caracole.toml); nothing asked."


# --- LRCLIB's exact-name ask, after its search answered ----------------------------------------------------------


@pytest.mark.parametrize("failing,state,said", [
    (502, "rows", "listed 1; its ask by the exact name not made: LRCLIB failed ("),
    (403, "rows", "listed 1; its ask by the exact name not made: LRCLIB turned us back; no asks until "),
], ids=["an error", "a block"])
def test_lrclibs_search_rows_stay_when_its_get_fails(cfg, conn, song, sites, failing, state, said):
    sites.lrclib.search = [lrc(90, track="Otra", artist="Otro")]
    sites.lrclib.failing = {"get": failing}
    found = search(cfg, conn, song)
    assert records(found)[:1] == ["lrclib:90"]
    assert found.state["lrclib"] == state and found.said["lrclib"].startswith(said)


def test_lrclibs_get_cut_by_the_searchs_budget_keeps_its_rows_and_says_so(cfg, conn, song, sites):
    cfg = replace(cfg, providers={**cfg.providers, "lrclib": replace(cfg.provider("lrclib"), lookup_requests=1)})
    sites.lrclib.search = [lrc(90, track="Otra", artist="Otro")]
    found = search_lyrics(cfg, conn, get_song(conn, song.id), NAME, now=NOW)
    assert records(found)[:1] == ["lrclib:90"] and [e for e, _ in sites.lrclib.requests] == ["search"]
    assert found.said["lrclib"] == ("listed 1; its ask by the exact name not made: this search's 1 asks of LRCLIB are "
                                    "spent")


def test_with_no_rows_a_get_that_fails_is_not_searched(cfg, conn, song, sites):
    from caracole.lyrics_search import last_line

    sites.lrclib.failing = {"get": 502}
    found = search(cfg, conn, song)
    assert found.state["lrclib"] == "failed"
    assert last_line(found).startswith("Not searched: nothing listed; its ask by the exact name not made: LRCLIB failed")
