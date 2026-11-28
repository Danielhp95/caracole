package io.github.danielhp95.caracole

import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import androidx.work.WorkInfo
import androidx.work.WorkManager
import io.github.danielhp95.caracole.core.index.Stamps
import io.github.danielhp95.caracole.server.lookups.YouTubeAuto
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Assume
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith
import java.time.Instant

/**
 * The automatic YouTube pass's work on the device (YouTubeWorker, the phone-youtube design's §5.3), through the real
 * WorkManager of the debug app: the daily work scheduled on a phone with no computer, and not on one that synced
 * within 14 days; the switch off schedules nothing and cancels what was there; soon's work enqueued once, KEEP. The
 * pass itself (which songs, how many, its stops) is the JVM's YouTubeAutoTest, over the real queue.
 *
 *     android/scripts/device-test.sh YouTubeWorkerTest
 */
@RunWith(AndroidJUnit4::class)
class YouTubeWorkerTest {
    private val context get() = InstrumentationRegistry.getInstrumentation().targetContext
    private val phone by lazy { Caracole.phone(context) }
    private val work by lazy { WorkManager.getInstance(context) }

    @Before fun clean() {
        Assume.assumeTrue("a build with yt-dlp", phone.youtube != null)
        work.cancelUniqueWork(YouTubeWorker.SOON).result.get()
        work.cancelUniqueWork(YouTubeWorker.DAILY).result.get()
        phone.parts.database.writeBlocking { db ->
            db.execute("DELETE FROM kv WHERE key LIKE 'sync:base:%'")
            YouTubeAuto.set(db, true)
        }
    }

    @After fun leave() {
        work.cancelUniqueWork(YouTubeWorker.SOON).result.get()
        work.cancelUniqueWork(YouTubeWorker.DAILY).result.get()
        phone.parts.database.writeBlocking { db ->
            db.execute("DELETE FROM kv WHERE key LIKE 'sync:base:%'")
            db.execute("DELETE FROM kv WHERE key = ?", YouTubeAuto.SWITCH)
        }
    }

    private fun waiting(name: String): Int = work.getWorkInfosForUniqueWork(name).get()
        .count { it.state == WorkInfo.State.ENQUEUED || it.state == WorkInfo.State.RUNNING || it.state == WorkInfo.State.BLOCKED }

    @Test fun theDailyWorkIsScheduledOnAPhoneWithNoComputerAndNotOnOneThatSynced() {
        YouTubeWorker.schedule(context, phone)
        assertEquals(1, waiting(YouTubeWorker.DAILY))
        val tags = work.getWorkInfosForUniqueWork(YouTubeWorker.DAILY).get().single().tags
        assertTrue("$tags", YouTubeWorker.DAILY in tags)
        phone.parts.database.writeBlocking { db ->
            db.kvSet("sync:base:0f1e2d3c4b5a6978",
                     """{"format": 3, "units": {"song/x": [null, "${Stamps.of(Instant.now().minusSeconds(86_400))}"]}}""")
        }
        YouTubeWorker.schedule(context, phone)
        assertEquals("synced yesterday: no daily pass", 0, waiting(YouTubeWorker.DAILY))
    }

    @Test fun theSwitchOffSchedulesNothing() {
        phone.parts.database.writeBlocking { db -> YouTubeAuto.set(db, false) }
        YouTubeWorker.schedule(context, phone)
        YouTubeWorker.soon(context, phone)
        assertEquals(0, waiting(YouTubeWorker.DAILY))
        assertEquals(0, waiting(YouTubeWorker.SOON))
    }

    @Test fun soonAfterALookupIsOneWorkWhateverHowOftenItIsAsked() {
        phone.onNoSheet()
        YouTubeWorker.soon(context, phone)
        assertEquals(1, waiting(YouTubeWorker.SOON))
        val info = work.getWorkInfosForUniqueWork(YouTubeWorker.SOON).get().single()
        assertEquals(WorkInfo.State.ENQUEUED, info.state)  // two minutes on, Wi-Fi and the battery's say
    }
}
