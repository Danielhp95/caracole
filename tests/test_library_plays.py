"""A song of yours' line on the library page (card.js ``plays``, rows.js, library.js, rows.css), in a real browser: a
button for each thing it holds to play from, right after its title, none of them first, each opening it at once and
carrying the marks of the sites its versions came from; the title opens the card, as the chevron does; a wanted
song's Fetch now is the download glyph on the same row; one row on a phone and on a desktop, Needs review under it.

The tests add a script after the page's own (test_library_card's ``KIT`` and ``run``), which notes what the lines
show into an attribute of the body, read back from the DOM once the page ran.
"""

from __future__ import annotations

import pytest
from helpers.browser import CHROMIUM_MARKS
from helpers.library_songs import hotel_california, with_versions
from test_library_card import HOTEL, SERVED, run
from test_library_page import attribute_of, put

from caracole.library import keep_file
from caracole.library_page import WebControls
from caracole.songs import update_song
from caracole.versions import upsert_version

from conftest import add_song

pytestmark = CHROMIUM_MARKS  # every test here opens the page in Chromium

# A line's buttons, each as it is drawn and named.
PLAYS = r"""
const playsOf = (title) => Array.from(lineOf(title).querySelectorAll(":scope > .line-title > .line-plays > *"))
  .map((a) => ({ tag: a.tagName.toLowerCase(), kind: a.dataset.kind, inst: a.dataset.inst, cls: a.className,
    href: a.getAttribute("href"), download: a.getAttribute("download"), said: a.getAttribute("aria-label"),
    title: a.title, glyph: a.querySelector("svg.glyph").getAttribute("class"),
    n: a.querySelector(".n") ? a.querySelector(".n").textContent : null,
    hidden: Array.from(a.querySelectorAll(".n, .marks")).every((x) => x.getAttribute("aria-hidden") === "true"),
    marks: Array.from(a.querySelectorAll(".marks > [data-source]")).map((m) => m.dataset.source) }));
"""


def plays(conn, cfg, tmp_path, title, **how):
    return attribute_of(run(conn, cfg, tmp_path, PLAYS + f'note("plays", playsOf({title!r}));', **how), "data-plays")


def harmonica_song(conn, cfg):
    """Eagles - Take It Easy: a chord sheet from Ultimate Guitar and a harmonica tab of harptabs.com, with its page."""
    song = add_song(conn, "Eagles", "Take It Easy")
    harp = upsert_version(conn, provider="harptabs", tab_id="77", song_id=song.id, slot="guitar", kind="harmonica",
                          rating=0, votes=0, version=1, label=None, url="https://www.harptabs.com/song.php?ID=77",
                          raw={}, now="2026-10-19T00:00:00Z")
    keep_file(conn, cfg.library_dir, song=song, version_id=harp, name="harmonica-1.txt", data=b"4 -4 5\n", rank=1)
    ug = upsert_version(conn, provider="ug", tab_id="5", song_id=song.id, slot="sheet", kind="chords", rating=4.5,
                        votes=10, version=1, label=None, url="https://tabs.ultimate-guitar.com/tab/x-chords-5",
                        raw={"tonality_name": "G"}, now="2026-10-19T00:00:00Z")
    keep_file(conn, cfg.library_dir, song=song, version_id=ug, name="sheet.json",
              data=b'{"content": "[ch]G[/ch]\\nx"}', rank=1)
    keep_file(conn, cfg.library_dir, song=song, version_id=ug, name="sheet.txt", data=b"[ch]G[/ch]\nx", rank=1)
    put(cfg, song, "sheet.html", "harmonica-1.html")
    update_song(conn, song.id, status="found")
    return song


# --- a button for each thing to play from ------------------------------------------------------------------------


