"""A song's lyrics looked up under another name on the library page caracole serve serves, in a real browser.

A song's card has a panel (library.js ``lyricsPanel``, the served data's ``server.lyricsSearch``): open in what needs
you, above Transcribe the lyrics, for a song with no lyrics found, else folded right under its foot. Its Artist and Title are
the name last asked (``[lyrics]``' ``as``), else the song's own; only its Search, a press, sends ``POST
/lyrics/search`` (opening the card and typing send nothing). Its line says the sites are asked while the search runs,
then the panel reads ``GET /api/lyrics/search`` again and lists a row a record, the best fit first, each with Use
these lyrics (``POST /lyrics/pick`` in place, the song's line then following the pick); a site that failed is said,
never "nothing found"; a search over a week old lists its rows with no Use; a record picked that gave no lyrics says
so, with Clear the pick (``POST /lyrics/clear``). The file on disk and the phone's page have none of it. A real
``caracole serve`` serves the page; its queue runs ``FakeLyrics``, which keeps a search as the command does.
"""

from __future__ import annotations

import json
import threading
import time
from datetime import UTC, datetime, timedelta
from urllib.parse import unquote

import pytest
from helpers import cards
from helpers.browser import CHROMIUM_MARKS
from test_autochords_transcript import youtube_song
from test_library_card import run
from test_library_page import attribute_of
from test_web_page_steps import driven
import test_web_page_transcribe as transcribe_page
from test_web_page_transcribe import line, opened, over, read_again
from test_web_page_youtube import serve

from caracole import db, stamps
from caracole.db import kv_set_json
from caracole.get import PROGRESS_PREFIX
from caracole.library_page import WebControls
from caracole.lyrics_search import KV, Row, Search, last_line
from caracole.overrides import set_lyrics_name, set_lyrics_record
from caracole.songs import get_song, update_song

from conftest import add_song

pytestmark = CHROMIUM_MARKS  # every test here drives the page in Chromium
# test_web_page_transcribe's fixtures: a caracole that transcribes (``able``), and a Chromium to drive.
able, browser = transcribe_page.able, transcribe_page.browser

ARTIST, TITLE = "孟维来", "野人『不再借世人的手』『动态歌词MV』"
ASKED = ("孟维来", "野人")


def found_rows() -> tuple[Row, ...]:
    """What the three sites list under 孟维来 - 野人, as lyrics_search.py orders them: the best fit first."""
    return (Row("lrclib:28399373", "lrclib", *ASKED, "野人", 226.0, True, best=True, fits=True),
            Row("lrclib:31", "lrclib", "孟维来", "野人 (Live)", "野人 Live", 271.0, True),
            Row("megalobiz:8", "megalobiz", "", "野人", "", 224.0, True),
            Row("azlyrics:mengweilai/yeren", "azlyrics", *ASKED, "", None, False, fits=True))


def a_search(asked=ASKED, *, rows=None, state=None, said=None, at=None) -> Search:
    state = state or {"lrclib": "rows", "megalobiz": "rows", "azlyrics": "rows"}
    said = said or {"lrclib": "listed 2", "megalobiz": "listed 1", "azlyrics": "listed 1"}
    return Search(at=stamps.stamp(at or datetime.now(UTC)), asked=asked, length=225.0, lrclib={"q": " ".join(asked)},
                  rows=found_rows() if rows is None else rows, said=said, state=state, instrumental=2)


