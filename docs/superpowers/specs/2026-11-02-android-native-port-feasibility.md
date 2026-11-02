# caracole on Android in Kotlin, without Termux: what it takes

The question (2026-11-02): rather than run the Python caracole on the phone, port these features alone, in Kotlin or
mostly so: looking up songs from an index, indexing, syncing with other caracoles, songbooks, and sheets with what
they do (scrolling, music theory, the harmonica and guitar overlays). Then: what else could come along.

## Verdict

Feasible, and the most useful split is not by feature but by layer:

- **Everything a page does on screen is already JavaScript** and needs no port: the sheet viewer (viewer.js,
  overlay.js, harptab.js, strum.js, instruments.js, winds.js, book.js: ~5,300 lines, scrolling, transposition,
  overlays, sound, settings) and the library page (library_assets/: ~9,500 lines of JS, CSS and HTML: search box,
  rows, cards, songbooks tab, requests tab). A WebView runs them as they are; the app already does for its offline
  copy.
- **What has to be written in Kotlin is what feeds them**: the data a viewer page carries (music theory tables,
  chord shapes, harps, pinyin, readings of harmonica tabs), the answers caracole serve gives the pages (search,
  lookups, songbooks, jobs), the site clients, and sync. That is roughly 25–30k lines of Python today; Kotlin of the
  same logic is about as long.
- **What can't come along natively**: ChordPro's PDFs (a Perl program), auto-chords (torch models) and anything
  YouTube (yt-dlp). Each has a fallback below.

The hardest single piece is not a site or sync but the viewer's data: music theory, harmonica-tab reading and
Chinese readings, which must agree with the Python caracole to the byte (below, Keeping two caracoles in step).

## The shape of the app

- **One Kotlin core** (no Android dependency, testable on the JVM as android/mirror is): the database, identity keys,
  search, the site clients, indexing, sync, songbooks, the page builder.
- **The same SQLite schema as caracole's** (db.py, schema 15), in a bundled SQLite: stock Android's has no FTS5 (none
  documented, and community reports agree), and search needs FTS5 with its trigram tokenizer (`ug_keys_fts`,
  `ug_artists_fts`, `ug_index_fts`). Bundle SQLite built with `-DSQLITE_ENABLE_FTS5` (sqlite.org's Android bindings
  document the switch); whether androidx's `sqlite-bundled` enables it is unverified (`pragma compile_options` on a
  device answers it). The same schema means an `index export` file, an SQLite file, merges with plain SQL.
- **caracole serve's routes in Kotlin, on 127.0.0.1** (a small embedded server, e.g. Ktor CIO or NanoHTTPD), which
  the existing pages talk to as they talk to caracole serve today. Not `shouldInterceptRequest` alone: a WebView
  gives an intercepted request no body, and the pages post forms (lookups, songbooks, sync). caracole serve has ~40
  routes; the five features need about 25 of them. Its security rules come along: the form token, the host check,
  `own_page_read`.
- **Jobs**: caracole serve runs each change as a `caracole` command in a child process and the pages poll
  `/jobs.json`. In the app a job is a coroutine on one queue; one process holds the database, so caracole's flock
  and its handoffs to lookups reduce to a mutex.

## Feature by feature

### 1. Looking up songs

Two halves, which the pages already keep apart.

**Searching the indexes** (search.py, ug/key_search.py, normalize.py, song_names.py: ~3,100 lines). Reads SQLite
alone. Needs:
- FTS5 with trigrams (above).
- rapidfuzz: caracole uses `fuzz.ratio` (36 calls), `fuzz.token_sort_ratio`, `fuzz.partial_ratio_alignment` and
  `process.extract`. Port these few exactly (an Indel-distance ratio, ~200 lines) rather than take a fuzzywuzzy port
  whose scores differ: the thresholds were tuned on rapidfuzz's.
- `normalize.romanize` (Chinese compared as pinyin) uses pypinyin's `lazy_pinyin`. There is no Kotlin pypinyin; the
  closest Java libraries (pinyin4j, TinyPinyin) read characters alone, not words, so polyphones differ. Port its
  phrase matching and ship its dictionaries as an asset (a few MB), or accept looser matches for Chinese.

Verdict: feasible, medium.

