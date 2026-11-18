# Lookups without a queue: Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A song asked for from the search box, a song's Fetch, a pasted UG link and the search box's one-request reads
start the moment they are asked for, beside caracole serve's queue, two or three at once, passing caracole's lock to
each other between two requests, so a site still gets one request at a time.

**Architecture:** Lane 6, one branch (`feat/lookup-lane`, worktree `../caracole-lookups`). Tasks 6.1–6.6 teach the lock
a lane (commands/_common.py: a shared flock that keeps everyone else out while lookups take turns, turns at a lookup's
pauses and between its stages, hand-overs to the lane from the queue's jobs) and put the lane's five commands in it;
tasks 6.7–6.9 give caracole serve's queue (web/jobs.py) a lane of `LANE` workers beside its one, decided from a
request's steps. No word the pages say moves, and the corpus does not either.

**Tech Stack:** Python 3.14 (fcntl flocks, threading, subprocess), pytest with pytest-xdist, Nix dev shells.

**Spec:** `docs/superpowers/specs/2026-11-18-lookups-without-a-queue-design.md` (approved by the owner on 2026-11-18,
its Q2 answered then: "do your propositions, that's rare of a case"), with the owner's decisions in
`.superpowers/sdd/lookup-lane/decisions.md` (the main checkout, local). Its part numbers ("part 2, rule 4") are cited
below.

## Global Constraints

- One request at a time per provider: only the lock's holder sends; a redirect is a request; each request comes after
  the pace's pause from the last one any caracole sent the site (kv `http:last_request:<provider>`).
- Two caracoles never write the library at once: only the lock's holder writes, and the lock changes hands only where
  nothing is half-written: never while `conn.in_transaction`, never inside a render, `write_pages` or a songbook's
  render (none has a pause).
- The lookup pace is unchanged: `lookup_delay` 0.125–0.375 s, `lookup_requests` 6 a song, `lookup_per_hour` 60 for
  every lookup together, `get.SHEETS_SHARE` (half) after the sheet, Megalobiz's `per_day` 900, LaCuerda's search
  `SEARCHES_PER_HOUR` 20. A lookup's run id stays `lookup:<time>` (`lookup_run_id`), so `lookup_requests_used` and the
  corpus's run ids stay.
- Blocks: one lookup's block stops the other before its next request there; `record_block` adds no strike for a
  cooldown begun after its caller started, `record_ok` clears none. Errors are never misses. A search asks no site.
  robots.txt and the LaCuerda and YouTube search gates: unchanged.
- Bulk work hands the lock to lookups alone; a `caracole-admin` command never gets it in a handoff, nor between two
  turns. `serve` never takes the lock: it runs more children, nothing else.
- Values: `LANE = 3`, `LANE_WAITING = 10`, the queue's `LIMIT = 20`, `WAIT_SAID = 1.0` s, `LANE_NAME =
  "caracole.lock.lane"`; as now `WAIT_POLL` 0.05 s, `TICKET_BEAT` 1 s, `TICKET_STALE` 5 s, `HANDOFF_SLICE` 0.25 s,
  `HANDOFF_TAKE` 10 s (bounding only a wait for a ticket nobody takes, never the lane's work).
- No schema change; nothing new in the library folder (the lane file and its tickets are in `state_dir`).
- The phone agrees to the byte: no word of web/status.py, web/outcome.py or web/feed.py moves; `JobQueue(lane=0)` is
  today's queue, its counts and ordinals, and the corpus's (tests/test_conformance_queue.py); `CARACOLE_CORPUS=write`
  writes no change; android/ is untouched (the phone keeps its one queue).
- Tests never make a live request (`httpx.MockTransport`, `_common.transport_for`); a test that starts another process
  is `@pytest.mark.slow`; a test waits for the state it needs (helpers/locks.py `waiting_for`, a log line), never a
  fixed time.
- Heavy imports stay inside commands: `test_registering_the_commands_imports_neither_the_matcher_nor_the_index` and
  `test_a_command_that_sends_no_request_imports_no_http_client` stay green (commands/_common.py imports no httpx at
  module level).
- docs/usage.md and AGENTS.md change with behaviour in the same commit, docstrings with their code;
  `ruff check --select E4,E7,E9,F src tests` clean, no reformatting of code not changed; the whole suite
  (`nix develop -c pytest -q`) before every commit.
- Conventional commits scoped by area (`feat(lock): …`, `feat(get): …`, `feat(serve): …`); no Claude or AI attribution
  anywhere (commits, code, docs).

## Review Focus

1. **A lane lookup killed or interrupted mid-turn** (SIGKILL, serve's `stop`, Ctrl-C while it waits to take the lock
   back): the lock, the lane flock and its ticket go with it, no record is written into a lock it doesn't hold, and the
   next lookup in the lane takes the lock within a second, the queue's caracole after the lane. Task 6.2
   (`test_a_lookup_killed_holding_the_lock_leaves_it_to_the_next_in_the_lane`,
   `test_a_turn_interrupted_as_it_waits_writes_nothing_and_leaves_no_ticket`).
2. **A dead or stale lane ticket at the head of the order** (its pid gone, or untouched past `TICKET_STALE`): passed
   over at once, or after 5 s at most, never waited for. Task 6.1
   (`test_lane_tickets_go_oldest_first_passing_over_a_dead_or_stale_one`).
3. **A turn asked inside a transaction or a savepoint, or by a caracole outside the lane** (a stage that opens one, a
   render's `between` calling `hand_over` in a lookup): no turn, no hand-over. Task 6.2
   (`test_no_turn_in_a_transaction_nor_outside_the_lane`).
4. **The hour or the day spent by the other lookup during a turn, below what this client sent:** its next request is
   never sent, one `budget` event, said as the hour's spent (and after the sheet as kept for sheets), the song owed
   its fetch. Task 6.4 (`test_after_a_turn_a_lookups_client_keeps_to_what_the_hour_and_the_day_leave`,
   `test_after_the_sheet_a_turn_keeps_the_reserve_for_sheets`).
5. **A lane lookup run in a process that goes on** (CliRunner, a test, a command that runs another): its lane flock is
   let go with its lock, so the next caracole of that process or another never waits for a lane it is not in. Task
   6.1 (`test_a_lookup_in_the_lane_takes_a_free_lock_at_once_and_leaves_the_lane_as_it_lets_go`).

## Where the lanes meet

Two redesigns run beside this lane: the library page (lane 1, stage 1c and on, in `../caracole-lane1`; lane 3b later,
card.js and card.css) and the sheet pages (lane 5, in `../caracole-lane5`).

1. **Lane 6 owns**: commands/_common.py (the lock, the clients), http.py (`PoliteClient._check_budget`,
   `answered_any`), get.py (its lock, its turns, its good run, the client's reserve), commands/ug.py `_read`,
   commands/lyrics.py `_lacuerda_artist`, `_lacuerda_search` and `_harptabs_artist`, web/jobs.py, commands/serve.py's
   queue, one function of web/jobs_routes.py (`_ahead`) and one line of web/feed.py (a queued request's place), and
   new tests/test_commands_lane.py and tests/helpers/lanes.py. The routes that queue (search_routes.py,
   library_routes.py, ug_link_routes.py, songbook_routes.py) need no change: the lane is decided in
   `JobQueue._submit_locked` from the steps, and each route's `QueueFull` words stand.
2. **Lane 6 does not edit** src/caracole/library_assets/, library_page.py, card.js or card.css (lanes 1 and 3b),
   src/caracole/viewer/ or render.py (lane 5), web/outcome.py or web/status.py (no word moves), android/.
3. **web/feed.py and web/jobs_routes.py** were lane 2's (merged, 139fcd18); no running lane lists them. Lane 6's edits
   there are task 6.9's few lines; a merge that meets another lane's change there keeps both.
4. **AGENTS.md and docs/usage.md** change in every lane: a merge conflict there keeps both sides' sentences. Lane 6's
   passages: AGENTS.md's Jobs and requests, Either pace, An interactive lookup, and One caracole at a time ("A lookup
   never waits behind a whole nightly run", "Bulk work hands the lock over", "`serve` never takes it"); usage.md's
   `caracole get`, One caracole at a time, and caracole serve's request lines and Journal.
5. **No crossing is planned.** The Journal's data and /jobs.json already carry every running request; requests.js and
   library.js draw each item they are given. If a browser shows the library page drawing two running requests wrongly,
   that is lane 1's code: the implementer names the case to the controller, and lane 6 edits nothing in
   library_assets/.
6. **The corpus**: lane 6 moves none. Lanes 1 and 5 regenerate it as they merge; task 6.10 merges main into the branch
   first and regenerates it after, expecting no change from lane 6.
7. **Merge order**: independent of the other lanes; lane 6 merges when 6.10's checks pass.

## Calls the planner made where the spec was silent (the owner may overrule)

- The lock's tests and the lane client's are a file of their own, tests/test_commands_lane.py (the lane at
  commands/_common.py's lock), importing `another_caracole` from test_commands_common.py; the processes they start are
  tests/helpers/lanes.py's scripts.
- A lane ticket is named `lane.<time.time_ns() as 20 digits>.<pid>` (`.<n>` after it on a clash), so names sort by
  when they were made; every other ticket keeps `<pid>.<n>`.
- `WAIT_SAID` holds back `on_wait` alone (the job's "Waiting for the book…"); the log's "Another caracole is running
  (…); it lets a lookup go first at its next pause, or between two songs." is said at once, as now (the tests that read
  it, test_commands_lock.py's `LOOKUP_WAITING`, stand).
- `exclusive(..., lane=True)` implies `interactive`; a lock taken while this process holds it keeps the outer one's
  kind (part 2).
- The lane runs on `LANE` worker threads (`caracole-lane-1` … `-3`) beside the queue's one.
- A lane command's good run is read from its own client (`PoliteClient.answered_any()`); `health.answered_any` stays
  for every other command, and for the phone's port.
- What follows the sheet keeps its share after a turn through the lane client's `reserve` (get.py sets it to
  `ceil(lookup_per_hour × SHEETS_SHARE)`), and the client's `kept_back` says when a turn's cut came from it, for
  get.py's words.
- The song stage's waiting words stand ("waiting for the book (…); a fetch goes first at its next pause"): the line
  reads only "waiting for the book", and test_get.py and the corpus's fixtures hold the rest.
- "Overrides after a turn" is tested on the `Overrides` that `write_pages` is given, index.html's source, rather than
  on the page's HTML.
- A queue job's hand-over is tested with a bulk-pace UG client under an interactive lock (as `fetch --song` holds
  one), standing for yt-dlp's pause: `make_youtube`'s pause is the same `_patient_sleep`.
- usage.md's One caracole at a time passage is rewritten once, in 6.6, when every lane command takes turns; AGENTS.md's
  rules move with each lock task.
- The audit (6.6): `lacuerda --search` checks its gate, sends its one request and records a failure in one turn (no
  turn before a client's first request); `ug --link`'s `known` decides only before its first request, and
  `record_failure` / `forget_failure` (kv `ug:link-failed`) come after its last, with no turn between; `lacuerda
  --artist` and `harptabs --artist` read nothing before a request that they write after it. Nothing else is read again.

## The lock, as tasks 6.1–6.4 leave it (commands/_common.py)

Files in `state_dir`:

- `caracole.lock` (`LOCK_NAME`): the lock, its holder's record `"<pid> <what>\n"`, as now.
- `caracole.lock.waiting/` (`WAITING_DIR`): a ticket for each caracole asked for now that waits. `_ticket_pid(name)`
  reads either name's pid; `lookups_waiting(cfg)` (any live ticket) and `lane_tickets(cfg)` (live lane tickets,
  oldest first) keep today's liveness: a gone pid dropped at once, untouched for `TICKET_STALE` not counted, for
  `TICKET_FORGOTTEN` deleted.
- `caracole.lock.handoff` (`HANDOFF_NAME`): the gate, as now.
- `caracole.lock.lane` (`LANE_NAME`, new): flocked `LOCK_SH` by a lane process from before it asks for the lock until
  it lets go of it (`_release` at depth 0 closes it); one that can't be opened is as the lock file is (`fail`, or the
  OSError with `fatal=False`). `_lane_empty(cfg)` tries `LOCK_EX | LOCK_NB` on a descriptor of
  its own and lets go at once; `_wait_lane_empty(cfg)` blocks on `LOCK_EX`, then lets go. A lane process never calls
  either: it would find itself there.

Process state: `_held` as now; `_as_lookup`, the locks taken as interactive or in the lane (now hand_over's rule, no
longer a refusal); `_lane: dict[Path, int]`, the lane file's descriptor by lock path.

**Waiting announced**, `_wait_announced(cfg, what, fd, *, lane=False, ticket=None, on_wait=None) -> None`:

```
ticket = ticket or _announce(cfg, what, lane=lane)
try:
    every WAIT_POLL:
        if not lane or lane_tickets(cfg)[:1] == [ticket]:      # a lane ticket tries only at the head of the lane
            if flock(fd, LOCK_EX | LOCK_NB) succeeds:
                if lane or _lane_empty(cfg): return
                flock(fd, LOCK_UN)                              # not the lane's, the lane not empty: let go at once
        on_wait(_holder(fd)), once, WAIT_SAID after the wait began
        touch the ticket every TICKET_BEAT (announced again if deleted)
finally: unlink the ticket
```

**Taking the lock**, `_acquire(cfg, what, *, fatal=True, interactive=False, lane=False, on_wait=None) -> Path`: held
already, the depth grows (the outer one's kind). Else:

- `lane`: join the lane (`LOCK_SH`, blocking: an exclusive holder only ever holds it for an instant); if a lane ticket
  waits or the lock is held, warn as now, then `_wait_announced(..., lane=True, on_wait=on_wait)`; else it has it.
- `interactive`: try the lock; had and `_lane_empty`, it has it; else let go, warn, `_wait_announced(..., lane=False,
  on_wait=on_wait)`.
- else `_take_outside_handoffs` as now, and then, holding the lock with the gate free: `if not _lane_empty(cfg)`: let
  go, say once (`Another caracole is running (…); waiting for it to finish.`), `_wait_lane_empty(cfg)`, start again.
- then the record, `_held`, `_as_lookup` (interactive or lane), `_lane`.

**A turn**, `pass_turn(cfg: Config, conn: sqlite3.Connection | None = None) -> bool` (part 2, rule 2):

```
not held, not in the lane, conn in a transaction, or no lane ticket waits: return False
record = pread(fd); ticket = _announce(cfg, what of the record, lane=True)   # behind every lane ticket waiting
flock(fd, LOCK_UN)
try: _wait_announced(cfg, what, fd, lane=True, ticket=ticket)
except BaseException: unlink the ticket; raise                               # holding nothing: no record written
write the record back; _handoffs += 1; return True
```

**Handing over**, `hand_over(cfg, conn=None) -> bool` (part 2, rule 4):

```
not held, in the lane (a lane process takes turns, never hands over), or conn in a transaction: return False
asked_now = lock in _as_lookup
nothing waiting (asked_now: no lane ticket; bulk: no ticket at all): return False
the gate: bulk, LOCK_EX blocking, as now; asked_now, LOCK_EX | LOCK_NB, going on without it when held (bulk's handoff
          holds it: it let this one in)
record = pread(fd); flock(fd, LOCK_UN)
asked_now: _wait_announced(cfg, what, fd)          # a ticket of its own: the lock again once the lane is empty
bulk:      loop:
               wait while lookups_waiting(cfg), HANDOFF_TAKE at most     # a ticket nobody takes
               _wait_lane_empty(cfg)                                     # the lane's work, however long
               flock(fd, LOCK_EX)                                        # blocking: last
               if _lane_empty(cfg): break
               flock(fd, LOCK_UN)                                        # a lookup came between: its turn first
           (as now, never left without the lock)
write the record back; close the gate; _handoffs += 1; return True
```

**A lane client**: `make_client(..., interactive=True)` in a lane process makes `_LockedClient(lane=True)`:

```
_pause(url):
    if lane and requests_made > 0: pass_turn(cfg, conn)          # never before its first request
    _after_a_lookup(url); super()._pause(url); _after_a_lookup(url)
_after_a_lookup(url), for bulk's clients and now the lane's, once handoffs() moved since it last looked:
    cooling: ProviderBlocked, no request (as now); the pause runs from the last request any caracole sent (as now)
    lane:  p = cfg.provider(provider); used = lookup_requests_used(conn, provider)
           hour = requests_made + max(0, p.lookup_per_hour - reserve - used)
           kept_back = kept_back or (reserve > 0 and hour < policy.budget)
           budget = min(policy.budget, hour)
           policy.per_day: budget = min(budget, requests_made + max(0, per_day - requests_today(conn, provider)))
           policy = replace(policy, budget=budget); _check_budget(url)  # BudgetExhausted, its one "budget" event
```

No deadlock: whatever holds the lock tries the gate and the lane without blocking and lets go before it waits; a lane
process holds the lane's flock while it waits, but polls; bulk work alone blocks holding a flock (the gate), once the
lane is empty.

## Tasks

### Task 6.1: The lane's flock and tickets; everyone else waits for an empty lane

**Files:**
- Modify: `src/caracole/commands/_common.py` (constants; `_announce`, `_wait_announced`, `lookups_waiting`, new
  `_ticket_pid`, `lane_tickets`, `_lane_empty`, `_wait_lane_empty`; `_acquire`, `_take_outside_handoffs`,
  `_release`, `exclusive`)
- Modify: `tests/test_commands_lock.py:483` (the fake `_acquire` takes `lane=False`)
- Modify: `AGENTS.md` (One caracole at a time, "A lookup never waits behind a whole nightly run": a bullet for the lane)
- Create: `tests/test_commands_lane.py`

**Interfaces:**
- Produces: `LANE_NAME`, `LANE_TICKET = "lane."`, `WAIT_SAID = 1.0`; `exclusive(cfg, what, *, fatal=True,
  interactive=False, lane=False, on_wait=None)`; `_acquire(..., lane=False, ...) -> Path`; `lane_tickets(cfg) ->
  list[Path]`; `_announce(cfg, what, *, lane=False) -> Path`; `_wait_announced(cfg, what, fd, *, lane=False,
  ticket=None, on_wait=None) -> None`; `_lane_empty(cfg) -> bool`; `_wait_lane_empty(cfg) -> None`; `_lane: dict[Path,
  int]`. All as "The lock" above says.

- [ ] **Step 1: The spec and this plan on main, and the worktree**

In the main checkout (its uncommitted improvements.md, android_port.md, run.sh and temp.sh left alone):

```bash
cd /home/dani/Projects/caracole
git switch main && git merge --no-ff design/lookup-lane -m "Merge branch 'design/lookup-lane': lookups without a queue, the design and its plan"
GH_TOKEN="$(gh auth token --user Danielhp95)" git push origin main
git worktree add ../caracole-lookups -b feat/lookup-lane main
```

Expected: a docs-only merge; every later path is relative to `/home/dani/Projects/caracole-lookups`.

- [ ] **Step 2: Write the failing tests** in `tests/test_commands_lane.py` (module docstring: "The lane at caracole's
  lock (commands/_common.py): lookups taking turns, and everyone else waiting for an empty lane.")

```python
def in_the_lane(cfg) -> int:
    """A lookup in the lane, as another process holds it: a descriptor of the lane file, flocked shared."""

def test_a_lookup_in_the_lane_takes_a_free_lock_at_once_and_leaves_the_lane_as_it_lets_go(cfg):
    lane = cfg.state_dir / _common.LANE_NAME
    with exclusive(cfg, "get Oasis - Wonderwall", lane=True):
        probe = os.open(lane, os.O_RDWR)
        with pytest.raises(BlockingIOError):
            fcntl.flock(probe, fcntl.LOCK_EX | fcntl.LOCK_NB)  # a lookup is in the lane
        os.close(probe)
    probe = os.open(lane, os.O_RDWR)
    fcntl.flock(probe, fcntl.LOCK_EX | fcntl.LOCK_NB)  # empty again: nothing of it left in this process
    os.close(probe)

@pytest.mark.parametrize("asked_now", [False, True], ids=["bulk", "asked now"])
def test_a_caracole_outside_the_lane_waits_for_it_to_empty_even_with_the_lock_free(cfg, asked_now):
    lane = in_the_lane(cfg)
    took = threading.Event()
    thread = threading.Thread(target=..., daemon=True)  # with exclusive(cfg, "remove Radiohead - Creep --yes",
    thread.start()                                       #      interactive=asked_now): took.set()
    assert waiting_for(cfg.state_dir / _common.LANE_NAME, thread.is_alive)  # blocked on the lane, or its ticket
    assert not took.is_set()
    os.close(lane)
    assert took.wait(5)

def test_lane_tickets_go_oldest_first_passing_over_a_dead_or_stale_one(cfg):
    # tickets in WAITING_DIR: lane.<1>.999999999 (no such process), lane.<2>.<own pid> touched TICKET_STALE + 1 s ago,
    # lane.<3>.<own pid>, lane.<4>.<own pid>.1, and <own pid>.0 (asked now, not the lane's)
    assert [t.name for t in _common.lane_tickets(cfg)] == [f"lane.{3:020d}.{pid}", f"lane.{4:020d}.{pid}.1"]
    assert not (folder / f"lane.{1:020d}.999999999").exists()  # its process gone: dropped
    assert _common.lookups_waiting(cfg)  # a lane ticket is a lookup waiting, for bulk work's pauses

def test_a_waiting_lookup_tells_whom_it_waits_for_only_once_it_has_waited_a_moment(cfg, monkeypatch):
    monkeypatch.setattr(_common, "WAIT_SAID", 0.3)
    told: list[str] = []
    # with another_caracole(cfg): a thread in exclusive(cfg, "get A - B", lane=True, on_wait=told.append) until its
    # ticket shows, then let go at once (a turn's moment): joined, told == []
    # again, held until told says something (5 s at most): told == ["pid 4242: run"], then let go and joined

def test_a_lock_taken_inside_the_lane_keeps_its_kind(cfg):
    # in a thread, joined within 5 s: with exclusive(cfg, "get A - B", lane=True): with exclusive(cfg, "ug requests"):
    # done.set() — make_client's lock never waits for a lane its own process is in
    assert done.wait(5)
```

- [ ] **Step 3: Run them to see them fail**

Run: `nix develop -c pytest -q tests/test_commands_lane.py`
Expected: FAIL (`exclusive() got an unexpected keyword argument 'lane'`, no `LANE_NAME`, no `lane_tickets`).

- [ ] **Step 4: Implement the lane in `src/caracole/commands/_common.py`**, as "The lock" says: the lane file,
  the tickets and their names, `_wait_announced` with `lane`, `ticket` and `on_wait` (told once after `WAIT_SAID`),
  `_acquire`'s three ways, `_take_outside_handoffs`' lane check, `_release` closing the lane's descriptor at depth 0,
  `exclusive(..., lane=False)` passing `interactive=interactive or lane`. `lookups_waiting` parses a lane ticket's pid
  (`_ticket_pid`), so a gone one is dropped at once. The fake `_acquire` in test_commands_lock.py:483 takes `lane=False`.
  The module docstring's "One caracole at a time" paragraph gains the lane: "Lookups take the lock in a lane of their
  own (`exclusive(..., lane=True)`, a shared flock of `caracole.lock.lane`): while one is there, no other caracole
  takes the lock."

- [ ] **Step 5: Run them to see them pass, then the lock's other tests**

Run: `nix develop -c pytest -q tests/test_commands_lane.py tests/test_commands_common.py tests/test_commands_lock.py tests/test_get.py`
Expected: PASS (the handoff tests at test_commands_common.py:767 and :815 unchanged).

- [ ] **Step 6: AGENTS.md**: under "A lookup never waits behind a whole nightly run, and still never writes beside it",
  a bullet: lookups take the lock in the lane (`exclusive(..., lane=True)`, a shared flock of
  `state_dir/caracole.lock.lane` from before they ask for the lock until they let go of it, tickets named
  `lane.<time>.<pid>`, oldest first); a caracole that isn't in the lane, once it has the lock, lets go of it while the
  lane holds anyone and waits for it to empty, holding nothing; `on_wait` is told after `WAIT_SAID` (1 s).

- [ ] **Step 7: Commit**

```bash
nix develop -c pytest -q
git add src/caracole/commands/_common.py tests/test_commands_lane.py tests/test_commands_lock.py AGENTS.md
git commit -m "feat(lock): a lane for lookups, which keeps every other caracole from the lock while it holds one"
```

### Task 6.2: Turns between the lane's lookups

**Files:**
- Modify: `src/caracole/commands/_common.py` (`pass_turn`)
- Create: `tests/helpers/lanes.py`
- Modify: `tests/test_commands_lane.py`, `AGENTS.md`

**Interfaces:**
- Consumes: 6.1's `lane_tickets`, `_announce(lane=True)`, `_wait_announced(ticket=)`, `_lane`.
- Produces: `pass_turn(cfg: Config, conn: sqlite3.Connection | None = None) -> bool` (a turn counts in `handoffs()`);
  tests/helpers/lanes.py: `config_file(cfg, tmp_path, ug: str = "") -> Path` (a caracole.toml of `cfg`'s three
  folders, with `ug`'s lines under `[providers.ug]`), `start(script, config, log, *args, go: Path | None = None) ->
  subprocess.Popen` (PYTHONPATH by `conftest.subprocess_pythonpath`; a script writes `ready <name> <t>`, then waits for
  `go` to exist, when given, before it asks for the lock), `records(log) -> list[tuple[str, str, float, list[str]]]`
  (each line's word, name, `time.time()` and the rest, in the order written), `wait_for(log, word, name, timeout=30) ->
  float`, and the scripts `TURNS` (name, turns: in the lane, each turn writes `turn <name> <t> <i>`, sleeps 0.1 s and
  calls `pass_turn(cfg)`; then `end <name> <t>`), `HOLD` (name: in the lane, writes `holding <name> <t>`, sleeps 60 s)
  and `WAITER` (name, kind: `exclusive(cfg, f"remove {name}", interactive=kind == "asked")`, then `got <name> <t>`).

- [ ] **Step 1: Write the failing tests** in `tests/test_commands_lane.py`

```python
@pytest.mark.slow
def test_two_lookups_in_the_lane_take_turns_at_the_lock(cfg, tmp_path):
    # TURNS a and b, 6 turns each, started together (go once both are ready)
    turns = [r for r in records(log) if r[0] == "turn"]
    assert {r[1] for r in turns[:2]} == {"a", "b"} and turns[1][2] - go_at < 1.0  # both move at once
    assert sum(x[1] != y[1] for x, y in zip(turns, turns[1:])) >= 5  # by turns, not one after the other
    assert a.wait(30) == 0 and b.wait(30) == 0

@pytest.mark.slow
def test_nothing_but_a_lookup_takes_the_lock_between_two_turns(cfg, tmp_path):
    # TURNS a and b, 10 turns each; once both have taken a turn, WAITER bulk and WAITER asked
    lane_over = max(t for word, _, t, _ in records(log) if word == "end")
    assert all(t > lane_over for word, _, t, _ in records(log) if word == "got")

@pytest.mark.slow
def test_a_lookup_killed_holding_the_lock_leaves_it_to_the_next_in_the_lane(cfg, tmp_path):
    # HOLD a; once holding: TURNS b (2 turns) and WAITER bulk, both seen waiting (waiting_for); then a.kill()
    assert wait_for(log, "turn", "b") - killed_at < 2.0
    assert wait_for(log, "got", "bulk") > wait_for(log, "end", "b")

def test_no_turn_in_a_transaction_nor_outside_the_lane(cfg, conn):
    # a lane ticket of this process, fresh, in WAITING_DIR: a lookup waits
    with exclusive(cfg, "get A - B", lane=True):
        conn.execute("BEGIN")
        assert not _common.pass_turn(cfg, conn)
        conn.execute("ROLLBACK")
        with db.savepoint(conn, "half"):
            assert not _common.pass_turn(cfg, conn)
        assert not _common.hand_over(cfg, conn)  # a lane process takes turns, never hands over (a render's between)
    with exclusive(cfg, "run"):
        assert not _common.pass_turn(cfg, conn)  # bulk work hands over, it has no turns
    assert not _common.pass_turn(cfg)  # nothing held

def test_a_turn_interrupted_as_it_waits_writes_nothing_and_leaves_no_ticket(cfg, monkeypatch):
    # a fresh lane ticket of this process; _wait_announced raises KeyboardInterrupt
    with pytest.raises(KeyboardInterrupt), exclusive(cfg, "get A - B", lane=True):
        _common.pass_turn(cfg)
    assert [t for t in _common.lane_tickets(cfg) if t.name != planted.name] == []  # its own ticket gone
    # and a thread's exclusive(cfg, "remove A - B --yes") takes the lock within 5 s
```

- [ ] **Step 2: Run them to see them fail**

Run: `nix develop -c pytest -q -n 0 tests/test_commands_lane.py -k "turn or killed"`
Expected: FAIL (`module 'caracole.commands._common' has no attribute 'pass_turn'`; no helpers.lanes).

- [ ] **Step 3: Implement `pass_turn` in `src/caracole/commands/_common.py`** as "The lock" says (its docstring: "Let
  the next lookup in the lane have caracole's lock now, and take it back in turn; True when one did. Only a lane
  process calls it, holding the lock, at a turn point, in no transaction: before a request but its client's first, and
  between two stages."), and tests/helpers/lanes.py as its Interfaces say (docstring: "Caracoles in processes of their
  own, taking caracole's lock in the lane or waiting for it, each writing what it did, timed, to a log: for
  tests/test_commands_lane.py.").

- [ ] **Step 4: Run them to see them pass**

Run: `nix develop -c pytest -q tests/test_commands_lane.py tests/test_commands_common.py`
Expected: PASS.

- [ ] **Step 5: AGENTS.md**: the lane bullet of 6.1 gains its turns: a lane process holding the lock, at a turn point
  (a lane client's pause before each request but its first, and between two of a lookup's stages), in no transaction,
  when a lane ticket waits, writes its own (the newest), lets go, takes the lock back when its ticket heads the lane,
  and counts a handoff (`pass_turn`), so whatever reads again after a handoff reads again after a turn.

- [ ] **Step 6: Commit**

```bash
nix develop -c pytest -q
git add src/caracole/commands/_common.py tests/helpers/lanes.py tests/test_commands_lane.py AGENTS.md
git commit -m "feat(lock): lookups in the lane take turns with caracole's lock"
```

### Task 6.3: What the owner asked for now hands the lock to the lane; bulk work takes it back once the lane is empty

**Files:**
- Modify: `src/caracole/commands/_common.py` (`hand_over`; the `_as_lookup` comment)
- Modify: `tests/helpers/lanes.py` (`BULK`, `QUEUE_JOB`), `tests/test_commands_lane.py`
- Modify: `tests/test_commands_lock.py:494` (replaced)
- Modify: `AGENTS.md`

**Interfaces:**
- Consumes: 6.1's `_lane_empty`, `_wait_lane_empty`, `_wait_announced`; 6.2's helpers.
- Produces: `hand_over(cfg, conn=None) -> bool` as "The lock" says (signature unchanged). Scripts: `BULK` (name, count:
  `exclusive(cfg, "run")` and `make_client(cfg, conn, "ug", "2026-10-19T03:30:00Z")`, `count` requests) and
  `QUEUE_JOB` (name, count: `exclusive(cfg, f"fetch --song {name}", interactive=True)` and the same bulk-pace client),
  each through a recording transport (`start <name> <t> <url>`, `end <name> <t> <status>` around each request, 200
  "ok", 403 for a URL ending in `/block`) and ending `done <name> <t> <client.handoffs>`.

- [ ] **Step 1: Write the failing tests**

In tests/test_commands_lock.py, `test_a_command_holding_the_lock_as_a_lookup_hands_it_to_no_other` becomes:

```python
def test_a_command_holding_the_lock_as_asked_now_hands_it_to_the_lane_alone(tmp_path, config, monkeypatch):
    cfg = load_config(config, env={})
    monkeypatch.setattr(_common, "lookups_waiting", lambda cfg: True)
    monkeypatch.setattr(_common, "lane_tickets", lambda cfg: [])
    with _common.exclusive(cfg, "fetch", interactive=True):
        assert not _common.hand_over(cfg)  # a ticket asked for now, not the lane's: it waits for this one's end
    with _common.exclusive(cfg, "fetch"):
        monkeypatch.setattr(_common, "HANDOFF_TAKE", 0.05)
        assert _common.hand_over(cfg)  # bulk work hands it to any lookup, as before
```

In tests/test_commands_lane.py (config: `config_file(cfg, tmp_path, "delay = [1.5, 1.5]")`):

```python
@pytest.mark.slow
def test_a_queue_job_lets_a_lookup_go_first_in_its_pause_and_gets_the_lock_back(cfg, tmp_path):
    # QUEUE_JOB q (2 requests); once q's first request ended: TURNS l (1 turn)
    assert turn_l < q_second_start  # in q's pause, not at its end
    assert q_second_start - end_l >= 1.4  # q's pause starts again, whole, after the lookup
    assert q_done_handoffs == 1

@pytest.mark.slow
def test_the_nightly_run_takes_the_lock_back_only_once_the_lane_is_empty(cfg, tmp_path):
    # BULK r (2 requests); once r's first ended: TURNS a (6 turns); once a's first turn: TURNS b (2 turns)
    assert r_second_start > max(end_a, end_b)
    assert r_done_handoffs == 1  # one handoff, the lane's two lookups in it

@pytest.mark.slow
def test_a_nightly_run_that_let_a_queue_job_in_gives_it_back_at_its_next_pause(cfg, tmp_path):
    # BULK r (3 requests); once r's first ended: QUEUE_JOB q (2 requests); once q's first ended: TURNS l (1 turn)
    assert turn_l < q_second_start < r_second_start  # q handed to the lane, then had it back before the run did
```

- [ ] **Step 2: Run them to see them fail**

Run: `nix develop -c pytest -q -n 0 tests/test_commands_lane.py -k "queue_job or nightly" tests/test_commands_lock.py -k asked_now`
Expected: FAIL (an interactive holder hands over to no one; the queue job keeps the lock to its end).

- [ ] **Step 3: Implement `hand_over`** as "The lock" says: no refusal for `_as_lookup` (its comment: "taken as
  interactive or in the lane: hands the lock to lane lookups alone"), the gate tried without waiting by an interactive
  holder, its wait announced with a ticket of its own, bulk work's loop that takes the lock back last, once the lane is
  empty. Its docstring says both ways and that a lane process never hands over.

- [ ] **Step 4: Run them to see them pass, with the handoff tests that stay**

Run: `nix develop -c pytest -q tests/test_commands_lane.py tests/test_commands_common.py tests/test_commands_lock.py tests/test_web_jobs.py -k "hand or lane or nightly or lookup_queued"`
Expected: PASS, test_commands_common.py's `test_the_nightly_run_hands_the_lock_to_a_lookup_during_its_pause` and
`..._alone_never_to_another_command_waiting` unchanged.

- [ ] **Step 5: AGENTS.md**: "A lookup never waits behind…": "A process holding the lock as a lookup hands it to no
  other (`hand_over`), since the run waiting to take it back would take it first" becomes: a process holding the lock
  as asked for now hands it to the lane's lookups alone, at its hand-over points (a yt-dlp pause, a YouTube sheet before
  its models, `fetch --song`'s pauses), taking the gate only if it is free, and waits with a ticket of its own to take
  it back once the lane is empty, so bulk work that let it in gives it back at its next pause. "Bulk work hands the lock
  over": "takes it back once the lookup is done" becomes once the lane is empty and no lookup waits (`HANDOFF_TAKE`
  bounding only a ticket nobody takes).

- [ ] **Step 6: Commit**

```bash
nix develop -c pytest -q
git add src/caracole/commands/_common.py tests/helpers/lanes.py tests/test_commands_lane.py tests/test_commands_lock.py AGENTS.md
git commit -m "feat(lock): what the owner asked for now lets the lane's lookups go first, and bulk work waits for the lane"
```

### Task 6.4: A lookup's client takes turns and keeps the hour after one

**Files:**
- Modify: `src/caracole/http.py` (`PoliteClient._check_budget`, `answered_any`, its count of failed requests)
- Modify: `src/caracole/commands/_common.py` (`_LockedClient`: `lane`, `reserve`, `kept_back`, `_pause`,
  `_after_a_lookup`; `make_client` passes `lane`)
- Modify: `tests/helpers/lanes.py` (`LOOKUP`), `tests/test_commands_lane.py`, `tests/test_http.py`, `AGENTS.md`

**Interfaces:**
- Consumes: 6.2's `pass_turn`.
- Produces: `PoliteClient._check_budget(url: str) -> None` (`_claim`'s budget check, its one `budget` event, raising
  `BudgetExhausted`; `_claim` calls it); `PoliteClient.answered_any() -> bool` (more requests sent than answered with
  an error or a block, as `health.answered_any` counts a run's); `_LockedClient(..., lane: bool = False)` with
  `reserve: int = 0` and `kept_back: bool = False` (made `lane=interactive and lock in _lane` by `make_client`). Script
  `LOOKUP` (name, count): in the lane, `make_client(cfg, conn, "ug", lookup_run_id(now), interactive=True)`, `count`
  requests through the recording transport, then `done`, `spent` (BudgetExhausted) or `blocked` (ProviderBlocked,
  recorded by `record_block(conn, "ug", now, str(e))` as get.py's asking does), each `<word> <name> <t>
  <requests_made>`.

- [ ] **Step 1: Write the failing tests**

tests/test_http.py:

```python
def test_a_client_says_whether_its_site_answered_any_of_its_requests(tmp_path):
    # MockTransport: one 200 → True; two 502 → False; none sent → False
```

tests/test_commands_lane.py:

```python
def test_a_lookups_client_passes_no_turn_before_its_first_request(cfg, conn, monkeypatch):
    # in the lane, an interactive ug client, two requests; pass_turn faked (False), recording how many requests the
    # transport had seen when it was asked
    assert turns == [1]  # one turn, before the second: none as the client is made, nor before its first

@pytest.mark.parametrize("provider, lookups, others", [("ug", 7, 0), ("megalobiz", 0, 899)])
def test_after_a_turn_a_lookups_client_keeps_to_what_the_hour_and_the_day_leave(cfg, conn, monkeypatch, provider,
                                                                                lookups, others):
    # lookup_per_hour 8 for ug; one request sent; the turn (pass_turn faked, _handoffs bumped, True) adds `lookups`
    # events of another lookup's run (lookup:…) and `others` of a nightly run's, now
    with pytest.raises(BudgetExhausted):
        client.get(second_url)
    assert transport_calls == 1
    assert budget_events(conn, provider) == 1

def test_after_the_sheet_a_turn_keeps_the_reserve_for_sheets(cfg, conn, monkeypatch):
    # lookup_per_hour 8, client.reserve = 4; one request; the turn adds 3 of another lookup's
    with pytest.raises(BudgetExhausted):
        client.get(second_url)
    assert client.kept_back

@pytest.mark.slow
def test_two_lookups_requests_alternate_and_a_site_sees_one_at_a_time(cfg, tmp_path):
    # ug: lookup_delay = [0.2, 0.2]; LOOKUP a and b, 4 requests each, started together
    starts, ends = ...  # every request, in the order it started
    assert abs(first_start["a"] - first_start["b"]) < 1.0
    assert sum(x.name != y.name for x, y in zip(starts, starts[1:])) >= 3
    assert all(s.t >= e.t for s, e in zip(starts[1:], ends))  # none overlaps the one before
    assert all(y.t - x.t >= 0.2 - 0.01 for x, y in zip(starts, starts[1:]))  # whichever process sent it
    assert a.wait(30) == 0 and b.wait(30) == 0

@pytest.mark.slow
def test_the_hour_holds_for_two_lookups(cfg, tmp_path):
    # ug: lookup_per_hour = 8, lookup_delay = [0.1, 0.1]; LOOKUP a and b, 6 requests each
    assert len(starts) == 8
    assert {word for word, *_ in last_lines} == {"spent"}

@pytest.mark.slow
def test_one_lookups_block_stops_the_other_before_its_next_request(cfg, tmp_path):
    # LOOKUP a's second URL ends in /block (403); LOOKUP b, 3 requests
    assert [s.name for s in starts] == ["a", "b", "a"]  # b's second never sent
    assert get_state(conn, "ug").strikes == 1  # one block, one strike
```

- [ ] **Step 2: Run them to see them fail**

Run: `nix develop -c pytest -q -n 0 tests/test_commands_lane.py -k "client or hour or alternate or block" tests/test_http.py -k answered`
Expected: FAIL (no `answered_any`, no turns in a lookup's pauses, the hour read once).

- [ ] **Step 3: Implement** `_check_budget` and `answered_any` in http.py (a failed request counted in `_event` for
  `error` and `blocked`), and the lane client in commands/_common.py as "The lock" says. `make_client`'s docstring:
  a lookup's client in the lane passes a turn before each request but its first, and after one keeps what the other
  left: its block, its last request's pause, the hour, the day and its reserve.

- [ ] **Step 4: Run them to see them pass**

Run: `nix develop -c pytest -q tests/test_commands_lane.py tests/test_http.py tests/test_commands_common.py tests/test_get.py`
Expected: PASS.

- [ ] **Step 5: AGENTS.md**: Either pace, "One request at a time per provider (a synchronous client, and the lock
  below)": "; two lookups at once pass the lock between two requests". An interactive lookup, "(`_common.lookup_policy`,
  counting the `events` of runs named `lookup:…`)": "read again after each turn (`_LockedClient` in the lane: the
  hour, the day, and after the sheet its `reserve`)".

- [ ] **Step 6: Commit**

```bash
nix develop -c pytest -q
git add src/caracole/http.py src/caracole/commands/_common.py tests/helpers/lanes.py tests/test_commands_lane.py tests/test_http.py AGENTS.md
git commit -m "feat(lock): a lookup's client passes a turn before each request, and keeps the hour after one"
```

### Task 6.5: `caracole get` in the lane

**Files:**
- Modify: `src/caracole/get.py` (`_Lookup.run`, `stage`, a new `_turn`, `after_the_sheet`, `asking`; the module
  docstring :62-65)
- Modify: `tests/test_get.py`, `tests/test_commands_lock.py:477-491`
- Modify: `docs/usage.md` (`caracole get`: "A nightly run that holds caracole's lock lets the lookup go first…")

**Interfaces:**
- Consumes: 6.1's `exclusive(lane=True)`, 6.2's `pass_turn`, `handoffs`, `overrides_since`, 6.4's
  `answered_any()`, `reserve`, `kept_back`.
- Produces: `_Lookup.handed: int` (the handoffs its overrides and song were read at); `_Lookup._turn() -> None`.

- [ ] **Step 1: Write the failing tests**

tests/test_commands_lock.py: the fake `_acquire` records `(what, interactive, lane)`; a `LANE` list beside
`ASKED_NOW` and `BULK`, `[("get", "Radiohead", "Creep")]` for now (6.6 adds the rest), and
`test_what_the_owner_asked_for_just_now_takes_the_lock_as_a_lookup_and_bulk_work_doesnt` becomes:

```python
@pytest.mark.parametrize("args", [*LANE, *ASKED_NOW, *BULK], ids=" ".join)
def test_lookups_take_the_lock_in_the_lane_what_the_owner_asked_for_now_as_a_lookup_and_bulk_work_neither(..., args):
    assert took[0][1:] == ((True, True) if args in LANE else (True, False) if args in ASKED_NOW else (False, False))
```

tests/test_get.py:

```python
def test_a_lookup_passes_a_turn_before_each_stage_never_inside_one(cfg, conn, sites, monkeypatch):
    # pass_turn recorded beside the Progress events, with conn.in_transaction
    for name in ("match", "sheet", "pdf", "lyrics", "ug", "lacuerda", "gtptabs", "harptabs", "gametabs", "pages",
                 "songbooks"):
        assert heard[heard.index(("running", name)) - 1] == "turn"
    assert not any(in_transaction for in_transaction in turns)

def test_after_a_turn_a_lookup_reads_overrides_and_its_song_again(cfg, conn, sites, monkeypatch):
    # the first turn (faked: _handoffs bumped, True) pins Oasis - Wonderwall's tab 4169 in overrides.toml, as the
    # other lookup would, and marks this song ug_dirty; _Lookup.match spied, caracole.todo.write_pages captured
    assert seen_dirty == [True]  # the match stage read the song's row again
    assert written.pin[override_key("Oasis - Wonderwall")] == (4169,)  # index.html made from overrides as they are

def test_a_lookups_good_run_is_its_own_clients_not_another_lookups_of_the_same_second(cfg, conn, sites):
    # 50 "error" events for ug under lookup_run_id(NOW), another lookup's of that second; ug at 1 strike, its
    # cooldown over; the lookup's own requests answered
    assert get_state(conn, "ug").strikes == 0

def test_what_follows_the_sheet_keeps_half_the_hour_for_sheets_through_a_turn(cfg, conn, sites, monkeypatch):
    # make_client wrapped to keep each client
    assert clients["ug"].reserve == math.ceil(cfg.provider("ug").lookup_per_hour * SHEETS_SHARE)
```

- [ ] **Step 2: Run them to see them fail**

Run: `nix develop -c pytest -q tests/test_get.py -k "turn or good_run or half" tests/test_commands_lock.py -k lane`
Expected: FAIL (get takes the lock as interactive, no turn, its good run read by run id).

- [ ] **Step 3: Implement in `src/caracole/get.py`**:
  - `run`: `exclusive(self.cfg, f"get {self.request.display}", lane=True, on_wait=waiting)`; `self.handed =
    handoffs()` once overrides.toml is read.
  - `stage(name, run)`: `self._turn()` first. `_turn()`: `pass_turn(self.cfg, self.conn)`; once `handoffs() !=
    self.handed`, `self.overrides = overrides_since(self.cfg, self.overrides, self.handed)`, the song read again
    (`get_song(self.conn, self.song.id)`), `self.handed = handoffs()` (a turn in a client's pause is read at the next
    stage too).
  - the good run: `client.answered_any()` in place of `answered_any(conn, self.run_id, provider, client.requests_made)`.
  - `after_the_sheet`'s `within`: `client.reserve = math.ceil(p.lookup_per_hour * SHEETS_SHARE)` before the cut.
  - `asking`'s `BudgetExhausted`: kept for sheets when `e.provider in self.kept_for_sheets or getattr(client,
    "kept_back", False)` (test_conformance_lookup.py's FakeClient has neither: the corpus doesn't move).
  - the docstring's "The lookup holds caracole's lock throughout, …": it takes the lock in the lane, and passes a turn
    to another lookup before each request but a client's first and between two stages, reading overrides.toml and its
    song again after one.

- [ ] **Step 4: Run them to see them pass**

Run: `nix develop -c pytest -q tests/test_get.py tests/test_commands_lock.py tests/test_conformance_lookup.py`
Expected: PASS, the corpus check unchanged.

- [ ] **Step 5: docs/usage.md**, `caracole get`: after "A nightly run that holds caracole's lock lets the lookup go
  first at its next pause": "Two lookups at once take turns with the lock, a request or a stage each, so both move and
  each site still gets one request at a time; the hour's lookups are counted again after each turn."

- [ ] **Step 6: Commit**

```bash
nix develop -c pytest -q
git add src/caracole/get.py tests/test_get.py tests/test_commands_lock.py docs/usage.md
git commit -m "feat(get): a lookup takes the lock in the lane and passes turns between its stages"
```

### Task 6.6: The lane's other commands, and what a turn could leave stale

**Files:**
- Modify: `src/caracole/commands/ug.py` (`_read`), `src/caracole/commands/lyrics.py` (`_lacuerda_artist`,
  `_lacuerda_search`, `_harptabs_artist`), `src/caracole/commands/_common.py` (module docstring :1-26)
- Modify: `tests/test_commands_lock.py` (`LANE`), `tests/test_commands_ug.py`, `tests/test_commands_lyrics.py`
- Modify: `docs/usage.md` (One caracole at a time), `AGENTS.md`

**Interfaces:**
- Consumes: 6.1's `exclusive(lane=True)`, 6.2's `pass_turn`, `handoffs`, `overrides_since`, 6.4's `answered_any()`.
- Produces: nothing new.

- [ ] **Step 1: Write the failing tests**

tests/test_commands_lock.py: `LANE` gains `("ug", f"--link={TAB_URL}", "--progress")`, `("lacuerda",
"--search=calamaro flaca", "--progress")`, `("lacuerda", "--artist=andres-calamaro")` and `("harptabs",
"--artist=Radiohead")`.

tests/test_commands_ug.py:

```python
def test_a_ug_link_takes_a_turn_between_its_tab_page_and_its_artists_lists(..., monkeypatch):
    # pass_turn recorded beside the --progress lines; overrides_since spied
    assert said[said.index("turn") - 1] == ("tab", "done") and said[said.index("turn") + 1] == ("artist", "running")
    assert not turned_in_a_transaction and overrides_read_again == 1

def test_a_ug_links_good_run_is_its_own_clients(...):
    # 50 "error" events for ug under the same second's lookup run id; ug at 1 strike, its cooldown over
    assert get_state(conn, "ug").strikes == 0
```

tests/test_commands_lyrics.py:

```python
def test_a_lacuerda_search_checks_its_gate_and_sends_in_one_turn(..., monkeypatch):
    assert turns == [] and len(sites.lacuerda_asked()) == 1  # its one request, its client's first: no turn

def test_a_lacuerda_artist_pages_good_run_is_its_own_clients(...):
    # 50 "error" events for lacuerda under the same second's lookup run id
    assert get_state(conn, "lacuerda").strikes == 0
```

- [ ] **Step 2: Run them to see them fail**

Run: `nix develop -c pytest -q tests/test_commands_lock.py -k lane tests/test_commands_ug.py -k "turn or good_run" tests/test_commands_lyrics.py -k "one_turn or good_run"`
Expected: FAIL.

- [ ] **Step 3: Implement**: each of the four takes `exclusive(..., lane=True)` and records its good run by
  `client.answered_any()`. In `_read`, as the artist stage starts after a tab's (the `stage` callback given `("artist",
  "running")` for a tab's link): `handed = handoffs()`, `pass_turn(cfg, conn)`, `ctx.overrides =
  overrides_since(cfg, ctx.overrides, handed)`. commands/_common.py's docstring: the interactive lookups (`get`, `ug
  --link`, `lacuerda --artist` and `--search`, `harptabs --artist`) take the lock in the lane and take turns there.

- [ ] **Step 4: The audit**: in the four commands and get.py's stages, every value read before a request and written
  after it (`kv_get`, `get_state`, `known`, `asked`, `failed`, `searches_used`). Verdicts, as "Calls" says: `lacuerda
  --search` one turn (pinned by its test above); `ug --link`'s `known` decides only before its first request,
  `record_failure` and `forget_failure` come after its last with no turn between; `lacuerda --artist` and `harptabs
  --artist` nothing. A value the audit finds otherwise is read again after a turn or read and written in one turn, with
  a test here naming it.

- [ ] **Step 5: Run the tests to see them pass**

Run: `nix develop -c pytest -q tests/test_commands_lock.py tests/test_commands_ug.py tests/test_commands_lyrics.py tests/test_get.py`
Expected: PASS.

- [ ] **Step 6: docs/usage.md**, One caracole at a time, rewritten where the lane changes it: lookups (`get`, `ug
  --link`, `lacuerda --search` and `--artist`, `harptabs --artist`) take turns with the lock, a request or a stage
  each, and while one runs or waits no other caracole takes the lock, not even between two turns
  (`caracole.lock.lane` in the state folder); "Holding the lock as a lookup, such a command lets nothing else go first
  in its own pauses" becomes: such a command lets a lookup go first there (a yt-dlp pause, a YouTube sheet before its
  models, `fetch --song`'s pauses), and gets the lock back once the lookups are done; a lookup still waits for a sync,
  an import, an index merge or a YouTube sheet's models (the owner's choice of 2026-11-18). AGENTS.md's "A lookup never
  waits…" names the five commands.

- [ ] **Step 7: Commit**

```bash
nix develop -c pytest -q
git add src/caracole/commands/ug.py src/caracole/commands/lyrics.py src/caracole/commands/_common.py tests/test_commands_lock.py tests/test_commands_ug.py tests/test_commands_lyrics.py docs/usage.md AGENTS.md
git commit -m "feat(lock): a pasted UG link, LaCuerda's search and an artist's page take turns in the lane too"
```

### Task 6.7: Which requests go to the lane, and its room

**Files:**
- Modify: `src/caracole/web/jobs.py` (`LANE`, `LANE_WAITING`, `lane_of`, `ahead`, `Job.lane`; `JobQueue.__init__`,
  `lanes`, `_submit_locked`, `room`, the docstrings of `submit` and the module's "The queue holds `limit` jobs…")
- Modify: `tests/test_web_jobs.py`

**Interfaces:**
- Produces: `LANE = 3`, `LANE_WAITING = 10`; `lane_of(steps: Sequence[tuple[str, Sequence[str]]]) -> bool` (every
  step a lane command: `get` without `--no-songbooks`, `ug --link=`, `lacuerda --search=` or `--artist=`, `harptabs
  --artist=`); `ahead(jobs: Sequence[Job], job: Job) -> int` (a lane job: the active lane jobs before it; a queue job:
  every active job before it and every active lane job; no lane, today's count); `Job.lane: bool =
  field(default=False, compare=False)` (in memory alone, never in `as_json` nor the history, as `report`);
  `JobQueue(runner, *, limit=LIMIT, keep=KEEP, max_lines=MAX_LINES, history=None, lane: int = 0, lane_waiting: int =
  LANE_WAITING)`; `JobQueue.lanes -> int`.

- [ ] **Step 1: Write the failing tests** in tests/test_web_jobs.py

```python
def test_lookups_and_the_search_boxs_one_request_reads_are_the_lanes_and_the_rest_the_queues():
    assert all(lane_of(s) for s in (lookup_steps("Muse", "Uprising"), lookup_steps("Muse", "Uprising", tab=TAB),
                                    ug_link_steps(TAB), lacuerda_search_steps("calamaro flaca", auto=True),
                                    lacuerda_artist_steps("andres-calamaro", "Andrés Calamaro"),
                                    harptabs_artist_steps("/artist/9", "Muse")))
    assert not any(lane_of(s) for s in (lookup_steps("Muse", "Uprising", songbooks=False), add_steps("Muse", "Uprising"),
                                        youtube_search_steps("muse uprising"), youtube_video_steps("dQw4w9WgXcQ"),
                                        youtube_sheet_steps("Muse - Uprising", VIDEO),
                                        version_steps("Muse", "Uprising", keep="1"), remove_steps("Muse - Uprising"),
                                        fetch_steps("Muse - Uprising"),
                                        [*add_steps("Muse", "Uprising"), *lookup_steps("Muse", "Uprising")]))

def test_a_queue_of_no_lane_places_every_request_in_the_queue_as_today():
    queue = JobQueue(FakeRunner())
    job, _ = queue.submit("Fetch Muse - Uprising", "muse|uprising", lookup_steps("Muse", "Uprising"), fetching=True)
    assert queue.lanes == 0 and not job.lane

@pytest.mark.parametrize("first", ["removal", "sheet from youtube", "songbook's lookup", "keep it"])
def test_a_lane_request_for_a_song_with_a_job_in_the_queue_goes_into_the_queue_behind_it(first):
    # JobQueue(FakeRunner(), lane=LANE); the song's job: REMOVING + key, YOUTUBE_SHEET + key, a get --no-songbooks,
    # or a versions --keep, queued first
    get, _ = queue.submit("Fetch Muse - Uprising", key, lookup_steps("Muse", "Uprising"), fetching=True)
    assert not get.lane  # in the queue by today's rules: answered, joined or after it
    assert queue.submit("Fetch Oasis - Wonderwall", "oasis|wonderwall", lookup_steps("Oasis", "Wonderwall"),
                        fetching=True)[0].lane  # a song with nothing queued: the lane's

def test_lane_requests_join_each_other_and_a_queue_request_never_joins_a_lane_job_that_waits():
    first, new = queue.submit(... lookup ...); again, joined = queue.submit(... the same lookup ...)
    assert new and not joined and again.id == first.id and first.lane
    keep, made = queue.submit("Keep", "muse|uprising", version_steps("Muse", "Uprising", keep="1"))
    assert made and not keep.lane  # its own job, in the queue
    assert [s.args[0] for s in queue.job(first.id).steps] == ["get"]  # the lane job as it was
    add, made = queue.submit("Add", "muse|uprising", add_steps("Muse", "Uprising"))
    assert not made and add.id == first.id  # a lane job that does as much is its answer

def test_the_lane_has_room_of_its_own():
    # LIMIT adds fill the queue: one more raises QueueFull, room() == 0
    lookups = [queue.submit(f"Fetch C - {n}", f"c|{n}", lookup_steps("C", str(n)), fetching=True)[0]
               for n in range(LANE + LANE_WAITING)]
    assert all(job.lane for job in lookups)
    with pytest.raises(QueueFull):
        queue.submit("Fetch D - 0", "d|0", lookup_steps("D", "0"), fetching=True)
    assert queue.active_count() == LIMIT + LANE + LANE_WAITING

def test_requests_queued_together_each_take_their_own_lanes_room():
    # the queue full: submit_all([a lookup, a songbook add]) raises QueueFull and queues neither
    # the queue with room: both queued, the lookup in the lane, the songbook's change in the queue

def test_a_request_counts_ahead_what_it_waits_for():
    # jobs 1 queue running, 2 lane running, 3 lane queued, 4 queue queued, 5 lane queued
    assert [ahead(jobs, jobs[i]) for i in (2, 4, 3)] == [1, 2, 4]
    # with no lane job, every active job before it, as today
```

- [ ] **Step 2: Run them to see them fail**

Run: `nix develop -c pytest -q tests/test_web_jobs.py -k "lane or ahead"`
Expected: FAIL (`cannot import name 'lane_of'`).

- [ ] **Step 3: Implement in `src/caracole/web/jobs.py`**. `_submit_locked`: `lane = self._lanes > 0 and
  lane_of(steps) and` no active job outside the lane whose `song_key_of(song_key)` is this one's; `mine` as now (every
  active job of the key, lane or not: `_as_much`'s); `waiting` = the first of `mine` queued in the same place (`job.lane
  == lane`); the room: a lane request against `lanes + lane_waiting` active lane jobs, any other against `limit` active
  jobs outside the lane (QueueFull either way); the new `Job(..., lane=lane)`. `room()` is the queue's (outside the
  lane); `active_count()` counts both. `submit_all` checks each request against its own place, all or none, as now.

- [ ] **Step 4: Run them to see them pass, and the queue's corpus**

Run: `nix develop -c pytest -q tests/test_web_jobs.py tests/test_conformance_queue.py tests/test_web_history.py`
Expected: PASS (a queue of no lane: the corpus as it is).

- [ ] **Step 5: Commit**

```bash
nix develop -c pytest -q
git add src/caracole/web/jobs.py tests/test_web_jobs.py
git commit -m "feat(serve): a lane beside the queue for lookups and the search box's one-request reads, with room of its own"
```

### Task 6.8: The lane's workers

**Files:**
- Modify: `src/caracole/web/jobs.py` (`start`, `stop`, `_work(lane)`, `_next(lane)`, `run_pending`, `_run`;
  `CaracoleRunner`; the module docstring :46-50)
- Modify: `src/caracole/commands/serve.py:75` (`lane=LANE`)
- Modify: `tests/test_web_jobs.py`, `tests/test_commands_serve.py`
- Modify: `AGENTS.md` (Jobs and requests; "`serve` never takes it"), `docs/usage.md` (caracole serve's request lines)

**Interfaces:**
- Consumes: 6.7's `Job.lane`, `lanes`.
- Produces: `JobQueue._next(lane: bool) -> Job | None` (the queue's worker: the first queued job outside the lane, only
  while no lane job runs or waits; a lane worker: the first queued lane job whose `song_key_of` has no job running),
  marking it running under the queue's lock; `CaracoleRunner` keeping a process a running command, `terminate` ending
  them all.

- [ ] **Step 1: Write the failing tests** in tests/test_web_jobs.py, with a runner whose commands each wait for their
  gate (their last argument) and return -15 once terminated

```python
def test_a_lookup_asked_while_a_long_request_runs_starts_at_once_and_a_request_after_it_waits_for_it():
    # lane=LANE, started: an add "Long" running; a lookup "Now" starts while it runs; an add "After" queued
    # "Long" opened and done: "After" still queued (the lane is busy); "Now" opened and done: "After" runs

def test_a_fourth_lookup_waits_for_a_slot_and_a_songs_second_job_for_its_first():
    # four lookups of four songs: three start, the fourth waits; one opened: the fourth starts
    # a lookup of D with tab 1 runs; D with tab 2 is a job of its own, in the lane; a lookup of E asked after it starts
    # while D's second still waits; D's first opened and done: D's second runs

def test_a_songs_own_job_keeps_its_order():
    # a removal of Muse - Uprising runs; Get it for it: a job in the queue, never the lane; it runs once the removal
    # is done, after it (the runner's calls in that order), so its wanted.txt line brings the song back as new

def test_cancel_takes_out_a_lookup_waiting_for_a_slot_never_one_that_runs():
    # three running, a fourth waiting: cancel(fourth) is cancelled; cancel(a running one) raises JobStarted

def test_a_stop_interrupts_every_running_request_and_a_restart_reads_them_back_so(tmp_path):
    # History(tmp_path / "requests.jsonl"); two lookups running; stop(): both INTERRUPTED; a new History's load():
    # both INTERRUPTED

def test_run_pending_runs_the_lane_before_the_queue():
    # lane=LANE: an add then a lookup queued; run_pending(): the lookup's command first

@pytest.mark.slow
def test_the_runner_keeps_a_process_a_command_and_ends_them_all(tmp_path):
    # python= a script that execs `sleep 30`; two commands from two threads; terminate(): both return -15 within 5 s
```

tests/test_commands_serve.py:

```python
def test_its_lookups_run_in_a_lane_of_their_own(tmp_path, started):
    assert invoke(tmp_path).exit_code == 0 and started["app"].queue.lanes == LANE
```

- [ ] **Step 2: Run them to see them fail**

Run: `nix develop -c pytest -q tests/test_web_jobs.py -k "lane or lookup_asked or fourth or own_order or stop or pending or runner_keeps" tests/test_commands_serve.py -k lane`
Expected: FAIL (one worker: the lookup waits behind the add).

- [ ] **Step 3: Implement**: `start()` starts the queue's worker and `lanes` lane workers (`caracole-lane-1`…), each
  waiting on `_wake` until a job it may start is there (never a busy loop), `_run` notifying `_wake` as each job ends;
  `stop()` stops them all, ends every command (`terminate`) and joins every worker; `run_pending` runs `_next(True)`
  then `_next(False)` until neither gives a job. `CaracoleRunner._processes: set[subprocess.Popen[str]]`. serve makes
  `JobQueue(..., history=..., lane=LANE)`. The module docstring's "One worker thread runs the jobs in order, so the
  server never runs two commands at once…": one worker runs the queue's jobs in order, and `LANE` more the lane's,
  lookups and the search box's one-request reads that start at once unless their song has a job in the queue, which
  take turns with caracole's lock (commands/_common.py), so the server is still no more aggressive than one lookup's
  pace a site.

- [ ] **Step 4: Run them to see them pass**

Run: `nix develop -c pytest -q tests/test_web_jobs.py tests/test_commands_serve.py tests/test_web_history.py tests/test_requests_tab.py`
Expected: PASS.

- [ ] **Step 5: Docs**: AGENTS.md, Jobs and requests: "every change runs as a `caracole` command queued in jobs.py":
  in the queue, one at a time, or in the lookups' lane, up to `LANE` at once, started at once unless the song has a job
  in the queue; "`serve` never takes it": "in a child process, one at a time (web/jobs.py)": one at a time in the queue,
  and up to `LANE` lookups beside it, which take turns with the lock. docs/usage.md, caracole serve's request lines: a
  lookup (Get it, Fetch, Fetch again, Fetch it now, a pasted UG link, LaCuerda's search, an artist's page) starts at
  once beside the request that runs, unless its song has a request in the queue; three at most run at once, a fourth
  waits with its place and Cancel.

- [ ] **Step 6: Commit**

```bash
nix develop -c pytest -q
git add src/caracole/web/jobs.py src/caracole/commands/serve.py tests/test_web_jobs.py tests/test_commands_serve.py AGENTS.md docs/usage.md
git commit -m "feat(serve): the lane's lookups start at once, up to three beside the queue's request"
```

### Task 6.9: What a queued line and the Journal count

**Files:**
- Modify: `src/caracole/web/jobs_routes.py` (`_ahead` gives way to `jobs.ahead`), `src/caracole/web/feed.py` (a
  queued request's place, in `feed`)
- Modify: `tests/test_requests_tab.py`
- Modify: `docs/usage.md` (the Journal's Now: "the request that runs" becomes the requests that run, oldest first)

**Interfaces:**
- Consumes: 6.7's `ahead`, `Job.lane`.

- [ ] **Step 1: Write the failing tests** in tests/test_requests_tab.py

```python
def test_a_lookup_waiting_for_a_slot_counts_the_lane_ahead_and_a_queued_request_the_lane_too():
    # jobs 1 queue running, 2 lane running, 3 lane queued, 4 queue queued, 5 lane queued
    assert [jobs_routes.view(jobs[i], jobs, None, None)["line"]["text"] for i in (2, 4, 3)] == [
        "Queued · 1 request ahead…", "Queued · 2 requests ahead…", "Queued · 4 requests ahead…"]

def test_queued_requests_say_their_place_in_their_lane_and_every_running_one_is_now():
    shown = by_id(feed(jobs, {}, now=NOW))
    assert [shown[n]["says"]["text"] for n in (3, 5, 4)] == ["Queued · next", "Queued · 2nd", "Queued · next"]
    assert [r["id"] for r in requests(feed(jobs, {}, now=NOW), "Now")][:2] == [1, 2]  # every running one, oldest first
```

- [ ] **Step 2: Run them to see them fail**

Run: `nix develop -c pytest -q tests/test_requests_tab.py -k "slot or their_lane"`
Expected: FAIL (every job before it counted; places counted across both).

- [ ] **Step 3: Implement**: jobs_routes.py's two callers use `jobs.ahead(jobs, job)` and `_ahead` goes; feed.py's
  queued place is the request's among the queued of its own place (`job.lane`), as now with no lane.

- [ ] **Step 4: Run them, the views' tests and the corpus to see no change**

Run: `nix develop -c pytest -q tests/test_requests_tab.py tests/test_web_status.py tests/test_web_outcome.py && CARACOLE_CORPUS=write nix develop -c pytest -q -n 0 tests/test_conformance_*.py && git status --porcelain tests/conformance`
Expected: PASS, and no line from `git status` (the corpus doesn't move).

- [ ] **Step 5: Commit**

```bash
nix develop -c pytest -q
git add src/caracole/web/jobs_routes.py src/caracole/web/feed.py tests/test_requests_tab.py docs/usage.md
git commit -m "feat(serve): a queued request counts what it waits for, a lookup its lane"
```

### Task 6.10: Merge

**Files:** none new.

- [ ] **Step 1: main into the branch**, if it moved: `git -C /home/dani/Projects/caracole-lookups merge main`
  (AGENTS.md or usage.md conflicts keep both sides' sentences, "Where the lanes meet" 4).

- [ ] **Step 2: The whole suite**: `nix develop -c pytest -q`. Expected: PASS but for main's known failure the owner
  left for later, test_ug_directory's thread race (flaky on main too: run that test again alone; it must fail no other
  way).

- [ ] **Step 3: The corpus, twice and checked**:
  `CARACOLE_CORPUS=write nix develop -c pytest -q -n 0 tests/test_conformance_*.py`, again, then
  `nix develop -c pytest -q -n 0 tests/test_conformance_*.py`, and `git status --porcelain tests/conformance`.
  Expected: PASS, no line (lane 6 moves no word: a change here is a word that moved, which stops the merge until it and
  the phone's port move together).

- [ ] **Step 4: The phone**: `nix develop ./android -c gradle -p android test`. Expected: BUILD SUCCESSFUL.

- [ ] **Step 5: The e2e, only if the corpus moved**:
  `CARACOLE_ANDROID_E2E=1 nix develop -c pytest -q -n 0 tests/test_android_e2e.py`. Expected: PASS but for main's
  known PhoneScenarioTest phase11 failure, left for later, failing as on main.

- [ ] **Step 6: `nix flake check`**. Expected: all checks pass.

- [ ] **Step 7: Merge and push**, from the main checkout (its uncommitted files left alone):

```bash
cd /home/dani/Projects/caracole
git switch main
git merge --no-ff feat/lookup-lane -m "Merge branch 'feat/lookup-lane': lookups without a queue, a lane beside serve's queue whose lookups take turns with caracole's lock"
GH_TOKEN="$(gh auth token --user Danielhp95)" git push origin main
```

Expected: a merge commit on main, pushed.
