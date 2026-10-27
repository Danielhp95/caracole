"""The sheet viewer's Chinese characters: a sheet's Chinese in Simplified characters, or in Traditional ones once
chosen, whichever it is written in. Converted at render time, word by word (viewer/hanzi.py, OpenCC), carried in
the page's data (``hanzi``), swapped in by viewer.js from the settings' row above Pinyin (Simplified at first), and
kept for every page at once, as the Pinyin is.

The conversions are OpenCC's: what it writes is what these tests write (头发 頭髮, 睡著 睡着).
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import pytest

from caracole.viewer import build_viewer, hanzi, viewer_csp
from caracole.viewer.book import BookSong, build_songbook, songbook_csp
from caracole.viewer.pinyin import readings

from conftest import subprocess_pythonpath
from helpers.browser import Browser, in_chromium
from helpers.version_pages import WONDERWALL, folder
from helpers.viewer_pages import viewer as open_viewer, written
from test_viewer_necks import STORAGE, follow, reload, reopen, served, to_song
from test_viewer_pinyin import BANMA, BANMA_READ, BANMA_TRADITIONAL, assert_over_their_characters, data_of

# 宋冬野's 斑马斑马 as UG has it in Traditional characters, and the same lines in Simplified ones.
TRADITIONAL = ["斑馬斑馬 你不要睡著啦", "再給我看看你受傷的尾巴", "我只想掀起你的頭髮", "我是只會歌唱的傻瓜"]
SIMPLIFIED = ["斑马斑马 你不要睡着啦", "再给我看看你受伤的尾巴", "我只想掀起你的头发", "我是只会歌唱的傻瓜"]


# --- the conversions --------------------------------------------------------------------------------


def test_a_traditional_sheet_is_shown_in_simplified_characters_and_in_traditional_as_written():
    shown = hanzi.scripts(TRADITIONAL)
    assert shown["simplified"] == dict(zip(TRADITIONAL, SIMPLIFIED))
    # As written, even where OpenCC's conversion into Traditional would change it (是只會: 是隻會).
    assert shown["traditional"] == {}


def test_a_simplified_sheet_is_shown_in_traditional_characters_in_taiwans_standard():
    shown = hanzi.scripts(SIMPLIFIED[:3])
    assert shown["simplified"] == {}
    assert shown["traditional"] == dict(zip(SIMPLIFIED[:3], TRADITIONAL[:3]))  # 睡着 in Taiwan's 睡著


def test_simplified_into_traditional_is_one_to_many_word_by_word():
    texts = ["头发 发现", "后来 皇后", "干净 干活 干涉", "一只猫 我只想你"]
    assert [hanzi.scripts(texts)["traditional"][t] for t in texts] == [
        "頭髮 發現", "後來 皇后", "乾淨 幹活 干涉", "一隻貓 我只想你"]


def test_traditional_into_simplified_reads_each_word_too():
    # 著 is 着 where Taiwan writes it so (睡著, 看著), and stays in a word Simplified writes with it (著名, 顯著);
    # 乾 is 干 in 乾淨 and stays in 乾坤; the OpenCC standard's variants (爲, 裏) are read as Taiwan's are.
    texts = ["睡著 看著 著名 顯著", "乾淨 乾坤", "為什麼 爲什麼 裡面 裏面"]
    assert [hanzi.scripts(texts)["simplified"][t] for t in texts] == [
        "睡着 看着 著名 显著", "干净 乾坤", "为什么 为什么 里面 里面"]


def test_the_script_a_sheet_is_written_in_is_the_one_most_of_its_own_characters_are():
    # A Simplified sheet with a stray Traditional character is Simplified: in Traditional, its lines are converted;
    # in Simplified, its stray character is.
    shown = hanzi.scripts(["我的头发", "你回来了", "这是個例子"])
    assert shown["traditional"] == {"我的头发": "我的頭髮", "你回来了": "你回來了", "这是個例子": "這是個例子"}
    assert shown["simplified"] == {"这是個例子": "这是个例子"}
    # And a Traditional sheet with a stray Simplified one is Traditional: as written in Traditional.
    shown = hanzi.scripts(["我的頭髮", "你回來了", "这是個例子"])
    assert shown["traditional"] == {}
    assert shown["simplified"] == {"我的頭髮": "我的头发", "你回來了": "你回来了", "这是個例子": "这是个例子"}


def test_a_text_the_same_in_either_script_or_without_chinese_has_no_conversion():
    assert hanzi.scripts(["你好", "la la la", "", "Hello 世界，ok 2!"]) == {"simplified": {}, "traditional": {}}
    assert hanzi.scripts(["la la", ""]) == {"simplified": {}, "traditional": {}}


def test_letters_digits_spaces_and_punctuation_stay_where_they_are():
    shown = hanzi.scripts(["Hello 头发，ok 2! [x]"])
    assert shown["traditional"] == {"Hello 头发，ok 2! [x]": "Hello 頭髮，ok 2! [x]"}


def test_a_conversion_keeps_the_texts_length_a_character_for_a_character():
    texts = [*TRADITIONAL, *SIMPLIFIED, "头发 发现 后来 皇后 干净 干活 干涉 𠀀里面", "鬱鬱蔥蔥 臺灣 裡面 著名"]
    for text in texts:
        for shown in (hanzi.scripts([text])["simplified"], hanzi.scripts([text])["traditional"]):
            assert all(len(after) == len(before) for before, after in shown.items()), shown


def test_a_conversion_that_changed_the_length_is_made_again_a_character_at_a_time(monkeypatch):
    # Never seen from OpenCC, whose phrases are each as long as their conversion: a text converted longer or shorter
    # is converted a character at a time, and a character converted into more or fewer than one stays as written.
    real = hanzi._converter

    def converter(config):
        convert = real(config)
        return lambda text: (convert(text) + "啊" if len(text) > 1 else {"发": "發髮"}.get(text, convert(text)))

    monkeypatch.setattr(hanzi, "_converter", converter)
    assert hanzi.scripts(["我的头发 后来", "回来"])["traditional"] == {"我的头发 后来": "我的頭发 後來", "回来": "回來"}


# --- in the page's data ------------------------------------------------------------------------------

# A sheet in Traditional characters: notes before the song (folded after two lines), a section's label in Chinese,
# a line of text, a tab with a word of Chinese.
SHEET = """{title: 斑馬斑馬}
{artist: 宋冬野}
{key: G}
作詞：宋冬野
作曲：宋冬野
來自網絡
{comment: 主歌}
[C]斑馬[D]斑[Bm]馬 你[Em]不要睡著啦
[C]再給[D]我看[G]看你受傷的尾巴
沒有和弦的一行

