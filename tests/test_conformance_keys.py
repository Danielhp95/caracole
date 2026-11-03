"""Identity keys and name forms, for the phone: normalize.py's data, and what it answers, for core.keys.

core.keys.Normalize ports normalize.py (all of it but OpenCC), lacuerda_index.name_key and title_key, and
core.keys.SafeName library.safe_name and song_folder. The logic is Kotlin's; everything normalize.py states as data
is written here, from the module itself, so a change to a table or a pattern regenerates the data the phone reads
and the phone follows it.

The data, a main resource of the phone's ``:core`` (caracole/keys/ on its classpath), UTF-8:

- ``t2s.txt``: ``_t2s_table()``, Traditional characters to Simplified ones, a pair a line,
  ``<traditional> <simplified>`` as lowercase hex code points, by the Traditional one's code point (the table
  ``str.maketrans`` makes of ``_T2S_PAIRS``, a later pair of one character winning, as it does).
- ``tables.json``: one object (sorted keys, an indent of one, a final newline), each member a constant of
  normalize.py or library.py under its own name:

  - ``KEY_VERSION`` and ``MAX_NAME_BYTES``: numbers;
  - ``_TRANSLIT``: ``{character: what it becomes}``;
  - ``_APOSTROPHES``: the characters its class holds, as one string, in code point order;
  - ``_CJK`` and ``_HAN``: ``[[first, last], …]``, the code points each class matches, inclusive, in order, neither
    overlapping nor touching;
  - ``VARIANT_TOKENS``, ``_HANGUL_INITIALS``, ``_HANGUL_MEDIALS`` and ``_HANGUL_FINALS``: arrays, in their order
    (a jamo's spellings are one string, space-separated, as normalize.py writes them);
  - ``GENERIC_WORDS``, ``_PLACEHOLDER_ARTISTS``, ``_ARTIST_DROPPED``, ``_TITLE_DROPPED``, ``_SPANISH_ARTICLES``,
    ``_GEMINATE`` and ``_LONG``: sets, as arrays in code point order;
  - ``_NUMBER_WORDS``, ``_KANA``, ``_SMALL_Y`` and ``_SMALL_VOWELS``: objects (a kana's spellings space-separated);
  - ``patterns``: ``{name: {"pattern": text, "ignorecase": bool}}``, every compiled pattern of normalize.py
    (``_DASH_SUFFIX``, ``_PAREN_FEAT``, ``_PAREN_SUFFIX``, ``_ACOUSTIC_WORD``, ``_LIVE_WORD``, ``_PART_BREAK``,
    ``_FEATURING``, ``_BRACKETED``, ``_MORA``) and library.py's ``_RESERVED``, as Python writes it (``.pattern``),
    with no flag but IGNORECASE. core.keys rewrites each into java.util.regex's syntax as Python reads it:
    ``.`` and ``$`` as Python means them, ``\\v`` as U+000B, ``\\s \\w \\d \\b`` through core.py.PyRegex, and
    IGNORECASE as sre's classes (core.py.PyUnicode.ignoreCaseKey).

The vectors (``helpers.corpus.jsonl``), each record ``{"fn": "caracole.<module>.<name>", "args": […], "out": …}``,
or ``"err": "<exception class>"`` where Python raises:

- ``vectors/keys/fold.jsonl``: ``fold`` of every code point whose fold differs from itself (no surrogate), then
  ``FOLD_STRINGS`` seeded random strings mixing scripts, combining marks, Hangul, Greek sigma and supplementary
  planes.
- ``vectors/keys/slug.jsonl``: ``slug_key``, ``ug_slug_key`` (of the inputs and of slugs made from them),
  ``compact`` and ``split_variant`` (of the inputs' keys and variant-suffixed ones).
- ``vectors/keys/identity.jsonl``: ``KEY_VERSION`` first (``args`` empty), then ``identity_key``, ``clean_title``,
  ``title_variant``, ``canonical_variant``, ``display_key``, ``without_featuring``, ``placeholder_artist``,
  ``has_han``, ``has_other_script``, ``simplified``, ``romanize``, ``name_words``, ``holds_run``, and
  lacuerda_index's ``name_key`` and ``title_key``.
- ``vectors/keys/name_forms.jsonl``: ``name_forms``, ``listing_forms`` and ``original_part``.
- ``vectors/keys/safe_name.jsonl``: library's ``safe_name`` and ``song_folder``.

The inputs are every string literal of ``LITERALS_FROM`` (their syntax trees' str constants, sorted, lone
surrogates left out), ``EDGES`` and ``NAMES`` seeded random names built to reach the rules: version suffixes in
English, Spanish and Portuguese, featurings in any bracket's width, names in two scripts with their romanizations
and translations, IGNORECASE's odd letters (ı, ſ, K), exotic spaces and digits. A two-argument function pairs each
input with another, a seeded permutation's.
"""

