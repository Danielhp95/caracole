package io.github.danielhp95.caracole.core.youtube

import io.github.danielhp95.caracole.core.config.ProviderPolicy
import io.github.danielhp95.caracole.core.db.Db
import io.github.danielhp95.caracole.core.health.EventLog
import io.github.danielhp95.caracole.core.health.Health
import io.github.danielhp95.caracole.core.health.Strptime
import io.github.danielhp95.caracole.core.http.BudgetExhausted
import io.github.danielhp95.caracole.core.http.Draws
import io.github.danielhp95.caracole.core.http.Event
import io.github.danielhp95.caracole.core.http.ProviderBlocked
import io.github.danielhp95.caracole.core.http.ProviderError
import io.github.danielhp95.caracole.core.json.PyJson
import io.github.danielhp95.caracole.core.lookup.Pace
import io.github.danielhp95.caracole.core.lookup.Pacing
import io.github.danielhp95.caracole.core.lyrics.internal.PyValues
import io.github.danielhp95.caracole.core.py.Py
import io.github.danielhp95.caracole.core.py.PyFormat
import io.github.danielhp95.caracole.core.py.PyRe
import io.github.danielhp95.caracole.core.py.PyStr
import io.github.danielhp95.caracole.core.py.PyText
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.int
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonPrimitive
import java.io.File
import java.nio.file.Files
import java.util.concurrent.TimeoutException

/** youtube.py's VideoUnavailable: YouTube answered that the video can't be had (removed, private, age-restricted…).
 * No block, and no miss. */
open class VideoUnavailable(provider: String, url: String?, status: Int?, msg: String?) :
    ProviderError(provider, url, status, msg)

/** The phone's: the video has no stream of the one format the phone asks (no FFmpeg there to make one): passed over,
 * the next video taken. A [VideoUnavailable], told apart by its class. */
class PassedOver(provider: String, url: String?, status: Int?, msg: String?) : VideoUnavailable(provider, url, status, msg)

/** The phone's: yt-dlp can't read YouTube's page (its extractor, or its challenge solver, is out of date). No block, no
 * miss, and nothing recorded against the video. */
class ExtractorOutdated(provider: String, url: String?, status: Int?, msg: String?) : ProviderError(provider, url, status, msg)

/** The phone's: the app's gate refused a host yt-dlp asked for, in youtube.json's `gate.refusal` words. Never a block. */
class GateRefused(provider: String, url: String?, val host: String, msg: String) : ProviderError(provider, url, null, msg)

/** The phone's: [YtDlp]'s `beforeRun` refused the run in its words (the metered check): no process, nothing spent, no
 * event. An error, never a miss. */
class RunHeldBack(provider: String, url: String?, msg: String) : ProviderError(provider, url, null, msg)

/**
 * The gate a run goes through, as the runner sees it: the `--proxy` value it is given, its log, and its end. A run
 * asks for one ([YtDlp]'s `gate`) and closes it once it has read the run's log, on every path. [HostGate.Opened] is
 * one, a gate of its own a run, which its close ends; a job that wants one gate for all its runs passes
 * `{ YtDlpGate.keptOpen(opened) }`, whose close does nothing, and closes `opened` itself once the job is over.
 */
interface YtDlpGate : java.io.Closeable {
    val proxyArg: String

    fun log(): Map<String, HostGate.HostUse>

    companion object {
        /** [gate], its close a no-op: the job's gate, which a run never ends. */
        fun keptOpen(gate: YtDlpGate): YtDlpGate = object : YtDlpGate {
            override val proxyArg: String get() = gate.proxyArg
            override fun log() = gate.log()
            override fun close() {}
            override fun toString() = "kept open: $gate"
        }
    }
}

/** A download's audio, right inside the folder given, and the video as yt-dlp reported it. */
data class Download(val path: File, val video: Video)

