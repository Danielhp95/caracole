"""A song removed on the library page leaves the list (the owner's ask of 2026-11-26, from the phone: "the tile should
dissapear, now it just hangs there, and I'm unable to interact with it"): once its Undo window has passed and its job
is done, its line says Removed where it was for a moment, then goes by itself, and nothing dead is left behind.

The phone's page is the computer's assets served with the Android app's controls (``WebControls(in_app=True,
sync="sheet")``) on a touch screen: here, caracole serve's page built with those controls, driven by touch.
"""

from __future__ import annotations

import json

import pytest
from conftest import add_song
from helpers import browser, cards
from helpers.browser import CHROMIUM_MARKS
from test_web_page import COUNTS, QUICK, FakeCaracole, press_remove, serve  # noqa: F401  (serve: a fixture)

from caracole.songs import find_song

pytestmark = CHROMIUM_MARKS  # every test here opens the page in Chromium

PHONE = (390, 844)
LAPTOP = (1280, 800)


@pytest.fixture
def phone_controls(monkeypatch):
    """The served page built as the Android app's: its controls ``in_app``, its sync the sheet alone."""
    import caracole.library_page as library_page

    real = library_page.WebControls
    monkeypatch.setattr(library_page, "WebControls",
                        lambda *a, **k: real(*a, **{**k, "in_app": True, "sync": "sheet"}))


def tap(page, selector: str) -> None:
    """A finger's tap in the middle of the element ``selector`` finds, brought into view first."""
    box = page.js(f"(() => {{ const e = document.querySelector({json.dumps(selector)}); if (!e) return null; "
                  "e.scrollIntoView({block: 'center'}); const r = e.getBoundingClientRect(); "
                  "return [r.x + r.width / 2, r.y + r.height / 2]; })()")
    assert box, f"nothing on the page is {selector}"
    tap_at(page, box)


def tap_at(page, point) -> None:
    page.send("Input.dispatchTouchEvent", type="touchStart", touchPoints=[{"x": point[0], "y": point[1]}])
    page.send("Input.dispatchTouchEvent", type="touchEnd", touchPoints=[])


def remove_by_touch(page, item: str) -> None:
    """Remove, by touch: the line's name tapped (its card opens under it), its "⋯", then Remove."""
    tap(page, cards.name_of(item))
    card = cards.card_js(item)
    assert page.wait(f"{card} !== null && {card}.checkVisibility()")
    card_id = page.js(f"{card}.id")
    tap(page, f"#{card_id} .foot-more > summary")
    assert page.wait(f"document.querySelector('#{card_id} .foot-more').open")
    tap(page, f"#{card_id} form.remove button")


def library(conn):
    for n in range(3):
        add_song(conn, "Band", f"Song {n:02}")
    add_song(conn, "Radiohead", "Airbag")
    creep = add_song(conn, "Radiohead", "Creep")
    add_song(conn, "Radiohead", "Karma Police")  # under Creep, in its artist's band: it takes Creep's place
    for n in range(30):  # enough under it that the page, scrolled to Creep, stays scrolled where it is
        add_song(conn, "Wilco", f"Tune {n:02}")
    return creep


# Where the removed line was, and what is there now: the song's line (window.song) out of the page, what a finger
# finds where its title was, where the focus is.
AFTER = """(() => ({
  connected: window.song.isConnected,
  at: (() => { const e = document.elementFromPoint(window.where[0], window.where[1]);
               const line = e && e.closest('#list article');
               return line ? line.querySelector('h3').textContent : null; })(),
  focus: (() => { const a = document.activeElement; const line = a && a.closest('#list article');
                  return line ? line.querySelector('h3').textContent : a ? a.tagName : null; })(),
  gone: document.querySelectorAll('#list .gone, #list .card-gone').length,
  titles: Array.from(document.querySelectorAll('#list article h3')).map((h) => h.textContent) }))()"""

WHERE = """(() => { const r = window.song.querySelector('h3').getBoundingClientRect();
  window.where = [r.left + 4, r.top + r.height / 2]; return true; })()"""


@pytest.mark.parametrize("on", ["phone", "laptop"])
def test_a_removed_songs_line_leaves_the_list_once_it_is_removed(serve, cfg, conn, tmp_path, on, request):  # noqa: F811
    if on == "phone":
        request.getfixturevalue("phone_controls")
    creep = library(conn)
    runner = FakeCaracole(cfg)
    url = serve(runner, "(() => {})();\n", timers=QUICK)
    item = f'#list [data-id="{creep.id}"]'
    width, height = PHONE if on == "phone" else LAPTOP
    with browser.Browser(tmp_path / "chrome", width=width, height=height, mobile=on == "phone") as page:
        page.open(url)
        before = page.js(COUNTS)
        page.js(f"window.song = document.querySelector('{item}')")
        if on == "phone":
            remove_by_touch(page, item)
        else:
            page.click(cards.name_of(item))
            press_remove(page, item)
        progress = "(window.song.querySelector('.progress') || {}).textContent"
        assert page.wait(f"{progress} === 'Removed'", timeout=20), page.js(progress)
        page.js(WHERE)
        assert page.wait("!window.song.isConnected", timeout=10), page.js("window.song.outerHTML.slice(0, 300)")
        after = page.js(AFTER)
        counts = page.js(COUNTS)
        if on == "phone":  # the line now where Creep was takes a finger: its card opens
            tap_at(page, page.js("window.where"))
            opened = ("(() => { const l = document.elementFromPoint(window.where[0], window.where[1])"
                      ".closest('#list article'); const m = l && l.querySelector('.line-more');"
                      " return Boolean(m && m.getAttribute('aria-expanded') === 'true'); })()")
            assert page.wait(opened), page.js(AFTER)
    assert find_song(conn, creep.key) is None
    assert after["connected"] is False and after["gone"] == 0, after
    assert "Creep" not in after["titles"], after
    assert after["at"] == "Karma Police", after  # the line under it took its place
    assert after["focus"] in ("Karma Police", "Airbag", "BODY"), after  # never on a line that's gone
    assert before["summary"] == ["36 wanted"] and counts["summary"] == ["35 wanted"], (before, counts)


