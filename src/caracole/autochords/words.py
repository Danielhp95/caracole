"""A transcript's words, kept where someone sings, broken into lines and written as enhanced LRC.

Pure Python, no I/O. ``sung_spans`` finds where a voice is, from the loudness of the separated vocal stem
against the full mix's; ``guard`` drops the words Whisper invented over the instrumental parts; ``lines_of``
and ``to_lrc`` turn the rest into the enhanced LRC that ``merge.parse_lrc_words`` reads.
"""

import re
from dataclasses import dataclass

from caracole.chordpro import display_columns

FRAME_S = 0.05  # one loudness frame
JOIN_S = 0.4  # sung runs closer than this are one
MIN_RUN_S = 0.3  # a sung run shorter than this is noise
PAD_S = 0.2  # a span reaches this far past its run on each side
SLACK_S = 0.3  # a word within this of a span is kept
# Starting values for the stem-to-mix rule, measured again on real songs.
STEM_WITHIN_DB = 10.0  # the stem is sung when it is at most this far under the mix
FLOOR_DB = 40.0  # frames this far under the mix's loudest are silence

SEG_COLS = 12  # a Whisper segment's first word breaks a line this wide
PUNCT_COLS = 18  # a line ending in punctuation breaks once this wide
BREATH_S = 0.5  # silence from a word's end to the next word's start that is a breath...
BREATH_COLS = 4  # ...and breaks a line this wide
MAX_COLS = 52  # no line is wider
BREAK_S = 2.0  # silence that gets an empty LRC line

_PUNCT = re.compile(r"[.,!?;，。！？；、]$")


@dataclass(frozen=True)
class Word:
    start: float
    end: float
    text: str
    space: bool  # a space comes before it, within a line
    segment_start: bool = False  # the first word of a Whisper segment


@dataclass(frozen=True)
class Span:
    start: float
    end: float


def sung_spans(
    stem_db: list[float], mix_db: list[float], *, frame_s: float = FRAME_S
) -> list[Span]:
    """Where a voice sings: frames where the stem is within ``STEM_WITHIN_DB`` of the mix and the mix is
    within ``FLOOR_DB`` of its loudest, joined across gaps under ``JOIN_S``, runs under ``MIN_RUN_S``
    dropped, each padded by ``PAD_S``."""
    if not mix_db:
        return []
    floor = max(mix_db) - FLOOR_DB
    runs: list[list[float]] = []
    start: int | None = None
    for i in range(len(mix_db) + 1):
        sung = i < len(mix_db) and stem_db[i] >= mix_db[i] - STEM_WITHIN_DB and mix_db[i] >= floor
        if sung and start is None:
            start = i
        elif not sung and start is not None:
            a, b = start * frame_s, i * frame_s
            if runs and a - runs[-1][1] < JOIN_S - 1e-9:
                runs[-1][1] = b
            else:
                runs.append([a, b])
            start = None
    return [
        Span(round(max(0.0, a - PAD_S), 3), round(b + PAD_S, 3))
        for a, b in runs
        if b - a >= MIN_RUN_S - 1e-9
    ]


def guard(words: list[Word], spans: list[Span]) -> tuple[list[Word], list[Word]]:
    """``(kept, dropped)``: a word goes when its start and its end both lie more than ``SLACK_S`` outside
    every span (a word that reaches across a span is not outside it)."""
    kept: list[Word] = []
    dropped: list[Word] = []
    for word in words:
        near = any(word.start <= s.end + SLACK_S and word.end >= s.start - SLACK_S for s in spans)
        (kept if near else dropped).append(word)
    return kept, dropped


def _width(line: list[Word]) -> int:
    return display_columns(_joined(line))[-1]


def _joined(line: list[Word]) -> str:
    return "".join((" " if word.space and n else "") + word.text for n, word in enumerate(line))


def lines_of(words: list[Word]) -> list[list[Word]]:
    """The words as lines: a new line before a word when the current one is not empty and a Whisper segment
    starts and the line is ``SEG_COLS`` wide, or it ends in punctuation and is ``PUNCT_COLS`` wide, or a
    breath of ``BREATH_S`` came and it is ``BREATH_COLS`` wide, or it is ``MAX_COLS`` wide."""
    lines: list[list[Word]] = []
    current: list[Word] = []
    for word in words:
        if current:
            width = _width(current)
            if (
                (word.segment_start and width >= SEG_COLS)
                or (_PUNCT.search(current[-1].text) and width >= PUNCT_COLS)
                or (word.start - current[-1].end >= BREATH_S - 1e-9 and width >= BREATH_COLS)
                or width >= MAX_COLS
            ):
                lines.append(current)
                current = []
        current.append(word)
    if current:
        lines.append(current)
    return lines


def _stamp(t: float, *, word: bool = False) -> str:
    centis = round(max(0.0, t) * 100)
    minutes, rest = divmod(centis, 6000)
    text = f"{minutes:02d}:{rest // 100:02d}.{rest % 100:02d}"
    return f"<{text}>" if word else f"[{text}]"


def to_lrc(lines: list[list[Word]]) -> str:
    """Enhanced LRC: ``[mm:ss.xx]`` per line, ``<mm:ss.xx>`` before each word, a space only where
    ``word.space``; an empty stamped line at a line's last word's end when the next line starts
    ``BREAK_S`` or more later."""
    out: list[str] = []
    for n, line in enumerate(lines):
        body = "".join(
            (" " if word.space and k else "") + _stamp(word.start, word=True) + word.text
            for k, word in enumerate(line)
        )
        out.append(_stamp(line[0].start) + " " + body)
        if n + 1 < len(lines) and lines[n + 1][0].start - line[-1].end >= BREAK_S - 1e-9:
            out.append(_stamp(line[-1].end))
    return "".join(row + "\n" for row in out)
