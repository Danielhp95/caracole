"""A sheet read, UG markup to ChordPro and a song's key, for the phone: viewer/sheet.py, the reading functions of
viewer/page.py that hold no HTML, chordpro.py with render.py's ``_chordpro_text`` and ``_as_latin``,
ug/page.py's ``decode_twice``, and keys.py, for :viewer's viewer.sheet (``Sheets``, ``SheetView``, ``ChordPro``,
``MusicKeys``).

The logic is Kotlin's; everything those modules state as data is written here, from the modules themselves, so a
change to a table or a pattern regenerates what the phone reads and the phone follows it.

The data, ``tests/conformance/data/caracole/viewer/sheet.json`` (caracole/viewer/sheet.json on the phone's
classpath, ``ViewerData.table("sheet")``; ``viewer_corpus.data_json``): one member a module, ``sheet``, ``page``,
``chordpro``, ``render``, ``ug_page`` and ``keys``, each the module's constants under their own names (a dict's
members in its order, a set as a sorted array) and its compiled patterns under ``patterns``, ``{name: {"pattern":
text, "ignorecase": bool}}`` (``.pattern``, as Python writes it; no flag but IGNORECASE, which core.py.PyRegex reads
as a leading ``(?i)``, true only for a pattern that doesn't start with its own ``(?i)``):

- ``sheet``: ``_DIRECTIVE``, ``_TOKEN``, ``_FRET``, ``_CHORUS``, ``_TUNING_NAME``, ``_TUNING_LABEL``, ``_CAPO``;
  ``_ESCAPED_BACKSLASH``, ``COMMENTS``, ``_STANDARD`` and autochords.merge's ``AUTO_MARKER``;
- ``page``: ``_SOURCES`` and ``_OF_THE_SHAPES``;
- ``chordpro``: ``_CHORD``, ``_TAB_MARK``, ``_SECTION``, ``_MARK``, ``_CHORD_LINE_REST``, ``_STAFF``,
  ``_SOLFEGE``, ``_LEAD_GAP``, ``_WORD``, ``_MARKUP_START``, ``_DECODED_BACKSLASH``, ``_DIRECTIVE_LIKE``;
  ``_SOLFEGE_LETTER``, ``TAB_STOP``, ``_BRACKETS`` (``{character: what it becomes}``), ``_ESCAPED_BACKSLASH``;
- ``render``: ``_LATIN_LOOKALIKES`` (``{character: its Latin letter}``) and ``cp1252``, the code points above
  U+007F that ``needs_font_file`` finds cp1252 encodes, as ``[[first, last], …]``, inclusive, in order;
- ``ug_page``: ``_ENTITY`` (IGNORECASE);
- ``keys``: ``_KEY_HEAD``, ``_KEY_HEAD_ENGLISH``, ``_KEY_LABEL``, ``_DIRECTIVE``, ``_CHORD_TAG``, ``_CHORD``,
  ``_QUALITY``, ``_ADDED``, ``_EXTENDED``, ``_MAJOR_SEVENTH``; ``SOURCES``, ``SHEET_DOC``, songs.py's
  ``HUMAN_SHEET`` and ``AUTO_SHEET``, ``_LETTERS``, ``_SOLFEGE``, ``_ACCIDENTALS``, ``_SHIFT``, ``_DIMINISHED``,
  ``_PROFILES`` (``{"major": […], "minor": […]}``, by its key False and True), ``MIN_FIT``, ``TONIC_SHARE``,
  ``EDGE``, ``_MAJOR_NAMES`` and ``_MINOR_NAMES``.

The vectors (``helpers.corpus.jsonl``). A chord is ``[root, quality, bass, shown, tones]`` with its trailing nulls
left out, a key ``[tonic, mode]`` (test_conformance_viewer_theory.py's rows); a sheet's line is ``["L", [[item,
text], …]]`` (Lyrics: ``item`` a chord's index, a mark's text or null), ``["C", [item, …]]`` (ChordRow), ``["T",
text]``, ``["Tab", [line, …]]`` or ``["B"]`` (Blank); a section ``[label, chorus, [line, …]]``; a sheet ``{"title",
"artist", "key", "capo", "auto", "chords", "sections", "defines"}``; a preamble (``sheet.Preamble``) ``{"notes",
"legend": [[chord, position], …], "tabs", "tuning", "capo_note", "end"}``.

``vectors/viewer/sheet.jsonl``, each record one of:

- ``read_of(cho, key, key_source)``, for every sheet of ``viewer_corpus.sheets()`` (its ``cho``, ``key`` and
  ``key_source``): ``{"sheet": parse_sheet(cho), "preamble": preamble_section(sheet), "shown": [pre, sections]
  (page._shown: the preamble's section, and each section shown as its index in ``sheet.sections`` where it is one of
  them, else its row), "peek": page._peek(pre) (null without a preamble), "keys": [[key, source,
  *page._song_key(sheet, chords, key, source)], …] for the record's own and ``OTHER_KEYS`` seeded of ``SONG_KEYS``,
  "viewer_key": page.viewer_key(cho, key, key_source), "given": page._given_shapes, "shapes": page.shapes_of,
  "legend": [[i, j], …] each line j of section i that sheet.is_legend reads as a legend's, "legend_lines": each n
  of ``cho.splitlines()`` sheet.is_legend_line reads as a legend's, "split": sheet.split_preamble(cho.splitlines())}``,
  and by their ``digest`` (the SHA-256 of ``json.dumps``, its defaults): "drawn": page._drawn_lines, "texts":
  page._written_texts, "places": page._places, "played": page._played, "written": [[sheet.written(line) …] a
  section], "directives": [[n, name, value], …] each line n of ``cho.splitlines()`` sheet.directive reads.
- ``lines_of(text)``, for every string literal of ``SHEET_LITERALS`` and ``EDGE_TEXTS``:
  ``{"sheet": parse_sheet(text), "directive": directive(text), "legend_line": is_legend_line(text), "split":
  split_preamble(text.splitlines()), "note": split_preamble([text, *NOTE_SONG])}``.

``vectors/viewer/chordpro.jsonl``, each record one of:

- ``caracole.render._chordpro_text(markup, title=, artist=, key=, capo=, auto=)``: ``to_chordpro`` then
  ``_as_latin``, byte for byte, for every sheet of ``viewer_corpus.sheets()`` with markup (the UG and LaCuerda
  fixtures' among them) as the corpus converts it, and the header alone (markup "") of a seeded sheet's title and
  artist with each of ``CONVERSIONS``' keys and capos (a capo as a string too), the body being the same whatever
  they are.
- ``lines_of(text)``, for every string literal of test_chordpro.py and ``EDGE_TEXTS``: ``{"normalize":
  normalize_chord, "tagged": tag_forgotten, "chord_line": is_chord_line, "columns": display_columns, "directive":
  directive_text, "latin": render._as_latin, "decoded": ug.page.decode_twice, "converted": to_chordpro(text,
  title="T", artist="A")}``, and ``"merged": merge_chord_line(text, next)`` with the next literal where the text
  is a chord line.
- ``display_columns(text)`` for ``COLUMNS`` seeded texts of every width (tabs, combining marks, wide, full-width
  and astral characters).

``vectors/viewer/musickeys.jsonl``, each record one of:

- ``named_of(texts)``: for a batch of ``BATCH`` texts (``viewer_corpus.key_texts()``, every string literal of
  test_keys.py and ``EDGE_TEXTS``), ``[keys.parse_key(text), keys._named(text)'s letter alone or null, key_name of
  the key, same_key(the key, KEY_TO)]`` (null where the text is no key).
- ``chord_of(names)``: for a batch of ``viewer_corpus.chord_names()`` and the literals, ``keys._chord(name)``:
  ``[root, spelling, triad, [[interval, share], …]]`` or null.
- ``markup_of(markup)``: for the corpus's fixture sheets with markup and ``CORPUS_MARKUPS`` seeded others, every
  literal of test_keys.py and ``EDGE_TEXTS``, and ``KEY_SHEETS``: ``{"stated": keys._stated(markup) ([key, bare] or
  null), "chords": chords_in_sheet(markup), "estimate": estimate_key(those chords), "sheet_key": [[raw, capo,
  sheet_key(raw, markup, capo)], …] for ``({}, None)`` and ``SHEET_KEYS`` seeded of ``RAWS`` by the capos 0, 2 and
  9 (a SongKey ``[key, source]``)}``.
- ``caracole.keys.estimate_key(items)``: progressions of ``viewer_corpus.progressions()`` as chord names, and
  some with seeded weights (``[name, weight]``).
- ``caracole.keys._correlation(a, b)``: ``CORRELATIONS`` seeded lists of 12 floats against each profile.
- ``caracole.keys.sheet_capo(meta)`` for each of ``METAS``.
- ``song_keys(fixture)``: a library (``helpers.corpus.dump_fixture``'s records, its files under the library
  folder) of the songs of ``LIBRARY``, and for each song ``[song id, song_key, *sheet_keys, letter_alone]``.

Regenerate: ``CARACOLE_CORPUS=write nix develop -c pytest -q -n 0 tests/test_conformance_viewer_sheet.py``, then
``nix develop ./android -c gradle -p android :viewer:test``.
"""

