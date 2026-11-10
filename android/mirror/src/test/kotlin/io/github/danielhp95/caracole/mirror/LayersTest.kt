package io.github.danielhp95.caracole.mirror

import io.github.danielhp95.caracole.mirror.FakeCaracole.Companion.sha256
import org.junit.After
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import java.io.ByteArrayInputStream
import java.io.File
import java.io.InputStream
import kotlin.test.assertContentEquals
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith
import kotlin.test.assertIs
import kotlin.test.assertNotNull
import kotlin.test.assertNull
import kotlin.test.assertTrue

/** A file's pages kept beside the computer's mirror, as a layer of it ([Mirror.takeLayer], [Mirror.layers]), and
 * what [Mirror.pageFor] serves of each. */
class LayersTest {
    @get:Rule val folder = TemporaryFolder()

    private val server = FakeCaracole()
    private val mirror by lazy { Mirror(folder.newFolder("files")) }

    @After fun stop() = server.close()

    private val song = "song/estopa/tu-calorro"
    private val other = "song/oasis/wonderwall"
    private val sheetPath = "Estopa/Tu calorro/sheet.html"
    private val onComputer = "d".repeat(64)
    private val inFile = "e".repeat(64)
    private val layerId = "0123456789abcdef"

    private val computersSheet = "<html>the computer's sheet</html>".toByteArray()
    private val filesSheet = "<html>the file's sheet</html>".toByteArray()
    private val filesPdf = "%PDF-1.7 the file's".toByteArray()
    private val filesLibrary = "<html>the file's library</html>".toByteArray()
    private val othersSheet = "<html>wonderwall</html>".toByteArray()

    /** The computer's library, mirrored: its library page and the song's sheet at the computer's digest. */
    private fun syncedWithComputer() {
        server.publish(
            mapOf("index.html" to "<html>library</html>".toByteArray(), sheetPath to computersSheet),
            units = mapOf(sheetPath to (song to onComputer)),
        )
        SyncEngine(mirror).sync(server.address)
    }

    /** A file's pages.json and the bytes of each page it lists, by path, each of the unit [units] names. */
    private class FilePages(val manifest: ByteArray, val blobs: Map<String, ByteArray>) {
        val asked = mutableListOf<String>()

        fun blob(sha256: String): InputStream? {
            asked.add(sha256)
            return blobs[sha256]?.let { ByteArrayInputStream(it) }
        }
    }

    private fun filePages(pages: Map<String, ByteArray>, units: Map<String, Pair<String, String?>>,
                          start: String = "index.html", lie: Map<String, ByteArray> = emptyMap()): FilePages {
        val entries = (listOf(start) + pages.keys.filter { it != start }).map { path ->
            val bytes = pages.getValue(path)
            Entry(path, FakeCaracole.urlOf(path), bytes.size.toLong(), sha256(bytes), FakeCaracole.typeOf(path), emptyMap(),
                  units[path]?.first, units[path]?.second)
        }
        val json = FakeCaracole.manifestJson(start, entries.map { FakeCaracole.entryJson(it) })
        val blobs = pages.values.associateBy { sha256(it) } + pages.filterKeys { it in lie }.map { (path, bytes) -> sha256(bytes) to lie.getValue(path) }
        return FilePages(json.toByteArray(), blobs)
    }

    /** The phone's own state as the gate reads it: each unit's digest the phone holds now. */
    private fun holding(vararg held: Pair<String, String>) = UnitGate { unit, digest ->
        val mine = held.toMap()[unit]
        if (mine == null || mine == digest) Gate.SERVE else Gate.CHANGED
    }

    private fun take(pages: FilePages, units: Set<String>, id: String = layerId) =
        mirror.takeLayer(id, pages.manifest, units, pages::blob)

    /** A layer's whole state: its list and every file in its folder. */
    private fun snapshot(dir: File): Map<String, String> =
        dir.walkTopDown().filter { it.isFile }.associate { it.relativeTo(dir).path to sha256(it.readBytes()) }

