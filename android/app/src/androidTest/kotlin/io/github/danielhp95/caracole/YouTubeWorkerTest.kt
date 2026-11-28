package io.github.danielhp95.caracole

import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import androidx.work.NetworkType
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
 * pass itself (which songs, how many, its stops) is the JVM's YouTubeAutoTest, over the real queue. Before and after
 * each test: both works cancelled, every `sync:base:%` record cleared (the phone's syncs: a test's own), the switch on.
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

    /** Both works' constraints as the design's §5.3 says: unmetered and the battery not low; the daily also charging. */
    @Test fun theWorksConstraintsAreTheDesigns() {
        YouTubeWorker.soon(context, phone)
        YouTubeWorker.schedule(context, phone)
        val soon = work.getWorkInfosForUniqueWork(YouTubeWorker.SOON).get().single().constraints
        val daily = work.getWorkInfosForUniqueWork(YouTubeWorker.DAILY).get().single().constraints
        for (c in listOf(soon, daily)) {
            assertEquals(NetworkType.UNMETERED, c.requiredNetworkType)
            assertTrue(c.requiresBatteryNotLow())
        }
        assertTrue(!soon.requiresCharging() && daily.requiresCharging())
    }

    @Test fun scheduledTwiceTheDailyWorkIsKept() {
        YouTubeWorker.schedule(context, phone)
        val first = work.getWorkInfosForUniqueWork(YouTubeWorker.DAILY).get().single().id
        YouTubeWorker.schedule(context, phone)
        assertEquals(first, work.getWorkInfosForUniqueWork(YouTubeWorker.DAILY).get().single().id)
    }

    /** The work forced through JobScheduler (`cmd jobscheduler run -f`, past its delay and constraints): its
     * doWork runs the pass, which with nothing due queues nothing; with the switch turned off since, it stops there. */
    @Test fun theSoonWorkForcedRunsThePass() = onWifiCharging {
        YouTubeWorker.lastForTests = null
        YouTubeWorker.foregroundForTests = false
        YouTubeWorker.soon(context, phone)
        force(YouTubeWorker.SOON)
        assertEquals(WorkInfo.State.SUCCEEDED, finished(YouTubeWorker.SOON))
        assertTrue("the worker went into the foreground (setForeground)", YouTubeWorker.foregroundForTests)
        // The pass ran: nothing due, or (no chord models on this emulator) the route not offered; no job either way.
        val stopped = YouTubeWorker.lastForTests?.stopped
        assertTrue("$stopped", stopped == YouTubeAuto.Stop.NOTHING_DUE || stopped == YouTubeAuto.Stop.NOT_OFFERED)
        assertEquals(emptyList<Int>(), YouTubeWorker.lastForTests?.jobs)

        YouTubeWorker.lastForTests = null
        YouTubeWorker.soon(context, phone)
        phone.parts.database.writeBlocking { db -> YouTubeAuto.set(db, false) }
        force(YouTubeWorker.SOON)
        assertEquals(WorkInfo.State.SUCCEEDED, finished(YouTubeWorker.SOON))
        assertEquals(YouTubeAuto.Stop.SWITCHED_OFF, YouTubeWorker.lastForTests?.stopped)
    }

    /** The daily work's run on a phone that synced since it was scheduled lets itself go, running no pass. (A periodic
     * work forced before its period WorkManager defers, so its run is called as doWork calls it.) */
    @Test fun theDailyWorkLetsItselfGoOncePaired() {
        YouTubeWorker.schedule(context, phone)
        assertEquals(1, waiting(YouTubeWorker.DAILY))
        phone.parts.database.writeBlocking { db ->
            db.kvSet("sync:base:0f1e2d3c4b5a6978", """{"format": 3, "units": {"song/x": [null, "${Stamps.of(Instant.now())}"]}}""")
        }
        YouTubeWorker.lastForTests = null
        kotlinx.coroutines.runBlocking { YouTubeWorker.work(context, phone, daily = true) }
        assertEquals(0, waiting(YouTubeWorker.DAILY))
        assertEquals(null, YouTubeWorker.lastForTests)
    }

    /** [block] with the emulator's constraints held (WorkManager checks them again as the job starts): Wi-Fi, no mobile
     * data, on AC and full; Wi-Fi and mobile data put back as they were after, the battery reset. The emulator's alone:
     * device-test.sh runs nothing on a phone. */
    private fun onWifiCharging(block: () -> Unit) {
        Assume.assumeTrue("an emulator",
                          android.os.Build.FINGERPRINT.contains("generic") || android.os.Build.PRODUCT.contains("sdk"))
        val data = shell("settings get global mobile_data").trim() == "1"
        val wifi = shell("settings get global wifi_on").trim() != "0"
        shell("svc data disable"); shell("svc wifi enable")
        shell("dumpsys battery set ac 1"); shell("dumpsys battery set level 100")
        try {
            val deadline = System.currentTimeMillis() + 20_000
            while (Caracole.metered(context) && System.currentTimeMillis() < deadline) Thread.sleep(200)
            block()
        } finally {
            shell("dumpsys battery reset")
            shell(if (wifi) "svc wifi enable" else "svc wifi disable")
            shell(if (data) "svc data enable" else "svc data disable")
        }
    }

    /** The JobScheduler job of the unique work [name], run now whatever its delay and constraints: its job id the one
     * WorkManager gave it, read from WorkManager's PRIVATE database (SystemIdInfo, in no_backup, in this, the app's
     * process) and its JobScheduler namespace: both WorkManager 2.10's, to redo at a WorkManager bump. */
    private fun force(name: String) {
        val id = work.getWorkInfosForUniqueWork(name).get().single().id.toString()
        val deadline = System.currentTimeMillis() + 10_000
        var job: Int? = null
        while (job == null && System.currentTimeMillis() < deadline) {
            job = android.database.sqlite.SQLiteDatabase.openDatabase(java.io.File(context.noBackupFilesDir, "androidx.work.workdb").path,
                                                                      null, android.database.sqlite.SQLiteDatabase.OPEN_READONLY).use { db ->
                db.rawQuery("SELECT system_id FROM SystemIdInfo WHERE work_spec_id = ?", arrayOf(id)).use { c ->
                    if (c.moveToFirst()) c.getInt(0) else null
                }
            }
            if (job == null) Thread.sleep(200)
        }
        // WorkManager 2.10 schedules in a JobScheduler namespace of its own from Android 14 on.
        val namespace = if (android.os.Build.VERSION.SDK_INT >= 34) "-n $WM_NAMESPACE " else ""
        val said = shell("cmd jobscheduler run -f $namespace${context.packageName} ${job ?: throw AssertionError("no job for $name ($id)")}")
        forced = "job $job: $said"
    }

    private fun finished(name: String): WorkInfo.State {
        val deadline = System.currentTimeMillis() + 60_000
        while (System.currentTimeMillis() < deadline) {
            val state = work.getWorkInfosForUniqueWork(name).get().single().state
            if (state.isFinished) return state
            Thread.sleep(200)
        }
        val state = work.getWorkInfosForUniqueWork(name).get().single().state
        throw AssertionError("$name still $state after $forced; " +
            shell("logcat -d -t 60 -v brief WM-SystemJobService:V WM-Processor:V WM-WorkerWrapper:V WM-SystemJobScheduler:V *:S").replace('\n', '|'))
    }

    private var forced = ""

    private companion object {
        const val WM_NAMESPACE = "androidx.work.systemjobscheduler"
    }

    /** [command] in the device's shell, its output and its errors. */
    private fun shell(command: String): String {
        val fds = InstrumentationRegistry.getInstrumentation().uiAutomation.executeShellCommandRwe(command)
        fds[1].close()  // nothing to write
        val out = android.os.ParcelFileDescriptor.AutoCloseInputStream(fds[0]).use { it.readBytes().decodeToString() }
        val err = android.os.ParcelFileDescriptor.AutoCloseInputStream(fds[2]).use { it.readBytes().decodeToString() }
        return out + err
    }
}
