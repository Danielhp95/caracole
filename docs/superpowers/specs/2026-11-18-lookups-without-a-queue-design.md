# Lookups without a queue

Status: written 2026-11-18 from the owner's decisions of that day (.superpowers/sdd/lookup-lane/decisions.md in the
main checkout), which bind. The rest is this spec's; its own choices are marked *(call)*. The computer alone: the phone
keeps its one queue for now. Paths are under src/caracole/ unless named otherwise, the phone's under
android/server/src/main/kotlin/io/github/danielhp95/caracole/server/jobs/; lines are main's at afe50f23.

## Why

A song asked for from the library page's search box waited, "Queued · 1 request ahead…" (web/status.py:240), because
another request was running. The owner: "I want there to not be a queue for search-bar lookups (also ultimate guitar
look ups that have been pasted via a link)", and "the politeness is for long crawls, not for one-offs".

The pace is not the wait: a lookup leaves 0.125–0.375 s between two requests to a site. The wait is caracole serve's
one worker, which starts a request only once every request before it is over (web/jobs.py:46-50, `_work` :764,
`_next` :775).

## Goals, non-goals, anti-goals

Goals:

- A lookup (`caracole get`) and a pasted UG link's read (`caracole ug --link`) start the moment they are asked for.
- Two or three at once all move. They pass caracole's lock to each other between two requests, as bulk work already
  hands it to a lookup.
- A site still gets one request at a time from caracole, each after the pace's pause from the last one any caracole
  sent it.
- The queue's other requests run as now: one at a time, in order.

Non-goals: the phone's queue (a later step); the nightly run's pace, budgets and handoff; any per-request delay or
budget (`lookup_delay`, `lookup_requests`, `lookup_per_hour` stay); the e2e phase-11 failure and test_ug_directory's
thread race (decisions.md: later).

Anti-goals:

- **A site gets two requests at once from caracole.** Never: only the lock's holder sends.
- **Two caracoles write the library at once.** Never: only the lock's holder writes, and the lock changes hands only
  where nothing is half-written (no transaction open, no render or page being written).
- **A lookup waits minutes behind a YouTube sheet's models or a sync.** Partly met: short jobs and YouTube's pauses
  let a lookup through; a YouTube sheet's model run and a sync still hold it (part 4, "How far it gets").

## What the code does now

**The queue.** One worker thread runs every job in order (web/jobs.py `start` :744, `_work` :764, `_next` :775,
`_run` :784). `CaracoleRunner` keeps one child process (`_process` :876, `terminate` :894). serve makes one queue
(commands/serve.py:75; web/server.py:142, :150). `submit` (:609, `_submit_locked` :669) keeps one job a song key: the
song's job that does as much is the answer (`_as_much` :529; a pick, `_pick` :473, only the song's last job with the
same pick), else the request joins the song's job that waits (`_join` :545: a lookup takes an add's place), else a job
of its own, `LIMIT` 20 (:90). `submit_all` (:639) is all or none, `together`; `cancel` (:693) takes out a job not
started. Each change is saved to `state_dir/requests.jsonl` under the queue's lock (`_save` :829); a restart reads
the jobs that waited or ran back interrupted (web/history.py:208). The routes are part 1's table.

**The lock** (commands/_common.py).

- `exclusive` (:485), `_acquire` (:230). What the owner asked for now (`interactive=True`) tries the flock, and if it
  is held says whom it waits for (`on_wait`) and waits announced: a ticket in `caracole.lock.waiting/`, polled every
  0.05 s, touched every second, given up after 5 s untouched or with its pid (`_wait_announced` :330,
  `lookups_waiting` :354). Anything else waits outside handoffs (`_take_outside_handoffs` :270: the flock, then the
  `caracole.lock.handoff` gate).
- Bulk work hands over (`hand_over` :406) in a pause, outside a transaction, when a ticket waits: it holds the gate,
  lets go, waits while tickets remain (`HANDOFF_TAKE`, 10 s at most), blocks to take it back, and counts a handoff
  (`handoffs()` :386). Its clients do so in each pause (`_patient_sleep` :451, `_LockedClient._wait` :569,
  `yields=not interactive` :762), then take on a block the lookup met and keep the pause after its last request
  (`_after_a_lookup` :586, kv `http:last_request:`); callers read overrides.toml again (`overrides_since` :391).
