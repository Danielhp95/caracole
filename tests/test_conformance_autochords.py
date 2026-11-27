"""The conformance corpus's auto-chords half that needs no model: btc.py's labels, for the phone's ``Labels``
(android/autochords, the design's §3.7; .claude/handoff/synchunt-2026-11-25/android-autochords-design.md).

It runs in the default shell: btc.py's label helpers import no NumPy, librosa or torch. Regenerated with the rest of
the corpus, ``CARACOLE_CORPUS=write nix develop -c pytest -q -n 0 tests/test_conformance_autochords.py``.

What it writes:

- ``data/caracole/autochords/labels.json``: btc.py's tables (``labels_json``): its roots, each vocabulary's qualities
  (a "maj" written as the bare root) and what ends it, the common names, the flats a flat key writes, the major scale,
  the flat keys, C major's spelling, and the frame's length. ``vocabulary`` is checked to be what they make.
- ``vectors/autochords/labels.jsonl``: a ``meta`` record (``FRAME_SECONDS``), then:
  - ``vocabulary``: the names of each size btc.py knows, and its ValueError for sizes it doesn't;
  - ``common_name``: ``[label, name]`` pairs: test_autochords_models.py's ``COMMON_NAMES``, every label of both
    vocabularies, those labels spelled with flats, and labels no vocabulary has (a bass, an unknown quality, none);
  - ``spell``: segments (``[start, end, label]``) and the labels ``spell_for_key`` gives them: test_autochords_models.py's
    ``SPELLINGS`` and seeded songs (ties between keys, labels already flat, "N" and "X" alone, none at all);
  - ``frames``: predictions, a frame's length and a vocabulary's size, and the segments ``frames_to_segments`` makes
    (``[start, end, label]``, each time Python's ``round(…, 3)``): test_autochords_models.py's ``FRAMES``, seeded
    runs at ``FRAME_SECONDS``, and a class a frame at ``TIE_FRAME_SECONDS``, where round's half to even on the exact
    value shows;
  - ``round``: ``round(k * FRAME_SECONDS, 3)`` for every k of a range (``from``, ``to``, ``step``), the segments'
    times over the first 3,000 frames one by one and over four hours sparsely.

And, for the phone's ``viewer.autochords`` (merge.py and align.py, area ``autochords-sheet``):

- ``data/caracole/viewer/autochords.json`` (``autochords_json``): merge.py's constants and patterns (``merge``) and
  align.py's (``align``), under their Python names (a leading underscore dropped), read by ``viewer.autochords``.

Each vector record a call of
the real function (``fn``, its ``args`` or ``kw``) and its whole answer (``out``), or what it raised (``err``, the
exception's class name):

- ``vectors/autochords-sheet/merge.jsonl``: every call test_autochords_merge.py makes of ``build_sheet``,
  ``snap_to_beats``, ``parse_lrc``, ``parse_lrc_words``, ``youtube_credit``, ``_beat_grid``, ``_word_start``,
  ``_on_words`` and ``_chord_line`` (each recorded as its test runs it); ``parse_lrc_words`` (``[time, text, words]``
  a line, ``words`` ``[[time, column], …]`` or null) over every string literal of ``MERGE_LITERALS`` and
  ``ALIGN_LITERALS`` and ``LRC_EDGES``; ``_word_start`` at every column of each literal of one line, and
  ``_on_words`` and ``_chord_line`` over seeded chords on them (``ASTRAL_LINES`` among them: characters past the BMP
  and combining marks, also as LRC with and without word stamps); ``_beat_grid``, ``_bar_starts`` and
  ``build_sheet`` where round()'s half to even decides (``_tie_records``); ``build_sheet`` over seeded hearings
  (``_seeded_hearings``: segments, beats with gaps, doubles and jitter, downbeats in 4/4, in 3/4, missed, spurious or
  none) and lyrics of each kind (none, plain, timed by line, timed by word, CJK, a break, a long line, a source of one
  line or several), and over the literals as synced and plain lyrics; ``with_plain_lyrics`` over sheets of no lyrics
  and the literals.
- ``vectors/autochords-sheet/align.jsonl``: every call test_autochords_align.py makes of ``lyrics_offset`` and
  ``shifted_lrc``, and ``lyrics_offset`` over seeded songs heard with something more at one end (or cut, or another
  song's lines), each with its candidates' scores to the bit (``fits``, ``_fits``); ``shifted_lrc`` over the
  literals, ``LRC_EDGES`` and ``STAMP_EDGES`` (minutes past a Long) at several offsets; ``math.fsum``. An ``Alignment`` is its
  fields, a float that is no number written as the string Python's ``repr`` writes (``"-inf"``).

A list of beats ``[s + k * step for k in range(n)]`` is written ``{"start": s, "step": step, "n": n}`` (where Python's
list is exactly that), a sheet past ``WHOLE_MOST`` characters by ``{"sha256": first 16 hex digits, "size": len}``,
and ``synced_words`` that are ``parse_lrc_words(synced)`` as ``true``.
"""

from __future__ import annotations

import hashlib
import json
import math
import random
import struct
import types
from contextlib import contextmanager

import test_autochords_align
import test_autochords_merge
from helpers.corpus import DATA, VECTORS, check, jsonl
from test_autochords_models import COMMON_NAMES, FRAMES, SPELLINGS, spelling_song
from test_conformance_viewer_sheet import literals

from caracole.autochords import ChordSegment, align, btc, merge

MADE_BY = "tests/test_conformance_autochords.py"
AREA = VECTORS / "autochords"
SIZES = (25, 170)
NOT_SIZES = (0, 24, 26, 169, 171)
# Labels no BTC vocabulary has, which common_name still names as btc.py does.
OTHER_LABELS = ("C:min/b3", "G/5", "C:weird", "", ":min", "Cb", "E#:maj", "N:min", "X:7", "Bb:min7/7")
# Frame lengths for the frames records: at the first three Python's round(…, 3) and a naive half-up rounding of the
# decimal shown disagree at some of the 25 frames' times (round's half to even on the exact binary value); at 2.0005,
# a control, they never do.
TIE_FRAME_SECONDS = (1.0005, 0.0015, 0.0025, 2.0005)
ROUNDED = ((0, 3000, 1), (3000, 155520, 149))  # four hours of frames at 10/108 s, sparsely past the first 3,000


