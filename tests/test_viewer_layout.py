"""The sheet viewer on a wide screen: one column, centred, unless the whole song fits the window in columns.

A song in columns runs down the first and back up the next; only a song the window shows whole can do that
without breaking the reading order and the autoscroll. It takes the fewest columns that show it whole, from two
up to as many as fit side by side (five at most: the owner's ask of 2026-11-18, "so much empty space between the
two columns"), each at least as wide as the song's widest line, kept between 16 em (no slivers) and 24 em of the
reader's own text: a song of long lines takes two columns of 24 em as before (the owner's narrower columns, D8).
The window's room for them is less the page's at its foot and, from 1200 px, the toolbar's at its top
(test_viewer_toolbar.py).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from caracole.viewer import build_viewer
from caracole.viewer.book import BookSong, build_songbook
from caracole.viewer.harptab_page import build_harmonica_viewer

from helpers.browser import CHROMIUM_MARKS, Browser
from helpers.chromium import Chromium

FIXTURES = Path(__file__).parent / "fixtures" / "chordpro"
SHORT = (FIXTURES / "ug_sheet.cho").read_text(encoding="utf-8")  # five short sections: a window holds them
LONG = "{title: Long Song}\n{artist: The Placeholders}\n" + "".join(
    f"{{comment: Verse {n}}}\n[G]Made up words [D]for verse {n},\n[Em]a line that [C]goes on\n"
    f"[G]and another [D]one after it,\n[Em]until the [C]verse ends\n\n"
    for n in range(1, 21)
)
TINY = "{title: Tiny Song}\n{artist: The Placeholders}\n{comment: Verse}\n[G]Tiny [D]words\n\n{comment: Chorus}\n[C]Sing it [G]out\n"
# A short song of long lines, each past 24 em: two columns of it are each 24 em at least, as before the owner's ask
# of 2026-11-18 (a song of short lines takes narrower columns, 16 em at least).
BROAD = "{title: Broad Song}\n{artist: The Placeholders}\n" + "".join(
    f"{{comment: {name}}}\n[G]Made up words that run along the line for [D]a while, and then [Em]some more of them "
    f"[C]to end it\n[C]Sing it out and sing it [G]long, a line that goes on [Am]past the room of a [F]narrow one\n\n"
    for name in ("Verse", "Chorus", "Bridge", "Outro")
)
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
        tab = opened(browser, build_viewer(BROAD), tmp_path)
        columns = lambda: tab.eval(LAYOUT)["right"] > 0  # noqa: E731
        seen = [columns()]
        resize(browser, 1600, 400)  # too low for the song in two columns, or in three (the rail of necks gone)
        tab.wait_for(f"({LAYOUT}).right === 0")
        resize(browser, 1600, 800)
        tab.wait_for(f"({LAYOUT}).right > 0")
        for _ in range(3):  # 24 px: two columns of its long lines no longer fit side by side
            tab.eval("document.getElementById('bigger').click()")
        seen.append(columns())
        for _ in range(3):
            tab.eval("document.getElementById('smaller').click()")
        seen.append(columns())
    assert seen == [True, False, True]


def test_text_too_large_for_two_columns_reads_in_one_centred_even_in_a_short_song(tmp_path):
    # The window would hold this song whole, but two columns of 24 em of this text no longer fit side by side.
    with Chromium(tmp_path / "profile", size=DESKTOP) as browser:
        tab = opened(browser, build_viewer(BROAD), tmp_path)
        two = tab.eval(LAYOUT)
        for _ in range(3):  # 24 px
            tab.eval("document.getElementById('bigger').click()")
        one = tab.eval(LAYOUT)
    assert two["right"] > 0, two
    assert one["right"] == 0 and one["width"] < 900 and one["font"] > 20, one


# Each column of a song of long lines is at least this many em of the sheet's text (the owner's D8), and each of a
# song of short lines this many (viewer.js layout()).
COLUMN_EM = 24
SHORT_COLUMN_EM = 16
# The room two columns of the sheet have at its text size, and their gap, as layout() measures them: in the
# two-column layout, whatever the page shows now.
TWO = """(() => {
  const root = document.documentElement;
  const sheet = document.getElementById("sheet");
  const shown = root.dataset.columns;
  root.dataset.columns = "2";
  const style = getComputedStyle(sheet);
  const seen = { width: sheet.getBoundingClientRect().width, gap: parseFloat(style.columnGap),
                 em: parseFloat(style.fontSize) };
  root.dataset.columns = shown;
  return seen;
})()"""


def fit_side_by_side(room: dict, em: float = COLUMN_EM) -> bool:
    """Whether two columns of ``em`` em of the room's text, and their gap, fit its width."""
    return 2 * em * room["em"] + room["gap"] <= room["width"]


