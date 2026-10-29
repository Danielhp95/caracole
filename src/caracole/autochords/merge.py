"""Merge recognized chords with lyrics into an auto-generated chord sheet.

The sheet is Ultimate Guitar markup, like every human sheet in the library:
chords wrapped in ``[ch]…[/ch]`` on a line above the lyric they belong to, and
``[Section]`` headers, so the ChordPro converter and the coverage scorer read it
unchanged. Its first line is always ``auto-generated, unverified``.

Pure Python, so it runs in the default environment; the models live in
``btc.py`` and ``beats.py``.
"""

from __future__ import annotations

import bisect
import itertools
import re
import statistics
import unicodedata
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, replace

NO_CHORD = "N"
AUTO_MARKER = "auto-generated, unverified"
DEFAULT_BEAT = 0.5  # seconds (120 BPM), when no beats were detected
BEATS_PER_BAR = 4
BARS_PER_LINE = 4
GAP_BARS = 2  # an instrumental gap at least this long gets chord-only lines
_EPS = 1e-6

_STAMP_RUN = re.compile(r"(?:\s*\[\d+:\d{1,2}(?:[.:]\d+)?\])+")
_STAMP = re.compile(r"\[(\d+):(\d{1,2})(?:[.:](\d+))?\]")
_TAG = re.compile(r"\[([A-Za-z#]+):(.*)\]")
_WORD_STAMP = re.compile(r"<\d+:\d{1,2}(?:[.:]\d+)?>")
_WORD_TIME = re.compile(r"<(\d+):(\d{1,2})(?:[.:](\d+))?>")  # _WORD_STAMP, read
# A line's text after its stamps, piece by piece: a word stamp, a run of spaces, or a run of
# other characters up to the next word stamp.
_WORD_PIECE = re.compile(rf"({_WORD_STAMP.pattern})|(\s+)|((?:(?!{_WORD_STAMP.pattern})\S)+)")

WordStarts = tuple[tuple[float, int], ...]


@dataclass(frozen=True)
class ChordSegment:
    """A chord sounding from ``start`` to ``end`` seconds. The label "N" means no chord."""

    start: float
    end: float
    label: str


@dataclass(frozen=True)
class LrcLine:
    """A timed LRC line as ``parse_lrc_words`` reads it.

    ``time`` and ``text`` are what ``parse_lrc`` gives for it. ``words``: for each
    enhanced-LRC word stamp (``<mm:ss.xx>word``), the time it marks and the column
    in ``text`` where its word begins (its syllable, for a stamp inside a word), in
    the order written; None when no word stamp of the line comes before a word.
    """

    time: float
    text: str
    words: WordStarts | None = None


def parse_lrc(text: str) -> list[tuple[float, str]]:
    """The timed lines of an LRC file, sorted by time.

    Reads ``[mm:ss.xx]``, ``[mm:ss.xxx]``, ``[mm:ss:xx]`` and ``[mm:ss]`` stamps,
    several stamps on one line, and enhanced-LRC word stamps (dropped; ``parse_lrc_words``
    keeps them). Metadata tags such as ``[ar:…]`` and ``[ti:…]`` are ignored, except
    ``[offset:±ms]``: a positive offset makes every line appear earlier. A stamp with
    no text is kept as ``""``, because LRC files mark instrumental breaks that way.
    """
    return [(line.time, line.text) for line in parse_lrc_words(text)]


def parse_lrc_words(text: str) -> list[LrcLine]:
    """The timed lines of an LRC file, as ``parse_lrc`` reads them, each with its word stamps.

    A word stamp times the word (or syllable) written right after it; of several in a row,
    the last one does, and one after a line's last word (where that word ends) times
    nothing. ``[offset:±ms]`` moves the word stamps as it moves the lines. A line stamped
    with several times keeps its word stamps as written for each of them.
    """
    offset = 0.0
    timed: list[tuple[float, str, list[tuple[float, int]]]] = []
    for raw in text.lstrip("\ufeff").splitlines():
        line = raw.strip()
        stamps = _STAMP_RUN.match(line)
        if stamps is None:
            tag = _TAG.fullmatch(line)
            if tag and tag.group(1).lower() == "offset":
                try:
                    offset = int(tag.group(2).strip()) / 1000
                except ValueError:
                    pass
            continue
        lyric, words = _stamped_words(line[stamps.end() :])
        for m in _STAMP.finditer(stamps.group()):
            timed.append((_seconds(*m.groups()), lyric, words))

    def moved(t: float) -> float:
        return round(max(0.0, t - offset), 3)

    lines = [
        LrcLine(moved(t), lyric, tuple((moved(w), col) for w, col in words) if words else None)
        for t, lyric, words in timed
    ]
    return sorted(lines, key=lambda line: line.time)