def test_a_line_has_a_button_for_each_thing_it_holds_to_play_from_none_first(conn, cfg, tmp_path):
    song = hotel_california(conn, cfg)
    with_versions(conn, cfg, song)
    shown = plays(conn, cfg, tmp_path, "Hotel California")
    # The card's order: its sheet, its Guitar Pro files, its text tab, its harmonica tab, its score; its lyrics have
    # none (their site's mark stays in the card). Each a link that opens it at once, as its tile does.
    assert [p["kind"] for p in shown] == ["sheet", "guitar", "tab", "harmonica", "score"], shown
    assert {p["tag"] for p in shown} == {"a"}
    assert [p["href"] for p in shown] == [HOTEL + "sheet.html", HOTEL + "guitar-1.gp5", HOTEL + "tab.txt",
                                          HOTEL + "harmonica-1.txt", HOTEL + "score-1.mxl"]
    # From the file, a Guitar Pro file and a MusicXML score download under the song's name.
    assert [p["download"] for p in shown] == [None, "Eagles - Hotel California.gp5", None, None,
                                              "Eagles - Hotel California.mxl"]
    # Named for what it opens, where its versions came from, and how many the card lists.
    assert [p["said"] for p in shown] == [
        "Open the chord sheet of Hotel California, from UG, LaCuerda and the audio (auto-chords), "
        "6 versions",
        "Download the Guitar Pro file of Hotel California, from gtptabs and your inbox, 2 files",
        "Open the guitar tab of Hotel California",
        "Open the harmonica tab of Hotel California, from harptabs",
        "Download the score of Hotel California, from your inbox"]
    assert all(p["title"] == p["said"] for p in shown)  # the pointer's tooltip says it too
    # Its instrument's glyph; the sites' marks at its foot, two at most, the one in use first; its count when more
    # than one; neither heard twice.
    assert [p["glyph"] for p in shown] == ["glyph glyph-sheet", "glyph glyph-guitar", "glyph glyph-guitar",
                                           "glyph glyph-harmonica", "glyph glyph-score"]
    assert [p["marks"] for p in shown] == [["ug", "lacuerda"], ["gtptabs", "inbox"], [], ["harptabs"], ["inbox"]]
    assert [p["n"] for p in shown] == ["6", "2", None, None, None]
    assert all(p["hidden"] for p in shown)
    # Which of the Filter panel's instruments each is one of; none is a primary or the line's main button.
    assert [p["inst"] for p in shown] == ["sheet", "guitar", "guitar", "harmonica", "score"]
    assert not any("primary" in p["cls"].split() for p in shown)


def test_the_line_has_no_open_and_its_title_no_link_nor_its_sites_marks(conn, cfg, tmp_path):
    hotel_california(conn, cfg)
    script = """
    const line = lineOf("Hotel California");
    note("line", { action: line.querySelector(".line-action").childElementCount,
      titleLink: line.querySelector(":scope > a.line-title, :scope > .line-title a.title-link") !== null,
      sitesOnLine: line.querySelector(":scope > .line-meta .line-sites") !== null,
      sitesInCard: line.querySelector(":scope > .line-panel .card-sites .line-sites") !== null,
      holds: line.querySelector(".line-holds") !== null });
    """
    shown = attribute_of(run(conn, cfg, tmp_path, script, controls=WebControls(csrf="tok")), "data-line")
    # Served too: no Open on its line, a title that is no link, which sites have it in its card alone.
    assert shown == {"action": 0, "titleLink": False, "sitesOnLine": False, "sitesInCard": True, "holds": False}


def test_served_the_guitar_pro_button_opens_its_page_and_a_harmonica_tab_its_own(conn, cfg, tmp_path):
    hotel_california(conn, cfg)
    harmonica_song(conn, cfg)
    guitar = plays(conn, cfg, tmp_path, "Hotel California", controls=SERVED)[1]
    assert guitar["href"].startswith("guitar?file=") and guitar["download"] is None
    assert guitar["said"] == "Open the Guitar Pro tab of Hotel California, from gtptabs and your inbox, 2 files"
    shown = plays(conn, cfg, tmp_path, "Take It Easy")
    assert [(p["kind"], p["href"], p["marks"]) for p in shown] == [
        ("sheet", "Eagles/Take%20It%20Easy/sheet.html", ["ug"]),
        ("harmonica", "Eagles/Take%20It%20Easy/harmonica-1.html", ["harptabs"])]
    assert shown[1]["said"] == "Open the harmonica tab of Take It Easy, from harptabs"


