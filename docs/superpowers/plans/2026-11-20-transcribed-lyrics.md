# Lyrics transcribed from a YouTube song's audio: implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** For a song whose audio came from YouTube and that every lyrics site missed, the owner can ask, from the
library page or the command line, for its lyrics to be transcribed from the audio. Whisper large-v3 hears the full
mix, separated vocals guard against invented words, and the song's auto sheet is made again with the chords over the
transcribed words. The models use the GPU when there is one.

**Architecture:** Pure-Python pieces in `src/caracole/autochords/`: sung spans, the guard, the lines and the LRC in
`words.py`; the kept transcript, the offer rule and kv in `transcript.py`. Two model wrappers: `separate.py` runs
demucs-rs as a subprocess; `transcribe.py` runs openai-whisper on torch. A job, `src/caracole/transcribe_job.py`,
copies youtube_sheet.py's staged run and is exposed as `caracole transcribe`. caracole serve queues it through `POST
/transcribe`. Auto-chords prefers a site's lyrics, then the transcript, then none. The viewer of `sheet (auto).html`
lights the sung line from the transcript, on the computer and on the phone. The GPU comes from a second package,
`autochords-cuda` (torch-bin), picked by a NixOS option.

**Tech Stack:** Python 3.14, typer, sqlite3; openai-whisper 20250625 and torch / torch-bin 2.13 from nixpkgs;
demucs-rs 0.3.4 (Rust, wgpu, plus the `cpu` cargo feature); librosa; Nix flake and NixOS module; Kotlin (android/)
for the phone's mirrors; vanilla JS (library_assets/).

**Spec:** `docs/superpowers/specs/2026-11-20-transcribed-lyrics-design.md` (approved 2026-11-20, commit ca416967).
Spike scripts and data, outside the repo: `~/Projects/caracole-spikes/2026-11-20-transcribed-lyrics/`.

**Where:** the worktree `/home/dani/Projects/caracole/.claude/worktrees/transcribed-lyrics`, on a branch
`feat/transcribed-lyrics` created there from `design/transcribed-lyrics` (`git switch -c feat/transcribed-lyrics`).
Every command below runs from that worktree's root.

## Global Constraints

- AGENTS.md binds every task: "How work is done here", "Invariants", "Traps", "Before a change is done".
- Test first: a failing test (on the missing name or an assertion), then the code.
- Never a live request in a test (YouTube, LRCLIB, Hugging Face, openaipublic). Never a real yt-dlp: `FakeYtDlp`.
- Heavy imports stay inside functions: torch, whisper, librosa and numpy never load on `caracole --help`, a page
  build or `transcribe_problem`.
- A dependency is listed three times (pyproject.toml, flake.nix `autochordsDeps`, nix/package.nix), from nixpkgs
  only: no pip, uv or PyPI pins.
- Third-party auto-chords imports (whisper, torch, librosa, numpy) appear only in files under
  `src/caracole/autochords/` (test_nix_package.py:114).
- A Nix file sets only `CARACOLE_*` variables the source reads (test_nix_package.py:38). `TRITON_CACHE_DIR` is set
  by caracole in `os.environ`.
- Docs move in the same commit as the behaviour they describe: docs/usage.md, docs/deploy.md, docs/install.md and
  AGENTS.md's sections (no test checks them).
- A change to the conformance corpus is regenerated, never hand-edited:
  `CARACOLE_CORPUS=write nix develop -c pytest -q -n 0 tests/test_conformance_*.py`. It merges only with
  `nix develop ./android -c gradle -p android test` passing.
- Conventional commits, scoped by area (`feat(autochords): …`, `test(conformance): …`, `build(nix): …`). No
  Claude or AI attribution anywhere.
- Fast loop: `nix develop -c pytest -q -m "not slow"`. Before each commit, the whole suite: `nix develop -c pytest -q`.
  When auto-chords is touched, also `nix develop .#autochords -c pytest -m autochords`. At the end,
  `nix flake check`.
- Values the spec pins, used below verbatim:
  - The Whisper call: model `large-v3`, `word_timestamps=True`, `condition_on_previous_text=False`,
    `beam_size=5`, `best_of=5`, `fp16` on CUDA only. The language is detected on the vocal stem's first 30 s of
    singing, then forced.
  - The guard: 50 ms frames; gaps under 0.4 s joined; runs under 0.3 s dropped; spans padded 0.2 s; a word goes
    when its start and end both lie more than 0.3 s outside every span.
  - The lines:
    - new line at a segment's first word once 12 columns wide;
    - new line after `.,!?;，。！？；、` once 18;
    - new line at 0.5 s of silence (word end to next start) once 4;
    - at most 52 columns, widths by `chordpro.display_columns`;
    - an empty LRC line at the last word's end before 2 s of silence.
  - Whisper large-v3: `https://openaipublic.azureedge.net/main/whisper/models/e5b1a55b89c1367dacf97e3e19bfd829a01529dbfdeefa8caeb59b3f1b81dadb/large-v3.pt`,
    3,087,371,615 bytes, SHA-256 `e5b1a55b89c1367dacf97e3e19bfd829a01529dbfdeefa8caeb59b3f1b81dadb`.
  - HTDemucs: `https://huggingface.co/set-soft/audio_separation/resolve/939723568b2dca203e61cc7294317ba38549964f/Demucs/htdemucs.safetensors`,
    84,030,696 bytes, SHA-256 `8193504cdfb3943adaf039b8acb524a46e87ebf232c383ac7a32c80a6578423e`.
  - The sheet's note: `Lyrics transcribed from the audio (Whisper), unverified`.
  - The job's Ready reason: `chords over the transcribed lyrics`.
- Names this plan fixes *(the spec left them open)*:
  - kv: `transcript:<song id>`, `transcribe:none:<song id>`;
  - version raw: `raw["lyrics_source"] = "transcript"`, `raw["transcript"]`, `raw["transcript_made_at"]`;
  - config: `[autochords] whisper_model`, `separator_model` and `transcribe_device` (default `"auto"`); top-level
    `demucs_bin` (default `"demucs"`);
  - env: `CARACOLE_WHISPER_MODEL`, `CARACOLE_DEMUCS_MODEL`, `CARACOLE_DEMUCS_BIN`, `CARACOLE_TORCH_CUDA`;
  - the job's key prefix `transcribe:`, its title `Lyrics from the audio: <Artist - Title>`, and the command
    `caracole transcribe --song "Artist - Title" [--progress]`.

## Review Focus

1. **A song whose audio is replaced after it was transcribed** (another video pasted, a purchase dropped into
   Music/). Expect: auto-chords no longer uses the old transcript, the sheet goes back to its chart, and the offer
   comes back. Test in Task 5 and Task 3.
