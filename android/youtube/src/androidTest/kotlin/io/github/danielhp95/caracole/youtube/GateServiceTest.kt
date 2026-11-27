package io.github.danielhp95.caracole.youtube

import android.content.ComponentName
import android.content.Context
import android.content.Intent
import android.content.ServiceConnection
import android.os.Binder
import android.os.Bundle
import android.os.DeadObjectException
import android.os.IBinder
import android.os.Message
import android.os.Messenger
import android.os.Parcel
import android.os.SystemClock
import androidx.test.ext.junit.runners.AndroidJUnit4
import io.github.danielhp95.caracole.core.youtube.HostGate
import io.github.danielhp95.caracole.youtube.Runs.context
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Assert.fail
import org.junit.Test
import org.junit.runner.RunWith
import java.io.IOException
import java.util.concurrent.LinkedBlockingQueue
import java.util.concurrent.TimeUnit

/**
 * [GateService] in this, the main process, where nothing it is asked may throw on its thread (an uncaught exception
 * there would end the process, the app's server and queue with it): an asker gone before its answer has the gate opened
 * for it closed; a gate that won't start is said, not thrown; an answer that comes late, after its ask gave up, is
 * never read as the next ask's. Run by `android/scripts/device-test.sh --youtube`, on the emulator alone.
 */
@RunWith(AndroidJUnit4::class)
class GateServiceTest {
    private val made = GateService.makeGate
    private val loopbackMade = GateService.makeLoopbackGate

    @After
    fun put() {
        GateService.makeGate = made
        GateService.makeLoopbackGate = loopbackMade
        GateService.modeOf = null
        GateService.answerDelayMs = 0
    }

    /** A Messenger whose process is gone: every send to it a DeadObjectException, as a dead asker's binder is. */
    private val dead = Messenger(object : Binder() {
        override fun onTransact(code: Int, data: Parcel, reply: Parcel?, flags: Int): Boolean =
            throw DeadObjectException()
    })

    @Test
    fun anAskerGoneBeforeItsAnswerHasItsGateClosedAndThisProcessGoesOn() {
        val bound = LinkedBlockingQueue<IBinder>()
        val connection = object : ServiceConnection {
            override fun onServiceConnected(name: ComponentName, service: IBinder) {
                bound.put(service)
            }

            override fun onServiceDisconnected(name: ComponentName) = Unit
        }
        assertTrue(context.bindService(Intent(context, GateService::class.java), connection, Context.BIND_AUTO_CREATE))
        try {
            val service = Messenger(checkNotNull(bound.poll(10, TimeUnit.SECONDS)) { "GateService didn't bind" })
            val running = checkNotNull(GateService.running)
            val before = running.openGates()
            val newest = running.newest()
            service.send(Message.obtain(null, GateService.OPEN).apply { replyTo = dead; data = Bundle() })
            // The answer's send failed on the service's thread: the gate it opened (the newest) closed, and nothing
            // thrown (this test, in the same process, would have ended).
            val until = SystemClock.elapsedRealtime() + 5_000
            while (running.newest() == newest && SystemClock.elapsedRealtime() < until) SystemClock.sleep(50)
            assertEquals(newest + 1, running.newest())
            SystemClock.sleep(200)
            assertEquals(before, running.openGates())
            // The service still answers.
            GateService.Client(context).use { gates -> gates.open().use { assertTrue(it.log().isEmpty()) } }
        } finally {
            context.unbindService(connection)
        }
    }

    @Test
    fun everyGateOfAClientIsClosedWithIt() {
        val clients = List(2) { GateService.Client(context) }
        clients.forEach { it.open() }
        val running = checkNotNull(GateService.running)
        assertTrue(running.openGates() >= 2)
        clients.forEach { it.close() }
        val until = SystemClock.elapsedRealtime() + 5_000
        while (running.openGates() != 0 && SystemClock.elapsedRealtime() < until) SystemClock.sleep(50)
        assertEquals(0, running.openGates())
    }

    /** A gate closed lets go of the death recipient its open linked on its asker's binder: one linked an open gate. */
    @Test
    fun aGateClosedUnlinksItsDeathRecipient() {
        GateService.Client(context).use { client ->
            val gates = List(3) { client.open() }
            val running = checkNotNull(GateService.running)
            assertEquals(running.openGates(), running.linkedDeaths())
            gates[0].close()
            gates[1].close()
            assertEquals(running.openGates(), running.linkedDeaths())
        }
        val running = checkNotNull(GateService.running)
        val until = SystemClock.elapsedRealtime() + 5_000
        while (running.linkedDeaths() != 0 && SystemClock.elapsedRealtime() < until) SystemClock.sleep(50)
        assertEquals(0, running.linkedDeaths())
    }

    /** An observing gate is the bench's alone, and never under the tests' network: refused to this (the main)
     * process, and to a process named as the bench's while the mode is loopback; no gate opened either way. */
    @Test
    fun anObservingGateIsNeverOpenedHere() {
        val running = { checkNotNull(GateService.running) }
        GateService.Client(context).use { client ->
            client.open().close()
            val newest = running().newest()
            val e = assertThrowsIo { client.openObserving() }
            assertEquals(GateService.OBSERVE_NOT_BENCH, e.message)
            assertEquals(newest, running().newest())
            assertEquals(HostGate.Mode.LOOPBACK, client.mode())
        }
        val newest = running().newest()
        val answers = LinkedBlockingQueue<Bundle>()
        val replies = android.os.HandlerThread("observe-asks").apply { start() }
        val bound = LinkedBlockingQueue<IBinder>()
        val connection = object : ServiceConnection {
            override fun onServiceConnected(name: ComponentName, service: IBinder) {
                bound.put(service)
            }

            override fun onServiceDisconnected(name: ComponentName) = Unit
        }
        try {
            assertTrue(context.bindService(Intent(context, BenchProcessAsker::class.java), connection,
                                           Context.BIND_AUTO_CREATE))
            val asker = Messenger(checkNotNull(bound.poll(30, TimeUnit.SECONDS)) { "the asker didn't bind" })
            asker.send(Message.obtain(null, 1).apply {
                replyTo = Messenger(android.os.Handler(replies.looper) { msg -> answers.put(Bundle(msg.data)); true })
            })
            val answer = checkNotNull(answers.poll(30, TimeUnit.SECONDS)) { "the asker never answered" }
            assertEquals(GateService.OBSERVE_LOOPBACK, answer.getString("refused"))
            assertEquals(newest, running().newest())
        } finally {
            context.unbindService(connection)
            replies.quitSafely()
        }
    }

