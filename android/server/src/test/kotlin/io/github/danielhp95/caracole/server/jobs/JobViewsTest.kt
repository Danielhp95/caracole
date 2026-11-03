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
import kotlinx.serialization.json.jsonObject
import org.junit.Test
import kotlin.test.assertEquals

/** jobs_routes.view on the phone: a job's view as the library page's script reads it, its line as status.py words
 * it, a sync's with its stages and outcome (§5.3). */
// The worker runs in the test's backgroundScope, whose tasks runCurrent runs (advanceUntilIdle leaves them be).
@OptIn(ExperimentalCoroutinesApi::class)
class JobViewsTest {
    private val sync = listOf("compare" to "Compare", "take" to "Take", "give" to "Give", "mirror" to "Mirror",
                              "agree" to "Agree", "index" to "Index")

    private fun TestScope.queue() = JobQueue(backgroundScope)

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
        assertEquals(listOf("queued", "Queued behind 1 request…", null),
                     line(JobViews.view(queue.job(second.id)!!, queue)))
        assertEquals("Queued behind 2 requests…", JobViews.line(queue.job(third.id)!!, 2).text)
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
        assertEquals(listOf("running", "Comparing…", null), line(JobViews.view(queue.job(job.id)!!, queue)))
        step.complete(Unit)
        runCurrent()
        assertEquals("Taking what changed there…", JobViews.line(queue.job(job.id)!!).text)  // between two stages
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
        assertEquals(Line("added", "Added: the nightly run looks for it"), JobViews.line(add))
        assertEquals(Line("added", "Added: the computer's next run fetches it."),
                     JobViews.line(run("add", "Added: the computer's next run fetches it.")))
        assertEquals(Line("removed", "Removed"), JobViews.line(run("remove")))
        assertEquals(Line("ready", "Synced"), JobViews.line(run("sync") {
            it.outcome(Json.parseToJsonElement("""{"taken":[],"given":[],"left":[],"agreed":3,"indexed":[]}""").jsonObject)
        }))
        val left = run("sync") {
            it.outcome(Json.parseToJsonElement(
                """{"taken":[],"given":[],"left":[["song/a/b","changed here"]],"agreed":2,"indexed":[]}""").jsonObject)
        }
        assertEquals(Line("waiting", "Synced: 1 change left as it was", details = "#tab=requests&job=${left.id}"),
                     JobViews.line(left))
        // A failure: its failed stage's first sentence, else its error line's, else its title's.
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
        assertEquals("add it failed.", JobViews.line(fakeFailed(add)).text)
        val long = "word ".repeat(60).trim()
        val cut = JobViews.line(run("add") { throw IllegalStateException(long) }).text
        assertEquals(("word ".repeat(31).trim()) + "…", cut)  // 159 characters at most, cut at a word
    }

    /** A job over as failed, with nothing said. */
    private fun fakeFailed(job: Job): Job = job.copy().also { it.state = Job.FAILED; it.output = emptyList() }

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
            "state":"done","fetching":false,"line":{"tone":"ready","text":"Synced","link":null,"details":null},
            "details":"#tab=sync","steps":[{"name":"compare","label":"Compare","state":"done","detail":""},
            {"name":"take","label":"Take","state":"done","detail":""},{"name":"give","label":"Give","state":"done","detail":""},
            {"name":"mirror","label":"Mirror","state":"done","detail":""},{"name":"agree","label":"Agree","state":"done","detail":""},
            {"name":"index","label":"Index","state":"skipped","detail":"no index newer"}],"count":null,
            "outcome":{"taken":["song/a/b"],"given":[],"left":[],"agreed":12,"indexed":[]}}"""), view)
        // queued, its stages waiting and no outcome yet
        val next = queue.submit(JobSpec("Sync with Laptop", "sync:http://laptop:8737", "sync", sync) {}).first
        val waiting = JobViews.view(next, queue)
        assertEquals(JsonNull, waiting["outcome"])
        assertEquals(List(6) { "waiting" }, (waiting["steps"] as JsonArray).map {
            (it.jsonObject["state"] as JsonPrimitive).content
        })
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
        val removal = queue.submit(JobSpec("Remove Radiohead - Creep", "remove:radiohead/creep", "remove", emptyList(),
                                           display = "Radiohead - Creep", songId = 9, join = false) {}).first
        val removing = JobViews.view(removal, queue)
        assertEquals(JsonPrimitive("remove"), removing["kind"])
        assertEquals(JsonPrimitive(9), removing["songId"])
        assertEquals(JsonPrimitive("radiohead/creep"), removing["identity"])
    }
}
