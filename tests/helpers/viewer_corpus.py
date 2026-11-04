"""The seeded inputs of milestone 5's generators: the sheets, chords and keys every ``tests/test_conformance_viewer_*.py``
reads, so the Kotlin port of viewer/ is checked against one set of songs (docs/superpowers/plans/
2026-11-03-android-port-m4-m6.md, lane theory).

Everything here is a function of ``SEED`` and of caracole's own modules and fixtures, and the same in every process:
no set is iterated, nothing is hashed with Python's ``hash``, no clock or environment is read, and each answer is
computed once (``functools.cache``; a caller gets a copy of a list it may change). ``digest()`` is the SHA-256 of it
all, which ``tests/test_viewer_corpus.py`` compares across processes started with different ``PYTHONHASHSEED``\\ s.

- ``keys()``: every key, ``theory.Key`` for each of ``theory.MODES`` (in their order) and each tonic 0 to 11.
- ``chord_names()``: the chord names the generators read, in order, each once: every quality of ``theory.QUALITIES``
  as its name and as the viewer shows it (``DISPLAY``) on every root (spelled with a sharp or a flat by turns), and
  five of them on every root spelled with a sharp, a flat or neither, ``♯`` and ``♭`` too; the
  synonyms sheets write (``SYNONYMS``, each on three seeded roots, some with a slash bass); seeded suffixes made of
  ``_intervals``' parts, of which some spell no chord; ``EDGE_CHORDS``; and every chord the sheets below write.
- ``key_texts()``: the texts a tab, a tag or a sheet's ``{key}`` may name a key with, ``theory.parse_key``'s inputs:
  ``EDGE_KEY_TEXTS`` and every letter with each accidental and mode word, in seeded spacing and case.
- ``progressions()``: ``CorpusProgression``\\ s: the numerals of each progression of ``harmony.CATALOGUE`` played on
  two seeded tonics, in the minor key where it plays ``i`` and the major one else, as chord names.
- ``sheets()``: ``CorpusSheet``\\ s, by ``name``:

  - ``mode-<mode>-<tonic>``, one for every key: the mode's own chords, triads and sevenths stacked in its scale
    (``theory._diatonic_quality``), in a seeded order that starts and ends on the tonic;
  - ``catalogue-<n>-<tonic>``: each progression of ``progressions()`` in a verse and a chorus;
  - ``qualities-<n>``: every quality of ``QUALITIES`` on seeded roots, in its names and synonyms, some over a bass;
  - each drawn, by the seed, with a preamble before its first section (the tabber's notes, a link, a capo line, a
    chord legend: "Am  x02210", "Dsus4   (xx0233)"), staff tabs, ``{define}`` lines, a capo, Chinese or kana
    lyrics, an auto sheet's notice, repeat marks and bars on its chord lines; ``tags`` says which;
  - ``edge-<n>``: sheets written in ChordPro the converter never writes (``{start_of_chorus}``, ``{soc}``,
    ``{c:}``, ``#`` comments, escapes, a ``{define}`` without frets, a capo of 0, an unclosed tab, empty
    sections), ``markup`` None;
  - ``fixture:<path>``: tests/fixtures/chordpro/'s ``.cho`` files as they are and its ``.txt`` markup converted,
    and the sheet on UG's chords and ukulele pages (``ug/tab_chords.html``, ``ug/tab_ukulele.html``:
    ``ug.page.parse_tab_page``'s ``content``, its key and capo from the page's ``meta``) and on LaCuerda's version
    page (``lacuerda/version.html``: ``lacuerda.parse_version_page``), converted.

A ``CorpusSheet``'s ``cho`` is what render.py writes for its ``markup`` (``render._chordpro_text``: ``to_chordpro``
then ``_as_latin``, given its title, artist, key and capo, and ``auto``), with its ``defines`` put after the header's
lines; for an ``edge-`` sheet and a ``.cho`` fixture, the text as written. ``key`` is the key the tab names (as UG
writes it, or None) and ``key_source`` where the song's key came from (one of keys.SOURCES, None or a word of
another source), as ``page.build_viewer`` is given them. ``played`` is the sheet's chords in the order they are
played (``page._played``), as names.

A generator writes what it needs of these into its own vectors (a sheet's ``cho``, or the chord names it plays):
the Kotlin side never runs this module. So an edit here changes every generator's vectors: regenerate the corpus
(``CARACOLE_CORPUS=write nix develop -c pytest -q -n 0 tests/test_conformance_viewer_*.py``) in the same commit.

The runtime data a viewer module states (``tests/conformance/data/caracole/viewer/<module>.json``, read by Kotlin's
``viewer.ViewerData.table(module)``) is written by ``data_json``: one object, its members the module's constants
under their own names, in the order the generator gives them (no sorting, so a dict's order is Python's), an indent
of one, a final newline. It shares caracole/viewer/ on the phone's classpath with viewer/'s copied assets, so no
module's data is named ``voicings*.json`` (voicings.py's is the asset itself): ``ViewerData.table`` refuses one.
"""

