"""caracole serve's requests page (/jobs: jobs_routes.py, pages.py's ``jobs_page``, outcome.py): now, the
request that runs with its steps and those queued under it, each with Cancel; then the feed of finished
ones, newest first under Today and Earlier, each with its outcome, its reason, when it ended and its next
step; and the routes that cancel a queued request and try a finished one again."""

from __future__ import annotations

import re
import time
from datetime import UTC, datetime, timedelta

import pytest
from helpers import browser
from helpers.browser import Browser, in_chromium
from helpers.targets import UNFOLD, noted, noting, small_targets

from caracole.get import STAGES, progress_line
from caracole.library import song_dir
from caracole.songs import update_song
from caracole.web.app import WebApp
from caracole.web.jobs import Job, JobQueue, Stage, Step, lookup_steps
from caracole.web.outcome import outcome
from caracole.web.pages import jobs_page
from caracole.web.songbooks import KEY
from caracole.web.status import SongFacts, job_line

from conftest import add_song
from test_web_app import ALLOWED, JOB_ITEM, Recorder, answer, get, get_json, header, post, text

ITEM = re.compile(r'<li class="job[^"]*" id="job-(\d+)">')


def items(body: str) -> list[str]:
    """The requests on the page, by id, in the order they are drawn."""
    return ITEM.findall(body)


def section(body: str, name: str) -> str:
    found = re.search(rf'<section class="requests {name}".*?</section>', body, re.S)
    return found.group(0) if found else ""


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


def mockup() -> tuple[list[Job], dict, dict]:
    """The mockup's requests: Muse - Hysteria running, one queued, two not found, one ready whose lyrics wait,
    a songbook deleted. Newest first, with their lines and outcomes, as jobs_routes.py gives them."""
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
             4: SongFacts(checked_now=True, asked_ug=True), 3: SongFacts(sheet="Radiohead/Creep/sheet.html")}
    songs = {5: 15, 4: 14, 3: 13}
    jobs = [queued, running, nyc, pizza, creep, book]
    lines = {job.id: job_line(job, facts.get(job.id), ahead=1 if job is queued else 0) for job in jobs}
    outcomes = {job.id: outcome(job, lines[job.id], facts.get(job.id), song_id=songs.get(job.id))
                for job in jobs if not job.active}
    return jobs, lines, outcomes


def mockup_page(*, refresh: bool = False) -> str:
    jobs, lines, outcomes = mockup()
    return jobs_page(jobs, lines, outcomes=outcomes, csrf="tok", now=NOW, refresh=refresh)


# --- now: the running request and those queued ---------------------------------------------------------------


def test_the_running_lookup_is_a_card_with_its_stages_as_steps():
    body = mockup_page()
    now = section(body, "now")
    assert items(now) == ["6", "7"]  # the running one, then the queue in order
    card = dict(JOB_ITEM.findall(now))["6"]
    assert '<span class="song">Muse - Hysteria</span>' in card and "started 12 s ago" in card
    assert '<span class="says running">Rendering the sheet…</span>' in card
    chips = re.findall(r'<li class="chip (\w+)"( aria-current="step")?><span aria-hidden="true">([^<]*)</span>'
                       r"([^<]+)<span", card)
    assert [(state, mark + name, bool(current)) for state, current, mark, name in chips] == [
        ("done", "✓ Song", False), ("done", "✓ Match", False), ("done", "✓ Sheet", False),
        ("running", "PDF", True), ("waiting", "Lyrics", False), ("waiting", "Extras", False),
        ("waiting", "Songbooks", False)]


def test_queued_requests_say_their_place_and_each_can_be_cancelled():
    jobs = [Job(n, f"Add A - {n}", f"a/{n}", [Step("Adding to the library", ("add",))], display=f"A - {n}")
            for n in (4, 3, 2, 1)]
    jobs[-1].state = "running"
    body = jobs_page(jobs, {}, csrf="tok", now=NOW)
    shown = dict(JOB_ITEM.findall(body))
    assert [re.search(r'class="says queued">([^<]*)<', shown[n]).group(1) for n in ("2", "3", "4")] == [
        "Queued, next", "Queued, 2nd", "Queued, 3rd"]
    form = re.search(r'<form class="act-form" method="post" action="/jobs/cancel">.*?</form>', shown["3"]).group(0)
    assert '<input type="hidden" name="csrf" value="tok">' in form and 'name="job" value="3"' in form
    assert 'aria-label="Cancel the request for A - 3"' in form and ">Cancel</button>" in form
    assert "/jobs/cancel" not in shown["1"]  # the running one: never stopped halfway


# --- the feed: what ended, and the next step ------------------------------------------------------------------


