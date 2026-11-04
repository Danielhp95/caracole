# caracole on Android in Kotlin: milestones 4–6, the implementation plan

Status: the plan for this round, written from what milestones 1–3 taught (the findings of 2026-11-03 and the 21 lane
groups' reports), revised after two critics' reads (§13 says what each found and how it is settled). The skeleton step commits it as `docs/superpowers/plans/2026-11-03-android-port-m4-m6.md`, and
every lane brief points here.

It follows the plan milestones 1–3 were built from,
[2026-11-03-android-port-m1-m3.md](2026-11-03-android-port-m1-m3.md): the same lane model (worktrees, Phase A and B,
`--no-ff` merges), the same corpus rules ([the corpus spec](../specs/2026-11-03-conformance-corpus.md), amended here)
and the same section numbering. What is new is marked so. The plan to share is
[docs/android_port.md](../../android_port.md), whose "Built: milestones 1 to 3" section says where M4 starts.

**The owner's answers of 2026-11-03, which win over this plan wherever the two differ:**
- **Politeness across two devices is not built** ("Don't share between devices", then "Don't do the polite request
  across 2 devices"). Each caracole keeps its own limits, request counts, cooldowns and the kv records that gate
  requests entirely to itself, and nothing of them crosses at a sync. So §4.1 (schema 16, `events.origin`,
  `answered_any`'s origin), §4.2 (the health document and its merge rules) and §4.4's health parts (`health` in
  `GET /api/peer/state`, `POST /peer/health`, `caracole peer health --take` and its job kind, the phone's
  `Politeness.merge` and its health push in the agree stage) are dropped, and Q3 and Q16 are moot. The schema stays
  15. What stays of §4: §4.3's settings (computer to phone, kept as `phone:settings`) and §4.4's index push
  (`POST /peer/index`, `caracole index merge --delete --progress`). Lanes crossing-computer and crossing-phone keep
  only the settings document and `PhoneConfig.take`; any brief that reads or writes the health document,
  `events.origin` or schema 16 drops that part. The spec, `../specs/2026-11-03-politeness-crossing.md`, says what is
  left. Two caracoles at one address may together send more than either one's limits.
- **Wait times divided by 4** ("reduce by a factor of 4 the wait times"): done on main before this round
  (`config.DEFAULT_PROVIDERS`' `delay` and `lookup_delay`, `commands/icons.py`'s `ICON_POLICY`, yt-dlp's own
  sleeps). Budgets, limits and every other rule are unchanged; the phone reads the new values from
  `data/caracole/config/config.json`.
- **Q2, UG's volatile raw**: "Don't count them for the sync": a sync FORMAT 3 whose digests hash a version's raw
  without UG's ratings and votes, bumped once, in lane sync-core (the sync redesign's), Python's and Kotlin's sides in
  one commit. No other lane bumps FORMAT; until sync-core merges, FORMAT 2 holds.
- Every other open question (§11): the plan's own default. Not built this round: the library lines' instrument
  buttons, sharing a music app's link.

Contents:
1. Scope and decisions
2. Architecture
3. The conformance corpus in M4–6
4. Politeness across two caracoles (schema 16, the health document, settings)
5. Interfaces (Kotlin, HTTP, the app's hooks)
6. The skeleton, in two steps
7. The lanes (7.0 how a lane works, 7.1 each lane)
8. Order
9. Milestone checks and integration
10. Risks
11. Open questions
12. Lessons applied
13. The critics' issues, and how this plan settles them

---

## 1. Scope and decisions

This round is milestones 4–6 of docs/android_port.md:

4. **Lookups on the phone.** The phone looks songs up itself, at the lookup pace only, as `caracole get`,
   `versions --keep` and `--keep-more`, `lacuerda --artist` and `--search` and `harptabs --artist` do on the
   computer. Providers: Ultimate Guitar (sheet, kept versions, bare-id tabs through artist pages), LRCLIB, Megalobiz
   (its per-day limit), AZLyrics, LaCuerda (sheets, an artist's page, its own search with its gate), gtptabs.com (a
   song's Guitar Pro file), harptabs.com (a song's tab, an artist's page), gametabs.net (a song's tab), MuseScore
   (links from the index only). Two caracoles keep their own HTTP caches and pace their own requests; their request
   counts, cooldowns and the records that gate requests cross at every sync, both ways. The phone takes the
   computer's provider switches and lookup settings at a sync. The Requests tab comes to the phone. **Goal:** a song
   found and added on the phone is looked up there and shows its sheet as text; a block met on one side cools the
   other from the next sync.
5. **The page builder.** The phone builds a song's pages itself (sheet.html, version-<tab>.html, harmonica-N.html,
   a songbook's page) exactly as render.py and viewer/ build them for the same inputs, and the library page's cards
   from its own library. PDFs are not ChordPro's on the phone. **Goal:** a song looked up on the phone plays as on
   the computer, byte for byte for the same inputs.
6. **Songbooks, sheet versions, PDFs, alphaTab and the rest.** Songbooks made and edited on the phone, sheet versions
   (Keep it, Make this the one, Make this my version), PDFs by Android's print framework, alphaTab's bundle as an
   asset for the Guitar Pro page, review of an uncertain match, files shared to the app filed as `_inbox/` files them,
   alerts as Android notifications, backups. **Goal:** every one of these on the phone, synced to the computer as
   units.

Never on the phone: bulk work (no nightly run, no sitemaps, no index builds, no artist-page or game-page passes beyond
what one lookup does), yt-dlp or YouTube, auto-chords, Music/ scanning, the to-do page.

Not built in this round, by the owner's decision (§12 names their files so no lane invests in them):
- the sync flow's redesign (one sync button, conflict cards, the summary);
- the library lines' instrument buttons;
- sharing a music-app link to the app (ACTION_SEND text/plain);
- the laptop relay for Fetch now.

### The owner's decisions (settled)

- Same architecture as milestones 1–3: native Kotlin; the phone's local server on 127.0.0.1 behind the launch
  cookie; caracole's own pages and library_assets reused byte for byte; byte agreement held by the corpus.
- Every Politeness and "Errors are never misses" invariant of AGENTS.md holds on the phone, with caracole's own user
  agent: lookup_requests per song, lookup_per_hour, lookup_delay, `get.SHEETS_SHARE`, the per-provider pause,
  robots.txt, the cache, cooldowns, blocks.
- Request counts (events), cooldowns and the kv records that gate requests (LaCuerda's search, Megalobiz's day,
  `http:last_request`, the 30-day checked records) cross at every sync, both ways.
- Computer-side changes go through the same rules: sync unit kinds, a sync FORMAT bump if units change, migrations
  through db.py.
- The small fixes of the findings go in an early lane.

### The planner's decisions

Each is open to the owner; those that most need the owner are §11.

| Decision | Choice | Why |
|---|---|---|
| HTML parsing | A pure-Kotlin HTML5 parser, `core.html`, in two lanes (tokenizer, then tree): the WHATWG tokenizer whole (character references by the HTML5 entity table, Python's `html.entities.html5`, which skeleton-m4 writes as data), the tree builder's insertion modes caracole's pages reach (initial to after-after-body, the in-table family, the adoption agency; foreign content as the spec builds it, self-closing tags acknowledged and the breakout tags honoured; templates' contents as ordinary children, as selectolax shows them), and selectolax/lexbor's own text and selector semantics (§5.1, spec `2026-11-03-html-parsing.md`). Held by vectors Python writes by driving selectolax over every fixture, every helper-built page, an edge set and a seeded mutation set, on the JVM and on the device | jsoup (probed, 1.15.3) differs from lexbor on CR, legacy entities, `<br>`, script text, quirks mode and id case. lexbor through the NDK is exact by construction but needs the NDK, CMake, JNI and a host build in two flakes; nu.validator's htmlparser is a pure-Java WHATWG builder the tokenizer lane times first (§11, Q1) |
| Events crossing | Schema 16: `events.origin` (the other caracole's sync id, NULL for this side's own) and `events.origin_id`, with a unique partial index. `health.answered_any` counts this side's own events alone; every other counter counts both. The skeleton makes the bump on both sides | A second sync must not count a request twice; a run id can collide across two databases |
| What crosses, and how | A **health document** (format 1), never a unit (FORMAT stays 2): cooldowns, `http:last_request`, this side's own events of the gating window, the global gating kv, the per-song checked records keyed by identity key, and each song's checks (`ug_checked_at` with its `ug_dirty`, `lacuerda_checked_at`), which no unit's digest holds (§4). Computer to phone: the state document's `health` member. Phone to computer: `POST /peer/health`, staged, taken by a queued `caracole peer health --take` | Politeness is merged, never chosen; a merge never changes a unit's digest (a test on both sides) |
| Settings | The state document's `settings` member (computer to phone only): each provider's `enabled` and lookup settings, `per_day`, `[match]`, `[rank]`, `user_agent` and the library's `name`, kept as kv `phone:settings` | Match decisions are in the song unit's digest, so the phone must match with the computer's thresholds |
| User agent | The computer's `user_agent` (caracole.toml, else `config.DEFAULT_USER_AGENT`), taken at a sync; the default before the first | Sites see caracole's own user agent, never `caracole-android/x` |
| HTTP stack | `core.http.RealTransport`: `java.net.HttpURLConnection`, no redirect followed (`PoliteClient` follows them by hand), exactly httpx's request headers, gzip and deflate decoded by caracole, 30 s timeouts | No new dependency; plain JVM |
| The HTTP cache | `stateDir/cache/http/<provider>/`, the layout of http.py, never Android's `context.cacheDir`, out of auto-backup | "Cached forever" is an invariant, and Android purges cacheDir |
| No live request from a test | `RealTransport` refuses any host but loopback and the emulator's `10.0.2.2` while the system property `caracole.network` is `loopback`: every Gradle `Test` task sets it, and so does the app's instrumentation runner, `CaracoleTestRunner` (skeleton-m4), before `Application.onCreate`, which also makes `Caracole.sitesForTests` a transport that refuses every site unless a test sets another. `PhoneDeps.transport` has no default and is read on every request. `PhoneDeps.searchesLacuerda` (false under the runner) is the computer's `WebApp(searches_lacuerda=False)`. The e2e and the device's lookup tests route sites through `RoutedTransport` to the fake sites server | AGENTS.md: never a live request; PhoneEndToEndTest's Get it becomes a real lookup in M4 |
| One worker | The phone keeps one job worker: a lookup queued behind an index import or a sync waits for it. A long job of the phone's own (the render job of M5) yields between songs through `JobContext.yieldToQueued()`, which runs the lookups queued meanwhile | The phone has no handoff; one writer is the lock (§11, Q4) |
| Jobs are command lines | A `JobSpec` carries Python's command lines as data, `Command(label, args)`, spelled exactly as web/jobs.py spells them; in-process `CommandRunner`s run them by `args[0]` | Try again, the history across a restart, `_pick`, `_as_much` and `_join` all read them |
| The request history | `stateDir/requests.jsonl`, history.py's format 1 and rules (100 kept, 30 days) | The Requests tab is caracole serve's |
| Words | Python's words verbatim ("the nightly run tries again" is true once synced). status.py's to-do link becomes a parameter, `todo=None` on the phone; get.py gains the words of a caracole with no PDFs (`NO_PDFS`, `PAGES_MADE`); the skeleton writes the computer's job kinds of `peer health` and `index merge --delete`; every one recorded in the corpus. The phone's own kinds (render, inbox, backup, restore) have words of their own in one table (§5.3's `PhoneKinds`), recorded in AGENTS.md as the phone's | Never fork Python's words on the Kotlin side alone (§11, Q5) |
| UG's volatile raw | FORMAT 2 unchanged: a tab fetched on both sides between two syncs may show a conflict. The M4 check counts them on the e2e | A projection is a FORMAT 3 bump for a rare case (§11, Q2) |
| The phone's index to the computer | In M4: the pages the phone's lookups stored (UG's artist pages, LaCuerda's artist pages and search rows, harptabs.com's artist pages), each noted by `core.index.Reads` as it is stored, sent since the last successful push to that computer, exported by Kotlin as index_transfer.export(pages=) does, `POST /peer/index`, a queued `caracole index merge`. A time window would lose rows: UG's stamp moves with the computer's nightly refresh, and LaCuerda's rows hold no time | docs/android_port.md deferred it to M4 |
| Lookups on mobile data | Allowed | (§11, Q6) |
| Alerts | Android notifications on their own channel, `alerts`: a block a phone lookup met (one a cooldown), and a job that failed while the app was in the background (`Alerts.failed`, wired by the skeleton through `JobQueue.onEnd`). On the computer a lookup sends none; on the phone it does, since the phone has no nightly run to tell (AGENTS.md says so). The computer's ntfy is unchanged | The owner asked for alerts; on the phone a lookup is the only thing that meets a site (§11, Q13) |
| The page builder's module | A new plain-JVM module, `:viewer` (`api(project(":core"))`), with its own assets copied byte for byte from `src/caracole/viewer/` | Keeps :core and :server apart; separate compile and corpus |
| Which songs the phone renders (M5) | The phone writes a song's pages when no mirror page serves it at its unit's digest (its own songs, songs changed or looked up on the phone), recording the unit digest each page was made at; it serves its page only while the unit is still at that digest, else the mirror's when its gate says SERVE, and a take forgets what it superseded; it records every song's progressions; it makes every card from its own library. The phone's pages are compared with render.py's page path run with no PDF (`tests/helpers/phone_render.py`), never with the computer's own pages, which link their PDFs | The computer's pages stay right for what the phone hasn't changed; cards and `progression` need every song (§11, Q7) |
| Pinyin with tones | The pinyin data regenerated as `Style.TONE`; `Style.NORMAL` derived in Kotlin as pypinyin's `to_normal` does; M1's vectors guard the derivation | One copy of the data |
| OpenCC | Its algorithm ported; its 11 `.ocd2` dictionaries dumped to text by the opencc package's own `opencc_dict` as runtime data (about 1.14 MB) | opencc4j would not match OpenCC 1.4.1 |
| PDFs | Export PDF prints the visible viewer through `WebView.createPrintDocumentAdapter` and Android's print dialog (a printer, or Save as PDF). Nothing is kept in the library | The app never gets the bytes without a non-SDK trick |
| Print CSS | viewer.css, book.css and harptab.css gain the light palette in print and `@page` margins, on the computer too, by lane pages before it writes the page vectors | Dark mode prints light grey on white today (§11, Q8) |
| alphaTab | Its three files as APK assets, answered in the WebView's `shouldInterceptRequest` | The sandboxed Guitar Pro page's script request carries no launch cookie |
| Files shared to the app | `ACTION_SEND` and `SEND_MULTIPLE` of stream MIME types only (never `VIEW`, which would offer caracole for every PDF and binary on the phone, nor `text/plain` or `*/*`, the music-app links' design). An unmatched file is staged in `stateDir/inbox/` and tried again after each sync and lookup, 30 days, as `_inbox/` keeps a file until a song fits | One entry point the later design extends |
| Backups | The library tables and the kept files (by SHA-256, shared between backups), as the before-sync backup plus the files: labels `by-hand`, `daily`, `before-sync`, 3 of each; a copy exported to a file the owner picks; a restore that keeps the current cooldowns, pace and gating records, `sync:id` and `phone:settings`. Make, restore and the daily backup run as queued jobs | A whole copy is about 430 MB; a restore must never forget a cooldown met since (§11, Q11) |
| The corpus's size | Per-area budgets in bytes (decimal MB: 1 MB = 1,000,000 bytes, the sum of a `vectors/<area>/` folder's files) and a 70 MB total for vectors, plus 12 MB for runtime data, enforced by `tests/test_corpus_budget.py` (§3); each area's budget is its size today plus an allowance per writer; fixtures referenced from `tests/fixtures/`, never copied; pages as digests | 27 MB today against 20, unenforced; search is at 5.49 MB today (§11, Q9) |
| Docs | AGENTS.md, docs/usage.md and android/README.md are owned by section: the skeleton writes one heading per lane that has lines to add, and each lane edits only its own | M1–3 left a backlog of AGENTS.md lines for integration |
| Device tests | Every lane that fills an area's replay or touches :app or :server's routes and pages is a device lane: it runs its own area (`device-test.sh --area`) and its classes on the one emulator through `android/scripts/device-test.sh`, which builds outside the lock and then takes it; a lane that changes :server's routes or pages or :app also runs the app's four M1–3 classes (`--app`) before it merges. Big data sets run only in the gated `bench` task, never in `test` | M1–3 ran the device only at integration and found bugs there; EndToEndTest and PinchTest first ran at integration and failed |
| Skeleton | Two steps: skeleton-m4 (Python, Gradle, the scripts, the moves, :core's and :server's M4 declarations, Assembly with the M5 and M6 seams `NONE`), then skeleton-m5m6 (:viewer's declarations, M6's routes and runners, the app's M6 hooks) as the first filler beside M4's first wave (§6) | M1–3's one skeleton was 99 files and 6,086 lines, a serial gate |
| The lookup's sites | Each site's stage of get.py, and its lookup commands, are a file of its site lane (`core/lookup/sites/`), neutral in the skeleton; lane lookup writes the frame and the envelope they ask through; whole lookups are replayed by lane lookup-scenarios once every site has merged | So lookup, lookup-routes and the e2e don't wait for the slowest site lane |
| Lane sizes | About 2,000 lines a lane, 2,600 at most, with a group's seam declared by the skeleton where a port is bigger (html, ug-fetch, lacuerda, requests, harmony, render, songbooks) | M1–3's rule-dense ports ran 1.3–2× their estimates |

---

## 2. Architecture

```
android/
  mirror/   (pure JVM) the computer's pages on the phone, gated by unit; Links (adds Route.Print)
  core/     (pure JVM) io.github.danielhp95.caracole.core.*
            M1–3: py/ db/ keys/ pinyin/ fuzz/ json/ search/ ug/ sites/ lacuerda/ names/ index/ library/ sync/
            M4 new: http/ (Transport, PoliteClient, Robots, Urls, HttpRules, the cache, the errors)
                    config/ (ProviderPolicy, MatchPolicy, RankPolicy, PhoneConfig)
                    health/ (Health, EventLog, Alerts)
                    html/ (the HTML5 parser, lexbor's semantics)
                    lookup/ (Pace, Clients, Lookup = get.py's frame, InteractiveAsk = its envelope;
                             sites/: each site's stage and lookup commands, its site lane's file)
                    match/ (match.py)  lyrics/ (lyrics.py, megalobiz*, azlyrics*)
                    ug/ += page, artist, fetch, rank, coverage, sheet versions
                    lacuerda/ += pages, sheets, search   sites/ += gtptabs, harptabs, gametabs, musescore
                    library/ += Kept, Versions, Numbering, Passes, Overrides, OverrideWriters, OverrideUrls
                    sync/ += Politeness      index/ += Reads (what a lookup stored), Export
                    lyrics/Lyrics.kt (the model, whole in the skeleton)
                    web/ (Inline, DownloadNames: moved from :server)
            M6 new: songbooks/ (songbook.py's rules)  inbox/ (inbox.py)  backup/ (Backups, public)
            testFixtures: testing/ += Replays, Scenarios, FakeTransport, FakeAsking, ForbiddenApis, Corpus.fixture
  viewer/   (NEW, pure JVM) io.github.danielhp95.caracole.viewer.*
            theory/ sheet/ (sheet, chordpro, keys) shapes/ (voicings, instruments) harp/ winds/ chinese/ (pinyin
            on pages, hanzi, OpenCC) harmony/ version/ progressions/ harptab/ pages/ (sheet, songbook, harmonica
            pages) render/ (the phone's render pass)
  server/   (pure JVM) io.github.danielhp95.caracole.server.*
            M4: jobs/ (+ Commands, JobHistory, Status, Outcomes, Feed, PhoneKinds) routes/ (+ LookupRoutes, RequestsRoutes)
                lookups/ (the command runners: get, versions, lacuerda, harptabs)
            M5: page/ (+ PhonePageData) files/ (written pages)
            M6: routes/ (+ SongbookRoutes, VersionsRoutes, HarmonicaRoutes, ReviewRoutes, ExportRoutes,
                GuitarRoutes) songbooks/
  app/      + ShareActivity, BackupsActivity, Printer, AlphaTabAssets, Alerts on Android, Caracole's transport;
            androidTest: CaracoleTestRunner (the refusing transport before Application.onCreate)
  e2e/      + the lookups phase against the fake sites server, the pages phase, the songbooks phase
  scripts/  (NEW) device-test.sh: build, then the emulator's lock, start, install, run areas and classes
tests/conformance/
  data/caracole/ += config/ http/ html/ hanzi/ viewer/ (and unicode's east_asian_width, pinyin with tones)
  vectors/       += py/ html/ http/ health/ pace/ lookup/ sites/ match/ library/ web/ sync/ viewer/ songbook/
  budget.json    (NEW) each area's budget in bytes, the vectors' total and the runtime data's
```

Module dependencies: `:core → :mirror`; `:viewer → :core`; `:server → :core, :viewer, :mirror`; `:app → :server`;
`:e2e → :server` plus the testFixtures of `:core`, `:viewer` and `:server`.

Data flow of a lookup on the phone:
- the library page posts `/lookup` (or `/fetch`, `/request` with `fetch=1`) → `LookupRoutes` →
  `JobQueue.submit(JobSpec(commands = [Command("Look it up now", ["get", "--progress", "--", artist, title])]))`;
- the queue's one worker → the `get` runner (`server.lookups.GetRunner`) → `core.lookup.Lookup.run()`, blocking, inside
  one `Database.writeBlocking` in autocommit (each event, block and kv record committed as it happens);
- each stage is its site's file (`core/lookup/sites/<Site>.kt`), which asks through `Asking` (lane lookup's
  `InteractiveAsk`) → `Clients.interactive` → `PoliteClient` → `Transport` (`RealTransport` on the phone,
  `FakeTransport` in a test, `RoutedTransport` on the e2e and the device);
- the site's pass writes versions, files and kv through `core.library`'s writers, and an index row it stores is noted
  by `core.index.Reads` for the next push to the computer;
- `pdf` is where the computer renders a song's pages (render_all): on the phone it calls `SongPages.render` (M5's
  `PhoneRender`; before it, `NONE` and the stage `skipped` with get.py's `NO_PDFS` words); `pages` is the library
  page (served live on the phone: the search invalidated); `songbooks` calls `SongbookPages.render` (M6);
- the job's stages and events reach `JobViews`, `/jobs.json`, `/requests.json` and the line on the library page;
- after the job, `SearchRoutes.invalidate()`.

Data flow of a sync, with M4's additions: compare (the state document now carries `health` and `settings`) → take →
give → mirror → agree (now also: `PhoneConfig.take(settings)`, `Politeness.merge(computer's health)`, then
`POST /peer/health` with the phone's) → index (the computer's newer indexes merged, then a checkpoint, then the
pages the phone's lookups stored pushed by `POST /peer/index`, merged or not). No stage is added: the Sync tab's UI
is the redesign's.

---

## 3. The conformance corpus in M4–6

The spec, `docs/superpowers/specs/2026-11-03-conformance-corpus.md`, still holds; the skeleton amends it with this
section. What is new:

**Budgets.** `tests/conformance/budget.json` = `{"vectors_total": 70000000, "data_total": 12000000, "areas":
{"<area>": <bytes>, ...}}`, in bytes (an area's size is the sum of its `vectors/<area>/` files' sizes; decimal MB below,
1 MB = 1,000,000 bytes), and `tests/test_corpus_budget.py` (not slow) fails when an area, the vectors' total or the
runtime data's (`data/`, what the APK ships) is over. Each area's budget is its size today plus an allowance for each
lane that writes it; a lane writes its new records into its own area (lookup-routes' gate vectors go to `web/`,
never `search/`):

| Area | MB | Today | Written by | Area | MB | Written by |
|---|---|---|---|---|---|---|
| unicode | 4 | 3.4 | M1, py-format | py | 2 | py-sites, py-format |
| keys | 4.5 | 3.90 | M1 | html | 3 | html-tokenizer, html-tree |
| pinyin | 6 | 4.67 | M1, chinese | http | 1.5 | http-client |
| fuzz | 6.5 | 5.34 | M1, matcher | health, pace | 0.3 each | health-pace |
| canonical | 1 | – | M1 | lookup | 3.5 | lookup, the site lanes, lookup-scenarios |
| search | 6 | 5.49 | M2, device-replays (no new records) | sites | 2 | the site lanes |
| index | 1.5 | – | M2, index-push | match | 1.5 | matcher |
| sync | 2 | – | M3, crossing-computer | viewer | 8 | the M5 lanes, songbook-entries |
| web | 9 | 3.64 | M2–3, job-views, requests-feed, lookup-routes, library-cards, the M6 route lanes, prep-core | songbook | 1 | the songbooks group |
| library | 2.5 | – | M3, library-writes, overrides-model | inbox | 0.3 | inbox-share |
| schema, corpus | 0.3, 0.1 | – | M1 | | | |

The areas sum to about 68 MB, under the 70 MB total. A lane that needs more says so in its report; it never raises a budget it doesn't own.

**Fixture references.** A record may name a file of `tests/fixtures/` instead of carrying its bytes:
`{"fixture": "lacuerda/artist.html"}` wherever a body or a text is expected. Python's `helpers.corpus.fixture_ref(path)`
writes it (and checks the file exists); Kotlin's `Corpus.fixture(path): ByteArray` reads it, from the system property
`caracole.fixtures` (every Gradle `Test` task sets it to `tests/fixtures`) or, on the device, from the androidTest
assets' `fixtures/` (app/build.gradle.kts copies `tests/fixtures/` there). A fixture edited changes the vectors that
name it: the generator's check fails until they are written again.

**Scenario records** (lookups and site passes; new). One record replays one pass over a fixture library and a set of
answers:

```json
{"fn": "caracole.lacuerda_fetch.lacuerda_sheets", "case": "a picked sheet replaces UG's",
 "fixture": "lookup-lacuerda-1",                          // a dump_fixture database (songs, versions, files, kv, phone_*)
 "library": {"Artist/Title/sheet.txt": {"fixture": "…"} | {"text": "…"} | {"base64": "…"}},
 "kw": {"now": "2026-11-03T12:00:00Z", "only": [3], "...": "..."},
 "clients": {"lacuerda": {"budget": 6, "delay": [0, 0]}},  // the policy each client is made with
 "cache": {"lacuerda": {"GET https://acordes.lacuerda.net/x/": {"status": 200, "fetched_at": "…", "body": {...}}}},
 "answers": {"GET https://acordes.lacuerda.net/x/y.shtml": {"status": 200, "headers": [["content-type", "…"]],
             "body": {"fixture": "lacuerda/version.html"}}},
 "out": {"result": {...}, "requests": ["GET https://…", ...],
         "rows": {"songs": [...], "versions": [...], "files": [...], "lacuerda_index": [...]},
         "kv": {"key": "value text", ...}, "library": {"Artist/Title/sheet.json": "<sha256>", ...},
         "events": [["provider", "url", status, "decision"], ...]}}
```

- Answers are keyed by `METHOD` and the full URL as httpx renders it (`core.http.Urls.withParams` renders it the same
  way). An unanswered request fails the generator.
- `out.rows` holds only the tables the pass writes, as `dump_fixture` reads them; `kv` only keys the pass changed.
- `raises` in place of `out` for a pass that raises; `requests`, `rows` and `kv` are still recorded under `"after"`.
- Python's side: `tests/helpers/scenario.py` (the skeleton's) runs the pass with a real `PoliteClient` over
  `httpx.MockTransport`, sleeps recorded and skipped, the clock fixed, and records the rest.
- Kotlin's side: `core.testing.Scenarios.replay(record) { world -> … }` (the skeleton declares it, http-client
  implements it) builds the database from the fixture, a library folder, a cache, a `FakeTransport` serving the
  answers and a `PoliteClient` per client, then compares.
- Random pauses are never compared byte for byte: a scenario compares requests, rows, kv, files and events. Pause
  lengths are http-client's and health-pace's vectors, with the draws recorded.

**Page records** (M5; new). A page is 200–650 KB, so a record holds its digests, never the page:
`{"fn": "caracole.viewer.page.build_viewer", "args": [...], "kw": {...}, "out": {"sha256": "…", "size": N,
"body_sha256": "…", "data": {"<member>": "<sha256 of its json.dumps>", ...}, "names_sha256": "…"}}`, so a mismatch
names the data member at fault. One small page is kept whole per page kind (`viewer/page_whole.json`).

**Runtime data, generated** (new files): `config/config.json` (skeleton), `http/robots.json` and `http/http.json`
(http-client), `html/entities.json` (skeleton-m4) and `unicode/east_asian_width.txt` (py-format), the pinyin data with
tones (chinese), `hanzi/*.txt` (chinese), `viewer/<module>.json` (each M5 lane: the module's constants and HTML
templates exported from the module itself, never retyped), `page/requests.json` (requests-feed: library_page's
Requests tab and panel). One file per lane, so no two lanes write one generated file.

**On the device.** `core.testing.Replays` (testFixtures) lists one `AreaReplay` object per area. Each lane's JVM test
of its area is a call to its replay plus its hand-written cases, and `CorpusOnDeviceTest` runs the replays under ART
and ICU, one test per area (parameterized by area name; `-e area NAME[,NAME…]` picks some, none runs them all, and a
failing area never hides another). The skeletons declare every planned area's object (neutral) in three registries,
which each lane's own file then fills:
- `core.testing.Replays`: Py, Html, Http, Health, Pace, LibraryWrites, Overrides, UgPages, Rank, Match, UgFetch,
  Lyrics, LaCuerda, HarpTabs, GameTabs, TabFiles, Lookup, LookupScenarios, Politeness, IndexExport, Songbook, Inbox,
  and M1–3's Search, Index, Sync (with Unicode, Keys, Pinyin, Fuzz, Canonical, already there);
- `server.testing.ServerReplays`: Web, LibraryName, Queue, JobViews, Requests, LookupRoutes, Cards, SongbookTab,
  Choices, Guitar, Export, Review;
- `viewer.testing.ViewerReplays`: Theory, Sheet, Shapes, Chinese, Harmony, Version, Harptab, Pages, HarmonicaPage,
  Render. Lane device-replays moves M1–3's search, index, sync and web replays there, which never ran on a device.

**Regenerating:** `CARACOLE_CORPUS=write nix develop -c pytest -q -n 0 tests/test_conformance_*.py`, then the check
mode, then `nix develop ./android -c gradle -p android test`. A Python lane that changes a vector runs the Android
suite before merging and follows the drift protocol.

---

## 4. Politeness across two caracoles

The spec is `docs/superpowers/specs/2026-11-03-politeness-crossing.md` (the skeleton writes it from this section; lane
crossing-computer makes it exact where a record's value shape needs it, in the same commit as the code).

### 4.1 Schema 16 (the skeleton)

```sql
ALTER TABLE events ADD COLUMN origin TEXT;        -- the other caracole's sync id; NULL for this side's own requests
ALTER TABLE events ADD COLUMN origin_id INTEGER;  -- that side's events.id
CREATE UNIQUE INDEX events_origin ON events(origin, origin_id) WHERE origin IS NOT NULL;
```

- db.py: `SCHEMA_VERSION = 16`, the script in `_MIGRATIONS` (no BEGIN or COMMIT of its own).
- health.py `answered_any`: `AND origin IS NULL` (a run's own answers). Every other reader counts both sides:
  `lookup_requests_used`, `requests_today`, `_last_request`'s fallback, LaCuerda's searches an hour, YouTube's.
- The phone: `Database.SCHEMA_VERSION = 16`, migrations.json regenerated, the schema and pragmas vectors written again.
  An index export made at 15 is refused at 16, as index_transfer refuses any other schema: both sides move together.

### 4.2 The health document (format 1)

```json
{"format": 1, "from": "<sync id>", "now": "<stamp>",
 "providers": {"ug": {"strikes": 1, "cooldown_until": "…", "last_ok": "…", "last_error": "…", "last_error_at": "…"}},
 "last_request": {"ug": 1730633001.250},
 "events": [[id, run, at, provider, url, status, decision, message], ...],
 "kv": {"lacuerda:search:<query key>": <value>, "lacuerda:search-failed": <value>,
        "gtptabs:unusable:<tab>": <value>, "ug:artist_url:<artist key>": <value>, "ug:pasted_tab:<tab>": <value>},
 "songs": {"<identity key>": {"records": {"megalobiz:checked:": <value>, "azlyrics:checked:": <value>,
                                          "gtptabs:checked:": <value>, "harptabs:checked:": <value>,
                                          "harptabs:checked::pick": <value>, "gametabs:checked:": <value>,
                                          "gametabs:checked::pick": <value>, "ug:artist_page_checked:": <value>},
                              "ug": {"checked_at": "<ug_checked_at>", "dirty": false},
                              "lacuerda_checked_at": "<stamp or null>"}}}
```

- `providers`: every `provider:<name>` kv of this side, as health.py stores it.
- `last_request`: every `http:last_request:<provider>` kv, as a float.
- `events`: this side's own events (`origin IS NULL`) with `at` ≥ the window's start: UTC midnight of `now`, less one
  hour (the day's count and the hour's both covered). Never another side's: nothing echoes.
- `kv`: the global records that gate a request, by the rule table below. Never `youtube-search:*` or `video:*`
  (the computer's alone), never `lookup:*`, index progress or `*:keys` records (index_transfer carries those),
  never `ug:artist_tabs:backfill` (about each side's own cache). Never `ug:unreadable:<tab>`: it is deleted when the
  tab reads again (ug/fetch.py), and a merge that only adds would bring it back at every sync; it is about the page
  each side read, as the cache is, and costs at most one request a week.
- `songs`: per song, by identity key (song ids differ between the two databases):
  - `records`: the per-song records of `songs._PER_SONG_KV` that gate a request, each `:pick` sub-key carried with
    its base record (it is no stamp of its own). Never `lyrics:failed:` (an error, not a miss) or `ug:blocked:`;
  - `ug`: the song's `ug_checked_at` with its `ug_dirty`, one pair (ug_dirty drives fetch_due: the side that
    checked UG later knows whether the song is still owed);
  - `lacuerda_checked_at`: the 30-day gate of lacuerda_fetch.py.
  These columns are outside every unit's digest (peer_sync.song_value reads status, review, the match, the lyrics,
  versions, files and overrides alone; SONG_COLUMNS are carried only when a unit is taken), so a merge writes them
  without making a change to sync. A test on each side asserts that a merge leaves every unit's digest unchanged and
  writes no other SONG_COLUMNS column and no CARRIED_KV record.

**Merge rules** (`politeness.merge_health` and `core.sync.Politeness.merge`, one table, one vector file):

| Member | Rule |
|---|---|
| providers | `health.merge_state(mine, theirs)`. A side's *decisive time* is the later of its `last_ok` and its block's start (`cooldown_until` − (24 h·2^(strikes−1) + 2 h), none without a cooldown). The pair (`strikes`, `cooldown_until`) is taken from the side whose decisive time is later (equal: the larger strikes); but a `cooldown_until` still running at `now` is never shortened: if the other side's runs later, its pair is taken. `last_ok` the later; `last_error` and `last_error_at` the later pair. So a reset (record_ok) on one side reaches the other, and a block after it is a first strike, not a second |
| last_request | the larger, written as `f'{x:.3f}'` (Locale.ROOT on the phone) |
| events | inserted with `origin = doc.from`, `origin_id = id`, `INSERT OR IGNORE` |
| kv, a stamped record (lacuerda:search:, gtptabs:unusable:) | the newer by its own stamp; a record this side lacks is taken |
| kv, lacuerda:search-failed | the union of the failures by (key, at), kept within the hour |
| kv, learned once (ug:artist_url:, ug:pasted_tab:) | taken only where this side has none |
| songs | applied to this side's song of that identity key, if any. `records`: each the newer by its stamp, a `:pick` with its base record. `ug`: the pair of the later `checked_at` (never an OR of `dirty`, which would make each side fetch again what the other just fetched). `lacuerda_checked_at`: the later |

A record one side deleted after a hit (a 30-day checked record of a song that now has lyrics, say) can come back from
the other; harmless, since the hit itself travels in the song's unit and the record gates nothing the song still
lacks. Lane crossing-computer writes the table as data (`politeness.RULES`: prefix → rule) and its vectors,
`vectors/sync/health.jsonl`: a library giving its document; two documents and a library giving the merged state;
among them a reset on one side merged both ways, a block after a reset, a running cooldown against a later ok on
the other side, a `:pick` sub-key, and the `ug` pair both ways.

**Between two syncs** each side counts only the requests it knows: two caracoles can together send up to twice
`lookup_per_hour`, Megalobiz's `per_day` and LaCuerda's 20 searches an hour within one sync's interval (§11, Q16;
the default accepts it, since the phone's lookups are few).

### 4.3 Settings (computer to phone)

```json
"settings": {"name": "<caracole.toml's name or null>", "user_agent": "…",
             "providers": {"<provider>": {"enabled": true, "lookup_delay": [0.5, 1.5], "lookup_requests": 6,
                                          "lookup_per_hour": 60, "per_day": null}},
             "match": {"accept": 90, "margin": 8, "review": 75, "artist_gate": 90},
             "rank": {"coverage_threshold": 0.8, "line_match": 85, "prior_votes": 10, "scored_sheets": 3,
                      "label_penalty": 0.5, "variant_bonus": 0.25}}
```

The phone keeps it as kv `phone:settings` (PyJson text) and `PhoneConfig.read(db)` lays it over
`caracole/config/config.json`'s defaults. The phone never sends settings back.

### 4.4 Where it happens

- **Computer**: `GET /api/peer/state` adds `health` (`politeness.health_document`) and `settings`
  (`politeness.settings_document`); readers ignore unknown keys, so FORMAT stays 2.
- **Computer**: `POST /peer/health` (body `json`, limit 4 MiB, the form token): checked (`format`, `from` a sync id,
  members of the right shapes), kept as `state_dir/peer/health-<16 hex>.json` (0600; at most 2 waiting; an hour,
  as push's `EXPIRES`), and `caracole peer health --take FILE --progress` queued, a job of no song's; it answers
  `202 {"job": N}`. AGENTS.md's "serve writes only…" list gains this file.
- **Computer**: `caracole peer sync` (computer to computer) merges the peer's `health` and posts its own the same way.
- **Phone**, in the sync job's `agree` stage, after take and give: `PhoneConfig.take(db, settings)`;
  `Politeness.merge(db, computer's health, computer's id, now)` (the health read at compare time, applied after the
  take, so a song just taken gets its records); then `PeerClient.health(token, Politeness.document(db, ownId, now))`.
  A failure there is said in the stage's detail and stops nothing.
- **Phone**, in the `index` stage, after the computer's newer indexes merge and the checkpoint (or with nothing to
  merge: the stage pushes either way): the pages `core.index.Reads` noted since the last successful push to that
  computer, exported and posted, `POST /peer/index` (body `bytes`, limit 64 MiB, the token), staged as
  `state_dir/peer/index-<16 hex>.sqlite`, `caracole index merge FILE --delete --progress` queued (§5.4); the notes
  forgotten once it answers 202. A LaCuerda page or search row the computer already has stays the computer's, as
  merge rules.
- **The job kinds** of `caracole peer health --take FILE --progress` and `caracole index merge FILE --delete
  --progress` (web/jobs.py's stages, status.py's `peer_kind` lines, outcome.py's `PEER_STEPS`) are skeleton-m4's,
  with their corpus records, so the crossing lanes write the commands and routes alone and job-views ports every
  kind from the start.

What stays each side's own: the HTTP cache, the pace within a sync's interval (both sides on one home address can
send to one site within the pause between syncs: accepted), `run:last`, every `*:keys` record.

---

## 5. Interfaces

Signatures the skeleton writes as stubs (`TODO("lane <id>")`, or the neutral answer named). A lane may add internal
members and public members with defaults; it changes a declared signature only with the consumers it breaks named in
its report. Every exception and every shared helper is declared once, here; no lane declares another copy (M1–3's
`UnitError`, `Stamps` ×4, `noOnes` ×3).

### 5.1 `:core`

**core.py additions** (py-sites: PyHtml, PyJson, PyFloat, PyInt, capitalize, PyUrl's additions; py-format: PyFormat,
PySequence, eastAsianWidth; skeleton-m4 moves `PyText`, `PyUrl` and `PyStr` here from :server, unchanged but
`PyText.lower`, which now calls `PyUnicode.lower`, and writes `PyCodec` whole over the moved decoder and the HTML5
entity table as data, `data/caracole/html/entities.json`, so the HTML lanes need no other lane):

```kotlin
object PyHtml { fun unescape(s: String): String }                       // html.unescape, html5 table as data
object PyCodec { fun utf8Replace(b: ByteArray): String }                // bytes.decode('utf-8', 'replace'); skeleton-m4's
// PyJson (existing) gains:
fun PyJson.loads(text: String): JsonElement   // json.loads: order kept, a duplicate key at its first place with its
                                              // last value, NaN/Infinity, big ints, lone surrogates as UTF-16 units;
                                              // numbers as literals in Python's int/float form (PyJson.float)
fun PyJson.dumps(v: JsonElement, indent: Int?, ensureAscii: Boolean = false, sortKeys: Boolean = false): String
object PyFormat { fun fixed(x: Double, digits: Int, width: Int = 0, zero: Boolean = false): String  // f'{x:0W.Nf}'
                  fun percent(x: Double, digits: Int): String                                       // f'{x:.N%}'
                  fun roundHalfEven(x: Double): Long }                                              // round(x)
object PyFloat { fun parse(s: String): Double? }   // float(str): Unicode digits, underscores, inf/nan words
object PyInt { fun parse(s: String): java.math.BigInteger? }
// PyUnicode (existing) gains: fun capitalize(s: String): String; fun eastAsianWidth(cp: Int): String
// PyUrl (moved) gains: urljoin, urlencode(List<Pair<String,String>>, doseq), urlunsplit
object PySequence { class SequenceMatcher<T>(a: List<T>, b: List<T>) {   // difflib, isjunk=None, autojunk=False
    fun ratio(): Double; fun matchingBlocks(): List<Triple<Int, Int, Int>> } }
```

`core.index.Stamps` is the one port of stamps.py (prep-core deletes the other three).

**core.http** (lane http-client; the errors are the skeleton's, whole):

```kotlin
data class HttpRequest(val method: String, val url: String, val headers: List<Pair<String, String>>)
class HttpAnswer(val status: Int, val headers: List<Pair<String, String>>, val body: ByteArray)
fun interface Transport { fun send(request: HttpRequest): HttpAnswer }        // one request, no redirect followed
class TransportError(val kind: String, message: String) : Exception(message) // kind: httpx's exception type name
object RealTransport : Transport   // HttpURLConnection; refuses a non-loopback host when caracole.network=loopback
class RoutedTransport(val base: String) : Transport  // test seam: GET {base}/fetch?url=<quoted url>, Host kept
fun interface Draws { fun uniform(low: Double, high: Double): Double }       // Python's low + (high-low)*u

class Response(val url: String, val status: Int, val content: ByteArray, val headers: Map<String, String>,
               val fromCache: Boolean = false, val fetchedAt: String? = null) {
    val text: String            // PyCodec.utf8Replace(content)
    fun json(): JsonElement }   // PyJson.loads(text)
data class Event(val provider: String, val url: String, val status: Int?, val decision: String, val message: String?)

open class ProviderError(val provider: String, val url: String? = null, val status: Int? = null,
                         val msg: String? = null) : Exception()   // message: "provider: status: url: msg", as http.py
class ProviderBlocked(...) : ProviderError; class ProviderUnavailable(...) : ProviderError
class RobotsClosed(...) : ProviderError
class BudgetExhausted(val provider: String) : Exception("$provider: request budget for this run is spent")
class PageParseError, LrclibParseError, MegalobizParseError, AzLyricsParseError, LaCuerdaParseError,
      GtpTabsParseError, HarpTabsParseError, GameTabsParseError : ProviderError   // each as Python's
class PagesNotFiles : ProviderError    // gtptabs_fetch's
class UnreadablePage : ProviderError   // ug/fetch's

interface Client {
    val provider: String; val requestsMade: Int; var policy: ProviderPolicy
    fun get(url: String, params: List<Pair<String, String>>? = null, cache: Boolean = true,
            conditional: Boolean = false, accept: Set<Int> = setOf(200), maxAge: java.time.Duration? = null): Response
    fun cached(url: String, accept: Set<Int> = setOf(200)): Response?
    fun hasCached(url: String, accept: Set<Int> = setOf(200)): Boolean }
class PoliteClient(provider: String, policy: ProviderPolicy, cacheDir: File, userAgent: String, transport: Transport,
                   sleep: (Double) -> Unit, draws: Draws, onEvent: ((Event) -> Unit)? = null,
                   maxConsecutiveErrors: Int = 3, monotonic: () -> Double, wallClock: () -> Instant) : Client, AutoCloseable
class CachedAnswers(provider: String, cacheDir: File) { fun cached(url: String, accept: Set<Int> = setOf(200)): Response? }
object Robots { const val NOT_A_URL = "not a valid URL"; fun disallows(url: String): String? }  // http/robots.json
object Urls { fun withParams(url: String, params: List<Pair<String, String>>): String; fun target(url: String): String
              fun host(url: String): String; fun site(url: String): String; fun resolve(base: String, location: String): String }
object HttpRules { fun stale(r: Response, now: Instant, maxAge: Duration): Boolean
                   fun retryAfter(headers: Map<String, String>, now: Instant): Double?
                   fun isChallenge(headers: Map<String, String>, body: ByteArray): Boolean
                   fun <T> readOnceMore(client: Client, resp: Response, url: String, unreadable: (Throwable) -> Boolean,
                                        fetched: MutableSet<String>? = null, accept: Set<Int> = setOf(200),
                                        params: List<Pair<String, String>>? = null, read: (Response) -> T): T }
```

**core.config** (data classes the skeleton's, whole; `PhoneConfig.read` and `take` health-pace's):

```kotlin
data class ProviderPolicy(val budget: Long, val delay: Pair<Double, Double>, val enabled: Boolean = true,
                          val lookupDelay: Pair<Double, Double> = 0.5 to 1.5, val lookupRequests: Int = 6,
                          val lookupPerHour: Int = 60, val perDay: Int? = null)
data class MatchPolicy(val accept: Double = 90.0, val margin: Double = 8.0, val review: Double = 75.0,
                       val artistGate: Double = 90.0)
data class RankPolicy(val coverageThreshold: Double = 0.8, val lineMatch: Int = 85, val priorVotes: Int = 10,
                      val scoredSheets: Int = 3, val labelPenalty: Double = 0.5, val variantBonus: Double = 0.25)
data class PhoneConfig(val providers: Map<String, ProviderPolicy>, val userAgent: String, val match: MatchPolicy,
                       val rank: RankPolicy, val libraryName: String?) {
    fun provider(name: String): ProviderPolicy
    companion object { const val SETTINGS_KV = "phone:settings"; val DEFAULTS: PhoneConfig  // config/config.json
                       val SWITCHABLE: Set<String>; const val NO_BUDGET = Long.MAX_VALUE
                       fun read(db: Db): PhoneConfig; fun take(db: Db, settings: JsonObject) } }
```

**core.health** (health-pace):

```kotlin
data class ProviderState(val provider: String, val strikes: Int = 0, val cooldownUntil: Instant? = null,
                         val lastOk: Instant? = null, val lastError: String? = null, val lastErrorAt: Instant? = null)
object Health { fun state(db: Db, provider: String): ProviderState
    fun recordBlock(db: Db, provider: String, now: Instant, message: String): ProviderState
    fun recordOk(db: Db, provider: String, now: Instant): ProviderState
    fun recordError(db: Db, provider: String, now: Instant, message: String): ProviderState
    fun isCooling(db: Db, provider: String, now: Instant): Boolean
    fun answeredAny(db: Db, runId: String, provider: String, requests: Int): Boolean }  // own events alone
class EventLog(db: Db, runId: String, clock: () -> Instant) : (Event) -> Unit   // events row + kv http:last_request
interface Alerts { fun blocked(provider: String, until: Instant?, message: String)   // once a cooldown
                  fun failed(title: String, line: String)                          // a job failed; the app decides
                  companion object { val NONE: Alerts } }                          // whether it was in the background
```

**core.lookup** (`Pace`, `Clients` health-pace's; the rest lookup's):

```kotlin
object Pace { const val LOOKUP_RUN = "lookup:"; const val LAST_SENT = "http:last_request:"; val SENT: Set<String>
    fun lookupRunId(now: Instant): String
    fun lookupRequestsUsed(db: Db, provider: String, now: Instant, run: String = LOOKUP_RUN): Int
    fun lookupPolicy(cfg: PhoneConfig, db: Db, provider: String, now: Instant): ProviderPolicy
    fun requestsToday(db: Db, provider: String, now: Instant): Int
    fun withinTheDay(db: Db, provider: String, policy: ProviderPolicy, now: Instant): ProviderPolicy
    fun lastRequest(db: Db, provider: String): Double?
    fun pauseAfterLastRequest(db: Db, provider: String, delay: Pair<Double, Double>, draws: Draws,
                              sleep: (Double) -> Unit, wallSeconds: () -> Double) }
data class Pacing(val sleep: (Double) -> Unit, val draws: Draws, val wallSeconds: () -> Double,
                  val monotonic: () -> Double, val clock: () -> Instant) { companion object { val REAL: Pacing } }
class Clients(val cfg: PhoneConfig, val cacheDir: File, val transport: (provider: String) -> Transport,
              val pacing: Pacing) {
    fun interactive(db: Db, provider: String, runId: String, policy: ProviderPolicy? = null): PoliteClient }
// lookup's:
data class LookupRequest(val artist: String, val title: String, val album: String? = null,
                         val durationMs: Long? = null, val ug: String? = null, val tab: String? = null,
                         val lacuerda: String? = null, val harptabs: String? = null, val gametabs: String? = null,
                         val songbooks: Boolean = true)
data class LookupResult(val songId: Long?, val display: String, val states: Map<String, String>,
                        val details: Map<String, String>, val files: Map<String, String>,
                        val secondsToSheet: Double?, val seconds: Double, val requests: Map<String, Int>,
                        val bug: String?, val refused: String?) { val ok: Boolean get() = bug == null }
interface Progress { fun stage(name: String, state: String, detail: String = "")
                     fun song(id: Long, display: String) {}; fun readable(files: Map<String, String>, seconds: Double) {} }
data class RenderStats(val written: Int = 0, val unchanged: Int = 0, val failed: Map<Long, String> = emptyMap())
fun interface SongPages { fun render(db: Db, songIds: Collection<Long>, between: (() -> Unit)?): RenderStats
                          companion object { val NONE: SongPages } }   // the pdf stage's; M5 phone-render implements
fun interface SongbookPages { fun render(db: Db, only: Set<String>?): RenderStats
                              companion object { val NONE: SongbookPages } }   // M6 songbook-entries implements
class Lookup(cfg: PhoneConfig, database: Database, store: LibraryStore, clients: Clients, pages: SongPages,
             songbooks: SongbookPages, alerts: Alerts, request: LookupRequest, progress: Progress, pacing: Pacing,
             stages: SiteStages = SiteStages.ALL) {
    fun run(db: Db): LookupResult }   // blocking: the runner calls it in database.writeBlocking; autocommit, never a
                                      // transaction, so each event, block and kv record commits as it happens
// the envelope every site asks through (skeleton-m4's whole, but InteractiveAsk, lookup's):
sealed interface Asked<out T> { data class Done<T>(val value: T) : Asked<T>; data class Off(val why: String) : Asked<Nothing>
    data class Cooling(val until: Instant?) : Asked<Nothing>; data class Blocked(val error: ProviderBlocked, val state: ProviderState) : Asked<Nothing>
    data class Spent(val hour: Boolean, val keptForSheets: Boolean) : Asked<Nothing>; data class Failed(val error: ProviderError) : Asked<Nothing> }
interface Asking { fun <T> ask(provider: String, policy: ProviderPolicy? = null, work: (Client) -> T): Asked<T>
                   val requests: Map<String, Int> }
data class StageContext(val db: Db, val song: SongRow, val overrides: Overrides, val config: PhoneConfig,
                        val library: LibraryStore, val asking: Asking, val now: Instant)
data class StageEnd(val state: String, val detail: String)   // done | skipped | failed, get.py's words
fun interface SiteStage { fun run(ctx: StageContext): StageEnd }
class SiteStages(val match: SiteStage, val ugSheet: SiteStage, val ug: SiteStage, val lacuerdaPick: SiteStage,
                 val lacuerda: SiteStage, val lrclib: SiteStage, val megalobiz: SiteStage, val azlyrics: SiteStage,
                 val gtptabs: SiteStage, val harptabs: SiteStage, val gametabs: SiteStage) {
    companion object { val ALL: SiteStages } }   // core/lookup/sites/*.kt: each stage its site lane's file, neutral in
                                                 // the skeleton ("skipped", get.py's words for a site not asked)
interface CommandContext { val db: Db; val asking: Asking; val now: Instant; fun say(line: String) }
// the lookup commands, each its site lane's file in core/lookup/sites/, neutral in the skeleton:
object VersionsCommands { fun keep(c: CommandContext, song: SongRow, tab: Long): String          // ug-fetch-artist
                          fun keepMore(c: CommandContext, song: SongRow): String }
object LaCuerdaCommands { fun artist(c: CommandContext, artist: String, first: String?): String  // lacuerda-sheets
                          fun search(c: CommandContext, query: String, auto: Boolean): String }
object HarpTabsCommands { fun artist(c: CommandContext, path: String): String }                  // harptabs
// testFixtures (skeleton-m4's, whole): FakeAsking(clients: Map<String, Client>) turns each error into its Asked as
// the envelope does, with no words, so a site lane tests its stage before lookup lands
```

**core.html** (html-tokenizer: `internal/token/`; html-tree: the rest; the spec `2026-11-03-html-parsing.md`):

```kotlin
object Html { fun parse(text: String): HtmlDoc; fun parse(bytes: ByteArray): HtmlDoc }   // bytes: utf8Replace first
class HtmlDoc(val quirks: Boolean) { fun css(sel: String): List<HtmlNode>; fun cssFirst(sel: String): HtmlNode? }
class HtmlNode { val tag: String   // lowercase; "-text", "-comment"
    fun attr(name: String): String?; val attributes: Map<String, String?>   // first duplicate wins
    fun text(deep: Boolean = true): String  // lexbor: script/style data in, <br> nothing, comments out, separator ""
    fun children(includeText: Boolean = true): List<HtmlNode>; val textContent: String?; val next: HtmlNode?
    val isText: Boolean; fun css(sel: String): List<HtmlNode>; fun cssFirst(sel: String): HtmlNode?
    fun replaceWith(text: String); fun insertAfter(text: String) }
```

Selectors: tag, `#id`, `.class`, `[a]`, `[a=v]`, `[a^=v]`, `[a*=v]`, `[a$=v]`, descendant, `>`, `+`, `,` (the ones
caracole's parsers use; the lane greps them all). id and class match without case in quirks mode.

**core.library additions** (library-writes: `Kept`, `Versions`, `Numbering`, `Passes`; overrides-model: the rest):

```kotlin
class SharedFolder(message: String) : Exception(message)      // library.SharedFolder
class OverridesError(message: String) : Exception(message)
object Kept { fun keepFile(db: Db, lib: LibraryStore, song: SongRow, versionId: Long, name: String, data: ByteArray,
                           rank: Int, now: String): Boolean; fun keptAlready(db: Db, songId: Long, sha256: String): Boolean
              fun holds(db: Db, lib: LibraryStore, song: SongRow, name: String, sha256: String): Boolean
              fun dropFile(db: Db, lib: LibraryStore, song: SongRow, name: String)
              fun writeAtomic(path: java.nio.file.Path, data: ByteArray): String }   // never mode 0600
data class VersionRow(/* the versions table's columns, as Python's Version */)
object Versions { fun upsert(db: Db, provider: String, tabId: String, songId: Long, slot: String, kind: String,
                             rating: Double, votes: Int, version: Int, label: String?, url: String, raw: JsonObject,
                             now: String): Long
    fun songVersions(db: Db, songId: Long, slot: String? = null, kinds: List<String>? = null,
                     includeGone: Boolean = false): List<VersionRow>
    fun get(db: Db, id: Long): VersionRow?; fun setRaw(db: Db, id: Long, raw: JsonObject)
    fun setCoverage(db: Db, id: Long, coverage: Double?); fun markGone(db: Db, id: Long)
    fun markStale(db: Db, songId: Long, provider: String); fun setPicks(db: Db, songId: Long, picks: Map<String, Long?>)
    fun updateSong(db: Db, songId: Long, columns: Map<String, Any?>); fun refreshStatus(db: Db, songId: Long) }
object Numbering { fun guitar(db: Db, lib: LibraryStore, song: SongRow): Int; fun harmonica(...): Int
                   fun gametab(...): Int; fun score(..., ext: String): Int }
open class PassStats(var asked: Int = 0, var failed: MutableMap<Long, String> = mutableMapOf() /* as provider_pass */)
object Passes { fun <S : PassStats> eachSong(songs: List<SongRow>, stats: S, site: String,
                    stopOn: Set<KClass<out ProviderError>> = emptySet(),
                    onError: ((SongRow, ProviderError) -> Unit)? = null, turn: (SongRow) -> Unit) }
class Overrides(/* overrides.Overrides' fields: alias, match, artistUrl, artistUrlNames, pin, pinUrls, transpose,
                   ignore, block, reject, youtube, lacuerda, harptabs, gametabs, azlyrics, version, harmonica */) {
    companion object { fun read(db: Db): Overrides } }
class LaCuerdaPick, HarpTabsPick, GameTabsPick   // url, path, tabId, holds(), as overrides.py
object OverrideWriters {   // each writes phone_overrides exactly as song_entries yields after the same add_*
    fun addMatch(db: Db, display: String, ugRef: String); fun addPin(db: Db, display: String, urls: List<String>)
    fun removePin(db: Db, display: String, tabs: Set<Long>?): Boolean
    fun addLacuerda(db: Db, display: String, url: String); fun addHarptabs(...); fun addGametabs(...)
    fun addReject(db: Db, display: String, refs: List<String>); fun addAlias(db: Db, sourceArtist: String, ugArtist: String)
    fun addIgnore(db: Db, display: String)
    fun addVersion(db: Db, display: String, query: String?, keyVersion: (String) -> Boolean)        // M5's check
    fun addHarmonica(db: Db, display: String, tab: String, reading: JsonElement?, checkSpec: (JsonElement) -> Unit) }
object OverrideUrls { fun overrideKey(display: String): String; fun tabIdFromUrl(s: String): Long
    fun pinUrl(s: String): String; fun artistPageAddress(url: String): String?; fun pastedTabId(url: String): Long?
    fun classifyTabUrl(url: String): String?   // ug/sitemap.classify_tab_url
    fun lacuerdaPickFromUrl(s: String): LaCuerdaPick; fun harptabsPickFromUrl(...); fun gametabsPickFromUrl(...) }
```

**core.lyrics' model and core.match's constants** (skeleton-m4's, whole, since ug-fetch, lacuerda and the lyrics
passes all read them): `data class Lyrics(...)` with lyrics.py's fields, `fun lyricsFromJson(text: String?): Lyrics?`,
`fun songLyrics(db: Db, songId: Long): Lyrics?` (lyrics.song_lyrics), and `Match.ARTIST_PAGE`,
`Match.REVIEW_ONLY_STEPS` (the only names ug/fetch.py imports from match).

**core.index.Reads** (skeleton-m4's, whole): `object Reads { fun note(db: Db, site: String, page: String, at: String);
fun since(db: Db, peer: String): Map<String, List<String>>; fun forget(db: Db, peer: String, upTo: String) }`, kv
`phone:read:<site>:<page>` = the stamp and `phone:pushed:<peer id>` = the last push's stamp. The site lanes call
`note` for each index row a lookup stores; index-push reads and forgets.

**core.ug, core.match, core.lyrics, core.lacuerda, core.sites** (the site lanes'). Each pass returns a data class named
as Python's (`LyricsStats`, `MegalobizStats`, `AzLyricsStats`, `LaCuerdaStats`, `GtpTabsStats`, `HarpTabsStats`,
`GameTabsStats`: Python's fields camelCased, extending `PassStats`), which the skeleton declares from Python's
dataclasses at main. Entry points (exact parameter lists the skeleton takes from the Python functions; `only` is
always the lookup's song):

```kotlin
// ug (ug-pages: UgPage, UgArtist, UgLookup, ArtistTabs additions; rank-coverage: Rank, Coverage, SheetVersions;
//     ug-fetch-sheet: UgFetch, FetchContext; ug-fetch-artist: ArtistRoute, the seam processSong calls)
object UgPage { fun parseTabPage(html: ByteArray, url: String? = null): UgTabPage; fun stripMarkup(s: String): String
                fun decodeTwice(s: String): String; fun kindOf(type: String?): String?; fun pageUrl(tabId: Long, path: String? = null): String }
object UgArtist { fun parse(html: ByteArray, url: String? = null): UgArtistPage; fun pageUrl(base: String, kind: String? = null, page: Int = 1): String }
object Rank { /* bayes, priorMean, rankByRating, rankSheets, rankGuitar, isComplete, replacesSheet */ }
object Coverage { fun coverage(sheetText: String, lyrics: String, policy: RankPolicy): Double? }
object SheetVersions { /* versionNames, sheetKind, keptByYou, noteKeptByYou, unkeepable, mayKeep, sheetPins, inLibrary, inLibraryOf, asData */ }
// ArtistTabs (existing) gains store, keepOnly, forget, backfill(db, cached: CachedAnswers)
class FetchContext(val db: Db, val client: Client, val overrides: Overrides, val rank: RankPolicy, val library: LibraryStore,
                   val now: Instant, val maxPagesPerGroup: Int = 3, val guitarPagesPerGroup: Int = 1,
                   val artistPageMaxAge: Duration = Duration.ofDays(30), val artistPagesPerKind: Int = 3, val versions: Boolean = true)
object UgFetch { fun processSong(ctx: FetchContext, song: SongRow, guitar: Boolean = true): SongFetchOutcome
                 fun keepVersion(ctx: FetchContext, song: SongRow, tabId: Long): String  // kept|same|held|sheet|gone|unreadable|closed|no text|unknown
                 fun checkedSince(song: SongRow, since: Instant): Boolean }
// match (matcher)
object Matcher { fun matchAll(db: Db, overrides: Overrides, policy: MatchPolicy, songs: List<SongRow>, dryRun: Boolean = false): List<MatchChange>
                 fun candidatesOf(song: SongRow): List<MatchCandidate> }
// lyrics (lyrics)
object Lrclib { fun fetchPendingLyrics(db: Db, client: Client, lib: LibraryStore, now: Instant, only: Set<Long>): LyricsStats }
object Megalobiz { fun megalobizLyrics(db: Db, client: Client, lib: LibraryStore, now: Instant, only: Set<Long>): MegalobizStats }
object AzLyrics { fun azlyricsLyrics(db: Db, client: Client, lib: LibraryStore, now: Instant, overrides: Overrides, only: Set<Long>): AzLyricsStats }
// lacuerda (lacuerda-pages: pages, writers, LaCuerdaSearch; lacuerda-sheets: LaCuerdaSheets)
object LaCuerdaSheets { fun lacuerdaSheets(db: Db, client: Client, lib: LibraryStore, rank: RankPolicy, now: Instant,
                                           overrides: Overrides, only: Set<Long>): LaCuerdaStats
                        fun readArtistPage(db: Db, client: Client, artist: String, now: Instant, first: String? = null): Pair<String, Int>? }
data class SearchGate(val state: String, val query: String, val key: String, val why: String?)   // /api/search's lacuerda_search
object LaCuerdaSearch { fun queryKey(q: String): String?; fun gate(cfg: PhoneConfig, db: Db, q: String, now: Instant): SearchGate?
                        fun search(db: Db, client: Client, q: String, now: Instant): LaCuerdaSearchAnswer }
// sites (harptabs, gametabs, tab-files)
object GtpTabs { fun gtptabsFiles(db: Db, client: Client, lib: LibraryStore, now: Instant, overrides: Overrides, only: Set<Long>): GtpTabsStats
                 fun sniff(data: ByteArray): String? }
object HarpTabs { fun harptabsTabs(...same...): HarpTabsStats; fun readArtist(db: Db, client: Client, path: String, now: Instant): HarpArtistPage? }
object GameTabs { fun gametabsTabs(...same...): GameTabsStats }
object MuseScore { fun songPages(db: Db, song: SongRow, limit: Int = 3): List<MuseScorePage> }
```

**core.sync additions** (crossing-phone; index-push for `pushIndex`):
`object Politeness { fun document(db: Db, ownId: String, now: Instant): JsonObject; fun merge(db: Db, doc: JsonObject,
peerId: String, now: Instant): Merged; fun mergeState(mine: ProviderState, theirs: ProviderState): ProviderState }`; `PeerClient.health(token: String, doc: JsonObject): Int` (the computer's
job id); `PeerClient.pushIndex(token: String, file: File): Int`; `PeerState.health: JsonObject?`,
`PeerState.settings: JsonObject?`.

**core.index additions** (index-push), in `core/index/Export.kt`, apart from IndexTransfer.kt (whose merge end is
prep-db's one line): `object IndexExport { fun export(db: Db, to: File, pages: Map<String, List<String>>): Exported }`
(index_transfer.export(pages=)'s file, limited to the pages Reads noted).

**core.db additions** (prep-db): `Database.checkpoint(truncate: Boolean = true)` (no-op stub in the skeleton, called
by Assembly's import and SyncEngine's index stage), `Database.warmUp()`. Big data sets (the 200,000-row merge, the
cold search, the matcher's 1.5 M rows, M1–3's MergeSpeedTest, renamed MergeSpeedBench by skeleton-m4) run only in each
module's gated `bench` task: classes named `*Bench`, excluded from `test`, run by `gradle -p android bench` with a
3 GiB heap and one fork.

**core.songbooks** (M6; songbook-writers; `set` songbook-entries'):
`class SongbookError(message: String) : Exception(message)`; `data class SongbookSong(val text: String, val setting:
Setting?)`; `data class Songbook(val name: String, val songs: List<SongbookSong>)`; `object Songbooks { checkName,
nameKey, folderKey, entryKeys, sameEntry, findEntrySong, all, find, make, add, remove, move, set, rename, delete }`
(each in `Database.write`, refusing with songbook.py's words).

**core.inbox** (M6; inbox-share): `sealed interface Filed { data class Kept(val songId: Long, val name: String);
data class PutBack(val paths: List<String>); object Duplicate; object Unmatched }`; `object Inbox { fun file(db: Db,
lib: LibraryStore, name: String, data: ByteArray, now: String): Filed; fun parseDownloadName(name: String):
Triple<String?, String, Int?> }`.

**core.backup** (M6; alerts-backups): `object Backups { fun make(db: Db, lib: LibraryStore, stateDir: File, now: Instant,
label: String): File?; fun list(stateDir: File): List<Backup>; fun restore(database: Database, lib: LibraryStore, file:
File, keep: (Db) -> JsonObject, putBack: (Db, JsonObject) -> Unit); fun exportTo(file: File, out: java.io.OutputStream) }`
(the take's backup made public, plus the kept files by SHA-256 under `stateDir/backups/blobs/`; a restore keeps this
side's politeness through `keep` and `putBack`, Politeness.document and merge; `Take.backupBeforeSync` calls make with
`before-sync`).

### 5.2 `:viewer` (M5)

Signatures skeleton-m5m6 declares (stubs); each M5 lane owns its package. `Voicings.TUNING` is the skeleton's constant, whole, so harmony needs theory alone.

```kotlin
// viewer.theory
data class Chord(val root: Int, val quality: String, val bass: Int? = null, val shown: String? = null, val tones: Set<Int>? = null)
data class Key(val tonic: Int, val mode: String)
object Theory { fun parseChord(text: String, strict: Boolean = true): Chord?; fun parseKey(text: Any?): Key?
    fun namedKey(text: Any?, capo: Int, played: List<Chord>): Key?; fun bareKey(named: Key, capo: Int, played: List<Chord>): Key
    fun keyName(k: Key): String; fun spelling(k: Key?): List<String>; fun mapChord(c: Chord, k: Key, mode: String): Chord
    fun alternatives(c: Chord, k: Key, limit: Int = 8): List<Chord>; fun capoHints(k: Key, limit: Int = 2, capo: Int = 0): List<Pair<Int, Key>>
    fun estimateKey(chords: List<Chord>): Key?; fun sounding(shapes: Key, capo: Int): Key; fun shapesKey(named: Key, capo: Int, played: List<Chord>): Key }
// viewer.sheet
data class Sheet(...); object Sheets { fun parse(cho: String): Sheet }
object SheetView { fun shown(s: Sheet); fun drawnLines(s: Sheet): List<String>; fun writtenTexts(s: Sheet): List<String>
                   fun places(s: Sheet): List<Pair<Int, Int>>; fun viewerKey(cho: String, key: String?, keySource: String?): Key?
                   fun shapesOf(s: Sheet): JsonObject }
object ChordPro { fun toChordPro(markup: String, title: String, artist: String, key: String? = null, capo: Int? = null, auto: Boolean = false): String }
data class SongKey(val key: String, val source: String)
object MusicKeys { fun sheetKey(raw: JsonObject, markup: String?, capo: Int?): SongKey?; fun songKey(db: Db, libraryDir: File, songId: Long): SongKey? }
// viewer.shapes, viewer.harp, viewer.winds
object Voicings { val TUNING: List<Int>; ... }; object Instruments { val INSTRUMENTS: Map<String, Instrument>; fun chordShapes(...); fun pageVoicings(...): JsonObject }
object Harp { fun tables(key: Key?, mapped: Map<String, List<Chord?>>, alts: Map<String, List<List<Chord>>>? = null): JsonObject
              fun holeNote(harp: Int, hole: Int, breath: String, bend: Int = 0, over: Boolean = false): Int?; fun holeTables(): JsonArray }
object Winds { fun tables(...): JsonObject; fun fingeringData(): JsonObject }
// viewer.chinese
object OpenCC { enum class Config { T2S, TW2S, S2TW }; fun convert(config: Config, text: String): String }
object Hanzi { fun scripts(texts: List<String>): Map<String, Map<String, String>>; fun names(texts: List<String>): Map<String, Map<String, String>> }
object ViewerPinyin { fun readings(lines: List<String>): List<List<String>?>?; fun isChinese(lines: List<String>): Boolean }
// viewer.harmony
object Harmony { fun numeral(...); fun progressions(...); fun progressionKey(numerals: List<String>): String; fun readTyped(text: String): List<String> }
object HarmonyTables { fun tables(chords: List<Chord?>, key: Key?, places: List<Pair<Int, Int>>, mapped: Map<String, List<Chord?>>, alts: Map<String, List<List<Chord>>>): JsonObject }
// viewer.version, viewer.progressions
data class Version(val t: Int = 0, val mode: String? = null, val capo: Int? = null, val alt: Map<String, Map<Int, String>> = emptyMap(),
                   val at: Map<Int, Int> = emptyMap(), val inst: String? = null)
data class Setting(val key: String?, val mode: String?, val capo: Int?, val instrument: String?)
object Versions { fun fromQuery(q: String): Version; fun query(v: Version): String; fun keyVersion(text: String): KeyVersion?
                  fun entry(v: Version, cho: String, key: Key?, capoSheet: Int?): String?; fun inSetting(...): Version
                  fun settingProblem(s: Setting): String?; fun playedKey(...); fun label(...): String; fun ownVersion(...): Version }
object Progressions { fun record(db: Db, songId: Long, cho: String, key: String?, keySource: String?); fun forget(db: Db, songId: Long)
                      fun library(db: Db): Map<Long, JsonArray>; fun read(text: String): Wanted?; fun songsWith(db: Db, w: Wanted): List<Playing> }
// viewer.harptab
object HarpTabs { fun parse(body: String, harp: String? = null, notation: Notation? = null): Tab; fun readings(body: String, harp: String? = null): List<Reading>
                  fun checkSpec(spec: JsonElement); fun specOf(r: Reading): JsonElement }
object HarpFit { fun choose(tab: Tab, cho: String? = null, key: String? = null, keySource: String? = null, pageKey: String? = null): Choice }
// viewer.pages
data class ViewerInputs(val cho: String, val key: String? = null, val keySource: String? = null, val transpose: Int = 0,
                        val start: String? = null, val pdf: String? = null, val export: Boolean = true, val versions: JsonObject? = null,
                        val guitar: List<String> = emptyList(), val harmonica: List<JsonObject> = emptyList(),
                        val pdfTraditional: String? = null, val video: JsonObject? = null)
object SheetPage { fun build(i: ViewerInputs): String; fun viewerCsp(page: ByteArray): String }
object HarmonicaPage { fun build(...): String }
data class BookSong(...); object SongbookPage { fun build(name: String, songs: List<BookSong>, pdf: String? = null,
                                                          cho: String? = null, pdfTraditional: String? = null): String }
                                                          // songbook-entries' (book.py imports version.py; page.py doesn't)
// viewer.render
class PhoneRender(database: Database, libraryDir: File, mirror: Mirror?) : SongPages { fun renderStale(between: () -> Unit): RenderStats }
object WrittenPages { fun written(db: Db, songId: Long, name: String): Written?   // sha256, size, the unit digest
                      fun note(db: Db, songId: Long, name: String, bytes: ByteArray, unitDigest: String)
                      fun current(db: Db, songId: Long, name: String): Boolean   // the unit still at that digest
                      fun songbook(db: Db, folder: String): Map<String, Pair<String, Long>>
                      fun noteSongbook(db: Db, folder: String, inputs: String, files: Map<String, ByteArray>) }
```

### 5.3 `:server`

```kotlin
// server.jobs (jobs-queue)
data class Command(val label: String, val args: List<String>)
fun interface CommandRunner { suspend fun run(args: List<String>, context: JobContext) }   // throws = the step failed
class Commands(val runners: Map<String, CommandRunner>) { fun runnerFor(args: List<String>): CommandRunner? }
data class JobSpec(val title: String, val key: String, val kind: String, val stages: List<Pair<String, String>>,
                   val display: String = "", val songId: Long? = null, val join: Boolean = true,
                   val doneLine: String? = null, val commands: List<Command> = emptyList(), val fetching: Boolean = false,
                   val note: String = "", val run: (suspend (JobContext) -> Unit)? = null)   // run null: the commands
interface JobContext { /* existing */ fun readable(files: Map<String, String>, seconds: Double) {}
                       fun yieldToQueued() {} }   // runs the lookups queued since, in this worker; no write held
class JobQueue(scope: CoroutineScope, limit: Int = 20, keep: Int = 100, clock: ..., commands: Commands = Commands(emptyMap()),
               history: JobHistory? = null) {
    /* existing */ fun submitAll(specs: List<JobSpec>): List<Pair<Job, Boolean>>; fun again(id: Int): Job
    var onEnd: (Job) -> Unit = {} }   // after each job, cancelled ones too: the afterJob hook and Alerts.failed
class JobHistory(file: File) { fun load(now: Instant): List<Job>; fun save(job: Job); fun rewrite(jobs: List<Job>) }
// server.jobs (job-views: JobViews, every kind, SongFacts, Status, Outcomes; requests-feed: Feed, §5.4's shapes)
// server.jobs.PhoneKinds (the skeletons', whole; no lane edits it): the phone's own job kinds, which Python never
// queues, their stages and words, read by JobViews (AGENTS.md records them as the phone's):
//   kind      key                 stages (label)               running line                    done / failed line
//   render    render:<build>      render ("Making the pages")  "Making the pages again: N of M"  "Pages made again for N songs" / "Pages not made: <why>"
//   inbox     inbox:<file name>   file ("Filing the file")     "Filing <name>…"                  "Filed as <name> of <song>" | "Waiting for a song that fits: <name>" / "Not filed: <why>"
//   backup    backup:<label>      backup ("Backing up")        "Backing up the library…"         "Backed up (<label>)" / "Not backed up: <why>"
//   restore   restore:<file>      restore ("Restoring")        "Restoring the library…"          "Restored the library of <date>" / "Not restored: <why>"
// server.lookups (lookup): GetRunner, VersionsRunner, LaCuerdaRunner, HarpTabsRunner : CommandRunner
// server.routes (each neutral in the skeleton, answering the Stubs' 409):
class LookupRoutes(...); class RequestsRoutes(...)                                  // M4
class SongbookRoutes(...); class VersionsRoutes(...); class HarmonicaRoutes(...); class ReviewRoutes(...)
class ExportRoutes(...); class GuitarRoutes(...)                                    // M6
// server.page: class PhonePageData(...) : PageData, SongCards   (M5 library-cards; delegates to MirrorPageData until)
// server.Assembly:
data class PhoneDeps(val database: Database, val libraryDir: File, val stateDir: File, val mirror: Mirror?,
                     val scope: CoroutineScope, val settings: SyncSettings, val secret: String, val csrf: String,
                     val transport: (provider: String) -> Transport,      // no default
                     val version: String = "0.1.0", val alerts: Alerts = Alerts.NONE, val pacing: Pacing = Pacing.REAL,
                     val searchesLacuerda: Boolean = true)   // false: /api/search's lacuerda_search null (the runner's)
```

`Phone` (skeleton-m4's for M4, skeleton-m5m6 adding M5's and M6's): every module of M4–6 listed in its final order (PageRoutes, SearchRoutes,
JobsRoutes, RequestsRoutes, SyncRoutes, LibraryRoutes, LookupRoutes, SongbookRoutes, VersionsRoutes, HarmonicaRoutes,
ReviewRoutes, ExportRoutes, GuitarRoutes), each built from `PhoneParts` (database, store, config reader, queue,
cards, clients, pages, songbook pages, alerts, pacing); the runners map (`get`, `versions`, `lacuerda`, `harptabs`,
`review`, `harmonica`, `render`, `songbook`, `inbox`), each a class in its owner's file; the checkpoint after an
import; `deps.transport` read on every request, never captured at start. After the skeletons no lane edits Assembly.kt;
a lane that must is named in its brief.

### 5.4 HTTP routes

On the phone (Python's shapes, by the routes' corpus):

| Route | Lane | Request | Answer |
|---|---|---|---|
| `POST /lookup` | lookup-routes | form: csrf, artist, title, album?, duration?, q?, ug?, tab?, lacuerda?, harptabs?, gametabs? | 202 `{job, url, view}` as `search_routes.lookup_request`; a form that doesn't ask for JSON: a redirect to `/#tab=requests&job=N` (status.details_href; the phone has no /lookup page) |
| `POST /request` (`fetch=1`) | lookup-routes | the request form | as library_routes: a lookup queued |
| `POST /fetch` | lookup-routes | csrf, song | as library_routes.fetch (its `review_first` refusal) |
| `POST /lacuerda/artist`, `/lacuerda/search`, `/harptabs/artist` | lookup-routes | csrf, artist / q, auto? / path | 202 `{job}`, keys `lacuerda-artist:`, `lacuerda-search:`, `harptabs-artist:` |
| `POST /versions/keep-more` | lookup-routes | csrf, song | 202 `{job}` |
| `GET /requests.json` | requests-feed | script-only, `?open=N` | feed.feed's JSON |
| `POST /jobs/again` | requests-feed | csrf, job | as jobs_routes |
| `GET /versions`, `POST /versions/choose`, `/keep`, `/clear` | versions-harmonica | as versions_routes | as versions_routes |
| `GET /harmonica`, `POST /harmonica/pin`, `/clear` | versions-harmonica | as harmonica_routes | as harmonica_routes |
| `GET /review`, `POST /review` | review | as review_routes | as review_routes |
| `GET /export.pdf` | export-print | sheet, the version's query, mine? | 200 `{"name": "<download name>", "label": "…"}` (queues Make this my version with `mine=1`); the app prints |
| `GET /guitar`, `GET /assets/alphatab/<name>` | guitar-alphatab | as guitar_routes | the page; the bundle (the app answers it first) |
| `POST /songbook/make`, `add`, `add-song`, `get`, `remove`, `move`, `set`, `rename`, `delete` | songbook-routes | as songbook_routes | as songbook_routes |

Stubs keeps `/youtube*` and `GET /api/youtube/video` (permanent) and `GET /lookup` (the computer's lookup page: the
library page's search does the same on the phone).

On the computer (new):

| Route | Lane | Request | Answer |
|---|---|---|---|
| `GET /api/peer/state` | crossing-computer | as before | adds `health` and `settings` (§4) |
| `POST /peer/health` | crossing-computer | json, the health document, token, ≤ 4 MiB | 202 `{"job": N}`; `caracole peer health --take FILE --progress` |
| `POST /peer/index` | index-push | bytes, an index export, token, ≤ 64 MiB | 202 `{"job": N}`; `caracole index merge FILE --delete --progress` |

### 5.5 The app's hooks (the skeletons', whole; each target file a lane's)

- `CaracoleTestRunner` (skeleton-m4; `testInstrumentationRunner` in app/build.gradle.kts): before
  `Application.onCreate` it sets `caracole.network=loopback` and makes `Caracole.sitesForTests` a transport that
  refuses every site (a `TransportError("refused")`), and `searchesLacuerdaForTests` false; a test that means to
  reach the fake sites sets `sitesForTests` to `RoutedTransport("http://10.0.2.2:P")`. `Caracole`'s transport reads
  `sitesForTests` on every request.
- `MainActivity`'s WebViewClient (skeleton-m5m6): `shouldInterceptRequest` asks `AlphaTabAssets.answer(request)` first
  (guitar-alphatab: its response carries `Access-Control-Allow-Origin: *` and the content type);
  `shouldOverrideUrlLoading` and the `DownloadListener` route `Links.Route.Print` to `Printer.print(activity, web, url)`
  (export-print).
- `AndroidManifest.xml` (skeleton-m5m6): `ShareActivity` (exported; `ACTION_SEND` and `SEND_MULTIPLE` alone, for
  `application/octet-stream`, `application/x-guitar-pro`, `application/vnd.recordare.musicxml*`, `application/pdf`,
  `audio/midi`, `application/x-musescore`; never `VIEW`, `text/plain` or `*/*`), `BackupsActivity`, the `alerts` channel.
- `Caracole` (skeleton-m4): `transport` (`RealTransport`, or `sitesForTests` under the runner), the phone's `Alerts`
  (alerts-backups), `version` from `BuildConfig.VERSION_NAME`.
- `SettingsActivity` (skeleton-m5m6): a "Backups" row opening `BackupsActivity`, apart from the sync rows the redesign
  replaces.

---

## 6. The skeleton, in two steps

### 6.1 skeleton-m4

One step, on the branch `android/m4-skeleton` in the worktree `.claude/worktrees/m4-skeleton`, made from main, merged
with `git -C /home/dani/Projects/caracole merge --no-ff android/m4-skeleton` once it passes. The main checkout's
uncommitted files (`improvements.md`, `android_port.md`, `run.sh`, `temp.sh`) are never touched. It declares what M4
codes against, and the seams M5 and M6 fill (`SongPages.NONE`, `SongbookPages.NONE`); skeleton-m5m6 (§6.2) declares
the rest while M4's first wave builds. Every elided signature of §5 takes the Python function's parameter list,
camelCased, and each data class Python's dataclass fields in order; the report lists each signature decided.

**Documents**
- This plan, as `docs/superpowers/plans/2026-11-03-android-port-m4-m6.md`.
- `docs/superpowers/specs/2026-11-03-politeness-crossing.md`: §4 in full.
- `docs/superpowers/specs/2026-11-03-html-parsing.md`: the parser's contract (§5.1 core.html; the probe's findings:
  CRLF and CR to LF; the LF after `<pre>` dropped; `text(deep)` with script and style data, nothing for `<br>`,
  comments out; text decoded by the HTML5 rules, attributes by the attribute rules (`&ampx` and `&amp=y` kept,
  `&amp頭` decoded); quirks mode from the doctype by the spec's lists, id and class without case in quirks mode;
  foreign content as the spec builds it; the selectors caracole uses). The probes of `<scratchpad>/plan-m4/sites-map/`
  are copied beside it as `docs/superpowers/spikes/2026-11-03-android/html-probes/` (`.py.txt`, `.java.txt`).
- `docs/superpowers/specs/2026-11-03-conformance-corpus.md`: amended with §3 (budgets in bytes, fixture references,
  scenario and page records, the three Replays registries, the new areas).
- AGENTS.md:
  - the schema-16 line under "Schema changes go through db.py" and the events' `origin` under health.py's lines;
  - under "How work is done here": a Kotlin test never reaches the network (`caracole.network=loopback`,
    `CaracoleTestRunner`, `PhoneDeps.transport`); a lane's device tests run through `android/scripts/device-test.sh`;
    big data sets only in the `bench` task;
  - under "The phone agrees with the computer to the byte": the no-JDK-text-API rule widened from `:core` to
    `:viewer` and `:server`'s ports, guarded by the shared `ForbiddenApis` check;
  - under `#### android/`: one `#####` heading per M4 area, each "Not built yet." for its lane to replace:
    `core.http, core.health, core.config` (http-client, health-pace), `core.html` (html-tree), `Lookups on the phone`
    (lookup), `Site passes on the phone` (the site lanes, one bullet each), `The Requests tab on the phone` (job-views,
    requests-feed), `Politeness across two caracoles` (crossing-phone);
  - the core/Stub.kt line (AGENTS.md:1108) removed with the file.
- docs/usage.md, under "Two caracoles": `### Politeness across two caracoles` (crossing-computer) and
  `### The phone's reads go to the computer (POST /peer/index)` (index-push), each "Not built yet.".
- android/README.md: `## Lookups on the phone` (lookup-routes), `## Performance notes` (prep-db), and the emulator's
  ANDROID_AVD_HOME, QT_QPA_PLATFORM and `-gpu host` in "Try it on an emulator".

**Python**
- db.py: schema 16 (§4.1), with `tests/test_db.py` cases (the columns, the partial index, a migrated v15 database);
  health.py `answered_any` counts own events alone (`tests/test_health.py`: an imported event of the same run
  answers nothing).
- The job kinds of the two new computer commands, whole, so the crossing lanes write commands and routes alone:
  web/jobs.py's `peer_health_job(path)` and `index_merge_job(path)` (their steps `caracole peer health --take FILE
  --progress` and `caracole index merge FILE --delete --progress`, stages, a job of no song's), status.py's
  `peer_kind` lines and outcome.py's `PEER_STEPS` for them, with test cases, and `vectors/web/job_views*` regenerated
  (AGENTS.md: a change to status.py or outcome.py moves the corpus).
- `tests/test_conformance_config.py`: writes `data/caracole/config/config.json` = `{"providers": {name: {budget
  (NO_BUDGET as 9223372036854775807), delay, enabled, lookup_delay, lookup_requests, lookup_per_hour, per_day}},
  "switchable": [...], "user_agent": DEFAULT_USER_AGENT, "match": MatchPolicy's fields, "rank": RankPolicy's}`.
- `tests/test_conformance_entities.py`: writes `data/caracole/html/entities.json` (html.entities.html5 in Python's
  order).
- `tests/conformance/budget.json` and `tests/test_corpus_budget.py` (§3).
- `tests/helpers/corpus.py`: `fixture_ref(path)`.
- `tests/helpers/scenario.py`: `record(conn, library_dir, *, fn, call, clients, answers, cache=None, now) -> dict`
  (§3's scenario record: a real `PoliteClient` per client over `httpx.MockTransport`, `time.sleep` and the pause
  recorded and skipped, the stamps fixed at `now`, `dump_fixture` before and the changed rows after), with
  `tests/test_scenario_helper.py` recording two HTTP-only records (a helper making two `client.get` calls: a miss
  and a cached hit; no site pass, so lane http-client replays them alone).
- The corpus regenerated (schema 16 moves `schema/` and every database fixture).

**Gradle, the flake, the scripts**
- `android/settings.gradle.kts` includes `:viewer`; `android/viewer/build.gradle.kts`: `kotlin("jvm")`,
  `java-test-fixtures`, serialization; `api(project(":core"))`; testFixtures of `:core`; a `Sync` task
  `copyViewerAssets` copying `../../src/caracole/viewer/` `*.js`, `*.css`, `voicings*.json` and `LICENSE-chords-db`
  byte for byte to `build/generated/assets/caracole/viewer/`, a main resource dir; a test that no copied asset holds a
  CR. (Its Kotlin declarations are skeleton-m5m6's.)
- `android/server/build.gradle.kts`: `api(project(":viewer"))`; its asset copy also takes `src/caracole/web/guitar.js`
  and `guitar.css`.
- Every module's `Test` tasks: `systemProperty("caracole.network", "loopback")` and `caracole.fixtures` (the
  absolute `tests/fixtures`, declared as an input), beside `caracole.conformance`; classes named `*Bench` excluded.
  Each JVM module gains a `bench` Test task (the `*Bench` classes alone, `maxHeapSize = "3g"`, one fork);
  `MergeSpeedTest` becomes `MergeSpeedBench` there.
- `ForbiddenApis` (core's testFixtures, from ForbiddenApiTest's check) run over `:core`, `:viewer` and `:server`
  `src/main`; a violation in :server's M1–3 code is fixed here when it is a one-line ASCII fold, else listed by file in
  the check's allow list with the lane that ports it.
- `android/app/build.gradle.kts`: `testInstrumentationRunner` = `CaracoleTestRunner`; the androidTest assets also get
  `tests/fixtures/` as `fixtures/`; `androidTestImplementation(testFixtures(project(":server")))` and `(":viewer")`;
  `apply(from = "alphatab.gradle.kts")` with an empty `android/app/alphatab.gradle.kts` (guitar-alphatab's).
- `android/flake.nix`: `CARACOLE_ALPHATAB_DIR` from `../nix/alphatab.nix` if the subflake can import it (the report
  says whether it can; else guitar-alphatab wires it).
- `android/scripts/device-test.sh [--computer DIR] [--sites SCENARIO] [--area NAME[,NAME…]] [--app] [CLASS[=DIR]]…`:
  - builds `assembleDebug assembleDebugAndroidTest` first, outside the lock;
  - then takes `flock ${CARACOLE_EMULATOR_LOCK:-${XDG_RUNTIME_DIR:-/tmp}/caracole-emulator.lock}`;
  - starts the emulator if `adb devices` shows none (`nix develop ./android#emulator`,
    `ANDROID_AVD_HOME=/home/dani/.config/.android/avd`, `QT_QPA_PLATFORM=xcb`, `LD_LIBRARY_PATH=/run/opengl-driver/lib`,
    `emulator -avd caracole -gpu host -no-snapshot-save`), waits for boot; without a display it stops and says so;
  - installs both APKs;
  - `--area` runs CorpusOnDeviceTest with `-e area …`; `--app` runs EndToEndTest, PinchTest, SyncTabTest and
    PhoneEndToEndTest, each against its own computer as the M1–3 integration ran them; `CLASS=DIR` gives a class its
    own computer (`python -m tests.helpers.e2e_library serve DIR P` on a free port, never 8737); `--computer DIR` one
    for every class; `--sites` the fake sites server (lookups-e2e fills that branch);
  - runs each class with `am instrument -w -e class …` (and `-e server`, `-e sites`); between classes `pm clear`,
    `am force-stop com.android.printspooler` and `input keyevent HOME`, so no print spooler or chooser stays up;
  - prints each result and exits non-zero on any failure; leaves the emulator running.

**Kotlin (:core and :server, M4)**
- Moved, behaviour unchanged, imports updated: `server/http/PyText.kt` → `core/py/PyText.kt` (its `lower` through
  `PyUnicode.lower`), `server/http/PyUrl.kt` → `core/py/PyUrl.kt`, `server/routes/library/PyStr.kt` →
  `core/py/PyStr.kt`, `server/http/Inline.kt` → `core/web/Inline.kt`, `server/files/DownloadNames.kt` →
  `core/web/DownloadNames.kt` (their tests with them). `PyCodec` whole over the moved decoder.
- `core/Stub.kt` deleted.
- Every M4 stub of §5.1 and §5.3 with its signature; written whole: the errors of core.http, `SharedFolder`,
  `OverridesError`, `core.config`'s data classes, each pass's stats class from Python's dataclass, the Lyrics model
  and `songLyrics`, `Match.ARTIST_PAGE` and `REVIEW_ONLY_STEPS`, `core.index.Reads`, `Asked`, `Asking`,
  `StageContext`, `StageEnd`, `SiteStage`, `CommandContext`; the site stages and command files of
  `core/lookup/sites/` neutral (each `skipped` with get.py's words for a site not asked; a command's "Not on the phone
  yet."), as is `ArtistRoute` (not found); `Database.checkpoint` and `warmUp` no-ops; `JobQueue.onEnd`,
  `JobContext.yieldToQueued` declared (jobs-queue's to fill); `PhoneKinds` with its (empty, M4) table.
- Assembly.kt for M4 as §5.3 says: `PhoneDeps` with `transport` required and read per request, `searchesLacuerda`;
  every M4 module and runner wired; the seams `SongPages.NONE` and `SongbookPages.NONE`; the checkpoint after an
  import; `SyncEngine`'s index stage calls `database.checkpoint()` after its merge; `warmUp()` launched on IO at start;
  an `afterJob` hook on `JobQueue.onEnd` (the search invalidated; `Alerts.failed` for a failed job);
  `AppConfig.libraryName` a supplier (`{ PhoneConfig.read(db).libraryName.orEmpty() }`); `PhoneConfig.read` neutral =
  `DEFAULTS` until health-pace; `ServerControls.guitar` (false; LibraryPage sends it as `server.guitar`).
- Every new M4 route module neutral: the same 409 "… isn't on the phone yet." the Stubs gave (the entry moves from
  `Stubs.FORMS`/`PAGES` to the module that will answer it). LookupRoutes' neutral declares `/fetch`, `/lacuerda/artist`,
  `/lacuerda/search`, `/harptabs/artist` and `/versions/keep-more`; `/lookup` and `/request` stay LibraryRoutes' until
  lookup-routes moves them; RequestsRoutes declares `/requests.json` and `/jobs/again`. The dead `/request`, `/lookup`
  and `/remove` entries of Stubs go.
- `AssemblyTest` rewritten to assert the wiring alone (the modules' order, every route answered by one module), never
  a neutral answer.
- Callers given a transport: the app (`RealTransport`, or `sitesForTests`), e2e's `ScenarioPhone` and every test that
  builds a `Phone` (a transport that throws `TransportError("refused", …)`).
- testFixtures of `:core` (`core/testing/`): `FakeTransport(answers)` (working: serves the map, records every request,
  fails an unanswered one), `FakeAsking(clients)` (working), `Corpus.fixture(path)` (working), `ForbiddenApis`,
  `Replays` with `interface AreaReplay { val area: String; fun replay(misses: Misses) }` and one neutral object per M4
  area of §3, each in its own file named in its lane's owns, and `Scenarios.replay` declared
  (`TODO("lane http-client")`); `server/testing/`: `ServerReplays` with its M4 areas.
- `CorpusOnDeviceTest` parameterized by area over `Replays.all` and `ServerReplays.all` (and `ViewerReplays.all` once
  skeleton-m5m6 adds it), `-e area` picking some.
- The app: `CaracoleTestRunner` (§5.5); `Caracole`'s transport, `sitesForTests`, `searchesLacuerdaForTests`, the
  phone's `Alerts` (`Alerts.NONE` until alerts-backups), `version` from `BuildConfig.VERSION_NAME`.
- One trivial test per new package.

skeleton-m4 is done when:
- `nix develop -c pytest -q` passes, and `tests/test_corpus_budget.py` with it;
- `nix develop ./android -c gradle -p android test assembleDebug assembleDebugAndroidTest` passes, and `bench`;
- every M4 signature of §5 compiles; `git grep -n 'TODO("lane'` lists only lane-owned files, each naming its lane;
- `ForbiddenApis` passes over `:core`, `:viewer` and `:server`;
- `nix build .#checks.x86_64-linux.package` passes (the package's fileset holds every new test's files, or the test
  skips without them);
- `android/scripts/device-test.sh --area` (every registered area) and `--app` pass on the emulator, and a device test
  that the app under `CaracoleTestRunner` opens no socket to a site;
- `CARACOLE_ANDROID_E2E=1 nix develop -c pytest -q -n 0 tests/test_android_e2e.py` passes (the scenario unchanged:
  Get it and Fetch now still add only, since LookupRoutes is neutral).

### 6.2 skeleton-m5m6

A lane-shaped skeleton step (§7.1's first lane, `android/m5m6-skeleton`), the first filler beside M4's first wave. No
M4 lane owns any of its files; while it runs it owns Assembly.kt, Stubs.kt, PhoneKinds.kt and the registries. It adds:
- every §5.2 signature in `:viewer` as a stub, `ViewerReplays` with one neutral replay per M5 area (§3), `Voicings.TUNING`
  whole;
- M6's `core.songbooks`, `core.inbox` and `core.backup` stubs (`SongbookError` whole), M6's route modules neutral
  (SongbookRoutes, VersionsRoutes, HarmonicaRoutes, ReviewRoutes, ExportRoutes, GuitarRoutes), the Stubs' M6 entries
  moved into them (Stubs keeps YouTube's routes and `GET /lookup` alone), M6's runners neutral (harmonica, render,
  review, inbox, backup, songbook), `ServerReplays`' M6 areas;
- `PhoneKinds`' entries for render, inbox, backup and restore (§5.3's table);
- Assembly's M5 and M6 wiring: `PhoneRender` as the pdf stage's `SongPages`, `SongbookPagesImpl` as `SongbookPages`,
  `afterSync` calling `PhoneRender.afterSync()`, a render job queued at start when `PhoneRender.renderStale()` says
  so (neutral false), the inbox's staged files retried in `afterJob` (`InboxRetry`), JobsRoutes' songbooks source;
- the app's M6 hooks of §5.5 (MainActivity's three, the manifest's ShareActivity and BackupsActivity, the alerts
  channel, Settings' Backups row), each target a stub class (`ShareActivity` finishes at once, `BackupsActivity` says
  "Not built yet.", `Printer.print` and `AlphaTabAssets.answer` return nothing), `Links.Route.Print`;
- AGENTS.md's and android/README.md's M5 and M6 headings, each "Not built yet.": `:viewer` (each M5 lane a bullet),
  `The phone's written pages` (written-pages), `Songbooks, versions and printing on the phone` (songbook-routes,
  versions-harmonica, export-print), `Guitar Pro on the phone` (guitar-alphatab), `Files shared to the app`
  (inbox-share), `Alerts and backups on the phone` (alerts-backups); README's `## Pages built on the phone`,
  `## Songbooks, versions and printing`, `## Guitar Pro`, `## Sharing files to caracole`, `## Alerts and backups`.

It is done when its lane's done_when (§7.1) holds.

---

## 7. The lanes

### 7.0 How a lane works

M1–3's model, with what it taught.

**Worktrees and branches.**
- Each lane works in `.claude/worktrees/<name>` on the branch it names, made from main:
  `git -C /home/dani/Projects/caracole worktree add .claude/worktrees/<name> -b <branch> main`, or reuses both.
- **Groups.** Lanes that name the same branch form a group and run in turn, each depending on the one before; their
  worktree is named after the branch, and each lane of a group merges into main when its own done_when holds, so the
  next starts from main merged in:
  - android/html: html-tokenizer → html-tree;
  - android/ug-fetch: ug-fetch-sheet → ug-fetch-artist (the seam: `ArtistRoute`, the skeleton's stub);
  - android/lacuerda: lacuerda-pages → lacuerda-sheets;
  - android/requests: job-views → requests-feed;
  - android/sync-crossing: crossing-computer → crossing-phone → index-push;
  - android/harmony: harmony → harmony-progressions;
  - android/harptab: harptab-read → harptab-layout;
  - android/render: phone-render → written-pages;
  - android/songbooks: songbook-writers → songbook-entries → songbook-routes.
- Nothing is checked out in the main checkout, and nothing touches its uncommitted files.
- A new file is `git add`ed before any Nix build.

**Phases.** As M1–3: Phase A (when `start_early`) does what the brief names against the skeleton's declarations, commits,
and reports `waiting on: <lanes>`; Phase B, once every producer has merged, merges main in and finishes. A Phase A
guard (a test skipped while a producer is missing) names its producer and is removed in Phase B; none is left at the
merge (`git grep -n 'waiting on\|Assume.*lane'` finds none of the lane's).

**Path shorthand** (the structured lane list's; §7.1 writes paths whole): `K/`, `KT/`, `KF/` are :core's
`src/main/kotlin/…/caracole/core/`, `src/test/…/core/` and `src/testFixtures/…/core/testing/`; `S/`, `ST/`, `SF/` and
`V/`, `VT/`, `VF/` the same of :server and :viewer; `A/` and `AT/` :app's main and androidTest; `E/` :e2e's tests;
`MIR/` :mirror's main; `CV/` and `CD/` `tests/conformance/vectors/` and `data/caracole/`.

**Signatures.** A signature §5 elides takes the Python function's parameter list, camelCased, and a data class
Python's dataclass fields in order; a lane changes a declared signature only with the consumers it breaks named in its
report.

**Merging.** `git -C /home/dani/Projects/caracole merge --no-ff <branch>` once every done_when holds with main merged
in; wait and retry on `.git/index.lock`; never force, never rebase main, never merge a failing done_when. The report
gives the merge commit. After each lane, a review and a fix pass run before its merge (M1–3's reviews found majors in
13 of 21 groups).

**Drift.** A lane that regenerates any vector runs `nix develop ./android -c gradle -p android test` before merging
and follows the spec's drift protocol: a Kotlin test that breaks is the Kotlin side's to follow first.

**The shared machine** (24 cores, 62 GB, one /dev/shm):
- At most 6 lanes at once. The loop: `nix develop -c pytest -q -n 4 -m "not slow" <tests>` and
  `nix develop ./android -c gradle -p android <module>:test`; Gradle at 4 workers.
- The whole suite (`nix develop -c pytest -q`) once before merging; `nix build .#checks.x86_64-linux.package` before
  merging any lane that added or changed a file under `tests/` (M1–3's integration found 72 collection errors there).
- Nobody runs `gradle --stop` or kills a daemon they didn't start, nor `omnibin-shell`.
- No test sends a request to a site: Kotlin's `RealTransport` refuses any host but loopback under every Gradle test
  task, Python's tests use fakes, the e2e and the device use the fake sites server.
- No `caracole serve` on port 8737 (the owner's service).
- **The emulator.** One, shared. A lane marked `device` runs its area and classes only through
  `android/scripts/device-test.sh` (`--area NAME` for its corpus area, `--app` for the app's four M1–3 classes,
  `CLASS[=DIR]` for its own), which builds first and then holds
  `flock ${CARACOLE_EMULATOR_LOCK:-${XDG_RUNTIME_DIR:-/tmp}/caracole-emulator.lock}` while it installs and runs, starts
  the emulator if none is up and leaves it up. A lane that finds it stuck waits; it never starts another.
- **Which lanes run what on the device.** Every lane that fills a replay runs its area; every lane that changes
  :server's routes or pages, or :app, also runs `--app` (EndToEndTest, PinchTest, SyncTabTest, PhoneEndToEndTest)
  before it merges; every Kotlin-side lane builds `assembleDebugAndroidTest`, which compiles the testFixtures for ART.
- **Benchmarks.** A data set of more than a few thousand rows runs only in a `*Bench` class of the gated `bench` task
  (`nix develop ./android -c gradle -p android bench`, a 3 GiB heap, one fork), never in `test`.

**Docs.** In the same commit as the behaviour. AGENTS.md, docs/usage.md and android/README.md are owned by section:
the skeleton wrote each lane's heading, and the lane replaces "Not built yet." under its own heading alone.

**Commits.** Conventional, scoped by area (`feat(android): …`, `feat(peer): …`, `fix(fetch): …`,
`test(conformance): …`, `docs: …`). No Claude or AI attribution anywhere.

**Shared files.** Lanes own disjoint files, but for files owned in turn, each pair in a depends_on chain:
- `server/routes/search/Found.kt`: lookup-routes (lacuerda_search, searchesLacuerda) → library-cards (progression);
- `server/page/MirrorPageData.kt` and its test: lookup-routes → library-cards;
- `core/sync/SyncEngine.kt`, `PeerClient.kt`, `SyncEngineTest.kt`, `FakeComputer.kt`, `web/peer_routes.py`,
  `peer_push.py`, `tests/test_web_peer.py`: the android/sync-crossing group, in turn;
- `tests/helpers/e2e_library.py`, `tests/test_android_e2e.py`, `android/e2e/**`: lookups-e2e → pages-e2e (lookup-routes
  edits only PhoneScenarioTest's phase-2 lines before both);
- `android/app/src/androidTest/…/PhoneEndToEndTest.kt`: lookup-routes alone (its Get it and typed-query lines);
- `tests/test_conformance_py.py`, `PyReplay.kt`: py-sites → py-format; `tests/helpers/scenario.py`: skeleton-m4 →
  lookup-scenarios (the whole-lookup recorder beside `record`);
- within each group: the files its lanes name "in turn" (`core/html/**`, `core/ug/internal/fetch/**`,
  `core/lacuerda/**`'s replay and generator, `viewer/harmony/**`, `viewer/harptab/**`, `viewer/render/**`,
  `core/songbooks/**`, `tests/test_conformance_songbook_tab.py`).

**The common must-not-touch list** (every lane's, beside its own):

- android/server/src/main/kotlin/io/github/danielhp95/caracole/server/Assembly.kt, android/server/src/main/kotlin/io/github/danielhp95/caracole/server/routes/Stubs.kt, android/server/src/main/kotlin/io/github/danielhp95/caracole/server/jobs/PhoneKinds.kt and the three Replays registries (the skeletons'; a lane that must change one is named in its brief)
- android/settings.gradle.kts and every android/*/build.gradle.kts, android/flake.nix, android/scripts/device-test.sh (the skeletons'; lookups-e2e alone fills the script's --sites branch)
- android/app/src/main/AndroidManifest.xml, MainActivity.kt's hooks and CaracoleTestRunner (the skeletons')
- tests/conformance/budget.json
- AGENTS.md, docs/usage.md and android/README.md outside the lane's own heading
- src/caracole/library_assets/sync.js, sync-tab.html, sync-panel.html, sync.css (the sync redesign's)
- src/caracole/library_assets/rows.js, card.js, library.js and their css (the instrument buttons' design)
- android/app/src/main/res/menu/main.xml and the Settings sync rows (the sync redesign's)
- any other lane's owns
- the main checkout's uncommitted files (improvements.md, android_port.md, run.sh, temp.sh)

In short (A: has a Phase A):

| Lane | Branch | Side | M | Depends on | Early | Device | ~Lines |
|---|---|---|---|---|---|---|---|
| skeleton-m5m6 | android/m5m6-skeleton | mixed | M5 | – | – | yes | 2200 |
| prep-core | android/prep-core | mixed | M4 | – | – | yes | 800 |
| prep-db | android/prep-db | kotlin | M4 | – | – | yes | 900 |
| device-replays | android/device-replays | kotlin | M4 | – | – | yes | 900 |
| py-sites | android/py-sites | mixed | M4 | – | – | yes | 1700 |
| py-format | android/py-format | mixed | M4 | py-sites | – | yes | 1200 |
| html-tokenizer | android/html | mixed | M4 | – | – | yes | 2000 |
| html-tree | android/html | mixed | M4 | html-tokenizer | – | yes | 2300 |
| http-client | android/http-client | mixed | M4 | – | – | yes | 2400 |
| health-pace | android/health-pace | mixed | M4 | http-client | A | yes | 1700 |
| library-writes | android/library-writes | mixed | M4 | – | – | yes | 1800 |
| overrides-model | android/overrides-model | mixed | M4 | – | – | yes | 1900 |
| ug-pages | android/ug-pages | mixed | M4 | html-tree, py-sites, http-client | A | yes | 1700 |
| rank-coverage | android/rank-coverage | mixed | M4 | library-writes | A | yes | 1400 |
| ug-fetch-sheet | android/ug-fetch | mixed | M4 | ug-pages, rank-coverage, http-client, library-writes, overrides-model | A | yes | 2200 |
| ug-fetch-artist | android/ug-fetch | mixed | M4 | ug-fetch-sheet | – | yes | 1800 |
| matcher | android/matcher | mixed | M4 | library-writes, overrides-model | A | yes | 2400 |
| lyrics | android/lyrics | mixed | M4 | http-client, py-sites, py-format, library-writes, overrides-model | A | yes | 2300 |
| lacuerda-pages | android/lacuerda | mixed | M4 | html-tree, http-client, health-pace, py-sites | A | yes | 1700 |
| lacuerda-sheets | android/lacuerda | mixed | M4 | lacuerda-pages, library-writes, overrides-model, rank-coverage | – | yes | 1500 |
| harptabs | android/harptabs | mixed | M4 | html-tree, http-client, library-writes, overrides-model, py-sites | A | yes | 1600 |
| gametabs | android/gametabs | mixed | M4 | html-tree, http-client, library-writes, overrides-model, py-sites | A | yes | 1300 |
| tab-files | android/tab-files | mixed | M4 | html-tree, http-client, library-writes, overrides-model | A | yes | 1600 |
| jobs-queue | android/jobs-queue | kotlin | M4 | – | – | yes | 1700 |
| job-views | android/requests | mixed | M4 | jobs-queue | A | yes | 1900 |
| requests-feed | android/requests | mixed | M4 | job-views | – | yes | 1300 |
| lookup | android/lookup | mixed | M4 | health-pace, jobs-queue, overrides-model, library-writes | A | yes | 2200 |
| lookup-scenarios | android/lookup-scenarios | mixed | M4 | lookup, matcher, ug-fetch-artist, lyrics, lacuerda-sheets, harptabs, gametabs, tab-files | A | yes | 1500 |
| lookup-routes | android/lookup-routes | mixed | M4 | lookup, job-views, lacuerda-pages, health-pace | A | yes | 2000 |
| crossing-computer | android/sync-crossing | python | M4 | – | – | – | 1800 |
| crossing-phone | android/sync-crossing | kotlin | M4 | crossing-computer, health-pace | A | yes | 1600 |
| index-push | android/sync-crossing | mixed | M4 | crossing-phone | A | yes | 1600 |
| lookups-e2e | android/lookups-e2e | mixed | M4 | lookup-routes, index-push, lookup-scenarios | A | yes | 1800 |
| theory | android/theory | mixed | M5 | skeleton-m5m6 | A | yes | 2600 |
| sheet-keys | android/sheet-keys | mixed | M5 | skeleton-m5m6, theory, py-sites, py-format | A | yes | 2600 |
| shapes-harp-winds | android/shapes-harp-winds | mixed | M5 | skeleton-m5m6, theory | A | yes | 2400 |
| chinese | android/chinese | mixed | M5 | skeleton-m5m6, theory | A | yes | 2300 |
| harmony | android/harmony | mixed | M5 | skeleton-m5m6, theory | A | yes | 1700 |
| harmony-progressions | android/harmony | mixed | M5 | harmony | – | yes | 1500 |
| version-progressions | android/version-progressions | mixed | M5 | skeleton-m5m6, theory, sheet-keys, harmony-progressions, shapes-harp-winds | A | yes | 2500 |
| harptab-read | android/harptab | mixed | M5 | skeleton-m5m6, shapes-harp-winds, theory | A | yes | 2000 |
| harptab-layout | android/harptab | mixed | M5 | skeleton-m5m6, harptab-read | A | yes | 1600 |
| pages | android/pages | mixed | M5 | skeleton-m5m6, harmony-progressions, shapes-harp-winds, chinese, sheet-keys | A | yes | 2300 |
| harmonica-page | android/harmonica-page | mixed | M5 | skeleton-m5m6, harptab-layout, pages, py-format | A | yes | 1900 |
| phone-render | android/render | mixed | M5 | skeleton-m5m6, pages, harmonica-page, version-progressions, sheet-keys, chinese, lookup, library-writes, jobs-queue | A | yes | 2200 |
| written-pages | android/render | mixed | M5 | phone-render | – | yes | 1100 |
| library-cards | android/library-cards | mixed | M5 | skeleton-m5m6, phone-render, matcher, ug-pages, rank-coverage, tab-files, version-progressions, chinese, lookup-routes | A | yes | 2400 |
| pages-e2e | android/pages-e2e | mixed | M5 | library-cards, written-pages, lookups-e2e | A | yes | 1300 |
| songbook-writers | android/songbooks | mixed | M6 | skeleton-m5m6 | A | yes | 1500 |
| songbook-entries | android/songbooks | mixed | M6 | songbook-writers, version-progressions, pages, written-pages | A | yes | 2100 |
| songbook-routes | android/songbooks | mixed | M6 | songbook-entries, job-views, lookup | – | yes | 1300 |
| versions-harmonica | android/versions-harmonica | mixed | M6 | skeleton-m5m6, ug-fetch-artist, lookup, phone-render, harptab-layout, overrides-model, job-views | A | yes | 1800 |
| guitar-alphatab | android/guitar-alphatab | mixed | M6 | skeleton-m5m6 | – | yes | 1300 |
| export-print | android/export-print | mixed | M6 | skeleton-m5m6, version-progressions, phone-render, overrides-model, job-views | A | yes | 1300 |
| review | android/review | mixed | M6 | skeleton-m5m6, matcher, library-cards, lookup, overrides-model, job-views | A | yes | 1200 |
| inbox-share | android/inbox-share | mixed | M6 | skeleton-m5m6, library-writes, matcher, lookup, tab-files | A | yes | 1500 |
| alerts-backups | android/alerts-backups | kotlin | M6 | skeleton-m5m6, lookup, jobs-queue, crossing-phone, written-pages | A | yes | 1700 |

### 7.1 Each lane in full

#### skeleton-m5m6: The second skeleton step: M5's and M6's declarations

- Branch `android/m5m6-skeleton` · mixed · M5 · about 2200 lines · depends on – · device
- Goal: Every M5 and M6 signature of §5 compiles as a neutral stub, :viewer's registry and M6's route modules are wired, and the app's M6 hooks are in place, so M5 and M6 lanes code against them while M4 builds.
- Owns: `android/viewer/src/main/kotlin/io/github/danielhp95/caracole/viewer/** (stubs only, every file then a lane's)`; `android/viewer/src/testFixtures/kotlin/io/github/danielhp95/caracole/viewer/testing/ViewerReplays.kt`; `android/viewer/src/testFixtures/kotlin/io/github/danielhp95/caracole/viewer/testing/replays/*.kt (neutral, then each lane's)`; `android/core/src/main/kotlin/io/github/danielhp95/caracole/core/songbooks/** (stubs)`; `android/core/src/main/kotlin/io/github/danielhp95/caracole/core/inbox/** (stubs)`; `android/core/src/main/kotlin/io/github/danielhp95/caracole/core/backup/** (stubs)`; `android/server/src/main/kotlin/io/github/danielhp95/caracole/server/routes/{SongbookRoutes,VersionsRoutes,HarmonicaRoutes,ReviewRoutes,ExportRoutes,GuitarRoutes}.kt (neutral)`; `android/server/src/main/kotlin/io/github/danielhp95/caracole/server/songbooks/** (stubs)`; `android/server/src/main/kotlin/io/github/danielhp95/caracole/server/guitar/** (stubs)`; `android/server/src/main/kotlin/io/github/danielhp95/caracole/server/lookups/{HarmonicaRunner,RenderRunner,ReviewRunner,InboxRunner,BackupRunner}.kt (neutral)`; `android/server/src/main/kotlin/io/github/danielhp95/caracole/server/Assembly.kt (M5 and M6 wiring)`; `android/server/src/main/kotlin/io/github/danielhp95/caracole/server/routes/Stubs.kt (M6 entries moved out)`; `android/server/src/main/kotlin/io/github/danielhp95/caracole/server/jobs/PhoneKinds.kt (render, inbox, backup, restore)`; `android/server/src/testFixtures/kotlin/io/github/danielhp95/caracole/server/testing/ServerReplays.kt (M6 areas)`; `android/server/src/testFixtures/kotlin/io/github/danielhp95/caracole/server/testing/replays/{Cards,SongbookTab,Choices,Guitar,Export,Review}Replay.kt (neutral)`; `android/core/src/testFixtures/kotlin/io/github/danielhp95/caracole/core/testing/Replays.kt (Songbook, Inbox)`; `android/core/src/testFixtures/kotlin/io/github/danielhp95/caracole/core/testing/replays/{Songbook,Inbox}Replay.kt (neutral)`; `android/app/src/main/AndroidManifest.xml (ShareActivity, BackupsActivity, the alerts channel's use)`; `android/app/src/main/kotlin/io/github/danielhp95/caracole/MainActivity.kt (the three hooks of §5.5 only)`; `android/app/src/main/kotlin/io/github/danielhp95/caracole/{ShareActivity,BackupsActivity,Printer,AlphaTabAssets,AndroidAlerts}.kt (stubs)`; `android/app/src/main/kotlin/io/github/danielhp95/caracole/SettingsActivity.kt (the Backups row only)`; `android/app/src/main/res/layout/activity_settings.xml (the Backups row only)`; `android/mirror/src/main/kotlin/io/github/danielhp95/caracole/mirror/Links.kt (Route.Print)`; `AGENTS.md (the M5 and M6 headings)`; `android/README.md (the M5 and M6 headings)`
- Must not touch: §7.0's common list
- Provides: every §5.2 signature and the M6 ones of §5.1, §5.3 and §5.5 as stubs; ViewerReplays with one neutral AreaReplay per M5 area; the M6 route modules neutral (each answering its Stubs' 409); PhoneKinds' M5 and M6 entries (§5.3's table); the app's M6 hooks
- Consumes: skeleton-m4's :viewer module, copyViewerAssets, Replays, Phone and PhoneParts
- Tests: android/viewer/src/test/kotlin/io/github/danielhp95/caracole/viewer/ViewerSkeletonTest.kt; android/server/src/test/kotlin/io/github/danielhp95/caracole/server/AssemblyTest.kt (the M5 and M6 modules' order)
- Done when: nix develop ./android -c gradle -p android test passes; nix develop ./android -c gradle -p android assembleDebug assembleDebugAndroidTest passes; every §5.2 signature and every M6 signature of §5 compiles; git grep -n 'TODO("lane' lists only lane-owned files, each naming its lane; AssemblyTest: every route of the M6 modules is answered by one module, the Stubs keep only YouTube's routes and GET /lookup; CARACOLE_ANDROID_E2E=1 nix develop -c pytest -q -n 0 tests/test_android_e2e.py passes, unchanged; android/scripts/device-test.sh passes; android/scripts/device-test.sh --app passes (EndToEndTest, PinchTest, SyncTabTest and PhoneEndToEndTest, each against its own computer, as the M1-3 integration ran them); nix develop -c pytest -q passes; nix build .#checks.x86_64-linux.package passes

Brief:

> Repo /home/dani/Projects/caracole. Lane skeleton-m5m6, branch android/m5m6-skeleton, worktree .claude/worktrees/m5m6-skeleton. Read docs/superpowers/plans/2026-11-03-android-port-m4-m6.md §7.0 first: its rules bind you. Depends on: none (after skeleton-m4). Runs whole at once. Device lane: android/scripts/device-test.sh alone runs your area and classes.
>
> Plan sections: §5.2, §5.3, §5.5, §6.2 (this step in full). The second half of the skeleton: what M5 and M6 lanes code against. It runs as the first filler beside M4's first wave (§8); no M4 lane owns any of its files, and it owns Assembly.kt, Stubs.kt, PhoneKinds.kt and the registries while it runs. Do §6.2 exactly: every §5.2 signature as a stub (TODO("lane <id>")) or the neutral answer named; the elided signatures take the Python function's parameter list, camelCased, and data classes Python's dataclass fields in order (list in your report each signature you decided); ViewerReplays and one neutral replay per M5 area; the M6 route modules neutral with the Stubs' 409 entries moved into them; the M6 runners neutral; PhoneKinds' entries for render, inbox, backup and restore with §5.3's words; Assembly's M5 and M6 wiring (PhoneRender as the pdf stage's SongPages, SongbookPages, afterSync's render, the render-stale job, the inbox retry after each job, Alerts.failed for a job that failed); the app's hooks of §5.5 (MainActivity's shouldInterceptRequest to AlphaTabAssets.answer, shouldOverrideUrlLoading and the DownloadListener routing Links.Route.Print to Printer.print; the manifest's ShareActivity with ACTION_SEND and SEND_MULTIPLE for stream MIME types only and BackupsActivity; Settings' Backups row apart from the sync rows), each target a stub class. One trivial test per new package.
> Commit: build(android): the second skeleton step, M5's and M6's declarations.

#### prep-core: One copy of each shared helper, and the small fixes

- Branch `android/prep-core` · mixed · M4 · about 800 lines · depends on – · device
- Goal: Stamps, noOnes and PINYIN_PARTIAL_SCALE ported once; the phone's title no longer says Phone twice; android/README says how to run, install and import.
- Owns: `android/core/src/main/kotlin/io/github/danielhp95/caracole/core/index/Stamps.kt`; `android/core/src/main/kotlin/io/github/danielhp95/caracole/core/library/internal/Stamps.kt`; `android/core/src/main/kotlin/io/github/danielhp95/caracole/core/sync/internal/client/Stamps.kt`; `android/core/src/main/kotlin/io/github/danielhp95/caracole/core/lacuerda/IsoTime.kt`; `android/core/src/main/kotlin/io/github/danielhp95/caracole/core/names/Known.kt (noOnes only)`; `android/core/src/main/kotlin/io/github/danielhp95/caracole/core/sites/Sites.kt (SiteText.noOnes only)`; `android/core/src/main/kotlin/io/github/danielhp95/caracole/core/search/Search.kt (noOnes only)`; `android/core/src/main/kotlin/io/github/danielhp95/caracole/core/search/internal/query/QueryRules.kt`; `android/core/src/main/kotlin/io/github/danielhp95/caracole/core/lacuerda/LaCuerdaFind.kt (PINYIN_PARTIAL_SCALE only)`; `android/core/src/main/kotlin/io/github/danielhp95/caracole/core/keys/Normalize.kt (PINYIN_PARTIAL_SCALE only)`; `android/server/src/main/kotlin/io/github/danielhp95/caracole/server/http/App.kt (AppConfig's name)`; `android/server/src/main/kotlin/io/github/danielhp95/caracole/server/http/MessagePage.kt`; `android/server/src/main/kotlin/io/github/danielhp95/caracole/server/http/LibraryName.kt`; `android/server/src/test/kotlin/io/github/danielhp95/caracole/server/http/LibraryNameTest.kt`; `android/core/src/test/kotlin/io/github/danielhp95/caracole/core/index/StampsTest.kt`; `android/server/src/testFixtures/kotlin/io/github/danielhp95/caracole/server/testing/replays/LibraryNameReplay.kt`; `tests/test_conformance_library_name.py`; `tests/conformance/vectors/web/library_name.jsonl`; `android/README.md (its 'Try it on an emulator' and install and import steps)`
- Must not touch: §7.0's common list
- Provides: core.index.Stamps, the one port of stamps.py; UgHits.noOnes, the one noOnes (Search, SiteText and Known delegate); Normalize.PINYIN_PARTIAL_SCALE, the one copy; LibraryName rendering of an empty or computer-given name with the Phone badge
- Consumes: AppConfig.libraryName: () -> String (the skeleton's); PhoneConfig.read(db).libraryName (neutral DEFAULTS until health-pace)
- Tests: android/core/src/test/kotlin/io/github/danielhp95/caracole/core/index/StampsTest.kt; android/server/src/test/kotlin/io/github/danielhp95/caracole/server/http/LibraryNameTest.kt; tests/test_conformance_library_name.py
- Done when: nix develop ./android -c gradle -p android test passes; nix develop ./android -c gradle -p android assembleDebug assembleDebugAndroidTest passes; nix develop -c pytest -q -n 0 tests/test_conformance_library_name.py passes (check mode); nix develop -c pytest -q tests/test_corpus_budget.py passes; git grep finds one Kotlin port of stamps.parse (core.index.Stamps), one noOnes body and one PINYIN_PARTIAL_SCALE; the phone's header and <title> are 'caracole · Phone' with no name and 'caracole · <name> · Phone' with one, byte for byte as library_name.LibraryName writes them; android/scripts/device-test.sh --area library_name passes; nix develop -c pytest -q passes; nix build .#checks.x86_64-linux.package passes

Brief:

> Repo /home/dani/Projects/caracole. Lane prep-core, branch android/prep-core, worktree .claude/worktrees/prep-core. Read docs/superpowers/plans/2026-11-03-android-port-m4-m6.md §7.0 first: its rules bind you. Depends on: none (after skeleton-m4). Runs whole at once. Device lane: android/scripts/device-test.sh alone runs your area and classes.
>
> Plan sections: §1 (the small fixes), §5.1 (core.py, Stamps), §6. The findings' small fixes, and the M1-3 lesson that shared helpers multiplied.
> Do: (1) core.index.Stamps is the one port of stamps.py: delete core/library/internal/Stamps.kt, core/sync/internal/client/Stamps.kt and lacuerda/IsoTime.kt and point their callers at it; library/stamps.jsonl and index/stamps.jsonl must still pass. (2) noOnes is defined once, in search/internal/ug/UgHits.kt; Search.noOnes already delegates; Sites.kt's SiteText.noOnes and names/Known.kt's delegate too. (3) PINYIN_PARTIAL_SCALE moves to Normalize, as normalize.py holds it; QueryRules.kt and LaCuerdaFind.kt read it there. (LaCuerda's LETTERS and lettersText are already one copy since M2: Looked.kt reads them; nothing to do.) (4) The title: AppConfig.libraryName is a supplier (the skeleton's); with no name taken from the computer yet the header and title are 'caracole' with the 'Phone' badge, never 'Phone · caracole · Phone'; with a name, as Python's LibraryName writes it. Write tests/test_conformance_library_name.py recording library_name.LibraryName's markup and title for no name, 'Music' and a name with markup characters, the badge 'Phone', into vectors/web/library_name.jsonl; fill LibraryNameReplay and make LibraryName match. (5) android/README.md: install the debug APK, open it, import the index (from the computer, or a file). Leave the request form's hint alone (true once lookup-routes lands). The Sites tab's empty state before the first sync needs sites.js, a shared asset: left (§11's list of what is left).
> Commit: refactor(android): one port of each shared helper; fix(android): the phone's title names caracole once.

#### prep-db: The WAL after a merge, and the cold first search

- Branch `android/prep-db` · kotlin · M4 · about 900 lines · depends on – · device
- Goal: A merge leaves no large WAL behind; the first search after an import or a start is measured on a big index and brought close to a warm one.
- Owns: `android/core/src/main/kotlin/io/github/danielhp95/caracole/core/db/Database.kt`; `android/core/src/main/kotlin/io/github/danielhp95/caracole/core/db/Warmup.kt`; `android/core/src/main/kotlin/io/github/danielhp95/caracole/core/db/Timings.kt`; `android/core/src/main/kotlin/io/github/danielhp95/caracole/core/search/Vocabulary.kt`; `android/core/src/main/kotlin/io/github/danielhp95/caracole/core/index/IndexTransfer.kt (the merge's end hook only: FTS5 optimize)`; `android/core/src/test/kotlin/io/github/danielhp95/caracole/core/db/CheckpointTest.kt`; `android/core/src/test/kotlin/io/github/danielhp95/caracole/core/db/CheckpointBench.kt`; `android/core/src/test/kotlin/io/github/danielhp95/caracole/core/db/ColdSearchBench.kt`; `android/app/src/androidTest/kotlin/io/github/danielhp95/caracole/ColdSearchTest.kt`; `android/README.md (## Performance notes)`
- Must not touch: §7.0's common list
- Provides: Database.checkpoint(truncate); Database.warmUp(); journal_size_limit and a start-up checkpoint
- Consumes: IndexTransfer.merge; core.search's vocabularies and FTS reads; the skeleton's calls: Assembly.importIndex and SyncEngine's index stage call checkpoint(); Phone's start launches warmUp() on Dispatchers.IO
- Tests: android/core/src/test/kotlin/io/github/danielhp95/caracole/core/db/CheckpointTest.kt; android/core/src/test/kotlin/io/github/danielhp95/caracole/core/db/CheckpointBench.kt; android/core/src/test/kotlin/io/github/danielhp95/caracole/core/db/ColdSearchBench.kt; android/app/src/androidTest/kotlin/io/github/danielhp95/caracole/ColdSearchTest.kt
- Done when: nix develop ./android -c gradle -p android test passes; nix develop ./android -c gradle -p android assembleDebug assembleDebugAndroidTest passes; nix develop ./android -c gradle -p android bench passes (the gated benchmarks, their own heap); CheckpointTest (in test, a few thousand rows): checkpoint() truncates the WAL and every reader still reads; CheckpointBench (in bench): after IndexTransfer.merge of 200,000 ug_index rows and checkpoint(), the -wal file is at most journal_size_limit (set at open; at most 64 MiB); ColdSearchBench (JVM, bench) and ColdSearchTest (emulator) measure /api/search's first answer after a reopen over a synthetic index of at least 300,000 ug_index rows, before and after the fix; the numbers and what was cold are in android/README.md's Performance notes; on the emulator the first search after a reopen answers within 3 s, or within twice the warm time, whichever is larger; android/scripts/device-test.sh io.github.danielhp95.caracole.ColdSearchTest passes

Brief:

> Repo /home/dani/Projects/caracole. Lane prep-db, branch android/prep-db, worktree .claude/worktrees/prep-db. Read docs/superpowers/plans/2026-11-03-android-port-m4-m6.md §7.0 first: its rules bind you. Depends on: none (after skeleton-m4). Runs whole at once. Device lane: android/scripts/device-test.sh alone runs your area and classes.
>
> Plan sections: §1, §5.1 (core.db additions), §6 (the skeleton's calls), §9 (what a real phone shows). The findings: on the owner's phone the WAL was left at 387 MB after the import, and the first search after an import or a start took more than 30 s, holding every search behind it.
> Do: (1) Database.checkpoint(truncate = true): PRAGMA wal_checkpoint(TRUNCATE) on the writer once no reader holds a snapshot (Database.read rolls each block back, so the pool holds none between reads); a journal_size_limit pragma at open; at open, a checkpoint when the WAL is over the limit. (2) Measure first: a timing of each step of the first search (Timings.kt, behind a debug flag, never in a page) over a big synthetic index on the JVM and on the emulator: candidates are WAL recovery and cold pages through a big WAL, Vocabulary.among's first read of ug_key_words, Close's ug_artist_words, the FTS5 segments of a fresh merge (no 'optimize'), the lazy data loads (pinyin, Unicode tables, PyRegex compiles). (3) Then the fix the numbers point to: Database.warmUp() (the skeleton launches it at start, on IO, through the reader pool, never holding the search lock), mmap_size or cache_size on the readers, FTS5 'optimize' after a UG merge (IndexTransfer.kt's merge end, your one line there; index-push's export lives in Export.kt). Big data sets run only in the gated `bench` task (classes named *Bench, their own 3 GiB heap; §7.0), never in `test`. Write what you measured in android/README.md's Performance notes. The owner's real phone is the milestone check's, with the owner's permission; do not use it. Device: build your ColdSearchTest's index inside the test (a few hundred thousand rows), run it through android/scripts/device-test.sh.
> Commit: fix(android): a merge leaves no large WAL; perf(android): the first search after a start is warm.

#### device-replays: M1-3's vectors on the device: search, index, sync, web

- Branch `android/device-replays` · kotlin · M4 · about 900 lines · depends on – · device
- Goal: The search, index, sync and web vectors, which never ran under ART and ICU, replay on the emulator through the Replays registry, as the JVM tests replay them.
- Owns: `android/core/src/testFixtures/kotlin/io/github/danielhp95/caracole/core/testing/replays/SearchReplay.kt`; `android/core/src/testFixtures/kotlin/io/github/danielhp95/caracole/core/testing/replays/IndexReplay.kt`; `android/core/src/testFixtures/kotlin/io/github/danielhp95/caracole/core/testing/replays/SyncReplay.kt`; `android/server/src/testFixtures/kotlin/io/github/danielhp95/caracole/server/testing/replays/WebReplay.kt`; `android/core/src/test/kotlin/io/github/danielhp95/caracole/core/search/SuggestTest.kt`; `android/core/src/test/kotlin/io/github/danielhp95/caracole/core/search/SearchUgTest.kt`; `android/core/src/test/kotlin/io/github/danielhp95/caracole/core/search/QueryTest.kt`; `android/core/src/test/kotlin/io/github/danielhp95/caracole/core/search/KeySearchTest.kt`; `android/core/src/test/kotlin/io/github/danielhp95/caracole/core/index/IndexMergeTest.kt`; `android/core/src/test/kotlin/io/github/danielhp95/caracole/core/index/IndexTransferTest.kt`; `android/core/src/test/kotlin/io/github/danielhp95/caracole/core/sync/CompareTest.kt`; `android/core/src/test/kotlin/io/github/danielhp95/caracole/core/sync/TakeTest.kt`; `android/core/src/test/kotlin/io/github/danielhp95/caracole/core/sync/UnitsTest.kt`; `android/server/src/test/kotlin/io/github/danielhp95/caracole/server/routes/search/SearchVectors.kt`; `android/server/src/test/kotlin/io/github/danielhp95/caracole/server/routes/search/OwnersTest.kt`; `android/server/src/test/kotlin/io/github/danielhp95/caracole/server/http/RoutingTest.kt`; `android/server/src/test/kotlin/io/github/danielhp95/caracole/server/routes/library/SyncRoutesVectorsTest.kt`
- Must not touch: android/server/src/test/kotlin/io/github/danielhp95/caracole/server/routes/search/ApiSearchTest.kt (lookup-routes'; it calls SearchVectors, which you move); android/server/src/test/kotlin/io/github/danielhp95/caracole/server/jobs/** (job-views'); android/server/src/test/kotlin/io/github/danielhp95/caracole/server/page/** (requests-feed's and library-cards'); android/core/src/test/kotlin/io/github/danielhp95/caracole/core/index/StampsTest.kt (prep-core's); android/core/src/test/kotlin/io/github/danielhp95/caracole/core/sync/SyncEngineTest.kt, PolitenessTest.kt (the sync-crossing group's); §7.0's common list
- Provides: SearchReplay, IndexReplay, SyncReplay, WebReplay filled; the pattern every later replay follows
- Consumes: core.testing.Replays and server.testing.ServerReplays (the skeleton's); CorpusOnDeviceTest.everyAreaReplaysUnderAndroid (the skeleton's)
- Tests: android/app/src/androidTest/kotlin/io/github/danielhp95/caracole/CorpusOnDeviceTest.kt (run, not edited)
- Done when: nix develop ./android -c gradle -p android test passes; nix develop ./android -c gradle -p android assembleDebug assembleDebugAndroidTest passes; android/scripts/device-test.sh --area search,index,sync,web passes with every record run under ART (none skipped), each area reported apart; each moved loop still runs on the JVM, as the call to its replay from its old test

Brief:

> Repo /home/dani/Projects/caracole. Lane device-replays, branch android/device-replays, worktree .claude/worktrees/device-replays. Read docs/superpowers/plans/2026-11-03-android-port-m4-m6.md §7.0 first: its rules bind you. Depends on: none (after skeleton-m4). Runs whole at once. Device lane: android/scripts/device-test.sh alone runs your area and classes.
>
> Plan sections: §3 (On the device), §6 (testFixtures, Replays). The M1-3 lesson: CorpusOnDeviceTest is hand-written per area and covers only unicode, keys, pinyin, fuzz and canonical, so the search, index, sync and web vectors never ran under ART and Android's ICU-backed regex.
> Do: move the record loops of the JVM tests that replay vectors/search, vectors/index, vectors/sync and the web vectors (api_search, routing, downloads, sync_routes; not job_views or library_page, which lanes job-views and requests-feed change) into the skeleton's replay objects (core/testing/replays/*.kt; server/testing/replays/WebReplay.kt), each reading its vectors through Corpus (so Corpus.open from the AssetManager works on the device) and its databases through TestDb and Fixtures. The JVM tests then call the replay. Run them on the emulator with android/scripts/device-test.sh --area search,index,sync,web; a record that differs on the device is a bug of :core or :server: fix it test first (the \G lesson) and say so in your report. Report the replay times.
> Commit: test(android): the search, index, sync and web vectors replay on the device.

#### py-sites: Python's JSON, HTML entities, numbers and URLs for the site parsers

- Branch `android/py-sites` · mixed · M4 · about 1700 lines · depends on – · device
- Goal: core.py answers as Python's json.loads, json.dumps(indent=2), html.unescape, float() and int(), str.capitalize and urllib.parse's urljoin, urlencode and urlunsplit do, record for record.
- Owns: `android/core/src/main/kotlin/io/github/danielhp95/caracole/core/py/PyHtml.kt`; `android/core/src/main/kotlin/io/github/danielhp95/caracole/core/py/PyNumbers.kt`; `android/core/src/main/kotlin/io/github/danielhp95/caracole/core/py/PyUrl.kt (urljoin, urlencode, urlunsplit)`; `android/core/src/main/kotlin/io/github/danielhp95/caracole/core/py/PyUnicode.kt (capitalize)`; `android/core/src/main/kotlin/io/github/danielhp95/caracole/core/json/PyJson.kt (loads, dumps with indent)`; `android/core/src/test/kotlin/io/github/danielhp95/caracole/core/py/PyHtmlTest.kt`; `android/core/src/test/kotlin/io/github/danielhp95/caracole/core/py/PyNumbersTest.kt`; `android/core/src/test/kotlin/io/github/danielhp95/caracole/core/py/PyUrlTest.kt`; `android/core/src/test/kotlin/io/github/danielhp95/caracole/core/json/PyJsonLoadsTest.kt`; `android/core/src/testFixtures/kotlin/io/github/danielhp95/caracole/core/testing/replays/PyReplay.kt (its sites records; py-format follows)`; `tests/test_conformance_py.py (the sites records)`; `tests/conformance/vectors/py/sites*.jsonl`
- Must not touch: §7.0's common list
- Provides: PyHtml.unescape; PyJson.loads, PyJson.dumps(indent); PyFloat.parse, PyInt.parse; PyUnicode.capitalize; PyUrl.urljoin, urlencode, urlunsplit
- Consumes: the HTML5 entity table data/caracole/html/entities.json and PyCodec.utf8Replace (skeleton-m4); PyUnicode, PyRegex (M1); PyText, PyUrl, PyStr moved to core.py (skeleton-m4)
- Tests: android/core/src/test/kotlin/io/github/danielhp95/caracole/core/py/PyHtmlTest.kt; android/core/src/test/kotlin/io/github/danielhp95/caracole/core/json/PyJsonLoadsTest.kt; android/core/src/test/kotlin/io/github/danielhp95/caracole/core/py/PyNumbersTest.kt; tests/test_conformance_py.py
- Done when: nix develop ./android -c gradle -p android test passes; nix develop ./android -c gradle -p android assembleDebug assembleDebugAndroidTest passes; nix develop -c pytest -q -n 0 tests/test_conformance_py.py passes (check mode); nix develop -c pytest -q tests/test_corpus_budget.py passes; every record of vectors/py/sites*.jsonl matches: unescape over every html5 name with and without ';' and in prefixes; loads over the sites' fixture JSON and an edge set (duplicate keys, NaN, Infinity, big ints, lone surrogates); dumps(indent=2, ensure_ascii=False) of each loaded value byte for byte; float() and int() on Unicode digits, underscores and str.strip whitespace; capitalize over every code point; urljoin, urlencode (quote_plus, doseq) and urlunsplit; android/scripts/device-test.sh --area py passes; nix develop -c pytest -q passes; nix build .#checks.x86_64-linux.package passes

Brief:

> Repo /home/dani/Projects/caracole. Lane py-sites, branch android/py-sites, worktree .claude/worktrees/py-sites. Read docs/superpowers/plans/2026-11-03-android-port-m4-m6.md §7.0 first: its rules bind you. Depends on: none (after skeleton-m4). Runs whole at once. Device lane: android/scripts/device-test.sh alone runs your area and classes.
>
> Plan sections: §3, §5.1 (core.py additions). What M4's site parsers read; each must be Python's to the byte. Write tests/test_conformance_py.py's sites records (batched per input, as the M1 lanes did; lane py-format adds its own to the same generator after you, in another vectors file).
> Rules: PyHtml.unescape is html.unescape over skeleton-m4's entities.json (the longest-prefix rule for names without ';', the numeric rules, the invalid code points); PyJson.loads keeps order, a duplicate key at its first place with its last value, NaN and Infinity, big integers, lone-surrogate escapes as UTF-16 units, numbers as literals in Python's int and float form (PyJson.float); dumps(indent=2, ensure_ascii=False) is json.dumps's bytes; PyFloat.parse and PyInt.parse accept what float() and int() accept; capitalize as str.capitalize through PyUnicode; urljoin, urlencode and urlunsplit as urllib.parse. :core never calls a JDK text API (ForbiddenApiTest). Fill PyReplay's sites records.
> Commit: feat(android): Python's JSON, entities, numbers and URLs in core.py.

#### py-format: Python's format specs, rounding, difflib and East Asian width

- Branch `android/py-format` · mixed · M4 · about 1200 lines · depends on py-sites · device
- Goal: core.py formats, rounds, matches sequences and measures widths as Python's format specs, round(), difflib.SequenceMatcher and unicodedata.east_asian_width do.
- Owns: `android/core/src/main/kotlin/io/github/danielhp95/caracole/core/py/PyFormat.kt`; `android/core/src/main/kotlin/io/github/danielhp95/caracole/core/py/PySequence.kt`; `android/core/src/main/kotlin/io/github/danielhp95/caracole/core/py/PyUnicode.kt (eastAsianWidth)`; `android/core/src/test/kotlin/io/github/danielhp95/caracole/core/py/PyFormatTest.kt`; `android/core/src/test/kotlin/io/github/danielhp95/caracole/core/py/PySequenceTest.kt`; `android/core/src/testFixtures/kotlin/io/github/danielhp95/caracole/core/testing/replays/PyReplay.kt (its format records, after py-sites)`; `tests/test_conformance_py.py (the format records, after py-sites)`; `tests/test_conformance_unicode.py (east_asian_width only)`; `tests/conformance/vectors/py/format*.jsonl`; `tests/conformance/data/caracole/unicode/east_asian_width.txt`
- Must not touch: §7.0's common list
- Provides: PyFormat.fixed, percent, roundHalfEven; PySequence.SequenceMatcher; PyUnicode.eastAsianWidth
- Consumes: py-sites' generator and PyReplay (in turn)
- Tests: android/core/src/test/kotlin/io/github/danielhp95/caracole/core/py/PyFormatTest.kt; android/core/src/test/kotlin/io/github/danielhp95/caracole/core/py/PySequenceTest.kt; tests/test_conformance_py.py; tests/test_conformance_unicode.py
- Done when: nix develop ./android -c gradle -p android test passes; nix develop ./android -c gradle -p android assembleDebug assembleDebugAndroidTest passes; nix develop -c pytest -q -n 0 tests/test_conformance_py.py tests/test_conformance_unicode.py passes (check mode); nix develop -c pytest -q tests/test_corpus_budget.py passes; every record of vectors/py/format*.jsonl matches: fixed and percent on exact ties and random doubles (half-even on the exact binary value, '%' multiplying by 100 first in double), round(x) half-even, SequenceMatcher(None, a, b, autojunk=False)'s ratio and matching blocks over random and harvested pairs, east_asian_width over every code point; android/scripts/device-test.sh --area py,unicode passes; nix develop -c pytest -q passes; nix build .#checks.x86_64-linux.package passes

Brief:

> Repo /home/dani/Projects/caracole. Lane py-format, branch android/py-format, worktree .claude/worktrees/py-format. Read docs/superpowers/plans/2026-11-03-android-port-m4-m6.md §7.0 first: its rules bind you. Depends on: py-sites. Starts once every producer has merged. Device lane: android/scripts/device-test.sh alone runs your area and classes.
>
> Plan sections: §3, §5.1 (core.py additions). Lyrics (Megalobiz's LRC, LRCLIB's duration) and M5's pages read these. Starts once py-sites merges (the two share tests/test_conformance_py.py and PyReplay.kt in turn); its data file is its own.
> Rules: PyFormat.fixed and percent round half-even on the exact binary value (BigDecimal(double)), never the JVM's locale; roundHalfEven as round(); SequenceMatcher with isjunk=None and autojunk=False (find_longest_match's ties, the recursion, adjacent blocks merged); eastAsianWidth from data/caracole/unicode/east_asian_width.txt (runs, with the unicodedata 16.0.0 header the other tables have; extend tests/test_conformance_unicode.py for it alone).
> Commit: feat(android): Python's format specs, rounding, difflib and East Asian width in core.py.

#### html-tokenizer: HTML5 input and tokenizer, as lexbor tokenizes

- Branch `android/html` · mixed · M4 · about 2000 lines · depends on – · device
- Goal: core.html's preprocessing and WHATWG tokenizer give lexbor's tokens for every page caracole reads.
- Owns: `android/core/src/main/kotlin/io/github/danielhp95/caracole/core/html/internal/token/**`; `android/core/src/test/kotlin/io/github/danielhp95/caracole/core/html/TokenizerTest.kt`; `android/core/src/testFixtures/kotlin/io/github/danielhp95/caracole/core/testing/replays/HtmlReplay.kt (in turn: tokenizer first)`; `tests/test_conformance_html.py (in turn: tokenizer first)`; `tests/conformance/vectors/html/tokens*.jsonl`; `docs/superpowers/specs/2026-11-03-html-parsing.md (its tokenizer half)`
- Must not touch: §7.0's common list
- Provides: core.html.internal.token.Tokenizer (tokens: doctype, start and end tags with their attributes in source order, comments, characters, EOF) and Preprocess
- Consumes: data/caracole/html/entities.json (skeleton-m4); PyCodec.utf8Replace (skeleton-m4)
- Tests: android/core/src/test/kotlin/io/github/danielhp95/caracole/core/html/TokenizerTest.kt; tests/test_conformance_html.py
- Done when: nix develop ./android -c gradle -p android test passes; nix develop ./android -c gradle -p android assembleDebug assembleDebugAndroidTest passes; nix develop -c pytest -q -n 0 tests/test_conformance_html.py passes (check mode); nix develop -c pytest -q tests/test_corpus_budget.py passes; every record of vectors/html/tokens*.jsonl matches: for every fixture page of tests/fixtures/{ug,lacuerda,gtptabs,harptabs,gametabs,azlyrics,megalobiz,musescore}, every page the helpers build and an edge set (entities with and without ';' in text and attributes, CR and CRLF, NUL, script data and its escapes, RCDATA and RAWTEXT, comments and bogus comments, a doctype of each quirks list), what the tokenizer alone decides as selectolax reads it: every element's attributes (decoded, the first of duplicates, in source order), every text node's and comment's data, the doctype's quirks mode; checked through a minimal tree builder in TokenizerTest (the real one is html-tree's); android/scripts/device-test.sh --area html passes; nix develop -c pytest -q passes; nix build .#checks.x86_64-linux.package passes

Brief:

> Repo /home/dani/Projects/caracole. Lane html-tokenizer, branch android/html, worktree .claude/worktrees/html. Read docs/superpowers/plans/2026-11-03-android-port-m4-m6.md §7.0 first: its rules bind you. Depends on: none (after skeleton-m4). Runs whole at once. Group: html-tokenizer → html-tree, in turn; merge main in first. Device lane: android/scripts/device-test.sh alone runs your area and classes.
>
> Plan sections: §1 (HTML parsing), §3, §5.1 (core.html), and the spec docs/superpowers/specs/2026-11-03-html-parsing.md (skeleton-m4's; make its tokenizer half exact in your commit). Lane html-tree follows you on android/html. Needs nothing but the skeleton: start in the first wave.
> Build in plain Kotlin: input preprocessing as lexbor does it (CRLF and CR to LF; NUL as the spec says); the WHATWG tokenizer whole (data, RCDATA, RAWTEXT, script data and its escapes, tags, attributes with the first of duplicates kept, comments, doctype with its public and system ids, character references through the entity table, the attribute-value rule for legacy names: '&ampx' and '&amp=y' kept, '&amp頭' decoded). The vectors: Python drives selectolax over each input and records what the tokenizer alone decides (lexbor exposes no token stream): attributes as lexbor reads them, text and comment data, quirks mode. Tag names folded by ASCII; no JDK text API (ForbiddenApiTest). Time-boxed first (half a day): nu.validator's htmlparser, a pure-Java WHATWG tokenizer and tree builder, run over the corpus; report how it matches (§11 Q1b); the default stays hand-written.
> Commit: feat(android): the HTML5 tokenizer, as lexbor tokenizes.

#### html-tree: HTML5 tree, nodes and selectors with lexbor's semantics

- Branch `android/html` · mixed · M4 · about 2300 lines · depends on html-tokenizer · device
- Goal: core.html builds lexbor's tree for every page caracole reads and answers every selector, attribute and text query as selectolax.lexbor does, on the JVM and under Android.
- Owns: `android/core/src/main/kotlin/io/github/danielhp95/caracole/core/html/** (all but internal/token, after html-tokenizer)`; `android/core/src/test/kotlin/io/github/danielhp95/caracole/core/html/TreeTest.kt`; `android/core/src/test/kotlin/io/github/danielhp95/caracole/core/html/HtmlVectorsTest.kt`; `android/core/src/testFixtures/kotlin/io/github/danielhp95/caracole/core/testing/replays/HtmlReplay.kt (after html-tokenizer)`; `tests/test_conformance_html.py (after html-tokenizer)`; `tests/conformance/vectors/html/tree*.jsonl`; `tests/conformance/vectors/html/mutations*.jsonl`; `docs/superpowers/specs/2026-11-03-html-parsing.md (its tree half and divergences)`
- Must not touch: §7.0's common list
- Provides: core.html.Html, HtmlDoc, HtmlNode (§5.1)
- Consumes: the tokenizer (html-tokenizer)
- Tests: android/core/src/test/kotlin/io/github/danielhp95/caracole/core/html/TreeTest.kt; android/core/src/test/kotlin/io/github/danielhp95/caracole/core/html/HtmlVectorsTest.kt; tests/test_conformance_html.py
- Done when: nix develop ./android -c gradle -p android test passes; nix develop ./android -c gradle -p android assembleDebug assembleDebugAndroidTest passes; nix develop -c pytest -q -n 0 tests/test_conformance_html.py passes (check mode); nix develop -c pytest -q tests/test_corpus_budget.py passes; every record of vectors/html/tree*.jsonl matches: for each fixture and helper-built page, every selector and operation caracole's parsers run (grepped from ug/page.py, lacuerda.py, gtptabs.py, harptabs.py, gametabs.py), the tree's shape (tags and depth in document order), each element's text(deep) and attributes; and the edge set (<pre>'s first LF, nested <a>, unclosed <p>, <li>, <td>, tables, <svg> with self-closing children and its breakout tags, <template>, script and style, quirks and no-quirks, a page cut short); the seeded mutation set (fixtures with random tag-soup edits) records the tree's shape; the lane reports how many match and pins those that don't in the spec's divergences list (the goal is none); android/scripts/device-test.sh --area html passes; nix develop -c pytest -q passes; nix build .#checks.x86_64-linux.package passes

Brief:

> Repo /home/dani/Projects/caracole. Lane html-tree, branch android/html, worktree .claude/worktrees/html. Read docs/superpowers/plans/2026-11-03-android-port-m4-m6.md §7.0 first: its rules bind you. Depends on: html-tokenizer. Starts once every producer has merged. Group: html-tokenizer → html-tree, in turn; merge main in first. Device lane: android/scripts/device-test.sh alone runs your area and classes.
>
> Plan sections: §1 (HTML parsing), §3, §5.1 (core.html) and the spec. Follows html-tokenizer on android/html.
> Build: the tree builder's insertion modes caracole's pages reach (initial, before html, before head, in head, after head, in body with the adoption agency, implied end tags and scopes, text, in table and its family, after body, after after body); foreign content as the spec builds it (svg and math elements in their namespace, a self-closing tag acknowledged, the breakout tags that leave it: lexbor keeps <path/> children siblings, an HTML-mode builder would nest them); <template> contents as ordinary children, as selectolax shows them; quirks mode from the doctype by the spec's lists. HtmlNode with lexbor's semantics: text(deep) concatenates descendant text including script and style data with no separator, gives nothing for <br>, skips comments; children(includeText) gives '-text' and '-comment'; attributes keep the first of duplicates; replaceWith and insertAfter for harptabs' <pre>. A selector matcher for exactly the selectors caracole uses (grep them), id and class without case in quirks mode. Never jsoup (the spec says why). A local-only differential run over the owner's HTTP cache (~/.cache/caracole/http) is §11 Q1c's, only with the owner's yes: not yours.
> Commit: feat(android): the HTML5 tree and selectors, with lexbor's semantics.

#### http-client: PoliteClient, robots.txt, the cache, the real transport

- Branch `android/http-client` · mixed · M4 · about 2400 lines · depends on – · device
- Goal: core.http asks a site exactly as http.py's PoliteClient does: the same URLs, robots rules, redirects, cache, challenges, retries, errors and events, over an injected Transport; and a scenario replays a pass recorded in Python.
- Owns: `android/core/src/main/kotlin/io/github/danielhp95/caracole/core/http/**`; `android/core/src/test/kotlin/io/github/danielhp95/caracole/core/http/**`; `android/core/src/testFixtures/kotlin/io/github/danielhp95/caracole/core/testing/Scenarios.kt`; `android/core/src/testFixtures/kotlin/io/github/danielhp95/caracole/core/testing/replays/HttpReplay.kt`; `tests/test_conformance_http.py`; `tests/conformance/data/caracole/http/**`; `tests/conformance/vectors/http/**`; `android/app/src/androidTest/kotlin/io/github/danielhp95/caracole/RealTransportOnDeviceTest.kt`
- Must not touch: §7.0's common list
- Provides: core.http.PoliteClient, Client, Response, CachedAnswers, Robots, Urls, HttpRules; RealTransport (HttpURLConnection, gzip and deflate decoded, the loopback guard); RoutedTransport; core.testing.Scenarios.replay (§3's scenario records)
- Consumes: core.config.ProviderPolicy (the skeleton's); the errors of core.http (the skeleton's); PyCodec.utf8Replace (skeleton-m4); tests/helpers/scenario.py (the skeleton's)
- Tests: android/core/src/test/kotlin/io/github/danielhp95/caracole/core/http/UrlsTest.kt; android/core/src/test/kotlin/io/github/danielhp95/caracole/core/http/RobotsTest.kt; android/core/src/test/kotlin/io/github/danielhp95/caracole/core/http/PoliteClientTest.kt; android/core/src/test/kotlin/io/github/danielhp95/caracole/core/http/RealTransportTest.kt; android/core/src/test/kotlin/io/github/danielhp95/caracole/core/http/ScenariosTest.kt; tests/test_conformance_http.py; android/app/src/androidTest/kotlin/io/github/danielhp95/caracole/RealTransportOnDeviceTest.kt
- Done when: nix develop ./android -c gradle -p android test passes; nix develop ./android -c gradle -p android assembleDebug assembleDebugAndroidTest passes; nix develop -c pytest -q -n 0 tests/test_conformance_http.py passes (check mode); nix develop -c pytest -q tests/test_corpus_budget.py passes; every record of vectors/http/urls.jsonl and robots.jsonl matches (every closed and open URL of tests/test_http.py, NOT_A_URL's cases, params replacing the query with '+', raw paths percent-encoded as httpx does, redirect Location resolution); every scripted session of vectors/http/client.jsonl matches: returns or raises, the requests and their headers in order, the events, the sleeps for the recorded draws, the cache files written (the test_http.py cases, one record each); RealTransportTest against a ServerSocket on 127.0.0.1: httpx's header set (names without case, values exact), no redirect followed, gzip and deflate decoded, a connection error a TransportError named as httpx's; and with caracole.network=loopback a request to any other host refused before a socket opens; ScenariosTest replays tests/test_scenario_helper.py's two records; nix develop -c pytest -q passes; nix build .#checks.x86_64-linux.package passes; android/scripts/device-test.sh --area http io.github.danielhp95.caracole.RealTransportOnDeviceTest passes

Brief:

> Repo /home/dani/Projects/caracole. Lane http-client, branch android/http-client, worktree .claude/worktrees/http-client. Read docs/superpowers/plans/2026-11-03-android-port-m4-m6.md §7.0 first: its rules bind you. Depends on: none (after skeleton-m4). Runs whole at once. Device lane: android/scripts/device-test.sh alone runs your area and classes.
>
> Plan sections: §1 (HTTP stack, cache, no live request), §3 (scenario records), §5.1 (core.http). Port http.py's PoliteClient and its rules: Urls.withParams (httpx.URL(url, params=): params replace the query, spaces as '+'), target (raw path and query as httpx encodes them), host, the two-label site, resolve (httpx's next_request); Robots.disallows over data/caracole/http/robots.json, which your generator writes from http.ROBOTS_DISALLOW (rules in order; '*' any run, a trailing '$' the end, anchored, the first rule named); the cache (cache_dir/http/<provider>/<2 hex>/<sha>.body gzip and .json meta, replaced atomically, only accepted 200 and 404, keyed by sha256 of the rendered URL); stale, max_age, conditional requests and 304; at most 3 redirect hops on the same site, each counted, paced and checked against robots (RobotsClosed); 403, 429 or a challenge (cf-mitigated, or a marker in the first 32768 bytes, from data/caracole/http/http.json) is ProviderBlocked and nothing more is sent; LRCLIB's 503 with Retry-After ≤ 30 s plus up to 1 s of jitter retried once; three other errors in a row ProviderUnavailable; read_once_more; CachedAnswers. ProviderError's text is 'provider: status: url: message'. Inject the transport, sleep, draws and clocks; pauses are compared for given draws, never against Python's random. RealTransport is HttpURLConnection with instanceFollowRedirects=false and 30 s timeouts, decoding gzip and deflate itself; it sends httpx's header set (accept */*, accept-encoding 'gzip, deflate', connection keep-alive, user-agent; checked as a set, names without case, values exact: neither platform lets the order be set, and the JDK drops a hand-set Connection, which it sends anyway); it refuses any host but loopback and the emulator's 10.0.2.2 while System.getProperty("caracole.network") == "loopback" (every Gradle Test task and the app's test runner set it). RoutedTransport carries the site's URL in the query (GET {base}/fetch?url=…), never in a Host header. Android's HttpURLConnection is OkHttp-based: RealTransportOnDeviceTest runs the same checks against a ServerSocket on the emulator's loopback. Implement core.testing.Scenarios.replay as §3 says; ScenariosTest replays skeleton-m4's HTTP-only records (two client.get calls, a miss and a cached hit), comparing the events captured from onEvent; the site lanes add EventLog's rows later.
> Commit: feat(android): the polite client, robots.txt and the cache, as http.py.

#### health-pace: Cooldowns, events and the lookup pace

- Branch `android/health-pace` · mixed · M4 · about 1700 lines · depends on http-client · Phase A may start early · device
- Goal: Health, EventLog, Pace, Clients and PhoneConfig give the same cooldowns, counts, budgets and pauses as health.py and commands/_common.py for the same events and kv.
- Owns: `android/core/src/main/kotlin/io/github/danielhp95/caracole/core/health/**`; `android/core/src/main/kotlin/io/github/danielhp95/caracole/core/lookup/Pace.kt`; `android/core/src/main/kotlin/io/github/danielhp95/caracole/core/lookup/Clients.kt`; `android/core/src/main/kotlin/io/github/danielhp95/caracole/core/config/PhoneConfig.kt`; `android/core/src/test/kotlin/io/github/danielhp95/caracole/core/health/**`; `android/core/src/test/kotlin/io/github/danielhp95/caracole/core/lookup/PaceTest.kt`; `android/core/src/test/kotlin/io/github/danielhp95/caracole/core/lookup/ClientsTest.kt`; `android/core/src/test/kotlin/io/github/danielhp95/caracole/core/config/**`; `android/core/src/testFixtures/kotlin/io/github/danielhp95/caracole/core/testing/replays/HealthReplay.kt`; `android/core/src/testFixtures/kotlin/io/github/danielhp95/caracole/core/testing/replays/PaceReplay.kt`; `tests/test_conformance_health.py`; `tests/conformance/vectors/health/**`; `tests/conformance/vectors/pace/**`
- Must not touch: §7.0's common list
- Provides: core.health.Health, ProviderState, EventLog, Alerts; core.lookup.Pace, Clients; PhoneConfig.read, PhoneConfig.take
- Consumes: core.http.PoliteClient, Event (http-client); data/caracole/config/config.json (the skeleton's); schema 16's events.origin (the skeleton's)
- Tests: android/core/src/test/kotlin/io/github/danielhp95/caracole/core/health/HealthTest.kt; android/core/src/test/kotlin/io/github/danielhp95/caracole/core/lookup/PaceTest.kt; android/core/src/test/kotlin/io/github/danielhp95/caracole/core/lookup/ClientsTest.kt; android/core/src/test/kotlin/io/github/danielhp95/caracole/core/config/PhoneConfigTest.kt; tests/test_conformance_health.py
- Done when: nix develop ./android -c gradle -p android test passes; nix develop ./android -c gradle -p android assembleDebug assembleDebugAndroidTest passes; nix develop -c pytest -q -n 0 tests/test_conformance_health.py passes (check mode); nix develop -c pytest -q tests/test_corpus_budget.py passes; every record of vectors/health/state.jsonl matches: sequences of block, ok and error at given times giving the kv provider:<p> text byte for byte (the running cooldown stays, 24 h × 2^(k−1) + 2 h); every record of vectors/pace/*.jsonl matches: an events fixture, a time and a config giving lookup_requests_used, lookup_policy's budget, requests_today, within_the_day, last_request (kv first, else events) and the pause for given draws; answered_any counts this side's own events alone; ClientsTest: Clients.interactive gives a client with the lookup policy, the day's cap for a provider with per_day, the pause after the last request, and kv http:last_request:<p> written as '%.3f' in Locale.ROOT after each sent event; PhoneConfigTest: DEFAULTS equal config.json; take then read gives a settings document's values over the defaults (§4.3); nix develop -c pytest -q passes; nix build .#checks.x86_64-linux.package passes; android/scripts/device-test.sh --area health,pace passes

Brief:

> Repo /home/dani/Projects/caracole. Lane health-pace, branch android/health-pace, worktree .claude/worktrees/health-pace. Read docs/superpowers/plans/2026-11-03-android-port-m4-m6.md §7.0 first: its rules bind you. Depends on: http-client. Phase A while any of http-client hasn't merged; Phase B once all have (§7.0). Device lane: android/scripts/device-test.sh alone runs your area and classes.
>
> Plan sections: §4.1, §4.3, §5.1 (core.config, core.health, core.lookup's Pace and Clients). Phase A while http-client hasn't merged: Health, Pace and PhoneConfig with their vectors (they need no client); Phase B: Clients over PoliteClient.
> Port health.py (ProviderState in kv provider:<p>, stamped '%Y-%m-%dT%H:%M:%SZ'; record_block, record_ok, record_error with the running-cooldown rule; is_cooling; answered_any, own events alone since schema 16; EventLog writing (run, at, provider, url, status, decision, message) with origin NULL) and commands/_common.py's lookup pace (lookup run ids, _SENT, lookup_requests_used with run LIKE 'lookup:%' and at ≥ now − 1 h compared as text, lookup_policy = min(lookup_requests, lookup_per_hour − used) never below 0, requests_today since UTC midnight, within_the_day, _last_request, _pause_after_last_request capped at delay[1]). There is no lock, ticket or handoff on the phone. Clients.interactive wires PoliteClient with the phone's user agent (PhoneConfig.userAgent), the cache under cacheDir, the transport for the provider, EventLog plus the http:last_request writer. PhoneConfig.read lays kv phone:settings over config.json's defaults (§4.3); take stores a settings document. Alerts (blocked, failed) is the skeleton's; you call nothing of it. Write tests/test_conformance_health.py (vectors/health, vectors/pace).
> Commit: feat(android): cooldowns, events and the lookup pace, as health.py and _common.

#### library-writes: Kept files, versions, numbering and the pass ladder

- Branch `android/library-writes` · mixed · M4 · about 1800 lines · depends on – · device
- Goal: core.library writes a song's kept files, versions, statuses and numbers exactly as library.py, versions.py, songs.py, inbox.py and provider_pass.py do, so a unit's digest agrees after the same writes.
- Owns: `android/core/src/main/kotlin/io/github/danielhp95/caracole/core/library/Kept.kt`; `android/core/src/main/kotlin/io/github/danielhp95/caracole/core/library/Versions.kt`; `android/core/src/main/kotlin/io/github/danielhp95/caracole/core/library/Numbering.kt`; `android/core/src/main/kotlin/io/github/danielhp95/caracole/core/library/Passes.kt`; `android/core/src/main/kotlin/io/github/danielhp95/caracole/core/library/internal/writes/**`; `android/core/src/test/kotlin/io/github/danielhp95/caracole/core/library/KeptTest.kt`; `android/core/src/test/kotlin/io/github/danielhp95/caracole/core/library/VersionsTest.kt`; `android/core/src/test/kotlin/io/github/danielhp95/caracole/core/library/NumberingTest.kt`; `android/core/src/test/kotlin/io/github/danielhp95/caracole/core/library/PassesTest.kt`; `android/core/src/testFixtures/kotlin/io/github/danielhp95/caracole/core/testing/replays/LibraryWritesReplay.kt`; `tests/test_conformance_library_writes.py`; `tests/conformance/vectors/library/writes*.jsonl`
- Must not touch: android/core/src/main/kotlin/io/github/danielhp95/caracole/core/sync/** (SongTake keeps its own SQL this round); §7.0's common list
- Provides: core.library.Kept, Versions, VersionRow, Numbering, PassStats, Passes.eachSong; SharedFolder raised as library.py does
- Consumes: core.library.LibraryStore, Songs (M3); core.json.Canonical (stored_hash)
- Tests: android/core/src/test/kotlin/io/github/danielhp95/caracole/core/library/KeptTest.kt; android/core/src/test/kotlin/io/github/danielhp95/caracole/core/library/VersionsTest.kt; android/core/src/test/kotlin/io/github/danielhp95/caracole/core/library/NumberingTest.kt; android/core/src/test/kotlin/io/github/danielhp95/caracole/core/library/PassesTest.kt; tests/test_conformance_library_writes.py
- Done when: nix develop ./android -c gradle -p android test passes; nix develop ./android -c gradle -p android assembleDebug assembleDebugAndroidTest passes; nix develop -c pytest -q -n 0 tests/test_conformance_library_writes.py passes (check mode); nix develop -c pytest -q tests/test_corpus_budget.py passes; every record of vectors/library/writes.jsonl matches: a database fixture and a library folder, a call (keep_file, dropped, upsert_version, set_raw, set_coverage, mark_gone, mark_stale, set_picks, update_song, refresh_status, guitar_number, harmonica_number, gametab_number, score_number), the rows of songs, versions and files and the library's files' sha256 after; a duplicate by sha refused; a SharedFolder raised; Units.libraryState's digests after each record's writes equal Python's peer_sync.library_state digests (recorded beside it); PassesTest: each_song's ladder (a block propagates, a spent budget ends the pass, Unavailable fails the rest, any other error records a failure and moves on) as provider_pass.py's tests say; nix develop -c pytest -q passes; nix build .#checks.x86_64-linux.package passes; android/scripts/device-test.sh --area library_writes passes

Brief:

> Repo /home/dani/Projects/caracole. Lane library-writes, branch android/library-writes, worktree .claude/worktrees/library-writes. Read docs/superpowers/plans/2026-11-03-android-port-m4-m6.md §7.0 first: its rules bind you. Depends on: none (after skeleton-m4). Runs whole at once. Device lane: android/scripts/device-test.sh alone runs your area and classes.
>
> Plan sections: §3 (records over fixtures), §5.1 (core.library additions). Every site lane writes through these, and a kept file's SHA-256, a version's canonical raw and a song's columns are in the sync unit, so they must be Python's to the byte.
> Port: library.keep_file (the dup-by-sha refusal, SharedFolder, ON CONFLICT upsert, created_at's format), kept_already, holds, drop_file, write_atomic (a random name opened exclusively, then a rename; never mode 0600); versions.py's upsert_version (a cached page adds only, as the callers use it), song_versions with its ORDER BY, set_raw, set_coverage, mark_gone, mark_stale, set_picks and picks; songs.py's update_song and refresh_status; inbox.py's guitar_number, harmonica_number, gametab_number, score_number with _names_taken reading the folder; provider_pass.each_song and PassStats. Write tests/test_conformance_library_writes.py: each record replays a dump_fixture database and a library folder, calls the function, and records the rows and the files' sha256 after, plus the unit digests.
> Commit: feat(android): kept files, versions and the pass ladder, as library.py and versions.py.

#### overrides-model: Overrides read as Python reads them, and every writer

- Branch `android/overrides-model` · mixed · M4 · about 1900 lines · depends on – · device
- Goal: Overrides.read gives overrides.Overrides' fields from phone_overrides, and each writer leaves phone_overrides exactly as overrides.song_entries yields after the same add_* in Python.
- Owns: `android/core/src/main/kotlin/io/github/danielhp95/caracole/core/library/Overrides.kt`; `android/core/src/main/kotlin/io/github/danielhp95/caracole/core/library/OverrideWriters.kt`; `android/core/src/main/kotlin/io/github/danielhp95/caracole/core/library/OverrideUrls.kt`; `android/core/src/main/kotlin/io/github/danielhp95/caracole/core/library/Picks.kt`; `android/core/src/main/kotlin/io/github/danielhp95/caracole/core/library/internal/overrides/**`; `android/core/src/test/kotlin/io/github/danielhp95/caracole/core/library/OverridesReadTest.kt`; `android/core/src/test/kotlin/io/github/danielhp95/caracole/core/library/OverrideWritersTest.kt`; `android/core/src/test/kotlin/io/github/danielhp95/caracole/core/library/OverrideUrlsTest.kt`; `android/core/src/testFixtures/kotlin/io/github/danielhp95/caracole/core/testing/replays/OverridesReplay.kt`; `tests/test_conformance_overrides.py`; `tests/conformance/vectors/library/overrides*.jsonl`
- Must not touch: android/core/src/main/kotlin/io/github/danielhp95/caracole/core/library/OverridesStore.kt (M3's; read it); §7.0's common list
- Provides: core.library.Overrides (read model), LaCuerdaPick, HarpTabsPick, GameTabsPick; OverrideWriters (addMatch, addPin, removePin, addLacuerda, addHarptabs, addGametabs, addReject, addAlias, addIgnore, addVersion, addHarmonica); OverrideUrls (overrideKey, tabIdFromUrl, pinUrl, artistPageAddress, pastedTabId, classifyTabUrl, the pick parsers); OverridesError with overrides.py's words
- Consumes: core.library.OverridesStore (M3); core.keys.Normalize
- Tests: android/core/src/test/kotlin/io/github/danielhp95/caracole/core/library/OverridesReadTest.kt; android/core/src/test/kotlin/io/github/danielhp95/caracole/core/library/OverrideWritersTest.kt; android/core/src/test/kotlin/io/github/danielhp95/caracole/core/library/OverrideUrlsTest.kt; tests/test_conformance_overrides.py
- Done when: nix develop ./android -c gradle -p android test passes; nix develop ./android -c gradle -p android assembleDebug assembleDebugAndroidTest passes; nix develop -c pytest -q -n 0 tests/test_conformance_overrides.py passes (check mode); nix develop -c pytest -q tests/test_corpus_budget.py passes; every record of vectors/library/overrides_read.jsonl matches (a phone_overrides fixture giving each field of overrides.Overrides as Python reads the same entries); every record of vectors/library/overrides_writes.jsonl matches: each writer over a fixture giving song_entries after, byte for byte as canonical text, and each refusal's OverridesError words (the same value again writes nothing; remove_pin takes only the given tabs; add_harmonica drops the entry with its last tab; add_reject's refs canonical and code-point sorted; add_alias appends a new slug only); every record of vectors/library/override_urls.jsonl matches (the parsers over the URLs of tests/test_overrides.py, test_get.py and test_ug_sitemap.py, harvested with ast); put_song_entries in Python reads every written value back as given (the generator asserts it); nix develop -c pytest -q passes; nix build .#checks.x86_64-linux.package passes; android/scripts/device-test.sh --area overrides passes

Brief:

> Repo /home/dani/Projects/caracole. Lane overrides-model, branch android/overrides-model, worktree .claude/worktrees/overrides-model. Read docs/superpowers/plans/2026-11-03-android-port-m4-m6.md §7.0 first: its rules bind you. Depends on: none (after skeleton-m4). Runs whole at once. Device lane: android/scripts/device-test.sh alone runs your area and classes.
>
> Plan sections: §5.1 (core.library additions), §4 (why a phone write must read back on the computer). M3's OverridesStore holds values as song_entries yields them but nothing reads them as Python's Overrides model, and no writer exists. A lookup writes [match], [pin], [lacuerda], [harptabs], [gametabs]; M6 writes [version], [harmonica], [reject], [alias], [ignore]. A value the computer's put_song_entries can't read back as given leaves the unit at every sync, so write each in its canonical form: pin URLs through pin_url; reject refs as ug_slug_key 'a/s' sorted in code-point order (Py.CODE_POINT_ORDER, never String.compareTo); version text stripped of a leading # or ?, at most 2000 characters, no control character; harmonica tabs named harmonica-N.txt. addVersion and addHarmonica take their M5 checks as parameters (keyVersion, checkSpec), so this lane ports nothing of the viewer. Also the URL parsers get.find_song and overrides.py use, and ug/sitemap.classify_tab_url. Write tests/test_conformance_overrides.py.
> Commit: feat(android): overrides read and written as overrides.py does.

#### ug-pages: UG's tab and artist pages, and the artist tabs a lookup reads

- Branch `android/ug-pages` · mixed · M4 · about 1700 lines · depends on html-tree, py-sites, http-client · Phase A may start early · device
- Goal: UG's tab and artist pages parse as ug/page.py and ug/artist.py parse them, ug/lookup.py's index reads answer as Python's, and ug/artist_tabs.py stores a page read as Python stores it.
- Owns: `android/core/src/main/kotlin/io/github/danielhp95/caracole/core/ug/UgPage.kt`; `android/core/src/main/kotlin/io/github/danielhp95/caracole/core/ug/UgArtist.kt`; `android/core/src/main/kotlin/io/github/danielhp95/caracole/core/ug/UgLookup.kt`; `android/core/src/main/kotlin/io/github/danielhp95/caracole/core/ug/ArtistTabs.kt (store, keepOnly, forget, backfill)`; `android/core/src/main/kotlin/io/github/danielhp95/caracole/core/ug/internal/pages/**`; `android/core/src/test/kotlin/io/github/danielhp95/caracole/core/ug/UgPageTest.kt`; `android/core/src/test/kotlin/io/github/danielhp95/caracole/core/ug/UgArtistTest.kt`; `android/core/src/test/kotlin/io/github/danielhp95/caracole/core/ug/ArtistTabsStoreTest.kt`; `android/core/src/testFixtures/kotlin/io/github/danielhp95/caracole/core/testing/replays/UgPagesReplay.kt`; `tests/test_conformance_ug_pages.py`; `tests/conformance/vectors/sites/ug_pages*.jsonl`; `tests/conformance/vectors/sites/ug_artist*.jsonl`; `src/caracole/ug/page.py (the lone-surrogate fix only)`; `the test file of ug/page.py (its case)`
- Must not touch: §7.0's common list
- Provides: core.ug.UgPage, UgArtist, UgLookup (IndexTab, songTabs, artistKnown, tabUrlFor); ArtistTabs.store, keepOnly, forget, backfill (each store noted with Reads.note)
- Consumes: core.html (html-tree); PyJson.loads, PyHtml.unescape, PyFloat (py-sites); CachedAnswers (http-client); core.index.Reads (skeleton-m4)
- Tests: android/core/src/test/kotlin/io/github/danielhp95/caracole/core/ug/UgPageTest.kt; android/core/src/test/kotlin/io/github/danielhp95/caracole/core/ug/UgArtistTest.kt; android/core/src/test/kotlin/io/github/danielhp95/caracole/core/ug/ArtistTabsStoreTest.kt; tests/test_conformance_ug_pages.py
- Done when: nix develop ./android -c gradle -p android test passes; nix develop ./android -c gradle -p android assembleDebug assembleDebugAndroidTest passes; nix develop -c pytest -q -n 0 tests/test_conformance_ug_pages.py passes (check mode); nix develop -c pytest -q tests/test_corpus_budget.py passes; every record of vectors/sites/ug_pages.jsonl matches: each UG fixture and each helpers/ug_pages.py variant giving the parsed page (raw as canonical JSON, content as its exact text, versions, meta) or its PageParseError; every record of vectors/sites/ug_artist*.jsonl matches (artist pages parsed; rows after store, keep_only, forget, backfill); a lone surrogate in UG's JSON no longer crashes the computer: parse_tab_page replaces it with U+FFFD (a Python test first), and the port does the same; android/scripts/device-test.sh --area ug_pages passes; nix develop -c pytest -q passes; nix build .#checks.x86_64-linux.package passes

Brief:

> Repo /home/dani/Projects/caracole. Lane ug-pages, branch android/ug-pages, worktree .claude/worktrees/ug-pages. Read docs/superpowers/plans/2026-11-03-android-port-m4-m6.md §7.0 first: its rules bind you. Depends on: html-tree, py-sites, http-client. Phase A while any of html-tree, py-sites, http-client hasn't merged; Phase B once all have (§7.0). Device lane: android/scripts/device-test.sh alone runs your area and classes.
>
> Plan sections: §3, §5.1 (core.ug, core.index.Reads), §1 (HTML parsing). First fix the computer: a lone surrogate in UG's JSON crashes the UTF-8 encode of sheet.txt; parse_tab_page replaces lone surrogates with U+FFFD (test first), then port the fixed rule.
> Port ug/page.py (div.js-store[data-content] decoded by the parser's attribute rules then PyJson.loads; data at store.page.data; parse_version needing a type and an integral id with float() semantics; tab_view.versions; wiki_tab.content and decode_twice; meta {} for UG's []; kind_of with KINDS chords, tabs, ukulele, never Pro or Power; page_url), ug/artist.py (other_tabs, pagination, ?filter= and page_url), ug/lookup.py (IndexTab, song_tabs, artist_known, learned and remembered artist URLs, tab_url_for) and ug/artist_tabs.py's store (savepoint, WHERE excluded.read_at >= ...), keep_only, forget and backfill from the phone's own cache (CachedAnswers). Every store a lookup makes calls Reads.note(db, "ug", page, at), so lane index-push sends it to the computer (§4.4). Vectors in vectors/sites/ug_pages*.jsonl and ug_artist*.jsonl over tests/fixtures/ug and helpers/ug_pages.py.
> Commit: fix(fetch): a lone surrogate in UG's page is U+FFFD; feat(android): UG's tab and artist pages.

#### rank-coverage: Ranking, coverage and sheet versions' rules

- Branch `android/rank-coverage` · mixed · M4 · about 1400 lines · depends on library-writes · Phase A may start early · device
- Goal: rank.py, coverage.py and sheet_versions.py give Python's numbers and lists for the same inputs.
- Owns: `android/core/src/main/kotlin/io/github/danielhp95/caracole/core/ug/Rank.kt`; `android/core/src/main/kotlin/io/github/danielhp95/caracole/core/ug/Coverage.kt`; `android/core/src/main/kotlin/io/github/danielhp95/caracole/core/ug/SheetVersions.kt`; `android/core/src/main/kotlin/io/github/danielhp95/caracole/core/ug/internal/rank/**`; `android/core/src/test/kotlin/io/github/danielhp95/caracole/core/ug/RankCoverageTest.kt`; `android/core/src/test/kotlin/io/github/danielhp95/caracole/core/ug/SheetVersionsTest.kt`; `android/core/src/testFixtures/kotlin/io/github/danielhp95/caracole/core/testing/replays/RankReplay.kt`; `tests/test_conformance_rank.py`; `tests/conformance/vectors/sites/ug_rank*.jsonl`; `tests/conformance/vectors/sites/ug_coverage*.jsonl`; `tests/conformance/vectors/sites/ug_sheet_versions*.jsonl`
- Must not touch: §7.0's common list
- Provides: core.ug.Rank (bayes, priorMean, rankByRating, rankSheets, rankGuitar, isComplete, replacesSheet); Coverage.coverage; SheetVersions (versionNames, sheetKind, keptByYou, noteKeptByYou, unkeepable, mayKeep, sheetPins, inLibrary, inLibraryOf, asData)
- Consumes: core.library.Versions (library-writes); core.fuzz.Fuzz (M1); core.pinyin (M1)
- Tests: android/core/src/test/kotlin/io/github/danielhp95/caracole/core/ug/RankCoverageTest.kt; android/core/src/test/kotlin/io/github/danielhp95/caracole/core/ug/SheetVersionsTest.kt; tests/test_conformance_rank.py
- Done when: nix develop ./android -c gradle -p android test passes; nix develop ./android -c gradle -p android assembleDebug assembleDebugAndroidTest passes; nix develop -c pytest -q -n 0 tests/test_conformance_rank.py passes (check mode); nix develop -c pytest -q tests/test_corpus_budget.py passes; every record of vectors/sites/ug_rank*.jsonl and ug_coverage*.jsonl matches, floats as Python's repr (coverage of every fixture sheet against fixture lyrics; random rank inputs; ties on (version, len(tab_id), tab_id)); every record of vectors/sites/ug_sheet_versions*.jsonl matches (over fixture libraries); android/scripts/device-test.sh --area rank passes; nix develop -c pytest -q passes; nix build .#checks.x86_64-linux.package passes

Brief:

> Repo /home/dani/Projects/caracole. Lane rank-coverage, branch android/rank-coverage, worktree .claude/worktrees/rank-coverage. Read docs/superpowers/plans/2026-11-03-android-port-m4-m6.md §7.0 first: its rules bind you. Depends on: library-writes. Phase A while any of library-writes hasn't merged; Phase B once all have (§7.0). Device lane: android/scripts/device-test.sh alone runs your area and classes.
>
> Plan sections: §3, §5.1 (core.ug). Needs no HTML: start as soon as library-writes merges.
> Port rank.py (Bayesian score (v·R + m·C)/(v+m), the label penalty, the variant bonus, ties on (version, len(tab_id), tab_id), complete sheets first), coverage.py (its regexes through PyRegex with (?i), \W and \s with Unicode semantics, Python's splitlines and split, partial_ratio through Fuzz.partialRatioAlignment, ratio when the sheet's lyric text is shorter than the line, Chinese compared as pinyin) and sheet_versions.py's rules (in_library, in_library_of in few queries, may_keep, as_data for M5 and M6's pages). Floats are written as Python's repr (PyJson.float).
> Commit: feat(android): ranking, coverage and sheet versions, as rank.py and coverage.py.

#### ug-fetch-sheet: UG's lookup path: the sheet, its versions and the tab

- Branch `android/ug-fetch` · mixed · M4 · about 2200 lines · depends on ug-pages, rank-coverage, http-client, library-writes, overrides-model · Phase A may start early · device
- Goal: UgFetch.processSong (its found-song path) and keepVersion send the same requests and write the same versions, files and kv as ug/fetch.py's lookup path for the same index, cache and answers.
- Owns: `android/core/src/main/kotlin/io/github/danielhp95/caracole/core/ug/UgFetch.kt`; `android/core/src/main/kotlin/io/github/danielhp95/caracole/core/ug/FetchContext.kt`; `android/core/src/main/kotlin/io/github/danielhp95/caracole/core/ug/internal/fetch/** (in turn: sheet first)`; `android/core/src/test/kotlin/io/github/danielhp95/caracole/core/ug/fetch/UgFetchSheetTest.kt`; `android/core/src/test/kotlin/io/github/danielhp95/caracole/core/ug/fetch/KeepVersionTest.kt`; `android/core/src/main/kotlin/io/github/danielhp95/caracole/core/lookup/sites/Ug.kt (the sheet and ug stages)`; `android/core/src/testFixtures/kotlin/io/github/danielhp95/caracole/core/testing/replays/UgFetchReplay.kt (in turn: sheet first)`; `tests/test_conformance_ug_fetch.py (in turn: sheet first)`; `tests/conformance/vectors/lookup/ug_sheet*.jsonl`; `tests/conformance/vectors/lookup/ug_keep*.jsonl`
- Must not touch: §7.0's common list
- Provides: core.ug.UgFetch.processSong (found songs), keepVersion, checkedSince; FetchContext; the lookup's sheet stage (UG's first pass) and ug stage (the rest)
- Consumes: UgPage, UgLookup, ArtistTabs (ug-pages); Rank, Coverage, SheetVersions (rank-coverage); Client, Scenarios (http-client); Kept, Versions (library-writes); Overrides, OverrideUrls (overrides-model); Lyrics.songLyrics and match's ARTIST_PAGE and REVIEW_ONLY_STEPS (skeleton-m4); StageContext, StageEnd (skeleton-m4)
- Tests: android/core/src/test/kotlin/io/github/danielhp95/caracole/core/ug/fetch/UgFetchSheetTest.kt; android/core/src/test/kotlin/io/github/danielhp95/caracole/core/ug/fetch/KeepVersionTest.kt; tests/test_conformance_ug_fetch.py
- Done when: nix develop ./android -c gradle -p android test passes; nix develop ./android -c gradle -p android assembleDebug assembleDebugAndroidTest passes; nix develop -c pytest -q -n 0 tests/test_conformance_ug_fetch.py passes (check mode); nix develop -c pytest -q tests/test_corpus_budget.py passes; every scenario of vectors/lookup/ug_sheet.jsonl replays (§3): the lookup's two passes (first=True with 1 versions page and 1 scored sheet; then the rest), pins and the pinned URL, rating pages, the sheet slot with versions kept beside as version-<tab>.txt and .json (beside a pin from the cache alone), 'yours', the tab slot, unreadable pages and their doubling retry, RobotsClosed, a 404 marking a version gone, a block, a spent budget: the requests in order, rows, kv and files' sha256 equal; every scenario of vectors/lookup/ug_keep.jsonl replays (keep_version's answers: kept, same, held, sheet, gone, unreadable, closed, no text, unknown); sheet.json, tab.json and version-*.json are json.dumps(indent=2, ensure_ascii=False) of the raw in UG's key order, floats as repr, byte for byte; android/scripts/device-test.sh --area ug_fetch passes; nix develop -c pytest -q passes; nix build .#checks.x86_64-linux.package passes

Brief:

> Repo /home/dani/Projects/caracole. Lane ug-fetch-sheet, branch android/ug-fetch, worktree .claude/worktrees/ug-fetch. Read docs/superpowers/plans/2026-11-03-android-port-m4-m6.md §7.0 first: its rules bind you. Depends on: ug-pages, rank-coverage, http-client, library-writes, overrides-model. Phase A while any of ug-pages, rank-coverage, http-client, library-writes, overrides-model hasn't merged; Phase B once all have (§7.0). Group: ug-fetch-sheet → ug-fetch-artist, in turn; merge main in first. Device lane: android/scripts/device-test.sh alone runs your area and classes.
>
> Plan sections: §3 (scenario records), §5.1 (core.ug, FetchContext, the site stages). Lane ug-fetch-artist follows you on android/ug-fetch (the artist-page route; the seam: processSong calls ArtistRoute.run, skeleton-m4's neutral stub answering 'not found' until it lands).
> Port ug/fetch.py's lookup path for a song the index matched, never its bulk work: FetchContext and _SongRun; _get_page and the one-more-fetch rule; the unreadable-page kv (7 days doubling to 90); RobotsClosed neither gone nor unreadable; record and recordPage with _check_links; pins and the pinned URL; rate groups (the lowest unrated id first, slugs without a part first); the sheet slot with _keep_beside and the beside-a-pin rule; 'yours'; the tab slot; keep_version; _finish (status, ug_dirty, ug_checked_at; info.json is M5's, write none). Coverage reads lyrics through Lyrics.songLyrics (skeleton-m4's, whole). Leave out fetch_songs, rescore_kept_sheets, handoffs, note_looked_up, songs_to_fetch, fetch_due. The stage file core/lookup/sites/Ug.kt: the sheet stage's UG pass (max_pages_per_group 1, scored_sheets 1, versions False) and the ug stage's (the defaults), each worded as get.py words it, through StageContext's asking (lane lookup's envelope; test with FakeAsking). Write tests/test_conformance_ug_fetch.py with tests/helpers/scenario.py over tests/fixtures/ug and helpers/ug_pages.py, bodies by fixture reference.
> Commit: feat(android): UG's lookup path for a matched song, as ug/fetch.py.

#### ug-fetch-artist: UG's artist-page route, and keeping more versions

- Branch `android/ug-fetch` · mixed · M4 · about 1800 lines · depends on ug-fetch-sheet · device
- Goal: A song the index can't place is looked up through its artist's UG page as ug/fetch.py does, and versions --keep and --keep-more keep versions as versions_cmd.py does.
- Owns: `android/core/src/main/kotlin/io/github/danielhp95/caracole/core/ug/internal/fetch/** (after ug-fetch-sheet)`; `android/core/src/main/kotlin/io/github/danielhp95/caracole/core/ug/ArtistRoute.kt`; `android/core/src/test/kotlin/io/github/danielhp95/caracole/core/ug/fetch/ArtistRouteTest.kt`; `android/core/src/main/kotlin/io/github/danielhp95/caracole/core/lookup/sites/VersionsCommands.kt`; `android/core/src/test/kotlin/io/github/danielhp95/caracole/core/lookup/VersionsCommandsTest.kt`; `android/core/src/testFixtures/kotlin/io/github/danielhp95/caracole/core/testing/replays/UgFetchReplay.kt (after ug-fetch-sheet)`; `tests/test_conformance_ug_fetch.py (after ug-fetch-sheet)`; `tests/conformance/vectors/lookup/ug_artist*.jsonl`; `tests/conformance/vectors/lookup/commands_versions*.jsonl`
- Must not touch: §7.0's common list
- Provides: ArtistRoute (the pasted tab, learning the address, the chords and tabs lists, best titles, reject); VersionsCommands.keep, keepMore (versions_cmd.py's words and writes)
- Consumes: ug-fetch-sheet's FetchContext and _SongRun; ArtistTabs (ug-pages); Asking, CommandContext (skeleton-m4)
- Tests: android/core/src/test/kotlin/io/github/danielhp95/caracole/core/ug/fetch/ArtistRouteTest.kt; android/core/src/test/kotlin/io/github/danielhp95/caracole/core/lookup/VersionsCommandsTest.kt; tests/test_conformance_ug_fetch.py
- Done when: nix develop ./android -c gradle -p android test passes; nix develop ./android -c gradle -p android assembleDebug assembleDebugAndroidTest passes; nix develop -c pytest -q -n 0 tests/test_conformance_ug_fetch.py passes (check mode); nix develop -c pytest -q tests/test_corpus_budget.py passes; every scenario of vectors/lookup/ug_artist.jsonl replays: a song not found through its artist's page (a pasted tab read once, kv ug:pasted_tab; at most LEARN_TRIES slugged tabs to learn kv ug:artist_url; the chords then tabs lists, ARTIST_PAGES_PER_KIND, 30 days max_age with a stale copy only past the budget then BudgetExhausted; the unfiltered page on a 404; best titles with TITLE_MATCH 90 and margin 8; reject), with Reads.note for each list stored; every record of vectors/lookup/commands_versions.jsonl matches: keep and keep-more's last lines, writes and requests (keep_more's loop through one client until the lookup's budget or a block, note_unkeepable); android/scripts/device-test.sh --area ug_fetch passes; nix develop -c pytest -q passes; nix build .#checks.x86_64-linux.package passes

Brief:

> Repo /home/dani/Projects/caracole. Lane ug-fetch-artist, branch android/ug-fetch, worktree .claude/worktrees/ug-fetch. Read docs/superpowers/plans/2026-11-03-android-port-m4-m6.md §7.0 first: its rules bind you. Depends on: ug-fetch-sheet. Starts once every producer has merged. Group: ug-fetch-sheet → ug-fetch-artist, in turn; merge main in first. Device lane: android/scripts/device-test.sh alone runs your area and classes.
>
> Plan sections: §3, §5.1 (core.ug, the command files). Follows ug-fetch-sheet on android/ug-fetch: fill skeleton-m4's ArtistRoute stub that processSong calls.
> Port ug/fetch.py's artist-page route: the pasted tab under [artist_url] read once (kv ug:pasted_tab:<tab>); at most LEARN_TRIES slugged tabs to learn the page (kv ug:artist_url:<artist key>); the chords list, then the tabs list if the filter bar offers it, ARTIST_PAGES_PER_KIND, cached 30 days (a stale copy served only past the budget, then BudgetExhausted); the unfiltered page when a list answers 404; best titles with TITLE_MATCH 90 and margin 8; reject; the match written with step artist_page. And versions_cmd.py's keep (the [block] and 'the sheet already' checks, keep_version, _stopped's words, record_ok only after a request) and keep_more (sheet_versions.may_keep in rank order through one client, note_unkeepable, 'kept N of M') in core/lookup/sites/VersionsCommands.kt, through CommandContext (lane lookup's runner calls them; test with FakeAsking).
> Commit: feat(android): UG's artist-page route and versions kept on the phone.

#### matcher: The matcher, for a lookup's song

- Branch `android/matcher` · mixed · M4 · about 2400 lines · depends on library-writes, overrides-model · Phase A may start early · device
- Goal: Matcher.matchAll decides a song's match, step, score, keys, candidates and review exactly as match.match_all does over the same index and overrides.
- Owns: `android/core/src/main/kotlin/io/github/danielhp95/caracole/core/match/**`; `android/core/src/test/kotlin/io/github/danielhp95/caracole/core/match/**`; `android/core/src/main/kotlin/io/github/danielhp95/caracole/core/fuzz/Fuzz.kt (osaDistance, extractDistance, tokenSetRatio)`; `android/core/src/test/kotlin/io/github/danielhp95/caracole/core/fuzz/FuzzDistanceTest.kt`; `tests/test_conformance_fuzz.py (OSA and token_set_ratio vectors only)`; `tests/conformance/vectors/fuzz/osa*.jsonl`; `tests/conformance/vectors/fuzz/token_set*.jsonl`; `android/core/src/testFixtures/kotlin/io/github/danielhp95/caracole/core/testing/replays/MatchReplay.kt`; `tests/test_conformance_match.py`; `tests/conformance/vectors/match/**`; `android/core/src/main/kotlin/io/github/danielhp95/caracole/core/lookup/sites/Match.kt (the match stage)`; `android/core/src/test/kotlin/io/github/danielhp95/caracole/core/match/MatcherBench.kt`
- Must not touch: §7.0's common list
- Provides: core.match.Matcher (matchAll, candidatesOf), MatchResult, MatchCandidate, MatchChange; Fuzz.osaDistance, extractDistance, tokenSetRatio; the lookup's match stage (core/lookup/sites/Match.kt: match_all over the song, get.py's words)
- Consumes: core.library.Overrides (overrides-model); Versions.markStale (library-writes); core.search, core.keys, core.fuzz (M1-2); MatchPolicy (the skeleton's); StageContext, StageEnd (skeleton-m4)
- Tests: android/core/src/test/kotlin/io/github/danielhp95/caracole/core/match/MatcherTest.kt; android/core/src/test/kotlin/io/github/danielhp95/caracole/core/fuzz/FuzzDistanceTest.kt; tests/test_conformance_match.py
- Done when: nix develop ./android -c gradle -p android test passes; nix develop ./android -c gradle -p android assembleDebug assembleDebugAndroidTest passes; nix develop -c pytest -q -n 0 tests/test_conformance_match.py tests/test_conformance_fuzz.py passes (check mode); nix develop -c pytest -q tests/test_corpus_budget.py passes; every record of vectors/match/*.jsonl matches: test_match.py's cases harvested over a small index fixture, and seeded songs over the corpus's library fixture, giving the songs' match_* columns, match_candidates as json.dumps text, review, ug_dirty and the versions marked stale; an incomplete index (no ug BUILT_KEY record) never records a miss, as Python; MatcherBench (the gated bench task) times matchAll on one song over a synthetic index of 1.5 M ug_index rows (artist keys, title keys and catch-all lines as Python loads them) and reports time and heap; title_only and catch_all load lazily, only when reached; nix develop -c pytest -q passes; nix build .#checks.x86_64-linux.package passes; nix develop ./android -c gradle -p android bench passes (the gated benchmarks, their own heap); android/scripts/device-test.sh --area match,fuzz passes

Brief:

> Repo /home/dani/Projects/caracole. Lane matcher, branch android/matcher, worktree .claude/worktrees/matcher. Read docs/superpowers/plans/2026-11-03-android-port-m4-m6.md §7.0 first: its rules bind you. Depends on: library-writes, overrides-model. Phase A while any of library-writes, overrides-model hasn't merged; Phase B once all have (§7.0). Device lane: android/scripts/device-test.sh alone runs your area and classes.
>
> Plan sections: §5.1 (core.match), §3. Phase A while library-writes or overrides-model haven't merged: the port and vectors; Phase B: the writes through Versions and the overrides read model.
> Port match.py for a lookup (match_all(songs=[song])): the ladder in order (overrides: ignore, pin, match; exact or alias title under the song's artist keys with name_forms and compact variants; the nearest artist keys at or above artist_gate by process.extract with ratio; word_title, typo_artist by OSA distance with a distance cutoff, catch_all over the misc-* songs; title_only), MatchResult, the candidates (5), review, and _save writing match_* and mark_stale when the match changes. Sorted lists use Py.CODE_POINT_ORDER, and compact_artists' range bounds keep '\U0010ffff' as a code point. Add to Fuzz: osaDistance (rapidfuzz's OSA), extractDistance (ascending, score_cutoff as a maximum distance, limit None) and tokenSetRatio, with vectors in vectors/fuzz. The match stage (core/lookup/sites/Match.kt, skeleton-m4's stub) is yours: artist_tabs.backfill once, match_all(songs=[song]), get.py's words for its outcome (MATCH_NOT_FOUND and the rest); lane lookup calls it. Measure in MatcherBench (the gated bench task, its own heap) and report: the phone holds about 150k artist keys, 720k title keys and 90k catch-all lines; if title_only needs another structure to fit a phone, say so in your report rather than changing its answers.
> Commit: feat(android): the matcher, as match.py.

#### lyrics: LRCLIB, Megalobiz and AZLyrics for a lookup

- Branch `android/lyrics` · mixed · M4 · about 2300 lines · depends on http-client, py-sites, py-format, library-writes, overrides-model · Phase A may start early · device
- Goal: The lyrics passes ask, parse, decide and write as lyrics.py, megalobiz*.py and azlyrics*.py do for one song: misses, errors back to pending, the per-day limit's counting and the link back.
- Owns: `android/core/src/main/kotlin/io/github/danielhp95/caracole/core/lyrics/**`; `android/core/src/test/kotlin/io/github/danielhp95/caracole/core/lyrics/**`; `android/core/src/testFixtures/kotlin/io/github/danielhp95/caracole/core/testing/replays/LyricsReplay.kt`; `tests/test_conformance_lyrics.py`; `tests/conformance/vectors/sites/lrclib*.jsonl`; `tests/conformance/vectors/sites/megalobiz*.jsonl`; `tests/conformance/vectors/sites/azlyrics*.jsonl`; `tests/conformance/vectors/lookup/lrclib*.jsonl`; `tests/conformance/vectors/lookup/megalobiz*.jsonl`; `tests/conformance/vectors/lookup/azlyrics*.jsonl`; `android/core/src/main/kotlin/io/github/danielhp95/caracole/core/lookup/sites/Lrclib.kt`; `android/core/src/main/kotlin/io/github/danielhp95/caracole/core/lookup/sites/Megalobiz.kt`; `android/core/src/main/kotlin/io/github/danielhp95/caracole/core/lookup/sites/AzLyrics.kt`; `android/core/src/main/kotlin/io/github/danielhp95/caracole/core/library/internal/LyricsFiles.kt (the derivation only; core/lyrics/Lyrics.kt is skeleton-m4's)`
- Must not touch: §7.0's common list
- Provides: core.lyrics.Lrclib, Megalobiz, AzLyrics (their passes, parsers, pickers); LyricsStats, MegalobizStats, AzLyricsStats filled; the lookup's lyrics stages (Lrclib, Megalobiz, AzLyrics)
- Consumes: Client, HttpRules.readOnceMore, Scenarios (http-client); PyJson.loads, PyFormat.fixed, roundHalfEven, PyHtml.unescape (py-sites, py-format); Versions.updateSong, Kept (library-writes); Overrides (overrides-model)
- Tests: android/core/src/test/kotlin/io/github/danielhp95/caracole/core/lyrics/LrclibTest.kt; android/core/src/test/kotlin/io/github/danielhp95/caracole/core/lyrics/MegalobizTest.kt; android/core/src/test/kotlin/io/github/danielhp95/caracole/core/lyrics/AzLyricsTest.kt; tests/test_conformance_lyrics.py
- Done when: nix develop ./android -c gradle -p android test passes; nix develop ./android -c gradle -p android assembleDebug assembleDebugAndroidTest passes; nix develop -c pytest -q -n 0 tests/test_conformance_lyrics.py passes (check mode); nix develop -c pytest -q tests/test_corpus_budget.py passes; every parser record of vectors/sites/{lrclib,megalobiz,azlyrics}*.jsonl matches over tests/fixtures/{lrclib,megalobiz,azlyrics} (pick_candidate, fits, another_version, parse_search, parse_lrc with round-half-even, pick_result, artist_url, parse_artist, parse_lyrics, pick_song); every scenario of vectors/lookup/{lrclib,megalobiz,azlyrics}*.jsonl replays: a hit, a miss and its 30-day kv, an unreadable cached answer asked once more, LRCLIB's 503 retried once, an error putting a song LRCLIB missed back to pending, AZLyrics' block page (a 200) a block never cached; lyrics.txt, lyrics.lrc and lyrics_json byte for byte; nix develop -c pytest -q passes; nix build .#checks.x86_64-linux.package passes; android/scripts/device-test.sh --area lyrics passes

Brief:

> Repo /home/dani/Projects/caracole. Lane lyrics, branch android/lyrics, worktree .claude/worktrees/lyrics. Read docs/superpowers/plans/2026-11-03-android-port-m4-m6.md §7.0 first: its rules bind you. Depends on: http-client, py-sites, py-format, library-writes, overrides-model. Phase A while any of http-client, py-sites, py-format, library-writes, overrides-model hasn't merged; Phase B once all have (§7.0). Device lane: android/scripts/device-test.sh alone runs your area and classes.
>
> Plan sections: §3, §5.1 (core.lyrics). Phase A while a producer hasn't merged: generator and port; Phase B: replays.
> Port lyrics.py (Lyrics, to_json as json.dumps with ensure_ascii False, /api/get with duration round()ed half-even, then /api/search with _HAN_GAP removed and pick_candidate's bands; read_once_more; LrclibParseError an error; fetch_pending_lyrics(only=); lyrics.txt and lyrics.lrc through write_atomic; kv lyrics:failed:), megalobiz.py and megalobiz_fetch.py (the search and the record, a 404 a miss, parse_lrc's f'{ms % 60000 / 1000:05.2f}' through PyFormat.fixed, pick_result, record_json, songs_to_ask, kv megalobiz:checked: and 30 days, back to pending on an error, the link back in lyrics_from) and azlyrics.py and azlyrics_fetch.py (artist_url, the artist then the lyrics page, regexes over resp.text then PyHtml.unescape, tags stripped, str.strip per line; the [azlyrics] pick; kv azlyrics:checked:). Megalobiz's per_day is the lookup's client policy (Pace.withinTheDay, health-pace's), not yours. Reuse library/internal/LyricsFiles.kt for the plain and synced derivation. The Lyrics model (Lyrics, lyricsFromJson, songLyrics) is skeleton-m4's, whole: fill nothing there. The stage files core/lookup/sites/{Lrclib,Megalobiz,AzLyrics}.kt are yours: each runs its pass for the song and words its outcome as get.py does (lane lookup combines them with _then's words), through StageContext (test with FakeAsking).
> Commit: feat(android): lyrics from LRCLIB, Megalobiz and AZLyrics, as the computer finds them.

#### lacuerda-pages: LaCuerda's pages, its index writers and its own search

- Branch `android/lacuerda` · mixed · M4 · about 1700 lines · depends on html-tree, http-client, health-pace, py-sites · Phase A may start early · device
- Goal: LaCuerda's pages parse as lacuerda.py parses them, its index rows are stored as lacuerda_index.py stores them, and its search gate and search answer as lacuerda_search.py does.
- Owns: `android/core/src/main/kotlin/io/github/danielhp95/caracole/core/lacuerda/LaCuerdaPages.kt`; `android/core/src/main/kotlin/io/github/danielhp95/caracole/core/lacuerda/LaCuerdaSearch.kt`; `android/core/src/main/kotlin/io/github/danielhp95/caracole/core/lacuerda/LaCuerda.kt (the store writers)`; `android/core/src/main/kotlin/io/github/danielhp95/caracole/core/lacuerda/internal/pages/**`; `android/core/src/test/kotlin/io/github/danielhp95/caracole/core/lacuerda/LaCuerdaPagesTest.kt`; `android/core/src/test/kotlin/io/github/danielhp95/caracole/core/lacuerda/LaCuerdaSearchTest.kt`; `android/core/src/testFixtures/kotlin/io/github/danielhp95/caracole/core/testing/replays/LaCuerdaReplay.kt (in turn: pages first)`; `tests/test_conformance_lacuerda_lookups.py (in turn: pages first)`; `tests/conformance/vectors/sites/lacuerda*.jsonl`; `tests/conformance/vectors/lookup/lacuerda_gate*.jsonl`; `tests/conformance/vectors/lookup/lacuerda_search*.jsonl`
- Must not touch: §7.0's common list
- Provides: core.lacuerda.LaCuerdaPages (every parser, URLs); LaCuerda's store writers (storeSongs, storeArtistPage, storeSearch, _replace), each noted with Reads.note; LaCuerdaSearch (queryKey, asked, answersWell, gate, search, recordFailure), SearchGate
- Consumes: core.html (html-tree); Client, Scenarios (http-client); Pace, Health (health-pace); PyUnicode.capitalize, PyInt (py-sites); LaCuerda's M2 index code; core.index.Reads (skeleton-m4)
- Tests: android/core/src/test/kotlin/io/github/danielhp95/caracole/core/lacuerda/LaCuerdaPagesTest.kt; android/core/src/test/kotlin/io/github/danielhp95/caracole/core/lacuerda/LaCuerdaSearchTest.kt; tests/test_conformance_lacuerda_lookups.py
- Done when: nix develop ./android -c gradle -p android test passes; nix develop ./android -c gradle -p android assembleDebug assembleDebugAndroidTest passes; nix develop -c pytest -q -n 0 tests/test_conformance_lacuerda_lookups.py passes (check mode); nix develop -c pytest -q tests/test_corpus_budget.py passes; every parser record matches over tests/fixtures/lacuerda and helpers/lacuerda_site.py: parse_artist_page, parse_popularity, parse_artist_name, parse_version_page (<A> to [ch], nbsp), parse_search with every cut-short refusal, parse_lcd, best_acordes_version, match_title, looks_spanish; every record of vectors/lookup/lacuerda_gate.jsonl matches (None, asked, spent, failed, button, auto from kv and events fixtures), and of lacuerda_search.jsonl (the search's one request, its savepoint, its kv, a failure kept an hour); android/scripts/device-test.sh --area lacuerda passes; nix develop -c pytest -q passes; nix build .#checks.x86_64-linux.package passes

Brief:

> Repo /home/dani/Projects/caracole. Lane lacuerda-pages, branch android/lacuerda, worktree .claude/worktrees/lacuerda. Read docs/superpowers/plans/2026-11-03-android-port-m4-m6.md §7.0 first: its rules bind you. Depends on: html-tree, http-client, health-pace, py-sites. Phase A while any of html-tree, http-client, health-pace, py-sites hasn't merged; Phase B once all have (§7.0). Group: lacuerda-pages → lacuerda-sheets, in turn; merge main in first. Device lane: android/scripts/device-test.sh alone runs your area and classes.
>
> Plan sections: §3, §5.1 (core.lacuerda, core.index.Reads). Lane lacuerda-sheets follows you on android/lacuerda.
> Port lacuerda.py's pages and URLs (the parser's text and child iteration, raw-html regexes with (?i)(?s), _strings, NMAX checks, every cut-short refusal), lacuerda_index.py's store_songs, store_artist_page, store_search and _replace (DELETE then INSERT OR REPLACE by page; an unnamed artist's name by capitalize through PyUnicode), each store calling Reads.note(db, "lacuerda", page, at) (LaCuerda's rows hold no time: Reads is what lets index-push send them), and lacuerda_search.py (query_key, asked, answers_well, Failure.said, record_failure, _forget_failure, searches_used by runs named lookup:lacuerda-search:, gate, search with max_age 30 days and read_once_more, in one savepoint).
> Commit: feat(android): LaCuerda's pages, index writers and search, as the computer reads them.

#### lacuerda-sheets: LaCuerda's sheets and an artist's page for a lookup

- Branch `android/lacuerda` · mixed · M4 · about 1500 lines · depends on lacuerda-pages, library-writes, overrides-model, rank-coverage · device
- Goal: A song's LaCuerda sheet and an artist's LaCuerda page are asked, chosen and kept as lacuerda_fetch.py does, and lacuerda --artist and --search run as the commands do.
- Owns: `android/core/src/main/kotlin/io/github/danielhp95/caracole/core/lacuerda/LaCuerdaSheets.kt`; `android/core/src/main/kotlin/io/github/danielhp95/caracole/core/lacuerda/internal/fetch/**`; `android/core/src/test/kotlin/io/github/danielhp95/caracole/core/lacuerda/LaCuerdaSheetsTest.kt`; `android/core/src/main/kotlin/io/github/danielhp95/caracole/core/lookup/sites/LaCuerda.kt (the sheet and lacuerda stages)`; `android/core/src/main/kotlin/io/github/danielhp95/caracole/core/lookup/sites/LaCuerdaCommands.kt`; `android/core/src/test/kotlin/io/github/danielhp95/caracole/core/lookup/LaCuerdaCommandsTest.kt`; `android/core/src/testFixtures/kotlin/io/github/danielhp95/caracole/core/testing/replays/LaCuerdaReplay.kt (after lacuerda-pages)`; `tests/test_conformance_lacuerda_lookups.py (after lacuerda-pages)`; `tests/conformance/vectors/lookup/lacuerda_sheets*.jsonl`; `tests/conformance/vectors/lookup/commands_lacuerda*.jsonl`
- Must not touch: §7.0's common list
- Provides: LaCuerdaSheets.lacuerdaSheets, readArtistPage; the lookup's LaCuerda stages (a pick in the sheet stage, the lacuerda stage); LaCuerdaCommands.artist, search (the commands' last lines)
- Consumes: lacuerda-pages' parsers and writers; Kept, Versions (library-writes); Overrides, LaCuerdaPick (overrides-model); Rank, Coverage (rank-coverage); Lyrics.songLyrics (skeleton-m4); StageContext, CommandContext (skeleton-m4)
- Tests: android/core/src/test/kotlin/io/github/danielhp95/caracole/core/lacuerda/LaCuerdaSheetsTest.kt; android/core/src/test/kotlin/io/github/danielhp95/caracole/core/lookup/LaCuerdaCommandsTest.kt; tests/test_conformance_lacuerda_lookups.py
- Done when: nix develop ./android -c gradle -p android test passes; nix develop ./android -c gradle -p android assembleDebug assembleDebugAndroidTest passes; nix develop -c pytest -q -n 0 tests/test_conformance_lacuerda_lookups.py passes (check mode); nix develop -c pytest -q tests/test_corpus_budget.py passes; every scenario of vectors/lookup/lacuerda_sheets.jsonl replays: a sheet kept, picked, or not replacing a better one; artist slugs tried in order (first=, the imported listings' artist_slugs, artist_slug_candidates) with a 404 or the 'aqui llega:' body moving on; store_songs' rows; sheet.json as json.dumps(indent=2)+newline; lacuerda_checked_at; looks_spanish unless picked; every record of vectors/lookup/commands_lacuerda.jsonl matches: lacuerda --artist's and --search's last lines ('Read: ', 'Not found: ', 'Not read: ', 'Searched: ', 'Found already: ', 'Nothing found: ', 'Not searched: ') and writes; android/scripts/device-test.sh --area lacuerda passes; nix develop -c pytest -q passes; nix build .#checks.x86_64-linux.package passes

Brief:

> Repo /home/dani/Projects/caracole. Lane lacuerda-sheets, branch android/lacuerda, worktree .claude/worktrees/lacuerda. Read docs/superpowers/plans/2026-11-03-android-port-m4-m6.md §7.0 first: its rules bind you. Depends on: lacuerda-pages, library-writes, overrides-model, rank-coverage. Starts once every producer has merged. Group: lacuerda-pages → lacuerda-sheets, in turn; merge main in first. Device lane: android/scripts/device-test.sh alone runs your area and classes.
>
> Plan sections: §3, §5.1 (core.lacuerda, the site stages, the command files). Follows lacuerda-pages on android/lacuerda.
> Port lacuerda_fetch.py for one song (_to_try and may_ask; _artist_songs' slug order; each page cached 30 days; _record and _keep; lacuerda_checked_at; looks_spanish unless picked) and read_artist_page; leave out popular_pages, the listings pass and handoffs. The stage file core/lookup/sites/LaCuerda.kt: a LaCuerda pick asked first in the sheet stage, the lacuerda stage when there is no sheet, each worded as get.py words it. The command file LaCuerdaCommands.kt: commands/lyrics.py's lacuerda --artist and --search (the gate, one request, their last lines), through CommandContext (lane lookup's runner calls them; test with FakeAsking).
> Commit: feat(android): LaCuerda's sheets and artist pages for a lookup.

#### harptabs: harptabs.com for a lookup, and an artist's page

- Branch `android/harptabs` · mixed · M4 · about 1600 lines · depends on html-tree, http-client, library-writes, overrides-model, py-sites · Phase A may start early · device
- Goal: A song's harmonica tab and an artist's harptabs.com page are asked, parsed, chosen and kept as harptabs*.py do.
- Owns: `android/core/src/main/kotlin/io/github/danielhp95/caracole/core/sites/HarpTabs.kt`; `android/core/src/main/kotlin/io/github/danielhp95/caracole/core/sites/internal/harptabs/**`; `android/core/src/test/kotlin/io/github/danielhp95/caracole/core/sites/HarpTabsTest.kt`; `android/core/src/main/kotlin/io/github/danielhp95/caracole/core/lookup/sites/HarpTabs.kt (the harptabs stage)`; `android/core/src/main/kotlin/io/github/danielhp95/caracole/core/lookup/sites/HarpTabsCommands.kt`; `android/core/src/test/kotlin/io/github/danielhp95/caracole/core/lookup/HarpTabsCommandsTest.kt`; `android/core/src/testFixtures/kotlin/io/github/danielhp95/caracole/core/testing/replays/HarpTabsReplay.kt`; `tests/test_conformance_harptabs.py`; `tests/conformance/vectors/sites/harptabs*.jsonl`; `tests/conformance/vectors/lookup/harptabs*.jsonl`; `tests/conformance/vectors/lookup/commands_harptabs*.jsonl`
- Must not touch: §7.0's common list
- Provides: core.sites.HarpTabs (harptabsTabs, readArtist, parsers); HarpTabsStats filled; the lookup's harptabs stage; HarpTabsCommands.artist (harptabs --artist's last line)
- Consumes: core.html, Client, Scenarios; PyJson.loads, PyFloat, PyInt (py-sites); Kept, Versions, Numbering; Overrides, HarpTabsPick; core.index.Reads, StageContext, CommandContext (skeleton-m4)
- Tests: android/core/src/test/kotlin/io/github/danielhp95/caracole/core/sites/HarpTabsTest.kt; android/core/src/test/kotlin/io/github/danielhp95/caracole/core/lookup/HarpTabsCommandsTest.kt; tests/test_conformance_harptabs.py
- Done when: nix develop ./android -c gradle -p android test passes; nix develop ./android -c gradle -p android assembleDebug assembleDebugAndroidTest passes; nix develop -c pytest -q -n 0 tests/test_conformance_harptabs.py passes (check mode); nix develop -c pytest -q tests/test_corpus_budget.py passes; every parser record matches over tests/fixtures/harptabs and helpers/harptabs_site.py: page URLs and keys (joined contractions), parse_tab_page (JSON-LD from script data, _pre_text's tree edits, views and rating through PyFloat), parse_artist_page; every scenario replays: candidates (8 at most) in order, the artist check by name forms, placeholders no one's, the most viewed kept as harmonica-N.txt with its version and raw, a pick read alone, misses and their 30-day kv (with :pick), a page that won't parse an error never a miss, the caracole user agent, a block; harptabs --artist's rows (store_artist_page, store_gone, each noted with Reads.note) and its last line; android/scripts/device-test.sh --area harptabs passes; nix develop -c pytest -q passes; nix build .#checks.x86_64-linux.package passes

Brief:

> Repo /home/dani/Projects/caracole. Lane harptabs, branch android/harptabs, worktree .claude/worktrees/harptabs. Read docs/superpowers/plans/2026-11-03-android-port-m4-m6.md §7.0 first: its rules bind you. Depends on: html-tree, http-client, library-writes, overrides-model, py-sites. Phase A while any of html-tree, http-client, library-writes, overrides-model, py-sites hasn't merged; Phase B once all have (§7.0). Device lane: android/scripts/device-test.sh alone runs your area and classes.
>
> Plan sections: §3, §5.1 (core.sites, the site stages, the command files).
> Port harptabs.py, harptabs_fetch.py for one song (candidates: an artist page's tabs of the title by views, then sitemap rows by title_keys lowest id first, at most 8; none unless the sitemap lists an artist by one of the song's name forms; the artist by JSON-LD composer, header link or 'by ...' line sharing a name form; the most viewed then best rated then lowest id; harmonica-N.txt as the <pre> text after <br> and <p>/<div> line ends, strip('\n')+'\n'; kv harptabs:checked: and :pick) and harptabs_index.read_artist (once in 30 days; store_artist_page, store_gone, artist_paths, ensure_current_keys; Reads.note for each page stored). Leave out sitemap refreshes and artist_pass. The stage file and the command file (commands/lyrics.py's harptabs --artist) are yours, through StageContext and CommandContext (test with FakeAsking). The own-user-agent and block tests of test_harptabs_fetch.py become scenario records.
> Commit: feat(android): harptabs.com for a lookup.

#### gametabs: gametabs.net for a lookup

- Branch `android/gametabs` · mixed · M4 · about 1300 lines · depends on html-tree, http-client, library-writes, overrides-model, py-sites · Phase A may start early · device
- Goal: A song's game tab is asked, parsed, chosen and kept as gametabs*.py do.
- Owns: `android/core/src/main/kotlin/io/github/danielhp95/caracole/core/sites/GameTabs.kt`; `android/core/src/main/kotlin/io/github/danielhp95/caracole/core/sites/internal/gametabs/**`; `android/core/src/test/kotlin/io/github/danielhp95/caracole/core/sites/GameTabsTest.kt`; `android/core/src/main/kotlin/io/github/danielhp95/caracole/core/lookup/sites/GameTabs.kt (the gametabs stage)`; `android/core/src/testFixtures/kotlin/io/github/danielhp95/caracole/core/testing/replays/GameTabsReplay.kt`; `tests/test_conformance_gametabs.py`; `tests/conformance/vectors/sites/gametabs*.jsonl`; `tests/conformance/vectors/lookup/gametabs*.jsonl`; `src/caracole/gametabs.py (the isdigit/int fix only)`; `tests/test_gametabs.py (its case)`
- Must not touch: §7.0's common list
- Provides: core.sites.GameTabs (gametabsTabs, parsers); GameTabsStats filled; the lookup's gametabs stage
- Consumes: core.html, Client, Scenarios; PyJson.loads, PyInt (py-sites); Kept, Versions, Numbering; Overrides, GameTabsPick; StageContext (skeleton-m4)
- Tests: android/core/src/test/kotlin/io/github/danielhp95/caracole/core/sites/GameTabsTest.kt; tests/test_conformance_gametabs.py
- Done when: nix develop ./android -c gradle -p android test passes; nix develop ./android -c gradle -p android assembleDebug assembleDebugAndroidTest passes; nix develop -c pytest -q -n 0 tests/test_conformance_gametabs.py passes (check mode); nix develop -c pytest -q tests/test_corpus_budget.py passes; every parser record matches over tests/fixtures/gametabs and helpers/gametabs_site.py: parse_tab_page (data-tab JSON, microdata, details) and parse_game_page; every scenario replays: game_forms, composers, fits, candidates (4 at most) in order, the most viewed kept as gametab-N.txt with its 12 raw fields, a pick read alone, misses and their 30-day kv (with :pick), a page that won't parse an error never a miss, the caracole user agent, a block; gametabs.parse_game_page no longer crashes on '²' (isdigit but not int): a GameTabsParseError, test first in Python, ported; android/scripts/device-test.sh --area gametabs passes; nix develop -c pytest -q passes; nix build .#checks.x86_64-linux.package passes

Brief:

> Repo /home/dani/Projects/caracole. Lane gametabs, branch android/gametabs, worktree .claude/worktrees/gametabs. Read docs/superpowers/plans/2026-11-03-android-port-m4-m6.md §7.0 first: its rules bind you. Depends on: html-tree, http-client, library-writes, overrides-model, py-sites. Phase A while any of html-tree, http-client, library-writes, overrides-model, py-sites hasn't merged; Phase B once all have (§7.0). Device lane: android/scripts/device-test.sh alone runs your area and classes.
>
> Plan sections: §3, §5.1 (core.sites, the site stages). First fix the computer: gametabs.parse_game_page does int(n) after n.isdigit(), which raises on '²'; make it a GameTabsParseError (test first), then port the fixed rule.
> Port gametabs.py and gametabs_fetch.py for one song (game_forms, composers, fits, at most 4, gametab-N.txt with its 12 raw fields, kv gametabs:checked: and :pick; parse_game_page ported, no game page read by a lookup). Leave out sitemap refreshes and game_pass. The stage file is yours, through StageContext (test with FakeAsking).
> Commit: fix(gametabs): a page number that isn't an int is a parse error; feat(android): gametabs.net for a lookup.

#### tab-files: gtptabs.com's Guitar Pro files and MuseScore's links

- Branch `android/tab-files` · mixed · M4 · about 1600 lines · depends on html-tree, http-client, library-writes, overrides-model · Phase A may start early · device
- Goal: A song's Guitar Pro file is found, downloaded, sniffed and kept as gtptabs*.py do, and MuseScore's links come from the index as musescore.song_pages gives them.
- Owns: `android/core/src/main/kotlin/io/github/danielhp95/caracole/core/sites/GtpTabs.kt`; `android/core/src/main/kotlin/io/github/danielhp95/caracole/core/sites/MuseScore.kt`; `android/core/src/main/kotlin/io/github/danielhp95/caracole/core/sites/internal/gtptabs/**`; `android/core/src/test/kotlin/io/github/danielhp95/caracole/core/sites/GtpTabsTest.kt`; `android/core/src/test/kotlin/io/github/danielhp95/caracole/core/sites/MuseScoreTest.kt`; `android/core/src/testFixtures/kotlin/io/github/danielhp95/caracole/core/testing/replays/TabFilesReplay.kt`; `tests/test_conformance_tab_files.py`; `tests/conformance/vectors/sites/gtptabs*.jsonl`; `tests/conformance/vectors/sites/musescore*.jsonl`; `tests/conformance/vectors/lookup/gtptabs*.jsonl`; `android/core/src/main/kotlin/io/github/danielhp95/caracole/core/lookup/sites/GtpTabs.kt (the gtptabs stage)`
- Must not touch: §7.0's common list
- Provides: core.sites.GtpTabs (gtptabsFiles, sniff, parsers, titlePage), MuseScore.songPages; GtpTabsStats filled; the lookup's gtptabs stage
- Consumes: core.html, Client, Scenarios; Kept, Versions, Numbering; Overrides; StageContext (skeleton-m4)
- Tests: android/core/src/test/kotlin/io/github/danielhp95/caracole/core/sites/GtpTabsTest.kt; android/core/src/test/kotlin/io/github/danielhp95/caracole/core/sites/MuseScoreTest.kt; tests/test_conformance_tab_files.py
- Done when: nix develop ./android -c gradle -p android test passes; nix develop ./android -c gradle -p android assembleDebug assembleDebugAndroidTest passes; nix develop -c pytest -q -n 0 tests/test_conformance_tab_files.py passes (check mode); nix develop -c pytest -q tests/test_corpus_budget.py passes; every parser record matches over tests/fixtures/{gtptabs,guitar,musescore}: parse_page_url, artist_keys, title_key, parse_artist_page (link text collapsed, the size and upload-number regexes), sniff over every Guitar Pro and Power Tab header and zips whose central directory lists Content/score.gpif (a small end-of-central-directory reader, never java.util.zip's stream); every scenario replays: candidates sorted (-stars, version, id), at most 3 downloads with cache=False from /tabs/download/{id}.html, a file kept as the lowest free guitar-N with its version, kv gtptabs:checked: and gtptabs:unusable:, PagesNotFiles after three pages, a song with a file getting none; MuseScore.songPages equals musescore.song_pages over a musescore_index fixture (at most 3, oldest first) and sends no request; nix develop -c pytest -q passes; nix build .#checks.x86_64-linux.package passes; android/scripts/device-test.sh --area tab_files passes

Brief:

> Repo /home/dani/Projects/caracole. Lane tab-files, branch android/tab-files, worktree .claude/worktrees/tab-files. Read docs/superpowers/plans/2026-11-03-android-port-m4-m6.md §7.0 first: its rules bind you. Depends on: html-tree, http-client, library-writes, overrides-model. Phase A while any of html-tree, http-client, library-writes, overrides-model hasn't merged; Phase B once all have (§7.0). Device lane: android/scripts/device-test.sh alone runs your area and classes.
>
> Plan sections: §3, §5.1 (core.sites). Phase A while a producer hasn't merged; Phase B: replays.
> Port gtptabs.py and gtptabs_fetch.py for one song with refresh_index=False (_Index and candidates by artist keys and 'Last, First' rotation and compact matches; artist pages cached 30 days, a stale copy BudgetExhausted; the candidate rules: same title key, a format of gp3, gp4, gp5, gpx, gp or ptb, at most 5 MB, a guitar part; download; sniff; keep as guitar-N.<ext> with kind guitar-pro or power, rating = stars, raw {title, format, size_kb, instruments, download}; never a replace or a delete), title_page for the Requests tab, and musescore.song_pages (no client: MuseScore gets no request from the phone). Keep sniff and the numbering where lane inbox-share (M6) reuses them. The stage file core/lookup/sites/GtpTabs.kt is yours, worded as get.py words it (GTPTABS_KEPT and the rest), through StageContext (test with FakeAsking).
> Commit: feat(android): gtptabs.com's files and MuseScore's links for a lookup.

#### jobs-queue: The job queue keeps Python's command lines and rules

- Branch `android/jobs-queue` · kotlin · M4 · about 1700 lines · depends on – · device
- Goal: The phone's JobQueue queues, joins, cancels, tries again and remembers jobs as web/jobs.py and history.py do, from command lines held as data, and lets a long job yield to the lookups queued behind it.
- Owns: `android/server/src/main/kotlin/io/github/danielhp95/caracole/server/jobs/JobQueue.kt`; `android/server/src/main/kotlin/io/github/danielhp95/caracole/server/jobs/Commands.kt`; `android/server/src/main/kotlin/io/github/danielhp95/caracole/server/jobs/JobHistory.kt`; `android/server/src/test/kotlin/io/github/danielhp95/caracole/server/jobs/JobQueueTest.kt`; `android/server/src/test/kotlin/io/github/danielhp95/caracole/server/jobs/JobHistoryTest.kt`; `android/server/src/test/kotlin/io/github/danielhp95/caracole/server/jobs/QueueVectorsTest.kt`; `tests/test_conformance_queue.py`; `tests/conformance/vectors/web/queue.jsonl`; `tests/conformance/vectors/web/history.jsonl`; `android/server/src/testFixtures/kotlin/io/github/danielhp95/caracole/server/testing/replays/QueueReplay.kt`
- Must not touch: §7.0's common list
- Provides: JobSpec with commands, Command, CommandRunner, Commands; JobQueue.submitAll, again, cancel with 'together', _pick/_as_much/_join; JobHistory (stateDir/requests.jsonl); JobQueue.onEnd (each job's end, for the afterJob hook and Alerts.failed); JobContext.yieldToQueued() (runs the lookups queued meanwhile, then returns; called with no write held)
- Consumes: the skeleton's JobSpec and JobContext declarations
- Tests: android/server/src/test/kotlin/io/github/danielhp95/caracole/server/jobs/JobQueueTest.kt; android/server/src/test/kotlin/io/github/danielhp95/caracole/server/jobs/JobHistoryTest.kt; android/server/src/test/kotlin/io/github/danielhp95/caracole/server/jobs/QueueVectorsTest.kt; tests/test_conformance_queue.py
- Done when: nix develop ./android -c gradle -p android test passes; nix develop ./android -c gradle -p android assembleDebug assembleDebugAndroidTest passes; nix develop -c pytest -q -n 0 tests/test_conformance_queue.py passes (check mode); nix develop -c pytest -q tests/test_corpus_budget.py passes; every record of vectors/web/queue.jsonl matches: submit, submit_all and cancel sequences of Python's JobSpecs (steps as Python spells them) giving the jobs (steps, stages, title, fetching, together) and which answered which (_pick, _as_much, _join); every record of vectors/web/history.jsonl matches: sample requests.jsonl files giving what load keeps (the newest 100 of 30 days, waiting or running ones INTERRUPTED, the next ids), and a save then rewrite giving Python's bytes; JobQueueTest: Try again re-queues a finished job's commands, dropping --auto and --no-songbooks; a job of the old kinds (run lambda) still runs; onBusy as before; JobQueueTest: yieldToQueued runs a lookup queued during a long job before the long job goes on; onEnd fires once a job, cancelled ones too; nix develop -c pytest -q passes; nix build .#checks.x86_64-linux.package passes; android/scripts/device-test.sh --area queue passes

Brief:

> Repo /home/dani/Projects/caracole. Lane jobs-queue, branch android/jobs-queue, worktree .claude/worktrees/jobs-queue. Read docs/superpowers/plans/2026-11-03-android-port-m4-m6.md §7.0 first: its rules bind you. Depends on: none (after skeleton-m4). Runs whole at once. Device lane: android/scripts/device-test.sh alone runs your area and classes.
>
> Plan sections: §1 (Jobs are command lines, the request history), §5.3 (server.jobs). M3's queue knows one job per key and lambdas; Try again, the Requests tab and a history across a restart need Python's rules over command lines.
> Port web/jobs.py's queue rules over JobSpec.commands (Command(label, args) spelled as Python's steps, e.g. ("Look it up now", ["get", "--progress", "--", artist, title])): _pick (the --ug/--tab/--lacuerda/--harptabs/--gametabs and --choose/--keep/--keep-more/--clear options), _as_much (a pick joins only the song's last job with the same pick; otherwise a lookup or fetch is the answer), _join (a lookup takes the place of a waiting add), _stages, _looks_up, _fetches, _reports; submit and submitAll (all or nothing, 'together'); cancel (queued only, and those queued together); again (the same commands, --auto and --no-songbooks dropped); LIMIT 20, KEEP 100. A job whose run is null runs its commands through Commands (the runner by args[0]) in-process, one after another, each step's state as Python's. JobHistory is history.py's format 1 at stateDir/requests.jsonl (0600): a line appended per change, rewritten past three lines a request or MAX_BYTES, load as history.py, INTERRUPTED for one that waited or ran. Keep the M3 behaviour of the kinds add, remove, sync and index. Two hooks the skeleton declared: onEnd(job) after each job (Assembly's afterJob and Alerts.failed hang on it), and JobContext.yieldToQueued(): a long job (the render job of M5, between two songs) calls it holding no Database.write; the queue then runs, in the same worker, every lookup kind queued since (song, versions, lacuerda-search, lacuerda-artist, harptabs-artist), and returns; a yielding job shows 'waiting for N requests' in its line meanwhile. Fill QueueReplay. Write tests/test_conformance_queue.py.
> Commit: feat(android): the phone's job queue keeps caracole serve's command lines and rules.

#### job-views: Every job's line, chips and outcome

- Branch `android/requests` · mixed · M4 · about 1900 lines · depends on jobs-queue · Phase A may start early · device
- Goal: JobViews and /jobs.json say every job's line, chips and outcome as status.py, outcome.py and jobs_routes.py do, for every kind Python has and the phone's own kinds.
- Owns: `android/server/src/main/kotlin/io/github/danielhp95/caracole/server/jobs/JobViews.kt`; `android/server/src/main/kotlin/io/github/danielhp95/caracole/server/jobs/Status.kt`; `android/server/src/main/kotlin/io/github/danielhp95/caracole/server/jobs/Outcomes.kt`; `android/server/src/main/kotlin/io/github/danielhp95/caracole/server/jobs/SongFacts.kt`; `android/server/src/main/kotlin/io/github/danielhp95/caracole/server/jobs/JobsRoutes.kt`; `android/server/src/test/kotlin/io/github/danielhp95/caracole/server/jobs/JobViewsTest.kt`; `android/server/src/test/kotlin/io/github/danielhp95/caracole/server/jobs/JobsRoutesTest.kt`; `android/server/src/testFixtures/kotlin/io/github/danielhp95/caracole/server/testing/replays/JobViewsReplay.kt`; `src/caracole/web/status.py (the todo parameter only)`; `status.py's test file (its cases)`; `tests/test_conformance_web.py (job_views only)`; `tests/conformance/vectors/web/job_views*.jsonl`; `tests/conformance/vectors/web/outcome*.jsonl`; `AGENTS.md (##### The Requests tab on the phone, its lines bullet)`
- Must not touch: §7.0's common list
- Provides: JobViews.view and line for every kind Python has (song, versions, lacuerda-search, lacuerda-artist, harptabs-artist, songbook, review, harmonica, export:mine, remove, sync, index, peer health, index merge) and PhoneKinds' entries; Status, Outcomes, SongFacts
- Consumes: JobQueue, JobHistory, Commands (jobs-queue); PhoneKinds (the skeletons'); SongCards (M2)
- Tests: android/server/src/test/kotlin/io/github/danielhp95/caracole/server/jobs/JobViewsTest.kt; android/server/src/test/kotlin/io/github/danielhp95/caracole/server/jobs/JobsRoutesTest.kt; tests/test_conformance_web.py
- Done when: nix develop ./android -c gradle -p android test passes; nix develop ./android -c gradle -p android assembleDebug assembleDebugAndroidTest passes; nix develop -c pytest -q -n 0 tests/test_conformance_web.py passes (check mode); nix develop -c pytest -q tests/test_corpus_budget.py passes; every record of vectors/web/job_views.jsonl matches for every kind and state Python has (the generator extends as_phone_job to them all, M6's kinds and skeleton-m4's peer health and index merge included), with todo=None, and PhoneKinds' kinds as §5.3's table words them; every record of vectors/web/outcome.jsonl matches (chips and reasons from get.py's stage words, the no-PDF words included: a pdf stage skipped is not drawn); status.job_line takes todo: str | None = TODO; None gives the line with no link (a Python test first); android/scripts/device-test.sh --area job_views passes; android/scripts/device-test.sh --app passes (EndToEndTest, PinchTest, SyncTabTest and PhoneEndToEndTest, each against its own computer, as the M1-3 integration ran them); nix develop -c pytest -q passes; nix build .#checks.x86_64-linux.package passes

Brief:

> Repo /home/dani/Projects/caracole. Lane job-views, branch android/requests, worktree .claude/worktrees/requests. Read docs/superpowers/plans/2026-11-03-android-port-m4-m6.md §7.0 first: its rules bind you. Depends on: jobs-queue. Phase A while any of jobs-queue hasn't merged; Phase B once all have (§7.0). Group: job-views → requests-feed, in turn; merge main in first. Device lane: android/scripts/device-test.sh alone runs your area and classes.
>
> Plan sections: §1 (Words), §5.3 (server.jobs, PhoneKinds). Lane requests-feed follows you on android/requests.
> Port web/status.py (job_line, song_line, SongFacts and song_of: the sheet's href, review, not_found, checked_now by ug_checked_at >= started_at, ignored, the picker, a lacuerda pick pending, elsewhere through the indexes, asked_ug, sheet_from; _artist_read from a job's last line), web/outcome.py (LOOKUP_STEPS, steps, progress, outcome; its _FAILED, _BLOCKED, _COOLING, _SPENT and _STATUS regexes through PyRegex over the stage words) and jobs_routes.view for every kind Python has, so no M6 lane edits JobViews; a phone-only kind (PhoneKinds.kt, the skeletons', §5.3's table) is read from that registry, never written here. The to-do link: status.job_line takes todo (default TODO) and the phone's variant is recorded with None; never fork a word in Kotlin alone. JobsRoutes' songbooks source is the skeleton's wiring.
> Commit: feat(android): every job's line, chips and outcome on the phone.

#### requests-feed: The Requests tab, its feed and Try again

- Branch `android/requests` · mixed · M4 · about 1300 lines · depends on job-views · device
- Goal: /requests.json, POST /jobs/again and the library page's Requests tab work on the phone as feed.py, jobs_routes.py and library_page.py make them.
- Owns: `android/server/src/main/kotlin/io/github/danielhp95/caracole/server/jobs/Feed.kt`; `android/server/src/main/kotlin/io/github/danielhp95/caracole/server/routes/RequestsRoutes.kt`; `android/server/src/main/kotlin/io/github/danielhp95/caracole/server/page/LibraryPage.kt`; `android/server/src/test/kotlin/io/github/danielhp95/caracole/server/routes/RequestsRoutesTest.kt`; `android/server/src/test/kotlin/io/github/danielhp95/caracole/server/jobs/FeedTest.kt`; `android/server/src/test/kotlin/io/github/danielhp95/caracole/server/page/LibraryPageTest.kt`; `android/server/src/testFixtures/kotlin/io/github/danielhp95/caracole/server/testing/replays/RequestsReplay.kt`; `tests/test_conformance_requests.py`; `tests/test_conformance_library_page.py`; `tests/conformance/data/caracole/page/requests.json`; `tests/conformance/vectors/web/requests*.jsonl`; `tests/conformance/vectors/web/library_page*`; `AGENTS.md (##### The Requests tab on the phone, its tab bullet)`
- Must not touch: §7.0's common list
- Provides: Feed (Now, Today, Earlier; Cancel; the output); GET /requests.json, POST /jobs/again; LibraryPage's Requests tab and panel
- Consumes: JobViews, Status, Outcomes (job-views); JobHistory (jobs-queue)
- Tests: android/server/src/test/kotlin/io/github/danielhp95/caracole/server/routes/RequestsRoutesTest.kt; android/server/src/test/kotlin/io/github/danielhp95/caracole/server/jobs/FeedTest.kt; android/server/src/test/kotlin/io/github/danielhp95/caracole/server/page/LibraryPageTest.kt; tests/test_conformance_requests.py
- Done when: nix develop ./android -c gradle -p android test passes; nix develop ./android -c gradle -p android assembleDebug assembleDebugAndroidTest passes; nix develop -c pytest -q -n 0 tests/test_conformance_requests.py tests/test_conformance_library_page.py passes (check mode); nix develop -c pytest -q tests/test_corpus_budget.py passes; every record of vectors/web/requests.jsonl matches: feed under TZ=UTC and TZ=Europe/Madrid (Locale.ROOT, English month names; the zone's label from tzdata's abbreviation, CET and CEST, as Python's %Z gives it, never the JDK's or ICU's GMT+01:00); the library page's corpus is written without patching _requests_tab and _requests_panel, and LibraryPage matches it byte for byte, with server.active counted; android/scripts/device-test.sh --area requests passes; android/scripts/device-test.sh --app passes (EndToEndTest, PinchTest, SyncTabTest and PhoneEndToEndTest, each against its own computer, as the M1-3 integration ran them); nix develop -c pytest -q passes; nix build .#checks.x86_64-linux.package passes

Brief:

> Repo /home/dani/Projects/caracole. Lane requests-feed, branch android/requests, worktree .claude/worktrees/requests. Read docs/superpowers/plans/2026-11-03-android-port-m4-m6.md §7.0 first: its rules bind you. Depends on: job-views. Starts once every producer has merged. Group: job-views → requests-feed, in turn; merge main in first. Device lane: android/scripts/device-test.sh alone runs your area and classes.
>
> Plan sections: §5.3, §5.4 (/requests.json, /jobs/again). Follows job-views on android/requests.
> Port web/feed.py (Now, Today, Earlier; Cancel posting /jobs/cancel; the output with meta, stages, steps and lines once opened with ?open=N; 'requested …' through stamps.shown(local=True): the zone's label is tzdata's abbreviation, a small table your generator exports for the zones it records, since java.time and ICU name zones otherwise), GET /requests.json (script-only) and POST /jobs/again as jobs_routes. LibraryPage fills __TABREQUESTS__ and __REQUESTS__ from data/caracole/page/requests.json, which your generator exports from library_page's _requests_tab and _requests_panel (never retyped); stop the library_page generator patching them.
> Commit: feat(android): the Requests tab on the phone.

#### lookup: The lookup on the phone: get.py and the lookup commands

- Branch `android/lookup` · mixed · M4 · about 2200 lines · depends on health-pace, jobs-queue, overrides-model, library-writes · Phase A may start early · device
- Goal: Lookup.run gives get.py's frame, stage order, envelope words, budgets and closing records for one song over the site stages, and the runners run get and the lookup commands as jobs.
- Owns: `android/core/src/main/kotlin/io/github/danielhp95/caracole/core/lookup/Lookup.kt`; `android/core/src/main/kotlin/io/github/danielhp95/caracole/core/lookup/LookupWords.kt`; `android/core/src/main/kotlin/io/github/danielhp95/caracole/core/lookup/InteractiveAsk.kt`; `android/core/src/main/kotlin/io/github/danielhp95/caracole/core/lookup/internal/**`; `android/core/src/test/kotlin/io/github/danielhp95/caracole/core/lookup/LookupTest.kt`; `android/core/src/test/kotlin/io/github/danielhp95/caracole/core/lookup/InteractiveAskTest.kt`; `android/server/src/main/kotlin/io/github/danielhp95/caracole/server/lookups/GetRunner.kt`; `android/server/src/main/kotlin/io/github/danielhp95/caracole/server/lookups/VersionsRunner.kt`; `android/server/src/main/kotlin/io/github/danielhp95/caracole/server/lookups/LaCuerdaRunner.kt`; `android/server/src/main/kotlin/io/github/danielhp95/caracole/server/lookups/HarpTabsRunner.kt`; `android/server/src/test/kotlin/io/github/danielhp95/caracole/server/lookups/**`; `android/core/src/testFixtures/kotlin/io/github/danielhp95/caracole/core/testing/replays/LookupReplay.kt`; `tests/test_conformance_lookup.py`; `tests/conformance/vectors/lookup/words*.jsonl`; `tests/conformance/vectors/lookup/asking*.jsonl`; `tests/conformance/vectors/lookup/after_the_sheet*.jsonl`; `src/caracole/get.py (the no-PDF words only)`; `tests/test_get.py (their case)`; `AGENTS.md (##### Lookups on the phone)`
- Must not touch: §7.0's common list
- Provides: core.lookup.Lookup, LookupWords, InteractiveAsk (implements Asking and CommandContext's envelope); the runners get, versions (keep, keep-more, choose, clear), lacuerda, harptabs; get.py's NO_PDFS and PAGES_MADE words
- Consumes: Pace, Clients, Health, PhoneConfig (health-pace); Commands, JobContext (jobs-queue); OverrideWriters, OverrideUrls (overrides-model); LibraryStore (M3), Versions (library-writes); the site stages and command files of core/lookup/sites (each its site lane's; skeleton-m4's neutral stubs until); SongPages, SongbookPages (seams; NONE in M4); Alerts (skeleton-m4)
- Tests: android/core/src/test/kotlin/io/github/danielhp95/caracole/core/lookup/LookupTest.kt; android/core/src/test/kotlin/io/github/danielhp95/caracole/core/lookup/InteractiveAskTest.kt; tests/test_conformance_lookup.py
- Done when: nix develop ./android -c gradle -p android test passes; nix develop ./android -c gradle -p android assembleDebug assembleDebugAndroidTest passes; nix develop -c pytest -q -n 0 tests/test_conformance_lookup.py passes (check mode); nix develop -c pytest -q tests/test_corpus_budget.py passes; every record of vectors/lookup/words.jsonl, asking.jsonl and after_the_sheet.jsonl matches (each provider state and exception giving get.py's stage state and detail; SHEETS_SHARE's arithmetic; the no-PDF words); LookupTest over fake stages: the stage order and their skips (a refusal marks song failed and the rest skipped; a site that failed or blocked is skipped after; a stage's exception is a bug and fails the job), the lyrics' _then words, the closing record_ok for each provider that answered, Alerts.blocked once for a block; Lookup.run is blocking and runs in Database.writeBlocking on the worker, in autocommit: an event, a block and kv http:last_request committed as each happens (a test stops the job mid-lookup and reads them); the pdf stage answers 'skipped' with get.py's NO_PDFS words while SongPages is NONE, and runs SongPages there once it isn't; the pages stage is the library page's (the search invalidated); android/scripts/device-test.sh --area lookup passes; nix develop -c pytest -q passes; nix build .#checks.x86_64-linux.package passes

Brief:

> Repo /home/dani/Projects/caracole. Lane lookup, branch android/lookup, worktree .claude/worktrees/lookup. Read docs/superpowers/plans/2026-11-03-android-port-m4-m6.md §7.0 first: its rules bind you. Depends on: health-pace, jobs-queue, overrides-model, library-writes. Phase A while any of health-pace, jobs-queue, overrides-model, library-writes hasn't merged; Phase B once all have (§7.0). Device lane: android/scripts/device-test.sh alone runs your area and classes.
>
> Plan sections: §2 (data flow), §5.1 (core.lookup, the site stages), §5.3 (runners), §3. Phase A once health-pace and jobs-queue merge; Phase B as overrides-model and library-writes merge. The site stages and the lookup commands are their site lanes' files (core/lookup/sites/*, skeleton-m4's neutral stubs answering 'skipped' with get.py's words for a site not built); you write the frame that calls them, and the envelope they ask through.
> Port get.py's _Lookup: STAGES in order (song, match, sheet, pdf, lyrics, ug, lacuerda, gtptabs, harptabs, gametabs, pages, songbooks) with Python's labels; find_song through LibraryStore.add and OverrideWriters (no wanted.txt on the phone) and _refuse_an_unused_kind (OverrideUrls.classifyTabUrl); the envelope (InteractiveAsk, implementing skeleton-m4's Asking): _usable (off, blocked, failed earlier, cooling with its until in '%Y-%m-%d %H:%M UTC'), asking (ProviderBlocked: record_block and Alerts.blocked, skipped; BudgetExhausted worded as the lookup's, the hour's or kept-for-sheets plus '; the nightly run does the rest'; ProviderError: record_error, failed, the site skipped after), after_the_sheet (left = per_hour - ceil(per_hour*0.5) - used); the sheet order (a LaCuerda pick first; UG's first pass; LaCuerda when no sheet); lyrics LRCLIB, Megalobiz (Pace.withinTheDay), AZLyrics and _then's words; _owed and ug_dirty; _check_readable to Progress.readable; the closing record_ok for each provider that answered (answered_any, own events). On the phone no ChordPro runs: first, test first, get.py gains its no-PDF words (NO_PDFS, 'skipped' while no page is made; PAGES_MADE once the phone writes the song's pages), constants the corpus records, used by nothing on the computer but the corpus; the pdf stage calls SongPages.render (PhoneRender from M5) and the pages stage is the library page (served live on the phone: the search invalidated). The runners (server/lookups) adapt JobContext to Progress and dispatch: get; versions --keep and --keep-more to VersionsCommands, --choose as get --tab, --clear as removePin then get; lacuerda --artist and --search to LaCuerdaCommands; harptabs --artist to HarpTabsCommands. Lookup.run is blocking (Database.write's block is not suspending): the runner calls it in writeBlocking on the worker; only the worker writes, and a nested write throws. A lookup alerts on the phone where the computer's sends none (the phone has no nightly run to tell): say so under your AGENTS.md heading. Whole lookups replayed from recorded answers are lane lookup-scenarios'.
> Commit: feat(android): the phone looks songs up, as caracole get does.

#### lookup-scenarios: Whole lookups replayed from the computer's records

- Branch `android/lookup-scenarios` · mixed · M4 · about 1500 lines · depends on lookup, matcher, ug-fetch-artist, lyrics, lacuerda-sheets, harptabs, gametabs, tab-files · Phase A may start early · device
- Goal: A whole lookup on the phone sends the requests and writes the rows, kv and files get.py does for the same library, cache and answers, and the lookup commands do as theirs.
- Owns: `tests/test_conformance_lookup_scenarios.py`; `tests/conformance/vectors/lookup/get*.jsonl`; `tests/conformance/vectors/lookup/commands_get*.jsonl`; `android/core/src/test/kotlin/io/github/danielhp95/caracole/core/lookup/LookupScenariosTest.kt`; `android/core/src/testFixtures/kotlin/io/github/danielhp95/caracole/core/testing/replays/LookupScenariosReplay.kt`; `tests/helpers/scenario.py (the whole-lookup recorder, beside skeleton-m4's record)`
- Must not touch: §7.0's common list
- Provides: vectors/lookup/get.jsonl, whole lookups; LookupScenariosReplay
- Consumes: every M4 site stage and Lookup
- Tests: android/core/src/test/kotlin/io/github/danielhp95/caracole/core/lookup/LookupScenariosTest.kt; tests/test_conformance_lookup_scenarios.py
- Done when: nix develop ./android -c gradle -p android test passes; nix develop ./android -c gradle -p android assembleDebug assembleDebugAndroidTest passes; nix develop -c pytest -q -n 0 tests/test_conformance_lookup_scenarios.py passes (check mode); nix develop -c pytest -q tests/test_corpus_budget.py passes; every scenario of vectors/lookup/get.jsonl replays: a new song found and its sheet kept, a picked tab, a picked LaCuerda sheet, a block on UG cooling it with the other sites asked, a spent hour, the kept-for-sheets share, a refusal, the lyrics' _then words, a song through its artist's page: the requests in order, the stage stream, the events, the rows, kv and files' sha256 the phone writes, the closing record_ok; every record of vectors/lookup/commands_get.jsonl matches (versions --choose and --clear through get); android/scripts/device-test.sh --area lookup_scenarios passes; nix develop -c pytest -q passes; nix build .#checks.x86_64-linux.package passes

Brief:

> Repo /home/dani/Projects/caracole. Lane lookup-scenarios, branch android/lookup-scenarios, worktree .claude/worktrees/lookup-scenarios. Read docs/superpowers/plans/2026-11-03-android-port-m4-m6.md §7.0 first: its rules bind you. Depends on: lookup, matcher, ug-fetch-artist, lyrics, lacuerda-sheets, harptabs, gametabs, tab-files. Phase A while any of lookup, matcher, ug-fetch-artist, lyrics, lacuerda-sheets, harptabs, gametabs, tab-files hasn't merged; Phase B once all have (§7.0). Device lane: android/scripts/device-test.sh alone runs your area and classes.
>
> Plan sections: §3 (scenario records), §5.1. Phase A while a producer hasn't merged: the recorder and the generator.
> Record whole lookups in Python: get.py's _Lookup run with `_common.transport_for` monkeypatched to the scenario's httpx.MockTransport (scenario.py's whole-lookup recorder takes a transport hook beside its clients), `_common.sleep` recorded and skipped, the clock fixed; chordpro absent and render_all, write_pages and render_songbooks patched to no-ops (what SongPages.NONE and SongbookPages.NONE are in M4), so Python writes no PDF, page, index.html or render:* kv; wanted.txt and its kv (wanted:first_seen:) left out of the record, the phone adding through LibraryStore.add; out's rows, kv and files filtered to the tables and prefixes the phone writes, the record naming the filter. Replay each through Lookup.run over FakeTransport.
> Commit: test(android): whole lookups replayed from the computer's records.

#### lookup-routes: The library page's lookups on the phone, and the app while they run

- Branch `android/lookup-routes` · mixed · M4 · about 2000 lines · depends on lookup, job-views, lacuerda-pages, health-pace · Phase A may start early · device
- Goal: Get it, Fetch now, Fetch them, an artist's Songs and LaCuerda's own search queue real lookups on the phone, the search answers lacuerda_search and lacuerda_unlisted, and the app keeps a lookup alive in the foreground.
- Owns: `android/server/src/main/kotlin/io/github/danielhp95/caracole/server/routes/LookupRoutes.kt`; `android/server/src/main/kotlin/io/github/danielhp95/caracole/server/routes/LibraryRoutes.kt`; `android/server/src/main/kotlin/io/github/danielhp95/caracole/server/routes/SearchRoutes.kt`; `android/server/src/main/kotlin/io/github/danielhp95/caracole/server/routes/search/Found.kt`; `android/server/src/main/kotlin/io/github/danielhp95/caracole/server/page/MirrorPageData.kt (lyrics_from on a minimal card only)`; `android/server/src/test/kotlin/io/github/danielhp95/caracole/server/routes/LookupRoutesTest.kt`; `android/server/src/test/kotlin/io/github/danielhp95/caracole/server/routes/library/LibraryRoutesTest.kt`; `android/server/src/test/kotlin/io/github/danielhp95/caracole/server/routes/search/ApiSearchTest.kt`; `android/server/src/test/kotlin/io/github/danielhp95/caracole/server/page/MirrorPageDataTest.kt`; `android/e2e/src/test/kotlin/io/github/danielhp95/caracole/e2e/PhoneScenarioTest.kt (phase 2's lines only)`; `android/app/src/main/kotlin/io/github/danielhp95/caracole/Working.kt`; `android/app/src/main/kotlin/io/github/danielhp95/caracole/Caracole.kt`; `android/app/src/main/kotlin/io/github/danielhp95/caracole/SyncService.kt`; `android/app/src/androidTest/kotlin/io/github/danielhp95/caracole/LookupOfflineTest.kt`; `tests/test_conformance_lookup_routes.py`; `tests/conformance/vectors/web/lookup_routes*.jsonl`; `tests/conformance/vectors/web/api_search_gate*.jsonl`; `android/README.md (## Lookups on the phone)`; `android/app/src/androidTest/kotlin/io/github/danielhp95/caracole/PhoneEndToEndTest.kt (its Get it and typed-query lines only)`; `android/server/src/testFixtures/kotlin/io/github/danielhp95/caracole/server/testing/replays/LookupRoutesReplay.kt`; `android/app/src/androidTest/kotlin/io/github/danielhp95/caracole/NoNetworkTest.kt`
- Must not touch: §7.0's common list
- Provides: POST /lookup, /request fetch=1, /fetch, /lacuerda/artist, /lacuerda/search, /harptabs/artist, /versions/keep-more on the phone; SearchRoutes.enabled from PhoneConfig, invalidated after every job; the app's foreground while a lookup runs; Caracole's RealTransport and cache dir; PhoneDeps.searchesLacuerda honoured (false: /api/search's lacuerda_search null, as WebApp(searches_lacuerda=False))
- Consumes: the runners and LookupRequest (lookup); JobViews, Status (job-views); LaCuerdaSearch.gate (lacuerda-pages); PhoneConfig (health-pace)
- Tests: android/server/src/test/kotlin/io/github/danielhp95/caracole/server/routes/LookupRoutesTest.kt; android/server/src/test/kotlin/io/github/danielhp95/caracole/server/routes/search/ApiSearchTest.kt; android/app/src/androidTest/kotlin/io/github/danielhp95/caracole/LookupOfflineTest.kt; tests/test_conformance_lookup_routes.py; android/app/src/androidTest/kotlin/io/github/danielhp95/caracole/NoNetworkTest.kt
- Done when: nix develop ./android -c gradle -p android test passes; nix develop ./android -c gradle -p android assembleDebug assembleDebugAndroidTest passes; nix develop -c pytest -q -n 0 tests/test_conformance_lookup_routes.py passes (check mode); nix develop -c pytest -q tests/test_corpus_budget.py passes; every record of vectors/web/lookup_routes.jsonl matches (each route's form checks, refusals and 202 answers as search_routes.lookup_request and library_routes.fetch give them, review_first included); every record of vectors/web/api_search_gate.jsonl matches: /api/search's lacuerda_search ({state, query, key, why}) and lacuerda_unlisted from kv and events fixtures; FETCH_LATER is gone; the e2e's phase 2 asserts the lookups' lines with a transport that refuses every site (stages failed, the song added, never a miss): CARACOLE_ANDROID_E2E=1 nix develop -c pytest -q -n 0 tests/test_android_e2e.py passes; a minimal card of a song with lyrics from Megalobiz or AZLyrics carries lyrics_from, as library_page writes it; a POST /lookup that doesn't ask for JSON redirects to /#tab=requests&job=N (status.details_href), recorded in vectors/web/lookup_routes.jsonl; PhoneEndToEndTest's Get it and typed query run with the test runner's refusing transport and searchesLacuerda false, and assert the lookup's lines (stages failed, the song added, never a miss); android/scripts/device-test.sh --area lookup_routes io.github.danielhp95.caracole.LookupOfflineTest io.github.danielhp95.caracole.NoNetworkTest passes (a lookup with no network ends with its stages failed, the song added, the 'jobs' notification while it ran; with no sites set, a lookup opens no socket); android/scripts/device-test.sh --app passes (EndToEndTest, PinchTest, SyncTabTest and PhoneEndToEndTest, each against its own computer, as the M1-3 integration ran them); nix develop -c pytest -q passes; nix build .#checks.x86_64-linux.package passes

Brief:

> Repo /home/dani/Projects/caracole. Lane lookup-routes, branch android/lookup-routes, worktree .claude/worktrees/lookup-routes. Read docs/superpowers/plans/2026-11-03-android-port-m4-m6.md §7.0 first: its rules bind you. Depends on: lookup, job-views, lacuerda-pages, health-pace. Phase A while any of lookup, job-views, lacuerda-pages, health-pace hasn't merged; Phase B once all have (§7.0). Device lane: android/scripts/device-test.sh alone runs your area and classes.
>
> Plan sections: §5.4 (the phone's routes), §1 (no live request, the cache, the user agent), §5.5. Phase A while a producer hasn't merged: the routes against the declared runners and the generator; Phase B: real jobs.
> Move /lookup and /request's fetch=1 from LibraryRoutes to lookup jobs (search_routes.lookup_request, library_routes.request and fetch with its review_first refusal); answer /fetch, /lacuerda/artist, /lacuerda/search (its gate; never twice for a query; auto or by hand), /harptabs/artist and /versions/keep-more, the entries the skeleton moved from Stubs into LookupRoutes. Found.kt: lacuerda_search from LaCuerdaSearch.gate and lacuerda_unlisted as search_routes computes it; SearchRoutes' enabled set from PhoneConfig, and invalidate() after every job ends (a lookup adds a song and changes the gate's kv and events). MirrorPageData's minimal card carries lyrics_from (the fair-use link back), until M5's cards. The app: Caracole passes RealTransport and the cache under the state folder (never context.cacheDir); Working's lines know the lookup kinds; the queue's busy keeps the foreground service and its 'jobs' notification. The e2e's phase 2 asserted FETCH_LATER: change only its lines (lane lookups-e2e replaces its transport with fake sites). PhoneEndToEndTest types a song and presses Get it: on the emulator that is now a real lookup, so its lines are yours: it runs under CaracoleTestRunner's refusing transport (skeleton-m4's: every app test does unless it sets Caracole.sitesForTests) with PhoneDeps.searchesLacuerda false, and asserts the no-miss lines. Found.kt honours searchesLacuerda (false: lacuerda_search null, as the computer's WebApp(searches_lacuerda=False)). A POST /lookup that doesn't ask for JSON redirects to /#tab=requests&job=N (the phone has no /lookup page). Never touch rows.js, card.js or library.js.
> Commit: feat(android): the library page's lookups on the phone.

#### crossing-computer: Politeness across two caracoles: the computer's side

- Branch `android/sync-crossing` · python · M4 · about 1800 lines · depends on –
- Goal: The computer gives its health and settings in the state document, takes a peer's health through POST /peer/health and a queued caracole peer health, and caracole peer sync crosses health both ways.
- Owns: `src/caracole/politeness.py`; `src/caracole/health.py (merge_state)`; `src/caracole/peer_sync.py (state_document's members, PeerState)`; `src/caracole/web/peer_routes.py (/peer/health, state)`; `src/caracole/peer_push.py (staging shared with health)`; `src/caracole/commands/peer.py (peer health, peer sync's crossing)`; `tests/test_politeness.py`; `tests/test_web_peer.py`; `tests/test_commands_peer.py`; `tests/test_health.py`; `tests/test_conformance_sync.py (health and settings records only)`; `tests/conformance/vectors/sync/health*.jsonl`; `tests/conformance/vectors/sync/settings*.jsonl`; `docs/superpowers/specs/2026-11-03-politeness-crossing.md`; `docs/usage.md (### Politeness across two caracoles)`; `AGENTS.md ('serve never takes it': the health staging file)`
- Must not touch: §7.0's common list
- Provides: politeness.health_document, settings_document, merge_health, RULES; health.merge_state; GET /api/peer/state's health and settings; POST /peer/health, caracole peer health --take FILE --progress
- Consumes: schema 16 (the skeleton's)
- Tests: tests/test_politeness.py; tests/test_web_peer.py; tests/test_commands_peer.py; tests/test_conformance_sync.py
- Done when: nix develop -c pytest -q passes; nix build .#checks.x86_64-linux.package passes; nix develop -c pytest -q -n 0 tests/test_conformance_sync.py passes (check mode); nix develop -c pytest -q tests/test_corpus_budget.py passes; tests/test_politeness.py: a document holds exactly §4.2's members (own events of the window, never another side's; per-song records by identity key; nothing of youtube-search, lookup:, *:keys or backfill), merging two documents both ways gives one state on both sides (a running cooldown never shortened; a reset on one side merged both ways stays reset; a block after a reset is the first strike; events never counted twice on a second merge; the later check's ug_dirty taken, never an OR), and every unit's digest is unchanged by a merge; POST /peer/health refuses a missing token, another site's fetch, a body over 4 MiB or a malformed document, and otherwise answers 202 with the queued job's id; the staged file is 0600 under state_dir/peer/ and deleted once taken or after an hour; caracole peer sync between two caracoles leaves each with the other's cooldowns and events (tests/test_commands_peer.py); vectors/sync/health.jsonl and settings.jsonl are written (documents of fixtures; merges of pairs); nix develop ./android -c gradle -p android test passes (the state document's new members are ignored by the phone until crossing-phone)

Brief:

> Repo /home/dani/Projects/caracole. Lane crossing-computer, branch android/sync-crossing, worktree .claude/worktrees/sync-crossing. Read docs/superpowers/plans/2026-11-03-android-port-m4-m6.md §7.0 first: its rules bind you. Depends on: none (after skeleton-m4). Runs whole at once. Group: crossing-computer → crossing-phone → index-push, in turn; merge main in first.
>
> Plan sections: §4 (all of it), §5.4 (the computer's routes). The skeleton made schema 16; the spec docs/superpowers/specs/2026-11-03-politeness-crossing.md is yours to make exact where a record's value shape needs it (read each record's writer: lacuerda_search.py, ug/fetch.py, gtptabs_fetch.py, *_fetch.py's checked records), in the same commit as the code.
> The merge rules are §4.2's as settled: providers by the side whose latest decisive event is newer, never shortening a running cooldown; the songs member carries the checks (ug_checked_at with its ug_dirty, lacuerda_checked_at) by the later check, never an OR, and each :pick sub-key with its base record; ug:unreadable: never crosses. Those song columns are outside every unit's digest (peer_sync.song_value reads status, review, match, lyrics, versions, files and overrides alone): a test merges two documents and asserts every unit's digest unchanged. The job kinds of `peer health` (web/jobs.py, status.py, outcome.py) are skeleton-m4's: you write the command and the route, and a test that its job's line is theirs. Write src/caracole/politeness.py: health_document(conn, own_id, now), settings_document(cfg), merge_health(conn, doc, peer_id, now) with the RULES table of §4.2 as data, and health.merge_state. GET /api/peer/state gains health and settings (readers ignore unknown keys: FORMAT stays 2). POST /peer/health: a json route with the form token and a 4 MiB limit, the cross-origin check, checked shapes, staged as state_dir/peer/health-<16 hex>.json (0600; at most 2 waiting; EXPIRES as a push's), and `caracole peer health --take FILE --progress` queued through skeleton-m4's jobs.peer_health_job. caracole peer sync merges the peer's health and posts its own. AGENTS.md's 'serve never takes it' list gains the staged file and nothing else. Lanes crossing-phone and index-push follow you on this branch.
> Commit: feat(peer): cooldowns, request counts and gates cross at a sync.

#### crossing-phone: Politeness across two caracoles: the phone's side

- Branch `android/sync-crossing` · kotlin · M4 · about 1600 lines · depends on crossing-computer, health-pace · Phase A may start early · device
- Goal: A phone sync takes the computer's settings and health and gives its own, so a block met on one side cools the other and the hour's and day's counts are shared.
- Owns: `android/core/src/main/kotlin/io/github/danielhp95/caracole/core/sync/Politeness.kt`; `android/core/src/main/kotlin/io/github/danielhp95/caracole/core/sync/internal/politeness/**`; `android/core/src/main/kotlin/io/github/danielhp95/caracole/core/sync/SyncEngine.kt`; `android/core/src/main/kotlin/io/github/danielhp95/caracole/core/sync/PeerClient.kt`; `android/core/src/test/kotlin/io/github/danielhp95/caracole/core/sync/PolitenessTest.kt`; `android/core/src/test/kotlin/io/github/danielhp95/caracole/core/sync/SyncEngineTest.kt`; `android/core/src/testFixtures/kotlin/io/github/danielhp95/caracole/core/testing/sync/FakeComputer.kt`; `android/core/src/testFixtures/kotlin/io/github/danielhp95/caracole/core/testing/replays/PolitenessReplay.kt`; `AGENTS.md (##### Politeness across two caracoles)`; `android/core/src/test/kotlin/io/github/danielhp95/caracole/core/sync/PolitenessDigestTest.kt`
- Must not touch: §7.0's common list
- Provides: core.sync.Politeness (document, merge, mergeState); PeerClient.health, PeerState.health and settings; the agree stage's crossing
- Consumes: vectors/sync/health*.jsonl and settings*.jsonl (crossing-computer); Health, PhoneConfig.take, EventLog (health-pace)
- Tests: android/core/src/test/kotlin/io/github/danielhp95/caracole/core/sync/PolitenessTest.kt; android/core/src/test/kotlin/io/github/danielhp95/caracole/core/sync/SyncEngineTest.kt
- Done when: nix develop ./android -c gradle -p android test passes; nix develop ./android -c gradle -p android assembleDebug assembleDebugAndroidTest passes; every record of vectors/sync/health.jsonl and settings.jsonl matches (the phone's document of a fixture; each merge); SyncEngineTest against FakeComputer: after a sync the phone holds the computer's cooldown and events (origin = the computer's id), the computer was posted the phone's document, a second sync counts nothing twice, a failure of /peer/health is said in agree's detail and stops nothing; no stage is added; CARACOLE_ANDROID_E2E=1 nix develop -c pytest -q -n 0 tests/test_android_e2e.py passes; nix develop -c pytest -q passes; PolitenessDigestTest: a merge writes no SONG_COLUMNS column outside the checks and no CARRIED_KV record, and leaves Units.libraryState's digests unchanged; android/scripts/device-test.sh --area politeness passes

Brief:

> Repo /home/dani/Projects/caracole. Lane crossing-phone, branch android/sync-crossing, worktree .claude/worktrees/sync-crossing. Read docs/superpowers/plans/2026-11-03-android-port-m4-m6.md §7.0 first: its rules bind you. Depends on: crossing-computer, health-pace. Phase A while any of crossing-computer, health-pace hasn't merged; Phase B once all have (§7.0). Group: crossing-computer → crossing-phone → index-push, in turn; merge main in first. Device lane: android/scripts/device-test.sh alone runs your area and classes.
>
> Plan sections: §4.2–§4.4, §5.1 (core.sync additions). Follows crossing-computer on the branch android/sync-crossing (merge main first if health-pace landed since).
> Write core.sync.Politeness (document and merge as politeness.py; mergeState as health.merge_state), PeerState's health and settings read from the state document, PeerClient.health(token, doc) posting /peer/health, and in SyncEngine's agree stage, after take and give: PhoneConfig.take(settings), Politeness.merge(the computer's health read at compare time), then post the phone's document. The phone's own events are origin NULL; the computer's come in with origin set. Never touch the Sync tab's UI or add a stage (the sync redesign's). FakeComputer (testFixtures) answers /peer/health. Fill PolitenessReplay.
> Commit: feat(android): the phone gives and takes cooldowns and request counts at a sync.

#### index-push: The phone's index reads go to the computer

- Branch `android/sync-crossing` · mixed · M4 · about 1600 lines · depends on crossing-phone · Phase A may start early · device
- Goal: At a sync the phone exports what its lookups read since the computer's indexes stamps, posts it, and the computer merges it as caracole index merge merges a file.
- Owns: `android/core/src/main/kotlin/io/github/danielhp95/caracole/core/index/Export.kt`; `android/core/src/test/kotlin/io/github/danielhp95/caracole/core/index/ExportTest.kt`; `android/core/src/main/kotlin/io/github/danielhp95/caracole/core/sync/SyncEngine.kt (the index stage's push, after crossing-phone)`; `android/core/src/main/kotlin/io/github/danielhp95/caracole/core/sync/PeerClient.kt (pushIndex, after crossing-phone)`; `android/core/src/test/kotlin/io/github/danielhp95/caracole/core/sync/SyncEngineTest.kt (after crossing-phone)`; `android/core/src/testFixtures/kotlin/io/github/danielhp95/caracole/core/testing/sync/FakeComputer.kt (/peer/index, after crossing-phone)`; `android/core/src/testFixtures/kotlin/io/github/danielhp95/caracole/core/testing/replays/IndexExportReplay.kt`; `src/caracole/index_transfer.py (export's since and pages)`; `src/caracole/web/peer_routes.py (/peer/index, after crossing-computer)`; `src/caracole/peer_push.py (the staging, after crossing-computer)`; `src/caracole/commands/index.py (merge --delete --progress)`; `tests/test_index_transfer.py`; `tests/test_web_peer.py (after crossing-computer)`; `tests/test_commands_index.py`; `tests/test_conformance_index.py (export records only)`; `tests/conformance/vectors/index/export*.jsonl`; `docs/usage.md (### The phone's reads go to the computer (POST /peer/index))`; `AGENTS.md ('serve never takes it': the index staging file)`
- Must not touch: §7.0's common list
- Provides: IndexExport.export(db, to, pages); PeerClient.pushIndex; POST /peer/index, caracole index merge FILE --delete --progress; index_transfer.export(pages=)
- Consumes: Politeness and the agree stage (crossing-phone); IndexTransfer.merge (M2)
- Tests: android/core/src/test/kotlin/io/github/danielhp95/caracole/core/index/ExportTest.kt; tests/test_index_transfer.py; tests/test_web_peer.py
- Done when: nix develop ./android -c gradle -p android test passes; nix develop ./android -c gradle -p android assembleDebug assembleDebugAndroidTest passes; nix develop -c pytest -q passes; nix build .#checks.x86_64-linux.package passes; nix develop -c pytest -q -n 0 tests/test_conformance_index.py passes (check mode); nix develop -c pytest -q tests/test_corpus_budget.py passes; every record of vectors/index/export*.jsonl matches: the phone's export of a fixture, limited to the pages Reads noted since the last push to that computer (UG's artist pages, harptabs.com's artist pages, LaCuerda's artist pages and search rows), has Python's export(pages=) tables row for row and its META; POST /peer/index refuses without the token or over 64 MiB, and otherwise stages the file and queues the merge; a merge of the phone's file adds the phone's reads where merge's rules take them (a LaCuerda page or search row the computer already has stays the computer's) and moves no progress record back; SyncEngineTest: the index stage pushes the phone's newly noted reads whether or not it merged anything from the computer, forgets the notes once the computer's job is queued, and sends nothing when none is noted; android/scripts/device-test.sh --area index_export passes; CARACOLE_ANDROID_E2E=1 nix develop -c pytest -q -n 0 tests/test_android_e2e.py passes

Brief:

> Repo /home/dani/Projects/caracole. Lane index-push, branch android/sync-crossing, worktree .claude/worktrees/sync-crossing. Read docs/superpowers/plans/2026-11-03-android-port-m4-m6.md §7.0 first: its rules bind you. Depends on: crossing-phone. Phase A while any of crossing-phone hasn't merged; Phase B once all have (§7.0). Group: crossing-computer → crossing-phone → index-push, in turn; merge main in first. Device lane: android/scripts/device-test.sh alone runs your area and classes.
>
> Plan sections: §1 (The phone's index to the computer), §4.4, §5.1 (core.index: Reads, IndexExport), §5.4. Follows crossing-phone on android/sync-crossing.
> What to send is what the phone read, never a time window: UG's stamp in the computer's `indexes` moves with its nightly refresh, and LaCuerda's pages and search rows hold no time at all. So every store a lookup makes is noted by skeleton-m4's Reads.note(db, site, page, at) (the site lanes call it), and the push sends the pages noted since the last successful push to that computer. Python: index_transfer.export gains pages={site: [page, ...]} (those pages' rows alone, by each site's table: ug_artist_tabs by artist page, harptabs.com's artist pages, LaCuerda's artist pages and search rows; the kv progress records as export writes them); POST /peer/index (bytes, the token, 64 MiB) staged as state_dir/peer/index-<16 hex>.sqlite (0600), and `caracole index merge FILE --delete --progress` queued through skeleton-m4's jobs.index_merge_job (add --delete and --progress to merge if missing; merge's backup-before rule holds; a LaCuerda page or search row the computer has stays the computer's, as merge already rules). Kotlin: IndexExport.export(db, to, pages), a port of export limited to those pages, read in one transaction; PeerClient.pushIndex; in SyncEngine's index stage, after the merge and the checkpoint (or with nothing merged: the stage pushes either way), export the noted pages, push them, and Reads.forget the pushed notes once the computer answers 202, saying so in the stage's detail. Fill IndexExportReplay. AGENTS.md's 'serve never takes it' list gains the staged file (crossing-computer's line; extend it).
> Commit: feat(peer): the phone's index reads go to the computer at a sync.

#### lookups-e2e: M4 end to end: lookups against fake sites, on the JVM and the emulator

- Branch `android/lookups-e2e` · mixed · M4 · about 1800 lines · depends on lookup-routes, index-push, lookup-scenarios · Phase A may start early · device
- Goal: The e2e scenario looks songs up on the phone against a fake sites server and proves M4's goal: the sheet shown as text, requests within the lookup's budget, no live host, a block crossing to the computer at the next sync.
- Owns: `tests/helpers/fake_sites.py`; `tests/test_fake_sites.py`; `tests/helpers/e2e_library.py`; `tests/test_android_e2e.py`; `android/e2e/src/test/kotlin/io/github/danielhp95/caracole/e2e/**`; `android/app/src/androidTest/kotlin/io/github/danielhp95/caracole/LookupOnDeviceTest.kt`; `android/scripts/device-test.sh (its --sites branch)`
- Must not touch: §7.0's common list
- Provides: tests/helpers/fake_sites.py (serve SCENARIO PORT); the e2e's lookups phase; LookupOnDeviceTest
- Consumes: RoutedTransport (http-client); every M4 lane
- Tests: tests/test_fake_sites.py; tests/test_android_e2e.py; android/e2e/src/test/kotlin/io/github/danielhp95/caracole/e2e/PhoneScenarioTest.kt; android/app/src/androidTest/kotlin/io/github/danielhp95/caracole/LookupOnDeviceTest.kt
- Done when: CARACOLE_ANDROID_E2E=1 nix develop -c pytest -q -n 0 tests/test_android_e2e.py passes with the new phase: with the computer off, Get it, Fetch now and Fetch them look songs up against the fake sites (one new to both sides keeps its sheet; its card's sheet.txt is served), each lookup within lookup_requests, robots-closed paths never asked, no request to any host but the fake server (counted); a fake 403 on UG cools it on the phone; the next sync gives the computer the phone's cooldown and events (origin = the phone's id) and the phone's index reads, and takes the computer's settings; android/scripts/device-test.sh --sites lookups io.github.danielhp95.caracole.LookupOnDeviceTest passes (the app's lookup through 10.0.2.2 to the fake server); android/scripts/device-test.sh --app passes (EndToEndTest, PinchTest, SyncTabTest and PhoneEndToEndTest, each against its own computer, as the M1-3 integration ran them); nix develop ./android -c gradle -p android assembleDebug assembleDebugAndroidTest passes; the phase reports how many conflicts a song looked up on both sides between syncs shows (UG's volatile ratings; §11 Q2); nix develop ./android -c gradle -p android test passes; nix develop -c pytest -q passes; nix build .#checks.x86_64-linux.package passes

Brief:

> Repo /home/dani/Projects/caracole. Lane lookups-e2e, branch android/lookups-e2e, worktree .claude/worktrees/lookups-e2e. Read docs/superpowers/plans/2026-11-03-android-port-m4-m6.md §7.0 first: its rules bind you. Depends on: lookup-routes, index-push, lookup-scenarios. Phase A while any of lookup-routes, index-push, lookup-scenarios hasn't merged; Phase B once all have (§7.0). Device lane: android/scripts/device-test.sh alone runs your area and classes.
>
> Plan sections: §9 (the M4 check), §3, §5.5 (Caracole.sitesForTests). The fake sites server: tests/helpers/fake_sites.py serves a scenario's answers (tests/fixtures and the helpers' pages) by the URL RoutedTransport carries (GET /fetch?url=…), counts every request, answers 404 for anything unknown and logs it; never a port of 8737. Extend e2e_library with songs only the fake sites know. Add a phase to tests/test_android_e2e.py and PhoneScenarioTest (ScenarioPhone gets RoutedTransport to the fake server) proving the done_when, and LookupOnDeviceTest (the androidTest sets Caracole.sitesForTests to RoutedTransport("http://10.0.2.2:P")). Give device-test.sh's --sites branch the real server (your one edit there). The device's guard allows 10.0.2.2, the emulator's address of the host, and nothing else.
> Commit: test(android): lookups end to end against fake sites, on the JVM and the emulator.

#### theory: The viewer's assets, its corpus inputs, and music theory

- Branch `android/theory` · mixed · M5 · about 2600 lines · depends on skeleton-m5m6 · Phase A may start early · device
- Goal: :viewer reads its assets and data, the shared generator of viewer inputs exists, and viewer.theory answers as theory.py for every chord, key and mode.
- Owns: `android/viewer/src/main/kotlin/io/github/danielhp95/caracole/viewer/ViewerAssets.kt`; `android/viewer/src/main/kotlin/io/github/danielhp95/caracole/viewer/ViewerData.kt`; `android/viewer/src/main/kotlin/io/github/danielhp95/caracole/viewer/theory/**`; `android/viewer/src/test/kotlin/io/github/danielhp95/caracole/viewer/ViewerAssetsTest.kt`; `android/viewer/src/test/kotlin/io/github/danielhp95/caracole/viewer/theory/**`; `android/viewer/src/testFixtures/kotlin/io/github/danielhp95/caracole/viewer/testing/replays/TheoryReplay.kt`; `tests/helpers/viewer_corpus.py`; `tests/test_viewer_corpus.py`; `tests/test_conformance_viewer_theory.py`; `tests/conformance/vectors/viewer/theory*.jsonl`; `tests/conformance/data/caracole/viewer/theory.json`; `AGENTS.md (##### :viewer, its theory bullet)`
- Must not touch: §7.0's common list
- Provides: ViewerAssets, ViewerData; tests/helpers/viewer_corpus.py (seeded sheets: every quality, key and mode, the catalogue's progressions, preambles, tabs, legends, defines, capos, Chinese and kana lyrics, plus tests/fixtures/chordpro and the UG and LaCuerda sheets); viewer.theory.Chord, Key, Theory
- Consumes: the skeleton's :viewer module and copyViewerAssets; core.py (M1, py-sites, py-format)
- Tests: android/viewer/src/test/kotlin/io/github/danielhp95/caracole/viewer/ViewerAssetsTest.kt; android/viewer/src/test/kotlin/io/github/danielhp95/caracole/viewer/theory/TheoryTest.kt; tests/test_conformance_viewer_theory.py
- Done when: nix develop ./android -c gradle -p android test passes; nix develop ./android -c gradle -p android assembleDebug assembleDebugAndroidTest passes; nix develop -c pytest -q -n 0 tests/test_conformance_viewer_theory.py passes (check mode); nix develop -c pytest -q tests/test_corpus_budget.py passes; every record of vectors/viewer/theory.jsonl matches (batched per chord name and key: parse_chord strict and not, map_chord over 7 modes, alternatives, spelling, key_name, parse_key, named_key, bare_key, shapes_key, sounding, capo_hints, estimate_key); Chord and Key are frozen and every list handed out is a copy (a test mutates one); nix develop -c pytest -q passes; nix build .#checks.x86_64-linux.package passes; android/scripts/device-test.sh --area theory passes

Brief:

> Repo /home/dani/Projects/caracole. Lane theory, branch android/theory, worktree .claude/worktrees/theory. Read docs/superpowers/plans/2026-11-03-android-port-m4-m6.md §7.0 first: its rules bind you. Depends on: skeleton-m5m6. Phase A while any of skeleton-m5m6 hasn't merged; Phase B once all have (§7.0). Device lane: android/scripts/device-test.sh alone runs your area and classes.
>
> Plan sections: §1 (the page builder's module), §3 (runtime data, page records), §5.2. M5's pure ports fill slots while M4's lanes wait on producers: start once skeleton-m5m6 merges.
> Do: ViewerAssets.text(name) (strict UTF-8 from caracole/viewer/ on the classpath) and the script lists of each page kind; ViewerData.table(module) reading data/caracole/viewer/<module>.json; tests/helpers/viewer_corpus.py, the seeded inputs every M5 generator reads (document it; deterministic across processes); then theory.py whole: Chord and Key frozen, parse_chord's strip as Py.strip, QUALITIES, _REWRITES, DISPLAY, MODES and SCALES exported to data/caracole/viewer/theory.json by your generator, never retyped.
> Commit: feat(android): the viewer's assets and music theory, as theory.py.

#### sheet-keys: A sheet read, UG markup to ChordPro, and a song's key

- Branch `android/sheet-keys` · mixed · M5 · about 2600 lines · depends on skeleton-m5m6, theory, py-sites, py-format · Phase A may start early · device
- Goal: viewer.sheet parses ChordPro and reads a sheet for its page as sheet.py and page.py's reading functions do; ChordPro converts UG markup as chordpro.py does; MusicKeys gives keys.py's key and source.
- Owns: `android/viewer/src/main/kotlin/io/github/danielhp95/caracole/viewer/sheet/**`; `android/viewer/src/test/kotlin/io/github/danielhp95/caracole/viewer/sheet/**`; `android/viewer/src/testFixtures/kotlin/io/github/danielhp95/caracole/viewer/testing/replays/SheetReplay.kt`; `tests/test_conformance_viewer_sheet.py`; `tests/conformance/vectors/viewer/sheet*.jsonl`; `tests/conformance/vectors/viewer/chordpro*.jsonl`; `tests/conformance/vectors/viewer/musickeys*.jsonl`; `tests/conformance/data/caracole/viewer/sheet.json`
- Must not touch: §7.0's common list
- Provides: viewer.sheet.Sheet, Sheets, SheetView (shown, drawnLines, writtenTexts, places, viewerKey, shapesOf); ChordPro.toChordPro (with render._as_latin); MusicKeys (sheetKey, songKey), SongKey
- Consumes: Theory (theory); PyStr.splitlines, PyUnicode.eastAsianWidth (py-sites, py-format); core.library (versions, files)
- Tests: android/viewer/src/test/kotlin/io/github/danielhp95/caracole/viewer/sheet/SheetsTest.kt; android/viewer/src/test/kotlin/io/github/danielhp95/caracole/viewer/sheet/ChordProTest.kt; android/viewer/src/test/kotlin/io/github/danielhp95/caracole/viewer/sheet/MusicKeysTest.kt; tests/test_conformance_viewer_sheet.py
- Done when: nix develop ./android -c gradle -p android test passes; nix develop ./android -c gradle -p android assembleDebug assembleDebugAndroidTest passes; nix develop -c pytest -q -n 0 tests/test_conformance_viewer_sheet.py passes (check mode); nix develop -c pytest -q tests/test_corpus_budget.py passes; every record of vectors/viewer/sheet.jsonl matches (parse_sheet, preamble_section, split_preamble, written, is_legend, and page.py's _shown, _drawn_lines, _written_texts, _peek, _places, _played, _song_key, viewer_key, shapes_of, _given_shapes); every record of vectors/viewer/chordpro.jsonl matches (to_chordpro then _as_latin over the UG and LaCuerda fixtures and the generated sheets, byte for byte; display_columns with east_asian_width and TAB_STOP 8); every record of vectors/viewer/musickeys.jsonl matches (parse_key, key_in_text, estimate_key's correlation summed in Python's order, sheet_key, sheet_keys, song_key over fixture libraries, sheet_capo); nix develop -c pytest -q passes; nix build .#checks.x86_64-linux.package passes; android/scripts/device-test.sh --area sheet passes

Brief:

> Repo /home/dani/Projects/caracole. Lane sheet-keys, branch android/sheet-keys, worktree .claude/worktrees/sheet-keys. Read docs/superpowers/plans/2026-11-03-android-port-m4-m6.md §7.0 first: its rules bind you. Depends on: skeleton-m5m6, theory, py-sites, py-format. Phase A while any of skeleton-m5m6, theory, py-sites, py-format hasn't merged; Phase B once all have (§7.0). Device lane: android/scripts/device-test.sh alone runs your area and classes.
>
> Plan sections: §5.2 (viewer.sheet), §3. Phase A while theory hasn't merged; Phase B: vectors pass.
> Port viewer/sheet.py, the reading functions of viewer/page.py that hold no HTML (they sit here, below the page, which breaks Python's page↔version and page↔harpfit cycles), chordpro.py with render._as_latin and ug/page.decode_twice, and keys.py (song_key over the phone's files and versions). splitlines, strip and split are Python's (core.py), never Kotlin's trim or lines; lengths and indexes in code points.
> Commit: feat(android): a sheet read, ChordPro and a song's key, as the viewer reads them.

#### shapes-harp-winds: Voicings, instruments, the harmonica and the winds

- Branch `android/shapes-harp-winds` · mixed · M5 · about 2400 lines · depends on skeleton-m5m6, theory · Phase A may start early · device
- Goal: viewer.shapes, viewer.harp and viewer.winds give voicings.py's, instruments.py's, harp.py's and winds.py's answers and tables for every key, mode and chord.
- Owns: `android/viewer/src/main/kotlin/io/github/danielhp95/caracole/viewer/shapes/**`; `android/viewer/src/main/kotlin/io/github/danielhp95/caracole/viewer/harp/**`; `android/viewer/src/main/kotlin/io/github/danielhp95/caracole/viewer/winds/**`; `android/viewer/src/test/kotlin/io/github/danielhp95/caracole/viewer/shapes/**`; `android/viewer/src/test/kotlin/io/github/danielhp95/caracole/viewer/harp/**`; `android/viewer/src/test/kotlin/io/github/danielhp95/caracole/viewer/winds/**`; `android/viewer/src/testFixtures/kotlin/io/github/danielhp95/caracole/viewer/testing/replays/ShapesReplay.kt`; `tests/test_conformance_viewer_shapes.py`; `tests/conformance/vectors/viewer/voicings*.jsonl`; `tests/conformance/vectors/viewer/instruments*.jsonl`; `tests/conformance/vectors/viewer/harp_*.jsonl`; `tests/conformance/vectors/viewer/winds*.jsonl`; `tests/conformance/data/caracole/viewer/instruments.json`; `tests/conformance/data/caracole/viewer/harp.json`; `tests/conformance/data/caracole/viewer/winds.json`
- Must not touch: §7.0's common list
- Provides: viewer.shapes.Voicings, Instruments (INSTRUMENTS, chordShapes, pageVoicings, pianoPositions); viewer.harp.Harp (tables, choices, holeNote, holeTables, layouts); viewer.winds.Winds
- Consumes: Theory (theory); voicings.json and voicings-ukulele.json (copied byte for byte)
- Tests: android/viewer/src/test/kotlin/io/github/danielhp95/caracole/viewer/shapes/VoicingsTest.kt; android/viewer/src/test/kotlin/io/github/danielhp95/caracole/viewer/harp/HarpTest.kt; android/viewer/src/test/kotlin/io/github/danielhp95/caracole/viewer/winds/WindsTest.kt; tests/test_conformance_viewer_shapes.py
- Done when: nix develop ./android -c gradle -p android test passes; nix develop ./android -c gradle -p android assembleDebug assembleDebugAndroidTest passes; nix develop -c pytest -q -n 0 tests/test_conformance_viewer_shapes.py passes (check mode); nix develop -c pytest -q tests/test_corpus_budget.py passes; every record of vectors/viewer/{voicings,instruments,harp_,winds}*.jsonl matches (keys sorted in code-point order, harp's ranking tuples sorted stably, CHORD_FIT and TONIC_WEIGHT floats exact); nix develop -c pytest -q passes; nix build .#checks.x86_64-linux.package passes; android/scripts/device-test.sh --area shapes passes

Brief:

> Repo /home/dani/Projects/caracole. Lane shapes-harp-winds, branch android/shapes-harp-winds, worktree .claude/worktrees/shapes-harp-winds. Read docs/superpowers/plans/2026-11-03-android-port-m4-m6.md §7.0 first: its rules bind you. Depends on: skeleton-m5m6, theory. Phase A while any of skeleton-m5m6, theory hasn't merged; Phase B once all have (§7.0). Device lane: android/scripts/device-test.sh alone runs your area and classes.
>
> Plan sections: §5.2, §3. Phase A while theory hasn't merged.
> Port viewer/voicings.py (voicing_keys, _nearest the first of the largest, parse_fingering, chord_legend, parse_define, sheet_shapes, shape_key, frets_from_nut, page_voicings), viewer/instruments.py (INSTRUMENTS exported as data, entries, easy_keys, piano_positions and stacked, ukulele_shapes, chord_shapes, page_voicings), viewer/harp.py (layout, positions, play/entry, choices, candidates and ranking, header_line, tables, ring, holes, key_scales, outside, chord_steps, layouts, hole_note, hole_tables, position_text) and viewer/winds.py (fingering charts as data, fingerings, fit, scale_notes, chord_steps, chord_notes, solfege, fingering_data, tables).
> Commit: feat(android): voicings, instruments, the harmonica and the winds, as the viewer draws them.

#### chinese: Pinyin with tones, Traditional and Simplified through OpenCC

- Branch `android/chinese` · mixed · M5 · about 2300 lines · depends on skeleton-m5m6, theory · Phase A may start early · device
- Goal: The viewer's pinyin readings and hanzi.py's conversions (OpenCC's (the dev shell's version, recorded in the data's header) t2s, tw2s and s2tw without tofu-risk dictionaries) are Python's, character for character.
- Owns: `android/core/src/main/kotlin/io/github/danielhp95/caracole/core/pinyin/Pinyin.kt`; `tests/test_conformance_pinyin.py`; `tests/conformance/data/caracole/pinyin/**`; `tests/conformance/vectors/pinyin/**`; `android/viewer/src/main/kotlin/io/github/danielhp95/caracole/viewer/chinese/**`; `android/viewer/src/test/kotlin/io/github/danielhp95/caracole/viewer/chinese/**`; `android/viewer/src/testFixtures/kotlin/io/github/danielhp95/caracole/viewer/testing/replays/ChineseReplay.kt`; `tests/test_conformance_viewer_chinese.py`; `tests/conformance/data/caracole/hanzi/**`; `tests/conformance/vectors/viewer/opencc*.jsonl`; `tests/conformance/vectors/viewer/hanzi*.jsonl`; `tests/conformance/vectors/viewer/pinyin_page*.jsonl`
- Must not touch: §7.0's common list
- Provides: Pinyin.lazyPinyin(style = TONE | NORMAL, errors = DEFAULT | EMPTY_EACH); viewer.chinese.OpenCC, Hanzi, ViewerPinyin
- Consumes: core.keys.Normalize.simplified (M1); ViewerData (theory)
- Tests: android/viewer/src/test/kotlin/io/github/danielhp95/caracole/viewer/chinese/OpenCCTest.kt; android/viewer/src/test/kotlin/io/github/danielhp95/caracole/viewer/chinese/HanziTest.kt; android/viewer/src/test/kotlin/io/github/danielhp95/caracole/viewer/chinese/ViewerPinyinTest.kt; tests/test_conformance_viewer_chinese.py
- Done when: nix develop ./android -c gradle -p android test passes; nix develop ./android -c gradle -p android assembleDebug assembleDebugAndroidTest passes; nix develop -c pytest -q -n 0 tests/test_conformance_pinyin.py tests/test_conformance_viewer_chinese.py passes (check mode); nix develop -c pytest -q tests/test_corpus_budget.py passes; the pinyin data is regenerated as Style.TONE; Style.NORMAL is derived in Kotlin as pypinyin's to_normal; every M1 pinyin vector still passes, and search's vectors with them; every record of vectors/viewer/opencc.jsonl matches (every dictionary key per config, batched, and seeded mixes), and hanzi.jsonl and pinyin_page.jsonl (scripts, names, written_in_traditional, readings with errors giving '' per character, the 著 rule, kana sheets with none); the 11 dictionaries are data/caracole/hanzi/*.txt, dumped by the generator through the opencc package's own clib/bin/opencc_dict (found from opencc.__file__); nix develop -c pytest -q passes; nix build .#checks.x86_64-linux.package passes; android/scripts/device-test.sh --area chinese,pinyin passes

Brief:

> Repo /home/dani/Projects/caracole. Lane chinese, branch android/chinese, worktree .claude/worktrees/chinese. Read docs/superpowers/plans/2026-11-03-android-port-m4-m6.md §7.0 first: its rules bind you. Depends on: skeleton-m5m6, theory. Phase A while any of skeleton-m5m6, theory hasn't merged; Phase B once all have (§7.0). Device lane: android/scripts/device-test.sh alone runs your area and classes.
>
> Plan sections: §1 (Pinyin with tones, OpenCC), §5.2 (viewer.chinese), §3. Phase A while theory hasn't merged.
> Pinyin: regenerate data/caracole/pinyin as Style.TONE and derive NORMAL (tones dropped, ü as v, heteronyms deduplicated after) in Pinyin.kt, so one copy ships and M1's vectors guard the derivation; add the errors mode that gives '' per character. OpenCC: port its algorithm as the dev shell's OpenCC (opencc.__version__: say which in the data's header) runs t2s, tw2s and s2tw with include_tofu_risk_dictionaries=False: the normalization dictionary, mmseg's maximum-match segmentation where the config has one (the configs are opencc/clib/share/opencc/*.json; tw2s and s2tw have mmseg; read t2s's default from the configs and headers), the conversion chain with longest-prefix matches through group dictionaries by the short_circuit and union policies (DictGroup.hpp), TSCharactersExt left out. Then viewer/pinyin.py and viewer/hanzi.py (scripts, names, written_in_traditional, the converter, _converted keeping a text's length and converting Han characters alone; chordpro() is for PDFs: leave it). Lengths in code points.
> Commit: feat(android): pinyin with tones and OpenCC's Traditional and Simplified on the phone.

#### harmony: Harmony: numerals, relations, tones and scales

- Branch `android/harmony` · mixed · M5 · about 1700 lines · depends on skeleton-m5m6, theory · Phase A may start early · device
- Goal: viewer.harmony gives harmony.py's numerals, relations, families, explanations, glossary, chord tones and scales for every chord, key and next chord.
- Owns: `android/viewer/src/main/kotlin/io/github/danielhp95/caracole/viewer/harmony/** (in turn: harmony first)`; `android/viewer/src/test/kotlin/io/github/danielhp95/caracole/viewer/harmony/HarmonyTest.kt`; `android/viewer/src/testFixtures/kotlin/io/github/danielhp95/caracole/viewer/testing/replays/HarmonyReplay.kt (in turn)`; `tests/test_conformance_viewer_harmony.py (in turn)`; `tests/conformance/vectors/viewer/harmony_chords*.jsonl`; `tests/conformance/data/caracole/viewer/harmony.json (in turn)`
- Must not touch: §7.0's common list
- Provides: viewer.harmony.Harmony (numeral, relation, family, explain, glossary, chordTones, soloScale, keyScale, pentatonic)
- Consumes: Theory (theory); Voicings.TUNING (skeleton-m5m6's constant)
- Tests: android/viewer/src/test/kotlin/io/github/danielhp95/caracole/viewer/harmony/HarmonyTest.kt; tests/test_conformance_viewer_harmony.py
- Done when: nix develop ./android -c gradle -p android test passes; nix develop ./android -c gradle -p android assembleDebug assembleDebugAndroidTest passes; nix develop -c pytest -q -n 0 tests/test_conformance_viewer_harmony.py passes (check mode); nix develop -c pytest -q tests/test_corpus_budget.py passes; every record of vectors/viewer/harmony_chords.jsonl matches (chord, key and next chord batched per chord: numeral, relation, family, explain and its tooltip lines, glossary, chord_tones, solo_scale, key_scale, pentatonic, _goes_to); android/scripts/device-test.sh --area harmony passes; nix develop -c pytest -q passes; nix build .#checks.x86_64-linux.package passes

Brief:

> Repo /home/dani/Projects/caracole. Lane harmony, branch android/harmony, worktree .claude/worktrees/harmony. Read docs/superpowers/plans/2026-11-03-android-port-m4-m6.md §7.0 first: its rules bind you. Depends on: skeleton-m5m6, theory. Phase A while any of skeleton-m5m6, theory hasn't merged; Phase B once all have (§7.0). Group: harmony → harmony-progressions, in turn; merge main in first. Device lane: android/scripts/device-test.sh alone runs your area and classes.
>
> Plan sections: §5.2, §3. Lane harmony-progressions follows you on android/harmony. harmony.py imports theory alone (a sheet's places are an argument; harmony_tables' TUNING is skeleton-m5m6's constant), so you need nothing but theory.
> Port viewer/harmony.py's chord half: numeral, relation, family, explain and its tooltip lines, glossary, chord_tones, solo_scale, key_scale, pentatonic, _goes_to. Its docstring's two-way readings are rules: B♭ in C borrowed from C minor, D in C V/V only going to G, C7 in C V7/IV only going to an F that is no dominant seventh. Its words and tables exported to data/caracole/viewer/harmony.json, never retyped.
> Commit: feat(android): harmony's numerals, relations and scales, as harmony.py.

#### harmony-progressions: Progressions and harmony's tables

- Branch `android/harmony` · mixed · M5 · about 1500 lines · depends on harmony · device
- Goal: viewer.harmony names a sheet's progressions as harmony.py does, and HarmonyTables gives harmony_tables.tables' JSON in Python's key order.
- Owns: `android/viewer/src/main/kotlin/io/github/danielhp95/caracole/viewer/harmony/** (after harmony)`; `android/viewer/src/test/kotlin/io/github/danielhp95/caracole/viewer/harmony/ProgressionsTest.kt`; `android/viewer/src/test/kotlin/io/github/danielhp95/caracole/viewer/harmony/HarmonyTablesTest.kt`; `android/viewer/src/testFixtures/kotlin/io/github/danielhp95/caracole/viewer/testing/replays/HarmonyReplay.kt (after harmony)`; `tests/test_conformance_viewer_harmony.py (after harmony)`; `tests/conformance/vectors/viewer/harmony_progressions*.jsonl`; `tests/conformance/vectors/viewer/harmony_tables*.jsonl`; `tests/conformance/data/caracole/viewer/harmony.json (after harmony)`
- Must not touch: §7.0's common list
- Provides: Harmony.progressions, progressionKey, nameOf, readTyped, catalogue; HarmonyTables.tables
- Consumes: harmony's chord half
- Tests: android/viewer/src/test/kotlin/io/github/danielhp95/caracole/viewer/harmony/ProgressionsTest.kt; android/viewer/src/test/kotlin/io/github/danielhp95/caracole/viewer/harmony/HarmonyTablesTest.kt; tests/test_conformance_viewer_harmony.py
- Done when: nix develop ./android -c gradle -p android test passes; nix develop ./android -c gradle -p android assembleDebug assembleDebugAndroidTest passes; nix develop -c pytest -q -n 0 tests/test_conformance_viewer_harmony.py passes (check mode); nix develop -c pytest -q tests/test_corpus_budget.py passes; every record of vectors/viewer/harmony_progressions.jsonl matches (progressions with CATALOGUE and _LOOPS from data, _fold, _passes, _contained, _ending, progression_key, name_of, read_typed); every record of vectors/viewer/harmony_tables.jsonl matches (tables for about 40 generated sheets, each member's digest, a few whole; Counter.most_common's ties in insertion order); android/scripts/device-test.sh --area harmony passes; nix develop -c pytest -q passes; nix build .#checks.x86_64-linux.package passes

Brief:

> Repo /home/dani/Projects/caracole. Lane harmony-progressions, branch android/harmony, worktree .claude/worktrees/harmony. Read docs/superpowers/plans/2026-11-03-android-port-m4-m6.md §7.0 first: its rules bind you. Depends on: harmony. Starts once every producer has merged. Group: harmony → harmony-progressions, in turn; merge main in first. Device lane: android/scripts/device-test.sh alone runs your area and classes.
>
> Plan sections: §5.2, §3 (page records' digests). Follows harmony on android/harmony.
> Port harmony.py's progressions (CATALOGUE and _LOOPS exported as data; _fold, _passes, _contained, _ending, progression_key, name_of, read_typed) and viewer/harmony_tables.py (Counter.most_common's ties in insertion order, text_of's shapes, the order of tones, words and scales). Every JsonObject is built in Python's insertion order; a reassigned key keeps its place; floats through PyJson.float.
> Commit: feat(android): progressions and harmony's tables, as harmony.py.

#### version-progressions: Versions of a sheet, and progressions

- Branch `android/version-progressions` · mixed · M5 · about 2500 lines · depends on skeleton-m5m6, theory, sheet-keys, harmony-progressions, shapes-harp-winds · Phase A may start early · device
- Goal: viewer.version gives version.py's queries, labels, settings and own versions, and viewer.progressions records and searches progressions as progressions.py does, so /api/search's progression answers on the phone.
- Owns: `android/viewer/src/main/kotlin/io/github/danielhp95/caracole/viewer/version/**`; `android/viewer/src/main/kotlin/io/github/danielhp95/caracole/viewer/progressions/**`; `android/viewer/src/test/kotlin/io/github/danielhp95/caracole/viewer/version/**`; `android/viewer/src/test/kotlin/io/github/danielhp95/caracole/viewer/progressions/**`; `android/viewer/src/testFixtures/kotlin/io/github/danielhp95/caracole/viewer/testing/replays/VersionReplay.kt`; `tests/test_conformance_viewer_version.py`; `tests/conformance/vectors/viewer/version*.jsonl`; `tests/conformance/vectors/viewer/progressions*.jsonl`
- Must not touch: §7.0's common list
- Provides: viewer.version.Version, Setting, KeyVersion, Versions (fromQuery, query, keyVersion, inKey, entry, inSetting, settingProblem, playedKey, label, ownVersion, forInstrument); viewer.progressions.Progressions; the progression records /api/search reads (library-cards wires Found.kt)
- Consumes: Theory, SheetView, Harmony, Instruments
- Tests: android/viewer/src/test/kotlin/io/github/danielhp95/caracole/viewer/version/VersionsTest.kt; android/viewer/src/test/kotlin/io/github/danielhp95/caracole/viewer/progressions/ProgressionsTest.kt; tests/test_conformance_viewer_version.py
- Done when: nix develop ./android -c gradle -p android test passes; nix develop ./android -c gradle -p android assembleDebug assembleDebugAndroidTest passes; nix develop -c pytest -q -n 0 tests/test_conformance_viewer_version.py passes (check mode); nix develop -c pytest -q tests/test_corpus_budget.py passes; every record of vectors/viewer/version.jsonl matches (version_from_query and version_query with _round as floor(x+0.5), instrument_of, played_on, for_instrument, played_key, version_label, played_label, setting_problem, in_setting, key_version, in_key, version_entry, own_version); every record of vectors/viewer/progressions.jsonl matches (sheet_progressions, record's kv text, library_progressions, catalogue, label, key_words, read_progression, songs_with); nix develop -c pytest -q passes; nix build .#checks.x86_64-linux.package passes; android/scripts/device-test.sh --area version passes

Brief:

> Repo /home/dani/Projects/caracole. Lane version-progressions, branch android/version-progressions, worktree .claude/worktrees/version-progressions. Read docs/superpowers/plans/2026-11-03-android-port-m4-m6.md §7.0 first: its rules bind you. Depends on: skeleton-m5m6, theory, sheet-keys, harmony-progressions, shapes-harp-winds. Phase A while any of skeleton-m5m6, theory, sheet-keys, harmony-progressions, shapes-harp-winds hasn't merged; Phase B once all have (§7.0). Device lane: android/scripts/device-test.sh alone runs your area and classes.
>
> Plan sections: §5.2, §3. Phase A while a producer hasn't merged.
> Port viewer/version.py's page side (apply_version, which rewrites a .cho for a PDF, can wait: say so if you leave it) and progressions.py (kv render:progressions:<id> as json.dumps kv text). version_entry writes overrides' [version], which is in a sync unit: byte for byte. Found.kt's progression, which reads the records, is library-cards' to wire.
> Commit: feat(android): a sheet's versions and progressions, as the viewer and search read them.

#### harptab-read: A harmonica tab read: notations, tokenizers, readings

- Branch `android/harptab` · mixed · M5 · about 2000 lines · depends on skeleton-m5m6, shapes-harp-winds, theory · Phase A may start early · device
- Goal: viewer.harptab reads a tab under each notation and weighs the readings as harptab.py does, Q for Q.
- Owns: `android/viewer/src/main/kotlin/io/github/danielhp95/caracole/viewer/harptab/**`; `android/viewer/src/test/kotlin/io/github/danielhp95/caracole/viewer/harptab/**`; `android/viewer/src/testFixtures/kotlin/io/github/danielhp95/caracole/viewer/testing/replays/HarptabReplay.kt`; `tests/test_conformance_viewer_harptab.py`; `tests/conformance/vectors/viewer/harptab*.jsonl`; `tests/conformance/data/caracole/viewer/harptab.json`
- Must not touch: §7.0's common list
- Provides: viewer.harptab Notation, Symbol, PRESETS, scan, Reading, readings, pinned, checkSpec, specOf
- Consumes: Harp.holeNote (shapes-harp-winds); PyRegex, PyRe (M1)
- Tests: android/viewer/src/test/kotlin/io/github/danielhp95/caracole/viewer/harptab/ReadingTest.kt; tests/test_conformance_viewer_harptab.py
- Done when: nix develop ./android -c gradle -p android test passes; nix develop ./android -c gradle -p android assembleDebug assembleDebugAndroidTest passes; nix develop -c pytest -q -n 0 tests/test_conformance_viewer_harptab.py passes (check mode); nix develop -c pytest -q tests/test_corpus_budget.py passes; every reading record of vectors/viewer/harptab_read.jsonl matches over tests/fixtures/harptabs/tab_*.html (their <pre> bodies), legends/ and spellings/ and generated tabs in every notation (tokenizers compiled at runtime through PyRegex: _alt sorted by (-len, text) in code-point order, re.escape's rules, lookbehinds, re.I; Q = P × T, MARGIN, TAB_Q, LEGEND_WEIGHT; pinned and check_spec's refusals; spec_of); nix develop -c pytest -q passes; nix build .#checks.x86_64-linux.package passes; android/scripts/device-test.sh --area harptab passes

Brief:

> Repo /home/dani/Projects/caracole. Lane harptab-read, branch android/harptab, worktree .claude/worktrees/harptab. Read docs/superpowers/plans/2026-11-03-android-port-m4-m6.md §7.0 first: its rules bind you. Depends on: skeleton-m5m6, shapes-harp-winds, theory. Phase A while any of skeleton-m5m6, shapes-harp-winds, theory hasn't merged; Phase B once all have (§7.0). Group: harptab-read → harptab-layout, in turn; merge main in first. Device lane: android/scripts/device-test.sh alone runs your area and classes.
>
> Plan sections: §5.2 (viewer.harptab), §3. The hardest port of M5 (harptab.py is about 1,180 lines of code); lane harptab-layout follows you on this branch. Phase A while a producer hasn't merged.
> Port harptab.py's notation and reading half: Notation, Symbol and PRESETS as data; the tokenizer compiled from a notation (scan(notation=)); scan's passes; legend and _LEXICON; the candidates; _weighed; read; pinned; check_spec; readings; spec_of; said. spec_of writes overrides' [harmonica], which is in a sync unit. Declare the types harptab-layout builds on (Scan, Reading, Row) and say their seam in your report.
> Commit: feat(android): a harmonica tab read under each notation, as harptab.py.

#### harptab-layout: A harmonica tab laid out: rows, words, syllables

- Branch `android/harptab` · mixed · M5 · about 1600 lines · depends on skeleton-m5m6, harptab-read · Phase A may start early · device
- Goal: viewer.harptab lays a read tab out in rows with its words and syllables as harptab.py does, so HarpTabs.parse gives Python's Tab.
- Owns: `android/viewer/src/main/kotlin/io/github/danielhp95/caracole/viewer/harptab/** (in turn after harptab-read)`; `android/viewer/src/test/kotlin/io/github/danielhp95/caracole/viewer/harptab/**`; `tests/conformance/vectors/viewer/harptab_layout*.jsonl`
- Must not touch: §7.0's common list
- Provides: viewer.harptab.HarpTabs.parse, Tab
- Consumes: harptab-read's Scan, Reading, Row
- Tests: android/viewer/src/test/kotlin/io/github/danielhp95/caracole/viewer/harptab/LayoutTest.kt; tests/test_conformance_viewer_harptab.py
- Done when: nix develop ./android -c gradle -p android test passes; nix develop ./android -c gradle -p android assembleDebug assembleDebugAndroidTest passes; nix develop -c pytest -q -n 0 tests/test_conformance_viewer_harptab.py passes (check mode); nix develop -c pytest -q tests/test_corpus_budget.py passes; every record of vectors/viewer/harptab_layout.jsonl matches over tests/fixtures/harptabs/layout and the tabs (_lay_out, _above, _is_label(beside_row=), Scan.prose and explained, Row.trusted, Tab.readable, align, _cuts with math.comb and MAX_CUTS, syllable_starts, named_key, DOTS, STAR_BENDS, the harp chip); nix develop -c pytest -q passes; nix build .#checks.x86_64-linux.package passes; android/scripts/device-test.sh --area harptab passes

Brief:

> Repo /home/dani/Projects/caracole. Lane harptab-layout, branch android/harptab, worktree .claude/worktrees/harptab. Read docs/superpowers/plans/2026-11-03-android-port-m4-m6.md §7.0 first: its rules bind you. Depends on: skeleton-m5m6, harptab-read. Phase A while any of skeleton-m5m6, harptab-read hasn't merged; Phase B once all have (§7.0). Group: harptab-read → harptab-layout, in turn; merge main in first. Device lane: android/scripts/device-test.sh alone runs your area and classes.
>
> Plan sections: §5.2 (viewer.harptab), §3. Follows harptab-read on android/harptab.
> Port harptab.py's layout half: the rows with their words (a row's words the line by it no section's name and no line of holes, or the line above in a tab whose words above fit better), what a notation can't read as a group of kind 'unread', the tabber's words as 'words', a row under ROW_TRUST as written, a tab not readable all as written, align and the cuts, syllable_starts, named_key, and parse(harp=, notation=).
> Commit: feat(android): a harmonica tab laid out, as harptab.py.

#### pages: The sheet page, byte for byte, and pages that print

- Branch `android/pages` · mixed · M5 · about 2300 lines · depends on skeleton-m5m6, harmony-progressions, shapes-harp-winds, chinese, sheet-keys · Phase A may start early · device
- Goal: SheetPage.build writes page.build_viewer's bytes for the same inputs, and the pages print in the light palette with margins on both sides.
- Owns: `android/viewer/src/main/kotlin/io/github/danielhp95/caracole/viewer/pages/SheetPage.kt`; `android/viewer/src/main/kotlin/io/github/danielhp95/caracole/viewer/pages/internal/**`; `android/viewer/src/test/kotlin/io/github/danielhp95/caracole/viewer/pages/SheetPageTest.kt`; `android/viewer/src/testFixtures/kotlin/io/github/danielhp95/caracole/viewer/testing/replays/PagesReplay.kt`; `tests/test_conformance_viewer_pages.py`; `tests/conformance/vectors/viewer/pages*.jsonl`; `tests/conformance/vectors/viewer/page_whole*`; `tests/conformance/data/caracole/viewer/page.json`; `src/caracole/viewer/viewer.css (print rules only)`; `src/caracole/viewer/book.css (print rules only)`; `src/caracole/viewer/harptab.css (print rules only)`; `tests/test_viewer_print.py`; `AGENTS.md (##### :viewer, its pages bullet)`
- Must not touch: §7.0's common list
- Provides: viewer.pages.SheetPage (build, viewerCsp, the page frame book.py reuses), ViewerInputs; the pages' HTML constants as data/caracole/viewer/page.json
- Consumes: every viewer package above; core.web.Inline (moved by the skeleton); page_icon's data (M2)
- Tests: android/viewer/src/test/kotlin/io/github/danielhp95/caracole/viewer/pages/SheetPageTest.kt; tests/test_conformance_viewer_pages.py; tests/test_viewer_print.py
- Done when: nix develop ./android -c gradle -p android test passes; nix develop ./android -c gradle -p android assembleDebug assembleDebugAndroidTest passes; nix develop -c pytest -q -n 0 tests/test_conformance_viewer_pages.py passes (check mode); nix develop -c pytest -q tests/test_corpus_budget.py passes; every record of vectors/viewer/pages.jsonl matches: the page's sha256 and size, its body's, each data member's digest and names' (§3's page records), over the generated sheets with every option (versions, guitar, harmonica, video, start, pdf links, Chinese, kana), and page_whole's small page byte for byte; the print rules first, test first (tests/test_viewer_print.py in Chromium's print emulation): the light palette in print whatever the scheme, @page margins; then the vectors written once; nix develop -c pytest -q passes; nix build .#checks.x86_64-linux.package passes; android/scripts/device-test.sh --area pages passes

Brief:

> Repo /home/dani/Projects/caracole. Lane pages, branch android/pages, worktree .claude/worktrees/pages. Read docs/superpowers/plans/2026-11-03-android-port-m4-m6.md §7.0 first: its rules bind you. Depends on: skeleton-m5m6, harmony-progressions, shapes-harp-winds, chinese, sheet-keys. Phase A while any of skeleton-m5m6, harmony-progressions, shapes-harp-winds, chinese, sheet-keys hasn't merged; Phase B once all have (§7.0). Device lane: android/scripts/device-test.sh alone runs your area and classes.
>
> Plan sections: §1 (Print CSS), §3 (page records), §5.2 (viewer.pages). Phase A while a producer hasn't merged: the print CSS and the HTML constants' export, the builders against declared signatures.
> First, on the computer: viewer.css, book.css and harptab.css get the light palette in @media print (the dark palette's variables reset) and @page margins, nothing more (two columns and diagrams in print are §11's question); this moves the computer's page bytes, so do it before writing any page vector. Then port viewer/page.py's builder (build_viewer, _data in Python's key order with the reassigned 'names' in its place, _body, _page with its CSP of sha256_source over each inlined script and style, names_table, zh_attr, artist_line, pdf_line, _footer, _song_html, _line_html, _words, written_script, is_chinese, viewer_csp); book.py's songbook page is lane songbook-entries' (it imports version.py, which page.py doesn't), so expose the page frame (_page, _song_html, names_table) it reuses. The HTML constants (_CONTROLS, _SHEET_CONTROLS, _VERSIONS, _VERSION_LIST, _GUITAR_ROW, _EXPORT_ROW, _EXPORT_ASK, _NOTICE, _CREDIT, the chords-db notice) are exported by your generator from the modules into data/caracole/viewer/page.json, never retyped. build_version is Python's alone: the phone never embeds or compares it.
> Commit: fix(viewer): pages print in the light palette with margins; feat(android): the sheet and songbook pages, byte for byte.

#### harmonica-page: A harmonica tab's page, and the harp it starts on

- Branch `android/harmonica-page` · mixed · M5 · about 1900 lines · depends on skeleton-m5m6, harptab-layout, pages, py-format · Phase A may start early · device
- Goal: HarmonicaPage.build and HarpFit.choose write harptab_page.build_harmonica_viewer's bytes and harpfit.choose's choice for the same inputs.
- Owns: `android/viewer/src/main/kotlin/io/github/danielhp95/caracole/viewer/pages/HarmonicaPage.kt`; `android/viewer/src/main/kotlin/io/github/danielhp95/caracole/viewer/harpfit/**`; `android/viewer/src/test/kotlin/io/github/danielhp95/caracole/viewer/pages/HarmonicaPageTest.kt`; `android/viewer/src/test/kotlin/io/github/danielhp95/caracole/viewer/harpfit/**`; `android/viewer/src/testFixtures/kotlin/io/github/danielhp95/caracole/viewer/testing/replays/HarmonicaPageReplay.kt`; `tests/test_conformance_viewer_harmonica.py`; `tests/conformance/vectors/viewer/harpfit*.jsonl`; `tests/conformance/vectors/viewer/harmonica_pages*.jsonl`; `tests/conformance/data/caracole/viewer/harmonica_page.json`
- Must not touch: §7.0's common list
- Provides: viewer.pages.HarmonicaPage; viewer.harpfit.HarpFit (choose, tabsHarp), Choice
- Consumes: HarpTabs (harptab-layout); the page frame (pages); PySequence.SequenceMatcher, PyFormat (py-format)
- Tests: android/viewer/src/test/kotlin/io/github/danielhp95/caracole/viewer/pages/HarmonicaPageTest.kt; android/viewer/src/test/kotlin/io/github/danielhp95/caracole/viewer/harpfit/HarpFitTest.kt; tests/test_conformance_viewer_harmonica.py
- Done when: nix develop ./android -c gradle -p android test passes; nix develop ./android -c gradle -p android assembleDebug assembleDebugAndroidTest passes; nix develop -c pytest -q -n 0 tests/test_conformance_viewer_harmonica.py passes (check mode); nix develop -c pytest -q tests/test_corpus_budget.py passes; every record of vectors/viewer/harpfit.jsonl matches (pitch, words, _sheet_lines, record_fit with SequenceMatcher and its sort by (-share, harp), choose and Choice.why, tabs_harp); every record of vectors/viewer/harmonica_pages.jsonl matches (page digests; round(q, 2) as Python floats; the header's {share:.0%}, {views/1000:.0f}k, {views/1e6:.1f}M, {rating:.1f}★ and ({q:.2f}) through PyFormat); nix develop -c pytest -q passes; nix build .#checks.x86_64-linux.package passes; android/scripts/device-test.sh --area harmonica_page passes

Brief:

> Repo /home/dani/Projects/caracole. Lane harmonica-page, branch android/harmonica-page, worktree .claude/worktrees/harmonica-page. Read docs/superpowers/plans/2026-11-03-android-port-m4-m6.md §7.0 first: its rules bind you. Depends on: skeleton-m5m6, harptab-layout, pages, py-format. Phase A while any of skeleton-m5m6, harptab-layout, pages, py-format hasn't merged; Phase B once all have (§7.0). Device lane: android/scripts/device-test.sh alone runs your area and classes.
>
> Plan sections: §5.2, §3. Phase A while a producer hasn't merged.
> Port viewer/harpfit.py and viewer/harptab_page.py (build_harmonica_viewer, _data, _overlay_data, _guitar_data, _header, _harp_lines, _read_as, the tab's HTML, the footer; _BAR, _BAR_RAW and _PILL exported as data), and render's _tab_harps for the sheets' harpTabs.
> Commit: feat(android): a harmonica tab's page, as harptab_page.py.

#### phone-render: The phone renders its own pages

- Branch `android/render` · mixed · M5 · about 2200 lines · depends on skeleton-m5m6, pages, harmonica-page, version-progressions, sheet-keys, chinese, lookup, library-writes, jobs-queue · Phase A may start early · device
- Goal: The phone writes and records a song's pages (sheet.html, version-<tab>.html, harmonica-N.html), its .cho and info.json exactly as render.py's page path does with no PDF, for the songs the mirror doesn't serve, and records every song's progressions.
- Owns: `android/viewer/src/main/kotlin/io/github/danielhp95/caracole/viewer/render/** (in turn: render first)`; `android/viewer/src/test/kotlin/io/github/danielhp95/caracole/viewer/render/PhoneRenderTest.kt`; `android/viewer/src/testFixtures/kotlin/io/github/danielhp95/caracole/viewer/testing/replays/RenderReplay.kt (in turn)`; `tests/test_conformance_viewer_render.py (in turn)`; `tests/helpers/phone_render.py`; `tests/conformance/vectors/viewer/render*.jsonl`; `android/README.md (## Pages built on the phone)`
- Must not touch: §7.0's common list
- Provides: viewer.render.PhoneRender (a SongPages; renderStale, afterSync); WrittenPages' records (each page with its sha256, size and the unit digest it was made at); tests/helpers/phone_render.py: render.py's page path with no PDF, the phone's reference
- Consumes: SheetPage, HarmonicaPage (pages, harmonica-page); Versions.ownVersion, Progressions (version-progressions); MusicKeys, ChordPro (sheet-keys); Kept, Versions (library-writes); the lookup's pdf stage (lookup); JobContext.yieldToQueued (jobs-queue); the skeletons' wiring
- Tests: android/viewer/src/test/kotlin/io/github/danielhp95/caracole/viewer/render/PhoneRenderTest.kt; tests/test_conformance_viewer_render.py
- Done when: nix develop ./android -c gradle -p android test passes; nix develop ./android -c gradle -p android assembleDebug assembleDebugAndroidTest passes; nix develop -c pytest -q -n 0 tests/test_conformance_viewer_render.py passes (check mode); nix develop -c pytest -q tests/test_corpus_budget.py passes; every record of vectors/viewer/render.jsonl matches: fixture libraries (helpers/rendered.py, library_songs.py) rendered by tests/helpers/phone_render.py (render.py's page path with PDFs off: no sheet.pdf, so pdf and pdf_traditional None), giving each written name with its sha256 and size, each kv record (render:files:<id> with the unit digest, render:progressions:<id>, keys:own_versions, the phone's script record), and info.json without PDF fields; with_plain_lyrics onto an auto sheet and its version's raw lyrics 'plain'; a version's or a tab's page dropped once it leaves; a lookup's pdf stage renders the song (PAGES_MADE); a take renders the songs the mirror doesn't serve; the render job calls yieldToQueued between songs, so a lookup queued meanwhile runs before the rest; android/scripts/device-test.sh --area render passes; nix develop -c pytest -q passes; nix build .#checks.x86_64-linux.package passes

Brief:

> Repo /home/dani/Projects/caracole. Lane phone-render, branch android/render, worktree .claude/worktrees/render. Read docs/superpowers/plans/2026-11-03-android-port-m4-m6.md §7.0 first: its rules bind you. Depends on: skeleton-m5m6, pages, harmonica-page, version-progressions, sheet-keys, chinese, lookup, library-writes, jobs-queue. Phase A while any of skeleton-m5m6, pages, harmonica-page, version-progressions, sheet-keys, chinese, lookup, library-writes, jobs-queue hasn't merged; Phase B once all have (§7.0). Group: phone-render → written-pages, in turn; merge main in first. Device lane: android/scripts/device-test.sh alone runs your area and classes.
>
> Plan sections: §1 (Which songs the phone renders), §5.2 (viewer.render), §2. Lane written-pages follows you on android/render (serving and forgetting).
> First the reference: tests/helpers/phone_render.py runs render.py's page path for given songs with PDFs off (chordpro absent or patched so no PDF exists: build_viewer then gets pdf=None and pdf_traditional=None), the phone's reference for the corpus, pages-e2e and the integration; what differs from the computer's own pages by design is named in its docstring: the PDF member and link, songbooks' file labels, build_version never embedded.
> Port render.py's page path, no PDF and no chordpro run: with_plain_lyrics and sheet_lyrics first; own_versions_upgraded; per song the kept versions' pages, the .cho (to_chordpro then _as_latin), the human sheet's viewer and an auto sheet beside it (export False, its alt and at cleared), the harmonica tabs' pages with _tab_harps; own_version from the phone's overrides; versions data (sheet_versions.as_data with sheet and pinned); guitar and harmonica lists; video data from the icons the mirror holds; records render:files:<id> (each with the song unit's digest it was made at, Units.digestOf) and render:progressions:<id>; _forget_written with holds; a record of the sheet's script for the cards' hanzi (the phone makes no PDF record); info.json as library.write_info without the PDF's fields. Which songs: those with no mirror page at their unit's digest (the phone's own, changed or looked up there); every song's progressions. The phone's own build stamp (viewer assets and data hashed, plus the app's version) in kv phone:render-build; a change queues the render job (PhoneKinds' render), which yields between songs (JobContext.yieldToQueued, holding no write).
> Commit: feat(android): the phone renders its own pages.

#### written-pages: The phone's written pages served, gated and forgotten

- Branch `android/render` · mixed · M5 · about 1100 lines · depends on phone-render · device
- Goal: LibraryFiles serves the phone's written page while its bytes are the record's and its unit is still at the digest it was made at, else the mirror's gated page, and a take or a removal forgets what it supersedes.
- Owns: `android/viewer/src/main/kotlin/io/github/danielhp95/caracole/viewer/render/** (after phone-render)`; `android/server/src/main/kotlin/io/github/danielhp95/caracole/server/files/LibraryFiles.kt`; `android/server/src/main/kotlin/io/github/danielhp95/caracole/server/files/FileTypes.kt`; `android/server/src/test/kotlin/io/github/danielhp95/caracole/server/files/LibraryFilesTest.kt`; `android/core/src/main/kotlin/io/github/danielhp95/caracole/core/library/internal/Removal.kt (the phone's written pages only)`; `android/core/src/test/kotlin/io/github/danielhp95/caracole/core/library/RemovalWrittenTest.kt`; `AGENTS.md (##### The phone's written pages)`; `android/app/src/androidTest/kotlin/io/github/danielhp95/caracole/PagesServedTest.kt`
- Must not touch: §7.0's common list
- Provides: LibraryFiles serving the phone's written pages (sheet, version, harmonica, songbook) in the viewer's sandbox; PhoneRender.afterSync forgetting pages a take superseded
- Consumes: WrittenPages' records (phone-render); PhoneGate (M3)
- Tests: android/server/src/test/kotlin/io/github/danielhp95/caracole/server/files/LibraryFilesTest.kt; android/core/src/test/kotlin/io/github/danielhp95/caracole/core/library/RemovalWrittenTest.kt; android/app/src/androidTest/kotlin/io/github/danielhp95/caracole/PagesServedTest.kt
- Done when: nix develop ./android -c gradle -p android test passes; nix develop ./android -c gradle -p android assembleDebug assembleDebugAndroidTest passes; LibraryFilesTest: a written page is served only while its bytes are the record's and its song's unit is at the recorded digest, with viewer_csp's sandbox, before the mirror's; a page changed on disk is refused; once a take moves the unit (the computer rendered it again), the mirror's page serves when PhoneGate says SERVE and the phone's is forgotten; the mirror's page serves where the phone wrote none; a songbook's page the same way by kv songbook:<folder>; Removal deletes the phone's written pages by their records (RemovalWrittenTest); android/scripts/device-test.sh io.github.danielhp95.caracole.PagesServedTest passes; android/scripts/device-test.sh --app passes (EndToEndTest, PinchTest, SyncTabTest and PhoneEndToEndTest, each against its own computer, as the M1-3 integration ran them); nix develop -c pytest -q passes; nix build .#checks.x86_64-linux.package passes

Brief:

> Repo /home/dani/Projects/caracole. Lane written-pages, branch android/render, worktree .claude/worktrees/render. Read docs/superpowers/plans/2026-11-03-android-port-m4-m6.md §7.0 first: its rules bind you. Depends on: phone-render. Starts once every producer has merged. Group: phone-render → written-pages, in turn; merge main in first. Device lane: android/scripts/device-test.sh alone runs your area and classes.
>
> Plan sections: §1 (Which songs the phone renders), §5.2 (WrittenPages), §5.3. Follows phone-render on android/render.
> Serving: LibraryFiles gives the phone's written page while its bytes are the record's (files.read_written_page's SHA-256 check) and the song unit is still at the digest the page was made at, with viewer_csp as web/app.py's written_page; otherwise the mirror's page through PhoneGate (SERVE, CHANGED, REMOVED as M3); a songbook's page by kv songbook:<folder> the same way, for songbook-entries. PhoneRender.afterSync (the skeleton calls it after a take) forgets the phone's pages of units the take moved, and renders those the mirror doesn't serve. Removal (M3) deletes by render:files records: make sure it deletes the phone's. Write PagesServedTest (androidTest) for a written page opened in the WebView's sandbox.
> Commit: feat(android): the phone's written pages served while they are current.

#### library-cards: The library page's cards from the phone's own library

- Branch `android/library-cards` · mixed · M5 · about 2400 lines · depends on skeleton-m5m6, phone-render, matcher, ug-pages, rank-coverage, tab-files, version-progressions, chinese, lookup-routes · Phase A may start early · device
- Goal: PhonePageData makes every card as library_page.song_cards makes it from the same library, in place of the mirror's re-identified and minimal cards.
- Owns: `android/server/src/main/kotlin/io/github/danielhp95/caracole/server/page/PhonePageData.kt`; `android/server/src/main/kotlin/io/github/danielhp95/caracole/server/page/internal/cards/**`; `android/server/src/main/kotlin/io/github/danielhp95/caracole/server/page/MirrorPageData.kt`; `android/server/src/main/kotlin/io/github/danielhp95/caracole/server/page/CardText.kt`; `android/server/src/test/kotlin/io/github/danielhp95/caracole/server/page/PhonePageDataTest.kt`; `android/server/src/test/kotlin/io/github/danielhp95/caracole/server/page/MirrorPageDataTest.kt`; `android/server/src/test/kotlin/io/github/danielhp95/caracole/server/page/CardTextTest.kt`; `tests/test_conformance_cards.py`; `tests/conformance/vectors/web/cards_full*.jsonl`; `android/server/src/main/kotlin/io/github/danielhp95/caracole/server/routes/search/Found.kt (progression only, after lookup-routes)`; `android/server/src/test/kotlin/io/github/danielhp95/caracole/server/routes/search/ProgressionTest.kt`; `android/server/src/testFixtures/kotlin/io/github/danielhp95/caracole/server/testing/replays/CardsReplay.kt`
- Must not touch: §7.0's common list
- Provides: server.page.PhonePageData : PageData, SongCards (every card from the phone's library; icons, sites and catalogue still the mirror's); /api/search's progression on the phone
- Consumes: MusicKeys, Progressions, Hanzi; SheetVersions.inLibraryOf, mayKeep (rank-coverage); Matcher.candidatesOf (matcher); MuseScore.songPages (tab-files); WrittenPages (phone-render)
- Tests: android/server/src/test/kotlin/io/github/danielhp95/caracole/server/page/PhonePageDataTest.kt; tests/test_conformance_cards.py; android/server/src/test/kotlin/io/github/danielhp95/caracole/server/routes/search/ProgressionTest.kt
- Done when: nix develop ./android -c gradle -p android test passes; nix develop ./android -c gradle -p android assembleDebug assembleDebugAndroidTest passes; nix develop -c pytest -q -n 0 tests/test_conformance_cards.py passes (check mode); nix develop -c pytest -q tests/test_corpus_budget.py passes; every record of vectors/web/cards_full.jsonl matches: library_page.song_cards over helpers/library_songs.py libraries (key, files, versions with UG's and LaCuerda's, the auto sheet, review choices, song_sites with the checked kv, MuseScore links, buy links' todo.songs_to_buy, hanzi names, progressions); the served page's data from PhonePageData equals Python's for the corpus's library fixture, cards and all; CARACOLE_ANDROID_E2E=1 nix develop -c pytest -q -n 0 tests/test_android_e2e.py passes; nix develop -c pytest -q passes; nix build .#checks.x86_64-linux.package passes; /api/search's progression over a fixture equals Python's; android/scripts/device-test.sh --area cards passes; android/scripts/device-test.sh --app passes (EndToEndTest, PinchTest, SyncTabTest and PhoneEndToEndTest, each against its own computer, as the M1-3 integration ran them)

Brief:

> Repo /home/dani/Projects/caracole. Lane library-cards, branch android/library-cards, worktree .claude/worktrees/library-cards. Read docs/superpowers/plans/2026-11-03-android-port-m4-m6.md §7.0 first: its rules bind you. Depends on: skeleton-m5m6, phone-render, matcher, ug-pages, rank-coverage, tab-files, version-progressions, chinese, lookup-routes. Phase A while any of skeleton-m5m6, phone-render, matcher, ug-pages, rank-coverage, tab-files, version-progressions, chinese, lookup-routes hasn't merged; Phase B once all have (§7.0). Device lane: android/scripts/device-test.sh alone runs your area and classes.
>
> Plan sections: §1 (Which songs the phone renders: cards for every song), §5.3 (server.page). Phase A while a producer hasn't merged.
> Port library_page.song_cards (_song, _files, _in_line_order, _versions_data, LaCuerda's versions and sheet, _auto_sheet, review_choices with search.index_song, song_sites, MuseScore links, todo.songs_to_buy with fetch_due and the index state, hanzi names by the phone's script records, progressions) into PhonePageData in one place, restructuring nothing: the library lines' instrument buttons are being designed and will reshape this data, so keep library_page's shape exactly and regenerate when it changes. Icons, sites and the catalogue stay the mirror's. MirrorPageData keeps only what PhonePageData doesn't make. Never touch rows.js, card.js or library.js. Found.kt's progression (from version-progressions' records) is yours after lookup-routes. Fill CardsReplay.
> Commit: feat(android): the library page's cards from the phone's own library.

#### pages-e2e: M5 end to end: a song looked up on the phone plays as on the computer

- Branch `android/pages-e2e` · mixed · M5 · about 1300 lines · depends on library-cards, written-pages, lookups-e2e · Phase A may start early · device
- Goal: The e2e and the emulator show a song looked up on the phone with pages byte-equal to the computer's for the same inputs, a Chinese sheet with pinyin pinched, and a harmonica tab's page.
- Owns: `tests/helpers/e2e_library.py`; `tests/test_android_e2e.py`; `android/e2e/src/test/kotlin/io/github/danielhp95/caracole/e2e/**`; `android/app/src/androidTest/kotlin/io/github/danielhp95/caracole/PagesOnDeviceTest.kt`; `android/app/src/androidTest/kotlin/io/github/danielhp95/caracole/PinchTest.kt`
- Must not touch: §7.0's common list
- Provides: the e2e's pages phase; PagesOnDeviceTest
- Consumes: every M5 lane; the fake sites (lookups-e2e)
- Tests: tests/test_android_e2e.py; android/e2e/src/test/kotlin/io/github/danielhp95/caracole/e2e/PhoneScenarioTest.kt; android/app/src/androidTest/kotlin/io/github/danielhp95/caracole/PagesOnDeviceTest.kt
- Done when: CARACOLE_ANDROID_E2E=1 nix develop -c pytest -q -n 0 tests/test_android_e2e.py passes with the pages phase: a song looked up on the phone gets sheet.html, its version pages and a harmonica tab's page whose bytes equal Python's build for the same inputs (tests/helpers/phone_render.py builds them from the computer's copy after the sync); a Chinese song with pinyin; /api/search's progression finds it; android/scripts/device-test.sh --sites lookups io.github.danielhp95.caracole.PagesOnDeviceTest io.github.danielhp95.caracole.PinchTest passes (the phone's sheet plays a chord, Pinyin and Traditional switch, a pinch zooms a Chinese sheet with pinyin, the harmonica tab's page draws); android/scripts/device-test.sh --app passes (EndToEndTest, PinchTest, SyncTabTest and PhoneEndToEndTest, each against its own computer, as the M1-3 integration ran them); nix develop ./android -c gradle -p android assembleDebug assembleDebugAndroidTest passes; nix develop ./android -c gradle -p android test passes; nix develop -c pytest -q passes; nix build .#checks.x86_64-linux.package passes

Brief:

> Repo /home/dani/Projects/caracole. Lane pages-e2e, branch android/pages-e2e, worktree .claude/worktrees/pages-e2e. Read docs/superpowers/plans/2026-11-03-android-port-m4-m6.md §7.0 first: its rules bind you. Depends on: library-cards, written-pages, lookups-e2e. Phase A while any of library-cards, written-pages, lookups-e2e hasn't merged; Phase B once all have (§7.0). Device lane: android/scripts/device-test.sh alone runs your area and classes.
>
> Plan sections: §9 (the M5 check). Add to e2e_library a Chinese sheet whose page carries pinyin (none had it in M1-3, so pinching was never tried with pinyin) and a harmonica tab on the fake sites; add the pages phase to the e2e (the phone looks the songs up, renders, syncs; tests/helpers/phone_render.py (phone-render's: render.py's page path with no PDF) builds the same pages from the computer's copy of the phone's units, and the e2e compares bytes) and PagesOnDeviceTest; extend PinchTest to the pinyin sheet.
> Commit: test(android): pages built on the phone end to end.

#### songbook-writers: Songbooks named, made and edited as songbook.py does

- Branch `android/songbooks` · mixed · M6 · about 1500 lines · depends on skeleton-m5m6 · Phase A may start early · device
- Goal: Songbooks makes, adds, removes, moves, renames and deletes songbooks in phone_songbooks with songbook.py's checks and words, so the computer takes each unit.
- Owns: `android/core/src/main/kotlin/io/github/danielhp95/caracole/core/songbooks/**`; `android/core/src/test/kotlin/io/github/danielhp95/caracole/core/songbooks/**`; `android/core/src/main/kotlin/io/github/danielhp95/caracole/core/library/SongbookStore.kt`; `android/core/src/testFixtures/kotlin/io/github/danielhp95/caracole/core/testing/replays/SongbookReplay.kt`; `tests/test_conformance_songbook.py`; `tests/conformance/vectors/songbook/writers*.jsonl`; `android/core/src/testFixtures/kotlin/io/github/danielhp95/caracole/core/testing/replays/SongbookReplay.kt`
- Must not touch: §7.0's common list
- Provides: core.songbooks.Songbooks (checkName, nameKey, folderKey, entryKeys, sameEntry, findEntrySong, all, find, make, add, remove, move, rename, delete), SongbookError, Songbook, SongbookSong
- Consumes: core.keys, SafeName, PyUnicode (M1); SongbookStore (M3)
- Tests: android/core/src/test/kotlin/io/github/danielhp95/caracole/core/songbooks/SongbooksTest.kt; tests/test_conformance_songbook.py
- Done when: nix develop ./android -c gradle -p android test passes; nix develop ./android -c gradle -p android assembleDebug assembleDebugAndroidTest passes; nix develop -c pytest -q -n 0 tests/test_conformance_songbook.py passes (check mode); nix develop -c pytest -q tests/test_corpus_budget.py passes; every record of vectors/songbook/writers.jsonl matches: each operation over a songbooks fixture giving songbook_value after, or its refusal's words (check_name: NFC, no Cc or Cf but space and tab, whitespace collapsed, 80 characters, no leading dot, a letter or digit in its safe name; check_free by name key and folder key; make dedupes by same_entry; move 1-based clamped; rename keeps the place); peer_sync's take of every phone-made songbook unit succeeds in Python (the generator asserts put_songbook reads it); nix develop -c pytest -q passes; nix build .#checks.x86_64-linux.package passes; android/scripts/device-test.sh --area songbook passes

Brief:

> Repo /home/dani/Projects/caracole. Lane songbook-writers, branch android/songbooks, worktree .claude/worktrees/songbooks. Read docs/superpowers/plans/2026-11-03-android-port-m4-m6.md §7.0 first: its rules bind you. Depends on: skeleton-m5m6. Phase A while any of skeleton-m5m6 hasn't merged; Phase B once all have (§7.0). Group: songbook-writers → songbook-entries → songbook-routes, in turn; merge main in first. Device lane: android/scripts/device-test.sh alone runs your area and classes.
>
> Plan sections: §5.1 (core.songbooks). M6 work that needs nothing of M4 or M5: start once skeleton-m5m6 merges. songbook-entries and songbook-routes follow you on android/songbooks.
> SongbookStore.put stores a name unchecked (M3's deviation); the computer's put_songbook runs check_name and check_free and leaves a unit that fails them. Port songbook.py's names (check_name, name_key, _folder_key, check_free), entries (entry_keys at every ' - ' cut, same_entry, find_entry_song by keys only, never by search) and writers (make, add, remove, move, rename, delete; set waits for M5's setting_problem: declare it, songbook-entries fills it), inside Database.write, refusing with songbook.py's words.
> Commit: feat(android): songbooks made and edited on the phone, as songbook.py.

#### songbook-entries: A songbook's entries, settings and page

- Branch `android/songbooks` · mixed · M6 · about 2100 lines · depends on songbook-writers, version-progressions, pages, written-pages · Phase A may start early · device
- Goal: A songbook's entries play as songbook.py plays them, a setting is set as `caracole songbook set` sets it, the Songbooks tab's data is songbook_section's, and the phone writes its own songbook.html as render_songbooks does.
- Owns: `android/core/src/main/kotlin/io/github/danielhp95/caracole/core/songbooks/** (after songbook-writers)`; `android/viewer/src/main/kotlin/io/github/danielhp95/caracole/viewer/pages/SongbookPage.kt`; `android/viewer/src/test/kotlin/io/github/danielhp95/caracole/viewer/pages/SongbookPageTest.kt`; `android/server/src/main/kotlin/io/github/danielhp95/caracole/server/songbooks/SongbookEntries.kt`; `android/server/src/main/kotlin/io/github/danielhp95/caracole/server/songbooks/SongbookPagesImpl.kt`; `android/server/src/main/kotlin/io/github/danielhp95/caracole/server/page/SongbookSection.kt`; `android/server/src/test/kotlin/io/github/danielhp95/caracole/server/songbooks/SongbookEntriesTest.kt`; `android/server/src/test/kotlin/io/github/danielhp95/caracole/server/songbooks/SongbookPagesTest.kt`; `src/caracole/songbook_section.py (the files parameter only)`; `tests/test_songbook_section.py`; `tests/test_conformance_songbook_tab.py (in turn: entries first)`; `tests/conformance/vectors/songbook/entries*.jsonl`; `tests/conformance/vectors/songbook/tab*.jsonl`; `tests/conformance/vectors/viewer/songbook_pages*.jsonl`; `android/server/src/testFixtures/kotlin/io/github/danielhp95/caracole/server/testing/replays/SongbookTabReplay.kt (in turn)`
- Must not touch: §7.0's common list
- Provides: Songbooks.set and SongbookEntries (songbook_entries, songs_to_get, plays_in, with_capo, on_instrument, where_played, songbooks_listing); SongbookPage.build (book.py); SongbookSection.data; SongbookPagesImpl (a SongbookPages: songbook.html written and recorded)
- Consumes: Versions.inSetting, settingProblem, playedKey, ownVersion (version-progressions); SheetPage's frame (pages); WrittenPages, LibraryFiles' songbook serving (written-pages)
- Tests: android/server/src/test/kotlin/io/github/danielhp95/caracole/server/songbooks/SongbookEntriesTest.kt; android/server/src/test/kotlin/io/github/danielhp95/caracole/server/songbooks/SongbookPagesTest.kt; android/viewer/src/test/kotlin/io/github/danielhp95/caracole/viewer/pages/SongbookPageTest.kt; tests/test_conformance_songbook_tab.py
- Done when: nix develop ./android -c gradle -p android test passes; nix develop ./android -c gradle -p android assembleDebug assembleDebugAndroidTest passes; nix develop -c pytest -q -n 0 tests/test_conformance_songbook_tab.py passes (check mode); nix develop -c pytest -q tests/test_corpus_budget.py passes; every record of vectors/songbook/entries.jsonl and tab.jsonl matches (songbook_entries, plays_in, with_capo, on_instrument; songbooks_data with files=[('songbook.html', 'Phone page')]); every record of vectors/viewer/songbook_pages.jsonl matches (page digests, §3); a songbook changed on the phone has the phone's songbook.html, recorded in kv songbook:<folder> as Python's _record, and one gone has its files removed (_remove_gone); android/scripts/device-test.sh --area songbook_tab passes; nix develop -c pytest -q passes; nix build .#checks.x86_64-linux.package passes

Brief:

> Repo /home/dani/Projects/caracole. Lane songbook-entries, branch android/songbooks, worktree .claude/worktrees/songbooks. Read docs/superpowers/plans/2026-11-03-android-port-m4-m6.md §7.0 first: its rules bind you. Depends on: songbook-writers, version-progressions, pages, written-pages. Phase A while any of songbook-writers, version-progressions, pages, written-pages hasn't merged; Phase B once all have (§7.0). Group: songbook-writers → songbook-entries → songbook-routes, in turn; merge main in first. Device lane: android/scripts/device-test.sh alone runs your area and classes.
>
> Plan sections: §5.1 (core.songbooks), §5.2 (SongbookPage), §2. Follows songbook-writers on android/songbooks; songbook-routes follows you.
> Fill Songbooks.set (check_setting through Versions.settingProblem) and port songbook.py's entries and plays (songbook_entries, songs_to_get, _entry_of, _played_in, with_capo, on_instrument, plays_in, where_played, _sheet_of, songbooks_listing); viewer/book.py (BookSong, build_songbook, _contents, _song, _opens_in, _key_and_capo, _pager; book's _CONTROLS exported as data) over pages' frame; songbook_section.songbooks_data from phone_songbooks (Python gains a files parameter, test first: the phone makes 'Phone page' alone, never chordpro's PDF or .cho); render_songbooks' songbook.html with kv songbook:<folder> records as Python's _record and _remove_gone, as SongbookPagesImpl (the seam the lookup's songbooks stage calls).
> Commit: feat(android): a songbook's entries, settings and page on the phone.

#### songbook-routes: The Songbooks tab's forms and jobs

- Branch `android/songbooks` · mixed · M6 · about 1300 lines · depends on songbook-entries, job-views, lookup · device
- Goal: Every /songbook/* form of the Songbooks tab queues a job keyed and worded as web/songbooks.py's, refuses as songbook_routes.py does, and Get the missing songs and Add a song look songs up first.
- Owns: `android/server/src/main/kotlin/io/github/danielhp95/caracole/server/routes/SongbookRoutes.kt`; `android/server/src/main/kotlin/io/github/danielhp95/caracole/server/songbooks/SongbookRunner.kt`; `android/server/src/test/kotlin/io/github/danielhp95/caracole/server/routes/SongbookRoutesTest.kt`; `android/app/src/androidTest/kotlin/io/github/danielhp95/caracole/SongbooksOnDeviceTest.kt`; `tests/test_conformance_songbook_tab.py (after songbook-entries)`; `tests/conformance/vectors/songbook/routes*.jsonl`; `android/server/src/testFixtures/kotlin/io/github/danielhp95/caracole/server/testing/replays/SongbookTabReplay.kt (after songbook-entries)`; `android/README.md (## Songbooks, versions and printing)`; `AGENTS.md (##### Songbooks, versions and printing on the phone, its songbooks bullet)`
- Must not touch: §7.0's common list
- Provides: SongbookRoutes (make, add, add-song, get, remove, move, set, rename, delete); the songbook runner
- Consumes: Songbooks, SongbookEntries, SongbookPagesImpl (songbook-entries); JobViews' songbook lines (job-views); the get runner (lookup)
- Tests: android/server/src/test/kotlin/io/github/danielhp95/caracole/server/routes/SongbookRoutesTest.kt; tests/test_conformance_songbook_tab.py; android/app/src/androidTest/kotlin/io/github/danielhp95/caracole/SongbooksOnDeviceTest.kt
- Done when: nix develop ./android -c gradle -p android test passes; nix develop ./android -c gradle -p android assembleDebug assembleDebugAndroidTest passes; nix develop -c pytest -q -n 0 tests/test_conformance_songbook_tab.py passes (check mode); nix develop -c pytest -q tests/test_corpus_budget.py passes; every record of vectors/songbook/routes.jsonl matches: each /songbook/* route's job keyed 'songbook\x1f...' as web/songbooks._job, its refusals as songbook_routes (a negative id or a mirror-only card: 'isn't in the library any more'), its line Python's; Get the missing songs and Add a song queue lookups first (submit_all, both or neither); the page's songbooks come from SongbookSection; android/scripts/device-test.sh --area songbook_tab io.github.danielhp95.caracole.SongbooksOnDeviceTest passes (make a songbook from the Select bar, set a song's key, open its page); android/scripts/device-test.sh --app passes (EndToEndTest, PinchTest, SyncTabTest and PhoneEndToEndTest, each against its own computer, as the M1-3 integration ran them); nix develop -c pytest -q passes; nix build .#checks.x86_64-linux.package passes

Brief:

> Repo /home/dani/Projects/caracole. Lane songbook-routes, branch android/songbooks, worktree .claude/worktrees/songbooks. Read docs/superpowers/plans/2026-11-03-android-port-m4-m6.md §7.0 first: its rules bind you. Depends on: songbook-entries, job-views, lookup. Starts once every producer has merged. Group: songbook-writers → songbook-entries → songbook-routes, in turn; merge main in first. Device lane: android/scripts/device-test.sh alone runs your area and classes.
>
> Plan sections: §5.4, §2. Follows songbook-entries on android/songbooks.
> SongbookRoutes (skeleton-m5m6's neutral module) answers make, add, add-song, get, remove, move, set, rename and delete, each a job of the songbook runner keyed as web/songbooks._job and refused as songbook_routes; the runner writes through Songbooks, renders the songbook through SongbookPagesImpl and invalidates the search. Get the missing songs queues one lookup a song then the render; Add a song queues lookup_request plus the add (submit_all). JobsRoutes' songbooks source is the skeleton's wiring.
> Commit: feat(android): the Songbooks tab on the phone.

#### versions-harmonica: A sheet's versions and a harmonica tab's readings, chosen on the phone

- Branch `android/versions-harmonica` · mixed · M6 · about 1800 lines · depends on skeleton-m5m6, ug-fetch-artist, lookup, phone-render, harptab-layout, overrides-model, job-views · Phase A may start early · device
- Goal: The /versions page (Make this the one, Keep it, back to caracole's pick) and the /harmonica page (a reading pinned or cleared) work on the phone as versions_routes.py and harmonica_routes.py do.
- Owns: `android/server/src/main/kotlin/io/github/danielhp95/caracole/server/routes/VersionsRoutes.kt`; `android/server/src/main/kotlin/io/github/danielhp95/caracole/server/routes/HarmonicaRoutes.kt`; `android/server/src/main/kotlin/io/github/danielhp95/caracole/server/lookups/HarmonicaRunner.kt`; `android/server/src/main/kotlin/io/github/danielhp95/caracole/server/pages/**`; `android/server/src/test/kotlin/io/github/danielhp95/caracole/server/routes/VersionsRoutesTest.kt`; `android/server/src/test/kotlin/io/github/danielhp95/caracole/server/routes/HarmonicaRoutesTest.kt`; `tests/test_conformance_choices.py`; `tests/conformance/vectors/web/versions_routes*.jsonl`; `tests/conformance/vectors/web/harmonica_routes*.jsonl`; `android/server/src/testFixtures/kotlin/io/github/danielhp95/caracole/server/testing/replays/ChoicesReplay.kt`; `android/app/src/androidTest/kotlin/io/github/danielhp95/caracole/VersionsPageTest.kt`
- Must not touch: §7.0's common list
- Provides: GET /versions, POST /versions/choose, /keep, /clear on the phone; GET /harmonica, POST /harmonica/pin, /clear; the harmonica runner
- Consumes: the versions runner (lookup); UgFetch.keepVersion and VersionsCommands (ug-fetch-sheet, ug-fetch-artist); HarpTabs.readings, specOf, checkSpec (harptab-layout); OverrideWriters.addHarmonica, removePin; PhoneRender (phone-render)
- Tests: android/server/src/test/kotlin/io/github/danielhp95/caracole/server/routes/VersionsRoutesTest.kt; android/server/src/test/kotlin/io/github/danielhp95/caracole/server/routes/HarmonicaRoutesTest.kt; tests/test_conformance_choices.py; android/app/src/androidTest/kotlin/io/github/danielhp95/caracole/VersionsPageTest.kt
- Done when: nix develop ./android -c gradle -p android test passes; nix develop ./android -c gradle -p android assembleDebug assembleDebugAndroidTest passes; nix develop -c pytest -q -n 0 tests/test_conformance_choices.py passes (check mode); nix develop -c pytest -q tests/test_corpus_budget.py passes; every record of vectors/web/versions_routes.jsonl and harmonica_routes.jsonl matches (what each page offers and refuses: 404 for a sheet that isn't the phone's viewer, 400 for a tab that isn't a number, 404 for one not the song's, 409 for what can't be done, an ignored song; the jobs' keys and commands); Keep it keeps version-<tab>.* and its page; Make this the one pins and looks up; back to caracole's pick removes the pins and looks up; a reading pinned writes [harmonica] and renders the tab's page and the sheet's viewers again; CARACOLE_ANDROID_E2E=1 nix develop -c pytest -q -n 0 tests/test_android_e2e.py passes; nix develop -c pytest -q passes; nix build .#checks.x86_64-linux.package passes; android/scripts/device-test.sh --area choices io.github.danielhp95.caracole.VersionsPageTest passes; android/scripts/device-test.sh --app passes (EndToEndTest, PinchTest, SyncTabTest and PhoneEndToEndTest, each against its own computer, as the M1-3 integration ran them)

Brief:

> Repo /home/dani/Projects/caracole. Lane versions-harmonica, branch android/versions-harmonica, worktree .claude/worktrees/versions-harmonica. Read docs/superpowers/plans/2026-11-03-android-port-m4-m6.md §7.0 first: its rules bind you. Depends on: skeleton-m5m6, ug-fetch-artist, lookup, phone-render, harptab-layout, overrides-model, job-views. Phase A while any of skeleton-m5m6, ug-fetch-artist, lookup, phone-render, harptab-layout, overrides-model, job-views hasn't merged; Phase B once all have (§7.0). Device lane: android/scripts/device-test.sh alone runs your area and classes.
>
> Plan sections: §5.4. Phase A while a producer hasn't merged.
> Port web/versions_routes.py and web/harmonica_routes.py: their GET pages (server pages with no script, forms posting with the token; reached from the sandboxed viewer by a plain GET) and their POSTs as jobs (versions --choose, --keep, --clear with --progress under the song's key, joined as jobs.py's _pick; harmonica --as or --clear under jobs.READING, harmonica:<key>:<tab>:<reading>:mine), and harmonica_cmd.py's runner (add_harmonica through OverrideWriters with HarpTabs.checkSpec, then the song rendered again). Hold the decisions in vectors; the pages' words are Python's. VersionsPageTest: a plain GET from the sandboxed viewer reaches /versions with the launch cookie (a top-level navigation), and its form posts with the token. Fill ChoicesReplay.
> Commit: feat(android): a sheet's versions and a tab's readings chosen on the phone.

#### guitar-alphatab: The Guitar Pro page with alphaTab from the APK

- Branch `android/guitar-alphatab` · mixed · M6 · about 1300 lines · depends on skeleton-m5m6 · device
- Goal: A song's Guitar Pro file opens on the phone's own Guitar Pro page, alphaTab loaded from the APK's assets with its integrity, as guitar_routes.py serves it.
- Owns: `android/server/src/main/kotlin/io/github/danielhp95/caracole/server/routes/GuitarRoutes.kt`; `android/server/src/main/kotlin/io/github/danielhp95/caracole/server/guitar/**`; `android/server/src/test/kotlin/io/github/danielhp95/caracole/server/guitar/**`; `android/app/alphatab.gradle.kts`; `android/app/src/main/kotlin/io/github/danielhp95/caracole/AlphaTabAssets.kt`; `android/mirror/src/main/kotlin/io/github/danielhp95/caracole/mirror/Links.kt (/guitar as a page)`; `android/flake.nix (CARACOLE_ALPHATAB_DIR, if the skeleton left it)`; `android/app/src/androidTest/kotlin/io/github/danielhp95/caracole/GuitarPageTest.kt`; `tests/test_conformance_guitar.py`; `tests/conformance/vectors/web/guitar*.jsonl`; `android/README.md (## Guitar Pro)`; `AGENTS.md (##### Guitar Pro on the phone)`; `android/server/src/testFixtures/kotlin/io/github/danielhp95/caracole/server/testing/replays/GuitarReplay.kt`
- Must not touch: §7.0's common list
- Provides: GET /guitar on the phone; alphaTab's bundle in the APK, answered by AlphaTabAssets; ServerControls.guitar true
- Consumes: inbox.guitar_files' query (a port here); the skeleton's hooks: shouldInterceptRequest → AlphaTabAssets.answer; ServerControls.guitar from GuitarRoutes
- Tests: android/server/src/test/kotlin/io/github/danielhp95/caracole/server/guitar/GuitarPageTest.kt; tests/test_conformance_guitar.py; android/app/src/androidTest/kotlin/io/github/danielhp95/caracole/GuitarPageTest.kt
- Done when: nix develop ./android -c gradle -p android test passes; nix develop ./android -c gradle -p android assembleDebug assembleDebugAndroidTest passes; nix develop -c pytest -q -n 0 tests/test_conformance_guitar.py passes (check mode); nix develop -c pytest -q tests/test_corpus_budget.py passes; every record of vectors/web/guitar.jsonl matches: the bundle's name and integrity for the nix files' hashes, build_page's bytes and its policy for a fixture file, the refusals (Power Tab, over 8 MiB, not a recorded guitar-N.*); the APK holds the bundle built byte for byte as alphatab.bundle builds it, with the MPL-2.0, OFL and Apache-2.0 notices; nix develop -c pytest -q passes; nix build .#checks.x86_64-linux.package passes; android/scripts/device-test.sh --area guitar io.github.danielhp95.caracole.GuitarPageTest passes; android/scripts/device-test.sh --app passes (EndToEndTest, PinchTest, SyncTabTest and PhoneEndToEndTest, each against its own computer, as the M1-3 integration ran them)

Brief:

> Repo /home/dani/Projects/caracole. Lane guitar-alphatab, branch android/guitar-alphatab, worktree .claude/worktrees/guitar-alphatab. Read docs/superpowers/plans/2026-11-03-android-port-m4-m6.md §7.0 first: its rules bind you. Depends on: skeleton-m5m6. Starts once every producer has merged. Device lane: android/scripts/device-test.sh alone runs your area and classes.
>
> Plan sections: §1 (alphaTab), §5.4, §5.5. Independent of M4 and M5: start once skeleton-m5m6 merges. 
> The bundle: alphaTab 1.8.4, Bravura.woff2 and sonivox.sf3 from nix/alphatab.nix through CARACOLE_ALPHATAB_DIR (android/flake.nix; the skeleton says whether it wired it), built in app/alphatab.gradle.kts exactly as web/alphatab.bundle builds it (json.dumps of base64 is a quoted ASCII string), into the APK's assets with the three licences. AlphaTabAssets.answer serves /assets/alphatab/<name> in shouldInterceptRequest, since the sandboxed page's script request carries no launch cookie; its WebResourceResponse carries Access-Control-Allow-Origin: * (the page's script tag is crossorigin with integrity, from an opaque origin: without the header the load fails, as guitar_routes answers any origin), the content type (text/javascript; charset=utf-8) and immutable caching. Without CARACOLE_ALPHATAB_DIR, alphatab.gradle.kts fails assembleDebug with a message naming the variable (never an APK without the bundle). :server ports guitar_routes.py and guitar_page.py (build_page, its policy: script-src the bundle and guitar.js by hash, worker-src blob:, the sandbox allow-scripts allow-downloads), guitar.js and guitar.css copied byte for byte (the skeleton added them to the server's assets), and inbox.guitar_files. Links routes /guitar?file= as a page; ServerControls.guitar becomes true.
> Commit: feat(android): the Guitar Pro page with alphaTab on the phone.

#### export-print: Export PDF prints the viewer; Make this my version

- Branch `android/export-print` · mixed · M6 · about 1300 lines · depends on skeleton-m5m6, version-progressions, phone-render, overrides-model, job-views · Phase A may start early · device
- Goal: Export PDF on the phone validates as export_routes.py does, makes the version the song's own with mine=1, and prints the visible viewer through Android's print dialog.
- Owns: `android/server/src/main/kotlin/io/github/danielhp95/caracole/server/routes/ExportRoutes.kt`; `android/server/src/main/kotlin/io/github/danielhp95/caracole/server/lookups/RenderRunner.kt`; `android/server/src/test/kotlin/io/github/danielhp95/caracole/server/routes/ExportRoutesTest.kt`; `android/app/src/main/kotlin/io/github/danielhp95/caracole/Printer.kt`; `android/app/src/androidTest/kotlin/io/github/danielhp95/caracole/PrintTest.kt`; `tests/test_conformance_export.py`; `tests/conformance/vectors/web/export*.jsonl`; `android/server/src/testFixtures/kotlin/io/github/danielhp95/caracole/server/testing/replays/ExportReplay.kt`
- Must not touch: §7.0's common list
- Provides: GET /export.pdf on the phone (JSON {name, label}; mine=1 queues Make this my version); the render runner (render --song --version --mine); Printer.print
- Consumes: Versions.entry, export_version's port, ownVersion (version-progressions); OverrideWriters.addVersion; PhoneRender; the skeleton's hooks: shouldOverrideUrlLoading and DownloadListener route Links.Route.Print to Printer
- Tests: android/server/src/test/kotlin/io/github/danielhp95/caracole/server/routes/ExportRoutesTest.kt; tests/test_conformance_export.py; android/app/src/androidTest/kotlin/io/github/danielhp95/caracole/PrintTest.kt
- Done when: nix develop ./android -c gradle -p android test passes; nix develop ./android -c gradle -p android assembleDebug assembleDebugAndroidTest passes; nix develop -c pytest -q -n 0 tests/test_conformance_export.py passes (check mode); nix develop -c pytest -q tests/test_corpus_budget.py passes; every record of vectors/web/export.jsonl matches (export_viewer's 409s for an auto sheet beside a human one and a version page; export_version; ExportSheet.kept; the download name; the mine=1 job's key); mine=1 stays the one tokenless write: a test that any other write without the token is refused; nix develop -c pytest -q passes; nix build .#checks.x86_64-linux.package passes; android/scripts/device-test.sh --area export io.github.danielhp95.caracole.PrintTest passes; android/scripts/device-test.sh --app passes (EndToEndTest, PinchTest, SyncTabTest and PhoneEndToEndTest, each against its own computer, as the M1-3 integration ran them)

Brief:

> Repo /home/dani/Projects/caracole. Lane export-print, branch android/export-print, worktree .claude/worktrees/export-print. Read docs/superpowers/plans/2026-11-03-android-port-m4-m6.md §7.0 first: its rules bind you. Depends on: skeleton-m5m6, version-progressions, phone-render, overrides-model, job-views. Phase A while any of skeleton-m5m6, version-progressions, phone-render, overrides-model, job-views hasn't merged; Phase B once all have (§7.0). Device lane: android/scripts/device-test.sh alone runs your area and classes.
>
> Plan sections: §1 (PDFs), §5.4, §5.5. Phase A while a producer hasn't merged.
> Server: GET /export.pdf validates as web/export_routes.py's _version (the sheet export_viewer names; export_version over the query and ExportSheet.own) and answers {name, label} (download_names' name) instead of a PDF; with mine=1 it queues render --song --version --mine under export:<key>:<version>:mine, whose runner writes ExportSheet.kept(v) (version_entry) through addVersion and renders the song again. App: Printer.print(activity, web, url) asks the server in-process (as LocalFiles does), then PrintManager.print(name, web.createPrintDocumentAdapter(name), A4) on the visible WebView, on the UI thread; nothing is kept. The system's print UI can't be automated: the device test checks the adapter and the job.
> Commit: feat(android): Export PDF prints the viewer on the phone.

#### review: An uncertain match reviewed on the phone

- Branch `android/review` · mixed · M6 · about 1200 lines · depends on skeleton-m5m6, matcher, library-cards, lookup, overrides-model, job-views · Phase A may start early · device
- Goal: The /review picker and form work on the phone as review_routes.py does: a pick writes [match] (and [alias]), a rejection [reject], then the match is decided again and a fetch follows when asked.
- Owns: `android/server/src/main/kotlin/io/github/danielhp95/caracole/server/routes/ReviewRoutes.kt`; `android/server/src/main/kotlin/io/github/danielhp95/caracole/server/lookups/ReviewRunner.kt`; `android/server/src/test/kotlin/io/github/danielhp95/caracole/server/routes/ReviewRoutesTest.kt`; `tests/test_conformance_review.py`; `tests/conformance/vectors/web/review*.jsonl`; `android/server/src/testFixtures/kotlin/io/github/danielhp95/caracole/server/testing/replays/ReviewReplay.kt`
- Must not touch: §7.0's common list
- Provides: GET /review, POST /review on the phone; the review runner
- Consumes: Matcher.matchAll, candidatesOf (matcher); the cards' candidates (library-cards); OverrideWriters.addMatch, addAlias, addReject; the get runner (lookup)
- Tests: android/server/src/test/kotlin/io/github/danielhp95/caracole/server/routes/ReviewRoutesTest.kt; tests/test_conformance_review.py
- Done when: nix develop ./android -c gradle -p android test passes; nix develop ./android -c gradle -p android assembleDebug assembleDebugAndroidTest passes; nix develop -c pytest -q -n 0 tests/test_conformance_review.py passes (check mode); nix develop -c pytest -q tests/test_corpus_budget.py passes; every record of vectors/web/review.jsonl matches (candidates_of, step_words, writes_alias and NO_ALIAS_STEPS, search_candidates minus [reject], the page's choices, the job's commands, the entries written); after a pick the song's match is decided again (and the artist's songs when an alias was written) and its line says so; nix develop -c pytest -q passes; nix build .#checks.x86_64-linux.package passes; android/scripts/device-test.sh --area review passes; android/scripts/device-test.sh --app passes (EndToEndTest, PinchTest, SyncTabTest and PhoneEndToEndTest, each against its own computer, as the M1-3 integration ran them)

Brief:

> Repo /home/dani/Projects/caracole. Lane review, branch android/review, worktree .claude/worktrees/review. Read docs/superpowers/plans/2026-11-03-android-port-m4-m6.md §7.0 first: its rules bind you. Depends on: skeleton-m5m6, matcher, library-cards, lookup, overrides-model, job-views. Phase A while any of skeleton-m5m6, matcher, library-cards, lookup, overrides-model, job-views hasn't merged; Phase B once all have (§7.0). Device lane: android/scripts/device-test.sh alone runs your area and classes.
>
> Plan sections: §5.4. Phase A while a producer hasn't merged.
> Port web/review_routes.py and pages.Pick (the picker's choices from library_page.review_choices) and commands/library.py's review --song --pick/--none --seen as the review runner: accept writes [match] plus [alias] when writes_alias, reject writes every candidate shown under [reject], then review=False and Matcher.matchAll over the song (and the artist's songs with an alias), then a lookup when asked. The status line's to-do fallback is job-views' todo=None variant.
> Commit: feat(android): an uncertain match reviewed on the phone.

#### inbox-share: Files shared to the app, filed as _inbox/ files them

- Branch `android/inbox-share` · mixed · M6 · about 1500 lines · depends on skeleton-m5m6, library-writes, matcher, lookup, tab-files · Phase A may start early · device
- Goal: A Guitar Pro file or a score shared to caracole is filed for its song as inbox.py files an _inbox/ file, and one no song fits waits and is tried again.
- Owns: `android/core/src/main/kotlin/io/github/danielhp95/caracole/core/inbox/**`; `android/core/src/test/kotlin/io/github/danielhp95/caracole/core/inbox/**`; `android/server/src/main/kotlin/io/github/danielhp95/caracole/server/lookups/InboxRunner.kt`; `android/app/src/main/kotlin/io/github/danielhp95/caracole/ShareActivity.kt`; `android/app/src/androidTest/kotlin/io/github/danielhp95/caracole/ShareTest.kt`; `android/core/src/testFixtures/kotlin/io/github/danielhp95/caracole/core/testing/replays/InboxReplay.kt`; `tests/test_conformance_inbox.py`; `tests/conformance/vectors/inbox/**`; `android/README.md (## Sharing files to caracole)`; `AGENTS.md (##### Files shared to the app)`; `android/core/src/testFixtures/kotlin/io/github/danielhp95/caracole/core/testing/replays/InboxReplay.kt`
- Must not touch: §7.0's common list
- Provides: core.inbox.Inbox (file, parseDownloadName), Filed; the inbox runner; ShareActivity; the staged files' retry after each sync and lookup
- Consumes: Kept, Versions, Numbering, GtpTabs.sniff (library-writes, tab-files); Fuzz.tokenSetRatio (matcher); the skeleton's afterJob hook (JobQueue.onEnd)
- Tests: android/core/src/test/kotlin/io/github/danielhp95/caracole/core/inbox/InboxTest.kt; tests/test_conformance_inbox.py; android/app/src/androidTest/kotlin/io/github/danielhp95/caracole/ShareTest.kt
- Done when: nix develop ./android -c gradle -p android test passes; nix develop ./android -c gradle -p android assembleDebug assembleDebugAndroidTest passes; nix develop -c pytest -q -n 0 tests/test_conformance_inbox.py passes (check mode); nix develop -c pytest -q tests/test_corpus_budget.py passes; every record of vectors/inbox/*.jsonl matches (parse_download_name over tests/test_inbox.py's names; _match over fixture songs with music.Names at cutoff 90; _place's numbering and inbox version; a duplicate by sha; a lost file put back); an unmatched file is staged in stateDir/inbox/, tried again after each sync and lookup, and dropped after 30 days; nix develop -c pytest -q passes; nix build .#checks.x86_64-linux.package passes; android/scripts/device-test.sh --area inbox io.github.danielhp95.caracole.ShareTest passes; android/scripts/device-test.sh --app passes (EndToEndTest, PinchTest, SyncTabTest and PhoneEndToEndTest, each against its own computer, as the M1-3 integration ran them)

Brief:

> Repo /home/dani/Projects/caracole. Lane inbox-share, branch android/inbox-share, worktree .claude/worktrees/inbox-share. Read docs/superpowers/plans/2026-11-03-android-port-m4-m6.md §7.0 first: its rules bind you. Depends on: skeleton-m5m6, library-writes, matcher, lookup, tab-files. Phase A while any of skeleton-m5m6, library-writes, matcher, lookup, tab-files hasn't merged; Phase B once all have (§7.0). Device lane: android/scripts/device-test.sh alone runs your area and classes.
>
> Plan sections: §1 (Files shared to the app), §5.1 (core.inbox), §5.5. Phase A while a producer hasn't merged.
> Port inbox.py's filing of one entry (parse_download_name, _match by identity key then music.Names with fuzz.ratio and token_set_ratio at 90, one song alone without an artist; guitar_number and score_number; _place with its inbox version; keep_file; _copies and _again). MusicXML's header match is left out on the phone: a score is matched by its file name (§11). ShareActivity (the skeleton registered it for stream MIME types only; never text/plain or */*, which the music-app-links design will take) reads EXTRA_STREAM (SEND and SEND_MULTIPLE alone: no VIEW filter, which would offer caracole for every PDF and binary on the phone) and queues the inbox runner (PhoneKinds' inbox kind, worded by §5.3's table; you never edit JobViews), then finishes with a toast of the outcome.
> Commit: feat(android): files shared to caracole are filed as _inbox/ files them.

#### alerts-backups: Alerts as notifications, and backups

- Branch `android/alerts-backups` · kotlin · M6 · about 1700 lines · depends on skeleton-m5m6, lookup, jobs-queue, crossing-phone, written-pages · Phase A may start early · device
- Goal: A block a phone lookup met, or a job that failed in the background, posts an Android notification; the library (its tables and its kept files) can be backed up by hand, daily and before a sync, exported to a file and restored without forgetting a cooldown.
- Owns: `android/app/src/main/kotlin/io/github/danielhp95/caracole/AndroidAlerts.kt`; `android/app/src/main/kotlin/io/github/danielhp95/caracole/BackupsActivity.kt`; `android/app/src/main/kotlin/io/github/danielhp95/caracole/BackupWorker.kt`; `android/app/src/main/res/layout/activity_backups.xml`; `android/core/src/main/kotlin/io/github/danielhp95/caracole/core/backup/**`; `android/core/src/main/kotlin/io/github/danielhp95/caracole/core/sync/internal/take/Backups.kt`; `android/core/src/main/kotlin/io/github/danielhp95/caracole/core/sync/Take.kt (its backup call only)`; `android/core/src/test/kotlin/io/github/danielhp95/caracole/core/backup/**`; `android/app/src/androidTest/kotlin/io/github/danielhp95/caracole/BackupsTest.kt`; `android/app/src/androidTest/kotlin/io/github/danielhp95/caracole/AlertsTest.kt`; `android/README.md (## Alerts and backups)`; `AGENTS.md (##### Alerts and backups on the phone)`; `android/server/src/main/kotlin/io/github/danielhp95/caracole/server/lookups/BackupRunner.kt`
- Must not touch: §7.0's common list
- Provides: the phone's Alerts (the 'alerts' channel); core.backup.Backups (make, list, restore, exportTo) with labels; BackupsActivity, the daily backup
- Consumes: Alerts' calls from the lookup's block path (lookup); JobQueue's end hook (jobs-queue); the skeleton's Settings row and manifest entries; Politeness.document and merge (crossing-phone); JobQueue.onEnd (jobs-queue), PhoneKinds' backup and restore (skeleton-m5m6)
- Tests: android/core/src/test/kotlin/io/github/danielhp95/caracole/core/backup/BackupsTest.kt; android/app/src/androidTest/kotlin/io/github/danielhp95/caracole/BackupsTest.kt; android/app/src/androidTest/kotlin/io/github/danielhp95/caracole/AlertsTest.kt
- Done when: nix develop ./android -c gradle -p android test passes; nix develop ./android -c gradle -p android assembleDebug assembleDebugAndroidTest passes; BackupsTest (JVM): make with each label keeps the newest 3 of that label, quick_check before it replaces one, refuses without room; a backup holds the library tables and the kept files by SHA-256 (stateDir/backups/blobs/, shared between backups); restore puts the tables and files back, keeps the current provider:, http:last_request:, gating, phone:settings and sync:id records over the restored ones (Politeness.document before, merged after), and the pages, search and mirror are refreshed after; make, restore and the daily backup run as queued jobs (PhoneKinds' backup and restore), never beside a lookup's write; android/scripts/device-test.sh io.github.danielhp95.caracole.BackupsTest io.github.danielhp95.caracole.AlertsTest passes (a backup by hand listed and exported through the document picker's intent; a block from a lookup posts one notification, a second block of the same cooldown none; a job that failed in the background posts one); android/scripts/device-test.sh --app passes (EndToEndTest, PinchTest, SyncTabTest and PhoneEndToEndTest, each against its own computer, as the M1-3 integration ran them)

Brief:

> Repo /home/dani/Projects/caracole. Lane alerts-backups, branch android/alerts-backups, worktree .claude/worktrees/alerts-backups. Read docs/superpowers/plans/2026-11-03-android-port-m4-m6.md §7.0 first: its rules bind you. Depends on: skeleton-m5m6, lookup, jobs-queue, crossing-phone, written-pages. Phase A while any of skeleton-m5m6, lookup, jobs-queue, crossing-phone, written-pages hasn't merged; Phase B once all have (§7.0). Device lane: android/scripts/device-test.sh alone runs your area and classes.
>
> Plan sections: §1 (Alerts, Backups), §5.1 (core.backup), §5.3 (PhoneKinds), §5.5.
> Alerts: AndroidAlerts implements core.health.Alerts on the 'alerts' channel: blocked ('caracole: <provider name> blocked', the cooldown's end, once a cooldown: a second block within it posts none) and failed (a job that failed while the app was in the background: the skeleton wires JobQueue.onEnd to it; you decide 'in the background' by the activity's lifecycle). POST_NOTIFICATIONS is already declared.
> Backups: Take's library-tables backup made public as core.backup.Backups with labels (by-hand, daily, before-sync), KEEP 3 per label, quick_check, refused without twice the room; each backup also keeps the library's kept files by SHA-256 in stateDir/backups/blobs/ (shared between backups, a blob gone with its last backup), so a restore leaves no row naming bytes that differ. Restore puts the tables and files back but keeps this side's politeness current: Politeness.document(db) before, Politeness.merge after, and the current sync:id and phone:settings records, so no cooldown met since is forgotten; the restored state is then the phone's own, given to the computer at the next sync (§11 Q11). make, restore and the daily backup (WorkManager, while idle, queuing the job) run as queued jobs of PhoneKinds' backup and restore kinds, never beside a lookup's write. BackupsActivity (Settings' Backups row, the skeleton's) lists them, makes one, exports one with ACTION_CREATE_DOCUMENT and restores one (then the pages rendered, the search invalidated, the mirror reloaded). Never touch the Settings sync rows.
> Commit: feat(android): alerts as notifications, and backups on the phone.


---

## 8. Order

```
skeleton-m4 (android/m4-skeleton, merged to main)
 │
 ├─ wave 1 (6 at once): html-tokenizer · http-client · library-writes · overrides-model · jobs-queue · skeleton-m5m6
 │  as slots free:      py-sites · html-tree · health-pace · rank-coverage · matcher · job-views · lookup
 │                      · crossing-computer · py-format · prep-core · prep-db · device-replays
 │
 │  html-tokenizer ─ html-tree ─┬─ ug-pages (+py-sites) ─ ug-fetch-sheet (+rank-coverage) ─ ug-fetch-artist ─┐
 │                              ├─ lacuerda-pages (+health-pace) ─ lacuerda-sheets ──────────────────────────┤
 │                              └─ harptabs · gametabs · tab-files                                           ├─ lookup-scenarios ─┐
 │  library-writes ─ rank-coverage;  library-writes, overrides-model ─ matcher ─────────────────────────────┤                    │
 │  py-sites ─ py-format ─ lyrics ──────────────────────────────────────────────────────────────────────────┘                    │
 │  http-client ─ health-pace ─┐                                                                                                 │
 │  jobs-queue ─┬──────────────┴─ lookup ─┐                                                                                      │
 │              └─ job-views ─ requests-feed ├─ lookup-routes (+lacuerda-pages) ─┐                                               │
 │  crossing-computer ─ crossing-phone ─ index-push ─────────────────────────────┴──────────────────────────── lookups-e2e ─────┘ → M4 check
 │
 ├─ M5 (after skeleton-m5m6; its pure ports fill slots while M4's lanes wait):
 │  theory ─┬─ sheet-keys (+py-format) ─────────┐
 │          ├─ shapes-harp-winds ────────────────┼─ version-progressions ─┐
 │          ├─ harmony ─ harmony-progressions ───┤                        │
 │          ├─ chinese                           ├─ pages ─ harmonica-page ┼─ phone-render (+lookup) ─ written-pages ─ library-cards ─ pages-e2e → M5 check
 │          └─ (shapes) harptab-read ─ harptab-layout ─────────────────────┘                              (+lookup-routes, lookups-e2e)
 │
 └─ M6 (after skeleton-m5m6): songbook-writers ─ songbook-entries (+version-progressions, pages, written-pages) ─ songbook-routes
        guitar-alphatab · export-print (+version-progressions, phone-render) · versions-harmonica · review · inbox-share
        · alerts-backups                                                                                  → M6 check → integration
```

**Scheduling, with at most 6 lanes at once:**
1. After skeleton-m4: html-tokenizer, http-client, library-writes, overrides-model, jobs-queue and skeleton-m5m6 (the
   roots of M4's critical paths, and the second skeleton step while nothing else needs a slot).
2. As slots free, in this order of priority: the critical path's next lane (html-tree, ug-pages, ug-fetch-sheet,
   ug-fetch-artist, lookup-scenarios, lookups-e2e); the lanes that unblock the routes (health-pace, lookup, job-views,
   lacuerda-pages, lookup-routes); then M4's others (py-sites, py-format, rank-coverage, matcher, lyrics,
   lacuerda-sheets, harptabs, gametabs, tab-files, requests-feed, the sync-crossing group, prep-core, prep-db,
   device-replays); then M5's pure ports (theory first) and M6's independents (songbook-writers, guitar-alphatab) as
   fillers whenever M4's next lanes wait on producers.
3. A lane whose producers haven't merged may take a slot only for its Phase A, and only when no Phase B lane waits.
4. phone-render, written-pages, library-cards and pages-e2e wait for the M4 check; M6's lanes that depend on M5 lanes
   wait for them.

**The critical paths:**
- html-tokenizer → html-tree → ug-pages → ug-fetch-sheet → ug-fetch-artist → lookup-scenarios → lookups-e2e (M4); the
  routes no longer wait on it: lookup-routes needs lookup, job-views and lacuerda-pages alone;
- theory → harmony → harmony-progressions → (pages, version-progressions) → phone-render → written-pages →
  library-cards → pages-e2e (M5);
- songbook-writers → songbook-entries → songbook-routes (M6, after version-progressions and written-pages).

---

## 9. Milestone checks and integration

Each check runs on main after its milestone's lanes have merged, in its own worktree (`.claude/worktrees/<m>-check`,
branch `android/<m>-check`), fixes what it finds test first (a fix to a lane's file is named in the report), and
merges with `--no-ff`. Each runs:
- `nix develop -c pytest -q`; `nix develop ./android -c gradle -p android test bench assembleDebug
  assembleDebugAndroidTest`; `nix flake check`; `tests/test_corpus_budget.py`;
- `CARACOLE_ANDROID_E2E=1 nix develop -c pytest -q -n 0 tests/test_android_e2e.py`;
- on the emulator, through `android/scripts/device-test.sh`: `--area` over every registered area (each reported apart),
  `--app`, and every other androidTest class there is (BundledSqliteTest, LocalServerTest, and the milestone's own);
- a grep that no Phase A guard, `TODO("lane`, or "Not built yet." of the milestone's lanes is left.

**M4 check** (after every M4 lane):
- ColdSearchTest, LookupOfflineTest, NoNetworkTest, RealTransportOnDeviceTest, and LookupOnDeviceTest with `--sites`.
- The goal, end to end (the e2e's lookups phase): with the computer off, a song new to both sides is found by
  /api/search, added and looked up on the phone against the fake sites, and its card shows sheet.txt; each lookup
  stays within lookup_requests and the hour's share; a robots-closed path is never asked; no host but the fake
  server is reached; a fake 403 cools UG on the phone, and at the next sync the computer's `provider:ug` is cooling
  with the phone's events (origin = the phone's id) counted in its hour; a reset on one side reaches the other; the
  phone's index reads reach the computer; the phone matches with the computer's `[match]`; every unit's digest is
  unchanged by the health merge.
- The count of conflicts a song looked up on both sides between two syncs shows (§11, Q2) is reported.
- With the owner's yes only (§11, Q10): on the Sony over wireless adb, the cold first search and the first lookup's
  match after an import, and the WAL after it.

**M5 check** (after every M5 lane):
- PagesOnDeviceTest, PagesServedTest and the pinyin PinchTest on the emulator; `--area` over every viewer area
  (harptab's runtime regexes under ICU).
- The goal: a song looked up on the phone plays as on the computer: its sheet.html, version pages and a harmonica
  tab's page are byte for byte what `tests/helpers/phone_render.py` (render.py's page path with no PDF) writes for the
  same inputs; /api/search's `progression` finds it; its card equals library_page's; once the computer renders it again
  and a sync takes it, the mirror's page serves and the phone's is forgotten.
- A re-render after a build change yields between songs (a lookup queued meanwhile runs first); its time over the
  e2e library is reported.

**M6 check** (after every M6 lane):
- SongbooksOnDeviceTest, VersionsPageTest, GuitarPageTest, PrintTest, ShareTest, BackupsTest and AlertsTest on the
  emulator.
- The goal: a songbook made and edited on the phone (a setting, a move, a rename), a version kept and one made the
  song's own, a match reviewed, a Guitar Pro file shared and filed, each reaching the computer as its units at the
  next sync and read back by its readers (peer take, put_songbook, put_song_entries); the phone's songbook.html
  served; Export PDF prints; a backup restored with no cooldown forgotten.

**Integration** (the final step, after the M6 check; `.claude/worktrees/m4-m6-integration`):
- Everything of the checks above, once more, on one emulator, in one run.
- The round's scenario, a new e2e phase written by this step: the phone, the computer off, looks up two songs against
  the fake sites, plays one (its page the phone's own), makes a songbook of both, sets one's key, makes a version its
  own, shares a Guitar Pro file to one, backs up; the computer back, one sync: every unit equal both ways, the health
  crossed, and the phone's pages of those songs equal `tests/helpers/phone_render.py`'s run on the computer's copy, byte
  for byte. The computer's own pages (`caracole render`, with chordpro) differ from them by design in the PDF member
  of the data and its footer link alone, which the phase asserts too (the rest of the bytes, with that member and link
  masked, equal).
- `nix flake check`; the corpus budget; a review of AGENTS.md's headings (no "Not built yet." left, each section
  true), docs/usage.md, android/README.md; docs/android_port.md gains "Built: milestones 4 to 6" (what works, what
  only a real phone can show, what is left) and its milestones and "Changes on the computer's side" are updated; the
  politeness spec and the corpus spec say what was built.
- The emulator stopped at the end.

---

## 10. Risks

- **The HTML parser** is the largest new semantic port. A divergence from lexbor on malformed markup changes a parse,
  hence a kept file's bytes, hence a unit's digest, hence a sync conflict. The mutation set measures it, foreign
  content is built as the spec builds it, and the fixtures are trimmed pages; the owner's HTTP cache (12,154 real
  bodies) is the only real check, local only and with the owner's yes (§11, Q1c). The fallbacks: nu.validator's
  htmlparser, timed by html-tokenizer first (Q1b), or lexbor through the NDK (Q1).
- **Lane sizes.** M1–3's rule-dense ports ran 1.3–2× their estimates. Lanes are now about 2,000 lines, 2,600 at most,
  with groups split at declared seams; theory, sheet-keys, http-client, matcher and version-progressions are the
  largest left, each one Python module or two.
- **57 lanes and two skeleton steps** cost merges and reviews; groups keep handoffs on one branch, and skeleton-m5m6
  runs beside M4's first wave so it costs no wall-clock time.
- **One emulator for about 45 device lanes**: each run holds the lock for its install and its own areas (minutes); a
  queue forms near each milestone's end. Building outside the lock, `--area` and `--app` keep each run short.
- **Two implementations to maintain** grows by about 100,000 lines: every site, page and theory change on the computer
  moves the corpus and the Kotlin side. The corpus catches drift; it doesn't prevent the work.
- **A block met only on the phone** (its network or TLS stack drawing a Cloudflare challenge where the computer's
  doesn't) cools the computer at the next sync and costs its nightly run (§11, Q3).
- **Between two syncs**, each side counts only its own requests: together they can send up to twice an hour's or a
  day's limit (§11, Q16).
- **Schema 16 in lockstep**: an old phone can't merge a new computer's index export, and the reverse; both sides
  upgrade together.
- **The matcher's memory** on the phone (hundreds of thousands of keys loaded for title_only and catch_all) may not
  fit or may take seconds; MatcherBench measures it, the M4 check on a real phone confirms.
- **The cold first search** may have a cause the emulator doesn't show; the Sony is the owner's to measure.
- **UG's volatile ratings** make a song looked up on both sides between syncs a conflict (§11, Q2).
- **One worker**: a lookup waits behind an index import (about 1.5 minutes on the Sony) or a long sync; the render job
  yields, an import doesn't.
- **Doze and background limits** during a lookup: the queue runs in the foreground service; a killed process leaves
  an interrupted request, never a half-written unit (autocommit, each write whole).
- **Page builds on a phone**: a full re-render after an upgrade is minutes; it yields between songs.
- **A restore** gives the phone's restored state to the computer at the next sync as the phone's own change (§11, Q11).
- **The corpus** at 70 MB of vectors makes the repository heavier with each regeneration (§11, Q9).
- **Printing**: Android's WebView print adapter is untested in CI beyond its creation; book.js shows one song at a
  time, so a songbook prints one song (§11, Q8).
- **Chromium and Gradle tests flake** at high load: at most 6 lanes, `-n 4`, 4 Gradle workers, benchmarks gated.

---

## 11. Open questions for the owner

Defaults are taken; each can be changed before its lane starts.

1. **The HTML engine.** Default: a pure-Kotlin HTML5 parser with lexbor's semantics, held by vectors. Alternative:
   lexbor itself through the NDK (exact by construction; the NDK, CMake and a host build in both flakes; about 1 MB
   per ABI). Which?
   - 1b. **nu.validator's htmlparser** (a pure-Java WHATWG tokenizer and tree builder, a dependency of :core) under
     core.html's own text and selector layer, if html-tokenizer's half-day timing shows it matches lexbor's trees?
     Default: hand-written; the lane reports.
   - 1c. **A local-only differential run** of core.html and the site parsers against selectolax over your HTTP cache
     (~/.cache/caracole/http, 12,154 bodies), never committed, each divergence pinned as a small committed edge case?
     Default: not run without your yes.
2. **UG's volatile raw.** Default: FORMAT 2 unchanged, so a tab fetched on both sides between syncs may show a
   conflict. Alternative: hash raw without rating and votes, a FORMAT 3 bump. The M4 check counts how often.
3. **A block met only on the phone** cools the computer at the next sync (your rule, as taken). Keep, or carry the
   phone's cooldown without adding a strike on the computer?
4. **A lookup behind an import or a sync** waits on the phone's one worker. Keep, or give lookups a second worker that
   never writes beside a write job?
5. **Words and links on the phone.** Default: Python's words verbatim ("the nightly run tries again", true once
   synced), and no link where the computer links the to-do page. Or a phone wording, made a parameter on both sides?
6. **Lookups on mobile data.** Default: allowed. Or Wi-Fi only, a setting?
7. **Which songs the phone renders.** Default: the songs the mirror doesn't serve (its own, changed or looked up on
   the phone), progressions for all, cards for all. Or every song (independent of the mirror, twice the storage)?
8. **Printing.** Default: Export PDF prints the open viewer; a songbook prints its open song; print CSS gains the
   light palette and margins on both sides. Do you want two columns and the chord diagrams in print (a larger change
   to the computer's pages), or a phone-only page printing a whole songbook in each song's setting?
9. **The corpus's size.** Default: 70 MB of vectors and 12 MB of runtime data, per-area budgets in bytes, fixtures
   referenced not copied, pages as digests. Or gzipped vectors (mtime 0), or a tighter budget?
10. **Testing on your phone.** May the M4 and M6 checks use the Sony over wireless adb to measure the cold search,
    the first lookup and storage? Or will you run those?
11. **Backups.** Default: the library tables and the kept files (by SHA-256, shared between backups; the indexes
    re-import), by hand, daily and before a sync, three of each, exportable to a file you pick; a restore keeps the
    current cooldowns and gating records, and the restored state is given to the computer at the next sync as the
    phone's change. Or: after a restore, the computer's version wins for every unit the restore changed? Or the whole
    database (about 430 MB a copy)?
12. **A shared file no song fits.** Default: kept 30 days in the app's state and tried again after each sync and
    lookup. Or a picker of your songs at once? And scores matched by file name only on the phone (no MusicXML
    header reading): fine?
13. **Alerts.** Default: a block a phone lookup met (once a cooldown; on the computer a lookup sends none, but the
    phone has no nightly run to tell), and a request that failed while the app was in the background. Others (a sync
    that stopped on conflicts, an import finished)?
14. **alphaTab in the APK** adds about 1 MB compressed (2.8 MB bundle) and three licence notices. Fine?
15. **The request form's hint** says "Added to wanted.txt", untrue on the phone; "Fetch it now gets its sheet right
    away" becomes true with M4. Change the shared template (a blank, both sides' pages move), or leave it?
16. **Limits between two syncs.** Each side counts only the requests it knows until the next sync, so the two can
    together send up to twice `lookup_per_hour`, Megalobiz's 900 a day (its API's 1,000) and LaCuerda's 20 searches
    an hour. Default: accept (the phone's lookups are few, and every count crosses at a sync). Or give the phone a
    share until the next sync (say, a day's limit less the computer's count at the last sync)?

**Left for later, by this round** (no question, no lane): the Sites tab's empty state before the first sync (it needs
sites.js, a shared asset the instrument-buttons design may change); MusicXML header matching on the phone (Q12).

---

## 12. Lessons applied (from milestones 1–3)

- **Shared types and helpers declared once, by the skeletons**: every exception of core.http, `SharedFolder`,
  `OverridesError`, `SongbookError`, the stats classes, `Pacing`, the config data classes, the Lyrics model, match's
  constants, `Reads`, the site stages' contract (`Asking`, `StageContext`, `StageEnd`, `CommandContext`, `FakeAsking`);
  one owner each for Stamps, noOnes and PINYIN_PARTIAL_SCALE (prep-core); PyText, PyUrl, PyStr, Inline and
  DownloadNames moved into :core, and `ForbiddenApis` run over :core, :viewer and :server.
- **Assembly.kt, Stubs.kt, PhoneKinds.kt and the app's entry points pre-wired** by the skeletons with neutral
  implementations, so no lane edits them; the route modules take their stubs' entries; AssemblyTest asserts wiring,
  never a neutral answer.
- **The skeleton split in two**, so the M4 gate is small and the M5 and M6 declarations come beside M4's first wave.
- **No lane waits on the slowest of its consumers' producers**: each site's lookup stage is its site lane's file, so
  lookup, lookup-routes and the e2e depend on the frame alone; HTML needs only the entity table; ug-fetch needs only
  match's constants; harmony needs only theory.
- **Tests that assert a neutral answer belong to the lane that replaces it**, named in its owns: LibraryRoutesTest,
  ApiSearchTest, MirrorPageDataTest, PhoneScenarioTest's phase 2 and PhoneEndToEndTest's Get it (lookup-routes),
  LibraryPageTest (requests-feed), JobViewsTest (job-views), LibraryFilesTest (written-pages).
- **Grouping**: lanes owning the same files in turn share one branch (nine groups, §7.0); files owned in sequence are
  listed in §7.0 and ordered by depends_on.
- **Sizes**: about 2,000 lines a lane, 2,600 at most, rule-dense ports split at declared seams.
- **Device tests in each lane that needs them, not only at the checks**: every replay's area on ART, `--app` for
  every lane that changes routes, pages or the app, `assembleDebugAndroidTest` in every Kotlin lane; the Replays
  registries cover every area, M1–3's included (device-replays).
- **No live request, by construction**: `PhoneDeps.transport` has no default and is read per request;
  `RealTransport` refuses non-loopback hosts under every Gradle test task and under the app's test runner, which also
  turns LaCuerda's auto search off; the e2e and device use the fake sites server.
- **`nix flake check` before merges** that add tests (the package build's fileset); a test reading outside it skips.
- **The corpus budget enforced** by a test, per area in bytes, with headroom per writer, fixtures referenced rather
  than copied and pages as digests.
- **Benchmarks gated** in their own task and heap, so a lane's suite never runs a 1.5 M-row data set.
- **The WAL and the cold first search fixed before the lookups rely on them** (prep-db), measured on a big index.
- **Byte agreement where sync looks**: kept files, versions' raw, overrides' and songbooks' values written by
  writers ported with their read-back checks; the health merge proven never to move a unit's digest.
- **The designs in progress left alone**: no lane edits sync.js, sync-tab.html, sync-panel.html, sync.css,
  MainActivity's menu or Settings' sync rows (the sync redesign); rows.js, card.js, library.js (the instrument
  buttons: library-cards ports the card data in one place, restructuring nothing); no `text/plain` share filter and no
  `VIEW` filter (the music-app links); no relay for Fetch now. Their files: `library_assets/sync*.{js,html,css}`,
  `app/res/menu/main.xml`, `MainActivity.kt`'s menu, `SettingsActivity.kt` and `activity_settings.xml`'s sync rows,
  `Syncs.kt`, `IndexImports.fromComputer`, `SyncRoutes.kt`, `web/sync_routes.py`, `SyncOutcome`, JobViews' and
  status.py's sync lines; `library_assets/rows.js`, `card.js`, `library.js`, `card.css`, `rows.css`,
  `library_page._song`, `PhonePageData`; `AndroidManifest.xml`'s share filters and `ShareActivity`'s dispatch.
- **Review then fix** after each lane, before its merge.
- **AGENTS.md and the docs owned by section**, so no backlog piles up for integration.

---

## 13. The critics' issues, and how this plan settles them

Two critics read the first draft (completeness, executability). Every blocker and major issue is settled here; where a
critic's premise was wrong, it says why.

| Issue | Settled by |
|---|---|
| Device tests could reach live sites (the guard is a Gradle property; PhoneEndToEndTest's Get it becomes a real lookup; LaCuerda's auto search) — blocker | `CaracoleTestRunner` sets the guard and a refusing `sitesForTests` before `Application.onCreate`; `PhoneDeps.transport` read per request; `searchesLacuerda` false under the runner; the guard allows 10.0.2.2 for RoutedTransport; PhoneEndToEndTest's lines are lookup-routes'; NoNetworkTest (§1, §5.5, §6.1) |
| Strikes ratchet across the sides | Providers merged by the side with the later decisive event, a running cooldown never shortened; vectors for a reset and a block after it (§4.2) |
| `songs` merge: ug_dirty OR-ed; ug_checked_at and lacuerda_checked_at don't cross; `:pick` keys aren't stamps | The `ug` pair by the later check, `lacuerda_checked_at` by the later, `:pick` with its base record (§4.2) |
| ug_dirty is in SONG_COLUMNS, so a merge would change digests (executability) | **Premise wrong**: peer_sync.song_value, the digest's input, reads status, review, the match, the lyrics, versions, files and overrides alone; SONG_COLUMNS are carried only when a unit is taken. Settled anyway: a test on both sides that a merge moves no digest and writes no other SONG_COLUMNS column or CARRIED_KV record |
| ug:unreadable: deletions can't cross | It no longer crosses (§4.2: each side's own, like the cache) |
| Exporting by the computer's stamps loses rows; LaCuerda rows have no time; the push never runs when nothing merged | `core.index.Reads` notes each page a lookup stores; the push sends those since the last push, merged or not (§4.4, index-push) |
| Nothing lets the render job yield | `JobContext.yieldToQueued()` (jobs-queue), called by phone-render between songs |
| The phone's stale page served first | Pages recorded with the unit digest they were made at, served only while current; a take forgets superseded pages (written-pages) |
| "The computer's pages equal the phone's" can't hold with PDFs | `tests/helpers/phone_render.py` (render.py's page path with no PDF) is the reference; the computer's own pages differ by the PDF member and link alone (§9) |
| The pdf stage would show "failed"; viewer pages are written in the pdf stage on the computer | get.py's NO_PDFS and PAGES_MADE words (lookup); PhoneRender in the pdf stage's slot, pages the library page (§2) |
| ForbiddenApiTest scans :core alone | `ForbiddenApis` over :core, :viewer and :server (§6.1); AGENTS.md's rule widened |
| A restore rolls back cooldowns and names files that differ | Backups keep the kept files by SHA-256; a restore keeps this side's politeness; make and restore are queued jobs (alerts-backups, Q11) |
| New computer jobs need web/jobs.py, status.py, outcome.py, which requests-tab owned | skeleton-m4 writes those kinds and their corpus records (§4.4, §6.1) |
| Alerts.failed has no wiring | `Alerts.failed` declared; `JobQueue.onEnd` wired to it by the skeleton |
| Many areas had no replay object | Three registries list every area; each lane owns its file (§3) |
| html waited on py-text | skeleton-m4 writes the entity table and PyCodec; html-tokenizer starts in wave 1 |
| ug-fetch and lacuerda need lyrics.song_lyrics; ug-fetch needs only match's constants | Both whole in skeleton-m4; matcher dropped from ug-fetch's producers |
| lookup waited on ten lanes | Site stages and commands inverted into their site lanes' files; whole lookups replayed by lookup-scenarios |
| M5 dependencies tighter than the imports | Found.kt's progression is library-cards'; harmony needs theory alone (TUNING a constant); SongbookPage moved to songbook-entries |
| One serial skeleton with elided signatures | Two steps (§6); elided signatures take Python's parameter lists, the report lists each |
| ScenariosTest needed LRCLIB and EventLog | The helper's records are HTTP-only; events compared from onEvent |
| Whole-lookup recording left unspecified | lookup-scenarios' brief: transport_for patched, render and pages no-ops, outputs filtered to what the phone writes |
| Corpus budgets: units, headroom, total under the sum | Bytes, decimal MB, today's size plus writers' allowance, 70 MB total over the 68 MB sum (§3) |
| Big tests in every `gradle test` with a 512 MB heap | The gated `bench` task (§6.1, §7.0) |
| Lanes filling replays weren't device lanes; no assembleDebugAndroidTest | Every replay lane is a device lane for its area; every Kotlin lane builds the androidTest APK |
| device-test.sh: lock path, builds under the lock, one area hides another, system UI left up, one computer | All five fixed (§6.1) |
| RealTransport's headers on Android; Host on the JDK | A header set, not an order; RealTransportOnDeviceTest; RoutedTransport carries the URL in the query |
| Foreign content as ordinary elements diverges | Built as the spec builds it (html-tree); nu.validator and the cache differential are Q1b and Q1c |
| Estimates too low | Splits: html, py-text, ug-fetch, harp-game, lacuerda, requests-tab, harmony, phone-render, songbook-tab |
| App classes only at milestone checks | `--app` in every lane that changes routes, pages or the app |
| Minor ones | Taken: prep-core's stale items, device-replays' exact files, harp_*, index-push's owns, jobs-queue's gates, onEnd, OpenCC's version (whatever the shell has, recorded: the critic saw 1.4.0, the page-builder map's store path says 1.4.1), guitar's CORS header and its failure without the directory, TZ=Europe/Madrid's zone label, export-print on its own branch, versions-harmonica on the device, prep-db's IndexTransfer line, Lookup.run blocking, the phone's alerts in AGENTS.md, the POST /lookup redirect, the harptabs fixture names, SEND only, phone-only kinds' words in PhoneKinds; the per-day doubling is Q16; the Sites tab's empty state is left (§11) |
