"""caracole.viewer: scrolling by itself (viewer.js), steered from a pill while it runs.

The tests that watch it scroll run in a Chromium of their own on real time (helpers/browser.py's
``Browser``): a page loaded on virtual time draws no frames, and the scroll moves on each frame.
"""

from __future__ import annotations

import http.server
import json
import re
import tempfile
import threading
import time
from contextlib import contextmanager
from html import unescape
from pathlib import Path

from helpers import browser
from helpers.browser import Browser, in_chromium

from caracole.viewer import build_viewer, viewer_csp

LONG = "{title: Long Song}\n{artist: Synthetic}\n" + "".join(
    f"[G]Synthetic line [D]number {n} [Em]made up to [C]scroll by\n" for n in range(160))

# What the pill shows: whether it and the bar are there, what its first button says and
# shows (the countdown's ring and number, ❚❚ or ▶), the speed, and where the page is.
LOOK = """(() => {
  const q = (s) => document.querySelector(s);
  const shown = (el) => Boolean(el) && el.getClientRects().length > 0;
  const go = q("#go");
  return {pill: shown(q("#pill")), bar: shown(q("#bar")), go: go.getAttribute("aria-label"),
          icons: [...go.children].filter(shown).map((el) => el.getAttribute("class")),
          tick: q("#tick").textContent, speed: q("#pill-speed").textContent,
          y: Math.round(scrollY), hash: location.hash, focus: document.activeElement ? document.activeElement.id : "",
          status: q("#scroll-status").textContent, inert: q("#pill").inert};
})()"""

# Every scrollTo the page makes, with when; scrollBy calls too, which it should never make.
RECORD = """(() => {
  window.moves = [];
  window.bys = [];
  const to = window.scrollTo.bind(window), by = window.scrollBy.bind(window);
  window.scrollTo = (x, y) => { moves.push([performance.now(), y]); to(x, y); };
  window.scrollBy = (x, y) => { bys.push(y); by(x, y); };
})()"""

# As WebKit does at a zoom other than 100 % (bug 281786): a scroll lands on whole device pixels
# only, here every second CSS pixel, so a step of one pixel from where the page is never moves it.
EVEN_PIXELS = """(() => {
  window.moves = [];
  window.bys = [];
  const to = window.scrollTo.bind(window);
  window.scrollTo = (x, y) => { moves.push([performance.now(), y]); to(x, Math.floor(y / 2) * 2); };
  window.scrollBy = (x, y) => { bys.push(y); to(x, Math.floor((scrollY + y) / 2) * 2); };
})()"""

# A screen wake lock that writes down what it is asked; ``system()`` lets go of the lock as a
# browser does when the page is hidden.
WAKE_LOCK = """(() => {
  window.wakeLog = [];
  let held = null;
  window.system = () => { if (held) { held.released = true; held.dispatchEvent(new Event("release")); held = null; } };
  Object.defineProperty(navigator, "wakeLock", { configurable: true, value: { request(type) {
    wakeLog.push("request " + type);
    const lock = new EventTarget();
    lock.type = type;
    lock.released = false;
    lock.release = () => {
      if (!lock.released) { lock.released = true; wakeLog.push("release"); lock.dispatchEvent(new Event("release")); }
      if (held === lock) held = null;
      return Promise.resolve();
    };
    held = lock;
    return Promise.resolve(lock);
  } } });
})()"""


def written(tmp_path: Path, cho: str = LONG, name: str = "Title") -> str:
    page = tmp_path / "Artist" / name / "sheet.html"
    page.parent.mkdir(parents=True, exist_ok=True)
    page.write_text(build_viewer(cho), encoding="utf-8")
    return page.as_uri()


@contextmanager
def viewer(tmp_path: Path, url: str | None = None, *, width: int = 390, height: int = 844, mobile: bool = True,
           reduced: bool = False):
    """The viewer at ``url`` (a long sheet's, by default) in a Chromium of its own, once its script ran."""
    url = url or written(tmp_path)
    with Browser(Path(tempfile.mkdtemp(prefix="profile-", dir=tmp_path)), width=width, height=height,
                 mobile=mobile) as b:
        if reduced:
            b.send("Emulation.setEmulatedMedia", features=[{"name": "prefers-reduced-motion", "value": "reduce"}])
        b.open(url)
        assert b.wait("document.documentElement.dataset.ready === '1'")
        yield b


