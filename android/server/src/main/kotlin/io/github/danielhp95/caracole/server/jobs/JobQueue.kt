package io.github.danielhp95.caracole.server.jobs

import io.github.danielhp95.caracole.core.index.Stamps
import io.github.danielhp95.caracole.core.json.PyJson
import io.github.danielhp95.caracole.core.py.Py
import io.github.danielhp95.caracole.server.http.Refused
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.channels.Channel
import kotlinx.coroutines.currentCoroutineContext
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.yield
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import java.time.Instant

/**
 * A job to queue: what it is ([title], and [display], what the page names it by: its title when empty), the key it is
 * queued under ([key]: a song's identity key, or a prefix of JobCommands' and what follows it), what it is about
 * ([kind]: add, remove, sync, index, song, versions, lacuerda-search…), its stages (name, label) as the page shows
 * them, the song it is about when that is known before it runs ([songId]: a removal's), and what it runs, on the
 * queue's one worker. [doneLine]: what its line says once it is done, in place of its kind's words ("Added: the
 * computer's next run fetches it.").
 *
 * A job of caracole serve's is its [commands]: Python's command lines as data, spelled exactly as web/jobs.py spells
 * them (JobCommands' builders), each run by the queue's runner of its first word ([Commands]), one after another; their
 * stages are JobCommands.stages', after [stages]. [run], when given, runs first (an add, a removal, a sync, an index
 * import of the phone's own), then the commands a request joined to it. [fetching]: whether it fetches its song (a
 * lookup's), [note] what Job.asJson's `note` says. [join] false: a job of the key that waits or runs is its answer,
 * left as it is (web/jobs.py's `join=False`).
 */
data class JobSpec(val title: String, val key: String, val kind: String, val stages: List<Pair<String, String>>,
                   val display: String = "", val songId: Long? = null, val join: Boolean = true,
                   val doneLine: String? = null, val commands: List<Command> = emptyList(),
                   val fetching: Boolean = false, val note: String = "",
                   val run: (suspend (JobContext) -> Unit)? = null)

/** What a running job tells its view: a stage's state and what it says now, a line of its output (an `error: …`
 * line is what its line says should it fail), its outcome (the view's `outcome`), and the song it turned out to be
 * about (an add's, once added), as `caracole get --progress`'s events tell caracole serve's. */
interface JobContext {
    fun stage(name: String, state: String, detail: String = "")
    fun say(line: String)
    fun outcome(value: JsonObject)
    val isCancelled: Boolean
    fun song(id: Long, display: String) {}

    /** The files a reader can open already, and how long they took (get.py's `readable` event). */
    fun readable(files: Map<String, String>, seconds: Double) {}

    /**
     * Runs the lookups queued since (JobCommands.isLookup's jobs, in the order queued, those queued meanwhile too),
     * then returns: a long job of the phone's own (the render job) calls it between two songs, from its run or a
     * plain callback of it (PhoneRender's `between`). They run in the queue's one worker, on the caller's thread,
     * which waits for them (a job's run is the worker's: nothing else of the queue runs meanwhile), and a stop of the
     * queue's scope stops them and then the caller (a CancellationException).
     *
     * It is called holding no Database.write: the lookups write. A write held on this thread fails a lookup's own
     * write at once (Database's "a write inside a write's block"); one it makes on another thread would wait for it.
     * A call from a job it runs, from a job that is no longer running, or with no lookup queued does nothing.
     */
    fun yieldToQueued() {}
}

/** A stage of a job: its state (waiting, running, done, skipped, failed, interrupted), what it says now, and what it
 * said last while it ran ([runningDetail], web/jobs.py's `running_detail`: a stage the queue ended failed says that
 * still, which is no failure's words). */
class Stage internal constructor(val name: String, val label: String) {
    var state: String = Job.WAITING
        internal set
    var detail: String = ""
        internal set
    var runningDetail: String = ""
        internal set

    internal fun copy() = Stage(name, label).also { it.state = state; it.detail = detail; it.runningDetail = runningDetail }
}

/** One of a job's commands as it runs (web/jobs.py's Step): its state (waiting, running, done, failed, skipped,
 * interrupted), the exit status it ended with ([code]: 0, the [CommandExit]'s, 1 for any other throw, null for one that
 * couldn't start or the queue's end stopped), its output's last [JobQueue.MAX_LINES] lines and how many came before
 * them ([dropped]). */
class Step internal constructor(val label: String, val args: List<String>) {
    var state: String = Job.WAITING
        internal set
    var code: Int? = null
        internal set
    var output: List<String> = emptyList()
        internal set
    var dropped: Int = 0
        internal set

    val command: Command get() = Command(label, args)

    internal fun copy() = Step(label, args).also { it.state = state; it.code = code; it.output = output; it.dropped = dropped }
}