from __future__ import annotations

import functools
import hashlib
import json
import random
from typing import Any, NamedTuple

from caracole import lacuerda
from caracole.chordpro import display_columns
from caracole.render import _chordpro_text
from caracole.ug.page import parse_tab_page
from caracole.viewer import harmony, page, theory
from caracole.viewer.sheet import parse_sheet
from caracole.viewer.theory import DISPLAY, MODES, QUALITIES, SCALES, Key, spelling

from helpers.corpus import DATA, FIXTURES, VECTORS

SEED = 20261104
VIEWER_DATA = DATA / "viewer"
VIEWER_VECTORS = VECTORS / "viewer"

# Spellings of a quality sheets write besides its name, each read by theory._REWRITES (or not: what Python answers
# is what the vectors hold).
SYNONYMS: dict[str, tuple[str, ...]] = {
    "": ("M", "maj", "major", "Maj"),
    "m": ("min", "mi", "-", "minor", "m(no5)"),
    "5": ("(no3)", "no3"),
    "dim": ("°", "o", "(b5)m", "mb5"),
    "aug": ("+", "+5", "(#5)", "#5"),
    "sus2": ("2", "(sus2)"),
    "sus4": ("sus", "4", "(sus4)"),
    "b5": ("(b5)", "-5", "(-5)", "5-"),
    "6": ("add6", "(6)"),
    "m6": ("-6", "min6"),
    "69": ("6/9", "6(9)", "(6/9)"),
    "m69": ("m6/9", "-6/9"),
    "7": ("dom7", "(7)"),
    "maj7": ("M7", "Δ", "Δ7", "7M", "Maj7", "ma7", "MA7", "j7"),
    "m7": ("-7", "min7", "mi7", "m(7)"),
    "mmaj7": ("m(maj7)", "mM7", "mMaj7", "minMaj7", "-Δ7", "m7M", "mMA7"),
    "m7b5": ("ø", "ø7", "m7(b5)", "-7b5", "m7-5", "min7b5"),
    "dim7": ("°7", "o7", "dim(7)"),
    "7sus4": ("7sus", "sus7", "7(sus4)"),
    "7sus2": ("7(sus2)",),
    "add9": ("(add9)", "add2", "2add"),
    "madd9": ("m(add9)", "-add9", "madd2"),
    "add11": ("(add11)", "add4"),
    "9": ("7(9)", "(9)", "dom9"),
    "maj9": ("M9", "Δ9", "maj7(9)"),
    "m9": ("-9", "min9", "m7(9)"),
    "9sus4": ("9sus", "sus9"),
    "11": ("7(11)", "9(11)"),
    "m11": ("-11", "min11"),
    "13": ("7(13)", "9(13)"),
    "7b5": ("7(b5)", "7-5"),
    "aug7": ("+7", "7+5", "7#5", "7+", "7(#5)"),
    "7b9": ("7(b9)", "7-9"),
    "7#9": ("7(#9)", "7+9"),
}
# Chord names at the edges of parse_chord: no chord at all, a suffix it can't read, spaces, other scripts, a slash
# that is no bass.
EDGE_CHORDS = (
    "", " ", "N.C.", "NC", "x2", "(x4)", "H", "h", "c", "Cb", "B#", "E#", "Fb", "C##", "Cbb", "C/", "C/H", "C/c",
    "C/E/G", "C6/9/E", "Cm/Eb", " Am7 ", "\tG\n", "　D　", "C ", "Am ", "C​", "Cfoo",
    "Cmfoo", "Cmajfoo", "Cm7foo", "Cfoo/E", "Cmaj13", "Cmaj11", "Cm13", "C7b13", "C7#11", "C7b11", "C7#13",
    "Cadd13", "Cadd6", "C9b5", "C9#5", "C13b9", "C7b9#9", "C7#9b9", "Cno5", "Cno3", "C5no3", "Cmaj6", "Cmaj69",
    "Cmmaj", "Cmaj", "CMaj", "CMA", "Cmajor", "Cminor", "Cmin", "Cmi", "Cm", "CM", "Cma", "Cmadd9", "Cmaj7sus4",
    "Csus4add9", "Csus2sus4", "Csus24", "C7sus4b9", "Cdim9", "Cdim7b9", "Caug9", "C+9", "C+add9", "C++", "C+-",
    "C-5", "C(9)", "C(11)", "C(13)", "C7(9)", "C7(11)", "C7(13)", "C9(13)", "C(b9)", "C ( b9 )", "C m 7", "Cm 7",
    "C♯", "D♭m", "E♭maj7", "F♯ø", "B♭/A♭", "A♯m7♭5", "G𝄪", "C😀", "Am😀", "С", "Аm", "Ｃ", "Ｃm", "C²", "C٧",
    "C७", "Cᵐ", "Cⁱ", "CΔ", "CΔ9", "CΔ#11", "C°", "Co", "Cø", "Cø9", "C-Δ", "C-maj7", "Cm-7", "C7-", "C9+",
    "C13+", "C7+9", "C+(b9)", "Bm7/F#", "G/B", "D/F#", "Am/G", "Fmaj7/C", "E7/G#", "C/Bb", "Dm7/C", "Asus2/E",
    "B7/D#", "F/G", "G7/F", "Em/D", "A/C#", "Cadd9/E", "Dsus4/F#", "C♭", "B♯",
)
# Texts that name a key or don't: parse_key's edges (a mode in any case, IGNORECASE's odd letters, no letter).
EDGE_KEY_TEXTS = (
    "", " ", "A", "a", "Am", "am", "AM", "A minor", "A Minor", "A MINOR", "A min", "A major", "A maj", "AMajor",
    "A dorian", "A Dorian", "a DORIAN", "D mixolydian", "E phrygian", "F lydian", "B locrian", "C ionian",
    "A aeolian", "F#m", "F♯m", "Bb", "B♭", "Bbm", "Ebmajor", "G#", "Ab", "Db minor", "C#", "Cb", "Fb", "E#", "B#",
    " C ", "\tD\n", "　E", "C ", "H", "Hm", "X", "Am7", "Cmaj7", "C7", "C/G", "Am/C", "A m", "A  m",
    "A mi", "A mino", "A minorr", "A-", "A min.", "Am.", "A m.", "Do", "La m", "Sol", "A mınor", "A MİNOR",
    "A mİnor", "A DORİAN", "A Mıxolydian", "A ſ", "Ab Aeolıan", "AΜ", "Ａ", "Ａm", "C#M", "cm", "c#", "bb", "ebm",
    "A dorian ", "A  dorian", "Adorian", "Aionian", "Alocrian", "A minor key", "Key: A", "A or Am",
)

