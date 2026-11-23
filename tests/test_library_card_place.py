"""Where a song's card is on the library page (stage 1d), in a real browser: the tests find it by its line's chevron, out
of sight (the keyboard's button, whose ``aria-controls`` names it), and open it as a hand does, by the line's name or
its blank space."""

from __future__ import annotations

import json

import pytest

import test_web_page_again as served_page
from conftest import add_song
from helpers import cards
from helpers.browser import CHROMIUM_MARKS, Browser, BrowserError
from test_library_card import SERVED, hotel, run
from test_library_page import attribute_of, page, put
from test_web_page import CANDIDATES

from caracole import db
from caracole.library_page import write_library_page
from caracole.songs import update_song

pytestmark = CHROMIUM_MARKS
# test_web_page_again's fixtures: caracole serve with its queue's fake lookup (``live``), and a Chromium to drive.
browser, live, lookup = served_page.browser, served_page.live, served_page.lookup


def test_the_tests_find_a_card_by_its_chevron(conn, cfg, tmp_path):
    for title in ("Creep", "Karma Police"):
        song = add_song(conn, "Radiohead", title)
        put(cfg, song, "sheet.pdf")
        update_song(conn, song.id, status="found")
    script = r"""
const line = lineOf("Creep");
openCardOf(line);
note("card", { id: cardOf(line).id, named: line.querySelector(".line-more").getAttribute("aria-controls"),
  other: cardOf(lineOf("Karma Police")).hidden });
"""
    dom = run(conn, cfg, tmp_path, script)
    noted = attribute_of(dom, "data-card")
    assert noted["id"] == noted["named"]
    assert noted["other"] is True
    card = cards.card_of(dom, "Creep")
    assert card.startswith('<div class="line-panel') and "Add to a songbook…" in card


# --- a song's card is built the first time it opens ----------------------------------------------------------------


def test_a_songs_card_is_made_the_first_time_it_opens(conn, cfg, tmp_path):
    # The list draws each song's line and an empty card behind its chevron, which names it from the start: what the
    # card holds is made as it first opens, for that song alone.
    hotel(conn, cfg)
    creep = add_song(conn, "Radiohead", "Creep")
    put(cfg, creep, "sheet.pdf")
    update_song(conn, creep.id, status="found")
    script = r"""
const panelOf = (line) => {
  const panel = cardOf(line);
  return panel && { empty: panel.childElementCount === 0, hidden: panel.hidden, cls: panel.className,
                    named: line.querySelector(".line-more").getAttribute("aria-controls") === panel.id };
};
const before = Array.from(document.querySelectorAll("#list .line")).map(panelOf);
const card = openCardOf(lineOf("Hotel California"));
note("made", { before, opened: card.childElementCount, hidden: card.hidden,
               creep: panelOf(lineOf("Creep")) });
"""
    made = attribute_of(run(conn, cfg, tmp_path, script), "data-made")
    assert len(made["before"]) == 2, made
    for panel in made["before"]:
        assert panel and panel["empty"] and panel["hidden"] and panel["named"], made
        assert "song-card" in panel["cls"].split() and "line-panel" in panel["cls"].split(), made
    assert made["opened"] > 0 and made["hidden"] is False, made
    assert made["creep"]["empty"] and made["creep"]["hidden"], made


def _found_and_in_review(cfg):
    """Estopa - Como Camarón found (its sheet kept), and Radiohead - Creep in review with two candidates."""
    found = served_page.camaron(cfg)
    conn = db.connect(cfg.db_path)
    try:
        creep = add_song(conn, "Radiohead", "Creep")
        update_song(conn, creep.id, match_decision="review", match_candidates=CANDIDATES, review=True)
        conn.commit()
        return found, creep
    finally:
        conn.close()


def _in_place(page) -> None:
    width, height = (int(n) for n in cards.IN_PLACE.split(","))
    page.send("Emulation.setDeviceMetricsOverride", width=width, height=height, deviceScaleFactor=1, mobile=False)


def _line(song) -> str:
    return f'#list article.line[data-id="{song.id}"]'


def test_a_card_first_opened_while_its_request_runs_has_no_pick_and_no_fetch_again(cfg, live, lookup, browser):
    # Built as it opens, a card says what the song's request lets it do then: no Fetch again, and a picker that
    # only lists, while a lookup of the song waits or runs.
    base, posted = live
    found, creep = _found_and_in_review(cfg)
    lookup.hold.clear()
    _in_place(browser)
    try:
        browser.open(base)
        for song in (found, creep):
            sent = browser.js("fetch('/lookup', { method: 'POST', headers: { Accept: 'application/json' }, "
                              "body: new URLSearchParams(" + json.dumps({"csrf": "tok", "song": str(song.id),
                                                                         "identity": song.key}) + ") })"
                              ".then((r) => r.status)")
            assert sent == 202, sent  # queued
        browser.open(base)  # the page that loads now follows both requests
        for song in (found, creep):
            progress = json.dumps(_line(song) + " .progress")
            assert browser.wait(f"(() => {{ const p = document.querySelector({progress}); "
                                "return Boolean(p && ['queued', 'running'].includes(p.dataset.tone)); })()"), \
                browser.js(f"document.querySelector({progress}) && document.querySelector({progress}).textContent")
        cards.install(browser)
        opened = browser.js("(() => { const f = window.openCardOf(document.querySelector(" + json.dumps(_line(found))
                            + ")); const c = window.openCardOf(document.querySelector(" + json.dumps(_line(creep))
                            + ")); const picker = c.querySelector('details.picker'); return { "
                            "built: f.childElementCount > 0 && c.childElementCount > 0, "
                            "again: f.querySelector('.actions.again') !== null, "
                            "picker: picker !== null, form: picker && picker.querySelector('form.pick-form') !== null, "
                            "said: picker && picker.querySelector('.pick-hint').textContent }; })()")
        assert opened == {"built": True, "again": False, "picker": True, "form": False,
                          "said": "This song is being fetched. Pick once it ends."}, opened
    finally:
        lookup.hold.set()


def test_pick_the_match_opens_the_card_and_its_picker(cfg, live, browser):
    # A wanted song caracole fetch would refuse until its match is picked: the line's Pick the match opens its card,
    # built then, and its picker in it, the focus on its first candidate.
    base, _ = live
    _, creep = _found_and_in_review(cfg)
    _in_place(browser)
    browser.open(base)
    line = json.dumps(_line(creep))
    assert browser.wait(f"document.querySelector({line} + ' .line-pick') !== null")
    browser.click(_line(creep) + " .line-pick")
    cards.install(browser)
    assert browser.wait(f"document.querySelector({line} + ' .line-more').getAttribute('aria-expanded') === 'true'")
    assert browser.wait(f"window.cardOf(document.querySelector({line})).querySelector('details.picker').open")
    assert browser.wait(f"document.activeElement === window.cardOf(document.querySelector({line}))"
                        ".querySelector('input[name=pick]')"), browser.js("document.activeElement.outerHTML")


# --- the card's parts, in the phone's order, with a head ---------------------------------------------------------

ORDER = r"""
const partsOf = (title) => {
  const line = lineOf(title);
  const panel = openCardOf(line);
  const foot = panel.querySelector(".foot");
  const head = panel.querySelector(".card-head");
  return {
    parts: Array.from(panel.children).filter((c) => !c.matches(".card-top"))  // the mark at its top: no part
      .map((c) => c.className.split(" ").find((x) => x !== "row-group") ||
      c.tagName.toLowerCase()),
    foot: foot ? Array.from(foot.querySelectorAll("button, a, summary")).filter((c) => !c.closest(".foot-menu")).map(text) : [],
    menu: foot ? Array.from(foot.querySelectorAll(".foot-menu button, .foot-menu a")).map(text) : [],
    head: head && { text: text(head.querySelector(".card-name")), id: head.querySelector(".card-name").id,
      hidden: head.getAttribute("aria-hidden"), tab: head.querySelector(".card-close").getAttribute("tabindex"),
      said: head.querySelector(".card-close").getAttribute("aria-label"), shown: getComputedStyle(head).display,
      tag: head.querySelector(".card-name").tagName.toLowerCase(), inner: head.firstElementChild.className,
      rest: getComputedStyle(head.firstElementChild).visibility },
  };
};
note("hotel", partsOf("Hotel California"));
note("lost", partsOf("Yesterday"));
"""


