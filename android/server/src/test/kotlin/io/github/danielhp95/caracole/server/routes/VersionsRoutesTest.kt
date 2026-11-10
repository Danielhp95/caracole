package io.github.danielhp95.caracole.server.routes

import io.github.danielhp95.caracole.core.http.HttpAnswer
import io.github.danielhp95.caracole.core.http.Transport
import io.github.danielhp95.caracole.core.keys.Normalize
import io.github.danielhp95.caracole.core.library.Kept
import io.github.danielhp95.caracole.core.library.Versions
import io.github.danielhp95.caracole.core.testing.Corpus
import io.github.danielhp95.caracole.core.testing.FakeTransport
import io.github.danielhp95.caracole.core.ug.SheetVersions
import io.github.danielhp95.caracole.viewer.render.WrittenPages
import kotlinx.serialization.json.JsonObject
import java.io.File
import io.github.danielhp95.caracole.core.library.Overrides
import io.github.danielhp95.caracole.core.library.Songs
import io.github.danielhp95.caracole.core.py.PyUrl
import io.github.danielhp95.caracole.core.testing.Fixtures
import io.github.danielhp95.caracole.core.testing.Misses
import io.github.danielhp95.caracole.core.testing.RefusingTransport
import io.github.danielhp95.caracole.core.testing.TestDb
import io.github.danielhp95.caracole.server.Phone
import io.github.danielhp95.caracole.server.PhoneDeps
import io.github.danielhp95.caracole.server.http.MessagePage
import io.github.danielhp95.caracole.server.http.Response
import io.github.danielhp95.caracole.server.jobs.Job
import io.github.danielhp95.caracole.server.jobs.JobCommands
import io.github.danielhp95.caracole.server.testing.TestApp
import io.github.danielhp95.caracole.server.testing.header
import io.github.danielhp95.caracole.server.testing.json
import io.github.danielhp95.caracole.server.testing.replays.ChoicesReplay
import io.github.danielhp95.caracole.server.testing.text
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.withTimeout
import kotlinx.serialization.json.int
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

/**
 * A sheet's versions chosen on the phone: the pages and posts as caracole serve answers them (the vectors), and the
 * phone whole, as the app assembles it, over the vectors' base library (De Música Ligera: its sheet Ver 1, Ver 2 kept
 * beside it, Ver 3 not kept), every site refused: the page a plain GET with the launch's cookie
 * reaches, its form posting with the form token, each post a job of the versions runner under the song's key.
 */