def _seconds(minutes: str, seconds: str, fraction: str | None) -> float:
    """The time a stamp's parts name, in seconds."""
    return int(minutes) * 60 + int(seconds) + (float(f"0.{fraction}") if fraction else 0.0)


def _stamped_words(rest: str) -> tuple[str, list[tuple[float, int]]]:
    """A line's text after its line stamps, as ``parse_lrc`` gives it (word stamps out,
    words one space apart), and the time and column of each word a word stamp times."""
    text = ""
    words: list[tuple[float, int]] = []
    stamp: float | None = None  # a word stamp, waiting for the word it times
    space = False
    for m in _WORD_PIECE.finditer(rest):
        stamped, spaces, chars = m.groups()
        if stamped:
            stamp = _seconds(*_WORD_TIME.fullmatch(stamped).groups())
        elif spaces:
            space = bool(text)
        else:
            if space:
                text += " "
                space = False
            if stamp is not None:
                words.append((stamp, len(text)))
                stamp = None
            text += chars
    return text, words


def snap_to_beats(segments: Iterable[ChordSegment], beats: Sequence[float]) -> list[ChordSegment]:
    """Move every chord change to the nearest beat, then clean up.

    A chord whose start and end land on the same beat (shorter than one beat) is
    dropped, and so is "N". A chord that touches the next one with the same label
    is merged with it; a chord that returns after a no-chord stretch is kept apart.

    Gaps in ``beats`` (a quiet passage where no beat was detected) are filled in,
    and the grid is extended before the first and after the last beat, so a change
    is never pulled far away. Without beats the segments are only cleaned.
    """
    segs = sorted(segments, key=lambda s: (s.start, s.end))
    if not segs:
        return []
    grid = _beat_grid(beats, until=max(s.end for s in segs))
    if len(grid) < 2:
        return _merge([s for s in segs if s.label != NO_CHORD and s.end > s.start])
    snapped = []
    for s in segs:
        a, b = _nearest(grid, s.start), _nearest(grid, s.end)
        if b > a and s.label != NO_CHORD:
            snapped.append(ChordSegment(grid[a], grid[b], s.label))
    return _merge(snapped)


def build_sheet(
    segments: Iterable[ChordSegment],
    *,
    title: str,
    artist: str,
    synced: str | None = None,
    synced_words: Sequence[LrcLine] | None = None,
    plain: str | None = None,
    beats: Sequence[float] | None = None,
    downbeats: Sequence[float] | None = None,
    source: str | None = None,
) -> str:
    """The text of ``sheet (auto).txt``. ``source``, when given, is a line after the song's
    name that says where its audio came from (a YouTube video, say).

    With synced lyrics (LRC), every lyric line gets the chords whose snapped start
    falls between its time and the next line's, at character columns proportional
    to their time within the line, each then moved to the start of the nearest
    word (``_on_words``). A change up to half a beat before a line's
    time counts as the start of that line, since singers often come in just
    after the downbeat. Where the voice rests for at least two bars, the chords
    go on chord-only lines of bars instead, such as ``| G | D | Em | C |``.

    ``synced_words`` is the same lyrics read with their word stamps (``parse_lrc_words``),
    for lyrics that time each word (enhanced LRC); given, it is what is laid out, and a
    line whose word stamps can be trusted puts each chord over the word sung when it
    starts (``_word_column``). A line without them keeps the columns by time.

    With plain lyrics only, the sheet is a chord chart of the whole song, four
    bars per line, followed by the lyrics. With no lyrics, it is the chart alone.
    """
    segs = snap_to_beats(segments, beats or [])
    if synced_words:
        lines = [(line.time, line.text) for line in synced_words]
        words: list[WordStarts | None] | None = [line.words for line in synced_words]
    else:
        lines, words = (parse_lrc(synced) if synced else []), None
    until = max([s.end for s in segs] + [t for t, _ in lines] + [0.0])
    grid = _beat_grid(beats or [], until=until)
    beat = _period(grid) or DEFAULT_BEAT
    bars = _bar_starts(grid, [s.start for s in segs], downbeats or [])
    bar = _period(bars) or BEATS_PER_BAR * beat
    out = [AUTO_MARKER, f"{artist} - {title}", *([source.strip()] if source and source.strip() else []), ""]
    if any(text for _, text in lines):
        out += _synced_body(segs, lines, tol=beat / 2, bars=bars, bar=bar, words=words)
    else:
        chart = _chart(segs, bars, _bar_at(bars, segs[0].start), segs[-1].end) if segs else []
        if chart:
            out += ["[Chords]", *chart, ""]
        lyrics = [line.rstrip() for line in (plain or "").strip("\n").splitlines()]
        if any(lyrics):
            out += ["[Lyrics]", *lyrics]
    return "\n".join(out).rstrip("\n") + "\n"


