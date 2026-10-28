"""caracole.viewer.harptab: a harmonica tab as harptabs.com's tabbers write it, read for its page.

The fixtures (tests/fixtures/harptabs/tabs/) are the 14 tabs sampled from harptabs.com on 2026-10-27, as caracole keeps
them (``harmonica-N.txt``, the page's ``<pre>``), named by their ids: every line of holes and every section's name as
the tabber wrote it, every other line's letters made up (a vowel for a vowel, a consonant for a consonant, the case,
the spaces, the hyphens and the punctuation kept, so each word keeps its place and its syllables), addresses
example.com's, and the few lines that name a harp written again in made-up words that still do.

tests/fixtures/harptabs/spellings/ holds six tabs of the 146 a study read on 2026-10-28, made the same way (the words
inside a line of holes made up too, a harp's name kept), each for a spelling harptabs.com's key doesn't give: ``-3”``
(17941), dots as durations (26330), signs after the hole (10319), ``*`` a bend on a tab its page calls Diatonic
(9069), ``-b3`` (2136), ``(3)b`` (4765). ``CHIPS`` is each one's harp chip, as its page shows it.
"""

from __future__ import annotations

import re
import time
from collections import Counter
from pathlib import Path

import pytest

from caracole.viewer import harp
from caracole.viewer.harptab import (
    BRACKETS,
    DOTS,
    SIGNS_AFTER,
    Gap,
    Group,
    Hole,
    Prose,
    Row,
    Words,
    align,
    named_key,
    parse,
    scan,
    syllable_starts,
)

TABS = Path(__file__).parent / "fixtures" / "harptabs" / "tabs"
SAMPLED = sorted(p.stem for p in TABS.glob("*.txt"))
SPELLINGS = Path(__file__).parent / "fixtures" / "harptabs" / "spellings"
CHIPS = {"17941_if-i-die-young": "Diatonic", "26330_vergiss-es-nie-dass-du-lebst": "Diatonic",
         "10319_dirty-old-town-not-pogues": "Diatonic", "9069_twelve-bar-blues-boogie-different": "Diatonic",
         "2136_whole-lotta-love": "Diatonic", "4765_en-el-pais-de-la-libertad": None}


def tab(stem: str):
    return parse((TABS / f"{stem}.txt").read_text(encoding="utf-8"))


def spelled(stem: str, harp: str | None = "chip"):
    """A tab of tests/fixtures/harptabs/spellings/ read with its page's harp chip (``harp``: another, or None)."""
    return parse((SPELLINGS / f"{stem}.txt").read_text(encoding="utf-8"), harp=CHIPS[stem] if harp == "chip" else harp)


def labels(read) -> list[str]:
    """The holes of the rows a tab's page draws (``Row.trusted``)."""
    return [g.label() for r in read.rows() if r.trusted for g in r.groups if g.holes]


def dotted(read) -> bool:
    """Whether its single dots lengthen a hole (``DOTS``, each candidate's in a tab that writes a dot before a hole)."""
    return DOTS in read.reading.notation.symbols


def star_bends(read) -> bool:
    """Whether its ``*`` after a hole is a bend (``STAR_BENDS``, where the page's chip says Diatonic)."""
    star = read.reading.notation.meaning("*", "after")
    return star is not None and star.means == "bend"


def sung(stem: str) -> list[Row]:
    return [r for r in tab(stem).rows() if r.lyric is not None]


def holes_of(row: Row) -> list[tuple[list[str], str]]:
    """A row's parts as the page shows them: each place's holes, and the words sung from there."""
    return [([g.label() for g in groups], text) for groups, text in row.parts]


# --- the sample ---------------------------------------------------------------------------------------------------


def test_the_sample_is_the_fourteen_tabs():
    assert len(SAMPLED) == 14


def test_every_sampled_tab_is_read_the_private_notations_syllables_kept_as_its_words():
    assert [stem for stem in SAMPLED if not tab(stem).readable] == []
    # "(3)tue (3)te", its tabber's own: each "(3)" a draw, each syllable the tabber's, kept against its hole
    knockin = tab("29910_knockin-on-heavens-door")
    assert len(knockin.rows()) == 2 and knockin.missed == [] and knockin.convention == "brackets"
    first = knockin.rows()[0]
    assert [g.label() for g in first.groups] == ["−3", "mua", "−3", "do", "−3", "be", "−3", "pi", "−3", "va", "3", "−3",
                                                 "fa"]
    assert {g.kind for g in first.groups if not g.holes} == {"words"}


