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


@dataclass(frozen=True)
class ChordSegment:
    """A chord sounding from ``start`` to ``end`` seconds. The label "N" means no chord."""

    start: float
    end: float
    label: str


def parse_lrc(text: str) -> list[tuple[float, str]]:
    """The timed lines of an LRC file, sorted by time.

    Reads ``[mm:ss.xx]``, ``[mm:ss.xxx]``, ``[mm:ss:xx]`` and ``[mm:ss]`` stamps,
    several stamps on one line, and enhanced-LRC word stamps (dropped). Metadata
    tags such as ``[ar:…]`` and ``[ti:…]`` are ignored, except ``[offset:±ms]``:
    a positive offset makes every line appear earlier. A stamp with no text is
    kept as ``""``, because LRC files mark instrumental breaks that way.
    """
    offset = 0.0
    timed: list[tuple[float, str]] = []
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
        lyric = " ".join(_WORD_STAMP.sub("", line[stamps.end() :]).split())
        for m in _STAMP.finditer(stamps.group()):
            minutes, seconds, fraction = m.groups()
            t = int(minutes) * 60 + int(seconds) + (float(f"0.{fraction}") if fraction else 0.0)
            timed.append((t, lyric))
    return sorted(((round(max(0.0, t - offset), 3), s) for t, s in timed), key=lambda x: x[0])


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


def youtube_credit(title: str, channel: str, video_id: str) -> str:
    """The line after the song's name (``build_sheet``'s ``source``) of a sheet made from a YouTube video's audio,
    as its .txt, its .cho and its PDF say it: the video by its title, else its id, and its channel ("Audio from
    YouTube: Creep (Radiohead - Topic)"), on one line. Its address isn't there: info.json names it, and the sheet's
    viewer draws its title as a link to it (render.py gives it the video)."""
    named = " ".join((title or video_id).split())
    channel = " ".join(channel.split())
    return f"Audio from YouTube: {named} ({channel})" if channel else f"Audio from YouTube: {named}"


def build_sheet(
    segments: Iterable[ChordSegment],
    *,
    title: str,
    artist: str,
    synced: str | None = None,
    plain: str | None = None,
    beats: Sequence[float] | None = None,
    downbeats: Sequence[float] | None = None,
    source: str | None = None,
) -> str:
    """The text of ``sheet (auto).txt``. ``source``, when given, is a line after the song's
    name that says where its audio came from (a YouTube video: ``youtube_credit``), which render.py
    reads as the sheet's credit, apart from its song.

    With synced lyrics (LRC), every lyric line gets the chords whose snapped start
    falls between its time and the next line's, at character columns proportional
    to their time within the line. A change up to half a beat before a line's
    time counts as the start of that line, since singers often come in just
    after the downbeat. Where the voice rests for at least two bars, the chords
    go on chord-only lines of bars instead, such as ``| G | D | Em | C |``.

    With plain lyrics only, the sheet is a chord chart of the whole song, four
    bars per line, followed by the lyrics. With no lyrics, it is the chart alone.
    """
    segs = snap_to_beats(segments, beats or [])
    lines = parse_lrc(synced) if synced else []
    until = max([s.end for s in segs] + [t for t, _ in lines] + [0.0])
    grid = _beat_grid(beats or [], until=until)
    beat = _period(grid) or DEFAULT_BEAT
    bars = _bar_starts(grid, [s.start for s in segs], downbeats or [])
    bar = _period(bars) or BEATS_PER_BAR * beat
    out = [AUTO_MARKER, f"{artist} - {title}", *([source.strip()] if source and source.strip() else []), ""]
    if any(text for _, text in lines):
        out += _synced_body(segs, lines, tol=beat / 2, bars=bars, bar=bar)
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
) -> list[str]:
    # Each sung line, with the time of the LRC entry after it and whether that
    # entry is empty, which is how LRC files mark a break.
    sung: list[tuple[float, str, float | None, bool]] = []
    for j, (t, text) in enumerate(lines):
        if text:
            after = lines[j + 1] if j + 1 < len(lines) else None
            sung.append((t, text, after[0] if after else None, after is not None and not after[1]))
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
        placed = [
            (max(0, int((s.start - t) / span * len(text))), s.label)
            for s in segs
            if t - tol <= s.start < end - tol
        ]
        if block_start and not (placed and placed[0][0] == 0):
            # The first line of a block names the chord already ringing when it starts.
            ringing = [s.label for s in segs if s.start < t - tol < s.end]
            if ringing:
                placed.insert(0, (0, ringing[-1]))
        if placed:
            out.append(_chord_line(placed))
        out.append(text)
        block_start = bool(chart) or (rest and nxt is not None)
        if chart:
            out += ["", "[Outro]" if nxt is None else "[Instrumental]", *chart, ""]
        elif block_start:
            out.append("")
    return out


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
