"""Where a song's card is on the library page (stage 1d), in a real browser: the tests find it by its line's chevron."""

from __future__ import annotations

import json

import pytest

import test_web_page_again as served_page
from conftest import add_song
from helpers import cards
from helpers.browser import CHROMIUM_MARKS
from test_library_card import SERVED, hotel, run
from test_library_page import attribute_of, put
from test_web_page import CANDIDATES

from caracole import db
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
      tag: head.querySelector(".card-name").tagName.toLowerCase(), inner: head.firstElementChild.className },
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
    assert head["shown"] == "none", head  # until the pane shows it
    missing = attribute_of(dom, "data-lost")
    assert missing["parts"] == ["card-head", "facts", "actions", "foot", "card-sites", "find-elsewhere"], missing
