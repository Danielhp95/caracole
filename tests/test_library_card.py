"""A song of yours opened on the library page (card.js, card.css), in a real browser: what you play from it as tiles,
each source's versions of each as chips that open one drawer under the row of tiles that holds its tile, its
progressions, where else to find it, and its foot, Remove at its end; on the file on disk, and on the page caracole
serve serves (here, as it writes it: its data and its forms, with no server behind them).

A test adds a script after the page's own (``with_script``), which opens the song's card and notes what it shows
(``KIT``: ``noteCard``, ``noteDrawer``) into an attribute of the body, read back from the DOM once the page ran.
"""

from __future__ import annotations

import json
from urllib.parse import quote

import pytest
import test_web_page_again as served_page
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
KIT = r"""
const text = (n) => (n ? n.textContent.replace(/\s+/g, " ").trim() : null);
const lineOf = (title) => Array.from(document.querySelectorAll("#list .line"))
  .find((l) => l.querySelector("h3").textContent === title);
const openCard = (title) => {
  const line = lineOf(title);
  const more = line.querySelector(".line-more");
  if (more.getAttribute("aria-expanded") !== "true") more.click();
  return line;
};
const noteCard = (title) => {
  const line = openCard(title);
  const panel = line.querySelector(".line-panel");
  const tiles = Array.from(panel.querySelectorAll(".tiles > .tile")).map((t) => {
    const open = t.querySelector(".tile-open");
    return {
      cls: t.className, name: text(t.querySelector(".tile-name")), from: text(t.querySelector(".tile-from")),
      href: open.getAttribute("href"), said: open.getAttribute("aria-label"), download: open.getAttribute("download"),
      lead: text(t.querySelector(".tile-versions .lead")),
      chips: Array.from(t.querySelectorAll(".tile-versions .vchip")).map((c) => ({
        tag: c.tagName.toLowerCase(), source: c.dataset.source || (c.querySelector("[data-source]") || {}).dataset?.source
          || null, n: text(c.querySelector(".n")), said: c.getAttribute("aria-label") || text(c.querySelector(".vchip-name")),
        expanded: c.getAttribute("aria-expanded") })),
      downloads: Array.from(t.querySelectorAll(".tile-downloads a")).map((a) => ({ text: text(a),
        said: a.getAttribute("aria-label"), href: a.getAttribute("href"), download: a.getAttribute("download") })),
    };
  });
  const parts = Array.from(panel.children).map((c) => c.className.split(" ").find((x) => x !== "row-group") ||
    c.tagName.toLowerCase());
  return { tiles, parts, foot: Array.from(panel.querySelectorAll(".foot button, .foot a")).map(text) };
};
const noteDrawer = (title) => {
  const d = lineOf(title).querySelector(".drawer");
  return { hidden: d.hidden, id: d.id, what: text(d.querySelector(".drawer-what")),
    said: text(d.querySelector(".drawer-said")), after: d.previousElementSibling.className,
    head: Array.from(d.querySelectorAll(".drawer-head button, .drawer-head form")).map(text),
    rows: Array.from(d.querySelectorAll(".vrow")).map((r) => ({ cls: r.className, ver: text(r.querySelector(".ver")),
      stars: text(r.querySelector(".stars")), note: text(r.querySelector(".note")),
      acts: Array.from(r.querySelectorAll(".vbtns > *")).map(text),
      open: (r.querySelector("a.go") || { getAttribute: () => null }).getAttribute("href") })),
    rest: text(d.querySelector(".drawer-rest .rest-said")), command: text(d.querySelector(".drawer-rest code")),
    restButtons: Array.from(d.querySelectorAll(".drawer-rest button")).map(text) };
};
const chipOf = (title, source, kind) => lineOf(title)
  .querySelector(".tile" + (kind ? ".tile-" + kind : "") + ' button.vchip[data-source="' + source + '"]');
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
    assert [t["name"] for t in tiles] == ["Chord sheet", "Guitar Pro", "Harmonica tab", "Lyrics", "Score"], tiles
    assert [t["href"] for t in tiles] == [HOTEL + "sheet.html", HOTEL + "guitar-1.gp5", HOTEL + "harmonica-1.txt",
                                          HOTEL + "lyrics.txt", HOTEL + "score-1.mxl"]
    assert [t["said"] for t in tiles] == [
        "Open the chord sheet of Hotel California", "Download the Guitar Pro file of Hotel California",
        "Open the harmonica tab of Hotel California", "Open the lyrics of Hotel California",
        "Download the score of Hotel California"]
    # From the file, a Guitar Pro file and a MusicXML score download under the song's name.
    assert tiles[1]["download"] == "Eagles - Hotel California.gp5" and tiles[0]["download"] is None
    assert tiles[4]["download"] == "Eagles - Hotel California.mxl"
    assert [t["from"] for t in tiles] == ["Ver 3 · 4.86★ · in use", "guitar-1.gp5", "Tab 1",
                                          "synced to the recording", "Score 1 (MusicXML)"]
    assert "primary" in tiles[0]["cls"].split() and not any("primary" in t["cls"].split() for t in tiles[1:])
    # Served with alphaTab, the Guitar Pro tile opens caracole serve's Guitar Pro page.
    served = attribute_of(run(conn, cfg, tmp_path, 'note("card", noteCard("Hotel California"));', controls=SERVED),
                          "data-card")["tiles"][1]
    assert served["href"].startswith("guitar?file=") and served["download"] is None
    assert served["said"] == "Open the Guitar Pro tab of Hotel California"


def test_the_sheet_tile_downloads_pdf_text_chordpro_and_each_export(conn, cfg, tmp_path):
    hotel(conn, cfg)
    sheet = attribute_of(run(conn, cfg, tmp_path, 'note("card", noteCard("Hotel California"));'),
                         "data-card")["tiles"][0]
    assert [(d["text"], d["href"]) for d in sheet["downloads"]] == [
        ("PDF", HOTEL + "sheet.pdf"), ("Text", HOTEL + "sheet.txt"), ("ChordPro", HOTEL + "sheet.cho"),
        ("PDF · G Dorian, capo 0", HOTEL + quote(EXPORT))]
    assert all(d["download"] is not None for d in sheet["downloads"])
    assert sheet["downloads"][0]["said"] == "Download the PDF of Hotel California"
    assert sheet["downloads"][3]["said"] == "Download the PDF of Hotel California in G Dorian, capo 0"


def test_chips_count_versions_per_source(conn, cfg, tmp_path):
    hotel(conn, cfg)
    tiles = attribute_of(run(conn, cfg, tmp_path, 'note("card", noteCard("Hotel California"));'), "data-card")["tiles"]
    chips = {t["name"]: (t["lead"], [(c["tag"], c["source"], c["n"], c["said"]) for c in t["chips"]]) for t in tiles}
    assert chips["Chord sheet"] == ("Versions", [
        ("button", "ug", "13", "Ultimate Guitar: 13 versions"), ("button", "lacuerda", "2", "LaCuerda: 2 versions"),
        ("button", "auto", "1", "the audio (auto-chords): 1 version")])  # an auto sheet beside the human one
    assert chips["Guitar Pro"] == ("Files", [("button", "gtptabs", "1", "gtptabs.com: 1 file"),
                                             ("button", "inbox", "1", "your inbox: 1 file")])
    # One source with one version, nothing to choose: From it, no chevron, no drawer.
    assert chips["Lyrics"] == ("From", [("span", "lrclib", None, "LRCLIB")])
    assert chips["Harmonica tab"] == ("From", [("span", "harptabs", None, "harptabs.com")])
    assert chips["Score"] == ("From", [("span", "inbox", None, "your inbox")])
    # More than one version: a small stack.
    assert [("stack" in t["cls"].split()) for t in tiles] == [True, True, False, False, False]
    assert all(c["expanded"] == "false" for t in tiles for c in t["chips"] if c["tag"] == "button")


# Opens the UG chip, then LaCuerda's (one drawer at a time), then LaCuerda's again (closed); notes each step.
CHIPS = """
const ug = chipOf("Hotel California", "ug");
ug.click();
const first = { drawer: noteDrawer("Hotel California"), ug: ug.getAttribute("aria-expanded"),
  controls: ug.getAttribute("aria-controls") };
