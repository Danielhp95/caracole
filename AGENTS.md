# AGENTS.md

What a coding agent needs before changing caracole. User documentation: README.md, docs/.

## What caracole is

caracole is a Python CLI, run every night by a NixOS service, that builds a private library
of sing-along chord sheets (Ultimate Guitar, LaCuerda), lyrics (LRCLIB), PDFs (ChordPro)
and Guitar Pro files (downloaded from gtptabs.com, or picked on UG for the user to
download) for the songs in `wanted.txt` and, optionally, Spotify. For a song
nobody has charted, `caracole autochords` writes a sheet from audio with local models
(torch, optional): a purchase, or audio the nightly run takes from YouTube with yt-dlp
(youtube.py, youtube_fetch.py), a few songs a night, only where auto-chords is. The
design lives in three files:

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
| icons | icons.py (each source's mark: a site's favicon, fetched once, sanitized, in `cache_dir/icons/`) |
| index | ug/sitemap.py, ug/index.py |
| match | match.py, ug/lookup.py |
| lyrics | lyrics.py |
| fetch | ug/fetch.py, ug/page.py (tab pages), ug/artist.py (artist pages), rank.py, coverage.py, versions.py |
| lacuerda | lacuerda.py (URLs, parsing: artist, version and listing pages), lacuerda_fetch.py (the step's sheets), lacuerda_index.py (then its listings of every artist into `lacuerda_index`, schema 6, resumed across runs, with the songs of the artist pages read; `find` is for searches, not wired in yet, `artist_slugs` for the sheets) |
| scan | music.py (Music/; `Names`, how alike a file's names and a song's are, for purchases and the inbox), inbox.py (Guitar Pro files and scores in `_inbox/`), musicxml.py (a MusicXML file's header) |
| gtptabs | gtptabs.py (URLs, sitemap rows, artist pages, file headers), gtptabs_fetch.py (the step) |
| musescore | musescore.py (song page URLs, a song's pages), musescore_fetch.py (the step: song sitemaps into `musescore_index`) |
| youtube | youtube.py (picking a song's video from a search, `YtDlp`: running yt-dlp), youtube_urls.py (a video's address, the standard library alone: overrides.py's `[youtube]`), youtube_fetch.py (the step: which songs, the audio in `cache_dir/youtube/`, kv `youtube:<song id>`, each song's state for the pages) |
| render | chordpro.py (UG markup to ChordPro), render.py (PDFs, styled by chordpro-style.json), viewer/ (sheet.html, and songbook.html in book.py, both built from page.py's pieces: `_page`, the head and its policy, `_footer`, `_song_html`, `viewer_csp`, which is `book.songbook_csp` too; `page.build_version` hashes `page.BUILD_FILES`, what a page is made from: a module the viewer comes to import goes there, test_viewer_book.py checks; theory.py and `voicings.voicing_keys` keep their answers, so `Chord` and `Key` stay frozen with every field compared, and a list handed out is a copy: test_viewer_theory.py), songbook.py (the songbooks of songbooks.toml, in `Library/_songbooks/`) |
| todo | todo.py (`_todo.md`), library_page.py (`index.html`) |

Each step returns a `report.StepResult` (what it did, counted; the songs a provider's error
left, with the error; what needs the user), which report.py turns into the run's summary on
stdout and ntfy: a new step plugs in by returning one. The log goes to stderr, set up once
by the root callback (logs.py: `-v`, `-vv`, `-q`, journal priorities, redacted secrets).

Shared: config.py (caracole.toml, directories, secrets), db.py (schema, migrations, `kv`,
`savepoint`: atomic writes on the autocommit connection), http.py (`PoliteClient`, robots
rules, `stale` and `read_once_more` for cached answers), health.py (cooldowns, `events`),
normalize.py (keys, pinyin), inline.py (a page's inline script or style by its hash,
`sha256_source`, and its JSON data blocks, `json_block`, each `<` escaped; the standard
library alone), overrides.py, library.py (song folders, safe file access), notify.py
(ntfy), site_index.py (a site's sitemaps into a table, resumed across runs: gtptabs.com's
and MuseScore's), keys.py (a song's musical key and its source, for info.json,
`index.html` and `search --key`), removal.py (`caracole remove` and the web page's
Remove: a song's wanted.txt lines, its record and the files caracole wrote; the
tombstones it leaves are songs.py's, in the `removed` table).

- `commands/`: one module per area, each with `register(app)`, which `cli.build_app` finds
  by itself (A4: add a module, never edit cli.py). `_common.py` holds what they share:
  `load_cfg`, `open_db`, `load_ovr`, `exclusive`, `make_client`, `make_youtube`,
  `write_pages`, `fail`, `warn`, `song_named` (the song a `--song` names).
  `caracole get` (commands/get.py) is one song looked up now, in one process: get.py runs
  the run's steps for that song alone (`only=` / `songs=` of lyrics.py, lacuerda_fetch.py,
  gtptabs_fetch.py and `match.match_all`), sheet first (one versions page and the best-rated
  sheet, then `Progress.readable`), with interactive clients; `--progress` prints a JSON line
  per event (`get.progress_line`) for caracole serve.
  The logic of `caracole review`, `caracole search`, `caracole remove` and `caracole songbook`
  is in review.py, search.py, removal.py and songbook.py. search.py reads a query as a
  title, an artist or both (each hit's `via`); `find_index` (with your songs, `found`)
  answers `caracole search` and `/api/search`: the artists a query
  names (`ArtistHit`, never a catch-all), the index's songs, `lead` and `best` (what Enter
  may act on, None for no clear song), with
  `artist_songs` and `library_by_artist`; tab counts are its only popularity, and Chinese
  pinyin counts only as whole words of a key, as in match.py. `search_gtptabs` and
  `search_musescore` read gtptabs.com's and MuseScore's tables (`SiteHit`; MuseScore's by
  exact title keys alone, the query's or what it leaves beside the artist of a song of that
  title, `_known_song`: a possible match), never the sites. Its prefilter reads
  ug/key_search.py (`rows_like`: the keys' trigram index, `ug_keys_fts`, schema 5), which
  must find exactly what a `LIKE` scan of `ug_index` finds
  (`test_search.py::test_the_prefilter_finds_through_the_key_index_what_a_scan_of_every_row_finds`),
  except that a pattern in more than `KEYS_PER_PATTERN` keys (a common word) brings in its
  shortest keys and those every pattern is in
  (`::test_a_common_word_brings_in_its_shortest_keys_and_those_every_word_is_in`).
- `web/`: `caracole serve` (commands/serve.py): security.py (host names, cross-origin
  writes, tokens), files.py (library files, no link followed; `read_written_page`, a page
  caracole wrote, while it holds the bytes a lookup says it wrote), jobs.py (the queue: each
  request runs the `caracole` CLI at `-v` in a child process, one command at a time; a
  lookup is one `caracole get --progress`, whose JSON lines become `Job.stages`, and
  `Job.as_json` is a job as data), status.py (the one line a request shows on its card and
  on /jobs, read from the job's steps and, once it is over, from the song's state, never
  from which commands ran: a step's label is that line while it runs, "Adding to the
  library…", and a lookup's running stage has one of its own, `status.STAGE_LINES`), app.py (the routes; `/jobs.json` and the forms answer the page's script in
  JSON, every refusal as data; `/api/search` for search as you type, through search.py's
  public functions (`find_index`, `found`, `search_gtptabs`, `search_musescore`; `skipped`, the
  sites it left out and why), one at a time, the newest first, an older one's
  SQL interrupted once a newer waits (`set_progress_handler`); `/api/artist?key=` an
  artist's songs, 50 at a time; `/api/jobs[/<id>]`; every `/api/` read refused to
  another site's fetch, `security.own_page_read`; `POST /lookup`, which runs a song your
  library has, by its id or found from the UG pick (`_Mine`: its match, or its names'
  `name_forms`), under its own names and writes no wanted.txt line for it;
  `written_pages`, each kind of page caracole writes into the library by file name, with
  its record and its CSP: the sheet viewers and songbook.html), songbooks.py (the songbook
  forms, each queued as its `caracole songbook` command; `songbook_of` reads a job's key back,
  the songbook it changes, and once it is over `/jobs.json` gives the Songbooks section drawn
  again, which the page puts in place of its own), lookup_page.py (the lookup page:
  its script, `createElement` and `textContent` only, allowed by hash, connects to the
  server alone; its results are the library's rows, `library_page.ROWS_SCRIPT` and
  `ROWS_STYLE` through its row builders, `ugHit` and `artistHit` too, and a song you have opens its viewer;
  Enter acts on `/api/search`'s `best`, or opens the leading artist's songs, and never
  spends a request without one),
  pages.py, server.py (`http.server`). The library page is
  library_page.py's, with `WebControls`; its script posts the forms with fetch() and asks
  /jobs.json how they go. Its one bar filters your songs as you type and, on Enter or Search
  all, lists `/api/search`'s answer under them (served; the file shows the `caracole search`
  line to run), each result's Get it a `POST /lookup` whose `view` the page tracks in the
  result's row; Enter never spends a request.
- `autochords/`: merge.py is pure Python and the only module `__init__.py` imports; btc.py
  (with the vendored btc_model.py and LICENSE-BTC) and beats.py need torch, librosa and
  beat_this; run.py runs them over the library.
- `tests/`: named after what they cover (test_fetch.py is ug/fetch.py's), and
  `test_commands_*.py` for the CLI. conftest.py has the `conn` and `cfg` fixtures (every
  directory under `tmp_path`, in /dev/shm if it will do; `conn` copies a database migrated once
  per process), `add_song` and `subprocess_pythonpath`. helpers/browser.py's `dump_dom` opens
  pages in one Chromium per process, each in a fresh context, for a test marked `@in_chromium`
  (`touch=True`: a touch screen, where `pointer: coarse` matches; `media=`: dark mode);
  helpers/targets.py measures a page's controls there: `small_targets`, any under 44 px, and
  `weak_edges`, a field's edge under 3:1. helpers/locks.py `waiting_for` sees a command wait
  for caracole's lock. test_harness.py tests what makes the suite fast. helpers/ug_pages.py
  builds fake UG tab and artist pages, escaped the way UG escapes them
  (`from helpers.ug_pages import ...`). helpers/gtptabs_site.py is `FakeGtpTabs`, a fake
  gtptabs.com behind a real `PoliteClient`, with synthetic Guitar Pro, Guitar Pro 6 and 7
  and Power Tab files (a format's magic header, then filler). helpers/musescore_site.py
  is `FakeMuseScore`, its song sitemaps and the challenge Cloudflare answers caracole
  with (`challenge()`). helpers/lacuerda_site.py is `LaCuerdaSite`, LaCuerda's listings
  of every artist (`listing_page`, with `Last-Modified` and 304s) and artist pages
  (`artist_page`). helpers/fake_ytdlp.py is `FakeYtDlp`, a yt-dlp the test writes as a
  script that answers from a plan and logs its arguments, and `route_on`, a config with the
  YouTube route on (auto-chords' packages taken to be there, model files, the fake).
  helpers/rendered.py keeps a sheet and renders it with a stand-in
  for chordpro (`rendered_song`), so its viewer is one caracole wrote; helpers/chromium.py
  drives a headless Chromium of the test's own over the DevTools protocol (a pipe, the standard
  library), for a page whose CSP refuses a test's script; helpers/browser.py's `Browser` is the
  same with typing, Enter, clicks, touches and the layout read back, on real time, for the lookup
  page's tests and the library page's bar (test_web_page_search.py: a real `caracole serve`, its
  queue running a fake `caracole get`), the viewer's scrolling (test_viewer_scroll.py: a page on
  `dump_dom`'s virtual time draws no frames), its bar (test_viewer_bar.py: a finger's drag is touch
  events, as `Input.synthesizeScrollGesture` scrolls nothing headless) and its settings and chord
  card, docked or beside the song (test_viewer_panels.py), which share helpers/viewer_pages.py: a
  viewer written and opened in it (`written`, `viewer`), a finger's `drag`, `tap` and `tap_at`,
  `rest` until the page stops gliding, and keys. Both
  resolve no host name (`helpers.browser.NO_LOOKUPS`), and their tests are `@in_chromium` too.
  fixtures/ holds UG, LaCuerda, LRCLIB,
  gtptabs.com, MuseScore and ChordPro samples: real response shapes, trimmed, and
  synthetic lyrics, sheets and files.
- `nix/`: package.nix (`buildPythonApplication`; the wrapper puts `chordpro` on PATH and
  defaults `CARACOLE_CJK_FONT`; `withAutochords` adds the extra, the model files and
  `yt-dlp` on PATH), autochords.nix (the model files, fixed-output), module.nix
  (`services.caracole`: units, timer, `caracole-admin`; with auto-chords on, the nightly
  unit runs the auto-chords package, for its youtube step, and caracole-web and
  `caracole-admin` run it too, so their pages agree), module-check.nix
  (`checks.module`).
- `docs/`: usage.md (configuration, commands, the to-do page, overrides.toml, the library
  folder), deploy.md (the NixOS host), install.md, and the design files above.
  web-search.md designs a search-API fallback for matching, not built.

## Development

    nix develop        # Python 3.14 with the dependencies, pytest, pytest-xdist, chordpro, ruff, sqlite3
    pytest -q                         # the whole suite, from the repo root, on up to 12 cores
    pytest -q -m "not slow"           # the quick loop, a few seconds
    pytest -q -m "not slow" --lf -x   # what failed last time, stopping at the first failure
    pytest -q tests/test_fetch.py     # given paths, pytest runs them in one process
    nix develop .#autochords -c pytest -m autochords   # the model tests

Given no paths, pytest runs on pytest-xdist workers (conftest.py: `-n auto`, at most 12,
`--dist worksteal`); `-n 0` runs it in one process, as `--pdb`, `--trace`, `-s` and
`-m autochords` do. `slow` marks a test that starts a browser (`helpers.browser.in_chromium`),
chordpro or the models (`@pytest.mark.chordpro` and `autochords` add `slow`) or another
process: mark a new one too. The whole suite stays the gate before a commit. tmp_path is in
/dev/shm, and stays on disk with `--basetemp` or `PYTEST_DEBUG_TEMPROOT`, or when /dev/shm is
noexec or has less than 1 GB free (a container's).

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
| `chromium` on PATH | `index.html`, `sheet.html`, `songbook.html`, the lookup page and caracole serve's own pages in a real browser (test_library_page.py, test_library_page_songbooks.py, test_viewer.py, test_viewer_book.py, test_viewer_layout.py, test_viewer_preamble.py, test_viewer_shapes.py, test_viewer_scroll.py, test_viewer_bar.py, test_viewer_panels.py, test_web_lookup_page.py, test_web_pages.py), a viewer `caracole serve` sends (test_web_server.py), the page served by a real `caracole serve` (test_web_page.py, test_web_page_search.py), and the shared browser itself (test_harness.py) | neither |

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
- Every pytest-xdist worker collects the suite itself and must find the same test ids:
  parametrize with nothing that changes between processes, such as a zip's clock-dated entries
  (helpers/zips.py `dated_entry`), random values or a set's order.

## How work is done here

- Test first: a test that fails (on the missing name or an assertion), then the code.
- Never a live request in a test: not to ultimate-guitar.com, lrclib.net, lacuerda.net,
  gtptabs.com, musescore.com, YouTube or Spotify. Give `PoliteClient` an
  `httpx.MockTransport` as `transport=`; CLI tests monkeypatch
  `caracole.commands._common.transport_for` (and `_common.sleep`); pipeline tests pass
  `Services` with fake clients (`FakeGtpTabs.client` and `FakeMuseScore.client` make real
  ones); Spotify tests use `FakeSpotify` (test_spotify.py) or patch
  `caracole.spotify.client_from_config`; YouTube tests run `FakeYtDlp` as `ytdlp_bin`,
  never a real yt-dlp: conftest.py points `CARACOLE_YTDLP_BIN` at no program for every
  test, so a command reading the real environment in `nix develop .#autochords` (torch, the
  model paths, yt-dlp on PATH) finds the route off. Nothing blocks the network for the
  whole suite; only the package build's sandbox has none.
- `load_config` takes `env=`, and unit tests pass it. CLI tests read the real environment:
  clear what could leak in, as `OUTSIDE_SETTINGS` does in test_commands_sources.py.
- Heavy imports stay inside the command function: `cli.build_app` imports every module in
  commands/ on every start, and the default package has no torch.
  `test_commands_index_match.py::test_registering_the_commands_imports_neither_the_matcher_nor_the_index`
  fails when importing `caracole.cli` loads rapidfuzz, `caracole.match` or `caracole.ug`; the
  `test_registering_the_command*` tests of fetch, lyrics, sources, autochords and youtube do
  the same. httpx, with the rich and pygments it brings, is a third of a start: http.py
  imports it inside the functions that use it, and `_common` makes its client class on first
  use (`_locked_client`).
  `test_commands_index_match.py::test_a_command_that_sends_no_request_imports_no_http_client`
  fails when importing `caracole.cli` and reading a `[youtube]` entry (youtube_urls.py) loads
  httpx, rich, `caracole.http` or `caracole.youtube`.
  music.py imports mutagen in `read_audio` alone: inbox.py, which the pages import,
  scores names with its `Names` (`test_music.py::test_the_pages_load_no_tag_reader`).
- Branch from `caracole-v1`, the default branch (`main` holds only the first design commit).
  Conventional commits, scoped by area: `fix(fetch): …`, `feat(lacuerda): …`,
  `test(commands): …`, `docs: …`, `build(nix): …`. No Claude or AI attribution anywhere:
  no Co-Authored-By trailer or "Generated with" line, in commits, code or docs.
- Keep docs/usage.md, docs/deploy.md and docs/install.md in step with behaviour (commands,
  options, defaults, files, messages) in the same commit; no test checks them.

## Invariants

Each names where it is enforced. Don't weaken one to make a test pass.

- **Politeness** (http.py, health.py, commands/_common.py), at two paces
  (`config.ProviderPolicy`; `_common.make_client` picks one).
  - **Bulk work**: the nightly run (its index refresh included), `caracole index build`
    and every command but `caracole get`. Budgets per run: `ug` 60, `lrclib` 200,
    `lacuerda` 30 (its sheets first, then its listings of every artist), `gtptabs` 20,
    `musescore` 10 requests, `youtube` 6 yt-dlp runs
    (`config.DEFAULT_PROVIDERS`); `caracole index build` at least 100 (`BUILD_BUDGET`,
    commands/index.py). Then `BudgetExhausted`. Between any two requests to a provider, a
    random pause from its `delay` (10–20 s for UG, LaCuerda, gtptabs.com and MuseScore,
    1–2 s for LRCLIB).
  - **An interactive lookup**: `caracole get`, one song asked for just now (caracole serve's
    lookups run it). Its clients are `make_client(..., interactive=True)`: a random gap from
    `lookup_delay` (default 0.5–1.5 s; `[0, 0]` allowed) between two requests to a provider,
    a budget of `lookup_requests` (6) requests to it for the song, and at most
    `lookup_per_hour` (60) for every lookup of the last hour together (`_common.lookup_policy`,
    counting the `events` of runs named `lookup:…`). What follows the sheet, which the nightly
    run would do anyway (get.py's `ug` stage, LaCuerda for a song with a sheet), spends only what
    leaves `get.SHEETS_SHARE` (half) of that hour's requests for sheets (`_Lookup.after_the_sheet`).
    Then `BudgetExhausted`: the rest waits for the nightly run. Nothing else is looser for a
    lookup, and a lookup never runs yt-dlp.
  - Either pace: one request at a time per provider (a synchronous client, and the lock
    below), redirect hops included. `PoliteClient` paces its own requests, and
    `_common._pause_after_last_request` its first after the last one any caracole sent
    (kv `http:last_request:<provider>`, to the fraction of a second, else `events`). No gap
    is shorter than the host's robots.txt `Crawl-delay` (`http.ROBOTS_CRAWL_DELAY`, from
    the same `User-agent: *` groups as the rules below: none has one today).
  - Only a provider in `config.SWITCHABLE` (`gtptabs`, `musescore`, `youtube`) can be
    turned off (`enabled = false`): then it gets no client and its step is skipped.
  - A 403, a 429 or a challenge page raises `ProviderBlocked`: the client sends nothing
    more that run, `health.record_block` cools the provider down for 24 h × 2^(k−1) + 2 h after
    the k-th block in a row (so the next nightly run is always skipped), and nothing retries or works around it (no proxies).
  - No URL robots.txt closes is asked for, or followed to (`http.ROBOTS_DISALLOW`,
    `robots_disallows`): not UG's `/search.php` (matching is local, against the sitemap
    index), `/tab/download`, `/tab/print?` or `/download/public/`, nor gtptabs.com's
    `/ru/` (half of its sitemaps), `/search/` or `/storage/` (an artist's "Download all"
    archive), nor musescore.com's `/api/jmuse`, `/score/*/download/*`, `/sheetmusic?`
    (its search) or `/oembed/*`. A host's rules are the `User-agent: *` group of its live
    robots.txt (tests/fixtures/gtptabs/ and tests/fixtures/musescore/robots.txt).
  - **The one exception is YouTube**, the owner's explicit choice for a handful of their
    own songs a night: its robots.txt closes `/results` and `/youtubei/` to crawlers, and
    yt-dlp uses both, against its terms too. Provider `youtube` (youtube.py) is the one
    place caracole runs yt-dlp, and only on these terms: for a song with no human sheet
    (`todo.songs_to_buy`) and only where auto-chords can make chords of it
    (`youtube_fetch.route_problem`: the packages, both model files, yt-dlp; the default
    package never runs it); within the budget, one run at a time, a pause from `delay`
    (15–30 s) between two runs (`YtDlp._pause`, and `_common._pause_after_last_request`
    via `make_youtube`), and yt-dlp's own pauses inside one (`--sleep-requests`,
    `--sleep-interval`); `--retries 0`; audio alone (`-x`), never a playlist, the song's
    name after `--`, arguments a list and never a shell; no cookies, login, config files,
    plugins (PO-token providers among them) or remote code (`--ignore-config`,
    `--no-cookies`, `--no-cookies-from-browser`, `--no-plugin-dirs`,
    `--no-remote-components`); none of caracole's secrets (`ytdlp_env` passes no
    `CREDENTIALS_DIRECTORY` or `CARACOLE_*` variable); a stop or Ctrl-C stops its process
    group too; a bot check, an HTTP 429 or 403, a rate limit or a captcha
    is `ProviderBlocked`, honoured like any block (tests/test_youtube.py). Everything else
    keeps honouring robots.txt; widen nothing here without the owner, and copy it to no
    other site.
  - Every accepted 200 and 404 is cached forever, in `cache_dir/http/<provider>/`.
- **Errors are never misses.** A block, a spent budget, an HTTP or network error, or a page
  that won't parse (`PageParseError`, `GtpTabsParseError`, `LaCuerdaParseError`,
  `LrclibParseError`) never makes a song not found, its lyrics missing or its Guitar Pro
  file a miss: the song waits for the next run (http.py, pipeline.py, ug/fetch.py, lyrics.py,
  gtptabs_fetch.py; `test_pipeline.py::test_ug_block_cools_down_and_never_marks_not_found`,
  `test_fetch.py::test_parse_error_is_not_a_miss`,
  `test_gtptabs_fetch.py::test_a_spent_budget_is_no_miss`). A cached answer that won't
  parse is asked for once more, past the cache, before it is an error, so a bad night
  isn't replayed every night after: `http.read_once_more` for LRCLIB, LaCuerda and
  gtptabs.com, ug/fetch.py's `_get_page` for UG
  (`test_lyrics_pending.py::test_a_cached_answer_that_isnt_json_is_asked_for_once_more`).
  On gtptabs.com only an artist page that answered without a candidate is a miss, asked
  about again after 30 days; on
  YouTube only a search that answered without a video that fits (youtube_fetch.py,
  `test_youtube_fetch.py::test_an_error_is_no_miss_and_the_song_waits_for_the_next_run`); of
  LaCuerda's listings only a page that answers 404 loses its artists, never one that errs or
  won't parse (`test_lacuerda_index.py::test_a_page_that_wont_parse_is_an_error_and_its_artists_stay`). A
  block or a spent budget exits 0; a bug exits 1, which fires the unit's ntfy alert.
- **Slugged tabs only at their slugged URL**, as UG answers 404 for them at `/tab/{id}`:
  the index keeps each tab's sitemap path (`ug_index.path`), from which ug/page.py
  `page_url` and ug/lookup.py `IndexTab.url` and `tab_url_for` build it. **Bare-id tabs**
  (a tenth of UG's, and every tab of an artist with an accented or non-Latin name) are
  found on the artist's UG page (ug/artist.py, the `artist_page` route in ug/fetch.py),
  `/artist/<name>_<id>` or `/artist/<id>` (`overrides.artist_page_address`), its URL from
  `[artist_url]` or learned from a tab page into kv `ug:artist_url:<artist key>`. An
  `[artist_url]` tab page is read once, through the run's client, for the page it links to:
  kv `ug:pasted_tab:<tab id>`; one that won't parse waits as any tab page does, kv
  `ug:unreadable:<tab id>` (`test_fetch.py::test_slugged_tabs_fetched_at_their_slugged_url`,
  `::test_bare_id_chords_of_a_matched_song_come_from_its_artist_page`, tests/test_live_banma.py).
- **Guitar Pro: Ultimate Guitar's assisted, gtptabs.com's downloaded.** config.py refuses
  any `guitar_pro_mode` but "assisted", which is UG's mode (its robots.txt closes
  `/tab/download`); ug/fetch.py picks Guitar Pro and Power Tab versions and downloads
  none; the to-do page lists them, and inbox.py files what the user drops into `_inbox/`.
  Official and non-public versions are never used. gtptabs_fetch.py downloads from
  `/tabs/download/{id}.html` alone, never logged in, one file for a song with no Guitar
  Pro or Power Tab file in `files` (filed or downloaded, deleted since or not), and keeps
  it only when `gtptabs.sniff` reads a Guitar Pro or Power Tab header: as the lowest
  `guitar-N` no file holds (`inbox.guitar_number`), with its version (provider
  `gtptabs`). It never replaces or deletes a file
  (`test_gtptabs_fetch.py::test_a_song_with_a_guitar_pro_file_gets_no_other`,
  `::test_a_number_a_file_in_the_folder_holds_is_never_reused`).
- **MuseScore is links and the inbox.** musescore_fetch.py asks MuseScore for its song
  sitemaps alone: never a song page, a score, a download or `/api/jmuse`, and never logged
  in (`test_musescore_fetch.py::test_caracole_asks_for_the_sitemaps_alone`). Its Cloudflare
  challenge is a block like a 403, and the to-do page then says plainly that MuseScore is
  blocking caracole, even with no page to list (`todo._musescore_pages`). Every match is on
  the title alone, a possible match (`musescore.song_pages`). inbox.py files what the user
  downloads (`SCORE_EXTENSIONS`) as `score-N.<ext>`, never as `sheet.pdf`, under the
  song's one `inbox` version of kind `score`; a MusicXML header is read with
  `musicxml.header`, up to the part list only.
- **Chinese is compared as pinyin** (`normalize.romanize`, with pypinyin) in match.py,
  coverage.py, music.py, search.py, library_page.py, ug/fetch.py and lacuerda_index.py
  (whose keys are pinyin); identity keys also fold
  Traditional characters to Simplified. Where a name caracole didn't write meets yours (UG's
  artist pages and slugs, LaCuerda's listings, purchases' tags, downloads), it is compared by `normalize.name_forms`,
  which also gives the parts of a name in two scripts ("Song Dongye (宋冬野)"); forms are for
  comparing and never make a key. A change to `clean_title`, `slug_key` or
  `identity_key` that can change a key bumps `normalize.KEY_VERSION`:
  `songs.ensure_current_keys`, run before songs are looked up, listed or added, then re-keys
  them once and merges those that now share a key. It re-keys `songs` and the tombstones of
  removed songs (`removed`, `songs._rekey_removed`) only; `ug_index` keys
  change when a sitemap is parsed again, and the keys of a table site_index.py fills
  (`gtptabs_index`, `musescore_index`) at its next refresh, which parses every sitemap
  again, an unchanged one from the cache
  (`test_gtptabs_fetch.py::test_new_keys_read_the_sitemaps_again_even_when_they_are_unchanged`);
  `lacuerda_index` keys are made again from the names it stores, with no request
  (`lacuerda_index.ensure_current_keys`, at its next refresh or store).
  Name new per-song kv keys `<prefix><song id>` (or `<prefix><song id>:<more>`) and add the
  prefix to `songs._PER_SONG_KV`, so a merge or a removal deletes them (`songs.delete_song_kv`).
- **A removed song stays removed until you ask for it again.** `caracole remove` (removal.py)
  takes the song's lines out of wanted.txt first, and stops before anything else when the
  file can't be read; then, in one savepoint, leaves its tombstone (`songs.mark_removed`:
  table `removed`, its key, name and source ids) and deletes its record (versions and files
  cascade), its per-song kv, its source ids' `songs:fields:` and its lines' `wanted:first_seen:`;
  then the files caracole wrote. `songs.upsert_song`, the one way a source adds a song, finds a
  tombstone by source id, or by key when no song has it, and raises `songs.SongRemoved`
  unless the source asks again (`_unless_removed`): a wanted.txt line always does (`caracole
  add`, the web page, a line typed), and any other source only with a track added after the
  removal. Spotify counts what stays out in `SyncStats.removed`. The to-do page suggests no
  removed song (`todo._suggestions`). Nothing else may create a song
  (`test_removal.py::test_the_next_sync_brings_nothing_back_until_you_ask_for_the_song_again`,
  `test_songs.py::test_no_spotify_track_added_before_a_songs_removal_brings_it_back`).