- A process that took the lock as interactive hands it to no one (`_as_lookup` :227, refused at :422): the bulk work
  waiting to take it back would take it first and keep it. So `youtube --sheet`'s "a waiting lookup goes first" before
  its models never hands over (youtube_sheet.py:416, under its interactive lock, :467), nor do the yt-dlp pauses of
  `youtube --search` and `--video` (`make_youtube` :875-878, :886).
- A lookup's client gets its budget once, as it is made: `min(lookup_requests, lookup_per_hour − used)`
  (`lookup_policy` :677, `make_client` :738-739).

**A lookup** (get.py). One interactive `exclusive` around every stage (:909); overrides.toml read once there (:911);
keys made current (:916); the stages in order (:922-927); a client a site, made on first use (:302). It writes in
autocommit, a savepoint where a write must be whole: overrides.toml in its song stage (:452-472), wanted.txt for a new
song, its song's files and rows, kv, the index rows of the pages it reads, _todo.md and index.html (:853-863), its
songbooks (:865-891). Its run id is `lookup:` and the time to the second (commands/_common.py:216, get.py:241), and
its good run is read back by run id (`answered_any`, health.py:126; get.py:930, commands/ug.py:199,
commands/lyrics.py:412, :518, :761): two lookups started in one second would read each other's errors.

**The words.** "Queued…", "Queued · N requests ahead…" (web/status.py:239-240), N every active job before it
(web/jobs_routes.py `_ahead` :419). Running, the running stage's line, or "Waiting for the book…" while the song
stage's detail starts "waiting for the book" (status.py:138, :353-354), as get.py's `on_wait` writes it (:905-907);
the page's bar "Waiting for the book · 1 of 7" (web/outcome.py `waits` :326-327), nothing for the first `BAR_AFTER`
(:123). The Journal's Now: the running jobs first, by id, then the queued ones, "Queued · next", "2nd"…
(web/feed.py:64-70, :102).

**The phone** ports these words (Status.kt:202, :142, :308; JobViews.kt:77, `queue.ahead`; Feed.kt:27), runs one job
at a time (JobQueue.kt:287-288, `next` :566), and already lets lookups queued behind a long job run in its stead
(`yieldToQueued`, :822-832). The corpus holds them: vectors/web/queue.jsonl and history.jsonl
(tests/test_conformance_queue.py), job_views*.jsonl, outcome.jsonl, requests.jsonl.

## Constraints

These hold as they are (AGENTS.md, Invariants):

- **Either pace**: one request at a time per provider, a redirect a request, each after the pause from the last one any
  caracole sent. One holder sends; after a turn a client keeps kv `http:last_request:`.
- **An interactive lookup**: `lookup_delay`, `lookup_requests` a song, `lookup_per_hour` for every lookup together,
  `SHEETS_SHARE` after the sheet. Two at once share the hour's 60, so it is read again after every turn (part 3).
- **Blocks**: one lookup's block stops the other before its next request there. `record_block` adds no strike for a
  cooldown begun after its caller started, and `record_ok` clears none.
- **Errors are never misses**, **A search asks no site**, the LaCuerda and YouTube search gates: unchanged; a gate is
  checked and spent in one turn (part 3).
- **Bulk work hands the lock over** to lookups alone; a `caracole-admin` command never gets it in a handoff.
- **serve never takes the lock**: it runs more children, nothing else.
- **The phone agrees to the byte**: no word of status.py, outcome.py or feed.py moves (part 6).
- No schema change, nothing new in the library folder.

What changes in AGENTS.md's words is listed in part 8.

## Approaches

From decisions.md:

1. **A lane of their own, passing the lock between two requests** (chosen). Such requests start at once beside the
   queue; two at once take turns with caracole's lock where bulk work already hands it over. Each keeps its process,
   its stages and its pace; the lock still orders every request and every write.
2. **Jump the queue** (rejected): a lookup goes to the head of the queue. A second search still waits for the first.
3. **Fully parallel, the lock held only for writes** (rejected): every site's fetch split from its writes, in every
   stage, and a lock a site to keep one request at a time. Far more code moves, for no more than option 1 gives.

## The design

### 1. The lane (web/jobs.py)

