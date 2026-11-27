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

And, for the phone's ``viewer.autochords`` (merge.py, align.py and sheet.py, area ``autochords-sheet``):

- ``data/caracole/viewer/autochords.json`` (``autochords_json``): merge.py's constants and patterns (``merge``),
  align.py's (``align``), sheet.py's (``sheet``) and transcript.py's the sheet reads (``transcript``), under their Python
  names (a leading underscore dropped), read by ``viewer.autochords``.

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

- ``vectors/autochords-sheet/sheet.jsonl``, sheet.py's sheet half for ``SheetHalf``, ``Heard`` and ``Relay``: ``heard``
  records name each hearing (``_hearings``: four chords, of no length, float corners, an empty one, the aligning song
  with a talk before it or an outro after, seeded songs), by its json.dumps text, which the others name;
  ``read_heard`` over ``HEARD_TEXTS`` (every shape it reads and every one it refuses: ``err`` ValueError), its ``out``
  heard_record's text; ``make_sheet`` (``kw``: the song's ``SONG_FIELDS``, a hearing's name, the source, a
  transcript, silent, said, the video's as_json text, the maker, its models as pairs) and its ``out``: the sheet, what
  it used, the key, the shift, silent, said, and ``raw``, raw_of's text as versions.set_raw stores it; ``relay``
  (``kw``: the song, a raw's text, its ``heard`` a hearing's name where it is one, ``noted``): relay_due, noted_in, and
  relay with the raw raw_of then writes, or ``err``; ``relays_here``, ``made_by_another`` and ``Timed.note``. A sheet or
  a raw past ``SHEET_WHOLE`` characters is its digest.
- ``vectors/autochords-sheet/relay.jsonl``: sheet_lyrics.py's ``relay_onto_sheets`` over one library (``_library``:
  sheets made on the phone, here, from replaced audio, elsewhere over other audio, with an unreadable ``heard``,
  ignored, in ``[ignore]``, beside a human sheet, over a transcript, up to date, of no columns; a transcript and nothing
  sung noted here), ``args`` its fixture (``sync:id`` among its kv) and its steps (``{"relay": song ids or null}``),
  ``out`` each step's songs re-laid, the songs' folders' files, every version's raw, each song unit's digest and each
  info.json.

