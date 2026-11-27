package io.github.danielhp95.caracole.ml

import android.os.Build
import kotlin.math.abs
import kotlin.math.round
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonArray
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put

/** What a report says of the phone, and nothing more: its maker and model, its SoC, its Android, the app's version. */
data class Device(val device: String, val soc: String, val android: String, val app: String) {
    companion object {
        /** This phone's, from [Build]: the SoC from Android 12 on (`SOC_MANUFACTURER`, `SOC_MODEL`), else unknown. */
        fun here(app: String): Device = Device(
            device = "${Build.MANUFACTURER} ${Build.MODEL}",
            soc = if (Build.VERSION.SDK_INT >= 31) "${Build.SOC_MANUFACTURER} ${Build.SOC_MODEL}" else Heat.UNKNOWN,
            android = "${Build.VERSION.RELEASE} (API ${Build.VERSION.SDK_INT})",
            app = app,
        )
    }
}

/** One look at the process while a model ran: its PSS in kB (null where the platform gave none), the phone's thermal
 * status ([Heat]'s names) and its thermal headroom (null where it gave none). */
data class Sample(val pssKb: Long?, val thermal: String, val headroom: Float?)

/**
 * One model's run over one file: [kind] is [BenchInput.CLIP] (a committed clip, parity's) or [BenchInput.REFERENCE]
 * (one of the owner's songs, Gate B0's); [model] is [BenchReport.BTC], [BenchReport.BEATS_FP16] or
 * [BenchReport.BEATS_FP32]; [pass] counts the file's back-to-back runs from 1; [cold] marks a session's first run (its
 * load apart, [Session.loadSeconds]); [screen] is "on" or "off" as the run began; [nanos] the model's time alone (its
 * inputs read before), [duration] the audio's seconds; [samples] the looks taken while it ran, one a second (a run of
 * BTC's lasts a tenth of that: its PSS is a look taken around the call); [rssPeakKb] the process's true peak RSS over
 * it (VmHWM, reset as it began), kept only where [reset] says the reset took (else it may be an earlier run's); the
 * battery's charge counter, µAh, before and after; [lengthNote], its input's ([BenchInput.lengthNote]).
 */
data class Run(
    val file: String, val kind: String, val model: String, val pass: Int, val threads: Int, val arena: Boolean,
    val screen: String, val cold: Boolean, val nanos: Long, val duration: Double, val samples: List<Sample>,
    val reset: Boolean, val rssPeakKb: Long?, val batteryStartUah: Long?, val batteryEndUah: Long?,
    val lengthNote: String? = null,
) {
    val seconds: Double get() = nanos / 1e9
    val rtf: Double get() = seconds / duration
    val pssPeakKb: Long? get() = samples.mapNotNull { it.pssKb }.maxOrNull()

    /** The peak RSS where it is this run's alone. */
    val truePeakKb: Long? get() = rssPeakKb.takeIf { reset }
}

/**
 * One model's session, in a process of its own (the bench starts one a session, so that its peak is its own): its
 * model, thread count and arena setting, the screen round it ran in ("on" or "off"), the model's load ([loadSeconds],
 * its session opened before the first run), the process's peak RSS over its whole life (VmHWM as it ends: the
 * session's own, its inputs' reading in it), the battery's charge counter as it began and ended, and why it ended
 * early: [failure] (an error, or its process dead) or [stopped] (the heat guard); its process's [pid], and [fresh],
 * true only when the bench saw the earlier session's process gone before it began this one; [complete], every run it
 * planned done; [outOfMemory], known to have run out of memory (an [OutOfMemoryError], ONNX Runtime's "Failed to
 * allocate memory", or Android's own word that it killed the process for memory).
 */
data class Session(
    val model: String, val threads: Int, val arena: Boolean, val round: String, val loadSeconds: Double?,
    val rssPeakKb: Long?, val batteryStartUah: Long?, val batteryEndUah: Long?, val failure: String?,
    val stopped: String?, val pid: Int? = null, val fresh: Boolean = false, val complete: Boolean = false,
    val outOfMemory: Boolean = false,
) {
    /** The whole-life peak where it is a whole hearing's and this session's alone: its process fresh (no earlier
     * session's still up as it began), every run it planned done ([complete]: no failure, nothing stopped it), a peak
     * read. Gate B0's memory: a hearing is a load and a first run, and this holds both. */
    val hearingPeakKb: Long? get() = rssPeakKb.takeIf { fresh && complete && failure == null && stopped == null }
}

