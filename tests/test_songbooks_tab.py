"""The library page's Songbooks tab, in a real browser: served by a real ``caracole serve`` (its queue running
``Fake``, caracole's commands done here with no request), and as the file on disk.

On the left the songbooks as lines, on the right the one opened as a set list: drag a song (or move it with
the keyboard), change where it plays (its chip), take it out, get the songs without a sheet, add a song from
your library or the offline indexes, rename or delete the songbook, open its files. Each change is one
``caracole songbook`` command, and the tab says how it goes on the songbook and on the song.
"""

from __future__ import annotations

import json
import re
import threading
import time
from dataclasses import replace
from datetime import UTC, datetime
from urllib.parse import parse_qs

import pytest
from helpers.browser import CHROMIUM_MARKS, Browser, BrowserError
from helpers.guitar import SYNTHETIC, alphatab_dir, keep_guitar
from helpers.songbooks import FakeChordPro, keep_sheet, render_sheets
from helpers.targets import small_targets, weak_edges

from caracole import db
from caracole.get import PROGRESS_PREFIX
from caracole.library_page import build_library_page, write_library_page
from caracole.overrides import Overrides, load_overrides, override_key
from caracole.songbook import (
    Setting,
    add_to_songbook,
    delete_songbook,
    load_songbooks,
    make_songbook,
    move_in_songbook,
    remove_from_songbook,
    rename_songbook,
    render_songbooks,
    set_song_setting,
    songbooks_file,
)
from caracole.songs import find_song, update_song
from caracole.web.app import WebApp
from caracole.web.jobs import JobQueue
from caracole.web.security import allowed_hosts
from caracole.web.server import make_server

from conftest import add_song

pytestmark = CHROMIUM_MARKS  # every test here opens the page in Chromium

QUICK = {"poll": 100, "undo": 500}  # the page asks /jobs.json every 100 ms
NOW = datetime(2026, 10, 18, 3, 41, tzinfo=UTC)
CAMPFIRE = "#tab=songbooks&book=Campfire"
# How long each of Fake's commands takes at least. caracole's take seconds, and a browser counts a layout shift as
# the tap's (``hadRecentInput``) for half a second after it: each takes longer, so that what a change does once it
# is over is never taken for the tap's, on a busy machine or an idle one.
TAKES = 0.6


class Fake:
    """caracole's commands, done here with no request. ``songbook`` changes songbooks.toml as the command does,
    then makes the songbooks' files again (a stand-in chordpro); ``get`` adds the song from wanted.txt and keeps
    a sheet, its stages said as ``caracole get --progress`` says them. Each takes ``TAKES`` at least, so the page
    sees it run; a songbook named in ``fail`` fails with that error; with ``hold``, an event, each waits for it
    first."""

    def __init__(self, cfg, *, fail=None, hold=None):
        self.cfg = cfg
        self.fail = fail or {}
        self.hold = hold  # an event: each command waits for it
        self.calls: list[list[str]] = []

    def __call__(self, args, emit):
        if self.hold is not None:
            self.hold.wait(20)
        self.calls.append(list(args))
        time.sleep(TAKES)
        conn = db.connect(self.cfg.db_path)
        try:
            if args[0] == "get":
                return self._get(conn, args, emit)
            if args[0] == "songbook":
                return self._songbook(conn, args, emit)
            emit(f"ran {args[0]}")
            return 0
        finally:
            conn.close()

    def _songbook(self, conn, args, emit):
        toml = songbooks_file(self.cfg.library_dir)
        action, rest = args[1], list(args[2:])
        options, words = rest[:rest.index("--")], rest[rest.index("--") + 1:]
        name, others = words[0], words[1:]
        if name in self.fail:
            emit(f"error: {self.fail[name]}")
            return 1
        if action == "make":
            make_songbook(toml, name, others)
        elif action == "add":
            add_to_songbook(toml, name, others)
        elif action == "remove":
            remove_from_songbook(toml, name, others)
        elif action == "move":
            move_in_songbook(toml, name, others[0], int(others[1]))
        elif action == "set":
            said = dict(zip(options[::2], options[1::2]))
            setting = None if "--clear" in options else Setting(
                said.get("--key"), said.get("--mode"), int(said["--capo"]) if "--capo" in said else None,
                said.get("--instrument"))
            set_song_setting(toml, name, others[0], setting)
        elif action == "rename":
            rename_songbook(toml, name, others[0])
        elif action == "delete":
            delete_songbook(toml, name)
        render_songbooks(conn, self.cfg, load_overrides(self.cfg.overrides_file), runner=FakeChordPro())
        emit(f"ran songbook {action}")
        return 0

    def _get(self, conn, args, emit):
        from caracole.wanted import sync_wanted

        def stage(name, state, detail=""):
            emit(PROGRESS_PREFIX + json.dumps({"stage": name, "state": state, "detail": detail}))

        stage("song", "running")
        sync_wanted(conn, self.cfg.wanted_file, datetime.now(UTC))
        stage("song", "done", "in the library")
        stage("sheet", "running")
        time.sleep(0.2)
        song = find_song(conn, override_key(f"{args[-2]} - {args[-1]}"))
        keep_sheet(conn, self.cfg, song, tab_id=700 + song.id)
        render_sheets(conn, self.cfg)
        update_song(conn, song.id, status="found", ug_dirty=False)
        stage("sheet", "done", "tab 1 from Ultimate Guitar")
        return 0


@pytest.fixture
def library(conn, cfg):
    """Creep and De Música Ligera with sheets (both in A minor), Hysteria without one; the songbook Campfire
    of the three, and Road trip of De Música Ligera alone, their files made."""
    songs = {}
    for artist, title, sheet in (("Radiohead", "Creep", True), ("Muse", "Hysteria", False),
                                 ("Soda Stereo", "De Música Ligera", True)):
        songs[title] = add_song(conn, artist, title)
        if sheet:
            keep_sheet(conn, cfg, songs[title], tab_id=len(songs))
    render_sheets(conn, cfg)
    make_songbook(songbooks_file(cfg.library_dir), "Campfire",
                  ["Radiohead - Creep", "Muse - Hysteria", "Soda Stereo - De Música Ligera"])
    make_songbook(songbooks_file(cfg.library_dir), "Road trip", ["Soda Stereo - De Música Ligera"])
    render_songbooks(conn, cfg, Overrides(), runner=FakeChordPro())
    conn.commit()
    return songs


@pytest.fixture
def serve(cfg):
    """``serve(runner)``: caracole serve on a free port, its queue running ``runner`` (``before(app)`` runs before
    it starts; with ``alphatab``, alphaTab's folder, it shows Guitar Pro files in the browser); returns its address
    and the forms the page posted, each (its address, its fields)."""
    started = []

    def start(runner, *, before=None, alphatab=None):
        queue = JobQueue(runner)
        app = WebApp(cfg if alphatab is None else replace(cfg, alphatab_dir=alphatab), queue,
                     allowed=allowed_hosts("127.0.0.1"), csrf="tok", timers=QUICK, searches_lacuerda=False)
        posted: list[tuple[str, dict[str, str]]] = []
        answer = app.handle

        def handle(request):
            if request.method == "POST":
                fields = parse_qs(request.body.decode("utf-8"))
                posted.append((request.target, {k: v[0] for k, v in fields.items() if k != "csrf"}))
            return answer(request)

        app.handle = handle
        if before is not None:  # what is queued before the queue starts: waiting when the page loads
            before(app)
        server = make_server(app, "127.0.0.1", 0)
        threading.Thread(target=server.serve_forever, args=(0.01,), daemon=True).start()  # stops within 10 ms
        queue.start()
        started.append((server, queue))
        return f"http://127.0.0.1:{server.server_address[1]}/", posted

    yield start
    for server, queue in started:
        queue.stop()
        server.shutdown()
        server.server_close()


