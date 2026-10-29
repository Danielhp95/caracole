"""Where LRCLIB's timed lyrics sit in audio of another length: how far to shift them, if it's clear.

LRCLIB times its lyrics against one release of a song. Audio of another length (a YouTube video
with a spoken intro, credits after the song, a longer fade, a cut intro) holds the same song moved
in time, and run.py lays the chords over the timed lyrics only where they fit it. When the lengths
differ by more than run.py's tolerance, ``lyrics_offset`` works out that move from what the models
gave, the chords and the beats, and nothing else: no other model, no request. It scores candidate
shifts and takes the best only when it wins clearly; otherwise there is none, and the sheet is a
chord chart above the plain lyrics, as before. ``shifted_lrc`` moves them, word stamps and all.

A shift ``o`` moves an LRC time ``t`` to ``t + o``. The candidates are no shift; ``d``, the audio's
length less the lyrics' (the audio's extra time all at its start), and a bar either side of it;
and every quarter beat within ``MAX_SHIFT`` (30 s) either way. Each scores the mean of three
measures of the lines it moves, weighed by ``WEIGHTS``, less a cost, plus a prior:

- **onsets**: each sung line starts on a bar (beat_this's downbeats) and on a chord change: full
  marks for each, falling to none a beat away; the mean over the lines;
- **coverage**: the share of each line's time some chord sounds, rather than none (talk, silence,
  past the end of the audio); the mean over the lines;
- **repeats**: a line sung again with the same words (a chorus) is sung over the same chords: the
  share of half beats whose chords agree (by root, major or minor), the mean over such pairs; a
  song with no line sung twice has no such term;
- **extent**, a cost: the audio's music, from its first steady chords to its last, fits within the
  lyrics' length once shifted, where it can. Each second it overhangs beyond what it must, past a
  bar's slack, costs ``EXTENT_COST`` a bar: a talk intro that BTC hears as no chord leaves the
  lyrics no room but after it. Audio with more music than the lyrics' length (a longer intro or
  outro of music) makes every shift within its overhang as good as another;
- **prior**: ``PRIOR`` for a shift within a beat of 0 or ``d``, falling to nothing two beats away.
  Audio of another length is most often the same recording with something more at one end, and
  nothing above tells one bar from the next in a song whose chords change every bar: this does.

The best is taken when it beats every candidate more than a beat away from it by ``MARGIN``, and
its lines land on bars and chord changes (onsets at least ``MIN_ONSETS``) over chords (coverage at
least ``MIN_COVERAGE``). Fewer than ``MIN_LINES`` sung lines, no chords or no beats: no shift.

A shift within a beat of 0 is no shift: such audio has its extra time at its end.

Pure Python, so it runs in the default environment, as merge.py does.
"""

from __future__ import annotations

import bisect
import math
import re
import statistics
from collections.abc import Sequence
from dataclasses import dataclass

from caracole.autochords.merge import (
    _STAMP,
    _STAMP_RUN,
    _WORD_TIME,
    BEATS_PER_BAR,
    ChordSegment,
    _bar_starts,
    _beat_grid,
    _period,
    _seconds,
    snap_to_beats,
)

MAX_SHIFT = 30.0  # seconds either way, for the grid; d and the bar around it are candidates beyond it too
STEPS_PER_BEAT = 4
MIN_LINES = 6
WEIGHTS = {"onsets": 1.0, "coverage": 1.0, "repeats": 0.5}
BAR_SHARE = 0.5  # of a line's onset score: on a bar; the rest, on a chord change
EXTENT_COST = 0.05  # a bar of music overhanging the lyrics' length
PRIOR = 0.1  # within a beat of 0 or d, falling to nothing two beats away
MARGIN = 0.07  # so the prior can outweigh but a little evidence against
MIN_ONSETS = 0.4
MIN_COVERAGE = 0.7
STEADY_BARS = 2  # the music starts with the first chord of a stretch this long that chords fill half of
REPEAT_CHARS = 8  # a line sung again counts when its words are at least this long
REPEATS_PER_LINE = 6  # occurrences of one line compared, at most
_EPS = 1e-6


@dataclass(frozen=True)
class Alignment:
    """What ``lyrics_offset`` found. ``offset``: the seconds to add to every LRC time (0.0 for none
    needed), or None when no shift fits clearly; the rest says why, for the log."""

    offset: float | None
    why: str
    best: float | None = None
    score: float | None = None
    runner_up: float | None = None


@dataclass(frozen=True)
class _Line:
    start: float
    end: float
    key: str  # its words, folded, for repeats


@dataclass(frozen=True)
class _Fit:
    offset: float
    score: float
    onsets: float
    coverage: float


