package io.github.danielhp95.caracole.autochords.frontend

import io.github.danielhp95.caracole.core.testing.Corpus
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.double
import kotlinx.serialization.json.int
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import java.nio.ByteBuffer
import java.nio.ByteOrder
import java.util.Base64
import kotlin.math.abs
import kotlin.test.assertEquals

/** vectors/autochords/soxr.jsonl read (tests/test_conformance_autochords_models.py): its meta and each conversion,
 * its input, its rates and python-soxr's answer. */
object SoxrRecords {
    /** The design's B1 resample gate: every sample within it. */
    const val TOLERANCE = 1e-6

    class Conversion(val family: String, val what: String, val x: FloatArray, val from: Double, val to: Double,
                     val y: FloatArray)

    private val lines by lazy { Corpus.lines("autochords/soxr.jsonl").drop(1) }
    val meta: JsonObject by lazy { lines.first { it.str("kind") == "meta" } }
    val conversions: List<Conversion> by lazy { lines.filter { it.str("kind") == "resample" }.map(::conversion) }

    /** The largest difference of [got] from [want], or infinity where their lengths differ. */
    fun worst(got: FloatArray, want: FloatArray): Double {
        if (got.size != want.size) return Double.POSITIVE_INFINITY
        var worst = 0.0
        for (i in want.indices) worst = maxOf(worst, abs(got[i].toDouble() - want[i].toDouble()))
        return worst
    }

    fun JsonObject.str(key: String): String = this[key]!!.jsonPrimitive.content

    private fun conversion(record: JsonObject): Conversion {
        val from = record["from"]!!.jsonPrimitive.double
        val to = record["to"]!!.jsonPrimitive.double
        val y = floats(record["y"]!!.jsonObject)
        assertEquals(record["length"]!!.jsonPrimitive.int, y.size)
        record["noise"]?.jsonObject?.let { noise ->
            return Conversion("noise", "noise of seed ${noise["seed"]} at $from to $to", floats(noise["x"]!!.jsonObject),
                              from, to, y)
        }
        val clip = record["clip"]!!.jsonObject
        val name = clip["wav"]!!.jsonObject.str("fixture")
        val offset = clip["offset"]!!.jsonPrimitive.int
        val count = clip["count"]!!.jsonPrimitive.int
        val x = wav(Corpus.fixture(name)).copyOfRange(offset, offset + count)
        val family = if (count > 100_000) "long clip" else "clip excerpt"
        return Conversion(family, "$name[$offset, +$count] at $from to $to", x, from, to, y)
    }

    /** A corpus array of float32: base64 of its little-endian values. */
    fun floats(array: JsonObject): FloatArray {
        assertEquals("float32", array.str("dtype"))
        val bytes = ByteBuffer.wrap(Base64.getDecoder().decode(array.str("base64"))).order(ByteOrder.LITTLE_ENDIAN)
        return FloatArray(bytes.remaining() / 4) { bytes.float }
    }

    /** A 16-bit mono PCM WAV's samples as soundfile reads them as float32: each one over 32,768. */
    fun wav(data: ByteArray): FloatArray {
        val b = ByteBuffer.wrap(data).order(ByteOrder.LITTLE_ENDIAN)
        assertEquals("RIFF", String(data, 0, 4, Charsets.US_ASCII))
        assertEquals("WAVE", String(data, 8, 4, Charsets.US_ASCII))
        var at = 12
        while (at + 8 <= data.size) {
            val id = String(data, at, 4, Charsets.US_ASCII)
            val size = b.getInt(at + 4)
            val body = at + 8
            when (id) {
                "fmt " -> {
                    assertEquals(1, b.getShort(body).toInt(), "PCM")
                    assertEquals(1, b.getShort(body + 2).toInt(), "mono")
                    assertEquals(16, b.getShort(body + 14).toInt(), "16-bit")
                }
                "data" -> return FloatArray(size / 2) { b.getShort(body + 2 * it) / 32768f }
            }
            at = body + size + (size and 1)
        }
        error("a WAV with no data chunk")
    }
}
