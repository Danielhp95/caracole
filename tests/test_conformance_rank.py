"""Ranking, lyric coverage and a song's sheet versions, for the phone: what rank.py, coverage.py (with versions.py's
``complete`` and ``replaces_sheet``) and sheet_versions.py answer, written for the Kotlin lane rank-coverage
(core.ug's ``Rank``, ``Coverage`` and ``SheetVersions``) to agree with, every float as Python's repr.

**vectors/sites/ug_rank.jsonl**, a record a call:

- first ``caracole.config.RankPolicy``, ``out`` its defaults: a policy in a record is the fields that differ from
  them, ``RankPolicy(**policy)`` (``prior_votes`` and ``line_match`` an int or a float, as caracole.toml may give
  them);
- ``caracole.rank.bayes`` (``args`` rating, votes, prior, m), ``prior_mean`` (``kw.cands``), ``is_complete``
  (``kw.cand``, ``kw.policy``), ``caracole.versions.complete`` and ``replaces_sheet`` (``args``; each threshold's
  edges, every pair of them);
- ``rank_by_rating`` and ``rank_sheets`` (``kw`` ``cands``, ``policy``, ``variant``), ``out`` the candidates in their
  order, each ``[its index in cands, its score]``; ``rank_guitar``, which is ``rank_by_rating``, on the text tabs'
  lists alone.

A candidate is an object of the ``rank.Candidate`` fields ranking reads (``tab_id``, ``rating``, ``votes``,
``version``, ``label``, ``coverage``): its ``provider`` is ``ug`` and its ``kind`` ``chords``, which it reads neither
of. ``case`` says where the inputs come from: ``hand`` (tests/test_rank.py's and the rules' edges) or ``random``
(seeded: ratings, votes of none to many, versions and tab ids that tie on ``(version, len(tab_id), tab_id)``, partial
labels, variants, coverage at and around the threshold).

**vectors/sites/ug_coverage.jsonl**: ``caracole.coverage.normalize_line``, ``lyric_lines``, ``sheet_lyric_text``,
``_is_plain_chord_line``, ``_comparable`` and ``_match`` (``args``), and ``coverage`` (``kw`` ``sheet``, ``lyrics``
and ``line_match``: the sheet's coverage of ``lyric_lines(lyrics)``; where it tells more than the share, a share
strictly between none and all or a sheet against its own words, ``scores``, each line's ``_match`` against the
sheet's lyric text, both made ``_comparable``). A text in ``args`` or ``kw`` is a string, or ``{"name": …}``, one of
**vectors/sites/ug_coverage_texts.jsonl**'s (``{name, fixture}``, a file of tests/fixtures/ read as UTF-8, or
``{name, text}``, a text read out of one, as caracole reads it: a UG tab page's ``content``, a LaCuerda version's
markup, an LRCLIB answer's plain lyrics…). Every fixture sheet is scored against every fixture lyrics, and a few
harmonica tabs (``HARMONICA_TABS``: words over holes, never a sheet coverage.py scores) against two; ``hand`` cases
take every regex's edges (case folded as Python folds it, Unicode's spaces, digits and line ends, Chinese as pinyin).

**vectors/sites/ug_sheet_versions.jsonl**, over the fixture **ug_sheet_versions_fixture_library.jsonl** (a library
built with caracole's writers: songs of wanted.txt lines, ``upsert_version``, ``keep_file``, ``mark_gone``,
``mark_stale``, ``kv_set_json``, rows of ``ug_index``; dumped with ``dump_fixture``, its files left out, as
sheet_versions.py reads the tables alone): ``{fn, case, fixture, kw, out, after}``, ``kw`` by Python's names
(``song_id`` a song of the fixture, ``policy`` as above), a ``SheetVersion`` an object of its fields,
``in_library_of``'s answer a ``[song id, versions]`` a song in its order, ``after.kv`` the kv records a writer left
(``note_kept_by_you``, ``note_unkeepable``). ``may_keep`` and ``as_data`` are given ``in_library``'s list.
``as_data`` and ``same_pages`` add ``dumps``, ``json.dumps(out, ensure_ascii=False)``: the answer with its members in
Python's order, which the pages embed and a record's sorted keys lose. Records without a fixture: ``version_names``,
``tab_of``, ``group_of`` (``kw.rows``: each version's ``kind``, ``tab_id`` and ``gone``).

The vectors stay small (the ``sites`` area's budget is every site lane's): a record only where it can answer
otherwise than another. The answers are the same on every run (``test_the_vectors_are_the_same_on_another_run``).
Regenerate with ``CARACOLE_CORPUS=write`` (tests/conformance/README.md).
"""

from __future__ import annotations

import json
import math
import random
import re
from dataclasses import fields
from pathlib import Path
from typing import Any

import pytest

from helpers.corpus import FIXTURES, VECTORS, check, dump_fixture, jsonl, plain, replay_fixture

MADE_BY = "tests/test_conformance_rank.py"
SITES = VECTORS / "sites"
RANK = SITES / "ug_rank.jsonl"
COVERAGE = SITES / "ug_coverage.jsonl"
TEXTS = SITES / "ug_coverage_texts.jsonl"
SHEET_VERSIONS = SITES / "ug_sheet_versions.jsonl"
FIXTURE = SITES / "ug_sheet_versions_fixture_library.jsonl"
SEED = 20261104
NOW = "2026-10-31T00:00:00Z"


def _records(text: str) -> list[dict[str, Any]]:
    """A vector's records, its header left out: a line a record, split at ``\n`` alone, as Kotlin's ``Corpus``
    reads them (a text holds U+2028 and U+0085 as they are, which ``str.splitlines`` would split at)."""
    return [r for r in (json.loads(line) for line in text.split("\n") if line) if not r.get("header")]


# --- rank.py ----------------------------------------------------------------------------------------------------


def _policy(**changes: Any) -> dict[str, Any]:
    """A policy as the records give it: the ``RankPolicy`` fields that differ from its defaults, ``RankPolicy(**it)``
    (``ug_rank.jsonl``'s first record gives the defaults)."""
    from caracole.config import RankPolicy

    RankPolicy(**changes)  # a field it has, each
    return dict(changes)


POLICIES = (
    _policy(),
    _policy(prior_votes=0),
    _policy(prior_votes=2.5, coverage_threshold=0.95, label_penalty=1.25, variant_bonus=0.0),
    _policy(coverage_threshold=0.5, label_penalty=0, variant_bonus=3, line_match=82.5),
)
LABELS = (None, None, None, "intro", "solo", "outro", "riff", "lesson", "acoustic", "unplugged", "live", "Acoustic",
          "Intro", "", "electric")
VARIANTS = (None, None, "acoustic", "unplugged", "live", "", "intro", "Acoustic")


