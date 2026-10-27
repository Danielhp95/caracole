"""The sheet viewer's Pinyin: each Chinese character's reading over it, read at render time in context
(viewer/pinyin.py), carried in the page's data (``pinyin``), drawn by viewer.js when the settings' Pinyin row
turns it on (off at first), and kept for every page at once, as the rail of necks is.

The readings are pypinyin's, in context: what it says is what these tests write (不要 bú yào, 睡着 zháo).
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

from caracole.viewer import build_viewer, viewer_csp
from caracole.viewer.book import BookSong, build_songbook, songbook_csp
from caracole.viewer.pinyin import readings

from conftest import subprocess_pythonpath
from helpers.browser import Browser, in_chromium
from helpers.targets import small_targets
from helpers.version_pages import WONDERWALL, folder
from helpers.viewer_pages import viewer as open_viewer, written
from test_viewer_necks import STORAGE, follow, reload, reopen, served, to_song

# A line of 宋冬野's 斑马斑马, in Simplified characters and in Traditional ones (UG has a version of each).
BANMA = "斑马斑马 你不要睡着啦"
BANMA_TRADITIONAL = "斑馬斑馬 你不要睡著啦"
BANMA_READ = ["bān", "mǎ", "bān", "mǎ", "", "nǐ", "bú", "yào", "shuì", "zháo", "la"]


def data_of(html: str, block: str = "song") -> dict:
    found = re.search(rf'<script type="application/json" id="{block}">(.*?)</script>', html, re.S)
    assert found, f"no {block} data"
    return json.loads(found.group(1))


# --- the readings --------------------------------------------------------------------------------


def test_a_line_is_read_in_context_a_reading_for_each_character():
    assert readings([BANMA]) == [BANMA_READ]


def test_the_same_line_in_traditional_characters_reads_the_same():
    # pypinyin alone reads Traditional 著 as zhù (著名), never as the 着 of 睡着: in a Traditional sheet it is 着.
    assert readings([BANMA_TRADITIONAL]) == [BANMA_READ]


def test_a_character_read_two_ways_is_read_as_its_word_has_it():
    assert readings(["长城", "成长"]) == [["cháng", "chéng"], ["chéng", "zhǎng"]]
    # In Traditional characters too, read through Simplified ones: pypinyin alone reads 長城 zhǎng chéng.
    assert readings(["長城", "成長"]) == [["cháng", "chéng"], ["chéng", "zhǎng"]]


def test_in_a_traditional_sheet_a_zhu_word_keeps_its_zhu():
    # 著 is 着 in a Traditional sheet (浪費著, 睡著, 著急), but in a word Simplified writes with 著 it is zhù (or
    # zhuó: 執著), whether pypinyin's phrase dictionary has the word (顯著) or its reading is 著's first (著名).
    lines = ["可我浪費著我寒冷的年華", "顯著 著名 著急 執著", "他們睡著了"]
    assert readings(lines) == [
        ["kě", "wǒ", "làng", "fèi", "zhe", "wǒ", "hán", "lěng", "de", "nián", "huá"],
        ["xiǎn", "zhù", "", "zhù", "míng", "", "zháo", "jí", "", "zhí", "zhuó"],
        ["tā", "men", "shuì", "zháo", "le"],
    ]


def test_in_a_simplified_sheet_zhu_is_zhu():
    assert readings(["著名的歌", "我们睡着了"]) == [["zhù", "míng", "de", "gē"], ["wǒ", "men", "shuì", "zháo", "le"]]


def test_letters_digits_spaces_and_punctuation_have_no_reading():
    assert readings(["Hello 世界，ok 2!"]) == [["", "", "", "", "", "", "shì", "jiè", "", "", "", "", "", ""]]


def test_a_line_without_chinese_is_none_and_a_sheet_without_any_has_none():
    assert readings(["斑马", "la la", ""]) == [["bān", "mǎ"], None, None]
    assert readings(["la la la", "Hello"]) is None
    assert readings([]) is None


def test_a_japanese_sheet_has_none_its_kanji_are_no_mandarin():
    assert readings(["夢を見た", "空"]) is None  # kana: Japanese, whose kanji pinyin would misread
    assert readings(["约翰・列侬"]) == [["yuē", "hàn", "", "liè", "nóng"]]  # a name's dot is Chinese's too


def test_a_reading_has_its_tone_marks():
    assert readings(["绿色女儿只"]) == [["lǜ", "sè", "nǚ", "ér", "zhǐ"]]


# --- in the page's data ----------------------------------------------------------------------------

ZH = """{title: 合成}
{artist: 示例}
{key: C}
{comment: Verse}
[C]这是一[G]个合成的[Am]例子，ok
[F]  [G]
没有和弦的一行
la [C]la la