A job is the lane's when each of its commands is a lane command. `lane_of(steps)` is a pure function of the steps,
never stored: the history's format and its corpus stay, and a job that joins another moves with its steps (a lookup
that takes an add's place).

| Asked from | Route | Command | Goes to |
|---|---|---|---|
| a search's Get it, Fetch again, the lookup page | POST /lookup (web/search_routes.py:241) | `get` | the lane |
| a song's Fetch | POST /fetch (web/library_routes.py:144) | `get` | the lane |
| the request form with Fetch it now, Add again | POST /request (:123) | `get` (else `add`) | the lane (`add`: the queue) |
| a pasted UG link | POST /ug/link (web/ug_link_routes.py:122) | `ug --link` | the lane |
| LaCuerda's search, by itself or by hand | POST /lacuerda/search (web/search_routes.py:1108) | `lacuerda --search` | the lane |
| an artist's page on LaCuerda, on harptabs.com | POST /lacuerda/artist, /harptabs/artist (:1035, :1004) | `lacuerda --artist`, `harptabs --artist` | the lane |
| YouTube's first video, a pasted video | POST /youtube/search, /youtube/video (web/youtube_routes.py:193, :292) | `youtube --search`, `--video` | the queue |
| a sheet from a video | POST /youtube, /request with a video (:114) | `youtube --sheet` | the queue |
| a sheet's versions | POST /versions/… (web/versions_routes.py:141) | `versions` | the queue |
| Get the missing songs | web/songbook_routes.py:64, :73 | `get --no-songbooks` each, then `songbook render` | the queue |
| Add a song (Songbooks tab) | web/songbook_routes.py:106 | `get`, then `songbook add` | the lane, then the queue |
| everything else (add, remove, review, render, harmonica, songbooks, sync, import, index merge) | | | the queue |

Its calls:

- *(call)* Every route's `get`, not the search box's alone: a song's Fetch, Fetch again and the request form run the
  same command for the same "now", and the joining rules work by song key whichever button sent it.
- *(call)* The search box's one-request reads join it: LaCuerda's search, which the page sends by itself as you type,
  and an artist's page. Each is one request at the lookup pace, and today waits behind whatever runs as a lookup did.
- *(call)* YouTube's search and a pasted video stay in the queue: a yt-dlp run holds the lock with no point inside it
  to pass a turn, after a 3.75–7.5 s pause, and it is a suggestion, not a song asked for. They let a lookup go first
  in that pause (part 4).
- *(call)* Get the missing songs' lookups stay in the queue: a 20-song songbook would fill the lane for minutes, with a
  song typed meanwhile behind it. As `get`s they still take turns at the lock with the lane's (part 2).
- *(call)* `versions` stays in the queue: it is asked from a sheet's page, and Fetch them spends a lookup's whole
  budget.
- *(call)* `LANE = 3` lane jobs run at once; a fourth waits in the lane, in order. The lock is one, so more at once
  fetch no faster in all; each starts at once and shows its steps, and a slot costs a Python process (about half a
  second to start). Two covers a song and another while it runs; three leaves room for a quick set list. `LIMIT`
  counts both.

Its workers, the queue's one as now and `LANE` lane workers, each `_next(lane)`:

- **The queue's worker starts its next job only while no lane job runs or waits.** The lock would make that job wait
  for the lane anyway (part 2), and it says so as Queued rather than as a step that seems to run. And a job queued
  after a lookup that needs what it got still comes after it: Add a song's `songbook add` after its `get`.
- **A lane worker takes the first queued lane job whose song (`song_key_of`, :468) has no job running**, in either
  lane: a song's second lookup for another pick, or a lookup asked while its add, removal or YouTube sheet runs, waits.
- `CaracoleRunner` keeps a process a running command; `terminate` ends them all, and a job's own can be ended (Cancel,
  part 5). `stop` joins every worker.
- `JobQueue(…, lane=0)` is today's queue, its counts and ordinals as now; caracole serve passes `lane=LANE`. The
  corpus's queues (tests/test_conformance_queue.py) stay at 0: they are the phone's one queue.

### 2. Turns at the lock (commands/_common.py)

