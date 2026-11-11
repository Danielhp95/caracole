package io.github.danielhp95.caracole.server.jobs

import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.test.TestScope
import kotlinx.coroutines.test.runCurrent
import kotlinx.coroutines.test.runTest
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.int
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import kotlinx.serialization.json.longOrNull
import io.github.danielhp95.caracole.core.testing.Corpus
import io.github.danielhp95.caracole.core.testing.Misses
import io.github.danielhp95.caracole.server.testing.replays.JobViewsReplay
import org.junit.Test
import kotlin.test.assertEquals
import kotlin.test.assertTrue

/** jobs_routes.view on the phone: a job's view as the library page's script reads it, its line as status.py words
 * it, a sync's with its stages and outcome (§5.3); every record of vectors/web/job_views.jsonl, Python's view of the
 * same job, answered alike. */
// The worker runs in the test's backgroundScope, whose tasks runCurrent runs (advanceUntilIdle leaves them be).
@OptIn(ExperimentalCoroutinesApi::class)
class JobViewsTest {
    private val sync = listOf("compare" to "Comparing", "take" to "Taking what changed there",
                              "give" to "Giving what changed here", "mirror" to "Copying the computer's pages",
                              "agree" to "Noting where the books agree", "index" to "Updating the indexes")

    private fun TestScope.queue() = JobQueue(backgroundScope)

    @Test fun everyRecordOfTheVectorsIsThisViewLineAndOutcomeOfTheSameJob() {
        val misses = Misses("job views")
        JobViewsReplay.replay(misses)
        misses.assertNone()
        val kinds = (Corpus.records("web/job_views.jsonl") + Corpus.records("web/job_views_kinds.jsonl"))
            .map { it.extra.getValue("job").jsonObject.getValue("kind").jsonPrimitive.content }.toSet()
        assertTrue(kinds.containsAll(setOf("sync", "peer-push", "index-merge", "add", "remove", "song", "versions",
                                           "lacuerda-artist", "lacuerda-search", "harptabs-artist", "songbook",
                                           "review", "harmonica", "export")), "$kinds")
        assertTrue(misses.checked >= 300, "${misses.checked} records")
    }

    private fun line(view: JsonObject) = view["line"]!!.jsonObject.let {
        listOf(it["tone"], it["text"], it["details"]).map { e -> if (e is JsonNull) null else (e as JsonPrimitive).content }
    }

    @Test fun aQueuedJobSaysHowManyAreBeforeIt() = runTest {
        val queue = queue()
        val gate = CompletableDeferred<Unit>()
        val first = queue.submit(JobSpec("Add a", "a", "add", emptyList()) { gate.await() }).first
        assertEquals(listOf("queued", "Queued…", null), line(JobViews.view(first, queue)))
        val second = queue.submit(JobSpec("Add b", "b", "add", emptyList()) {}).first
        val third = queue.submit(JobSpec("Add c", "c", "add", emptyList()) {}).first
        runCurrent()
        assertEquals(listOf("queued", "Queued · 1 request ahead…", null),
                     line(JobViews.view(queue.job(second.id)!!, queue)))
        assertEquals("Queued · 2 requests ahead…", JobViews.line(queue.job(third.id)!!, 2).text)
        gate.complete(Unit)
    }

