package io.github.danielhp95.caracole.ml

import io.github.danielhp95.caracole.autochords.Checkpoints
import io.github.danielhp95.caracole.autochords.ChordSegment
import io.github.danielhp95.caracole.autochords.Heard
import io.github.danielhp95.caracole.autochords.Labels
import io.github.danielhp95.caracole.autochords.Scores
import io.github.danielhp95.caracole.autochords.Stages
import io.github.danielhp95.caracole.autochords.frontend.Mel
import kotlin.math.round
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.double
import kotlinx.serialization.json.doubleOrNull
import kotlinx.serialization.json.int
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import kotlinx.serialization.json.long
import kotlinx.serialization.json.put

/**
 * The design's B1 end-to-end gate (§4.2) of a whole hearing on the phone against the computer's hearing of the same
 * file: a `hearing` record (vectors/autochords/models.jsonl's, or a folder's of the owner's songs:
 * tests/helpers/autochords_reference.py `--hearings`), its thresholds the records' meta's `gates.end_to_end`
 * ([Gates.of]), never typed here. Scored ([score]): BTC's chords (the checkpoint's Harte labels) at a WCSR of
 * `wcsr_majmin_min` and `wcsr_tetrads_min` (mir_eval's rules, [Scores.wcsr]) against the chords the computer's argmax
 * names, spelled for the key; beat_this's beats and downbeats at an F of `f_measure_min` within `window`, after
 * `trim` s ([Scores.trimBeats]); and beside the gate, the lengths each model read against the computer's (BTC's
 * samples and frames, the mel's frames, the duration), with where the two hearings' frames part ([Scored.differ]).
 * Over all files ([overAll]): each gate passed by every file, its least and its mean weighted by each file's length.
 */
object EndToEnd {
    /** B1's thresholds, as the records' meta states them. */
    data class Gates(val wcsrMajminMin: Double, val wcsrTetradsMin: Double, val fMin: Double, val window: Double,
                     val trim: Double) {
        companion object {
            /** From a meta record: its `gates.end_to_end`. */
            fun of(meta: JsonObject): Gates {
                val g = meta["gates"]!!.jsonObject["end_to_end"]!!.jsonObject
                fun d(key: String) = g[key]!!.jsonPrimitive.double
                return Gates(d("wcsr_majmin_min"), d("wcsr_tetrads_min"), d("f_measure_min"), d("window"), d("trim"))
            }

            fun of(text: String): Gates = of(Json.parseToJsonElement(text).jsonObject)
        }
    }

    /** A `hearing` record: the computer's whole hearing of [name] ([sha256] where the record names its bytes). */
    class Hearing(
        val name: String, val sha256: String?, val duration: Double?, val btcSamples: Long, val btcFrames: Int,
        val argmax: IntArray, val segments: List<ChordSegment>, val melFrames: Int, val beats: List<Double>,
        val downbeats: List<Double>,
    ) {
        /** The chords the computer's argmax names, Harte labels spelled for the key, as the gate reads them. */
        val harte: List<ChordSegment> by lazy {
            Labels.spellForKey(Labels.framesToSegments(argmax, Labels.FRAME_SECONDS, Labels.vocabulary(Stages.CLASSES)))
        }

        companion object {
            fun read(text: String): Hearing = of(Json.parseToJsonElement(text).jsonObject)

            fun of(r: JsonObject): Hearing {
                require(r["kind"]?.jsonPrimitive?.content == "hearing") { "not a hearing record" }
                val file = r["file"]!!.jsonObject
                val name = file["name"]?.jsonPrimitive?.content
                    ?: file["fixture"]!!.jsonPrimitive.content.substringAfterLast('/')
                val btc = r["btc"]!!.jsonObject
                val beats = r["beats"]!!.jsonObject
                val runs = btc["argmax"]!!.jsonArray
                val argmax = IntArray(runs.sumOf { it.jsonArray[1].jsonPrimitive.int })
                var at = 0
                for (run in runs) {
                    val (k, n) = run.jsonArray.map { it.jsonPrimitive.int }
                    argmax.fill(k, at, at + n)
                    at += n
                }
                return Hearing(name, file["sha256"]?.jsonPrimitive?.content, r["duration"]?.jsonPrimitive?.doubleOrNull,
                    btc["samples"]!!.jsonPrimitive.long, btc["frames"]!!.jsonPrimitive.int, argmax,
                    btc["segments"]!!.jsonArray.map { seg ->
                        val (start, end, label) = seg.jsonArray
                        ChordSegment(start.jsonPrimitive.double, end.jsonPrimitive.double, label.jsonPrimitive.content)
                    }, beats["frames"]!!.jsonPrimitive.int,
                    beats["beats"]!!.jsonArray.map { it.jsonPrimitive.double },
                    beats["downbeats"]!!.jsonArray.map { it.jsonPrimitive.double })
            }
        }
    }

