"""A song of yours opened on the library page (card.js, card.css), in a real browser: what you play from it as tiles,
each with a chevron that opens one drawer right under it (its downloads, then a part a source of its versions), its
progressions, where else to find it, and its foot, Remove at its end; on the file on disk, and on the page caracole
serve serves (here, as it writes it: its data and its forms, with no server behind them).

A test adds a script after the page's own (``with_script``), which opens the song's card and notes what it shows
(``KIT``: ``noteCard``, ``drawerOf``, ``noteDrawer``) into an attribute of the body, read back from the DOM once the
page ran.
"""

from __future__ import annotations

import json
from urllib.parse import quote

import pytest
import test_web_page_again as served_page
from helpers import cards
from helpers.browser import CHROMIUM_MARKS, Browser, BrowserError
from helpers.library_songs import EXPORT, LACUERDA, hotel_california, with_versions
from test_library_page import NOW, attribute_of, dump_dom, page, put, with_script

from caracole.library import keep_file
from caracole.library_page import WebControls, build_library_page, write_library_page
from caracole.overrides import Overrides
from caracole.songs import update_song
from caracole.versions import upsert_version

from conftest import add_song

pytestmark = CHROMIUM_MARKS  # every test here opens the page in Chromium
# test_web_page_again's fixtures: caracole serve with its queue's fake lookup (``live``), and a Chromium to drive.
browser, live, lookup = served_page.browser, served_page.live, served_page.lookup

HOTEL = "Eagles/Hotel%20California/"

# What the tests' scripts share: a song's card opened by its title, its tiles and the order of its parts noted, and
# its drawer's.
KIT = cards.KIT + r"""
const text = (n) => (n ? n.textContent.replace(/\s+/g, " ").trim() : null);
const lineOf = (title) => Array.from(document.querySelectorAll("#list .line"))
  .find((l) => l.querySelector("h3").textContent === title);
const openCard = (title) => {
  const line = lineOf(title);
  openCardOf(line);
  return line;
};
const noteCard = (title) => {
  const line = openCard(title);
  const panel = cardOf(line);
  const tiles = Array.from(panel.querySelectorAll(".tiles > .tile")).map((t) => {
    const open = t.querySelector(".tile-open");
    const more = t.querySelector(":scope > button.tile-more");
    const link = t.querySelector(":scope > a.tile-source");
    return {
      cls: t.className, name: text(t.querySelector(".tile-name")), from: text(t.querySelector(".tile-from")),
      href: open.getAttribute("href"), said: open.getAttribute("aria-label"), download: open.getAttribute("download"),
      sources: Array.from(t.querySelectorAll(".tile-source [data-source]")).map((m) => m.dataset.source),
      link: link ? link.getAttribute("href") : null, more: more ? more.getAttribute("aria-label") : null,
      expanded: more ? more.getAttribute("aria-expanded") : null,
    };
  });
  const parts = Array.from(panel.children).filter((c) => !c.matches(".card-top"))  // the mark at its top: no part
    .map((c) => c.className.split(" ").find((x) => x !== "row-group") ||
    c.tagName.toLowerCase());
  return { tiles, parts, foot: Array.from(panel.querySelectorAll(".foot button, .foot a")).map(text) };
};
// The song's card opened, and its tile of ``kind``'s drawer (a press of its chevron, unless that drawer shows); the
// chevron.
const drawerOf = (title, kind) => {
  const more = openCardOf(lineOf(title)).querySelector(".tile-" + kind + " > button.tile-more");
  if (more.getAttribute("aria-expanded") !== "true") more.click();
  return more;
};
// The card's drawer: where it is, what labels it, its downloads, its parts' sources; and what the part of ``source``
// shows (the first part's, when none is given), as each source's drawer did.
const noteDrawer = (title, source) => {
  const d = cardOf(lineOf(title)).querySelector(".drawer");
  const parts = Array.from(d.querySelectorAll(":scope > .drawer-part"));
  const p = (source ? parts.find((x) => x.dataset.source === source) : parts[0]) || null;
  const q = (sel) => (p ? p.querySelector(sel) : null);
  const all = (sel) => (p ? Array.from(p.querySelectorAll(sel)) : []);
  const label = d.getAttribute("aria-labelledby");
  return { hidden: d.hidden, id: d.id, after: d.previousElementSibling ? d.previousElementSibling.className : null,
    label: label ? text(document.getElementById(label)) : null, tile: d.dataset.tile || null,
    files: Array.from(d.querySelectorAll(":scope > .drawer-files a.dl")).map((a) => ({ text: text(a),
      said: a.getAttribute("aria-label"), href: a.getAttribute("href"), download: a.getAttribute("download") })),
    parts: parts.map((x) => x.dataset.source),
    what: text(q(".drawer-what")), said: text(q(".drawer-said")),
    head: all(".drawer-head button, .drawer-head form").map(text),
    rows: all(".vrow").map((r) => ({ cls: r.className, ver: text(r.querySelector(".ver")),
      stars: text(r.querySelector(".stars")), note: text(r.querySelector(".note")),
      acts: Array.from(r.querySelectorAll(".vbtns > *")).map(text),
      open: (r.querySelector("a.go") || { getAttribute: () => null }).getAttribute("href") })),
    rest: text(q(".drawer-rest .rest-said")), command: text(q(".drawer-rest code")),
    restButtons: all(".drawer-rest button").map(text) };
};
const note = (name, value) => document.body.setAttribute("data-" + name, JSON.stringify(value));
"""


def run(conn, cfg, tmp_path, script, *, controls=None, overrides=None, size="1280,900", media=None, touch=False):
    """The page written with KIT and ``script`` after its own, as served (``controls``) or as the file; its DOM."""
    html = build_library_page(conn, cfg, overrides or Overrides(), NOW, controls=controls) if controls is not None \
        else page(conn, cfg, overrides)
    path = write_library_page(cfg.library_dir, with_script(html, "(() => {\n" + KIT + script + "\n})();"))
    return dump_dom(path, tmp_path, size=size, media=media, touch=touch)


def hotel(conn, cfg):
    song = hotel_california(conn, cfg)
    with_versions(conn, cfg, song)
    return song


SERVED = WebControls(csrf="tok", guitar=True)


# --- the tiles ------------------------------------------------------------------------------------------------


def test_tiles_in_order_with_their_open_links(conn, cfg, tmp_path):
    hotel(conn, cfg)
    card = attribute_of(run(conn, cfg, tmp_path, 'note("card", noteCard("Hotel California"));'), "data-card")
    tiles = card["tiles"]
    # The line's order, its text tab a tile of its own beside its Guitar Pro files.
    assert [t["name"] for t in tiles] == ["Chord sheet", "Guitar Pro", "Guitar tab", "Harmonica tab", "Lyrics",
                                          "Score"], tiles
    assert [t["href"] for t in tiles] == [HOTEL + "sheet.html", HOTEL + "guitar-1.gp5", HOTEL + "tab.txt",
                                          HOTEL + "harmonica-1.txt", HOTEL + "lyrics.txt", HOTEL + "score-1.mxl"]
    assert [t["said"] for t in tiles] == [
        "Open the chord sheet of Hotel California", "Download the Guitar Pro file of Hotel California",
        "Open the guitar tab of Hotel California", "Open the harmonica tab of Hotel California",
        "Open the lyrics of Hotel California", "Download the score of Hotel California"]
    # From the file, a Guitar Pro file and a MusicXML score download under the song's name.
    assert tiles[1]["download"] == "Eagles - Hotel California.gp5" and tiles[0]["download"] is None
    assert tiles[5]["download"] == "Eagles - Hotel California.mxl"
    assert [t["from"] for t in tiles] == ["Ver 3 · ★ 4.86 (408) · in use", "guitar-1.gp5", "a text tab", "Tab 1",
                                          "timed", "Score 1 (MusicXML)"]
    assert not any("primary" in t["cls"].split() for t in tiles)  # none first
    # Served with alphaTab, the Guitar Pro tile opens caracole serve's Guitar Pro page.
    served = attribute_of(run(conn, cfg, tmp_path, 'note("card", noteCard("Hotel California"));', controls=SERVED),
                          "data-card")["tiles"][1]
    assert served["href"].startswith("guitar?file=") and served["download"] is None
    assert served["said"] == "Open the Guitar Pro tab of Hotel California"


