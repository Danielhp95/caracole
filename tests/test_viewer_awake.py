"""Keeping the screen on (screen.js's ``caracoleScreen.awake``, which viewer.js and harptab.js call): while a viewer
page shows, a screen wake lock until the minutes More's Keep the screen on sets have passed since the last touch, key
or scroll (10 by default, Off to 60 by 5), and always while autoscroll counts in and scrolls. The page asks for it
again when it shows again, and never through ``navigator.permissions.query``, which Android's WebView answers "denied"
while it grants the lock. ``html[data-awake="1"]`` while the page holds one.

The minutes are kept for every page as the theme is: localStorage ``caracole-viewer-awake``, and ``awake=`` in the
address while they aren't 10, which a link to another page of the song and a songbook's next song take on, so that
they hold where the browser keeps nothing (caracole serve's sandbox). The harmonica tab's page has no control of its
own and follows them.

Each page is opened with a wake lock that writes down what it is asked and long timers held back (helpers/
viewer_pages.py's ``WAKE_LOCK`` and ``LONG_TIMERS``): ``skip(ms)`` passes minutes in a moment.
"""

from __future__ import annotations

from caracole.viewer.book import BookSong, build_songbook

from helpers.browser import CHROMIUM_MARKS
from helpers.version_pages import WONDERWALL, folder
from helpers.viewer_pages import DENIED, LONG_TIMERS, NO_STORAGE, WAKE_LOCK, key, tap, viewer, written
from test_viewer_harptab_browser import tab, written as harmonica_written
from test_viewer_scroll import LONG

pytestmark = CHROMIUM_MARKS  # every test here opens a page in Chromium

FAKES = [WAKE_LOCK, LONG_TIMERS]
MINUTE = 60_000
HELD = "document.documentElement.dataset.awake === '1'"
READY = "document.documentElement.dataset.ready === '1'"
STATE = "document.getElementById('pill').dataset.state"
OTHER = LONG.replace("Long Song", "Other Song")

# The row as it says the minutes: its value, its ends, what the browser keeps ("refused" where it keeps nothing), the
# address, and whether the screen is kept on.
ROW = """(() => { const q = (id) => document.getElementById(id);
  let kept;
  try { kept = localStorage.getItem('caracole-viewer-awake'); } catch (err) { kept = 'refused'; }
  return {at: q('awake-at').textContent, down: q('awake-down').getAttribute('aria-disabled'),
    up: q('awake-up').getAttribute('aria-disabled'), kept, hash: location.hash,
    held: document.documentElement.dataset.awake === '1'}; })()"""


def wake_log(b) -> list[str]:
    return list(b.js("wakeLog"))


def held(b) -> bool:
    return b.js(HELD)


def more(b) -> None:
    b.click("#more")
    assert b.wait("!document.getElementById('panel').hidden")


def scrolling(b) -> None:
    """Autoscroll started from the bar, then pressed again: running, with no countdown."""
    b.click("#scroll")
    b.click("#go")
    assert b.wait(STATE + " === 'running'")


def test_the_screen_stays_on_ten_minutes_after_the_last_touch(tmp_path):
    with viewer(tmp_path, written(tmp_path, LONG), before=FAKES) as b:
        assert b.wait(HELD)
        opened = wake_log(b)
        b.js(f"skip(9 * {MINUTE})")
        nine = [wake_log(b), held(b)]
        tap(b, "#sheet .w")  # a touch: ten minutes from now
        b.js(f"skip(9 * {MINUTE})")
        later = [wake_log(b), held(b)]
        b.js("skip(61000)")
        gone = [wake_log(b), held(b)]
        key(b, "a", 65)  # a key: on again
        assert b.wait("wakeLog.length === 3 && " + HELD)
        back = wake_log(b)
    assert opened == ["request screen"]
    assert nine == [["request screen"], True] and later == [["request screen"], True]
    assert gone == [["request screen", "release"], False]
    assert back == ["request screen", "release", "request screen"]


def test_autoscroll_keeps_it_on_past_the_minutes(tmp_path):
    with viewer(tmp_path, written(tmp_path, LONG), before=FAKES) as b:
        assert b.wait(HELD)
        scrolling(b)
        b.js(f"skip(15 * {MINUTE})")
        running = [wake_log(b), held(b), b.js(STATE)]
        tap(b, "#sheet .w")  # a finger pauses it: ten minutes from now
        assert b.wait(STATE + " === 'paused'")
        paused = [wake_log(b), held(b)]
        b.js(f"skip(10 * {MINUTE} + 1000)")
        after = [wake_log(b), held(b)]
    assert running == [["request screen"], True, "running"]
    assert paused == [["request screen"], True]
    assert after == [["request screen", "release"], False]


