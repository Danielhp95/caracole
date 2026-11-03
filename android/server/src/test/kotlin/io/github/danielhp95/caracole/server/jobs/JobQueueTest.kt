package io.github.danielhp95.caracole.server.jobs

import io.github.danielhp95.caracole.server.http.Refused
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.cancel
import kotlinx.coroutines.delay
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.test.StandardTestDispatcher
import kotlinx.coroutines.test.TestScope
import kotlinx.coroutines.test.runCurrent
import kotlinx.coroutines.test.runTest
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import org.junit.Test
import java.time.Instant
import java.util.concurrent.atomic.AtomicInteger
import kotlin.concurrent.thread
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith
import kotlin.test.assertFalse
import kotlin.test.assertNull
import kotlin.test.assertSame
import kotlin.test.assertTrue

/** web/jobs.py's queue on the phone: one worker, one job at a time, one job per key, cancel, the jobs remembered,
 * and busy and idle told as they come; on a test's clock. */
// The worker runs in the test's backgroundScope, whose tasks runCurrent runs (advanceUntilIdle leaves them be).
@OptIn(ExperimentalCoroutinesApi::class)
class JobQueueTest {
    private var now = Instant.parse("2026-11-03T12:00:00Z")
    private val clock = { now.also { now = now.plusSeconds(1) } }

    private fun spec(key: String, kind: String = "add", join: Boolean = true,
                     stages: List<Pair<String, String>> = listOf("add" to "Adding to the library"),
                     run: suspend (JobContext) -> Unit = {}) =
        JobSpec(title = "Add $key", key = key, kind = kind, stages = stages, display = key, join = join, run = run)

    private fun TestScope.queue(limit: Int = JobQueue.LIMIT, keep: Int = JobQueue.KEEP) =
        JobQueue(backgroundScope, limit, keep, clock)

    @Test fun aJobRunsOnTheWorkerItsStagesAndOutcomeAsItSaysThem() = runTest {
        val queue = queue()
        val (job, new) = queue.submit(spec("radiohead/creep") { context ->
            context.stage("add", "running")
            context.song(7, "Radiohead - Creep")
            context.stage("add", "done", "added")
            context.outcome(JsonObject(mapOf("added" to JsonPrimitive(true))))
        })
        assertTrue(new)
        assertEquals(Job.QUEUED, job.state)
        val over = queue.await(job.id)
        assertEquals(Job.DONE, over.state)
        assertEquals(listOf("done" to "added"), over.stages.map { it.state to it.detail })
        assertEquals(JsonObject(mapOf("added" to JsonPrimitive(true))), over.outcome)
        assertEquals(Job.QUEUED, job.state)  // what the queue gave back is a copy, as caracole serve's
        assertEquals(Json.parseToJsonElement("""{"id":1,"title":"Add radiohead/creep","display":"radiohead/creep",
            "state":"done","active":false,"note":"","queued_at":"2026-11-03T12:00:00Z",
            "started_at":"2026-11-03T12:00:01Z","finished_at":"2026-11-03T12:00:02Z",
            "steps":[{"name":"add","label":"Adding to the library","state":"done","detail":"added"}],"commands":[],
            "song":{"id":7,"display":"Radiohead - Creep"},"files":{},"seconds_to_sheet":null}"""), over.asJson())
        // A stage it names that its spec didn't is one more, named by itself.
        val more = queue.submit(spec("muse/hysteria") { it.stage("pages", "done") }).first
        assertEquals(listOf("add" to "skipped", "pages" to "done"), queue.await(more.id).stages.map { it.name to it.state })
    }

    @Test fun theOneWorkerRunsOneJobAtATimeInTheOrderQueued() = runTest {
        val queue = queue()
        val gate = CompletableDeferred<Unit>()
        val log = mutableListOf<String>()
        val first = queue.submit(spec("a") { log += "a starts"; gate.await(); log += "a ends" }).first
        val second = queue.submit(spec("b") { log += "b" }).first
        val third = queue.submit(spec("c") { log += "c" }).first
        runCurrent()
        assertEquals(listOf("a starts"), log)
        assertEquals(listOf(Job.QUEUED, Job.QUEUED, Job.RUNNING), queue.snapshot().map { it.state })  // newest first
        assertEquals(listOf(1, 2), listOf(second, third).map { queue.ahead(it) })
        assertEquals(3, queue.activeCount())
        gate.complete(Unit)
        assertEquals(Job.DONE, queue.await(third.id).state)
        assertEquals(listOf("a starts", "a ends", "b", "c"), log)
        assertEquals(0, queue.activeCount())
        assertEquals(Job.DONE, queue.await(first.id).state)  // over already: at once
    }

