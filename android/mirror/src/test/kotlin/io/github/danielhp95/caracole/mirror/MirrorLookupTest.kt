package io.github.danielhp95.caracole.mirror

import org.junit.After
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import kotlin.test.assertContentEquals
import kotlin.test.assertEquals
import kotlin.test.assertIs
import kotlin.test.assertNull

/** What the app's PathHandler answers the WebView ([Mirror.respond]), what the phone's server finds of a path once
 * the phone's own state gates it ([Mirror.pageFor]), and where a link goes ([Links.route]). */
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

    private val song = "song/estopa/tu-calorro"
    private val digest = "d".repeat(64)

    /** The library of [synced], each file of the song naming its unit and digest as caracole serve lists them. */
    private fun syncedWithUnits() {
        val files = mapOf(
            "index.html" to "<html>library</html>".toByteArray(),
            "Estopa/Tu calorro/sheet.html" to sheet,
            "Estopa/Tu calorro/sheet.pdf" to pdf,
            "_songbooks/Campfire/songbook.html" to "<html>book</html>".toByteArray(),
        )
        server.publish(
            files,
            headers = mapOf("Estopa/Tu calorro/sheet.html" to mapOf("Content-Security-Policy" to csp)),
            units = mapOf(
                "Estopa/Tu calorro/sheet.html" to (song to digest),
                "Estopa/Tu calorro/sheet.pdf" to (song to digest),
                "_songbooks/Campfire/songbook.html" to ("songbook/campfire" to "e".repeat(64)),
            ),
        )
        SyncEngine(mirror).sync(server.address)
    }

    /** A gate that answers [answer] for every unit, and records what it was asked. */
    private class Asked(val answer: Gate) : UnitGate {
        val asked = mutableListOf<Pair<String, String?>>()
        override fun check(unit: String, digest: String?): Gate {
            asked.add(unit to digest)
            return answer
        }
    }

    @Test
    fun `a file of a unit the phone holds as the computer did is the page, its entry and its blob`() {
        syncedWithUnits()
        val gate = Asked(Gate.SERVE)
        val page = assertIs<Looked.Page>(mirror.pageFor("Estopa/Tu calorro/sheet.html", gate))
        assertEquals(listOf<Pair<String, String?>>(song to digest), gate.asked, "the gate is asked with the unit and digest listed")
        assertEquals(song, page.entry.unit)
        assertEquals(mapOf("Content-Security-Policy" to csp), page.entry.headers)
        assertContentEquals(sheet, page.file.readBytes())
    }

    @Test
    fun `a file of a unit the phone changed or removed is kept back, with what the gate said`() {
        syncedWithUnits()
        for (said in listOf(Gate.CHANGED, Gate.REMOVED)) {
            val gate = Asked(said)
            for (path in listOf("Estopa/Tu calorro/sheet.html", "Estopa/Tu calorro/sheet.pdf")) {
                val gated = assertIs<Looked.Gated>(mirror.pageFor(path, gate), "$said: $path")
                assertEquals(said, gated.gate)
                assertEquals(path, gated.entry.path)
            }
            val book = assertIs<Looked.Gated>(mirror.pageFor("_songbooks/Campfire/songbook.html", gate))
            assertEquals("songbook/campfire", book.entry.unit)
            assertEquals(listOf<Pair<String, String?>>(song to digest, song to digest, "songbook/campfire" to "e".repeat(64)), gate.asked)
        }
    }

    @Test
    fun `a file of no unit is served whatever the gate would say, and a path not listed is missing`() {
        syncedWithUnits()
        val gate = Asked(Gate.REMOVED)
        val page = assertIs<Looked.Page>(mirror.pageFor("index.html", gate))
        assertNull(page.entry.unit)
        assertEquals(Looked.Missing, mirror.pageFor("Estopa/Tu calorro/sheet (auto).html", gate))
        mirror.blob(FakeCaracole.sha256(pdf)).delete()
        assertEquals(Looked.Missing, mirror.pageFor("Estopa/Tu calorro/sheet.pdf", gate), "a blob gone is no file")
        assertEquals(emptyList<Pair<String, String?>>(), gate.asked, "the gate is asked only of a file there is, of a unit")
    }

    @Test
    fun `the gate reads the units of the list a sync swaps in`() {
        syncedWithUnits()
        server.publish(
            mapOf("index.html" to "<html>library</html>".toByteArray(), "Estopa/Tu calorro/sheet.html" to sheet),
            units = mapOf("Estopa/Tu calorro/sheet.html" to (song to "f".repeat(64))),
        )
        SyncEngine(mirror).sync(server.address)
        val gate = Asked(Gate.SERVE)
        assertIs<Looked.Page>(mirror.pageFor("Estopa/Tu calorro/sheet.html", gate))
        assertEquals(listOf<Pair<String, String?>>(song to "f".repeat(64)), gate.asked)
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