def test_off_holds_it_only_while_it_scrolls(tmp_path):
    with viewer(tmp_path, written(tmp_path, LONG) + "#awake=0", before=FAKES) as b:
        log = [wake_log(b)]  # opened: nothing asked
        b.click("#scroll")
        log.append(wake_log(b))  # counting down
        b.click("#go")
        log.append(wake_log(b))  # scrolling: the same lock
        b.click("#go")
        log.append(wake_log(b))  # paused: the screen may sleep at once
        awake_paused = held(b)
        b.click("#go")
        b.click("#go")
        b.js("system()")  # the page was hidden, and the browser let go of the lock...
        b.js("document.dispatchEvent(new Event('visibilitychange'))")  # ...it shows again
        assert b.wait("wakeLog.length === 4")
        log.append(wake_log(b))
        b.click("#pill-end")
        log.append(wake_log(b))
        ended = held(b)
    assert log == [
        [],
        ["request screen"],
        ["request screen"],
        ["request screen", "release"],
        ["request screen", "release", "request screen", "request screen"],
        ["request screen", "release", "request screen", "request screen", "release"],
    ]
    assert awake_paused is False and ended is False


def test_hidden_and_shown_again_it_asks_again(tmp_path):
    hide = ("Object.defineProperty(document, 'visibilityState', {configurable: true, get: () => 'hidden'});"
            " document.dispatchEvent(new Event('visibilitychange'))")
    show = "delete document.visibilityState; document.dispatchEvent(new Event('visibilitychange'))"
    with viewer(tmp_path, written(tmp_path, LONG), before=FAKES) as b:
        assert b.wait(HELD)
        b.js("system()")  # the page hidden: the browser lets go of the lock
        let_go = held(b)
        b.js(hide)
        key(b, "a", 65)  # nothing is asked while it is hidden
        hidden = wake_log(b)
        b.js(show)
        assert b.wait("wakeLog.length === 2 && " + HELD)
        shown = wake_log(b)
    assert let_go is False and hidden == ["request screen"]
    assert shown == ["request screen", "request screen"]


def test_a_denied_permission_never_stops_it(tmp_path):
    with viewer(tmp_path, written(tmp_path, LONG), before=[*FAKES, DENIED]) as b:
        assert b.wait(HELD)
        scrolling(b)
        seen = [wake_log(b), held(b), b.js("queried")]
    assert seen == [["request screen"], True, 0]


def test_the_minutes_are_a_setting_kept_for_every_page(tmp_path):
    url, other = written(tmp_path, LONG), written(tmp_path, OTHER, name="Other")
    pages = folder(tmp_path, WONDERWALL, name="Wonderwall")
    with viewer(tmp_path, url, before=FAKES) as b:
        more(b)
        first = b.js(ROW)
        label = b.js("[document.getElementById('awake-lab').textContent,"
                     " document.getElementById('awake-down').getAttribute('aria-label'),"
                     " document.getElementById('awake-up').getAttribute('aria-label')]")
        b.click("#awake-up")
        fifteen = b.js(ROW)
        for _ in range(3):
            b.click("#awake-down")
        off = b.js(ROW)
        b.click("#awake-down")  # at Off: stays
        still = b.js(ROW)
        for _ in range(13):  # to 60, and once more
            b.click("#awake-up")
        most = b.js(ROW)
        for _ in range(9):
            b.click("#awake-down")
        b.click("#reset-all")
        reset = b.js(ROW)
        b.open(other)  # another song's page, its address naming none
        assert b.wait(READY + " && location.href.includes('Other')")
        more(b)
        elsewhere = b.js(ROW)
        b.open(pages["sheet.html"].as_uri())
        assert b.wait(READY)
        links = b.js("[...document.querySelectorAll('#version-list a[data-page]')].map((a) => a.getAttribute('href'))")
    assert label == ["Keep the screen on", "Fewer minutes", "More minutes"]
    assert first["at"] == "10 min" and first["down"] == first["up"] == "false" and first["kept"] is None
    assert "awake" not in first["hash"]
    assert fifteen["at"] == "15 min" and fifteen["kept"] == "15" and "awake=15" in fifteen["hash"]
    assert off["at"] == "Off" and off["down"] == "true" and off["kept"] == "0" and "awake=0" in off["hash"]
    assert fifteen["held"] and not off["held"]  # Off, not scrolling: the screen may sleep at once
    assert still["at"] == "Off" and still["kept"] == "0"
    assert most["at"] == "60 min" and most["up"] == "true" and most["kept"] == "60" and most["held"]
    assert reset["at"] == "15 min" and reset["kept"] == "15" and "awake=15" in reset["hash"]  # Reset all leaves it
    assert elsewhere["at"] == "15 min" and "awake=15" in elsewhere["hash"]
    assert links and all("awake=15" in link.split("#", 1)[1] for link in links), links


def test_ten_minutes_ride_in_no_address(tmp_path):
    with viewer(tmp_path, written(tmp_path, LONG) + "#awake=15", before=FAKES) as b:
        more(b)
        named = b.js(ROW)
        b.click("#awake-down")
        ten = b.js(ROW)
    assert named["at"] == "15 min" and "awake=15" in named["hash"]
    assert ten["at"] == "10 min" and "awake" not in ten["hash"] and ten["kept"] == "10"


