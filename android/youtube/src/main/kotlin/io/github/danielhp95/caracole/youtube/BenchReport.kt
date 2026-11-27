package io.github.danielhp95.caracole.youtube

import io.github.danielhp95.caracole.core.youtube.HostGate
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.doubleOrNull
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import kotlinx.serialization.json.longOrNull
import kotlin.math.abs

/** One line of a run's stderr as the client gave it (redacted), [ms] after the run's bind. */
data class Stamped(val ms: Long, val text: String)

/**
 * One run of a bench session as it went: the song as typed, its [kind] (`search` or `download`), [cache] (`cold` or
 * `warm`, a download's), when it started (UTC), the client's process timings, how long it ran, the pause caracole
 * made before it, its stderr lines as they came (stamped, redacted), its outcome and reason, the gate's log, the uid's
 * bytes over it, the peaks of PSS sampled, and a download's file and what MediaCodec decoded of it.
 */
data class BenchRunRecord(
    val song: String,
    val kind: String,
    val cache: String?,
    val startedAt: String,
    val processStartMs: Long,
    val pythonReadyMs: Long,
    val seconds: Double,
    val pauseSeconds: Double,
    val lines: List<Stamped>,
    val outcome: String,
    val reason: String?,
    val hosts: Map<String, HostGate.HostUse>,
    val uidBytes: Long?,
    val pssPeakMb: Map<String, Double>,
    val file: JsonObject? = null,
    val decoded: JsonObject? = null,
    val chosenBy: String? = null,
)

/** Whether the app was idle over the session: its server's requests served and its queue's jobs, before and after. */
data class BenchIdle(val servedBefore: Long, val servedAfter: Long, val jobsBefore: Long, val jobsAfter: Long,
                     val runningBefore: Boolean, val runningAfter: Boolean) {
    val idle: Boolean get() = servedAfter == servedBefore && jobsAfter == jobsBefore && !runningBefore && !runningAfter
}

/**
 * The YouTube bench's report (the phone-youtube design's §4.3), `caracole-ytbench-<UTC>.json`: [of] makes it from what
 * a session measured, [summary] each gate's numbers from a report (§4.4; the verdicts are
 * `tests/helpers/ytbench_gate.py`'s). It names the songs as typed and nothing else of the owner's.
 *
 * What it reads of a run's stderr (yt-dlp's own words, read from the pinned 2026.11.23's source; a measurement, no
 * rule of caracole's): the JS challenge from its `Solving JS challenges using <runtime>` line (yt-dlp-ejs's
 * `jsc/_builtin/ejs.py`, logged before qjs runs) to the first line after it that isn't the challenge's (`[jsc…]` or
 * `Running QuickJS`); yt-dlp's own sleeps, its `Sleeping N seconds` lines; the clients, its `Downloading <client>
 * player API JSON` lines; the pins, its `-v` header (`[debug] yt-dlp version`, `[debug] Python`, `JS runtimes:`); and
 * each run's `ERROR:` and `WARNING:` lines, kept whole (the first real sessions confirm Y1.1's provisional patterns
 * by them). These patterns are typed here, not exported to youtube.json: they are the debug bench's own reading of
 * what it measures, no rule of caracole's for a run. No `[debug]` line is kept, and every text is scrubbed of a gate-shaped address ([HostGate.PROXY_PATTERN])
 * as a second guard: the client's redaction is the first.
 */
object BenchReport {
    const val FORMAT = 1

    private val PROXY = Regex(HostGate.PROXY_PATTERN)
    private val SOLVING = Regex("""Solving JS challenges using (\S+)""")
    private val CHALLENGE_LINE = Regex("""\[jsc|Running QuickJS""")
    private val SLEEPING = Regex("""Sleeping ([0-9]+(?:\.[0-9]+)?) seconds""")
    private val CLIENT = Regex("""Downloading (.+?) player API JSON""")
    private val YTDLP = Regex("""\[debug\] yt-dlp version (?:\S+@)?(\S+)""")
    private val PYTHON = Regex("""\[debug\] Python (\S+)""")
    private val RUNTIMES = Regex("""JS runtimes: (\S+)""")

