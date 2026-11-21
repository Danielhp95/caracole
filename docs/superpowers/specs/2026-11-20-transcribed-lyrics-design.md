# Lyrics transcribed from a YouTube song's audio

Date: 2026-11-20. The owner's ask: "For songs downloaded via youtube that lyrics could not be found. I want to try to
attempt extracting the lyrics using a sound to text model … Which will then will be used as a timed lyrics over which
to put chords over. This will serve as a fallback if no lyrics can be found. The user should be prompted if no lyrics
have been found if they want to proceed with extracting lyrics." Then: "I will also want the models to run on GPU if
available." Lines marked *(my call)* are decisions the owner didn't make and may still change.

Worked example: **Luke Nickle - I translated North Korean pop into American** (video `nlSSyPXQ2i4`, 149 s). Its live
`sheet (auto)` is a bare chord chart: LRCLIB, Megalobiz and AZLyrics have nothing (`"lyrics": "missing"`).

## Why

A song nobody has charted, taken from YouTube, gets chords from auto-chords (BTC, beat_this, merge.py), but with no
lyrics the sheet is a chart of bars, which is hard to play along to. Timed lyrics put each chord over the word sung
when it changes (merge.py's enhanced-LRC path), and the songs that come from YouTube are exactly the ones the lyrics
sites tend to lack. Machine-heard words are worse than a person's, so they are the last resort, made only when the
owner says yes.

## The owner's decisions

- **Ask first.** Transcription runs only after the owner says yes, for a song no lyrics site had lyrics for.
- **Timed lyrics are the point.** The chords go over the transcript's words.
- **Only for its own sheet.** Asked whether a transcript should count as the song's lyrics elsewhere too (the
  coverage that ranks a UG or LaCuerda sheet found later and retires the auto sheet): "Do only for its own sheet.
  The transcriptions aren't perfect on either case, but it's better than nothing for sure."
- **Lyrics sites first, always**: "Always prefer lyrics from lyric sites."
- **The sung line, on the computer and the phone**: asked whether the viewer should light the line being sung on a
  transcribed sheet, as it does over a site's timed lyrics: "Yes, on both computer and phone"
- **No editing now.** Asked what "make them …" meant: "make them editable, so I can fix the wrong words". Then: "Ignore
  the text editing. In the future I will add features for changing song lyrics, but I will want this to be more
  general than this. so ignore for now."
- **No made-up words over instrumental parts** ("Do 1, not 2"): where nobody sings, no words. **Not** chords worked
  out from a separated backing track (option 2, rejected).
- **Whisper large-v3 over the full mix.** The owner compared four sheets of the example with the same chords, and
  ranked: Whisper large-v3 on the full mix best, YouTube's auto-captions second, Whisper on separated vocals worst.
  Qwen3-ASR + Qwen3-ForcedAligner, sent after, lost to the mix too: "Mix is better, keep that one."
- **The GPU when there is one**, the CPU otherwise.
- **Approach A** (below): "A, go ahead".

## What was measured (2026-11-20, the example, in a scratch library, nothing in the repo)

| Lyrics from | Words | Time | Owner's rank |
|---|---|---|---|
| Whisper large-v3 (faster-whisper, CPU int8), full mix | 240 | 128 s CPU | 1 |
| YouTube auto-captions (`--write-auto-subs`, word-timed VTT) | 239 | none (one yt-dlp run) | 2 |
| Whisper large-v3 on HTDemucs vocals (demucs-rs) | 248 | 35 s separation (warm) + 136 s CPU | 3 |
| Qwen3-ASR-1.7B + Qwen3-ForcedAligner-0.6B, full mix | 239 | 22 s GPU | below the mix |
| Whisper large-v3 (openai-whisper, torch-bin CUDA), full mix | 242 | 15.7 s GPU (RTX 5090) | not shown; 5% of words differ from rank 1, mostly toward YouTube's ("oh so full and warm", "forever we will follow") |
| the same, only over the sung spans (`clip_timestamps`) | — | 14.2 s GPU | not shown; 11.7% differ, and worse ("though ends our hearts", "find I beg you president") |

- The same chords under every version, through caracole's own path: the transcript stored, for the spike, as `lyrics_json`
  (provider `transcribed`, enhanced LRC; the design keeps it apart instead, below), then `caracole autochords --song` and `caracole render --song` (about 15 s, CPU).
