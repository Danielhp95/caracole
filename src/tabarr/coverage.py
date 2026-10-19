"""Lyric coverage: how much of LRCLIB's lyrics a chord sheet actually contains.

A sheet is "complete" when it covers at least 80% of the song's distinct lyric
lines; a line counts as covered when rapidfuzz ``partial_ratio`` against the
sheet's lyric text is 85 or more (plan §3). This sinks sheets that chart only
the first verse, or no lyrics at all, below any complete one.
"""

from __future__ import annotations

import re
from typing import Sequence

from rapidfuzz import fuzz

from tabarr.normalize import fold

_NON_WORD = re.compile(r"[\W_]+")
_CH_SPAN = re.compile(r"\[ch\].*?\[/ch\]", re.IGNORECASE)
_TAB_TAGS = re.compile(r"\[/?tab\]", re.IGNORECASE)
_SECTION = re.compile(r"^\s*\[[^\]\n]*\]\s*$")
_FILLER = re.compile(r"^[\s|/\\\-–x×0-9().:*]*$", re.IGNORECASE)
_STAFF = re.compile(r"^\s*[A-Ga-g]?[#b]?\s*\|.*-{2,}")
_CHORD_TOKEN = re.compile(
    r"^\(?(?:[A-G][#b]?|(?:do|re|mi|fa|sol|la|si)[#b]?)"
    r"(?:m|maj|min|dim|aug|sus|add|M|°|ø|\+|-)?\d*(?:(?:sus|add|maj|b|#)\d+)*"
    r"(?:/[A-G][#b]?)?\)?$",
    re.IGNORECASE,
)
_FILLER_TOKEN = re.compile(r"^(?:\||-+|/|x\d+|\(x?\d+\)|\d+x|\*+)$", re.IGNORECASE)
MIN_LINE_CHARS = 4


def normalize_line(s: str) -> str:
    """Fold accents and case, turn punctuation into spaces, collapse whitespace."""
    return " ".join(_NON_WORD.sub(" ", fold(s)).split())


def lyric_lines(plain: str) -> list[str]:
    """The distinct, normalized lyric lines (choruses count once; very short lines are skipped)."""
    seen: set[str] = set()
    out: list[str] = []
    for line in plain.splitlines():
        n = normalize_line(line)
        if len(n) < MIN_LINE_CHARS or n in seen:
            continue
        seen.add(n)
        out.append(n)
    return out


def _is_plain_chord_line(line: str) -> bool:
    tokens = line.split()
    if not tokens:
        return False
    chords = [t for t in tokens if _CHORD_TOKEN.match(t)]
    return bool(chords) and all(_CHORD_TOKEN.match(t) or _FILLER_TOKEN.match(t) for t in tokens)


def sheet_lyric_text(sheet: str) -> str:
    """The lyrics in a sheet, as one normalized string.

    Drops chord lines (``[ch]`` markup or plain chord names), tab staff lines and
    ``[Section]`` headers, and removes chords written inline.
    """
    kept: list[str] = []
    for raw in sheet.splitlines():
        line = _TAB_TAGS.sub("", raw)
        without_chords = _CH_SPAN.sub(" ", line)
        if _CH_SPAN.search(line) and _FILLER.match(without_chords):
            continue
        if _SECTION.match(line) or _STAFF.match(line):
            continue
        if _is_plain_chord_line(without_chords):
            continue
        text = normalize_line(without_chords)
        if text:
            kept.append(text)
    return " ".join(kept)


def coverage(sheet: str, lines: Sequence[str], *, line_match: int = 85) -> float | None:
    """Share of ``lines`` (from ``lyric_lines``) found in the sheet; None without lyrics."""
    if not lines:
        return None
    text = sheet_lyric_text(sheet)
    if not text:
        return 0.0
    covered = sum(1 for line in lines if fuzz.partial_ratio(line, text) >= line_match)
    return covered / len(lines)
