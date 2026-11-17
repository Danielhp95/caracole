package io.github.danielhp95.caracole.server.routes

import io.github.danielhp95.caracole.core.testing.RefusingTransport
import io.github.danielhp95.caracole.core.testing.TestDb
import io.github.danielhp95.caracole.core.ug.UgLinks
import io.github.danielhp95.caracole.server.Phone
import io.github.danielhp95.caracole.server.PhoneDeps
import io.github.danielhp95.caracole.server.http.Response
import io.github.danielhp95.caracole.server.jobs.Job
import io.github.danielhp95.caracole.server.jobs.JobCommands
import io.github.danielhp95.caracole.server.testing.TestApp
import io.github.danielhp95.caracole.server.testing.json
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.withTimeout
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonNull
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
import java.net.URLEncoder
import kotlin.test.assertEquals
import kotlin.test.assertTrue

/** A UG link pasted into the library page's search box, on the phone whole, as the app assembles it, every site
 * refused: what `/api/ug/link` says of a link, and `POST /ug/link`'s read queued, run and refused. The routes'
 * answers to the byte are UgLinkReplay's (vectors/web/ug_link.jsonl). */
class UgLinkRoutesTest {
    @get:Rule val tmp = TemporaryFolder()

    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Default)
    private lateinit var phone: Phone

    private object NoAddress : SyncSettings {
        override val address: String? = null
        override fun remember(address: String) = Unit
    }

    private val banma = "https://tabs.ultimate-guitar.com/tab/4180894"

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

    private fun post(url: String): Response = handle(
        "POST", "/ug/link",
        mapOf("sec-fetch-site" to "same-origin", "origin" to "http://${TestApp.HOST}",
              "content-type" to "application/x-www-form-urlencoded", "accept" to "application/json"),
        TestApp.form(listOf("csrf" to TestApp.CSRF, "url" to url)),
    )

    private fun known(url: String): JsonObject = handle(
        "GET", "/api/ug/link?url=${URLEncoder.encode(url, Charsets.UTF_8)}",
        mapOf("sec-fetch-site" to "same-origin", "accept" to "application/json", TestApp.TOKEN_HEADER to TestApp.CSRF),
    ).json.jsonObject

    private fun done(id: Int): Job = runBlocking { withTimeout(60_000) { phone.queue.await(id) } }

    @Test fun `words are no link, and nothing is queued`() {
        assertEquals(400, post("banma ultimate guitar").status)
        assertEquals(400, handle("GET", "/api/ug/link?url=banma", mapOf("sec-fetch-site" to "same-origin")).status)
        assertEquals(0, phone.queue.snapshot().size)
    }

    @Test fun `a link caracole doesn't know is read by itself once, its failure remembered for the hour`() {
        val before = known(banma)
        assertEquals("auto", before.getValue("state").jsonPrimitive.content, "$before")
        assertEquals(JsonNull, before["tab"])
        assertEquals(JsonArray(emptyList()), before["hits"])
        val answer = post(banma)
        assertEquals(202, answer.status, answer.json.toString())
        val id = answer.json.jsonObject.getValue("job").jsonPrimitive.int
        assertEquals("/api/jobs/$id", answer.json.jsonObject.getValue("url").jsonPrimitive.content)
        val again = post(banma)  // asked again while it waits or runs: that job, or refused once it failed
        assertTrue(again.status == 202 || again.status == 429, "${again.status}")
        val job = done(id)
        assertEquals(JobCommands.UG_LINK + banma, job.key)
        assertEquals(listOf(listOf("ug", "--link=$banma", "--progress")), job.steps.map { it.args })
        assertEquals("Read tab 4180894 on Ultimate Guitar", job.spec.title)
        assertEquals("A tab on Ultimate Guitar", job.display)
        assertEquals(listOf("tab", "artist"), job.stages.map { it.name })
        val last = job.output.last()
        assertTrue(last.startsWith("Not read: UG failed ("), last)
        // its progress lines are the job's stages, never its output: the tab's ended with the line, as the panel reads it
        assertTrue(job.output.none { it.startsWith("caracole-progress: ") }, "${job.output}")
        val tab = job.stages.first { it.name == "tab" }
        assertEquals("skipped" to last, tab.state to tab.detail)
        assertEquals("skipped", job.stages.first { it.name == "artist" }.state)  // never asked: the queue ends it so
        val after = known(banma)
        assertEquals("failed", after.getValue("state").jsonPrimitive.content, "$after")
        assertTrue(after.getValue("why").jsonPrimitive.content.startsWith("reading it failed within the hour ("), "$after")
        assertEquals(429, post(banma).status)
        assertTrue(phone.parts.database.read { it.kvGet(UgLinks.FAILED_KEY) }!!.contains(banma))
    }

    /** The panel sends the text pasted as it is (any address `read_link` reads), and its Fetch this version posts the
     * server's `url`, a bare `/tab/{id}` here, as the lookup's `tab` (rows.js getIt: POST /lookup). */
    @Test fun `the pasted text is taken as given, and the link's address is a tab a lookup takes`() {
        val pasted = "  tabs.ultimate-guitar.com/tab/4180894?ref=share\u3000"
        assertEquals(banma, known(pasted).getValue("url").jsonPrimitive.content)
        val read = post(pasted)
        assertEquals(202, read.status, read.json.toString())
        done(read.json.jsonObject.getValue("job").jsonPrimitive.int)
        val lookup = handle(
            "POST", "/lookup",
            mapOf("sec-fetch-site" to "same-origin", "origin" to "http://${TestApp.HOST}",
                  "content-type" to "application/x-www-form-urlencoded", "accept" to "application/json"),
            TestApp.form(listOf("csrf" to TestApp.CSRF, "artist" to "宋冬野", "title" to "斑马斑马", "tab" to banma)),
        )
        assertEquals(202, lookup.status, lookup.json.toString())
        val job = done(lookup.json.jsonObject.getValue("job").jsonPrimitive.int)
        assertEquals(listOf(listOf("get", "--progress", "--tab=$banma", "--", "宋冬野", "斑马斑马")), job.steps.map { it.args })
        assertEquals(Job.DONE, job.state, job.output.toString())
    }

    @Test fun `a tab the index lists is found, its song the hit, and nothing is read`() {
        phone.parts.database.writeBlocking { db ->
            db.execute("INSERT INTO ug_index (tab_id, artist_key, song_key, type, sitemap, first_seen, path) " +
                           "VALUES (85053, 'soda-stereo', 'de-musica-ligera', 'chords', '1', 'x', " +
                           "'soda-stereo/de-musica-ligera-chords-85053')")
        }
        val said = known("ultimate-guitar.com/tab/soda-stereo/de-musica-ligera-chords-85053?app=1")
        assertEquals("found", said.getValue("state").jsonPrimitive.content, "$said")
        assertEquals("chords", said.getValue("type").jsonPrimitive.content)
        val hits = said.getValue("hits").jsonArray
        assertEquals(1, hits.size, "$hits")
        assertEquals("soda-stereo/de-musica-ligera", hits[0].jsonObject.getValue("ug").jsonPrimitive.content)
        assertEquals(409, post("https://tabs.ultimate-guitar.com/tab/soda-stereo/de-musica-ligera-chords-85053").status)
        assertEquals(0, phone.queue.snapshot().size)
    }

    @Test fun `a tab of a type caracole keeps nothing of is said so with no request`() {
        val url = "https://tabs.ultimate-guitar.com/tab/metallica/one-guitar-pro-225441"
        val said = known(url)
        assertEquals("other", said.getValue("state").jsonPrimitive.content)
        assertEquals("it is a Guitar Pro file: ${UgLinks.KEEPS}", said.getValue("why").jsonPrimitive.content)
        val refused = post(url)
        assertEquals(409, refused.status)
        assertEquals(0, phone.queue.snapshot().size)
    }

    /** UG's artist directory, as a merge of the computer's index brings it: a search finds an artist it names whose
     * page caracole hasn't read, and their row's Read their page on UG (rows.js readArtistPage: POST /ug/link with
     * the row's `url`) is the link's read of that artist page, bare or slugged. */
    @Test fun `an artist the directory names is a search's row whose address the link reads`() {
        phone.parts.database.writeBlocking { db ->
            for ((id, name, slug, key) in listOf(listOf("7001", "Joaquín Sabina", "", "joaquin-sabina"),
                                                 listOf("7006", "Los Rodríguez", "los_rodriguez", "los-rodriguez"))) {
                db.execute("INSERT INTO ug_directory (artist_id, name, slug, letter, place, tabs, updated_at, artist_key, " +
                               "forms, seen_at) VALUES (?, ?, ?, ?, 0, 230, '', ?, ?, '2026-11-03T10:00:00Z')",
                           id.toLong(), name, slug, key.take(1), key, "$key ${key.replace("-", "")}")
            }
        }
        for ((query, url) in listOf("joaquin sabina" to "https://www.ultimate-guitar.com/artist/7001",
                                    "Los Rodríguez" to "https://www.ultimate-guitar.com/artist/los_rodriguez_7006")) {
            val answer = handle(
                "GET", "/api/search?q=${URLEncoder.encode(query, Charsets.UTF_8)}&box=b",
                mapOf("sec-fetch-site" to "same-origin", "accept" to "application/json", TestApp.TOKEN_HEADER to TestApp.CSRF),
            ).json.jsonObject
            val rows = answer.getValue("ug_directory").jsonArray
            assertEquals(1, rows.size, "$answer")
            val row = rows[0].jsonObject
            assertEquals(url, row.getValue("url").jsonPrimitive.content)
            assertEquals("auto", row.getValue("state").jsonPrimitive.content)
            assertEquals(4, row.getValue("requests").jsonPrimitive.int)  // a list a kind, then one each further 100 tabs
            assertEquals(JsonNull, answer["hint"])  // an artist the listings name is no artist the index can't see
            assertEquals(JsonNull, answer["unseen"])
            assertEquals(JsonPrimitive("auto"), known(url)["state"])
            val read = post(url)
            assertEquals(202, read.status, read.json.toString())
            val job = done(read.json.jsonObject.getValue("job").jsonPrimitive.int)
            assertEquals(JobCommands.UG_LINK + url, job.key)
            assertEquals(listOf(listOf("ug", "--link=$url", "--progress")), job.steps.map { it.args })
            assertEquals(listOf("artist"), job.stages.map { it.name })
        }
    }

    @Test fun `an artist link's job has the artist page's stage alone`() {
        val url = "https://www.ultimate-guitar.com/artist/634073"
        assertEquals(JsonPrimitive("auto"), known(url)["state"])
        val job = done(post(url).json.jsonObject.getValue("job").jsonPrimitive.int)
        assertEquals(listOf("artist"), job.stages.map { it.name })
        assertEquals("An artist on Ultimate Guitar", job.display)
        assertEquals("Read an artist's page on Ultimate Guitar", job.spec.title)
    }
}
