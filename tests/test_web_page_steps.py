"""A lookup's steps on the library page caracole serve serves, in a real browser: a row of chips under the song's line.

While a song is looked up (Fetch now, a search result's Get it), its request line says what runs and how many steps
are over ("Fetching the lyrics from LRCLIB… · 4 of 7 done"), and under it each step is a chip (outcome.py's, as
/jobs.json gives them): those done ticked, the one that runs lit, those to come grey, Match naming the index it
matched in ("Match UG", or "Match: not on UG", plain) and Sheet the site it asks, then the one its sheet came from.
Ended Ready, they fold away and the line is the song's own, which opens its sheet; ended otherwise, they stay, to
show which step stopped. A real ``caracole serve`` answers on a socket with the page's timers quick
(``WebApp(timers=...)``), and its queue runs ``Staged``: ``caracole get --progress``'s lines, said a stage at a
time, stopping where the test says until it lets it go on.
"""

from __future__ import annotations

import json
import threading
from datetime import UTC, datetime

import pytest
from helpers.browser import CHROMIUM_MARKS, Browser, BrowserError
from test_web_page_search import RYAN, WONDERWALL, search, sites

from caracole import db
from caracole.get import MATCH_NOT_FOUND, NOT_IN_INDEX, PROGRESS_PREFIX, SHEET_FROM
from caracole.library import keep_file, song_dir
from caracole.overrides import override_key
from caracole.songs import find_song, update_song
from caracole.versions import upsert_version
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
                   stage("songbooks", "running"), stage("songbooks", "skipped", "no songbook lists it")]
# A song Ultimate Guitar has: its sheet from there; the test holds it while the sheet is asked for, then while the
# lyrics are.
FROM_UG = [stage("song", "running"), stage("song", "done", "in the library"), stage("match", "running"),
           stage("match", "done", "matched to it"), stage("sheet", "running"),
           stage("sheet", "running", SHEET_FROM["ug"]), HOLD, kept_from("ug"),
           stage("sheet", "done", "tab 1 from Ultimate Guitar"), stage("pdf", "running"), stage("pdf", "done", "made"),
           stage("lyrics", "running"), HOLD, *AFTER_THE_SHEET]
# A song Ultimate Guitar's index lacks, whose sheet LaCuerda fails to give: held while LaCuerda is asked.
LACUERDA_FAILS = "LaCuerda failed (lacuerda: 503: https://acordes.lacuerda.net/x: HTTP 503); the nightly run tries again"
NOT_ON_UG = [stage("song", "running"), stage("song", "done", "in the library"), stage("match", "running"),
             not_matched, stage("match", "done", MATCH_NOT_FOUND), stage("sheet", "running"),
             stage("sheet", "running", SHEET_FROM["lacuerda"]), HOLD, stage("sheet", "failed", LACUERDA_FAILS),
             stage("pdf", "running"), stage("pdf", "skipped", "no sheet yet"), stage("lyrics", "running"),
             stage("lyrics", "done", "found"), stage("ug", "running"), stage("ug", "skipped", NOT_IN_INDEX),
             stage("lacuerda", "running"), stage("lacuerda", "failed", "asked already, for the sheet: " + LACUERDA_FAILS),
             stage("gtptabs", "running"), stage("gtptabs", "skipped", "no file wanted"), stage("pages", "running"),
             stage("pages", "done", ""), stage("songbooks", "running"), stage("songbooks", "skipped", "no songbook")]


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


def steps_of(item: str) -> str:
    """The expression for the chips under ``item`` (a selector): each one's state and its words as shown (its mark,
    its name, its site), what a screen reader alone hears left out."""
    return (f"[...document.querySelectorAll({json.dumps(item + ' .step-chips > li')})].map((c) => {{ "
            "const shown = c.cloneNode(true); shown.querySelectorAll('.visually-hidden').forEach((n) => n.remove()); "
            "return [c.className.replace('step-chip ', ''), shown.textContent]; })")