def _vocabulary_tables() -> dict:
    qualities = {"25": ["maj", "min"], "170": list(btc._QUALITIES)}
    tails = {"25": [btc.NO_CHORD], "170": ["X", btc.NO_CHORD]}
    for n in SIZES:
        made = [r if q == "maj" else f"{r}:{q}" for r in btc.ROOTS for q in qualities[str(n)]] + tails[str(n)]
        assert made == btc.vocabulary(n), n
    return {"qualities": qualities, "tails": tails}


def labels_json() -> str:
    """labels.json: what Labels reads, every value btc.py's own."""
    doc = {
        "roots": list(btc.ROOTS),
        "vocabularies": _vocabulary_tables(),
        "common": dict(btc._COMMON),
        "flats": dict(btc._FLATS),
        "major_scale": list(btc._MAJOR_SCALE),
        "flat_keys": sorted(btc._FLAT_KEYS),
        "c_major_spelling": dict(btc._C_MAJOR_SPELLING),
        "no_chord": btc.NO_CHORD,
        "unknown": "X",
        "frame": {"chunk_seconds": btc.CHUNK_SECONDS, "timestep": btc.TIMESTEP, "seconds": btc.FRAME_SECONDS},
    }
    return json.dumps(doc, ensure_ascii=False, sort_keys=True, indent=1) + "\n"


def _segments(segs) -> list[list]:
    return [[s.start, s.end, s.label] for s in segs]


def _seeded_songs() -> list[list[ChordSegment]]:
    names = btc.vocabulary(170)
    flat = ["Bb", "Eb:min", "Ab:7", "Db", "Gb:maj7"]
    rng = random.Random(8)
    songs = []
    for n in (1, 2, 5, 12, 40, 120):
        t, song = 0.0, []
        for _ in range(n):
            d = round(rng.choice((0.0, 0.093, 0.5, 1.204, 2.315, 4.0)) * rng.randint(1, 3), 3)
            song.append(ChordSegment(t, round(t + d, 3), rng.choice(names + flat)))
            t = round(t + d, 3)
        songs.append(song)
    two = ChordSegment
    songs += [
        [],
        [two(0.0, 3.0, "N"), two(3.0, 5.0, "X")],
        [two(0.0, 0.0, "C#"), two(0.0, 0.0, "A#:min")],  # no time at all: unchanged
        [two(0.0, 1.0, "C"), two(1.0, 2.0, "F#")],  # C and G major tie with F major and others: the first fit wins
        [two(0.0, 1.0, "A#"), two(1.0, 2.0, "D#:7"), two(2.0, 3.0, "G#")],
        [two(0.0, 1.0, "Bb"), two(1.0, 2.0, "A#:min")],
        [two(0.0, 0.1, "C"), two(0.1, 0.2, "C"), two(0.2, 0.30000000000000004, "D#")],
    ]
    return songs


def _seeded_frames() -> list[list[int]]:
    rng = random.Random(108)
    out = [[], [7], [169, 169], list(range(170)) * 3]
    for frames, longest in ((300, 1), (3000, 40), (5000, 300)):
        p: list[int] = []
        while len(p) < frames:
            p += [rng.randrange(170)] * rng.randint(1, longest)
        out.append(p[:frames])
    return out


def labels_records() -> list[dict]:
    records: list[dict] = [{"kind": "meta", "frame_seconds": btc.FRAME_SECONDS}]
    for n in SIZES:
        records.append({"kind": "vocabulary", "n": n, "names": btc.vocabulary(n)})
    for n in NOT_SIZES:
        try:
            btc.vocabulary(n)
        except ValueError as e:
            records.append({"kind": "vocabulary", "n": n, "error": str(e)})
        else:
            raise AssertionError(n)

    labels = list(COMMON_NAMES) + btc.vocabulary(170) + btc.vocabulary(25)
    labels += [btc._FLATS.get(lab.partition(":")[0], "") + lab[2:] for lab in btc.vocabulary(170) if lab[1:2] == "#"]
    labels += list(OTHER_LABELS)
    records.append({"kind": "common_name", "pairs": [[lab, btc.common_name(lab)] for lab in labels]})

    for labs, _ in SPELLINGS:
        song = spelling_song(labs)
        records.append({"kind": "spell", "segments": _segments(song), "spelled": [s.label for s in btc.spell_for_key(song)]})
    for song in _seeded_songs():
        records.append({"kind": "spell", "segments": _segments(song), "spelled": [s.label for s in btc.spell_for_key(song)]})

    cases = [(FRAMES[0], FRAMES[1], 25)] + [(p, btc.FRAME_SECONDS, 170) for p in _seeded_frames()]
    # A class a frame at frame lengths whose times round otherwise half to even on the exact value than half up on
    # the decimal (k · 1.0005 at k = 1, 7, 11…; k · 0.0015 at 5, 9, 13…), which 10/108 s never shows.
    cases += [(list(range(25)), seconds, 25) for seconds in TIE_FRAME_SECONDS]
    for predictions, seconds, n in cases:
        segs = btc.frames_to_segments(predictions, seconds, btc.vocabulary(n))
        records.append({"kind": "frames", "predictions": list(predictions), "frame_seconds": seconds, "vocabulary": n,
                        "segments": _segments(segs)})

    for start, stop, step in ROUNDED:
        records.append({"kind": "round", "from": start, "to": stop, "step": step,
                        "seconds": [round(k * btc.FRAME_SECONDS, 3) for k in range(start, stop, step)]})
    return records


def test_labels_json():
    check(DATA / "autochords" / "labels.json", labels_json())


def test_labels_vectors():
    check(AREA / "labels.jsonl", jsonl(labels_records(), corpus="autochords/labels", made_by=MADE_BY))


# --- merge.py and align.py: viewer.autochords (area autochords-sheet) ------------------------------------------------