/** The battery over the whole bench: its charge counter and percent at its start and end, and whether it was
 * plugged in as it began. */
data class Battery(
    val startUah: Long?, val endUah: Long?, val startPercent: Int?, val endPercent: Int?, val plugged: Boolean?,
)

/** B0's gates as the computer's records state them (models.jsonl's meta `gates`, §4.2), never typed here. */
data class Gates(
    val btcMarginUnder: Double, val btcLogitsMaxAbs: Double, val fp32LogitsMaxAbs: Double, val fp16FMin: Double,
    val trim: Double, val window: Double,
)

/** BTC on one file against the computer's logits: how many frames' argmax agree, the computer's top-two margin at
 * each frame that doesn't ([differMargins]), and those of them where it was [Gates.btcMarginUnder] or more (a near
 * tie may go either way: the gate's allowance). */
data class BtcParity(
    val file: String, val threads: Int, val arena: Boolean, val frames: Int, val agreement: Double,
    val differMargins: List<Float>, val logitsMaxAbs: Float,
) {
    /** The frames that disagree, by the computer's margin there. */
    fun differOverMargin(gates: Gates): Int = differMargins.count { it >= gates.btcMarginUnder }

    fun pass(gates: Gates): Boolean = differOverMargin(gates) == 0 && logitsMaxAbs <= gates.btcLogitsMaxAbs

    companion object {
        /** [got] against [want], both `[frames, CLASSES]` (the first [frames] frames of [got]; its padding after),
         * [margins] the computer's top-two margin of each frame. */
        fun of(file: String, threads: Int, arena: Boolean, got: FloatArray, want: FloatArray, margins: FloatArray,
               frames: Int): BtcParity {
            val classes = OrtModels.CLASSES
            require(want.size == frames * classes && got.size >= frames * classes && margins.size == frames)
            var most = 0f
            val differ = mutableListOf<Float>()
            for (t in 0 until frames) {
                var g = 0
                var w = 0
                for (k in 0 until classes) {
                    val i = t * classes + k
                    most = maxOf(most, abs(got[i] - want[i]))
                    if (got[i] > got[t * classes + g]) g = k
                    if (want[i] > want[t * classes + w]) w = k
                }
                if (g != w) differ += margins[t]
            }
            return BtcParity(file, threads, arena, frames, (frames - differ.size).toDouble() / frames, differ, most)
        }

        /** Each frame's top two logits' difference, as the computer's records store it, for a reference that keeps
         * only the logits. */
        fun margins(logits: FloatArray, frames: Int): FloatArray {
            val classes = OrtModels.CLASSES
            return FloatArray(frames) { t ->
                var first = Float.NEGATIVE_INFINITY
                var second = Float.NEGATIVE_INFINITY
                for (k in 0 until classes) {
                    val v = logits[t * classes + k]
                    if (v > first) { second = first; first = v } else if (v > second) second = v
                }
                first - second
            }
        }
    }
}

/** beat_this on one file against the computer's: its logits' largest difference, and its beats' and downbeats'
 * F-measure (the minimal postprocessor's peaks, after the trim, within the window); null F where the computer's
 * reference holds no beat after the trim. */
data class BeatParity(
    val file: String, val model: String, val threads: Int, val arena: Boolean, val logitsMaxAbs: Float,
    val beatsF: Double?, val downbeatsF: Double?,
) {
    fun pass(gates: Gates): Boolean {
        val fs = beatsF != null && downbeatsF != null
        return when (model) {
            BenchReport.BEATS_FP32 -> logitsMaxAbs <= gates.fp32LogitsMaxAbs
            else -> fs && beatsF!! >= gates.fp16FMin && downbeatsF!! >= gates.fp16FMin
        }
    }

    companion object {
        fun of(file: String, model: String, threads: Int, arena: Boolean, beat: FloatArray, downbeat: FloatArray,
               wantBeat: FloatArray, wantDownbeat: FloatArray, wantBeats: List<Double>, wantDownbeats: List<Double>,
               fps: Int, gates: Gates): BeatParity {
            require(beat.size == wantBeat.size && downbeat.size == wantDownbeat.size)
            var most = 0f
            for (i in beat.indices) most = maxOf(most, abs(beat[i] - wantBeat[i]))
            for (i in downbeat.indices) most = maxOf(most, abs(downbeat[i] - wantDownbeat[i]))
            val (beats, downbeats) = BeatThis.peaks(beat, downbeat, fps)
            fun f(reference: List<Double>, estimated: List<Double>): Double? {
                val r = BeatThis.trimmed(reference, gates.trim)
                return if (r.isEmpty()) null
                else BeatThis.fMeasure(r, BeatThis.trimmed(estimated, gates.trim), gates.window)
            }
            return BeatParity(file, model, threads, arena, most, f(wantBeats, beats), f(wantDownbeats, downbeats))
        }
    }
}

