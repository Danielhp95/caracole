# AGENTS.md

What a coding agent needs before changing caracole. User documentation: README.md, docs/.

## What caracole is

caracole is a Python CLI, run every night by a NixOS service, that builds a private library
of sing-along chord sheets (Ultimate Guitar, LaCuerda), lyrics (LRCLIB), PDFs (ChordPro)
and Guitar Pro picks for the songs in `wanted.txt` and, optionally, Spotify. For a song
nobody has charted, `caracole autochords` writes a sheet from purchased audio with local
models (torch, optional). The design lives in three files:

- `plan.md`: design v2.1, and why. Its code sketches are older than the code: its module
  runs `caracole run --config …`, which the CLI rejects (`--config` is a root option:
  `caracole --config FILE run`).
- `docs/superpowers/plans/2026-10-18-caracole.md`: the task plan, with amendments A1–A7 made
  during the build: A2 optional Spotify and `wanted.txt`, A3 Chinese titles, A4 command
  plug-ins, A5 agent rules, A6 bare-id tabs, A7 `index.html` and `caracole search`.
- `docs/spike-2026-10-18.md`: what the live sites did when checked. It corrects plan.md:
  UG's `Pro` is a public Guitar Pro file; a slugged tab answers only at its slugged URL.

## Layout

In `src/caracole/`, `caracole run` (pipeline.py) runs these steps in order, each one even when
an earlier one failed:

| Step | Modules |
|---|---|
| sync | sources.py (`sync_sources`), wanted.py, spotify.py, songs.py |
| index | ug/sitemap.py, ug/index.py |
| match | match.py, ug/lookup.py |
| lyrics | lyrics.py |
| fetch | ug/fetch.py, ug/page.py (tab pages), ug/artist.py (artist pages), rank.py, coverage.py, versions.py |
| lacuerda | lacuerda.py (URLs, parsing), lacuerda_fetch.py (the step) |
| scan | music.py (Music/), inbox.py (Guitar Pro files in `_inbox/`) |
| render | chordpro.py (UG markup to ChordPro), render.py (PDFs) |
| todo | todo.py (`_todo.md`), library_page.py (`index.html`) |

Each step returns a `report.StepResult` (what it did, counted; the songs a provider's error
left, with the error; what needs the user), which report.py turns into the run's summary on
stdout and ntfy: a new step plugs in by returning one. The log goes to stderr, set up once
by the root callback (logs.py: `-v`, `-vv`, `-q`, journal priorities, redacted secrets).

Shared: config.py (caracole.toml, directories, secrets), db.py (schema, migrations, `kv`),
http.py (`PoliteClient`, robots rules), health.py (cooldowns, `events`), normalize.py (keys,
pinyin), overrides.py, library.py (song folders, safe file access), notify.py (ntfy).

- `commands/`: one module per area, each with `register(app)`, which `cli.build_app` finds
  by itself (A4: add a module, never edit cli.py). `_common.py` holds what they share:
  `load_cfg`, `open_db`, `load_ovr`, `exclusive`, `make_client`, `write_pages`, `fail`, `warn`.
  The logic of `caracole review` and `caracole search` is in review.py and search.py.
- `autochords/`: merge.py is pure Python and the only module `__init__.py` imports; btc.py
  (with the vendored btc_model.py and LICENSE-BTC) and beats.py need torch, librosa and
  beat_this; run.py runs them over the library.