@pytest.mark.parametrize("size", ["390,844", "1280,900"])
def test_a_cards_parts_come_in_the_phones_order(conn, cfg, tmp_path, size):
    from caracole.db import kv_set_json
    from caracole.musescore import parse_song_url
    from caracole.progressions import KV, sheet_progressions
    from test_library_page import PROGRESSIONS

    song = hotel(conn, cfg)
    put(cfg, song, "info.json")
    conn.execute("INSERT INTO musescore_index VALUES (?, ?, ?, '18')",
                 parse_song_url("https://musescore.com/song/hotel_california-1234"))
    kv_set_json(conn, f"{KV}{song.id}", sheet_progressions(PROGRESSIONS["pop"], None))
    lost = add_song(conn, "The Beatles", "Yesterday")
    update_song(conn, lost.id, match_decision="not_found")
    dom = run(conn, cfg, tmp_path, ORDER, controls=SERVED, size=size)
    found = attribute_of(dom, "data-hotel")
    assert found["parts"] == ["card-head", "facts", "tiles", "foot", "card-sites", "find-elsewhere", "progressions"], found
    assert found["foot"] == ["Fetch again", "Use LaCuerda's sheet", "Add to a songbook…", "⋯"], found
    assert found["menu"][-1] == "Remove", found
    head = found["head"]
    assert head["text"] == "Hotel California · Eagles" and head["tag"] == "h2", head
    assert head["id"] == f"card-name-{song.id}" and head["inner"] == "card-head-in", head
    assert head["said"] == "Close Hotel California" and head["shown"] == "block", head
    if size == "390,844":  # in place: shown once its line is out of sight, and never heard (the line says it)
        assert head["hidden"] == "true" and head["tab"] == "-1" and head["rest"] == "hidden", head
    else:  # in the laptop's pane: its heading, heard and shown, its close a stop of Tab's
        assert head["hidden"] is None and head["tab"] is None and head["rest"] == "visible", head
    missing = attribute_of(dom, "data-lost")
    assert missing["parts"] == ["card-head", "facts", "actions", "foot", "card-sites", "find-elsewhere"], missing


# --- a long card's head sticks under the search bar, and closing it brings its line back ---------------------------

PHONE = {"width": 390, "height": 844, "mobile": True}
# The page's script's names for a test's: Hotel California's line (``song``), its chevron (out of sight, the
# keyboard's), its name, its card's head and the bar kept at the top. ``headingAt(y)`` scrolls until the name's middle
# is at ``y(…)`` on the screen, ``rowAt(y)`` the middle of the line's own row (over its card), ``topAt(y)`` until the
# card's top is (the bar sticks on the way, so y is asked again each step); ``geometry()`` notes where each is;
# ``settled()``, two frames and a task on, once the page's observers have said what they saw.
PLACE = r"""
window.line = document.querySelector('#list article.line[data-id="SONG"]');
window.chevron = () => line.querySelector(":scope > .line-more");
window.heading = () => line.querySelector(":scope > .line-title h3");
window.bar = () => document.querySelector(".searchbar").getBoundingClientRect();
window.headIn = () => cardOf(line).querySelector(".card-head-in");
window.scrollTill = (at, y) => {
  for (let i = 0; i < 8; i += 1) {
    const by = at() - y();
    if (Math.abs(by) < 0.5) break;
    scrollBy(0, by);
  }
};
window.headingAt = (y) => scrollTill(() => { const r = heading().getBoundingClientRect(); return (r.top + r.bottom) / 2; }, y);
window.rowAt = (y) => scrollTill(() => (line.getBoundingClientRect().top + cardOf(line).getBoundingClientRect().top) / 2, y);
window.topAt = (y) => scrollTill(() => cardOf(line).getBoundingClientRect().top, y);
window.settled = () => new Promise((done) => requestAnimationFrame(() => requestAnimationFrame(() =>
  setTimeout(() => done(true), 50))));
window.geometry = () => {
  const name = headIn().querySelector(".card-name");
  const h = heading().getBoundingClientRect();
  return { shown: headIn().checkVisibility({ visibilityProperty: true }), head: headIn().getBoundingClientRect().top,
           bar: bar().bottom, barTop: bar().top, heading: [h.top, h.bottom], line: line.getBoundingClientRect().top,
           card: [cardOf(line).getBoundingClientRect().top, cardOf(line).getBoundingClientRect().bottom],
           middle: innerHeight / 2, lines: name.clientHeight / parseFloat(getComputedStyle(name).lineHeight),
           expanded: chevron().getAttribute("aria-expanded") };
};
"""
SHOWN = "headIn().checkVisibility({ visibilityProperty: true })"
# The line back in view, between the bar's bottom and the middle of the screen; and there once the page has stopped
# scrolling (a frame on, it is still there).
BACK = ("(() => { const t = line.getBoundingClientRect().top; "
        "return t >= bar().bottom - 0.5 && t <= innerHeight / 2; })()")
LANDED = ("new Promise((done) => { const at = scrollY; requestAnimationFrame(() => requestAnimationFrame(() => "
          f"done(scrollY === at && {BACK}))); }})")


def _long_card(conn, cfg):
    """Hotel California, whose sheet's drawer makes its card taller than a phone's screen, and the songs after it: the
    file's address and the song."""
    song = hotel(conn, cfg)
    for n in range(14):  # Radiohead's, after Eagles: room to scroll once the card is closed
        add_song(conn, "Radiohead", f"Song {n:02d}")
    return write_library_page(cfg.library_dir, page(conn, cfg)).as_uri(), song


def _phone(tmp_path, url, song, size=PHONE):
    try:
        b = Browser(tmp_path / "chrome", **size)
    except BrowserError as e:
        pytest.skip(f"chromium couldn't run: {e}")
    b.open(url)
    cards.install(b)
    b.js(PLACE.replace("SONG", str(song.id)))
    return b


def _open_long(b):
    """Hotel California's card opened, its sheet's drawer too: taller than the screen."""
    b.js("openCardOf(line)")
    b.js("cardOf(line).querySelector('.tile-sheet > button.tile-more').click()")
    assert b.wait("!cardOf(line).querySelector('.drawer').hidden")
    assert b.js("cardOf(line).getBoundingClientRect().height > innerHeight")


def _tap(b, x, y):
    """A tap where it is, the page left as it is scrolled (Browser.click brings its element to the middle first)."""
    for kind in ("mousePressed", "mouseReleased"):
        b.send("Input.dispatchMouseEvent", type=kind, x=x, y=y, button="left", clickCount=1)


