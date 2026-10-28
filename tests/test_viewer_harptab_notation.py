"""caracole.viewer.harptab's notations: each preset against a table of tokens, the score that chooses one (Q = P × T,
ties to the commoner, the margin), a tab's legend, and Spokey Dokey.

Spokey Dokey (tests/fixtures/harptabs/legends/693_spokey-dokey.txt, harptabs.com's tab 693, the owner's): its lines of
holes, its section names and its legend's lines as the tabber wrote them, every other line's letters made up (a vowel
for a vowel, a consonant for a consonant, the case, the spaces and the punctuation kept). Its tabber writes ``3b`` for
blow 3, ``3d`` draw 3, ``*`` a bend before the letter, ``-`` between notes run together, and says so at its foot:
"(w) = Wah effect", "(h) = Hold", "* = bend", "D= draw", "b= blow". ``$``, ``(DV)`` and the first hole of ``3-4b``
it defines nowhere.
"""

from __future__ import annotations

import re
from collections import Counter
from pathlib import Path

import pytest

from caracole.viewer import harp
from caracole.viewer.harptab import (
    BARRETT,
    BRACKETS,
    LETTERS,
    MARGIN,
    PRESETS,
    SIGNS,
    SIGNS_AFTER,
    Hole,
    Legend,
    Notation,
    Symbol,
    Words,
    legend,
    parse,
    scan,
)

SPOKEY = (Path(__file__).parent / "fixtures" / "harptabs" / "legends" / "693_spokey-dokey.txt").read_text("utf-8")
LEGEND_LINES = ("(w) = Wah effect", "(h) = Hold", "* = bend", "D= draw", "b= blow")


def reads(token: str, notation: Notation) -> list[str]:
    """What ``notation`` reads in ``token``: each group's label, an unread span as ``?`` and its text, a group run
    into the next with ``~``, an effect in brackets."""
    return [("?" + g.text if g.kind == "unread" else g.label()) + "".join(f"[{e}]" for e in g.effects)
            + ("…" if g.hold else "") + ("~" if g.join else "") for g in scan(token, notation=notation).groups]


# --- each preset, against a table of tokens ------------------------------------------------------------------------

TOKENS = [
    # harptabs.com's key: a sign before the hole, a bend after it (or b before it), o, a slide
    (SIGNS, "4", ["4"]), (SIGNS, "+4", ["4"]), (SIGNS, "-4", ["−4"]), (SIGNS, "−4", ["−4"]), (SIGNS, "–4", ["−4"]),
    (SIGNS, "-3'", ["−3′"]), (SIGNS, "-3''", ["−3′′"]), (SIGNS, "-3'''", ["−3′′′"]), (SIGNS, "-3’", ["−3′"]),
    (SIGNS, "-3b", ["−3′"]), (SIGNS, "-3bb", ["−3′′"]), (SIGNS, "b-3", ["−3′"]), (SIGNS, "bb-3", ["−3′′"]),
    (SIGNS, "-b3", ["−3′"]), (SIGNS, "6o", ["6°"]), (SIGNS, "-7o", ["−7°"]), (SIGNS, "10", ["10"]),
    (SIGNS, "-10", ["−10"]), (SIGNS, "-4<", ["−4<"]), (SIGNS, "<-4", ["−4<"]), (SIGNS, "-4*", ["−4<"]),
    (SIGNS, "-45", ["−4", "5"]), (SIGNS, "-4-5", ["−4", "−5"]), (SIGNS, "4----", ["4…"]), (SIGNS, "3b", ["3′"]),
    (SIGNS, "4d", ["?4d"]), (SIGNS, "4D", ["?4D"]), (SIGNS, "(5)", ["?(", "5", "?)"]), (SIGNS, "(-5)", ["−5"]),
    (SIGNS, "(4 5)", ["(4 5)"]), (SIGNS, "2nd", ["?2nd"]), (SIGNS, "x2", []), (SIGNS, "$", ["?$"]),
    # the Spanish tabs: a hole in brackets drawn
    (BRACKETS, "5", ["5"]), (BRACKETS, "(5)", ["−5"]), (BRACKETS, "(45)", ["(−4 −5)"]), (BRACKETS, "(3)b", ["−3′"]),
    (BRACKETS, "(2)'", ["−2′"]), (BRACKETS, "(3b)", ["−3′"]), (BRACKETS, "(4)-(5)", ["−4~", "−5"]),
    (BRACKETS, "-4", ["?-", "4"]),
    # letters after the hole, in either case; a bend before the letter; - runs two notes together
    (LETTERS, "4b", ["4"]), (LETTERS, "4B", ["4"]), (LETTERS, "4d", ["−4"]), (LETTERS, "4D", ["−4"]),
    (LETTERS, "3*d", ["−3′"]), (LETTERS, "3**d", ["−3′′"]), (LETTERS, "-3'D", ["?-", "−3′"]),
    (LETTERS, "3*d-3d", ["−3′~", "−3"]), (LETTERS, "3**d-3*d-3d", ["−3′′~", "−3′~", "−3"]),
    (LETTERS, "3-4b", ["?3~", "4"]), (LETTERS, "4d-$-5d", ["−4~", "?$~", "−5"]), (LETTERS, "7,8B", ["(7 8)"]),
    (LETTERS, "4", ["?4"]), (LETTERS, "-4", ["?-4"]), (LETTERS, "3*d(W)", ["−3′", "?(W)"]),
    # the two-sign system: + and - after the hole
    (SIGNS_AFTER, "6+", ["6"]), (SIGNS_AFTER, "6-", ["−6"]), (SIGNS_AFTER, "10-", ["−10"]),
    (SIGNS_AFTER, "6", ["6"]), (SIGNS_AFTER, "6--", ["6…"]), (SIGNS_AFTER, "6-7", ["6", "?-", "7"]), (SIGNS_AFTER, "4-'", ["−4′"]),
    # David Barrett's: a hole alone drawn, + blown
    (BARRETT, "3", ["−3"]), (BARRETT, "4+", ["4"]), (BARRETT, "3'", ["−3′"]), (BARRETT, "2’’", ["−2′′"]),
    (BARRETT, "-4", ["?-", "−4"]),
]