{comment: Chorus}
[C]我只[D]想掀[Em]起你的頭髮
{start_of_tab}
e|---0---| 頭髮
{end_of_tab}
"""


def test_the_data_carries_every_text_the_sheet_writes_in_simplified_characters():
    data = data_of(build_viewer(SHEET))
    simplified = data["hanzi"]["simplified"]
    assert simplified["作詞：宋冬野"] == "作词：宋冬野" and simplified["來自網絡"] == "来自网络"
    assert simplified["斑馬斑馬 你不要睡著啦"] == "斑马斑马 你不要睡着啦"
    assert simplified["再給我看看你受傷的尾巴"] == "再给我看看你受伤的尾巴"
    assert simplified["沒有和弦的一行"] == "没有和弦的一行"
    assert simplified["我只想掀起你的頭髮"] == "我只想掀起你的头发"
    assert simplified["e|---0---| 頭髮"] == "e|---0---| 头发"
    assert "主歌" not in simplified and "作曲：宋冬野" not in simplified  # the same in either script
    assert data["hanzi"]["traditional"] == {}


def test_a_sections_label_and_the_notes_peek_are_converted_too():
    cho = "{title: T}\n{artist: A}\n說明一\n說明二\n說明三\n{comment: 副歌（重複）}\n[C]頭髮\n"
    simplified = data_of(build_viewer(cho))["hanzi"]["simplified"]
    assert simplified["副歌（重複）"] == "副歌（重复）"
    assert {"說明一": "说明一", "說明二": "说明二", "說明三": "说明三"}.items() <= simplified.items()


def test_a_sheet_without_chinese_lyrics_has_no_conversions_and_no_row_shown():
    html = build_viewer("{title: 斑马}\n{artist: A}\n{comment: Verse}\n[Am]la la [F]la\n")
    assert "hanzi" not in data_of(html)
    assert re.search(r'<div id="hanzi-row" hidden>', html)  # the script shows it for a sheet with Chinese


def test_a_japanese_sheet_has_none_its_kanji_are_no_chinese():
    assert "hanzi" not in data_of(build_viewer("{title: T}\n{artist: A}\n{comment: V}\n[C]夢を見た\n"))


def test_the_settings_have_a_two_way_choice_right_above_the_pinyin():
    html = build_viewer(SHEET)
    found = re.search(r'<div id="hanzi-row" hidden>(.*?)</div></div>\n<div id="pinyin-row"', html, re.S)
    assert found, "the row, hidden until the script shows it, right above Pinyin's"
    row = found.group(1)
    assert '<div class="seg" id="hanzi" role="group" aria-label="Chinese characters">' in row
    buttons = re.findall(r'<button type="button" id="(hanzi-[st])" aria-pressed="(\w+)" aria-controls="sheet">', row)
    assert buttons == [("hanzi-s", "true"), ("hanzi-t", "false")]  # Simplified first, and at first
    assert re.sub(r"<[^>]+>", "", row).split() == ["Simplified", "简体", "Traditional", "繁體"]


def test_a_songbooks_songs_each_carry_their_own():
    songs = [BookSong("斑馬", "宋冬野", cho=SHEET, id="aaaa"),
             BookSong("Other", "A", cho="{title: Other}\n{artist: A}\n[C]la la\n", id="bbbb"),
             BookSong("斑马", "宋冬野", cho="{title: 斑马}\n{artist: 宋冬野}\n[C]我的头发\n", id="cccc")]
    html = build_songbook("Campfire", songs)
    assert data_of(html, "data-1")["hanzi"] == data_of(build_viewer(SHEET))["hanzi"]
    assert "hanzi" not in data_of(html, "data-2")
    assert data_of(html, "data-3")["hanzi"] == {"simplified": {}, "traditional": {"我的头发": "我的頭髮"}}
    assert 'id="hanzi-row"' in html


def test_the_characters_in_an_address_are_no_part_of_a_version():
    # An export or Make this my version reads the viewer's address: trad=1 there plays the song no otherwise.
    from caracole.viewer.version import version_from_query

    assert version_from_query("#t=2&mode=dorian&capo=3&trad=1") == version_from_query("#t=2&mode=dorian&capo=3")


# --- what the pages are made from ----------------------------------------------------------------------


def test_the_viewer_is_made_from_the_hanzi_module_and_openccs_dictionaries(monkeypatch):
    from caracole.viewer import page

    assert page.HERE / "hanzi.py" in page.BUILD_FILES
    page.build_version.cache_clear()
    try:
        before = page.build_version()
        monkeypatch.setattr(page, "_opencc_version", lambda: "0.0.1")
        page.build_version.cache_clear()
        assert page.build_version() != before  # an upgrade of OpenCC may convert a character otherwise
    finally:
        page.build_version.cache_clear()


@pytest.mark.slow
def test_opencc_is_loaded_only_for_a_sheet_with_chinese():
    code = (
        "import sys; import caracole.cli; from caracole.viewer import build_viewer, page\n"
        "page.build_version()\n"
        "build_viewer('{title: 斑馬}\\n{artist: A}\\n[C]la la\\n')\n"
        "print('opencc' in sys.modules)\n"
        "build_viewer('{title: T}\\n{artist: A}\\n[C]頭髮\\n')\n"
        "print('opencc' in sys.modules)\n"
    )
    src = Path(__file__).resolve().parents[1] / "src"
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True,
                         env={"PYTHONPATH": subprocess_pythonpath(src)})
    assert out.stdout.split() == ["False", "True"]


# --- in a browser --------------------------------------------------------------------------------------

DESKTOP = {"width": 1280, "height": 800, "mobile": False}
PHONE = {"width": 390, "height": 844, "mobile": True}

# What the sheet shows in its words: each line's (its columns' text, a ruby's character without its reading, no
# chord), each section's label (without the progression the numerals name), each tab's and the notes' peek; and
# the row, its two segments, the address's trad and the sheet's language.
TEXT = """const text = (el) => [...el.childNodes].map((n) => n.nodeType === 3 ? n.data
    : n.nodeName === 'RT' || n.nodeName === 'BR' || n.matches('.c, .m') ? '' : text(n)).join('');"""
SHOWN = """(() => {
  """ + TEXT + """
  const sheet = document.getElementById('sheet'), all = (s) => [...sheet.querySelectorAll(s)];
  return {lines: all('p.l:not(.chords)').map(text), labels: all('h2.lbl').map((h) => h.firstChild.data),
    tabs: all('pre.tab').map(text), peek: all('.peek').map((p) => [...p.childNodes].filter((n) => n.nodeType === 3)
      .map((n) => n.data)),
    rubies: all('ruby.py').map((r) => [r.firstChild.textContent, r.querySelector('rt').textContent]),
    row: !document.getElementById('hanzi-row').hidden,
    pressed: ['hanzi-s', 'hanzi-t'].map((id) => document.getElementById(id).getAttribute('aria-pressed')),
    trad: new URLSearchParams(location.hash.slice(1)).get('trad'), lang: sheet.lang};
})()"""
# A Simplified sheet: a long line, which wraps on a phone, with a chord over a comma and one over a word of letters.
LONG = ("{title: 合成}\n{artist: 示例}\n{key: C}\n{comment: Verse}\n"
        "[C]这是一个[G]很长很长的[Am]合成例子[F]，我们[C]看它怎么[G]换行[Am]ok [F]然后继续唱下去\n"
        "[C]你的[G]头发[Am]后来\n")
LONG_LINES = ["这是一个很长很长的合成例子，我们看它怎么换行ok 然后继续唱下去", "你的头发后来"]
LONG_TRADITIONAL = ["這是一個很長很長的合成例子，我們看它怎麼換行ok 然後繼續唱下去", "你的頭髮後來"]


def choose(b: Browser, segment: str, shown: str) -> dict:
    """The settings opened, if they aren't, ``segment`` pressed (``#hanzi-s``, ``#hanzi-t``), and what the sheet
    shows once its words hold ``shown``."""
    if b.js("document.getElementById('panel').hidden"):
        b.click("#more")
    b.click(segment)
    assert b.wait(f"(() => {{ {TEXT} return text(document.getElementById('sheet')); }})().includes({shown!r})")
    return b.js(SHOWN)


def written_texts(cho: str) -> dict:
    """What the sheet writes in its words, as the page wrote it: SHOWN's, read from the page alone."""
    html = build_viewer(cho)
    article = re.search(r'<article[^>]*id="sheet"[^>]*>(.*?)</article>', html, re.S).group(1)
    lines = re.findall(r'<p class="l(?: legend)?">(.*?)</p>', article)
    strip = lambda s: re.sub(r"<b [^>]*>.*?</b>|<i [^>]*>.*?</i>|<[^>]+>", "", s)  # noqa: E731
    from html import unescape
    return {"lines": [unescape(strip(line)) for line in lines],
            "labels": [unescape(s) for s in re.findall(r'<h2 class="lbl">(.*?)</h2>', article)],
            "tabs": [unescape(s) for s in re.findall(r'<pre class="tab">(.*?)</pre>', article, re.S)],
            "peek": [[unescape(s) for s in p.split("<br>")]
                     for p in re.findall(r'<span class="peek">(.*?)</span>', article)]}


