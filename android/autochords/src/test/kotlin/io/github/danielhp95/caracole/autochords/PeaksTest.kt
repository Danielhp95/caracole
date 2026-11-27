package io.github.danielhp95.caracole.autochords

import io.github.danielhp95.caracole.autochords.testing.PeaksRecords
import io.github.danielhp95.caracole.core.testing.Misses
import kotlin.test.Test
import kotlin.test.assertEquals

/** [Peaks] against beat_this's minimal postprocessor (vectors/autochords/peaks.jsonl). */
class PeaksTest {
    @Test
    fun `every record is beat_this's answer`() {
        assertEquals(26, PeaksRecords.records.count { it["kind"].toString() == "\"peaks\"" })
        val misses = Misses("autochords/peaks.jsonl")
        PeaksRecords.replay(misses)
        misses.assertNone()
    }

    @Test
    fun `a twin peak is its mean, and a downbeat goes to the nearest beat`() {
        val beat = FloatArray(30) { -2f }.also { it[10] = 1.5f; it[11] = 1.5f; it[20] = 1f }
        val downbeat = FloatArray(30) { -2f }.also { it[15] = 1f }
        assertEquals(listOf(0.21, 0.4) to listOf(0.21), Peaks.of(beat, downbeat))
        assertEquals(emptyList<Double>() to emptyList(), Peaks.of(FloatArray(4), FloatArray(4)))
    }
}