def cand(tab_id: str, rating: float, votes: int, *, version: int = 1, coverage: float | None = None,
         label: str | None = None) -> dict[str, Any]:
    """A candidate as the records give it: the fields ranking reads, its provider and kind (which it reads neither
    of) left out."""
    return {"tab_id": tab_id, "rating": float(rating), "votes": votes, "version": version, "label": label,
            "coverage": coverage}


def _candidate(d: dict[str, Any]):
    from caracole.rank import Candidate

    return Candidate(provider="ug", kind="chords", **d)


def _rank_policy(p: dict[str, Any]):
    from caracole.config import RankPolicy

    return RankPolicy(**p)


def _ranked(fn: str, cands: list[dict[str, Any]], policy: dict[str, Any], variant: str | None) -> list[list[Any]]:
    from caracole import rank

    made = [_candidate(c) for c in cands]
    order = getattr(rank, fn)(made, _rank_policy(policy), variant=variant)
    return [[next(i for i, m in enumerate(made) if m is c), c.score] for c in order]


def _random_rating(rng: random.Random) -> float:
    pick = rng.random()
    if pick < 0.15:
        return rng.choice((0.0, 5.0, 4.85, 4.86, 4.5, 1.0))
    if pick < 0.6:
        return round(rng.uniform(0, 5), 2)
    return rng.uniform(0, 5)


def _random_votes(rng: random.Random) -> int:
    pick = rng.random()
    if pick < 0.2:
        return 0
    if pick < 0.5:
        return rng.randint(1, 12)
    if pick < 0.9:
        return rng.randint(13, 2000)
    return rng.randint(2000, 40000)


def _random_coverage(rng: random.Random, threshold: float) -> float | None:
    pick = rng.random()
    if pick < 0.35:
        return None
    if pick < 0.5:
        return rng.choice((0.0, 1.0, threshold, 0.8, 0.79, 0.95, 0.5))
    return rng.random()


def _random_tab(rng: random.Random, taken: set[str]) -> str:
    while True:
        tab = str(rng.choice((rng.randint(1, 9), rng.randint(10, 99), rng.randint(100, 999), rng.randint(1, 10 ** 7))))
        if rng.random() < 0.1:
            tab = "0" + tab  # a leading zero: a longer tab of the same number
        if tab not in taken:
            taken.add(tab)
            return tab


def _random_cands(rng: random.Random, policy: dict[str, Any]) -> list[dict[str, Any]]:
    n = rng.choice((0, 1, 2, 3, 3, 4, 5, 6, 8))
    threshold = _rank_policy(policy).coverage_threshold
    taken: set[str] = set()
    out = []
    tie = rng.random() < 0.3  # ratings and votes repeated: the tiebreak decides
    rating, votes = _random_rating(rng), _random_votes(rng)
    for _ in range(n):
        if not tie:
            rating, votes = _random_rating(rng), _random_votes(rng)
        out.append(cand(_random_tab(rng, taken), rating, votes, version=rng.choice((1, 1, 2, 3, 4)),
                        coverage=_random_coverage(rng, threshold), label=rng.choice(LABELS)))
    return out


def rank_records() -> list[dict[str, Any]]:
    from caracole import rank, versions

    from caracole.config import RankPolicy

    k = "caracole.rank."
    out: list[dict[str, Any]] = [{"fn": "caracole.config.RankPolicy", "case": "the defaults", "args": [], "kw": {},
                                  "out": plain(RankPolicy())}]
    p = POLICIES[0]
    # bayes: tests/test_rank.py's, and none to weigh
    for args in ((4.85, 81, 4.8, 10), (5.0, 0, 4.2, 10), (0.0, 0, 0.0, 0), (3.5, 0, 4.0, 0), (4.2, 7, 0.0, 0),
                 (4.9, 1, 4.633333333333333, 10), (1.0, 3, 2.0, 2.5), (0.1, 10, 0.2, 10), (5.0, 40000, 4.99, 10),
                 (2.0, 0, 3.0, 0.0)):
        out.append({"fn": k + "bayes", "case": "hand", "args": list(args), "out": rank.bayes(*args)})
    rng = random.Random(SEED)
    for _ in range(50):
        args = (_random_rating(rng), _random_votes(rng), _random_rating(rng),
                rng.choice((10, 10, 0, 1, 2.5, 7, 0.0)))
        out.append({"fn": k + "bayes", "case": "random", "args": list(args), "out": rank.bayes(*args)})
    # prior_mean
    for cands in ([cand("1", 4.0, 10), cand("2", 5.0, 30), cand("3", 1.0, 0)], [cand("1", 4.0, 0)], [],
                  [cand("1", 0.1, 1), cand("2", 0.2, 1), cand("3", 0.3, 1)],
                  [cand("1", 1e16, 1), cand("2", 1.0, 1), cand("3", -1e16, 1)]):
        out.append({"fn": k + "prior_mean", "case": "hand", "kw": {"cands": cands},
                    "out": rank.prior_mean([_candidate(c) for c in cands])})
    for _ in range(10):
        cands = _random_cands(rng, p)
        out.append({"fn": k + "prior_mean", "case": "random", "kw": {"cands": cands},
                    "out": rank.prior_mean([_candidate(c) for c in cands])})
    # is_complete, complete, replaces_sheet
    for coverage in (None, 0.0, 0.5, 0.79, 0.7999999999999999, 0.8, 0.95, 1.0):
        for policy in POLICIES[:1] + POLICIES[2:]:  # each threshold
            c = cand("1", 4.0, 1, coverage=coverage)
            out.append({"fn": k + "is_complete", "case": "hand", "kw": {"cand": c, "policy": policy},
                        "out": rank.is_complete(_candidate(c), _rank_policy(policy))})
    shares = (None, 0.0, 0.3, 0.5, 0.79, 0.8, 0.9, 1.0)
    for threshold in (0.8, 0.5, 0.95):
        for new in shares:
            out.append({"fn": "caracole.versions.complete", "case": "hand", "args": [new, threshold],
                        "out": versions.complete(new, threshold)})
    # replaces_sheet at its edges: unknown, under, just under, at and over each threshold, every pair of them
    for threshold, edges in ((0.8, (None, 0.0, 0.5, 0.79, 0.8, 1.0)), (0.5, (None, 0.3, 0.5, 0.9, 0.95)),
                             (0.95, (None, 0.3, 0.5, 0.9, 0.95))):
        for new in edges:
            for kept in edges:
                out.append({"fn": "caracole.versions.replaces_sheet", "case": "hand", "args": [new, kept, threshold],
                            "out": versions.replaces_sheet(new, kept, threshold)})
    # the rankings: tests/test_rank.py's lists, then seeded ones under every policy and variant
    hand = [
        [cand("1", 5.0, 1), cand("2", 4.8, 270), cand("3", 4.4, 200)],
        [cand("1", 4.9, 300, coverage=0.5), cand("2", 4.2, 20, coverage=0.95)],
        [cand("1", 4.2, 20, coverage=0.9), cand("2", 4.8, 200, coverage=0.85)],
        [cand("1", 4.0, 5, coverage=0.3), cand("2", 4.5, 50, coverage=0.6)],
        [cand("1", 4.9, 500, coverage=None), cand("2", 3.0, 2, coverage=0.81)],
        [cand("1", 4.9, 100, label="solo"), cand("2", 4.6, 100), cand("3", 4.5, 100, label="acoustic")],
        [cand("4", 4.5, 100, label="unplugged"), cand("5", 4.6, 100)],
        [cand("9", 0, 0, version=2), cand("10", 0, 0, version=1), cand("8", 0, 0, version=1)],
        [cand("100", 4.0, 10), cand("99", 4.0, 10), cand("1000", 4.0, 10), cand("0100", 4.0, 10), cand("2", 4.0, 10)],
        [cand("1", 4.0, 10, label="intro"), cand("2", 3.5, 10)],  # a penalty that ties the score
        [],
    ]
    for i, cands in enumerate(hand):
        # rank_guitar is rank_by_rating in Python: the text tabs' lists alone, to name it
        for fn in ("rank_by_rating", "rank_sheets") + (("rank_guitar",) if i in (5, 6, 7) else ()):
            for variant in (None, "acoustic"):
                out.append({"fn": k + fn, "case": "hand", "kw": {"cands": cands, "policy": p, "variant": variant},
                            "out": _ranked(fn, cands, p, variant)})
    for _ in range(45):
        policy = rng.choice(POLICIES)
        cands = _random_cands(rng, policy)
        variant = rng.choice(VARIANTS)
        fn = rng.choice(("rank_by_rating", "rank_sheets", "rank_sheets"))
        out.append({"fn": k + fn, "case": "random", "kw": {"cands": cands, "policy": policy, "variant": variant},
                    "out": _ranked(fn, cands, policy, variant)})
    return out