def test_each_outcome_says_its_word_its_reason_and_its_next_step():
    body = mockup_page()
    today = section(body, "today")
    assert items(today) == ["5", "4", "3", "2"]  # newest first
    shown = dict(JOB_ITEM.findall(today))
    nyc = shown["5"]
    assert '<span class="says missing">Not found</span>' in nyc
    assert ('<p class="reason">Ultimate Guitar has no chords for it; gtptabs.com&#x27;s index lists a page for '
            "it.</p>" in nyc)
    assert re.search(r'<form class="act-form" method="post" action="/lookup">.*name="song" value="15">'
                     r'.*name="then" value="jobs">.*>Get it from there</button></form>', nyc)
    assert '<time class="when" datetime="' in nyc and ">14:02</time>" in nyc
    pizza = shown["4"]
    assert '<a class="btn act" href="/#q=Horse+The+Band+-+Crippled+By+Pizza">Request by name</a>' in pizza
    assert '<p class="reason">Ultimate Guitar has no chords for it.</p>' in pizza
    creep = shown["3"]
    assert '<span class="says ready">Ready</span>' in creep
    assert '<p class="reason">LRCLIB answered 503: the lyrics wait for tonight&#x27;s run.</p>' in creep
    assert '<a class="btn act primary" href="/Radiohead/Creep/sheet.html">Open</a>' in creep
    book = shown["2"]
    assert '<span class="says removed">Deleted</span>' in book and 'class="btn' not in book
    # The to-do page is no next step here.
    assert "_todo.md" not in body and "to-do page" not in body


def test_every_request_keeps_its_output_fold():
    body = mockup_page()
    for job_id, item in JOB_ITEM.findall(body):
        assert '<details class="output"><summary>Output</summary>' in item, job_id
    opened = mockup()
    page = jobs_page(opened[0], opened[1], outcomes=opened[2], csrf="tok", now=NOW, opened=3)
    assert '<details class="output" open>' in dict(JOB_ITEM.findall(page))["3"]


def test_the_outputs_time_is_in_the_servers_time_zone_named(monkeypatch):
    monkeypatch.setenv("TZ", "EST+05")  # five hours behind UTC, a POSIX rule: no zone files
    time.tzset()
    try:
        job = Job(1, "Add A - B", "a/b", [Step("Adding to the library", ("add",), state="done")], state="done",
                  display="A - B", queued_at=datetime(2026, 10, 21, 3, 30, tzinfo=UTC),
                  finished_at=datetime(2026, 10, 21, 3, 31, tzinfo=UTC))
        body = jobs_page([job], {1: job_line(job, SongFacts())}, csrf="tok", now=datetime(2026, 10, 21, 12, tzinfo=UTC))
    finally:
        monkeypatch.undo()
        time.tzset()
    assert "Add A - B · requested 2026-10-20 22:30 EST" in body


def test_finished_requests_are_grouped_by_the_day_they_ended_in_the_servers_time_zone():
    def done(job_id: int, when: datetime) -> Job:
        return Job(job_id, f"Add A - {job_id}", f"a/{job_id}", [Step("Adding to the library", ("add",), state="done")],
                   state="done", display=f"A - {job_id}", queued_at=when, finished_at=when)

    midnight = NOW.replace(hour=0, minute=0)
    jobs = [done(4, NOW - timedelta(minutes=1)), done(3, midnight + timedelta(minutes=1)),
            done(2, midnight - timedelta(minutes=1)), done(1, NOW - timedelta(days=3))]
    lines = {job.id: job_line(job, SongFacts()) for job in jobs}
    body = jobs_page(jobs, lines, csrf="tok", now=NOW)
    assert items(section(body, "today")) == ["4", "3"] and items(section(body, "earlier")) == ["2", "1"]
    assert section(body, "now") == ""
    earlier = dict(JOB_ITEM.findall(body))["2"]
    yesterday = (midnight - timedelta(minutes=1))
    assert f">{yesterday.day} {yesterday:%b}, 23:59</time>" in earlier
    assert body.index('id="h-today"') < body.index('id="h-earlier"')


# --- the routes: Cancel, Try again -----------------------------------------------------------------------------


@pytest.fixture
def queue():
    return JobQueue(Recorder(), limit=5)