/** Every file's parity of a bench, under [gates]. */
data class Parity(
    val gates: Gates, val btc: List<BtcParity>, val beats: List<BeatParity>,
    val laterBtc: List<BtcParity> = emptyList(), val laterBeats: List<BeatParity> = emptyList(),
    val differs: List<Differs> = emptyList(),
) {
    /** Every entry passes, a later session's too, and there is one at least. */
    val pass: Boolean get() = (btc.isNotEmpty() || beats.isNotEmpty()) &&
        (btc + laterBtc).all { it.pass(gates) } && (beats + laterBeats).all { it.pass(gates) }
}

/** A file's parity under one setting that a later session ([session], an index of the report's `sessions`) found
 * otherwise than the first ([firstSession]): both entries, [first] and [other] ([BtcParity] or [BeatParity]). */
data class Differs(val file: String, val model: String, val threads: Int, val arena: Boolean, val firstSession: Int,
                   val session: Int, val first: Any, val other: Any)

/**
 * The Chords bench's report, `caracole-bench-<UTC>.json` (the design's §9.1): the phone ([Device]: model, SoC,
 * Android, and the app's version), the runtime, every run ([Run]: seconds, RTF, the process's peak PSS and RSS, the
 * thermal states seen and the highest headroom, the battery's charge-counter change), each [Session] and the whole
 * [Battery], a summary of the warm runs a setting and screen state, the owner's songs ("references": Gate B0's speed,
 * RTF ≤ [RTF_GATE] sustained, and memory, true peak RSS ≤ [MEMORY_GATE_MB]) apart from the committed clips ("clips"),
 * and parity with the computer ([Parity]). Numbers are rounded for reading: seconds to the millisecond, megabytes to
 * a tenth.
 */
object BenchReport {
    const val FORMAT = 1
    const val BTC = "btc"
    const val BEATS_FP16 = "beat_this fp16"
    const val BEATS_FP32 = "beat_this fp32"
    const val RTF_GATE = 0.125
    const val MEMORY_GATE_MB = 1024.0

    fun of(runs: List<Run>, parity: Parity, device: Device, made: String, sessions: List<Session> = emptyList(),
           battery: Battery? = null): JsonObject = buildJsonObject {
        put("bench", FORMAT)
        put("made", made)
        put("device", device.device)
        put("soc", device.soc)
        put("android", device.android)
        put("runtime", OrtModels.RUNTIME)
        put("app", device.app)
        put("battery", battery?.let { b ->
            buildJsonObject {
                put("start_uah", b.startUah)
                put("end_uah", b.endUah)
                put("change_uah", if (b.startUah != null && b.endUah != null) b.endUah - b.startUah else null)
                put("start_percent", b.startPercent)
                put("end_percent", b.endPercent)
                put("plugged", b.plugged)
            }
        } ?: JsonNull)
        put("sessions", JsonArray(sessions.map(::session)))
        // The references whose duration their mel disagreed with, a file once: timed by the mel's length instead.
        put("length_flags", JsonArray(runs.filter { it.lengthNote != null }.distinctBy { it.file }.map { r ->
            buildJsonObject {
                put("file", r.file)
                put("note", r.lengthNote)
            }
        }))
        put("runs", JsonArray(runs.map(::run)))
        put("summary", buildJsonObject {
            put("gates", buildJsonObject {
                put("memory_mb", MEMORY_GATE_MB)
                put("rtf_max", RTF_GATE)
            })
            for ((key, kind) in listOf("references" to BenchInput.REFERENCE, "clips" to BenchInput.CLIP)) {
                val ofKind = runs.filter { it.kind == kind }
                val block = summary(ofKind, sessions, gate = kind == BenchInput.REFERENCE)
                put(key, JsonArray(block))
                if (block.isEmpty() && ofKind.isNotEmpty()) {
                    put("${key}_note", "every run of these was its session's first run (cold), which the summary " +
                        "leaves out: run 2 passes or more for one")
                }
            }
        })
        put("parity", parity(parity))
    }

