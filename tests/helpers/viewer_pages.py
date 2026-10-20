"""A sheet viewer written to a file and driven in a Chromium of its own, on real time, as a finger,
the mouse and the keyboard would: the bar's, the settings', the card's and the scroll's tests::

    from helpers.viewer_pages import drag, rest, tap, viewer as open_viewer, written

    with open_viewer(tmp_path, written(tmp_path, cho)) as b:
        drag(b, 500)  # on down the song
        rest(b)
        tap(b, "#sheet .w")

A finger is touch events (``Input.dispatchTouchEvent``): ``Input.synthesizeScrollGesture`` with a
touch scrolls nothing in a headless Chromium.
"""

from __future__ import annotations

import json
import tempfile
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from caracole.viewer import build_viewer

from helpers.browser import Browser


def written(tmp_path: Path, cho: str, name: str = "Title") -> str:
    """The viewer of ``cho``, written as Artist/<name>/sheet.html under ``tmp_path``; its address."""
    page = tmp_path / "Artist" / name / "sheet.html"
    page.parent.mkdir(parents=True, exist_ok=True)
    page.write_text(build_viewer(cho), encoding="utf-8")
    return page.as_uri()


@contextmanager
def viewer(tmp_path: Path, url: str, *, width: int = 390, height: int = 844, mobile: bool = True,
           reduced: bool = False) -> Iterator[Browser]:
    """The page at ``url`` in a Chromium of its own, ``width`` × ``height`` (``mobile``: a phone's, with
    touch), once its script ran; ``reduced``: with prefers-reduced-motion."""
    with Browser(Path(tempfile.mkdtemp(prefix="profile-", dir=tmp_path)), width=width, height=height,
                 mobile=mobile) as b:
        b.send("Emulation.setEmulatedMedia", features=[
            {"name": "prefers-reduced-motion", "value": "reduce" if reduced else "no-preference"}])
        b.open(url)
        assert b.wait("document.documentElement.dataset.ready === '1'")
        yield b


def drag(b: Browser, dy: float, *, start: float | None = None) -> None:
    """A finger drags the page by ``dy`` pixels (more than 0: on down the song) from ``start`` px down
    the screen (by default low for a drag down, high for one up), and lets go: it may glide on a little."""
    if start is None:
        start = 640 if dy > 0 else 200
    steps = 12
    b.send("Input.dispatchTouchEvent", type="touchStart", touchPoints=[{"x": 195, "y": start}])
    for i in range(1, steps + 1):
        b.send("Input.dispatchTouchEvent", type="touchMove", touchPoints=[{"x": 195, "y": start - dy * i / steps}])
        time.sleep(0.016)
    b.send("Input.dispatchTouchEvent", type="touchEnd", touchPoints=[])


def rest(b: Browser) -> None:
    """Until the page stops gliding after a drag: a tap on a page still moving only stops it, with no click."""
    last = None
    for _ in range(40):
        y = b.js("scrollY")
        if y == last:
            return
        last = y
        time.sleep(0.1)


def key(b: Browser, name: str, code: int) -> None:
    """A key pressed and let go where the focus is (``Browser.press`` knows Enter, Escape and Tab alone)."""
    for kind in ("keyDown", "keyUp"):
        b.send("Input.dispatchKeyEvent", type=kind, key=name, code=name, windowsVirtualKeyCode=code)


def tab(b: Browser, *, back: bool = False) -> None:
    """Tab, or Shift+Tab, where the focus is."""
    for kind in ("keyDown", "keyUp"):
        b.send("Input.dispatchKeyEvent", type=kind, key="Tab", code="Tab", windowsVirtualKeyCode=9,
               modifiers=8 if back else 0)


def tap_at(b: Browser, x: float, y: float) -> None:
    """A finger on the screen at ``x``, ``y``, lifted at once."""
    b.send("Input.dispatchTouchEvent", type="touchStart", touchPoints=[{"x": x, "y": y}])
    b.send("Input.dispatchTouchEvent", type="touchEnd", touchPoints=[])
    time.sleep(0.05)


def click_at(b: Browser, x: float, y: float) -> None:
    """The mouse pressed and let go at ``x``, ``y``."""
    for kind in ("mousePressed", "mouseReleased"):
        b.send("Input.dispatchMouseEvent", type=kind, x=x, y=y, button="left", clickCount=1)
    time.sleep(0.05)


def tap(b: Browser, selector: str) -> None:
    """A finger on the first element ``selector`` finds in view, without scrolling to it, with no chord
    within a finger's reach: Chrome hit-tests a touch over an area, and a word beside a chord's larger
    target would open the chord's card. On the element's last line of text, as a word's box reaches up
    into the row of chords; one of the sheet's clear of the bar and the pill, at the foot."""
    clear = 120 if selector.startswith("#sheet") else 0
    box = b.js(f"""(() => {{
      const at = (r) => [r.x + r.width / 2, r.bottom - Math.min(8, r.height / 2)];
      const near = [[0, 0], [-12, 0], [12, 0], [0, -12], [0, 12], [-9, -9], [9, -9], [-9, 9], [9, 9]];
      const el = [...document.querySelectorAll({json.dumps(selector)})].find((e) => {{
        const r = e.getBoundingClientRect();
        if (!r.width || r.top < 0 || r.bottom > innerHeight - {clear}) return false;
        const [x, y] = at(r);
        if (!e.contains(document.elementFromPoint(x, y))) return false;
        return near.every(([dx, dy]) => {{ const hit = document.elementFromPoint(x + dx, y + dy);
          return !(hit && hit.closest(".c")); }}); }});
      return el ? at(el.getBoundingClientRect()) : null; }})()""")
    assert box, f"nothing in view is {selector}"
    b.send("Input.dispatchTouchEvent", type="touchStart", touchPoints=[{"x": box[0], "y": box[1]}])
    b.send("Input.dispatchTouchEvent", type="touchEnd", touchPoints=[])