    @Test fun aRunningJobSaysItsRunningStageElseTheNextOne() = runTest {
        val queue = queue()
        val step = CompletableDeferred<Unit>()
        val gate = CompletableDeferred<Unit>()
        val job = queue.submit(JobSpec("Sync with Laptop", "sync:http://laptop:8737", "sync", sync) { context ->
            context.stage("compare", "running", "the computer's state")
            step.await()
            context.stage("compare", "done")
            gate.await()
        }).first
        runCurrent()
        assertEquals(listOf("running", "Comparing books…", null), line(JobViews.view(queue.job(job.id)!!, queue)))
        step.complete(Unit)
        runCurrent()
        assertEquals("Taking their entries…", JobViews.line(queue.job(job.id)!!).text)  // between two stages
        gate.complete(Unit)
        val labelled = queue.submit(JobSpec("Odd", "odd", "other", listOf("odd" to "Doing the odd thing")) {
            it.stage("odd", "running"); CompletableDeferred<Unit>().await()
        }).first
        val bare = queue.submit(JobSpec("Bare", "bare", "other", emptyList()) {}).first
        runCurrent()
        assertEquals("Doing the odd thing…", JobViews.line(queue.job(labelled.id)!!).text)
        assertEquals("Running…", JobViews.line(fakeRunning(bare)).text)
    }

    /** A job as it runs, with no stage at all. */
    private fun fakeRunning(job: Job): Job = job.copy().also { it.state = Job.RUNNING }

    @Test fun aJobOverSaysHowItEnded() = runTest {
        val queue = queue()
        fun run(kind: String, doneLine: String? = null, block: suspend (JobContext) -> Unit = {}): Job {
            val job = queue.submit(JobSpec("$kind it", "$kind:${queue.snapshot().size}", kind,
                                           listOf("one" to "One"), doneLine = doneLine, run = block)).first
            runCurrent()
            return queue.job(job.id)!!
        }
        val add = run("add")
        assertEquals(Line("added", "Added · fetched tonight"), JobViews.line(add))
        assertEquals(Line("added", "Added: the computer's next run fetches it."),
                     JobViews.line(run("add", "Added: the computer's next run fetches it.")))
        assertEquals(Line("removed", "Removed"), JobViews.line(run("remove")))
        assertEquals(Line("ready", "Shared"), JobViews.line(run("sync") {
            it.outcome(Json.parseToJsonElement("""{"taken":[],"given":[],"left":[],"agreed":3,"indexed":[]}""").jsonObject)
        }))
        val left = run("sync") {
            it.outcome(Json.parseToJsonElement(
                """{"taken":[],"given":[],"left":[["song/a/b","changed here"]],"agreed":2,"indexed":[]}""").jsonObject)
        }
        assertEquals(Line("waiting", "Shared · 1 change left as it was", details = "#tab=requests&job=${left.id}"),
                     JobViews.line(left))
        // A failure: its failed stage's first sentence, else its error line's, else its command's (an add's stage's
        // label, a staged job's title).
        val stage = run("sync") {
            it.stage("one", "failed", "The computer answered 503 Service Unavailable. It may be restarting")
            throw IllegalStateException("stopped")
        }
        assertEquals(Line("failed", "The computer answered 503 Service Unavailable.",
                          details = "#tab=requests&job=${stage.id}"), JobViews.line(stage))
        assertEquals("No full stop.", JobViews.line(run("sync") {
            it.stage("one", "failed", "No full stop"); throw IllegalStateException("x")
        }).text)
        val full = "The phone's database can't be written: disk full"
        assertEquals(full, JobViews.line(run("add") { throw IllegalStateException(full) }).text)
        assertEquals("It stopped.", JobViews.line(run("add") {
            it.say("error: An earlier error.")
            throw IllegalStateException("It stopped. This is the rest")
        }).text)  // the last error line, as status.py reads a command's output
        assertEquals("One failed.", JobViews.line(fakeFailed(add)).text)
        assertEquals("sync it failed.", JobViews.line(fakeFailed(run("sync"))).text)
        assertEquals("Stopped before the end.", JobViews.line(fakeFailed(add).also {
            it.stages.forEach { stage -> stage.state = Job.DONE }
        }).text)
        val long = "word ".repeat(60).trim()
        val cut = JobViews.line(run("add") { throw IllegalStateException(long) }).text
        assertEquals(("word ".repeat(31).trim()) + "…", cut)  // 159 characters at most, cut at a word
    }

