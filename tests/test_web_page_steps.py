"""A lookup's steps on the library page caracole serve serves, in a real browser: a segmented bar on the song's line.

While a song is looked up (Fetch now, a search result's Get it), once its request has run a second (none before it,
outcome.py's ``BAR_AFTER``, so a quick one draws none), its request line is a bar of its steps (outcome.py's, as
/jobs.json gives them), a segment a step: those done in the accent, the one that runs at half, pulsing (steady where
motion is unwelcome), those to come grey, a skipped one an outline, a failed one red, taller, with its "!"; then the
step in hand, the site it names in full and its place among them all, "Sheet · Ultimate Guitar · 3 of 7", which is
what a screen reader hears, in one row on a laptop and a phone alike, the segments square at their ends.
Ended Ready, the bar folds away and the line is the song's own, which opens its sheet; ended otherwise, the line says
how, and the bar stays under it, frozen, to show which step stopped, each in its place, with the step that failed and
its place ("Sheet · LaCuerda · 3 of 7"). The song's card, open, lists the steps in the bar's place, one a line: each
one's mark (done and plain ✓, the one that runs ◐, those to come ○, a failed one !, a skipped one –), its name, its
site and what it found; once the request is over, the skipped ones fold into one last line, "Skipped: PDF,
Songbooks". A real ``caracole serve`` answers on a socket with the page's timers quick (``WebApp(timers=...)``), and
its queue runs ``Staged``: ``caracole get --progress``'s lines, said a stage at a time, stopping where the test says
until it lets it go on.
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

# A song whose lookup waits for the book (a nightly run holds caracole's lock, get.py's words) until the test lets it
# go on; then FROM_UG's, held as it asks Ultimate Guitar for the sheet.
WAITS_FOR_THE_BOOK = [stage("song", "running"),
                      stage("song", "running", "waiting for the book (pid 42: run); a fetch goes first at its next "
                                               "pause"), HOLD, *FROM_UG[1:]]


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
    """The expression for ``item``'s list of steps: each one's state, glyph, step and site, and what it found."""
    return (f"[...document.querySelectorAll({json.dumps(item + ' .steps > .step-list > li')})].map((li) => ["
            "li.className.replace('step ', ''), li.querySelector('.step-glyph').textContent, "
            "li.querySelector('.step-name') ? li.querySelector('.step-name').textContent : li.lastChild.textContent, "
            "(li.querySelector('.step-found') || {}).textContent || ''])")


def shown(item: str, part: str) -> str:
    """The expression for whether ``item``'s ``part`` (a selector under it) is drawn: there, and displayed."""
    return (f"(() => {{ const e = document.querySelector({json.dumps(item + ' ' + part)}); "
            "return !!e && getComputedStyle(e).display !== 'none'; })()")


def colour(var: str) -> str:
    """The expression for the colour ``var`` (a custom property of the page's) computes to: a probe's background."""
    return (f"(() => {{ const i = document.createElement('i'); i.style.background = 'var({var})'; "
            "document.body.appendChild(i); const c = getComputedStyle(i).backgroundColor; i.remove(); return c; })()")


ACCENT = colour("--accent")
FAILED = colour("--failed")