    @Test fun aWaitingJobOfTheSameKeyIsTheAnswerToAnotherThatMayJoinIt() = runTest {
        val queue = queue()
        val gate = CompletableDeferred<Unit>()
        val running = queue.submit(spec("oasis/wonderwall") { gate.await() }).first
        runCurrent()
        val (waiting, new) = queue.submit(spec("oasis/wonderwall"))
        assertTrue(new)  // the running one never takes it in: it comes after
        assertTrue(waiting.id != running.id)
        val (joined, again) = queue.submit(spec("oasis/wonderwall"))
        assertFalse(again)
        assertEquals(waiting.id, joined.id)
        val (own, apart) = queue.submit(spec("oasis/wonderwall", join = false))
        assertTrue(apart && own.id != waiting.id)
        assertTrue(queue.submit(spec("blur/song 2")).second)  // another key: a job of its own
        gate.complete(Unit)
        runCurrent()
        assertEquals(4, queue.snapshot().size)
    }

    @Test fun aFullQueueTakesNoNewJobButAJobThatJoinsNeedsNoRoom() = runTest {
        val queue = queue(limit = 2)
        val gate = CompletableDeferred<Unit>()
        queue.submit(spec("a") { gate.await() })
        val waiting = queue.submit(spec("b")).first
        runCurrent()
        assertFailsWith<QueueFull> { queue.submit(spec("c")) }
        val refused = assertFailsWith<Refused> { queue.submitOrRefuse(spec("c")) }
        assertEquals(503 to "The queue is full: try again once it empties.", refused.status to refused.message)
        assertEquals(waiting.id, queue.submit(spec("b")).first.id)
        gate.complete(Unit)
        runCurrent()
        assertTrue(queue.submit(spec("c")).second)
    }

    @Test fun theLastJobsOverAreRememberedTheOthersForgotten() = runTest {
        val queue = queue(keep = 3)
        repeat(5) { queue.submit(spec("song/$it")) }
        runCurrent()
        assertEquals(listOf(5, 4, 3), queue.snapshot().map { it.id })
        assertNull(queue.job(1))
        assertEquals(3, queue.job(3)!!.id)
        assertFailsWith<NoSuchElementException> { queue.await(1) }
        assertEquals(6, queue.submit(spec("song/again")).first.id)  // ids go on
    }

    @Test fun cancelTakesAQueuedJobOutAndNeverStopsOneThatRunsOrIsOver() = runTest {
        val queue = queue()
        val gate = CompletableDeferred<Unit>()
        val ran = mutableListOf<String>()
        val running = queue.submit(spec("a") { gate.await() }).first
        val queued = queue.submit(spec("b", stages = listOf("one" to "One", "two" to "Two")) { ran += "b" }).first
        runCurrent()
        val cancelled = queue.cancel(queued.id)!!
        assertEquals(Job.CANCELLED, cancelled.state)
        assertEquals(listOf(Job.SKIPPED, Job.SKIPPED), cancelled.stages.map { it.state })
        assertEquals(Instant.parse("2026-11-03T12:00:03Z"), cancelled.finishedAt)
        assertNull(queue.cancel(queued.id))  // cancelled already
        assertNull(queue.cancel(99))  // never queued
        assertEquals(Job.RUNNING, assertFailsWith<JobStarted> { queue.cancel(running.id) }.state)
        gate.complete(Unit)
        runCurrent()
        assertEquals(Job.DONE, assertFailsWith<JobStarted> { queue.cancel(running.id) }.state)
        assertEquals(emptyList(), ran)
        assertEquals(Job.CANCELLED, queue.await(queued.id).state)  // a page that follows it hears that it ended
        // A cancelled job of a key is no answer to the next of that key.
        assertTrue(queue.submit(spec("b")).second)
    }

