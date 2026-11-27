package io.github.danielhp95.caracole.youtube

import android.app.ActivityManager
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
import io.github.danielhp95.caracole.core.youtube.HostGate
import java.io.ByteArrayOutputStream
import java.io.Closeable
import java.io.File
import java.io.IOException
import java.io.RandomAccessFile
import java.security.SecureRandom
import java.util.concurrent.ConcurrentHashMap
import java.util.concurrent.LinkedBlockingQueue
import java.util.concurrent.Semaphore
import java.util.concurrent.TimeUnit

/**
 * What a run in `:youtube` gave: yt-dlp's exit status, its stdout, the end of its stderr (its last [STDERR_TAIL]
 * characters: on a long output an early WARNING can be lost, which the adapter to core's YtDlpProcess decides about),
 * whether the client [killed] it (a timeout, [timedOut] then, a cancel or a close; [exit] is then -1 and the rest is
 * what it wrote until then, or nothing for a run stopped before it began), and how long, from the client's bind, the
 * `:youtube` process took to start ([processStartMs]) and Python to be ready with yt-dlp imported and the argv
 * checked ([pythonReadyMs]); -1 for what never was. Every text the gate's `--proxy` is in is redacted ([YtDlpClient]).
 */
data class Ran(
    val exit: Int,
    val stdout: String,
    val stderrTail: String,
    val killed: Boolean,
    val timedOut: Boolean,
    val processStartMs: Long,
    val pythonReadyMs: Long,
) {
    companion object {
        const val STDERR_TAIL = 64 * 1024
    }
}

/** The `:youtube` process died while yt-dlp ran, unasked (the phone may have run out of memory): something may have
 * been sent. No block, no miss: an error. [words] never hold the argv. */
class YtDlpStopped(val words: String) : IOException(words)

/** No yt-dlp was started at all (the service wouldn't bind, Python didn't start): nothing was sent. */
class YtDlpNotStarted(val words: String) : IOException(words)

/** The service won't run this argv ([YtDlpService]'s refusals, the glue's words): nothing was run, nothing asked. */
class Refused(val words: String) : IOException(words)

/**
 * The main process's side of a yt-dlp run in `:youtube` ([YtDlpService]): [run] binds the service
 * (`BIND_AUTO_CREATE | BIND_IMPORTANT`), so a fresh process starts, sends it the argv and this process's mode
 * ([mode]: by default `caracole.network`, read as [HostGate.Mode.of] reads it, which the test runners set in the main
 * process; a client of another process of the app is given the mode of its gate, [GateService.Gate.mode], the main
 * process's; sent by its name, LOOPBACK or NETWORK: the `:youtube` process has no test runner to set it) and the run's
 * own folders ([RunFolders], the only ones its argv may name: the service checks them, the glue holds the argv to
 * them), follows its stderr line by line as yt-dlp writes it ([Env.err]), and once it
 * is answered, or [killed][Ran.killed], lets go and waits until that process is gone, so each run is a process of its
 * own. A `:youtube` process left from before (a run of a client of another process's life) is killed first.
 *
 * - One run at a time, of every client of every process of the app: within a process a run that must wait for
 *   another tells `waiting` once and waits; across processes a client holds [LOCK]'s file lock (a `FileChannel`
 *   lock on `filesDir/youtube-run.lock`) for the whole of its run, and a client that can't take it kills nothing,
 *   starts nothing and throws [YtDlpNotStarted] in [ANOTHER_RUN]'s words. The `:youtube` process left from before is
 *   killed only while the lock is held.
 * - Each run has its own stop: [cancel] (any thread) or [close] stops the runs of this client asked so far, a run
 *   still waiting for its turn included, which then starts nothing.
 * - A stop: past `timeoutS` from the bind, on [cancel] or on [close], it kills the `:youtube` process
 *   (`Process.killProcess` of its pid). Stopped once the request was sent but before its pid came, it waits for it
 *   ([START_WAIT_MS]), else finds the process by its name, and kills it: no yt-dlp is left to run on.
 * - Android's ActivityManager kills the killed process's cgroup, the children yt-dlp started, qjs among them
 *   (KillTest measured it). NEVER a process-group kill: every process of the app's uid, the main one included,
 *   shares one group (zygote's).
 * - Every answer carries its run's id: an answer of another run is never read as this one's.
 * - The process gone before its answer, unasked: [YtDlpStopped]; none started: [YtDlpNotStarted]; a refusal:
 *   [Refused].
 * - [run] blocks; never on the main thread, whose looper delivers the binding.
 *
 * The gate's secret: it logs nothing of the argv, and redacts, in one place ([Redact]), every line given to `onLine`,
 * the stderr tail and the stdout: any text shaped as a gate's `--proxy` ([HostGate.PROXY_PATTERN]) whole, and the
 * user and secret of each such address apart, wherever the argv spelled it (`--proxy`, `--proxy=`, `--prox` and any
 * other prefix yt-dlp's parser takes) and wherever the text shows it. yt-dlp's `-v` prints its
 * proxy map, the secret in it: a bench or a debug run that adds `-v` must keep those `[debug]` lines out of every
 * log, report and screen but through this client.
 */
