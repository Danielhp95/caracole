package io.github.danielhp95.caracole.youtube

import android.content.Context
import io.github.danielhp95.caracole.core.youtube.YouTubeData
import io.github.danielhp95.caracole.core.youtube.YtDlpProcess
import java.io.Closeable
import java.io.File
import java.util.concurrent.CancellationException
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import io.github.danielhp95.caracole.core.youtube.Ran as CoreRan

/**
 * The app's yt-dlp as core.youtube's runner ([io.github.danielhp95.caracole.core.youtube.YtDlp]) sees it: each [run]
 * one run in `:youtube` through a [YtDlpClient] of its own, the same service, client and stop the debug bench runs
 * through. The runner owns the budget, the pauses, the block, the events and the gate; this runs the argv it is given
 * (youtube.json's template filled: never one of its own; the service's glue checks it again), once.
 *
 * - One at a time across the app: the client's rules (within this process a run waits its turn, `waiting` told once;
 *   while another process of the app runs one, the debug bench's `:ytbench`, it starts nothing and is [NotStarted] in
 *   [YtDlpClient.ANOTHER_RUN]'s words: the bench's run is never waited for, nor stopped).
 * - [YtDlpProcess.NotStarted], nothing sent: the service wouldn't bind or Python didn't start ([YtDlpNotStarted]), the
 *   argv refused by the client or the glue ([Refused]: a `--proxy` that is no open gate of the app's among them), a
 *   run stopped before its request was sent ([Ran.sent] false).
 * - [CoreRan]: yt-dlp's exit status, its stdout and its stderr; [CoreRan.timedOut] once it ran past `timeoutS` and was
 *   killed. Its stderr is every line it wrote up to [HEAD] characters, then, past them, the client's tail (its last
 *   [Ran.STDERR_TAIL]): classify reads a block's or a warning's words anywhere, and the last ERROR line is the tail's.
 * - Cut off, something maybe sent: the `:youtube` process gone unasked ([YtDlpStopped], thrown as it is), a [cancel] or
 *   [close] while it ran (a CancellationException), the calling thread interrupted (an InterruptedException): the
 *   process killed first, with its qjs (YtDlpClient's stop). The runner counts and logs such a run; nothing here
 *   records anything.
 * - No argv in any message or line: the client redacts every line, and nothing here says the argv.
 *
 * [close] (or [cancel]) stops the run under way, and [close] refuses every later one: nothing is left of it (no
 * process, no thread: each run's client is closed as the run ends).
 */
class ProcessYtDlp(context: Context) : YtDlpProcess, Closeable {
    private val context = context.applicationContext
    private val lock = Any()
    private var current: YtDlpClient? = null
    @Volatile private var closed = false
    private val data = YouTubeData.read()

    override fun run(argv: List<String>, timeoutS: Double, onLine: (String) -> Unit, waiting: () -> Unit): CoreRan {
        val client = synchronized(lock) {
            if (closed) throw YtDlpProcess.NotStarted(CLOSED)
            YtDlpClient(context).also { current = it }
        }
        val stderr = Stderr()
        val folders = folders(argv)
        val ran = try {
            folders.cache?.mkdirs() // yt-dlp's cache, the runner's to name and this run's to make (the service checks it)
            client.run(argv, timeoutS, { _, line -> stderr.add(line); onLine(line) }, waiting, folders)
        } catch (e: YtDlpNotStarted) {
            throw YtDlpProcess.NotStarted(e.words)
        } catch (e: Refused) {
            throw YtDlpProcess.NotStarted(e.words)
        } finally {
            synchronized(lock) { if (current === client) current = null }
            client.close()
        }
        return when {
            !ran.sent -> throw YtDlpProcess.NotStarted(STOPPED_BEFORE)
            ran.timedOut -> CoreRan.timedOut()
            ran.killed -> throw CancellationException(STOPPED)
            else -> CoreRan(ran.exit, ran.stdout, stderr.text(ran.stderrTail))
        }
    }

    /** Stops the run under way, if any: its process killed. */
    fun cancel() {
        synchronized(lock) { current }?.cancel()
    }

    /** [cancel], and no run after. */
    override fun close() {
        closed = true
        cancel()
    }

    /** The run's own folders, as the argv the runner built names them: `--cache-dir`'s value, and a download's `-o`
     * folder; each flag read off youtube.json's templates (the element before its placeholder), never typed here. */
    internal fun folders(argv: List<String>): RunFolders {
        val ends = argv.indexOf(END).let { if (it < 0) argv.size else it }
        val options = argv.subList(0, ends)
        var cache: File? = null
        var into: File? = null
        for (template in templates().values) {
            val words = (template as JsonArray).map { (it as JsonPrimitive).content }
            for ((i, word) in words.withIndex()) {
                val isCache = word == placeholder("cache_dir")
                val isInto = word.startsWith(placeholder("into"))
                if (i == 0 || !(isCache || isInto)) continue
                val at = options.indexOf(words[i - 1]).takeIf { it >= 0 && it + 1 < options.size } ?: continue
                val value = options[at + 1]
                if (isCache) cache = File(value)
                val rest = word.removePrefix(placeholder("into"))
                if (isInto && value.endsWith(rest)) into = File(value.removeSuffix(rest))
            }
        }
        return RunFolders(cache, into)
    }

    private fun placeholder(name: String): String = data.placeholders.getValue(name)

    /** Every line, while they come to [HEAD] and the client's tail's [Ran.STDERR_TAIL] characters at most; past them,
     * the lines of the first [HEAD] characters, then the tail, which then can't overlap them. */
    private class Stderr {
        private val all = StringBuilder()
        private var head = -1 // where the head ends, once the lines went past the two together

        @Synchronized
        fun add(line: String) {
            if (head >= 0) return
            if (all.length + line.length + 1 <= HEAD + Ran.STDERR_TAIL) {
                all.append(line).append('\n')
                return
            }
            var end = 0
            while (true) {
                val next = all.indexOf("\n", end)
                if (next < 0 || next + 1 > HEAD) break
                end = next + 1
            }
            head = end
            all.setLength(end)
        }

        @Synchronized
        fun text(tail: String): String = if (head >= 0) all.toString() + tail else all.toString()
    }

    companion object {
        /** The stderr kept whole before the client's tail takes over. */
        const val HEAD = 64 * 1024

        const val CLOSED = "yt-dlp wasn't started: its runner is closed"
        const val STOPPED = "yt-dlp was stopped"
        const val STOPPED_BEFORE = "yt-dlp wasn't started: it was stopped before its turn"

        private fun templates(): JsonObject = YouTubeData.read().json.getValue("phone_argv") as JsonObject

        /** The argv's end of options, after which the target alone: youtube.json's templates' own (the element before
         * the target's placeholder). */
        private val END: String by lazy {
            val download = (templates().getValue("download") as JsonArray).map { (it as JsonPrimitive).content }
            download[download.indexOf(YouTubeData.read().placeholders.getValue("target")) - 1]
        }
    }
}
