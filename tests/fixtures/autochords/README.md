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

The decode gate's files, `decode*.*` (CC0 too), are steady.wav's first 6 s encoded by FFmpeg (LAME, libvorbis,
libopus, its own AAC and FLAC) in each form the computer takes, written once by `encode.sh`, which says what each one
is; tests/test_conformance_autochords_models.py writes the computer's decode of each into decode.jsonl. The end-to-end
gate's files, `hearing.mp3` (44.1 kHz stereo MP3) and `hearing.m4a` (48 kHz stereo AAC), are long.wav's first 20 s
encoded the same way; it writes the computer's whole hearing of each into models.jsonl.

Two of them are fragmented MP4, as yt-dlp leaves YouTube's m4a on the phone, which has no FFmpeg to remux it ("writing
DASH m4a"); FFmpeg 9.0.1 wrote them, a box dump of each:

- `decode-frag.m4a` (54,945 bytes): decode.m4a's very AAC frames (22,050 Hz mono, 64 kb/s) by `-movflags
  frag_keyframe+empty_moov+default_base_moof`: `ftyp` (M4A; iso6, iso5); an empty `moov` (`mvhd` and `mdhd` of
  duration 0; `stts`, `stsc`, `stsz` and `stco` of no entry; `mvex`/`trex`); one `moof` (`tfdt` 0, a `trun` of 131
  samples, each one's duration and size) and its `mdat`; `mfra`.
- `decode-dash.m4a` (98,838 bytes): the clip as YouTube's itag 140 is coded, AAC-LC at 128 kb/s and 44.1 kHz stereo,
  by `-movflags dash+global_sidx+frag_keyframe+empty_moov+default_base_moof -frag_duration 1000000`: `ftyp` (M4A;
  iso6, iso5, dash); the same empty `moov`; a global `sidx` (6 references); six `moof`s (a default duration of 1,024
  in each `tfhd`; `tfdt` 0, 45,056, …; 44 samples each, the last 40 with their own durations) and their `mdat`s;
  `mfra`. The closer stand-in for YouTube's: its brand, its `sidx` and its many fragments (what boxes YouTube's own
  file holds beyond those, an edit list or none, no file here shows).

Neither has an edit list (FFmpeg writes none in a fragmented file, `-use_editlist 1` or not), an iTunSMPB or an
`sgpd`/`sbgp` roll: the encoder's priming, 1,024 samples, is in no box. So FFmpeg decodes it, the fragmented file read
whole is its last frame's padding longer than its samples' durations say, and mutagen states no length of it. The
computer never holds such a file: its yt-dlp remuxes it (FixupM4a, `ffmpeg -c copy -f mp4`), whose `elst` starts at 0,
whose `mdhd` is the fragments' length (133,324 and 265,624 samples), and whose decode is the fragmented file's ended
there: encode.sh writes each remux beside it (`decode-frag-remux.m4a`, `decode-dash-remux.m4a`), and the generator
checks both against it. decode.jsonl's records of them are that decode and that length (`fragmented`). Against the
plain file of the same frames (decode.m4a, and the itag 140 clip as a plain MP4), whose edit list trims the priming,
those samples are the plain decode's 1,024 samples later.

Regenerate them (never by hand) in two halves: the clips and this README in the default shell,
`CARACOLE_CORPUS=write nix develop -c pytest -q -n 0 tests/test_conformance_autochords_models.py`; then, after any
clip changes, the models' outputs over them in the auto-chords shell,
`CARACOLE_CORPUS=write nix develop .#autochords -c pytest -q -n 0 -m autochords tests/test_conformance_autochords_models.py`.
