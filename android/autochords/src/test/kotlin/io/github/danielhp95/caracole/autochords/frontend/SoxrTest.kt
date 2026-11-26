package io.github.danielhp95.caracole.autochords.frontend

import io.github.danielhp95.caracole.autochords.frontend.SoxrRecords.TOLERANCE
import io.github.danielhp95.caracole.autochords.frontend.SoxrRecords.str
import kotlinx.serialization.json.double
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
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