from __future__ import annotations

import ast
import functools
import json
import random
import re
import unicodedata
from pathlib import Path

from caracole import lacuerda_index, library, normalize
from helpers.corpus import DATA, VECTORS, check, jsonl

MADE_BY = "tests/test_conformance_keys.py"
KEYS_DATA = DATA / "keys"
KEYS_VECTORS = VECTORS / "keys"
TESTS = Path(__file__).resolve().parent
LITERALS_FROM = ("test_normalize.py", "test_ug_names_adversarial.py", "test_song_names.py", "test_search.py",
                 "test_lacuerda_index.py")

SEED = 20261103
FOLD_STRINGS = 2000
CHARS_A_RECORD = 100
NAMES = 600

N = "caracole.normalize."
PATTERNS = ("_DASH_SUFFIX", "_PAREN_FEAT", "_PAREN_SUFFIX", "_ACOUSTIC_WORD", "_LIVE_WORD", "_PART_BREAK",
            "_FEATURING", "_BRACKETED", "_MORA")
LISTS = ("VARIANT_TOKENS", "_HANGUL_INITIALS", "_HANGUL_MEDIALS", "_HANGUL_FINALS")
SETS = ("GENERIC_WORDS", "_PLACEHOLDER_ARTISTS", "_ARTIST_DROPPED", "_TITLE_DROPPED", "_SPANISH_ARTICLES",
        "_GEMINATE", "_LONG")
MAPS = ("_NUMBER_WORDS", "_KANA", "_SMALL_Y", "_SMALL_VOWELS")


def _no_surrogate(s: str) -> bool:
    return not any(0xD800 <= ord(c) <= 0xDFFF for c in s)


def _ranges(pattern: re.Pattern[str]) -> list[list[int]]:
    """The code points a one-character pattern matches, as ranges: every code point tried."""
    ranges: list[list[int]] = []
    for cp in range(0x110000):
        if pattern.fullmatch(chr(cp)):
            if ranges and ranges[-1][1] == cp - 1:
                ranges[-1][1] = cp
            else:
                ranges.append([cp, cp])
    return ranges


def _sorted(items) -> list[str]:
    return sorted(items)  # str's order is the code points'


# --- the data ------------------------------------------------------------------------------------------------------


def t2s_txt() -> str:
    table = normalize._t2s_table()
    return "".join(f"{k:x} {table[k]:x}\n" for k in sorted(table))


def _pattern(p: re.Pattern[str]) -> dict:
    extra = p.flags & ~(re.IGNORECASE | re.UNICODE)
    assert not extra, f"{p.pattern!r}: a flag the phone doesn't read ({extra})"
    return {"pattern": p.pattern, "ignorecase": bool(p.flags & re.IGNORECASE)}


@functools.cache
def tables_json() -> str:
    return json.dumps(tables(), ensure_ascii=False, sort_keys=True, indent=1) + "\n"


def tables() -> dict:
    apostrophes = "".join(chr(cp) for cp in range(0x110000) if normalize._APOSTROPHES.fullmatch(chr(cp)))
    out: dict = {
        "KEY_VERSION": normalize.KEY_VERSION,
        "MAX_NAME_BYTES": library.MAX_NAME_BYTES,
        "_TRANSLIT": {chr(k): v for k, v in sorted(normalize._TRANSLIT.items())},
        "_APOSTROPHES": apostrophes,
        "_CJK": _ranges(normalize._CJK),
        "_HAN": _ranges(normalize._HAN),
        "patterns": {name: _pattern(getattr(normalize, name)) for name in PATTERNS},
    }
    out["patterns"]["_RESERVED"] = _pattern(library._RESERVED)
    for name in LISTS:
        out[name] = list(getattr(normalize, name))
    for name in SETS:
        out[name] = _sorted(getattr(normalize, name))
    for name in MAPS:
        out[name] = dict(sorted(getattr(normalize, name).items()))
    return out


