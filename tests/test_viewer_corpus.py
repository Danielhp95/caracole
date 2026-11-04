"""tests/helpers/viewer_corpus.py, the seeded inputs of milestone 5's generators: what it covers, and that every process
computes the same."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from caracole.render import _chordpro_text
from caracole.viewer import harmony, theory
from caracole.viewer.sheet import parse_sheet
from caracole.viewer.theory import MODES, QUALITIES, Key, parse_chord
from conftest import subprocess_pythonpath
from helpers import viewer_corpus

TESTS = Path(__file__).resolve().parent
SRC = TESTS.parent / "src"


def test_every_key_is_there_once_by_mode_then_tonic():
    keys = viewer_corpus.keys()
    assert keys == [Key(tonic, mode) for mode in MODES for tonic in range(12)]
    keys.clear()
    assert len(viewer_corpus.keys()) == 84  # a copy each time


def test_every_quality_is_named_on_every_root_and_its_synonyms_are_read():
    read = {(c.root, c.quality) for c in map(parse_chord, viewer_corpus.chord_names()) if c is not None}
    assert {(root, quality) for root in range(12) for quality in QUALITIES} <= read
    names = viewer_corpus.chord_names()
    assert set(viewer_corpus.EDGE_CHORDS) <= set(names)
    assert len(names) == len(set(names))
    assert any(parse_chord(n) is None and parse_chord(n, strict=False) is not None for n in names)
    assert any(parse_chord(n) is not None and parse_chord(n).tones is not None for n in names)  # outside QUALITIES
    assert set(QUALITIES) == set(viewer_corpus.SYNONYMS)


def test_key_texts_name_every_letter_in_every_mode_and_the_edges():
    texts = viewer_corpus.key_texts()
    keys = {theory.parse_key(t) for t in texts}
    assert {Key(tonic, mode) for tonic in range(12) for mode in MODES} <= keys
    assert None in keys
    assert set(viewer_corpus.EDGE_KEY_TEXTS) <= set(texts)


def test_every_progression_of_the_catalogue_is_played_on_two_keys():
    progressions = viewer_corpus.progressions()
    assert sorted({p.row for p in progressions}) == list(range(len(harmony.CATALOGUE)))
    assert all(sum(p.row == row for p in progressions) == 2 for row in range(len(harmony.CATALOGUE)))
    for p in progressions:
        assert len(p.chords) == len(p.numerals)
        assert all(parse_chord(c) is not None for c in p.chords), p
    pop = next(p for p in progressions if p.name == "the pop progression")
    names = theory.spelling(pop.key)
    assert pop.chords[0] == names[pop.key.tonic]  # I, the tonic's major chord


def test_the_sheets_hold_every_kind_of_line_the_viewer_reads():
    sheets = viewer_corpus.sheets()
    assert len({s.name for s in sheets}) == len(sheets)
    tags = {t for s in sheets for t in s.tags}
    assert {"mode", "catalogue", "qualities", "edge", "fixture", "preamble", "legend", "tab", "define", "capo",
            "chinese", "kana", "auto", "ug", "lacuerda"} <= tags
    assert {f"mode-{k.mode}-{k.tonic}" for k in viewer_corpus.keys()} <= {s.name for s in sheets}
    assert {f"catalogue-{p.row}-{p.key.tonic}" for p in viewer_corpus.progressions()} <= {s.name for s in sheets}
    fixtures = {s.name for s in sheets if "fixture" in s.tags}
    assert {"fixture:chordpro/ug_sheet.txt", "fixture:chordpro/ug_sheet.cho", "fixture:chordpro/legend_sheet.cho",
            "fixture:chordpro/zh_sheet.txt", "fixture:ug/tab_chords.html", "fixture:ug/tab_ukulele.html",
            "fixture:lacuerda/version.html"} <= fixtures
    for s in sheets:
        parsed = parse_sheet(s.cho)
        assert parsed.title == s.title or s.markup is None, s.name
        assert all(f"[{name}]" in s.cho for name in s.played), s.name
        if "define" in s.tags:
            assert parsed.defines, s.name
        if "capo" in s.tags:
            assert parsed.capo == s.capo, s.name
        if "auto" in s.tags:
            assert parsed.auto, s.name
        if "tab" in s.tags:
            assert "{start_of_tab}" in s.cho, s.name
        if s.markup is not None and not s.defines:
            assert s.cho == _chordpro_text(s.markup, title=s.title, artist=s.artist, key=s.key, capo=s.capo,
                                           auto=s.auto), s.name
    assert viewer_corpus.sheet("fixture:ug/tab_ukulele.html").capo == 1


# Read by hand from each sheet's text: its chords as written, section after section, the notes' before the song
# among them; an annotation ([*x2], [*N.C.], [*| ]) and a tab's lines are none, and a repeat mark repeats nothing.
PLAYED_BY_HAND = {
    "fixture:chordpro/ug_sheet.cho": ("G", "D", "Em", "C", "G", "D", "Em", "C", "C", "G/B", "Am", "F", "C", "G", "D",
                                      "C"),
    "fixture:chordpro/legend_sheet.cho": ("Em7", "G", "A7sus4", "Cadd9", "Em7", "G", "Dsus4", "A7sus4", "Em7", "G",
                                          "Dsus4", "A7sus4", "Cadd9", "Dsus4/F#", "Cadd9", "Em7", "G", "Em7",
                                          "Cadd9", "G"),
    "edge-0": ("Em", "C", "G", "D", "Am", "D", "Em"),
    "edge-1": ("G", "D", "C", "G", "Am"),
    "edge-8": ("A", "D", "E7", "A", "D", "A", "D", "E7"),
}


def test_a_sheets_played_chords_are_those_it_plays_in_order():
    for name, played in PLAYED_BY_HAND.items():
        assert viewer_corpus.sheet(name).played == played, name


def test_a_sheets_defines_follow_its_header():
    s = next(s for s in viewer_corpus.sheets() if s.defines and s.markup is not None)
    lines = s.cho.split("\n")
    first = lines.index(s.defines[0])
    assert all(line.startswith(viewer_corpus._HEAD) for line in lines[:first])
    assert lines[first:first + len(s.defines)] == list(s.defines)
    without = lines[:first] + lines[first + len(s.defines):]
    assert "\n".join(without) == _chordpro_text(s.markup, title=s.title, artist=s.artist, key=s.key, capo=s.capo,
                                                auto=s.auto)


def test_data_json_keeps_the_order_it_is_given():
    text = viewer_corpus.data_json({"b": 1, "a": {"z": [1, 2], "y": "é"}})
    assert text == '{\n "b": 1,\n "a": {\n  "z": [\n   1,\n   2\n  ],\n  "y": "é"\n }\n}\n'
    assert list(json.loads(text)) == ["b", "a"]


@pytest.mark.slow
def test_every_process_computes_the_same_inputs():
    here = viewer_corpus.digest()
    code = "from helpers import viewer_corpus; print(viewer_corpus.digest())"
    for seed in ("0", "1", "12345"):
        env = {**os.environ, "PYTHONHASHSEED": seed,
               "PYTHONPATH": os.pathsep.join((str(TESTS), subprocess_pythonpath(SRC)))}
        out = subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, text=True, check=True,
                             cwd=TESTS)
        assert out.stdout.strip() == here, f"PYTHONHASHSEED={seed}"