- **Schema changes go through db.py**: bump `SCHEMA_VERSION` and add the script to
  `_MIGRATIONS`. `_migrate` copies an existing database to `caracole.sqlite.v<N>.bak`
  (`VACUUM INTO`), then runs each script in one `BEGIN IMMEDIATE` transaction with its
  `PRAGMA user_version` (a script never begins or commits one itself). A newer database
  raises `DatabaseTooNew`, and `_common.open_db` exits 2 (tests/test_db.py). Writes that
  apply whole or not at all go in `db.savepoint(conn, name)`, which nests in a caller's:
  the connection is in autocommit mode, where `with conn:` opens no transaction
  (`test_db.py::test_a_savepoint_undoes_its_whole_block_and_nests`, tests/test_versions.py).
- **overrides.toml** is written only through the `add_*` functions of overrides.py: tomlkit,
  so the user's comments and layout survive, then `library.write_atomic`. It is read only
  as a regular file (`test_overrides.py::test_writers_preserve_comments_and_roundtrip`).
  So is **songbooks.toml**, through the writers of songbook.py (`make_songbook`, `add_to_songbook`,
  ...): a file that won't parse is a `SongbookFileError`, which stops the songbooks and nothing else
  (`test_songbook.py::test_writers_keep_comments_and_layout`,
  `test_songbook_render.py::test_a_broken_songbooks_file_is_an_error_that_stops_nothing_else`).