from __future__ import annotations

import ast
import functools
import hashlib
import json
import random
import re
from pathlib import Path

from caracole import chordpro, keys, render
from caracole.autochords.merge import AUTO_MARKER
from caracole.chordpro import display_columns, is_chord_line, merge_chord_line, normalize_chord, tag_forgotten
from caracole.chordpro import directive_text, to_chordpro
from caracole.library import keep_file
from caracole.songs import AUTO_SHEET, HUMAN_SHEET
from caracole.ug import page as ug_page
from caracole.versions import upsert_version
from caracole.viewer import page, sheet
from caracole.viewer.sheet import Blank, ChordRow, Lyrics, Section, Tab, Text, parse_sheet
from caracole.viewer.theory import parse_chord
from helpers import viewer_corpus
from helpers.corpus import check, dump_fixture, jsonl
from test_conformance_viewer_theory import chord_row, key_row

MADE_BY = "tests/test_conformance_viewer_sheet.py"
HELPER = "test_conformance_viewer_sheet."
TESTS = Path(__file__).resolve().parent
SEED = viewer_corpus.SEED + 200
BATCH = 60
SHEET_LITERALS = ("test_viewer_sheet.py", "test_viewer_preamble.py")
CHORDPRO_LITERALS = ("test_chordpro.py",)
KEYS_LITERALS = ("test_keys.py",)
# The rest of a sheet after a note, so that the note is the sheet's preamble (test_viewer_sheet.py's).
NOTE_SONG = ("", "{comment: Verse}", "[Em]words", "{comment: Chorus}", "[G]more")
# Keys and sources page._song_key is given beside a sheet's own: a key of the shapes, the tab's word, info.json's,
# another source's, a letter alone, one in a mode, and none.
SONG_KEYS = (("A", "chords"), ("Am", "tab"), ("C", None), ("Bb", "MusicBrainz  Lookup"), ("F# lydian", "audio"),
             ("not a key", "tab"), (None, None))
