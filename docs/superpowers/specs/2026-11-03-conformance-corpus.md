# The conformance corpus

Status: the contract between caracole's Python suite and the Kotlin port of the Android app (plan:
[2026-11-03-android-port-m1-m3.md](../plans/2026-11-03-android-port-m1-m3.md), §3). The phone agrees with the
computer to the byte: every rule the Kotlin side ports, Python states as data here, and the Kotlin tests read it.
The helpers are `tests/helpers/corpus.py` (Python) and `android/core/src/testFixtures/…/core/testing/` (Kotlin:
`Corpus.kt`, `Fixtures.kt`, `TestDb.kt`); their tests are `tests/test_corpus_helpers.py` and `:core`'s.

## Who writes it

The Python suite writes every file under `tests/conformance/`.

- Each area has its own generator test, `tests/test_conformance_<area>.py`. The test builds the file's content in
  memory and calls `helpers.corpus.check(path, content)`.
- By default, `check` asserts that the committed file is byte-identical to the new content. A mismatch fails,
  naming the first differing line and the command that regenerates it. A missing file fails the same way.
- With `CARACOLE_CORPUS=write`, `check` writes the file instead:

      CARACOLE_CORPUS=write nix develop -c pytest -q -n 0 tests/test_conformance_*.py

- Generated files are never edited by hand. Any lane may regenerate any of them. A merge conflict in one is resolved
  by regenerating after the merge.

## JSONL vectors

`tests/conformance/vectors/<area>/<name>.jsonl`, in UTF-8 with `\n` line ends (`helpers.corpus.jsonl`).

- Line 1 is the header:
  `{"header":true,"corpus":"<area>/<name>","made_by":"tests/test_conformance_<area>.py","versions":{…}}`.
  `versions` holds `python`, `unicodedata`, `sqlite`, `pypinyin`, `rapidfuzz` and `caracole`
  (`helpers.corpus.versions()`). A nixpkgs bump therefore makes every file stale, and regenerating shows the Kotlin
  side what moved.
- Every later line is one record: `{"fn":"<python dotted name>","args":[…],"kw":{…},"out":…}`, or `"err":"<Python
  exception class>"` in place of `out`. A corpus may add other keys (`fixture`, `note`, `seed`).
- Every line is `json.dumps(rec, ensure_ascii=False, sort_keys=True, separators=(",", ":"))`.
- No string in a corpus holds a lone surrogate; generators leave U+D800–DFFF out of their inputs, and `jsonl`
  refuses one.
- Values map as follows (`helpers.corpus.plain`):
  - a tuple becomes an array;
  - a dataclass or NamedTuple becomes an object of its fields, recursively;
  - a `Song` becomes its `key`;
  - a set has no order and is refused: a generator sorts it first;
  - a float is written by Python's repr; Kotlin parses it as a `Double` and compares with `==`.

  Objects compare as maps, and arrays in order.

## Whole-file JSON vectors

`vectors/<area>/<name>.json` is one object, with the header's fields as its `header` member
(`helpers.corpus.json_document`: sorted keys, `ensure_ascii=False`, an indent of one, a final `\n`).

## Runtime data

`tests/conformance/data/caracole/<area>/…` is generated and checked the same way.

- It is a main resource root of `:core`, so the APK ships it, on the classpath as `caracole/<area>/…`.
- Its format is the producing lane's own, documented in the generator's docstring and in the Kotlin reader.
- Text formats are preferred. gzip is allowed only with `mtime=0`.
- Two files are hand-written, not generated:
  - `data/caracole/schema/phone.sql`, the phone's own DDL (the plan's §5.4), which `PhoneSchema` and
    `helpers.corpus.replay_fixture` both read;
  - `data/caracole/README.md`.
- `data/caracole/schema/migrations.json` (`tests/test_conformance_schema.py`) is
  `{"schema": db.SCHEMA_VERSION, "statements": {"1": [stmt, …], …}}`, each of db.py's migration scripts split into
  its statements with `sqlite3.complete_statement`; `core.db.Database` runs it.

