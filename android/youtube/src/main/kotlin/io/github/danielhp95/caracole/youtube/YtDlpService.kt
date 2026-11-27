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
import io.github.danielhp95.caracole.core.youtube.HostGate
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicBoolean

/**
 * One yt-dlp run in the app's `:youtube` process (the phone-youtube design's §3.2), then the process killed: the
 * computer runs a fresh `yt-dlp` each time, and yt-dlp keeps module state. Bound by [YtDlpClient] over a [Messenger]:
 *
 * - it takes one [Wire.RUN] (`run` its id, echoed in every answer; `argv`; `network`), answers [Wire.STARTED] (its pid
 *   and its process's start), then starts Python (Chaquopy's, in this process), makes the environment [Env]'s alone
 *   (the glue's `environ`), and asks the glue's `refusal` (an allowlist: the phone's own argv templates, through
 *   [GlueRules]; the glue's docstring says it): refused, [Wire.REFUSED] in words, never run; else [Wire.READY] and
 *   yt-dlp's run, its streams into [Env.out] and [Env.err], then [Wire.DONE] with its exit status; a failure
 *   [Wire.FAILED], `sent` false when nothing of yt-dlp ran (Python didn't start);
 * - `network` is the main process's mode, exactly `LOOPBACK` or `NETWORK` ([HostGate.Mode]'s names), which the client
 *   sends in each request: this process has no test runner to set it and reads no property; anything else, none
 *   included, is refused;
 * - one request a process, of any client and any instance of this service ([TAKEN], process-wide): a second is
 *   refused and the process dies (a request of a client long gone may still be in it);
 * - it runs nothing once its client let go: before Python starts, before the check and before the run it asks whether
 *   it is still bound, and if not, ends;
 * - once it has answered, it sweeps TMPDIR ([Env.sweep]), waits for its client to unbind (at most [UNBIND_WAIT_MS])
 *   and kills its own process (`Process.killProcess(myPid())`); let go of before any request, at once.
 *
 * No argv crosses into a log, an exception or an answer: the proxy's holds the gate's secret. What it logs is what
 * happened, in its own words.
 */
class YtDlpService : Service() {
    private val thread = HandlerThread("caracole-ytdlp").apply { start() }
    private val unbound = CountDownLatch(1)
    @Volatile private var bound = false
    private val messenger by lazy { Messenger(Handler(thread.looper) { msg -> receive(msg); true }) }

    override fun onBind(intent: Intent): IBinder {
        bound = true
        return messenger.binder
    }

    override fun onUnbind(intent: Intent): Boolean {
        bound = false
        unbound.countDown()
        // Let go of before any request (a client stopped before it sent one): nothing to wait for.
        if (!TAKEN.get()) die()
        return false
    }

    override fun onDestroy() {
        bound = false
        if (!TAKEN.get()) die()
    }

    private fun receive(msg: Message) {
        if (msg.what != Wire.RUN) return
        val reply = msg.replyTo ?: return
        val data = Bundle(msg.data)
        val run = data.getLong(Wire.RUN_ID)
        if (!TAKEN.compareAndSet(false, true)) {
            answer(reply, run, Wire.REFUSED) { putString(Wire.WORDS, ONE_RUN) }
            Log.w(TAG, "a second request in one :youtube process: refused, the process ends")
            die()
            return
        }
        Thread({ runOnce(reply, run, data) }, "caracole-ytdlp-run").start()
    }