@pytest.mark.parametrize("size, fragment", [("1199,800", ""), ("1280,800", "#necks=0&"), (DESKTOP, "")],
                         ids=["1199-no-rail", "1280-rail-hidden", "1600-beside-the-rail"])
def test_two_columns_hold_at_larger_text_sizes(tmp_path, size, fragment):
    # A song of long lines the window shows whole reads in two columns at every text size two columns of 24 em and
    # their gap fit the room at, in the reader's own size; at the next size, in one, 3 px larger.
    seen = {}
    with Chromium(tmp_path / "profile", size=size) as browser:
        for fs in range(18, 25):
            tab = opened(browser, build_viewer(BROAD), tmp_path / str(fs), fragment=f"{fragment or '#'}fs={fs}")
            seen[fs] = tab.eval(LAYOUT) | {"room": tab.eval(TWO)}
    for fs, at in seen.items():
        assert at["room"]["em"] == fs, at
        if fit_side_by_side(at["room"]):
            assert at["right"] > 0 and at["font"] == fs and at["height"] <= at["window"], (fs, at)
        else:
            assert at["right"] == 0 and at["font"] == fs + 3, (fs, at)
    assert seen[18]["right"] > 0 and seen[24]["right"] == 0, seen  # where they stop fitting lies in between
    # Sizes where columns of 28 em, the width before, gave one column, and 24 em give two.
    assert any(at["right"] > 0 and not fit_side_by_side(at["room"], 28) for at in seen.values()), seen
    if fragment:  # 1280 px with the rail hidden: 21 px reads in two now
        assert seen[21]["right"] > 0 and seen[22]["right"] > 0 and seen[23]["right"] == 0, seen


def test_a_song_of_short_lines_keeps_two_columns_of_16_em_at_sizes_two_of_24_em_would_not_fit(tmp_path):
    # Its lines are each narrower than 16 em: two columns of 16 em and their gap fit 1280 px with the rail hidden at
    # every text size (up to 30 px), where two of 24 em stop at 22 px.
    seen = {}
    with Chromium(tmp_path / "profile", size="1280,800") as browser:
        for fs in (23, 26, 30):
            tab = opened(browser, build_viewer(TINY), tmp_path / str(fs), fragment=f"#necks=0&fs={fs}")
            seen[fs] = tab.eval(LAYOUT) | {"room": tab.eval(TWO)}
    for fs, at in seen.items():
        assert not fit_side_by_side(at["room"]) and fit_side_by_side(at["room"], SHORT_COLUMN_EM), (fs, at)
        assert at["right"] > 0 and at["font"] == fs and at["height"] <= at["window"], (fs, at)


def test_at_the_default_size_nothing_changes(tmp_path):
    with Chromium(tmp_path / "profile", size=DESKTOP) as browser:
        long = opened(browser, build_viewer(LONG), tmp_path / "long").eval(LAYOUT)
        short = opened(browser, build_viewer(SHORT), tmp_path / "short").eval(LAYOUT)
    assert long["right"] == 0 and long["font"] == 21, long  # too tall to show whole: one column, larger
    assert short["right"] > 0 and short["font"] == 18, short


def test_the_size_buttons_keep_two_columns_up_to_22_px(tmp_path):
    # At 1280 px with the rail of necks hidden, two columns of 24 em and their gap fit up to 22 px of text.
    with Chromium(tmp_path / "profile", size="1280,800") as browser:
        tab = opened(browser, build_viewer(BROAD), tmp_path, fragment="#necks=0")
        seen = [tab.eval(LAYOUT)]
        for button in ("bigger", "bigger", "bigger", "smaller"):
            tab.eval(f"document.getElementById('{button}').click()")
            seen.append(tab.eval(LAYOUT))
    two = [(s["right"] > 0, s["font"]) for s in seen]
    assert two == [(True, 18), (True, 20), (True, 22), (False, 27), (True, 22)], seen


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
    # From 900 px wide the settings are a rail the song moves over for: two columns of its long lines no longer
    # fit beside it, so the song reads in one, in the larger text, and in two again once the rail closes.
    with Chromium(tmp_path / "profile", size=DESKTOP) as browser:
        tab = opened(browser, build_viewer(BROAD), tmp_path)
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
    # this short song's long lines no longer fit beside it, at 1600 px they do; the song is measured beside the rail.
    seen = {}
    for width in (1199, 1280, 1600):
        with Chromium(tmp_path / f"profile-{width}", size=f"{width},800") as browser:
            seen[width] = opened(browser, build_viewer(BROAD), tmp_path).eval(LAYOUT)
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


