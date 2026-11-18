"""The sheet viewer on a wide screen: one column, centred, unless the whole song fits the window in two.

A song in two columns runs down the first and back up the second; only a song the window shows
whole can do that without breaking the reading order and the autoscroll.
"""

from __future__ import annotations

from pathlib import Path

from caracole.viewer import build_viewer
from caracole.viewer.book import BookSong, build_songbook

from helpers.browser import CHROMIUM_MARKS
from helpers.chromium import Chromium

FIXTURES = Path(__file__).parent / "fixtures" / "chordpro"
SHORT = (FIXTURES / "ug_sheet.cho").read_text(encoding="utf-8")  # five short sections: a window holds them
LONG = "{title: Long Song}\n{artist: The Placeholders}\n" + "".join(
    f"{{comment: Verse {n}}}\n[G]Made up words [D]for verse {n},\n[Em]a line that [C]goes on\n"
    f"[G]and another [D]one after it,\n[Em]until the [C]verse ends\n\n"
    for n in range(1, 21)
)
TINY = "{title: Tiny Song}\n{artist: The Placeholders}\n{comment: Verse}\n[G]Tiny [D]words\n\n{comment: Chorus}\n[C]Sing it [G]out\n"
# A wide laptop's: beside the rail of necks (345 px, from 1200 px wide), as much room as 1280 px without it.
DESKTOP = "1600,800"

pytestmark = CHROMIUM_MARKS  # every test here opens the page in Chromium

# What the page shows: how many of the sheet's lines sit in its right half (a second column), and so on; its
# margins are those of the room beside the rail of necks, when there is one.
LAYOUT = """(() => {
  const sheet = document.getElementById("sheet");
  const box = sheet.getBoundingClientRect();
  const middle = box.left + box.width / 2;
  const page = document.querySelector(".page").getBoundingClientRect();
  const rail = document.getElementById("necks");
  const from = rail && !rail.hidden ? rail.getBoundingClientRect().right : 0;
  return {
    right: [...sheet.querySelectorAll(".l, .tab")].filter((l) => l.getBoundingClientRect().left > middle).length,
    height: box.height, window: innerHeight,
    font: parseFloat(getComputedStyle(sheet).fontSize),
    margins: [Math.round(page.left - from), Math.round(document.documentElement.clientWidth - page.right)],
    rail: Math.round(from),
    width: page.width, sideways: document.documentElement.scrollWidth > document.documentElement.clientWidth,
  };
})()"""


def opened(browser: Chromium, html: str, tmp_path: Path, name: str = "sheet.html", fragment: str = ""):
    page = tmp_path / "Library" / "Artist" / "Title" / name
    page.parent.mkdir(parents=True, exist_ok=True)
    page.write_text(html, encoding="utf-8")
    tab = browser.open(page.as_uri() + fragment)
    tab.wait_for("document.documentElement.dataset.ready === '1'")
    return tab


def resize(browser: Chromium, width: int, height: int) -> None:
    """Make the browser's one window ``width`` by ``height``, as a person dragging its corner would."""
    page = next(t for t in browser.send("Target.getTargets")["targetInfos"]
                if t["type"] == "page" and t["url"].startswith("file:"))
    window = browser.send("Browser.getWindowForTarget", targetId=page["targetId"])["windowId"]
    browser.send("Browser.setWindowBounds", windowId=window, bounds={"width": width, "height": height})


def test_a_song_that_fits_the_window_reads_in_two_columns_side_by_side(tmp_path):
    with Chromium(tmp_path / "profile", size=DESKTOP) as browser:
        seen = opened(browser, build_viewer(SHORT), tmp_path).eval(LAYOUT)
    assert seen["right"] > 0, seen  # a second column
    assert seen["height"] <= seen["window"], seen  # and the whole song in sight
    assert seen["width"] > 1000 and not seen["sideways"], seen


def test_a_longer_song_reads_down_one_column_centred_in_larger_text(tmp_path):
    with Chromium(tmp_path / "profile", size=DESKTOP) as browser:
        seen = opened(browser, build_viewer(LONG), tmp_path).eval(LAYOUT)
    assert seen["right"] == 0, seen  # one column, top to bottom
    assert seen["height"] > seen["window"], seen
    assert abs(seen["margins"][0] - seen["margins"][1]) <= 1 and seen["width"] < 900, seen  # centred
    assert seen["font"] > 18, seen  # larger than a phone's 18 px
    assert not seen["sideways"], seen