_ROOT_SPELLINGS = tuple(letter + accidental for letter in "CDEFGAB" for accidental in ("", "#", "b"))
_UNICODE_ROOTS = ("C♯", "D♭", "F♯", "G♭", "A♭", "B♭", "E♭", "C♭", "B♯")
_PARTS = ("m", "dim", "aug", "maj", "6", "7", "9", "11", "13", "69", "sus2", "sus4", "sus", "add9", "add2",
          "add11", "add4", "add6", "add13", "b5", "#5", "b9", "#9", "b11", "#11", "b13", "#13", "no3", "no5",
          "(", ")", "+", "-", "M", "Δ", "ø", "°", "/9", " ")
_ROMANS = ("VII", "VI", "IV", "V", "III", "II", "I")
_DEGREE = {"I": 0, "II": 1, "III": 2, "IV": 3, "V": 4, "VI": 5, "VII": 6}

_LATIN_WORDS = ("tiny", "test", "words", "go", "here", "made", "up", "only", "for", "a", "parser", "sing", "it",
                "out", "softly", "now", "and", "the", "night", "is", "long", "corazón", "canción", "mañana",
                "noche", "Straße", "über", "naïve", "café", "rock'n'roll", "don't", "I'm", "(oh)", "yeah", "la",
                "na-na", "hey!", "you", "me", "we", "river", "road", "home", "away", "blue", "light", "rain")
_HAN = "我们一起唱歌月亮代表我的心斑马南山南爱情故事你说过的话遥远的地方愛情說話聽見發髮著着開門風吹過來了"
_KANA = "さくらのはながさいているよるにかけるありがとうカタカナテストきみとぼくのうたーっゃゅょ"
_SECTIONS = ("Intro", "Verse 1", "Verse 2", "Verse", "Pre-Chorus", "Chorus", "Bridge", "Solo", "Interlude",
             "Outro", "Coro", "Estribillo", "Estrofa", "Puente", "Refrain", "副歌", "主歌", "間奏", "サビ")