def test_a_songbook_without_storage_carries_the_minutes_to_its_next_song(tmp_path):
    path = tmp_path / "Library" / "_songbooks" / "Campfire" / "songbook.html"
    path.parent.mkdir(parents=True)
    path.write_text(build_songbook("Campfire", [BookSong("Long Song", "Synthetic", cho=LONG, id="aaaa"),
                                                BookSong("Other Song", "Synthetic", cho=OTHER, id="bbbb")]),
                    encoding="utf-8")
    with viewer(tmp_path, path.as_uri() + "#song-1", before=[*FAKES, NO_STORAGE]) as b:
        assert b.wait(HELD)
        more(b)
        b.click("#awake-up")
        first = b.js(ROW)
        b.click("#panel [data-close]")
        assert b.wait("document.getElementById('panel').hidden")
        b.js("window.before = true")
        key(b, "ArrowRight", 39)
        assert b.wait(f"!window.before && location.hash.startsWith('#song-2') && {READY}")
        assert b.wait(HELD)
        more(b)
        second = b.js(ROW)
        b.js(f"skip(15 * {MINUTE} - 2000)")
        kept_on = held(b)
        b.js("skip(3000)")
        let_go = held(b)
    assert first["at"] == "15 min" and first["kept"] == "refused" and "awake=15" in first["hash"]
    assert second["at"] == "15 min" and "awake=15" in second["hash"]
    assert kept_on is True and let_go is False  # the song's page keeps it on as long


def test_the_harmonica_page_keeps_it_on_as_long(tmp_path):
    url = harmonica_written(tmp_path, tab("588_hotel-california"), back="sheet.html")
    with viewer(tmp_path, url + "#awake=5", before=FAKES) as b:
        assert b.wait(HELD)
        b.js(f"skip(4 * {MINUTE})")
        four = held(b)
        b.js(f"skip({MINUTE} + 1000)")
        five = [wake_log(b), held(b)]
        href = b.js("document.querySelector('a.back[data-sheet]').getAttribute('href')")
        hash_now = b.js("location.hash")
        scrolling(b)  # autoscroll holds it past the minutes, as on a sheet
        b.js(f"skip(6 * {MINUTE})")
        running = [wake_log(b), held(b), b.js(STATE)]
    assert four is True and five == [["request screen", "release"], False]
    assert "awake=5" in href.split("#", 1)[1] and "awake=5" in hash_now, (href, hash_now)
    assert running == [["request screen", "release", "request screen"], True, "running"]


# The row as it lies in the panel: within it, its words on one line and whole, the stepper's buttons a finger's, the
# stepper at the row's right on the words' line or under them, and the page no wider than the window.
FIT = """(() => { const q = (id) => document.getElementById(id), r = (id) => q(id).getBoundingClientRect();
  const row = r('awake-row'), panel = r('panel'), lab = r('awake-lab'), at = r('awake-at');
  const step = q('awake-row').querySelector('.stepper').getBoundingClientRect();
  const pad = parseFloat(getComputedStyle(q('awake-row')).paddingRight);
  return {inside: row.left >= panel.left && row.right <= panel.right + 0.5 && step.right <= row.right - pad + 0.5,
    right: Math.abs(step.right - (row.right - pad)) <= 1,
    oneLine: Math.abs((lab.top + lab.bottom) - (at.top + at.bottom)) <= 2,
    words: lab.height < 30 && q('awake-lab').scrollWidth <= q('awake-lab').clientWidth + 1
      && q('awake-at').scrollWidth <= q('awake-at').clientWidth + 1,
    sizes: ['awake-down', 'awake-up'].map((id) => Math.min(r(id).width, r(id).height)),
    page: document.documentElement.scrollWidth}; })()"""


def test_the_row_fits_a_320_px_phone(tmp_path):
    seen, widths = {}, []
    for width in (320, 360):
        with viewer(tmp_path, written(tmp_path, LONG), width=width, height=640, before=FAKES) as b:
            more(b)
            b.js("document.getElementById('awake-row').scrollIntoView({block: 'center'})")
            seen[width] = b.js(FIT)
            if width == 320:
                for clicks in (0, 2, 10):  # "10 min", "Off", "50 min": the stepper never changes its width
                    for _ in range(clicks):
                        b.click("#awake-down" if clicks == 2 else "#awake-up")
                    widths.append(b.js("document.querySelector('#awake-row .stepper').getBoundingClientRect().width"))
    for width, fit in seen.items():
        assert fit["inside"] and fit["right"] and fit["words"] and fit["page"] <= width, (width, fit)
        assert min(fit["sizes"]) >= 44, (width, fit)
    assert seen[360]["oneLine"], seen[360]  # a 360 px phone, the commonest narrow one: the words and the stepper
    assert len(set(widths)) == 1, widths
