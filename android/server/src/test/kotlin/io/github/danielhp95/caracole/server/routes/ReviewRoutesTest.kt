package io.github.danielhp95.caracole.server.routes

import io.github.danielhp95.caracole.core.library.Overrides
import io.github.danielhp95.caracole.core.library.Songs
import io.github.danielhp95.caracole.core.testing.Misses
import io.github.danielhp95.caracole.core.testing.RefusingTransport
import io.github.danielhp95.caracole.core.testing.TestDb
import io.github.danielhp95.caracole.server.Phone
import io.github.danielhp95.caracole.server.PhoneDeps
import io.github.danielhp95.caracole.server.http.Response
import io.github.danielhp95.caracole.server.jobs.Job
import io.github.danielhp95.caracole.server.jobs.JobViews
import io.github.danielhp95.caracole.server.testing.TestApp
import io.github.danielhp95.caracole.server.testing.header
import io.github.danielhp95.caracole.server.testing.json
import io.github.danielhp95.caracole.server.testing.replays.ReviewReplay
import io.github.danielhp95.caracole.server.testing.text
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
import kotlin.test.assertNotNull
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

    @Test fun `the picker's page carries the form token, the candidates and no script`() {
        val routes = ReviewRoutes(phone.parts, csrf = { TestApp.CSRF }, libraryName = { "Tabs" })
        val page = routes.routes.first { it.method == "GET" }.get!!
            .answer(TestApp.request("GET", "/review?song=${creep.id}", emptyMap(), ByteArray(0), TestApp.SECRET))
        assertEquals(200, page.status)
        val html = page.text
        assertFalse("<script" in html)
        assertTrue("<input type=\"hidden\" name=\"csrf\" value=\"${TestApp.CSRF}\">" in html)
        assertTrue("<input type=\"hidden\" name=\"shown\" value=\"$SHOWN\">" in html)
        assertTrue("value=\"radiohead/creep\" required autofocus>" in html)
        assertTrue("form-action 'self'" in page.header("content-security-policy")!!)
        assertTrue("<title>Phone · Pick the match · caracole · Tabs</title>" in html, html.take(800))
    }

    @Test fun `a pick waits for the song's own request, and a page from elsewhere is refused`() {
        val first = post("/review", "song" to "${creep.id}", "pick" to "radiohead/creep", "shown" to SHOWN)
        assertEquals(200, first.status)
        val refused = handle(
            "POST", "/review",
            mapOf("sec-fetch-site" to "cross-site", "origin" to "http://evil.example",
                  "content-type" to "application/x-www-form-urlencoded"),
            TestApp.form(listOf("csrf" to TestApp.CSRF, "song" to "${creep.id}", "pick" to "none", "shown" to SHOWN)),
        )
        assertEquals(403, refused.status)
        val id = first.json.jsonObject.getValue("job").jsonObject.getValue("id").jsonPrimitive.int
        done(id)
        assertNotNull(phone.queue.job(id))
        assertEquals(1, phone.queue.snapshot().size, "nothing more was queued")
        assertEquals(JobViews.detailsHref(id), "#tab=requests&job=$id")
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
