"""Music synthesized here, with known chords and beats: the auto-chords clips the corpus commits
(tests/fixtures/autochords/, CC0: made by this module, no recording, no download).

- ``render(spec, seed) -> bytes``: a 16-bit mono WAV at 22,050 Hz (``RATE``), the rate BTC and beat_this read, so a
  reader needs no resampler. Pure Python (``math``, ``random`` seeded, ``wave``): the same bytes in every process and
  on every run, with no NumPy whose SIMD sine could move a last bit.
- ``Spec``: the clip's length, the silence before its first part, and its ``Part``s, played one after another; a
  part is a tempo, the beats of a bar and a chord a bar ("N" a bar of silence, drums and all). What comes after the
  parts, up to the clip's length, is silence; a part the length cuts is cut.
- ``known(spec)``: the chords as played (``[start, end, name]``, silence "N") and the beats and downbeats, in seconds.
- ``CLIPS``: the committed clips, each a ``Clip(name, spec, seed, about)``; ``readme()``, their README
  (tests/fixtures/autochords/README.md), a row a clip's spec (``described``); ``python -m tests.helpers.synth_music
  DIR`` writes them.

The sound, a bar at a time: the chord's tones (octave 4, three harmonics, struck each bar and fading), its root in the
bass (octave 2, plucked each beat), a kick on every beat (louder on the downbeat), a snare on the bar's even beats and
a hi-hat on every eighth, the noises drawn from ``random.Random(seed)``.
"""

from __future__ import annotations

import io
import math
import random
import sys
import wave
from dataclasses import dataclass
from pathlib import Path

RATE = 22050

_PITCHES = {"C": 0, "C#": 1, "Db": 1, "D": 2, "D#": 3, "Eb": 3, "E": 4, "F": 5, "F#": 6, "Gb": 6, "G": 7, "G#": 8,
            "Ab": 8, "A": 9, "A#": 10, "Bb": 10, "B": 11}
_QUALITIES = {"": (0, 4, 7), "m": (0, 3, 7), "7": (0, 4, 7, 10), "maj7": (0, 4, 7, 11), "m7": (0, 3, 7, 10),
              "dim": (0, 3, 6), "sus4": (0, 5, 7)}
_TABLE = 4096  # a period of the chord tones' timbre, looked up with linear interpolation


@dataclass(frozen=True)
class Part:
    bpm: float
    bars: tuple[str, ...]
    beats: int = 4


@dataclass(frozen=True)
class Spec:
    seconds: float
    parts: tuple[Part, ...]
    lead: float = 0.0


@dataclass(frozen=True)
class Clip:
    name: str
    spec: Spec
    seed: int
    about: str


def chord_tones(name: str) -> tuple[int, ...]:
    """The pitch classes above the root's (the root's first) of a chord name: "Am7" → (9, 0, 4, 7)."""
    root = name[:2] if name[1:2] in ("#", "b") else name[:1]
    quality = name[len(root):]
    if root not in _PITCHES or quality not in _QUALITIES:
        raise ValueError(f"no chord {name!r} here")
    return tuple((_PITCHES[root] + step) % 12 for step in _QUALITIES[quality])


def _bars(spec: Spec):
    """Each bar as ``(start, seconds, beats, chord)``, cut at the clip's length."""
    t = spec.lead
    for part in spec.parts:
        beat = 60.0 / part.bpm
        for chord in part.bars:
            if t >= spec.seconds:
                return
            yield t, beat * part.beats, part.beats, chord
            t += beat * part.beats


