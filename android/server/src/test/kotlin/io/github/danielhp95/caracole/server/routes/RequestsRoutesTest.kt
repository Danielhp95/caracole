package io.github.danielhp95.caracole.server.routes

import io.github.danielhp95.caracole.server.jobs.CommandExit
import io.github.danielhp95.caracole.server.jobs.CommandRunner
import io.github.danielhp95.caracole.server.jobs.Commands
import io.github.danielhp95.caracole.server.jobs.Feed
import io.github.danielhp95.caracole.server.jobs.Job
import io.github.danielhp95.caracole.server.jobs.JobCommands
import io.github.danielhp95.caracole.server.jobs.JobHistory
import io.github.danielhp95.caracole.server.jobs.JobQueue
import io.github.danielhp95.caracole.server.jobs.JobSpec
import io.github.danielhp95.caracole.server.testing.TestApp
import io.github.danielhp95.caracole.server.testing.TestParts
import io.github.danielhp95.caracole.server.testing.header
import io.github.danielhp95.caracole.server.testing.json
import io.github.danielhp95.caracole.server.testing.text
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.withTimeout
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import org.junit.After
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import java.time.Instant
import java.time.ZoneId
import java.util.Collections
import kotlin.test.assertEquals
import kotlin.test.assertTrue

/** The Requests tab's routes on the phone, through the App: /requests.json for the page's script alone, Feed's answer
 * of the queue's jobs, their lines, outcomes, steps and picks, and Try again in jobs_routes.again's words and rules. */