SHEET_AREA = VECTORS / "autochords-sheet"
MERGE_LITERALS = ("test_autochords_merge.py",)
ALIGN_LITERALS = ("test_autochords_align.py",)
WHOLE_MOST = 1500  # a sheet longer than this is written by its digest
CALLS_A_TEST = 12
# LRC as LRCLIB, Megalobiz and hands write it, and as nobody should: what parse_lrc_words and shifted_lrc read of each.
LRC_EDGES = (
    "",
    "﻿﻿[00:01.00]two marks\n",
    "[00:01.00]x\r\n[00:02.50]y\r[00:03]z [00:04.5]w\x85[00:05:25]v\n",
    "  [00:01.00]  spaced  out  \n\t[00:02.00]\ttabbed\t\n",
    "[00:01.00][00:03.00] [00:05.00]  three times\n",
    "[03:45.00]\n[00:10.00]last stamp empty, first in time\n",
    "[00:61.00]a minute's worth of seconds\n[100:05.5]a long song\n[0:5]short\n[00:05.123456]fine\n",
    "[00:1x]not a stamp\n[00:05.]no fraction\n[:05.00]no minute\n[00:005.00]three digits\n",
    "[٠٠:١٢.٥٠]Arabic-Indic digits\n[００:１２]full-width digits\n",
    "[00:१२.३]Devanagari seconds\n<00:01.00>a word stamp first\n",
    "[offset:+5_00]\n[00:10.00]underscored offset\n",
    "[offset: -250 ]\n[00:10.00]spaced offset\n",
    "[OFFSET:100]\n[00:10.00]capital offset\n[offset:abc]\n[00:11.00]unread offset\n",
    "[offset:9999999999999999999999]\n[00:10.00]far offset\n",
    "[offset:" + "9" * 5000 + "]\n[00:10.00]an offset past int()'s digits is ignored\n",
    "[offset:+1000]\n[00:00.50]moved before the start\n[00:01.50]<00:00.20>Word <00:01.70>two\n",
    "[ar:Someone]\n[ti:A Title]\n[length: 03:12]\n[by:x]\n[#:comment]\n[00:01.00]tags\n",
    "[00:01.00]<00:01.00>Hel<00:01.40>lo  <00:02.00>world <00:02.80>\n",
    "[00:01.00]<00:01.00><00:01.20>two stamps <00:01.50> <00:01.60>then\n",
    "[00:01.00]words <0:1.5>bad stamp <00:01.70\n",
    "[00:01.00]<00:01:50>colon <00:02.5>short <01:02.250>long\n",
    "[00:01.00]宋<00:01.30>冬<00:01.60>野  　全角\n",
    "[00:01.00]   \n[00:02.00]　\n",
    "[00:01.00]a non breaking　space\n",
    "[00:00.00]\n[00:00.00]same time\n[00:00.00]again\n",
)
# Characters past the BMP (CJK Extension B, emoji and a ZWJ sequence, mathematical letters and digits) and combining
# marks: every column, length and slice above is in code points, never UTF-16 units.
ASTRAL_LINES = (
    "\u7b2c\U00020000\U00020001\u4e00\u884c\U00020002\u6b4c",
    "I love \U0001f600 you \U0001f469\u200d\U0001f469\u200d\U0001f467 so much",
    "corazo\u0301n esta\u0301 aqui\u0301 ya",
    "\U0001d401\U0001d428\U0001d425\U0001d41d math letters \U0001d7cf\U0001d7d0",
    "\U0001f600\U0001f600 x \U0001f600",
    "(\U00020000\u6211) \U0001f600love\U00020001",
)


def _word_stamped(text: str, start: float) -> str:
    """``text`` with a word stamp before each word (each character, in a line of no space)."""
    parts = text.split(" ") if " " in text else list(text)
    joiner = " " if " " in text else ""
    return joiner.join(f"<00:{start + 0.4 * k:05.2f}>{part}" for k, part in enumerate(parts))


LRC_EDGES += tuple(f"[00:01.00]{line}\n[00:05.00]{_word_stamped(line, 5.0)}\n[00:09.00]{line}\n"
                   for line in ASTRAL_LINES)
LRC_EDGES += ("[\U0001d7ce\U0001d7ce:\U0001d7cf\U0001d7d0.\U0001d7d3\U0001d7ce]mathematical digits\n",)
# Stamps far past an hour: parsed and shifted, never laid out (a sheet of 10**20 minutes has no end).
STAMP_EDGES = ("[100000000000000000000:00]x\n", "[99999999999999999999:59.999]<99999999999999999999:59.999>y\n")
LRC_RAISING = (
    "[0" + "9" * 5000 + ":01.00]a minute past int()'s digits\n",
    "[" + "9" * 400 + ":01.00]a minute past a float\n",
    "[offset:" + "9" * 400 + "]\n[00:01.00]an offset past a float\n",
)
SHIFTS = (12.0, -2.0, 0.0005)
LABELS = ("G", "D", "Em", "C", "Am7", "F#m", "Bb", "Cmaj7", "E7", "Dsus4", "C/E", "Abm", "N", "N")
WORDS = ("walking", "down", "the", "river", "road", "singing", "to", "morning", "light", "¿dónde",
         "estás?", "can't", "(oh)", "l'amour", "“hey,”", "yeah!", "corazón", "♪")
ASTRAL_WORDS = ("\U0001f600", "\U0001f469\u200d\U0001f469\u200d\U0001f467", "\U00020000\U00020001",
                "\U0001d401\U0001d428\U0001d425\U0001d41d", "corazo\u0301n", "e\u0301\u0301te\u0301")
CJK = "第一行歌词在这里我你，再见君の名はラーメン사랑해요"