@pytest.mark.parametrize("size", ["390,844", "320,640"])  # at 320 px its line is taller: its buttons in a column
def test_a_long_cards_head_sticks_under_the_bar_and_closes_it(conn, cfg, tmp_path, size):
    # A card longer than the screen, scrolled until its top, and so all of its line, is under the bar kept at the
    # top: its head (its name, its close) sticks right under the bar, one line, as far as the card goes, and goes with
    # its end, never past it, and not at all once the card is wholly above the screen; its close closes it, its line
    # comes back into view under the bar, and the focus is on the line's chevron. At the top again with the card open,
    # the head is gone: the line says it all there.
    width, height = (int(n) for n in size.split(","))
    url, song = _long_card(conn, cfg)
    b = _phone(tmp_path, url, song, size={"width": width, "height": height, "mobile": True})
    try:
        _open_long(b)
        # The head takes no room in the card: its facts right under its top's padding, as before it had one.
        assert abs(b.js("(() => { const card = cardOf(line); return card.querySelector(':scope > .facts')"
                        ".getBoundingClientRect().top - card.getBoundingClientRect().top - "
                        "parseFloat(getComputedStyle(card).paddingTop); })()")) < 0.5
        assert b.js(SHOWN) is False  # its line in view: no head
        b.js("topAt(() => bar().bottom - 10)")
        assert b.wait(SHOWN), b.js("geometry()")
        at = b.js("geometry()")
        assert at["barTop"] == 0 and at["card"][0] < at["bar"], at  # the bar stuck, the card's top under it
        assert abs(at["head"] - at["bar"]) <= 1 and at["lines"] <= 1.5, at
        # Further down the card, the head still under the bar; at the card's end, it goes with it.
        b.js("scrollBy(0, cardOf(line).getBoundingClientRect().bottom - bar().bottom - 200)")
        assert b.wait(f"{SHOWN} && Math.abs(headIn().getBoundingClientRect().top - bar().bottom) <= 1"), \
            b.js("geometry()")
        b.js("scrollBy(0, cardOf(line).getBoundingClientRect().bottom - bar().bottom - 20)")
        assert b.js("headIn().getBoundingClientRect().bottom <= cardOf(line).getBoundingClientRect().bottom + 0.5"), \
            b.js("[headIn().getBoundingClientRect().bottom, cardOf(line).getBoundingClientRect().bottom]")
        # The card wholly above the screen: no head, whose card isn't there to be closed.
        b.js("scrollBy(0, cardOf(line).getBoundingClientRect().bottom + 100)")
        assert b.wait("!cardOf(line).classList.contains('head-away')"), b.js("geometry()")
        b.js("scrollTo(0, 0)")
        assert b.wait(f"!{SHOWN}"), b.js("geometry()")
        b.js("topAt(() => bar().bottom - 10)")
        assert b.wait(SHOWN), b.js("geometry()")
        x, y = b.js("(() => { const r = cardOf(line).querySelector('.card-close').getBoundingClientRect(); "
                    "return [r.x + r.width / 2, r.y + r.height / 2]; })()")
        _tap(b, x, y)
        assert b.wait("chevron().getAttribute('aria-expanded') === 'false'"), b.js("geometry()")
        assert b.wait(LANDED), b.js("geometry()")
        assert b.js("document.activeElement === chevron()"), b.js("document.activeElement.outerHTML.slice(0, 120)")
    finally:
        b.close()


def test_at_320_px_no_head_lies_over_the_lines_buttons_still_showing(conn, cfg, tmp_path):
    # At 320 px Hotel California's buttons stand in rows beside its title: its row's upper half under the bar,
    # those buttons still show under it, and no head lies over them; a tap there is the button's. Once the card's top
    # is under the bar too, the head shows.
    url, song = _long_card(conn, cfg)
    b = _phone(tmp_path, url, song, size={"width": 320, "height": 640, "mobile": True})
    try:
        _open_long(b)
        b.js("rowAt(() => bar().bottom)")  # its first row of buttons under the bar, its second showing
        play = ("[...line.querySelectorAll('.line-plays > .play')].find((p) => "
                "p.getBoundingClientRect().top > bar().bottom + 2)")
        assert b.js(f"Boolean({play})"), b.js("geometry()")  # a button of the line's still on the screen
        assert b.js("settled()") and b.js(SHOWN) is False, b.js("geometry()")
        assert b.js(f"(() => {{ const p = {play}; const r = p.getBoundingClientRect(); "
                    "const at = document.elementFromPoint(r.x + r.width / 2, r.y + r.height / 2); "
                    "return Boolean(at && at.closest('.play') === p); })()"), b.js("geometry()")
        b.js("topAt(() => bar().bottom - 10)")
        assert b.wait(SHOWN), b.js("geometry()")
    finally:
        b.close()


def test_closing_by_the_title_brings_the_line_back_too(conn, cfg, tmp_path):
    # The title half under the bar, its lower half tapped: the card closes and its line comes back into view.
    url, song = _long_card(conn, cfg)
    b = _phone(tmp_path, url, song)
    try:
        _open_long(b)
        b.js("headingAt(() => bar().bottom)")
        at = b.js("geometry()")
        assert at["barTop"] == 0 and at["heading"][0] < at["bar"] < at["heading"][1], at
        x, y = b.js("(() => { const r = heading().getBoundingClientRect(); "
                    "return [r.x + r.width / 2, (bar().bottom + r.bottom) / 2]; })()")
        _tap(b, x, y)
        assert b.wait("chevron().getAttribute('aria-expanded') === 'false'"), b.js("geometry()")
        assert b.wait(LANDED), b.js("geometry()")
    finally:
        b.close()


def test_with_reduced_motion_closing_lands_at_once(conn, cfg, tmp_path):
    # Asked for less motion, the line comes back at once: where it lands is read in the same task as the click,
    # and a frame later it is still there.
    url, song = _long_card(conn, cfg)
    b = _phone(tmp_path, url, song)
    try:
        b.send("Emulation.setEmulatedMedia", features=[{"name": "prefers-reduced-motion", "value": "reduce"}])
        _open_long(b)
        b.js("headingAt(() => bar().bottom)")
        was, at, later = b.js("(() => { const was = scrollY; chevron().click(); const at = scrollY; "
                              "return new Promise((done) => requestAnimationFrame(() => requestAnimationFrame(() => "
                              "done([was, at, scrollY])))); })()")
        assert at != was and at == later, (was, at, later)
        assert b.js(BACK), b.js("geometry()")
    finally:
        b.close()


def test_a_running_requests_line_and_steps_are_never_under_the_head(cfg, live, lookup, browser):
    # Served, a lookup of Hotel California running with its card open: its request's line and its steps sit between
    # its title's row and its card. While they show, no head lies over them; once they too are under the bar, it does.
    base, _ = live
    conn = db.connect(cfg.db_path)
    try:
        song = hotel(conn, cfg)
        for n in range(14):
            add_song(conn, "Radiohead", f"Song {n:02d}")
        conn.commit()
    finally:
        conn.close()
    lookup.hold.clear()
    browser.send("Emulation.setDeviceMetricsOverride", width=390, height=844, deviceScaleFactor=1, mobile=True)
    try:
        browser.open(base)
        sent = browser.js("fetch('/lookup', { method: 'POST', headers: { Accept: 'application/json' }, "
                          "body: new URLSearchParams(" + json.dumps({"csrf": "tok", "song": str(song.id),
                                                                     "identity": song.key}) + ") })"
                          ".then((r) => r.status)")
        assert sent == 202, sent
        browser.open(base)  # the page that loads now follows the request
        cards.install(browser)
        browser.js(PLACE.replace("SONG", str(song.id)))
        assert browser.wait("(() => { const p = line.querySelector(':scope > .progress'); "
                            "return Boolean(p && ['queued', 'running'].includes(p.dataset.tone)); })()")
        _open_long(browser)
        steps = "line.querySelector(':scope > .steps')"
        assert browser.wait(f"Boolean({steps}) && {steps}.checkVisibility()", timeout=15), \
            browser.js("line.outerHTML.slice(0, 400)")
        # The title under the bar, the request's line and its steps still showing: no head over them.
        browser.js("headingAt(() => bar().bottom - 30)")
        assert browser.js(f"{steps}.getBoundingClientRect().bottom > bar().bottom + 10"), browser.js("geometry()")
        assert browser.js("settled()") and browser.js(SHOWN) is False, browser.js("geometry()")
        assert browser.js(f"(() => {{ const r = {steps}.getBoundingClientRect(); "
                          "const at = document.elementFromPoint(r.x + r.width / 2, Math.max(r.top, bar().bottom) + 4); "
                          f"return Boolean(at && {steps}.contains(at)); }})()"), browser.js("geometry()")
        # Their bottom under the bar too, and the card's top: the head.
        browser.js("topAt(() => bar().bottom - 10)")
        assert browser.js(f"{steps}.getBoundingClientRect().bottom < bar().bottom"), browser.js("geometry()")
        assert browser.wait(SHOWN), browser.js("geometry()")
    finally:
        lookup.hold.set()