{comment: Chorus}
[F]长城和[C]成长
"""
# The lines of the song's sections, as the page draws them (#sheet section.sec > p.l): the text of each.
ZH_LINES = ["这是一个合成的例子，ok", "", "没有和弦的一行", "la la la", "长城和成长"]


def test_the_data_carries_each_lines_readings_in_the_order_the_page_draws_them():
    data = data_of(build_viewer(ZH))
    assert data["pinyin"] == readings(ZH_LINES)
    assert data["pinyin"][0] == ["zhè", "shì", "yí", "gè", "hé", "chéng", "de", "lì", "zi", "", "", ""]  # 一个: yí
    assert data["pinyin"][1] is None and data["pinyin"][3] is None  # chords alone; words with no Chinese
    assert data["pinyin"][4] == ["cháng", "chéng", "hé", "chéng", "zhǎng"]


def test_the_lines_the_data_reads_are_those_of_the_sheets_sections():
    html = build_viewer(ZH)
    article = re.search(r'<article[^>]*id="sheet"[^>]*>(.*?)</article>', html, re.S).group(1)
    lines = re.findall(r'<p class="l[^"]*">(.*?)</p>', article)
    texts = [re.sub(r"<b [^>]*>.*?</b>|<i [^>]*>.*?</i>|<[^>]+>", "", line) for line in lines]
    assert [t if t.strip() else "" for t in texts] == ZH_LINES
    assert len(data_of(html)["pinyin"]) == len(lines)


def test_the_notes_before_the_song_have_no_readings():
    cho = "{title: 合成}\n{artist: 示例}\n作词：示例\n作曲：示例\n来自网络\n{comment: Verse}\n[C]你好\n"
    data = data_of(build_viewer(cho))
    assert data["pinyin"] == [["nǐ", "hǎo"]]


def test_a_sheet_without_chinese_lyrics_has_no_readings_and_no_pinyin_row_shown():
    html = build_viewer("{title: 斑马}\n{artist: A}\n{comment: Verse}\n[Am]la la [F]la\n")
    assert "pinyin" not in data_of(html)
    assert re.search(r'<div id="pinyin-row" hidden>', html)  # the script shows it for a sheet with some


def test_the_settings_have_a_pinyin_row_hidden_until_the_script_shows_it():
    html = build_viewer(ZH)
    row = re.search(r'<div id="pinyin-row" hidden>(.*?)</div>', html, re.S)
    assert row and ('<button type="button" class="switch" id="pinyin-chip" aria-pressed="false" aria-controls="sheet" '
                    'aria-describedby="pinyin-hint">Pinyin</button>') in row.group(1)  # a switch, off


def test_a_songbooks_songs_each_carry_their_own_readings():
    songs = [BookSong("合成", "示例", cho=ZH, id="aaaa"),
             BookSong("Other", "A", cho="{title: Other}\n{artist: A}\n[C]la la\n", id="bbbb")]
    html = build_songbook("Campfire", songs)
    assert data_of(html, "data-1")["pinyin"] == readings(ZH_LINES)
    assert "pinyin" not in data_of(html, "data-2")
    assert 'id="pinyin-row"' in html


def test_the_pinyin_in_an_address_is_no_part_of_a_version():
    # An export or Make this my version reads the viewer's address: py=1 there plays the song no otherwise.
    from caracole.viewer.version import version_from_query

    assert version_from_query("#t=2&mode=dorian&capo=3&py=1") == version_from_query("#t=2&mode=dorian&capo=3")


# --- what the pages are made from -------------------------------------------------------------------


def test_the_viewer_is_made_from_the_pinyin_module_and_pypinyins_dictionaries(monkeypatch):
    from caracole.viewer import page

    assert page.HERE / "pinyin.py" in page.BUILD_FILES
    page.build_version.cache_clear()
    try:
        before = page.build_version()
        monkeypatch.setattr(page, "_pypinyin_version", lambda: "0.0.1")
        page.build_version.cache_clear()
        assert page.build_version() != before  # an upgrade of pypinyin may read a character otherwise
    finally:
        page.build_version.cache_clear()


@pytest.mark.slow
def test_pypinyin_is_loaded_only_for_a_sheet_with_chinese():
    code = (
        "import sys; import caracole.cli; from caracole.viewer import build_viewer, page\n"
        "page.build_version()\n"
        "build_viewer('{title: T}\\n{artist: A}\\n[C]la la\\n')\n"
        "print('pypinyin' in sys.modules)\n"
        "build_viewer('{title: T}\\n{artist: A}\\n[C]你好\\n')\n"
        "print('pypinyin' in sys.modules)\n"
    )
    src = Path(__file__).resolve().parents[1] / "src"
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True,
                         env={"PYTHONPATH": subprocess_pythonpath(src)})
    assert out.stdout.split() == ["False", "True"]


# --- in a browser --------------------------------------------------------------------------------------

DESKTOP = {"width": 1280, "height": 800, "mobile": False}
PHONE = {"width": 390, "height": 844, "mobile": True}
# A long line, which wraps on a phone, with a chord over a comma and one over a word of letters.
LONG = ("{title: 合成}\n{artist: 示例}\n{key: C}\n{comment: Verse}\n"
        "[C]这是一个[G]很长很长的[Am]合成例子[F]，我们[C]看它怎么[G]换行[Am]ok [F]然后继续唱下去\n"
        "[C]你好[G]，世界\n")

# The song's lines as drawn: each line's columns' text, and every ruby's character and reading.
DRAWN = """(() => {
  const lines = [...document.querySelectorAll('#sheet section.sec > p.l')];
  return {lines: lines.map((p) => [...p.childNodes].map((n) => n.nodeName + ':' + n.textContent)),
    rubies: lines.map((p) => [...p.querySelectorAll('ruby.py')].map((r) => [r.firstChild.textContent,
      r.querySelector('rt').textContent])),
    py: new URLSearchParams(location.hash.slice(1)).get('py'),
    row: !document.getElementById('pinyin-row').hidden, chip: document.getElementById('pinyin-chip').textContent,
    pressed: document.getElementById('pinyin-chip').getAttribute('aria-pressed'),
    sideways: document.documentElement.scrollWidth > document.documentElement.clientWidth};
})()"""
# Each chord of the song's lines and the character under it: the chord's box, the character's (its glyph, by a
# Range), and its column's (the ruby with its reading, or the character alone) and reading's when it has one.
CHORDS = """(() => {
  const box = (r) => ({left: r.left, right: r.right, top: r.top, bottom: r.bottom, width: r.width});
  const glyph = (node) => { const r = document.createRange(); r.setStart(node, 0);
    r.setEnd(node, node.data.codePointAt(0) > 0xffff ? 2 : 1); return box(r.getBoundingClientRect()); };
  return [...document.querySelectorAll('#sheet section.sec .s')].map((s) => {
    const y = s.querySelector('.y'), ruby = y.firstChild && y.firstChild.nodeName === 'RUBY' ? y.firstChild : null;
    const text = ruby ? ruby.firstChild : y.firstChild;
    return {chord: s.querySelector('.c').textContent, c: box(s.querySelector('.c').getBoundingClientRect()),
      char: text ? text.data[0] : '', glyph: text ? glyph(text) : null,
      column: box((ruby || y).getBoundingClientRect()),
      reading: ruby ? box(ruby.querySelector('rt').getBoundingClientRect()) : null,
      line: [...document.querySelectorAll('#sheet section.sec > p.l')].indexOf(s.closest('p.l'))};
  });
})()"""


def chords(b: Browser) -> list[dict]:
    return b.js(CHORDS)


def han(text: str) -> list[str]:
    return [c for c in text if re.match(r"[一-鿿]", c)]


def turn_on(b: Browser) -> None:
    b.click("#more")
    b.click("#pinyin-chip")
    assert b.wait("document.querySelector('#sheet ruby.py') !== null")


def places(seen: list[dict]) -> list[tuple[str, int]]:
    """The character each chord is over, and its line, chord by chord."""
    return [(c["char"], c["line"]) for c in seen]


def assert_aligned(off: list[dict], on: list[dict]) -> None:
    """Every chord over the character it sits over without pinyin: off, its left edge at the character's; on, at
    its column's (the character and its reading, centred one over the other), above the reading, above the
    character."""
    assert places(on) == places(off)
    for c in off:
        assert abs(c["c"]["left"] - c["glyph"]["left"]) <= 1, c
    assert_over_their_characters(on)


def assert_over_their_characters(on: list[dict]) -> None:
    """With pinyin, each chord at its column's left, above the reading, above the character, a row's chords at one
    height (``assert_aligned``)."""
    for c in on:
        if c["reading"] is None:  # a comma, a word of letters: as without pinyin
            assert abs(c["c"]["left"] - c["glyph"]["left"]) <= 1, c
            continue
        column, glyph, reading = c["column"], c["glyph"], c["reading"]
        assert abs(c["c"]["left"] - column["left"]) <= 1, c
        assert column["left"] - 0.5 <= glyph["left"] and glyph["right"] <= column["right"] + 0.5, c
        middle = (glyph["left"] + glyph["right"]) / 2
        assert abs(middle - (column["left"] + column["right"]) / 2) <= 1, c  # the character centred under it
        assert abs(middle - (reading["left"] + reading["right"]) / 2) <= 1, c  # and its reading over it
        assert c["c"]["bottom"] <= reading["top"] + 1 and reading["bottom"] <= glyph["top"] + 1, c
    rows: dict[tuple[int, int], list[dict]] = {}
    for c in on:  # the chords of a row of a line, one above the other row's: all at one height
        rows.setdefault((c["line"], round(c["glyph"]["bottom"])), []).append(c)
    for row in rows.values():
        assert max(c["c"]["top"] for c in row) - min(c["c"]["top"] for c in row) <= 1, row


@in_chromium
def test_off_at_first_and_on_each_chinese_character_has_its_reading_over_it(tmp_path):
    with open_viewer(tmp_path, written(tmp_path, ZH), **DESKTOP) as b:
        before = b.js(DRAWN)
        turn_on(b)
        on = b.js(DRAWN)
        b.click("#pinyin-chip")
        assert b.wait("document.querySelector('#sheet ruby.py') === null")
        off = b.js(DRAWN)
    assert all(r == [] for r in before["rubies"]) and before["py"] is None
    assert before["chip"] == "Pinyin" and before["pressed"] == "false"
    expected = readings(ZH_LINES)
    for line, rubies, read in zip(ZH_LINES, on["rubies"], expected):
        assert [c for c, _ in rubies] == han(line)  # a ruby each Chinese character, none for the rest
        assert [r for _, r in rubies] == [r for r in (read or []) if r]
    assert on["rubies"][4] == [["长", "cháng"], ["城", "chéng"], ["和", "hé"], ["成", "chéng"], ["长", "zhǎng"]]
    assert on["row"] and on["chip"] == "Pinyin" and on["pressed"] == "true" and on["py"] == "1"
    assert off["lines"] == before["lines"] and off["py"] is None  # the words as the page wrote them, again


@in_chromium
def test_on_a_phone_the_row_is_a_thumbs_target_and_copied_lyrics_leave_the_readings_out(tmp_path):
    with open_viewer(tmp_path, written(tmp_path, ZH), **PHONE) as b:
        copy = ("(() => { const line = document.querySelectorAll('#sheet section.sec > p.l')[%d];"
                " getSelection().selectAllChildren(line); return getSelection().toString(); })()")
        before = [b.js(copy % n) for n in (0, 2, 4)]
        turn_on(b)
        b.js("document.getElementById('pinyin-row').scrollIntoView({block: 'center'})")
        small = b.js(small_targets(":not(#pinyin-chip)"))
        copied = [b.js(copy % n) for n in (0, 2, 4)]
    assert small == []
    assert [re.sub(r"\s", "", text) for text in copied] == [re.sub(r"\s", "", text) for text in before]
    assert copied[2].split() == ["F", "长", "城", "和", "C", "成", "长"]  # no reading in it


@in_chromium
def test_a_sheet_without_chords_has_no_settings_but_shows_the_readings_another_page_turned_on(tmp_path):
    cho = "{title: 合成}\n{artist: 示例}\n{comment: Verse}\n没有和弦\n"
    with open_viewer(tmp_path, written(tmp_path, cho) + "#py=1", **PHONE) as b:
        seen = [b.js(DRAWN), b.js("document.getElementById('more').hidden")]
    assert seen[0]["rubies"] == [[["没", "méi"], ["有", "yǒu"], ["和", "hé"], ["弦", "xián"]]] and seen[1]


@in_chromium
def test_a_sheet_without_chinese_shows_no_pinyin_row_and_draws_none(tmp_path):
    cho = "{title: T}\n{artist: A}\n{comment: Verse}\n[C]la la [G]la\n"
    with open_viewer(tmp_path, written(tmp_path, cho) + "#py=1", **DESKTOP) as b:
        b.click("#more")
        seen = b.js("[document.getElementById('pinyin-row').hidden, document.querySelectorAll('ruby').length,"
                    " new URLSearchParams(location.hash.slice(1)).get('py')]")
    assert seen == [True, 0, "1"]  # the setting kept for the next sheet with Chinese


@pytest.mark.parametrize("size", [DESKTOP, PHONE], ids=["1280", "390"])
@in_chromium
def test_each_chord_stays_over_its_character_with_the_reading_between_them(tmp_path, size):
    with open_viewer(tmp_path, written(tmp_path, LONG), **size) as b:
        off = chords(b)
        turn_on(b)
        b.click("#panel [data-close]")
        on = chords(b)
        seen = b.js(DRAWN)
    assert_aligned(off, on)
    assert [c["chord"] for c in on] == [c["chord"] for c in off]
    assert not seen["sideways"]
    if size is PHONE:  # the long line wraps, between columns: each chord with its reading and its character
        assert len({round(c["glyph"]["bottom"]) for c in on if c["line"] == 0}) > 1


@in_chromium
def test_transposing_and_numerals_change_the_chords_never_the_readings(tmp_path):
    with open_viewer(tmp_path, written(tmp_path, LONG) + "#py=1", **DESKTOP) as b:
        before = [b.js(DRAWN), chords(b)]
        b.click("#t-up")
        b.click("#t-up")
        moved = [b.js(DRAWN), chords(b)]
        b.click("#more")
        b.click("#names button:nth-child(2)")  # Chords + numerals
        named = [b.js(DRAWN), chords(b)]
    assert before[0]["rubies"] == moved[0]["rubies"] == named[0]["rubies"] and before[0]["rubies"][0]
    assert [c["chord"] for c in moved[1]][:3] == ["D", "A", "Bm"]
    for seen in (before[1], moved[1], named[1]):
        assert places(seen) == places(before[1])
        assert_over_their_characters(seen)


@in_chromium
def test_the_choice_is_kept_across_a_reload_and_for_every_other_sheet(tmp_path):
    url, other = written(tmp_path, ZH), written(tmp_path, LONG, name="Other")
    with open_viewer(tmp_path, url, **DESKTOP) as b:
        turn_on(b)
        reload(b)
        reloaded = b.js(DRAWN)
        reopen(b, other)
        elsewhere = b.js(DRAWN)
        b.click("#more")
        b.click("#pinyin-chip")  # off, here: off everywhere
        reopen(b, url)
        back = b.js(DRAWN)
    assert reloaded["rubies"][0] and reloaded["pressed"] == "true"
    assert elsewhere["rubies"][0] and elsewhere["pressed"] == "true"
    assert all(r == [] for r in back["rubies"]) and back["pressed"] == "false" and back["py"] is None


@in_chromium
def test_reset_everything_hides_the_pinyin(tmp_path):
    url = written(tmp_path, ZH)
    with open_viewer(tmp_path, url, **DESKTOP) as b:
        turn_on(b)
        b.click("#reset-all")
        reset = b.js(DRAWN)
        reopen(b, url)
        kept = b.js(DRAWN)
    for seen in (reset, kept):
        assert all(r == [] for r in seen["rubies"]) and seen["py"] is None and seen["pressed"] == "false"


@in_chromium
def test_served_in_its_sandbox_with_no_storage_the_address_keeps_it(tmp_path):
    sheet = "/Artist/Title/sheet.html"
    with served({sheet: (build_viewer(ZH), viewer_csp)}) as site, \
            open_viewer(tmp_path, site + sheet, **DESKTOP) as b:
        sandboxed = [b.js("origin"), b.js(STORAGE)]
        turn_on(b)
        reload(b)
        reloaded = b.js(DRAWN)
    assert sandboxed == ["null", False]
    assert reloaded["py"] == "1" and reloaded["rubies"][0] and reloaded["pressed"] == "true"


@in_chromium
def test_the_next_version_opens_with_the_pinyin_too(tmp_path):
    pages = folder(tmp_path, WONDERWALL)
    with open_viewer(tmp_path, pages["sheet.html"].as_uri() + "#fs=24&py=1") as b:
        following = b.js("document.getElementById('ver-next').getAttribute('href')")
    assert following == "version-39144.html#fs=24&py=1"


@in_chromium
def test_a_served_songbook_carries_it_from_song_to_song_and_through_its_contents(tmp_path):
    songs = [BookSong("合成", "示例", cho=ZH, id="aaaa"),
             BookSong("Other", "A", cho="{title: Other}\n{artist: A}\n{comment: V}\n[C]la la\n", id="bbbb"),
             BookSong("长", "示例", cho=LONG, id="cccc")]
    page = "/_songbooks/Campfire/songbook.html"
    contents = "document.documentElement?.dataset.view === 'contents'"
    with served({page: (build_songbook("Campfire", songs), songbook_csp)}) as site, \
            open_viewer(tmp_path, site + page + "#song-1", **DESKTOP) as b:
        turn_on(b)
        one = [b.js(DRAWN), b.js("location.hash")]
        follow(b, "document.querySelector('#song-1 a[rel=next]').click()")
        two = [b.js(DRAWN), b.js("location.hash")]
        follow(b, "document.querySelector('#song-2 a[rel=next]').click()")
        three = [b.js(DRAWN), b.js("location.hash")]
        follow(b, "document.querySelector('#song-3 a[href=\"#contents\"]').click()", contents)
        listed = b.js("location.hash")
        follow(b, "document.querySelector('#contents a[href=\"#song-1\"]').click()")
        back = [b.js(DRAWN), b.js("location.hash")]
    assert one[0]["rubies"][0] and one[1] == "#song-1=&py=1"
    assert two[1] == "#song-2=&py=1" and not two[0]["row"]  # no Chinese here: no row, the setting goes on
    assert three[1] == "#song-3=&py=1" and three[0]["rubies"][0] and three[0]["pressed"] == "true"
    assert listed == "#contents=&py=1"
    assert back[1] == "#song-1=&py=1" and back[0]["rubies"][0]


@in_chromium
def test_in_a_songbook_from_a_file_it_stays_on_from_song_to_song(tmp_path):
    songs = [BookSong("合成", "示例", cho=ZH, id="aaaa"), BookSong("长", "示例", cho=LONG, id="cccc")]
    path = tmp_path / "Library" / "_songbooks" / "Campfire" / "songbook.html"
    path.parent.mkdir(parents=True)
    path.write_text(build_songbook("Campfire", songs), encoding="utf-8")
    with open_viewer(tmp_path, path.as_uri() + "#song-1", **PHONE) as b:
        turn_on(b)
        to_song(b, 2)
        two = b.js(DRAWN)
        on = chords(b)
    assert two["rubies"][0] and two["pressed"] == "true"
    assert all(c["reading"] is not None or not han(c["char"]) for c in on)


@pytest.mark.parametrize("scheme", ["light", "dark"])
@in_chromium
def test_the_reading_is_muted_smaller_and_legible_in_either_theme(tmp_path, scheme):
    look = """(() => {
      const rt = document.querySelector('#sheet ruby.py rt'), base = document.querySelector('#sheet ruby.py');
      const s = getComputedStyle(rt), page = getComputedStyle(document.body);
      return {color: s.color, muted: getComputedStyle(document.documentElement).getPropertyValue('--muted').trim(),
              size: parseFloat(s.fontSize), base: parseFloat(getComputedStyle(base).fontSize), bg: page.backgroundColor};
    })()"""
    with open_viewer(tmp_path, written(tmp_path, ZH) + "#py=1", **PHONE) as b:
        b.send("Emulation.setEmulatedMedia", features=[{"name": "prefers-color-scheme", "value": scheme}])
        seen = b.js(look)
    assert seen["color"] == rgb(seen["muted"])
    assert 10 <= seen["size"] < seen["base"]  # smaller than the characters, legible on a phone
    assert contrast(seen["color"], seen["bg"]) >= 4.5, seen


@in_chromium
def test_printed_the_page_shows_what_the_screen_shows(tmp_path):
    shown = "[...document.querySelectorAll('#sheet ruby.py rt')].filter((rt) => rt.getClientRects().length).length"
    with open_viewer(tmp_path, written(tmp_path, ZH) + "#py=1", **DESKTOP) as b:
        screen = b.js(shown)
        b.send("Emulation.setEmulatedMedia", media="print")
        printed = [b.js(shown), b.js("getComputedStyle(document.querySelector('#sheet rt')).color")]
    assert screen == printed[0] == sum(len(han(line)) for line in ZH_LINES)
    assert contrast(printed[1], "rgb(255, 255, 255)") >= 4.5  # grey on paper


def rgb(color: str) -> str:
    """A #rrggbb colour as getComputedStyle writes it."""
    value = color.lstrip("#")
    return "rgb({}, {}, {})".format(*(int(value[i:i + 2], 16) for i in (0, 2, 4)))


def contrast(one: str, two: str) -> float:
    """WCAG's contrast ratio of two rgb() colours."""
    def lum(color: str) -> float:
        parts = [int(v) / 255 for v in re.findall(r"\d+", color)[:3]]
        lin = [p / 12.92 if p <= 0.03928 else ((p + 0.055) / 1.055) ** 2.4 for p in parts]
        return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]
    a, b = sorted((lum(one), lum(two)), reverse=True)
    return (a + 0.05) / (b + 0.05)