/** A unit a sync took, gave or left ([outcome]), and why (web/jobs.py's `Job.units`): read back from a history
 * caracole serve wrote; the phone's own syncs set their outcome instead. */
data class JobUnit(val id: String, val outcome: String, val why: String)

/**
 * A job queued, running or over (web/jobs.py's `Job`): its [state], queued, running, done, failed (its run or a
 * command failed), cancelled (taken out of the queue before it ran) or interrupted (the queue's scope ended while it
 * ran, or the history read it back unfinished); its [steps] (its commands), stages, output, outcome and song. The
 * queue changes it under its lock; what a caller gets of it ([JobQueue.snapshot], [JobQueue.job], [JobQueue.await])
 * is a copy, as caracole serve's queue hands out copies.
 *
 * [spec] is what it runs now: the request it was queued with, its title, commands, fetching and note as a request
 * that joined it while it waited left them (web/jobs.py's `_join`).
 */
class Job internal constructor(val id: Int, spec: JobSpec, queuedAt: Instant = Instant.now()) {
    var spec: JobSpec = spec
        internal set
    var state: String = QUEUED
        internal set
    var queuedAt: Instant = queuedAt
        internal set
    var startedAt: Instant? = null
        internal set
    var finishedAt: Instant? = null
        internal set
    var steps: List<Step> = spec.commands.map { Step(it.label, it.args) }
        internal set
    var stages: List<Stage> = stagesOf(spec, steps)
        internal set
    var outcome: JsonObject? = null
        internal set
    var songId: Long? = spec.songId
        internal set
    var songDisplay: String? = if (spec.songId != null) spec.display.ifEmpty { spec.title } else null
        internal set
    var files: Map<String, String> = emptyMap()
        internal set
    var secondsToSheet: Double? = null
        internal set

    /** The jobs queued with it by one [JobQueue.submitAll], itself among them; cancelling one cancels those that
     * haven't started. */
    var together: List<Int> = emptyList()
        internal set
    var units: List<JobUnit> = emptyList()
        internal set

    /** While it lets the lookups queued behind it go first (JobContext.yieldToQueued): how many of them wait or run;
     * 0 else. */
    var waitingFor: Int = 0
        internal set

    /** What its run said, before any command ran (its commands' output is theirs, [Step.output]). */
    internal var said: List<String> = emptyList()

    /** Read back from the history as a job of the phone's own (a run of its own, which the history can't keep). */
    internal var readOwn: Boolean = false

    /** The name it was queued with, as web/jobs.py keeps `display` (its title then, when none was given). */
    internal var named: String = spec.display.ifEmpty { spec.title }

    val title: String get() = spec.title
    val key: String get() = spec.key
    val fetching: Boolean get() = spec.fetching
    val note: String get() = spec.note

    /** Whether it waits or runs. */
    val active: Boolean get() = state == QUEUED || state == RUNNING

    /** What the page names it by. */
    val display: String get() = named.ifEmpty { spec.title }

    /** What it said, its run's lines then each command's, in order (set: what it said, its commands' none). */
    var output: List<String>
        get() = said + steps.flatMap { it.output }
        internal set(value) {
            said = value
            for (step in steps) {
                step.output = emptyList()
                step.dropped = 0
            }
        }

    /** Whether one of its commands looks its song up (`caracole get`, or `versions --choose` or `--clear`). */
    val looksUp: Boolean get() = steps.any { JobCommands.looksUp(it.args) }

    internal val ended = CompletableDeferred<Unit>()

    internal fun copy(): Job = Job(id, spec, queuedAt).also {
        it.state = state
        it.startedAt = startedAt
        it.finishedAt = finishedAt
        it.steps = steps.map(Step::copy)
        it.stages = stages.map(Stage::copy)
        it.said = said
        it.readOwn = readOwn
        it.outcome = outcome
        it.songId = songId
        it.songDisplay = songDisplay
        it.files = files
        it.secondsToSheet = secondsToSheet
        it.together = together
        it.units = units
        it.waitingFor = waitingFor
        it.named = named
    }