class FakeLyrics:
    """``caracole lyrics --song --as``: waits for ``hold``, then keeps ``search`` (made under the name asked) in kv
    as lyrics_search.py keeps it and says its last line. ``--record --progress``: the pick's stages, the record
    written under ``[lyrics]`` and the song's lyrics found, as lyrics_pick.py leaves them. ``--clear``: the record
    taken out and the song pending."""

    def __init__(self):
        self.ran: list[tuple[str, ...]] = []
        self.hold = threading.Event()
        self.hold.set()
        self.search = lambda asked: a_search(asked)
        self.cfg = None
        self.song = None

    def _in_the_book(self, change) -> None:
        conn = db.connect(self.cfg.db_path)
        try:
            change(conn, get_song(conn, self.song.id))
        finally:
            conn.close()

    def __call__(self, args, emit):
        self.ran.append(tuple(args))
        asked = next((a.removeprefix("--as=") for a in args if a.startswith("--as=")), None)
        record = next((a.removeprefix("--record=") for a in args if a.startswith("--record=")), None)
        if asked is not None:
            self.hold.wait(30)
            search = self.search(tuple(asked.split(" - ", 1)))
            self._in_the_book(lambda conn, song: kv_set_json(conn, f"{KV}{song.id}", search.as_json()))
            emit(last_line(search))
            return 0
        if record is not None:
            def stage(name, state, detail=""):
                emit(PROGRESS_PREFIX + json.dumps({"stage": name, "state": state, "detail": detail}))

            emit(PROGRESS_PREFIX + json.dumps({"song": {"id": self.song.id, "display": self.song.display}}))
            stage("song", "done", "in the book")
            set_lyrics_record(self.cfg.overrides_file, self.song.display, record)
            self._in_the_book(lambda conn, song: update_song(conn, song.id, lyrics_status="found"))
            stage("lyrics", "done", "Timed lyrics from LRCLIB: 孟维来 - 野人 (野人, 3:46)")
            for name in ("chords", "pdf", "pages"):
                stage(name, "skipped", "no audio to make an auto sheet from")
            return 0
        from caracole.lyrics_pick import clear_pick
        from caracole.overrides import load_overrides

        said = []
        self._in_the_book(lambda conn, song: said.append(
            clear_pick(self.cfg, conn, song, load_overrides(self.cfg.overrides_file))))
        emit(str(said[0]))
        return 0


@pytest.fixture
def lyrics(able, tmp_path):
    made = FakeLyrics()
    conn = db.connect(able.db_path)
    try:
        made.cfg, made.song = able, youtube_song(conn, tmp_path, ARTIST, TITLE)  # no lyrics; offered a transcription
    finally:
        conn.close()
    yield made
    made.hold.set()


@pytest.fixture
def live(able, lyrics):
    server, queue, base, posted = serve(able, lyrics)
    yield base, posted, queue
    server.shutdown()
    server.server_close()
    lyrics.hold.set()
    queue.stop()


def in_book(cfg, change):
    conn = db.connect(cfg.db_path)
    try:
        return change(conn)
    finally:
        conn.close()


PANEL = "details.lyrics-search"


def queued(queue, title: str, timeout: float = 10.0):
    """The queue's job whose title begins with ``title``, once it is there (the server queues it after the POST)."""
    deadline = time.monotonic() + timeout
    while not (jobs := [job for job in queue.snapshot() if job.title.startswith(title)]):
        assert time.monotonic() < deadline, [job.title for job in queue.snapshot()]
        time.sleep(0.05)
    return jobs[0]


def tone(song) -> str:
    """The tone of the song's request line, none before it has one."""
    return f"((document.querySelector({json.dumps(line(song) + ' .progress')}) || {{}}).dataset || {{}}).tone"


def panel_of(card: str) -> str:
    return json.dumps(f"{card} {PANEL}")


def drawn(page, card: str) -> None:
    """Wait until the card's panel has drawn what GET /api/lyrics/search answered (its ``data-read``)."""
    assert page.wait(f"(document.querySelector({panel_of(card)}) || {{dataset: {{}}}}).dataset.read === '1'")


def rows_of(card: str) -> str:
    """Each row of the panel's list: its site's name, its names, its facts, its marks, and its button's words and
    label (none: no button)."""
    return (f"[...document.querySelectorAll({json.dumps(card + ' ' + PANEL + ' ol.lyrics-rows > li')})].map((li) => {{"
            "const t = (s) => (li.querySelector(s) || {}).textContent || ''; "
            "const b = li.querySelector('button'); "
            "return [t('.lyrics-site-name'), t('.lyrics-name'), t('.lyrics-meta'), "
            "[...li.querySelectorAll('.lyrics-tag')].map((m) => m.textContent), "
            "b ? [b.textContent, b.getAttribute('aria-label')] : null]; })")