const lc = chipOf("Hotel California", "lacuerda");
lc.click();
const second = { drawer: noteDrawer("Hotel California"), ug: ug.getAttribute("aria-expanded"),
  lc: lc.getAttribute("aria-expanded") };
lc.click();
note("chips", { first, second, closed: noteDrawer("Hotel California").hidden, lc: lc.getAttribute("aria-expanded"),
  drawers: lineOf("Hotel California").querySelectorAll(".drawer").length });
"""


def test_a_chip_opens_its_drawer_and_another_chip_closes_it(conn, cfg, tmp_path):
    hotel(conn, cfg)
    chips = attribute_of(run(conn, cfg, tmp_path, CHIPS), "data-chips")
    first, second = chips["first"], chips["second"]
    assert first["ug"] == "true" and first["controls"] == first["drawer"]["id"] and not first["drawer"]["hidden"]
    assert first["drawer"]["what"] == "Ultimate Guitar · chord sheets"
    assert second["ug"] == "false" and second["lc"] == "true" and second["drawer"]["what"] == "LaCuerda · chord sheets"
    assert chips["closed"] is True and chips["lc"] == "false" and chips["drawers"] == 1


def test_the_ug_drawer_lists_the_kept_versions_and_counts_the_rest(conn, cfg, tmp_path):
    from helpers.cli_lines import parsed

    hotel(conn, cfg)
    drawer = attribute_of(run(conn, cfg, tmp_path, 'chipOf("Hotel California", "ug").click();\n'
                                                   'note("drawer", noteDrawer("Hotel California"));'), "data-drawer")
    assert drawer["said"] == "13 versions on the site · 3 kept in your library"
    rows = drawer["rows"]
    assert [(r["ver"], r["stars"]) for r in rows] == [
        ("Ver 3", "4.86★ · 408 votes"), ("Ver 4", "4.75★ · 850 votes"), ("Ver 5", "4.70★ · 800 votes")], rows
    assert [r["note"] for r in rows] == ["Every line of the lyrics · caracole's pick", "80% of the lyrics",
                                         "50% of the lyrics"]
    assert [r["acts"] for r in rows] == [["In use", "Open"], ["Open"], ["Open"]]  # the file chooses nothing
    assert [r["open"] for r in rows] == [HOTEL + "sheet.html", HOTEL + "version-46191.html",
                                         HOTEL + "version-46192.txt"]
    assert "cur" in rows[0]["cls"].split()
    # The rest are counted, not listed; from the file, the command that fetches them.
    assert drawer["rest"] == "10 more on Ultimate Guitar, not kept" and drawer["restButtons"] == []
    assert drawer["command"] == "caracole versions --keep-more 'Eagles - Hotel California'"
    words, params = parsed(drawer["command"])
    assert words == ("versions",) and params["keep_more"] is True and list(params["song"]) == ["Eagles - Hotel California"]


def test_the_lacuerda_and_auto_drawers_list_theirs(conn, cfg, tmp_path):
    hotel(conn, cfg)
    script = ('chipOf("Hotel California", "lacuerda").click();\nconst lc = noteDrawer("Hotel California");\n'
              'chipOf("Hotel California", "auto").click();\nnote("drawers", [lc, noteDrawer("Hotel California")]);')
    lc, auto = attribute_of(run(conn, cfg, tmp_path, script), "data-drawers")
    assert lc["said"] == "2 versions caracole met"
    assert [(r["ver"], r["note"], r["acts"], r["open"]) for r in lc["rows"]] == [
        ("Version 1", "90% of the lyrics", ["Its page ↗"], LACUERDA[0]),
        ("Version 2", "60% of the lyrics", ["Its page ↗"], LACUERDA[1])]  # the sheet is UG's: In use on none
    assert auto["what"] == "Auto sheet · from the recording"
    [row] = auto["rows"]
    assert row["open"] == HOTEL + "sheet%20%28auto%29.html" and row["note"] == "PDF · Text · ChordPro"


def test_a_files_chip_lists_that_sources_files(conn, cfg, tmp_path):
    hotel(conn, cfg)
    script = 'chipOf("Hotel California", "inbox", "guitar").click();\nnote("drawer", noteDrawer("Hotel California"));'
    drawer = attribute_of(run(conn, cfg, tmp_path, script, controls=SERVED), "data-drawer")
    assert (drawer["what"], drawer["said"]) == ("your inbox · Guitar Pro files", "1 file")
    [row] = drawer["rows"]
    assert row["ver"] == "Guitar Pro 2" and row["acts"] == ["Open", "Download"]
    assert row["open"].startswith("guitar?file=")


def test_escape_closes_the_drawer_and_gives_the_focus_back_to_its_chip(conn, cfg, tmp_path):
    # UG's drawer opened, the focus on its first Open: Escape closes it, the focus back on its chip; so does its ✕.
    hotel(conn, cfg)
    path = write_library_page(cfg.library_dir, with_script(page(conn, cfg),
                                                           "(() => {\n" + KIT + "\nwindow.openCard = openCard;\n})();"))
    try:
        browser = Browser(tmp_path / "chrome")
    except BrowserError as e:
        pytest.skip(f"chromium couldn't run: {e}")
    with browser:
        browser.open(path.as_uri())
        browser.js('openCard("Hotel California")')
        browser.click('.tile-sheet button.vchip[data-source="ug"]')
        assert browser.wait("!document.querySelector('.drawer').hidden")
        browser.js("document.querySelector('.drawer a.go').focus()")
        browser.press("Escape")
        assert browser.wait("document.querySelector('.drawer').hidden")
        assert browser.js("document.activeElement.dataset.source") == "ug"
        assert browser.js("document.activeElement.getAttribute('aria-expanded')") == "false"
        browser.click('.tile-sheet button.vchip[data-source="ug"]')
        browser.click(".drawer .drawer-close")
        assert browser.wait("document.querySelector('.drawer').hidden")
        assert browser.js("document.activeElement.dataset.source") == "ug"


# Notes every fetch the page makes and every resource it loads while each chip opens and closes its drawer.
QUIET = """
const asked = [];
const real = window.fetch;
window.fetch = (...args) => { asked.push(String(args[0])); return real(...args); };
const loaded = performance.getEntriesByType("resource").length;
openCard("Hotel California");
for (const chip of lineOf("Hotel California").querySelectorAll("button.vchip")) { chip.click(); chip.click(); }
note("quiet", { asked, loaded: performance.getEntriesByType("resource").length - loaded,
  chips: lineOf("Hotel California").querySelectorAll("button.vchip").length });