def test_an_auto_sheet_is_a_button_in_its_colour_and_ukulele_chords_the_ukuleles(conn, cfg, tmp_path):
    zebra = add_song(conn, "宋冬野", "斑马，斑马")
    put(cfg, zebra, "sheet (auto).html", "sheet (auto).pdf", "sheet (auto).txt")
    update_song(conn, zebra.id, status="found")
    [auto] = plays(conn, cfg, tmp_path, "斑马，斑马")
    assert auto["kind"] == "sheet" and "auto" in auto["cls"].split()
    assert auto["said"].startswith("Open the auto sheet of 斑马，斑马")
    uke = add_song(conn, "Israel Kamakawiwoʻole", "Over the Rainbow")
    v = upsert_version(conn, provider="ug", tab_id="8", song_id=uke.id, slot="sheet", kind="ukulele", rating=4.8,
                       votes=50, version=1, label=None, url="https://tabs.ultimate-guitar.com/tab/x-ukulele-8",
                       raw={}, now="2026-10-19T00:00:00Z")
    keep_file(conn, cfg.library_dir, song=uke, version_id=v, name="sheet.txt", data=b"[ch]C[/ch]\nx", rank=1)
    update_song(conn, uke.id, status="found")
    [ukulele] = plays(conn, cfg, tmp_path, "Over the Rainbow")
    assert ukulele["glyph"] == "glyph glyph-ukulele" and ukulele["inst"] == "sheet ukulele"
    assert ukulele["said"] == "Open the ukulele chords of Over the Rainbow, from UG"


def test_game_music_tabs_are_a_button_and_a_song_with_nothing_has_none(conn, cfg, tmp_path):
    song = add_song(conn, "Hollow Knight", "Resting Grounds")
    for n in (1, 2):
        v = upsert_version(conn, provider="gametabs", tab_id=f"tabs/hk/rg-{n}", song_id=song.id, slot="guitar",
                           kind="gametab", rating=5.0, votes=10, version=1, label=None,
                           url=f"https://gametabs.net/tabs/hk/rg-{n}", raw={}, now="2026-10-28T03:30:00Z")
        keep_file(conn, cfg.library_dir, song=song, version_id=v, name=f"gametab-{n}.txt", data=f"e|--{n}--|".encode(), rank=n)
    update_song(conn, song.id, status="found")
    add_song(conn, "The Beatles", "Yesterday")
    script = PLAYS + """
    note("plays", { game: playsOf("Resting Grounds"),
      none: lineOf("Yesterday").querySelector(".line-plays") === null });
    """
    shown = attribute_of(run(conn, cfg, tmp_path, script), "data-plays")
    [game] = shown["game"]
    assert (game["kind"], game["inst"], game["marks"], game["n"]) == ("gametab", "guitar", ["gametabs"], "2")
    assert game["said"] == "Open the game music tab of Resting Grounds, from gametabs, 2 tabs"
    assert shown["none"]


# --- the title opens the card; a button opens its file --------------------------------------------------------


def test_the_title_opens_the_card_as_the_chevron_does_and_a_button_never_does(conn, cfg, tmp_path):
    hotel_california(conn, cfg)
    script = """
    const line = lineOf("Hotel California");
    const more = line.querySelector(":scope > .line-more");
    const state = () => ({ expanded: more.getAttribute("aria-expanded"),
      shown: !line.querySelector(":scope > .line-panel").hidden });
    const play = line.querySelector(".line-plays a");
    play.addEventListener("click", (e) => e.preventDefault());  // the test stays on the page
    play.click();
    const afterPlay = state();
    line.querySelector(".line-title h3").click();
    const opened = state();
    line.querySelector(".line-title h3").click();
    note("title", { afterPlay, opened, closed: state(),
      cursor: getComputedStyle(line.querySelector(".line-title")).cursor });
    """
    shown = attribute_of(run(conn, cfg, tmp_path, script), "data-title")
    assert shown["afterPlay"] == {"expanded": "false", "shown": False}
    assert shown["opened"] == {"expanded": "true", "shown": True}
    assert shown["closed"] == {"expanded": "false", "shown": False}
    assert shown["cursor"] == "pointer"


# --- Fetch now: the download glyph ------------------------------------------------------------------------------


