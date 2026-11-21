# Lyrics transcribed from a YouTube song's audio: the measurements (Task 14)

Measured 2026-11-21 on the branch `feat/transcribed-lyrics`. Numbers, settings and positions only: no song's lyrics
are kept here (the repo is public). The scripts, their raw output, the songs' audio and stems and the scratch
libraries are outside the repo, in `~/Projects/caracole-spikes/2026-11-20-transcribed-lyrics/` (`spike/measure.py`,
`spike/tune.py`, `out/measure/`, `out/e2e/`).

**Machine**: RTX 5090 Laptop GPU (24 GB, driver 615.78.08), 24 cores. `nix develop .#autochords-cuda`: torch-bin
2.13.0+cu130, openai-whisper 20250625, librosa 1.0.0, nixpkgs' wgpu demucs-rs 0.3.4. **GPU load**: a game (Slay the
Spire 2) stayed resident on the GPU throughout, 1.2 GB of memory and idle: nvidia-smi read 0 % before every timing
below; during a job the GPU peaked at 100 % and averaged 21-23 %, all of it the job's own.

## The guard: what was measured

### The songs

| Song | Length | What it tests |
|---|---|---|
| the example (Luke Nickle - I translated North Korean pop into American) | 149 s | all words kept, none in the 89.6-100.8 s break, WER against the spike's `gpu-mix.json` |
| 孟维来 - 野人 | 198 s | the credit (作词 作曲 李宗盛) over the intro and "请不吝点赞订阅" over the end dropped; CER and line starts against LRCLIB (record 14196560, and the timed record) |
| Nick Cani - Vikingos veganos (live) | 222 s | the 0-27 s spoken intro marked unsung |
| an instrumental: the example minus its vocal stem | 149 s | no invented word kept |
| sparse vocals: the instrumental with the vocal stem added back over one verse (48.9-68.9 s, 50 ms fades) | 149 s, 20 s sung | no invented word kept outside the verse |
| a real instrumental (extra): 180 s of an orchestral "study music" video, no voice | 180 s | no invented word kept |