    /** The report of the sessions measured, in their order: their runs, and each file's parity under each setting
     * once (its first session's; the screen-off round runs the same settings again). */
    fun ofSessions(results: List<SessionResult>, gates: Gates, device: Device, made: String,
                   battery: Battery? = null): JsonObject {
        val btc = mutableListOf<BtcParity>()
        val beats = mutableListOf<BeatParity>()
        val laterBtc = mutableListOf<BtcParity>()
        val laterBeats = mutableListOf<BeatParity>()
        val differs = mutableListOf<Differs>()
        val firstOf = mutableMapOf<List<Any>, Pair<Int, Any>>()
        results.forEachIndexed { i, r ->
            for (b in r.btc) {
                val key = listOf(BTC, b.file, b.threads, b.arena)
                val known = firstOf[key]
                if (known == null) {
                    firstOf[key] = i to b
                    btc += b
                } else {
                    laterBtc += b
                    if (known.second != b) differs += Differs(b.file, BTC, b.threads, b.arena, known.first, i,
                        known.second, b)
                }
            }
            for (b in r.beats) {
                val key = listOf(b.model, b.file, b.threads, b.arena)
                val known = firstOf[key]
                if (known == null) {
                    firstOf[key] = i to b
                    beats += b
                } else {
                    laterBeats += b
                    if (known.second != b) differs += Differs(b.file, b.model, b.threads, b.arena, known.first, i,
                        known.second, b)
                }
            }
        }
        return of(results.flatMap { it.runs }, Parity(gates, btc, beats, laterBtc, laterBeats, differs), device,
            made, results.map { it.session }, battery)
    }

    private fun session(s: Session): JsonObject = buildJsonObject {
        put("model", s.model)
        put("threads", s.threads)
        put("arena", s.arena)
        put("round", s.round)
        put("load_seconds", s.loadSeconds?.let { rounded(it, 1000) })
        put("rss_peak_mb", mb(s.rssPeakKb))
        put("battery_uah", if (s.batteryStartUah != null && s.batteryEndUah != null)
            s.batteryEndUah - s.batteryStartUah else null)
        put("failure", s.failure)
        put("stopped", s.stopped)
        put("pid", s.pid)
        put("fresh", s.fresh)
        put("complete", s.complete)
        put("out_of_memory", s.outOfMemory)
    }

    private fun run(r: Run): JsonObject = buildJsonObject {
        put("file", r.file)
        put("kind", r.kind)
        put("model", r.model)
        put("pass", r.pass)
        put("threads", r.threads)
        put("arena", r.arena)
        put("screen", r.screen)
        put("cold", r.cold)
        put("seconds", rounded(r.seconds, 1000))
        put("duration", rounded(r.duration, 1000))
        put("rtf", rounded(r.rtf, 10_000))
        put("pss_peak_mb", mb(r.pssPeakKb))
        put("reset", r.reset)
        put("rss_peak_mb", mb(r.truePeakKb))
        put("thermal", JsonArray(r.samples.map { it.thermal }.distinct().map(::JsonPrimitive)))
        put("headroom_max", r.samples.mapNotNull { it.headroom }.maxOrNull()
            ?.let { JsonPrimitive(rounded(it.toDouble(), 1000)) } ?: JsonNull)
        put("battery_uah", if (r.batteryStartUah != null && r.batteryEndUah != null)
            JsonPrimitive(r.batteryEndUah - r.batteryStartUah) else JsonNull)
        put("length_note", r.lengthNote)
    }