def test_the_columns_follow_the_window_and_the_text_size(tmp_path):
    with Chromium(tmp_path / "profile", size=DESKTOP) as browser:
        tab = opened(browser, build_viewer(SHORT), tmp_path)
        columns = lambda: tab.eval(LAYOUT)["right"] > 0  # noqa: E731
        seen = [columns()]
        resize(browser, 1600, 400)  # too low for the song, even in two columns
        tab.wait_for(f"({LAYOUT}).right === 0")
        resize(browser, 1600, 800)
        tab.wait_for(f"({LAYOUT}).right > 0")
        tab.eval("document.getElementById('bigger').click()")  # two no longer fit side by side
        seen.append(columns())
        tab.eval("document.getElementById('smaller').click()")
        seen.append(columns())
    assert seen == [True, False, True]


def test_text_too_large_for_two_columns_reads_in_one_centred_even_in_a_short_song(tmp_path):
    # The window would hold this song whole, but two columns of this text no longer fit side by side.
    with Chromium(tmp_path / "profile", size=DESKTOP) as browser:
        tab = opened(browser, build_viewer(TINY), tmp_path)
        two = tab.eval(LAYOUT)
        tab.eval("document.getElementById('bigger').click()")
        one = tab.eval(LAYOUT)
    assert two["right"] > 0, two
    assert one["right"] == 0 and one["width"] < 900 and one["font"] > 20, one


def test_measuring_the_columns_never_moves_the_page(tmp_path):
    # Each change measures the song in two columns, shorter than one: the place you were reading stays put.
    with Chromium(tmp_path / "profile", size=DESKTOP) as browser:
        tab = opened(browser, build_viewer(LONG), tmp_path)
        before, after = tab.eval("""(() => {
          window.scrollTo(0, document.documentElement.scrollHeight);
          const before = window.scrollY;
          document.getElementById("up").click();  // a semitone up: every chord renamed, and measured again
          return [before, window.scrollY];
        })()""")
        seen = tab.eval(LAYOUT)
    assert before > 1000 and after == before
    assert seen["right"] == 0, seen


def test_a_songbooks_song_takes_two_columns_only_when_it_fits(tmp_path):
    book = build_songbook("Campfire", [BookSong("Synthetic Test Song", "The Placeholders", cho=SHORT, id="aaaa"),
                                       BookSong("Long Song", "The Placeholders", cho=LONG, id="bbbb")])
    with Chromium(tmp_path / "profile", size=DESKTOP) as browser:
        short = opened(browser, book, tmp_path, "songbook.html", "#song-1").eval(LAYOUT)
        long = opened(browser, book, tmp_path, "songbook.html", "#song-2").eval(LAYOUT)
    assert short["right"] > 0 and short["height"] <= short["window"], short
    assert long["right"] == 0 and long["font"] > 18, long


def test_the_settings_rail_beside_the_song_measures_its_columns_again(tmp_path):
    # From 900 px wide the settings are a rail the song moves over for: two columns of it no longer fit
    # beside it, so the song reads in one, in the larger text, and in two again once the rail closes.
    with Chromium(tmp_path / "profile", size=DESKTOP) as browser:
        tab = opened(browser, build_viewer(SHORT), tmp_path)
        seen = [tab.eval(LAYOUT)]
        tab.eval("document.getElementById('more').click()")
        seen.append(tab.eval(LAYOUT) | {"columns": tab.eval("document.documentElement.dataset.columns")})
        tab.eval("document.getElementById('more').click()")
        seen.append(tab.eval(LAYOUT))
    assert seen[0]["right"] > 0, seen
    assert seen[1]["right"] == 0 and seen[1]["columns"] == "1" and seen[1]["font"] > 18, seen[1]
    assert not seen[1]["sideways"], seen[1]
    assert seen[2]["right"] > 0 and seen[2]["font"] == seen[0]["font"], seen


def test_the_rail_of_necks_takes_its_width_off_the_room_for_two_columns(tmp_path):
    # From 1200 px wide the rail is on the left, and the song moves over for it: at 1280 px two columns of
    # this short song no longer fit beside it, at 1600 px they do; the song is measured beside the rail.
    seen = {}
    for width in (1199, 1280, 1600):
        with Chromium(tmp_path / f"profile-{width}", size=f"{width},800") as browser:
            seen[width] = opened(browser, build_viewer(SHORT), tmp_path).eval(LAYOUT)
    assert seen[1199]["rail"] == 0 and seen[1199]["right"] > 0, seen[1199]  # no rail: two columns
    assert seen[1280]["rail"] == 345 and seen[1280]["right"] == 0 and seen[1280]["font"] > 18, seen[1280]
    assert abs(seen[1280]["margins"][0] - seen[1280]["margins"][1]) <= 1, seen[1280]  # centred beside it
    assert seen[1600]["rail"] == 345 and seen[1600]["right"] > 0, seen[1600]
    assert not any(s["sideways"] for s in seen.values()), seen


