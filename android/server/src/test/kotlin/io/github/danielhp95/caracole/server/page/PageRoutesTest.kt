package io.github.danielhp95.caracole.server.page

import io.github.danielhp95.caracole.core.db.Database
import io.github.danielhp95.caracole.core.testing.TestDb
import io.github.danielhp95.caracole.server.http.Body
import io.github.danielhp95.caracole.server.http.Request
import io.github.danielhp95.caracole.server.http.Response
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import kotlinx.serialization.json.long
import org.junit.After
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import kotlin.test.assertEquals
import kotlin.test.assertTrue

/** GET /, /index.html and /favicon.ico, each route's answer as the router gets it (the router's own checks and
 * headers are server-shell's: RoutingTest). */
class PageRoutesTest {
    @get:Rule val tmp = TemporaryFolder()

    private val database: Database by lazy { TestDb.fresh(tmp.newFolder("db")) }

    @After fun close() = database.close()

    private val page = LibraryPage(LibraryAssets.load())

    private fun routes(controls: ServerControls = ServerControls("tok", sync = true)): PageRoutes {
        val mirror = mirrorOf(tmp.newFolder(), libraryPage(mirroredData(listOf(
            mirroredCard(10, "estopa/tu-calorro", "Estopa", "Tu Calorro"), mirroredCard(11, "oasis/wonderwall", "Oasis", "Wonderwall")))))
        return PageRoutes(database, page, MirrorPageData(mirror)) { controls }
    }

    private fun get(routes: PageRoutes, path: String): Response =
        routes.routes.single { it.method == "GET" && it.path == path }.get!!.answer(Request("GET", path, mapOf("host" to "127.0.0.1"), ByteArray(0)))

    private fun text(response: Response) = String((response.body as Body.Bytes).bytes)

    private fun header(response: Response, name: String) = response.headers.single { it.first == name }.second

    @Test
    fun `the routes are the page's three`() {
        assertEquals(listOf("GET /", "GET /index.html", "GET /favicon.ico"), routes().routes.map { "${it.method} ${it.path}" })
        assertTrue(routes().routes.all { it.doc.isNotEmpty() && !it.scriptOnly && !it.under })
    }

    @Test
    fun `the library page is the page of the phone's data, served with the server's controls`() {
        waitingOnServerShell()
        val calorro = addSong(database, "estopa/tu-calorro", "Estopa", "Tu Calorro")
        val controls = ServerControls("tok", busy = setOf(calorro), active = 1, sync = true)
        val routes = routes(controls)
        for (path in listOf("/", "/index.html")) {
            val response = get(routes, path)
            assertEquals(200, response.status)
            assertEquals("text/html; charset=utf-8", header(response, "Content-Type"))
            assertEquals("frame-ancestors 'none'", header(response, "Content-Security-Policy"))
            val html = text(response)
            val data = MirrorPageData.dataBlock(html.toByteArray())!!
            assertEquals(listOf(calorro, -1L), data.getValue("songs").jsonArray.map { it.jsonObject.getValue("id").jsonPrimitive.long })
            assertEquals("tok", data.getValue("server").jsonObject.getValue("csrf").jsonPrimitive.content)
            val built = database.read { db -> routes.data.data(db, data.getValue("generated").jsonPrimitive.content) }
            assertEquals(page.served(page.withServer(built, controls), controls, PageRoutes.LIBRARY_NAME), html)
            assertTrue(page.assets.template("sync-tab.html") in html)
        }
    }

    @Test
    fun `the icon is the page's mark, an SVG that may load and run nothing`() {
        waitingOnServerShell()
        val response = get(routes(), "/favicon.ico")
        assertEquals(200, response.status)
        assertEquals("image/svg+xml", header(response, "Content-Type"))
        assertEquals("default-src 'none'; frame-ancestors 'none'", header(response, "Content-Security-Policy"))
        assertEquals(PageIcons.svg, text(response))
        assertTrue(text(response).startsWith("<svg"))
    }
}