@pytest.mark.parametrize("stem", SAMPLED)
def test_every_hole_read_is_a_note_a_richter_harp_has(stem):
    holes = [h for r in tab(stem).rows() for g in r.groups for h in g.holes]
    assert holes
    assert all(harp.hole_note(0, h.hole, h.breath, h.bend, h.over) is not None for h in holes)


def test_nearly_every_sung_hole_finds_its_own_syllable():
    # Of the 886 holes over words in the sample, 805 snap to a syllable's start, 54 cut a word, 27 are held.
    placed = Counter()
    for stem in SAMPLED:
        for row in sung(stem):
            placed.update(row.placement)
    assert placed == Counter(snap=805, split=54, held=27)
    assert (placed["snap"] + placed["split"]) / sum(placed.values()) > 0.96


def test_what_each_sampled_tab_holds():
    rows = {stem: len(tab(stem).rows()) for stem in SAMPLED}
    assert rows == {"10228_whammer-jammer": 48, "124_heart-of-gold": 9, "1278_house-of-the-rising-sun": 4,
                    "164_blowin-in-the-wind": 11, "16_amazing-grace": 4, "1786_simple-man": 8, "1882_juke": 23,
                    "25_piano-man": 15, "28841_isnt-she-lovely": 8, "29910_knockin-on-heavens-door": 2,
                    "3489_wonderwall": 33, "53_love-me-do": 4, "588_hotel-california": 19, "99_free-bird": 22}
    instrumental = [s for s in SAMPLED if tab(s).rows() and not sung(s)]
    assert instrumental == ["10228_whammer-jammer", "124_heart-of-gold", "1882_juke", "28841_isnt-she-lovely",
                            "29910_knockin-on-heavens-door"]


def test_how_each_tab_writes_a_draw():
    # The notation each is read by (test_viewer_harptab_notation.py's), chosen by its score.
    conventions = {stem: tab(stem).convention for stem in SAMPLED}
    assert conventions.pop("124_heart-of-gold") == "letters"  # 4B 5D
    assert conventions.pop("28841_isnt-she-lovely") == "brackets"  # (5): no "-" anywhere
    assert conventions.pop("29910_knockin-on-heavens-door") == "brackets"
    assert set(conventions.values()) == {"signs"}
    assert all(tab(stem).reading.source == "guessed" for stem in SAMPLED)


def test_the_harp_a_tabs_words_name():
    assert tab("1882_juke").key == "A"  # "… so I use an A harp", though its page's chip says E
    assert tab("28841_isnt-she-lovely").key == "C"  # "ARMONICA EN C"
    assert tab("588_hotel-california").key is None


# --- the sampled tabs, read ----------------------------------------------------------------------------------------


def test_hotel_california_holes_over_their_syllables():
    rows = sung("588_hotel-california")
    assert holes_of(rows[0])[:6] == [(["8"], "At "), (["8"], "e "), (["8"], "nirs "), (["−8"], "lom-"),
                                     (["−8"], "udb "), (["−8"], "pavf-")]
    # "air--": the holes after the last syllable are held on it, a melisma
    assert holes_of(rows[1])[-1] == (["−8", "7", "−6"], "eiv--")
    assert rows[1].placement == Counter(snap=12, held=2)


def test_hotel_california_has_its_chorus_and_its_tabbers_line():
    read = tab("588_hotel-california")
    assert [(s.label, s.chorus) for s in read.sections] == [(None, False), ("chorus", True)]
    chorus = read.sections[1].items
    assert [type(i).__name__ for i in chorus[-3:]] == ["Prose", "Gap", "Row"]  # "next verses the same…", one more