def autochords_json() -> str:
    """autochords.json: what viewer.autochords reads, every value merge.py's or align.py's own."""
    from helpers.viewer_corpus import data_json

    m, a = merge, align
    return data_json({
        "merge": {
            "NO_CHORD": m.NO_CHORD, "AUTO_MARKER": m.AUTO_MARKER, "DEFAULT_BEAT": m.DEFAULT_BEAT,
            "BEATS_PER_BAR": m.BEATS_PER_BAR, "BARS_PER_LINE": m.BARS_PER_LINE, "GAP_BARS": m.GAP_BARS,
            "EPS": m._EPS, "STAMP_RUN": m._STAMP_RUN.pattern, "STAMP": m._STAMP.pattern, "TAG": m._TAG.pattern,
            "WORD_TIME": m._WORD_TIME.pattern, "WORD_PIECE": m._WORD_PIECE.pattern, "UNSPACED": m._UNSPACED.pattern,
            "APOSTROPHES": m._APOSTROPHES, "NO_CHORD_CELL": m._NO_CHORD_CELL,
        },
        "align": {
            "MAX_SHIFT": a.MAX_SHIFT, "STEPS_PER_BEAT": a.STEPS_PER_BEAT, "MIN_LINES": a.MIN_LINES,
            "WEIGHTS": a.WEIGHTS, "BAR_SHARE": a.BAR_SHARE, "EXTENT_COST": a.EXTENT_COST, "PRIOR": a.PRIOR,
            "MARGIN": a.MARGIN, "MIN_ONSETS": a.MIN_ONSETS, "MIN_COVERAGE": a.MIN_COVERAGE,
            "STEADY_BARS": a.STEADY_BARS, "REPEAT_CHARS": a.REPEAT_CHARS, "REPEATS_PER_LINE": a.REPEATS_PER_LINE,
            "EPS": a._EPS, "WORD": a._WORD.pattern,
        },
    })


def _number(x):
    """A float as JSON holds it; one that is no number as the string ``repr`` writes."""
    return x if x is None or math.isfinite(x) else repr(x)


def _series(xs):
    """A list of times, or the series it exactly is."""
    xs = [float(x) for x in xs]
    if len(xs) >= 3:
        start, step = xs[0], xs[1] - xs[0]
        if all(x == start + k * step for k, x in enumerate(xs)):
            return {"start": start, "step": step, "n": len(xs)}
    return xs


def _segs(segs):
    return [[float(s.start), float(s.end), s.label] for s in segs]


def _lrc_lines(lines):
    return [[line.time, line.text, [list(w) for w in line.words] if line.words is not None else None]
            for line in lines]


def _text(text: str):
    if len(text) <= WHOLE_MOST:
        return text
    return {"sha256": hashlib.sha256(text.encode("utf-8")).hexdigest()[:16], "size": len(text)}


def _err(e: Exception) -> str:
    return type(e).__name__


def _floats(xs):
    return [float(x) for x in xs] if xs is not None else None


def _sheet_record(segments, *, title, artist, synced=None, synced_words=None, plain=None, beats=None,
                  downbeats=None, source=None) -> dict:
    segments = [ChordSegment(float(s.start), float(s.end), s.label) for s in segments]
    beats, downbeats = _floats(beats), _floats(downbeats)
    words = list(synced_words) if synced_words is not None else None
    text = merge.build_sheet(segments, title=title, artist=artist, synced=synced, synced_words=words, plain=plain,
                             beats=beats, downbeats=downbeats, source=source)
    if words is None:
        said_words = None
    elif synced is not None and words == merge.parse_lrc_words(synced):
        said_words = True
    else:
        said_words = _lrc_lines(words)
    kw = {"segments": _segs(segments), "title": title, "artist": artist, "synced": synced,
          "synced_words": said_words, "plain": plain, "beats": _series(beats) if beats is not None else None,
          "downbeats": _series(downbeats) if downbeats is not None else None, "source": source}
    return {"fn": "build_sheet", "kw": kw, "out": _text(text)}


class _Recorder:
    """The calls a test module makes of merge.py's and align.py's functions, each answered by the real one."""

    def __init__(self):
        self.records: list[dict] = []

    def build_sheet(self, segments, **kw):
        record = _sheet_record(list(segments), **kw)
        self.records.append(record)
        return merge.build_sheet(list(segments), **kw)

    def snap_to_beats(self, segments, beats):
        segments = list(segments)
        out = merge.snap_to_beats(segments, beats)
        self.records.append({"fn": "snap_to_beats", "args": [_segs(segments), _series(beats)], "out": _segs(out)})
        return out

    def parse_lrc(self, text):
        self.records.append(_parse_record(text))
        return merge.parse_lrc(text)

    def parse_lrc_words(self, text):
        self.records.append(_parse_record(text))
        return merge.parse_lrc_words(text)

    def youtube_credit(self, title, channel, video_id):
        out = merge.youtube_credit(title, channel, video_id)
        self.records.append({"fn": "youtube_credit", "args": [title, channel, video_id], "out": out})
        return out

    def _beat_grid(self, beats, *, until):
        out = merge._beat_grid(beats, until=until)
        self.records.append({"fn": "_beat_grid", "args": [_floats(beats), float(until)], "out": out})
        return out

    def _word_start(self, text, col):
        out = merge._word_start(text, col)
        self.records.append({"fn": "_word_start", "args": [text, col], "out": out})
        return out

    def _on_words(self, text, placed):
        out = merge._on_words(text, placed)
        self.records.append({"fn": "_on_words", "args": [text, [list(p) for p in placed]],
                             "out": [list(p) for p in out]})
        return out

    def _chord_line(self, placed):
        out = merge._chord_line(placed)
        self.records.append({"fn": "_chord_line", "args": [[list(p) for p in placed]], "out": out})
        return out

    def lyrics_offset(self, lines, segments, beats, downbeats, *, audio_s, lyrics_s):
        record = _offset_record(lines, segments, beats, downbeats, audio_s=audio_s, lyrics_s=lyrics_s)
        self.records.append(record)
        return align.lyrics_offset(lines, segments, beats, downbeats, audio_s=audio_s, lyrics_s=lyrics_s)

    def shifted_lrc(self, text, offset):
        out = align.shifted_lrc(text, offset)
        self.records.append({"fn": "shifted_lrc", "args": [text, float(offset)], "out": out})
        return out


def _parse_record(text: str) -> dict:
    try:
        return {"fn": "parse_lrc_words", "args": [text], "out": _lrc_lines(merge.parse_lrc_words(text))}
    except (ValueError, OverflowError) as e:
        return {"fn": "parse_lrc_words", "args": [text], "err": _err(e)}