@pytest.mark.parametrize(("notation", "token", "found"), TOKENS,
                         ids=[f"{n.name}:{t}" for n, t, _ in TOKENS])
def test_each_preset_reads_its_tokens(notation, token, found):
    assert reads(token, notation) == found


def test_the_presets_and_their_order_the_commonest_first():
    assert [n.name for n in PRESETS] == ["signs", "brackets", "letters", "signs after", "barrett"]
    assert (SIGNS.bare, BRACKETS.bare, LETTERS.bare, SIGNS_AFTER.bare, BARRETT.bare) == (
        "blow", "blow", None, "blow", "draw")
    assert LETTERS.fold and not SIGNS.fold


def test_a_notation_is_its_table_and_its_tokenizer_is_made_from_it():
    # A notation made by hand: "u" after the hole a bend, "^" before it a draw, "~" between two a run.
    mine = Notation("mine", (Symbol("^", "draw", "before"), Symbol("u", "bend", "after"),
                             Symbol("~", "join", "between")))
    assert reads("^3u~4 ^2uu", mine) == ["−3′~", "4", "−2′′"]
    # changed as a legend or the owner would: the symbol written the same way in the same place is replaced
    changed = SIGNS.changed((Symbol("*", "bend", "after"), Symbol("(w)", "wah", "after")))
    assert changed.meaning("*", "after") == Symbol("*", "bend", "after")
    assert changed.meaning("<", "after").means == "slide" and changed.name == "signs"
    assert reads("-3* 4(w)", changed) == ["−3′", "4[wah]"]
    assert reads("-3* 4 (w)", changed) == ["−3′", "4[wah]"]  # written apart, the hole's before it


def test_what_a_scan_used_is_counted_as_written():
    found = scan("3*d 3b 3B 3-4b", notation=LETTERS)
    assert found.used == Counter({("b", "blow", "after", 1): 2, ("B", "blow", "after", 1): 1,
                                  ("d", "draw", "after", 1): 1, ("*", "bend", "after", 1): 1,
                                  ("-", "join", "between", 1): 1})
    assert scan("4 -4 (5)", notation=BRACKETS).used == Counter({("", "blow", "bare", 1): 2,
                                                                ("()", "draw", "around", 1): 1})


# --- the score: Q = P × T --------------------------------------------------------------------------------------