def said(item: str) -> str:
    """The expression for ``item``'s request line, as [its words, its count of steps over, if it shows one]."""
    p = f"document.querySelector({json.dumps(item + ' .progress')})"
    over = f"{p}.querySelector('.steps-over')"
    return f"[{p}.firstChild.textContent, {over} && {over}.getBoundingClientRect().width > 0 ? {over}.textContent : '']"


def fits(page: Browser, item: str) -> None:
    """No page wider than the screen, and every chip within ``item``'s line."""
    assert page.js("document.documentElement.scrollWidth <= window.innerWidth"), page.js(
        "[document.documentElement.scrollWidth, window.innerWidth]")
    over = page.js(f"(() => {{ const line = document.querySelector({json.dumps(item)}).getBoundingClientRect(); "
                   f"return [...document.querySelectorAll({json.dumps(item + ' .step-chips > li')})]"
                   ".filter((c) => c.getBoundingClientRect().right > line.right + 0.5).length; })()")
    assert over == 0


def wait_for(page: Browser, expression: str, expected, timeout: float = 15.0) -> None:
    """Wait until ``expression`` is ``expected``, as JSON says them."""
    shown = json.dumps(expected, separators=(",", ":"), ensure_ascii=False)  # as JSON.stringify writes it
    assert page.wait(f"JSON.stringify({expression}) === {json.dumps(shown)}", timeout=timeout), page.js(expression)


WAITING = [["waiting", "PDF"], ["waiting", "Lyrics"], ["waiting", "Extras"], ["waiting", "Songbooks"]]


@pytest.mark.parametrize("width", [1280, 390])
def test_a_songs_line_shows_its_lookups_steps_ticking_then_folds_them_away_once_ready(cfg, live, tmp_path, width):
    base, runner = live
    runner.script = FROM_UG
    conn = db.connect(cfg.db_path)
    creep = add_song(conn, "Radiohead", "Creep")
    update_song(conn, creep.id, match_decision="accept", match_artist_key="radiohead", match_song_key="creep")
    conn.close()
    line = f'#list article.line[data-id="{creep.id}"]'
    with driven(tmp_path, width) as page:
        page.open(base)
        page.click(f"{line} form.fetch button")
        # Asking Ultimate Guitar for the sheet: the song and its match over, the sheet lit with its site.
        wait_for(page, steps_of(line), [["done", "✓ Song"], ["done", "✓ Match UG"], ["running", "Sheet UG"],
                                        *WAITING])
        wait_for(page, said(line), ["Fetching from Ultimate Guitar…", "2 of 7 done"])
        fits(page, line)
        runner.go()
        # The sheet kept, from Ultimate Guitar, and its PDF: the lyrics now, four of seven over.
        wait_for(page, steps_of(line), [["done", "✓ Song"], ["done", "✓ Match UG"], ["done", "✓ Sheet UG"],
                                        ["done", "✓ PDF"], ["running", "Lyrics"], ["waiting", "Extras"],
                                        ["waiting", "Songbooks"]])
        wait_for(page, said(line), ["Fetching the lyrics from LRCLIB…", "4 of 7 done"])
        assert page.js(f"document.querySelector('{line} .step-chips').getAttribute('aria-label')") == "Steps"
        assert page.js(f"document.querySelector('{line} .step-chips [aria-current=step]').textContent") == (
            "Lyrics: running")
        fits(page, line)
        runner.go()
        # Ready: the chips fold away and nothing takes their place; the line is the song's, found, its Open opening
        # its sheet. Its request line says Ready to a screen reader alone, which hears the request end.
        assert page.wait(f"document.querySelector('{line} .progress').dataset.tone === 'ready'", timeout=15)
        assert page.js(f"document.querySelector('{line} .step-chips')") is None
        assert page.js(f"document.querySelector('{line} .progress').textContent") == "Ready"
        assert page.js(f"document.querySelector('{line} .progress a')") is None  # no "Ready · Open sheet"
        assert page.js(f"document.querySelector('{line} .progress').getBoundingClientRect().height") <= 1
        assert page.js(f"document.querySelector('{line} .line-status .badge').textContent") == "Found"
        assert page.wait(f"document.querySelector('{line} .line-action a').textContent === 'Open PDF'")
        # The focus, on the request line since Fetch now, is on the Open that took Fetch now's place.
        assert page.js("document.activeElement.textContent") == "Open PDF"
        assert page.js(f"document.querySelector('{line}').contains(document.activeElement)")
        assert page.js("document.documentElement.scrollWidth <= window.innerWidth")