    /** [text] with any gate-shaped address put back as the client's `<proxy>`. */
    fun scrub(text: String): String = PROXY.replace(text, YtDlpClient.PROXY_SAID)

    /** The JS challenge's time and runtime of [lines], or null where none was solved. */
    fun challenge(lines: List<Stamped>): JsonObject? {
        val at = lines.indexOfFirst { SOLVING.containsMatchIn(it.text) }
        if (at < 0) return null
        val runtime = SOLVING.find(lines[at].text)!!.groupValues[1]
        val end = lines.drop(at + 1).firstOrNull { !CHALLENGE_LINE.containsMatchIn(it.text) && !SOLVING.containsMatchIn(it.text) }
            ?: lines.last()
        return obj("seconds" to num((end.ms - lines[at].ms) / 1000.0), "runtime" to str(runtime))
    }

    /** yt-dlp's own sleeps in [lines], in seconds. */
    fun sleeps(lines: List<Stamped>): Double =
        lines.sumOf { line -> SLEEPING.find(line.text)?.groupValues?.get(1)?.toDouble() ?: 0.0 }

    /** The clients yt-dlp asked YouTube's player API as, in order, once each. */
    fun clients(lines: List<Stamped>): List<String> =
        lines.mapNotNull { CLIENT.find(it.text)?.groupValues?.get(1) }.distinct()

    /** The versions the running code reported in its `-v` header: yt-dlp, Python, the JS runtimes; null for none. */
    fun pins(runs: List<BenchRunRecord>): JsonObject {
        val lines = runs.flatMap { it.lines }
        fun first(r: Regex) = lines.firstNotNullOfOrNull { r.find(it.text)?.groupValues?.get(1) }?.let(::str) ?: JsonNull
        return obj("ytdlp" to first(YTDLP), "python" to first(PYTHON), "js_runtimes" to first(RUNTIMES))
    }

    /** Requests the gates saw after the first blocked run: the connects of every run after it. 0 by construction (a
     * session stops at its block): it says the bench sent nothing after one, never how YouTube treats the phone
     * afterwards. */
    fun afterBlockRequests(runs: List<BenchRunRecord>): Int {
        val blocked = runs.indexOfFirst { it.outcome == BLOCKED }
        if (blocked < 0) return 0
        return runs.drop(blocked + 1).sumOf { run -> run.hosts.values.sumOf { it.connects } }
    }

    /** The report of a session. */
    fun of(
        device: JsonObject,
        network: JsonObject,
        gate: String,
        mode: String,
        startedAt: String,
        idle: BenchIdle,
        budget: Pair<Int, Int>,
        budgetOf: Int,
        runs: List<BenchRunRecord>,
        killCheck: JsonObject,
        firstStart: JsonObject,
        stopped: String?,
    ): JsonObject {
        val report = obj(
            "format" to JsonPrimitive(FORMAT),
            "started_at" to str(startedAt),
            "gate" to str(gate),
            "mode" to str(mode),
            *device.entries.map { it.key to it.value }.toTypedArray(),
            "pins" to pins(runs),
            "network" to network,
            "idle" to JsonPrimitive(idle.idle),
            "idle_detail" to obj("served_before" to num(idle.servedBefore), "served_after" to num(idle.servedAfter),
                                 "jobs_before" to num(idle.jobsBefore), "jobs_after" to num(idle.jobsAfter),
                                 "running_before" to JsonPrimitive(idle.runningBefore),
                                 "running_after" to JsonPrimitive(idle.runningAfter)),
            "budget" to obj("before" to num(budget.first), "after" to num(budget.second), "of" to num(budgetOf)),
            "runs" to JsonArray(runs.map(::runJson)),
            "after_block_requests" to num(afterBlockRequests(runs)),
            "kill_check" to killCheck,
            "first_start" to firstStart,
            "stopped" to (stopped?.let { str(scrub(it)) } ?: JsonNull),
        )
        return JsonObject(report + ("summary" to summary(report)))
    }