# --- As many columns as the song's lines leave room for (the owner's ask of 2026-11-18) -----------------------------

# A song of short lines (none past 16 em), too tall to show whole in two columns at 1920 × 1080 and short enough for
# three: nine verses of four lines.
SHORT_LINES = "{title: Short Lines}\n{artist: The Placeholders}\n" + "".join(
    f"{{comment: Verse {n}}}\n[G]Made up words [D]for verse {n},\n[Em]a line that [C]goes on\n"
    f"[G]and another [D]one after it,\n[Em]until the [C]verse ends\n\n"
    for n in range(1, 10)
)
# WIDE_LINES' verses, their lines cut short: as tall a song, of short lines.
SHORT_TWIN = "{title: Short Twin}\n{artist: The Placeholders}\n" + "".join(
    f"{{comment: Verse {n}}}\n[G]Made up [D]verse {n},\n[C]another [G]one,\n[Em]a third, [C]the same,\n"
    f"[G]a fourth to [D]close it\n\n"
    for n in range(1, 7)
) + "{comment: Verse 7}\n[G]Made up [D]verse 7,\n[C]another [G]one,\n"
# Made-up lines in Chinese, sung in the owner's kind of song: a dozen characters or so, in two or three words.
ZH_LINES = ("河边的小路 通向远方的家", "我在窗前 数着天上的星星", "秋天的风 吹过山岗和田野", "旧信封里 有一个夏天的歌",
            "火车开往 没有名字的城", "灯光照亮 回家的那座桥", "黄昏的站台 空无一人啊", "她把吉他 放在窗边的椅子上",
            "风里还有 昨天的歌声", "我们在沙漠里 等一场雨", "谁也没有 说一声再见", "月亮照着 安静的小镇",
            "你说过的话 我还都记得", "遥远的地方 有一盏灯", "我们一起唱歌 直到天亮", "山的那一边 是蓝色的大海")
ZH_RIFF = "[Cadd9] [D6add9] [Bm7] [Em] [Cmaj7] [D6add9] [Em]\n"


def zh_song() -> str:
    """A made-up song in Chinese like the owner's screenshot (宋冬野's 斑马斑马 on UG, at 2000 × 1050 with pinyin): an
    intro, two verses and a bridge of sung lines, each with four chords, two choruses, a line of chords between them
    and one at the end; with the readings over the characters, two columns run past the bar."""
    sung = iter(ZH_LINES * 2)

    def lines(count: int) -> str:
        out = ""
        for _ in range(count):
            first, second = next(sung).split(" ")
            out += f"[Cmaj7]{first[:2]}[D]{first[2:]} [Bm]{second[:3]}[Em]{second[3:]}\n"
        return out

    return ("{title: 河边的小路}\n{artist: 虚构乐队}\n{key: G}\n"
            f"{{comment: Intro}}\n{ZH_RIFF}\n{{comment: Verse 1}}\n{lines(4)}\n"
            f"{{start_of_chorus: Chorus}}\n{lines(4)}{{end_of_chorus}}\n\n{{comment: Instrumental}}\n{ZH_RIFF}\n"
            f"{{comment: Verse 2}}\n{lines(4)}\n{{comment: Bridge}}\n{lines(8)}\n"
            f"{{start_of_chorus: Chorus}}\n{lines(4)}{{end_of_chorus}}\n\n{{comment: Outro}}\n{ZH_RIFF}")


