"""A lookup's steps on the library page caracole serve serves, in a real browser: a segmented bar on the song's line.

While a song is looked up (Fetch now, a search result's Get it), once its request has run a second (none before it,
outcome.py's ``BAR_AFTER``, so a quick one draws none), its request line is a bar of its steps (outcome.py's, as
/jobs.json gives them), a segment a step: those done in the accent, the one that runs at half, pulsing (steady where
motion is unwelcome), those to come grey, a skipped one an outline, a failed one red, taller, with its "!"; then the
step in hand, the site it names in full and its place among them all, "Sheet · Ultimate Guitar · 3 of 7", which is
what a screen reader hears, in one row on a laptop and a phone alike, the segments square at their ends.
Ended Ready, the bar folds away and the line is the song's own, which opens its sheet; ended otherwise, the line says
how, and the steps stay under it as chips (done ticked, a failed one crossed, Match naming Ultimate Guitar's index or
"Match · not on UG", plain), to show which step stopped, each in its place. A real ``caracole serve`` answers on a
socket with the page's timers quick (``WebApp(timers=...)``), and its queue runs ``Staged``: ``caracole get
--progress``'s lines, said a stage at a time, stopping where the test says until it lets it go on.
"""
from __future__ import annotations

import json
import threading
from datetime import UTC, datetime, timedelta

import pytest
from helpers.browser import CHROMIUM_MARKS, Browser, BrowserError
from test_web_page_search import RYAN, WONDERWALL, search, sites

from caracole import db
from caracole.get import MATCH_NOT_FOUND, NOT_IN_INDEX, PROGRESS_PREFIX, SHEET_FROM
from caracole.library import keep_file, song_dir
from caracole.overrides import override_key
from caracole.songs import find_song, update_song
from caracole.versions import upsert_version
from caracole.web import outcome
from caracole.web.app import WebApp
from caracole.web.jobs import JobQueue
from caracole.web.security import allowed_hosts
from caracole.web.server import make_server

from conftest import add_song

pytestmark = CHROMIUM_MARKS  # every test here drives the page in Chromium

QUICK = {"poll": 100, "undo": 500}  # the page asks how its requests go every 100 ms (test_web_page.py's)
HOLD = object()  # in a script: stop here until the test lets it go on (``Staged.go``)


def stage(name: str, state: str, detail: str = "") -> dict:
    return {"stage": name, "state": state, "detail": detail}


def kept_from(provider: str):
    """A script's step: the song's sheet kept, as a fetch from ``provider`` keeps one (its version, its text, its
    PDF), and the song found."""

    def keep(conn, cfg, song):
        vid = upsert_version(conn, provider=provider, tab_id="1", song_id=song.id, slot="sheet", kind="chords",
                             rating=4.5, votes=12, version=1, label=None, url="https://example.com/1", raw={},
                             now="x")
        keep_file(conn, cfg.library_dir, song=song, version_id=vid, name="sheet.txt", data=b"Words\n", rank=1)
        (song_dir(cfg.library_dir, song) / "sheet.pdf").write_bytes(b"%PDF-1.4")
        update_song(conn, song.id, status="found", ug_dirty=False)

    return keep


def not_matched(conn, cfg, song):
    """A script's step: the offline index lacks the song."""
    update_song(conn, song.id, match_decision="not_found")


AFTER_THE_SHEET = [stage("lyrics", "done", "found"), stage("ug", "running"), stage("ug", "done", "sheet 1"),
                   stage("lacuerda", "running"), stage("lacuerda", "skipped", "not a song for LaCuerda: not Spanish, "
                                                                            "a complete sheet already, or asked this "
                                                                            "month"),
                   stage("gtptabs", "running"), stage("gtptabs", "skipped", "no file wanted, or gtptabs.com's index "
                                                                            "doesn't know the artist"),
                   stage("pages", "running"), stage("pages", "done", "_todo.md and index.html rewritten"),
                   stage("songbooks", "running"), stage("songbooks", "skipped", "in no songbook")]
# A song Ultimate Guitar has: its sheet from there; the test holds it while the sheet is asked for, then while the
# lyrics are.
FROM_UG = [stage("song", "running"), stage("song", "done", "in the book"), stage("match", "running"),
           stage("match", "done", "matched to it"), stage("sheet", "running"),
           stage("sheet", "running", SHEET_FROM["ug"]), HOLD, kept_from("ug"),
           stage("sheet", "done", "tab 1 from Ultimate Guitar"), stage("pdf", "running"), stage("pdf", "done", "made"),
           stage("lyrics", "running"), HOLD, *AFTER_THE_SHEET]
