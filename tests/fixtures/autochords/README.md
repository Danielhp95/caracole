# tests/fixtures/autochords: synthesized clips with known chords and beats

Made here by tests/helpers/synth_music.py, `render(spec, seed)`, from the specs below: no recording, no download,
no one else's music. CC0 1.0: dedicated to the public domain.

Each is a 16-bit mono WAV at 22,050 Hz, the rate BTC and beat_this read, so a reader needs no decoder or
resampler. A bar holds its chord's tones (octave 4, three harmonics), its root in the bass (octave 2, each beat), a
kick each beat (louder on the downbeat), a snare on the even beats and a hi-hat each eighth; "N" is a bar of
silence. tests/test_conformance_autochords_models.py checks that each file is what `render` makes, and writes what
the computer's models make of them into tests/conformance/vectors/autochords/.

| File | Length | Seed | Silence first | Parts, played in order (a chord a bar) |
|---|---|---|---|---|
| `steady.wav` | 12 s | 1 | 0 s | 120 BPM, 4 beats a bar: C G Am F C G |
| `tempo-change.wav` | 12 s | 2 | 0 s | 90 BPM, 4 beats a bar: Am Dm E7; 140 BPM, 4 beats a bar: Am F G7 |
| `silence.wav` | 10.05 s | 3 | 1.5 s | 100 BPM, 4 beats a bar: D N Bm G |
| `long.wav` | 40 s | 4 | 0 s | 110 BPM, 4 beats a bar: Cmaj7 Am7 Dm7 G7 Cmaj7 Am7 Dm7 G7 Cmaj7 Am7 Dm7 G7; 110 BPM, 3 beats a bar: Esus4 E Am Bdim C Dm G C; 110 BPM, 4 beats a bar: F C |

- `steady`: 120 BPM in 4, a chord a bar: 12 s, a window and a fifth of BTC's.
- `tempo-change`: 90 BPM for three bars, then 140 BPM, its last bar cut at 12 s.
- `silence`: 1.5 s of silence, then a bar of silence between chords; 10.05 s, a tail shorter than a CQT hop.
- `long`: sevenths in 4, then triads in 3, its last bar cut; 40 s, four whole windows of BTC's, two chunks of beat_this's.

Regenerate them (never by hand) with
`CARACOLE_CORPUS=write nix develop -c pytest -q -n 0 tests/test_conformance_autochords_models.py`.
