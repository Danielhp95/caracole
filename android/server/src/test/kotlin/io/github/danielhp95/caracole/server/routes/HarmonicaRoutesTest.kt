package io.github.danielhp95.caracole.server.routes

import io.github.danielhp95.caracole.core.config.PhoneConfig
import io.github.danielhp95.caracole.core.db.Database
import io.github.danielhp95.caracole.core.health.Alerts
import io.github.danielhp95.caracole.core.keys.Normalize
import io.github.danielhp95.caracole.core.library.LibraryStore
import io.github.danielhp95.caracole.core.library.Overrides
import io.github.danielhp95.caracole.core.library.Songs
import io.github.danielhp95.caracole.core.lookup.Clients
import io.github.danielhp95.caracole.core.lookup.Pacing
import io.github.danielhp95.caracole.core.lookup.RenderStats
import io.github.danielhp95.caracole.core.lookup.SongPages
import io.github.danielhp95.caracole.core.lookup.SongbookPages
import io.github.danielhp95.caracole.core.py.PyUrl
import io.github.danielhp95.caracole.core.testing.Fixtures
import io.github.danielhp95.caracole.core.testing.RefusingTransport
import io.github.danielhp95.caracole.core.testing.TestDb
import io.github.danielhp95.caracole.server.Phone
import io.github.danielhp95.caracole.server.PhoneDeps
import io.github.danielhp95.caracole.server.PhoneParts
import io.github.danielhp95.caracole.server.http.MessagePage
import io.github.danielhp95.caracole.server.http.Response
import io.github.danielhp95.caracole.server.jobs.CommandExit
import io.github.danielhp95.caracole.server.jobs.Job
import io.github.danielhp95.caracole.server.jobs.JobCommands
import io.github.danielhp95.caracole.server.jobs.JobContext
import io.github.danielhp95.caracole.server.jobs.JobQueue
import io.github.danielhp95.caracole.server.lookups.HarmonicaRunner
import io.github.danielhp95.caracole.server.page.MirrorPageData
import io.github.danielhp95.caracole.server.testing.TestApp
import io.github.danielhp95.caracole.server.testing.header
import io.github.danielhp95.caracole.server.testing.replays.ChoicesReplay
import io.github.danielhp95.caracole.server.testing.text
import io.github.danielhp95.caracole.viewer.render.WrittenPages
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.withTimeout
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import org.junit.After
import org.junit.Before
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import java.io.File
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith
import kotlin.test.assertFalse
import kotlin.test.assertTrue

/**
 * A harmonica tab's readings chosen on the phone, the phone whole as the app assembles it, over the vectors' Spokey
 * Dokey (harmonica-1.txt, a tab with its own legend, its page written; harmonica-2.txt, signs with a bend changed):
 * the page a plain GET with the launch's cookie reaches, each reading's form posting with the form token, each post a
 * job of the harmonica runner under jobs.READING, which pins the reading in `[harmonica]` (or takes it out) and
 * renders the song again. The pages and posts against caracole serve's are VersionsRoutesTest's replay.
 */