# A song Ultimate Guitar's index lacks, whose sheet LaCuerda fails to give: held while LaCuerda is asked.
LACUERDA_FAILS = "LaCuerda failed (lacuerda: 503: https://acordes.lacuerda.net/x: HTTP 503); the nightly run tries again"
NOT_ON_UG = [stage("song", "running"), stage("song", "done", "in the book"), stage("match", "running"),
             not_matched, stage("match", "done", MATCH_NOT_FOUND), stage("sheet", "running"),
             stage("sheet", "running", SHEET_FROM["lacuerda"]), HOLD, stage("sheet", "failed", LACUERDA_FAILS),
             stage("pdf", "running"), stage("pdf", "skipped", "no sheet yet"), stage("lyrics", "running"),
             stage("lyrics", "done", "found"), stage("ug", "running"), stage("ug", "skipped", NOT_IN_INDEX),
             stage("lacuerda", "running"), stage("lacuerda", "failed", "asked already, for the sheet: " + LACUERDA_FAILS),
             stage("gtptabs", "running"), stage("gtptabs", "skipped", "no file wanted"), stage("pages", "running"),
             stage("pages", "done", ""), stage("songbooks", "running"), stage("songbooks", "skipped", "no songbook")]

# The same, held again once its sheet failed, as it asks for the lyrics.
LYRICS = NOT_ON_UG.index(stage("lyrics", "running")) + 1
NOT_ON_UG_HELD = [*NOT_ON_UG[:LYRICS], HOLD, *NOT_ON_UG[LYRICS:]]


class Staged:
    """``caracole get --progress``, said a stage at a time from ``script``: an event is printed as the command prints
    it, a function is what the command does to the library then (``f(conn, cfg, song)``), and ``HOLD`` stops it until
    the test lets it go on (``go``). The song is the one its names find, added from wanted.txt first, as the lookup's
    song stage adds one the server wrote there."""

    def __init__(self, cfg):
        self.cfg = cfg
        self.script: list = []
        self.gate = threading.Semaphore(0)

    def __call__(self, args, emit):
        from caracole.wanted import sync_wanted

        conn = db.connect(self.cfg.db_path)
        try:
            sync_wanted(conn, self.cfg.wanted_file, datetime.now(UTC))
            song = find_song(conn, override_key(f"{args[-2]} - {args[-1]}"))
            for step in self.script:
                if step is HOLD:
                    if not self.gate.acquire(timeout=30):
                        return 1
                elif callable(step):
                    step(conn, self.cfg, song)
                else:
                    emit(PROGRESS_PREFIX + json.dumps(step))
            return 0
        finally:
            conn.close()

    def go(self) -> None:
        self.gate.release()


@pytest.fixture
def live(cfg):
    """The library page on a socket, its timers quick; its queue runs ``Staged`` (``runner.script``, set by the
    test before the page asks)."""
    runner = Staged(cfg)
    queue = JobQueue(runner)
    queue.start()
    app = WebApp(cfg, queue, allowed=allowed_hosts("127.0.0.1"), csrf="tok", timers=QUICK, searches_lacuerda=False)
    server = make_server(app, "127.0.0.1", 0)
    threading.Thread(target=server.serve_forever, args=(0.01,), daemon=True).start()  # stops within 10 ms
    yield f"http://127.0.0.1:{server.server_address[1]}/", runner
    for _ in range(4):  # a test that stopped halfway leaves no lookup waiting
        runner.go()
    server.shutdown()
    server.server_close()
    queue.stop()


def driven(tmp_path, width: int) -> Browser:
    try:
        return Browser(tmp_path / f"chrome-{width}", width=width, height=900 if width > 500 else 844,
                       mobile=width < 500)
    except BrowserError as e:
        pytest.skip(f"chromium couldn't run: {e}")


def bar_of(item: str) -> str:
    """The expression for the segments of ``item``'s bar (its running one, else its frozen one): each one's state."""
    segs = f"{item} .progress.barred .step-segs > i, {item} .steps > .step-bar .step-segs > i"
    return f"[...document.querySelectorAll({json.dumps(segs)})].map((s) => s.className.replace('seg ', ''))"


def words_of(item: str) -> str:
    """The expression for the words beside ``item``'s bar: [the step and its site, the count]."""
    bar = json.dumps(f"{item} .progress.barred, {item} .step-bar")
    return (f"(() => {{ const b = document.querySelector({bar}); "
            "const t = (s) => (b && b.querySelector(s) || {}).textContent || ''; "
            "return [t('.step-at'), t('.step-count')]; })()")


