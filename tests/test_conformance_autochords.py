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
"""

from __future__ import annotations

import json
import random

from helpers.corpus import DATA, VECTORS, check, jsonl
from test_autochords_models import COMMON_NAMES, FRAMES, SPELLINGS, spelling_song

from caracole.autochords import ChordSegment, btc

MADE_BY = "tests/test_conformance_autochords.py"
AREA = VECTORS / "autochords"
SIZES = (25, 170)
NOT_SIZES = (0, 24, 26, 169, 171)
# Labels no BTC vocabulary has, which common_name still names as btc.py does.
OTHER_LABELS = ("C:min/b3", "G/5", "C:weird", "", ":min", "Cb", "E#:maj", "N:min", "X:7", "Bb:min7/7")
# Frame lengths at which Python's round(…, 3) and a naive half-up rounding disagree (frames records).
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
