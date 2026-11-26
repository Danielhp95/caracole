"""caracole/web/lyrics_routes.py: a song's lyrics searched under a name you type, the kept search read, a row of it
picked and a pick taken back, from the library page.

The routes queue ``caracole lyrics --song --as`` (a search), ``--record --progress`` (a pick) and ``--clear``
(lyrics_search.py, lyrics_pick.py, tested in test_lyrics_search.py and test_lyrics_pick.py); here the queue records
the commands, and nothing runs. A kept search is written into kv as the search writes it.
"""

import json
from datetime import UTC, datetime, timedelta
from urllib.parse import urlencode

import pytest
from conftest import add_song

from caracole import stamps
from caracole.db import kv_set_json
from caracole.lyrics_search import KV, Row, Search, last_line
from caracole.overrides import set_lyrics_name, set_lyrics_record
from caracole.songs import update_song
from caracole.web.app import Request, WebApp
from caracole.web.jobs import (
    LANE,
    LYRICS_CLEAR,
    LYRICS_PICK,
    LYRICS_SEARCH,
    JobQueue,
    lyrics_clear_steps,
    lyrics_pick_steps,
    lyrics_search_steps,
    song_key_of,
)

HOST = "localhost:8737"
ALLOWED = frozenset({"localhost", "127.0.0.1", "::1"})
YEREN = ("孟维来", "野人")


class Recorder:
    def __init__(self):
        self.calls = []

    def __call__(self, args, emit):
        self.calls.append(list(args))
        return 0


@pytest.fixture
def queue():
    return JobQueue(Recorder(), limit=3, lane=LANE)


def app_for(cfg, queue):
    return WebApp(cfg, queue, allowed=ALLOWED, csrf="tok")


def post(app, path, fields, *, csrf="tok", **headers):
    sent = {"host": HOST, "content-type": "application/x-www-form-urlencoded", "sec-fetch-site": "same-origin",
            "origin": f"http://{HOST}", "accept": "application/json"} | headers
    form = ({"csrf": csrf} if csrf is not None else {}) | fields
    return app.handle(Request("POST", path, {k: v for k, v in sent.items() if v is not None},
                              urlencode(form).encode("utf-8")))


def get(app, target, **headers):
    sent = {"host": HOST, "accept": "application/json", "sec-fetch-site": "same-origin"} | headers
    return app.handle(Request("GET", target, {k: v for k, v in sent.items() if v is not None}))


def answer(response):
    return json.loads(response.body)


def song_of(conn, artist="孟维来", title="野人 (官方MV)", **kw):
    return add_song(conn, artist, title, **kw)


def rows():
    return (Row("lrclib:28399373", "lrclib", *YEREN, "野人", 226.0, True, best=True, fits=True),
            Row("megalobiz:8", "megalobiz", "", "野人", "", 231.0, True),
            Row("azlyrics:mengweilai/yeren", "azlyrics", *YEREN, "", None, False, fits=True))


def keep_search(conn, song, *, at=None, asked=YEREN, kept=None):
    """The song's search kept as ``caracole lyrics --as`` keeps it, made at ``at`` (now by default)."""
    when = at or datetime.now(UTC)
    search = Search(at=stamps.stamp(when), asked=asked, length=225.0, lrclib={"q": "孟维来 野人"},
                    rows=rows() if kept is None else kept,
                    said={"lrclib": "2 records", "megalobiz": "1 result", "azlyrics": "1 song"},
                    state={"lrclib": "rows", "megalobiz": "rows", "azlyrics": "rows"}, instrumental=2)
    kv_set_json(conn, f"{KV}{song.id}", search.as_json())
    return search


# --- POST /lyrics/search ----------------------------------------------------------------------------------------