@pytest.fixture
def app(cfg, queue):
    return WebApp(cfg, queue, allowed=ALLOWED, csrf="tok")


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
    assert cancelled.status == 303 and header(cancelled, "location") == "/jobs"
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
    body = text(get(app, "/jobs"))
    assert '<li class="job over cancelled" id="job-2">' in section(body, "today")
    item = dict(JOB_ITEM.findall(body))["2"]
    assert '<span class="says cancelled">Cancelled</span>' in item
    assert '<p class="reason">Taken out of the queue before it ran.</p>' in item
    assert "/jobs/cancel" not in item and "/jobs/again" not in item  # you cancelled it: the library asks again
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
    item = dict(JOB_ITEM.findall(text(get(app, "/jobs"))))["1"]
    assert 'action="/jobs/again"' in item and 'name="job" value="1"' in item and ">Try again</button>" in item
    assert post(app, "/jobs/again", {"job": "1"}, csrf=None).status == 403
    assert post(app, "/jobs/again", {"job": "1"}, csrf="wrong").status == 403
    assert len(queue.snapshot()) == 1
    response = post(app, "/jobs/again", {"job": "1"})
    assert response.status == 303 and header(response, "location") == "/jobs"
    again, first = queue.snapshot()
    assert again.id == 2 and again.state == "queued"
    assert [s.args for s in again.steps] == [s.args for s in first.steps]
    assert (again.title, again.song_key, again.fetching, again.display) == (
        first.title, first.song_key, first.fetching, first.display)
    assert post(app, "/jobs/again", {"job": "2"}).status == 409  # not over yet
    assert post(app, "/jobs/again", {"job": "9"}).status == 404
    queue.run_pending()
    assert queue.snapshot()[0].state == "done"


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
    item = dict(JOB_ITEM.findall(text(get(app, "/jobs"))))["1"]
    # Nobody asked Ultimate Guitar: the index doesn't have it under this name, and its artist's page isn't known.
    assert '<p class="reason">Not in the offline Ultimate Guitar index under this name.</p>' in item
    assert "no chords" not in item and "Request by name" not in item
    assert item.count("See what caracole search finds") == 1
    assert (f'<div class="next"><a class="btn act primary" href="/review?song={pizza.id}">See what caracole search '
            "finds</a><time" in item)
    assert 'class="waits"' not in item
    # The library page's line for it is as it was.
    [view] = answer(get_json(app, "/jobs.json?jobs=1"))["jobs"]
    assert view["line"] == {"tone": "missing", "text": "Not found",
                            "link": {"label": "see the to-do page", "href": "_todo.md"}, "details": None}


def test_a_song_not_found_requests_it_by_name_or_gets_it_where_the_indexes_have_it(cfg, conn, queue, app):
    pizza = lookup_ran(cfg, conn, queue, app, "Horse The Band", "Crippled By Pizza", asked=True)
    item = dict(JOB_ITEM.findall(text(get(app, "/jobs"))))["1"]
    assert '<p class="reason">Ultimate Guitar has no chords for it.</p>' in item
    assert '<a class="btn act" href="/#q=Horse+The+Band+-+Crippled+By+Pizza">Request by name</a>' in item
    # The library page's line for it is as it was: Not found, with the to-do page.
    [view] = answer(get_json(app, "/jobs.json?jobs=1"))["jobs"]
    assert view["line"] == {"tone": "missing", "text": "Not found",
                            "link": {"label": "see the to-do page", "href": "_todo.md"}, "details": None}
    assert view["songId"] == pizza.id
    conn.execute("INSERT INTO lacuerda_index (path, artist_slug, artist, artist_key, title, title_key, versions, "
                 "acordes, page) VALUES ('estopa/como_camaron', 'estopa', 'Estopa', 'estopa', 'Como Camarón', "
                 "'como-camaron', 'lcd', 1, 'e')")
    camaron = lookup_ran(cfg, conn, queue, app, "Estopa", "Como Camarón")
    item = dict(JOB_ITEM.findall(text(get(app, "/jobs"))))["2"]
    assert "Not in the offline Ultimate Guitar index under this name; LaCuerda has a sheet." in item
    # What caracole search finds, beside it, in the same row: never a second way on under the output.
    assert re.search(r'<div class="next"><form [^>]*action="/lookup">.*?</form><a class="btn act" '
                     rf'href="/review\?song={camaron.id}">See what caracole search finds</a><time', item)
    assert item.count("See what caracole search finds") == 1
    form = re.search(r'<form class="act-form" method="post" action="/lookup">.*?</form>', item).group(0)
    fields = dict(re.findall(r'name="(\w+)" value="([^"]*)"', form))
    assert fields == {"csrf": "tok", "song": str(camaron.id),
                      "lacuerda": "https://acordes.lacuerda.net/estopa/como_camaron.shtml", "then": "jobs"}
    # The form is the lookup a search's Get it runs, back to the requests page, where it runs.
    response = post(app, "/lookup", {k: v for k, v in fields.items() if k != "csrf"})
    assert response.status == 303 and header(response, "location") == "/jobs"
    assert queue.snapshot()[0].steps[0].args == (
        "get", "--progress", "--lacuerda=https://acordes.lacuerda.net/estopa/como_camaron.shtml", "--", "Estopa",
        "Como Camarón")