def look(b: Browser) -> dict:
    return b.js(LOOK)


def start_now(b: Browser) -> None:
    """Start from the bar, then press again: no countdown."""
    b.click("#scroll")
    b.click("#go")
    assert look(b)["go"] == "Pause"


def tap(b: Browser, selector: str) -> None:
    """A finger on the middle of the first element ``selector`` finds in view (clear of the pill, at
    the bottom, for the sheet's), without scrolling to it."""
    clear = 120 if selector.startswith("#sheet") else 0
    box = b.js(f"""(() => {{
      const el = [...document.querySelectorAll({json.dumps(selector)})].find((e) => {{
        const r = e.getBoundingClientRect(); return r.width && r.top >= 0 && r.bottom <= innerHeight - {clear}; }});
      if (!el) return null;
      const r = el.getBoundingClientRect(); return [r.x + r.width / 2, r.y + r.height / 2]; }})()""")
    assert box, f"nothing in view is {selector}"
    b.send("Input.dispatchTouchEvent", type="touchStart", touchPoints=[{"x": box[0], "y": box[1]}])
    b.send("Input.dispatchTouchEvent", type="touchEnd", touchPoints=[])


def key(b: Browser, name: str, code: int) -> None:
    for kind in ("keyDown", "keyUp"):
        b.send("Input.dispatchKeyEvent", type=kind, key=name, code=name, windowsVirtualKeyCode=code)


def moved_since(b: Browser, y: int, wait: float = 0.5) -> bool:
    time.sleep(wait)
    return look(b)["y"] > y


# --- the page as written ---------------------------------------------------------------------------


def test_the_pill_is_on_the_page_hidden_until_scrolling_starts():
    html = build_viewer(LONG)
    pill = re.search(r'<div class="pill" id="pill"([^>]*)>(.*?)</div>', html, re.S)
    assert pill, "no pill"
    attrs, inside = pill.groups()
    assert " hidden" in attrs and 'role="group"' in attrs and 'aria-label="Scrolling by itself"' in attrs
    assert re.findall(r'<button type="button"[^>]*id="([^"]+)"[^>]*aria-label="([^"]*)"', inside) == [
        ("go", "Pause"), ("pill-slower", "Slower"), ("pill-faster", "Faster"), ("pill-end", "Stop scrolling")]
    assert '<output id="pill-speed">6</output>' in inside
    # A live region outside the pill, there before it shows, says when it starts and stops.
    assert re.search(r'<p class="vh" id="scroll-status" role="status"></p>', html)
    # ▶ in the bar starts it; the pill's − and + set the speed, a number: no slider without one.
    assert re.search(r'<button type="button" class="tool play" id="scroll" aria-label="Scroll by itself">', html)
    assert 'id="speed"' not in html and 'type="range"' not in html


# --- what the page keeps ---------------------------------------------------------------------------


def run_in_page(html: str, tmp_path: Path, body: str, fragment: str = "") -> object:
    """What ``body`` (JavaScript run once the page's own script ran) sets ``out`` to, in Chromium."""
    script = ("<script>\nwindow.addEventListener(\"load\", () => {\n"
              "const q = (s) => document.querySelector(s);\nlet out;\n" + body
              + "\ndocument.body.dataset.result = JSON.stringify(out);\n});\n</script>\n")
    html = re.sub(r'<meta http-equiv="Content-Security-Policy"[^>]*>\n', "", html)
    page = tmp_path / "Artist" / "Title" / "sheet.html"
    page.parent.mkdir(parents=True, exist_ok=True)
    page.write_text(html.replace("</body>", script + "</body>"), encoding="utf-8")
    dom = browser.dump_dom(page.as_uri() + fragment, (390, 844))
    found = re.search(r'data-result="([^"]*)"', dom)
    assert found, "the harness didn't run"
    return json.loads(unescape(found.group(1)))


