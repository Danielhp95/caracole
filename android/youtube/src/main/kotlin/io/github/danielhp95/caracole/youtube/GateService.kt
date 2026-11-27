package io.github.danielhp95.caracole.youtube

import android.app.Service
import android.content.ComponentName
import android.content.Context
import android.content.Intent
import android.content.ServiceConnection
import android.os.Bundle
import android.os.Handler
import android.os.HandlerThread
import android.os.IBinder
import android.os.Looper
import android.os.Message
import android.os.Messenger
import android.os.RemoteException
import android.os.SystemClock
import io.github.danielhp95.caracole.core.youtube.HostGate
import java.io.Closeable
import java.io.IOException
import java.util.concurrent.ConcurrentHashMap
import java.util.concurrent.LinkedBlockingQueue
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicInteger
import java.util.concurrent.atomic.AtomicLong

/**
 * The app's gate for another process of the app (the phone-youtube design's §3.3): a [HostGate] runs in the main process
 * alone, where this service is, so a process that runs yt-dlp's argv from elsewhere (the bench's `:ytbench`) asks it
 * here for one, then for its log. Its mode is decided here, in the main process, from `caracole.network` (the test
 * runner's, [HostGate.Mode.of]): `loopback` under the test runners, the network otherwise, given to the gate's
 * constructor (the gate reads no property); its rule YOUTUBE's.
 *
 * Over a [Messenger]: [MODE] answers the gates' mode (a client of another process sends it to `:youtube`, the
 * main process's, as its own has no test runner to set it); [OPEN] starts a gate and answers its id, port and
 * `proxyArg` (which holds its secret, carried in the answer alone, never logged); [OPEN_OBSERVING] the same of an
 * OBSERVE gate (the bench's every host logged), opened only where the mode is the network's (under the tests'
 * LOOPBACK never, so no test can ask one) and for an ask that names the bench's own process (`:ytbench`): the pid is
 * the asker's own claim, which the app's ActivityManager must list under that name (a Messenger carries no calling
 * pid), so it guards against a mistake inside the app's own uid, never against another process of the app; the bench
 * asks it from its button alone; [OPEN_LOOPBACK] a gate of LOOPBACK's mode whatever this process's, which can reach
 * 127.0.0.1 alone ([HostGate.KILL_CHECK_HOSTS]: never 10.0.2.2, a routable private address on some real networks; the
 * bench's kill check, on the owner's phone too: always safe to open); [LOG] answers a gate's [HostGate.log] and [HostGate.refusedAny]; [CLOSE] closes one;
 * [CLOSE_ALL] a client's every gate (its close), each gate is closed too when the process that asked for it dies, and
 * every gate when the service ends. Nothing it is asked throws on its thread (where an uncaught
 * exception would end the main process, its server and queue with it): a gate that won't start is said in the answer,
 * and an answer to an asker gone closes the gate opened for it. [Client] is that from the other side, each ask matched
 * to its own answer.
 */
class GateService : Service() {
    private val thread = HandlerThread("caracole-gate-service").apply { start() }
    private val gates = ConcurrentHashMap<Int, HostGate>()
    /** Each gate's asker: the binder of the Messenger it asked with, whose client's close, or process's death, closes
     * it. */
    private val owners = ConcurrentHashMap<Int, IBinder>()
    /** Each gate's death recipient on its asker's binder, unlinked as the gate closes. */
    private val deaths = ConcurrentHashMap<Int, IBinder.DeathRecipient>()
    private val serial = AtomicInteger()
    private val messenger by lazy { Messenger(Handler(thread.looper) { msg -> receive(msg); true }) }

    override fun onCreate() {
        running = this
    }

    override fun onBind(intent: Intent): IBinder = messenger.binder

    override fun onUnbind(intent: Intent): Boolean {
        closeAll()
        return false
    }

    override fun onDestroy() {
        if (running === this) running = null
        closeAll()
        thread.quitSafely()
    }

    private fun closeAll() {
        for (id in gates.keys.toList()) closeGate(id)
    }