    /** Job.as_json: the job as plain data, `/api/jobs/N`'s answer: its stages as its steps (else its commands), its
     * commands, its song once known. */
    fun asJson(): JsonObject = JsonObject(linkedMapOf(
        "id" to JsonPrimitive(id),
        "title" to JsonPrimitive(title),
        "display" to JsonPrimitive(display),
        "state" to JsonPrimitive(state),
        "active" to JsonPrimitive(active),
        "note" to JsonPrimitive(note),
        "queued_at" to stamp(queuedAt),
        "started_at" to stamp(startedAt),
        "finished_at" to stamp(finishedAt),
        "steps" to JsonArray(if (stages.isNotEmpty()) stages.map { stage ->
            JsonObject(linkedMapOf("name" to JsonPrimitive(stage.name), "label" to JsonPrimitive(stage.label),
                                   "state" to JsonPrimitive(stage.state), "detail" to JsonPrimitive(stage.detail)))
        } else steps.map { step ->
            JsonObject(linkedMapOf("name" to JsonPrimitive(step.args.firstOrNull() ?: ""),
                                   "label" to JsonPrimitive(step.label), "state" to JsonPrimitive(step.state),
                                   "detail" to JsonPrimitive("")))
        }),
        "commands" to JsonArray(steps.map { step ->
            JsonObject(linkedMapOf("label" to JsonPrimitive(step.label),
                                   "args" to JsonArray(step.args.map(::JsonPrimitive)),
                                   "state" to JsonPrimitive(step.state),
                                   "code" to (step.code?.let(::JsonPrimitive) ?: JsonNull)))
        }),
        "song" to songId.let { song ->
            if (song == null) JsonNull
            else JsonObject(linkedMapOf("id" to JsonPrimitive(song),
                                        "display" to (songDisplay?.let(::JsonPrimitive) ?: JsonNull)))
        },
        "files" to JsonObject(files.mapValues { JsonPrimitive(it.value) }),
        "seconds_to_sheet" to (secondsToSheet?.let(PyJson::float) ?: JsonNull),
        "units" to JsonArray(units.map { JsonArray(listOf(JsonPrimitive(it.id), JsonPrimitive(it.outcome),
                                                           JsonPrimitive(it.why))) }),
    ))

    companion object {
        const val QUEUED = "queued"
        const val RUNNING = "running"
        const val DONE = "done"
        const val FAILED = "failed"
        const val CANCELLED = "cancelled"
        const val INTERRUPTED = "interrupted"
        const val WAITING = "waiting"
        const val SKIPPED = "skipped"

        /** A time as caracole serve writes one ("%Y-%m-%dT%H:%M:%SZ", in UTC: stamps.stamp, core.index.Stamps), or
         * null. */
        internal fun stamp(at: Instant?): JsonElement = if (at == null) JsonNull else JsonPrimitive(Stamps.of(at))

        /** A job's stages, all waiting: its spec's, then those its commands report it hasn't (JobCommands.stages). */
        private fun stagesOf(spec: JobSpec, steps: List<Step>): List<Stage> {
            val own = spec.stages.map { (name, label) -> Stage(name, label) }
            val names = own.map { it.name }.toSet()
            return own + JobCommands.stages(steps.map { it.args })
                .filter { it.first !in names }.map { (name, label) -> Stage(name, label) }
        }
    }
}

/** The queue holds [JobQueue.limit] jobs that wait or run already (web/jobs.py's QueueFull). */
class QueueFull(val limit: Int) : Exception("$limit requests are waiting already")

/** A job asked to be cancelled that runs, or is over ([state]): a job is never stopped halfway (web/jobs.py's). */
class JobStarted(val id: Int, val state: String) : Exception("request $id is $state")

/** A job asked to run again that waits or runs still ([state]): Try again is for a request that is over. */
class JobNotOver(val id: Int, val state: String) : Exception("request $id is $state")

/** A job the queue remembers but can't run again: one of the phone's own (an add, a removal, a sync, an index import)
 * read back from the history, which keeps no run (format 1 keeps commands alone), so there is nothing to run. */
class JobNotRepeatable(val id: Int) : Exception("request $id can't be run again: the phone ran it itself")

/**
 * web/jobs.py's JobQueue on the phone: jobs in order, run by one worker coroutine in [scope], so they never write
 * beside each other (an index import, a sync, a lookup, an add).
 *
 * - [submit]: web/jobs.py's rules over command lines, one job per song: a song's job that waits or runs and does as
 *   much is the answer (for a pick, `--ug`, `--tab`, `--choose`…, only the song's last job, with the same pick; else
 *   one that looks the song up or fetches it, or, for a request that fetches nothing or mustn't join, any); else a
 *   request joins the song's job that still waits (a lookup takes the place of its add and its lookup, the rest of its
 *   commands added); else a job of its own, unless [limit] jobs wait or run already ([QueueFull]). A job of the
 *   phone's own (JobSpec.run) joins none. [submitAll]: several, all or none, `together`.
 * - [cancel]: a job that hasn't started taken out of the queue, over as "cancelled", its steps and stages skipped,
 *   and those queued together with it that haven't started; one that runs or is over is never stopped ([JobStarted]).
 * - [again]: a job over queued again, its commands as they were (Try again: a search the page sent asked by hand now,
 *   a lookup made with its songbooks).
 * - A job runs its run, then its commands one after another, each by its runner ([commands]), its steps' states as
 *   caracole serve's: a command that throws fails its step (its `error:` line said, none for a [CommandExit] of no
 *   words, typer.Exit's; its code [CommandExit]'s or 1),
 *   the job's running stage failed and the rest skipped. A run that throws fails its job as milestone 3's did: the
 *   first line of what it threw said (`error: …`) and the words of its stage that ran (else the first that waited),
 *   failed. The worker goes on. One the scope's end stops is interrupted, its step and stage that ran so too, whatever
 *   the command threw, and the commands after it skipped, a stop between two of them too (caracole serve's
 *   `_stopping`); the worker stops. A progress event of a command that writes none (JobCommands.reports) is a line of
 *   its output, as caracole serve keeps such a line.
 * - [history]: the jobs it remembers read back as the queue starts (history.py: those that waited or ran
 *   interrupted), each saved to it as it is queued or joined, starts and is over, under the queue's lock, in order.
 * - The last [keep] jobs over are remembered.
 * - [onBusy]: told true as the queue gets a job to run, and false once none waits or runs (the app's foreground
 *   service listens); told under the queue's lock, so in order: it must not block. [onEnd]: each job once it is over.
 */