@in_chromium
def test_the_address_and_the_browser_keep_the_scroll_speed(tmp_path):
    # Like t, mode, capo and fs: in the address (speed=) where the page has no storage, and in
    # the browser's storage for each song where it has some.
    hashes, kept = run_in_page(build_viewer(LONG), tmp_path, """
      const seen = [location.hash];
      q("#scroll").click();
      q("#pill-faster").click();
      q("#pill-faster").click();
      q("#pill-end").click();
      seen.push(location.hash, q("#pill-speed").textContent);
      q("#size").click();
      q("#bigger").click();
      seen.push(location.hash);
      const saved = JSON.parse(localStorage.getItem("caracole-viewer:" + location.pathname));
      out = [seen, [saved.speed, saved.fs]];
    """)
    assert hashes == ["", "#speed=8", "8", "#speed=8&fs=20"]
    assert kept == [8, 20]

    read = run_in_page(build_viewer(LONG), tmp_path, """
      out = [q("#pill-speed").textContent, location.hash];
    """, "#t=1&speed=11")
    assert read == ["11", "#t=1&speed=11"]

    # Nothing the page can't do: a speed out of range is the page's own.
    for fragment in ("#speed=0", "#speed=31", "#speed=fast"):
        odd = run_in_page(build_viewer(LONG), tmp_path, 'out = [q("#pill-speed").textContent, location.hash];', fragment)
        assert odd == ["6", ""], fragment


@in_chromium
def test_served_in_a_sandbox_a_reload_keeps_the_speed(tmp_path):
    page = build_viewer(LONG).encode("utf-8")

    class Server(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Security-Policy", viewer_csp(page))
            self.end_headers()
            self.wfile.write(page)

        def log_message(self, *args):
            pass

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Server)
    threading.Thread(target=server.serve_forever, args=(0.01,), daemon=True).start()
    try:
        dom = browser.dump_dom(f"http://127.0.0.1:{server.server_port}/Artist/Title/sheet.html#fs=22&speed=9",
                               (390, 844))
    finally:
        server.shutdown()
        server.server_close()
    assert 'data-ready="1"' in dom  # its script ran, with no storage
    assert '<output id="pill-speed">9</output>' in dom
    assert re.search(r'<html[^>]*style="--fs: 22px;"', dom)  # and the text size beside it


# --- scrolling, in real time -------------------------------------------------------------------------


@in_chromium
def test_it_starts_three_seconds_after_start_or_at_once_when_pressed_again(tmp_path):
    with viewer(tmp_path) as b:
        b.js(RECORD)
        b.click("#scroll")
        pressed = b.js("performance.now()")
        counting = look(b)
        ring = b.js("getComputedStyle(document.querySelector('#go .ring .bar')).animationName")
        time.sleep(1.2)
        later = look(b)
        assert b.wait("document.querySelector('#go').getAttribute('aria-label') === 'Pause'", 5)
        assert b.wait("moves.length > 0", 2)
        first = b.js("moves[0][0]")
        running = look(b)

        b.click("#pill-end")
        b.js("moves.length = 0")
        b.click("#scroll")
        b.click("#go")  # pressed again: no waiting
        again = b.js("performance.now()")
        assert b.wait("moves.length > 0", 1)
        soon = b.js("moves[0][0]") - again

    # The pill takes the bar's place, counting down on its first button, which has the focus:
    # press it again to start at once.
    assert counting["pill"] and not counting["bar"] and counting["focus"] == "go"
    assert counting["go"] == "Start now" and counting["tick"] == "3" and counting["icons"] == ["ring", "tick"]
    assert counting["status"] == "Scrolling in 3 seconds" and counting["y"] == 0
    assert ring == "drain"  # the ring empties as the seconds pass
    assert later["tick"] == "2" and later["y"] == 0
    assert 2900 <= first - pressed <= 4000
    assert running["icons"] == ["i-pause"] and running["status"] == "Scrolling"
    assert soon < 500