# --- coverage.py ------------------------------------------------------------------------------------------------

# tests/test_coverage.py's texts.
LYRICS = """Walking down the empty road tonight
Counting every light along the way

Walking down the empty road tonight
I keep on singing till the break of day
Nothing else will ever feel the same
"""
FULL_SHEET = """[Verse 1]
[tab][ch]G[/ch]          [ch]D[/ch]
Walking down the empty road tonight[/tab]
[tab][ch]Em[/ch]            [ch]C[/ch]
Counting every light along the way[/tab]

[Chorus]
[ch]G[/ch]   [ch]D[/ch]
I keep on singing till the break of day
[ch]Em[/ch]        [ch]C[/ch]
Nothing else will ever feel the same
"""
FIRST_VERSE_ONLY = """[Verse 1]
[ch]G[/ch]          [ch]D[/ch]
Walking down the empty road tonight
[ch]Em[/ch]            [ch]C[/ch]
Counting every light along the way
(repeat chords for the rest)
"""
CHORDS_ONLY = """[Intro]
[ch]G[/ch] [ch]D[/ch] [ch]Em[/ch] [ch]C[/ch]
[tab]e|-----3-----|
B|---0---0---|[/tab]
G D Em C   x4
"""
# Lines at every regex's edges: Python's case folding (ſ is s, ı is i, K's Kelvin sign), Unicode's spaces, digits
# and line ends (\u2028, \x1c, \x85, \r\n), filler, staff lines, sections, chords in Latin and solfège.
EDGES_SHEET = (
    "[CH]Am[/CH] hello [Ch]G[/cH] there\r\n"
    "[TAB][ch]Do#m7[/ch]   [ch]SOL[/ch][/TaB]\u2028"
    "[ch]Am[/ch] x2 | -- (x3) 2x **\x1c"
    "  [Verse 2]  \x85"
    "[Coro]\u3000\n"
    "[ch]A[/ch]\xa0\u2003/ \\ - – × 0 9 ( ) . : *\n"
    "e|---3---0---|\n"
    "  C# |--0--2--|\n"
    "Bb|-\n"
    "|--|--\n"
    "ſol mı Rem7 FAmaj7 Lab ſi\n"
    "Am٧ Dsus٤ G/B C/E\n"
    "(Am) (G7) D/F# Esus4 Cadd9 Bm7b5 F#m7-5 Edim Gaug G+ Bø C°\n"
    "Am Bm Cm7 | / x4 (2x)\n"
    "Am I am the one\n"
    "Re mi fa sol la si do\n"
    "do re mi\n"
    "[ch]C[/ch] Ünïcödé wörds, ñandú; ÆØÅ æøå ß ﬁ\n"
    "斑马，斑马，你不要睡着啦\n"
    "再給我看看你受傷的尾巴\n"
    "Ⅳ ① ¹ ½ ٣ word_with_underscore don't\n"
    "\t \x0b \x0c\n"
    "\x1f unit separator stays in its line\x1fand more\n"
    "[unclosed section\n"
    "[]\n"
    "[ch][/ch]\n"
    "[ch]G[/ch][ch]D[/ch]\n"
    "word [ch]G\n"
    "keep the ångström\n"
)
EDGES_LYRICS = (
    "Hello there\r\nHELLO THERE!\r\nHi\u2028Hi there you\x1cÜnïcödé wörds ñandú\x85斑馬斑馬你不要睡著啦\n"
    "ſol mı\n\u212aEEP THE \u212bNGSTRÖM\nWord with underscore don't\n\n   \n¿Dónde estás, corazón?\n"
)
NORMALIZE = (
    "¿Dónde estás, corazón?", "斑马，斑马，你不要睡着啦", "", "   ", "a_b", "__x__", "Ⅳ ① ¹ ½ ٣", "don't stop",
    "ÆØÅ æøå ß ﬁ ŁĐ", "İstanbul ıi", "Straße", "ǅ ǈ ǋ", "\xa0nbsp\u2003em\u3000ideo\u200bzw",
    "e\u0301 combining", "Ⓐ ⓑ", "x\ty\nz", "😀 emoji 😀", "123abc", "Ω ω Σ σ ς", "한국어 가사", "日本語のうた",
    "Привет, мир", "a-b–c—d", "word.word", "\x1c\x1d\x1e\x1f", "ſ \u212a \u212b K Å",
)
CHORD_LINES = (
    "G  D/F#  Em  C", "Am7 Cadd9 Dsus4", "Am I am", "Do Re Mi Fa Sol La Si", "do#m sib", "SOL RE", "ſol", "mı",
    "Mİ", "Am٧", "(Am)", "(Am", "Am)", "G | / x4", "x2", "| |", "", "   ", "C°", "Bø", "G+", "F#m7-5", "Emaj7",
    "Amin", "Gsus2sus4", "Cadd9add11", "C/E", "C/", "H", "Hm", "B#", "Cb", "Am x", "Am xx", "Am (x3)", "Am (3)",
    "Am 3x", "Am ***", "Am ---", "Am -", "Am — ", "A\xa0D", "A\u2003D", "Am\u3000G", "Sol7 Mim", "LA SI",
    "Am7b5", "A7#9", "Dm/F", "Bb/Ab", "Eb", "e", "E|---", "x", "(x2)",
)
COMPARABLE = (
    "斑马斑马", "斑馬斑馬 你不要睡著啦", "plain latin", "", "宋冬野 - 斑马，斑马", "mixed 斑马 and words", "한국어",
    "日本語", "〇", "斑马123", "ban ma",
)
MATCHES = (
    ("walking down the empty road tonight", "walking down the empty road"),
    ("walking down the empty road tonight", "i"),
    ("i", "walking down the empty road tonight"),
    ("", ""), ("a", ""), ("", "a"),
    ("hello there", "hello there"),
    ("ban ma ban ma ni bu yao shui zhao la", "ban ma ban ma ni bu yao shui zhe la"),
    ("abcd", "xxabcdxx"), ("abcd", "abce"),
)