def test_each_tiles_drawer_holds_its_downloads_and_a_part_a_source(conn, cfg, tmp_path):
    hotel(conn, cfg)
    script = """const card = noteCard("Hotel California");
    const kinds = ["sheet", "guitar", "tab", "harmonica", "lyrics", "score"];
    note("drawers", { more: card.tiles.map((t) => t.more), sources: card.tiles.map((t) => t.sources),
      stacks: card.tiles.map((t) => t.cls.split(" ").includes("stack")), expanded: card.tiles.map((t) => t.expanded),
      drawers: kinds.map((k) => { drawerOf("Hotel California", k); const d = noteDrawer("Hotel California");
        return [d.tile, d.after.split(" ")[1], d.files.map((f) => f.text), d.parts]; }),
      open: cardOf(lineOf("Hotel California")).querySelectorAll(".drawer:not([hidden])").length });"""
    shown = attribute_of(run(conn, cfg, tmp_path, script), "data-drawers")
    assert shown["more"] == ["Chord sheet: its versions and downloads", "Guitar Pro: its files and downloads",
                             "Guitar tab: its downloads", "Harmonica tab: its downloads", "Lyrics: its downloads",
                             "Score: its downloads"]
    assert shown["sources"] == [["ug", "lacuerda"], ["gtptabs", "inbox"], [], ["harptabs"], ["lrclib"], ["inbox"]]
    assert shown["drawers"] == [
        ["sheet", "tile-sheet", ["PDF", "Text", "ChordPro", "PDF · G Dorian, capo 0"], ["ug", "lacuerda", "auto"]],
        ["guitar", "tile-guitar", [".gp5"], ["gtptabs", "inbox"]], ["tab", "tile-tab", ["Text"], []],
        ["harmonica", "tile-harmonica", ["Text"], []], ["lyrics", "tile-lyrics", ["Text", "Timed (.lrc)"], []],
        ["score", "tile-score", ["MusicXML"], []]]
    assert shown["open"] == 1  # one at a time, right after its own tile
    # More than one version: a small stack. Every drawer closed at first.
    assert shown["stacks"] == [True, True, False, False, False, False]
    assert shown["expanded"] == ["false"] * 6


def test_lyrics_from_megalobiz_link_back_to_their_page_from_the_tile(conn, cfg, tmp_path):
    # Megalobiz's fair use asks a link to the record's page wherever its lyrics show: the Lyrics tile's source is it.
    from caracole.lyrics import Lyrics
    from caracole.songs import update_song

    song = hotel(conn, cfg)
    url = "https://megalobiz.com/lrc/24519/hotel-california"
    update_song(conn, song.id, lyrics_status="found", lyrics_json=Lyrics(
        plain="x", synced="[00:01.00]x", instrumental=False, duration=None, lrclib_id=None, provider="megalobiz",
        url=url).to_json())
    script = """
    openCard("Hotel California");
    const link = cardOf(lineOf("Hotel California")).querySelector(".tile-lyrics > a.tile-source");
    note("link", { tag: link.tagName.toLowerCase(), href: link.getAttribute("href"), target: link.target,
                   rel: link.rel, said: link.getAttribute("aria-label"),
                   name: text(link.querySelector(".tile-source-name")), mark: link.querySelector("[data-source]").dataset.source });
    """
    link = attribute_of(run(conn, cfg, tmp_path, script), "data-link")
    assert link == {"tag": "a", "href": url, "target": "_blank", "rel": "noopener noreferrer",
                    "said": "Lyrics: its page on Megalobiz", "name": "Megalobiz", "mark": "megalobiz"}


def test_lyrics_from_azlyrics_link_back_to_their_page_from_the_tile(conn, cfg, tmp_path):
    from caracole.lyrics import Lyrics
    from caracole.songs import update_song

    song = hotel(conn, cfg)
    url = "https://www.azlyrics.com/lyrics/eagles/hotelcalifornia.html"
    update_song(conn, song.id, lyrics_status="found", lyrics_json=Lyrics(
        plain="x", synced=None, instrumental=False, duration=None, lrclib_id=None, provider="azlyrics",
        url=url).to_json())
    script = """
    openCard("Hotel California");
    const link = cardOf(lineOf("Hotel California")).querySelector(".tile-lyrics > a.tile-source");
    note("link", { href: link.getAttribute("href"), said: link.getAttribute("aria-label"),
                   name: text(link.querySelector(".tile-source-name")) });
    """
    link = attribute_of(run(conn, cfg, tmp_path, script), "data-link")
    assert link == {"href": url, "said": "Lyrics: its page on AZLyrics", "name": "AZLyrics"}


def test_a_tab_of_game_music_is_a_tile_of_its_own_opened_as_text(conn, cfg, tmp_path):
    song = add_song(conn, "Hollow Knight", "Resting Grounds")
    for number in (1, 2):
        vid = upsert_version(conn, provider="gametabs", tab_id=f"tabs/hollow-knight/resting-grounds-{number}",
                             song_id=song.id, slot="guitar", kind="gametab", rating=5.0, votes=10, version=1,
                             label=None, url="https://gametabs.net/tabs/hollow-knight/resting-grounds-2", raw={},
                             now="2026-10-28T03:30:00Z")
        keep_file(conn, cfg.library_dir, song=song, version_id=vid, name=f"gametab-{number}.txt", data=f"E|--{number}--|\n".encode(),
                  rank=number)
    update_song(conn, song.id, status="found")
    script = ('note("card", noteCard("Resting Grounds"));\ndrawerOf("Resting Grounds", "gametab");\n'
              'note("drawer", noteDrawer("Resting Grounds"));')
    dom = run(conn, cfg, tmp_path, script)
    [tile] = attribute_of(dom, "data-card")["tiles"]
    folder = "Hollow%20Knight/Resting%20Grounds/"
    assert (tile["name"], tile["from"], tile["href"], tile["said"], tile["more"]) == (
        "Game music tab", "Tab 1", folder + "gametab-1.txt", "Open the game music tab of Resting Grounds",
        "Game music tab: its tabs and downloads")
    assert tile["sources"] == ["gametabs"]
    drawer = attribute_of(dom, "data-drawer")
    assert [f["text"] for f in drawer["files"]] == ["Text"]
    assert (drawer["parts"], drawer["said"]) == (["gametabs"], "2 tabs")


def test_the_sheet_tile_downloads_pdf_text_chordpro_and_each_export(conn, cfg, tmp_path):
    hotel(conn, cfg)
    drawer = attribute_of(run(conn, cfg, tmp_path, 'drawerOf("Hotel California", "sheet");\n'
                                                   'note("drawer", noteDrawer("Hotel California"));'), "data-drawer")
    files = drawer["files"]
    assert [(d["text"], d["href"]) for d in files] == [
        ("PDF", HOTEL + "sheet.pdf"), ("Text", HOTEL + "sheet.txt"), ("ChordPro", HOTEL + "sheet.cho"),
        ("PDF · G Dorian, capo 0", HOTEL + quote(EXPORT))]
    assert all(d["download"] is not None for d in files)
    assert files[0]["said"] == "Download the PDF of Hotel California"
    assert files[3]["said"] == "Download the PDF of Hotel California in G Dorian, capo 0"


# Opens the sheet's drawer, then the Guitar Pro tile's (one drawer at a time), then the Guitar Pro's again (closed);
# notes each step.
CHEVRONS = """
const card = cardOf(openCard("Hotel California"));
const sheet = drawerOf("Hotel California", "sheet");
const first = { drawer: noteDrawer("Hotel California"), sheet: sheet.getAttribute("aria-expanded"),
  controls: sheet.getAttribute("aria-controls"),
  open: Array.from(card.querySelectorAll(".tile.open")).map((t) => t.className) };
const guitar = card.querySelector(".tile-guitar > button.tile-more");
guitar.click();
const second = { drawer: noteDrawer("Hotel California"), sheet: sheet.getAttribute("aria-expanded"),
  guitar: guitar.getAttribute("aria-expanded"), open: card.querySelectorAll(".tile.open").length };
guitar.click();
note("chevrons", { first, second, closed: noteDrawer("Hotel California").hidden,
  guitar: guitar.getAttribute("aria-expanded"), drawers: card.querySelectorAll(".drawer").length, open: card.querySelectorAll(".tile.open").length });
"""