    /** The kill check's gate is LOOPBACK's whatever this process's mode: with the mode seam saying the network's
     * (never `caracole.network` cleared: it keeps every client of this process on loopback), an ordinary open makes a
     * NETWORK gate and openLoopback the kill check's (the gates made seen through the seams; neither reaches a host). */
    @Test
    fun aLoopbackGateIsLoopbacksWhateverTheProcesssMode() {
        val modes = java.util.Collections.synchronizedList(mutableListOf<String>())
        GateService.makeGate = { mode -> modes += mode.name; HostGate(mode, HostGate.HostRule.YOUTUBE) }
        GateService.makeLoopbackGate = { modes += "kill check"; loopbackMade() }
        GateService.modeOf = { HostGate.Mode.NETWORK }
        GateService.Client(context).use { client ->
            assertEquals(HostGate.Mode.NETWORK, client.mode())
            client.open().close()
            client.openLoopback().close()
        }
        assertEquals("loopback", System.getProperty(YtDlpClient.NETWORK))
        assertEquals(listOf("NETWORK", "kill check"), modes.toList())
    }

    /** The kill check's gate reaches 127.0.0.1 alone: 10.0.2.2 (the emulator's host, a routable private address on
     * some real networks) refused by it with a 403, logged, never dialled; 127.0.0.1 tunnelled. */
    @Test
    fun theKillChecksGateRefuses10002() {
        java.net.ServerSocket(0, 4, java.net.InetAddress.getByName("127.0.0.1")).use { server ->
            val served = Thread { runCatching { server.accept().use { it.getOutputStream().write("ok".toByteArray()) } } }
                .apply { isDaemon = true; start() }
            GateService.Client(context).use { client ->
                client.openLoopback().use { gate ->
                    assertEquals(403, connect(gate, "10.0.2.2:${server.localPort}"))
                    assertEquals(200, connect(gate, "127.0.0.1:${server.localPort}"))
                    val log = gate.log()
                    assertEquals(1, log["10.0.2.2"]?.refused)
                    assertEquals("not 127.0.0.1", log["10.0.2.2"]?.why)
                    assertEquals(0, log["10.0.2.2"]?.connects)
                    assertEquals(1, log["127.0.0.1"]?.connects)
                }
            }
            served.join(5_000)
        }
    }

    /** A CONNECT to [target] through [gate] with its credentials: the answer's status. */
    private fun connect(gate: GateService.Gate, target: String): Int {
        val m = checkNotNull(Regex("""^http://([0-9a-f]+):([0-9a-f]+)@127\.0\.0\.1:(\d+)$""").find(gate.proxyArg))
        val auth = android.util.Base64.encodeToString("${m.groupValues[1]}:${m.groupValues[2]}".toByteArray(),
                                                      android.util.Base64.NO_WRAP)
        java.net.Socket("127.0.0.1", gate.port).use { s ->
            s.soTimeout = 10_000
            s.getOutputStream().write(("CONNECT $target HTTP/1.1\r\nHost: $target\r\n" +
                "Proxy-Authorization: Basic $auth\r\n\r\n").toByteArray(Charsets.ISO_8859_1))
            val head = StringBuilder()
            val input = s.getInputStream()
            while (!head.endsWith("\r\n\r\n")) head.append((input.read().takeIf { it >= 0 } ?: break).toChar())
            return head.substring(head.indexOf(' ') + 1).substringBefore(' ').toInt()
        }
    }

    private fun assertThrowsIo(block: () -> Unit): IOException = try {
        block()
        fail("not refused")
        throw IllegalStateException()
    } catch (e: IOException) {
        e
    }

    @Test
    fun aGateThatWontStartIsSaidNotThrown() {
        // A gate started already: its start() throws, as one that can't listen would.
        GateService.makeGate = { mode -> HostGate(mode, HostGate.HostRule.YOUTUBE).also { it.start() } }
        GateService.Client(context).use { gates ->
            try {
                gates.open()
                fail("opened")
            } catch (e: IOException) {
                assertEquals("the gate couldn't start", e.message)
            }
            GateService.makeGate = made
            gates.open().use { assertTrue(it.proxyArg.startsWith("http://")) }
        }
    }

    @Test
    fun aLateAnswerIsNeverTheNextAsks() {
        GateService.Client(context).use { gates ->
            GateService.answerDelayMs = 1_500
            gates.waitMs = 300
            try {
                gates.open()
                fail("answered in time")
            } catch (e: IOException) {
                assertEquals("the gate's service didn't answer", e.message)
            }
            GateService.answerDelayMs = 0
            gates.waitMs = 10_000
            val gate = gates.open()
            // The late answer (the first ask's gate) came first and was passed over: this is the newest gate.
            val running = checkNotNull(GateService.running)
            assertEquals(2, running.openGates())
            assertEquals(running.newest(), gate.id)
            assertTrue(gate.log().isEmpty())
        }
    }
}
