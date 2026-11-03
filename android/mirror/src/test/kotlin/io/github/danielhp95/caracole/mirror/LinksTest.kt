package io.github.danielhp95.caracole.mirror

import org.junit.Test
import java.net.URI
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertTrue

/** Where a link the WebView is asked to follow goes ([Links.route]), and what it may load itself ([Links.loads]). */
class LinksTest {
    private val origin = "http://127.0.0.1:8738"

    /** The files of the library another app opens; anything else at the origin is the server's to answer. */
    private val files = setOf("Estopa/Tu calorro/sheet.pdf", "Estopa/Tu calorro/guitar-1.gp5", "Ñandú/Canción #1?/sheet.cho")
    private val links = Links(URI(origin)) { it in files }

    @Test
    fun `a page only at the server's exact origin, whatever its path, query or fragment`() {
        for (url in listOf("$origin/", origin, "$origin/index.html?x=1#prog=I-V-vi-IV",
            "$origin/Estopa/Tu%20calorro/sheet.html#t=2&necks=0", "$origin/#tab=sync",
            // The server's own pages answer on the phone too (a message page when they aren't on it yet), and so do
            // a path it holds no file at: never another app.
            "$origin/export?sheet=Estopa%2FTu+calorro%2Fsheet.html&t=2", "$origin/versions?sheet=x&do=keep",
            "$origin/Estopa/Tu%20calorro/sheet%20(auto).pdf", "HTTP://127.0.0.1:8738/index.html")) {
            assertEquals(Route.Page, links.route(url), url)
        }
    }

    @Test
    fun `a file at the origin goes to another app, by its path in the library`() {
        assertEquals(Route.File("Estopa/Tu calorro/sheet.pdf"), links.route("$origin/Estopa/Tu%20calorro/sheet.pdf"))
        assertEquals(Route.File("Ñandú/Canción #1?/sheet.cho"),
            links.route("$origin/%C3%91and%C3%BA/Canci%C3%B3n%20%231%3F/sheet.cho#x"))
        // caracole serve's Guitar Pro page, which a served viewer links each Guitar Pro file to: the file itself, when
        // the library has it; else the server's page, which says it isn't on the phone.
        assertEquals(Route.File("Estopa/Tu calorro/guitar-1.gp5"),
            links.route("$origin/guitar?file=Estopa%2FTu%20calorro%2Fguitar-1.gp5"))
        assertEquals(Route.File("Estopa/Tu calorro/guitar-1.gp5"),
            links.route("$origin/guitar?file=Estopa%2FTu+calorro%2Fguitar-1.gp5&track=2"))
        assertEquals(Route.Page, links.route("$origin/guitar?file=Estopa%2FTu%20calorro%2Fguitar-2.gp5"))
        assertEquals(Route.Page, links.route("$origin/guitar"))
    }

    @Test
    fun `any other origin is the browser's, every loopback port and the old asset loader's included`() {
        for (url in listOf("http://127.0.0.1:8737/", "http://127.0.0.1:8737/index.html", "http://127.0.0.1:8739/",
            "http://127.0.0.1/", "http://127.0.0.1:80/", "https://127.0.0.1:8738/", "http://localhost:8738/",
            "http://[::1]:8738/", "http://127.0.0.2:8738/", "http://192.168.1.20:8737/",
            "https://tabs.ultimate-guitar.com/tab/x", "https://appassets.androidplatform.net/index.html",
            "http://user@127.0.0.1:8738/")) {
            assertEquals(Route.Browser(url), links.route(url), url)
        }
    }

    @Test
    fun `another scheme, or no address at all, opens nothing`() {
        for (url in listOf("javascript:alert(1)", "intent://x#Intent;end", "file:///sdcard/x.pdf", "content://x/y",
            "data:text/html,hi", "http://127.0.0.1:8738/a b", "")) {
            assertEquals(Route.Ignored, links.route(url), url)
        }
    }

    @Test
    fun `a download at the origin is a file, whatever its path, and one elsewhere goes as a link does`() {
        assertEquals(Route.File("Estopa/Tu calorro/guitar-9.gp5"),
            links.route("$origin/Estopa/Tu%20calorro/guitar-9.gp5", download = true))
        assertEquals(Route.File("Estopa/Tu calorro/guitar-1.gp5"),
            links.route("$origin/guitar?file=Estopa%2FTu%20calorro%2Fguitar-1.gp5", download = true))
        assertEquals(Route.Browser("http://127.0.0.1:8737/x.gp5"), links.route("http://127.0.0.1:8737/x.gp5", download = true))
        assertEquals(Route.Ignored, links.route("$origin/", download = true), "the root is no file")
    }

    @Test
    fun `the WebView loads only the server's exact origin, and what is no request at all`() {
        assertTrue(links.loads("$origin/"))
        assertTrue(links.loads("$origin/Estopa/Tu%20calorro/sheet.html?x#y"))
        assertTrue(links.loads("data:image/svg+xml,%3Csvg%3E"), "a data: URL is the page's own bytes")
        assertTrue(links.loads("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg'> </svg>"), "one no URI parses too")
        for (url in listOf("http://127.0.0.1:8737/", "http://127.0.0.1:9000/x.js", "http://localhost:8738/",
            "https://127.0.0.1:8738/", "http://[::1]:8738/", "http://10.0.2.2:8737/api/offline",
            "https://appassets.androidplatform.net/index.html", "file:///android_asset/x", "content://x/y",
            "http://user@127.0.0.1:8738/", "not a url")) {
            assertFalse(links.loads(url), url)
        }
    }

    @Test
    fun `a path's target on the server is each part percent-encoded`() {
        assertEquals("/Estopa/Tu%20calorro/sheet.html", Links.target("Estopa/Tu calorro/sheet.html"))
        assertEquals("/%C3%91and%C3%BA/Canci%C3%B3n%20%231%3F/sheet%20%28auto%29.html",
            Links.target("Ñandú/Canción #1?/sheet (auto).html"))
        assertEquals("$origin/Estopa/Tu%20calorro/sheet.pdf", links.address("Estopa/Tu calorro/sheet.pdf"))
        assertEquals("$origin/", links.address(""))
    }
}