def test_a_tiles_chevron_opens_its_drawer_and_another_closes_it(conn, cfg, tmp_path):
    hotel(conn, cfg)
    chevrons = attribute_of(run(conn, cfg, tmp_path, CHEVRONS), "data-chevrons")
    first, second = chevrons["first"], chevrons["second"]
    assert first["sheet"] == "true" and first["controls"] == first["drawer"]["id"] and not first["drawer"]["hidden"]
    assert (first["drawer"]["label"], first["drawer"]["tile"]) == ("Chord sheet", "sheet")  # named by its tile
    assert first["drawer"]["after"] == first["open"][0] and first["open"][0].startswith("tile tile-sheet")
    assert first["drawer"]["what"] == "UG · chord sheets"
    assert second["sheet"] == "false" and second["guitar"] == "true" and second["open"] == 1
    assert (second["drawer"]["label"], second["drawer"]["what"]) == ("Guitar Pro", "gtptabs · Guitar Pro files")
    assert second["drawer"]["after"].startswith("tile tile-guitar")
    assert chevrons["closed"] is True and chevrons["guitar"] == "false" and chevrons["drawers"] == 1
    assert chevrons["open"] == 0


def test_a_version_with_no_rating_is_new(conn, cfg, tmp_path):
    song = add_song(conn, "Radiohead", "Creep")
    v = upsert_version(conn, provider="ug", tab_id="7", song_id=song.id, slot="sheet", kind="chords", rating=0,
                       votes=0, version=1, label=None,
                       url="https://tabs.ultimate-guitar.com/tab/radiohead/creep-chords-7", raw={}, now="x")
    keep_file(conn, cfg.library_dir, song=song, version_id=v, name="sheet.txt", data=b"[ch]G[/ch]\nx", rank=1)
    upsert_version(conn, provider="ug", tab_id="8", song_id=song.id, slot="sheet", kind="chords", rating=4.5, votes=3,
                   version=2, label=None, url="https://tabs.ultimate-guitar.com/tab/radiohead/creep-chords-8", raw={},
                   now="x")  # a second, not kept: one version alone would say it all, with no part in the drawer
    put(cfg, song, "sheet.html")
    update_song(conn, song.id, status="found")
    script = ('const card = noteCard("Creep");\ndrawerOf("Creep", "sheet");\n'
              'note("new", { from: card.tiles[0].from, stars: noteDrawer("Creep", "ug").rows.map((r) => r.stars) });')
    assert attribute_of(run(conn, cfg, tmp_path, script), "data-new") == {"from": "Ver 1 · New · in use",
                                                                         "stars": ["New"]}


def test_a_ug_version_is_named_by_what_differs(conn, cfg, tmp_path):
    song = hotel(conn, cfg)
    conn.execute("UPDATE versions SET label = 'acoustic' WHERE song_id = ? AND tab_id = '46191'", (song.id,))
    script = 'drawerOf("Hotel California", "sheet");\nnote("drawer", noteDrawer("Hotel California", "ug"));'
    rows = attribute_of(run(conn, cfg, tmp_path, script), "data-drawer")["rows"]
    assert [(r["ver"], r["note"]) for r in rows] == [("Ver 3", "All the lyrics · our pick"),
                                                     ("Ver 4", "Acoustic · 80% of the lyrics"),
                                                     ("Ver 5", "50% of the lyrics")]


def test_the_ug_drawer_lists_the_kept_versions_and_counts_the_rest(conn, cfg, tmp_path):
    from helpers.cli_lines import parsed

    hotel(conn, cfg)
    drawer = attribute_of(run(conn, cfg, tmp_path, 'drawerOf("Hotel California", "sheet");\n'
                                                   'note("drawer", noteDrawer("Hotel California", "ug"));'),
                          "data-drawer")
    assert drawer["said"] == "13 on UG · 3 in your logbook"
    rows = drawer["rows"]
    assert [(r["ver"], r["stars"]) for r in rows] == [
        ("Ver 3", "★ 4.86 (408)"), ("Ver 4", "★ 4.75 (850)"), ("Ver 5", "★ 4.70 (800)")], rows
    assert [r["note"] for r in rows] == ["All the lyrics · our pick", "80% of the lyrics",
                                         "50% of the lyrics"]
    assert [r["acts"] for r in rows] == [["In use", "Open"], ["Open"], ["Open"]]  # the file chooses nothing
    assert [r["open"] for r in rows] == [HOTEL + "sheet.html", HOTEL + "version-46191.html",
                                         HOTEL + "version-46192.txt"]
    assert "cur" in rows[0]["cls"].split()
    # The rest are counted, not listed; from the file, the command that fetches them.
    assert drawer["rest"] == "10 more on UG, not kept" and drawer["restButtons"] == []
    assert drawer["command"] == "caracole versions --keep-more 'Eagles - Hotel California'"
    words, params = parsed(drawer["command"])
    assert words == ("versions",) and params["keep_more"] is True and list(params["song"]) == ["Eagles - Hotel California"]


def test_the_lacuerda_and_auto_drawers_list_theirs(conn, cfg, tmp_path):
    hotel(conn, cfg)
    script = ('drawerOf("Hotel California", "sheet");\n'
              'note("drawers", [noteDrawer("Hotel California", "lacuerda"), noteDrawer("Hotel California", "auto")]);')
    lc, auto = attribute_of(run(conn, cfg, tmp_path, script), "data-drawers")
    assert lc["said"] == "2 versions seen"
    assert [(r["ver"], r["note"], r["acts"], r["open"]) for r in lc["rows"]] == [
        ("Version 1", "90% of the lyrics", ["Its page ↗"], LACUERDA[0]),
        ("Version 2", "60% of the lyrics", ["Its page ↗"], LACUERDA[1])]  # the sheet is UG's: In use on none
    assert auto["what"] == "Auto sheet · from the recording"
    [row] = auto["rows"]
    assert row["open"] == HOTEL + "sheet%20%28auto%29.html" and row["note"] == "PDF · Text · ChordPro"


def test_a_files_part_lists_that_sources_files(conn, cfg, tmp_path):
    hotel(conn, cfg)
    script = 'drawerOf("Hotel California", "guitar");\nnote("drawer", noteDrawer("Hotel California", "inbox"));'
    drawer = attribute_of(run(conn, cfg, tmp_path, script, controls=SERVED), "data-drawer")
    assert (drawer["what"], drawer["said"]) == ("your inbox · Guitar Pro files", "1 file")
    [row] = drawer["rows"]
    assert row["ver"] == "Guitar Pro 2" and row["acts"] == ["Open", "Download"]
    assert row["open"].startswith("guitar?file=")


