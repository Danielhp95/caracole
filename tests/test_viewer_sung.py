"""The song's timed lyrics matched to its sheet's lines (viewer/sung.py), so the page can light the line being sung:
each timed line the sheet line it is sung on, read top to bottom, a chorus the sheet writes once lit the first time
alone; and a song whose lyrics meet too few of its lines gets no highlight at all (build_viewer's data has no
``sung``)."""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

from caracole.viewer import build_viewer, page
from caracole.viewer.sheet import parse_sheet
from caracole.viewer.sung import LINE_MATCH, MAX_SECONDS, MIN_LINES, MIN_SHARE, line_key, sung_lines

from conftest import subprocess_pythonpath

DRAWN = ["Synthetic morning on the river", "", "Paper boats are drifting slowly", "Nobody counts the hours",
         "Sing it back to me", "Over the hills and home"]


def lrc(*lines: str, start: float = 8.0, gap: float = 4.0) -> list[tuple[float, str]]:
    return [(start + gap * k, text) for k, text in enumerate(lines)]


def data_of(html: str) -> dict:
    found = re.search(r'<script type="application/json" id="song">(.*?)</script>', html, re.S)
    assert found, "no song data"
    return json.loads(found.group(1))


def test_its_numbers_are_the_ones_the_phone_follows():
    assert (LINE_MATCH, MIN_SHARE, MIN_LINES, MAX_SECONDS) == (80, 0.5, 4, 86400)


def test_a_lines_key_is_its_words_and_a_chinese_lines_its_pinyin():
    assert line_key("Paper Boats, are drifting!") == "paper boats are drifting"
    assert line_key("斑馬，斑馬") == line_key("斑马 斑马") == line_key("斑 马 斑 马") == "ban ma ban ma"
    assert line_key("我们 love you") == "wo men love you"
    assert line_key("") == line_key("  ") == line_key("(…)") == ""


def test_each_timed_line_lights_the_sheet_line_it_is_sung_on():
    assert sung_lines(DRAWN, lrc(*[t for t in DRAWN if t])) == [
        [8000, 0], [12000, 2], [16000, 3], [20000, 4], [24000, 5]]


def test_a_chorus_the_sheet_writes_once_is_lit_the_first_time_alone():
    timed = lrc(DRAWN[0], DRAWN[2], DRAWN[3], DRAWN[4], DRAWN[5], DRAWN[4], DRAWN[5])
    assert [n for _, n in sung_lines(DRAWN, timed)] == [0, 2, 3, 4, 5, None, None]


def test_words_written_a_little_otherwise_still_match_another_line_never():
    timed = lrc(DRAWN[0], "Paper boats are driftin' slowly", "Something else entirely here", DRAWN[3], DRAWN[4])
    assert [n for _, n in sung_lines(DRAWN, timed)] == [0, 2, None, 3, 4]


def test_the_sheet_is_read_top_to_bottom_never_back():
    # A line sung after the ones below it on the sheet is no line of the sheet's: the light never goes back up.
    timed = lrc(DRAWN[0], DRAWN[2], DRAWN[3], DRAWN[4], DRAWN[5], DRAWN[0])
    assert [n for _, n in sung_lines(DRAWN, timed)] == [0, 2, 3, 4, 5, None]


def test_an_instrumental_break_lights_nothing():
    timed = lrc(DRAWN[0], DRAWN[2], "", DRAWN[3], DRAWN[4], DRAWN[5])
    assert sung_lines(DRAWN, timed) == [[8000, 0], [12000, 2], [16000, None], [20000, 3], [24000, 4], [28000, 5]]


def test_too_few_matches_give_no_highlight():
    five = [t for t in DRAWN if t]
    assert sung_lines(DRAWN, lrc(*five[:3], "Other words", "And more of them")) is None  # 3 lines: under MIN_LINES
    assert sung_lines(DRAWN, lrc(*five[:4])) is not None  # 4 of 5: enough
    ten = [*five, "A sixth line of words", "The seventh one here", "Eight is enough now", "Nine lines and counting",
           "Ten makes a long song"]
    assert sung_lines(ten, lrc(*ten[:4])) is None  # 4 of 10: under MIN_SHARE
    assert sung_lines(ten, lrc(*ten[:5])) is not None  # 5 of 10: half
    assert sung_lines(DRAWN, []) is None and sung_lines([], lrc(*five)) is None