    private fun closeGate(id: Int) {
        val owner = owners.remove(id)
        val death = deaths.remove(id)
        if (owner != null && death != null) {
            try {
                owner.unlinkToDeath(death, 0)
            } catch (_: NoSuchElementException) {
                // Never linked (its link failed) or gone with its binder: nothing to unlink.
            }
        }
        gates.remove(id)?.close()
    }

    private fun closeOf(owner: IBinder) {
        for ((id, of) in owners.entries.toList()) if (of == owner) closeGate(id)
    }

    private fun receive(msg: Message) {
        val reply = msg.replyTo ?: return
        val id = msg.data.getInt(ID, -1)
        val ask = msg.data.getLong(ASK, -1)
        val answer = Bundle().apply { putLong(ASK, ask) }
        var opened = -1
        when (msg.what) {
            MODE -> answer.putString(MODE_NAME, mode().name)
            OPEN, OPEN_OBSERVING, OPEN_LOOPBACK -> {
                if (msg.what == OPEN_OBSERVING) {
                    observeRefusal(msg.data.getInt(PID, -1))?.let { why ->
                        answer.putString(FAILED, why)
                        reply.trySend(msg.what, answer)
                        return
                    }
                }
                var gate: HostGate? = null
                val open = try {
                    when (msg.what) {
                        OPEN_OBSERVING -> makeObserving(mode())
                        OPEN_LOOPBACK -> makeLoopbackGate()
                        else -> makeGate(mode())
                    }.also { gate = it }.start()
                } catch (e: Exception) {
                    // A gate that won't listen (no port, a socket refused): said to the asker, never thrown here,
                    // where an uncaught exception would end the main process.
                    gate?.close()
                    null
                }
                if (open == null || gate == null) {
                    answer.putString(FAILED, "the gate couldn't start")
                } else {
                    opened = serial.incrementAndGet()
                    gates[opened] = gate!!
                    val owner = reply.binder
                    owners[opened] = owner
                    try {
                        // An asker of another process that dies has its gates closed with it.
                        val death = IBinder.DeathRecipient { closeOf(owner) }
                        deaths[opened] = death
                        owner.linkToDeath(death, 0)
                    } catch (_: RemoteException) {
                        closeGate(opened)
                    }
                    answer.putInt(ID, opened)
                    answer.putInt(PORT, open.port)
                    answer.putString(PROXY, open.proxyArg)
                }
            }
            LOG -> {
                val gate = gates[id]
                if (gate != null) {
                    val log = gate.log()
                    answer.putStringArrayList(HOSTS, ArrayList(log.keys))
                    for ((host, use) in log) answer.putBundle("host:$host", Bundle().apply {
                        putInt("connects", use.connects)
                        putLong("up", use.bytesUp)
                        putLong("down", use.bytesDown)
                        putInt("refused", use.refused)
                        putBoolean("apart", use.apart)
                        putString("why", use.why)
                    })
                    answer.putBoolean(REFUSED_ANY, gate.refusedAny())
                } else {
                    answer.putString(FAILED, "no such gate")
                }
            }
            CLOSE -> closeGate(id)
            CLOSE_ALL -> closeOf(reply.binder)
            else -> return
        }
        if (answerDelayMs > 0) SystemClock.sleep(answerDelayMs)
        try {
            reply.send(Message.obtain(null, msg.what).apply { data = answer })
        } catch (e: RemoteException) {
            // The asker died between asking and the answer (a DeadObjectException): the gate it would have had is
            // closed now, never left listening until the last unbind; nothing thrown on this thread.
            if (opened > 0) closeGate(opened)
        }
    }

    private fun mode(): HostGate.Mode = modeOf?.invoke() ?: HostGate.Mode.of(System.getProperty(YtDlpClient.NETWORK))

    /** Why an OBSERVE gate isn't opened for the asker of [pid], or null: the bench's own process asks, under the
     * network's mode. */
    private fun observeRefusal(pid: Int): String? {
        val bench = "$packageName$BENCH_PROCESS"
        val name = getSystemService(android.app.ActivityManager::class.java)?.runningAppProcesses
            ?.firstOrNull { it.pid == pid }?.processName
        if (name != bench) return OBSERVE_NOT_BENCH
        if (mode() != HostGate.Mode.NETWORK) return OBSERVE_LOOPBACK
        return null
    }

