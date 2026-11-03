package io.github.danielhp95.caracole.server.page

import io.github.danielhp95.caracole.core.testing.Corpus
import io.github.danielhp95.caracole.server.http.AppConfig
import io.github.danielhp95.caracole.server.http.Response
import io.github.danielhp95.caracole.server.testing.TestApp
import io.github.danielhp95.caracole.server.testing.bytes
import io.github.danielhp95.caracole.server.testing.text
import kotlinx.serialization.json.int
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import kotlinx.serialization.json.long
import org.junit.After
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import kotlin.test.assertContentEquals
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertTrue

/** GET /, /index.html and /favicon.ico through the phone's App (TestApp), as caracole serve answers them: their
 * status and every header (vectors/web/library_page.json's `routes`), a HEAD as its GET, and nothing without the
 * launch's cookie. */
class PageRoutesTest {
    @get:Rule val tmp = TemporaryFolder()

    private val vector = Corpus.json("web/library_page.json")
    private val served = vector.getValue("routes").jsonObject
    private val page = LibraryPage(LibraryAssets.load())
    private val opened = ArrayList<TestApp>()

    @After fun close() = opened.forEach { it.close() }

    /** The App with the page's routes alone, over a mirror of the computer's page of two songs. */
    private fun app(controls: ServerControls = ServerControls(TestApp.CSRF, sync = true),
                    libraryName: String = AppConfig.PHONE): TestApp {
        val mirror = mirrorOf(tmp.newFolder(), libraryPage(mirroredData(listOf(
            mirroredCard(10, "estopa/tu-calorro", "Estopa", "Tu Calorro"), mirroredCard(11, "oasis/wonderwall", "Oasis", "Wonderwall")))))
        return TestApp(tmp.newFolder(), modules = { database ->
            listOf(PageRoutes(database, page, MirrorPageData(mirror), { controls }, libraryName))
        }).also { opened.add(it) }
    }

    private fun headers(response: Response) = response.headers.map { listOf(it.first, it.second) }

    private fun pythons(path: String): List<List<String>> =
        served.getValue(path).jsonObject.getValue("headers").jsonArray.map { pair -> pair.jsonArray.map { it.jsonPrimitive.content } }

    @Test
    fun `the routes are the page's three`() {
        val routes = PageRoutes(app().database, page, MirrorPageData(null), { ServerControls("tok") }).routes
        assertEquals(listOf("GET /", "GET /index.html", "GET /favicon.ico"), routes.map { "${it.method} ${it.path}" })
        assertTrue(routes.all { it.doc.isNotEmpty() && !it.scriptOnly && !it.under })
    }

    @Test
    fun `the library page is answered with caracole serve's status and headers, built of the phone's data`() {
        val test = app()
        val calorro = addSong(test.database, "estopa/tu-calorro", "Estopa", "Tu Calorro")
        for (path in listOf("/", "/index.html")) {
            val response = test.get(path)
            assertEquals(served.getValue(path).jsonObject.getValue("status").jsonPrimitive.int, response.status)
            assertEquals(pythons(path), headers(response), path)
            val html = response.text
            val data = MirrorPageData.dataBlock(html.toByteArray())!!
            assertEquals(listOf(calorro, -1L), data.getValue("songs").jsonArray.map { it.jsonObject.getValue("id").jsonPrimitive.long })
            assertEquals(TestApp.CSRF, data.getValue("server").jsonObject.getValue("csrf").jsonPrimitive.content)
            assertTrue("<title>Phone · caracole · Phone</title>" in html, "the badge, caracole, the library's name")
            assertTrue(page.assets.template("sync-tab.html") in html)
            // The page is the page of the data it carries, for these controls: nothing of the route's own in it.
            assertEquals(page.served(data, ServerControls(TestApp.CSRF, sync = true), AppConfig.PHONE), html)
        }
    }

    @Test
    fun `the page carries the server's controls as they are now`() {
        var controls = ServerControls(TestApp.CSRF)
        val mirror = mirrorOf(tmp.newFolder(), libraryPage(mirroredData(emptyList())))
        val test = TestApp(tmp.newFolder(), modules = { database ->
            listOf(PageRoutes(database, page, MirrorPageData(mirror), { controls }))
        }).also { opened.add(it) }
        val song = addSong(test.database, "estopa/tu-calorro", "Estopa", "Tu Calorro")
        fun server() = MirrorPageData.dataBlock(test.get("/").bytes)!!.getValue("server").jsonObject
        assertEquals(0, server().getValue("active").jsonPrimitive.int)
        controls = ServerControls(TestApp.CSRF, busy = setOf(song), active = 1)
        assertEquals(listOf(song), server().getValue("busy").jsonArray.map { it.jsonPrimitive.long })
        assertEquals(1, server().getValue("active").jsonPrimitive.int)
    }

    @Test
    fun `a HEAD is answered as its GET`() {
        val test = app()
        for (path in listOf("/", "/index.html", "/favicon.ico")) {
            val get = test.get(path)
            val head = test.handle(test.request("HEAD", path, mapOf("sec-fetch-site" to "same-origin")))
            assertEquals(get.status, head.status, path)
            assertEquals(headers(get), headers(head), path)
            if (path == "/favicon.ico") assertContentEquals(get.bytes, head.bytes)
        }
    }

    @Test
    fun `without the launch's cookie there is no page`() {
        val test = app()
        for (path in listOf("/", "/index.html", "/favicon.ico")) {
            val response = test.handle(TestApp.request("GET", path, emptyMap(), ByteArray(0), secret = null))
            assertEquals(403, response.status, path)
            assertEquals("Not this app's caracole.\n", response.text)
            assertFalse("<script" in response.text)
        }
    }

    @Test
    fun `the page names the library the App is configured with`() {
        val html = app(libraryName = "Dani's songs").get("/").text
        assertTrue("<title>Phone · caracole · Dani&#x27;s songs</title>" in html)
        assertTrue("<p class=\"libname\"><span class=\"name\">Dani&#x27;s songs</span>" in html)
    }

    @Test
    fun `the icon is caracole serve's, an SVG that may load and run nothing`() {
        val response = app().get("/favicon.ico")
        assertEquals(200, response.status)
        assertEquals(pythons("/favicon.ico"), headers(response))
        assertEquals(served.getValue("svg").jsonPrimitive.content, response.text)
    }
}