def _alignment(found) -> dict:
    return {"offset": _number(found.offset), "why": found.why, "best": _number(found.best),
            "score": _number(found.score), "runner_up": _number(found.runner_up)}


def _offset_record(lines, segments, beats, downbeats, *, audio_s, lyrics_s) -> dict:
    lines = [(float(t), text) for t, text in lines]
    segments = [ChordSegment(float(s.start), float(s.end), s.label) for s in segments]
    beats, downbeats = _floats(beats), _floats(downbeats)
    found = align.lyrics_offset(lines, segments, beats, downbeats, audio_s=float(audio_s), lyrics_s=float(lyrics_s))
    kw = {"lines": [list(line) for line in lines], "segments": _segs(segments), "beats": _series(beats),
          "downbeats": _series(downbeats), "audio_s": float(audio_s), "lyrics_s": float(lyrics_s)}
    return {"fn": "lyrics_offset", "kw": kw, "out": _alignment(found),
            "fits": _fits(lines, segments, beats, downbeats, audio_s=float(audio_s), lyrics_s=float(lyrics_s))}


def _fits(lines, segments, beats, downbeats, *, audio_s, lyrics_s) -> dict | None:
    """Every candidate's ``_Fit`` (offset, score, onsets, coverage), as ``lyrics_offset`` scores them before it rounds
    any: the SHA-256 (16 hex digits) of their doubles' big-endian bytes, and how many; None where it scores none. So
    a sum off in its last bit (``statistics.fmean``'s math.fsum, the builtin sum of the measures) shows. The steps
    are lyrics_offset's own, called one by one."""
    sung = align._sung(lines)
    if len(sung) < align.MIN_LINES:
        return None
    audio = align._Audio(segments, beats, downbeats, until=max([audio_s] + [s.end for s in segments]))
    if not audio.segs or audio.beat <= 0 or len(audio.bars) < 2:
        return None
    d = audio_s - lyrics_s
    pairs = align._repeated(sung)
    music = audio.music()
    least = max(0.0, music[1] - music[0] - lyrics_s)
    fits = [align._fit(o, sung, pairs, audio, d=d, music=music, lyrics_s=lyrics_s, least=least)
            for o in align._candidates(d, audio.beat, audio.bar)]
    data = b"".join(struct.pack(">dddd", f.offset, f.score, f.onsets, f.coverage) for f in fits)
    return {"sha256": hashlib.sha256(data).hexdigest()[:16], "n": len(fits)}


@contextmanager
def _recording(module, names: tuple[str, ...], *, merge_names: tuple[str, ...] = ()):
    """``module``'s ``names`` (and its ``merge``'s ``merge_names``) answered through a recorder, for its tests."""
    rec = _Recorder()
    saved = {name: getattr(module, name) for name in names}
    saved_merge = getattr(module, "merge", None)
    try:
        for name in names:
            setattr(module, name, getattr(rec, name))
        if merge_names:
            proxy = types.SimpleNamespace(**{k: getattr(merge, k) for k in dir(merge) if not k.startswith("__")})
            for name in merge_names:
                setattr(proxy, name, getattr(rec, name))
            module.merge = proxy
        yield rec
    finally:
        for name, value in saved.items():
            setattr(module, name, value)
        if merge_names:
            module.merge = saved_merge


def _tests_calls(module, names, merge_names=()) -> list[dict]:
    """Every call of ``names`` the module's tests make, but past ``CALLS_A_TEST`` of one function in one test (a test
    that loops over seeded beats a thousand times)."""
    out: list[dict] = []
    with _recording(module, names, merge_names=merge_names) as rec:
        for name in sorted(n for n in dir(module) if n.startswith("test_")):
            rec.records.clear()
            getattr(module, name)()
            counts: dict[str, int] = {}
            for record in rec.records:
                counts[record["fn"]] = counts.get(record["fn"], 0) + 1
                if counts[record["fn"]] <= CALLS_A_TEST:
                    out.append(record)
    return out


def _once(records: list[dict]) -> list[dict]:
    seen: dict[str, dict] = {}
    for record in records:
        seen.setdefault(json.dumps(record, sort_keys=True, ensure_ascii=False), record)
    return list(seen.values())


def _one_line_texts() -> list[str]:
    return [t for t in literals(MERGE_LITERALS + ALIGN_LITERALS)
            if "\n" not in t and 3 <= len(t) <= 80 and (" " in t or not t.isascii())] + list(ASTRAL_LINES)


def _seeded_beats(rng: random.Random, until: float) -> list[float]:
    """Beats as beat_this gives them: a tempo, a little jitter, sometimes a gap, a beat found twice, none at all."""
    kind = rng.choice(("plain", "jitter", "gap", "double", "late", "none", "few"))
    if kind == "none":
        return []
    period = rng.choice((0.5, 0.4, 0.45, 0.6, 0.667, 0.375))
    start = rng.choice((0.0, 0.0, 0.12, 0.3, 1.0))
    beats = [round(start + k * period, 3) for k in range(int((until - start) / period) + 1)]
    if kind == "few":
        return beats[: rng.randint(1, 2)]
    if kind == "jitter":
        beats = [round(b + rng.choice((-0.01, 0.0, 0.004, 0.012)), 3) for b in beats]
    elif kind == "gap" and len(beats) > 20:
        a = rng.randrange(4, len(beats) - 12)
        del beats[a : a + rng.randint(3, 9)]
    elif kind == "double" and len(beats) > 8:
        k = rng.randrange(1, len(beats) - 1)
        beats.insert(k + 1, round(beats[k] + 0.04, 3))
        beats.append(round(beats[-1] + period / 2, 3))  # half a period on: a beat, never -1 missing
    elif kind == "late":
        beats = [b for b in beats if b >= 4.0]
    return beats