A process running a lane command takes turns, wherever it was started (a `caracole get` in a terminal beside serve's
too). It asks with `exclusive(..., lane=True)`: get.py:909, commands/ug.py:158, commands/lyrics.py:384, :468, :725. A
nested `exclusive` keeps the outer one's kind.

1. **The lane flock.** A lane process holds a shared flock on a lane file (`caracole.lock.lane`, say) from before it
   asks for the lock until it ends. Its tickets say they are the lane's.
2. **A turn** (`pass_turn`). Holding the lock, at a turn point (part 3), outside a transaction, when a lane ticket
   waits, a lane process writes its own ticket, lets go of the flock (its depth kept, as `hand_over` does), waits
   announced to take it back, writes its record back, and counts a handoff, so whatever reads again after a handoff
   reads again after a turn. The oldest lane ticket goes next (tickets are named by when they were made): three take
   turns in order.
3. **Everyone else waits for an empty lane.** A process that isn't the lane's, once it has the flock (interactive, or
   through `_take_outside_handoffs`), tries the lane flock exclusively without blocking. While a lane process holds it,
   it lets go of the lock, waits for the lane to empty holding nothing, and tries again. So a removal, an add or a
   YouTube sheet of serve's queue, or the nightly run starting, never takes the lock between two turns. One that holds
   the lock already keeps it to its end, or to its next hand-over point (rule 4).
4. **Handing over.** Bulk work hands over as now. A process that took the lock as interactive now does too, to lane
   lookups alone, at the hand-over points it already has (part 4). Each takes the gate if it is free, never waiting for
   it (bulk's own handoff holds it when an interactive command bulk let in hands over in turn). Each takes the lock
   back only once the lane is empty (bulk work: and no other ticket waits). An interactive caller waits announced, a
   ticket of its own, so the bulk work that let it in, waiting too, gives it back at its next pause rather than keeping
   it to its end: `_as_lookup`'s reason is gone, and so is its refusal (:422). Bulk work takes the lock back last,
   blocking; `HANDOFF_TAKE` bounds only its wait for a ticket nobody takes, never the lane's work.
5. **Unchanged**: bulk work hands over only in a pause or between two songs, outside a transaction; a `caracole-admin`
   command waits outside handoffs (the gate), and now outside the lane.

So the lane's lookups go first, by turns; then what the queue or a terminal asked for now; then bulk work.

| Holding the lock | A lane lookup that asks gets it |
|---|---|
| nothing | at once |
| another lane lookup | at that one's next turn point: after one request, or one stage |
| bulk work (the nightly run, a `caracole-admin` command) | at its next pause, or between two songs, as now |
| a queue job with a hand-over point (`youtube --search`, `--video`, `--sheet`'s audio and models, `fetch --song`) | at that point |
| any other queue job (add, remove, review, render, harmonica, versions, songbook, sync, import, index merge) | at its end |

No deadlock: nothing that holds the lock waits for the gate or blocks on the lane's flock (it tries both without
blocking, and lets go of the lock before it waits); a lane process holds the lane's flock while it waits for the lock,
but polls; bulk work alone blocks holding a flock, on the lock while holding its gate, once the lane is empty.

### 3. A lookup's turn points, and what it reads again

- **Where**, only where nothing is half-written, and never in a transaction (`conn.in_transaction`):
  - at the start of a lane client's pause before each request, whatever is left of it (`_LockedClient._pause`,
    commands/_common.py:581, over http.py:711), so the other lookup uses the pause;
  - between two stages (`_Lookup.stage`, get.py:264), and between `ug --link`'s tab page and its artist's lists;
  - *(call)* not in a new client's first pause (`_pause_after_last_request`, :741), so a gate checked under the lock
    and spent on that client's first request is one turn (LaCuerda's search, commands/lyrics.py:471-500);
  - never inside a render, `write_pages` or a songbook's render: none has a pause.
- **After a turn, the client**, as `_after_a_lookup` does for bulk: it sends nothing to a site the other lookup was
  blocked by (ProviderBlocked, no strike); its pause runs from the last request any caracole sent the site; and its
  budget is cut to what the hour leaves of `lookup_per_hour`, the UTC day of `per_day` (`within_the_day`), and, after
  the sheet, of `SHEETS_SHARE` (get.py:361-379). Read once today (make_client :738-739, get.py:368), two lookups could
  together pass the hour's 60.
