package io.github.danielhp95.caracole.server.routes.sync

import kotlinx.serialization.json.Json
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import java.io.File
import java.nio.file.Files
import java.nio.file.attribute.PosixFilePermissions
import java.util.concurrent.atomic.AtomicLong
import kotlin.test.assertContentEquals
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith
import kotlin.test.assertFalse
import kotlin.test.assertTrue

/** A file to import staged part by part on the phone, as peer_import.py stages one (Imports). */
class ImportsTest {
    @get:Rule val tmp = TemporaryFolder()

    private val clock = AtomicLong(System.currentTimeMillis())
    private val stateDir by lazy { tmp.newFolder("state") }
    private val imports by lazy { Imports(stateDir, clock::get) }

    private fun refused(status: Int, words: String, block: () -> Unit) {
        val e = assertFailsWith<Imports.StagingError> { block() }
        assertEquals(words to status, e.message to e.status)
    }

    private fun mode(file: File) = PosixFilePermissions.toString(Files.getPosixFilePermissions(file.toPath()))

    @Test
    fun `a file sent in parts is whole once its last part has come`() {
        val id = imports.open(10, "horde_logbook-03-11-26.caracole")
        assertTrue(Imports.ID.matches(id))
        val folder = File(stateDir, "peer/import-$id")
        assertEquals(folder, imports.folderOf(id))
        assertEquals(setOf("file.caracole", "open.json"), folder.list()!!.toSet())
        assertEquals("rwx------" to "rw-------", mode(folder) to mode(File(folder, "file.caracole")))
        assertEquals("rw-------", mode(File(folder, "open.json")))
        val opened = Json.parseToJsonElement(File(folder, "open.json").readText()).jsonObject
        assertEquals(listOf("size", "name", "opened"), opened.keys.toList())
        assertEquals("10", opened.getValue("size").jsonPrimitive.content)

        assertEquals(4L, imports.addPart(id, 0, "PK\u0003\u0004".toByteArray()))
        refused(400, Imports.NOT_WHOLE) { imports.whole(id) }
        assertEquals(10L, imports.addPart(id, 4, "abcdef".toByteArray()))
        assertContentEquals("PK\u0003\u0004abcdef".toByteArray(), imports.whole(id).readBytes())
        assertEquals("horde_logbook-03-11-26.caracole", imports.openedName(id))
        imports.remove(id)
        assertFalse(folder.exists())
    }

    @Test
    fun `a part that isn't the next one, would pass the size or is past 8 MiB is refused, and what it had stays`() {
        val id = imports.open(10, "a.caracole")
        imports.addPart(id, 0, "1234".toByteArray())
        refused(400, Imports.NOT_NEXT) { imports.addPart(id, 0, "abcd".toByteArray()) }
        refused(400, Imports.NOT_NEXT) { imports.addPart(id, 5, "abcd".toByteArray()) }
        refused(400, Imports.NOT_NEXT) { imports.addPart(id, 4, "abcdefg".toByteArray()) }
        refused(400, "A part is 8 MiB at most: send it in smaller parts.") { imports.addPart(id, 4, ByteArray(Imports.PART_MAX + 1)) }
        refused(404, Imports.NO_SUCH) { imports.addPart("0".repeat(16), 0, "x".toByteArray()) }
        for (bad in listOf("", "../import-x", "0123456789ABCDEF", "0".repeat(17))) {
            refused(400, "Which import? Its id is 16 hex.") { imports.addPart(bad, 0, "x".toByteArray()) }
        }
        assertContentEquals("1234".toByteArray(), File(imports.folderOf(id), "file.caracole").readBytes())
    }

    @Test
    fun `one import at a time, and a size that isn't one or is past 8 GiB is refused before anything is made`() {
        refused(400, "How big is the file? Its size is a number of bytes.") { imports.open(0, "a") }
        refused(400, "How big is the file? Its size is a number of bytes.") { imports.open(null, "a") }
        refused(413, Imports.TOO_BIG) { imports.open(Imports.IMPORT_MAX + 1, "a") }
        refused(400, "What is the file called? Its name is text.") { imports.open(5, null) }
        assertFalse(File(stateDir, "peer").exists(), "nothing made")

        val id = imports.open(Imports.IMPORT_MAX, "x".repeat(300) + "🎸")
        refused(409, Imports.BUSY) { imports.open(5, "b") }
        assertEquals("x".repeat(255), imports.openedName(id), "a name kept to 255 characters")
    }

    @Test
    fun `an upload cut short is never compared, and is swept an hour after`() {
        val id = imports.open(10, "a.caracole")
        imports.addPart(id, 0, "1234".toByteArray())
        refused(400, Imports.NOT_WHOLE) { imports.whole(id) }

        clock.addAndGet(Imports.EXPIRES)
        assertEquals(emptyList(), imports.sweep(), "an hour to the millisecond: kept")
        clock.addAndGet(1)
        imports.held(id) { folder ->
            assertEquals(emptyList(), imports.sweep(), "held by the import that reads it")
            assertTrue(folder.isDirectory)
        }
        assertEquals(listOf(id), imports.sweep())
        assertFalse(imports.folderOf(id).exists())
        refused(404, Imports.GONE) { imports.held(id) {} }
        refused(404, Imports.NO_SUCH) { imports.whole(id) }

        val again = imports.open(10, "a.caracole")
        clock.addAndGet(Imports.EXPIRES - 1)
        imports.addPart(again, 0, "12".toByteArray())
        clock.addAndGet(2)
        assertEquals(emptyList(), imports.sweep(), "a part touches it")
        clock.addAndGet(Imports.EXPIRES)
        val other = imports.open(3, "b.caracole")
        assertFalse(imports.folderOf(again).exists(), "opening one sweeps those an hour has left first")
        assertTrue(imports.folderOf(other).isDirectory)
    }
}