- Any two transcripts differ on 15–18% of words; there is no human reference, so the owner's ear is the judge.
- **Separation as input hurts**, and research agrees: on Jam-ALT, HTDemucs vocals took Whisper v3 from 35.5 to 48.0
  WER (arXiv 2408.06370). Using the vocal stem only to find where the singing is helps: long hallucinated runs went
  from 1.31% to 0.35% (arXiv 2506.15514).
- **Cutting the audio to the sung spans hurts the words** (short clips lose context). So the guard drops words
  after transcribing the whole mix. On the example it drops none: all 240 words of rank 1 fall inside the sung spans,
  so the owner's sheet is unchanged.
- The sung spans of the example (the stem's energy, rule below): 12 spans, 123 s of 149 s, the break 89.6–100.8 s out.

Then the design's pipeline (language detected on the stem, Whisper on the GPU over the mix, the guard) on two more
the owner chose, for languages other than English:

| Song | Language detected | Time (GPU) | What came out |
|---|---|---|---|
| Nick Cani - Vikingos veganos (`Knbhlb3ZEqU`, 222 s, live) | es 0.87 | 18 s | most lines right; "cuerpos ganos" for "sanos", "guasdazo" for "guantazo"; the spoken intro and the first sung line ("Somos los vikingos, nos gusta la destrucción", 27.7 s) missed, which YouTube's Spanish captions have; the guard dropped nothing (the stem held 65% of the mix's energy: voice and guitar bleed, the spans cover 207 of 222 s) |
| 孟维来 - 野人 (`uNWIiDcs-Lc`, 198 s, lyric video) | zh 0.95 | 14 s | 9.9% of characters differ from LRCLIB's lyrics (homophones: 她们 for 他们, 花孤独 for 花骨朵); 37 of 38 line starts within 5 s of LRCLIB's timed record, median 0.19 s early, mean error 0.34 s, 33 within 0.6 s; **the guard dropped 20 invented characters**: a credit (作词 作曲 李宗盛) over the silent intro and "请不吝点赞订阅" ("please like and subscribe") over the end, Whisper's known hallucinations on music |

