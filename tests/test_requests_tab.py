"""The library page's Requests tab (web/feed.py, jobs_routes.py's ``/requests.json``, library_assets/requests.js):
under Now, the request that runs with its steps and those queued under it, each with Cancel; then the finished
ones, newest first under Today and Earlier, each with its outcome, its reason, when it ended and its next step;
every request's output folded away; and the routes that cancel a queued request and try a finished one again."""

from __future__ import annotations

import json
import time
import threading
from datetime import UTC, datetime, timedelta

import pytest
from helpers import browser
from helpers.browser import Browser, in_chromium
from helpers.targets import UNFOLD, noted, noting, small_targets

from caracole.get import MATCH_NOT_FOUND, SHEET_FROM, STAGES, progress_line
from caracole.library import song_dir
from caracole.songs import update_song
from caracole.web.app import WebApp, json_response
from caracole.web.feed import feed
from caracole.web.jobs import Job, JobQueue, Stage, Step, lookup_steps
from caracole.web.outcome import outcome
from caracole.web.pages import Pick
from caracole.web.songbooks import KEY
from caracole.web.status import SongFacts, job_line

from conftest import add_song
from test_web_app import ALLOWED, Recorder, answer, get, get_json, header, post, text
from test_web_page import FakeCaracole, serve  # noqa: F401  (serve: the fixture)

REQUESTS = "/#tab=requests"


def requests(fed: dict, group: str) -> list[dict]:
    """The requests of one of the feed's groups (Now, Today, Earlier), in order; [] for a group not there."""
    return next((g["requests"] for g in fed["groups"] if g["name"] == group), [])


def by_id(fed: dict) -> dict[int, dict]:
    return {r["id"]: r for g in fed["groups"] for r in g["requests"]}


# --- the six requests of the owner's mockup, as fake jobs -----------------------------------------------------


def today_at(hour: int, minute: int) -> datetime:
    """A time of today in the server's local time zone."""
    return datetime.now().astimezone().replace(hour=hour, minute=minute, second=0, microsecond=0)


NOW = today_at(14, 3)


def lookup(job_id: int, display: str, said: dict[str, tuple[str, str]], *, state: str = "done",
           finished: datetime | None = None) -> Job:
    artist, title = display.split(" - ", 1)
    steps = [Step(label, args, state={"queued": "waiting", "done": "done"}.get(state, state),
                  output=[] if state == "queued" else [f"get: looking up {display}"])
             for label, args in lookup_steps(artist, title)]
    every = {name: ("waiting" if state in ("queued", "running") else "done", "") for name, _ in STAGES} | said
    return Job(job_id, f"Fetch {display}", display.lower(), steps, fetching=True, display=display, state=state,
               queued_at=(finished or NOW) - timedelta(seconds=20), started_at=(finished or NOW) - timedelta(seconds=15),
               finished_at=finished, stages=[Stage(name, label, *every[name]) for name, label in STAGES])


def mockup() -> tuple[list[Job], dict, dict, dict]:
    """The mockup's requests: Muse - Hysteria running, one queued, two not found, one ready whose lyrics wait,
    a songbook deleted. Newest first, with their lines, outcomes and songs' facts, as jobs_routes.py gives them."""
    running = lookup(6, "Muse - Hysteria", {"song": ("done", ""), "match": ("done", ""), "sheet": ("done", ""),
                                            "pdf": ("running", "")}, state="running")
    running.started_at = NOW - timedelta(seconds=12)
    queued = lookup(7, "Estopa - Como Camarón", {}, state="queued")
    nyc = lookup(5, "Horse The Band - New York City", {"sheet": ("skipped", "Ultimate Guitar has no sheet to keep"),
                                                       "pdf": ("skipped", "no sheet yet")}, finished=today_at(14, 2))
    pizza = lookup(4, "Horse The Band - Crippled By Pizza", {"sheet": ("skipped", "Ultimate Guitar has no sheet to "
                                                                                  "keep"), "pdf": ("skipped", "")},
                   finished=today_at(14, 1))
    creep = lookup(3, "Radiohead - Creep", {"lyrics": (
        "failed", "LRCLIB failed (lrclib: 503: https://lrclib.net/api/get: HTTP 503); the nightly run tries again")},
        finished=today_at(13, 40))
    book = Job(2, 'Delete the songbook "test"', f"{KEY}songbook\x1fdelete\x1f--\x1ftest",
               [Step("Deleting the songbook", ("songbook", "delete", "--", "test"), state="done")], state="done",
               display='Delete the songbook "test"', queued_at=today_at(13, 12), finished_at=today_at(13, 12))
    # Both Horse The Band songs are matched, and Ultimate Guitar was asked: it has no chords for them.
    facts = {5: SongFacts(checked_now=True, asked_ug=True,
                          elsewhere=("gtptabs", "https://gtptabs.com/tabs/h/horse-the-band/new-york-city.html")),
             4: SongFacts(checked_now=True, asked_ug=True), 3: SongFacts(sheet="Radiohead/Creep/sheet.html"),
             6: SongFacts(sheet="Muse/Hysteria/sheet.html", sheet_from="UG")}  # its sheet, from Ultimate Guitar
    songs = {5: 15, 4: 14, 3: 13}
    jobs = [queued, running, nyc, pizza, creep, book]
    lines = {job.id: job_line(job, facts.get(job.id), ahead=1 if job is queued else 0) for job in jobs}
    outcomes = {job.id: outcome(job, lines[job.id], facts.get(job.id), song_id=songs.get(job.id))
                for job in jobs if not job.active}
    return jobs, lines, outcomes, facts


