package io.github.danielhp95.caracole.youtube

import io.github.danielhp95.caracole.core.config.PhoneConfig
import io.github.danielhp95.caracole.core.db.Db
import io.github.danielhp95.caracole.core.health.EventLog
import io.github.danielhp95.caracole.core.health.Health
import io.github.danielhp95.caracole.core.http.Draws
import io.github.danielhp95.caracole.core.http.Event
import io.github.danielhp95.caracole.core.json.PyJson
import io.github.danielhp95.caracole.core.lookup.Pace
import io.github.danielhp95.caracole.core.py.PyFormat
import io.github.danielhp95.caracole.core.py.PyRe
import io.github.danielhp95.caracole.core.youtube.Choose
import io.github.danielhp95.caracole.core.youtube.Classify
import io.github.danielhp95.caracole.core.youtube.HostGate
import io.github.danielhp95.caracole.core.youtube.Videos
import io.github.danielhp95.caracole.core.youtube.YouTubeData
import io.github.danielhp95.caracole.core.youtube.YtDlp
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.int
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonPrimitive
import io.github.danielhp95.caracole.core.http.ProviderBlocked
import java.io.File
import java.io.IOException
import java.net.InetAddress
import java.net.ServerSocket
import java.net.URI
import java.time.Duration
import java.time.Instant
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit

/** [at] as caracole stores a time (stamps.py's): UTC, to the second, `Z`. */
fun utc(at: Instant): String = at.truncatedTo(java.time.temporal.ChronoUnit.SECONDS).toString()

/** What a run of the bench gave: [YtDlpClient]'s [Ran], its stderr's lines stamped as they came. */
data class BenchRan(val ran: Ran, val lines: List<Stamped>)

/**
 * The YouTube bench's session (the phone-youtube design's §4.2), on what [BenchRun] is given: the runs ([Runner],
 * [YtDlpClient] in the app), the gates ([Gates], [GateService]'s), the phone's record of runs ([Ledger], the main
 * process's database), what it measures ([Probe]) and its clock ([Clock]).
 *
 * It drives the client itself, not the runner (core.youtube.YtDlp): the report wants what the runner hides (each
 * stderr line stamped, the process's start and Python's, the uid's bytes and the PSS over each run, a gate opened to
 * observe every host), and a loopback session's targets are addresses the runner's search and download don't take. So
 * it holds the owner's terms itself, each as the runner does, on the same records:
 *
 * - the day's runs: at most the provider's budget (PhoneConfig's `youtube`, 6) in any 24 hours, every yt-dlp run the
 *   phone sent counted ([DbLedger]: kv `ytbench:runs` and `events`' sent runs of provider `youtube`, the larger), the
 *   session refused when it would pass them; and each run RESERVED before its gate opens ([Ledger.reserve]: in one
 *   write of the main process, the provider on, no cooldown, fewer than the budget, and its stamp appended to
 *   `ytbench:runs`), so a run is counted whatever ends it (this process killed, a gate's log or close that throws,
 *   its record that fails); only a run the client says never started (`YtDlpNotStarted`, `Refused`, or its gate that
 *   wouldn't open) gives its slot back ([Ledger.release]);
 * - every run sent is an `events` row (its decision the runner's), written in a `finally` whatever followed it;
 * - the pause: before its first run Pace.pauseAfterLastRequest's own (asked with the reservation, computed in the
 *   main process from kv `http:last_request:youtube`), before each later one the delay's draw less the time since the
 *   last ended (the runner's `_pause`), each said in `pause_seconds`;
 * - one run at a time: the client's (its file lock, across the app's processes);
 * - a block: a run whose stderr classifies as blocked is recorded as the runner records it (an `events` row,
 *   `Health.recordBlock` at the session's start, its status kept only where it is one of the data's block statuses),
 *   and the session stops there; the gate's log read first (a refusal, then its `stopped` bucket: an error in the
 *   data's words, never a block); a session or run while `youtube`
 *   cools down is refused, so no run follows a block until its cooldown ends; no alert is sent (the screen says it);
 * - the provider off: no session;
 * - a search's run id is `youtube-search:…`, so SearchGate's hour counts it, and a sent run moves kv
 *   `http:last_request:youtube`.
 *
 * Its queries ([plan]): 1 to [MOST_QUERIES] lines. Under the network: "Artist - Title" (a search, the computer's
 * `choose`, then a download; "AC/DC - Back in Black" too) or a video id (a download); a line shaped as an address (a
 * scheme, or a host name and a path) is refused. Under loopback (the main process's mode, the gate's): each an
 * http(s) address of a loopback host, else the session is refused before any run; a search there is the address's
 * metadata, its download the address. `observe` is refused under loopback.
 *
 * yt-dlp's cache is emptied once at the session's start ([Folders.cache]), so the first download solves the player
 * cold and the later ones warm. Every run adds `-v` ([Runner.run]'s `verbose`); its lines come redacted from the
 * client, and the report keeps no `[debug]` line.
 *
 * The kill check ([killCheck]), on the emulator and on the owner's phone alike: a gate of the main process's that can
 * only reach 127.0.0.1 ([Gates.openLoopback], LOOPBACK whatever the process's mode) and a run sent as LOOPBACK
 * ([killRunner]: the glue then takes a loopback target and its one `--exec` form, which starts the qjs child a real
 * download would have: yt-dlp's own solver starts qjs for YouTube alone), a trickled download of [TrickleServer]'s
 * bytes on 127.0.0.1 in this process, cancelled 2 s into its body; 2 s later the `:youtube` and qjs processes the
 * [Probe] finds (none must be left), then a `--version` run through the same gate (the next run works). It never
 * leaves the phone: no reservation, none of the six spent; it keeps one run at a time (the client's lock).
 *
 * The downloaded audio is deleted once it is measured: nothing of a session but its report stays.
 */
