# Syncing as one flow, with export and import: Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** One sync on each device (what to sync, a card for each conflict, a picture of what it did), written once in
library_assets and served by caracole serve and the phone alike, and a library exported to a `.caracole` file and
imported as a sync with that file.

**Architecture:** The flow lives once in library_assets (sync.js, sync-words.js, sync-sheet.html, sync-panel.html,
sync.css). caracole serve and the phone's server both serve it byte for byte, and they answer the same routes with
the same JSON, which the corpus holds. The sync's rules gain two things: a scope (the three parts) and the one new
rule, an import's remembered answer. A file is a zip of what a sync reads from the other side. A `UnitSource` reads
it, so the take doesn't change. The phone adds only a top-bar button, the WebView's file chooser and downloads, the
unattended sync's notification, and a layer of the mirror for a file's pages.

**Tech Stack:** Python 3.14 (typer, httpx, sqlite3, zipfile); vanilla JS, CSS and HTML in library_assets, tested in
Chromium through tests/helpers/browser.py; Kotlin (:core, :mirror, :server on the JVM; :app with WebView, WorkManager
and FileProvider); the conformance corpus (tests/conformance/).

**Spec:** [docs/superpowers/specs/2026-11-03-sync-redesign-design.md](../specs/2026-11-03-sync-redesign-design.md),
with its mockups `2026-11-03-sync-redesign/phone.html` and `laptop.html`. This plan joins the build of
[2026-11-03-android-port-m4-m6.md](2026-11-03-android-port-m4-m6.md). Its §7.0 (worktrees, Phase A and B, `--no-ff`
merges, drift, the shared machine, the emulator lock, docs owned by section, the common must-not-touch list) binds
every lane here.

## Global Constraints

- One entry point per device. **Phone:** a sync button in the app's top bar on every page (circular arrows, left of ⋮).
  It replaces Settings' Sync now, Settings' Import indexes (From the computer, From a file), and the ⋮ menu's Sync
  now and Sync with the computer, which all go. **Laptop:** the library page's Sync tab.
- Phone tabs stay unsplit, with no Sync tab. The laptop's tab bar splits: **Library**, **Songbooks** on the left;
  **Sites**, **Requests**, **Sync** on the right, in that order.
- The laptop's Sync tab has three panels side by side: **Sync with a server** (address remembered, **Test**, last
  sync, **Sync**), **Export**, **Import a file**.
- Settings keeps the address with **Test**, gains **Export** and **Import a file**, and keeps **Sync on Wi-Fi by
  itself**. **No item text ends in "…".**
- Three parts, **Library**, **Songbooks**, **Site indexes**, are all ticked for a sync. A song a songbook lists comes
  along with it even when Library isn't ticked. **Cancel** on the left, **Sync** on the right.
- Conflict card: the song's name, "1 of N", this device left and the other side right, each with its icon, showing
  how the two differ. It never says who changed what, or when: the mockups' "changed today, 18:40" lines go.
- Under "Which version to keep", the two buttons are **Phone** and **Computer** on the phone, **This computer** and
  the server's name on the laptop, and **File** for an import. Under them sits **Same for the other N**. There is no
  Skip: Cancel ends the sync with nothing taken or given.
- Above the card: green ↓ N to take, blue ↑ N to give, orange ⚠ N changed on both, and the chips Compared, Your
  choice, Library, Songbooks, Indexes.
- Summary: "Synced with: **<name>**" (the name in the accent colour, the only bold text) and the date as
  `dd/mm/yy, HH:MM`. Below, the two sides as icons (phone, computer tower, server or file; this device always left).
