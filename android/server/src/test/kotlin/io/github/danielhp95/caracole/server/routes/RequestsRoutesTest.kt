package io.github.danielhp95.caracole.server.routes

import io.github.danielhp95.caracole.server.jobs.CommandExit
import io.github.danielhp95.caracole.server.jobs.CommandRunner
import io.github.danielhp95.caracole.server.jobs.Commands
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
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.test.TestScope
import kotlinx.coroutines.test.runCurrent
import kotlinx.coroutines.test.runTest
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import java.time.Instant
import java.time.ZoneId
import kotlin.test.assertEquals
import kotlin.test.assertTrue

/** The Requests tab's routes on the phone, through the App: /requests.json for the page's script alone, Feed's answer,
 * and Try again in jobs_routes.again's words and rules. */
// The worker runs in the test's backgroundScope, whose tasks runCurrent runs.
@OptIn(ExperimentalCoroutinesApi::class)
class RequestsRoutesTest {
    @get:Rule val tmp = TemporaryFolder()

    /** The queue's clock and the feed's: late on the 3rd in UTC, after midnight in Madrid. */
    private val NOW = Instant.parse("2026-11-03T23:30:00Z")

    /** The commands the queue runs: each looks the song up, saying a line; one of a title "Fails" fails. */
    private val ran = ArrayList<List<String>>()
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

    private fun TestScope.app(limit: Int = JobQueue.LIMIT): Pair<TestApp, JobQueue> {
        val queue = JobQueue(backgroundScope, limit = limit, clock = { NOW }, commands = commands)
        val madrid = ZoneId.of("Europe/Madrid")
        return TestApp(tmp.root, { database ->
            listOf(RequestsRoutes(TestParts.of(database, tmp.root, backgroundScope, queue), clock = { NOW },
                                  zone = { madrid }))
        }) to queue
    }

    private fun lookup(title: String, songbooks: Boolean = true) = JobSpec(
        "Look up A - $title", "a/${title.lowercase()}", "song", emptyList(), display = "A - $title",
        commands = JobCommands.lookupSteps("A", title, songbooks = songbooks), fetching = true,
    )

    @Test fun requestsJsonIsThePagesScriptsAlone() = runTest {
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

    @Test fun theFeedHasTheRunningRequestThoseQueuedAndThoseOverEachOutputOpenedAsAsked() = runTest {
        val (test, queue) = app()
        test.use {
            val done = queue.submit(lookup("Done")).first
            runCurrent()
            val held = queue.submit(lookup("Held")).first
            val waiting = queue.submit(lookup("Waits")).first
            runCurrent()
            val feed = test.script("/requests.json?open=${done.id},x").json.jsonObject
            assertEquals(JsonPrimitive(2), feed["active"])
            val groups = feed.getValue("groups").jsonArray.map { it.jsonObject }
            assertEquals(listOf("Now", "Today"), groups.map { it.getValue("name").jsonPrimitive.content })
            val now = groups[0].getValue("requests").jsonArray.map { it.jsonObject }
            assertEquals(listOf(held.id, waiting.id), now.map { it.getValue("id").jsonPrimitive.content.toInt() })
            assertEquals("Queued, next", now[1].getValue("says").jsonObject.getValue("text").jsonPrimitive.content)
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
            assertTrue("lines" !in now[0].getValue("output").jsonObject.getValue("steps").jsonArray.single().jsonObject)
            gate.complete(Unit)
            runCurrent()
        }
    }

    @Test fun tryAgainQueuesARequestOverAgainWithItsCommandsAsJobsRoutesDoes() = runTest {
        val (test, queue) = app()
        test.use {
            val first = queue.submit(lookup("Fails", songbooks = false)).first
            val search = queue.submit(JobSpec("Search LaCuerda for x", "lacuerda-search:x", "lacuerda-search",
                                              emptyList(), commands = JobCommands.lacuerdaSearchSteps("x", auto = true))).first
            runCurrent()
            assertEquals(Job.FAILED, queue.job(first.id)!!.state)
            ran.clear()
            val script = test.postScript("/jobs/again", listOf("job" to "${first.id}"))
            assertEquals(200, script.status, script.text)
            val view = script.json.jsonObject.getValue("job").jsonObject
            val again = view.getValue("id").jsonPrimitive.content.toInt()
            assertTrue(again > search.id)
            runCurrent()
            // made with its songbooks now: no --no-songbooks before --
            assertEquals(listOf(JobCommands.lookupSteps("A", "Fails").single().args), ran)
            val page = test.post("/jobs/again", listOf("job" to " ${search.id} "))
            assertEquals(303, page.status)
            assertEquals("/#tab=requests", page.header("Location"))
            runCurrent()
            assertEquals(listOf("lacuerda", "--search=x", "--progress"), ran.last())  // asked by hand: no --auto
        }
    }

    @Test fun tryAgainRefusesInCaracoleServesWords() = runTest {
        val (test, queue) = app()
        test.use {
            val running = queue.submit(lookup("Held")).first
            runCurrent()
            fun refused(job: String): Pair<Int, String> = test.postScript("/jobs/again", listOf("job" to job)).let {
                it.status to it.text
            }
            assertEquals(400, refused("").first)
            assertEquals(400, refused("x1").first)
            assertEquals(400, refused("1234567890123").first)
            assertEquals(400, refused("٣").first)  // a digit of another script is no request's
            assertEquals(404, refused("99").first)
            assertEquals(404, refused("999999999999").first)
            val (status, text) = refused("${running.id}")
            assertEquals(409, status)
            assertTrue("still queued or running" in text, text)
            gate.complete(Unit)
            runCurrent()
        }
    }

    @Test fun aRequestOfThePhonesOwnReadBackFromTheHistoryHasNothingToRunAgain() = runTest {
        val history = JobHistory(tmp.newFile("requests.jsonl").also { it.delete() })
        val first = JobQueue(backgroundScope, history = history)
        first.submit(JobSpec("Import the index", "index", "index", listOf("merge" to "Merging the index")) {})
        runCurrent()
        val queue = JobQueue(backgroundScope, history = history, commands = commands)
        val test = TestApp(tmp.root, { database ->
            listOf(RequestsRoutes(TestParts.of(database, tmp.root, backgroundScope, queue)))
        })
        test.use {
            val old = queue.snapshot().single()
            val answer = test.postScript("/jobs/again", listOf("job" to "${old.id}"))
            assertEquals(409, answer.status)
            assertTrue(RequestsRoutes.NOT_REPEATABLE in answer.text, answer.text)
        }
    }

    @Test fun aFullQueueRefusesTryAgainAsEveryRequestIsRefused() = runTest {
        val (test, queue) = app(limit = 1)
        test.use {
            val over = queue.submit(lookup("Done")).first
            runCurrent()
            queue.submit(lookup("Held"))
            runCurrent()
            val answer = test.postScript("/jobs/again", listOf("job" to "${over.id}"))
            assertEquals(503, answer.status)
            assertTrue(JobQueue.QUEUE_FULL in answer.text, answer.text)
            gate.complete(Unit)
            runCurrent()
        }
    }
}