def text_of(card: str, selector: str) -> str:
    return f"(document.querySelector({json.dumps(card + ' ' + PANEL + ' ' + selector)}) || {{}}).textContent"


def fields_of(card: str) -> str:
    return (f"['artist', 'title'].map((n) => document.querySelector({panel_of(card)} + "
            "` input[name=${n}]`).value)")


def type_into(page, card: str, name: str, text: str) -> None:
    page.js(f"(() => {{ const f = document.querySelector({panel_of(card)} + ' input[name={name}]'); "
               "f.focus(); f.select(); })()")
    page.type(text)


def test_a_song_with_no_lyrics_has_the_search_above_transcribe_filled_in(able, live, lyrics, browser):
    base, posted, _ = live
    song = lyrics.song
    browser.open(base)
    card = opened(browser, song)
    assert browser.wait(f"document.querySelector({panel_of(card)}) !== null")
    drawn(browser, card)
    # Open, in what needs you, before Transcribe the lyrics: the lyrics sites before Whisper.
    assert browser.js(f"document.querySelector({panel_of(card)}).open") is True
    assert browser.js(f"document.querySelector({panel_of(card)} + ' > summary').textContent") == (
        "No lyrics found. Look them up under another name")
    order = browser.js(f"(() => {{ const p = document.querySelector({panel_of(card)}); "
                       f"const t = document.querySelector({json.dumps(card + ' form.transcribe')}); "
                       "return !!t && !!(p.compareDocumentPosition(t) & Node.DOCUMENT_POSITION_FOLLOWING) "
                       "&& !p.closest('.foot'); })()")
    assert order is True
    # The song's own name, nothing asked yet.
    assert browser.js(fields_of(card)) == [ARTIST, TITLE]
    assert browser.js(text_of(card, "ol.lyrics-rows")) in (None, "")
    # Typing in its fields sends nothing: only Search does.
    type_into(browser, card, "title", "野人")
    assert not browser.wait("false", timeout=1.0)
    assert posted == [] and f"/api/lyrics/search?song={song.id}&identity={song.key}" in map(unquote, posted.read)
    assert lyrics.ran == []


def test_a_song_with_lyrics_has_it_folded_under_its_foot(able, live, lyrics, browser):
    base, posted, _ = live
    song = lyrics.song
    in_book(able, lambda conn: update_song(conn, song.id, lyrics_status="found"))
    browser.open(base)
    card = opened(browser, song)
    assert browser.wait(f"document.querySelector({panel_of(card)}) !== null")
    assert browser.js(f"(() => {{ const p = document.querySelector({panel_of(card)}); "
                      "const prev = p.previousElementSibling; "
                      "return [p.open, !!prev && prev.matches('.foot'), p.querySelector('summary').textContent]; })()"
                      ) == [False, True, "Lyrics under another name…"]
    reads = len([t for t in posted.read if t.startswith("/api/lyrics/search")])
    assert reads == 0  # folded: nothing read until it is opened
    browser.click(f"{card} {PANEL} > summary")
    drawn(browser, card)
    assert browser.js(fields_of(card)) == [ARTIST, TITLE]
    assert posted == []
    assert not browser.wait("document.querySelector('form.transcribe') !== null", timeout=0.5)


def test_the_lyrics_name_kept_fills_the_fields(able, live, lyrics, browser):
    base, posted, _ = live
    set_lyrics_name(able.overrides_file, lyrics.song.display, "孟维来 - 野人")
    browser.open(base)
    card = opened(browser, lyrics.song)
    drawn(browser, card)
    assert browser.js(fields_of(card)) == list(ASKED)
    assert posted == []