- The summary has one section per kind of change, each starting closed: green songs taken, blue songs given (with why),
  orange dashed conflicts (which side was kept), yellow songbooks, purple indexes (the net tabs on the arrow, each
  site's before → after and when read; up in green, down in red). **Done** closes it.
- Export: "Export this library", the name, the songs and the date. Library and Songbooks start ticked, **Site indexes
  starts unticked**, and each part shows its size. Cancel left, Export right.
- The file is `<library name>-dd-mm-yy.caracole`: the browser downloads it, and the phone hands it to Android's share
  sheet.
- Import: "Sync with a file from **<its library's name>**", when it was exported, and the parts, where a part the file
  doesn't hold is greyed "Not in this file". The file takes nothing back, so no arrow goes out.
- An import records the agreement with the file's caracole by its id. A conflict answered "keep mine" in an import is
  remembered: the base keeps the two versions chosen between.
- Refused: a file older than the last sync with its caracole ("Nothing in this file is newer than your sync with
  horde_logbook on 03/11/26"), and a library's own export.
- Sync on Wi-Fi by itself: every 6 hours on an unmetered network, when the computer answers, the three parts ticked.
  It takes and gives every one-sided change, leaves each conflict, and notifies ("2 songs changed on both sides: tap
  to choose").
- CLI: `caracole peer export FILE`, `caracole peer import FILE`. `peer diff`, `pull` and `sync` keep working.
- AGENTS.md's page rules hold: no network, every inline script and style by its hash, `createElement` and
  `textContent`, never `innerHTML`.
- library_assets is inlined byte for byte and copied byte for byte to the phone (`copyLibraryAssets`). A
  library_assets change regenerates the corpus in the same commit, and `nix develop ./android -c gradle -p android
  test` passes before it merges.
- Every write passes the cross-origin check and carries the form token. Every `json` and `bytes` route declares its
  limit.
- caracole serve never takes caracole's lock, and AGENTS.md lists each new file serve writes: the export's temporary
  file in `cache_dir/peer/`, deleted once sent, and the import's staging folder `state_dir/peer/import-<16 hex>/`.
- Phone: the launch cookie and the security rules hold, and the WebView gets no JavaScript bridge.
- `upsert_song` stays the one way a song is added, a removed song stays removed, schema changes go through db.py, and
  an import takes its units exactly as a pull or a push does.
- Nothing in an export or an import is sent to a music site, and a page loads nothing from the network.
- The owner's choice "ignore the privacy, share everything" (2026-11-03) goes into AGENTS.md beside the harptabs.com,
  gametabs.net and AZLyrics terms.
- No Claude or AI attribution anywhere. Never run `omnibin-shell`. Never start a `caracole serve` on 8737. No live
  request to a music site.

## Review Focus

1. **A part left out is never read as a removal.** A Songbooks-only file or sync, or Library unticked, must leave every
   song it doesn't hold as it is. Pinned by Task 2 (`in_scope` with `holds`), Task 7
   (`test_a_songbooks_only_file_removes_no_song_it_doesnt_hold`) and Task 13 (the Kotlin twin).
2. **A file cut short, corrupt, oversized, or naming a path outside its layout is refused whole, before anything is
   taken.** This covers a zip with `../`, a CRC error, a blob over 64 MiB, a part sent out of order, and an upload
   that stops halfway. Pinned by Tasks 5, 6, 11, 21 and 33.
3. **The same file imported twice, a library's own export, or a file older than the last sync with its caracole is
   refused in the owner's words, with nothing changed.** Pinned by Tasks 5, 7 and 13.
4. **The unattended sync never settles a conflict, and does nothing and says nothing when no caracole answers** (a
   Wi-Fi login page, say). Pinned by Task 12 (`Conflicts.LEAVE`), Task 18 (`SyncRoutes.alone`) and Task 38 (the
   worker's probe and the notification only for conflicts left).
5. **Cancel at any step before Sync queues nothing, and a sync already on its way is followed, never started
   again.** This holds when the page loads (a reload, or the notification's tap) and when a second tab opens. Pinned
   by Task 27 (`test_cancel_on_a_card_queues_nothing`) and Task 28 (`test_a_sync_on_its_way_as_the_page_loads_is_followed_to_its_summary`).

---

## 1. How the lanes slot into milestones 4–6

Eight lanes, each a branch made from main in `.claude/worktrees/<id>`, merged `--no-ff` once its done_when holds with
main merged in. A lane whose producers haven't merged may do a Phase A against this plan's contracts (§3) and report
`waiting on: <lanes>`.

| Lane | Branch | Side | Depends on (sync; M4–6) | Device | ~Lines | Tasks |
|---|---|---|---|---|---|---|
| sync-rules | android/sync-rules | python | –; crossing-computer | no | 1000 | 1–3 |
| sync-file | android/sync-file | python | sync-rules; crossing-computer | no | 2600 | 4–9 |
| sync-core | android/sync-core | kotlin | sync-rules, sync-file; index-push, songbook-writers, device-replays | yes | 2900 | 10–14 |
| sync-routes | android/sync-routes | mixed | sync-core; index-push, requests-tab, device-replays | yes | 2700 | 15–19 |
| sync-exchange | android/sync-exchange | python | sync-file, sync-routes; index-push, requests-tab | no | 2500 | 20–24 |
| sync-page | android/sync-page | mixed | sync-routes, sync-exchange; requests-tab | yes | 2900 | 25–30 |
| sync-phone | android/sync-phone | kotlin | sync-core, sync-routes, sync-exchange; lookup-routes, device-replays | yes | 2300 | 31–34 |
| sync-app | android/sync-app | kotlin | sync-phone, sync-page; lookup-routes | yes | 1700 | 35–39 |

```
crossing-computer ─ sync-rules ─ sync-file ─┬──────────────────────────────┐
index-push, songbook-writers, device-replays ┴─ sync-core ─ sync-routes ─ sync-exchange ─ sync-page ─┐
requests-tab ────────────────────────────────────────────┘                                          ├─ sync-app
lookup-routes ─────────────────────────────────────────────────────────── sync-phone ───────────────┘
                                                                              └─ library-cards (M5) after it
```

**Files shared with M4–6 lanes, in turn (first → then):**

| File | Order |
|---|---|
| `src/caracole/peer_sync.py` | crossing-computer → sync-rules → sync-exchange |
| `src/caracole/commands/peer.py`, `tests/test_commands_peer.py` | crossing-computer → sync-file → sync-exchange |
| `src/caracole/web/peer_routes.py`, `tests/test_web_peer.py` | crossing-computer → index-push → sync-exchange |
| `src/caracole/index_transfer.py` (`tab_counts` alone) | index-push → sync-routes |
| `src/caracole/web/status.py` (`PEER_KINDS` alone) | requests-tab → sync-exchange |
| `tests/test_conformance_sync_routes.py` (its job-view half) | requests-tab → sync-routes |
| `tests/test_conformance_library_page.py`, `vectors/web/library_page*`, `data/caracole/page/*`, `LibraryPage.kt`, `LibraryPageTest.kt` (their sync lines) | requests-tab → sync-page |
| `core/sync/SyncEngine.kt`, `PeerClient.kt`, `SyncEngineTest.kt`, testFixtures `sync/FakeComputer.kt` | crossing-phone → index-push → sync-core |
| testFixtures `core/testing/replays/SyncReplay.kt` | device-replays → sync-core |
| testFixtures `server/testing/replays/WebReplay.kt`, `SyncRoutesVectorsTest.kt` | device-replays → sync-routes → sync-phone |
| `server/page/MirrorPageData.kt`, `MirrorPageDataTest.kt` | lookup-routes → sync-phone → library-cards |
| `server/Assembly.kt`, `AssemblyTest.kt` | the M4 skeleton → sync-phone (named here, as §5.3 of the M4–6 plan allows) |
| `app/.../MainActivity.kt`, `SettingsActivity.kt`, `activity_settings.xml` | the M4 skeleton (its hooks, the Backups row) → sync-app |
| `app/src/main/res/values/strings.xml` (the sync strings alone) | any lane; sync-app edits only its own lines |

**What the M4–6 plan's reviser changes to take these lanes:**
- §1's "Not built in this round: the sync flow's redesign" becomes built by these lanes (this plan).
- library-cards' depends_on gains `sync-phone` (MirrorPageData.kt in turn). phone-render's "no mirror page serves it
  at its unit's digest" reads `Mirror.pageFor`, which sync-phone makes layer-aware (a file's pages count as served).
- crossing-phone and index-push keep "no stage is added". sync-core adds none on a network sync either (its import
  has stages of its own, §3.5).
- §9's device runs list `SyncSheetTest` and `ExportImportTest` in place of `SyncTabTest`.
- `tests/conformance/budget.json`: the `sync` area gains about 120 KB (kept.jsonl, scope.jsonl, file.jsonl, three
  small `.caracole` fixtures), and `web` about 60 KB (sync_routes.jsonl, sync_file_routes.jsonl). A lane that passes
  its area's budget says so in its report. It never edits budget.json.

---

## 2. File structure

**Python (src/caracole/)**
- `peer_sync.py`: unchanged rules, plus the remembered answer (`kept_of`, `record_kept`, `merged_kept`, `compare(...,
  kept=)`), the parts (`part_of`, `listed_songs`, `in_scope`), `change_of` and `names_of`, and later `Peer.index` and
  `Peer.indexes`.
- `peer_file.py` (new): the `.caracole` file, written (`export_file`), read (`read_file`, `SyncFile`), refused
  (`check_importable`), taken from (`FileSource`, a `UnitSource`).
- `peer_import.py` (new): an upload staged in `state_dir/peer/import-<id>/`, part by part, and later `Uploader`, which
  sends a file to another caracole serve's import routes.
- `commands/peer.py`: `peer export`, `peer import`, `peer sync --parts`, the index stage and the report event.
- `web/sync_routes.py`: the network sync's routes (§3.4.1).
- `web/sync_file_routes.py` (new): the export's and the import's routes (§3.4.2).
- `web/offline_routes.py`: `manifest_of(app)` and `library_pages(cfg)`, the pages a file holds.
- `web/jobs.py`: `Job.report`, the `report` event, the index stage and the import's stages.
- `web/jobs_routes.py`: `peer_outcome`'s report.
- `web/status.py`: `peer import` is a sync.
- `index_transfer.py`: `tab_counts`.
- `library_page.py`: `WebControls.sync` is `"tab"`, `"sheet"` or None, plus the template lists.
- `library_assets/`: `sync-sheet.html` (new; the dialog, both devices), `sync-panel.html` (the laptop's three
  panels), `sync-tab.html`, `sync-words.js` (new; differences, changes and numbers in words), `sync.js` (the flow),
  `sync.css`, `body.html` (the tab order), and `tabs.js` and `__init__.py` (their words).

**Kotlin (android/)**
- `core/sync/Compare.kt` (the remembered answer), `core/sync/Scope.kt` (new; parts, listed songs, changes, names),
  `core/sync/PeerClient.kt` (`PeerState.kept`, `indexes()`), `core/sync/SyncEngine.kt` (parts, `Conflicts`, an
  import, the report).
- `core/sync/file/` (new): `SyncFiles.kt` (write, read, name, sizes), `SyncFile.kt`, `FileSource.kt`, `Zip.kt`
  (checked reading). `core/index/TabCounts.kt` (new).
- `mirror/Layers.kt` (new) and `mirror/Mirror.kt` (`pageFor` layer-aware): a file's pages beside the computer's.
- `server/routes/SyncRoutes.kt`, `routes/library/SyncJson.kt` (the network routes, `alone`, `tested`),
  `server/routes/SyncFileRoutes.kt` (new), `server/routes/sync/Imports.kt` and `Exports.kt` (new; staging, export
  files), `server/page/MirrorPageData.kt` (a layer's cards), `server/page/LibraryPage.kt` (the sheet, no tab),
  `server/Assembly.kt` (wiring).
- `app/`: `MainActivity.kt` (bar button, sheet intents, file chooser, downloads), `SheetAddress.kt`, `FileChooser.kt`
  and `Exports.kt` (new), `SettingsActivity.kt`, `Syncs.kt` (the unattended sync), `Notifications.kt` (new; moved out of
  `IndexImports.kt`, which goes), `res/` (layout, menu, strings, `drawable/ic_sync.xml`, `xml/file_paths.xml`).

---

## 3. Shared contracts

Every lane codes against these. A task's Interfaces block names the sections it consumes.

### 3.1 The base and the remembered answer (Python and Kotlin alike, held by `vectors/sync/kept.jsonl`)

kv `sync:base:<peer id>` keeps a second member:

```json
{"format": 2,
 "units": {"song/eagles/hotel california": ["<digest>|null", "2026-11-03T18:40:00Z"]},
 "kept":  {"song/eagles/hotel california": ["<digest here, kept>|null", "<digest there, not taken>|null", "2026-11-03T21:10:00Z"]}}
```

- **`record_kept(conn, peer, chosen, at) -> int`**: written by an import alone. `chosen` holds `{unit: (here's
  digest, the file's digest)}` for each conflict answered "keep mine", and `at` is the file's `made`.
- **`record_agreement`**: keeps `"kept"` and deletes the entry of every unit it records as agreed.
- **The state document's `"kept"` member**: the answering side's entries for the asker, as stored, so `here` is the
  answering side's. `read_state_document` reads it into `PeerState.kept`, leaving odd entries out.
- **`merged_kept(mine, mine_kept, theirs, theirs_kept) -> dict[str, KeptPair]`**: for each unit, the latest of the
  four records by `when` (ISO 8601, so the latest sorts last). On a tie, an agreement wins. A unit whose latest record
  is a kept one comes back as `KeptPair`, `(was_here, was_there, chooser)`:
  - mine's as stored, with chooser `"mine"`;
  - theirs' swapped (`(entry[1], entry[0])`), with chooser `"theirs"`.
- **`compare(mine, theirs, base, kept=None)`**: for a unit in `kept`, `here_changed = mine digest != was_here` and
  `there_changed = theirs digest != was_there`.
  - Neither changed, and they differ: proposal `MINE` with why `KEPT_HERE` when the chooser is `"mine"`, else
    `THEIRS` with why `KEPT_THERE`.
  - One changed: that side's, in the usual words (`_changed`).
  - Both changed: `CONFLICT`.
  - A unit in `kept` that the two hold alike is no difference.
- **Words:** `KEPT_HERE = "kept here, as you chose when a file of the other's was imported"` and `KEPT_THERE = "kept
  there, as you chose when a file of this one's was imported"`.

### 3.2 Parts and scope (held by `vectors/sync/scope.jsonl`)

- `PARTS = ("library", "songbooks", "indexes")`. `part_of(unit_id)`: `song`, `removed`, `alias`, `artist_url`,
  `block` are `"library"`, `songbook` is `"songbooks"`, anything else None.
- `listed_songs(books, units) -> dict[str, list[str]]`: `books` are songbook values, `{"name", "songs": [[text,
  parts], …]}`, of either side, by unit id. For each entry text and each key of `songbook.entry_keys(text)` where
  `"song/<key>"` is in `units`, that song unit maps to the songbook units listing it (sorted, unique).
- `in_scope(found, parts, *, listed=None, holds=None)`:
  - keeps `d` when `part_of(d.id)` is in `parts`, or when it is a song unit, `"songbooks"` is in `parts` and `d.id`
    is in `listed`;
  - with `holds` (a file's parts), then drops `d` when `part_of(d.id)` isn't in `holds` and `d.theirs is None`:
    a unit a partial file lacks is never a removal.
- `change_of(d, base, kept=None) -> (here, there)`: each side's change since the base, `"new"`, `"changed"`, `"gone"`
  or None.
  - With a base (or a `KeptPair`): a side unchanged is None; one that was None is `"new"`; one now None is `"gone"`;
    anything else `"changed"`.
  - With no base: a unit on one side alone is `"new"` on that side and None on the other; on both, `("changed",
    "changed")`.
- `names_of(unit_id, label) -> (artist, title) | None`: for a song unit, the cut of `label` at `" - "` whose
  `normalize.identity_key(artist, title)` is the unit's key; else the first cut. None for other kinds.

### 3.3 The `.caracole` file (format 1; held by `vectors/sync/file.jsonl`)

A zip. Member names, in this order:

| Member | What |
|---|---|
| `caracole.json` | `{"format": 1, "caracole": "<version>", "schema": <db.SCHEMA_VERSION>, "sync": 2, "id": "<16 hex>", "name": "<library name>", "made": "<stamp>", "parts": [...], "songs": n, "songbooks": n, "units": n, "files": n, "pages": n, "indexes": ["ug", …]}` |
| `state.json` | `peer_sync.state_document(id, version, name, units, None, now=made, indexes=newest or {}, kept={})`: the units of the file (§3.2: Library's kinds whole when ticked; songbooks when ticked, with the songs they list); `newest` is `index_transfer.newest` of the `indexes.sqlite` it holds |
| `bases.json` | `{"<peer id>": {"units": …, "kept": …}}`: every base this side keeps (kv `sync:base:*`) |
| `units.jsonl` | a line per unit of `state.json`, in `peer_sync._order`: `peer_sync.unit_document(...)` |
| `files/<sha256>` | each kept file the song documents name, once |
| `pages.json` | the exporter's `GET /api/offline` manifest (format 1), `files` cut to the file's units and its start page; absent without Library |
| `pages/<sha256>` | each page's bytes, once; none for a page whose bytes are a kept file's, held under `files/` (a page is read from `pages/`, else `files/`) |
| `indexes.sqlite` | `index_transfer.export` of every site, when `"indexes"` is in parts |

- JSON members are `ZIP_DEFLATED`, the others `ZIP_STORED`. Every member's date is the manifest's `made`. The file is
  written to `.<name>.<12 hex>.part` beside it, then renamed.
- A song with a kept file that can no longer be read as recorded (`peer_sync.song_file` gives None), or past
  `FILE_MAX`, is left out with its pages, and said (`Made.left`: `(unit, why)`, `CHANGED` or `TOO_BIG`).
- **Reading:** `caracole.json` comes first. Every name is in the layout: `files/` and `pages/` names are 64
  lowercase hex, and nothing else is allowed. Each blob is at most `FILE_MAX` (64 MiB), each JSON member at most
  64 MiB, and the declared sizes sum to at most `IMPORT_MAX` (8 GiB). A blob's SHA-256 is checked as it is read, and
  a CRC error or truncated member is `UNREADABLE`.
- `"indexes"` counts as held only when the manifest's `schema` is this database's.
- An index export (an SQLite file holding `index_transfer.META`) is a file of parts `("indexes",)` alone, with no id.
  Its name is the file's own name.
- Refusals, exact copy, the same words on both sides (`peer_file`, `core.sync.file.FileError`):
  - `NOT_A_FILE = "That isn't a file caracole exported: a .caracole file, or an index from caracole index export."`
  - `OTHER_FORMAT = "That file was made by another version of caracole (format {format}): export it again with this one."`
  - `OWN_EXPORT = "That file is this library's own export: a library takes nothing from itself. caracole backup keeps copies of the computer's database to go back to."`
  - `OLDER = "Nothing in this file is newer than your sync with {name} on {day}."` (`day` is `dd/mm/yy` in the
    server's zone, under TZ=UTC in the vectors; "older" means `made` ≤ the latest `when` of this side's base for
    that id, its `kept` included)
  - `UNREADABLE = "That file can't be read whole ({why}): export it again."`
- File name: `file_name(name, when)` is download_names' cleaned stem (`_clean`, `_cut` to `MAX_BYTES`) of the
  library's name, or `caracole` for none, then `-dd-mm-yy` and `.caracole`. So `file_name("horde_logbook", 3 Nov 2026)
  == "horde_logbook-03-11-26.caracole"`.

### 3.4 The routes (both servers answer each with the same JSON)

#### 3.4.1 The network sync (web/sync_routes.py; server/routes/SyncRoutes.kt; `vectors/web/sync_routes.jsonl`)

| Route | Request | Answer |
|---|---|---|
| `GET /api/sync` | – | `{"server", "name", "device": "computer"\|"phone", "address", "peers", "songs": n, "songbooks": n}` |
| `POST /sync/test` | form: csrf, address | `{"peer": {address, server, caracole, name}, "songs": n, "songbooks": n, "indexes": "<newest stamp>"\|null, "synced_at": "<stamp>"\|null, "said": "<words>"}`; refusals as compare's |
| `POST /sync/compare` | form: csrf, address | as before (`comparison`, `peer`, `synced_before`, `differences`), plus the members below |
| `GET /api/sync/unit` | `?comparison=&id=` | `{"id", "here": <unit document>\|null, "there": <unit document>\|null}`; 409 GONE for a comparison not kept; 404 for a unit it didn't find |
| `GET /api/sync/indexes` | – | `{"indexes": {"<site>": {"read": "<stamp>"\|null, "tabs": n}}}`, every site of `index_transfer.SITES` |
| `POST /sync/apply` | form: csrf, comparison, choices, prefer, `parts` (commas; absent = all three) | as before, the job's view |

The new members of `POST /sync/compare`'s answer:
- `peer.kind`: `"server"` on the computer, `"computer"` on the phone.
- `peer.made`: null.
- `holds`: all three parts.
- each difference gains:
  - `names`: `{artist, title}` from `names_of`, null for other kinds;
  - `change`: `[here, there]` from `change_of`;
  - `part`: from `part_of`;
  - `with`: the songbook units that list it (`listed_songs`, from both sides' songbook documents).
- `songbooks`: `{"songbook/<k>": {"here": doc|null, "there": doc|null}}` for each songbook difference.
- `indexes`: `[{"site", "title", "here": stamp|null, "there": stamp|null, "newer": "here"|"there"}]` for each site
  whose newest read differs, in `SITES`' order.

The comparison is made with the kept answers (`merged_kept` of this side's and the state's `kept`), and its hash
(`compared_hash`) is of the differences unscoped. `apply` refuses a part it doesn't know (400 "Not a part", "parts
are library, songbooks or indexes, by commas.") and queues `caracole peer sync --push --yes --progress --parts=<P>
--compared=<H> --choose=… -- ADDRESS` (Python) or the phone's job (Kotlin).

What lane sync-routes settled beyond the table (both servers answer so, and the corpus holds it):
- `GET /api/sync/unit` is the page's script's alone: it asks the other caracole, so it needs the form token in the
  `X-Caracole-Form-Token` header, as a `json` route does (403 without). `GET /api/sync/indexes` is a plain `/api/` read,
  which the phone's `PeerClient.indexes` asks as a client.
- `GET /api/sync`'s `songbooks` is null on caracole serve while songbooks.toml can't be read (that stops the songbooks
  and nothing else); the phone's is always a count.
- `POST /sync/apply`'s `parts`: absent is all three; sent, it names at least one part (blank, or commas alone, is the
  400 of a part it doesn't know). caracole serve queues `--parts=<P>` (in `PARTS`' order) only when the form sends
  `parts`, so a Sync with none queues the command as before.
- `POST /sync/test`'s `indexes` is the newest of the state's reads that is a time (`stamps.parse`), as the state
  writes it; one that isn't a time is left out.
- caracole serve's `Compared` keeps the differences (`found`) for a Sync's scope; one kept without them has every
  conflict it proposes chosen first, whatever the parts, and `GET /api/sync/unit` answers a comparison of a peer
  alone (another `source`, a file's, 409).

`said` words (exact):
- `"{name} answered: {songs} songs, {songbooks} songbooks, its indexes read {day}"`, singular "1 song" and
  "1 songbook";
- `", no indexes"` in place of the last part when its state names none;
- `name` is the state's name, else the address; `day` is `dd/mm/yy` in the server's zone.

#### 3.4.2 Export and import (web/sync_file_routes.py; server/routes/SyncFileRoutes.kt; `vectors/web/sync_file_routes.jsonl`)

| Route | Request | Answer |
|---|---|---|
| `GET /api/sync/sizes` | – | `{"name", "songs", "songbooks", "made": "<stamp>", "library": <bytes>, "indexes": <bytes>\|null, "tabs": n}` |
| `POST /sync/export` | json `{"parts": [...]}`, token, ≤ 4 KiB | `{"export": "<16 hex>", "name": "<file name>", "size": n}`; made in `cache_dir/peer/export-<id>.caracole` (0600), one at a time (503 "Another export is being made: try again once it is."); its parts must include library or songbooks (400) |
| `GET /api/sync/export` | `?export=` | the file, `Content-Type: application/vnd.caracole+zip`, `Content-Disposition` as `download_names.content_disposition(name)`, streamed; deleted once open; 404 after, and an hour after if never asked |
| `POST /sync/import/open` | json `{"size": n, "name": "<file name>"}`, token, ≤ 4 KiB | `{"import": "<16 hex>", "part": 8388608}`; 413 over 8 GiB; 409 with one open already |
| `POST /sync/import/part` | `?import=&at=` bytes, token, ≤ 8 MiB | `{"have": n}`; 400 for a part not at the end of what it has or past the size |
| `POST /sync/import/compare` | form: csrf, import | the comparison as `POST /sync/compare`'s, with `peer.kind` `"file"`, `peer.address` null, `peer.made` the manifest's `made`, `holds` the file's parts; or `{"error"}`: 400 `NOT_A_FILE` / `OTHER_FORMAT` / `UNREADABLE`, 409 `OWN_EXPORT` / `OLDER` |

- `POST /sync/apply` on an import's comparison queues `caracole peer import --yes --progress --parts=<P>
  --compared=<H> --choose=… -- <staging folder>` (Python) or the phone's import job (Kotlin), under the key
  `import:<file id>`.
- Its job is of kind `"sync"`, displayed `"Sync with a file from <name>"`.
- A file's comparison holds the differences within its `holds` (`in_scope(found, holds, listed=…, holds=holds)`), and
  its hash is of those.
- The staging folder is deleted once the job ends, or an hour after its last part if never applied.

### 3.5 The sync job's stages and report

- Python stages: `peer sync`'s are compare, take, give, agree, index. `PEER_SYNC_STAGES` gains `("index", "Bringing
  the indexes up to date")`. `peer import`'s are `PEER_IMPORT_STAGES = (("check", "Reading the file"), ("take",
  "Taking what changed there"), ("render", "Rendering what was taken"), ("agree", "What the two agree on"),
  ("index", "Merging the indexes"))`.
- The phone's network sync keeps its six stages. Its import's are `FILE_STAGES = check, take, mirror ("Keeping the
  file's pages"), agree, index`, the chips' names in outcome.py's `PEER_STEPS`.
- At its end a sync or an import says, with `--progress`, `{"event": "report", "report": R}`. The phone's job puts R
  in its outcome.

```json
{"with": {"name": "studio", "kind": "server|computer|file", "address": "http://…|null"},
 "at": "<stamp>", "parts": ["library", "songbooks", "indexes"],
 "indexes": [{"site": "ug", "title": "Ultimate Guitar", "direction": "taken|given",
              "before": 1503236, "after": 1515576, "read": "<stamp>"}]}
```

- `before` and `after` are the rows of the site's first table (`index_transfer.SITES[site].tables[0]`). For a taken
  site they come from this side, around its merge. For a given site they come from the other side's `GET
  /api/sync/indexes`, before the give and after its merge job ends.
- `jobs.Job.report` is in memory alone (never in `as_json` or the history).
- `jobs_routes.peer_outcome` adds `"report"` only when there is one, so the views of jobs without one are unchanged.

### 3.6 The page's addresses and the phone's hooks

- `#sheet=sync`, `#sheet=export` and `#sheet=import` open the sheet at that flow, and sync.js takes the word out of
  the address once it opens (`history.replaceState`). On a page with no Sync tab, `#tab=sync` is `#sheet=sync`, so
  outcome.py's Compare again keeps working on the phone.
- `WebControls.sync` (Python) is `"tab"` on caracole serve: the tab, the panel and the sheet.
  `ServerControls.sync` (Kotlin) true means the sheet alone, as Python's `"sheet"`.
- The phone has no JavaScript bridge:
  - the bar's button loads `<library page>#sheet=sync`;
  - Settings' Export and Import a file start MainActivity with the extra `sheet` (`"export"`, `"import"`), which
    loads that address;
  - the notification's tap does the same with `"sync"`.
- The page's file input (`#sync-file`, `accept=".caracole,.sqlite"`) reaches Android's picker through
  `WebChromeClient.onShowFileChooser`.
- The page's download link to `/api/sync/export?export=` reaches the share sheet through the WebView's
  `DownloadListener`.

### 3.7 Words the page draws (sync-words.js; exact copy the Chromium tests pin)

- **Sides:**
  - this device is `"Phone"` and `"On the phone"` (device phone), or `"This computer"` and `"On this computer"`;
  - the other is `"Computer"` and `"On the computer"` (kind computer), `"<peer name or address>"` and `"On <name>"`
    (kind server), or `"File"` and `"In the file"`;
  - in sentences: "the phone", "this computer", "the computer", "<name>", "the file".
- **Parts:**
  - `"Library"`: "Your songs, their sheets and pages, both ways"; a file's: "Its songs, sheets and pages · it takes
    nothing back";
  - `"Songbooks"`: "Your songbooks and their set lists, both ways"; a file's: "N songbooks";
  - `"Site indexes"`: "For searching offline";
  - what's waiting is added after `" · "`: "N changed on the computer" (counted in the part), "newer on the computer:
    Ultimate Guitar (read today)" (the first site, "and N more");
  - a part the file doesn't hold: unticked, disabled, "Not in this file".
- **Counts:** "N to take", "N to give", "N changed on both". **Chips:** "Compared", "Your choice", "Library",
  "Songbooks", "Indexes".
- **Card:**
  - the label: a song's "<artist> · <title>" (`names`), else its label;
  - "1 of N";
  - each side's lines, one per aspect the two documents hold differently (`differ`, below);
  - "Which version to keep", the two side buttons, "Same for the other N".
- **`differ(kind, here, there) -> [{what, here, there}]`:** each value is text, "–" for none.

| Kind | What and value |
|---|---|
| song | "Its own key": `overrides.version` (`key=Am&capo=2` → "A minor, capo 2"; `mode=` names it, "G minor (dorian), capo 0"; none → "as the sheet's") |
| song | "Its sheet": the version of the lowest `pick_rank` → "<provider title> · tab <tab_id>" (provider titles from the page's `data.icons`, else the provider) |
| song | "Its versions": their count, then "Its kept files": names, then "Its lyrics": `lyrics_status`, then "Its status": status and "in review" |
| song | "Its album", "Its length" (`m:ss`), "Its variant"; any other `overrides` table: "An override: [<table>]" ("set" / "–") |
| songbook | "Its set list": "N songs"; then "Songs added": the entries one has the other lacks, both ways; "Its order", when the same entries in another order; "A song's setting": an entry whose parts differ |
| removed | "Removed" on the side with the tombstone, "Kept" on the other |
| alias, artist_url, block | "Its slugs" / "Its UG page" / "Blocked": the values |

- **Summary:**
  - the title: "Synced with:" and the name; "dd/mm/yy, HH:MM" (local time);
  - green: "N songs taken" ("1 song taken"), rows "<title> – <artist>";
  - blue: "N songs given", rows with "added on <this side>" / "changed on <this side>" / "removed on <this side>" by
    `change[0]`;
  - orange dashed: "N conflicts · <side>'s kept" ("1 conflict · phone's kept"; "mixed" when both sides were kept),
    rows "<title> – <artist>" and "<the phone's | this computer's | <name>'s | the file's> version kept: <the kept
    side's differ lines, lowercased first letters, by ", ">";
  - yellow: "N songbooks taken" / "given" / "taken or given", rows: name, then "N songs added" / "N songs taken out" /
    "its order changed" / "a song's setting changed" / "N songs" for a new one;
  - purple: "N indexes taken · +12,130 tabs" (given: "given", "for <name>"), rows "Ultimate Guitar · +12,340 tabs",
    and under each "1,503,236 → 1,515,576 tabs tracked · read by <the reader side> on dd/mm/yy". A fall says
    "· its listings no longer name them, so they would not have opened". Up is green, down red, each with its sign;
  - numbers: digits grouped by "," in threes, written by hand (no locale);
  - a file: 'A file takes nothing back: no "given" arrow. To give your changes, export a file of your own.';
  - "Done".
- **Export sheet:**
  - "Export this library", then "<name> · N songs · dd/mm/yy";
  - Library "Your songs, their sheets and pages · 34 MB", Songbooks "N songbooks", Site indexes "For searching offline
    · 207 MB" ("· 1,515,576 tabs" when the size is null);
  - "Cancel", "Export"; while it is made, "Making the file…" (a status line, not an item).
- **Import sheet:**
  - before a file: "Import a file", "A file a phone or a server exported, synced as if its caracole were here",
    "Choose a file";
  - while it is sent: "Sending the file: N of M MB".

---

## 4. Lane sync-rules (python): the remembered answer and the parts

Branch `android/sync-rules`, worktree `.claude/worktrees/sync-rules`. Depends on crossing-computer (`peer_sync.py` in
turn). Python alone: no Kotlin test reads these vectors until sync-core.

### Task 1: The remembered answer in the base

**Files:**
- Modify: `src/caracole/peer_sync.py` (`record_agreement`, `compare`, `state_document`, `read_state_document`,
  `PeerState`; new `Kept`, `KeptPair`, `KEPT_HERE`, `KEPT_THERE`, `kept_of`, `record_kept`, `merged_kept`)
- Test: `tests/test_peer_sync_kept.py`

**Interfaces:**
- Consumes: the existing `base_of`, `merged_base`, `record_agreement`, `compare`, `Unit`, `Difference`.
- Produces (§3.1):
  - `Kept = dict[str, tuple[str | None, str | None, str]]`;
  - `KeptPair = tuple[str | None, str | None, str]`;
  - `kept_of(conn, peer: str) -> Kept`;
  - `record_kept(conn, peer: str, chosen: Mapping[str, tuple[str | None, str | None]], at: str) -> int`;
  - `merged_kept(mine: Base | None, mine_kept: Mapping[str, tuple], theirs: Base | None, theirs_kept: Mapping[str, tuple]) -> dict[str, KeptPair]`;
  - `compare(mine, theirs, base, kept: Mapping[str, KeptPair] | None = None)`;
  - `state_document(..., kept: Mapping[str, tuple] | None = None)` (member `"kept"`, `{}` when None);
  - `PeerState.kept: Kept` (default `{}`).

- [ ] **Step 1: Write the failing tests**

```python
U = lambda i, d: sync.Unit(i, i, d)
PEER, T0, T1, T2 = "0f1e2d3c4b5a6978", "2026-11-03T10:00:00Z", "2026-11-03T11:00:00Z", "2026-11-03T12:00:00Z"

def test_a_kept_answer_is_kept_beside_the_base_and_read_back(conn):
    sync.record_agreement(conn, PEER, {"song/a": U("song/a", "a1")}, {"song/a": U("song/a", "a1")}, T0)
    assert sync.record_kept(conn, PEER, {"song/b": ("bh", "bt")}, T1) == 1
    assert sync.kept_of(conn, PEER) == {"song/b": ("bh", "bt", T1)}
    assert sync.base_of(conn, PEER) == {"song/a": ("a1", T0)}

def test_a_unit_kept_here_and_changed_on_neither_side_is_this_sides_not_a_conflict():
    [d] = sync.compare({"song/b": U("song/b", "bh")}, {"song/b": U("song/b", "bt")}, {},
                       kept={"song/b": ("bh", "bt", "mine")})
    assert (d.proposal, d.why) == (sync.MINE, sync.KEPT_HERE)

def test_a_change_after_a_kept_answer_is_compared_as_usual():
    kept = {"song/b": ("bh", "bt", "mine")}
    def proposal(h, t):
        return sync.compare({"song/b": U("song/b", h)}, {"song/b": U("song/b", t)}, {}, kept=kept)[0].proposal
    assert (proposal("bh2", "bt"), proposal("bh", "bt2"), proposal("bh2", "bt2")) == (sync.MINE, sync.THEIRS, sync.CONFLICT)

def test_the_other_sides_kept_answer_is_read_with_its_sides_swapped():
    merged = sync.merged_kept(None, {}, None, {"song/b": ("bt", "bh", T1)})
    assert merged == {"song/b": ("bh", "bt", "theirs")}
    [d] = sync.compare({"song/b": U("song/b", "bh")}, {"song/b": U("song/b", "bt")}, None, kept=merged)
    assert (d.proposal, d.why) == (sync.THEIRS, sync.KEPT_THERE)

def test_the_later_of_an_agreement_and_a_kept_answer_counts_and_a_tie_is_the_agreements():
    kept = {"song/b": ("bh", "bt", T1)}
    assert sync.merged_kept({"song/b": ("same", T2)}, kept, None, {}) == {}
    assert sync.merged_kept({"song/b": ("same", T1)}, kept, None, {}) == {}
    assert sync.merged_kept({"song/b": ("same", T0)}, kept, None, {}) == {"song/b": ("bh", "bt", "mine")}

def test_an_agreement_drops_the_kept_answer_of_each_unit_it_agrees_on_and_keeps_the_others(conn):
    sync.record_kept(conn, PEER, {"song/b": ("bh", "bt"), "song/c": ("ch", "ct")}, T1)
    sync.record_agreement(conn, PEER, {"song/b": U("song/b", "bt")}, {"song/b": U("song/b", "bt")}, T2)
    assert sync.kept_of(conn, PEER) == {"song/c": ("ch", "ct", T1)}

def test_the_state_document_carries_the_kept_answers_and_reads_them_back():
    doc = sync.state_document("a1b2c3d4e5f60718", "0.1.0", "Desk", {}, None, now=T2, kept={"song/b": ("bh", "bt", T1)})
    assert doc["kept"] == {"song/b": ["bh", "bt", T1]}
    assert sync.read_state_document(doc).kept == {"song/b": ("bh", "bt", T1)}
    assert sync.read_state_document({**doc, "kept": {"song/x": [1], "song/y": "z"}}).kept == {}
```

- [ ] **Step 2: Run them and see them fail**

Run: `nix develop -c pytest -q -n 0 tests/test_peer_sync_kept.py`
Expected: FAIL, `AttributeError: module 'caracole.peer_sync' has no attribute 'record_kept'`.

- [ ] **Step 3: Implement §3.1 in `src/caracole/peer_sync.py`**

`kept_of` reads `kv_get_json(conn, BASE_KEY + peer)["kept"]` with `_read_units`' care (odd entries out, any read
error `{}`). `record_agreement` and `record_kept` write one document holding both members. The module's docstring
gains a paragraph, **The remembered answer**, in its style.

- [ ] **Step 4: Run them and the module's tests**

Run: `nix develop -c pytest -q -n 0 tests/test_peer_sync_kept.py tests/test_peer_sync.py tests/test_commands_peer.py tests/test_conformance_sync.py tests/test_conformance_sync_routes.py`
Expected: PASS, the existing sync vectors unchanged in check mode (a peer_sync.py change moves no record of theirs).

- [ ] **Step 5: Commit**

```bash
git add src/caracole/peer_sync.py tests/test_peer_sync_kept.py
git commit -m "feat(peer): an import's 'keep mine' is remembered beside the base"
```

### Task 2: Parts, the songs songbooks list, each side's change and a song's names

**Files:**
- Modify: `src/caracole/peer_sync.py` (new `PARTS`, `part_of`, `listed_songs`, `in_scope`, `change_of`, `names_of`)
- Test: `tests/test_peer_sync_scope.py`

**Interfaces:**
- Consumes: `songbook.entry_keys`, `normalize.identity_key`, Task 1's `KeptPair`.
- Produces (§3.2): `PARTS: tuple[str, ...]`, `part_of(unit_id: str) -> str | None`, `listed_songs(books:
  Mapping[str, Mapping[str, Any]], units: Iterable[str]) -> dict[str, list[str]]`, `in_scope(found:
  Sequence[Difference], parts: Iterable[str], *, listed: Mapping[str, Sequence[str]] | None = None, holds:
  Iterable[str] | None = None) -> list[Difference]`, `change_of(d: Difference, base: Mapping[str, str | None] | None,
  kept: Mapping[str, KeptPair] | None = None) -> tuple[str | None, str | None]`, `names_of(unit_id: str, label: str)
  -> tuple[str, str] | None`.

- [ ] **Step 1: Write the failing tests**

```python
D = lambda i, mine="m", theirs="t": sync.Difference(i, i, mine and sync.Unit(i, i, mine), theirs and sync.Unit(i, i, theirs), sync.CONFLICT, "")
SONG, OTHER, BOOK = "song/eagles/hotel california", "song/pomme/mononoke", "songbook/campfire"

def test_library_alone_keeps_songs_removals_and_overrides_and_no_songbook():
    found = [D(SONG), D("removed/x/y"), D("alias/x"), D("block/7"), D(BOOK)]
    assert [d.id for d in sync.in_scope(found, ["library"])] == [SONG, "removed/x/y", "alias/x", "block/7"]

def test_songbooks_alone_bring_the_songs_they_list_and_no_other():
    found = [D(SONG), D(OTHER), D(BOOK)]
    kept = sync.in_scope(found, ["songbooks"], listed={SONG: [BOOK]})
    assert [d.id for d in kept] == [SONG, BOOK]

def test_a_file_that_holds_no_library_never_reads_a_song_it_lacks_as_removed():
    found = [D(SONG, theirs=None), D(OTHER), D(BOOK)]
    kept = sync.in_scope(found, ["songbooks"], listed={SONG: [BOOK], OTHER: [BOOK]}, holds=["songbooks"])
    assert [d.id for d in kept] == [OTHER, BOOK]

def test_a_songbooks_entry_lists_a_song_by_any_cut_of_its_name():
    key = normalize.identity_key("Earth - Wind", "Fire")
    books = {BOOK: {"name": "Campfire", "songs": [["Earth - Wind - Fire", {}]]}}
    assert sync.listed_songs(books, [f"song/{key}", OTHER]) == {f"song/{key}": [BOOK]}

def test_each_sides_change_is_new_changed_or_gone():
    assert sync.change_of(D(SONG, "m", None), {SONG: None}) == ("new", None)
    assert sync.change_of(D(SONG, None, "t"), {SONG: "m"}) == ("gone", "changed")
    assert sync.change_of(D(SONG, "m", "t"), None) == ("changed", "changed")
    assert sync.change_of(D(SONG, "m", None), None) == ("new", None)
    assert sync.change_of(D(SONG, "bh2", "bt"), {}, {SONG: ("bh", "bt", "mine")}) == ("changed", None)

def test_a_songs_names_come_from_the_cut_of_its_label_that_is_its_key():
    key = normalize.identity_key("Earth - Wind", "Fire")
    assert sync.names_of(f"song/{key}", "Earth - Wind - Fire") == ("Earth - Wind", "Fire")
    assert sync.names_of(SONG, "Eagles - Hotel California") == ("Eagles", "Hotel California")
    assert sync.names_of(BOOK, "the songbook Campfire") is None
```

- [ ] **Step 2: Run them and see them fail**

Run: `nix develop -c pytest -q -n 0 tests/test_peer_sync_scope.py`
Expected: FAIL, `no attribute 'in_scope'`.

- [ ] **Step 3: Implement §3.2 in `src/caracole/peer_sync.py`**

`songbook` and `normalize` are imported inside the functions (Heavy imports). `in_scope` keeps `found`'s order.

- [ ] **Step 4: Run them**

Run: `nix develop -c pytest -q -n 0 tests/test_peer_sync_scope.py tests/test_peer_sync.py tests/test_conformance_sync.py`
Expected: PASS, the existing sync vectors unchanged.

- [ ] **Step 5: Commit**

```bash
git add src/caracole/peer_sync.py tests/test_peer_sync_scope.py
git commit -m "feat(peer): a sync's parts, the songs songbooks list, each side's change"
```

### Task 3: The corpus of the rules, and AGENTS.md

**Files:**
- Create: `tests/test_conformance_sync_kept.py`, `tests/conformance/vectors/sync/kept.jsonl`,
  `tests/conformance/vectors/sync/scope.jsonl`
- Modify: `AGENTS.md` (`#### peer_sync.py`: two bullets, the remembered answer and the parts)

**Interfaces:**
- Consumes: Tasks 1–2; `helpers.corpus` (`jsonl`, `check`, `dump_fixture`, `replay_fixture`), `test_conformance_sync.Corpus` for fixtures.
- Produces:
  - `vectors/sync/kept.jsonl`, records `{fn, in, out}`:
    - `fn: "merged_kept"`, with `in: {mine, mine_kept, theirs, theirs_kept}` and `out` the map;
    - `fn: "compare"`, with `in: {mine, theirs, base, kept}` and `out` the differences as `[id, proposal, why]`;
    - `fn: "record_kept"` and `"record_agreement"`, with `in: {kv, peer, args}` and `out` the kv value after;
  - `vectors/sync/scope.jsonl`, records `fn` in `"in_scope"`, `"listed_songs"`, `"change_of"`, `"names_of"`, each
    over ten cases or more (names in other scripts from the keys corpus' `EDGES` for `names_of` and
    `listed_songs`).

- [ ] **Step 1: Write the generator with its two tests**, `test_kept_jsonl_is_what_the_rules_answer` and
  `test_scope_jsonl_is_what_the_rules_answer`, each `check(VECTORS / "sync" / "<name>.jsonl", jsonl(records(),
  corpus="sync", made_by=MADE_BY))`.

- [ ] **Step 2: Run it in check mode and see it fail**

Run: `nix develop -c pytest -q -n 0 tests/test_conformance_sync_kept.py`
Expected: FAIL (no vector file yet).

- [ ] **Step 3: Write the vectors**

Run: `CARACOLE_CORPUS=write nix develop -c pytest -q -n 0 tests/test_conformance_sync_kept.py`

- [ ] **Step 4: Run the gates**

Run:
```
nix develop -c pytest -q -n 0 tests/test_conformance_sync_kept.py
nix develop -c pytest -q tests/test_corpus_budget.py
nix develop -c pytest -q
nix develop ./android -c gradle -p android test
nix build .#checks.x86_64-linux.package
```
Expected: PASS each (the Kotlin side reads no new vector yet; its compare vectors are unchanged).

- [ ] **Step 5: Commit**

```bash
git add tests/test_conformance_sync_kept.py tests/conformance/vectors/sync/kept.jsonl tests/conformance/vectors/sync/scope.jsonl AGENTS.md
git commit -m "test(conformance): the remembered answer and a sync's parts, for the phone"
```

---

## 5. Lane sync-file (python): the file, its staging, `peer export` and `peer import`

Branch `android/sync-file`. Depends on sync-rules and crossing-computer.

### Task 4: A library written to a file

**Files:**
- Create: `src/caracole/peer_file.py`, `tests/test_peer_file.py`
- Modify: `src/caracole/web/offline_routes.py` (`manifest_of`, `library_pages`; `manifest()` calls `manifest_of`), `tests/test_web_offline.py` (one case)

**Interfaces:**
- Consumes: §3.2 `in_scope`, `listed_songs`; `peer_sync.library_state`, `unit_document`, `song_file`, `state_document`, `base_of`, `kept_of`; `index_transfer.export`, `newest`; `download_names._clean`, `_cut`, `MAX_BYTES`.
- Produces (§3.3):
  - `FORMAT = 1`, `SUFFIX = ".caracole"`, `MEDIA_TYPE = "application/vnd.caracole+zip"`;
  - the member names `MANIFEST`, `STATE`, `BASES`, `UNITS`, `PAGES`, `FILES = "files/"`, `PAGE_BLOBS = "pages/"`,
    `INDEXES`;
  - `FILE_MAX = 64 * 1024 * 1024`, `IMPORT_MAX = 8 * 1024 ** 3`;
  - `class FileError(ValueError)`;
  - `@dataclass(frozen=True) class Made: path: Path; parts: tuple[str, ...]; songs: int; songbooks: int; size: int;
    left: tuple[str, ...]`;
  - `Pages = tuple[Mapping[str, Any], Callable[[str], bytes]]` (the manifest, and an entry's bytes by its path);
  - `file_name(library_name: str | None, when: datetime) -> str`;
  - `export_file(conn, cfg, overrides, books, path: Path, parts: Sequence[str], *, now: datetime, version: str, name:
    str, pages: Pages | None = None) -> Made`;
  - `offline_routes.manifest_of(app: WebApp) -> dict[str, Any]` (Refused as `manifest` refuses);
  - `offline_routes.library_pages(cfg) -> Pages | None`: a WebApp made for reading alone, its queue never started,
    nothing written; None while the library page isn't as written.

- [ ] **Step 1: Write the failing tests** (a library from `tests/helpers` with two songs, a songbook listing one, a kept
  file each; `zipfile.ZipFile` to read the result)

```python
def test_an_export_holds_its_manifest_state_units_and_each_kept_file_once(conn, cfg, two_songs):
    made = peer_file.export_file(conn, cfg, ovr(cfg), books(cfg), tmp / "x.caracole", ["library", "songbooks"],
                                 now=NOW, version="0.1.0", name="Desk")
    z = zipfile.ZipFile(made.path)
    assert z.namelist()[0] == "caracole.json"
    manifest = json.loads(z.read("caracole.json"))
    assert (manifest["format"], manifest["sync"], manifest["parts"], manifest["songs"]) == (1, 2, ["library", "songbooks"], 2)
    state = sync.read_state_document(json.loads(z.read("state.json")))
    assert set(state.units) == set(sync.library_state(conn, ovr(cfg), books(cfg)))
    lines = [json.loads(l) for l in z.read("units.jsonl").splitlines()]
    assert [l["id"] for l in lines] == [u.id for u in sorted(state.units.values(), key=sync._order)]
    assert sorted(n for n in z.namelist() if n.startswith("files/")) == sorted(f"files/{s}" for s in kept_shas(conn))
    assert "indexes.sqlite" not in z.namelist() and made.left == ()

def test_songbooks_alone_bring_the_songs_they_list_and_their_files(...):   # units == the songbook and its one song
def test_indexes_come_only_when_asked_and_are_the_index_export(...):        # indexes.sqlite opens with caracole_export
def test_a_song_whose_kept_file_changed_on_disk_is_left_out_and_said(...):  # made.left == ("song/…",), no files/ of it
def test_every_base_this_side_keeps_goes_into_bases_json(...):              # two kv sync:base:* → two keys, "kept" kept
def test_a_files_pages_are_those_of_its_units_and_its_start_page(...):      # pages: two entries, one of a unit not exported → left out
def test_the_file_name_is_the_librarys_name_and_the_day():
    assert peer_file.file_name("horde_logbook", datetime(2026, 11, 3, 21, 10, tzinfo=UTC)) == "horde_logbook-03-11-26.caracole"
    assert peer_file.file_name("a/b: c?", NOW) == "a b c-03-11-26.caracole"   # download_names' cleaning
    assert peer_file.file_name(None, NOW) == "caracole-03-11-26.caracole"
```

In `tests/test_web_offline.py`: `test_manifest_of_is_what_get_api_offline_answers`.

- [ ] **Step 2: Run them and see them fail.** Run: `nix develop -c pytest -q -n 0 tests/test_peer_file.py tests/test_web_offline.py`. Expected: FAIL, `ModuleNotFoundError: caracole.peer_file`.

- [ ] **Step 3: Implement `export_file`, `file_name` and the two offline functions**

- **Reading:** the database is read in one read transaction (`BEGIN`, as `index_transfer.export` reads), which
  takes no lock.
- **Writing:** each blob goes through `zipfile.ZipFile.open(name, "w")` in chunks of 1 MiB, never whole in memory.
- **Parts:** given parts other than §3.2's raise FileError("parts are library, songbooks or indexes").

- [ ] **Step 4: Run them.** Run: `nix develop -c pytest -q -n 0 tests/test_peer_file.py tests/test_web_offline.py`. Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/caracole/peer_file.py src/caracole/web/offline_routes.py tests/test_peer_file.py tests/test_web_offline.py
git commit -m "feat(peer): a library written to a .caracole file"
```

### Task 5: A file read back, refused, and taken from

**Files:**
- Modify: `src/caracole/peer_file.py` (`SyncFile`, `read_file`, `FileSource`, `check_importable`, the five refusals)
- Test: `tests/test_peer_file.py` (new cases)

**Interfaces:**
- Consumes: Task 4; `peer_sync.UnitSource`, `PeerError`, `read_state_document`, `value_of_document`, `digest_of`;
  `peer_push.kept_copy`; `index_transfer.META`.
- Produces:
  - `@dataclass(frozen=True) class SyncFile`, with:
    - fields `path: Path`, `manifest: dict[str, Any]`, `state: PeerState | None`, `bases: dict[str, dict]`,
      `holds: tuple[str, ...]`, `index_only: bool`;
    - properties `id -> str | None`, `name -> str`, `made -> str | None`;
    - `base_for(peer: str | None) -> tuple[Base | None, Kept]`;
  - `read_file(path: Path) -> SyncFile`;
  - `class FileSource`, a `peer_sync.UnitSource`:
    - `__init__(self, file: SyncFile, conn: sqlite3.Connection | None, library_dir: Path)`;
    - `unit(id) -> dict | None`;
    - `file(key, name, sha256) -> bytes`;
    - `indexes(to: Path) -> bool`;
    - `pages() -> dict | None`;
    - `page(sha256: str) -> bytes`;
  - `check_importable(file: SyncFile, conn, *, own: str | None) -> None`;
  - the constants `NOT_A_FILE`, `OTHER_FORMAT`, `OWN_EXPORT`, `OLDER`, `UNREADABLE` (§3.3).

- [ ] **Step 1: Write the failing tests**

```python
def test_a_file_read_back_is_what_was_exported_unit_for_unit(exported):
    f = peer_file.read_file(exported.path)
    src = peer_file.FileSource(f, None, tmp)
    for unit_id, unit in f.state.units.items():
        assert sync.digest_of(sync.value_of_document(unit_id, src.unit(unit_id))) == unit.digest
    assert (f.id, f.name, f.holds) == (OWN_ID, "Desk", ("library", "songbooks"))

def test_a_unit_the_file_doesnt_name_is_an_error_never_a_removal(exported):
    with pytest.raises(sync.PeerError):
        peer_file.FileSource(peer_file.read_file(exported.path), None, tmp).unit("song/not/here")

@pytest.mark.parametrize("bad", ["../evil", "files/notahash", "extra.txt", "files/" + "A" * 64])
def test_a_member_outside_the_layout_is_refused_whole(tmp_path, bad):
    with pytest.raises(peer_file.FileError, match="can't be read whole"):
        peer_file.read_file(zip_with(tmp_path, {"caracole.json": MANIFEST_OK, bad: b"x"}))

def test_a_file_cut_short_or_with_a_blob_over_its_size_is_refused(tmp_path, exported):
    cut = tmp_path / "cut.caracole"; cut.write_bytes(exported.path.read_bytes()[:-500])
    with pytest.raises(peer_file.FileError): peer_file.read_file(cut)
    with pytest.raises(peer_file.FileError): peer_file.read_file(zip_declaring(tmp_path, "files/" + "a" * 64, peer_file.FILE_MAX + 1))

def test_something_else_is_not_a_file_caracole_exported(tmp_path):
    (tmp_path / "x").write_bytes(b"hello")
    with pytest.raises(peer_file.FileError, match="isn't a file caracole exported"): peer_file.read_file(tmp_path / "x")

def test_an_index_export_is_an_import_of_indexes_alone(conn, tmp_path):
    index_transfer.export(conn, tmp_path / "i.sqlite", now=NOW)
    f = peer_file.read_file(tmp_path / "i.sqlite")
    assert (f.index_only, f.holds, f.id, f.state) == (True, ("indexes",), None, None)

def test_own_export_and_one_no_newer_than_the_last_sync_are_refused(conn, exported_by_other):
    with pytest.raises(peer_file.FileError, match="this library's own export"):
        peer_file.check_importable(peer_file.read_file(own_export), conn, own=OWN_ID)
    sync.record_agreement(conn, OTHER_ID, {}, {}, "2026-11-03T21:10:00Z")   # the file's made, or later
    with pytest.raises(peer_file.FileError, match=r"Nothing in this file is newer than your sync with Studio on 03/11/26\."):
        peer_file.check_importable(peer_file.read_file(exported_by_other.path), conn, own=OWN_ID)

def test_a_blob_whose_bytes_arent_its_name_is_refused_when_read(...):  # FileSource.file raises PeerError
```

- [ ] **Step 2: Run them and see them fail.** Run: `nix develop -c pytest -q -n 0 tests/test_peer_file.py`. Expected: FAIL, `no attribute 'read_file'`.

- [ ] **Step 3: Implement §3.3's reading rules.** `read_file` reads the central directory and the three JSON members
  alone. Blobs are read when asked for, checked by SHA-256. `zipfile.BadZipFile`, `zlib.error`, `EOFError` and
  `KeyError` become `UNREADABLE`, and `SyncFile` never holds an open file.

- [ ] **Step 4: Run them.** Expected: PASS.

- [ ] **Step 5: Commit** — `feat(peer): a .caracole file read back, checked, and refused in your words`

### Task 6: An upload staged part by part

**Files:**
- Create: `src/caracole/peer_import.py`, `tests/test_peer_import.py`

**Interfaces:**
- Consumes: `peer_push`'s `FOLDER`, `ID`, `_private_dir`, `_write_private`, `_read_json` (imported, never changed); `peer_file.IMPORT_MAX`.
- Produces:
  - `OPEN = 1`, `PART_MAX = 8 * 1024 * 1024`, `EXPIRES = 3600.0`, `PREFIX = "import-"`, `FILE = "file.caracole"`,
    `OPENED = "open.json"`;
  - `class StagingError(ValueError)` (`.status`);
  - `open_import(state_dir, *, size: int, name: str, now: float | None = None) -> str`;
  - `add_part(state_dir, import_id: str, at: int, data: bytes) -> int`;
  - `whole(state_dir, import_id: str) -> Path`;
  - `sweep(state_dir, now: float | None = None) -> list[str]`;
  - `held(folder: Path)`, a contextmanager;
  - `staged_folder(state_dir, given) -> Path`;
  - `remove(folder: Path) -> None`.
- Words:

| Status | Words |
|---|---|
| 413 | "That file is too big: a file to import is at most 8 GiB." |
| 409 | "A file is being sent here already: try again once it is taken, or in an hour." |
| 400 | "That part isn't the next one: choose the file again." |
| 404 | "No such import is open here: choose the file again." |
| 400 | "That file isn't whole yet: send the rest of it." |

- [ ] **Step 1: Write the failing tests**:
  - `test_an_upload_is_staged_part_by_part_in_order_and_whole_once_its_size_is_reached`: three parts → `have` 3, 6,
    8; `whole()` is the bytes joined;
  - `test_a_part_out_of_order_or_past_the_size_is_refused` (`at` ≠ have; `have + len > size`);
  - `test_one_import_at_a_time_and_an_hour_untouched_is_swept_unless_held`;
  - `test_staged_folder_refuses_any_other_path` (a symlink to it, another prefix, a folder elsewhere);
  - `test_the_staged_file_is_0600_in_a_0700_folder`;
  - `test_a_file_bigger_than_eight_gib_is_refused_before_anything_is_made`.
- [ ] **Step 2: Run them and see them fail** (`ModuleNotFoundError`).
- [ ] **Step 3: Implement.** Write with `os.open(..., O_WRONLY | O_NOFOLLOW)` and `os.pwrite` at `at`, under a module
  lock, the folder's mtime touched with each part (`sweep` reads it as push's `_touched` does).
- [ ] **Step 4: Run them.** Expected: PASS.
- [ ] **Step 5: Commit** — `feat(peer): a file to import staged part by part in state_dir/peer`

### Task 7: `caracole peer export` and `caracole peer import`

**Files:**
- Modify: `src/caracole/commands/peer.py` (two commands; `_Said.report`; `_import`)
- Test: `tests/test_commands_peer_file.py` (new; two libraries made by `helpers`, as `tests/test_commands_peer.py` makes them)

**Interfaces:**
- Consumes: Tasks 4–6; §3.1 `merged_base`, `merged_kept`, `record_agreement`, `record_kept`; §3.2 `in_scope`, `listed_songs`; `apply_units`; `backup.make(label=BACKUP_LABEL)`; `render_all`, `render_songbooks`, `write_pages`; `index_transfer.merge`.
- Produces:
  - `caracole peer export FILE [--parts library,songbooks]`: no lock, one read transaction. It prints `"Exported
    {name}: {songs} songs, {songbooks} songbooks, {MB} MB to {FILE}."`, then a line per song left.
  - `caracole peer import SOURCE [--parts P] [--choose here|there:UNIT]… [--prefer here|there] [--compared HASH]
    [--progress] [--yes]`:
    - `SOURCE` is a file, or a staged folder (`peer_import.staged_folder`, held, removed at the end and swept);
    - its stages are §3.5's `PEER_IMPORT_STAGES` names, and `--progress` says them, each unit (`taken`, `left`) and
      the report (`{"event": "report", …}`, `with.kind` `"file"`);
    - under `exclusive(cfg, "peer import", interactive=True)`, with a backup first, labelled `before-sync`;
    - exit 2 for `FileError` (words as §3.3), 1 for a unit left, else 0.
  - The import's rules:
    - this side's units and the file's state are compared with `base_of(conn, file.id)` merged with
      `file.base_for(own)`, and `merged_kept` of both;
    - scoped by `in_scope(found, holds, listed=…, holds=holds)`, then by `--parts`;
    - `THEIRS` is taken. `MINE` is neither taken nor said. A conflict goes by `--choose`, else `--prefer`, else is
      asked on a terminal, else left;
    - after the take: `record_agreement(conn, file.id, mine_after, file.state.units, at=file.made)`, then
      `record_kept(conn, file.id, {u: (here, there) for conflicts kept here}, at=file.made)`;
    - with `"indexes"` held and asked, `indexes.sqlite` is copied out beside the staged file (or to
      `cache_dir/peer/`) and merged, then deleted;
    - an index-only file does only that, and records no agreement.

- [ ] **Step 1: Write the failing tests**

```python
def test_an_export_imported_into_another_library_brings_its_songs_files_and_songbooks(two_libraries):
    run(desk, "peer", "export", str(f := tmp / "d.caracole"))
    out = run(studio, "peer", "import", "--yes", str(f))
    assert out.exit_code == 0 and state(studio) >= state_of_units(desk, LIBRARY | SONGBOOKS)

def test_a_second_import_of_the_same_file_is_refused_as_no_newer(two_libraries):
    run(studio, "peer", "import", "--yes", str(f))
    again = run(studio, "peer", "import", "--yes", str(f))
    assert again.exit_code == 2 and "Nothing in this file is newer than your sync with Desk on" in again.output

def test_a_librarys_own_export_is_refused_and_changes_nothing(two_libraries):  # exit 2, OWN_EXPORT, kv untouched

def test_a_songbooks_only_file_removes_no_song_it_doesnt_hold(two_libraries):
    run(desk, "peer", "export", "--parts", "songbooks", str(f))
    before = songs(studio)
    run(studio, "peer", "import", "--yes", str(f))
    assert songs(studio) >= before

def test_a_conflict_kept_here_is_remembered_and_not_asked_again_at_the_next_import(two_libraries):
    # both change song X; import with --choose here:song/X → kept_of(studio, desk_id)[song/X] == (studio's, file's)
    # desk exports again unchanged → the next import finds song/X proposed MINE, with KEPT_HERE, and takes nothing

def test_with_progress_an_import_says_its_stages_its_units_and_a_report(two_libraries):
    lines = [json.loads(l) for l in run(studio, "peer", "import", "--yes", "--progress", str(f)).output.splitlines()]
    assert [l["stage"] for l in lines if l.get("state") == "running"] == ["check", "take", "render", "agree"]
    [report] = [l["report"] for l in lines if l.get("event") == "report"]
    assert report["with"] == {"name": "Desk", "kind": "file", "address": None} and report["indexes"] == []

def test_an_index_file_is_merged_and_records_no_agreement(two_libraries):  # index export → indexes merged; no sync:base

def test_a_staged_folder_is_taken_then_deleted(two_libraries):  # SOURCE = peer_import folder → gone after
```

- [ ] **Step 2: Run them and see them fail** (`No such command 'export'`).
- [ ] **Step 3: Implement both commands** in commands/peer.py's style. The heavy imports stay inside the functions:
  `test_commands_index_match.py::test_registering_the_commands_imports_neither_the_matcher_nor_the_index` must stay
  green.
- [ ] **Step 4: Run them**, then `tests/test_commands_peer.py` and `tests/test_commands_index_match.py`. Expected: PASS.
- [ ] **Step 5: Commit** — `feat(peer): caracole peer export and peer import`

### Task 8: `caracole peer sync --parts`, and the kept answers it reads

**Files:**
- Modify: `src/caracole/commands/peer.py` (`sync_cmd`'s `--parts`; `_compare` merges kept and lists songs)
- Test: `tests/test_commands_peer_file.py` (two cases)

**Interfaces:**
- Consumes: §3.1, §3.2; `Peer.unit` (the peer's songbook documents for `listed_songs`).
- Produces:
  - `caracole peer sync ADDRESS --parts library,songbooks,indexes` (the default all three): the differences outside
    the parts are neither taken nor given nor said; `"indexes"` is accepted and does nothing until Task 23;
  - `_compare(cfg, address)` returns, beside what it does, `kept` (`merged_kept`) and `listed`, and its differences
    come from `compare(..., kept=…)`.

- [ ] **Step 1: Write the failing tests**:
  - `test_a_sync_of_songbooks_alone_takes_the_songbook_and_its_song_and_nothing_else` (two `caracole serve` over
    `httpx.MockTransport`, as `tests/test_commands_peer.py`'s `computers` fixture);
  - `test_a_unit_kept_here_at_an_import_is_given_at_the_next_network_sync` (kept here, then `peer sync --push --yes`
    → the other side holds this side's version, and `kept_of` is empty after).
- [ ] **Step 2: Run them and see them fail** (`No such option: --parts`).
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run them** with `tests/test_commands_peer.py`. Expected: PASS.
- [ ] **Step 5: Commit** — `feat(peer): peer sync --parts, and the answers an import remembered`

### Task 9: The file's corpus, the owner's choice, the docs

**Files:**
- Create: `tests/test_conformance_sync_file.py`, `tests/conformance/vectors/sync/file.jsonl`,
  `tests/conformance/vectors/sync/files/{full,songbooks,indexes}.caracole`
- Modify:
  - AGENTS.md:
    - a new `#### peer_file.py` under "Shared by the steps and the commands": the file's layout, its refusals, that
      an import is a sync with the file (`FileSource`), the remembered answer;
    - `##### harptabs.com`, `##### gametabs.net` and `##### azlyrics.com`: one bullet each, "An export (`caracole
      peer export`, the Sync tab's Export, the phone's) holds what this site gave too, to share as the owner likes:
      the owner's choice of 2026-11-03 ('ignore the privacy, share everything'); caracole itself sends it nowhere.";
    - "### One caracole at a time": `peer export` among those that only read and never wait;
  - docs/usage.md: "### Export and import: peer export, peer import" under "## Two caracoles".

**Interfaces:**
- Produces `vectors/sync/file.jsonl`:
  - `{fn: "export", fixture, parts, now, name, out: {manifest, state, bases, units, files, pages}}`, every member
    parsed as JSON, `files` the sorted SHA-256 list. Its three files are written beside it, deterministic: fixed
    `made`, members in §3.3's order;
  - `{fn: "read", file: "files/<name>.caracole", out: {id, name, made, holds, index_only, units: {id: digest}}}`, one
    for each refusal (a file made in the test: cut short, `../`, own, older) with `out: {"error": <words>}`;
  - `{fn: "import", here: fixture, kv, file, parts, choices, out: {differences: [[id, proposal, why]], taken, left,
    base_after, kept_after}}`.

- [ ] **Step 1: Write the generator** (`test_file_jsonl_is_what_export_read_and_import_do`) — check mode first, FAIL.
- [ ] **Step 2: Write the vectors.** Run: `CARACOLE_CORPUS=write nix develop -c pytest -q -n 0 tests/test_conformance_sync_file.py`
- [ ] **Step 3: The gates.** Run:
```
nix develop -c pytest -q -n 0 tests/test_conformance_sync_file.py tests/test_conformance_sync_kept.py
nix develop -c pytest -q tests/test_corpus_budget.py
nix develop -c pytest -q
nix develop ./android -c gradle -p android test
nix build .#checks.x86_64-linux.package
```
Expected: PASS each.
- [ ] **Step 4: Commit** — `test(conformance): the .caracole file, for the phone; docs: export and import`

---

## 6. Lane sync-core (kotlin): the rules, the file and the engine on the phone

Branch `android/sync-core`. Depends on sync-rules, sync-file, index-push (SyncEngine.kt, PeerClient.kt and
FakeComputer.kt in turn after the android/sync-crossing group), songbook-writers (`core.songbooks.Songbooks.entryKeys`)
and device-replays (SyncReplay.kt). Every rule here replays a Python vector. `:core` calls no JDK or ICU text API
(`ForbiddenApiTest`).

### Task 10: The remembered answer and the parts in Kotlin

**Files:**
- Modify: `android/core/src/main/kotlin/io/github/danielhp95/caracole/core/sync/Compare.kt`, `core/sync/PeerClient.kt` (`PeerState.kept`)
- Create: `core/sync/Scope.kt`, `android/core/src/test/kotlin/io/github/danielhp95/caracole/core/sync/KeptTest.kt`, `core/sync/ScopeTest.kt`
- Modify: `android/core/src/testFixtures/kotlin/io/github/danielhp95/caracole/core/testing/replays/SyncReplay.kt` (kept.jsonl, scope.jsonl)

**Interfaces:**
- Consumes: §3.1, §3.2; `vectors/sync/kept.jsonl`, `scope.jsonl`; `Songbooks.entryKeys` (songbook-writers); `Normalize.identityKey`.
- Produces:
  - `data class KeptEntry(val here: String?, val there: String?, val at: String)`, `typealias Kept = Map<String,
    KeptEntry>`, `data class KeptPair(val here: String?, val there: String?, val chooser: String)`;
  - `Compare.keptOf(db: Db, peer: String): Kept`, `Compare.recordKept(db: Db, peer: String, chosen: Map<String,
    Pair<String?, String?>>, at: String): Int`;
  - `Compare.mergedKept(mine: Base?, mineKept: Kept, theirs: Base?, theirsKept: Kept): Map<String, KeptPair>`;
  - `Compare.compare(mine, theirs, base, kept: Map<String, KeptPair>? = null)`, `Compare.KEPT_HERE`, `KEPT_THERE`;
  - `PeerState.kept: Kept` (default empty);
  - `object Scope { val PARTS: List<String>; fun partOf(unitId: String): String?; fun listedSongs(books: Map<String,
    JsonObject>, units: Collection<String>): Map<String, List<String>>; fun inScope(found: List<Difference>, parts:
    Collection<String>, listed: Map<String, List<String>> = emptyMap(), holds: Collection<String>? = null):
    List<Difference>; fun changeOf(d: Difference, base: Map<String, String?>?, kept: Map<String, KeptPair>? = null):
    Pair<String?, String?>; fun namesOf(unitId: String, label: String): Pair<String, String>? }`;
  - `Compare.recordAgreement` keeps `"kept"` and drops the agreed.

- [ ] **Step 1: Write the failing tests.**
  - `KeptTest`:
    - `` `every record of kept jsonl replays` `` (`SyncReplay.kept(misses)`; the misses empty);
    - `` `an agreement drops the kept answer of each unit it agrees on and keeps the others` `` (one `TestDb`).
  - `ScopeTest`:
    - `` `every record of scope jsonl replays` ``;
    - `` `a file that holds no library never reads a song it lacks as removed` `` (a direct case, as Python's).
- [ ] **Step 2: Run them and see them fail.** Run: `nix develop ./android -c gradle -p android :core:test --tests 'io.github.danielhp95.caracole.core.sync.KeptTest' --tests 'io.github.danielhp95.caracole.core.sync.ScopeTest'`. Expected: FAIL (unresolved `keptOf`).
- [ ] **Step 3: Implement.** Stamps compare as Python's strings do (`Py.CODE_POINT_ORDER`).
- [ ] **Step 4: Run them, then `:core:test`.** Expected: PASS.
- [ ] **Step 5: Commit** — `feat(android): the remembered answer and a sync's parts on the phone`

### Task 11: The `.caracole` file in Kotlin

**Files:**
- Create: `core/sync/file/SyncFiles.kt`, `SyncFile.kt`, `FileSource.kt`, `Zip.kt`; `core/index/TabCounts.kt`;
  tests `core/sync/file/SyncFilesTest.kt`, `core/index/TabCountsTest.kt`
- Modify: `SyncReplay.kt` (file.jsonl)

**Interfaces:**
- Consumes: §3.3; `vectors/sync/file.jsonl` and its three files; `Units.libraryState`, `Units.document`, `Units.valueOfDocument`; `IndexTransfer` (export through `core.index.Export` of index-push, `newest`); `core.web.DownloadNames` (the skeleton moved it).
- Produces:
  - `object SyncFiles`:
    - `const val FORMAT = 1`, `const val MEDIA_TYPE = "application/vnd.caracole+zip"`;
    - `fun fileName(name: String?, at: Instant, zone: ZoneId): String`;
    - `fun export(db: Db, libraryDir: File, pages: PageSource?, to: File, parts: List<String>, now: String, id:
      String, name: String, version: String): Made`;
    - `fun read(file: File): SyncFile`;
    - `fun checkImportable(file: SyncFile, db: Db, own: String, zone: ZoneId)`;
    - `fun indexesSize(db: Db): Long?`;
  - `interface PageSource { fun manifest(units: Map<String, String>): JsonObject?; fun open(sha256: String): InputStream? }`;
  - `data class Made(val file: File, val parts: List<String>, val songs: Int, val songbooks: Int, val size: Long, val left: List<String>)`;
  - `class SyncFile` (`manifest`, `state: PeerState?`, `bases`, `holds`, `indexOnly`, `id`, `name`, `made`,
    `baseFor(peer)`);
  - `class FileSource(file: SyncFile, database: Database?, libraryDir: File) : UnitSource`, with `indexes(to: File):
    Boolean`, `pages(): JsonObject?`, `page(sha256): InputStream`;
  - `class FileError(message: String) : Exception(message)`, holding §3.3's words;
  - `object TabCounts { fun of(db: Db): Map<String, Long> }`, the rows of each site's first table.

- [ ] **Step 1: Write the failing tests.**
  - `` `every record of file jsonl replays: Python's files read back alike, and the phone's export of each fixture is Python's as data` ``;
  - `` `a member outside the layout, a blob over 64 MiB or a file cut short is refused whole` ``;
  - `` `an index export is a file of indexes alone` ``;
  - `` `the file's name is the library's name and the day` ``: `fileName("horde_logbook", 2026-11-03T21:10Z, UTC) ==
    "horde_logbook-03-11-26.caracole"`;
  - `TabCountsTest`: `` `each site counts the rows of its first table` ``.
- [ ] **Step 2: Run them and see them fail** (`:core:test --tests '*SyncFilesTest' --tests '*TabCountsTest'`).
- [ ] **Step 3: Implement.**
  - Writing: `ZipOutputStream`. `STORED` entries take their size and CRC from a first pass over the file; JSON is
    `DEFLATED`, written by `PyJson` as Python's `json.dumps(ensure_ascii=False)` would.
  - Reading: `ZipFile` (no `ZipInputStream`), names checked before any entry is opened.
  - The phone's own `pages`: `null` until Task 33 wires a `PageSource`.
- [ ] **Step 4: Run them, then `:core:test`.** Expected: PASS.
- [ ] **Step 5: Commit** — `feat(android): the .caracole file written and read on the phone`

### Task 12: The engine's parts, its comparison's new members, and the unattended sync

**Files:**
- Modify: `core/sync/SyncEngine.kt`, `core/sync/PeerClient.kt` (`indexes()`), testFixtures `core/testing/sync/FakeComputer.kt` (answers `GET /api/sync/indexes`)
- Test: `android/core/src/test/kotlin/io/github/danielhp95/caracole/core/sync/client/SyncEngineTest.kt` (new cases)

**Interfaces:**
- Consumes: Task 10; `PeerClient.unit` (songbook documents); §3.4.1's members.
- Produces:
  - `data class Comparison` gains:
    - `kind: String` (`"computer"` / `"file"`) and `file: SyncFile?`;
    - `holds: List<String>` and `listed: Map<String, List<String>>`;
    - `songbooks: Map<String, Pair<JsonObject?, JsonObject?>>`;
    - `indexes: List<IndexWaiting>` and `base: Map<String, String?>?`;
    - `kept: Map<String, KeptPair>`;
  - `data class IndexWaiting(val site: String, val title: String, val here: String?, val there: String?, val newer: String)`;
  - `enum class Conflicts { ASK, LEAVE }`;
  - `suspend fun apply(c: Comparison, choices: Map<String, Side>, prefer: Side?, parts: List<String> = Scope.PARTS,
    conflicts: Conflicts = Conflicts.ASK, stage: (String, String, String) -> Unit): SyncOutcome`:
    - LEAVE leaves each unsettled conflict (`UNSETTLED`) and never refuses;
    - with Library unticked, the mirror stage is skipped ("Library isn't synced this time");
    - with Site indexes unticked, the index stage is skipped;
  - `fun documents(c: Comparison, unitId: String): Pair<JsonObject?, JsonObject?>` (`/api/sync/unit`);
  - `fun tested(address: String): Tested`, with `data class Tested(val peer: PeerState, val address: String, val
    songs: Int, val songbooks: Int, val indexes: String?, val syncedAt: String?)`;
  - `data class IndexCount(val read: String?, val tabs: Long)` and `PeerClient.indexes(): Map<String, IndexCount>`.

- [ ] **Step 1: Write the failing tests** (against `FakeComputer`):
  - `` `songbooks alone take the songbook and the song it lists and nothing else` ``;
  - `` `the unattended sync takes and gives every one-sided change and leaves each conflict, never refusing` `` (the
    outcome's `left` holds the conflict with `UNSETTLED`; both sides' digests of it unchanged);
  - `` `a unit kept at an import is given at the next sync without asking` `` (the phone's kept answer → the computer
    takes it, and `keptOf` is empty after);
  - `` `the comparison carries each difference's names, change, part and songbooks, and the indexes waiting` ``;
  - `` `library unticked skips the mirror, and indexes unticked skips the index stage` ``;
  - `` `tested says the computer's songs, songbooks, newest index and the last sync, and changes nothing` ``.
- [ ] **Step 2: Run them and see them fail** (`:core:test --tests '*SyncEngineTest'`).
- [ ] **Step 3: Implement.** `compare` asks `client.unit` once for each songbook difference, so `listed` reads both
  sides' songbook documents.
- [ ] **Step 4: Run `:core:test`.** Expected: PASS (the existing cases unchanged).
- [ ] **Step 5: Commit** — `feat(android): a sync's parts, and the unattended sync that leaves conflicts`

### Task 13: An import on the phone

**Files:**
- Modify: `core/sync/SyncEngine.kt` (`compareFile`, file comparisons in `apply`, `FILE_STAGES`, the `pagesFromFile` hook)
- Test: `core/sync/file/ImportTest.kt` (new)

**Interfaces:**
- Consumes: Task 11's `SyncFile`, `FileSource`, `checkImportable`; Task 10's `recordKept`; `Take.applyUnits`, `Take.backupBeforeSync`; `IndexTransfer.merge`.
- Produces:
  - `fun compareFile(file: File): Comparison`, refusing with `FileError` as §3.3 says;
  - `apply` on a file comparison runs `FILE_STAGES` (`check`, `take`, `mirror`, `agree`, `index`). Then it records
    the agreement and the kept answers as Task 7 does, hands the units taken to `pagesFromFile`, and gives nothing;
  - the constructor parameter `pagesFromFile: ((SyncFile, List<String>) -> Unit)? = null`.

- [ ] **Step 1: Write the failing tests**:
  - `` `every import record of file jsonl gives the same differences, takes and bases as Python's` ``;
  - `` `a songbooks only file removes no song it doesn't hold` ``;
  - `` `the same file twice, the phone's own export or an older file is refused and changes nothing` ``;
  - `` `a conflict kept here is remembered with both digests at the file's made` ``;
  - `` `an index file merges its indexes and records no agreement` ``;
  - `` `the units taken from a file are handed to the pages hook, and none when nothing was taken` ``.
- [ ] **Step 2: Run them and see them fail.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run `:core:test`.** Expected: PASS.
- [ ] **Step 5: Commit** — `feat(android): a file imported on the phone, as a sync with it`

### Task 14: The report, and the phone's sync heading in AGENTS.md

**Files:**
- Modify: `core/sync/SyncEngine.kt` (`SyncOutcome.report`; the index stage counts around its merge, and after its
  push it waits for the computer's merge job and reads `GET /api/sync/indexes`)
- Modify: AGENTS.md (`#### android/`: a new `##### Syncing on the phone`: the engine's parts, `Conflicts.LEAVE`, an
  import, the report)
- Test: `SyncEngineTest.kt` (two cases)

**Interfaces:**
- Consumes: §3.5; `TabCounts.of`; `PeerClient.job`, `awaitJob`; `PeerClient.indexes`.
- Produces: `SyncOutcome(..., val report: JsonObject?)`, written as §3.5's JSON, `with.kind` `"computer"` or `"file"`.

- [ ] **Step 1: Write the failing tests**:
  - `` `a sync's report counts each index taken before and after its merge` ``;
  - `` `an index given is counted on the computer before the push and after its merge job` ``.
- [ ] **Step 2: Run them and see them fail.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: The gates.** Run:
```
nix develop ./android -c gradle -p android test
nix develop -c pytest -q
ANDROID_AVD_HOME=/home/dani/.config/.android/avd QT_QPA_PLATFORM=xcb android/scripts/device-test.sh io.github.danielhp95.caracole.CorpusOnDeviceTest
CARACOLE_ANDROID_E2E=1 nix develop -c pytest -q -n 0 tests/test_android_e2e.py
```
The script starts `nix develop ./android#emulator` with AVD `caracole` when none runs, under the emulator lock.
Expected: PASS each, `SyncReplay` replaying kept, scope and file under ART.
- [ ] **Step 5: Commit** — `feat(android): a sync's report, with each index's tabs before and after`

---

## 7. Lane sync-routes (mixed): the network sync's routes on both servers

Branch `android/sync-routes`. Depends on sync-core, index-push (`index_transfer.py` in turn), requests-tab
(`tests/test_conformance_sync_routes.py`'s job views) and device-replays (WebReplay.kt, SyncRoutesVectorsTest.kt).
`vectors/web/sync_routes.jsonl` changes here with the Kotlin side in the same commit (Task 19).

### Task 15: `GET /api/sync` and `POST /sync/test`

**Files:**
- Modify: `src/caracole/web/sync_routes.py` (`sync_state`, new `test`, `tested_words`)
- Test: `tests/test_web_sync.py`

**Interfaces:**
- Consumes: §3.4.1; `Peer.state`; `peers_of`.
- Produces: `GET /api/sync`'s `device`, `songs`, `songbooks`; `Route("POST", "/sync/test", …)`; `tested_words(name:
  str, songs: int, songbooks: int, indexes_at: str | None) -> str`.

- [ ] **Step 1: Write the failing tests**:

```python
def test_the_tab_reads_this_caracole_its_device_and_its_counts(computers):
    assert script(here, "api/sync")["device"] == "computer" and script(here, "api/sync")["songs"] == 2

def test_test_asks_the_other_caracole_and_changes_nothing(computers):
    said = script(here, "sync/test", {"address": THERE})
    assert said["said"] == "Studio answered: 3 songs, 1 songbook, its indexes read 02/11/26"
    assert kv_rows(here) == before and asked_paths(there) == ["/api/peer/state"]

def test_test_says_no_indexes_and_refuses_as_compare_does(computers):  # ", no indexes"; 400 address; 502; 409 same id
```
- [ ] **Step 2: Run them and see them fail.** Run: `nix develop -c pytest -q -n 0 tests/test_web_sync.py`.
- [ ] **Step 3: Implement**, the docstring's route lines in its style (test_web_app.py checks them).
- [ ] **Step 4: Run them.** Expected: PASS.
- [ ] **Step 5: Commit** — `feat(serve): the Sync tab's Test asks the other caracole, changing nothing`

### Task 16: The comparison's new members, `GET /api/sync/unit` and `GET /api/sync/indexes`

**Files:**
- Modify: `src/caracole/web/sync_routes.py` (`compare`, `_compared` with kept and listed, `Compared` gains `source`,
  `holds`, `listed`, `kind`, `unit_documents`, `indexes`), `src/caracole/index_transfer.py` (`tab_counts` alone)
- Test: `tests/test_web_sync.py`, `tests/test_index_transfer.py` (one case)

**Interfaces:**
- Consumes: §3.2, §3.1; `Peer.unit`; `index_transfer.newest`.
- Produces: §3.4.1's members; `Compared(address, name, hash, proposals, at, source: str = "peer", holds:
  tuple[str, ...] = PARTS, listed: dict = …, kind: str = "server")`; `index_transfer.tab_counts(conn) -> dict[str,
  int]`.

- [ ] **Step 1: Write the failing tests**:
  - `test_a_comparison_names_each_songs_artist_and_title_and_each_sides_change_and_part`;
  - `test_a_songbook_difference_carries_both_documents_and_lists_its_songs`;
  - `test_the_indexes_newer_on_either_side_are_listed_in_the_sites_order`;
  - `test_a_units_two_documents_are_answered_for_a_comparison_kept_and_refused_otherwise` (200; 409 GONE; 404);
  - `test_the_indexes_route_says_each_sites_newest_read_and_its_tabs`;
  - `test_tab_counts_are_the_rows_of_each_sites_first_table`.
- [ ] **Step 2: Run them and see them fail.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run them**, with `tests/test_web_app.py` (the routes' docstring lines). Expected: PASS.
- [ ] **Step 5: Commit** — `feat(serve): a comparison says what changed where, and each conflict's two documents`

### Task 17: `POST /sync/apply` with parts

**Files:**
- Modify: `src/caracole/web/sync_routes.py` (`apply`), `tests/test_web_sync.py`

**Interfaces:**
- Consumes: Task 8's `peer sync --parts`.
- Produces: `apply` reads `parts` and queues `--parts=<P>` (§3.4.1).

- [ ] **Step 1: Write the failing tests**:
  - `test_sync_queues_its_parts_and_refuses_a_part_it_doesnt_know`;
  - `test_two_computers_sync_songbooks_alone_through_the_routes`.
- [ ] **Step 2: Run them and see them fail.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run `tests/test_web_sync.py`.** Expected: PASS (the old cases unchanged: no `parts` is all three).
- [ ] **Step 5: Commit** — `feat(serve): Sync sends the parts ticked`

### Task 18: The phone answers the same, and its unattended sync

**Files:**
- Modify: `android/server/src/main/kotlin/io/github/danielhp95/caracole/server/routes/SyncRoutes.kt`, `routes/library/SyncJson.kt`
- Create: `android/server/src/test/kotlin/io/github/danielhp95/caracole/server/routes/library/SyncRoutesTest.kt` (or extend it if it exists)

**Interfaces:**
- Consumes: Tasks 12, 14 (`Comparison`'s members, `tested`, `documents`, `apply(parts, conflicts)`, `SyncOutcome.report`); `TabCounts.of`, `IndexTransfer.newest`.
- Produces:
  - SyncRoutes answers §3.4.1's six routes as Python does, `device` `"phone"`;
  - `fun tested(address: String): JsonObject` (`/sync/test`'s answer, for Settings too);
  - `fun alone(address: String): Job?`: an unattended sync of the three parts, `Conflicts.LEAVE`, null when one with
    that address waits or runs;
  - `SyncJson.outcome` writes `"report"` when there is one;
  - the constructor's new parameters all have defaults, so Assembly.kt is unchanged here.

- [ ] **Step 1: Write the failing tests**:
  - `` `test says the computer's counts in Python's words` ``;
  - `` `the comparison's new members are Python's` ``;
  - `` `apply sends the parts to the engine` ``;
  - `` `alone queues one sync that leaves conflicts and refuses a second while it runs` ``.
- [ ] **Step 2: Run them and see them fail.** Run: `nix develop ./android -c gradle -p android :server:test --tests '*SyncRoutesTest'`.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run `:server:test`.** Expected: PASS, except SyncRoutesVectorsTest until Task 19.
- [ ] **Step 5: Commit** — `feat(android): the phone's sync routes answer what caracole serve answers`

### Task 19: The routes' corpus, both sides in one commit

**Files:**
- Modify: `tests/test_conformance_sync_routes.py` (records for `POST /sync/test`, `GET /api/sync/unit`, `GET
  /api/sync/indexes`, compare's members, apply's parts), `tests/conformance/vectors/web/sync_routes.jsonl`,
  testFixtures `server/testing/replays/WebReplay.kt` (the new fns), `SyncRoutesVectorsTest.kt` (its fn set)
- Modify: docs/usage.md ("### caracole serve": the Sync tab's routes); AGENTS.md (`##### Routes by area`: a
  `sync_routes.py` bullet)

- [ ] **Step 1: Regenerate.** Run: `CARACOLE_CORPUS=write nix develop -c pytest -q -n 0 tests/test_conformance_sync_routes.py`
- [ ] **Step 2: Make the replay ask the new routes**, then the fn set `assertEquals(setOf("GET /api/sync", "POST
  /sync/test", "POST /sync/compare", "GET /api/sync/unit", "GET /api/sync/indexes", "POST /sync/apply"), …)`.
- [ ] **Step 3: The gates.** Run:
```
nix develop -c pytest -q -n 0 tests/test_conformance_sync_routes.py
nix develop -c pytest -q tests/test_corpus_budget.py
nix develop -c pytest -q
nix develop ./android -c gradle -p android test
nix build .#checks.x86_64-linux.package
ANDROID_AVD_HOME=/home/dani/.config/.android/avd QT_QPA_PLATFORM=xcb android/scripts/device-test.sh io.github.danielhp95.caracole.CorpusOnDeviceTest
CARACOLE_ANDROID_E2E=1 nix develop -c pytest -q -n 0 tests/test_android_e2e.py
```
Expected: PASS each.
- [ ] **Step 4: Commit** — `test(conformance): the sync routes' new answers, both sides`

---

## 8. Lane sync-exchange (python): export and import on caracole serve, and the indexes both ways

Branch `android/sync-exchange`. Depends on sync-file, sync-routes, index-push (`peer_routes.py` and
`tests/test_web_peer.py` in turn) and requests-tab (`status.py` in turn).

### Task 20: The export's routes

**Files:**
- Create: `src/caracole/web/sync_file_routes.py`, `tests/test_web_sync_files.py`
- Modify: `src/caracole/web/__init__.py` (its parts' line), `src/caracole/peer_file.py` (`indexes_size`, in turn after
  sync-file)

**Interfaces:**
- Consumes: Task 4's `export_file`, `file_name`, `MEDIA_TYPE`; `offline_routes.manifest_of`; `peer_routes._Streamed`
  and `_leftovers` (imported); `download_names.content_disposition`.
- Produces: `GET /api/sync/sizes`, `POST /sync/export` (json, 4 KiB), `GET /api/sync/export`; one export made at a
  time (a module lock); `peer_file.indexes_size(conn) -> int | None` (dbstat when `PRAGMA compile_options` lists
  `ENABLE_DBSTAT_VTAB`).

- [ ] **Step 1: Write the failing tests**:
  - `test_sizes_say_the_librarys_bytes_its_songbooks_and_the_indexes`;
  - `test_an_export_is_made_named_for_the_library_and_the_day_and_sent_once` (`Content-Disposition` has
    `horde_logbook-03-11-26.caracole`; a second GET is 404; nothing left in `cache_dir/peer/`);
  - `test_an_export_needs_the_token_and_the_page_and_refuses_indexes_alone`;
  - `test_a_second_export_while_one_is_made_is_refused`;
  - `test_another_sites_fetch_reads_neither_sizes_nor_the_file` (`own_page_read`).
- [ ] **Step 2: Run them and see them fail.**
- [ ] **Step 3: Implement**, with a docstring route line for each route.
- [ ] **Step 4: Run them**, with `tests/test_web_app.py`. Expected: PASS.
- [ ] **Step 5: Commit** — `feat(serve): Export makes the library's file and sends it once`

### Task 21: The import's routes, and Sync on an import

**Files:**
- Modify: `src/caracole/web/sync_file_routes.py` (open, part, compare), `src/caracole/web/sync_routes.py` (`apply`
  queues `peer import` for an import's comparison), `src/caracole/web/status.py` (`PEER_KINDS["import"] = "sync"`),
  `src/caracole/web/jobs.py` (`_peer_stages` maps `"import"` to `PEER_IMPORT_STAGES`)
- Test: `tests/test_web_sync_files.py`, `tests/test_web_status.py` (one case)

**Interfaces:**
- Consumes: Task 6 (staging), Task 5 (`read_file`, `check_importable`), Task 16 (`Compared(source="import:<id>", kind="file", holds=…)`).
- Produces: §3.4.2's import routes; `apply` on `source.startswith("import:")` queues §3.4.2's command under key
  `import:<file id>`.

- [ ] **Step 1: Write the failing tests**:
  - `test_a_file_sent_in_parts_is_compared_as_a_sync_with_it`;
  - `test_a_part_out_of_order_too_big_or_without_the_token_is_refused`;
  - `test_a_file_refused_says_its_words_and_is_deleted` (OWN 409; OLDER 409; NOT_A_FILE 400);
  - `test_sync_on_an_import_queues_peer_import_of_its_folder_and_its_view_is_a_sync`;
  - `test_two_computers_one_imports_the_others_export_through_the_routes` (end to end, the units equal after);
  - `test_a_staged_import_never_applied_is_swept_an_hour_after`.
- [ ] **Step 2: Run them and see them fail.**
- [ ] **Step 3: Implement.** `apply`'s fresh comparison of an import reads its staged file again, sending no request,
  and refuses 409 `STALE` as a network one does once the library has moved since.
- [ ] **Step 4: Run them**, with `tests/test_web_status.py`, `tests/test_web_jobs.py` and every
  `tests/test_conformance_*.py` in check mode (`nix develop -c pytest -q -n 0 tests/test_conformance_*.py`), then
  `nix develop ./android -c gradle -p android test`. Expected: PASS, no vector moved (a status.py change regenerates
  the corpus in its commit; this one moves no record: no recorded job is an import).
- [ ] **Step 5: Commit** — `feat(serve): Import a file sends it in parts and syncs with it`

### Task 22: The job's report

**Files:**
- Modify: `src/caracole/web/jobs.py` (`Job.report`; `heard` takes `{"event": "report"}`), `src/caracole/web/jobs_routes.py` (`peer_outcome`)
- Test: `tests/test_web_jobs.py`, `tests/test_web_sync.py` (one case)

**Interfaces:**
- Produces: §3.5's `Job.report`, in memory alone; `peer_outcome(job)["report"]` only when present.

- [ ] **Step 1: Write the failing tests**:
  - `test_a_syncs_report_event_is_kept_on_its_job_and_never_in_its_history`;
  - `test_a_syncs_view_carries_its_report_once_over_and_none_while_it_runs`.
- [ ] **Step 2: Run them and see them fail.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run them**, with `tests/test_web_history.py` and `tests/test_conformance_sync_routes.py` (check mode,
  unchanged). Expected: PASS.
- [ ] **Step 5: Commit** — `feat(serve): a sync's view says what it did, for the page's summary`

### Task 23: `peer sync`'s indexes both ways, its report, and the state's kept answers

**Files:**
- Modify:
  - `src/caracole/peer_sync.py`: `Peer.index(to: Path, sites: Sequence[str]) -> None` (`GET /api/peer/index`,
    streamed to a file); `Peer.indexes() -> dict[str, dict]` (`GET /api/sync/indexes`);
  - `src/caracole/peer_import.py`: `class Uploader(peer_push.Pusher)` with `upload(path: Path) -> str` (open, then
    the parts), `compare(import_id: str) -> dict` and `apply(comparison: str, parts: Sequence[str]) -> int`;
  - `src/caracole/commands/peer.py`: the index stage after agree, and the report;
  - `src/caracole/web/jobs.py`: `PEER_SYNC_STAGES` gains index;
  - `src/caracole/web/peer_routes.py`: `state` passes `kept=sync.kept_of(conn, peer)`.
- Test: `tests/test_commands_peer_indexes.py` (new), `tests/test_web_peer.py` (one case)

**Interfaces:**
- Consumes: Task 21's routes on the other side; `index_transfer.export`, `merge`, `newest`, `tab_counts`; `peer_push.wait_for`.
- Produces:
  - `peer sync`'s stage `index`:
    - a site newer there is taken: `Peer.index`, then `merge` with its backup;
    - a site newer here is given: `index_transfer.export` of those sites, `Uploader.upload`, `compare`, then
      `apply(parts=["indexes"])` and `wait_for` its job;
    - each is counted for the report (§3.5);
    - skipped without `"indexes"` in `--parts`, or with nothing newer ("no index is newer on either side");
  - with `--progress`, the report event (`with.kind` `"server"`).

- [ ] **Step 1: Write the failing tests**:
  - `test_a_site_read_more_recently_there_is_taken_and_counted`;
  - `test_a_site_read_more_recently_here_is_given_through_the_others_import_and_counted_there`;
  - `test_nothing_newer_skips_the_index_stage`;
  - `test_the_state_document_gives_the_asker_the_kept_answers_this_side_keeps_for_it`.
- [ ] **Step 2: Run them and see them fail.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run them**, with `tests/test_commands_peer.py` and `tests/test_web_peer.py`. Expected: PASS.
- [ ] **Step 5: Commit** — `feat(peer): a sync gives and takes the indexes whichever side read them later`

### Task 24: The export's and import's corpus, serve's writes, the docs

**Files:**
- Create: `tests/test_conformance_sync_file_routes.py`, `tests/conformance/vectors/web/sync_file_routes.jsonl`
- Modify:
  - AGENTS.md:
    - "#### `serve` never takes it": the export's file in `cache_dir/peer/` (one at a time, deleted once open, or an
      hour after), and the import's staging `state_dir/peer/import-<16 hex>/` (0700, its file 0600, one at a time,
      deleted once its import is over or an hour after its last part);
    - `##### Routes by area`: `sync_file_routes.py`;
  - docs/usage.md: "### Syncing parts, and the indexes" under "## Two caracoles", and the routes under "###
    caracole serve".

**Interfaces:**
- Produces `vectors/web/sync_file_routes.jsonl`: `{fn: "<METHOD> <path>", here: fixture, form | json | parts, status,
  out}` for every route of §3.4.2. Ids are masked (`"<export>"`, `"<import>"`, `"<comparison>"`), and a file's bytes
  come by name from `vectors/sync/files/`. No Kotlin test reads it until sync-phone.

- [ ] **Step 1: Write the generator** (`test_sync_file_routes_jsonl_is_what_the_routes_answer`), check mode, FAIL.
- [ ] **Step 2: Write the vectors.**
- [ ] **Step 3: The gates.** Run:
```
nix develop -c pytest -q -n 0 tests/test_conformance_sync_file_routes.py tests/test_conformance_sync_routes.py
nix develop -c pytest -q tests/test_corpus_budget.py
nix develop -c pytest -q
nix develop ./android -c gradle -p android test
nix build .#checks.x86_64-linux.package
```
Expected: PASS each.
- [ ] **Step 4: Commit** — `test(conformance): the export's and import's routes; docs: serve's new files`

---

## 9. Lane sync-page (mixed): the flow, once, in library_assets

Branch `android/sync-page`. Depends on sync-routes and sync-exchange (the routes the page asks), and requests-tab
(LibraryPage.kt, its test, the library page's corpus in turn). The Chromium tests run with `chromium` on PATH, as the
owner's machine has it: none of them may be skipped (`-rs` shows a skip).

### Task 25: The templates, the laptop's tab bar, and `WebControls.sync`

**Files:**
- Create: `src/caracole/library_assets/sync-sheet.html` (the `<dialog id="sync-sheet">`, its four views `#sync-what`,
  `#sync-conflict`, `#sync-going`, `#sync-done`, and `<template>`s of the side and arrow icons as inline SVG)
- Modify:
  - `src/caracole/library_assets/sync-panel.html`: the three panels, `#sync-address`, `#sync-test`, `#sync-tested`,
    `#sync-last`, `#sync-start`, `#sync-export`, and the label of `<input type="file" id="sync-file"
    accept=".caracole,.sqlite">`;
  - `sync-tab.html`, `body.html` (`__TABREQUESTS____TABSYNC__`), `sync.css` (the split from 720 px:
    `.masthead.lib .tabs #tab-sites { margin-inline-start: auto }`; the sheet, the panels), `tabs.js` (its header's
    words: Sync last, served on the computer), `__init__.py`'s docstring;
  - `src/caracole/library_page.py`: `WebControls.sync: str | None` (`"tab"`, `"sheet"`); `_sync_panel` gives the panel
    and the sheet for `"tab"`, the sheet alone for `"sheet"`; `TEMPLATES` gains `sync-sheet.html`;
  - `src/caracole/web/library_routes.py`: `sync="tab"`;
  - the corpus and the phone's page in the same commit: `tests/test_conformance_library_page.py` (its cases'
    `controls.sync`: `"tab"`, `"sheet"`, None), `tests/conformance/data/caracole/page/library_assets.json`,
    `tests/conformance/vectors/web/library_page.json`, `android/server/src/main/kotlin/io/github/danielhp95/caracole/server/page/LibraryPage.kt`
    (`__TABSYNC__` empty, `__SYNC__` is `sync-sheet.html` when `controls.sync`), `android/server/src/test/kotlin/.../page/LibraryPageTest.kt`
    (`` `the phone's page is the sheet case byte for byte` ``).
- Test: `tests/test_sync_sheet.py` (new; replaces `tests/test_sync_tab.py`, deleted), `tests/test_requests_tab.py`
  (its tab order line), `tests/test_library_assets.py`, `tests/test_web_sync.py`
  (`test_the_library_page_has_the_sync_tab_last`)

- [ ] **Step 1: Write the failing tests**:
  - `test_the_laptops_tab_bar_splits_library_and_songbooks_from_sites_requests_and_sync` (1280 px: the tabs' order
    `["tab-library", "tab-songbooks", "tab-sites", "tab-requests", "tab-sync"]`, and Sites' left edge right of the
    middle);
  - `test_on_a_phone_the_tabs_stay_one_row_unsplit` (390 px);
  - `test_the_phones_page_has_the_sheet_and_no_sync_tab` (`assemble_page(..., sync="sheet")`: no `#tab-sync`, one
    `#sync-sheet`);
  - `test_the_sheet_never_puts_markup_in_from_a_text_and_asks_nothing_of_another_site` (no `innerHTML`,
    `insertAdjacentHTML` or `outerHTML` in sync.js or sync-words.js; every `fetch` to a relative path).
  - In test_requests_tab.py, the order becomes `[..., "tab-sites", "tab-requests", "tab-sync"]  # Sync last`.
- [ ] **Step 2: Run them and see them fail.** Run: `nix develop -c pytest -q -n 0 tests/test_sync_sheet.py tests/test_requests_tab.py tests/test_library_assets.py`
- [ ] **Step 3: Implement**, then regenerate the page's corpus: `CARACOLE_CORPUS=write nix develop -c pytest -q -n 0
  tests/test_conformance_library_page.py`, and make LibraryPage.kt match.
- [ ] **Step 4: Run them**, with `nix develop -c pytest -q -n 0 tests/test_conformance_library_page.py` (check mode)
  and `nix develop ./android -c gradle -p android :server:test`. Expected: PASS.
- [ ] **Step 5: Commit** — `feat(page): the Sync tab last, the tabs split on a wide screen, one sheet for both devices`

**Every later task of this lane that changes a file of library_assets ends as this one does:** the page's corpus
regenerated (`CARACOLE_CORPUS=write … tests/test_conformance_library_page.py`) and `:server:test` passing, in the same
commit as the change (AGENTS.md: the phone agrees with the computer to the byte).

### Task 26: sync-words.js: how two documents differ, each change, the numbers

**Files:**
- Create: `src/caracole/library_assets/sync-words.js` (`window.caracoleSyncWords`: `differ(kind, here, there)`,
  `changed(change, side)`, `sides(device, peer)`, `tabs(n)`, `day(stamp)`, `when(stamp)`), `tests/test_sync_words.py`
- Modify: `src/caracole/library_page.py` (`SCRIPTS`: `sync-words.js` before `sync.js`)

**Interfaces:**
- Consumes: §3.7's tables; the unit documents of `peer_sync.unit_document`.
- Produces: `caracoleSyncWords`, frozen, read by sync.js alone.

- [ ] **Step 1: Write the failing test** (`helpers.browser.dump_dom` of a page that runs the script on fixed
  documents and writes the answers into `data-said`):

```python
def test_two_song_documents_are_told_apart_aspect_by_aspect():
    said = words_of({"kind": "song", "here": doc(version="key=Am&capo=2", pick=("ug", 1234567)),
                     "there": doc(version=None, pick=("ug", 7654321))})
    assert said == [{"what": "Its own key", "here": "A minor, capo 2", "there": "as the sheet's"},
                    {"what": "Its sheet", "here": "Ultimate Guitar · tab 1234567", "there": "Ultimate Guitar · tab 7654321"}]

def test_a_songbooks_set_lists_are_told_apart():  # "Songs added", "Its order", "A song's setting"
def test_each_change_and_number_reads_as_the_owner_reads_it():
    assert said["changed"] == ["added on the phone", "changed on this computer", "removed on the phone"]
    assert said["tabs"] == ["+12,130", "−210", "1,503,236"] and said["day"] == "03/11/26, 19:42"
```
- [ ] **Step 2: Run it and see it fail.**
- [ ] **Step 3: Implement**, `createElement` and `textContent` only (it builds no element: it answers texts).
- [ ] **Step 4: Run it.** Expected: PASS.
- [ ] **Step 5: Commit** — `feat(page): the words of how two versions differ`

### Task 27: The sheet: what to sync, a card for each conflict, Sync

**Files:**
- Modify: `src/caracole/library_assets/sync.js` (rewritten), `sync.css`
- Test: `tests/test_sync_sheet.py` (a `FakeSync` answering §3.4's shapes, `test_web_sync.py`'s shape check pointed at it)

**Interfaces:**
- Consumes: §3.4.1, §3.6, §3.7; `caracoleTabs`, `caracoleLibrary.track`.
- Produces: the sheet's DOM, which Tasks 28–29 and the device tests read:
  - `#sync-sheet[data-view=what|conflict|going|done]`;
  - `input[name=part][value=library|songbooks|indexes]`;
  - `#sync-go`, `#sync-cancel`;
  - `#sync-counts .take|.give|.both`, `#sync-chips li`;
  - `#sync-card`, `#sync-card-here`, `#sync-card-there`, `#sync-keep-here`, `#sync-keep-there`, `#sync-same`.

- [ ] **Step 1: Write the failing tests**:
  - `test_the_sheet_asks_what_to_sync_with_every_part_ticked_and_says_whats_waiting`:
    `#sheet=sync` → "Sync with Studio", three boxes ticked;
    "Songbooks · Your songbooks and their set lists, both ways · 2 changed on Studio";
    "newer on Studio: Ultimate Guitar (read today)";
  - `test_a_conflict_stops_it_card_by_card_with_each_sides_lines_and_the_sides_named`
    (laptop: "This computer" and "Studio"; phone, `device: "phone"`: "Phone" and "Computer"; "1 of 2");
  - `test_same_for_the_other_n_settles_every_conflict_left_and_sync_posts_one_field_of_choices`
    (`POST /sync/apply`: `choices` `"here\tsong/…\nhere\tsong/…"`, `parts` "library,songbooks,indexes");
  - `test_cancel_on_a_card_queues_nothing` (the fake's `applied == []`, the sheet closed);
  - `test_unticked_parts_are_sent_and_their_differences_counted_out` (the counts row's numbers move; `parts` "library");
  - `test_a_refusal_says_the_servers_words_and_compares_again` (409 STALE → a comparison afresh).
- [ ] **Step 2: Run them and see them fail.**
- [ ] **Step 3: Implement.** The sheet compares as it opens (`POST /sync/compare` for an address,
  `/sync/import/compare` for a file). A card asks `GET /api/sync/unit` once for its unit. Escape is Cancel before
  Sync and Done after it.
- [ ] **Step 4: Run them.** Expected: PASS.
- [ ] **Step 5: Commit** — `feat(page): what to sync, a card for each conflict, then Sync`

### Task 28: Following the sync, and its summary

**Files:**
- Modify: `sync.js`, `sync.css`
- Test: `tests/test_sync_sheet.py`

**Interfaces:**
- Consumes: §3.5 (the view's `outcome.report`), the comparison and choices the sheet holds.
- Produces: `#sync-done` with `.sync-section[data-kind=taken|given|conflicts|songbooks|indexes]`, each a
  `button[aria-expanded=false]` with its count, its rows in a list it opens.

- [ ] **Step 1: Write the failing tests**:
  - `test_the_summary_draws_each_kind_of_change_closed_and_opens_on_its_chevron` (the five sections' titles of
    §3.7, "Synced with: Studio", "03/11/26, 19:42"; the name the only bold text: `getComputedStyle` weight ≥ 600 on
    it alone);
  - `test_an_index_that_fell_is_red_and_says_why` ("LaCuerda · −210 tabs" and "its listings no longer name them, so
    they would not have opened");
  - `test_a_sync_on_its_way_as_the_page_loads_is_followed_to_its_summary` (`server.jobs` holds the sync's running
    view; no `POST` sent; the summary at its end);
  - `test_a_report_missing_draws_the_summary_from_the_outcome_alone`;
  - `test_the_sheet_fits_a_phone_and_a_laptop_in_light_and_dark` (390 and 1280; no sideways scroll; every control
    44 px on touch: `helpers.targets.small_targets`).
- [ ] **Step 2: Run them and see them fail.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run them.** Expected: PASS.
- [ ] **Step 5: Commit** — `feat(page): what a sync did, as a picture with its details a tap away`

### Task 29: Export and import in the sheet

**Files:**
- Modify: `sync.js`
- Test: `tests/test_sync_sheet.py`

**Interfaces:**
- Consumes: §3.4.2.
- Produces: `#sheet=export` and `#sheet=import`; the export's download link `a[download][href^="api/sync/export?export="]`.

- [ ] **Step 1: Write the failing tests**:
  - `test_export_offers_the_parts_with_their_sizes_indexes_unticked_and_downloads_the_file`
    ("Library · Your songs, their sheets and pages · 34 MB"; Site indexes unticked; `POST /sync/export {"parts":
    ["library", "songbooks"]}`; the link clicked);
  - `test_import_sends_the_file_in_parts_then_syncs_as_with_a_file_with_no_arrow_out`
    (a 20 MiB file → three parts at 0, 8 MiB and 16 MiB; "Sync with a file from Phone"; Site indexes greyed "Not in
    this file"; the summary has no given section, and the file's note);
  - `test_a_file_refused_says_its_words` (OLDER's words shown);
  - `test_the_phones_settings_open_the_sheet_at_export_and_import_by_its_address`.
- [ ] **Step 2: Run them and see them fail.**
- [ ] **Step 3: Implement.** Blob.slice per part and one part in flight.
- [ ] **Step 4: Run them.** Expected: PASS.
- [ ] **Step 5: Commit** — `feat(page): export a library, and import a file as a sync with it`

### Task 30: The docs, and the whole lane's gates on the JVM and the device

**Files:**
- Modify: docs/usage.md ("### The Sync tab", rewritten); AGENTS.md ("##### Songs gone, and the page's tabs": Sync
  last, served on the computer; a new "##### The Sync tab and its sheet": one flow, `#sheet=`, the parts, the
  conflict cards, the summary, export and import)

- [ ] **Step 1: Check the corpus is the last commit's.** Run: `nix develop -c pytest -q -n 0 tests/test_conformance_library_page.py` (check mode). Expected: PASS.
- [ ] **Step 2: Write the docs.**
- [ ] **Step 3: The gates.** Run:
```
nix develop -c pytest -q -n 0 tests/test_conformance_library_page.py
nix develop -c pytest -q -n 0 -rs tests/test_sync_sheet.py tests/test_sync_words.py tests/test_requests_tab.py
nix develop -c pytest -q tests/test_corpus_budget.py
nix develop -c pytest -q
nix develop ./android -c gradle -p android test
nix build .#checks.x86_64-linux.package
ANDROID_AVD_HOME=/home/dani/.config/.android/avd QT_QPA_PLATFORM=xcb android/scripts/device-test.sh io.github.danielhp95.caracole.CorpusOnDeviceTest
```
Expected: PASS each, no skip in the second run.
- [ ] **Step 4: Commit** — `feat(page): one sync flow on both devices; the phone's page in lockstep`

---

## 10. Lane sync-phone (kotlin): a file's pages, the phone's export and import, the wiring

Branch `android/sync-phone`. Depends on sync-core, sync-routes and sync-exchange
(`vectors/web/sync_file_routes.jsonl`), and lookup-routes (MirrorPageData.kt in turn). library-cards follows it.

### Task 31: A file's pages as a layer of the mirror

**Files:**
- Create: `android/mirror/src/main/kotlin/io/github/danielhp95/caracole/mirror/Layers.kt`, `android/mirror/src/test/kotlin/io/github/danielhp95/caracole/mirror/LayersTest.kt`
- Modify: `mirror/Mirror.kt` (`layers()`, `takeLayer`, `pageFor`)

**Interfaces:**
- Produces:
  - `class Layer(val id: String, val dir: File)` with `manifest(): Manifest?`, `lookup(path): Served?`;
  - `fun Mirror.layers(): List<Layer>`, those under `dir/layers/<16 hex>/`, the newest taken first;
  - `fun Mirror.takeLayer(id: String, manifest: ByteArray, units: Set<String>, blob: (String) -> InputStream?)`:
    keeps the entries of `units` and the start page, writes their blobs (checked by SHA-256), then swaps its
    manifest and deletes the blobs no longer named;
  - `pageFor(path, gate)`: the computer's entry when the gate says SERVE; else the first layer whose entry at that
    path the gate says SERVE; else the computer's answer (Gated or Missing);
  - `cleanUp` never touches a layer.

- [ ] **Step 1: Write the failing tests**:
  - `` `a page the phone took from a file is served from its layer once the computer's is changed` ``;
  - `` `a layer keeps only the pages of the units taken and the file's start page` ``;
  - `` `a blob whose bytes aren't its name leaves the layer as it was` ``;
  - `` `the computer's mirror sync never deletes a layer's blobs` ``.
- [ ] **Step 2: Run them and see them fail.** Run: `nix develop ./android -c gradle -p android :mirror:test --tests '*LayersTest'`.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run `:mirror:test`.** Expected: PASS.
- [ ] **Step 5: Commit** — `feat(android): a file's pages beside the computer's, each song's from the side it came from`

### Task 32: The library page's cards of a file's songs

**Files:**
- Modify: `android/server/src/main/kotlin/io/github/danielhp95/caracole/server/page/MirrorPageData.kt`, `android/server/src/test/kotlin/.../page/MirrorPageDataTest.kt`

**Interfaces:**
- Consumes: Task 31's `layers()`.
- Produces: a song with no card in the computer's page data takes the card of the newest layer whose start page holds
  its identity (re-identified as the computer's are). Else it gets the minimal card, as now.

- [ ] **Step 1: Write the failing test** `` `a song taken from a file has the file's card, with its sheet's link` ``.
- [ ] **Step 2: Run it and see it fail.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run `:server:test --tests '*MirrorPageDataTest'`.** Expected: PASS.
- [ ] **Step 5: Commit** — `feat(android): a song from a file opens its sheet on the phone`

### Task 33: The phone's export and import routes

**Files:**
- Create: `server/routes/SyncFileRoutes.kt`, `server/routes/sync/Imports.kt` (staging, §3.4.2's words, in
  `stateDir/peer/import-<id>/`), `server/routes/sync/Exports.kt` (made in `stateDir/cache/peer/`, deleted once open),
  `server/routes/sync/MirrorPages.kt` (a `PageSource` over the mirror and its layers), `server/routes/SyncFileRoutesTest.kt`
- Modify: testFixtures `server/testing/replays/WebReplay.kt` (sync_file_routes.jsonl)

**Interfaces:**
- Consumes: Tasks 11, 13, 31; `vectors/web/sync_file_routes.jsonl`.
- Produces: §3.4.2's six routes on the phone; the import's job (key `import:<file id>`, kind `sync`, `FILE_STAGES`,
  the engine's `pagesFromFile` writing `takeLayer`).

- [ ] **Step 1: Write the failing tests**:
  - `` `every record of sync file routes jsonl replays` ``;
  - `` `an upload cut short is never compared, and is swept an hour after` ``;
  - `` `an export is sent once and leaves nothing in the cache` ``.
- [ ] **Step 2: Run them and see them fail.**
- [ ] **Step 3: Implement.** `Body.FromFile` streams the export, and parts are written with `RandomAccessFile` at `at`.
- [ ] **Step 4: Run `:server:test`.** Expected: PASS.
- [ ] **Step 5: Commit** — `feat(android): Export and Import a file on the phone`

### Task 34: The wiring

**Files:**
- Modify: `android/server/src/main/kotlin/io/github/danielhp95/caracole/server/Assembly.kt` (SyncFileRoutes after
  SyncRoutes; `val sync: SyncRoutes` public; the engine's `pagesFromFile` and the export's `PageSource` over
  `deps.mirror`), `AssemblyTest.kt`
- Modify: AGENTS.md (`##### Syncing on the phone`: a file's layers, Export and Import a file)

- [ ] **Step 1: Write the failing test.** Extend `AssemblyTest`'s list of the modules' order and its check that each
  route has one module.
- [ ] **Step 2: Run it and see it fail.**
- [ ] **Step 3: Wire.**
- [ ] **Step 4: The gates.** Run:
```
nix develop ./android -c gradle -p android test
nix develop -c pytest -q
ANDROID_AVD_HOME=/home/dani/.config/.android/avd QT_QPA_PLATFORM=xcb android/scripts/device-test.sh io.github.danielhp95.caracole.CorpusOnDeviceTest
CARACOLE_ANDROID_E2E=1 nix develop -c pytest -q -n 0 tests/test_android_e2e.py
```
Expected: PASS each.
- [ ] **Step 5: Commit** — `feat(android): the phone's sync, export and import wired`

---

## 11. Lane sync-app (kotlin, device): the button, files, Settings, the unattended sync

Branch `android/sync-app`. Depends on sync-phone, sync-page and lookup-routes (which owns Caracole.kt, SyncService.kt
and Working.kt: never touched here).

### Task 35: The bar's sync button, the menu, and the sheet's intents

**Files:**
- Modify:
  - `android/app/src/main/kotlin/io/github/danielhp95/caracole/MainActivity.kt`: `showSheet(name)`, which loads
    `links.address("") + "#sheet=" + name` and asks to notify; `onNewIntent` reads the extra `SHEET`; the menu has
    Library and Settings; `showSyncTab` and `SYNC_TAB` go;
  - `res/layout/activity_main.xml`: an `ImageButton` `@+id/sync` left of `@+id/more`, `contentDescription`
    `@string/sync`;
  - `res/menu/main.xml`: `sync_now` and `sync_tab` go;
  - `res/values/strings.xml`: `sync` = "Sync"; `sync_now` and `sync_with_computer` go;
- Create: `res/drawable/ic_sync.xml` (circular arrows, 24 dp, `@color/on_bar`), `app/.../SheetAddress.kt`
- Test: `android/app/src/test/kotlin/.../SheetAddressTest.kt` (the address for each sheet)

**Interfaces:**
- Produces: `MainActivity.SHEET = "sheet"` (an intent extra: `"sync"`, `"export"`, `"import"`); `object SheetAddress
  { fun of(library: String, sheet: String): String }`.

- [ ] **Step 1: Write the failing test** `` `each sheet's address is the library page's with its word` ``:
  `SheetAddress.of("http://127.0.0.1:8738/", "export") == "http://127.0.0.1:8738/#sheet=export"`; an unknown word
  gives the library page alone.
- [ ] **Step 2: Run it and see it fail.** Run: `nix develop ./android -c gradle -p android :app:testDebugUnitTest --tests '*SheetAddressTest'`.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run `:app:testDebugUnitTest`.** Expected: PASS.
- [ ] **Step 5: Commit** — `feat(android): one sync button in the app's bar`

### Task 36: The WebView's file chooser and downloads

**Files:**
- Create: `app/.../FileChooser.kt` (`onShowFileChooser`: `ACTION_OPEN_DOCUMENT`, type `*/*`, the result handed
  back), `app/.../Exports.kt` (an export link read in-process, as LocalFiles reads a file, copied to
  `cacheDir/exports/<name>`, then `ACTION_SEND` through a chooser, type `application/zip`)
- Modify: `MainActivity.kt` (the chrome client's `onShowFileChooser`; the download listener sends an export to
  `Exports`, before `follow`), `res/xml/file_paths.xml` (`<cache-path name="exports" path="exports/" />`)
- Test: `app/.../ExportsTest.kt`

**Interfaces:**
- Produces:
  - `object Exports { fun isExport(url: String, origin: String): Boolean; fun nameOf(disposition: String?): String; suspend fun share(activity: Activity, files: LocalFiles, url: String, disposition: String?) }`;
  - `class FileChooser(activity: Activity)` with `open(callback: ValueCallback<Array<Uri>>, params)` and
    `result(requestCode, resultCode, data)`.

- [ ] **Step 1: Write the failing tests**:
  - `` `an export's link is told from any other download` ``;
  - `` `the shared file is named as the server's attachment names it` ``
    (`nameOf("attachment; filename=\"horde_logbook-03-11-26.caracole\"") == "horde_logbook-03-11-26.caracole"`,
    and `filename*=UTF-8''` read first);
  - `` `a name with a path in it is cut to its last part` ``.
- [ ] **Step 2: Run them and see them fail.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run `:app:testDebugUnitTest`.** Expected: PASS.
- [ ] **Step 5: Commit** — `feat(android): the page's file input and its export reach Android's picker and share sheet`

### Task 37: Settings

**Files:**
- Modify:
  - `SettingsActivity.kt`: Test calls `Caracole.phone(this).sync.tested(address)` on IO and shows `said`, or the
    refusal's words; Export and Import a file start MainActivity with `SHEET`; Sync now, the last sync line, Import
    indexes and its two buttons, last import and hint go; the Backups row stays;
  - `res/layout/activity_settings.xml`: its sync rows;
  - `res/values/strings.xml`: `export` = "Export", `export_hint` = "This library in one file: to share with another
    caracole, or to keep", `import_file_row` = "Import a file", `import_file_hint` = "A file another caracole
    exported: synced as if it were here"; the import strings go;
  - `Settings.kt`: `lastImport` goes; `lastOutcome` stays, for the unattended sync.
- Test: `app/.../SyncSettingsTest.kt` (rewritten)

- [ ] **Step 1: Write the failing test** `` `no settings item text ends in an ellipsis` ``: every `android:text` of
  activity_settings.xml and menu/main.xml, resolved, has no trailing "…".
- [ ] **Step 2: Run it and see it fail** (it fails on the old rows).
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run `:app:testDebugUnitTest`.** Expected: PASS.
- [ ] **Step 5: Commit** — `feat(android): Settings keep the address and Test, and gain Export and Import a file`

### Task 38: The unattended sync and its notification

**Files:**
- Modify: `Syncs.kt` (`run(context, probe)`: `phone.sync.alone(address)`, `queue.await`, the outcome's
  conflicts left; `onWifi` unchanged; `now` goes)
- Create: `Notifications.kt` (the `jobs` channel moved out of IndexImports.kt, the same API, and `syncs`)
- Delete: `IndexImports.kt`, `app/src/test/.../IndexImportsTest.kt`
- Modify: `res/values/strings.xml` (`syncs_channel` = "Syncs"; `conflicts_left` plurals as §3.7, "N songs changed on
  both sides: tap to choose", or "N changes on both sides: tap to choose" when not all are songs)
- Test: `app/.../SyncsTest.kt`

**Interfaces:**
- Consumes: Task 18's `SyncRoutes.alone`; Task 34's `Phone.sync`; `JobQueue.await`.
- Produces: `Syncs.conflictsLeft(outcome: JsonObject): Pair<Int, Boolean>` (how many, whether all are songs); the
  notification's tap starts MainActivity with `SHEET` `"sync"`.

- [ ] **Step 1: Write the failing tests**:
  - `` `the conflicts left are counted from the outcome, and only conflicts count` ``;
  - `` `the probe of a Wi-Fi sync with nothing answering does nothing and says nothing` `` (`Syncs.run` with a
    `ServerAddress` nothing answers → null, `Caracole.status` Idle);
  - `` `a sync with no conflict left posts no notification` ``.
- [ ] **Step 2: Run them and see them fail.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run `:app:testDebugUnitTest`.** Expected: PASS.
- [ ] **Step 5: Commit** — `feat(android): Sync on Wi-Fi is this sync, unattended, and tells of each conflict it left`

### Task 39: On the device, and the README

**Files:**
- Create: `android/app/src/androidTest/kotlin/io/github/danielhp95/caracole/SyncSheetTest.kt`, `ExportImportTest.kt`
- Delete: `SyncTabTest.kt`
- Modify: `EndToEndTest.kt`, `PinchTest.kt` (their menu lines: the bar's button), `android/README.md` ("## Sync from
  the phone", rewritten: the button, the sheet, Settings' Export and Import a file, Sync on Wi-Fi)

- [ ] **Step 1: Write the device tests** (against the e2e computer):
  - `SyncSheetTest`:
    - `` `the bar's button opens the sheet, a conflict's card names Phone and Computer, and the summary shows what it did` ``;
    - `` `the notification of a sync that left a conflict opens the sheet at its card` ``;
  - `ExportImportTest` (Espresso-Intents):
    - `` `Settings' Export opens the sheet and its file goes to the share sheet` `` (`intended(hasAction(ACTION_CHOOSER))`,
      the shared URI's bytes a zip whose first member is `caracole.json`);
    - `` `Import a file picks through Android's picker and syncs with the file` `` (`intending(hasAction(ACTION_OPEN_DOCUMENT))`
      answered with a fixture copied to the app's cache, then the summary).
- [ ] **Step 2: Run them.** Run: `ANDROID_AVD_HOME=/home/dani/.config/.android/avd QT_QPA_PLATFORM=xcb android/scripts/device-test.sh --computer "$(mktemp -d)" io.github.danielhp95.caracole.SyncSheetTest io.github.danielhp95.caracole.ExportImportTest io.github.danielhp95.caracole.EndToEndTest io.github.danielhp95.caracole.PinchTest io.github.danielhp95.caracole.CorpusOnDeviceTest`. Expected: PASS each.
- [ ] **Step 3: The gates.** Run:
```
nix develop ./android -c gradle -p android test assembleDebug assembleDebugAndroidTest
nix develop -c pytest -q
CARACOLE_ANDROID_E2E=1 nix develop -c pytest -q -n 0 tests/test_android_e2e.py
nix flake check
```
Expected: PASS each.
- [ ] **Step 4: Commit** — `test(android): the sync button, export and import on the emulator; docs: syncing from the phone`

---

## 12. Self-review

**Spec coverage.**

| Spec | Task |
|---|---|
| One sync button on the phone; four old entries gone | 35, 37, 38 |
| Phone tabs, no Sync tab; laptop split Library, Songbooks / Sites, Requests, Sync | 25 |
| Laptop's three panels, Test, last sync | 15, 25 |
| Settings: address + Test; Export; Import a file; no "…" | 37 |
| Sync on Wi-Fi: this sync, unattended, conflicts left, notification | 12, 18, 38 |
| Step 1: three parts, what's waiting, songbook's songs come along | 2, 12, 16, 27 |
| Step 2: one card per conflict, sides named, how they differ, Same for the other N, no Skip, counts, chips | 16, 26, 27 |
| Step 3: the summary as a picture, sections, index tabs before/after | 14, 22, 23, 26, 28 |
| Export sheet, sizes, Site indexes unticked, file name, download / share sheet | 20, 29, 33, 36 |
| Import: picker, same sheet, Not in this file, no arrows out | 21, 29, 33, 36 |
| Agreement after an import; the remembered "keep mine" | 1, 7, 13 |
| Older file refused; own export refused | 5, 7, 13 |
| The file: state, units, files by SHA-256, pages, indexes, manifest | 4, 5, 11 |
| A file's pages beside the mirror on the phone | 31, 32, 34 |
| Share everything, recorded in AGENTS.md | 9 |
| `peer export`, `peer import`; diff, pull, sync keep working | 7, 8 |
| Same code on both devices | 25–30 (one flow), 19 and 24 (one JSON) |
| Removing what this replaces, with docs | 25 (Sync tab test), 35, 37, 38, 39 (app), 9/19/24/30/39 (docs) |

**Step scan.** Each step names its file, signature, values and test. Bodies appear only for exact copy (§3's words).

**Type consistency.** The pairs that cross lanes, checked:
- `KeptPair` is (here, there, chooser) in 1, 10 and 12;
- `in_scope(found, parts, *, listed, holds)` matches `Scope.inScope(found, parts, listed, holds)`;
- `export_file` matches `SyncFiles.export`;
- `Comparison`'s members are the routes' JSON;
- `SyncRoutes.alone`/`tested` are the ones Tasks 37–38 call;
- `Mirror.takeLayer` is called by Task 33's `pagesFromFile`.

**Review Focus.** Each of the five lines has its test in its owning task.

**Proportion.** About 18,000 lines of code and tests, planned in 39 tasks. The plan holds signatures, tests and the
spec's words, and no bodies but §3's contracts.

## 13. Questions for the owner (the defaults taken)

1. **The phone's tabs.** M4's lane requests-tab brings the Requests tab to the phone, so its tabs become Library,
   Songbooks, Sites, Requests, unsplit, with no Sync tab. Default: that. The spec said "stay Library, Songbooks,
   Sites" before Requests came to the phone.
2. **Import a file from Settings takes one more tap.** A page can't open the file picker without a tap of its own,
   and there is no JavaScript bridge, so Settings opens the sheet and its Choose a file opens the picker. Default:
   that. The alternative is Settings opening the picker itself and the app sending the file to its own server.
3. **A file's pages on the phone after M5.** Default: the songs taken from a file are served from the file's layer
   until the phone changes them, and phone-render renders only what no layer serves.
4. **Giving indexes from the laptop to a server** sends the whole of each newer site (hundreds of MB) in 8 MiB parts,
   as an index-only import there. Default: yes. The alternative is that the laptop only takes indexes.
5. **"Keep mine" at an import, then a network sync with that caracole:** the kept version goes to the other side
   without asking. Default: yes, it is the answer given.
6. **Songbooks alone bring the songs every songbook lists** on either side, not only those of the songbooks that
   changed. Default: every listed song.
7. **The unattended sync's notification** has a channel of its own, "Syncs", beside M6's "alerts". Default: yes.
8. **Test's words and dates:** "studio answered: 96 songs, 3 songbooks, its indexes read 02/11/26", dates `dd/mm/yy`
   in the device's zone. Default: that.
9. **Sharing the export on Android:** the file is shared as `application/zip` with its `.caracole` name, so most
   targets take it. Default: that.

## Execution

Each lane runs as the M4–6 plan's §7.0 says: its worktree and branch, the tasks in order (subagent-driven: a fresh
implementer per task and a reviewer after each), a review and fix pass, then a `--no-ff` merge once its done_when
holds with main merged in.