def test_a_lookup_that_ends_otherwise_keeps_its_steps_to_show_which_one_stopped(cfg, live, tmp_path):
    base, runner = live
    runner.script = NOT_ON_UG
    conn = db.connect(cfg.db_path)
    song = add_song(conn, "Estopa", "Tu Calorro")
    conn.close()
    line = f'#list article.line[data-id="{song.id}"]'
    with driven(tmp_path, 1280) as page:
        page.open(base)
        page.click(f"{line} form.fetch button")
        # The offline index lacks it, plainly: no failure, as the sheet is asked of LaCuerda.
        wait_for(page, steps_of(line), [["done", "✓ Song"], ["plain", "Match: not on UG"],
                                        ["running", "Sheet LaCuerda"], *WAITING])
        wait_for(page, said(line), ["Fetching from LaCuerda…", "2 of 7 done"])
        assert page.js(f"getComputedStyle(document.querySelector('{line} .step-chips .plain')).borderTopStyle") == (
            "dashed")
        runner.go()
        # Not found: the line says so with its next step, as before, and the steps stay; those that turned out not to
        # apply (no sheet, so no PDF; no songbook lists it) are gone.
        wait_for(page, f"document.querySelector('{line} .progress').textContent", "Not found·see the to-do page")
        wait_for(page, steps_of(line), [["done", "✓ Song"], ["plain", "Match: not on UG"],
                                        ["failed", "✕ Sheet LaCuerda"], ["done", "✓ Lyrics"], ["failed", "✕ Extras"]])
        assert page.js(f"!!document.querySelector('{line} .progress .steps-over')") is False  # over: no count


@pytest.mark.parametrize("width", [1280, 390])
def test_a_search_results_get_it_shows_the_steps_in_its_row_then_the_song_as_yours(cfg, live, tmp_path, width):
    base, runner = live
    runner.script = FROM_UG
    sites(cfg, **WONDERWALL)
    with driven(tmp_path, width) as page:
        page.open(base)
        search(page, "wonderwall")
        assert page.wait(f"!!document.querySelector(\"{RYAN}\")")
        page.click(f"{RYAN} .line-action button")
        # Its request line in its Get it's place, and the steps under it, in the result's own row.
        row = RYAN
        wait_for(page, steps_of(row), [["done", "✓ Song"], ["done", "✓ Match UG"], ["running", "Sheet UG"], *WAITING])
        wait_for(page, said(row), ["Fetching from Ultimate Guitar…", "2 of 7 done"])
        fits(page, row)
        runner.go()
        wait_for(page, said(row), ["Fetching the lyrics from LRCLIB…", "4 of 7 done"])
        fits(page, row)
        runner.go()
        # Over, and Ready: the row is the song's own line, yours, its Open its sheet's; no steps, no Ready · Open sheet.
        line = "document.querySelector('#results .progress').closest('article')"
        assert page.wait(f"{line}.querySelector('.progress').dataset.tone === 'ready'", timeout=15)
        assert page.wait(f"{line}.querySelector('.line-action a') && "
                         f"{line}.querySelector('.line-action a').textContent === 'Open PDF'")
        assert page.js(f"{line}.querySelector('h3').textContent") == "Wonderwall"
        assert page.js(f"{line}.querySelector('.step-chips')") is None
        assert page.js(f"{line}.querySelector('.progress a')") is None
        assert page.js(f"{line}.querySelector('.progress').getBoundingClientRect().height") <= 1
        assert page.js("document.documentElement.scrollWidth <= window.innerWidth")