def opened(tmp_path, width=1280, height=800, *, dark=False):
    """A Chromium of the test's own, ``width`` × ``height`` (narrower than 500: a phone's, with touch)."""
    try:
        page = Browser(tmp_path / "chrome", width=width, height=height, mobile=width < 500)
    except BrowserError as e:
        pytest.skip(f"chromium couldn't run: {e}")
    if dark:
        page.send("Emulation.setEmulatedMedia", features=[{"name": "prefers-color-scheme", "value": "dark"}])
    return page


SIZES = pytest.mark.parametrize("size", [(390, 844), (1280, 800)], ids=["phone", "laptop"])

BOOKS = """Array.from(document.querySelectorAll('#songbooks .book-line'))
  .map((b) => [b.querySelector('.book-name').textContent, b.querySelector('.book-meta').textContent])"""
SET = """Array.from(document.querySelectorAll('#songbooks .book .set-line:not(.gone)')).map((li) => [
  li.querySelector('.set-n').textContent, li.querySelector('h3').textContent, li.querySelector('.set-by').textContent,
  (li.querySelector('.plays, .badge.missing') || {}).textContent || ''])"""
TITLES = "Array.from(document.querySelectorAll('#songbooks .book .set-line:not(.gone) h3')).map((h) => h.textContent)"
# The titles as they show, top to bottom: a drag moves the lines it passes before it moves any in the page.
SEEN = """Array.from(document.querySelectorAll('#songbooks .book .set-line:not(.gone)'))
  .sort((a, b) => a.getBoundingClientRect().top - b.getBoundingClientRect().top)
  .map((li) => li.querySelector('h3').textContent)"""
STATUS = "((document.querySelector('#songbooks .book .book-status') || {}).textContent || '')"
SHOWN = "((s) => { const n = document.querySelector(s); return Boolean(n && n.checkVisibility()); })"

# Notes every layout shift that no input brought about (buffered: since the page loaded), what moved, and when (``at``,
# by the page's clock).
SHIFTS = """(() => {
  window.shifts = [];
  new PerformanceObserver((list) => {
    for (const e of list.getEntries()) {
      if (e.hadRecentInput) continue;
      const moved = (e.sources || []).map((s) => (s.node ? s.node.id || String(s.node.className || s.node.nodeName) : "?"));
      window.shifts.push({ value: Math.round(e.value * 10000) / 10000, moved, at: Math.round(e.startTime) });
    }
  }).observe({ type: "layout-shift", buffered: true });
  return true;
})()"""
# The shifts but the masthead's Requests count's, which counts what runs, as on every page that asks for something.
MOVED = "window.shifts.filter((s) => s.value > 0 && JSON.stringify(s.moved) !== '[\"links\"]')"
# The page's clock once the frames under way are drawn: a shift after it (``at``) came after what was drawn by then.
DRAWN = "new Promise((done) => requestAnimationFrame(() => requestAnimationFrame(() => done(performance.now()))))"
# When the page hears the server's answer to a form it posts (``window.answered``, by its clock), before its script does.
ANSWERED = """(() => {
  const real = window.fetch;
  window.fetch = (url, init) => real(url, init).then((r) => {
    if (init && init.method === "POST") window.answered = performance.now();
    return r;
  });
  return true;
})()"""
# What a Select's change moved on its own: none of what the tab's opening moved, on the server's answer to the tap
# (``window.answered``, and the frames drawn by ``tab``), which is the tap's, however late a busy machine gives it.
OWN_MOVES = "{moved}.filter((s) => s.at <= window.answered || s.at > {tab})"
STILL = "new Promise((done) => setTimeout(() => requestAnimationFrame(() => requestAnimationFrame(done)), 400))"


def books_toml(cfg):
    return load_songbooks(songbooks_file(cfg.library_dir))


def key(page, name, code):
    for kind in ("keyDown", "keyUp"):
        page.send("Input.dispatchKeyEvent", type=kind, key=name, code=name, windowsVirtualKeyCode=code)


def middles(page, *selectors):
    """Where the middle of each is on the screen, the first scrolled to the screen's middle first."""
    return page.js(f"""(() => {{ const all = {json.dumps(list(selectors))}.map((s) => document.querySelector(s));
        all[0].scrollIntoView({{block: 'center'}});
        return all.map((n) => {{ const r = n.getBoundingClientRect(); return [r.x + r.width / 2, r.y + r.height / 2]; }});
    }})()""")


# --- the list -----------------------------------------------------------------------------------------------


@SIZES
def test_the_songbooks_tab_lists_each_songbook_with_its_counts(serve, cfg, library, tmp_path, size):
    url, _ = serve(Fake(cfg))
    with opened(tmp_path, *size) as page:
        page.open(url)
        assert page.js(f"{SHOWN}('#list')") and not page.js(f"{SHOWN}('#songbooks')")  # the library first
        assert page.js("document.querySelector('#tab-songbooks .n').textContent") == "2"
        page.click("#tab-songbooks")
        assert page.js("document.querySelector('#tab-songbooks').getAttribute('aria-selected')") == "true"
        assert page.js(f"{SHOWN}('#songbooks')") and not page.js(f"{SHOWN}('#list')")
        books = page.js(BOOKS)
        day = r"changed \d{4}-\d{2}-\d{2}"
        assert [b[0] for b in books] == ["Campfire", "Road trip"]
        assert re.fullmatch(r"3 songs · 1 without a sheet · " + day, books[0][1]), books
        assert re.fullmatch(r"1 song · " + day, books[1][1]), books
        assert page.js(f"{SHOWN}('#songbooks .new-book')")
        # On a laptop the first songbook opens beside the list; on a phone the list comes alone, the whole screen's.
        laptop = size[0] >= 900
        assert page.js(f"{SHOWN}('#songbooks .book')") is laptop
        if laptop:
            assert page.js("document.querySelector('#songbooks .book h2').textContent") == "Campfire"
            assert page.js("document.querySelector('#songbooks .book-line[aria-current=\"true\"] .book-name')"
                           ".textContent") == "Campfire"
        assert "tab=songbooks" in page.js("location.hash")
        page.js("window.before = true; location.reload()")
        assert page.wait("window.before === undefined && document.readyState === 'complete'")
        assert page.js(f"{SHOWN}('#songbooks')")  # the address keeps the tab
        page.click("#tab-library")
        assert page.js(f"{SHOWN}('#list')") and "tab=" not in page.js("location.hash")
        assert page.js("document.documentElement.scrollWidth <= innerWidth")


@SIZES
def test_opening_a_songbook_shows_its_set_list_with_each_songs_setting(serve, cfg, library, tmp_path, size):
    set_song_setting(songbooks_file(cfg.library_dir), "Campfire", "Radiohead - Creep", Setting("G", "dorian", 0))
    url, _ = serve(Fake(cfg))
    with opened(tmp_path, *size) as page:
        page.open(url + "#tab=songbooks")
        page.click('#songbooks .book-line[data-book="Road trip"]')
        assert page.js("document.querySelector('#songbooks .book h2').textContent") == "Road trip"
        if size[0] < 900:  # on a phone the set list takes the screen, and its way back is the list's
            assert not page.js(f"{SHOWN}('#songbooks .book-list')")
            page.click("#songbooks .book-back")
            assert page.js(f"{SHOWN}('#songbooks .book-list')") and not page.js(f"{SHOWN}('#songbooks .book')")
        page.click('#songbooks .book-line[data-book="Campfire"]')
        assert page.js(SET) == [["1", "Creep", "Radiohead", "G Dorian"],
                                ["2", "Hysteria", "Muse", "No sheet yet"],
                                ["3", "De Música Ligera", "Soda Stereo", "A Minor"]]
        # Creep plays where the songbook says; De Música Ligera as its own version: its chip says so to a reader.
        said = page.js("Array.from(document.querySelectorAll('#songbooks .set-line .plays'))"
                       ".map((c) => c.getAttribute('aria-label'))")
        assert said == ["Creep plays in G Dorian here: change it",
                        "De Música Ligera plays in A Minor, its own version: change it"], said
        assert page.js("document.querySelector('#songbooks .set-line .set-title').getAttribute('href')") == \
            "Radiohead/Creep/sheet.html"  # its title opens its sheet
        assert "book=Campfire" in page.js("location.hash")
        page.js("window.before = true; location.reload()")
        assert page.wait("window.before === undefined && document.readyState === 'complete'")
        assert page.js("document.querySelector('#songbooks .book h2').textContent") == "Campfire"
        assert page.js("document.documentElement.scrollWidth <= innerWidth")