def in_script(texts: dict, table: dict[str, str]) -> dict:
    """``texts`` (``written_texts``') each as ``table`` converts it, or as written."""
    return {"lines": [table.get(t, t) for t in texts["lines"]], "labels": [table.get(t, t) for t in texts["labels"]],
            "tabs": [table.get(t, t) for t in texts["tabs"]],
            "peek": [[table.get(t, t) for t in p] for p in texts["peek"]]}


def words_of(seen: dict) -> dict:
    return {name: seen[name] for name in ("lines", "labels", "tabs", "peek")}


@in_chromium
def test_a_traditional_sheet_shows_in_simplified_at_first_and_as_written_once_traditional_is_chosen(tmp_path):
    texts, table = written_texts(SHEET), data_of(build_viewer(SHEET))["hanzi"]["simplified"]
    with open_viewer(tmp_path, written(tmp_path, SHEET), **DESKTOP) as b:
        first = b.js(SHOWN)
        traditional = choose(b, "#hanzi-t", "斑馬")
        simplified = choose(b, "#hanzi-s", "斑马")
    assert words_of(first) == in_script(texts, table) == words_of(simplified)
    assert first["lines"][3] == "斑马斑马 你不要睡着啦" and first["labels"] == ["主歌", "Chorus"]
    assert first["tabs"] == ["e|---0---| 头发"] and first["peek"] == [["作词：宋冬野", "作曲：宋冬野"]]
    assert first["row"] and first["pressed"] == ["true", "false"] and first["trad"] is None
    assert first["lang"] == "zh-Hans"
    assert words_of(traditional) == texts  # as the page wrote it
    assert traditional["pressed"] == ["false", "true"] and traditional["trad"] == "1"
    assert traditional["lang"] == "zh-Hant"
    assert simplified["pressed"] == ["true", "false"] and simplified["trad"] is None


