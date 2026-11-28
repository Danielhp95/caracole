package io.github.danielhp95.caracole.youtube

import android.os.Process
import android.os.SystemClock
import androidx.test.ext.junit.runners.AndroidJUnit4
import io.github.danielhp95.caracole.youtube.Runs.context
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Assert.fail
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit

/**
 * A run stopped leaves nothing behind: a trickled download stopped 2 s into its body by a cancel, by a close and by
 * its timeout, then, 2 s later, no process of this app's uid but this one (the main); a run whose yt-dlp started a
 * child, qjs (the glue's one `--exec` form, under LOOPBACK alone), cancelled 2 s after the child appears, the child gone
 * with it; a run stopped before its STARTED came (the service's seam holds it back), no process left (the client's
 * kill or the service's own exit once unbound: those two tests don't tell which); a run cancelled or closed while it
 * waits its turn, which starts nothing; and the `:youtube` process killed by another (a SIGKILL from outside the
 * client, as the low-memory killer sends one: `am kill` leaves a process a foreground one binds) is [YtDlpStopped],
 * this process answering after it; a ProcessYtDlp stopped as it makes its run's client, and a run asked on an
 * interrupted thread or interrupted while the service binds, which send nothing. Each time the next run works. Run
 * by `android/scripts/device-test.sh --youtube`, on the emulator alone.
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
        Runs.said("$what: $ms ms after the stop, processes of this uid but the main one: $left")
        assertEquals("left behind: $left", emptyMap<Int, String>(), left)
    }

    /** The next run, of a fresh client: its own answer, whole. */
    private fun theNextRunWorks() {
        YtDlpClient(context).use { next ->
            val ran = next.run(Runs.version(gate.proxyArg), 120.0, { _, _ -> }, {})
            assertEquals(ran.stderrTail, 0, ran.exit)
            assertTrue(ran.stdout, Regex("""\d{4}\.\d+\.\d+\n""").matches(ran.stdout))
        }
    }

    private fun trickled() = LoopbackServer(Runs.clip, trickle = 256, pause = 100)

    /** A trickled download, stopped by [stop] 2 s into its body. */
    private fun stoppedInItsBody(name: String, timeoutS: Double = 120.0, stop: () -> Unit): Ran = trickled().use { s ->
        val stopper = Thread {
            if (s.bodyBegun.await(120, TimeUnit.SECONDS)) {
                SystemClock.sleep(2_000)
                stop()
            }
        }.apply { start() }
        val argv = Runs.download(gate.proxyArg, s.url(), Runs.into(name))
        val ran = client.run(argv, timeoutS, { _, _ -> }, {}, Runs.folders(argv))
        stopper.join()
        ran
    }

    @Test
    fun aTrickledDownloadCancelledLeavesNoProcess() {
        val ran = stoppedInItsBody("cancel") { client.cancel() }
        assertTrue("not stopped: exit ${ran.exit}\n${ran.stderrTail}", ran.killed)
        assertFalse(ran.timedOut)
        assertEquals(-1, ran.exit)
        nothingLeft(2_000, "a trickled download cancelled")
        theNextRunWorks()
    }

    @Test
    fun aTrickledDownloadClosedLeavesNoProcess() {
        val ran = stoppedInItsBody("close") { client.close() }
        assertTrue(ran.killed)
        assertFalse(ran.timedOut)
        nothingLeft(2_000, "a trickled download closed")
        theNextRunWorks()
    }

    @Test
    fun aTrickledDownloadPastItsTimeoutLeavesNoProcess() {
        // The download's own pause (2.5–5 s) and 2 s or so of its body: past 9 s, the run is killed mid-body.
        trickled().use { s ->
            val argv = Runs.download(gate.proxyArg, s.url(), Runs.into("timeout"))
            val ran = client.run(argv, 9.0, { _, _ -> }, {}, Runs.folders(argv))
            assertTrue(ran.killed && ran.timedOut)
            assertEquals(-1, ran.exit)
            assertTrue("the body never began", s.bodyBegun.count == 0L)
        }
        nothingLeft(2_000, "a trickled download past its timeout")
        theNextRunWorks()
    }

    @Test
    fun aChildOfYtDlpGoesWithItsProcess() {
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
            val into = Runs.into("child")
            val argv = Runs.download(gate.proxyArg, server.url(), into, Runs.child(into))
            val ran = client.run(argv, 120.0, { _, _ -> }, {}, Runs.folders(argv))
            stopper.join()
            Runs.said("a child of yt-dlp: qjs $child; this process ${Process.myPid()} (group " +
                "${Runs.group(Process.myPid())}); the others as it ran: $groups")
            assertTrue("no qjs child seen:\n${ran.stderrTail}", child > 0)
            assertTrue(ran.killed)
        }
        nothingLeft(2_000, "a child of yt-dlp")
        theNextRunWorks()
    }

    /** Stopped once the request was sent and before STARTED came: no process is left and the next run works. What it
     * doesn't tell: whether the client's wait-and-kill ended `:youtube` or the service's own exit did (unbound, it runs
     * nothing and kills its process): either leaves the same nothing, which is what this holds. */
    @Test
    fun aRunStoppedBeforeItsStartLeavesNoProcess() {
        client.startedDelayMs = 2_500
        val ran = client.run(Runs.version(gate.proxyArg), 1.0, { _, _ -> }, {})
        assertTrue(ran.killed && ran.timedOut)
        assertEquals(-1, ran.processStartMs)
        nothingLeft(2_000, "a run stopped before its STARTED")
        theNextRunWorks()
    }

    /** Stopped before STARTED, which comes after the client's wait: no process is left and the next run works.
     * Whether by the client's kill (finding the process by its name) or by the service's own exit once unbound, this
     * doesn't tell apart. */
    @Test
    fun aRunStoppedLongBeforeItsStartLeavesNoProcess() {
        client.startedDelayMs = YtDlpClient.START_WAIT_MS + 3_000
        val ran = client.run(Runs.version(gate.proxyArg), 1.0, { _, _ -> }, {})
        assertTrue(ran.killed && ran.timedOut)
        nothingLeft(2_000, "a run stopped long before its STARTED")
        theNextRunWorks()
    }

    /** Another client's run in the way: this one's cancel or close while it waits its turn starts nothing. */
    @Test
    fun aRunStoppedWhileItWaitsItsTurnStartsNothing() {
        for (stop in listOf<(YtDlpClient) -> Unit>({ it.cancel() }, { it.close() })) {
            trickled().use { s ->
                val other = YtDlpClient(context)
                val waits = CountDownLatch(1)
                var ran: Ran? = null
                var took = 0L
                val waiter = Thread {
                    val t0 = SystemClock.elapsedRealtime()
                    ran = other.run(Runs.version(gate.proxyArg), 120.0, { _, _ -> }, { waits.countDown() })
                    took = SystemClock.elapsedRealtime() - t0
                }
                val first = Thread {
                    val argv = Runs.download(gate.proxyArg, s.url(), Runs.into("first"))
                    client.run(argv, 120.0, { _, _ -> }, {}, Runs.folders(argv))
                }.apply { start() }
                assertTrue(s.bodyBegun.await(120, TimeUnit.SECONDS))
                waiter.start()
                assertTrue("the second run didn't wait", waits.await(30, TimeUnit.SECONDS))
                stop(other)
                SystemClock.sleep(500)
                client.cancel()
                first.join()
                waiter.join()
                other.close()
                assertTrue("the waiting run ran: $ran", ran!!.killed && ran!!.processStartMs == -1L)
                assertTrue("it waited past the first's end: $took ms", took < 60_000)
            }
            nothingLeft(2_000, "a run stopped while it waited its turn")
        }
        theNextRunWorks()
    }

    /** A stop landing as ProcessYtDlp makes the run's client, before the run is registered with it, is never lost:
     * that client starts nothing (no process), and the run is NotStarted, nothing sent. */
    @Test
    fun aProcessYtDlpClosedAsItsClientIsMadeStartsNothing() {
        for (stop in listOf<(ProcessYtDlp) -> Unit>({ it.cancel() }, { it.close() })) {
            val process = ProcessYtDlp(context)
            process.beforeRun = { stop(process) }
            try {
                process.run(Runs.version(gate.proxyArg), 120.0, {}, {})
                fail("ran after its stop")
            } catch (e: io.github.danielhp95.caracole.core.youtube.YtDlpProcess.NotStarted) {
                assertEquals(ProcessYtDlp.STOPPED_BEFORE, e.message)
            } finally {
                process.close()
            }
            nothingLeft(1_000, "a ProcessYtDlp stopped as its client was made")
        }
        theNextRunWorks()
    }

    /** A run asked on a thread interrupted already sent nothing: YtDlpNotStarted, its interrupt kept for the caller,
     * nothing left. (Measured here: the emulator's FileChannel.tryLock doesn't check a pending interrupt, so it is
     * met as the service binds; where a channel throws ClosedByInterruptException at the lock, the client says the
     * same.) */
    @Test
    fun aRunAskedOnAnInterruptedThreadSentNothingAndKeepsItsInterrupt() {
        var interrupted = false
        val thrown = runCatching {
            Thread.currentThread().interrupt()
            try {
                client.run(Runs.version(gate.proxyArg), 120.0, { _, _ -> }, {})
            } finally {
                interrupted = Thread.interrupted()
            }
        }.exceptionOrNull()
        assertTrue("$thrown", thrown is YtDlpNotStarted)
        assertEquals(YtDlpClient.INTERRUPTED_WAITING, (thrown as YtDlpNotStarted).words)
        assertTrue("the interrupt kept", interrupted)
        nothingLeft(2_000, "a run asked on an interrupted thread")
        theNextRunWorks()
    }

    /** A thread interrupted while the service binds, before the request is sent: YtDlpNotStarted, its interrupt
     * kept, no process left. */
    @Test
    fun aRunInterruptedWhileItBindsSentNothingAndKeepsItsInterrupt() {
        client.onBound = { Thread.currentThread().interrupt() }
        var interrupted = false
        val thrown = runCatching {
            try {
                client.run(Runs.version(gate.proxyArg), 120.0, { _, _ -> }, {})
            } finally {
                interrupted = Thread.interrupted()
            }
        }.exceptionOrNull()
        assertTrue("$thrown", thrown is YtDlpNotStarted)
        assertEquals(YtDlpClient.INTERRUPTED_WAITING, (thrown as YtDlpNotStarted).words)
        assertTrue("the interrupt kept", interrupted)
        nothingLeft(2_000, "a run interrupted while it binds")
        theNextRunWorks()
    }

    @Test
    fun theProcessKilledByAnotherIsYtDlpStopped() {
        trickled().use { server ->
            // `am kill` kills a background process alone: :youtube, bound BIND_IMPORTANT by this foreground one, it
            // leaves (measured: the run then ends as ever). So the process is killed as the low-memory killer kills
            // one, a SIGKILL, from outside the client (Process.killProcess, which this uid may send its own).
            val killer = Thread {
                if (server.bodyBegun.await(120, TimeUnit.SECONDS)) {
                    val youtube = checkNotNull(Runs.youtube()) { "no :youtube process" }
                    Runs.said("killing :youtube, $youtube, from outside the client")
                    Process.killProcess(youtube)
                }
            }.apply { start() }
            try {
                val argv = Runs.download(gate.proxyArg, server.url(), Runs.into("killed"))
                val ran = client.run(argv, 60.0, { _, _ -> }, {}, Runs.folders(argv))
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
