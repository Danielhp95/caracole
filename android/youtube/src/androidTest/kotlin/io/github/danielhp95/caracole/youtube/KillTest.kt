package io.github.danielhp95.caracole.youtube

import android.os.Process
import android.os.SystemClock
import androidx.test.ext.junit.runners.AndroidJUnit4
import io.github.danielhp95.caracole.youtube.Runs.context
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Assert.fail
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith
import java.util.concurrent.TimeUnit

/**
 * A run stopped leaves nothing behind: a trickled download cancelled 2 s into its body, then, 2 s later, no process of
 * this app's uid but this one (the main); a run whose yt-dlp started a child, qjs (`--exec before_dl:`, under loopback
 * alone, the glue's one exception), cancelled 2 s after the child appears, the child gone with it; the next run works;
 * and the `:youtube` process killed by another (a SIGKILL from outside the client, as the low-memory killer sends one:
 * `am kill` leaves a process a foreground one binds) is [YtDlpStopped], this process answering after it. Run by
 * `android/scripts/device-test.sh --youtube`, on the emulator alone.
 */
@RunWith(AndroidJUnit4::class)
class KillTest {
    private lateinit var gates: GateService.Client
    private lateinit var gate: GateService.Gate
    private val client = YtDlpClient(context)

    @Before
    fun open() {
        gates = GateService.Client(context)
        gate = gates.open()
        assertEquals("a process of this uid before the test: ${Runs.others()}", emptyMap<Int, String>(), Runs.others())
    }

    @After
    fun close() {
        client.close()
        gate.close()
        gates.close()
    }

    /** No process of this uid but this one, [ms] after: the measurement, said whatever it finds. */
    private fun nothingLeft(ms: Long, what: String) {
        SystemClock.sleep(ms)
        val left = Runs.others()
        Runs.said("$what: ${ms} ms after the stop, processes of this uid but the main one: $left")
        assertEquals("left behind: $left", emptyMap<Int, String>(), left)
    }

    private fun theNextRunWorks() {
        val ran = client.run(Runs.version(gate.proxyArg), 120.0, { _, _ -> }, {})
        assertEquals(ran.stderrTail, 0, ran.exit)
    }

    @Test
    fun aTrickledDownloadStoppedLeavesNoProcess() {
        LoopbackServer(Runs.clip, trickle = 256, pause = 100).use { server ->
            val stopper = Thread {
                if (server.bodyBegun.await(120, TimeUnit.SECONDS)) {
                    SystemClock.sleep(2_000)
                    client.cancel()
                }
            }.apply { start() }
            val ran = client.run(Runs.download(gate.proxyArg, server.url(), Runs.into("trickle")), 120.0, { _, _ -> }, {})
            stopper.join()
            assertTrue("not stopped: exit ${ran.exit}\n${ran.stderrTail}", ran.killed)
            assertEquals(-1, ran.exit)
        }
        nothingLeft(2_000, "a trickled download")
        theNextRunWorks()
    }

    @Test
    fun aChildOfYtDlpGoesWithItsProcess() {
        val qjs = Qjs.path(context).path
        LoopbackServer(Runs.clip).use { server ->
            var child = -1
            var groups = ""
            val stopper = Thread {
                val until = SystemClock.elapsedRealtime() + 120_000
                while (child < 0 && SystemClock.elapsedRealtime() < until) {
                    Runs.others().entries.firstOrNull { "libqjs.so" in it.value }?.let { child = it.key }
                    SystemClock.sleep(50)
                }
                if (child > 0) {
                    groups = Runs.others().keys.joinToString { "$it (group ${Runs.group(it)})" }
                    SystemClock.sleep(2_000)
                }
                client.cancel()
            }.apply { start() }
            val argv = Runs.download(gate.proxyArg, server.url(), Runs.into("child"),
                                     // A script with no `{}`, which --exec would fill with the file's path.
                                     listOf("--exec", "before_dl:$qjs -e 'while (true);'"))
            val ran = client.run(argv, 120.0, { _, _ -> }, {})
            stopper.join()
            Runs.said("a child of yt-dlp: qjs $child; this process ${Process.myPid()} (group " +
                "${Runs.group(Process.myPid())}); the others as it ran: $groups")
            assertTrue("no qjs child seen:\n${ran.stderrTail}", child > 0)
            assertTrue(ran.killed)
        }
        nothingLeft(2_000, "a child of yt-dlp")
        theNextRunWorks()
    }

    @Test
    fun theProcessKilledByAnotherIsYtDlpStopped() {
        LoopbackServer(Runs.clip, trickle = 256, pause = 100).use { server ->
            // `am kill` kills a background process alone: :youtube, bound BIND_IMPORTANT by this foreground one, it
            // leaves (measured: the run then ends as ever). So the process is killed as the low-memory killer kills
            // one, a SIGKILL, from outside the client (Process.killProcess, which this uid may send its own).
            val killer = Thread {
                if (server.bodyBegun.await(120, TimeUnit.SECONDS)) {
                    val youtube = Runs.others().entries.first { it.value.endsWith(":youtube") }.key
                    Runs.said("killing :youtube, $youtube, from outside the client")
                    Process.killProcess(youtube)
                }
            }.apply { start() }
            try {
                val ran = client.run(Runs.download(gate.proxyArg, server.url(), Runs.into("killed")), 60.0,
                                     { _, _ -> }, {})
                fail("not stopped: killed ${ran.killed}, exit ${ran.exit}")
            } catch (e: YtDlpStopped) {
                assertEquals(YtDlpClient.STOPPED, e.words)
            } finally {
                killer.join()
            }
        }
        // This process answers: its gate, and a run after.
        assertTrue(gate.log().containsKey("127.0.0.1"))
        nothingLeft(2_000, "a SIGKILL from outside")
        theNextRunWorks()
    }
}