OTHER_KEYS = 3  # of SONG_KEYS, seeded, for each sheet besides its own
CONVERSIONS = (("Do#m", 2), (" Bb ", "3"), ("", "0"), (None, " 0 "), ("Gm", "x"), ("Sol", None))
KEY_TO = "F# minor"
CORPUS_MARKUPS = 50  # of the corpus's sheets with markup, seeded, besides its fixtures'
SHEET_KEYS = 4  # of RAWS by the capos 0, 2 and 9, seeded, for each markup besides ({}, None)
RAWS = ({}, {"tonality_name": ""}, {"tonality_name": "A"}, {"tonality_name": "Am"}, {"tonality_name": "Standard"},
        {"tonality_name": 7}, {"tonality_name": "C major"})
CORRELATIONS = 24
COLUMNS = 40
# Texts every reader above is asked about besides the tests' literals: Python's whitespace and line ends, escapes,
# entities, look-alike letters, wide and astral characters, solfège and lower-case chords, bare repeat marks.
EDGE_TEXTS = (
    "", " ", "\t", " ", "　", "a b", "a\x0bb\x0cc", "a\x1cb\x1dc\x1ed\x85e", "line\r\nnext\rlast",
    "{ Title :  Spaced Out  }", "{TITLE: Upper}", "{c:}", "{comment:auto-generated, unverified}", "{key}",
    "{ capo : 03 }", "{capo: -1}", "{capo: 99}", "{define: Am base-fret 1 frets x 0 2 2 1 0}", "{chord:}",
    "{start_of_tab: Riff}", "{sot}", "{eot}", "{eoc}", "{soc: Coro final}", "{x_custom: value}", "{bad directive}",
    "# comment", " # not a comment", "[Am]", "[*x2]", "[*]", "[]", "[ ]", "[Am] [*x02210]", "[Am]  x02210",
    "Am  x02210", "Dsus4   (xx0233)", "Em7 022033  G 320033", "Cadd9 (x32033) in the chorus", "[C]a [*N.C.]b",
    "A back\\u005cslash", "trailing\\", "\\u00e9 escaped", "<b>bold</b> & <i>", "{not a directive} here",
    "%{title} sub", "[x2] and again", "[Verse 1] [ch]Am[/ch] [ch]G[/ch]", "[Chorus] x2", "[Bridge] (x4)",
    "[ch]Do[/ch]  [ch]Rem[/ch]  [ch]Sol7[/ch]", "[ch]am[/ch] [ch]em7[/ch] dm", "Fadd9 Faug Falt",
    "[ch]Dm[/ch]    Dm/F    [ch]E[/ch]", "[tab]e|---3---|[/tab]", "e|-----0---0---|", "|-3-|", "A|--3--3--|",
    "x2", "(x4)", "2x", "(2)", "N.C.", "n.c", "×3", "[ch]C[/ch]\tx2", "\t[ch]G[/ch]\t\t[ch]D[/ch]",
    "我们一起唱", "Ａｂｃ", "é́tude", "\U0001F3B8 rock \U0001F600",
    "х2 АВ", "Русский", "ΑΟο",
    "&amp;amp;feature", "&#39;quoted&#39;", "&AMP;lt;", "&#x41;&#X42;", "&notanentity;", "&amp;#x3c;tag",
    "&ampx", "Key: G", "Key of Bb", "key = do not use", "Tono: La menor", "Tonalidad: Re", "Tonality - F#m",
    "Key: [ch]F#m[/ch]", "Tono original: Mi", "KEY:sol", "Capo 2, drop d", "Tuning: DADGAD (open)",
    "(Tuning: DADGAD)", "Eb standard tuning", "half-step down", "Drop a comment", "Tuning: Standard",
    "A", "Am", "A minor", "a min", "La", "la menor", "Do mayor", "SOL", "B♭m", "E♭", "C♯", "Hm", "Cm7", "A/E",
    "A ", " Bb major ", "Mi7", "Sib", "Fa#m",
)
# Sheets whose key keys.py reads from their words (test_keys.py's, and more).
_HOTEL = (
    "[Intro]\n[ch]Am[/ch]  [ch]E7[/ch]  [ch]G[/ch]  [ch]D[/ch]  [ch]F[/ch]  [ch]C[/ch]  [ch]Dm[/ch]  [ch]E[/ch]\n"
    + "[Verse]\n[ch]Am[/ch]  [ch]E7[/ch]\nWords go here\n[ch]G[/ch]  [ch]D[/ch]\nmore words\n"
    "[ch]F[/ch]  [ch]C[/ch]\nand more\n[ch]Dm[/ch]  [ch]E7[/ch]\nand back\n" * 3
)
_AM_F_C_G = "[Verse]\n[ch]Am[/ch]  [ch]F[/ch]  [ch]C[/ch]  [ch]G[/ch]\nWords go here\n" * 4
KEY_SHEETS = (
    _HOTEL, _AM_F_C_G, "Key: G\n\n" + _AM_F_C_G, "Tono: La\n\n" + _AM_F_C_G, "Key: A major\n\n" + _HOTEL,
    "{key: Bm}\n[ch]Bm[/ch] [ch]G[/ch]\n", "Intro: [ch]Am[/ch]\nKey: C\n", "Key: [ch]F#m[/ch]\n[ch]A[/ch]\n",
    "[ch]Cm[/ch] [ch]Ab[/ch] [ch]Eb[/ch] [ch]Bb[/ch] [ch]Cm[/ch]\nwords\n",
    "[ch]Em[/ch] [ch]C[/ch]\nwords\n[ch]N.C.[/ch] [ch]x2[/ch] [ch]Hm[/ch]\n",
    "[ch]Am7b5[/ch] [ch]D7sus4[/ch] [ch]Gmaj7[/ch] [ch]C7M[/ch] [ch]F#ø[/ch] [ch]Bdim7[/ch] [ch]E+[/ch] "
    "[ch]A5[/ch] [ch]Dsus2[/ch] [ch]Gadd9[/ch] [ch]Cm(maj7)[/ch] [ch]F13[/ch]\n",
    "[ch]Do[/ch] [ch]Lam[/ch] [ch]Fa[/ch] [ch]Sol7[/ch]\n", "", "Just words\nand no chords\n",
)
# The metas sheet_capo reads: numbers and strings as UG writes them, and what it reads as no capo.
METAS = ({"capo": 2}, {"capo": "2"}, {"capo": "2.0"}, {"capo": 2.0}, {"capo": 2.5}, {"capo": True}, {"capo": 0},
         {"capo": -1}, {"capo": "x"}, {"capo": None}, {"capo": " 3 "}, {"capo": "1e1"}, {"capo": "inf"},
         {"capo": "nan"}, {"capo": [2]}, {"capo": "３"}, {"capo": "٣"}, {"capo": "1_0"}, {}, None, [1],
         "capo", {"capo": "+4"}, {"capo": 12})