def test_fetch_now_is_the_download_glyph_on_the_same_row(conn, cfg, tmp_path):
    add_song(conn, "Radiohead", "Creep")
    hotel_california(conn, cfg)
    script = """
    const go = lineOf("Creep").querySelector(".line-action form.fetch button");
    note("fetch", { text: go.textContent, said: go.getAttribute("aria-label"), type: go.type, title: go.title,
      glyph: go.querySelector("svg.glyph").getAttribute("class"), action: go.form.getAttribute("action"),
      have: lineOf("Hotel California").querySelector(".line-action").childElementCount });
    """
    shown = attribute_of(run(conn, cfg, tmp_path, script, controls=WebControls(csrf="tok")), "data-fetch")
    assert shown == {"text": "", "said": "Fetch Creep by Radiohead", "type": "submit",
                     "title": "Fetch: ask UG for this song",
                     "glyph": "glyph glyph-download", "action": "/fetch", "have": 0}


def test_on_a_touch_screen_a_play_is_a_filled_tile_its_sites_letters_8px(conn, cfg, tmp_path):
    hotel_california(conn, cfg)
    script = PLAYS + """
    const look = (n) => { const s = getComputedStyle(n); return [s.borderTopStyle, s.backgroundColor !== "rgba(0, 0, 0, 0)"]; };
    note("tiles", { tiles: Array.from(lineOf("Hotel California").querySelectorAll(".line-plays > .play")).map(look),
      letters: Array.from(lineOf("Hotel California").querySelectorAll(".play .marks > .source")).map((m) =>
        [m.dataset.source, getComputedStyle(m).fontSize, Math.round(m.getBoundingClientRect().height)]) });"""
    drawn = attribute_of(run(conn, cfg, tmp_path, script, size="390,844", touch=True), "data-tiles")
    assert drawn["tiles"] == [["none", True]] * 5  # no outline; the fill keeps its shape
    # The sheet's UG, the Guitar Pro files' gtptabs and inbox, the harmonica tab's harptabs, the score's inbox (the
    # text tab has no site): letters, or the inbox's glyph, at 8 px on a mark 16 px tall.
    assert drawn["letters"] == [["ug", "8px", 16], ["gtptabs", "8px", 16], ["inbox", "8px", 16],
                                ["harptabs", "8px", 16], ["inbox", "8px", 16]], drawn


CHIPS = PLAYS + r"""
note("chips", Array.from(document.querySelectorAll("#list .line")).map((l) => [l.querySelector("h3").textContent,
  Array.from(l.querySelectorAll(".line-plays > .play")).map((a) => {
    const text = (n) => n.textContent;
    return { words: a.querySelector(".play-words").checkVisibility() ? text(a.querySelector(".play-words")) : null,
    n: a.querySelector(".n") && a.querySelector(".n").checkVisibility() ? text(a.querySelector(".n")) : null,
    marks: a.querySelector(".marks") ? a.querySelector(".marks").checkVisibility() : null,
    height: Math.round(a.getBoundingClientRect().height),
    hidden: a.querySelector(".play-words").getAttribute("aria-hidden") }; })]));
"""
WORDS = {"Hotel California": ["Chords · UG", "Guitar Pro · gtptabs", "Tab", "Harmonica · harptabs", "Score · inbox"],
         "Take It Easy": ["Chords · UG", "Harmonica · harptabs"], "斑马，斑马": ["Auto sheet"],
         "De Música Ligera": ["Chords · LaCuerda"]}


def chip_library(conn, cfg):
    """Hotel California with its versions (6 of its sheet, 2 Guitar Pro files), Take It Easy, an auto sheet alone
    and a LaCuerda sheet: nine buttons."""
    with_versions(conn, cfg, hotel_california(conn, cfg))
    harmonica_song(conn, cfg)
    zebra = add_song(conn, "宋冬野", "斑马，斑马")
    put(cfg, zebra, "sheet (auto).html", "sheet (auto).pdf")
    update_song(conn, zebra.id, status="found")
    soda = add_song(conn, "Soda Stereo", "De Música Ligera")  # a LaCuerda sheet
    lc = upsert_version(conn, provider="lacuerda", tab_id="soda_stereo/de_musica_ligera", song_id=soda.id,
                        slot="sheet", kind="acordes", rating=0, votes=0, version=1, label=None,
                        url="https://acordes.lacuerda.net/soda_stereo/de_musica_ligera.shtml", raw={}, now="x")
    keep_file(conn, cfg.library_dir, song=soda, version_id=lc, name="sheet.txt", data=b"[ch]Am[/ch]\nx", rank=1)
    put(cfg, soda, "sheet.html")
    update_song(conn, soda.id, status="found")