def test_post_lyrics_search_queues_the_search_and_answers_its_job(cfg, conn, queue):
    song = song_of(conn)
    response = post(app_for(cfg, queue), "/lyrics/search",
                    {"song": str(song.id), "identity": song.key, "artist": "孟维来", "title": "野人"})
    assert response.status == 202, response.body
    [job] = queue.snapshot()
    assert answer(response) == {"job": job.id, "url": f"/api/jobs/{job.id}", "as": {"artist": "孟维来", "title": "野人"}}
    assert job.song_key == LYRICS_SEARCH + song.key and job.lane and not job.stages
    assert job.display == song.display and job.title == "Lyrics under “孟维来 - 野人”"
    assert [(s.label, s.args) for s in job.steps] == lyrics_search_steps(song.display, "孟维来 - 野人")
    # Without the page's script, a form: its request in the Requests tab.
    form = post(app_for(cfg, queue), "/lyrics/search", {"song": str(song.id), "artist": "孟维来", "title": "野人"},
                accept="text/html")
    assert form.status == 303 and dict(form.headers)["Location"] == f"/#tab=requests&job={job.id}"


def test_the_name_asked_is_the_one_the_command_reads_from_the_two_fields(cfg, conn, queue):
    # The fields are joined into --as "A - T", which the command reads back through song_names.read_names and cleans
    # (its video tag dropped): the answer, the job's label and its --as are that name, never the fields as typed.
    song = add_song(conn, "Nick Cani", "Vikingos veganos (Video Oficial)")
    response = post(app_for(cfg, queue), "/lyrics/search", {"song": str(song.id), "identity": song.key,
                                                            "artist": " Nick  Cani ",
                                                            "title": "Vikingos veganos (Video Oficial)"})
    assert answer(response)["as"] == {"artist": "Nick Cani", "title": "Vikingos veganos"}
    [job] = queue.snapshot()
    assert job.steps[0].args[-1] == "--as=Nick Cani - Vikingos veganos"


def test_pressed_again_the_search_on_its_way_is_the_answer_and_another_name_is_said_not_taken(cfg, conn, queue):
    song = song_of(conn)
    app = app_for(cfg, queue)
    fields = {"song": str(song.id), "identity": song.key, "artist": "孟维来", "title": "野人"}
    first = answer(post(app, "/lyrics/search", fields))
    again = answer(post(app, "/lyrics/search", fields))
    assert again == first and len(queue.snapshot()) == 1
    other = answer(post(app, "/lyrics/search", fields | {"title": "野人 (Live)"}))
    assert other["job"] == first["job"] and len(queue.snapshot()) == 1
    assert other["as"] == {"artist": "孟维来", "title": "野人"}  # the name on its way, never the one just typed
    assert other["said"] == ("A search under “孟维来 - 野人” is on its way: ask under “孟维来 - 野人 (Live)” once "
                             "it is over.")
    with queue._lock:
        queue._jobs[0].state = "running"
    assert answer(post(app, "/lyrics/search", fields | {"title": "野人 (Live)"}))["said"] == other["said"]


def test_a_search_on_its_way_under_a_name_that_reads_as_none_is_said_with_no_name_never_the_one_typed(cfg, conn,
                                                                                                       queue):
    song = song_of(conn)
    app = app_for(cfg, queue)
    app.submit("Lyrics under “?”", LYRICS_SEARCH + song.key, lyrics_search_steps(song.display, "\x00"),
               display=song.display)
    other = answer(post(app, "/lyrics/search", {"song": str(song.id), "identity": song.key, "artist": "孟维来",
                                                 "title": "野人"}))
    assert other["as"] is None
    assert other["said"] == "A search under “\x00” is on its way: ask under “孟维来 - 野人” once it is over."


def test_a_field_with_a_control_character_or_a_leading_dash_reaches_the_command_cleaned_as_one_argument(cfg, conn,
                                                                                                      queue):
    # A NUL or a newline typed into a field is dropped as the command drops it; a name that begins with "-" is the
    # value of --as=, one argument, never an option of the command's.
    app = app_for(cfg, queue)
    for n, (artist, title, asked) in enumerate((("Nick\x00 Cani", "Vikingos\nveganos", "Nick Cani - Vikingos veganos"),
                                                ("--help", "-Vikingos", "--help - -Vikingos"))):
        song = song_of(conn, title=f"Song {n}")
        response = post(app, "/lyrics/search", {"song": str(song.id), "identity": song.key, "artist": artist,
                                                 "title": title})
        assert response.status == 202, response.body
        [job] = [job for job in queue.snapshot() if job.song_key == LYRICS_SEARCH + song.key]
        assert job.steps[0].args == ("lyrics", f"--song={song.display}", f"--as={asked}")