/**
 * youtube.py's YtDlp on the phone: yt-dlp for one job, budgeted, paced, one run at a time, stopping at the first block.
 * Every rule, flag and word is youtube.json's; the pace, the budget, the block and the events are the phone's own
 * HTTP providers' machinery, for provider `youtube`:
 *
 * - [budget] runs at most ([requestsMade] counts them), then `BudgetExhausted`, the `budget` event written once;
 * - before each run, a cooldown recorded by an earlier job (`Health.isCooling`) refuses it: `ProviderBlocked` in the
 *   words the computer's callers say a cooling YouTube in (youtube_sheet.py: "waiting out YouTube until …"), with no
 *   gate opened, no process, no event and no strike; then [beforeRun] may refuse it ([RunHeldBack]: no process, no
 *   budget spent, no event);
 * - before the first, the pause after the last run this side sent ([Pace.pauseAfterLastRequest], kv
 *   `http:last_request:youtube`); before each later one, `_pause`'s: a draw of [policy]'s delay from [rng], less the
 *   time since the last run ended on [clock]'s monotonic clock;
 * - every run's argv is youtube.json's template filled ([YouTubeData.argv]), the gate's `proxyArg` its `--proxy`
 *   ([gate] asked once a run, closed once the run's log is read, whatever the run came to: [YtDlpGate]); the cache is
 *   [cacheDir]'s `runner.cache_folder`;
 * - each run one `events` row ([EventLog] under [runId]: the computer's fields), heard after by [onEvent], and for one
 *   sent kv `http:last_request:youtube` as `f"{time.time():.3f}"` writes it;
 * - after a run, in order: the gate's log first (a host it refused during the run: [GateRefused], an `error` event;
 *   the gate stopped accepting by a bug of its own, its log's `gate.stopped`: a ProviderError in `gate.stopped_said`);
 *   then a timeout (an `error`, the computer's words); then the exit status (`ok`); then [Classify.of] the stderr:
 *   blocked (`ProviderBlocked`, [Health.recordBlock] at the job's start, every later run refused with no process),
 *   unavailable ([VideoUnavailable]), pass_over ([PassedOver]), outdated ([ExtractorOutdated]: no block recorded),
 *   else a ProviderError. The events are the computer's for every run (a pass-over and an out of date run are its
 *   `error`s); only the class raised is the phone's.
 * - a run the process ends by throwing (a cancel, an interrupt, the service killed: anything but
 *   [YtDlpProcess.NotStarted]) was started, so it is counted ([requestsMade]) and logged, an `error` event and kv
 *   `http:last_request:youtube` as any run, then rethrown in words with no secret: an interrupt as an
 *   InterruptedException (the thread's interrupt kept), a cancel as a CancellationException, anything else a
 *   ProviderError. The computer's runner writes no event for its BaseException path; the phone's day budget and the
 *   next job's pause must see a run yt-dlp may have sent requests in, the `:youtube` process being one Android can
 *   kill mid-run.
 *
 * What the callers do: never record a block themselves (the runner records it, [Health.recordBlock], one strike), and
 * send its alert ([io.github.danielhp95.caracole.core.health.Alerts.blocked], once a cooldown) from the
 * `ProviderBlocked` they catch.
 *
 * The gate's address holds its secret: no event, kv record, exception or line given to [onLine] holds it (each is
 * read with the proxy's user and secret put back as `<proxy>`).
 */