def test_searching_says_it_asks_then_lists_one_row_a_record_best_fit_first(able, live, lyrics, browser):
    base, posted, queue = live
    song = lyrics.song
    lyrics.hold.clear()
    browser.open(base)
    card = opened(browser, song)
    drawn(browser, card)
    type_into(browser, card, "title", "野人")
    browser.press("Enter")  # Enter in its fields submits it: a press
    path, fields = posted.next(0)
    assert (path, fields) == ("/lyrics/search", {"csrf": "tok", "song": str(song.id), "identity": song.key,
                                                 "artist": ARTIST, "title": "野人"})
    said = text_of(card, "p.lyrics-said")
    assert browser.wait(f"{said} === 'Asking LRCLIB, Megalobiz and AZLyrics under “孟维来 - 野人”…'"), browser.js(said)
    assert browser.js(f"document.querySelector({panel_of(card)} + ' form.lyrics-search-form button').disabled")
    assert browser.js(f"document.querySelector({panel_of(card)} + ' p.lyrics-said').getAttribute('role')") == \
        "status"
    browser.press("Enter")  # pressed again while it runs: nothing more is sent
    assert not browser.wait("false", timeout=0.5) and len(posted) == 1
    lyrics.hold.set()
    line_words = "Searched: LRCLIB, Megalobiz and AZLyrics list 4 records for “孟维来 - 野人”."
    assert browser.wait(f"{said} === {json.dumps(line_words)}"), browser.js(said)
    assert browser.wait(f"{rows_of(card)}.length === 4")
    assert browser.js(rows_of(card)) == [
        ["LRCLIB", "孟维来 - 野人", "野人 · 3:46 · timed", ["Best fit"],
         ["Use these lyrics", "Use LRCLIB's timed lyrics of 野人 by 孟维来"]],
        ["LRCLIB", "孟维来 - 野人 (Live)", "野人 Live · 4:31 (audio 3:45) · timed", [],
         ["Use these lyrics", "Use LRCLIB's timed lyrics of 野人 (Live) by 孟维来"]],
        ["Megalobiz", "(no artist) - 野人", "3:44 · timed", [],
         ["Use these lyrics", "Use Megalobiz's timed lyrics of 野人"]],
        ["AZLyrics", "孟维来 - 野人", "plain", [],
         ["Use these lyrics", "Use AZLyrics' plain lyrics of 野人 by 孟维来"]]]
    assert browser.js(text_of(card, "p.lyrics-asked")).startswith("Asked as “孟维来 - 野人”")
    assert browser.js(text_of(card, "ul.lyrics-notes")) == "2 records marked instrumental aren't listed."
    assert not browser.js(f"document.querySelector({panel_of(card)} + ' form.lyrics-search-form button').disabled")
    assert lyrics.ran == [("lyrics", f"--song={song.display}", "--as=孟维来 - 野人")] and len(posted) == 1


def test_nothing_found_says_where_it_looked(able, live, lyrics, browser):
    base, posted, _ = live
    lyrics.search = lambda asked: a_search(asked, rows=(), state={s: "none" for s in ("lrclib", "megalobiz",
                                                                                       "azlyrics")},
                                           said={"lrclib": "nothing listed", "megalobiz": "nothing listed",
                                                 "azlyrics": "no artist page for 孟维来"})
    browser.open(base)
    card = opened(browser, lyrics.song)
    drawn(browser, card)
    type_into(browser, card, "title", "野人")
    browser.click(f"{card} {PANEL} form.lyrics-search-form button[type=submit]")
    posted.next(0)
    said = text_of(card, "p.lyrics-said")
    assert browser.wait(f"{said} === 'Nothing found: LRCLIB, Megalobiz and AZLyrics list nothing for “孟维来 - 野人”.'"
                        ), browser.js(said)
    assert browser.js(f"{rows_of(card)}.length") == 0
    assert browser.js(fields_of(card)) == [ARTIST, "野人"]  # left for another name


