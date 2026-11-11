package io.github.danielhp95.caracole.server.routes

import io.github.danielhp95.caracole.core.library.Overrides
import io.github.danielhp95.caracole.core.library.OverridesError
import io.github.danielhp95.caracole.core.library.Songs
import io.github.danielhp95.caracole.core.testing.Misses
import io.github.danielhp95.caracole.core.testing.RefusingTransport
import io.github.danielhp95.caracole.core.testing.TestDb
import io.github.danielhp95.caracole.server.Phone
import io.github.danielhp95.caracole.server.PhoneDeps
import io.github.danielhp95.caracole.server.http.Response
import io.github.danielhp95.caracole.server.jobs.CommandExit
import io.github.danielhp95.caracole.server.jobs.Commands
import io.github.danielhp95.caracole.server.jobs.Job
import io.github.danielhp95.caracole.server.jobs.JobCommands
import io.github.danielhp95.caracole.server.jobs.JobQueue
import io.github.danielhp95.caracole.server.jobs.JobSpec
import io.github.danielhp95.caracole.server.lookups.ReviewRunner
import io.github.danielhp95.caracole.server.testing.TestApp
import io.github.danielhp95.caracole.server.testing.header
import io.github.danielhp95.caracole.server.testing.json
import io.github.danielhp95.caracole.server.testing.replays.ReviewReplay
import io.github.danielhp95.caracole.server.testing.text
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.withTimeout
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.int
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import org.junit.After
import org.junit.Before
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertTrue

/** An uncertain match reviewed on the phone: the routes and the runner as caracole serve's (the vectors), and the
 * phone whole, as the app assembles it: a pick from the card's picker written, the song matched again, its line. */
