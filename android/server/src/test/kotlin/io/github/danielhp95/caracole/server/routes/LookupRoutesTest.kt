package io.github.danielhp95.caracole.server.routes

import io.github.danielhp95.caracole.core.config.PhoneConfig
import io.github.danielhp95.caracole.core.keys.Normalize
import io.github.danielhp95.caracole.core.library.Songs
import io.github.danielhp95.caracole.core.testing.Misses
import io.github.danielhp95.caracole.core.testing.RefusingTransport
import io.github.danielhp95.caracole.core.testing.TestDb
import io.github.danielhp95.caracole.server.Phone
import io.github.danielhp95.caracole.server.PhoneDeps
import io.github.danielhp95.caracole.server.http.Response
import io.github.danielhp95.caracole.server.jobs.Job
import io.github.danielhp95.caracole.server.jobs.JobCommands
import io.github.danielhp95.caracole.server.jobs.JobViews
import io.github.danielhp95.caracole.server.testing.TestApp
import io.github.danielhp95.caracole.server.testing.header
import io.github.danielhp95.caracole.server.testing.json
import io.github.danielhp95.caracole.server.testing.replays.LookupRoutesReplay
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.withTimeout
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.int
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import org.junit.After
import org.junit.Assume
import org.junit.Before
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import java.io.File
import java.net.URLEncoder
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertNotNull
import kotlin.test.assertTrue

/** The library page's lookups on the phone: the routes as caracole serve answers them (the vectors), and the phone
 * whole, as the app assembles it, looking songs up with every site refused. */
