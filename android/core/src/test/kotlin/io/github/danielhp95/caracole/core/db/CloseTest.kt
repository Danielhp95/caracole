package io.github.danielhp95.caracole.core.db

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
import kotlin.test.assertNull
import kotlin.test.assertTrue

/**
 * Database.close while a block still uses a connection (the start's warm-up, a test that closes its database at once,
 * Caracole.start's failure): no connection is closed while lent (the bundled SQLite is THREADSAFE=2, so that would be
 * undefined behaviour, a native crash at worst); each closes as its block ends, and whatever comes after is refused.
 */
class CloseTest {
    @get:Rule val tmp = TemporaryFolder()

    private fun count(db: Db): Long = db.one("SELECT COUNT(*) FROM kv") { it.long(0)!! }!!

    @Test fun aReadThatRunsAsTheDatabaseClosesEndsOnItsOwnConnection() {
        val database = TestDb.fresh(tmp.root)
        database.writeBlocking { it.kvSet("a", "1") }
        val reading = CountDownLatch(1)
        val closed = CountDownLatch(1)
        var seen: Long? = null
        var failed: Throwable? = null
        val reader = thread {
            try {
                database.read { db ->
                    reading.countDown()
                    closed.await()
                    seen = count(db)  // its connection still open: it closes once this block ends
                }
            } catch (e: Throwable) {
                failed = e
            }
        }
        reading.await()
        database.close()
        closed.countDown()
        reader.join()
        assertNull(failed)
        assertTrue(seen!! >= 1)
        assertFailsWith<IllegalStateException> { database.read(::count) }
        assertFailsWith<IllegalStateException> { database.writeBlocking { it.kvSet("b", "2") } }
        assertFailsWith<IllegalStateException> { database.checkpoint() }
        database.close()  // a second close does nothing
    }

    @Test fun aWriteThatRunsAsTheDatabaseClosesEndsAndCommits() {
        val path = File(tmp.root, "caracole.sqlite")
        val database = Database(path)
        val writing = CountDownLatch(1)
        val closed = CountDownLatch(1)
        val writer = thread {
            database.writeBlocking { db ->
                writing.countDown()
                closed.await()
                db.kvSet("written", "after the close")
            }
        }
        writing.await()
        database.close()
        closed.countDown()
        writer.join()
        assertFailsWith<IllegalStateException> { database.writeBlocking { it.kvSet("b", "2") } }
        Database(path).use { again -> assertEquals("after the close", again.read { it.kvGet("written") }) }
    }

    @Test fun aReadWaitingForAReaderWhenTheDatabaseClosesIsRefused() {
        val database = Database(File(tmp.root, "caracole.sqlite"), readers = 1)
        val holding = CountDownLatch(1)
        val release = CountDownLatch(1)
        val holder = thread { database.read { holding.countDown(); release.await() } }
        holding.await()
        var refused: Throwable? = null
        val waiting = thread {
            try {
                database.read(::count)
            } catch (e: Throwable) {
                refused = e
            }
        }
        Thread.sleep(50)  // the second read waits for the one reader
        database.close()
        waiting.join(TimeUnit.SECONDS.toMillis(5))
        assertTrue(refused is IllegalStateException, "the waiting read: $refused")
        release.countDown()
        holder.join()
    }

    @Test fun theWarmUpClosedAsItStartsLeavesNothingRunning() {
        repeat(5) { n ->
            val database = TestDb.fresh(tmp.newFolder("phone-$n"))
            var failed: Throwable? = null
            val warming = thread {
                try {
                    database.warmUp()
                } catch (e: IllegalStateException) {
                    // closed before it took a reader: refused, as any read
                } catch (e: Throwable) {
                    failed = e
                }
            }
            database.close()
            warming.join()
            assertNull(failed)
        }
    }
}