def mockup_feed(*, opened=()) -> dict:
    jobs, lines, outcomes, facts = mockup()
    return feed(jobs, lines, outcomes=outcomes, facts=facts, opened=opened, now=NOW)


# --- now: the running request and those queued ---------------------------------------------------------------


def test_the_running_lookup_comes_first_with_its_stages_as_steps():
    fed = mockup_feed()
    assert fed["active"] == 2
    now = requests(fed, "Now")
    assert [r["id"] for r in now] == [6, 7]  # the running one, then the queue in order
    card = now[0]
    assert (card["display"], card["state"], card["ago"]) == ("Muse - Hysteria", "running", "started 12 s ago")
    assert card["says"] == {"tone": "running", "text": "Rendering the sheet…"}
    assert [(c["name"], c["source"], c["state"]) for c in card["steps"]] == [
        ("Song", "", "done"), ("Match", "UG", "done"), ("Sheet", "UG", "done"), ("PDF", "", "running"),
        ("Lyrics", "", "waiting"), ("Extras", "", "waiting"), ("Songbooks", "", "waiting")]
    assert "actions" not in card  # the running one: never stopped halfway


def test_the_running_steps_say_a_song_ultimate_guitars_index_lacks_plainly_and_where_the_sheet_comes_from():
    estopa = lookup(8, "Estopa - Tu Calorro", {"song": ("done", "in the library"),
                                              "match": ("done", MATCH_NOT_FOUND),
                                              "sheet": ("running", SHEET_FROM["lacuerda"])}, state="running")
    [card] = requests(feed([estopa], {8: job_line(estopa, None)}, now=NOW), "Now")
    assert card["says"]["text"] == "Fetching from LaCuerda…"
    assert card["steps"][:3] == [{"name": "Song", "source": "", "state": "done"},
                                 {"name": "Match: not on UG", "source": "", "state": "plain"},
                                 {"name": "Sheet", "source": "LaCuerda", "state": "running"}]


def test_queued_requests_say_their_place_and_each_can_be_cancelled():
    jobs = [Job(n, f"Add A - {n}", f"a/{n}", [Step("Adding to the library", ("add",))], display=f"A - {n}")
            for n in (4, 3, 2, 1)]
    jobs[-1].state = "running"
    shown = by_id(feed(jobs, {}, now=NOW))
    assert [shown[n]["says"] for n in (2, 3, 4)] == [{"tone": "queued", "text": f"Queued, {place}"}
                                                     for place in ("next", "2nd", "3rd")]
    assert shown[3]["actions"] == [{"label": "Cancel", "post": "/jobs/cancel", "fields": {"job": "3"},
                                    "aria": "Cancel the request for A - 3", "primary": False}]
    assert "actions" not in shown[1]


# --- the feed: what ended, and the next step ------------------------------------------------------------------


def test_each_outcome_says_its_word_its_reason_and_its_next_step():
    fed = mockup_feed()
    today = requests(fed, "Today")
    assert [r["id"] for r in today] == [5, 4, 3, 2]  # newest first
    nyc, pizza, creep, book = today
    assert nyc["says"] == {"tone": "missing", "text": "Not found"}
    assert nyc["reason"] == "Ultimate Guitar has no chords for it; gtptabs.com's index lists a page for it."
    assert nyc["actions"] == [{"label": "Get it from there", "primary": True, "post": "/lookup",
                               "fields": {"song": "15"}}]
    assert nyc["when"]["text"] == "14:02" and nyc["when"]["stamp"].endswith("Z")
    assert pizza["actions"] == [{"label": "Request by name", "primary": False,
                                 "href": "/#q=Horse+The+Band+-+Crippled+By+Pizza"}]
    assert pizza["reason"] == "Ultimate Guitar has no chords for it."
    assert creep["says"] == {"tone": "ready", "text": "Ready"}
    assert creep["reason"] == "LRCLIB answered 503: the lyrics wait for tonight's run."
    assert creep["actions"] == [{"label": "Open", "primary": True, "href": "/Radiohead/Creep/sheet.html"}]
    assert book["says"] == {"tone": "removed", "text": "Deleted"} and "actions" not in book
    # The to-do page is no next step here.
    assert "_todo.md" not in json.dumps(fed) and "to-do page" not in json.dumps(fed)


def test_every_request_keeps_its_output_and_what_each_command_printed_once_it_is_opened():
    fed = mockup_feed()
    for request in by_id(fed).values():
        output = request["output"]
        assert output["opened"] is False and " · requested " in output["meta"]
        assert all("lines" not in step for step in output["steps"]), request["id"]
    creep = by_id(fed)[3]["output"]
    assert creep["meta"].startswith("Fetch Radiohead - Creep · requested ")
    assert {"label": "Lyrics from LRCLIB", "badge": {"tone": "failed", "text": "Failed"},
            "detail": "LRCLIB failed (lrclib: 503: https://lrclib.net/api/get: HTTP 503); the nightly run tries "
                      "again"} in creep["stages"]
    assert [s["badge"] for s in creep["steps"]] == [{"tone": "done", "text": "Done"}]
    opened = by_id(mockup_feed(opened={3}))
    assert opened[3]["output"]["opened"] is True
    assert opened[3]["output"]["steps"][0]["lines"] == ["get: looking up Radiohead - Creep"]
    assert all("lines" not in step for step in opened[5]["output"]["steps"])