def test_wonderwall_gives_its_next_verse_as_words_and_its_address_as_prose():
    read = tab("3489_wonderwall")
    assert read.notes == ["Tanrs elm Dibop vu Faoz Tenrislam"]  # "Words and Music by …", before the first row
    last = read.sections[-1]
    assert last.label == "Next verse"
    words = [i for i in last.items if isinstance(i, Words)]
    assert len(words) == 1 and len(words[0].lines) == 17
    assert [i.text for i in last.items if isinstance(i, Prose)] == ["Norsul ma dbo pevf", "https://example.com/watch?v=0"]
    # "an - y - bo - dy": spaced hyphens are no syllable's start, but each word is
    row = next(r for r in read.rows() if r.lyric and r.lyric.startswith("A vof'z"))
    assert [g for g, _ in holes_of(row)] == [["8"], ["9"], ["8"], ["9"], ["9"], ["−10"], ["9"], ["−8"], ["7"]]


def test_juke_is_played_alone_with_its_bends_written_before_the_hole():
    read = tab("1882_juke")
    assert all(r.lyric is None for r in read.rows())
    sixth = read.rows()[5]
    assert [g.label() for g in sixth.groups][:2] == ["−3", "−3′"]  # -3 b-3
    assert sixth.groups[1].holes == (Hole(3, "draw", 1),)
    assert read.notes == ["Made-up words in E, so I use an A harp"]


def test_heart_of_gold_writes_a_blow_and_a_draw_after_the_hole_and_holes_together_with_a_comma():
    read = tab("124_heart-of-gold")
    first = read.rows()[0]
    assert [g.label() for g in first.groups] == ["4", "6", "−5", "5", "−4", "4", "3"]
    together = read.rows()[6]
    assert together.groups[0].kind == "chord" and together.groups[0].label() == "(7 8)"


def test_isnt_she_lovely_reads_a_lone_hole_in_brackets_as_a_draw():
    first = tab("28841_isnt-she-lovely").rows()[0]
    assert [g.label() for g in first.groups] == ["5", "−5", "5", "−4", "4"]


def test_whammer_jammer_shakes_splits_and_deep_bends():
    groups = [g for r in tab("10228_whammer-jammer").rows() for g in r.groups]
    kinds = Counter(g.kind for g in groups)
    assert kinds["shake"] > 0 and kinds["split"] > 0 and kinds["chord"] > 0
    assert any(h.bend == 2 for g in groups for h in g.holes)  # -2bb
    split = next(g for g in groups if g.kind == "split")
    assert split.label() == "[−2 −5]"


def test_simple_man_names_its_sections_on_a_row_of_holes_and_holds():
    read = tab("1786_simple-man")
    assert [s.label for s in read.sections] == ["Intro", "FILL 1", "Verse"]
    intro = read.sections[0].items[0]
    assert intro.lyric is None and intro.groups[0].hold  # (-3) -------


# --- the spellings harptabs.com's key doesn't give, in the tabs that write them -------------------------------------


def lines_of_holes(stem: str) -> list[str]:
    """The fixture's lines that hold a number and no word, a verse's name ("[V1]") aside."""
    text = (SPELLINGS / f"{stem}.txt").read_text(encoding="utf-8")
    return [line for line in text.splitlines() if re.search(r"\d", line) and not re.search(r"[^\W\d_]{2,}", line)
            and not re.fullmatch(r"\s*\[\w+\]\s*", line)]


def test_if_i_die_young_bends_each_draw_it_marks_with_a_double_quote_a_whole_step():
    read = spelled("17941_if-i-die-young")
    text = (SPELLINGS / "17941_if-i-die-young.txt").read_text(encoding="utf-8")
    assert len(read.rows()) == len(lines_of_holes("17941_if-i-die-young")) == 61
    assert all(r.unknown == [] for r in read.rows())
    bent = [h for r in read.rows() for g in r.groups for h in g.holes if h.bend]
    assert bent == [Hole(3, "draw", 2)] * text.count("”") and len(bent) == 26  # -3”: −3′′, never −3


def test_a_tab_that_lengthens_its_holes_with_dots_reads_every_line_of_them():
    # "the dots extend the note": a dot before a hole (".5", ". 4") and after it ("5 .", "-5.")
    read = spelled("26330_vergiss-es-nie-dass-du-lebst")
    assert dotted(read) and read.readable
    assert len(read.rows()) == len(lines_of_holes("26330_vergiss-es-nie-dass-du-lebst")) == 14
    assert all(r.unknown == [] for r in read.rows())
    second = read.rows()[1]  # .5. -4 5 -4 5 .
    assert [(g.label(), g.hold) for g in second.groups] == [
        ("5", True), ("−4", False), ("5", False), ("−4", False), ("5", True)]