def test_escape_closes_the_drawer_and_gives_the_focus_back_to_its_chevron(conn, cfg, tmp_path):
    # The sheet's drawer opened, the focus on its first Open: Escape closes it, the focus back on its chevron; so does
    # its ✕; and on its chevron, Escape too.
    hotel(conn, cfg)
    kit = "(() => {\n" + KIT + "\nObject.assign(window, { openCard, cardOf, lineOf });\n})();"
    path = write_library_page(cfg.library_dir, with_script(page(conn, cfg), kit))
    try:
        browser = Browser(tmp_path / "chrome")
    except BrowserError as e:
        pytest.skip(f"chromium couldn't run: {e}")
    with browser:
        browser.open(path.as_uri())
        browser.js('openCard("Hotel California")')
        browser.click(".tile-sheet > button.tile-more")
        assert browser.wait("!document.querySelector('.drawer').hidden")
        browser.js("document.querySelector('.drawer a.go').focus()")
        browser.press("Escape")
        assert browser.wait("document.querySelector('.drawer').hidden")
        assert browser.js("document.activeElement.matches('.tile-sheet > button.tile-more')") is True
        assert browser.js("document.activeElement.getAttribute('aria-expanded')") == "false"
        assert browser.js("document.querySelectorAll('.tile.open').length") == 0
        browser.click(".tile-sheet > button.tile-more")
        assert browser.js("document.querySelector('.drawer .drawer-close').getAttribute('aria-label')") == (
            "Close: Chord sheet")
        browser.click(".drawer .drawer-close")
        assert browser.wait("document.querySelector('.drawer').hidden")
        assert browser.js("document.activeElement.matches('.tile-sheet > button.tile-more')") is True
        # On its chevron, outside the drawer, Escape closes it too, the focus staying there; and the card stays open.
        browser.press("Enter")
        assert browser.wait("!document.querySelector('.drawer').hidden")
        browser.press("Escape")
        assert browser.wait("document.querySelector('.drawer').hidden")
        assert browser.js("document.activeElement.matches('.tile-sheet > button.tile-more')") is True
        assert browser.js("document.activeElement.getAttribute('aria-expanded')") == "false"
        assert browser.js("cardOf(lineOf('Hotel California')).checkVisibility()") is True


# Notes every fetch the page makes and every resource it loads while each tile's chevron opens and closes its drawer.
QUIET = """
const asked = [];
const real = window.fetch;
window.fetch = (...args) => { asked.push(String(args[0])); return real(...args); };
const loaded = performance.getEntriesByType("resource").length;
openCard("Hotel California");
for (const more of cardOf(lineOf("Hotel California")).querySelectorAll("button.tile-more")) {
  more.click();
  more.click();
}
note("quiet", { asked, loaded: performance.getEntriesByType("resource").length - loaded,
  chevrons: cardOf(lineOf("Hotel California")).querySelectorAll("button.tile-more").length });
"""


def test_opening_a_drawer_sends_no_request(conn, cfg, tmp_path):
    hotel(conn, cfg)
    quiet = attribute_of(run(conn, cfg, tmp_path, QUIET, controls=SERVED), "data-quiet")
    assert quiet == {"asked": [], "loaded": 0, "chevrons": 6}, quiet


# --- what a card shows of a song with no sheet, a text tab, a score, links elsewhere ---------------------------


def test_a_song_with_no_sheet_has_no_tiles_but_its_notes_and_links(conn, cfg, tmp_path):
    lost = add_song(conn, "The Beatles", "Yesterday")
    update_song(conn, lost.id, match_decision="not_found")
    script = ('note("card", noteCard("Yesterday"));\n'
              'note("action", lineOf("Yesterday").querySelector(".line-action button").getAttribute("aria-label"));')
    dom = run(conn, cfg, tmp_path, script, controls=WebControls(csrf="tok"))
    card = attribute_of(dom, "data-card")
    assert card["tiles"] == [] and "tiles" not in card["parts"]
    # Look in the index; which sites had it; links
    assert card["parts"] == ["card-head", "facts", "actions", "foot", "card-sites", "find-elsewhere"], card["parts"]
    assert attribute_of(dom, "data-action") == "Fetch Yesterday by The Beatles"


def test_musescore_links_show_beside_a_sheet_too(conn, cfg, tmp_path):
    from caracole.musescore import parse_song_url

    hotel(conn, cfg)
    conn.execute("INSERT INTO musescore_index VALUES (?, ?, ?, '18')",
                 parse_song_url("https://musescore.com/song/hotel_california-1234"))
    script = ('note("card", noteCard("Hotel California"));\n'
              'note("elsewhere", text(cardOf(lineOf("Hotel California")).querySelector(".find-elsewhere")));')
    dom = run(conn, cfg, tmp_path, script)
    assert attribute_of(dom, "data-card")["parts"] == ["card-head", "facts", "tiles", "foot", "card-sites", "find-elsewhere"]
    elsewhere = attribute_of(dom, "data-elsewhere")
    assert elsewhere.startswith("ElsewhereScores on MuseScore") and "hotel_california-1234" in elsewhere


def test_a_text_tab_alone_is_a_guitar_tab_tile(conn, cfg, tmp_path):
    creep = add_song(conn, "Radiohead", "Creep")
    tab = upsert_version(conn, provider="ug", tab_id="9", song_id=creep.id, slot="guitar", kind="tabs", rating=4.5,
                         votes=3, version=1, label=None, url="https://tabs.ultimate-guitar.com/tab/9", raw={}, now="x")
    keep_file(conn, cfg.library_dir, song=creep, version_id=tab, name="tab.txt", data=b"e|--0--|", rank=1)
    put(cfg, creep, "sheet.pdf")
    update_song(conn, creep.id, status="found")
    dom = run(conn, cfg, tmp_path, 'note("card", noteCard("Creep"));\ndrawerOf("Creep", "tab");\n'
                                   'note("drawer", noteDrawer("Creep"));')
    guitar = attribute_of(dom, "data-card")["tiles"][1]
    assert (guitar["name"], guitar["href"], guitar["said"]) == (
        "Guitar tab", "Radiohead/Creep/tab.txt", "Open the guitar tab of Creep")
    assert guitar["sources"] == ["ug"] and guitar["more"] == "Guitar tab: its downloads"
    drawer = attribute_of(dom, "data-drawer")
    assert [d["text"] for d in drawer["files"]] == ["Text"] and drawer["parts"] == []


def test_a_score_you_filed_is_a_tile(conn, cfg, tmp_path):
    song = add_song(conn, "Eagles", "Desperado")
    put(cfg, song, "sheet.pdf", "score-1.pdf", "score-1.mxl", "score-2.pdf")
    update_song(conn, song.id, status="found")
    dom = run(conn, cfg, tmp_path, 'note("card", noteCard("Desperado"));\ndrawerOf("Desperado", "score");\n'
                                   'note("drawer", noteDrawer("Desperado"));')
    score = attribute_of(dom, "data-card")["tiles"][1]
    # It opens the first, in inbox.py's order of formats: MusicXML, a download; a PDF the browser shows opens.
    assert (score["name"], score["href"], score["said"]) == ("Score", "Eagles/Desperado/score-1.mxl",
                                                            "Download the score of Desperado")
    assert score["download"] == "Eagles - Desperado.mxl"
    assert "stack" in score["cls"].split()
    drawer = attribute_of(dom, "data-drawer")
    assert [d["text"] for d in drawer["files"]] == ["MusicXML", "PDF", "PDF"]
    # Put there by hand, from no site: no mark on the tile, and one part of their own, a row a file.
    assert score["sources"] == [] and drawer["parts"] == [""] and len(drawer["rows"]) == 3


def test_an_auto_sheet_alone_is_its_own_tile_in_its_colour(conn, cfg, tmp_path):
    zebra = add_song(conn, "宋冬野", "斑马，斑马")
    put(cfg, zebra, "sheet (auto).html", "sheet (auto).pdf", "sheet (auto).txt")
    update_song(conn, zebra.id, status="found")
    dom = run(conn, cfg, tmp_path, 'note("card", noteCard("斑马，斑马"));\ndrawerOf("斑马，斑马", "sheet");\n'
                                   'note("drawer", noteDrawer("斑马，斑马"));')
    [tile] = attribute_of(dom, "data-card")["tiles"]
    assert tile["name"] == "Auto sheet" and tile["from"] == "from the recording"
    assert "auto" in tile["cls"].split() and "primary" not in tile["cls"].split()
    assert tile["sources"] == ["auto"] and tile["more"] == "Auto sheet: its downloads"
    drawer = attribute_of(dom, "data-drawer")
    assert [d["text"] for d in drawer["files"]] == ["PDF", "Text"] and drawer["parts"] == []


# --- the foot -------------------------------------------------------------------------------------------------

