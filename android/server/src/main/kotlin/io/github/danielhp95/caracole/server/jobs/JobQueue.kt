package io.github.danielhp95.caracole.server.jobs

import io.github.danielhp95.caracole.server.http.Refused
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.channels.Channel
import kotlinx.coroutines.currentCoroutineContext
import kotlinx.coroutines.launch
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import java.time.Instant
import java.time.ZoneOffset
import java.time.format.DateTimeFormatter

/**
 * A job to queue: what it is ([title], and [display], what the page names it by: its title when empty), the key it is
 * queued under ([key]: a waiting job of the same key is the answer to another, when [join]), what it is about ([kind]:
 * add, remove, sync, index), its stages (name, label) as the page shows them, the song it is about when that is known
 * before it runs ([songId]: a removal's), and what it runs, on the queue's one worker. [doneLine]: what its line says
 * once it is done, in place of its kind's words ("Added: the computer's next run fetches it.").
 */
data class JobSpec(val title: String, val key: String, val kind: String, val stages: List<Pair<String, String>>,
                   val display: String = "", val songId: Long? = null, val join: Boolean = true,
                   val doneLine: String? = null, val run: suspend (JobContext) -> Unit)

/** What a running job tells its view: a stage's state and what it says now, a line of its output (an `error: …`
 * line is what its line says should it fail), its outcome (the view's `outcome`), and the song it turned out to be
 * about (an add's, once added), as `caracole get --progress`'s events tell caracole serve's. */
interface JobContext {
    fun stage(name: String, state: String, detail: String = "")
    fun say(line: String)
    fun outcome(value: JsonObject)
    val isCancelled: Boolean
    fun song(id: Long, display: String) {}
}

/** A stage of a job: its state (waiting, running, done, skipped, failed, interrupted) and what it says now. */
class Stage internal constructor(val name: String, val label: String) {
    var state: String = Job.WAITING
        internal set
    var detail: String = ""
        internal set

    internal fun copy() = Stage(name, label).also { it.state = state; it.detail = detail }
}

/**
 * A job queued, running or over (web/jobs.py's `Job`): its [state], queued, running, done, failed (its run threw),
 * cancelled (taken out of the queue before it ran) or interrupted (the queue's scope ended while it ran); its stages,
 * its output's last lines, its outcome and its song. The queue changes it under its lock; what a caller gets of it
 * ([JobQueue.snapshot], [JobQueue.job], [JobQueue.await]) is a copy, as caracole serve's queue hands out copies.
 */
class Job internal constructor(val id: Int, val spec: JobSpec, queuedAt: Instant = Instant.now()) {
    var state: String = QUEUED
        internal set
    var queuedAt: Instant = queuedAt
        internal set
    var startedAt: Instant? = null
        internal set
    var finishedAt: Instant? = null
        internal set
    var stages: List<Stage> = spec.stages.map { (name, label) -> Stage(name, label) }
        internal set
    var output: List<String> = emptyList()
        internal set
    var outcome: JsonObject? = null
        internal set
    var songId: Long? = spec.songId
        internal set
    var songDisplay: String? = if (spec.songId != null) spec.display.ifEmpty { spec.title } else null
        internal set

    /** Whether it waits or runs. */
    val active: Boolean get() = state == QUEUED || state == RUNNING

    /** What the page names it by. */
    val display: String get() = spec.display.ifEmpty { spec.title }

    internal val ended = CompletableDeferred<Unit>()

    internal fun copy(): Job = Job(id, spec, queuedAt).also {
        it.state = state
        it.startedAt = startedAt
        it.finishedAt = finishedAt
        it.stages = stages.map(Stage::copy)
        it.output = output
        it.outcome = outcome
        it.songId = songId
        it.songDisplay = songDisplay
    }