A list of beats ``[s + k * step for k in range(n)]`` is written ``{"start": s, "step": step, "n": n}`` (where Python's
list is exactly that), a sheet past ``WHOLE_MOST`` characters by ``{"sha256": first 16 hex digits, "size": len}``,
and ``synced_words`` that are ``parse_lrc_words(synced)`` as ``true``.
"""

from __future__ import annotations

import functools
import hashlib
import json
import math
import random
import struct
import types
from contextlib import contextmanager

import test_autochords_align
import test_autochords_merge
from conftest import add_song
from helpers import phone_render
from helpers.corpus import DATA, VECTORS, check, dump_fixture, jsonl
from test_autochords_models import COMMON_NAMES, FRAMES, SPELLINGS, spelling_song
from test_conformance_viewer_sheet import literals

from caracole.autochords import ChordSegment, align, btc, merge, sheet, transcript
from caracole.autochords.sheet_lyrics import relay_onto_sheets
from caracole.autochords.transcript import Transcript, keep_transcript, note_heard_nothing
from caracole.db import kv_set_json
from caracole.overrides import load_overrides
from caracole.songs import AUTO_SHEET, get_song, list_songs, update_song
from caracole.lyrics import Lyrics
from caracole.songs import Song
from caracole.youtube import Video

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
        "sheet": {
            "MODEL": sheet.MODEL, "CONTRACT": sheet.CONTRACT, "SYNC_TOLERANCE_S": sheet.SYNC_TOLERANCE_S,
            "COLUMNS": sheet.COLUMNS, "MAKER_MEMBERS": list(sheet.MAKER_MEMBERS),
            "RELAY_KEEPS": list(sheet.RELAY_KEEPS),
        },
        "transcript": {
            "LYRICS_SOURCE": transcript.LYRICS_SOURCE, "NOTE": transcript.NOTE, "SILENT": transcript.SILENT,
            "NOT_SUNG": transcript.NOT_SUNG, "TRANSCRIPT": transcript.TRANSCRIPT,
            "HEARD_NOTHING": transcript.HEARD_NOTHING,
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


def _text(text: str, most: int = WHOLE_MOST):
    if len(text) <= most:
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
        self.records.append(_parse_record(text, words=False))
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


def _parse_record(text: str, *, words: bool = True) -> dict:
    """``parse_lrc_words`` of ``text``, or ``parse_lrc``'s (``[time, text]`` a line), a function of its own."""
    fn = "parse_lrc_words" if words else "parse_lrc"
    try:
        out = _lrc_lines(merge.parse_lrc_words(text)) if words else [list(line) for line in merge.parse_lrc(text)]
    except (ValueError, OverflowError) as e:
        return {"fn": fn, "args": [text], "err": _err(e)}
    return {"fn": fn, "args": [text], "out": out}


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
    any (``align.scored``, the steps ``lyrics_offset`` itself takes): the SHA-256 (16 hex digits) of their doubles'
    big-endian bytes, and how many; None where it scores none. So a sum off in its last bit (``statistics.fmean``'s
    math.fsum, the builtin sum of the measures) shows."""
    early, fits, _ = align.scored(lines, segments, beats, downbeats, audio_s=audio_s, lyrics_s=lyrics_s)
    if early is not None:
        return None
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
    records += [_parse_record(t, words=False) for t in LRC_EDGES + LRC_RAISING]
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
    # Lines past the BMP: mathematical letters and digits, CJK Extension B (``_sung``'s ``\w+`` and casefold, the
    # repeats' keys counted in code points), the chorus repeated so that its lines pair.
    chorus = [f"{ASTRAL_LINES[k]} \U0001d7d0{k}" for k in (0, 3, 5, 1)]
    astral = [(chords, chorus if sung == test_autochords_align.CHORUS_WORDS else sung) for chords, sung in form()]
    lines, lyrics_s, segs, beats, downbeats, audio_s = build(astral, before=7.25)
    out.append(_offset_record(lines, segs, beats, downbeats, audio_s=audio_s, lyrics_s=lyrics_s))
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


# --- sheet.py and sheet_lyrics.py's re-lay: viewer.autochords' SheetHalf and Relay (area autochords-sheet) -------

PHONE_ID = "f0f0f0f0f0f0f0f0"  # the sync id of the caracole that made a phone-made sheet
HERE_ID = "1a2b3c4d5e6f7a8b"  # this side's, in relay.jsonl's library (kv sync:id)
PHONE_MAKER = sheet.Maker("phone", PHONE_ID, {"chords": "btc_large_voca@0123456789abcdef",
                                              "beats": "beat_this final0@fedcba9876543210 fp16"},
                          "onnxruntime 1.32.0", "song.mp3", "00112233aabbccdd")
COMPUTER_MAKER = sheet.Maker("computer", HERE_ID, {"chords": "btc_large_voca@0123456789abcdef",
                                                   "beats": "beat_this final0@fedcba9876543210"},
                             "torch 2.13.0", "Song (purchase).m4a", "8899aabbccddeeff")
BARE_MAKER = sheet.Maker("computer", None, {}, None, None, None)  # only the side known: the rest left out
SONG_FIELDS = ("title", "artist", "lyrics_status", "lyrics_json", "audio_path", "audio_mtime", "autochords_mtime")
SHEET_VIDEO = {"id": "lzN7Thn3FV4", "title": "Longships  (Official Audio)", "channel": "Nobody - Topic",
               "duration": 46.0}
PURCHASE = "Audio from a purchase: Nobody - River Road.m4a"
SYNCED_FOUR = "[00:00.50]Walking down the river road\n[00:05.20]Singing to the morning light\n"
WORDS_FOUR = "[00:00.00]<00:00.00>Walking <00:00.60>down <00:01.20>the <00:03.00>river <00:03.60>road\n"
CHINESE_FOUR = "[00:00.50]我们一起走在河边的路上\n[00:05.20]唱着早晨的歌\n"
ASTRAL_FOUR = ("[00:00.50]\U0001d401\U0001d428\U0001d425\U0001d41d \U00020000\U00020001 \U0001f600 road\n"
               "[00:05.20]corazón \U0001d7cf\U0001d7d0 light\n")
TRANSCRIPT_FOUR = "[00:01.00]<00:01.00>heard <00:01.50>words\n[00:06.00]<00:06.00>and <00:06.40>more\n"
NOTE_CASES = ((None, 0.0), (0.0, 3.0), (0.0, -3.0), (0.0, 0.05), (0.0, -0.25), (12.0, 12.0), (-2.0, -2.5),
              (0.05, 1.0), (0.15, 1.0), (0.25, 1.0), (-0.05, -1.0), (2.45, 3.0), (1e-07, 0.1), (-0.0, 0.0),
              (1234.56789, 1234.5), (0.30000000000000004, 0.30000000000000004))


def _song(**fields) -> Song:
    """A song record as make_sheet and relay_due read it (only ``SONG_FIELDS`` matter)."""
    base = dict(id=7, key="nobody|river road", artist="Nobody", title="River Road", artists=["Nobody"], album=None,
                duration_ms=None, isrc=None, source_ids={}, added_at="2026-11-01T00:00:00Z", variant=None,
                status="found", review=False, match_decision=None, match_step=None, match_score=None,
                match_artist_key=None, match_song_key=None)
    return Song(**{**base, **fields})


def _song_kw(song: Song) -> dict:
    return {name: getattr(song, name) for name in SONG_FIELDS}


def _lyrics(plain: str = "", synced: str | None = None, *, duration: float | None = None,
            instrumental: bool = False) -> str:
    """The text of a song's ``lyrics_json``, plain lyrics from the timed ones' lines where none are given."""
    if not plain and synced:
        plain = "\n".join(text for _, text in merge.parse_lrc(synced))
    return Lyrics(plain=plain, synced=synced, instrumental=instrumental, duration=duration, lrclib_id=None, raw={},
                  provider="lrclib", url=None).to_json()


def _transcript(lrc: str, made_at: str = "2026-11-20T01:00:00Z") -> Transcript:
    return Transcript(lrc=lrc, audio="", audio_mtime=None, model="", language="", device="", words_dropped=0,
                      made_at=made_at)


def _maker_kw(maker: sheet.Maker | None) -> dict | None:
    if maker is None:
        return None
    # the models as pairs, in their order: a record's objects are written with their keys sorted
    return {"on": maker.on, "by": maker.by, "models": [list(item) for item in maker.models.items()],
            "runtime": maker.runtime,
            "audio_name": maker.audio_name, "audio_sha16": maker.audio_sha16}


def _heard_text(heard: sheet.Heard) -> str:
    """What was heard as an auto sheet's raw writes it: json.dumps of ``heard_record``."""
    return json.dumps(sheet.heard_record(heard), ensure_ascii=False)


