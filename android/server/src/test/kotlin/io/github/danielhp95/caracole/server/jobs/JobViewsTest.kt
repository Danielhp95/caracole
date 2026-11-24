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

    /** A request queued behind a long job of the phone's own, which the queue's one worker runs first, says which
     * and how far it has got, its words as that job's line says them (the phone's own: Python never queues one). */
    @Test fun aRequestQueuedBehindAPhonesOwnJobSaysWhatItWaitsFor() = runTest {
        val queue = queue()
        val kind = PhoneKinds.CATALOGUES
        val gate = CompletableDeferred<Unit>()
        val importing = "Importing · Ultimate Guitar · 600,000 of 1,521,145 tabs"
        val catalogues = phoneJob(queue, kind, "") { context ->
            context.stage("catalogues", "running", PhoneKinds.fill(kind.running, "doing" to importing))
            gate.await()
        }
        runCurrent()
        val lookup = queue.submit(JobSpec("Get Muse - Hysteria", "muse/hysteria", "song", emptyList(),
                                          commands = JobCommands.lookupSteps("Muse", "Hysteria"), fetching = true)).first
        val add = queue.submit(JobSpec("Add b", "b", "add", emptyList()) {}).first
        assertEquals(listOf("queued", "Queued · after the site catalogues ($importing)", null),
                     line(JobViews.view(queue.job(lookup.id)!!, queue)))
        assertEquals(listOf("queued", "Queued · 2 requests ahead, now the site catalogues ($importing)", null),
                     line(JobViews.view(queue.job(add.id)!!, queue)))
        // Its line alone, given the jobs (the Requests tab's and /jobs.json's).
        val jobs = queue.snapshot()
        assertEquals("Queued · after the site catalogues ($importing)",
                     JobViews.line(queue.job(lookup.id)!!, 1, behind = JobViews.behind(queue.job(lookup.id)!!, jobs)).text)
        // A sync's: its running stage and its words; a job of commands ahead (Python's too) is counted as ever.
        assertEquals(null, JobViews.behind(queue.job(catalogues.id)!!, jobs), "a running job waits for none")
        gate.complete(Unit)
        runCurrent()
        val syncing = CompletableDeferred<Unit>()
        val sync = queue.submit(JobSpec("Sharing logs with studio", "sync:http://pc:8737", "sync", sync,
                                        display = "Sharing logs with studio") { context ->
            context.stage("index", "running", "Downloading the computer's indexes · 120 of 274 MB")
            syncing.await()
        }).first
        runCurrent()
        val after = queue.submit(JobSpec("Get Muse - Uprising", "muse/uprising", "song", emptyList(),
                                         commands = JobCommands.lookupSteps("Muse", "Uprising"), fetching = true)).first
        assertEquals("Queued · after the sync (Updating the indexes · Downloading the computer's indexes · 120 of 274 MB)",
                     JobViews.line(queue.job(after.id)!!, 1, behind = JobViews.behind(queue.job(after.id)!!,
                                                                                      queue.snapshot())).text)
        syncing.complete(Unit)
        runCurrent()
        assertEquals(Job.DONE, queue.job(sync.id)!!.state)
    }

    /** Behind a kind whose line is the same while it runs (a backup, a file filed, a restore): that line once, its
     * first letter small; behind one that counts (the pages remade), its name and its count, or its name alone before
     * it has counted anything. No parentheses twice. */
    @Test fun aRequestQueuedBehindAPhonesOwnJobSaysItsKindsOwnLineOnce() = runTest {
        val queue = queue()
        fun behind(spec: JobSpec, said: String?): String {
            val gate = CompletableDeferred<Unit>()
            val kind = PhoneKinds.ALL.getValue(spec.kind)
            val running = queue.submit(spec.copy(run = { context ->
                context.stage(kind.stage.first, "running", said ?: "")
                gate.await()
            })).first
            runCurrent()
            val waiting = queue.submit(JobSpec("Add q", "q-${running.id}", "add", emptyList()) {}).first
            val text = JobViews.line(queue.job(waiting.id)!!, 1, behind = JobViews.behind(queue.job(waiting.id)!!,
                                                                                          queue.snapshot())).text
            gate.complete(Unit)
            runCurrent()
            return text
        }
        fun spec(kind: PhoneKinds.Kind, display: String) =
            JobSpec(kind.title, kind.key + display, kind.kind, listOf(kind.stage), display = display) {}
        val backup = PhoneKinds.BACKUP
        assertEquals("Queued · after backing up the book", behind(spec(backup, "A backup (daily)"), backup.running))
        val inbox = PhoneKinds.INBOX
        assertEquals("Queued · after filing song.gp5",
                     behind(spec(inbox, "song.gp5"), PhoneKinds.fill(inbox.running, "name" to "song.gp5")))
        val render = PhoneKinds.RENDER
        assertEquals("Queued · after the phone's pages (Remaking pages · 3 of 10)",
                     behind(spec(render, render.display),
                            PhoneKinds.fill(render.running, "done" to 3, "total" to 10)))
        assertEquals("Queued · after the phone's pages", behind(spec(render, render.display), null))
        val catalogues = PhoneKinds.CATALOGUES
        assertEquals("Queued · after the site catalogues", behind(spec(catalogues, catalogues.display), null))
    }

    /** A request kept in the history from before the metered stop's words changed still reads as a wait. */
    @Test fun theMeteredStopsFormerWordsStillReadAsAWait() = runTest {
        val queue = queue()
        val kind = PhoneKinds.CATALOGUES
        val old = "52 MB to download: waiting for Wi-Fi or your go-ahead"
        val job = phoneJob(queue, kind, "old") { context -> context.stage("catalogues", "done", old) }
        runCurrent()
        assertEquals(Line("waiting", old, details = "#tab=requests&job=${job.id}"), JobViews.line(queue.job(job.id)!!))
        assertTrue(kind.waits(old))
        assertTrue(kind.waits(PhoneKinds.fill(kind.otherwise!!, "size" to "52 MB")))
        assertEquals(false, kind.waits("Up to date: the catalogues of 24 Nov 2026"))
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

    @Test fun theSiteCataloguesSayWhatTheyDoTheirDateAndWhyNot() = runTest {
        val queue = queue()
        val kind = PhoneKinds.CATALOGUES
        assertEquals(kind, PhoneKinds.ALL["catalogues"])
        val step = CompletableDeferred<Unit>()
        val gate = CompletableDeferred<Unit>()
        val job = phoneJob(queue, kind, "") { context ->
            context.stage("catalogues", "running")
            step.await()
            context.stage("catalogues", "running", PhoneKinds.fill(kind.running, "doing" to "Downloading · 31 of 52 MB"))
            gate.await()
            context.stage("catalogues", "done", PhoneKinds.fill(kind.done, "date" to "24 Nov 2026"))
        }
        runCurrent()
        assertEquals(Line("running", "Catalogues…"), JobViews.line(queue.job(job.id)!!))  // nothing filled yet
        step.complete(Unit)
        runCurrent()
        assertEquals(Line("running", "Downloading · 31 of 52 MB"), JobViews.line(queue.job(job.id)!!))
        gate.complete(Unit)
        runCurrent()
        val over = queue.job(job.id)!!
        assertEquals(Line("ready", "Catalogues of 24 Nov 2026"), JobViews.line(over))
        assertEquals(JsonPrimitive("catalogues"), JobViews.view(over, queue)["kind"])
        assertEquals(listOf(Chip("Catalogues", "done")), Outcomes.steps(over))
        // Up to date: done, as ready as an import; a metered network's stop, the kind's second way to end, a wait.
        val upToDate = phoneJob(queue, kind, "again") { context ->
            context.stage("catalogues", "done", "Up to date: the catalogues of 24 Nov 2026")
        }
        val metered = phoneJob(queue, kind, "go") { context ->
            context.stage("catalogues", "done", PhoneKinds.fill(kind.otherwise!!, "size" to "52 MB"))
        }
        runCurrent()
        assertEquals(Line("ready", "Up to date: the catalogues of 24 Nov 2026"), JobViews.line(queue.job(upToDate.id)!!))
        assertEquals(Line("waiting", "52 MB to download: waiting for your go-ahead to use mobile data",
                          details = "#tab=requests&job=${metered.id}"), JobViews.line(queue.job(metered.id)!!))
        val failed = phoneJob(queue, kind, "failed") { context ->
            val line = PhoneKinds.fill(kind.failed, "why" to "No catalogues are published yet.")
            context.stage("catalogues", "failed", line)
            throw CommandExit(1, line)
        }
        runCurrent()
        assertEquals(Line("failed", "Not imported: No catalogues are published yet.",
                          details = "#tab=requests&job=${failed.id}"), JobViews.line(queue.job(failed.id)!!))
        // A line fits a template with its blanks filled, wherever they are.
        assertTrue(PhoneKinds.fits("52 MB to download: waiting for your go-ahead to use mobile data", kind.otherwise!!))
        assertTrue(PhoneKinds.fits("Waiting for its song: a.gp5", PhoneKinds.INBOX.otherwise!!))
        assertTrue(PhoneKinds.fits("Filed · a of b", PhoneKinds.INBOX.done))
        assertEquals(false, PhoneKinds.fits("Up to date: the catalogues of 24 Nov 2026", kind.otherwise!!))
        assertEquals(false, PhoneKinds.fits("Filed · a", PhoneKinds.INBOX.done))
        assertEquals(false, PhoneKinds.fits("Pages remade", PhoneKinds.RENDER.done))
        // A job read back from the history is of its kind by its key.
        assertEquals("catalogues", JobCommands.kindOf("catalogues:", emptyList(), listOf("catalogues")))
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
        val now = queue.job(job.id)!!.startedAt!!.plusSeconds(5)  // past its first second, which draws no steps
        assertEquals(null, JobViews.view(queue.job(job.id)!!, queue, facts = SongFacts(),
                                         now = queue.job(job.id)!!.startedAt!!)["steps"])
        val view = JobViews.view(queue.job(job.id)!!, queue, facts = SongFacts(), now = now)
        assertEquals("Fetching from LaCuerda…", view["line"]!!.jsonObject["text"]!!.jsonPrimitive.content)
        assertEquals(2, view["at"]!!.jsonPrimitive.int)
        assertEquals(JsonPrimitive("3 of 7"), view["count"])
        val sheet = view["steps"]!!.jsonArray[2].jsonObject
        assertEquals(Json.parseToJsonElement("""{"name":"Sheet","site":"LaCuerda","state":"running","found":""}"""), sheet)
        // Cut off there (the server stopped): failed, naming the site it asked, and nothing found, what it said while it
        // ran being no finding; the match it found stays.
        val cut = queue.job(job.id)!!.copy().also { it.stages.first { stage -> stage.name == "sheet" }.state = Job.INTERRUPTED }
        assertEquals(listOf(Chip("Match", "done", "Ultimate Guitar", "accepted"), Chip("Sheet", "failed", "LaCuerda")),
                     Outcomes.steps(cut).subList(1, 3))
        // The song new to the library, its song stage adds it, as caracole add would.
        assertEquals("Adding to the book…", Status.jobLine(fakeRunningSong(queue.job(job.id)!!), null).text)
        gate.complete(Unit)
    }

    @Test fun aLookupWaitingForTheBookSaysSoOfItsStepInHand() = runTest {
        val held = CompletableDeferred<Unit>()
        val gate = CompletableDeferred<Unit>()
        val commands = Commands(mapOf("get" to CommandRunner { _, context ->
            context.stage("song", "running", "waiting for the book (pid 42: run); a fetch goes first at its next pause")
            held.await()
            context.stage("song", "done")
            context.stage("match", "running")
            gate.await()
        }))
        val queue = JobQueue(backgroundScope, commands = commands)
        val job = queue.submit(JobSpec("Fetch Soda Stereo - De música ligera", "soda stereo/de musica ligera", "song",
                                       emptyList(), display = "Soda Stereo - De música ligera", fetching = true,
                                       commands = JobCommands.lookupSteps("Soda Stereo", "De música ligera"))).first
        runCurrent()
        val now = queue.job(job.id)!!.startedAt!!.plusSeconds(5)
        val view = JobViews.view(queue.job(job.id)!!, queue, facts = SongFacts(), now = now)
        assertEquals("Waiting for the book…", view["line"]!!.jsonObject["text"]!!.jsonPrimitive.content)
        assertEquals(listOf("at", "count", "waits"), view.keys.filter { it in setOf("at", "count", "waits") })
        assertEquals(JsonPrimitive("1 of 7"), view["count"])
        assertEquals(JsonPrimitive(true), view["waits"])
        held.complete(Unit)
        runCurrent()
        val going = JobViews.view(queue.job(job.id)!!, queue, facts = SongFacts(), now = now)
        assertEquals(JsonPrimitive("2 of 7"), going["count"])
        assertEquals(null, going["waits"])
        gate.complete(Unit)
    }

    /** A lookup with its song stage running. */
    private fun fakeRunningSong(job: Job): Job = job.copy().also {
        it.stages.forEach { stage -> stage.state = Job.WAITING }
        it.stages.first { stage -> stage.name == "song" }.state = Job.RUNNING
    }
}
