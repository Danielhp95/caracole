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

    private val digest = "d".repeat(64)

    private fun entry(path: String, url: String = "/x", size: Long = 3, sha256: String = sha,
                      type: String = "text/html; charset=utf-8", headers: Map<String, String> = emptyMap(),
                      unit: String? = null, digest: String? = null) =
        Entry(path, url, size, sha256, type, headers, unit, digest)

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
    fun `a file names the unit it is of and the unit's digest, the library page neither`() {
        val text = manifestJson(
            "index.html",
            listOf(
                entryJson(entry("index.html", "/offline/index.html")),
                entryJson(entry("Estopa/Tu calorro/sheet.html", unit = "song/estopa/tu-calorro", digest = digest)),
                entryJson(entry("_songbooks/Campfire/songbook.pdf", type = "application/pdf",
                                unit = "songbook/campfire", digest = "e".repeat(64))),
                entryJson(entry("Estopa/Tu calorro/sheet.pdf", type = "application/pdf", unit = "song/estopa/tu-calorro")),
            ),
        )
        val manifest = parse(text)
        assertEquals(emptyList(), manifest.skipped)
        val page = manifest.byPath.getValue("index.html")
        assertNull(page.unit)
        assertNull(page.digest)
        val sheet = manifest.byPath.getValue("Estopa/Tu calorro/sheet.html")
        assertEquals("song/estopa/tu-calorro" to digest, sheet.unit to sheet.digest)
        val book = manifest.byPath.getValue("_songbooks/Campfire/songbook.pdf")
        assertEquals("songbook/campfire" to "e".repeat(64), book.unit to book.digest)
        val pdf = manifest.byPath.getValue("Estopa/Tu calorro/sheet.pdf")
        assertEquals("song/estopa/tu-calorro" to null, pdf.unit to pdf.digest, "a unit whose digest wasn't given")
    }

    @Test
    fun `a manifest of format 1's fields alone still reads, every file of no unit`() {
        // As a caracole serve from before the units lists it: the same format, and no unit or digest anywhere.
        val text = """{"format": 1, "start": "index.html", "files": [
            {"path": "index.html", "url": "/offline/index.html", "size": 3, "sha256": "$sha", "type": "text/html; charset=utf-8", "headers": {}},
            {"path": "Estopa/Tu calorro/sheet.pdf", "url": "/Estopa/Tu%20calorro/sheet.pdf", "size": 3, "sha256": "$sha", "type": "application/pdf"}]}"""
        val manifest = parse(text)
        assertEquals(listOf("index.html", "Estopa/Tu calorro/sheet.pdf"), manifest.entries.map { it.path })
        assertEquals(emptyList(), manifest.skipped)
        assertTrue(manifest.entries.all { it.unit == null && it.digest == null })
    }

    @Test
    fun `a unit or a digest that breaks the contract skips its file`() {
        val good = entryJson(entry("index.html"))
        val bad = listOf(
            entry("u1.pdf", unit = "", digest = digest), entry("u2.pdf", unit = "song", digest = digest),
            entry("u3.pdf", unit = "/estopa", digest = digest), entry("u4.pdf", unit = "song/", digest = digest),
            entry("u5.pdf", unit = "song/a\nb", digest = digest),
            entry("d1.pdf", unit = "song/a/b", digest = "D".repeat(64)), entry("d2.pdf", unit = "song/a/b", digest = "abc"),
            entry("d3.pdf", digest = digest),
        ).map { entryJson(it) }
        val odd = listOf(
            """{"path": "o1.pdf", "url": "/o", "size": 1, "sha256": "$sha", "type": "application/pdf", "unit": 42}""",
            """{"path": "o2.pdf", "url": "/o", "size": 1, "sha256": "$sha", "type": "application/pdf", "unit": "song/a/b", "digest": 7}""",
        )
        val nulls = """{"path": "n.pdf", "url": "/n", "size": 1, "sha256": "$sha", "type": "application/pdf", "unit": null, "digest": null}"""
        val manifest = parse(manifestJson("index.html", listOf(good) + bad + odd + nulls))
        assertEquals(listOf("index.html", "n.pdf"), manifest.entries.map { it.path }, "null is none")
        assertEquals(bad.size + odd.size, manifest.skipped.size, manifest.skipped.joinToString("\n"))
        assertTrue(manifest.skipped.any { "d3.pdf" in it && "digest" in it }, manifest.skipped.joinToString("\n"))
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
