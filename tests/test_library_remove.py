"""A song removed on the library page leaves the list (the owner's ask of 2026-11-26, from the phone: "the tile should
dissapear, now it just hangs there, and I'm unable to interact with it"). Through the five seconds with Undo nothing
moves; as the removal is sent its card closes, so its line alone waits ("Removing…"); once its job is done the line
says Removed for a moment, then leaves, the list drawn as a fresh page would draw it, and nothing dead is left behind.

The phone's page is the computer's assets served with the Android app's controls (``WebControls(in_app=True,
sync="sheet")``) on a touch screen: here, caracole serve's page built with those controls, driven by touch.
"""

from __future__ import annotations

import json
import time

import pytest
from conftest import add_song
from helpers import browser, cards
from helpers.browser import CHROMIUM_MARKS
from test_web_page import COUNTS, QUICK, FakeCaracole, press_remove, serve  # noqa: F401  (serve: a fixture)

from caracole.songs import find_song

pytestmark = CHROMIUM_MARKS  # every test here opens the page in Chromium

PHONE = (390, 844)
LAPTOP = (1280, 800)
GONE_AFTER = 2.0  # seconds a removed song's line says Removed before it leaves (library.js GONE_AFTER)
PRESS_MOST = 3.0  # seconds a move waits at most for a pointer still down (library.js PRESS_MOST)
# Remove's countdown long enough that no step below can outrun it on a loaded machine (test_library_card_place.py's).
SLOW_UNDO = {"poll": QUICK["poll"], "undo": 9000}


@pytest.fixture
def phone_controls(monkeypatch):
    """The served page built as the Android app's: its controls ``in_app``, its sync the sheet alone."""
    import caracole.library_page as library_page

    real = library_page.WebControls
    monkeypatch.setattr(library_page, "WebControls",
                        lambda *a, **k: real(*a, **{**k, "in_app": True, "sync": "sheet"}))


# The middle of an element once it stands still: brought into view, the same box over two frames, and the element (or
# one inside it) what a finger there would touch; null until then.
STILL = """((selector) => new Promise((done) => {
  const e = document.querySelector(selector);
  if (!e) return done(null);
  e.scrollIntoView({ block: 'center' });
  const a = e.getBoundingClientRect();
  requestAnimationFrame(() => requestAnimationFrame(() => {
    const b = e.getBoundingClientRect();
    const x = b.x + b.width / 2, y = b.y + b.height / 2;
    const at = document.elementFromPoint(x, y);
    const same = a.x === b.x && a.y === b.y && a.width === b.width && a.height === b.height;
    done(same && b.width > 0 && at && (at === e || e.contains(at)) ? [x, y] : null);
  }));
}))"""


def tap(page, selector: str, timeout: float = 10.0) -> None:
    """A finger's tap in the middle of the element ``selector`` finds, once it stands still where a finger finds it."""
    deadline = time.monotonic() + timeout
    while True:
        point = page.js(f"{STILL}({json.dumps(selector)})")
        if point:
            break
        assert time.monotonic() < deadline, f"{selector} never stood still under a finger"
        time.sleep(0.03)
    tap_at(page, point)


def tap_at(page, point) -> None:
    page.send("Input.dispatchTouchEvent", type="touchStart", touchPoints=[{"x": point[0], "y": point[1]}])
    page.send("Input.dispatchTouchEvent", type="touchEnd", touchPoints=[])


def remove_by_touch(page, item: str) -> str:
    """Remove, by touch: the line's name tapped (its card opens under it), its "⋯", then Remove; the card's id."""
    tap(page, cards.name_of(item))
    card = cards.card_js(item)
    assert page.wait(f"{card} !== null && {card}.checkVisibility()")
    card_id = page.js(f"{card}.id")
    tap(page, f"#{card_id} .foot-more > summary")
    assert page.wait(f"document.querySelector('#{card_id} .foot-more').open")
    tap(page, f"#{card_id} form.remove button")
    return card_id


def menu_settled(card_id: str) -> str:
    """The card's ⋯ menu closed and its history entry taken back (card.js caracoleMenus), as after a choice in it."""
    return (f"!document.querySelector('#{card_id} .foot-more[open]') && "
            "typeof (history.state && history.state.caracoleMenu) !== 'number'")