@in_chromium
def test_a_simplified_sheet_shows_as_written_at_first_and_in_traditional_once_chosen(tmp_path):
    with open_viewer(tmp_path, written(tmp_path, LONG), **PHONE) as b:
        first = b.js(SHOWN)
        traditional = choose(b, "#hanzi-t", "這是")
    assert first["lines"] == LONG_LINES and first["pressed"] == ["true", "false"]
    assert traditional["lines"] == LONG_TRADITIONAL and traditional["trad"] == "1"


@pytest.mark.parametrize("size", [DESKTOP, PHONE], ids=["1280", "390"])
@in_chromium
def test_each_chord_stays_over_its_character_and_each_reading_over_it_in_either_script(tmp_path, size):
    from test_viewer_pinyin import assert_aligned, chords, places, turn_on

    with open_viewer(tmp_path, written(tmp_path, LONG), **size) as b:
        off = chords(b)
        turn_on(b)
        on = [b.js(SHOWN), chords(b)]
        traditional = choose(b, "#hanzi-t", "這是")
        b.click("#panel [data-close]")
        on_traditional = chords(b)
        sideways = b.js("document.documentElement.scrollWidth > document.documentElement.clientWidth")
    assert_aligned(off, on[1])
    # The characters are Traditional now, each chord over the Traditional of the character it was over.
    to_traditional = dict(zip("".join(LONG_LINES), "".join(LONG_TRADITIONAL)))
    assert places(on_traditional) == [(to_traditional.get(c, c), n) for c, n in places(off)] != places(off)
    assert_over_their_characters(on_traditional)
    expected = readings(LONG_LINES)
    read = [r for line in expected for r in line if r]
    assert [r for _, r in on[0]["rubies"]] == read == [r for _, r in traditional["rubies"]]  # the same readings
    assert "".join(c for c, _ in traditional["rubies"]) == "".join(
        c for line in LONG_TRADITIONAL for c in line if re.match(r"[一-鿿]", c))
    assert not sideways