class VersionsRoutesTest {
    @get:Rule val tmp = TemporaryFolder()

    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Default)
    private lateinit var phone: Phone

    /** The sites the phone reaches: every one refused, unless a test answers one. */
    @Volatile private var sites: Transport = RefusingTransport

    private object NoAddress : SyncSettings {
        override val address: String? = null
        override fun remember(address: String) = Unit
    }

    @Before fun up() {
        val database = TestDb.fresh(tmp.newFolder("db"))
        val library = tmp.newFolder("library")
        database.writeBlocking { db ->
            Fixtures.loadRecords(db, ChoicesReplay.scene(ChoicesReplay.VERSIONS, "base"), library)
        }
        phone = Phone(PhoneDeps(database, library, tmp.newFolder("state"), null, scope, NoAddress, TestApp.SECRET,
                                TestApp.CSRF, transport = { sites }, searchesLacuerda = false))
    }

    @After fun down() {
        scope.cancel()
        phone.parts.database.close()
    }

    @Test fun `each page and post answers as caracole serve's (vectors web versions_routes and harmonica_routes)`() {
        val misses = Misses("choices")
        ChoicesReplay.replay(misses)
        misses.assertNone()
        assertTrue(misses.checked >= 250, "${misses.checked} answers compared")
    }

    private fun handle(method: String, target: String, headers: Map<String, String?>, body: ByteArray = ByteArray(0)) =
        phone.app.handle(TestApp.request(method, target, headers, body, TestApp.SECRET))

    /** A top-level navigation: no Origin, no token, the launch's cookie alone (the sandboxed viewer's link). */
    private fun navigate(target: String): Response = handle("GET", target, mapOf("sec-fetch-site" to "cross-site"))

    /** The page's form posted, as the browser posts it from the server's own page. */
    private fun post(target: String, vararg fields: Pair<String, String>, json: Boolean = false,
                     token: String = TestApp.CSRF): Response = handle(
        "POST", target,
        mapOf("sec-fetch-site" to "same-origin", "origin" to "http://${TestApp.HOST}",
              "content-type" to "application/x-www-form-urlencoded") +
            (if (json) mapOf("accept" to "application/json") else emptyMap()),
        TestApp.form(listOf("csrf" to token) + fields),
    )

    private fun done(id: Int): Job = runBlocking { withTimeout(120_000) { phone.queue.await(id) } }

    private fun versions(tab: String, doing: String, sheet: String = SHEET): String =
        "/versions?" + PyUrl.urlencode(listOf("sheet" to sheet, "tab" to tab, "do" to doing))

    private fun jobOf(location: String): Int = location.substringAfterLast("job=").toInt()

    private fun ligera() = phone.parts.database.read { db ->
        Songs.byKey(db, Normalize.identityKey("Soda Stereo", "De Música Ligera"))!!
    }

    private fun pins(): List<Long> = phone.parts.database.read { db -> Overrides.read(db).pin[ligera().key].orEmpty() }

    @Test fun `a plain GET with the launch's cookie reaches the page, whose one form carries the phone's token`() {
        val page = navigate(versions(OTHER, "keep"))
        assertEquals(200, page.status, page.text)
        assertEquals(MessagePage.csp, page.header("Content-Security-Policy"))
        assertEquals("text/html; charset=utf-8", page.header("Content-Type"))
        assertTrue("<form class=\"confirm\" method=\"post\" action=\"/versions/keep\">" in page.text, page.text)
        assertTrue("name=\"csrf\" value=\"${TestApp.CSRF}\"" in page.text)
        assertTrue("<span class=\"scratch\"" in page.text, "the phone's badge")
        assertFalse("<script" in page.text)
        // without the launch's cookie, nothing is read
        val stranger = phone.app.handle(TestApp.request("GET", versions(OTHER, "keep"), emptyMap(), ByteArray(0), null))
        assertEquals(403, stranger.status)
        // a viewer the phone never wrote names no sheet
        assertEquals(404, navigate(versions(OTHER, "keep", sheet = "Soda Stereo/De Música Ligera/version-$OTHER.html")).status)
    }

    @Test fun `a form posted without the token or from another site queues nothing`() {
        assertEquals(403, post("/versions/keep", "sheet" to SHEET, "tab" to OTHER, token = "old").status)
        val elsewhere = handle("POST", "/versions/keep",
                               mapOf("sec-fetch-site" to "cross-site", "origin" to "http://evil.example",
                                     "content-type" to "application/x-www-form-urlencoded"),
                               TestApp.form(listOf("csrf" to TestApp.CSRF, "sheet" to SHEET, "tab" to OTHER)))
        assertEquals(403, elsewhere.status)
        assertTrue(phone.queue.snapshot().isEmpty())
    }

    @Test fun `keep it runs the versions runner under the song's key, and the page follows the job to its end`() {
        val posted = post("/versions/keep", "sheet" to SHEET, "tab" to OTHER)
        assertEquals(303, posted.status, posted.text)
        val location = posted.header("Location")!!
        assertTrue(location.startsWith(versions(OTHER, "keep") + "&job="), location)
        val job = done(jobOf(location))
        assertEquals(ligera().key, job.key)
        assertEquals(listOf(listOf("versions", "--keep=$OTHER", "--progress", "--", "Soda Stereo", "De Música Ligera")),
                     job.steps.map { it.args })
        val page = navigate(location)
        assertEquals(200, page.status)
        assertFalse("http-equiv=\"refresh\"" in page.text, "a job over reloads no more")
        // every site refused: nothing kept, said from the song's state, never from the command's exit
        assertTrue(if (job.state == Job.DONE) "Done, but it wasn't kept" in page.text else "Failed" in page.text,
                   page.text)
        // by the song's id, to the page's script: the job itself
        val again = post("/versions/keep", "song" to ligera().id.toString(), "tab" to OTHER, json = true)
        assertEquals(200, again.status, again.text)
        assertTrue(again.json.jsonObject.getValue("job").jsonObject.getValue("id").jsonPrimitive.int > 0)
    }

    @Test fun `make this the one pins the version and looks the song up, and back to caracole's pick takes the pin out`() {
        val chose = post("/versions/choose", "sheet" to SHEET, "tab" to OTHER)
        assertEquals(303, chose.status, chose.text)
        val job = done(jobOf(chose.header("Location")!!))
        assertEquals(listOf("versions", "--choose=$OTHER", "--progress", "--", "Soda Stereo", "De Música Ligera"),
                     job.steps.single().args)
        assertTrue(job.stages.map { it.name }.containsAll(JobCommands.GET_STAGES.map { it.first }), "a lookup's stages")
        assertEquals("done", job.stages.first { it.name == "song" }.state, "${job.stages.map { it.name to it.state }}")
        // the choice recorded under [pin], in place of the text tab's pin, which no offline index tells apart from it
        // (get.py's _other_pins)
        assertEquals(listOf(OTHER.toLong()), pins())
        // its pin is a new match (match.py's _save): the versions found under the old one wait, stale, for UG to list
        // them again, which every site refused never did; the page then knows no such version, as caracole serve's
        assertEquals(404, navigate(chose.header("Location")!!).status)

        val cleared = post("/versions/clear", "sheet" to SHEET)
        assertEquals(303, cleared.status, cleared.text)
        val back = done(jobOf(cleared.header("Location")!!))
        assertEquals(listOf("versions", "--clear", "--progress", "--", "Soda Stereo", "De Música Ligera"),
                     back.steps.single().args)
        assertEquals(emptyList(), pins(), "the sheet's pin out")
        assertTrue("Done: caracole picks the sheet again." in navigate(cleared.header("Location")!!).text)
        assertEquals(409, post("/versions/clear", "sheet" to SHEET).status, "no pin of its sheet to go back from")
    }

    @Test fun `keep it keeps the version beside the sheet with its page, and the page opens it`() {
        // UG's version 85053 of the song (tests/fixtures/ug/tab_chords.html, at its own address), not kept yet
        val url = "https://tabs.ultimate-guitar.com/tab/85053"
        phone.parts.database.writeBlocking { db ->
            Versions.upsert(db, "ug", "85053", ligera().id, "sheet", "chords", 4.54038, 7, 6, null, url,
                            JsonObject(emptyMap()), "2026-11-03T10:00:00Z")
        }
        val ug = FakeTransport(mapOf("GET $url" to HttpAnswer(200, listOf("content-type" to "text/html; charset=utf-8"),
                                                               Corpus.fixture("ug/tab_chords.html"))))
        sites = ug
        val posted = post("/versions/keep", "sheet" to SHEET, "tab" to "85053")
        assertEquals(303, posted.status, posted.text)
        val job = done(jobOf(posted.header("Location")!!))
        assertEquals(Job.DONE, job.state, job.output.toString())
        assertEquals(listOf("GET $url"), ug.said, "one tab page, at the lookup pace")
        val (txt, data, page) = SheetVersions.versionNames("85053")
        phone.parts.database.read { db ->
            val kept = Kept.keptFiles(db, ligera().id).map { it.name }
            assertTrue(txt in kept && data in kept, "$kept")
            assertTrue(WrittenPages.written(db, ligera().id, page) != null, "its page written and recorded")
        }
        assertTrue(File(phone.parts.store.folderOf(ligera()), page).isFile)
        val said = navigate(posted.header("Location")!!).text
        assertTrue("Done: it is kept beside the sheet." in said, said)
        assertTrue("<a class=\"btn primary\" href=\"/Soda%20Stereo/De%20M%C3%BAsica%20Ligera/$page\">Open it</a>" in said)
    }

    private companion object {
        const val SHEET = "Soda Stereo/De Música Ligera/sheet.html"
        const val OTHER = "1064463"
    }
}