    /** A job over as failed, with nothing said, its stage failed with no words. */
    private fun fakeFailed(job: Job): Job = job.copy().also {
        it.state = Job.FAILED
        it.output = emptyList()
        it.stages.forEach { stage -> stage.state = Job.FAILED; stage.detail = "" }
    }

    @Test fun aCancelledJobAndAnInterruptedOneSaySo() = runTest {
        val queue = queue()
        val gate = CompletableDeferred<Unit>()
        queue.submit(JobSpec("a", "a", "add", emptyList()) { gate.await() })
        val waiting = queue.submit(JobSpec("b", "b", "add", emptyList()) {}).first
        runCurrent()
        assertEquals(Line("cancelled", "Cancelled"), JobViews.line(queue.cancel(waiting.id)!!))
        val stopped = waiting.copy().also { it.state = Job.INTERRUPTED }
        assertEquals(Line("waiting", "Interrupted", details = "#tab=requests&job=${waiting.id}"), JobViews.line(stopped))
        gate.complete(Unit)
    }

    @Test fun aSyncsViewIsThePlansShapeItsDetailsTheSyncTab() = runTest {
        val queue = queue()
        val job = queue.submit(JobSpec("Sync with Laptop", "sync:http://laptop:8737", "sync", sync,
                                       display = "Sync with Laptop") { context ->
            for ((name, _) in sync.dropLast(1)) context.stage(name, "done")
            context.stage("index", "skipped", "no index newer")
            context.outcome(Json.parseToJsonElement(
                """{"taken":["song/a/b"],"given":[],"left":[],"agreed":12,"indexed":[]}""").jsonObject)
        }).first
        runCurrent()
        val view = JobViews.view(queue.job(job.id)!!, queue)
        assertEquals(Json.parseToJsonElement("""{"id":1,"display":"Sync with Laptop","songId":null,"kind":"sync",
            "state":"done","fetching":false,"line":{"tone":"ready","text":"Shared","link":null,"details":null},
            "details":"#tab=sync","steps":[{"name":"compare","label":"Compare","state":"done","detail":""},
            {"name":"take","label":"Take","state":"done","detail":""},{"name":"give","label":"Give","state":"done","detail":""},
            {"name":"mirror","label":"Copy","state":"done","detail":""},{"name":"agree","label":"Agree","state":"done","detail":""},
            {"name":"index","label":"Indexes","state":"skipped","detail":"no index newer"}],"count":null,
            "outcome":{"taken":["song/a/b"],"given":[],"left":[],"agreed":12,"indexed":[]}}"""), view)
        // queued, its stages waiting and no outcome yet
        val next = queue.submit(JobSpec("Sync with Laptop", "sync:http://laptop:8737", "sync", sync) {
            throw IllegalStateException("The computer stopped answering.")
        }).first
        val waiting = JobViews.view(next, queue)
        assertEquals(JsonNull, waiting["outcome"])
        assertEquals(List(6) { "waiting" }, (waiting["steps"] as JsonArray).map {
            (it.jsonObject["state"] as JsonPrimitive).content
        })
        // over, failed before it set an outcome: nothing taken, given or left, as caracole serve's says it
        runCurrent()
        assertEquals(Json.parseToJsonElement("""{"taken":[],"given":[],"left":[],"agreed":null,"indexed":[]}"""),
                     JobViews.view(queue.job(next.id)!!, queue)["outcome"])
    }