def test_dirty_old_town_writes_its_signs_after_the_hole():
    read = spelled("10319_dirty-old-town-not-pogues")
    assert read.convention == "signs after" and read.readable
    assert [r.lyric is not None for r in read.rows()] == [True] * 4 and all(r.unknown == [] for r in read.rows())
    assert [g.label() for g in read.rows()[0].groups] == ["6", "−6", "7", "8", "−8", "7", "8", "7", "6"]
    assert read.notes[-1].startswith("Rtu zheirvi")  # its "3+" and "7+" in a line of prose are prose still


def test_a_star_after_a_hole_is_a_bend_on_twelve_bar_blues_boogie_as_its_page_says_diatonic():
    read = spelled("9069_twelve-bar-blues-boogie-different")
    assert star_bends(read) and not read.chromatic and read.readable
    assert labels(read).count("−3′") == 6 and not any(h.button for r in read.rows() for g in r.groups for h in g.holes)
    # its turnaround, its words inside it kept in their place (test_viewer_harptab_layout.py); its holes, as their
    # legend says
    turnaround = next(r for r in read.rows() if r.line == 10)
    assert turnaround.trusted and read.missed == []
    assert [g.label() for g in turnaround.groups if g.holes][:8] == ["−1", "−2", "−3′", "−3′", "1", "2", "3", "−3′"]
    assert [g.label() for g in turnaround.groups if g.holes][-5:] == ["−4′", "−4", "−4′", "4", "−3"]  # b-4/-4 b-4 4 -3
    assert [g.text for g in turnaround.groups if g.kind == "words"] == ["(wvel how ob fuqweziudf i na ub nwez wia)",
                                                                        "od"]
    # without its chip, as a tab kept before caracole kept chips: a slide, a chromatic's, shown as written
    assert not spelled("9069_twelve-bar-blues-boogie-different", harp=None).readable


def test_whole_lotta_love_bends_a_draw_with_a_b_between_the_sign_and_the_hole():
    read = spelled("2136_whole-lotta-love")
    assert labels(read).count("−3′") == 7  # -b3 (5) and b-3 (2)
    assert "3′" not in labels(read)  # never a blow bent, a note no harp has


def test_en_el_pais_de_la_libertad_bends_a_draw_written_in_brackets():
    read = spelled("4765_en-el-pais-de-la-libertad")
    assert read.convention == "brackets"
    first = read.rows()[0]  # 4 ---> 6 ...... 6 5 (4) - 5 (4) 4 (3)b (3)b 3
    assert [g.label() for g in first.groups if g.holes] == ["4", "6", "6", "5", "−4", "5", "−4", "4", "−3′", "−3′", "3"]
    assert [g.text for g in first.groups][-3:] == ["(3)b", "(3)b", "3"] and first.unknown == ["-"]
    assert [g.text for g in first.groups if g.kind == "unread"] == ["-"]  # kept in its place


# --- the notation ----------------------------------------------------------------------------------------------


def test_each_way_of_writing_a_hole():
    # By harptabs.com's key (the signs, scan's own); 4B and 4D are the letters' (test_viewer_harptab_notation.py).
    found = scan("4 +4 -4 −4 –4 -3' -3'' -3b -3bb b-3 6o -7o 10 -10")
    assert [g.label() for g in found.groups] == [
        "4", "4", "−4", "−4", "−4", "−3′", "−3′′", "−3′", "−3′′", "−3′", "6°", "−7°", "10", "−10"]
    assert found.coverage == 1.0 and found.is_row


def test_a_bend_of_three_semitones_is_read_as_its_other_spellings_are():
    # The 3 draw bends a whole step and a half: -3''', -3bbb or bbb-3, as the module's docstring reads them.
    found = scan("-3''' -3bbb bbb-3 -2bb 10b")
    assert [g.label() for g in found.groups] == ["−3′′′", "−3′′′", "−3′′′", "−2′′", "10′"]
    assert found.coverage == 1.0 and harp.hole_note(0, 3, "draw", 3) is not None


