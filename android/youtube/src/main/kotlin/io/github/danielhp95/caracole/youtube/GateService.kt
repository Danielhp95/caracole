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
import io.github.danielhp95.caracole.core.youtube.HostGate
import java.io.Closeable
import java.io.IOException
import java.util.concurrent.ConcurrentHashMap
import java.util.concurrent.LinkedBlockingQueue
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicInteger

/**
 * The app's gate for another process of the app (the phone-youtube design's §3.3): a [HostGate] runs in the main process
 * alone, where this service is, so a process that runs yt-dlp's argv from elsewhere (the bench's `:ytbench`) asks it
 * here for one, then for its log. Its mode is decided here, in the main process, from `caracole.network` (the test
 * runner's, [HostGate.Mode.of]): `loopback` under the test runners, the network otherwise, given to the gate's
 * constructor (the gate reads no property); its rule YOUTUBE's.
 *
 * Over a [Messenger]: [OPEN] starts a gate and answers its id, port and `proxyArg` (which holds its secret, carried in
 * the answer alone, never logged); [LOG] answers a gate's [HostGate.log] and [HostGate.refusedAny]; [CLOSE] closes one;
 * every gate is closed once no client is bound. [Client] is that from the other side.
 */
class GateService : Service() {
    private val thread = HandlerThread("caracole-gate-service").apply { start() }
    private val gates = ConcurrentHashMap<Int, HostGate>()
    private val serial = AtomicInteger()
    private val messenger by lazy { Messenger(Handler(thread.looper) { msg -> receive(msg); true }) }

    override fun onBind(intent: Intent): IBinder = messenger.binder

    override fun onUnbind(intent: Intent): Boolean {
        closeAll()
        return false
    }

    override fun onDestroy() {
        closeAll()
        thread.quitSafely()
    }

    private fun closeAll() {
        for (id in gates.keys.toList()) gates.remove(id)?.close()
    }

    private fun receive(msg: Message) {
        val reply = msg.replyTo ?: return
        val id = msg.data.getInt(ID, -1)
        val answer = Bundle()
        when (msg.what) {
            OPEN -> {
                val gate = HostGate(HostGate.Mode.of(System.getProperty(YtDlpClient.NETWORK)), HostGate.HostRule.YOUTUBE)
                val open = gate.start()
                val n = serial.incrementAndGet()
                gates[n] = gate
                answer.putInt(ID, n)
                answer.putInt(PORT, open.port)
                answer.putString(PROXY, open.proxyArg)
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
                }
            }
            CLOSE -> {
                gates.remove(id)?.close()
            }
            else -> return
        }
        reply.send(Message.obtain(null, msg.what).apply { data = answer })
    }

    /** A gate opened in the main process, asked from another: its [port] and [proxyArg] (with its secret: never log
     * it), its [log] and [refusedAny] as [HostGate.Opened]'s. */
    class Gate internal constructor(private val client: Client, private val id: Int, val port: Int, val proxyArg: String) :
        Closeable {
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
        fun open(): Gate {
            val answer = ask(OPEN, -1)
            return Gate(this, answer.getInt(ID), answer.getInt(PORT), requireNotNull(answer.getString(PROXY)))
        }

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

        @Synchronized
        private fun ask(what: Int, id: Int): Bundle {
            answers.clear()
            service.send(Message.obtain(null, what).apply {
                replyTo = incoming
                data = Bundle().apply { putInt(ID, id) }
            })
            val answer = answers.poll(WAIT_S, TimeUnit.SECONDS) ?: throw IOException("the gate's service didn't answer")
            return Bundle(answer.data)
        }

        /** Lets go of the service, which closes every gate it opened once no client is bound. */
        override fun close() {
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

        private const val ID = "id"
        private const val PORT = "port"
        private const val PROXY = "proxy"
        private const val HOSTS = "hosts"
        private const val REFUSED_ANY = "refusedAny"
        private const val WAIT_S = 10L
    }
}
