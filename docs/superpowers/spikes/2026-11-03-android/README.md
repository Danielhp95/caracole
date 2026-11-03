# The Android port's spikes (2026-11-03)

The Kotlin the plan's choices rest on ([2026-11-03-android-port-m1-m3.md](../../plans/2026-11-03-android-port-m1-m3.md),
§1's table), kept for reference: `.kt.txt`, so nothing builds them. They ran in a Gradle project of their own beside
android/, with the plugins android/ uses (AGP 8.13.2, Kotlin 2.2.21), JDK 17, on the JVM and in a throwaway APK on the
emulator.

## Sqlite.kt.txt: caracole's schema in the bundled SQLite

`androidx.sqlite:sqlite-bundled:2.7.1` (`BundledSQLiteDriver`), the SQLite `:core` uses.

- It is SQLite 3.50.1, source id `2025-06-06 14:52:32 b77dc5e0f596d2140d9ac682b2893ff65d3a4140aa86067a3efebe29dc914c95`,
  with 52 compile options, `ENABLE_FTS5`, `ENABLE_MATH_FUNCTIONS`, `THREADSAFE=2` and `MAX_VARIABLE_NUMBER=32766` among
  them. The Android ABIs carry the same source id and the same options.
- All 15 of db.py's migrations ran, 90 statements, each version in `BEGIN IMMEDIATE` … `PRAGMA user_version` …
  `COMMIT`, and the database's `sqlite_master` was the one Python makes.
- `prepare` and `execSQL` run the **first** statement of a text and silently ignore the rest ("SELECT 1; SELECT 2"
  answers 1; two CREATE TABLEs make one). Hence `migrations.json`'s statements one by one.
- Through caracole's triggers, `ug_index` rows fill `ug_keys`, `ug_artists`, `ug_index_fts` and `ug_key_words`. A
  trigram `LIKE` goes through `ug_keys_fts` (`SCAN ug_keys_fts VIRTUAL TABLE INDEX 0:L0`), and so does `GLOB`; a
  trigram `MATCH` of a phrase is refused (`detail!=full`), as it is in Python. unicode61 `MATCH` on `ug_artists_fts`
  and `ug_index_fts`, the `ug_artist_words` fts5vocab, the delete triggers and FTS5's `integrity-check` work.
- json1 (`json_each`, `json_remove`, `->>`), `RETURNING`, upserts, window and math functions, nested savepoints,
  `ATTACH` of a database Python wrote (and `DETACH`), `VACUUM INTO` and `quick_check` work. 40,000 bound parameters
  are refused ("too many SQL variables"): a list stays under 32,766.
- SQLite's own `lower()` and `upper()` fold ASCII alone (`lower('ÉLAN')` is `Élan`), so no text rule may lean on them.
- The full `jdk17` of nixpkgs links gtk3, which brings nixpkgs' libsqlite3 (3.53.3), and that library silently
  interposes the bundled library's `sqlite3_*` symbols: the program reported 3.53.3. With `jdk17_headless`, the only
  SQLite mapped (`/proc/self/maps`) is the bundled one's temporary copy, and it reports 3.50.1. Hence android/flake.nix's
  JDK, and a test that asserts `sqlite_source_id()`.

## Bench.kt.txt: an index's size through the triggers

200,000 `ug_index` rows of synthetic keys, in one transaction through the triggers, on the JVM: 1.9 s, making 270,001
`ug_keys`, 70,001 `ug_artists` and 15,119 `ug_key_words`, a 63 MB file; a trigram `LIKE` then found 39 keys in about
0.5 ms. UG's real index is about 1.4 million rows, so a whole import is tens of seconds on a phone: a job, never a
request's work.

## Http.kt.txt: the local server

Ktor 3.3.3's CIO engine against NanoHTTPD 2.3.1, each handing a request whole to one engine-neutral handler (the
shape `server.http.App.handle` takes).

- Ktor keeps the raw request target (`/Estopa/Tu%20calorro/a%2Fb%3F.html?q=caf%C3%A9&a=1` as sent) and every header,
  so caracole serve's strict unquoting and its checks port as they are. NanoHTTPD decodes `%2F` in the path before
  the handler sees it, so it is out.
- A form's body arrives whole, the cookie and the Host header as sent; an answer's headers (the policy, Referrer-Policy,
  nosniff) go out as given.
- Ktor CIO adds about 750 KB to the APK after R8, which needs `-dontwarn java.lang.management.ManagementFactory` and
  `RuntimeMXBean` (android/app/proguard-rules.pro).