2. **caracole serve's job child on a machine whose GPU is missing, busy or out of memory.** Expect: the job ends
   "the GPU failed: …" or runs on the CPU; the song is never filed as unreadable and stays offered. Test in Task 9
   and Task 10.
3. **A site's lyrics arriving for a song with a transcript**, plain or timed. Expect: the next auto-chords run
   remakes the sheet over the site's lyrics, the note goes, and the viewer stops lighting lines from the
   transcript. Test in Task 5 and Task 6.
4. **A song removed or merged into another while it has a transcript.** Expect: both kv records go with it, and a
   new song reusing the id inherits nothing. Test in Task 3.
5. **The owner pressing Transcribe twice, or on two songs at once.** Expect: one job a song (the second press
   answers with the first job), and jobs for two songs queue one after the other under the lock. Test in Task 11.

---

### Task 1: The GPU package and Whisper as a dependency (de-risk first)

**Files:**
- Modify: `pyproject.toml` (`optional-dependencies.autochords`), `flake.nix:13` (`autochordsDeps`),
  `nix/package.nix:113-123` (`optional-dependencies.autochords`)
- Modify: `flake.nix`: a second nixpkgs import, `packages.autochords-cuda`, `devShells.autochords-cuda`
- Modify: `nix/package.nix`: a `cudaTorch ? false` argument, setting `CARACOLE_TORCH_CUDA=1` in the wrapper when
  true
- Modify: AGENTS.md "Programs and models the tests need", docs/install.md (the new package)

**Interfaces:**
- Produces: `packages.x86_64-linux.autochords-cuda`, `devShells.x86_64-linux.autochords-cuda`; `import whisper`
  works in both auto-chords environments; the env var `CARACOLE_TORCH_CUDA` is `"1"` in the CUDA wrapper alone.

- [ ] **Step 1:** Add `openai-whisper` to the auto-chords extra in all three places. Run
  `nix develop -c pytest -q tests/test_nix_package.py`. Expected: PASS
  (`test_pyproject_the_flake_and_the_package_list_the_same_dependencies`).
- [ ] **Step 2:** In flake.nix, import nixpkgs a second time as `pkgsCuda`:
  - with `config.allowUnfreePredicate` admitting exactly the unfree packages torch-bin's closure needs (torch-bin,
    triton-bin, cudnn, libcublas and the rest), listed by evaluating it;
  - with python's `packageOverrides` setting `torch = torch-bin`, `torchaudio = torchaudio-bin`,
    `torchvision = torchvision-bin` and `triton = triton-bin`.

  `packages.autochords-cuda` is caracole with `withAutochords = true; cudaTorch = true;` built from `pkgsCuda`.
  `devShells.autochords-cuda` mirrors `devShells.autochords` on that python, and sets
  `CARACOLE_TORCH_CUDA = "1"` as the package's wrapper does.
- [ ] **Step 3:** Build it and run the model tests in it, on the CPU: `nix build .#autochords-cuda`, then
  `nix develop .#autochords-cuda -c pytest -m autochords`. Expected: both succeed. This is the spec's first check:
  beat-this, torchaudio and torchcodec against torch-bin. If a dependency won't build or a test fails, stop and
  report; nothing after this task assumes otherwise.
- [ ] **Step 4:** Check CUDA and Whisper once, by hand:

  ```
  nix develop .#autochords-cuda -c python -c "import torch, whisper; print(torch.cuda.is_available())"
  ```

  with `LD_LIBRARY_PATH=/run/opengl-driver/lib` if it proves needed. Expected: `True`. Record in the commit message
  whether `LD_LIBRARY_PATH` was needed.
- [ ] **Step 5:** Run the whole suite and `nix flake check`. Commit:
  `build(nix): an autochords-cuda package on torch-bin, and openai-whisper in the auto-chords extra`.

### Task 2: The model files, demucs-rs, and their settings

**Files:**
- Modify: `nix/autochords.nix` (two `fetchurl`s: `whisperLargeV3`, `htdemucs`)
- Modify: `nix/package.nix`:
  - `demucs` defaults to `demucs-rs.overrideAttrs { buildFeatures = [ "cpu" ]; }` and goes on the wrapper's PATH
    beside yt-dlp, with auto-chords only;
  - `--set-default CARACOLE_WHISPER_MODEL` and `CARACOLE_DEMUCS_MODEL` in `modelFiles`;
  - `passthru`;
  - `postCheck` greps.