def one_row(page: Browser, item: str, bar: str = ".progress.barred") -> None:
    """``item``'s bar (its running one, else ``bar``) in one row: its segments and its count centred on one line, the
    count within ``item``'s line, and no page wider than the screen."""
    at = page.js(f"(() => {{ const item = document.querySelector({json.dumps(item)}); "
                 "const r = (s) => item.querySelector(s).getBoundingClientRect(); "
                 f"const segs = r('{bar} .step-segs'), count = r('{bar} .step-count'); "
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
        # No chips, nor any frozen bar: the list of steps waits under the line for its card to open, and takes no room
        # meanwhile.
        assert page.js(f"document.querySelector('{line} .step-chips, {line} .step-bar')") is None
        assert page.js(shown(line, ".step-list")) is False
        assert page.js(shown(line, ".steps")) is False
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
        assert page.js(f"document.querySelector('{line} .step-segs, {line} .steps, {line} .step-chips')") is None
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


def test_a_failed_step_is_red_on_the_running_bar_and_keeps_its_place(cfg, live, tmp_path):
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
        # Not found: the line says so with its next step, and the bar stays under it, frozen, each step in its place
        # (those that turned out not to apply, no songbook listing it, skipped); the line itself, its outcome, counts
        # nothing.
        wait_for(page, f"document.querySelector('{line} .progress').textContent", "Not on the sites·To-do page")
        assert page.js(f"document.querySelector('{line} .progress').classList.contains('barred')") is False
        wait_for(page, bar_of(line), ["done", "plain", "failed", "skipped", "done", "failed", "skipped"])
        assert page.js(f"document.querySelector('{line} .step-chips, {line} .progress .step-count')") is None


@pytest.mark.parametrize("width", [1024, 390])  # its card under its line (from 1200 px, in the pane: below)
def test_a_lookup_that_ends_otherwise_keeps_its_bar_frozen_under_its_line(cfg, live, tmp_path, width):
    base, runner = live
    runner.script = NOT_ON_UG
    conn = db.connect(cfg.db_path)
    song = add_song(conn, "Estopa", "Tu Calorro")
    conn.close()
    line = line_of(song)
    with driven(tmp_path, width) as page:
        page.open(base)
        page.click(f"{line} form.fetch button")
        wait_for(page, bar_of(line), ["done", "plain", "running"] + ["waiting"] * 4)
        wait_for(page, words_of(line), ["Sheet · LaCuerda", " · 3 of 7"])
        runner.go()
        # Not on the sites: its words, and under them the bar as the lookup left it, frozen, with the step that
        # failed first and its place; for a screen reader, a picture whose name says every step and how it ended.
        wait_for(page, f"document.querySelector('{line} .progress').textContent", "Not on the sites·To-do page")
        wait_for(page, bar_of(line), ["done", "plain", "failed", "skipped", "done", "failed", "skipped"])
        assert page.js(words_of(line)) == ["Sheet · LaCuerda", " · 3 of 7"]
        bar = f"document.querySelector('{line} .step-bar')"
        assert page.js(f"{bar}.getAttribute('role')") == "img"
        assert page.js(f"{bar}.getAttribute('aria-label')") == (
            "Steps: Song: done; Match · not on UG: done; Sheet, LaCuerda: failed; PDF: skipped; Lyrics: done; "
            "Extras: failed; Songbooks: skipped")
        assert page.js(f"document.querySelector('{line} .seg.failed').textContent") == "!"
        assert page.js(f"{bar}.parentNode.previousElementSibling === document.querySelector('{line} .progress')")
        assert page.js(f"{bar}.getBoundingClientRect().top >= "
                       f"document.querySelector('{line} .progress').getBoundingClientRect().bottom - 0.5")
        one_row(page, line, ".step-bar")
        assert page.js(shown(line, ".step-list")) is False
        page.click(f"{line} .line-more")  # the card open: the list in the bar's place
        assert page.js(shown(line, ".step-bar")) is False
        assert page.js(shown(line, ".step-list")) is True
        assert page.js(f"document.querySelector('{line} .step-list').getAttribute('aria-label')") == "Steps"
        # Each step a line, what it found beside it; over, those skipped fold into one last line.
        assert page.js(steps_of(line)) == [
            ["done", "✓", "Song", "in the book"], ["plain", "✓", "Match · not on UG", ""],
            ["failed", "!", "Sheet · LaCuerda", LACUERDA_FAILS], ["done", "✓", "Lyrics", "found"],
            ["failed", "!", "Extras", "asked already, for the sheet: " + LACUERDA_FAILS],
            ["skipped-all", "–", "Skipped: PDF, Songbooks", ""]]
        items = f"[...document.querySelectorAll('{line} .step-list > li')]"
        # What a screen reader hears of each: its state after its name (a plain one done), never the glyph.
        assert page.js(f"{items}.map((li) => (li.querySelector('.visually-hidden') || {{}}).textContent || '')") == [
            ": done", ": done", ": failed", ": done", ": failed", ""]
        assert page.js(f"{items}.every((li) => li.querySelector('.step-glyph').getAttribute('aria-hidden') === 'true')")
        assert page.js(f"document.querySelector('{line} .step-list .step-name b').textContent") == "Song"
        assert page.js(f"{items}.some((li) => li.hasAttribute('aria-current'))") is False  # none runs now
        glyph = f"getComputedStyle(document.querySelector('{line} .step.failed .step-glyph')).color"
        assert page.js(glyph) == page.js(FAILED)
        assert page.js("document.documentElement.scrollWidth <= window.innerWidth")
        page.click(f"{line} .line-more")  # closed again: the frozen bar back
        assert page.js(shown(line, ".step-bar")) is True
        assert page.js(shown(line, ".step-list")) is False


def test_on_a_laptop_the_selected_lines_steps_are_listed_in_the_pane(cfg, live, tmp_path):
    # From 1200 px a song's card is in the pane beside the list: its steps listed there, under its head, while its line
    # keeps its request's words and the bar as the lookup left it, frozen.
    base, runner = live
    runner.script = NOT_ON_UG
    conn = db.connect(cfg.db_path)
    song = add_song(conn, "Estopa", "Tu Calorro")
    conn.close()
    line = line_of(song)
    with driven(tmp_path, 1280) as page:
        page.open(base)
        page.click(f"{line} form.fetch button")
        wait_for(page, bar_of(line), ["done", "plain", "running"] + ["waiting"] * 4)
        runner.go()
        wait_for(page, f"document.querySelector('{line} .progress').textContent", "Not on the sites·To-do page")
        page.click(f"{line} .line-title h3")  # its card in the pane
        assert page.wait("Boolean(document.querySelector('#card-pane .song-card'))")
        assert page.js(shown("#card-pane", ".step-list")) is True
        assert page.js(steps_of("#card-pane")) == [
            ["done", "✓", "Song", "in the book"], ["plain", "✓", "Match · not on UG", ""],
            ["failed", "!", "Sheet · LaCuerda", LACUERDA_FAILS], ["done", "✓", "Lyrics", "found"],
            ["failed", "!", "Extras", "asked already, for the sheet: " + LACUERDA_FAILS],
            ["skipped-all", "–", "Skipped: PDF, Songbooks", ""]]
        assert page.js("document.querySelector('#card-pane .card-head').compareDocumentPosition("
                       "document.querySelector('#card-pane .step-list')) & Node.DOCUMENT_POSITION_FOLLOWING")
        assert page.js(shown(line, ".step-bar")) is True
        assert page.js(shown(line, ".step-list")) is False
        assert page.js("document.documentElement.scrollWidth <= window.innerWidth")
        page.click(f"{line} .line-more")  # closed: the pane holds no steps, the line its frozen bar
        assert page.wait("!document.querySelector('#card-pane .step-list')")
        assert page.js(shown(line, ".step-bar")) is True


def test_the_open_cards_list_follows_a_running_lookup_and_folds_away_once_ready(cfg, live, tmp_path):
    base, runner = live
    runner.script = FROM_UG
    line = line_of(creep(cfg))
    with driven(tmp_path, 1024) as page:  # its card under its line
        page.open(base)
        page.click(f"{line} .line-more")  # Creep's card open
        page.click(f"{line} .line-action form.fetch button")
        # Asking Ultimate Guitar for the sheet: the list says the step that runs, those before it ticked with what
        # they found, those to come waiting; the bar stays on the line's row, over the list.
        wait_for(page, steps_of(line), [
            ["done", "✓", "Song", "in the book"], ["done", "✓", "Match · Ultimate Guitar", "matched to it"],
            ["running", "◐", "Sheet · Ultimate Guitar", ""], ["waiting", "○", "PDF", ""], ["waiting", "○", "Lyrics", ""],
            ["waiting", "○", "Extras", ""], ["waiting", "○", "Songbooks", ""]])
        current = f"[...document.querySelectorAll('{line} .step-list > [aria-current]')]"
        assert page.js(f"{current}.map((li) => [li.getAttribute('aria-current'), li.className])") == [
            ["step", "step running"]]
        assert page.js(f"{current}[0].querySelector('.visually-hidden').textContent") == ": running"
        assert page.js(shown(line, ".progress.barred")) is True
        assert page.js(f"document.querySelector('{line} .step-bar')") is None
        assert page.js(f"document.querySelector('{line} .step-list').getBoundingClientRect().top >= "
                       f"document.querySelector('{line} .progress').getBoundingClientRect().bottom - 0.5")
        wait_for(page, words_of(line), ["Sheet · Ultimate Guitar", " · 3 of 7"])
        runner.go()
        # The sheet kept, from Ultimate Guitar, and what it found; the lyrics now.
        listed = steps_of(line)
        wait_for(page, f"(() => {{ const l = {listed}; return [l[2], l[4] && l[4][0]]; }})()",
                 [["done", "✓", "Sheet · Ultimate Guitar", "tab 1 from Ultimate Guitar"], "running"])
        runner.go()
        # Ready: the list folds away with the bar, as on a closed line; the card stays open.
        p = f"document.querySelector('{line} .progress')"
        assert page.wait(f"{p}.dataset.tone === 'ready'", timeout=15)
        assert page.wait(f"!document.querySelector('{line} .steps')", timeout=15)
        assert page.js(f"document.querySelector('{line} > .line-more').getAttribute('aria-expanded')") == "true"


def test_a_lookup_waiting_for_the_book_says_so_on_its_bar(cfg, live, tmp_path):
    base, runner = live
    runner.script = WAITS_FOR_THE_BOOK
    line = line_of(creep(cfg))
    with driven(tmp_path, 1280) as page:
        page.open(base)
        page.click(f"{line} .line-more")  # its card open, which lists the steps as the bar draws them
        page.click(f"{line} .line-action form.fetch button")
        # A nightly run holds the book: the bar says so in place of the step's name, its place kept, and the step in
        # hand drawn waiting, unlit and steady, as nothing moves.
        wait_for(page, bar_of(line), ["waiting"] * 7)
        wait_for(page, words_of(line), ["Waiting for the book", " · 1 of 7"])
        p = f"document.querySelector('{line} .progress')"
        assert page.js(f"{p}.textContent") == "Waiting for the book · 1 of 7"  # what a screen reader hears
        song = f"getComputedStyle(document.querySelector('{line} .seg'))"
        assert page.js(f"{song}.animationName") == "none"
        assert page.js(f"{song}.backgroundColor") != page.js(ACCENT)
        # The card's list the same: Song waiting, no step running.
        wait_for(page, f"{steps_of(line)}[0]", ["waiting", "○", "Song", ""])
        assert page.js(f"document.querySelector('{line} .step-list > [aria-current]')") is None
        runner.go()
        # The book its own: the song found, the sheet asked of Ultimate Guitar, the step's name again.
        wait_for(page, bar_of(line), ["done", "done", "running", "waiting", "waiting", "waiting", "waiting"])
        wait_for(page, words_of(line), ["Sheet · Ultimate Guitar", " · 3 of 7"])
        wait_for(page, f"{steps_of(line)}[2]", ["running", "◐", "Sheet · Ultimate Guitar", ""])


@pytest.mark.parametrize("width", [1280, 390])
def test_a_queued_request_says_its_place_with_cancel_beside_it(cfg, live, tmp_path, width):
    base, runner = live
    runner.script = FROM_UG
    creep_line = line_of(creep(cfg))
    conn = db.connect(cfg.db_path)
    try:
        wonder = add_song(conn, "Oasis", "Wonderwall")
    finally:
        conn.close()
    wonderwall = line_of(wonder)
    with driven(tmp_path, width) as page:
        page.open(base)
        page.click(f"{creep_line} .line-more")
        page.click(f"{creep_line} .line-action form.fetch button")
        wait_for(page, bar_of(creep_line), ["done", "done", "running", "waiting", "waiting", "waiting", "waiting"])
        page.click(f"{wonderwall} .line-more")
        page.click(f"{wonderwall} .line-action form.fetch button")
        # Behind Creep's lookup, held at its sheet: its place, and Cancel beside it.
        wait_for(page, f"document.querySelector('{wonderwall} .progress').textContent",
                 "Queued · 1 request ahead…·Cancel")
        button = f"{wonderwall} .progress button.cancel"
        assert page.js(f"document.querySelector('{button}').getAttribute('aria-label')") == "Cancel Oasis - Wonderwall"
        if width < 500:  # a touch screen: a target of 44 px at least
            box = page.js(f"(() => {{ const r = document.querySelector('{button}').getBoundingClientRect(); "
                          "return [r.width, r.height]; })()")
            assert box[1] >= 44 and box[0] >= 44, box
        page.click(button)
        wait_for(page, f"document.querySelector('{wonderwall} .progress').textContent", "Cancelled")
        assert page.wait(f"!!document.querySelector('{wonderwall} form.fetch button')")  # its Fetch is back
        assert page.js(bar_of(creep_line))[2] == "running"  # the one that runs is never stopped
        assert page.js("document.documentElement.scrollWidth <= window.innerWidth")
        runner.go()
        runner.go()


def _queued_behind_creep(cfg, runner, page, base):
    """Creep looked up and held; Wonderwall's Fetch queued behind it. Returns Wonderwall's line selector."""
    runner.script = FROM_UG
    creep_line = line_of(creep(cfg))
    conn = db.connect(cfg.db_path)
    try:
        wonder = add_song(conn, "Oasis", "Wonderwall")
    finally:
        conn.close()
    wonderwall = line_of(wonder)
    page.open(base)
    page.click(f"{creep_line} .line-more")
    page.click(f"{creep_line} .line-action form.fetch button")
    wait_for(page, bar_of(creep_line), ["done", "done", "running", "waiting", "waiting", "waiting", "waiting"])
    page.click(f"{wonderwall} .line-more")
    page.click(f"{wonderwall} .line-action form.fetch button")
    wait_for(page, f"document.querySelector('{wonderwall} .progress').textContent",
             "Queued · 1 request ahead…·Cancel")
    return wonderwall


def test_cancel_touches_no_neighbouring_target_and_stays_in_its_line(cfg, live, tmp_path):
    base, runner = live
    with driven(tmp_path, 390) as page:
        wonderwall = _queued_behind_creep(cfg, runner, page, base)
        # Cancel's box meets no line's play tiles or chevron (every line's, its own too), and lies in its own line.
        clashes = page.js("(() => { const b = document.querySelector("
                          f"'{wonderwall} .progress button.cancel').getBoundingClientRect(); "
                          "const hit = (r) => r.left < b.right && b.left < r.right && r.top < b.bottom && b.top < r.bottom; "
                          "return [...document.querySelectorAll('#list .line-plays > *, #list .line-more')]"
                          ".filter((e) => e.getClientRects().length && hit(e.getBoundingClientRect()))"
                          ".map((e) => e.className); })()")
        assert clashes == [], clashes
        inside = page.js("(() => { const b = document.querySelector("
                         f"'{wonderwall} .progress button.cancel').getBoundingClientRect(); "
                         f"const l = document.querySelector('{wonderwall}').getBoundingClientRect(); "
                         "return b.top >= l.top - 0.5 && b.bottom <= l.bottom + 0.5; })()")
        assert inside
        runner.go()
        runner.go()


@pytest.mark.parametrize("refusal", ["409", "none"])
def test_a_cancel_the_server_refuses_or_never_answers_says_so_and_leaves_no_dead_button(cfg, live, tmp_path, refusal):
    base, runner = live
    with driven(tmp_path, 1280) as page:
        wonderwall = _queued_behind_creep(cfg, runner, page, base)
        answer = ("Promise.resolve(new Response(JSON.stringify({error: 'Already over: nothing to cancel.'}), "
                  "{status: 409}))" if refusal == "409" else "Promise.reject(new TypeError('offline'))")
        page.js("(() => { const real = window.fetch; window.fetch = (u, o) => String(u).includes('/jobs/cancel') ? "
                f"{answer} : real(u, o); return true; }})()")
        # The poll draws the queued line again within 100 ms: watch every text the line takes.
        page.js("(() => { window.texts = []; const p = document.querySelector("
                f"'{wonderwall} .progress'); new MutationObserver(() => window.texts.push(p.textContent))"
                ".observe(p, {subtree: true, childList: true, characterData: true}); return true; })()")
        page.click(f"{wonderwall} .progress button.cancel")
        said = ("Already over: nothing to cancel." if refusal == "409"
                else "No answer from caracole serve. Is it running?")
        assert page.wait(f"window.texts.includes({json.dumps(said)})"), page.js("window.texts")
        # The next view of the job draws its queued line again, with a Cancel that works.
        wait_for(page, f"document.querySelector('{wonderwall} .progress').textContent",
                 "Queued · 1 request ahead…·Cancel")
        assert page.js(f"document.querySelector('{wonderwall} .progress button.cancel').disabled") is False
        # While it said so, no button was left on the line (a dead, disabled one).
        assert all("Cancel" not in t for t in page.js("window.texts") if t == said)
        runner.go()
        runner.go()


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
        assert page.js(f"document.querySelector(\"{row} .step-chips, {row} .step-bar\")") is None
        assert page.js(shown(row, ".step-list")) is False  # a row has no card to list them in
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
        assert page.js(f"{line}.querySelector('.step-segs, .steps, .step-chips')") is None
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