    /** The warm runs a setting and screen state; with [gate], Gate B0's flags beside (the references': the clips'
     * block is parity's, their chunks' overhead no measure of a song's). */
    private fun summary(runs: List<Run>, sessions: List<Session>, gate: Boolean): List<JsonObject> =
        runs.filter { !it.cold }.groupBy { listOf(it.model, it.threads, it.arena, it.screen) }.map { (_, group) ->
            val first = group.first()
            val rtfs = group.map { it.rtf }.sorted()
            val median = if (rtfs.size % 2 == 1) rtfs[rtfs.size / 2]
            else (rtfs[rtfs.size / 2 - 1] + rtfs[rtfs.size / 2]) / 2
            val steady = group.mapNotNull { it.truePeakKb }.maxOrNull()
            // The hearing's: the whole-life peaks of this setting's sessions, each a load, a first run and the rest;
            // none where a session has none to trust.
            val theirs = sessions.filter {
                it.model == first.model && it.threads == first.threads && it.arena == first.arena &&
                    it.round == first.screen
            }
            val hearing = if (theirs.isEmpty() || theirs.any { it.hearingPeakKb == null }) null
            else theirs.maxOf { it.hearingPeakKb!! }
            val memoryNote = when {
                theirs.isEmpty() -> "no session of this setting measured its hearing's peak"
                theirs.any { it.outOfMemory } -> "a session of this setting could not finish for memory on this " +
                    "phone (it ran out of memory): see sessions[].failure"
                theirs.any { it.failure != null || it.stopped != null || !it.complete } ->
                    "a session of this setting didn't finish its runs, so its peak is no hearing's: see " +
                        "sessions[].failure and sessions[].stopped"
                theirs.any { !it.fresh } -> "a session of this setting didn't start in a fresh process (an earlier " +
                    "one's still up), so its peak may not be its own: see sessions[].fresh"
                hearing == null -> "a session of this setting gave no peak"
                else -> null
            }
            val memoryOk = when {
                theirs.any { it.outOfMemory } -> JsonPrimitive(false)
                hearing == null -> JsonNull
                else -> JsonPrimitive(hearing / 1024.0 <= MEMORY_GATE_MB)
            }
            buildJsonObject {
                put("model", first.model)
                put("threads", first.threads)
                put("arena", first.arena)
                put("screen", first.screen)
                put("runs", group.size)
                put("rtf_median", rounded(median, 10_000))
                put("rtf_max", rounded(rtfs.last(), 10_000))
                put("pss_peak_mb", mb(group.mapNotNull { it.pssPeakKb }.maxOrNull()))
                put("rss_steady_mb", mb(steady))
                put("rss_hearing_mb", mb(hearing))
                if (gate) {
                    put("speed_ok", rtfs.last() <= RTF_GATE)
                    put("memory_ok", memoryOk)
                    if (memoryNote != null) put("memory_note", memoryNote)
                }
            }
        }

    private fun parity(p: Parity): JsonObject = buildJsonObject {
        put("pass", p.pass)
        put("gates", buildJsonObject {
            put("btc_margin_under", p.gates.btcMarginUnder)
            put("btc_logits_max_abs", p.gates.btcLogitsMaxAbs)
            put("beats_fp32_logits_max_abs", p.gates.fp32LogitsMaxAbs)
            put("beats_fp16_f_min", p.gates.fp16FMin)
            put("trim", p.gates.trim)
            put("window", p.gates.window)
        })
        put("btc", JsonArray(p.btc.map { btc(it, p.gates) }))
        put("beats", JsonArray(p.beats.map { beat(it, p.gates) }))
        put("differs", JsonArray(p.differs.map { d ->
            buildJsonObject {
                put("file", d.file)
                put("model", d.model)
                put("threads", d.threads)
                put("arena", d.arena)
                put("first_session", d.firstSession)
                put("session", d.session)
                put("first", entry(d.first, p.gates))
                put("other", entry(d.other, p.gates))
            }
        }))
    }

    private fun entry(e: Any, gates: Gates): JsonObject = when (e) {
        is BtcParity -> btc(e, gates)
        is BeatParity -> beat(e, gates)
        else -> throw IllegalArgumentException("no parity entry: $e")
    }

    private fun btc(b: BtcParity, gates: Gates): JsonObject = buildJsonObject {
        put("file", b.file)
        put("threads", b.threads)
        put("arena", b.arena)
        put("frames", b.frames)
        put("agreement", rounded(b.agreement, 1_000_000))
        put("differ", b.differMargins.size)
        put("differ_over_margin", b.differOverMargin(gates))
        put("logits_max_abs", b.logitsMaxAbs.toDouble())
        put("pass", b.pass(gates))
    }

    private fun beat(b: BeatParity, gates: Gates): JsonObject = buildJsonObject {
        put("file", b.file)
        put("model", b.model)
        put("threads", b.threads)
        put("arena", b.arena)
        put("logits_max_abs", b.logitsMaxAbs.toDouble())
        put("beats_f", b.beatsF?.let { JsonPrimitive(rounded(it, 1_000_000)) } ?: JsonNull)
        put("downbeats_f", b.downbeatsF?.let { JsonPrimitive(rounded(it, 1_000_000)) } ?: JsonNull)
        put("pass", b.pass(gates))
    }

    private fun rounded(x: Double, scale: Int): Double = round(x * scale) / scale

    private fun mb(kb: Long?): JsonElement = kb?.let { JsonPrimitive(rounded(it / 1024.0, 10)) } ?: JsonNull
}
