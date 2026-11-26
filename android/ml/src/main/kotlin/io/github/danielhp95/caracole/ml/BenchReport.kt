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
 * One model's run over one file: [model] is [BenchReport.BTC], [BenchReport.BEATS_FP16] or [BenchReport.BEATS_FP32];
 * [pass] counts the file's back-to-back runs from 1; [cold] marks a session's first run, its load in its time;
 * [screen] is "on" or "off" as the run began; [nanos] the model's time alone (its inputs read before), [duration]
 * the audio's seconds; [samples] the looks taken while it ran; [rssPeakKb] the process's peak RSS over it (VmHWM,
 * reset as it began); the battery's charge counter, µAh, before and after.
 */
data class Run(
    val file: String, val model: String, val pass: Int, val threads: Int, val arena: Boolean, val screen: String,
    val cold: Boolean, val nanos: Long, val duration: Double, val samples: List<Sample>, val rssPeakKb: Long?,
    val batteryStartUah: Long?, val batteryEndUah: Long?,
) {
    val seconds: Double get() = nanos / 1e9
    val rtf: Double get() = seconds / duration
    val pssPeakKb: Long? get() = samples.mapNotNull { it.pssKb }.maxOrNull()
}

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
data class Parity(val gates: Gates, val btc: List<BtcParity>, val beats: List<BeatParity>) {
    /** Every entry passes, and there is one at least. */
    val pass: Boolean get() = (btc.isNotEmpty() || beats.isNotEmpty()) && btc.all { it.pass(gates) } &&
        beats.all { it.pass(gates) }
}

/**
 * The Chords bench's report, `caracole-bench-<UTC>.json` (the design's §9.1): the phone ([Device]: model, SoC,
 * Android, and the app's version), the runtime, every run ([Run]: seconds, RTF, the process's peak PSS and RSS, the
 * thermal states seen and the highest headroom, the battery's charge-counter change), a summary of the warm runs a
 * setting and screen state (Gate B0's speed, RTF ≤ [RTF_GATE] sustained, and memory, peak RSS ≤ [MEMORY_GATE_MB]),
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

    fun of(runs: List<Run>, parity: Parity, device: Device, made: String): JsonObject = buildJsonObject {
        put("bench", FORMAT)
        put("made", made)
        put("device", device.device)
        put("soc", device.soc)
        put("android", device.android)
        put("runtime", OrtModels.RUNTIME)
        put("app", device.app)
        put("runs", JsonArray(runs.map(::run)))
        put("summary", JsonArray(summary(runs)))
        put("parity", parity(parity))
    }

    private fun run(r: Run): JsonObject = buildJsonObject {
        put("file", r.file)
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
        put("rss_peak_mb", mb(r.rssPeakKb))
        put("thermal", JsonArray(r.samples.map { it.thermal }.distinct().map(::JsonPrimitive)))
        put("headroom_max", r.samples.mapNotNull { it.headroom }.maxOrNull()
            ?.let { JsonPrimitive(rounded(it.toDouble(), 1000)) } ?: JsonNull)
        put("battery_uah", if (r.batteryStartUah != null && r.batteryEndUah != null)
            JsonPrimitive(r.batteryEndUah - r.batteryStartUah) else JsonNull)
    }

    private fun summary(runs: List<Run>): List<JsonObject> =
        runs.filter { !it.cold }.groupBy { listOf(it.model, it.threads, it.arena, it.screen) }.map { (_, group) ->
            val first = group.first()
            val rtfs = group.map { it.rtf }.sorted()
            val median = if (rtfs.size % 2 == 1) rtfs[rtfs.size / 2]
            else (rtfs[rtfs.size / 2 - 1] + rtfs[rtfs.size / 2]) / 2
            val rss = group.mapNotNull { it.rssPeakKb }.maxOrNull()
            buildJsonObject {
                put("model", first.model)
                put("threads", first.threads)
                put("arena", first.arena)
                put("screen", first.screen)
                put("runs", group.size)
                put("rtf_median", rounded(median, 10_000))
                put("rtf_max", rounded(rtfs.last(), 10_000))
                put("pss_peak_mb", mb(group.mapNotNull { it.pssPeakKb }.maxOrNull()))
                put("rss_peak_mb", mb(rss))
                put("speed_ok", rtfs.last() <= RTF_GATE)
                put("memory_ok", rss?.let { JsonPrimitive(it / 1024.0 <= MEMORY_GATE_MB) } ?: JsonNull)
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
        put("btc", JsonArray(p.btc.map { b ->
            buildJsonObject {
                put("file", b.file)
                put("threads", b.threads)
                put("arena", b.arena)
                put("frames", b.frames)
                put("agreement", rounded(b.agreement, 1_000_000))
                put("differ", b.differMargins.size)
                put("differ_over_margin", b.differOverMargin(p.gates))
                put("logits_max_abs", b.logitsMaxAbs.toDouble())
                put("pass", b.pass(p.gates))
            }
        }))
        put("beats", JsonArray(p.beats.map { b ->
            buildJsonObject {
                put("file", b.file)
                put("model", b.model)
                put("threads", b.threads)
                put("arena", b.arena)
                put("logits_max_abs", b.logitsMaxAbs.toDouble())
                put("beats_f", b.beatsF?.let { JsonPrimitive(rounded(it, 1_000_000)) } ?: JsonNull)
                put("downbeats_f", b.downbeatsF?.let { JsonPrimitive(rounded(it, 1_000_000)) } ?: JsonNull)
                put("pass", b.pass(p.gates))
            }
        }))
    }

    private fun rounded(x: Double, scale: Int): Double = round(x * scale) / scale

    private fun mb(kb: Long?): JsonElement = kb?.let { JsonPrimitive(rounded(it / 1024.0, 10)) } ?: JsonNull
}