def test_a_double_quote_after_a_hole_is_two_bends_as_two_marks_are():
    # Barrett's key writes a whole-step bend so; of the 128 a study found, 124 on draws 2 and 3, which bend a whole step
    found = scan('-3" -2” -3\'\' -2bb 4')
    assert [g.label() for g in found.groups] == ["−3′′", "−2′′", "−3′′", "−2′′", "4"]
    assert found.coverage == 1.0 and found.unknown == ()


def test_what_no_spelling_reads_is_unknown_never_dropped():
    # a quote after no hole, a lone dash, a bracket left open, a full stop: each the line's own, unread, in its place
    found = scan('4 " 5 - 6 ( 7 .')
    assert [g.label() for g in found.groups] == ["4", '"', "5", "-", "6", "(", "7", "."]
    assert [g.kind for g in found.groups if not g.holes] == ["unread"] * 4
    assert found.unknown == ('"', "-", "(", ".") and found.coverage == 0.5


def test_a_bend_written_between_the_sign_and_the_hole():
    # Whole Lotta Love's "-b3": the draw bent, as "-3b" and "b-3" are
    found = scan("-3-b3 3 -bb2 b-3 -3b")
    assert [g.label() for g in found.groups] == ["−3", "−3′", "3", "−2′′", "−3′", "−3′"]
    assert found.unknown == ()


def test_a_bend_after_a_lone_hole_in_brackets_bends_the_hole():
    # "(3)b": the draw of a tab that writes a draw in brackets, bent; "(3)'" and "(3)bb" as the hole's own marks are
    found = scan("(3)b (3)' (4) (3)bb", notation=BRACKETS)
    assert [g.label() for g in found.groups] == ["−3′", "−3′", "−4", "−3′′"]
    assert found.unknown == () and found.groups[0].text == "(3)b"
    assert scan("(-3)b 4").groups[0].label() == "−3′"
    assert scan("(4 5)b").unknown == ("b",)  # holes together: no bend of theirs
    assert scan("(3)tue", notation=BRACKETS).unknown == ("tue",)  # a word after it, no bend


def test_a_time_signature_or_a_clock_time_is_prose_never_holes():
    for line in ("Time: 3/4", "3/4 TIME (SLOW)", "4/4", "2/4,", "1:45", "3:02", "21:57 30/03/2018",
                 "SOLO 4:24", "run time 3:00."):
        found = scan(line)
        assert found.holes == () and not found.is_row, line
    assert parse("Time: 3/4\n\n4 5 6\nla la la\n").notes == ["Time: 3/4"]
    # a bar or a bend written with "/" beside a hole still reads
    assert [g.label() for g in scan("4 / 5 /6 -3/ 7").groups] == ["4", "5", "6", "−3", "7"]


def test_a_tab_writes_its_signs_after_the_hole_or_before_it_never_both():
    # "6+ 6-" (Wikibooks' notation), in a tab that writes no sign before a hole: blow 6, draw 6
    read = parse("6+ 6- 7+ 8+ 8- 7+\nla la la la la la\n")
    assert read.convention == "signs after"
    assert [g.label() for g in read.rows()[0].groups] == ["6", "−6", "7", "8", "−8", "7"]
    assert read.rows()[0].unknown == []
    # a tab that writes "-6" before the hole: "6-" is no draw, and its "-" no hole's
    read = parse("-6 6- 7 -7\nla la la la\n")
    assert read.convention == "signs"
    assert labels(read) == ["−6", "6", "7", "−7"] and read.rows()[0].unknown == ["-"]
    assert [g.label() for g in scan("6- 7+ 6-7").holes] == ["6", "7", "6", "−7"]  # harptabs.com's, a line alone
    assert scan("6+ 6-", notation=SIGNS_AFTER).unknown == () and scan("6--", notation=SIGNS_AFTER).groups[0].hold


def test_dots_lengthen_the_hole_before_them_in_a_tab_that_writes_a_dot_before_a_hole():
    # A German hymn series on harptabs.com: "the dots extend the note"; a dot before a hole, then after one
    read = parse(". 4   4   -4  5 .  7\nLo-rem ip su: dol si\n.5. -4 5 -4 5 .\nam-et con-se\n")
    assert dotted(read) and read.convention == "signs"
    first, second = read.rows()
    assert [(g.label(), g.hold) for g in first.groups] == [
        ("4", False), ("4", False), ("−4", False), ("5", True), ("7", False)]
    assert [g.hold for g in second.groups] == [True, False, False, False, True]
    assert first.unknown == second.unknown == []