def steps_of(item: str) -> str:
    """The expression for the chips under ``item`` (a selector), once its request is over: each one's state and its
    words as shown (its mark, its name, its site), what a screen reader alone hears left out."""
    return (f"[...document.querySelectorAll({json.dumps(item + ' .step-chips > li')})].map((c) => {{ "
            "const shown = c.cloneNode(true); shown.querySelectorAll('.visually-hidden').forEach((n) => n.remove()); "
            "return [c.className.replace('step-chip ', ''), shown.textContent]; })")


def colour(var: str) -> str:
    """The expression for the colour ``var`` (a custom property of the page's) computes to: a probe's background."""
    return (f"(() => {{ const i = document.createElement('i'); i.style.background = 'var({var})'; "
            "document.body.appendChild(i); const c = getComputedStyle(i).backgroundColor; i.remove(); return c; })()")


ACCENT = colour("--accent")
FAILED = colour("--failed")


def one_row(page: Browser, item: str) -> None:
    """``item``'s bar in one row: its segments and its count centred on one line, the count within ``item``'s line,
    and no page wider than the screen."""
    at = page.js(f"(() => {{ const item = document.querySelector({json.dumps(item)}); "
                 "const r = (s) => item.querySelector(s).getBoundingClientRect(); "
                 "const segs = r('.progress.barred .step-segs'), count = r('.progress.barred .step-count'); "
                 "return [segs.top + segs.height / 2, count.top + count.height / 2, count.right, "
                 "item.getBoundingClientRect().right]; })()")
    assert abs(at[0] - at[1]) <= 2, at
    assert at[2] <= at[3] + 0.5, at
    assert page.js("document.documentElement.scrollWidth <= window.innerWidth"), page.js(
        "[document.documentElement.scrollWidth, window.innerWidth]")


def wait_for(page: Browser, expression: str, expected, timeout: float = 15.0) -> None:
    """Wait until ``expression`` is ``expected``, as JSON says them."""
    shown = json.dumps(expected, separators=(",", ":"), ensure_ascii=False)  # as JSON.stringify writes it
    assert page.wait(f"JSON.stringify({expression}) === {json.dumps(shown)}", timeout=timeout), page.js(expression)


def creep(cfg):
    """Creep, a song Ultimate Guitar's index matched."""
    conn = db.connect(cfg.db_path)
    try:
        song = add_song(conn, "Radiohead", "Creep")
        update_song(conn, song.id, match_decision="accept", match_artist_key="radiohead", match_song_key="creep")
        return song
    finally:
        conn.close()


def line_of(song) -> str:
    return f'#list article.line[data-id="{song.id}"]'


@pytest.mark.parametrize("width", [1280, 390, 320])
def test_a_running_lookup_is_a_segmented_bar_on_its_line_in_one_row(cfg, live, tmp_path, width):
    base, runner = live
    runner.script = FROM_UG
    line = line_of(creep(cfg))
    with driven(tmp_path, width) as page:
        page.open(base)
        page.click(f"{line} form.fetch button")
        # Asking Ultimate Guitar for the sheet: the song and its match over, the sheet in hand, four steps to come.
        wait_for(page, bar_of(line), ["done", "done", "running", "waiting", "waiting", "waiting", "waiting"])
        wait_for(page, words_of(line), ["Sheet · Ultimate Guitar", " · 3 of 7"])
        p = f"document.querySelector('{line} .progress')"
        assert page.js(f"{p}.textContent") == "Sheet · Ultimate Guitar · 3 of 7"  # what a screen reader hears
        assert page.js(f"{p}.getAttribute('role')") == "status"
        assert page.js(f"{p}.querySelector('.step-segs').getAttribute('aria-hidden')") == "true"
        assert page.js(f"{p}.querySelector('.step-at b').textContent") == "Sheet"
        assert page.js(f"document.querySelector('{line} .step-chips, {line} .steps')") is None  # no chips meanwhile
        one_row(page, line)
        assert page.js(f"getComputedStyle(document.querySelector('{line} .seg.running')).animationName") == "step-pulse"
        done = f"getComputedStyle(document.querySelector('{line} .seg.done'))"
        assert page.js(f"{done}.backgroundColor") == page.js(ACCENT)
        assert page.js(f"{done}.borderTopLeftRadius") == "0px"  # square ends
        assert page.js(f"getComputedStyle({p}, '::before').content") == "none"  # the bar in place of the line's dot
        runner.go()
        # The sheet kept, from Ultimate Guitar, and its PDF: the lyrics now, the fifth step of seven, no site.
        wait_for(page, bar_of(line), ["done"] * 4 + ["running", "waiting", "waiting"])
        wait_for(page, words_of(line), ["Lyrics", " · 5 of 7"])
        assert page.js(f"{p}.textContent") == "Lyrics · 5 of 7"
        one_row(page, line)
        runner.go()
        # Ready: the bar folds away and nothing takes its place; the line is the song's, found, its sheet's button
        # opening it. Its request line says Ready to a screen reader alone, which hears the request end.
        assert page.wait(f"{p}.dataset.tone === 'ready'", timeout=15)
        assert page.js(f"{p}.classList.contains('barred')") is False
        assert page.js(f"{p}.getBoundingClientRect().height") <= 1
        assert page.js(f"document.querySelector('{line} .step-segs, {line} .step-chips')") is None
        assert page.js(f"{p}.textContent") == "Ready"
        assert page.js(f"{p}.querySelector('a')") is None  # no "Ready · Open sheet"
        # Found, it needs no badge: its status is the line's alone, as the page's filters read it.
        assert page.js(f"document.querySelector('{line}').dataset.status") == "found"
        assert page.js(f"document.querySelector('{line} .line-status .badge')") is None
        assert page.wait(f"!!document.querySelector('{line} .line-plays a.play-sheet')")
        # The focus, on the request line since Fetch now, is on the first of its buttons, its sheet's.
        assert page.js("document.activeElement.classList.contains('play-sheet')") is True
        assert page.js(f"document.querySelector('{line}').contains(document.activeElement)")
        assert page.js("document.documentElement.scrollWidth <= window.innerWidth")