def library(conn):
    for n in range(3):
        add_song(conn, "Band", f"Song {n:02}")
    add_song(conn, "Radiohead", "Airbag")
    creep = add_song(conn, "Radiohead", "Creep")
    karma = add_song(conn, "Radiohead", "Karma Police")  # under Creep, in its artist's band: it takes Creep's place
    for n in range(30):  # enough under it that the page, scrolled to Creep, stays scrolled where it is
        add_song(conn, "Wilco", f"Tune {n:02}")
    return creep, karma


# What the page does from the tap on: the line's texts (window.lines), when it is sent ("Removing…", its card then
# closed and the line its own height alone), when it says Removed, when it leaves; and each text a live region (an
# aria-live element or a role=status line) comes to hold, with whether the line had left by then (window.said).
WATCH = """(() => {
  window.lines = []; window.said = [];
  window.sentAt = window.removedAt = window.leftAt = window.atSend = undefined;
  let song = window.song;
  const title = song.querySelector('h3').textContent;
  const p = () => song.querySelector('.progress');
  if (window.watcher) window.watcher.disconnect();  // the song watched before
  window.watcher = new MutationObserver((records) => {
    const now = performance.now();
    if (!song.isConnected && window.removedAt === undefined) {  // drawn again as gone in a node of its own
      const again = [...document.querySelectorAll('article.gone')].find((a) => a.querySelector('h3').textContent === title);
      if (again) window.song = song = again;
    }
    const text = p() ? p().textContent : '';
    if (text && window.lines[window.lines.length - 1] !== text) window.lines.push(text);
    if (window.sentAt === undefined && text.startsWith('Removing…')) {
      window.sentAt = now;
      requestAnimationFrame(() => {
        const card = cardOf(song);
        window.atSend = { card: Boolean(card && card.checkVisibility()), tall: song.getBoundingClientRect().height };
      });
    }
    if (window.removedAt === undefined && text === 'Removed') window.removedAt = now;
    if (window.leftAt === undefined && window.removedAt !== undefined && !song.isConnected) window.leftAt = now;
    for (const r of records) {
      const at = r.target.nodeType === 1 ? r.target : r.target.parentElement;
      const region = at && at.closest('[aria-live], [role=status]');
      if (!region || !region.isConnected) continue;
      const t = region.textContent;
      const last = window.said[window.said.length - 1];
      if (!last || last.text !== t || last.region !== region) {
        window.said.push({ region, text: t, left: window.leftAt !== undefined });
      }
    }
  });
  window.watcher.observe(document.body, { subtree: true, childList: true, characterData: true });
  return true;
})()"""


@pytest.mark.parametrize("on", ["phone", "laptop"])
def test_a_removed_songs_line_leaves_the_list_once_it_is_removed(serve, cfg, conn, tmp_path, on, request):  # noqa: F811
    if on == "phone":
        request.getfixturevalue("phone_controls")
    creep, karma = library(conn)
    runner = FakeCaracole(cfg)
    url = serve(runner, "(() => {})();\n", timers=QUICK)
    item = f'#list [data-id="{creep.id}"]'
    width, height = PHONE if on == "phone" else LAPTOP
    with browser.Browser(tmp_path / "chrome", width=width, height=height, mobile=on == "phone") as page:
        page.open(url)
        before = page.js(COUNTS)
        page.js(f"window.song = document.querySelector('{item}')")
        cards.install(page)
        assert page.js(WATCH)
        if on == "phone":
            remove_by_touch(page, item)
        else:
            page.click(cards.name_of(item))
            press_remove(page, item)
        assert page.wait("window.removedAt !== undefined", timeout=20), page.js("window.lines")
        where = page.js("(() => { const r = window.song.querySelector('h3').getBoundingClientRect();"
                        " return [r.left + 4, r.top + r.height / 2]; })()")
        assert page.wait("window.leftAt !== undefined", timeout=10), page.js("window.song.outerHTML.slice(0, 300)")
        after = page.js(f"""(() => {{
          const e = document.elementFromPoint({where[0]}, {where[1]});
          const line = e && e.closest('#list article');
          return {{ at: line ? line.querySelector('h3').textContent : null,
                   focus: document.activeElement === document.querySelector('#list [data-id="{karma.id}"] .line-more'),
                   gone: document.querySelectorAll('#list .gone').length,
                   titles: Array.from(document.querySelectorAll('#list article h3')).map((h) => h.textContent) }}; }})()""")
        counts, at_send = page.js(COUNTS), page.js("window.atSend")
        said = page.js("window.said.map((s) => [s.region === window.song.querySelector('.progress'), s.text, s.left])")
        timing = page.js("[window.sentAt, window.removedAt, window.leftAt]")
        if on == "phone":  # the line now where Creep was takes a finger: its card opens
            tap_at(page, where)
            opened = (f"document.querySelector('#list [data-id=\"{karma.id}\"] .line-more')"
                      ".getAttribute('aria-expanded') === 'true'")
            assert page.wait(opened), page.js("document.activeElement.outerHTML.slice(0, 200)")
    assert find_song(conn, creep.key) is None
    # Sent: its card closed, the line alone waits, one line tall.
    assert at_send["card"] is False and at_send["tall"] < 120, at_send
    # Removed for GONE_AFTER, then gone: the line under it in its place, the focus on it, one song fewer counted.
    assert timing[2] - timing[1] >= GONE_AFTER * 1000 - 50, timing
    assert after["gone"] == 0 and "Creep" not in after["titles"], after
    assert after["at"] == "Karma Police" and after["focus"] is True, after
    assert before["summary"] == ["36 wanted"] and counts["summary"] == ["35 wanted"], (before, counts)
    # A screen reader hears Removed on the line, once, before it leaves; the leaving says nothing more.
    assert [s for s in said if s[0] and s[1] == "Removed"] == [[True, "Removed", False]], said
    assert [s for s in said if s[2]] == [], said