SHEET_WHOLE = 320  # a sheet or a raw of sheet.jsonl longer than this is written by its digest


def _made_out(made: sheet.Made) -> dict:
    return {"text": _text(made.text, SHEET_WHOLE), "used": made.used, "key": made.key, "shift": made.shift,
            "silent": made.silent, "said": made.said}


def _raw_text(raw: dict) -> str:
    """A raw as versions.set_raw stores it."""
    return json.dumps(raw, ensure_ascii=False)


@functools.cache
def _hearings() -> dict[str, sheet.Heard]:
    """What was heard, by name: four chords over ten seconds; the same of no length; float corners (0.1 + 0.2, 1e-07,
    -0.0, a time a hair past a beat); an aligning song heard with a talk before it, and with less; seeded songs."""
    four = [ChordSegment(2.0 * k, 2.0 * (k + 1), ("C", "G", "Am", "F")[k % 4]) for k in range(5)]
    beats = [k * 0.5 for k in range(21)]
    out = {"four": sheet.Heard(four, beats, beats[::4], 10.0),
           "four_unmeasured": sheet.Heard(four, beats, beats[::4], None),
           "corners": sheet.Heard([ChordSegment(-0.0, 0.1 + 0.2, "C"), ChordSegment(0.1 + 0.2, 2.0000001, "G"),
                                   ChordSegment(2.0000001, 4.0, "Am7"), ChordSegment(4.0, 6.0, "N"),
                                   ChordSegment(6.0, 9.5, "F#m")],
                                  [1e-07] + [k * 0.5 for k in range(1, 20)], [1e-07, 2.0, 4.0, 6.0, 8.0], 9.5),
           "empty": sheet.Heard([], [], [], 3.0)}
    for name, kw in (("talk", {"before": 12.0}), ("short_talk", {"before": 1.5}), ("outro", {"after": 4.0}),
                     ("long_talk", {"before": 31.0})):
        _, _, segs, beats, downbeats, audio_s = test_autochords_align.build(test_autochords_align.song_form(), **kw)
        out[name] = sheet.Heard(segs, beats, downbeats, audio_s)
    rng = random.Random(17)
    for n in range(6):
        until = rng.choice((20.0, 36.0, 64.0))
        beats = _seeded_beats(rng, until)
        downbeats, _ = _seeded_downbeats(rng, beats)
        segs = _seeded_segments(rng, beats, until, rng.choice((1, 6, 20, 60)))
        out[f"seeded{n}"] = sheet.Heard(segs, beats, downbeats or [], round(until + rng.choice((0.0, 0.7)), 3))
    return out


def _aligning_lyrics(words: bool = False) -> tuple[str, float]:
    """The aligning song's timed lyrics as LRCLIB timed them (a stamp before each word where ``words``), and their
    length."""
    lines, lyrics_s, *_ = test_autochords_align.build(test_autochords_align.song_form())
    if words:
        return "".join(f"{_stamp(t)}{_word_stamped(text, t)}\n" for t, text in lines), lyrics_s
    return "".join(f"{_stamp(t)}{text}\n" for t, text in lines), lyrics_s


def _lyric_kinds() -> dict[str, tuple[str, str | None]]:
    """A song's lyrics of each kind, by name: (``lyrics_status``, ``lyrics_json``)."""
    aligning, length = _aligning_lyrics()
    return {
        "none": ("pending", None),
        "missing": ("missing", None),
        "instrumental": ("instrumental", None),
        "instrumental_record": ("found", _lyrics("", None, instrumental=True)),
        "plain": ("found", _lyrics("Walking down the river road\n\nSinging to the morning light  \n")),
        "plain_other": ("found", _lyrics("Other words now\nfor the river road")),
        "plain_same": ("found", _lyrics("Walking down the river road\nSinging to the morning light")),
        "synced": ("found", _lyrics("", SYNCED_FOUR, duration=10.0)),
        "synced_near": ("found", _lyrics("", SYNCED_FOUR, duration=11.9)),
        "synced_far": ("found", _lyrics("", SYNCED_FOUR, duration=25.0)),
        "synced_unmeasured": ("found", _lyrics("", SYNCED_FOUR, duration=None)),
        "words": ("found", _lyrics("", WORDS_FOUR, duration=10.0)),
        "chinese": ("found", _lyrics("", CHINESE_FOUR, duration=10.0)),
        "astral": ("found", _lyrics("", ASTRAL_FOUR, duration=9.5)),
        "aligning": ("found", _lyrics("", aligning, duration=length)),
        "aligning_words": ("found", _lyrics("", _aligning_lyrics(True)[0], duration=length)),
        "unreadable": ("found", "{not json"),
    }


def _named(heard: sheet.Heard) -> str:
    """The name of one of ``_hearings``' (a record names what was heard by it: the ``heard`` records)."""
    return next(name for name, h in _hearings().items() if h == heard)


def _make(song: Song, heard: sheet.Heard, *, source=None, transcript=None, silent=False, said=False, video=None,
          maker=None) -> dict:
    made = sheet.make_sheet(song, heard, source=source, transcript=transcript, silent=silent, said=said)
    raw = sheet.raw_of(song, made, video=Video.from_json(video) if video else None, maker=maker)
    kw = {"song": _song_kw(song), "heard": _named(heard), "source": source,
          "transcript": {"lrc": transcript.lrc, "made_at": transcript.made_at} if transcript else None,
          "silent": silent, "said": said, "video": _raw_text(Video.from_json(video).as_json()) if video else None,
          "maker": _maker_kw(maker)}
    return {"fn": "make_sheet", "kw": kw, "out": {**_made_out(made), "raw": _text(_raw_text(raw), SHEET_WHOLE)}}