## Fixtures

Fixtures are cross-lane and exact. `vectors/<area>/fixtures/<name>.jsonl` is a header, then lines in this order:

1. `{"sql":"<CREATE …>"}` lines. These appear only in a fixture of a file that is not a migrated caracole database,
   such as an index export, and create its tables (`dump_fixture(conn, raw=True)`).
2. `{"table":"<base table>","row":{<column>:<value>}}` lines, in the order of the fixed list below, then by rowid.
3. `{"kv":"<key>","value":"<text>"}` lines, by key.
4. `{"file":"<path under the library>","base64":"…"}` lines, by path.

How fixtures are written and replayed:

- `helpers.corpus.dump_fixture(conn, library_dir=None)` dumps exactly these base tables, parents first:
  `songs, versions, files, removed, events, ug_index, ug_artist_tabs, lacuerda_index, gtptabs_index,
  musescore_index, harptabs_index, harptabs_artists, harptabs_artist_tabs, gametabs_index, gametabs_games,
  gametabs_game_tabs`, then `phone_overrides, phone_songbooks` when they exist, then `kv` without `sync:id`
  unless the fixture pins it (`sync_id=True`).
- It never dumps a virtual table, an FTS shadow table (any table named `<virtual table>_…`) or a trigger-filled
  table (`ug_keys`, `ug_artists`, `ug_key_words`).
- `dump_fixture` refuses a database with a base table the list neither names nor excludes, and
  `test_corpus_helpers.py` fails when a migration adds one.
- Both sides replay into a freshly migrated database:
  - one plain `INSERT` per row in file order, so the triggers number derived rows alike;
  - kv lines as upserts;
  - `phone_*` tables created from `phone.sql` first, with kv `phone:schema`, as `PhoneSchema` makes them (Python's
    schema has none).

  Python's replay is `helpers.corpus.replay_fixture`; Kotlin's is `Fixtures.load`, or `Fixtures.loadRaw` into an
  empty file for `sql` fixtures.
- Python runs a corpus's queries against the replayed database, never the one it built first.
- `test_corpus_helpers.py` round-trips a library with `ug_index` rows, then passes `PRAGMA integrity_check` and each
  FTS table's `'integrity-check'`; it writes that library as `vectors/corpus/fixtures/library.jsonl`, which `:core`'s
  tests replay with `Fixtures.load`.

## Determinism

Generators iterate in a defined order. No output may depend on `PYTHONHASHSEED`: the search corpus runs its
generator twice in subprocesses, with `PYTHONHASHSEED=1` and `=2`, and asserts the outputs are equal.

## Size and speed

Each generator runs in under 3 s, or it is marked `slow`. Vectors stay under 20 MB in total.

## The Kotlin reader

`android/core/src/testFixtures/kotlin/io/github/danielhp95/caracole/core/testing/Corpus.kt`:

- `Corpus.records(name): List<Record>`, where
  `Record(fn: String, args: JsonArray, kw: JsonObject, out: JsonElement?, err: String?, extra: JsonObject)`; `name`
  is the path under `vectors/` (`"unicode/categories.jsonl"`).
- `Corpus.json(name)` reads a `.json` vector.
- `Corpus.open: (path: String) -> InputStream?` defaults to the directory in the system property
  `caracole.conformance`. Gradle sets it for every test task and declares the directory an input. An androidTest
  sets `Corpus.open` from the instrumentation's `AssetManager`.
- A missing file fails the test; it never skips.

## On the device

`CorpusOnDeviceTest` (the integration step) runs the `unicode`, `keys`, `pinyin`, `fuzz` and `canonical` vectors
under Android's runtime and its ICU-backed regex.

## The drift protocol

A corpus is a contract between a Python owner and Kotlin readers who may already have merged.

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
- After this round, the same holds for all work (AGENTS.md, "The phone agrees with the computer to the byte"): a
  change to normalize, search, peer_sync, the schema, library_assets, status.py or outcome.py regenerates the corpus
  in the same commit, and `nix develop ./android -c gradle -p android test` passes before it merges.
