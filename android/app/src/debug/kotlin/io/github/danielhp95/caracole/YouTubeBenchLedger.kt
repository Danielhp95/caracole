package io.github.danielhp95.caracole

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
import io.github.danielhp95.caracole.youtube.BenchRun
import io.github.danielhp95.caracole.youtube.DbLedger
import java.io.Closeable
import java.io.IOException
import java.time.Instant
import java.util.concurrent.LinkedBlockingQueue
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicLong

/**
 * The YouTube bench's record of runs, in the app's main process (no `android:process`), where the phone's database,
 * server and queue are: the bench's `:ytbench` asks it [STATE] (DbLedger's, with the server's requests served and the
 * queue's jobs for `idle`) and [RECORD] (one run's `events` row, kv `http:last_request:youtube` and `ytbench:runs`,
 * a block's strike), each in one read or write of the phone's database. The debug build's alone. Nothing it is asked
 * throws on its thread (the main process's server and queue would end with it): a failure is said in the answer.
 */
class YouTubeBenchLedger : Service() {
    private val thread = HandlerThread("caracole-ytbench-ledger").apply { start() }
    private val messenger by lazy { Messenger(Handler(thread.looper) { msg -> receive(msg); true }) }

    override fun onBind(intent: Intent): IBinder = messenger.binder

    override fun onDestroy() {
        thread.quitSafely()
    }

    private fun receive(msg: Message) {
        val reply = msg.replyTo ?: return
        val data = Bundle(msg.data)
        val answer = Bundle().apply { putLong(ASK, data.getLong(ASK)) }
        try {
            val phone = Caracole.phone(applicationContext)
            val database = phone.parts.database
            when (msg.what) {
                STATE -> {
                    val jobs = phone.queue.snapshot()
                    val state = database.read { db ->
                        DbLedger.state(db, Instant.now(), phone.server.served, jobs.maxOfOrNull { it.id.toLong() } ?: 0,
                                       phone.queue.activeCount() > 0)
                    }
                    answer.putBoolean("enabled", state.enabled)
                    answer.putInt("budget", state.budget)
                    answer.putDouble("delayLow", state.delay.first)
                    answer.putDouble("delayHigh", state.delay.second)
                    answer.putInt("runs", state.runs)
                    answer.putString("cooling", state.cooling)
                    state.lastSent?.let { answer.putDouble("lastSent", it) }
                    answer.putLong("served", state.served)
                    answer.putLong("jobs", state.jobs)
                    answer.putBoolean("running", state.running)
                }
                RECORD -> {
                    val entry = BenchRun.Entry(data.getString("runId")!!, data.getString("target")!!,
                        data.getInt("status", -1).takeIf { it >= 0 }, data.getString("decision")!!,
                        data.getString("message"), data.getBoolean("blocked"))
                    val start = Instant.ofEpochMilli(data.getLong("sessionStart"))
                    database.writeBlocking { db ->
                        DbLedger.record(db, entry, Instant.now(), System.currentTimeMillis() / 1000.0, start)
                    }
                }
                else -> return
            }
        } catch (e: Exception) {
            answer.putString(FAILED, "the phone's record of runs can't be read or written (${e.javaClass.simpleName})")
        }
        try {
            reply.send(Message.obtain(null, msg.what).apply { this.data = answer })
        } catch (_: RemoteException) {
            // The bench gone: nothing to tell.
        }
    }

    /** The ledger from `:ytbench`: each ask blocks for its own answer (never on the main thread). */
    class Client(context: Context) : BenchRun.Ledger, Closeable {
        private val context = context.applicationContext
        private val replies = HandlerThread("caracole-ytbench-ledger-client").apply { start() }
        private val answers = LinkedBlockingQueue<Message>()
        private val asks = AtomicLong()
        private val incoming = Messenger(Handler(replies.looper) { msg -> answers.put(Message.obtain(msg)); true })
        private val bound = LinkedBlockingQueue<IBinder>()
        private val connection = object : ServiceConnection {
            override fun onServiceConnected(name: ComponentName, service: IBinder) {
                bound.put(service)
            }

            override fun onServiceDisconnected(name: ComponentName) = Unit
        }
        private val service: Messenger by lazy {
            check(Looper.myLooper() != Looper.getMainLooper()) { "the ledger's client blocks: never on the main thread" }
            if (!context.bindService(Intent(context, YouTubeBenchLedger::class.java), connection,
                                     Context.BIND_AUTO_CREATE)) throw IOException("the bench's ledger wouldn't bind")
            Messenger(bound.poll(WAIT_S, TimeUnit.SECONDS) ?: throw IOException("the bench's ledger didn't answer"))
        }

        override fun state(): BenchRun.State {
            val a = ask(STATE, Bundle())
            return BenchRun.State(a.getBoolean("enabled"), a.getInt("budget"),
                a.getDouble("delayLow") to a.getDouble("delayHigh"), a.getInt("runs"), a.getString("cooling"),
                if (a.containsKey("lastSent")) a.getDouble("lastSent") else null, a.getLong("served"), a.getLong("jobs"),
                a.getBoolean("running"))
        }

        override fun record(entry: BenchRun.Entry, sessionStart: Instant) {
            ask(RECORD, Bundle().apply {
                putString("runId", entry.runId)
                putString("target", entry.target)
                putInt("status", entry.status ?: -1)
                putString("decision", entry.decision)
                putString("message", entry.message)
                putBoolean("blocked", entry.blocked)
                putLong("sessionStart", sessionStart.toEpochMilli())
            })
        }

        @Synchronized
        private fun ask(what: Int, data: Bundle): Bundle {
            val ask = asks.incrementAndGet()
            service.send(Message.obtain(null, what).apply {
                replyTo = incoming
                this.data = data.apply { putLong(ASK, ask) }
            })
            val until = SystemClock.elapsedRealtime() + WAIT_S * 1000
            while (true) {
                val left = until - SystemClock.elapsedRealtime()
                val answer = (if (left > 0) answers.poll(left, TimeUnit.MILLISECONDS) else null)
                    ?: throw IOException("the bench's ledger didn't answer")
                if (answer.what != what || answer.data.getLong(ASK, -1) != ask) continue
                val got = Bundle(answer.data)
                got.getString(FAILED)?.let { throw IOException(it) }
                return got
            }
        }

        override fun close() {
            try {
                context.unbindService(connection)
            } catch (_: IllegalArgumentException) {
            }
            replies.quitSafely()
        }
    }

    companion object {
        const val STATE = 1
        const val RECORD = 2
        private const val ASK = "ask"
        private const val FAILED = "failed"
        private const val WAIT_S = 30L
    }
}