- **After a turn, the lookup**, at its next stage: overrides.toml (`overrides_since`, keyed by `handoffs()`), since the
  other may have pinned its own song's tab, which this one's index.html would leave out; and its song's row, as bulk
  work's `as_now` does (provider_pass.py:47).
- **Its good run** is read from its own clients, each counting what it was answered and its errors and blocks, not
  from `events` by run id. *(call)* So the run id stays `lookup:<time>`, and with it `lookup_requests_used` (by
  prefix) and the corpus that holds run ids (vectors/pace/run_id.jsonl, vectors/lookup/commands_*.jsonl).
- **Nothing else.** The first lookup to hold the lock makes the keys current before any turn, so the next one's
  `ensure_current_keys` does nothing. The HTTP cache and the indexes are read at each request and query. The other
  lookup's song is never this one's (part 1).

### 4. The queue's jobs that hold the lock

- Short ones (add, remove, review, render, harmonica, versions, a songbook change) keep it to their end, seconds. A
  lookup asked meanwhile waits that long, then goes before the queue's next job.
- Their hand-over points start working (part 2, rule 4): the pause before a yt-dlp run (`make_youtube`,
  commands/_common.py:878, :886: `youtube --search`, `--video`, `--sheet`'s audio), `youtube --sheet` before its
  models (youtube_sheet.py:416, overrides read again at :417, as its docstring :22-23 says already), and the pauses of
  `fetch --song`'s bulk-pace client.
- **How far it gets.** A lookup asked while a YouTube sheet's models run (one `autochords_pending` call, minutes), or
  while a sync, an import or an index merge runs (no hand-over point), waits for it: "Waiting for the book…", the
  Journal's detail naming the holder. Left for later: the models run without the lock (they read the audio and write
  at the end), and a sync handing over where a lookup can change no unit it compared (before it takes, after it
  agrees).

### 5. Same song, Cancel, Try again, the history, a stop

- **Same song**: `submit`'s rules stand: a lookup of a song whose lookup waits or runs is that job; a pick joins the
  last one with the same pick, or comes after it. Part 1 keeps a song's second job from starting beside its first.
- **Cancel**: as now for a job that waits, a lane job waiting for a slot among them. *(call, Q3)* A lane job that runs
  but still waits for the book can be cancelled too: it holds no lock, has written nothing, and the route wrote
  wanted.txt already, as for a cancelled add. Its process is ended, the job cancelled. A job that has had the lock is
  never stopped.
- **Try again**: a new `submit` of the same steps, in their lane.
- **The history**: its format stays; saves stay under the queue's lock, in order; several running jobs are each read
  back interrupted, as history.py does any.
- **A stop**: `stop` ends every running command and marks each job interrupted. A lookup ended mid-turn drops the lock
  and the lane flock with its process; its ticket goes with its pid.

### 6. What the pages say, and the corpus

- *(call)* No new word. A lookup taking turns says its running stage's line ("Fetching from UG…"): a turn lasts one
  request or one stage of the other, and both move. "Waiting for the book…" keeps its meaning: a lookup that can't
  start its first stage, whoever holds the lock.
- *(call)* `on_wait` is told once the wait has lasted `WAIT_SAID` (1 s), so a lookup that starts as another passes its
  turn never flashes "Waiting for the book…". The bar waits `BAR_AFTER` already.
- "Queued · N requests ahead…" counts what it waits for (the queue's `ahead(job)`, as the phone's `queue.ahead`): a
  lane job, the lane's jobs before it; a queue job, every job before it and every lane job that runs or waits. With
  `lane=0`, every job before it, as now.
- The Journal's Now lists every running request, oldest first (feed.py:64 does already), then the queued, "Queued ·
  next" by place in their lane.
- **The corpus does not move**: the words stand, a one-lane queue's counts and ordinals are today's, and the history
  and the queue vectors are lane 0's. `CARACOLE_CORPUS=write` writes no change, and the phone's Status.kt,
  JobViews.kt, Feed.kt and JobQueue.kt stay. A word the builder finds must change moves the corpus and the phone's port
  in the same commit (AGENTS.md, "The phone agrees with the computer to the byte").

### 7. Tests that prove it

Test first; real processes where the lock is the subject, as test_commands_common.py:767 does.