**Looking a song up now** (`caracole get`: get.py, match.py, ug/*, rank.py, coverage.py, versions.py,
sheet_versions.py, the lyrics sites, LaCuerda, gtptabs.com, harptabs.com, gametabs.net, MuseScore: ~8,700 lines),
plus the politeness it runs under (http.py, health.py, config.py, the lookup pace of commands/_common.py: ~1,800).
- httpx → OkHttp; selectolax → jsoup; JSON → kotlinx.serialization. Every site is HTML or JSON over HTTP: nothing
  needs a browser or a native library.
- The invariants come along whole: robots.txt, budgets per run and per hour, the pace, one request at a time, a block
  as a cooldown with no retry, errors that are never misses, the cache of 200s and 404s. Each has a test in the
  Python suite to port with it.
- Breadth is the cost, not difficulty: seven sites, each with its parser and its rules.

Verdict: feasible, large. UG and lyrics first; the others one at a time.

### 2. Indexing

ug/sitemap.py, ug/index.py, site_index.py, lacuerda_index.py, harptabs_index.py, gametabs_index.py,
index_transfer.py: ~2,600 lines. Streaming XML and HTML, and SQL: feasible in Kotlin, medium.

But building UG's index on a phone is the wrong job for it: days of polite requests, 1.6 million rows, a database of
about 430 MB. Better:
- **Import the computer's** `caracole index export` file and merge it (index_transfer.py's rules are SQL over
  ATTACHed tables: a small port).
- **Carry it in sync**, which doesn't do it yet: a `GET /api/peer/index` that streams the export, merged at each sync.
- Refresh on the phone only what is cheap (a LaCuerda artist's page, a harptabs.com artist page), or nothing.

### 3. Syncing with other caracoles

peer_sync.py, web/peer_routes.py, commands/peer.py: ~1,000 lines, and the protocol is already HTTP and JSON. Feasible,
medium. Three things to settle first:

- **Digests must come out the same in both languages.** Today a unit's digest is the SHA-256 of Python's
  `json.dumps(sort_keys=True, separators=(",", ":"), ensure_ascii=False)`. Kotlin must reproduce it byte for byte:
  key order, escapes, and floats (Python writes `0.8333333333333334` and `1e+16`; Java and Kotlin print doubles
  their own way). Write the canonical form down as a spec, with test vectors.
- **A version's `raw` is hashed as stored text**, so the same tab fetched by each side, serialized by each
  language, would differ. Hash it canonicalized (parsed, then written canonically): a small change on the Python side
  first.
- **Identity keys must agree to the character**: sync names every song `song/<identity key>`. They don't depend on
  pypinyin (`identity_key` uses caracole's own folding and its own Traditional-to-Simplified table, which are data
  to copy), but they do use Unicode normalization, whose tables differ between Python's Unicode version and the
  phone's ICU for the newest characters. Test vectors catch it.
- **Who calls whom.** Today each side pulls, so the computer must reach the phone's server to take its changes. On a
  phone it is simpler to start every sync from the phone: it pulls, then pushes its own units to a new
  `POST /peer/push` on the computer (with the form token, as every write). The phone then serves nothing to the
  network, only to its own WebView.

### 4. Songbooks

songbook.py, songbook_section.py, viewer/book.py: ~1,400 lines, and book.js and songbooks.js reused.
- The set lists, their order and each song's setting (key, mode, capo, instrument): feasible, small to medium.
  `with_capo` and `on_instrument` need version.py's theory (feature 5).
- songbooks.toml written with its comments kept (tomlkit) matters only for a file you edit by hand. The phone can
  keep songbooks and overrides in SQLite: sync moves units, not files.
- A songbook's page is the viewer's (feature 5). Its PDF and `songbook.cho` are ChordPro's: see Missing, below.

### 5. Sheets and what they do

The viewer's JavaScript is reused unchanged: scrolling, transposition, capo, modes, the guitar and harmonica
overlays, the Harmony panel, strumming, instruments, pinyin over the words, Simplified and Traditional. What Kotlin
must make is each page's data, today viewer/*.py with chordpro.py, keys.py and progressions.py (~8,900 lines):

| Part | Python | Kotlin |
|---|---|---|
| A UG or LaCuerda sheet read (chordpro.py, viewer/sheet.py) | ~1,000 | parsing, mechanical |
| Theory, keys, versions (theory.py, keys.py, version.py) | ~1,500 | pure logic, mechanical |
| Harmony and its tables (harmony.py, harmony_tables.py, progressions.py) | ~1,400 | pure logic; the catalogue of progressions is data |
| Chord shapes (voicings.py, instruments.py; voicings.json and voicings-ukulele.json, 84k lines of data) | ~500 | the JSON files as assets; the piano computed |
| The harmonica (harp.py, harpfit.py) and the winds (winds.py) | ~870 | pure logic |
| Harmonica tabs read (harptab.py, harptab_page.py) | ~1,900 | the hardest: notations as data, readings weighed |
| Pinyin (pinyin.py: pypinyin in context) | 61, plus pypinyin | pypinyin's dictionaries and phrase matching ported |
| Simplified and Traditional (hanzi.py: OpenCC) | 108 | opencc4j: pure Java, Apache-2.0 (its output against OpenCC's to check) |
| The page itself (page.py: the data assembled, the scripts inlined by their hashes) | ~900 | mechanical |

Verdict: feasible, the largest piece (extra large). The phone can start without it: pages synced from the computer
already arrive rendered, and only songs looked up on the phone need the builder.

## Keeping two caracoles in step

Two implementations of the same theory drift unless a test holds them together. caracole already does this between
Python and JavaScript (test_viewer_version.py, test_viewer_numerals.py). Do the same for Kotlin:
- a conformance corpus the Python suite writes: inputs (sheets, names, harmonica tabs, search queries, sync units)
  and Python's outputs (page data JSON, identity keys, search results, digests);
- the Kotlin tests read the same files and must match them exactly;
- a change on either side regenerates or fails the corpus.

Without it, a song can read in one key on the phone and another on the computer, or sync can see a song twice.

## What you didn't list, and whether it can come

| Feature | Feasible? | How |
|---|---|---|
| Lyrics (LRCLIB, Megalobiz, AZLyrics) | yes, small to medium | part of a lookup: JSON and HTML over HTTP |
| PDFs: a sheet's, Export PDF in a version, a songbook's | not as ChordPro makes them | print the viewer page to PDF with Android's print framework (`WebView.createPrintDocumentAdapter`): small, but it looks like the page, not ChordPro's two columns |
| Guitar Pro files drawn and played (alphaTab) | yes, small | alphaTab is JavaScript: ship its bundle as an asset |
| Guitar Pro files from gtptabs.com, harmonica tabs from harptabs.com, game tabs from gametabs.net, MuseScore links | yes | part of a lookup and of indexing |
| The library page whole: filters, cards, the Sites tab, the Requests tab | yes, medium | its JavaScript reused; the routes behind it in Kotlin |
| Sheet versions: Keep it, Make this the one, Make this my version | yes, medium | part of a lookup, and overrides in the database |
| Review of an uncertain match | yes, small | a page and the matcher |
| Add, remove, and removed songs staying removed | yes, small | needed for sync anyway |
| Files shared to the app (Guitar Pro, scores) as `_inbox/` files them | yes, small | Android's share intent |
| A nightly run on the phone | yes, but don't | WorkManager can, but the computer does bulk work, so the sites see one caracole |
| Alerts | yes, small | Android notifications in place of ntfy |
| Backups | yes, small | `VACUUM INTO`, as backup.py |
| Auto-chords from audio | no, in practice | the models would need converting (ONNX Runtime or ExecuTorch) and librosa's features rewriting in Kotlin: a research project |
| YouTube: a search's first video, a pasted video, a sheet from a video | not natively | no yt-dlp in Kotlin; NewPipeExtractor (Java, GPL-3.0) can read YouTube, but a sheet from a video needs auto-chords, and the owner's YouTube exception would have to cover it |
| Music/ purchases scanned | possible, little use | MediaStore in place of mutagen; it only feeds auto-chords |
| The to-do page, `_todo.md` | possible, little use | the library page says the same |

## An order that pays off early

1. **The core, identity keys and the schema**, with the conformance corpus; the computer's index imported; search
   answered by the reused library page. The phone searches with the computer off.
2. **Sync started from the phone**: pull, and push to `POST /peer/push`. The 20 songs you change on the computer
   reach the phone rendered, and come back.
3. **Lookups**: UG first, then lyrics, LaCuerda and the rest, each with its politeness and its tests. Songs looked up
   on the phone show their sheet as text until step 4.
4. **The page builder**: theory, harmony, shapes, harps and winds first; harmonica tabs, pinyin and Traditional
   after. Every sheet then plays on the phone as on the computer.
5. **Songbooks**, then **PDFs by printing**, then the rest of the table above as wanted.

## Not verified here

- Which SQLite build to bundle, and that FTS5 with trigrams runs in it on a phone (`pragma compile_options`).
- opencc4j's output against OpenCC 1.4.1's on caracole's sheets (the corpus would show it).
- How long a page build takes on a phone: harmony tables are computed for every transposition and mode.
- Ktor's or NanoHTTPD's footprint and start-up time in an app.

Sources consulted: [androidx sqlite-bundled build file](https://android.googlesource.com/platform/frameworks/support/+/f66fa79d19e5874f0afaa6868363c69ecf851cf2/sqlite/sqlite-bundled/build.gradle),
[SQLite Android bindings](https://sqlite.org/android/info/985ad0e6f280e048),
[CommonsWare on Room and FTS](https://commonsware.com/Room/pages/chap-roomfts-001),
[B4X forum on FTS5 on Android](https://www.b4x.com/android/forum/threads/sqlite3-fts5.110369/),
[opencc4j on Maven Central](https://mvnrepository.com/artifact/com.github.houbb/opencc4j/versions),
[android-opencc](https://gittrend.io/repo/qichuan/android-opencc),
[Android Request Inspector WebView](https://github.com/acsbendi/Android-Request-Inspector-WebView),
[android-post-webview](https://github.com/josketres/android-post-webview).