def test_a_lookup_that_ends_otherwise_keeps_its_steps_to_show_which_one_stopped(cfg, live, tmp_path):
    base, runner = live
    runner.script = NOT_ON_UG_HELD
    conn = db.connect(cfg.db_path)
    song = add_song(conn, "Estopa", "Tu Calorro")
    conn.close()
    line = line_of(song)
    with driven(tmp_path, 1280) as page:
        page.open(base)
        page.click(f"{line} form.fetch button")
        # The offline index lacks it, plainly: no failure, drawn as done, as the sheet is asked of LaCuerda.
        wait_for(page, bar_of(line), ["done", "plain", "running", "waiting", "waiting", "waiting", "waiting"])
        wait_for(page, words_of(line), ["Sheet · LaCuerda", " · 3 of 7"])
        assert page.js(f"getComputedStyle(document.querySelector('{line} .seg.plain')).backgroundColor") == (
            page.js(ACCENT))
        runner.go()
        # LaCuerda failed: its segment red and taller, with its "!", which a screen reader doesn't hear; no sheet, so no
        # PDF, skipped in its place, and the lyrics now.
        wait_for(page, bar_of(line), ["done", "plain", "failed", "skipped", "running", "waiting", "waiting"])
        wait_for(page, words_of(line), ["Lyrics", " · 5 of 7"])
        failed = f"document.querySelector('{line} .seg.failed')"
        assert page.js(f"{failed}.textContent") == "!"
        assert page.js(f"{failed}.getBoundingClientRect().height") == 12
        assert page.js(f"getComputedStyle({failed}).backgroundColor") == page.js(FAILED)
        assert page.js(f"getComputedStyle(document.querySelector('{line} .seg.skipped')).backgroundColor") == (
            "rgba(0, 0, 0, 0)")  # an outline alone
        one_row(page, line)
        runner.go()
        # Not found: the line says so with its next step, as before, the bar gone, and the steps stay under it as chips;
        # those that turned out not to apply (no songbook lists it) keep their places, skipped.
        wait_for(page, f"document.querySelector('{line} .progress').textContent", "Not on the sites·To-do page")
        assert page.js(f"document.querySelector('{line} .progress').classList.contains('barred')") is False
        wait_for(page, steps_of(line), [["done", "✓ Song"], ["plain", "Match · not on UG"],
                                        ["failed", "✕ Sheet LaCuerda"], ["skipped", "PDF"], ["done", "✓ Lyrics"],
                                        ["failed", "✕ Extras"], ["skipped", "Songbooks"]])
        assert page.js(f"getComputedStyle(document.querySelector('{line} .step-chips .plain')).borderTopStyle") == (
            "dashed")
        # Over, the view's count names the step that failed; the line, its outcome, shows none.
        assert page.js(f"document.querySelector('{line} .progress .step-count, {line} .progress .steps-over')") is None


