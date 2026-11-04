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
            "song":{"id":7,"display":"Radiohead - Creep"},"files":{},"seconds_to_sheet":null,"units":[]}"""),
            over.asJson())
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

    @Test fun aJobOfTheSameKeyThatWaitsOrRunsIsTheAnswerToAnotherThatMayJoinIt() = runTest {
        val queue = queue()
        val gate = CompletableDeferred<Unit>()
        val running = queue.submit(spec("oasis/wonderwall") { gate.await() }).first
        runCurrent()
        val (same, new) = queue.submit(spec("oasis/wonderwall"))  // a second Remove from another device, say
        assertFalse(new)  // as caracole serve's queue answers a request that fetches nothing: the one that runs
        assertEquals(running.id, same.id)
        // One that mustn't join: the song's job is its answer, left as it is (web/jobs.py's join=False).
        val (own, apart) = queue.submit(spec("oasis/wonderwall", join = false))
        assertFalse(apart)
        assertEquals(running.id, own.id)
        val (joined, again) = queue.submit(spec("oasis/wonderwall"))
        assertFalse(again)
        assertEquals(running.id, joined.id)  // the oldest of the key's
        assertTrue(queue.submit(spec("blur/song 2")).second)  // another key: a job of its own
        gate.complete(Unit)
        runCurrent()
        assertEquals(2, queue.snapshot().size)
        assertTrue(queue.submit(spec("oasis/wonderwall")).second)  // over: the next is a job of its own
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
        assertEquals(1, queue.submit(spec("a")).first.id)  // so does one that joins the job that runs
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

    @Test fun aFailureIsSaidByTheStageThatRanNeverWhatItSaidWhileItRanAndInItsFirstLine() = runTest {
        val queue = queue()
        val failing = queue.submit(spec("a", kind = "sync", stages = listOf("compare" to "Compare", "take" to "Take")) {
            it.stage("compare", "done", "4 differences")
            it.stage("take", "running", "song/radiohead/creep")
            throw IllegalStateException("\nSQLITE_BUSY: the database is locked\n  at Take.applyUnits(Take.kt:88)")
        }).first
        val between = queue.submit(spec("b", kind = "sync", stages = listOf("compare" to "Compare", "take" to "Take")) {
            it.stage("compare", "done")
            throw IllegalStateException("The computer stopped answering.")
        }).first
        runCurrent()
        val over = queue.job(failing.id)!!
        assertEquals(listOf("done" to "4 differences", "failed" to "SQLITE_BUSY: the database is locked"),
                     over.stages.map { it.state to it.detail })
        assertEquals("song/radiohead/creep", over.stages[1].runningDetail)
        assertEquals("error: SQLITE_BUSY: the database is locked", over.output.last())
        assertEquals("SQLITE_BUSY: the database is locked.", JobViews.line(over).text)
        val next = queue.job(between.id)!!  // between two stages: the next one says why
        assertEquals(listOf("done" to "", "failed" to "The computer stopped answering."),
                     next.stages.map { it.state to it.detail })
        assertEquals("The computer stopped answering.", JobViews.line(next).text)
    }

    private fun deep(n: Int): Int = deep(n + 1) + 1  // a StackOverflowError, as a bug's

    @Test fun aRunsOwnTimeoutAndAnErrorItThrowsFailItsJobAloneAndTheWorkerGoesOn() = runTest {
        val queue = queue()
        val told = mutableListOf<Boolean>()
        queue.onBusy = { told += it }
        val timedOut = queue.submit(spec("a", kind = "sync", stages = listOf("give" to "Give")) {
            it.stage("give", "running")
            kotlinx.coroutines.withTimeout(10_000) { CompletableDeferred<Unit>().await() }  // the push never taken
        }).first
        val todo = queue.submit(spec("b") { TODO("not built yet") }).first  // as a skeleton's neutral stub throws
        val overflow = queue.submit(spec("c") { deep(0) }).first
        val next = queue.submit(spec("d")).first
        runCurrent()
        testScheduler.advanceTimeBy(10_001)
        runCurrent()
        assertEquals(Job.FAILED, queue.job(timedOut.id)!!.state)
        assertTrue(queue.job(timedOut.id)!!.output.last().startsWith("error: Timed out "))  // the test clock's words
        assertEquals("error: An operation is not implemented: not built yet", queue.job(todo.id)!!.output.last())
        assertEquals("error: StackOverflowError", queue.job(overflow.id)!!.output.last())
        assertEquals(Job.FAILED, queue.await(overflow.id).state)  // await never hangs on one
        assertEquals(Job.DONE, queue.job(next.id)!!.state)  // the worker went on
        assertEquals(0, queue.activeCount())
        assertEquals(listOf(true, false), told)  // and the queue went idle
        assertTrue(queue.submit(spec("e")).second)
        runCurrent()
        assertEquals(Job.DONE, queue.snapshot().first().state)
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

    // --- jobs of commands -------------------------------------------------------------------------------------

    private fun lookup(artist: String, title: String, songbooks: Boolean = true) = JobSpec(
        title = "Get $artist - $title", key = "${artist.lowercase()}/${title.lowercase()}", kind = "song",
        stages = emptyList(), commands = JobCommands.lookupSteps(artist, title, songbooks = songbooks), fetching = true)

    private fun search(query: String, auto: Boolean) = JobSpec(
        title = "LaCuerda's search for $query", key = JobCommands.LACUERDA_SEARCH + query, kind = "lacuerda-search",
        stages = emptyList(), commands = JobCommands.lacuerdaSearchSteps(query, auto))

    private fun TestScope.queue(commands: Map<String, CommandRunner>, history: JobHistory? = null) =
        JobQueue(backgroundScope, clock = clock, commands = Commands(commands), history = history)

    @Test fun aJobsCommandsRunOneAfterAnotherEachByItsRunnerTheirStatesAsCaracoleServes() = runTest {
        val ran = mutableListOf<List<String>>()
        val queue = queue(mapOf(
            "get" to CommandRunner { args, context ->
                ran += args
                context.stage("song", "running")
                context.say("get: Radiohead - Creep is in the library")
                context.stage("song", "done", "in the library")
                context.readable(mapOf("sheet" to "Radiohead/Creep/sheet.txt"), 2.5)
            },
            "versions" to CommandRunner { args, _ -> ran += args; throw CommandExit(2, "No such version.") },
        ))
        val job = queue.submit(lookup("Radiohead", "Creep")).first
        assertEquals(JobCommands.GET_STAGES.map { it.first }, job.stages.map { it.name })  // its commands' stages
        val over = queue.await(job.id)
        assertEquals(Job.DONE, over.state)
        assertEquals(listOf(Job.DONE to 0), over.steps.map { it.state to it.code })
        assertEquals(listOf("get: Radiohead - Creep is in the library"), over.steps[0].output)
        assertEquals(listOf("done", "skipped"), over.stages.take(2).map { it.state })
        assertEquals(mapOf("sheet" to "Radiohead/Creep/sheet.txt") to 2.5, over.files to over.secondsToSheet)
        // A command that fails: its error line said, its exit status kept, the rest skipped.
        val two = JobSpec("Keep it, then look it up", "a/t", "versions", emptyList(), fetching = true,
                          commands = JobCommands.versionSteps("A", "T", keep = "3") + JobCommands.lookupSteps("A", "T"))
        val failed = queue.await(queue.submit(two).first.id)
        assertEquals(Job.FAILED, failed.state)
        assertEquals(listOf(Job.FAILED to 2, Job.SKIPPED to null), failed.steps.map { it.state to it.code })
        assertEquals(listOf("error: No such version."), failed.steps[0].output)
        assertEquals(listOf("error: No such version."), failed.output)
        // A command the phone has no runner for fails its step, as one that couldn't start.
        val none = queue.await(queue.submit(JobSpec("Match", "m", "song", emptyList(),
                                                    commands = listOf(Command("Looking it up", listOf("match"))))).first.id)
        assertEquals(listOf(Job.FAILED to null), none.steps.map { it.state to it.code })
        assertEquals(listOf("error: caracole match isn't on the phone"), none.output)
        assertEquals(2, ran.size)
    }

    @Test fun aLookupTakesThePlaceOfThePhonesOwnAddThatWaitsAndAKeepItComesAfterIt() = runTest {
        val log = mutableListOf<String>()
        val queue = queue(mapOf("get" to CommandRunner { _, _ -> log += "get" },
                                "versions" to CommandRunner { _, _ -> log += "versions" }))
        val gate = CompletableDeferred<Unit>()
        queue.submit(spec("hold") { gate.await() })
        val add = queue.submit(spec("radiohead/creep") { log += "add Creep" }).first
        val (joined, new) = queue.submit(lookup("Radiohead", "Creep"))
        assertFalse(new)
        assertEquals(add.id, joined.id)
        assertEquals(null, joined.spec.run)  // `caracole get` adds the song itself
        assertEquals("song" to "Get Radiohead - Creep", joined.spec.kind to joined.title)
        assertTrue(joined.fetching)
        assertEquals(listOf("get"), joined.steps.map { it.args[0] })
        assertEquals(JobCommands.GET_STAGES.map { it.first }, joined.stages.map { it.name })
        val other = queue.submit(spec("muse/hysteria") { log += "add Hysteria" }).first
        val keep = JobSpec("Keep it", "muse/hysteria", "versions", emptyList(), fetching = true,
                           commands = JobCommands.versionSteps("Muse", "Hysteria", keep = "9"))
        assertEquals(other.id to false, queue.submit(keep).let { it.first.id to it.second })
        assertEquals(listOf("add", "song", "version", "pdf", "pages"), queue.job(other.id)!!.stages.map { it.name })
        gate.complete(Unit)
        runCurrent()
        assertEquals(listOf("get", "add Hysteria", "versions"), log)  // the add's run, then the command joined
        assertEquals(Job.DONE, queue.job(other.id)!!.state)
    }

    @Test fun tryAgainQueuesAJobOverWithItsCommandsAsTheyWereByHandAndWithItsSongbooks() = runTest {
        var fails = true
        val ran = mutableListOf<List<String>>()
        val queue = queue(mapOf(
            "get" to CommandRunner { args, _ -> ran += args; if (fails) throw CommandExit(1, "UG answered 500.") },
            "lacuerda" to CommandRunner { args, _ -> ran += args },
        ))
        val first = queue.submit(lookup("Radiohead", "Creep", songbooks = false).copy(note = "from Campfire", songId = 7))
            .first
        val searched = queue.submit(search("tu calorro", auto = true)).first
        assertFailsWith<JobNotOver> { queue.again(first.id) }  // still waiting
        assertFailsWith<NoSuchElementException> { queue.again(99) }
        runCurrent()
        assertEquals(Job.FAILED, queue.job(first.id)!!.state)
        fails = false
        val again = queue.again(first.id)
        assertTrue(again.id > searched.id)
        assertEquals(listOf("get", "--progress", "--", "Radiohead", "Creep"), again.steps.single().args)
        assertEquals(listOf("Get Radiohead - Creep", "from Campfire"), listOf(again.title, again.note))
        assertEquals(7L, again.songId)
        assertEquals(again.id, queue.again(first.id).id)  // the song's lookup that waits is its answer
        assertEquals(listOf("lacuerda", "--search=tu calorro", "--progress"), queue.again(searched.id).steps.single().args)
        runCurrent()
        assertEquals(listOf(listOf("get", "--progress", "--no-songbooks", "--", "Radiohead", "Creep"),
                            listOf("lacuerda", "--search=tu calorro", "--progress", "--auto"),
                            listOf("get", "--progress", "--", "Radiohead", "Creep"),
                            listOf("lacuerda", "--search=tu calorro", "--progress")), ran)
        // A job of the phone's own runs its run again.
        var runs = 0
        val own = queue.submit(spec("blur/song 2") { runs++ }).first
        runCurrent()
        queue.await(queue.again(own.id).id)
        assertEquals(2, runs)
    }

    @Test fun onEndIsToldOnceAJobIsOverCancelledOnesTooEachOfThoseQueuedTogether() = runTest {
        val queue = queue(mapOf("get" to CommandRunner { _, _ -> }))
        val told = mutableListOf<Pair<Int, String>>()
        queue.onEnd = { told += it.id to it.state }
        val gate = CompletableDeferred<Unit>()
        val held = queue.submit(spec("hold") { gate.await() }).first
        val together = queue.submitAll(listOf(lookup("A", "1"), lookup("B", "1"), lookup("C", "1")))
        assertEquals(listOf(true, true, true), together.map { it.second })
        assertEquals(together.map { it.first.id }, queue.job(together[1].first.id)!!.together)
        val failing = queue.submit(spec("failing") { throw IllegalStateException("no") }).first
        runCurrent()
        queue.cancel(together[1].first.id)
        assertEquals(together.map { it.first.id to Job.CANCELLED }, told)
        gate.complete(Unit)
        runCurrent()
        assertEquals(together.map { it.first.id to Job.CANCELLED } + listOf(held.id to Job.DONE, failing.id to Job.FAILED),
                     told)
    }

    @Test fun submitAllQueuesAllOrNoneAndAJobItJoinedIsAsItWas() = runTest {
        val queue = JobQueue(backgroundScope, limit = 3, clock = clock)
        val gate = CompletableDeferred<Unit>()
        queue.submit(spec("hold") { gate.await() })
        val add = queue.submit(spec("a/1") {}).first
        assertFailsWith<QueueFull> { queue.submitAll(listOf(lookup("A", "1"), lookup("B", "1"), lookup("C", "1"))) }
        assertEquals(listOf(1, 2), queue.snapshot().map { it.id }.reversed())
        val restored = queue.job(add.id)!!
        assertEquals("add" to 0, restored.spec.kind to restored.steps.size)  // as it was
        assertTrue(restored.spec.run != null)
        assertEquals(3, queue.submit(lookup("B", "1")).first.id)  // ids as they were
    }

    // --- a long job yields --------------------------------------------------------------------------------------

    @Test fun aLongJobLetsTheLookupsQueuedMeanwhileGoFirstThenGoesOn() = runTest {
        val log = mutableListOf<String>()
        lateinit var queue: JobQueue
        var render = 0
        val waiting = mutableListOf<Int>()
        queue = queue(mapOf(
            "get" to CommandRunner { args, context ->
                waiting += queue.job(render)!!.waitingFor
                log += "get ${args.last()}"
                if (args.last() == "1") queue.submit(lookup("D", "4"))  // queued meanwhile: it runs too
                context.yieldToQueued()  // a lookup's own: nothing
            },
            "lacuerda" to CommandRunner { _, _ -> log += "search" },
        ))
        val songs = CompletableDeferred<Unit>()
        render = queue.submit(JobSpec("Make the pages again", "render:b1", "render", listOf("render" to "Making the pages")) {
            context ->
            context.stage("render", "running", "1 of 2")
            log += "song 1"
            songs.await()
            context.yieldToQueued()
            log += "song 2"
            context.stage("render", "done")
        }).first.id
        runCurrent()
        val add = queue.submit(spec("muse/hysteria") { log += "add" }).first  // no lookup: it waits its turn
        queue.submit(lookup("A", "1"))
        queue.submit(search("q", auto = true))
        assertEquals(0, queue.job(render)!!.waitingFor)
        songs.complete(Unit)
        runCurrent()
        assertEquals(listOf("song 1", "get 1", "search", "get 4", "song 2", "add"), log)
        assertEquals(listOf(2, 1), waiting)  // the render waited for 2 requests, then 1
        assertEquals(Job.DONE, queue.job(render)!!.state)
        assertEquals(0, queue.job(render)!!.waitingFor)
        assertEquals(Job.DONE, queue.job(add.id)!!.state)
        assertEquals(listOf(true), queue.snapshot().map { it.state == Job.DONE }.distinct())
    }

    @Test fun aYieldWithNoLookupQueuedReturnsAtOnceAndAStoppedYieldInterruptsBoth() = runTest {
        val scope = CoroutineScope(StandardTestDispatcher(testScheduler) + SupervisorJob())
        val queue = JobQueue(scope, clock = clock, commands = Commands(mapOf("get" to CommandRunner { _, _ ->
            CompletableDeferred<Unit>().await()
        })))
        var yielded = 0
        val songs = CompletableDeferred<Unit>()
        val render = queue.submit(JobSpec("Make the pages again", "render:b1", "render", listOf("render" to "Pages")) {
            it.yieldToQueued()  // none queued
            yielded++
            songs.await()
            it.yieldToQueued()
            yielded++
        }).first
        runCurrent()
        assertEquals(1, yielded)
        val lookup = queue.submit(lookup("A", "1")).first
        songs.complete(Unit)
        runCurrent()
        assertEquals(Job.RUNNING to Job.RUNNING, queue.job(render.id)!!.state to queue.job(lookup.id)!!.state)
        assertEquals(1, queue.job(render.id)!!.waitingFor)
        scope.cancel()
        runCurrent()
        assertEquals(Job.INTERRUPTED to Job.INTERRUPTED, queue.job(render.id)!!.state to queue.job(lookup.id)!!.state)
        assertEquals(1, yielded)
    }
}

