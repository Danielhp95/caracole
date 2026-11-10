# AGENTS.md

What a coding agent needs before changing caracole. User documentation: README.md, docs/.

## What caracole is

caracole is a Python CLI, run every night by a NixOS service, that builds, for the songs in `wanted.txt`, a private
library of:

- sing-along chord sheets (Ultimate Guitar, LaCuerda);
- lyrics (LRCLIB, then Megalobiz for timed ones, AZLyrics for plain ones where neither has any);
- PDFs (ChordPro);
- Guitar Pro files (downloaded from gtptabs.com, or filed from what the user drops into `_inbox/`);
- harmonica tabs (harptabs.com).

For a song nobody has charted, `caracole autochords` writes a sheet from audio with local models (torch, optional):

- a purchase;
- or audio the nightly run takes from YouTube with yt-dlp (youtube.py, youtube_fetch.py), a few songs a night, only
  where auto-chords is;
- or that of a video the owner pastes on the library page, made into the song's sheet at once (youtube_sheet.py).

The design lives in three files:

- `plan.md`: design v2.1, and why. Its code sketches are older than the code: its module runs
  `caracole run --config …`, which the CLI rejects (`--config` is a root option: `caracole --config FILE run`).
- `docs/superpowers/plans/2026-10-18-caracole.md`: the task plan, with amendments A1–A7 made during the build:
  A2 `wanted.txt`, A3 Chinese titles, A4 command plug-ins, A5 agent rules, A6 bare-id tabs, A7 `index.html` and
  `caracole search`.
- `docs/spike-2026-10-18.md`: what the live sites did when checked. It corrects plan.md:
  - UG's `Pro` is a public Guitar Pro file;
  - a slugged tab answers only at its slugged URL.

## Layout

In `src/caracole/`, `caracole run` (pipeline.py) runs these steps in order, each one even when an earlier one failed.

Each module's docstring says what it does and why, and each package's `__init__.py` how the package is laid out
(commands/, web/, viewer/, library_assets/, autochords/): the details live there, beside the code they describe, and
change with it. This section says where things are, and the rules a change there keeps.

### The run's steps

Below the table, a section for each step whose modules have more to say.

| Step | Modules |
|---|---|
| sync | sources.py, wanted.py (the one source of songs), songs.py |
| icons | icons.py (each source's mark) |
| index | ug/sitemap.py, ug/index.py |
| match | match.py, ug/lookup.py |
| lyrics | lyrics.py |
| megalobiz | megalobiz.py, megalobiz_fetch.py |
| azlyrics | azlyrics.py, azlyrics_fetch.py |
| fetch | ug/fetch.py, ug/page.py, ug/artist.py, ug/artist_tabs.py, rank.py, coverage.py, versions.py, sheet_versions.py |
| lacuerda | lacuerda.py, lacuerda_fetch.py, lacuerda_index.py, lacuerda_search.py |
| scan | music.py (Music/), inbox.py (`_inbox/`), musicxml.py |
| gtptabs | gtptabs.py (URLs, parsing), gtptabs_fetch.py (the step) |
| harptabs | harptabs.py, harptabs_fetch.py, harptabs_index.py |
| gametabs | gametabs.py, gametabs_fetch.py, gametabs_index.py |
| musescore | musescore.py (URLs, parsing), musescore_fetch.py (the step) |
| youtube | youtube.py, youtube_urls.py, youtube_fetch.py, youtube_sheet.py, youtube_search.py |
| render | chordpro.py, render.py, pdf_text.py, viewer/, songbook.py |
| todo | todo.py (`_todo.md`), library_page.py (`index.html`), library_assets/, songbook_section.py, song_sites.py |
| backup | backup.py |

#### lyrics

- lyrics.py: LRCLIB.
  - `Lyrics.provider` and `.url`: who answered and the page to link back to.
  - `fits` and `another_version`: the matching rules another site's picker keeps.
  - kv `lyrics:failed:`: the songs LRCLIB failed on.

#### megalobiz

- megalobiz.py: Megalobiz's public API: its search and a record read, `pick_result`; `MegalobizParseError`.
- megalobiz_fetch.py: the step.
  - The songs LRCLIB left, missing, failed on or plain only: `songs_to_ask`.
  - A miss: kv `megalobiz:checked:`, asked again after 30 days.
  - An error puts a song LRCLIB missed back to pending.
  - The link back its fair use asks: info.json's `lyrics_from` and the card's Lyrics tile, `library.lyrics_from`.
- Also in `caracole lyrics`, a lookup and a sheet from a YouTube video.

#### azlyrics

- azlyrics.py: its pages read:
  - an artist's address from their name, `artist_url`;
  - their page's songs, `parse_artist`, `pick_song`;
  - a lyrics page, `parse_lyrics`;
  - `AzLyricsParseError`.
- azlyrics_fetch.py: the step.
  - The songs still with no lyrics, missing or failed on by LRCLIB: `songs_to_ask`.
  - Two requests a song, no index and no list of artists.
  - `[azlyrics]`: a page named, one request.
  - A miss: kv `azlyrics:checked:`, asked again after 30 days.
  - An error puts a song LRCLIB missed back to pending.
  - The link back as Megalobiz's: `library.LYRICS_PAGES`.
- Also in `caracole lyrics`, a lookup and a sheet from a YouTube video.

#### fetch

- ug/fetch.py: UG's chords and text tabs, and its Ukulele Chords as the sheet of a song with no chords there:
  `UKULELE_KINDS`, `sheet_group`.
- ug/page.py: tab pages; `KINDS`, the types caracole uses: chords, tabs, ukulele.
- ug/artist.py: artist pages.
- ug/artist_tabs.py: the tabs of every artist page read, kept for searches: `ug_artist_tabs`, schema 7.
- rank.py, coverage.py, versions.py.
- sheet_versions.py: a song's UG chords versions in rank order, or its ukulele chords ones when its sheet is one
  (`sheet_kind`, `group_of`).
  - The one and those kept beside it as `version-<tab>.txt`, `.json`, `.html`: the versions the fetch scores,
    written by ug/fetch.py's `_keep_beside` with no request more, a pinned sheet's from the cache alone.
  - `in_library`: the list as the library holds it; and `in_library_of`: many songs' in a few queries, the library
    page's.
  - `may_keep`: those a keep may still keep, the page's count of the rest.
  - `as_data`: the pages' JSON.

#### lacuerda

- lacuerda.py: URLs, parsing, its search's pages.
- lacuerda_fetch.py: the sheets.
  - `may_ask`: the songs LaCuerda may have, for the step and the to-do page.
  - `popular_pages`: the most popular artists' pages once the listings are read whole.
- lacuerda_index.py: its listings of every artist, for searches.
  - `backfill_cached`: the artist pages the HTTP cache holds.
  - `store_search`: what its search answered.
- lacuerda_search.py: its own search, one query at the lookup pace, `caracole lacuerda --search`.
  - `gate`: whether the pages may send it.

#### harptabs

- harptabs.py: URLs, and:
  - its sitemap's rows (a tab's key with a contraction's end joined to its word, `joined`, which `title_keys` meets);
  - a tab page read;
  - an artist page read: its name, the tabs it says they have and the 30 it lists, `parse_artist_page`;
  - `song_title`, `song_key`: the song a tab's title names;
  - what the site answered caracole's probe.
- harptabs_fetch.py: the step.
  - A song's candidates by title, its artist confirmed on the page, the most viewed kept as `harmonica-N.txt`,
    provider `harptabs`, kind `harmonica`.
  - `inbox.harmonica_files`, which library_page.py and render.py read: the viewer's data `harmonicaTabs`, each with
    its `page`, `inbox.harmonica_page`.
- harptabs_index.py: its artist pages read into `harptabs_artists` and `harptabs_artist_tabs`, schema 11, for
  searches.
  - `artist_pass`: the step's with what its budget leaves and `caracole harptabs --index`'s; your songs' artists
    first, each page again after 30 days, resumed across runs.
  - `read_artist`: one page now, `caracole harptabs --artist`.
  - `index_state`: how far it has got.

#### gametabs

- gametabs.py: URLs, and:
  - its sitemaps' rows (a slug's number, `main-theme-108`, one more tab of a title, `IndexRow.key`, never part of
    it, `slug_key` the whole slug's);
  - a tab page read: its `data-tab` JSON, else its microdata, and its `<pre>`;
  - a game page read: each tab's composers and instruments, 50 a page, the site's instruments by its shuffle
    dialog's names.
- gametabs_fetch.py: the step.
  - A song's candidates by title, of a game or a composer its artist is (`game_forms`: "Hollow Knight OST" is the
    game).
  - The most viewed agreeing page kept as `gametab-N.txt`, provider `gametabs`, kind `gametab`, opened as text as
    UG's `tab.txt` is.
  - `[gametabs]`: a tab you picked.
- gametabs_index.py: its game pages read into `gametabs_games` and `gametabs_game_tabs`, schema 13, for composers.
  - `game_pass`: the step's with what its budget leaves and `caracole gametabs --index`'s; your songs' games first,
    each page again after 30 days, resumed across runs.
  - `index_state`.

#### youtube

- youtube.py: running yt-dlp.
- youtube_urls.py: a video's address.
- youtube_fetch.py: the step.
  - `song_states`: where each song stands for the pages: `todo.write_pages` asks once and hands it to both, a
    one-song card asks of its song alone.
- youtube_sheet.py is no step but `caracole youtube --sheet`: one song's auto sheet from a video now.
  - Its stages song, audio, lyrics, chords, pdf, pages, reported as a lookup's.
  - LRCLIB asked with the audio's length.
  - `autochords_pending(only=)`.
  - caracole serve's sheet from a YouTube video runs it (web/youtube_routes.py).
- youtube_search.py is `caracole youtube --search`: a search's first video and its thumbnail, suggested on the
  library page (`gate`, `sheet_on_screen`, `checked_jpeg`).
  - And `caracole youtube --video`: a pasted video's metadata (`video_gate`, `read_video`, `song_of_video`).
- A pasted video's "Artist - Title" is song_names.py's, from its title and channel.

#### render

- **chordpro.py**: UG markup to ChordPro.
- **render.py**: PDFs.
  - **Chinese sheets**: a Chinese sheet's (`page.written_script`) in Simplified characters, and in Traditional ones
    beside it, `songs.TRADITIONAL_PDFS` (`sheet (Traditional).pdf`, `sheet (auto, Traditional).pdf`).
    - `_render_traditional`, kv `render:<id>:trad`, gone with its sheet's Chinese.
    - The printed text converted as the viewer converts the page (`hanzi.chordpro`, `_in_script`), the .cho as
      written.
    - An export in the characters its viewer showed, `trad=1` (`export_traditional`, its label ", Traditional").
    - songbook.py's `songbook (Traditional).pdf` for a songbook with a Chinese song.
  - **Kept versions**: a viewer page alone for each version kept beside the sheet, `version-<tab>.html` from its
    `.json`, with no Export PDF (an export is the one's), recorded in `render:files:` and dropped once the version
    leaves.
  - **Harmonica tabs**: a page for each harmonica tab kept, `harmonica-N.html` beside its `.txt` (how, below),
    recorded in `render:files:` and dropped once the tab leaves or its text is gone (test_render_harmonica.py,
    test_viewer_harptab_browser.py).
  - **What every viewer of the song carries**:
    - `versions`, `sheet_versions.as_data` with `sheet`, the one's provider, `pinned`, whether a `[pin]` chooses it
      (`sheet_versions.sheet_pins`, what `caracole versions --clear` takes out), and `this` on each entry, true on the
      page's own;
    - and `guitar`, the song's kept Guitar Pro files caracole serve shows in the browser (`inbox.guitar_files`),
      linked in served settings as Guitar Pro tab.
  - **Exports**: `render_version`, an export: the PDF in a viewer's version of the sheet `export_viewer` names, the
    human one else the auto one, on the instrument its `inst=` names (`export_version`; `sheet (A Major, piano).pdf`),
    while `sheet.pdf` is the guitar's (`on_the_guitar`).
    - Listed under PDF exports in its line's ⋯ on index.html, where Sheet versions lists the UG versions kept beside
      the sheet (`sheet_versions.in_library`, library_page.py `_versions_data`).
  - **The song's own version**: `own_version`, the song's own on one of its sheets, overrides.toml's `[version]`:
    - kept by the key it plays in, as Make this my version writes it (`ExportSheet.entry`, `key=Gm&mode=dorian&capo=0`:
      the key of the shapes in the mode the sheet's chords are read in, a mode only where one was chosen, shapes by
      their frets);
    - which each sheet takes by a songbook setting's rule, its chords read in the notes of its own key, so a replaced
      sheet plays in that key, and one that reads the same chords in the relative key, or names the parallel one for
      them (`version._fitting`), plays them;
    - or, written before, a `t=` move from the sheet, which Make this my version, asked again, keeps by its key.
    - `own_versions_upgraded`, at the start of `render_all` and `render_songbooks`, rewrites once
      (kv `keys:own_versions`, through `overrides.add_version`) an entry kept by a major letter alone on a sheet now
      read minor, in the minor key that plays it where it did.
  - `version_pdf`: `render_version`'s PDF as bytes, made in a private folder and written nowhere (caracole serve's
    Export PDF, a download).
  - **The chordpro plumbing songbook.py shares**:
    - `run_chordpro`, a run's errors as `RenderError`s;
    - `private_dir`, the 0700 folder chordpro works in;
    - `pdf_font`, the font a text needs;
    - and `written_entry`, the one reading of a file written's record.
- **pdf_text.py**: each PDF's own text.
  - `names`: the theory edition's chord names: each chord and its numeral, or the numerals alone in a chart with no
    diagrams, with a legend from `harmony.glossary`.
  - Its two columns end level, at a section, by `line_heights` and `column_height`: chordpro's layout in caracole's
    style, chordpro-style.json's sizes and the PDF fonts' widths (pdf_fonts.py), which test_render.py pins to the
    real chordpro's pages in the built-in fonts and in Adwaita's.
  - On another instrument, a version's text with a song config of its own, `##config: json`:
    - `instrument_config`: a ukulele's `tuning`, so its four strings take each `{define}`; the piano's keyboard,
      `KEYBOARD`, a `{define: X keys …}` of the viewer's first position, `version.define_keys`;
    - the harmonica's harps and each chord's holes (harp.py `header_line`, `play`) or the winds' scale in place of
      diagrams;
    - the instrument and its folded capo under the title;
    - the rows of diagrams `column_height` counts read from that config.
  - One chordpro run draws one number of strings, chordpro 6.050.7's tuning being global, so a songbook draws its
    most common one and writes the others' shapes as frets, `diagrams=False`.
