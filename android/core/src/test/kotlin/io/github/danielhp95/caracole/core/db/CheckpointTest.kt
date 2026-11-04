package io.github.danielhp95.caracole.core.db

import io.github.danielhp95.caracole.core.testing.BigIndex
import io.github.danielhp95.caracole.core.testing.TestDb
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import java.io.File
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import kotlin.concurrent.thread
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith
import kotlin.test.assertFalse
import kotlin.test.assertTrue

/** Database.checkpoint and the journal size limit: a big write's WAL given back, every reader reading after it (a
 * few thousand rows; CheckpointBench merges 200,000). */
class CheckpointTest {
    @get:Rule val tmp = TemporaryFolder()

    private fun wal(path: File) = File(path.path + "-wal")

    private fun fill(database: Database, rows: Int, from: Int = 1) = database.writeBlocking { db ->
        db.savepoint("rows") {
            for (i in from until from + rows) {
                db.execute("INSERT INTO ug_index (tab_id, artist_key, song_key, type, sitemap, first_seen, path) " +
                               "VALUES (?, ?, ?, 'chords', 'big', '2026-10-28T03:30:00Z', ?)",
                           i, "artist-${i % 97}", "song-${i / 3}", "artist-${i % 97}/song-${i / 3}-chords-$i")
            }
        }
    }

    private fun count(db: Db): Long = db.one("SELECT COUNT(*) FROM ug_index") { it.long(0)!! }!!

    @Test fun aCheckpointTruncatesTheWalAndEveryReaderStillReads() {
        TestDb.fresh(tmp.root).use { database ->
            fill(database, 5_000)
            assertTrue(wal(database.path).length() > Database.JOURNAL_SIZE_LIMIT / 64, "the rows are in the WAL")
            val done = database.checkpoint()
            assertFalse(done.busy)
            assertEquals(done.log, done.checkpointed, "every frame copied back")
            assertEquals(0L, wal(database.path).length())
            // Every reader of the pool at once, each through its own connection, reads every row.
            val ready = CountDownLatch(4)
            val counts = LongArray(4)
            val readers = List(4) { n ->
                thread {
                    database.read { db ->
                        ready.countDown()
                        ready.await()
                        counts[n] = count(db)
                    }
                }
            }
            readers.forEach { it.join() }
            assertEquals(List(4) { 5_000L }, counts.toList())
            fill(database, 10, from = 5_001)
            assertEquals(5_010L, database.read(::count))
        }
    }

    @Test fun aCheckpointWaitsForAReadThatHoldsItsSnapshotThenTruncates() {
        TestDb.fresh(tmp.root).use { database ->
            fill(database, 2_000)
            val reading = CountDownLatch(1)
            val release = CountDownLatch(1)
            var seen = 0L
            val reader = thread {
                database.read { db ->
                    db.raw.prepare("BEGIN").use { it.step() }
                    seen = count(db)  // its snapshot held until its block ends
                    reading.countDown()
                    release.await()
                }
            }
            reading.await()
            val checkpointed = CountDownLatch(1)
            val checkpoint = thread {
                database.checkpoint()
                checkpointed.countDown()
            }
            assertFalse(checkpointed.await(300, TimeUnit.MILLISECONDS), "the checkpoint waits for the read")
            release.countDown()
            reader.join()
            checkpoint.join()
            assertEquals(2_000L, seen)
            assertEquals(0L, wal(database.path).length())
            assertEquals(2_000L, database.read(::count))
        }
    }

    @Test fun aWalOverTheLimitIsCheckpointedAsTheDatabaseOpens() {
        val limit = 64L * 1024
        val path = File(tmp.newFolder(), "caracole.sqlite")
        val started = File(tmp.newFolder(), "caracole.sqlite")
        Database(path, journalSizeLimit = limit).use { database ->
            fill(database, 5_000)
            BigIndex.killedCopy(path, started)  // a phone killed with its database open
        }
        assertTrue(wal(started).length() > limit, "a WAL of ${wal(started).length()} bytes")
        Database(started, journalSizeLimit = limit).use { database ->
            assertEquals(0L, wal(started).length())
            assertEquals(5_000L, database.read(::count))
        }
    }

    @Test fun aWalUnderTheLimitIsLeftAsTheDatabaseOpens() {
        val path = File(tmp.newFolder(), "caracole.sqlite")
        val started = File(tmp.newFolder(), "caracole.sqlite")
        Database(path).use { database ->
            fill(database, 50)
            BigIndex.killedCopy(path, started)
        }
        val left = wal(started).length()
        assertTrue(left in 1..Database.JOURNAL_SIZE_LIMIT)
        Database(started).use { database ->
            assertEquals(left, wal(started).length())
            assertEquals(50L, database.read(::count))
        }
    }

    @Test fun everyConnectionKeepsTheJournalSizeLimit() {
        TestDb.fresh(tmp.root).use { database ->
            val limit = { db: Db -> db.one("PRAGMA journal_size_limit") { it.long(0) } }
            assertEquals(Database.JOURNAL_SIZE_LIMIT, database.writeBlocking(limit))
            val ready = CountDownLatch(4)
            val limits = LongArray(4)
            List(4) { n ->
                thread { database.read { db -> ready.countDown(); ready.await(); limits[n] = limit(db)!! } }
            }.forEach { it.join() }
            assertEquals(List(4) { Database.JOURNAL_SIZE_LIMIT }, limits.toList())
        }
    }

    @Test fun aCheckpointInsideAReadOrAWriteIsRefused() {
        TestDb.fresh(tmp.root).use { database ->
            assertFailsWith<IllegalStateException> { database.read { database.checkpoint() } }
            assertFailsWith<IllegalStateException> { database.writeBlocking { database.checkpoint() } }
            fill(database, 10)
            database.checkpoint()
            assertEquals(10L, database.read(::count))
        }
    }

    @Test fun aPassiveCheckpointCopiesTheWalBackAndTheNextWriteCutsItsFileToTheLimit() {
        val limit = 64L * 1024
        Database(File(tmp.root, "caracole.sqlite"), journalSizeLimit = limit).use { database ->
            fill(database, 5_000)
            val done = database.checkpoint(truncate = false)
            assertFalse(done.busy)
            assertEquals(done.log, done.checkpointed, "every frame copied back")
            assertTrue(wal(database.path).length() > limit, "a passive checkpoint leaves the file as it was")
            // The next write restarts the WAL, which the limit cuts down before its own page or two.
            database.writeBlocking { db -> db.kvSet("after", "the checkpoint") }
            assertTrue(wal(database.path).length() <= limit, "a WAL of ${wal(database.path).length()} bytes")
            assertEquals(5_000L, database.read(::count))
        }
    }
}
