package io.github.danielhp95.caracole.autochords.testing

import io.github.danielhp95.caracole.autochords.frontend.Cqt
import io.github.danielhp95.caracole.autochords.frontend.Mel
import io.github.danielhp95.caracole.autochords.testing.SoxrRecords.str
import io.github.danielhp95.caracole.core.testing.Corpus
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.double
import kotlinx.serialization.json.int
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import java.nio.ByteBuffer
import java.nio.ByteOrder
import java.util.Base64
import kotlin.math.abs
import kotlin.math.sqrt

/**
 * vectors/autochords/frontend.jsonl read (tests/test_conformance_autochords_models.py): its meta's `gates` (the
 * design's B1 feature gate), each clip's log-CQT (float32) and log-mel (stored as float16), and each excerpt's
 * log-CQT; and [score], the gate applied to what [Cqt] and [Mel] make of the same samples, the committed WAVs read as
 * soundfile reads them ([SoxrRecords.wav]).
 */
object FrontendRecords {
    class Gate(val cosineMedianMin: Double, val cosineMin: Double, val silentWithin: Double, val cqtFloor: Double,
               val melFloor: Double)

    /** One record's samples (a whole clip, or an excerpt of one) and the stored features of them: [mel] is null for
     * an excerpt, which has none. */
    class Source(val name: String, val samples: FloatArray, val cqt: FloatArray, val mel: FloatArray?)

    private val lines by lazy { Corpus.lines("autochords/frontend.jsonl").drop(1) }
    val meta: JsonObject by lazy { lines.first { it.str("kind") == "meta" } }

    val gate: Gate by lazy {
        val g = meta["gates"]!!.jsonObject
        require(g.str("frames") == "equal")
        val floors = g["floors"]!!.jsonObject
        Gate(g["cosine_median_min"]!!.jsonPrimitive.double, g["cosine_min"]!!.jsonPrimitive.double,
             g["silent_within"]!!.jsonPrimitive.double, floors["cqt"]!!.jsonPrimitive.double,
             floors["mel"]!!.jsonPrimitive.double)
    }

    /** The clips, then the excerpts. */
    val sources: List<Source> by lazy {
        lines.filter { it.str("kind") == "clip" || it.str("kind") == "excerpt" }.map(::source)
    }

    private fun source(record: JsonObject): Source {
        val name = record["wav"]!!.jsonObject.str("fixture")
        val wav = SoxrRecords.wav(Corpus.fixture(name))
        if (record.str("kind") == "clip") {
            check(wav.size == record["samples"]!!.jsonPrimitive.int) { "$name: its samples' count" }
            return Source(record.str("clip"), wav, matrix(record["cqt"]!!.jsonObject, 144),
                          matrix(record["mel"]!!.jsonObject, 128))
        }
        val offset = record["offset"]!!.jsonPrimitive.int
        val count = record["count"]!!.jsonPrimitive.int
        return Source("$name[$offset, +$count]", wav.copyOfRange(offset, offset + count),
                      matrix(record["cqt"]!!.jsonObject, 144), null)
    }

    /** A stored `[frames, width]` array, float32 or float16, as float32. */
    private fun matrix(array: JsonObject, width: Int): FloatArray {
        val shape = array["shape"]!!.jsonArray.map { it.jsonPrimitive.int }
        check(shape.size == 2 && shape[1] == width) { "a [frames, $width] array, not $shape" }
        val bytes = ByteBuffer.wrap(Base64.getDecoder().decode(array.str("base64"))).order(ByteOrder.LITTLE_ENDIAN)
        val out = when (array.str("dtype")) {
            "float32" -> FloatArray(bytes.remaining() / 4) { bytes.float }
            "float16" -> FloatArray(bytes.remaining() / 2) { half(bytes.short.toInt() and 0xffff) }
            else -> error("no float array: ${array.str("dtype")}")
        }
        check(out.size == shape[0] * shape[1])
        return out
    }