    @Test fun aSongsViewAndARemovalsNameTheSongByItsIdentityItsCardOnceOver() = runTest {
        val queue = queue()
        val add = queue.submit(JobSpec("Add Radiohead - Creep", "radiohead/creep", "add", emptyList(),
                                       display = "Radiohead - Creep") {}).first
        val queued = JobViews.view(add, queue)
        assertEquals(setOf("id", "display", "songId", "kind", "state", "fetching", "line", "details"), queued.keys)
        assertEquals(JsonPrimitive("song"), queued["kind"])
        assertEquals(JsonPrimitive("#tab=requests&job=1"), queued["details"])
        runCurrent()
        val card = JsonObject(mapOf("id" to JsonPrimitive(9), "title" to JsonPrimitive("Creep")))
        val songbooks = JsonObject(mapOf("books" to JsonArray(emptyList())))
        val over = JobViews.view(queue.job(add.id)!!, queue, card = card, songbooks = songbooks)
        assertEquals(JsonPrimitive(9), over["songId"])
        assertEquals(JsonPrimitive("radiohead/creep"), over["identity"])
        assertEquals(card, over["card"])
        assertEquals(songbooks, over["songbooks"])
        assertEquals(listOf("songbooks", "card"), over.keys.toList().takeLast(2))  // jobs_routes.views' order
        val removal = queue.submit(JobSpec("Remove Radiohead - Creep", "remove:radiohead/creep", "remove", emptyList(),
                                           display = "Radiohead - Creep", songId = 9, join = false) {}).first
        val removing = JobViews.view(removal, queue)
        assertEquals(JsonPrimitive("remove"), removing["kind"])
        assertEquals(JsonPrimitive(9), removing["songId"])
        assertEquals(JsonPrimitive("radiohead/creep"), removing["identity"])
    }

    /** A job of PhoneKinds' [kind], run by [block]. */
    private fun TestScope.phoneJob(queue: JobQueue, kind: PhoneKinds.Kind, key: String,
                                   block: suspend (JobContext) -> Unit): Job =
        queue.submit(JobSpec(kind.title, kind.key + key, kind.kind, listOf(kind.stage), display = kind.display,
                             run = block)).first

    @Test fun thePhonesOwnKindsSayTheirTablesWordsAsTheirRunFilledThemIn() = runTest {
        val queue = queue()
        val step = CompletableDeferred<Unit>()
        val gate = CompletableDeferred<Unit>()
        val render = PhoneKinds.RENDER
        val job = phoneJob(queue, render, "build-1") { context ->
            context.stage("render", "running")
            step.await()
            context.stage("render", "running", PhoneKinds.fill(render.running, "done" to 3, "total" to 10))
            gate.await()
            context.stage("render", "done", PhoneKinds.fill(render.done, "n" to 10))
        }
        runCurrent()
        assertEquals(Line("running", "Making the pages…"), JobViews.line(queue.job(job.id)!!))  // nothing filled yet
        step.complete(Unit)
        runCurrent()
        assertEquals(Line("running", "Remaking pages · 3 of 10"), JobViews.line(queue.job(job.id)!!))
        gate.complete(Unit)
        runCurrent()
        val over = queue.job(job.id)!!
        assertEquals(Line("ready", "Pages remade · 10 songs"), JobViews.line(over))
        val view = JobViews.view(over, queue)
        assertEquals(JsonPrimitive("render"), view["kind"])
        assertEquals(null, view["steps"])  // a line of its own, never a song's or a sync's
        assertEquals(listOf(Chip("Making the pages", "done")), Outcomes.steps(over))
        assertEquals(Outcome("ready", "Pages remade · 10 songs"),
                     Outcomes.outcome(over, JobViews.line(over), null, null))
        val failed = phoneJob(queue, render, "build-2") { context ->
            context.stage("render", "failed", PhoneKinds.fill(render.failed, "why" to "the disk is full"))
            throw IllegalStateException("Pages not made: the disk is full")
        }
        runCurrent()
        assertEquals(Line("failed", "Pages not made: the disk is full.", details = "#tab=requests&job=${failed.id}"),
                     JobViews.line(queue.job(failed.id)!!))
        // A file shared to the app: filed, or waiting for a song that fits, a wait the Requests tab says so.
        val inbox = PhoneKinds.INBOX
        val filed = phoneJob(queue, inbox, "song.gp5") { context ->
            context.stage("file", "done", PhoneKinds.fill(inbox.done, "name" to "guitar-1.gp5", "song" to "Radiohead - Creep"))
        }
        val waits = phoneJob(queue, inbox, "other.gp5") { context ->
            context.stage("file", "done", PhoneKinds.fill(inbox.otherwise!!, "name" to "other.gp5"))
        }
        runCurrent()
        assertEquals(Line("ready", "Filed · guitar-1.gp5 of Radiohead - Creep"), JobViews.line(queue.job(filed.id)!!))
        assertEquals(Line("waiting", "Waiting for its song: other.gp5", details = "#tab=requests&job=${waits.id}"),
                     JobViews.line(queue.job(waits.id)!!))
        val backing = phoneJob(queue, PhoneKinds.BACKUP, "by-hand") { context ->
            context.stage("backup", "running")
            CompletableDeferred<Unit>().await()
        }
        runCurrent()
        assertEquals(Line("running", "Backing up the book…"), JobViews.line(queue.job(backing.id)!!))
    }