# harptabs.com's tabs, one of each fixture folder's and those whose words have lyrics made of them: holes, bends and
# words over them, never a sheet coverage.py scores, so scored against two lyrics and their own words alone.
HARMONICA_TABS = ("harptabs/layout/12631_en-brazos-de-la-fiebre-with-lyric.txt",
                  "harptabs/legends/693_spokey-dokey.txt", "harptabs/spellings/17941_if-i-die-young.txt",
                  "harptabs/tabs/25_piano-man.txt", "harptabs/tabs/3489_wonderwall.txt")


def _txt(path: str) -> str:
    return (FIXTURES / path).read_bytes().decode("utf-8")  # as it is: no newline translated


def _plain_of(sheet: str) -> str:
    """A sheet's own words as lyrics: its lines with the chords and tags taken out, sections and chord lines left
    out (a lyrics site's text of the song the sheet charts)."""
    out = []
    for raw in sheet.splitlines():
        line = re.sub(r"\[/?tab\]", "", raw, flags=re.I)
        line = re.sub(r"\[ch\].*?\[/ch\]", "", line, flags=re.I)
        if re.fullmatch(r"\s*\[[^\]]*\]\s*", line) or not re.search(r"[^\W\d_]{2}", line):
            continue
        out.append(line.strip())
    return "\n".join(out)


def _accents(text: str) -> str:
    """The words spelled another way: accents added, case changed, punctuation in."""
    table = str.maketrans({"a": "á", "e": "è", "o": "ö", "u": "ú", "n": "ñ", " ": ", "})
    return "\n".join(line.translate(table).upper() if i % 2 else line.translate(table)
                     for i, line in enumerate(text.splitlines()))


