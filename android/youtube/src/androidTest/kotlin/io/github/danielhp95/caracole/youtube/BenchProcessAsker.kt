package io.github.danielhp95.caracole.youtube

import android.app.Service
import android.content.Intent
import android.os.Bundle
import android.os.Handler
import android.os.HandlerThread
import android.os.IBinder
import android.os.Message
import android.os.Messenger

/**
 * A process of the test APK's named as the bench's (`:ytbench`), so that GateServiceTest asks GateService for an
 * observing gate from the bench's own process: any message is answered with what the ask came to, `opened` or the
 * refusal's words (`refused`).
 */
class BenchProcessAsker : Service() {
    private val thread = HandlerThread("bench-process-asker").apply { start() }
    private val messenger by lazy {
        Messenger(Handler(thread.looper) { msg ->
            val reply = msg.replyTo
            Thread {
                val answer = Bundle()
                GateService.Client(this).use { gates ->
                    try {
                        gates.openObserving().close()
                        answer.putBoolean("opened", true)
                    } catch (e: java.io.IOException) {
                        answer.putString("refused", e.message)
                    }
                }
                reply?.send(Message.obtain(null, 1).apply { data = answer })
            }.start()
            true
        })
    }

    override fun onBind(intent: Intent): IBinder = messenger.binder
}
