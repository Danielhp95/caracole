package io.github.danielhp95.caracole.mirror

import org.junit.After
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import kotlin.test.assertContentEquals
import kotlin.test.assertEquals
import kotlin.test.assertIs
import kotlin.test.assertNull

/** What the app's PathHandler answers the WebView ([Mirror.respond]), and where a link goes ([Links.route]). */
class MirrorLookupTest {
    @get:Rule val folder = TemporaryFolder()

    private val server = FakeCaracole()
    private val mirror by lazy { Mirror(folder.newFolder("files")) }
    private val links by lazy { Links(mirror) }

    @After fun stop() = server.close()

    private val csp = "sandbox allow-scripts; default-src 'none'; script-src 'sha256-abc='"
    private val sheet = "<html>sheet</html>".toByteArray()
    private val pdf = "%PDF-1.7".toByteArray()

    private fun synced() {
        server.publish(
            mapOf(
                "index.html" to "<html>library</html>".toByteArray(),
                "Estopa/Tu calorro/sheet.html" to sheet,
                "Estopa/Tu calorro/sheet.pdf" to pdf,
                "Estopa/Tu calorro/guitar-1.gp5" to "FICHIER GUITAR PRO v5".toByteArray(),
            ),
            headers = mapOf("Estopa/Tu calorro/sheet.html" to mapOf("Content-Security-Policy" to csp, "Referrer-Policy" to "same-origin")),
        )
        SyncEngine(mirror).sync(server.address)
    }

    @Test
    fun `a page is answered with its blob, its type split, and the headers serve sends with it`() {
        synced()
        val response = mirror.respond("Estopa/Tu calorro/sheet.html")
        assertEquals(200, response.status)
        assertEquals("text/html", response.mimeType)
        assertEquals("utf-8", response.charset)
        assertEquals(mapOf("Content-Security-Policy" to csp, "Referrer-Policy" to "same-origin"), response.headers)
        assertContentEquals(sheet, response.file!!.readBytes())

        val file = mirror.respond("Estopa/Tu calorro/sheet.pdf")
        assertEquals("application/pdf", file.mimeType)
        assertNull(file.charset)
        assertEquals(emptyMap(), file.headers)
        assertContentEquals(pdf, file.file!!.readBytes())
    }

    @Test
    fun `anything the list doesn't name is a 404`() {
        assertEquals(Response.NOT_FOUND, mirror.respond("index.html"), "before any sync")
        synced()
        for (path in listOf("", "/index.html", "Estopa/Tu calorro", "estopa/tu calorro/sheet.html", "Estopa/Tu%20calorro/sheet.html",
            "Estopa/Tu calorro/sheet.html/", "../files/manifest.json", "blobs/" + FakeCaracole.sha256(sheet))) {
            assertEquals(Response.NOT_FOUND, mirror.respond(path), path)
        }
        mirror.blob(FakeCaracole.sha256(pdf)).delete()
        assertEquals(Response.NOT_FOUND, mirror.respond("Estopa/Tu calorro/sheet.pdf"), "a blob gone is no file")
    }

    @Test
    fun `the lookup reads the list a sync swaps in`() {
        synced()
        server.publish(mapOf("index.html" to "<html>library</html>".toByteArray(), "Other/Song/sheet.html" to sheet))
        SyncEngine(mirror).sync(server.address)
        assertEquals(Response.NOT_FOUND, mirror.respond("Estopa/Tu calorro/sheet.html"))
        assertEquals(200, mirror.respond("Other/Song/sheet.html").status)
    }

    @Test
    fun `a link goes to the WebView, another app, the browser, or nowhere`() {
        synced()
        val base = "https://appassets.androidplatform.net"
        assertEquals(Route.Page, links.route("$base/Estopa/Tu%20calorro/sheet.html#t=2&necks=0"))
        assertEquals(Route.Page, links.route("$base/index.html?x=1#prog=I-V-vi-IV"))
        val pdfRoute = assertIs<Route.File>(links.route("$base/Estopa/Tu%20calorro/sheet.pdf"))
        assertEquals("application/pdf", pdfRoute.served.entry.mimeType)
        assertEquals(Route.Missing, links.route("$base/Estopa/Tu%20calorro/sheet%20(auto).html"))

        // A page that takes itself for served links serve's own pages: its Guitar Pro file is in the mirror;
        // Export, the versions' forms and the requests page aren't.
        val guitar = assertIs<Route.File>(links.route("$base/guitar?file=Estopa%2FTu%20calorro%2Fguitar-1.gp5"))
        assertEquals("Estopa/Tu calorro/guitar-1.gp5", guitar.served.entry.path)
        assertEquals(Route.Missing, links.route("$base/guitar?file=Estopa%2FTu%20calorro%2Fguitar-2.gp5"))
        assertEquals(Route.ServerOnly, links.route("$base/export?sheet=Estopa%2FTu+calorro%2Fsheet.html&t=2"))
        assertEquals(Route.ServerOnly, links.route("$base/versions?sheet=x&do=keep"))
        assertEquals(Route.ServerOnly, links.route("$base/jobs?job=3#job-3"))

        assertEquals(Route.Browser("https://tabs.ultimate-guitar.com/tab/x"), links.route("https://tabs.ultimate-guitar.com/tab/x"))
        assertEquals(Route.Browser("http://192.168.1.20:8737/"), links.route("http://192.168.1.20:8737/"))
        assertEquals(Route.Browser("http://appassets.androidplatform.net/index.html"),
            links.route("http://appassets.androidplatform.net/index.html"), "the mirror is https alone")
        assertEquals(Route.Ignored, links.route("javascript:alert(1)"))
        assertEquals(Route.Ignored, links.route("intent://x#Intent;end"))
    }

    @Test
    fun `a path's address in the mirror is each part percent-encoded`() {
        assertEquals("https://appassets.androidplatform.net/Estopa/Tu%20calorro/sheet.html", Links.address("Estopa/Tu calorro/sheet.html"))
        assertEquals("https://appassets.androidplatform.net/%C3%91and%C3%BA/Canci%C3%B3n%20%231%3F/sheet%20%28auto%29.html",
            Links.address("Ñandú/Canción #1?/sheet (auto).html"))
    }
}