class YtDlp(
    private val process: YtDlpProcess,
    val policy: ProviderPolicy,
    private val cacheDir: File,
    private val qjs: String,
    private val gate: () -> YtDlpGate,
    private val db: Db,
    private val clock: Pacing,
    private val rng: Draws = clock.draws,
    val budget: Int,
    runId: String,
    private val beforeRun: () -> String? = { null },
    private val onEvent: ((Event) -> Unit)? = null,
    private val timeouts: Pair<Double, Double> = DATA.number("search_timeout") to DATA.number("download_timeout"),
    private val onLine: (String) -> Unit = {},
    private val waiting: () -> Unit = {},
) {
    val provider: String = PROVIDER
    var requestsMade: Int = 0
        private set

    private val log = EventLog(db, runId, clock.clock)
    private val started = clock.clock()
    private var last: Double? = null
    private var pacedAfterLastRun = false
    private var blocked: ProviderBlocked? = null
    private var budgetReported = false

    /** A search's videos: `ytsearch<n>:` and [query] as it is. */
    fun search(query: String, n: Int = DATA.searchResults): List<Video> =
        Videos.parseSearch(run(SEARCH, DATA.searchTarget(query, n), timeouts.first, null))

    /** A video's metadata, one run and no download. */
    fun video(videoId: String): Video {
        require(PyRe.fullmatch(DATA.videoId, videoId) != null) { "not a YouTube video id: $videoId" }
        return Videos.parseVideo(run(VIDEO, DATA.watchUrl(videoId), timeouts.first, null), videoId)
    }

    /** The video's audio in [into], and the video as yt-dlp reported it (its `--print` line, the last with a
     * `filepath`); no audio file of some size right inside [into], and no link, is an error. */
    fun download(videoId: String, into: File): Download {
        require(PyRe.fullmatch(DATA.videoId, videoId) != null) { "not a YouTube video id: $videoId" }
        val url = DATA.watchUrl(videoId)
        val out = run(DOWNLOAD, url, timeouts.second, into)
        var info: JsonObject? = null
        for (line in PyStr.splitlines(out).asReversed()) {
            val found = try {
                PyJson.loads(line)
            } catch (_: IllegalArgumentException) {
                continue
            }
            if (found is JsonObject && PyValues.truthy(found["filepath"])) {
                info = found
                break
            }
        }
        val path = File(Videos.str(info?.get("filepath")))
        if (!audioIn(path, into)) {
            throw ProviderError(PROVIDER, url, null, YouTubeData.fillAll(words("no_audio_left"), mapOf("folder" to into.name)))
        }
        // _duration: an int duration no float holds is an answer error, in the words of a video's answer that isn't JSON.
        val duration = try {
            PyValues.number(info?.get("duration"))
        } catch (e: ArithmeticException) {
            throw ProviderError(PROVIDER, url, null, YouTubeData.fillOnce(answerWords("video_not_json"), "{}", e.message ?: ""))
        }
        val video = Video(videoId, Videos.str(info?.get("title")), Videos.str(Videos.or(info?.get("channel"), info?.get("uploader"))),
                          duration)
        return Download(path, video)
    }

    // -- one run ------------------------------------------------------------------------------------------------------

    private fun run(what: String, target: String, timeout: Double, into: File?): String {
        blocked?.let { throw ProviderBlocked(PROVIDER, target, it.status, words("blocked_earlier")) }
        if (Health.isCooling(db, PROVIDER, clock.clock())) throw ProviderBlocked(PROVIDER, target, null, coolingWords())
        if (requestsMade >= budget) {
            if (!budgetReported) {
                budgetReported = true
                event(target, null, BUDGET, YouTubeData.fillAll(words("budget_spent"), mapOf("budget" to budget.toString())))
            }
            throw BudgetExhausted(PROVIDER)
        }
        beforeRun()?.let { throw RunHeldBack(PROVIDER, target, it) }
        try {
            return gate().use { opened -> runThrough(opened, what, target, timeout, into) }
        } catch (e: InterruptedException) {
            Thread.currentThread().interrupt() // kept, once the gate is closed (its close joins its threads)
            throw e
        }
    }

    /** One run through [opened], which the caller closes after: everything here reads its log first. */
    private fun runThrough(opened: YtDlpGate, what: String, target: String, timeout: Double, into: File?): String {
        val argv = DATA.argv(what, target, File(cacheDir, words("cache_folder")).path, qjs, opened.proxyArg, into?.path)
        if (!pacedAfterLastRun) {
            pacedAfterLastRun = true
            Pace.pauseAfterLastRequest(db, PROVIDER, policy.delay, rng, clock.sleep, clock.wallSeconds)
        }
        pause()
        val refusedBefore = refusals(opened)
        val ran = try {
            process.run(argv, timeout, { line -> onLine(redacted(line, opened)) }, waiting)
        } catch (e: YtDlpProcess.NotStarted) { // nothing was sent
            throw ProviderError(PROVIDER, target, null, redacted(e.message ?: e.toString(), opened))
        } catch (e: Exception) { // started, then cut off: counted and logged, said with no secret
            requestsMade++
            last = clock.monotonic()
            val said = redacted(e.message ?: e::class.simpleName.orEmpty(), opened)
            event(target, null, ERROR, said)
            throw cutOff(e, target, said)
        }
        requestsMade++
        last = clock.monotonic()
        val refused = refusals(opened).filter { (host, n) -> n > (refusedBefore[host] ?: 0) }.keys
        if (refused.isNotEmpty()) {
            val host = refused.first()
            val message = YouTubeData.fillAll(DATA.text("refusal", DATA.gate), mapOf("host" to host))
            event(target, null, ERROR, message)
            throw GateRefused(PROVIDER, target, host, message)
        }
        if (DATA.text("stopped", DATA.gate) in opened.log()) {
            val message = DATA.text("stopped_said", DATA.gate)
            event(target, null, ERROR, message)
            throw ProviderError(PROVIDER, target, null, message)
        }
        if (ran.timedOut) {
            val message = YouTubeData.fillAll(words("timed_out"), mapOf("timeout:g" to PyFormat.general(timeout)))
            event(target, null, ERROR, message)
            throw ProviderError(PROVIDER, target, null, message).also { it.initCause(TimeoutException(message)) }
        }
        if (ran.exit == Classify.OK_EXIT) {
            event(target, null, OK, null)
            return ran.stdout
        }
        val stderr = ran.stderr
        val reason = redacted(reason(stderr), opened)
        val status = PyRe.search(DATA.pattern("status"), stderr)?.groupValues?.get(1)?.toInt()
        when (Classify.of(stderr)) {
            BLOCKED -> {
                val e = ProviderBlocked(PROVIDER, target, status?.takeIf { it in blockStatuses }, reason)
                blocked = e
                event(target, status, BLOCKED, reason)
                Health.recordBlock(db, PROVIDER, started, e.message!!)
                throw e
            }
            UNAVAILABLE -> {
                event(target, status, OK, YouTubeData.fillAll(words("unavailable_said"), mapOf("reason" to reason)))
                throw VideoUnavailable(PROVIDER, target, status, reason)
            }
            PASS_OVER -> {
                event(target, status, ERROR, reason)
                throw PassedOver(PROVIDER, target, status, reason)
            }
            OUTDATED -> {
                event(target, status, ERROR, reason)
                throw ExtractorOutdated(PROVIDER, target, status, reason)
            }
            else -> {
                event(target, status, ERROR, reason)
                throw ProviderError(PROVIDER, target, status, reason)
            }
        }
    }

    /** `_pause`: a draw of the delay, less the time since the last run ended, slept. */
    private fun pause() {
        val at = last ?: return
        val remaining = rng.uniform(policy.delay.first, policy.delay.second) - (clock.monotonic() - at)
        if (remaining > 0) clock.sleep(remaining)
    }

    private fun event(target: String, status: Int?, decision: String, message: String?) {
        val e = Event(PROVIDER, target, status, decision, message)
        log(e)
        if (decision in Pace.SENT) db.kvSet(Pace.LAST_SENT + PROVIDER, PyFormat.fixed(clock.wallSeconds(), 3))
        onEvent?.invoke(e)
    }

    /** youtube_sheet.py's words for a cooling YouTube (the data's `runner.cooling`, its end as `cooling_when`, else
     * `cooling_later`): "waiting out YouTube until 2026-11-27 13:00 UTC". */
    private fun coolingWords(): String {
        val stamp = Health.state(db, PROVIDER).cooldownUntil?.let { Strptime.format(it) }
        val until = if (stamp == null) words("cooling_later") else YouTubeData.fillAll(words("cooling_when"),
            mapOf("date" to stamp.substring(0, 10), "time" to stamp.substring(11, 16)))
        return YouTubeData.fillAll(words("cooling"), mapOf("when" to until))
    }

    /** What a run cut off by [e] is rethrown as: its kind kept where a caller acts on it, its words [said]. */
    private fun cutOff(e: Exception, target: String, said: String): Exception {
        val again = when (e) {
            is InterruptedException -> InterruptedException(said)
            is java.util.concurrent.CancellationException -> java.util.concurrent.CancellationException(said)
            else -> ProviderError(PROVIDER, target, null, said)
        }
        again.stackTrace = e.stackTrace
        return again
    }

    /** The gate's refusals by host, as its log has them now. */
    private fun refusals(opened: YtDlpGate): Map<String, Int> =
        opened.log().filterValues { it.refused > 0 }.mapValues { it.value.refused }

    companion object {
        private val DATA: YouTubeData by lazy { YouTubeData.read() }
        private val PROVIDER: String by lazy { DATA.text("provider", DATA.json.getValue("answers") as JsonObject) }
        private val blockStatuses: Set<Int> by lazy {
            DATA.runner.getValue("block_statuses").jsonArray.map { it.jsonPrimitive.int }.toSet()
        }
        private const val SEARCH = "search"
        private const val VIDEO = "video"
        private const val DOWNLOAD = "download"
        private const val OK = "ok"
        private const val ERROR = "error"
        private const val BUDGET = "budget"
        private const val BLOCKED = "blocked"
        private const val UNAVAILABLE = "unavailable"
        private const val PASS_OVER = "pass_over"
        private const val OUTDATED = "outdated"

        private fun words(name: String): String = DATA.text(name, DATA.runner)

        /** A word of the data's `answers`: what an answer that can't be read says. */
        private fun answerWords(name: String): String = DATA.text(name, DATA.json.getValue("answers") as JsonObject)

        /** `_reason`: yt-dlp's last ERROR line less that word, else its last line, else `said_nothing`; cut to
         * `reason_chars` code points, its last `reason_cut`. Every line read, `[debug]` ones too, as the computer's. */
        fun reason(stderr: String): String {
            val classify = DATA.classify
            val errorPrefix = DATA.text("error_prefix", classify)
            val lines = PyStr.splitlines(stderr).map { Py.strip(it) }.filter { it.isNotEmpty() }
            val errors = lines.filter { it.startsWith(errorPrefix) }.map { Py.strip(it.removePrefix(errorPrefix)) }
            val text = errors.lastOrNull() ?: lines.lastOrNull() ?: words("said_nothing")
            val most = DATA.number("reason_chars").toInt()
            return if (Py.len(text) <= most) text else Py.slice(text, 0, most - 1) + words("reason_cut")
        }

        /** [text] with the gate's address, and its user and secret alone, put back as the `proxy` placeholder. */
        internal fun redacted(text: String, opened: YtDlpGate): String {
            val mark = DATA.placeholders.getValue("proxy")
            val arg = opened.proxyArg
            var out = text.replace(arg, mark)
            val credentials = arg.substringAfter("//", "").substringBefore('@', "")
            for (secret in listOf(credentials) + credentials.split(':')) {
                if (secret.isNotEmpty()) out = out.replace(secret, mark)
            }
            return out
        }

        /** `_audio_in`: [path] an audio file (`audio_suffixes`, its suffix lowercased) of some size right inside
         * [folder], no link. */
        private fun audioIn(path: File, folder: File): Boolean = try {
            val parent = path.absoluteFile.parentFile
            parent != null && parent.canonicalFile == folder.canonicalFile && !Files.isSymbolicLink(path.toPath()) &&
                path.isFile && suffix(path.name) in DATA.texts("audio_suffixes", DATA.json) && path.length() > 0
        } catch (_: java.io.IOException) {
            false
        }

        /** PurePath.suffix, lowercased as str.lower: the name's last dotted part, none for a name that only starts
         * with a dot or ends with one. */
        private fun suffix(name: String): String {
            val dot = name.lastIndexOf('.')
            return if (dot <= 0 || dot == name.length - 1) "" else PyText.lower(name.substring(dot))
        }
    }
}