class HarmonicaRoutesTest {
    @get:Rule val tmp = TemporaryFolder()

    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Default)
    private lateinit var phone: Phone
    private lateinit var database: Database
    private lateinit var library: File

    private object NoAddress : SyncSettings {
        override val address: String? = null
        override fun remember(address: String) = Unit
    }

    @Before fun up() {
        database = TestDb.fresh(tmp.newFolder("db"))
        library = tmp.newFolder("library")
        database.writeBlocking { db ->
            Fixtures.loadRecords(db, ChoicesReplay.scene(ChoicesReplay.HARMONICA, "spokey"), library)
        }
        phone = Phone(PhoneDeps(database, library, tmp.newFolder("state"), null, scope, NoAddress, TestApp.SECRET,
                                TestApp.CSRF, transport = { RefusingTransport }, searchesLacuerda = false))
    }

    @After fun down() {
        scope.cancel()
        database.close()
    }

    private fun handle(method: String, target: String, headers: Map<String, String?>, body: ByteArray = ByteArray(0)) =
        phone.app.handle(TestApp.request(method, target, headers, body, TestApp.SECRET))

    /** A top-level navigation from the sandboxed tab's page: the launch's cookie alone. */
    private fun navigate(target: String): Response = handle("GET", target, mapOf("sec-fetch-site" to "cross-site"))

    private fun post(target: String, vararg fields: Pair<String, String>): Response = handle(
        "POST", target,
        mapOf("sec-fetch-site" to "same-origin", "origin" to "http://${TestApp.HOST}",
              "content-type" to "application/x-www-form-urlencoded"),
        TestApp.form(listOf("csrf" to TestApp.CSRF) + fields),
    )

    private fun done(id: Int): Job = runBlocking { withTimeout(60_000) { phone.queue.await(id) } }

    private fun readings(page: String = PAGE, extra: String = ""): String =
        "/harmonica?" + PyUrl.urlencode(listOf("page" to page)) + extra

    private fun spokey() = database.read { db -> Songs.byKey(db, Normalize.identityKey("Cowboy Bebop", "Spokey Dokey"))!! }

    private fun pinned(): Map<String, Any> = database.read { db -> Overrides.read(db).harmonica[spokey().key].orEmpty() }

    @Test fun `a plain GET with the launch's cookie reaches the readings, each form carrying the phone's token`() {
        val page = navigate(readings())
        assertEquals(200, page.status, page.text)
        assertEquals(MessagePage.csp, page.header("Content-Security-Policy"))
        assertTrue("from the tab&#x27;s own legend" in page.text, page.text)
        assertEquals(6, Regex("action=\"/harmonica/pin\"").findAll(page.text).count())
        assertTrue("name=\"csrf\" value=\"${TestApp.CSRF}\"" in page.text)
        assertFalse("<script" in page.text)
        assertEquals(404, navigate(readings("Cowboy Bebop/Spokey Dokey/harmonica-5.html")).status, "a page of no tab")
        assertEquals(403, phone.app.handle(TestApp.request("GET", readings(), emptyMap(), ByteArray(0), null)).status)
    }

    @Test fun `a reading pinned writes harmonica, and back to caracole's guess takes it out`() {
        val posted = post("/harmonica/pin", "page" to PAGE, "as" to "letters")
        assertEquals(303, posted.status, posted.text)
        val location = posted.header("Location")!!
        assertTrue(location.startsWith(readings() + "&job="), location)
        val job = done(location.substringAfterLast("=").toInt())
        assertEquals(Job.DONE, job.state, job.output.toString())
        assertEquals("${JobCommands.READING}${spokey().key}:harmonica-1.txt:\"letters\"${JobCommands.MINE}", job.key)
        assertEquals(listOf("harmonica", "--tab=harmonica-1.txt", "--as=letters", "--", "Cowboy Bebop", "Spokey Dokey"),
                     job.steps.single().args)
        assertEquals(mapOf("harmonica-1.txt" to JsonPrimitive("letters")), pinned())
        // the tab's page made again (PhoneRender), read as you set it
        val tabPage = File(phone.parts.store.folderOf(spokey()), "harmonica-1.html")
        assertTrue(tabPage.isFile)
        assertTrue("\"source\":\"pinned\"" in tabPage.readText(), "the page's reading is the pin")
        database.read { db -> assertTrue(WrittenPages.current(db, spokey().id, "harmonica-1.html")) }
        val after = navigate(location)
        assertTrue("Done · read as b blow · d draw · * bend · - joins, as you set it." in after.text, after.text)
        assertTrue("Back to our guess" in after.text)
        assertEquals(409, post("/harmonica/pin", "page" to PAGE, "as" to "letters").status, "read so already")

        val table = post("/harmonica/pin", "page" to "Cowboy Bebop/Spokey Dokey/harmonica-2.html",
                         "as" to """{"as": "signs", "*": "bend"}""")
        val read = done(table.header("Location")!!.substringAfterLast("=").toInt())
        assertEquals(listOf("harmonica", "--tab=harmonica-2.txt", "--as=signs", "--symbol=*=bend", "--", "Cowboy Bebop",
                            "Spokey Dokey"), read.steps.single().args)
        assertEquals(JsonObject(mapOf("as" to JsonPrimitive("signs"), "*" to JsonPrimitive("bend"))),
                     pinned()["harmonica-2.txt"])

        val cleared = post("/harmonica/clear", "page" to PAGE)
        assertEquals(303, cleared.status, cleared.text)
        done(cleared.header("Location")!!.substringAfterLast("=").toInt())
        assertFalse("harmonica-1.txt" in pinned(), "${pinned()}")
        assertTrue("Done · we guess its reading again." in navigate(cleared.header("Location")!!).text)
        assertEquals(409, post("/harmonica/clear", "page" to PAGE).status, "nothing pinned to take out")
    }

    /** A runner over the phone's database whose render is [pages]. */
    private fun runner(pages: SongPages): HarmonicaRunner {
        val state = tmp.newFolder()
        val parts = PhoneParts(database, LibraryStore(library), state, { PhoneConfig.DEFAULTS }, JobQueue(scope),
                               MirrorPageData(null),
                               { Clients(PhoneConfig.DEFAULTS, File(state, "cache"), { RefusingTransport }, Pacing.REAL) },
                               pages, SongbookPages.NONE, Alerts.NONE, Pacing.REAL, searchesLacuerda = false)
        return HarmonicaRunner(parts)
    }

    private class Said : JobContext {
        val lines = ArrayList<String>()
        override fun stage(name: String, state: String, detail: String) {}
        override fun say(line: String) { lines += line }
        override fun outcome(value: JsonObject) {}
        override val isCancelled = false
    }

    @Test fun `the runner renders the song again after a pin or a clear, never after a usage error`() {
        val rendered = ArrayList<Long>()
        val run = runner { _, ids, _ -> rendered += ids; RenderStats() }
        val song = listOf("--", "Cowboy Bebop", "Spokey Dokey")
        runBlocking { run.run(listOf("harmonica", "--tab=harmonica-1.txt", "--as=brackets") + song, Said()) }
        assertEquals(listOf(spokey().id), rendered)
        runBlocking { run.run(listOf("harmonica", "--tab=harmonica-1.txt", "--clear") + song, Said()) }
        assertEquals(listOf(spokey().id, spokey().id), rendered)
        val refused = assertFailsWith<CommandExit> {
            runBlocking { run.run(listOf("harmonica", "--tab=harmonica-2.txt", "--as=legend") + song, Said()) }
        }
        assertEquals(2, refused.code)
        assertEquals(2, rendered.size, "a usage error renders nothing")
        // pages that couldn't all be made fail the command, the pin written
        val failing = runner { _, ids, _ -> RenderStats(failed = ids.associateWith { "no font" }) }
        val failed = assertFailsWith<CommandExit> {
            runBlocking { failing.run(listOf("harmonica", "--tab=harmonica-1.txt", "--as=letters") + song, Said()) }
        }
        assertEquals(1, failed.code)
        assertEquals("Cowboy Bebop - Spokey Dokey: its pages could not all be rendered again; the log says why",
                     failed.message)
    }

    @Test fun `with neither, the runner says how each tab is read and the readings it weighs`() {
        val said = Said()
        runBlocking { runner(SongPages.NONE).run(listOf("harmonica", "--", "Cowboy Bebop - Spokey Dokey"), said) }
        assertEquals("harmonica-1.txt: read as b blow · d draw · * bend · - joins · (h) hold · (w) wah, from the tab's " +
                     "own legend (Q 0.96)", said.lines[0])
        assertEquals("  legend       Q 0.96  b blow · d draw · * bend · - joins · (h) hold · (w) wah", said.lines[1])
        assertTrue(said.lines.any { it == "harmonica-4.txt: can't be read" }, "${said.lines}")
    }

    private companion object {
        const val PAGE = "Cowboy Bebop/Spokey Dokey/harmonica-1.html"
    }
}