def test_at_320_px_a_chinese_or_long_name_stays_one_line(conn, cfg, tmp_path):
    # At 320 px a card's head keeps its name on one line, cut short when it is long, and its close a thumb's 44 px;
    # nothing is wider than the screen.
    long_title = ("The Longest Song Title Anybody Ever Gave A Song About A Very Long Road Home Through The Night "
                  "And Back Again At Dawn Now")
    assert len(long_title) == 120
    zh = add_song(conn, "宋冬野", "斑马，斑马")
    long = add_song(conn, "Eagles", long_title)
    for song in (zh, long):
        put(cfg, song, "sheet.pdf")
        update_song(conn, song.id, status="found")
    url = write_library_page(cfg.library_dir, page(conn, cfg)).as_uri()
    b = _phone(tmp_path, url, zh, size={"width": 320, "height": 640, "mobile": True})
    try:
        heads = b.js("[" + ", ".join(
            "(() => { const card = openCardOf(document.querySelector('#list article.line[data-id=\"%d\"]')); "
            "const name = card.querySelector('.card-name'); "
            "const close = card.querySelector('.card-close').getBoundingClientRect(); "
            "return { text: name.textContent, height: name.clientHeight, "
            "line: parseFloat(getComputedStyle(name).lineHeight), cut: name.scrollWidth > name.clientWidth, "
            "close: [close.width, close.height] }; })()" % s.id for s in (zh, long)) + "]")
        zh_head, long_head = heads
        assert zh_head["text"] == "斑马，斑马 · 宋冬野", zh_head
        for head in heads:
            assert 0 < head["height"] <= 1.5 * head["line"], head  # one line
            assert head["close"] == [44, 44], head
        assert long_head["cut"] is True, long_head
        assert b.js("document.documentElement.scrollWidth") <= 320
    finally:
        b.close()


# --- the laptop: one column under 1200 px, the list and the pane from 1200 px ---------------------------------------

LAPTOP = {"width": 1280, "height": 900}
# The page's script's names for a test's: a line by its title, the pane, whether a line's card is in it, and the
# focus's element.
PANE = r"""
window.lineOf = (title) => [...document.querySelectorAll('#list article.line')]
  .find((l) => l.querySelector('h3').textContent === title);
window.pane = () => document.getElementById('card-pane');
window.inPane = (title) => { const c = cardOf(lineOf(title)); return Boolean(c && pane().contains(c)); };
window.chevronOf = (title) => lineOf(title).querySelector(':scope > .line-more');
window.empty = () => pane().querySelector('.pane-empty');
"""


def _radiohead(conn, cfg, *more):
    """Radiohead's Creep and Karma Police found, each with its chord sheet, and ``more`` (artist, title) songs alike:
    the file's address."""
    for artist, title in (("Radiohead", "Creep"), ("Radiohead", "Karma Police"), *more):
        song = add_song(conn, artist, title)
        put(cfg, song, "sheet.html", "sheet.pdf")
        update_song(conn, song.id, status="found")
    return write_library_page(cfg.library_dir, page(conn, cfg)).as_uri()


def _opened(tmp_path, url, size=LAPTOP):
    try:
        b = Browser(tmp_path / "chrome", **size)
    except BrowserError as e:
        pytest.skip(f"chromium couldn't run: {e}")
    b.open(url)
    cards.install(b)
    b.js(PANE)
    return b


@pytest.mark.parametrize("width", [1280, 1200])
def test_from_1200_px_the_list_and_an_empty_pane(conn, cfg, tmp_path, width):
    # From 1200 px the list (760 px, or what is left beside the pane) and, right of it, the pane, which says what it is
    # for until a song is opened.
    b = _opened(tmp_path, _radiohead(conn, cfg), {"width": width, "height": 900})
    try:
        at = b.js("(() => { const r = (n) => n.getBoundingClientRect(); const list = document.getElementById('list'); "
                  "return { said: empty().textContent, shown: empty().checkVisibility(), "
                  "list: [r(list).left, r(list).right, r(list).width], pane: [r(pane()).left, r(pane()).width], "
                  "label: pane().getAttribute('aria-label'), tag: pane().tagName.toLowerCase(), "
                  "page: [document.documentElement.scrollWidth, innerWidth] }; })()")
        assert at["said"] == "Open a song to see its card here." and at["shown"], at
        assert at["tag"] == "aside" and at["label"] == "Song", at
        if width == 1280:
            assert abs(at["list"][2] - 760) <= 0.5, at
        else:
            assert at["list"][2] >= 700, at
        assert 400 <= at["pane"][1] <= 480 and at["pane"][0] >= at["list"][1], at
        assert at["page"][0] <= at["page"][1], at
    finally:
        b.close()


def test_a_title_puts_its_card_in_the_pane_and_marks_its_line(conn, cfg, tmp_path):
    b = _opened(tmp_path, _radiohead(conn, cfg))
    try:
        length = b.js("history.length")
        creep = b.js("lineOf('Creep').dataset.id")
        b.click(f'#list article.line[data-id="{creep}"] .line-title h3')
        assert b.wait("inPane('Creep')"), b.js("pane().outerHTML.slice(0, 300)")
        shown = b.js("(() => { const card = cardOf(lineOf('Creep')); const name = card.querySelector('.card-name'); "
                     "const line = lineOf('Creep'); return { name: name.textContent, hidden: name.closest('[aria-hidden]') "
                     "!== null, seen: name.checkVisibility({ visibilityProperty: true }), card: card.hidden, "
                     "selected: line.classList.contains('selected'), current: line.getAttribute('aria-current'), "
                     "expanded: chevronOf('Creep').getAttribute('aria-expanded'), empty: empty().checkVisibility(), "
                     "labelled: pane().getAttribute('aria-labelledby') === name.id, "
                     "close: card.querySelector('.card-close').tabIndex, length: history.length, "
                     "look: [getComputedStyle(line).marginTop, getComputedStyle(line).boxShadow.includes('inset')] "
                     "}; })()")
        assert shown == {"name": "Creep · Radiohead", "hidden": False, "seen": True, "card": False, "selected": True,
                         "current": "true", "expanded": "true", "empty": False, "labelled": True, "close": 0,
                         "length": length, "look": ["0px", True]}, shown  # no card's box, the accent on its edge
        # Another song's line, tapped in its blank space: its card in the pane, Creep's back under its line, closed.
        cards.press_at(b, cards.blank_point(b, f'#list article.line[data-id="{b.js("lineOf(\'Karma Police\').dataset.id")}"]'))
        assert b.wait("inPane('Karma Police')")
        back = b.js("(() => { const card = cardOf(lineOf('Creep')); return { selected: lineOf('Creep').classList"
                    ".contains('selected'), current: lineOf('Creep').hasAttribute('aria-current'), "
                    "inLine: card.parentNode === lineOf('Creep'), hidden: card.hidden, "
                    "expanded: chevronOf('Creep').getAttribute('aria-expanded'), "
                    "head: card.querySelector('.card-head').getAttribute('aria-hidden'), "
                    "karma: lineOf('Karma Police').classList.contains('selected'), "
                    "lines: document.querySelectorAll('.line.selected').length }; })()")
        assert back == {"selected": False, "current": False, "inLine": True, "hidden": True, "expanded": "false",
                        "head": "true", "karma": True, "lines": 1}, back
        # Its name again: the pane empty, the card back under its line.
        b.click(cards.name_of(f'#list article.line[data-id="{b.js("lineOf(\'Karma Police\').dataset.id")}"]'))
        assert b.wait("empty().checkVisibility() && !pane().querySelector('.song-card')"), b.js("pane().outerHTML")
        assert b.js("document.querySelectorAll('.line.selected, [aria-current]').length") == 0
        assert b.js("cardOf(lineOf('Karma Police')).parentNode === lineOf('Karma Police')")
        assert b.js("history.length") == length
    finally:
        b.close()


def test_the_keyboard_goes_into_the_pane_and_escape_comes_back(conn, cfg, tmp_path):
    b = _opened(tmp_path, _radiohead(conn, cfg))
    try:
        b.js("chevronOf('Creep').focus()")
        b.press("Enter")
        assert b.wait("inPane('Creep')")
        assert b.wait("document.activeElement === cardOf(lineOf('Creep')).querySelector('.card-name')"), \
            b.js("document.activeElement.outerHTML.slice(0, 200)")
        b.press("Escape")
        assert b.wait("document.activeElement === chevronOf('Creep')"), b.js("document.activeElement.outerHTML")
        assert b.js("inPane('Creep') && lineOf('Creep').classList.contains('selected')")
    finally:
        b.close()