def known(spec: Spec) -> tuple[list[list], list[float], list[float]]:
    """The chords as played (silence "N", runs of one chord joined), the beats and the downbeats, in seconds rounded
    to the millisecond; a beat at or past the clip's end is none."""
    chords: list[list] = []
    beats: list[float] = []
    downbeats: list[float] = []

    def played(start: float, end: float, name: str) -> None:
        if end <= start:
            return
        if chords and chords[-1][2] == name and chords[-1][1] == round(start, 3):
            chords[-1][1] = round(end, 3)
        else:
            chords.append([round(start, 3), round(end, 3), name])

    t = 0.0
    for start, seconds, n, chord in _bars(spec):
        played(t, start, "N")
        end = min(start + seconds, spec.seconds)
        played(start, end, chord)
        t = end
        if chord != "N":
            for k in range(n):
                at = start + k * seconds / n
                if at < spec.seconds:
                    beats.append(round(at, 3))
                    if k == 0:
                        downbeats.append(round(at, 3))
    played(t, spec.seconds, "N")
    return chords, beats, downbeats


def _timbre() -> list[float]:
    table = [sum(a * math.sin(2 * math.pi * h * i / _TABLE) for h, a in ((1, 1.0), (2, 0.5), (3, 0.25)))
             for i in range(_TABLE)]
    return table + table[:1]


def _hz(midi: int) -> float:
    return 440.0 * 2.0 ** ((midi - 69) / 12)