class YtDlpClient(
    context: Context,
    private val mode: HostGate.Mode = HostGate.Mode.of(System.getProperty(NETWORK)),
) : Closeable {
    private val context = context.applicationContext
    private val replies = HandlerThread("caracole-ytdlp-client").apply { start() }
    private val runs = ConcurrentHashMap<Long, Run>()
    private val lock = Any()
    private var active = 0
    @Volatile private var closed = false

    /** The tests' seam: STARTED held back that long by the service, under LOOPBACK alone. */
    internal var startedDelayMs = 0L

    private sealed interface Event {
        data class Connected(val binder: IBinder) : Event
        data object Died : Event
        data object Stop : Event
        data class Said(val what: Int, val data: Bundle) : Event
    }

    /** One run's own: its id, its answers, its stop. */
    private class Run(val id: Long) {
        val events = LinkedBlockingQueue<Event>()
        @Volatile var stopped = false

        fun stop() {
            stopped = true
            events.put(Event.Stop)
        }
    }

    private val incoming = Messenger(Handler(replies.looper) { msg ->
        val data = Bundle(msg.data)
        runs[data.getLong(YtDlpService.Wire.RUN_ID)]?.events?.put(Event.Said(msg.what, data))
        true
    })

    /**
     * yt-dlp run once with [argv] (its arguments, no program name; its `--proxy` the gate's), stopped once it has run
     * [timeoutS] seconds; each line of its stderr goes to [onLine] with the milliseconds since the bind, as it comes;
     * [folders] the run's own, the only ones its argv may name; [verbose] the bench's leave for `-v` (allowed under
     * LOOPBACK anyway).
     */
    fun run(argv: List<String>, timeoutS: Double, onLine: (Long, String) -> Unit, waiting: () -> Unit,
            folders: RunFolders = RunFolders(), verbose: Boolean = false): Ran {
        check(Looper.myLooper() != Looper.getMainLooper()) { "YtDlpClient.run blocks: never on the main thread" }
        val run = Run(RANDOM.nextLong())
        synchronized(lock) {
            check(!closed) { "this YtDlpClient is closed" }
            active++
            runs[run.id] = run
        }
        try {
            if (!ONE_AT_A_TIME.tryAcquire()) {
                waiting()
                ONE_AT_A_TIME.acquire()
            }
            try {
                if (run.stopped || closed) return Ran(-1, "", "", true, false, -1, -1)
                return acrossProcesses { runAlone(run, argv, folders, verbose, timeoutS, Redact(argv), onLine) }
            } finally {
                ONE_AT_A_TIME.release()
            }
        } finally {
            runs.remove(run.id)
            synchronized(lock) {
                active--
                if (closed && active == 0) replies.quitSafely()
            }
        }
    }

    /** Stops every run of this client asked so far: the one under way killed, one waiting its turn never begun. */
    fun cancel() {
        for (run in runs.values) run.stop()
    }

    /** [cancel], and no run after. */
    override fun close() {
        synchronized(lock) {
            closed = true
            if (active == 0) replies.quitSafely()
        }
        cancel()
    }

    /** [block] while this client holds [LOCK]'s file lock, which no other process of the app then holds; none
     * taken: [YtDlpNotStarted] in [ANOTHER_RUN]'s words, nothing killed or started. */
    private fun <T> acrossProcesses(block: () -> T): T {
        val file = File(context.filesDir, LOCK)
        RandomAccessFile(file, "rw").use { raf ->
            val held = try {
                raf.channel.tryLock()
            } catch (_: java.nio.channels.OverlappingFileLockException) {
                null // this process holds it already: never two runs at once here either
            } ?: throw YtDlpNotStarted(ANOTHER_RUN)
            try {
                return block()
            } finally {
                held.release()
            }
        }
    }

    private fun runAlone(run: Run, argv: List<String>, folders: RunFolders, verbose: Boolean, timeoutS: Double,
                         redact: Redact, onLine: (Long, String) -> Unit): Ran {
        youtubePid()?.let { kill(it) }
        val out = Env.out(context)
        val err = Env.err(context)
        Env.runs(context).mkdirs()
        out.delete()
        err.delete()
        val t0 = SystemClock.elapsedRealtime()
        val deadline = t0 + (timeoutS * 1000).toLong()
        var binder: IBinder? = null
        val events = run.events
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
            throw YtDlpNotStarted(NOT_STARTED)
        }
        val tail = Tail(err, t0, redact, onLine)
        var pid = -1
        var started = -1L
        var ready = -1L
        var exit: Int? = null
        var killed = false
        var timedOut = false
        var sent = false
        try {
            while (exit == null) {
                tail.read()
                val now = SystemClock.elapsedRealtime()
                if (run.stopped || now >= deadline) {
                    killed = true
                    timedOut = !run.stopped
                    break
                }
                when (val event = events.poll(minOf(POLL_MS, deadline - now), TimeUnit.MILLISECONDS)) {
                    null, Event.Stop -> Unit
                    is Event.Connected -> {
                        binder = event.binder.also { it.linkToDeath(death, 0) }
                        val request = Message.obtain(null, YtDlpService.Wire.RUN).apply {
                            replyTo = incoming
                            data = Bundle().apply {
                                putLong(YtDlpService.Wire.RUN_ID, run.id)
                                putStringArray(YtDlpService.Wire.ARGV, argv.toTypedArray())
                                putString(YtDlpService.Wire.NETWORK, mode.name)
                                folders.cache?.let { putString(YtDlpService.Wire.CACHE, it.path) }
                                folders.into?.let { putString(YtDlpService.Wire.INTO, it.path) }
                                if (verbose) putBoolean(YtDlpService.Wire.VERBOSE, true)
                                if (startedDelayMs > 0) putLong(YtDlpService.Wire.DELAY_STARTED, startedDelayMs)
                            }
                        }
                        try {
                            Messenger(event.binder).send(request)
                            sent = true
                        } catch (_: RemoteException) {
                            events.put(Event.Died)
                        }
                    }
                    Event.Died -> throw if (pid < 0 && !sent) YtDlpNotStarted(NOT_STARTED) else YtDlpStopped(STOPPED)
                    is Event.Said -> when (event.what) {
                        YtDlpService.Wire.STARTED -> {
                            pid = event.data.getInt(YtDlpService.Wire.PID, -1)
                            started = event.data.getLong(YtDlpService.Wire.AT, -1)
                        }
                        YtDlpService.Wire.READY -> ready = event.data.getLong(YtDlpService.Wire.AT, -1)
                        YtDlpService.Wire.REFUSED ->
                            throw Refused(event.data.getString(YtDlpService.Wire.WORDS) ?: "refused")
                        YtDlpService.Wire.FAILED -> {
                            val words = event.data.getString(YtDlpService.Wire.WORDS) ?: STOPPED
                            throw if (event.data.getBoolean(YtDlpService.Wire.SENT)) YtDlpStopped(words)
                            else YtDlpNotStarted(words)
                        }
                        YtDlpService.Wire.DONE -> exit = event.data.getInt(YtDlpService.Wire.EXIT)
                    }
                }
            }
            if (killed) {
                if (pid <= 0 && sent) pid = awaitPid(events)
                if (pid <= 0) pid = youtubePid() ?: -1
                if (pid > 0) Process.killProcess(pid)
            }
            tail.read()
            tail.end()
            return Ran(
                exit = if (killed) -1 else exit!!,
                stdout = redact(read(out)),
                stderrTail = tail.last(),
                killed = killed,
                timedOut = timedOut,
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

    /** STARTED's pid, waited for at most [START_WAIT_MS] (the run's other answers passed over); -1 for none. */
    private fun awaitPid(events: LinkedBlockingQueue<Event>): Int {
        val until = SystemClock.elapsedRealtime() + START_WAIT_MS
        while (true) {
            val left = until - SystemClock.elapsedRealtime()
            if (left <= 0) return -1
            val event = events.poll(left, TimeUnit.MILLISECONDS) ?: return -1
            if (event is Event.Said && event.what == YtDlpService.Wire.STARTED) {
                return event.data.getInt(YtDlpService.Wire.PID, -1)
            }
            if (event == Event.Died) return -1
        }
    }

    /** The app's `:youtube` process now, by its name (ActivityManager lists this app's own), or null. */
    private fun youtubePid(): Int? {
        val name = "${context.packageName}$PROCESS"
        return context.getSystemService(ActivityManager::class.java)?.runningAppProcesses
            ?.firstOrNull { it.processName == name }?.pid
    }

    private fun kill(pid: Int) {
        Process.killProcess(pid)
        gone(pid)
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

    /** The one place the gate's `--proxy` is taken out of what yt-dlp wrote: every gate-shaped address
     * ([HostGate.PROXY_PATTERN]) the argv holds, whatever option spelled it, or the text shows, whole, then the user
     * and the secret of each, apart (one learned from the text is redacted from then on too). */
    internal class Redact(argv: List<String>) : (String) -> String {
        private val shape = Regex(HostGate.PROXY_PATTERN)
        private val whole = LinkedHashSet<String>()
        private val parts = LinkedHashSet<String>()

        init {
            for (arg in argv) learn(arg)
        }

        private fun learn(text: String) {
            for (found in shape.findAll(text)) {
                val proxy = found.value
                if (whole.add(proxy)) {
                    val credentials = proxy.substringAfter("://", "").substringBefore('@', "")
                    parts += credentials.split(':').filter { it.length >= 4 }
                }
            }
        }

        @Synchronized
        override fun invoke(text: String): String {
            learn(text)
            var out = text
            for (p in whole.sortedByDescending { it.length }) out = out.replace(p, PROXY_SAID)
            for (p in parts.sortedByDescending { it.length }) out = out.replace(p, SECRET_SAID)
            return out
        }
    }

    /** The lines of [file] as they are written, each redacted and told with the milliseconds since [t0]; the last of
     * them kept. */
    private class Tail(private val file: File, private val t0: Long, private val redact: Redact,
                       private val onLine: (Long, String) -> Unit) {
        private var at = 0L
        private val partial = ByteArrayOutputStream()
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
            val text = redact(partial.toByteArray().decodeToString())
            partial.reset()
            kept.append(text).append('\n')
            if (kept.length > Ran.STDERR_TAIL) kept.delete(0, kept.length - Ran.STDERR_TAIL)
            onLine(SystemClock.elapsedRealtime() - t0, text)
        }
    }

    companion object {
        /** The property the test runners set in this (the main) process, sent in each request as a [HostGate.Mode]. */
        const val NETWORK = "caracole.network"

        /** The service's process, after the package's name (the manifest's `android:process`). */
        const val PROCESS = ":youtube"

        const val STOPPED = "yt-dlp stopped (the phone may have run out of memory)"
        const val NOT_STARTED = "yt-dlp couldn't be started: its service wouldn't bind"
        const val ANOTHER_RUN = "another run is going: yt-dlp runs one at a time on the phone"

        /** The file in `filesDir` whose lock a client holds for the whole of a run, across the app's processes. */
        const val LOCK = "youtube-run.lock"
        const val PROXY_SAID = "<proxy>"
        const val SECRET_SAID = "<secret>"

        private const val POLL_MS = 50L
        private const val GONE_WAIT_MS = 10_000L

        /** How long a stop waits for the pid of a process it sent a request to. */
        const val START_WAIT_MS = 5_000L

        private val RANDOM = SecureRandom()

        /** One run at a time, of every client in this process (the file lock is the processes' rule). */
        private val ONE_AT_A_TIME = Semaphore(1)

        /** Whether a process of this app's uid is [pid] still (its /proc entry, which an app sees for its own uid). */
        fun alive(pid: Int): Boolean = File("/proc/$pid").exists()
    }
}