def test_while_selecting_the_pane_is_put_away(conn, cfg, tmp_path):
    # Select puts away what a line opens: the pane too, until it is over.
    b = _opened(tmp_path, _radiohead(conn, cfg))
    try:
        b.js("openCardOf(lineOf('Creep'))")
        assert b.wait("inPane('Creep')")
        b.js("document.dispatchEvent(new CustomEvent('caracole:new-songbook'))")
        assert b.wait("document.body.classList.contains('selecting') && !pane().checkVisibility()")
        b.js("document.querySelector('.pick-done').click()")
        assert b.wait("pane().checkVisibility() && inPane('Creep')")
    finally:
        b.close()


def test_crossing_1200_px_moves_the_open_card(conn, cfg, tmp_path):
    # Narrower than 1200 px the card in the pane goes back under its line, open; wider again, into the pane. The focus
    # on a part of it stays there, both ways; on the head's close, hidden under the line, it goes to the line's chevron.
    narrow = {"width": 1000, "height": 900, "deviceScaleFactor": 1, "mobile": False}
    wide = dict(narrow, width=1280)
    b = _opened(tmp_path, _radiohead(conn, cfg))
    try:
        b.js("openCardOf(lineOf('Creep'))")
        assert b.wait("inPane('Creep')")
        b.js("window.tile = cardOf(lineOf('Creep')).querySelector('a.tile-open'); tile.focus()")
        assert b.js("document.activeElement === tile")
        b.send("Emulation.setDeviceMetricsOverride", **narrow)
        assert b.wait("(() => { const card = cardOf(lineOf('Creep')); return card.parentNode === lineOf('Creep') && "
                      "!card.hidden && chevronOf('Creep').getAttribute('aria-expanded') === 'true' && "
                      "!document.querySelector('.line.selected') && !pane().checkVisibility(); })()"), \
            b.js("[cardOf(lineOf('Creep')).parentNode.tagName, cardOf(lineOf('Creep')).hidden]")
        assert b.js("cardOf(lineOf('Creep')).querySelector('.card-head').getAttribute('aria-hidden')") == "true"
        assert b.js("document.activeElement === tile"), b.js("document.activeElement.outerHTML.slice(0, 120)")
        b.send("Emulation.setDeviceMetricsOverride", **wide)
        assert b.wait("inPane('Creep') && lineOf('Creep').classList.contains('selected')")
        assert b.js("!cardOf(lineOf('Creep')).hidden && pane().checkVisibility()")
        assert b.js("document.activeElement === tile"), b.js("document.activeElement.outerHTML.slice(0, 120)")
        b.js("cardOf(lineOf('Creep')).querySelector('.card-close').focus()")
        assert b.js("document.activeElement.matches('.card-close')")
        b.send("Emulation.setDeviceMetricsOverride", **narrow)
        assert b.wait("cardOf(lineOf('Creep')).parentNode === lineOf('Creep')")
        assert b.js("document.activeElement === chevronOf('Creep')"), \
            b.js("document.activeElement.outerHTML.slice(0, 120)")
    finally:
        b.close()


def test_crossing_up_while_another_tab_shows_puts_the_card_in_the_pane_once_the_library_shows(conn, cfg, tmp_path):
    b = _opened(tmp_path, _radiohead(conn, cfg), {"width": 1000, "height": 900})
    try:
        b.js("openCardOf(lineOf('Creep'))")
        b.click("#tab-sites")
        assert b.wait("!document.getElementById('library-view').checkVisibility()")
        b.send("Emulation.setDeviceMetricsOverride", width=1280, height=900, deviceScaleFactor=1, mobile=False)
        assert b.wait("matchMedia('(min-width: 1200px)').matches")
        assert b.js("new Promise((done) => requestAnimationFrame(() => requestAnimationFrame(() => done(true))))")
        # No line to see: the card stays open where it was.
        assert b.js("cardOf(lineOf('Creep')).parentNode === lineOf('Creep') && "
                    "chevronOf('Creep').getAttribute('aria-expanded') === 'true'")
        b.click("#tab-library")
        assert b.wait("inPane('Creep') && lineOf('Creep').classList.contains('selected')"), \
            b.js("[cardOf(lineOf('Creep')).parentNode.tagName, chevronOf('Creep').getAttribute('aria-expanded')]")
    finally:
        b.close()


def test_crossing_1200_px_takes_the_card_opened_last_and_closes_the_others(conn, cfg, tmp_path):
    b = _opened(tmp_path, _radiohead(conn, cfg), {"width": 1000, "height": 900})
    try:
        b.js("openCardOf(lineOf('Karma Police')); openCardOf(lineOf('Creep'))")
        assert b.js("(() => { scrollTo(0, 0); return scrollY; })()") == 0
        b.send("Emulation.setDeviceMetricsOverride", width=1280, height=900, deviceScaleFactor=1, mobile=False)
        assert b.wait("inPane('Creep')")
        assert b.js("[chevronOf('Karma Police').getAttribute('aria-expanded'), cardOf(lineOf('Karma Police')).hidden, "
                    "cardOf(lineOf('Karma Police')).parentNode === lineOf('Karma Police'), scrollY]") == \
            ["false", True, True, 0]
    finally:
        b.close()


def test_under_1200_px_one_column_of_800(conn, cfg, tmp_path):
    b = _opened(tmp_path, _radiohead(conn, cfg), {"width": 1000, "height": 900})
    try:
        at = b.js("(() => { const r = (n) => n.getBoundingClientRect(); const v = r(document.getElementById('library-view')); "
                  "const inside = (s) => { const x = r(document.querySelector(s)); return x.left >= v.left - 0.5 && "
                  "x.right <= v.right + 0.5; }; return { view: [v.left, v.width, innerWidth - v.right], "
                  "bar: inside('.searchbar .bar-row') && document.getElementById('library-view')"
                  ".contains(document.querySelector('.searchbar')), counts: document.getElementById('library-view')"
                  ".contains(document.querySelector('.counts-row')) && inside('.counts-row'), "
                  "list: r(document.getElementById('list')).width, mast: r(document.querySelector('.masthead')).width, "
                  "pane: pane().checkVisibility() }; })()")
        assert abs(at["view"][1] - 800) <= 0.5 and abs(at["view"][0] - at["view"][2]) <= 1, at  # centred
        assert at["bar"] and at["counts"] and at["pane"] is False, at
        assert at["mast"] > 900, at  # the masthead keeps the page's width
        b.js("openCardOf(lineOf('Creep'))")
        assert b.js("cardOf(lineOf('Creep')).parentNode === lineOf('Creep') && !cardOf(lineOf('Creep')).hidden")
        assert b.js("document.querySelectorAll('.line.selected').length") == 0
    finally:
        b.close()


def test_the_pane_empties_when_its_line_leaves_the_list(conn, cfg, tmp_path):
    b = _opened(tmp_path, _radiohead(conn, cfg))
    try:
        b.js("openCardOf(lineOf('Creep'))")
        assert b.wait("inPane('Creep')")
        b.js("document.getElementById('q').focus()")
        b.type("karma")
        assert b.wait("empty().checkVisibility() && !pane().querySelector('.song-card')"), b.js("pane().outerHTML")
        assert b.js("document.querySelectorAll('.line.selected').length") == 0
        assert b.js("!lineOf('Creep')")  # not in the list
    finally:
        b.close()