"""


def test_opening_a_drawer_sends_no_request(conn, cfg, tmp_path):
    hotel(conn, cfg)
    quiet = attribute_of(run(conn, cfg, tmp_path, QUIET, controls=SERVED), "data-quiet")
    assert quiet == {"asked": [], "loaded": 0, "chips": 5}, quiet


# --- what a card shows of a song with no sheet, a text tab, a score, links elsewhere ---------------------------


def test_a_song_with_no_sheet_has_no_tiles_but_its_notes_and_links(conn, cfg, tmp_path):
    lost = add_song(conn, "The Beatles", "Yesterday")
    update_song(conn, lost.id, match_decision="not_found")
    script = 'note("card", noteCard("Yesterday"));\nnote("action", text(lineOf("Yesterday").querySelector(".line-action")));'
    dom = run(conn, cfg, tmp_path, script, controls=WebControls(csrf="tok"))
    card = attribute_of(dom, "data-card")
    assert card["tiles"] == [] and "tiles" not in card["parts"]
    assert card["parts"] == ["facts", "actions", "find-elsewhere", "foot"], card["parts"]  # Look in the index; links
    assert attribute_of(dom, "data-action") == "Fetch now"


def test_musescore_links_show_beside_a_sheet_too(conn, cfg, tmp_path):
    from caracole.musescore import parse_song_url

    hotel(conn, cfg)
    conn.execute("INSERT INTO musescore_index VALUES (?, ?, ?, '18')",
                 parse_song_url("https://musescore.com/song/hotel_california-1234"))
    script = ('note("card", noteCard("Hotel California"));\n'
              'note("elsewhere", text(lineOf("Hotel California").querySelector(".find-elsewhere")));')
    dom = run(conn, cfg, tmp_path, script)
    assert attribute_of(dom, "data-card")["parts"] == ["facts", "tiles", "find-elsewhere", "foot"]
    elsewhere = attribute_of(dom, "data-elsewhere")
    assert elsewhere.startswith("Find it elsewhereScores on MuseScore") and "hotel_california-1234" in elsewhere


def test_a_text_tab_alone_is_a_guitar_tab_tile(conn, cfg, tmp_path):
    creep = add_song(conn, "Radiohead", "Creep")
    tab = upsert_version(conn, provider="ug", tab_id="9", song_id=creep.id, slot="guitar", kind="tabs", rating=4.5,
                         votes=3, version=1, label=None, url="https://tabs.ultimate-guitar.com/tab/9", raw={}, now="x")
    keep_file(conn, cfg.library_dir, song=creep, version_id=tab, name="tab.txt", data=b"e|--0--|", rank=1)
    put(cfg, creep, "sheet.pdf")
    update_song(conn, creep.id, status="found")
    tiles = attribute_of(run(conn, cfg, tmp_path, 'note("card", noteCard("Creep"));'), "data-card")["tiles"]
    guitar = tiles[1]
    assert (guitar["name"], guitar["href"], guitar["said"]) == (
        "Guitar tab", "Radiohead/Creep/tab.txt", "Open the guitar tab of Creep")
    assert guitar["lead"] == "From" and [c["source"] for c in guitar["chips"]] == ["ug"]
    assert [d["text"] for d in guitar["downloads"]] == ["Text"]


def test_a_score_you_filed_is_a_tile(conn, cfg, tmp_path):
    song = add_song(conn, "Eagles", "Desperado")
    put(cfg, song, "sheet.pdf", "score-1.pdf", "score-1.mxl", "score-2.pdf")
    update_song(conn, song.id, status="found")
    tiles = attribute_of(run(conn, cfg, tmp_path, 'note("card", noteCard("Desperado"));'), "data-card")["tiles"]
    score = tiles[1]
    # It opens the first, in inbox.py's order of formats: MusicXML, a download; a PDF the browser shows opens.
    assert (score["name"], score["href"], score["said"]) == ("Score", "Eagles/Desperado/score-1.mxl",
                                                            "Download the score of Desperado")
    assert score["download"] == "Eagles - Desperado.mxl"
    assert [d["text"] for d in score["downloads"]] == ["MusicXML", "PDF", "PDF"]
    assert "stack" in score["cls"].split()


def test_an_auto_sheet_alone_is_its_own_tile_in_its_colour(conn, cfg, tmp_path):
    zebra = add_song(conn, "宋冬野", "斑马，斑马")
    put(cfg, zebra, "sheet (auto).html", "sheet (auto).pdf", "sheet (auto).txt")
    update_song(conn, zebra.id, status="found")
    [tile] = attribute_of(run(conn, cfg, tmp_path, 'note("card", noteCard("斑马，斑马"));'), "data-card")["tiles"]
    assert tile["name"] == "Auto sheet" and tile["from"] == "from the recording"
    assert "auto" in tile["cls"].split() and "primary" not in tile["cls"].split()
    assert [d["text"] for d in tile["downloads"]] == ["PDF", "Text"]
    assert tile["lead"] == "From" and [c["source"] for c in tile["chips"]] == ["auto"]


# --- the foot -------------------------------------------------------------------------------------------------

REMOVE = """
const card = noteCard("Hotel California");
const go = lineOf("Hotel California").querySelector(".foot form.remove button");
const style = getComputedStyle(go);
const failed = getComputedStyle(document.documentElement).getPropertyValue("--failed").trim();
const probe = document.createElement("span");
probe.style.color = failed;
document.body.appendChild(probe);
note("remove", { foot: card.foot, said: go.getAttribute("aria-label"), color: style.color,
  failed: getComputedStyle(probe).color, background: style.backgroundColor, border: style.borderTopColor,
  last: lineOf("Hotel California").querySelector(".foot").lastElementChild.className });
