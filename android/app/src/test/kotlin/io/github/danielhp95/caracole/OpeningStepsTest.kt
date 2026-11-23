package io.github.danielhp95.caracole

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
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

    @Test
    fun theStepsAreThreeInOrder() {
        assertEquals(listOf(OpeningSteps.Step.OPEN, OpeningSteps.Step.START, OpeningSteps.Step.DRAW),
                     OpeningSteps.Step.entries.toList())
        assertEquals(listOf(1, 2, 3), OpeningSteps.Step.entries.map { it.number })
    }
}