def test_the_reading_that_explains_the_most_of_what_a_harp_plays_wins():
    # b a blow or a bend: read as bends, blows 3 and 2 bent are notes no harp has (T 0)
    found = parse("3b 3b 2b 3d\n")
    assert found.convention == "letters" and found.reading.source == "guessed"
    assert (found.reading.explained, found.reading.playable, found.reading.q) == (1.0, 1.0, 1.0)
    assert found.reading.runner == "signs"


def test_plausibility_is_a_soft_score_never_a_filter():
    # 1**d: hole 1's draw bends one semitone, not two: the tabber's slip costs a little and blocks nothing
    found = parse("1**d 1*d 1d 2b 2d 3b\n")
    assert found.convention == "letters" and found.readable
    assert found.reading.playable == pytest.approx(5 / 6)
    assert [g.label() for g in found.rows()[0].groups] == ["−1′′", "−1′", "−1", "2", "−2", "3"]


def test_a_hole_alone_in_brackets_is_a_draw_where_the_tab_writes_no_sign():
    spanish = parse("(5) 5 (4) 4 (5) 6 (6)\nla la la la la la la\n")
    assert spanish.convention == "brackets"
    assert [g.label() for g in spanish.rows()[0].groups if g.holes] == ["−5", "5", "−4", "4", "−5", "6", "−6"]
    signed = parse("-4 -5 (6) 6 -5 -4 4 -4 -5\nla la la la la la la la la\n")
    assert signed.convention == "signs" and signed.rows()[0].groups[3].label() == "6"


def test_a_tie_goes_to_the_commoner_notation_and_is_no_rival():
    # Bare numbers alone: harptabs.com's blows or Barrett's draws, explained and played alike: the commoner wins, and
    # a reading less common needs no margin over it.
    found = parse("4 4 5 5 6 6 5\n")
    assert found.convention == "signs" and found.reading.margin == 0 and found.reading.runner == "barrett"
    assert found.readable  # brackets read it alike: no rival at all


def test_an_unusual_reading_must_beat_a_commoner_one_by_the_margin():
    # Bare blows and a single (5): brackets explain it, by under the margin: the tab is shown as written
    thin = parse(" ".join(["4 5 6"] * 14) + " (5)\n")
    assert thin.convention == "brackets" and thin.reading.margin < MARGIN
    assert not thin.reading.confident and not thin.readable
    clear = parse(" ".join(["4 5 6"] * 8) + " (5) (6)\n")
    assert clear.convention == "brackets" and clear.reading.confident and clear.readable


@pytest.mark.parametrize(("body", "name"), [
    ("4B 6B 5D 5B 4D 4B 3B\n", "letters"),
    ("6+ 6-   7+  8+  8- 7+  8+  7+   6+\nI faund my lavo by tha gesworks creft\n", "signs after"),
    ("2 3' 4+ 4' 4 5 4 4' 4+ 3' 4+ 3' 2 2’’ 1 1+ 1 2\n", "barrett"),
    ("-4 -4 5 -5 6 -6 6 -5\n", "signs"),
])
def test_each_notation_is_found_by_its_score(body, name):
    assert parse(body).convention == name


def test_a_row_read_with_low_confidence_is_shown_as_written():
    # One row of bent blows on holes 2 and 3 in a tab of signs: read alike, but no harp plays it
    found = parse("4 -4 5 -5 6\nla la la la la\n\n3b 3b 2b 2b\nlo lo lo lo\n\n-4 -5 6\nli li li\n")
    rows = found.rows()
    assert [r.trusted for r in rows] == [True, False, True] and found.readable
    assert rows[1].text == "3b 3b 2b 2b" and rows[1].lyric == "lo lo lo lo" and rows[1].parts == []
    assert rows[1].confidence == 0 and found.missed == ["3b 3b 2b 2b"]


def test_a_line_of_holes_read_under_the_share_is_shown_as_written_never_taken_for_words():
    found = parse("4 -4 5 -5 6\nla la la la la\n\n4 5 6 -6 5 BOOM\nlo lo lo lo lo\n")
    rows = found.rows()
    assert [(r.trusted, r.text, r.lyric) for r in rows] == [
        (True, "4 -4 5 -5 6", "la la la la la"), (False, "4 5 6 -6 5 BOOM", "lo lo lo lo lo")]
    assert not any(isinstance(i, Words) for s in found.sections for i in s.items)