# How the page lays the song out in columns: their count (data-columns) and the distinct lefts of the song's rows;
# the gap and each column's width; the sheet's height against the room above the bar; whether its end is in the
# last column; the sung lines that wrap (their columns' bottoms apart); the widest row as it would run unwrapped
# (each as wide as its content, a chord past its text counted), in px and in em of the sheet's text; sideways scroll.
COLUMNS = """(() => {
  const root = document.documentElement;
  const sheet = document.getElementById("sheet");
  const box = sheet.getBoundingClientRect();
  const style = getComputedStyle(sheet);
  const n = Number(root.dataset.columns);
  const gap = parseFloat(style.columnGap) || 0;
  const rows = [...sheet.querySelectorAll(".sec > .l, .sec > .tab")];
  const lefts = new Set(rows.map((r) => Math.round(r.getBoundingClientRect().left)));
  const end = rows[rows.length - 1].getBoundingClientRect();
  const wrapped = rows.filter((r) => r.querySelector(".s")).filter((r) => {
    const bottoms = [...r.querySelectorAll(".s, .w")].map((c) => c.getBoundingClientRect().bottom);
    return Math.max(...bottoms) - Math.min(...bottoms) > 2;
  }).length;
  for (const r of rows) r.style.width = "max-content";
  const widest = Math.max(...rows.map((r) => {
    const own = r.getBoundingClientRect();
    let right = own.right;
    for (const c of r.querySelectorAll(".s > .c")) right = Math.max(right, c.getBoundingClientRect().right);
    return right - own.left;
  }));
  for (const r of rows) r.style.width = "";
  const page = document.querySelector(".page");
  const em = parseFloat(style.fontSize);
  return {
    columns: root.dataset.columns, lefts: lefts.size, gap, em, column: (box.width - (n - 1) * gap) / n,
    // the window less the page's room at its foot and, from 1200 px, the toolbar's at its top (viewer.js layout())
    height: box.height, room: innerHeight - parseFloat(getComputedStyle(page).paddingBottom)
      - (parseFloat(getComputedStyle(root).getPropertyValue("--toolbar")) || 0),
    last: end.left >= box.left + (n - 1) * (box.width + gap) / n - 1, wrapped, widest, widestEm: widest / em,
    sideways: root.scrollWidth > root.clientWidth,
  };
})()"""


def in_columns(count: int) -> str:
    """The sheet's height and its gap laid out in ``count`` columns, whatever the page shows now (given back after)."""
    return f"""(() => {{
      const root = document.documentElement;
      const sheet = document.getElementById("sheet");
      const shown = root.dataset.columns;
      root.dataset.columns = "{count}";
      const seen = {{ height: sheet.getBoundingClientRect().height, gap: parseFloat(getComputedStyle(sheet).columnGap) }};
      root.dataset.columns = shown;
      return seen;
    }})()"""


def shows_whole(seen: dict) -> None:
    assert seen["lefts"] == int(seen["columns"]), seen  # every column holds some of the song
    assert seen["height"] <= seen["room"] and seen["last"], seen  # the whole song in the room, its end in the last
    assert not seen["sideways"], seen


def test_from_1200_px_the_columns_show_the_song_whole_under_the_toolbar(tmp_path):
    # From 1200 px the bar is a toolbar under the title, sticking to the window's top (test_viewer_toolbar.py): the room
    # for columns is the window less its 56 px (--toolbar) and the page's room at its foot. A window that would hold the
    # song in two columns with no toolbar, but not under it, takes more columns, or one.
    MIDDLING = "{title: Middling Song}\n{artist: The Placeholders}\n" + "".join(
        f"{{comment: Verse {n}}}\n[G]Tiny [D]words\n[C]Sing it [G]out\n\n" for n in range(1, 8))
    under = """(() => { const sheet = document.getElementById("sheet").getBoundingClientRect();
      const bar = document.getElementById("bar").getBoundingClientRect();
      return {top: sheet.top, bottom: sheet.bottom, bar: bar.bottom, stuck: bar.top, window: innerHeight}; })()"""
    with Chromium(tmp_path / "profile", size=DESKTOP) as browser:
        tab = opened(browser, build_viewer(MIDDLING), tmp_path)
        first = tab.eval(COLUMNS)
        tab.eval("document.getElementById('sheet').scrollIntoView({block: 'start'})")
        seen = tab.eval(under)
        two = tab.eval(in_columns(2))["height"]
        foot = tab.eval("parseFloat(getComputedStyle(document.querySelector('.page')).paddingBottom)")
        chrome = tab.eval("outerHeight - innerHeight")
        resize(browser, 1600, round(two + foot + 28 + chrome))  # room for it but for the toolbar's 56 px
        tab.wait_for(f"innerHeight === {round(two + foot + 28)} && document.documentElement.dataset.columns !== '2'")
        tight = tab.eval(COLUMNS)
        resize(browser, 1600, round(two + foot + 56 + 8 + chrome))  # and with them
        tab.wait_for("document.documentElement.dataset.columns === '2'")
        roomy = tab.eval(COLUMNS)
    assert first["columns"] == "2", first
    assert two + foot + 28 >= 500, two  # the tight window no short screen, whose full screen has no toolbar
    shows_whole(first)
    # brought into view, the song whole between the toolbar and the window's foot
    assert seen["stuck"] == 0 and seen["bar"] <= seen["top"] and seen["bottom"] <= seen["window"] - foot, seen
    assert tight["columns"] != "2", tight
    if tight["columns"] != "1":
        shows_whole(tight)
    shows_whole(roomy)


