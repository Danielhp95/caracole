package io.github.danielhp95.caracole.server.routes.sync

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
import kotlin.test.assertNotNull
import kotlin.test.assertNull
import kotlin.test.assertTrue

/** The phone's exports, each made for its one download (Exports). */
class ExportsTest {
    @get:Rule val tmp = TemporaryFolder()

    private val clock = AtomicLong(System.currentTimeMillis())
    private val cache by lazy { tmp.newFolder("cache") }
    private val exports by lazy { Exports(cache, clock::get) }
    private val bytes = "PK\u0003\u0004 a library".toByteArray()

    private fun files() = exports.folder.listFiles().orEmpty().map { it.name }.toSet()

    @Test
    fun `an export is taken once, and one taken that no server opened is swept`() {
        val made = exports.make("horde_logbook-03-11-26.caracole") { it.writeBytes(bytes) }
        assertTrue(Imports.ID.matches(made.id))
        assertEquals("horde_logbook-03-11-26.caracole" to bytes.size.toLong(), made.name to made.size)
        assertEquals(setOf("export-${made.id}.caracole"), files())
        assertEquals("rwx------", PosixFilePermissions.toString(Files.getPosixFilePermissions(exports.folder.toPath())))
        assertEquals("rw-------", PosixFilePermissions.toString(Files.getPosixFilePermissions(File(exports.folder, "export-${made.id}.caracole").toPath())))

        val (file, name) = assertNotNull(exports.take(made.id))
        assertEquals("horde_logbook-03-11-26.caracole", name)
        assertContentEquals(bytes, file.readBytes())
        assertNull(exports.take(made.id), "sent once")
        assertTrue(files().none { it.startsWith("export-") }, "no export of that name is left")

        clock.addAndGet(Exports.SENT)
        exports.sweep()
        assertEquals(1, files().size, "kept for the download that opens it")
        clock.addAndGet(1)
        exports.sweep()
        assertEquals(emptySet(), files(), "nothing left in the cache")
    }

    @Test
    fun `one export waits for its download at most, a new one taking the place of one never asked for`() {
        val first = exports.make("a.caracole") { it.writeBytes(bytes) }
        val second = exports.make("b.caracole") { it.writeBytes(bytes) }
        assertEquals(setOf("export-${second.id}.caracole"), files())
        assertNull(exports.take(first.id))
        assertNotNull(exports.take(second.id))
    }

    @Test
    fun `a phone's caracole starting clears every export an earlier one left`() {
        val taken = exports.make("b.caracole") { it.writeBytes(bytes) }
        exports.take(taken.id)
        val made = exports.make("a.caracole") { it.writeBytes(bytes) }
        File(exports.folder, ".export-0123456789abcdef.caracole.0123456789ab.part").writeBytes(bytes)
        File(exports.folder, "something else").writeBytes(bytes)
        Exports(cache, clock::get).clear()
        assertEquals(setOf("something else"), files())
        assertNull(exports.take(made.id))
    }

    @Test
    fun `one export is made at a time, and a writer that fails leaves nothing`() {
        exports.make("a.caracole") { file ->
            assertFailsWith<Exports.Busy> { exports.make("b.caracole") { it.writeBytes(bytes) } }
            file.writeBytes(bytes)
        }
        assertFailsWith<IllegalStateException> { exports.make("c.caracole") { it.writeBytes(bytes); error("cut short") } }
        assertEquals(1, files().size)
        assertEquals(Exports.BUSY, Exports.Busy().message)
    }

    @Test
    fun `an export never asked for, and a part a writer left, are deleted an hour after`() {
        val made = exports.make("a.caracole") { it.writeBytes(bytes) }
        val left = File(exports.folder, ".export-0123456789abcdef.caracole.0123456789ab.part").apply {
            writeBytes(bytes)
            setLastModified(clock.get())
        }
        File(exports.folder, "something else").writeBytes(bytes)
        clock.addAndGet(Exports.EXPIRES)
        exports.sweep()
        assertEquals(setOf("export-${made.id}.caracole", left.name, "something else"), files(), "an hour to the millisecond: kept")
        clock.addAndGet(1)
        exports.sweep()
        assertEquals(setOf("something else"), files())
        assertNull(exports.take(made.id))
        assertNull(exports.take("not an id"))
    }
}