class BenchRun(
    private val runner: Runner,
    private val killRunner: Runner,
    private val gates: Gates,
    private val ledger: Ledger,
    private val probe: Probe,
    private val clock: Clock,
    private val folders: Folders,
    private val qjs: String,
    private val say: (String) -> Unit = {},
) {
    interface Runner {
        /** One yt-dlp run (YtDlpClient.run), [verbose] adding the bench's `-v` leave for its request. */
        fun run(argv: List<String>, folders: RunFolders, timeoutS: Double, verbose: Boolean): BenchRan

        /** Stops the run under way. */
        fun cancel()
    }

    interface Gate : AutoCloseable {
        val proxyArg: String

        fun log(): Map<String, HostGate.HostUse>

        override fun close()
    }

    interface Gates {
        /** The main process's mode, which its gates have. */
        val mode: HostGate.Mode

        fun open(observe: Boolean): Gate

        /** A gate that can reach 127.0.0.1 alone, in any process's mode: the kill check's. */
        fun openLoopback(): Gate
    }

    /** What the phone's records say now: whether `youtube` is on, its budget and delay, the sent runs of the last
     * 24 hours, the cooldown's words, the last sent run (epoch seconds), and the app's server and queue (idle). */
    data class State(val enabled: Boolean, val budget: Int, val delay: Pair<Double, Double>, val runs: Int,
                     val cooling: String?, val lastSent: Double?, val served: Long, val jobs: Long, val running: Boolean)

    /** One run to record: its run id, target, status, decision (the runner's), words, and whether it was a block. */
    data class Entry(val runId: String, val target: String, val status: Int?, val decision: String,
                     val message: String?, val blocked: Boolean)

    /** A run's slot of the day's: its [stamp] in `ytbench:runs`, or why none ([refused]); [pause], the first run's
     * pause after the phone's last (Pace.pauseAfterLastRequest's), 0 for a later one. */
    data class Reservation(val stamp: String?, val refused: String?, val pause: Double)

    interface Ledger {
        fun state(): State

        /** One write: the provider on, no cooldown, fewer runs than the budget in 24 h, then this run's stamp kept. */
        fun reserve(first: Boolean): Reservation

        /** A reserved run that never started: its stamp taken back, in one write. */
        fun release(stamp: String)

        /** A sent run's `events` row, kv `http:last_request:youtube`, and a block's strike. */
        fun record(entry: Entry, sessionStart: Instant)
    }

    interface Probe {
        fun device(): JsonObject
        fun network(): JsonObject
        fun uidBytes(): Long?

        /** Samples the PSS of `:youtube` and qjs every 0.5 s until the returned stop, which answers the peaks (MB). */
        fun sample(): () -> Map<String, Double>

        /** What MediaCodec decoded of [file]: its track's mime, rate, channels and frames; null when it can't. */
        fun decode(file: File): JsonObject?

        /** Whether Chaquopy's files were there before the session (an earlier start extracted them). */
        fun pythonExtracted(): Boolean

        /** The `:youtube` and qjs processes of the app's uid now, by their command lines. */
        fun leftover(): List<String>
    }

    class Clock(val now: () -> Instant, val wall: () -> Double, val monotonic: () -> Double,
                val sleep: (Double) -> Unit, val draws: Draws)

    /** The bench's folders: [root] (in the app's cache), yt-dlp's cache in it, a fresh download folder a run. */
    class Folders(val root: File) {
        val cache: File get() = File(root, YouTubeData.read().text("cache_folder", YouTubeData.read().runner))

        fun into(n: Int): File = File(root, "into-$n").apply { deleteRecursively(); mkdirs() }
    }

    /** A session refused before any run, in words. */
    class Refused(val words: String) : Exception(words)

    /** What a session came to. */
    class Session(val startedAt: Instant, val gate: String, val mode: HostGate.Mode, val runs: List<BenchRunRecord>,
                  val budgetBefore: Int, val budgetAfter: Int, val budgetOf: Int, val idle: BenchIdle,
                  val killCheck: JsonObject, val firstStart: JsonObject, val stopped: String?)

    /** One song of a session: as typed, and what its runs are. */
    data class Song(val typed: String, val search: String?, val download: String?, val names: Choose.Song?)

    private val data = YouTubeData.read()

    /** The songs [queries] stand for under [mode], or [Refused] in words. */
    fun plan(queries: List<String>, observe: Boolean): List<Song> {
        val lines = queries.map { it.trim() }.filter { it.isNotEmpty() }
        if (lines.isEmpty()) throw Refused(NO_QUERY)
        if (lines.size > MOST_QUERIES) throw Refused(TOO_MANY)
        val loopback = gates.mode == HostGate.Mode.LOOPBACK
        if (observe && loopback) throw Refused(NO_OBSERVE)
        return lines.map { q ->
            if (loopback) {
                if (!isLoopback(q)) throw Refused(notLoopback(q))
                Song(q, q, null, null)
            } else if (looksLikeAnAddress(q)) {
                throw Refused(notAQuery(q))
            } else if (PyRe.fullmatch(data.videoId, q) != null) {
                Song(q, null, data.watchUrl(q), null)
            } else {
                val artist = q.substringBefore(" - ", "").trim()
                val title = q.substringAfter(" - ").trim()
                Song(q, data.searchTarget(q), null,
                     Choose.Song(artist, title, if (artist.isEmpty()) emptyList() else listOf(artist)))
            }
        }
    }

    /** The runs [songs] take: a search and a download each, a video id's download alone. */
    fun runsOf(songs: List<Song>): Int = songs.sumOf { (if (it.search != null) 1 else 0) + 1 }

    /** A session over [queries]; [observe] the gate's every host logged (the button's alone). */
    fun session(queries: List<String>, observe: Boolean): Session {
        val songs = plan(queries, observe)
        val start = clock.now()
        val before = ledger.state()
        if (!before.enabled) throw Refused(OFF)
        before.cooling?.let { throw Refused(it) }
        val needed = runsOf(songs)
        if (before.runs + needed > before.budget) throw Refused(budgetWords(needed, before.budget - before.runs, before.budget))
        say("$needed runs: ${before.budget - before.runs} of ${before.budget} left in the last 24 hours")
        val extracted = probe.pythonExtracted()
        folders.cache.deleteRecursively()
        folders.cache.mkdirs()
        val runs = mutableListOf<BenchRunRecord>()
        var stopped: String? = null
        var lastEnd: Double? = null
        var downloads = 0
        val stamp = utc(start)
        var n = 0
        loop@ for (song in songs) {
            var download = song.download
            var chosenBy: String? = null
            if (song.search != null) {
                val (record, stop) = one(song.typed, SEARCH, null, song.search, null, "$SEARCH_RUN$stamp", lastEnd,
                                         start, observe)
                record?.let { runs += it.first; lastEnd = clock.monotonic() }
                if (stop != null) { stopped = stop; break@loop }
                if (record!!.first.outcome != OK) continue@loop
                if (gates.mode == HostGate.Mode.LOOPBACK) {
                    download = song.search
                    chosenBy = LOOPBACK_CHOSEN
                } else {
                    val videos = try {
                        Videos.parseSearch(record.second)
                    } catch (e: Exception) {
                        say("the search's answer won't read: ${e.message}")
                        continue@loop
                    }
                    val video = Choose.choose(song.names!!, videos, null)
                    if (video == null) {
                        say("no video of the search fits “${song.typed}”")
                        continue@loop
                    }
                    download = video.url
                    chosenBy = CHOSEN
                }
            }
            val cache = if (downloads++ == 0) COLD else WARM
            val (record, stop) = one(song.typed, DOWNLOAD, cache, download!!, folders.into(n++), "$DOWNLOAD_RUN$stamp",
                                     lastEnd, start, observe, chosenBy)
            record?.let { runs += it.first; lastEnd = clock.monotonic() }
            if (stop != null) { stopped = stop; break@loop }
        }
        val after = ledger.state()
        val kill = killCheck()
        val first = runs.firstOrNull()
        val firstStart = JsonObject(linkedMapOf(
            "first_after_install" to JsonPrimitive(!extracted),
            "process_start_ms" to JsonPrimitive(first?.processStartMs ?: -1),
            "python_ready_ms" to JsonPrimitive(first?.pythonReadyMs ?: -1),
        ))
        return Session(start, if (observe) OBSERVE else ENFORCE, gates.mode, runs, before.runs, after.runs,
                       before.budget, BenchIdle(before.served, after.served, before.jobs, after.jobs, before.running,
                                                after.running), kill, firstStart, stopped)
    }

    /** One run: reserved first (refused: no record, the words its stop), paused, run through a fresh gate, its gate's
     * log read, its `events` row written in a `finally` for a run sent whatever followed, classified. Its record with
     * its stdout, and the session's stop if it stops it. */
    private fun one(song: String, kind: String, cache: String?, target: String, into: File?, runId: String,
                    lastEnd: Double?, sessionStart: Instant, observe: Boolean,
                    chosenBy: String? = null): Pair<Pair<BenchRunRecord, String>?, String?> {
        val state = ledger.state()
        val reservation = ledger.reserve(first = lastEnd == null)
        val stamp = reservation.stamp ?: return null to (reservation.refused ?: OFF)
        val pause = if (lastEnd == null) reservation.pause
            else clock.draws.uniform(state.delay.first, state.delay.second) - (clock.monotonic() - lastEnd)
        var sent = false
        var ran: BenchRan? = null
        var thrown: Exception? = null
        var log: Map<String, HostGate.HostUse> = emptyMap()
        var outcome = ERROR
        var reason: String? = null
        var stderr = ""
        var startedAt = utc(clock.now())
        var seconds = 0.0
        var pss: Map<String, Double> = emptyMap()
        var uid0: Long? = null
        try {
            if (pause > 0) clock.sleep(pause)
            val cacheDir = folders.cache
            startedAt = utc(clock.now())
            say("${kind}${cache?.let { " ($it)" } ?: ""} of “$song”…")
            val gate = gates.open(observe)
            uid0 = probe.uidBytes()
            val peaks = probe.sample()
            val t0 = clock.monotonic()
            try {
                sent = true
                ran = runner.run(argv(kind, target, cacheDir, into, gate.proxyArg, verbose = true),
                                 RunFolders(cacheDir, into),
                                 if (kind == SEARCH) data.number("search_timeout") else data.number("download_timeout"),
                                 verbose = true)
            } catch (e: YtDlpNotStarted) {
                sent = false
                thrown = e
            } catch (e: io.github.danielhp95.caracole.youtube.Refused) {
                sent = false
                thrown = e
            } catch (e: IOException) {
                thrown = e
            } finally {
                seconds = clock.monotonic() - t0
                pss = peaks()
                log = try { gate.log() } finally { gate.close() }
            }
            stderr = ran?.lines?.joinToString("\n") { it.text }.orEmpty()
            val refused = log.filterValues { it.refused > 0 }.keys
            val decided = when {
                refused.isNotEmpty() ->
                    GATE_REFUSED to YouTubeData.fillAll(data.text("refusal", data.gate), mapOf("host" to refused.first()))
                data.text("stopped", data.gate) in log -> ERROR to data.text("stopped_said", data.gate)
                thrown != null -> ERROR to (thrown.message ?: thrown.javaClass.simpleName)
                ran!!.ran.timedOut || ran.ran.killed -> ERROR to "timed out or stopped"
                ran.ran.exit == Classify.OK_EXIT -> OK to null
                else -> Classify.of(stderr) to YtDlp.reason(stderr)
            }
            outcome = decided.first
            reason = decided.second
        } finally {
            if (sent) {
                val decision = when (outcome) {
                    OK, UNAVAILABLE -> OK
                    BenchReport.BLOCKED -> BenchReport.BLOCKED
                    else -> ERROR
                }
                // A run cut off by anything (the gate's log or close, an exception of the run's own) is still an
                // events row: an error in words, as the runner writes one.
                val words = reason ?: if (outcome == OK) null else CUT_OFF
                val status = PyRe.search(data.pattern("status"), stderr)?.groupValues?.get(1)?.toInt()
                ledger.record(Entry(runId, target, status, decision, words, outcome == BenchReport.BLOCKED), sessionStart)
            } else {
                ledger.release(stamp)
            }
        }
        val uid1 = probe.uidBytes()
        var file: JsonObject? = null
        var decoded: JsonObject? = null
        if (kind == DOWNLOAD && outcome == OK) {
            val printed = ran!!.ran.stdout.lines().lastOrNull { it.startsWith("{") && "\"filepath\"" in it }
            val info = printed?.let { runCatching { PyJson.loads(it) as? JsonObject }.getOrNull() }
            val path = info?.get("filepath")?.takeIf { it !is JsonNull }?.jsonPrimitive?.content?.let(::File)
            if (path != null && path.isFile) {
                file = JsonObject(linkedMapOf(
                    "ext" to JsonPrimitive(path.extension),
                    "bytes" to JsonPrimitive(path.length()),
                    "duration" to (info["duration"] ?: JsonNull),
                ))
                decoded = probe.decode(path)
            }
        }
        // Measured: the audio goes, nothing of the session but its report stays.
        into?.deleteRecursively()
        val record = BenchRunRecord(
            song, kind, cache, startedAt, ran?.ran?.processStartMs ?: -1, ran?.ran?.pythonReadyMs ?: -1, seconds,
            maxOf(pause, 0.0), ran?.lines.orEmpty(), outcome, reason, log,
            if (uid0 != null && uid1 != null) uid1 - uid0 else null, pss, file, decoded, chosenBy,
        )
        say("  $outcome in ${PyFormat.fixed(seconds, 1)} s${reason?.let { ": ${BenchReport.scrub(it)}" } ?: ""}")
        return (record to (ran?.ran?.stdout ?: "")) to (if (outcome == BenchReport.BLOCKED) BLOCKED_STOP else null)
    }

    /** youtube.json's argv for [kind], its target [target] (a loopback address in place of the template's watch
     * address where the mode is loopback's), the proxy [proxy], and the bench's `-v` before `--` where [verbose]. */
    private fun argv(kind: String, target: String, cache: File, into: File?, proxy: String,
                     verbose: Boolean = false): List<String> {
        val template = if (kind == DOWNLOAD && !data.isWatchUrl(target)) data.watchUrl(PLACEHOLDER_ID) else target
        val argv = data.argv(kind, template, cache.path, qjs, proxy, into?.path)
        val dash = argv.lastIndexOf("--")
        return argv.subList(0, dash) + (if (verbose) listOf(VERBOSE) else emptyList()) + listOf("--", target)
    }

    /** The kill check over a trickled loopback clip, on a loopback gate whatever the main process's mode. */
    fun killCheck(): JsonObject {
        TrickleServer().use { server ->
            val into = File(folders.root, "kill").apply { deleteRecursively(); mkdirs() }
            val script = File(into, "loop.js").apply { writeText("while (true);\n") }
            val gate = try {
                gates.openLoopback()
            } catch (e: IOException) {
                return JsonObject(linkedMapOf("run" to JsonPrimitive(false),
                                              "why" to JsonPrimitive("its gate: ${e.message}")))
            }
            var qjsSeen = false
            val over = java.util.concurrent.atomic.AtomicBoolean(false)
            val stopper = Thread {
                // Its body begun (or the run over without it: nothing to stop), then 2 s, then the stop.
                val until = System.nanoTime() + TimeUnit.SECONDS.toNanos(120)
                while (!over.get() && System.nanoTime() < until) {
                    if (server.begun.await(100, TimeUnit.MILLISECONDS)) {
                        clock.sleep(2.0)
                        qjsSeen = probe.leftover().any { it.contains(QJS) }
                        killRunner.cancel()
                        break
                    }
                }
            }
            var next = false
            val killed = try {
                stopper.start()
                val base = argv(DOWNLOAD, server.url, folders.cache, into, gate.proxyArg)
                val dash = base.lastIndexOf("--")
                val argv = base.subList(0, dash) + listOf("--exec", "before_dl:$qjs ${script.path}") +
                    base.subList(dash, base.size)
                killRunner.run(argv, RunFolders(folders.cache, into), 120.0, verbose = false).ran.killed
            } catch (e: IOException) {
                say("the kill check's run: ${e.message}")
                false
            } finally {
                over.set(true)
                stopper.join()
            }
            clock.sleep(2.0)
            val left = probe.leftover()
            try {
                val version = listOf("--ignore-config", "--no-plugin-dirs", "--proxy", gate.proxyArg, "--version")
                next = killRunner.run(version, RunFolders(), 120.0, verbose = false).ran.exit == Classify.OK_EXIT
            } catch (e: IOException) {
                say("the run after the kill check: ${e.message}")
            } finally {
                gate.close()
                into.deleteRecursively()
            }
            return JsonObject(linkedMapOf(
                "run" to JsonPrimitive(true), "spends" to JsonPrimitive(0), "killed" to JsonPrimitive(killed),
                "qjs_seen" to JsonPrimitive(qjsSeen), "left" to JsonArray(left.map(::JsonPrimitive)),
                "next_run_ok" to JsonPrimitive(next),
            ))
        }
    }

    /** A body of zeros served on 127.0.0.1 as `audio/mp4`, 256 bytes every 100 ms: a download that is always going. */
    class TrickleServer : AutoCloseable {
        private val server = ServerSocket(0, 4, InetAddress.getByName("127.0.0.1"))
        val url = "http://127.0.0.1:${server.localPort}/clip.m4a"
        val begun = CountDownLatch(1)
        private val thread = Thread({
            while (!server.isClosed) {
                val socket = try { server.accept() } catch (_: IOException) { return@Thread }
                Thread {
                    try {
                        socket.use {
                            val input = it.getInputStream()
                            var tail = 0
                            while (tail != 0x0d0a0d0a) tail = (tail shl 8) or (input.read().takeIf { b -> b >= 0 } ?: return@Thread)
                            val out = it.getOutputStream()
                            out.write("HTTP/1.1 200 OK\r\nContent-Type: audio/mp4\r\nContent-Length: $BODY\r\nConnection: close\r\n\r\n".toByteArray())
                            val chunk = ByteArray(256)
                            repeat(BODY / chunk.size) { _ ->
                                out.write(chunk)
                                out.flush()
                                begun.countDown()
                                Thread.sleep(100)
                            }
                        }
                    } catch (_: Exception) {
                        // the run killed mid-body
                    }
                }.apply { isDaemon = true; start() }
            }
        }, "ytbench-trickle").apply { isDaemon = true; start() }

        override fun close() {
            server.close()
            thread.join(2_000)
        }

        private companion object {
            const val BODY = 1 shl 20
        }
    }

    companion object {
        const val MOST_QUERIES = 3
        const val ENFORCE = "enforce"
        const val OBSERVE = "observe"
        const val SEARCH = "search"
        const val DOWNLOAD = "download"
        const val COLD = "cold"
        const val WARM = "warm"
        const val OK = "ok"
        const val ERROR = "error"
        const val UNAVAILABLE = "unavailable"
        const val GATE_REFUSED = "gate_refused"
        const val CHOSEN = "choose"
        const val LOOPBACK_CHOSEN = "loopback"
        const val QJS = "libqjs.so"
        private const val VERBOSE = "-v"

        /** A search's run id: SearchGate's ten an hour count runs of this prefix (commands/youtube.py's). */
        const val SEARCH_RUN = "youtube-search:ytbench:"
        const val DOWNLOAD_RUN = "ytbench:"
        private const val PLACEHOLDER_ID = "aaaaaaaaaaa"

        const val NO_QUERY = "No query: type up to 3 lines, “Artist - Title” or a video id."
        const val TOO_MANY = "Three queries at most: the day's runs are six."
        const val NO_OBSERVE = "Observing every host is never asked under the tests' network: loopback alone is reached."
        const val OFF = "YouTube is turned off on this phone (its provider's switch): no run."
        const val BLOCKED_STOP = "YouTube blocked a run: the session stops, and no run starts until its cooldown ends."
        const val CUT_OFF = "the run was cut off before its end was read"

        fun notLoopback(q: String) = "“$q” isn't a loopback address: under the tests' network the bench asks " +
            "loopback alone (127.0.0.1, 10.0.2.2), so no run is made."

        fun notAQuery(q: String) = "“$q” isn't a query: “Artist - Title” or a YouTube video id."

        fun budgetWords(needed: Int, left: Int, budget: Int) =
            "This session's $needed runs would pass the day's $budget: ${maxOf(left, 0)} left in the last 24 hours."

        private val SCHEME = Regex("^[A-Za-z][A-Za-z0-9+.-]*:")
        private val HOST_PATH = Regex("^(?:[A-Za-z0-9-]+\\.)+[A-Za-z]{2,}(?:[:/?#]|$)")

        /** Whether [q] is shaped as an address, not a query: a scheme (`https:`, `ytsearch:`), or a host name then a
         * path, port or end (`youtube.com/watch?v=…`). "AC/DC - Back in Black" is a query. */
        fun looksLikeAnAddress(q: String): Boolean = SCHEME.containsMatchIn(q) || HOST_PATH.containsMatchIn(q)

        /** Whether an intent starts a session: `go`, not a relaunch from Recents (FLAG_ACTIVITY_LAUNCHED_FROM_HISTORY),
         * and the tests' loopback alone; on the network a session starts only by a tap on Start. */
        fun startsByIntent(mode: HostGate.Mode, go: Boolean, fromHistory: Boolean): Boolean =
            go && !fromHistory && mode == HostGate.Mode.LOOPBACK

        /** Whether [q] is an http(s) address of a loopback host the gate allows (HostGate's names), no user in it. */
        fun isLoopback(q: String): Boolean = try {
            val uri = URI(q)
            uri.scheme in setOf("http", "https") && uri.host in HostGate.LOOPBACK_NAMES && uri.rawUserInfo == null
        } catch (_: Exception) {
            false
        }
    }
}