def test_a_full_stop_lengthens_nothing_in_a_tab_that_writes_no_dot_before_a_hole():
    read = parse("1.\n4 5 6.\nla la la\n2.\n")
    assert not dotted(read) and not star_bends(read) and read.convention == "signs"
    assert len(read.rows()) == 1 and [g.hold for g in read.rows()[0].groups if g.holes] == [False, False, False]
    assert read.rows()[0].unknown == ["."]


def test_holes_together():
    found = scan("(4 5 6) (456) {-4 -5} [-2 -5] (-4)")
    assert [(g.kind, g.label()) for g in found.groups] == [
        ("chord", "(4 5 6)"), ("chord", "(4 5 6)"), ("shake", "{−4 −5}"), ("split", "[−2 −5]"), ("note", "−4")]


def test_a_lone_hole_in_brackets_is_a_draw_only_where_the_tab_says_so():
    assert scan("(5) 4", notation=BRACKETS).groups[0].holes == (Hole(5, "draw"),)
    assert scan("(4 5)", notation=BRACKETS).groups[0].holes == (Hole(4, "draw"), Hole(5, "draw"))  # "se aspiran"
    # By harptabs.com's key, brackets round one hole mean nothing: the hole is read, the brackets kept as written
    signs = scan("(5) 4")
    assert [(g.kind, g.text) for g in signs.groups] == [("unread", "("), ("note", "5"), ("unread", ")"), ("note", "4")]
    assert signs.holes[0].holes == (Hole(5, "blow"),) and signs.coverage == 0.5


def test_holds_bars_and_repeats_are_read_and_hold_the_hole_before_them():
    found = scan("Intro: 4---- -5.... | 6 (hold) x2")
    assert found.label == "Intro" and found.is_row
    assert [(g.label(), g.hold) for g in found.groups] == [("4", True), ("−5", True), ("6", True)]


def test_a_repeat_mark_is_read_written_either_way():
    # "x2" and "(x2)", and as often "2x" and "(2x)": a row of holes with one is a row, its holes all read.
    for line in ("-4 -5 6 x2", "-4 -5 6 (x2)", "-4 -5 6 2x", "-4 -5 6 (2x)", "-4 -5 6 (3X)"):
        found = scan(line)
        assert found.is_row and found.coverage == 1.0, line
        assert [g.label() for g in found.groups] == ["−4", "−5", "6"], line
    tab = parse("4 -4 5 -5 6 (2x)\nla la la la la\n")
    assert [p for r in tab.rows() for p, _ in r.parts] and tab.rows()[0].lyric == "la la la la la"


def test_a_digit_in_a_word_is_no_hole_and_a_line_of_words_is_no_row():
    assert scan("the 2nd verse, 4th time").holes == ()
    assert not scan("Play it 3 times then go to 4").is_row
    assert scan("").groups == () and not scan("   ").is_row


def test_a_chromatics_slide_or_its_pages_chip_is_shown_as_written():
    assert not parse("4 <5 -6 7*\nwords to sing here\n").readable
    assert parse("4 5 -6 7\nwords to sing here\n").readable
    assert not parse("4 5 -6 7\nwords to sing here\n", harp="Chromatic").readable
    assert parse("4 5 -6 7\nwords to sing here\n", harp="Diatonic").readable


def test_a_tab_harptabs_com_calls_chromatic_is_shown_as_written_though_it_presses_no_slide():
    body = "4 5 6 -6 7\nla la la la la\n"
    assert parse(body).readable and parse(body, harp="Diatonic").readable
    chromatic = parse(body, harp="Chromatic")
    assert chromatic.chromatic and not chromatic.readable


