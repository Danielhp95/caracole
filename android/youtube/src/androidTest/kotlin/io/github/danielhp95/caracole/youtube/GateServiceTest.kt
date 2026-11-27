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

    @After
    fun put() {
        GateService.makeGate = made
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