@pytest.mark.parametrize(("size", "touch"), [("1280,900", False), ("390,844", False), ("1280,900", True)])
def test_the_pointer_decides_chips_for_a_mouse_tiles_for_a_thumb_whatever_the_width(conn, cfg, tmp_path, size, touch):
    chip_library(conn, cfg)
    drawn = dict(attribute_of(run(conn, cfg, tmp_path, CHIPS, size=size, touch=touch), "data-chips"))
    for title, words in WORDS.items():
        shown = drawn[title]
        if touch:  # a tile: its icon, the sites' marks at its corner, no words
            assert all(p["words"] is None and p["marks"] is not False and p["height"] == 48 for p in shown), shown
        else:  # a chip of about 28 px: the kind and the site in words, its count after them, no marks
            assert [p["words"] for p in shown] == words, (title, shown)
            assert all(p["height"] == 28 and p["marks"] in (False, None) for p in shown), shown
        assert all(p["hidden"] == "true" for p in shown)  # its name is its aria-label, as before
    if not touch:
        assert [p["n"] for p in drawn["Hotel California"]] == ["6", "2", None, None, None]


def test_a_real_mouse_gets_the_chips(conn, cfg, tmp_path):
    from helpers.browser import FINE_POINTER, Browser
    from test_library_page import page

    from caracole.library_page import write_library_page

    chip_library(conn, cfg)
    path = write_library_page(cfg.library_dir, page(conn, cfg))
    with Browser(tmp_path / "chrome", args=FINE_POINTER) as b:
        b.open(path.as_uri())
        assert b.wait("document.querySelectorAll('#list .line-plays .play').length === 9")
        assert b.js("matchMedia('(pointer: fine)').matches") is True
        assert b.js("Array.from(document.querySelectorAll('#list .line-plays .play-words'))"
                    ".filter((w) => w.checkVisibility()).length") == 9


def test_a_chip_never_wraps_its_words_beside_a_long_title(conn, cfg, tmp_path):
    long = add_song(conn, "宋冬野", "斑马，斑马，你不要睡着啦，再给我看看你受伤的尾巴，我不想去触碰你伤口的疤")
    put(cfg, long, "sheet (auto).html", "sheet (auto).pdf")
    update_song(conn, long.id, status="found")
    script = PLAYS + """const l = document.querySelector("#list .line"), h3 = l.querySelector("h3");
    note("long", { cut: h3.scrollWidth > h3.clientWidth, chips: Array.from(l.querySelectorAll(".play"))
      .map((a) => Math.round(a.getBoundingClientRect().height)) });"""
    phone = attribute_of(run(conn, cfg, tmp_path, script, size="390,844"), "data-long")
    assert phone == {"cut": True, "chips": [28]}, phone  # the title cut short, the chip whole on one line
    assert attribute_of(run(conn, cfg, tmp_path, script, size="1280,900"), "data-long")["chips"] == [28]


# --- one row, on a phone and on a desktop ------------------------------------------------------------------------

# Each line's parts, where they are: its title's, its buttons' (with their marks and counts), its action's, its key's
# and its chevron's boxes, its status's, the line's own; and every button's target.
LAYOUT = PLAYS + r"""
const box = (n) => { const b = n.getBoundingClientRect(); return [b.left, b.right, b.top, b.bottom]; };
const laid = {};
for (const line of document.querySelectorAll("#list .line")) {
  const one = (sel) => { const n = line.querySelector(sel); return n && n.checkVisibility() ? box(n) : null; };
  laid[line.querySelector("h3").textContent] = { line: box(line), h3: one(":scope > .line-title h3"),
    key: one(":scope > .line-key"), more: one(":scope > .line-more"), action: one(":scope > .line-action > *"),
    status: one(":scope > .line-meta .line-status"),
    plays: Array.from(line.querySelectorAll(".line-plays > .play")).map((p) => ({ box: box(p),
      parts: Array.from(p.querySelectorAll(".n, .marks > *")).filter((n) => n.checkVisibility()).map(box) })) };
}
note("laid", { laid, page: [document.documentElement.scrollWidth, window.innerWidth] });
"""