def test_a_failed_site_is_said_never_nothing_found(able, live, lyrics, browser):
    base, posted, _ = live
    lyrics.search = lambda asked: a_search(asked, rows=(), state={"lrclib": "failed", "megalobiz": "none",
                                                                  "azlyrics": "cooling"},
                                           said={"lrclib": "LRCLIB failed (lrclib: 502: Bad Gateway)",
                                                 "megalobiz": "nothing listed",
                                                 "azlyrics": "waiting out AZLyrics until 26/11 18:00"})
    browser.open(base)
    card = opened(browser, lyrics.song)
    drawn(browser, card)
    browser.click(f"{card} {PANEL} form.lyrics-search-form button[type=submit]")
    posted.next(0)
    said = text_of(card, "p.lyrics-said")
    assert browser.wait(f"{said}.startsWith('Not searched: ')"), browser.js(said)
    assert "Nothing found" not in browser.js(said)
    notes = f"[...document.querySelectorAll({json.dumps(card + ' ' + PANEL + ' ul.lyrics-notes > li')})]" \
            ".map((li) => li.textContent)"
    assert browser.js(notes) == ["LRCLIB failed (lrclib: 502: Bad Gateway).", "Megalobiz: nothing listed.",
                                 "AZLyrics: waiting out AZLyrics until 26/11 18:00.",
                                 "2 records marked instrumental aren't listed."]


def test_use_these_posts_the_record_in_place_and_the_line_follows_the_pick(able, live, lyrics, browser):
    base, posted, queue = live
    song = lyrics.song
    in_book(able, lambda conn: kv_set_json(conn, f"{KV}{song.id}", a_search().as_json()))
    browser.open(base)
    browser.js("window.notReloaded = true")
    card = opened(browser, song)
    drawn(browser, card)
    assert browser.wait(f"{rows_of(card)}.length === 4")  # its rows drawn before a press lands in them
    browser.click(f"{card} {PANEL} ol.lyrics-rows > li:first-child button[type=submit]")
    path, fields = posted.next(0)
    assert (path, fields) == ("/lyrics/pick", {"csrf": "tok", "song": str(song.id), "identity": song.key,
                                               "record": "lrclib:28399373"})
    # The song's line follows the pick to Ready, drawn again from the song as it is now: its lyrics found, the
    # panel folded under its foot, the record In use with Clear the pick, and no transcription offered.
    assert browser.wait(f"{tone(song)} === 'ready'"), browser.js(f"{tone(song)}")
    again = cards.card_js(line(song))
    assert browser.wait(f"{again} !== null && {again}.querySelector('.foot + details.lyrics-search') !== null")
    read_again(posted)  # the offers read again: GET /transcribe
    assert browser.js("window.notReloaded === true")
    assert browser.js(f"{again}.querySelector('form.transcribe')") is None
    browser.js(f"{again}.querySelector('details.lyrics-search').open = true")
    shown = "#" + browser.js(f"{again}.id")
    drawn(browser, shown)
    assert browser.wait(f"{rows_of(shown)}.length === 4")
    first = browser.js(rows_of(shown))[0]
    assert first[3] == ["Best fit", "In use"] and first[4] == [
        "Clear the pick", "Clear the pick of LRCLIB's lyrics for 野人『不再借世人的手』『动态歌词MV』"]


def test_a_refused_pick_says_why_in_the_panel(able, live, lyrics, browser):
    base, posted, _ = live
    song = lyrics.song
    in_book(able, lambda conn: kv_set_json(conn, f"{KV}{song.id}", a_search().as_json()))
    browser.open(base)
    card = opened(browser, song)
    drawn(browser, card)
    assert browser.wait(f"{rows_of(card)}.length === 4")
    # The search replaced meanwhile (another device searched): its record is no row of it now.
    in_book(able, lambda conn: kv_set_json(conn, f"{KV}{song.id}", a_search(rows=found_rows()[2:]).as_json()))
    browser.click(f"{card} {PANEL} ol.lyrics-rows > li:first-child button[type=submit]")
    posted.next(0)
    said = text_of(card, "p.lyrics-said")
    assert browser.wait(f"{said} === \"Search again: that record isn't among its last search's, or the search is "
                        "over a week old.\""), browser.js(said)
    assert browser.js(f"document.querySelector({panel_of(card)}).hidden") is False