# --- the set list ---------------------------------------------------------------------------------------------


@SIZES
def test_dragging_a_song_moves_it_and_the_keyboard_can_too(serve, cfg, library, tmp_path, size):
    url, posted = serve(Fake(cfg))
    with opened(tmp_path, *size) as page:
        page.open(url + CAMPFIRE)
        assert page.js(SHIFTS)
        grip = '#songbooks .set-line[data-entry="Radiohead - Creep"] .grip'
        (x, y), (_, below) = middles(page, grip, '#songbooks .set-line[data-entry="Muse - Hysteria"]')
        finger = size[0] < 500  # a phone's drag is a finger's: touch events; a laptop's, the mouse's
        if finger:
            page.send("Input.dispatchTouchEvent", type="touchStart", touchPoints=[{"x": x, "y": y}])
        else:
            page.send("Input.dispatchMouseEvent", type="mousePressed", x=x, y=y, button="left", clickCount=1)
        for n in range(1, 9):
            at = y + (below + 12 - y) * n / 8
            if finger:
                page.send("Input.dispatchTouchEvent", type="touchMove", touchPoints=[{"x": x, "y": at}])
            else:
                page.send("Input.dispatchMouseEvent", type="mouseMoved", x=x, y=at, button="left", buttons=1)
            time.sleep(0.02)
        assert page.js(SEEN) == ["Hysteria", "Creep", "De Música Ligera"]  # it follows the pointer
        if finger:
            page.send("Input.dispatchTouchEvent", type="touchEnd", touchPoints=[])
        else:
            page.send("Input.dispatchMouseEvent", type="mouseReleased", x=x, y=below + 12, button="left",
                      clickCount=1)
        assert page.wait(f"{STATUS} === 'Moved'", timeout=20), page.js(STATUS)
        assert ("/songbook/move", {"name": "Campfire", "song": "Radiohead - Creep", "position": "2"}) in posted
        assert books_toml(cfg)[0].texts == ("Muse - Hysteria", "Radiohead - Creep", "Soda Stereo - De Música Ligera")
        assert page.js(SET)[1][:2] == ["2", "Creep"]  # numbered by its place now
        # The keyboard: the grip takes ↑ and ↓, the focus stays on it, and a reader hears where the song went.
        page.js("document.querySelector('#songbooks .set-line[data-entry=\"Soda Stereo - De Música Ligera\"] .grip')"
                ".focus()")
        key(page, "ArrowUp", 38)
        assert page.js(TITLES) == ["Hysteria", "De Música Ligera", "Creep"]
        assert page.js("document.activeElement.closest('.set-line').dataset.entry") == "Soda Stereo - De Música Ligera"
        assert page.js("document.querySelector('#songbooks .set-said').textContent") == "De Música Ligera: 2 of 3"
        deadline = time.monotonic() + 20  # sent a moment after the last key, so that ↑ ↑ ↑ is one move
        while len([p for p in posted if p[0] == "/songbook/move"]) < 2 and time.monotonic() < deadline:
            time.sleep(0.05)
        assert page.wait(f"{STATUS} === 'Moved'", timeout=20), page.js(STATUS)
        assert books_toml(cfg)[0].texts == ("Muse - Hysteria", "Soda Stereo - De Música Ligera", "Radiohead - Creep")
        assert page.js(TITLES) == ["Hysteria", "De Música Ligera", "Creep"]
        moves = [fields for where, fields in posted if where == "/songbook/move"]
        assert moves[-1] == {"name": "Campfire", "song": "Soda Stereo - De Música Ligera", "position": "2"}
        assert len(moves) == 2  # one move each: a drag sends its drop alone
        page.js(STILL)
        assert page.js(MOVED) == [], page.js("window.shifts")
        assert page.js("document.documentElement.scrollWidth <= innerWidth")


def test_a_drag_the_browser_cancels_puts_the_line_back_and_sends_nothing(serve, cfg, library, tmp_path):
    url, posted = serve(Fake(cfg))
    with opened(tmp_path, 390, 844) as page:
        page.open(url + CAMPFIRE)
        grip = '#songbooks .set-line[data-entry="Radiohead - Creep"] .grip'
        (x, y), (_, below) = middles(page, grip, '#songbooks .set-line[data-entry="Muse - Hysteria"]')
        page.send("Input.dispatchTouchEvent", type="touchStart", touchPoints=[{"x": x, "y": y}])
        for n in range(1, 9):
            page.send("Input.dispatchTouchEvent", type="touchMove",
                      touchPoints=[{"x": x, "y": y + (below + 12 - y) * n / 8}])
            time.sleep(0.02)
        assert page.js(SEEN) == ["Hysteria", "Creep", "De Música Ligera"]  # it follows the finger
        page.send("Input.dispatchTouchEvent", type="touchCancel", touchPoints=[])
        assert page.wait(f"{SEEN}[0] === 'Creep'", timeout=5), page.js(SEEN)
        time.sleep(0.5)  # a move, if one were sent, is posted by now
        assert page.js(TITLES) == ["Creep", "Hysteria", "De Música Ligera"]
        assert [p for p in posted if p[0] == "/songbook/move"] == []
        assert books_toml(cfg)[0].texts[0] == "Radiohead - Creep"


@SIZES
def test_a_settings_chip_changes_that_songs_key_mode_and_capo(serve, cfg, library, tmp_path, size):
    url, posted = serve(Fake(cfg))
    creep = '#songbooks .set-line[data-entry="Radiohead - Creep"]'
    chip = f"document.querySelector('{creep} .plays').textContent"
    with opened(tmp_path, *size) as page:
        page.open(url + CAMPFIRE)
        assert page.js(SHIFTS)
        assert page.js(chip) == "A Minor"
        page.click(f"{creep} .plays")
        # The menus start where it plays now: A, minor, no capo.
        assert page.js(f"""Array.from(document.querySelectorAll('{creep} .set-edit select'))
            .map((s) => s.options[s.selectedIndex].textContent)""") == ["A", "Minor", "No capo", "Guitar"]
        page.js(f"""(() => {{ const form = document.querySelector('{creep} .set-edit');
            form.elements.key.value = 'G'; form.elements.mode.value = 'dorian'; form.elements.capo.value = '0'; }})()""")
        page.click(f"{creep} .set-edit button[type=submit]")
        assert page.js(f"document.activeElement === document.querySelector('{creep} .plays')")  # the keyboard stays
        assert page.wait(f"{chip} === 'G Dorian'", timeout=20), page.js(chip)  # no capo: none said
        assert ("/songbook/set", {"name": "Campfire", "song": "Radiohead - Creep", "key": "G", "mode": "dorian",
                                  "capo": "0"}) in posted
        assert books_toml(cfg)[0].songs[0].setting == Setting("G", "dorian", 0)
        assert not page.js(f"{SHOWN}('{creep} .set-edit')")  # put away once sent
        # A capo it plays with is said.
        page.click(f"{creep} .plays")
        page.js(f"document.querySelector('{creep} .set-edit').elements.capo.value = '2'")
        page.click(f"{creep} .set-edit button[type=submit]")
        assert page.wait(f"{chip} === 'G Dorian, capo 2'", timeout=20), page.js(chip)
        assert books_toml(cfg)[0].songs[0].setting == Setting("G", "dorian", 2)
        # Back to its own version: the setting goes.
        page.click(f"{creep} .plays")
        page.click(f"{creep} .set-edit .as-own")
        assert page.js(f"document.activeElement === document.querySelector('{creep} .plays')")
        assert page.wait(f"{chip} === 'A Minor'", timeout=20), page.js(chip)
        assert ("/songbook/set", {"name": "Campfire", "song": "Radiohead - Creep", "clear": "1"}) in posted
        assert books_toml(cfg)[0].songs[0].setting is None
        page.js(STILL)
        assert page.js(MOVED) == [], page.js("window.shifts")