# --- the data ------------------------------------------------------------------------------------------------------


def _patterns(module, names: tuple[str, ...]) -> dict:
    out = {}
    for name in names:
        p = getattr(module, name)
        assert p.flags & ~(re.UNICODE | re.IGNORECASE) == 0, f"{name}: a flag the phone doesn't read"
        # a leading "(?i)" is the pattern's own: IGNORECASE is said only when it comes from elsewhere
        inline = p.pattern.startswith("(?i)")
        out[name] = {"pattern": p.pattern, "ignorecase": bool(p.flags & re.IGNORECASE) and not inline}
    return out


def _ranges(points: list[int]) -> list[list[int]]:
    out: list[list[int]] = []
    for cp in points:
        if out and out[-1][1] == cp - 1:
            out[-1][1] = cp
        else:
            out.append([cp, cp])
    return out


def _cp1252() -> list[list[int]]:
    found = []
    for cp in range(0x80, 0x110000):
        if 0xD800 <= cp <= 0xDFFF:
            continue
        if not render.needs_font_file(chr(cp)):
            found.append(cp)
    return _ranges(found)


def constants() -> dict:
    return {
        "sheet": {
            "patterns": _patterns(sheet, ("_DIRECTIVE", "_TOKEN", "_FRET", "_CHORUS", "_TUNING_NAME", "_TUNING_LABEL",
                                          "_CAPO")),
            "_ESCAPED_BACKSLASH": sheet._ESCAPED_BACKSLASH,
            "COMMENTS": sorted(sheet.COMMENTS),
            "_STANDARD": sorted(sheet._STANDARD),
            "AUTO_MARKER": AUTO_MARKER,
        },
        "page": {"_SOURCES": dict(page._SOURCES), "_OF_THE_SHAPES": sorted(page._OF_THE_SHAPES)},
        "chordpro": {
            "patterns": _patterns(chordpro, ("_CHORD", "_TAB_MARK", "_SECTION", "_MARK", "_CHORD_LINE_REST", "_STAFF",
                                             "_SOLFEGE", "_LEAD_GAP", "_WORD", "_MARKUP_START", "_DECODED_BACKSLASH",
                                             "_DIRECTIVE_LIKE")),
            "_SOLFEGE_LETTER": dict(chordpro._SOLFEGE_LETTER),
            "TAB_STOP": chordpro.TAB_STOP,
            "_BRACKETS": {chr(k): chr(v) for k, v in chordpro._BRACKETS.items()},
            "_ESCAPED_BACKSLASH": chordpro._ESCAPED_BACKSLASH,
        },
        "render": {
            "_LATIN_LOOKALIKES": {chr(k): v if isinstance(v, str) else chr(v)
                                  for k, v in sorted(render._LATIN_LOOKALIKES.items())},
            "cp1252": _cp1252(),
        },
        "ug_page": {"patterns": _patterns(ug_page, ("_ENTITY",))},
        "keys": {
            "patterns": _patterns(keys, ("_KEY_HEAD", "_KEY_HEAD_ENGLISH", "_KEY_LABEL", "_DIRECTIVE", "_CHORD_TAG",
                                         "_CHORD", "_QUALITY", "_ADDED", "_EXTENDED", "_MAJOR_SEVENTH")),
            "SOURCES": dict(keys.SOURCES),
            "SHEET_DOC": keys.SHEET_DOC,
            "HUMAN_SHEET": HUMAN_SHEET,
            "AUTO_SHEET": AUTO_SHEET,
            "_LETTERS": dict(keys._LETTERS),
            "_SOLFEGE": dict(keys._SOLFEGE),
            "_ACCIDENTALS": dict(keys._ACCIDENTALS),
            "_SHIFT": dict(keys._SHIFT),
            "_DIMINISHED": list(keys._DIMINISHED),
            "_PROFILES": {"major": list(keys._PROFILES[False]), "minor": list(keys._PROFILES[True])},
            "MIN_FIT": keys.MIN_FIT,
            "TONIC_SHARE": keys.TONIC_SHARE,
            "EDGE": keys.EDGE,
            "_MAJOR_NAMES": list(keys._MAJOR_NAMES),
            "_MINOR_NAMES": list(keys._MINOR_NAMES),
        },
    }


@functools.cache
def sheet_json() -> str:
    return viewer_corpus.data_json(constants())


def test_sheet_json_is_the_modules_constants():
    check(viewer_corpus.VIEWER_DATA / "sheet.json", sheet_json())