class _Audio:
    """The chords and bars of the audio, to look times up in."""

    def __init__(self, segments: Sequence[ChordSegment], beats: Sequence[float],
                 downbeats: Sequence[float], until: float):
        self.segs = snap_to_beats(segments, beats)
        self.starts = [s.start for s in self.segs]
        grid = _beat_grid(beats, until=until)
        self.beat = _period(grid) or 0.0
        self.bars = _bar_starts(grid, self.starts, downbeats)
        self.bar = _period(self.bars) or BEATS_PER_BAR * self.beat
        self.changes = sorted(set(self.starts))

    def chord_at(self, t: float) -> str | None:
        i = bisect.bisect_right(self.starts, t) - 1
        return self.segs[i].label if i >= 0 and self.segs[i].end > t else None

    def sounding(self, a: float, b: float) -> float:
        """Seconds of [a, b) during which some chord sounds."""
        i = max(bisect.bisect_right(self.starts, a) - 1, 0)
        total = 0.0
        while i < len(self.segs) and self.segs[i].start < b:
            total += max(0.0, min(b, self.segs[i].end) - max(a, self.segs[i].start))
            i += 1
        return total

    def music(self) -> tuple[float, float]:
        """Where the music starts and ends: the first and last chords of steady stretches."""
        window = STEADY_BARS * self.bar
        start = next((s.start for s in self.segs if self.sounding(s.start, s.start + window) >= window / 2),
                     self.segs[0].start)
        end = next((s.end for s in reversed(self.segs) if self.sounding(s.end - window, s.end) >= window / 2),
                   self.segs[-1].end)
        return start, end


def lyrics_offset(
    lines: Sequence[tuple[float, str]],
    segments: Sequence[ChordSegment],
    beats: Sequence[float],
    downbeats: Sequence[float],
    *,
    audio_s: float,
    lyrics_s: float,
) -> Alignment:
    """How far to shift the timed ``lines`` (``merge.parse_lrc``'s) to fit the audio the models
    heard as ``segments``, ``beats`` and ``downbeats``, ``audio_s`` long, when LRCLIB timed them
    against a release ``lyrics_s`` long. See the module's docstring."""
    sung = _sung(lines)
    if len(sung) < MIN_LINES:
        return Alignment(None, f"{len(sung)} sung lines, too few to place")
    audio = _Audio(segments, beats, downbeats, until=max([audio_s] + [s.end for s in segments]))
    if not audio.segs or audio.beat <= 0 or len(audio.bars) < 2:
        return Alignment(None, "no chords or no beats to place the lines by")
    d = audio_s - lyrics_s
    pairs = _repeated(sung)
    music = audio.music()
    least = max(0.0, music[1] - music[0] - lyrics_s)  # the overhang no shift avoids: more music than lyrics
    fits = [_fit(o, sung, pairs, audio, d=d, music=music, lyrics_s=lyrics_s, least=least)
            for o in _candidates(d, audio.beat, audio.bar)]
    best = max(fits, key=lambda f: (f.score, -abs(f.offset)))
    others = [f.score for f in fits if abs(f.offset - best.offset) > audio.beat + _EPS]
    runner_up = max(others, default=-math.inf)
    found = {"best": round(best.offset, 3), "score": round(best.score, 3), "runner_up": round(runner_up, 3)}
    if best.onsets < MIN_ONSETS:
        return Alignment(None, f"the lines land on no bars or chord changes (onsets {best.onsets:.2f})", **found)
    if best.coverage < MIN_COVERAGE:
        return Alignment(None, f"the lines land where no chord sounds (coverage {best.coverage:.2f})", **found)
    if best.score - runner_up < MARGIN:
        return Alignment(None, f"no clear winner ({best.score:.3f} at {best.offset:+.2f} s, "
                               f"{runner_up:.3f} a beat or more away)", **found)
    offset = 0.0 if abs(best.offset) <= audio.beat + _EPS else round(best.offset, 3)
    return Alignment(offset, f"{best.score:.3f} at {best.offset:+.2f} s, {runner_up:.3f} a beat or more away",
                     **found)


def shifted_lrc(text: str, offset: float) -> str:
    """The LRC ``text`` with every stamp moved by ``offset`` seconds, a line's and each word's
    (enhanced LRC) alike, so that ``merge.parse_lrc_words`` still finds each word where it is
    sung; the rest as written, an ``[offset:]`` tag too. A time moved before the start is
    dropped, and its line with it once it has no other, as the audio hasn't got it; a word
    stamp so moved starts at 0."""
    out = []
    for raw in text.lstrip("﻿").splitlines():
        line = raw.strip()
        stamps = _STAMP_RUN.match(line)
        if stamps is None:
            out.append(raw)
            continue
        times = [round(_seconds(*m.groups()) + offset, 3) for m in _STAMP.finditer(stamps.group())]
        if all(at < 0 for at in times):
            continue
        words = _WORD_TIME.sub(lambda m: _stamp(_seconds(*m.groups()) + offset, "<>"), line[stamps.end() :])
        out.append("".join(_stamp(at, "[]") for at in times if at >= 0) + words)
    return "\n".join(out) + "\n"