def test_t2s_txt_is_normalizes_table_a_pair_a_line():
    check(KEYS_DATA / "t2s.txt", t2s_txt())


def test_tables_json_is_normalizes_constants():
    check(KEYS_DATA / "tables.json", tables_json())


def test_the_data_reads_back_as_normalize_holds_it():
    pairs = dict(tuple(int(h, 16) for h in line.split(" ")) for line in t2s_txt().splitlines())
    assert pairs == normalize._t2s_table()
    data = json.loads(tables_json())
    for name, spec in data["patterns"].items():
        source = library._RESERVED if name == "_RESERVED" else getattr(normalize, name)
        flags = re.IGNORECASE if spec["ignorecase"] else 0
        assert re.compile(spec["pattern"], flags) == source
    for name in ("_CJK", "_HAN"):
        held = {cp for a, b in data[name] for cp in range(a, b + 1)}
        assert all(bool(getattr(normalize, name).match(chr(cp))) == (cp in held) for cp in range(0x30000))
    assert "".join(c for c in data["_APOSTROPHES"] if normalize._APOSTROPHES.match(c)) == data["_APOSTROPHES"]
    assert str.maketrans(data["_TRANSLIT"]) == normalize._TRANSLIT


# --- the inputs ----------------------------------------------------------------------------------------------------


def literals() -> list[str]:
    found: set[str] = set()
    for name in LITERALS_FROM:
        tree = ast.parse((TESTS / name).read_text("utf-8"))
        found |= {n.value for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, str)}
    return sorted(s for s in found if _no_surrogate(s))