- **The library is synced**: Syncthing and every device can write to it. Read a file there
  with `library.read_regular` (or `open_regular`: no symbolic link followed, regular files
  only; `dir_fd=` for a name in a folder opened without following a link, as inbox.py reads
  `_inbox/`; `read_json` for its JSON, where whatever a device wrote is a ValueError at worst,
  never the RecursionError that would stop a pass over every song, as it is an `OverridesError`
  or a `SongbookFileError` in overrides.toml or songbooks.toml), and write one with
  `library.write_atomic`: a random temporary name opened
  exclusively, then a rename. Never `mkstemp`, whose mode 0600 hides files from Syncthing.
  Nothing private or bulky goes there: the database, the Spotify token, the lock, the HTTP
  cache and the audio taken from YouTube (`cache_dir/youtube/`, youtube_fetch.py) stay in
  `state_dir` and `cache_dir`, and chordpro works on a copy in a 0700 folder under the cache
  (render.py). tests/test_library_safety.py. A removal deletes only what caracole
  wrote in the song's folder (`removal._caracoles`: kept files, the outputs of a kept sheet or
  of a render record, LRCLIB's lyrics, info.json), by name, through descriptors opened with
  `O_NOFOLLOW` from the library down, and names everything it leaves; it never touches Music/,
  and deletes the song's audio taken from YouTube from the cache (tests/test_removal.py).