    private fun runJson(run: BenchRunRecord): JsonObject {
        val kept = run.lines.map { it.text.trim() }.filter { it.startsWith("ERROR:") || it.startsWith("WARNING:") }
        return obj(
            "song" to str(run.song),
            "kind" to str(run.kind),
            "cache" to (run.cache?.let(::str) ?: JsonNull),
            "chosen_by" to (run.chosenBy?.let(::str) ?: JsonNull),
            "started_at" to str(run.startedAt),
            "process_start_ms" to num(run.processStartMs),
            "python_ready_ms" to num(run.pythonReadyMs),
            "seconds" to num(run.seconds),
            "challenge" to (challenge(run.lines) ?: JsonNull),
            "sleeps_seconds" to num(sleeps(run.lines)),
            "pause_seconds" to num(run.pauseSeconds),
            "clients" to JsonArray(clients(run.lines).map(::str)),
            "outcome" to str(run.outcome),
            "reason" to (run.reason?.let { str(scrub(it)) } ?: JsonNull),
            "said" to JsonArray(kept.map { str(scrub(it)) }),
            "hosts" to JsonObject(run.hosts.mapValues { (_, use) ->
                obj("connects" to num(use.connects), "bytes_up" to num(use.bytesUp), "bytes_down" to num(use.bytesDown),
                    "refused" to num(use.refused), "apart" to JsonPrimitive(use.apart))
            }),
            "uid_bytes" to (run.uidBytes?.let(::num) ?: JsonNull),
            "pss_peak_mb" to JsonObject(run.pssPeakMb.mapValues { num(it.value) }),
            "file" to (run.file ?: JsonNull),
            "decoded" to (run.decoded ?: JsonNull),
        )
    }