def test_a_settings_chip_plays_that_song_on_another_instrument(serve, cfg, library, tmp_path):
    # On an instrument with no capo the key is the key the song sounds in: G dorian at capo 2 is A dorian on the
    # piano, its capo menu off; the instrument is sent once it changes
    url, posted = serve(Fake(cfg))
    creep = '#songbooks .set-line[data-entry="Radiohead - Creep"]'
    chip = f"document.querySelector('{creep} .plays').textContent"
    form = f"document.querySelector('{creep} .set-edit')"
    with opened(tmp_path, 390, 844) as page:
        page.open(url + CAMPFIRE)
        page.click(f"{creep} .plays")
        page.js(f"(() => {{ const f = {form}; f.elements.key.value = 'G'; f.elements.mode.value = 'dorian'; "
                "f.elements.capo.value = '2'; })()")
        page.click(f"{creep} .set-edit button[type=submit]")
        assert page.wait(f"{chip} === 'G Dorian, capo 2'", timeout=20), page.js(chip)
        assert not any("instrument" in fields for _, fields in posted)  # the guitar still: none sent
        page.click(f"{creep} .plays")
        page.js(f"(() => {{ const s = {form}.elements.instrument; s.value = 'piano'; "
                "s.dispatchEvent(new Event('change')); })()")
        assert page.js(f"[{form}.elements.key.value, {form}.elements.capo.disabled]") == ["A", True]
        page.click(f"{creep} .set-edit button[type=submit]")
        assert page.wait(f"{chip} === 'A Dorian, piano'", timeout=20), page.js(chip)
        assert ("/songbook/set", {"name": "Campfire", "song": "Radiohead - Creep", "key": "A", "mode": "dorian",
                                  "instrument": "piano"}) in posted
        assert books_toml(cfg)[0].songs[0].setting == Setting("A", "dorian", None, "piano")  # no capo sent
        # its menus start there; back on a ukulele, which takes a capo, from the key it sounds in, with none
        page.click(f"{creep} .plays")
        assert page.js(f"""Array.from({form}.querySelectorAll('select'))
            .map((s) => s.options[s.selectedIndex].textContent)""") == ["A", "Dorian", "No capo", "Piano"]
        page.js(f"(() => {{ const s = {form}.elements.instrument; s.value = 'ukulele'; "
                "s.dispatchEvent(new Event('change')); })()")
        assert page.js(f"[{form}.elements.key.value, {form}.elements.capo.value, {form}.elements.capo.disabled]") == [
            "A", "0", False]
        page.click(f"{creep} .set-edit button[type=submit]")
        assert page.wait(f"{chip} === 'A Dorian, ukulele'", timeout=20), page.js(chip)
        assert books_toml(cfg)[0].songs[0].setting == Setting("A", "dorian", 0, "ukulele")
        assert page.js("document.documentElement.scrollWidth <= innerWidth")


def index(cfg, *songs):
    """The offline Ultimate Guitar index: each (artist key, song key) with a chords version."""
    from caracole.ug.index import mark_built, upsert_rows

    conn = db.connect(cfg.db_path)
    when = datetime(2026, 10, 19, tzinfo=UTC)
    rows = [(1000 + n, a, s, "chords", f"{a}/{s}-chords-{1000 + n}") for n, (a, s) in enumerate(songs)]
    upsert_rows(conn, rows, "1", when)
    mark_built(conn, when)
    conn.commit()
    conn.close()


@SIZES
def test_add_a_song_searches_everything_and_a_site_song_is_looked_up_then_added(serve, cfg, library, tmp_path, size):
    index(cfg, ("oasis", "wonderwall"), ("radiohead", "creep"))
    runner = Fake(cfg)
    url, posted = serve(runner)
    results = """Array.from(document.querySelectorAll('#songbooks .add-results .line')).map((l) => [
      l.querySelector('h3').textContent, (l.querySelector('.line-action button') || {}).textContent || '',
      Boolean(l.querySelector('.line-action button') && l.querySelector('.line-action button').disabled)])"""
    with opened(tmp_path, *size) as page:
        page.open(url + CAMPFIRE)
        page.click("#songbooks .add-song input")
        page.type("crep")  # your songs as you type, a typo and all, by the search's own rules
        assert page.wait(f"{results}.some((r) => r[0] === 'Creep')", timeout=10), page.js(results)
        assert [r for r in page.js(results) if r[0] == "Creep"][0][1:] == ["In it", True]  # in this songbook already
        page.js("document.querySelector('#songbooks .add-song input').select()")
        page.type("wonderwall")
        assert page.wait(f"{results}.some((r) => r[0] === 'Wonderwall')", timeout=10), page.js(results)
        assert posted == []  # typing posts nothing, and asks no site: /api/search reads the local indexes
        boxes = page.js("[...new Set(performance.getEntriesByType('resource').map((r) => new URL(r.name))"
                        ".filter((u) => u.pathname === '/api/search').map((u) => u.searchParams.get('box')))]")
        assert len(boxes) == 1 and boxes[0], boxes  # Add a song's own box: typed on, it stops its own searches alone
        assert page.js(SHIFTS)
        page.js(STILL)
        page.js("window.shifts = []")  # (typed here without keys, the results coming in count as shifts): from Add on
        n = page.js("Array.from(document.querySelectorAll('#songbooks .add-results .line'))"
                    ".findIndex((l) => l.querySelector('h3').textContent === 'Wonderwall')")
        page.click(f"#songbooks .add-results .line:nth-child({n + 1}) .line-action button")
        assert page.wait(f"{TITLES}.length === 4", timeout=5)  # at once, in its place at the end
        assert page.wait(f"{STATUS} === 'Added·Open songbook'", timeout=30), page.js(STATUS)
        assert posted == [("/songbook/add-song", {"name": "Campfire", "artist": "Oasis", "title": "Wonderwall",
                                                  "ug": "oasis/wonderwall"})]
        assert [c[0] for c in runner.calls] == ["get", "songbook"]  # looked up, then put in the songbook
        assert runner.calls[1][:2] == ["songbook", "add"]
        assert page.wait(f"{SET}[3][3] === 'A Minor'", timeout=10), page.js(SET)
        assert page.js(SET)[3][:3] == ["4", "Wonderwall", "Oasis"]
        assert books_toml(cfg)[0].texts[-1] == "Oasis - Wonderwall"
        page.js(STILL)
        assert page.js(MOVED) == [], page.js("window.shifts")


def test_a_new_songs_pending_line_shows_its_lookup_while_that_waits(serve, cfg, library, tmp_path):
    index(cfg, ("oasis", "wonderwall"))
    hold = threading.Event()
    url, _ = serve(Fake(cfg, hold=hold))
    line = "((document.querySelector('#songbooks .set-line.pending .progress') || {}).textContent || '')"
    try:
        with opened(tmp_path) as page:
            page.open(url + CAMPFIRE)
            page.click("#songbooks .add-song input")
            page.type("wonderwall")
            found = ("Array.from(document.querySelectorAll('#songbooks .add-results .line'))"
                     ".findIndex((l) => l.querySelector('h3').textContent === 'Wonderwall')")
            assert page.wait(f"{found} >= 0", timeout=10)
            page.click(f"#songbooks .add-results .line:nth-child({page.js(found) + 1}) .line-action button")
            # the lookup's own line as it runs, held ("Queued…" until the queue takes it up), never the songbook
            # change's "Queued behind 1 request…"
            assert page.wait(f"{line} === 'Adding to the library…'", timeout=10), page.js(line)
    finally:
        hold.set()