def test_a_pointer_that_never_comes_up_keeps_the_line_no_longer_than_the_bound(serve, cfg, conn, tmp_path,  # noqa: F811
                                                                               phone_controls):
    # A finger the page never hears come up (the system took the touch, the app went away): the line waits for it
    # PRESS_MOST at most, then leaves all the same.
    creep, _ = library(conn)
    url = serve(FakeCaracole(cfg), "(() => {})();\n", timers=QUICK)
    item = f'#list [data-id="{creep.id}"]'
    with browser.Browser(tmp_path / "chrome", width=PHONE[0], height=PHONE[1], mobile=True) as page:
        page.open(url)
        page.js(f"window.song = document.querySelector('{item}')")
        cards.install(page)
        assert page.js(WATCH)
        remove_by_touch(page, item)
        assert page.wait("window.removedAt !== undefined", timeout=20), page.js("window.lines")
        page.send("Input.dispatchTouchEvent", type="touchStart", touchPoints=[{"x": 380, "y": 830}])  # never let go
        assert page.wait("window.leftAt !== undefined", timeout=GONE_AFTER + PRESS_MOST + 5)
        waited = page.js("window.leftAt - window.removedAt") / 1000
        page.send("Input.dispatchTouchEvent", type="touchCancel", touchPoints=[])
    assert GONE_AFTER + PRESS_MOST - 0.3 <= waited <= GONE_AFTER + PRESS_MOST + 2.5, waited