def _seeded_downbeats(rng: random.Random, beats: list[float]) -> tuple[list[float] | None, int]:
    kind = rng.choice(("four", "four", "three", "missed", "spurious", "none", "none", "one"))
    per = 3 if kind == "three" else 4
    if kind == "none" or not beats:
        return None, per
    marks = beats[rng.randrange(per) :: per]
    if kind == "missed" and len(marks) > 4:
        del marks[len(marks) // 2]
    elif kind == "spurious" and len(marks) > 2:
        marks = sorted(marks + [round(marks[1] + 0.3, 3)])
    elif kind == "one":
        marks = marks[:1]
    return marks, per


def _seeded_segments(rng: random.Random, beats: list[float], until: float, n: int) -> list[ChordSegment]:
    """Chords changing near beats (on one, between two at their middle, a blip, a long "N"), up to ``until``."""
    grid = beats if len(beats) >= 2 else [k * 0.5 for k in range(int(until / 0.5) + 1)]
    t, segs = rng.choice((0.0, 0.0, 0.25, 2.0)), []
    for _ in range(n):
        k = min(range(len(grid)), key=lambda i: abs(grid[i] - t))
        step = rng.choice((1, 2, 2, 4, 4, 4, 8, 0))
        end = grid[min(k + step, len(grid) - 1)] if step else t + 0.1
        end = round(end + rng.choice((0.0, 0.0, 0.03, -0.02, 0.25)), 3)
        if end <= t:
            end = round(t + 0.2, 3)
        segs.append(ChordSegment(t, end, rng.choice(LABELS)))
        t = end
        if t >= until:
            break
    return segs


def _word_line(rng: random.Random, script: str) -> str:
    if script == "cjk":
        return "".join(rng.choice(CJK) for _ in range(rng.randint(3, 12)))
    if script == "mixed":
        return rng.choice(CJK) + rng.choice(WORDS) + rng.choice(CJK) + "，" + rng.choice(WORDS)
    n = rng.randint(1, 14 if script == "long" else 7)
    return " ".join(rng.choice(WORDS + ASTRAL_WORDS if script == "astral" else WORDS) for _ in range(n))


def _stamp(t: float, brackets: str = "[]") -> str:
    m, s = divmod(t, 60)
    return f"{brackets[0]}{int(m):02d}:{s:05.2f}{brackets[1]}"


def _seeded_lrc(rng: random.Random, start: float, until: float, words: bool) -> str:
    """Timed lyrics: a line every bar or two, a break now and then, a word stamp before each word where ``words``."""
    script = rng.choice(("latin", "latin", "cjk", "mixed", "long", "astral"))
    lines, t = [], start
    while t < until:
        if rng.random() < 0.12:
            lines.append(_stamp(t))  # an empty entry: a break
            t += rng.choice((4.0, 8.0, 10.0))
            continue
        text = _word_line(rng, script)
        if words and rng.random() < 0.85:
            parts = text.split(" ") if script not in ("cjk",) else list(text)
            span = rng.choice((1.5, 3.0, 4.0))
            w = t + rng.choice((0.0, 0.0, 0.1, -0.2))
            out = []
            for part in parts:
                out.append(_stamp(max(w, 0.0), "<>") + part)
                w += span / len(parts) * rng.choice((1.0, 0.5, 1.5))
            text = (" " if script != "cjk" else "").join(out) + (" " + _stamp(w, "<>") if rng.random() < 0.5 else "")
        lines.append(_stamp(t) + text)
        t += rng.choice((2.0, 4.0, 4.0, 3.5, 8.0))
    return "\n".join(lines) + "\n"


def _seeded_hearings() -> list[dict]:
    rng = random.Random(16)
    records = []
    for case in range(44):
        until = rng.choice((8.0, 20.0, 36.0, 64.0))
        beats = _seeded_beats(rng, until)
        downbeats, _ = _seeded_downbeats(rng, beats)
        segs = _seeded_segments(rng, beats, until, rng.choice((0, 1, 6, 20, 60)))
        lyrics = rng.choice(("none", "plain", "synced", "synced", "words", "words", "both"))
        synced = plain = words = None
        first = rng.choice((0.0, 0.4, 4.0, 9.0))
        if lyrics in ("synced", "words", "both"):
            synced = _seeded_lrc(rng, first, until - rng.choice((0.0, 6.0)), lyrics in ("words", "both"))
            if lyrics != "synced":
                words = merge.parse_lrc_words(synced)
        if lyrics in ("plain", "both"):
            plain = "\n".join(_word_line(rng, rng.choice(("latin", "cjk", "astral"))) for _ in range(rng.randint(1, 6)))
            plain = rng.choice(("", "\n\n", "  ")) + plain + rng.choice(("", "\n", "\n\n  \n"))
        source = rng.choice((None, None, "", "  ", merge.youtube_credit("Some video", "A channel", "abc"),
                             "Audio from YouTube: X (Y)\nLyrics 12.00 s later than LRCLIB timed them\n"
                             "Lyrics transcribed from the audio (Whisper), unverified"))
        title, artist = rng.choice((("River Road", "Nobody"), ("斑马斑马", "宋冬野"),
                                    ("T", "A")))
        records.append(_sheet_record(segs, title=title, artist=artist, synced=synced, synced_words=words,
                                     plain=plain, beats=beats or None, downbeats=downbeats, source=source))
    return records


def _edge_sheets() -> list[dict]:
    """What the brief names: snapping's ties, 3/4 and no downbeats, a lyric line longer than a bar, no segments, one
    chord, an instrumental."""
    beats = [k * 0.5 for k in range(41)]
    seg = ChordSegment
    out = []
    # A change exactly between two beats goes to the earlier one; both ends there drop the chord.
    ties = [seg(0.25, 1.25, "G"), seg(1.25, 1.5, "D"), seg(1.5, 2.75, "Em"), seg(2.75, 3.75, "C"), seg(3.75, 9.0, "G")]
    out.append({"fn": "snap_to_beats", "args": [_segs(ties), _series(beats)], "out": _segs(merge.snap_to_beats(ties, beats))})
    for segs in ([], [seg(0.0, 9.0, "N")], [seg(0.0, 0.0, "G")], [seg(3.0, 1.0, "G")], [seg(1.0, 2.0, "G")]):
        for b in (beats, [], [1.0], [2.0, 1.0, 1.5, -0.5, 1.0004]):
            out.append({"fn": "snap_to_beats", "args": [_segs(segs), _series(b)],
                        "out": _segs(merge.snap_to_beats(segs, b))})
    waltz = [seg(0.0, 3.0, "G"), seg(3.0, 6.0, "D"), seg(6.0, 7.5, "Em"), seg(7.5, 12.0, "C")]
    long_line = "[00:00.00]" + " ".join(["a very long line that goes on"] * 6) + "\n[00:02.00]short\n"
    for kw in (
        {"segments": waltz, "beats": beats[:25], "downbeats": beats[:25:3]},
        {"segments": waltz, "beats": beats[:25], "downbeats": None},
        {"segments": waltz, "beats": beats[:25], "downbeats": [], "synced": "[00:01.50]in three\n[00:04.50]time\n"},
        {"segments": waltz, "beats": None, "plain": "no beats at all\n"},
        {"segments": [seg(0.0, 8.0, "Am")], "beats": beats, "synced": long_line},
        {"segments": [seg(0.0, 8.0, "Am")], "beats": beats},
        {"segments": [], "beats": beats, "plain": "La la"},
        {"segments": [], "beats": None, "synced": "[00:01.00]just words\n"},
        {"segments": [], "beats": None},
        {"segments": [seg(0.0, 20.0, "N")], "beats": beats, "synced": "[00:01.00]\n[00:05.00]\n"},
    ):
        out.append(_sheet_record(title="T", artist="A", **kw))
    return out


def _literal_sheets() -> list[dict]:
    """Every literal as lyrics: synced (and read for its words) and plain, over one hearing; and put on a sheet of none."""
    beats = [k * 0.5 for k in range(121)]
    segs = [ChordSegment(2.0 * k + 0.1, 2.0 * k + 2.1, LABELS[k % len(LABELS)]) for k in range(14)]
    bare = merge.build_sheet(segs[:2], title="T", artist="A", beats=beats[:9])
    out = [{"fn": "with_plain_lyrics", "args": [bare, "\n\nLa la\n  \nla  \n\n"], "out": merge.with_plain_lyrics(bare, "\n\nLa la\n  \nla  \n\n")}]
    for text in dict.fromkeys(literals(MERGE_LITERALS + ALIGN_LITERALS) + LRC_EDGES[:14] + LRC_EDGES[15:]):
        if any(e in text for e in ("9" * 400,)):
            continue
        try:
            words = merge.parse_lrc_words(text)
        except (ValueError, OverflowError):
            continue
        if any(line.text for line in words):
            out.append(_sheet_record(segs, title="T", artist="A", synced=text, synced_words=words or None,
                                     beats=beats))
        elif "\n" in text or text.strip() != text or not text:
            out.append(_sheet_record(segs[:3], title="T", artist="A", plain=text, beats=beats[:13]))
            out.append({"fn": "with_plain_lyrics", "args": [bare, text], "out": merge.with_plain_lyrics(bare, text)})
    return out


def _column_records() -> list[dict]:
    rng = random.Random(1616)
    out = []
    for text in _one_line_texts():
        n = len(text)
        out.append({"fn": "_word_start", "args": [text, None], "out": [merge._word_start(text, c) for c in range(n + 2)]})
        placed = sorted((rng.randrange(n + 3), rng.choice(LABELS[:-2])) for _ in range(rng.randint(1, 5)))
        on = merge._on_words(text, placed)
        out.append({"fn": "_on_words", "args": [text, [list(p) for p in placed]], "out": [list(p) for p in on]})
        out.append({"fn": "_chord_line", "args": [[list(p) for p in on]], "out": merge._chord_line(on)})
    return out


def merge_records() -> list[dict]:
    records = _tests_calls(test_autochords_merge,
                           ("build_sheet", "parse_lrc", "parse_lrc_words", "snap_to_beats", "youtube_credit"),
                           ("_word_start", "_on_words", "_chord_line", "_beat_grid"))
    texts = dict.fromkeys(literals(MERGE_LITERALS + ALIGN_LITERALS) + LRC_EDGES + STAMP_EDGES + LRC_RAISING)
    records += [_parse_record(t) for t in texts]
    for title, channel, video in (("", "", "id"), ("　Wide　title ", "\tChan\nnel", "x"), ("T", "  ", "y")):
        records.append({"fn": "youtube_credit", "args": [title, channel, video],
                        "out": merge.youtube_credit(title, channel, video)})
    records += _column_records()
    records += _edge_sheets()
    records += _literal_sheets()
    records += _seeded_hearings()
    records += _tie_records()
    return _once(records)


def _tie_records() -> list[dict]:
    """Where Python's round() half to even decides: a gap of exactly 2.5 and 4.5 beat periods (``_beat_grid``'s
    missing beats), downbeats whose spacings' median is 2.5 or 4.5 beats (``_bar_starts``' beats a bar), and a missed
    downbeat 2.5 bars on (its missing bars, and where each falls)."""
    out = []
    for beats in ([0.0, 0.5, 1.0, 1.5, 2.75, 3.25, 3.75, 4.25, 4.75],
                  [0.0, 0.5, 1.0, 1.5, 2.0, 4.25, 4.75, 5.25, 5.75, 6.25, 6.75]):
        out.append({"fn": "_beat_grid", "args": [beats, 8.0], "out": merge._beat_grid(beats, until=8.0)})
        segs = [ChordSegment(0.0, 2.6, "G"), ChordSegment(2.6, 4.3, "D"), ChordSegment(4.3, 8.0, "Em")]
        out.append(_sheet_record(segs, title="T", artist="A", beats=beats))
    grid = [k * 0.5 for k in range(41)]
    segs = [ChordSegment(1.0 * k, 1.0 * k + 1.0, LABELS[k % 12]) for k in range(20)]
    for marks in ([0, 2, 5], [0, 4, 9], [0, 2, 4, 9], [0, 4, 8, 18], [1, 3, 6, 8, 11], [3, 7, 12, 16, 21, 30]):
        downbeats = [grid[i] for i in marks]
        out.append({"fn": "_bar_starts", "args": [grid, [s.start for s in segs], downbeats],
                    "out": merge._bar_starts(grid, [s.start for s in segs], downbeats)})
        out.append(_sheet_record(segs, title="T", artist="A", beats=grid, downbeats=downbeats))
    return out


def _seeded_alignments() -> list[dict]:
    """test_autochords_align's songs heard otherwise: more at one end, cut, a 3/4 song, another song's lines, an
    LRC entry of no words, too few lines, no downbeats."""
    build, form = test_autochords_align.build, test_autochords_align.song_form
    rng = random.Random(1617)
    out = []
    for before, after, lead, tail in ((0.0, 0.0, 0.0, 2.0), (7.25, 0.0, 0.0, 2.0), (0.0, 7.3, 0.5, 0.0),
                                      (20.0, 4.0, 1.0, 3.0), (1.5, 0.0, 0.0, 2.0), (31.0, 0.0, 0.0, 2.0),
                                      (0.0, 0.0002, 0.0, 2.0), (0.4, 0.0, 0.2, 1.0)):
        lines, lyrics_s, segs, beats, downbeats, audio_s = build(form(), before=before, after=after, lead=lead,
                                                                 tail=tail)
        out.append(_offset_record(lines, segs, beats, downbeats, audio_s=audio_s, lyrics_s=lyrics_s))
        if rng.random() < 0.5:
            out.append(_offset_record(lines, segs, beats, [], audio_s=audio_s, lyrics_s=lyrics_s))
        jitter = [round(b + rng.choice((-0.012, 0.0, 0.007)), 3) for b in beats]
        out.append(_offset_record(lines + [(lines[3][0] + 1.0, "")], segs, jitter, downbeats[::2],
                                  audio_s=audio_s, lyrics_s=lyrics_s))
    lines, lyrics_s, segs, beats, downbeats, audio_s = build(form(), before=12.0)
    sparse = [seg for k, seg in enumerate(segs) if k % 3 == 0]  # a chord one bar in three, silence between
    out.append(_offset_record(lines, sparse, beats, downbeats, audio_s=audio_s, lyrics_s=lyrics_s))
    out.append(_offset_record(lines[:5], segs, beats, downbeats, audio_s=audio_s, lyrics_s=lyrics_s))
    out.append(_offset_record(lines[:6], segs, beats, downbeats, audio_s=audio_s, lyrics_s=lyrics_s))
    out.append(_offset_record(lines, segs, beats[:1], downbeats, audio_s=audio_s, lyrics_s=lyrics_s))
    out.append(_offset_record(lines, [ChordSegment(0.0, audio_s, "N")], beats, downbeats, audio_s=audio_s,
                              lyrics_s=lyrics_s))
    waltz = [(["G", "D", "Em", "C"] * 3, [f"Waltz line {n}" for n in range(6)])] * 4
    lines, lyrics_s, segs, beats, downbeats, audio_s = build(waltz, before=6.0)
    out.append(_offset_record(lines, segs, beats, beats[::3], audio_s=audio_s, lyrics_s=lyrics_s))
    labels = ("C#m7", "Dbmaj7", "Ebdim", "F#", "Bbm", "A", "Amaj7", "Gm", "", "N")
    mixed = [ChordSegment(2.0 * k, 2.0 * k + 2.0, labels[k % len(labels)]) for k in range(60)]
    beats = [k * 0.5 for k in range(241)]
    sung = [(round(2.0 * k + 0.1, 3), "the same words again" if k % 3 == 0 else f"line {k}") for k in range(0, 54, 2)]
    out.append(_offset_record(sung, mixed, beats, beats[::4], audio_s=120.0, lyrics_s=110.0))
    return out


def align_records() -> list[dict]:
    records = _tests_calls(test_autochords_align, ("lyrics_offset", "shifted_lrc", "parse_lrc", "parse_lrc_words"))
    records = [r for r in records if r["fn"] in ("lyrics_offset", "shifted_lrc")]
    texts = dict.fromkeys(literals(ALIGN_LITERALS + MERGE_LITERALS) + LRC_EDGES + STAMP_EDGES)
    for text in texts:
        try:
            timed = bool(merge.parse_lrc(text))
        except (ValueError, OverflowError):
            timed = True
        for offset in SHIFTS if timed or text in LRC_EDGES else ():
            try:
                out = align.shifted_lrc(text, offset)
            except (ValueError, OverflowError) as e:
                records.append({"fn": "shifted_lrc", "args": [text, offset], "err": _err(e)})
            else:
                records.append({"fn": "shifted_lrc", "args": [text, offset], "out": _text(out)})
    records += _seeded_alignments()
    records += _fsums()
    return _once(records)


def _fsums() -> list[dict]:
    """math.fsum, which statistics.fmean sums align.py's measures with (correctly rounded, unlike the builtin sum):
    sums that cancel, that tie half way between two floats, of one value, of none."""
    rng = random.Random(1618)
    cases = [[], [0.1], [0.1] * 10, [1e16, 1.0, -1e16], [1.0, 1e100, 1.0, -1e100], [1e308, 1e308, -1e308],
             [2.0 ** 53, 1.0, 1e-16], [2.0 ** 53, -0.5, -2.0 ** -54], [-0.0], [-0.0, 0.0], [0.5, 0.25, 1 / 3] * 7]
    for _ in range(12):
        cases.append([rng.choice((1.0, -1.0)) * rng.random() * 10.0 ** rng.randint(-20, 20) for _ in range(rng.randint(2, 40))])
    out = []
    for xs in cases:
        try:
            out.append({"fn": "math.fsum", "args": [xs], "out": math.fsum(xs)})
        except OverflowError as e:
            out.append({"fn": "math.fsum", "args": [xs], "err": _err(e)})
    return out


def test_autochords_json():
    check(DATA / "viewer" / "autochords.json", autochords_json())


def test_merge_vectors():
    check(SHEET_AREA / "merge.jsonl", jsonl(merge_records(), corpus="autochords-sheet/merge", made_by=MADE_BY))


def test_align_vectors():
    check(SHEET_AREA / "align.jsonl", jsonl(align_records(), corpus="autochords-sheet/align", made_by=MADE_BY))