def test_new_songbook_on_an_empty_library_says_why_it_cant_instead_of_doing_nothing(serve, cfg, tmp_path):
    url, _ = serve(Fake(cfg))
    with opened(tmp_path) as page:
        page.open(url + "#tab=songbooks")
        assert page.js(f"{SHOWN}('#songbooks .book-none')")
        assert "no songs" in page.js("document.querySelector('#songbooks .book-none').textContent")
        assert not page.js(f"{SHOWN}('#songbooks .new-book')")  # no button that does nothing


# --- the songbook's files, and the file on disk -----------------------------------------------------------------


@SIZES
def test_exports_are_the_pdf_the_phone_page_and_chordpro(serve, cfg, library, tmp_path, size):
    url, _ = serve(Fake(cfg))
    with opened(tmp_path, *size) as page:
        page.open(url + CAMPFIRE)
        links = page.js("Array.from(document.querySelectorAll('#songbooks .book-files a'))"
                        ".map((a) => [a.textContent, a.getAttribute('href'), a.getAttribute('target')])")
        assert links == [["PDF", "_songbooks/Campfire/songbook.pdf", None],
                         ["Phone page", "_songbooks/Campfire/songbook.html", None],
                         ["ChordPro", "_songbooks/Campfire/songbook.cho", None]]  # each in the same tab
        statuses = page.js("Promise.all(Array.from(document.querySelectorAll('#songbooks .book-files a'))"
                           ".map((a) => fetch(a.href).then((r) => r.status)))")
        assert statuses == [200, 200, 200]  # served, the phone page as the page caracole wrote
        page.click('#songbooks .book-files a[href$="songbook.html"]')
        assert page.wait("location.pathname === '/_songbooks/Campfire/songbook.html'")


@SIZES
def test_the_file_page_shows_the_songbooks_read_only_with_their_commands(conn, cfg, library, tmp_path, size):
    path = write_library_page(cfg.library_dir, build_library_page(conn, cfg, Overrides(), NOW))
    with opened(tmp_path, *size) as page:
        page.open(path.as_uri() + CAMPFIRE)
        assert page.js(SET) == [["1", "Creep", "Radiohead", "A Minor"],
                                ["2", "Hysteria", "Muse", "No sheet yet"],
                                ["3", "De Música Ligera", "Soda Stereo", "A Minor"]]
        # Nothing on it changes anything: no grip, chip to edit, ×, Get it, search to add, nor any form.
        assert page.js("document.querySelectorAll('#songbooks form, #songbooks .grip, #songbooks button.plays, "
                       "#songbooks .set-out, #songbooks .set-get, #songbooks .add-song').length") == 0
        assert page.js("document.querySelectorAll('#songbooks span.plays').length") == 2
        assert page.js("Array.from(document.querySelectorAll('#songbooks .book-files a'))"
                       ".map((a) => a.textContent)") == ["PDF", "Phone page", "ChordPro"]
        commands = page.js("Array.from(document.querySelectorAll('#songbooks .book-commands code'))"
                           ".map((c) => c.textContent)")
        assert commands == [
            "caracole songbook add 'Campfire' 'ARTIST - TITLE'",
            "caracole songbook move 'Campfire' 'Radiohead - Creep' 2",
            "caracole songbook set 'Campfire' 'Radiohead - Creep' --key G --mode dorian --capo 0",
            "caracole songbook remove 'Campfire' 'Radiohead - Creep'",
            "caracole songbook rename 'Campfire' 'NEW NAME'",
            "caracole songbook delete 'Campfire'"], commands
        # + New songbook: Select, on the library, which shows the command to run.
        if size[0] < 900:
            page.click("#songbooks .book-back")  # on a phone, the list is the set list's way back
        page.click("#songbooks .new-book")
        assert page.js(f"{SHOWN}('#list')") and page.js("document.body.classList.contains('selecting')")
        assert page.js("document.documentElement.scrollWidth <= innerWidth")


def test_the_file_pages_commands_run_for_names_that_start_with_a_dash(conn, cfg, tmp_path):
    # The songbook "-M- nights" of a song by -M-, a French artist: each line, run as shown, reaches its command with
    # those names, none taken for an option ("No such option: -M").
    from urllib.parse import quote

    from helpers.cli_lines import parsed

    add_song(conn, "-M-", "Je dis aime")
    make_songbook(songbooks_file(cfg.library_dir), "-M- nights", ["-M- - Je dis aime"])
    conn.commit()
    path = write_library_page(cfg.library_dir, build_library_page(conn, cfg, Overrides(), NOW))
    with opened(tmp_path) as page:
        page.open(path.as_uri() + "#tab=songbooks&book=" + quote("-M- nights"))
        assert page.wait("document.querySelectorAll('#songbooks .book-commands code').length === 6")
        commands = page.js("Array.from(document.querySelectorAll('#songbooks .book-commands code'))"
                           ".map((c) => c.textContent)")
    name, song = "-M- nights", "-M- - Je dis aime"
    assert [parsed(line) for line in commands] == [
        (("songbook", "add"), {"name": name, "songs": ("ARTIST - TITLE",)}),
        (("songbook", "move"), {"name": name, "song": song, "position": 2}),
        (("songbook", "set"), {"name": name, "song": song, "key": "G", "mode": "dorian", "capo": 0, "instrument": None,
                                  "clear": False}),
        (("songbook", "remove"), {"name": name, "songs": (song,)}),
        (("songbook", "rename"), {"name": name, "new": "NEW NAME"}),
        (("songbook", "delete"), {"name": name})], commands


# --- touch, contrast, dark mode ---------------------------------------------------------------------------------


@pytest.mark.parametrize("size,dark", [((390, 844), False), ((390, 844), True), ((1280, 800), False),
                                       ((1280, 800), True)], ids=["phone", "phone-dark", "laptop", "laptop-dark"])
def test_the_tab_meets_touch_contrast_and_dark_mode(serve, cfg, library, tmp_path, size, dark):
    url, _ = serve(Fake(cfg))
    with opened(tmp_path, *size, dark=dark) as page:
        page.open(url + CAMPFIRE)
        page.click('#songbooks .set-line[data-entry="Radiohead - Creep"] .plays')  # its menus, measured too
        page.js("document.querySelector('#songbooks details.book-more').open = true")
        page.click("#songbooks .add-song input")
        page.type("musica")
        assert page.wait("document.querySelector('#songbooks .add-results .line') !== null", timeout=10)
        weak = page.js(weak_edges())
        assert weak == [], weak  # every field and menu's edge 3:1 against what is around it
        if size[0] < 500:  # a touch screen: a thumb's target, each
            short = page.js(small_targets())
            assert short == [], short
        else:  # a mouse: the set list's lines as dense as the library's
            tall = page.js("Array.from(document.querySelectorAll('#songbooks .set-line:not(.editing)'))"
                           ".map((l) => Math.round(l.getBoundingClientRect().height))")
            page.js("document.getElementById('tab-library').click()")
            line = page.js("Math.round(document.querySelector('#list .line').getBoundingClientRect().height)")
            assert line <= 26, line  # the library's own line, about 25 px with its border
            assert max(tall) <= line, (tall, line)
        colours = page.js("""(() => { const c = (n) => getComputedStyle(n);
            return [c(document.body).backgroundColor, c(document.querySelector('#songbooks .book')).color]; })()""")
        lum = [sum(int(v) for v in c[c.index("(") + 1:c.index(")")].split(",")[:3]) / 3 for c in colours]
        assert (lum[0] < 60 and lum[1] > 180) if dark else (lum[0] > 200 and lum[1] < 80), colours
        assert page.js("document.documentElement.scrollWidth <= innerWidth")


# --- a song's Guitar Pro mark -----------------------------------------------------------------------------------


@pytest.fixture
def guitars(conn, cfg, library):
    """Creep with a Guitar Pro file caracole keeps (gtptabs.com's); De Música Ligera and Hysteria with none."""
    keep_guitar(conn, cfg, library["Creep"], SYNTHETIC.read_bytes(), name="guitar-1.gp")
    conn.commit()
    return library