def test_the_outputs_time_is_in_the_servers_time_zone_named(monkeypatch):
    monkeypatch.setenv("TZ", "EST+05")  # five hours behind UTC, a POSIX rule: no zone files
    time.tzset()
    try:
        job = Job(1, "Add A - B", "a/b", [Step("Adding to the library", ("add",), state="done")], state="done",
                  display="A - B", queued_at=datetime(2026, 10, 21, 3, 30, tzinfo=UTC),
                  finished_at=datetime(2026, 10, 21, 3, 31, tzinfo=UTC))
        fed = feed([job], {1: job_line(job, SongFacts())}, now=datetime(2026, 10, 21, 12, tzinfo=UTC))
    finally:
        monkeypatch.undo()
        time.tzset()
    assert by_id(fed)[1]["output"]["meta"] == "Add A - B · requested 2026-10-20 22:30 EST"


def test_finished_requests_are_grouped_by_the_day_they_ended_in_the_servers_time_zone():
    def done(job_id: int, when: datetime) -> Job:
        return Job(job_id, f"Add A - {job_id}", f"a/{job_id}", [Step("Adding to the library", ("add",), state="done")],
                   state="done", display=f"A - {job_id}", queued_at=when, finished_at=when)

    midnight = NOW.replace(hour=0, minute=0)
    jobs = [done(4, NOW - timedelta(minutes=1)), done(3, midnight + timedelta(minutes=1)),
            done(2, midnight - timedelta(minutes=1)), done(1, NOW - timedelta(days=3))]
    fed = feed(jobs, {job.id: job_line(job, SongFacts()) for job in jobs}, now=NOW)
    assert [g["name"] for g in fed["groups"]] == ["Today", "Earlier"] and fed["active"] == 0
    assert [r["id"] for r in requests(fed, "Today")] == [4, 3]
    assert [r["id"] for r in requests(fed, "Earlier")] == [2, 1]
    yesterday = midnight - timedelta(minutes=1)
    assert by_id(fed)[2]["when"]["text"] == f"{yesterday.day} {yesterday:%b}, 23:59"


def test_a_lookup_that_stopped_for_a_pick_says_its_sheet_waits_for_one_never_that_it_failed():
    creep = lookup(1, "Radiohead - Creep", {"sheet": ("skipped", "needs review first")}, finished=NOW)
    pick = Pick(9, "Radiohead - Creep", "Creep", "Radiohead", ({"ref": "radiohead/creep"},))
    line = job_line(creep, SongFacts(review=True, picker="review?song=9"))
    fed = feed([creep], {1: line}, outcomes={1: outcome(creep, line, SongFacts(review=True, picker="review?song=9"),
                                                        song_id=9)},
               picks={creep.song_key: pick}, now=NOW)
    shown = by_id(fed)[1]
    assert shown["says"] == {"tone": "review", "text": "Needs review"}
    assert shown["actions"] == [{"label": "Pick the match", "primary": True, "href": "/review?song=9"}]
    sheet = next(s for s in shown["output"]["stages"] if s["label"] == "The sheet")
    assert sheet["badge"] == {"tone": "review", "text": "Waits for a pick"} and "Pick the match" in sheet["note"]


def test_a_song_the_index_didnt_match_gets_what_caracole_search_finds_as_a_next_step_once():
    job = Job(1, "Add A - B", "a/b", [Step("Adding to the library", ("add",), state="done")], state="done",
              display="A - B", queued_at=NOW, finished_at=NOW)
    pick = Pick(4, "A - B", "B", "A", search=True)
    shown = by_id(feed([job], {1: job_line(job, SongFacts())}, picks={"a/b": pick}, now=NOW))[1]
    assert shown["actions"] == [{"label": "See what caracole search finds", "href": "/review?song=4",
                                 "primary": False}]


# --- the routes: the feed, Cancel, Try again -------------------------------------------------------------------


@pytest.fixture
def queue():
    return JobQueue(Recorder(), limit=5)


@pytest.fixture
def app(cfg, queue):
    return WebApp(cfg, queue, allowed=ALLOWED, csrf="tok")


def test_the_feed_answers_the_pages_own_script_alone(app, queue):
    post(app, "/request", {"artist": "Radiohead", "title": "Creep"})
    assert get(app, "/requests.json", accept="application/json").status == 403  # no form token
    assert get_json(app, "/requests.json", token="wrong").status == 403
    assert get_json(app, "/requests.json", **{"sec-fetch-site": "cross-site"}).status == 403
    fed = answer(get_json(app, "/requests.json"))
    assert fed["active"] == 1 and [r["id"] for r in requests(fed, "Now")] == [1]
    queue.run_pending()
    fed = answer(get_json(app, "/requests.json"))
    assert fed["active"] == 0 and [r["says"]["text"] for r in requests(fed, "Today")] == ["Added"]
    assert "lines" not in by_id(fed)[1]["output"]["steps"][0]
    opened = answer(get_json(app, "/requests.json?open=1,x"))
    assert by_id(opened)[1]["output"]["steps"][0]["lines"] == ["ok"]


def test_the_feed_with_nothing_queued(app):
    assert answer(get_json(app, "/requests.json")) == {"active": 0, "groups": []}