    private fun Messenger.trySend(what: Int, answer: Bundle) {
        try {
            send(Message.obtain(null, what).apply { data = answer })
        } catch (_: RemoteException) {
        }
    }

    /** How many gates are open now. */
    internal fun openGates(): Int = gates.size

    /** How many death recipients are linked now (one an open gate). */
    internal fun linkedDeaths(): Int = deaths.size

    /** The id of the gate opened last. */
    internal fun newest(): Int = serial.get()

    /** A gate opened in the main process, asked from another: its [port] and [proxyArg] (with its secret: never log
     * it), its [log] and [refusedAny] as [HostGate.Opened]'s. */
    class Gate internal constructor(
        private val client: Client,
        internal val id: Int,
        val port: Int,
        val proxyArg: String,
    ) : Closeable {
        fun log(): Map<String, HostGate.HostUse> = client.log(id).first

        fun refusedAny(): Boolean = client.log(id).second

        override fun close() = client.closeGate(id)

        override fun toString() = "GateService.Gate(127.0.0.1:$port)"
    }

    /** GateService bound from any process of the app; each call blocks for its answer (never on the main thread). */
    class Client(context: Context) : Closeable {
        private val context = context.applicationContext
        private val replies = HandlerThread("caracole-gate-client").apply { start() }
        private val answers = LinkedBlockingQueue<Message>()
        private val asks = AtomicLong()
        private val incoming = Messenger(Handler(replies.looper) { msg ->
            answers.put(Message.obtain(msg))
            true
        })
        private val bound = LinkedBlockingQueue<IBinder>()
        private val connection = object : ServiceConnection {
            override fun onServiceConnected(name: ComponentName, service: IBinder) {
                bound.put(service)
            }

            override fun onServiceDisconnected(name: ComponentName) = Unit
        }
        private val service: Messenger by lazy {
            check(Looper.myLooper() != Looper.getMainLooper()) { "GateService.Client blocks: never on the main thread" }
            if (!context.bindService(Intent(context, GateService::class.java), connection, Context.BIND_AUTO_CREATE)) {
                throw IOException("the gate's service wouldn't bind")
            }
            Messenger(bound.poll(WAIT_S, TimeUnit.SECONDS) ?: throw IOException("the gate's service didn't answer"))
        }

        /** A fresh gate, listening. */
        fun open(): Gate = gate(ask(OPEN, -1))

        /** A fresh OBSERVE gate: every host logged; the bench's alone, its button's (refused otherwise, in words). */
        fun openObserving(): Gate = gate(ask(OPEN_OBSERVING, -1) { putInt(PID, android.os.Process.myPid()) })

        /** A fresh gate of LOOPBACK's mode, whatever the main process's: it reaches 127.0.0.1 alone. */
        fun openLoopback(): Gate = gate(ask(OPEN_LOOPBACK, -1))

        /** The gates' mode, the main process's. */
        fun mode(): HostGate.Mode = HostGate.Mode.valueOf(requireNotNull(ask(MODE, -1).getString(MODE_NAME)))

        private fun gate(answer: Bundle) =
            Gate(this, answer.getInt(ID), answer.getInt(PORT), requireNotNull(answer.getString(PROXY)))

        internal fun log(id: Int): Pair<Map<String, HostGate.HostUse>, Boolean> {
            val answer = ask(LOG, id)
            val log = LinkedHashMap<String, HostGate.HostUse>()
            for (host in answer.getStringArrayList(HOSTS).orEmpty()) {
                val use = answer.getBundle("host:$host") ?: continue
                log[host] = HostGate.HostUse(
                    use.getInt("connects"), use.getLong("up"), use.getLong("down"), use.getInt("refused"),
                    use.getBoolean("apart"), use.getString("why"),
                )
            }
            return log to answer.getBoolean(REFUSED_ANY)
        }