# Each song of the set list: its title, then its mark's address, classes, name, download, target and rel, and how
# its guitar is drawn (filled, or "none" for an outline); its title alone without one.
MARKS = """Array.from(document.querySelectorAll('#songbooks .book .set-line:not(.gone)')).map((li) => {
  const a = li.querySelector('.set-gp'), title = li.querySelector('h3').textContent;
  return a ? [title, a.getAttribute('href'), a.className, a.getAttribute('aria-label'), a.getAttribute('download'),
              a.target, a.rel, getComputedStyle(a.querySelector('svg path')).fill === 'none' ? 'outline' : 'solid']
    : [title]; })"""
WITHOUT = ["De Música Ligera"]


@SIZES
def test_a_songs_guitar_pro_mark_opens_its_page_served(serve, cfg, guitars, tmp_path, size):
    url, _ = serve(Fake(cfg), alphatab=alphatab_dir())
    with opened(tmp_path, *size) as page:
        page.open(url + CAMPFIRE)
        assert page.js(MARKS) == [
            ["Creep", "guitar?file=Radiohead%2FCreep%2Fguitar-1.gp", "set-gp",
             "Guitar Pro tab: Radiohead - Creep.gp, open it in the browser", None, "", "", "solid"],
            ["Hysteria"], WITHOUT]
        assert page.js("document.querySelector('#songbooks .set-gp').title") == "Guitar Pro tab: open it in the browser"
        assert page.js("fetch(document.querySelector('#songbooks .set-gp').href).then((r) => r.status)") == 200
        # Next to its title, on its line, before what else the line holds; a key's reach (Tab) like any link.
        beside = page.js("""Array.from(document.querySelectorAll('#songbooks .set-gp')).map((a) => {
            const li = a.closest('.set-line'), box = a.getBoundingClientRect();
            const title = li.querySelector('.set-title').getBoundingClientRect();
            const after = li.querySelector('.set-act, .set-by').getBoundingClientRect();
            return box.left >= title.right - 0.5 && box.top < title.bottom && box.bottom > title.top
              && (after.top >= box.bottom - 0.5 || after.left >= box.right - 0.5); })""")
        assert beside == [True], beside
        assert page.js("document.querySelector('#songbooks .set-gp').tabIndex") == 0
        if size[0] < 500:  # a touch screen: a thumb's target, and these titles still whole beside it
            short = page.js(small_targets())
            assert short == [], short
            assert page.js("Array.from(document.querySelectorAll('#songbooks .set-line h3'))"
                           ".filter((h) => h.scrollWidth > h.clientWidth).map((h) => h.textContent)") == []
        else:  # a mouse: the set list's lines as dense as without it
            tall = page.js("Array.from(document.querySelectorAll('#songbooks .set-line'))"
                           ".map((l) => Math.round(l.getBoundingClientRect().height))")
            assert max(tall) <= 26, tall
        assert page.js("document.documentElement.scrollWidth <= innerWidth")
        page.click("#songbooks .set-gp")
        assert page.wait("location.pathname === '/guitar'")


@pytest.mark.parametrize("where", ["file", "served without alphaTab"])
def test_a_kept_guitar_pro_files_mark_downloads_it_where_no_page_shows_it(serve, conn, cfg, guitars, tmp_path, where):
    if where == "file":
        address = write_library_page(cfg.library_dir, build_library_page(conn, cfg, Overrides(), NOW)).as_uri()
    else:
        address, _ = serve(Fake(cfg))
    with opened(tmp_path) as page:
        page.open(address + CAMPFIRE)
        assert page.js(MARKS) == [
            ["Creep", "Radiohead/Creep/guitar-1.gp", "set-gp", "Guitar Pro tab: Radiohead - Creep.gp, download it",
             "Radiohead - Creep.gp", "", "", "solid"],
            ["Hysteria"], WITHOUT]
        assert page.js("document.querySelector('#songbooks .set-gp').title") == \
            "Guitar Pro tab: download Radiohead - Creep.gp"
        if where != "file":  # the file itself, as the library's line links it
            assert page.js("fetch(document.querySelector('#songbooks .set-gp').href).then((r) => r.status)") == 200


# --- the songbooks' changes: where they come from, and how they end ---------------------------------------------


def new_songbook(page):
    """+ New songbook, from wherever the page is: the Songbooks tab, its list (on a phone, back from a set list), then
    its button, which turns Select on, on the library, its bar ready for the name (unfolded on a phone)."""
    page.click("#tab-songbooks")
    if not page.js(f"{SHOWN}('#songbooks .new-book')"):
        page.click("#songbooks .book-back")
    page.click("#songbooks .new-book")
    assert page.wait("document.body.classList.contains('selecting')")


def test_select_makes_a_songbook_and_the_tab_opens_on_it(serve, cfg, library, tmp_path):
    hold = threading.Event()
    url, posted = serve(Fake(cfg, hold=hold))
    with opened(tmp_path, 390, 844) as page:
        page.open(url)
        assert page.js(SHIFTS) and page.js(ANSWERED)
        new_songbook(page)
        page.click('#list [data-id="%d"] .pick' % library["Hysteria"].id)
        page.click('#list [data-id="%d"] .pick' % library["Creep"].id)
        page.click(".pick-name")
        page.type("Beach nights")
        page.click(".pickbar-form button[type=submit]")
        # The tab opens on the songbook at once, its songs in the order picked, and says how it goes.
        assert page.wait(f"{SHOWN}('#songbooks') && document.querySelector('#songbooks .book h2').textContent === "
                         "'Beach nights'", timeout=10)
        # It opens on the server's answer to the tap (OWN_MOVES). The make is held until then, and ends after.
        tab = page.js(DRAWN)
        hold.set()
        assert page.js(TITLES) == ["Hysteria", "Creep"]
        assert page.wait(f"{STATUS} === 'Made·Open songbook'", timeout=20), page.js(STATUS)
        assert page.js(TITLES) == ["Hysteria", "Creep"] and "book=Beach+nights" in page.js("location.hash")
        assert [b[0] for b in page.js(BOOKS)] == ["Campfire", "Road trip", "Beach nights"]
        assert not page.js("document.body.classList.contains('selecting')")
        assert page.js("Array.from(document.querySelectorAll('.pick-into option')).map((o) => o.value)") == [
            "", "Campfire", "Road trip", "Beach nights"]
        assert posted[0][0] == "/songbook/make"
        page.js(STILL)
        assert page.js(OWN_MOVES.format(moved=MOVED, tab=tab)) == [], page.js("window.shifts")


def test_select_adds_to_a_songbook_there_is_and_the_tab_opens_on_it(serve, cfg, library, tmp_path):
    hold = threading.Event()
    url, posted = serve(Fake(cfg, hold=hold))
    with opened(tmp_path) as page:
        page.open(url)
        assert page.js(SHIFTS) and page.js(ANSWERED)
        new_songbook(page)
        page.click('#list [data-id="%d"] .pick' % library["Creep"].id)
        page.js("(() => { const into = document.querySelector('.pick-into'); into.value = 'Road trip';"
                " into.dispatchEvent(new Event('change')); })()")
        page.click(".pickbar-form button[type=submit]")
        assert page.wait(f"{SHOWN}('#songbooks') && document.querySelector('#songbooks .book h2').textContent === "
                         "'Road trip'", timeout=10)
        tab = page.js(DRAWN)  # opened on the server's answer to the tap, as a make's is
        hold.set()
        assert page.js(TITLES) == ["De Música Ligera", "Creep"]  # at its end, at once
        assert page.wait(f"{STATUS} === 'Added·Open songbook'", timeout=20), page.js(STATUS)
        assert page.js(SET)[1] == ["2", "Creep", "Radiohead", "A Minor"]
        assert posted == [("/songbook/add", {"name": "Road trip", "songs": str(library["Creep"].id)})]
        page.js(STILL)
        assert page.js(OWN_MOVES.format(moved=MOVED, tab=tab)) == [], page.js("window.shifts")