REMOVE = """
const card = noteCard("Hotel California");
const more = cardOf(lineOf("Hotel California")).querySelector(".foot > details.foot-more");
const go = more.querySelector("form.remove button");
const closed = { open: more.open, shown: go.checkVisibility(), said: more.querySelector("summary").getAttribute("aria-label") };
more.open = true;
const opened = go.checkVisibility();
const style = getComputedStyle(go);
const failed = getComputedStyle(document.documentElement).getPropertyValue("--failed").trim();
const probe = document.createElement("span");
probe.style.color = failed;
document.body.appendChild(probe);
note("remove", { foot: card.foot, said: go.getAttribute("aria-label"), color: style.color,
  failed: getComputedStyle(probe).color, background: style.backgroundColor, border: style.borderTopColor,
  last: cardOf(lineOf("Hotel California")).querySelector(".foot").lastElementChild.className, closed, opened,
  menu: more.querySelector(".foot-menu").lastElementChild.className });
"""


def test_remove_says_remove_and_is_red_and_last(conn, cfg, tmp_path):
    put(cfg, hotel(conn, cfg), "info.json")
    remove = attribute_of(run(conn, cfg, tmp_path, REMOVE, controls=SERVED), "data-remove")
    assert remove["foot"] == ["Fetch again", "Use LaCuerda's sheet", "Add to a songbook…", "info.json", "Remove"]
    assert remove["last"].split()[0] == "foot-more" and remove["menu"].split()[0] == "remove"  # last, behind ⋯
    assert remove["closed"] == {"open": False, "shown": False, "said": "More: Hotel California"}
    assert remove["opened"] is True  # ⋯ opens info.json and Remove
    assert remove["said"] == "Remove Hotel California by Eagles from your logbook"
    # Red from the start, its words and edge, yet outlined: never filled, never the main thing to do.
    assert remove["color"] == remove["failed"] and remove["background"] == "rgba(0, 0, 0, 0)"
    assert remove["border"] != remove["color"]


def test_the_file_page_offers_no_change_but_the_command_that_fetches_versions(conn, cfg, tmp_path):
    hotel(conn, cfg)
    script = ('drawerOf("Hotel California", "sheet");\nnote("card", noteCard("Hotel California"));\n'
              'note("drawer", noteDrawer("Hotel California", "ug"));\n'
              'note("forms", cardOf(lineOf("Hotel California")).querySelectorAll("form").length);')
    dom = run(conn, cfg, tmp_path, script)
    card, drawer = attribute_of(dom, "data-card"), attribute_of(dom, "data-drawer")
    assert card["foot"] == ["Add to a songbook…"]  # no Fetch again, no Remove
    assert attribute_of(dom, "data-forms") == 0
    assert all("Use this one" not in r["acts"] for r in drawer["rows"]) and drawer["restButtons"] == []
    assert drawer["command"].startswith("caracole versions --keep-more ")


PROGS = """
const line = openCard("Synthetic Song");
const panel = cardOf(line);
const chips = Array.from(panel.querySelectorAll(".progressions .prog"));
const before = { label: text(panel.querySelector(".progressions .card-label").firstChild),
  em: text(panel.querySelector(".progressions .card-label em")), hint: panel.querySelector(".progressions .card-label").title,
  chips: chips.map((c) => [text(c), c.getAttribute("aria-label"), !!c.querySelector("svg.glyph-search")]) };
chips[0].click();
note("progs", { before, hash: location.hash,
  titles: Array.from(document.querySelectorAll("#list .line h3")).map((h) => h.textContent).sort() });
"""


def test_progressions_are_search_chips_that_filter(conn, cfg, tmp_path):
    from test_library_page import progression_library

    progression_library(conn, cfg)
    progs = attribute_of(run(conn, cfg, tmp_path, PROGS), "data-progs")
    assert (progs["before"]["label"], progs["before"]["em"]) == ("Progressions", None)  # no line of words about it
    assert progs["before"]["hint"] == "Find songs that play one"  # the label says it as a tooltip
    assert progs["before"]["chips"][0][0] == "vi–IV–I–V" and progs["before"]["chips"][0][2] is True
    assert progs["before"]["chips"][0][1].startswith("Songs with I–V–vi–IV")
    assert "prog=I+V+vi+IV" in progs["hash"] and progs["titles"] == ["In A Minor", "Synthetic Song"]


TILE_ROWS = """
const line = openCard("Hotel California");
const panel = cardOf(line);
const mid = (n) => { const b = n.getBoundingClientRect(); return Math.round(b.top + b.height / 2); };
note("rows", Array.from(panel.querySelectorAll(".tiles > .tile")).map((t) => ({
  name: text(t.querySelector(".tile-name")), height: Math.round(t.getBoundingClientRect().height),
  mids: [t.querySelector(".tile-open"), t.querySelector(".tile-source"), t.querySelector(".tile-more")]
    .filter(Boolean).map(mid),
  mark: !!t.querySelector(".tile-source [data-source]"),
  visible: Array.from(panel.querySelectorAll(".foot button, .foot a, .foot summary")).filter((n) => n.checkVisibility())
    .map((n) => text(n)) })));
"""


@pytest.mark.parametrize(("size", "touch"), [("360,780", True), ("390,844", True), (cards.IN_PLACE, False),
                                             ("1280,900", False)])
def test_a_tile_is_one_row_and_its_source_keeps_its_mark_beside_its_name(conn, cfg, tmp_path, size, touch):
    # What you play from, a row each at every width: its name and version, the marks of where it came from, its
    # chevron at the end; 56 to 64 px tall on a touch screen, 48 px at most with a mouse, whether the card is under its
    # line (a phone, a laptop under 1200 px) or in the pane beside the list (1280). On a phone 360 px wide its name
    # takes the room of its arrow. Under the card's foot only Fetch again, Use LaCuerda's sheet, Add to a songbook and
    # ⋯ show.
    hotel(conn, cfg)
    rows = attribute_of(run(conn, cfg, tmp_path, TILE_ROWS, controls=SERVED, size=size, touch=touch), "data-rows")
    assert rows and all(max(r["mids"]) - min(r["mids"]) <= 16 for r in rows), rows  # one row
    assert all(56 <= r["height"] <= 64 if touch else r["height"] <= 48 for r in rows), rows
    [sheet] = [r for r in rows if r["name"] == "Chord sheet"]
    assert sheet["mark"] is True, sheet  # the marks of where its versions came from
    assert rows[0]["visible"] == ["Fetch again", "Use LaCuerda's sheet", "Add to a songbook…", "⋯"], rows[0]["visible"]


MANY = """
const card = caracoleCard({}, caracoleRows({}));
const long = "I–V7/IV–IV–I–vi–V7/V–V7–I–V7/IV–IV–iv–I–vi–V7–I";
const box = card.progressions(["a", "b", "c", "d", "e", "f"].map((k, n) => ({ text: n ? "I–IV–V" + n : long,
  said: "Your songs with " + k, go: () => {} })));
document.body.appendChild(box);
const shown = () => Array.from(box.querySelectorAll(".prog")).filter((c) => c.checkVisibility());
const first = shown().map((c) => [Math.round(c.getBoundingClientRect().width), c.getAttribute("aria-label")]);
const more = box.querySelector("button.progs-more");
const before = { n: first.length, widest: Math.max(...first.map((f) => f[0])), said: first[0][1], more: more ? text(more) : null };
if (more) more.click();
note("many", { before, after: shown().length, gone: !box.querySelector("button.progs-more") || !box.querySelector("button.progs-more").checkVisibility() });
"""


def test_progressions_are_short_chips_four_and_a_button_for_the_rest(conn, cfg, tmp_path):
    many = attribute_of(run(conn, cfg, tmp_path, MANY), "data-many")
    assert many["before"]["n"] == 4 and many["before"]["more"] == "+2", many  # four, and the rest one press away
    assert many["before"]["widest"] <= 17 * 16, many  # a string of numerals is cut, never a wide chip
    assert many["before"]["said"] == "Your songs with a"  # the whole of it for a screen reader
    assert many["after"] == 6 and many["gone"] is True, many


# --- its layout: 390 px and a desktop, the drawer right under its tile ----------------------------------------

