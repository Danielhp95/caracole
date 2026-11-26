"""lyrics_search.py: what the three lyrics sites list under a name you type, for a song whose own name finds nothing.

LRCLIB is a fake here (``/api/search`` answers ``search``, ``/api/get`` ``got``), Megalobiz and AZLyrics
tests/helpers/' fakes, each behind a real ``PoliteClient`` made by ``_common.make_client`` (``transport_for``): nothing
reaches the network. The records are real response shapes with invented words.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import httpx
import pytest
from conftest import add_song
from helpers.azlyrics_site import FakeAzLyrics, artist_page
from helpers.megalobiz_site import FakeMegalobiz
from helpers.megalobiz_site import record as mz_record

from caracole import db
from caracole.commands import _common
from caracole.health import get_state, is_cooling, record_block
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
        self.requests: list[tuple[str, dict]] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        endpoint = request.url.path.removeprefix("/api/")
        self.requests.append((endpoint, dict(request.url.params)))
        if self.status is not None:
            return httpx.Response(self.status, text="Bad Gateway")
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
        "rows": [{"record": "azlyrics:../x", "site": "azlyrics", "artist": "", "title": "", "album": "",
                  "duration": None, "timed": False, "best": False, "fits": False},
                 {"record": "megalobiz:8", "site": "lrclib", "artist": "", "title": "", "album": "",
                  "duration": None, "timed": False, "best": False, "fits": False}]})
    back = kept_search(conn, song.id, NOW)
    assert back.rows == () and row_of(back, "azlyrics:../x") is None


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
    sites.lrclib.search = [lrc(77)]
    asked = sites.requests()
    search(cfg, conn, song, ("Nick Cani", "Vikingos veganos"), now=NOW)  # asked before: the cache answers
    assert sites.requests() - asked <= 2


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


def test_a_block_sends_no_alert(cfg, conn, song, sites, monkeypatch):
    record_block(conn, "azlyrics", NOW - timedelta(days=30), "403")  # long over
    sites.lrclib.status = 403
    search(cfg, conn, song)
    assert "ntfy" not in sites.made


def test_a_removal_or_a_merge_drops_the_kept_search(cfg, conn, song, sites):
    from caracole.songs import delete_song_kv

    search(cfg, conn, song)
    assert kept_search(conn, song.id, NOW) is not None
    delete_song_kv(conn, song.id)  # what a removal and a merge delete (songs._PER_SONG_KV)
    assert kept_search(conn, song.id, NOW) is None