        internal fun closeGate(id: Int) {
            ask(CLOSE, id)
        }

        /** One ask and its own answer: an answer of another (an earlier ask's, late) is passed over. */
        @Synchronized
        private fun ask(what: Int, id: Int, fill: Bundle.() -> Unit = {}): Bundle {
            val ask = asks.incrementAndGet()
            service.send(Message.obtain(null, what).apply {
                replyTo = incoming
                data = Bundle().apply {
                    putInt(ID, id)
                    putLong(ASK, ask)
                    fill()
                }
            })
            val until = SystemClock.elapsedRealtime() + waitMs
            while (true) {
                val left = until - SystemClock.elapsedRealtime()
                val answer = (if (left > 0) answers.poll(left, TimeUnit.MILLISECONDS) else null)
                    ?: throw IOException("the gate's service didn't answer")
                if (answer.what != what || answer.data.getLong(ASK, -1) != ask) continue
                val data = Bundle(answer.data)
                data.getString(FAILED)?.let { throw IOException(it) }
                return data
            }
        }

        /** How long an ask waits for its answer (a test's shorter). */
        internal var waitMs = WAIT_S * 1000

        /** Closes every gate this client opened (one whose answer came too late among them), then lets go of the
         * service. */
        override fun close() {
            try {
                if (asks.get() > 0) ask(CLOSE_ALL, -1)
            } catch (_: IOException) {
                // The service gone or slow: its gates go with it, or at its end.
            }
            try {
                context.unbindService(connection)
            } catch (_: IllegalArgumentException) {
            }
            replies.quitSafely()
        }
    }

    companion object {
        const val OPEN = 1
        const val LOG = 2
        const val CLOSE = 3
        const val CLOSE_ALL = 4
        const val MODE = 5
        const val OPEN_OBSERVING = 6
        const val OPEN_LOOPBACK = 7

        /** The bench's process, after the package's name (the debug app's manifest). */
        const val BENCH_PROCESS = ":ytbench"
        const val OBSERVE_NOT_BENCH = "a gate that observes every host is the YouTube bench's alone"
        const val OBSERVE_LOOPBACK = "a gate that observes every host is never opened under the tests' network"

        private const val ID = "id"
        private const val ASK = "ask"
        private const val FAILED = "failed"
        private const val PORT = "port"
        private const val PROXY = "proxy"
        private const val HOSTS = "hosts"
        private const val REFUSED_ANY = "refusedAny"
        private const val PID = "pid"
        private const val MODE_NAME = "mode"
        private const val WAIT_S = 10L

        /** How a gate is made: a test's seam (a gate that won't start). */
        @Volatile internal var makeGate: (HostGate.Mode) -> HostGate = { mode -> HostGate(mode, HostGate.HostRule.YOUTUBE) }

        /** How the kill check's gate is made: LOOPBACK, 127.0.0.1 alone, whatever this process's mode. */
        @Volatile internal var makeLoopbackGate: () -> HostGate = {
            HostGate(HostGate.Mode.LOOPBACK, HostGate.HostRule.YOUTUBE, loopbackHosts = HostGate.KILL_CHECK_HOSTS)
        }

        /** A test's seam: the gates' mode in place of `caracole.network`'s (null, in production: the property's). A
         * test never clears that property, the guard that keeps every client of its process on loopback. */
        @Volatile internal var modeOf: (() -> HostGate.Mode)? = null

        /** How an OBSERVE gate is made (only once [observeRefusal] passed: the network's mode). */
        private val makeObserving: (HostGate.Mode) -> HostGate = { mode -> HostGate(mode, HostGate.HostRule.OBSERVE) }

        /** A test's seam: each answer held back that long, as a slow main process would. */
        @Volatile internal var answerDelayMs = 0L

        /** The service running in this process, for a test to count its gates. */
        @Volatile internal var running: GateService? = null

        /** How many gates the service in this process has opened (0 for none running): the app's YouTubeBenchTest
         * reads it ([running] being this module's own). */
        val gatesOpened: Int get() = running?.newest() ?: 0
    }
}
