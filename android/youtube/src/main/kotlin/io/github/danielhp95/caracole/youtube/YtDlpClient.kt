package io.github.danielhp95.caracole.youtube

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
import android.os.Process
import android.os.RemoteException
import android.os.SystemClock
import java.io.Closeable
import java.io.File
import java.io.IOException
import java.io.RandomAccessFile
import java.util.concurrent.LinkedBlockingQueue
import java.util.concurrent.Semaphore
import java.util.concurrent.TimeUnit

/**
 * What a run in `:youtube` gave: yt-dlp's exit status, its stdout, the end of its stderr (its last [STDERR_TAIL]
 * characters), whether the client [killed] it (a timeout, a cancel, a close: then [exit] is -1 and the rest is what it
 * wrote until then), and how long, from the client's bind, the `:youtube` process took to start ([processStartMs]) and
 * Python to be ready with yt-dlp imported and the argv checked ([pythonReadyMs]; -1 if it never was).
 */
data class Ran(
    val exit: Int,
    val stdout: String,
    val stderrTail: String,
    val killed: Boolean,
    val processStartMs: Long,
    val pythonReadyMs: Long,
) {
    companion object {
        const val STDERR_TAIL = 64 * 1024
    }
}

/** The `:youtube` process died before its run's answer, unasked (the phone may have run out of memory), or never
 * started. No block, no miss: an error. [words] never hold the argv. */
class YtDlpStopped(val words: String) : IOException(words)

/** The service won't run this argv ([YtDlpService]'s refusals, the glue's words): nothing was run, nothing asked. */
class Refused(val words: String) : IOException(words)

/**
 * The main process's side of a yt-dlp run in `:youtube` ([YtDlpService]): [run] binds the service
 * (`BIND_AUTO_CREATE | BIND_IMPORTANT`), so a fresh process starts, sends it the argv and this process's
 * `caracole.network` (the mode travels in the request: the `:youtube` process has no test runner to set it), follows
 * its stderr line by line as yt-dlp writes it ([Env.err]), and once it is answered, or [killed][Ran.killed], lets go
 * and waits until that process is gone, so each run is a process of its own.
 *
 * - One run at a time, of every client of this process: a run that must wait for another tells `waiting` once.
 * - A stop: past `timeoutS` from the bind, on [cancel] (any thread) or on [close], it kills the `:youtube` process
 *   (`Process.killProcess` of its pid: Android's ActivityManager then kills that process's cgroup, the children yt-dlp
 *   started, qjs among them, with it; KillTest measures it).
 * - The process gone before its answer, unasked: [YtDlpStopped]. A refusal: [Refused].
 * - [run] blocks; never on the main thread, whose looper delivers the binding.
 *
 * It logs nothing of the argv, whose `--proxy` holds the gate's secret.
 */
class YtDlpClient(context: Context) : Closeable {
    private val context = context.applicationContext
    private val replies = HandlerThread("caracole-ytdlp-client").apply { start() }
    private val events = LinkedBlockingQueue<Event>()
    @Volatile private var stopped = false
    @Volatile private var closed = false

    private sealed interface Event {
        data class Connected(val binder: IBinder) : Event
        data object Died : Event
        data object Stop : Event
        data class Said(val what: Int, val data: Bundle) : Event
    }

    private val incoming = Messenger(Handler(replies.looper) { msg ->
        events.put(Event.Said(msg.what, Bundle(msg.data)))
        true
    })

    /**
     * yt-dlp run once with [argv] (its arguments, no program name; its `--proxy` the gate's), stopped once it has run
     * [timeoutS] seconds; each line of its stderr goes to [onLine] with the milliseconds since the bind, as it comes.
     */
    fun run(argv: List<String>, timeoutS: Double, onLine: (Long, String) -> Unit, waiting: () -> Unit): Ran {
        check(Looper.myLooper() != Looper.getMainLooper()) { "YtDlpClient.run blocks: never on the main thread" }
        check(!closed) { "this YtDlpClient is closed" }
        if (!ONE_AT_A_TIME.tryAcquire()) {
            waiting()
            ONE_AT_A_TIME.acquire()
        }
        try {
            return runAlone(argv, timeoutS, onLine)
        } finally {
            ONE_AT_A_TIME.release()
        }
    }

    /** Stops the run under way, if any: its process killed, [run] returning it [killed][Ran.killed]. */
    fun cancel() {
        stopped = true
        events.put(Event.Stop)
    }

    /** [cancel], and no run after. */
    override fun close() {
        closed = true
        cancel()
        replies.quitSafely()
    }