@pytest.mark.parametrize(("size", "touch"), [("390,844", True), ("1280,900", False), ("820,1180", True), ("320,640", True)])
def test_a_line_is_one_row_its_buttons_whole_and_needs_review_under_it_on_a_phone(conn, cfg, tmp_path, size, touch):
    hotel_california(conn, cfg)
    harmonica_song(conn, cfg)
    review = add_song(conn, "Eagles", "Desperado")
    update_song(conn, review.id, review=True)  # Needs review, and Fetch now
    drawn = attribute_of(run(conn, cfg, tmp_path, LAYOUT, controls=WebControls(csrf="tok"), size=size, touch=touch),
                         "data-laid")
    wide, width = drawn["page"]
    assert wide <= width, drawn["page"]
    laid = drawn["laid"]
    phone = int(size.split(",")[0]) < 720

    def middle(b):
        return (b[2] + b[3]) / 2

    def same_row(a, b):
        return a[2] < middle(b) < a[3]

    easy = laid["Take It Easy"]
    assert len(easy["plays"]) == 2 and len(laid["Hotel California"]["plays"]) == 5, laid
    # One row: the title, its two buttons, the key and the chevron, side by side, in that order.
    row = [easy["h3"], *[p["box"] for p in easy["plays"]], easy["key"], easy["more"]]
    assert all(same_row(easy["more"], b) for b in row), easy
    assert all(a[1] <= b[0] + 0.5 for a, b in zip(row, row[1:], strict=False)), row
    # Every button's marks and count whole, inside the line, overlapping no other part of it.
    for title, line in laid.items():
        others = [b for b in (line["h3"], line["key"], line["more"], line["action"], line["status"]) if b]
        for p in line["plays"]:
            for part in [p["box"], *p["parts"]]:
                assert line["line"][0] - 0.5 <= part[0] and part[1] <= line["line"][1] + 0.5, (title, part)
                assert line["line"][2] - 0.5 <= part[2] and part[3] <= line["line"][3] + 0.5, (title, part)
                assert not any(a[0] < part[1] - 0.5 and part[0] < a[1] - 0.5 and a[2] < part[3] - 0.5
                               and part[2] < a[3] - 0.5 for a in others), (title, part, others)
            w, h = p["box"][1] - p["box"][0], p["box"][3] - p["box"][2]
            if not touch:  # a chip of 28 px, as wide as its words
                assert round(h) == 28 and round(w) >= 28, p
            if touch:  # a thumb's target, 48 px square, its marks and count inside it
                assert (round(w), round(h)) == (48, 48), p
                assert all(p["box"][0] - .5 <= q[0] and q[1] <= p["box"][1] + .5 and p["box"][2] - .5 <= q[2]
                           and q[3] <= p["box"][3] + .5 for q in p["parts"]), p
        if touch:  # the title keeps some room even at 320 px
            assert line["h3"] is None or line["h3"][1] - line["h3"][0] > 40, (title, line["h3"])
        if touch:  # 8 px between two on a row
            boxes = [p["box"] for p in line["plays"]]
            assert all(b[0] - a[1] >= 7.5 for a, b in zip(boxes, boxes[1:], strict=False) if same_row(a, b)), (title, boxes)
    # Needs review: on a phone a row of its own under the title, Fetch now's glyph on the title's row.
    desperado = laid["Desperado"]
    assert same_row(desperado["more"], desperado["action"]) and same_row(desperado["more"], desperado["h3"])
    if phone:
        assert desperado["status"][2] >= desperado["h3"][3] - 0.5, desperado
    else:
        assert same_row(desperado["more"], desperado["status"]), desperado
    # The keys line up, and so do the chevrons.
    assert len({round(line["key"][1]) for line in laid.values() if line["key"]}) == 1, laid
    assert len({round(line["more"][1]) for line in laid.values()}) == 1, laid
