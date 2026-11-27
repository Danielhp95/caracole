package io.github.danielhp95.caracole.autochords.frontend

import io.github.danielhp95.caracole.autochords.testing.SoxrRecords
import io.github.danielhp95.caracole.autochords.testing.SoxrRecords.TOLERANCE
import io.github.danielhp95.caracole.autochords.testing.SoxrRecords.str
import kotlinx.serialization.json.double
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import org.junit.Rule
import org.junit.rules.TemporaryFolder
import java.nio.ByteBuffer
import java.nio.ByteOrder
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith
import kotlin.test.assertTrue

/** [Soxr] against python-soxr's answers (vectors/autochords/soxr.jsonl, tests/test_conformance_autochords_models.py):
 * the design's B1 resample gate, every sample within [TOLERANCE], each length equal. */
class SoxrTest {
    @Test
    fun `the records are python-soxr's HQ by libsoxr 0_1_3 within the design's tolerance`() {
        val meta = SoxrRecords.meta
        assertEquals("HQ", meta.str("quality"))
        assertEquals("libsoxr-0.1.3", meta["libraries"]!!.jsonObject.str("libsoxr"))
        assertEquals(TOLERANCE, meta["tolerance"]!!.jsonPrimitive.double)
        assertTrue(SoxrRecords.conversions.size >= 30, "only ${SoxrRecords.conversions.size} records")
    }

    @Test
    fun `every record is python-soxr's to within 1e-6, of the same length`() {
        for (c in SoxrRecords.conversions) {
            val got = Soxr.resample(c.x, c.from, c.to)
            assertEquals(c.y.size, got.size, "${c.what}: the length")
            val worst = SoxrRecords.worst(got, c.y)
            assertTrue(worst <= TOLERANCE, "${c.what}: a sample differs by $worst")
        }
    }

    @get:Rule val tmp = TemporaryFolder()

    @Test
    fun `a file resampled a block at a time is the one-shot's sample for sample`() {
        var longest = 0
        for (c in SoxrRecords.conversions) {
            val input = tmp.newFile()
            val bytes = ByteBuffer.allocate(4 * c.x.size).order(ByteOrder.LITTLE_ENDIAN)
            c.x.forEach { bytes.putFloat(it) }
            input.writeBytes(bytes.array())
            val output = tmp.newFile()
            val written = Soxr.resample(input, c.from, c.to, output)
            val back = ByteBuffer.wrap(output.readBytes()).order(ByteOrder.LITTLE_ENDIAN).asFloatBuffer()
            val streamed = FloatArray(back.remaining()).also { back.get(it) }
            val whole = Soxr.resample(c.x, c.from, c.to)
            assertEquals(whole.size.toLong(), written, "${c.what}: the length")
            assertTrue(whole.contentEquals(streamed), "${c.what}: a sample differs from the one-shot's")
            longest = maxOf(longest, whole.size)
        }
        // Some output many times a call's room: the stream drained across calls.
        assertTrue(longest > 4 * Soxr.ROOM, "the longest conversion gives $longest samples")
    }

    @Test
    fun `a rate that isn't over 0 is refused, as python-soxr refuses it`() {
        for ((from, to) in listOf(0.0 to 22050.0, 44100.0 to -1.0, Double.NaN to 22050.0, 44100.0 to Double.NaN)) {
            assertFailsWith<IllegalArgumentException> { Soxr.resample(FloatArray(10), from, to) }
        }
    }

    @Test
    fun `an infinite rate is refused`() {
        for ((from, to) in listOf(Double.POSITIVE_INFINITY to 22050.0, 44100.0 to Double.POSITIVE_INFINITY)) {
            assertFailsWith<IllegalArgumentException> { Soxr.resample(FloatArray(10), from, to) }
        }
    }
}