    @Test fun aRunThatThrowsFailsItsJobWhatItThrewItsLastLineAndTheQueueGoesOn() = runTest {
        val queue = queue()
        val failing = queue.submit(spec("a", kind = "sync", stages = listOf("compare" to "Compare", "take" to "Take")) {
            it.stage("compare", "running")
            it.say("asking the computer")
            throw IllegalStateException("The computer can't be reached. Is caracole serve running?")
        }).first
        val next = queue.submit(spec("b")).first
        runCurrent()
        val over = queue.job(failing.id)!!
        assertEquals(Job.FAILED, over.state)
        assertEquals(listOf(Job.FAILED, Job.SKIPPED), over.stages.map { it.state })
        assertEquals(listOf("asking the computer", "error: The computer can't be reached. Is caracole serve running?"),
                     over.output)
        assertEquals(Job.DONE, queue.job(next.id)!!.state)
    }

    @Test fun aJobTheScopesEndStopsIsInterruptedAndToldSo() = runTest {
        val scope = CoroutineScope(StandardTestDispatcher(testScheduler) + SupervisorJob())
        val queue = JobQueue(scope, clock = clock)
        var told: Boolean? = null
        val job = queue.submit(spec("a", stages = listOf("take" to "Take", "agree" to "Agree")) { context ->
            context.stage("take", "running")
            try {
                CompletableDeferred<Unit>().await()
            } finally {
                told = context.isCancelled
            }
        }).first
        runCurrent()
        assertEquals(Job.RUNNING, queue.job(job.id)!!.state)
        scope.cancel()
        runCurrent()
        val over = queue.job(job.id)!!
        assertEquals(Job.INTERRUPTED, over.state)
        assertEquals(listOf(Job.INTERRUPTED, Job.SKIPPED), over.stages.map { it.state })
        assertEquals(true, told)
    }

    @Test fun busyIsToldAsTheQueueGetsAJobAndIdleOnceNoneWaitsOrRuns() = runTest {
        val queue = queue()
        val told = mutableListOf<Boolean>()
        queue.onBusy = { told += it }
        val gate = CompletableDeferred<Unit>()
        queue.submit(spec("a") { gate.await() })
        queue.submit(spec("b"))
        assertEquals(listOf(true), told)
        gate.complete(Unit)
        runCurrent()
        assertEquals(listOf(true, false), told)
        val held = CompletableDeferred<Unit>()
        queue.submit(spec("c") { held.await() })
        val last = queue.submit(spec("d")).first
        runCurrent()
        queue.cancel(last.id)
        assertEquals(listOf(true, false, true), told)  // c still runs
        held.complete(Unit)
        runCurrent()
        assertEquals(listOf(true, false, true, false), told)
        val only = queue.submit(spec("e")).first
        queue.cancel(only.id)  // never ran: idle at once
        assertEquals(listOf(true, false, true, false, true, false), told)
    }

    @Test fun aJobIsWhatItsSpecSays() = runTest {
        val queue = queue()
        val spec = JobSpec(title = "Remove Radiohead - Creep", key = "remove:radiohead/creep", kind = "remove",
                           stages = emptyList(), display = "Radiohead - Creep", songId = 4) {}
        val job = queue.submit(spec).first
        assertSame(spec, job.spec)
        assertEquals(4L, job.songId)
        assertEquals("Radiohead - Creep", job.display)
        assertEquals(Json.parseToJsonElement("""{"id":4,"display":"Radiohead - Creep"}"""), job.asJson()["song"])
        assertEquals("Add x", queue.submit(spec("x").copy(display = "")).first.display)
    }

    @Test fun onRealThreadsTheJobsSubmittedFromManyRunOneAtATimeEachOnce() = runBlocking {
        val scope = CoroutineScope(Dispatchers.Default + SupervisorJob())
        val queue = JobQueue(scope, limit = 200)
        val running = AtomicInteger()
        val most = AtomicInteger()
        val ran = AtomicInteger()
        val ids = java.util.Collections.synchronizedList(mutableListOf<Int>())
        val threads = (0 until 8).map { t ->
            thread {
                repeat(10) { i ->
                    ids += queue.submit(spec("song/$t/$i") {
                        most.accumulateAndGet(running.incrementAndGet(), ::maxOf)
                        delay(1)
                        running.decrementAndGet()
                        ran.incrementAndGet()
                    }).first.id
                }
            }
        }
        threads.forEach { it.join() }
        for (id in ids) queue.await(id)
        assertEquals(80, ran.get())
        assertEquals(1, most.get())
        assertEquals((1..80).toList(), ids.sorted())
        assertEquals(0, queue.activeCount())
        scope.cancel()
    }
}