def test_the_data_reads_back_as_the_modules_hold_it():
    data = json.loads(sheet_json())
    for name, module in (("sheet", sheet), ("chordpro", chordpro), ("ug_page", ug_page), ("keys", keys)):
        for pattern_name, p in data[name]["patterns"].items():
            flags = re.IGNORECASE if p["ignorecase"] else 0
            assert re.compile(p["pattern"], flags) == getattr(module, pattern_name)
    assert set(data["sheet"]["COMMENTS"]) == sheet.COMMENTS
    assert {ord(k): ord(v) for k, v in data["chordpro"]["_BRACKETS"].items()} == chordpro._BRACKETS
    assert {ord(k): v for k, v in data["render"]["_LATIN_LOOKALIKES"].items()} == render._LATIN_LOOKALIKES
    assert {False: tuple(data["keys"]["_PROFILES"]["major"]), True: tuple(data["keys"]["_PROFILES"]["minor"])} \
        == keys._PROFILES
    encodable = {cp for first, last in data["render"]["cp1252"] for cp in range(first, last + 1)}
    assert len(encodable) == 123  # cp1252's 96 Latin-1 letters and signs, and 27 more of 0x80 to 0x9F
    assert not render.needs_font_file("".join(chr(cp) for cp in sorted(encodable)))


# --- the inputs ----------------------------------------------------------------------------------------------------


