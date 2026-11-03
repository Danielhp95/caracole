package io.github.danielhp95.caracole

import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import java.io.File
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith
import kotlin.test.assertFalse
import kotlin.test.assertTrue

/**
 * The phone's database is made whole once: a fresh one seeded under a name of its own, and given its name only
 * then; after, it is opened as it is. A fake database here, a file of the lines written to it: the real one needs
 * the bundled SQLite of a device (the integration step's).
 */
class PhoneDatabaseTest {
    @get:Rule val folder = TemporaryFolder()

    /** A database that is its file: what it was opened at, and what a seed wrote there. */
    private class Fake(val file: File) : AutoCloseable {
        init {
            file.parentFile?.mkdirs()
            if (!file.exists()) file.writeText("migrated\n")
        }

        var closed = false
        override fun close() {
            closed = true
        }
    }

    private val opened = mutableListOf<Fake>()
    private fun open(file: File) = Fake(file).also { opened.add(it) }

    @Test
    fun `a fresh database is seeded under a name of its own, then named, then opened`() {
        val file = File(folder.root, "files/caracole.sqlite")
        var seeded: File? = null
        val db = PhoneDatabase.open(file, ::open) { fresh ->
            assertFalse(file.exists(), "the database has no name of its own while it is seeded")
            fresh.file.appendText("seeded\n")
            seeded = fresh.file
        }
        assertEquals(File(folder.root, "files/caracole.sqlite.new"), seeded)
        assertEquals(file, db.file)
        assertEquals("migrated\nseeded\n", file.readText())
        assertFalse(seeded!!.exists())
        assertEquals(listOf(true, false), opened.map { it.closed }, "the seeded one closed before it is named")
    }

    @Test
    fun `a database there is opened as it is, never seeded again`() {
        val file = File(folder.root, "caracole.sqlite").apply { writeText("migrated\nseeded\nsongs\n") }
        val db = PhoneDatabase.open(file, ::open) { error("seeded again") }
        assertEquals(file, db.file)
        assertEquals("migrated\nseeded\nsongs\n", file.readText())
        assertEquals(1, opened.size)
    }

    @Test
    fun `a start cut short while seeding leaves no database, and the next start makes it again`() {
        val file = File(folder.root, "caracole.sqlite")
        assertFailsWith<IllegalStateException> {
            PhoneDatabase.open(file, ::open) { it.file.appendText("half\n"); error("killed") }
        }
        assertFalse(file.exists())
        assertTrue(opened.single().closed)
        // What it left, the half-seeded file and SQLite's own beside it, is no start for the next.
        File(folder.root, "caracole.sqlite.new-wal").writeText("stale")
        File(folder.root, "caracole.sqlite.new-shm").writeText("stale")
        PhoneDatabase.open(file, ::open) { it.file.appendText("seeded\n") }
        assertEquals("migrated\nseeded\n", file.readText())
        assertEquals(listOf("caracole.sqlite"), folder.root.list()!!.sorted())
    }
}