def test_the_panes_head_keeps_a_long_name_on_one_line(conn, cfg, tmp_path):
    long_title = ("The Longest Song Title Anybody Ever Gave A Song About A Very Long Road Home Through The Night "
                  "And Back Again At Dawn Now")
    assert len(long_title) == 120
    zh = add_song(conn, "宋冬野", long_title)
    put(cfg, zh, "sheet.html")
    update_song(conn, zh.id, status="found")
    b = _opened(tmp_path, write_library_page(cfg.library_dir, page(conn, cfg)).as_uri())
    try:
        b.js(f"openCardOf(lineOf({json.dumps(long_title)}))")
        assert b.wait(f"inPane({json.dumps(long_title)})")
        head = b.js(f"(() => {{ const name = cardOf(lineOf({json.dumps(long_title)})).querySelector('.card-name'); "
                    "return { text: name.textContent, height: name.clientHeight, line: parseFloat(getComputedStyle(name)"
                    ".lineHeight), cut: name.scrollWidth > name.clientWidth, "
                    "inside: name.getBoundingClientRect().right <= pane().getBoundingClientRect().right }; })()")
        assert head["text"] == long_title + " · 宋冬野", head
        assert 0 < head["height"] <= 1.5 * head["line"] and head["cut"] and head["inside"], head
        assert b.js("document.documentElement.scrollWidth <= innerWidth")
    finally:
        b.close()


@pytest.mark.parametrize("size", [{"width": 390, "height": 844, "mobile": True}, LAPTOP], ids=["in-place", "pane"])
def test_opening_a_card_adds_no_history_entry(conn, cfg, tmp_path, size):
    # Back closes the card's ⋯ menu (lane 3's); the card itself is no step of the browser's history, at either width.
    b = _opened(tmp_path, _radiohead(conn, cfg), size)
    try:
        said = b.js("(() => { const now = () => [history.length, JSON.stringify(history.state)]; const before = now(); "
                    "const card = openCardOf(lineOf('Creep')); const opened = now(); "
                    "const where = pane().contains(card) ? 'pane' : card.parentNode === lineOf('Creep') ? 'line' : '?'; "
                    "closeCard(lineOf('Creep')); return { before, opened, closed: now(), where }; })()")
        assert said["before"] == said["opened"] == said["closed"], said
        assert said["where"] == ("line" if size.get("mobile") else "pane"), said
    finally:
        b.close()


# Each song line's parts where they are: its h3's box, its artist's (and its middle), its buttons' (left, top, right),
# its key's left, right and top, every play's box inside the line, its right padding, and the list's right.
PARTS = """(() => {
  const r = (n) => n && n.checkVisibility() ? n.getBoundingClientRect() : null;
  const list = document.getElementById('list').getBoundingClientRect();
  return Object.fromEntries([...document.querySelectorAll('#list article.line')].map((line) => {
    const h3 = r(line.querySelector('h3')), by = r(line.querySelector('.line-by')), key = r(line.querySelector('.line-key')),
      plays = r(line.querySelector('.line-plays')), box = r(line);
    const each = [...line.querySelectorAll('.line-plays > .play')].map((p) => p.getBoundingClientRect());
    return [line.querySelector('h3').textContent, {
      h3: [h3.left, h3.right, h3.top, h3.bottom], by: by && [by.left, by.right, (by.top + by.bottom) / 2],
      plays: plays && [plays.left, plays.top, plays.right], key: key && [key.left, key.right, key.top],
      pad: parseFloat(getComputedStyle(line).paddingRight),
      inside: each.every((p) => p.left >= box.left - 0.5 && p.right <= box.right + 0.5 && p.top >= box.top - 0.5
        && p.bottom <= box.bottom + 0.5), n: each.length, line: [box.left, box.right, box.width],
      cut: line.querySelector('h3').scrollWidth > line.querySelector('h3').clientWidth }];
  }).concat([["", { list: [list.left, list.right], page: [document.documentElement.scrollWidth, innerWidth] }]]));
})()"""


# Every other kind a line has a button for, beside a keyed sheet: a Guitar Pro file, a text tab, a harmonica tab, a tab
# of game music and a score. Six icon tiles, which don't fit beside a long name on a laptop's line beside the pane.
OTHER_KINDS = ("guitar-1.gp5", "tab.txt", "harmonica-1.txt", "gametab-1.txt", "score-1.mxl")


def _six(conn, cfg, artist, title):
    """A song of yours with a sheet that names its key and a button for every other kind: six on its line."""
    from test_library_bands import keyed

    song = keyed(conn, cfg, artist, title)
    put(cfg, song, *OTHER_KINDS)
    return song


@pytest.mark.parametrize("size", ["1280,900", "1200,900"])
@pytest.mark.parametrize("selecting", [False, True])
def test_on_a_laptop_chips_wrap_under_the_title_and_never_push_the_key_off(conn, cfg, tmp_path, size, selecting):
    # Beside the pane a folded line reads on one row as under 1200 px (its title, its artist right after it, then its
    # play buttons and its key, at its end) while its buttons fit there, as Hotel California's five icon tiles do; where
    # they don't (Suite: Judy Blue Eyes, Live's six, beside Crosby, Stills, Nash & Young's long name), they go on a row of
    # their own under its title, at its end, left of the key's column, and the first row keeps the title, its artist
    # right after it and the key. None pushes the key off the line, and the title keeps its room; selecting too, after
    # the line's box.
    from test_library_bands import keyed

    hotel(conn, cfg)
    _six(conn, cfg, "Crosby, Stills, Nash & Young", "Suite: Judy Blue Eyes, Live")
    keyed(conn, cfg, "The Beatles", "Yesterday")
    for title in ("Creep", "Karma Police"):
        keyed(conn, cfg, "Radiohead", title)
    width, height = (int(n) for n in size.split(","))
    b = _opened(tmp_path, write_library_page(cfg.library_dir, page(conn, cfg)).as_uri(), {"width": width, "height": height})
    try:
        if selecting:  # Select on, as + New songbook turns it on: each line gets its box
            b.js("document.dispatchEvent(new CustomEvent('caracole:new-songbook'))")
            assert b.wait("document.querySelectorAll('#list .line > .pick').length === 5")
        at = b.js(PARTS)
        hotel_line, suite, yesterday, creep = (at["Hotel California"], at["Suite: Judy Blue Eyes, Live"], at["Yesterday"],
                                               at["Creep"])
        whole = at[""]
        assert hotel_line["n"] == 5 and suite["n"] == 6 and yesterday["n"] == 1 and creep["n"] == 1, at
        lines = (hotel_line, suite, yesterday, creep, at["Karma Police"])
        assert max(line["key"][0] for line in lines) - min(line["key"][0] for line in lines) <= 1, at  # one column
        for line in lines:
            assert line["inside"] and not line["cut"], line  # every button on the line, the title whole
            assert line["key"][1] <= whole["list"][1] + 0.5, (line, whole)
            # The key at the line's end, where the chevron was: its padding after it, and the room its 36 px leave in
            # its 44 px column (centred).
            assert line["line"][1] - line["key"][1] <= line["pad"] + 4.5, (line, whole)
        # Every line's buttons end beside its key's column (the owner's ask of 2026-11-22: right-aligned).
        for line in lines:
            assert 0 <= line["key"][0] - line["plays"][2] <= 16.5, line
        # Yesterday and Hotel California, folded (The Beatles and the Eagles have one song each): one row, its title,
        # its artist, its buttons, then its key.
        for line in (yesterday, hotel_line):
            h3, by, plays = line["h3"], line["by"], line["plays"]
            assert by and h3[1] <= by[0] + 0.5 and h3[2] <= by[2] <= h3[3], line
            assert by[1] <= plays[0] + 0.5 and plays[1] < h3[3] and plays[2] <= line["key"][0], line
        # Suite: Judy Blue Eyes, Live, folded, six buttons that don't fit beside it: its title, its artist right after it and
        # its key on the first row, the buttons under them, at the line's end.
        h3, by, plays = suite["h3"], suite["by"], suite["plays"]
        assert by and h3[1] <= by[0] + 0.5 and h3[2] <= by[2] <= h3[3], suite
        assert suite["key"][2] < h3[3], suite
        assert plays[1] >= h3[3] - 1 and plays[0] > h3[0] + 1, suite
        # In Radiohead's band: the title, then its button on its row.
        assert creep["plays"][0] >= creep["h3"][1] and creep["plays"][1] < creep["h3"][3], creep
        assert whole["page"][0] <= whole["page"][1], whole
    finally:
        b.close()