LAYOUT = """
const line = openCard("Hotel California");
const panel = cardOf(line);
const tiles = Array.from(panel.querySelectorAll(".tiles > .tile"));
const box = (n) => { const b = n.getBoundingClientRect(); return [Math.round(b.left), Math.round(b.right),
  Math.round(b.top), Math.round(b.bottom)]; };
const css = getComputedStyle;
const at = (kind) => {
  drawerOf("Hotel California", kind);
  const drawer = panel.querySelector(".drawer"), tile = panel.querySelector(".tile-" + kind);
  return { after: drawer.previousElementSibling.className, drawer: box(drawer), tile: box(tile),
    corners: [css(tile).borderBottomLeftRadius, css(tile).borderBottomRightRadius, css(drawer).borderTopLeftRadius,
      css(drawer).borderTopRightRadius],
    stack: [css(tile, "::before").content, css(tile, "::after").content], stacked: tile.classList.contains("stack"),
    score: box(panel.querySelector(".tile-score")) };
};
note("layout", { sheet: at("sheet"), guitar: at("guitar"), tiles: tiles.map(box),
  wide: [document.documentElement.scrollWidth, innerWidth] });
"""


@pytest.mark.parametrize(("size", "touch"), [("320,640", True), ("390,844", True), ("640,900", False),
                                             ("1280,900", False)])
def test_the_card_fits_with_the_drawer_under_its_tile(conn, cfg, tmp_path, size, touch):
    hotel(conn, cfg)
    layout = attribute_of(run(conn, cfg, tmp_path, LAYOUT, size=size, controls=SERVED, touch=touch), "data-layout")
    wide, width = layout["wide"]
    assert wide <= width, layout  # no sideways scroll
    for kind in ("sheet", "guitar"):
        at = layout[kind]
        left, right, _, bottom = at["tile"]
        assert at["after"].startswith("tile tile-" + kind), (kind, at)  # its tile's next sibling
        assert abs(at["drawer"][2] - bottom) <= 1, (kind, at)  # touching it, right under it
        assert abs(at["drawer"][0] - left) <= 1 and abs(at["drawer"][1] - right) <= 1, (kind, at)  # its edges
        assert at["corners"] == ["0px"] * 4, (kind, at)  # one box: the tile's bottom corners and its top square
        assert at["stacked"] is True and at["stack"] == ["none", "none"], (kind, at)  # no stack under it while open
        assert at["score"][2] >= at["drawer"][3], (kind, at)  # the tiles after it under its drawer
    # One tile a row, on a phone, a small tablet's width and from 720 px.
    assert len({t[0] for t in layout["tiles"]}) == 1 and len({t[2] for t in layout["tiles"]}) == len(layout["tiles"])


# The sheet's drawer opened: where its downloads lie, in rows, and its ✕.
CLOSE_ROOM = """
openCard("Hotel California");
drawerOf("Hotel California", "sheet");
const d = cardOf(lineOf("Hotel California")).querySelector(".drawer");
const box = (n) => { const b = n.getBoundingClientRect(); return [b.left, b.right, b.top, b.bottom]; };
note("room", { close: box(d.querySelector(".drawer-close")),
  files: Array.from(d.querySelectorAll(".drawer-files > *")).map(box), drawer: box(d) });
"""


@pytest.mark.parametrize(("size", "touch"), [("390,844", True), ("1280,900", False)])
def test_a_drawers_downloads_leave_room_for_its_close_and_wrap_under_it(conn, cfg, tmp_path, size, touch):
    # The ✕ at the drawer's top right is in the way of its downloads' first row alone: they never lie under it, and on
    # a phone's touch screen the sheet's Download, PDF, Text, ChordPro and its export take two rows, not three.
    hotel(conn, cfg)
    room = attribute_of(run(conn, cfg, tmp_path, CLOSE_ROOM, controls=SERVED, size=size, touch=touch), "data-room")
    cl, cr, ct, cb = room["close"]
    assert not [f for f in room["files"] if f[0] < cr and f[1] > cl and f[2] < cb and f[3] > ct], room
    assert all(f[1] <= room["drawer"][1] for f in room["files"]), room  # inside it
    mids = sorted((f[2] + f[3]) / 2 for f in room["files"])
    rows = [m for n, m in enumerate(mids) if n == 0 or m - mids[n - 1] > 8]  # each row's first middle
    if touch:
        assert len(rows) == 2, room
        assert abs(rows[0] - (ct + cb) / 2) <= 2, room  # the first row level with the ✕


# --- the card at the pane's width: as it reads in place ------------------------------------------------------

PANE = """
const line = openCard("Hotel California");  // from 1200 px its card goes into lane 1's #card-pane, 400-480 px wide
const card = cardOf(line), pane = document.getElementById("card-pane");
drawerOf("Hotel California", "sheet");
const box = (n) => n.getBoundingClientRect();
const row = card.querySelector('.drawer-part[data-source="ug"] .vrow');
note("pane", { inPane: pane.contains(card), width: pane.clientWidth, outer: pane.offsetWidth, wide: pane.scrollWidth,
  stacked: box(row.querySelector(".vbtns")).top >= box(row.querySelector(".ver")).bottom - 0.5,
  buttons: Array.from(card.querySelectorAll(".vrow .vbtns > *")).map((b) => Math.round(box(b).height)),
  rows: Array.from(card.querySelectorAll(".tile")).map((t) => Math.round(box(t).height)) });
"""


@pytest.mark.parametrize("controls", [SERVED, None], ids=["served", "file"])
@pytest.mark.parametrize("size", ["1200,900", "1280,900", "1440,900"])
def test_the_card_fits_the_laptops_pane_on_a_wide_screen(conn, cfg, tmp_path, size, controls):
    # In the pane a card is as narrow as a phone's: its version rows stacked (their words, then their buttons, each
    # on one line), its tiles a row each, nothing wider than the pane, whatever the window.
    hotel(conn, cfg)
    pane = attribute_of(run(conn, cfg, tmp_path, PANE, controls=controls, size=size), "data-pane")
    assert pane["inPane"] and 400 <= pane["outer"] <= 480 and pane["wide"] <= pane["width"], pane
    assert pane["stacked"] is True and all(h <= 48 for h in pane["rows"]), pane
    assert pane["buttons"] and all(h <= 32 for h in pane["buttons"]), pane  # "Use this one" never wraps


WIDE_ROWS = """
const card = cardOf(openCard("Hotel California"));
drawerOf("Hotel California", "sheet");
const box = (n) => n.getBoundingClientRect();
note("wide", Array.from(card.querySelectorAll(".vrow")).map((r) => box(r.querySelector(".vbtns")).top
  < box(r.querySelector(".ver")).bottom));
"""


def test_a_version_takes_one_row_in_a_card_560_px_wide(conn, cfg, tmp_path):
    # Under its line on a laptop under 1200 px the card is about 780 px wide: a version's number, rating, note and
    # buttons side by side, as they were from 720 px; the card's own width decides it, never the window's.
    hotel(conn, cfg)
    wide = attribute_of(run(conn, cfg, tmp_path, WIDE_ROWS, controls=SERVED, size=cards.IN_PLACE), "data-wide")
    assert wide and all(wide), wide


BOX = """
const line = openCard("Hotel California"), card = cardOf(line), css = getComputedStyle;
note("box", { inPane: document.getElementById("card-pane").contains(card), selected: line.classList.contains("selected"),
  line: css(line).marginTop, card: [css(card).rowGap, css(card).paddingBottom], foot: css(card.querySelector(".foot")).display,
  tokens: [css(card).getPropertyValue("--card-gap").trim(), css(card).getPropertyValue("--card-pad-end").trim()],
  edge: [css(line).borderLeftWidth, css(line).borderTopLeftRadius] });
"""