_SHAPES = (("Am", "x02210"), ("C", "x32010"), ("G", "320003"), ("D", "xx0232"), ("E", "022100"),
           ("Em", "022000"), ("F", "133211"), ("Dm", "xx0231"), ("A", "x02220"), ("E7", "020100"),
           ("Em7", "022033"), ("Cadd9", "x32033"), ("Dsus4", "xx0233"), ("A7sus4", "x02033"), ("G/B", "x20003"),
           ("Bm", "x24432"), ("F#m", "244222"), ("B7", "x21202"))
_DEFINES = ("{define: Am base-fret 1 frets x 0 2 2 1 0}", "{define: Cadd9 base-fret 1 frets x 3 2 0 3 3}",
            "{define: Bm base-fret 2 frets x 1 3 3 2 1 fingers 0 1 3 4 2 1}", "{chord: D/F# base-fret 1 frets 2 x 0 2 3 2}",
            "{define: G base-fret 1 frets 3 2 0 0 0 3}", "{define: Fmaj7 frets x x 3 2 1 0}",
            "{define: E7 base-fret 1 frets 0 2 0 1 0 0}", "{define: Cm base-fret 3 frets x 1 3 3 2 1}",
            "{define: Csus2 keys 0 2 7}", "{define: X frets x x x x x x}")
_HEAD = ("{title:", "{artist:", "{key:", "{capo:")  # the lines to_chordpro's header starts with
_STAFF = ("e|-----0---0---|", "B|---1---1---1-|", "G|-2-----------|", "D|-------------|", "A|-3-----------|",
          "E|-------------|")


class CorpusSheet(NamedTuple):
    """One sheet of the corpus (the module's docstring says each field)."""

    name: str
    title: str
    artist: str
    key: str | None
    key_source: str | None
    capo: int | None
    auto: bool
    markup: str | None
    defines: tuple[str, ...]
    cho: str
    tags: tuple[str, ...]
    played: tuple[str, ...]


class CorpusProgression(NamedTuple):
    """A progression of harmony.CATALOGUE on one key: its catalogue name and row, the key, its numerals, and the
    chord names that play them there."""

    name: str
    row: int
    key: Key
    numerals: tuple[str, ...]
    chords: tuple[str, ...]


# --- keys and chords ------------------------------------------------------------------------------------------------


@functools.cache
def _keys() -> tuple[Key, ...]:
    return tuple(Key(tonic, mode) for mode in MODES for tonic in range(12))


def keys() -> list[Key]:
    """Every key: each mode of MODES, in order, on each tonic 0 to 11."""
    return list(_keys())


def chord_name(root: int, quality: str, key: Key | None = None, bass: int | None = None, suffix: str | None = None) -> str:
    """A chord's name as a sheet in ``key`` writes it (``theory.spelling``): its root, ``suffix`` (else the quality as
    the viewer shows it, DISPLAY), and ``/bass``."""
    names = spelling(key)
    shown = DISPLAY.get(quality, quality) if suffix is None else suffix
    return names[root % 12] + shown + ("" if bass is None else "/" + names[bass % 12])


@functools.cache
def _chord_names() -> tuple[str, ...]:
    rng = random.Random(SEED)
    found: dict[str, None] = {}
    for root in range(12):
        for quality in QUALITIES:
            spelled = (theory.SHARPS, theory.FLATS)[(root + len(quality)) % 2][root]
            found[spelled + quality] = None
            found[spelled + DISPLAY.get(quality, quality)] = None
    for root in _ROOT_SPELLINGS + _UNICODE_ROOTS:
        for quality in ("", "m", "7", "maj7", "m7b5"):
            found[root + quality] = None
    for quality, synonyms in SYNONYMS.items():
        for synonym in synonyms:
            for root in rng.sample(_ROOT_SPELLINGS + _UNICODE_ROOTS, 3):
                found[root + synonym] = None
            if rng.random() < 0.5:
                found[rng.choice(_ROOT_SPELLINGS) + synonym + "/" + rng.choice(_ROOT_SPELLINGS)] = None
    for _ in range(240):
        suffix = "".join(rng.choice(_PARTS) for _ in range(rng.randint(1, 4)))
        name = rng.choice(_ROOT_SPELLINGS + _UNICODE_ROOTS) + suffix
        if rng.random() < 0.25:
            name += "/" + rng.choice(_ROOT_SPELLINGS + _UNICODE_ROOTS)
        found[name] = None
    for name in EDGE_CHORDS:
        found[name] = None
    for sheet in _sheets():
        for name in parse_sheet(sheet.cho).chords:
            found[name] = None
    return tuple(found)