def test_on_a_laptop_a_bands_line_puts_its_buttons_under_its_title_where_they_dont_fit(conn, cfg, tmp_path):
    # In a band, a line's buttons sit on its title's row where they fit (Hotel California's five icon tiles,
    # Desperado's one) and go under it where they don't (six beside one of Panic! at the Disco's longest titles), the
    # title whole, every button inside its line and at its end, left of the key, either way (library.js placePlays).
    hotel(conn, cfg)
    for title in ("Desperado", "Take It Easy"):
        song = add_song(conn, "Eagles", title)
        put(cfg, song, "sheet.html")
        update_song(conn, song.id, status="found")
    london = "London Beckoned Songs About Money Written by Machines"
    _six(conn, cfg, "Panic! at the Disco", london)
    sins = add_song(conn, "Panic! at the Disco", "I Write Sins Not Tragedies")
    put(cfg, sins, "sheet.html")
    update_song(conn, sins.id, status="found")
    for size in ("1280,900", "1200,900"):
        width, height = (int(n) for n in size.split(","))
        b = _opened(tmp_path, write_library_page(cfg.library_dir, page(conn, cfg)).as_uri(),
                    {"width": width, "height": height})
        try:
            at = b.js(PARTS)
            long_line, hotel_line, desperado = at[london], at["Hotel California"], at["Desperado"]
            assert long_line["n"] == 6 and long_line["plays"][1] >= long_line["h3"][3] - 1, long_line  # under the title
            for line in (hotel_line, desperado):  # beside it
                assert line["plays"][0] >= line["h3"][1] and line["plays"][1] < line["h3"][3], line
            assert long_line["inside"] and hotel_line["inside"] and desperado["inside"], at
            assert all(0 <= line["key"][0] - line["plays"][2] <= 16.5 for line in (long_line, hotel_line, desperado)
                       if line["key"]), at
            assert long_line["plays"][2] >= hotel_line["plays"][2] - 0.5, at  # the same end, under the title too
            assert all(line["line"][1] <= at[""]["list"][1] + 0.5 for line in (long_line, hotel_line, desperado)), at
            assert not long_line["cut"] and not hotel_line["cut"] and at[""]["page"][0] <= at[""]["page"][1], at
        finally:
            b.close()


STAY = "document.addEventListener('click', (e) => e.preventDefault())"  # the tile opens nothing during the test


def test_a_song_opened_from_the_pane_is_recently_opened(conn, cfg, tmp_path):
    b = _opened(tmp_path, _radiohead(conn, cfg))
    try:
        b.js(STAY)
        b.js("openCardOf(lineOf('Creep'))")
        assert b.wait("inPane('Creep')")
        href = b.js("pane().querySelector('a.tile-open').getAttribute('href')")
        b.js("pane().querySelector('a.tile-open').click()")
        b.js("document.getElementById('q').focus()")
        assert b.wait("document.getElementById('recent').checkVisibility()")
        assert b.js("[...document.querySelectorAll('#recent a')].map((a) => [a.querySelector('.recent-title')"
                    ".textContent, a.getAttribute('href')])")[0] == ["Creep", href]
    finally:
        b.close()


def test_the_panes_close_empties_it_and_gives_its_line_the_focus(conn, cfg, tmp_path):
    b = _opened(tmp_path, _radiohead(conn, cfg))
    try:
        b.js("openCardOf(lineOf('Creep'))")
        assert b.wait("inPane('Creep')")
        b.click("#card-pane .card-close")
        assert b.wait("empty().checkVisibility() && !pane().querySelector('.song-card')")
        assert b.js("document.activeElement === chevronOf('Creep') && !lineOf('Creep').classList.contains('selected')")
        assert b.js("cardOf(lineOf('Creep')).parentNode === lineOf('Creep') && cardOf(lineOf('Creep')).hidden")
    finally:
        b.close()


def test_a_selected_lines_card_drawn_again_takes_its_place_in_the_pane(cfg, live, browser):
    # Served, Fetch again from the pane: the request over, its line is drawn again, and its card, made again from the
    # song as it is now, takes the old one's place in the pane, open, the line still selected.
    base, posted = live
    found = served_page.camaron(cfg)
    browser.open(base)
    cards.install(browser)
    browser.js(PANE)
    line = json.dumps(_line(found))
    browser.js(f"openCardOf(document.querySelector({line}))")
    assert browser.wait(f"pane().contains(cardOf(document.querySelector({line})))")
    old = browser.js(f"cardOf(document.querySelector({line})).id")
    browser.js(f"cardOf(document.querySelector({line})).querySelector('.actions.again button').click()")
    posted.next(0)
    assert browser.wait(f"(() => {{ const l = document.querySelector({line}); const c = cardOf(l); "
                        f"return Boolean(c) && c.id !== {json.dumps(old)} && pane().contains(c) && !c.hidden && "
                        "l.classList.contains('selected') && pane().querySelectorAll('.song-card').length === 1 && "
                        "!document.getElementById(" + json.dumps(old) + "); })()", timeout=15), \
        browser.js("pane().outerHTML.slice(0, 300)")
    assert browser.js(f"cardOf(document.querySelector({line})).querySelector('.card-head').hasAttribute('aria-hidden')") \
        is False
    assert browser.js("pane().getAttribute('aria-labelledby')") == f"card-name-{found.id}"


def _rgb(colour: str) -> tuple[float, ...]:
    """A computed colour, rgb(…) or color(srgb …), as 0–255 channels."""
    import re

    if colour.startswith("color(srgb"):
        return tuple(float(v) * 255 for v in re.findall(r"[\d.]+", colour)[:3])
    return tuple(float(v) for v in re.findall(r"[\d.]+", colour)[:3])


def _contrast(a: str, b: str) -> float:
    def luminance(rgb):
        def channel(c):
            c /= 255
            return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4
        r, g, bl = (channel(c) for c in rgb)
        return 0.2126 * r + 0.7152 * g + 0.0722 * bl

    high, low = sorted((luminance(_rgb(a)), luminance(_rgb(b))), reverse=True)
    return (high + 0.05) / (low + 0.05)


@pytest.mark.parametrize("scheme", ["light", "dark"])
def test_a_selected_line_keeps_its_buttons_shape_and_its_words_contrast(conn, cfg, tmp_path, scheme):
    # The line whose card the pane holds: a fill of its own, never its play buttons' (so they keep their shape), its
    # title and artist as readable on it as on any line, the accent along its edge.
    hotel(conn, cfg)
    b = _opened(tmp_path, write_library_page(cfg.library_dir, page(conn, cfg)).as_uri())
    try:
        b.send("Emulation.setEmulatedMedia", features=[{"name": "prefers-color-scheme", "value": scheme}])
        b.js("openCardOf(lineOf('Hotel California'))")
        assert b.wait("inPane('Hotel California')")
        look = b.js("(() => { const l = lineOf('Hotel California'), c = getComputedStyle; return { "
                    "line: c(l).backgroundColor, play: c(l.querySelector('.line-plays > .play')).backgroundColor, "
                    "title: c(l.querySelector('h3')).color, artist: c(l.querySelector('.line-by .artist-name')).color, "
                    "edge: c(l).boxShadow }; })()")
        assert max(abs(x - y) for x, y in zip(_rgb(look["line"]), _rgb(look["play"]))) >= 4, look  # told apart
        assert _contrast(look["title"], look["line"]) >= 4.5 and _contrast(look["artist"], look["line"]) >= 4.5, look
        assert "inset" in look["edge"], look
    finally:
        b.close()


