package io.github.danielhp95.caracole.youtube

import android.content.ComponentName
import android.content.Context
import android.content.Intent
import android.content.ServiceConnection
import android.os.Bundle
import android.os.Handler
import android.os.HandlerThread
import android.os.IBinder
import android.os.Message
import android.os.Messenger
import android.os.SystemClock
import androidx.test.ext.junit.runners.AndroidJUnit4
import io.github.danielhp95.caracole.youtube.Runs.context
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertThrows
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith
import java.util.concurrent.LinkedBlockingQueue
import java.util.concurrent.TimeUnit

/**
 * One run at a time across the app's processes: a client of another process (":other", [OtherProcessRuns], as the
 * bench's ":ytbench" is) running a trickled download, this process's client kills nothing and starts nothing, saying
 * [YtDlpClient.ANOTHER_RUN]; the other's run goes on, its `:youtube` process the same, until it is stopped; then a
 * run here works. Run by `android/scripts/device-test.sh --youtube`, on the emulator alone.
 */
@RunWith(AndroidJUnit4::class)
class AcrossProcessesTest {
    private lateinit var gates: GateService.Client
    private lateinit var gate: GateService.Gate
    private val replies = HandlerThread("across-processes").apply { start() }
    private val answers = LinkedBlockingQueue<Bundle>()
    private val incoming = Messenger(Handler(replies.looper) { msg -> answers.put(Bundle(msg.data)); true })
    private val bound = LinkedBlockingQueue<IBinder>()
    private val connection = object : ServiceConnection {
        override fun onServiceConnected(name: ComponentName, service: IBinder) {
            bound.put(service)
        }

        override fun onServiceDisconnected(name: ComponentName) = Unit
    }

    @Before
    fun open() {
        gates = GateService.Client(context)
        gate = gates.open()
    }

    @After
    fun close() {
        context.unbindService(connection)
        gate.close()
        gates.close()
        replies.quitSafely()
    }

    private fun other(): Messenger {
        assertTrue(context.bindService(Intent(context, OtherProcessRuns::class.java), connection,
                                       Context.BIND_AUTO_CREATE))
        return Messenger(checkNotNull(bound.poll(30, TimeUnit.SECONDS)) { "OtherProcessRuns didn't bind" })
    }

    @Test
    fun aClientOfAnotherProcessRunningKeepsThisOneFromKillingOrStartingAnything() {
        LoopbackServer(Runs.clip, trickle = 256, pause = 100).use { server ->
            val other = other()
            val into = Runs.into("other-process")
            val argv = Runs.download(gate.proxyArg, server.url(), into)
            val folders = Runs.folders(argv)
            other.send(Message.obtain(null, OtherProcessRuns.RUN).apply {
                replyTo = incoming
                data = Bundle().apply {
                    putStringArray(OtherProcessRuns.ARGV, argv.toTypedArray())
                    putString(OtherProcessRuns.MODE, "LOOPBACK")
                    putString(OtherProcessRuns.CACHE, folders.cache!!.path)
                    putString(OtherProcessRuns.INTO, folders.into!!.path)
                }
            })
            assertTrue("the other process's run never began its body", server.bodyBegun.await(120, TimeUnit.SECONDS))
            val youtube = checkNotNull(Runs.youtube()) { "no :youtube process" }
            YtDlpClient(context).use { here ->
                val t0 = SystemClock.elapsedRealtime()
                val e = assertThrows(YtDlpNotStarted::class.java) {
                    here.run(Runs.version(gate.proxyArg), 60.0, { _, _ -> }, {})
                }
                assertEquals(YtDlpClient.ANOTHER_RUN, e.words)
                assertTrue("it waited", SystemClock.elapsedRealtime() - t0 < 5_000)
            }
            SystemClock.sleep(1_000)
            assertEquals("the other's :youtube process was killed", youtube, Runs.youtube())
            assertTrue("the other's run is going", answers.isEmpty())
            other.send(Message.obtain(null, OtherProcessRuns.CANCEL))
            val ran = checkNotNull(answers.poll(60, TimeUnit.SECONDS)) { "the other's run never ended" }
            assertEquals(null, ran.getString(OtherProcessRuns.ERROR))
            assertTrue("the other's run ended otherwise than by its cancel", ran.getBoolean(OtherProcessRuns.KILLED))
        }
        // Its lock let go of: a run here goes.
        YtDlpClient(context).use { here ->
            val ran = here.run(Runs.version(gate.proxyArg), 120.0, { _, _ -> }, {})
            assertEquals(ran.stderrTail, 0, ran.exit)
            assertFalse(ran.killed)
        }
    }
}
