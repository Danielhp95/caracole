# caracole on Android in Kotlin: milestones 1–3, the implementation plan

Status: the plan for this round, revised after two critiques (completeness, executability); §12 says what each
critique changed and where the plan declines a fix. The skeleton step commits it as
`docs/superpowers/plans/2026-11-03-android-port-m1-m3.md`, and every lane brief points here.

The plan to share is [docs/android_port.md](../../android_port.md). Its research is
[2026-11-02-android-native-port-feasibility.md](../specs/2026-11-02-android-native-port-feasibility.md). The sync
protocol is [2026-10-31-phone-server-sync-design.md](../specs/2026-10-31-phone-server-sync-design.md); its phases 1
and 2 are built in `src/caracole/peer_sync.py`, `web/peer_routes.py` and `commands/peer.py`. The patch
`~/Downloads/caracole-android-sync.patch` is already applied: its 13 commits are main's `7d6f679..4b5568b`. Nothing
is applied again.

Contents:
1. Scope and decisions
2. Architecture
3. The conformance corpus
4. Canonical JSON and sync FORMAT 2
5. Interfaces (Kotlin, HTTP, storage, threads)
6. The skeleton
7. The lanes (7.0 how a lane works, 7.1 each lane)
8. Order
9. Integration
10. Risks
11. Open questions
12. What the critiques changed

---

## 1. Scope and decisions

This round is milestones 1–3 of docs/android_port.md:

1. **Foundations.**
   - A Kotlin core holding caracole's schema in a bundled SQLite with FTS5.
   - Identity keys, canonical JSON and digests.
   - The conformance corpus: the Python suite writes it and the Kotlin suite reads it.
2. **Search with the computer off.**
   - The phone imports the computer's `caracole index export` and merges it.
   - The phone's local server answers the library page's read routes.
   - The library page's own JavaScript runs unchanged.
3. **Sync from the phone.**
   - The Kotlin sync engine.
   - On the computer: `POST /peer/push` and canonical hashing (sync FORMAT 2).
   - The Sync tab of the library page, in JavaScript, serving both sides.
   - The mirror keeps the phone's own songs beside the computer's pages.

Out of this round, with room left for them:
- lookups on the sites (M4);
- the page builder (M5);
- songbooks, PDFs and alphaTab (M6).

Their routes answer "not on the phone yet". The seams they will fill are already here: `SongCards`, `PageData`, the
job queue's kinds, and the state document's room for `cooldowns`.

### The owner's decisions (settled)

- Native Kotlin. Nothing on the phone needs Python, Termux or Chaquopy.
- The phone's local server listens on 127.0.0.1 and needs a random secret, made at each launch.
  - The app sets the secret as a cookie in the WebView, and the server checks it on every request.
  - The host check, the form token, the cross-origin checks and each page's CSP all come along unchanged.
- The phone starts every sync. It pulls what it takes, then pushes what the computer takes to `POST /peer/push`,
  with the form token as on every write. The phone serves nothing to the network.
- The computer builds the site indexes. The phone imports `caracole index export` files and merges them, and never
  refreshes an index in bulk.

### The planner's decisions

Each one is open to the owner. Those that most need the owner are §11.