"""


def test_remove_says_remove_and_is_red_and_last(conn, cfg, tmp_path):
    put(cfg, hotel(conn, cfg), "info.json")
    remove = attribute_of(run(conn, cfg, tmp_path, REMOVE, controls=SERVED), "data-remove")
    assert remove["foot"] == ["Fetch again", "Use LaCuerda's sheet", "Add to a songbook…", "info.json", "Remove"]
    assert remove["last"].split()[0] == "remove"
    assert remove["said"] == "Remove Hotel California by Eagles from caracole"
    # Red from the start, its words and edge, yet outlined: never filled, never the main thing to do.
    assert remove["color"] == remove["failed"] and remove["background"] == "rgba(0, 0, 0, 0)"
    assert remove["border"] != remove["color"]


def test_the_file_page_offers_no_change_but_the_command_that_fetches_versions(conn, cfg, tmp_path):
    hotel(conn, cfg)
    script = ('chipOf("Hotel California", "ug").click();\nnote("card", noteCard("Hotel California"));\n'
              'note("drawer", noteDrawer("Hotel California"));\n'
              'note("forms", lineOf("Hotel California").querySelectorAll("form").length);')
    dom = run(conn, cfg, tmp_path, script)
    card, drawer = attribute_of(dom, "data-card"), attribute_of(dom, "data-drawer")
    assert card["foot"] == ["Add to a songbook…"]  # no Fetch again, no Remove
    assert attribute_of(dom, "data-forms") == 0
    assert all("Use this one" not in r["acts"] for r in drawer["rows"]) and drawer["restButtons"] == []
    assert drawer["command"].startswith("caracole versions --keep-more ")


PROGS = """
const line = openCard("Synthetic Song");
const chips = Array.from(line.querySelectorAll(".progressions .prog"));
const before = { label: text(line.querySelector(".progressions .card-label").firstChild),
  em: text(line.querySelector(".progressions .card-label em")),
  chips: chips.map((c) => [text(c), c.getAttribute("aria-label"), !!c.querySelector("svg.glyph-search")]) };