def test_the_requests_page_is_gone_into_the_library_pages_tab(app):
    # Nothing answers /jobs as a page any more: the library page's Requests tab shows the requests.
    assert get(app, "/jobs").status == 404


def test_cancel_takes_a_queued_request_out_and_never_stops_the_running_one(cfg, conn):
    answers = []

    def runner(args, emit):  # while the first request runs, the page cancels it, then the one queued after it
        if not answers:
            answers.append(post(app, "/jobs/cancel", {"job": "1"}))
            answers.append(post(app, "/jobs/cancel", {"job": "2"}))
        return 0

    queue = JobQueue(runner)
    app = WebApp(cfg, queue, allowed=ALLOWED, csrf="tok")
    post(app, "/request", {"artist": "Radiohead", "title": "Creep"})
    post(app, "/request", {"artist": "Oasis", "title": "Wonderwall"})
    # Without the form token, nothing is cancelled.
    assert post(app, "/jobs/cancel", {"job": "2"}, csrf="wrong").status == 403
    assert [j.id for j in queue.snapshot()] == [2, 1]
    queue.run_pending()
    running, cancelled = answers
    assert running.status == 409 and "never stops a command halfway" in text(running)
    assert cancelled.status == 303 and header(cancelled, "location") == REQUESTS
    assert [(j.id, j.state) for j in queue.snapshot()] == [(2, "cancelled"), (1, "done")]
    # Its wanted.txt line stays: the nightly run looks for the song.
    assert "Oasis - Wonderwall" in cfg.wanted_file.read_text(encoding="utf-8")
    assert post(app, "/jobs/cancel", {"job": "2"}).status == 404  # cancelled already
    over = post(app, "/jobs/cancel", {"job": "1"})
    assert over.status == 409 and "is over" in text(over)
    assert post(app, "/jobs/cancel", {"job": "x"}).status == 400


def test_cancel_answers_the_pages_script_as_data(app, queue):
    post(app, "/request", {"artist": "Radiohead", "title": "Creep"})
    response = post(app, "/jobs/cancel", {"job": "1"}, accept="application/json")
    assert response.status == 200 and answer(response) == {"cancelled": 1}
    assert [(job.id, job.state, job.active) for job in queue.snapshot()] == [(1, "cancelled", False)]


def test_a_cancelled_request_ends_as_cancelled_for_every_page_that_follows_it(app, queue, conn):
    # A library page open on another device follows the request cancelled here: it ends there, as Cancelled, with
    # its song's card as it is now (its Fetch now back), never a request queued for ever; and it stays in the history.
    creep = add_song(conn, "Radiohead", "Creep")
    update_song(conn, creep.id, match_decision="accept", match_artist_key="radiohead", match_song_key="creep")
    post(app, "/request", {"artist": "Oasis", "title": "Wonderwall"})  # the request before it
    post(app, "/fetch", {"song": str(creep.id)})
    assert post(app, "/jobs/cancel", {"job": "2"}).status == 303
    seen = {view["id"]: view for view in answer(get_json(app, "/jobs.json?jobs=1,2"))["jobs"]}
    assert (seen[2]["state"], seen[2]["songId"], seen[2]["line"]) == (
        "cancelled", creep.id, {"tone": "cancelled", "text": "Cancelled", "link": None, "details": None})
    assert seen[2]["card"]["id"] == creep.id and seen[2]["card"]["fetchable"] is True
    assert answer(get_json(app, "/jobs.json"))["active"] == 1
    assert queue.room() == queue._limit - 1  # it waits no more: the add alone does
    fed = answer(get_json(app, "/requests.json"))
    assert [r["id"] for r in requests(fed, "Today")] == [2]
    item = by_id(fed)[2]
    assert item["says"] == {"tone": "cancelled", "text": "Cancelled"}
    assert item["reason"] == "Taken out of the queue before it ran."
    assert "actions" not in item  # you cancelled it: the library asks again
    assert post(app, "/jobs/cancel", {"job": "2"}).status == 404  # cancelled already
    queue.run_pending()
    assert queue._runner.calls == [["add", "--", "Oasis", "Wonderwall"]]
    assert [(job.id, job.state) for job in queue.snapshot()] == [(2, "cancelled"), (1, "done")]


def test_try_again_queues_the_same_steps_and_needs_the_token(cfg, conn):
    codes = iter([1, 0])

    def runner(args, emit):
        emit("error: LRCLIB is down.")
        return next(codes)

    queue = JobQueue(runner)
    app = WebApp(cfg, queue, allowed=ALLOWED, csrf="tok")
    post(app, "/request", {"artist": "Radiohead", "title": "Creep", "fetch": "1"})
    queue.run_pending()
    [failed] = queue.snapshot()
    assert failed.state == "failed"
    item = by_id(answer(get_json(app, "/requests.json")))[1]
    assert item["actions"] == [{"label": "Try again", "primary": False, "post": "/jobs/again", "fields": {"job": "1"}}]
    assert post(app, "/jobs/again", {"job": "1"}, csrf=None).status == 403
    assert post(app, "/jobs/again", {"job": "1"}, csrf="wrong").status == 403
    assert len(queue.snapshot()) == 1
    response = post(app, "/jobs/again", {"job": "1"})
    assert response.status == 303 and header(response, "location") == REQUESTS
    again, first = queue.snapshot()
    assert again.id == 2 and again.state == "queued"
    assert [s.args for s in again.steps] == [s.args for s in first.steps]
    assert (again.title, again.song_key, again.fetching, again.display) == (
        first.title, first.song_key, first.fetching, first.display)
    # To the page's script, the job, as /jobs.json gives it: the song's line follows it.
    assert answer(post(app, "/jobs/again", {"job": "2"}, accept="application/json")).get("error")  # not over yet
    assert post(app, "/jobs/again", {"job": "2"}).status == 409
    assert post(app, "/jobs/again", {"job": "9"}).status == 404
    queue.run_pending()
    assert queue.snapshot()[0].state == "done"
    view = answer(post(app, "/jobs/again", {"job": "2"}, accept="application/json"))["job"]
    assert (view["id"], view["display"], view["line"]["text"]) == (3, "Radiohead - Creep", "Queued…")