@in_chromium
def test_switching_with_the_pinyin_on_keeps_the_readings_and_changes_the_characters(tmp_path):
    cho = "{title: 斑馬}\n{artist: 宋冬野}\n{comment: Verse}\n[C]斑馬[D]斑[Bm]馬 你[Em]不要睡著啦\n"
    with open_viewer(tmp_path, written(tmp_path, cho) + "#py=1", **DESKTOP) as b:
        first = b.js(SHOWN)
        traditional = choose(b, "#hanzi-t", "斑馬")
        b.click("#pinyin-chip")
        assert b.wait("document.querySelector('#sheet ruby.py') === null")
        plain = b.js(SHOWN)
    assert first["rubies"] == [[c, r] for c, r in zip(BANMA, BANMA_READ) if r]
    assert traditional["rubies"] == [[c, r] for c, r in zip(BANMA_TRADITIONAL, BANMA_READ) if r]
    assert plain["lines"] == [BANMA_TRADITIONAL] and plain["rubies"] == []


@in_chromium
def test_the_choice_is_kept_across_a_reload_and_for_every_other_sheet(tmp_path):
    url, other = written(tmp_path, SHEET), written(tmp_path, LONG, name="Other")
    with open_viewer(tmp_path, url, **DESKTOP) as b:
        choose(b, "#hanzi-t", "斑馬")
        reload(b)
        reloaded = b.js(SHOWN)
        reopen(b, other)
        elsewhere = b.js(SHOWN)
        choose(b, "#hanzi-s", "这是")  # Simplified, here: Simplified everywhere
        reopen(b, url)
        back = b.js(SHOWN)
    assert reloaded["lines"][3] == "斑馬斑馬 你不要睡著啦" and reloaded["pressed"] == ["false", "true"]
    assert elsewhere["lines"] == LONG_TRADITIONAL and elsewhere["pressed"] == ["false", "true"]
    assert back["lines"][3] == "斑马斑马 你不要睡着啦" and back["pressed"] == ["true", "false"]
    assert back["trad"] is None