@pytest.mark.parametrize("size", ["1280,900", cards.IN_PLACE])
def test_the_cards_box_is_its_panels_own_and_a_selected_line_is_no_empty_card(conn, cfg, tmp_path, size):
    hotel(conn, cfg)
    box = attribute_of(run(conn, cfg, tmp_path, BOX, controls=SERVED, size=size), "data-box")
    assert box["card"] == ["14px", "14px"] and box["foot"] == "flex", box  # .line-panel.song-card's, in place or not
    assert box["tokens"] == ["14px", "14px"], box  # card.css's --card-gap and --card-pad-end, which library.css reads
    if size == "1280,900":  # the card in the pane: its line, selected, isn't raised as an empty card
        assert box["inPane"] and box["selected"] and box["line"] == "0px", box
        assert box["edge"] == ["0px", "0px"], box  # no card's edge or corners: a line as its neighbours are
    else:  # in place, the opened line is raised as today
        assert not box["inPane"] and box["line"] == "6px", box
        assert box["edge"] == ["1px", "12px"], box


@pytest.mark.parametrize("size", ["390,844", "1280,900"])
def test_the_card_meets_touch_targets_with_a_drawer_open(conn, cfg, tmp_path, size):
    from helpers.targets import ARTIST_NAMES, noted, noting, small_targets

    hotel(conn, cfg)
    script = 'openCard("Hotel California");\ndrawerOf("Hotel California", "sheet");\n' + noting(
        "data-short", small_targets(ARTIST_NAMES))
    dom = run(conn, cfg, tmp_path, script, size=size, controls=SERVED, touch=True)
    assert noted(dom, "data-short") == []


# The contrast of each text the card shows against the first solid background under it, in its theme.
READS = """
openCard("Hotel California");
drawerOf("Hotel California", "sheet");
const rgb = (t) => (/^rgba?\\(([\\d.]+),\\s*([\\d.]+),\\s*([\\d.]+)(?:,\\s*([\\d.]+))?\\)$/.exec(t) || []).slice(1).map(Number);
const lum = (c) => { const f = (v) => (v / 255 <= 0.04045 ? v / 255 / 12.92 : ((v / 255 + 0.055) / 1.055) ** 2.4);
  return 0.2126 * f(c[0]) + 0.7152 * f(c[1]) + 0.0722 * f(c[2]); };
const behind = (n) => { for (let at = n; at; at = at.parentElement) { const c = rgb(getComputedStyle(at).backgroundColor);
  if (c.length && !(c[3] < 1)) return c; } return [255, 255, 255]; };
const ratio = (n) => { const [hi, lo] = [lum(rgb(getComputedStyle(n).color)), lum(behind(n))].sort((a, b) => b - a);
  return Math.round((hi + 0.05) / (lo + 0.05) * 100) / 100; };
const reads = {};
for (const sel of [".tile-name", ".tile-from", ".drawer-files .lead", ".drawer .dl", ".drawer-said", ".vrow .ver",
  ".vrow .stars", ".vrow .note", ".inuse", ".drawer-rest", ".card-label", ".facts", ".btn.remove", ".tile-ico",
  ".line-plays .play", ".line-plays .play .n"]) {
  const n = (sel.startsWith(".line-plays") ? lineOf("Hotel California") : cardOf(lineOf("Hotel California"))).querySelector(sel);
  reads[sel] = n ? ratio(n) : null;
}
note("reads", reads);
"""


@pytest.mark.parametrize("scheme", ["light", "dark"])
def test_the_card_reads_in_both_themes(conn, cfg, tmp_path, scheme):
    from caracole.musescore import parse_song_url

    hotel(conn, cfg)
    conn.execute("INSERT INTO musescore_index VALUES (?, ?, ?, '18')",
                 parse_song_url("https://musescore.com/song/hotel_california-1234"))  # Find it elsewhere's label
    reads = attribute_of(run(conn, cfg, tmp_path, READS, controls=SERVED, media={"prefers-color-scheme": scheme}),
                         "data-reads")
    weak = {sel: value for sel, value in reads.items() if value is None or value < 4.5}
    assert weak == {}, (scheme, reads)


def card(browser, item):
    """The selector of the open card of the line ``item`` finds (opened if it is not): the card moves, so it is found
    again by its chevron each time it is read."""
    return cards.open_card(browser, item)


# --- served: a line drawn again ---------------------------------------------------------------------------------


def test_a_line_drawn_again_keeps_its_card_open_and_its_drawer_closed(conn, cfg, live, browser):
    # Fetch again pressed in its foot, a drawer open: once the lookup is over, the song's line is drawn again from
    # what the library has now, its card still open, its drawer closed.
    base, posted = live
    song = hotel(conn, cfg)
    item = f'article.line[data-id="{song.id}"]'
    browser.open(base)
    browser.click(item + " .line-more")
    browser.click(card(browser, item) + " .tile-sheet > button.tile-more")
    assert browser.wait(f"!document.querySelector('{card(browser, item)} .drawer').hidden")
    browser.js(f"[...document.querySelectorAll('{card(browser, item)} .foot button')].find((b) => b.textContent === 'Fetch again')"
               ".click()")
    posted.next(0)
    assert browser.wait(f"document.querySelector('{item} .progress')?.dataset.tone === 'ready'", timeout=20)
    assert browser.js(f"document.querySelector('{item} .line-more').getAttribute('aria-expanded')") == "true"
    assert browser.js(f"document.querySelector('{card(browser, item)}').hidden") is False
    assert browser.js(f"document.querySelector('{card(browser, item)} .drawer').hidden") is True
    assert browser.js(f"[...document.querySelectorAll('{card(browser, item)} button.tile-more')].map((c) => "
                      "c.getAttribute('aria-expanded'))") == ["false"] * 6
    assert browser.js(f"document.querySelectorAll('{card(browser, item)} .tile.open').length") == 0


# --- served: what a drawer's versions do ---------------------------------------------------------------------


class FakeVersions:
    """The commands the drawer's posts queue, faked (``ran``, each one's words): ``caracole versions --keep-more``
    keeps the next two versions not kept beside the sheet, as the real one would within a lookup's budget; any
    other (``--choose``, ``--clear``, ``caracole get``) changes nothing."""

    def __init__(self, cfg):
        self.cfg = cfg
        self.ran: list[tuple[str, ...]] = []

    def __call__(self, args, emit):
        from helpers.library_songs import TABS

        from caracole import db
        from caracole.overrides import override_key
        from caracole.sheet_versions import version_names
        from caracole.songs import find_song

        self.ran.append(tuple(args))
        if args[0] == "versions" and "--keep-more" in args:
            conn = db.connect(self.cfg.db_path)
            try:
                song = find_song(conn, override_key(f"{args[-2]} - {args[-1]}"))
                for rank, tab in enumerate(TABS[3:5], start=4):
                    vid = conn.execute("SELECT id FROM versions WHERE song_id = ? AND tab_id = ?",
                                       (song.id, tab)).fetchone()[0]
                    text, doc, _ = version_names(tab)
                    keep_file(conn, self.cfg.library_dir, song=song, version_id=vid, name=text, data=tab.encode(),
                              rank=rank)
                    keep_file(conn, self.cfg.library_dir, song=song, version_id=vid, name=doc, data=b"{}", rank=rank)
            finally:
                conn.close()
        return 0


class Posts(list):
    """Each POST the page sent, as (path, its form), in order; ``next`` waits for the one after ``n``."""

    def next(self, n: int, timeout: float = 10.0) -> tuple[str, dict]:
        import time

        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if len(self) > n:
                return self[n]
            time.sleep(0.05)
        raise AssertionError(f"the page posted nothing after {n}")


@pytest.fixture
def versions_served(cfg):
    """caracole serve on a free port, its queue running FakeVersions and its page asking how its requests go every
    100 ms: its address, the posts it got, and the commands it ran."""
    import threading
    from urllib.parse import parse_qs

    from caracole.web.app import WebApp
    from caracole.web.jobs import JobQueue
    from caracole.web.security import allowed_hosts
    from caracole.web.server import make_server

    runner = FakeVersions(cfg)
    queue = JobQueue(runner)
    queue.start()
    app = WebApp(cfg, queue, allowed=allowed_hosts("127.0.0.1"), csrf="tok", timers={"poll": 100, "undo": 500},
                 searches_lacuerda=False)
    posts = Posts()
    answer = app.handle

    def handle(request):
        if request.method == "POST":
            posts.append((request.target, {k: v[0] for k, v in parse_qs(request.body.decode()).items()}))
        return answer(request)

    app.handle = handle
    server = make_server(app, "127.0.0.1", 0)
    threading.Thread(target=server.serve_forever, args=(0.01,), daemon=True).start()
    yield f"http://127.0.0.1:{server.server_address[1]}/", posts, runner
    server.shutdown()
    server.server_close()
    queue.stop()