@functools.cache
def literals(names: tuple[str, ...]) -> tuple[str, ...]:
    """Every string literal of the tests ``names`` (no f-string's parts, no lone surrogate), each once, in order."""
    found: dict[str, None] = {}
    for name in names:
        tree = ast.parse((TESTS / name).read_text("utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.JoinedStr):
                for part in node.values:
                    setattr(part, "_in_fstring", True)
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str) \
                    and not getattr(node, "_in_fstring", False) and len(node.value) <= 4000:
                found[node.value] = None
    return tuple(s for s in found if not any(0xD800 <= ord(c) <= 0xDFFF for c in s))


def _texts(names: tuple[str, ...]) -> list[str]:
    return list(dict.fromkeys([*literals(names), *EDGE_TEXTS]))


def line_row(line) -> list:
    if isinstance(line, Lyrics):
        return ["L", [[c, text] for c, text in line.parts]]  # an index, a mark's text or None, as JSON tells them
    if isinstance(line, ChordRow):
        return ["C", list(line.items)]
    if isinstance(line, Text):
        return ["T", line.text]
    if isinstance(line, Tab):
        return ["Tab", list(line.lines)]
    assert isinstance(line, Blank)
    return ["B"]


def section_row(section: Section | None) -> list | None:
    if section is None:
        return None
    return [section.label, section.chorus, [line_row(line) for line in section.lines]]


def sheet_row(s: sheet.Sheet) -> dict:
    return {"title": s.title, "artist": s.artist, "key": s.key, "capo": s.capo, "auto": s.auto,
            "chords": list(s.chords), "sections": [section_row(x) for x in s.sections], "defines": list(s.defines)}


def given_row(given) -> list:
    return [[chord_row(c), position] for c, position in given]


def preamble_row(pre: sheet.Preamble) -> dict:
    return {"notes": list(pre.notes), "legend": given_row(pre.legend), "tabs": [list(t) for t in pre.tabs],
            "tuning": pre.tuning, "capo_note": pre.capo_note, "end": pre.end}


# --- vectors/viewer/sheet.jsonl ------------------------------------------------------------------------------------


def song_key(s: sheet.Sheet, key: str | None, source: str | None) -> list:
    chords = [parse_chord(name, strict=False) for name in s.chords]
    found, origin = page._song_key(s, chords, key, source)
    return [key, source, key_row(found), origin]


def digest(value) -> str:
    """The SHA-256 of ``json.dumps(value)`` (its defaults: ASCII, ``", "`` and ``": "``), for what a record holds
    only by its digest."""
    return hashlib.sha256(json.dumps(value).encode("ascii")).hexdigest()


def shown_row(s: sheet.Sheet) -> list:
    """page._shown: the preamble's row, and each section shown as its index in ``s.sections`` where it is one of
    them, else its row (the first, what follows the preamble in its section)."""
    pre, sections = page._shown(s)
    rows = []
    for x in sections:
        at = next((i for i, y in enumerate(s.sections) if y is x), None)
        rows.append(at if at is not None else section_row(x))
    return [section_row(pre), rows]


def read_of(cho: str, key: str | None, key_source: str | None, rng: random.Random) -> dict:
    s = parse_sheet(cho)
    pre, _ = page._shown(s)
    lines = cho.splitlines()
    keys_given = [(key, key_source)] + rng.sample([k for k in SONG_KEYS if k != (key, key_source)], OTHER_KEYS)
    return {
        "sheet": sheet_row(s),
        "preamble": section_row(sheet.preamble_section(s)),
        "shown": shown_row(s),
        "drawn": digest(page._drawn_lines(s)),
        "texts": digest(page._written_texts(s)),
        "peek": page._peek(pre, s.chords) if pre else None,
        "places": digest([list(p) for p in page._places(s)]),
        "played": digest(page._played(s)),
        "keys": [song_key(s, k, src) for k, src in keys_given],
        "viewer_key": key_row(page.viewer_key(cho, key, key_source)),
        "given": given_row(page._given_shapes(s)),
        "shapes": page.shapes_of(s),
        "written": digest([[sheet.written(line, s.chords) for line in x.lines] for x in s.sections]),
        "legend": [[i, j] for i, x in enumerate(s.sections) for j, line in enumerate(x.lines)
                   if sheet.is_legend(line, s.chords)],
        "directives": digest([[n, *found] for n, line in enumerate(lines)
                              if (found := sheet.directive(line)) is not None]),
        "legend_lines": [n for n, line in enumerate(lines) if sheet.is_legend_line(line)],
        "split": preamble_row(sheet.split_preamble(lines)),
    }


def sheet_lines_of(text: str) -> dict:
    found = sheet.directive(text)
    return {
        "sheet": sheet_row(parse_sheet(text)),
        "directive": None if found is None else list(found),
        "legend_line": sheet.is_legend_line(text),
        "split": preamble_row(sheet.split_preamble(text.splitlines())),
        "note": preamble_row(sheet.split_preamble([text, *NOTE_SONG])),
    }


def sheet_records() -> list[dict]:
    rng = random.Random(SEED + 4)
    out = [{"fn": HELPER + "read_of", "args": [s.cho, s.key, s.key_source],
            "out": read_of(s.cho, s.key, s.key_source, rng)} for s in viewer_corpus.sheets()]
    out += [{"fn": HELPER + "lines_of", "args": [t], "out": sheet_lines_of(t)} for t in _texts(SHEET_LITERALS)]
    return out


def test_sheet_vectors_are_the_readers_answers():
    check(viewer_corpus.VIEWER_VECTORS / "sheet.jsonl",
          jsonl(sheet_records(), corpus="viewer/sheet", made_by=MADE_BY))


# --- vectors/viewer/chordpro.jsonl ---------------------------------------------------------------------------------


def _converted(s: viewer_corpus.CorpusSheet, markup: str, key, capo) -> dict:
    kw = {"title": s.title, "artist": s.artist, "key": key, "capo": capo, "auto": s.auto}
    return {"fn": "caracole.render._chordpro_text", "args": [markup], "kw": kw,
            "out": render._chordpro_text(markup, **kw)}


def chordpro_lines_of(text: str, after: str | None) -> dict:
    out = {
        "normalize": normalize_chord(text),
        "tagged": tag_forgotten(text),
        "chord_line": is_chord_line(text),
        "columns": display_columns(text),
        "directive": directive_text(text),
        "latin": render._as_latin(text),
        "decoded": ug_page.decode_twice(text),
        "converted": to_chordpro(text, title="T", artist="A"),
    }
    if after is not None and out["chord_line"]:
        out["merged"] = [after, merge_chord_line(text, after)]
    return out


def _columns_texts() -> list[str]:
    rng = random.Random(SEED + 1)
    pool = ("a", "Z", " ", "\t", "́", "̈", "​", "我", "あ", "가", "Ａ", "　",
            "\U0001F600", "\U00020000", "é", "х", "-", "|", " ", "\x00", "\x7f", "ᄀ", "₩")
    return ["".join(rng.choice(pool) for _ in range(rng.randint(1, 24))) for _ in range(COLUMNS)]


def chordpro_records() -> list[dict]:
    out = []
    rng = random.Random(SEED)
    for s in viewer_corpus.sheets():
        if s.markup is not None:
            out.append(_converted(s, s.markup, s.key, s.capo))
    for key, capo in CONVERSIONS:  # the header alone: the body is the same whatever the key and the capo
        s = rng.choice(viewer_corpus.sheets())
        out.append(_converted(s._replace(auto=rng.random() < 0.3), "", key, capo))
    texts = _texts(CHORDPRO_LITERALS)
    for i, text in enumerate(texts):
        after = texts[i + 1] if i + 1 < len(texts) else None
        out.append({"fn": HELPER + "lines_of", "args": [text, after], "out": chordpro_lines_of(text, after)})
    out += [{"fn": "caracole.chordpro.display_columns", "args": [t], "out": display_columns(t)}
            for t in _columns_texts()]
    return out


def test_chordpro_vectors_are_the_converters_answers():
    check(viewer_corpus.VIEWER_VECTORS / "chordpro.jsonl",
          jsonl(chordpro_records(), corpus="viewer/chordpro", made_by=MADE_BY))


# --- vectors/viewer/musickeys.jsonl --------------------------------------------------------------------------------


def _batches(items: list) -> list[list]:
    return [items[i:i + BATCH] for i in range(0, len(items), BATCH)]


def named_of(text: str) -> list | None:
    found = keys._named(text)
    if found is None:
        assert keys.parse_key(text) is None
        return None
    return [keys.parse_key(text), found[1], keys.key_name(found[0]), keys.same_key(found[0], KEY_TO)]


def chord_of(name: str) -> list | None:
    found = keys._chord(name)
    if found is None:
        return None
    root, spelling, triad, tones = found
    return [root, spelling, triad, [list(t) for t in tones]]


def song_key_row(found: keys.SongKey | None) -> list | None:
    return None if found is None else [found.key, found.source]


def markup_of(markup: str, rng: random.Random) -> dict:
    stated = keys._stated(markup)
    names = keys.chords_in_sheet(markup)
    given = [({}, None)] + rng.sample([(raw, capo) for raw in RAWS for capo in (0, 2, 9)], SHEET_KEYS)
    return {
        "stated": None if stated is None else list(stated),
        "chords": names,
        "estimate": keys.estimate_key(names),
        "sheet_key": [[raw, capo, song_key_row(keys.sheet_key(raw, markup, capo))] for raw, capo in given],
    }


def _estimates() -> list[dict]:
    rng = random.Random(SEED + 2)
    out = []
    for p in viewer_corpus.progressions():
        items: list = list(p.chords)
        out.append({"fn": "caracole.keys.estimate_key", "args": [items], "out": keys.estimate_key(items)})
        if rng.random() < 0.25:
            weighted = [[name, rng.choice((0.5, 1.0, 2.0, 3.25, 0.0, -1.0, 7.0))] for name in items]
            out.append({"fn": "caracole.keys.estimate_key", "args": [weighted],
                        "out": keys.estimate_key([tuple(w) for w in weighted])})
    return out


def _correlations() -> list[dict]:
    rng = random.Random(SEED + 3)
    out = []
    for n in range(CORRELATIONS):
        flat = n == 0
        a = [0.0] * 12 if flat else [round(rng.uniform(0, 9), rng.choice((1, 2, 6))) * rng.choice((1, 0.5)) for _ in
                                      range(12)]
        for profile in (keys._PROFILES[False], keys._PROFILES[True]):
            b = [profile[(pc - n) % 12] for pc in range(12)]
            out.append({"fn": "caracole.keys._correlation", "args": [a, b], "out": keys._correlation(a, b)})
    return out


_STATES_G = "Key: G\n\n[ch]G[/ch] [ch]C[/ch] [ch]D[/ch]\nwords\n"
# Past json's RecursionError on the computer (its C stack's, about 50,000 deep) and the phone's MAX_DEPTH alike.
_TOO_DEEP = 100_000

# The songs of the library song_keys reads: (artist, title, the human sheet's (provider, raw, content, meta) or
# None, the auto sheet's raw or None, and what is done to its files after: "no json", "a list", "bom" (sheet.json
# after a UTF-8 BOM, which json.loads of its text refuses), "too deep" (nested past json's RecursionError), "other
# version", "no sheet.json", "no auto file"). A "bom" or "too deep" sheet states a key no other source gives, so a
# read that took its markup would answer it.
LIBRARY = (
    ("Placeholders", "Tonality", ("ug", {"tonality_name": "Bm"}, _AM_F_C_G, None), None, None),
    ("Placeholders", "Stated", ("ug", {}, "Key: G\n\n" + _AM_F_C_G, None), None, None),
    ("Placeholders", "Tono", ("lacuerda", {}, "Tono: Re\n\n" + _AM_F_C_G, None), None, None),
    ("Placeholders", "Hotel", ("ug", {"tonality_name": "A"}, _HOTEL, {"capo": 2}), None, None),
    ("Placeholders", "Hotel By Sound", ("ug", {"tonality_name": "B"}, _HOTEL, {"capo": "2.0"}), None, None),
    ("Placeholders", "Capo Nine", ("ug", {"tonality_name": "A"},
                                   "[ch]Am[/ch] [ch]F[/ch] [ch]C[/ch] [ch]G[/ch] [ch]Am[/ch]\nwords\n", {"capo": 9}),
     None, None),
    ("Placeholders", "Relative", ("ug", {"tonality_name": "C"},
                                  "[ch]Am[/ch] [ch]F[/ch] [ch]C[/ch] [ch]G[/ch] [ch]Am[/ch]\nwords\n", {"capo": 3}),
     None, None),
    ("Placeholders", "Tono La", ("lacuerda", {}, "Tono: La\n\n" + _AM_F_C_G, None), None, None),
    ("Placeholders", "Estimated", ("ug", {"tonality_name": ""}, _AM_F_C_G, None), None, None),
    ("Placeholders", "Not A Key", ("ug", {"tonality_name": "Standard"}, _AM_F_C_G, None), None, None),
    ("Placeholders", "Heard", None, {"model": "btc_large_voca", "key": "B minor"}, None),
    ("Placeholders", "Older Auto", None, {"model": "btc_large_voca"}, None),
    ("Placeholders", "Words Only", ("ug", {}, "Just the words\nand no chords\n", None), {"key": "C"}, None),
    ("Placeholders", "Human Wins", ("ug", {}, _AM_F_C_G, None), {"key": "C"}, None),
    ("Placeholders", "No Json", ("ug", {"tonality_name": "F"}, _AM_F_C_G, None), None, "no json"),
    ("Placeholders", "A List", ("ug", {}, _AM_F_C_G, None), None, "a list"),
    ("Placeholders", "Bom", ("ug", {}, _STATES_G, None), None, "bom"),
    ("Placeholders", "Too Deep", ("ug", {}, _STATES_G, None), None, "too deep"),
    ("Placeholders", "Other Version", ("ug", {}, _AM_F_C_G, None), None, "other version"),
    ("Placeholders", "No Sheet Json", ("ug", {"tonality_name": "Gb"}, _AM_F_C_G, None), None, "no sheet.json"),
    ("Placeholders", "No Auto File", None, {"model": "btc_large_voca"}, "no auto file"),
    ("Placeholders", "Auto Not Utf8", None, {"model": "btc_large_voca"}, "auto not utf-8"),
    ("Placeholders", "No Sheet", None, None, None),
    ("Placeholders", "Letter Stated", ("ug", {}, "Key: A\n\n" + _HOTEL, {"capo": 2}), None, None),
    ("Placeholders", "Named Major", ("ug", {}, "Key: A major\n\n" + _HOTEL, {"capo": 2}), None, None),
    ("宋冬野", "斑马，斑马", ("ug", {"tonality_name": "C"}, "[ch]C[/ch] [ch]G[/ch]\n斑马斑马\n", {"capo": "1"}),
     None, None),
)
_AUTO_TEXT = "auto-generated, unverified\nA - T\n\n[Chords]\n| [ch]Em[/ch] | [ch]C[/ch] | [ch]G[/ch] | [ch]D[/ch] |\n"


def _library(conn, library_dir: Path) -> list:
    from conftest import add_song

    from caracole.library import song_dir

    songs = []
    for n, (artist, title, human, auto, then) in enumerate(LIBRARY):
        song = add_song(conn, artist, title)
        songs.append(song)
        if human is not None:
            provider, raw, content, meta = human
            url = f"https://example.invalid/{n}"
            vid = upsert_version(conn, provider=provider, tab_id=str(n), song_id=song.id, slot="sheet",
                                 kind="chords" if provider == "ug" else "acordes", rating=4.5, votes=10, version=1,
                                 label=None, url=url, raw=raw, now="2026-11-04T00:00:00Z")
            doc_version = vid
            if then == "other version":
                doc_version = upsert_version(conn, provider=provider, tab_id=f"{n}-other", song_id=song.id,
                                             slot="sheet", kind="chords", rating=4.0, votes=1, version=2, label=None,
                                             url=url + "-other", raw={"tonality_name": "E"},
                                             now="2026-11-04T00:00:00Z")
            doc = {"version": raw, "content": content, "url": url, **({"meta": meta} if meta is not None else {})}
            if then != "no sheet.json":
                keep_file(conn, library_dir, song=song, version_id=doc_version, name=keys.SHEET_DOC,
                          data=json.dumps(doc, ensure_ascii=False).encode(), rank=1)
            keep_file(conn, library_dir, song=song, version_id=vid, name=HUMAN_SHEET,
                      data=content.replace("[ch]", "").replace("[/ch]", "").encode(), rank=1)
            folder = song_dir(library_dir, song)
            if then == "no json":
                (folder / keys.SHEET_DOC).write_text("{not json")
            elif then == "a list":
                (folder / keys.SHEET_DOC).write_text("[1, 2]")
            elif then == "bom":
                (folder / keys.SHEET_DOC).write_bytes(b"\xef\xbb\xbf" + json.dumps(doc).encode())
            elif then == "too deep":
                deep = "[" * _TOO_DEEP + "]" * _TOO_DEEP
                (folder / keys.SHEET_DOC).write_text(json.dumps(doc)[:-1] + f', "x": {deep}}}')
        if auto is not None:
            vid = upsert_version(conn, provider="auto", tab_id=str(song.id), song_id=song.id, slot="sheet",
                                 kind="auto", rating=0, votes=0, version=1, label=None, url="file:///x.flac",
                                 raw=auto, now="2026-11-04T00:00:00Z")
            keep_file(conn, library_dir, song=song, version_id=vid, name=AUTO_SHEET, data=_AUTO_TEXT.encode(), rank=1)
            folder = song_dir(library_dir, song)
            if then == "no auto file":
                (folder / AUTO_SHEET).unlink()
            elif then == "auto not utf-8":
                (folder / AUTO_SHEET).write_bytes(b"[ch]Em[/ch] \xff\xfe\n")
    out = []
    for song in songs:
        human, auto = keys.sheet_keys(conn, library_dir, song)
        out.append([song.id, song_key_row(keys.song_key(conn, library_dir, song)), song_key_row(human),
                    song_key_row(auto), keys.letter_alone(conn, library_dir, song)])
    return out


NOW = "2026-11-04T00:00:00Z"


def song_keys_record(conn, library_dir: Path) -> dict:
    out = _library(conn, library_dir)
    # every stamp caracole writes as now, made NOW: the fixture is the same on every run
    conn.execute("UPDATE songs SET created_at = ?, updated_at = ?", (NOW, NOW))
    conn.execute("UPDATE files SET created_at = ?", (NOW,))
    return {"fn": HELPER + "song_keys", "args": [dump_fixture(conn, library_dir)], "out": out}


def musickeys_records(conn, library_dir: Path) -> list[dict]:
    texts = list(dict.fromkeys(viewer_corpus.key_texts() + _texts(KEYS_LITERALS)))
    out = [{"fn": HELPER + "named_of", "args": [batch], "out": [named_of(t) for t in batch]}
           for batch in _batches(texts)]
    names = list(dict.fromkeys(viewer_corpus.chord_names() + _texts(KEYS_LITERALS)))
    out += [{"fn": HELPER + "chord_of", "args": [batch], "out": [chord_of(n) for n in batch]}
            for batch in _batches(names)]
    rng = random.Random(SEED + 5)
    marked = [s.markup for s in viewer_corpus.sheets() if s.markup is not None]
    fixtures = [s.markup for s in viewer_corpus.sheets() if s.markup is not None and s.name.startswith("fixture:")]
    markups = list(dict.fromkeys(fixtures + rng.sample(marked, CORPUS_MARKUPS) + list(KEY_SHEETS)
                                 + _texts(KEYS_LITERALS)))
    out += [{"fn": HELPER + "markup_of", "args": [m], "out": markup_of(m, rng)} for m in markups]
    out += _estimates()
    out += _correlations()
    out += [{"fn": "caracole.keys.sheet_capo", "args": [meta], "out": keys.sheet_capo(meta)} for meta in METAS]
    out.append(song_keys_record(conn, library_dir))
    return out


def test_musickeys_vectors_are_keys_pys_answers(conn, cfg):
    check(viewer_corpus.VIEWER_VECTORS / "musickeys.jsonl",
          jsonl(musickeys_records(conn, cfg.library_dir), corpus="viewer/musickeys", made_by=MADE_BY))


# --- the inputs reach what they are for ------------------------------------------------------------------------------


def test_the_sheets_reach_every_kind_of_line_and_every_way_to_a_key():
    kinds, origins = set(), set()
    for s in viewer_corpus.sheets():
        parsed = parse_sheet(s.cho)
        kinds |= {type(line).__name__ for x in parsed.sections for line in x.lines}
        for k, src in [(s.key, s.key_source), *SONG_KEYS]:
            origins.add(song_key(parsed, k, src)[3])
    assert kinds == {"Lyrics", "ChordRow", "Text", "Tab", "Blank"}
    assert {"from the tab", "guessed from the chords", "from the audio", "from the song's entry", "from the sheet",
            "from MusicBrainz Lookup"} <= origins
    assert any(sheet.split_preamble(s.cho.splitlines()).legend for s in viewer_corpus.sheets())
    assert any(sheet.preamble_section(parse_sheet(s.cho)) for s in viewer_corpus.sheets())


def test_the_capos_reach_every_answer():
    found = {keys.sheet_capo(meta) for meta in METAS}
    assert {None, 2, 3, 10, 4, 12} <= found


def test_a_sheet_json_json_can_t_read_gives_no_key_though_its_markup_states_one(conn, cfg):
    assert keys.sheet_key({}, _STATES_G) == keys.SongKey("G", "tab")
    rows = {title: row for (_, title, *_), row in zip(LIBRARY, _library(conn, cfg.library_dir), strict=True)}
    assert rows["Bom"][1:] == rows["Too Deep"][1:] == [None, None, None, None]