def _period(grid: Sequence[float]) -> float | None:
    """The median spacing of a sorted grid, or None when it has fewer than two points."""
    if len(grid) < 2:
        return None
    return statistics.median(b - a for a, b in itertools.pairwise(grid))


def _synced_body(
    segs: list[ChordSegment],
    lines: list[tuple[float, str]],
    *,
    tol: float,
    bars: list[float],
    bar: float,
    words: Sequence[WordStarts | None] | None = None,
) -> list[str]:
    # Each sung line, with the time of the LRC entry after it and whether that
    # entry is empty, which is how LRC files mark a break.
    sung: list[tuple[float, str, float | None, bool]] = []
    sung_words: list[WordStarts | None] = []  # each sung line's word stamps (``words``)
    for j, (t, text) in enumerate(lines):
        if text:
            after = lines[j + 1] if j + 1 < len(lines) else None
            sung.append((t, text, after[0] if after else None, after is not None and not after[1]))
            sung_words.append(words[j] if words else None)
    windows = [after - t for t, _, after, _ in sung if after is not None]
    # A line is sung for about the median line length; any longer silence is instrumental.
    typical = statistics.median(windows) if windows else GAP_BARS * bar
    music_end = segs[-1].end if segs else sung[-1][0]
    out: list[str] = []
    first = sung[0][0] - tol
    if segs and first - segs[0].start >= bar - _EPS:
        intro = _chart(segs, bars, _bar_at(bars, segs[0].start), first)
        if intro:
            out += ["[Intro]", *intro, ""]
    block_start = True
    for i, (t, text, after, rest) in enumerate(sung):
        nxt = sung[i + 1][0] if i + 1 < len(sung) else None
        sung_end = t + typical if after is None else min(after, t + typical)
        gap_end = max(music_end, sung_end) if nxt is None else nxt
        gap_start = _bar_on_or_after(bars, sung_end)
        chart: list[str] = []
        if gap_end - gap_start >= GAP_BARS * bar - _EPS:
            chart = _chart(segs, bars, gap_start, gap_end - tol)
        end = gap_start if chart else gap_end
        span = max(end - t, _EPS)
        timed = _trusted_words(sung_words[i], t, after, tol)
        placed = [
            (
                _word_column(timed, s.start, tol)
                if timed
                else max(0, int((s.start - t) / span * len(text))),
                s.label,
            )
            for s in segs
            if t - tol <= s.start < end - tol
        ]
        if block_start and not (placed and placed[0][0] == 0):
            # The first line of a block names the chord already ringing when it starts.
            ringing = [s.label for s in segs if s.start < t - tol < s.end]
            if ringing:
                placed.insert(0, (0, ringing[-1]))
        if placed:
            out.append(_chord_line(_on_words(text, placed)))
        out.append(text)
        block_start = bool(chart) or (rest and nxt is not None)
        if chart:
            out += ["", "[Outro]" if nxt is None else "[Instrumental]", *chart, ""]
        elif block_start:
            out.append("")
    return out


def _trusted_words(
    words: WordStarts | None, t: float, until: float | None, tol: float
) -> WordStarts | None:
    """A sung line's word stamps, when they can place its chords: in the order sung, the
    first no earlier than the line's time ``t``, the last no later than the next LRC entry's
    (``until``), within ``tol``. None otherwise, and the line's chords go by time alone.
    Words before the first word stamp start with the line, at ``t``."""
    if not words:
        return None
    times = [w for w, _ in words]
    if any(b < a for a, b in itertools.pairwise(times)):
        return None
    if times[0] < t - tol - _EPS or (until is not None and times[-1] > until + tol + _EPS):
        return None
    return words if words[0][1] == 0 else ((min(t, times[0]), 0), *words)