chips[0].click();
note("progs", { before, hash: location.hash,
  titles: Array.from(document.querySelectorAll("#list .line h3")).map((h) => h.textContent).sort() });
"""


def test_progressions_are_search_chips_that_filter(conn, cfg, tmp_path):
    from test_library_page import progression_library

    progression_library(conn, cfg)
    progs = attribute_of(run(conn, cfg, tmp_path, PROGS), "data-progs")
    assert (progs["before"]["label"], progs["before"]["em"]) == ("Progressions", "find your songs that play one")
    assert progs["before"]["chips"][0][0] == "vi–IV–I–V" and progs["before"]["chips"][0][2] is True
    assert progs["before"]["chips"][0][1].startswith("Your songs with I–V–vi–IV")
    assert "prog=I+V+vi+IV" in progs["hash"] and progs["titles"] == ["In A Minor", "Synthetic Song"]


# --- its layout: 390 px and a desktop, the drawer under its tile's row ----------------------------------------

LAYOUT = """
const line = openCard("Hotel California");
const tiles = Array.from(line.querySelectorAll(".tiles > .tile"));
const box = (n) => { const b = n.getBoundingClientRect(); return [Math.round(b.left), Math.round(b.right),
  Math.round(b.top), Math.round(b.bottom)]; };
const at = (kind) => {
  chipOf("Hotel California", kind === "guitar" ? "gtptabs" : "ug", kind).click();
  const drawer = line.querySelector(".drawer");
  const point = parseFloat(drawer.style.getPropertyValue("--point")) + line.querySelector(".tiles").getBoundingClientRect().left;
  return { after: drawer.previousElementSibling.className, drawer: box(drawer), point,
    tile: box(line.querySelector(".tile-" + kind)), last: box(tiles[tiles.length - 1]) };
};
note("layout", { sheet: at("sheet"), guitar: at("guitar"), tiles: tiles.map(box),
  wide: [document.documentElement.scrollWidth, innerWidth] });
