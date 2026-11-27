package io.github.danielhp95.caracole.youtube

import android.app.Service
import android.content.Intent
import android.os.Bundle
import android.os.Handler
import android.os.HandlerThread
import android.os.IBinder
import android.os.Message
import android.os.Messenger
import android.os.Process
import android.os.RemoteException
import android.os.SystemClock
import android.util.Log
import com.chaquo.python.Python
import com.chaquo.python.android.AndroidPlatform
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicBoolean

/**
 * One yt-dlp run in the app's `:youtube` process (the phone-youtube design's §3.2), then the process killed: the
 * computer runs a fresh `yt-dlp` each time, and yt-dlp keeps module state. Bound by [YtDlpClient] over a [Messenger]:
 *
 * - it takes one [Wire.RUN] (`argv`, `network`), answers [Wire.STARTED] (its pid and its process's start), then starts
 *   Python (Chaquopy's, in this process), makes the environment [Env]'s alone (the glue's `environ`), and asks the
 *   glue's `refusal`: an argv whose `--proxy` isn't a gate's (`http://user:secret@127.0.0.1:port`), and under
 *   `network` `loopback` a target that isn't a loopback address (the glue's docstring says each), is [Wire.REFUSED] in
 *   words, never run; else [Wire.READY] and yt-dlp's run, its streams into [Env.out] and [Env.err], then
 *   [Wire.DONE] with its exit status; a failure to start Python or to open those files [Wire.FAILED];
 * - `network` is the main process's `caracole.network`, which the client sends in each request: this process has no
 *   instrumentation runner to set it, and reads no property; a request without it is refused;
 * - a second request, of any client, is refused: one run a process;
 * - once it has answered, it sweeps TMPDIR ([Env.sweep]), waits for its client to unbind (at most [UNBIND_WAIT_MS])
 *   and kills its own process (`Process.killProcess(myPid())`); let go of before any request, at once.
 *
 * No argv crosses into a log, an exception or an answer: the proxy's holds the gate's secret. What it logs is what
 * happened, in its own words.
 */
class YtDlpService : Service() {
    private val thread = HandlerThread("caracole-ytdlp").apply { start() }
    private val taken = AtomicBoolean()
    private val unbound = CountDownLatch(1)
    private val messenger by lazy { Messenger(Handler(thread.looper) { msg -> receive(msg); true }) }

    override fun onBind(intent: Intent): IBinder = messenger.binder

    override fun onUnbind(intent: Intent): Boolean {
        unbound.countDown()
        // Let go of before any request (a client stopped before it sent one): nothing to wait for.
        if (!taken.get()) Process.killProcess(Process.myPid())
        return false
    }

    override fun onDestroy() {
        // Destroyed with no run taken (its client gone before binding it): no process is left for nothing.
        if (!taken.get()) Process.killProcess(Process.myPid())
    }

    private fun receive(msg: Message) {
        if (msg.what != Wire.RUN) return
        val reply = msg.replyTo ?: return
        val data = Bundle(msg.data)
        if (!taken.compareAndSet(false, true)) {
            answer(reply, Wire.REFUSED) { putString(Wire.WORDS, ONE_RUN) }
            return
        }
        Thread({ runOnce(reply, data) }, "caracole-ytdlp-run").start()
    }

    private fun runOnce(reply: Messenger, data: Bundle) {
        try {
            answer(reply, Wire.STARTED) {
                putInt(Wire.PID, Process.myPid())
                putLong(Wire.AT, Process.getStartElapsedRealtime())
            }
            val argv = data.getStringArray(Wire.ARGV)
            val network = data.getString(Wire.NETWORK)
            if (argv == null || network == null) {
                answer(reply, Wire.REFUSED) { putString(Wire.WORDS, NO_MODE) }
                return
            }
            val glue = try {
                if (!Python.isStarted()) Python.start(AndroidPlatform(this))
                Python.getInstance().getModule("caracole_ytdlp")
            } catch (e: Throwable) {
                Log.e(TAG, "Python didn't start: ${e.javaClass.name}")
                answer(reply, Wire.FAILED) { putString(Wire.WORDS, "Python didn't start (${e.javaClass.simpleName})") }
                return
            }
            val env = Env.prepare(this)
            val had = glue.callAttr("environ", env.keys.toTypedArray(), env.values.toTypedArray()).asList()
            Log.i(TAG, "the environment made Env's alone; the process had ${had.joinToString(" ")}")
            val why = glue.callAttr("refusal", argv, network == LOOPBACK, Qjs.path(this).path)?.toString()
            answer(reply, Wire.READY) { putLong(Wire.AT, SystemClock.elapsedRealtime()) }
            if (why != null) {
                Log.i(TAG, "refused a run: $why")
                answer(reply, Wire.REFUSED) { putString(Wire.WORDS, why) }
                return
            }
            val runs = Env.runs(this).apply { mkdirs() }
            check(runs.isDirectory) { "no folder for the run's output" }
            val exit = try {
                glue.callAttr("run", argv, Env.out(this).path, Env.err(this).path).toInt()
            } catch (e: Throwable) {
                // run raises only what isn't an Exception (a KeyboardInterrupt), or when its files won't open.
                Log.e(TAG, "yt-dlp's run raised ${e.javaClass.name}")
                answer(reply, Wire.FAILED) { putString(Wire.WORDS, "yt-dlp's run raised (${e.javaClass.simpleName})") }
                return
            }
            Log.i(TAG, "yt-dlp's run ended with status $exit")
            answer(reply, Wire.DONE) { putInt(Wire.EXIT, exit) }
        } catch (e: Throwable) {
            Log.e(TAG, "the run failed: ${e.javaClass.name}")
            answer(reply, Wire.FAILED) { putString(Wire.WORDS, "the run failed (${e.javaClass.simpleName})") }
        } finally {
            Env.sweep(this)
            unbound.await(UNBIND_WAIT_MS, TimeUnit.MILLISECONDS)
            Process.killProcess(Process.myPid())
        }
    }

    private fun answer(reply: Messenger, what: Int, fill: Bundle.() -> Unit) {
        try {
            reply.send(Message.obtain(null, what).apply { data = Bundle().apply(fill) })
        } catch (_: RemoteException) {
            // The client is gone: nothing to tell; the process ends all the same.
        }
    }

    /** What the client and the service say to each other over their Messengers. */
    internal object Wire {
        const val RUN = 1
        const val STARTED = 2
        const val READY = 3
        const val REFUSED = 4
        const val DONE = 5
        const val FAILED = 6

        const val ARGV = "argv"
        const val NETWORK = "network"
        const val PID = "pid"
        const val AT = "at"
        const val WORDS = "words"
        const val EXIT = "exit"
    }

    companion object {
        private const val TAG = "caracole-ytdlp"

        /** The main process's `caracole.network` under the test runners (CaracoleTestRunner, YoutubeTestRunner). */
        const val LOOPBACK = "loopback"

        /** How long it waits for its client to let go after answering, before it kills its process anyway. */
        const val UNBIND_WAIT_MS = 5_000L

        const val ONE_RUN = "this :youtube process has run yt-dlp once already"
        const val NO_MODE = "a request names its argv and its network mode"
    }
}
