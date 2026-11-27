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
import java.io.Closeable
import java.util.concurrent.LinkedBlockingQueue
import java.util.concurrent.TimeUnit

/**
 * [YtDlpService] bound by hand, its wire's messages sent as a test writes them ([YtDlpService.Wire]): what YtDlpClient
 * never sends (no mode, another mode, two requests on one binding, a request let go of at once).
 */
class RawService : Closeable {
    private val replies = HandlerThread("raw-ytdlp").apply { start() }
    val answers = LinkedBlockingQueue<Pair<Int, Bundle>>()
    private val incoming = Messenger(Handler(replies.looper) { msg -> answers.put(msg.what to Bundle(msg.data)); true })
    private val bound = LinkedBlockingQueue<IBinder>()
    private val connection = object : ServiceConnection {
        override fun onServiceConnected(name: ComponentName, service: IBinder) {
            bound.put(service)
        }

        override fun onServiceDisconnected(name: ComponentName) = Unit
    }
    private var unbound = false
    private val service: Messenger

    init {
        val context = Runs.context
        check(context.bindService(Intent(context, YtDlpService::class.java), connection,
                                  Context.BIND_AUTO_CREATE or Context.BIND_IMPORTANT))
        service = Messenger(checkNotNull(bound.poll(30, TimeUnit.SECONDS)) { "YtDlpService didn't bind" })
    }

    /** A RUN of [fill]'s fields, run id [run]. */
    fun send(run: Long, fill: Bundle.() -> Unit) {
        service.send(Message.obtain(null, YtDlpService.Wire.RUN).apply {
            replyTo = incoming
            data = Bundle().apply {
                putLong(YtDlpService.Wire.RUN_ID, run)
                fill()
            }
        })
    }

    /** The next answer of [what] within [s] seconds, the others passed over; null for none. */
    fun next(what: Int, s: Long = 60): Bundle? {
        val until = System.currentTimeMillis() + s * 1000
        while (true) {
            val left = until - System.currentTimeMillis()
            if (left <= 0) return null
            val (got, data) = answers.poll(left, TimeUnit.MILLISECONDS) ?: return null
            if (got == what) return data
        }
    }

    fun unbind() {
        if (!unbound) Runs.context.unbindService(connection)
        unbound = true
    }

    override fun close() {
        unbind()
        replies.quitSafely()
    }
}