def _make_records() -> list[dict]:
    """make_sheet and raw_of over what was heard × lyrics of each kind, sources, a transcript, nothing sung."""
    heard, kinds = _hearings(), _lyric_kinds()
    out = []
    for name in ("four", "four_unmeasured", "corners", "empty"):
        for kind, (status, lyrics) in kinds.items():
            if kind in ("aligning", "aligning_words", "unreadable"):
                continue
            song = _song(lyrics_status=status, lyrics_json=lyrics, audio_path="/music/Nobody/River Road.m4a")
            out.append(_make(song, heard[name], source=PURCHASE if kind != "plain" else None,
                             maker=COMPUTER_MAKER if kind == "words" else None))
    for kind in ("aligning", "aligning_words"):
        aligning = _song(lyrics_status="found", lyrics_json=kinds[kind][1])
        for name in ("talk", "short_talk", "outro", "long_talk"):
            out.append(_make(aligning, heard[name], maker=PHONE_MAKER, source=PURCHASE if kind == "aligning" else None))
    four = heard["four"]
    for kind in ("none", "synced", "instrumental", "plain"):  # a transcript is used only where no site has words
        song = _song(lyrics_status=kinds[kind][0], lyrics_json=kinds[kind][1])
        out.append(_make(song, four, source=PURCHASE, transcript=_transcript(TRANSCRIPT_FOUR)))
        for said in (False, True):  # nothing sung, by what was heard or by the owner's word
            out.append(_make(song, four, source=PURCHASE, silent=True, said=said))
    none = _song(lyrics_status="pending", lyrics_json=None, audio_path=None)
    credit = merge.youtube_credit(SHEET_VIDEO["title"], SHEET_VIDEO["channel"], SHEET_VIDEO["id"])
    for kind in ("none", "synced", "synced_far"):
        song = _song(lyrics_status=kinds[kind][0], lyrics_json=kinds[kind][1], audio_path=None)
        out.append(_make(song, four, source=credit, video=SHEET_VIDEO, maker=PHONE_MAKER))
    out.append(_make(none, four, source="  ", maker=BARE_MAKER))
    out.append(_make(none, four, source=f"{credit}\n{PURCHASE}", transcript=_transcript(TRANSCRIPT_FOUR, "x")))
    for n in range(4):
        for kind in ("none", "plain", "synced", "words", "chinese", "astral"):
            song = _song(lyrics_status=kinds[kind][0], lyrics_json=kinds[kind][1])
            out.append(_make(song, heard[f"seeded{n}"], source=PURCHASE if n % 2 else None,
                             maker=PHONE_MAKER if n % 3 == 0 else None))
    unreadable = _song(lyrics_status="found", lyrics_json=kinds["unreadable"][1])
    try:
        sheet.make_sheet(unreadable, four)
    except ValueError:  # make_sheet reads the song's lyrics and lets their error out (JSONDecodeError)
        out.append({"fn": "make_sheet", "kw": {"song": _song_kw(unreadable), "heard": "four",
                                               "source": None, "transcript": None, "silent": False, "said": False,
                                               "video": None, "maker": None}, "err": "ValueError"})
    else:
        raise AssertionError("unreadable lyrics made a sheet")
    return out


# read_heard's inputs, each as JSON text: what it reads, and what it refuses (ValueError), as the phone must.
HEARD_TEXTS = (
    '{"contract": 1, "duration": 10.0, "chords": [[0.0, 5.0, "C"], [5, 10.0, "G"]], "beats": [0.5, 1], '
    '"downbeats": []}',
    '{"contract": 1.0, "duration": null, "chords": [], "beats": [], "downbeats": [], "more": "kept out"}',
    '{"contract": 1, "duration": 0.30000000000000004, "chords": [[1e-07, 1e+21, "Am7"], [-0.0, 3, "N"]], '
    '"beats": [1e-07, 0.1, 2e-308, 5e-324, 1.7976931348623157e+308, 1E5, 12345678901234567890], "downbeats": [3]}',
    '{"contract": 1, "duration": NaN, "chords": [[Infinity, -Infinity, "C"]], "beats": [NaN], "downbeats": []}',
    '{"contract": 1, "duration": 1e400, "chords": [], "beats": [-1e400], "downbeats": []}',
    '{"contract": 1, "duration": 9007199254740993, "chords": [[0, 1, "\U0001d401́\U00020000"]], '
    '"beats": [], "downbeats": []}',
    '{"contract": 1, "duration": -0, "chords": [[-0, -0.0, "C"]], "beats": [-0, -0.0, 0], "downbeats": [-0]}',
    '{"contract": 2, "duration": 1.0, "chords": [], "beats": [], "downbeats": []}',
    '{"contract": true, "duration": 1.0, "chords": [], "beats": [], "downbeats": []}',
    '{"contract": "1", "duration": 1.0, "chords": [], "beats": [], "downbeats": []}',
    '{"contract": 1.5, "duration": 1.0, "chords": [], "beats": [], "downbeats": []}',
    '{"duration": 1.0, "chords": [], "beats": [], "downbeats": []}',
    '{"contract": 1, "chords": [], "beats": [], "downbeats": []}',
    '{"contract": 1, "duration": true, "chords": [], "beats": [], "downbeats": []}',
    '{"contract": 1, "duration": "1.0", "chords": [], "beats": [], "downbeats": []}',
    '{"contract": 1, "duration": 1.0, "beats": [], "downbeats": []}',
    '{"contract": 1, "duration": 1.0, "chords": "C", "beats": [], "downbeats": []}',
    '{"contract": 1, "duration": 1.0, "chords": [[0.0, 1.0]], "beats": [], "downbeats": []}',
    '{"contract": 1, "duration": 1.0, "chords": [[0.0, 1.0, "C", "x"]], "beats": [], "downbeats": []}',
    '{"contract": 1, "duration": 1.0, "chords": [["0.0", 1.0, "C"]], "beats": [], "downbeats": []}',
    '{"contract": 1, "duration": 1.0, "chords": [[0.0, false, "C"]], "beats": [], "downbeats": []}',
    '{"contract": 1, "duration": 1.0, "chords": [[0.0, 1.0, 7]], "beats": [], "downbeats": []}',
    '{"contract": 1, "duration": 1.0, "chords": [[0.0, 1.0, null]], "beats": [], "downbeats": []}',
    '{"contract": 1, "duration": 1.0, "chords": [{"start": 0}], "beats": [], "downbeats": []}',
    '{"contract": 1, "duration": 1.0, "chords": [], "beats": "12", "downbeats": []}',
    '{"contract": 1, "duration": 1.0, "chords": [], "beats": [0.5, true], "downbeats": []}',
    '{"contract": 1, "duration": 1.0, "chords": [], "beats": [0.5, "1.0"], "downbeats": []}',
    '{"contract": 1, "duration": 1.0, "chords": [], "beats": [], "downbeats": null}',
    '{"contract": 1, "duration": 1.0, "chords": [], "beats": [], "downbeats": [[1.0]]}',
    '{"contract": 1, "duration": 1.0, "chords": [], "beats": []}',
    '{"contract": 1, "duration": 1' + "0" * 400 + ', "chords": [], "beats": [], "downbeats": []}',
    '{"contract": 1, "duration": 1.0, "chords": [[0, -1' + "0" * 400 + ', "C"]], "beats": [], "downbeats": []}',
    '[1, 1.0, [], [], []]',
    'null',
    '"heard"',
)