def test_a_star_after_a_hole_is_a_bend_on_a_tab_harptabs_com_calls_diatonic():
    # Tab 9069's legend: "* = half step bend", "** = whole step bend"; its page's chip says Diatonic
    body = "-1 -2 -3* -3*/ 1 2 3 -3**/ -2\nla la la la la la la la la\n"
    read = parse(body, harp="Diatonic")
    assert read.readable and star_bends(read) and not dotted(read)
    assert labels(read) == ["−1", "−2", "−3′", "−3′", "1", "2", "3", "−3′′", "−2"]
    # no chip (a tab kept before, one from the inbox) or another: a slide, as a chromatic's tab writes it
    for chip in (None, "Tremolo"):
        assert parse(body, harp=chip).chromatic and not parse(body, harp=chip).readable
    assert parse("4 <5 -6\nla la la\n", harp="Diatonic").chromatic  # "<" is the slide on any harp


def test_a_tab_with_no_row_is_shown_as_written():
    assert not parse("").readable
    assert not parse("Just some words\nabout the song\n").readable


def test_the_harp_a_tab_names_in_its_words():
    assert named_key(["The band plays in E so I use an A harp"]) == "A"
    assert named_key(["harp in Bb"]) == "Bb"
    assert named_key(["ARMONICA EN C"]) == "C"
    assert named_key(["A harp is a fine thing"]) == "A"  # as a tabber might begin one: read as a harp
    assert named_key(["a harp in a minor key", "harmonica Diatonic"]) is None


def test_a_tab_with_windows_line_ends_tabs_and_no_break_spaces_reads_as_one_without():
    plain = parse("4  5  6\nla la la\n")
    for body in ("4  5  6\r\nla la la\r\n", "4  5  6\nla la la\n"):
        assert holes_of(parse(body).rows()[0]) == holes_of(plain.rows()[0])
    assert holes_of(parse("4\t5\nla\tla\n").rows()[0]) == [(["4"], "la      "), (["5"], "la")]


# --- holes over syllables ----------------------------------------------------------------------------------------


def row(holes: str, lyric: str) -> list[tuple[list[str], str]]:
    r = Row(list(scan(holes).groups), lyric)
    align(r)
    return holes_of(r)


def test_syllables_start_at_each_word_and_after_a_hyphen_or_a_comma_inside_one():
    assert syllable_starts("des-ert hea-vy,and") == [0, 4, 8, 12, 15]


def test_a_hole_snaps_to_the_syllable_it_is_written_over():
    assert row("8  -8  -8", "On des-ert") == [(["8"], "On "), (["−8"], "des-"), (["−8"], "ert")]


def test_a_hole_written_inside_a_word_with_no_hyphen_cuts_it_where_a_syllable_breaks():
    assert row("4   5 6", "tomorrow") == [(["4"], "to"), (["5"], "mor"), (["6"], "row")]


def test_holes_after_the_last_syllable_are_held_on_it():
    assert row("-8 7 -6", "air--") == [(["−8", "7", "−6"], "air--")]


def test_words_before_the_first_hole_come_first_with_none():
    assert row("      4", "la la la") == [([], "la la "), (["4"], "la")]


def test_a_word_with_many_holes_inside_never_takes_long():
    holes = " ".join(["4"] * 30)
    started = time.monotonic()
    parts = row(holes, "a" + "bcdefghijklmnopqrstuvwxyz" * 3)
    assert time.monotonic() - started < 2
    assert sum(len(g) for g, _ in parts) == 30  # every hole placed, cut or held


def test_every_group_of_a_row_is_placed_once_in_its_order():
    for stem in SAMPLED:
        for r in tab(stem).rows():
            placed = [g for groups, _ in r.parts for g in groups]
            assert placed == r.groups, (stem, r.lyric)
            if r.lyric is not None:  # every word, but the spaces before the first
                joined, lyric = "".join(text for _, text in r.parts), r.lyric.rstrip()
                assert lyric.endswith(joined) and not lyric[:len(lyric) - len(joined)].strip(), (stem, r.lyric)


def test_the_page_items_are_what_the_tab_holds():
    read = parse("Notes before\n\n4 5\nla la\n\nVerse\n-4 -5\nlo lo\n\nsung the same\nto the tune\n\n"
                 "Play it twice to fade\n")
    assert read.notes == ["Notes before"]
    assert [s.label for s in read.sections] == [None, "Verse"]
    assert [type(i) for i in read.sections[1].items] == [Row, Gap, Words, Gap, Prose]
    assert isinstance(read.sections[0].items[0].groups[0], Group)