    /** An IEEE half's value. */
    fun half(bits: Int): Float {
        val sign = if (bits and 0x8000 != 0) -1f else 1f
        val exponent = (bits shr 10) and 0x1f
        val mantissa = bits and 0x3ff
        return sign * when (exponent) {
            0 -> mantissa / 1024f / 16384f
            0x1f -> if (mantissa == 0) Float.POSITIVE_INFINITY else Float.NaN
            else -> Float.fromBits(((exponent - 15 + 127) shl 23) or (mantissa shl 13))
        }
    }

    /** What the gate makes of [got] against [want], both `[frames, width]`. */
    class Score(val what: String, val frames: Int, val wanted: Int, val silent: Int, val loudWhereSilent: Int,
                val median: Double, val least: Double, val leastAt: Int, val maxAbs: Double, val millis: Long) {
        fun passes(gate: Gate): Boolean = frames == wanted && loudWhereSilent == 0 &&
            median >= gate.cosineMedianMin && least >= gate.cosineMin

        override fun toString(): String =
            "$what: $frames frames of $wanted ($silent silent" +
                (if (loudWhereSilent > 0) ", $loudWhereSilent of them not silent here" else "") +
                "), cosine median 1 - ${"%.2e".format(1 - median)}, least 1 - ${"%.2e".format(1 - least)} " +
                "(frame $leastAt), max abs ${"%.3g".format(maxAbs)}, $millis ms"
    }

    fun score(what: String, got: FloatArray, want: FloatArray, width: Int, floor: Double, millis: Long,
              gate: Gate = this.gate): Score {
        val frames = got.size / width
        val wanted = want.size / width
        if (frames != wanted || got.size % width != 0) {
            return Score(what, frames, wanted, 0, 0, Double.NaN, Double.NaN, -1, Double.NaN, millis)
        }
        fun silent(a: FloatArray, f: Int) = (0 until width).all { abs(a[f * width + it] - floor) <= gate.silentWithin }
        val cosines = ArrayList<Double>()
        var silentFrames = 0
        var loud = 0
        var least = Double.POSITIVE_INFINITY
        var leastAt = -1
        var maxAbs = 0.0
        for (f in 0 until frames) {
            for (i in 0 until width) {
                maxAbs = maxOf(maxAbs, abs(got[f * width + i].toDouble() - want[f * width + i]))
            }
            if (silent(want, f)) {
                silentFrames++
                if (!silent(got, f)) loud++
                continue
            }
            var dot = 0.0
            var a = 0.0
            var b = 0.0
            for (i in 0 until width) {
                val x = got[f * width + i].toDouble()
                val y = want[f * width + i].toDouble()
                dot += x * y
                a += x * x
                b += y * y
            }
            // A frame of ours with nothing in it, where the stored one has something, is as far as a frame can be.
            val cosine = (dot / (sqrt(a) * sqrt(b))).takeUnless { it.isNaN() } ?: -1.0
            cosines += cosine
            if (cosine < least) {
                least = cosine
                leastAt = f
            }
        }
        cosines.sort()
        val n = cosines.size
        val median = when {
            n == 0 -> Double.NaN
            n % 2 == 1 -> cosines[n / 2]
            else -> (cosines[n / 2 - 1] + cosines[n / 2]) / 2
        }
        return Score(what, frames, wanted, silentFrames, loud, median, if (n == 0) Double.NaN else least, leastAt,
                     maxAbs, millis)
    }

    /** [Cqt.logFeatures] of [source]'s samples against its stored log-CQT. */
    fun cqt(source: Source): Score {
        val start = System.nanoTime()
        val got = Cqt.logFeatures(source.samples)
        val millis = (System.nanoTime() - start) / 1_000_000
        return score("${source.name} log-CQT", got, source.cqt, Cqt.BINS, gate.cqtFloor, millis)
    }

    /** [Mel.logMel] of [source]'s samples against its stored log-mel. */
    fun mel(source: Source): Score {
        val start = System.nanoTime()
        val got = Mel.logMel(source.samples)
        val millis = (System.nanoTime() - start) / 1_000_000
        return score("${source.name} log-mel", got, source.mel!!, Mel.MELS, gate.melFloor, millis)
    }
}