class LookupRoutesTest {
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
    }

    @After fun down() {
        scope.cancel()
        phone.parts.database.close()
    }

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

    private fun search(q: String): JsonObject = handle(
        "GET", "/api/search?q=${URLEncoder.encode(q, Charsets.UTF_8)}&box=t",
        mapOf("sec-fetch-site" to "same-origin", "accept" to "application/json", TestApp.TOKEN_HEADER to TestApp.CSRF),
    ).json.jsonObject

    /** The job an answer queued: `{job: N, url, view}` (a lookup's, a read's) or `{job: view}` (a form's). */
    private fun jobOf(answer: Response): Int = when (val job = answer.json.jsonObject.getValue("job")) {
        is JsonPrimitive -> job.int
        else -> job.jsonObject.getValue("id").jsonPrimitive.int
    }

    private fun done(id: Int): Job = runBlocking { withTimeout(60_000) { phone.queue.await(id) } }

    @Test fun `each route answers as caracole serve's (vectors web lookup_routes and api_search_gate)`() {
        val misses = Misses("lookup-routes")
        LookupRoutesReplay.replay(misses)
        misses.assertNone()
    }

    @Test fun `Get it with every site refused adds the song, its sites' stages failed, never a miss`() {
        val answer = post("/lookup", "artist" to "Fito Páez", "title" to "Mariposa Tecknicolor")
        assertEquals(202, answer.status, answer.json.toString())
        val body = answer.json.jsonObject
        val id = jobOf(answer)
        assertEquals("/api/jobs/$id", body.getValue("url").jsonPrimitive.content)
        assertEquals(id, body.getValue("view").jsonObject.getValue("id").jsonPrimitive.int)
        val job = done(id)
        assertEquals(listOf(listOf("get", "--progress", "--", "Fito Páez", "Mariposa Tecknicolor")), job.steps.map { it.args })
        assertEquals("song", job.spec.kind)
        val stages = job.stages.associate { it.name to it.state }
        assertEquals("done", stages["song"], "$stages")
        assertEquals("failed", stages["lyrics"], "LRCLIB refused: $stages")
        // Each site's stage failed, or is skipped while its lane's port is neutral: none found anything.
        for (site in listOf("ug", "lacuerda", "gtptabs", "harptabs", "gametabs")) {
            assertTrue(stages[site] in setOf("failed", "skipped"), "$site: $stages")
        }
        val song = assertNotNull(phone.parts.database.read { Songs.byKey(it, Normalize.identityKey("Fito Páez", "Mariposa Tecknicolor")) })
        assertEquals("Fito Páez", song.artist)
        assertFalse(song.matchDecision == "not_found", "a refused site makes no miss: ${song.matchDecision}")
        assertFalse(song.lyricsStatus == "missing", "a refused site makes no miss: ${song.lyricsStatus}")
        // status.py's line for a song added that no site gave anything yet: the nightly run tries again
        assertEquals("done", job.state)
        assertEquals("Added: the nightly run looks for it", JobViews.line(job).text)
    }

    @Test fun `a lookup the page's script didn't post goes to its line in the Requests tab, the phone having no lookup page`() {
        val answer = post("/lookup", "artist" to "Estopa", "title" to "Como Camarón", json = false)
        assertEquals(303, answer.status)
        val id = phone.queue.snapshot().single().id
        assertEquals("/#tab=requests&job=$id", answer.header("location"))
        done(id)
    }

    @Test fun `Fetch now on the request form is a lookup, which adds the song`() {
        val answer = post("/request", "artist" to "Soda Stereo", "title" to "De Música Ligera", "fetch" to "1")
        val job = done(jobOf(answer))
        assertEquals("song", job.spec.kind)
        assertEquals(JobCommands.LOOKUP, job.steps.single().args.first())
        assertNotNull(phone.parts.database.read { Songs.byKey(it, Normalize.identityKey("Soda Stereo", "De Música Ligera")) })
    }

    @Test fun `a song a lookup added is found by the next search, the search's answers forgotten once a job ends`() {
        assertEquals(0, search("mariposa tecknicolor").getValue("library").jsonArray.size)
        done(jobOf(post("/lookup", "artist" to "Fito Páez", "title" to "Mariposa Tecknicolor")))
        val mine = search("mariposa tecknicolor").getValue("library").jsonArray
        assertEquals(1, mine.size, "$mine")
    }

    @Test fun `with searchesLacuerda false a search offers no LaCuerda search`() {
        assertEquals(JsonNull, search("corazones rotos")["lacuerda_search"])
    }

    @Test fun `with searchesLacuerda false LaCuerda's search route says the query is answered`() {
        Assume.assumeTrue("waiting on lacuerda-pages (LaCuerdaSearch)", LookupRoutesReplay.gateLanded)
        val refused = post("/lacuerda/search", "q" to "corazones rotos")
        assertEquals(409, refused.status, refused.json.toString())
        assertEquals(0, phone.queue.snapshot().size)
    }

    @Test fun `the sites a search leaves out are those the phone's settings turn off`() {
        val before = search("radiohead creep").getValue("skipped").jsonArray.map { it.jsonObject.getValue("source").jsonPrimitive.content }
        assertFalse("gtptabs" in before && "turned off" in search("radiohead creep").toString(), "$before")
        phone.parts.database.writeBlocking { db ->
            PhoneConfig.take(db, JsonObject(mapOf("providers" to JsonObject(mapOf(
                "gtptabs" to JsonObject(mapOf("enabled" to JsonPrimitive(false))),
            )))))
        }
        phone.search.invalidate()
        val skipped = search("radiohead creep").getValue("skipped").jsonArray.map { it.jsonObject }
        val gtptabs = skipped.single { it.getValue("source").jsonPrimitive.content == "gtptabs" }
        assertEquals("turned off in caracole.toml", gtptabs.getValue("why").jsonPrimitive.content)
    }

    @Test fun `Fetch now on a card, an artist's Songs and Fetch them each queue their command`() {
        val added = done(jobOf(post("/request", "artist" to "Estopa", "title" to "Tu Calorro")))
        val id = assertNotNull(added.songId ?: phone.parts.database.read { Songs.byKey(it, "estopa/tu-calorro") }?.id)
        val fetched = done(jobOf(post("/fetch", "song" to "$id")))
        assertEquals(listOf("get", "--progress", "--", "Estopa", "Tu Calorro"), fetched.steps.single().args)
        val none = post("/versions/keep-more", "song" to "$id")
        assertEquals(409, none.status, "a song with no UG version has none to keep")
        val unread = post("/lacuerda/artist", "name" to "Fito Páez")
        assertEquals(202, unread.status, unread.json.toString())
        assertEquals("lacuerda-artist", done(jobOf(unread)).spec.kind)
    }

    @Test fun `the phone keeps its HTTP cache under its state folder`() {
        val clients = phone.parts.clients()
        assertEquals(File(phone.parts.stateDir, "cache"), clients.cacheDir)
    }
}