@in_chromium
def test_reset_everything_goes_back_to_simplified(tmp_path):
    url = written(tmp_path, SHEET)
    with open_viewer(tmp_path, url, **DESKTOP) as b:
        choose(b, "#hanzi-t", "斑馬")
        b.click("#reset-all")
        reset = b.js(SHOWN)
        reopen(b, url)
        kept = b.js(SHOWN)
    for seen in (reset, kept):
        assert seen["lines"][3] == "斑马斑马 你不要睡着啦" and seen["trad"] is None and seen["pressed"][0] == "true"


@in_chromium
def test_a_sheet_without_chinese_shows_no_row_and_keeps_the_choice_for_the_next(tmp_path):
    cho = "{title: T}\n{artist: A}\n{comment: Verse}\n[C]la la [G]la\n"
    with open_viewer(tmp_path, written(tmp_path, cho) + "#trad=1", **DESKTOP) as b:
        b.click("#more")
        seen = b.js(SHOWN)
    assert not seen["row"] and seen["lines"] == ["la la la"] and seen["trad"] == "1" and seen["lang"] == ""


@in_chromium
def test_served_in_its_sandbox_with_no_storage_the_address_keeps_it(tmp_path):
    sheet = "/Artist/Title/sheet.html"
    with served({sheet: (build_viewer(SHEET), viewer_csp)}) as site, \
            open_viewer(tmp_path, site + sheet, **DESKTOP) as b:
        sandboxed = [b.js("origin"), b.js(STORAGE)]
        choose(b, "#hanzi-t", "斑馬")
        reload(b)
        reloaded = b.js(SHOWN)
    assert sandboxed == ["null", False]
    assert reloaded["trad"] == "1" and reloaded["lines"][3] == "斑馬斑馬 你不要睡著啦"
    assert reloaded["pressed"] == ["false", "true"]


@in_chromium
def test_the_next_version_opens_in_traditional_too(tmp_path):
    pages = folder(tmp_path, WONDERWALL)
    with open_viewer(tmp_path, pages["sheet.html"].as_uri() + "#fs=24&py=1&trad=1") as b:
        following = b.js("document.getElementById('ver-next').getAttribute('href')")
    assert following == "version-39144.html#fs=24&py=1&trad=1"