def _word_column(words: WordStarts, start: float, tol: float) -> int:
    """The column of the word sung when a chord starts at ``start``: the word starting
    nearest it within ``tol`` (a voice a little ahead of the beat or behind it), else the
    last word started before it (a chord that comes in mid-word goes over that word's
    start); 0 before the first word stamped. A word with no stamp of its own goes with the
    word stamped before it."""
    near = [(abs(w - start), col) for w, col in words if abs(w - start) <= tol + _EPS]
    if near:
        return min(near)[1]
    started = [col for w, col in words if w <= start]
    return started[-1] if started else 0


def _bar_starts(
    grid: list[float], changes: Sequence[float], downbeats: Sequence[float]
) -> list[float]:
    """Bar start times on the beat grid.

    Bars start on the downbeats, and continue at the same number of beats per bar
    before the first and after the last one, and across a missed downbeat; a
    downbeat less than half a bar after the previous one is ignored. Without
    downbeats, a bar is 4 beats, phased so that as many chord changes as possible
    start a bar.
    """
    if len(grid) < 2:
        return list(grid)
    found = sorted({_nearest(grid, t) for t in downbeats})
    if len(found) >= 2:
        per_bar = max(1, round(statistics.median(b - a for a, b in itertools.pairwise(found))))
        marks = [found[0]]
        for m in found[1:]:
            if m - marks[-1] >= per_bar / 2:
                marks.append(m)
        starts = list(range(marks[0] - per_bar, -1, -per_bar))[::-1]
        for a, b in itertools.pairwise(marks):
            missing = round((b - a) / per_bar) - 1
            starts += [a + round(k * (b - a) / (missing + 1)) for k in range(missing + 1)]
        starts += list(range(marks[-1], len(grid), per_bar))
    else:
        on_beat = [_nearest(grid, t) for t in changes]
        phase = max(
            range(BEATS_PER_BAR),
            key=lambda p: (sum(1 for i in on_beat if i % BEATS_PER_BAR == p), -p),
        )
        starts = list(range(phase, len(grid), BEATS_PER_BAR))
    if starts[0] > 0:
        starts.insert(0, 0)  # a pickup bar
    return [grid[i] for i in starts]


def _bar_on_or_after(bars: Sequence[float], t: float) -> float:
    i = bisect.bisect_left(bars, t - _EPS)
    return bars[i] if i < len(bars) else t


def _bar_at(bars: Sequence[float], t: float) -> float:
    """The start of the bar that contains ``t``."""
    i = bisect.bisect_right(bars, t + _EPS) - 1
    return bars[i] if i >= 0 else t


def _chart(segs: Sequence[ChordSegment], bars: Sequence[float], lo: float, hi: float) -> list[str]:
    """Chord-only lines for the bars that start in [lo, hi), four bars per line.

    A bar shows the chord sounding when it starts, then any chord that starts
    within it; a bar where nothing sounds shows N.C. A line repeated right away
    is written once, with a count: ``| G | D | Em | C | x3``.
    """
    cells = []
    for k, start in enumerate(bars):
        if start < lo - _EPS or start >= hi - _EPS:
            continue
        end = min(bars[k + 1], hi) if k + 1 < len(bars) else hi
        names = [s.label for s in segs if s.start <= start + _EPS < s.end]
        for s in segs:
            if start + _EPS < s.start < end - _EPS and (not names or names[-1] != s.label):
                names.append(s.label)
        cells.append(" ".join(f"[ch]{n}[/ch]" for n in names) if names else "[ch]N.C.[/ch]")
    while cells and cells[-1] == "[ch]N.C.[/ch]":
        cells.pop()
    rows = [
        "| " + " | ".join(cells[i : i + BARS_PER_LINE]) + " |"
        for i in range(0, len(cells), BARS_PER_LINE)
    ]
    counted = [(row, len(list(group))) for row, group in itertools.groupby(rows)]
    return [row if n == 1 else f"{row} x{n}" for row, n in counted]


def _chord_line(placed: Sequence[tuple[int, str]]) -> str:
    """A chord line in UG markup, each chord at its column, at least one space apart."""
    visible = 0
    out = ""
    for col, name in placed:
        col = max(col, visible + 1 if visible else 0)
        out += " " * (col - visible) + f"[ch]{name}[/ch]"
        visible = col + len(name)
    return out


