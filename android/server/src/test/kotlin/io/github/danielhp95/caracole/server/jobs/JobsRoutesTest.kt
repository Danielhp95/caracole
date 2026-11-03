package io.github.danielhp95.caracole.server.jobs

import io.github.danielhp95.caracole.core.db.Database
import io.github.danielhp95.caracole.core.db.Db
import io.github.danielhp95.caracole.core.library.SongRow
import io.github.danielhp95.caracole.server.page.SongCards
import io.github.danielhp95.caracole.server.testing.TestApp
import io.github.danielhp95.caracole.server.testing.header
import io.github.danielhp95.caracole.server.testing.json
import io.github.danielhp95.caracole.server.testing.text
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.test.TestScope
import kotlinx.coroutines.test.runCurrent
import kotlinx.coroutines.test.runTest
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import kotlin.test.assertEquals
import kotlin.test.assertNull
import kotlin.test.assertTrue

/** jobs_routes.py on the phone, through the App: /jobs.json for the page's script alone, a job's view with its song's
 * card once over, /api/jobs/N, and Cancel. */
// The worker runs in the test's backgroundScope, whose tasks runCurrent runs (advanceUntilIdle leaves them be).
@OptIn(ExperimentalCoroutinesApi::class)
class JobsRoutesTest {
    @get:Rule val tmp = TemporaryFolder()

    /** Each song's card: its id and title, as a test can tell them apart. */
    private object Cards : SongCards {
        override fun cards(db: Db, songs: List<SongRow>): Map<Long, JsonObject> =
            songs.associate { it.id to JsonObject(mapOf("id" to JsonPrimitive(it.id), "title" to JsonPrimitive(it.title))) }
    }

    private fun TestScope.app(): Pair<TestApp, JobQueue> {
        val queue = JobQueue(backgroundScope)
        return TestApp(tmp.root, { database -> listOf(JobsRoutes(queue, Cards, database)) }) to queue
    }

    private fun insert(db: Db, artist: String, title: String, key: String): Long {
        db.execute("INSERT INTO songs (key, artist, title, artists, added_at, created_at, updated_at) " +
                   "VALUES (?, ?, ?, ?, '2026-11-01T00:00:00Z', '2026-11-01T00:00:00Z', '2026-11-01T00:00:00Z')",
                   key, artist, title, "[\"$artist\"]")
        return db.lastRowid()
    }

    private fun song(database: Database, artist: String, title: String, key: String): Long =
        database.writeBlocking { db -> insert(db, artist, title, key) }

    private fun add(database: Database, artist: String, title: String, key: String) = JobSpec(
        "Add $artist - $title", key, "add", listOf("add" to "Adding to the library"), display = "$artist - $title",
    ) { context ->
        context.stage("add", "running")
        database.write { db -> insert(db, artist, title, key) }  // the job's write, as every write on the phone
        context.stage("add", "done")
    }

    @Test fun jobsJsonIsThePagesScriptsAloneAndSaysToReloadToAnythingElse() = runTest {
        val (test, _) = app()
        test.use {
            val page = test.get("/jobs.json")
            assertEquals(403, page.status)
            assertTrue("reload it" in page.text, page.text)
            val script = test.get("/jobs.json", "accept" to "application/json")
            assertEquals(403, script.status)
            assertEquals("""{"error":"caracole serve has restarted since this page was opened: reload it."}""", script.text)
            assertEquals(403, test.script("/jobs.json", TestApp.TOKEN_HEADER to "an old token").status)
            val fine = test.script("/jobs.json")
            assertEquals(200, fine.status)
            assertEquals("""{"active":0,"jobs":[]}""", fine.text)
            assertEquals("application/json; charset=utf-8", fine.header("Content-Type"))
        }
    }

    @Test fun eachJobsViewAndOnceOverTheCardOfItsSongWhenThePageAsksForIt() = runTest {
        val (test, queue) = app()
        test.use {
            val gate = CompletableDeferred<Unit>()
            val first = queue.submit(add(test.database, "Radiohead", "Creep", "radiohead/creep")).first
            val held = queue.submit(JobSpec("Sync with Laptop", "sync:http://laptop:8737", "sync",
                                            listOf("compare" to "Compare")) { gate.await() }).first
            val third = queue.submit(add(test.database, "Muse", "Hysteria", "muse/hysteria")).first
            runCurrent()
            val all = test.script("/jobs.json").json.jsonObject
            assertEquals(JsonPrimitive(2), all["active"])
            assertEquals(listOf(third.id, held.id, first.id),
                         all["jobs"]!!.jsonArray.map { it.jsonObject["id"]!!.jsonPrimitive.content.toInt() })  // newest first
            val radiohead = all["jobs"]!!.jsonArray.last().jsonObject
            assertNull(radiohead["card"])  // none asked for: a line alone
            // Asked for by its id, over: its song's card as the page draws it, by its key.
            val asked = test.script("/jobs.json?jobs=${first.id},x,${held.id}").json.jsonObject["jobs"]!!.jsonArray
            assertEquals(listOf(held.id, first.id), asked.map { it.jsonObject["id"]!!.jsonPrimitive.content.toInt() })
            val over = asked.last().jsonObject
            val id = test.database.read { db -> db.one("SELECT id FROM songs WHERE key = 'radiohead/creep'") { it.long(0) } }
            assertEquals(Json.parseToJsonElement("""{"id":$id,"title":"Creep"}"""), over["card"])
            assertEquals(JsonPrimitive(id), over["songId"])
            assertEquals(JsonPrimitive("radiohead/creep"), over["identity"])
            assertEquals("Added: the nightly run looks for it", over["line"]!!.jsonObject["text"]!!.jsonPrimitive.content)
            assertNull(asked.first().jsonObject["card"])  // the sync runs still
            assertEquals(JsonPrimitive("running"), asked.first().jsonObject["state"])
            gate.complete(Unit)
            runCurrent()
            assertEquals(JsonPrimitive(0), test.script("/jobs.json?jobs=").json.jsonObject["active"])
        }
    }