    @Test fun thePhonesIndexImportSaysTheComputersIndexNotAnotherCaracolesPages() = runTest {
        val queue = queue()
        val gate = CompletableDeferred<Unit>()
        val job = queue.submit(JobSpec("Import the computer's index", "index", "index", listOf("merge" to "Merging the index"),
                                       display = "The computer's index") { context ->
            context.stage("merge", "running")
            gate.await()
            context.stage("merge", "done", "merged")
            context.outcome(Json.parseToJsonElement("""{"changed":true,"sites":["ug"]}""").jsonObject)
        }).first
        runCurrent()
        assertEquals(Line("running", "Merging the computer's index…"), JobViews.line(queue.job(job.id)!!))
        gate.complete(Unit)
        runCurrent()
        val over = queue.job(job.id)!!
        assertEquals(Line("added", "Merged"), JobViews.line(over))
        val view = JobViews.view(over, queue)
        assertEquals("Merging the index", view["steps"]!!.jsonArray.single().jsonObject["label"]!!.jsonPrimitive.content)
        assertEquals(Json.parseToJsonElement("""{"changed":true,"sites":["ug"]}"""), view["outcome"])
    }

    @Test fun aLookupOfCommandsSaysItsRunningStageAndCountsItsSteps() = runTest {
        val gate = CompletableDeferred<Unit>()
        val commands = Commands(mapOf("get" to CommandRunner { _, context ->
            context.stage("song", "done")
            context.stage("match", "done", "accepted")
            context.stage("sheet", "running", "from LaCuerda")
            gate.await()
        }))
        val queue = JobQueue(backgroundScope, commands = commands)
        val job = queue.submit(JobSpec("Fetch Soda Stereo - De música ligera", "soda stereo/de musica ligera", "song",
                                       emptyList(), display = "Soda Stereo - De música ligera", fetching = true,
                                       commands = JobCommands.lookupSteps("Soda Stereo", "De música ligera"))).first
        runCurrent()
        val view = JobViews.view(queue.job(job.id)!!, queue, facts = SongFacts())
        assertEquals("Fetching from LaCuerda…", view["line"]!!.jsonObject["text"]!!.jsonPrimitive.content)
        assertEquals(JsonPrimitive("2 of 7 done"), view["count"])
        val sheet = view["steps"]!!.jsonArray[2].jsonObject
        assertEquals(Json.parseToJsonElement("""{"name":"Sheet","source":"LaCuerda","state":"running"}"""), sheet)
        // The song new to the library, its song stage adds it, as caracole add would.
        assertEquals("Adding to the book…", Status.jobLine(fakeRunningSong(queue.job(job.id)!!), null).text)
        gate.complete(Unit)
    }

    /** A lookup with its song stage running. */
    private fun fakeRunningSong(job: Job): Job = job.copy().also {
        it.stages.forEach { stage -> stage.state = Job.WAITING }
        it.stages.first { stage -> stage.name == "song" }.state = Job.RUNNING
    }
}