- `tests/`: named after what they cover (test_fetch.py is ug/fetch.py's), and
  `test_commands_*.py` for the CLI. conftest.py has the `conn` and `cfg` fixtures (every
  directory under `tmp_path`), `add_song` and `subprocess_pythonpath`. helpers/ug_pages.py
  builds fake UG tab and artist pages, escaped the way UG escapes them
  (`from helpers.ug_pages import ...`). fixtures/ holds UG, LaCuerda, LRCLIB and ChordPro
  samples: real response shapes, synthetic lyrics and sheets.
- `nix/`: package.nix (`buildPythonApplication`; the wrapper puts `chordpro` on PATH and
  defaults `CARACOLE_CJK_FONT`; `withAutochords` adds the extra and the model files),
  autochords.nix (the model files, fixed-output), module.nix (`services.caracole`: units,
  timer, `caracole-admin`), module-check.nix (`checks.module`).
- `docs/`: usage.md (configuration, commands, the to-do page, overrides.toml, the library
  folder), deploy.md (the NixOS host), install.md, and the design files above.

## Development

    nix develop        # Python 3.14 with the dependencies, pytest, chordpro, ruff, sqlite3
    pytest -q          # from the repo root; pyproject.toml sets testpaths and pythonpath
    nix develop .#autochords -c pytest -m autochords   # the model tests

Both shells set `CARACOLE_CJK_FONT` to the packages' font. `.#autochords` adds torch,
beat-this and librosa, and sets `CARACOLE_BTC_WEIGHTS` and `CARACOLE_BEAT_CHECKPOINT` to the
files nix/autochords.nix fetches. Tests that need a real program or model skip without it:

| Needs | Tests | Set by |
|---|---|---|
| `chordpro` on PATH, or `CARACOLE_CHORDPRO_BIN` | real PDFs: test_render.py, test_render_all.py, test_chordpro.py | both shells |
| `CARACOLE_CJK_FONT`: one `.ttf` or `.otf` with CJK glyphs | Chinese PDFs | both shells |
| `pdftotext` on PATH, or `CARACOLE_PDFTOTEXT` | the PDFs' text in test_render_all.py (fewer checks without it, no skip) | neither: `nix shell --inputs-from . nixpkgs#poppler-utils` |
| torch, librosa, beat_this, and `CARACOLE_BTC_WEIGHTS` with `CARACOLE_BEAT_CHECKPOINT`, or `CARACOLE_MODELS_DIR` (searched for `btc_model_large_voca.pt` and `final0.ckpt`) | the tests marked `autochords` | `.#autochords` |
| `CARACOLE_BTC_MAJMIN_WEIGHTS`, or `btc_model.pt` under `CARACOLE_MODELS_DIR` | `test_the_major_minor_model_loads_too` | neither |
| `ffmpeg` on PATH | `test_btc_reads_aac_from_the_itunes_store` | neither |
| `chromium` on PATH | `index.html` in a real browser (test_library_page.py) | neither |

Before a change is done:

    nix develop -c pytest -q
    nix develop .#autochords -c pytest -m autochords   # when auto-chords is touched
    nix flake check

`nix flake check` builds three checks: `package` and `autochords` each run the suite (minus
the tests marked `autochords`), then check the wrapped `caracole`; `module` evaluates small
NixOS systems against nix/module-check.nix and loads their caracole.toml with config.py. One
at a time: `nix build`, `nix build .#autochords`, `nix build .#checks.x86_64-linux.module`.

Traps:

- The flake sees only files git tracks: `git add` a new file before a Nix build.
- The package builds from pyproject.toml, README.md, src/ and tests/ alone, in a sandbox
  without network (test_nix_package.py skips itself there). A subprocess test keeps the
  inherited PYTHONPATH (`conftest.subprocess_pythonpath`): the dependencies arrive on it.
- A dependency is listed three times: pyproject.toml, flake.nix (`runtimeDeps` or
  `autochordsDeps`) and nix/package.nix. It comes from nixpkgs: no pip, uv or PyPI pins.
- The version is in pyproject.toml and src/caracole/__init__.py; the package check compares
  `caracole --version` with pyproject's, and test_cli.py expects "caracole 0.1.0".
- A Nix file may set only `CARACOLE_*` variables the source reads (test_nix_package.py). A
  unit setting changes together with its expectation in nix/module-check.nix.
- `ruff check --select E4,E7,E9,F src tests` is clean; ruff's default rules and
  `ruff format --check` are not. Don't reformat code you aren't changing.

## How work is done here

- Test first: a test that fails (on the missing name or an assertion), then the code.
- Never a live request in a test: not to ultimate-guitar.com, lrclib.net, lacuerda.net or
  Spotify. Give `PoliteClient` an `httpx.MockTransport` as `transport=`; CLI tests
  monkeypatch `caracole.commands._common.transport_for` (and `_common.sleep`); pipeline tests
  pass `Services` with fake clients; Spotify tests use `FakeSpotify` (test_spotify.py) or
  patch `caracole.spotify.client_from_config`. Nothing blocks the network for the whole
  suite; only the package build's sandbox has none.
- `load_config` takes `env=`, and unit tests pass it. CLI tests read the real environment:
  clear what could leak in, as `OUTSIDE_SETTINGS` does in test_commands_sources.py.
- Heavy imports stay inside the command function: `cli.build_app` imports every module in
  commands/ on every start, and the default package has no torch.
  `test_commands_index_match.py::test_registering_the_commands_imports_neither_the_matcher_nor_the_index`
  fails when importing `caracole.cli` loads rapidfuzz, `caracole.match` or `caracole.ug`; the
  `test_registering_the_command*` tests of fetch, lyrics, sources and autochords do the same.
- Branch from `caracole-v1`, the default branch (`main` holds only the first design commit).
  Conventional commits, scoped by area: `fix(fetch): …`, `feat(lacuerda): …`,
  `test(commands): …`, `docs: …`, `build(nix): …`. No Claude or AI attribution anywhere:
  no Co-Authored-By trailer or "Generated with" line, in commits, code or docs.
- Keep docs/usage.md, docs/deploy.md and docs/install.md in step with behaviour (commands,
  options, defaults, files, messages) in the same commit; no test checks them.

## Invariants

Each names where it is enforced. Don't weaken one to make a test pass.

- **Politeness** (http.py, health.py, commands/_common.py).
  - Budgets per run: `ug` 60, `lrclib` 200, `lacuerda` 30 requests
    (`config.DEFAULT_PROVIDERS`); `caracole index build` at least 100 (`BUILD_BUDGET`,
    commands/index.py). Then `BudgetExhausted`.
  - One request at a time (a synchronous client, and the lock below), with a random pause
    from the provider's `delay` (10–20 s for UG and LaCuerda, 1–2 s for LRCLIB) between
    any two, redirect hops included: `PoliteClient` paces its own requests, and
    `_common._pause_after_last_request` its first after the last one any caracole sent.
  - A 403, a 429 or a challenge page raises `ProviderBlocked`: the client sends nothing
    more that run, `health.record_block` cools the provider down for 24 h × 2^(k−1) + 2 h after
    the k-th block in a row (so the next nightly run is always skipped), and nothing retries or works around it (no proxies).
  - No URL robots.txt closes is asked for, or followed to (`http.ROBOTS_DISALLOW`,
    `robots_disallows`): not UG's `/search.php` (matching is local, against the sitemap
    index), `/tab/download`, `/tab/print?` or `/download/public/`.
  - Every accepted 200 and 404 is cached forever, in `cache_dir/http/<provider>/`.