    @Test
    fun `a page the phone took from a file is served from its layer once the computer's is changed`() {
        syncedWithComputer()
        take(filePages(mapOf("index.html" to filesLibrary, sheetPath to filesSheet, "Estopa/Tu calorro/sheet.pdf" to filesPdf),
                       mapOf(sheetPath to (song to inFile), "Estopa/Tu calorro/sheet.pdf" to (song to inFile))), setOf(song))

        val taken = holding(song to inFile)
        val page = assertIs<Looked.Page>(mirror.pageFor(sheetPath, taken), "the computer's page is of another digest")
        assertContentEquals(filesSheet, page.file.readBytes())
        assertEquals(inFile, page.entry.digest)
        val pdf = assertIs<Looked.Page>(mirror.pageFor("Estopa/Tu calorro/sheet.pdf", taken), "a path the computer lacks")
        assertContentEquals(filesPdf, pdf.file.readBytes())

        val computers = assertIs<Looked.Page>(mirror.pageFor(sheetPath, holding(song to onComputer)),
                                              "the computer's page first, while the phone holds the song as it did")
        assertContentEquals(computersSheet, computers.file.readBytes())

        val changed = holding(song to "f".repeat(64))
        val gated = assertIs<Looked.Gated>(mirror.pageFor(sheetPath, changed), "neither is the song's now")
        assertEquals(onComputer, gated.entry.digest, "the computer's answer")
        assertEquals(Gate.CHANGED, gated.gate)
        val onlyInLayer = assertIs<Looked.Gated>(mirror.pageFor("Estopa/Tu calorro/sheet.pdf", changed))
        assertEquals(inFile, onlyInLayer.entry.digest, "where the computer has nothing, the layer's answer")

        assertEquals(Looked.Missing, mirror.pageFor("index.html.not", taken))
        val start = assertIs<Looked.Page>(mirror.pageFor("index.html", taken))
        assertContentEquals("<html>library</html>".toByteArray(), start.file.readBytes(), "a file of no unit is the computer's alone")
    }

    @Test
    fun `a phone that never synced with the computer serves the pages it took from a file`() {
        take(filePages(mapOf("index.html" to filesLibrary, sheetPath to filesSheet), mapOf(sheetPath to (song to inFile))), setOf(song))
        assertNull(mirror.manifest())
        val page = assertIs<Looked.Page>(mirror.pageFor(sheetPath, holding(song to inFile)))
        assertContentEquals(filesSheet, page.file.readBytes())
        assertEquals(Looked.Missing, mirror.pageFor("index.html", holding()), "a layer's start page is for its cards, never served")
    }

    @Test
    fun `a layer keeps only the pages of the units taken and the file's start page`() {
        val pages = filePages(
            mapOf("index.html" to filesLibrary, sheetPath to filesSheet, "Oasis/Wonderwall/sheet.html" to othersSheet,
                  "style.css" to "body {}".toByteArray()),
            mapOf(sheetPath to (song to inFile), "Oasis/Wonderwall/sheet.html" to (other to inFile)),
        )
        take(pages, setOf(song))

        val layer = mirror.layers().single()
        assertEquals(layerId, layer.id)
        val manifest = assertNotNull(layer.manifest())
        assertEquals("index.html", manifest.start)
        assertEquals(listOf("index.html", sheetPath), manifest.entries.map { it.path })
        assertEquals(setOf(sha256(filesLibrary), sha256(filesSheet)), layer.blobs.list()!!.toSet())
        assertEquals(setOf(sha256(filesLibrary), sha256(filesSheet)), pages.asked.toSet(), "no other page is read")
        assertContentEquals(filesLibrary, assertNotNull(layer.lookup("index.html")).file.readBytes())
        assertNull(layer.lookup("Oasis/Wonderwall/sheet.html"))
        assertEquals(Looked.Missing, mirror.pageFor("Oasis/Wonderwall/sheet.html", holding()))
    }

    @Test
    fun `a later file of the same caracole takes the pages of its units and its start page, and keeps the others'`() {
        take(filePages(mapOf("index.html" to filesLibrary, sheetPath to filesSheet), mapOf(sheetPath to (song to inFile))), setOf(song))
        val newer = "<html>the newer file's library</html>".toByteArray()
        val again = "<html>the song again</html>".toByteArray()
        take(filePages(mapOf("index.html" to newer, "Oasis/Wonderwall/sheet.html" to othersSheet, sheetPath to again),
                       mapOf("Oasis/Wonderwall/sheet.html" to (other to inFile), sheetPath to (song to "a".repeat(64)))),
             setOf(other))

        val layer = mirror.layers().single()
        val manifest = assertNotNull(layer.manifest())
        assertEquals(listOf("index.html", "Oasis/Wonderwall/sheet.html", sheetPath), manifest.entries.map { it.path })
        assertEquals(inFile, manifest.byPath.getValue(sheetPath).digest, "a unit it didn't take keeps the earlier file's page")
        assertEquals(setOf(sha256(newer), sha256(othersSheet), sha256(filesSheet)), layer.blobs.list()!!.toSet(),
                     "the blob no entry names is gone")
        assertContentEquals(filesSheet, assertIs<Looked.Page>(mirror.pageFor(sheetPath, holding(song to inFile))).file.readBytes())

        take(filePages(mapOf("index.html" to newer), emptyMap()), setOf(song))
        assertEquals(listOf("index.html", "Oasis/Wonderwall/sheet.html"), assertNotNull(mirror.layers().single().manifest()).entries.map { it.path },
                     "a unit taken again with no page keeps none of the earlier one's")
    }