def test_a_stale_search_offers_no_use_button(able, live, lyrics, browser):
    base, posted, _ = live
    song = lyrics.song
    old = datetime.now(UTC) - timedelta(days=8)
    in_book(able, lambda conn: kv_set_json(conn, f"{KV}{song.id}", a_search(at=old).as_json()))
    browser.open(base)
    card = opened(browser, song)
    drawn(browser, card)
    assert browser.wait(f"{rows_of(card)}.length === 4")
    assert [row[4] for row in browser.js(rows_of(card))] == [None] * 4
    asked = browser.js(text_of(card, "p.lyrics-asked"))
    assert asked == f"Asked as “孟维来 - 野人” on {old:%d/%m/%y}: over a week ago. Search again to pick one."
    assert posted == []


def test_a_picked_record_with_no_lyrics_says_why_and_offers_clear(able, live, lyrics, browser):
    base, posted, queue = live
    song = lyrics.song
    in_book(able, lambda conn: kv_set_json(conn, f"{KV}{song.id}", a_search().as_json()))
    set_lyrics_record(able.overrides_file, song.display, "megalobiz:8")  # its lyrics still missing
    browser.open(base)
    card = opened(browser, song)
    drawn(browser, card)
    assert browser.js(text_of(card, ".lyrics-why p")) == (
        "The record you picked (megalobiz 8) has given no lyrics: pick another, or clear the pick.")
    assert browser.js("document.querySelector('form.transcribe')") is None  # the server offers none: the panel says why
    assert browser.wait(f"{rows_of(card)}.length === 4")
    in_use = [row for row in browser.js(rows_of(card)) if "In use" in row[3]]
    assert [row[1] for row in in_use] == ["(no artist) - 野人"]
    browser.click(f"{card} {PANEL} .lyrics-why button[type=submit]")
    path, fields = posted.next(0)
    assert (path, fields) == ("/lyrics/clear", {"csrf": "tok", "song": str(song.id), "identity": song.key})
    over(queue, queued(queue, "Clear the lyrics record").id)
    read_again(posted)  # pending again: the offers read again, and none (every site must answer first)
    assert lyrics.ran[-1] == ("lyrics", f"--song={song.display}", "--clear")
    assert in_book(able, lambda conn: get_song(conn, song.id).lyrics_status) == "pending"


@pytest.mark.parametrize("width", [390, 1280])
def test_the_panel_fits_the_card_at_a_phones_width_and_a_laptops(able, live, lyrics, tmp_path, width):
    base, posted, _ = live
    song = lyrics.song
    in_book(able, lambda conn: kv_set_json(conn, f"{KV}{song.id}", a_search().as_json()))
    page = driven(tmp_path, width)
    try:
        page.open(base)
        card = opened(page, song)
        drawn(page, card)
        assert page.wait(f"{rows_of(card)}.length === 4")
        fits = page.js(f"(() => {{ const p = document.querySelector({panel_of(card)}); const r = "
                       "p.getBoundingClientRect(); const out = [...p.querySelectorAll('*')].filter((n) => { "
                       "const b = n.getBoundingClientRect(); return b.width && (b.right > r.right + 0.5 || "
                       "b.left < r.left - 0.5); }).map((n) => n.className || n.tagName); "
                       "return [out, document.documentElement.scrollWidth <= window.innerWidth]; })()")
        assert fits == [[], True]
        if width >= 1200:
            assert page.js(f"!!document.querySelector('#card-pane').contains(document.querySelector({panel_of(card)}))")
    finally:
        page.close()


def test_none_on_the_phones_page_or_the_file(conn, cfg, tmp_path):
    add_song(conn, ARTIST, TITLE)
    update_song(conn, 1, lyrics_status="missing")
    probe = (f'const l = lineOf({json.dumps(TITLE)}); openCardOf(l); '
             f'note("lyrics", !!cardOf(l).querySelector({json.dumps(PANEL)}));')
    assert attribute_of(run(conn, cfg, tmp_path, probe), "data-lyrics") is False  # the file on disk
    phone = WebControls(csrf="tok")  # the phone's member: lyricsSearch false
    assert attribute_of(run(conn, cfg, tmp_path, probe, controls=phone), "data-lyrics") is False
    served = WebControls(csrf="tok", lyrics_search=True)
    assert attribute_of(run(conn, cfg, tmp_path, probe, controls=served), "data-lyrics") is True