def chord_names() -> list[str]:
    """Every chord name the generators read (the module's docstring says which), each once, in a fixed order."""
    return list(_chord_names())


@functools.cache
def _key_texts() -> tuple[str, ...]:
    rng = random.Random(SEED + 1)
    words = ("", "m", "M", "min", "minor", "maj", "major", *MODES)
    found: dict[str, None] = dict.fromkeys(EDGE_KEY_TEXTS)
    for letter in "CDEFGAB":
        for accidental in ("", "#", "b", "♯", "♭"):
            for word in words:
                text = rng.choice((letter, letter.lower())) + accidental
                if word:
                    word = rng.choice((word, word.upper(), word.capitalize()))
                    text += rng.choice(("", " ", "  ", "\t")) + word
                found[rng.choice(("", " ", "\n")) + text + rng.choice(("", "", " ", " "))] = None
    return tuple(found)


def key_texts() -> list[str]:
    """parse_key's inputs: EDGE_KEY_TEXTS, then every letter with each accidental and mode word, seeded."""
    return list(_key_texts())


# --- progressions ---------------------------------------------------------------------------------------------------


def _numeral(numeral: str, key: Key) -> tuple[int, str]:
    """The root and quality a Roman numeral of harmony.CATALOGUE names in ``key``: its degree of the tonic's major
    scale moved by its accidental, a minor triad in lower case, a diminished one with "°", and "V/x" the major chord
    a fifth above the root of ``x``."""
    if "/" in numeral:
        upper, target = numeral.split("/")
        root, _ = _numeral(target, key)
        degree_root, quality = _numeral(upper, Key(root, "ionian"))
        return degree_root, quality
    shift = 0
    while numeral[:1] in ("♭", "♯", "b", "#"):
        shift += -1 if numeral[0] in ("♭", "b") else 1
        numeral = numeral[1:]
    roman = next(r for r in _ROMANS if numeral.upper().startswith(r))
    rest = numeral[len(roman):]
    minor = numeral[: len(roman)].islower()
    quality = "dim" if rest.startswith("°") else "m" if minor else ""
    return (key.tonic + SCALES["ionian"][_DEGREE[roman]] + shift) % 12, quality


@functools.cache
def _progressions() -> tuple[CorpusProgression, ...]:
    rng = random.Random(SEED + 2)
    out = []
    for row, (name, numerals, _) in enumerate(harmony.CATALOGUE):
        mode = "aeolian" if "i" in numerals else "ionian"
        for tonic in sorted(rng.sample(range(12), 2)):
            key = Key(tonic, mode)
            chords = tuple(chord_name(*_numeral(n, key), key) for n in numerals)
            out.append(CorpusProgression(name, row, key, tuple(numerals), chords))
    return tuple(out)


def progressions() -> list[CorpusProgression]:
    """Each progression of harmony.CATALOGUE on two seeded tonics, in its major or minor key."""
    return list(_progressions())


# --- sheets ---------------------------------------------------------------------------------------------------------


def _width(text: str) -> int:
    return display_columns(text)[-1]


def _lyric(rng: random.Random, script: str) -> str:
    if script == "chinese":
        return "".join(rng.choice(_HAN) for _ in range(rng.randint(4, 12)))
    if script == "kana":
        return "".join(rng.choice(_KANA + _HAN[:6]) for _ in range(rng.randint(4, 12)))
    return " ".join(rng.choice(_LATIN_WORDS) for _ in range(rng.randint(3, 8)))


def _chord_line(rng: random.Random, chords: list[str], width: int) -> str:
    """UG's chord line: each chord ``[ch]X[/ch]`` at a display column, left to right, within ``width`` or past it."""
    out, column = "", 0
    for i, name in enumerate(chords):
        room = max(width - column, 1) // max(len(chords) - i, 1)
        at = column + (rng.randint(0, max(room - 1, 0)) if i else rng.choice((0, 0, 1, 2)))
        out += " " * (at - column) + f"[ch]{name}[/ch]"
        column = at + len(name) + 1
        out += " "
    return out.rstrip()