- **viewer/**: sheet.html, songbook.html, and:
  - **version.py**: a viewer's version applied to a sheet in Python, and where a key plays a sheet.
    - `Setting`: key, mode, capo, instrument.
    - `in_setting`: the setting's key as the key of the shapes played (on an instrument with no capo, the key it
      sounds in), its mode and capo.
    - A `Version`'s `inst`: the viewer's `inst=`, which `apply_version` shapes for (a ukulele's frets, the piano's
      keys, none for the harmonica and the winds) and `played_key`, `version_label` and `played_label` fold the capo
      in for ("A Major, piano").
    - `KeyVersion`: a `[version]` kept by its key, its swaps and shapes by their chords' names: `key_version` reads
      one, `version_entry` writes one, `in_key` plays it on any sheet.
  - **harmony.py**: what each chord does in its key on top of theory.py:
    - Roman numerals, relations, families, glossary lines, chord tones, solo scales;
    - progressions named from its `CATALOGUE` (each row with its source; a row of `_LOOPS` from any of its chords,
      the others from their first; a cycle a section plays whole, or `contains`, the ones played within a longer
      section, within each pass of one played round) and their endings;
    - a section's repeats folded round a pass that varies them (`_fold`);
    - `progression_key` for searching, `name_of` and `read_typed` for numerals typed.
  - **harmony_tables.py**: its answers as the tables a viewer's data carries, per mode, each text naming notes
    written for every transposition, for viewer.js to look up.
  - **strum.js**: a chord's shape strummed in Web Audio, `window.caracoleSound`, each instrument's voice.
  - **overlay.js**: the rail of a wide screen, Guitar (the necks) and Harmonica (the circle of fifths, the key on the
    harp chosen, each chord's holes, the slim bar), and narrower the phone's sheet, `window.caracoleOverlay`, which
    viewer.js and harptab.js draw with what they look up.
  - **harp.py**: the Richter harmonica:
    - its layout in every key, positions by Wikipedia's circle-of-fifths numbering;
    - the overlay's tables by steps above the tonic (`ring`, `holes`, `key_scales`, `outside`, `chord_steps`);
    - the chords a harp plays (`play`: whole, as its triad, a minor substitute, or not);
    - and the harps for a song (`choices`, `header_line`), ranked by one rule in one place (`candidates`,
      `CHORD_FIT`, `TONIC_WEIGHT` and `ranking`): a major key's 1st position, then its 2nd, the owner's; any other
      mode by the chords each plays.
  - **winds.py**: the flute's and the soprano recorder's fingerings (baroque and German), a melody's octave (`fit`),
    a key's scale and a chord's notes as they read them.
  - harp.py and winds.py, each with its `tables` in a viewer's data, for **winds.js**, which registers the Harmonica,
    the Flute and the Recorder with instruments.js:
    - the harmonica's line under the key line, a chord's holes on the card and the strip, its settings row (a harp of
      the line chosen, each chord on it, the song's `harmonicaTabs` linked);
    - the winds' fingerings of a chord's notes and their row (A–G or Do–Si, the recorder's baroque or German, the
      key's scale);
    - the notes heard in strum.js's `reed`, `flute` and `recorder` voices.
  - **instruments.py**: the instruments the viewer draws chords for, `INSTRUMENTS` (guitar, ukulele high and low G,
    baritone, piano, harmonica, flute, recorder: tuning, capo or none, where its shapes are, easy keys):
    - the ukuleles' shapes from chords-db (voicings-ukulele.json, filed by the guitar's keys, the baritone's a fourth
      lower);
    - the piano's computed (`piano_positions`: root position and two inversions, a left-hand bass);
    - `chord_shapes`, what the viewer shows a chord on one;
    - and version.py's `for_instrument`, the capo folded in on one that takes none.
  - **instruments.js**: their box and keyboard and `window.caracoleInstruments`, where another instrument's script
    registers its drawing, a header line and a settings row.
- **songbook.py**: songbooks.toml: a song is a string, or a table with its own `Setting`, `instrument` among its parts
  (`caracole songbook set --instrument`, the Songbooks tab's chip; `_run_strings`, the strings its PDF draws).
  - `SongbookSong`, `Songbook.songs`, `.texts`.
  - `set_song_setting`, and `with_capo`, the capo a key or a mode `caracole songbook set` gives plays at now, so a
    replaced sheet keeps the key it sounds in, and `on_instrument`, the key and capo `--instrument` alone takes to
    keep the pitch, songbooks.js's menus' rule.
  - Its files play each song through `apply_version`, never chordpro's `{transpose}`, where `in_setting` puts it,
    the rest the song's `own_version`.
  - `plays_in`: that in words, "key unknown, as written" for a sheet with no key that a setting or the song's own key
    can't take.

#### render: a harmonica tab's page

`harmonica-N.html` comes of `_render_harmonica`, whatever came of the sheet's PDF:

- viewer/harptab_page.py `build_harmonica_viewer`, page.py's `_page` with viewer.css and harptab.css, strum.js,
  overlay.js and harptab.js.
- **harptab.py reads the tab**, its holes over syllables in the sheet's `.s` columns:
  - a notation is data (`Notation`, its `Symbol`s: a mark, its meaning, before, after, around or between holes;
    `PRESETS` signs, brackets, letters, signs after, barrett, the commonest first);
  - its tokenizer compiled from it (`scan(notation=)`);
  - the tab read under each candidate and the best kept by Q = P × T (`read`, `Reading`: the share of its lines of
    holes explained, times the share of holes `harp.hole_note` plays; ties to the commoner, `MARGIN` for a less
    common one, `TAB_Q`);
  - a legend of `SYM = meaning` lines one more candidate and a weight, never an order (`legend`, `LEGEND_WEIGHT`);
  - the harp chip harptabs.com's page names (`inbox.HarmonicaFile.harp`, `parse(harp=)`: Chromatic is the text as
    written, Diatonic one more candidate, `STAR_BENDS`);
  - `DOTS` where a dot comes before a hole;
  - `parse(notation=)` a reading pinned, drawn whatever its Q (`pinned`, a pin of overrides.toml's `[harmonica]`: a
    preset, "legend", or a table, `check_spec`; `readings`, every reading weighed, best first, `spec_of` the pin of
    each);
  - what a notation can't read: a group of kind "unread" in place, never dropped;
  - the tabber's words in a line of holes: one of kind "words" (`Scan.prose`, `Scan.explained`: a row with its words
    aside, `is_row`);
  - a row under `ROW_TRUST` (`Row.trusted`): its text as written; a tab not `Tab.readable`: all of it;
  - a row's words: the line by it no section's name (`_is_label(beside_row=)`: "End of the road" is sung) and no line
    of holes (`Scan.holey`), the line above it in a tab whose words above fit its rows better, syllables to holes
    (`_above`, `Row.above`);
  - the page's "Read as" line: `Reading.symbols`, none for `Reading.standard` (harptabs.com's own key, guessed: its
    familiar legend), its source a link served to caracole serve's `/harmonica` (harptab.js; a standard tab's or one
    shown as written, "Change how it's read" at its foot).
- **harpfit.py** chooses the harp it starts on, with the record by the sheet's chords, else the tab's words,
  harptabs.com's key, the song's key, a C harp, `Choice.why` (`tabs_harp`, the record's or the words', the overlay's
  "the tab's", which `_tab_harps` gives the sheet's viewers, page.py `harpTabs`).
- **Its overlay**: Harmonica first, its harp the page's both ways, Guitar the sheet as written, harptab_page.py
  `_overlay_data`.
- **The bar**: the bar's harp −/+, Notes, a hole tapped and a line's ▶ in strum.js's reed voice, every note looked up
  in harp.py's `hole_tables`.

#### todo

- todo.py: `_todo.md`.
- library_page.py: `index.html`.
- library_assets/.
- songbook_section.py: its Songbooks tab's data.
- song_sites.py: which sites have each song, had nothing or weren't asked yet: its card's marks, rows.js
  `siteMarks` (card.js `sitesOf`).

#### backup

- backup.py: a whole copy of the database, `VACUUM INTO` on the run's connection, into `state_dir/backups/`.
  - Checked by `PRAGMA quick_check` before it takes an old one's place.
  - The newest `KEEP` (3) kept; none made and none deleted without room (`needed`, `Skipped`).
  - The one step that waits for a run no step of which failed, and a copy failing its check fails the run.
  - `caracole backup` (commands/backup.py) makes one by hand, and `index merge` one before it changes anything.

### Each step's report, and the log

- Each step returns a `report.StepResult` (what it did, counted; the songs a provider's error left, with the error;
  what needs the user), which report.py turns into the run's summary on stdout and ntfy: a new step plugs in by
  returning one.
- The log goes to stderr, set up once by the root callback (logs.py: `-v`, `-vv`, `-q`, journal priorities; under
  systemd, the information of `JOURNAL_INFO`'s loggers too at the default verbosity: page_log.py's).

### Shared by the steps and the commands

| Module | What for |
|---|---|
| config.py | caracole.toml and directories, and no secret (ntfy is a topic's URL alone); `name`, what the pages call the library (`Config.library_name`: else its folder's name) |
| index_transfer.py | `caracole index export` and `merge` (below) |
| peer_sync.py | two caracoles compared and synced, unit by unit (below) |
| canonical.py | canonical JSON: one text, so one digest, for a value in Python and in Kotlin (`dumps`, `digest`, `read`, `stored_hash`; docs/superpowers/specs/2026-11-03-canonical-json.md); the standard library alone |
| peer_push.py | a push: the units another caracole (the phone) gives this one, staged by caracole serve, taken by `caracole peer take` (below) |
| peer_file.py | a library in a `.caracole` file: `caracole peer export` writes one, `caracole peer import` syncs with one (below) |
| peer_import.py | a file to import, staged part by part in `state_dir/peer/import-<id>/` (peer_file.py, below) |
| politeness.py | the settings the computer gives the phone at a sync (`settings_document`: caracole.toml's name, the user agent, each provider's switch and lookup settings, `[match]`, `[rank]`), never its politeness (Two caracoles, each its own politeness, below); the standard library alone |
| service.py | whether this machine runs caracole as a service (below) |
| db.py | the schema, migrations, `kv`, `savepoint` (atomic writes on the autocommit connection) |
| http.py | `PoliteClient`, robots rules, cached answers (`stale`, `read_once_more`; `cached` and `CachedAnswers` read the cache alone, sending nothing) |
| health.py | cooldowns, `events` |
| normalize.py | keys, pinyin, `name_forms`; `name_words`, `holds_run` and `PINYIN_PARTIAL_SCALE`, Chinese in pinyin only as whole words, for search.py and lacuerda_index.py |
| song_names.py | the artist and the title a free text names, the one parser of it (below) |
| inline.py | what a page holds inline: a script or a style by its hash, a JSON data block; the standard library alone |
| pdf_fonts.py | the fonts every PDF is set in (below) |
| page_log.py | the library page's line in the log, one a build (below) |
| page_icon.py | the mark in every page's tab, "¿" drawn in SVG (`LINK`, a `data:` URI for a page's head; `SVG`, caracole serve's `/favicon.ico`); the standard library alone |
| library_name.py | which library a page shows (below) |
| overrides.py | overrides.toml (`[harmonica]`: a tab's reading pinned, `add_harmonica`, checked by viewer/harptab.py `check_spec`) |
| library.py | song folders, safe file access in the synced library |
| download_names.py | the name a kept file downloads under ("Eagles - Hotel California (2).gp5"): web/app.py's `Content-Disposition`, the `download` of index.html's and the viewer's links; the standard library alone (the viewer imports it) |
| notify.py | ntfy |
| site_index.py | a site's sitemaps into a table, resumed across runs; one that answers cut short, before its closing `</urlset>` or `</sitemapindex>`, an error that leaves the table as it was, never fewer rows |
| stamps.py | how caracole stores a time and shows one (below) |
| provider_pass.py | one song at a time through a provider (`each_song`, `PassStats`): the lyrics, LaCuerda, gtptabs.com and YouTube passes share its ladder of errors that are never misses, and name the songs an error left (`failures`) |
| keys.py | a song's musical key and where it came from (below) |
| removal.py | `caracole remove` and the web page's Remove; the tombstones it leaves are songs.py's |
| sites.py | the library page's Sites tab's data (below) |
| progress.py | a command's output: a live line on a terminal, plain lines elsewhere |
| progressions.py | each song's progressions (below) |

#### index_transfer.py

- `caracole index export` and `merge` (commands/index.py).
- **Export**: every site's index (`SITES`: its tables and the kv records of its progress) into a new SQLite file, in
  one read transaction, with its `caracole_export` table (format, schema, sites).
- **Merge**: such a file into the database under the lock:
  - refused whole (`TransferError`, status 2) for another schema or other columns;
  - else per site what the file read more recently:
    - a sitemap or LaCuerda listing page by its record's time (UG's rows upserted as a refresh stores them, its new
      tabs' songs marked);
    - harptabs.com's artist and gametabs.net's game pages by `read_at`;
    - UG's artist pages' tabs a row at a time;
    - LaCuerda's artist pages and search rows only where the database has none;
  - progress records move on, never back;
  - backed up first (backup.py, `before-merge`) only when something changes, so a second merge writes nothing;
  - each index's `ensure_current_keys` after, whole where the file's keys record differs.

#### peer_sync.py

- Two caracoles synced: `caracole peer diff`, `sync`, `pull` and `new-id` (commands/peer.py); the design is
  docs/superpowers/specs/2026-10-31-phone-server-sync-design.md.
- **Units** (`library_state`): a library cut into units, each taken whole:
  - `song/<key>`: its names, decisions, versions, kept files' hashes and every overrides.toml entry about it
    (`overrides.song_entries`);
  - `removed/`, `songbook/`, `alias/`, `artist_url/`, `block/`;
  - never what caracole makes of one, nor what a lookup finds again.
- Each unit's `digest` is its canonical JSON's SHA-256 (canonical.py's `digest`), a version's raw record and a song's
  lyrics hashed canonicalized (`stored_hash`), so the phone's Kotlin gets the same digest of the same record.
  - A version's raw record is hashed without what `VOLATILE_RAW` names for its provider (`stored_hash`'s `without`):
    UG's ratings and votes, the owner's choice of 2026-11-03 ("Don't count them for the sync"); the version's JSON
    kept beside a UG sheet or tab (`sheet.json`, `tab.json`, `version-<tab>.json`) holds neither
    (ug/fetch.py `KEPT_WITHOUT`, the phone's `Slots.keepText` alike), so a tab read on both sides on two days is no
    conflict (`test_fetch.py::test_a_tab_read_on_two_days_is_kept_alike_and_is_one_song_to_a_sync`). A JSON kept
    before that holds them until the fetch keeps it again.
- **FORMAT 3** (`FORMAT`) is of every document a side answers (the state, a unit, a push) and of the base each keeps
  (`{"format": 3, "units": …}`): a base of another format reads as none, so the first sync after a format bump
  compares as a first sync (no shim). FORMAT 2's digests hashed UG's ratings and votes.
- **Comparing** (`compare`): three ways, against the base.
  - The base is each side's agreements with that peer (kv `sync:base:<peer id>`: a digest or None, and when),
    recorded by `record_agreement` at the end of every pull, and merged with the peer's by the later
    (`merged_base`).
  - A unit changed on one side is that side's; on both, differently, a `CONFLICT` (`decide`: as chosen, else
    `--prefer`, else left).
- **The remembered answer**: an import's "keep mine", kept beside the base (`record_kept`, `kept_of`: its `"kept"`,
  `{unit: [digest here, digest there, when]}`, at the file's `made`), since a file can't take this side's version.
  - `state_document(kept=)` carries those kept for the asker (`"kept"`, no member unless given; `PeerState.kept`),
    which `GET /api/peer/state` serves from sync-exchange on; `merged_kept` takes, a unit at a time, the latest of
    each side's agreement and kept answer, an agreement on a tie, the other's swapped.
  - `compare(..., kept=)`: a unit changed on neither side since is the chooser's (`KEPT_HERE`, `KEPT_THERE`), never
    a conflict asked again; a change after it is compared as usual.
  - An agreement (`record_agreement`, given each side's whole state) drops the answer of each unit it agrees on,
    both sides' alike or both lacking it, and a base with none is written as before.
- **Parts** (`PARTS`: library, songbooks, indexes; `part_of`, by a unit's kind; no unit is of the indexes):
  - `in_scope` keeps a unit of a part asked for, or a song a songbook lists while the songbooks are (`listed_songs`:
    by any cut of an entry's "Artist - Title", `songbook.entry_keys`), which comes along to a side that lacks it and
    is never removed (a removal given, taken or asked, the library's, is left out);
  - with a file's `holds`, a unit the file lacks of a part it doesn't hold is never read as removed;
  - `change_of`: what each side did since the base (new, changed, gone); `names_of`: a song's names from its label.
- Both are written for the phone, `vectors/sync/kept.jsonl` and `scope.jsonl` (tests/test_conformance_sync_kept.py),
  which sync-core ports.
- **Ids**: each side's id is kv `sync:id`, made by schema 15 for every database, so caracole serve answers one
  without writing; `new_id` gives a copied database another.
- `Peer` is the other's caracole serve over HTTP, never a site.
- **Taking** (`apply_units`), under the lock: each unit read whole (`unit_document`) and refused when it is no longer
  as compared.
  - A song through its wanted.txt line and `sync_wanted` (the one way a song is added), then its record's
    `SONG_COLUMNS`, versions, kept files checked by SHA-256 (`song_file`), `CARRIED_KV`, lyrics files and
    `overrides.put_song_entries`.
  - A song gone there is removed as `caracole remove` does.
  - `songbook.put_songbook`, `overrides.put_alias`, `put_artist_url`, `put_block`.
  - Then the command renders the songs taken, the songbooks and the pages, after a backup (`before-sync`).
- **Giving** a side what it takes, two ways: `caracole peer sync --here` asks the other to pull (`POST /peer/pull`),
  and `--push` pushes (peer_push.py `Pusher`), as the phone, which serves nothing to the network, always does.
- **A push** (peer_push.py): `POST /peer/push/new` names the files its units keep by their SHA-256, `POST
  /peer/push/file` sends each one this side needs, `POST /peer/push` the document, checked against each unit's digest;
  then `caracole peer take DIR` takes its units from the staging folder as a pull takes a peer's, and deletes it.

#### peer_file.py

- A library in a `.caracole` file: `caracole peer export FILE` writes one, `caracole peer import SOURCE` syncs this
  library with one as if its caracole were here (commands/peer.py); the design is
  docs/superpowers/specs/2026-11-03-sync-redesign-design.md, the layout docs/superpowers/plans/2026-11-03-sync-redesign.md
  §3.3.
- **The file** (`FORMAT` 1): a zip of what a sync reads from the other side, its members in order:
  - `caracole.json`, the manifest (the caracole, schema and sync format that made it, the library's id and name,
    `made`, its parts, its counts, its indexes' sites);
  - `state.json` (`peer_sync.state_document` of its units), `bases.json` (every base it keeps), `units.jsonl` (each
    unit's document), `files/<sha256>` (each kept file once);
  - with the library, `pages.json` and `pages/<sha256>`, the pages made of its units (`offline_routes.library_pages`:
    `GET /api/offline`'s manifest cut to them), so a phone that takes a song opens its sheet: each page's bytes
    once, none for a page that is a kept file (held once, under `files/`), so a page is read from `pages/`, else
    `files/` (`FileSource.page`);
  - with the indexes, `indexes.sqlite` (`index_transfer.export`).
  - Its parts (`peer_sync.PARTS`): the library whole, the songbooks with the songs they list (`listed_songs`), the
    indexes. JSON deflated, blobs stored and copied by the MiB, every member dated `made`.
  - Its units read in one read transaction and its indexes in their own (`index_transfer.export`'s), state.json
    naming their newest read as indexes.sqlite holds it; each page read once, one no longer as its manifest says
    left out; taking no lock; written under a name of its own and renamed, never over a file.
  - A song whose kept file changed since caracole kept it, or is past `FILE_MAX`, is left out (`Made.left`, with
    why: `CHANGED`, `TOO_BIG`), its state still naming it, so the file never reads as having lost it.
  - `file_name`: download_names' cleaning of the library's name, then `-dd-mm-yy.caracole`.
- **Reading** (`read_file`, `SyncFile`): the manifest first, then every name in the layout, each once, each blob at
  most `FILE_MAX` (64 MiB), each JSON member `JSON_MAX`, the whole `IMPORT_MAX` (8 GiB); the indexes held only at this
  database's schema; an index export (`index_transfer.META`) a file of the indexes alone, with no id.
  - `check_whole` reads every member through before an import takes anything (its CRC, each blob its SHA-256, each
    document its state's digest, each kept file a song names and each page pages.json lists held): a file that can't
    be read whole is refused whole.
- **Refusals**, in the owner's words and the phone's alike, the whys caracole's own (`NOT_A_FILE`, `OTHER_FORMAT`,
  `OWN_EXPORT`, `OLDER`, `UNREADABLE`): `check_importable` refuses a library's own export and a file no newer than
  this side's last sync with its caracole (its base's latest time, the kept answers' included).
- **An import is a sync with the file**:
  - `compare_file`: this side's base for the file's caracole merged with the one the file keeps for this side, and the
    answers both remembered (`peer_sync.merged_kept`), within the parts the file holds (`in_scope(holds=)`);
  - `FileSource`, the take's `UnitSource`, so `apply_units` takes a file's units as a peer's: a unit of a part it holds
    that its state lacks is one its caracole hasn't got (a removal, against the base); one it names without a document,
    or of a part it doesn't hold, a `PeerError`, left, never a removal;
  - `record_import`: what the two agree on, stamped `made`, of the units the file speaks for alone (`speaks_for`: of a
    part it holds, or that it carries), every other unit's base as it was; then each "keep mine" (`kept_answers`)
    remembered (`peer_sync.record_kept`), a file taking nothing back; none for an import of the indexes alone, so the
    same file's library may still be imported after.
  - commands/peer.py's `peer import` takes a staged folder only once its file is whole (`peer_import.whole`), and
    exits 1 for a unit left or its indexes not merged; with `--progress` its report comes whatever it took.
- **peer_import.py**: an upload staged part by part, `state_dir/peer/import-<16 hex>/` (0700: `file.caracole` and
  `open.json`, 0600), one at a time, each part 8 MiB at most and the next one, 8 GiB in all; one untouched an hour is
  swept unless `held`; `staged_folder` checks the folder `peer import` is given, which it deletes once it is over.
- `peer sync --parts` and `peer import --parts`: the parts of a sync, a difference outside them neither taken, given
  nor said; a sync compares with the kept answers, so a unit kept here at an import is given there at the next one.
  - `peer sync --compared HASH` applies the comparison its hash names: with the kept answers (`peer diff`'s, and
    caracole serve's Sync tab's, sync_routes.py `_compared`), or without them, a comparison made before them
    (commands/peer.py `_Compared.named`).
- Written for the phone: `vectors/sync/file.jsonl`, `vectors/sync/files/*.caracole` (`full`, `songbooks`, `indexes`,
  `left`) and the fixtures `file_conflict` and `file_indexed` (tests/test_conformance_sync_file.py), which the Kotlin
  sync ports: an export, a file read and refused, a unit taken from one, an import.

#### service.py

- Whether this machine runs caracole as a service: its marker, `/etc/caracole/service` (`MARKER`, a few lines of TOML
  naming its `state_dir` and `library_dir`), which nix/module.nix and deploy.md's Ubuntu steps write, and
  `CARACOLE_SERVICE_FILE` another, which conftest.py points at no file for every test.
- `elsewhere`: the service when a caracole with no config named (no `--config`, no `CARACOLE_CONFIG`) would use
  another database than its. Then, unless the root `--home`:
  - `_common.load_cfg` refuses a command that builds an index (`builds_index=`, its words: run, index build and
    refresh, gtptabs, musescore, harptabs, gametabs and lacuerda `--index`) with status 2;
  - and any other says `warning` once before it writes (`_common.warn_elsewhere`, as it first takes the lock, or as
    add and serve write first).
- The standard library alone.

#### song_names.py

- The artist and the title a free text names, the one parser of it (`read_names`: its rules in order, cleaned first
  by `clean`, a video's channel by `clean_channel`; a known artist, a one-word artist of your library only once
  credible).
- Every path that turns text into a name uses it:
  - `/api/search`'s `names` (with the YouTube video suggested for the query), which the library page's request form,
    its Make the sheet and the lookup page's form by name fill in, each field until you type into it (no page splits
    a text itself: test_web_page_names.py);
  - a pasted video's guess (youtube_routes.py `pasted_video`);
  - `/request` and `/lookup` given one text, `q` (library_routes.py `named_form`);
  - `caracole add TEXT` and `caracole get TEXT` (`_common.read_song_text`; ARTIST TITLE, two arguments, are never
    read).

#### pdf_fonts.py

- The fonts every PDF is set in (`pdf_fonts`, `CARACOLE_PDF_FONTS`): a folder of `regular`, `bold`, `italic` and
  `mono` (`in_folder`).
- What `metrics` reads of each: the characters it has and their widths as ChordPro's PDF library counts them, which
  render.py's `pdf_font` (a letter the regular font lacks brings in the CJK font, for the words alone:
  `fonts_options`, `PDF_FONT_ELEMENTS`) and pdf_text.py's layout read.
- Without the folder, ChordPro's built-in fonts, as before.
- The standard library alone.

#### page_log.py

- The library page's line in the log, one a build (`PageBuild`: caracole serve's at `/`, library_routes.py, with the
  host; `todo.write_pages`'s `index.html`): its songs found, wanted, ignored and in review, its songbooks, the
  database's path, size and time, how long it took.
- A page with no songs, or a database that can't be opened or read: a warning that says what tells why, the page
  answered as ever:
  - the database before and after the build opened it, its owner, WAL, schema version and `songs` rows read straight
    from it, read-only;
  - the folders, the process's uid and gid.
- Information the journal keeps by default (logs.py `JOURNAL_INFO`): `journalctl -u caracole-web | grep 'library page'`
  (test_page_log.py).

#### library_name.py

- Which library a page shows (`LibraryName`): its name after caracole's in the header and the tab's title of
  index.html and every page caracole serve writes itself (top.py, pages.py, lookup_page.py, guitar_page.py:
  `WebApp.library_name`).
- On caracole serve's alone, a badge for a library that isn't the owner's usual one, with the "¿" in its colour
  (`scratch_badge`, once at start):
  - `caracole serve --label`, else `SCRATCH` for a config file, library folder or state folder in a temporary folder;
  - never the NixOS or Ubuntu service's /var/lib/caracole nor a library run by hand at home: test_library_name.py;
  - never on the written index.html, a viewer or a songbook's page.
- The standard library alone.

#### stamps.py

- How caracole stores a time (ISO 8601 UTC to the second, a naive time is UTC) and shows one (`shown`, in UTC;
  `local=True`, the Requests tab's, in the server's zone, named).
- A stored time missing or unreadable is older than any (`before`).
- The standard library alone.

#### keys.py

- A song's musical key and where it came from.
- A key named by its letter alone (UG's `A`, a sheet's `Key: A`, LaCuerda's `Tono: La`) is its parallel minor where
  the sheet's chords say so, one rule for every reader:
  - `theory.bare_key`: their key is that minor, or has its notes, or the minor's a capo lower, and neither major's, or
    is the relative minor of the letter's major, that minor (`C` over Am F C G Am, A minor), and no chord plays that
    tonic major, A or A7;
  - keys.py reads sheet.json's capo, page.py's `_song_key` a sheet's `{key}` by `theory.named_key` and trusts a
    keys.py source's key as given.
- Hotel California's `A`, capo 2, is A minor, sounding B minor (test_keys.py, test_viewer_theory.py).

#### sites.py

- The library page's Sites tab's data (`sites_data`, its `data["sites"]`):
  - each site's role, robots.txt in words with the closed paths worth naming (each in `http.ROBOTS_DISALLOW` but
    YouTube's), its terms note;
  - what its index holds, what your library keeps from it, last night's requests (kv `run:last`) and its status
    (`status_of`, which todo.py's health table reads too).
- Read with no request.

#### progressions.py

- Each song's progressions, read by render.py as it renders the song's sheet (its human one, else its auto one:
  `test_progressions.py::test_a_song_that_keeps_both_sheets_is_found_by_its_human_sheet_never_the_auto_one`) into
  kv `render:progressions:<song id>` (`record`; harmony.py's `progressions` and `progression_key`).
- So that these read one row a song, never a sheet:
  - index.html's data (each song's `progressions`, the page's `catalogue`);
  - `#prog=` (any rotation of it, made the key by library.js's `progKeyOf` as `progression_key` makes one);
  - `/api/search`'s `progression`;
  - and `caracole search --progression`.
- `read_progression`: numerals or a catalogue name typed.
- A named progression stands for every reading of its name (the pop progression in a major key and in its relative
  minor) and finds a section that plays it within it (a record's `contains`).

### Rules a change there keeps

The Invariants below are the others.

#### The pages caracole writes and serves

The pages caracole writes and serves are index.html, sheet.html, songbook.html and caracole serve's own.

- **They load nothing from the network.**
  - A Content-Security-Policy allows each inline script and stylesheet by the hash of the very text inlined
    (inline.py `sha256_source`), and a page's data is a JSON block with each `<` escaped (`inline.json_block`).
  - Each carries `page_icon.LINK` in its head, which its policy allows with `img-src data:` (test_page_icon.py).
  - Their scripts build every element with `createElement` and `textContent`, never `innerHTML`, and connect to
    nothing but caracole serve.
- **A page caracole writes into the library** is served only through `app.written_pages`, and only while it holds the
  bytes caracole recorded (`files.read_written_page`).
  - A new kind goes there, with its record and its policy.
  - A kept version's page, `version-<tab>.html`, is a sheet viewer by its name, and a harmonica tab's page,
    `harmonica-N.html`, a kind of its own by its name, served as a viewer is: `app.written_page`.
  - index.html itself, recorded by `library_page.write_library_page`, only at `/offline/index.html`, with no sandbox.
- **The one page that loads anything from caracole serve is the Guitar Pro page** (`web/guitar_routes.py`,
  `guitar_page.py`: a song's kept `guitar-N.*` file drawn and played by alphaTab, made per request, nothing written
  into the library).
  - Served in a sandbox, it loads alphaTab's one bundle (`web/alphatab.py`: the library, its font and its SoundFont,
    from `CARACOLE_ALPHATAB_DIR`) by `<script src integrity crossorigin>`, which its policy allows by the bundle's
    SHA-256, as it does the `@font-face` stylesheet alphaTab adds (`alphatab.font_face`, pinned by
    test_web_guitar_browser.py).
  - The bundle route answers any origin.
- **A suggested video's thumbnail**: the served library page shows the thumbnail of a YouTube video it suggests for a
  search from caracole serve (`GET /youtube/thumb/<id>.jpg`, youtube_routes.py: a JPEG of caracole's cache, checked by
  its bytes), which its policy allows with `img-src 'self'` alone; the file on disk has none.

##### Searching from the pages

- **Enter in a search box never spends a request on a guess**:
  - on the lookup page it acts only on `/api/search`'s `best` (or opens the leading artist's songs);
  - on the library page, whose served bar searches `/api/search` as you type (which asks no site), it only moves the
    focus to the first result;
  - the exceptions are LaCuerda's search, which Enter sends when its gate allows, and YouTube's suggestion, below.
- **YouTube's first video**: a served library page's search with no sheet on the sites
  (`youtube_search.sheet_on_screen`) asks YouTube for its first video once the query has settled (1.5 s; Enter at
  once), when `/api/search`'s `youtube` says `auto` (`youtube_search.gate`).
  - `POST /youtube/search`, a queued `caracole youtube --search --progress`, one yt-dlp run and the video's thumbnail.
  - Its row (library.js `ytRow`) fills the request form in, and sends nothing itself.
- **A YouTube video's link** typed or pasted into that box (library.js `youtubeVideo`, youtube_urls.py's shapes) is no
  query at all: no site, LaCuerda or YouTube search goes for it.
  - Its panel (`showLink`) reads `GET /api/youtube/video` (no request: what caracole knows of the video, its name read
    by song_names.py, the library's song of it).
  - For a video not read yet, it sends `POST /youtube/video` once (a queued `caracole youtube --video --progress`: one
    yt-dlp run of its metadata and its thumbnail).
  - Only its Add and make the sheet sends the request form (`POST /request` with the video): nothing is downloaded
    before.
- **LaCuerda's own search** is one of the two requests a search may bring.
  - Both pages send it by themselves (`POST /lacuerda/search`, a queued `caracole lacuerda --search --auto`) once the
    query has settled, the box unchanged for 1.5 s, when `/api/search`'s `lacuerda_search` says `auto`.
  - Enter sends it at once, by hand as the button does (no `--auto`), when it says `auto` or `button` (for the query's
    answer on the screen, else with the answer on its way, unless Escape leaves the results first; the settle's timer
    then sends nothing).
  - Never twice for a query in a page.
  - `button` (the hour's share of such searches spent) and `failed` (it failed within the hour, or three did) offer it
    by hand, a line under the results (rows.js `lacuerdaSearcher`).
  - Its rows come with the search asked again once the job is over, the focus Enter moved to a result staying on it,
    an artist's songs Enter opened on the lookup page staying open, and a search refused or failed has the button its
    words name: test_web_page_lacuerda_search.py.
  - One LaCuerda button on the screen at a time, worded Ask LaCuerda:
    - the search's own, "Ask LaCuerda for “…” (1 request)", only where the results offer no name's page;
    - where they do (`lacuerda_unlisted`), Ask LaCuerda's under the chevron of `nothingFound`'s line or in
      `notesLine` stands for both, sending the search while its gate says `auto` or `button` (the searcher's `ask`,
      which the pages' `does.ask` tries first) and reading the name's page else, the search's line then its words
      alone.
  - A test that drives the pages for something else passes `WebApp(searches_lacuerda=False)`, which caracole serve
    never does.
- **A row for one instrument says which**, a badge as a source has its mark, on both pages (rows.js
  `instrumentBadges`: Ukulele for UG's Ukulele Chords, Harmonica for harptabs.com's tabs, Score for MuseScore's,
  Guitar, Bass… for gametabs.net's, as its game pages name them; a song's card's `instruments`, library_page.py
  `instruments_of`).
  - No site's row is ever filtered by instrument: the Filter panel's Has something for (library.js `instOf`, a line's
    holds read the same way) keeps to your songs, in the list and among the results.
- **harptabs.com is searched as UG's index is** (`search.search_harptabs`, `/api/search`'s `harptabs_artists` and
  `harptabs`):
  - its artists, named from their page once read (harptabs_index.py);
  - and a song's tabs by an artist whose page caracole read, a song a line, the most viewed first under its "⋯"
    (rows.js `harpTabsOf`), each Get it a lookup that keeps that tab (`harptabs`, `caracole get --harptabs`,
    `[harptabs]`);
  - a tab no page read names is a title alone, as MuseScore's pages, apart.
  - An artist's group ends with "+ N more by … on harptabs.com" (`/api/artist?harptabs=`) or, for a page never read,
    the offer to read it (`POST /harptabs/artist`, `caracole harptabs --artist` queued, a job of no song's,
    `jobs.INDEX_READS`).
  - Its `looked` mark says how far its artist index has got ("harptabs.com: 1,204 of 10,428 artists", its name and
    tooltip).
- **gametabs.net's tracks of games** (`search.search_gametabs`, `/api/search`'s `gametabs`) are songs whose artist is
  their game:
  - a line in the game's group, their tabs under its "⋯" (rows.js `gameTabsOf`), each Get it a lookup that keeps that
    tab (`gametabs`, `caracole get --gametabs`, `[gametabs]`);
  - their instruments badges, none while it is turned off;
  - its `looked` mark says how far its game pages are read ("gametabs.net: 2 of 7 games", search_routes.py
    `_gametabs_looked`).

##### What a search says beside its results

It is rows.js's, shared by both pages:

- `countMarks`: under the box, in the bar kept at the top, what each site found:
  - your songs' count by the page's "¿", then a mark of `looked`'s and a count a site, its songs as the lines show
    them (`foundOn`; the library page's, library.js `foundNow`, with those "+ N more" listed since);
  - 0 quieter, a state in a colour and a glyph, never a colour alone, no control.
- `countsSaid`: the counts in words, the line's live region and the box's description, a screen reader's alone while
  the marks show: library.js `drawCounts`, lookup_page.py `showCounts`.
- `nothingFound`: a query that found nothing on the sites:
  - a line of the list under a quiet band, "Not on the sites", the query, Request where a song's Open is, the one
    Request then, and no Back to your songs, its marks the row under the box's;
  - under its chevron Ask LaCuerda and `unseen` folded.
- `notesLine`: those two under results.
- On the lookup page, `didYouMean` (`/api/search`'s `suggest`, a row each, a song's as the search's rows are, before
  any result).
- The library page draws a suggestion as an artist's band of its own, first, a song suggested a line in it
  (`indexLine`, or your own line), which leaves the miss's line in place (library.js `mergeSites`, `foundNothing`,
  `tailOf`); the line under the box names the first (`meantName`).

##### The library page's list

- On the library page, library.js's `mergeSites` puts your songs and every index's rows under one header an artist
  and one line a song, by the two parts of the identity key (the rows' `artist_key` and `title_key`, an artist's
  `group_key`, a song's `identity` in the page's data), each line rows.js's `indexLine`.
- A removed song's line asks for it again as the request form does.
- A "Did you mean" band's "Their 7 songs on UG ›" opens that artist's group from `/api/artist`, as "+ N more" does.
- A song of yours under its ⋯ (Fetch again; Use LaCuerda's sheet, `lacuerdaSheet` or the search's LaCuerda row of it)
  posts `/lookup` exactly as the lookup page's rows of it do (test_web_page_again.py).
- A hit's name there and on the lookup page presses its Get it (or Add again), disabled while that button is (rows.js
  `nameDoes`): never in place of a title that opens a sheet, and only a click or a key on it.
- **An artist's name**:
  - Served, an artist's name (a header's, a line's, a lookup row's) searches for them as typing it would (library.js
    `searchFor`, a step of the browser's history; lookup_page.py `searchArtist`), which asks no site, and the funnel
    beside it (rows.js `artistOnly`) shows your songs of theirs alone.
  - From a file the name is the funnel's (`artistFilter`).
  - A viewer's artist line (sheet.html, a version's page, a songbook's song: page.py `artist_line`) is a plain link to
    `index.html#by=<name>`, which library.js's `addressed` reads as the same press, served or from a file, then
    writes its own address in its place (Back is the sheet).
  - Your songs there keep to the Filter panel's filters and the artist's tag (`kept`), as the list's do.

##### Songs gone, and the page's tabs

- select.js knows only the songs the page was loaded with, less those gone since: a line offers Add to a songbook…
  for those alone.
- songs.id has no AUTOINCREMENT, so the next song added may get a removed song's id:
  - library.js knows a song gone by its removal done on the page, or by a view or a card of `/jobs.json` that names
    another song's identity under its id (the view's `identity`, `jobs_routes.view`);
  - removed elsewhere, its line says Removed, the song that has the id now is new to the page, and select.js and
    songbooks.js let it go (`caracole:gone`; songbooks.js's set lists show a lookup on a line of the same identity
    alone).
- The page's tabs are tabs.js's (body.html's tablist, `tab-NAME` buttons, `#tab=NAME`, `window.caracoleTabs`,
  "caracole:tab"): Library, Songbooks, Sites, then Requests, served alone, then Sync, the last, on caracole serve's
  page alone (the phone's has none); from 720 px Library and Songbooks on the left, Sites, Requests and Sync on the
  right (sync.css), a phone's one row unsplit (test_sync_sheet.py, test_requests_tab.py fits five on a phone).

##### The Sync tab and its sheet

- One flow on both devices, written once in library_assets/ (sync.js, sync-words.js, sync-sheet.html, sync-panel.html,
  sync.css; the plan: docs/superpowers/plans/2026-11-03-sync-redesign.md §3.4–3.7, §9), served byte for byte by
  caracole serve and the phone; `WebControls.sync` says which page has what:
  - `"tab"`, caracole serve's: the Sync tab, its three panels (Sync with a server: the address remembered, Test, the
    last sync, Sync; Export; Import a file) and the sheet;
  - `"sheet"`, the phone's (`ServerControls.sync`): the sheet alone, which the app's sync button opens; None, neither.
- The sheet (`<dialog id="sync-sheet">`, `data-view` what, conflict, going, done) opens from the tab's buttons and
  from the address: `#sheet=sync`, `#sheet=export`, `#sheet=import`, taken out once open; `#tab=sync` on a page with no
  Sync tab is `#sheet=sync` (outcome.py's Compare again).
- **What to sync**: it compares as it opens (`POST /sync/compare`, or `/sync/import/compare` for a file), then the three
  parts, Library, Songbooks and Site indexes, ticked, each with what waits in it, and above them ↓ to take, ↑ to give,
  ⚠ changed on both, counted in the parts ticked as `peer_sync.in_scope` counts them (a song a songbook lists comes
  along with Songbooks), and the chips Compared, Your choice and the parts. A part a file doesn't hold: "Not in this
  file".
- **A card for each conflict** in those parts: its two documents (`GET /api/sync/unit`, once a card) told apart by
  sync-words.js's `differ`, this device on the left; a button for each side, named for it (Phone and Computer, This
  computer and the server's name, File), and Same for the other N. No Skip, and nothing who changed what, or when.
- **Cancel queues nothing**, at any step before Sync goes; Escape is Cancel before it and Done after it. Sync posts the
  parts and each conflict's side in one field (`POST /sync/apply`); a 409 says the server's words and compares again,
  keeping the choices of each conflict as it was.
- **A sync on its way** (the page's, or the server's `jobs` as it loads: a reload, a second tab, the phone's
  notification) is followed quietly (`caracoleLibrary.track`), never started again; the sheet opened meanwhile shows
  it.
- **What it did**: "Synced with:" and the other side's name (the summary's one bold text), when, the two sides as
  icons, and a section a kind of change (`.sync-section[data-kind=taken|given|conflicts|songbooks|indexes]`), each a
  button that opens its rows, closed at first; drawn from the comparison and the choices the sheet sent, and the view's
  `outcome` and its `report` (§3.5), from the outcome alone for a sync the page didn't start. A file's has no given
  section.
- **Export**: `GET /api/sync/sizes`, the parts with their sizes, Site indexes unticked; `POST /sync/export`, then the
  file's link (`a[download]` to `api/sync/export?export=ID`), clicked once: the browser saves it, the phone's
  `DownloadListener` shares it. **Import a file**: `#sync-file` (`accept=".caracole,.sqlite"`, the phone's picker),
  sent in parts of 8 MiB, one at a time (`POST /sync/import/open`, `/sync/import/part`, `Blob.slice`), then the sheet as
  a sync with the file.
- Its words are sync-words.js's (`window.caracoleSyncWords`, frozen: texts alone, never an element): sides, changes,
  numbers grouped by hand, dates in the device's time (test_sync_words.py pins them in Madrid's zone).
- Every request relative, the reads with the form token in their header; no `innerHTML`
  (test_sync_sheet.py's `FakeSync` answers §3.4's shapes, which test_web_sync.py holds to the real routes).

##### The Songbooks tab

- The library page's Songbooks tab (`#tab=songbooks`) is songbooks.js's, drawn from the data's `songbooks`
  (songbook_section.py):
  - each songbook's set list, where it plays each song as `songbook.plays_in` says it;
  - each song's Guitar Pro mark, `guitar`: a file kept, else none;
  - and the setting's menus' names, the theory's, and the instruments.
- `/jobs.json` gives them again once a job is over (`jobs_routes.views`: a songbook's change, a lookup, which makes
  the songbooks its song is in again, or a removal; a LaCuerda artist's read changes none).
- library.js lends it `window.caracoleLibrary` (`track`, `showLine`, `focusOn`, and `fold`, the search's
  normalize.fold, for Add a song) and tells it every job's view (`caracole:job`) and the songbooks
  (`caracole:songbooks`).
- library.js posts the Select bar's songbook too, and gives the bar its ticks back when that make fails
  (`caracole:unmade`; the songbook stays on the tab until it is made, under its name or with those ticks under
  another, or its Forget it is pressed: songbooks.js `letGo`).
- A song's chip sends the capo with the key and the mode (`/songbook/set`, as `caracole songbook set` keeps it), and
  the instrument once it changes (on one with no capo, the key it sounds in, `at.sounds`, its capo menu off).
- Add a song looks a song the library hasn't got up first (`/songbook/add-song`: `search_routes.lookup_request`, then
  `caracole songbook add`, both or neither: `JobQueue.submit_all`).
- A change that ends seconds after its tap moves nothing on the screen: what it took away says so where it was until
  the next click or key (test_songbooks_tab.py).

#### index.html's assets (library_assets/)

- index.html's stylesheets, scripts and markup are the .css, .js and .html files of library_assets/, inlined byte for
  byte in the order of `library_page.STYLESHEETS`, `SCRIPTS` and `TEMPLATES`, where a new file is listed
  (test_library_assets.py).
- A song of yours closes to a line: its title, then a button for each thing to play from, none first (card.js
  `plays`, from `things`, what the card's tiles are made of too: each a link that opens it at once, its instrument's
  `glyph`, inline SVG made with `createElementNS`, the one address the page names, the marks of the sites its versions
  came from, how many; the lyrics none), Fetch now's download glyph where it has one (rows.js `fetchIcon`, a site's
  song's Get it too), its key and its chevron, one row on a phone and a laptop (test_library_plays.py). Its title and
  its chevron open it as a card (card.js `caracoleCard`, card.css):
  - a tile for each thing to play from, every one alike, each source's versions a chip whose drawer reads the page's
    data alone, never a request;
  - its UG versions not kept are counted (`versions.rest`, `sheet_versions.may_keep`), and Fetch them keeps them,
    `caracole versions --keep-more`, within a lookup's budget (test_library_card.py).

#### viewer/

- **What a page is made from** is `page.BUILD_FILES`, hashed into `page.build_version`: a module the viewer comes to
  import goes there (test_viewer_book.py checks).
- **Music theory**:
  - theory.py, harmony.py and `voicings.voicing_keys` keep their answers, so `Chord` and `Key` stay frozen with every
    field compared, and a list handed out is a copy (test_viewer_theory.py, test_viewer_harmony.py).
  - harmony.py's docstring holds the rules where music theory reads a chord two ways (B♭ in C is borrowed from C
    minor; D in C is V/V only going to G; C7 in C is V7/IV only going to an F that is no dominant seventh): change a
    rule there and in its test.
  - version.py names and shapes every chord as viewer.js does, so a PDF made in a version is what the viewer shows
    (test_viewer_version.py compares the two in Chromium).
  - viewer.js computes no music theory: a chord's numeral, its line, its notes, its solo scale and the key's scale are
    looked up in harmony_tables.py's tables, whose texts name notes as the page names them in the key shown
    (test_viewer_numerals.py checks them against harmony.py on every transposition).
  - Nor does harptab.js: a hole's note on any harp is harp.py's `hole_tables` (`hole_note`), its name
    `theory.spelling`'s, a group's effects the data's (`groups[i][2].fx`, which `drawGroup` draws again), how the tab
    was read Python's words (test_viewer_harp.py, test_viewer_harptab_page.py, test_viewer_harptab_notation.py).
- **strum.js**, inlined before viewer.js (and in a songbook), is the one place a page makes sound:
  - a plucked-string synthesis into AudioBuffers, no sample, worklet or request;
  - an AudioContext only on a tap (`navigator.userActivation`), suspended when the page is hidden or silent, resumed
    on the next tap.
  - `caracoleSound.play` is what a part that plays chords in sequence calls (its header documents it; the Harmony
    panel's ▶ does), never another synthesis (test_viewer_sound.py, test_viewer_panels.py).
  - It times a progression on the context's clock alone (a strum it comes to late moves the rest on, never two
    crammed together).
  - Every stop (■, another ▶ or strum, the panel closed, the page hidden or left) leaves no note to begin and no timer
    of it, even when the notes cut tell they ended late.
  - A sound asked while the context wakes plays only if nothing was asked after it, and a context woken for nothing
    sleeps again.
  - test_viewer_sound.py's `SCHEDULE` records each note and timer the page makes, and plays a slow device on demand
    (a resume held, `ended` events late).
- **Versions**: a sheet viewer's data `versions` (sheet_versions.as_data, with each entry's `this` and the one's
  provider, `sheet`) draws its switcher under the key line and the list it opens, a rail like the settings and never
  beside them (test_viewer_versions.py); the songbook has none.
- **The rail of necks** (from 1200 px) is the overlay, overlay.js's:
  - two tabs, Guitar first on a sheet and Harmonica first on a harmonica tab's page, the tab shown kept for that page
    alone;
  - viewer.js and harptab.js hand it what they look up, and Harmonica's notes, scales and harps are harp.py's tables,
    by steps above the tonic as the song sounds, a transposition moving every harp and a capo none
    (test_viewer_harp.py, test_viewer_overlay.py, test_viewer_harptab_browser.py).
- **Below 1200 px** the bar's neck (`necks-open`, after the key) slides it up as the phone's sheet (the page's
  `sheet()`, `data-sheet` half or full: its handle and ✕ for Hide), a dialog not modal and, in viewer.js, one of the
  layers docked on the bar (`--dock`):
  - each page opens with it closed, ▶ leaves it at half, the rail's Hide and Chord necks don't touch it;
  - and below 440 px (a phone, the owner's choice) the neck takes the guitar's place in the bar, the strip then ⋯'s
    All chord shapes (test_viewer_overlay_sheet.py, test_viewer_bar.py).
- **The rail is sized** by viewer.css's `--nk` (1.15: the owner's 15 % over the first 300 px), its width, padding,
  text and targets alike.
- **Settings kept for every page at once**:
  - **The necks**: whether the rail shows (`state.necks`) is the one setting kept for every page at once:
    - localStorage `caracole-viewer-necks`;
    - and `necks=0` in the address, which book.js's `carryScreen` takes on to a songbook's next address, for its
      sandbox with no storage, as a link to another of the song's pages does (a version's ‹ ›, a harmonica tab's and
      its ‹ Chord sheet, viewer.js `screenChoices`, the view's `carry`, harptab.js `backToSheet`);
    - with its Hide, the bar's button and the settings' row in step (test_viewer_necks.py).
  - **Pinyin**: so is the settings' Pinyin (`state.py`, off at first: localStorage `caracole-viewer-pinyin`, `py=1` in
    the address, which `carryScreen` takes on too), each Chinese character's reading over it, between its chord and
    it:
    - pinyin.py reads them at render time (pypinyin in context, a Traditional sheet in Simplified characters through
      normalize.py's table, its 著 as 着 but in a word Simplified writes with 著) into the data's `pinyin`, a reading
      per character of each `section.sec > p.l`;
    - viewer.js draws each as a `<ruby>`, its row of the line kept by every column, so a chord stays over its
      character's column, on or off, at 390 px too (test_viewer_pinyin.py).
  - **Chinese characters**: so are the settings' Chinese characters, Simplified or Traditional, a segmented control
    right above Pinyin, where Pinyin's row shows (`state.trad`, Simplified at first: localStorage
    `caracole-viewer-hanzi`, `trad=1` in the address, which `carryScreen` takes on too):
    - hanzi.py converts every text the sheet writes in its words (page.py `_written_texts`: its lines, the notes
      before the song and their peek, the sections' labels, its tabs) at render time with OpenCC, word by word (发 發
      or 髮), into the data's `hanzi`, `simplified` and `traditional` by the text;
    - a sheet is written in the script most of its own characters are, and shows as written in it: a Traditional
      sheet's Simplified is `tw2s`'s, a Simplified one's Traditional `s2tw`'s;
    - each a character for a character (one of another length made again a character at a time), which viewer.js cuts
      where the page cut the text, each reading over the character shown;
    - and the song's title, its artist's name and the page's title, each judged alone (`hanzi.names`), in a
      `song-names` block on a page whose sheet is Chinese (page.py `names_table`, `is_chinese`), each element that
      shows one marked with it as written (`zh_attr`, `data-zh`):
      - sheet.html's and a version's header;
      - a songbook's contents, pagers and headings (book.js draws them on its contents, viewer.js on a song);
      - a harmonica tab's page's heading (harptab.js reads the choice kept, no row);
      - the library page's lines and artist headers, by each card's `hanzi` (library_page.py, a song whose sheet's PDF
        record names its `script`: `render.chinese_songs`), library.js reading the choice kept
        (test_viewer_hanzi.py, test_library_page_hanzi.py).
  - **The Instrument**: so is the Instrument (`state.inst`, the guitar at first: localStorage
    `caracole-viewer-instrument`, `inst=` in the address while it is another, which `carryScreen` takes on too):
    - a songbook song's own version may name one, where it starts, and the songs after it on the player's (the one it
      came with, or the last chosen there by hand: book.js `player`), which never moves the song;
    - every instrument's shapes are instruments.py's, per root in the data's `voicings` (viewer.js looks them up);
    - one with no capo (the piano) names the chords as they sound (viewer.js `capoNow`, version.py `for_instrument`);
    - and the menu offers only what the page draws, an instrument of another kind once its script registers it
      (instruments.js documents that API);
    - test_viewer_instruments.py, test_viewer_instruments_page.py, test_viewer_sound.py.
  - **A numeral's tooltip**: so, last, is the view of a numeral's tooltip (the chord's notes on a twelve-note circle,
    or tiles over a keyboard: localStorage `caracole-viewer-tipview`, the circle with none):
    - it draws only what `tones` (with each note's pitch class) and `keyScale` give;
    - a chord's card opens it too, by its chord, with the chords' names alone (its Circle & keyboard, viewer.js
      `tipDraws`): test_viewer_numerals.py.

#### `commands/`

- One module per area, each with `register(app)`, which `cli.build_app` finds by itself (A4: add a module, never edit
  cli.py).
- `_common.py` holds what they share (config, the database, the lock, clients at either pace, pages, `fail`, `warn`,
  `song_named`): use it rather than another copy.
- A command's logic lives in a module outside commands/, imported inside the command's function (Heavy imports,
  below):
  - get.py is `caracole get`, one song looked up now:
    - the run's steps for that song alone, sheet first, at the lookup pace;
    - then its `songbooks` stage: the songbooks of songbooks.toml that list the song, `songbook.songbooks_listing`,
      made again by `render_songbooks(only=…)`, then `write_pages` again once one was, as `caracole songbook render`
      writes the pages after;
    - `--progress`, a JSON line per event, for caracole serve.
  - versions_cmd.py is `caracole versions`: a song's UG chords versions listed from sheet_versions.py with no request.
    - `--keep`: one tab page at the lookup pace, `ug.fetch.keep_version`, noted as yours in
      `sheet_versions.kept_by_you`.
    - `--keep-more`: the versions `sheet_versions.may_keep` gives, kept so in rank order through one client until the
      lookup's budget or the hour's is spent, those it can't keep noted (`note_unkeepable`) and never read again.
    - `--choose`: get's `--tab`.
    - `--clear`: `overrides.remove_pin` then get.
  - harmonica_cmd.py is `caracole harmonica`: how each of a song's harmonica tabs is read and the readings weighed,
    with no lock.
    - `--as` and `--symbol`, `--clear`: `overrides.add_harmonica`, then the song rendered again, under the lock,
      waiting as a lookup does.
  - lacuerda_search.py is `caracole lacuerda --search`: LaCuerda's own search, one query, one request at the lookup
    pace.
  - youtube_sheet.py is `caracole youtube --sheet`: a song's auto sheet from a YouTube video now, at the bulk pace: a
    command, never a lookup.
  - review.py, search.py, removal.py and songbook.py are `caracole review`, `search`, `remove` and `songbook`.

##### search.py

- search.py reads the local indexes alone, never a site:
  - UG's sitemap index and the artist pages caracole read (ug/artist_tabs.py);
  - gtptabs.com's, MuseScore's, LaCuerda's, harptabs.com's (its sitemap's and the artist pages read,
    harptabs_index.py) and gametabs.net's tables (its sitemaps' and the game pages read, gametabs_index.py);
  - the tombstones of removed songs (`search_removed`: never `lead` or `best`, shown with the `caracole add` line that
    brings one back, and in `/api/search`'s `removed`, which the library page shows with Add again);
  - the words of the UG index's artists' names (`ug_artists_fts` and its vocabulary `ug_artist_words`, schema 8, kept
    by triggers on `ug_index`, a key going with its last row):
    - an artist by a word of their name, `ArtistHit.part`, bounded by `WORD_LETTERS` and `WORD_ARTISTS` (LaCuerda's
      by `lacuerda_index.WORD_ARTISTS`), placed before a small namesake by `_with_parts`, leading by `_part_leads`
      and, against LaCuerda's, `lacuerda_leads`;
    - and `suggest_artists`, the artists spelled close to a query nothing matches well, UG's, LaCuerda's and
      harptabs.com's ranked together;
  - the words of every row of `ug_index` (`ug_index_fts`, schema 12, its content `ug_index`'s own, kept by triggers on
    `ug_index`) and of every key (`ug_key_words`, kept by a trigger on `ug_keys`, which only grows; read once a
    process, then only the words added since, `_Vocabulary`):
    - `suggest_titles`, the songs whose titles are spelled close to such a query, an artist's words beside them
      maybe, UG's, LaCuerda's and harptabs.com's, a song on several once, under its artist (`Suggestion.title`,
      `.hits`);
    - `suggestions` ranks both kinds together (a tab as `TAB_SONGS` of an artist's songs, `_cut`), `/api/search`'s
      `suggest` (a song's `title`, its row on each site, `song`, your song's row, `library`), the pages' "Did you
      mean".
- `gtptabs_songs` counts an artist's songs on gtptabs.com (an artist row's `gtptabs` in `/api/search`, the "Guitar
  Pro 12" of their header).
- `--progression` reads progressions.py's records alone, your songs only (`songs_with`).
- Its prefilter reads ug/key_search.py (`rows_like`: the keys' trigram index), which must find exactly what a `LIKE`
  scan of `ug_index` finds
  (`test_search.py::test_the_prefilter_finds_through_the_key_index_what_a_scan_of_every_row_finds`):
  - except that a pattern in more than `KEYS_PER_PATTERN` keys (a common word) brings in its shortest keys and those
    every pattern is in (`::test_a_common_word_brings_in_its_shortest_keys_and_those_every_word_is_in`).

#### `web/`

`caracole serve` (commands/serve.py).

##### Routes by area

- **guitar_routes.py** is the Guitar Pro page and alphaTab's bundle (alphatab.py):
  - the page: guitar_page.py, guitar.js, guitar.css: the tracks laid out, each muted on its own with
    `changeTrackMute`;
  - guitar.js `mend` patches alphaTab 1.8.4's canvas, which drew a part black when it began in the colour the last
    part ended in and cut the header's first line, so an alphaTab upgrade re-checks it: test_web_guitar_browser.py
    reads the header's pixels;
  - a song's kept Guitar Pro files are `inbox.guitar_files`, which library_page.py (`guitarPage`),
    songbook_section.py (a set list's `guitar`) and render.py (the viewer's `guitar`) read too.
- **youtube_routes.py** is `POST /youtube` (and the request form's YouTube video, `POST /request` with `youtube`): a
  song's auto sheet from the video pasted.
  - `caracole youtube --sheet --progress` queued under `jobs.YOUTUBE_SHEET` and the song's key (never joining its
    lookup), its stages its line's steps (status.py, outcome.py `YOUTUBE_STEPS`).
  - Offered only where `youtube_fetch.route_problem` says it can be made, the request form saying why not otherwise
    (library_page.py `server.youtube`, a card's `youtubeSheet`).
  - `POST /youtube/search`: a search's first video (`caracole youtube --search --progress`, `jobs.YOUTUBE_SEARCH`,
    among `INDEX_READS`), and `GET /youtube/thumb/`, its thumbnail.
  - `GET /api/youtube/video` and `POST /youtube/video`: a video pasted into the library page's search box
    (`caracole youtube --video --progress`).
- **offline_routes.py** is `GET /api/offline`, the manifest caracole's Android app copies the library by (read-only:
  each file the written index.html links to, as `WebApp._file` sends it now, its bytes' SHA-256 and its headers;
  test_web_offline.py).
- **peer_routes.py** is `GET /api/peer/state`, this library's units for another caracole to compare, with what it
  agreed on with the asker and the answers its imports of the asker's files kept (`kept`), the settings a phone
  takes (`settings`, politeness.py) and the form token (no wider than a
  page's, which any client that reaches the server reads, for a sync's `POST /peer/pull`); `GET /api/peer/unit` and `/api/peer/file` (peer_sync.py, read-only, as
  `/api/offline` is); and `POST /peer/pull`, `caracole peer pull` queued as any change (test_web_peer.py).
  - A push, the phone's (peer_push.py): `POST /peer/push/new`, `/peer/push/file` and `/peer/push`, `json` and `bytes`
    routes with the form token in their header, then `caracole peer take --progress DIR` queued.
  - `GET /api/peer/index[?sites=]`: this library's site indexes as `caracole index export` writes them, a SQLite file
    streamed from a temporary export (`cache_dir/peer/`), one at a time.
- **sync_routes.py** is the library page's Sync tab (library_assets/sync.js, sync-tab.html, sync-panel.html), the
  sync redesign's §3.4.1:
  - `GET /api/sync`: this caracole, its `device` (`computer`, the phone's `phone`), its songs and songbooks counted;
  - `POST /sync/test`: one `GET /api/peer/state` of the other caracole, nothing written, its counts, newest index read
    and the last sync in words (`tested_words`), refused as a comparison is;
  - `POST /sync/compare`: one `GET /api/peer/state`, then a `GET /api/peer/unit` for each songbook that differs and
    the other has; compared with the kept answers (`peer_sync.merged_kept`), as `peer sync` compares; each
    difference's `names`, `change`, `part` and `with` (`peer_sync.names_of`, `change_of`, `part_of`,
    `listed_songs` of both sides' songbooks), `songbooks` (both documents of each that differs), `indexes` (the sites
    newer on either side); kept 10 minutes (`Compared`, its `found` for a Sync's scope: one kept without it has every
    conflict it proposes chosen first);
  - `GET /api/sync/unit` (script only): a kept comparison's unit, both documents, the other's asked now (a comparison
    of another `source` than a peer's, a file's, refused);
  - `GET /api/sync/indexes`: each site's newest read and tabs (`index_transfer.newest`, `tab_counts`), which the
    phone, a client, reads;
  - `POST /sync/apply`: `parts` (`parts_of`; none sent, all three), a conflict of those parts (`peer_sync.in_scope`)
    with no side refused, then `caracole peer sync --push [--parts=…] --compared HASH --choose=…` queued, a job of
    kind `sync`.
  - The phone's server/routes/SyncRoutes.kt answers the six alike (SyncJson; vectors/web/sync_routes.jsonl, under
    UTC, which `WebReplay.syncRoutes` replays with the other side's `peer_units`), but its `device` `phone` and the
    computer's `kind` `computer`; `tested` is Settings' Test too, and `alone(address)` the unattended sync (the three
    parts, `Conflicts.LEAVE`, none queued while one with that address waits or runs).
- **sync_file_routes.py** is the sync's Export and Import a file: `GET /api/sync/sizes` (what an export would hold:
  the library's bytes, its songbooks, the indexes' bytes by SQLite's dbstat, `peer_file.indexes_size`, and their
  tabs), `POST /sync/export` (`peer_file.export_file` of the parts named into `cache_dir/peer/`, one at a time) and
  `GET /api/sync/export` (that file once, an attachment named `peer_file.file_name`, streamed); `POST
  /sync/import/open` and `/sync/import/part` (a file sent in parts, `json` and `bytes` routes with the form token in
  their header, staged by peer_import.py for `caracole peer import`), `POST /sync/import/compare` (the staged file
  read whole and compared as `caracole peer import` compares it, `sync_routes.comparison_answer`, kept as a
  `Compared` of source `import:<id>`, kind `file`, holding the file's parts; refused in peer_file.py's words and
  deleted) and `POST /sync/import/drop`.
  - `POST /sync/apply` on that comparison reads the staged file again (409 `STALE` once this library moved) and queues
    `caracole peer import --yes --progress [--parts=…] --compared HASH --choose=… -- FOLDER` under `import:<id>`, a
    job of kind `sync` (`status.PEER_KINDS`), "Sync with a file from <name>".
  - `caracole peer sync`'s index stage gives a site read more recently here through these routes
    (peer_import.py `Uploader`: open, parts, compare, apply of the indexes alone, then `peer_push.wait_for`), and
    takes one read more recently there (`peer_sync.Peer.index`, then `index_transfer.merge`), each counted for its
    report (`{"event": "report"}`, `jobs.Job.report`, `jobs_routes.peer_outcome`'s `report`).
  - The phone's SyncFileRoutes answers alike (vectors/web/sync_file_routes.jsonl, its routes' limits among them).

##### The router

- web/__init__.py names its parts, and web/app.py's docstring the modules of routes and the checks every request
  passes.
- app.py is the router and what every route shares (`Request`, `Response`, the answers' shapes, `WebApp.db()`,
  `.overrides()`, `.submit()`, `.queued()`).
- A route lives in its area's `*_routes.py`, as a `Route` in its `ROUTES`, which the router gathers from every such
  module, and a line of its docstring (test_web_app.py checks both): neither a new route nor a new module of them
  changes app.py.
- A route declares its body's kind and limit (`Route(..., body="form"|"json"|"bytes", limit=bytes)`): server.py asks
  `app.body_limit` before it reads a body (16 KiB for an unknown path); a `json` or `bytes` route needs the
  cross-origin check and the `X-Caracole-Form-Token` header, a form route its `csrf` field.
- A route refuses with `pages.Refused`, which `WebApp.handle` answers as the message page, or to the page's script as
  JSON: every refusal as data.

##### What keeps other sites out

- Every `/api/` read is refused to another site's fetch (`security.own_page_read`), and every write passes
  security.py's cross-origin check and carries the form token.
- **The one exception is Make this my version from Export PDF**, the owner's explicit choice:
  - `GET /export.pdf?…&mine=1` (export_routes.py), a plain link the sandboxed viewer follows, queues
    `caracole render --song --version --mine` with no form token and no cross-origin check.
  - A site could change a song's saved version with a link of its own; nothing is lost (Reset or another version
    undoes it), and the host-name check holds for it as for every request.
  - Widen it to nothing else without the owner (security.py,
    `test_web_export.py::test_mine_is_a_plain_link_with_no_token_but_the_host_check_still_holds`).
- There is no sign-in, by the owner's choice: no access token, no cookie, no secret; whoever can reach the server may
  use it, so it is for a network they trust (a LAN, a tailnet).
- What keeps other sites' pages out is the host-name check (DNS rebinding), the cross-origin check, the form token and
  `own_page_read`, with Referrer-Policy `same-origin` (header and every page's meta tag), so that a form a phone posts
  over plain HTTP carries its Origin (`test_web_server.py::test_a_phone_on_the_lan_cancels_a_request`).

##### Jobs and requests

- Beyond a wanted.txt line, every change runs as a `caracole` command queued in jobs.py (One caracole at a time,
  below).
- The one line a request shows is status.py's, read from the job's steps and the song's state, never from which
  commands ran: a step's label is that line while it runs ("Adding to the library…").
- The library page's Requests tab, its last, says that line its own way (outcome.py): `#tab=requests`,
  library_assets/requests.js, drawn from `/requests.json`: web/feed.py; no page of its own, every link and redirect to
  a request is `/#tab=requests&job=N`, status.py `details_href`.
- The library page's lines read only its steps (`outcome.progress`: a lookup's chips under its line while it runs,
  kept when it ends otherwise than Ready), never the rest: a finished one's outcome, a reason from its stages and its
  song's state (never made up: Not found says Ultimate Guitar has no chords only once the fetch asked it,
  `SongFacts.asked_ug`), and its next step.
- Cancel takes a request that hasn't started out of the queue (`JobQueue.cancel`, never one that runs, with the jobs
  `submit_all` queued `together` with it), keeping it in the history as over ("cancelled"), so a page that follows it
  hears it ended.
- Try again queues a finished one's steps again (a removal's asks its question again).
- **A sandboxed viewer reaches a form** only through a GET page of the server's own, whose form posts with the token:
  - `/versions` (versions_routes.py: Make this the one, Keep it and back to caracole's pick,
    `caracole versions --choose`, `--keep` and `--clear`, with `--progress`: the job's stages, a lookup's for
    `--choose` and `--clear`, which run `caracole get`), each a job under the song's key, which jobs.py's `_pick` joins
    as a lookup's `--tab`;
  - and `/harmonica` (harmonica_routes.py: a harmonica tab's readings, each pinned, or back to caracole's guess,
    `caracole harmonica --as` or `--clear`), linked from the tab's page by harptab.js when served, each job under
    `jobs.READING`, the song's change as Make this my version's `EXPORTING` is (status.py, jobs_routes.py).
- What a done job came to is read from the song's state and overrides.toml again (`caracole get` exits 0 on a block or
  a spent budget, the sheet unchanged).
- **Its Export PDF is no page**: `GET /export.pdf` (export_routes.py) renders the version in this process (render.py
  `version_pdf`, in a private folder under the cache) and answers it as an attachment, writing nothing into the
  library and recording nothing, with no lock and no queue.
  - With `mine=1` (the exception above) it queues Make this my version too, under the song's key (`jobs.EXPORTING`,
    `jobs.MINE`).
  - The viewer's Export PDF is a link to it, which its sandbox may download (`viewer_csp`: `allow-downloads`, nothing
    else added), the page staying where it is.
  - On a version whose music differs from the song's own (key, mode, capo, swaps, shapes: viewer.js `musicOf`; never
    a reading setting nor the instrument, the player's), a modal dialog asks first, Download and make it mine
    (`mine=1`), Just download or Cancel (test_viewer_panels.py, test_web_server.py's download in the real sandbox).

#### `autochords/`

- merge.py is pure Python and the only module `__init__.py` imports.
- sheet_lyrics.py, no model either (render.py imports it, in any package), puts lyrics that came after a sheet of none
  on it, `render_all` first thing, so every path to a page gives it them (`merge.with_plain_lyrics`, a version's
  `raw["lyrics"]` then "plain").
- btc.py (with the vendored btc_model.py and LICENSE-BTC) and beats.py need torch, librosa and beat_this; run.py runs
  them over the library.
- align.py, pure Python too, is run.py's: how far to shift timed lyrics LRCLIB timed for audio of another length, from
  the chords and beats alone:
  - `lyrics_offset`: candidate shifts scored, the best taken only by a clear margin, else the plain lyrics as before;
  - `shifted_lrc` moves line and word stamps alike, so word-timed lines keep their words;
  - the shift said on a line of the sheet's after the song's name, after the video's credit for audio from YouTube,
    and kept as `raw["lyrics_shift"]`.

#### `tests/`

- Named after what they cover (test_fetch.py is ug/fetch.py's), and `test_commands_*.py` for the CLI.
- conftest.py has the `conn` and `cfg` fixtures (every directory under `tmp_path`, in /dev/shm if it will do; `conn`
  copies a database migrated once per process), `add_song` and `subprocess_pythonpath`.
- tests/helpers/ holds what the tests share, a module each, whose docstring says what it gives and how
  (`from helpers.<module> import ...`); look there before writing another:
  - fake sites behind a real `PoliteClient`, a fake yt-dlp, synthetic files, a song rendered;
  - a PDF's text where it is drawn (pdf_pages.py), a wait for caracole's lock seen, Chromium (Browser tests, below).
- test_harness.py tests what makes the suite fast.
- fixtures/ holds samples of what each site answers (real response shapes, trimmed) and synthetic lyrics, sheets and
  files.

#### `nix/`

- **package.nix**: `buildPythonApplication`.
  - The wrapper puts `chordpro` on PATH and defaults `CARACOLE_CJK_FONT`, `CARACOLE_PDF_FONTS` and
    `CARACOLE_ALPHATAB_DIR`.
  - pdf-fonts.nix: nixpkgs' adwaita-fonts as four files, static Regular, Bold and Italic instances of Adwaita Sans
    made by pdf-fonts.py with fontTools, each glyph record padded to an even length, Adwaita Mono, and the OFL.
  - alphatab.nix: alphaTab's npm package, fixed-output, three files and their licences.
  - `withAutochords` adds the extra, the model files and `yt-dlp` on PATH.
- **autochords.nix**: the model files, fixed-output.
- **module.nix**: `services.caracole`: units, timer, `caracole-admin`.
  - No `credentials` option, as caracole reads no secret, so no unit and not `caracole-admin` loads one.
  - With auto-chords on, the nightly unit runs the auto-chords package, for its youtube step, and caracole-web and
    `caracole-admin` run it too, so their pages agree.
  - caracole-web then without MemoryDenyWriteExecute, as the auto-chords unit and `caracole-admin`, since a sheet from
    a YouTube video runs the models in it.
  - And `/etc/caracole/service`, the service's marker, service.py's.
- **module-check.nix**: `checks.module`, which loads the marker with service.py.

#### `docs/`

- usage.md: configuration, commands, the to-do page, overrides.toml, the library folder.
- deploy.md: a server: the NixOS module, or Ubuntu 24.04 without Nix, whose units and caracole-admin do what
  nix/module.nix's do, so a change to a unit there changes them too.
- install.md, and the design files above.
- web-search.md designs a search-API fallback for matching, not built.
- android_port.md plans caracole in Kotlin on the phone, to share, not built (its research:
  superpowers/specs/2026-11-02-android-native-port-feasibility.md).
- screenshots/: the README's pictures, of a demo library of public-domain songs, and make.py, which builds that
  library with no request and takes them again (its docstring says how): retake them when the pages they show change.
- superpowers/plans/2026-11-03-android-port-m1-m3.md: the Kotlin port's plan for milestones 1–3, its lanes and their
  interfaces; specs/2026-11-03-conformance-corpus.md and specs/2026-11-03-canonical-json.md, the contracts it rests
  on; spikes/2026-11-03-android/, the spikes' Kotlin, kept as `.kt.txt`.

#### android/

The Android app and caracole's rules in Kotlin (android/README.md; the plan above). A Gradle build of its own
(`android/flake.nix`: JDK 17 headless, Gradle, the SDK), packages under `io.github.danielhp95.caracole`:

- `:mirror`: the computer's pages on the phone, as `GET /api/offline` lists them (manifest, blobs, the sync), each
  page gated by its unit (`UnitGate`, `Mirror.pageFor`).
- `:core` (plain JVM): caracole's rules, each package the port of a Python module:
  - `db/`: db.py, its migrations from `caracole/schema/migrations.json` in the bundled SQLite (sqlite-bundled 3.50.1,
    FTS5), and the phone's own tables (`phone.sql`: `phone_overrides`, `phone_songbooks`);
  - `py/`: Python's Unicode and string semantics (unicodedata 16.0.0's tables, `re`'s classes); `keys/`:
    normalize.py and library.safe_name; `pinyin/`: pypinyin; `fuzz/`: rapidfuzz-cpp;
  - `json/`: canonical.py (canonical JSON, digests) and `json.dumps`'s kv text;
  - `search/`, `ug/`, `sites/`, `lacuerda/`: search.py, ug/key_search.py, ug/artist_tabs.py, lacuerda_index.py and
    the other sites' search; `names/`: song_names.py; `index/`: index_transfer.py's merge;
  - `library/`: songs.py, removal.py's rules, overrides.toml and songbooks.toml as tables; `sync/`: peer_sync.py,
    and the phone's sync engine and peer client.
  - testFixtures: `Corpus`, `Fixtures`, `TestDb`: how every Kotlin test reads the corpus and makes a database.
- `:server` (plain JVM): web/ on the phone, on Ktor CIO at 127.0.0.1 behind a launch secret: `http/` (app.py,
  security.py, inline.py, the message page), `files/`, `page/` (library_page.py's page, from library_assets/ copied
  byte for byte at build time), `jobs/` (jobs.py, jobs_routes.py), `routes/`, and `Assembly.kt`, the phone whole.
- `:app`: the Android app on its own server (`Caracole.kt`: one `Phone` a process, its server on
  `http://127.0.0.1:8738`, else a free port; the launch's secret a cookie, `caracole-launch`, set in the WebView, which
  loads that exact origin alone, `mirror.Links`); Settings' Import indexes (from the computer's `GET /api/peer/index`
  or a file, a foreground job); the Sync tab's sync in a foreground service (`SyncService`).
- `:viewer` (plain JVM, milestone 5): the page builder, viewer/ in Kotlin, with viewer/'s `.js`, `.css` and voicings
  copied byte for byte at build time (`copyViewerAssets`).
- `:e2e`: the end-to-end phases against a real caracole serve (`PhoneScenarioTest`, driven by
  tests/test_android_e2e.py, below).
- Milestones 1–3 are built (docs/android_port.md's status); lookups, the page builder, songbooks and PDFs on the phone
  are later rounds' (docs/superpowers/plans/2026-11-03-android-port-m4-m6.md, §5):
  - each route a module of its own, answering "… isn't on the phone yet." (409) until its lane lands;
    `server/routes/Stubs.kt` keeps YouTube's routes and `GET /lookup` alone, for good;
  - a declaration not built yet is `TODO("lane <id>")` in a file its lane owns, or, for a seam the phone already
    calls (`PhoneRender`, `SongbookPagesImpl`, `InboxRetry`), a neutral answer;
  - the lookup reaches `PhoneRender` and `SongbookPagesImpl` through their `seam`, `SongPages.NONE` and
    `SongbookPages.NONE` until their lanes make it the real one, so it calls no milestone's code before it lands.
- Building a `Phone` queues nothing: `Phone.start`, which the app calls once it has wired the queue's `onBusy`, queues
  the render job when the phone owes pages, and a take that owes some queues it after the sync, never inside it.
- The phone's own job kinds, which Python never queues (render, inbox, backup, restore), are one table with their
  words, `server/jobs/PhoneKinds.kt`, the phone's alone.
- `app/src/androidTest/` runs on a device or an emulator alone (the device step, below), under `CaracoleTestRunner`:
  `BundledSqliteTest`, `CorpusOnDeviceTest` (one test per corpus area, `core.testing.Replays`,
  `server.testing.ServerReplays` and `viewer.testing.ViewerReplays`; `-e area NAME[,NAME…]` picks some), `NoSitesTest`,
  `LocalServerTest`, `EndToEndTest`, `PinchTest`, `SyncTabTest` and `PhoneEndToEndTest`.

##### core.http, core.health, core.config

- `core.http` is http.py on the phone, held to Python by `vectors/http/` (tests/test_conformance_http.py), with what
  it reads as data in `data/caracole/http/` (`robots.json`, `ROBOTS_DISALLOW`; `http.json`, http.py's other
  constants; `idna.json`, the idna package's tables and each code point's bidi class):
  - `Urls`: httpx 0.28's URL (`HttpxUrl`: its normalizing and percent-encoding, `withParams` in place of the query, a
    host not ASCII through `Idna`, the idna package's encode and decode), `resolve` its next request's URL (urljoin as
    3.14 has it); a string httpx refuses an `UrlError` named as Python's exception;
  - `Robots.disallows`; `HttpRules` (`stale`, `retryAfter` with email.utils's dates, `isChallenge`, `readOnceMore`);
  - `PoliteClient` and `CachedAnswers`: the cache as http.py lays it out (`HttpCache` under `cacheRoot`, http.py's
    `cache_root`), httpx's request headers (a URL's user and password its basic auth, carried on a redirect as httpx
    carries it), the budget, the pause for given draws, redirects, blocks, LRCLIB's 503, the breaker, each case of
    tests/test_http.py a session of `client.jsonl`; `Response.json()` reads the bytes as `json.loads` does
    (`PyJson.loads(ByteArray)`: a byte that isn't the text's encoding an error, never `text`'s U+FFFD);
  - `RealTransport`: HttpURLConnection, no redirect followed, httpx's header set, a URL httpx won't send refused with
    its UnsupportedProtocol before any socket (ws and wss asked as http and https), gzip and deflate decoded as
    httpx's decoders decode them (zlib's gzip mode: `rules.jsonl`'s `decode`), errors named as httpx's, every host but
    loopback and 10.0.2.2 refused under `caracole.network=loopback` (the host as urlsplit, OkHttp and java.net.URL
    each read it); `RoutedTransport`, a test's sites through the fake sites server (`GET {base}/fetch?url=…`).
  - What the platform does otherwise than httpx, each the owner's to decide (RealTransportChecks pins the second):
    - a connection that fails as the answer is read: the JDK's HttpURLConnection sends the GET once more by itself,
      and Android's OkHttp may on another route, so a site can see two requests for one PoliteClient counted, paced
      and budgeted;
    - Android's OkHttp writes a path's `|` and `^` percent-encoded and its `\` as `/` (httpx sends all three as they
      are; the query is left alone);
    - Android's OkHttp ungzips a body of `Content-Encoding: gzip` itself, a body it can't read failing in its own
      words (DecodingError still);
    - http.py's httpx client keeps the cookies a site sets for the client's life (a run's, a lookup's) and sends them
      back; the phone keeps none.
- core.testing's `Scenarios.replay` replays a scenario record (§3 of the M4-6 plan: the fixture, the cache, the
  answers; the result or what it raised, the requests, the rows, kv, files, events and pauses compared), and
  `RealTransportChecks` the transport against a ServerSocket on loopback (RealTransportTest on the JVM,
  RealTransportOnDeviceTest on the device).
- core.health, health.py's: `Health` (kv `provider:<name>`, read as `get_state` reads it, `PyJson.loads`, strikes
  Python's int of any size by `PyInt`'s rule, a `last_error` that isn't text written back as it was, and written as
  `kv_set_json` writes it; 24 h × 2^(k−1) + 2 h after the k-th block in a row, a running cooldown kept, its strikes
  too; Python's exceptions as the KDoc maps them, which `HealthReplay` checks by class), `EventLog` (each request's
  `events` row, nothing else) and `Strptime` (`strptime("%Y-%m-%dT%H:%M:%SZ")`, CPython 3.14's `_strptime` regex by
  hand; the text written `Stamps.stamp`'s).
- core.lookup's `Pace`, _common.py's lookup pace (`lookup_requests_used`, `lookup_policy`, `requests_today`,
  `within_the_day`, `_last_request`, its kv read as `float()` reads a text, `PyFloat`, and
  `_pause_after_last_request`), and `Clients`, `make_client(..., interactive=True)` over `PoliteClient`: the pause
  after this side's last request drawn before the client's own, kv `http:last_request:<provider>` after each request
  sent, as `f"{time.time():.3f}"` writes it (`PyFormat.fixed`). No lock, ticket or handoff on the phone.
- core.config: `PhoneConfig.read`, kv `phone:settings` over config.json's defaults, each value as config.py would
  hold it or the default (`_delay`, `_count`, the `[match]` and `[rank]` ranges), a provider the phone doesn't know
  passed over, `per_day` the stricter of the two, never lifted (`take` is crossing-phone's).
- Every count, cooldown and record is this side's own. tests/test_conformance_health.py writes vectors/health/ and
  vectors/pace/ (`HealthReplay`, `PaceReplay`).

##### core.html

- The tokenizer (html-tokenizer), `core.html.internal.token`: `Preprocess` (UTF-8 with replacement, CRLF and CR to LF)
  and `Tokenizer`, the WHATWG tokenizer as lexbor 3.1.0 tokenizes for selectolax (its processing instructions, a null
  value for an attribute written with none, an empty doctype identifier a missing one in `CompatMode.of`), driven by
  the tree builder (`switchTo`, `contentFor`, `foreignContent`, asked only once the text before a `<!` came out of
  `next()`); docs/superpowers/specs/2026-11-03-html-parsing.md.
- Held by vectors/html/tokens*.jsonl (tests/test_conformance_html.py: what selectolax's tree shows lexbor's tokenizer
  decided of every fixture page, every page the fake sites build, an edge set and seeded tag soup; never a
  `<template>`'s contents, which selectolax's tree doesn't reach), which `HtmlReplay` reads through `TokensTree`, a
  small tree builder of its own (the active formatting elements reconstructed, the tokenizer's names compared as it
  gives them).
- The tree, nodes and selectors (html-tree), `core.html.internal.tree` and `.select`:
  - `TreeBuilder`, lexbor 3.1.0's tree builder ported insertion mode by insertion mode, with its tables of each tag's
    categories (`Tags`), and lexbor's own readings: `<select>` a scope with no "in select" mode, a token "in table"
    hands to "in body" never processed again, the implied end tags by name in any namespace, `sup` no breakout tag,
    text after a frameset's `</html>` read whole;
  - `Dom.kt`, lexbor's linked nodes, a template's contents a fragment no walk reaches;
  - `Selectors`, lexbor's matching of caracole's selectors: an element once for each selector of a list it matches,
    a node's search finding itself and its combinators reading the whole tree, the HTML attributes whose values match
    without case;
  - `HtmlDoc` and `HtmlNode` as selectolax's tree and nodes (`text`, `children`, `attributes`, `replaceWith`,
    `insertAfter`; a processing instruction's tag `-pi`, selectolax's None, and `iter()` `children(includeText =
    false)`: the spec's "For the site parsers");
  - `TreeBuilder`, `Tags` and `Selectors` ported from lexbor's C, with its copyright, under the vendored
    `core/html/internal/LICENSE-lexbor` (the Apache License 2.0 and lexbor's NOTICE).
- Held by vectors/html/tree*.jsonl and mutations.jsonl (tests/test_conformance_html.py's tree half: every page's
  shape, texts, the parsers' selectors and harptabs.py's `<pre>` read; the tree's edge set; selectors alone; 400 seeded
  tag-soup edits of the fixtures, by digest), which `HtmlTreeReplay` reads, the token vectors through core.html's tree
  too; the spec's one divergence, an input's duplicate `type` in a table, pinned in `TreeTest`.

##### Lookups on the phone

- core.lookup's `Lookup` is get.py's `_Lookup` (`internal/LookupRun.kt`), held to it by vectors/lookup/words, asking
  and after_the_sheet (tests/test_conformance_lookup.py, `LookupReplay`):
  - its stages in get.py's order and labels (`LookupWords.STAGES`), each reported as it starts and ends;
  - the song found, or added (`LibraryStore.add`, the phone's wanted.txt line), the pages picked recorded through
    `OverrideWriters`; a refusal (ignored, a tab of a kind caracole doesn't use, a pick that can't be recorded) the song
    stage failed and the rest skipped;
  - the sheet's order (a LaCuerda pick first, Ultimate Guitar's first pass, LaCuerda when no sheet is kept, asked once
    a lookup), its running detail `SHEET_FROM`; the lyrics put together as `_then` does; what follows the sheet within
    `SHEETS_SHARE`; `_owed`; the sheet readable as `_check_readable` says it; the closing `record_ok` and kv
    `lookup:songs`.
- Each site's stage is its lane's file of core/lookup/sites/, called with a `StageContext` whose `asking` is the
  envelope or `InteractiveAsk.afterTheSheet`. A stage words its site's answer as get.py's work does and every other
  `Asked` through `LookupWords.end`; `LookupWords.NOTHING_TO_ASK` is get.py's None: in the lyrics, Megalobiz's or
  AZLyrics' nothing to ask (`_then` says what the sites before said), anywhere else `done` with no words. A
  `SharedFolder` fails the stage in get.py's words; anything else is a bug, said in its stage and `LookupResult.bug`.
- `InteractiveAsk` is get.py's `_ask`: `_usable`'s words, a block recorded, an error counted, a spent budget worded
  the lookup's, the hour's or kept for sheets; one client a provider a lookup (`Clients.interactive`, at the lookup's
  run or a command's own, `lookup:lacuerda-search:`). A block alerts once (`Alerts.blocked`): on the phone a lookup
  alerts, where the computer's sends none, since the phone has no nightly run to tell.
- What a caracole with no ChordPro, no wanted.txt and no index.html says is get.py's too, recorded in the corpus and
  used by nothing on the computer: `ADDED` (the song stage), `NO_PDFS` (the pdf stage, skipped while `SongPages` is
  `NONE`), `PAGES_MADE` (once the phone makes the song's pages), `LIBRARY_PAGE` (the pages stage). The songbooks stage
  says "not on the phone yet" while `SongbookPages` is `NONE`.
- `Lookup.run` blocks: a runner calls it inside one `Database.writeBlocking` on the queue's worker, in autocommit, so
  each event, block and kv record commits as it happens; a write inside it throws; a queue that stops stops it at its
  next stage.
- server/lookups' runners: `GetRunner` (`caracole get`, its options checked as commands/get.py checks them,
  `LookupLines` and `LookupWords.totals` its output; a refusal or a bug exits 1), `VersionsRunner` (`--keep` and
  `--keep-more` to `VersionsCommands`; `--choose` as get `--tab` at the version's address; `--clear` as `removePin`,
  then get), `LaCuerdaRunner` (`--artist`, `--search` to `LaCuerdaCommands`) and `HarpTabsRunner` (`--artist`).
  - A refused lookup's step ends with `error: Nothing looked up: ….` and a bug's with `error: a bug in caracole: …`
    (the queue writes an `error:` line for every step that fails), where the computer's says the first plainly and
    logs the second; the stage the library page's line reads says the same on both.
- A lookup command (core/lookup/sites/'s `VersionsCommands`, `LaCuerdaCommands`, `HarpTabsCommands`) runs in
  `LookupJobs.context`, a `CommandContext` (the whole contract: LookupWords' section on a lookup command):
  - it says its Python's `--progress` events as `LookupWords.progressLine`s (`stageLine`, `songLine`; the queue's
    `JobCommands.progressLine` to the byte, a test checks), its job's events when it reports them
    (`JobCommands.reports`, as web/jobs.py's emit reads them), and its other lines; its last line is the one it
    returns;
  - it asks through `c.asking`, which records a block (and alerts once) and an error: a command never records
    either itself;
  - it records its own good run where its Python does: `Health.recordOk` after `Health.answeredAny` of its run
    (`LookupWords.lookupRunOf(c.now)`, `searchRunId` for LaCuerda's search), or after any request where versions_cmd.py
    counts them;
  - `versions --keep` and `--keep-more`: the runner begins the song stage and finds the song, the command says from
    `{"song": …}` on, and at its `pdf` and `pages` running events (versions_cmd.py's: a version kept, pdf then pages;
    any other outcome past its refusals, pages alone) the runner makes the song's pages and ends both stages in the
    phone's words (`NO_PDFS` while `SongPages` is `NONE`, `LIBRARY_PAGE`), the command's own ends of them unsaid
    (`LookupJobs.CommandLines`).

##### Site passes on the phone

- Ultimate Guitar's pages (ug-pages):
  - core.ug's `UgPage`, `UgArtist` and `UgLookup` are ug/page.py, ug/artist.py and ug/lookup.py: the js-store read
    through core.html and PyJson.loads, each field as Python's `float()`, `int()` and `str()` read it
    (internal/pages/`PyValues`: a list's or an object's text its repr), and half of a surrogate pair U+FFFD in every
    string, keys too (ug/page.py's `_whole`, the computer's fix too); `IndexTab` Python's, its label and its url.
  - `ArtistTabs.store`, `keepOnly`, `forget` and `backfill` (from the phone's own cache, `CachedAnswers`) write
    artist_tabs.py's rows; each page a store keeps tabs of is noted (`Reads.note`, site `ug`) for the next push to the
    computer, at the store's own time (`now`) or the read's if later, never moved back: a list stored from an older
    copy in the cache after a push is still sent.
  - A number past a Long (an id) or an Int (a version, a vote count, an artist page's number) is none where Python
    keeps it (the tab unusable, 0, the next number read), and a page nested deeper than `PyJson.MAX_DEPTH` a
    PageParseError: UG writes neither.
  - `UgPagesReplay` (area `ug-pages`) replays vectors/sites/ug_pages*.jsonl and ug_artist*.jsonl
    (tests/test_conformance_ug_pages.py).
- core.ug's `Rank`, `Coverage` and `SheetVersions`: rank.py, coverage.py and sheet_versions.py, Python's numbers and
  lists for the same inputs (versions.py's `complete` and `replaces_sheet` are `Rank`'s).
  - A score is Python's float arithmetic (`prior_mean` the builtin sum's, `Py.fsum`), a ranking a stable sort on
    Python's keys: a float as `==` and `<` compare it, ties on `(version, len(tab_id), tab_id)` in code points.
  - Coverage: its regexes through PyRegex, `str.splitlines` and `split()`, lengths in code points, `partial_ratio`
    as `Fuzz.partialRatioAlignment`, Chinese as pinyin.
  - `SheetVersions` reads the tables with sheet_versions.py's own SQL (`inLibraryOf` in four queries), a kv list's
    items as Python's `str()` makes them, `asData` in Python's member order (a record's `dumps`, json.dumps'
    text, checks it byte for byte).
  - tests/test_conformance_rank.py writes vectors/sites/ug_rank.jsonl, ug_coverage*.jsonl (every fixture sheet
    against every fixture lyrics) and ug_sheet_versions*.jsonl (over a fixture library): `RankReplay`. They are
    a share of the `sites` area every site lane writes: a record only where it can answer otherwise than another
    (a policy by the fields that differ from `RankPolicy()`'s, which its first record gives).
- UG's lookup path for a matched song (ug-fetch-sheet): core.ug's `UgFetch` (`processSong`, `keepVersion`,
  `checkedSince`, `needsArtistPage`), ug/fetch.py's for one song, never its bulk work (no fetch_songs,
  rescore_kept_sheets or handoffs), in internal/fetch/:
  - `Pages`: `_read_page` and its one more fetch past the cache, kv `ug:unreadable:<tab>` (7 days, doubling, 90 at
    most), RobotsClosed neither gone nor unreadable, a 404 a version gone, each page's versions recorded
    (`_check_links`), its artist's page learned (kv `ug:artist_url:`);
  - `Slots`: the groups rated from the lowest unrated id (a slug naming no part first), the pins and the pinned URL,
    the sheet slot (another site's sheet replaced only as `replaces_sheet` says, LaCuerda's you picked never but by a
    pin, a complete one retiring the auto sheet) and the tab slot; `Beside`: the versions kept beside the sheet, beside
    a pin from the cache alone, yours, one text under one name (kv `sheet_versions:same:`);
  - `SongFetch`: `_finish` (status, `ug_dirty`, `ug_checked_at`, kv `ug:blocked:`), `_drop_undone`, `keep_version`'s
    answers; info.json is the viewer's (M5): the phone writes none, and a song's `updated_at` is the fetch's time;
  - `ArtistPages`: the artist-page route (ug-fetch-artist's, below).
- The lookup's UG stages (core/lookup/sites/Ug.kt): `UgSheetStage`, the first pass (one versions page, one sheet
  scored, nothing kept beside it, no tab: "tab N from Ultimate Guitar"), `UgStage` the rest ("sheet N · tab M · kept
  beside it: …"), `_ug_ready`'s skips (none for a song the index can't settle whose artist's page is known,
  `ArtistRoute.artistIsKnown`), and what asking came to in `LookupWords.end`'s words; the envelope (InteractiveAsk)
  marks the song owed a fetch (`_owed`), and the frame (LookupRun) asks the ug stage within `after_the_sheet`, and
  LaCuerda after a sheet stage that kept none.
- tests/test_conformance_ug_fetch.py writes vectors/lookup/ug_sheet.jsonl and ug_keep.jsonl, scenario records, and
  ug_sheet_stages.jsonl, get.py's words for the two stages and `_ug_ready`'s answers (`UgFetchReplay`, area
  `ug-fetch`).
- UG's artist pages (ug-fetch-artist): a song the index can't place looked up on its artist's UG page, ug/fetch.py's
  route, in internal/fetch/`ArtistPages` (`processSong` calls it, as `process_song` calls `_artist_page_route`):
  - the page's address: `[artist_url]`, a tab page there read once for the page it links to (kv
    `ug:pasted_tab:<tab>`, or what is wrong with it: `ArtistRoute.pastedPageProblem`), a learned one (kv
    `ug:artist_url:<artist key>`), else `LEARN_TRIES` slugged tabs of the artist read for it;
  - the chords list, then those its filter bar offers (the unfiltered page when a list answers 404, a 404 there a
    page gone), `artistPagesPerKind` pages a kind, 30 days from the cache (a stale copy no answer: BudgetExhausted
    once the budget is spent), every page stored for searches (`ArtistTabs.store`, `Reads.note`d for the computer);
    a block, an error or a page that won't parse raised, never a miss (no `ug:artist_page_checked:`);
  - titles as `_best_title` takes them (`TITLE_MATCH` 90, `TITLE_MARGIN` 8), a `[reject]`ed song out first, the
    match written with step `artist_page`; the lists of a song matched there, or of one whose index tabs hold no
    chords, read as its versions; `ArtistRoute.artistIsKnown` what the UG stages ask first.
- `versions --keep` and `--keep-more` (ug-fetch-artist): core/lookup/sites/`VersionsCommands`, versions_cmd.py's
  `keep` and `keep_more` through a `CommandContext` and the song's `LibraryStore` (the `[block]`, gone and "the
  sheet already" checks, `KeepRefused` its `fail`, exit 1; `keepVersion`; `_stopped`'s words; `Health.recordOk` only
  after a request; keep-more in `SheetVersions.mayKeep`'s rank order through one client, `noteUnkeepable`, "kept N of
  M"), saying its `pdf` and `pages` stages where versions_cmd.py makes the song's pages, its last line returned, which
  lane lookup's VersionsRunner says after them.
- tests/test_conformance_ug_fetch.py writes vectors/lookup/ug_artist.jsonl and commands_versions.jsonl too (the
  same `UgFetchReplay`).
- core.match's `Matcher`: match.py for a lookup's song (`matchAll`, `candidatesOf`; the ladder, `Ladder`; the index
  as it reads it, `IndexView`), each answer Python's for the same index and overrides.
  - Its scores are core.fuzz's: `ratio` and `extract`, `osaDistance` and `extractDistance` (rapidfuzz's OSA, the typo
    route's: the nearest first, then by index), and `tokenSetRatio` (music.py's names); each rounded as
    `round(score, 1)` (`Py.round`), each list sorted in code points, a range's bound U+10FFFF as one code point.
  - `matchAll` writes as `_save` does, through `Versions` (`updateSong`, `markStale`, `refreshStatus`), the candidates
    as json.dumps' text; an index not complete (no `ug:index:built_at`) records no miss and undoes nothing the ladder
    found.
  - `IndexView` loads the artist keys, the title keys and the catch-alls' songs whole only once a step reaches them: a
    song steps 1 and 2 settle loads none (MatcherTest).
  - A stored candidate may name no step (`MatchCandidate.step` null, as match._stored's `c.get("step")`):
    `candidatesOf` gives those that name a UG song.
  - The lookup's match stage (core/lookup/sites/Match.kt, `MatchStage`): `ArtistTabs.backfill` from the lookup's
    cache alone (`StageContext.cacheDir`, which the frame gives every stage whatever asking it passes; its keys made
    current first), then `matchAll` over the song, get.py's words for what it came to.
  - tests/test_conformance_match.py writes vectors/match/ (test_match.py's cases harvested, a few views over keys past
    U+FFFF, a seeded library, the stage), tests/test_conformance_fuzz.py vectors/fuzz/osa*.jsonl and
    token_set.jsonl: `MatchReplay`.
  - MatcherBench (`gradle bench`, 1.5 M rows, its own heap) times one song and its heap; a song that reaches
    title_only loads every title key, about 100 MiB on the JVM, the phone's to measure.
- core.lyrics' `Lrclib`, `Megalobiz` and `AzLyrics`: lyrics.py, megalobiz*.py and azlyrics*.py for a lookup's song,
  and their stages, get.py's `_lrclib`, `_megalobiz` and `_azlyrics` (core/lookup/sites/, its words; lane lookup's
  frame puts them together as `_then` does).
  - An answer read as json.loads reads it (PyJson: a number an int or a float as Python's, `lyrics.internal.PyValues`
    for `isinstance` and `repr`), a length `round()`ed half to even, Megalobiz's stamps as
    `f'{ms % 60000 / 1000:05.2f}'` writes them (PyFormat), AZLyrics' pages by Python's regexes over the text and
    `html.unescape` (PyHtml).
  - LRC's stamps are read in one place, library/internal/LyricsFiles.kt (any decimal digits, a minute as long as
    `int()` reads, as Python's `\d`, `int()` and `float()`, their errors past 4300 digits or a float's range too), for
    `Lyrics.fromRecord` and the files written: `lyrics.txt`,
    `lyrics.lrc` and `lyrics_json` byte for byte.
  - kv `lyrics:failed:`, `megalobiz:checked:` and `azlyrics:checked:` as Python's: an error never a miss, a song
    LRCLIB missed back to pending; Megalobiz's per-day limit is the lookup's client's (`Pace.withinTheDay`); info.json,
    the link back's, is milestone 5's.
  - tests/test_conformance_lyrics.py writes vectors/sites/{lrclib,megalobiz,azlyrics}.jsonl (the parsers and pickers
    over tests/fixtures/) and vectors/lookup/ the same (each pass of one song as a scenario record): `LyricsReplay`.
- LaCuerda's pages and search (lacuerda-pages), core.lacuerda:
  - `LaCuerdaPages`, lacuerda.py's pages read as the computer reads them (core.html's tree, PyRegex for its regexes
    over the raw page, Python's str and int on code points): an artist page's songs, their popularity and the
    artist's name, the "aqui llega:" body, a version's sheet in UG markup, an answer of its search (every page cut
    short a `LaCuerdaParseError`), `parseLcd`, `bestAcordesVersion`, `matchTitle`, `looksSpanish`, `searchWords` and
    `searchUrl`; the listings' pages are the nightly run's alone, never read on the phone;
  - `LaCuerda`'s store writers, lacuerda_index.py's `store_songs`, `store_artist_page`, `store_search` and
    `_replace`, each noting the page it wrote (`Reads.note`: "<slug>/", or `busca.php` for an answer with rows, at
    the store's `at`), which index-push sends;
  - `LaCuerdaSearch`, lacuerda_search.py: `queryKey`, `asked`, `answersWell`, `answered`, the failures
    (`recordFailure`, `forgetFailure`, `failed`, `Failure.said`), `searchesUsed`, `gate` (and its /api/search shape,
    `SearchGate.of`, of `answersWell` over the route's own kept hits) and `search`: its one request, the answer
    stored and its kv in one savepoint, the count it states Python's int of any size;
  - tests/test_conformance_lacuerda_lookups.py writes vectors/sites/lacuerda_pages.jsonl and lacuerda_store.jsonl,
    vectors/lookup/lacuerda_gate.jsonl and lacuerda_search.jsonl (`LaCuerdaReplay`, area `lacuerda`).
- LaCuerda's sheets (lacuerda-sheets):
  - `LaCuerdaSheets`, lacuerda_fetch.py for a lookup's songs (`only`): `_to_try` and `mayAsk`, the artist's slugs in
    `_artist_songs`' order (a slug given first, the listings' `artistSlugs`, then `artistSlugCandidates`; a 404 or
    "aqui llega:" moving on), each page cached 30 days (a stale copy no answer once the budget is spent), your pick's
    page, `_record` and `_keep` (`sheet.json` as `json.dumps(indent=2)` and a newline, then `sheet.txt`; no
    savepoint, as Python's), `lacuerda_checked_at`, a shared folder waiting; and `readArtistPage` (its `first`, which
    Python's lacks, asked in place of the name written as a slug). The songs re-keyed first, as `list_songs` does.
    Each page stored is noted for the next push. Python's nightly parts are left out: the popular artists' pages, the
    listings pass, the handoffs, info.json;
  - core.lookup.sites' `LaCuerdaPickStage` and `LaCuerdaStage`: get.py's `lacuerda()` through the stage's asking, its
    words for what the pass came to, and `LookupWords.end`'s for what asking came to;
  - `LaCuerdaCommands`, commands/lyrics.py's `lacuerda --artist` and `--search` (with `progress`, its default, the
    search's `--progress` lines said; the last returned), the cooldown and the gate checked as Python checks them,
    the block and the error recorded by the asking, a good run by `LookupWords.lookupRunOf`'s run, which the runner's
    asking logs under; the search re-keys the songs before `answered`, as `search_library`'s `list_songs` does, and
    stores no cached page first (`backfill_cached`: the phone stores each page as it reads it);
  - tests/test_conformance_lacuerda_lookups.py writes vectors/lookup/lacuerda_sheets.jsonl (the pass, an artist's
    page, and get.py's stage over the record's client alone) and commands_lacuerda.jsonl (through InteractiveAsk, as
    LaCuerdaRunner asks): `LaCuerdaReplay.sheets` and `commands`, each record's `noted` the pages the phone notes.
- harptabs.com (harptabs): core.sites' `HarpTabsFetch` and `HarpTabsPages`, harptabs.py, harptabs_fetch.py for a
  lookup's song and harptabs_index.py's `read_artist`, over the index the computer's sync brings (the phone reads no
  sitemap and makes no artist pass):
  - its pages read as selectolax reads them (core.html), their JSON-LD by `PyJson.loads` (a value's `str()` as
    Python's), their counts by `PyFloat` and `PyInt`, whole as Python's int: one past SQLite's integers is its
    OverflowError only where it is written (`HarpTabsPages.sqliteInteger`), never on a page passed over;
  - a song's candidates, its artist by name forms, the most viewed kept as `harmonica-N.txt` (`Numbering`, `Kept`,
    `Versions`; no info.json, milestone 5's), kv `harptabs:checked:` and `:pick`;
  - an artist page stored (`store_artist_page`, `store_gone`), each noted for the next push (`Reads.note`, site
    `harptabs`, the page's path);
  - the lookup's harptabs stage (`HarpTabsStage`, the rest of what asking came to `LookupWords.end`'s) and
    `caracole harptabs --artist` (`HarpTabsCommands.artist`, its one line, commands/lyrics.py's words), through
    StageContext's and CommandContext's asking;
  - tests/test_conformance_harptabs.py writes vectors/sites/harptabs.jsonl, vectors/lookup/harptabs.jsonl,
    harptabs_artist.jsonl and commands_harptabs.jsonl: `HarpTabsReplay` (asking through `InteractiveAsk` over each
    record's client, each request with caracole's own user agent, the pages noted beside Python's rows).
- gametabs.net (gametabs): core.sites' `GameTabsPages` (gametabs.py's tab and game pages read through core.html,
  `parseTabPage` and `parseGamePage`) and `GameTabsFetch` (gametabs_fetch.py for a lookup's song alone, no sitemap
  or game page read), and the lookup's gametabs stage (core/lookup/sites/GameTabs.kt, get.py's words, the envelope's
  `LookupWords.end`'s).
  - A `data-tab` value as gametabs.py reads it: Python's truth and `str()` of each JSON value, its ints unbounded
    (`BigInteger`), each as the float Python makes of it (the nearest, a tie to the even one, whatever the platform's
    `BigInteger.toDouble` rounds), one too large for a float an OverflowError as `math.isfinite` raises; a version's
    votes are the views as SQLite holds them (64 bits, sqlite3's OverflowError past them).
  - Candidates by game (its slug's key, its page's name) or composer, `CANDIDATES` (4) at most, the most viewed
    first, then by path in code points; the most viewed page that fits kept as `gametab-N.txt`, a pick
    (`[gametabs]`) read alone; kv `gametabs:checked:<id>` and `:pick`, of the lookup's song alone; the game pages'
    title keys made again first (`SiteKeys.gametabsEnsureCurrentKeys`, kv `gametabs:games:keys`), as the computer's
    pass does.
  - tests/test_conformance_gametabs.py writes vectors/sites/gametabs.jsonl (the parsers over tests/fixtures/gametabs,
    helpers/gametabs_site.py's pages and an edge set; `title_key`, `game_forms`, `song_forms`, `fits`) and
    vectors/lookup/gametabs.jsonl (the pass's scenarios, each request with caracole's user agent): `GameTabsReplay`.
- gtptabs.com and MuseScore (tab-files), core.sites' `GtpTabsPages`, `GtpTabsFetch` and `MuseScorePages`: gtptabs.py's,
  gtptabs_fetch.py's and musescore.py's rules for a lookup's song, every regex PyRegex's.
  - `GtpTabsPages.parseArtistPage`: an artist page through core.html's tree, its link text collapsed as `split()`
    does, the size and upload-number regexes Python's.
  - `GtpTabsFetch.gtptabsFiles`: the pass with `refresh_index=False` (the computer's index, no sitemap read), its
    candidates (internal `GtpPass`: by the artist keys, "Last, First" and without hyphens; sorted by (-stars,
    version, id)), artist pages cached 30 days (a stale copy BudgetExhausted), three downloads at most past the
    cache, the file kept as the lowest free `guitar-N` (Kept, Versions, Numbering), kv `gtptabs:checked:` and
    `gtptabs:unusable:`, `PagesNotFiles`; never a replace or a delete; no info.json (M5's).
  - `sniff` reads a Guitar Pro 7 zip's central directory as CPython's zipfile does (internal `ZipNames`: the end
    records, zip64's, cp437 and UTF-8 names, the Unicode Path field), never java.util.zip's stream; inbox-share
    reuses it.
  - `titlePage`, the Requests tab's; `MuseScorePages.songPages`, links from the index alone, with no client.
  - The lookup's gtptabs stage (core/lookup/sites/GtpTabs.kt, `GtpTabsStage`) in get.py's words, the envelope's
    `LookupWords.end`.
  - tests/test_conformance_tab_files.py writes vectors/sites/gtptabs*.jsonl, musescore.jsonl and
    lookup/gtptabs.jsonl (its stage records asked through InteractiveAsk with the records' clients):
    `TabFilesReplay`, area `tab-files`.

##### The Requests tab on the phone

- **Its lines** (server/jobs: `Status`, `Outcomes`, `SongFacts`, `JobViews`, `JobsRoutes`): every job's line, chips
  and outcome as status.py, outcome.py and jobs_routes.view say them, for every kind caracole serve queues and the
  phone's own:
  - a job of commands is read as caracole serve's; one of the phone's own (a run, no command) as caracole serve's of
    the same request (`Shape`): an add's or a removal's stage its one command, a staged one's stages under its title;
  - with no to-do page: status.job_line's `todo=None`, the same words with no link;
  - its song as the library has it now (`SongFacts.songOf`, jobs_routes.song_of: the sheet its card opens, review,
    the picker, ignored and a LaCuerda pick by the phone's overrides, `checked_now` by `ug_checked_at` and the
    artist page's check, read as strptime reads them, `elsewhere` from the local indexes and `Health.isCooling`);
  - what a job over came to worked out once, the queue's one answer (`SongFacts.ended(queue)`, jobs_routes'
    `_ended`), which every route that says a job's line asks, /jobs.json's and the Requests tab's alike;
  - PhoneKinds' kinds (render, inbox, backup, restore) say §5.3's table's words, the ones their run filled in as
    their stage's detail (`context.stage(<its stage>, state, PhoneKinds.fill(…))`, done, running or failed; inbox's
    wait a done detail in `otherwise`'s words: `JobViewsTest.thePhonesOwnKindsSayTheirTablesWordsAsTheirRunFilledThemIn`),
    and the phone's index import "Merging the computer's index…";
  - vectors/web/job_views.jsonl (the phone's own jobs), job_views_kinds.jsonl (every kind of commands in every state,
    every stage a line words running, a sync's, a take's and a merge's commands), outcome.jsonl (the same and each
    site's waits and errors, then the tables of words whole, its `tables` record) and job_views_song_of.jsonl
    (song_of over a small library a record, its fixture), written by tests/test_conformance_sync_routes.py and
    test_conformance_web.py (`JobViewsReplay`, area `job-views`).
- **Its tab** (`server/jobs/Feed.kt`, `server/routes/RequestsRoutes.kt`, `server/page/LibraryPage.kt`): the library
  page's Requests tab as caracole serve's (feed.py, jobs_routes.py, library_page.py):
  - the tab and its panel are library_page's `_requests_tab` and `_requests_panel`, exported as they are into
    data/caracole/page/requests.json (`RequestsTab`), the tab counting `ServerControls.active`;
  - `GET /requests.json` (the page's script alone, `?open=N,M`) is `Feed.feed` over the queue's snapshot: each job's
    line `JobViews.line` (its song's facts through `SongFacts.ended`, the cache /jobs.json shares, its songbook's page
    `JobsRoutes.songbookPage`), each one over `Outcomes.outcome`, the running one's `Outcomes.steps`, and the songs
    that wait for a pick (review_routes.picks_waiting: a review with candidates, `SongFacts.hasCandidates`, or a song
    the index didn't match, `search`), read apart from the lines as caracole serve reads them;
  - a database that can't be read (`RequestsRoutes.unreadable`, Python's `(sqlite3.Error, OSError)`: SQLite's own
    error, a file's, a database too new) leaves the lines saying only how the jobs went, or no picks; anything else is
    a bug, the request's error;
  - `Feed.feed` takes the outcomes and chips as `Outcome` and `Chip`, and works out one not given from the job, as
    feed.py does (an outcome from its line, the running one's chips with no facts);
  - the times are the phone's zone's, named as Python's `%Z` names them, tzdata's abbreviations (CET and CEST), from
    requests.json's `zones` (`ZoneNames`: every zone's labels of letters by offset and since when, else the offset's
    number, `-03`, `+0545`), never java.time's or ICU's "GMT+01:00"; month names the C locale's;
  - `POST /jobs/again` is jobs_routes.again over `JobQueue.again`, its view the job as the queue has it now (one the
    worker started already runs, WebApp.job_view), its refusals caracole serve's words, but a request
    of the phone's own read back from the history, with nothing left to run (`JobNotRepeatable`): 409, the phone's
    words (`RequestsRoutes.NOT_REPEATABLE`);
  - vectors/web/requests.jsonl (feed.py's answer byte for byte under UTC and Europe/Madrid, `_ordinal`, `_ago`,
    `stamps.shown(local=True)` in zones of letters and numbers either side of a change of clocks, the tab for a
    count, feed.py's words) and requests.json, written by tests/test_conformance_requests.py (`RequestsReplay`, area
    `requests`), with library_page.json's pages whole, the tab in them.

##### The computer's settings on the phone

- A sync's agree stage takes the computer's settings from the state it reads again there (`PeerState.settings`, `GET
  /api/peer/state`'s `settings`; a member that isn't an object is none), inside the agreement's write:
  `SyncEngine.takeSettings`, then `PhoneConfig.take`, the document whole as kv `phone:settings`, as `kv_set_json`
  writes one, replacing the last. A state with none (an older computer) leaves it as it was; a sync that stops before
  agree takes none.
- `PhoneConfig.read` lays it over config.json's defaults, value by value as config.py would hold it (`[rank]`'s
  `line_match` and `prior_votes` numbers, 82.5 too, so `RankPolicy`'s are Doubles; a provider the phone doesn't know
  passed over). Assembly reads it for each lookup's clients and the cards; the library's `name` is shown nowhere yet,
  the phone's pages naming it `AppConfig.libraryName`, "Phone", until that reads `PhoneConfig.read(db).libraryName`.
- It is no unit: a take changes no unit's digest and no other record (SettingsTest), and the phone sends no settings
  back. Nothing of either side's politeness crosses (Two caracoles, each its own politeness, below).
- `SettingsReplay` (area `settings`) replays vectors/sync/settings.jsonl (each caracole.toml's document taken, then
  read as config.py holds it) and settings_take.jsonl (the take rule by rule), each take through `PeerState.read` and
  `SyncEngine.takeSettings`.

##### Syncing on the phone

- **The rules** are peer_sync.py's, replayed (`SyncReplay`, area `sync`): `Compare`'s kept answers (`keptOf`,
  `recordKept`, `mergedKept`, `compare(kept=)`, `recordAgreement` dropping each agreed unit's, the base written with a
  `"kept"` only when it holds one; `PeerState.kept`, the state's `kept`) and `Scope`'s parts (`PARTS`, `partOf`,
  `listedSongs` through `Songbooks.entryKeys`, `inScope`, `changeOf`, `namesOf`): vectors/sync/kept.jsonl and
  scope.jsonl.
- **The engine's comparison** (`SyncEngine.compare`) carries, beside its differences, its `kind` (`"computer"` or
  `"file"`), the parts the other side `holds`, the merged `base` and `kept` answers it compared against, the songs
  either side's songbooks `listed` (each songbook difference's document asked of the computer once,
  `Scope.listedOn`), each songbook difference's two documents (`songbooks`) and each site whose newest read differs
  (`indexes`, `IndexWaiting`); its hash is of the differences unscoped. `documents` gives a unit's two documents (a
  file's none of a unit it left out or of a part it doesn't hold, `FileSource.says`) and `tested` what the computer
  holds (its state read once, nothing changed).
- **`apply(c, choices, prefer, parts, conflicts)`**: only the differences of `parts` are taken, given or left
  (`Scope.inScope`: a part left out is never read as a removal, a song a songbook lists comes along with the
  songbooks); Library unticked skips the mirror stage, Site indexes unticked the index stage, each saying so. No stage
  is added to a network sync. `Conflicts.ASK` refuses a conflict settled neither way before any change;
  `Conflicts.LEAVE`, the unattended sync's, leaves it (`UNSETTLED`) and never refuses.
- **An import** (`compareFile`, then `apply` of its comparison) is a sync with a `.caracole` file (core.sync.file,
  peer_file.py's port: `SyncFiles`, `SyncFile`, `FileSource`, `FileError` in its words, vectors/sync/file.jsonl), in
  `FILE_STAGES` (check, take, mirror, agree, index): the file read and refused whole before anything changes (another
  format, this library's own export, one no newer than the last sync with its caracole, one that can't be read
  whole), compared within the parts it holds
  (a part it lacks is never read as a removal), taken from as from the computer, the units taken handed to the
  `pagesFromFile` hook, the agreement kept with the file's caracole at its `made` for the units it speaks for, each
  "keep mine" remembered (`SyncFiles.recordImport`), its indexes merged; it gives nothing back.
  - Its zip is read by `Zip`, CPython 3.14's zipfile by hand (the end records, zip64's too, the central directory,
    names in UTF-8 or cp437, each member's local header, its data stored or inflated, its CRC-32 at its end), never
    java.util.zip.ZipFile, which Android refuses at open for a name with `..` or a name twice (ZipPathValidator),
    where peer_file says which member is wrong: file.jsonl's zips made by hand hold it to Python's, on the device too.
  - Its JSON members are read as `json.loads(bytes)` reads them (`SyncFiles.json`: json.detect_encoding's UTF-8,
    UTF-16 or UTF-32, lone surrogates passed).
- **The report** (`SyncOutcome.report`, the sync redesign's §3.5): with whom (`with`: name, kind, address), when,
  its parts, and each index taken or given, its first table's rows (`TabCounts`) before and after: a taken one around
  its merge here; a given one on the computer (`GET /api/sync/indexes`, `PeerClient.indexes`) before the push and
  after its merge job, none from a computer that doesn't count them.
- A phone's own export writes the file `SyncFiles.export` makes (its indexes every site's whole, `IndexFile`, as
  `caracole index export` writes them, which SyncReplay compares with Python's as data; its pages through a
  `PageSource`, none until one is wired).
- What the phone says otherwise: the report leaves out a site whose merge moved its progress records alone (no row
  taken, its count the same), as IndexTransfer's `Merged` says what changed of the merge whole (`SyncEngine.taken`).

##### :viewer

- Its assets and data, `ViewerAssets` and `ViewerData`, and music theory (theory):
  - `viewer.theory` is viewer/theory.py (`Chord`, `Key`, `Theory`, Python's parameter names), its tables and
    patterns read from `data/caracole/viewer/theory.json`, which tests/test_conformance_viewer_theory.py writes from
    the module, never retyped; `Chord` a class with a data class's members, so that its `tones` are a frozen copy as
    Python's frozenset is, and every list handed out a copy (TheoryTest mutates them).
  - `ViewerAssets` reads viewer/'s files as page.py does (strict UTF-8) and names each page kind's (`Page`, held by
    vectors/viewer/theory_assets.jsonl); `ViewerData.table(module)` reads `data/caracole/viewer/<module>.json`
    (viewer_corpus.py `data_json`'s format), which shares its classpath folder with viewer/'s assets: no module's
    data is named `voicings*.json`.
  - tests/helpers/viewer_corpus.py is the seeded inputs every M5 generator reads (its docstring), the same in every
    process; an edit there, or to a string literal of tests/test_viewer_theory.py (the theory vectors read them),
    regenerates the corpus.
- A sheet read, ChordPro and a song's key (sheet-keys): `viewer.sheet`'s `Sheets` (viewer/sheet.py: `parse`,
  `directive`, `written`, `isLegend`, `isLegendLine`, `preambleSection`, `splitPreamble`), `SheetView` (page.py's
  reading functions that hold no HTML, below the page, so that a version's and the harp's reading need no page:
  `shown`, `drawnLines`, `writtenTexts`, `peek`, `places`, `played`, `songKey` and `viewerKey`, `givenShapes` and
  `shapesOf`), `ChordPro` (chordpro.py, with render.py's `chordProText`, `asLatin` and `needsFontFile` and
  ug/page.py's `decodeTwice`) and `MusicKeys` (keys.py: `sheetKey`, `sheetKeys`, `songKey` and `letterAlone` over the
  phone's `files` and `versions` as core.library reads them, `Kept.keptFiles` and `Versions.get`, each file read only
  as a regular file, never through a link; `SongKey`).
  - Their constants and patterns exported from the modules by tests/test_conformance_viewer_sheet.py into
    data/caracole/viewer/sheet.json, a member a module, never retyped; Python's lines, whitespace and lengths
    throughout (str.splitlines, str.isspace, code points, a chord's column a display column), never Kotlin's trim or
    lines.
  - Every answer held by vectors/viewer/sheet, chordpro and musickeys (`SheetReplay`, the `sheet` area), a sheet's
    derived lists by their digest; estimate_key's sums Python's (`Py.fsum`), its correlation compared to the bit.
  - Their inputs include every string literal of tests/test_viewer_sheet.py, test_viewer_preamble.py,
    test_chordpro.py and test_keys.py (`SHEET_LITERALS`, `CHORDPRO_LITERALS`, `KEYS_LITERALS`): an edit to one
    regenerates the corpus.
  - Where Kotlin holds less than Python: a `{capo}` or a sheet.json capo past an Int is none; and as in Python, a
    solfège name sre's IGNORECASE reads but no table holds (`[ch]ſol[/ch]`) raises.
- Voicings, instruments, the harmonica and the winds (shapes-harp-winds): `viewer.shapes`' `Voicings` (chords-db's
  fingerings from viewer/'s own voicings.json and voicings-ukulele.json, a legend's and a `{define}`'s shapes,
  `voicingKeys`, `sheetShapes`) and `Instruments` (`INSTRUMENTS`, easy keys, each one's shapes of a chord, a page's
  `voicings` and `instruments`), `viewer.harp`'s `Harp` (the layout, the chords a harp plays, the ranking in one
  place, the tables, `holeNote`, `holeTables`) and `viewer.winds`' `Winds`.
  - Their constants exported from the modules by tests/test_conformance_viewer_shapes.py: data/caracole/viewer/
    instruments.json (voicings.py's patterns too, viewer/voicings.json being chords-db's), harp.json (harmony's
    pentatonic boxes too) and winds.json (harmony's `_BASS_DEGREES` too: a chord's tones in harmony's order).
  - Every answer held by vectors/viewer/voicings, instruments, harp_* and winds (`ShapesReplay`, the `shapes` area),
    a page's objects in Python's order too (a kept answer's `sha256`).
- Pinyin with tones, OpenCC and hanzi (chinese):
  - core.pinyin's data is pypinyin's in Style.TONE alone (data/caracole/pinyin/, `symbols.txt` its tone marks):
    `Pinyin.lazyPinyin(text, errors, style)` (`DEFAULT`, `IGNORE`, `EMPTY_EACH`; `TONE`, `NORMAL`), NORMAL derived as
    pypinyin's `to_normal` (`Pinyin.normal`), which M1's NORMAL vectors guard, vectors/pinyin/tone.jsonl the TONE.
  - `viewer.chinese.OpenCC` is OpenCC's algorithm as hanzi.py runs `t2s`, `tw2s` and `s2tw` without tofu-risk
    dictionaries: normalization, mmseg, the chain, groups by `short_circuit` and `union`, an IDS written whole, a
    segment ending at a NUL. Its configs are the package's as shipped (data/caracole/hanzi/opencc.json, with
    `opencc.__version__`, 1.4.0) and its dictionaries the package's opencc_dict dumps (`hanzi/<Name>.txt`): an OpenCC
    bump regenerates them, and OpenCCTest names the version it ports.
  - `Hanzi` and `ViewerPinyin` are hanzi.py's and pinyin.py's, in code points (pinyin.py's constants from
    `viewer/pinyin.json`); hanzi.py's `chordpro` is the computer's PDFs' alone. tests/test_conformance_viewer_chinese.py
    writes their data and vectors (viewer/opencc, hanzi, pinyin_page), each also read back from the data alone.
- Harmony (harmony): `viewer.harmony.Harmony`, harmony.py's chord half: `numeral` (`Numeral.text`), `relation`,
  `family`, `explain` (the numeral's tooltip line), `glossary`, `chordTones`, `soloScale`, `keyScale`, `pentatonic`
  and `goesTo` (`_goes_to`), each read as `_read` reads the chord with the one it goes to (`HarmonyChords`, function for
  function, its words harmony.py's own), its tables harmony.py's exported to data/caracole/viewer/harmony.json
  (tests/test_conformance_viewer_harmony.py, `vectors/viewer/harmony_chords.jsonl`, HarmonyReplay); its progressions
  and tables (harmony-progressions):
  - `progressions`, `progressionKey`, `nameOf`, `readTyped` (each of a list or of a string typed) and `catalogue`
    (`catalogue_keys`), `HarmonyProgressions` function for function (`_fold`, `_passes`, `_varies`, `_whole`, `_rows`,
    `_contained`, `_ending`, public for the replay), CATALOGUE, `_LOOPS` and its other tables and patterns exported to
    harmony.json too, a key's turn chosen by code point as Python compares str;
  - `HarmonyTables.tables`, harmony_tables.py's, each object in Python's insertion order (a chord's reading the one most
    of its places have, the first seen in a tie), so that `PyJson.dumps` writes `json.dumps`' bytes;
  - `vectors/viewer/harmony_progressions.jsonl` and `harmony_tables.jsonl` (a table's members by their SHA-256, a few
    kept whole).
- A sheet's versions and progressions (version-progressions): `viewer.version`'s `Versions`, viewer/version.py's page
  side function for function, and render.py's `own_version` (`ownVersion`); `apply_version`, a sheet's ChordPro for
  chordpro's PDF of a version, is the computer's alone.
  - `fromQuery` and `query`, a version as the viewer's address reads and writes it (Python's parse_qsl, JavaScript's
    Number(), URLSearchParams' bytes); `playedKey`, `forInstrument`, `label` and `playedLabel`; `settingProblem` in
    Python's words and reprs, of any value a form or a file gives; `inSetting`; `keyVersion` (an
    IllegalArgumentException with key_version's words, which `Overrides.read` and `OverrideWriters.addVersion` take as
    their check), `inKey`, `entry` and `KeyVersion.query` and `label`, byte for byte, as `[version]` is in a song's
    sync unit.
  - `viewer.progressions`' `Progressions`, progressions.py's: `record` (kv `render:progressions:<song id>`, json.dumps'
    text, written only when what json.loads reads there changed), `forget`, `library`, `read`, `songsWith` (the
    library's keys as they are: it re-keys none), `catalogue`, `label`, `keyWords`; /api/search's `progression` is
    library-cards' to wire (Found.kt).
  - Their constants and patterns exported to data/caracole/viewer/version.json (`version` and `progressions`) by
    tests/test_conformance_viewer_version.py, which writes vectors/viewer/version.jsonl and progressions.jsonl
    (`VersionReplay`, the `version` area), a batch's answers by a 16-digit digest where the viewer area is short of
    room.
  - Where Kotlin holds less than Python: a chord's index, a shape's number or a swap's root or bass past an Int, in an
    address, is dropped, and a record's song id past a Long is none.
- A harmonica tab read (harptab-read): `viewer.harptab`, harptab.py's reading half, Q for Q:
  - `Notation`, `Symbol` and the presets as data (data/caracole/viewer/harptab.json, every constant and pattern of
    harptab.py, written by tests/test_conformance_viewer_harptab.py), each notation compiled at run time into its
    tokenizer (`Tokens`, `_alt`'s order and `re.escape`'s rules, through core.py.PyRegex);
  - `HarpTabs.scan` and its passes (Scanner.kt), its columns Python's code points (`Group.col`, `digit`, `end`), the
    text UTF-16 while it runs; a notation that folds reads a symbol as its tokenizer's IGNORECASE does
    (`Notation.meaning`: an "ı" or an "İ" is its "i", `PyRegex.ignoreCase`); the legends (`legend`, `meaning`,
    `entry`); the candidates, `weighed` (Python's builtin sum, Py.fsum), `read` and `readings`; a pin's `checkSpec`
    (Python's words and its reprs), `pinned` and `specOf`; `said`, `Reading.standard`; Python's `expandtabs`,
    `swapcase` (a capital sigma by its context) and `_fold_accents` (`HarpTabText`).
  - `Scan`, `Reading`, `Prepared` and `Weighed` are the seam harptab-layout builds `parse` on.
  - `HarptabReplay` (area `harptab`) replays vectors/viewer/harptab_read.jsonl: each fixture tab, the tests' literals
    and drawn tabs in every notation, their candidates, scores, scans (whole or by digest), readings and pins, each
    pin's tab read as it says (`read(notation=)`).
- A harmonica tab laid out (harptab-layout): `HarpTabs.parse`, harptab.py's layout half, giving Python's `Tab`:
  - Layout.kt: each line's kind, the tabber's notes, the sections, a row's words under it or above it (`above`), a
    section's name beside a row or sung (`isLabel(besideRow=)`), prose and later verses, `namedKey`, `Row.trusted`,
    `Tab.readable` and `missed`;
  - Align.kt: `syllableStarts` and `align`, which answers the row with its parts (Python's sets them in place), the
    cuts weighed as `_cuts` weighs them (`math.comb` exact, the costs summed as Python's builtin sum, Py.fsum), every
    column a code point;
  - `HarptabReplay` replays vectors/viewer/harptab_layout.jsonl too: each tab of harptab_read's records and drawn
    ones, parsed and read as another reading's pin says (layout/'s small tabs whole, the rest by digest, for the
    viewer's budget), its rows' parts as lengths, its lines and words, `align` on drawn rows, and `_cuts` on drawn
    words, on ties that each of its numbers decides (`TIED_CUTS`) and on MAX_CUTS's edges.
- The sheet page (pages): `viewer.pages.SheetPage` is viewer/page.py's builder, byte for byte: `build(ViewerInputs)`
  writes `build_viewer`'s page (the data's members in Python's order, `names` kept in its place; the policy of each
  inlined file's hash, `ViewerAssets.Page.SHEET`), `viewerCsp` its header, and the frame book.py and harptab_page.py
  reuse, under Python's names (`page`, `readSong`, `songHtml`, `sheetHtml`, `preambleHtml`, `sectionHtml`, `facts`,
  `footer`, `namesTable`, `zhAttr`, `artistLine`, `pdfLine`, `words`, `CONTROLS`, `LIBRARY_PAGE`).
  - Its HTML and constants are page.py's, data/caracole/viewer/page.json, which tests/test_conformance_viewer_pages.py
    writes from the module (`_CONTROLS`, `_SHEET_CONTROLS`, `_VERSIONS`…, chords-db's notice, `_META_POLICY` run over
    a page's bytes read as Latin-1); its icon page/icon.json's; `build_version` is Python's alone.
  - `PagesReplay` (area `pages`): vectors/viewer/pages_parts.jsonl (the frame, function by function), pages-1.jsonl to
    pages-6.jsonl (every corpus sheet's page with every option, as digests: the page, its body, each data member, its
    names) and page_whole.json (a small page whole, the files it inlines by name).
  - A page record is the generator's `page_out` and `PagesReplay.out`: `sha256` and `size` of the whole page, `body`
    and `names` as their SHA-256's first 16 hex digits, `data` one string of `member=digest` in the data's order (8 hex
    digits each), so that it pins the members' order too; another lane's page records take that shape.
  - Printed, every viewer page is in the light palette with a 15 mm margin: viewer.css's dark palette is the screen's
    alone (`@media screen and (prefers-color-scheme: dark)`), `@media print` sets `color-scheme: light` and `@page`
    the margin, which Android's print framework gives a WebView's page none of (tests/test_viewer_print.py, in
    Chromium's print emulation).
- A harmonica tab's page (harmonica-page): `viewer.pages.HarmonicaPage`, harptab_page.py's builder, byte for byte:
  `build` writes `build_harmonica_viewer`'s page on SheetPage's frame (`page`, `namesTable`, `isChinese`, `zhAttr`,
  `artistLine`, `words`, `LIBRARY_PAGE`; `ViewerAssets.Page.HARMONICA`), its data's members in Python's order (`groups` and `rows` filled as the tab
  is written), and its parts under Python's names (`overlayData`, `harpLines`, `readAs`, `footer`, `a`); and
  `viewer.harpfit.HarpFit`, harpfit.py: `pitch`, `words`, `sheetLines`, `recordFit` (PySequence.SequenceMatcher, the
  fits by share then harp), `choose` and `Choice.tabsHarp`, and render.py's `_tab_harps` as `tabHarps` (each
  `HarmonicaTab` a kept tab as render.py reads it; one it can't read, a refused pin among them, gives no harp), the
  harps a sheet's viewers start on (`harpTabs`).
  - Its constants are data/caracole/viewer/harmonica_page.json (harpfit.py's, and harptab_page.py's `_BAR`,
    `_BAR_RAW`, `_PILL`, `_SAID`…), written by tests/test_conformance_viewer_harmonica.py; its numbers as Python
    writes them (`round(q, 2)` a PyJson float; `{share:.0%}`, `{views/1000:.0f}k`, `{views/1e6:.1f}M`,
    `{rating:.1f}★` and `({q:.2f})` through PyFormat), a fact counted only where Python's `isinstance` takes it.
  - `HarmonicaPageReplay` (area `harmonica-page`): vectors/viewer/harpfit.jsonl (pitch, words, a sheet's sung lines,
    each tab's fit and choices, `_tab_harps`), harmonica_pages.jsonl (the parts, and every page as digests: the page,
    its header, tab, foot and bar, each data member, the overlay's two) and harmonica_pages_whole.jsonl (a small page
    whole, the files it inlines by name); the texts that are no fixture in harpfit_texts.jsonl.
- The phone's own pages, `PhoneRender` (phone-render): render.py's page path with no PDF, for the songs no mirror
  page serves at their unit's digest (`owed`: kv `render:<id>:phone`'s `unit` and `build` not now's), each pass
  render_all's for the song (`SongPass`: the kept versions' pages, each sheet's .cho and page, an auto sheet's beside
  the human one with no export and none of its shapes and swaps, the harmonica tabs' pages whatever came of the
  sheets, with HarpFit.tabHarps, a viewer's `guitar` from GuitarFiles, inbox.guitar_files' port), after `PlainLyrics`
  (sheet_lyrics.py) and `OwnVersions` (own_versions_upgraded); a song the mirror serves gets its progressions, script
  and info.json alone, the phone's own pages of it forgotten.
  - `WrittenPages`: kv `render:files:<id>` as render.py records it, each entry's `unit` the song unit's digest it was
    made at (Units.digestOf: an entry no pass wrote or found as written keeps its own); kv `render:<id>:phone`
    (`unit`, `build`, `script`, which `chineseSongs` reads for the cards, the phone making no PDF record); a songbook's
    kv `songbook:<folder>`.
  - `InfoJson` is library.write_info, its `render` null whatever kv `render:<id>` holds; `RenderBuild` is the app's
    version and, on the phone, the APK's `classes*.dex` and `caracole/` entries by name, size and CRC-32, so every
    APK whose code or tables changed makes the pages again (elsewhere each viewer asset and runtime data file the
    pages read, hashed, each listed and held to its folder by PhoneRenderTest).
  - `render` is the lookup's pdf stage (in its write, its `between` never the queue's), its failed detail render.py's
    log line, the phone's alone; `renderStale` the render job's, a write a song, `between` two
    (JobContext.yieldToQueued: PhoneRenderJobTest on the real queue), passing over a song a lookup made meanwhile, then
    kv `phone:render-build`; a song's pass that fails, on a bug too ("a bug in caracole"), costs the others nothing
    and is stamped all the same.
  - `stale` is the start's, one query (a song this build never made, or kv `phone:render-build` not this build's);
    `afterSync` reads every song's digest, inside the sync's job, and `owe`s (that kv forgotten) what moved, as a change
    on the phone that makes no page of its song does.
  - tests/helpers/phone_render.py is the reference (render_all with `_render_sheet_pdf`, `_render_traditional` and
    `_remake_exports` making nothing, `_write_viewer` linking no PDF, `_drop_human_outputs` the phone's and no PDF's
    record read, whatever PDFs the library holds; then the phone's records and info.json);
    tests/test_conformance_viewer_render.py writes vectors/viewer/render.jsonl (fixture libraries and steps: renders, a
    file dropped, one deleted), which `RenderReplay` (area `render`) replays: the names, each pass's info.json and
    units, and every step whole.

##### The phone's written pages

- `LibraryFiles` serves a page the phone wrote (a sheet's viewer, a kept version's, a harmonica tab's, a songbook's in
  `_songbooks/<folder>/`) as app.py's `_written_page` does, before the mirror's:
  - while it is the bytes WrittenPages recorded (`render:files:<id>` among the songs whose folder it is in, of those
    with a record; `songbook:<folder>`), read once, of a recorded size and SHA-256, and its unit (the song's, or the
    songbook's, `WrittenPages.songbookUnit`) is still at the digest it was made at (each entry's `unit`);
  - with `SheetPage.viewerCsp` of those very bytes (its `_NOTHING` sandbox for a page with no policy) and
    `frame-ancestors 'none'`;
  - otherwise the mirror's through PhoneGate, else a message page: 409 for a unit moved since its page was made (the
    phone's sheet.txt linked), 404 Not sent, by the page's kind, for one changed on disk;
  - a .cho it wrote the same way, as text (LibraryFilesTest).
- Its checks are made on the path, then the file is opened with no link followed and its bytes checked: the library
  is the app's own folder, which nothing but the app writes.
- `PhoneRender.afterSync`, after a take: the pages the take superseded forgotten (`forgetSuperseded`: each deleted
  while it is as written, its record's entry with it), a song's or a songbook's made at a digest its unit has moved
  from where the mirror now serves it at its digest, and a songbook's whose folder no songbook has any more; a moved
  song's page the mirror doesn't serve stays, never served, for the render job to make again.
- A removal takes the phone's written pages by their records: each `render:files:<id>` entry naming the `unit` it was
  made at, as removal.py takes a version's or a tab's page (the phone makes no PDF, so no render record names them); a
  record render.py wrote names no unit and keeps removal.py's answer (RemovalWrittenTest).
- A take that moves or respells a song's folder deletes the phone's pages of it still as written rather than moving
  them (`Removal.phonesWritten`, SongTake), so no page is left there unrecorded and a removal after it empties the
  folder (RemovalWrittenTest).
- PagesServedTest opens one in the WebView: its own policy and an opaque origin, refused once changed on disk or once
  its song's unit moves.

##### Songbooks, versions and printing on the phone

- Songbooks, their entries and the Songbooks tab (songbook-writers, songbook-entries, songbook-routes): not built yet.
- A sheet's versions and a harmonica tab's readings chosen on the phone (versions-harmonica): not built yet.
- Export PDF and Make this my version (export-print): not built yet.

##### Guitar Pro on the phone

Not built yet. (guitar-alphatab.)

##### A song shared to the app

- A music app's Share of a song is `ShareLinkActivity`'s (SEND of text/plain alone, its own intent filter; files are
  ShareActivity's): its extras logged under `caracole-share` (`SharedLink.said`), then the library screen loads
  `GET /share` with them (`SharedLink.page`; MainActivity takes a share page alone from an intent, and Cancel,
  `/share/cancel`, as `leaveShare`: the history before the share, the sender in front).
- core.share's `SharedText.read`, the one place that knows each app's words, before read_names: the app (package,
  link host, words), the first link, each app's shape (`SHAPES`: Deezer's, Shazam's, SoundCloud's… as "Artist -
  Title"), else the text less its links and an app's name, with no request. tests/fixtures/share/shares.jsonl holds
  each app's shapes and where they were found (SharedTextTest).
- A text that names no song but a link of Apple Music's, Spotify's, TIDAL's, YouTube's or YouTube Music's is read by
  asking its service once, the owner's choice of 2026-11-10 (Politeness, "A shared link read by asking its service
  once"):
  - core.share's `ShareLinks.of`: what the link is, with no request (a song's id, a short link, or an album, a
    playlist, an artist… that names no song, said so); `answer`, what the service's answer names (Apple's lookup,
    Spotify's and TIDAL's track page, YouTube's oEmbed: a video's title and channel, read by read_names as a pasted
    video's), a page that won't parse a `ShareParseError`, never a miss;
  - `ShareAsk`: off, the cache's answer with no request and no write, else one ask through the lookup's envelope
    (`InteractiveAsk`, run `lookup:share:…`) inside one write (server's `ShareReader`), its words one line;
  - ShareLinksTest and ShareAskTest, over the services' answers to caracole of 2026-11-10 (tests/fixtures/itunes/,
    spotify/, tidal/, youtube/).
- server's `ShareRoutes` is the phone's own page, which caracole serve has none of:
  - the names through `SongNames.readNames` (a link's service's, "Read from Spotify's page: …"), searched as
    `/api/search` searches (`SearchRoutes.answer`);
  - its rows on one line a song (`SongLine`, as mergeSites), the best (`best`, else the names' identity);
  - Get it the library page's `POST /lookup`, Open, Edit (`GET /share?artist=&title=`), in the message page's frame
    and policy (`MessagePage.html`: no script).
- ShareRoutesTest and SharedLinkTest on the JVM, ShareLinkTest on the device.

##### Files shared to the app

Not built yet. (inbox-share.)

##### Alerts and backups on the phone

Not built yet. (alerts-backups.)

tests/conformance/ is the corpus between the two (its README): `data/caracole/` the phone's runtime data (a resource
root of `:core`), `vectors/` what the Kotlin tests compare with, both written by `tests/test_conformance_*.py` through
helpers/corpus.py.

#### The phone agrees with the computer to the byte

- What the Kotlin side ports, Python states as data in the conformance corpus
  (docs/superpowers/specs/2026-11-03-conformance-corpus.md): each `tests/test_conformance_<area>.py` builds its file
  and `helpers.corpus.check`s it against the committed one. Never edit one by hand; regenerate:
  `CARACOLE_CORPUS=write nix develop -c pytest -q -n 0 tests/test_conformance_*.py`.
- A change to normalize, search, peer_sync, the schema, library_assets, status.py or outcome.py regenerates the corpus
  in the same commit, and `nix develop ./android -c gradle -p android test` passes before it merges. When a Kotlin
  test breaks on it, the change doesn't merge: it is conformance drift, the Kotlin side's to follow first (the drift
  protocol, in the spec).
- A `SCHEMA_VERSION` or `KEY_VERSION` bump moves the phone in lockstep: migrations.json regenerated,
  `Database.SCHEMA_VERSION` and `Normalize.KEY_VERSION` bumped, `LibraryStore.ensureCurrentKeys` re-keying as
  `songs.ensure_current_keys` does.
- `:core`, `:viewer` and `:server` never call a JDK or ICU text API (case, normalization, `Character` classes,
  `java.util.regex`'s own `\w` or `\s`, `Collator`): their Unicode is not Python's, and on Android it varies by
  device. They use `core.py` and its tables, held by the shared check `core.testing.ForbiddenApis` (each module's
  `ForbiddenApiTest`; an M1–3 file a later lane ports may be allowed by name, with that lane, until it does: none
  is today).
- What the JVM can't show, the device does: `CorpusOnDeviceTest` answers every record of the `unicode`, `keys`,
  `pinyin`, `fuzz` and `canonical` vectors under Android's runtime and ICU-backed regex (it found ICU reading a `\G`
  inside a lookaround otherwise than the JDK: py/PyRe.kt's guard after an empty match uses no `\G`).

## Development

### Running the tests

- **Fast loop**: `nix develop -c pytest -q -m "not slow"` (about 6 s) while you work, and the whole suite,
  `nix develop -c pytest -q` (about 35 s), before a commit.
- Always through `nix develop`: its pytest has pytest-xdist, which spreads the suite over the cores; a pytest without
  it runs the whole suite in one process, for minutes.

```
nix develop        # Python 3.14 with the dependencies, pytest, pytest-xdist, chordpro, ruff, sqlite3
caracole --help    # in either shell: the checkout's src/ (PYTHONPATH), no rebuild after an edit
pytest -q                         # the whole suite, from the repo root, on up to 12 cores
pytest -q -m "not slow"           # the quick loop, a few seconds
pytest -q -m "not slow" --lf -x   # what failed last time, stopping at the first failure
pytest -q tests/test_fetch.py     # given paths, pytest runs them in one process
nix develop .#autochords -c pytest -m autochords   # the model tests
nix develop ./android -c gradle -p android test    # the Android side: :mirror, :core, :server, :app, :e2e on the JVM
CARACOLE_ANDROID_E2E=1 nix develop -c pytest -q -n 0 tests/test_android_e2e.py   # the phone and the computer synced
```

- tests/test_android_e2e.py, marked `android_e2e` and `slow`, is skipped unless `CARACOLE_ANDROID_E2E=1`: the goal's
  scenario (docs/android_port.md), a computer built by tests/helpers/e2e_library.py with no request and real `caracole
  serve` processes, the phone android/e2e's `PhoneScenarioTest` on the JVM, a Gradle run a phase.
- **The device step**, the one place an emulator runs, one at a time (android/README.md, "Try it on an emulator"):
  `nix develop ./android#emulator`, the AVD made once (`avdmanager` writes it under `~/.config/.android/avd`: give
  `ANDROID_AVD_HOME` that folder), `emulator -avd caracole -gpu host` with `LD_LIBRARY_PATH=/run/opengl-driver/lib`
  (and `QT_QPA_PLATFORM=xcb` on Wayland), a computer of its own for each test that changes the phone's library
  (`nix develop -c python -m tests.helpers.e2e_library serve DIR PORT --address 127.0.0.1`, the emulator's
  `http://10.0.2.2:PORT`), `adb shell pm clear io.github.danielhp95.caracole` between them, and each class alone with
  `adb -s emulator-5554 shell am instrument -w -e class io.github.danielhp95.caracole.CLASS [-e server …]
  io.github.danielhp95.caracole.test/androidx.test.runner.AndroidJUnitRunner`.

- Given no paths, pytest runs on pytest-xdist workers (conftest.py: `-n auto`, at most 12, `--dist worksteal`).
- `-n 0` runs it in one process, as `--pdb`, `--trace`, `-s` and `-m autochords` do.
- `slow` marks a test that starts a browser (`helpers.browser.in_chromium`), chordpro or the models
  (`@pytest.mark.chordpro` and `autochords` add `slow`) or another process: mark a new one too.
- The whole suite stays the gate before a commit.
- tmp_path is in /dev/shm, and stays on disk with `--basetemp` or `PYTEST_DEBUG_TEMPROOT`, or when /dev/shm is noexec
  or has less than 1 GB free (a container's).

### Browser tests

- A test that opens a page in Chromium is marked `@in_chromium` (or has it as its module's `pytestmark`,
  `helpers.browser.CHROMIUM_MARKS`): slow, and skipped without Chromium.
- One that opens a page unmarked fails (`helpers.browser.require_in_chromium`).
- It opens pages through:
  - helpers/browser.py, `dump_dom` (the DOM once the page's script ran, its timers on virtual time, in one Chromium
    per process and a fresh context per page) or `Browser` (a page on real time, to type, press keys, click and touch,
    in a browser context of its own of another Chromium the process's Browsers share, `_Driven`);
  - or helpers/chromium.py, for a page whose policy refuses a test's script.
- None of them resolves a host name (`helpers.browser.NO_LOOKUPS`), and the other browser helpers in tests/helpers/
  build on them.
- A test that drives a page on real time (`Browser`) waits for the state it needs, never a fixed time: its workers
  share the machine with eleven others.
  - `Browser.wait`: an expression that throws while the page still loads is not true yet; once the page has loaded,
    it raises at once.
  - After a step that loads the page again (a reload, a songbook's next song), it waits for the new document, not the
    one before it (`window.before`, as `Browser.open` does for an address).
- The library page caracole serve serves asks /jobs.json every 1.5 s and counts Remove's five seconds:
  - `WebApp(timers=...)` shortens both for such a test (test_web_page.py's `QUICK`);
  - and caracole serve never sets it, so the page users get carries no timers (`WebControls.timers`).

### Programs and models the tests need

- Both shells set `CARACOLE_CJK_FONT` to the packages' font, `CARACOLE_PDF_FONTS` to their PDF fonts
  (nix/pdf-fonts.nix), and `CARACOLE_ALPHATAB_DIR` to alphaTab (nix/alphatab.nix).
- `.#autochords` adds torch, beat-this and librosa, and sets `CARACOLE_BTC_WEIGHTS` and `CARACOLE_BEAT_CHECKPOINT` to
  the files nix/autochords.nix fetches.
- Tests that need a real program or model skip without it:

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

### Before a change is done

```
nix develop -c pytest -q
nix develop .#autochords -c pytest -m autochords   # when auto-chords is touched
nix develop ./android -c gradle -p android test    # when android/ or the corpus is touched
CARACOLE_ANDROID_E2E=1 nix develop -c pytest -q -n 0 tests/test_android_e2e.py   # when sync, android/ or the corpus is
nix flake check
```

- `nix flake check`'s package build runs the suite on a tree of pyproject.toml, README.md, LICENSE, src/ and tests/
  alone: a test that reads docs/ or android/ skips there (test_nix_package.py, test_android_termux.py,
  test_canonical.py).

- `nix flake check` builds three checks:
  - `package` and `autochords` each run the suite (minus the tests marked `autochords`), then check that the installed
    package is src/ file for file (the suite imports caracole from src/, so a data file left out of the wheel shows
    only there: a new asset folder goes inside src/caracole/) and check the wrapped `caracole`;
  - `module` evaluates small NixOS systems against nix/module-check.nix, loads their caracole.toml with config.py and
    parses their units' command lines with caracole's own CLI (a command or option a unit names, renamed or removed,
    fails it).
- One at a time: `nix build`, `nix build .#autochords`, `nix build .#checks.x86_64-linux.module`.

### Traps

- The flake sees only files git tracks: `git add` a new file before a Nix build.
- The package builds from pyproject.toml, README.md, LICENSE, src/ and tests/ alone, in a sandbox without network
  (test_nix_package.py skips itself there). A subprocess test keeps the inherited PYTHONPATH
  (`conftest.subprocess_pythonpath`): the dependencies arrive on it.
- A dependency is listed three times: pyproject.toml, flake.nix (`runtimeDeps` or `autochordsDeps`) and
  nix/package.nix.
  - It comes from nixpkgs: no pip, uv or PyPI pins.
  - Every third-party module src/ imports is listed, even one another dependency brings (click with typer);
    auto-chords' modules may import the extra's.
  - test_nix_package.py checks both.
- The version is in pyproject.toml and src/caracole/__init__.py; the package check compares `caracole --version` with
  pyproject's, and test_cli.py expects "caracole 0.1.0".
- A Nix file may set only `CARACOLE_*` variables the source reads (test_nix_package.py). A unit setting changes
  together with its expectation in nix/module-check.nix.
- docs/deploy.md's Ubuntu part pins by hand what Nix pins:
  - its constraints.txt is the package's versions in flake.lock's nixpkgs;
  - its CPython and deno are nixpkgs' too;
  - and its SHA-256s are nix/'s (alphaTab's and the model files', which test_nix_package.py checks, and the fonts
    nix/pdf-fonts.py makes).
  - A commit that moves flake.lock or nix/ moves deploy.md with it.
- `ruff check --select E4,E7,E9,F src tests` is clean; ruff's default rules and `ruff format --check` are not. Don't
  reformat code you aren't changing.
- Every pytest-xdist worker collects the suite itself and must find the same test ids: parametrize with nothing that
  changes between processes, such as a zip's clock-dated entries (helpers/zips.py `dated_entry`), random values or a
  set's order.

## How work is done here

- Test first: a test that fails (on the missing name or an assertion), then the code.
- **Never a live request in a test**: not to ultimate-guitar.com, lrclib.net, megalobiz.com, azlyrics.com,
  lacuerda.net, gtptabs.com, musescore.com or YouTube.
  - Give `PoliteClient` an `httpx.MockTransport` as `transport=`.
  - CLI tests monkeypatch `caracole.commands._common.transport_for` (and `_common.sleep`).
  - Pipeline tests pass `Services` with fake clients (`FakeGtpTabs.client` and `FakeMuseScore.client` make real ones).
  - YouTube tests run `FakeYtDlp` as `ytdlp_bin`, never a real yt-dlp: conftest.py points `CARACOLE_YTDLP_BIN` at no
    program for every test, so a command reading the real environment in `nix develop .#autochords` (torch, the model
    paths, yt-dlp on PATH) finds the route off.
  - Nothing blocks the network for the whole suite; only the package build's sandbox has none.
- **A Kotlin test never reaches the network**: every Gradle `Test` task sets `caracole.network=loopback`, under which
  `core.http.RealTransport` refuses any host but loopback and the emulator's `10.0.2.2`; the app's instrumentation
  runner, `CaracoleTestRunner`, sets it too, before `Application.onCreate`, and makes `Caracole.sitesForTests` a
  transport that refuses every site unless a test sets another. `PhoneDeps.transport` has no default: every `Phone` a
  test builds names its transport.
- **The device**: a lane's device tests run only through `android/scripts/device-test.sh` (`--area NAME` for a
  corpus area, `--app` for the app's classes, `CLASS[=DIR]` for its own), which builds first, then holds the
  emulator's lock (`${CARACOLE_EMULATOR_LOCK:-${XDG_RUNTIME_DIR:-/tmp}/caracole-emulator.lock}`) while it installs and
  runs, starts the one emulator if none is up and leaves it up.
- **Big data sets** (more than a few thousand rows) run only in a `*Bench` class of the gated `bench` task
  (`nix develop ./android -c gradle -p android bench`: a 3 GiB heap, one fork), never in `test`, which excludes them.
- `load_config` takes `env=`, and unit tests pass it. CLI tests read the real environment: clear what could leak in,
  as `OUTSIDE_SETTINGS` does in test_commands_sources.py.
- **Heavy imports** stay inside the command function: `cli.build_app` imports every module in commands/ on every
  start, and the default package has no torch.
  - `test_commands_index_match.py::test_registering_the_commands_imports_neither_the_matcher_nor_the_index` fails
    when importing `caracole.cli` loads rapidfuzz, `caracole.match` or `caracole.ug`; the
    `test_registering_the_command*` tests of fetch, lyrics, sources, autochords and youtube do the same.
  - httpx, with the rich and pygments it brings, is a third of a start: http.py imports it inside the functions that
    use it, and `_common` makes its client class on first use (`_locked_client`).
  - `test_commands_index_match.py::test_a_command_that_sends_no_request_imports_no_http_client` fails when importing
    `caracole.cli` and reading a `[youtube]` entry (youtube_urls.py) loads httpx, rich, `caracole.http` or
    `caracole.youtube`.
  - music.py imports mutagen in `read_audio` alone, and lyrics.py (`expected_seconds`) in `_matches`: inbox.py, which
    the pages import, scores names with its `Names` (`test_music.py::test_the_pages_load_no_tag_reader`,
    `::test_the_inbox_loads_no_http_client`).
  - viewer/pinyin.py imports pypinyin in `_read` alone, and viewer/hanzi.py OpenCC in `_converter`: a page of a sheet
    with no Chinese loads neither (`test_viewer_pinyin.py::test_pypinyin_is_loaded_only_for_a_sheet_with_chinese`,
    `test_viewer_hanzi.py::test_opencc_is_loaded_only_for_a_sheet_with_chinese`).
- Branch from `main`, the default branch: each piece of work on a branch of its own, merged into `main` once it passes
  (`caracole-v1`, the default until 2026-10-27, is retired).
- Conventional commits, scoped by area: `fix(fetch): …`, `feat(lacuerda): …`, `test(commands): …`, `docs: …`,
  `build(nix): …`.
- No Claude or AI attribution anywhere: no Co-Authored-By trailer or "Generated with" line, in commits, code or docs.
- Keep docs/usage.md, docs/deploy.md and docs/install.md in step with behaviour (commands, options, defaults, files,
  messages) in the same commit; no test checks them.

## Invariants

Each names where it is enforced. Don't weaken one to make a test pass.

### Politeness

Politeness (http.py, health.py, commands/_common.py), at two paces (`config.ProviderPolicy`; `_common.make_client`
picks one).

#### Bulk work

- The nightly run (its index refresh included), `caracole index build` and every command but `caracole get`,
  `caracole versions`, `caracole lacuerda --artist` and `--search`, and `caracole harptabs --artist`.
- Budgets per run (`config.DEFAULT_PROVIDERS`):
  - `ug` 60;
  - `lrclib` 200;
  - `megalobiz` 60 (a search and a record a song, `megalobiz_fetch.py`; and never more than its `per_day`, 900 a UTC
    day, every run's, command's and lookup's together, counted in `events`: `_common.within_the_day`, under its API's
    1,000 a day);
  - `azlyrics` none (`config.NO_BUDGET`, the owner's choice of 2026-10-30, the one site with none: two requests a
    song, only for a song with no lyrics, each once in 30 days; a lookup keeps its own limits);
  - `lacuerda` 30 (its sheets first, then its listings of every artist, then, once those are read whole, the pages of
    its most popular artists not read in 30 days, `lacuerda_fetch.POPULAR_PAGES` (10) at most);
  - `gtptabs` 20;
  - `musescore` 10;
  - `harptabs` 20 requests (its sitemap, then a song's candidates, `harptabs_fetch.CANDIDATES` (8) at most, then, once
    the library has a song, artist pages with what is left, `harptabs_index.artist_pass`);
  - `gametabs` 20 requests (its sitemap index and six children, then a song's candidates, `gametabs_fetch.CANDIDATES`
    (4) at most, then, once the library has a song, game pages with what is left, `gametabs_index.game_pass`);
  - `youtube` 6 yt-dlp runs;
  - `ytimg` 20 requests (YouTube's image host: the thumbnail of a video suggested for a search, one image a video,
    youtube_search.py).
- `caracole index build`: at least 100 (`BUILD_BUDGET`, commands/index.py); and `caracole harptabs --index` and
  `caracole gametabs --index` their `--budget`, `BUILD_BUDGET` by default.
- Then `BudgetExhausted`.
- Between any two requests to a provider, a random pause from its `delay`, each a quarter of what it was before
  2026-11-03, the owner's choice that day ("wait times divided by 4"; the budgets and limits are as they were):
  - 2.5–5 s for UG, LaCuerda, gtptabs.com, MuseScore and harptabs.com;
  - 0.25–0.5 s for LRCLIB;
  - 0.5–1 s for Megalobiz (0.5–0.75 s a lookup's): its API allows 30 a minute, which caracole can now go past, by
    the owner's choice (a 429 is a block, as at any site);
  - 0.25 s for gametabs.net (its robots.txt's `Crawl-delay` asks 5 s: caracole waits less, by the owner's choice);
  - none for `ytimg`: the owner's choice of 2026-10-29, a thumbnail comes right after its search, YouTube's
    3.75–7.5 s between yt-dlp runs and its last request never holding it back;
  - none for `azlyrics`, the owner's choice of 2026-10-30, at either pace.
- Everything else below binds both.

#### An interactive lookup

- An interactive lookup is one of:
  - `caracole get`, one song asked for just now (caracole serve's lookups run it);
  - `caracole versions --keep`, one tab page asked for now, and `--keep-more`, as many as one lookup's budget lets
    (`--choose` and `--clear` run get);
  - `caracole lacuerda --artist`, one artist's page (an artist's Songs);
  - `caracole harptabs --artist`, one artist's page (an artist's Songs, once in 30 days);
  - and `caracole lacuerda --search`, one query of LaCuerda's search (one request).
- `caracole lacuerda --search`:
  - a query at most once in 30 days, kv `lacuerda:search:<key>`, its words' key in alphabetical order;
  - none once your library or LaCuerda's index answers it well, `lacuerda_search.answered`, checked again after the
    cached artist pages are stored;
  - those the pages send by themselves, `--auto`:
    - at most `lacuerda_search.SEARCHES_PER_HOUR` (20) in the last hour, counted in `events` under runs named
      `lookup:lacuerda-search:…`, within `lookup_per_hour`;
    - and none of a query whose search failed within the hour, nor any once three did, kv `lacuerda:search-failed`:
      an answer caracole can't read is never asked again by every page that shows the query.
- Its clients are `make_client(..., interactive=True)`:
  - a random gap from `lookup_delay` (default 0.125–0.375 s, the owner's quarter of 2026-11-03; `[0, 0]` allowed)
    between two requests to a provider;
  - a budget of `lookup_requests` (6) requests to it for the song;
  - and at most `lookup_per_hour` (60) for every lookup of the last hour together (`_common.lookup_policy`, counting
    the `events` of runs named `lookup:…`).
- What follows the sheet, which the nightly run would do anyway (get.py's `ug` stage, LaCuerda for a song with a
  sheet), spends only what leaves `get.SHEETS_SHARE` (half) of that hour's requests for sheets
  (`_Lookup.after_the_sheet`).
- Then `BudgetExhausted`: the rest waits for the nightly run.
- Nothing else is looser for a lookup, and a lookup never runs yt-dlp.

#### A shared link read by asking its service once

- The owner's choice of 2026-11-10: a link shared to the phone whose text names no song (core.share's `SharedText`)
  is read by asking its service once, one request a shared link, at a lookup's pace and nothing looser (core.share's
  `ShareLinks`, `ShareAsk`):
  - Apple Music: `itunes.apple.com/lookup?id=…&country=…`, provider `itunes` (Apple documents about 20 calls a minute
    for it);
  - Spotify: the track's page, `open.spotify.com/track/<id>`, provider `spotify`, which names the artist to
    caracole's own user agent (checked by hand on 2026-11-10; its oEmbed names the title alone, and is unasked);
  - TIDAL: the track's page, `tidal.com/track/<id>`, provider `tidal`;
  - YouTube and YouTube Music: YouTube's oEmbed, `www.youtube.com/oembed?url=…&format=json`, provider
    `youtube-oembed`, never yt-dlp's `youtube`.
- Each asks the one URL the link's id names: one request, or two for a short link (`spotify.link`,
  `spotify.app.link`, `tidal.link`), whose redirect, to another site, is its answer (a redirect whose status the
  caller accepts is never followed: http.py and core.http alike, client.jsonl's session). An album's, a playlist's or
  an artist's link names no song, said with no request. Deezer's shares carry their names (its API's robots.txt is
  closed: never asked); a Navidrome or Subsonic server's link is never asked.
- Their policies (config.py, `SHARE_PROVIDERS`): no budget, no bulk work (no run or command of the computer asks
  them, pipeline.py and the to-do page's health leave them out), `lookup_requests` what a share needs (1, Spotify's
  and TIDAL's 2), within `lookup_per_hour` with every lookup's (run `lookup:share:…`), at `lookup_delay`.
- Each is switchable (`config.SWITCHABLE`, `enabled = false`, which the phone takes from the computer at a sync), on
  by default.
- The cache's answer is read first, with no request; a block cools the service down and alerts once, an error is
  counted, and the page says either in one line, Edit open: never "this link names no song" for an error.
- Nothing is sent to a tab site before Get it.

#### Either pace

- One request at a time per provider (a synchronous client, and the lock below), redirect hops included.
- `PoliteClient` paces its own requests, and `_common._pause_after_last_request` its first after the last one any
  caracole sent (kv `http:last_request:<provider>`, to the fraction of a second, else `events`), as bulk work's client
  paces its next one once its process let a lookup go first (`_LockedClient._after_a_lookup`).
- The gap between two requests is the pace's alone: no robots.txt `Crawl-delay` adds to it (gametabs.net's asks 5 s;
  the owner chose, on 2026-10-28, that caracole does not keep it), nor an API's own rate (Megalobiz's 30 a minute;
  the owner chose, on 2026-11-03, the wait times divided by 4, quicker than that). The Sites tab says so of both
  (sites.py `CRAWL_DELAY_ASKED`, `API_PACE_ASKED`).

#### Two caracoles, each its own politeness

- A phone and a computer each keep their own limits, request counts (`events`), cooldowns, pace
  (`http:last_request:`) and the kv records that gate a request, and nothing of them crosses at a sync: the owner's
  choice of 2026-11-03 ("Don't do the polite request across 2 devices";
  docs/superpowers/specs/2026-11-03-politeness-crossing.md).
- So two caracoles at one address may together send a site more than either one's limits; each keeps every rule
  here on its own, and the phone looks songs up at the lookup pace alone.
- What the phone takes from the computer is its settings (provider switches, lookup settings, `[match]`, `[rank]`, the
  user agent, the library's name: `GET /api/peer/state`'s `settings`, politeness.py `settings_document`, which the
  phone keeps as kv `phone:settings`), never its politeness.

#### Turning a provider off

- Only a provider in `config.SWITCHABLE` (`megalobiz`, `azlyrics`, `gtptabs`, `musescore`, `harptabs`, `gametabs`,
  `youtube`, `ytimg`, and a shared link's `itunes`, `spotify`, `tidal`, `youtube-oembed`) can be turned off
  (`enabled = false`): then it gets no client and its step is skipped (`ytimg` off: a suggested video's row without
  its thumbnail; a shared link's service off: the phone's share page says so, and asks it nothing).

#### Blocks

- A 403, a 429 or a challenge page raises `ProviderBlocked`:
  - the client sends nothing more that run;
  - `health.record_block` cools the provider down for 24 h × 2^(k−1) + 2 h after the k-th block in a row (so the next
    nightly run is always skipped);
  - one ntfy alert goes out for the block, never one a song, titled with `logs.provider_name` (the run's step, or
    `_common.alert_block` in a command, `caracole fetch --song` from serve's review page too; a lookup sends none);
  - and nothing retries or works around it (no proxies).
- A block a lookup met while bulk work let it go first is that work's too: its client sends nothing more
  (`_LockedClient._after_a_lookup`), and `record_block` adds no strike for a cooldown that began after its caller did,
  as `record_ok` clears none
  (`test_commands_common.py::test_bulk_work_sends_nothing_more_to_a_site_that_blocked_a_lookup_it_let_go_first`).

#### robots.txt

- No URL robots.txt closes is asked for, or followed to (`http.ROBOTS_DISALLOW`, `robots_disallows`):
  - not UG's `/search.php` (matching is local, against the sitemap index), `/tab/download`, `/tab/print?` or
    `/download/public/`;
  - nor gtptabs.com's `/ru/` (half of its sitemaps), `/search/` or `/storage/` (an artist's "Download all" archive);
  - nor musescore.com's `/api/jmuse`, `/score/*/download/*`, `/sheetmusic?` (its search) or `/oembed/*`;
  - nor harptabs.com's `/search`, `/api/` or `/*?*_rsc=`;
  - nor gametabs.net's `/api/`, `/tabs?*` (its filters) or `/preparing-tab-file-download` (every attachment, behind a
    login);
  - nor azlyrics.com's `/search/`, `/suggest/`, `/song/` or `/lyricsdb/` (tests/fixtures/azlyrics/robots.txt);
  - nor i.ytimg.com's `/sb/`;
  - nor, for a link shared to the phone, itunes.apple.com's `/*/lookup?`, `/search*` and `/WebObjects/*`,
    open.spotify.com's `/embed/`, `/download/` and `/local/`, spotify.link's and spotify.app.link's `/_r/`, or
    www.youtube.com's `/results`, `/youtubei/`, `/api/` and the rest of its `User-agent: *` group (tidal.com's and
    tidal.link's close nothing).
- A rule's `$` ends it (`/*.php$`).
- A host's rules are the `User-agent: *` group of its live robots.txt (tests/fixtures/gtptabs/,
  tests/fixtures/musescore/robots.txt, tests/fixtures/harptabs/robots.txt, tests/fixtures/gametabs/robots.txt and
  tests/fixtures/youtube/ytimg-robots.txt, checked by hand on 2026-10-29; tests/fixtures/itunes/, spotify/, tidal/
  and youtube/www-robots.txt on 2026-11-10).
- LaCuerda's robots.txt is empty, and so are LRCLIB's and Megalobiz's API hosts' (none; megalobiz.com's, whose favicon
  caracole asks, closes only accounts and editors: tests/fixtures/megalobiz/robots.txt).

#### A search asks no site

- A search (`caracole search`, `/api/search`) reads the local indexes alone, `lacuerda_index` among them, asks no site
  and takes no lock (`test_web_app.py::test_a_search_asks_no_site_and_takes_no_lock`).
- The exceptions are YouTube's first video for a search, under YouTube's exception below, and LaCuerda's own search
  (`/busca.php`, lacuerda_search.py):
  - sent as a queued job at the lookup pace (`caracole lacuerda --search`), one request;
  - only when the query has settled and its gate allows (`lacuerda_search.gate`, read with no request):
    - a word of four letters;
    - neither your library nor LaCuerda's index answering it well already;
    - not asked within 30 days;
    - no cooldown;
    - the hour's lookups;
    - no failure within the hour;
  - or by hand (its button, or Enter while the gate says `auto` or `button`);
  - at most 20 an hour sent by the pages by themselves within `lookup_per_hour`;
  - each query kept 30 days (kv and the HTTP cache).
- An artist's songs come from their page, read at most once in 30 days.

#### The one exception is YouTube

- The one exception is YouTube, the owner's explicit choice for a handful of their own songs a night: its robots.txt
  closes `/results` and `/youtubei/` to crawlers, and yt-dlp uses both, against its terms too.
- Provider `youtube` (youtube.py) is the one place caracole runs yt-dlp, and only on these terms, for:
  - a song with no human sheet (`todo.songs_to_buy`);
  - or one the owner names with the video to take (`caracole youtube --song`, and its `--sheet`, which the library
    page's sheet from a YouTube video queues as a command: the owner chooses the video and starts it from the page; a
    song with no human sheet, not ignored, no purchase linked, `youtube_sheet.py`);
  - or the first video of a search on the served library page, the owner's explicit choice of 2026-10-29
    (`youtube_search.py`, `caracole youtube --search`, a queued job, never `caracole get`):
    - metadata alone (`ytsearch1:`, `--flat-playlist --dump-single-json`, the query after `--`, `make_youtube`'s
      pauses and lock);
    - its thumbnail from `i.ytimg.com/vi/<id>/hqdefault.jpg` (a `PoliteClient` of provider `ytimg`, right after the
      search with no pause, one request, cached forever, its own cooldown and alert, so that a block of either never
      cools the other, kept in `cache_dir` once `checked_jpeg` reads a JPEG);
    - only for a query with no sheet on the sites;
    - a query once in 30 days (kv `youtube-search:<key>`, which keeps the video for the page);
    - at most `SEARCHES_PER_HOUR` (10) an hour (`events`, runs named `youtube-search:`);
    - none while YouTube cools down, none of a query that failed within the hour, none for the hour once three did;
  - or the metadata of a video pasted into that box, the owner's explicit choice of 2026-10-29
    (`caracole youtube --video`, `youtube_search.read_video`):
    - `--skip-download --flat-playlist --dump-single-json` of the video's plain address after `--`, never a download;
    - under the same gate keyed `video:<id>`, the hour's 10 shared with the searches;
    - its thumbnail as theirs.
- And only where auto-chords can make chords of it (`youtube_fetch.route_problem`: the packages, both model files,
  yt-dlp; the default package never runs it).
- How it runs:
  - within the budget, one run at a time;
  - a pause from `delay` (3.75–7.5 s) between two runs (`YtDlp._pause`, and `_common._pause_after_last_request` via
    `make_youtube`), and yt-dlp's own pauses inside one (`--sleep-requests 0.5`, `--sleep-interval 2.5` to
    `--max-sleep-interval 5` before a download), each a quarter of what it was before 2026-11-03, the owner's choice;
  - `--retries 0`;
  - audio alone (`-x`), never a playlist, the song's name after `--`, arguments a list and never a shell;
  - no cookies, login, config files, plugins (PO-token providers among them) or remote code (`--ignore-config`,
    `--no-cookies`, `--no-cookies-from-browser`, `--no-plugin-dirs`, `--no-remote-components`);
  - an environment of its own (`ytdlp_env`: what a program needs, no `CARACOLE_*` variable);
  - a stop or Ctrl-C stops its process group too;
  - a bot check, an HTTP 429 or 403, a rate limit or a captcha is `ProviderBlocked`, honoured like any block
    (tests/test_youtube.py).
- YouTube's oEmbed for a link shared to the phone (provider `youtube-oembed`, the owner's choice of 2026-11-10) is no
  yt-dlp run and no part of this exception: one request a video, robots.txt honoured (its `/oembed` is open).
- Everything else keeps honouring robots.txt; widen nothing here without the owner, and copy it to no other site.

#### The second exception: a site whose terms forbid automated access, where the owner chose it

- A site's terms against bots, scrapers or copying do not stop caracole at a site the owner chose, named below with
  its terms; the owner's rule, for any site they name here.
- Everything else above binds caracole there, as at every site:
  - robots.txt honoured (its disallowed paths; its `Crawl-delay` is not kept);
  - caracole's own user agent;
  - the paces and budgets;
  - one request at a time;
  - never a login, a file behind one, or an API robots.txt closes;
  - a 403, a 429 or a challenge a block (`ProviderBlocked`, the cooldown, one alert);
  - and nothing worked around (no other user agent, cookies, login, proxies, API keys or captcha).
- The exception is what is kept, never how it is asked for.
- A site joins it by the owner's choice alone, never by analogy.

##### harptabs.com

- Its site terms (2004) say no one may "use, copy, or distribute any portion" of it, and its API's terms ask that its
  tabs not be bulk-mirrored, yet caracole keeps tabs from it.
- Provider `harptabs` (harptabs.py, harptabs_fetch.py) keeps them for the songs of wanted.txt and a lookup's song:
  - never a tab page for a song nobody asked for and never a mirror (its sitemap, then the pages of a song's
    candidates, `CANDIDATES` at most, each read once and cached);
  - one tab a song, privately, in the library;
  - robots.txt honoured (it closes `/search`, `/api/`, `/*?*_rsc=` and more);
  - the bulk pace and budget above, a lookup's at the lookup pace.
- Its artist pages, which robots.txt allows, are read for the names of their tabs alone, never a tab, so that a
  search finds its tabs by artist as UG's index does, the owner's ask (harptabs_index.py: every artist the sitemap
  lists, once in 30 days, at the bulk pace and within a budget; an artist's Songs, one page at the lookup pace).
- An artist's tabs past the 30 a page renders are the site's API's, which caracole never asks for.
- caracole sends harptabs.com its own user agent, as every site
  (`test_harptabs_fetch.py::test_caracole_asks_with_its_own_user_agent`): asked by hand on 2026-10-27 (robots.txt,
  the sitemap and two tab pages: all 200, the sitemap after one Cloudflare 530, an error), it answers it.
- A block there is any site's (`test_pipeline.py::test_a_harptabs_block_cools_it_down_and_marks_no_song`).
- An export (`caracole peer export`, the Sync tab's Export, the phone's) holds what this site gave too, to share as the
  owner likes: the owner's choice of 2026-11-03 ("ignore the privacy, share everything"); caracole itself sends it
  nowhere.

##### gametabs.net

- Its terms (updated 2026-05-25) forbid "Using automated means (bots, scrapers, etc.) to access or collect data from
  the Service without Our express written permission"; the owner chose to read it anyway on 2026-10-28, knowing
  them.
- Its robots.txt allows tab and game pages and the sitemaps, closes `/api/`, `/tabs?*`, the pages behind a login
  (`/preparing-tab-file-download`, every attachment's download, among them) and more, and asks a `Crawl-delay` of
  5 s, which caracole does not keep: its pace is four requests a second (`config.DEFAULT_PROVIDERS`, a quarter of a
  second apart since the owner's choice of 2026-11-03), far quicker than it asks.
- Provider `gametabs` (gametabs.py, gametabs_fetch.py, gametabs_index.py) keeps the text tab each tab page shows to
  anyone, never an attachment (Guitar Pro, MIDI, PDF: a login's), for the songs of wanted.txt and a lookup's song
  alone:
  - never a tab page for a song nobody asked for and never a mirror (its sitemaps, then the pages of a song's
    candidates, `CANDIDATES` at most, each read once and cached);
  - one tab a song, privately, in the library.
- Its game pages, which robots.txt allows (`?page=N` too, which its sitemap lists), are read for each tab's
  composers and instruments alone, never a tab, so that a song is found by its composer, the owner's ask
  (gametabs_index.py: every page the sitemaps list, once in 30 days, at the bulk pace and within a budget).
- Asked by hand on 2026-10-28 with caracole's own user agent (robots.txt, the sitemap index, a child, three game
  pages and two tab pages), it answered each with 200 from a plain nginx; caracole asks it so
  (`test_gametabs_fetch.py::test_caracole_asks_with_its_own_user_agent`).
- A block there is any site's (`test_pipeline.py::test_a_gametabs_block_cools_it_down_and_marks_no_song`).
- An export (`caracole peer export`, the Sync tab's Export, the phone's) holds what this site gave too, to share as the
  owner likes: the owner's choice of 2026-11-03 ("ignore the privacy, share everything"); caracole itself sends it
  nowhere.

##### azlyrics.com

- Each lyrics page says, in a comment above the text, "Usage of azlyrics.com content by any third-party lyrics
  provider is prohibited by our licensing agreement", and it has no terms page caracole found (its `/copyright.html`
  is a DMCA policy, silent on bots); the owner chose to read it anyway on 2026-10-30, knowing that notice.
- Its robots.txt allows artist and lyrics pages and closes its search, so that provider `azlyrics` (azlyrics.py,
  azlyrics_fetch.py) keeps the plain lyrics of the songs of wanted.txt and a lookup's song alone:
  - only where LRCLIB and Megalobiz left none;
  - reached from the artist's page by their name: two requests a song, each cached, no letter page, no index, never
    a mirror;
  - privately in the library, with a link back to the page wherever caracole credits them.
- No pause and no budget, the owner's choice (Bulk work, above).
- caracole sends it its own user agent (`test_azlyrics_fetch.py::test_caracole_asks_with_its_own_user_agent`).
- Its block page is a 200, which `http.is_challenge` knows by its words and the client never caches
  (`test_azlyrics_fetch.py::test_its_block_page_is_never_kept_in_the_cache`), a block as at any site
  (`test_pipeline.py::test_an_azlyrics_block_cools_it_down_and_marks_no_song`).
- An export (`caracole peer export`, the Sync tab's Export, the phone's) holds what this site gave too, to share as the
  owner likes: the owner's choice of 2026-11-03 ("ignore the privacy, share everything"); caracole itself sends it
  nowhere.

##### Spotify and TIDAL, for a link shared to the phone

- Spotify's User Guidelines forbid "crawling" or "scraping", "whether manually or by automated means, or otherwise
  using any automated means (including bots, scrapers, and spiders), to view, access or collect information", and
  TIDAL's Content Guidelines, part of its terms, say the same in the same words (both as a web search quoted them on
  2026-11-10); the owner chose on 2026-11-10 that the phone reads one of their track pages for a link shared to it
  (A shared link read by asking its service once, above), and, told these terms the same day, kept both on ("don't
  turn tidal and spotify off").
- One page a shared link (its short link's hop besides), at a lookup's pace, robots.txt honoured (both open their
  track pages), cached; only the song's two names are read of it, for the share page and a lookup the owner taps.
- Apple's lookup is its documented public API and YouTube's oEmbed a public endpoint for any client; YouTube's terms
  forbid automated access but for search engines by its robots.txt, with its permission or as the law permits, so
  its oEmbed is asked by the same choice of the owner's, one request a video.

#### The cache

- Every accepted 200 and 404 is cached forever, in `cache_dir/http/<provider>/`.

### Errors are never misses

- A block, a spent budget, an HTTP or network error, or a page that won't parse (`PageParseError`,
  `GtpTabsParseError`, `LaCuerdaParseError`, `LrclibParseError`, `MegalobizParseError`, `AzLyricsParseError`,
  `HarpTabsParseError`, `GameTabsParseError`) never makes a song not found, its lyrics missing or its Guitar Pro file
  or harmonica tab a miss: the song waits for the next run.
  - http.py, pipeline.py, provider_pass.py, ug/fetch.py, lyrics.py, megalobiz_fetch.py, azlyrics_fetch.py,
    lacuerda_fetch.py, gtptabs_fetch.py, harptabs_fetch.py, gametabs_fetch.py.
  - `test_pipeline.py::test_ug_block_cools_down_and_never_marks_not_found`,
    `test_fetch.py::test_parse_error_is_not_a_miss`, `test_gtptabs_fetch.py::test_a_spent_budget_is_no_miss`.
- A cached answer that won't parse is asked for once more, past the cache, before it is an error, so a bad night isn't
  replayed every night after: `http.read_once_more` for LRCLIB, LaCuerda, harptabs.com, gametabs.net and gtptabs.com,
  ug/fetch.py's `_get_page` for UG
  (`test_lyrics_pending.py::test_a_cached_answer_that_isnt_json_is_asked_for_once_more`).
- LRCLIB's 503 is its ServerOverloaded, busy, never a miss:
  - `PoliteClient` asks once more after its `Retry-After` (seconds or a date, 30 s at most, within the budget and the
    pace; a host of `http.RETRY_AFTER_503` alone);
  - and a second 503, or one without it, is an error
    (`test_lyrics_pending.py::test_a_503_from_get_is_an_error_and_the_song_waits_never_missing`).
- A song's lyrics are missing only once every site asked answered a miss:
  - LRCLIB's miss;
  - then Megalobiz's (a search with no result that fits, or a record gone, 404), which asks again after 30 days; an
    error there puts a song LRCLIB missed back to pending, and a song LRCLIB failed on is never missing whatever
    Megalobiz answers (`test_megalobiz_fetch.py::test_an_error_on_a_song_lrclib_missed_puts_it_back_to_pending`);
  - AZLyrics the same way, after Megalobiz, its miss a 404 or a page that doesn't list the song
    (`test_azlyrics_fetch.py::test_an_error_on_a_song_the_others_missed_puts_it_back_to_pending`).
- On gtptabs.com only an artist page that answered without a candidate is a miss, asked about again after 30 days.
- On harptabs.com only candidates that all answered, none by the song's artist (or gone, 404), asked about again after
  30 days (harptabs_fetch.py, `test_harptabs_fetch.py::test_a_page_that_wont_parse_is_an_error_never_a_miss`).
- On gametabs.net only candidates that all answered, none whose page is the song's title of its game or composer (or
  gone, 404), asked about again after 30 days (gametabs_fetch.py,
  `test_gametabs_fetch.py::test_a_page_that_wont_parse_is_an_error_never_a_miss`); and of its game pages only one that
  answers 404 loses its tabs (gametabs_index.py).
- On YouTube only a search that answered without a video that fits (youtube_fetch.py,
  `test_youtube_fetch.py::test_an_error_is_no_miss_and_the_song_waits_for_the_next_run`).
- Of LaCuerda's listings only a page that answers 404 loses its artists, never one that errs or won't parse
  (`test_lacuerda_index.py::test_a_page_that_wont_parse_is_an_error_and_its_artists_stay`).
- A page of LaCuerda's search its server cut short (its table or list not closed, its script's arrays missing or
  disagreeing, fewer rows than it counts) is a `LaCuerdaParseError`, never "no results":
  - it records nothing asked (`test_lacuerda.py::test_an_answer_cut_short_is_a_parse_error_never_no_results`);
  - only the failure that keeps the pages from sending it by themselves for an hour
    (`test_commands_lyrics.py::test_lacuerda_search_that_failed_isnt_sent_by_the_page_again_within_the_hour_but_by_hand_it_is`).
- A block or a spent budget exits 0; a bug exits 1, which fires the unit's ntfy alert.

### Slugged tabs only at their slugged URL

- **Slugged tabs only at their slugged URL**, as UG answers 404 for them at `/tab/{id}`: the index keeps each tab's
  sitemap path (`ug_index.path`), from which ug/page.py `page_url` and ug/lookup.py `IndexTab.url` and `tab_url_for`
  build it.
- **Bare-id tabs** (a tenth of UG's, and every tab of an artist with an accented or non-Latin name) are found on the
  artist's UG page (ug/artist.py, the `artist_page` route in ug/fetch.py; every list read kept for searches,
  ug/artist_tabs.py), `/artist/<name>_<id>` or `/artist/<id>` (`overrides.artist_page_address`):
  - its URL from `[artist_url]` or learned from a tab page into kv `ug:artist_url:<artist key>`;
  - an `[artist_url]` tab page is read once, through the run's client, for the page it links to: kv
    `ug:pasted_tab:<tab id>`;
  - one that won't parse waits as any tab page does, kv `ug:unreadable:<tab id>`.
- `test_fetch.py::test_slugged_tabs_fetched_at_their_slugged_url`,
  `::test_bare_id_chords_of_a_matched_song_come_from_its_artist_page`, tests/test_live_banma.py.

### Guitar Pro: gtptabs.com's downloads and the inbox, never Ultimate Guitar's

- The index keeps UG's chords, text tabs and ukulele chords alone (ug/sitemap.py `KEEP_TYPES`): a Guitar Pro or Power
  Tab file's tab is counted by type and left out, so no song matches one and no page, search, count or link shows one
  (`test_index.py::test_guitar_pro_and_power_tab_files_are_counted_by_type_and_left_out`).
- ug/page.py gives UG's `Pro` and `Power` types no kind (`KINDS`: chords, tabs, ukulele), so ug/fetch.py never rates,
  records or picks such a version, never reads an artist page's lists of them, and a `[pin]` of one pins nothing
  (`test_fetch.py::test_a_pin_ultimate_guitar_answers_with_a_guitar_pro_page_pins_nothing`,
  `::test_artist_page_kinds_fill_the_tab_slot_and_its_guitar_pro_lists_are_never_read`).
- `caracole get --tab` refuses a page whose address names another type before writing anything
  (`test_get.py::test_a_page_of_another_type_asked_for_as_the_tab_is_refused_and_nothing_is_written`).
- inbox.py files what the user drops into `_inbox/` by its name, for any song not ignored, as the song's lowest free
  `guitar-N`, under its own `inbox` version of the file's kind (`test_inbox.py::test_files_into_song_by_name`).
- Official and non-public versions are never used.
- gtptabs_fetch.py downloads from `/tabs/download/{id}.html` alone, never logged in:
  - one file for a song with no Guitar Pro or Power Tab file in `files` (filed or downloaded, deleted since or not);
  - and keeps it only when `gtptabs.sniff` reads a Guitar Pro or Power Tab header: as the lowest `guitar-N` no file
    holds (`inbox.guitar_number`), with its version (provider `gtptabs`).
  - It never replaces or deletes a file (`test_gtptabs_fetch.py::test_a_song_with_a_guitar_pro_file_gets_no_other`,
    `::test_a_number_a_file_in_the_folder_holds_is_never_reused`).

### MuseScore is links and the inbox

- musescore_fetch.py asks MuseScore for its song sitemaps alone: never a song page, a score, a download or
  `/api/jmuse`, and never logged in (`test_musescore_fetch.py::test_caracole_asks_for_the_sitemaps_alone`).
- Its Cloudflare challenge is a block like a 403, and the to-do page then says plainly that MuseScore is blocking
  caracole, even with no page to list (`todo._musescore_pages`).
- Every match is on the title alone, a possible match (`musescore.song_pages`).
- inbox.py files what the user downloads (`SCORE_EXTENSIONS`) as `score-N.<ext>`, never as `sheet.pdf`, under the
  song's one `inbox` version of kind `score`.
- A MusicXML header is read with `musicxml.header`, up to the part list only.

### Chinese is compared as pinyin

- Chinese is compared as pinyin (`normalize.romanize`, with pypinyin) in match.py, coverage.py, music.py, search.py,
  library_page.py, ug/fetch.py, ug/artist_tabs.py (its forms) and lacuerda_index.py (whose keys are pinyin).
- Identity keys also fold Traditional characters to Simplified.
- Where a name caracole didn't write meets yours (UG's artist pages and slugs, LaCuerda's listings, purchases' tags,
  downloads), it is compared by `normalize.name_forms`, which also gives the parts of a name in two scripts ("Song
  Dongye (宋冬野)"); forms are for comparing and never make a key.
- **A key changed**: a change to `clean_title`, `slug_key` or `identity_key` that can change a key bumps
  `normalize.KEY_VERSION`: `songs.ensure_current_keys`, run before songs are looked up, listed or added, then re-keys
  them once and merges those that now share a key.
  - It re-keys `songs` and the tombstones of removed songs (`removed`, `songs._rekey_removed`) only.
  - `ug_index` keys change when a sitemap is parsed again.
  - The keys of a table site_index.py fills (`gtptabs_index`, `musescore_index`, `harptabs_index`, `gametabs_index`)
    at its next refresh, which parses every sitemap again, an unchanged one from the cache
    (`test_gtptabs_fetch.py::test_new_keys_read_the_sitemaps_again_even_when_they_are_unchanged`).
  - `harptabs_index`'s, after a change to how harptabs.py keys a slug alone (`harptabs.joined`: a tab's
    `can-t-help-…` is `cant-help-…`), from the paths it holds, with no request, before the step, a lookup or the
    artist pages' pass (`harptabs_fetch.ensure_current_keys`, `ROW_KEYS`).
  - `lacuerda_index` keys are made again from the names it stores, with no request
    (`lacuerda_index.ensure_current_keys`, at its next refresh or store).
  - So are `ug_artist_tabs`' keys and forms (`artist_tabs.ensure_current_keys`, at its next store or backfill, which
    the match step and every lookup call).
  - And `gametabs_game_tabs`' title keys from their titles (`gametabs_index.ensure_current_keys`, before the step, a
    lookup or a game pass).
- Name new per-song kv keys `<prefix><song id>` (or `<prefix><song id>:<more>`) and add the prefix to
  `songs._PER_SONG_KV`, so a merge or a removal deletes them (`songs.delete_song_kv`).

### A removed song stays removed until you ask for it again

- `caracole remove` (removal.py):
  - takes the song's lines out of wanted.txt first, and stops before anything else when the file can't be read;
  - then, in one savepoint, leaves its tombstone (`songs.mark_removed`: table `removed`, its key, name and source ids)
    and deletes its record (versions and files cascade), its per-song kv and its lines' `wanted:first_seen:`;
  - then the files caracole wrote.
- `songs.upsert_song`, the one way a song is added, is given wanted.txt lines alone (`caracole add`, the web page, a
  line typed):
  - a line for a removed song asks for it again, so its tombstone (found by source id or by key) goes and the song
    comes back new;
  - or the line finds the song of that key the library has (after a re-keying).
- Nothing else may create a song
  (`test_removal.py::test_the_next_sync_brings_nothing_back_until_you_ask_for_the_song_again`,
  `test_songs.py::test_a_wanted_line_brings_a_removed_song_back_as_new`).

### Schema changes go through db.py

- Bump `SCHEMA_VERSION` and add the script to `_MIGRATIONS`.
- A trigger states no conflict clause: an upsert's `DO UPDATE` aborts on a conflict in any trigger it fires, whatever
  `OR IGNORE` says, so a trigger looks up what it would repeat (schema 14,
  `test_index.py::test_a_tab_renamed_to_a_new_key_of_words_the_index_knows_is_stored`).
- `_migrate` copies an existing database to `caracole.sqlite.v<N>.bak` (`VACUUM INTO`, under a name of its own, then
  renamed), then runs each script in one `BEGIN IMMEDIATE` transaction with its `PRAGMA user_version` (a script never
  begins or commits one itself).
- One connection migrates at a time, of every thread and process (an flock on `caracole.sqlite.migrating`, the version
  read again under it:
  `test_db.py::test_connections_opened_at_once_migrate_once_and_each_opens_the_database`).
- A newer database raises `DatabaseTooNew`, and `_common.open_db` exits 2 (tests/test_db.py).
- Writes that apply whole or not at all go in `db.savepoint(conn, name)`, which nests in a caller's: the connection is
  in autocommit mode, where `with conn:` opens no transaction
  (`test_db.py::test_a_savepoint_undoes_its_whole_block_and_nests`, tests/test_versions.py).

### overrides.toml and songbooks.toml

- **overrides.toml** is written only through the `add_*` functions of overrides.py: tomlkit, so the user's comments
  and layout survive, then `library.write_atomic`.
- It is read only as a regular file (`test_overrides.py::test_writers_preserve_comments_and_roundtrip`).
- So is **songbooks.toml**, through the writers of songbook.py (`make_songbook`, `add_to_songbook`, ...): a file that
  won't parse is a `SongbookFileError`, which stops the songbooks and nothing else
  (`test_songbook.py::test_writers_keep_comments_and_layout`,
  `test_songbook_render.py::test_a_broken_songbooks_file_is_an_error_that_stops_nothing_else`).

### The library is synced

- Syncthing and every device can write to it.
- Read a file there with `library.read_regular` (or `open_regular`: no symbolic link followed, regular files only):
  - `dir_fd=` for a name in a folder opened without following a link, as inbox.py reads `_inbox/`;
  - `read_text` for its text, any failure the caller's error naming the file, as overrides.py and songbook.py read
    theirs;
  - `read_json` for its JSON, where whatever a device wrote is a ValueError at worst, never the RecursionError that
    would stop a pass over every song, as it is an `OverridesError` or a `SongbookFileError` in overrides.toml or
    songbooks.toml.
- Write one with `library.write_atomic`: a random temporary name opened exclusively, then a rename. Never `mkstemp`,
  whose mode 0600 hides files from Syncthing.
- Nothing private or bulky goes there: the database, the lock, caracole serve's request history (`requests.jsonl`,
  0600), the HTTP cache and the audio taken from YouTube (`cache_dir/youtube/`, youtube_fetch.py) stay in `state_dir`
  and `cache_dir`, and chordpro works on a copy in a 0700 folder under the cache (render.py).
  tests/test_library_safety.py.
- A removal deletes only what caracole wrote in the song's folder, by name, through descriptors opened with
  `O_NOFOLLOW` from the library down, and names everything it leaves:
  - `removal._caracoles`: kept files, the outputs of a kept sheet (its Traditional PDF among them) or of a render
    record, its exports, a version's or a harmonica tab's page `render:files:` records, LRCLIB's lyrics, info.json;
  - it never touches Music/, and deletes the song's audio taken from YouTube from the cache (tests/test_removal.py).

### One caracole at a time

- `_common.exclusive` holds an flock on `state_dir/caracole.lock`, re-entrant within a process, and the clients of
  `make_client` and the yt-dlp runner of `make_youtube` hold it until closed.
- Every command that asks UG, LRCLIB, LaCuerda, gtptabs.com, MuseScore or YouTube for pages or writes the library
  takes it.
- `search`, `match --dry-run`, `index stats`, `remove --list`, `songbook list`, `songbook show`, `versions` (the list
  alone), `backup --list`, `index export` and `peer export` (one read transaction each) only read and never wait.
- `add` writes its wanted.txt line first, and a `--lacuerda` pick (overrides.toml is in the library) only once it holds
  the lock, failing when the lock file can't be opened
  (`test_commands_sources.py::test_add_with_lacuerda_writes_no_pick_without_caracoles_lock`).
- `review` and `remove` take it only after their questions (commands/library.py, commands/remove.py), so the nightly
  run never waits for an answer (`test_commands_lock.py::test_review_never_holds_the_lock_while_it_waits_for_you`,
  `::test_remove_never_holds_the_lock_while_it_asks`).

#### A lookup never waits behind a whole nightly run, and still never writes beside it

- `exclusive(..., interactive=True)` announces it in `state_dir/caracole.lock.waiting/`:
  - a file per waiting process, touched every `TICKET_BEAT` s while it tries for the lock, and dropped once it holds
    it;
  - one its process left, or untouched for `TICKET_STALE` s, a lookup killed while it waited, no longer counts.
- `caracole versions --keep`, `--keep-more` and `--clear` (which writes overrides.toml under it) wait so too, and
  `--choose` through get.
- Every changing `caracole songbook` command (make, add, remove, move, set, rename, delete, render:
  commands/songbook.py) waits the same way, as a songbook is asked for now
  (`test_commands_songbook.py::test_a_change_waits_for_the_nightly_run_as_a_lookup_does_never_for_its_whole_run`).

#### Bulk work hands the lock over

- Bulk work hands the lock over (`_common.hand_over`, never inside a transaction): it lets go of the flock, takes it
  back once the lookup is done, counts the handoff (`_common.handoffs()`), and goes on.
- That count is how everything below learns a lookup went first (a client's block and pace checks, the re-reads of
  songs and overrides.toml): it is the one way to let go of the lock mid-work.
- It hands it to lookups alone: meanwhile it holds the flock of `state_dir/caracole.lock.handoff`, and a caracole that
  isn't a lookup lets go of a lock it took during a handoff and waits for it to end (`_common._take_outside_handoffs`),
  so a `caracole-admin` command waiting for the run takes the lock after it, never in its middle
  (`test_commands_common.py::test_the_nightly_run_hands_the_lock_to_a_lookup_alone_never_to_another_command_waiting`).
- It does so in two places:
  - Its clients, and the yt-dlp runner of `make_youtube` between two runs, spend each pause looking for a waiting
    lookup (every `HANDOFF_SLICE` s), then pause a whole `delay` again
    (`test_commands_common.py::test_the_youtube_steps_pauses_hand_the_lock_to_a_waiting_lookup_too`).
  - Work that sends no request does it between two songs (a `between` callback): `autochords_pending`
    (commands/autochords.py) and `render_all` (pipeline.py's render step, commands/render.py).
- A bulk caller holding state across a handoff re-reads it after one:
  - ug/fetch.py `fetch_songs` reads each song and overrides.toml again (`_Handoffs`; a song a lookup fetched mid-turn
    is fetched again next run);
  - lacuerda_fetch.py `lacuerda_sheets` reads each song and overrides.toml again and passes over a song no longer to
    try (`_Lookups`; after a handoff within a song's turn, it records what LaCuerda answered only for a song still to
    try with the pick the turn asked for:
    `test_lacuerda_fetch.py::test_a_tab_a_lookup_pinned_during_the_songs_own_turn_is_never_replaced`);
  - gtptabs_fetch.py checks a song still has no file before its turn;
  - and `autochords_pending` and `render_all` read each song after and overrides.toml again;
  - what comes after reads overrides.toml again too (`_common.overrides_since`): the run's next steps,
    `StepContext.read_overrides_again`; the songbooks and pages of `caracole render` and `autochords`; the pages of
    `caracole fetch`, `youtube`, `icons` and commands/lyrics.py's `_provider_pass`.
  - `test_lacuerda_fetch.py::test_a_tab_a_lookup_pinned_during_an_earlier_step_is_never_replaced_by_lacuerda`,
    `test_commands_common.py::test_the_nightly_run_hands_the_lock_to_a_lookup_during_its_pause`,
    `test_autochords_run.py::test_a_lookup_waiting_for_the_lock_takes_it_between_two_songs`.

#### `serve` never takes it

- It reads like `search` and appends to wanted.txt like `add`, and runs every other change as a `caracole` command in
  a child process, one at a time (web/jobs.py), since the lock is re-entrant within a process and its threads would
  share it.
- A removal too, `caracole remove --yes`, once the line's five seconds with Undo are over (the library page's script;
  without it, a page of its own), having asked what goes (`removal.plan_removal`, which only reads, and
  `removal.brief`); its job's song key is `remove:<key>` (`jobs.REMOVING`), so it never joins the song's add or fetch.
- Beyond wanted.txt, the one thing it writes is its own request history, `state_dir/requests.jsonl`
  (web/history.py), no table of caracole.sqlite:
  - a file no command reads or writes, whose one writer is caracole serve's queue, under the queue's own lock
    (`JobQueue._save`), so it needs caracole's lock no more than wanted.txt does, and the database keeps its rule that
    every change to it is a caracole command's;
  - a line a request appended in one write as it changes;
  - written again whole (a temporary file, synced, renamed over it) when it starts and when it grows past three lines
    a request kept or `MAX_BYTES`;
  - a line it can't read skipped;
  - the last `jobs.KEEP` (100) requests of `DAYS` (30) read back, the next ids after theirs, one that waited or ran
    then `INTERRUPTED`, as is one the server ends as it stops (`JobQueue.stop`): over, Try again queues it
    (test_web_history.py).
- It also writes, for the phone's sync alone, and nothing else: a push's staging folder (`state_dir/peer/push-<id>/`,
  0700, its files checked by their SHA-256, deleted once `caracole peer take` is over or an hour after); a
  temporary index export for `GET /api/peer/index` (`cache_dir/peer/`, one read transaction, no lock, deleted once
  sent); and the index pages a phone's lookups read, `POST /peer/index`'s export of them
  (`state_dir/peer/index-<16 hex>.sqlite`, 0600, at most `peer_push.INDEX_OPEN` waiting, read before its 202 as an
  export of pages alone of this caracole's version, `index_transfer.check_pages`, deleted when it isn't, then
  `caracole index merge --delete --progress` queued, which deletes it once merged or refused, and `--delete` deletes
  a refused file of that staging alone, never one named by hand; one an hour old no waiting request names is swept,
  `peer_push.sweep_indexes`).
- And for Export and Import a file (sync_file_routes.py), nothing else: an export's file
  (`cache_dir/peer/export-<16 hex>.caracole`, 0600, one made at a time, its units from one read transaction and its
  indexes from one of their own, no lock; one waits to be sent at most, the one before it deleted as the next is made;
  deleted once it is open to be sent, or an hour after if never asked, a part a killed process left swept only while
  no export is made); and a file to import's staging folder (`state_dir/peer/import-<16 hex>/`, peer_import.py:
  0700, its `file.caracole` and `open.json` 0600, one at a time, each part 8 MiB at most and the next one, 8 GiB in
  all), deleted once its import is over, refused at its comparison, dropped (`POST /sync/import/drop`), let go as
  another is opened when no request names it and it is whole or its upload stopped (`peer_import.let_go`,
  `STOPPED`), or an hour after its last part, unless an import holds it. Everything else stays a queued command's.

### wanted.txt is the one source of songs

- `sources.sync_sources` syncs it alone, and a song's album, duration, ISRC and variant are what its line says now,
  kept in its record alone (`songs.upsert_song`;
  `test_songs.py::test_a_song_keeps_what_its_line_says_in_its_own_record_alone`).
