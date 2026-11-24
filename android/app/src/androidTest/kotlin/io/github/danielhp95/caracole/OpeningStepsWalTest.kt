package io.github.danielhp95.caracole

import androidx.sqlite.SQLiteConnection
import androidx.sqlite.driver.bundled.BundledSQLiteDriver
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith
import java.io.File

/**
 * The opening screen's "Updating your library…" against the SQLite the app bundles, on the device: a migration's
 * `PRAGMA user_version` that is still in the WAL (the process ended with no checkpoint, as Android ends one) is read
 * there, so nothing is said to update that SQLite won't migrate (OpeningSteps.userVersion; the JVM's OpeningStepsTest
 * holds the same over files the host's SQLite wrote).
 */
@RunWith(AndroidJUnit4::class)
class OpeningStepsWalTest {
    private val dir = File(InstrumentationRegistry.getInstrumentation().targetContext.cacheDir, "opening-wal-test")

    private fun SQLiteConnection.run(sql: String) = prepare(sql).use { it.step() }
    private fun SQLiteConnection.version() = prepare("PRAGMA user_version").use { it.step(); it.getLong(0).toInt() }

    @Test
    fun aMigrationStillInTheWalIsNoUpdate() {
        dir.deleteRecursively()
        dir.mkdirs()
        val file = File(dir, "caracole.sqlite")
        val connection = BundledSQLiteDriver().open(file.path)
        try {
            connection.run("PRAGMA journal_mode = WAL")
            connection.run("PRAGMA wal_autocheckpoint = 0")
            connection.run("CREATE TABLE t (x)")
            connection.run("PRAGMA user_version = 16")
            connection.run("PRAGMA wal_checkpoint(TRUNCATE)")  // the file's header: 16
            connection.run("PRAGMA user_version = 17")          // the migration's commit: in the WAL alone
            // What the next start's opening screen reads, the connection never closed (no checkpoint).
            assertEquals(17, connection.version())
            assertEquals(17, OpeningSteps.userVersion(file))
            assertFalse(OpeningSteps.updating(file, schema = 17))
            assertTrue(OpeningSteps.updating(file, schema = 18))
        } finally {
            connection.close()
            dir.deleteRecursively()
        }
    }
}