def test_traditional_lyrics_meet_a_simplified_sheet():
    drawn = ["斑马 斑马 你不要睡着啦", "再给我看看你受伤的尾巴", "我不想去触碰你伤口的疤", "我只想掀起你的头发",
             "斑马 斑马 你回到了你的家"]
    timed = lrc("斑馬，斑馬，你不要睡著啦", "再給我看看你受傷的尾巴", "我不想去觸碰你傷口的疤", "我只想掀起你的頭髮",
                "斑馬，斑馬，你回到了你的家")
    assert [n for _, n in sung_lines(drawn, timed)] == [0, 1, 2, 3, 4]
    # and the other way round: a Traditional sheet, lyrics in Simplified characters
    assert [n for _, n in sung_lines([t for _, t in timed], lrc(*drawn))] == [0, 1, 2, 3, 4]


def test_chinese_meets_as_its_pinyin_spaced_or_written_with_other_characters():
    # A tabber's spaces between the characters, 妳 for 你, 著 for 着: as characters, fuzz.ratio says 69, 67, 75 and 60
    drawn = ["斑 马 斑 马 你 不 要 睡 着 啦", "你好吗", "你在哪里", "等着你回来", "我爱你"]
    timed = lrc("斑马斑马你不要睡着啦", "妳好嗎", "妳在哪裡", "等著妳回來", "我恨你")
    # ...and a word changed is another line: wo ai ni is no wo hen ni
    assert [n for _, n in sung_lines(drawn, timed)] == [0, 1, 2, 3, None]


def test_a_time_past_a_day_is_left_out():
    five = [t for t in DRAWN if t]
    timed = [(0.0, five[0]), (1.5, five[1]), (2.5, five[2]), (86399.999, five[3]), (86400.0, five[4]),
             (1e300, five[4])]
    assert sung_lines(DRAWN, timed) == [[0, 0], [1500, 2], [2500, 3], [86399999, 4]]


def test_a_time_is_rounded_to_the_millisecond_half_to_even():
    five = [t for t in DRAWN if t]
    timed = [(0.0005, five[0]), (0.0015, five[1]), (0.0025, five[2]), (12.3456, five[3]), (20.0, five[4])]
    assert [ms for ms, _ in sung_lines(DRAWN, timed)] == [round(s * 1000) for s, _ in timed]


SHEET = (
    "{title: Synthetic River}\n{artist: The Placeholders}\n"
    "A note before the song, by its tabber\n\n"  # the notes before the song: none of the drawn lines
    "{comment: Intro}\n[G] [D] [Em] [C]\n\n"  # a line of chords alone: a drawn line with no words
    "{comment: Verse}\n[G]Synthetic morning [D]on the river\n[Em]Paper boats are [C]drifting slowly\n\n"
    "{comment: Chorus}\n[C]Nobody counts the [G]hours\n[D]Sing it back to [Em]me\n[C]Over the hills and [G]home\n"
)


def test_build_viewer_puts_the_sung_lines_in_its_data_by_the_lines_pinyin_reads():
    drawn = page._drawn_lines(parse_sheet(SHEET))
    assert drawn[0] == "" and "A note before the song, by its tabber" not in drawn
    timed = lrc("Synthetic morning on the river", "Paper boats are drifting slowly", "Nobody counts the hours",
                "Sing it back to me", "Over the hills and home")
    data = data_of(build_viewer(SHEET, timed=timed, guitar=("guitar-1.gp5",)))
    assert data["sung"] == sung_lines(drawn, timed) == [[8000, 1], [12000, 2], [16000, 3], [20000, 4], [24000, 5]]
    assert list(data)[-2:] == ["guitarDownload", "sung"]  # the last member build_viewer adds
    assert "sung" not in data_of(build_viewer(SHEET))
    assert "sung" not in data_of(build_viewer(SHEET, timed=timed[:3]))  # too few lines


@pytest.mark.slow
def test_rapidfuzz_is_loaded_only_for_a_page_with_timed_lyrics_and_pypinyin_only_for_chinese():
    code = (
        "import sys; import caracole.cli; from caracole.viewer import build_viewer\n"
        "cho = '{title: T}\\n' + ''.join(f'[C]Line number {n} of words\\n' for n in range(5))\n"
        "print('\"sung\":[' in build_viewer(cho), 'rapidfuzz' in sys.modules, 'pypinyin' in sys.modules)\n"
        "timed = [(4.0 * n, f'Line number {n} of words') for n in range(5)]\n"
        "print('\"sung\":[' in build_viewer(cho, timed=timed), 'rapidfuzz' in sys.modules,"
        " 'pypinyin' in sys.modules)\n"
    )
    src = Path(__file__).resolve().parents[1] / "src"
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True,
                         env={"PYTHONPATH": subprocess_pythonpath(src)})
    assert out.stdout.split() == ["False", "False", "False", "True", "True", "False"]