    /** Job.as_json: the job as plain data, `/api/jobs/N`'s answer: its stages as its steps, and none of the commands
     * a job of caracole serve's runs (the phone runs none), its song once known. */
    fun asJson(): JsonObject = JsonObject(linkedMapOf(
        "id" to JsonPrimitive(id),
        "title" to JsonPrimitive(spec.title),
        "display" to JsonPrimitive(display),
        "state" to JsonPrimitive(state),
        "active" to JsonPrimitive(active),
        "note" to JsonPrimitive(""),
        "queued_at" to stamp(queuedAt),
        "started_at" to stamp(startedAt),
        "finished_at" to stamp(finishedAt),
        "steps" to JsonArray(stages.map { stage ->
            JsonObject(linkedMapOf("name" to JsonPrimitive(stage.name), "label" to JsonPrimitive(stage.label),
                                   "state" to JsonPrimitive(stage.state), "detail" to JsonPrimitive(stage.detail)))
        }),
        "commands" to JsonArray(emptyList()),
        "song" to songId.let { song ->
            if (song == null) JsonNull
            else JsonObject(linkedMapOf("id" to JsonPrimitive(song),
                                        "display" to (songDisplay?.let(::JsonPrimitive) ?: JsonNull)))
        },
        "files" to JsonObject(emptyMap()),
        "seconds_to_sheet" to JsonNull,
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

        private val STAMP = DateTimeFormatter.ofPattern("yyyy-MM-dd'T'HH:mm:ss'Z'").withZone(ZoneOffset.UTC)

        /** A time as caracole serve writes one ("%Y-%m-%dT%H:%M:%SZ", in UTC), or null. */
        internal fun stamp(at: Instant?): JsonElement = if (at == null) JsonNull else JsonPrimitive(STAMP.format(at))
    }
}

/** The queue holds [JobQueue.limit] jobs that wait or run already (web/jobs.py's QueueFull). */
class QueueFull(val limit: Int) : Exception("$limit requests are waiting already")

/** A job asked to be cancelled that runs, or is over ([state]): a job is never stopped halfway (web/jobs.py's). */
class JobStarted(val id: Int, val state: String) : Exception("request $id is $state")

/**
 * web/jobs.py's JobQueue on the phone: jobs in order, run by one worker coroutine in [scope], so they never write
 * beside each other (an index import, a sync, an add: §5.5).
 *
 * - [submit]: one job per key: a job of the same key that still waits is the answer to another that may join it
 *   (JobSpec.join); else a job of its own, unless [limit] jobs wait or run already ([QueueFull]).
 * - [cancel]: a job that hasn't started taken out of the queue, over as "cancelled", its stages skipped; one that runs
 *   or is over is never stopped ([JobStarted]).
 * - A job's run that throws fails it, what it threw said as its last line (`error: …`); one the scope's end stops is
 *   interrupted. Either way its stages left running end so too, and those waiting are skipped, as caracole serve's.
 * - The last [keep] jobs over are remembered, in memory alone (the phone keeps no history).
 * - [onBusy]: told true as the queue gets a job to run, and false once none waits or runs (the app's foreground
 *   service listens); told under the queue's lock, so in order: it must not block.
 */
class JobQueue(private val scope: CoroutineScope, val limit: Int = LIMIT, val keep: Int = KEEP,
               private val clock: () -> Instant = { Instant.now() }) {
    private val lock = Any()
    private val jobs = ArrayList<Job>()  // oldest first, as queued
    private var nextId = 1
    private val wake = Channel<Unit>(Channel.CONFLATED)
    private var started = false
    private var busy = false

    /** Told true as the queue gets busy and false as it goes idle (the app's foreground service listens). */
    var onBusy: (Boolean) -> Unit = {}

    /** The job, and whether it is new (false: a waiting job of the same key that joins). */
    fun submit(spec: JobSpec): Pair<Job, Boolean> {
        var start = false
        val job = synchronized(lock) {
            val waiting = jobs.firstOrNull { spec.join && it.state == Job.QUEUED && it.spec.key == spec.key }
            if (waiting != null) return waiting.copy() to false
            if (jobs.count { it.active } >= limit) throw QueueFull(limit)
            val job = Job(nextId++, spec, clock())
            jobs.add(job)
            start = !started
            started = true
            busy(true)
            job.copy()
        }
        if (start) scope.launch { work() }  // the one worker, started outside the lock
        wake.trySend(Unit)
        return job to true
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

    /** How many jobs wait or run before [job], queued as it waits ("Queued behind 2 requests…"). */
    fun ahead(job: Job): Int = synchronized(lock) { jobs.count { it.active && it.id < job.id } }

    /**
     * A job that hasn't started taken out of the queue, over and never run, and given back as a copy; null for one
     * never queued, cancelled already or forgotten. [JobStarted] for one that runs or is over.
     */
    fun cancel(id: Int): Job? = synchronized(lock) {
        val job = jobs.firstOrNull { it.id == id } ?: return null
        if (job.state == Job.CANCELLED) return null
        if (job.state != Job.QUEUED) throw JobStarted(id, job.state)
        job.state = Job.CANCELLED
        job.finishedAt = clock()
        for (stage in job.stages) stage.state = Job.SKIPPED
        job.ended.complete(Unit)
        forget()
        idle()
        job.copy()
    }

    /** The job once it is over, as a copy; [NoSuchElementException] for one the queue doesn't remember. */
    suspend fun await(id: Int): Job {
        val job = synchronized(lock) { jobs.firstOrNull { it.id == id } }
            ?: throw NoSuchElementException("no request $id")
        job.ended.await()
        return synchronized(lock) { job.copy() }
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
        }
    }

    private fun next(): Job? = synchronized(lock) {
        jobs.firstOrNull { it.state == Job.QUEUED }?.also {
            it.state = Job.RUNNING
            it.startedAt = clock()
        }
    }

    private suspend fun run(job: Job) {
        val running = currentCoroutineContext()[kotlinx.coroutines.Job]
        val context = Context(job) { running?.isCancelled == true }
        try {
            job.spec.run(context)
            end(job, Job.DONE)
        } catch (e: CancellationException) {
            end(job, Job.INTERRUPTED)
            throw e
        } catch (e: Exception) {
            context.say("error: ${e.message?.takeIf { it.isNotBlank() } ?: e::class.simpleName}")
            end(job, Job.FAILED)
        }
    }

    private fun end(job: Job, state: String) = synchronized(lock) {
        job.state = state
        job.finishedAt = clock()
        for (stage in job.stages) {
            if (stage.state == Job.RUNNING) stage.state = if (state == Job.DONE) Job.DONE else state
            else if (stage.state == Job.WAITING) stage.state = Job.SKIPPED
        }
        job.ended.complete(Unit)
        forget()
        idle()
    }

    /** Keep the last [keep] jobs over. */
    private fun forget() {
        val over = jobs.filter { !it.active }
        for (job in over.take(maxOf(0, over.size - keep))) jobs.remove(job)
    }

    private fun idle() {
        if (jobs.none { it.active }) busy(false)
    }

    private fun busy(now: Boolean) {
        if (busy == now) return
        busy = now
        onBusy(now)
    }

    /** What a running job tells its view, under the queue's lock. */
    private inner class Context(private val job: Job, private val cancelled: () -> Boolean) : JobContext {
        override fun stage(name: String, state: String, detail: String) = synchronized(lock) {
            val stage = job.stages.firstOrNull { it.name == name }
                ?: Stage(name, name).also { job.stages = job.stages + it }
            stage.state = state
            stage.detail = detail
        }

        override fun say(line: String) = synchronized(lock) {
            job.output = (job.output + line).takeLast(MAX_LINES)
        }

        override fun outcome(value: JsonObject) = synchronized(lock) { job.outcome = value }

        override val isCancelled: Boolean get() = cancelled()

        override fun song(id: Long, display: String) = synchronized(lock) {
            job.songId = id
            job.songDisplay = display
        }
    }

    companion object {
        const val LIMIT = 20  // jobs waiting or running
        const val KEEP = 100  // jobs over remembered
        const val MAX_LINES = 400  // a job's output kept: its last lines
        const val QUEUE_FULL = "The queue is full: try again once it empties."  // app.py's
    }
}
