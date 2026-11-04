package io.github.danielhp95.caracole.core.db

import io.github.danielhp95.caracole.core.sync.Take
import io.github.danielhp95.caracole.core.testing.TestDb
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertTrue

/**
 * The bundled SQLite's own error, told apart where :core catches it, on the JVM and on the device: on the JVM it is
 * androidx.sqlite.SQLiteException, which on Android is a typealias of android.database.SQLException, a class the JVM
 * build's catch can't name (CorpusOnDeviceTest's index and sync areas found it: a merge of no export escaped as a
 * raw SQLException, and a take's failure was a NoClassDefFoundError). android.database.SQLException here is the
 * test's stand-in.
 */
class SqliteErrorsTest {
    @get:Rule val tmp = TemporaryFolder()

    private val onTheDevice = android.database.SQLException("Error code: 1, message: no such table: theirs.caracole_export")

    @Test fun eitherClassIsTheDatabasesErrorAndNothingElseIs() {
        val onTheJvm = TestDb.fresh(tmp.root).use { database ->
            runCatching { database.read { db -> db.query("SELECT * FROM nowhere") { it.text(0) } } }.exceptionOrNull()!!
        }
        assertTrue(onTheJvm.isSqliteError(), "$onTheJvm")
        assertTrue(onTheDevice.isSqliteError())
        assertTrue(object : android.database.SQLException("Error code: 19, message: x") {}.isSqliteError(), "a subclass")
        assertFalse(IllegalStateException("Error code: 1, message: no").isSqliteError())
        assertFalse(java.io.IOException("disk").isSqliteError())
    }

    @Test fun aTakeTellsTheDatabasesFailureFromAUnitsRefusalOnTheDeviceToo() {
        assertTrue(Take.databaseFailed(android.database.SQLException("Error code: 10, message: disk I/O error")))
        assertFalse(Take.databaseFailed(android.database.SQLException("Error code: 275, message: CHECK constraint failed: x")))
        assertFalse(Take.databaseFailed(android.database.SQLException("Error code: 1811, message: datatype mismatch")))
        assertTrue(Take.databaseFailed(android.database.SQLException("no code at all")))
        assertFalse(Take.databaseFailed(IllegalStateException("Error code: 10, message: no")))
        assertEquals("no such table: theirs.caracole_export", Take.why(onTheDevice))
    }
}