def test_a_song_of_short_lines_too_tall_for_two_columns_reads_in_three_and_shows_whole(tmp_path):
    with Chromium(tmp_path / "profile", size="1920,1080") as browser:
        tab = opened(browser, build_viewer(SHORT_LINES), tmp_path)
        seen, two, span = tab.eval(COLUMNS), tab.eval(in_columns(2)), tab.eval(SPAN)
    assert two["height"] > seen["room"], two  # two columns don't show it whole
    assert seen["columns"] == "3", seen
    shows_whole(seen)
    assert seen["widestEm"] < SHORT_COLUMN_EM and seen["column"] >= SHORT_COLUMN_EM * seen["em"], seen
    assert not seen["wrapped"], seen
    # The columns spread across the page as two do, 5 % of the room each side; the room over widens them, and
    # three stand closer together than two.
    margins_ok(span)
    assert 40 <= seen["gap"] < two["gap"], (seen, two)


def test_the_count_follows_the_window_fewest_first(tmp_path):
    # A taller window shows the song whole in two; a lower one in three, then in none: one column.
    with Chromium(tmp_path / "profile", size="1920,1080") as browser:
        tab = opened(browser, build_viewer(SHORT_LINES), tmp_path)
        seen = [tab.eval("document.documentElement.dataset.columns")]
        for width, height, columns in ((1920, 1440, "2"), (1920, 1080, "3"), (1920, 600, "1"), (1920, 1080, "3")):
            resize(browser, width, height)
            tab.wait_for(f"document.documentElement.dataset.columns === '{columns}'")
            seen.append(tab.eval(COLUMNS))
    assert seen[0] == "3"
    for at in (seen[1], seen[2], seen[4]):
        shows_whole(at)
    assert seen[3]["lefts"] == 1 and seen[3]["em"] > 18, seen[3]


@pytest.mark.parametrize("fragment", ["#py=1&nm=both", "#py=1&nm=both&necks=0"], ids=["beside-the-rail", "rail-hidden"])
def test_the_owners_song_in_chinese_with_pinyin_shows_whole_in_as_many_columns_as_it_takes(tmp_path, fragment):
    # The owner's screenshot: a song in Chinese with its readings and the chords' numerals, at about 2000 × 1050,
    # whose two columns ran past the bar with a wide empty gap between them.
    with Chromium(tmp_path / "profile", size="2000,1050") as browser:
        tab = opened(browser, build_viewer(zh_song()), tmp_path, fragment=fragment)
        seen, two = tab.eval(COLUMNS), tab.eval(in_columns(2))
        readings = tab.eval("document.querySelectorAll('#sheet ruby.py').length")
    assert readings > 100, readings
    assert two["height"] > seen["room"], two  # two columns don't show it whole
    assert int(seen["columns"]) >= 3, seen
    shows_whole(seen)
    # Each column at least as wide as its widest row, up to 24 em (its rows of chords with their numerals are
    # longer, and wrap between their chords): no sung line wraps.
    assert seen["column"] >= min(seen["widest"], COLUMN_EM * seen["em"]) - 1, seen
    assert not seen["wrapped"], seen


def test_a_song_of_long_lines_takes_two_columns_at_most_where_only_two_fit(tmp_path):
    # At 1600 px beside the rail of necks, three columns of 24 em don't fit side by side: a song of long lines that
    # two columns don't show whole reads in one, where its twin of short lines, as tall, reads in three.
    with Chromium(tmp_path / "profile", size="1600,900") as browser:
        wide = opened(browser, build_viewer(WIDE_LINES), tmp_path / "wide")
        long = wide.eval(COLUMNS) | {"two": wide.eval(in_columns(2)), "three": wide.eval(TWO) | wide.eval(in_columns(3))}
        short = opened(browser, build_viewer(SHORT_TWIN), tmp_path / "short").eval(COLUMNS)
    assert long["widestEm"] > COLUMN_EM, long
    assert long["two"]["height"] > long["room"], long  # two don't show it whole
    room = long["three"]
    assert 3 * COLUMN_EM * room["em"] + 2 * room["gap"] > room["width"], room  # and three of 24 em don't fit
    assert long["columns"] == "1" and long["lefts"] == 1, long
    assert short["columns"] == "3", short
    shows_whole(short)