    /** One file's hearing against the computer's: the gate's four scores (an F null where the computer's holds no
     * beat after the trim), the lengths each side read, and where the frames part. */
    data class Scored(
        val file: String, val majmin: Double, val tetrads: Double, val beatsF: Double?, val downbeatsF: Double?,
        val btcFrames: Int, val computerBtcFrames: Int, val btcSamples: Long, val computerBtcSamples: Long,
        val melFrames: Int, val computerMelFrames: Int, val duration: Double, val computerDuration: Double?,
        val differ: Differ,
    ) {
        /** The gate's scores under their thresholds, in words. */
        fun gateFailures(g: Gates): List<String> = buildList {
            if (majmin < g.wcsrMajminMin) add("WCSR majmin $majmin under ${g.wcsrMajminMin}")
            if (tetrads < g.wcsrTetradsMin) add("WCSR tetrads $tetrads under ${g.wcsrTetradsMin}")
            for ((key, f) in listOf("beats" to beatsF, "downbeats" to downbeatsF)) {
                if (f == null) add("no reference $key after ${g.trim} s")
                else if (f < g.fMin) add("$key F $f under ${g.fMin}")
            }
        }

        /** The lengths that aren't the computer's, in words: each model's input is the computer's very length. */
        fun lengthFailures(): List<String> = buildList {
            if (btcSamples != computerBtcSamples) add("BTC read $btcSamples samples, the computer $computerBtcSamples")
            if (btcFrames != computerBtcFrames) add("BTC heard $btcFrames frames, the computer $computerBtcFrames")
            if (melFrames != computerMelFrames) add("beat_this read $melFrames frames, the computer $computerMelFrames")
            if (computerDuration != null && duration != computerDuration) {
                add("its length $duration s, read_audio's $computerDuration s")
            }
        }

        fun failures(g: Gates): List<String> = gateFailures(g) + lengthFailures()

        fun pass(g: Gates): Boolean = failures(g).isEmpty()

        /** A line for a test's output. */
        fun line(): String = "WCSR majmin ${r6(majmin)}, tetrads ${r6(tetrads)}; beats F ${beatsF?.let(::r6)}, " +
            "downbeats F ${downbeatsF?.let(::r6)}; BTC $btcSamples samples (the computer's $computerBtcSamples), " +
            "$btcFrames frames (${computerBtcFrames}); mel $melFrames frames ($computerMelFrames); $duration s " +
            "(read_audio's $computerDuration); ${differ.line()}"
    }

    /** Where the phone's chords and the computer's part, frame by frame (each BTC frame's label): how many differ,
     * and in which tenth of the song, with the first few runs of them in seconds. */
    data class Differ(val frames: Int, val count: Int, val tenths: List<Int>, val runs: List<Pair<Double, Double>>) {
        fun line(): String = "$count of $frames frames differ" + if (count == 0) "" else
            " (by tenth of the song: $tenths; first runs, s: ${runs.joinToString { "${it.first}-${it.second}" }})"
    }

    /** [heard] (its Harte chords, [harte], and its pcm's meta, [pcm]) against [hearing]. */
    fun score(hearing: Hearing, harte: List<ChordSegment>, heard: Heard, pcm: Checkpoints.Pcm, g: Gates): Scored {
        val frames = framesOf(harte)
        val f = listOf(hearing.beats to heard.beats, hearing.downbeats to heard.downbeats).map { (want, got) ->
            val reference = Scores.trimBeats(want, g.trim)
            if (reference.isEmpty()) null else Scores.beatF(reference, Scores.trimBeats(got, g.trim), g.window)
        }
        return Scored(hearing.name, Scores.wcsr(hearing.harte, harte, "majmin"),
            Scores.wcsr(hearing.harte, harte, "tetrads"), f[0], f[1], frames, hearing.btcFrames, pcm.btcSamples,
            hearing.btcSamples, Mel.frames(pcm.samples.toInt()), hearing.melFrames, heard.duration, hearing.duration,
            differ(hearing.harte, harte, maxOf(frames, hearing.btcFrames)))
    }

    /** The frames [segments] cover: the one whose time ([Labels.time]) is their last end. */
    fun framesOf(segments: List<ChordSegment>): Int {
        if (segments.isEmpty()) return 0
        val end = segments.last().end
        val near = Math.round(end / Labels.FRAME_SECONDS).toInt()
        return (near - 1..near + 1).first { Labels.time(it, Labels.FRAME_SECONDS) == end }
    }