def test_a_name_missing_too_long_or_with_a_dash_in_its_artist_is_refused(cfg, conn, queue):
    song = song_of(conn)
    app = app_for(cfg, queue)
    which = "Which name? An artist and a title, 1 to 200 characters each."
    for artist, title in (("", "野人"), ("孟维来", " "), ("a" * 201, "野人"), ("孟维来", "t" * 201)):
        response = post(app, "/lyrics/search", {"song": str(song.id), "artist": artist, "title": title})
        assert (response.status, answer(response)) == (400, {"error": which}), (artist, title)
    dash = post(app, "/lyrics/search", {"song": str(song.id), "artist": "Hall - Oates", "title": "Maneater"})
    assert (dash.status, answer(dash)) == (400, {"error": "An artist's name can't hold “ - ”."})
    nothing = post(app, "/lyrics/search", {"song": str(song.id), "artist": "孟维来", "title": "​"})
    assert (nothing.status, answer(nothing)) == (400, {"error": "Which name? “孟维来 - \u200b” names no artist and "
                                                                "title once cleaned."})
    assert queue.snapshot() == []


def test_a_full_lane_is_refused_with_nothing_queued(cfg, conn):
    queue = JobQueue(Recorder(), limit=1, lane=1, lane_waiting=0)
    app = app_for(cfg, queue)
    songs = [song_of(conn, title=f"Song {n}") for n in range(2)]
    assert post(app, "/lyrics/search", {"song": str(songs[0].id), "artist": "A", "title": "B"}).status == 202
    full = post(app, "/lyrics/search", {"song": str(songs[1].id), "artist": "A", "title": "B"})
    assert full.status == 503 and len(queue.snapshot()) == 1


# --- GET /api/lyrics/search -------------------------------------------------------------------------------------


def test_get_api_lyrics_search_reads_the_kept_search_and_the_lyrics_entry_with_no_request(cfg, conn, queue,
                                                                                         monkeypatch):
    import caracole.commands._common as common

    def no_client(*a, **kw):
        raise AssertionError("a read sends nothing")

    monkeypatch.setattr(common, "make_client", no_client)
    song = song_of(conn, duration_ms=225000)
    app = app_for(cfg, queue)
    empty = answer(get(app, f"/api/lyrics/search?song={song.id}"))
    assert empty == {"song": song.id, "identity": song.key, "as": None, "picked": None, "picked_why": None,
                     "length": 225.0, "search": None}
    search = keep_search(conn, song)
    set_lyrics_name(cfg.overrides_file, song.display, "孟维来 - 野人")
    set_lyrics_record(cfg.overrides_file, song.display, "lrclib:28399373")
    read = answer(get(app, f"/api/lyrics/search?song={song.id}&identity={song.key}"))
    assert read == {
        "song": song.id, "identity": song.key, "as": {"artist": "孟维来", "title": "野人"},
        "picked": "lrclib:28399373", "length": 225.0,
        # transcript.picked_without_lyrics' words: a song still pending, its record not asked yet
        "picked_why": "the record you picked isn't read yet (lrclib 28399373): tonight's run or a lookup reads it",
        # The length its rows were scored against (the audio may have changed since), and its last line's words.
        "search": {"at": search.at, "as": {"artist": "孟维来", "title": "野人"}, "length": 225.0,
                   "rows": [row.as_json() for row in rows()], "said": search.said, "state": search.state,
                   "instrumental": 2, "pickable": True,
                   "line": "Searched: LRCLIB, Megalobiz and AZLyrics list 3 records for “孟维来 - 野人”."}}
    assert read["search"]["line"] == last_line(search)
    assert queue.snapshot() == []
    update_song(conn, song.id, lyrics_status="found")
    assert answer(get(app, f"/api/lyrics/search?song={song.id}"))["picked_why"] is None


