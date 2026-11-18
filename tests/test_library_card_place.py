"""Where a song's card is on the library page (stage 1d), in a real browser: the tests find it by its line's chevron."""

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
    parts: Array.from(panel.children).map((c) => c.className.split(" ").find((x) => x !== "row-group") ||
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
    assert head["hidden"] == "true" and head["tab"] == "-1" and head["said"] == "Close Hotel California", head
    assert head["shown"] == "block" and head["rest"] == "hidden", head  # in place: shown once its line is out of sight
    missing = attribute_of(dom, "data-lost")
    assert missing["parts"] == ["card-head", "facts", "actions", "foot", "card-sites", "find-elsewhere"], missing


# --- a long card's head sticks under the search bar, and closing it brings its line back ---------------------------

PHONE = {"width": 390, "height": 844, "mobile": True}
# The page's script's names for a test's: Hotel California's line (``song``), its chevron, its card's head and the
# bar kept at the top. ``chevronAt(y)`` scrolls until the chevron's middle is at ``y(…)`` on the screen (the bar
# sticks on the way, so y is asked again each step); ``geometry()`` notes where each is.
PLACE = r"""
window.line = document.querySelector('#list article.line[data-id="SONG"]');
window.chevron = () => line.querySelector(":scope > .line-more");
window.bar = () => document.querySelector(".searchbar").getBoundingClientRect();
window.headIn = () => cardOf(line).querySelector(".card-head-in");
window.chevronAt = (y) => {
  for (let i = 0; i < 8; i += 1) {
    const r = chevron().getBoundingClientRect();
    const by = (r.top + r.bottom) / 2 - y();
    if (Math.abs(by) < 0.5) break;
    scrollBy(0, by);
  }
};
window.geometry = () => {
  const name = headIn().querySelector(".card-name");
  const c = chevron().getBoundingClientRect();
  return { shown: headIn().checkVisibility({ visibilityProperty: true }), head: headIn().getBoundingClientRect().top,
           bar: bar().bottom, barTop: bar().top, chevron: [c.top, c.bottom], line: line.getBoundingClientRect().top,
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
    """Hotel California, whose UG drawer makes its card taller than a phone's screen, and the songs after it: the
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
    """Hotel California's card opened, its UG drawer too: taller than the screen."""
    b.js("openCardOf(line)")
    b.js("""cardOf(line).querySelector('.tile-sheet button.vchip[data-source="ug"]').click()""")
    assert b.wait("!cardOf(line).querySelector('.drawer').hidden")
    assert b.js("cardOf(line).getBoundingClientRect().height > innerHeight")


def _tap(b, x, y):
    """A tap where it is, the page left as it is scrolled (Browser.click brings its element to the middle first)."""
    for kind in ("mousePressed", "mouseReleased"):
        b.send("Input.dispatchMouseEvent", type=kind, x=x, y=y, button="left", clickCount=1)


@pytest.mark.parametrize("size", ["390,844", "320,640"])  # at 320 px its line is taller: its buttons in a column
def test_a_long_cards_head_sticks_under_the_bar_and_closes_it(conn, cfg, tmp_path, size):
    # A card longer than the screen, scrolled until its line's chevron is under the bar kept at the top: its head
    # (its name, its close) sticks right under the bar, one line, as far as the card goes, and goes with its end,
    # never past it; its close closes it, and its line comes back into view under the bar. At the top again with
    # the card open, the head is gone: the line says it all there.
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
        b.js("chevronAt(() => bar().bottom - 30)")
        assert b.wait(SHOWN), b.js("geometry()")
        at = b.js("geometry()")
        assert at["barTop"] == 0 and at["chevron"][1] < at["bar"], at  # the bar stuck, the chevron under it
        assert abs(at["head"] - at["bar"]) <= 1 and at["lines"] <= 1.5, at
        # Further down the card, the head still under the bar; at the card's end, it goes with it.
        b.js("scrollBy(0, cardOf(line).getBoundingClientRect().bottom - bar().bottom - 200)")
        assert b.wait(f"{SHOWN} && Math.abs(headIn().getBoundingClientRect().top - bar().bottom) <= 1"), \
            b.js("geometry()")
        b.js("scrollBy(0, cardOf(line).getBoundingClientRect().bottom - bar().bottom - 20)")
        assert b.js("headIn().getBoundingClientRect().bottom <= cardOf(line).getBoundingClientRect().bottom + 0.5"), \
            b.js("[headIn().getBoundingClientRect().bottom, cardOf(line).getBoundingClientRect().bottom]")
        b.js("scrollTo(0, 0)")
        assert b.wait(f"!{SHOWN}"), b.js("geometry()")
        b.js("chevronAt(() => bar().bottom - 30)")
        assert b.wait(SHOWN), b.js("geometry()")
        x, y = b.js("(() => { const r = cardOf(line).querySelector('.card-close').getBoundingClientRect(); "
                    "return [r.x + r.width / 2, r.y + r.height / 2]; })()")
        _tap(b, x, y)
        assert b.wait("chevron().getAttribute('aria-expanded') === 'false'"), b.js("geometry()")
        assert b.wait(LANDED), b.js("geometry()")
    finally:
        b.close()


def test_closing_by_the_chevron_brings_the_line_back_too(conn, cfg, tmp_path):
    # The chevron half under the bar, its lower half tapped: the card closes and its line comes back into view.
    url, song = _long_card(conn, cfg)
    b = _phone(tmp_path, url, song)
    try:
        _open_long(b)
        b.js("chevronAt(() => bar().bottom)")
        at = b.js("geometry()")
        assert at["barTop"] == 0 and at["chevron"][0] < at["bar"] < at["chevron"][1], at
        x, y = b.js("(() => { const r = chevron().getBoundingClientRect(); "
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
        b.js("chevronAt(() => bar().bottom)")
        was, at, later = b.js("(() => { const was = scrollY; chevron().click(); const at = scrollY; "
                              "return new Promise((done) => requestAnimationFrame(() => requestAnimationFrame(() => "
                              "done([was, at, scrollY])))); })()")
        assert at != was and at == later, (was, at, later)
        assert b.js(BACK), b.js("geometry()")
    finally:
        b.close()


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