EDGES = (
    "", " ", "  \t\n", "-", "--", "_", "'", "’", "and", "And And And", "the", "The", "The The", "the and",
    "y", "Fito y Fitipaldis", "Los", "Los Enanitos Verdes", "La", "El Último de la Fila", "Té Para Tres",
    "Té para 3", "19 Días y 500 Noches", "Doce", "uno dos tres", "zero ten eleven twelve",
    "Song - Remaster ２０１１", "Hysteria - lıve", "Canción - ACÚSTICO", "Song - ſtereo", "Song - Remaſtered",
    "Song - 2011 Remaster", "Song - Remastered 2011", "Song - Digital Remaster", "Song - Remasterizado 2009",
    "Song (Live)", "Song (live at Wembley)", "Song (En Vivo)", "Song - En Vivo", "Song - Ao Vivo", "Song - En Directo",
    "Song - Live; 2013 Remaster", "Song - Acoustic; Live at MTV Unplugged, 1994", "Song - Live/Remastered",
    "Song - Versión Acústica", "Song (Acoustic Version)", "Song (MTV Unplugged)", "Song - Unplugged",
    "Song - Radio Edit", "Song - Single Version", "Song - Album Version", "Song - Edit", "Song - Demo",
    "Song - Demo Version", "Song - Bonus Track", "Song - Mono", "Song - Stereo", "Song - 1999 Stereo Mix",
    "Song - 2009 Mix", "Song - Recorded Live at the Fillmore", "Song - BBC Sessions", "Song - Peel Session",
    "Song - From \"The Film\" Soundtrack", "Song - from “Film”", "Song - From The Motion Picture Soundtrack",
    "Song (feat. Someone)", "Song [ft. Someone]", "Song (featuring X & Y)", "Song (with Z)", "Song (feat Someone)",
    "Live and Let Die", "Live", "Acoustic", "Live - Live", "Song (Live) - Remastered", "Song (Live) (Remastered)",
    "Song - Live\n", "Song - Live\nmore", "Song - Recorded Live at X\nY", "Song - Live", "Song - Live",
    "Song　-　Live", "Song — Live", "Song – Acústico", "Song - LIVE", "Song - lıve at", "SONG (LİVE)",
    "Song - Remaster ١٩٩٩", "Song - Remaster 𝟚𝟘𝟙𝟙",
    "Ma Di (feat. 宋冬野)", "Ma Di feat. 宋冬野", "南山南（feat. 宋冬野）", "南山南【ft. 宋冬野】", "Ma Di ft. X",
    "Ma Di featuring X", "Ma Di Feat. X", "Ma Di (with 宋冬野)", "(feat. X)", "feat. X",
    "Song Dongye (宋冬野)", "宋冬野", "宋冬野 斑马", "斑马，斑马", "斑马斑马", "斑馬斑馬", "周杰倫《斑馬，斑馬》",
    "斑马 斑马 Banma Banma Zebra Zebra", "与我交谈 Speak With Me", "17岁 17 Sui", "Baby 对不起", "我的Baby", "K歌之王",
    "重来 Chong Lai", "重来 Zhong Lai", "绿色 Lv Se", "绿色 Lu Se", "爱 Ai", "IU (아이유)", "봄날 (Spring Day)",
    "봄날 Bomnal Spring Day", "Кино (Kino)", "Ты (Ty)", "ใจ (Jai)", "A (甲) & B (乙)", "Hong Dou (Red Bean)",
    "Nơi Này Có Anh (Where This Is You)", "Another Brick in the Wall (Part 1)", "夜に駆ける Yoru ni Kakeru Racing into the Night",
    "夜に駆ける (Yoru ni Kakeru)", "ありがとう Arigatou", "ありがとう Arigato", "ファイト Faito", "ティー Tii", "ウィー Wii",
    "きゃりー Kyarii", "しゃしん Shashin", "ちゃ Cha", "じゃ Ja", "がっこう Gakkou", "ラーメン Raamen", "時々 Tokidoki",
    "カタカナ Katakana", "ヷヸ Va", "𠮷野家 Yoshinoya", "𠀀 X", "𠮷", "𪚥 Zhe", "ΤΡΥΠΕΣ", "Σίσυφος", "ΣΑΣ Σ",
    "हिंदी", "हिंदी Hindi", "Ærøskøbing Straße", "Łódź", "Þór", "İstanbul", "ŋŋ", "ə Song", "ﬁre", "①②", "½", "x²",
    "ＡＢＣ", "Ｓｏｎｇ", "misc", "Misc", "Unknown Artist", "Various Artists", "V/A", "N/A", "The Unknown", "VA",
    "Desconocido", "Anónimo", "Varios Artistas", "artist", "intro", "x-intro", "x-solo", "-intro", "intro-",
    "song-live-live", "AC/DC", "AC\\DC", "Title: Subtitle", "a : b", "a\t\tb", "a\r\nb", "a\x0bb\x0cc",
    "a*b?c\"d<e>f|g", "\x00\x1f\x7f", "...", " . ", ". a .", "é", "Café del Mar", "宋" * 50,
    "a" * 119 + "宋", "a" * 118 + "é", "é" * 70, "a" * 119 + ". x", "a" * 121, "𠮷" * 40, "a" * 117 + "😀",
)

_LATIN_WORDS = ("the", "and", "y", "los", "las", "el", "la", "rolling", "stones", "uno", "dos", "tres", "one",
                "zero", "doce", "intro", "live", "acoustic", "unplugged", "solo", "remix", "version", "Baby",
                "Banma", "Zebra", "Song", "Dongye", "Chong", "Lai", "Sui", "Yoru", "ni", "Kakeru", "Arigatou", "Ai",
                "Kino", "Ty", "Bomnal", "Spring", "Day", "with", "feat.", "ft.", "featuring", "ost", "part", "2",
                "17", "Part 1", "AC", "DC", "x", "a", "K", "I'll", "Don’t", "rock'n'roll", "MTV", "BBC")
_ACCENTED = ("Café", "Niño", "Ærøskøbing", "Straße", "Łódź", "Þór", "İstanbul", "lıve", "ſtereo", "Kelvin",
             "ΤΡΥΠΕΣ", "Σίσυφος", "ＡＢＣ", "２０１１", "ﬁ", "①", "½", "²", "Ŋ", "ə", "Đặng", "Œuvre", "Ħal",
             "ACÚSTICO", "Acústica", "Versión", "Días", "Último", "Mötley", "Crüe", "Sigur Rós", "Björk", "ĲSSEL")
_CJK_WORDS = ("宋冬野", "斑马", "斑馬", "南山南", "重来", "绿色", "周杰倫", "对不起", "我的", "歌之王", "与我交谈", "岁",
              "夜に駆ける", "ありがとう", "ファ", "ティ", "ウィ", "きゃ", "しゃ", "っ", "ー", "々", "カタカナ", "時々",
              "봄날", "아이유", "사랑", "Кино", "Ты", "ใจ", "हिंदी", "Ελλάδα", "𠮷", "𠀀", "𪚥", "甲", "乙", "爱", "王菲")