def test_a_search_over_a_week_old_is_read_unpickable_and_a_picked_record_with_no_lyrics_says_why(cfg, conn, queue):
    song = song_of(conn)
    keep_search(conn, song, at=datetime.now(UTC) - timedelta(days=8))
    set_lyrics_record(cfg.overrides_file, song.display, "megalobiz:8")
    update_song(conn, song.id, lyrics_status="missing")
    read = answer(get(app_for(cfg, queue), f"/api/lyrics/search?song={song.id}"))
    assert read["search"]["pickable"] is False and len(read["search"]["rows"]) == 3
    assert read["picked"] == "megalobiz:8"
    assert read["picked_why"] == ("the record you picked (megalobiz 8) has given no lyrics: pick another, or clear "
                                  "the pick")


def test_get_api_lyrics_search_refuses_no_song_another_songs_identity_and_no_id(cfg, conn, queue):
    song = song_of(conn)
    app = app_for(cfg, queue)
    assert get(app, f"/api/lyrics/search?song={song.id + 1}").status == 404
    assert get(app, f"/api/lyrics/search?song={song.id}&identity=other/song").status == 409
    assert get(app, "/api/lyrics/search").status == 400


def test_another_sites_fetch_of_it_is_refused(cfg, conn, queue):
    song = song_of(conn)
    keep_search(conn, song)
    response = get(app_for(cfg, queue), f"/api/lyrics/search?song={song.id}", **{"sec-fetch-site": "cross-site"})
    assert response.status == 403 and b"lrclib" not in response.body


# --- POST /lyrics/pick ------------------------------------------------------------------------------------------


def test_post_lyrics_pick_queues_a_record_of_the_kept_search(cfg, conn, queue):
    song = song_of(conn)
    keep_search(conn, song)
    app = app_for(cfg, queue)
    response = post(app, "/lyrics/pick", {"song": str(song.id), "identity": song.key, "record": "lrclib:28399373"})
    assert response.status == 200, response.body
    view = answer(response)["job"]
    assert (view["kind"], view["songId"], view["identity"]) == ("song", song.id, song.key)
    [job] = queue.snapshot()
    assert job.song_key == LYRICS_PICK + song.key and not job.lane and job.picks_lyrics
    assert job.title == f"Lyrics for {song.display}"
    assert [(s.label, s.args) for s in job.steps] == lyrics_pick_steps(song.display, "lrclib:28399373")
    # The same record again: that job.
    again = post(app, "/lyrics/pick", {"song": str(song.id), "identity": song.key, "record": "lrclib:28399373"})
    assert answer(again)["job"]["id"] == job.id and len(queue.snapshot()) == 1


def test_another_record_picked_while_a_pick_is_on_its_way_is_refused_in_words(cfg, conn, queue):
    song = song_of(conn)
    keep_search(conn, song)
    app = app_for(cfg, queue)
    post(app, "/lyrics/pick", {"song": str(song.id), "identity": song.key, "record": "lrclib:28399373"})
    for state in ("queued", "running"):
        with queue._lock:
            queue._jobs[0].state = state
        other = post(app, "/lyrics/pick", {"song": str(song.id), "identity": song.key, "record": "megalobiz:8"})
        assert (other.status, answer(other)) == (409, {"error": "A pick of this song is on its way: lrclib:28399373. "
                                                                "Pick another once it is over."})
    assert len(queue.snapshot()) == 1


def test_a_record_not_among_its_rows_or_a_stale_search_is_refused(cfg, conn, queue):
    song = song_of(conn)
    app = app_for(cfg, queue)
    words = "Search again: that record isn't among its last search's, or the search is over a week old."
    none = post(app, "/lyrics/pick", {"song": str(song.id), "record": "lrclib:28399373"})
    assert (none.status, answer(none)) == (409, {"error": words})
    keep_search(conn, song)
    for record in ("lrclib:1", "genius:1", ""):
        response = post(app, "/lyrics/pick", {"song": str(song.id), "record": record})
        assert (response.status, answer(response)) == (409, {"error": words}), record
    keep_search(conn, song, at=datetime.now(UTC) - timedelta(days=8))
    stale = post(app, "/lyrics/pick", {"song": str(song.id), "record": "lrclib:28399373"})
    assert (stale.status, answer(stale)) == (409, {"error": words})
    assert queue.snapshot() == []