    @Test
    fun `a blob whose bytes aren't its name leaves the layer as it was`() {
        take(filePages(mapOf("index.html" to filesLibrary, sheetPath to filesSheet), mapOf(sheetPath to (song to inFile))), setOf(song))
        val layerDir = mirror.layers().single().dir
        val before = snapshot(layerDir)
        val pdf = "Estopa/Tu calorro/sheet.pdf"

        val lying = filePages(mapOf("index.html" to "<html>new</html>".toByteArray(), sheetPath to "<html>new sheet</html>".toByteArray(),
                                    pdf to filesPdf),
                              mapOf(sheetPath to (song to "a".repeat(64)), pdf to (song to "a".repeat(64))),
                              lie = mapOf(pdf to "%PDF-1.7 something else".toByteArray()))
        val error = assertFailsWith<LayerError> { take(lying, setOf(song)) }
        assertTrue("sheet.pdf" in error.message!!, error.message)
        assertEquals(before, snapshot(layerDir), "its list and its blobs as they were, no temporary left")

        val missing = filePages(mapOf("index.html" to "<html>new</html>".toByteArray(), pdf to filesPdf), mapOf(pdf to (song to "a".repeat(64))))
        val gone = FilePages(missing.manifest, missing.blobs - sha256(filesPdf))
        assertFailsWith<LayerError> { take(gone, setOf(song)) }
        assertEquals(before, snapshot(layerDir), "a page the file lacks: as it was")

        val longer = filePages(mapOf("index.html" to filesLibrary, pdf to filesPdf), mapOf(pdf to (song to "a".repeat(64))),
                               lie = mapOf(pdf to filesPdf + "more".toByteArray()))
        assertFailsWith<LayerError> { take(longer, setOf(song)) }
        assertEquals(before, snapshot(layerDir), "a page longer than listed: as it was")

        assertFailsWith<LayerError> { mirror.takeLayer(layerId, "{\"format\": 1}".toByteArray(), setOf(song)) { null } }
        assertEquals(before, snapshot(layerDir), "a list it can't use: as it was")
        assertContentEquals(filesSheet, assertIs<Looked.Page>(mirror.pageFor(sheetPath, holding(song to inFile))).file.readBytes())
    }

    @Test
    fun `the computer's mirror sync never deletes a layer's blobs`() {
        syncedWithComputer()
        take(filePages(mapOf("index.html" to filesLibrary, sheetPath to filesSheet), mapOf(sheetPath to (song to inFile))), setOf(song))
        val layerDir = mirror.layers().single().dir
        val before = snapshot(layerDir)

        server.publish(mapOf("index.html" to "<html>library, later</html>".toByteArray()))
        SyncEngine(mirror).sync(server.address)
        assertEquals(before, snapshot(layerDir))
        assertEquals(setOf(sha256("<html>library, later</html>".toByteArray())), mirror.blobs.list()!!.toSet(),
                     "the computer's blobs are its list's alone")
        assertContentEquals(filesSheet, assertIs<Looked.Page>(mirror.pageFor(sheetPath, holding(song to inFile))).file.readBytes())
        assertTrue(mirror.storageBytes() >= filesSheet.size + filesLibrary.size, "the layers' bytes are the mirror's too")
    }

    @Test
    fun `the newest layer taken is asked first, and a layer's id is 16 hex`() {
        val older = "1111111111111111"
        val newer = "2222222222222222"
        val first = "<html>first</html>".toByteArray()
        val second = "<html>second</html>".toByteArray()
        take(filePages(mapOf("index.html" to filesLibrary, sheetPath to first), mapOf(sheetPath to (song to inFile))), setOf(song), newer)
        take(filePages(mapOf("index.html" to filesLibrary, sheetPath to second), mapOf(sheetPath to (song to inFile))), setOf(song), older)
        assertEquals(listOf(older, newer), mirror.layers().map { it.id }, "the newest taken first, whatever its id")
        assertContentEquals(second, assertIs<Looked.Page>(mirror.pageFor(sheetPath, holding(song to inFile))).file.readBytes())

        take(filePages(mapOf("index.html" to filesLibrary, sheetPath to first), mapOf(sheetPath to (song to inFile))), setOf(song), newer)
        assertEquals(listOf(newer, older), Mirror(mirror.dir).layers().map { it.id }, "as another mirror of the folder reads them")

        for (id in listOf("", "../escape", "0123456789ABCDEF", "0123456789abcde", "0123456789abcdef0")) {
            assertFailsWith<IllegalArgumentException>(id) { take(filePages(mapOf("index.html" to filesLibrary), emptyMap()), emptySet(), id) }
        }
        File(mirror.dir, "layers/not-a-layer").mkdirs()
        File(mirror.dir, "layers/3333333333333333").mkdirs()  // a folder with no list: none
        assertEquals(listOf(newer, older), Mirror(mirror.dir).layers().map { it.id })
    }
}