def _read_heard_records() -> list[dict]:
    """read_heard over ``HEARD_TEXTS``, and over the records the hearings make: what heard_record then writes."""
    out = []
    texts = list(HEARD_TEXTS) + [_heard_text(h) for h in _hearings().values()][:4]
    for text in texts:
        try:
            heard = sheet.read_heard(json.loads(text))
        except ValueError as e:
            out.append({"fn": "read_heard", "args": [text], "err": _err(e)})
        else:
            out.append({"fn": "read_heard", "args": [text], "out": _text(_heard_text(heard))})
    return out


def _noted_kw(noted: sheet.Noted | None) -> dict | None:
    if noted is None:
        return None
    t = noted.transcript
    return {"transcript": {"lrc": t.lrc, "made_at": t.made_at} if t else None, "silent": noted.silent,
            "said": noted.said}


def _relay_case(song: Song, raw: dict, noted: sheet.Noted | None = None) -> dict:
    """relay_due of a raw over the song now, and, where it reads, relay and the raw it writes. The raw is written with
    its ``heard`` the name of the hearing it is, where it is one of ``_hearings``' (else as it is)."""
    names = {json.dumps(sheet.heard_record(h)): name for name, h in _hearings().items()}
    said = {**raw, "heard": names.get(json.dumps(raw.get("heard")), raw.get("heard"))} if "heard" in raw else raw
    kw = {"song": _song_kw(song), "raw": _raw_text(said), "noted": _noted_kw(noted)}
    out: dict = {"due": sheet.relay_due(song, raw, noted), "noted_in": _noted_kw(sheet.noted_in(raw))}
    try:
        made = sheet.relay(song, raw, noted)
    except ValueError:  # json.loads' JSONDecodeError among them: the phone's IllegalArgumentException
        out["relay"] = {"err": "ValueError"}
    else:
        out["relay"] = {**_made_out(made), "raw": _text(_raw_text(sheet.raw_of(song, made)), SHEET_WHOLE)}
    return {"fn": "relay", "kw": kw, "out": out}