@pytest.mark.parametrize("width", [1280, 390])
def test_a_search_results_get_it_shows_the_bar_in_its_row_then_the_song_as_yours(cfg, live, tmp_path, width):
    base, runner = live
    runner.script = FROM_UG
    sites(cfg, **WONDERWALL)
    with driven(tmp_path, width) as page:
        page.open(base)
        search(page, "wonderwall")
        assert page.wait(f"!!document.querySelector(\"{RYAN}\")")
        page.click(f"{RYAN} .line-action button")
        # Its request line in its Get it's place, a bar in the result's own row.
        row = RYAN
        wait_for(page, bar_of(row), ["done", "done", "running", "waiting", "waiting", "waiting", "waiting"])
        wait_for(page, words_of(row), ["Sheet · Ultimate Guitar", " · 3 of 7"])
        assert page.js(f"document.querySelector(\"{row} .step-chips\")") is None
        one_row(page, row)
        runner.go()
        wait_for(page, words_of(row), ["Lyrics", " · 5 of 7"])
        one_row(page, row)
        runner.go()
        # Over, and Ready: the row is the song's own line, yours, its sheet's button on it; no bar, no Ready · Open
        # sheet.
        line = "document.querySelector('#results .progress').closest('article')"
        assert page.wait(f"{line}.querySelector('.progress').dataset.tone === 'ready'", timeout=15)
        assert page.wait(f"!!{line}.querySelector('.line-plays a.play-sheet')")
        assert page.js(f"{line}.querySelector('h3').textContent") == "Wonderwall"
        assert page.js(f"{line}.querySelector('.step-segs, .step-chips')") is None
        assert page.js(f"{line}.querySelector('.progress a')") is None
        assert page.js(f"{line}.querySelector('.progress').getBoundingClientRect().height") <= 1
        assert page.js("document.documentElement.scrollWidth <= window.innerWidth")


SEEN = ("new MutationObserver(() => { if (document.querySelector('#list .step-segs, #list .steps')) "
        "window.barSeen = true; }).observe(document.getElementById('list'), {subtree: true, childList: true})")
TIMED = ("window.clicked = 0; window.barAt = 0; document.addEventListener('click', () => { "
         "if (!window.clicked) window.clicked = performance.now(); }, true); new MutationObserver(() => { "
         "if (!window.barAt && document.querySelector('#list .step-segs')) window.barAt = performance.now(); })"
         ".observe(document.getElementById('list'), {subtree: true, childList: true})")


def test_the_bar_comes_after_a_second_and_a_quick_request_draws_none(cfg, live, tmp_path, monkeypatch):
    base, runner = live
    conn = db.connect(cfg.db_path)
    quick = add_song(conn, "Estopa", "Tu Calorro")
    conn.close()
    held = creep(cfg)
    # Quick, with no hold: over within its first second (the server, in this process, waits half a minute for it, so
    # that a busy machine is no slower than that), its line drew no bar, nor any step.
    runner.script = [s for s in NOT_ON_UG if s is not HOLD]
    monkeypatch.setattr(outcome, "BAR_AFTER", timedelta(seconds=30))
    with driven(tmp_path, 1280) as page:
        page.open(base)
        page.js(SEEN)
        page.click(f"{line_of(quick)} form.fetch button")
        wait_for(page, f"document.querySelector('{line_of(quick)} .progress').textContent",
                 "Not on the sites·To-do page")
        assert page.js("window.barSeen") is not True
        # Held: the bar a second or more after Fetch, never before.
        monkeypatch.setattr(outcome, "BAR_AFTER", timedelta(seconds=1))
        runner.script = FROM_UG
        page.js(TIMED)
        page.click(f"{line_of(held)} form.fetch button")
        assert page.wait("window.barAt > 0", timeout=15)
        assert page.js("window.barAt - window.clicked") >= 950, page.js("[window.clicked, window.barAt]")


def test_the_running_segment_is_steady_under_reduced_motion(cfg, live, tmp_path):
    base, runner = live
    runner.script = FROM_UG
    line = line_of(creep(cfg))
    with driven(tmp_path, 1280) as page:
        page.send("Emulation.setEmulatedMedia", features=[{"name": "prefers-reduced-motion", "value": "reduce"}])
        page.open(base)
        page.click(f"{line} form.fetch button")
        assert page.wait(f"!!document.querySelector('{line} .seg.running')", timeout=15)
        running = f"getComputedStyle(document.querySelector('{line} .seg.running'))"
        assert page.js(f"{running}.animationName") == "none"
        assert page.js(f"{running}.opacity") == "0.5"
