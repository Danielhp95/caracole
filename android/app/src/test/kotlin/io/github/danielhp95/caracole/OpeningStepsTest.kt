package io.github.danielhp95.caracole

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import java.io.File

class OpeningStepsTest {
    @get:Rule val folder = TemporaryFolder()

    /** A file with SQLite's header and [version] as its user_version (bytes 60–63, big-endian). */
    private fun database(version: Int): File = folder.newFile().apply {
        val bytes = ByteArray(4096)
        "SQLite format 3\u0000".toByteArray(Charsets.US_ASCII).copyInto(bytes)
        for (i in 0 until 4) bytes[60 + i] = (version ushr (24 - 8 * i)).toByte()
        writeBytes(bytes)
    }

    @Test
    fun aLibraryAtAnOlderSchemaIsUpdatedFirst() {
        assertTrue(OpeningSteps.updating(database(16), schema = 17))
        assertTrue(OpeningSteps.updating(database(1), schema = 17))
    }

    @Test
    fun aCurrentNewOrMissingLibraryIsOpenedAsEver() {
        assertFalse(OpeningSteps.updating(database(17), schema = 17))
        assertFalse(OpeningSteps.updating(database(0), schema = 17))  // made, not yet migrated: a first start
        assertFalse(OpeningSteps.updating(File(folder.root, "none.sqlite"), schema = 17))
        assertFalse(OpeningSteps.updating(folder.newFile().apply { writeText("not a database") }, schema = 17))
    }

    /**
     * A database and its WAL as SQLite 3.53 left them, the process killed before any checkpoint (copied while its
     * connection was open), from test resources `opening/`:
     *
     * - `migrated`: user_version 16 checkpointed into the file, then `PRAGMA user_version = 17` committed into the WAL
     *   alone, as an update's migration leaves it (`PRAGMA journal_mode = WAL; PRAGMA wal_autocheckpoint = 0; CREATE
     *   TABLE t(x); PRAGMA user_version = 16; PRAGMA wal_checkpoint(TRUNCATE); PRAGMA user_version = 17`);
     * - `restarted`: frames of 5 then 17 checkpointed into the file (17), then the WAL restarted by `PRAGMA
     *   user_version = 16`, its first frame overwritten with new salts and the old ones after it, stale (`… CREATE
     *   TABLE t(x); PRAGMA user_version = 5; PRAGMA user_version = 17; PRAGMA wal_checkpoint(PASSIVE); PRAGMA
     *   user_version = 16`): SQLite reads 16.
     */
    private fun withWal(name: String, wal: (ByteArray) -> ByteArray = { it }): File {
        val dir = folder.newFolder()
        val file = File(dir, "caracole.sqlite")
        file.writeBytes(resource("$name.sqlite"))
        File(dir, "caracole.sqlite-wal").writeBytes(wal(resource("$name.sqlite-wal")))
        return file
    }

    private fun resource(name: String): ByteArray =
        javaClass.getResourceAsStream("/opening/$name")!!.use { it.readBytes() }

    @Test
    fun aMigrationTheWalHoldsIsNoUpdate() {
        // The file's header says 16, but SQLite reads the WAL's 17: nothing to migrate, "Opening your library…".
        assertEquals(17, OpeningSteps.userVersion(withWal("migrated")))
        assertFalse(OpeningSteps.updating(withWal("migrated"), schema = 17))
        assertTrue(OpeningSteps.updating(withWal("migrated"), schema = 18))
    }

    @Test
    fun aRestartedWalIsReadByItsSaltsNeverItsStaleFrames() {
        // The file's header says 17 and the stale frames after the first say 17; SQLite reads the restarted one's 16.
        assertEquals(16, OpeningSteps.userVersion(withWal("restarted")))
        assertTrue(OpeningSteps.updating(withWal("restarted"), schema = 17))
    }

    @Test
    fun aFrameCutShortOrWrongIsNoCommit() {
        // The commit's frame cut short, or a byte of it changed (its checksum then fails): not committed, the file's 16.
        assertEquals(16, OpeningSteps.userVersion(withWal("migrated") { it.copyOf(it.size - 100) }))
        assertEquals(16, OpeningSteps.userVersion(withWal("migrated") { it.copyOf().also { b -> b[32 + 24 + 200]++ } }))
        // A WAL whose own header is wrong, or that is no WAL: none, the file's.
        assertEquals(16, OpeningSteps.userVersion(withWal("migrated") { it.copyOf().also { b -> b[12]++ } }))
        assertEquals(16, OpeningSteps.userVersion(withWal("migrated") { ByteArray(4096) { 7 } }))
        assertEquals(16, OpeningSteps.userVersion(withWal("migrated") { ByteArray(0) }))
    }

    @Test
    fun aWalTooLargeToReadAtTheStartSaysNoUpdate() {
        // A WAL past what the opening reads (a big write killed mid-way): it can't say, so it opens as ever.
        val big = withWal("migrated") { it + ByteArray(OpeningSteps.MOST_WAL.toInt()) }
        assertNull(OpeningSteps.userVersion(big))
        assertFalse(OpeningSteps.updating(big, schema = 18))
    }

    @Test
    fun theStepsAreThreeInOrder() {
        assertEquals(listOf(OpeningSteps.Step.OPEN, OpeningSteps.Step.START, OpeningSteps.Step.DRAW),
                     OpeningSteps.Step.entries.toList())
        assertEquals(listOf(1, 2, 3), OpeningSteps.Step.entries.map { it.number })
    }
}