UG, LC = '.drawer-part[data-source="ug"]', '.drawer-part[data-source="lacuerda"]'  # the sheet drawer's parts


def drawer_of(browser, song):
    """The song's card opened, and its sheet tile's drawer, then shown; its line's selector."""
    item = f'article.line[data-id="{song.id}"]'
    browser.click(item + " .line-more")
    browser.click(card(browser, item) + " .tile-sheet > button.tile-more")
    assert browser.wait(f"!document.querySelector('{card(browser, item)} .drawer').hidden")
    return item


def press(browser, item, words, where=".drawer"):
    """The button of the song's ``where`` that says ``words``, pressed as a hand would."""
    found = (f"[...document.querySelectorAll('{card(browser, item)} {where} button')].find((b) => b.textContent === "
             f"{json.dumps(words)})")
    assert browser.wait(f"!!({found})"), browser.js(f"[...document.querySelectorAll('{card(browser, item)} {where} button')]"
                                                   ".map((b) => b.textContent)")
    browser.js(f"({found}).dataset.pressMe = '1'")
    browser.click(f"{card(browser, item)} {where} button[data-press-me]")


def test_use_this_one_posts_choose_with_the_tab(conn, cfg, versions_served, browser):
    base, posts, _ = versions_served
    song = hotel(conn, cfg)
    browser.open(base)
    item = drawer_of(browser, song)
    assert browser.js(f"[...document.querySelectorAll('{card(browser, item)} {UG} .vrow')].map((r) => "
                      "[...r.querySelectorAll('.vbtns button, .vbtns .inuse')].map((b) => b.textContent))") == [
        ["In use"], ["Use this one"], ["Use this one"]]
    press(browser, item, "Use this one", UG)
    assert posts.next(0) == ("/versions/choose", {"csrf": "tok", "song": str(song.id), "identity": song.key, "tab": "46191"})
    # Its request shows on the song's line, as a lookup's does.
    assert browser.wait(f"!!document.querySelector('{item} .progress')?.textContent")


def test_fetch_them_posts_keep_more_and_says_fetch_n_more(conn, cfg, versions_served, browser):
    base, posts, _ = versions_served
    song = hotel(conn, cfg)
    few = add_song(conn, "Eagles", "Take It Easy")  # three versions not kept: one press keeps them all
    for n, tab in enumerate(("700", "701", "702", "703")):
        vid = upsert_version(conn, provider="ug", tab_id=tab, song_id=few.id, slot="sheet", kind="chords",
                             rating=4.5 - n / 10, votes=10, version=n + 1, label=None,
                             url=f"https://tabs.ultimate-guitar.com/tab/{tab}", raw={}, now="x")
        if n == 0:
            keep_file(conn, cfg.library_dir, song=few, version_id=vid, name="sheet.txt", data=b"G\n", rank=1)
    update_song(conn, few.id, status="found")
    browser.open(base)
    item = drawer_of(browser, song)
    rest = f"document.querySelector('{card(browser, item)} {UG} .drawer-rest')"
    assert browser.js(f"{rest}.querySelector('.rest-said').textContent") == "10 more on UG, not kept"
    assert browser.js(f"{rest}.querySelector('button').getAttribute('aria-label')") == (
        "Fetch 6 more versions of Hotel California from UG")
    other = drawer_of(browser, few)
    assert browser.js(f"[...document.querySelectorAll('{card(browser, other)} {UG} .drawer-rest button')]"
                      ".map((b) => b.textContent)") == ["Fetch them"]
    press(browser, item, "Fetch 6 more")
    assert posts.next(0) == ("/versions/keep-more", {"csrf": "tok", "song": str(song.id), "identity": song.key})


def test_after_keep_more_the_drawer_counts_again_from_the_jobs_view(conn, cfg, versions_served, browser):
    base, posts, runner = versions_served
    song = hotel(conn, cfg)
    browser.open(base)
    item = drawer_of(browser, song)
    press(browser, item, "Fetch 6 more")
    posts.next(0)
    # Once its job is over, the line is drawn again from what the library has: two more kept, eight left.
    assert browser.wait(f"document.querySelector('{item} .progress')?.dataset.tone === 'ready'", timeout=20)
    assert runner.ran == [("versions", "--keep-more", "--progress", "--", "Eagles", "Hotel California")]
    assert browser.js(f"document.querySelector('{card(browser, item)} .drawer').hidden") is True  # closed, as it was drawn again
    browser.click(card(browser, item) + " .tile-sheet > button.tile-more")
    assert browser.wait(f"!document.querySelector('{card(browser, item)} .drawer').hidden")
    assert browser.js(f"document.querySelector('{card(browser, item)} {UG} .drawer-said').textContent") == (
        "13 on UG · 5 in your logbook")
    assert browser.js(f"document.querySelector('{card(browser, item)} {UG} .drawer-rest .rest-said').textContent") == (
        "8 more on UG, not kept")
    assert browser.js(f"document.querySelectorAll('{card(browser, item)} {UG} .vrow').length") == 5


def test_back_to_caracoles_pick_only_when_pinned(conn, cfg, versions_served, browser):
    from caracole.overrides import add_pin

    base, posts, _ = versions_served
    song = hotel(conn, cfg)
    browser.open(base)
    item = drawer_of(browser, song)
    assert browser.js(f"document.querySelector('{card(browser, item)} .drawer').textContent").count("Back") == 0
    add_pin(cfg.overrides_file, song.display, ["https://tabs.ultimate-guitar.com/tab/eagles/hotel-california-chords-46191"])
    browser.open(base)
    item = drawer_of(browser, song)
    press(browser, item, "Back to our pick", UG + " .drawer-head")
    assert posts.next(0) == ("/versions/clear", {"csrf": "tok", "song": str(song.id), "identity": song.key})


def test_lacuerda_use_this_one_posts_the_lookup_with_its_page(conn, cfg, versions_served, browser):
    base, posts, _ = versions_served
    song = hotel(conn, cfg)
    browser.open(base)
    item = drawer_of(browser, song)
    press(browser, item, "Use this one", LC)
    assert posts.next(0) == ("/lookup", {"csrf": "tok", "song": str(song.id), "identity": song.key, "lacuerda": LACUERDA[0]})


def test_lacuerda_use_this_one_waits_for_a_pin_to_go(conn, cfg, versions_served, browser):
    # A UG version chosen (a [pin]) outranks a LaCuerda pick: its Use this one would do nothing until the pin goes.
    from caracole.overrides import add_pin

    base, posts, _ = versions_served
    song = hotel(conn, cfg)
    add_pin(cfg.overrides_file, song.display, ["https://tabs.ultimate-guitar.com/tab/eagles/hotel-california-chords-46191"])
    browser.open(base)
    item = drawer_of(browser, song)
    buttons = f"[...document.querySelectorAll('{card(browser, item)} {LC} button')].map((b) => b.textContent)"
    assert "Use this one" not in browser.js(buttons)
    # Its note says where the one Back to our pick is: the UG part's, above it, never a second button of its own.
    assert "Back to our pick" not in browser.js(buttons)
    assert browser.js(f"document.querySelector('{card(browser, item)} {LC} .pin-note').textContent") == (
        "Your UG choice is in use: Back to our pick, above, first.")
    every = f"[...document.querySelectorAll('{card(browser, item)} .drawer button')].map((b) => b.textContent)"
    assert browser.js(every).count("Back to our pick") == 1
    press(browser, item, "Back to our pick", UG)
    assert posts.next(0) == ("/versions/clear", {"csrf": "tok", "song": str(song.id), "identity": song.key})