def _bar_line(rng: random.Random, chords: list[str]) -> str:
    """A line of chords alone: plain, in bars, with beat slashes, or a repeat mark."""
    shape = rng.randrange(4)
    if shape == 0:
        return "  ".join(f"[ch]{c}[/ch]" for c in chords)
    if shape == 1:
        return "| " + " | ".join(f"[ch]{c}[/ch] / / /" for c in chords) + " |"
    mark = rng.choice(("x2", "(x4)", "2x", "x3", "(2)", "N.C."))
    return "  ".join(f"[ch]{c}[/ch]" for c in chords) + "  " + mark


def _section(rng: random.Random, label: str, chords: list[str], script: str) -> list[str]:
    lines = [f"[{label}]"]
    if label in ("Intro", "Interlude", "Solo", "Outro", "間奏"):
        return lines + [_bar_line(rng, chords)]
    for i in range(0, len(chords), 2):
        pair = chords[i:i + 2]
        words = _lyric(rng, script)
        chord_line = _chord_line(rng, pair, _width(words))
        if rng.random() < 0.4:
            lines.append(f"[tab]{chord_line}\n{words}[/tab]")
        else:
            lines += [chord_line, words]
    return lines


def _preamble(rng: random.Random, capo: int | None) -> tuple[list[str], bool]:
    lines = [rng.choice(("This is a made-up note about the version played that night",
                         "Tabbed by a made-up tabber, standard tuning",
                         "Afinación estándar, una nota inventada",
                         "这是一个合成的说明"))]
    if rng.random() < 0.5:
        lines.append("http://example.com/watch?v=placeholder&feature=related")
    if capo:
        lines.append(rng.choice((f"Capo {capo}", f"Capo on fret {capo}", f"capo {capo}. fret")))
    legend = rng.random() < 0.6
    if legend:
        lines += ["", "                  EADGBe"]
        for name, frets in rng.sample(_SHAPES, rng.randint(2, 5)):
            lines.append(rng.choice((f"{name}  {frets}", f"{name}   ({frets})", f"{name}: {frets}")))
        if rng.random() < 0.3:
            (a, fa), (b, fb) = rng.sample(_SHAPES, 2)
            lines.append(f"{a} {fa}  {b} {fb}")
    return lines + [""], legend


def _staff(rng: random.Random) -> list[str]:
    rows = list(_STAFF[: rng.choice((3, 6))])
    return ["[tab]" + "\n".join(rows) + "[/tab]"] if rng.random() < 0.5 else rows


def _sheet(name: str, rng: random.Random, chords: list[str], *, key_named: str | None, title: str,
           tags: list[str], extra_sections: int = 2) -> CorpusSheet:
    script = "chinese" if rng.random() < 0.12 else "kana" if rng.random() < 0.1 else "latin"
    capo = rng.choice((None, None, None, 1, 2, 3, 4, 5, 7)) if rng.random() < 0.45 else None
    auto = rng.random() < 0.08
    lines: list[str] = []
    if rng.random() < 0.3:
        preamble, legend = _preamble(rng, capo)
        lines += preamble
        tags.append("preamble")
        if legend:
            tags.append("legend")
    labels = ["Intro", "Verse 1", "Chorus"] + rng.sample(_SECTIONS, extra_sections)
    for label in labels:
        lines += _section(rng, label, chords if label != "Intro" else chords[:4], script)
        lines.append("")
    if rng.random() < 0.25:
        lines += ["[Riff]", *_staff(rng), ""]
        tags.append("tab")
    lines += _section(rng, "Outro", chords[-2:], script)
    markup = "\n".join(lines) + "\n"
    defines = tuple(rng.sample(_DEFINES, rng.randint(1, 3))) if rng.random() < 0.15 else ()
    if defines:
        tags.append("define")
    if capo:
        tags.append("capo")
    if script != "latin":
        tags.append(script)
    if auto:
        tags.append("auto")
    key_source = rng.choice((None, "tab", "tab", "chords", "audio", "musicbrainz")) if key_named or rng.random() < 0.3 \
        else None
    artist = rng.choice(("The Placeholders", "Los Inventados", "合成乐队", "架空バンド", "Made Up & The Tests"))
    return _converted(name, title, artist, key_named, key_source, capo, auto, markup, defines, tuple(tags))


def _converted(name: str, title: str, artist: str, key: str | None, key_source: str | None, capo: int | None,
               auto: bool, markup: str, defines: tuple[str, ...], tags: tuple[str, ...]) -> CorpusSheet:
    cho = _chordpro_text(markup, title=title, artist=artist, key=key, capo=capo, auto=auto)
    if defines:
        lines = cho.split("\n")
        head = next(i for i, line in enumerate(lines) if not line.startswith(_HEAD))
        cho = "\n".join(lines[:head] + list(defines) + lines[head:])
    return _with_played(CorpusSheet(name, title, artist, key, key_source, capo, auto, markup, defines, cho, tags, ()))