- The owner's library gave neither an instrumental nor a sparse song: from this account, the service's database and
  its YouTube audio (`/var/lib/caracole/state`, `cache`) can't be read (the `caracole` group reaches the library
  folder only, which holds no audio). So the two were made from the example with demucs-rs (HTDemucs, all four
  stems, whose sum leaves a residual 33 dB under the mix), scaled by 0.74 so that nothing clips. The extra
  instrumental is 10:00-13:00 of a file in `~/Music` (caracole's default `music_dir`), copied. Nothing was
  downloaded.
- Each song went through the branch's own pieces, in the cuda shell: `separate.frame_db` on the mix,
  `DemucsSeparator.vocals`, `frame_db` on the stem, `words.sung_spans` (for the language's first 30 s of singing),
  `WhisperTranscriber.hear` on CUDA. Every word Whisper heard was kept, before the guard, with both loudness tracks;
  `tune.py` then replays `sung_spans`, `guard`, `lines_of` and `to_lrc` at any pair of thresholds without a model.

### The yardsticks

- **WER**: word-level edit distance over lowercased words, punctuation stripped, divided by the reference's words.
- **CER**: character-level edit distance over the CJK characters alone, both texts in Simplified (OpenCC `t2s`),
  divided by the reference's characters. On the spike's own `out/yeren.json` it gives 9.92 %, the spec's 9.9 %.
- **Line starts**: each line of the transcript's LRC to the nearest line start of LRCLIB's timed record, the signed
  error's median over those within 5 s. On the spike's own `out/yeren.lrc` it gives -0.19 s, the spec's "median
  0.19 s early". The other way round (each LRCLIB line to our nearest line) is recorded too.
- **The break**: no word whose middle lies in 89.6-100.8 s. The first word after the break, 100.52-101.32 s, sung
  and in `gpu-mix.json` too, reaches 0.28 s into it: words overlapping it are counted apart.

### What Whisper heard (the same at every threshold)

| Song | Language (p) | Words heard | Whisper on GPU | Separation |
|---|---|---|---|---|
| the example | en 0.974 | 242, WER 0.0 % against `gpu-mix.json` (word for word the spike's) | 27.1 s | 94.3 s (burn's autotune cache cold) |
| 野人 | zh 0.936 | 240 (CER 18.2 % before the guard) | 32.5 s | 44.6 s |
| Vikingos veganos | es 0.903 | 269 | 41.2 s | 61.8 s |
| the instrumental | pt 0.247 | 12, all invented | 10.6 s | 39.0 s |
| sparse vocals | en 0.982 (first sung 50.4 s) | 49: 43 in the verse, 6 outside | 11.8 s | 43.3 s |
| the real instrumental | en 0.444 | 12, all invented | 11.5 s | 45.8 s |

The language detected on each sung song was the spike's (en, zh, es); at 10 and at 12 dB the guard's first span
starts at the same frame (9.85 s, 25.35 s, 8.3 s, 50.35 s), so the language is heard on the same 30 s.

### Against the targets: before (10 dB, 40 dB) and after (12 dB, 40 dB)

| Song | Target | `STEM_WITHIN_DB` 10, `FLOOR_DB` 40 (before) | 12, 40 (after) |
|---|---|---|---|
| the example | every word kept | 242 of 242, 0 dropped | 242 of 242, 0 dropped |
| | none in 89.6-100.8 s | 0 (1 overlapping: the sung word at 100.52 s); no sung frame in the break | the same |
| | WER ≤ 10 % against `gpu-mix.json` | 0.0 % | 0.0 % |
| | (sung spans) | 43 spans, 114.5 s of 149.5 s | 39 spans, 116.2 s |
| 野人 | the credit and "请不吝点赞订阅" dropped | dropped: 20 characters, 11 in 0.0-5.8 s and at 24.2 s (the credit, twice), 9 in 195.3-198.1 s (the outro); the spike's same 20 | the same |
| | CER ≤ 9.9 % | 9.92 % (the spike's 0.0992, said 9.9 %) | 9.92 % |
| | median line start within 0.19 s | -0.19 s (33 of our 33 lines within 5 s, 28 within 0.6 s, mean error 0.37 s); LRCLIB's 38 lines to ours: median -0.135 s | the same |
| Vikingos veganos | the 0-27 s intro unsung | **missed**: 18.7 s of 0-27 s sung (from 8.3 s) | **missed**: 18.7 s |
| | (sung spans) | 206.5 s of 222.3 s, 0 of 269 words dropped | 206.7 s, 0 dropped |
| the instrumental | no invented word kept | 0 spans, 0 of 12 kept | 0 spans, 0 of 12 kept |
| sparse vocals | none kept outside the verse | 0 kept outside (6 dropped: at 96.3, 97.7, 128.4, 128.7 and twice 149.3 s); 43 of 43 in the verse kept | the same, 2 spans, 18.7 s, all inside the verse |
| the real instrumental | no invented word kept | 0 spans, 0 of 12 kept | 0 spans, 0 of 12 kept |

With no sung span, as on both instrumentals, the job doesn't run Whisper at all ("no singing heard").

### How far each target is from its edge

`STEM_WITHIN_DB` swept in 0.5 dB steps (FLOOR 40), `FLOOR_DB` swept (WITHIN 10), and a grid of 17 × 10 pairs
(`out/measure/guard-grid.txt`, `margins.txt`):

| Edge | Where |
|---|---|
| the example drops a word (one at 27.38 s, a phrase's last) | `STEM_WITHIN_DB` < 9.0 (8.5: 1 dropped; 5.5: 9; 2.5: 83); `FLOOR_DB` < 15 (12: 3 dropped; 5: 106) |
| a made-up word is kept | the real instrumental from `STEM_WITHIN_DB` 26.5 (1 word); 野人's credits from `FLOOR_DB` 100 (5 characters); the instrumental and the sparse song: none up to 40 dB |
| 野人's CER or line starts move | only below 4 dB |
| Task 4's tests | `STEM_WITHIN_DB` in [3, 15) (a stem 3 dB under is sung, 15 dB under is bleed), `FLOOR_DB` < 60 |

**Vikingos veganos's intro can't be marked unsung by these two thresholds.** At every setting that keeps the
example's words (1-40 dB × 5-100 dB swept), 18.4 s or more of 0-27 s is sung; the least anywhere, 3.3 s (1 dB, a
5 dB floor), costs the example 230 of its 242 words. Its 8-27 s are the performer talking to the audience (YouTube's
captions have the words), a voice the stem holds as it holds the singing: the stem sits 1.4-3.0 dB under the mix
there (median, by stretch), 1.2-2.8 dB in the sung verses, and the mix is as loud as in the verses (7-10 dB under
its loudest). Only the first 8 s, with no voice (the stem 57 dB under), is unsung. A stem-to-mix rule tells a voice
from bleed, not speech from singing. What it costs here: Whisper heard 1 word in the intro (20.4-21.8 s, where a
voice is), kept.

### The constants chosen

`STEM_WITHIN_DB = 12.0` (was 10.0), `FLOOR_DB = 40.0` (unchanged).

- Every target but the Vikingos intro holds anywhere from 9 to 26 dB; 10 dB sat 1 dB from the example losing a sung
  word (the hard floor). 12 dB keeps 3 dB there, 14 dB from the first made-up word kept, and 3 dB inside Task 4's
  "15 dB under is bleed".
- `FLOOR_DB` 40 is 25 dB above the example's edge (15) and far below the credits' (100); nothing moved it.
- Whisper's `hallucination_silence_threshold` wasn't added: the guard alone kept no invented word on any song.
- A test pins the margin: tests/test_autochords_words.py `test_a_soft_line_11_db_under_the_mix_is_still_sung`.

## The end-to-end run

A scratch library (`out/e2e/lib`, its own caracole.toml with `data_dir` and `music_dir` there): the example as a
YouTube song every site missed, seeded as tests/test_transcribe_job.py's `offered` does (the song, its audio in the
cache's `youtube/`, lyrics missing with LRCLIB asked, the youtube record, Megalobiz's and AZLyrics' stamps). Then,
from the worktree, `$S` the spike folder:

    CARACOLE_TORCH_CUDA=1 nix develop .#autochords-cuda -c python -I $S/spike/timed.py $S/out/e2e/cold -- \
      caracole --config $S/out/e2e/lib/caracole.toml transcribe \
      --song "Luke Nickle - I translated North Korean pop into American" --progress

(`timed.py` stamps each output line and samples nvidia-smi every 0.5 s.) **Cold** is a fresh library (its cache
folder empty: burn's autotune cache and Triton's); **warm** is the same library again after the song's audio was
taken again (copied over its file, a new mtime: the transcript is another audio's and the song is offered again).
The instrumented runs are the same command through `spike/instrumented.py`, which wraps the models' calls with
timers and changes nothing else. The Whisper model file was in the page cache in every run: a first load from disk
takes about 100 s more (the spike's 103 s).

| Stage | cold | cold, instrumented | warm | warm, instrumented |
|---|---|---|---|---|
| song | 0.0 s | 0.0 s | 0.0 s | 0.0 s |
| vocals | 130.9 s | 160.0 s | 81.7 s | 86.8 s |
| words | 39.8 s | 42.8 s | 38.9 s | 40.0 s |
| chords | 4.7 s | 5.6 s | 4.4 s | 4.8 s |
| pdf | 1.1 s | 1.6 s | 0.2 s (up to date) | 0.3 s (up to date) |
| pages | 0.1 s | 0.1 s | 0.1 s | 0.1 s |
| **Done in** | **176.7 s** | **210.1 s** | **125.4 s** | **132.0 s** |
| GPU before / during | 0 % / max 100 %, mean 22.5 % | 0 % / 100 %, 21.0 % | 0 % / 100 %, 22.5 % | 0 % / 100 %, 22.6 % |

Inside the stages (instrumented, cold / warm):

| Piece | cold | warm |
|---|---|---|
| demucs-rs on the 2 s test tone (the separator's tone check) | 108.8 s (autotune cold) | 37.3 s |
| the mix's loudness | 0.2 s | 0.2 s |
| demucs-rs on the song | 50.5 s | 48.8 s |
| the stem's loudness | 0.2 s | 0.2 s |
| Whisper's import and load (3 GB, from the page cache) | about 10 s | about 9 s (load 8.1 s) |
| Whisper on the test tone (the tone check) | 3.9 s | 3.7 s |
| Whisper on the song (language 0.15 s, then the mix) | 29.0 s | 27.2 s |
| BTC and beat_this on the tone | 1.7 s | 1.6 s |

- **The result**: every run ended `Chords: chords over the transcribed lyrics.`, exit 0, `Words: 242 words in 40
  lines (en), 0 dropped.`, `Vocals: sung from 9.8 s, 39 stretches.`; the transcript (kv, device `cuda`) word for word
  `gpu-mix.json` (WER 0.0 %), no word in the break (the one word starting in it, at 100.52 s, is `gpu-mix.json`'s
  sung word), one empty LRC line at its start; the song's lyrics still missing and
  no `lyrics_json`; the version's raw `lyrics_source` "transcript", `lyrics` "synced", `transcript` the kept LRC.
- **The NOTE**: `sheet (auto).txt` says `Lyrics transcribed from the audio (Whisper), unverified` on its line 4,
  after the video's credit; the PDF and `sheet (auto).html` made.
- **`sung`**: `sheet (auto).html`'s data has `sung`, 41 entries (the first at 9.24 s, the last at 139.46 s).
- **About a minute?** No. **The warm GPU job takes about 125-132 s, twice the offer's "about a minute"**; cold, 177-210
  s. Where the warm time goes: two demucs-rs runs of about 30 s fixed cost each (a 2-second tone takes 28-37 s;
  the shader cache is not it: a kept `XDG_CACHE_HOME` ran the tone in 27.6-30.8 s and the song in 41.6-42.1 s
  against 30.0 s and 43.2 s fresh, `out/measure/demucs-cache.txt`), so **the separator's tone check alone is 37 s
  of the warm job's 132 s** (instrumented); Whisper's stage about 40 s, its tone check 3.7 s of it. The offer's
  wording is unchanged.
- **Triton's fallback**: Whisper warns `Failed to launch Triton kernels, likely due to missing CUDA toolkit; falling
  back to a slower median kernel implementation...` and `... DTW implementation...` on every 30 s window (12 times on
  the example, 2 more on the tone): Triton's launcher can't link `libcuda.so.1` (`ld: cannot find -l:libcuda.so.1`,
  it isn't on the linker's path; `TRITON_LIBCUDA_PATH` doesn't help), and each window compiles and fails again.
  With `LIBRARY_PATH=/run/opengl-driver/lib` the kernels launch and Whisper took 25.1 s, then 22.0 s,
  against 28.9 s and 27.8 s with the fallback (`out/measure/triton-cost.txt`): **the fallback costs about 4-6 s a
  song**. The words are the same either way (242). (The follow-up below finds the cost is the failed builds, not the
  slower kernels.)

## The separator's exit, measured

26 runs of the wgpu demucs-rs from Python in this task: 19 exited 0 (2 of those seen printing `NVVM compilation
failed: 3` after `Done!`), 6 died by SIGSEGV after `Done!` (taken, as separate.py does since e92b9e8f), and **1
died by SIGABRT with glibc's `double free or corruption (out)` as its last line, after `Done!` with the stem
written** (the instrumental's first separation). separate.py took only a `Done!` that was the last line, so that run
failed as "the separator can't run here (double free or corruption (out))", and a job would have too. Fixed
(`fix(autochords): a demucs-rs that says more or aborts after Done! has separated the vocals too`): a death by a
signal once `Done!` was said, with vocals.wav written, has separated the vocals; a signal before `Done!`, a positive
exit and a missing stem still fail. Test: tests/test_autochords_separate.py
`test_a_demucs_that_aborts_with_more_said_after_done_has_separated_them_too`.

## Not measured here

- The spec's "a few songs of the library with LRCLIB timed lyrics and audio": the library's database and audio
  can't be read from this account (above); 野人 is the one song with a reference.
- The job inside caracole-web's unit, on the GPU and with the GPU hidden, and the served page lighting the sheet's
  lines on the computer and, after a sync, on the phone: the owner's, after the switch (Task 14, Step 4).

## Follow-up: the job's time

Three changes after the measurements above, then the example's job timed again in the same scratch libraries:

- the job runs demucs-rs on the song alone, with no test tone first (its failure on the song is the setup's, as on a
  tone, and records nothing); Whisper's and auto-chords' tone checks stay;
- before importing Whisper, caracole sets `LIBRARY_PATH` to `/run/opengl-driver/lib` when the driver's
  `libcuda.so.1` is there and the variable is unset. triton-bin 3.7.1 reads no `TRITON_LIBCUDA_PATH` (its knob is
  defined, nothing reads it; nixpkgs' `libcuda_dirs` returns `/run/opengl-driver/lib/libcuda.so` as a string, which
  `library_dirs` spreads into one-character folders), so the launcher's gcc found no libcuda;
- the offer on a GPU says "a couple of minutes" (below), the CPU's "up to half an hour" unchanged.

| Stage | warm, run 1 | warm, run 2 | cold (a fresh library) |
|---|---|---|---|
| song | 0.0 s | 0.0 s | 0.0 s |
| vocals | 45.2 s | 50.2 s | 110.2 s (burn's autotune cold, on the song now) |
| words | 32.7 s | 31.6 s | 33.1 s |
| chords | 4.4 s | 4.6 s | 5.0 s |
| pdf | 0.2 s (up to date) | 0.2 s (up to date) | 1.2 s |
| pages | 0.1 s | 0.1 s | 0.1 s |
| **Done in** | **82.6 s** | **86.7 s** | **149.7 s** |
| GPU before / during | 0 % / max 100 %, mean 35.0 % | 0 % / 100 %, 31.8 % | 0 % / 100 %, 24.1 % |

(The game stayed resident, 1.3 GB, idle.) Against the runs above: warm 125.4 s -> 82.6-86.7 s, cold 176.7 s ->
149.7 s. Every run ended `chords over the transcribed lyrics`, 242 words in 40 lines, 0 dropped, WER 0.0 % against
`gpu-mix.json`, the NOTE on line 4, `sung` with 41 entries, and no Triton warning.

- **The offer**: warm T = 82.6-86.7 s, over 75 s, so "about a minute" became **"a couple of minutes"**.
- **Triton**, Whisper alone on the example (`triton_cost.py`, two hears a process): with `LIBRARY_PATH` set by
  caracole, 21.8 s then 19.4 s and no fallback; as before, 28.9 s then 27.8 s, 12 fallback warnings each; and with
  no C compiler on PATH at all, 21.7 s then 19.8 s, 12 fallback warnings each (`out/measure/triton-no-compiler.txt`).
  So the 4-6 s were Triton's failed gcc runs (two a 30 s window), not the slower kernels. caracole-web's unit has no
  C compiler on its PATH (nix/module.nix sets no `path`; the package's wrapper adds chordpro, yt-dlp and demucs-rs;
  read, not run in the unit), so there Whisper should fall back as before, quickly, saying so in the journal; the
  setting saves the time wherever gcc is found, as in the shells.