    /**
     * Each gate's numbers (§4.4) from a [report]: W the songs, their downloads ok and decoded, the runs blocked; T the
     * cold download's challenge, the cold song's search and download less yt-dlp's sleeps, the warm downloads' times;
     * H the hosts named, any refused by name asked for, each run's uid bytes against its gate's, and idle; B the runs
     * left unclassified and the requests after a block; F each decoded file's length against yt-dlp's duration; K
     * what the kill check left; M the peak PSS of `:youtube` and qjs together; C the first run's Python start against
     * the later runs' least.
     */
    fun summary(report: JsonObject): JsonObject {
        val runs = report["runs"]?.jsonArray.orEmpty().map { it.jsonObject }
        fun d(o: JsonObject, k: String) = o[k]?.let { if (it is JsonNull) null else it.jsonPrimitive.doubleOrNull }
        fun s(o: JsonObject, k: String) = o[k]?.let { if (it is JsonNull) null else it.jsonPrimitive.content }
        val downloads = runs.filter { s(it, "kind") == "download" }
        val cold = downloads.firstOrNull { s(it, "cache") == "cold" }
        val coldSong = cold?.let { c -> runs.filter { s(it, "song") == s(c, "song") } }.orEmpty()
        val coldWhole = if (coldSong.isEmpty()) null
            else coldSong.sumOf { (d(it, "seconds") ?: 0.0) - (d(it, "sleeps_seconds") ?: 0.0) }
        val hosts = runs.flatMap { it["hosts"]?.jsonObject?.keys.orEmpty() }.distinct()
        val refusedByName = runs.flatMap { r -> r["hosts"]?.jsonObject?.keys.orEmpty() }
            .filter { HostGate.HostRule.refusedByName(it) }.distinct()
        val bytes = runs.map { r ->
            val gate = r["hosts"]?.jsonObject?.values.orEmpty().sumOf {
                val u = it.jsonObject
                (u["bytes_up"]?.jsonPrimitive?.longOrNull ?: 0) + (u["bytes_down"]?.jsonPrimitive?.longOrNull ?: 0)
            }
            obj("uid" to (r["uid_bytes"] ?: JsonNull), "gate" to num(gate))
        }
        val classes = setOf("ok", "blocked", "unavailable", "outdated", "pass_over", "gate_refused", "error")
        val fileGaps = downloads.mapNotNull { r ->
            val decoded = r["decoded"]?.takeIf { it !is JsonNull }?.jsonObject ?: return@mapNotNull null
            val file = r["file"]?.takeIf { it !is JsonNull }?.jsonObject ?: return@mapNotNull null
            val frames = decoded["frames"]?.jsonPrimitive?.doubleOrNull ?: return@mapNotNull null
            val rate = decoded["rate"]?.jsonPrimitive?.doubleOrNull?.takeIf { it > 0 } ?: return@mapNotNull null
            val duration = file["duration"]?.jsonPrimitive?.doubleOrNull ?: return@mapNotNull null
            num(abs(frames / rate - duration))
        }
        val peak = runs.maxOfOrNull { r ->
            r["pss_peak_mb"]?.jsonObject?.values.orEmpty().sumOf { it.jsonPrimitive.doubleOrNull ?: 0.0 }
        }
        val ready = runs.mapNotNull { d(it, "python_ready_ms")?.takeIf { ms -> ms >= 0 } }
        val kill = report["kill_check"]?.jsonObject
        return obj(
            "W" to obj("songs" to num(runs.mapNotNull { s(it, "song") }.distinct().size),
                       "downloads_ok" to num(downloads.count { s(it, "outcome") == "ok" }),
                       "decoded" to num(downloads.count { it["decoded"] != null && it["decoded"] !is JsonNull }),
                       "blocked" to num(runs.count { s(it, "outcome") == BLOCKED })),
            "T" to obj("cold_challenge_s" to (cold?.get("challenge")?.takeIf { it !is JsonNull }?.jsonObject?.get("seconds") ?: JsonNull),
                       "cold_whole_s_less_sleeps" to (coldWhole?.let(::num) ?: JsonNull),
                       "warm_downloads_s" to JsonArray(downloads.filter { s(it, "cache") == "warm" }
                           .map { it["seconds"] ?: JsonNull })),
            "H" to obj("hosts" to JsonArray(hosts.map(::str)),
                       "refused_by_name_asked" to JsonArray(refusedByName.map(::str)),
                       "bytes" to JsonArray(bytes), "idle" to (report["idle"] ?: JsonNull)),
            "B" to obj("unclassified" to num(runs.count { s(it, "outcome") !in classes }),
                       "after_block_requests" to (report["after_block_requests"] ?: num(0))),
            "F" to obj("decoded_vs_duration_s" to JsonArray(fileGaps)),
            "K" to obj("run" to (kill?.get("run") ?: JsonNull),
                       "left" to (kill?.get("left")?.takeIf { it !is JsonNull }?.jsonArray?.size?.let(::num) ?: JsonNull)),
            "M" to obj("pss_peak_mb" to (peak?.let(::num) ?: JsonNull)),
            "C" to obj("first_python_ready_ms" to (ready.firstOrNull()?.let(::num) ?: JsonNull),
                       "least_later_python_ready_ms" to (ready.drop(1).minOrNull()?.let(::num) ?: JsonNull)),
        )
    }

    /** What the screen says of a report: one line a run, then the stop. */
    fun said(report: JsonObject): List<String> {
        val out = mutableListOf<String>()
        for (r in report["runs"]?.jsonArray.orEmpty().map { it.jsonObject }) {
            val cache = r["cache"]?.takeIf { it !is JsonNull }?.jsonPrimitive?.content?.let { " ($it)" } ?: ""
            val reason = r["reason"]?.takeIf { it !is JsonNull }?.jsonPrimitive?.content?.let { ": $it" } ?: ""
            out += "${r["kind"]!!.jsonPrimitive.content}$cache of “${r["song"]!!.jsonPrimitive.content}”: " +
                "${r["outcome"]!!.jsonPrimitive.content} in ${r["seconds"]}s$reason"
        }
        report["stopped"]?.takeIf { it !is JsonNull }?.let { out += "stopped: ${it.jsonPrimitive.content}" }
        return out.map(::scrub)
    }

    const val BLOCKED = "blocked"

    private fun obj(vararg pairs: Pair<String, JsonElement>) = JsonObject(linkedMapOf(*pairs))
    private fun str(s: String) = JsonPrimitive(s)
    private fun num(n: Number) = JsonPrimitive(n)
}