- LRCLIB has 野人 (a 198 s timed record), so caracole wouldn't transcribe it; it served as the reference.
- Whisper missing a live recording's opening is a known limit this design doesn't fix.
- nixpkgs (caracole's lock, nixos-unstable 2026-10-14): `python3Packages.openai-whisper` 20250625,
  `faster-whisper` 1.2.1, `whisperx`, `transformers` 5.17 and `demucs-rs` 0.3.4 (Apache-2.0, HTDemucs on wgpu/Vulkan)
  are packaged; Python demucs and the RoFormer separators are not. `torch` and `ctranslate2` are built without CUDA.
- GPU torch: `torch-bin` (unfree, prebuilt CUDA wheels), overriding `torch`, `torchaudio`, `torchvision` and `triton`
  (`triton-bin`) package-wide; with the source `triton` instead, torch 2.13's `torch/_native` Triton kernels fail
  (nixpkgs' patched `libcuda_dirs()` returns a string where a list is expected; `TORCH_DISABLE_NATIVE_JIT=1` avoids
  them). With `triton-bin`, openai-whisper ran on CUDA with no workaround.

## Goals

- For a song whose audio came from YouTube and that every lyrics site missed, the library page offers to transcribe
  its lyrics; on a yes, one job makes the song's timed lyrics from its audio and makes its auto sheet again with the
  chords over the words.
- No words where nobody sings.
- The models (Whisper, the separator, and BTC and beat_this too) run on the GPU when there is one, else the CPU.
- The sheet and the card say the lyrics were transcribed and are unverified.

## Non-goals

- Editing lyrics (the owner's: a more general lyrics feature comes later).
- Chords from a separated backing track (the owner's "not 2").
- Purchases in Music/ *(my call: YouTube songs only, as asked; the job's code shouldn't care where the audio came
  from, so purchases are a later one-line change)*.
- Timing plain lyrics a site has (AZLyrics') against the audio, with an aligner or by matching them to a transcript's
  timed words: a possible follow-on, which would keep a site's plain lyrics from turning the sheet into a chart.
- YouTube's auto-captions as a source: ranked below the mix, another yt-dlp run each, and only some videos have them.
- Transcribing on the phone. The phone gets the auto sheet by sync, as any file; the transcript itself stays on the
  computer.

## Anti-goals

- Transcribing without the owner's yes: the nightly run never transcribes.
- A transcript passing for a person's lyrics anywhere it is shown.
- Words over the intro, a break or the outro.
- A transcript standing in front of a site's lyrics: a site's always win.
- An offer that would fail (no models, no GPU stack, no audio): nothing is offered then, as the YouTube sheet's
  route already does (`youtube_fetch.route_problem`).

## Approaches

- **A, chosen: openai-whisper on the same torch as the chord models.** The auto-chords package switches torch to
  `torch-bin`, so Whisper, BTC and beat_this all use the GPU when there is one and the CPU otherwise. One stack, one
  device setting. Costs: an unfree package, a bigger closure, a CPU fallback slower than B's (not measured).
- **B: faster-whisper (CTranslate2)**, the exact engine of the owner's rank-1 sheet, fastest on CPU (128 s), but its
  CUDA build is not in the binary cache (CTranslate2 compiled from source) and it is a second stack beside torch.
- Dropped: separated vocals as Whisper's input (ranked last); transcribing only the sung spans (worse words);
  Qwen3-ASR + aligner (the owner preferred the mix); YouTube captions (ranked second, see Non-goals).

## The design

A review of the first draft (a review reading the design against the code) found where it was wrong about
the code or would have broken; what it changed is folded in below, each marked *(review)*.

### Which songs

A song is **due for an offer** when all hold:
- its audio came from YouTube (`youtube_fetch.youtube_audio` names a video), and the file exists;
- it has no human sheet, and it isn't ignored;
- its `lyrics_status` is `missing`, and every lyrics site that is switched on has asked about it and missed:
  LRCLIB's `lyrics_at`, `megalobiz:checked:<id>`, `azlyrics:checked:<id>` *(review: `missing` alone isn't "every site
  missed": a site skipped for its cooldown leaves no stamp, youtube_sheet.py:349-351, 371-373)*;
- its current audio has no transcript yet, nor a record of being transcribed to nothing (below).

### Where it is offered (my calls)

- **After a YouTube sheet**: when the job ends Ready with the chords stage's "chords only, no lyrics"
  (`youtube_sheet.HOLDS["none"]`), the song's line and its Requests tab entry offer **Transcribe the lyrics**, with
  the time it takes here ("about a minute" with a GPU; the CPU's, measured, below).
- **On the song's card**, for any song due for an offer, such as the example made before this exists.
- **Only on the computer's served page**, from served-only data, as `controls.youtube` is today (library_page.py
  440-446): the songs due and whether transcription runs here. The card's own data (`library_page._song`, pinned by
  the cards corpus and mirrored by the phone's Cards.kt) doesn't change, and the phone, which can't transcribe,
  offers nothing *(review)*.
- **Its own command**, modelled on youtube_sheet.py: `caracole transcribe --song "Artist - Title" [--progress]`
  *(review: not an `autochords` option; my call on the name)*, refused for a song not due, as the route
  (`POST /transcribe`) refuses it up front (`pages.Refused`, 409). It takes caracole's lock as an interactive
  command and joins test_commands_lock's list (auto-chords' is bulk, commands/autochords.py:72) *(review)*.

### The job

One queued job a song, its own key prefix (as `jobs.YOUTUBE_SHEET`), its view the song's (`kind` "song"), so the
song's line follows it; one at a time a song. Its stages, reported as a lookup's (`Progress`, JSON lines):

| Stage | What it does |
|---|---|
| `song` | refused when no longer due (the library may change while it waits) |
| `vocals` | the separated vocals (demucs-rs, `htdemucs`, vocals stem only), into a temporary folder; then the sung spans |
| `words` | Whisper large-v3 over the full mix; the guard; the lines; kept as the song's transcript (not its lyrics) |
| `chords` | auto-chords for that song alone (`autochords_pending(only=)`) |
| `pdf` | `render_all(song_ids=)` |
| `pages` | `_todo.md` and `index.html` |

- **The lock** is handed to a waiting lookup before each of `vocals`, `words` and `chords` (`_common.hand_over`),
  the long stages, and the song is read again and checked still due after each hand-over *(review)*.
- It ends Ready "chords over the transcribed lyrics" (`youtube_sheet.HOLDS` learns that case from
  `raw["lyrics_source"]`, below, *review*), or Not made: why ("no singing heard", "can't read the audio", "the
  separator can't run here", "the GPU failed: …").
- **Failures are told apart as auto-chords tells them** (run.py's three kinds), with one more *(review)*: a CUDA
  error (out of memory, a lost device) is the setup's, never the audio's. The song stays due, nothing is recorded
  against it, and the job says the GPU failed. Today anything `_hear` raises is filed as the file's
  (`autochords:failed:`, run.py:299-305) and parks the song until its audio changes.
- **The phone**: the new job kind's prefix, stages and outcome words are in tables the web corpus pins and the phone
  mirrors (jobs.py `song_key_of`, outcome.py, status.py; Commands.kt, Outcomes.kt, Status.kt;
  tests/test_conformance_web.py). The Kotlin side follows by the drift protocol, though the phone never runs the
  job *(review)*.

### Transcribing

- **The model**: `whisper.load_model(<the pinned file's path>, device=…)`, then
  `model.set_alignment_heads(<large-v3's>)`. Loaded from a path, openai-whisper sets no alignment heads (its
  `__init__.py:136-141`), and word timings then come from every head. The spike loaded it by name, which hashes
  the 3 GB file each time and downloads it again on a mismatch *(review)*. large-v3's heads are openai-whisper's
  `_ALIGNMENT_HEADS["large-v3"]`; caracole may keep a copy as a constant.
- **The call**: `transcribe(mix, language=…, word_timestamps=True, condition_on_previous_text=False, beam_size=5,
  best_of=5, fp16=<on CUDA>)`, the spike's settings. `condition_on_previous_text=False` avoids repetition loops.
- **Triton's cache**: on CUDA, Whisper's word timing compiles Triton kernels and writes `~/.triton/cache`, which the
  units' read-only HOME (`/var/empty`, nix/module.nix:106) refuses. The error isn't one Whisper catches
  (whisper/timing.py:41, 145). caracole sets `TRITON_CACHE_DIR` under its `cache_dir`, in `os.environ`, before
  importing whisper *(review)*. Verified inside the unit, not only in a shell.
- **The language** *(my call)*: detected by Whisper on the vocal stem's first 30 s of singing, then forced for the
  transcription of the mix. Forcing the language helped Whisper on singing in the research: WER 37.8 → 27.9.
  Measured: es 0.87 on Vikingos veganos, zh 0.95 on 野人.
- **The guard** *(review: the spike's rule was relative to the stem's own peak, so on bleed, as in Vikingos veganos,
  where 207 of 222 s counted as sung, or on an instrumental, it guards nothing)*:
  - A 50 ms frame is **sung** when the stem's energy is within a few dB of the mix's in that frame, and above a floor
    relative to the mix's loudest.
  - Sung frames are joined across gaps under 0.4 s, runs under 0.3 s dropped, each padded 0.2 s.
  - A word whose start and end both lie more than 0.3 s outside every sung span is dropped, and so is a line left
    empty.
  - The builder measures the thresholds on the three songs here, plus an instrumental and a song with sparse vocals.
    The example must still keep all its words; 野人 must still lose its credits and "请不吝点赞订阅".
  - Whisper's own `hallucination_silence_threshold` may be added on top, if it helps on those songs.
- **The lines**: Whisper's segments, broken further for a sheet:
  - a new line at a segment's first word once the line is 12 columns wide;
  - after `.,!?;，。！？；、` once it is 18;
  - at a breath: 0.5 s of silence from one word's end to the next one's start, once the line is 4 columns;
  - or at 52 columns.

  Widths are display columns, a Chinese character two. Words keep Whisper's spacing: a space before a Spanish or
  English word, none between Chinese characters (`<00:25.00>没<00:25.40>有…`). A pause measured between word starts
  broke a slow verse at every held note ("El / día en que muramos"), so the rule measures silence instead. These
  rules read well on the three songs tried.
- **The result**: enhanced LRC, a line stamp and a stamp before each word
  (`[00:09.34] <00:09.34>It <00:09.60>feels …`), which `merge.parse_lrc_words` already reads. Before each silence of
  2 s or more there is an empty line stamped at the last word's end. merge.py reads an empty line as the break LRC
  files mark (merge.py:262); without one it guesses a line lasts the median line length (merge.py:271) *(review)*.
- **Kept apart from the song's lyrics** (the owner's "only for its own sheet"; where, *my call*): kv
  `transcript:<song id>`, `{lrc, audio, audio_mtime, model, language, device, words_dropped, made_at}`. The song's
  `lyrics_json`, `lyrics_status` ("missing") and `lyrics_at` are untouched. So everything that reads a song's lyrics
  goes on as for a song with none:
  - the coverage that ranks a UG or LaCuerda sheet found later and retires the auto sheet (ug/fetch.py
    `_lyric_lines`);
  - the lyrics files in the song's folder;
  - the to-do page's missing lyrics;
  - the Sync and Sites tabs;
  - the lyrics' sync to the phone.

  Only auto-chords reads the transcript, and the auto sheet's viewer (below).
- **The per-song kv**: `transcript:` and `transcribe:none:` join `songs._PER_SONG_KV` (songs.py:59-69), so they go
  with a song removed or merged (SQLite reuses ids). The phone's `SongKv.kt` list and the sync corpus
  (tests/test_conformance_sync.py) follow *(review)*.
- **No words heard** (Whisper ran to the end and kept none): nothing is kept, and kv `transcribe:none:<song id>`
  keeps the audio's path and mtime, so the offer goes until the audio changes, as `autochords:failed:` does *(my
  call)*. A failure of the setup (the GPU, the separator) writes nothing.
- **New audio** (another video pasted, a purchase linked, the audio taken again): a transcript belongs to the audio
  it was heard from (its `audio` and `audio_mtime`). Once the song's audio is another, auto-chords no longer uses it,
  and the offer comes back *(my call: its words and timings are another recording's)*. A new transcript replaces the
  old.

### Auto-chords: which words go under the chords

- **The song's lyrics from a site, whenever it has any** (the owner's "always prefer lyrics from lyric sites"):
  everything as today (timed lyrics over their words, shifted when they fit; plain lyrics as the chart, then the
  lyrics).
- **Else the transcript of its current audio**, as timed lyrics whose duration is the audio's, so they fit exactly
  (`SYNC_TOLERANCE_S`) and no shift is searched.
- **Else none** (a chart alone), as today.
- The auto sheet's version records which it used: `raw["lyrics"]` "synced" as for any timed lyrics, and
  `raw["lyrics_source"]` "transcript" *(name my call)*. `_skip_reason` makes the song due again:
  - when a sheet made over a transcript finds the song now has a site's lyrics;
  - when a sheet made over none finds a transcript of the current audio (the job's own trigger);
  - when the transcript it used is another than the one kept now.

### What the sheet and the pages say

- The sheet's line after the video's credit (where the lyrics shift goes now): "Lyrics transcribed from the audio
  (Whisper), unverified" *(my call on the words)*. The sheet's file goes to the phone as any file.
- The card shows no new note *(review: the card's data is pinned by the cards corpus and mirrored on the phone)*;
  the sheet says it.
- Ready says "chords over the transcribed lyrics".
- **The viewer's sung line** (the owner's "yes, on both computer and phone"): `sheet (auto).html` made over a
  transcript lights the line being sung during autoscroll, as a sheet over a site's timed lyrics does (viewer.js
  `lightSung`, the data's `sung`).
  - The transcript's LRC travels with the auto sheet's version, `raw["transcript"]` beside `raw["lyrics_source"]`.
    Versions and their `raw` sync to the phone (peer_sync.py:394, hashed by `canonical.stored_hash`), so the phone
    has it with no kv of its own.
  - `render._timed_lyrics` is the song's, read once and given to every page of the song (render.py:833-843, AGENTS.md
    "sung"). For the auto sheet's page alone, when its version was made over a transcript, the timed lines come
    from that version's `raw["transcript"]`. Every other page of the song (a human `sheet.html` found later,
    `version-<tab>.html`) keeps the song's own timed lyrics, none while they are missing: the owner's "only for its
    own sheet".
  - The phone's `SongPass.timedLyrics` (android/viewer, render/internal/SongPass.kt) does the same, by the
    conformance corpus and its drift protocol, so the two write the same page.

### Lyrics found later

Nothing in the lyrics passes changes. LRCLIB, Megalobiz and AZLyrics go on asking about the song as about any miss,
once in 30 days (lyrics.py `_due`, the steps' `songs_to_ask`), on the computer and the phone alike. Once one finds
lyrics, the next auto-chords run makes the sheet again over them. This holds even for plain lyrics, which give the
chart then the lyrics, and for timed ones of another cut, which are shifted when one shift fits, else give the chart:
the owner prefers a site's lyrics always. The transcript stays kept, unused while the song has lyrics.

### The GPU

- **Only transcription uses the GPU** *(review)*. BTC and beat_this keep `[autochords].device`, default "cpu". They
  take about 15 s a song, their chords stay reproducible, and the nightly caracole-autochords unit keeps its sandbox
  (`PrivateDevices`) as it is. Transcription has its own setting, `[autochords].transcribe_device` *(name my call)*,
  default `auto`. That means CUDA when torch sees a usable device (one small allocation succeeds), else the CPU.
- **Packages** *(my call)*: the free CPU `autochords` package stays as it is. A second one, `autochords-cuda`, builds
  the same with `torch`, `torchaudio`, `torchvision` and `triton` overridden to their `-bin` packages. The module
  option `services.caracole.autochords.cuda` (default false) picks it; the owner's nix_config (`nixos/caracole.nix`)
  sets it true. The flake is public, so its default stays free.
  - The flake's own nixpkgs import allows unfree for torch-bin and the CUDA packages it brings: cudnn, libcublas and
    about a dozen more, listed by evaluating it *(review)*.
  - Its closure is about 6.7 GiB, against 1.1 GiB for the CPU torch.
- **First step of the plan, before anything is built on it** *(review)*: the cuda env builds with every auto-chords
  dependency against torch-bin, and `-m autochords` passes in it on the CPU. Only openai-whisper has been built
  against torch-bin so far; beat-this, torchaudio and torchcodec (BTC's fallback decoder, btc.py:144-146) haven't.
- **The units**: with `cuda` on, caracole-web (whose job child runs the transcription) and caracole-admin see the GPU,
  and the nightly unit doesn't.
  - `DeviceAllow` takes device groups, not path globs: `char-nvidiactl`, `char-nvidia-uvm`, `char-nvidia-caps`,
    `char-drm` and the NVIDIA frontend, with `DevicePolicy=closed`, as nixpkgs' ollama module does *(review)*.
  - `PrivateDevices` off for those two, and the `video` and `render` groups where the nodes need them.
  - nix/module-check.nix's expectations move with them.
  - No `LD_LIBRARY_PATH` unless it proves needed. If it is, it is set for the models alone, never for yt-dlp, ffmpeg
    or chordpro *(review)*.
- AGENTS.md's trap applies: a Nix file sets only `CARACOLE_*` variables. `TRITON_CACHE_DIR`, and
  `TORCH_DISABLE_NATIVE_JIT` if it proves needed, are set by caracole in `os.environ` before importing torch.
- **The CPU**: Whisper large-v3 (openai-whisper, torch-bin with the GPU hidden, 16 threads on the Core Ultra 9
  285HX) took 299 s for the 149 s example, about twice the song's length, against 15.7 s on the GPU. demucs-rs'
  `cpu` build is unmeasured. The offer says the time it will take here: about a minute with a GPU, "a few minutes"
  without.
- **The Ubuntu install** (docs/deploy.md) gets no transcription in this work: its route stays off, and it gains only
  the pins its tests demand *(review: it is a CPU-only box, and demucs-rs' release binary runs on Vulkan alone)*.

### The separator

- **demucs-rs 0.3.4** (Apache-2.0, in nixpkgs).
- **CPU mode**: nixpkgs builds it with wgpu alone; CPU is a cargo feature, `cpu` (demucs-cli/Cargo.toml), off by
  default *(review)*. caracole's package builds it with `buildFeatures = [ "cpu" ]`, so it runs where there is no
  GPU, and the builder checks how the CLI picks the backend.
- **No unguarded fallback** *(review)*: where the separator can't run, the job ends "the separator can't run here",
  and the route doesn't offer it. Transcribing without the guard would break the owner's "no made-up words".
- **The model**: `htdemucs.safetensors`, 84,030,696 bytes, SHA-256
  `8193504cdfb3943adaf039b8acb524a46e87ebf232c383ac7a32c80a6578423e`, from
  `https://huggingface.co/set-soft/audio_separation/resolve/939723568b2dca203e61cc7294317ba38549964f/Demucs/htdemucs.safetensors`
  (the URL demucs-rs uses, at today's commit), a fixed-output derivation. demucs-rs only checks that the file
  exists, so caracole runs it with `XDG_CACHE_HOME` pointing at a folder holding `demucs-rs/htdemucs.safetensors`
  linked to the pinned file.
- **Its autotune cache** is `~/.config/autotune/…`; the first run filled it over about 2 minutes. caracole gives it a
  persistent `XDG_CONFIG_HOME` under its `cache_dir`, or every run is cold *(review)*.

### Models and programs, pinned

- **Whisper large-v3**: `https://openaipublic.azureedge.net/main/whisper/models/e5b1a55b…81dadb/large-v3.pt`. The
  path's hex is the file's SHA-256, 3,087,371,615 bytes, MIT. A fixed-output derivation in nix/autochords.nix, as
  BTC's is.
- **HTDemucs**: above.
- Settings, three ways as for BTC: `CARACOLE_WHISPER_MODEL` / `[autochords] whisper_model`, `CARACOLE_DEMUCS_MODEL`
  / `separator_model`, `CARACOLE_DEMUCS_BIN` *(names my call)*, wired through package.nix's wrapper and the module's
  options.
- **Dependencies**: `openai-whisper` joins the autochords extra, listed in all three places (pyproject.toml,
  flake.nix `autochordsDeps`, nix/package.nix; test_nix_package.py). demucs-rs is a program on the wrapper's PATH,
  as chordpro and yt-dlp are.
- **Where it can run** *(review)*: a `transcribe_problem(cfg)` separate from `route_problem`. It holds
  `route_problem`'s checks plus whisper's `find_spec`, demucs-rs on PATH, and both model files present: no model
  loaded, since it runs on every page build (library_page.py:444, 507). `route_problem` and
  `commands/autochords.py`'s `MODEL_PACKAGES` don't change, so auto-chords stays on wherever Whisper is absent. In
  tests it is off as the YouTube route is (conftest's missing yt-dlp).
- **The test tone**: at model load in the job, as `run._models` does for BTC, Whisper and the separator must run on a
  2 s tone without error ("runs"; whether Whisper hears a word in it isn't the test) *(review)*.

### Tests

- A `Transcriber` protocol (audio, vocal spans → timed words) and a `Separator` protocol (audio → vocal stem), with
  fakes, as `run.Recognizer` has. The fast suite runs no model.
- Pure functions get their own tests: the sung spans, the guard, the lines, the LRC, the due rules, which words
  auto-chords lays the chords over and when it makes the sheet again, the failure kinds, and `transcribe_problem`.
- Tests marked `autochords` run the real models on a short clip. The repo is public, so the clip must be one it may
  hold: a short sung recording under a free licence, or one made for the test *(review; the builder finds it)*.
  `.#autochords` gains the two model files.
- Never a live request in a test (AGENTS.md "How work is done here").

## Left to the builder

- The module layout (`autochords/transcribe.py`, a separator module), the job's key and stage names, and the page
  strings, all within the rules above.
- The guard's thresholds, measured on the songs named above.
- How demucs-rs' CLI picks the CPU backend in the `cpu` build.
- How the line and the card show the offer, within the library page's existing patterns, from served-only data.
- The docs, in the same commits: docs/usage.md, docs/deploy.md, docs/install.md, AGENTS.md.

## Checked before it's done

- **First**: the cuda env builds, and `-m autochords` passes in it (above).
- The example made through the page: its words are within 10% WER of the spike's GPU whole-mix Whisper run
  (`gpu-mix.json`; fp16 beam search and another torch-bin build won't reproduce it word for word), no word falls in
  89.6–100.8 s, and the sheet says the lyrics are transcribed. The spike's scripts, transcripts, sung spans, the
  three songs' audio and stems, and the sheets the owner compared are kept outside the repo, in
  `~/Projects/caracole-spikes/2026-11-20-transcribed-lyrics/` *(my call: a song's transcribed lyrics don't belong in
  a public repo)*.
- 野人 through the same path: the credits and "请不吝点赞订阅" gone, its characters and line starts no worse than the
  spike's against LRCLIB (CER 9.9%, median line start 0.19 s early).
- An instrumental and a song with sparse vocals: no invented words kept.
- The transcription job inside caracole-web's unit, on the GPU and with the GPU hidden, not only in a shell.
- A few songs of the library with LRCLIB timed lyrics and audio, in English, Spanish and Chinese: the transcript's
  WER and line-start error against LRCLIB's, recorded in the plan. This is an evaluation script, not a test.
- The example's `sheet (auto).html`, on the computer and as the phone writes it after a sync: the line being sung
  lights during autoscroll, and the two pages agree.
- The whole suite, `-m autochords`, the Android suite and corpus (the job tables, the per-song kv and the sung lines
  move), and
  `nix flake check` (AGENTS.md "Before a change is done").