"""


@pytest.mark.parametrize("size", ["390,844", "1280,900"])
def test_the_card_fits_with_the_drawer_under_its_tile(conn, cfg, tmp_path, size):
    hotel(conn, cfg)
    layout = attribute_of(run(conn, cfg, tmp_path, LAYOUT, size=size, controls=SERVED), "data-layout")
    wide, width = layout["wide"]
    assert wide <= width, layout
    for kind in ("sheet", "guitar"):
        at = layout[kind]
        left, right, _, bottom = at["tile"]
        assert left <= at["point"] <= right, (kind, at)  # its pointer over its tile
        assert at["drawer"][2] >= bottom, (kind, at)  # under it
    if size == "390,844":  # one tile a row: right under its own
        assert len({t[0] for t in layout["tiles"]}) == 1
        assert layout["sheet"]["after"].startswith("tile tile-sheet")
        assert layout["guitar"]["after"].startswith("tile tile-guitar")
    else:  # four a row, the drawer under the row: after its last tile, the score's row under the drawer
        assert [t[2] for t in layout["tiles"]].count(layout["tiles"][0][2]) == 4, layout["tiles"]
        assert layout["sheet"]["after"].startswith("tile tile-lyrics")
        assert layout["guitar"]["after"].startswith("tile tile-lyrics")
        assert layout["tiles"][4][2] >= layout["guitar"]["drawer"][3], layout


def test_a_drawer_left_open_in_a_folded_card_is_placed_again_when_the_card_opens_after_a_resize(conn, cfg, tmp_path):
    # Folded, the card's tiles measure nothing: a resize then (a phone turned) waits for the card to open again.
    import tempfile
    from pathlib import Path

    hotel(conn, cfg)
    html = build_library_page(conn, cfg, Overrides(), NOW, controls=SERVED)
    path = write_library_page(cfg.library_dir, with_script(html, "(() => {\n" + KIT +
                                                           "\nwindow.kit = { openCard, chipOf, lineOf };\n})();"))
    after = "kit.lineOf('Hotel California').querySelector('.drawer').previousElementSibling.className"
    with Browser(Path(tempfile.mkdtemp(prefix="profile-", dir=tmp_path)), width=1280, height=900) as b:
        b.open(path.as_uri())
        assert b.wait("!!window.kit && !!document.querySelector('#list .line-more')", 15)
        b.js("kit.openCard('Hotel California'); kit.chipOf('Hotel California', 'gtptabs', 'guitar').click()")
        assert b.js(after).startswith("tile tile-lyrics")  # four a row: under the row
        b.js("kit.lineOf('Hotel California').querySelector('.line-more').click()")  # folded, its drawer left open
        b.js("window.resized = 0; addEventListener('resize', () => { window.resized += 1; })")  # after the page's own
        b.send("Emulation.setDeviceMetricsOverride", width=390, height=844, deviceScaleFactor=1, mobile=False)
        assert b.wait("innerWidth === 390 && window.resized > 0")  # the page heard it while the card was folded
        b.js("kit.openCard('Hotel California')")
        assert b.wait(f"{after}.startsWith('tile tile-guitar')"), b.js(after)  # one a row: right under its own


@pytest.mark.parametrize("size", ["390,844", "1280,900"])
def test_the_card_meets_touch_targets_with_a_drawer_open(conn, cfg, tmp_path, size):
    from helpers.targets import noted, noting, small_targets

    hotel(conn, cfg)
    script = 'openCard("Hotel California");\nchipOf("Hotel California", "ug").click();\n' + noting(
        "data-short", small_targets())
    dom = run(conn, cfg, tmp_path, script, size=size, controls=SERVED, touch=True)
    assert noted(dom, "data-short") == []


# The contrast of each text the card shows against the first solid background under it, in its theme.
READS = """
openCard("Hotel California");
chipOf("Hotel California", "ug").click();
const rgb = (t) => (/^rgba?\\(([\\d.]+),\\s*([\\d.]+),\\s*([\\d.]+)(?:,\\s*([\\d.]+))?\\)$/.exec(t) || []).slice(1).map(Number);
const lum = (c) => { const f = (v) => (v / 255 <= 0.04045 ? v / 255 / 12.92 : ((v / 255 + 0.055) / 1.055) ** 2.4);
  return 0.2126 * f(c[0]) + 0.7152 * f(c[1]) + 0.0722 * f(c[2]); };
