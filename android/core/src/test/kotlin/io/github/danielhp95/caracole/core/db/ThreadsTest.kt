package io.github.danielhp95.caracole.core.db

import androidx.sqlite.driver.bundled.BundledSQLiteDriver
import androidx.sqlite.execSQL
import io.github.danielhp95.caracole.core.testing.TestDb
import kotlinx.coroutines.async
import kotlinx.coroutines.awaitAll
import kotlinx.coroutines.runBlocking
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import java.io.File
import java.util.concurrent.CountDownLatch
import java.util.concurrent.Executors
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicInteger
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertTrue

/** The plan's §5.5: one writer under `writes`, a pool of readers each lent to one block, WAL, the busy timeout. */
class ThreadsTest {
    @get:Rule val tmp = TemporaryFolder()

    @Test fun readsGoOnOnSeveralThreadsWhileAWriteHoldsTheLock() {
        TestDb.fresh(tmp.root).use { database ->
            database.writeBlocking { it.kvSet("seen", "before") }
            val writing = CountDownLatch(1)
            val readsDone = CountDownLatch(8)
            val pool = Executors.newFixedThreadPool(9)
            try {
                val writer = pool.submit {
                    database.writeBlocking { db ->
                        db.savepoint("long") {
                            db.kvSet("seen", "during")
                            writing.countDown()
                            // The write holds the lock, its transaction open, until every read is done.
                            assertTrue(readsDone.await(30, TimeUnit.SECONDS), "the reads waited for the write")
                        }
                    }
                }
                assertTrue(writing.await(30, TimeUnit.SECONDS))
                assertTrue(database.writes.isLocked)
                val inFlight = AtomicInteger()
                val most = AtomicInteger()
                val together = CountDownLatch(4)
                val reads = (1..8).map {
                    pool.submit<String?> {
                        database.read { db ->
                            most.accumulateAndGet(inFlight.incrementAndGet(), ::maxOf)
                            val seen = db.kvGet("seen")
                            // Four reads hold their connections at once, each on its own thread.
                            together.countDown()
                            assertTrue(together.await(30, TimeUnit.SECONDS), "four reads at once")
                            inFlight.decrementAndGet()
                            seen
                        }.also { readsDone.countDown() }
                    }
                }
                // Each read saw the last commit, never the write's open transaction.
                assertEquals(List(8) { "before" }, reads.map { it.get(30, TimeUnit.SECONDS) })
                assertEquals(4, most.get(), "reads at once (four readers)")
                writer.get(30, TimeUnit.SECONDS)
                assertFalse(database.writes.isLocked)
                assertEquals("during", database.read { it.kvGet("seen") })
            } finally {
                pool.shutdownNow()
            }
        }
    }

    @Test fun writesTakeTheirTurnUnderOneLock() {
        TestDb.fresh(tmp.root).use { database ->
            runBlocking {
                (1..50).map { n ->
                    async(kotlinx.coroutines.Dispatchers.Default) {
                        database.write { db ->
                            val now = db.kvGet("n")?.toInt() ?: 0
                            db.kvSet("n", (now + 1).toString())
                            db.kvSet("w$n", "x")
                        }
                    }
                }.awaitAll()
            }
            assertEquals("50", database.read { it.kvGet("n") })
        }
    }

    @Test fun aWriteWaitsOnTheBusyTimeoutRatherThanFailing() {
        TestDb.fresh(tmp.root).close()
        // Another connection to the file (another process's, say) holds a write transaction for a while.
        val other = BundledSQLiteDriver().open(File(tmp.root, "caracole.sqlite").path)
        other.execSQL("BEGIN IMMEDIATE")
        other.execSQL("INSERT INTO kv (key, value) VALUES ('other', 'first')")
        val released = CountDownLatch(1)
        val pool = Executors.newSingleThreadExecutor()
        try {
            TestDb.fresh(tmp.root).use { database ->
                val started = System.nanoTime()
                pool.submit {
                    Thread.sleep(700)
                    other.execSQL("COMMIT")
                    released.countDown()
                }
                // BEGIN IMMEDIATE (a savepoint's first write) waits for the other's commit, within BUSY_TIMEOUT_MS.
                database.writeBlocking { db -> db.savepoint("mine") { db.kvSet("mine", "second") } }
                val waited = (System.nanoTime() - started) / 1_000_000
                assertTrue(released.await(5, TimeUnit.SECONDS))
                assertTrue(waited in 500 until Database.BUSY_TIMEOUT_MS, "waited $waited ms")
                assertEquals(listOf("first", "second"), database.read { db -> listOf("other", "mine").map { db.kvGet(it) } })
            }
        } finally {
            pool.shutdownNow()
            other.close()
        }
    }
}