# --- a tab's legend ------------------------------------------------------------------------------------------------


def test_spokey_dokeys_legend_is_read():
    found = legend(["4b 5d", "", *LEGEND_LINES])
    assert len(found) == 1 and found[0].lines == LEGEND_LINES and found[0].at == (2, 3, 4, 5, 6)
    assert found[0].symbols == (Symbol("(w)", "wah", ""), Symbol("(h)", "hold", ""), Symbol("*", "bend", ""),
                                Symbol("D", "draw", ""), Symbol("b", "blow", ""))


@pytest.mark.parametrize(("lines", "symbols"), [
    # the Spanish tabs' placeholders: a hole in brackets, a hole alone
    (["b = bending", "(numero) = aspirar", "numero = soplar"],
     [Symbol("b", "bend", ""), Symbol("()", "draw", "around"), Symbol("", "blow", "bare")]),
    (["# = soplar", "(#) = aspirar"], [Symbol("", "blow", "bare"), Symbol("()", "draw", "around")]),
    (["(2):aspirado", "2:soplado", "(2)b:bend aspirado"],
     [Symbol("()", "draw", "around"), Symbol("", "blow", "bare"), Symbol("b", "bend", "after")]),
    # columns, no separator but the spaces
    (["x             Nota soplada", "(x)            Nota aspirada", "x-x            Glisando"],
     [Symbol("", "blow", "bare"), Symbol("()", "draw", "around"), Symbol("-", "glissando", "between")]),
    # a hole's mark with a hole for the placeholder, a bend written twice and thrice
    (["4 = blow", "-4 = draw", "-4' = bend", "/= A bar", "*= half step bend", "**=whole step bend"],
     [Symbol("", "blow", "bare"), Symbol("-", "draw", "before"), Symbol("'", "bend", "after"),
      Symbol("/", "mark", ""), Symbol("*", "bend", "")]),
    (["Tab key:", "w = whole note", "r = rest"], [Symbol("w", "mark", ""), Symbol("r", "mark", "")]),
])
def test_a_legend_in_each_shape_the_tabs_write(lines, symbols):
    found = legend(lines)
    assert len(found) == 1 and list(found[0].symbols) == symbols


@pytest.mark.parametrize("lines", [
    ["Key: D", "Tuning: standard"],  # a harp's key, never a legend
    ["b = blow"],  # one line alone
    ["Chorus: x2", "Verse: 3"],  # no word of a legend's
    ["see https://example.com/tab = draw", "https://example.com/b = blow"],
    ["4  -4  5", "-5  6  -6"],  # holes in columns
])
def test_what_is_no_legend(lines):
    assert legend(lines) == []


def test_a_legend_is_found_wherever_it_sits():
    body = "4 -4 5\nla la la\n\nb = blow\nd = draw\n\n5 -5 6\nlo lo lo\n"
    found = parse(body)
    items = [type(i).__name__ for s in found.sections for i in s.items]
    assert items == ["Row", "Gap", "Legend", "Gap", "Row"]
    assert found.legend == Legend(("b = blow", "d = draw"), (Symbol("b", "blow", ""), Symbol("d", "draw", "")), (3, 4))


def test_a_legend_weighs_on_the_score_and_never_overrules_it():
    # A legend saying b is a blow, pasted on a tab whose b are bends after signs: the signs still read it best
    pasted = parse("b = blow\nd = draw\n\n-4b -4 5 -5 -3b -3 4 -4b\nla la la la la la la la\n")
    assert pasted.convention == "signs" and pasted.reading.source == "guessed"
    assert [g.label() for g in pasted.rows()[0].groups][:2] == ["−4′", "−4"]
    # Where the reading is open, the legend tips it: (5) the Spanish draw, said so
    said = parse("(numero) = aspirar\nnumero = soplar\n\n" + " ".join(["4 5 6"] * 14) + " (5)\n")
    assert said.convention == "brackets" and said.reading.source == "legend" and said.readable