def test_trying_a_lacuerda_artists_read_again_lets_go_of_the_searches_kept_once_it_is_read(app, queue):
    # A read asked for from a search drops the answers kept once it is over (search_routes._after_reads):
    # Try again's read does the same.
    post(app, "/lacuerda/artist", {"name": "Caifanes"})
    queue.run_pending()
    app._reads.clear()
    response = post(app, "/jobs/again", {"job": "1"})
    assert response.status == 303
    assert app._reads == {2}


def lookup_ran(cfg, conn, queue, app, artist, title, *, sheet=False, asked=False):
    """A song looked up now (Fetch it now) whose lookup left it as the test says: not found in the offline
    index, matched and asked on Ultimate Guitar (``asked``), which had no sheet, or with a sheet."""
    post(app, "/request", {"artist": artist, "title": title, "fetch": "1"})
    song = add_song(conn, artist, title)
    update_song(conn, song.id, match_decision="accept" if sheet or asked else "not_found")
    if sheet:
        folder = song_dir(cfg.library_dir, song)
        folder.mkdir(parents=True)
        (folder / "sheet.pdf").write_bytes(b"%PDF")
    queue.run_pending()
    if asked:  # its fetch settled it during the job: what it lacks, UG lacks
        started = queue.snapshot()[0].started_at
        update_song(conn, song.id, ug_checked_at=started.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"))
    return song


def test_a_song_the_offline_index_lacks_says_so_and_its_one_next_step_is_what_caracole_search_finds(
        cfg, conn, queue, app):
    pizza = lookup_ran(cfg, conn, queue, app, "Horse The Band", "Crippled By Pizza")
    item = by_id(answer(get_json(app, "/requests.json")))[1]
    # Nobody asked Ultimate Guitar: the index doesn't have it under this name, and its artist's page isn't known.
    assert item["reason"] == "Not in the offline Ultimate Guitar index under this name."
    assert item["actions"] == [{"label": "See what caracole search finds", "primary": True,
                                "href": f"/review?song={pizza.id}"}]
    # The library page's line for it is as it was.
    [view] = answer(get_json(app, "/jobs.json?jobs=1"))["jobs"]
    assert view["line"] == {"tone": "missing", "text": "Not found",
                            "link": {"label": "see the to-do page", "href": "_todo.md"}, "details": None}


def test_a_song_not_found_requests_it_by_name_or_gets_it_where_the_indexes_have_it(cfg, conn, queue, app):
    pizza = lookup_ran(cfg, conn, queue, app, "Horse The Band", "Crippled By Pizza", asked=True)
    item = by_id(answer(get_json(app, "/requests.json")))[1]
    assert item["reason"] == "Ultimate Guitar has no chords for it."
    assert item["actions"] == [{"label": "Request by name", "primary": False,
                                "href": "/#q=Horse+The+Band+-+Crippled+By+Pizza"}]
    [view] = answer(get_json(app, "/jobs.json?jobs=1"))["jobs"]
    assert view["line"] == {"tone": "missing", "text": "Not found",
                            "link": {"label": "see the to-do page", "href": "_todo.md"}, "details": None}
    assert view["songId"] == pizza.id
    conn.execute("INSERT INTO lacuerda_index (path, artist_slug, artist, artist_key, title, title_key, versions, "
                 "acordes, page) VALUES ('estopa/como_camaron', 'estopa', 'Estopa', 'estopa', 'Como Camarón', "
                 "'como-camaron', 'lcd', 1, 'e')")
    camaron = lookup_ran(cfg, conn, queue, app, "Estopa", "Como Camarón")
    item = by_id(answer(get_json(app, "/requests.json")))[2]
    assert item["reason"] == "Not in the offline Ultimate Guitar index under this name; LaCuerda has a sheet."
    # What caracole search finds, beside it: never a second way on.
    get_it, search = item["actions"]
    assert search == {"label": "See what caracole search finds", "primary": False, "href": f"/review?song={camaron.id}"}
    assert get_it == {"label": "Get it from there", "primary": True, "post": "/lookup",
                      "fields": {"song": str(camaron.id),
                                 "lacuerda": "https://acordes.lacuerda.net/estopa/como_camaron.shtml"}}
    # The form is the lookup a search's Get it runs; the tab posts it as the page's script, and follows its job.
    response = post(app, "/lookup", get_it["fields"], accept="application/json")
    assert response.status == 202 and answer(response)["view"]["id"] == 3
    assert queue.snapshot()[0].steps[0].args == (
        "get", "--progress", "--lacuerda=https://acordes.lacuerda.net/estopa/como_camaron.shtml", "--", "Estopa",
        "Como Camarón")


def test_a_song_ready_opens_its_sheet_and_its_line_on_the_library_page_says_ready_alone(cfg, conn, queue, app):
    lookup_ran(cfg, conn, queue, app, "Radiohead", "Creep", sheet=True)
    item = by_id(answer(get_json(app, "/requests.json")))[1]
    assert item["actions"] == [{"label": "Open", "primary": True, "href": "/Radiohead/Creep/sheet.pdf"}]
    # The song's line opens its sheet itself (its title, its Open): no link of the request's, and no steps.
    [view] = answer(get_json(app, "/jobs.json?jobs=1"))["jobs"]
    assert view["line"] == {"tone": "ready", "text": "Ready", "link": None, "details": None}
    assert view["sheet"] == "Radiohead/Creep/sheet.pdf" and "steps" not in view and "count" not in view


def kept_sheet_from(cfg, conn, song, provider: str) -> None:
    """The song's sheet kept, as a fetch from ``provider`` keeps one: its version, its text and its PDF."""
    from caracole.library import keep_file
    from caracole.versions import upsert_version

    vid = upsert_version(conn, provider=provider, tab_id="1", song_id=song.id, slot="sheet", kind="chords",
                         rating=4.5, votes=12, version=1, label=None, url="https://example.com/1", raw={}, now="x")
    keep_file(conn, cfg.library_dir, song=song, version_id=vid, name="sheet.txt", data=b"Words\n", rank=1)
    (song_dir(cfg.library_dir, song) / "sheet.pdf").write_bytes(b"%PDF-1.4")
    update_song(conn, song.id, status="found")


def test_a_lookups_progress_shows_in_the_tab_and_on_its_songs_line(cfg, conn):
    # The tab gives the running request's steps; /jobs.json gives the library page the same steps, and how many are
    # over, for the song's line.
    creep = add_song(conn, "Radiohead", "Creep")
    seen, views = [], []

    def runner(args, emit):
        emit(progress_line({"stage": "song", "state": "done", "detail": "in the library"}))
        emit(progress_line({"stage": "match", "state": "done", "detail": "matched to radiohead/creep"}))
        emit(progress_line({"stage": "sheet", "state": "running"}))
        emit(progress_line({"stage": "sheet", "state": "running", "detail": SHEET_FROM["ug"]}))
        seen.append(answer(get_json(app, "/requests.json")))
        views.append(answer(get_json(app, "/jobs.json"))["jobs"][0])
        kept_sheet_from(cfg, conn, creep, "ug")
        emit(progress_line({"stage": "sheet", "state": "done", "detail": "tab 1 from Ultimate Guitar"}))
        emit(progress_line({"stage": "pdf", "state": "done", "detail": "made"}))
        emit(progress_line({"stage": "lyrics", "state": "running"}))
        seen.append(answer(get_json(app, "/requests.json")))
        views.append(answer(get_json(app, "/jobs.json"))["jobs"][0])
        return 0

    queue = JobQueue(runner)
    app = WebApp(cfg, queue, allowed=ALLOWED, csrf="tok")
    post(app, "/request", {"artist": "Radiohead", "title": "Creep", "fetch": "1"})
    queue.run_pending()
    [card] = requests(seen[0], "Now")
    assert card["says"]["text"] == "Fetching from Ultimate Guitar…" and card["ago"].startswith("started ")
    assert card["steps"][:3] == [{"name": "Song", "source": "", "state": "done"},
                                 {"name": "Match", "source": "UG", "state": "done"},
                                 {"name": "Sheet", "source": "UG", "state": "running"}]
    asking, lyrics = views
    assert asking["line"]["text"] == "Fetching from Ultimate Guitar…" and asking["count"] == "2 of 7 done"
    assert asking["steps"] == card["steps"]
    # Once done, the sheet says where the song's sheet came from: its version's site, as the library has it.
    assert lyrics["line"]["text"] == "Fetching the lyrics from LRCLIB…" and lyrics["count"] == "4 of 7 done"
    assert lyrics["steps"][2] == {"name": "Sheet", "source": "UG", "state": "done"}
    assert requests(seen[1], "Now")[0]["steps"][2] == {"name": "Sheet", "source": "UG", "state": "done"}
    # Over, and Ready: the steps fold away from the song's line.
    [over] = answer(get_json(app, "/jobs.json"))["jobs"]
    assert over["line"]["text"] == "Ready" and "steps" not in over and "count" not in over


# --- in Chromium: the tab on the page caracole serve serves ---------------------------------------------------

QUICK = {"poll": 100, "undo": 500, "idle": 300}  # the page's timers, for a test on real time


def with_feed(fed: dict):
    """``serve``'s ``before``: /requests.json answers ``fed`` whatever is queued (the mockup's requests)."""

    def before(app):
        real = app.handle

        def handle(request):
            if request.target.startswith("/requests.json"):
                return app.finish(json_response(200, fed))
            return real(request)

        app.handle = handle

    return before


# What the page shows once the tab has drawn the mockup's six requests: where its tabs are, how wide it got, and its
# controls short of a thumb's size; then, with a fourth tab put before Requests, as the Sites tab will be, where its
# tabs are.
DRAWN = """
(() => {
  const tabs = () => Array.from(document.querySelectorAll(".masthead [role=tab]")).map((t) => {
    const r = t.getBoundingClientRect();
    return [t.id, Math.round(r.left), Math.round(r.right), Math.round(r.top)];
  });
  const drawn = () => {
    if (document.querySelectorAll("#requests li.req").length < 6) return setTimeout(drawn, 50);
    __UNFOLD__
    document.body.setAttribute("data-shown", JSON.stringify({
      groups: Array.from(document.querySelectorAll("#requests .req-head")).map((h) => h.textContent),
      ids: Array.from(document.querySelectorAll("#requests li.req")).map((li) => li.id),
      library: document.getElementById("library-view").hidden,
      selected: document.querySelector("[role=tab][aria-selected=true]").id,
      chips: Array.from(document.querySelectorAll("#req-6 .step-chip")).map((c) => c.textContent),
      says: Array.from(document.querySelectorAll("#requests .req-says")).map((s) => [s.textContent, s.dataset.tone]),
      actions: Array.from(document.querySelectorAll("#req-5 .req-next .btn, #req-4 .req-next .btn"))
        .map((b) => [b.textContent, b.tagName, b.closest("form") ? b.closest("form").getAttribute("action")
          : b.getAttribute("href")]),
      when: (document.querySelector("#req-5 time") || {}).textContent,
      tabs: tabs(), page: innerWidth, edge: Math.round(document.querySelector(".masthead").getBoundingClientRect().right),
    }));
    __SHORT__
    const sites = document.getElementById("tab-songbooks").cloneNode(true);
    sites.id = "tab-sites";
    sites.firstChild.textContent = "Sites ";
    sites.querySelector(".n").textContent = "12";
    document.getElementById("tab-requests").before(sites);
    document.querySelector("#tab-songbooks .n").textContent = "12";
    document.body.setAttribute("data-four", JSON.stringify({ tabs: tabs(),
      wide: document.documentElement.scrollWidth }));
  };
  drawn();
})();
"""


@pytest.mark.parametrize("width", [390, 1280])
@in_chromium
def test_the_tab_draws_every_request_and_fits_a_phone_with_four_tabs_in_light_and_dark(
        serve, cfg, tmp_path, width):  # noqa: F811
    script = DRAWN.replace("__UNFOLD__", UNFOLD).replace(
        "__SHORT__", noting("data-short", small_targets()) + noting("data-wide", "document.documentElement.scrollWidth"))
    url = serve(FakeCaracole(cfg), script, before=with_feed(mockup_feed()), timers=QUICK)
    for scheme in ("light", "dark"):
        dom = browser.dump_dom(url + "#tab=requests", (width, 900), mobile=width < 500, touch=width < 500,
                               media={"prefers-color-scheme": scheme}, budget_ms=20000)
        shown = noted(dom, "data-shown")
        assert shown["selected"] == "tab-requests" and shown["library"] is True, shown
        assert [t[0] for t in shown["tabs"]] == ["tab-library", "tab-songbooks", "tab-requests"]  # Requests last
        assert shown["groups"] == ["Now", "Today"]
        assert shown["ids"] == ["req-6", "req-7", "req-5", "req-4", "req-3", "req-2"]
        assert shown["chips"] == ["✓ Song: done", "✓ Match UG: done", "✓ Sheet UG: done", "PDF: running",
                                  "Lyrics: waiting", "Extras: waiting", "Songbooks: waiting"]
        assert shown["says"][:3] == [["Rendering the sheet…", "running"], ["Queued, next", "queued"],
                                     ["Not found", "missing"]]
        assert shown["actions"] == [["Get it from there", "BUTTON", "/lookup"],
                                    ["Request by name", "A", "/#q=Horse+The+Band+-+Crippled+By+Pizza"]]
        assert shown["when"] == "14:02"
        if width < 500:  # on a touch screen every control is a thumb's size, its Output open; a mouse keeps compact tabs
            assert noted(dom, "data-short") == [], scheme
        assert noted(dom, "data-wide") <= shown["page"], scheme  # no sideways scroll
        # The tabs on one line, inside the page; and so they stay with a fourth tab before Requests.
        four = noted(dom, "data-four")
        for tabs in (shown["tabs"], four["tabs"]):
            assert len({top for *_, top in tabs}) == 1 and tabs[-1][2] <= shown["edge"], (tabs, shown["edge"])
            assert all(a[2] <= b[1] for a, b in zip(tabs, tabs[1:])), tabs
        assert four["wide"] <= shown["page"], four


class Held:
    """The queue's commands, faked: the first waits until the test lets it go (``go``), one whose song is "Fail -
    Me" fails with an error, the rest are done; each prints a line. (``serve`` counts the page's asks and posts.)"""

    def __init__(self):
        from test_web_page import Polls

        self.go = threading.Event()
        self.calls: list[list[str]] = []
        self.posted: list = []
        self.polls = Polls()
        self.down = 0

    def __call__(self, args, emit):
        self.calls.append(list(args))
        emit(f"ran {args[0]} for {' - '.join(args[-2:])}")
        if len(self.calls) == 1:
            self.go.wait(30)
        if args[-2:] == ("Fail", "Me"):
            emit("error: It broke.")
            return 1
        return 0


def adds(*songs: tuple[str, str]):
    """``serve``'s ``before``: a request to add each song, queued before the queue starts."""

    def before(app):
        for artist, title in songs:
            app.submit(f"Add {artist} - {title}", f"{artist.lower()}/{title.lower()}",
                       [("Adding to the library", ("add", "--", artist, title))], display=f"{artist} - {title}")

    return before


SAYS = "(document.querySelector('#req-{n} .req-says') || {{}}).textContent"


@in_chromium
def test_cancel_try_again_and_output_work_in_the_tab_and_a_link_to_it_stays_on_the_page(
        serve, cfg, tmp_path):  # noqa: F811
    runner = Held()
    url = serve(runner, "(() => {})();\n", before=adds(("Radiohead", "Creep"), ("Oasis", "Wonderwall"), ("Fail", "Me")),
                timers=QUICK)
    try:
        with Browser(tmp_path / "chrome", width=390, height=844, mobile=True) as page:
            page.open(url)
            # The tab counts what waits or runs, as Songbooks counts its songbooks; the library shows until it's
            # pressed.
            assert page.js("document.querySelector('#tab-requests .n').textContent") == "3"
            assert page.js("document.getElementById('requests').hidden") is True
            page.click("#tab-requests")
            assert page.wait(SAYS.format(n=2) + " === 'Queued, next'"), page.js("document.body.innerText")
            assert page.js("location.hash") == "#tab=requests" and page.js("document.getElementById('library-view')"
                                                                           ".hidden") is True
            assert page.js(SAYS.format(n=1)) == "Adding to the library…"
            assert page.js("document.querySelector('#req-1 form')") is None  # the running one: never stopped
            # Cancel, posted with the form token, the page staying where it is.
            page.click("#req-2 form button")
            assert page.wait(SAYS.format(n=2) + " === 'Cancelled'"), page.js("document.body.innerText")
            assert page.js("location.pathname + location.hash") == "/#tab=requests"
            assert page.js("document.querySelector('#req-2 .req-reason').textContent") == (
                "Taken out of the queue before it ran.")
            runner.go.set()
            assert page.wait(SAYS.format(n=3) + " === 'Failed'", timeout=20), page.js("document.body.innerText")
            assert page.wait("document.querySelector('#tab-requests .n').textContent === ''")
            assert page.js("document.querySelector('#req-3 .req-reason').textContent") == "It broke."
            # Its Output, folded: opened, it brings what each command printed.
            page.click("#req-3 .req-output > summary")
            assert page.wait("(document.querySelector('#req-3 .req-output pre') || {}).textContent === "
                             "'ran add for Fail - Me\\nerror: It broke.'")
            assert page.js("document.querySelector('#req-3 .req-output').open") is True
            # Open, it takes the whole request's width, under its line.
            output, item = page.js("[document.querySelector('#req-3 .req-output').getBoundingClientRect().width, "
                                   "document.querySelector('#req-3').getBoundingClientRect().width]")
            assert output > 0.9 * item - 40, (output, item)
            # Try again: the same command queued again, a request of its own, drawn first.
            page.click("#req-3 .req-next form button")
            assert page.wait(SAYS.format(n=4) + " === 'Failed'", timeout=20), page.js("document.body.innerText")
            assert [c for c in runner.calls if c[-2:] == ["Fail", "Me"]] == [["add", "--", "Fail", "Me"]] * 2
            assert page.js("Array.from(document.querySelectorAll('#requests li.req')).map((li) => li.id)")[:2] == [
                "req-4", "req-3"]
            assert page.js("document.querySelector('#req-3 .req-output').open") is True  # as you left it
            # A link to another tab of the page (a request line's Details) stays on the page; one to the library's own
            # words (Request by name) shows the library, searched.
            page.click("#tab-library")
            page.js("(() => { const a = document.createElement('a'); a.id = 'to-4'; a.href = '/#tab=requests&job=4';"
                    " a.textContent = 'Details'; document.getElementById('list').prepend(a); window.here = 1; })()")
            page.click("#to-4")
            assert page.wait("document.querySelector('#req-4 .req-output pre') !== null"
                             " && document.querySelector('#req-4 .req-output').open")
            assert page.js("window.here") == 1 and page.js("document.activeElement.id") == "req-4"
            assert page.js("location.hash") == "#tab=requests"
            page.js("(() => { const a = document.createElement('a'); a.id = 'by-name'; a.href = '/#q=Creep';"
                    " a.textContent = 'Request by name'; document.getElementById('requests').prepend(a); })()")
            page.click("#by-name")
            assert page.wait("!document.getElementById('library-view').hidden && document.getElementById('q').value"
                             " === 'Creep'")
            assert page.js("window.here") == 1 and page.js("document.getElementById('requests').hidden") is True
            # The tablist's own keys: ← from the first goes round to the last, Requests; Home and End.
            page.js("document.getElementById('tab-library').focus()")
            page.press("ArrowLeft")
            assert page.js("[document.activeElement.id, document.querySelector('[aria-selected=true]').id]") == [
                "tab-requests", "tab-requests"]
            page.press("Home")
            assert page.js("document.activeElement.id") == "tab-library"
            page.press("ArrowRight")
            assert page.js("[document.activeElement.id, location.hash]") == ["tab-songbooks", "#q=Creep&tab=songbooks"]
            # Opened at a request (job=N, where the server sends a form back), its output is open and in view.
            page.open(url + "#tab=requests&job=3")
            assert page.wait("document.querySelector('#req-3 .req-output pre') !== null")
            assert page.js("[document.querySelector('#req-3 .req-output').open, document.activeElement.id, "
                           "location.hash]") == [True, "req-3", "#tab=requests"]
    finally:
        runner.go.set()