const behind = (n) => { for (let at = n; at; at = at.parentElement) { const c = rgb(getComputedStyle(at).backgroundColor);
  if (c.length && !(c[3] < 1)) return c; } return [255, 255, 255]; };
const ratio = (n) => { const [hi, lo] = [lum(rgb(getComputedStyle(n).color)), lum(behind(n))].sort((a, b) => b - a);
  return Math.round((hi + 0.05) / (lo + 0.05) * 100) / 100; };
const reads = {};
for (const sel of [".tile-name", ".tile-from", ".tile-versions .lead", ".vchip .n", ".dl", ".drawer-said", ".vrow .ver",
  ".vrow .stars", ".vrow .note", ".inuse", ".drawer-rest", ".card-label", ".facts", ".btn.remove", ".tile.primary .tile-name"]) {
  const n = lineOf("Hotel California").querySelector(sel);
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


# --- served: a line drawn again ---------------------------------------------------------------------------------


def test_a_line_drawn_again_keeps_its_card_open_and_its_drawer_closed(conn, cfg, live, browser):
    # Fetch again pressed in its foot, a drawer open: once the lookup is over, the song's line is drawn again from
    # what the library has now, its card still open, its drawer closed.
    base, posted = live
    song = hotel(conn, cfg)
    item = f'article.line[data-id="{song.id}"]'
    browser.open(base)
    browser.click(item + " .line-more")
    browser.click(item + ' .tile-sheet button.vchip[data-source="ug"]')
    assert browser.wait(f"!document.querySelector('{item} .drawer').hidden")
    browser.js(f"[...document.querySelectorAll('{item} .foot button')].find((b) => b.textContent === 'Fetch again')"
               ".click()")
    posted.next(0)
    assert browser.wait(f"document.querySelector('{item} .progress')?.dataset.tone === 'ready'", timeout=20)
    assert browser.js(f"document.querySelector('{item} .line-more').getAttribute('aria-expanded')") == "true"
    assert browser.js(f"document.querySelector('{item} .line-panel').hidden") is False
    assert browser.js(f"document.querySelector('{item} .drawer').hidden") is True
    assert browser.js(f"[...document.querySelectorAll('{item} button.vchip')].map((c) => "
                      "c.getAttribute('aria-expanded'))") == ["false"] * 5


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


def drawer_of(browser, song, source):
    """The song's card opened, and its chip of ``source`` on its sheet tile, its drawer then shown; its line's
    selector."""
    item = f'article.line[data-id="{song.id}"]'
    browser.click(item + " .line-more")
    browser.click(item + f' .tile-sheet button.vchip[data-source="{source}"]')
    assert browser.wait(f"!document.querySelector('{item} .drawer').hidden")
    return item


def press(browser, item, words, where=".drawer"):
    """The button of the song's ``where`` that says ``words``, pressed as a hand would."""
    found = (f"[...document.querySelectorAll('{item} {where} button')].find((b) => b.textContent === "
             f"{json.dumps(words)})")
    assert browser.wait(f"!!({found})"), browser.js(f"[...document.querySelectorAll('{item} {where} button')]"
                                                   ".map((b) => b.textContent)")
    browser.js(f"({found}).dataset.pressMe = '1'")
    browser.click(f"{item} {where} button[data-press-me]")


def test_use_this_one_posts_choose_with_the_tab(conn, cfg, versions_served, browser):
    base, posts, _ = versions_served
    song = hotel(conn, cfg)
    browser.open(base)
    item = drawer_of(browser, song, "ug")
    assert browser.js(f"[...document.querySelectorAll('{item} .vrow')].map((r) => [...r.querySelectorAll("
                      "'.vbtns button, .vbtns .inuse')].map((b) => b.textContent))") == [
        ["In use"], ["Use this one"], ["Use this one"]]
    press(browser, item, "Use this one")
    assert posts.next(0) == ("/versions/choose", {"csrf": "tok", "song": str(song.id), "tab": "46191"})
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
    item = drawer_of(browser, song, "ug")
    rest = f"document.querySelector('{item} .drawer-rest')"
    assert browser.js(f"{rest}.querySelector('.rest-said').textContent") == "10 more on Ultimate Guitar, not kept"
    assert browser.js(f"{rest}.querySelector('button').getAttribute('aria-label')") == (
        "Fetch 6 more versions of Hotel California from Ultimate Guitar")
    other = drawer_of(browser, few, "ug")
    assert browser.js(f"[...document.querySelectorAll('{other} .drawer-rest button')].map((b) => b.textContent)") == [
        "Fetch them"]
    press(browser, item, "Fetch 6 more")
    assert posts.next(0) == ("/versions/keep-more", {"csrf": "tok", "song": str(song.id)})


def test_after_keep_more_the_drawer_counts_again_from_the_jobs_view(conn, cfg, versions_served, browser):
    base, posts, runner = versions_served
    song = hotel(conn, cfg)
    browser.open(base)
    item = drawer_of(browser, song, "ug")
    press(browser, item, "Fetch 6 more")
    posts.next(0)
    # Once its job is over, the line is drawn again from what the library has: two more kept, eight left.
    assert browser.wait(f"document.querySelector('{item} .progress')?.dataset.tone === 'ready'", timeout=20)
    assert runner.ran == [("versions", "--keep-more", "--progress", "--", "Eagles", "Hotel California")]
    assert browser.js(f"document.querySelector('{item} .drawer').hidden") is True  # closed, as it was drawn again
    browser.click(item + ' .tile-sheet button.vchip[data-source="ug"]')
    assert browser.wait(f"!document.querySelector('{item} .drawer').hidden")
    assert browser.js(f"document.querySelector('{item} .drawer-said').textContent") == (
        "13 versions on the site · 5 kept in your library")
    assert browser.js(f"document.querySelector('{item} .drawer-rest .rest-said').textContent") == (
        "8 more on Ultimate Guitar, not kept")
    assert browser.js(f"document.querySelectorAll('{item} .vrow').length") == 5


def test_back_to_caracoles_pick_only_when_pinned(conn, cfg, versions_served, browser):
    from caracole.overrides import add_pin

    base, posts, _ = versions_served
    song = hotel(conn, cfg)
    browser.open(base)
    item = drawer_of(browser, song, "ug")
    assert browser.js(f"document.querySelector('{item} .drawer-head').textContent").count("Back") == 0
    add_pin(cfg.overrides_file, song.display, ["https://tabs.ultimate-guitar.com/tab/eagles/hotel-california-chords-46191"])
    browser.open(base)
    item = drawer_of(browser, song, "ug")
    press(browser, item, "Back to caracole's pick", ".drawer-head")
    assert posts.next(0) == ("/versions/clear", {"csrf": "tok", "song": str(song.id)})


def test_lacuerda_use_this_one_posts_the_lookup_with_its_page(conn, cfg, versions_served, browser):
    base, posts, _ = versions_served
    song = hotel(conn, cfg)
    browser.open(base)
    item = drawer_of(browser, song, "lacuerda")
    press(browser, item, "Use this one")
    assert posts.next(0) == ("/lookup", {"csrf": "tok", "song": str(song.id), "lacuerda": LACUERDA[0]})


def test_lacuerda_use_this_one_waits_for_a_pin_to_go(conn, cfg, versions_served, browser):
    # A UG version chosen (a [pin]) outranks a LaCuerda pick: its Use this one would do nothing until the pin goes.
    from caracole.overrides import add_pin

    base, posts, _ = versions_served
    song = hotel(conn, cfg)
    add_pin(cfg.overrides_file, song.display, ["https://tabs.ultimate-guitar.com/tab/eagles/hotel-california-chords-46191"])
    browser.open(base)
    item = drawer_of(browser, song, "lacuerda")
    buttons = f"[...document.querySelectorAll('{item} .drawer button')].map((b) => b.textContent)"
    assert "Use this one" not in browser.js(buttons)
    assert browser.js(f"document.querySelector('{item} .drawer .pin-note').textContent") == (
        "Your choice on Ultimate Guitar is in use: Back to caracole's pick first.")
    press(browser, item, "Back to caracole's pick")
    assert posts.next(0) == ("/versions/clear", {"csrf": "tok", "song": str(song.id)})