/**
 * The phone's record of the bench's runs, on its database ([Db], the main process's): [state], [reserve], [release]
 * and [record] as [BenchRun.Ledger] asks them, each in one read or write of the caller's.
 *
 * - The day's runs: the larger of kv `ytbench:runs` (the bench's own, a JSON list of UTC stamps, those of the last
 *   24 hours kept) and `events`' sent runs of provider `youtube` of the last 24 hours (every run the phone sent: the
 *   bench's own are rows there too, so a later product job and the bench share the six). A clock set back only
 *   counts more runs, never fewer (a stamp later than now is still within 24 hours of it).
 * - A reservation: the provider on, no cooldown, fewer runs than its budget, then the run's stamp appended, in one
 *   write; the first run's pause asked of Pace.pauseAfterLastRequest itself (its sleep taken as the answer).
 * - A record: the run's `events` row under its run id (EventLog), kv `http:last_request:youtube` for a sent decision
 *   (as the runner writes it), and for a block `Health.recordBlock` at the session's start (one strike), its message
 *   the runner's ProviderBlocked's, its status kept only where it is one of the data's `block_statuses`.
 */
object DbLedger {
    const val RUNS = "ytbench:runs"
    private const val PROVIDER = "youtube"
    private val DAY = Duration.ofHours(24)

