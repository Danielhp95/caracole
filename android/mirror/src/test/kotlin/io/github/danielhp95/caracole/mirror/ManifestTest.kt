package io.github.danielhp95.caracole.mirror

import io.github.danielhp95.caracole.mirror.FakeCaracole.Companion.entryJson
import io.github.danielhp95.caracole.mirror.FakeCaracole.Companion.manifestJson
import io.github.danielhp95.caracole.mirror.FakeCaracole.Companion.quote
import org.junit.Test
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith
import kotlin.test.assertNull
import kotlin.test.assertTrue

class ManifestTest {
    private val address = ServerAddress.parse("192.168.1.20:8737")
    private val sha = "a".repeat(64)

    private fun entry(path: String, url: String = "/x", size: Long = 3, sha256: String = sha,
                      type: String = "text/html; charset=utf-8", headers: Map<String, String> = emptyMap()) =
        Entry(path, url, size, sha256, type, headers)

    private fun parse(text: String) = Manifest.parse(text.toByteArray(), address)

    @Test
    fun `reads the contract's list, the start page first`() {
        val csp = "sandbox allow-scripts; default-src 'none'; script-src 'sha256-abc='"
        val text = manifestJson(
            "index.html",
            listOf(
                entryJson(entry("index.html", "/offline/index.html", 81234, headers = mapOf("Referrer-Policy" to "same-origin"))),
                entryJson(entry("Estopa/Tu calorro/sheet.html", "/Estopa/Tu%20calorro/sheet.html", 151002,
                    headers = mapOf("Content-Security-Policy" to csp, "Set-Cookie" to "no=1"))),
                entryJson(entry("Estopa/Tu calorro/sheet.pdf", "/Estopa/Tu%20calorro/sheet.pdf", 40211, type = "application/pdf")),
            ),
        )
        val manifest = parse(text)
        assertEquals("index.html", manifest.start)
        assertEquals(listOf("index.html", "Estopa/Tu calorro/sheet.html", "Estopa/Tu calorro/sheet.pdf"), manifest.entries.map { it.path })
        assertEquals(emptyList(), manifest.skipped)
        assertEquals(81234L + 151002 + 40211, manifest.bytes)

        val sheet = manifest.byPath.getValue("Estopa/Tu calorro/sheet.html")
        assertEquals("/Estopa/Tu%20calorro/sheet.html", sheet.url)
        assertEquals(mapOf("Content-Security-Policy" to csp), sheet.headers, "a header the contract doesn't name is ignored")
        assertEquals("text/html", sheet.mimeType)
        assertEquals("utf-8", sheet.charset)
        assertTrue(sheet.isPage)

        val pdf = manifest.byPath.getValue("Estopa/Tu calorro/sheet.pdf")
        assertEquals("application/pdf", pdf.mimeType)
        assertNull(pdf.charset)
        assertEquals("sheet.pdf", pdf.name)
    }

    @Test
    fun `an answer that isn't caracole's list is no caracole`() {
        for (text in listOf("<html>hello</html>", "[1, 2]", """{"files": []}""", """{"format": "1"}""", "")) {
            assertFailsWith<SyncError.NotCaracole>(text) { parse(text) }
        }
        assertFailsWith<SyncError.NotCaracole> { Manifest.parse(byteArrayOf(0xff.toByte(), 0xfe.toByte()), address) }
    }

    @Test
    fun `another format is a caracole newer than the app`() {
        val newer = assertFailsWith<SyncError.NewerFormat> { parse(manifestJson("index.html", emptyList(), format = "2")) }
        assertTrue("newer than the app" in newer.message!!, newer.message)
    }

    @Test
    fun `the start page must be among the files`() {
        assertFailsWith<SyncError.BadManifest> {
            parse(manifestJson("index.html", listOf(entryJson(entry("other.html")))))
        }
    }

    @Test
    fun `an entry that breaks the contract is skipped and reported, the others kept`() {
        val bad = listOf(
            entry(""), entry("/abs.html"), entry("a/../b.html"), entry("./a.html"), entry("a/./b.html"),
            entry("a\\b.html"), entry("a\u0000b.html"), entry("a//b.html"), entry("a/"),
            entry("u1.pdf", url = "http://evil.example/x"), entry("u2.pdf", url = "//evil.example/x"),
            entry("u3.pdf", url = "relative/x"), entry("u4.pdf", url = "/with space"), entry("u5.pdf", url = "/x#frag"),
            entry("s1.pdf", sha256 = "A".repeat(64)), entry("s2.pdf", sha256 = "abc"),
            entry("n.pdf", size = -1),
            entry("t.pdf", type = "pdf"),
            entry("h.html", headers = mapOf("Content-Security-Policy" to "sandbox\r\nSet-Cookie: x=1")),
        ).map { entryJson(it) }
        val odd = listOf(
            "42",
            """{"path": "nourl.pdf", "size": 1, "sha256": "$sha", "type": "application/pdf"}""",
            """{"path": "frac.pdf", "url": "/f", "size": 1.5, "sha256": "$sha", "type": "application/pdf"}""",
            """{"path": "hdr.pdf", "url": "/h", "size": 1, "sha256": "$sha", "type": "application/pdf", "headers": []}""",
        )
        val good = listOf(entryJson(entry("index.html")), entryJson(entry("Ñandú/日本/sheet.pdf", url = "/%C3%91and%C3%BA/x", type = "application/pdf")))
        val duplicate = entryJson(entry("index.html", url = "/other"))
        val manifest = parse(manifestJson("index.html", good + bad + odd + duplicate))
        assertEquals(listOf("index.html", "Ñandú/日本/sheet.pdf"), manifest.entries.map { it.path })
        assertEquals("/x", manifest.byPath.getValue("index.html").url, "the first of a path listed twice is kept")
        assertEquals(bad.size + odd.size + 1, manifest.skipped.size, manifest.skipped.joinToString("\n"))
        assertTrue(manifest.skipped.last().contains("listed twice"))
    }

    @Test
    fun `json escapes are read`() {
        val text = """{"format": 1, "start": "año\/x.html", "files": [{"path": "año/x.html", "url": "/a", "size": 0,
            "sha256": ${quote(sha)}, "type": "text/html", "headers": {"content-security-policy": "sandbox"}}]}"""
        val manifest = parse(text)
        assertEquals("año/x.html", manifest.start)
        assertEquals(mapOf("Content-Security-Policy" to "sandbox"), manifest.entries.single().headers)
    }

    @Test
    fun `a content type splits as the WebView takes it`() {
        assertEquals("text/html", ContentType.mimeType("Text/HTML; charset=utf-8"))
        assertEquals("utf-8", ContentType.charset("text/html; charset=utf-8"))
        assertEquals("UTF-8", ContentType.charset("text/plain;charset=\"UTF-8\""))
        assertNull(ContentType.charset("application/pdf"))
        assertEquals("application/pdf", ContentType.mimeType("application/pdf"))
    }
}