# The letters of the scripts written without spaces between words: Chinese characters and kana.
_UNSPACED = re.compile(
    "[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff\U00020000-\U0002ebef]"
)
_APOSTROPHES = "'\u2019"


def _on_words(text: str, placed: Sequence[tuple[int, str]]) -> list[tuple[int, str]]:
    """The chords of a lyric line, each moved to the start of the word nearest its column.

    They keep their order, one a word: a chord whose word start is the previous chord's, or
    under its name, takes the first word start clear of that name and a space, or, with no word
    left, the column right after it, where ``_chord_line`` would lay it out anyway.
    """
    starts = _word_starts(text)
    out: list[tuple[int, str]] = []
    free = 0  # the first column clear of the previous chord's name and a space
    for col, name in placed:
        at = _word_start(text, col)
        if at < free:
            later = bisect.bisect_left(starts, free)
            at = starts[later] if later < len(starts) else free
        out.append((at, name))
        free = at + len(name) + 1
    return out


def _word_start(text: str, col: int) -> int:
    """The column of the word start in ``text`` nearest ``col``; a tie goes to the earlier word.

    A word starts at a letter or digit that doesn't go on the word before it: the line's first, or
    one after a space, punctuation or a quote, so a chord goes on "¿[G]Dónde" and "([G]oh", never
    on the "¿" or the "(". An accent, precomposed or combining, and an apostrophe between two
    letters ("can't", "l'amour") are inside a word. Each Chinese character and kana starts a word,
    as those scripts have no spaces (a long vowel mark, "ー", goes on the kana before it); Hangul,
    written with spaces, has words as Latin letters do. A column at or past the line's end, or in a
    line with no word ("♪"), stays where it is.
    """
    starts = _word_starts(text)
    if not starts or col >= len(text):
        return col
    return starts[_nearest(starts, col)]


def _word_starts(text: str) -> list[int]:
    """The columns where the words of ``text`` start, as ``_word_start`` reads them."""
    starts = []
    for i, c in enumerate(text):
        kind = unicodedata.category(c)
        if _UNSPACED.match(c):
            if kind == "Lo":
                starts.append(i)
            continue
        if kind[0] not in "LN":
            continue
        before = text[i - 1] if i else ""
        if i > 1 and before in _APOSTROPHES:
            before = text[i - 2]  # an apostrophe between two letters joins them
        if not _in_word(before):
            starts.append(i)
    return starts


def _in_word(c: str) -> bool:
    """Whether a letter after ``c`` goes on the word ``c`` is in: a letter, a mark or a digit of a
    script written with spaces."""
    return bool(c) and unicodedata.category(c)[0] in "LMN" and not _UNSPACED.match(c)


def _merge(segs: list[ChordSegment]) -> list[ChordSegment]:
    out: list[ChordSegment] = []
    for s in segs:
        if out and out[-1].label == s.label and s.start <= out[-1].end + _EPS:
            out[-1] = replace(out[-1], end=max(out[-1].end, s.end))
        else:
            out.append(s)
    return out


def _beat_grid(beats: Sequence[float], *, until: float) -> list[float]:
    """The beats, sorted, with missing beats filled in and the grid extended to 0 and ``until``."""
    found = sorted({round(float(b), 3) for b in beats if b >= 0})
    if len(found) < 2:
        return found
    period = statistics.median(b - a for a, b in itertools.pairwise(found))
    grid = [found[0]]
    for b in found[1:]:
        base = grid[-1]
        if b - base < period / 2:
            continue  # the same beat detected twice
        missing = round((b - base) / period) - 1
        step = (b - base) / (missing + 1)
        grid.extend(round(base + step * k, 3) for k in range(1, missing + 1))
        grid.append(b)
    head = []
    t = grid[0] - period
    while t > -period / 2:
        head.append(round(max(t, 0.0), 3))
        t -= period
    tail = []
    t = grid[-1] + period
    while t < until + period / 2:
        tail.append(round(t, 3))
        t += period
    return head[::-1] + grid + tail


def _nearest(grid: Sequence[float], t: float) -> int:
    """Index of the grid time nearest to ``t``; a tie goes to the earlier one."""
    i = bisect.bisect_left(grid, t)
    if i == 0:
        return 0
    if i == len(grid):
        return len(grid) - 1
    return i if grid[i] - t < t - grid[i - 1] else i - 1