def _with_played(sheet: CorpusSheet) -> CorpusSheet:
    parsed = parse_sheet(sheet.cho)
    return sheet._replace(played=tuple(parsed.chords[i] for i in page._played(parsed)))


def _named(rng: random.Random, key: Key) -> str | None:
    """The key a tab names for a sheet in ``key``: none, its letter alone, its name, or its mode spelled out."""
    tonic = spelling(key)[key.tonic]
    return rng.choice((None, tonic, theory.key_name(key), f"{tonic} {key.mode}", tonic + " minor", tonic + "m"))


def _mode_sheets() -> list[CorpusSheet]:
    rng = random.Random(SEED + 3)
    out = []
    for key in _keys():
        steps = SCALES[key.mode]
        degrees = [0] + rng.sample(range(1, 7), 6) + [0]
        chords = []
        for degree in degrees:
            root = (key.tonic + steps[degree]) % 12
            quality = theory._diatonic_quality(root, key, rng.choice((3, 3, 4)))
            chords.append(chord_name(root, quality, key))
        name = f"mode-{key.mode}-{key.tonic}"
        out.append(_sheet(name, rng, chords, key_named=_named(rng, key), title=f"In {theory.key_name(key)}",
                          tags=["mode"]))
    return out


def _catalogue_sheets() -> list[CorpusSheet]:
    rng = random.Random(SEED + 4)
    out = []
    for p in _progressions():
        chords = list(p.chords) * 2
        name = f"catalogue-{p.row}-{p.key.tonic}"
        out.append(_sheet(name, rng, chords, key_named=_named(rng, p.key), title=p.name.capitalize(),
                          tags=["catalogue"], extra_sections=1))
    return out


def _quality_sheets() -> list[CorpusSheet]:
    rng = random.Random(SEED + 5)
    out = []
    for n in range(8):
        chords = []
        for quality in QUALITIES:
            root = rng.randrange(12)
            key = rng.choice(_keys())
            suffix = rng.choice((None, None, *SYNONYMS.get(quality, ())))
            bass = rng.randrange(12) if rng.random() < 0.15 else None
            chords.append(chord_name(root, quality, key, bass, suffix))
        rng.shuffle(chords)
        out.append(_sheet(f"qualities-{n}", rng, chords, key_named=None, title=f"Every chord {n}",
                          tags=["qualities"], extra_sections=0))
    return out


EDGE_SHEETS = (
    "{title: Chorus Environments}\n{artist: The Placeholders}\n{key: Em}\n\n{start_of_chorus}\n[Em]Sing the [C]chorus "
    "[G]now [D]\n{end_of_chorus}\n\n{soc: Chorus 2}\n[Am]And a[D]gain\n{eoc}\n{c: Coda}\n[Em] [*x2]\n",
    "{t: Comments And Escapes}\n{artist: The Placeholders}\n# a comment line\n{c: Verse}\n[G]A back\\u005cslash "
    "[D]and [*N.C.]words\n{ci: Chorus}\n[C]Ita[G]lic\n{cb: Bridge}\n{highlight: Coro}\n[Am]\n",
    "{title: Defines Only}\n{artist: The Placeholders}\n{define: Am base-fret 1 frets x 0 2 2 1 0}\n{define: Am7}\n"
    "{chord: C}\n{define: Xyz frets 1 2 3}\n[Am]Words [Am7]more [C]words\n",
    "{title: Capo Zero}\n{artist: The Placeholders}\n{capo: 0}\n{key: }\n[C]No capo [G]here\n{capo: x}\n",
    "{title: Unclosed Tab}\n{artist: The Placeholders}\n{comment: Riff}\n{start_of_tab}\ne|---0---|\nB|---1---|\n",
    "{title: Empty Sections}\n{artist: The Placeholders}\n{comment: Intro}\n{comment: Verse}\n\n\n{comment: Outro}\n"
    "[C]\n",
    "{title: 斑马，斑马}\n{artist: 宋冬野}\n{key: C}\n{comment: 主歌}\n[C]斑马斑马 你[G]不要睡着啦\n[Am]再给我看看你受伤的[F]尾巴\n"
    "{comment: 副歌}\n[F]我的[G]心[C]\n",
    "{title: 夜に駆ける}\n{artist: 架空バンド}\n{key: Bbm}\n{capo: 1}\n{comment: サビ}\n[Am]沈むように[F]溶けてゆくように\n"
    "[G]二人だけの[C]空が広がる夜に\n",
    "{title: Repeats And Bars}\n{artist: The Placeholders}\n{key: A}\n{comment: Intro}\n[A] [*| ][D] [*/ / /] [E7] "
    "[*(x4)]\n[A]  [D]\n{comment: Verse}\n[A]Words [D]and [E7]more [*x2]\n",
    "{title: Auto}\n{artist: The Placeholders}\n{comment: auto-generated, unverified}\n[Am]La [F]la [C]la [G]la\n",
)