def test_select_refused_says_why_in_its_bar_and_keeps_the_picks(serve, cfg, library, tmp_path):
    url, _ = serve(Fake(cfg))
    with opened(tmp_path) as page:
        page.open(url)
        new_songbook(page)
        page.click('#list [data-id="%d"] .pick' % library["Creep"].id)
        page.click(".pick-name")
        page.type("CAMPFIRE")
        page.click(".pickbar-form button[type=submit]")
        assert page.wait("document.querySelector('.pick-error').textContent !== ''", timeout=10)
        assert "is there already" in page.js("document.querySelector('.pick-error').textContent")
        assert page.js("document.body.classList.contains('selecting')") and page.js(f"{SHOWN}('#list')")
        assert page.js("document.querySelector('.pick-count').textContent") == "1 selected"
        assert not page.js("document.querySelector('.pickbar-form button[type=submit]').disabled")


@SIZES
def test_a_make_that_fails_keeps_its_songbook_says_why_and_gives_the_picks_back(serve, cfg, library, tmp_path, size):
    # Select's make, queued, then failed where it ran: songbooks.toml hasn't got the songbook, which was never deleted.
    # Its line and its set list stay, its status line says why (with Details), and the Select bar has its ticks again.
    why = "songbooks.toml can't be written: read-only file system."
    runner = Fake(cfg, fail={"Brand new": why})
    url, _ = serve(runner)
    with opened(tmp_path, *size) as page:
        page.open(url)
        new_songbook(page)
        page.click('#list [data-id="%d"] .pick' % library["Hysteria"].id)
        page.click('#list [data-id="%d"] .pick' % library["Creep"].id)
        page.click(".pick-name")
        page.type("Brand new")
        page.click(".pickbar-form button[type=submit]")
        assert page.wait(f"{SHOWN}('#songbooks') && document.querySelector('#songbooks .book h2').textContent === "
                         "'Brand new'", timeout=5)
        assert page.wait(f"{STATUS}.includes(\"songbooks.toml can't be written\")", timeout=20), page.js(STATUS)
        page.js(STILL)
        page.click("#songbooks .book h2")  # a click, and a key: nothing that says so goes
        page.press("Tab")
        assert "Details" in page.js(STATUS) and why in page.js(STATUS)
        assert page.js("document.querySelector('#songbooks .book h2').textContent") == "Brand new"
        assert page.js(TITLES) == ["Hysteria", "Creep"]
        books = page.js(BOOKS)
        assert [b[0] for b in books] == ["Campfire", "Road trip", "Brand new"], books
        assert books[2][1] == "2 songs · couldn't be made", books
        # Nothing on it to change but by making it again, from the Select bar (+ New songbook), which has the picks
        # and says why.
        assert page.js("document.querySelector('#songbooks .book .book-files .hint').textContent") == (
            "Not made: + New songbook can make it again.")
        assert page.js("document.querySelectorAll('#songbooks .book .set-line button:not([disabled]), "
                       "#songbooks .book .book-more button:not([disabled])').length") == 0
        assert page.js(f"!{SHOWN}('#songbooks .book .add-song')")
        assert page.js("document.querySelector('.pick-count').textContent") == "2 selected"
        assert page.js("document.querySelector('.pick-name').value") == "Brand new"
        assert why in page.js("document.querySelector('.pick-error').textContent")
        assert [b.name for b in books_toml(cfg)] == ["Campfire", "Road trip"]
        # Made again once the file can be written: the songbook as new, its controls back.
        runner.fail.clear()
        new_songbook(page)
        assert page.js("document.querySelector('.pick-name').value") == "Brand new"
        page.click(".pickbar-form button[type=submit]")
        assert page.wait(f"{STATUS} === 'Made·Open songbook'", timeout=20), page.js(STATUS)
        assert page.js(TITLES) == ["Hysteria", "Creep"] and page.js(f"{SHOWN}('#songbooks .book .add-song')")
        assert page.js("document.querySelectorAll('#songbooks .book .set-line .grip:not([disabled])').length") == 2
        assert re.fullmatch(r"2 songs · 1 without a sheet · changed \S+", page.js(BOOKS)[2][1]), page.js(BOOKS)
    assert [b.name for b in books_toml(cfg)] == ["Campfire", "Road trip", "Brand new"]


@SIZES
def test_a_songbook_that_couldnt_be_made_goes_once_made_under_another_name_or_forgotten(serve, cfg, library,
                                                                                        tmp_path, size):
    # Its picks given back, made under another name: the one that couldn't be made goes, the new one in its place.
    # Another that couldn't be made, not made again: Forget it takes it off the tab, the list back.
    why = "songbooks.toml can't be written: read-only file system."
    runner = Fake(cfg, fail={"Brand new": why, "Other": why})
    url, _ = serve(runner)

    def make(name, *titles):
        new_songbook(page)
        for title in titles:
            page.click('#list [data-id="%d"] .pick' % library[title].id)
        page.js("document.querySelector('.pick-name').value = ''")
        page.click(".pick-name")
        page.type(name)
        page.click(".pickbar-form button[type=submit]")
        assert page.wait(f"{SHOWN}('#songbooks') && document.querySelector('#songbooks .book h2').textContent === "
                         f"{json.dumps(name)}", timeout=5)

    with opened(tmp_path, *size) as page:
        page.open(url)
        make("Brand new", "Hysteria", "Creep")
        assert page.wait(f"{STATUS}.includes(\"songbooks.toml can't be written\")", timeout=20), page.js(STATUS)
        make("Beach nights")  # the picks it gave back, under another name
        assert page.wait(f"{STATUS} === 'Made·Open songbook'", timeout=20), page.js(STATUS)
        assert page.js(TITLES) == ["Hysteria", "Creep"]
        assert [b[0] for b in page.js(BOOKS)] == ["Campfire", "Road trip", "Beach nights"], page.js(BOOKS)
        make("Other", "De Música Ligera")
        assert page.wait(f"{STATUS}.includes(\"songbooks.toml can't be written\")", timeout=20), page.js(STATUS)
        assert page.js(BOOKS)[3] == ["Other", "1 song · couldn't be made"], page.js(BOOKS)
        page.click("#songbooks .book .book-forget")
        open_now = "((document.querySelector('#songbooks .book h2') || {}).textContent || '')"
        assert page.wait(f"{open_now} !== 'Other'", timeout=5)
        assert page.js(open_now) == ("" if size[0] < 900 else "Campfire")  # the list; beside it, the first one
        assert [b[0] for b in page.js(BOOKS)] == ["Campfire", "Road trip", "Beach nights"], page.js(BOOKS)
        assert "book=" not in page.js("location.hash")
        assert page.js("document.activeElement.closest('#songbooks') !== null")  # the focus stays on the tab
    assert [b.name for b in books_toml(cfg)] == ["Campfire", "Road trip", "Beach nights"]


def test_renaming_then_deleting_a_songbook_stay_on_the_tab(serve, cfg, library, tmp_path):
    url, _ = serve(Fake(cfg))
    with opened(tmp_path) as page:
        page.open(url + CAMPFIRE)
        assert page.js(SHIFTS)
        page.click("#songbooks details.book-more > summary")
        page.click('#songbooks form[action="/songbook/rename"] input[name="new"]')
        page.js("document.querySelector('#songbooks form[action=\"/songbook/rename\"] input[name=\"new\"]').select()")
        page.type("Beach nights")
        page.click('#songbooks form[action="/songbook/rename"] button')
        assert page.wait(f"{STATUS} === 'Renamed'", timeout=20), page.js(STATUS)
        assert page.js("document.querySelector('#songbooks .book h2').textContent") == "Beach nights"
        assert [b[0] for b in page.js(BOOKS)] == ["Beach nights", "Road trip"]
        assert "book=Beach+nights" in page.js("location.hash")
        assert page.js("Array.from(document.querySelectorAll('.pick-into option')).map((o) => o.value)") == [
            "", "Beach nights", "Road trip"]
        if not page.js("document.querySelector('#songbooks details.book-more').open"):
            page.click("#songbooks details.book-more > summary")
        page.click('#songbooks form[action="/songbook/delete"] input[type="checkbox"]')
        page.click('#songbooks form[action="/songbook/delete"] button')
        assert page.wait(f"{STATUS} === 'Deleted'", timeout=20), page.js(STATUS)
        # Deleted: it says so where it was, nothing left on it to change, until your next click or key.
        assert page.js("document.querySelectorAll('#songbooks .book form, #songbooks .book .grip').length") == 0
        assert books_toml(cfg) == [books_toml(cfg)[0]] and books_toml(cfg)[0].name == "Road trip"
        page.js(STILL)
        assert page.js(MOVED) == [], page.js("window.shifts")