- Modify: `flake.nix` (both auto-chords devShells set the two model variables and put demucs on PATH)
- Modify: `src/caracole/config.py:165-169, 213-223, 446-475`
- Modify: `tests/conftest.py:122-125` (`CARACOLE_DEMUCS_BIN` names no program in every test, as yt-dlp's does)
- Test: `tests/test_config.py`
- Modify: docs/usage.md (the `[autochords]` settings and `demucs_bin`); docs/deploy.md (the two SHA-256s, which
  `test_deploy_md_checks_what_nix_fetches_against_the_same_hashes` demands, and a line saying the Ubuntu install
  doesn't transcribe); AGENTS.md "Programs and models the tests need"

**Interfaces:**
- Produces:
  - `AutochordsConfig.whisper_model: Path | None = None`, `.separator_model: Path | None = None`,
    `.transcribe_device: str = "auto"`;
  - `Config.demucs_bin: str = "demucs"`, read from the toml key `demucs_bin`, else `CARACOLE_DEMUCS_BIN`;
  - the model paths from the `[autochords]` keys `whisper_model` / `separator_model`, else `CARACOLE_WHISPER_MODEL`
    / `CARACOLE_DEMUCS_MODEL`, as `ac_path` reads BTC's.

- [ ] **Step 1: Write the failing tests** in tests/test_config.py, beside `test_autochords_settings`:
  - `test_transcription_settings`:
    - `[autochords] whisper_model = "w.pt"`, `separator_model = "h.safetensors"` and `transcribe_device = "cpu"`
      load as `Path`s resolved against the config file's folder, and as `"cpu"`;
    - with neither key and `env={"CARACOLE_WHISPER_MODEL": "/m/w.pt", "CARACOLE_DEMUCS_MODEL": "/m/h.st"}`, they
      are `Path("/m/w.pt")` and `Path("/m/h.st")`;
    - with nothing, `None`, `None` and `"auto"`.
  - `test_demucs_bin_from_the_file_then_the_environment`: `demucs_bin = "/opt/demucs"` wins over
    `CARACOLE_DEMUCS_BIN`, which wins over `"demucs"`.
  - Extend the parametrized type-error tests: `whisper_model` and `separator_model` as paths (:315-316),
    `transcribe_device` and `demucs_bin` as strings (:331).
- [ ] **Step 2:** `nix develop -c pytest -q tests/test_config.py`. Expected: FAIL on the unknown keys.
- [ ] **Step 3:** Implement the config fields. Add the fetchurls with the hashes from Global Constraints, the
  wrapper defaults and the devShell variables. Set `CARACOLE_DEMUCS_BIN` in conftest.
- [ ] **Step 4:** Run tests/test_config.py and tests/test_nix_package.py. Expected: PASS. Then
  `nix build .#autochords` and check `ls $(nix build --print-out-paths .#autochords)/bin`, plus that the wrapper
  names both model files and a `demucs` on PATH.
- [ ] **Step 5:** Check by hand that the `cpu` build runs with no GPU:

  ```
  nix develop .#autochords -c env -u WAYLAND_DISPLAY VK_ICD_FILENAMES=/dev/null demucs -m htdemucs -s vocals -o /tmp/x <10 s wav>
  ```

  Learn from `demucs --help` how it picks the CPU backend, and note it in nix/package.nix's comment. Expected:
  `vocals.wav` written.
- [ ] **Step 6:** Whole suite, then commit: `build(nix): Whisper large-v3 and HTDemucs pinned, demucs-rs with its
  CPU backend, and their settings`.

### Task 3: The kept transcript and the offer rule

**Files:**
- Create: `src/caracole/autochords/transcript.py`
- Modify: `src/caracole/songs.py:65-69` (`_PER_SONG_KV` gains `"transcript:"` and `"transcribe:none:"`)
- Modify: `android/core/src/main/kotlin/io/github/danielhp95/caracole/core/library/internal/SongKv.kt:15-20` (the same
  two, the same order)
- Modify: `src/caracole/youtube_fetch.py` (`transcribe_problem`, `transcribe_reason`, `transcribe_time`)
- Test: `tests/test_autochords_transcript.py`, `tests/test_youtube_fetch.py` (or the file covering
  `route_problem`), `tests/test_songs.py`
- Corpus: regenerate (`vectors/library/remove.jsonl` and its fixture)

**Interfaces:**
- Consumes: `youtube_fetch.youtube_audio(conn, song) -> Video | None`, `route_problem(cfg) -> str | None`,
  `songs.Song` (`audio_path`, `audio_mtime`, `lyrics_status`, `status`, `key`, `display`), `db.kv_get_json` /
  `kv_set_json` / `kv_delete`.
- Produces (transcript.py, no third-party import):
  - Constants:
    - `TRANSCRIPT = "transcript:"`, `HEARD_NOTHING = "transcribe:none:"`, `LYRICS_SOURCE = "transcript"`;
    - `NOTE = "Lyrics transcribed from the audio (Whisper), unverified"`;
    - `MODEL = "whisper-large-v3"`.
  - `@dataclass(frozen=True) class Transcript`:
    - fields `lrc: str`, `audio: str`, `audio_mtime: float | None`, `model: str`, `language: str`, `device: str`,
      `words_dropped: int`, `made_at: str`;
    - `as_json() -> dict` and `from_json(value) -> Transcript | None` (None for anything malformed).
  - Storage:
    - `keep_transcript(conn, song, transcript) -> None`, which also deletes the song's `HEARD_NOTHING` record;
    - `transcript_of(conn, song) -> Transcript | None`: the kept one, only while `audio` and `audio_mtime` are the
      song's own;
    - `note_heard_nothing(conn, song, stamp: str) -> None`;
    - `heard_nothing(conn, song) -> bool`, true for the song's current audio only.
  - The offer:
    - `why_not_offered(conn, cfg, song, overrides) -> str | None`: None when due (the spec's "Which songs"), else
      one short reason;
    - `offered_song_ids(conn, cfg, overrides) -> list[int]`, ascending.
- Produces (youtube_fetch.py):
  - `transcribe_problem(cfg) -> str | None`: `route_problem(cfg)`; then `find_spec("whisper")` (else "built
    without Whisper"); then whisper_model and separator_model configured and `is_file()`; then
    `shutil.which(cfg.demucs_bin)` (else "demucs-rs isn't there");
  - `transcribe_reason(cfg) -> str | None`: the few words a page shows, as `route_reason` gives;
  - `transcribe_time(cfg) -> str`: `"about a minute"` when `os.environ.get("CARACOLE_TORCH_CUDA") == "1"`,
    `cfg.autochords.transcribe_device != "cpu"` and `Path("/dev/nvidiactl").exists()`; else `"a few minutes"`.

- [ ] **Step 1: Write the failing tests** (tests/test_autochords_transcript.py, with conftest's `conn`, `cfg` and
  `add_song`, and the youtube audio linked as test_autochords_run.py's `with_audio` does plus a youtube record as
  tests/test_youtube_fetch.py makes one):
  - `test_a_transcript_kept_is_read_back_while_the_audio_is_the_same`.
  - `test_a_transcript_of_other_audio_is_none_and_the_offer_comes_back`: change `audio_mtime`; `transcript_of` is
    None; `why_not_offered` is None.
  - `test_heard_nothing_holds_for_that_audio_alone`.
  - `test_a_song_is_offered_once_every_site_switched_on_missed`:
    - `lyrics_status="missing"`, `lyrics_at` set, kv `megalobiz:checked:<id>` and `azlyrics:checked:<id>`
      present: None;
    - drop the azlyrics stamp: a reason;
    - turn `[providers.azlyrics] enabled = false` via cfg: None again.
  - `test_no_offer_for_pending_or_found_or_instrumental_lyrics_a_human_sheet_an_ignored_song_or_bought_audio`:
    parametrized; each gives a reason, never None.
  - `test_offered_song_ids_lists_the_songs_due`.
  - `test_transcript_kv_goes_with_a_removed_song` (tests/test_songs.py): `delete_song_kv` leaves no
    `transcript:<id>` or `transcribe:none:<id>`.
  - `test_transcribe_problem_starts_with_the_youtube_route` (tests/test_youtube_fetch.py): with the route off it
    says the route's problem. With the route on (`helpers.fake_ytdlp.route_on`) and no whisper spec
    (monkeypatched `find_spec`), it says Whisper is missing. Then the models and `demucs_bin` each in turn, then
    None. Assert that importing nothing from torch happened (`"torch" not in sys.modules` after a fresh import, as
    the existing heavy-import tests do).
- [ ] **Step 2:** Run them. Expected: FAIL (`ModuleNotFoundError: caracole.autochords.transcript`).
- [ ] **Step 3:** Implement transcript.py, the youtube_fetch functions, and the two prefixes in `_PER_SONG_KV` and
  in SongKv.kt.
- [ ] **Step 4:** Run the new tests. Expected: PASS. Regenerate the corpus. Run
  `nix develop ./android -c gradle -p android test`. Expected: PASS (`LibraryStoreTest`
  `aSongIsRemovedAsRemoveSongRemovesIt`).
- [ ] **Step 5:** Whole suite, then commit: `feat(autochords): a song's transcript kept apart from its lyrics, and
  which songs are offered one`.

### Task 4: Sung spans, the guard, the lines and the LRC

**Files:**
- Create: `src/caracole/autochords/words.py` (pure Python, no numpy)
- Test: `tests/test_autochords_words.py`

**Interfaces:**
- Consumes: `caracole.chordpro.display_columns(text) -> list[int]` (a text's width is its last entry).
- Produces:
  - `@dataclass(frozen=True) class Word`: `start: float`, `end: float`, `text: str`, `space: bool`,
    `segment_start: bool = False`.
  - `@dataclass(frozen=True) class Span`: `start: float`, `end: float`.
  - Constants:
    - `FRAME_S = 0.05`, `JOIN_S = 0.4`, `MIN_RUN_S = 0.3`, `PAD_S = 0.2`, `SLACK_S = 0.3`;
    - `STEM_WITHIN_DB = 10.0`, `FLOOR_DB = 40.0`: starting values, measured again in Task 14;
    - `SEG_COLS = 12`, `PUNCT_COLS = 18`, `BREATH_S = 0.5`, `BREATH_COLS = 4`, `MAX_COLS = 52`, `BREAK_S = 2.0`.
  - `sung_spans(stem_db, mix_db, *, frame_s=FRAME_S) -> list[Span]`: a frame is sung when
    `stem_db[i] >= mix_db[i] - STEM_WITHIN_DB` and `mix_db[i] >= max(mix_db) - FLOOR_DB`.
  - `guard(words, spans) -> tuple[list[Word], list[Word]]`: `(kept, dropped)`.
  - `lines_of(words) -> list[list[Word]]`.
  - `to_lrc(lines) -> str`: `[mm:ss.xx]` line stamps, `<mm:ss.xx>` before each word, a space only where
    `word.space`, and an empty `[mm:ss.xx]` line at a line's last word's end when the next line starts `BREAK_S` or
    more later.

- [ ] **Step 1: Write the failing tests:**
  - `test_frames_where_the_stem_is_near_the_mix_are_sung`: 100 frames, stem −3 dB under the mix in frames 20–59
    and −30 dB elsewhere, mix at −10 dB. Expect `[Span(0.8, 3.2)]` (padded 0.2 s each side).
  - `test_bleed_without_a_voice_is_not_sung`: the stem 15 dB under the mix everywhere. Expect `[]`.
  - `test_short_gaps_join_and_short_runs_drop`.
  - `test_words_outside_every_span_are_dropped_and_words_touching_one_kept`:
    - `Word(0.0, 0.5, "作")` with spans `[Span(25.0, 30.0)]` → dropped;
    - `Word(24.8, 25.2, "没")` → kept.
  - `test_a_line_breaks_at_a_breath_not_at_a_held_note`: "El" ends at 24.9, "día" starts at 25.34 (no break, 0.44 s
    of silence); "nuestro" starts 0.6 s after the previous end (break).
  - `test_chinese_lines_count_two_columns_a_character_and_join_with_no_space`: 27 Chinese characters with no
    pauses break at 52 columns (26 characters); the LRC line has no spaces.
  - `test_lrc_marks_a_break_before_two_seconds_of_silence`. Expected text:

    ```
    [00:01.00] <00:01.00>Hi <00:01.50>there
    [00:02.00]
    [00:05.00] <00:05.00>Again
    ```

  - `test_the_lrc_reads_back_through_merge`: `merge.parse_lrc_words(to_lrc(lines))` gives the same words and
    stamps.
- [ ] **Step 2:** Run them. Expected: FAIL (no module).
- [ ] **Step 3:** Implement words.py. The rules are the spec's "The guard" and "The lines". The spike's
  `spike/to_lrc.py` and `spike/gate.py` are prior art, except for the stem-to-mix rule.
- [ ] **Step 4:** Run them. Expected: PASS. Whole suite, then commit: `feat(autochords): the sung spans, the guard
  and the lines of a transcript`.

### Task 5: Auto-chords over the transcript

**Files:**
- Modify: `src/caracole/autochords/run.py`:
  - `_generate` :294 reads `transcript_of`;
  - `_make_sheet` :651 chooses site lyrics, else the transcript, else none, and adds `NOTE` after the source and
    shift notes;
  - `_keep` :685 writes `lyrics_source`, `transcript` and `transcript_made_at` into raw;
  - `_skip_reason` :414 gains the spec's three new cases.
- Modify: `src/caracole/youtube_sheet.py:69, 442-444` (`HOLDS` says "chords over the transcribed lyrics" when the
  version's `raw["lyrics_source"] == "transcript"`)
- Test: `tests/test_autochords_run.py`, `tests/test_youtube_sheet.py`
- Modify: AGENTS.md `autochords/` section; docs/usage.md (auto-chords' lyrics order)

**Interfaces:**
- Consumes: `transcript.transcript_of`, `transcript.LYRICS_SOURCE`, `transcript.NOTE`, `Transcript.lrc`,
  `Transcript.made_at`.
- Produces: the auto sheet's version `raw` has `"lyrics_source": "transcript"`, `"transcript": <lrc>` and
  `"transcript_made_at": <made_at>` when made over a transcript, and none of the three otherwise.

- [ ] **Step 1: Write the failing tests** in tests/test_autochords_run.py, with its `FakeRecognizer`, `FakeBeats`,
  `with_audio` and `run`, and a `keep_transcript` of a word-timed LRC over a 10 s WAV:
  - `test_a_song_with_no_lyrics_and_a_transcript_gets_its_chords_over_the_transcribed_words`:
    - the sheet has the lyric lines;
    - `NOTE` is on the line after the song's name;
    - the raw has the three keys;
    - `raw["lyrics"] == "synced"`.
  - `test_a_sites_lyrics_win_over_the_transcript`: plain lyrics stored, so `lyrics_status="found"`. The sheet is
    chart-then-lyrics, the raw has no `lyrics_source`, and there is no NOTE.
  - `test_a_sheet_over_a_transcript_is_made_again_once_a_site_has_lyrics`.
  - `test_a_sheet_over_none_is_made_again_once_a_transcript_comes`.
  - `test_a_sheet_over_one_transcript_is_made_again_over_a_newer_one`.
  - `test_a_transcript_of_other_audio_is_not_used`.
  - `test_the_ready_line_says_the_lyrics_are_transcribed` (tests/test_youtube_sheet.py): `HOLDS` for a transcript
    sheet.
- [ ] **Step 2:** Run them. Expected: FAIL.
- [ ] **Step 3:** Implement. `_make_sheet` may return a small dataclass in place of its 4-tuple if the extra field
  makes the tuple unclear.
- [ ] **Step 4:** Run tests/test_autochords_run.py and tests/test_youtube_sheet.py. Expected: PASS. Then
  `nix develop .#autochords -c pytest -m autochords`. Expected: PASS. Whole suite, then commit:
  `feat(autochords): a song with no lyrics from a site gets its chords over its transcript`.

### Task 6: The sung line from the transcript (computer)

**Files:**
- Modify: `src/caracole/render.py`:
  - `_Sheet` (:1975-1984) gains `timed: tuple[tuple[float, str], ...] | None = None`;
  - `_auto_sheet` (:2031-2048) fills it from `raw["transcript"]` (`lyrics.synced_lines`) when
    `raw.get("lyrics_source") == "transcript"`;
  - the `render` closure passes `sheet.timed` in place of the song's `timed` at :801 when it isn't None.
- Test: `tests/test_render_all.py`, or whichever file holds the existing sung-line render tests (grep
  `sung_lines`), and `tests/test_conformance_viewer_render.py` (a case in `auto_sheets`, :386, whose auto
  version's raw has the three keys; `render.jsonl` stays under its 400,000-byte cap)
- Modify: AGENTS.md's `sung` paragraph (:338-341)

**Interfaces:**
- Consumes: Task 5's raw keys.
- Produces: `sheet (auto).html`'s data has `sung` from the transcript; `sheet.html` and `version-<tab>.html` keep
  the song's own timed lyrics.

- [ ] **Step 1: Write the failing tests:**
  - `test_an_auto_sheet_over_a_transcript_lights_its_lines_from_the_transcript`: the data's `sung` is not None, and
    `ms` matches the transcript's first line.
  - `test_a_human_sheet_beside_it_lights_none_from_the_transcript`.
  - `test_an_auto_sheet_remade_over_a_sites_lyrics_lights_its_lines_from_them_not_the_transcript`.
  - The conformance case added.
- [ ] **Step 2:** Run them. Expected: FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run them. Expected: PASS. Regenerate the corpus. Expected: the Kotlin `PhoneRenderTest` now fails
  on the new record (that is Task 7's). Commit with the corpus: `feat(viewer): an auto sheet over a transcript
  lights the line being sung`. This commit does not merge alone; Task 7 follows it on the branch.

### Task 7: The sung line from the transcript (phone)

**Files:**
- Modify: `android/viewer/src/main/kotlin/io/github/danielhp95/caracole/viewer/render/internal/Sources.kt`:
  - `SheetSource` (:29-30) gains `val timed: List<Pair<Double, String>>? = null`;
  - `Sources.auto` (:65-81) fills it from the raw's `"transcript"` via `Lyrics.syncedLines`, when `"lyrics_source"`
    is `"transcript"`.
- Modify: `android/viewer/src/main/kotlin/io/github/danielhp95/caracole/viewer/render/internal/SongPass.kt:153-162`
  (`renderSheet(..., timed = sheet.timed ?: timed)`)

**Interfaces:**
- Consumes: Task 6's corpus record.

- [ ] **Step 1:** Run `nix develop ./android -c gradle -p android test`. Expected: FAIL in `PhoneRenderTest` on the
  transcript case.
- [ ] **Step 2:** Implement the mirror.
- [ ] **Step 3:** Run it again. Expected: PASS. Commit: `feat(android): the phone lights an auto sheet's lines
  from its transcript, as the computer does`.

### Task 8: The separator

**Files:**
- Create: `src/caracole/autochords/separate.py`
- Test: `tests/test_autochords_separate.py` (a fake `demucs` script written to `tmp_path`, as
  `helpers/fake_ytdlp.py` writes yt-dlp's); `tests/test_autochords_models.py` (one `autochords`-marked test)

**Interfaces:**
- Consumes: `words.FRAME_S`.
- Produces:
  - `class SeparatorFailed(Exception)`.
  - `class Separator(Protocol)`: `def vocals(self, audio: Path, workdir: Path) -> Path`.
  - `class DemucsSeparator`:
    - `__init__(self, binary: str, model: Path, cache_dir: Path)`;
    - `vocals` runs `[binary, "-m", "htdemucs", "-s", "vocals", "-o", str(workdir / "stems"), str(audio)]` with
      `XDG_CACHE_HOME=workdir / "cache"` (holding `demucs-rs/htdemucs.safetensors`, a symlink to `model`) and
      `XDG_CONFIG_HOME=cache_dir / "demucs-rs"` (its autotune cache, kept between runs);
    - it returns `workdir / "stems" / "vocals.wav"`;
    - it raises `SeparatorFailed`, carrying the last stderr line, when the exit is nonzero or the file is missing.
  - `frame_db(path: Path, *, frame_s: float = FRAME_S, rate: int = 16000) -> list[float]`: librosa RMS in dB, one
    value per frame, imported inside the function.

- [ ] **Step 1: Write the failing tests:**
  - `test_demucs_runs_on_the_audio_with_its_model_linked_and_its_autotune_cache_kept`: the fake records its argv
    and environment and writes `vocals.wav`. Assert:
    - the argv;
    - that `$XDG_CACHE_HOME/demucs-rs/htdemucs.safetensors` resolves to the model;
    - `XDG_CONFIG_HOME`.
  - `test_a_demucs_that_fails_raises_separator_failed_with_its_last_line`.
  - `test_a_demucs_that_writes_no_stem_raises_separator_failed`.
  - `@pytest.mark.autochords test_htdemucs_separates_a_tone_and_frame_db_reads_it`: real binary and model from the
    environment; `frame_db` gives `ceil(seconds / 0.05)` values, within one.
- [ ] **Step 2:** Run them. Expected: FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run the fast tests (PASS), then `nix develop .#autochords -c pytest -m autochords -k htdemucs`
  (PASS). Commit: `feat(autochords): the vocals separated with demucs-rs`.

### Task 9: The transcriber

**Files:**
- Create: `src/caracole/autochords/transcribe.py`
- Test: `tests/test_autochords_transcribe.py` (fast: device and error rules with torch faked via `sys.modules`);
  `tests/test_autochords_models.py` (one `autochords` test)

**Interfaces:**
- Consumes: `words.Word`; `run._write_tone(path)` (the 2 s C major WAV).
- Produces:
  - `@dataclass(frozen=True) class Heard`: `language: str`, `words: list[Word]`.
  - `class Transcriber(Protocol)`: `def hear(self, mix: Path, stem: Path, first_sung_s: float) -> Heard`.
  - `class SetupFailed(Exception)`: the setup's (the GPU's, a model that won't load), never the audio's.
  - `ALIGNMENT_HEADS: bytes`: openai-whisper's `_ALIGNMENT_HEADS["large-v3"]`, copied.
  - `resolve_device(setting: str) -> str`: `"cpu"` and `"cuda"` as given; `"auto"` means `"cuda"` when
    `torch.cuda.is_available()` and `torch.zeros(1, device="cuda")` succeeds, else `"cpu"`.
  - `is_setup_error(e: BaseException) -> bool`: true for `torch.cuda.OutOfMemoryError`, and for a `RuntimeError`
    whose message has `"CUDA"`, `"cuDNN"` or `"device-side"`.
  - `class WhisperTranscriber`:
    - `__init__(self, model_path: Path, *, device: str, cache_dir: Path)`. It sets
      `os.environ.setdefault("TRITON_CACHE_DIR", str(cache_dir / "triton"))` before importing whisper, loads with
      `whisper.load_model(str(model_path), device=device)`, then calls `set_alignment_heads(ALIGNMENT_HEADS)`.
    - `hear`:
      - detects the language on `stem[first_sung_s : first_sung_s + 30 s]`;
      - transcribes the mix with Global Constraints' settings;
      - gives `Word(w["start"], w["end"], w["word"].strip(), w["word"][:1].isspace(), first in its segment)` for
        each word with text;
      - raises `SetupFailed` for what `is_setup_error` says.
  - `tone_problems(models: list[tuple[str, Callable[[Path], object]]]) -> list[str]`, as run.py's `_test_tone`. If
    `_test_tone` can serve as it is, reuse it and skip this function.

- [ ] **Step 1: Write the failing tests:**
  - `test_auto_is_cuda_when_torch_allocates_on_it_else_cpu`: a fake `torch` module in `sys.modules`; three cases
    (unavailable, allocation raises, works).
  - `test_out_of_memory_and_cuda_errors_are_the_setups`: `is_setup_error` true for `RuntimeError("CUDA error: out
    of memory")` and false for `RuntimeError("Error opening x.m4a")`.
  - `test_the_alignment_heads_are_large_v3s`: under `pytest.importorskip("whisper")`, equal to
    `whisper._ALIGNMENT_HEADS["large-v3"]`.
  - `@pytest.mark.autochords test_whisper_hears_a_tone_without_error`: real model; `hear(tone, tone, 0.0)` returns a
    `Heard` (any words); the triton cache dir is under `cache_dir`.
- [ ] **Step 2:** Run them. Expected: FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run the fast tests (PASS). Run `nix develop .#autochords -c pytest -m autochords -k whisper`
  (PASS, on the CPU). Run `nix develop .#autochords-cuda -c pytest -m autochords -k whisper` (PASS, on CUDA when
  there is one). Commit: `feat(autochords): Whisper large-v3 hears a song, on the GPU when there is one`.

### Task 10: The job and `caracole transcribe`

**Files:**
- Create: `src/caracole/staged.py`. Extract youtube_sheet.py's `_Sheet` reporting half into
  `class StagedRun`: `_report`, `stage`, `_check_readable`, `_fail`, `_song_again`, `_refuse` and the `_Stop`
  exception. youtube_sheet.py then uses it, with every test in tests/test_youtube_sheet.py and
  tests/test_commands_youtube.py passing unchanged.
- Create: `src/caracole/transcribe_job.py`
- Create: `src/caracole/commands/transcribe.py`
- Test: `tests/test_transcribe_job.py`, `tests/test_commands_transcribe.py`, `tests/test_commands_lock.py`
  (`ASKED_NOW` gains `("transcribe", "--song", "A - T", "--progress")`; the test's monkeypatch of
  `route_problem` gains `transcribe_problem`)
- Modify: docs/usage.md (the command, its output, its exits); AGENTS.md (Layout, `autochords/`, the command)

**Interfaces:**
- Consumes:
  - Tasks 3–5 and 8–9;
  - `autochords_pending(conn, cfg, *, recognizer, beats_fn, now, overrides, only)`;
  - `render_all(..., song_ids=)`, `todo.write_pages`;
  - `_common.exclusive(cfg, what, interactive=True, on_wait=)`, `_common.hand_over(cfg, conn)`, `handoffs()`,
    `overrides_since()`;
  - `get.Progress`.
- Produces:
  - `transcribe_job.STAGES = (("song", "Find the song"), ("vocals", "Where the singing is"), ("words",
    "Transcribing the lyrics"), ("chords", "Chords from the audio"), ("pdf", "PDF"), ("pages", "The logbook
    page"))`.
  - `@dataclass(frozen=True) class TranscribeRequest(artist: str, title: str)` with a `display` property.
  - `TranscribeResult`, shaped as `youtube_sheet.SheetResult`.
  - `make_transcript(cfg, request, progress=None, *, separator=None, transcriber=None, recognizer=None,
    beats_fn=None, runner=subprocess.run, now=None, clock=time.monotonic) -> TranscribeResult`.
  - The command `caracole transcribe --song "Artist - Title" [--progress]`. It exits 1 when
    `transcribe_problem(cfg)` says why (`caracole transcribes nothing here: <problem>`) or the result isn't `ok`,
    and 0 otherwise.

Stages, each as the spec's "The job" says:
- **song**: the song by its identity key, never added to wanted.txt. Refused by `why_not_offered`.
- **vocals**:
  - `hand_over`, read the song again, check it is still due;
  - a `tempfile.TemporaryDirectory(dir=cfg.cache_dir)`;
  - `separator.vocals`, then `sung_spans(frame_db(stem), frame_db(mix))`;
  - `SeparatorFailed` → `_fail("the separator can't run here (…)")`.
- **words**:
  - `hand_over`, read the song again;
  - `transcriber.hear(mix, stem, spans[0].start if spans else 0.0)`, then `guard`, `lines_of`, `to_lrc`;
  - nothing kept → `note_heard_nothing` and `_fail("no singing heard")`;
  - else `keep_transcript`, done with "N words in M lines (<language>), K dropped".
- **chords**: as youtube_sheet's `chords`. Ready detail: `chords over the transcribed lyrics`.
- **pdf** and **pages**: as youtube_sheet's.
- **Setup failures**: a `SetupFailed` anywhere → `_fail("the GPU failed: …")` or the model's own words. Nothing is
  written against the song.
- **Default models**: `separator` and `transcriber` default to `DemucsSeparator(cfg.demucs_bin,
  cfg.autochords.separator_model, cfg.cache_dir)` and `WhisperTranscriber(cfg.autochords.whisper_model,
  device=resolve_device(cfg.autochords.transcribe_device), cache_dir=cfg.cache_dir)`, built at their first stage,
  after the tone check.

- [ ] **Step 1:** Extract `StagedRun`. Run `nix develop -c pytest -q tests/test_youtube_sheet.py
  tests/test_commands_youtube.py`. Expected: PASS, unchanged. Commit: `refactor(youtube): the sheet's staged run,
  shared`.
- [ ] **Step 2: Write the failing tests** (tests/test_transcribe_job.py: a fake `Separator` that writes a WAV, a
  fake `Transcriber` returning fixed words, test_youtube_sheet.py's `Heard` progress, `Recognizer`, `beats` and
  `fake_chordpro`):
  - `test_an_offered_song_gets_its_transcript_and_its_sheet_over_it`: stages all done in order; kv
    `transcript:<id>`; the sheet has NOTE; `result.ok`.
  - `test_a_song_not_offered_is_refused_with_its_reason_and_nothing_runs`: the fakes are never called.
  - `test_words_outside_the_singing_are_dropped`: the fake's word at 0.0 with spans starting at 25 s.
  - `test_no_singing_heard_records_it_and_fails_without_a_sheet`.
  - `test_a_separator_that_cant_run_fails_the_job_and_records_nothing`.
  - `test_a_gpu_failure_fails_the_job_records_nothing_and_the_song_stays_offered`: the fake raises `SetupFailed`.
  - `test_the_lock_goes_to_a_waiting_lookup_before_each_long_stage`, as
    `test_a_song_removed_as_the_models_let_a_lookup_go_first_ends_the_sheet_as_a_refusal` does with
    `helpers.locks.waiting_for`.
  - tests/test_commands_transcribe.py:
    - `test_transcribe_says_each_stage_and_exits_0`;
    - `test_transcribe_where_it_cant_run_says_why_and_exits_1`;
    - `test_registering_the_command_imports_no_model`: `"whisper"`, `"torch"`, `"librosa"` are not in
      `sys.modules` after `build_app()`.
- [ ] **Step 3:** Run them. Expected: FAIL.
- [ ] **Step 4:** Implement transcribe_job.py and commands/transcribe.py. The help text has no unescaped `[…]`
  (`test_every_help_keeps_its_square_brackets`).
- [ ] **Step 5:** Run them, plus tests/test_commands_lock.py. Expected: PASS. Whole suite, then commit:
  `feat(autochords): caracole transcribe, a song's lyrics transcribed from its audio and its sheet made again`.

### Task 11: caracole serve: the route, the job kind and the offer on the page

**Files:**
- Create: `src/caracole/web/transcribe_routes.py`. It has `ROUTES = (Route("POST", "/transcribe", …),)` and
  `transcribe_song(app, form) -> Response`, copying `youtube_routes.sheet_from_youtube`'s song-by-id branch:
  - `song_id`, `same_song`;
  - Refused 409 with `transcribe_reason` when it can't run here;
  - Refused 409 with `why_not_offered` when the song isn't due;
  - `app.submit(f"Lyrics from the audio: {display}", TRANSCRIBE + key, transcribe_steps(display),
    display=display, full=…)`, then `app.queued(job)`.
- Modify: `src/caracole/web/jobs.py`:
  - `TRANSCRIBE = "transcribe:"`;
  - `transcribe_steps(display) -> [("Transcribing the lyrics", ("transcribe", "--progress", f"--song={display}"))]`;
  - `_transcribes(args)`;
  - `Job.transcribes` beside `from_youtube` (:191-195);
  - `_reports` (:355-362) admits `"transcribe"`;
  - `song_key_of` (:490-492) strips `TRANSCRIBE` too;
  - `_stages` (:568-593) adds `transcribe_job.STAGES`.
- Modify: `src/caracole/web/status.py`:
  - `STAGE_LINES` gains `"vocals": "Finding where the singing is"` and `"words": "Transcribing the lyrics"`;
  - a Ready rule for `TRANSCRIBE` as :279-283's (Ready once `chords` is done).
- Modify: `src/caracole/web/outcome.py`:
  - `TRANSCRIBE_STEPS = (("Song", ("song",)), ("Vocals", ("vocals",)), ("Words", ("words",)), ("Chords",
    ("chords",)), ("PDF", ("pdf",)))`;
  - the transcribe job in `steps()`, `lists_steps`, the `progress()` gate and the Ready and waiting reasons;
  - generalize `_youtube_holds` / `_youtube_stopped` to take the job's stage names, rather than copying them.
- Modify: `src/caracole/library_page.py:437-445`: `data["server"]["transcribe"] = {"ok": bool, "why": str | None,
  "songs": [ids], "time": str}`, from `transcribe_reason`, `offered_song_ids` and `transcribe_time`, built only
  when `controls is not None`.
- Modify: `src/caracole/library_assets/library.js`:
  - `transcribeOffer(s)` beside `youtubeSheet` (:432-464): `songForm("transcribe", "/transcribe", s)`, button
    "Transcribe the lyrics", hint `From the audio, ${time}.`, shown when `server.transcribe.ok` and
    `server.transcribe.songs` includes `s.id`;
  - placed in `cardFor` after `youtubeSheet` (:1352-1353);
  - removed in `paint()` while a job is active (:4353-4357).
- Modify: `src/caracole/library_assets/requests.js`: a Requests-tab entry whose song is in
  `server.transcribe.songs` shows the same form after its Ready line.
- Modify: `library.css`: the form as `.youtube-sheet`'s (:383-384).
- Modify: `tests/test_web_app.py:3093-3096` (the routes modules list).
- Test: `tests/test_web_transcribe.py` (modelled on tests/test_web_youtube.py:54-102); `tests/test_web_jobs.py`;
  `tests/test_web_status.py`; `tests/test_web_outcome.py`; `tests/test_library_page.py:270-273` (the served
  keys); `tests/test_web_page_transcribe.py` (Chromium, modelled on tests/test_web_page_youtube.py:222)
- Conformance:
  - tests/test_conformance_web.py: `phone_kind` gains `(_jobs.TRANSCRIBE, "transcribe")`; the job joins the
    every-state loop (:913-932) and `staged` (:936); `TRANSCRIBE_STEPS` goes into `tables_record`;
  - tests/test_conformance_queue.py `COMMANDS` gains the command's argv;
  - tests/test_conformance_library_page.py `server_member` gains `"transcribe"`.
- **Budget:** `vectors/web/` is at 9,996,046 of its 10,000,000 bytes. The owner OK'd (2026-11-20) raising `"web"`
  in tests/conformance/budget.json to 20,000,000, and `vectors_total` to 82,000,000 so the areas still fit in it
  (test_the_areas_budgets_fit_in_the_total), in a commit of its own: `test(conformance): the web area's budget
  20 MB, the owner's OK`.
- Modify: docs/usage.md (the page's offer), AGENTS.md (web routes, jobs, status/outcome).

**Interfaces:**
- Consumes: Task 3 (`why_not_offered`, `offered_song_ids`, `transcribe_reason`, `transcribe_time`), Task 10 (the
  command and `transcribe_job.STAGES`).
- Produces: `POST /transcribe` (form `csrf`, `song`, `identity`); `jobs.TRANSCRIBE`, `jobs.transcribe_steps`; the
  served `server.transcribe` member.

- [ ] **Step 1: Write the failing tests:**
  - test_web_transcribe.py:
    - `test_an_offered_song_queues_one_caracole_transcribe` (the queued job's `song_key == TRANSCRIBE + key`; its
      steps are `transcribe_steps(display)`);
    - `test_asked_again_while_it_waits_the_one_waiting_is_the_answer`;
    - `test_where_it_cant_run_it_says_why_and_queues_nothing` (409);
    - `test_a_song_not_offered_is_refused_with_its_reason` (409);
    - `test_a_transcription_never_joins_the_songs_lookup_nor_a_lookup_it`.
  - test_web_status.py: `test_a_transcription_says_its_running_stage` and `test_it_is_ready_once_its_chords_are_made`.
  - test_web_outcome.py: `test_a_transcription_shows_its_steps_and_says_what_it_holds_or_what_stopped_it`.
  - test_library_page.py: `test_the_served_page_lists_the_songs_offered_a_transcription`, and the served keys
    include `transcribe`.
  - Chromium: `test_a_songs_card_offers_a_transcription_and_its_line_follows_it`, with a `FakeTranscribe` runner
    emitting stage events, as `FakeSheet` does.
  - Chromium: `test_where_it_cant_run_no_card_offers_one`.
- [ ] **Step 2:** Run them. Expected: FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run them, then the whole suite. Expected: PASS. Regenerate the corpus. Then
  `nix develop -c pytest -q tests/test_corpus_budget.py`. Expected: PASS.
  Commit: `feat(web): Transcribe the lyrics on a song's card and its request, a job of its own`. Android follows in
  Task 12 before merging.

### Task 12: The phone mirrors the new job kind

**Files:**
- Modify (android/server/src/main/kotlin/io/github/danielhp95/caracole/server/jobs/):
  - `Commands.kt`: `TRANSCRIBE_STAGES` as `YOUTUBE_SHEET_STAGES` (:83-91), `TRANSCRIBE = "transcribe:"`,
    `reports` (:264-266), `transcribes(args)`, `songKeyOf` (:299), `stages` (:321-338), `kindOf` (:373);
  - `Outcomes.kt`: `TRANSCRIBE_STEPS` and its uses, as `YOUTUBE_STEPS`' (:63-67, :143, :153, :181-190, :232,
    :311, :326, :396, :406);
  - `Status.kt`: `STAGE_LINES` (:102-131) and the Ready rule (:236-240).
- Modify: `android/server/src/main/kotlin/io/github/danielhp95/caracole/server/page/LibraryPage.kt:79-80`. It
  writes `"transcribe": {"ok": false, "why": <its reason>, "songs": [], "time": "a few minutes"}`, as it writes
  `youtube`'s.

- [ ] **Step 1:** Run `nix develop ./android -c gradle -p android test`. Expected: FAIL in `QueueReplay`,
  `JobViewsReplay` and the library page replay.
- [ ] **Step 2:** Implement the mirrors.
- [ ] **Step 3:** Run it again. Expected: PASS. Commit: `feat(android): the phone knows a transcription's job and
  offers none`.

### Task 13: The NixOS module: the GPU for the transcription

**Files:**
- Modify: `nix/module.nix`:
  - `services.caracole.autochords.cuda` (bool, default false): picks `packages.autochords-cuda` as the default
    `autochords.package`;
  - `whisperModel` and `separatorModel` (nullOr path) join `modelEnv` as `CARACOLE_WHISPER_MODEL` and
    `CARACOLE_DEMUCS_MODEL`;
  - with `cuda`, caracole-web and caracole-admin get `PrivateDevices = false`, `DevicePolicy = "closed"`,
    `DeviceAllow` from nixpkgs' ollama module (`char-nvidiactl`, `char-nvidia-uvm`, `char-nvidia-caps`,
    `char-drm`, and the NVIDIA frontend);
  - also `SupplementaryGroups = [ "video" "render" ]` where the device nodes need them;
  - `/run/opengl-driver` stays readable;
  - the caracole-autochords unit is unchanged.
- Modify: `flake.nix:56` (the module's default package follows `cuda`)
- Modify: `nix/module-check.nix`: a `webCuda` system, and expectations:
  - "caracole-web.service with autochords.cuda sees the GPU and nothing else";
  - "caracole-autochords.service keeps PrivateDevices with autochords.cuda";
  - "without autochords.cuda, caracole-web keeps PrivateDevices".
- Modify: docs/install.md, docs/deploy.md (NixOS part), AGENTS.md `nix/` section

- [ ] **Step 1:** Write the expectations in module-check.nix. Run `nix build .#checks.x86_64-linux.module`.
  Expected: FAIL, listing the three.
- [ ] **Step 2:** Implement the options and unit settings.
- [ ] **Step 3:** Run it again. Expected: PASS. Then `nix flake check`. Commit: `feat(nix): autochords.cuda, the
  GPU for caracole serve's transcriptions alone`.

### Task 14: The guard measured, and the end-to-end checks

**Files:**
- Create: `docs/superpowers/plans/2026-11-20-transcribed-lyrics-results.md`. It records the measurements, not the
  lyrics: the repo is public.
- Modify: `src/caracole/autochords/words.py` (`STEM_WITHIN_DB`, `FLOOR_DB`, if the measurements move them), with
  Task 4's tests kept true.

- [ ] **Step 1:** In `nix develop .#autochords-cuda`, run the pipeline (Tasks 8–9 plus words.py), through a short
  script kept in the spike folder, on the spike folder's songs and two more the owner picks or the library has:
  - the example (`media/song.wav`): all words kept; none in 89.6–100.8 s; within 10% WER of `out/gpu-mix.json`;
  - 野人 (`media-yeren/`): 作词 作曲 李宗盛 and 请不吝点赞订阅 dropped; CER at most 9.9% against `ref/yeren.json`
    record 14196560; median line start within 0.19 s against `ref/yeren-lrclib.lrc`;
  - Vikingos veganos (`media-vikingos/`): the guard now marks the 0–27 s intro unsung (stem-to-mix);
  - an instrumental, and a song with sparse vocals: no invented words kept.

  Tune the two constants until all hold, and record them.
- [ ] **Step 2:** Run `caracole transcribe` on the example in a scratch library with
  `CARACOLE_TORCH_CUDA=1 nix develop .#autochords-cuda` (as the spike's `lib-*` folders were made): the sheet has
  NOTE, and `sheet (auto).html`'s data has `sung`.
- [ ] **Step 3:** Regenerate the corpus, run the whole suite, `-m autochords` in both shells, gradle, and
  `nix flake check`. Commit the results file and any constants: `docs(plan): the transcription measured on five
  songs`.
- [ ] **Step 4 (the owner's, after merging to main):**
  - in `~/nix_config/nixos/caracole.nix`, set `services.caracole.autochords.cuda = true;`;
  - run `nix flake update caracole`;
  - `sudo nixos-rebuild switch` (the owner runs it: sudo needs their password).

  Then, on the served page: Transcribe on the example's card; the job runs inside caracole-web on the GPU and ends
  Ready; the sheet lights its lines during autoscroll on the computer and, after a sync, on the phone.