def coverage_texts() -> tuple[dict[str, dict[str, str]], dict[str, str], list[str], list[str], dict[str, str]]:
    """The texts the records name: ``{name: record}`` (a fixture or a text), ``{name: its text}``, the sheets'
    names, the fixture lyrics' names, and the lyrics made of a sheet's own words, each with its sheet's name."""
    from caracole.azlyrics import parse_lyrics
    from caracole.gametabs import parse_tab_page as game_tab
    from caracole.http import Response
    from caracole.lacuerda import parse_version_page
    from caracole.ug.page import parse_tab_page

    records: dict[str, dict[str, str]] = {}
    texts: dict[str, str] = {}
    sheets: list[str] = []
    lyrics: list[str] = []
    derived: list[str] = []
    of_sheet: dict[str, str] = {}

    def named(name: str, *, fixture: str | None = None, text: str | None = None, into: list[str]) -> None:
        assert name not in records, name
        if fixture is not None:
            records[name] = {"name": name, "fixture": fixture}
            texts[name] = _txt(fixture)
        else:
            assert text is not None
            records[name] = {"name": name, "text": text}
            texts[name] = text
        into.append(name)

    for path in ("chordpro/ug_sheet.txt", "chordpro/zh_sheet.txt", "chordpro/ug_sheet.cho",
                 "chordpro/legend_sheet.cho"):
        named(path, fixture=path, into=sheets)
    for path in HARMONICA_TABS:
        named(path, fixture=path, into=sheets)
    for path in ("ug/tab_chords.html", "ug/tab_ukulele.html"):
        named(path + " content", text=parse_tab_page((FIXTURES / path).read_bytes()).content, into=sheets)
    named("lacuerda/version.html markup", text=parse_version_page(_txt("lacuerda/version.html")), into=sheets)
    for path in sorted(p.relative_to(FIXTURES).as_posix() for p in (FIXTURES / "gametabs").glob("tab_*.html")):
        named(path + " body", text=game_tab((FIXTURES / path).read_bytes()).body, into=sheets)
    for name, text in (("full sheet", FULL_SHEET), ("first verse only", FIRST_VERSE_ONLY),
                       ("chords only", CHORDS_ONLY), ("edges", EDGES_SHEET)):
        named(name, text=text, into=sheets)

    hit = json.loads(_txt("lrclib/get_hit.json"))
    named("lrclib/get_hit.json plainLyrics", text=hit["plainLyrics"], into=lyrics)
    banma = json.loads(_txt("lrclib/search_banma.json"))
    for i, text in enumerate(dict.fromkeys(x["plainLyrics"] for x in banma if x.get("plainLyrics"))):
        named(f"lrclib/search_banma.json plainLyrics {i}", text=text, into=lyrics)
    lrc = json.loads(_txt("megalobiz/lrc_24519.json"))["lrc"]
    named("megalobiz/lrc_24519.json lrc's words", text=re.sub(r"\[[^\]]*\]", "", lrc), into=lyrics)
    page = Response(url="https://www.azlyrics.com/lyrics/x/y.html", status=200,
                    content=(FIXTURES / "azlyrics/lyrics_mononoke.html").read_bytes())
    named("azlyrics/lyrics_mononoke.html lyrics", text=parse_lyrics(page), into=lyrics)
    named("lyrics", text=LYRICS, into=lyrics)
    named("edge lyrics", text=EDGES_LYRICS, into=lyrics)
    for name in ("chordpro/ug_sheet.txt", "chordpro/zh_sheet.txt", "harptabs/tabs/25_piano-man.txt",
                 "harptabs/layout/12631_en-brazos-de-la-fiebre-with-lyric.txt", "ug/tab_chords.html content",
                 "lacuerda/version.html markup"):
        words = _plain_of(texts[name])
        half = "\n".join(words.splitlines()[: max(1, len(words.splitlines()) // 2)])
        more = words + "\nA verse the sheet leaves out entirely\nand the last line nobody charted"
        for made, text in ((f"{name} words", words), (f"{name} words, half", half),
                           (f"{name} words, spelled otherwise", _accents(words)), (f"{name} words, and more", more)):
            named(made, text=text, into=derived)
            of_sheet[made] = name
    return records, texts, sheets, lyrics, of_sheet


def coverage_records(texts: dict[str, str], sheets: list[str], lyrics: list[str],
                     of_sheet: dict[str, str]) -> list[dict[str, Any]]:
    from caracole import coverage

    k = "caracole.coverage."
    out: list[dict[str, Any]] = []

    def ref(name: str) -> dict[str, str]:
        return {"name": name}

    for s in NORMALIZE:
        out.append({"fn": k + "normalize_line", "case": "hand", "args": [s], "out": coverage.normalize_line(s)})
    for s in CHORD_LINES:
        out.append({"fn": k + "_is_plain_chord_line", "case": "hand", "args": [s],
                    "out": coverage._is_plain_chord_line(s)})
    for s in COMPARABLE:
        out.append({"fn": k + "_comparable", "case": "hand", "args": [s], "out": coverage._comparable(s)})
    for line, text in MATCHES:
        out.append({"fn": k + "_match", "case": "hand", "args": [line, text], "out": coverage._match(line, text)})
    # (of the lyrics made of a sheet's words, those whose lines aren't another's: its words and their other spelling)
    for name in lyrics + [n for n in of_sheet if not n.endswith((" words, half", " words, and more"))]:
        out.append({"fn": k + "lyric_lines", "case": "fixture", "args": [ref(name)],
                    "out": coverage.lyric_lines(texts[name])})
    for name in sheets:
        out.append({"fn": k + "sheet_lyric_text", "case": "fixture", "args": [ref(name)],
                    "out": coverage.sheet_lyric_text(texts[name])})
    # every fixture sheet against every fixture lyrics, and a sheet's own words against it and the edges' sheet
    pairs = [(sheet, words) for sheet in sheets for words in lyrics
             if sheet not in HARMONICA_TABS or words in ("lyrics", "edge lyrics")]
    pairs += [(sheet, words) for words, own in of_sheet.items() for sheet in (own, "edges")]
    for sheet, words in pairs:
        text = coverage._comparable(coverage.sheet_lyric_text(texts[sheet]))
        lines = coverage.lyric_lines(texts[words])
        for line_match in (85,) if sheet != "edges" else (85, 82.5, 100):
            share = coverage.coverage(texts[sheet], lines, line_match=line_match)
            r = {"fn": k + "coverage", "case": "fixture",
                 "kw": {"sheet": ref(sheet), "lyrics": ref(words), "line_match": line_match}, "out": share}
            # each line's score where it tells more than the share: a share strictly between none and all, or a
            # sheet against its own words (once: a score doesn't depend on line_match)
            if line_match == 85 and (share is not None and 0 < share < 1 or of_sheet.get(words) == sheet):
                r["scores"] = [coverage._match(coverage._comparable(line), text) for line in lines] if text else []
            out.append(r)
    # tests/test_coverage.py's sheets and lyrics, as given
    for sheet, words in (
            ("[ch]Bm[/ch]   [ch]G[/ch]\nElla durmio, al calor de las masas\n[ch]D[/ch]\nY yo desperte, queriendo sonarla",
             "Ella durmió al calor de las masas\nY yo desperté queriendo soñarla"),
            ("[ch]C[/ch]      [ch]G[/ch]\n斑马斑马 你不要睡着啦\n[ch]Am[/ch]     [ch]F[/ch]\n再给我看看你受伤的尾巴",
             "斑马斑马你不要睡着啦\n再给我看看你受伤的尾巴\n我不想去触碰你伤口的疤"),
            ("[Intro]\n[ch]G[/ch] [ch]D[/ch] [ch]Em[/ch] [ch]C[/ch]\nI\n[ch]G[/ch] [ch]D[/ch]\n", LYRICS),
            ("[ch]C[/ch]      [ch]G[/ch]\n我\n[ch]Am[/ch]     [ch]F[/ch]\n",
             "斑馬斑馬你不要睡著啦\n再給我看看你受傷的尾巴\n我不想去觸碰你傷口的疤"),
            ("[ch]G[/ch]          [ch]D[/ch]\nWalking down the empty road\n", LYRICS),
            ("[ch]C[/ch]      [ch]G[/ch]\n斑马斑马 你不要睡着啦\n[ch]Am[/ch]     [ch]F[/ch]\n再给我看看你受伤的尾巴",
             "斑馬斑馬你不要睡著啦\n再給我看看你受傷的尾巴"),
            (FULL_SHEET, ""), ("", LYRICS), ("Walking", "Walking down the empty road tonight\nwalking"),
    ):
        lines = coverage.lyric_lines(words)
        text = coverage._comparable(coverage.sheet_lyric_text(sheet))
        out.append({"fn": k + "coverage", "case": "hand", "kw": {"sheet": sheet, "lyrics": words, "line_match": 85},
                    "out": coverage.coverage(sheet, lines, line_match=85),
                    "scores": [coverage._match(coverage._comparable(line), text) for line in lines] if text else []})
    return out


# --- sheet_versions.py --------------------------------------------------------------------------------------------

SONGS = {  # the fixture's songs, by the name its records give each
    "wall": ("Oasis", "Wonderwall"), "soda": ("Soda Stereo", "De Música Ligera"), "riptide": ("Vance Joy", "Riptide"),
    "georgia": ("Vance Joy", "Georgia"), "creep": ("Radiohead", "Creep"), "nude": ("Radiohead", "Nude"),
    "none": ("Nobody", "Nothing"), "zebra": ("宋冬野", "斑马，斑马"), "tabs": ("Led Zeppelin", "Stairway to Heaven"),
    "gone": ("Blur", "Song 2"), "ties": ("Queen", "Bohemian Rhapsody"),
}
UG = "https://tabs.ultimate-guitar.com/tab/"


def _song_id(conn, name: str) -> int:
    from caracole.normalize import identity_key
    from caracole.songs import find_song

    song = find_song(conn, identity_key(*SONGS[name]))
    assert song is not None, name
    return song.id


def build_library(lib) -> None:
    from caracole.db import kv_set_json
    from caracole.library import keep_file
    from caracole.sheet_versions import same_key, unkeepable_key, yours_key
    from caracole.songs import find_song, get_song, update_song
    from caracole.versions import mark_gone, mark_stale, set_coverage, upsert_version

    conn = lib.conn
    for artist, title in SONGS.values():
        lib.song(artist, title, sheet=None, lyrics=None)

    def version(song: str, tab: str, *, rating: float = 4.5, votes: int = 100, number: int = 1,
                coverage: float | None = None, raw: Any = None, provider: str = "ug", kind: str = "chords",
                slot: str = "sheet", label: str | None = None, url: str | None = None) -> int:
        vid = upsert_version(conn, provider=provider, tab_id=tab, song_id=_song_id(conn, song), slot=slot, kind=kind,
                             rating=rating, votes=votes, version=number, label=label, url=url or UG + tab,
                             raw=raw if raw is not None else {}, now=NOW)
        if coverage is not None:
            set_coverage(conn, vid, coverage)
        return vid

    def keep(song: str, vid: int, name: str, rank: int = 1) -> None:
        s = get_song(conn, _song_id(conn, song))
        assert keep_file(conn, lib.cfg.library_dir, song=s, version_id=vid, name=name, data=name.encode(), rank=rank)

    # Oasis - Wonderwall: scored, complete and not, never scored, ties, notes of every shape, gone, kept, the one,
    # a lacuerda version and a text tab (neither listed), a URL robots.txt closes, records of every kv.
    w = "wall"
    v1 = version(w, "1", rating=5.0, votes=900, coverage=0.4, raw={"version_description": " Capo 2\n  slowly "})
    v2 = version(w, "2", rating=4.6, votes=200, number=2, coverage=0.9)
    version(w, "3", rating=4.8, votes=300, number=3, coverage=0.95, raw={"version_description": "x" * 300})
    version(w, "4", rating=4.9, votes=500, number=4, raw={"version_description": {"not": "a note"}})
    version(w, "5", rating=4.2, votes=50, number=5, raw={"version_description": "  \n "})
    version(w, "6", rating=4.9, votes=500, number=4, raw={"version_description": None})
    v10 = version(w, "10", rating=4.9, votes=500, number=4, raw={"version_description": 42})
    v7 = version(w, "7", rating=4.95, votes=900, raw={"version_description": "gone, still kept"})
    mark_gone(conn, v7)
    version(w, "8", rating=4.1, votes=12, coverage=0.8, raw={"z": 1, "version_description": "\u3000a\xa0b\u2028c d"})
    version(w, "9", rating=3.9, votes=3, raw={"version_description": "😀" * 150 + "é" * 100})
    version(w, "20", rating=4.0, votes=10, url="https://www.ultimate-guitar.com/tab-pro/download?id=20")
    version(w, "30", rating=3.0, votes=1, raw={"version_description": math.nan})
    version(w, "31", rating=0.0, votes=0, number=0, label="intro")
    v40 = version(w, "40", rating=4.4, votes=40, coverage=0.0)
    version(w, "lc", rating=4.99, votes=999, provider="lacuerda", kind="acordes")
    tab = version(w, "900", rating=4.0, votes=10, kind="tabs", slot="guitar")
    keep(w, v2, "sheet.txt")
    keep(w, v1, "version-1.txt", 2)
    keep(w, v1, "version-1.json", 2)
    keep(w, v1, "version-1.html", 2)
    keep(w, v10, "version-10.txt", 3)
    keep(w, v40, "version-40.txt", 3)
    keep(w, v7, "version-7.txt", 4)
    keep(w, v40, "version-0040.txt", 5)
    keep(w, v10, "version-6.json", 6)  # a version's JSON alone: none kept
    keep(w, tab, "tab.txt")
    wall = _song_id(conn, w)
    kv_set_json(conn, same_key(wall), {"5": "version-1.html", "6": "sheet.html", "9": "version-9.html", "4": 5,
                                       "31": "version-40.html"})
    kv_set_json(conn, yours_key(wall), ["3", 10])
    kv_set_json(conn, unkeepable_key(wall), ["6", 8])
    # Soda Stereo: its sheet LaCuerda's, its UG versions listed, one kept beside it
    lc = version("soda", "lc-1", provider="lacuerda", kind="acordes")
    version("soda", "11", rating=4.1, votes=10)
    v12 = version("soda", "12", rating=4.0, votes=900, raw={"version_description": "live"})
    keep("soda", lc, "sheet.txt")
    keep("soda", v12, "version-12.txt", 2)
    # Vance Joy - Riptide: a ukulele sheet, the ukulele versions listed
    uke = version("riptide", "301", kind="ukulele", rating=4.9)
    version("riptide", "302", kind="ukulele", rating=4.5)
    version("riptide", "101", rating=4.0)
    keep("riptide", uke, "sheet.txt")
    # Vance Joy - Georgia: ukulele versions alone, no sheet
    version("georgia", "201", kind="ukulele")
    version("georgia", "202", kind="ukulele", rating=4.0)
    # Radiohead - Creep: a version of an earlier match, then one of this
    version("creep", "71")
    mark_stale(conn, _song_id(conn, "creep"), "ug")
    version("creep", "72")
    # Radiohead - Nude: an acoustic song, labels its variant weighs or not
    update_song(conn, _song_id(conn, "nude"), variant="acoustic")
    version("nude", "80", rating=4.9, votes=500)
    version("nude", "81", rating=4.2, votes=50, label="Acoustic")
    version("nude", "82", rating=4.3, votes=60, label="unplugged")
    version("nude", "83", rating=4.95, votes=800, label="intro")
    version("nude", "84", rating=4.3, votes=60, label="acoustic", coverage=0.85)
    # 宋冬野 - 斑马，斑马: its chords gone, a ukulele version live
    mark_gone(conn, version("zebra", "401"))
    version("zebra", "402", kind="ukulele")
    # Led Zeppelin: a sheet.txt kept from a text tab (no UG sheet of the sheet's kinds)
    t = version("tabs", "501", kind="tabs")
    version("tabs", "502")
    keep("tabs", t, "sheet.txt")
    # Blur: every version gone
    mark_gone(conn, version("gone", "601"))
    mark_gone(conn, version("gone", "602", kind="ukulele"))
    # Queen: ratings and versions tied, tab ids of every length
    for tab in ("100", "99", "1000", "0100", "2", "10"):
        version("ties", tab, rating=4.0, votes=10, number=2 if tab == "2" else 1)
    # The offline index's tabs, for sheet_pins
    for tab_id, kind in ((7001, "chords"), (7002, "tabs"), (7003, "ukulele"), (7004, "Chords")):
        conn.execute("INSERT INTO ug_index (tab_id, artist_key, song_key, type, sitemap, first_seen, path) "
                     "VALUES (?, 'oasis', 'wonderwall', ?, 'sitemap1.xml', ?, ?)",
                     (tab_id, kind, NOW, f"/tab/oasis/wonderwall-{kind}-{tab_id}"))
    assert find_song(conn, "nobody/nothing") is not None


def _settled(conn) -> None:
    conn.execute("UPDATE songs SET created_at = ?, updated_at = ?", (NOW, NOW))
    conn.execute("UPDATE files SET created_at = ?", (NOW,))


def _versions(listed) -> list[dict[str, Any]]:
    return [plain(v) for v in listed]


def sheet_version_records(conn) -> list[dict[str, Any]]:
    from caracole import sheet_versions as sv
    from caracole.config import RankPolicy
    from caracole.versions import VersionRow

    k = "caracole.sheet_versions."
    fx = "library"
    out: list[dict[str, Any]] = []
    ids = {name: _song_id(conn, name) for name in SONGS}
    policies = (_policy(), _policy(coverage_threshold=0.95, prior_votes=0), _policy(prior_votes=2.5, variant_bonus=2))

    def rec(fn: str, case: str, kw: dict[str, Any], result: Any, *, fixture: str | None = fx,
            after: dict[str, Any] | None = None, dumps: Any = None) -> None:
        r = {"fn": k + fn, "case": case, "fixture": fixture, "kw": kw, "out": result}
        if after is not None:
            r["after"] = after
        if dumps is not None:  # the answer's members in Python's order, which the sorted line loses
            r["dumps"] = json.dumps(dumps, ensure_ascii=False)
        out.append(r)

    for tab in ("39144", "7", "0012", ""):
        out.append({"fn": k + "version_names", "case": "hand", "fixture": None, "args": [tab],
                    "out": sv.version_names(tab)})
    for name in ("version-39144.txt", "version-39144.json", "version-39144.html", "sheet.txt", "version-.txt",
                 "version-12.pdf", "version-1a.txt", "version-12.txt.bak", "version-0012.txt", "version-١٢.txt",
                 "version-12.TXT", "Version-12.txt", "version-12.txt\n", "xversion-12.txt", "version-12.htm"):
        out.append({"fn": k + "tab_of", "case": "hand", "fixture": None, "args": [name], "out": sv.tab_of(name)})

    def rows(*specs: tuple[str, str, bool]) -> list[VersionRow]:
        return [VersionRow(id=i, provider="ug", tab_id=tab, song_id=1, slot="sheet", kind=kind, rating=0.0, votes=0,
                           version=1, label=None, coverage=None, url="", raw={}, fetched_at=NOW, pick_rank=None,
                           gone=gone) for i, (kind, tab, gone) in enumerate(specs, start=1)]

    for case, specs, chosen in (
            ("no rows: chords", (), None),
            ("chords live", (("chords", "1", False), ("ukulele", "2", False)), None),
            ("chords gone alone: ukulele", (("chords", "1", True), ("ukulele", "2", False)), None),
            ("ukulele alone", (("ukulele", "2", False),), None),
            ("the chosen one's kind", (("chords", "1", False), ("ukulele", "2", False)), "2"),
            ("a chosen tab no row has", (("chords", "1", True), ("ukulele", "2", False)), "9"),
            ("the chosen one gone still names it", (("chords", "1", True), ("ukulele", "2", False)), "1"),
            ("every row gone", (("chords", "1", True), ("ukulele", "2", True)), None),
    ):
        listed = rows(*specs)
        out.append({"fn": k + "group_of", "case": case, "fixture": None,
                    "kw": {"rows": [{"kind": r.kind, "tab_id": r.tab_id, "gone": r.gone} for r in listed],
                           "chosen_tab": chosen},
                    "out": sv.group_of(listed, chosen)})

    for name, song_id in ids.items():
        rec("library_state", name, {"song_id": song_id}, sv.library_state(conn, song_id))
        same = sv.same_pages(conn, song_id)
        rec("same_pages", name, {"song_id": song_id}, same, dumps=same)
        rec("sheet_kind", name, {"song_id": song_id}, sv.sheet_kind(conn, song_id))
        rec("kept_by_you", name, {"song_id": song_id}, sv.kept_by_you(conn, song_id))
        rec("unkeepable", name, {"song_id": song_id}, sv.unkeepable(conn, song_id))
        # another policy only where it can reorder the list: a song of versions scored, or labelled for its variant
        for policy in {"wall": policies[:2], "nude": policies[::2]}.get(name, policies[:1]):
            listed = sv.in_library(conn, song_id, RankPolicy(**policy))
            rec("in_library", name, {"song_id": song_id, "policy": policy}, _versions(listed))
            if policy is not policies[0]:
                continue
            if name in ("wall", "nude", "none"):
                data = sv.as_data(listed, 13)
                rec("as_data", name, {"song_id": song_id, "policy": policy, "total": 13}, data, dumps=data)
            for block in ([], [4, 8, 99]) if name in ("wall", "ties") else ([],):
                rec("may_keep", name, {"song_id": song_id, "policy": policy, "block": block},
                    _versions(sv.may_keep(conn, song_id, listed, block)))
    every = sorted(ids.values())
    for case, song_ids in (("every song", every + [9999]), ("none", []), ("a song with none", [ids["none"]]),
                           ("one, given twice", [ids["riptide"], ids["riptide"]]), ("unknown", [9999]),
                           ("out of order", [ids["riptide"], ids["creep"], ids["soda"]])):
        for policy in policies[:1]:
            listed = sv.in_library_of(conn, song_ids, RankPolicy(**policy))
            rec("in_library_of", case, {"song_ids": song_ids, "policy": policy},
                [[song_id, _versions(v)] for song_id, v in listed.items()])
    for case, name, chosen, kept, same in (
            ("none chosen or kept", "wall", None, [], None),
            ("chosen a gone one", "wall", "7", [], None),
            ("the one and two kept", "nude", "80", ["81", "83"], None),
            ("a kept tab no version has", "nude", "80", ["555"], None),
            ("those a kept one's text", "nude", "80", ["81"], {"82": "version-81.html", "84": "sheet.html"}),
            ("chosen another site's tab", "nude", "lc", ["84"], None),
    ):
        policy = policies[0]
        rec("song_sheet_versions", case,
            {"song_id": ids[name], "policy": policy, "chosen_tab": chosen, "kept_tabs": kept, "same_as": same},
            _versions(sv.song_sheet_versions(conn, ids[name], RankPolicy(**policy), chosen_tab=chosen, kept_tabs=kept,
                                             same_as=same)))
    wall = ids["wall"]
    for name in ("riptide", "ties", "zebra"):
        rec("song_sheet_versions", name, {"song_id": ids[name], "policy": policies[0], "chosen_tab": None,
                                          "kept_tabs": [], "same_as": None},
            _versions(sv.song_sheet_versions(conn, ids[name], RankPolicy(), chosen_tab=None, kept_tabs=())))
    for case, pins in (("chords and a text tab of the song's", [1, 900, 2]), ("the index's kinds", [7001, 7002, 7003,
                       7004]), ("a tab neither knows", [123456]), ("a chords tab of the song's", [5]), ("none", [])):
        rec("sheet_pins", case, {"song_id": wall, "pins": pins}, sv.sheet_pins(conn, wall, pins))
    rec("sheet_pins", "a ukulele song's", {"song_id": ids["riptide"], "pins": [301, 101, 7002]},
        sv.sheet_pins(conn, ids["riptide"], [301, 101, 7002]))
    return out


def writer_records(replay) -> list[dict[str, Any]]:
    """The kv writers, each over a fresh copy of the fixture: their answer and the record they leave."""
    from caracole import sheet_versions as sv
    from caracole.db import kv_get

    k = "caracole.sheet_versions."
    out = []
    for fn, key_of, case, name, tab in (
            ("note_kept_by_you", sv.yours_key, "a new tab after the others", "wall", "4"),
            ("note_kept_by_you", sv.yours_key, "a tab there already: nothing", "wall", "10"),
            ("note_kept_by_you", sv.yours_key, "a song with none", "soda", "11"),
            ("note_unkeepable", sv.unkeepable_key, "a new tab", "wall", "9"),
            ("note_unkeepable", sv.unkeepable_key, "an int given, as a string", "wall", 31),
            ("note_unkeepable", sv.unkeepable_key, "there already, given as an int", "wall", 8),
            ("note_unkeepable", sv.unkeepable_key, "a song with none", "riptide", "302"),
    ):
        with replay() as conn:
            song_id = _song_id(conn, name)
            result = getattr(sv, fn)(conn, song_id, tab)
            out.append({"fn": k + fn, "case": case, "fixture": "library", "kw": {"song_id": song_id, "tab_id": tab},
                        "out": result, "after": {"kv": {key_of(song_id): kv_get(conn, key_of(song_id))}}})
    return out


# --- the files -----------------------------------------------------------------------------------------------------


class Made:
    def __init__(self, workdir: Path):
        from helpers.peer_libraries import Library

        self.workdir = workdir
        self.n = 0
        lib = Library(workdir / "built")
        try:
            build_library(lib)
            _settled(lib.conn)
            fixture = [r for r in dump_fixture(lib.conn)]
        finally:
            lib.close()
        self.fixture = jsonl(fixture, corpus="sites/ug_sheet_versions_fixture_library", made_by=MADE_BY)
        records, texts, sheets, lyrics, of_sheet = coverage_texts()
        self.texts = jsonl(records.values(), corpus="sites/ug_coverage_texts", made_by=MADE_BY)
        self.coverage = jsonl(coverage_records(texts, sheets, lyrics, of_sheet), corpus="sites/ug_coverage", made_by=MADE_BY)
        self.rank = jsonl(rank_records(), corpus="sites/ug_rank", made_by=MADE_BY)
        with self.replayed() as conn:
            listed = sheet_version_records(conn)
        listed += writer_records(self.replayed)
        self.sheet_versions = jsonl(listed, corpus="sites/ug_sheet_versions", made_by=MADE_BY)

    def replayed(self):
        from contextlib import contextmanager

        from caracole import db
        from conftest import migrated_database

        @contextmanager
        def copy():
            self.n += 1
            path = self.workdir / f"replayed-{self.n}.sqlite"
            path.write_bytes(migrated_database())
            conn = db.connect(path)
            try:
                replay_fixture(conn, _records(self.fixture))
                yield conn
            finally:
                conn.close()
        return copy()

    def files(self) -> dict[Path, str]:
        return {RANK: self.rank, COVERAGE: self.coverage, TEXTS: self.texts, SHEET_VERSIONS: self.sheet_versions,
                FIXTURE: self.fixture}


@pytest.fixture(scope="module")
def made(tmp_path_factory) -> Made:
    return Made(tmp_path_factory.mktemp("rank"))


@pytest.mark.parametrize("path", [RANK, COVERAGE, TEXTS, SHEET_VERSIONS, FIXTURE], ids=lambda p: p.name)
def test_the_vector_is_what_rank_coverage_and_sheet_versions_answer(made, path):
    check(path, made.files()[path])


def test_every_function_the_port_meets_is_in_the_vectors(made):
    from caracole import coverage, rank, sheet_versions

    def fns(text: str) -> set[str]:
        return {r["fn"] for r in _records(text)}

    assert fns(made.rank) == {f"caracole.rank.{f}" for f in ("bayes", "prior_mean", "is_complete", "rank_by_rating",
                                                            "rank_sheets", "rank_guitar")} | {
        "caracole.versions.complete", "caracole.versions.replaces_sheet", "caracole.config.RankPolicy"}
    assert fns(made.coverage) == {f"caracole.coverage.{f}" for f in (
        "normalize_line", "lyric_lines", "sheet_lyric_text", "_is_plain_chord_line", "_comparable", "_match",
        "coverage")}
    assert fns(made.sheet_versions) == {f"caracole.sheet_versions.{f}" for f in (
        "version_names", "tab_of", "group_of", "library_state", "same_pages", "sheet_kind", "kept_by_you",
        "unkeepable", "note_kept_by_you", "note_unkeepable", "may_keep", "sheet_pins", "in_library", "in_library_of",
        "as_data", "song_sheet_versions")}
    for module, names in ((rank, fns(made.rank)), (coverage, fns(made.coverage)),
                          (sheet_versions, fns(made.sheet_versions))):
        for name in names:
            if name.startswith(module.__name__ + "."):
                assert callable(getattr(module, name.rsplit(".", 1)[1]))
    assert {f.name for f in fields(rank.Candidate)} - {"score", "version_id", "provider", "kind"} == set(
        cand("1", 0, 0))


def test_the_vectors_cover_what_they_say(made):
    records = _records(made.coverage)
    scored = [r for r in records if r["fn"] == "caracole.coverage.coverage" and r["case"] == "fixture"]
    shares = {r["out"] for r in scored}
    assert 0.0 in shares and 1.0 in shares and any(0 < s < 1 for s in shares if s is not None)
    assert None in {r["out"] for r in records if r["fn"] == "caracole.coverage.coverage" and r["case"] == "hand"}
    assert any(r["out"] is not None and 0.8 <= r["out"] < 1 for r in scored)
    # the whole-string ratio taken for a sheet shorter than a line, and partial_ratio for one that holds it
    matched = [r["args"] for r in records if r["fn"] == "caracole.coverage._match"]
    assert any(len(t) < len(line) for line, t in matched) and any(len(t) > len(line) for line, t in matched)
    ranked = [r for r in _records(made.rank) if r["fn"].startswith("caracole.rank.rank_")]
    assert any(len(r["out"]) > 1 and len({s for _, s in r["out"]}) < len(r["out"]) for r in ranked)  # ties
    listed = [r for r in _records(made.sheet_versions) if r["fn"] == "caracole.sheet_versions.in_library"]
    every = [v for r in listed for v in r["out"]]
    assert {v["page"] for v in every} >= {"sheet.html", "version-1.html", "version-40.html", None}
    assert any(v["gone"] and v["kept"] for v in every) and any(v["complete"] is None for v in every)
    assert any(v["note"] is not None and len(v["note"]) == 200 for v in every)


def test_the_vectors_are_the_same_on_another_run(made, tmp_path):
    again = Made(tmp_path)
    assert again.files() == made.files()