def test_a_song_ready_opens_its_sheet_and_its_line_on_the_library_page_is_unchanged(cfg, conn, queue, app):
    lookup_ran(cfg, conn, queue, app, "Radiohead", "Creep", sheet=True)
    item = dict(JOB_ITEM.findall(text(get(app, "/jobs"))))["1"]
    assert '<a class="btn act primary" href="/Radiohead/Creep/sheet.pdf">Open</a>' in item
    [view] = answer(get_json(app, "/jobs.json?jobs=1"))["jobs"]
    assert view["line"] == {"tone": "ready", "text": "Ready",
                            "link": {"label": "Open sheet", "href": "Radiohead/Creep/sheet.pdf"}, "details": None}


def test_a_lookups_progress_shows_on_the_running_card(cfg, conn):
    seen = []

    def runner(args, emit):
        emit(progress_line({"stage": "song", "state": "done", "detail": "in the library"}))
        emit(progress_line({"stage": "match", "state": "done", "detail": "matched"}))
        emit(progress_line({"stage": "sheet", "state": "running"}))
        seen.append(text(get(app, "/jobs")))
        return 0

    queue = JobQueue(runner)
    app = WebApp(cfg, queue, allowed=ALLOWED, csrf="tok")
    post(app, "/request", {"artist": "Radiohead", "title": "Creep", "fetch": "1"})
    queue.run_pending()
    card = dict(JOB_ITEM.findall(section(seen[0], "now")))["1"]
    assert '<span class="says running">Fetching from Ultimate Guitar…</span>' in card
    assert '<li class="chip running" aria-current="step"><span aria-hidden="true"></span>Sheet' in card
    assert '<li class="chip done"><span aria-hidden="true">✓ </span>Match' in card
    assert re.search(r'<span class="ago">started \d+ s ago</span>', card)


# --- in Chromium: on a phone it stacks; every control a thumb's size; light and dark -------------------------


CHECKS = (UNFOLD + noting("data-short", small_targets(".app a"))
          + noting("data-wide", "document.documentElement.scrollWidth")
          + noting("data-page", "window.innerWidth"))


@pytest.mark.parametrize("width", [390, 1280])
@in_chromium
def test_the_page_fits_its_width_and_every_control_is_a_thumbs_size_in_light_and_dark(tmp_path, width):
    path = tmp_path / "requests.html"
    path.write_text(mockup_page().replace("</body>", f"<script>{CHECKS}</script>\n</body>"), encoding="utf-8")
    for scheme in ("light", "dark"):
        dom = browser.dump_dom(path.as_uri(), (width, 900), mobile=width < 500, touch=width < 500,
                               media={"prefers-color-scheme": scheme})
        assert noted(dom, "data-short") == [], scheme
        assert noted(dom, "data-wide") <= noted(dom, "data-page"), scheme  # no sideways scroll


@in_chromium
def test_on_a_phone_a_requests_parts_stack_and_on_a_wide_screen_its_next_step_sits_beside_it(tmp_path):
    path = tmp_path / "requests.html"
    path.write_text(mockup_page(), encoding="utf-8")
    where = ("(() => { const job = document.getElementById('job-5'); const r = (s) => job.querySelector(s)"
             ".getBoundingClientRect(); return [r('.line').top, r('.line').right, r('.next').top, r('.next').left]; })()")
    with Browser(tmp_path / "phone", width=390, height=844, mobile=True) as phone:
        phone.open(path.as_uri())
        line_top, _, next_top, _ = phone.js(where)
        assert next_top > line_top + 20  # under the song's line
    with Browser(tmp_path / "wide", width=1280, height=900) as wide:
        wide.open(path.as_uri())
        line_top, line_right, next_top, next_left = wide.js(where)
        assert next_left >= line_right and abs(next_top - line_top) < 40  # beside it


@in_chromium
def test_output_still_unfolds(tmp_path):
    path = tmp_path / "requests.html"
    path.write_text(mockup_page(), encoding="utf-8")
    with Browser(tmp_path / "profile", width=1280, height=900) as page:
        page.open(path.as_uri())
        assert page.js("document.querySelector('#job-3 details.output').open") is False
        page.click("#job-3 details.output > summary")
        assert page.wait("document.querySelector('#job-3 details.output').open === true")
        assert page.js("document.querySelector('#job-3 details.output pre') !== null")
        # Open, it takes the whole request's width, under its line.
        widths = page.js("[document.querySelector('#job-3 details.output').getBoundingClientRect().width, "
                         "document.querySelector('#job-3').getBoundingClientRect().width]")
        assert widths[0] > 0.9 * widths[1] - 40