    fun state(db: Db, now: Instant, served: Long, jobs: Long, running: Boolean): BenchRun.State {
        val policy = PhoneConfig.read(db).provider(PROVIDER)
        return BenchRun.State(policy.enabled, policy.budget.toInt(), policy.delay, runs(db, now), cooling(db, now),
                              Pace.lastRequest(db, PROVIDER), served, jobs, running)
    }

    /** The sent runs of the last 24 hours before [now]: the larger of the bench's own stamps and `events`'. */
    fun runs(db: Db, now: Instant): Int {
        val since = utc(now.minus(DAY))
        val sent = db.one("SELECT COUNT(*) FROM events WHERE provider = ? AND at >= ? AND decision IN " +
                          "(${Pace.SENT.joinToString(", ") { "?" }})", PROVIDER, since, *Pace.SENT.toTypedArray()) {
            it.long(0)
        }!!.toInt()
        return maxOf(sent, stamps(db).count { it >= since })
    }

    private fun cooling(db: Db, now: Instant): String? = if (Health.isCooling(db, PROVIDER, now)) {
        val until = Health.state(db, PROVIDER).cooldownUntil?.let { utc(it) }
        "YouTube is cooling down after a block${until?.let { " until $it" } ?: ""}: no run."
    } else null

    /** One write (the caller's): the run's slot, or why none. */
    fun reserve(db: Db, now: Instant, first: Boolean, draws: Draws, wall: () -> Double): BenchRun.Reservation {
        val policy = PhoneConfig.read(db).provider(PROVIDER)
        if (!policy.enabled) return BenchRun.Reservation(null, BenchRun.OFF, 0.0)
        cooling(db, now)?.let { return BenchRun.Reservation(null, it, 0.0) }
        val budget = policy.budget.toInt()
        if (runs(db, now) >= budget) return BenchRun.Reservation(null, BenchRun.budgetWords(1, 0, budget), 0.0)
        val stamp = utc(now)
        val since = utc(now.minus(DAY))
        db.kvSet(RUNS, JsonArray((stamps(db).filter { it >= since } + stamp).map(::JsonPrimitive)).toString())
        var pause = 0.0
        if (first) Pace.pauseAfterLastRequest(db, PROVIDER, policy.delay, draws, { pause = it }, wall)
        return BenchRun.Reservation(stamp, null, pause)
    }