def _relay_records() -> list[dict]:
    """relay_due's every reason, and None, over raws make_sheet wrote; relay over each; relays_here and
    made_by_another's cases; Timed.note's."""
    heard, kinds = _hearings(), _lyric_kinds()
    four = heard["four"]

    def song(kind, **fields):
        return _song(lyrics_status=kinds[kind][0], lyrics_json=kinds[kind][1], **fields)

    def raw(kind, *, h=four, maker=None, video=None, columns=True, **make):
        s = song(kind)
        made = sheet.make_sheet(s, h, **make)
        r = sheet.raw_of(s, made, video=Video.from_json(video) if video else None, maker=maker)
        if not columns:
            del r["columns"]  # a sheet made before its chords went at display columns
        return r

    t = _transcript(TRANSCRIPT_FOUR)
    out = []
    for before in ("none", "plain", "plain_same", "synced", "synced_far", "words", "chinese", "astral",
                   "instrumental"):
        for now in ("none", "plain", "plain_other", "synced", "synced_far", "words", "chinese", "astral",
                    "instrumental", "instrumental_record", "unreadable"):
            out.append(_relay_case(song(now), raw(before, maker=PHONE_MAKER if before == "synced" else None)))
    over_transcript = raw("none", transcript=t)
    for now in ("none", "plain", "instrumental"):
        out.append(_relay_case(song(now), over_transcript))
        out.append(_relay_case(song(now), over_transcript, sheet.Noted(_transcript(TRANSCRIPT_FOUR, "later"))))
        out.append(_relay_case(song(now), over_transcript, sheet.Noted()))
    for noted in (sheet.Noted(t), sheet.Noted(silent=True), sheet.Noted(silent=True, said=True), sheet.Noted()):
        out.append(_relay_case(song("none"), raw("none"), noted))
        out.append(_relay_case(song("instrumental"), raw("none"), noted))
    out.append(_relay_case(song("none"), raw("none", silent=True), sheet.Noted(silent=True)))
    out.append(_relay_case(song("plain"), raw("none", silent=True, said=True)))
    out.append(_relay_case(song("chinese"), raw("chinese", columns=False)))
    out.append(_relay_case(song("synced"), raw("synced", columns=False)))
    credit = merge.youtube_credit(SHEET_VIDEO["title"], SHEET_VIDEO["channel"], SHEET_VIDEO["id"])
    out.append(_relay_case(song("synced", audio_path=None),
                           raw("none", video=SHEET_VIDEO, source=credit, maker=PHONE_MAKER)))
    unnamed = raw("none", maker=PHONE_MAKER)
    unnamed["youtube"] = None  # a kept "youtube": null is no video: no member written, no credit
    out.append(_relay_case(song("synced"), unnamed))
    for name in ("corners", "seeded0", "seeded3"):
        out.append(_relay_case(song("words"), raw("none", h=heard[name], maker=COMPUTER_MAKER)))
    talk = raw("none", h=heard["talk"], maker=PHONE_MAKER)
    out.append(_relay_case(_song(lyrics_status="found", lyrics_json=kinds["aligning"][1]), talk))
    for damaged in ({"contract": 2}, {"beats": [True]}, {"duration": 10**400}):
        bad = raw("none")
        bad["heard"] = {**bad["heard"], **damaged}
        out.append(_relay_case(song("plain"), bad))
    old = raw("none")
    del old["heard"]  # made before what was heard was kept: never re-laid, though it may be due
    out.append(_relay_case(song("plain"), old))
    for audio_path, audio_mtime, autochords_mtime in ((None, None, None), ("/a.m4a", 100.0, 100.0),
                                                       ("/a.m4a", 200.0, 100.0), ("/a.m4a", 100.0, None),
                                                       ("/a.m4a", None, None), ("", 1.0, 2.0)):
        for elsewhere in (False, True):
            s = _song(audio_path=audio_path, audio_mtime=audio_mtime, autochords_mtime=autochords_mtime)
            out.append({"fn": "relays_here", "args": [_song_kw(s), elsewhere], "out": sheet.relays_here(s, elsewhere)})
    for raw_by, own in ((None, HERE_ID), (HERE_ID, HERE_ID), (PHONE_ID, HERE_ID), (PHONE_ID, None), (7, HERE_ID),
                        ("", HERE_ID), ("", None)):
        r = {} if raw_by is None else {"made_by": raw_by}
        out.append({"fn": "made_by_another", "args": [_raw_text(r), own], "out": sheet.made_by_another(r, own)})
    for shift, longer in NOTE_CASES:
        out.append({"fn": "Timed.note", "args": [shift, longer], "out": sheet.Timed("", shift, longer).note()})
    return out


def sheet_records() -> list[dict]:
    named = [{"fn": "heard", "args": [name], "out": _heard_text(h)} for name, h in _hearings().items()]
    return _once(named + _read_heard_records() + _make_records() + _relay_records())


def test_sheet_vectors():
    check(SHEET_AREA / "sheet.jsonl", jsonl(sheet_records(), corpus="autochords-sheet/sheet", made_by=MADE_BY))


# --- relay.jsonl: sheet_lyrics.relay_onto_sheets over a library ----------------------------------------------------

AUDIO_AT = 1764000000.5  # the mtime of a song's audio on this side, in relay.jsonl's library


def _kept_auto(w, song, raw: dict, text: str) -> int:
    """An auto sheet kept as auto-chords keeps one: its version (``raw``) and ``sheet (auto).txt``."""
    from test_conformance_viewer_render import _keep, _version

    vid = _version(w, song, "auto", str(song.id), "auto", raw=raw, rating=0, votes=0)
    _keep(w, song, vid, AUTO_SHEET, text)
    return vid


def _sheet_of(w, song, heard: sheet.Heard, *, maker=None, video=None, **make) -> int:
    """An auto sheet of the song as it is now (its words, its audio), made from ``heard`` by ``maker``."""
    s = get_song(w.conn, song.id)
    made = sheet.make_sheet(s, heard, **make)
    return _kept_auto(w, s, sheet.raw_of(s, made, video=Video.from_json(video) if video else None, maker=maker),
                      made.text)