def test_undo_by_touch_keeps_the_song_on_the_phone(serve, cfg, conn, tmp_path, phone_controls):  # noqa: F811
    creep, _ = library(conn)
    runner = FakeCaracole(cfg)
    url = serve(runner, "(() => {})();\n", timers=SLOW_UNDO)
    item = f'#list [data-id="{creep.id}"]'
    line = f"document.querySelector('{item} .progress')"
    with browser.Browser(tmp_path / "chrome", width=PHONE[0], height=PHONE[1], mobile=True) as page:
        page.open(url)
        card_id = remove_by_touch(page, item)
        assert page.wait(f"{line} !== null && !!{line}.querySelector('button.undo')")
        assert page.wait(menu_settled(card_id))  # the menu Remove was in has closed, its entry taken back
        tap(page, f"{item} .progress button.undo")
        assert page.wait(f"{line}.textContent === 'Not removed'"), page.js(f"{line}.textContent")
        kept = page.js(f"document.querySelector('{item}') !== null && "
                       f"document.querySelectorAll('#list .gone').length === 0 && "
                       f"!document.querySelector('#{card_id} form.remove button').disabled")
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
    # Its card closed as it was sent, and stays closed: the line says why, and its card opens again as ever.
    if on == "phone":
        request.getfixturevalue("phone_controls")
    creep, _ = library(conn)
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
          return {{ there: Boolean(l), gone: document.querySelectorAll('#list .gone').length,
                   buttons: l.querySelectorAll('button, a').length }}; }})()""")
        time.sleep(GONE_AFTER + 0.3)  # past the time a removed line would have left: this one stays
        stays = page.js(f"document.querySelector('{item}') !== null")
        cards.open_card(page, item)
        opened = page.js(f"{cards.card_js(item)}.checkVisibility()")
    assert shown["there"] and shown["gone"] == 0 and shown["buttons"] > 0, shown
    assert stays and opened
    assert find_song(conn, creep.key) is not None


# The list as it is drawn: each band or folded artist (its key, folded, its counts), each run of lines or folds and
# what its estimate holds, each line's title, in order; and the A-Z strip's letters.
SHAPE = """(() => Array.from(document.querySelectorAll('#list section.artist, #list section.flat, #list .cv, #list article.line'))
  .map((e) => {
    const cv = e.classList.contains('cv') ? ['--bands', '--lines', '--folds']
      .map((n) => e.style.getPropertyValue(n)).join('/') : '';
    if (e.matches('section.artist')) {
      const c = e.querySelector(':scope > .artist-title .artist-counts');
      return ['artist', e.dataset.artist, e.classList.contains('folded'), c ? c.textContent : '', cv];
    }
    if (e.matches('article.line')) return ['line', e.querySelector('h3').textContent];
    return [e.matches('section.flat') ? 'flat' : 'run', cv];
  }))()"""
JUMP = "(() => { const j = document.getElementById('jump'); return [j.hidden, [...j.querySelectorAll('button')].map((b) => b.textContent)]; })()"
# Each letter of the strip pressed: what it brings into view and gives the focus to is in the page, the first group
# of that letter.
JUMPS = """(() => [...document.querySelectorAll('#jump button')].map((b) => {
  b.click();
  const at = document.activeElement;
  const groups = [...document.querySelectorAll('#list section.artist')];
  const first = groups.find((g) => (g.dataset.artist || '').toUpperCase().startsWith(b.textContent));
  return [b.textContent, at.isConnected, at === first];
}))()"""


def test_the_list_a_removal_leaves_is_what_a_fresh_page_draws(serve, cfg, conn, tmp_path):  # noqa: F811
    # Over 40 songs, the A-Z strip shown: the only song of a letter (Eels: E goes from the strip), the first song of a
    # letter with others (Beatles' Help), and one of an artist's two (ABBA folds into Waterloo). The list each leaves,
    # its bands, folds, runs and their estimates, its counts and its strip, is the one a fresh page draws of what is
    # left, each letter pressed landing on its first group.
    dancing = add_song(conn, "ABBA", "Dancing Queen")
    add_song(conn, "ABBA", "Waterloo")
    help_ = add_song(conn, "Beatles", "Help")
    for title in ("Let It Be", "Yesterday"):
        add_song(conn, "Beatles", title)
    singles = {}
    for artist in ("Cake", "Dido", "Eels", "Feist", "Garbage", "Hole", "Interpol", "Jamiroquai", "Keane"):
        singles[artist] = add_song(conn, artist, "Song")
    for n in range(30):
        add_song(conn, "Wilco", f"Tune {n:02}")
    url = serve(FakeCaracole(cfg), "(() => {})();\n", timers=QUICK)
    with browser.Browser(tmp_path / "chrome", width=LAPTOP[0], height=LAPTOP[1]) as page:
        page.open(url)
        first_strip = page.js(JUMP)
        for song in (singles["Eels"], help_, dancing):
            item = f'#list [data-id="{song.id}"]'
            page.js(f"window.song = document.querySelector('{item}')")
            page.click(cards.name_of(item))
            press_remove(page, item)
            assert page.wait("!window.song.isConnected", timeout=20), page.js("window.song.textContent")
        shape, strip, jumps = page.js(SHAPE), page.js(JUMP), page.js(JUMPS)
        page.open(url)  # a fresh page of what is left
        fresh_shape, fresh_strip = page.js(SHAPE), page.js(JUMP)
    assert first_strip == [False, ["A", "B", "C", "D", "E", "F", "G", "H", "I", "J", "K", "W"]], first_strip
    assert strip == fresh_strip == [False, ["A", "B", "C", "D", "F", "G", "H", "I", "J", "K", "W"]], strip
    assert all(connected and first for _, connected, first in jumps), jumps
    assert shape == fresh_shape, (shape, fresh_shape)
    assert shape[0][:3] == ["artist", "abba", True], shape[:3]  # folded into Waterloo


def test_a_song_removed_elsewhere_leaves_the_list_on_the_phone(serve, cfg, conn, tmp_path, phone_controls):  # noqa: F811
    # Removed on the computer (or another tab) while the phone's Library shows: the page learns it from /jobs.json,
    # the song asked for next getting its id again (another identity under it, library.js lostTo). Its line says
    # Removed, as a removal made on the page does, then leaves.
    add_song(conn, "Band", "Song")
    creep = add_song(conn, "Radiohead", "Creep")  # the newest: the next song added takes its id
    url = serve(FakeCaracole(cfg), "(() => {})();\n", timers=QUICK)
    item = f'#list [data-id="{creep.id}"]'
    with browser.Browser(tmp_path / "chrome", width=PHONE[0], height=PHONE[1], mobile=True) as page:
        page.open(url)
        page.js(f"window.song = document.querySelector('{item}')")
        cards.install(page)
        assert page.js(WATCH)
        conn.execute("DELETE FROM songs WHERE id = ?", (creep.id,))  # removed elsewhere
        page.js("""(() => { const form = document.querySelector("form.request-form");
          form.elements.namedItem("artist").value = "Muse"; form.elements.namedItem("title").value = "Uprising";
          form.requestSubmit(); })()""")
        assert page.wait("window.leftAt !== undefined", timeout=20), page.js("window.lines")
        lines = page.js("window.lines")
        listed = page.js("Array.from(document.querySelectorAll('#list article h3')).map((h) => h.textContent)")
        summary = page.js(COUNTS)["summary"]
    assert lines[-1] == "Removed", lines
    assert "Creep" not in listed and "Song" in listed, listed
    assert find_song(conn, creep.key) is None
    assert summary == ["1 wanted"], summary  # Song; Uprising found its sheet


def test_a_song_removed_from_the_search_leaves_its_results(serve, cfg, conn, tmp_path, phone_controls):  # noqa: F811
    # Among a search's results on the phone (search mode, #found): the line leaves the results as it would the list,
    # the focus on the next line of the results. Where the search found that song alone, the results then say what
    # a search that finds none of yours says, and the focus is in the search box.
    add_song(conn, "Radiohead", "Airbag")
    creep = add_song(conn, "Radiohead", "Creep")
    karma = add_song(conn, "Radiohead", "Karma Police")
    wonderwall = add_song(conn, "Oasis", "Wonderwall")
    url = serve(FakeCaracole(cfg), "(() => {})();\n", timers=QUICK)
    found = ("Array.from(document.querySelectorAll('#found section.artist article.line h3'))"
             ".map((h) => h.textContent)")  # your songs' lines (what found nothing on the sites is a line of its own)
    with browser.Browser(tmp_path / "chrome", width=PHONE[0], height=PHONE[1], mobile=True) as page:
        page.open(url)
        cards.install(page)
        for query, song in (("radiohead", creep), ("wonderwall", wonderwall)):
            page.js("document.getElementById('q').focus(); document.getElementById('q').select()")
            page.type(query)
            assert page.wait(f"document.getElementById('found').dataset.query === {json.dumps(query)}")
            item = f'#found [data-id="{song.id}"]'
            assert page.wait(f"document.querySelector('{item}') !== null"), page.js(found)
            page.js(f"window.song = document.querySelector('{item}')")
            assert page.js(WATCH)
            remove_by_touch(page, item)
            assert page.wait("window.leftAt !== undefined", timeout=20), page.js("window.lines")
            if query == "radiohead":
                left = page.js(found)
                focus = page.js(f"document.activeElement === document.querySelector('#found [data-id=\"{karma.id}\"] "
                                ".line-more')")
            else:
                alone = page.js(found)
                said = page.js("document.getElementById('results').innerText")
                focus_alone = page.js("document.activeElement.id")
                searching = page.js("document.body.classList.contains('search-mode')")
    assert left == ["Airbag", "Karma Police"] and focus is True, (left, focus)
    assert "Wonderwall" not in alone and focus_alone == "q" and searching, (alone, focus_alone)
    assert "Nothing for “wonderwall”" in said, said