    private fun runAlone(argv: List<String>, timeoutS: Double, onLine: (Long, String) -> Unit): Ran {
        events.clear()
        stopped = false
        val out = Env.out(context)
        val err = Env.err(context)
        Env.runs(context).mkdirs()
        out.delete()
        err.delete()
        val t0 = SystemClock.elapsedRealtime()
        val deadline = t0 + (timeoutS * 1000).toLong()
        var binder: IBinder? = null
        val death = IBinder.DeathRecipient { events.put(Event.Died) }
        val connection = object : ServiceConnection {
            override fun onServiceConnected(name: ComponentName, service: IBinder) {
                events.put(Event.Connected(service))
            }

            override fun onServiceDisconnected(name: ComponentName) {
                events.put(Event.Died)
            }

            override fun onBindingDied(name: ComponentName) {
                events.put(Event.Died)
            }

            override fun onNullBinding(name: ComponentName) {
                events.put(Event.Died)
            }
        }
        val intent = Intent(context, YtDlpService::class.java)
        if (!context.bindService(intent, connection, Context.BIND_AUTO_CREATE or Context.BIND_IMPORTANT)) {
            context.unbindService(connection)
            throw YtDlpStopped(NOT_STARTED)
        }
        val tail = Tail(err, t0, onLine)
        var pid = -1
        var started = -1L
        var ready = -1L
        var exit: Int? = null
        var killed = false
        try {
            while (exit == null) {
                tail.read()
                val now = SystemClock.elapsedRealtime()
                if (stopped || now >= deadline) {
                    killed = true
                    break
                }
                when (val event = events.poll(minOf(POLL_MS, deadline - now), TimeUnit.MILLISECONDS)) {
                    null, Event.Stop -> Unit
                    is Event.Connected -> {
                        binder = event.binder.also { it.linkToDeath(death, 0) }
                        val request = Message.obtain(null, YtDlpService.Wire.RUN).apply {
                            replyTo = incoming
                            data = Bundle().apply {
                                putStringArray(YtDlpService.Wire.ARGV, argv.toTypedArray())
                                putString(YtDlpService.Wire.NETWORK, System.getProperty(NETWORK).orEmpty())
                            }
                        }
                        try {
                            Messenger(event.binder).send(request)
                        } catch (_: RemoteException) {
                            events.put(Event.Died)
                        }
                    }
                    Event.Died -> throw YtDlpStopped(STOPPED)
                    is Event.Said -> when (event.what) {
                        YtDlpService.Wire.STARTED -> {
                            pid = event.data.getInt(YtDlpService.Wire.PID, -1)
                            started = event.data.getLong(YtDlpService.Wire.AT, -1)
                        }
                        YtDlpService.Wire.READY -> ready = event.data.getLong(YtDlpService.Wire.AT, -1)
                        YtDlpService.Wire.REFUSED ->
                            throw Refused(event.data.getString(YtDlpService.Wire.WORDS) ?: "refused")
                        YtDlpService.Wire.FAILED ->
                            throw YtDlpStopped(event.data.getString(YtDlpService.Wire.WORDS) ?: STOPPED)
                        YtDlpService.Wire.DONE -> exit = event.data.getInt(YtDlpService.Wire.EXIT)
                    }
                }
            }
            if (killed && pid > 0) Process.killProcess(pid)
            tail.read()
            tail.end()
            return Ran(
                exit = if (killed) -1 else exit!!,
                stdout = read(out),
                stderrTail = tail.last(),
                killed = killed,
                processStartMs = if (started >= 0) started - t0 else -1,
                pythonReadyMs = if (ready >= 0) ready - t0 else -1,
            )
        } finally {
            binder?.unlinkToDeath(death, 0)
            try {
                context.unbindService(connection)
            } catch (_: IllegalArgumentException) {
            }
            gone(pid)
            out.delete()
            err.delete()
        }
    }

    /** Waits for the `:youtube` process [pid] to be gone (it kills itself once unbound), killing it past
     * [GONE_WAIT_MS], so the next run's bind starts a fresh one. */
    private fun gone(pid: Int) {
        if (pid <= 0) return
        val until = SystemClock.elapsedRealtime() + GONE_WAIT_MS
        while (alive(pid) && SystemClock.elapsedRealtime() < until) SystemClock.sleep(POLL_MS)
        if (alive(pid)) {
            Process.killProcess(pid)
            val again = SystemClock.elapsedRealtime() + GONE_WAIT_MS
            while (alive(pid) && SystemClock.elapsedRealtime() < again) SystemClock.sleep(POLL_MS)
        }
    }

    /** A file's text as UTF-8, a bad byte U+FFFD; none for no file. */
    private fun read(file: File): String = if (file.isFile) file.readBytes().decodeToString() else ""

    /** The lines of [file] as they are written, each told with the milliseconds since [t0]; the last of it kept. */
    private class Tail(private val file: File, private val t0: Long, private val onLine: (Long, String) -> Unit) {
        private var at = 0L
        private val partial = java.io.ByteArrayOutputStream()
        private val kept = StringBuilder()

        fun read() {
            if (!file.isFile) return
            val bytes = RandomAccessFile(file, "r").use { raf ->
                if (raf.length() <= at) return
                ByteArray((raf.length() - at).toInt()).also { raf.seek(at); raf.readFully(it) }
            }
            at += bytes.size
            for (b in bytes) {
                if (b == '\n'.code.toByte()) line() else partial.write(b.toInt())
            }
        }

        fun end() {
            if (partial.size() > 0) line()
        }

        fun last(): String = kept.toString()

        private fun line() {
            val text = partial.toByteArray().decodeToString()
            partial.reset()
            kept.append(text).append('\n')
            if (kept.length > Ran.STDERR_TAIL) kept.delete(0, kept.length - Ran.STDERR_TAIL)
            onLine(SystemClock.elapsedRealtime() - t0, text)
        }
    }

    companion object {
        /** The property the test runners set in this (the main) process, sent in each request. */
        const val NETWORK = "caracole.network"

        const val STOPPED = "yt-dlp stopped (the phone may have run out of memory)"
        const val NOT_STARTED = "yt-dlp couldn't be started: its service wouldn't bind"

        private const val POLL_MS = 50L
        private const val GONE_WAIT_MS = 10_000L

        /** One run at a time, of every client in this process. */
        private val ONE_AT_A_TIME = Semaphore(1)

        /** Whether a process of this app's uid is [pid] still (its /proc entry, which an app sees for its own uid). */
        fun alive(pid: Int): Boolean = File("/proc/$pid").exists()
    }
}