class JobQueue(private val scope: CoroutineScope, val limit: Int = LIMIT, val keep: Int = KEEP,
               private val clock: () -> Instant = { Instant.now() }, val commands: Commands = Commands(emptyMap()),
               val history: JobHistory? = null) {
    private val lock = Any()
    private val jobs = ArrayList<Job>()  // oldest first, as queued
    private var nextId = 1
    private val wake = Channel<Unit>(Channel.CONFLATED)
    private var started = false
    private var busy = false
    private var yielding = false  // under the lock: a long job lets the lookups behind it go first

    /** Told true as the queue gets busy and false as it goes idle (the app's foreground service listens). */
    var onBusy: (Boolean) -> Unit = {}

    /** Told each job once it is over, cancelled ones too, outside the queue's lock, as a copy, before anyone awaiting
     * it hears it ended: the phone's afterJob (the search invalidated, Alerts.failed for a failed job). */
    var onEnd: (Job) -> Unit = {}

    init {
        if (history != null) {
            val loaded = history.load(clock())
            for (job in loaded.jobs) job.ended.complete(Unit)  // over, all of them
            jobs.addAll(loaded.jobs)
            nextId = loaded.nextId
        }
    }

    /** The job, and whether it is new (false: a job of the song's that waits or runs is its answer, or it joined the
     * song's job that waits). */
    fun submit(spec: JobSpec): Pair<Job, Boolean> {
        var start = false
        val done = synchronized(lock) {
            val done = submitLocked(spec)
            save(done.first.id)
            if (done.second) start = gotWork()
            done
        }
        if (start) scope.launch { work() }  // the one worker, started outside the lock
        wake.trySend(Unit)
        return done
    }

    /**
     * [submit] of each spec, all or none, under the queue's one lock: when one finds the queue full, [QueueFull] is
     * thrown and the queue is as it was, the jobs the earlier ones joined as before. A spec that joins a job already
     * queued needs no room. The jobs it makes are queued `together`: cancelling one cancels those of them that haven't
     * started. The copies it gives back were made before that is said (web/jobs.py's submit_all).
     */
    fun submitAll(specs: List<JobSpec>): List<Pair<Job, Boolean>> {
        var start = false
        val done = synchronized(lock) {
            val waiting = jobs.filter { it.state == Job.QUEUED }.associate { it.id to Triple(it.spec, it.steps, it.stages) }
            val count = jobs.size
            val next = nextId
            val done = ArrayList<Pair<Job, Boolean>>()
            try {
                for (spec in specs) done += submitLocked(spec)
            } catch (e: QueueFull) {
                while (jobs.size > count) jobs.removeAt(jobs.size - 1)
                nextId = next
                for (job in jobs) {
                    val (spec, steps, stages) = waiting[job.id] ?: continue
                    job.spec = spec
                    job.steps = steps
                    job.stages = stages
                }
                throw e
            }
            val made = done.filter { it.second }.map { it.first.id }
            if (made.size > 1) {  // both or neither: cancelled so too
                for (job in jobs) if (job.id in made) job.together = made
            }
            for (id in done.map { it.first.id }.distinct()) save(id)  // saved once all are queued
            if (made.isNotEmpty()) start = gotWork()
            done
        }
        if (start) scope.launch { work() }
        wake.trySend(Unit)
        return done
    }

    /**
     * A job over queued again ([submit]) with its commands as they were (jobs_routes.again: a query of LaCuerda's
     * search the page sent by itself asked by hand now, no `--auto`; a lookup Get the missing songs queued made with
     * its songbooks, no `--no-songbooks`; a pick's `caracole review` after the song's own request, never joined), and
     * a run of the phone's own run again; the job it is now, a song's job that waits or runs if that is its answer.
     * [NoSuchElementException] for one the queue doesn't remember (jobs_routes.again's 404); [JobNotOver] for one
     * that waits or runs; [JobNotRepeatable] for one it remembers with nothing to run (the phone's own add, say, read
     * back from the history).
     */
    fun again(id: Int): Job {
        val spec = synchronized(lock) {
            val job = jobs.firstOrNull { it.id == id } ?: throw NoSuchElementException("no request $id")
            if (job.active) throw JobNotOver(id, job.state)
            if (job.spec.run == null && job.steps.isEmpty()) throw JobNotRepeatable(id)
            var commands = job.steps.map { it.command }
            if (job.key.startsWith(JobCommands.LACUERDA_SEARCH)) {  // you ask for it now: by hand
                commands = commands.map { command -> command.copy(args = command.args.filter { it != "--auto" }) }
            }
            commands = commands.map { it.copy(args = withSongbooks(it.args)) }
            val picked = job.steps.any { it.args.firstOrNull() == "review" }  // after the song's own request
            job.spec.copy(display = job.named, songId = job.songId, join = !picked, commands = commands)
        }
        return submit(spec).first
    }

    /** A lookup's command with its songbooks stage (no `--no-songbooks` before `--`). */
    private fun withSongbooks(args: List<String>): List<String> {
        if (args.firstOrNull() != JobCommands.LOOKUP || "--" !in args) return args
        val end = args.indexOf("--")
        return args.subList(0, end).filter { it != "--no-songbooks" } + args.subList(end, args.size)
    }

    /** [submit], as a route answers a full queue: [Refused] (503) with [full] (WebApp.submit's). */
    fun submitOrRefuse(spec: JobSpec, full: String = QUEUE_FULL): Pair<Job, Boolean> = try {
        submit(spec)
    } catch (e: QueueFull) {
        throw Refused(503, "The queue is full", full)
    }

    /** A job remembered, as a copy; null for one never queued, or forgotten. */
    fun job(id: Int): Job? = synchronized(lock) { jobs.firstOrNull { it.id == id }?.copy() }

    /** Every job the queue remembers, newest first, as copies. */
    fun snapshot(): List<Job> = synchronized(lock) { jobs.asReversed().map(Job::copy) }

    /** How many jobs wait or run. */
    fun activeCount(): Int = synchronized(lock) { jobs.count { it.active } }

    /** How many more jobs the queue takes now: [limit], less those waiting or running. */
    fun room(): Int = synchronized(lock) { maxOf(0, limit - jobs.count { it.active }) }

    /** The songs a job that waits or runs will fetch (their keys). */
    fun fetchingKeys(): Set<String> = synchronized(lock) { jobs.filter { it.active && it.fetching }.map { it.key }.toSet() }

    /** How many jobs wait or run before [job], queued as it waits ("Queued behind 2 requests…"). */
    fun ahead(job: Job): Int = synchronized(lock) { jobs.count { it.active && it.id < job.id } }

    /**
     * A job that hasn't started taken out of the queue, over and never run, and given back as a copy, with those
     * queued `together` with it that haven't started; null for one never queued, cancelled already or forgotten.
     * [JobStarted] for one that runs or is over.
     */
    fun cancel(id: Int): Job? {
        val (cancelled, over) = synchronized(lock) {
            val job = jobs.firstOrNull { it.id == id } ?: return null
            if (job.state == Job.CANCELLED) return null
            if (job.state != Job.QUEUED) throw JobStarted(id, job.state)
            val now = clock()
            val gone = jobs.filter { it === job || (it.id in job.together && it.state == Job.QUEUED) }
            for (j in gone) {
                j.state = Job.CANCELLED
                j.finishedAt = now
                for (step in j.steps) step.state = Job.SKIPPED
                for (stage in j.stages) stage.state = Job.SKIPPED
                save(j.id)
            }
            forget()
            idle()
            job.copy() to gone.map { it to it.copy() }
        }
        for ((job, copy) in over) {
            runCatching { onEnd(copy) }
            job.ended.complete(Unit)
        }
        return cancelled
    }

    /** The job once it is over, as a copy; [NoSuchElementException] for one the queue doesn't remember. */
    suspend fun await(id: Int): Job {
        val job = synchronized(lock) { jobs.firstOrNull { it.id == id } }
            ?: throw NoSuchElementException("no request $id")
        job.ended.await()
        return synchronized(lock) { job.copy() }
    }

    // --- the rules (web/jobs.py's submit) ----------------------------------------------------------------------

    /** [submit] under the queue's lock: the song's job that does as much, else its job that still waits, joined,
     * else a job of its own. */
    private fun submitLocked(spec: JobSpec): Pair<Job, Boolean> {
        val new = spec.commands.map { it.args }
        val mine = jobs.filter { it.active && it.key == spec.key }
        val waiting = mine.firstOrNull { it.state == Job.QUEUED }
        val enough = asMuch(mine, waiting, new, spec.fetching, spec.join)
        if (enough != null) return enough.copy() to false
        if (waiting != null && spec.run == null) {
            join(waiting, spec)
            return waiting.copy() to false
        }
        if (jobs.count { it.active } >= limit) throw QueueFull(limit)
        val job = Job(nextId++, spec, clock())
        jobs.add(job)
        return job.copy() to true
    }

    /** web/jobs.py's _as_much: which of a song's jobs waiting or running ([mine]; [waiting], the first that waits)
     * does as much as a request of [new] commands, and so is its answer; null for none. */
    private fun asMuch(mine: List<Job>, waiting: Job?, new: List<List<String>>, fetching: Boolean, join: Boolean): Job? {
        val picked = JobCommands.pick(new)
        if (picked.isNotEmpty() && join) {  // your pick: only the song's last job, with the same pick, does as much
            val last = waiting ?: mine.firstOrNull { it.state == Job.RUNNING }
            return if (last != null && JobCommands.pick(last.steps.map { it.args }) == picked) last else null
        }
        var enough = mine.firstOrNull { job -> JobCommands.fetches(job.steps.map { it.args }) }
        if (enough == null && (!fetching || !join) && mine.isNotEmpty()) enough = mine[0]
        return enough
    }

    /**
     * web/jobs.py's _join: a request joins the song's job that still waits. Its `caracole get` (or `versions
     * --choose`) takes the place of the job's add and lookup (the phone's own add, its run, among them), and the job
     * gets each of its commands it doesn't run, with their stages; it fetches now, under the request's title, and keeps
     * its note, else takes the request's.
     */
    private fun join(waiting: Job, request: JobSpec) {
        val new = request.commands.map { Step(it.label, it.args) }
        var spec = waiting.spec
        if (new.any { it.args.firstOrNull() == JobCommands.LOOKUP ||
                      (JobCommands.looksUp(it.args) && "--clear" !in it.args) }) {
            waiting.steps = waiting.steps.filter { it.args.firstOrNull() != "add" && it.args.firstOrNull() != JobCommands.LOOKUP }
            waiting.stages = emptyList()
            spec = spec.copy(kind = request.kind, stages = emptyList(), doneLine = request.doneLine,
                             run = if (spec.kind == "add") null else spec.run)
        }
        val runs = waiting.steps.map { it.args.firstOrNull() }.toSet()
        val commands = waiting.steps.map { it.args }.toSet()
        waiting.steps = waiting.steps + new.filter {
            it.args.firstOrNull() !in runs || (it.args.firstOrNull() == JobCommands.VERSIONS && it.args !in commands)
        }
        val had = waiting.stages.map { it.name }.toSet()  // a job waiting has heard nothing yet
        waiting.stages = waiting.stages + JobCommands.stages(waiting.steps.map { it.args })
            .filter { it.first !in had }.map { (name, label) -> Stage(name, label) }
        waiting.spec = spec.copy(title = request.title, fetching = true, note = spec.note.ifEmpty { request.note },
                                 commands = waiting.steps.map { it.command })
    }

    // --- the worker -----------------------------------------------------------------------------------------------

    private suspend fun work() {
        while (true) {
            val job = next()
            if (job == null) {
                wake.receive()
                continue
            }
            run(job)
            yield()  // whoever heard it ended goes first
        }
    }

    private fun next(): Job? = synchronized(lock) { jobs.firstOrNull { it.state == Job.QUEUED }?.also(::startLocked) }

    private fun startLocked(job: Job) {
        job.state = Job.RUNNING
        job.startedAt = clock()
        save(job.id)
    }

    private suspend fun run(job: Job) {
        val context = Context(job, currentCoroutineContext()[kotlinx.coroutines.Job])
        val own = job.spec.run  // a running job's spec never changes: a request joins one that waits
        if (own != null) {
            try {
                own(context)
            } catch (e: Throwable) {
                // The worker's own end (its scope's): the job is interrupted, and the worker stops. Any other throw, a
                // timeout of the run's own among them, fails the job alone, and the worker goes on.
                if (e is CancellationException && !currentCoroutineContext().isActive) {
                    end(job, Job.INTERRUPTED)
                    throw e
                }
                val said = said(e)
                context.say("error: $said")
                end(job, Job.FAILED, said)
                return
            }
        }
        var failed = false
        for (step in job.steps) {
            // The queue stopped (its scope's end, as caracole serve's `_stopping`): this step and the rest skipped,
            // the job interrupted, and the worker stops.
            if (!currentCoroutineContext().isActive) {
                end(job, Job.INTERRUPTED)
                throw CancellationException("the queue stopped")
            }
            val starts = synchronized(lock) {
                if (failed) {
                    step.state = Job.SKIPPED
                    false
                } else {
                    step.state = Job.RUNNING
                    context.step = step
                    if (JobCommands.looksUp(step.args)) afresh(job.stages)  // after Keep it, whose stages share names
                    true
                }
            }
            if (!starts) continue
            val code: Int? = try {
                val runner = commands.runnerFor(step.args)
                if (runner == null) {
                    context.say("error: caracole ${step.args.firstOrNull().orEmpty()} isn't on the phone")
                    null
                } else {
                    runner.run(step.args, context)
                    0
                }
            } catch (e: Throwable) {
                // A command the queue's stop ended, whatever it threw, is interrupted, never failed (web/jobs.py's
                // `INTERRUPTED if self._stopping`).
                if (!currentCoroutineContext().isActive) {
                    synchronized(lock) { context.step = null }
                    end(job, Job.INTERRUPTED)
                    throw e as? CancellationException ?: CancellationException("the queue stopped").apply { initCause(e) }
                }
                // an exit with no words is typer.Exit's: its command said why itself, and writes no error line
                if (e !is CommandExit || !e.message.isNullOrEmpty()) context.say("error: ${said(e)}")
                (e as? CommandExit)?.code ?: 1
            }
            synchronized(lock) {
                step.code = code
                step.state = if (code == 0) Job.DONE else Job.FAILED
                failed = failed || code != 0
                context.step = null
            }
        }
        // Stopped as its last command ended: interrupted unless every command was done (web/jobs.py's `interrupted`).
        if (!currentCoroutineContext().isActive && job.steps.any { it.state != Job.DONE }) {
            end(job, Job.INTERRUPTED)
            throw CancellationException("the queue stopped")
        }
        end(job, if (failed) Job.FAILED else Job.DONE)
    }

    /** What a throw says: its message's first line with something on it, else its class's name. */
    private fun said(e: Throwable): String = firstLine(e.message) ?: e::class.simpleName ?: "it stopped"

    /** get.py's stages as they are before a lookup starts, all waiting (web/jobs.py's _afresh). */
    private fun afresh(stages: List<Stage>) {
        val names = JobCommands.GET_STAGES.map { it.first }.toSet()
        for (stage in stages) {
            if (stage.name in names) {
                stage.state = Job.WAITING
                stage.detail = ""
                stage.runningDetail = ""
            }
        }
    }

    /** Whether [job] is to let the lookups queued behind it go first now: it runs, isn't one of them, isn't being
     * let go before, and a lookup waits. */
    private fun yields(job: Job): Boolean = synchronized(lock) {
        !yielding && job.state == Job.RUNNING && !isLookup(job) && jobs.any { it.state == Job.QUEUED && isLookup(it) }
    }

    /** The lookups queued since a long job of the phone's own began, run here, one by one, until none waits or the
     * queue stops (JobContext.yieldToQueued). */
    private suspend fun yieldFrom(job: Job) {
        synchronized(lock) { yielding = true }
        try {
            while (currentCoroutineContext().isActive) {
                val next = synchronized(lock) {
                    val lookups = jobs.filter { it.state == Job.QUEUED && isLookup(it) }
                    job.waitingFor = lookups.size
                    lookups.firstOrNull()?.also(::startLocked)
                } ?: break
                run(next)
            }
        } finally {
            synchronized(lock) {
                yielding = false
                job.waitingFor = 0
            }
        }
    }

    /** A job of the lookup kinds: commands alone, each an interactive lookup (JobCommands.isLookup). */
    private fun isLookup(job: Job): Boolean =
        job.spec.run == null && job.steps.isNotEmpty() && job.steps.all { JobCommands.isLookup(it.args) }

    /** The job over; [onEnd] told before anyone awaiting it hears it ended. */
    private fun end(job: Job, state: String, failure: String? = null) {
        val over = endLocked(job, state, failure)
        runCatching { onEnd(over) }
        job.ended.complete(Unit)
    }

    private fun endLocked(job: Job, state: String, failure: String? = null): Job = synchronized(lock) {
        job.state = state
        job.finishedAt = clock()
        if (failure != null) {  // a run's: its stage that ran, else the first that waited, says why
            val stage = job.stages.firstOrNull { it.state == Job.RUNNING } ?: job.stages.firstOrNull { it.state == Job.WAITING }
            stage?.state = Job.FAILED
            stage?.detail = failure
        }
        for (stage in job.stages) {
            if (stage.state == Job.RUNNING) stage.state = if (state == Job.DONE) Job.DONE else state
            else if (stage.state == Job.WAITING) stage.state = Job.SKIPPED
        }
        for (step in job.steps) {
            if (step.state == Job.RUNNING) step.state = state
            else if (step.state == Job.WAITING) step.state = Job.SKIPPED
        }
        save(job.id)
        forget()
        idle()
        job.copy()
    }

    /** The job as it is now saved to the history, if there is one; under the queue's lock, so saves are in order. */
    private fun save(id: Int) {
        val history = history ?: return
        val job = jobs.firstOrNull { it.id == id } ?: return
        history.save(job, jobs, nextId)
    }

    /** A message's first line with something on it, trimmed; null for none. */
    private fun firstLine(message: String?): String? =
        message?.lineSequence()?.map { Py.strip(it) }?.firstOrNull { it.isNotEmpty() }

    /** Keep the last [keep] jobs over. */
    private fun forget() {
        val over = jobs.filter { !it.active }
        for (job in over.take(maxOf(0, over.size - keep))) jobs.remove(job)
    }

    /** A new job queued: busy now; true when the worker is to be started. */
    private fun gotWork(): Boolean {
        busy(true)
        if (started) return false
        started = true
        return true
    }

    private fun idle() {
        if (jobs.none { it.active }) busy(false)
    }

    private fun busy(now: Boolean) {
        if (busy == now) return
        busy = now
        onBusy(now)
    }

    /** What a running job tells its view, under the queue's lock; [worker] is the coroutine that runs it (the queue's
     * worker, or the yield that runs it in the worker's stead). */
    private inner class Context(private val job: Job, private val worker: kotlinx.coroutines.Job?) : JobContext {
        /** The command that runs now, whose output a line is; null while the job's own run runs. */
        var step: Step? = null

        /** Whether an event of [step]'s is a line of its output instead: a command that writes no progress lines
         * (JobCommands.reports: `lacuerda --artist`, `review`, any without `--progress`), whose `caracole-progress:`
         * line caracole serve keeps as output (web/jobs.py's emit). */
        private fun asLine(event: JsonObject): Boolean {
            val step = step ?: return false
            if (JobCommands.reports(step.args)) return false
            say(JobCommands.progressLine(event))
            return true
        }

        override fun stage(name: String, state: String, detail: String) {
            if (asLine(JsonObject(linkedMapOf("stage" to JsonPrimitive(name), "state" to JsonPrimitive(state),
                                              "detail" to JsonPrimitive(detail))))) return
            synchronized(lock) {
                val stage = job.stages.firstOrNull { it.name == name }
                    ?: Stage(name, name).also { job.stages = job.stages + it }
                stage.state = state
                stage.detail = detail
                if (state == Job.RUNNING) stage.runningDetail = detail
            }
        }

        /** A line of its output; one with line breaks in it is said a line at a time, as a command prints them. */
        override fun say(line: String) = synchronized(lock) {
            val step = step
            if (step == null) {
                job.said = (job.said + line.lines()).takeLast(MAX_LINES)
            } else {
                val all = step.output + line.lines()
                val over = maxOf(0, all.size - MAX_LINES)
                step.output = all.drop(over)
                step.dropped += over
            }
        }

        override fun outcome(value: JsonObject) = synchronized(lock) { job.outcome = value }

        override val isCancelled: Boolean get() = worker?.isCancelled == true

        override fun song(id: Long, display: String) {
            if (asLine(JsonObject(linkedMapOf("song" to JsonObject(linkedMapOf(
                    "id" to JsonPrimitive(id), "display" to JsonPrimitive(display))))))) return
            synchronized(lock) {
                job.songId = id
                job.songDisplay = display
            }
        }

        override fun readable(files: Map<String, String>, seconds: Double) {
            if (asLine(JsonObject(linkedMapOf("files" to JsonObject(files.mapValues { JsonPrimitive(it.value) }),
                                              "seconds" to PyJson.float(JobCommands.round3(seconds)))))) return
            synchronized(lock) {
                job.files = LinkedHashMap(files)
                if (job.secondsToSheet == null) job.secondsToSheet = seconds
            }
        }

        /** The lookups queued behind it run on this thread, in the worker's stead: under a supervisor that is the
         * worker's child, so that the queue's stop stops them (and then this job: a CancellationException) while an
         * error of theirs is never the worker's. */
        override fun yieldToQueued() {
            if (!yields(job)) return
            val link = SupervisorJob(worker)
            try {
                runBlocking(link) { yieldFrom(job) }
            } finally {
                link.cancel()  // no child of the worker's left behind
            }
        }
    }

    companion object {
        const val LIMIT = 20  // jobs waiting or running
        const val KEEP = 100  // jobs over remembered, as the history keeps them
        const val MAX_LINES = 400  // a command's output kept: its last lines
        const val QUEUE_FULL = "The queue is full: try again once it empties."  // app.py's
    }
}