    private fun runOnce(reply: Messenger, run: Long, data: Bundle) {
        try {
            val network = data.getString(Wire.NETWORK)
            val mode = HostGate.Mode.entries.firstOrNull { it.name == network }
            // The tests' seam (KillTest), under LOOPBACK alone: STARTED held back, as a slow process start would.
            val delay = data.getLong(Wire.DELAY_STARTED, 0)
            if (mode == HostGate.Mode.LOOPBACK && delay > 0) SystemClock.sleep(delay)
            answer(reply, run, Wire.STARTED) {
                putInt(Wire.PID, Process.myPid())
                putLong(Wire.AT, Process.getStartElapsedRealtime())
            }
            val argv = data.getStringArray(Wire.ARGV)
            if (argv == null || mode == null) {
                answer(reply, run, Wire.REFUSED) { putString(Wire.WORDS, if (argv == null) NO_ARGV else BAD_MODE) }
                return
            }
            if (!bound) return
            val glue = try {
                if (!Python.isStarted()) Python.start(AndroidPlatform(this))
                Python.getInstance().getModule("caracole_ytdlp")
            } catch (e: Throwable) {
                Log.e(TAG, "Python didn't start: ${e.javaClass.name}")
                answer(reply, run, Wire.FAILED) {
                    putString(Wire.WORDS, "Python didn't start (${e.javaClass.simpleName})")
                    putBoolean(Wire.SENT, false)
                }
                return
            }
            if (!bound) return
            val env = Env.prepare(this)
            val had = glue.callAttr("environ", env.keys.toTypedArray(), env.values.toTypedArray()).asList()
            Log.i(TAG, "the environment made Env's alone; the process had ${had.joinToString(" ")}")
            val roots = listOf(filesDir, cacheDir).map { it.canonicalPath }
            val rules = GlueRules.of(mode, Qjs.path(this).path, roots)
            val why = glue.callAttr("refusal", argv, rules)?.toString()
            answer(reply, run, Wire.READY) { putLong(Wire.AT, SystemClock.elapsedRealtime()) }
            if (why != null) {
                Log.i(TAG, "refused a run: $why")
                answer(reply, run, Wire.REFUSED) { putString(Wire.WORDS, why) }
                return
            }
            if (!bound) return
            Env.runs(this).mkdirs()
            val exit = try {
                glue.callAttr("run", argv, Env.out(this).path, Env.err(this).path).toInt()
            } catch (e: Throwable) {
                // run raises only what isn't an Exception (a KeyboardInterrupt), or when its files won't open.
                Log.e(TAG, "yt-dlp's run raised ${e.javaClass.name}")
                answer(reply, run, Wire.FAILED) {
                    putString(Wire.WORDS, "yt-dlp's run raised (${e.javaClass.simpleName})")
                    putBoolean(Wire.SENT, true)
                }
                return
            }
            Log.i(TAG, "yt-dlp's run ended with status $exit")
            answer(reply, run, Wire.DONE) { putInt(Wire.EXIT, exit) }
        } catch (e: Throwable) {
            Log.e(TAG, "the run failed: ${e.javaClass.name}")
            answer(reply, run, Wire.FAILED) {
                putString(Wire.WORDS, "the run failed (${e.javaClass.simpleName})")
                putBoolean(Wire.SENT, true)
            }
        } finally {
            Env.sweep(this)
            if (bound) unbound.await(UNBIND_WAIT_MS, TimeUnit.MILLISECONDS)
            die()
        }
    }

    private fun die() {
        Process.killProcess(Process.myPid())
    }

    private fun answer(reply: Messenger, run: Long, what: Int, fill: Bundle.() -> Unit) {
        try {
            reply.send(Message.obtain(null, what).apply {
                data = Bundle().apply {
                    putLong(Wire.RUN_ID, run)
                    fill()
                }
            })
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

        const val RUN_ID = "run"
        const val ARGV = "argv"
        const val NETWORK = "network"
        const val DELAY_STARTED = "delayStarted"
        const val PID = "pid"
        const val AT = "at"
        const val WORDS = "words"
        const val EXIT = "exit"
        const val SENT = "sent"
    }

    companion object {
        private const val TAG = "caracole-ytdlp"

        /** Whether this process has taken its one request, whichever instance of the service took it. */
        private val TAKEN = AtomicBoolean()

        /** How long it waits for its client to let go after answering, before it kills its process anyway. */
        const val UNBIND_WAIT_MS = 5_000L

        const val ONE_RUN = "this :youtube process has taken a request already"
        const val NO_ARGV = "a request names its argv"
        const val BAD_MODE = "a request names its network mode, LOOPBACK or NETWORK"
    }
}