_SEPARATORS = (" ", " ", " ", " - ", " / ", " | ", " – ", " — ", "（", "）", "(", ")", "[", "]", "【", "】", "「",
               "」", ", ", " & ", "'", "’", "`", "_", ": ", ".", "\t", " ", " ", "　", "\u0085", "-")
_SUFFIXES = (" - Remastered 2011", " - 2011 Remaster", " (Live)", " (En Vivo)", " - Ao Vivo", " - Live at Wembley",
             " (feat. 宋冬野)", " feat. X", " ft. Y", " (Acoustic Version)", " - Acústico", " - ACÚSTICO", " - lıve",
             " (Remasterizado 2009)", " - Radio Edit", " - Mono", " - From \"Film\" Soundtrack",
             " - Recorded Live at X", " - BBC Sessions", " - Remaster ２０１１", " - Versión Acústica",
             " (MTV Unplugged)", " - Demo Version", " - 1999 Stereo Mix", "（feat. 宋冬野）", " [ft. Z]",
             " - Live; 2013 Remaster", " (with Y)", " - Single Edit", " (Live at the BBC)", " - ſingle Edit")


def _word(rng: random.Random, t2s: list[tuple[int, int]]) -> str:
    kind = rng.random()
    if kind < 0.35:
        return rng.choice(_LATIN_WORDS)
    if kind < 0.55:
        return rng.choice(_ACCENTED)
    if kind < 0.8:
        return rng.choice(_CJK_WORDS)
    if kind < 0.9:
        trad, simp = rng.choice(t2s)
        return "".join(chr(rng.choice((trad, simp))) for _ in range(rng.randint(1, 3)))
    return "".join(chr(rng.randint(0x21, 0x2FF)) for _ in range(rng.randint(1, 4)))


def _two_scripts(rng: random.Random) -> str:
    """A name UG writes in two scripts: an original, its romanization, maybe a translation, in some order."""
    original = rng.choice(("宋冬野", "斑马 斑马", "重来", "绿色", "南山南", "夜に駆ける", "ありがとう", "봄날", "사랑", "王菲",
                           "Кино", "ใจ", "斑馬", "17岁"))
    if normalize.has_han(original) and not any(normalize._kana_letter(c) for c in original):
        roman = normalize.romanize(original)
    else:
        roman = {"夜に駆ける": "Yoru ni Kakeru", "ありがとう": "Arigatou", "봄날": "Bomnal", "사랑": "Sarang",
                 "Кино": "Kino", "ใจ": "Jai"}.get(original, "Xyz")
    roman = rng.choice((roman, roman.title(), roman.replace(" ", ""), roman.upper()))
    translation = rng.choice(("", "Zebra Zebra", "Spring Day", "Love", "Racing into the Night", "Live"))
    shape = rng.randrange(5)
    if shape == 0:
        return f"{original} {roman} {translation}".strip()
    if shape == 1:
        return f"{roman} ({original})"
    if shape == 2:
        return f"{original} ({roman})"
    if shape == 3:
        return f"{original} / {roman} {translation}".strip()
    return f"【{original}】{translation or roman}"


def names() -> list[str]:
    rng = random.Random(SEED)
    t2s = sorted(normalize._t2s_table().items())
    out = []
    for _ in range(NAMES):
        if rng.random() < 0.3:
            name = _two_scripts(rng)
        else:
            parts = [_word(rng, t2s)]
            for _ in range(rng.randint(0, 4)):
                parts += [rng.choice(_SEPARATORS), _word(rng, t2s)]
            name = "".join(parts)
        if rng.random() < 0.35:
            name += rng.choice(_SUFFIXES)
        if rng.random() < 0.05:
            name = rng.choice(("  ", "\t", "\n", " - ")) + name + rng.choice(("  ", "\n", ""))
        out.append(name)
    return out


@functools.cache
def inputs() -> list[str]:
    seen = dict.fromkeys(literals())
    seen.update(dict.fromkeys(EDGES))
    seen.update(dict.fromkeys(names()))
    return [s for s in seen if _no_surrogate(s)]