@in_chromium
def test_a_served_songbook_carries_it_from_song_to_song_and_through_its_contents(tmp_path):
    songs = [BookSong("斑馬", "宋冬野", cho=SHEET, id="aaaa"),
             BookSong("Other", "A", cho="{title: Other}\n{artist: A}\n{comment: V}\n[C]la la\n", id="bbbb"),
             BookSong("合成", "示例", cho=LONG, id="cccc")]
    page = "/_songbooks/Campfire/songbook.html"
    contents = "document.documentElement?.dataset.view === 'contents'"
    with served({page: (build_songbook("Campfire", songs), songbook_csp)}) as site, \
            open_viewer(tmp_path, site + page + "#song-1", **DESKTOP) as b:
        choose(b, "#hanzi-t", "斑馬")
        one = [b.js(SHOWN), b.js("location.hash")]
        follow(b, "document.querySelector('#song-1 a[rel=next]').click()")
        two = [b.js(SHOWN), b.js("location.hash")]
        follow(b, "document.querySelector('#song-2 a[rel=next]').click()")
        three = [b.js(SHOWN), b.js("location.hash")]
        follow(b, "document.querySelector('#song-3 a[href=\"#contents\"]').click()", contents)
        listed = b.js("location.hash")
        follow(b, "document.querySelector('#contents a[href=\"#song-1\"]').click()")
        back = [b.js(SHOWN), b.js("location.hash")]
    assert one[1] == "#song-1=&trad=1" and one[0]["lines"][3] == "斑馬斑馬 你不要睡著啦"
    assert two[1] == "#song-2=&trad=1" and not two[0]["row"]  # no Chinese here: no row, the setting goes on
    assert three[1] == "#song-3=&trad=1" and three[0]["lines"] == LONG_TRADITIONAL
    assert three[0]["pressed"] == ["false", "true"]
    assert listed == "#contents=&trad=1"
    assert back[1] == "#song-1=&trad=1" and back[0]["lines"][3] == "斑馬斑馬 你不要睡著啦"


@in_chromium
def test_in_a_songbook_from_a_file_it_stays_from_song_to_song(tmp_path):
    songs = [BookSong("斑馬", "宋冬野", cho=SHEET, id="aaaa"), BookSong("合成", "示例", cho=LONG, id="cccc")]
    path = tmp_path / "Library" / "_songbooks" / "Campfire" / "songbook.html"
    path.parent.mkdir(parents=True)
    path.write_text(build_songbook("Campfire", songs), encoding="utf-8")
    with open_viewer(tmp_path, path.as_uri() + "#song-1", **PHONE) as b:
        first = b.js(SHOWN)
        choose(b, "#hanzi-t", "斑馬")
        to_song(b, 2)
        two = b.js(SHOWN)
    assert first["lines"][3] == "斑马斑马 你不要睡着啦"
    assert two["lines"] == LONG_TRADITIONAL and two["pressed"] == ["false", "true"]


@in_chromium
def test_the_row_is_a_segmented_control_like_the_chord_names_right_above_the_pinyin(tmp_path):
    from helpers.targets import small_targets

    look = """(() => {
      const box = (id) => { const r = document.getElementById(id).getBoundingClientRect(); return {top: r.top, bottom: r.bottom}; };
      const style = (el) => { const s = getComputedStyle(el);
        return [s.backgroundColor, s.borderTopColor, s.borderRadius, s.color, s.fontSize, s.fontWeight]; };
      const names = document.querySelector('#names'), mine = document.getElementById('hanzi');
      const on = (seg) => seg.querySelector('[aria-pressed=true]'), off = (seg) => seg.querySelector('[aria-pressed=false]');
      return {track: [style(names), style(mine)], on: [style(on(names)), style(on(mine))],
        off: [style(off(names)), style(off(mine))], row: box('hanzi-row'), pinyin: box('pinyin-row'),
        necks: document.getElementById('necks-row').hidden ? null : box('necks-row'),
        heights: [...mine.children].map((b) => b.getBoundingClientRect().height)};
    })()"""
    with open_viewer(tmp_path, written(tmp_path, SHEET), **PHONE) as b:
        b.click("#more")
        b.js("document.getElementById('hanzi-row').scrollIntoView({block: 'center'})")
        seen = b.js(look)
        small = b.js(small_targets(":not(#pinyin-chip)"))
    assert seen["track"][0] == seen["track"][1]  # the same sunken track
    assert seen["on"][0] == seen["on"][1] and seen["off"][0] == seen["off"][1]  # the same segments
    assert seen["row"]["bottom"] <= seen["pinyin"]["top"] + 1 and seen["pinyin"]["top"] - seen["row"]["bottom"] < 16
    assert all(44 <= h < 60 for h in seen["heights"])  # a thumb's, its words on one line
    assert small == []
