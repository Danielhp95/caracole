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
an earlier one failed. Each module's docstring says what it does and why, and each package's
`__init__.py` how the package is laid out (commands/, web/, viewer/, library_assets/,
autochords/): the details live there, beside the code they describe, and change with it. This
section says where things are, and the rules a change there keeps.

| Step | Modules |
|---|---|
| sync | sources.py, wanted.py, spotify.py, songs.py |
| icons | icons.py (each source's mark) |
| index | ug/sitemap.py, ug/index.py |
| match | match.py, ug/lookup.py |
| lyrics | lyrics.py |
| fetch | ug/fetch.py, ug/page.py (tab pages), ug/artist.py (artist pages), ug/artist_tabs.py (the tabs of every artist page read, kept for searches: `ug_artist_tabs`, schema 7), rank.py, coverage.py, versions.py |
| lacuerda | lacuerda.py (URLs, parsing), lacuerda_fetch.py (the sheets), lacuerda_index.py (its listings of every artist, for searches) |
| scan | music.py (Music/), inbox.py (`_inbox/`), musicxml.py |
| gtptabs | gtptabs.py (URLs, parsing), gtptabs_fetch.py (the step) |
| musescore | musescore.py (URLs, parsing), musescore_fetch.py (the step) |
| youtube | youtube.py (running yt-dlp), youtube_urls.py (a video's address), youtube_fetch.py (the step) |
| render | chordpro.py (UG markup to ChordPro), render.py (PDFs; `render_version`, an export: the PDF in a viewer's version of the sheet `export_viewer` names, the human one else the auto one, listed under Versions in its line's ⋯ on index.html; `own_version`, the song's own, overrides.toml's `[version]`), pdf_text.py (each PDF's own text), viewer/ (sheet.html, songbook.html; version.py, a viewer's version applied to a sheet in Python), songbook.py (songbooks.toml) |
| todo | todo.py (`_todo.md`), library_page.py (`index.html`), library_assets/, songbook_section.py |

Each step returns a `report.StepResult` (what it did, counted; the songs a provider's error
left, with the error; what needs the user), which report.py turns into the run's summary on
stdout and ntfy: a new step plugs in by returning one. The log goes to stderr, set up once
by the root callback (logs.py: `-v`, `-vv`, `-q`, journal priorities, redacted secrets).

Shared by the steps and the commands:

| Module | What for |
|---|---|
| config.py | caracole.toml, directories, secrets |
| db.py | the schema, migrations, `kv`, `savepoint` (atomic writes on the autocommit connection) |
| http.py | `PoliteClient`, robots rules, cached answers (`stale`, `read_once_more`; `cached` and `CachedAnswers` read the cache alone, sending nothing) |
| health.py | cooldowns, `events` |
| normalize.py | keys, pinyin, `name_forms`; `name_words`, `holds_run` and `PINYIN_PARTIAL_SCALE`, Chinese in pinyin only as whole words, for search.py and lacuerda_index.py |
| inline.py | what a page holds inline: a script or a style by its hash, a JSON data block; the standard library alone |
| overrides.py | overrides.toml |
| library.py | song folders, safe file access in the synced library |
| notify.py | ntfy |
| site_index.py | a site's sitemaps into a table, resumed across runs |
| keys.py | a song's musical key and where it came from |
| removal.py | `caracole remove` and the web page's Remove; the tombstones it leaves are songs.py's |
| progress.py | a command's output: a live line on a terminal, plain lines elsewhere |

Rules a change there keeps (the Invariants below are the others):

- **The pages caracole writes and serves** (index.html, sheet.html, songbook.html, caracole
  serve's own) load nothing from the network: a Content-Security-Policy allows each inline
  script and stylesheet by the hash of the very text inlined (inline.py `sha256_source`), and a
  page's data is a JSON block with each `<` escaped (`inline.json_block`). Their scripts build
  every element with `createElement` and `textContent`, never `innerHTML`, and connect to
  nothing but caracole serve. A page caracole writes into the library is served only through
  `app.written_pages` (a new kind goes there, with its record and its policy), and only while it
  holds the bytes caracole recorded (`files.read_written_page`). Enter in a search box never
  spends a request on a guess: on the lookup page it acts only on `/api/search`'s `best` (or
  opens the leading artist's songs), and on the library page, whose served bar searches
  `/api/search` as you type (which asks no site), it only moves the focus to the first result.
  There, library.js's `mergeSites` puts your songs and every index's rows under one header an
  artist and one line a song, by the two parts of the identity key (the rows' `artist_key` and
  `title_key`, an artist's `group_key`, a song's `identity` in the page's data), each line
  rows.js's `indexLine`; a removed song's line asks for it again as the request form does.
- index.html's stylesheets, scripts and markup are the .css, .js and .html files of
  library_assets/, inlined byte for byte in the order of `library_page.STYLESHEETS`, `SCRIPTS`
  and `TEMPLATES`, where a new file is listed (test_library_assets.py).
- viewer/: what a page is made from is `page.BUILD_FILES`, hashed into `page.build_version`: a
  module the viewer comes to import goes there (test_viewer_book.py checks). theory.py and
  `voicings.voicing_keys` keep their answers, so `Chord` and `Key` stay frozen with every field
  compared, and a list handed out is a copy (test_viewer_theory.py). version.py names and shapes
  every chord as viewer.js does, so a PDF made in a version is what the viewer shows
  (test_viewer_version.py compares the two in Chromium).
- `commands/`: one module per area, each with `register(app)`, which `cli.build_app` finds
  by itself (A4: add a module, never edit cli.py). `_common.py` holds what they share (config,
  the database, the lock, clients at either pace, pages, `fail`, `warn`, `song_named`): use it
  rather than another copy. A command's logic lives in a module outside commands/, imported
  inside the command's function (Heavy imports, below): get.py is `caracole get`, one song looked
  up now (the run's steps for that song alone, sheet first, at the lookup pace; `--progress`, a
  JSON line per event, for caracole serve), and review.py, search.py, removal.py and songbook.py
  are `caracole review`, `search`, `remove` and `songbook`. search.py reads the local indexes
  alone, never a site: UG's sitemap index and the artist pages caracole read (ug/artist_tabs.py),
  gtptabs.com's, MuseScore's and LaCuerda's tables, and the tombstones of removed songs
  (`search_removed`: never `lead` or `best`, shown with the `caracole add` line that brings one back,
  and in `/api/search`'s `removed`, which the library page shows with Add again). Its prefilter reads ug/key_search.py (`rows_like`: the keys' trigram
  index), which must find exactly what a `LIKE` scan of `ug_index` finds
  (`test_search.py::test_the_prefilter_finds_through_the_key_index_what_a_scan_of_every_row_finds`),
  except that a pattern in more than `KEYS_PER_PATTERN` keys (a common word) brings in its
  shortest keys and those every pattern is in
  (`::test_a_common_word_brings_in_its_shortest_keys_and_those_every_word_is_in`).
- `web/`: `caracole serve` (commands/serve.py). web/__init__.py names its parts, and web/app.py's
  docstring the modules of routes and the checks every request passes. app.py is the router and
  what every route shares (`Request`, `Response`, the answers' shapes, `WebApp.db()`,
  `.overrides()`, `.submit()`, `.queued()`); a route lives in its area's `*_routes.py`, as a
  `Route` in its `ROUTES`, which the router gathers from every such module, and a line of its
  docstring (test_web_app.py checks both): neither a new route nor a new module of them changes
  app.py. A route refuses with `pages.Refused`, which `WebApp.handle` answers as the message
  page, or to the page's script as JSON: every refusal as data. Every `/api/` read is refused to
  another site's fetch (`security.own_page_read`), and every write passes security.py's
  cross-origin check and carries the form token. Beyond a wanted.txt line, every change runs as a
  `caracole` command queued in jobs.py (One caracole at a time, below). The one line a request
  shows is status.py's, read from the job's steps and the song's state, never from which commands
  ran: a step's label is that line while it runs ("Adding to the library…").
- `autochords/`: merge.py is pure Python and the only module `__init__.py` imports; btc.py
  (with the vendored btc_model.py and LICENSE-BTC) and beats.py need torch, librosa and
  beat_this; run.py runs them over the library.
- `tests/`: named after what they cover (test_fetch.py is ug/fetch.py's), and
  `test_commands_*.py` for the CLI. conftest.py has the `conn` and `cfg` fixtures (every
  directory under `tmp_path`, in /dev/shm if it will do; `conn` copies a database migrated once
  per process), `add_song` and `subprocess_pythonpath`. tests/helpers/ holds what the tests
  share, a module each, whose docstring says what it gives and how (`from helpers.<module>
  import ...`): fake sites behind a real `PoliteClient`, a fake yt-dlp, synthetic files, a song
  rendered, a wait for caracole's lock seen, Chromium (Browser tests, below); look there before
  writing another. test_harness.py tests what makes the suite fast. fixtures/ holds samples of
  what each site answers (real response shapes, trimmed) and synthetic lyrics, sheets and files.
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

**Fast loop**: `nix develop -c pytest -q -m "not slow"` (about 6 s) while you work, and the
whole suite, `nix develop -c pytest -q` (about 35 s), before a commit. Always through `nix
develop`: its pytest has pytest-xdist, which spreads the suite over the cores; a pytest
without it runs the whole suite in one process, for minutes.

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

**Browser tests.** A test that opens a page in Chromium is marked `@in_chromium` (or has it as
its module's `pytestmark`, `helpers.browser.CHROMIUM_MARKS`): slow, and skipped without
Chromium; one that opens a page unmarked fails (`helpers.browser.require_in_chromium`). It opens
pages through helpers/browser.py, `dump_dom` (the DOM once the page's script ran, its timers on
virtual time, in one Chromium per process and a fresh context per page) or `Browser` (a Chromium
of its own, on real time, to type, press keys, click and touch), or through helpers/chromium.py,
for a page whose policy refuses a test's script. None of them resolves a host name
(`helpers.browser.NO_LOOKUPS`), and the other browser helpers in tests/helpers/ build on them.

A test that drives a page on real time (`Browser`) waits for the state it needs
(`Browser.wait`: an expression that throws while the page still loads is not true yet; once the
page has loaded, it raises at once), never a fixed time: its workers share the machine with eleven
others. After a step that loads the page again (a reload, a songbook's next song), it waits for the
new document, not the one before it (`window.before`, as `Browser.open` does for an address). The
library page caracole serve serves asks /jobs.json every 1.5 s and counts Remove's five
seconds; `WebApp(timers=...)` shortens both for such a test (test_web_page.py's `QUICK`), and
caracole serve never sets it, so the page users get carries no timers (`WebControls.timers`).

Both shells set `CARACOLE_CJK_FONT` to the packages' font. `.#autochords` adds torch,
beat-this and librosa, and sets `CARACOLE_BTC_WEIGHTS` and `CARACOLE_BEAT_CHECKPOINT` to the
files nix/autochords.nix fetches. Tests that need a real program or model skip without it:

| Needs | Tests | Set by |
|---|---|---|
| `chordpro` on PATH, or `CARACOLE_CHORDPRO_BIN` | the tests marked `chordpro`: real PDFs | both shells |
| `CARACOLE_CJK_FONT`: one `.ttf` or `.otf` with CJK glyphs | Chinese PDFs | both shells |
| `pdftotext` on PATH, or `CARACOLE_PDFTOTEXT` | the PDFs' text in test_render_all.py (fewer checks without it, no skip) | neither: `nix shell --inputs-from . nixpkgs#poppler-utils` |
| torch, librosa, beat_this, and `CARACOLE_BTC_WEIGHTS` with `CARACOLE_BEAT_CHECKPOINT`, or `CARACOLE_MODELS_DIR` (searched for `btc_model_large_voca.pt` and `final0.ckpt`) | the tests marked `autochords` | `.#autochords` |
| `CARACOLE_BTC_MAJMIN_WEIGHTS`, or `btc_model.pt` under `CARACOLE_MODELS_DIR` | `test_the_major_minor_model_loads_too` | neither |
| `ffmpeg` on PATH | `test_btc_reads_aac_from_the_itunes_store` | neither |
| `chromium` on PATH | the tests marked `@in_chromium` (Browser tests, above): the pages caracole writes and serves, in a real browser | neither |

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
  music.py imports mutagen in `read_audio` alone, and lyrics.py in `_expected_seconds`:
  inbox.py, which the pages import, scores names with its `Names`
  (`test_music.py::test_the_pages_load_no_tag_reader`, `::test_the_inbox_loads_no_http_client`).
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
    and every command but `caracole get` and `caracole lacuerda --artist`. Budgets per run:
    `ug` 60, `lrclib` 200, `lacuerda` 30 (its sheets first, then its listings of every
    artist), `gtptabs` 20, `musescore` 10 requests, `youtube` 6 yt-dlp runs
    (`config.DEFAULT_PROVIDERS`); `caracole index build` at least 100 (`BUILD_BUDGET`,
    commands/index.py). Then `BudgetExhausted`. Between any two requests to a provider, a
    random pause from its `delay` (10–20 s for UG, LaCuerda, gtptabs.com and MuseScore,
    1–2 s for LRCLIB).
  - **An interactive lookup**: `caracole get`, one song asked for just now (caracole serve's
    lookups run it), and `caracole lacuerda --artist`, one artist's page (an artist's Songs).
    Its clients are `make_client(..., interactive=True)`: a random gap from
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
    robots.txt (tests/fixtures/gtptabs/ and tests/fixtures/musescore/robots.txt). LaCuerda's
    robots.txt is empty, and it has no search caracole uses: a search reads `lacuerda_index`
    alone, and an artist's songs come from their page, read at most once in 30 days
    (`test_web_app.py::test_a_search_asks_no_site_and_takes_no_lock`).
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
  lacuerda_fetch.py, gtptabs_fetch.py;
  `test_pipeline.py::test_ug_block_cools_down_and_never_marks_not_found`,
  `test_fetch.py::test_parse_error_is_not_a_miss`,
  `test_gtptabs_fetch.py::test_a_spent_budget_is_no_miss`). A cached answer that won't
  parse is asked for once more, past the cache, before it is an error, so a bad night
  isn't replayed every night after: `http.read_once_more` for LRCLIB, LaCuerda and
  gtptabs.com, ug/fetch.py's `_get_page` for UG
  (`test_lyrics_pending.py::test_a_cached_answer_that_isnt_json_is_asked_for_once_more`).
  On gtptabs.com only an artist page that answered without a candidate is a miss, asked
  about again after 30 days; on YouTube only a search that answered without a video that
  fits (youtube_fetch.py,
  `test_youtube_fetch.py::test_an_error_is_no_miss_and_the_song_waits_for_the_next_run`); of
  LaCuerda's listings only a page that answers 404 loses its artists, never one that errs
  or won't parse
  (`test_lacuerda_index.py::test_a_page_that_wont_parse_is_an_error_and_its_artists_stay`).
  A block or a spent budget exits 0; a bug exits 1, which fires the unit's ntfy alert.
- **Slugged tabs only at their slugged URL**, as UG answers 404 for them at `/tab/{id}`:
  the index keeps each tab's sitemap path (`ug_index.path`), from which ug/page.py
  `page_url` and ug/lookup.py `IndexTab.url` and `tab_url_for` build it. **Bare-id tabs**
  (a tenth of UG's, and every tab of an artist with an accented or non-Latin name) are
  found on the artist's UG page (ug/artist.py, the `artist_page` route in ug/fetch.py; every
  list read kept for searches, ug/artist_tabs.py),
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
  coverage.py, music.py, search.py, library_page.py, ug/fetch.py, ug/artist_tabs.py (its
  forms) and lacuerda_index.py (whose keys are pinyin); identity keys also fold
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
  (`lacuerda_index.ensure_current_keys`, at its next refresh or store), and so are
  `ug_artist_tabs`' keys and forms (`artist_tabs.ensure_current_keys`, at its next store or
  backfill, which the match step and every lookup call).
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
  `_inbox/`; `read_text` for its text, any failure the caller's error naming the file, as
  overrides.py and songbook.py read theirs; `read_json` for its JSON, where whatever a device
  wrote is a ValueError at worst, never the RecursionError that would stop a pass over every
  song, as it is an `OverridesError` or a `SongbookFileError` in overrides.toml or
  songbooks.toml), and write one with `library.write_atomic`: a random temporary name opened
  exclusively, then a rename. Never `mkstemp`, whose mode 0600 hides files from Syncthing.
  Nothing private or bulky goes there: the database, the Spotify token, the lock, the HTTP
  cache and the audio taken from YouTube (`cache_dir/youtube/`, youtube_fetch.py) stay in
  `state_dir` and `cache_dir`, and chordpro works on a copy in a 0700 folder under the cache
  (render.py). tests/test_library_safety.py. A removal deletes only what caracole
  wrote in the song's folder (`removal._caracoles`: kept files, the outputs of a kept sheet or
  of a render record, its exports, LRCLIB's lyrics, info.json), by name, through descriptors opened with
  `O_NOFOLLOW` from the library down, and names everything it leaves; it never touches Music/,
  and deletes the song's audio taken from YouTube from the cache (tests/test_removal.py).
- **One caracole at a time**: `_common.exclusive` holds an flock on `state_dir/caracole.lock`,
  re-entrant within a process, and the clients of `make_client` and the yt-dlp runner of
  `make_youtube` hold it until closed. Every command that asks UG, LRCLIB, LaCuerda,
  gtptabs.com, MuseScore or YouTube for pages or writes the library takes it;
  `search`, `match --dry-run`, `index stats`, `remove --list`, `songbook list` and
  `songbook show` only read and never wait.
  `add` writes its wanted.txt line first, and a `--lacuerda` pick (overrides.toml is in the
  library) only once it holds the lock, failing when the lock file can't be opened
  (`test_commands_sources.py::test_add_with_lacuerda_writes_no_pick_without_caracoles_lock`).
  `review` and `remove` take it only after their questions (commands/library.py,
  commands/remove.py), so the nightly run never waits for an answer
  (`test_commands_lock.py::test_review_never_holds_the_lock_while_it_waits_for_you`,
  `::test_remove_never_holds_the_lock_while_it_asks`).
  A lookup never waits behind a whole nightly run, and still never writes beside it:
  `exclusive(..., interactive=True)` announces it in `state_dir/caracole.lock.waiting/` (a
  file per waiting process, touched every `TICKET_BEAT` s while it tries for the lock, and
  dropped once it holds it; one its process left, or untouched for `TICKET_STALE` s, a
  lookup killed while it waited, no longer counts). Every changing `caracole songbook`
  command (make, add, remove, move, rename, delete, render: commands/songbook.py) waits the
  same way, as a songbook is asked for now
  (`test_commands_songbook.py::test_a_change_waits_for_the_nightly_run_as_a_lookup_does_never_for_its_whole_run`).
  Bulk work hands the lock over
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
  a removal too, `caracole remove --yes`, once the line's five seconds with Undo are over
  (the library page's script; without it, a page of its own), having asked what goes
  (`removal.plan_removal`, which only reads, and `removal.brief`); its job's song key is
  `remove:<key>` (`jobs.REMOVING`), so it never joins the song's add or fetch.
- **Spotify is optional, and wanted.txt is always a source.** `sources.sync_sources` syncs
  wanted.txt first, then Spotify, importing spotipy, only when `cfg.spotify.enabled` (a
  `client_id` is set); any Spotify failure becomes a state on its report, never an error.