    /** Each of [frames] frames' label, from segments whose times are [Labels.time]'s of their first frames ("?" past
     * their end). */
    fun frameLabels(segments: List<ChordSegment>, frames: Int): List<String> {
        val out = ArrayList<String>(frames)
        var i = 0
        for (s in segments) while (i < frames && Labels.time(i, Labels.FRAME_SECONDS) < s.end) {
            out += s.label
            i++
        }
        while (out.size < frames) out += "?"
        return out
    }

    private fun differ(reference: List<ChordSegment>, got: List<ChordSegment>, frames: Int): Differ {
        val want = frameLabels(reference, frames)
        val have = frameLabels(got, frames)
        val tenths = IntArray(10)
        val runs = mutableListOf<Pair<Double, Double>>()
        var count = 0
        var start = -1
        for (t in 0..frames) {
            val differs = t < frames && want[t] != have[t]
            if (differs) {
                count++
                tenths[minOf(9, t * 10 / maxOf(1, frames))]++
                if (start < 0) start = t
            } else if (start >= 0) {
                if (runs.size < RUNS_SAID) {
                    runs += Labels.time(start, Labels.FRAME_SECONDS) to Labels.time(t, Labels.FRAME_SECONDS)
                }
                start = -1
            }
        }
        return Differ(frames, count, tenths.toList(), runs)
    }

    /** How many runs of differing frames a [Differ] keeps. */
    const val RUNS_SAID = 12

    /** Every file's gate, and over all of them: a gate passes over all where every file passes it; each score's
     * least, and its mean weighted by each file's length (its seconds). */
    fun overAll(files: List<Scored>, g: Gates): JsonObject = buildJsonObject {
        put("files", files.size)
        put("pass", files.isNotEmpty() && files.all { it.pass(g) })
        put("gates_pass", files.isNotEmpty() && files.all { it.gateFailures(g).isEmpty() })
        put("lengths_agree", files.isNotEmpty() && files.all { it.lengthFailures().isEmpty() })
        val seconds = files.sumOf { it.duration }
        for ((key, of) in listOf<Pair<String, (Scored) -> Double?>>("wcsr_majmin" to { it.majmin },
            "wcsr_tetrads" to { it.tetrads }, "beats_f" to { it.beatsF }, "downbeats_f" to { it.downbeatsF })) {
            val values = files.mapNotNull { s -> of(s)?.let { it to s.duration } }
            put("${key}_least", values.minOfOrNull { it.first }?.let(::r6))
            put("${key}_mean", if (values.isEmpty() || seconds <= 0) null
            else r6(values.sumOf { it.first * it.second } / values.sumOf { it.second }))
        }
        put("seconds", r3(seconds))
    }

    /** One file's scores as a report's JSON. */
    fun json(s: Scored, g: Gates): JsonObject = buildJsonObject {
        put("file", s.file)
        put("wcsr_majmin", r6(s.majmin))
        put("wcsr_tetrads", r6(s.tetrads))
        put("beats_f", s.beatsF?.let(::r6))
        put("downbeats_f", s.downbeatsF?.let(::r6))
        put("btc_samples", s.btcSamples)
        put("computer_btc_samples", s.computerBtcSamples)
        put("btc_frames", s.btcFrames)
        put("computer_btc_frames", s.computerBtcFrames)
        put("mel_frames", s.melFrames)
        put("computer_mel_frames", s.computerMelFrames)
        put("duration", s.duration)
        put("computer_duration", s.computerDuration)
        put("frames_differ", s.differ.count)
        put("frames_differ_by_tenth", JsonArray(s.differ.tenths.map(::JsonPrimitive)))
        put("frames_differ_runs", JsonArray(s.differ.runs.map {
            JsonArray(listOf(JsonPrimitive(it.first), JsonPrimitive(it.second)))
        }))
        put("failures", JsonArray(s.failures(g).map(::JsonPrimitive)))
        put("pass", s.pass(g))
    }

    fun gatesJson(g: Gates): JsonElement = buildJsonObject {
        put("wcsr_majmin_min", g.wcsrMajminMin)
        put("wcsr_tetrads_min", g.wcsrTetradsMin)
        put("f_measure_min", g.fMin)
        put("window", g.window)
        put("trim", g.trim)
    }

    private fun r6(x: Double): Double = round(x * 1_000_000) / 1_000_000
    private fun r3(x: Double): Double = round(x * 1000) / 1000
}