// The queue's worker runs on a scope of the test's own (not runTest's, which would report a coroutine exception
// another class leaked as this one's), each step waited for by the job's end or its state.
class RequestsRoutesTest {
    @get:Rule val tmp = TemporaryFolder()

    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Default)

    @After fun stop() = scope.cancel()

    /** The queue's clock and the feed's: late on the 3rd in UTC, after midnight in Madrid. */
    private val now = Instant.parse("2026-11-03T23:30:00Z")

    /** The commands the queue runs: each looks the song up, saying a line; one of a title "Fails" fails, one of
     * "Held" waits for the gate. */
    private val ran: MutableList<List<String>> = Collections.synchronizedList(ArrayList())
    private val gate = CompletableDeferred<Unit>()
    private val commands = Commands(mapOf(
        "get" to CommandRunner { args, context ->
            ran += args
            if (args.last() == "Held") gate.await()
            context.say("looked ${args.last()} up")
            if (args.last() == "Fails") throw CommandExit(1, "it failed")
        },
        "lacuerda" to CommandRunner { args, _ -> ran += args },
    ))

    private fun app(limit: Int = JobQueue.LIMIT,
                    queue: JobQueue = JobQueue(scope, limit = limit, clock = { now }, commands = commands),
                    zone: ZoneId = ZoneId.of("Europe/Madrid")): Pair<TestApp, JobQueue> =
        TestApp(tmp.root, { database ->
            listOf(RequestsRoutes(TestParts.of(database, tmp.root, scope, queue), clock = { now }, zone = { zone }))
        }) to queue

    private fun lookup(title: String, songbooks: Boolean = true) = JobSpec(
        "Look up A - $title", "a/${title.lowercase()}", "song", emptyList(), display = "A - $title",
        commands = JobCommands.lookupSteps("A", title, songbooks = songbooks), fetching = true,
    )

    /** The job once over. */
    private fun ended(queue: JobQueue, job: Job): Job = runBlocking { withTimeout(10_000) { queue.await(job.id) } }

    /** Once the job runs. */
    private fun running(queue: JobQueue, job: Job) {
        val deadline = System.nanoTime() + 10_000_000_000L
        while (queue.job(job.id)!!.state != Job.RUNNING) {
            check(System.nanoTime() < deadline) { "request ${job.id} never ran" }
            Thread.sleep(2)
        }
    }

    private fun release(queue: JobQueue, held: Job) {
        gate.complete(Unit)
        ended(queue, held)
    }

    private fun says(request: kotlinx.serialization.json.JsonObject): String =
        request.getValue("says").jsonObject.getValue("text").jsonPrimitive.content

    @Test fun requestsJsonIsThePagesScriptsAlone() {
        val (test, _) = app()
        test.use {
            assertEquals(403, test.get("/requests.json").status)
            assertEquals(403, test.script("/requests.json", TestApp.TOKEN_HEADER to "an old token").status)
            val fine = test.script("/requests.json")
            assertEquals(200, fine.status)
            assertEquals("""{"active":0,"groups":[]}""", fine.text)
            assertEquals("application/json; charset=utf-8", fine.header("Content-Type"))
        }
    }

    @Test fun theFeedHasTheRunningRequestThoseQueuedAndThoseOverEachOutputOpenedAsAsked() {
        val (test, queue) = app()
        test.use {
            val done = queue.submit(lookup("Done")).first
            ended(queue, done)
            val held = queue.submit(lookup("Held")).first
            val waiting = queue.submit(lookup("Waits")).first
            running(queue, held)
            val feed = test.script("/requests.json?open=${done.id},x").json.jsonObject
            assertEquals(JsonPrimitive(2), feed["active"])
            val groups = feed.getValue("groups").jsonArray.map { it.jsonObject }
            assertEquals(listOf("Now", "Today"), groups.map { it.getValue("name").jsonPrimitive.content })
            val current = groups[0].getValue("requests").jsonArray.map { it.jsonObject }
            assertEquals(listOf(held.id, waiting.id), current.map { it.getValue("id").jsonPrimitive.content.toInt() })
            assertEquals("Queued · next", says(current[1]))
            val over = groups[1].getValue("requests").jsonArray.single().jsonObject
            assertEquals(done.id, over.getValue("id").jsonPrimitive.content.toInt())
            val output = over.getValue("output").jsonObject
            assertEquals(JsonPrimitive(true), output["opened"])
            assertEquals(listOf("looked Done up"),
                         output.getValue("steps").jsonArray.single().jsonObject.getValue("lines").jsonArray.map {
                             it.jsonPrimitive.content
                         })
            assertTrue(" · requested 2026-11-04 00:30 CET" in output.getValue("meta").jsonPrimitive.content,
                       output.getValue("meta").toString())
            assertTrue("lines" !in current[0].getValue("output").jsonObject.getValue("steps").jsonArray.single().jsonObject)
            release(queue, held)
        }
    }

    @Test fun eachRequestOverSaysItsOutcomeAndTheRunningOneItsSteps() {
        val (test, queue) = app()
        test.use {
            val failed = queue.submit(lookup("Fails")).first
            ended(queue, failed)
            val held = queue.submit(lookup("Held")).first
            running(queue, held)
            val groups = test.script("/requests.json").json.jsonObject.getValue("groups").jsonArray.map { it.jsonObject }
            val shown = groups.first().getValue("requests").jsonArray.single().jsonObject
            assertEquals(held.id, shown.getValue("id").jsonPrimitive.content.toInt())
            assertEquals(listOf("Song", "Match", "Sheet", "PDF", "Lyrics", "Extras", "Songbooks"),
                         shown.getValue("steps").jsonArray.map { it.jsonObject.getValue("name").jsonPrimitive.content })
            val over = groups.last().getValue("requests").jsonArray.single().jsonObject
            assertEquals(failed.id, over.getValue("id").jsonPrimitive.content.toInt())
            assertEquals("Failed", says(over))
            assertEquals("it failed.", over.getValue("reason").jsonPrimitive.content)  // its error line, as outcome._sentence ends it
            val again = over.getValue("actions").jsonArray.single().jsonObject
            assertEquals("Try again", again.getValue("label").jsonPrimitive.content)
            assertEquals("/jobs/again", again.getValue("post").jsonPrimitive.content)
            assertEquals(JsonPrimitive("${failed.id}"), again.getValue("fields").jsonObject["job"])
            release(queue, held)
        }
    }

    @Test fun aLookupThatEndedWaitingForThePickSaysSoAndOffersThePicker() {
        val queue = JobQueue(scope, clock = { now }, commands = Commands(mapOf(
            "get" to CommandRunner { _, context ->
                for (stage in listOf("song", "match")) context.stage(stage, Job.DONE)
                context.stage("sheet", Job.SKIPPED, "needs review first")
            },
        )))
        val (test, _) = app(queue = queue, zone = ZoneId.of("UTC"))
        test.use {
            val id = test.database.writeBlocking { db ->
                db.execute("INSERT INTO songs (key, artist, title, artists, added_at, created_at, updated_at, review, " +
                           "match_candidates) VALUES ('a/picked', 'A', 'Picked', '[\"A\"]', '2026-11-01T00:00:00Z', " +
                           "'2026-11-01T00:00:00Z', '2026-11-01T00:00:00Z', 1, " +
                           "'[{\"artist_key\": \"a\", \"song_key\": \"picked\", \"score\": 80}]')")
                db.lastRowid()
            }
            ended(queue, queue.submit(lookup("Picked")).first)
            val over = test.script("/requests.json").json.jsonObject.getValue("groups").jsonArray.single().jsonObject
                .getValue("requests").jsonArray.single().jsonObject
            assertEquals("Needs your pick", says(over))
            assertEquals("/review?song=$id",
                         over.getValue("actions").jsonArray.single().jsonObject.getValue("href").jsonPrimitive.content)
            val sheet = over.getValue("output").jsonObject.getValue("stages").jsonArray.map { it.jsonObject }
                .single { it.getValue("label").jsonPrimitive.content == "The sheet" }
            assertEquals("Waits for a pick", sheet.getValue("badge").jsonObject.getValue("text").jsonPrimitive.content)
            assertEquals(Feed.PICK_STAGE, sheet.getValue("note").jsonPrimitive.content)
        }
    }

    /** A lookup's queue whose `get` matches the song and skips its sheet as needing review first, as get.py does for a
     * song in review: a request that waits for a pick, when its song has one. One of a title "Held" waits for the
     * gate. */
    private fun reviewing(): JobQueue = JobQueue(scope, clock = { now }, commands = Commands(mapOf(
        "get" to CommandRunner { args, context ->
            if (args.last() == "Held") gate.await()
            for (stage in listOf("song", "match")) context.stage(stage, Job.DONE)
            context.stage("sheet", Job.SKIPPED, "needs review first")
        },
    )))

    /** A song of key `a/<title>`, its other columns [columns]; its id. */
    private fun song(test: TestApp, title: String, columns: Map<String, Any> = emptyMap()): Long =
        test.database.writeBlocking { db ->
            val all = linkedMapOf<String, Any>("key" to "a/${title.lowercase()}", "artist" to "A", "title" to title,
                                               "artists" to "[\"A\"]", "added_at" to "2026-11-01T00:00:00Z",
                                               "created_at" to "2026-11-01T00:00:00Z",
                                               "updated_at" to "2026-11-01T00:00:00Z") + columns
            db.execute("INSERT INTO songs (${all.keys.joinToString()}) VALUES (${all.keys.joinToString { "?" }})",
                       *all.values.toTypedArray())
            db.lastRowid()
        }

    /** The one finished request the feed shows of [job]. */
    private fun shownOver(test: TestApp, job: Job): kotlinx.serialization.json.JsonObject =
        test.script("/requests.json").json.jsonObject.getValue("groups").jsonArray
            .flatMap { it.jsonObject.getValue("requests").jsonArray }.map { it.jsonObject }
            .single { it.getValue("id").jsonPrimitive.content.toInt() == job.id }

    private fun actions(shown: kotlinx.serialization.json.JsonObject): List<kotlinx.serialization.json.JsonObject> =
        shown["actions"]?.jsonArray.orEmpty().map { it.jsonObject }

    /** The lookup's Sheet stage, as its output shows it. */
    private fun sheetStage(shown: kotlinx.serialization.json.JsonObject): kotlinx.serialization.json.JsonObject =
        shown.getValue("output").jsonObject.getValue("stages").jsonArray.map { it.jsonObject }
            .single { it.getValue("label").jsonPrimitive.content == "The sheet" }

    /** Each action as (label, its link or form, primary). */
    private fun said(shown: kotlinx.serialization.json.JsonObject): List<Triple<String, String, Boolean>> =
        actions(shown).map { a ->
            Triple(a.getValue("label").jsonPrimitive.content,
                   (a["href"] ?: a.getValue("post")).jsonPrimitive.content, a.getValue("primary").jsonPrimitive.content == "true")
        }

    @Test fun aSongTheIndexDidntMatchOffersWhatCaracoleSearchFindsOnceAndNeverWaitsForAPick() {
        val queue = reviewing()
        val (test, _) = app(queue = queue, zone = ZoneId.of("UTC"))
        test.use {
            val missed = song(test, "Missed", mapOf("match_decision" to "not_found"))
            val lost = song(test, "Lost", mapOf("match_decision" to "not_found"))
            // Not found's own way on is the search's (outcome._not_found): the pick adds it no second time
            val notFound = shownOver(test, ended(queue, queue.submit(lookup("Missed")).first))
            assertEquals(listOf(Triple(Feed.SEARCH, "/review?song=$missed", true)), said(notFound), "$notFound")
            // a request you cancelled has no way on of its own: the pick offers the search, a plain button
            val held = queue.submit(lookup("Held")).first
            running(queue, held)
            val cancelled = queue.submit(lookup("Lost")).first
            queue.cancel(cancelled.id)
            release(queue, held)
            val taken = shownOver(test, cancelled)
            assertEquals("Cancelled", says(taken))
            assertEquals(listOf(Triple(Feed.SEARCH, "/review?song=$lost", false)), said(taken), "$taken")
            for (shown in listOf(notFound, taken)) {
                val output = shown.getValue("output").jsonObject.toString()
                assertTrue("Waits for a pick" !in output, "a search's pick never waits: $output")
            }
        }
    }

    @Test fun noSongIgnoredNorAReviewWithNoCandidateOffersAPick() {
        val queue = reviewing()
        val (test, _) = app(queue = queue, zone = ZoneId.of("UTC"))
        test.use {
            val candidates = "[{\"artist_key\": \"a\", \"song_key\": \"x\", \"score\": 80}]"
            song(test, "Ignored", mapOf("status" to "ignored", "review" to 1, "match_candidates" to candidates))
            song(test, "Overridden", mapOf("review" to 1, "match_candidates" to candidates))
            song(test, "Bare", mapOf("review" to 1, "match_candidates" to "[]"))
            song(test, "Nameless", mapOf("review" to 1, "match_candidates" to "[{\"artist_key\": \"\", \"score\": 80}]"))
            song(test, "Unasked", mapOf("match_decision" to "not_found"))
            test.database.writeBlocking { db ->
                for (title in listOf("Overridden", "Unasked")) {
                    db.execute("INSERT INTO phone_overrides (tbl, key, written, value) VALUES ('ignore', ?, ?, 'true')",
                               "a/${title.lowercase()}", "A - $title")
                }
            }
            for (title in listOf("Ignored", "Overridden", "Bare", "Nameless", "Unasked")) {
                val shown = shownOver(test, ended(queue, queue.submit(lookup(title)).first))
                assertTrue(actions(shown).none { it.getValue("label").jsonPrimitive.content == Feed.SEARCH }, "$title: $shown")
                val sheet = sheetStage(shown)
                assertEquals("Skipped", sheet.getValue("badge").jsonObject.getValue("text").jsonPrimitive.content, "$title: $sheet")
                assertTrue("note" !in sheet, "$title: $sheet")
            }
        }
    }

    @Test fun aDatabaseThatCantBeReadLeavesTheLinesSayingHowTheJobsWentAndNoPicks() {
        val queue = reviewing()
        val (test, _) = app(queue = queue, zone = ZoneId.of("UTC"))
        test.use {
            song(test, "Missed", mapOf("match_decision" to "not_found"))
            val over = ended(queue, queue.submit(lookup("Missed")).first)
            test.database.writeBlocking { db -> db.execute("ALTER TABLE songs RENAME TO songs_gone") }  // SQLite's error
            val answer = test.script("/requests.json")
            assertEquals(200, answer.status, answer.text)
            val shown = shownOver(test, over)
            assertEquals("Added", says(shown))  // its stages' line, not its song's Not found: no song to read
            assertTrue(actions(shown).none { it.getValue("label").jsonPrimitive.content == Feed.SEARCH }, "$shown")
        }
    }

    @Test fun tryAgainAnswersTheRequestAsTheQueueHasItNowStartedAlready() {
        // A worker on Dispatchers.Unconfined starts the job queued again inside the queue's submit, before the route
        // makes its answer: the answer is the queue's copy now (WebApp.job_view), running, never the one submit gave.
        val runs = java.util.concurrent.atomic.AtomicInteger()
        val unconfined = CoroutineScope(SupervisorJob() + Dispatchers.Unconfined)
        val queue = JobQueue(unconfined, clock = { now }, commands = Commands(mapOf(
            "get" to CommandRunner { _, _ -> if (runs.incrementAndGet() > 1) gate.await() },
        )))
        val (test, _) = app(queue = queue)
        try {
            test.use {
                val first = queue.submit(lookup("Again")).first
                ended(queue, first)
                val script = test.postScript("/jobs/again", listOf("job" to "${first.id}"))
                assertEquals(200, script.status, script.text)
                val view = script.json.jsonObject.getValue("job").jsonObject
                val again = queue.job(view.getValue("id").jsonPrimitive.content.toInt())!!
                assertEquals(Job.RUNNING, again.state)
                assertEquals(JsonPrimitive(Job.RUNNING), view["state"], "$view")
                release(queue, again)
            }
        } finally {
            unconfined.cancel()
        }
    }

    @Test fun tryAgainQueuesARequestOverAgainWithItsCommandsAsJobsRoutesDoes() {
        val (test, queue) = app()
        test.use {
            val first = queue.submit(lookup("Fails", songbooks = false)).first
            val search = queue.submit(JobSpec("Search LaCuerda for x", "lacuerda-search:x", "lacuerda-search",
                                              emptyList(), commands = JobCommands.lacuerdaSearchSteps("x", auto = true))).first
            assertEquals(Job.FAILED, ended(queue, first).state)
            ended(queue, search)
            ran.clear()
            val script = test.postScript("/jobs/again", listOf("job" to "${first.id}"))
            assertEquals(200, script.status, script.text)
            val view = script.json.jsonObject.getValue("job").jsonObject
            val again = view.getValue("id").jsonPrimitive.content.toInt()
            assertTrue(again > search.id)
            ended(queue, queue.job(again)!!)
            // made with its songbooks now: no --no-songbooks before --
            assertEquals(listOf(JobCommands.lookupSteps("A", "Fails").single().args), ran.toList())
            val page = test.post("/jobs/again", listOf("job" to " ${search.id} "))
            assertEquals(303, page.status)
            assertEquals("/#tab=requests", page.header("Location"))
            ended(queue, queue.snapshot().first())
            assertEquals(listOf("lacuerda", "--search=x", "--progress"), ran.last())  // asked by hand: no --auto
        }
    }

    @Test fun tryAgainRefusesInCaracoleServesWords() {
        val (test, queue) = app()
        test.use {
            val held = queue.submit(lookup("Held")).first
            running(queue, held)
            fun refused(job: String): Pair<Int, String> = test.postScript("/jobs/again", listOf("job" to job)).let {
                it.status to it.text
            }
            assertEquals(400, refused("").first)
            assertEquals(400, refused("x1").first)
            assertEquals(400, refused("1234567890123").first)
            assertEquals(400, refused("٣").first)  // a digit of another script is no request's
            assertEquals(404, refused("99").first)
            assertEquals(404, refused("999999999999").first)
            val (status, text) = refused("${held.id}")
            assertEquals(409, status)
            assertTrue("still queued or running" in text, text)
            release(queue, held)
        }
    }

    @Test fun aRequestOfThePhonesOwnReadBackFromTheHistoryHasNothingToRunAgain() {
        val history = JobHistory(tmp.newFile("requests.jsonl").also { it.delete() })
        val first = JobQueue(scope, history = history)
        ended(first, first.submit(JobSpec("Import the computer's index", "index", "index",
                                          listOf("merge" to "Merging the index")) {}).first)
        val (test, queue) = app(queue = JobQueue(scope, history = history, commands = commands))
        test.use {
            val old = queue.snapshot().single()
            val answer = test.postScript("/jobs/again", listOf("job" to "${old.id}"))
            assertEquals(409, answer.status)
            assertTrue(RequestsRoutes.NOT_REPEATABLE in answer.text, answer.text)
        }
    }

    @Test fun aFullQueueRefusesTryAgainAsEveryRequestIsRefused() {
        val (test, queue) = app(limit = 1)
        test.use {
            val over = queue.submit(lookup("Done")).first
            ended(queue, over)
            val held = queue.submit(lookup("Held")).first
            running(queue, held)
            val answer = test.postScript("/jobs/again", listOf("job" to "${over.id}"))
            assertEquals(503, answer.status)
            assertTrue(JobQueue.QUEUE_FULL in answer.text, answer.text)
            release(queue, held)
        }
    }
}