def test_no_count_shows_a_long_song_whole_so_it_reads_in_one_even_where_five_fit(tmp_path):
    # On 2560 × 1440 five columns of a song of short lines fit side by side, the most the page takes.
    long = LONG + "".join(f"{{comment: Verse {n}}}\n[G]Made up words [D]for verse {n},\n[Em]a line that [C]goes on\n\n"
                          for n in range(21, 41))
    with Chromium(tmp_path / "profile", size="2560,1440") as browser:
        tab = opened(browser, build_viewer(long), tmp_path)
        seen, five = tab.eval(LAYOUT), tab.eval(in_columns(5))
    assert five["height"] > seen["window"], five
    assert seen["right"] == 0 and seen["width"] <= 860 and seen["font"] > 18, seen


def test_a_songbooks_song_takes_as_many_columns_as_it_takes(tmp_path):
    book = build_songbook("Campfire", [BookSong("Short Lines", "The Placeholders", cho=SHORT_LINES, id="aaaa"),
                                       BookSong("Synthetic Test Song", "The Placeholders", cho=SHORT, id="bbbb")])
    with Chromium(tmp_path / "profile", size="1920,1080") as browser:
        three = opened(browser, book, tmp_path, "songbook.html", "#song-1").eval(COLUMNS)
        two = opened(browser, book, tmp_path, "songbook.html", "#song-2").eval(COLUMNS)
    assert three["columns"] == "3", three
    shows_whole(three)
    assert two["columns"] == "2", two
    shows_whole(two)


def test_a_harmonica_tabs_page_reads_in_one_column_as_before(tmp_path):
    tab_text = (Path(__file__).parent / "fixtures" / "harptabs" / "tabs" / "124_heart-of-gold.txt").read_text(
        encoding="utf-8")
    html = build_harmonica_viewer(tab_text, title="Heart of Gold", artist="The Placeholders",
                                  tab_file="harmonica-1.txt", page_key="G")
    with Chromium(tmp_path / "profile", size="1920,1080") as browser:
        page = tmp_path / "Library" / "Artist" / "Title" / "harmonica-1.html"
        page.parent.mkdir(parents=True, exist_ok=True)
        page.write_text(html, encoding="utf-8")
        (page.parent / "harmonica-1.txt").write_text(tab_text, encoding="utf-8")
        tab = browser.open(page.as_uri())
        tab.wait_for("document.documentElement.dataset.ready === '1'")
        seen = tab.eval("""(() => { const s = getComputedStyle(document.getElementById("sheet"));
          return { columns: document.documentElement.dataset.columns || null, count: s.columnCount,
                   font: parseFloat(s.fontSize), page: document.querySelector(".page").getBoundingClientRect().width }; })()""")
    assert seen["columns"] is None and seen["count"] == "auto", seen
    assert seen["font"] == 21 and seen["page"] <= 860, seen


def test_printed_the_song_is_one_column(tmp_path):
    page = tmp_path / "Library" / "Artist" / "Title" / "sheet.html"
    page.parent.mkdir(parents=True, exist_ok=True)
    page.write_text(build_viewer(SHORT_LINES), encoding="utf-8")
    with Browser(tmp_path / "profile", width=1920, height=1080) as b:
        b.open(page.as_uri())
        assert b.wait("document.documentElement.dataset.ready === '1'")
        screen = b.js(COLUMNS)
        b.send("Emulation.setEmulatedMedia", media="print")
        assert b.wait("matchMedia('print').matches")
        printed = b.js("""(() => { const s = document.getElementById("sheet");
          const lefts = new Set([...s.querySelectorAll(".sec > .l")].map((l) => Math.round(l.getBoundingClientRect().left)));
          return { count: getComputedStyle(s).columnCount, lefts: lefts.size }; })()""")
    assert screen["columns"] == "3", screen
    assert printed == {"count": "auto", "lefts": 1}, printed