@in_chromium
def test_the_pill_steers_the_scroll_without_stopping_it(tmp_path):
    with viewer(tmp_path, width=1280, height=800, mobile=False) as b:
        start_now(b)
        time.sleep(0.3)
        for button in ("#pill-faster", "#pill-faster", "#pill-faster", "#pill-slower"):
            b.click(button)
        faster = look(b)
        assert moved_since(b, faster["y"])  # still scrolling

        b.click("#go")
        paused = look(b)
        time.sleep(0.4)
        still = look(b)["y"]
        b.click("#go")
        resumed = look(b)
        b.click("#go")
        assert moved_since(b, look(b)["y"])

        # A chord's card covers the pill: the scroll waits, and the pill is out of reach behind it.
        b.js("""[...document.querySelectorAll('#sheet .c')].find((c) => c.getBoundingClientRect().top > 100).click()""")
        card = look(b)
        b.press("Escape")
        after_card = look(b)

        b.click("#pill-end")
        ended = look(b)
        time.sleep(0.3)
        ended_still = look(b)["y"] == ended["y"]
        b.js("location.reload()")
        assert b.wait("document.documentElement.dataset.ready === '1'")
        reloaded = look(b)

    assert faster["go"] == "Pause" and faster["speed"] == "8"
    assert faster["hash"] == "#speed=8"
    assert paused["go"] == "Resume" and paused["icons"] == ["i-play"] and paused["pill"]
    assert paused["status"] == "Paused" and still == paused["y"]
    assert resumed["go"] == "Start now" and resumed["tick"] == "3"  # a countdown again, to get your hands back
    assert card["go"] == "Resume" and card["inert"]
    assert after_card["pill"] and not after_card["inert"] and after_card["go"] == "Resume"
    assert not ended["pill"] and ended["bar"] and ended["focus"] == "scroll" and ended_still
    assert ended["status"] == ""
    assert reloaded["speed"] == "8" and not reloaded["pill"]  # kept; it doesn't start by itself


@in_chromium
def test_a_touch_a_wheel_a_key_or_a_scroll_by_hand_pauses_and_keeps_the_pill(tmp_path):
    with viewer(tmp_path) as b:
        start_now(b)
        time.sleep(0.3)
        tap(b, "#pill-faster")  # the pill's own buttons steer it, a finger on them pauses nothing
        steered = look(b)
        tap(b, "#sheet .w")
        touched = look(b)

        b.click("#go")
        b.click("#go")
        b.send("Input.dispatchMouseEvent", type="mouseWheel", x=195, y=400, deltaX=0, deltaY=120)
        wheeled = b.wait("document.querySelector('#go').getAttribute('aria-label') === 'Resume'", 2)

        b.click("#go")
        b.click("#go")
        key(b, "PageDown", 34)  # with the focus on the pill's button, which scrolls the page all the same
        keyed = look(b)

        b.click("#go")
        b.click("#go")
        b.js("window.scrollTo(0, scrollY + 300)")  # a scroll bar dragged, a search in the page
        by_hand = b.wait("document.querySelector('#go').getAttribute('aria-label') === 'Resume'", 2)

        b.click("#go")  # the countdown waits for no touch either
        tap(b, "#sheet .w")
        counting_touched = look(b)

    assert steered["go"] == "Pause" and steered["speed"] == "7"
    assert touched["go"] == "Resume" and touched["pill"] and touched["icons"] == ["i-play"]
    assert wheeled and keyed["go"] == "Resume" and by_hand
    assert counting_touched["go"] == "Resume" and counting_touched["tick"] == ""


@in_chromium
def test_it_scrolls_to_rounded_targets_so_no_step_is_lost_at_a_zoom(tmp_path):
    # Speed 30 is 60 px a second at the usual text size, and a bigger text scrolls faster in
    # step with it: the same speed keeps the same pace through the song.
    rates = []
    for name, fragment, expected in (("Usual", "#speed=30", 60), ("Bigger", "#speed=30&fs=24", 80)):
        with viewer(tmp_path, written(tmp_path, name=name) + fragment) as b:
            b.js(EVEN_PIXELS)
            start_now(b)
            time.sleep(1.5)
            b.click("#go")
            moves, bys, y = b.js("[moves, bys, scrollY]")
        assert bys == []  # never a step from where the page is
        ys = [m[1] for m in moves]
        assert all(isinstance(v, int) for v in ys)  # whole pixels, counted from where it began...
        assert all(a2 <= b2 for a2, b2 in zip(ys, ys[1:])) and ys[-1] - ys[0] > 50
        assert y >= ys[-1] - 2  # ...and the page went there, two pixels at a time
        rates.append((ys[-1] - ys[0]) / (moves[-1][0] - moves[0][0]) * 1000 / expected)
    assert all(0.75 <= r <= 1.15 for r in rates), rates