def test_a_refused_change_says_why_where_it_was_asked(serve, cfg, library, tmp_path):
    url, _ = serve(Fake(cfg))
    with opened(tmp_path) as page:
        page.open(url + CAMPFIRE)
        page.click("#songbooks details.book-more > summary")
        page.js("document.querySelector('#songbooks form[action=\"/songbook/rename\"] input[name=\"new\"]').value = "
                "'.hidden'")
        page.click('#songbooks form[action="/songbook/rename"] button')
        assert page.wait(f"{STATUS}.includes('dot')", timeout=10), page.js(STATUS)
        assert page.js("document.querySelector('#songbooks .book-status').dataset.tone") == "failed"
        assert page.js("Array.from(document.querySelectorAll('#songbooks .book button')).every((b) => !b.disabled)")


def test_a_failed_change_says_why_on_its_songbook_with_its_details(serve, cfg, library, tmp_path):
    url, _ = serve(Fake(cfg, fail={"Campfire": "songbooks.toml can't be written: read-only file system."}))
    with opened(tmp_path) as page:
        page.open(url + CAMPFIRE)
        page.click('#songbooks .set-line[data-entry="Muse - Hysteria"] .set-out')
        assert page.wait(f"{STATUS}.includes(\"songbooks.toml can't be written\")", timeout=20), page.js(STATUS)
        assert "Details" in page.js(STATUS)
        assert page.js(TITLES) == ["Creep", "Hysteria", "De Música Ligera"]  # still in it


def test_a_change_on_its_way_when_the_page_loads_shows_on_its_songbook(serve, cfg, library, tmp_path):
    from caracole.web.app import Request

    def move(app):  # from another tab, say
        sent = {"host": "127.0.0.1", "content-type": "application/x-www-form-urlencoded",
                "sec-fetch-site": "same-origin"}
        body = "csrf=tok&name=Campfire&song=Muse+-+Hysteria&position=3".encode()
        assert app.handle(Request("POST", "/songbook/move", sent, body)).status == 303

    hold = threading.Event()
    url, _ = serve(Fake(cfg, hold=hold), before=move)
    with opened(tmp_path) as page:
        page.open(url + CAMPFIRE)
        assert page.js(STATUS) in ("Queued…", "Moving the song…")
        hold.set()
        assert page.wait(f"{STATUS} === 'Moved'", timeout=20), page.js(STATUS)
        assert page.js(TITLES) == ["Creep", "De Música Ligera", "Hysteria"]


@SIZES
def test_get_the_missing_songs_looks_each_up_then_makes_the_songbook_again(serve, cfg, conn, library, tmp_path, size):
    uprising = add_song(conn, "Muse", "Uprising")
    add_to_songbook(songbooks_file(cfg.library_dir), "Campfire", ["Pixies - Debaser", "Muse - Uprising"])
    conn.commit()
    runner = Fake(cfg)
    url, posted = serve(runner)
    get = "#songbooks .book form.get-missing button"
    lines = """Array.from(document.querySelectorAll('#songbooks .set-line')).map((li) => [
      li.querySelector('h3').textContent, (li.querySelector('.progress') || {}).textContent || '',
      (li.querySelector('.plays, .badge.missing') || {}).textContent || ''])"""
    with opened(tmp_path, *size) as page:
        page.open(url + CAMPFIRE)
        assert page.js(f"document.querySelector({json.dumps(get)}).textContent") == "Get the 2 missing songs now"
        assert page.js(SHIFTS)
        page.click(get)
        assert page.wait(f"{STATUS}.startsWith('Made')", timeout=30), (page.js(STATUS), page.js(lines))
        assert page.wait(f"{lines}[4][1].startsWith('Ready')", timeout=10), page.js(lines)
        shown = page.js(lines)
        assert [s[0] for s in shown] == ["Creep", "Hysteria", "De Música Ligera", "Debaser", "Uprising"]
        assert shown[1][1].startswith("Ready") and shown[4][1].startswith("Ready"), shown
        assert shown[1][2] == "A Minor" and shown[3][2] == "Not in the library", shown
        # Nothing left to get: its button goes (its room kept until your next click, so nothing moves).
        assert page.js(f"((b) => !b || getComputedStyle(b).visibility === 'hidden')(document.querySelector("
                       f"{json.dumps(get)}))")
        assert [c[:2] for c in runner.calls] == [["get", "--progress"], ["get", "--progress"], ["songbook", "render"]]
        assert runner.calls[1][-1] == "Uprising" and uprising
        # One at a time on the set list's Get it: that song alone, then the songbook again.
        assert posted == [("/songbook/get", {"name": "Campfire"})]
        assert page.js("document.getElementById('tray').hidden")  # the songbook says how they go: no tray
        page.js(STILL)
        assert page.js(MOVED) == [], page.js("window.shifts")


def test_a_song_fetched_from_the_library_shows_with_its_sheet_in_its_songbooks(serve, cfg, library, tmp_path):
    # Fetch now on the library's line: a lookup alone, no songbook's change. Once it is over the set list it is in
    # draws again, so it offers no Get it the server would refuse ("has a sheet already").
    runner = Fake(cfg)
    url, posted = serve(runner)
    hysteria = '#songbooks .set-line[data-entry="Muse - Hysteria"]'
    line = f'#list [data-id="{library["Hysteria"].id}"]'
    get = "#songbooks .book form.get-missing button"
    with opened(tmp_path, 1280, 800) as page:
        page.open(url + CAMPFIRE)
        assert page.js(SET)[1] == ["2", "Hysteria", "Muse", "No sheet yet"]
        assert page.js(f"document.querySelector('{hysteria} .set-get') !== null")
        page.click("#tab-library")
        page.click(f"{line} form.fetch button")
        assert page.wait(f"document.querySelector('{line} .progress').textContent.startsWith('Ready')", timeout=30)
        page.click("#tab-songbooks")
        assert page.js(SET)[1] == ["2", "Hysteria", "Muse", "A Minor"], page.js(SET)
        assert page.js(f"document.querySelector('{hysteria} .set-get') === null")
        assert page.js(f"((b) => !b || getComputedStyle(b).visibility === 'hidden')(document.querySelector("
                       f"{json.dumps(get)}))")
        assert [p[0] for p in posted] == ["/fetch"] and [c[0] for c in runner.calls] == ["get"]


def test_a_set_lists_get_it_looks_that_song_up(serve, cfg, library, tmp_path):
    runner = Fake(cfg)
    url, posted = serve(runner)
    hysteria = '#songbooks .set-line[data-entry="Muse - Hysteria"]'
    with opened(tmp_path, 390, 844) as page:
        page.open(url + CAMPFIRE)
        page.click(f"{hysteria} .set-get")
        assert page.wait(f"document.querySelector('{hysteria} .plays') !== null", timeout=30)
        assert page.js(f"document.querySelector('{hysteria} .progress').textContent").startswith("Ready")
        assert posted == [("/songbook/get", {"name": "Campfire", "song": str(library["Hysteria"].id)})]
        assert [c[0] for c in runner.calls] == ["get", "songbook"]