def test_a_folded_lines_buttons_are_placed_again_whatever_it_was_meanwhile(conn, cfg, tmp_path):
    # Suite: Judy Blue Eyes, Live's six buttons don't fit beside it and its artist's long name: under its title whenever it
    # is a folded or flat line beside the pane, after it was a band's line meanwhile (a search that folds Crosby,
    # Stills, Nash & Young into it, then none; the list sorted by title, by artist, by title) or the window narrower.
    artist = "Crosby, Stills, Nash & Young"
    _six(conn, cfg, artist, "Suite: Judy Blue Eyes, Live")
    for title in ("Helplessly Hoping", "Teach Your Children"):
        song = add_song(conn, artist, title)
        put(cfg, song, "sheet.html")
        update_song(conn, song.id, status="found")
    b = _opened(tmp_path, write_library_page(cfg.library_dir, page(conn, cfg)).as_uri())
    under = "lineOf('Suite: Judy Blue Eyes, Live').classList.contains('plays-under')"
    kind = "[...lineOf('Suite: Judy Blue Eyes, Live').closest('section').classList].filter((c) => c !== 'cv').join(' ')"
    lines = "document.querySelectorAll('#list article.line').length"
    try:
        assert b.js(f"[{kind}, {under}]") == ["artist", False]  # a band's line: beside its title, else under it
        b.js("document.getElementById('q').focus()")
        for _ in range(2):  # folded, a band's, folded again
            b.type("suite")
            assert b.wait(f"{lines} === 1 && {under}"), b.js(f"[{kind}, {under}]")
            b.press("Escape")  # the box cleared, the search kept: all three again, under their band
            assert b.wait(f"{lines} === 3 && !{under}"), b.js(f"[{kind}, {under}]")
        for sort, flat in (("title", True), ("artist", False), ("title", True)):
            b.js(f"(() => {{ const s = document.getElementById('sort'); s.value = '{sort}'; "
                 "s.dispatchEvent(new Event('change')); })()")
            assert b.wait(f"{under} === {json.dumps(flat)}"), (sort, b.js(f"[{kind}, {under}]"))
        b.send("Emulation.setDeviceMetricsOverride", width=1000, height=900, deviceScaleFactor=1, mobile=False)
        assert b.wait(f"!{under}")  # under 1200 px: one row, its buttons wrapping beside its artist (1d.2a)
        b.send("Emulation.setDeviceMetricsOverride", width=1280, height=900, deviceScaleFactor=1, mobile=False)
        assert b.wait(under)
    finally:
        b.close()


# --- the pane's forms act on the song's line (served) ------------------------------------------------------------

from test_web_page import QUICK, FakeCaracole, serve  # noqa: E402,F401  (serve: a fixture)


class _Held(FakeCaracole):
    """FakeCaracole whose ``get`` waits for ``release`` (a test sees the request running)."""

    def __init__(self, cfg):
        import threading

        super().__init__(cfg)
        self.release = threading.Event()

    def __call__(self, args, emit):
        if args[0] == "get":
            self.release.wait(30)
        return super().__call__(args, emit)


def _served_pane(serve, cfg, conn, tmp_path, runner, timers=QUICK):  # noqa: F811
    """Radiohead's Creep found and Karma Police, served at 1280 x 900, Creep selected: the page and the song.
    ``timers``: the page's (QUICK unless a test needs a countdown it can't outrun)."""
    creep = add_song(conn, "Radiohead", "Creep")
    put(cfg, creep, "sheet.pdf")
    update_song(conn, creep.id, status="found")
    other = add_song(conn, "Radiohead", "Karma Police")
    put(cfg, other, "sheet.pdf")
    update_song(conn, other.id, status="found")
    url = serve(runner, "(() => {})();\n", timers=timers)
    try:
        b = Browser(tmp_path / "chrome", width=1280, height=900)
    except BrowserError as e:
        pytest.skip(f"chromium couldn't run: {e}")
    b.open(url)
    cards.install(b)
    b.js(PANE)
    b.js("openCardOf(lineOf('Creep'))")
    assert b.wait("inPane('Creep')")
    return b, creep


def _pane_form(b, selector):
    return f"document.querySelector('#card-pane {selector}')"


def test_fetch_again_from_the_pane_follows_on_the_songs_line(serve, cfg, conn, tmp_path):  # noqa: F811
    runner = _Held(cfg)
    b, creep = _served_pane(serve, cfg, conn, tmp_path, runner)
    try:
        b.click("#card-pane .actions.again button")
        progress = json.dumps(_line(creep) + " .progress")
        assert b.wait(f"(() => {{ const p = document.querySelector({progress}); return Boolean(p && "
                      "['queued', 'running'].includes(p.dataset.tone)); })()"), b.js("document.body.innerText.slice(0, 200)")
        sent = [p for p in runner.posted if p[1].startswith("/lookup")]
        assert len(sent) == 1
        from urllib.parse import parse_qs

        form = parse_qs(sent[0][2].decode())
        assert form["song"] == [str(creep.id)] and form["identity"] == [creep.key], form
        assert b.wait(f"{_pane_form(b, '.actions.again')} === null"), b.js("pane().outerHTML.slice(0, 300)")
        assert b.js("inPane('Creep')")
    finally:
        runner.release.set()
        b.close()


# Remove's countdown, long enough that no check below can outrun it on a loaded machine (QUICK's half second could
# end between the wait for "Removing in N s" and the disabled check or the Undo click).
SLOW_UNDO = {"poll": QUICK["poll"], "undo": 9000}


def test_remove_from_the_pane_counts_down_on_the_line_and_undo_keeps_it(serve, cfg, conn, tmp_path):  # noqa: F811
    runner = FakeCaracole(cfg)
    b, creep = _served_pane(serve, cfg, conn, tmp_path, runner, timers=SLOW_UNDO)
    try:
        b.js("document.querySelector('#card-pane .foot-more').open = true")
        b.click("#card-pane form.remove button")
        progress = json.dumps(_line(creep) + " .progress")
        assert b.wait(f"(() => {{ const p = document.querySelector({progress}); return Boolean(p && "
                      "/Removing in \\d s/.test(p.textContent) && p.textContent.includes('Undo')); })()"), \
            b.js(f"document.querySelector({progress}) && document.querySelector({progress}).textContent")
        assert b.js(f"{_pane_form(b, 'form.remove button')}.disabled") is True
        b.click(_line(creep) + " .progress button.undo")
        assert b.wait(f"document.querySelector({progress}).textContent.includes('Not removed')"), \
            b.js(f"document.querySelector({progress}).textContent")
        assert b.wait(f"{_pane_form(b, 'form.remove button')}.disabled === false")
        assert not [c for c in runner.calls if c[0] == "remove"]
    finally:
        b.close()


def test_a_song_removed_from_the_pane_empties_it(serve, cfg, conn, tmp_path):  # noqa: F811
    runner = FakeCaracole(cfg)
    b, creep = _served_pane(serve, cfg, conn, tmp_path, runner)
    try:
        b.js("document.querySelector('#card-pane .foot-more').open = true")
        b.click("#card-pane form.remove button")
        b.js(f"window.song = document.querySelector({json.dumps(_line(creep))})")  # the line's node, once gone
        assert b.wait("window.song.querySelector('.progress') && window.song.querySelector('.progress').textContent "
                      "=== 'Removed'", timeout=20), b.js("window.song.querySelector('.progress') && "
                                                         "window.song.querySelector('.progress').textContent")
        assert b.wait("!pane().querySelector('.line-panel') && empty() && empty().checkVisibility()"), \
            b.js("pane().outerHTML.slice(0, 300)")
    finally:
        b.close()


def test_add_to_a_songbook_from_the_pane_starts_select_with_the_song(serve, cfg, conn, tmp_path):  # noqa: F811
    runner = FakeCaracole(cfg)
    b, creep = _served_pane(serve, cfg, conn, tmp_path, runner)
    try:
        b.js("[...document.querySelectorAll('#card-pane button')].find((x) => x.textContent.includes('Add to a songbook')).dataset.pressMe = '1'")
        b.click("#card-pane button[data-press-me]")
        assert b.wait("document.body.classList.contains('selecting')")
        assert b.wait(f"(() => {{ const box = document.querySelector({json.dumps(_line(creep))} "
                      "+ ' input[type=checkbox]'); return Boolean(box && box.checked); })()"), \
            b.js(f"document.querySelector({json.dumps(_line(creep))}).outerHTML.slice(0, 400)")
    finally:
        b.close()