    /** One write: [stamp] taken back (one of it), for a run that never started. */
    fun release(db: Db, stamp: String) {
        val kept = stamps(db).toMutableList()
        if (kept.remove(stamp)) db.kvSet(RUNS, JsonArray(kept.map(::JsonPrimitive)).toString())
    }

    fun record(db: Db, entry: BenchRun.Entry, now: Instant, wall: Double, sessionStart: Instant) {
        EventLog(db, entry.runId) { now }(Event(PROVIDER, entry.target, entry.status, entry.decision, entry.message))
        if (entry.decision in Pace.SENT) db.kvSet(Pace.LAST_SENT + PROVIDER, PyFormat.fixed(wall, 3))
        if (entry.blocked) {
            val statuses = YouTubeData.read().runner.getValue("block_statuses").jsonArray.map { it.jsonPrimitive.int }
            val blocked = ProviderBlocked(PROVIDER, entry.target, entry.status?.takeIf { it in statuses },
                                          entry.message ?: "blocked")
            Health.recordBlock(db, PROVIDER, sessionStart, blocked.message!!)
        }
    }

    private fun stamps(db: Db): List<String> = db.kvGet(RUNS)?.let { text ->
        (runCatching { PyJson.loads(text) }.getOrNull() as? JsonArray)?.mapNotNull {
            (it as? JsonPrimitive)?.takeIf { p -> p.isString }?.content
        }
    }.orEmpty()
}