def test_a_record_of_a_site_turned_off_is_refused(cfg, conn, queue):
    from dataclasses import replace

    song = song_of(conn)
    keep_search(conn, song)
    off = replace(cfg, providers={**cfg.providers, "megalobiz": replace(cfg.provider("megalobiz"), enabled=False)})
    response = post(app_for(off, queue), "/lyrics/pick", {"song": str(song.id), "record": "megalobiz:8"})
    assert (response.status, answer(response)) == (409, {"error": "Megalobiz is off (caracole.toml): nothing "
                                                                  "picked."})
    assert queue.snapshot() == []


# --- POST /lyrics/clear -----------------------------------------------------------------------------------------


def test_post_lyrics_clear_queues_the_clear_a_job_of_the_songs_with_no_stages(cfg, conn, queue):
    song = song_of(conn)
    set_lyrics_record(cfg.overrides_file, song.display, "lrclib:28399373")
    app = app_for(cfg, queue)
    response = post(app, "/lyrics/clear", {"song": str(song.id), "identity": song.key})
    assert response.status == 200, response.body
    view = answer(response)["job"]
    assert (view["kind"], view["songId"], view["identity"]) == ("song", song.id, song.key)
    [job] = queue.snapshot()
    assert job.song_key == LYRICS_CLEAR + song.key and song_key_of(job.song_key) == song.key
    assert not job.lane and not job.stages and job.title == f"Clear the lyrics record: {song.display}"
    assert [(s.label, s.args) for s in job.steps] == lyrics_clear_steps(song.display)
    assert answer(post(app, "/lyrics/clear", {"song": str(song.id)}))["job"]["id"] == job.id


def test_a_song_with_no_record_picked_has_nothing_to_clear(cfg, conn, queue):
    song = song_of(conn)
    set_lyrics_name(cfg.overrides_file, song.display, "孟维来 - 野人")  # a name alone: no record
    response = post(app_for(cfg, queue), "/lyrics/clear", {"song": str(song.id), "identity": song.key})
    assert (response.status, answer(response)) == (409, {"error": f"{song.display} has no lyrics record picked "
                                                                  "under [lyrics]: nothing to clear."})
    assert queue.snapshot() == []


# --- what every one of them refuses -----------------------------------------------------------------------------


FORMS = {"/lyrics/search": {"artist": "孟维来", "title": "野人"}, "/lyrics/pick": {"record": "lrclib:28399373"},
         "/lyrics/clear": {}}


def test_another_songs_identity_or_an_ignored_song_is_refused(cfg, conn, queue):
    song = song_of(conn)
    keep_search(conn, song)
    set_lyrics_record(cfg.overrides_file, song.display, "lrclib:28399373")
    app = app_for(cfg, queue)
    for path, fields in FORMS.items():
        other = post(app, path, {"song": str(song.id), "identity": "someone/else"} | fields)
        assert other.status == 409 and "another has its place" in answer(other)["error"], path
        gone = post(app, path, {"song": str(song.id + 1)} | fields)
        assert (gone.status, answer(gone)) == (404, {"error": "That song isn't in the logbook."}), path
    update_song(conn, song.id, status="ignored")
    for path, fields in FORMS.items():
        ignored = post(app, path, {"song": str(song.id), "identity": song.key} | fields)
        assert (ignored.status, answer(ignored)) == (409, {"error": f"{song.display} is ignored in overrides.toml."})
    assert queue.snapshot() == []


def test_a_get_another_sites_post_or_a_form_without_its_token_queues_nothing(cfg, conn, queue):
    song = song_of(conn)
    keep_search(conn, song)
    set_lyrics_record(cfg.overrides_file, song.display, "lrclib:28399373")
    app = app_for(cfg, queue)
    for path, fields in FORMS.items():
        assert get(app, f"{path}?song={song.id}").status == 404, path
        assert post(app, path, {"song": str(song.id)} | fields, csrf=None).status == 403, path
        assert post(app, path, {"song": str(song.id)} | fields, csrf="old").status == 403, path
        cross = post(app, path, {"song": str(song.id)} | fields, **{"sec-fetch-site": "cross-site",
                                                                    "origin": "https://evil.example"})
        assert cross.status == 403, path
    assert queue.snapshot() == []