    @Test fun aRemovalOverHasNoCardOnceItsSongIsGone() = runTest {
        val (test, queue) = app()
        test.use {
            val id = song(test.database, "Oasis", "Wonderwall", "oasis/wonderwall")
            val removal = queue.submit(JobSpec("Remove Oasis - Wonderwall", "remove:oasis/wonderwall", "remove",
                                               emptyList(), display = "Oasis - Wonderwall", songId = id, join = false) {
                test.database.write { db -> db.execute("DELETE FROM songs WHERE id = ?", id) }
            }).first
            runCurrent()
            val view = test.script("/jobs.json?jobs=${removal.id}").json.jsonObject["jobs"]!!.jsonArray.single().jsonObject
            assertNull(view["card"])
            assertEquals(JsonPrimitive(id), view["songId"])
            assertEquals(JsonPrimitive("remove"), view["kind"])
            assertEquals(JsonPrimitive("oasis/wonderwall"), view["identity"])
            assertEquals("Removed", view["line"]!!.jsonObject["text"]!!.jsonPrimitive.content)
        }
    }

    @Test fun theIdsAskedForArePlainDigitsFiftyAtMost() {
        assertNull(JobsRoutes.jobIds(null))
        assertEquals(emptySet(), JobsRoutes.jobIds(""))
        assertEquals(setOf(1, 2, 3), JobsRoutes.jobIds("1, 2,x,,3,-4,٣,99999999999999999999"))
        assertEquals((1..50).toSet(), JobsRoutes.jobIds((1..60).joinToString(",")))
    }

    @Test fun oneJobAsDataOrNone() = runTest {
        val (test, queue) = app()
        test.use {
            val job = queue.submit(add(test.database, "Blur", "Song 2", "blur/song 2")).first
            runCurrent()
            val answer = test.script("/api/jobs/${job.id}")
            assertEquals(200, answer.status)
            assertEquals(queue.job(job.id)!!.asJson(), answer.json)
            for (other in listOf("/api/jobs/99", "/api/jobs/abc", "/api/jobs/", "/api/jobs/99999999999999")) {
                val none = test.script(other)
                assertEquals(404, none.status, other)
                assertEquals("""{"error":"no such request"}""", none.text)
            }
            // A read of /api/ another site's page makes is refused, as every one is.
            assertEquals(403, test.get("/api/jobs/${job.id}", "sec-fetch-site" to "cross-site").status)
        }
    }

    @Test fun cancelTakesAWaitingJobOutAndRefusesInCaracoleServesWords() = runTest {
        val (test, queue) = app()
        test.use {
            val gate = CompletableDeferred<Unit>()
            val running = queue.submit(JobSpec("a", "a", "add", emptyList()) { gate.await() }).first
            val waiting = queue.submit(JobSpec("b", "b", "add", emptyList()) {}).first
            val other = queue.submit(JobSpec("c", "c", "add", emptyList()) {}).first
            runCurrent()
            val script = test.postScript("/jobs/cancel", listOf("job" to "${waiting.id}"))
            assertEquals(200, script.status)
            assertEquals("""{"cancelled":${waiting.id}}""", script.text)
            assertEquals(Job.CANCELLED, queue.job(waiting.id)!!.state)
            val page = test.post("/jobs/cancel", listOf("job" to " ${other.id} "))
            assertEquals(303, page.status)
            assertEquals("/#tab=requests", page.header("Location"))
            fun refused(job: String) = test.postScript("/jobs/cancel", listOf("job" to job)).let {
                it.status to it.json.jsonObject["error"]!!.jsonPrimitive.content
            }
            assertEquals(409 to "That request has started, and caracole never stops a command halfway: it runs to its end.",
                         refused("${running.id}"))
            assertEquals(404 to "That request isn't queued any more.", refused("${waiting.id}"))  // cancelled already
            assertEquals(404 to "That request isn't queued any more.", refused("77"))
            assertEquals(400 to "Which request? The form names none.", refused("two"))
            assertEquals(400 to "Which request? The form names none.", refused("1234567890123"))
            assertEquals(400, test.postScript("/jobs/cancel").status)
            gate.complete(Unit)
            runCurrent()
            assertEquals(409 to "That request is over: there's nothing left to cancel.", refused("${running.id}"))
            assertEquals(403, test.postScript("/jobs/cancel", listOf("job" to "1"), token = "old").status)
        }
    }
}