def _library(w) -> list[dict]:
    """The songs and their auto sheets, then what changed since each was made; the steps."""
    from test_conformance_viewer_render import ug_sheet

    four, kinds = _hearings()["four"], _lyric_kinds()

    def song(title, **fields):
        s = add_song(w.conn, "Nobody", title, added_at=f"2026-10-{len(list_songs(w.conn)) + 1:02d}T00:00:00Z")
        if fields:
            update_song(w.conn, s.id, **fields)
        return get_song(w.conn, s.id)

    def words(s, kind):
        status, lyrics = kinds[kind]
        update_song(w.conn, s.id, lyrics_status=status, lyrics_json=lyrics)

    here = {"audio_path": "/music/Nobody/x.m4a", "audio_mtime": AUDIO_AT, "autochords_mtime": AUDIO_AT}
    credit = merge.youtube_credit(SHEET_VIDEO["title"], SHEET_VIDEO["channel"], SHEET_VIDEO["id"])
    made = {}
    # Made on the phone over no words; this side holds no audio of it: lyrics came.
    made["phone"] = song("Phone Made")
    _sheet_of(w, made["phone"], four, maker=PHONE_MAKER)
    # Made on the phone from a video's audio; timed lyrics came.
    made["phone_video"] = song("From A Video")
    _sheet_of(w, made["phone_video"], four, maker=PHONE_MAKER, video=SHEET_VIDEO, source=credit)
    # Made here from the audio this side holds now (no maker named: an older sheet of this side's); other words.
    made["here"] = song("Made Here", **here)
    words(made["here"], "plain")
    _sheet_of(w, made["here"], four, source=PURCHASE)
    # Made here from audio since replaced: the models' to make again, never a re-lay.
    made["new_audio"] = song("New Audio", **{**here, "audio_mtime": AUDIO_AT + 60})
    _sheet_of(w, made["new_audio"], four, maker=COMPUTER_MAKER)
    # Made on the phone; this side holds other audio of it: re-laid all the same (its own heard).
    made["elsewhere"] = song("Made Elsewhere", **{**here, "autochords_mtime": None})
    _sheet_of(w, made["elsewhere"], _hearings()["corners"], maker=PHONE_MAKER)
    # What was heard can't be read (a newer contract): left as it is.
    made["unread"] = song("Unread")
    vid = _sheet_of(w, made["unread"], four, maker=PHONE_MAKER)
    from caracole.versions import get_version, set_raw

    raw = get_version(w.conn, vid).raw
    set_raw(w.conn, vid, {**raw, "heard": {**raw["heard"], "contract": 2}})
    # Ignored; in [ignore]; beside a human sheet: none re-laid.
    made["ignored"] = song("Ignored", status="ignored")
    _sheet_of(w, made["ignored"], four)
    made["ignore"] = song("In Ignore")
    _sheet_of(w, made["ignore"], four, maker=PHONE_MAKER)
    w.overrides('[ignore]\nsongs = ["Nobody - In Ignore"]\n')
    made["human"] = song("Beside A Human Sheet")
    ug_sheet(w, made["human"], "[ch]G[/ch]\nwords\n", tab=93101, tonality="G")
    _sheet_of(w, made["human"], four, maker=PHONE_MAKER)
    # A transcript, and nothing sung, noted here of this side's own audio since its sheet of none was made.
    made["transcript"] = song("Transcribed Since", **here)
    _sheet_of(w, made["transcript"], four, source=PURCHASE)
    keep_transcript(w.conn, made["transcript"], Transcript(
        lrc=TRANSCRIPT_FOUR, audio=here["audio_path"], audio_mtime=AUDIO_AT, model="whisper-large-v3",
        language="en", device="cpu", words_dropped=0, made_at="2026-11-20T01:00:00Z"))
    made["silent"] = song("Nothing Sung", **here)
    _sheet_of(w, made["silent"], four, source=PURCHASE)
    note_heard_nothing(w.conn, made["silent"], "2026-11-20T01:00:00Z", why="sung 6.2 s", by="caracole")
    # Made over a transcript on another caracole: the words it was laid with are its raw's; a site's lyrics came.
    made["over_transcript"] = song("Over A Transcript")
    _sheet_of(w, made["over_transcript"], four, maker=PHONE_MAKER, transcript=_transcript(TRANSCRIPT_FOUR))
    # Up to date: its words are the sheet's own.
    made["current"] = song("Up To Date")
    words(made["current"], "synced")
    _sheet_of(w, made["current"], four, maker=PHONE_MAKER)
    # Chinese timed lyrics on a sheet that counted characters (an older one).
    made["columns"] = song("Columns")
    words(made["columns"], "chinese")
    vid = _sheet_of(w, made["columns"], four, maker=PHONE_MAKER)
    raw = get_version(w.conn, vid).raw
    set_raw(w.conn, vid, {k: v for k, v in raw.items() if k != "columns"})
    # The owner's "it isn't sung", noted here of this side's own audio: chords only, in their words.
    made["said"] = song("Not Sung You Said", **here)
    _sheet_of(w, made["said"], four, source=PURCHASE)
    note_heard_nothing(w.conn, made["said"], "2026-11-20T01:00:00Z", why="you said so", by="you")
    # A transcript and nothing sung noted of OTHER audio than this side's now, and a transcript of no shape: none
    # is the song's own audio's, so neither sheet is due.
    other = {"audio": here["audio_path"], "audio_mtime": AUDIO_AT + 1.0}
    made["other_transcript"] = song("Transcript Of Other Audio", **here)
    _sheet_of(w, made["other_transcript"], four)
    kv_set_json(w.conn, f"transcript:{made['other_transcript'].id}", {
        "lrc": TRANSCRIPT_FOUR, **other, "model": "whisper-large-v3", "language": "en", "device": "cpu",
        "words_dropped": 0, "made_at": "2026-11-20T01:00:00Z"})
    made["other_silence"] = song("Silence Of Other Audio", **here)
    _sheet_of(w, made["other_silence"], four)
    kv_set_json(w.conn, f"transcribe:none:{made['other_silence'].id}",
                {**other, "at": "2026-11-20T01:00:00Z", "why": "sung 6.2 s", "by": "you"})
    # A purchase heard here, then the same bytes given as an upload, whose kept name holds their digest: its
    # transcript follows them (transcript.py ``of_audio``, by the name alone: no file read), so the sheet of none is
    # laid out over it; a transcript of another upload's bytes is other audio's.
    given = {"audio_path": "/state/audio/1-0123456789abcdef.m4a", "audio_mtime": AUDIO_AT, "autochords_mtime": AUDIO_AT}
    heard_then = {"lrc": TRANSCRIPT_FOUR, "audio": here["audio_path"], "audio_mtime": AUDIO_AT - 60.0,
                  "audio_size": 5, "model": "whisper-large-v3", "language": "en", "device": "cpu", "words_dropped": 0,
                  "made_at": "2026-11-20T01:00:00Z"}
    made["given_same"] = song("Given The Bytes Heard", **given)
    _sheet_of(w, made["given_same"], four, source=PURCHASE)
    kv_set_json(w.conn, f"transcript:{made['given_same'].id}",
                {**heard_then, "audio_sha256": "0123456789abcdef" + "5a" * 24})
    made["given_other"] = song("Given Other Bytes", **given)
    _sheet_of(w, made["given_other"], four, source=PURCHASE)
    kv_set_json(w.conn, f"transcript:{made['given_other'].id}",
                {**heard_then, "audio_sha256": "fedcba9876543210" + "5a" * 24})
    kv_set_json(w.conn, f"transcribe:none:{made['given_other'].id}",
                {"audio": here["audio_path"], "audio_mtime": AUDIO_AT - 60.0, "audio_size": 5,
                 "audio_sha256": "fedcba9876543210", "at": "2026-11-20T01:00:00Z", "why": "sung 6.2 s",
                 "by": "caracole"})
    made["bad_transcript"] = song("Transcript Of No Shape", **here)
    _sheet_of(w, made["bad_transcript"], four)
    kv_set_json(w.conn, f"transcript:{made['bad_transcript'].id}", {
        "lrc": TRANSCRIPT_FOUR, "audio": here["audio_path"], "audio_mtime": AUDIO_AT, "model": "whisper-large-v3",
        "language": "en", "device": "cpu", "words_dropped": "none", "made_at": "2026-11-20T01:00:00Z"})
    # A sheet that keeps no heard (made before it was kept): the candidates' query passes it over.
    made["no_heard"] = song("Heard Not Kept")
    vid = _sheet_of(w, made["no_heard"], four, maker=PHONE_MAKER)
    raw = get_version(w.conn, vid).raw
    set_raw(w.conn, vid, {k: v for k, v in raw.items() if k != "heard"})
    # A sheet over timed lyrics, and then a site's word that the song is instrumental.
    made["instrumental"] = song("Instrumental Since")
    words(made["instrumental"], "synced")
    _sheet_of(w, made["instrumental"], four, maker=PHONE_MAKER)
    # Lyrics the sheet half can't read (a stamp's minute past a float): a bug laying it out, the song's alone.
    made["bug"] = song("Unlaid Bug")
    _sheet_of(w, made["bug"], four, maker=PHONE_MAKER)
    # Then the words that came since each was made.
    update_song(w.conn, made["instrumental"].id, lyrics_status="instrumental", lyrics_json=None)
    update_song(w.conn, made["bug"].id, lyrics_status="found", lyrics_json=_lyrics(
        "a minute past a float", "[" + "9" * 400 + ":01.00]a minute past a float\n", duration=10.0))
    words(made["no_heard"], "plain")
    for name, kind in (("phone", "synced"), ("phone_video", "words"), ("here", "plain_other"),
                       ("new_audio", "plain"), ("elsewhere", "astral"), ("unread", "plain"), ("ignored", "plain"),
                       ("ignore", "plain"), ("human", "plain"), ("over_transcript", "plain")):
        words(made[name], kind)
    w.conn.execute("INSERT OR REPLACE INTO kv (key, value) VALUES ('sync:id', ?)", (HERE_ID,))
    return [{"relay": [made["phone"].id, made["new_audio"].id, made["ignore"].id]}, {"relay": None},
            {"relay": None}]