def test_undo_by_touch_keeps_the_song_on_the_phone(serve, cfg, conn, tmp_path, phone_controls):  # noqa: F811
    from test_library_card_place import SLOW_UNDO

    creep = library(conn)
    runner = FakeCaracole(cfg)
    url = serve(runner, "(() => {})();\n", timers=SLOW_UNDO)
    item = f'#list [data-id="{creep.id}"]'
    line = f"document.querySelector('{item} .progress')"
    with browser.Browser(tmp_path / "chrome", width=PHONE[0], height=PHONE[1], mobile=True) as page:
        page.open(url)
        remove_by_touch(page, item)
        assert page.wait(f"{line} !== null && !!{line}.querySelector('button.undo')")
        tap(page, f"{item} .progress button.undo")
        assert page.wait(f"{line}.textContent === 'Not removed'"), page.js(f"{line}.textContent")
        kept = page.js(f"document.querySelector('{item}') !== null && "
                       f"document.querySelectorAll('#list .gone, #list .card-gone').length === 0")
    assert kept
    assert not [c for c in runner.calls if c[0] == "remove"]
    assert find_song(conn, creep.key) is not None


class FailingRemoval(FakeCaracole):
    """``remove`` fails, as the command says an error, and removes nothing."""

    def __call__(self, args, emit):
        if args[0] == "remove":
            self.calls.append(list(args))
            self.polls.wait(1)
            emit("error: the library folder can't be written: Permission denied")
            return 1
        return super().__call__(args, emit)


@pytest.mark.parametrize("on", ["phone", "laptop"])
def test_a_removal_that_fails_puts_the_line_back_with_its_reason(serve, cfg, conn, tmp_path, on, request):  # noqa: F811
    if on == "phone":
        request.getfixturevalue("phone_controls")
    creep = library(conn)
    runner = FailingRemoval(cfg)
    url = serve(runner, "(() => {})();\n", timers=QUICK)
    item = f'#list [data-id="{creep.id}"]'
    width, height = PHONE if on == "phone" else LAPTOP
    with browser.Browser(tmp_path / "chrome", width=width, height=height, mobile=on == "phone") as page:
        page.open(url)
        if on == "phone":
            remove_by_touch(page, item)
        else:
            page.click(cards.name_of(item))
            press_remove(page, item)
        line = f"(document.querySelector('{item} .progress') || {{}}).textContent"
        assert page.wait(f"/failed|Permission denied/i.test({line} || '')", timeout=20), page.js(line)
        shown = page.js(f"""(() => {{ const l = document.querySelector('{item}');
          return {{ there: Boolean(l), gone: document.querySelectorAll('#list .gone, #list .card-gone').length,
                   buttons: l.querySelectorAll('button, a').length }}; }})()""")
    assert shown["there"] and shown["gone"] == 0 and shown["buttons"] > 0, shown
    assert find_song(conn, creep.key) is not None


def test_an_artist_left_with_one_song_folds_into_it_and_one_left_with_none_goes(
        serve, cfg, conn, tmp_path):  # noqa: F811
    # As the list draws them (library.js artistGroup): an artist of two lines is a band over them, of one a line
    # folded into it; a removal that leaves Radiohead one song folds it, and Oasis, left none, goes.
    add_song(conn, "Band", "Song")
    creep = add_song(conn, "Radiohead", "Creep")
    add_song(conn, "Radiohead", "Karma Police")
    wonderwall = add_song(conn, "Oasis", "Wonderwall")
    runner = FakeCaracole(cfg)
    url = serve(runner, "(() => {})();\n", timers=QUICK)
    groups = """Array.from(document.querySelectorAll('#list section.artist')).map((g) =>
      [g.dataset.artist, g.classList.contains('folded'),
       Array.from(g.querySelectorAll('article h3')).map((h) => h.textContent)])"""
    with browser.Browser(tmp_path / "chrome", width=LAPTOP[0], height=LAPTOP[1]) as page:
        page.open(url)
        before = page.js(groups)
        for song in (creep, wonderwall):
            item = f'#list [data-id="{song.id}"]'
            page.js(f"window.song = document.querySelector('{item}')")
            page.click(cards.name_of(item))
            press_remove(page, item)
            assert page.wait("!window.song.isConnected", timeout=20), page.js("window.song.textContent")
        after = page.js(groups)
        folded = page.js("""(() => { const g = document.querySelector('#list section.artist[data-artist="radiohead"]');
          return getComputedStyle(g.querySelector('.line-by')).display !== 'none'; })()""")
    assert before == [["band", True, ["Song"]], ["oasis", True, ["Wonderwall"]],
                      ["radiohead", False, ["Creep", "Karma Police"]]], before
    assert after == [["band", True, ["Song"]], ["radiohead", True, ["Karma Police"]]], after
    assert folded  # its artist's name over its title, as a folded line has it