def _stamp(t: float, brackets: str) -> str:
    """An LRC stamp of ``t`` seconds (0 for before the start), ``[mm:ss.xxx]`` or ``<mm:ss.xxx>``."""
    minutes, seconds = divmod(max(0.0, round(t, 3)), 60)
    return f"{brackets[0]}{int(minutes):02d}:{seconds:06.3f}{brackets[1]}"


def _sung(lines: Sequence[tuple[float, str]]) -> list[_Line]:
    """The sung lines, each until the next LRC entry or a typical line's length, whichever is first."""
    timed = sorted(lines, key=lambda x: x[0])
    nexts = {j: timed[j + 1][0] for j in range(len(timed) - 1)}
    windows = [nexts[j] - t for j, (t, text) in enumerate(timed) if text and j in nexts and nexts[j] > t]
    typical = statistics.median(windows) if windows else 0.0
    out = []
    for j, (t, text) in enumerate(timed):
        if not text:
            continue
        end = min(nexts.get(j, math.inf), t + typical)
        if end > t:
            out.append(_Line(t, end, " ".join(re.findall(r"\w+", text.casefold()))))
    return out


def _repeated(sung: list[_Line]) -> list[tuple[_Line, _Line]]:
    """Pairs of lines sung with the same words, long enough to count."""
    groups: dict[str, list[_Line]] = {}
    for line in sung:
        if len(line.key) >= REPEAT_CHARS:
            groups.setdefault(line.key, []).append(line)
    return [(a, b) for group in groups.values() for i, a in enumerate(group[:REPEATS_PER_LINE])
            for b in group[i + 1 : REPEATS_PER_LINE]]


def _candidates(d: float, beat: float, bar: float) -> list[float]:
    step = beat / STEPS_PER_BEAT
    reach = int(MAX_SHIFT / step)
    near_d = int(bar / step) + 1
    found = {round(k * step, 3) for k in range(-reach, reach + 1)}
    found |= {round(d + k * step, 3) for k in range(-near_d, near_d + 1)}
    return sorted(found | {0.0, round(d, 3)})


def _overhang(o: float, music: tuple[float, float], lyrics_s: float) -> float:
    """Seconds of the audio's music outside the lyrics' length, once shifted by ``o``."""
    start, end = music
    return max(0.0, o - start) + max(0.0, end - lyrics_s - o)


def _closeness(points: Sequence[float], t: float, width: float) -> float:
    i = bisect.bisect_left(points, t)
    near = min((abs(points[k] - t) for k in (i - 1, i) if 0 <= k < len(points)), default=math.inf)
    return max(0.0, 1.0 - near / width)


def _family(label: str | None) -> str | None:
    """A chord by its root, major or minor: BTC hears D and D7 in the same bar of two choruses."""
    if label is None:
        return None
    root = label[:2] if label[1:2] in ("#", "b") else label[:1]
    rest = label[len(root):]
    return root + ("m" if rest.startswith(("m", "dim")) and not rest.startswith("maj") else "")


def _fit(o: float, sung: list[_Line], pairs: list[tuple[_Line, _Line]], audio: _Audio, *, d: float,
         music: tuple[float, float], lyrics_s: float, least: float) -> _Fit:
    beat, bar = audio.beat, audio.bar
    onsets = statistics.fmean(
        BAR_SHARE * _closeness(audio.bars, x.start + o, beat)
        + (1 - BAR_SHARE) * _closeness(audio.changes, x.start + o, beat)
        for x in sung
    )
    coverage = statistics.fmean(audio.sounding(x.start + o, x.end + o) / (x.end - x.start) for x in sung)
    measures = {"onsets": onsets, "coverage": coverage}
    if pairs:
        measures["repeats"] = statistics.fmean(_agreement(a, b, o, audio) for a, b in pairs)
    evidence = sum(WEIGHTS[k] * v for k, v in measures.items()) / sum(WEIGHTS[k] for k in measures)
    overhang = max(0.0, _overhang(o, music, lyrics_s) - least - bar)
    prior = PRIOR * min(1.0, max(0.0, 2.0 - min(abs(o), abs(o - d)) / beat))
    return _Fit(o, evidence - EXTENT_COST * overhang / bar + prior, onsets, coverage)


def _agreement(a: _Line, b: _Line, o: float, audio: _Audio) -> float:
    """The share of half beats over which two lines sung with the same words have the same chords."""
    step = audio.beat / 2
    n = max(1, int(min(a.end - a.start, b.end - b.start) / step))
    same = 0
    for k in range(n):
        x = (k + 0.5) * step + o
        one = _family(audio.chord_at(a.start + x))
        same += one is not None and one == _family(audio.chord_at(b.start + x))
    return same / n