def render(spec: Spec, seed: int) -> bytes:
    """The clip as a 16-bit mono WAV at ``RATE`` Hz: the same bytes for the same spec and seed, everywhere."""
    rng = random.Random(seed)
    n = round(spec.seconds * RATE)
    y = [0.0] * n
    table = _timbre()
    sin, exp = math.sin, math.exp

    def add(at: int, length: int, sample) -> None:
        for i in range(max(0, -at), min(length, n - at)):
            y[at + i] += sample(i)

    for start, seconds, beats, chord in _bars(spec):
        if chord == "N":
            continue
        first = round(start * RATE)
        length = round(seconds * RATE)
        beat = length / beats
        tones = chord_tones(chord)
        for pc in tones:
            step = _hz(60 + pc) * _TABLE / RATE

            def tone(i, step=step):
                phase = (i * step) % _TABLE
                k = int(phase)
                envelope = min(1.0, i / 220.0) * exp(-i / (2.5 * RATE))
                return 0.07 * envelope * (table[k] + (phase - k) * (table[k + 1] - table[k]))

            add(first, length, tone)
        bass = 2 * math.pi * _hz(36 + tones[0]) / RATE
        for k in range(beats):
            at = first + round(k * beat)
            add(at, round(beat), lambda i: 0.18 * min(1.0, i / 110.0) * exp(-i / (0.25 * RATE)) * sin(bass * i))
            gain = 0.5 if k == 0 else 0.3

            def kick(i, gain=gain):
                phase = 2 * math.pi * (45.0 * i / RATE + 65.0 * 0.03 * (1 - exp(-i / (0.03 * RATE))))
                return gain * exp(-i / (0.06 * RATE)) * sin(phase)

            add(at, round(0.25 * RATE), kick)
            if k % 2:
                noise = [rng.uniform(-1.0, 1.0) for _ in range(round(0.15 * RATE))]

                def snare(i, noise=noise):
                    return exp(-i / (0.04 * RATE)) * (0.15 * noise[i] + 0.1 * sin(2 * math.pi * 190 * i / RATE))

                add(at, len(noise), snare)
            for half in (0, 1):
                hat = [rng.uniform(-1.0, 1.0) for _ in range(round(0.03 * RATE) + 1)]

                def hihat(i, hat=hat):
                    return 0.05 * exp(-i / (0.008 * RATE)) * (hat[i + 1] - hat[i])

                add(at + round(half * beat / 2), len(hat) - 1, hihat)

    out = io.BytesIO()
    with wave.open(out, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes(b"".join(max(-32768, min(32767, round(v * 32767))).to_bytes(2, "little", signed=True)
                               for v in y))
    return out.getvalue()


CLIPS = (
    Clip("steady", Spec(12.0, (Part(120.0, ("C", "G", "Am", "F", "C", "G")),)), 1,
         "120 BPM in 4, a chord a bar: 12 s, a window and a fifth of BTC's"),
    Clip("tempo-change", Spec(12.0, (Part(90.0, ("Am", "Dm", "E7")), Part(140.0, ("Am", "F", "G7")))), 2,
         "90 BPM for three bars, then 140 BPM, its last bar cut at 12 s"),
    Clip("silence", Spec(10.05, (Part(100.0, ("D", "N", "Bm", "G")),), lead=1.5), 3,
         "1.5 s of silence, then a bar of silence between chords; 10.05 s, a tail shorter than a CQT hop"),
    Clip("long", Spec(40.0, (Part(110.0, ("Cmaj7", "Am7", "Dm7", "G7") * 3),
                             Part(110.0, ("Esus4", "E", "Am", "Bdim", "C", "Dm", "G", "C"), beats=3),
                             Part(110.0, ("F", "C")))), 4,
         "sevenths in 4, then triads in 3, its last bar cut; 40 s, four whole windows of BTC's, two chunks of "
         "beat_this's"),
)


def described(clip: Clip) -> str:
    """A clip's spec in words, a Markdown table's row: its file, length, seed, lead silence and each part."""
    parts = "; ".join(f"{p.bpm:g} BPM, {p.beats} beats a bar: {' '.join(p.bars)}" for p in clip.spec.parts)
    return (f"| `{clip.name}.wav` | {clip.spec.seconds:g} s | {clip.seed} | {clip.spec.lead:g} s | {parts} |")


def readme() -> str:
    """tests/fixtures/autochords/README.md: where the clips come from, their licence, and each one's spec."""
    rows = "\n".join(described(clip) for clip in CLIPS)
    abouts = "\n".join(f"- `{clip.name}`: {clip.about}." for clip in CLIPS)
    return f"""# tests/fixtures/autochords: synthesized clips with known chords and beats

Made here by tests/helpers/synth_music.py, `render(spec, seed)`, from the specs below: no recording, no download,
no one else's music. CC0 1.0: dedicated to the public domain.

Each is a 16-bit mono WAV at 22,050 Hz, the rate BTC and beat_this read, so a reader needs no decoder or
resampler. A bar holds its chord's tones (octave 4, three harmonics), its root in the bass (octave 2, each beat), a
kick each beat (louder on the downbeat), a snare on the even beats and a hi-hat each eighth; "N" is a bar of
silence. tests/test_conformance_autochords_models.py checks that each file is what `render` makes, and writes what
the computer's models make of them into tests/conformance/vectors/autochords/.

| File | Length | Seed | Silence first | Parts, played in order (a chord a bar) |
|---|---|---|---|---|
{rows}

{abouts}

The decode gate's files, `decode*.*` (CC0 too), are steady.wav's first 6 s encoded by FFmpeg (LAME, libvorbis,
libopus, its own AAC and FLAC) in each form the computer takes, written once by `encode.sh`, which says what each one
is; tests/test_conformance_autochords_models.py writes the computer's decode of each into decode.jsonl.

Regenerate them (never by hand) in two halves: the clips and this README in the default shell,
`CARACOLE_CORPUS=write nix develop -c pytest -q -n 0 tests/test_conformance_autochords_models.py`; then, after any
clip changes, the models' outputs over them in the auto-chords shell,
`CARACOLE_CORPUS=write nix develop .#autochords -c pytest -q -n 0 -m autochords tests/test_conformance_autochords_models.py`.
"""


def main(argv: list[str]) -> int:
    """``python -m tests.helpers.synth_music DIR``: every clip of ``CLIPS`` written as ``DIR/<name>.wav``."""
    if len(argv) != 1:
        print("usage: python -m tests.helpers.synth_music DIR", file=sys.stderr)
        return 2
    folder = Path(argv[0])
    folder.mkdir(parents=True, exist_ok=True)
    for clip in CLIPS:
        (folder / f"{clip.name}.wav").write_bytes(render(clip.spec, clip.seed))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