# Lines that wrap in two columns of today's 1180 px page and run on in the wider ones of a big window.
# (Six verses and two lines: the song just fills two columns of the wide window, with lines standing .4em apart.)
WIDE_LINES = "{title: Wide Song}\n{artist: The Placeholders}\n" + "".join(
    f"{{comment: Verse {n}}}\n[G]Made up words for [D]verse {n}, a line that goes on [Em]and on and on, long,\n"
    f"[C]and another one after it that is [G]just as long as it is, or so,\n"
    f"[Em]a third one, the same, [C]for the room it takes up on it,\n[G]and a fourth to [D]close the verse here for now\n\n"
    for n in range(1, 7)
) + "{comment: Verse 7}\n[G]Made up words for [D]verse 7, a line that goes on [Em]and on and on, long,\n[C]and another one after it that is [G]just as long as it is, or so,\n"
# Where the sheet sits in the room beside the rail of necks (the rail is open from 1200 px wide).
SPAN = """(() => {
  const sheet = document.getElementById("sheet");
  const box = sheet.getBoundingClientRect();
  const w = document.documentElement.clientWidth;
  const rail = document.getElementById("necks");
  const from = rail && !rail.hidden ? rail.getBoundingClientRect().right : 0;
  return { columns: document.documentElement.dataset.columns, left: box.left, right: box.right, w, from,
           height: box.height, window: innerHeight };
})()"""


def margins_ok(seen: dict) -> None:
    room = seen["w"] - seen["from"]
    assert seen["left"] >= seen["from"], seen  # never under the rail
    assert abs(seen["left"] - seen["from"] - room * 0.05) <= room * 0.01, seen
    assert abs(seen["w"] - seen["right"] - room * 0.05) <= room * 0.01, seen


def test_two_columns_span_the_window_less_five_percent_each_side(tmp_path):
    for width, height in ((1920, 1080), (2560, 1440)):
        with Chromium(tmp_path / f"profile{width}", size=f"{width},{height}") as browser:
            seen = opened(browser, build_viewer(SHORT), tmp_path / str(width)).eval(SPAN)
        assert seen["columns"] == "2", seen
        margins_ok(seen)


def test_a_song_two_columns_of_the_old_width_could_not_show_whole_does_in_the_wider_ones(tmp_path):
    with Chromium(tmp_path / "profile", size="1920,1080") as browser:
        tab = opened(browser, build_viewer(WIDE_LINES), tmp_path)
        wide = tab.eval(SPAN)
        tab.eval("""(() => { const p = document.querySelector(".page").style;  // today's page: 1180 px at most
          p.setProperty("max-width", "1180px", "important"); p.setProperty("margin", "0 auto", "important");
          p.setProperty("padding-left", "16px", "important"); p.setProperty("padding-right", "16px", "important");
          window.dispatchEvent(new Event("resize")); })()""")
        tab.wait_for("document.documentElement.dataset.columns === '1'")
    assert wide["columns"] == "2" and wide["height"] <= wide["window"], wide


def test_a_song_too_tall_to_show_whole_stays_in_one_centred_column_on_a_big_window(tmp_path):
    with Chromium(tmp_path / "profile", size="1920,1080") as browser:
        seen = opened(browser, build_viewer(LONG), tmp_path).eval(LAYOUT)
    assert seen["right"] == 0 and seen["width"] <= 860 and seen["font"] > 18, seen
    assert abs(seen["margins"][0] - seen["margins"][1]) <= 1, seen


def test_below_1100px_the_song_is_one_column(tmp_path):
    with Chromium(tmp_path / "profile", size="1000,800") as browser:
        seen = opened(browser, build_viewer(SHORT), tmp_path).eval(SPAN)
    assert seen["columns"] == "1", seen


def test_beside_the_rail_of_necks_the_columns_keep_five_percent_of_the_room_left(tmp_path):
    with Chromium(tmp_path / "profile", size="1600,900") as browser:
        seen = opened(browser, build_viewer(SHORT), tmp_path).eval(SPAN)
    assert seen["from"] > 300 and seen["columns"] == "2", seen
    margins_ok(seen)