class ReviewRoutesTest {
    @get:Rule val tmp = TemporaryFolder()

    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Default)
    private lateinit var phone: Phone

    private object NoAddress : SyncSettings {
        override val address: String? = null
        override fun remember(address: String) = Unit
    }

    @Before fun up() {
        val database = TestDb.fresh(tmp.newFolder("db"))
        phone = Phone(PhoneDeps(database, tmp.newFolder("library"), tmp.newFolder("state"), null, scope, NoAddress,
                                TestApp.SECRET, TestApp.CSRF, transport = { RefusingTransport },
                                searchesLacuerda = false))
        database.writeBlocking { db ->
            for ((tab, song) in listOf(1 to "creep", 2 to "creep-acoustic", 3 to "high-and-dry")) {
                db.execute("INSERT INTO ug_index (tab_id, artist_key, song_key, type, sitemap, first_seen, path) " +
                               "VALUES (?, 'radiohead', ?, 'chords', '1', 'x', ?)", tab, song, "radiohead/$song-chords-$tab")
            }
            db.kvSet("ug:index:built_at", "2026-11-03T10:00:00Z")
            val creep = phone.parts.store.add(db, "Radiohead", "Creep", now = "2026-11-03T12:00:00Z")
            db.execute("UPDATE songs SET match_decision = 'review', review = 1, match_candidates = ? WHERE id = ?",
                       CANDIDATES, creep.id)
        }
    }

    @After fun down() {
        scope.cancel()
        phone.parts.database.close()
    }

    private val creep get() = phone.parts.database.read { Songs.byKey(it, "radiohead/creep") }!!

    private fun handle(method: String, target: String, headers: Map<String, String?>, body: ByteArray = ByteArray(0)) =
        phone.app.handle(TestApp.request(method, target, headers, body, TestApp.SECRET))

    /** A form posted from the page; with [json], as its script posts it. */
    private fun post(target: String, vararg fields: Pair<String, String>, json: Boolean = true): Response = handle(
        "POST", target,
        mapOf("sec-fetch-site" to "same-origin", "origin" to "http://${TestApp.HOST}",
              "content-type" to "application/x-www-form-urlencoded") +
            (if (json) mapOf("accept" to "application/json") else emptyMap()),
        TestApp.form(listOf("csrf" to TestApp.CSRF) + fields),
    )

    private fun done(id: Int): Job = runBlocking { withTimeout(60_000) { phone.queue.await(id) } }

    /** The job's line as the library page shows it: /jobs.json's view. */
    private fun shownLine(id: Int): JsonObject = handle(
        "GET", "/jobs.json?jobs=$id",
        mapOf("sec-fetch-site" to "same-origin", "accept" to "application/json", TestApp.TOKEN_HEADER to TestApp.CSRF),
    ).json.jsonObject.getValue("jobs").jsonArray.single().jsonObject.getValue("line").jsonObject

    @Test fun `each route and the runner answer as caracole serve's (vectors web review)`() {
        val misses = Misses("review")
        ReviewReplay.replay(misses)
        misses.assertNone()
    }

    @Test fun `a pick from the card's picker is written, the song matched again, and its line says so`() {
        val answer = post("/review", "song" to "${creep.id}", "pick" to "radiohead/creep", "shown" to SHOWN)
        assertEquals(200, answer.status, answer.text)
        val id = answer.json.jsonObject.getValue("job").jsonObject.getValue("id").jsonPrimitive.int
        val job = done(id)
        assertEquals("done", job.state, "${job.steps.map { it.output }}")
        assertEquals(listOf(listOf("review", "--song=Radiohead - Creep", "--pick=radiohead/creep")), job.steps.map { it.args })
        val overrides = phone.parts.database.read { Overrides.read(it) }
        assertEquals("radiohead" to "creep", overrides.match["radiohead/creep"])
        assertTrue(overrides.alias.isEmpty(), "the artist's own song: no [alias]")
        val song = creep
        assertEquals("accept", song.matchDecision)
        assertEquals("override", song.matchStep)
        assertFalse(song.review)
        assertEquals("Now matched to radiohead/creep: caracole fetch --song \"Radiohead - Creep\" fetches it now, or the " +
                         "nightly run does.", job.steps.single().output.last())
        val line = shownLine(id)
        assertEquals(JsonPrimitive("added"), line["tone"], "$line")
    }

    @Test fun `a pick with Fetch it now is looked up after it, by the phone's own lookup`() {
        val answer = post("/review", "song" to "${creep.id}", "pick" to "radiohead/creep", "shown" to SHOWN,
                          "fetch" to "1", json = false)
        assertEquals(303, answer.status)
        val id = answer.header("location")!!.substringAfter("job=").toInt()
        val job = done(id)
        assertEquals(listOf("review", "get"), job.steps.map { it.args.first() })
        assertEquals("Pick radiohead/creep for Radiohead - Creep, and fetch it", job.spec.title)
        assertTrue(job.fetching)
        assertEquals("done", job.steps[0].state)
        assertEquals("accept", creep.matchDecision, "the lookup's match stage keeps the pick: ${creep.matchStep}")
        val stages = job.stages.associate { it.name to it.state }
        assertEquals("done", stages["match"], "$stages")
    }

    @Test fun `none of these rejects the candidates shown, and a song left with none to pick is not found`() {
        val answer = post("/review", "song" to "${creep.id}", "pick" to "none", "shown" to SHOWN, "fetch" to "1")
        val job = done(answer.json.jsonObject.getValue("job").jsonObject.getValue("id").jsonPrimitive.int)
        assertEquals(listOf(listOf("review", "--song=Radiohead - Creep", "--none", "--seen=radiohead/creep",
                                   "--seen=radiohead/creep-acoustic")), job.steps.map { it.args })
        assertFalse(job.fetching, "None of these fetches nothing")
        val overrides = phone.parts.database.read { Overrides.read(it) }
        assertEquals(setOf("radiohead" to "creep", "radiohead" to "creep-acoustic"), overrides.reject["radiohead/creep"])
        assertFalse(creep.review)
    }

    @Test fun `the picker's page, as the app assembles it, carries the form token, and its form's Pick is taken`() {
        val page = handle("GET", "/review?song=${creep.id}", mapOf("sec-fetch-site" to "same-origin"))
        assertEquals(200, page.status, page.text)
        val html = page.text
        assertFalse("<script" in html)
        assertTrue("<input type=\"hidden\" name=\"csrf\" value=\"${TestApp.CSRF}\">" in html, html)
        assertTrue("<input type=\"hidden\" name=\"shown\" value=\"$SHOWN\">" in html)
        assertTrue("value=\"radiohead/creep\" required autofocus>" in html)
        assertTrue("form-action 'self'" in page.header("content-security-policy")!!)
        assertTrue(Regex("<title>[^<]*Pick the match · caracole[^<]*</title>").containsMatchIn(html), html.take(800))
        // The form as a browser sends it: its hidden fields, the first candidate, Fetch it now as ticked.
        val hidden = Regex("<input type=\"hidden\" name=\"([a-z]+)\" value=\"([^\"]*)\">").findAll(html)
            .map { it.groupValues[1] to it.groupValues[2] }.toList()
        assertEquals(listOf("csrf", "song", "shown"), hidden.map { it.first })
        val pick = Regex("name=\"pick\" value=\"([^\"]*)\"").find(html)!!.groupValues[1]
        val answer = handle(
            "POST", "/review",
            mapOf("sec-fetch-site" to "same-origin", "origin" to "http://${TestApp.HOST}",
                  "content-type" to "application/x-www-form-urlencoded"),
            TestApp.form(hidden + listOf("pick" to pick, "fetch" to "1")),
        )
        assertEquals(303, answer.status, answer.text)
        val location = answer.header("location")!!
        assertTrue(Regex("/#tab=requests&job=\\d+").matches(location), location)
        val job = done(location.substringAfter("job=").toInt())
        assertEquals(listOf("review", "get"), job.steps.map { it.args.first() })
        assertEquals("done", job.steps[0].state, "${job.steps[0].output}")
        assertEquals("radiohead" to "creep", phone.parts.database.read { Overrides.read(it) }.match["radiohead/creep"])
    }

    @Test fun `a pick waits for the song's own request`() {
        val holding = CompletableDeferred<Unit>()
        val (own, _) = phone.queue.submit(JobSpec("Look up ${creep.display}", creep.key, "song", emptyList(),
                                                  display = creep.display, run = { holding.await() }))
        try {
            val refused = post("/review", "song" to "${creep.id}", "pick" to "radiohead/creep", "shown" to SHOWN)
            assertEquals(409, refused.status, refused.text)
            assertEquals("A request for Radiohead - Creep is waiting or running: pick once it ends.",
                         refused.json.jsonObject.getValue("error").jsonPrimitive.content)
            assertEquals(listOf(own.id), phone.queue.snapshot().map { it.id }, "nothing more was queued")
        } finally {
            holding.complete(Unit)
        }
        done(own.id)
        val after = post("/review", "song" to "${creep.id}", "pick" to "radiohead/creep", "shown" to SHOWN)
        assertEquals(200, after.status, "once it ended, the pick is taken: ${after.text}")
        done(after.json.jsonObject.getValue("job").jsonObject.getValue("id").jsonPrimitive.int)
    }

    @Test fun `a page from elsewhere is refused`() {
        val refused = handle(
            "POST", "/review",
            mapOf("sec-fetch-site" to "cross-site", "origin" to "http://evil.example",
                  "content-type" to "application/x-www-form-urlencoded"),
            TestApp.form(listOf("csrf" to TestApp.CSRF, "song" to "${creep.id}", "pick" to "none", "shown" to SHOWN)),
        )
        assertEquals(403, refused.status)
        assertTrue(phone.queue.snapshot().isEmpty(), "nothing was queued")
        assertTrue(creep.review, "nothing was written")
    }

    @Test fun `overrides the phone can't read stop the answer, exit 2, in _common's words`() {
        val runner = ReviewRunner(phone.parts, readOverrides = { throw OverridesError("[match]: not a table") })
        val queue = JobQueue(scope, commands = Commands(mapOf("review" to runner)))
        val (job, _) = queue.submit(JobSpec("Pick radiohead/creep for Radiohead - Creep", creep.key, "review",
                                            emptyList(), display = creep.display, join = false,
                                            commands = JobCommands.reviewSteps(creep.display, pick = "radiohead/creep")))
        val ended = runBlocking { withTimeout(60_000) { queue.await(job.id) } }
        assertEquals("failed", ended.state)
        assertEquals("error: overrides: [match]: not a table", ended.steps.single().output.last())
        assertTrue(creep.review, "nothing was written")
    }

    @Test fun `the command line ends its options at --, as click does`() {
        val asked = ReviewRunner.Asked.of(listOf("review", "--song=Radiohead - Creep", "--pick=1", "--"))
        assertEquals("Radiohead - Creep", asked.song)
        for ((args, said) in listOf(
            listOf("--song=Radiohead - Creep", "--", "--none") to "Got unexpected extra argument (--none)",
            listOf("--song=Radiohead - Creep", "--pick=1", "x", "--", "y") to "Got unexpected extra arguments (x y)",
            listOf("--song=Radiohead - Creep", "--pick=1", "--fetch") to "No such option: --fetch",
        )) {
            val refused = runCatching { ReviewRunner.Asked.of(listOf("review") + args) }.exceptionOrNull()
            assertTrue(refused is CommandExit && refused.code == 2, "$args: $refused")
            assertEquals(said, refused.message)
        }
    }

    private companion object {
        const val SHOWN = "radiohead/creep radiohead/creep-acoustic"
        val CANDIDATES = JsonArray(listOf(
            JsonObject(mapOf("artist_key" to JsonPrimitive("radiohead"), "song_key" to JsonPrimitive("creep"),
                             "score" to JsonPrimitive(88.0), "step" to JsonPrimitive("fuzzy_title"))),
            JsonObject(mapOf("artist_key" to JsonPrimitive("radiohead"), "song_key" to JsonPrimitive("creep-acoustic"),
                             "score" to JsonPrimitive(80.0), "step" to JsonPrimitive("word_title"))),
        )).toString()
    }
}
