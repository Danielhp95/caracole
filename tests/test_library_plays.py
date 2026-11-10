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
        "Open the chord sheet of Hotel California, from Ultimate Guitar, LaCuerda and the audio (auto-chords), "
        "6 versions",
        "Download the Guitar Pro file of Hotel California, from gtptabs.com and your inbox, 2 files",
        "Open the guitar tab of Hotel California",
        "Open the harmonica tab of Hotel California, from harptabs.com",
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
    assert guitar["said"] == "Open the Guitar Pro tab of Hotel California, from gtptabs.com and your inbox, 2 files"
    shown = plays(conn, cfg, tmp_path, "Take It Easy")
    assert [(p["kind"], p["href"], p["marks"]) for p in shown] == [
        ("sheet", "Eagles/Take%20It%20Easy/sheet.html", ["ug"]),
        ("harmonica", "Eagles/Take%20It%20Easy/harmonica-1.html", ["harptabs"])]
    assert shown[1]["said"] == "Open the harmonica tab of Take It Easy, from harptabs.com"


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
    assert ukulele["said"] == "Open the ukulele chords of Over the Rainbow, from Ultimate Guitar"


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
    assert game["said"] == "Open the game music tab of Resting Grounds, from gametabs.net, 2 tabs"
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
    assert shown == {"text": "", "said": "Fetch Creep by Radiohead now", "type": "submit",
                     "title": "Fetch now: ask Ultimate Guitar for this song now, politely",
                     "glyph": "glyph glyph-download", "action": "/fetch", "have": 0}


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
      parts: Array.from(p.querySelectorAll(".n, .marks > *")).map(box) })) };
}
note("laid", { laid, page: [document.documentElement.scrollWidth, window.innerWidth] });
"""


@pytest.mark.parametrize(("size", "touch"), [("390,844", True), ("1280,900", False), ("820,1180", True)])
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
            # A thumb's target, 44 px square; a mouse's, smaller.
            w, h = p["box"][1] - p["box"][0], p["box"][3] - p["box"][2]
            assert (round(w), round(h)) == ((44, 44) if touch else (30, 24)), p
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