- **Two lookups started together both move**: two scripted lane processes, each an interactive client to a recording
  transport that writes each request's start and end to a shared file. Both send their first request within a
  second, their requests alternate, and both end.
- **A site sees one request at a time**: from that record, no two requests to one provider overlap, and each starts
  `lookup_delay[0]` or more after the one before, whichever process sent it.
- **The hour holds for two**: `lookup_per_hour` 8, two lookups wanting 6 each: 8 sent in all.
- **One lookup's block stops the other**: its next request there is never sent; the streak grows by one.
- **Overrides after a turn**: one pins its song's tab; the other's index.html, written after, shows the pin.
- **A lookup asked while a long job runs starts at once** (tests/test_web_jobs.py, a fake runner): it runs and ends
  while a queue job still blocks; a queue job asked after it starts only once it has ended; a fourth lane job waits for
  a slot; a song's second job waits for its first.
- **Nothing but a lookup takes the lock between two turns**: a removal, and a command that isn't interactive, waiting
  while two lookups take turns, get it only once both have ended.
- **The nightly run still hands over**: test_commands_common.py:767 and :815 unchanged; handed to one lookup, it takes
  the lock back only once a second that came meanwhile has ended too.
- **A queue job hands over at its hand-over point and gets the lock back**, replacing test_commands_lock.py:494 ("hands
  it to no other"): `youtube --search`'s pause; and a nightly run that let it in doesn't keep the lock to its end.
- **A stop and a restart**: two running requests both interrupted, and read back so.
- **Cancel** of a lane job that waits for the book (with Q3).
- The corpus regenerated: no change.

### 8. The words that change, in the same commit as the code

- AGENTS.md:
  - *Jobs and requests*: "every change runs as a `caracole` command queued in jobs.py": in the queue, one at a time,
    or in the lookups' lane, up to `LANE` at once, started at once. Its Cancel sentence too, with Q3.
  - *A lookup never waits behind a whole nightly run*: "A process holding the lock as a lookup hands it to no other
    (`hand_over`), since the run waiting to take it back would take it first": part 2's rules.
  - *Bulk work hands the lock over*: "takes it back once the lookup is done": once the lane is empty and no lookup
    waits.
  - *`serve` never takes it*: "in a child process, one at a time (web/jobs.py)": one at a time in the queue, and up to
    `LANE` lookups beside it, which take turns with the lock.
  - *Either pace*, "One request at a time per provider (a synchronous client, and the lock below)", and *An
    interactive lookup*, "(`_common.lookup_policy`, counting the `events` of runs named `lookup:…`)": two lookups at
    once pass the lock between two requests, and count the hour again after each turn.
- Docstrings: web/jobs.py (:46-50), commands/_common.py (:15-26), get.py (:62-65).
- docs/usage.md: One caracole at a time (:1912-1962: two lookups take turns, and "Holding the lock as a lookup, such a
  command lets nothing else go first in its own pauses", :1960-1961, becomes: it lets a lookup go first there);
  `caracole get` (:652-653); caracole serve's request lines (:4650-4653: a lookup starts at once; Cancel) and the
  Journal (:4685: "the requests that run").

## Left to the builder

- Names: the lane file, `pass_turn`, `LANE`, `WAIT_SAID`; how a lane ticket is told apart and named by its time.
- Lane worker threads, or a thread a running lane job; how `CaracoleRunner` hands a job its own process.
- An audit of the lane commands for a value read before a request and written after it, which a turn could make
  stale (kv `lacuerda:search-failed`, `ug:link-failed`, ug/link.py's `known` at commands/ug.py:160): read it again
  after a turn, or read and write it in one.
- The song stage's waiting detail, "…; a fetch goes first at its next pause" (get.py:906-907), wrong behind a sync;
  the line reads only its start.

## Open questions for the owner

1. Three lookups at once, a fourth waiting for one to end? Proposed: yes, `LANE = 3`.
2. A lookup asked during a sync, an import, or a YouTube sheet's model run waits for it, minutes at worst, its line
   "Waiting for the book…". Accept that for now, the models without the lock a later step? Proposed: yes.
3. Cancel a lookup that runs but hasn't had the book yet, by ending a process that has done nothing, though "we never
   stop a command halfway"? Proposed: yes.