- **Errors are never misses.** A block, a spent budget, an HTTP or network error, or a page
  that won't parse (`PageParseError`) never makes a song not found or its lyrics missing:
  the song waits for the next run (http.py, pipeline.py, ug/fetch.py, lyrics.py;
  `test_pipeline.py::test_ug_block_cools_down_and_never_marks_not_found`,
  `test_fetch.py::test_parse_error_is_not_a_miss`). A block or a spent budget exits 0; a
  bug exits 1, which fires the unit's ntfy alert.
- **Slugged tabs only at their slugged URL**, as UG answers 404 for them at `/tab/{id}`:
  the index keeps each tab's sitemap path (`ug_index.path`), from which ug/page.py
  `page_url` and ug/lookup.py `IndexTab.url` and `tab_url_for` build it. **Bare-id tabs**
  (a tenth of UG's, and every tab of an artist with an accented or non-Latin name) are
  found on the artist's UG page (ug/artist.py, the `artist_page` route in ug/fetch.py),
  `/artist/<name>_<id>` or `/artist/<id>` (`overrides.artist_page_address`), its URL from
  `[artist_url]` or learned from a tab page into kv `ug:artist_url:<artist key>`. An
  `[artist_url]` tab page is read once, through the run's client, for the page it links to:
  kv `ug:pasted_tab:<tab id>` (`test_fetch.py::test_slugged_tabs_fetched_at_their_slugged_url`,
  `::test_bare_id_chords_of_a_matched_song_come_from_its_artist_page`, tests/test_live_banma.py).
- **Guitar Pro is assisted only.** config.py refuses any `guitar_pro_mode` but "assisted";
  ug/fetch.py picks Guitar Pro and Power Tab versions and downloads none; the to-do page
  lists them, and inbox.py files what the user drops into `_inbox/`. Official and
  non-public versions are never used.
- **Chinese is compared as pinyin** (`normalize.romanize`, with pypinyin) in match.py,
  coverage.py, music.py, search.py, library_page.py and ug/fetch.py; identity keys also fold
  Traditional characters to Simplified. Where a name caracole didn't write meets yours (UG's
  artist pages and slugs, purchases' tags, downloads), it is compared by `normalize.name_forms`,
  which also gives the parts of a name in two scripts ("Song Dongye (宋冬野)"); forms are for
  comparing and never make a key. A change to `clean_title`, `slug_key` or
  `identity_key` that can change a key bumps `normalize.KEY_VERSION`:
  `songs.ensure_current_keys`, run before songs are looked up, listed or added, then re-keys
  them once and merges those that now share a key. It re-keys `songs` only; `ug_index` keys
  change when a sitemap is parsed again. Name new per-song kv keys `<prefix><song id>` and
  add the prefix to `songs._PER_SONG_KV`, so a merge deletes them.
- **Schema changes go through db.py**: bump `SCHEMA_VERSION` and add the script to
  `_MIGRATIONS`. `_migrate` copies an existing database to `caracole.sqlite.v<N>.bak`
  (`VACUUM INTO`), then runs each script in one `BEGIN IMMEDIATE` transaction with its
  `PRAGMA user_version` (a script never begins or commits one itself). A newer database
  raises `DatabaseTooNew`, and `_common.open_db` exits 2 (tests/test_db.py).
- **overrides.toml** is written only through the `add_*` functions of overrides.py: tomlkit,
  so the user's comments and layout survive, then `library.write_atomic`. It is read only
  as a regular file (`test_overrides.py::test_writers_preserve_comments_and_roundtrip`).
- **The library is synced**: Syncthing and every device can write to it. Read a file there
  with `library.read_regular` (or `open_regular`: no symbolic link followed, regular files
  only), and write one with `library.write_atomic`: a random temporary name opened
  exclusively, then a rename. Never `mkstemp`, whose mode 0600 hides files from Syncthing.
  Nothing private goes there: the database, the Spotify token, the lock and the HTTP cache
  stay in `state_dir` and `cache_dir`, and chordpro works on a copy in a 0700 folder under
  the cache (render.py). tests/test_library_safety.py.
- **One caracole at a time**: `_common.exclusive` holds an flock on `state_dir/caracole.lock`,
  re-entrant within a process, and the clients of `make_client` hold it until closed.
  Every command that asks UG, LRCLIB or LaCuerda for pages or writes the library takes it;
  `search`, `match --dry-run` and `index stats` only read and never wait. `review` takes it
  only after its questions (commands/library.py), so the nightly run never waits for an
  answer (`test_commands_lock.py::test_review_never_holds_the_lock_while_it_waits_for_you`).
- **Spotify is optional, and wanted.txt is always a source.** `sources.sync_sources` syncs
  wanted.txt first, then Spotify, importing spotipy, only when `cfg.spotify.enabled` (a
  `client_id` is set); any Spotify failure becomes a state on its report, never an error.