def pairs(items: list[str]) -> list[tuple[str, str]]:
    other = list(items)
    random.Random(SEED + 1).shuffle(other)
    return list(zip(items, other))


def answer(f, *args):
    """What ``f`` answers, or ``{"err": "<exception class>"}`` where it raises (no function here answers an object)."""
    try:
        return f(*args)
    except Exception as e:  # recorded: the phone raises where Python does
        return {"err": type(e).__name__}


def call(fn: str, f, *args) -> dict:
    try:
        return {"fn": fn, "args": list(args), "out": f(*args)}
    except Exception as e:  # recorded: the phone raises where Python does
        return {"fn": fn, "args": list(args), "err": type(e).__name__}


def answers(fns: dict, *args) -> dict:
    """Each function's answer for the same arguments, by its name: one record holds an input once."""
    return {name: answer(f, *args) for name, f in fns.items()}


def _vector(name: str, records: list[dict]) -> None:
    check(KEYS_VECTORS / f"{name}.jsonl", jsonl(records, corpus=f"keys/{name}", made_by=MADE_BY))


# --- the vectors ---------------------------------------------------------------------------------------------------
#
# A record of one of the helpers below holds one input and every answer for it (``answers``), so the input is
# written once: ``fold_each``, ``slugs_of``, ``identity_of``, ``forms_of`` and ``safe_of``, named
# ``test_conformance_keys.<helper>`` in their records. The others are calls of caracole's own functions.


def fold_each(text: str) -> list[str]:
    """``fold`` of each character alone."""
    return [normalize.fold(c) for c in text]


def slugs_of(s: str) -> dict:
    """``slug_key`` and ``ug_slug_key`` of ``s``, and ``compact`` and ``split_variant`` of its key."""
    key = normalize.slug_key(s)
    return {"slug_key": key, "ug_slug_key": answer(normalize.ug_slug_key, s),
            "compact": answer(normalize.compact, key), "split_variant": answer(normalize.split_variant, key)}


IDENTITY_OF = {
    "clean_title": normalize.clean_title, "title_variant": normalize.title_variant,
    "without_featuring": normalize.without_featuring, "placeholder_artist": normalize.placeholder_artist,
    "has_han": normalize.has_han, "has_other_script": normalize.has_other_script, "simplified": normalize.simplified,
    "romanize": normalize.romanize, "name_words": normalize.name_words, "name_key": lacuerda_index.name_key,
    "title_key": lacuerda_index.title_key,
}


def identity_of(s: str, other: str, runs: list[str]) -> dict:
    """``s``'s answers of ``IDENTITY_OF`` (lacuerda_index's ``name_key`` and ``title_key`` among them),
    ``identity_key`` and ``display_key`` of ``s`` as the artist and ``other`` as the title, and ``holds_run`` of
    ``s``'s ``name_words`` and each of ``runs``, ``[run, answer]`` pairs in order."""
    out = answers(IDENTITY_OF, s)
    out["identity_key"] = answer(normalize.identity_key, s, other)
    out["display_key"] = answer(normalize.display_key, s, other)
    words = normalize.name_words(s)
    out["holds_run"] = [[run, answer(normalize.holds_run, words, run)] for run in runs]
    return out


FORMS_OF = {"name_forms": normalize.name_forms, "listing_forms": normalize.listing_forms,
            "original_part": normalize.original_part}


def safe_of(s: str, other: str) -> dict:
    """library's ``safe_name`` of ``s``, and ``song_folder`` of ``s`` as the artist and ``other`` as the title."""
    return {"safe_name": answer(library.safe_name, s), "song_folder": answer(library.song_folder, s, other)}