def _relay_out(w, done, errors: list[str]) -> dict:
    """A step's songs re-laid, those whose re-lay failed (``errors``' songs, by id), the files, raws, units and
    info.json."""
    from test_conformance_viewer_render import _out

    out = _out(w, phone_render.PhoneRendered(done, []))
    raws = {str(vid): text for vid, text in w.conn.execute("SELECT id, raw FROM versions ORDER BY id")}
    failed = [s.id for s in list_songs(w.conn) if any(e.startswith(f"{s.display}: ") for e in errors)]
    return {"relaid": [s.id for s in done], "failed": sorted(failed), "files": out["files"], "raws": raws,
            "units": out["units"], "info": out["info"]}


def relay_records(root) -> list[dict]:
    from test_conformance_viewer_render import World, _settle

    w = World(root / "relay")
    try:
        steps = _library(w)
        _settle(w)
        fixture = [r for r in dump_fixture(w.conn, w.cfg.library_dir, sync_id=True) if "file" not in r or "/" in r["file"]]
        outs = []
        for step in steps:
            overrides = load_overrides(w.cfg.overrides_file)
            errors: list[str] = []
            done = relay_onto_sheets(w.conn, w.cfg, overrides, only=step["relay"], errors=errors)
            outs.append(_relay_out(w, done, errors))
        return [{"fn": "relay_onto_sheets", "case": "library", "args": [fixture, steps], "out": outs}]
    finally:
        w.close()


def test_relay_vectors(tmp_path):
    check(SHEET_AREA / "relay.jsonl", jsonl(relay_records(tmp_path), corpus="autochords-sheet/relay",
                                           made_by=MADE_BY))
