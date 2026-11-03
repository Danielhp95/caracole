package io.github.danielhp95.caracole.mirror

import org.junit.After
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import kotlin.test.assertContentEquals
import kotlin.test.assertEquals
import kotlin.test.assertIs
import kotlin.test.assertNull

/** What the mirror answers for a path ([Mirror.respond]); where a link goes is LinksTest's. */
class MirrorLookupTest {
    @get:Rule val folder = TemporaryFolder()

    private val server = FakeCaracole()
    private val mirror by lazy { Mirror(folder.newFolder("files")) }

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
}