| Decision | Choice | Why |
|---|---|---|
| SQLite | `androidx.sqlite:sqlite-bundled:2.7.1`: SQLite 3.50.1 with FTS5, on the JVM and on Android | The spike ran all 15 migrations with an identical `sqlite_master`. Trigram LIKE, unicode61 MATCH, fts5vocab, json1 and ATTACH work. The Android ABIs carry the same source id and the same 52 compile options. |
| JDK in `android/flake.nix` | `jdk17_headless` | The full `jdk17` links gtk3, which pulls in nixpkgs' libsqlite3 3.53.3, and that library silently interposes the bundled library's `sqlite3_*` symbols. A test asserts `sqlite_source_id()`. |
| Connections | One writer connection under `Database.writes`; reads take a pooled connection for one blocking block; every connection sets `busy_timeout` (§5.5) | The bundled SQLite is THREADSAFE=2, so a connection is never shared by two threads at once. Ktor CIO answers on several threads. |
| HTTP server | Ktor 3.3.3, CIO engine | The last Ktor built on Kotlin 2.2.21 and coroutines 1.10.2. It keeps the raw request target and every header, and adds about 750 KB after R8. NanoHTTPD decodes `%2F` in paths, so it is out. |
| JSON | kotlinx-serialization-json 1.9.0 for documents. A hand-written strict parser and writer for canonical hashing (§4) and for `kv` text (`PyJson`) | Hashing must accept exactly what Python's `json.loads` accepts, and `kv` text must be `json.dumps`'s bytes. |
| Port | 8738 preferred, else an ephemeral port | A fixed origin keeps the viewers' localStorage across launches. 8737 is a Termux `caracole serve`'s. |
| Secret cookie | `caracole-launch=<64 hex>; Path=/; HttpOnly; SameSite=Lax` | Lax, not Strict: a sandboxed viewer has an opaque origin, so its link back is a cross-site navigation (checked in Chromium 156). Cookies ignore the port, so the WebView loads **only** the server's exact origin (scheme, host and port); any other loopback origin opens in the browser. |
| Phone-only data | Tables `phone_overrides` and `phone_songbooks`, made by `caracole/schema/phone.sql` and counted in kv `phone:schema`. `PRAGMA user_version` stays caracole's 15. | Sync moves units, not files, so there is no TOML on the phone. `index_transfer` checks only the site tables and the schema number. |
| The phone's songs | The `songs` table is the source of songs; there is no wanted.txt on the phone. `LibraryStore.add` ports `upsert_song`'s rules: tombstones, `_artist_as_written`, `title_variant`, strip. | |
| Unicode | Every table is generated from Python 3.14's `unicodedata` 16.0.0 and shipped as a resource. `:core` never calls a JDK or ICU text API (`ForbiddenApiTest`). | JDK 17 has Unicode 13, Android's ICU varies by device, and Android's `java.util.regex` is ICU-backed. |
| rapidfuzz | Port rapidfuzz-cpp 3.3.4, not `fuzz_py` | The pure-Python fallback picks other alignment windows in about 27% of cases. The skeleton commits the checked transcription as `tests/helpers/rapidfuzz_cpp.py`. |
| FORMAT 2 hashing | A version's `raw` and a song's `lyrics_json` are hashed as canonical JSON, with an exact decimal rule for numbers and bounded fallbacks (§4) | Two languages serializing one record must give one digest. |
| A stored base after the bump | Tagged `{"format":2,"units":…}`. An untagged (FORMAT 1) base reads as none: no translation | The owner's rule against compatibility shims. The cost is one first sync that shows plain differences (§4; §11, question 4). |
| Display names on a take | The take writes the peer's `artist`, `title` and `artists` verbatim. When the taken artist's folder differs **only in case** from how the library already writes that artist, every song of that artist is respelled to the taken spelling and its folder moved once (§5.6) | Today two spellings never agree (a probe showed it). The respelling keeps one folder per artist, which a case-blind file system needs (`songs._artist_as_written`'s reason). |
| A removed song on the phone | Its mirrored card is dropped and its mirrored pages answer "removed on the phone" until a sync settles it. A take of a song forgets the phone's tombstone of that key | "A removed song stays removed until you ask for it again" must hold where the owner looks. |
| Get it and Fetch now on the phone | `POST /lookup` and `POST /request` with `fetch=1` add the song as `fetch=0` does, answering "Added: the computer's next run fetches it." | The request form's default and every search row's Get it must add a song with the computer off. A lookup on the sites is M4. |
| Cooldowns at a sync | Deferred to M4, when the phone first meets a site. The state document ignores unknown keys, so `cooldowns` can come later | The phone sends no request to a site in M1–M3. |
| The index at a sync | Computer to phone: a sync's last stage, `index`, merges the computer's newer sites (`GET /api/peer/index?sites=`), and also a file the owner picks. Phone to computer: M4, recorded in docs/android_port.md and the design's Phases | The phone reads no site before M4. |
| What caracole serve writes | Beyond wanted.txt and its request history: the push staging folder (`state_dir/peer/push-<id>/`, 0700) and a temporary index export (`cache_dir/peer/`), both deleted after use. Everything else stays a queued command's: peers' addresses are kv `sync:peer:<id>`, written by `caracole peer sync`; the Sync tab's choices go on the command line | AGENTS.md's invariant gains these two exceptions, with nothing else. |
| The phone's backup before a take | A full, openable database: `caracole/schema/migrations.json` and `phone.sql` run on a new file, then the library tables copied in (`songs`, `versions`, `files`, `removed`, `kv`, `phone_*`). The index tables stay empty. Three are kept. `Take.restore` puts one back | A whole `VACUUM INTO` copies about 430 MB on every sync, and a take never changes the index tables. |
| Your songs in M2 | The page shows the cards of the mirror's `index.html` data block, re-identified to the phone's ids. `/api/search`'s `library` is the phone's database, empty until M3 | The library page filters its own songs in the browser, so M2 still finds them. |
| A mirrored page of a song the phone changed | Served while the phone holds no unit of that id, or holds it with the manifest's digest. Otherwise the message page, linking to the phone's `sheet.txt` | Until M5's page builder. |
| Progression search, LaCuerda's own search, YouTube | `progression`, `lacuerda_search`, `lacuerda_unlisted` and `youtube` answer `null` | These need M4 or M5. The page then sends nothing by itself. |
| The Requests tab and the job history on the phone | Not in M3. The Sync tab shows a sync's own outcome, and the history lives in memory | M4 brings the Requests tab with lookups. |

---

## 2. Architecture

```
android/
  mirror/   (kept, pure JVM) the computer's rendered pages: manifest, blobs, a page gated by unit (UnitGate), Http (GET, POST)
  core/     (new, pure JVM)  io.github.danielhp95.caracole.core.*
            Stub.kt py/ db/ keys/ pinyin/ fuzz/ json/ search/ ug/ sites/ lacuerda/ names/ index/ library/ sync/
            testFixtures/: testing/{Corpus,Fixtures,TestDb}.kt, testing/sync/FakeComputer.kt
  server/   (new, pure JVM)  io.github.danielhp95.caracole.server.*
            http/ files/ page/ jobs/ routes/ ktor/ Assembly.kt; testFixtures/: testing/TestApp.kt
  app/      the Android app: starts LocalServer, sets the cookie, the WebView at http://127.0.0.1:8738/
  e2e/      (new, pure JVM)  the end-to-end phases against a real caracole serve (lane e2e-jvm)
tests/conformance/
  data/caracole/…   generated runtime data, a resource root of :core (unicode, keys, pinyin, schema, page)
  vectors/…         generated test vectors the Kotlin tests read (system property caracole.conformance)
docs/superpowers/spikes/2026-11-03-android/   the spikes' Kotlin, kept for reference (not compiled)
```

Module dependencies:
- `:core → :mirror`
- `:server → :core, :mirror`
- `:app → :server`
- `:e2e → :server`, plus the testFixtures of `:core` and `:server`

`:core` and `:server` are `kotlin("jvm")` with Java 17 and `java-test-fixtures`.

Data flow on the phone:
- WebView → `http://127.0.0.1:8738` → Ktor CIO → `App.handle` (the secret, then caracole serve's checks) → a route
  module, or a stub where no module answers.
- Search routes → `core.search` over `Database.read`.
- Page routes → `LibraryPage`, built from `library_assets/` (copied byte for byte at build time, in the order of
  `caracole/page/library_assets.json`), plus `PageData` (M2–M3: `MirrorPageData` over the mirror's `index.html` data
  block and the phone's database).
- Library files → the phone's library folder (`filesDir/library`), then the mirror's blobs, gated by unit
  (`UnitGate`).
- Writes (add, remove, a sync, an index import) → `JobQueue` → `Database.write`:
  - a sync: `SyncEngine` (`PeerClient` → the computer) → `Take` into the database and the library folder → the
    mirror's refresh → the index's merge;
  - an add or a removal: `LibraryStore`;
  - an index import: `IndexTransfer.merge`.

---

## 3. The conformance corpus

The full spec is `docs/superpowers/specs/2026-11-03-conformance-corpus.md`, which the skeleton writes from this
section.

- **Who writes it.** The Python suite writes every file under `tests/conformance/`.
  - Each area has its own generator test, `tests/test_conformance_<area>.py`. The test builds the file's content in
    memory and calls `helpers.corpus.check(path, content)`.
  - By default, `check` asserts that the committed file is byte-identical to the new content. A mismatch fails,
    naming the first differing line and the command that regenerates it.
  - With `CARACOLE_CORPUS=write`, `check` writes the file instead:
    `CARACOLE_CORPUS=write nix develop -c pytest -q -n 0 tests/test_conformance_*.py`.
  - Generated files are never edited by hand. Any lane may regenerate any of them. A merge conflict in one is
    resolved by regenerating after the merge.
- **JSONL vectors.** `tests/conformance/vectors/<area>/<name>.jsonl`, in UTF-8 with `\n` line ends.
  - Line 1 is the header:
    `{"header":true,"corpus":"<area>/<name>","made_by":"tests/test_conformance_<area>.py","versions":{…}}`.
    `versions` holds `python`, `unicodedata`, `sqlite`, `pypinyin`, `rapidfuzz` and `caracole`
    (`helpers.corpus.versions()`). A nixpkgs bump therefore makes every file stale, and regenerating shows the
    Kotlin side what moved.
  - Every later line is one record: `{"fn":"<python dotted name>","args":[…],"kw":{…},"out":…}`, or `"err":"<Python
    exception class>"` in place of `out`. A corpus may add other keys (`fixture`, `note`, `seed`).
  - Every line is `json.dumps(rec, ensure_ascii=False, sort_keys=True, separators=(",", ":"))`.
  - No string in a corpus holds a lone surrogate; generators leave U+D800–DFFF out of their inputs.
  - Values map as follows. A tuple becomes an array. A dataclass or NamedTuple becomes an object of its fields,
    recursively (`helpers.corpus.plain`). A `Song` becomes its `key`. A float is written by Python's repr; Kotlin
    parses it as a `Double` and compares with `==`. Objects compare as maps, and arrays in order.
- **Whole-file JSON vectors.** `vectors/<area>/<name>.json` is one object, with the header's fields as its `header`
  member.
- **Runtime data.** `tests/conformance/data/caracole/<area>/…` is generated and checked the same way.
  - It is a main resource root of `:core`, so the APK ships it, on the classpath as `caracole/<area>/…`.
  - Its format is the producing lane's own, documented in the generator's docstring and in the Kotlin reader.
  - Text formats are preferred. gzip is allowed only with `mtime=0`.
  - Two files are hand-written, not generated:
    - `data/caracole/schema/phone.sql`, the phone's own DDL (§5.4), which `PhoneSchema` and
      `helpers.corpus.replay_fixture` both read;
    - `data/caracole/README.md`.
- **Fixtures** (cross-lane, exact). `vectors/<area>/fixtures/<name>.jsonl` is a header, then lines in this order:
  1. `{"sql":"<CREATE …>"}` lines. These appear only in a fixture of a file that is not a migrated caracole
     database, such as an index export, and create its tables.
  2. `{"table":"<base table>","row":{<column>:<value>}}` lines, in the order of the fixed list below, then by rowid.
  3. `{"kv":"<key>","value":"<text>"}` lines.
  4. `{"file":"<path under the library>","base64":"…"}` lines.

  How fixtures are written and replayed:
  - `helpers.corpus.dump_fixture(conn, library_dir=None)` dumps exactly these base tables, parents first:
    `songs, versions, files, removed, events, ug_index, ug_artist_tabs, lacuerda_index, gtptabs_index,
    musescore_index, harptabs_index, harptabs_artists, harptabs_artist_tabs, gametabs_index, gametabs_games,
    gametabs_game_tabs`, then `phone_overrides, phone_songbooks` when they exist, then `kv` without `sync:id`
    unless the fixture pins it.
  - It never dumps a virtual table, an FTS shadow table (any table named `<virtual table>_…`) or a trigger-filled
    table (`ug_keys`, `ug_artists`, `ug_key_words`).
  - `test_corpus_helpers.py` fails when a migration adds a base table that the list neither names nor excludes.
  - Both sides replay into a freshly migrated database: one plain `INSERT` per row in file order, so the triggers
    number derived rows alike; kv lines as upserts; `phone_*` tables created from `phone.sql` first (Python's
    schema has none). Python's replay is `helpers.corpus.replay_fixture`; Kotlin's is `Fixtures.load`, or
    `Fixtures.loadRaw` into an empty file for `sql` fixtures.
  - Python runs a corpus's queries against the replayed database, never the one it built first.
  - `test_corpus_helpers.py` round-trips a library with `ug_index` rows, then passes `PRAGMA integrity_check` and each
    FTS table's `'integrity-check'`.
- **Determinism.** Generators iterate in a defined order. No output may depend on `PYTHONHASHSEED`: the search corpus
  runs its generator twice in subprocesses, with `PYTHONHASHSEED=1` and `=2`, and asserts the outputs are equal.
- **Size and speed.** Each generator runs in under 3 s, or it is marked `slow`. Vectors stay under 20 MB in total.
- **The Kotlin reader** (skeleton, `android/core/src/testFixtures/…/core/testing/Corpus.kt`):
  - `Corpus.records(name): List<Record>`, where
    `Record(fn: String, args: JsonArray, kw: JsonObject, out: JsonElement?, err: String?, extra: JsonObject)`.
  - `Corpus.json(name)` reads a `.json` vector.
  - `Corpus.open: (path: String) -> InputStream?` defaults to the directory in the system property
    `caracole.conformance`. Gradle sets it for every test task and declares the directory an input. An androidTest
    sets `Corpus.open` from the instrumentation's `AssetManager`.
  - A missing file fails the test; it never skips.
- **On the device.** `CorpusOnDeviceTest` (integration) runs the `unicode`, `keys`, `pinyin`, `fuzz` and `canonical`
  vectors under Android's runtime and its ICU-backed regex.

**The drift protocol.** A corpus is a contract between a Python owner and Kotlin readers who may already have merged.
- A Python lane that changes behaviour a corpus covers regenerates that corpus in its own branch. It then runs
  `nix develop ./android -c gradle -p android test` against it before merging.
  - If a Kotlin test breaks, the Python lane does not merge. It reports "conformance drift: <corpus>, Kotlin lane
    <id>" and stops. The orchestrator reopens the owning Kotlin lane (or a `conformance-fix` step scoped to that
    area) on a branch that merges both.
  - When the Kotlin lane is the one still open, it takes the regenerated corpus by merging main.
- A Kotlin lane that finds Python's answer ambiguous (an unordered query, a set's order, a tie) may make a scoped fix
  to the Python reference, with a determinism test and the regenerated vectors, in a commit scoped to that area
  (`fix(search): …`). This applies to search.py, lacuerda_index.py, ug/key_search.py, song_names.py, status.py and
  outcome.py, even after that file's owner has merged. It never changes behaviour beyond the tie.
- `search-corpus` orders every query whose row order reaches an output, not only the LIMITed ones.
- The skeleton's AGENTS.md rule says the same for later work: a change to normalize, search, peer_sync, the schema,
  library_assets, status.py or outcome.py regenerates the corpus in the same commit, and `gradle -p android test`
  passes before it merges.

---

## 4. Canonical JSON and sync FORMAT 2

The full spec is `docs/superpowers/specs/2026-11-03-canonical-json.md`, which the skeleton writes from this section
with at least 25 vectors, each checked against Python. The Python reference is `src/caracole/canonical.py` (lane
`canonical`).

**The strict reading.** Canonical hashing reads text exactly as Python's `json.loads(text)` does with its defaults
(`strict=True`). Kotlin has its own small parser for it, never a lenient one.
- Whitespace is only space, `\t`, `\n` and `\r`.
- A string may not hold a raw control character below U+0020.
- `01`, `+1`, `.5`, `1.` and a BOM are refused.
- `NaN`, `Infinity` and `-Infinity` are read.
- An integer literal of more than 4300 digits is refused, as Python's int limit refuses it.
- A refused text is "not JSON".

**Canonical text** `C(v)`:
- **Objects.** Members sorted by key in code-point order (not UTF-16 order), written `{"k":v,…}` with no spaces.
  When the text repeats a key, the last value wins, as in `json.loads`, and the key appears once.
- **Arrays.** `[v,…]`, in order.
- **Strings.**
  - `"` and `\` are written `\"` and `\\`.
  - U+0008, 09, 0A, 0C and 0D are written `\b`, `\t`, `\n`, `\f` and `\r`.
  - Every other code point below U+0020 is written `\u00xx`, in lowercase hex.
  - Every other code point is written raw as UTF-8, including U+007F, U+2028, U+2029 and the supplementary planes.
  - A lone surrogate is an error in a value and "not canonicalizable" in a stored text.
- **Literals.** `true`, `false`, `null`; `NaN`, `Infinity` and `-Infinity` as is.
- **An integer literal** (`-?\d+`) is written as the integer's decimal, so `-0` becomes `0`.
- **Any other number literal** (with a fraction or an exponent) is written as its **exact decimal value**:
  - plain notation, no exponent;
  - trailing fractional zeros dropped, then a trailing `.`;
  - `-0` written `0`.

  It is computed on the literal's digits, never through a float or a bounded precision: Python's
  `Decimal.normalize()` under the default context rounds to 28 digits, which is wrong here. Examples:
  - `238.0` → `238`
  - `4.50` → `4.5`
  - `1E2` → `100`
  - `1e-7` → `0.0000001`
  - `-0.0` → `0`
  - `0.12345678901234567890123456789012345` stays as is.

  When the literal's exponent is beyond ±1000, the whole text is "not canonicalizable".
- This is exactly `json.dumps(v, sort_keys=True, separators=(",",":"), ensure_ascii=False)` for every value without
  a non-integral number, which keeps FORMAT 1's unit digests unchanged.

**Digest** `D(v)` = the lowercase hex SHA-256 of `UTF-8(C(v))`, which is `peer_sync.digest_of`.

**Stored JSON hash** `H(text)`, for `versions.raw` and `songs.lyrics_json`:
- `null` stays `null`.
- Text that is JSON and canonicalizable: `H = D(parsed)`.
- Otherwise (not JSON, a lone surrogate, an exponent beyond ±1000), `H` is the SHA-256 of the text's bytes, as
  Python's `text.encode("utf-8", "surrogatepass")` gives them. Kotlin hashes those same bytes.

The vectors cover each rule: more than 28 significant digits, `1e999999999`, a 5000-digit integer, a raw control
character in a string, `01`, `+1`, `.5`, a BOM, duplicate keys, `\ud800` escapes, `NaN`, whitespace variants of one
record, and a supplementary key beside a U+FF61 key.

**`kv` text** (`PyJson.dumps`, not canonical): `db.kv_set_json` writes `json.dumps(value, ensure_ascii=False)`. That
is `", "` and `": "` separators, insertion order, and a number's literal as given. `Db.kvSetJson` writes exactly
that, keeping a `JsonObject`'s order, so every kv record either side writes is byte-identical. This includes the
sync base, which Python builds in `sorted()` key order.

**FORMAT 2.**
- `peer_sync.FORMAT = 2`. The state, unit and push documents carry `"format": 2`, and a side refuses any other
  format, as today.
- `song_value`'s `versions[].raw` becomes `H(raw)`, and `lyrics[1]` becomes `H(lyrics_json)`. Nothing else in a unit
  value changes.
- The stored base `kv sync:base:<peer id>` becomes `{"format":2,"units":{"<unit id>":[digest|null,"<stamp>"]}}`, and
  `_read_base` reads anything else as no base.
  - There is no translation of a FORMAT 1 base. That would be a compatibility shim, which the owner rules out.
  - The cost: the first sync after the upgrade compares as a first sync. A unit on one side alone is that side's, so
    a song one side removed after their last sync shows as the other side's to take, and the owner flips it to
    "here" in the Sync tab (§11, question 4).
- The state document gains:
  - `"now"`: the computer's clock, as a stamp. Agreements are stamped with it on both sides, so one clock is used.
  - `"indexes"`: `{site: stamp}`, the newest read time of each site's index on that side (§5.3). The phone uses it
    to fetch only the sites the computer holds newer.

  Readers ignore keys they don't know, so `cooldowns` can join in M4.

---

## 5. Interfaces

Package roots: `core.` is `io.github.danielhp95.caracole.core.`, `server.` is `io.github.danielhp95.caracole.server.`,
`mirror.` is `io.github.danielhp95.caracole.mirror.`.

**The rules for stubs.**
- The skeleton writes every file named here, with these signatures.
- Bodies are `TODO("lane <id>")`, with three exceptions:
  - The files marked **final** are written whole.
  - The files marked **working** get a working first version that the named lane hardens.
  - Every function that `Assembly.kt` reaches while the app runs returns a neutral value through
    `core.stub("lane <id>") { … }` (marked **neutral** below). That keeps the app and the device tests running
    before the lane lands.
- A stubbed `val` is `get() = TODO(…)`, never an initialiser, so an object's other members still load.
- A lane may add private members and new files in its own packages. It may not change a declared signature: if one
  must change, the lane says so in its report and updates this plan in the same change.

### 5.1 `:core`

```kotlin
// core/Stub.kt (final)
inline fun <T> stub(lane: String, neutral: () -> T): T = neutral()   // grep 'stub("lane' lists what is still neutral

// core/py/Py.kt (py-unicode)
object Py {
    val CODE_POINT_ORDER: Comparator<String>          // Python's str ordering
    fun len(s: String): Int                           // code points
    fun codePoints(s: String): IntArray
    fun string(cps: IntArray, from: Int = 0, to: Int = cps.size): String
    fun slice(s: String, from: Int?, to: Int?): String // s[from:to], negative indexes included
    fun split(s: String): List<String>                // str.split() on Python's whitespace
    fun strip(s: String): String
    fun asciiLower(s: String): String                 // A–Z only: header names, hex, protocol words
    fun round(x: Double, digits: Int): Double         // round(x, n): half-even on the exact binary value
    fun fsum(xs: Iterable<Double>): Double            // builtin sum() of floats, 3.12+ (Neumaier)
    fun floorMod(a: Int, b: Int): Int
    fun <K> mostCommonFirst(items: Iterable<K>): K?   // Counter(items).most_common(1)[0][0]
}
// core/py/PyUnicode.kt (py-unicode): tables from caracole/unicode/*
object PyUnicode {
    const val UNIDATA_VERSION = "16.0.0"
    fun isAlnum(cp: Int): Boolean; fun isAlpha(cp: Int): Boolean; fun isDecimal(cp: Int): Boolean
    fun isDigit(cp: Int): Boolean; fun isNumeric(cp: Int): Boolean; fun isSpace(cp: Int): Boolean
    fun isWord(cp: Int): Boolean                      // re's \w: isalnum() or '_'
    fun isPrintable(cp: Int): Boolean
    fun category(cp: Int): String                     // "Lu", "Mn", …
    fun combining(cp: Int): Int
    fun latinByName(cp: Int): Boolean                 // "LATIN" in unicodedata.name(c)
    fun lower(s: String): String; fun upper(s: String): String; fun casefold(s: String): String
    fun nfc(s: String): String; fun nfkc(s: String): String; fun nfd(s: String): String; fun nfkd(s: String): String
    fun ignoreCaseKey(cp: Int): Int                   // sre's IGNORECASE class representative
    fun allAlnum(s: String): Boolean; fun allDigit(s: String): Boolean; fun allAlpha(s: String): Boolean; fun allSpace(s: String): Boolean
}
// core/py/PyRegex.kt (py-unicode): fragments for java.util.regex that mean what Python's mean, in \x{…} ranges
object PyRegex {
    val WORD: String; val NOT_WORD: String; val SPACE: String; val DIGIT: String   // [...] class bodies (get() = …)
    fun compile(pattern: String): Regex   // expands \w \W \s \S \d \D \b \B into the classes above; no flags
    fun ignoreCase(s: String): String     // length-preserving map to ignoreCaseKey, for IGNORECASE patterns
}

// core/db/Database.kt (working: the skeleton's, from the spike; core-db hardens it). Threads: §5.5
class Database(val path: java.io.File, driver: androidx.sqlite.SQLiteDriver = BundledSQLiteDriver(), readers: Int = 4) : AutoCloseable {
    companion object {
        const val SCHEMA_VERSION = 15
        const val SQLITE_SOURCE_ID = "2025-06-06 14:52:32 b77dc5e0f596d2140d9ac682b2893ff65d3a4140aa86067a3efebe29dc914c95"
        const val BUSY_TIMEOUT_MS = 10_000
    }
    val writes: kotlinx.coroutines.sync.Mutex             // caracole's lock on the phone
    fun <T> read(block: (Db) -> T): T                     // a pooled connection for this block alone; never writes
    suspend fun <T> write(block: (Db) -> T): T            // the one writer connection, under writes
    fun <T> writeBlocking(block: (Db) -> T): T            // the same lock, for a caller that is not a coroutine
    fun backupTo(target: java.io.File)                    // VACUUM INTO, under a .part name, then a rename
    override fun close()
}
// Opening migrates once per path, under an in-process lock (caracole/schema/migrations.json): when 0 < user_version < 15,
// VACUUM INTO <path>.v<N>.bak first; each version in BEGIN IMMEDIATE … PRAGMA user_version=N … COMMIT; above 15, DatabaseTooNew.
// Then PhoneSchema. Every connection: PRAGMA foreign_keys=ON, journal_mode=WAL, synchronous=NORMAL, busy_timeout.
class Db internal constructor(val raw: androidx.sqlite.SQLiteConnection) {
    fun <T> query(sql: String, vararg args: Any?, row: (Row) -> T): List<T>
    fun <T> one(sql: String, vararg args: Any?, row: (Row) -> T): T?
    fun execute(sql: String, vararg args: Any?): Int  // changes()
    fun lastRowid(): Long
    fun <T> savepoint(name: String, block: () -> T): T   // nests
    fun kvGet(key: String): String?; fun kvSet(key: String, value: String); fun kvDelete(key: String)
    fun kvGetJson(key: String): kotlinx.serialization.json.JsonElement?
    fun kvSetJson(key: String, value: kotlinx.serialization.json.JsonElement)   // = db.kv_set_json's bytes (core.json.PyJson.dumps)
    fun attach(file: java.io.File, alias: String); fun detach(alias: String)
}
interface Row { fun text(i: Int): String?; fun long(i: Int): Long?; fun double(i: Int): Double?; fun isNull(i: Int): Boolean
                fun text(name: String): String?; fun long(name: String): Long?; fun double(name: String): Double?; val columns: List<String> }
class DatabaseTooNew(message: String) : Exception(message)
object PhoneSchema { const val VERSION = 1; fun migrate(db: Db) }  // caracole/schema/phone.sql and kv phone:schema, in one BEGIN IMMEDIATE

// core/keys/Normalize.kt (keys)
object Normalize {
    const val KEY_VERSION = 2
    fun fold(s: String): String; fun nameWords(s: String): List<String>; fun holdsRun(words: List<String>, run: String): Boolean
    fun cleanTitle(t: String): String; fun titleVariant(t: String): String?; fun canonicalVariant(v: String): String
    fun slugKey(s: String): String; fun ugSlugKey(slug: String): String; fun compact(key: String): String
    fun splitVariant(key: String): Pair<String, String?>; fun identityKey(artist: String, title: String): String
    fun simplified(s: String): String; fun hasHan(s: String): Boolean; fun hasOtherScript(s: String): Boolean
    fun romanize(s: String): String; fun withoutFeaturing(s: String): String; fun placeholderArtist(name: String): Boolean
    fun displayKey(artist: String, title: String): String
    fun nameForms(name: String): List<String>; fun listingForms(title: String): List<String>; fun originalPart(name: String): String
    fun lacuerdaNameKey(name: String): String      // lacuerda_index.name_key: identity_key(romanize(name), "") artist side
    fun lacuerdaTitleKey(title: String): String    // lacuerda_index.title_key
}
// core/keys/SafeName.kt (keys): library.safe_name and song_folder
object SafeName { fun safeName(s: String): String; fun songFolder(artist: String, title: String): Pair<String, String> }

// core/pinyin/Pinyin.kt (pinyin): pypinyin 0.55.0, Style.NORMAL
object Pinyin {
    enum class Errors { DEFAULT, IGNORE }
    fun lazyPinyin(text: String, errors: Errors = Errors.DEFAULT): List<String>
    fun heteronyms(cp: Int): List<String>            // pinyin(c, style=NORMAL, heteronym=True)[0]
}

// core/fuzz/Fuzz.kt (fuzz): rapidfuzz 3.14.5 on rapidfuzz-cpp 3.3.4, code points, processor=None
object Fuzz {
    data class Alignment(val score: Double, val srcStart: Int, val srcEnd: Int, val destStart: Int, val destEnd: Int)
    data class Extracted(val choice: String, val score: Double, val index: Int)
    fun ratio(a: String, b: String): Double
    fun tokenSortRatio(a: String, b: String): Double
    fun partialRatioAlignment(a: String, b: String): Alignment
    fun extract(query: String, choices: List<String>, scoreCutoff: Double, limit: Int?): List<Extracted>  // scorer=fuzz.ratio
}

// core/json/Canonical.kt, PyJson.kt (canonical)
object Canonical {
    val KEY_ORDER: Comparator<String>                                      // code points
    fun write(value: kotlinx.serialization.json.JsonElement): String       // C(v), §4
    fun digest(value: kotlinx.serialization.json.JsonElement): String      // D(v)
    fun hashStoredJson(text: String?): String?                             // H(text)
    fun parse(text: String): kotlinx.serialization.json.JsonElement        // the strict reading of §4: literals kept, last duplicate wins; CanonicalError when not JSON
    fun sha256Hex(bytes: ByteArray): String
}
object PyJson { fun dumps(value: kotlinx.serialization.json.JsonElement, sortKeys: Boolean = false, compact: Boolean = false): String } // json.dumps(…, ensure_ascii=False)
class CanonicalError(message: String) : Exception(message)

// core/library/Songs.kt (final): the read side every lane shares
data class SongRow(val id: Long, val key: String, val artist: String, val title: String, val artists: List<String>,
    val album: String?, val durationMs: Long?, val isrc: String?, val sourceIds: String, val addedAt: String,
    val variant: String?, val status: String, val review: Boolean, val matchDecision: String?, val matchStep: String?,
    val matchScore: Double?, val matchArtistKey: String?, val matchSongKey: String?, val matchCandidates: String,
    val matchedAt: String?, val ugDirty: Boolean, val ugCheckedAt: String?, val lyricsStatus: String,
    val lyricsJson: String?, val lyricsAt: String?, val lacuerdaCheckedAt: String?, val createdAt: String) {
    val display: String   // song.display, as songs.py defines it
}
data class RemovedRow(val key: String, val artist: String, val title: String, val sourceIds: String, val removedAt: String)
object Songs {
    fun list(db: Db): List<SongRow>                  // list_songs: ORDER BY added_at DESC, id DESC
    fun byKey(db: Db, key: String): SongRow?; fun byId(db: Db, id: Long): SongRow?
    fun removed(db: Db): List<RemovedRow>            // as search_removed reads them
    fun isRemoved(db: Db, key: String): Boolean      // a tombstone of that key and no song of it
}

// core/search/Hits.kt (final): search.py's dataclasses; toJson() as helpers.corpus.plain writes them
data class LibraryHit(val song: SongRow, val score: Double, val via: String = "both")   // toJson: song → song.key
data class IndexHit(val artistKey: String, val songKey: String, val counts: LinkedHashMap<String, Int>, val score: Double,
    val url: String, val labels: List<String> = emptyList(), val artist: String = "", val title: String = "",
    val via: String = "both", val rating: Double? = null, val votes: Int = 0, val page: String = "") { val tabs: Int; val catchAll: Boolean }
data class ArtistHit(val artistKey: String, val artist: String, val score: Double, val songs: Int, val tabs: Int,
    val top: List<IndexHit> = emptyList(), val page: String = "", val part: Boolean = false)
data class IndexFound(val artists: List<ArtistHit> = emptyList(), val songs: List<IndexHit> = emptyList(), val lead: String? = null, val best: IndexHit? = null)
data class Found(val library: List<LibraryHit>, val artists: List<ArtistHit>, val songs: List<IndexHit>, val lead: String?, val best: Any? /* LibraryHit | IndexHit */)
data class HarpTabHit(val title: String, val url: String, val views: Int = 0, val rating: Double? = null, val key: String? = null, val difficulty: String? = null)
data class GameTabHit(val title: String, val url: String, val views: Int = 0, val rating: Double? = null, val instruments: List<String> = emptyList(), val composers: List<String> = emptyList())
data class SiteHit(val source: String, val title: String, val url: String, val score: Double, val artist: String = "",
    val artistKey: String = "", val titleKey: String = "", val uploads: Int = 1, val via: String = "title",
    val sheet: String? = null, val tabs: List<Any> = emptyList() /* HarpTabHit | GameTabHit */, val page: String = "")
data class SiteArtist(val source: String, val artist: String, val slug: String, val url: String, val score: Double,
    val songs: Int = 0, val known: Int = 0, val via: String = "artist", val top: List<SiteHit> = emptyList(),
    val part: Boolean = false, val read: Boolean = false)
data class Suggestion(val source: String, val artist: String, val key: String, val songs: Int, val score: Double,
    val title: String = "", val hits: List<Any> = emptyList() /* IndexHit | SiteHit */)
data class RemovedHit(/* search.py's RemovedHit fields, copied by the skeleton */)
object SearchLimits { /* every constant of search.py lines 169–196, same names in SCREAMING_CASE, same values */ }
// every class has fun toJson(): JsonObject with Python's snake_case field names, in declaration order

// core/search/Query.kt, KeySearch.kt (search-query): the seam search-ug, search-suggest, search-sites and search-lacuerda score through
data class Readings(val title: Double, val both: Double, val artist: Double)
data class Reading(val score: Double, val via: String)
class Query(val text: String, val runs: List<String> = emptyList()) {
    val compact: String                                // get() = …
    fun holds(vararg names: String): Boolean
    fun score(artist: String, title: String): Double
    fun readings(artist: String, title: String): Readings
    fun name(artist: String): Double
}
object Queries {
    fun forms(text: String): List<String>; fun patterns(tokens: List<String>): List<String>; fun of(text: String): List<Query>
    fun pinyinRuns(words: List<String>): List<String>
    fun reading(scores: Iterable<Readings>, reading: String? = null): Reading
    fun namesReading(queries: List<Query>, artists: List<String>, title: String, reading: String? = null): Reading
    fun songReading(queries: List<Query>, song: SongRow, reading: String? = null): Reading
}
object KeySearch { const val KEYS_PER_PATTERN = 1000; fun rowsLike(db: Db, patterns: List<String>): List<Triple<String, String, Int>> }
// core/search/Search.kt (search-ug)
object Search {
    fun searchLibrary(db: Db, q: String, limit: Int = 10, reading: String? = null): List<LibraryHit>
    fun searchRemoved(db: Db, q: String, limit: Int = 10): List<RemovedHit>
    fun findIndex(db: Db, q: String, artists: Int = 3, songs: Int = 8, reading: String? = null): IndexFound
    fun found(library: List<LibraryHit>, index: IndexFound): Found
    fun artistSongs(db: Db, artistKey: String, limit: Int = 50, offset: Int = 0, title: String? = null): Pair<List<IndexHit>, Int>
    fun indexArtist(db: Db, artistKey: String): ArtistHit?
    fun libraryByArtist(songs: List<SongRow>, name: String, artistKey: String? = null): List<SongRow>
    fun bareIdHint(q: String, hits: List<Any>, artist: String? = null): String?
    fun bareIdUnseen(q: String, hits: List<Any>): kotlinx.serialization.json.JsonObject?
    fun noOnes(artistKey: String): Boolean
}
// core/ug/ArtistTabs.kt (search-ug): ug/artist_tabs.py's keys, refile, ensure_current_keys
object ArtistTabs { fun ensureCurrentKeys(db: Db): Int; fun refile(db: Db, pages: Collection<String>? = null): Int }  // pages: artist pages, as artist_tabs.refile; null: every one
// core/search/Suggest.kt (search-suggest; neutral: emptyList())
object Suggest {
    fun suggestArtists(db: Db, q: String, limit: Int = 3, lacuerda: Boolean = true, harptabs: Boolean = true): List<Suggestion>
    fun suggestTitles(db: Db, q: String, limit: Int = 3, lacuerda: Boolean = true, harptabs: Boolean = true, gtptabs: Boolean = true): List<Suggestion>
    fun suggestions(db: Db, q: String, index: IndexFound, sites: List<Any> = emptyList(), lacuerda: Boolean = true, harptabs: Boolean = true, gtptabs: Boolean = true): List<Suggestion>
}
// core/sites/SiteSearch.kt, SiteKeys.kt (search-sites)
object SiteSearch {
    fun searchGtptabs(db: Db, q: String, limit: Int = 5): List<SiteHit>; fun gtptabsSongs(db: Db, artist: String): Int
    fun searchMusescore(db: Db, q: String, limit: Int = 5): List<SiteHit>
    fun searchHarptabs(db: Db, q: String, songs: Int = 5, artists: Int = 3): Pair<List<SiteArtist>, List<SiteHit>>
    fun harptabsArtist(db: Db, path: String): SiteArtist?; fun harptabsSongs(db: Db, path: String, title: String? = null): List<SiteHit>
    fun searchGametabs(db: Db, q: String, limit: Int = 5): List<SiteHit>
}
object SiteKeys { fun harptabsEnsureCurrentKeys(db: Db): Int; fun gametabsEnsureCurrentKeys(db: Db): Int
                  fun harptabsIndexState(db: Db): kotlinx.serialization.json.JsonObject; fun gametabsIndexState(db: Db): kotlinx.serialization.json.JsonObject }
// core/lacuerda/LaCuerda.kt (search-lacuerda): lacuerda_index.py's read side and search.py's LaCuerda glue
object LaCuerda {
    fun nameKey(name: String): String = Normalize.lacuerdaNameKey(name)   // final delegation (keys owns the rule)
    fun titleKey(title: String): String = Normalize.lacuerdaTitleKey(title)
    fun searchLacuerda(db: Db, q: String, songs: Int = 5, artists: Int = 3): Pair<List<SiteArtist>, List<SiteHit>>
    fun lacuerdaArtist(db: Db, slug: String): SiteArtist?; fun lacuerdaArtistNamed(db: Db, name: String): SiteArtist?
    fun lacuerdaSongs(db: Db, slug: String, title: String? = null): List<SiteHit>
    fun lacuerdaLeftOut(db: Db): Pair<String, String>?; fun lacuerdaLeads(ug: IndexFound, lc: List<SiteArtist>): Boolean
    fun lettersRead(db: Db): kotlinx.serialization.json.JsonObject; fun ensureCurrentKeys(db: Db): Int
}
// core/names/SongNames.kt (song-names)
object SongNames { fun clean(text: String): String; fun cleanChannel(channel: String): String
                   fun readNames(db: Db?, text: String, songs: List<SongRow>, channel: String? = null): Pair<String, String>? }
// core/index/IndexTransfer.kt (index-transfer); merge is called inside Database.write
object IndexTransfer {
    const val FORMAT = "1"
    fun merge(db: Db, export: java.io.File, now: String, sites: List<String>? = null, backup: (() -> Unit)? = null): Merged
    fun seedFresh(db: Db)                              // the kv records a fresh Python database holds (caracole/schema/fresh_kv.json)
    fun newest(db: Db): Map<String, String>            // per site, the newest read time: the state document's "indexes"
}
data class Merged(val sites: Map<String, Map<String, Int>>, val changed: Boolean)
class TransferError(message: String) : Exception(message)

// core/library/LibraryStore.kt (sync-take); every method is called inside Database.write
class LibraryStore(val libraryDir: java.io.File) {
    fun add(db: Db, artist: String, title: String, album: String? = null, durationMs: Long? = null, variant: String? = null, now: String): SongRow
    fun remove(db: Db, key: String, now: String): RemovedRow?   // removal.remove_song's rules on the phone
    fun ensureCurrentKeys(db: Db): Int                          // songs.ensure_current_keys: songs and tombstones re-keyed at a KEY_VERSION change
    fun folderOf(song: SongRow): java.io.File                   // libraryDir/<SafeName.songFolder>
    fun fileOf(song: SongRow, name: String): java.io.File       // a checked name (§5.6) under folderOf, never through a link
}
// core/library/OverridesStore.kt, SongbookStore.kt (sync-units): phone_overrides, phone_songbooks (§5.4)
object OverridesStore {
    fun songEntries(db: Db, key: String): kotlinx.serialization.json.JsonObject  // = overrides.song_entries
    fun putSongEntries(db: Db, key: String, written: String, entries: kotlinx.serialization.json.JsonObject?)
    fun alias(db: Db, artistKey: String): kotlinx.serialization.json.JsonArray?; fun putAlias(db: Db, artistKey: String, written: String, slugs: kotlinx.serialization.json.JsonArray?)
    fun artistUrl(db: Db, artistKey: String): kotlinx.serialization.json.JsonObject?; fun putArtistUrl(db: Db, artistKey: String, value: kotlinx.serialization.json.JsonObject?)
    fun blocks(db: Db): List<Long>; fun putBlock(db: Db, tab: Long, on: Boolean)
}
data class StoredSongbook(val key: String, val name: String, val songs: kotlinx.serialization.json.JsonArray)
object SongbookStore { fun nameKey(name: String): String; fun all(db: Db): List<StoredSongbook>; fun put(db: Db, name: String, songs: kotlinx.serialization.json.JsonArray?) }

// core/sync/Units.kt, Compare.kt (sync-units)
data class SyncUnit(val id: String, val label: String, val digest: String) { val kind: String get() = id.substringBefore('/') }
data class Difference(val id: String, val label: String, val mine: SyncUnit?, val theirs: SyncUnit?, val proposal: String /* mine|theirs|conflict */, val why: String)
typealias Base = Map<String, Pair<String?, String>>
object Units {
    const val FORMAT = 2
    fun libraryState(db: Db): Map<String, SyncUnit>
    fun digestOf(db: Db, unitId: String): String?                        // one unit, for mirror gating (neutral: null)
    fun value(db: Db, unitId: String): kotlinx.serialization.json.JsonElement?
    fun document(db: Db, libraryDir: java.io.File, unitId: String): kotlinx.serialization.json.JsonObject?   // as /api/peer/unit's "unit"
    fun valueOfDocument(unitId: String, doc: kotlinx.serialization.json.JsonObject?): kotlinx.serialization.json.JsonElement?
}
object Compare {
    fun ownId(db: Db): String                                             // kv sync:id (migration 15 makes it)
    fun baseOf(db: Db, peer: String): Base?
    fun mergedBase(mine: Base?, theirs: Base?): Map<String, String?>?
    fun compare(mine: Map<String, SyncUnit>, theirs: Map<String, SyncUnit>, base: Map<String, String?>?): List<Difference>
    fun decide(found: List<Difference>, prefer: String? = null, choose: ((Difference) -> String?)? = null): Pair<List<Difference>, List<Difference>>
    fun order(found: List<Difference>): List<Difference>                  // peer_sync._order
    fun comparedHash(found: List<Difference>): String                     // sha256 of C([[id, proposal, here, there], …]) in order
    fun recordAgreement(db: Db, peer: String, mine: Map<String, SyncUnit>, theirs: Map<String, SyncUnit>, at: String): Int
}
// core/sync/Source.kt (final)
interface UnitSource { fun unit(id: String): kotlinx.serialization.json.JsonObject?; fun file(songKey: String, name: String, sha256: String): ByteArray }
// core/sync/Take.kt (sync-take); applyUnits and restore are called inside Database.write
data class Applied(val taken: List<String>, val left: List<Pair<String, String>>, val songs: List<Long>, val respelled: List<String>, val songbooksChanged: Boolean)
object Take {
    fun applyUnits(db: Db, store: LibraryStore, source: UnitSource, wanted: List<Pair<String, String?>>, expectedHere: Map<String, String?>,
                   now: String, onUnit: ((String, String) -> Unit)? = null): Applied
    fun backupBeforeSync(db: Db, stateDir: java.io.File, now: String): java.io.File?   // a full openable database (§1), 3 kept
    fun restore(db: Db, backup: java.io.File)                                           // its library tables back, in one savepoint
    fun checkedName(name: String): String                                               // _take_song's file-name rule, else UnitError
}
// core/sync/PeerClient.kt, SyncEngine.kt (sync-client)
data class PeerState(val format: Int, val server: String?, val caracole: String, val name: String, val now: String?,
                     val units: Map<String, SyncUnit>, val base: Base?, val token: String, val indexes: Map<String, String> = emptyMap())
class PeerClient(val address: mirror.ServerAddress, http: mirror.Http = mirror.Http()) : UnitSource {
    fun state(asking: String?): PeerState                                                    // 60 s read timeout
    fun pushNew(token: String, from: String, files: List<String>): Pair<String, List<String>>  // push id, the shas it needs
    fun pushFile(token: String, push: String, sha256: String, bytes: ByteArray)
    fun push(token: String, push: String, payload: kotlinx.serialization.json.JsonObject): Int // the job's id
    fun job(id: Int): kotlinx.serialization.json.JsonObject                                       // GET /api/jobs/<id>
    fun index(to: java.io.File, sites: List<String>? = null)                                      // GET /api/peer/index, no read timeout
}
enum class Side { HERE, THERE, SKIP }
data class Comparison(val id: String, val address: String, val peer: PeerState, val syncedBefore: Boolean,
                      val differences: List<Difference>, val hash: String)
data class SyncOutcome(val taken: List<String>, val given: List<String>, val left: List<Pair<String, String>>, val agreed: Int, val indexed: List<String>)
class SyncEngine(val database: core.db.Database, val store: LibraryStore, val stateDir: java.io.File,
                 val client: (String) -> PeerClient, val mirrorRefresh: (suspend (String) -> Unit)?) {
    fun compare(address: String): Comparison                       // kept by id 10 minutes
    suspend fun apply(c: Comparison, choices: Map<String, Side>, prefer: Side?, stage: (name: String, state: String, detail: String) -> Unit): SyncOutcome
}
```

### 5.2 `:server` and `:mirror`

```kotlin
// server/http/Http.kt (server-shell)
data class Request(val method: String, val target: String, val headers: Map<String, String> /* lowercase */, val body: ByteArray)
sealed interface Body { data object Empty : Body; class Bytes(val bytes: ByteArray) : Body; class FromFile(val file: java.io.File, val length: Long) : Body }
class Response(var status: Int, var body: Body = Body.Empty, val headers: MutableList<Pair<String, String>> = mutableListOf(), var data: kotlinx.serialization.json.JsonObject? = null)
class Refused(val status: Int, val title: String, message: String, val reload: Boolean = false) : Exception(message)
fun interface GetAnswer { fun answer(request: Request): Response }
fun interface PostAnswer { fun answer(request: Request, form: Map<String, String>): Response }
data class Route(val method: String, val path: String, val doc: String, val under: Boolean = false, val scriptOnly: Boolean = false,
                 val page: String = "the library", val limit: Int = 16_384, val get: GetAnswer? = null, val post: PostAnswer? = null)
interface RouteModule { val routes: List<Route> }
// server/http/App.kt (server-shell)
data class AppConfig(val csrf: String, val secret: String, val allowed: Set<String> = setOf("127.0.0.1", "localhost"), val libraryName: String = "Phone")
class App(val config: AppConfig, modules: List<RouteModule>, stubs: RouteModule, val files: server.files.LibraryFiles) {
    // A stub's route answers only where no module does; two modules answering one (method, path) refuse to construct.
    fun handle(request: Request): Response    // secret cookie → host → path → (GET own_page_read, route, scriptOnly token, else file) | (POST form ≤ route.limit)
    fun finish(response: Response): Response  // WebApp.finish's headers
    fun json(data: kotlinx.serialization.json.JsonElement, status: Int = 200): Response
    fun queued(view: kotlinx.serialization.json.JsonObject): Response   // 303 with data {job: view}; JSON 200 to Accept: application/json
}
object Security { const val SECRET_COOKIE = "caracole-launch"; fun hostName(h: String?): String?; fun answersTo(name: String?, allowed: Set<String>): Boolean
    fun crossOriginOk(method: String, headers: Map<String, String>, host: String?): Boolean; fun ownPageRead(headers: Map<String, String>): Boolean
    fun sameToken(given: String?, expected: String): Boolean; fun hasSecret(headers: Map<String, String>, secret: String): Boolean }
object Inline { fun sha256Source(text: String): String; fun jsonBlock(id: String, data: kotlinx.serialization.json.JsonElement): String }
object MessagePage { fun page(status: Int, title: String, message: String, link: Pair<String, String>? = null): Response }
// server/files/LibraryFiles.kt (server-shell)
class PhoneGate(val database: core.db.Database) : mirror.UnitGate   // song/<key>: removed here → Removed; Units.digestOf ≠ entry's → Changed; else Serve
class LibraryFiles(val libraryDir: java.io.File, val mirror: mirror.Mirror?, val gate: mirror.UnitGate, val database: core.db.Database) { fun serve(path: String): Response? }
// server/routes/Stubs.kt (server-shell): the out-of-round routes (§5.3)
class Stubs : RouteModule
// server/ktor/LocalServer.kt (server-shell)
class LocalServer(val app: App) : AutoCloseable { fun start(preferred: Int = 8738): Int; val origin: String; override fun close() }
// android/server/src/testFixtures/…/server/testing/TestApp.kt (server-shell): an App over a TestDb, a request builder (cookie, Host, token, form)

// server/page/* (library-page)
class LibraryAssets private constructor() { companion object { fun load(): LibraryAssets }  // order: caracole/page/library_assets.json
    val scripts: String; val styles: String; val scriptHash: String; val styleHash: String; fun template(name: String): String }
data class ServerControls(val csrf: String, val busy: Set<Long> = emptySet(), val active: Int = 0, val held: Set<Long> = emptySet(),
    val removing: Set<Long> = emptySet(), val jobs: List<kotlinx.serialization.json.JsonObject> = emptyList(),
    val timers: Map<String, Int>? = null, val badge: String? = "Phone", val sync: Boolean = false)
interface PageData { fun data(db: core.db.Db, now: String): kotlinx.serialization.json.JsonObject }   // songs, fold, icons, catalogue, generated, songbooks, sites
interface SongCards { fun cards(db: core.db.Db, songs: List<core.library.SongRow>): Map<Long, kotlinx.serialization.json.JsonObject> }
class MirrorPageData(val mirror: mirror.Mirror?) : PageData, SongCards   // cards re-id'd; tombstoned songs dropped; phone-only minimal cards
class LibraryPage(val assets: LibraryAssets) { fun served(data: kotlinx.serialization.json.JsonObject, controls: ServerControls, libraryName: String): String }
class PageRoutes(val database: core.db.Database, val page: LibraryPage, val data: PageData, val controls: () -> ServerControls) : RouteModule  // GET /, /index.html, /favicon.ico (neutral: the message page)

// server/routes/SearchRoutes.kt (search-routes; neutral: /api/search answers {query, library:[], index:[], short:true})
class SearchRoutes(val database: core.db.Database, val cards: SongCards, val enabled: Set<String> = setOf("gtptabs", "musescore", "harptabs", "gametabs")) : RouteModule {
    fun invalidate()   // after an index import or a sync
}
// server/jobs/* (jobs; JobsRoutes neutral: /jobs.json answers {active:0, jobs:[]})
data class JobSpec(val title: String, val key: String, val kind: String, val stages: List<Pair<String, String>> /* name, label */,
                   val display: String = "", val songId: Long? = null, val join: Boolean = true, val run: suspend (JobContext) -> Unit)
interface JobContext { fun stage(name: String, state: String, detail: String = ""); fun say(line: String); fun outcome(value: kotlinx.serialization.json.JsonObject); val isCancelled: Boolean }
class Job { val id: Int; val spec: JobSpec; val state: String; fun asJson(): kotlinx.serialization.json.JsonObject }
class JobQueue(scope: kotlinx.coroutines.CoroutineScope, val limit: Int = 20, val keep: Int = 100) {
    fun submit(spec: JobSpec): Pair<Job, Boolean>; fun job(id: Int): Job?; fun snapshot(): List<Job>; fun cancel(id: Int): Job?
    suspend fun await(id: Int): Job
    var onBusy: (Boolean) -> Unit
}
object JobViews { fun view(job: Job, queue: JobQueue, card: kotlinx.serialization.json.JsonObject? = null, songbooks: kotlinx.serialization.json.JsonObject? = null): kotlinx.serialization.json.JsonObject }
class JobsRoutes(val queue: JobQueue, val cards: SongCards, val database: core.db.Database) : RouteModule   // GET /jobs.json, /api/jobs/; POST /jobs/cancel

// server/routes/SyncRoutes.kt, LibraryRoutes.kt (phone-sync-routes; neutral: GET /api/sync answers {server:null, name, address:null, peers:[]})
interface SyncSettings { val address: String?; fun remember(address: String) }
class SyncRoutes(val engine: core.sync.SyncEngine, val queue: JobQueue, val settings: SyncSettings, val database: core.db.Database, val afterSync: () -> Unit) : RouteModule
class LibraryRoutes(val store: core.library.LibraryStore, val queue: JobQueue, val cards: SongCards, val database: core.db.Database) : RouteModule   // POST /request, /lookup, /remove

// server/Assembly.kt (final; integration may adjust)
data class PhoneDeps(val database: core.db.Database, val libraryDir: java.io.File, val stateDir: java.io.File, val mirror: mirror.Mirror?,
                     val scope: kotlinx.coroutines.CoroutineScope, val settings: SyncSettings, val secret: String, val csrf: String)
class Phone(deps: PhoneDeps) {
    val app: App; val queue: JobQueue; val search: SearchRoutes; val server: LocalServer
    fun importIndex(file: java.io.File): Job   // a job of kind "index" (key "index"): IndexTransfer.merge inside Database.write, then search.invalidate()
}
// Route modules in this order: PageRoutes, SearchRoutes, JobsRoutes, SyncRoutes, LibraryRoutes; Stubs last. ServerControls.sync = true.

// :mirror additions, written by the skeleton (Manifest.kt and Mirror.kt are offline-units' after it)
data class Entry(/* the fields of today */, val unit: String? = null, val digest: String? = null)   // parsed by offline-units
fun interface UnitGate { fun check(unit: String, digest: String?): Gate }
enum class Gate { SERVE, CHANGED, REMOVED }
fun Mirror.pageFor(path: String, gate: UnitGate): Looked   // final: Looked.Page(entry, file) | Looked.Gated(entry, gate) | Looked.Missing
// mirror/Links.kt (app-local): Links(origin: java.net.URI, lookup: (String) -> Boolean) — a page only at that exact origin
```

### 5.3 HTTP

**The phone (127.0.0.1:8738).**
- Every request needs the cookie `caracole-launch` matching the launch's secret, compared in constant time.
  Without it, the answer is `403 text/plain` "Not this app's caracole.".
- Then caracole serve's checks run, in caracole serve's order (web/app.py `_route`, security.py):
  1. the host check (421);
  2. strict unquoting of the path (400);
  3. `own_page_read` on `/api/` reads (403 JSON);
  4. on script-only reads, the token header `x-caracole-form-token` (403, with `reload`);
  5. on writes: the cross-origin check, `application/x-www-form-urlencoded`, at most the route's `limit` bytes
     (16 KiB unless the route says more), at most 20 fields, and the `csrf` field.
- Every answer gets `WebApp.finish`'s headers.

| Route | M | Owner | Answer |
|---|---|---|---|
| `GET /`, `GET /index.html` | M2 | library-page | The served library page, built from the templates (§5.2 `LibraryPage`). The header CSP is `frame-ancestors 'none'`. The meta policy is `default-src 'none'; script-src <h>; style-src <h>; img-src data: 'self'; base-uri 'none'; form-action 'self'; connect-src 'self'`. The Sync tab is the templates `sync-tab.html` and `sync-panel.html`, put in verbatim while `ServerControls.sync` |
| `GET /api/search?q=&box=` | M2 | search-routes | search_routes.py's shape, with `lacuerda_search`, `youtube`, `lacuerda_unlisted` and `progression` set to `null`. A superseded search answers `{query, superseded:true}` |
| `GET /api/artist?key=&offset=`, `?lacuerda=&lacuerda_name=`, `?harptabs=` | M2 | search-routes | search_routes.py's three shapes |
| `GET /jobs.json?jobs=` (script-only), `GET /api/jobs/N` | M2 neutral, M3 | jobs | `{active, jobs:[view]}` and `Job.asJson` |
| `POST /jobs/cancel` | M3 | jobs | as jobs_routes.py's |
| `GET /api/youtube/video?id=` | M2 | server-shell | `{id, url, state:"off", why:"YouTube isn't on the phone.", video:null, guess:{artist:"", title:""}, song:null}` |
| `GET /favicon.ico` | M2 | library-page | `page_icon.SVG` |
| other GETs | M2 | server-shell | A library file: the phone's folder first, then the mirror through `PhoneGate`. `CHANGED` answers the message page "This song changed on the phone since the computer made its page.", linking to `sheet.txt` when the phone has one. `REMOVED` answers "This song was removed on the phone." |
| `GET /review`, `/versions`, `/harmonica`, `/guitar`, `/lookup`, `/export.pdf` | M2 | server-shell (Stubs) | The message page, 409: "… isn't on the phone yet." |
| `POST /fetch`, `/review`, `/versions/*`, `/songbook/*`, `/lacuerda/*`, `/harptabs/artist`, `/youtube*`, `/jobs/again` | M2 | server-shell (Stubs) | `Refused(409, …, "… isn't on the phone yet.")`, which the page shows on the line |
| `POST /request`, `POST /lookup`, `POST /remove` | M2 Stubs (409), M3 | phone-sync-routes | **`/request`** as library_routes.py reads it (`q`, or the artist and title). `fetch=0` and `fetch=1` both add through `LibraryStore.add` as an `add` job; with `fetch=1` the line says "Added: the computer's next run fetches it." **`/lookup`** adds the same way and answers a lookup's shape: `202 {job, url:"/api/jobs/N", view}`. **`/remove`** follows remove_routes.py: first the question, then the confirmed removal queued under `remove:<key>` |
| `GET /api/sync` | M3 | phone-sync-routes | `{server, name, address, peers:[{address, server, name, synced_at}]}` |
| `POST /sync/compare` (form: `csrf`, `address`) | M3 | phone-sync-routes | `{comparison, peer:{address,server,caracole,name}, synced_before, differences:[{id,label,kind,proposal,why,here,there}]}`. `here` and `there` are a digest or null. The comparison is kept 10 minutes |
| `POST /sync/apply` (limit 1 MiB; form: `csrf`, `comparison`, `prefer` = `""`, `here` or `there`, and `choices` = lines `<here\|there\|skip>\t<unit id>`, only for conflicts and flipped proposals) | M3 | phone-sync-routes | `{job: view}` with kind `sync`. Refused, 409, when a conflict has neither a choice nor `prefer`, or when a fresh comparison's hash differs from the one kept |

**The `sync` job's view.** It is the same on both sides; jobs_routes.view writes it, and so does the phone's
`JobViews`:

```
{id, display:"Sync with <name>", songId:null, kind:"sync", state, fetching:false,
 line:{tone, text, link:null, details}, details:"#tab=sync",
 steps:[{name, label, state, detail}],        // compare, take, give, mirror, agree, index (the computer's: compare, take, give, agree)
 count:null,
 outcome: null | {taken:[unit id], given:[unit id], left:[[unit id, why]], agreed:<n>, indexed:[site]}}
```

- The `peer-push` view, the computer's take of a push, has kind `peer-push`, display "Changes from <name>", and
  steps `check`, `take`, `render`, `agree`.
- `add` and `remove` views are Python's for a song's add and its removal.
- The tones and the words are status.py's and outcome.py's as lane `sync-tab` writes them. They are recorded in
  `vectors/web/job_views.jsonl`, which the phone replays.
- On the phone, `details` is `#tab=sync` for a sync; other views keep Python's `#tab=requests&job=N`. With no
  Requests tab there, tabs.js falls back to the library tab, which is harmless.

**The computer (caracole serve).**
- web/app.py gains a body kind per route: `Route(..., body="form"|"json"|"bytes", limit=bytes)`.
- server.py asks `app.body_limit(method, path)` before it reads a body. An unknown path keeps 16 KiB.
- A `json` or `bytes` route needs the cross-origin check and the header `X-Caracole-Form-Token` equal to the csrf.
  A form route keeps the `csrf` field.
- `POST /peer/pull` and `POST /sync/apply` get 1 MiB.
- A GET answer may stream a file (`Response` with a body path, written in chunks).

| Route | Body | Owner | Answer |
|---|---|---|---|
| `GET /api/peer/state?peer=<id>` | | peer-format2 | as today, plus `"now"` and `"indexes"`, with `format: 2` |
| `GET /api/peer/unit?id=`, `GET /api/peer/file?song=&name=` | | peer-format2 | as today, `format: 2` |
| `POST /peer/push/new` | json ≤ 1 MiB: `{"format":2,"from":"<phone id>","files":["<sha256>",…]}` | peer-push-routes | `{"push":"<16 hex>","need":["<sha256>",…]}`: the files the computer has no readable copy of. It makes `state_dir/peer/push-<id>/` (0700). At most 2 pushes are open at once; one left uncommitted for an hour is deleted |
| `POST /peer/push/file?push=&sha256=` | bytes ≤ 64 MiB, `application/octet-stream` | peer-push-routes | `{"ok":true}`. 400 when the bytes' SHA-256 differs, or when `push` isn't 16 hex of an open push, or `sha256` isn't 64 hex, or `sha256` isn't in `need`, or the push's staged bytes would pass 2 GiB. No path is built before these checks |
| `POST /peer/push?push=` | json ≤ 16 MiB: the push document below | peer-push-routes | `{"job": view}` (Accept: application/json). It queues `caracole peer take --progress <dir>` under the job key `peer-push:<from>`, `join=False` |
| `GET /api/peer/index[?sites=ug,lacuerda,…]` | | peer-push-routes | `application/vnd.sqlite3`, streamed from a fresh `index_transfer.export` in `cache_dir/peer/` (one read transaction, no lock), deleted after |
| `GET /api/sync`, `POST /sync/compare`, `POST /sync/apply` | form | sync-tab | The phone's shapes. `GET /api/sync` reads kv `sync:peer:<id>` = `{address, name, synced_at}`, which `caracole peer sync` writes. `apply` queues `caracole peer sync ADDRESS --compared HASH --push --progress --choose=<side>:<unit id> …` (argv, no file) under `sync:<address>`, kind `sync` |

**The push document.** It is also written to `push-<id>/push.json` for `caracole peer take`:

```json
{"format": 2, "from": "<phone id>", "name": "<its library name>", "caracole": "<version>",
 "at": "<the computer's now, from the state the phone compared>",
 "units": {"<id>": {"label": "…", "digest": "…"}},
 "take": [{"id": "<unit id>", "expected": "<the computer's digest as compared, or null>",
           "digest": "<the phone's digest now, or null>", "unit": {<unit document as /api/peer/unit's "unit">} }]}
```

`units` is the phone's whole state after its own take. Before queueing, the route checks:
- the format and the token;
- that `from` is not the computer's own id;
- that each entry's `digest` equals `digest_of(value_of_document(id, unit))` (a null unit goes with a null digest);
- that every file a song document names is staged or already on the computer.

`caracole peer take [--progress] DIR` runs under `exclusive(interactive=True)`:
1. **check**: each unit's digest here is compared with `expected`. A unit changed since is left, with "changed here
   since the comparison".
2. A backup (`before-sync`).
3. **take**: `apply_units` from a `StagedSource`.
4. **render**: `render_all`, `render_songbooks` and `write_pages`.
5. **agree**: `record_agreement(conn, from, library_state(after), units, at)`.
6. A line per unit, taken or left, then `DIR` is deleted.

`--progress` prints get.py's JSON line events for each stage, plus `{"event":"unit","id":…,"outcome":"taken"|"left","why":…}`.
The exit code is 0 unless a bug. `caracole peer sync --progress` prints the same events for its stages: compare,
take, give, agree.

**The phone's sync** (`SyncEngine.apply`). It holds `Database.write` only for take and agree, never while it
fetches the index or polls the computer.
1. **compare**: re-read `GET /api/peer/state?peer=<phone id>`, compare again, and refuse when the hash differs.
2. **take**: a backup, then for each unit the phone takes: `GET /api/peer/unit` checked against the compared digest,
   then its files, then `Take.applyUnits` with `expectedHere`.
3. **give**: `pushNew`, then `pushFile` for each needed file, then `push` with the documents of the phone's state
   after its take. Then poll `GET /api/jobs/<id>` every second, 10 minutes at most.
4. **mirror**: `GET /api/offline` through the mirror's `SyncEngine`.
5. **agree**: `GET /api/peer/state` again, then `Compare.recordAgreement` at its `now`.
6. **index**: the sites whose `indexes` stamp is newer than kv `sync:index:<peer id>` records, fetched through
   `GET /api/peer/index?sites=` and merged inside `Database.write`. This stage is skipped when no site is newer. A
   failure here leaves the agreement in place.

On a 403 whose data says `reload`, the phone re-reads the state once, for a fresh token, and retries that call.

**`/api/offline`** (offline-units). Each entry may carry `"unit": "song/<key>"` or `"songbook/<key>"`, and with it
`"digest"`, the unit's digest when the manifest was made. The format stays 1, and the new fields are additive.
`index.html` and the files of no unit carry neither.

### 5.4 Storage on the phone

- `filesDir/caracole.sqlite`: caracole's schema 15 plus the phone's tables. It holds the indexes imported and the
  songs taken or added.
- `filesDir/library/<song folder>/<name>`: the phone's kept files. `files.path` is relative to this folder, as on
  the computer.
- `filesDir/state/`:
  - `backups/before-sync-<stamp>.sqlite`, 3 kept, none made without free space of twice the copy's size;
  - `cache/`: the index files fetched or picked, deleted after the merge.
- `filesDir/blobs/` and `filesDir/manifest.json`: the mirror, as today. No other file goes in `blobs/`, and no name
  there starts with `.tmp-`.

`tests/conformance/data/caracole/schema/phone.sql` (hand-written by the skeleton; `PhoneSchema` version 1, kv
`phone:schema` = `'1'`):

```sql
CREATE TABLE phone_overrides (
  tbl TEXT NOT NULL,      -- match, pin, transpose, reject, youtube, lacuerda, harptabs, gametabs, azlyrics, version, harmonica, ignore, alias, artist_url, block
  key TEXT NOT NULL,      -- identity key (song tables), slug_key(artist) (alias, artist_url), the tab id (block)
  written TEXT NOT NULL,  -- the name as overrides.toml would write it: "Artist - Title", the artist's name, the tab id
  value TEXT NOT NULL,    -- C(value): the value exactly as overrides.song_entries yields it (§4)
  PRIMARY KEY (tbl, key));
CREATE TABLE phone_songbooks (
  key TEXT PRIMARY KEY,   -- songbook.name_key(name): NFC, whitespace collapsed, casefold
  name TEXT NOT NULL,
  songs TEXT NOT NULL,    -- C([[entry text, parts], …]) as peer_sync.songbook_value
  position INTEGER NOT NULL);
```

### 5.5 Threads and the database

- `Database` holds one writer connection and a pool of `readers` connections. The bundled SQLite is THREADSAFE=2, so
  one connection is used by one thread at a time.
- `read { }` checks a connection out for its block, which never suspends.
- `write { }` takes `writes` (a coroutine `Mutex`) and the writer connection. `writeBlocking { }` takes the same lock
  for a caller that is not a coroutine: a test, or the index import worker waiting on its job.
- Every connection sets `PRAGMA busy_timeout` to `BUSY_TIMEOUT_MS`.
- Routes answer on Ktor's threads. They read through `read`, and they write only by submitting a job.
- These run inside `write`, and only there: `IndexTransfer.merge`, `Take.applyUnits`, `Take.restore`,
  `Take.backupBeforeSync`, `LibraryStore.add`, `remove` and `ensureCurrentKeys`, `Compare.recordAgreement`, and
  `PhoneSchema.migrate`. Each takes a `Db`, the writer connection, and none opens a connection of its own.
- Jobs run one at a time on one worker coroutine. An index import is a job too (`Phone.importIndex`), so it never
  writes beside a sync.

### 5.6 A take, on both sides

The same rules hold for Python's `_take_song` (lane `peer-format2`) and Kotlin's `Take` (lane `sync-take`). Each rule
below has a case in `vectors/sync/` (lane `sync-corpus`).

- **Names.** The peer's `artist`, `title`, `artists`, `album`, `duration_ms` and `variant` are written verbatim.
  `identity_key(names)` must equal the unit's key.
- **Respelling.** Suppose the library has songs whose artist's folder (`safe_name`) differs from the taken artist's
  folder in case alone, and no song with the taken folder exactly. Then each of those songs is respelled: `artist`,
  and `artists[0]` when it equals the old `artist`, take the taken spelling. The artist's folder is renamed once,
  through a temporary name, so the rename works on a case-blind file system. Each respelled song is reported (the
  `Applied.respelled` list, or `caracole peer take`'s output). Its unit changes, so the next comparison shows it if
  the peer spells it otherwise.
- **Folders.** When a song's folder changes, its files move, and `files.path` with them, in the song's savepoint.
  - The old folder's render records are dropped, so the next render makes them again.
  - The move goes file by file, through descriptors opened `O_NOFOLLOW` from the library down (on the phone,
    canonical paths under `libraryDir`, with no link followed).
  - A move that fails leaves the song whole in one folder, never in neither.
- **File names.** A name with `/`, `\`, a leading `.`, `''` or `..` is refused, as `_take_song` refuses it today.
- **Tombstones.** Taking a song forgets this side's tombstone of that key. A song new to this side is created through
  the one way songs are added (`upsert_song`, or `LibraryStore.add`, which drops a tombstone found by key or source
  id), then overwritten with the document.
- **A song absent there** is removed by `removal.remove_song`'s rules. A `removed/<key>` unit makes a tombstone only
  when neither the song nor a tombstone exists. An absent `removed/<key>` forgets the tombstone.
- **Whole or nothing.**
  - Files are fetched and sha-checked before any change.
  - The rows, the carried kv and the overrides entries change in one savepoint.
  - Python writes overrides.toml after the savepoint, and an `OverridesError` there undoes the rows through a
    savepoint that wraps both.
  - `sqlite3.IntegrityError` is caught per unit, as the other unit errors are.
  - Files no longer kept are deleted after.
- **Compare and swap.** A unit whose digest here differs from the compared one is left: "changed here since the
  comparison". A unit whose document's digest differs from the compared one there is left: "changed there since the
  comparison".

---

## 6. The skeleton

The skeleton is one step, on the branch `android/skeleton` in the worktree `.claude/worktrees/skeleton`, made from
main. It is merged into main with `git -C /home/dani/Projects/caracole merge --no-ff android/skeleton` once it
passes. The main checkout has the owner's uncommitted files (`improvements.md` modified; `android_port.md`, `run.sh`
and `temp.sh` untracked at the root): nothing touches them, and nothing is checked out there.

**Documents**
- This plan, as `docs/superpowers/plans/2026-11-03-android-port-m1-m3.md`.
- `docs/superpowers/specs/2026-11-03-conformance-corpus.md`: §3 in full, the drift protocol included.
- `docs/superpowers/specs/2026-11-03-canonical-json.md`: §4 in full, with at least 25 vectors. Each vector is
  checked in a scratch script against Python (`json.loads` and `json.dumps(sort_keys=True, separators=(",",":"),
  ensure_ascii=False)` for the text, and `hashlib`), and against the decimal rule worked by hand.
- `docs/superpowers/spikes/2026-11-03-android/`: `Sqlite.kt`, `Http.kt` and `Bench.kt` from the spikes (`.kt.txt`,
  not compiled), with a README naming what each showed.

**The corpus's frame**
- `tests/conformance/README.md`, which points to the spec, and `.gitkeep` files in `tests/conformance/data/caracole/`
  and `tests/conformance/vectors/`.
- `tests/conformance/data/caracole/schema/phone.sql` (§5.4).
- `tests/helpers/corpus.py`: `VECTORS`, `DATA`, `versions()`, `plain(obj)`, `jsonl(records, corpus=, made_by=)`,
  `check(path, content)`, `dump_fixture(conn, library_dir=None)` and `replay_fixture(conn, records,
  library_dir=None)`, exactly as §3 specifies: the fixed table list, kv upserts, `sql` lines, and `phone_*` made from
  `phone.sql`. Its test is `tests/test_corpus_helpers.py`: a round trip with `ug_index` rows passing the integrity
  checks, the table list against `sqlite_master`, `check`'s write and stale modes.
- `tests/test_conformance_schema.py`, first version: it writes `data/caracole/schema/migrations.json` =
  `{"schema": db.SCHEMA_VERSION, "statements": {"1": [stmt, …], …}}`, each script split with
  `sqlite3.complete_statement`. Lane core-db adds its vectors.
- `tests/helpers/rapidfuzz_cpp.py`: the checked Python transcription of rapidfuzz-cpp 3.3.4's
  `partial_ratio_alignment`. It is copied from `<scratchpad>/searchmap/rf_port.py`, where `<scratchpad>` is
  `/tmp/nix-shell.Q4nvbl/claude-1000/-home-dani-Projects-caracole/71827265-2369-44f5-93a9-565da48e6767/scratchpad`.
  It needs a module docstring saying what it is and that it matched rapidfuzz on 4000 of 4000 cases. Lane fuzz adds
  its test.

**Gradle and the flake**
- `android/settings.gradle.kts` includes `:mirror`, `:core`, `:server`, `:app` and `:e2e`.
- `android/build.gradle.kts` adds `org.jetbrains.kotlin.plugin.serialization` 2.2.21 (apply false).
- `android/gradle.properties`: `org.gradle.workers.max=4`.
- `android/core/build.gradle.kts`:
  - `kotlin("jvm")`, `java-test-fixtures`, the serialization plugin.
  - `api("androidx.sqlite:sqlite-bundled:2.7.1")`, `api("org.jetbrains.kotlinx:kotlinx-serialization-json:1.9.0")`,
    `api("org.jetbrains.kotlinx:kotlinx-coroutines-core:1.10.2")`, `api(project(":mirror"))`; junit 4.13.2,
    kotlin-test-junit and kotlinx-coroutines-test 1.10.2 for tests and testFixtures.
  - `sourceSets.main.resources.srcDir("../../tests/conformance/data")`.
  - Every `Test` task gets `systemProperty("caracole.conformance", <absolute ../../tests/conformance/vectors>)`, with
    the directory declared as an input.
- `android/server/build.gradle.kts`:
  - `kotlin("jvm")`, `java-test-fixtures`, `api(project(":core"))`, `implementation("io.ktor:ktor-server-cio:3.3.3")`,
    and `testImplementation(testFixtures(project(":core")))`, `testFixturesApi(testFixtures(project(":core")))`.
  - A `Sync` task, `copyLibraryAssets`, copies `../../src/caracole/library_assets/` (`*.js`, `*.css`, `*.html`; no
    filtering, no line-end change) into `build/generated/assets/caracole/library_assets/`. That folder is a main
    resource dir, and `processResources` depends on the task. The order of the files comes from
    `caracole/page/library_assets.json` (lane library-page).
  - The same corpus property.
- `android/e2e/build.gradle.kts`: `kotlin("jvm")`; `:server` and the testFixtures of `:core` and `:server`; junit.
  - Its `test` task passes the `caracole.e2e.*` project properties through as system properties.
  - It sets `outputs.upToDateWhen { false }`.
  - It is skipped, by `Assume`, without them.
- `android/app/build.gradle.kts`:
  - `implementation(project(":server"))` and `androidTestImplementation(testFixtures(project(":core")))`.
  - `ndk { abiFilters += listOf("arm64-v8a", "x86_64") }`.
  - Packaging excludes `org/fusesource/jansi/internal/native/**`.
  - A `Copy` task copies `../../tests/conformance/vectors` into `build/generated/conformanceAssets/conformance/`,
    which is the androidTest assets srcDir. A plain srcDir puts the files at the assets' root.
- `android/app/proguard-rules.pro`: `-dontwarn java.lang.management.ManagementFactory` and
  `-dontwarn java.lang.management.RuntimeMXBean`.
- `android/flake.nix`: `jdk = pkgs.jdk17_headless`.
- New files go in with `git add` before any Nix build.

**Kotlin**
- Every stub file of §5.1 and §5.2, with its signatures, and the stub rules of §5.
- Written whole (**final**): `core/Stub.kt`, `Songs.kt`, `Hits.kt`, `Source.kt`, `Assembly.kt`, LaCuerda's two key
  delegations, and in `:mirror`: `Entry.unit`/`digest` (defaults null, not yet parsed), `UnitGate`, `Gate`,
  `Mirror.pageFor` and `Looked`.
- Written as a first working version (**working**): `core/db/Database.kt` (Database, Db, Row, DatabaseTooNew,
  PhoneSchema), from the spike's `Sqlite.kt`:
  - the migrations from `migrations.json`;
  - `read`, `write` and `writeBlocking`;
  - `busy_timeout`, savepoints and kv (`kvSetJson` calls `PyJson.dumps`, a stub until lane canonical lands);
  - attach and `backupTo`.

  So `TestDb.fresh` and `Fixtures.load` work from the start.
- Neutral (**neutral**): `Units.digestOf` (null), `Suggest.*` (empty), `JobsRoutes` (`{active:0, jobs:[]}`, and
  `/api/jobs/N` 404 JSON), `SearchRoutes` (`{query, library:[], index:[], short:true}`), `SyncRoutes` (`GET
  /api/sync` `{server:null, name, address:null, peers:[]}`; POSTs 409 "Sync isn't built yet."), `LibraryRoutes`
  (POSTs 409), `PageRoutes` (the message page "Not built yet."), `LibraryFiles.serve` (null).
- testFixtures of `:core`, in `android/core/src/testFixtures/kotlin/io/github/danielhp95/caracole/core/testing/`:
  - `Corpus.kt` (§3, with `Corpus.open`);
  - `Fixtures.kt`: `Fixtures.load(db: Db, name: String, libraryDir: File? = null)` and
    `Fixtures.loadRaw(file: File, name: String)`;
  - `TestDb.kt`: `TestDb.fresh(dir: File): Database`.
- testFixtures of `:server`: an empty `server/testing/` package for server-shell's `TestApp`.
- One trivial test per module, so `gradle -p android test` is green with the stubs untouched.

**Python**
- `library_page.py`:
  - Extract the pure `assemble_page(data, controls, *, problem, library_name)` from `build_library_page`, whose
    behaviour is unchanged.
  - Add `WebControls.sync: bool = False` and the served-only blanks `__TABSYNC__` (before `__TABREQUESTS__` in
    body.html) and `__SYNC__`, filled verbatim with the templates `sync-tab.html` and `sync-panel.html` while `sync`
    is True, and with nothing otherwise.
- `src/caracole/library_assets/`:
  - `sync-tab.html`: the tab button `tab-sync`, "Sync".
  - `sync-panel.html`: the panel `#sync`, saying "Sync isn't built yet.".
  - `sync.js`: a header comment, and an IIFE that returns unless `#sync` exists.
  - `sync.css`: a header comment.
  - All four are listed in `TEMPLATES`, `SCRIPTS` and `STYLESHEETS`, and `test_library_assets.py` stays green.
  - From here on, the Sync tab's markup is these templates alone, so the page is a pure function of the assets on
    both sides.

**Text the lanes fill in.** Each heading's body is "Not built yet.", and each lane edits only its own section.
- `docs/usage.md`, under "Two caracoles":
  - `### The phone pushes its changes (POST /peer/push)` (peer-push-routes);
  - `### Syncing by hand: peer sync --push, --choose, --compared` (peer-sync-cli);
  - `### The Sync tab` (sync-tab);
  - `### What the offline copy lists` (offline-units).
- `android/README.md`:
  - `## Search with the computer off` (app-local);
  - `## Sync from the phone` (app-sync).
- `AGENTS.md`:
  - A `#### android/` section under Layout: the modules and packages of §2, which Python module each package ports,
    `tests/conformance/`.
  - Under Rules, `#### The phone agrees with the computer to the byte`:
    - the corpus and its regeneration command, and the drift protocol of §3;
    - a SCHEMA_VERSION or KEY_VERSION bump moves the phone in lockstep (migrations.json, `Normalize.KEY_VERSION`,
      `LibraryStore.ensureCurrentKeys`);
    - `:core` never calls a JDK or ICU text API.
  - The web/app.py line: a route declares its body kind and limit.
  - The "One caracole at a time" invariant: caracole serve also writes the push staging and a temporary index export
    (§1), and nothing else.
  - The Development table: `nix develop ./android -c gradle -p android test`.
  - After the skeleton, only the integration step edits AGENTS.md.

The skeleton is done when:
- `nix develop -c pytest -q` passes.
- `nix develop ./android -c gradle -p android test assembleDebug` passes.
- Every §5 signature compiles.
- `git grep -n 'TODO("lane\|stub("lane'` lists only lane-owned files.
- `TestDb.fresh` migrates, and `Fixtures.load` replays a fixture written by `test_corpus_helpers.py`.

---

## 7. The lanes

### 7.0 How a lane works

**Worktrees and branches.**
- Each lane works in its own worktree, `.claude/worktrees/<id>`, on the branch `android/<id>` made from main:
  `git -C /home/dani/Projects/caracole worktree add .claude/worktrees/<id> -b android/<id> main`. A lane reuses the
  worktree and the branch when they already exist.
- Nothing is checked out in the main checkout, and nothing touches its uncommitted files.
- Every command in a brief runs from the lane's worktree. The root shell sets `PYTHONPATH` from
  `git rev-parse --show-toplevel`, and `gradle -p android` and the corpus paths are relative.
- A new file is `git add`ed before any Nix build, since the flake sees only what git tracks.

**Phases.** A lane whose producers (`depends_on`) haven't all merged into main may still have work it can do now.
- **Phase A** runs only when `start_early` is true. The lane does the part its brief names as Phase A, against the
  skeleton's declared interfaces:
  - the Python generators and their vectors;
  - the code, written against the declared signatures;
  - every test that can pass without the producers.

  It commits on its branch, and its report ends with `waiting on: <lanes>`.
- **Phase B** starts once every producer has merged. The orchestrator starts it again, with the same brief: a fresh
  agent, or the same one resumed. The lane merges main into its branch, finishes, and makes every done_when hold.
- A lane with `start_early` false starts only in Phase B.
- A lane with no `depends_on` runs whole at once.

**Merging.**
- A lane merges once every done_when holds, with main merged in:
  `git -C /home/dani/Projects/caracole merge --no-ff android/<id>`.
- When `.git/index.lock` is held, it waits and retries. It never forces, never rebases main, and never merges a
  branch with a failing done_when.
- Its report gives the merge commit.

**Drift.** Before merging, a Python lane that regenerated a corpus runs `nix develop ./android -c gradle -p android
test` and follows §3's drift protocol.

**The shared machine** (24 cores, 62 GB, one `/dev/shm`):
- At most 6 lanes run at once.
- The test loop is `nix develop -c pytest -q -n 4 -m "not slow" <tests>` and `nix develop ./android -c gradle -p
  android <module>:test`. `gradle.properties` caps Gradle at 4 workers.
- The whole suite, `nix develop -c pytest -q`, runs once before merging.
- Nobody runs `gradle --stop`, and nobody kills a Gradle or Kotlin daemon they did not start; daemons time out by
  themselves.
- Nobody runs `omnibin-shell`.
- No test sends a live request to any site.
- No lane runs an emulator. Every on-device test is compiled by its lane (`assembleDebugAndroidTest`) and run by the
  integration step, one emulator at a time.

**Commits.**
- Conventional commits scoped by area: `feat(android): …`, `feat(peer): …`, `feat(web): …`, `fix(search): …`,
  `test(conformance): …`, `docs: …`.
- Docs go in the same commit as the behaviour.
- No Claude or AI attribution anywhere.

**Shared files.**
- Lanes own disjoint files. A file owned by two lanes is owned **in sequence**, and the later lane depends on the
  earlier one:
  - `android/app/**`: app-local, then app-sync;
  - `commands/peer.py` and `tests/test_commands_peer.py`: peer-format2, then peer-push-routes, then peer-sync-cli;
  - `tests/test_web_peer.py`: peer-format2, then peer-push-routes;
  - `web/app.py` and `tests/test_web_app.py`: peer-push-routes, then sync-tab, which edits one line of each.
- docs/usage.md and android/README.md are owned by section.
- AGENTS.md is the skeleton's, then the integration step's.

Every brief below starts with this preamble, filled in for its lane:

> Repo /home/dani/Projects/caracole. Your lane: `<id>`, branch `android/<id>`, in the worktree
> `.claude/worktrees/<id>` (§7.0). Read docs/superpowers/plans/2026-11-03-android-port-m1-m3.md §7.0, then the
> sections named below. Depends on: … Phase: … Test first.

In short (A: has a Phase A):

| Lane | Side | M | Depends on | Early | ~Lines |
|---|---|---|---|---|---|
| core-db | mixed | M1 | – | – | 800 |
| py-unicode | mixed | M1 | – | – | 1500 |
| pinyin | mixed | M1 | – | – | 900 |
| fuzz | mixed | M1 | – | – | 900 |
| canonical | mixed | M1 | – | – | 1000 |
| keys | mixed | M1 | py-unicode, pinyin | A | 2000 |
| search-corpus | python | M2 | – | – | 1200 |
| search-query | kotlin | M2 | keys, fuzz, search-corpus | A | 900 |
| search-ug | kotlin | M2 | search-query | A | 1700 |
| search-suggest | kotlin | M2 | search-query | A | 1300 |
| search-sites | kotlin | M2 | search-query | A | 1400 |
| search-lacuerda | kotlin | M2 | search-query | A | 1500 |
| song-names | kotlin | M2 | keys, search-corpus | A | 600 |
| index-transfer | mixed | M2 | keys, canonical, search-ug, search-sites, search-lacuerda | A | 1700 |
| server-shell | mixed | M2 | – | – | 2200 |
| library-page | mixed | M2 | server-shell, keys | A | 1500 |
| search-routes | kotlin | M2 | server-shell, library-page, search-ug, search-suggest, search-sites, search-lacuerda, song-names | A | 1700 |
| app-local | kotlin | M2 | server-shell, library-page, search-routes, index-transfer | A | 1200 |
| peer-format2 | python | M3 | canonical | A | 1100 |
| peer-push-routes | python | M3 | peer-format2 | A | 1500 |
| peer-sync-cli | python | M3 | peer-push-routes | – | 700 |
| sync-corpus | python | M3 | peer-format2 | A | 900 |
| sync-tab | mixed | M3 | peer-sync-cli, library-page | A | 1900 |
| offline-units | mixed | M3 | – | – | 600 |
| jobs | kotlin | M3 | server-shell, sync-tab | A | 1100 |
| sync-units | kotlin | M3 | keys, canonical, sync-corpus | A | 1500 |
| sync-take | kotlin | M3 | sync-units | A | 1900 |
| sync-client | kotlin | M3 | sync-take, peer-push-routes | A | 1500 |
| phone-sync-routes | kotlin | M3 | jobs, sync-client, song-names, sync-tab | A | 1400 |
| app-sync | kotlin | M3 | app-local, phone-sync-routes, offline-units | – | 600 |
| e2e-jvm | mixed | M3 | phone-sync-routes, offline-units, index-transfer, search-routes, peer-sync-cli, sync-tab | A | 1300 |

### 7.1 Each lane in full

#### core-db: caracole's schema in the bundled SQLite, hardened

- Branch `android/core-db` · mixed · M1 · about 800 lines · depends on nothing · runs at once
- Goal: The skeleton's working Database becomes caracole's db.py on the phone: the migrations and their backup rule exactly, the phone's schema in one transaction, the connection contract of §5.5, and tests proving it is the bundled SQLite 3.50.1 with FTS5 that runs, on the JVM and (compiled now, run by integration) on Android.
- Owns: `android/core/src/main/kotlin/io/github/danielhp95/caracole/core/db/**`; `android/core/src/test/kotlin/io/github/danielhp95/caracole/core/db/**`; `tests/test_conformance_schema.py`; `tests/conformance/data/caracole/schema/migrations.json`; `tests/conformance/vectors/schema/**`; `android/app/src/androidTest/kotlin/io/github/danielhp95/caracole/BundledSqliteTest.kt`
- Must not touch: src/caracole/db.py; tests/conformance/data/caracole/schema/phone.sql; android/*/build.gradle.kts; android/settings.gradle.kts; android/flake.nix; AGENTS.md; tests/helpers/corpus.py; android/core/src/testFixtures/**; any other lane's owns
- Provides: core.db.Database/Db/Row/DatabaseTooNew/PhoneSchema to §5.1 and §5.5; caracole/schema/migrations.json; vectors/schema/*
- Consumes: the skeleton's working Database.kt, migrations.json generator, helpers.corpus, TestDb, Corpus
- Tests: tests/test_conformance_schema.py; android/core/src/test/kotlin/io/github/danielhp95/caracole/core/db/DatabaseTest.kt; android/core/src/test/kotlin/io/github/danielhp95/caracole/core/db/FtsTest.kt; android/core/src/test/kotlin/io/github/danielhp95/caracole/core/db/ThreadsTest.kt; android/app/src/androidTest/kotlin/io/github/danielhp95/caracole/BundledSqliteTest.kt
- Done when: nix develop -c pytest -q passes, tests/test_conformance_schema.py included; nix develop ./android -c gradle -p android :core:test passes: sqlite_master and table_info equal Python's, the source id and ENABLE_FTS5 asserted; nix develop ./android -c gradle -p android :app:assembleDebugAndroidTest passes (BundledSqliteTest compiles; integration runs it on the emulator); changing db.py's migrations without regenerating makes tests/test_conformance_schema.py fail

Brief:

> Repo /home/dani/Projects/caracole. Lane core-db: branch android/core-db, worktree .claude/worktrees/core-db (git -C /home/dani/Projects/caracole worktree add .claude/worktrees/core-db -b android/core-db main, or reuse them); never touch the main checkout's files. First read the plan, docs/superpowers/plans/2026-11-03-android-port-m1-m3.md, §7.0 (phases, merging, drift, and the shared machine: pytest -n 4 in the loop, the whole suite once before merging, never `gradle --stop`, no omnibin-shell, no live request, no emulator). Depends on: nothing. Phase: no lane comes before you: do it all at once. Test first; conventional commits; no Claude or AI attribution. When every done_when holds with main merged in: git -C /home/dani/Projects/caracole merge --no-ff android/core-db.
>
> Plan sections: §3, §5.1 (core/db), §5.4, §5.5.
>
> The skeleton wrote a working core/db/Database.kt from the spike (docs/superpowers/spikes/2026-11-03-android/Sqlite.kt.txt) and the first tests/test_conformance_schema.py (migrations.json). You make both exact.
>
> Python, tests/test_conformance_schema.py: keep migrations.json; add vectors/schema/sqlite_master.json (type, name, tbl_name, sql of a freshly migrated Python database, sorted by type and name) and vectors/schema/pragmas.json (each table's PRAGMA table_info), all through helpers.corpus.check; a test that migrations.json's "schema" equals db.SCHEMA_VERSION.
>
> Kotlin, core/db/:
> - Migration exactly as db.py: back up with VACUUM INTO <path>.v<N>.bak only when 0 < user_version < 15 (db.py's `if current and pending`); each version in BEGIN IMMEDIATE ... PRAGMA user_version=N ... COMMIT; DatabaseTooNew above 15; once per path under an in-process lock.
> - PhoneSchema.migrate runs caracole/schema/phone.sql and sets kv phone:schema in one BEGIN IMMEDIATE.
> - §5.5: one writer connection under `writes`; `read {}` from a pool of `readers` connections, each used by one thread at a time (THREADSAFE=2); `writeBlocking`; PRAGMA foreign_keys=ON, journal_mode=WAL, synchronous=NORMAL and busy_timeout on every connection.
> - savepoint nests (SAVEPOINT/RELEASE/ROLLBACK TO); bound parameters Long, Int, Double, String, ByteArray, Boolean (0/1), null; lists kept under 32,766 variables. kvSetJson stays a call to core.json.PyJson.dumps (lane canonical tests its bytes).
> Tests: the migrated sqlite_master, minus phone_* tables, equals sqlite_master.json, and table_info equals pragmas.json; Database.SCHEMA_VERSION equals migrations.json's schema; sqlite_source_id() == Database.SQLITE_SOURCE_ID and PRAGMA compile_options holds ENABLE_FTS5 (this catches an interposed system SQLite, which is why android/flake.nix uses jdk17_headless); a trigram LIKE goes through ug_keys_fts (EXPLAIN QUERY PLAN names VIRTUAL TABLE INDEX); unicode61 MATCH on ug_artists_fts; the ug_artist_words fts5vocab; json_each; nested savepoints roll back; DatabaseTooNew; the backup rule; PRAGMA integrity_check and each FTS 'integrity-check' after inserts through the triggers; backupTo; ThreadsTest: concurrent reads on several threads while a write holds the lock, and a write waiting on busy_timeout rather than failing.
> android/app/src/androidTest/.../BundledSqliteTest.kt: the same source id, compile options (FTS5), migrations, trigram LIKE, MATCH and fts5vocab on the device. It must compile (assembleDebugAndroidTest); the integration step runs it on the emulator, so no emulator is needed here.
> Commit: feat(android): caracole's schema in the bundled SQLite, as db.py migrates it.

#### py-unicode: Python's Unicode and string semantics in Kotlin

- Branch `android/py-unicode` · mixed · M1 · about 1500 lines · depends on nothing · runs at once
- Goal: Kotlin code can do what Python's str methods, unicodedata 16.0.0 and re's \w \s \d \b and IGNORECASE do, code point for code point, from tables Python generates, with no JDK or ICU text API.
- Owns: `android/core/src/main/kotlin/io/github/danielhp95/caracole/core/py/**`; `android/core/src/test/kotlin/io/github/danielhp95/caracole/core/py/**`; `tests/test_conformance_unicode.py`; `tests/conformance/data/caracole/unicode/**`; `tests/conformance/vectors/unicode/**`
- Must not touch: src/caracole/**; android/*/build.gradle.kts; AGENTS.md; tests/helpers/corpus.py; android/core/src/testFixtures/**; any other lane's owns
- Provides: core.py.Py (asciiLower included); core.py.PyUnicode; core.py.PyRegex; ForbiddenApiTest over all of :core
- Consumes: helpers.corpus, Corpus.kt (skeleton)
- Tests: tests/test_conformance_unicode.py; android/core/src/test/kotlin/io/github/danielhp95/caracole/core/py/PyUnicodeTest.kt; android/core/src/test/kotlin/io/github/danielhp95/caracole/core/py/PyTest.kt; android/core/src/test/kotlin/io/github/danielhp95/caracole/core/py/PyRegexTest.kt; android/core/src/test/kotlin/io/github/danielhp95/caracole/core/py/ForbiddenApiTest.kt
- Done when: nix develop -c pytest -q passes; nix develop ./android -c gradle -p android :core:test passes, every record of vectors/unicode/*.jsonl matching; ForbiddenApiTest passes on the whole :core main tree as merged

Brief:

> Repo /home/dani/Projects/caracole. Lane py-unicode: branch android/py-unicode, worktree .claude/worktrees/py-unicode (git -C /home/dani/Projects/caracole worktree add .claude/worktrees/py-unicode -b android/py-unicode main, or reuse them); never touch the main checkout's files. First read the plan, docs/superpowers/plans/2026-11-03-android-port-m1-m3.md, §7.0 (phases, merging, drift, and the shared machine: pytest -n 4 in the loop, the whole suite once before merging, never `gradle --stop`, no omnibin-shell, no live request, no emulator). Depends on: nothing. Phase: no lane comes before you: do it all at once. Test first; conventional commits; no Claude or AI attribution. When every done_when holds with main merged in: git -C /home/dani/Projects/caracole merge --no-ff android/py-unicode.
>
> Plan sections: §1, §3, §5.1 (core/py).
>
> Why: normalize.py, search.py and song_names.py rely on Python 3.14.7's unicodedata 16.0.0: NFKD/NFKC/NFC, combining, category, name ('LATIN' in it), str.lower() with Final_Sigma ('ΤΡΥΠΕΣ'.lower() == 'τρυπες'), casefold(), upper() ('ß' -> 'SS'), isalnum/isalpha/isdecimal/isdigit/isnumeric/isspace (isspace includes \x1c-\x1f and U+0085), and re's Unicode classes: \w is isalnum() or '_' (so it excludes Mn/Mc/Me: slug_key('हिंदी') is 'ह-द'), \d is every Nd ('２０１１' matches), \s is isspace. IGNORECASE follows sre ('i' matches 'ı', 's' matches 'ſ', the Kelvin sign 'k'). JDK 17 is Unicode 13, Android's ICU varies by device, and Android's java.util.regex is ICU-backed while the JVM tests run OpenJDK's. So :core never calls java.text.Normalizer, Character.is*/getType/getName, String.lowercase/uppercase, or a regex's predefined classes or case-insensitive flags.
>
> Python, tests/test_conformance_unicode.py, runtime tables under tests/conformance/data/caracole/unicode/ (a compact text format, e.g. hex range lines 'start end value', documented in the docstring): property flags (alnum, alpha, decimal, digit, numeric, space, word, printable, latin-by-name), general category, canonical combining class, canonical and compatibility decompositions with the composition exclusions NFC/NFKC need, full lower/upper/casefold mappings with the cased and case-ignorable sets Final_Sigma needs, and sre's IGNORECASE classes. Build those classes as sre does, never by testing pairs (1.1 M squared is infeasible): group every code point by `_sre.unicode_tolower(cp)`, then join the groups `re._casefix._EXTRA_CASES` links (both exist in Python 3.14.7; grouping every code point takes under a second); assert the relation is transitive and fail naming the code points if not; the representative is a class's smallest member. Vectors: vectors/unicode/strings.jsonl (lower, upper, casefold, nfc, nfd, nfkc, nfkd and the predicates over every code point a table maps non-trivially, and 3,000 seeded random strings mixing scripts, combining marks, Hangul, Greek sigma and supplementary planes, no lone surrogates); vectors/unicode/py.jsonl (round(x,1) and round(x,2) over tricky floats (0.25, 0.35, 94.75, 1e16 ...), sum() over float lists (sum([0.1]*10)==1.0), str.split()/strip() with exotic spaces, negative slices, sorted() of strings with supplementary and U+E000-FFFF characters, Counter.most_common(1) ties, ASCII lowering); vectors/unicode/regex.jsonl (re.split/findall/fullmatch of \w+, [\W_]+, \d+, \s+, \b over the random strings, and IGNORECASE matches of literal patterns). Under 3 s, or marked slow.
>
> Kotlin: core/py/Py.kt, PyUnicode.kt and PyRegex.kt to §5.1, on code points (IntArray). PyRegex.compile rewrites \w \W \s \S \d \D into explicit [\x{...}-\x{...}] classes and \b/\B into lookarounds over WORD, and accepts no flags; ignoreCase maps a subject length-preservingly to representatives so a pattern written in representatives can match. ForbiddenApiTest scans android/core/src/main/kotlin and fails naming the file and line for: `.lowercase(`, `.uppercase(`, `Normalizer`, `Character.getType`, `Character.getName`, `Character.is` except the allow-listed isHighSurrogate, isLowSurrogate, isSurrogate, toChars and charCount, `IGNORE_CASE`, `CASE_INSENSITIVE`, `UNICODE_CHARACTER_CLASS`, and \w \s \d \b inside the string argument of `Regex(`, `.toRegex(` or `Pattern.compile(` outside core/py/. It never scans other string literals: a JSON writer's "\\b" escape is not a regex.
> Commit: feat(android): Python's Unicode semantics, from Python's own tables.

#### pinyin: pypinyin 0.55.0 in Kotlin

- Branch `android/pinyin` · mixed · M1 · about 900 lines · depends on nothing · runs at once
- Goal: Pinyin.lazyPinyin and Pinyin.heteronyms give exactly what pypinyin 0.55.0 gives for caracole's calls.
- Owns: `android/core/src/main/kotlin/io/github/danielhp95/caracole/core/pinyin/**`; `android/core/src/test/kotlin/io/github/danielhp95/caracole/core/pinyin/**`; `tests/test_conformance_pinyin.py`; `tests/conformance/data/caracole/pinyin/**`; `tests/conformance/vectors/pinyin/**`
- Must not touch: src/caracole/**; android/*/build.gradle.kts; AGENTS.md; tests/helpers/corpus.py; any other lane's owns
- Provides: core.pinyin.Pinyin
- Consumes: helpers.corpus, Corpus.kt
- Tests: tests/test_conformance_pinyin.py; android/core/src/test/kotlin/io/github/danielhp95/caracole/core/pinyin/PinyinTest.kt
- Done when: nix develop -c pytest -q passes; nix develop ./android -c gradle -p android :core:test passes, every record of vectors/pinyin/*.jsonl matching; once py-unicode has merged, its ForbiddenApiTest passes over core/pinyin/

Brief:

> Repo /home/dani/Projects/caracole. Lane pinyin: branch android/pinyin, worktree .claude/worktrees/pinyin (git -C /home/dani/Projects/caracole worktree add .claude/worktrees/pinyin -b android/pinyin main, or reuse them); never touch the main checkout's files. First read the plan, docs/superpowers/plans/2026-11-03-android-port-m1-m3.md, §7.0 (phases, merging, drift, and the shared machine: pytest -n 4 in the loop, the whole suite once before merging, never `gradle --stop`, no omnibin-shell, no live request, no emulator). Depends on: nothing. Phase: no lane comes before you: do it all at once. Test first; conventional commits; no Claude or AI attribution. When every done_when holds with main merged in: git -C /home/dani/Projects/caracole merge --no-ff android/pinyin.
>
> Plan sections: §3, §5.1 (core/pinyin).
>
> caracole calls pypinyin three ways (src/caracole/normalize.py:283-294 and :561-571): lazy_pinyin(s) (Style.NORMAL, errors='default'), lazy_pinyin(text, errors='ignore'), and pinyin(c, style=Style.NORMAL, heteronym=True)[0]. viewer/pinyin.py's Style.TONE is M5, out of this round. Read pypinyin's algorithm in the store (`nix develop -c python -c 'import pypinyin,os;print(os.path.dirname(pypinyin.__file__))'`), converter.py, core.py, seg/simpleseg.py and seg/mmseg.py, not from memory: simple_seg splits on pypinyin's RE_HANS (NOT caracole's _HAN: it includes U+3007, PUA E815-E864, FA18 and Ext C-I); each Han run goes through mmseg forward maximum matching over the prefix set of PHRASES_DICT (no_non_phrases=True); a phrase takes its dictionary pinyin, a lone char PINYIN_DICT[ord].split(',')[0], else itself (errors='default') or nothing ('ignore'); Style.NORMAL strips tones and writes ü as v ('绿色' -> ['lv','se']); _remove_dup_and_empty applies to heteronyms.
>
> Python, tests/test_conformance_pinyin.py: runtime data data/caracole/pinyin/chars.txt (code point in hex, then its NORMAL readings in pypinyin's order, comma-separated), phrases.txt (phrase, then its NORMAL syllables), both converted by pypinyin's own style functions so Kotlin strips no tone, and hans.txt (RE_HANS's ranges). Vectors: vectors/pinyin/lazy.jsonl (lazy_pinyin in both error modes over every phrase key holding a polyphone, 3,000 seeded random Han/Latin/kana/punctuation mixes, the string literals of tests/test_normalize.py and tests/test_search.py, and supplementary-plane Han) and vectors/pinyin/heteronyms.jsonl (every code point of PINYIN_DICT). Vectors under about 6 MB; the data plain text (it ships in the APK).
>
> Kotlin: core/pinyin/Pinyin.kt to §5.1, loading the data lazily from the classpath (caracole/pinyin/...), on code points (String.codePointAt and Character.charCount are allowed), with no JDK text API: nothing here needs py-unicode.
> Commit: feat(android): pypinyin's readings, ported with its dictionaries.

#### fuzz: rapidfuzz's scores, exactly

- Branch `android/fuzz` · mixed · M1 · about 900 lines · depends on nothing · runs at once
- Goal: Fuzz.ratio, tokenSortRatio, partialRatioAlignment and extract give rapidfuzz 3.14.5's exact doubles and alignments (its C++ core, rapidfuzz-cpp 3.3.4).
- Owns: `android/core/src/main/kotlin/io/github/danielhp95/caracole/core/fuzz/**`; `android/core/src/test/kotlin/io/github/danielhp95/caracole/core/fuzz/**`; `tests/test_conformance_fuzz.py`; `tests/helpers/rapidfuzz_cpp.py`; `tests/test_rapidfuzz_cpp.py`; `tests/conformance/vectors/fuzz/**`
- Must not touch: src/caracole/**; android/*/build.gradle.kts; AGENTS.md; tests/helpers/corpus.py; any other lane's owns
- Provides: core.fuzz.Fuzz
- Consumes: tests/helpers/rapidfuzz_cpp.py (the skeleton committed it)
- Tests: tests/test_rapidfuzz_cpp.py; tests/test_conformance_fuzz.py; android/core/src/test/kotlin/io/github/danielhp95/caracole/core/fuzz/FuzzTest.kt
- Done when: nix develop -c pytest -q passes; nix develop ./android -c gradle -p android :core:test passes, every record of vectors/fuzz/*.jsonl equal (doubles ==)

Brief:

> Repo /home/dani/Projects/caracole. Lane fuzz: branch android/fuzz, worktree .claude/worktrees/fuzz (git -C /home/dani/Projects/caracole worktree add .claude/worktrees/fuzz -b android/fuzz main, or reuse them); never touch the main checkout's files. First read the plan, docs/superpowers/plans/2026-11-03-android-port-m1-m3.md, §7.0 (phases, merging, drift, and the shared machine: pytest -n 4 in the loop, the whole suite once before merging, never `gradle --stop`, no omnibin-shell, no live request, no emulator). Depends on: nothing. Phase: no lane comes before you: do it all at once. Test first; conventional commits; no Claude or AI attribution. When every done_when holds with main merged in: git -C /home/dani/Projects/caracole merge --no-ff android/fuzz.
>
> Plan sections: §3, §5.1 (core/fuzz).
>
> Search's readings depend on rapidfuzz's exact numbers and windows (src/caracole/search.py _Query.readings; lacuerda_index.py:814-874). Facts checked: ratio is exactly (1.0 - indel_dist/(len1+len2))*100 (not 100-100*d/ls: they differ in 46% of cases), and ratio('','')==100. partial_ratio_alignment follows rapidfuzz-cpp 3.3.4's fuzz_impl.hpp: full windows searched in bisection order with strict '<' and pruning, scored 1-best/(2*len1); then prefixes s2[:i] for i<len1 only when their last char is in s1's set; then suffixes from len2-len1; the first strictly better wins and 100 returns at once; no separate path past 64 chars. The pure-Python fuzz_py differs in about 27% of cases: never port it. token_sort_ratio splits with rapidfuzz's is_space, whose set depends on the string's storage width: NBSP and U+0085 are spaces only when the string holds a char above U+00FF; tokens sort by code point. process.extract(query, choices, scorer=fuzz.ratio, score_cutoff=c, limit=n) sorts by score descending, then choice index ascending, and keeps sim >= c. No processor anywhere (rapidfuzz 3's default is None). Inputs are code points.
>
> The skeleton committed tests/helpers/rapidfuzz_cpp.py, a Python transcription of the C++ partial_ratio_alignment that matched the installed rapidfuzz on 4000 of 4000 random cases; it is the reference for Kotlin. Write tests/test_rapidfuzz_cpp.py, comparing it with rapidfuzz on seeded random pairs.
>
> Python, tests/test_conformance_fuzz.py: vectors/fuzz/ratio.jsonl, token_sort.jsonl, partial_alignment.jsonl (score, src_start, src_end, dest_start, dest_end) and extract.jsonl over 3,000 short and 3,000 long seeded random pairs (Latin, accented, CJK, supplementary, spaces of every kind, NBSP with and without a char above U+00FF), the pairs of caracole's search tests (e.g. 'banma' in 'song dongye ban ma ban ma': C++ dest 19-24), empty strings, and extract cases with ties and cutoffs 80 and 90.
>
> Kotlin: core/fuzz/Fuzz.kt to §5.1: an exact LCS-based Indel distance (bit-parallel or DP; exactness is what matters) and the formulas above, on code points. No JDK text API (py-unicode's ForbiddenApiTest will scan it). Tests compare doubles with ==.
> Commit: feat(android): rapidfuzz's ratio, token sort and partial alignment, ported from its C++ core.

#### canonical: Canonical JSON, the stored-JSON hash and kv text, both sides

- Branch `android/canonical` · mixed · M1 · about 1000 lines · depends on nothing · runs at once
- Goal: One definition of a unit's canonical JSON, its digest, FORMAT 2's hash of stored JSON and the kv text db.kv_set_json writes, as Python (src/caracole/canonical.py) and Kotlin (core/json), held together by vectors.
- Owns: `src/caracole/canonical.py`; `tests/test_canonical.py`; `tests/test_conformance_canonical.py`; `tests/conformance/vectors/canonical/**`; `android/core/src/main/kotlin/io/github/danielhp95/caracole/core/json/**`; `android/core/src/test/kotlin/io/github/danielhp95/caracole/core/json/**`
- Must not touch: src/caracole/peer_sync.py; docs/superpowers/specs/2026-11-03-canonical-json.md (report a spec change; the skeleton's text is the contract); android/*/build.gradle.kts; AGENTS.md; android/core/src/main/kotlin/io/github/danielhp95/caracole/core/db/**; any other lane's owns
- Provides: caracole.canonical (dumps, digest, stored_hash); core.json.Canonical; core.json.PyJson (so Db.kvSetJson writes db.kv_set_json's bytes)
- Consumes: the canonical-JSON spec (skeleton)
- Tests: tests/test_canonical.py; tests/test_conformance_canonical.py; android/core/src/test/kotlin/io/github/danielhp95/caracole/core/json/CanonicalTest.kt; android/core/src/test/kotlin/io/github/danielhp95/caracole/core/json/PyJsonTest.kt (Db.kvSetJson through TestDb included)
- Done when: nix develop -c pytest -q passes; nix develop ./android -c gradle -p android :core:test passes, every canonical and pydumps vector equal byte for byte; canonical.digest(v) == peer_sync.digest_of(v) for every unit value of tests/test_peer_sync.py's libraries (a test); Db.kvSetJson of each pydumps vector's value writes exactly Python's text (a test through TestDb)

Brief:

> Repo /home/dani/Projects/caracole. Lane canonical: branch android/canonical, worktree .claude/worktrees/canonical (git -C /home/dani/Projects/caracole worktree add .claude/worktrees/canonical -b android/canonical main, or reuse them); never touch the main checkout's files. First read the plan, docs/superpowers/plans/2026-11-03-android-port-m1-m3.md, §7.0 (phases, merging, drift, and the shared machine: pytest -n 4 in the loop, the whole suite once before merging, never `gradle --stop`, no omnibin-shell, no live request, no emulator). Depends on: nothing. Phase: no lane comes before you: do it all at once. Test first; conventional commits; no Claude or AI attribution. When every done_when holds with main merged in: git -C /home/dani/Projects/caracole merge --no-ff android/canonical.
>
> Plan sections: §4 and docs/superpowers/specs/2026-11-03-canonical-json.md (the contract, with its worked vectors); §5.1 (core/json).
>
> Python, new module src/caracole/canonical.py (standard library only, with a module docstring):
> - dumps(value) -> str: json.dumps(value, sort_keys=True, separators=(',',':'), ensure_ascii=False), refusing a lone surrogate (ValueError).
> - digest(value) -> str: sha256 hex of dumps' UTF-8; equal to peer_sync.digest_of for every value peer_sync makes today.
> - stored_hash(text: str | None) -> str | None, §4's H: json.loads(text) with its defaults decides what is JSON (raw control characters, '01', '+1', '.5', a BOM and an integer over 4300 digits are not); parse_float keeps the literal, object_pairs_hook keeps the last duplicate; a non-integral literal is written as its exact decimal value computed on its digits (never Decimal.normalize() under the default 28-digit context, never a float), plain notation, trailing fractional zeros and a trailing '.' dropped, '-0' as '0'; an exponent beyond ±1000 or a lone surrogate makes the text not canonicalizable; NaN, Infinity and -Infinity as is; text that is not JSON or not canonicalizable hashes as sha256(text.encode('utf-8', 'surrogatepass')).
> Do NOT change peer_sync.py: lane peer-format2 switches it to canonical.py.
> tests/test_canonical.py: the spec's vectors and properties (FORMAT 1 digests unchanged for float-free values; 238.0 and 238 hash equal; key order by code point: U+FF61 before U+1F600; 0.12345678901234567890123456789012345 kept whole).
>
> Vectors, tests/test_conformance_canonical.py: vectors/canonical/dumps.jsonl (escapes of every char below 0x20, U+007F, U+2028/9, non-BMP, keys mixing high-BMP and supplementary, nesting, big ints), digest.jsonl, stored_hash.jsonl (caracole's real raw records from tests/fixtures (UG tab JSON, LRCLIB answers), 238.0/4.50/1E2/1e-7/-0.0/1e+300/5e-324, 30+ significant digits, 1e999999999, a 5000-digit integer, a raw control character in a string, '01', '+1', '.5', '1.', a BOM, duplicate keys, NaN, not-JSON, '\ud800' escapes, whitespace variants of one record, only ' \t\n\r' as whitespace), and pydumps.jsonl (json.dumps(v, ensure_ascii=False) with its default separators over kv-shaped values: progress records, a sync base built in sorted() order, nested objects in insertion order, numbers as their literals).
>
> Kotlin, core/json/: Canonical (write sorts keys with a code-point comparator and escapes as Python; parse is your own strict parser of §4 over kotlinx JsonElement, keeping each number's literal in JsonPrimitive's content and the last duplicate key, throwing CanonicalError on what json.loads refuses; numbers by the decimal rule with BigInteger/BigDecimal from the literal, checked against the vectors; hashStoredJson falls back to the bytes Python's surrogatepass gives) and PyJson.dumps (insertion order unless sortKeys; ', ' and ': ' unless compact; numbers as their literal). No JDK text API beyond String.codePointAt and the surrogate helpers.
> Commit: feat(peer): canonical JSON, the stored-JSON hash and kv text, in Python and Kotlin.

#### keys: Identity keys and name forms

- Branch `android/keys` · mixed · M1 · about 2000 lines · depends on py-unicode, pinyin · Phase A may start early
- Goal: Normalize.* and SafeName.* in Kotlin agree with normalize.py, lacuerda_index.name_key/title_key and library.safe_name to the character, held by vectors.
- Owns: `android/core/src/main/kotlin/io/github/danielhp95/caracole/core/keys/**`; `android/core/src/test/kotlin/io/github/danielhp95/caracole/core/keys/**`; `tests/test_conformance_keys.py`; `tests/conformance/data/caracole/keys/**`; `tests/conformance/vectors/keys/**`
- Must not touch: src/caracole/normalize.py; src/caracole/library.py; android/*/build.gradle.kts; AGENTS.md; any other lane's owns
- Provides: core.keys.Normalize (lacuerdaNameKey and lacuerdaTitleKey included); core.keys.SafeName
- Consumes: core.py.*; core.pinyin.Pinyin
- Tests: tests/test_conformance_keys.py; android/core/src/test/kotlin/io/github/danielhp95/caracole/core/keys/FoldTest.kt; android/core/src/test/kotlin/io/github/danielhp95/caracole/core/keys/IdentityTest.kt; android/core/src/test/kotlin/io/github/danielhp95/caracole/core/keys/NameFormsTest.kt; android/core/src/test/kotlin/io/github/danielhp95/caracole/core/keys/SafeNameTest.kt
- Done when: nix develop -c pytest -q passes; nix develop ./android -c gradle -p android :core:test passes, every record of vectors/keys/*.jsonl matching; Normalize.KEY_VERSION == normalize.KEY_VERSION (a vector); ForbiddenApiTest passes

Brief:

> Repo /home/dani/Projects/caracole. Lane keys: branch android/keys, worktree .claude/worktrees/keys (git -C /home/dani/Projects/caracole worktree add .claude/worktrees/keys -b android/keys main, or reuse them); never touch the main checkout's files. First read the plan, docs/superpowers/plans/2026-11-03-android-port-m1-m3.md, §7.0 (phases, merging, drift, and the shared machine: pytest -n 4 in the loop, the whole suite once before merging, never `gradle --stop`, no omnibin-shell, no live request, no emulator). Depends on: py-unicode, pinyin. Phase: Phase A while any of py-unicode, pinyin has not merged into main (the part named Phase A below; commit, and end your report with 'waiting on: <lanes>'); Phase B once they all have (merge main into your branch, finish, merge). Test first; conventional commits; no Claude or AI attribution. When every done_when holds with main merged in: git -C /home/dani/Projects/caracole merge --no-ff android/keys.
>
> Plan sections: §1, §3, §5.1 (core/keys).
> Phase A (before py-unicode and pinyin merge): the Python generator and its vectors, and the Kotlin port written against core.py's and core.pinyin's declared signatures. Phase B: make the vectors pass.
>
> Port src/caracole/normalize.py (all of it but OpenCC/hanzi), lacuerda_index.name_key and title_key (romanize, then identity_key: Normalize.lacuerdaNameKey and lacuerdaTitleKey; core.lacuerda.LaCuerda delegates to them) and library.py's safe_name and song_folder.
> Facts: fold = an ASCII fast path s.lower(), else NFKD, drop unicodedata.combining(c)!=0, translate _TRANSLIT, then str.lower() of the whole string (Final_Sigma). Hangul decomposes to jamo and stays. _SPLIT=[\W_]+ with Python's \w. slug_key = _canon(_SPLIT.split(_APOSTROPHES.sub('', fold(s)))): empty tokens dropped, 'and' dropped unless alone, a leading 'the' dropped, tokens joined by '-' except between CJK chars, where _join tests the LAST CODE POINT so far and the first of the next token against _CJK (which includes U+20000-2EBEF: test the code point, never the last UTF-16 char). identity_key = _identity(artist, artist=True)+'/'+_identity(clean_title(title)): T2S, the artist 'y' dropped, number words to digits, a leading Spanish article for the artist. clean_title applies _DASH_SUFFIX, _PAREN_FEAT and _PAREN_SUFFIX to a fixpoint with IGNORECASE and Unicode \s \d \b '.' ('Song - Remaster ２０１１' -> 'Song'; 'Hysteria - lıve' -> 'Hysteria'; 'ACÚSTICO' matches ac[uú]stic[oa]). title_variant slices in code points. _T2S_PAIRS: generated from Python, never retyped. name_forms is ordered and deduplicated: _own_keys (slug, then for Han slug(romanize), slug(T2S)), the keys without featured artists, then per-part forms (_parts, _cut, _script with fold(c).isascii() or 'LATIN' in unicodedata.name(c), _readings: Hangul jamo tables, kana Hepburn with small kana and ー, kanji morae via _MORA, Han pinyin heteronyms; _pinyin_readings uses context pinyin only when len(lazy_pinyin(errors='ignore')) equals the number of _HAN chars; _reads_as memoized; _generic with str.isdigit). romanize: lazy_pinyin(s), strip, drop the parts that are empty or that _SPLIT fullmatches, join, collapse \s+. Every Unicode decision through core.py (PyUnicode, PyRegex, Py), every pinyin through core.pinyin: no JDK text API.
>
> Python, tests/test_conformance_keys.py: data/caracole/keys/t2s.txt (from normalize._T2S_PAIRS); vectors/keys/fold.jsonl (every code point whose fold differs from itself, and 2,000 random strings), slug.jsonl (slug_key, ug_slug_key, compact, split_variant), identity.jsonl (identity_key, clean_title, title_variant, canonical_variant, display_key, without_featuring, placeholder_artist, has_han, has_other_script, simplified, romanize, name_words, holds_run, lacuerda_index.name_key, title_key) over every string literal of tests/test_normalize.py, test_ug_names_adversarial.py, test_song_names.py, test_search.py and test_lacuerda_index.py (collected from their AST's str constants) and seeded random names; name_forms.jsonl (name_forms, listing_forms, original_part) over the same; safe_name.jsonl (library.safe_name, song_folder). Record err where Python raises.
>
> Kotlin: core/keys/Normalize.kt and SafeName.kt to §5.1, results cached (an LRU for nameForms, as Python's lru_cache).
> Commit: feat(android): identity keys, name forms and pinyin keys, agreeing with normalize.py.

#### search-corpus: Search made deterministic, and its corpus

- Branch `android/search-corpus` · python · M2 · about 1200 lines · depends on nothing · runs at once
- Goal: search.py and lacuerda_index.py give one answer whatever PYTHONHASHSEED and whatever rowids, and the Python suite writes the fixtures and vectors every Kotlin search lane and the search routes check against.
- Owns: `src/caracole/search.py`; `src/caracole/lacuerda_index.py`; `src/caracole/ug/key_search.py`; `tests/test_search_determinism.py`; `tests/test_conformance_search.py`; `tests/conformance/vectors/search/**`; `tests/conformance/vectors/web/api_search.jsonl`
- Must not touch: android/**; src/caracole/web/**; AGENTS.md; tests/helpers/corpus.py; any other lane's owns
- Provides: deterministic search.py; vectors/search/fixtures/*.jsonl; vectors/search/{query,library,index,suggest,sites,lacuerda,names}.jsonl; vectors/web/api_search.jsonl
- Consumes: helpers.corpus (skeleton)
- Tests: tests/test_search_determinism.py; tests/test_conformance_search.py
- Done when: nix develop -c pytest -q passes, every existing search test unchanged; the generator's output is identical under PYTHONHASHSEED=1 and 2 (a slow test); CARACOLE_CORPUS=write regeneration, then a plain run, passes

Brief:

> Repo /home/dani/Projects/caracole. Lane search-corpus: branch android/search-corpus, worktree .claude/worktrees/search-corpus (git -C /home/dani/Projects/caracole worktree add .claude/worktrees/search-corpus -b android/search-corpus main, or reuse them); never touch the main checkout's files. First read the plan, docs/superpowers/plans/2026-11-03-android-port-m1-m3.md, §7.0 (phases, merging, drift, and the shared machine: pytest -n 4 in the loop, the whole suite once before merging, never `gradle --stop`, no omnibin-shell, no live request, no emulator). Depends on: nothing. Phase: no lane comes before you: do it all at once. Test first; conventional commits; no Claude or AI attribution. When every done_when holds with main merged in: git -C /home/dani/Projects/caracole merge --no-ff android/search-corpus.
>
> Plan sections: §3 (fixtures, the drift protocol), §5.1 (search), §5.3 (/api/search).
>
> 1. Determinism: behaviour-preserving except at exact ties; the whole suite must still pass. Replace iterated sets with dict.fromkeys lists (order of first appearance): search.py _names_reading's {(artists[0], titles[0]), (artists[-1], titles[-1])} (about line 2167), _harp_songs (~1613), _listed_rows (~2325), _gametabs_paths' set of paths (~1386, which orders tabs and composers). Give every query whose row order reaches an output an ORDER BY on stable keys, LIMITed or not: _ug_suggestions' FTS MATCH ... LIMIT 1000, _Vocabulary's terms (by the term, not id), the LIMIT 2000 of search_gtptabs, _harp_artists, _gametabs_paths, _harptabs_titled, views/place ties in _harp_grouped, and the same in lacuerda_index.py's find, _rows_like and songs_like and in ug/key_search.py. Each fix with a test in tests/test_search_determinism.py that fails without it (rows inserted in two orders give one answer).
>
> 2. Fixtures: tests/test_conformance_search.py builds fixture libraries with caracole's own functions from the existing test data (test_search.py's ROWS, PINYIN_ROWS and other row sets; test_lacuerda_index.py's, test_harptabs_index.py's, test_gametabs_index.py's; gtptabs and musescore rows; a few songs and tombstones; artist-tab pages), dumps each with helpers.corpus.dump_fixture into vectors/search/fixtures/<name>.jsonl, replays it into a fresh database (helpers.corpus.replay_fixture) and runs every query against the replayed one.
>
> 3. Vectors (records {fn, fixture, args, kw, out}, out = helpers.corpus.plain of the result; LibraryHit.song as its key):
> - vectors/search/query.jsonl: _forms, _patterns, _queries, _pinyin_runs, key_search.rows_like, and a table of (query, artist, title) -> _Query.readings, score, name and holds, so Kotlin's Query is checked alone (lane search-query).
> - library.jsonl (search_library, search_removed, library_by_artist), index.jsonl (find_index, found, artist_songs, index_artist, bare_id_hint, bare_id_unseen, no_ones), suggest.jsonl (suggest_artists, suggest_titles, suggestions), sites.jsonl (search_gtptabs, gtptabs_songs, search_musescore, search_harptabs, harptabs_artist, harptabs_songs, search_gametabs), lacuerda.jsonl (search_lacuerda, lacuerda_artist, lacuerda_artist_named, lacuerda_songs, lacuerda_left_out, lacuerda_leads, letters_read), names.jsonl (song_names.clean, clean_channel, read_names with the fixture's conn and songs).
> Queries: every query the existing tests of those functions use, plus Chinese, Korean, Japanese, initials, typos, one-letter, empty, numeral (I V vi IV) and unread-letter queries.
> - vectors/web/api_search.jsonl: GET /api/search?q=&box= and /api/artist's three forms answered by a real WebApp (searches_lacuerda=False; YouTube off, as conftest leaves it) over each fixture with an empty library folder, recording status and parsed JSON. The phone answers progression, lacuerda_search, lacuerda_unlisted and youtube as null, and progression can add library rows, so masking keys afterwards is not enough: the generator patches, for its WebApp alone, progressions.read_progression to return None and search.lacuerda_unlisted to return None (documented in its docstring), so the recorded answers are what the phone computes. The library[] rows' card fields (files, links, source, key, instruments) are replaced by '*'.
> 4. Run the generator twice in subprocesses with PYTHONHASHSEED=1 and 2 and assert equal output (marked slow).
> Drift: this lane merges before the Kotlin search lanes; a later fix to these files follows §3's drift protocol.
> Commits: fix(search): one answer whatever the hash seed; test(conformance): the search corpus.

#### search-query: Search's scoring seam: Query, Queries, KeySearch

- Branch `android/search-query` · kotlin · M2 · about 900 lines · depends on keys, fuzz, search-corpus · Phase A may start early
- Goal: Kotlin's Query, Queries and KeySearch answer exactly what search.py's _Query, _forms, _patterns, _queries and ug/key_search.rows_like answer, so the four search lanes score through one checked seam.
- Owns: `android/core/src/main/kotlin/io/github/danielhp95/caracole/core/search/Query.kt`; `android/core/src/main/kotlin/io/github/danielhp95/caracole/core/search/KeySearch.kt`; `android/core/src/main/kotlin/io/github/danielhp95/caracole/core/search/internal/query/**`; `android/core/src/test/kotlin/io/github/danielhp95/caracole/core/search/QueryTest.kt`; `android/core/src/test/kotlin/io/github/danielhp95/caracole/core/search/KeySearchTest.kt`
- Must not touch: android/core/src/main/kotlin/io/github/danielhp95/caracole/core/search/Hits.kt; android/core/src/main/kotlin/io/github/danielhp95/caracole/core/library/Songs.kt; src/caracole/**; android/*/build.gradle.kts; AGENTS.md; any other lane's owns
- Provides: core.search.Query/Queries/Readings/Reading; core.search.KeySearch
- Consumes: core.keys.Normalize; core.fuzz.Fuzz; core.py.*; vectors/search/query.jsonl and fixtures
- Tests: android/core/src/test/kotlin/io/github/danielhp95/caracole/core/search/QueryTest.kt; android/core/src/test/kotlin/io/github/danielhp95/caracole/core/search/KeySearchTest.kt
- Done when: nix develop ./android -c gradle -p android :core:test passes: every record of vectors/search/query.jsonl matches; ForbiddenApiTest passes

Brief:

> Repo /home/dani/Projects/caracole. Lane search-query: branch android/search-query, worktree .claude/worktrees/search-query (git -C /home/dani/Projects/caracole worktree add .claude/worktrees/search-query -b android/search-query main, or reuse them); never touch the main checkout's files. First read the plan, docs/superpowers/plans/2026-11-03-android-port-m1-m3.md, §7.0 (phases, merging, drift, and the shared machine: pytest -n 4 in the loop, the whole suite once before merging, never `gradle --stop`, no omnibin-shell, no live request, no emulator). Depends on: keys, fuzz, search-corpus. Phase: Phase A while any of keys, fuzz, search-corpus has not merged into main (the part named Phase A below; commit, and end your report with 'waiting on: <lanes>'); Phase B once they all have (merge main into your branch, finish, merge). Test first; conventional commits; no Claude or AI attribution. When every done_when holds with main merged in: git -C /home/dani/Projects/caracole merge --no-ff android/search-query.
>
> Plan sections: §3, §5.1 (core/search Query.kt, KeySearch.kt).
> Phase A (before keys, fuzz or search-corpus merge): the port written against their declared signatures. Phase B: the vectors pass.
>
> Port from search.py: _forms, _patterns (at most 2, the longest words, or %syllable%syllable% for Chinese words of 4+ pinyin letters, or initials hyphenated and compact), _queries, _pinyin_runs, _Query (holds, score, readings with partial_ratio_alignment windows deciding title/artist/both, name), _reading (ties go to title, then both), _song_reading, _names_reading (dict.fromkeys order, as search-corpus made it). Port ug/key_search.py rows_like: the same SQL over the temp table (LIKE through ug_keys_fts, never MATCH: detail=none refuses phrase queries), the trigram path or the scan, KEYS_PER_PATTERN, and the keys every pattern is in. Scores round with Py.round(x,1). Sorting by Py.CODE_POINT_ORDER, never String.compareTo; dicts as LinkedHashMap. Tests replay vectors/search/query.jsonl (KeySearch over its fixtures through Fixtures.load into TestDb.fresh).
> Commit: feat(android): search's query readings and key prefilter, as search.py.

#### search-ug: Search: your songs, UG's index and its artists

- Branch `android/search-ug` · kotlin · M2 · about 1700 lines · depends on search-query · Phase A may start early
- Goal: Kotlin's Search and ArtistTabs answer exactly what search.py, ug/lookup.py and ug/artist_tabs.py answer over the search fixtures.
- Owns: `android/core/src/main/kotlin/io/github/danielhp95/caracole/core/search/Search.kt`; `android/core/src/main/kotlin/io/github/danielhp95/caracole/core/search/internal/ug/**`; `android/core/src/main/kotlin/io/github/danielhp95/caracole/core/ug/**`; `android/core/src/test/kotlin/io/github/danielhp95/caracole/core/search/SearchUgTest.kt`; `android/core/src/test/kotlin/io/github/danielhp95/caracole/core/ug/**`
- Must not touch: android/core/src/main/kotlin/io/github/danielhp95/caracole/core/search/Hits.kt; android/core/src/main/kotlin/io/github/danielhp95/caracole/core/search/Query.kt; android/core/src/main/kotlin/io/github/danielhp95/caracole/core/search/KeySearch.kt; android/core/src/main/kotlin/io/github/danielhp95/caracole/core/search/internal/query/**; android/core/src/main/kotlin/io/github/danielhp95/caracole/core/search/internal/suggest/**; android/core/src/main/kotlin/io/github/danielhp95/caracole/core/library/Songs.kt; src/caracole/**; android/*/build.gradle.kts; AGENTS.md; any other lane's owns
- Provides: core.search.Search; core.ug.ArtistTabs
- Consumes: core.search.Query/Queries/KeySearch; core.keys.Normalize; core.fuzz.Fuzz; vectors/search/{library,index}.jsonl and fixtures
- Tests: android/core/src/test/kotlin/io/github/danielhp95/caracole/core/search/SearchUgTest.kt; android/core/src/test/kotlin/io/github/danielhp95/caracole/core/ug/ArtistTabsTest.kt
- Done when: nix develop ./android -c gradle -p android :core:test passes: every record of vectors/search/library.jsonl and index.jsonl matches; ForbiddenApiTest passes

Brief:

> Repo /home/dani/Projects/caracole. Lane search-ug: branch android/search-ug, worktree .claude/worktrees/search-ug (git -C /home/dani/Projects/caracole worktree add .claude/worktrees/search-ug -b android/search-ug main, or reuse them); never touch the main checkout's files. First read the plan, docs/superpowers/plans/2026-11-03-android-port-m1-m3.md, §7.0 (phases, merging, drift, and the shared machine: pytest -n 4 in the loop, the whole suite once before merging, never `gradle --stop`, no omnibin-shell, no live request, no emulator). Depends on: search-query. Phase: Phase A while any of search-query has not merged into main (the part named Phase A below; commit, and end your report with 'waiting on: <lanes>'); Phase B once they all have (merge main into your branch, finish, merge). Test first; conventional commits; no Claude or AI attribution. When every done_when holds with main merged in: git -C /home/dani/Projects/caracole merge --no-ff android/search-ug.
>
> Plan sections: §3, §5.1 (core/search Search.kt; core/ug/ArtistTabs.kt; Hits.kt and Songs.kt are final).
> Phase A (before search-query merges): the port against Query's declared signatures. Phase B: the vectors pass.
>
> Port from search.py: _Row/_Named, _scored_rows, _parts, _part_names, _artists_with_words (FTS MATCH strings built exactly as Python builds them), _listed_rows, _merged, _artist_rows, _with_parts, _part_leads, _outweighs, _song_counts, search_library, search_removed, find_index, found, artist_songs, _index_hit, _best_listed (rank.prior_mean: CPython's sum is Neumaier, use Py.fsum), _Yours, _names_from_path, _title_words (str.upper: PyUnicode.upper), library_by_artist, bare_id_hint, _unseen, bare_id_unseen, no_ones, display_from_keys; what search needs of ug/lookup.py and match.py; ug/artist_tabs.py _names, _file (Py.mostCommonFirst), refile and ensure_current_keys. Scores with Py.round(x,1). Py.CODE_POINT_ORDER, LinkedHashMap, every Unicode decision through core.py and core.keys. Tests load a fixture (Fixtures.load into TestDb.fresh) and replay library.jsonl and index.jsonl.
> Commit: feat(android): search over your songs and UG's index, as search.py.

#### search-suggest: Search: Did you mean

- Branch `android/search-suggest` · kotlin · M2 · about 1300 lines · depends on search-query · Phase A may start early
- Goal: Suggest.* answers what search.py's suggest_artists, suggest_titles and suggestions answer over the fixtures.
- Owns: `android/core/src/main/kotlin/io/github/danielhp95/caracole/core/search/Suggest.kt`; `android/core/src/main/kotlin/io/github/danielhp95/caracole/core/search/Vocabulary.kt`; `android/core/src/main/kotlin/io/github/danielhp95/caracole/core/search/internal/suggest/**`; `android/core/src/test/kotlin/io/github/danielhp95/caracole/core/search/SuggestTest.kt`
- Must not touch: android/core/src/main/kotlin/io/github/danielhp95/caracole/core/search/Query.kt; android/core/src/main/kotlin/io/github/danielhp95/caracole/core/search/Search.kt; android/core/src/main/kotlin/io/github/danielhp95/caracole/core/search/Hits.kt; android/core/src/main/kotlin/io/github/danielhp95/caracole/core/search/internal/ug/**; android/core/src/main/kotlin/io/github/danielhp95/caracole/core/search/internal/query/**; src/caracole/**; android/*/build.gradle.kts; AGENTS.md; any other lane's owns
- Provides: core.search.Suggest
- Consumes: core.search.Query/Queries; core.fuzz.Fuzz; vectors/search/suggest.jsonl
- Tests: android/core/src/test/kotlin/io/github/danielhp95/caracole/core/search/SuggestTest.kt
- Done when: nix develop ./android -c gradle -p android :core:test passes: every record of vectors/search/suggest.jsonl matches; ForbiddenApiTest passes

Brief:

> Repo /home/dani/Projects/caracole. Lane search-suggest: branch android/search-suggest, worktree .claude/worktrees/search-suggest (git -C /home/dani/Projects/caracole worktree add .claude/worktrees/search-suggest -b android/search-suggest main, or reuse them); never touch the main checkout's files. First read the plan, docs/superpowers/plans/2026-11-03-android-port-m1-m3.md, §7.0 (phases, merging, drift, and the shared machine: pytest -n 4 in the loop, the whole suite once before merging, never `gradle --stop`, no omnibin-shell, no live request, no emulator). Depends on: search-query. Phase: Phase A while any of search-query has not merged into main (the part named Phase A below; commit, and end your report with 'waiting on: <lanes>'); Phase B once they all have (merge main into your branch, finish, merge). Test first; conventional commits; no Claude or AI attribution. When every done_when holds with main merged in: git -C /home/dani/Projects/caracole merge --no-ff android/search-suggest.
>
> Plan sections: §3, §5.1 (core/search Suggest.kt; Query.kt is search-query's seam). Suggest's stub is neutral (empty lists); replace it whole.
> Phase A (before search-query merges): the port. Phase B: the vectors pass.
>
> Port search.py ~654-1237: suggest_artists, suggest_titles, suggestions, _no_room, _unshown_titles, _shown, name_words_key, _suggestible, _cut, _suggesting, _closeness and _title_closeness (Py.fsum for sum(); x*x for ** 2, checked against the vectors), _close_words and _near (process.extract with fuzz.ratio, cutoff CLOSE, limit CLOSE_WORDS: Fuzz.extract), _weighed, _ranked, _artist_suggestions, _ug_suggestions, _lacuerda_suggestions, _harptabs_suggestions, _Titled, _title_suggestions, _title_suggestion, _source_of, _word_closeness, _ug_titled, _needles, _holds, _lacuerda_titled, _harptabs_titled, _gtptabs_titled, _Vocabulary (per first code point and length; the SQL range bound chr(ord(start)+1) built from the first code point; a start of U+D7FF makes a lone surrogate, which crashes Python too: do the same, never invent), _vocabulary (once per process, then only the words added since). search-corpus ordered these queries by stable keys: keep its SQL exactly. The LaCuerda and harptabs SQL these need is ported here, privately, into core/search/internal/suggest/ (no dependency on search-lacuerda or search-sites).
> Commit: feat(android): Did you mean, as search.py suggests.

#### search-sites: Search: gtptabs.com, MuseScore, harptabs.com, gametabs.net

- Branch `android/search-sites` · kotlin · M2 · about 1400 lines · depends on search-query · Phase A may start early
- Goal: SiteSearch and SiteKeys answer what search.py's other-sites search and the harptabs/gametabs key helpers answer over the fixtures.
- Owns: `android/core/src/main/kotlin/io/github/danielhp95/caracole/core/sites/**`; `android/core/src/test/kotlin/io/github/danielhp95/caracole/core/sites/**`
- Must not touch: android/core/src/main/kotlin/io/github/danielhp95/caracole/core/search/**; src/caracole/**; android/*/build.gradle.kts; AGENTS.md; any other lane's owns
- Provides: core.sites.SiteSearch; core.sites.SiteKeys
- Consumes: core.search.Query/Queries; core.keys.Normalize; vectors/search/sites.jsonl
- Tests: android/core/src/test/kotlin/io/github/danielhp95/caracole/core/sites/SiteSearchTest.kt; android/core/src/test/kotlin/io/github/danielhp95/caracole/core/sites/SiteKeysTest.kt
- Done when: nix develop ./android -c gradle -p android :core:test passes: every record of vectors/search/sites.jsonl matches; SiteKeys' ensure_current_keys re-key a fixture whose keys record is absent so its rows equal the same fixture keyed by Python (a test); ForbiddenApiTest passes

Brief:

> Repo /home/dani/Projects/caracole. Lane search-sites: branch android/search-sites, worktree .claude/worktrees/search-sites (git -C /home/dani/Projects/caracole worktree add .claude/worktrees/search-sites -b android/search-sites main, or reuse them); never touch the main checkout's files. First read the plan, docs/superpowers/plans/2026-11-03-android-port-m1-m3.md, §7.0 (phases, merging, drift, and the shared machine: pytest -n 4 in the loop, the whole suite once before merging, never `gradle --stop`, no omnibin-shell, no live request, no emulator). Depends on: search-query. Phase: Phase A while any of search-query has not merged into main (the part named Phase A below; commit, and end your report with 'waiting on: <lanes>'); Phase B once they all have (merge main into your branch, finish, merge). Test first; conventional commits; no Claude or AI attribution. When every done_when holds with main merged in: git -C /home/dani/Projects/caracole merge --no-ff android/search-sites.
>
> Plan sections: §3, §5.1 (core/sites).
> Phase A (before search-query merges): the port. Phase B: the vectors pass.
>
> Port search.py ~1239-1676 and ~1885-1912: search_gtptabs, _gtptabs_artist, gtptabs_songs, _gtptabs_keys, search_musescore with _title_pages and _known_song, search_gametabs with _GameTab, _gametabs_paths (ordered by search-corpus), _gametabs_tracks, _gametabs_reading, _gametabs_hit, _listed_names, search_harptabs, harptabs_artist, harptabs_songs, _titled_only, _HarpArtist, _harp_artists, _harp_named, _harp_known, _harp_artist, _harp_songs, _harp_grouped; and the site helpers they call: harptabs.py (joined, title_key, song_title, song_key, page_url), gametabs.py (slug_key, IndexRow.key and what search reads), musescore.py (title keys). SiteKeys: harptabs_fetch.ensure_current_keys (ROW_KEYS), harptabs_index.ensure_current_keys and index_state, gametabs_index.ensure_current_keys and index_state, which index-transfer calls after a merge (src/caracole/harptabs_fetch.py:184-198, harptabs_index.py:136-163, gametabs_index.py:130-157). Score through core.search.Query. Code-point sorting, LinkedHashMap, Py.round. For the re-key test, build the Python-keyed fixture in the test from vectors/search/fixtures (Python's keys are in its rows).
> Commit: feat(android): search over gtptabs.com, MuseScore, harptabs.com and gametabs.net.

#### search-lacuerda: Search: LaCuerda's index

- Branch `android/search-lacuerda` · kotlin · M2 · about 1500 lines · depends on search-query · Phase A may start early
- Goal: LaCuerda.* answers what lacuerda_index.py's read side and search.py's LaCuerda glue answer over the fixtures.
- Owns: `android/core/src/main/kotlin/io/github/danielhp95/caracole/core/lacuerda/** (not nameKey/titleKey's delegation, which is final)`; `android/core/src/test/kotlin/io/github/danielhp95/caracole/core/lacuerda/**`
- Must not touch: android/core/src/main/kotlin/io/github/danielhp95/caracole/core/search/**; android/core/src/main/kotlin/io/github/danielhp95/caracole/core/keys/**; src/caracole/**; android/*/build.gradle.kts; AGENTS.md; any other lane's owns
- Provides: core.lacuerda.LaCuerda
- Consumes: core.search.Query; core.fuzz.Fuzz; core.keys.Normalize (lacuerdaNameKey, lacuerdaTitleKey); vectors/search/lacuerda.jsonl
- Tests: android/core/src/test/kotlin/io/github/danielhp95/caracole/core/lacuerda/LaCuerdaTest.kt
- Done when: nix develop ./android -c gradle -p android :core:test passes: every record of vectors/search/lacuerda.jsonl matches; ForbiddenApiTest passes

Brief:

> Repo /home/dani/Projects/caracole. Lane search-lacuerda: branch android/search-lacuerda, worktree .claude/worktrees/search-lacuerda (git -C /home/dani/Projects/caracole worktree add .claude/worktrees/search-lacuerda -b android/search-lacuerda main, or reuse them); never touch the main checkout's files. First read the plan, docs/superpowers/plans/2026-11-03-android-port-m1-m3.md, §7.0 (phases, merging, drift, and the shared machine: pytest -n 4 in the loop, the whole suite once before merging, never `gradle --stop`, no omnibin-shell, no live request, no emulator). Depends on: search-query. Phase: Phase A while any of search-query has not merged into main (the part named Phase A below; commit, and end your report with 'waiting on: <lanes>'); Phase B once they all have (merge main into your branch, finish, merge). Test first; conventional commits; no Claude or AI attribution. When every done_when holds with main merged in: git -C /home/dani/Projects/caracole merge --no-ff android/search-lacuerda.
>
> Plan sections: §3, §5.1 (core/lacuerda).
> Phase A (before search-query merges): the port. Phase B: the vectors pass.
>
> Port lacuerda_index.py's read side (~264-352, 521-930): find with its own _Query (artist, _scale, readings, part_of: rapidfuzz ratio, token_sort_ratio and partial_ratio_alignment at ~814-874), _patterns, _forms, _rows_like, artist_songs, songs_like, artist_slugs, index_state, letters_read, unread_letter, letters_text, artist_slug_candidates, what it uses of listing_forms, ensure_current_keys (keys made again from stored names, no request); lacuerda.py ~148-206 (the URLs and slugs search needs); search.py ~1677-1884: search_lacuerda, lacuerda_artist, lacuerda_artist_named, lacuerda_songs, lacuerda_left_out, lacuerda_leads, _lacuerda_song, _lacuerda_artist, _known_song. name_key and title_key are lane keys' Normalize.lacuerdaNameKey/TitleKey; LaCuerda.nameKey delegates (final). lacuerda_unlisted is NOT needed: the phone answers null until M4. Use core.fuzz, core.keys and core.search.Query where search.py does.
> Commit: feat(android): search over LaCuerda's index.

#### song-names: The artist and title a free text names

- Branch `android/song-names` · kotlin · M2 · about 600 lines · depends on keys, search-corpus · Phase A may start early
- Goal: SongNames.clean, cleanChannel and readNames answer what song_names.py answers, for /api/search's names and the phone's request form.
- Owns: `android/core/src/main/kotlin/io/github/danielhp95/caracole/core/names/**`; `android/core/src/test/kotlin/io/github/danielhp95/caracole/core/names/**`
- Must not touch: src/caracole/**; android/*/build.gradle.kts; AGENTS.md; any other lane's owns
- Provides: core.names.SongNames
- Consumes: core.py.*; core.keys.Normalize (lacuerdaNameKey); vectors/search/names.jsonl
- Tests: android/core/src/test/kotlin/io/github/danielhp95/caracole/core/names/SongNamesTest.kt
- Done when: nix develop ./android -c gradle -p android :core:test passes: every record of vectors/search/names.jsonl matches; ForbiddenApiTest passes

Brief:

> Repo /home/dani/Projects/caracole. Lane song-names: branch android/song-names, worktree .claude/worktrees/song-names (git -C /home/dani/Projects/caracole worktree add .claude/worktrees/song-names -b android/song-names main, or reuse them); never touch the main checkout's files. First read the plan, docs/superpowers/plans/2026-11-03-android-port-m1-m3.md, §7.0 (phases, merging, drift, and the shared machine: pytest -n 4 in the loop, the whole suite once before merging, never `gradle --stop`, no omnibin-shell, no live request, no emulator). Depends on: keys, search-corpus. Phase: Phase A while any of keys, search-corpus has not merged into main (the part named Phase A below; commit, and end your report with 'waiting on: <lanes>'); Phase B once they all have (merge main into your branch, finish, merge). Test first; conventional commits; no Claude or AI attribution. When every done_when holds with main merged in: git -C /home/dani/Projects/caracole merge --no-ff android/song-names.
>
> Plan sections: §5.1 (core/names).
> Phase A (before keys or search-corpus merge): the port. Phase B: the vectors pass.
>
> Port src/caracole/song_names.py whole: clean, clean_channel, read_names and its rules in order, _words (unicodedata.normalize('NFKC') then casefold: PyUnicode.nfkc and casefold), the noise word sets, _BRACKETS, _MARK, _BY (IGNORECASE: PyRegex.ignoreCase), _Known (its queries over ug_index, ug_artist_tabs, gtptabs_index, lacuerda_index through Normalize.lacuerdaNameKey, harptabs; and the files table for HUMAN_SHEET). A one-word artist counts only once credible, as in Python. Every regex through PyRegex.compile.
> Commit: feat(android): song names read from free text, as song_names.py.

#### index-transfer: Importing the computer's index

- Branch `android/index-transfer` · mixed · M2 · about 1700 lines · depends on keys, canonical, search-ug, search-sites, search-lacuerda · Phase A may start early
- Goal: The phone merges a `caracole index export` file into its database exactly as index_transfer.merge does, a fresh phone database never re-keys a whole index on its first import, and newest() gives the state document's per-site stamps.
- Owns: `android/core/src/main/kotlin/io/github/danielhp95/caracole/core/index/**`; `android/core/src/test/kotlin/io/github/danielhp95/caracole/core/index/**`; `tests/test_conformance_index.py`; `tests/conformance/data/caracole/schema/fresh_kv.json`; `tests/conformance/vectors/index/**`
- Must not touch: src/caracole/index_transfer.py; android/core/src/main/kotlin/io/github/danielhp95/caracole/core/db/**; android/*/build.gradle.kts; AGENTS.md; any other lane's owns
- Provides: core.index.IndexTransfer (merge, seedFresh, newest); fresh_kv.json
- Consumes: core.db; core.ug.ArtistTabs; core.lacuerda.LaCuerda.ensureCurrentKeys; core.sites.SiteKeys; Fixtures.loadRaw
- Tests: tests/test_conformance_index.py; android/core/src/test/kotlin/io/github/danielhp95/caracole/core/index/IndexTransferTest.kt; android/core/src/test/kotlin/io/github/danielhp95/caracole/core/index/MergeSpeedTest.kt
- Done when: nix develop -c pytest -q passes; nix develop ./android -c gradle -p android :core:test passes: every merge case's database after equals Python's dump, kv text included; a fresh phone database seeded by seedFresh merges an export with no re-key (a test checks the keys records untouched and no row re-keyed)

Brief:

> Repo /home/dani/Projects/caracole. Lane index-transfer: branch android/index-transfer, worktree .claude/worktrees/index-transfer (git -C /home/dani/Projects/caracole worktree add .claude/worktrees/index-transfer -b android/index-transfer main, or reuse them); never touch the main checkout's files. First read the plan, docs/superpowers/plans/2026-11-03-android-port-m1-m3.md, §7.0 (phases, merging, drift, and the shared machine: pytest -n 4 in the loop, the whole suite once before merging, never `gradle --stop`, no omnibin-shell, no live request, no emulator). Depends on: keys, canonical, search-ug, search-sites, search-lacuerda. Phase: Phase A while any of keys, canonical, search-ug, search-sites, search-lacuerda has not merged into main (the part named Phase A below; commit, and end your report with 'waiting on: <lanes>'); Phase B once they all have (merge main into your branch, finish, merge). Test first; conventional commits; no Claude or AI attribution. When every done_when holds with main merged in: git -C /home/dani/Projects/caracole merge --no-ff android/index-transfer.
>
> Plan sections: §1, §3 (fixtures with sql lines, Fixtures.loadRaw), §4 (kv text), §5.1 (core/index), §5.5 (merge runs inside Database.write).
> Phase A (before keys, canonical, search-ug, search-sites and search-lacuerda merge): the Python generator and its vectors, and merge's own code. Phase B: the re-key paths (ArtistTabs, LaCuerda, SiteKeys) and every case passing.
>
> Port src/caracole/index_transfer.py's merge (not export): ATTACH the file as theirs; _meta (refuse unless format=='1' and schema==str(15): TransferError); _check_columns (identical PRAGMA table_info, order included); per site a _plan and an _apply in one savepoint: UG sitemaps by indexed_at upserted with ON CONFLICT DO UPDATE, then mark_dirty_for_new (ug/index.py:312-333), ug_artist_tabs rows by read_at then ArtistTabs.refile; LaCuerda listing pages by checked_at, artist pages and search rows only where the phone lacks them; gtptabs and musescore sitemaps by checked_at; harptabs and gametabs sitemaps, then pages by read_at; progress records only move forward, written with Db.kvSetJson (Python's kv_set_json bytes); the backup callback before the first change only; then each index's ensure_current_keys, whole where META.keys differs. stamps.parse must accept what datetime.fromisoformat accepts (port stamps.py:19-35). seedFresh(db) inserts the kv records of data/caracole/schema/fresh_kv.json, so the first merge sees the same keys records and re-keys nothing. newest(db): per site, the newest read time of its rows and progress records, as merge compares them, for the state document's "indexes" (§4); Python's twin is lane peer-format2's index_transfer.newest, and both must agree on the vectors.
>
> Python, tests/test_conformance_index.py: data/caracole/schema/fresh_kv.json (a fresh migrated database, each site's ensure_current_keys run on its empty tables, then the kv rows they set: ug:artist_tabs:keys, lacuerda:index:keys, harptabs:artists:keys, harptabs:index:keys, gametabs:games:keys and any other the code shows); vectors/index/: for each case (an empty phone and an export; a phone with older and newer rows; a refused schema; refused columns; a re-key because META.keys differs) the export as a fixture with its sql lines (the export's own DDL from its sqlite_master, then its rows and its caracole_export table), the phone before (a fixture), the phone after (a dump), and merge's report; vectors/index/newest.jsonl.
> Kotlin's test: Fixtures.loadRaw writes the export as a real SQLite file, Fixtures.load builds the phone, merge runs inside Database.writeBlocking, and the dump after equals Python's, kv text byte for byte.
> MergeSpeedTest: 200,000 generated ug_index rows merged, its time printed (no assertion), for the risks list.
> Commit: feat(android): the computer's index merged on the phone, as index merge does.

#### server-shell: The phone's local server: router, security, files

- Branch `android/server-shell` · mixed · M2 · about 2200 lines · depends on nothing · runs at once
- Goal: An engine-neutral router shaped like web/app.py with caracole serve's checks plus the launch secret, the library file route (the phone's folder, then the mirror through PhoneGate), the message page, the out-of-round stubs, :server's test fixtures, and a Ktor CIO adapter on 127.0.0.1.
- Owns: `android/server/src/main/kotlin/io/github/danielhp95/caracole/server/http/**`; `android/server/src/main/kotlin/io/github/danielhp95/caracole/server/files/**`; `android/server/src/main/kotlin/io/github/danielhp95/caracole/server/routes/Stubs.kt`; `android/server/src/main/kotlin/io/github/danielhp95/caracole/server/ktor/**`; `android/server/src/testFixtures/**`; `android/server/src/test/kotlin/io/github/danielhp95/caracole/server/http/**`; `android/server/src/test/kotlin/io/github/danielhp95/caracole/server/files/**`; `android/server/src/test/kotlin/io/github/danielhp95/caracole/server/ktor/**`; `tests/test_conformance_web.py`; `tests/conformance/vectors/web/security.jsonl`; `tests/conformance/vectors/web/routing.jsonl`; `tests/conformance/data/caracole/page/message.json`; `tests/conformance/data/caracole/page/icon.json`
- Must not touch: src/caracole/web/**; android/server/src/main/kotlin/io/github/danielhp95/caracole/server/Assembly.kt; android/*/build.gradle.kts; AGENTS.md; android/mirror/src/main/kotlin/io/github/danielhp95/caracole/mirror/**; any other lane's owns
- Provides: server.http.App/Request/Response/Route(limit)/Refused/Security/Inline/MessagePage; server.files.LibraryFiles, PhoneGate; server.routes.Stubs; server.ktor.LocalServer; :server testFixtures TestApp (an App over a TestDb, a request builder: cookie, Host, token, form)
- Consumes: mirror.Mirror.pageFor, UnitGate (skeleton, final); core.db.Database (files table); core.sync.Units.digestOf (neutral null until sync-units); core.library.Songs.isRemoved
- Tests: tests/test_conformance_web.py; android/server/src/test/kotlin/io/github/danielhp95/caracole/server/http/SecurityTest.kt; android/server/src/test/kotlin/io/github/danielhp95/caracole/server/http/RoutingTest.kt; android/server/src/test/kotlin/io/github/danielhp95/caracole/server/files/LibraryFilesTest.kt; android/server/src/test/kotlin/io/github/danielhp95/caracole/server/ktor/LocalServerTest.kt
- Done when: nix develop -c pytest -q passes; nix develop ./android -c gradle -p android :server:test passes: every security and routing vector matches; LocalServerTest over a real socket: no cookie is 403, the cookie reaches the route, %2F in a path survives, it binds 127.0.0.1 only; LibraryFilesTest: a gated page answers CHANGED's and REMOVED's message pages; a route's path is never a file

Brief:

> Repo /home/dani/Projects/caracole. Lane server-shell: branch android/server-shell, worktree .claude/worktrees/server-shell (git -C /home/dani/Projects/caracole worktree add .claude/worktrees/server-shell -b android/server-shell main, or reuse them); never touch the main checkout's files. First read the plan, docs/superpowers/plans/2026-11-03-android-port-m1-m3.md, §7.0 (phases, merging, drift, and the shared machine: pytest -n 4 in the loop, the whole suite once before merging, never `gradle --stop`, no omnibin-shell, no live request, no emulator). Depends on: nothing. Phase: no lane comes before you: do it all at once. Test first; conventional commits; no Claude or AI attribution. When every done_when holds with main merged in: git -C /home/dani/Projects/caracole merge --no-ff android/server-shell.
>
> Plan sections: §1, §5.2 (server/http, files, routes/Stubs, ktor, testFixtures), §5.3 (the phone's table), §5.5.
>
> Port web/app.py's Request/Response/Route/Refused handling, WebApp.handle/_route/_form/finish/_file and web/security.py (host_name, answers_to, cross_origin_ok, own_page_read, same_token), web/files.py's TYPES and download Content-Disposition (download_names.py), inline.py (sha256_source; json_block writing every '<' as \u003c), and pages.py's message page (its CSS and CSP hash). Order: the secret cookie first (Cookie header caracole-launch=<secret>, constant time; missing or wrong: 403 text/plain 'Not this app's caracole.'), then exactly _route's order: host (421); strict path unquoting (400); GET/HEAD: /api/ refused 403 JSON when Sec-Fetch-Site is cross-site or same-site; exact route, then under= prefixes; scriptOnly routes need cross_origin_ok and x-caracole-form-token == csrf (403 {'error','reload':true}); else the file route; POST: route or 404, cross_origin_ok 403, Content-Type application/x-www-form-urlencoded 415, body <= route.limit (16384 by default) 413, at most 20 fields 400, first value per name, csrf in constant time 403 with reload; other methods 405 Allow: GET, HEAD, POST; HEAD as GET without a body. Refused -> the message page, or {'error': message} with its status to Accept: application/json; a 303 with data -> 200 JSON. finish(): CSP frame-ancestors 'none' unless set, X-Content-Type-Options nosniff, X-Frame-Options DENY, Referrer-Policy same-origin, Cross-Origin-Resource-Policy same-origin, Cross-Origin-Opener-Policy same-origin, Cache-Control no-store, each unless set. JSON compact UTF-8, 'application/json; charset=utf-8'. App(config, modules, stubs, files): a stub route answers only where no module does; two modules on one (method, path) fail at construction (a test).
> Reads go through Database.read (§5.5); a route never writes.
>
> LibraryFiles: a path a route answers is never a file; then the phone's library folder (only files its files table records, with files.py's type and download name, canonical paths under libraryDir, no link followed), then mirror.Mirror.pageFor(path, PhoneGate) with the manifest's headers exactly (sandbox CSP included). PhoneGate.check(unit, digest): for song/<key>, Songs.isRemoved -> REMOVED; Units.digestOf(unit) non-null and != digest -> CHANGED; else SERVE (Units.digestOf is neutral null until sync-units, so everything serves). CHANGED answers the message page 'This song changed on the phone since the computer made its page.', linking to sheet.txt when the phone keeps one; REMOVED 'This song was removed on the phone.'
>
> Stubs: every out-of-round route of §5.3 (GET pages: the message page, 409; POSTs, /request, /lookup and /remove included until phone-sync-routes: Refused 409 '... isn't on the phone yet.'; GET /api/youtube/video's off answer with guess {artist:'', title:''}).
>
> LocalServer: Ktor 3.3.3 CIO, one intercept handing Request(method, the raw target as sent, lowercase headers, the body read up to the route's limit+1) to App.handle and writing the Response (Body.FromFile streamed); binding 127.0.0.1 only, the preferred port, else ephemeral. The spike is docs/superpowers/spikes/2026-11-03-android/Http.kt.txt.
>
> testFixtures (android/server/src/testFixtures/.../server/testing/TestApp.kt): TestApp builds an App over TestDb.fresh with chosen modules, and a request builder that adds the cookie, Host, token header and urlencoded form, so every :server lane tests the same way.
>
> Python, tests/test_conformance_web.py: vectors/web/security.jsonl (security.py's functions over a matrix of hosts, headers and methods; reuse tests/test_web_security.py's cases), vectors/web/routing.jsonl (a WebApp over an empty library, with only form routes and GET reads, the behaviour both sides keep after peer-push-routes' body kinds: each refusal path's status and the headers finish() sets), data/caracole/page/message.json (the message page's style text and CSP) and data/caracole/page/icon.json (page_icon.LINK and SVG). Kotlin tests replay them against App with a fake secret.
> Commit: feat(android): the phone's local server, with caracole serve's checks and a launch secret.

#### library-page: The served library page, from caracole's own assets

- Branch `android/library-page` · mixed · M2 · about 1500 lines · depends on server-shell, keys · Phase A may start early
- Goal: GET / on the phone answers the library page caracole serve would build for the same data, byte for byte in its frame and hashes, with the computer's cards from the mirror re-identified to the phone's song ids and the phone's removed songs left out.
- Owns: `android/server/src/main/kotlin/io/github/danielhp95/caracole/server/page/**`; `android/server/src/test/kotlin/io/github/danielhp95/caracole/server/page/**`; `tests/test_conformance_library_page.py`; `tests/conformance/data/caracole/page/library_assets.json`; `tests/conformance/vectors/web/library_page.json`; `tests/conformance/vectors/web/cards.jsonl`
- Must not touch: src/caracole/library_page.py; src/caracole/library_assets/**; android/*/build.gradle.kts; AGENTS.md; any other lane's owns
- Provides: server.page.LibraryAssets/LibraryPage/ServerControls/PageData/SongCards/MirrorPageData/PageRoutes; caracole/page/library_assets.json (runtime order)
- Consumes: server.http.*; mirror.Mirror; core.keys.Normalize; core.library.Songs; the skeleton's library_page.assemble_page and sync templates
- Tests: tests/test_conformance_library_page.py; android/server/src/test/kotlin/io/github/danielhp95/caracole/server/page/LibraryPageTest.kt; android/server/src/test/kotlin/io/github/danielhp95/caracole/server/page/MirrorPageDataTest.kt
- Done when: nix develop -c pytest -q passes; nix develop ./android -c gradle -p android :server:test passes: the script and style hashes equal Python's; the served page for each vector's data and controls equals Python's sha256; MirrorPageData re-ids cards by identity, drops the cards of songs the phone holds a tombstone of, and gives phone-only songs minimal cards (tests)

Brief:

> Repo /home/dani/Projects/caracole. Lane library-page: branch android/library-page, worktree .claude/worktrees/library-page (git -C /home/dani/Projects/caracole worktree add .claude/worktrees/library-page -b android/library-page main, or reuse them); never touch the main checkout's files. First read the plan, docs/superpowers/plans/2026-11-03-android-port-m1-m3.md, §7.0 (phases, merging, drift, and the shared machine: pytest -n 4 in the loop, the whole suite once before merging, never `gradle --stop`, no omnibin-shell, no live request, no emulator). Depends on: server-shell, keys. Phase: Phase A while any of server-shell, keys has not merged into main (the part named Phase A below; commit, and end your report with 'waiting on: <lanes>'); Phase B once they all have (merge main into your branch, finish, merge). Test first; conventional commits; no Claude or AI attribution. When every done_when holds with main merged in: git -C /home/dani/Projects/caracole merge --no-ff android/library-page.
>
> Plan sections: §1 (your songs in M2, ids, removed songs), §5.2 (server/page), §5.3.
> Phase A (before server-shell and keys merge): the Python generator, LibraryAssets and LibraryPage. Phase B: MirrorPageData's keys, and every test through TestApp.
>
> The page decides it is served by data.server (library.js:59-63), and with server present library.js uses the served markup unguarded (requestedList.prepend), so the page is built from the templates as library_page.assemble_page builds it (the skeleton extracted it), never by patching the mirror's index.html. Port assemble_page's served branch: head.html/body.html blanks __CSP__ __ICON__ __STYLE__ __TITLE__ __MARK__ __LIBRARY__ __TABSYNC__ and __SYNC__ (the templates sync-tab.html and sync-panel.html verbatim while ServerControls.sync) __TABREQUESTS__ and __REQUESTS__ (empty: no Requests tab on the phone in M3) __REQUEST__ (request.html with __CSRF__ __YOUTUBE__ __YOUTUBEHINT__: YouTube off) __REQUESTED__; scripts and styles concatenated in library_assets.json's order from the classpath copy caracole/library_assets/ (the skeleton's copyLibraryAssets task: never filter or re-encode); the meta CSP "default-src 'none'; script-src <sha256 of scripts>; style-src <sha256 of styles>; img-src data: 'self'; base-uri 'none'; form-action 'self'; connect-src 'self'"; the header CSP frame-ancestors 'none'; the JSON block through Inline.jsonBlock; library_name.py's LibraryName (title, markup, badge 'Phone'); page_mark and the icon from data/caracole/page/icon.json.
>
> MirrorPageData(mirror: Mirror?) (M2-M3's PageData and SongCards): read the mirror's index.html data block (library_page._DATA's regex) from its blob, or start from an empty library when there is no mirror; take icons, catalogue, fold, sites and generated as they are; re-id every card (and songbooks.books[].set[].id) to the phone database's id by identity key (card.identity); a card with no phone song gets a negative id (-1, -2, ...) and fetchable false; drop every card whose identity the phone holds a tombstone of (Songs.isRemoved) until a sync settles it; overlay status and review from the phone database; give songs only on the phone a minimal card: id, artist, artists, title, display, status, review, identity, sortArtist (slug_key(romanize(text)) or fold(text)), artistLetter, sortTitle, titleLetter, search (_haystack), initials (_initials), files (the phone's files table: name, label, href), sites [], key null (port library_page.py's _sort_key, _letter, _initials and _haystack exactly). Add server = {csrf, busy, active, removing, jobs, guitar:false, youtube:{ok:false, why:"YouTube isn't on the phone.", off:true}} (plus timers when ServerControls.timers) and song.fetchable. Reads through Database.read.
> PageRoutes: GET / and /index.html, GET /favicon.ico.
>
> Python, tests/test_conformance_library_page.py: data/caracole/page/library_assets.json (SCRIPTS, STYLESHEETS, TEMPLATES: the runtime order LibraryAssets reads); vectors/web/library_page.json (the script and style sha256_source of the real assets, and for two fixed data objects (one with Chinese, one with no songs) and WebControls with sync on and off, the sha256 of assemble_page's output, and the output itself for the smallest case); vectors/web/cards.jsonl (_sort_key, _letter, _initials, _haystack over the keys corpus's names). Any lane that changes library_assets regenerates these with this generator (§3).
> Commit: feat(android): the library page served on the phone, from caracole's own assets.

#### search-routes: /api/search and /api/artist on the phone

- Branch `android/search-routes` · kotlin · M2 · about 1700 lines · depends on server-shell, library-page, search-ug, search-suggest, search-sites, search-lacuerda, song-names · Phase A may start early
- Goal: The phone answers /api/search and /api/artist with search_routes.py's JSON over its own database, so the library page's search box works with the computer off.
- Owns: `android/server/src/main/kotlin/io/github/danielhp95/caracole/server/routes/SearchRoutes.kt`; `android/server/src/main/kotlin/io/github/danielhp95/caracole/server/routes/search/**`; `android/server/src/test/kotlin/io/github/danielhp95/caracole/server/routes/search/**`
- Must not touch: src/caracole/**; android/core/**; android/*/build.gradle.kts; AGENTS.md; any other lane's owns
- Provides: server.routes.SearchRoutes
- Consumes: core.search.*; core.sites.*; core.lacuerda.*; core.names.SongNames; server.page.SongCards; server.http.*, TestApp; vectors/web/api_search.jsonl
- Tests: android/server/src/test/kotlin/io/github/danielhp95/caracole/server/routes/search/ApiSearchTest.kt; android/server/src/test/kotlin/io/github/danielhp95/caracole/server/routes/search/SupersedeTest.kt; android/server/src/test/kotlin/io/github/danielhp95/caracole/server/routes/search/CacheTest.kt
- Done when: nix develop ./android -c gradle -p android :server:test passes: every record of vectors/web/api_search.jsonl matches (the masked card fields aside); a second search of the same box supersedes the first; another box's never does (a test)

Brief:

> Repo /home/dani/Projects/caracole. Lane search-routes: branch android/search-routes, worktree .claude/worktrees/search-routes (git -C /home/dani/Projects/caracole worktree add .claude/worktrees/search-routes -b android/search-routes main, or reuse them); never touch the main checkout's files. First read the plan, docs/superpowers/plans/2026-11-03-android-port-m1-m3.md, §7.0 (phases, merging, drift, and the shared machine: pytest -n 4 in the loop, the whole suite once before merging, never `gradle --stop`, no omnibin-shell, no live request, no emulator). Depends on: server-shell, library-page, search-ug, search-suggest, search-sites, search-lacuerda, song-names. Phase: Phase A while any of server-shell, library-page, search-ug, search-suggest, search-sites, search-lacuerda, song-names has not merged into main (the part named Phase A below; commit, and end your report with 'waiting on: <lanes>'); Phase B once they all have (merge main into your branch, finish, merge). Test first; conventional commits; no Claude or AI attribution. When every done_when holds with main merged in: git -C /home/dani/Projects/caracole merge --no-ff android/search-routes.
>
> Plan sections: §1, §5.2 (SearchRoutes), §5.3, §5.5. The skeleton's SearchRoutes is neutral; replace it whole.
> Phase A (while any producer is unmerged): the port against the declared signatures, with ApiSearchTest written. Phase B: every vector matches.
>
> Port web/search_routes.py ~171-1162: q = ' '.join(query.split())[:200] in code points; short when sum(c.isalnum()) < (2 if has_han else 3) -> {query, library:[], index:[], short:true}; _found_for and its keys in order (query, library, index, artists, lead, best, hint, progression, unseen, names, removed, gtptabs, musescore, harptabs, harptabs_artists, gametabs, lacuerda, lacuerda_artists, lacuerda_unlisted, lacuerda_leads, lacuerda_search, youtube, suggest, skipped, partial, looked) with progression, lacuerda_search, lacuerda_unlisted and youtube null (the vectors were recorded with exactly those off); _skipped and _looked from the enabled set and the index_state kv (LaCuerda.lettersRead, SiteKeys' index states; no provider:<name> kv on the phone in M2-M3, so nothing cools down); _rows, _hit_json, _owners, _Mine (a site hit is your song by an accepted or pinned match, then identity_key, then compact name_forms), the per-site row JSON with artist_key/title_key from identity_key and group_key on artists, _suggestion_json, _names_json; /api/artist's three forms (key/offset, 50 a page; a lacuerda slug or lacuerda_name, up to 1000 songs with read/listed/total/gtptabs; a harptabs path matching artist/\d+/slug). One search at a time on one worker (a Mutex), the newest per box wins: an older search of that box answers {query, superseded:true} when it ends (the bundled SQLite has no progress handler: check between queries); an answer cache of 300 s and 128 entries by q, dropped by invalidate(). Reads through Database.read. JSON with ordered maps; floats compare by value. A database error -> 503 {query, error}. The test replays the vectors through TestApp over each fixture, with a SongCards that gives the masked fields.
> Commit: feat(android): the phone's search routes, as caracole serve's.

#### app-local: The app on its own server, and the index imported

- Branch `android/app-local` · kotlin · M2 · about 1200 lines · depends on server-shell, library-page, search-routes, index-transfer · Phase A may start early
- Goal: The app starts the phone's local server, sets the launch cookie, opens http://127.0.0.1:8738/ in the WebView in place of the asset loader, loads nothing at any other origin, and imports the computer's index from a file or from the computer as a job.
- Owns: `android/app/src/main/**`; `android/app/src/test/**`; `android/app/src/androidTest/kotlin/io/github/danielhp95/caracole/EndToEndTest.kt`; `android/app/src/androidTest/kotlin/io/github/danielhp95/caracole/PinchTest.kt`; `android/app/src/androidTest/kotlin/io/github/danielhp95/caracole/Pages.kt`; `android/app/src/androidTest/kotlin/io/github/danielhp95/caracole/LocalServerTest.kt`; `android/app/build.gradle.kts (dependencies only; the skeleton's tasks stay)`; `android/mirror/src/main/kotlin/io/github/danielhp95/caracole/mirror/Links.kt`; `android/mirror/src/test/kotlin/io/github/danielhp95/caracole/mirror/LinksTest.kt`; `android/README.md (its '## Search with the computer off' section and the sections the switch changes; not '## Sync from the phone')`
- Must not touch: android/core/**; android/server/**; android/mirror/src/main/kotlin/io/github/danielhp95/caracole/mirror/Manifest.kt; android/mirror/src/main/kotlin/io/github/danielhp95/caracole/mirror/Mirror.kt; android/mirror/src/main/kotlin/io/github/danielhp95/caracole/mirror/SyncEngine.kt; android/mirror/src/main/kotlin/io/github/danielhp95/caracole/mirror/Http.kt; android/settings.gradle.kts; android/flake.nix; AGENTS.md; src/**; any other lane's owns
- Provides: the app on 127.0.0.1:8738 with the launch cookie, its exact origin only; index import from a file or from the computer, as a job
- Consumes: server.Phone (importIndex); core.index.IndexTransfer; mirror.*
- Tests: android/mirror/src/test/kotlin/io/github/danielhp95/caracole/mirror/LinksTest.kt; android/app/src/test/... (Settings, origin restore, the download path); android/app/src/androidTest/kotlin/io/github/danielhp95/caracole/LocalServerTest.kt (compiled; integration runs it)
- Done when: nix develop ./android -c gradle -p android test assembleDebug assembleRelease assembleDebugAndroidTest passes; LinksTest: a page only at the server's exact origin; http://127.0.0.1:8737/ and any other loopback port are Browser

Brief:

> Repo /home/dani/Projects/caracole. Lane app-local: branch android/app-local, worktree .claude/worktrees/app-local (git -C /home/dani/Projects/caracole worktree add .claude/worktrees/app-local -b android/app-local main, or reuse them); never touch the main checkout's files. First read the plan, docs/superpowers/plans/2026-11-03-android-port-m1-m3.md, §7.0 (phases, merging, drift, and the shared machine: pytest -n 4 in the loop, the whole suite once before merging, never `gradle --stop`, no omnibin-shell, no live request, no emulator). Depends on: server-shell, library-page, search-routes, index-transfer. Phase: Phase A while any of server-shell, library-page, search-routes, index-transfer has not merged into main (the part named Phase A below; commit, and end your report with 'waiting on: <lanes>'); Phase B once they all have (merge main into your branch, finish, merge). Test first; conventional commits; no Claude or AI attribution. When every done_when holds with main merged in: git -C /home/dani/Projects/caracole merge --no-ff android/app-local.
>
> Plan sections: §1 (the cookie, origins), §2, §5.2 (Assembly.kt's Phone, mirror Links), §5.3, §5.4, §5.5, and android/README.md.
> Phase A (while a producer is unmerged): the app's wiring against Phone, which the skeleton wrote whole. Phase B: assemble and test with the real modules.
>
> - Caracole.kt: one Database (filesDir/caracole.sqlite, IndexTransfer.seedFresh at creation inside writeBlocking), one Phone(PhoneDeps(...)) per process, the secret (SecureRandom 32 bytes, hex) and the csrf per launch.
> - MainActivity: before the first loadUrl, CookieManager.getInstance().setCookie(origin, 'caracole-launch=<secret>; Path=/; HttpOnly; SameSite=Lax') and flush(); load origin + '/'. shouldInterceptRequest returns null (to the socket) only for the server's exact origin (scheme, host and port: LocalServer.origin), and a 404 for every other origin, loopback included, since cookies ignore the port. restoreState only when the saved origin equals today's. Retire WebViewAssetLoader and MirrorPathHandler (delete them): the mirror is served by the local server's file route.
> - mirror Links.kt: Links(origin, lookup): a page only at that exact origin; any other http(s) origin, 127.0.0.1:8737 included, is Browser; files are File. Update LinksTest.
> - Downloads: a File link (and the WebView's download listener) is read in-process through the App (App.handle of the path, with the cookie) and handed off as today (Handoff copies it to cacheDir and opens it with the FileProvider); never a DownloadManager request, which carries no cookie.
> - Settings: 'Import indexes': 'From the computer' (GET /api/peer/index into filesDir/state/cache: a plain mirror.Http GET until sync-client's PeerClient.index lands) or 'From a file' (ACTION_OPEN_DOCUMENT, copied into filesDir/state/cache); an IndexImportWorker (WorkManager, setForeground with a progress notification; FOREGROUND_SERVICE, FOREGROUND_SERVICE_DATA_SYNC and the service type in the manifest) calls Phone.importIndex(file) and awaits the job, so the merge never writes beside a sync.
> - androidTest: update EndToEndTest, PinchTest and Pages for the new origin; add LocalServerTest (the app's server answers /, refuses a request without the cookie, and the WebView never loads another loopback port). They must compile (assembleDebugAndroidTest); the integration step runs them on the emulator.
> - android/README.md: fill '## Search with the computer off' (importing the index, what works offline, the 127.0.0.1 server and its cookie) and correct the sections the switch changes (the offline copy is served by the app's own server; no appassets origin).
> Commit: feat(android): the app's own server on 127.0.0.1, and the computer's index imported.

#### peer-format2: Sync FORMAT 2 on the computer: canonical hashing, names on a take

- Branch `android/peer-format2` · python · M3 · about 1100 lines · depends on canonical · Phase A may start early
- Goal: peer_sync speaks FORMAT 2: raw and lyrics hashed canonically, a tagged base, 'now' and 'indexes' in the state document, a UnitSource under apply_units with a compare-and-swap of this side's digests, and a take that writes the peer's names verbatim with §5.6's respelling and folder moves.
- Owns: `src/caracole/peer_sync.py`; `src/caracole/index_transfer.py (newest() alone)`; `tests/test_peer_sync.py`; `tests/test_index_transfer.py (newest's tests alone)`; `tests/test_commands_peer.py (first; then peer-push-routes, then peer-sync-cli)`; `tests/test_web_peer.py (first; then peer-push-routes)`; `docs/usage.md (only the 'Two caracoles' paragraphs on formats)`; `docs/superpowers/specs/2026-10-31-phone-server-sync-design.md (its format, take and Phases text)`
- Must not touch: src/caracole/canonical.py; src/caracole/web/**; src/caracole/commands/**; src/caracole/songs.py; src/caracole/library_page.py; src/caracole/library_assets/**; android/**; AGENTS.md; any other lane's owns
- Provides: FORMAT 2 on the computer; peer_sync.UnitSource, value_of_document, apply_units(source, expected_here); the state document's now and indexes; index_transfer.newest; §5.6's take in Python
- Consumes: caracole.canonical
- Tests: tests/test_peer_sync.py; tests/test_commands_peer.py; tests/test_web_peer.py; tests/test_index_transfer.py
- Done when: nix develop -c pytest -q passes; a pull of a song spelled differently here ends with equal digests on both sides (a test); a take whose artist differs in case alone respells every song of that artist and leaves one folder (a test, on a case-insensitive check of the folder names); value_of_document(id, unit_document(x)) == value(x) for every unit of the test libraries (a property test); ruff check --select E4,E7,E9,F src tests is clean

Brief:

> Repo /home/dani/Projects/caracole. Lane peer-format2: branch android/peer-format2, worktree .claude/worktrees/peer-format2 (git -C /home/dani/Projects/caracole worktree add .claude/worktrees/peer-format2 -b android/peer-format2 main, or reuse them); never touch the main checkout's files. First read the plan, docs/superpowers/plans/2026-11-03-android-port-m1-m3.md, §7.0 (phases, merging, drift, and the shared machine: pytest -n 4 in the loop, the whole suite once before merging, never `gradle --stop`, no omnibin-shell, no live request, no emulator). Depends on: canonical. Phase: Phase A while any of canonical has not merged into main (the part named Phase A below; commit, and end your report with 'waiting on: <lanes>'); Phase B once they all have (merge main into your branch, finish, merge). Test first; conventional commits; no Claude or AI attribution. When every done_when holds with main merged in: git -C /home/dani/Projects/caracole merge --no-ff android/peer-format2.
>
> Plan sections: §1, §4, §5.6, and docs/superpowers/specs/2026-10-31-phone-server-sync-design.md. caracole's rules apply (AGENTS.md): every change runs as a queued caracole command; overrides.toml and songbooks.toml only through their writers; the library through library.write_atomic and descriptors opened O_NOFOLLOW; nothing private in the library.
> Phase A (before canonical merges): everything but the switch to canonical.py's hash. Phase B: the switch, and every test passing.
>
> peer_sync.py:
> - FORMAT = 2; song_value hashes versions' raw and lyrics_json with canonical.stored_hash; digest_of delegates to canonical.digest.
> - The stored base kv sync:base:<peer> becomes {'format':2,'units':{...}}, written with kv_set_json; _read_base reads anything else as None (no translation of a FORMAT 1 base: the owner's rule against compatibility shims; §4 says what the first sync then shows).
> - The state document gains 'now' (a utcnow stamp) and 'indexes' ({site: index_transfer.newest(conn)[site]}); every reader ignores keys it doesn't know.
> - index_transfer.newest(conn) -> {site: stamp}: per site of index_transfer.SITES, the newest read time of its rows and progress records, as merge compares them; a test, and lane index-transfer's Kotlin twin must agree.
> - A UnitSource Protocol (unit(id), file(key, name, sha256)) that Peer implements; value_of_document(unit_id, doc) -> the unit's value from its document alone (the inverse of song_document and the others).
> - apply_units(conn, cfg, source, wanted, now, *, expected_here: Mapping[str, str | None] | None = None, on_unit=None): a unit whose digest here differs from expected_here[id] is left, 'changed here since the comparison'; sqlite3.IntegrityError is caught per unit like the other unit errors.
> - _take_song by §5.6: the peer's names verbatim (today upsert_song keeps here's, so 'radiohead - creep' here and 'Radiohead - Creep' there never agree); when the taken artist's folder differs from the library's spelling in case alone, every song of that artist respelled (artist, and artists[0] where it equals the old artist), the artist's folder renamed once through a temporary name, each respelled song reported; a song's folder change moving its files and files.path in its savepoint, its old render records dropped; the moves through descriptors opened O_NOFOLLOW from the library down; a failed move leaves the song whole in one folder; a taken song forgets this side's tombstone of its key; rows, kv and overrides entries whole or not at all (an outer savepoint around the rows, rolled back when writing overrides.toml fails).
> Tests: tests/test_peer_sync.py (FORMAT 2 digests, the tagged base and an untagged one read as none, value_of_document's property, the CAS, IntegrityError per unit, names verbatim, the respelling, a folder move that fails halfway), test_commands_peer.py and test_web_peer.py updated to FORMAT 2 and the new state keys.
> Docs: docs/usage.md's 'Two caracoles' paragraphs on formats (FORMAT 2; a first sync after the upgrade shows plain differences); the design doc's text on formats and the take.
> Drift: sync-corpus generates from this code; if it has merged already, regenerate its corpus and run gradle (§3).
> Commit: feat(peer): sync format 2, canonical hashing of records and lyrics, and names taken as written.

#### peer-push-routes: POST /peer/push, caracole peer take, GET /api/peer/index

- Branch `android/peer-push-routes` · python · M3 · about 1500 lines · depends on peer-format2 · Phase A may start early
- Goal: caracole serve accepts a staged push from the phone (POST /peer/push/new, /peer/push/file, /peer/push) with body kinds and limits per route, takes it with `caracole peer take` under the lock, streams its index at GET /api/peer/index, and a computer can push to another.
- Owns: `src/caracole/peer_push.py`; `src/caracole/web/app.py (first; then sync-tab's one docstring line)`; `src/caracole/web/server.py`; `src/caracole/web/peer_routes.py`; `src/caracole/commands/peer.py (first: peer take; then peer-sync-cli)`; `tests/test_peer_push.py`; `tests/test_web_server.py`; `tests/test_web_app.py (first; then sync-tab)`; `tests/test_web_peer.py (after peer-format2)`; `tests/test_commands_peer.py (after peer-format2; then peer-sync-cli)`; `docs/usage.md (only '### The phone pushes its changes (POST /peer/push)')`
- Must not touch: src/caracole/peer_sync.py; src/caracole/canonical.py; src/caracole/web/offline_routes.py; src/caracole/web/sync_routes.py; src/caracole/library_page.py; src/caracole/library_assets/**; android/**; AGENTS.md; any other lane's owns
- Provides: Route(body=, limit=) and app.body_limit in caracole serve; a streamed file Response; POST /peer/push/new, /peer/push/file, /peer/push; GET /api/peer/index; caracole peer take [--progress] DIR; peer_push.StagedSource and push_units (a push client)
- Consumes: peer_sync FORMAT 2 (UnitSource, value_of_document, apply_units)
- Tests: tests/test_peer_push.py; tests/test_web_server.py; tests/test_web_app.py; tests/test_web_peer.py; tests/test_commands_peer.py
- Done when: nix develop -c pytest -q passes; a push staged by a test client is taken by `caracole peer take` and both sides then agree (record_agreement on both); a 20 MB JSON push is refused 413 before routing; a 1 MiB /peer/pull form is accepted; a bad push id or sha256 is refused before any path is built (tests); tests/conformance/vectors/web/routing.jsonl regenerates with no change (the form routes' behaviour kept); ruff check --select E4,E7,E9,F src tests is clean

Brief:

> Repo /home/dani/Projects/caracole. Lane peer-push-routes: branch android/peer-push-routes, worktree .claude/worktrees/peer-push-routes (git -C /home/dani/Projects/caracole worktree add .claude/worktrees/peer-push-routes -b android/peer-push-routes main, or reuse them); never touch the main checkout's files. First read the plan, docs/superpowers/plans/2026-11-03-android-port-m1-m3.md, §7.0 (phases, merging, drift, and the shared machine: pytest -n 4 in the loop, the whole suite once before merging, never `gradle --stop`, no omnibin-shell, no live request, no emulator). Depends on: peer-format2. Phase: Phase A while any of peer-format2 has not merged into main (the part named Phase A below; commit, and end your report with 'waiting on: <lanes>'); Phase B once they all have (merge main into your branch, finish, merge). Test first; conventional commits; no Claude or AI attribution. When every done_when holds with main merged in: git -C /home/dani/Projects/caracole merge --no-ff android/peer-push-routes.
>
> Plan sections: §1 (what caracole serve writes), §5.3 (the computer's table, the push document, caracole peer take), §5.6. caracole's rules apply (AGENTS.md); the exception this lane adds to "serve writes only wanted.txt and its history" is the push staging and the temporary index export, nothing else (the skeleton wrote it into AGENTS.md).
> Phase A (before peer-format2 merges): web/app.py and server.py's body kinds, the staging and its checks. Phase B: peer take and the push end to end.
>
> 1. web/app.py and web/server.py: Route gains body='form'|'json'|'bytes' and limit; server.py asks app.body_limit(method, path) before reading (411/413 as today beyond it; an unknown path keeps 16 KiB); json and bytes routes need cross_origin_ok and X-Caracole-Form-Token == csrf; POST /peer/pull's limit becomes 1 MiB (sync-tab gives POST /sync/apply 1 MiB the same way); a GET Response may carry a body path, which server.py writes in chunks. Update web/app.py's docstring. The form routes' behaviour is unchanged: regenerate tests/conformance/vectors/web/routing.jsonl (tests/test_conformance_web.py) and expect no diff.
> 2. src/caracole/peer_push.py (new, with its docstring): the staging folder state_dir/peer/push-<id>/ (0700: push.json, files/<sha256>); push ids 16 hex and sha256 64 hex checked before any path is built; at most 2 pushes open, 64 MiB a file, 2 GiB a push; StagedSource(UnitSource); uncommitted pushes deleted after an hour; push_units(peer, units, ...), a push client for one computer pushing to another (the three requests the phone makes).
> 3. web/peer_routes.py: POST /peer/push/new, /peer/push/file and /peer/push with §5.3's bodies, checks and answers (queue `caracole peer take --progress DIR` under 'peer-push:<from>', join=False, app.queued); GET /api/peer/index[?sites=] streaming a temporary index_transfer.export from cache_dir/peer/ (one read transaction, no lock), deleted after.
> 4. commands/peer.py: `caracole peer take [--progress] DIR`: §5.3's steps (check, backup, take, render, agree; a line per unit; exit 0 unless a bug); exclusive(interactive=True); --progress prints get.py's JSON line events per stage and {"event":"unit","id","outcome","why"} per unit.
> Tests: tests/test_peer_push.py (a real WebApp in a thread: a push of an added song, a removal, a songbook, a conflict left by the CAS, a bad digest refused, a missing file refused, a stale token 403 reload, a 20 MB JSON body refused, a bad push id; peer take end to end with a fake runner; GET /api/peer/index merged into another database), test_web_server.py (411/413 by route), test_web_app.py (body kinds).
> Docs: docs/usage.md's '### The phone pushes its changes (POST /peer/push)'.
> Commits: feat(web): a body kind and a limit per route; feat(peer): POST /peer/push and caracole peer take; feat(peer): the index streamed at GET /api/peer/index.

#### peer-sync-cli: caracole peer sync by push, by choice, against a comparison

- Branch `android/peer-sync-cli` · python · M3 · about 700 lines · depends on peer-push-routes · starts after its producers merge
- Goal: `caracole peer sync ADDRESS` can give by pushing (--push), take the owner's choices from its command line (--choose), refuse a changed comparison (--compared), report its stages (--progress), and record the peer's address for serve to read.
- Owns: `src/caracole/commands/peer.py (after peer-push-routes)`; `tests/test_commands_peer.py (after peer-push-routes)`; `docs/usage.md (only '### Syncing by hand: peer sync --push, --choose, --compared')`
- Must not touch: src/caracole/peer_sync.py; src/caracole/peer_push.py; src/caracole/web/**; android/**; AGENTS.md; any other lane's owns
- Provides: caracole peer sync --push --choose --compared --progress; kv sync:peer:<id> = {address, name, synced_at}
- Consumes: peer_push.push_units; peer_sync.compare, decide, apply_units(expected_here)
- Tests: tests/test_commands_peer.py
- Done when: nix develop -c pytest -q passes; two computers' libraries in a test sync with --push and --choose and end with no differences; --compared with a stale hash refuses before any change (a test); ruff check --select E4,E7,E9,F src tests is clean

Brief:

> Repo /home/dani/Projects/caracole. Lane peer-sync-cli: branch android/peer-sync-cli, worktree .claude/worktrees/peer-sync-cli (git -C /home/dani/Projects/caracole worktree add .claude/worktrees/peer-sync-cli -b android/peer-sync-cli main, or reuse them); never touch the main checkout's files. First read the plan, docs/superpowers/plans/2026-11-03-android-port-m1-m3.md, §7.0 (phases, merging, drift, and the shared machine: pytest -n 4 in the loop, the whole suite once before merging, never `gradle --stop`, no omnibin-shell, no live request, no emulator). Depends on: peer-push-routes. Phase: start only once peer-push-routes have merged into main; merge main into your branch first. Test first; conventional commits; no Claude or AI attribution. When every done_when holds with main merged in: git -C /home/dani/Projects/caracole merge --no-ff android/peer-sync-cli.
>
> Plan sections: §5.3 (the computer's table: GET /api/sync's kv, /sync/apply's argv; the sync view's stages), §5.6.
>
> commands/peer.py, `caracole peer sync ADDRESS`:
> - --push: give by pushing (peer_push.push_units) instead of asking the other side to pull, so only this side needs to reach the other.
> - --choose=<here|there|skip>:<unit id>, repeatable (side first: unit ids hold '/' and ':'); a conflict with neither a choice nor --prefer is left, as today.
> - --compared HASH: compare afresh and refuse, before any change, when Compare's hash differs: sha256 of canonical.dumps([[id, proposal, here, there], ...]) in _order's order, here and there the digests or null (lane sync-units ports the same hash).
> - --progress: get.py's JSON line events for the stages compare, take, give, agree, and a unit event per unit taken, given or left.
> - After a sync, kv sync:peer:<peer id> = {address, name, synced_at} (kv_set_json), which caracole serve's GET /api/sync reads; serve writes nothing of it.
> Pulling keeps the compared digests (expected_here on this side; the peer's compared digests for what it takes).
> Tests in tests/test_commands_peer.py: two libraries in threads with WebApps and fake runners, a sync by --push with choices, a stale --compared, the progress lines, the kv record.
> Docs: docs/usage.md's '### Syncing by hand: peer sync --push, --choose, --compared'.
> Commit: feat(peer): caracole peer sync by push, with the owner's choices and the comparison they were made on.

#### sync-corpus: The sync corpus

- Branch `android/sync-corpus` · python · M3 · about 900 lines · depends on peer-format2 · Phase A may start early
- Goal: The Python suite writes fixture libraries with their unit values, digests, documents and labels, comparison cases, take cases and the library's add/remove rules, so the Kotlin sync code is checked against FORMAT 2 Python.
- Owns: `tests/test_conformance_sync.py`; `tests/conformance/vectors/sync/**`; `tests/conformance/vectors/library/**`
- Must not touch: src/**; android/**; AGENTS.md; tests/helpers/corpus.py; any other lane's owns
- Provides: vectors/sync/fixtures/*.jsonl; vectors/sync/{values,documents,compare,merged_base,record_agreement,decide,name_key,compared_hash,take}.jsonl; vectors/library/{add,remove,lyrics_files,stamps,ensure_current_keys}.jsonl
- Consumes: peer_sync (FORMAT 2); caracole.canonical; songs.upsert_song, removal.remove_song, lyrics, stamps
- Tests: tests/test_conformance_sync.py
- Done when: nix develop -c pytest -q passes, with the corpus generated from FORMAT 2 peer_sync; every unit kind, every compare case of the design's table and every §5.6 rule appears in the vectors

Brief:

> Repo /home/dani/Projects/caracole. Lane sync-corpus: branch android/sync-corpus, worktree .claude/worktrees/sync-corpus (git -C /home/dani/Projects/caracole worktree add .claude/worktrees/sync-corpus -b android/sync-corpus main, or reuse them); never touch the main checkout's files. First read the plan, docs/superpowers/plans/2026-11-03-android-port-m1-m3.md, §7.0 (phases, merging, drift, and the shared machine: pytest -n 4 in the loop, the whole suite once before merging, never `gradle --stop`, no omnibin-shell, no live request, no emulator). Depends on: peer-format2. Phase: Phase A while any of peer-format2 has not merged into main (the part named Phase A below; commit, and end your report with 'waiting on: <lanes>'); Phase B once they all have (merge main into your branch, finish, merge). Test first; conventional commits; no Claude or AI attribution. When every done_when holds with main merged in: git -C /home/dani/Projects/caracole merge --no-ff android/sync-corpus.
>
> Plan sections: §3 (fixtures), §4, §5.1 (core/sync, core/library), §5.4, §5.6.
> Phase A (before peer-format2 merges): the generator against main's peer_sync. Phase B: regenerate from FORMAT 2 and finish.
>
> tests/test_conformance_sync.py writes:
> - vectors/sync/fixtures/<name>.jsonl: libraries built with caracole's own helpers (tests/helpers/library_songs.py, songbooks.py, the overrides writers): songs with versions, kept files (file lines), lyrics, every overrides table (match, pin, transpose, reject, youtube, lacuerda, harptabs, gametabs, azlyrics, version, harmonica, ignore, alias, artist_url, block), songbooks with settings, tombstones, Chinese and non-BMP names, a tab_id '101' beside '99' (BINARY order), carried kv (sheet_versions:yours: and the others), two songs of one artist. The overrides and songbooks are written as phone_overrides and phone_songbooks rows ({table:'phone_overrides', row:{tbl, key, written, value: canonical.dumps(the value as song_entries, alias, ... yield it)}}), which replay_fixture creates from phone.sql, so Kotlin loads one database that is the whole library.
> - values.jsonl: per fixture and unit {fixture, id, label, value, digest}, from peer_sync.library_state and each value function.
> - documents.jsonl: unit_document for every unit (what GET /api/peer/unit's 'unit' holds) and value_of_document's result.
> - compare.jsonl: {mine, theirs, base, out:[{id, label, proposal, why}]} over every row of the design's three-way table, first syncs, a unit appearing and going, both sides making one change, and 'removed here, changed there' (song/K a conflict, removed/K mine).
> - merged_base.jsonl, record_agreement.jsonl (base before, mine, theirs, at -> the base text after, byte for byte, and the count), decide.jsonl, name_key.jsonl (songbook.name_key over ß, İ, NFC/NFD pairs, whitespace), compared_hash.jsonl (the --compared hash of differences lists).
> - take.jsonl: for each §5.6 rule, a fixture before, the units taken (documents), and the library after as values and digests: names verbatim; the respelling of an artist differing in case alone; a song new here; a taken song forgetting a tombstone ('removed here, changed there, resolved there'); a song absent there; a tombstone made or forgotten; a refused file name; the CAS left.
> - vectors/library/add.jsonl (songs.upsert_song for one song: _artist_as_written, strip, title_variant, artists, a tombstone dropped by key or by source id, a song of that key found), remove.jsonl (removal.remove_song's database effects: the tombstone, the rows gone, each _PER_SONG_KV prefix), lyrics_files.jsonl (the lyrics.txt and lyrics.lrc a take writes from lyrics_json), stamps.jsonl (stamps.parse over what datetime.fromisoformat accepts and refuses), ensure_current_keys.jsonl (songs and tombstones re-keyed when the keys record is older).
> Commit: test(conformance): the sync corpus.

#### sync-tab: The Sync tab of the library page, and the computer's sync routes

- Branch `android/sync-tab` · mixed · M3 · about 1900 lines · depends on peer-sync-cli, library-page · Phase A may start early
- Goal: A served-only Sync tab, in JavaScript and two templates, that lists a sync's differences, lets the owner choose a side for each and syncs; the computer's GET /api/sync, POST /sync/compare and POST /sync/apply; the sync and peer-push job views; and the vectors the phone replays.
- Owns: `src/caracole/library_assets/sync.js`; `src/caracole/library_assets/sync.css`; `src/caracole/library_assets/sync-tab.html`; `src/caracole/library_assets/sync-panel.html`; `src/caracole/library_page.py (only if the templates need a blank more)`; `src/caracole/web/sync_routes.py`; `src/caracole/web/library_routes.py`; `src/caracole/web/jobs_routes.py`; `src/caracole/web/status.py`; `src/caracole/web/outcome.py`; `src/caracole/web/app.py (its docstring's list of route modules, one line, after peer-push-routes)`; `tests/test_web_sync.py`; `tests/test_sync_tab.py`; `tests/test_requests_tab.py`; `tests/test_web_app.py (the route modules' names, after peer-push-routes)`; `tests/test_conformance_sync_routes.py`; `tests/conformance/vectors/web/sync_routes.jsonl`; `tests/conformance/vectors/web/job_views.jsonl`; `docs/usage.md (only '### The Sync tab')`
- Must not touch: src/caracole/peer_sync.py; src/caracole/peer_push.py; src/caracole/commands/peer.py; src/caracole/web/peer_routes.py; android/**; AGENTS.md; any other lane's owns
- Provides: library_assets/sync.js, sync.css, sync-tab.html, sync-panel.html; GET /api/sync, POST /sync/compare, POST /sync/apply on the computer; the sync and peer-push job views; vectors/web/{sync_routes,job_views}.jsonl
- Consumes: caracole peer sync --push --choose --compared --progress; kv sync:peer:<id>; peer_sync.compare; library-page's generator (to regenerate library_page.json)
- Tests: tests/test_web_sync.py; tests/test_sync_tab.py; tests/test_requests_tab.py; tests/test_conformance_sync_routes.py
- Done when: nix develop -c pytest -q passes (the Chromium tests included where chromium is on PATH); two computers' caracole serves in a test sync through the tab's routes and end with no differences; tests/conformance/vectors/web/library_page.json regenerated, and nix develop ./android -c gradle -p android :server:test passes against it; vectors/web/job_views.jsonl covers the sync, peer-push, add and remove kinds in every state

Brief:

> Repo /home/dani/Projects/caracole. Lane sync-tab: branch android/sync-tab, worktree .claude/worktrees/sync-tab (git -C /home/dani/Projects/caracole worktree add .claude/worktrees/sync-tab -b android/sync-tab main, or reuse them); never touch the main checkout's files. First read the plan, docs/superpowers/plans/2026-11-03-android-port-m1-m3.md, §7.0 (phases, merging, drift, and the shared machine: pytest -n 4 in the loop, the whole suite once before merging, never `gradle --stop`, no omnibin-shell, no live request, no emulator). Depends on: peer-sync-cli, library-page. Phase: Phase A while any of peer-sync-cli, library-page has not merged into main (the part named Phase A below; commit, and end your report with 'waiting on: <lanes>'); Phase B once they all have (merge main into your branch, finish, merge). Test first; conventional commits; no Claude or AI attribution. When every done_when holds with main merged in: git -C /home/dani/Projects/caracole merge --no-ff android/sync-tab.
>
> Plan sections: §3 (drift), §5.3 (/api/sync, /sync/compare, /sync/apply; the sync job's view), and AGENTS.md's rules for pages (no innerHTML: createElement and textContent; CSP by hash; connect only to the server; tabs.js's tablist).
> Phase A (before peer-sync-cli and library-page merge): sync.js, sync.css, the templates and the Chromium tests against a fake runner. Phase B: the routes over the real commands, the vectors, the regenerated page corpus.
>
> - The tab's markup is the templates sync-tab.html (the tab-sync button, before Requests) and sync-panel.html (the #sync panel), which both sides put in verbatim; the page stays a pure function of the assets, so the phone needs no code change for your markup. Change library_page.py only if a blank must be added, and say so in §5.3 of the plan in the same commit.
> - sync.js and sync.css: the tab draws from GET /api/sync (the address remembered, the peers synced before); an address field and Compare (POST /sync/compare); the differences grouped by kind (Songs, Removals, Songbooks, Artists' aliases, Artists' UG pages, Blocked tabs), each with its proposal in words ('keep here's', 'take there's', 'CONFLICT') and a choice (here, there, skip; a conflict has none until chosen); 'Keep here's for every conflict' and 'Take there's for every conflict'; Sync (POST /sync/apply, the choices in one field, only conflicts and flipped proposals), disabled until every conflict is chosen; the job tracked through window.caracoleLibrary.track and 'caracole:job', its stages shown; at its end, what was taken, given and left (the view's outcome), and Reload. Only differences and choices travel, never documents.
> - web/library_routes.py serves the page with WebControls.sync=True; test_requests_tab.py's phone-fit test becomes five tabs at 390 px (renamed to say so).
> - src/caracole/web/sync_routes.py (new: its ROUTES and docstring line; add it to tests/test_web_app.py's list of route modules and to web/app.py's docstring list): GET /api/sync (kv sync:peer:* and the bases); POST /sync/compare (compares with the address over HTTP as `caracole peer diff` does; keeps the comparison 10 minutes by id; here and there are digests); POST /sync/apply (limit 1 MiB through peer-push-routes' Route(limit=); queues `caracole peer sync ADDRESS --compared HASH --push --progress --choose=<side>:<id> ...` under 'sync:<address>', kind 'sync'; serve writes no file for it).
> - web/jobs_routes.py, status.py and outcome.py: the sync and peer-push kinds' views, lines and outcomes, exactly the keys of §5.3's view.
> - tests/test_conformance_sync_routes.py: vectors/web/sync_routes.jsonl (the three routes' answers over two fixture WebApps, comparison ids and tokens masked) and vectors/web/job_views.jsonl (jobs_routes.view over synthetic jobs of the sync, peer-push, add and remove kinds in each state), which the phone replays (lanes jobs and phone-sync-routes).
> - Regenerate vectors/web/library_page.json with library-page's generator (CARACOLE_CORPUS=write nix develop -c pytest -q -n 0 tests/test_conformance_library_page.py) and run gradle's :server:test against it before merging (§3's drift protocol).
> - docs/usage.md: fill '### The Sync tab'.
> Tests: tests/test_web_sync.py (the routes against two WebApps in threads with fake runners), tests/test_sync_tab.py (Chromium: draw, choose, conflict gating, Sync posts one field, the job's end shows Reload, 390 px light and dark).
> Commit: feat(web): the Sync tab, for a computer and the phone.

#### offline-units: The mirror's pages carry their units

- Branch `android/offline-units` · mixed · M3 · about 600 lines · depends on nothing · runs at once
- Goal: /api/offline names each file's unit and digest, and the phone's mirror parses them, so the local server serves a computer page only while the phone's unit agrees with it; the mirror no longer makes the computer's index.html the start page.
- Owns: `src/caracole/web/offline_routes.py`; `tests/test_web_offline.py`; `docs/usage.md (only '### What the offline copy lists')`; `android/mirror/src/main/kotlin/io/github/danielhp95/caracole/mirror/Manifest.kt (after the skeleton's Entry fields)`; `android/mirror/src/main/kotlin/io/github/danielhp95/caracole/mirror/Mirror.kt (after the skeleton's pageFor; keep it as written)`; `android/mirror/src/main/kotlin/io/github/danielhp95/caracole/mirror/SyncEngine.kt`; `android/mirror/src/test/kotlin/io/github/danielhp95/caracole/mirror/ManifestTest.kt`; `android/mirror/src/test/kotlin/io/github/danielhp95/caracole/mirror/MirrorLookupTest.kt`; `android/mirror/src/test/kotlin/io/github/danielhp95/caracole/mirror/SyncEngineTest.kt`; `android/mirror/src/test/kotlin/io/github/danielhp95/caracole/mirror/FakeCaracole.kt`
- Must not touch: android/mirror/src/main/kotlin/io/github/danielhp95/caracole/mirror/Links.kt; android/mirror/src/main/kotlin/io/github/danielhp95/caracole/mirror/Http.kt; src/caracole/peer_sync.py; android/app/**; android/server/**; AGENTS.md; any other lane's owns
- Provides: /api/offline entries' unit and digest; mirror.Entry.unit/digest parsed; Mirror.pageFor tested over every Gate
- Consumes: peer_sync.library_state; the skeleton's UnitGate, Gate, Mirror.pageFor
- Tests: tests/test_web_offline.py; android/mirror/src/test/kotlin/io/github/danielhp95/caracole/mirror/ManifestTest.kt; android/mirror/src/test/kotlin/io/github/danielhp95/caracole/mirror/MirrorLookupTest.kt; android/mirror/src/test/kotlin/io/github/danielhp95/caracole/mirror/SyncEngineTest.kt
- Done when: nix develop -c pytest -q passes; nix develop ./android -c gradle -p android :mirror:test passes; the manifest parser still reads a manifest with format 1's fields alone (a test)

Brief:

> Repo /home/dani/Projects/caracole. Lane offline-units: branch android/offline-units, worktree .claude/worktrees/offline-units (git -C /home/dani/Projects/caracole worktree add .claude/worktrees/offline-units -b android/offline-units main, or reuse them); never touch the main checkout's files. First read the plan, docs/superpowers/plans/2026-11-03-android-port-m1-m3.md, §7.0 (phases, merging, drift, and the shared machine: pytest -n 4 in the loop, the whole suite once before merging, never `gradle --stop`, no omnibin-shell, no live request, no emulator). Depends on: nothing. Phase: no lane comes before you: do it all at once. Test first; conventional commits; no Claude or AI attribution. When every done_when holds with main merged in: git -C /home/dani/Projects/caracole merge --no-ff android/offline-units.
>
> Plan sections: §1 (mirrored pages, gating, removed songs), §5.2 (:mirror additions), §5.3 (/api/offline), §5.4.
>
> Python: web/offline_routes.py: each manifest entry of a song's file (its folder's sheet.html, the versions' pages, PDFs, harmonica pages, files) carries 'unit': 'song/<key>' and 'digest' (peer_sync.library_state's digest when the manifest is made), and each songbook's files 'songbook/<name key>'; index.html and files of no unit carry neither; the format stays 1 (the app's parser ignores unknown keys). tests/test_web_offline.py covers it. docs/usage.md: fill '### What the offline copy lists'.
> Kotlin (android/mirror): Manifest's parser reads Entry.unit and digest when present (the skeleton added the fields, default null); MirrorLookupTest covers the skeleton's Mirror.pageFor over SERVE, CHANGED and REMOVED and an entry of no unit; SyncEngine keeps swapping manifest.json and its blobs whole as today (the phone's own files never live in blobs/), and its report's counts stay; Manifest.start is no longer the app's start page (the local server's / is), which only means nothing in :mirror navigates to it. Tests in android/mirror/src/test with FakeCaracole serving unit and digest.
> Commit: feat(android): the mirror's pages carry their units, for the phone's gate.

#### jobs: The phone's job queue

- Branch `android/jobs` · kotlin · M3 · about 1100 lines · depends on server-shell, sync-tab · Phase A may start early
- Goal: A coroutine job queue the library page follows exactly as it follows caracole serve's: /jobs.json views as jobs_routes.view writes them (replayed from vectors), /api/jobs/N, /jobs/cancel, one job per key, stages as steps.
- Owns: `android/server/src/main/kotlin/io/github/danielhp95/caracole/server/jobs/**`; `android/server/src/test/kotlin/io/github/danielhp95/caracole/server/jobs/**`
- Must not touch: src/**; android/core/**; android/*/build.gradle.kts; AGENTS.md; any other lane's owns
- Provides: server.jobs.JobQueue/Job/JobSpec/JobContext/JobViews/JobsRoutes
- Consumes: server.http.*, TestApp; server.page.SongCards (the interface; a fake in tests); vectors/web/job_views.jsonl
- Tests: android/server/src/test/kotlin/io/github/danielhp95/caracole/server/jobs/JobQueueTest.kt; android/server/src/test/kotlin/io/github/danielhp95/caracole/server/jobs/JobsRoutesTest.kt; android/server/src/test/kotlin/io/github/danielhp95/caracole/server/jobs/JobViewsTest.kt
- Done when: nix develop ./android -c gradle -p android :server:test passes; /jobs.json without the token header is 403 with reload (a test through TestApp); every record of vectors/web/job_views.jsonl matches JobViews.view for the same job

Brief:

> Repo /home/dani/Projects/caracole. Lane jobs: branch android/jobs, worktree .claude/worktrees/jobs (git -C /home/dani/Projects/caracole worktree add .claude/worktrees/jobs -b android/jobs main, or reuse them); never touch the main checkout's files. First read the plan, docs/superpowers/plans/2026-11-03-android-port-m1-m3.md, §7.0 (phases, merging, drift, and the shared machine: pytest -n 4 in the loop, the whole suite once before merging, never `gradle --stop`, no omnibin-shell, no live request, no emulator). Depends on: server-shell, sync-tab. Phase: Phase A while any of server-shell, sync-tab has not merged into main (the part named Phase A below; commit, and end your report with 'waiting on: <lanes>'); Phase B once they all have (merge main into your branch, finish, merge). Test first; conventional commits; no Claude or AI attribution. When every done_when holds with main merged in: git -C /home/dani/Projects/caracole merge --no-ff android/jobs.
>
> Plan sections: §5.2 (server/jobs), §5.3 (the sync job's view), §5.5. The skeleton's JobsRoutes is neutral; replace it whole.
> Phase A (before server-shell and sync-tab merge): the queue and its tests (a TestScope). Phase B: the routes through TestApp and the view vectors.
>
> Port what the page reads of web/jobs.py, jobs_routes.py, status.py and outcome.py: JobQueue (limit 20 active, keep 100 over; one job per key: a waiting job with the same key and join=true is returned in place of a new one); states queued, running, done, failed, cancelled, interrupted; cancel takes a queued job out (never a running one); one worker coroutine, so jobs never write beside each other; await(id); Job.asJson = {id, title, display, state, active, note, queued_at, started_at, finished_at, steps:[{name,label,state,detail}], commands:[], song, files:[], seconds_to_sheet:null}; JobContext.outcome(value) sets the view's outcome; JobViews.view to §5.3's shape, each kind's line worded as vectors/web/job_views.jsonl records Python's (sync, peer-push, add, remove), details '#tab=sync' for a sync. JobsRoutes: GET /jobs.json?jobs=N,M (50 ids at most; scriptOnly, so the token header) -> {active, jobs:[view]}, with card (SongCards) for a finished add or remove and songbooks when a view says so; GET /api/jobs/N (under=true) -> asJson, or 404 JSON; POST /jobs/cancel as jobs_routes.py's. onBusy(true/false) as the queue goes busy and idle (the app's foreground service listens). History in memory only.
> Commit: feat(android): the phone's job queue, as the library page follows caracole serve's.

#### sync-units: The phone's units, digests and three-way comparison

- Branch `android/sync-units` · kotlin · M3 · about 1500 lines · depends on keys, canonical, sync-corpus · Phase A may start early
- Goal: Units and Compare give, over the phone's database, exactly the values, digests, labels, documents, proposals, hashes and base text Python's peer_sync gives for the same library, with the phone's overrides and songbooks stores.
- Owns: `android/core/src/main/kotlin/io/github/danielhp95/caracole/core/sync/Units.kt`; `android/core/src/main/kotlin/io/github/danielhp95/caracole/core/sync/Compare.kt`; `android/core/src/main/kotlin/io/github/danielhp95/caracole/core/sync/internal/units/**`; `android/core/src/main/kotlin/io/github/danielhp95/caracole/core/library/OverridesStore.kt`; `android/core/src/main/kotlin/io/github/danielhp95/caracole/core/library/SongbookStore.kt`; `android/core/src/test/kotlin/io/github/danielhp95/caracole/core/sync/UnitsTest.kt`; `android/core/src/test/kotlin/io/github/danielhp95/caracole/core/sync/CompareTest.kt`; `android/core/src/test/kotlin/io/github/danielhp95/caracole/core/library/StoresTest.kt`
- Must not touch: android/core/src/main/kotlin/io/github/danielhp95/caracole/core/sync/Source.kt; android/core/src/main/kotlin/io/github/danielhp95/caracole/core/library/Songs.kt; src/**; AGENTS.md; any other lane's owns
- Provides: core.sync.Units (digestOf for the gate); core.sync.Compare (comparedHash, order); core.sync.SyncUnit/Difference/Base; core.library.OverridesStore; core.library.SongbookStore
- Consumes: core.json.Canonical, PyJson; core.keys.Normalize; core.py.PyUnicode; vectors/sync/*
- Tests: android/core/src/test/kotlin/io/github/danielhp95/caracole/core/sync/UnitsTest.kt; android/core/src/test/kotlin/io/github/danielhp95/caracole/core/sync/CompareTest.kt; android/core/src/test/kotlin/io/github/danielhp95/caracole/core/library/StoresTest.kt
- Done when: nix develop ./android -c gradle -p android :core:test passes: every value, digest, label and document of vectors/sync matches; every compare, merged_base, record_agreement (base text byte for byte), decide, name_key and compared_hash case matches; ForbiddenApiTest passes

Brief:

> Repo /home/dani/Projects/caracole. Lane sync-units: branch android/sync-units, worktree .claude/worktrees/sync-units (git -C /home/dani/Projects/caracole worktree add .claude/worktrees/sync-units -b android/sync-units main, or reuse them); never touch the main checkout's files. First read the plan, docs/superpowers/plans/2026-11-03-android-port-m1-m3.md, §7.0 (phases, merging, drift, and the shared machine: pytest -n 4 in the loop, the whole suite once before merging, never `gradle --stop`, no omnibin-shell, no live request, no emulator). Depends on: keys, canonical, sync-corpus. Phase: Phase A while any of keys, canonical, sync-corpus has not merged into main (the part named Phase A below; commit, and end your report with 'waiting on: <lanes>'); Phase B once they all have (merge main into your branch, finish, merge). Test first; conventional commits; no Claude or AI attribution. When every done_when holds with main merged in: git -C /home/dani/Projects/caracole merge --no-ff android/sync-units.
>
> Plan sections: §4, §5.1 (core/sync Units, Compare; core/library OverridesStore, SongbookStore), §5.4, §5.5. Units.digestOf's stub is neutral (null); the gate starts working when yours lands.
> Phase A (before keys, canonical and sync-corpus merge): the port. Phase B: the vectors pass.
>
> Port peer_sync.py's library_state; song_value (names {artist, artists, title, album, duration_ms, variant}; status; review bool; match [decision, artist key, song key]; lyrics [status, H(lyrics_json)]; versions from SQL ORDER BY provider, tab_id in SQLite BINARY order, never re-sorted in Kotlin, each {provider, tab, slot, kind, label, pick, gone: gone != 0, url, raw: H(raw)}; files {name: sha256}; overrides = OverridesStore.songEntries); removed_value {artist, title}; songbook_value {name, songs: [[entry, parts with only the non-null key, mode, capo, instrument]]}; alias (the slugs list); artist_url {name, page}; block true; labels ('A - T', 'A - T (removed)', ...); digest = Canonical.digest; unit ids song/<key>, removed/<key>, songbook/<SongbookStore.nameKey(name)> (NFC, whitespace collapsed, casefold: PyUnicode), alias/<slug_key>, artist_url/<slug_key>, block/<tab>. Documents: song_document {key, names, song: the SONG_COLUMNS cells as stored (match_candidates text NOT NULL, review/ug_dirty 0/1, match_score REAL), versions: the VERSION_COLUMNS cells plus files [{name, sha256, kept_rank}] sorted by name, kv: CARRIED_KV keyed 'prefix|rest', overrides}, and the other kinds' documents as peer_sync.unit_document gives them; valueOfDocument. Compare: ownId (kv sync:id), baseOf (the FORMAT 2 tagged base; untagged reads as none), mergedBase (the later 'at' wins, mine on a tie), compare (proposals and why's words as Python's), decide, order (_order: kinds song, removed, songbook, alias, artist_url, block; then label casefold; then id), comparedHash (sha256 of C([[id, proposal, here, there], ...]) in order), recordAgreement (writes the tagged base with Db.kvSetJson in code-point key order, so its text is Python's byte for byte; called inside Database.write).
> OverridesStore and SongbookStore over phone_overrides and phone_songbooks (§5.4): values stored as Canonical.write text and read back as JsonElement.
> Commit: feat(android): the phone's sync units and the three-way comparison.

#### sync-take: The phone takes units, adds and removes songs

- Branch `android/sync-take` · kotlin · M3 · about 1900 lines · depends on sync-units · Phase A may start early
- Goal: Take.applyUnits writes units from a UnitSource into the phone's database and library folder by §5.6's rules, whole and checked against the compared digests, and LibraryStore adds, removes and re-keys songs by caracole's rules; the backup before a sync is a full openable database that restore puts back.
- Owns: `android/core/src/main/kotlin/io/github/danielhp95/caracole/core/sync/Take.kt`; `android/core/src/main/kotlin/io/github/danielhp95/caracole/core/sync/internal/take/**`; `android/core/src/main/kotlin/io/github/danielhp95/caracole/core/library/LibraryStore.kt`; `android/core/src/main/kotlin/io/github/danielhp95/caracole/core/library/internal/**`; `android/core/src/test/kotlin/io/github/danielhp95/caracole/core/sync/TakeTest.kt`; `android/core/src/test/kotlin/io/github/danielhp95/caracole/core/library/LibraryStoreTest.kt`
- Must not touch: android/core/src/main/kotlin/io/github/danielhp95/caracole/core/sync/Units.kt; android/core/src/main/kotlin/io/github/danielhp95/caracole/core/sync/Compare.kt; android/core/src/main/kotlin/io/github/danielhp95/caracole/core/sync/Source.kt; android/core/src/main/kotlin/io/github/danielhp95/caracole/core/library/Songs.kt; src/**; AGENTS.md; any other lane's owns
- Provides: core.sync.Take (applyUnits, backupBeforeSync, restore, checkedName); core.library.LibraryStore (add, remove, ensureCurrentKeys)
- Consumes: core.sync.Units/Compare; core.library.OverridesStore/SongbookStore; core.keys.SafeName; vectors/sync/take.jsonl, vectors/library/*
- Tests: android/core/src/test/kotlin/io/github/danielhp95/caracole/core/sync/TakeTest.kt; android/core/src/test/kotlin/io/github/danielhp95/caracole/core/library/LibraryStoreTest.kt
- Done when: nix develop ./android -c gradle -p android :core:test passes: every record of vectors/sync/take.jsonl and vectors/library/*.jsonl matches; every fixture of vectors/sync taken into an empty phone yields its exact values and digests (a test); a backup made before a take restores the library tables exactly (a test); ForbiddenApiTest passes

Brief:

> Repo /home/dani/Projects/caracole. Lane sync-take: branch android/sync-take, worktree .claude/worktrees/sync-take (git -C /home/dani/Projects/caracole worktree add .claude/worktrees/sync-take -b android/sync-take main, or reuse them); never touch the main checkout's files. First read the plan, docs/superpowers/plans/2026-11-03-android-port-m1-m3.md, §7.0 (phases, merging, drift, and the shared machine: pytest -n 4 in the loop, the whole suite once before merging, never `gradle --stop`, no omnibin-shell, no live request, no emulator). Depends on: sync-units. Phase: Phase A while any of sync-units has not merged into main (the part named Phase A below; commit, and end your report with 'waiting on: <lanes>'); Phase B once they all have (merge main into your branch, finish, merge). Test first; conventional commits; no Claude or AI attribution. When every done_when holds with main merged in: git -C /home/dani/Projects/caracole merge --no-ff android/sync-take.
>
> Plan sections: §1, §5.1 (Take, LibraryStore, UnitSource), §5.4, §5.5 (all of this runs inside Database.write), §5.6 (the rules, shared with Python), and AGENTS.md's invariant 'A removed song stays removed until you ask for it again'.
> Phase A (before sync-units merges): the port and an in-memory UnitSource. Phase B: the vectors pass.
>
> LibraryStore.add: songs.upsert_song's rules for one song, held by vectors/library/add.jsonl: the identity key; _artist_as_written (a new song's artist takes the library's spelling when only case differs); strip, title_variant and artists as upsert_song makes them; a tombstone of that key or source id goes; a song of that key is found, not doubled; added_at and created_at now; source_ids '{}'; status wanted; match_candidates '[]'. LibraryStore.remove: removal.remove_song's on the phone (vectors/library/remove.jsonl): in one savepoint a tombstone {key, artist, title, source_ids, removed_at}, the row deleted (versions and files cascade), every _PER_SONG_KV prefix of songs.py for its id; then the files LibraryStore wrote in its folder; the phone has no wanted.txt. LibraryStore.ensureCurrentKeys: songs.ensure_current_keys for songs and tombstones (vectors/library/ensure_current_keys.jsonl); its keys record is seeded at creation through fresh_kv.json.
> Take.applyUnits, the wanted units sorted by kind order, each by §5.6: fetch its document (source.unit) and leave it when Units.valueOfDocument's digest differs from the compared one ('changed there since the comparison') or when the phone's own digest differs from expectedHere ('changed here since the comparison'); a song: identity_key(names) == key; file names through checkedName (no '/', '\', leading '.', '' or '..'), paths resolved canonically under libraryDir with no link followed; every file whose sha256 differs here fetched first (source.file, sha-checked) and written atomically into the song's folder; a song new here created through LibraryStore.add, then overwritten; in one savepoint the names verbatim, SONG_COLUMNS, versions and files replaced, the carried kv re-keyed to the phone's id, the overrides entries (OverridesStore.putSongEntries), the tombstone of its key forgotten; the respelling of an artist differing in case alone, its folder renamed once through a temporary name, each song in Applied.respelled; lyrics.txt and lyrics.lrc from lyrics_json as peer_sync writes them (vectors/library/lyrics_files.jsonl); files no longer kept deleted after the savepoint. A song absent there: LibraryStore.remove. removed: a tombstone only when neither the song nor one exists; absent: forgotten. songbook, alias, artist_url, block: put or dropped. An error in a unit leaves it with its reason and never aborts the rest; stamps parsed as stamps.parse (vectors/library/stamps.jsonl).
> backupBeforeSync: a new file migrated from migrations.json and phone.sql, the library tables (songs, versions, files, removed, kv, phone_*) copied in through ATTACH; state/backups/before-sync-<stamp>.sqlite, 3 kept, none made without free space of twice the copy's size. restore(db, backup): those tables back, in one savepoint.
> Tests with an in-memory UnitSource built from the vectors/sync fixtures' documents: every fixture taken into an empty phone gives Units.libraryState equal to its values; each take.jsonl case; the CAS refusals; a removal leaves a tombstone and LibraryStore.add brings the song back new; a failing file fetch changes nothing of that song; a backup restores.
> Commit: feat(android): the phone takes sync units, adds and removes songs.

#### sync-client: The phone's sync engine and peer client

- Branch `android/sync-client` · kotlin · M3 · about 1500 lines · depends on sync-take, peer-push-routes · Phase A may start early
- Goal: PeerClient speaks the computer's peer routes (state, unit, file, push, jobs, index), and SyncEngine runs a whole phone-started sync: compare, take, give, mirror, agree, index.
- Owns: `android/core/src/main/kotlin/io/github/danielhp95/caracole/core/sync/PeerClient.kt`; `android/core/src/main/kotlin/io/github/danielhp95/caracole/core/sync/SyncEngine.kt`; `android/core/src/main/kotlin/io/github/danielhp95/caracole/core/sync/internal/client/**`; `android/core/src/test/kotlin/io/github/danielhp95/caracole/core/sync/client/**`; `android/core/src/testFixtures/kotlin/io/github/danielhp95/caracole/core/testing/sync/**`; `android/mirror/src/main/kotlin/io/github/danielhp95/caracole/mirror/Http.kt`; `android/mirror/src/test/kotlin/io/github/danielhp95/caracole/mirror/HttpTest.kt`
- Must not touch: android/core/src/main/kotlin/io/github/danielhp95/caracole/core/sync/Units.kt; android/core/src/main/kotlin/io/github/danielhp95/caracole/core/sync/Compare.kt; android/core/src/main/kotlin/io/github/danielhp95/caracole/core/sync/Take.kt; android/core/src/main/kotlin/io/github/danielhp95/caracole/core/sync/Source.kt; android/mirror/src/main/kotlin/io/github/danielhp95/caracole/mirror/Manifest.kt; android/mirror/src/main/kotlin/io/github/danielhp95/caracole/mirror/Mirror.kt; android/mirror/src/main/kotlin/io/github/danielhp95/caracole/mirror/SyncEngine.kt; android/mirror/src/main/kotlin/io/github/danielhp95/caracole/mirror/Links.kt; src/**; AGENTS.md; any other lane's owns
- Provides: core.sync.PeerClient; core.sync.SyncEngine; mirror.Http.post and per-call timeouts; core testFixtures FakeComputer (for :core and :server tests)
- Consumes: core.sync.Units/Compare/Take; core.index.IndexTransfer; core.json.Canonical; mirror.ServerAddress; the computer's peer routes (peer-push-routes); vectors/sync/*
- Tests: android/core/src/test/kotlin/io/github/danielhp95/caracole/core/sync/client/PeerClientTest.kt; android/core/src/test/kotlin/io/github/danielhp95/caracole/core/sync/client/SyncEngineTest.kt; android/mirror/src/test/kotlin/io/github/danielhp95/caracole/mirror/HttpTest.kt
- Done when: nix develop ./android -c gradle -p android :core:test :mirror:test passes; a sync against FakeComputer ends with both sides' states equal and both bases recording the agreement; Database.writes is free while give polls the computer's job (a test)

Brief:

> Repo /home/dani/Projects/caracole. Lane sync-client: branch android/sync-client, worktree .claude/worktrees/sync-client (git -C /home/dani/Projects/caracole worktree add .claude/worktrees/sync-client -b android/sync-client main, or reuse them); never touch the main checkout's files. First read the plan, docs/superpowers/plans/2026-11-03-android-port-m1-m3.md, §7.0 (phases, merging, drift, and the shared machine: pytest -n 4 in the loop, the whole suite once before merging, never `gradle --stop`, no omnibin-shell, no live request, no emulator). Depends on: sync-take, peer-push-routes. Phase: Phase A while any of sync-take, peer-push-routes has not merged into main (the part named Phase A below; commit, and end your report with 'waiting on: <lanes>'); Phase B once they all have (merge main into your branch, finish, merge). Test first; conventional commits; no Claude or AI attribution. When every done_when holds with main merged in: git -C /home/dani/Projects/caracole merge --no-ff android/sync-client.
>
> Plan sections: §1, §5.1 (PeerClient, SyncEngine, Comparison, Side, SyncOutcome), §5.3 (the computer's routes, the push document, the phone's sync), §5.5.
> Phase A (before sync-take and peer-push-routes merge): mirror Http, PeerClient against FakeComputer, SyncEngine. Phase B: the take through the real Take, and FakeComputer's answers checked against peer-push-routes' routes.
>
> - mirror Http.kt gains post(address, uri, type, headers, body writer, read) (no redirects, no cookies; HttpURLConnection) and GET with extra headers, and a read timeout per call; keep its behaviour and tests.
> - PeerClient: GET /api/peer/state?peer= (60 s read timeout), /api/peer/unit?id= (format 2 checked), /api/peer/file?song=&name= (sha256 checked); POST /peer/push/new, /peer/push/file and /peer/push (JSON or bytes, the header X-Caracole-Form-Token, Accept: application/json; no Origin and no Sec-Fetch-Site: a non-browser passes cross_origin_ok); GET /api/jobs/<id>; GET /api/peer/index streamed to a file with no read timeout; a 403 whose JSON says reload re-reads the state once for a fresh token and retries.
> - SyncEngine.compare: the state, Units.libraryState (Database.read), mergedBase, compare, and Compare.comparedHash, kept by id 10 minutes. apply: §5.3's six stages, each through stage(name, state, detail); decide with choices and prefer (a conflict with neither: refused before any change); take: Take.backupBeforeSync, then Take.applyUnits inside Database.write (source = the client, expectedHere = the compared phone digests); give: the push document with the phone's state after its take and at = the compared state's now, the job polled every second for 10 minutes at most, with no lock held; mirror: mirrorRefresh(address); agree: the state again, then Compare.recordAgreement at its now inside Database.write, and kv sync:peer:<computer id> = {address, name, synced_at} (what GET /api/sync lists); index: the sites whose 'indexes' stamp is newer than kv sync:index:<peer id>, fetched with PeerClient.index into state/cache and merged with IndexTransfer.merge inside Database.write, the kv updated; skipped when none is newer; a failure there leaves the agreement.
> - FakeComputer, in :core's testFixtures (core/testing/sync/FakeComputer.kt) so :server's tests reach it too: a com.sun.net.httpserver (as mirror's FakeCaracole) holding a library loaded from the vectors/sync fixtures and answering the routes with Python's documents.
> Tests: a full sync both ways with a conflict; a token change mid-sync; a computer that changed a unit between compare and take (left); a push job that fails (left, the base not moved); the index stage fetching only newer sites; no lock held while give polls.
> Commit: feat(android): the phone's sync engine, pulling then pushing.

#### phone-sync-routes: The phone's Sync tab routes, add and remove

- Branch `android/phone-sync-routes` · kotlin · M3 · about 1400 lines · depends on jobs, sync-client, song-names, sync-tab · Phase A may start early
- Goal: The phone answers the Sync tab's routes with the computer's JSON, runs a sync as a job, and adds and removes songs from the library page (Get it and Fetch now included), so both sides can change things.
- Owns: `android/server/src/main/kotlin/io/github/danielhp95/caracole/server/routes/SyncRoutes.kt`; `android/server/src/main/kotlin/io/github/danielhp95/caracole/server/routes/LibraryRoutes.kt`; `android/server/src/main/kotlin/io/github/danielhp95/caracole/server/routes/library/**`; `android/server/src/test/kotlin/io/github/danielhp95/caracole/server/routes/library/**`
- Must not touch: src/**; android/core/**; android/server/src/main/kotlin/io/github/danielhp95/caracole/server/Assembly.kt; android/server/src/main/kotlin/io/github/danielhp95/caracole/server/routes/Stubs.kt; AGENTS.md; any other lane's owns
- Provides: server.routes.SyncRoutes; server.routes.LibraryRoutes (POST /request, /lookup, /remove)
- Consumes: core.sync.SyncEngine; core.library.LibraryStore; core.names.SongNames; server.jobs.*; server.page.SongCards; TestApp, FakeComputer; vectors/web/sync_routes.jsonl, job_views.jsonl
- Tests: android/server/src/test/kotlin/io/github/danielhp95/caracole/server/routes/library/SyncRoutesTest.kt; android/server/src/test/kotlin/io/github/danielhp95/caracole/server/routes/library/LibraryRoutesTest.kt
- Done when: nix develop ./android -c gradle -p android :server:test passes; every record of vectors/web/sync_routes.jsonl matches the phone's answer over the same comparison (masked ids and tokens aside); compare then apply against FakeComputer ends with the job done and the states equal; a conflict without a choice is 409; add then remove leaves a tombstone; Get it (POST /lookup) adds the song (tests)

Brief:

> Repo /home/dani/Projects/caracole. Lane phone-sync-routes: branch android/phone-sync-routes, worktree .claude/worktrees/phone-sync-routes (git -C /home/dani/Projects/caracole worktree add .claude/worktrees/phone-sync-routes -b android/phone-sync-routes main, or reuse them); never touch the main checkout's files. First read the plan, docs/superpowers/plans/2026-11-03-android-port-m1-m3.md, §7.0 (phases, merging, drift, and the shared machine: pytest -n 4 in the loop, the whole suite once before merging, never `gradle --stop`, no omnibin-shell, no live request, no emulator). Depends on: jobs, sync-client, song-names, sync-tab. Phase: Phase A while any of jobs, sync-client, song-names, sync-tab has not merged into main (the part named Phase A below; commit, and end your report with 'waiting on: <lanes>'); Phase B once they all have (merge main into your branch, finish, merge). Test first; conventional commits; no Claude or AI attribution. When every done_when holds with main merged in: git -C /home/dani/Projects/caracole merge --no-ff android/phone-sync-routes.
>
> Plan sections: §5.2 (SyncRoutes, LibraryRoutes, SyncSettings), §5.3 (the phone's table and the sync view), §5.5. The skeleton's SyncRoutes and LibraryRoutes are neutral; replace them whole. The page's JS is sync-tab's src/caracole/library_assets/sync.js: read it and web/sync_routes.py, and answer the same shapes.
> Phase A (while a producer is unmerged): the routes against the declared signatures. Phase B: the vectors and the end-to-end tests.
>
> SyncRoutes: GET /api/sync {server: Compare.ownId, name, address: settings.address, peers:[{address, server, name, synced_at}] from the kv bases and sync:peer records}; POST /sync/compare (form csrf, address) -> SyncEngine.compare's JSON, remembering the address; POST /sync/apply (limit 1 MiB; form csrf, comparison, prefer, choices lines '<here|there|skip>\t<id>') -> a JobSpec (kind 'sync', key 'sync:<address>', stages compare, take, give, mirror, agree, index) running SyncEngine.apply and setting the view's outcome, then afterSync() (the search cache invalidated, the page data reloaded) -> App.queued(view); refusals 409 in the words the Python routes use. LibraryRoutes: POST /request as library_routes.request reads it (q read by SongNames.readNames, or the artist and title fields): fetch=0 and fetch=1 both add through LibraryStore.add as an 'add' job, its view's card from SongCards, fetch=1's line saying 'Added: the computer's next run fetches it.'; POST /lookup adds the same way and answers a lookup's shape, 202 {job, url:'/api/jobs/N', view}, which rows.js's queueAndFollow follows; POST /remove as remove_routes.remove: the question's data {removal:{song, key, display, ...}}, then the confirmed removal queued under 'remove:<key>' running LibraryStore.remove. Every write through Database.write inside its job.
> Tests through TestApp with FakeComputer (core testFixtures).
> Commit: feat(android): the Sync tab, add and remove on the phone.

#### app-sync: Sync from the app

- Branch `android/app-sync` · kotlin · M3 · about 600 lines · depends on app-local, phone-sync-routes, offline-units · starts after its producers merge
- Goal: The app's Sync tab works on the phone: the computer's address comes from Settings, a running job keeps the process alive in a foreground service, and after a sync the mirror and the page show the result.
- Owns: `android/app/src/main/** (after app-local)`; `android/app/src/test/** (after app-local)`; `android/app/src/androidTest/kotlin/io/github/danielhp95/caracole/SyncTabTest.kt`; `android/README.md (its '## Sync from the phone' section)`
- Must not touch: android/core/**; android/server/**; android/mirror/**; src/**; AGENTS.md; any other lane's owns
- Provides: the app's sync: settings, the foreground service, the Sync tab's entry
- Consumes: server.Phone; server.routes.SyncRoutes; server.jobs.JobQueue.onBusy
- Tests: android/app/src/test/... (SyncSettings); android/app/src/androidTest/kotlin/io/github/danielhp95/caracole/SyncTabTest.kt (compiled; integration runs it)
- Done when: nix develop ./android -c gradle -p android test assembleDebug assembleRelease assembleDebugAndroidTest passes

Brief:

> Repo /home/dani/Projects/caracole. Lane app-sync: branch android/app-sync, worktree .claude/worktrees/app-sync (git -C /home/dani/Projects/caracole worktree add .claude/worktrees/app-sync -b android/app-sync main, or reuse them); never touch the main checkout's files. First read the plan, docs/superpowers/plans/2026-11-03-android-port-m1-m3.md, §7.0 (phases, merging, drift, and the shared machine: pytest -n 4 in the loop, the whole suite once before merging, never `gradle --stop`, no omnibin-shell, no live request, no emulator). Depends on: app-local, phone-sync-routes, offline-units. Phase: start only once app-local, phone-sync-routes, offline-units have merged into main; merge main into your branch first. Test first; conventional commits; no Claude or AI attribution. When every done_when holds with main merged in: git -C /home/dani/Projects/caracole merge --no-ff android/app-sync.
>
> Plan sections: §1, §5.2 (Phone, SyncSettings, JobQueue.onBusy), and android/README.md. Start once app-local, phone-sync-routes and offline-units have merged; you own android/app/** after app-local.
>
> - SyncSettings over the app's Settings (the server address the mirror already keeps), so the Sync tab offers it.
> - A SyncService (foreground, type dataSync, a notification naming the running job, 'Syncing with <name>…' for a sync) started by JobQueue.onBusy(true) and stopped on false; the manifest's permissions.
> - The menu's Sync now runs the mirror refresh as today; a 'Sync with the computer' item opens the library page at #tab=sync.
> - After a sync job, Phone.search.invalidate() and the page data reloaded (afterSync).
> - androidTest: SyncTabTest against -e server http://10.0.2.2:PORT (the computer that `python -m tests.helpers.e2e_library serve` starts, lane e2e-jvm): the tab compares and syncs. It must compile; the integration step runs it on the emulator.
> - android/README.md: fill '## Sync from the phone' (what a sync does, choosing sides, the computer needing caracole with sync format 2, what shows for a song changed or removed on the phone).
> Commit: feat(android): sync from the phone's Sync tab.

#### e2e-jvm: The goal, end to end on the JVM against a real caracole serve

- Branch `android/e2e-jvm` · mixed · M3 · about 1300 lines · depends on phone-sync-routes, offline-units, index-transfer, search-routes, peer-sync-cli, sync-tab · Phase A may start early
- Goal: An automated test proves docs/android_port.md's goal on this machine: 20 songs changed on the computer reach the phone; with the computer off the phone searches and changes things; a sync lists the differences, the owner's choices apply, and both libraries end unit-for-unit equal.
- Owns: `tests/test_android_e2e.py`; `tests/helpers/e2e_library.py`; `android/e2e/**`; `pyproject.toml (the android_e2e marker alone)`
- Must not touch: src/**; android/core/**; android/server/** (report a bug to the integration step, with a failing test); AGENTS.md; any other lane's owns
- Provides: tests/helpers/e2e_library.py build(dir) and `python -m tests.helpers.e2e_library serve DIR PORT`; the JVM end-to-end scenario
- Consumes: server.Phone; caracole serve; caracole index export; caracole peer sync
- Tests: tests/test_android_e2e.py; android/e2e/src/test/.../PhoneScenarioTest.kt
- Done when: nix develop -c pytest -q passes (the e2e test skipped without CARACOLE_ANDROID_E2E); CARACOLE_ANDROID_E2E=1 nix develop -c pytest -q -n 0 tests/test_android_e2e.py passes; `python -m tests.helpers.e2e_library serve DIR PORT` builds the library and serves it on 0.0.0.0:PORT for the device tests

Brief:

> Repo /home/dani/Projects/caracole. Lane e2e-jvm: branch android/e2e-jvm, worktree .claude/worktrees/e2e-jvm (git -C /home/dani/Projects/caracole worktree add .claude/worktrees/e2e-jvm -b android/e2e-jvm main, or reuse them); never touch the main checkout's files. First read the plan, docs/superpowers/plans/2026-11-03-android-port-m1-m3.md, §7.0 (phases, merging, drift, and the shared machine: pytest -n 4 in the loop, the whole suite once before merging, never `gradle --stop`, no omnibin-shell, no live request, no emulator). Depends on: phone-sync-routes, offline-units, index-transfer, search-routes, peer-sync-cli, sync-tab. Phase: Phase A while any of phone-sync-routes, offline-units, index-transfer, search-routes, peer-sync-cli, sync-tab has not merged into main (the part named Phase A below; commit, and end your report with 'waiting on: <lanes>'); Phase B once they all have (merge main into your branch, finish, merge). Test first; conventional commits; no Claude or AI attribution. When every done_when holds with main merged in: git -C /home/dani/Projects/caracole merge --no-ff android/e2e-jvm.
>
> Plan sections: §9 (the scenario, which this lane builds), §5.3.
> Phase A (while a producer is unmerged): tests/helpers/e2e_library.py and its serve command, and the Python driver. Phase B: the Kotlin phases and the whole scenario passing.
>
> tests/helpers/e2e_library.py: build(dir) makes a 20-song library with no request (docs/screenshots/make.py's way, and tests/helpers: sheets kept, UG's index read from a written sitemap, a LaCuerda listing, gtptabs rows, real chordpro renders, pages written) and the goal's changes ([version] and [transpose] on 5 songs, a chosen sheet on 2); `python -m tests.helpers.e2e_library serve DIR PORT` builds it when absent, exports the index (caracole index export DIR/index.sqlite) and runs caracole serve on PORT (address 0.0.0.0, so the emulator reaches it at 10.0.2.2), for the device tests of the integration step.
> tests/test_android_e2e.py is marked slow and android_e2e (registered in pyproject.toml's markers), skipped unless CARACOLE_ANDROID_E2E=1, run with -n 0 under nix develop. Each Kotlin phase is a subprocess `nix develop ./android -c gradle -p android :e2e:test --rerun -Pcaracole.e2e.phase=N -Pcaracole.e2e.server=http://127.0.0.1:P -Pcaracole.e2e.dir=DIR`, whose JVM test (android/e2e, PhoneScenarioTest) builds server.Phone over DIR/phone, so the phone persists between phases, and drives it through TestApp's request builder against its App.
> The phases are §9's steps 1-7; assert what each says, and in phase 2 that the phone's PeerClient and mirror Http made no request at all (count them; the computer's port refused).
> Commit: test(android): the phone and the computer synced end to end.

---

## 8. Order

```
skeleton (android/skeleton, merged to main)
 ├─ at once, no producers: core-db · py-unicode · pinyin · fuzz · canonical · search-corpus · server-shell · offline-units
 │
 │  M2  keys (py-unicode, pinyin) ─┬─ search-query (keys, fuzz, search-corpus) ─┬─ search-ug ───────┐
 │                                 │                                            ├─ search-sites ────┼─ index-transfer (+ keys, canonical)
 │                                 │                                            ├─ search-lacuerda ─┘
 │                                 │                                            └─ search-suggest
 │                                 ├─ song-names (+ search-corpus)
 │                                 └─ library-page (+ server-shell)
 │      search-routes (server-shell, library-page, search-ug, -suggest, -sites, -lacuerda, song-names)
 │      app-local (server-shell, library-page, search-routes, index-transfer)                        → M2 done
 │
 │  M3  canonical ── peer-format2 ─┬─ peer-push-routes ── peer-sync-cli ── sync-tab (+ library-page) ── jobs (+ server-shell)
 │                                 └─ sync-corpus ── sync-units (+ keys, canonical) ── sync-take ── sync-client (+ peer-push-routes)
 │      phone-sync-routes (jobs, sync-client, song-names, sync-tab) ── app-sync (+ app-local, offline-units)
 │      e2e-jvm (phone-sync-routes, offline-units, index-transfer, search-routes, peer-sync-cli, sync-tab)  → M3 done
 └─ integration (every lane merged): the device step, AGENTS.md, the docs
```

**Scheduling, with at most 6 lanes at once:**
1. Start py-unicode, pinyin, fuzz, canonical, core-db and search-corpus. Their producers are the skeleton alone,
   and they feed both critical paths.
2. As slots free, start server-shell and offline-units.
3. Then the Phase A of keys, peer-format2, sync-corpus and library-page.
4. Then each lane as its producers merge, the critical paths first.

**The critical paths:**
- py-unicode → keys → search-query → search-sites and search-lacuerda → index-transfer → app-local;
- canonical → peer-format2 → peer-push-routes → peer-sync-cli → sync-tab → jobs → phone-sync-routes → app-sync;
- peer-format2 → sync-corpus → sync-units → sync-take → sync-client.

---

## 9. Integration

**The JVM scenario.** Lane `e2e-jvm` builds it, and the integration step runs it again. `tests/test_android_e2e.py`
is marked `slow` and `android_e2e` and skipped unless `CARACOLE_ANDROID_E2E=1`. Each Kotlin phase is
`nix develop ./android -c gradle -p android :e2e:test --rerun -Pcaracole.e2e.phase=N -Pcaracole.e2e.server=… -Pcaracole.e2e.dir=…`.
Its JVM test builds `Phone` (§5.2) over `dir/phone/`, so the phone's state persists between phases.

1. **Computer.**
   - `e2e_library.build(dir)` makes 20 songs with no request: sheets kept, a UG index from a written sitemap, a
     LaCuerda listing, gtptabs rows, real chordpro renders, pages written.
   - The goal's changes are made: `[version]` and `[transpose]` on 5 songs, and a sheet chosen on 2.
   - `caracole index export` writes `dir/index.sqlite`.
   - `caracole serve --address 127.0.0.1 --port P` starts.
2. **Phone, phase 1.**
   - The index comes in through `GET /api/peer/index` (`Phone.importIndex`).
   - A mirror sync runs, then the Sync tab's routes on the phone: `POST /sync/compare`, then `POST /sync/apply` with
     no choices.
   - Assert:
     - 20 songs, with digests equal to the computer's `/api/peer/state`;
     - `phone_overrides` holds the changes;
     - each mirrored `sheet.html` is served, its gate `SERVE`;
     - `/api/search` finds an indexed song that isn't in the library.
3. **Computer off.** Python stops serve.
4. **Phone, phase 2.**
   - `/api/search` finds a song of the index.
   - Songs are added: 1 through a search row's Get it (`POST /lookup`), 1 with `POST /request` and `fetch=1`, and 1
     with `fetch=0`.
   - Song R is removed (`POST /remove`), and so is a computer song, C1.
   - After the removal, C1's card is gone from `GET /`'s data, and its mirrored `sheet.html` answers "removed on the
     phone".
   - Assert that the phone's `PeerClient` and mirror `Http` sent no request in this phase (counted), and that the
     computer's port was refused.
5. **Computer.** Python starts serve again. `caracole add` adds 3 songs, and C1 and C2 change (`[transpose]`).
6. **Phone, phase 3.** `POST /sync/compare`, then assert these differences:
   - the phone's 3 adds, `mine`;
   - the computer's 3 adds, `theirs`;
   - C2, `theirs`;
   - song/C1, a conflict, with removed/C1 `mine`;
   - R's units, `mine`.

   Then apply with `C1=here`, and assert the job's stages are done and nothing is left. The other choice for C1,
   "there", is sync-take's and sync-client's tests.
7. **Both.**
   - The phone writes its `Units.libraryState` to `dir/phone-state.json`.
   - Python asserts it equals `peer_sync.library_state` of the computer, unit by unit.
   - A last phone phase compares again and finds no difference.
   - The computer lacks C1, and its wanted.txt holds the phone's 3 adds.

**The device step** (the integration step's own; no lane runs an emulator):
1. Build the emulator shell: `nix develop ./android#emulator`. Its first run downloads several GB of SDK, emulator
   and system image, so give it a long timeout.
2. Create the AVD as android/README.md says:
   `avdmanager create avd -n caracole -k "system-images;android-36;google_apis;x86_64" -d pixel_6`.
3. Start one emulator: `LD_LIBRARY_PATH=/run/opengl-driver/lib emulator -avd caracole -gpu host`. This needs a
   display, because the software renderers crash. Without one, stop and report it.
4. Start a computer for it: `nix develop -c python -m tests.helpers.e2e_library serve DIR P`.
5. Install `assembleDebug` and `assembleDebugAndroidTest`, then run one class at a time with
   `adb -s emulator-5554 shell am instrument -w -e class … [-e server http://10.0.2.2:P] io.github.danielhp95.caracole.test/androidx.test.runner.AndroidJUnitRunner`:
   - `BundledSqliteTest` (core-db);
   - `CorpusOnDeviceTest` (this step's own): the `unicode`, `keys`, `pinyin`, `fuzz` and `canonical` vectors from the
     androidTest assets (`Corpus.open` from the `AssetManager`), under Android's runtime and ICU-backed regex;
   - `LocalServerTest`, `EndToEndTest` and `PinchTest` (app-local);
   - `SyncTabTest` (app-sync);
   - `PhoneEndToEndTest` (this step's own), which checks:
     - the app's server at `http://127.0.0.1:8738/`;
     - the cookie set, and a cookieless request refused;
     - another loopback port never loaded in the WebView;
     - `Sec-Fetch-Site` reaching the server from the WebView;
     - a typed query showing `/api/search`'s rows;
     - a search row's Get it adding a song;
     - a removed song's card gone after a reload;
     - a sync from the Sync tab;
     - a sandboxed viewer's link back to the library carrying the cookie.

**What only a real phone can show:**
- `BundledSqliteTest` on arm64 (the emulator is x86_64);
- the index import's time and storage for the full 1.4 M-row UG index (about 400 MB, through triggers);
- `/api/search`'s latency on that index;
- a WebView whose Chromium differs from the emulator's (cookies on `http://127.0.0.1`, `Sec-Fetch-Site`);
- doze and the background limits during a long sync or import;
- Wi-Fi or tailnet reachability of the computer;
- the APK's size on arm64.

---

## 10. Risks

- Two implementations to maintain: every later change to search, keys, sync or the schema is made twice. The corpus and the drift protocol catch drift; they don't spare the work.
- Unicode and regex drift: a JDK or ICU text call in :core breaks agreement on some devices. ForbiddenApiTest (narrowed to regex arguments and an allow-list of surrogate helpers) and CorpusOnDeviceTest guard it.
- rapidfuzz: a port that departs from rapidfuzz-cpp 3.3.4's bisection order changes which reading wins; 6,000 random pairs and the committed reference transcription hold it.
- SQLite version skew (3.53.3 on the computer, 3.50.1 on the phone): the FTS5 tokenizers are expected to agree and the search corpus runs on both. REAL-to-TEXT printing differs, so no float goes through SQLite's text on the sync path.
- The index import's speed on a phone: 1.4 M rows through six triggers, about 400 MB, inside the one writer lock. A bulk path (copy, then rebuild the derived tables as migrations 5, 8 and 12 do) would give other derived ids; search-corpus orders every query whose order reaches an output, so ids decide nothing.
- The bundled SQLite has no progress handler (OMIT_PROGRESS_CALLBACK): a superseded search runs to its end before it answers 'superseded'.
- Python determinism fixes in search.py and lacuerda_index.py may change which of two tied results comes first; the existing tests must still pass.
- The take's respelling and folder moves change the computer's library folders; a move that half fails must leave each song whole in one folder, and a case-only rename needs a temporary name on case-blind file systems.
- Body kinds and limits in web/app.py and web/server.py change the path every request takes on the computer; the existing web tests and the unchanged routing corpus are the guard.
- caracole serve gains two writes of its own (the push staging, a temporary index export): an amendment to AGENTS.md's invariant, open to the owner (§11).
- Byte-for-byte asset copying: a git eol attribute or a Gradle filter changes the CSP hash and breaks the served page; library-page asserts the hashes against Python's, and the Sync tab's markup is templates, so the page stays a pure function of the assets.
- Coordination: lanes started early wait for producers (Phase A, then Phase B); a stalled producer stalls its consumers, and the orchestrator must restart Phase B as merges land.
- The shared machine: more than about 6 lanes at once, pytest above -n 4, or a `gradle --stop` from one agent makes others' runs flaky or fail; §7.0's rules and gradle.properties' worker cap hold it.
- The emulator is not built yet (several GB to fetch) and needs a display for -gpu host; every on-device test first runs in the integration step, so device-only failures surface late.
- Songs added on the phone show minimal cards (no key, no sites, no progressions), and a mirrored page of a song the phone changed falls back to the message page and sheet.txt until M5's page builder.
- Song ids are each database's own: the page's ids are the phone's, remapped by identity; a card the mirror has but the phone lacks (M2) gets a negative id and offers no write.
- Ktor CIO on Android is checked on the JVM and through R8 only until the integration step runs it on the emulator.
- The launch secret is a departure from caracole's no-secret rule, by the owner's choice; it holds only if the WebView loads nothing at another loopback origin (cookies ignore the port), which LinksTest and PhoneEndToEndTest check and only real phones fully show.
- Android background limits: an index import or a long sync needs a foreground service; doze on a real phone is untested here.

## 11. Open questions for the owner

1. A version's raw record is hashed whole (canonicalized) in FORMAT 2. UG's raw holds rating and votes, so one tab fetched by both sides at different times still differs. Keep it whole this round, and let M4 (the phone's first fetches) decide on a projection without volatile keys, which would be FORMAT 3?
2. On a take, when the taken artist's folder differs in case alone from how the library writes that artist, every song of that artist is respelled to the taken spelling and its folder renamed once (§5.6). That rewrites names in your library, on the computer as on the phone. Is that the rule you want, or should a take keep the library's spelling and leave such a song as a lasting difference?
3. caracole serve will write two things itself beyond wanted.txt and its history: the push staging folder (state_dir/peer/push-<id>/, 0700, deleted after the take or after an hour) and a temporary index export (cache_dir/peer/, deleted after streaming). Everything else stays a queued command's. Is that exception to AGENTS.md's invariant acceptable?
4. FORMAT 2 reads every stored FORMAT 1 sync base as none (no compatibility shim). Has a real `caracole peer sync` already run between two of your machines? If so, their first sync after the upgrade compares as a first sync, and a song one side removed since shows as the other side's to take until you flip it.
5. On the computer, the Sync tab syncs with another computer (pull, then push), since the phone serves nothing. Is that a use you want, or should the computer's tab only show the last sync with the phone?
6. The phone runs SQLite 3.50.1 (androidx sqlite-bundled 2.7.1, stable) against the computer's 3.53.3, with the search corpus holding them together. Is that fine, or pin sqlite-bundled 2.8.0-alpha03 (3.53.4), an alpha?

---

## 12. What the critiques changed

Every blocker and major issue from the two critiques was settled as listed here. Most minor issues were taken as
well.

**Blocker**
- **No owner for the Sync tab's markup on the phone.** The tab is now two templates, `sync-tab.html` and
  `sync-panel.html`, which both sides put in verbatim. The page is a pure function of the assets, so lane
  `sync-tab` changes it without any Kotlin change. sync-tab depends on library-page and regenerates its corpus.

**Major issues: completeness**
- **A removed song came back from the mirror.** `MirrorPageData` drops tombstoned cards. `PhoneGate` answers
  `REMOVED`, and `Songs.isRemoved` is final.
- **A take didn't forget the tombstone, and bypassed `add`.** This is now §5.6, with a corpus case.
- **The decimal rule rounded to 28 digits.** §4 now uses the exact value, a strict reading of the text, and
  bounded fallbacks, with vectors for each.
- **`kv` text wasn't Python's.** It now is: `PyJson`, owned by lane canonical. Dumps compare it byte for byte.
- **`dump_fixture`'s exclusions were wrong.** It now dumps a fixed allow-list in foreign-key order, replays kv as
  upserts, and creates `phone_*` from `phone.sql`. A test checks the list against `sqlite_master`.
- **`_artist_as_written` and case-blind folders.** The respelling rule of §5.6 settles them, on both sides. It is
  §11, question 2.
- **The cookie reached any loopback port.** The WebView now loads only the server's exact origin, and downloads are
  read in-process.
- **The sync job's view was unspecified.** §5.3 fixes it. `--progress` was added to `peer take` and `peer sync`,
  and `job_views.jsonl` is generated. `jobs` now depends on sync-tab.
- **caracole serve wrote files of its own.** Choices now go on the command line, and peers' addresses live in kv
  written by the command. The two writes that remain are named in AGENTS.md and in §11, question 3. Push ids and
  shas are validated before any path is built, and staging is capped.
- **`api_search` vectors with progression and lacuerda_unlisted.** The generator patches those two off for its
  WebApp, so the recorded answers are the phone's.
- **Get it and Fetch now were refused.** On the phone, both add the song.
- **The connection and threading contract was missing.** It is §5.5. The index import is a job.
- **The asset order wasn't available at runtime.** It is now `data/caracole/page/library_assets.json`.
- **The index was never merged at a sync.** A sync's last stage is now `index`. The deferrals are recorded by
  integration.
- **Take didn't validate file names.** `Take.checkedName` does now, and paths are canonical under `libraryDir`.

**Major issues: executability**
- **The Kotlin lanes couldn't test until core-db.** The skeleton now writes a working `Database` and the
  migrations.
- **Lanes started early had no wait and resume.** §7.0 adds Phase A and Phase B, and each brief names its Phase A.
- **Some dependencies were wrong.** pinyin, fuzz and canonical no longer depend on py-unicode. The LaCuerda keys
  moved into keys, so song-names no longer needs search-lacuerda. Mirror gating is a skeleton interface.
  app-local's `/jobs.json` is neutral.
- **Stubs threw at runtime.** Every stub on Assembly's path is now neutral.
- **The emulator wasn't ready.** One serialized device step in integration runs every on-device test, and
  `e2e_library serve` starts its computer.
- **The machine would be overloaded.** At most 6 lanes run at once, with `-n 4` and 4 Gradle workers, and nobody
  runs `gradle --stop`.
- **No drift protocol.** §3 now has one.
- **peer-push was too big.** It was split into peer-format2, peer-push-routes and peer-sync-cli.
- **search-ug was too big.** search-query was split out as the seam.
- **IGNORECASE classes couldn't be built pair by pair.** They now come from `_sre.unicode_tolower` and
  `re._casefix`.
- **The skeleton committed on main.** Each lane now works in its own worktree and branch, and nothing touches the
  owner's files.

**Minor issues taken**
- `Corpus.open` is pluggable, and the androidTest assets are copied under `conformance/`.
- The rapidfuzz transcription and the spikes are committed, so no brief points at `/tmp`.
- `ForbiddenApiTest` is narrowed, and `Py.asciiLower` added.
- FakeComputer is in `:core`'s testFixtures, and `TestApp` in `:server`'s.
- `sync_routes.jsonl` and `job_views.jsonl` are generated.
- `vectors/library/*` hold add, remove, the lyrics files, stamps and `ensure_current_keys`;
  `LibraryStore.ensureCurrentKeys` is ported; KEY_VERSION is in the lockstep rule.
- `PeerClient` has 60 s and unbounded timeouts.
- A route `limit` on both sides, and 1 MiB for `/sync/apply`.
- core-db's backup condition, `phone_*` left out of the `sqlite_master` check, `PhoneSchema` in one transaction,
  and `SCHEMA_VERSION` asserted.
- Phase 2 counts requests, BundledSqliteTest on arm64 is in the real-phone list, and the pinyin vectors run on the
  device.
- Python's YouTube stub shape, `/request` and `/remove` stubbed in M2, a stub that a real module overrides,
  `/jobs/cancel` routed, and the details link set to `#tab=sync`.
- The backup is openable, and `Take.restore` puts it back.
- The test_web_app.py names list, the docstring line in app.py and the pyproject marker are owned.
- The export's DDL is in its fixture (`Fixtures.loadRaw`).
- e2e runs never count as up to date, and `--rerun` is passed.
- Stubbed `val`s use `get()`, and `MirrorPageData` takes a `Mirror?`.

**Declined, with the reason**
- **Translating FORMAT 1 bases at the bump.** That is a compatibility shim, which the owner rules out. The cost is
  stated in §4 and put to the owner as §11, question 4.
- **Splitting integration into a JVM step and a device step.** The JVM scenario became the lane `e2e-jvm`. The
  integration step is the device step plus the docs, since the output keeps a single integration step.
- **A capability map in `server` to hide out-of-round controls.** It isn't needed: refusals show on the line, and
  Get it now works.