- **One caracole at a time**: `_common.exclusive` holds an flock on `state_dir/caracole.lock`,
  re-entrant within a process, and the clients of `make_client` and the yt-dlp runner of
  `make_youtube` hold it until closed. Every command that asks UG, LRCLIB, LaCuerda,
  gtptabs.com, MuseScore or YouTube for pages or writes the library takes it;
  `search`, `match --dry-run`, `index stats`, `remove --list`, `songbook list` and
  `songbook show` only read and never wait.
  `review` and `remove` take it only after their questions (commands/library.py,
  commands/remove.py), so the nightly run never waits for an answer
  (`test_commands_lock.py::test_review_never_holds_the_lock_while_it_waits_for_you`,
  `::test_remove_never_holds_the_lock_while_it_asks`).
  A lookup never waits behind a whole nightly run, and still never writes beside it:
  `exclusive(..., interactive=True)` announces it in `state_dir/caracole.lock.waiting/` (a
  file per waiting process, touched every `TICKET_BEAT` s while it tries for the lock, and
  dropped once it holds it; one its process left, or untouched for `TICKET_STALE` s, a
  lookup killed while it waited, no longer counts). Bulk work hands the lock over
  (`_common.hand_over`, never inside a transaction): it lets go of the flock, takes it back
  once the lookup is done, and goes on. It does so in two places. Its clients, and the
  yt-dlp runner of `make_youtube` between two runs, spend each pause looking for a waiting
  lookup (every `HANDOFF_SLICE` s), then pause a whole `delay` again
  (`test_commands_common.py::test_the_youtube_steps_pauses_hand_the_lock_to_a_waiting_lookup_too`).
  Work that sends no request does it between two songs (a `between` callback):
  `autochords_pending` (commands/autochords.py) and `render_all` (pipeline.py's render step,
  commands/render.py). A bulk caller
  holding state across a handoff re-reads it after one: ug/fetch.py `fetch_songs` reads each
  song and overrides.toml again (`_Handoffs`; a song a lookup fetched mid-turn is fetched
  again next run), gtptabs_fetch.py checks a song still has no file before its turn, and
  `autochords_pending` and `render_all` read each song after and overrides.toml again
  (`test_commands_common.py::test_the_nightly_run_hands_the_lock_to_a_lookup_during_its_pause`,
  `test_autochords_run.py::test_a_lookup_waiting_for_the_lock_takes_it_between_two_songs`).
  `serve` never takes it: it reads like `search` and appends to wanted.txt like `add`, and
  runs every other change as a `caracole` command in a child process, one at a time
  (web/jobs.py), since the lock is re-entrant within a process and its threads would share it:
  a removal too, `caracole remove --yes`, once its page (`removal.plan_removal`, which only
  reads) has asked; its job's song key is `remove:<key>` (`jobs.REMOVING`), so it never joins
  the song's add or fetch.
- **Spotify is optional, and wanted.txt is always a source.** `sources.sync_sources` syncs
  wanted.txt first, then Spotify, importing spotipy, only when `cfg.spotify.enabled` (a
  `client_id` is set); any Spotify failure becomes a state on its report, never an error.