def _edge_sheets() -> list[CorpusSheet]:
    out = []
    for n, cho in enumerate(EDGE_SHEETS):
        parsed = parse_sheet(cho)
        out.append(_with_played(CorpusSheet(f"edge-{n}", parsed.title, parsed.artist, parsed.key, None,
                                            parsed.capo, parsed.auto, None, (), cho, ("edge",), ())))
    return out


def _fixture_sheets() -> list[CorpusSheet]:
    out = []
    folder = FIXTURES / "chordpro"
    for path in sorted(folder.iterdir(), key=lambda p: p.name):
        name = "fixture:chordpro/" + path.name
        text = path.read_text(encoding="utf-8")
        if path.suffix == ".cho":
            parsed = parse_sheet(text)
            out.append(_with_played(CorpusSheet(name, parsed.title, parsed.artist, parsed.key, "tab", parsed.capo,
                                                parsed.auto, None, (), text, ("fixture",), ())))
        elif path.suffix == ".txt":
            tags = ("fixture", "chinese") if path.name.startswith("zh") else ("fixture",)
            out.append(_converted(name, "Synthetic Test Song", "The Placeholders", None, None, None, False, text, (),
                                  tags))
    for path in ("ug/tab_chords.html", "ug/tab_ukulele.html"):
        tab_page = parse_tab_page((FIXTURES / path).read_bytes())
        meta = tab_page.meta
        key = meta.get("tonality") if isinstance(meta.get("tonality"), str) else None
        capo = meta.get("capo") if isinstance(meta.get("capo"), int) else None
        out.append(_converted("fixture:" + path, tab_page.tab.song_name, tab_page.tab.artist_name, key or None,
                              "tab" if key else None, capo, False, tab_page.content or "", (), ("fixture", "ug")))
    markup = lacuerda.parse_version_page((FIXTURES / "lacuerda" / "version.html").read_text(encoding="utf-8"))
    out.append(_converted("fixture:lacuerda/version.html", "Baila la lluvia", "Los Placeholders", None, None, None,
                          False, markup, (), ("fixture", "lacuerda")))
    return out


@functools.cache
def _sheets() -> tuple[CorpusSheet, ...]:
    return tuple(_mode_sheets() + _catalogue_sheets() + _quality_sheets() + _edge_sheets() + _fixture_sheets())


def sheets() -> list[CorpusSheet]:
    """Every sheet of the corpus, in a fixed order: the modes', the catalogue's, the qualities', the edges', the
    fixtures'."""
    return list(_sheets())


def sheet(name: str) -> CorpusSheet:
    """The sheet called ``name``."""
    return next(s for s in _sheets() if s.name == name)


# --- what a generator writes --------------------------------------------------------------------------------------


def data_json(constants: dict[str, Any]) -> str:
    """A ``data/caracole/viewer/<module>.json``'s text: ``constants`` in their order, an indent of one, a newline.

    Never for a ``voicings*`` module: its name is an asset's of viewer/ on the phone's classpath."""
    return json.dumps(constants, ensure_ascii=False, indent=1) + "\n"


def digest() -> str:
    """The SHA-256 of every input above, in order: the same in every process."""
    everything = {
        "keys": [[k.tonic, k.mode] for k in _keys()],
        "chord_names": list(_chord_names()),
        "key_texts": list(_key_texts()),
        "progressions": [[p.name, p.row, p.key.tonic, p.key.mode, list(p.numerals), list(p.chords)]
                         for p in _progressions()],
        "sheets": [list(s._replace(defines=list(s.defines), tags=list(s.tags), played=list(s.played)))
                   for s in _sheets()],
    }
    text = json.dumps(everything, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


__all__ = [
    "SEED", "VIEWER_DATA", "VIEWER_VECTORS", "SYNONYMS", "EDGE_CHORDS", "EDGE_KEY_TEXTS", "EDGE_SHEETS",
    "CorpusSheet", "CorpusProgression", "keys", "chord_name", "chord_names", "key_texts", "progressions", "sheets",
    "sheet", "data_json", "digest",
]
