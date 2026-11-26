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
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith
import kotlin.test.assertTrue

/** [Soxr] against python-soxr's answers (vectors/autochords/soxr.jsonl, tests/test_conformance_autochords_models.py):
 * the design's B1 resample gate, every sample within [TOLERANCE], each length equal. */
class SoxrTest {
    private val lines = Corpus.lines("autochords/soxr.jsonl").drop(1)
    private val meta = lines.first { it.str("kind") == "meta" }
    private val records = lines.filter { it.str("kind") == "resample" }

    @Test
    fun `the records are python-soxr's HQ by libsoxr 0_1_3 within the design's tolerance`() {
        assertEquals("HQ", meta.str("quality"))
        assertEquals("libsoxr-0.1.3", meta["libraries"]!!.jsonObject.str("libsoxr"))
        assertEquals(TOLERANCE, meta["tolerance"]!!.jsonPrimitive.double)
        assertTrue(records.size >= 30, "only ${records.size} records")
    }

    @Test
    fun `every record is python-soxr's to within 1e-6, of the same length`() {
        for (record in records) {
            val x = input(record)
            val from = record["from"]!!.jsonPrimitive.double
            val to = record["to"]!!.jsonPrimitive.double
            val want = floats(record["y"]!!.jsonObject)
            assertEquals(record["length"]!!.jsonPrimitive.int, want.size)
            val got = Soxr.resample(x, from, to)
            val what = "${describe(record)} at $from to $to"
            assertEquals(want.size, got.size, "$what: the length")
            var worst = 0.0
            for (i in want.indices) worst = maxOf(worst, abs(got[i].toDouble() - want[i].toDouble()))
            assertTrue(worst <= TOLERANCE, "$what: a sample differs by $worst")
        }
    }

    @Test
    fun `a rate that isn't over 0 is refused, as python-soxr refuses it`() {
        for ((from, to) in listOf(0.0 to 22050.0, 44100.0 to -1.0, Double.NaN to 22050.0)) {
            assertFailsWith<IllegalArgumentException> { Soxr.resample(FloatArray(10), from, to) }
        }
    }

    private fun input(record: JsonObject): FloatArray {
        record["noise"]?.jsonObject?.let { return floats(it["x"]!!.jsonObject) }
        val clip = record["clip"]!!.jsonObject
        val samples = wav(Corpus.fixture(clip["wav"]!!.jsonObject.str("fixture")))
        val offset = clip["offset"]!!.jsonPrimitive.int
        return samples.copyOfRange(offset, offset + clip["count"]!!.jsonPrimitive.int)
    }

    private fun describe(record: JsonObject): String =
        record["noise"]?.let { "noise of seed ${it.jsonObject["seed"]}" } ?: "clip ${record["clip"]}".take(120)

    private companion object {
        const val TOLERANCE = 1e-6

        fun JsonObject.str(key: String): String = this[key]!!.jsonPrimitive.content

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
}