@in_chromium
def test_the_screen_stays_on_while_it_scrolls(tmp_path):
    with viewer(tmp_path) as b:
        b.js(WAKE_LOCK)
        b.click("#scroll")
        log = [list(b.js("wakeLog"))]  # counting down
        b.click("#go")
        log.append(list(b.js("wakeLog")))  # scrolling: the same lock
        b.click("#go")
        log.append(list(b.js("wakeLog")))  # paused: the screen may sleep
        b.click("#go")
        b.click("#go")
        b.js("system()")  # the page was hidden, and the browser let go of the lock...
        b.js("document.dispatchEvent(new Event('visibilitychange'))")  # ...it shows again
        assert b.wait("wakeLog.length === 4")
        log.append(list(b.js("wakeLog")))
        b.click("#pill-end")
        log.append(list(b.js("wakeLog")))
    assert log == [
        ["request screen"],
        ["request screen"],
        ["request screen", "release"],
        ["request screen", "release", "request screen", "request screen"],
        ["request screen", "release", "request screen", "request screen", "release"],
    ]


@in_chromium
def test_the_pill_fits_a_phone_and_a_desktop_and_holds_still(tmp_path):
    box = """(() => { const r = document.querySelector('#pill').getBoundingClientRect();
      return [r.left, r.top, r.width, r.height].map(Math.round); })()"""
    sizes = """[...document.querySelectorAll('#pill button')].map((e) => {
      const r = e.getBoundingClientRect(); return Math.min(r.width, r.height); })"""
    room = """(() => { const r = document.querySelector('#pill').getBoundingClientRect();
      return r.left >= 0 && r.right <= innerWidth && r.bottom <= innerHeight
        && document.documentElement.scrollWidth <= innerWidth; })()"""
    for width, height, mobile in ((390, 844, True), (1280, 800, False)):
        with viewer(tmp_path, width=width, height=height, mobile=mobile) as b:
            b.click("#scroll")
            boxes = {tuple(b.js(box))}  # counting down
            b.click("#go")
            boxes.add(tuple(b.js(box)))  # scrolling
            for _ in range(4):
                b.click("#pill-faster")  # to 10: two digits
            boxes.add(tuple(b.js(box)))
            smallest = min(b.js(sizes))
            fits = b.js(room)
            b.click("#go")
            boxes.add(tuple(b.js(box)))  # paused
        assert len(boxes) == 1, (width, boxes)
        assert smallest >= 44 and fits, width


@in_chromium
def test_with_reduced_motion_the_countdown_does_not_move_but_scrolling_still_runs(tmp_path):
    with viewer(tmp_path, reduced=True) as b:
        b.click("#scroll")
        counting = look(b)
        time.sleep(1.2)
        later = look(b)
        b.click("#go")
        running = look(b)
        moved = moved_since(b, running["y"])
    assert counting["icons"] == ["tick"] and counting["tick"] == "3"  # the number alone, no ring
    assert later["tick"] == "2"
    assert running["go"] == "Pause" and moved


@in_chromium
def test_the_pill_answers_the_keyboard(tmp_path):
    with viewer(tmp_path, width=1280, height=800, mobile=False) as b:
        b.js("document.querySelector('#scroll').focus()")
        b.press("Enter")
        counting = look(b)
        b.press("Enter")  # again: at once
        running = look(b)
        b.press("Tab")
        b.press("Enter")  # slower
        slower = look(b)
        b.press("Tab")
        b.press("Tab")
        b.press("Enter")  # stop
        ended = look(b)
    assert counting["focus"] == "go" and counting["go"] == "Start now"
    assert running["go"] == "Pause" and running["focus"] == "go"
    assert slower["focus"] == "pill-slower" and slower["speed"] == "5" and slower["go"] == "Pause"
    assert not ended["pill"] and ended["focus"] == "scroll"
