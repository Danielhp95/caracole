package io.github.danielhp95.caracole.server.routes.sync

import io.github.danielhp95.caracole.mirror.Mirror
import io.github.danielhp95.caracole.server.page.json
import io.github.danielhp95.caracole.server.page.obj
import io.github.danielhp95.caracole.server.page.sha256
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import java.io.File
import kotlin.test.assertContentEquals
import kotlin.test.assertEquals
import kotlin.test.assertNotNull
import kotlin.test.assertNull

/** The pages the phone's export holds: the mirror's and its layers', each unit's at the digest the phone holds. */
class MirrorPagesTest {
    @get:Rule val tmp = TemporaryFolder()

    private val song = "song/estopa/tu-calorro"
    private val other = "song/oasis/wonderwall"
    private val d1 = "1".repeat(64)
    private val d2 = "2".repeat(64)

    private val library = "<html>the computer's library</html>".toByteArray()
    private val computersSheet = "<html>the computer's sheet</html>".toByteArray()
    private val computersOther = "<html>wonderwall</html>".toByteArray()
    private val filesLibrary = "<html>the file's library</html>".toByteArray()
    private val filesSheet = "<html>the file's sheet</html>".toByteArray()
    private val filesPdf = "%PDF the file's".toByteArray()

    private fun entry(path: String, bytes: ByteArray, unit: String? = null, digest: String? = null): JsonObject = obj(
        "path" to path, "url" to "/offline/" + path.replace(" ", "%20"), "size" to bytes.size, "sha256" to sha256(bytes),
        "type" to "text/html; charset=utf-8", "headers" to mapOf("Referrer-Policy" to "same-origin"),
        *(if (unit == null) arrayOf<Pair<String, Any?>>() else arrayOf<Pair<String, Any?>>("unit" to unit, "digest" to digest)),
    )

    private fun list(vararg files: JsonObject) = obj("format" to 1, "start" to "index.html", "files" to files.toList())

    /** The computer's library mirrored, as a sync leaves it, and a file's pages taken as a layer. */
    private fun mirror(): Mirror {
        val mirror = Mirror(tmp.newFolder("files"))
        mirror.blobs.mkdirs()
        for (bytes in listOf(library, computersSheet, computersOther)) File(mirror.blobs, sha256(bytes)).writeBytes(bytes)
        mirror.manifestFile.writeText(list(
            entry("index.html", library),
            entry("Estopa/Tu calorro/sheet.html", computersSheet, song, d1),
            entry("Oasis/Wonderwall/sheet.html", computersOther, other, d1),
            entry("style.css", library),
        ).toString())
        mirror.reload()
        val blobs = listOf(filesLibrary, filesSheet, filesPdf).associateBy { sha256(it) }
        mirror.takeLayer("0123456789abcdef", list(
            entry("index.html", filesLibrary),
            entry("Estopa/Tu calorro/sheet.html", filesSheet, song, d2),
            entry("Estopa/Tu calorro/sheet.pdf", filesPdf, song, d2),
        ).toString().toByteArray(), setOf(song)) { blobs[it]?.inputStream() }
        return mirror
    }

    private fun paths(listed: JsonObject?) =
        assertNotNull(listed).getValue("files").jsonArray.map { it.jsonObject.getValue("path").jsonPrimitive.content }

    @Test
    fun `each unit's pages at the digest the phone holds, the computer's first, then its layers'`() {
        val pages = MirrorPages(mirror())
        val computers = pages.manifest(mapOf(song to d1, other to d1))
        assertEquals(listOf("index.html", "Estopa/Tu calorro/sheet.html", "Oasis/Wonderwall/sheet.html"), paths(computers),
                     "the start page, then each unit's at its digest; no other page of no unit")
        assertEquals(json(mapOf("format" to 1, "start" to "index.html")), JsonObject(computers!! - "files"))
        assertEquals(entry("Estopa/Tu calorro/sheet.html", computersSheet, song, d1), computers.getValue("files").jsonArray[1])

        val taken = pages.manifest(mapOf(song to d2))
        assertEquals(listOf("index.html", "Estopa/Tu calorro/sheet.html", "Estopa/Tu calorro/sheet.pdf"), paths(taken),
                     "the pages taken from a file, where the computer's are of another digest")
        assertEquals(sha256(filesSheet), taken!!.getValue("files").jsonArray[1].jsonObject.getValue("sha256").jsonPrimitive.content)
        assertEquals(entry("index.html", library), taken.getValue("files").jsonArray[0], "the computer's library page")

        assertEquals(listOf("index.html"), paths(pages.manifest(mapOf(song to "3".repeat(64)))))
    }

    @Test
    fun `a page's bytes by its sha256, wherever the mirror holds them`() {
        val pages = MirrorPages(mirror())
        assertContentEquals(computersSheet, assertNotNull(pages.open(sha256(computersSheet))).use { it.readBytes() })
        assertContentEquals(filesPdf, assertNotNull(pages.open(sha256(filesPdf))).use { it.readBytes() })
        assertNull(pages.open(sha256("nowhere".toByteArray())))
        assertNull(pages.open("../manifest.json"))
    }

    @Test
    fun `with no start page there are no pages`() {
        assertNull(MirrorPages(null).manifest(mapOf(song to d1)))
        assertNull(MirrorPages(Mirror(tmp.newFolder("never-synced"))).manifest(mapOf(song to d1)))
        val mirror = mirror()
        File(mirror.blobs, sha256(library)).delete()
        assertEquals(sha256(filesLibrary), assertNotNull(MirrorPages(mirror).manifest(emptyMap())).getValue("files").jsonArray
            .single().jsonObject.getValue("sha256").jsonPrimitive.content, "the newest layer's start page, the computer's gone")
    }
}
