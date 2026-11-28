package io.github.danielhp95.caracole.youtube

import android.app.Service
import android.content.Intent
import android.os.Bundle
import android.os.Handler
import android.os.HandlerThread
import android.os.IBinder
import android.os.Message
import android.os.Messenger
import io.github.danielhp95.caracole.core.youtube.HostGate
import java.io.File
import java.io.IOException

/**
 * A [YtDlpClient] in a process of the app's other than the test's (":other", the test APK's manifest), driven over a
 * Messenger: [RUN] runs `argv` (under the mode `mode` names, sent from the test's process as the bench's gate says
 * it), answering [RAN] once it ends (`exit`, `killed`, or `error`: the words of what it threw); [CANCEL] stops it.
 */
class OtherProcessRuns : Service() {
    private val thread = HandlerThread("other-process-runs").apply { start() }
    @Volatile private var client: YtDlpClient? = null

    private val messenger by lazy {
        Messenger(Handler(thread.looper) { msg ->
            val reply = msg.replyTo
            when (msg.what) {
                RUN -> {
                    val data = Bundle(msg.data)
                    val mode = HostGate.Mode.valueOf(data.getString(MODE)!!)
                    val made = YtDlpClient(this, mode).also { client = it }
                    Thread {
                        val answer = Bundle()
                        try {
                            val argv = data.getStringArray(ARGV)!!.toList()
                            val ran = made.run(argv, 120.0, { _, _ -> }, {},
                                RunFolders(data.getString(CACHE)?.let(::File), data.getString(INTO)?.let(::File)))
                            answer.putInt(EXIT, ran.exit)
                            answer.putBoolean(KILLED, ran.killed)
                        } catch (e: IOException) {
                            answer.putString(ERROR, e.message)
                        }
                        made.close()
                        reply?.send(Message.obtain(null, RAN).apply { this.data = answer })
                    }.start()
                }
                CANCEL -> client?.cancel()
            }
            true
        })
    }

    override fun onBind(intent: Intent): IBinder = messenger.binder

    companion object {
        const val RUN = 1
        const val CANCEL = 2
        const val RAN = 3
        const val ARGV = "argv"
        const val MODE = "mode"
        const val CACHE = "cache"
        const val INTO = "into"
        const val EXIT = "exit"
        const val KILLED = "killed"
        const val ERROR = "error"
    }
}
