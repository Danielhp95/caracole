# AGENTS.md

What a coding agent needs before changing caracole. User documentation: README.md, docs/.

## What caracole is

caracole is a Python CLI, run every night by a NixOS service, that builds a private library
of sing-along chord sheets (Ultimate Guitar, LaCuerda), lyrics (LRCLIB), PDFs (ChordPro)
and Guitar Pro files (downloaded from gtptabs.com, or filed from what the user drops
into `_inbox/`) for the songs in `wanted.txt`. For a song
nobody has charted, `caracole autochords` writes a sheet from audio with local models
(torch, optional): a purchase, or audio the nightly run takes from YouTube with yt-dlp
(youtube.py, youtube_fetch.py), a few songs a night, only where auto-chords is. The
design lives in three files:

- `plan.md`: design v2.1, and why. Its code sketches are older than the code: its module
  runs `caracole run --config …`, which the CLI rejects (`--config` is a root option:
  `caracole --config FILE run`).
- `docs/superpowers/plans/2026-10-18-caracole.md`: the task plan, with amendments A1–A7 made
  during the build: A2 `wanted.txt`, A3 Chinese titles, A4 command
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
| sync | sources.py, wanted.py (the one source of songs), songs.py |
| icons | icons.py (each source's mark) |
| index | ug/sitemap.py, ug/index.py |
| match | match.py, ug/lookup.py |
| lyrics | lyrics.py |
| fetch | ug/fetch.py (UG's chords and text tabs alone), ug/page.py (tab pages; `KINDS`, the types caracole uses: chords, tabs), ug/artist.py (artist pages), ug/artist_tabs.py (the tabs of every artist page read, kept for searches: `ug_artist_tabs`, schema 7), rank.py, coverage.py, versions.py, sheet_versions.py (a song's UG chords versions in rank order, the one and those kept beside it as `version-<tab>.txt`, `.json`, `.html`: the versions the fetch scores, written by ug/fetch.py's `_keep_beside` with no request more, a pinned sheet's from the cache alone; `in_library`, the list as the library holds it; `as_data`, the pages' JSON) |
| lacuerda | lacuerda.py (URLs, parsing, its search's pages), lacuerda_fetch.py (the sheets; `may_ask`, the songs LaCuerda may have, for the step and the to-do page; `popular_pages`, the most popular artists' pages once the listings are read whole), lacuerda_index.py (its listings of every artist, for searches; `backfill_cached`, the artist pages the HTTP cache holds; `store_search`, what its search answered), lacuerda_search.py (its own search, one query at the lookup pace, `caracole lacuerda --search`; `gate`, whether the pages may send it) |
| scan | music.py (Music/), inbox.py (`_inbox/`), musicxml.py |
| gtptabs | gtptabs.py (URLs, parsing), gtptabs_fetch.py (the step) |
| musescore | musescore.py (URLs, parsing), musescore_fetch.py (the step) |
| youtube | youtube.py (running yt-dlp), youtube_urls.py (a video's address), youtube_fetch.py (the step; `song_states`, where each song stands for the pages: `todo.write_pages` asks once and hands it to both, a one-song card asks of its song alone) |
| render | chordpro.py (UG markup to ChordPro), render.py (PDFs; a viewer page alone for each version kept beside the sheet, `version-<tab>.html` from its `.json`, with no Export PDF (an export is the one's), recorded in `render:files:` and dropped once the version leaves; every viewer of the song carries `versions`, `sheet_versions.as_data` with `sheet`, the one's provider, `pinned`, whether a `[pin]` chooses it (`sheet_versions.sheet_pins`, what `caracole versions --clear` takes out), and `this` on each entry, true on the page's own, and `guitar`, the song's kept Guitar Pro files caracole serve shows in the browser (`inbox.guitar_files`), linked in served settings as Guitar Pro tab; `render_version`, an export: the PDF in a viewer's version of the sheet `export_viewer` names, the human one else the auto one, listed under PDF exports in its line's ⋯ on index.html, where Sheet versions lists the UG versions kept beside the sheet (`sheet_versions.in_library`, library_page.py `_versions_data`); `own_version`, the song's own on one of its sheets, overrides.toml's `[version]`: kept by the key it plays in, as Make this my version writes it (`ExportSheet.entry`, `key=Gm&mode=dorian&capo=0`: the key of the shapes in the mode the sheet's chords are read in, a mode only where one was chosen, shapes by their frets), which each sheet takes by a songbook setting's rule, its chords read in the notes of its own key, so a replaced sheet plays in that key, and one that reads the same chords in the relative key, or names the parallel one for them (`version._fitting`), plays them; or, written before, a `t=` move from the sheet, which the export page offers to keep by its key; the chordpro plumbing songbook.py shares: `run_chordpro`, a run's errors as `RenderError`s, `private_dir`, the 0700 folder chordpro works in, `pdf_font`, the font a text needs, and `written_entry`, the one reading of a file written's record), pdf_text.py (each PDF's own text; `names`, the theory edition's chord names: each chord and its numeral, or the numerals alone in a chart with no diagrams, with a legend from `harmony.glossary`; its two columns end level, at a section, by `line_heights` and `column_height`: chordpro's layout in caracole's style, chordpro-style.json's sizes and the PDF fonts' widths (pdf_fonts.py), which test_render.py pins to the real chordpro's pages in the built-in fonts and in Adwaita's), viewer/ (sheet.html, songbook.html; version.py, a viewer's version applied to a sheet in Python, and where a key plays a sheet: `Setting`, key, mode, capo, and `in_setting`, the setting's key as the key of the shapes played, its mode and capo; `KeyVersion`, a `[version]` kept by its key, its swaps and shapes by their chords' names: `key_version` reads one, `version_entry` writes one, `in_key` plays it on any sheet; harmony.py, what each chord does in its key on top of theory.py: Roman numerals, relations, families, glossary lines, chord tones, solo scales, progressions named from its `CATALOGUE` (each row with its source; a row of `_LOOPS` from any of its chords, the others from their first; a cycle a section plays whole, or `contains`, the ones played within a longer section, within each pass of one played round) and their endings, a section's repeats folded round a pass that varies them (`_fold`), `progression_key` for searching, `name_of` and `read_typed` for numerals typed; harmony_tables.py, its answers as the tables a viewer's data carries, per mode, each text naming notes written for every transposition, for viewer.js to look up; strum.js, a chord's shape strummed in Web Audio, `window.caracoleSound`; instruments.py, the instruments the viewer draws chords for, `INSTRUMENTS` (guitar, ukulele high and low G, baritone, piano: tuning, capo or none, where its shapes are, easy keys), the ukuleles' shapes from chords-db (voicings-ukulele.json, filed by the guitar's keys, the baritone's a fourth lower), the piano's computed (`piano_positions`: root position and two inversions, a left-hand bass), `chord_shapes`, what the viewer shows a chord on one, and version.py's `for_instrument`, the capo folded in on one that takes none; instruments.js, their box and keyboard and `window.caracoleInstruments`, where another instrument's script registers its drawing, a header line and a settings row), songbook.py (songbooks.toml: a song is a string, or a table with its own `Setting`; `SongbookSong`, `Songbook.songs`, `.texts`; `set_song_setting`, and `with_capo`, the capo a key or a mode `caracole songbook set` gives plays at now, so a replaced sheet keeps the key it sounds in; its files play each song through `apply_version`, never chordpro's `{transpose}`, where `in_setting` puts it, the rest the song's `own_version`; `plays_in`, that in words, "key unknown, as written" for a sheet with no key that a setting or the song's own key can't take) |
| todo | todo.py (`_todo.md`), library_page.py (`index.html`), library_assets/, songbook_section.py (its Songbooks tab's data) |

Each step returns a `report.StepResult` (what it did, counted; the songs a provider's error
left, with the error; what needs the user), which report.py turns into the run's summary on
stdout and ntfy: a new step plugs in by returning one. The log goes to stderr, set up once
by the root callback (logs.py: `-v`, `-vv`, `-q`, journal priorities).

Shared by the steps and the commands:

| Module | What for |
|---|---|
| config.py | caracole.toml and directories, and no secret (ntfy is a topic's URL alone) |
| db.py | the schema, migrations, `kv`, `savepoint` (atomic writes on the autocommit connection) |
| http.py | `PoliteClient`, robots rules, cached answers (`stale`, `read_once_more`; `cached` and `CachedAnswers` read the cache alone, sending nothing) |
| health.py | cooldowns, `events` |
| normalize.py | keys, pinyin, `name_forms`; `name_words`, `holds_run` and `PINYIN_PARTIAL_SCALE`, Chinese in pinyin only as whole words, for search.py and lacuerda_index.py |
| inline.py | what a page holds inline: a script or a style by its hash, a JSON data block; the standard library alone |
| pdf_fonts.py | the fonts every PDF is set in (`pdf_fonts`, `CARACOLE_PDF_FONTS`): a folder of `regular`, `bold`, `italic` and `mono` (`in_folder`), and what `metrics` reads of each, the characters it has and their widths as ChordPro's PDF library counts them, which render.py's `pdf_font` (a letter the regular font lacks brings in the CJK font, for the words alone: `fonts_options`, `PDF_FONT_ELEMENTS`) and pdf_text.py's layout read; without the folder, ChordPro's built-in fonts, as before; the standard library alone |
| page_icon.py | the mark in every page's tab, "¿" drawn in SVG (`LINK`, a `data:` URI for a page's head; `SVG`, caracole serve's `/favicon.ico`); the standard library alone |
| overrides.py | overrides.toml |
| library.py | song folders, safe file access in the synced library |
| download_names.py | the name a kept file downloads under ("Eagles - Hotel California (2).gp5"): web/app.py's `Content-Disposition`, the `download` of index.html's and the viewer's links; the standard library alone (the viewer imports it) |
| notify.py | ntfy |
| site_index.py | a site's sitemaps into a table, resumed across runs |
| stamps.py | how caracole stores a time (ISO 8601 UTC to the second, a naive time is UTC) and shows one (`shown`, in UTC; `local=True`, the requests page's, in the server's zone, named); a stored time missing or unreadable is older than any (`before`); the standard library alone |
| provider_pass.py | one song at a time through a provider (`each_song`, `PassStats`): the lyrics, LaCuerda, gtptabs.com and YouTube passes share its ladder of errors that are never misses, and name the songs an error left (`failures`) |
| keys.py | a song's musical key and where it came from |
| removal.py | `caracole remove` and the web page's Remove; the tombstones it leaves are songs.py's |
| progress.py | a command's output: a live line on a terminal, plain lines elsewhere |
| progressions.py | each song's progressions, read by render.py as it renders the song's sheet (its human one, else its auto one: `test_progressions.py::test_a_song_that_keeps_both_sheets_is_found_by_its_human_sheet_never_the_auto_one`) into kv `render:progressions:<song id>` (`record`; harmony.py's `progressions` and `progression_key`), so that index.html's data (each song's `progressions`, the page's `catalogue`), `#prog=` (any rotation of it, made the key by library.js's `progKeyOf` as `progression_key` makes one), `/api/search`'s `progression` and `caracole search --progression` read one row a song, never a sheet; `read_progression`, numerals or a catalogue name typed; a named progression stands for every reading of its name (the pop progression in a major key and in its relative minor) and finds a section that plays it within it (a record's `contains`) |

Rules a change there keeps (the Invariants below are the others):

- **The pages caracole writes and serves** (index.html, sheet.html, songbook.html, caracole
  serve's own) load nothing from the network: a Content-Security-Policy allows each inline
  script and stylesheet by the hash of the very text inlined (inline.py `sha256_source`), and a
  page's data is a JSON block with each `<` escaped (`inline.json_block`). Each carries
  `page_icon.LINK` in its head, which its policy allows with `img-src data:` (test_page_icon.py). Their scripts build
  every element with `createElement` and `textContent`, never `innerHTML`, and connect to
  nothing but caracole serve. A page caracole writes into the library is served only through
  `app.written_pages` (a new kind goes there, with its record and its policy; a kept version's page,
  `version-<tab>.html`, is a sheet viewer by its name: `app.written_page`), and only while it
  holds the bytes caracole recorded (`files.read_written_page`). The one page that loads anything from caracole
  serve is the Guitar Pro page (`web/guitar_routes.py`, `guitar_page.py`: a song's kept `guitar-N.*` file drawn and
  played by alphaTab, made per request, nothing written into the library): served in a sandbox, it loads alphaTab's
  one bundle (`web/alphatab.py`: the library, its font and its SoundFont, from `CARACOLE_ALPHATAB_DIR`) by
  `<script src integrity crossorigin>`, which its policy allows by the bundle's SHA-256, as it does the
  `@font-face` stylesheet alphaTab adds (`alphatab.font_face`, pinned by test_web_guitar_browser.py); the bundle
  route answers any origin. Enter in a search box never
  spends a request on a guess: on the lookup page it acts only on `/api/search`'s `best` (or
  opens the leading artist's songs), and on the library page, whose served bar searches
  `/api/search` as you type (which asks no site), it only moves the focus to the first result;
  the one exception is LaCuerda's search, which Enter sends when its gate allows.
  LaCuerda's own search is the one request a search may bring: both pages send it by themselves
  (`POST /lacuerda/search`, a queued `caracole lacuerda --search --auto`) once the query has settled,
  the box unchanged for 1.5 s, when `/api/search`'s `lacuerda_search` says `auto`, and Enter sends it
  at once, by hand as the button does (no `--auto`), when it says `auto` or `button` (for the query's
  answer on the screen, else with the answer on its way, unless Escape leaves the results first; the
  settle's timer then sends nothing), never
  twice for a query in a page; `button` (the hour's share of such searches spent) and `failed` (it
  failed within the hour, or three did) offer it by hand, a line under the results (rows.js
  `lacuerdaSearcher`; its rows come with the search asked again once the job is over, the focus Enter
  moved to a result staying on it, an artist's songs Enter opened on the lookup page staying open, and
  a search refused or failed has the button its words name: test_web_page_lacuerda_search.py). A test that drives
  the pages for something else passes `WebApp(searches_lacuerda=False)`, which caracole serve never
  does.
  What a search says beside its results is rows.js's, shared by both pages: `didYouMean` (`/api/search`'s
  `suggest`), `nothingFound` (one card for a query that found nothing: the request by name first, Ask LaCuerda,
  the chips of `looked`, `unseen` folded) and `lookedLine` (the chips in one muted line under results).
  There, library.js's `mergeSites` puts your songs and every index's rows under one header an
  artist and one line a song, by the two parts of the identity key (the rows' `artist_key` and
  `title_key`, an artist's `group_key`, a song's `identity` in the page's data), each line
  rows.js's `indexLine`; a removed song's line asks for it again as the request form does, a "Did you
  mean" name (rows.js's `didYouMean`) opens that artist's group from `/api/artist`, as "+ N more" does, and a
  song of yours under its ⋯ (Fetch again; Use LaCuerda's sheet, `lacuerdaSheet` or the search's LaCuerda row of
  it) posts `/lookup` exactly as the lookup page's rows of it do (test_web_page_again.py). A hit's
  name there and on the lookup page presses its Get it (or Add again), disabled while that button is
  (rows.js `nameDoes`): never in place of a title that opens a sheet, and only a click or a key on it. Served, an
  artist's name (a header's, a line's, a lookup row's) searches for them as typing it would (library.js
  `searchFor`, a step of the browser's history; lookup_page.py `searchArtist`), which asks no site, and the funnel
  beside it (rows.js `artistOnly`) shows your songs of theirs alone; from a file the name is the funnel's
  (`artistFilter`). Your
  songs there keep to the Show buttons, the Key menu and the artist's chip (`kept`), as the list's
  do. select.js knows only the songs the page was loaded with, less those gone since: a line offers Add to a
  songbook… for those alone. songs.id has no AUTOINCREMENT, so the next song added may get a removed song's id;
  library.js knows a song gone by its removal done on the page, or by a view or a card of `/jobs.json` that names
  another song's identity under its id (the view's `identity`, `jobs_routes.view`): removed elsewhere, its line
  says Removed, the song that has the id now is new to the page, and select.js and songbooks.js let it go
  (`caracole:gone`; songbooks.js's set lists show a lookup on a line of the same identity alone). The page's Songbooks tab (`#tab=songbooks`) is songbooks.js's, drawn from the
  data's `songbooks` (songbook_section.py: each songbook's set list, where it plays each song as
  `songbook.plays_in` says it, each song's Guitar Pro mark, `guitar`: a file kept, else none,
  and the setting's menus' names, the theory's), which `/jobs.json`
  gives again once a job is over (`jobs_routes.views`: a songbook's change, a lookup, which makes the
  songbooks its song is in again, or a removal; a LaCuerda artist's read changes none). library.js lends it `window.caracoleLibrary`
  (`track`, `showLine`, `focusOn`, and `fold`, the search's normalize.fold, for Add a song) and tells it every job's view (`caracole:job`) and the songbooks
  (`caracole:songbooks`); it posts the Select bar's songbook too, and gives the bar its ticks back when
  that make fails (`caracole:unmade`; the songbook stays on the tab until it is made, under its name or with
  those ticks under another, or its Forget it is pressed: songbooks.js `letGo`). A song's chip sends the capo with
  the key and the mode (`/songbook/set`, as `caracole songbook set` keeps it), and Add a song looks
  a song the library hasn't got up first (`/songbook/add-song`: `search_routes.lookup_request`, then
  `caracole songbook add`, both or neither: `JobQueue.submit_all`). A change that ends seconds after its tap moves nothing on the screen:
  what it took away says so where it was until the next click or key (test_songbooks_tab.py).
- index.html's stylesheets, scripts and markup are the .css, .js and .html files of
  library_assets/, inlined byte for byte in the order of `library_page.STYLESHEETS`, `SCRIPTS`
  and `TEMPLATES`, where a new file is listed (test_library_assets.py).
- viewer/: what a page is made from is `page.BUILD_FILES`, hashed into `page.build_version`: a
  module the viewer comes to import goes there (test_viewer_book.py checks). theory.py, harmony.py
  and `voicings.voicing_keys` keep their answers, so `Chord` and `Key` stay frozen with every field
  compared, and a list handed out is a copy (test_viewer_theory.py, test_viewer_harmony.py).
  harmony.py's docstring holds the rules where music theory reads a chord two ways (B♭ in C is
  borrowed from C minor; D in C is V/V only going to G; C7 in C is V7/IV only going to an F that is
  no dominant seventh): change a rule there and in its test. version.py names and shapes
  every chord as viewer.js does, so a PDF made in a version is what the viewer shows
  (test_viewer_version.py compares the two in Chromium). viewer.js computes no music theory: a
  chord's numeral, its line, its notes, its solo scale and the key's scale are looked up in
  harmony_tables.py's tables, whose texts name notes as the page names them in the key shown
  (test_viewer_numerals.py checks them against harmony.py on every transposition). strum.js,
  inlined before viewer.js (and in a songbook), is the one place a page makes sound: a
  plucked-string synthesis into AudioBuffers, no sample, worklet or request; an AudioContext only on
  a tap (`navigator.userActivation`), suspended when the page is hidden or silent, resumed on the
  next tap. `caracoleSound.play` is what a part that plays chords in sequence calls (its header
  documents it; the Harmony panel's ▶ does), never another synthesis (test_viewer_sound.py,
  test_viewer_panels.py). It times a progression on the context's clock alone (a strum it comes to
  late moves the rest on, never two crammed together), and every stop (■, another ▶ or strum, the
  panel closed, the page hidden or left) leaves no note to begin and no timer of it, even when the notes
  cut tell they ended late; a sound asked while the context wakes plays only if nothing was asked after
  it, and a context woken for nothing sleeps again: test_viewer_sound.py's `SCHEDULE` records each note
  and timer the page makes, and plays a slow device on demand (a resume held, `ended` events late). A sheet viewer's data `versions` (sheet_versions.as_data, with each entry's `this` and the one's provider, `sheet`) draws its switcher
  under the key line and the list it opens, a rail like the settings and never beside them
  (test_viewer_versions.py); the songbook has none. The rail of necks (from 1200 px) is sized by
  viewer.css's `--nk` (1.15: the owner's 15 % over the first 300 px), its width, padding, text and
  targets alike; whether it shows (`state.necks`) is the one setting kept for every page at once
  (localStorage `caracole-viewer-necks`, and `necks=0` in the address, which book.js's `carryScreen`
  takes on to a songbook's next address, for its sandbox with no storage), with its Hide, the bar's
  button and the settings' row in step (test_viewer_necks.py). So is the settings' Pinyin (`state.py`,
  off at first: localStorage `caracole-viewer-pinyin`, `py=1` in the address, which `carryScreen` takes
  on too), each Chinese character's reading over it, between its chord and it: pinyin.py reads them at
  render time (pypinyin in context, a Traditional sheet in Simplified characters through normalize.py's
  table, its 著 as 着 but in a word Simplified writes with 著) into the data's `pinyin`, a reading per
  character of each `section.sec > p.l`, and viewer.js draws each as a `<ruby>`, its row of the line
  kept by every column, so a chord stays over its character's column, on or off, at 390 px too
  (test_viewer_pinyin.py). So is the Instrument (`state.inst`, the guitar at first: localStorage
  `caracole-viewer-instrument`, `inst=` in the address while it is another, which `carryScreen` takes on
  too; a songbook song's own version may name one, where it starts), which never moves the song: every
  instrument's shapes are instruments.py's, per root in the data's `voicings` (viewer.js looks them up),
  one with no capo (the piano) names the chords as they sound (viewer.js `capoNow`, version.py
  `for_instrument`), and the menu offers only what the page draws, an instrument of another kind once its
  script registers it (instruments.js documents that API): test_viewer_instruments.py,
  test_viewer_instruments_page.py, test_viewer_sound.py.
- `commands/`: one module per area, each with `register(app)`, which `cli.build_app` finds
  by itself (A4: add a module, never edit cli.py). `_common.py` holds what they share (config,
  the database, the lock, clients at either pace, pages, `fail`, `warn`, `song_named`): use it
  rather than another copy. A command's logic lives in a module outside commands/, imported
  inside the command's function (Heavy imports, below): get.py is `caracole get`, one song looked
  up now (the run's steps for that song alone, sheet first, at the lookup pace, then its `songbooks` stage: the songbooks of songbooks.toml that list the
  song, `songbook.songbooks_listing`, made again by `render_songbooks(only=…)`, then `write_pages` again once one was, as `caracole songbook render` writes the pages after; `--progress`, a
  JSON line per event, for caracole serve), versions_cmd.py is `caracole versions` (a song's UG
  chords versions listed from sheet_versions.py with no request; `--keep`, one tab page at the
  lookup pace, `ug.fetch.keep_version`, noted as yours in `sheet_versions.kept_by_you`; `--choose`,
  get's `--tab`; `--clear`, `overrides.remove_pin` then get), lacuerda_search.py is `caracole lacuerda
  --search` (LaCuerda's own search, one query, one request at the lookup pace), and review.py, search.py,
  removal.py and songbook.py are `caracole review`, `search`, `remove` and `songbook`. search.py reads the local
  indexes alone, never a site: UG's sitemap index and the artist pages caracole read (ug/artist_tabs.py),
  gtptabs.com's, MuseScore's and LaCuerda's tables, and the tombstones of removed songs
  (`search_removed`: never `lead` or `best`, shown with the `caracole add` line that brings one back,
  and in `/api/search`'s `removed`, which the library page shows with Add again), the words of the UG index's
  artists' names (`ug_artists_fts` and its vocabulary `ug_artist_words`, schema 8, kept by triggers on `ug_index`,
  a key going with its last row: an artist by a word of their name, `ArtistHit.part`, bounded by `WORD_LETTERS` and
  `WORD_ARTISTS` (LaCuerda's by `lacuerda_index.WORD_ARTISTS`), placed before a small namesake by `_with_parts`,
  leading by `_part_leads` and, against LaCuerda's, `lacuerda_leads`; and `suggest_artists`, the artists spelled
  close to a query nothing matches well, UG's and LaCuerda's ranked together, `/api/search`'s `suggest`, the pages'
  "Did you mean"), and
  `gtptabs_songs` counts an artist's songs on gtptabs.com (an artist row's `gtptabs` in `/api/search`, the
  "Guitar Pro 12" of their header); `--progression` reads progressions.py's records alone, your songs
  only (`songs_with`). Its prefilter reads ug/key_search.py (`rows_like`: the keys' trigram
  index), which must find exactly what a `LIKE` scan of `ug_index` finds
  (`test_search.py::test_the_prefilter_finds_through_the_key_index_what_a_scan_of_every_row_finds`),
  except that a pattern in more than `KEYS_PER_PATTERN` keys (a common word) brings in its
  shortest keys and those every pattern is in
  (`::test_a_common_word_brings_in_its_shortest_keys_and_those_every_word_is_in`).
- `web/`: `caracole serve` (commands/serve.py). guitar_routes.py is the Guitar Pro page and alphaTab's bundle
  (alphatab.py; the page guitar_page.py, guitar.js, guitar.css: the tracks laid out, each muted on its own with
  `changeTrackMute`; guitar.js `mend` patches alphaTab 1.8.4's canvas, which drew a part black when it began in the
  colour the last part ended in and cut the header's first line, so an alphaTab upgrade re-checks it:
  test_web_guitar_browser.py reads the header's pixels); a song's kept Guitar Pro files are
  `inbox.guitar_files`, which library_page.py (`guitarPage`), songbook_section.py (a set list's `guitar`) and render.py
  (the viewer's `guitar`) read too. web/__init__.py names its parts, and web/app.py's
  docstring the modules of routes and the checks every request passes. app.py is the router and
  what every route shares (`Request`, `Response`, the answers' shapes, `WebApp.db()`,
  `.overrides()`, `.submit()`, `.queued()`); a route lives in its area's `*_routes.py`, as a
  `Route` in its `ROUTES`, which the router gathers from every such module, and a line of its
  docstring (test_web_app.py checks both): neither a new route nor a new module of them changes
  app.py. A route refuses with `pages.Refused`, which `WebApp.handle` answers as the message
  page, or to the page's script as JSON: every refusal as data. Every `/api/` read is refused to
  another site's fetch (`security.own_page_read`), and every write passes security.py's
  cross-origin check and carries the form token. There is no sign-in, by the owner's choice: no access
  token, no cookie, no secret; whoever can reach the server may use it, so it is for a network they trust (a
  LAN, a tailnet). What keeps other sites' pages out is the host-name check (DNS rebinding), the
  cross-origin check, the form token and `own_page_read`, with Referrer-Policy `same-origin` (header and
  every page's meta tag), so that a form a phone posts over plain HTTP carries its Origin
  (`test_web_server.py::test_a_phone_on_the_lan_cancels_a_request`). Beyond a wanted.txt line, every change runs as a
  `caracole` command queued in jobs.py (One caracole at a time, below). The one line a request
  shows is status.py's, read from the job's steps and the song's state, never from which commands
  ran: a step's label is that line while it runs ("Adding to the library…"). The requests page
  (/jobs) says that line its own way (outcome.py), and the library page's lines never read it: the
  running request's steps, a finished one's outcome, a reason from its stages and its song's state
  (never made up: Not found says Ultimate Guitar has no chords only once the fetch asked it,
  `SongFacts.asked_ug`), and its next step; Cancel takes a request that hasn't started out of the
  queue (`JobQueue.cancel`, never one that runs, with the jobs `submit_all` queued `together` with
  it), keeping it in the history as over ("cancelled"), so a page that follows it hears it ended, and Try again queues a finished one's steps again (a removal's asks its question again). A sandboxed
  viewer reaches a form only through a GET page of the server's own, whose form posts with the token:
  `/export` (export_routes.py) and `/versions` (versions_routes.py: Make this the one, Keep it and back
  to caracole's pick, `caracole versions --choose`, `--keep` and `--clear`, with `--progress`: the job's
  stages, a lookup's for `--choose` and `--clear`, which run `caracole get`), each a job under the song's
  key, which jobs.py's `_pick` joins as a lookup's `--tab`. What a done job came to is read from the song's state and
  overrides.toml again (`caracole get` exits 0 on a block or a spent budget, the sheet unchanged).
- `autochords/`: merge.py is pure Python and the only module `__init__.py` imports; btc.py
  (with the vendored btc_model.py and LICENSE-BTC) and beats.py need torch, librosa and
  beat_this; run.py runs them over the library.
- `tests/`: named after what they cover (test_fetch.py is ug/fetch.py's), and
  `test_commands_*.py` for the CLI. conftest.py has the `conn` and `cfg` fixtures (every
  directory under `tmp_path`, in /dev/shm if it will do; `conn` copies a database migrated once
  per process), `add_song` and `subprocess_pythonpath`. tests/helpers/ holds what the tests
  share, a module each, whose docstring says what it gives and how (`from helpers.<module>
  import ...`): fake sites behind a real `PoliteClient`, a fake yt-dlp, synthetic files, a song
  rendered, a PDF's text where it is drawn (pdf_pages.py), a wait for caracole's lock seen, Chromium (Browser tests, below); look there before
  writing another. test_harness.py tests what makes the suite fast. fixtures/ holds samples of
  what each site answers (real response shapes, trimmed) and synthetic lyrics, sheets and files.
- `nix/`: package.nix (`buildPythonApplication`; the wrapper puts `chordpro` on PATH and
  defaults `CARACOLE_CJK_FONT`, `CARACOLE_PDF_FONTS` and `CARACOLE_ALPHATAB_DIR`; pdf-fonts.nix: nixpkgs'
  adwaita-fonts as four files, static Regular, Bold and Italic instances of Adwaita Sans made by pdf-fonts.py
  with fontTools, each glyph record padded to an even length, Adwaita Mono, and the OFL; alphatab.nix:
  alphaTab's npm package, fixed-output, three files and their licences; `withAutochords` adds the extra, the model files and
  `yt-dlp` on PATH), autochords.nix (the model files, fixed-output), module.nix
  (`services.caracole`: units, timer, `caracole-admin`; no `credentials` option, as caracole reads no
  secret, so no unit and not `caracole-admin` loads one; with auto-chords on, the nightly
  unit runs the auto-chords package, for its youtube step, and caracole-web and
  `caracole-admin` run it too, so their pages agree), module-check.nix
  (`checks.module`).
- `docs/`: usage.md (configuration, commands, the to-do page, overrides.toml, the library
  folder), deploy.md (a server: the NixOS module, or Ubuntu 24.04 without Nix, whose units
  and caracole-admin do what nix/module.nix's do, so a change to a unit there changes them
  too), install.md, and the design files above.
  web-search.md designs a search-API fallback for matching, not built. screenshots/: the
  README's pictures, of a demo library of public-domain songs, and make.py, which builds that
  library with no request and takes them again (its docstring says how): retake them when the
  pages they show change.

## Development

**Fast loop**: `nix develop -c pytest -q -m "not slow"` (about 6 s) while you work, and the
whole suite, `nix develop -c pytest -q` (about 35 s), before a commit. Always through `nix
develop`: its pytest has pytest-xdist, which spreads the suite over the cores; a pytest
without it runs the whole suite in one process, for minutes.

    nix develop        # Python 3.14 with the dependencies, pytest, pytest-xdist, chordpro, ruff, sqlite3
    caracole --help    # in either shell: the checkout's src/ (PYTHONPATH), no rebuild after an edit
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

Both shells set `CARACOLE_CJK_FONT` to the packages' font, `CARACOLE_PDF_FONTS` to their PDF fonts
(nix/pdf-fonts.nix), and `CARACOLE_ALPHATAB_DIR` to alphaTab (nix/alphatab.nix). `.#autochords` adds torch,
beat-this and librosa, and sets `CARACOLE_BTC_WEIGHTS` and `CARACOLE_BEAT_CHECKPOINT` to the
files nix/autochords.nix fetches. Tests that need a real program or model skip without it:

| Needs | Tests | Set by |
|---|---|---|
| `chordpro` on PATH, or `CARACOLE_CHORDPRO_BIN` | the tests marked `chordpro`: real PDFs | both shells |
| `CARACOLE_CJK_FONT`: one `.ttf` or `.otf` with CJK glyphs | Chinese PDFs | both shells |
| `CARACOLE_PDF_FONTS`: Adwaita's four files (`helpers.fonts.PDF_FONTS`) | the real PDFs in Adwaita Sans (test_render.py, test_render_all.py, test_songbook_render.py: their fonts, and the glyphs embedded), the two-column estimates in its widths, test_pdf_fonts.py's Adwaita test | both shells |
| `CARACOLE_ALPHATAB_DIR`: alphaTab's three files (`helpers.guitar.alphatab_dir`) | test_web_guitar_browser.py: the Guitar Pro page in Chromium | both shells |
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
the tests marked `autochords`), then check that the installed package is src/ file for file (the
suite imports caracole from src/, so a data file left out of the wheel shows only there: a new
asset folder goes inside src/caracole/) and check the wrapped `caracole`; `module` evaluates small
NixOS systems against nix/module-check.nix, loads their caracole.toml with config.py and parses
their units' command lines with caracole's own CLI (a command or option a unit names, renamed or
removed, fails it). One at a time: `nix build`, `nix build .#autochords`,
`nix build .#checks.x86_64-linux.module`.

Traps:

- The flake sees only files git tracks: `git add` a new file before a Nix build.
- The package builds from pyproject.toml, README.md, LICENSE, src/ and tests/ alone, in a sandbox
  without network (test_nix_package.py skips itself there). A subprocess test keeps the
  inherited PYTHONPATH (`conftest.subprocess_pythonpath`): the dependencies arrive on it.
- A dependency is listed three times: pyproject.toml, flake.nix (`runtimeDeps` or
  `autochordsDeps`) and nix/package.nix. It comes from nixpkgs: no pip, uv or PyPI pins.
  Every third-party module src/ imports is listed, even one another dependency brings (click
  with typer); auto-chords' modules may import the extra's.
  test_nix_package.py checks both.
- The version is in pyproject.toml and src/caracole/__init__.py; the package check compares
  `caracole --version` with pyproject's, and test_cli.py expects "caracole 0.1.0".
- A Nix file may set only `CARACOLE_*` variables the source reads (test_nix_package.py). A
  unit setting changes together with its expectation in nix/module-check.nix.
- docs/deploy.md's Ubuntu part pins by hand what Nix pins: its constraints.txt is the package's
  versions in flake.lock's nixpkgs, its CPython and deno are nixpkgs' too, and its SHA-256s are
  nix/'s (alphaTab's and the model files', which test_nix_package.py checks, and the fonts
  nix/pdf-fonts.py makes). A commit that moves flake.lock or nix/ moves deploy.md with it.
- `ruff check --select E4,E7,E9,F src tests` is clean; ruff's default rules and
  `ruff format --check` are not. Don't reformat code you aren't changing.
- Every pytest-xdist worker collects the suite itself and must find the same test ids:
  parametrize with nothing that changes between processes, such as a zip's clock-dated entries
  (helpers/zips.py `dated_entry`), random values or a set's order.

## How work is done here

- Test first: a test that fails (on the missing name or an assertion), then the code.
- Never a live request in a test: not to ultimate-guitar.com, lrclib.net, lacuerda.net,
  gtptabs.com, musescore.com or YouTube. Give `PoliteClient` an
  `httpx.MockTransport` as `transport=`; CLI tests monkeypatch
  `caracole.commands._common.transport_for` (and `_common.sleep`); pipeline tests pass
  `Services` with fake clients (`FakeGtpTabs.client` and `FakeMuseScore.client` make real
  ones); YouTube tests run `FakeYtDlp` as `ytdlp_bin`,
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
  music.py imports mutagen in `read_audio` alone, and lyrics.py (`expected_seconds`) in `_matches`:
  inbox.py, which the pages import, scores names with its `Names`
  (`test_music.py::test_the_pages_load_no_tag_reader`, `::test_the_inbox_loads_no_http_client`).
  viewer/pinyin.py imports pypinyin in `_read` alone: a page of a sheet with no Chinese loads none
  (`test_viewer_pinyin.py::test_pypinyin_is_loaded_only_for_a_sheet_with_chinese`).
- Branch from `caracole-v1`, the default branch; `main` takes it by merge, when the owner asks.
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
    and every command but `caracole get`, `caracole versions` and `caracole lacuerda --artist`
    and `--search`. Budgets per run:
    `ug` 60, `lrclib` 200, `lacuerda` 30 (its sheets first, then its listings of every
    artist, then, once those are read whole, the pages of its most popular artists not read in
    30 days, `lacuerda_fetch.POPULAR_PAGES` (10) at most), `gtptabs` 20, `musescore` 10 requests,
    `youtube` 6 yt-dlp runs
    (`config.DEFAULT_PROVIDERS`); `caracole index build` at least 100 (`BUILD_BUDGET`,
    commands/index.py). Then `BudgetExhausted`. Between any two requests to a provider, a
    random pause from its `delay` (10–20 s for UG, LaCuerda, gtptabs.com and MuseScore,
    1–2 s for LRCLIB).
  - **An interactive lookup**: `caracole get`, one song asked for just now (caracole serve's
    lookups run it), `caracole versions --keep`, one tab page asked for now (`--choose` and
    `--clear` run get), `caracole lacuerda --artist`, one artist's page (an artist's Songs), and
    `caracole lacuerda --search`, one query of LaCuerda's search (one request; a query at most once
    in 30 days, kv `lacuerda:search:<key>`, its words' key in alphabetical order; none once your library or
    LaCuerda's index answers it well, `lacuerda_search.answered`, checked again after the cached artist pages
    are stored; those the pages send by themselves, `--auto`, at most
    `lacuerda_search.SEARCHES_PER_HOUR` (20) in the last hour, counted in `events` under runs named
    `lookup:lacuerda-search:…`, within `lookup_per_hour`, and none of a query whose search failed within the
    hour, nor any once three did, kv `lacuerda:search-failed`: an answer caracole can't read is never
    asked again by every page that shows the query). Its clients are
    `make_client(..., interactive=True)`: a random gap from
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
    (kv `http:last_request:<provider>`, to the fraction of a second, else `events`), as bulk
    work's client paces its next one once its process let a lookup go first
    (`_LockedClient._after_a_lookup`). No gap
    is shorter than the host's robots.txt `Crawl-delay` (`http.ROBOTS_CRAWL_DELAY`, from
    the same `User-agent: *` groups as the rules below: none has one today).
  - Only a provider in `config.SWITCHABLE` (`gtptabs`, `musescore`, `youtube`) can be
    turned off (`enabled = false`): then it gets no client and its step is skipped.
  - A 403, a 429 or a challenge page raises `ProviderBlocked`: the client sends nothing
    more that run, `health.record_block` cools the provider down for 24 h × 2^(k−1) + 2 h after
    the k-th block in a row (so the next nightly run is always skipped), one ntfy alert goes out
    for the block, never one a song, titled with `logs.provider_name` (the run's step, or
    `_common.alert_block` in a command, `caracole fetch --song` from serve's review page too; a lookup
    sends none), and nothing retries or works around it (no proxies). A block a lookup met
    while bulk work let it go first is that work's too: its client sends nothing more
    (`_LockedClient._after_a_lookup`), and `record_block` adds no strike for a cooldown that
    began after its caller did, as `record_ok` clears none
    (`test_commands_common.py::test_bulk_work_sends_nothing_more_to_a_site_that_blocked_a_lookup_it_let_go_first`).
  - No URL robots.txt closes is asked for, or followed to (`http.ROBOTS_DISALLOW`,
    `robots_disallows`): not UG's `/search.php` (matching is local, against the sitemap
    index), `/tab/download`, `/tab/print?` or `/download/public/`, nor gtptabs.com's
    `/ru/` (half of its sitemaps), `/search/` or `/storage/` (an artist's "Download all"
    archive), nor musescore.com's `/api/jmuse`, `/score/*/download/*`, `/sheetmusic?`
    (its search) or `/oembed/*`. A host's rules are the `User-agent: *` group of its live
    robots.txt (tests/fixtures/gtptabs/ and tests/fixtures/musescore/robots.txt). LaCuerda's
    robots.txt is empty. A search (`caracole search`, `/api/search`) reads the local indexes
    alone, `lacuerda_index` among them, asks no site and takes no lock
    (`test_web_app.py::test_a_search_asks_no_site_and_takes_no_lock`); the one exception is
    LaCuerda's own search (`/busca.php`, lacuerda_search.py), sent as a queued job at the lookup
    pace (`caracole lacuerda --search`), one request, only when the query has settled and its gate
    allows (`lacuerda_search.gate`, read with no request: a word of four letters, neither your library
    nor LaCuerda's index answering it well already, not asked within 30 days, no cooldown, the hour's
    lookups, no failure within the hour), or by hand (its button, or Enter while the gate says `auto`
    or `button`), at most 20 an hour sent by the pages by
    themselves within `lookup_per_hour`, each query kept 30 days (kv and the HTTP cache). An artist's
    songs come from their page, read at most once in 30 days.
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
    `--no-remote-components`); an environment of its own (`ytdlp_env`: what a program needs, no
    `CARACOLE_*` variable); a stop or Ctrl-C stops its process
    group too; a bot check, an HTTP 429 or 403, a rate limit or a captcha
    is `ProviderBlocked`, honoured like any block (tests/test_youtube.py). Everything else
    keeps honouring robots.txt; widen nothing here without the owner, and copy it to no
    other site.
  - Every accepted 200 and 404 is cached forever, in `cache_dir/http/<provider>/`.
- **Errors are never misses.** A block, a spent budget, an HTTP or network error, or a page
  that won't parse (`PageParseError`, `GtpTabsParseError`, `LaCuerdaParseError`,
  `LrclibParseError`) never makes a song not found, its lyrics missing or its Guitar Pro
  file a miss: the song waits for the next run (http.py, pipeline.py, provider_pass.py, ug/fetch.py,
  lyrics.py, lacuerda_fetch.py, gtptabs_fetch.py;
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
  (`test_lacuerda_index.py::test_a_page_that_wont_parse_is_an_error_and_its_artists_stay`);
  a page of LaCuerda's search its server cut short (its table or list not closed, its script's
  arrays missing or disagreeing, fewer rows than it counts) is a `LaCuerdaParseError`, never "no
  results", and records nothing asked
  (`test_lacuerda.py::test_an_answer_cut_short_is_a_parse_error_never_no_results`), only the failure that
  keeps the pages from sending it by themselves for an hour
  (`test_commands_lyrics.py::test_lacuerda_search_that_failed_isnt_sent_by_the_page_again_within_the_hour_but_by_hand_it_is`).
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
- **Guitar Pro: gtptabs.com's downloads and the inbox, never Ultimate Guitar's.** The index
  keeps UG's chords and text tabs alone (ug/sitemap.py `KEEP_TYPES`): a Guitar Pro or Power
  Tab file's tab is counted by type and left out, so no song matches one and no page, search,
  count or link shows one
  (`test_index.py::test_guitar_pro_and_power_tab_files_are_counted_by_type_and_left_out`).
  ug/page.py gives UG's `Pro` and `Power` types no kind (`KINDS`: chords, tabs), so ug/fetch.py
  never rates, records or picks such a version, never reads an artist page's lists of them,
  and a `[pin]` of one pins nothing
  (`test_fetch.py::test_a_pin_ultimate_guitar_answers_with_a_guitar_pro_page_pins_nothing`,
  `::test_artist_page_kinds_fill_the_tab_slot_and_its_guitar_pro_lists_are_never_read`);
  `caracole get --tab` refuses a page whose address names another type before writing anything
  (`test_get.py::test_a_page_of_another_type_asked_for_as_the_tab_is_refused_and_nothing_is_written`).
  inbox.py files what the user drops into `_inbox/` by its name, for any song not ignored, as the
  song's lowest free `guitar-N`, under its own `inbox` version of the file's kind
  (`test_inbox.py::test_files_into_song_by_name`). Official and non-public versions are
  never used. gtptabs_fetch.py downloads from
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
  cascade), its per-song kv and its lines' `wanted:first_seen:`; then the files caracole wrote.
  `songs.upsert_song`, the one way a song is added, is given wanted.txt lines alone (`caracole
  add`, the web page, a line typed): a line for a removed song asks for it again, so its tombstone
  (found by source id or by key) goes and the song comes back new, or the line finds the song of
  that key the library has (after a re-keying). Nothing else may create a song
  (`test_removal.py::test_the_next_sync_brings_nothing_back_until_you_ask_for_the_song_again`,
  `test_songs.py::test_a_wanted_line_brings_a_removed_song_back_as_new`).
- **Schema changes go through db.py**: bump `SCHEMA_VERSION` and add the script to
  `_MIGRATIONS`. `_migrate` copies an existing database to `caracole.sqlite.v<N>.bak`
  (`VACUUM INTO`, under a name of its own, then renamed), then runs each script in one `BEGIN IMMEDIATE`
  transaction with its `PRAGMA user_version` (a script never begins or commits one itself); one connection
  migrates at a time, of every thread and process (an flock on `caracole.sqlite.migrating`, the version read
  again under it: `test_db.py::test_connections_opened_at_once_migrate_once_and_each_opens_the_database`). A newer database
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
  Nothing private or bulky goes there: the database, the lock, the HTTP
  cache and the audio taken from YouTube (`cache_dir/youtube/`, youtube_fetch.py) stay in
  `state_dir` and `cache_dir`, and chordpro works on a copy in a 0700 folder under the cache
  (render.py). tests/test_library_safety.py. A removal deletes only what caracole
  wrote in the song's folder (`removal._caracoles`: kept files, the outputs of a kept sheet or
  of a render record, its exports, a version's page `render:files:` records, LRCLIB's lyrics, info.json), by name, through descriptors opened with
  `O_NOFOLLOW` from the library down, and names everything it leaves; it never touches Music/,
  and deletes the song's audio taken from YouTube from the cache (tests/test_removal.py).
- **One caracole at a time**: `_common.exclusive` holds an flock on `state_dir/caracole.lock`,
  re-entrant within a process, and the clients of `make_client` and the yt-dlp runner of
  `make_youtube` hold it until closed. Every command that asks UG, LRCLIB, LaCuerda,
  gtptabs.com, MuseScore or YouTube for pages or writes the library takes it;
  `search`, `match --dry-run`, `index stats`, `remove --list`, `songbook list`,
  `songbook show` and `versions` (the list alone) only read and never wait.
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
  lookup killed while it waited, no longer counts). `caracole versions --keep` and `--clear` (which
  writes overrides.toml under it) wait so too, and `--choose` through get. Every changing `caracole songbook`
  command (make, add, remove, move, set, rename, delete, render: commands/songbook.py) waits the
  same way, as a songbook is asked for now
  (`test_commands_songbook.py::test_a_change_waits_for_the_nightly_run_as_a_lookup_does_never_for_its_whole_run`).
  Bulk work hands the lock over
  (`_common.hand_over`, never inside a transaction): it lets go of the flock, takes it back
  once the lookup is done, counts the handoff (`_common.handoffs()`), and goes on. That count is
  how everything below learns a lookup went first (a client's block and pace checks, the re-reads
  of songs and overrides.toml): it is the one way to let go of the lock mid-work. It hands it to lookups alone: meanwhile it holds the
  flock of `state_dir/caracole.lock.handoff`, and a caracole that isn't a lookup lets go of a
  lock it took during a handoff and waits for it to end (`_common._take_outside_handoffs`), so a
  `caracole-admin` command waiting for the run takes the lock after it, never in its middle
  (`test_commands_common.py::test_the_nightly_run_hands_the_lock_to_a_lookup_alone_never_to_another_command_waiting`).
  It does so in two places. Its clients, and the
  yt-dlp runner of `make_youtube` between two runs, spend each pause looking for a waiting
  lookup (every `HANDOFF_SLICE` s), then pause a whole `delay` again
  (`test_commands_common.py::test_the_youtube_steps_pauses_hand_the_lock_to_a_waiting_lookup_too`).
  Work that sends no request does it between two songs (a `between` callback):
  `autochords_pending` (commands/autochords.py) and `render_all` (pipeline.py's render step,
  commands/render.py). A bulk caller
  holding state across a handoff re-reads it after one: ug/fetch.py `fetch_songs` reads each
  song and overrides.toml again (`_Handoffs`; a song a lookup fetched mid-turn is fetched
  again next run), lacuerda_fetch.py `lacuerda_sheets` reads each song and overrides.toml again
  and passes over a song no longer to try (`_Lookups`; after a handoff within a song's turn, it
  records what LaCuerda answered only for a song still to try with the pick the turn asked for:
  `test_lacuerda_fetch.py::test_a_tab_a_lookup_pinned_during_the_songs_own_turn_is_never_replaced`),
  gtptabs_fetch.py checks a song still has no file
  before its turn, and `autochords_pending` and `render_all` read each song after and
  overrides.toml again; what comes after (the run's next steps, `StepContext.read_overrides_again`;
  the songbooks and pages of `caracole render` and `autochords`; the pages of `caracole fetch`,
  `youtube`, `icons` and commands/lyrics.py's `_provider_pass`) reads overrides.toml again too
  (`_common.overrides_since`;
  `test_lacuerda_fetch.py::test_a_tab_a_lookup_pinned_during_an_earlier_step_is_never_replaced_by_lacuerda`,
  `test_commands_common.py::test_the_nightly_run_hands_the_lock_to_a_lookup_during_its_pause`,
  `test_autochords_run.py::test_a_lookup_waiting_for_the_lock_takes_it_between_two_songs`).
  `serve` never takes it: it reads like `search` and appends to wanted.txt like `add`, and
  runs every other change as a `caracole` command in a child process, one at a time
  (web/jobs.py), since the lock is re-entrant within a process and its threads would share it:
  a removal too, `caracole remove --yes`, once the line's five seconds with Undo are over
  (the library page's script; without it, a page of its own), having asked what goes
  (`removal.plan_removal`, which only reads, and `removal.brief`); its job's song key is
  `remove:<key>` (`jobs.REMOVING`), so it never joins the song's add or fetch.
- **wanted.txt is the one source of songs.** `sources.sync_sources` syncs it alone, and a song's
  album, duration, ISRC and variant are what its line says now, kept in its record alone
  (`songs.upsert_song`; `test_songs.py::test_a_song_keeps_what_its_line_says_in_its_own_record_alone`).