def fold_strings() -> list[str]:
    rng = random.Random(SEED + 2)
    blocks = ((0x20, 0x7E), (0xA0, 0x24F), (0x300, 0x36F), (0x370, 0x3FF), (0x400, 0x4FF), (0x900, 0x97F),
              (0x1100, 0x11FF), (0x1E00, 0x1EFF), (0x2000, 0x206F), (0x2150, 0x218F), (0x2460, 0x24FF),
              (0x3040, 0x30FF), (0x3130, 0x318F), (0x3200, 0x33FF), (0x4E00, 0x9FFF), (0xAC00, 0xD7A3),
              (0xF900, 0xFAFF), (0xFB00, 0xFB4F), (0xFE30, 0xFE4F), (0xFF00, 0xFFEF), (0x10400, 0x1044F),
              (0x1D400, 0x1D7FF), (0x1F100, 0x1F1FF), (0x1F600, 0x1F64F), (0x20000, 0x2A6DF), (0xE0000, 0xE007F))
    sigma = ("Σ", "ς", "σ", "ΑΣ", "ΑΣ Β", "Σ.", "ΤΡΥΠΕΣ", "'Σ'", "ΑΣ́")
    out = []
    for _ in range(FOLD_STRINGS):
        parts = []
        for _ in range(rng.randint(1, 8)):
            if rng.random() < 0.1:
                parts.append(rng.choice(sigma))
            else:
                a, b = rng.choice(blocks)
                parts.append(chr(rng.randint(a, b)))
        out.append("".join(parts))
    return out


def test_fold_vectors():
    changed = "".join(chr(cp) for cp in range(0x110000)
                      if not 0xD800 <= cp <= 0xDFFF and normalize.fold(chr(cp)) != chr(cp))
    records = [call("test_conformance_keys.fold_each", fold_each, changed[i:i + CHARS_A_RECORD])
               for i in range(0, len(changed), CHARS_A_RECORD)]
    records += [call(N + "fold", normalize.fold, s) for s in fold_strings()]
    _vector("fold", records)


def test_slug_vectors():
    items = inputs()
    records = [call("test_conformance_keys.slugs_of", slugs_of, s) for s in items]
    rng = random.Random(SEED + 3)
    slugs = dict.fromkeys(("", "-", "the-the", "-the-rifles-", "and-and", "adam-and-the-ants"))
    keys = dict.fromkeys(("intro", "-intro", "x-", "x--solo", "a-b-live", "live-", "a-unplugged", "a-remix"))
    for s in items:
        key = normalize.slug_key(s)
        if key and rng.random() < 0.2:
            slugs["-" + key.upper().replace("-", rng.choice(("-", "--", "_"))) + rng.choice(("", "-", "-the"))] = None
            keys[key + "-" + rng.choice(normalize.VARIANT_TOKENS + ("remix", "unplugged"))] = None
    records += [call(N + "ug_slug_key", normalize.ug_slug_key, s) for s in slugs]
    records += [call(N + "split_variant", normalize.split_variant, k) for k in keys]
    _vector("slug", records)


def _runs(words: list[str], rng: random.Random) -> list[str]:
    """A run the words hold, and one they almost hold."""
    if not words:
        return [""]
    i = rng.randrange(len(words))
    j = rng.randint(i + 1, len(words))
    run = "".join(words[i:j])
    return [run, rng.choice((run + "a", run[:-1], "x" + run))]


def test_identity_vectors():
    items = inputs()
    rng = random.Random(SEED + 4)
    records = [{"fn": N + "KEY_VERSION", "args": [], "out": normalize.KEY_VERSION}]
    for s, other in pairs(items):
        runs = _runs(normalize.name_words(s), rng)
        if normalize.has_han(s):  # a Chinese name's pinyin, as search holds it against another name's words
            runs.append(normalize.compact(normalize.slug_key(normalize.romanize(s))))
        records.append(call("test_conformance_keys.identity_of", identity_of, s, other, runs))
    labels = normalize.VARIANT_TOKENS + ("unplugged", "Unplugged", "UNPLUGGED", "remix", "", " unplugged")
    records += [call(N + "canonical_variant", normalize.canonical_variant, v) for v in labels]
    pinyin_words = [(normalize.name_words(normalize.romanize(s)), normalize.compact(normalize.slug_key(normalize.romanize(s))))
                    for s in items if normalize.has_han(s)]
    records += [call(N + "holds_run", normalize.holds_run, words, run) for words, run in pinyin_words]
    _vector("identity", records)


def test_name_forms_vectors():
    records = [call("test_conformance_keys.forms_of", lambda s: answers(FORMS_OF, s), s) for s in inputs()]
    _vector("name_forms", records)


def test_safe_name_vectors():
    items = inputs()
    nfd = [unicodedata.normalize("NFD", s) for s in items if unicodedata.normalize("NFD", s) != s]
    records = [call("test_conformance_keys.safe_of", safe_of, a, t) for a, t in pairs(items)]
    records += [call("caracole.library.safe_name", library.safe_name, s) for s in nfd]
    _vector("safe_name", records)
