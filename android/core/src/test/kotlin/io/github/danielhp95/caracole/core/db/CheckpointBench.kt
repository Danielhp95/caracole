package io.github.danielhp95.caracole.core.db

import io.github.danielhp95.caracole.core.index.IndexTransfer
import io.github.danielhp95.caracole.core.testing.BigIndex
import io.github.danielhp95.caracole.core.testing.TestDb
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import java.io.File
import kotlin.test.assertEquals
import kotlin.test.assertTrue

/**
 * The WAL after an import of 200,000 ug_index rows (BigIndex), as Settings' Import merges it (IndexTransfer.merge on
 * the writer, then Database.checkpoint): what the merge left (its last writes restart the WAL, which the journal size
 * limit cuts down) and what the checkpoint left, each at most Database.JOURNAL_SIZE_LIMIT; each step's time printed
 * (Timings), for android/README.md's Performance notes. In the gated `bench` task.
 */
class CheckpointBench {
    @get:Rule val tmp = TemporaryFolder()

    @Test fun anImportsWalIsGivenBack() {
        val export = BigIndex(ROWS).export(File(tmp.newFolder(), "export.sqlite"))
        TestDb.fresh(tmp.newFolder()).use { database ->
            val wal = File(database.path.path + "-wal")
            database.writeBlocking { IndexTransfer.seedFresh(it) }
            Timings.enabled = true
            Timings.take()
            try {
                Timings.time("merge") {
                    database.writeBlocking { IndexTransfer.merge(it, export, "2026-11-03T12:00:00Z") }
                }
                val grown = wal.length()
                val done = database.checkpoint()
                val left = wal.length()
                println("CheckpointBench: $ROWS ug_index rows: the merge left a WAL of $grown bytes, " +
                            "the checkpoint $left ($done); ${Timings.take().joinToString(", ")}")
                // The merge's own last writes restart the WAL, which the limit cuts down already.
                assertTrue(grown <= Database.JOURNAL_SIZE_LIMIT, "the merge left a WAL of $grown bytes")
                assertTrue(left <= Database.JOURNAL_SIZE_LIMIT, "the checkpoint left $left bytes")
                val count = database.read { db -> db.one("SELECT COUNT(*) FROM ug_index") { it.long(0) } }
                assertEquals(ROWS.toLong(), count)
            } finally {
                Timings.enabled = false
            }
        }
    }

    companion object {
        const val ROWS = 200_000
    }
}