def test_a_letter_a_legend_writes_in_one_case_reads_the_tabs_other_case():
    found = parse("(W) = wah\n(H) = hold\n\n-4 (w) -5 6(h)\nla la la\n")
    row = found.rows()[0]
    assert [(g.label(), g.effects, g.hold) for g in row.groups] == [("−4", ("wah",), False), ("−5", (), False),
                                                                     ("6", (), True)]
    assert found.reading.source == "legend" and found.reading.said() == "4 blow · - draw · (h) hold · (w) wah"


# --- Spokey Dokey ---------------------------------------------------------------------------------------------------


def without_legend(text: str) -> str:
    return "\n".join(line for line in text.split("\n") if line not in LEGEND_LINES)


def test_spokey_dokey_reads_as_b_blow_d_draw_star_bend_from_its_own_legend():
    found = parse(SPOKEY)
    assert found.convention == "letters" and found.reading.source == "legend" and found.readable
    assert found.reading.said() == "b blow · d draw · * bend · - joins · (h) hold · (w) wah"
    assert found.reading.q > 0.95 and found.reading.margin > 0.5
    assert found.legend is not None and found.legend.lines == LEGEND_LINES
    # its legend is its own item, never words sung to the same tune
    last = found.sections[-1].items
    assert isinstance(last[-1], Legend) and not any(isinstance(i, Words) for s in found.sections for i in s.items)


def test_spokey_dokey_reads_the_same_with_its_legend_deleted():
    found = parse(without_legend(SPOKEY))
    assert found.convention == "letters" and found.reading.source == "guessed" and found.readable
    assert found.reading.said() == "b blow · d draw · * bend · - joins"
    assert found.reading.q > 0.85 and found.reading.runner is not None and found.reading.margin > 0.5
    with_legend = parse(SPOKEY)
    holes = [[g.holes for g in r.groups if g.holes] for r in found.rows()]
    assert holes == [[g.holes for g in r.groups if g.holes] for r in with_legend.rows()]
    # what only its legend says: (w) a wah and (h) a hold; without it they are kept as written
    unread = Counter(g.text for r in found.rows() for g in r.groups if g.kind == "unread")
    assert unread["(w)"] == 10 and unread["(W)"] == 1 and unread["(H)(DV)"] == 1


def test_spokey_dokey_is_every_row_drawn_its_notes_nearly_all_on_a_harp():
    found = parse(SPOKEY)
    rows = found.rows()
    assert len(rows) == 13 and all(r.trusted for r in rows)
    assert [s.label for s in found.sections] == ["INTRO", "Chorus"]
    holes = [h for r in rows for g in r.groups for h in g.holes]
    playable = [h for h in holes if harp.hole_note(0, h.hole, h.breath, h.bend, h.over) is not None]
    assert (len(holes), len(playable)) == (136, 134)  # 1**d twice: the tabber's own
    assert rows[0].groups[0].holes == (Hole(3, "draw", 1),) and rows[0].groups[1].holes == (Hole(3, "blow"),)


def test_spokey_dokeys_unread_tokens_stay_in_place_unguessed():
    found = parse(SPOKEY)
    for row in found.rows():
        unread = [(g.col, g.text) for g in row.groups if g.kind == "unread"]
        written = [(m.start(), m.group(0)) for m in re.finditer(r"\$|\(DV\)|(?<![\d*])\d(?=-\d)", row.text)]
        assert unread == written, row.text
    texts = Counter(g.text for r in found.rows() for g in r.groups if g.kind == "unread")
    assert texts == Counter({"3": 4, "$": 2, "(DV)": 1})


def test_spokey_dokeys_effects_are_on_their_holes_and_its_runs_kept():
    rows = parse(SPOKEY).rows()
    chorus = rows[8]  # 3**d-3*d-3d-3*d(W) 2**d 3**d-3*d(H)(DV)-3d
    assert [(g.label(), g.effects, g.hold, g.join) for g in chorus.groups] == [
        ("−3′′", (), False, True), ("−3′", (), False, True), ("−3", (), False, True), ("−3′", ("wah",), False, False),
        ("−2′′", (), False, False), ("−3′′", (), False, True), ("−3′", (), True, False), ("(DV)", (), False, True),
        ("−3", (), False, False)]
    wahs = sum("wah" in g.effects for r in rows for g in r.groups)
    holds = sum(g.hold for r in rows for g in r.groups)
    assert (wahs, holds) == (11, 4)
