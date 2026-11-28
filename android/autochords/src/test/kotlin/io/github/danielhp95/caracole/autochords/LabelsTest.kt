package io.github.danielhp95.caracole.autochords

import io.github.danielhp95.caracole.autochords.testing.LabelsRecords
import io.github.danielhp95.caracole.core.testing.Misses
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith

/** [Labels] against btc.py (vectors/autochords/labels.jsonl), and test_autochords_models.py's own cases. */
class LabelsTest {
    @Test
    fun `every record is btc_py's answer`() {
        val misses = Misses("autochords/labels.jsonl")
        LabelsRecords.replay(misses)
        misses.assertNone()
    }

    @Test
    fun `the large vocabulary's indices name Harte labels`() {
        val names = Labels.vocabulary(170)
        assertEquals(listOf("C:min", "C", "C:7", "C#:min", "C#", "B:sus4", "X", "N"),
                     listOf(0, 1, 9, 14, 15, 167, 168, 169).map { names[it] })
        assertEquals(listOf("C", "C:min"), Labels.vocabulary(25).take(2))
        assertEquals("N", Labels.vocabulary(25)[24])
        assertFailsWith<IllegalArgumentException> { Labels.vocabulary(24) }
    }

    @Test
    fun `Harte labels become common names`() {
        val cases = mapOf("C" to "C", "C:maj" to "C", "A:min7" to "Am7", "B:hdim7" to "Bm7b5", "E:minmaj7" to "EmMaj7",
                          "X" to "N", "N" to "N", "C:min/b3" to "Cm", "C:weird" to "Cweird")
        assertEquals(cases, cases.keys.associateWith { Labels.commonName(it) })
    }

    @Test
    fun `black-key roots are spelled for the song's key`() {
        fun song(vararg labels: String) = labels.mapIndexed { k, l -> ChordSegment(2.0 * k, 2.0 * (k + 1), l) }
        assertEquals(listOf("F", "Bb", "C", "D:min"), Labels.spellForKey(song("F", "A#", "C", "D:min")).map { it.label })
        assertEquals(listOf("E", "B", "C#:min", "A"), Labels.spellForKey(song("E", "B", "C#:min", "A")).map { it.label })
        assertEquals(listOf("C", "Bb", "F", "C"), Labels.spellForKey(song("C", "A#", "F", "C")).map { it.label })
    }

    @Test
    fun `frames become segments, their times rounded as Python's round(x, 3)`() {
        assertEquals(listOf(ChordSegment(0.0, 1.0, "C"), ChordSegment(1.0, 2.5, "A:min"), ChordSegment(2.5, 3.0, "N")),
                     Labels.framesToSegments(intArrayOf(0, 0, 19, 19, 19, 24), 0.5, Labels.vocabulary(25)))
        assertEquals(emptyList(), Labels.framesToSegments(IntArray(0), Labels.FRAME_SECONDS, Labels.vocabulary(170)))
        // 0.0925925… s a frame: frame 27 is 2.5 s exactly; 2.6851851… rounds to 2.685.
        assertEquals(2.5, Labels.time(27, Labels.FRAME_SECONDS))
        assertEquals(2.685, Labels.time(29, Labels.FRAME_SECONDS))
        // 1.0005 is 1.000499999… in binary, 2.0005 2.000500000…: Python rounds the exact value, 1.0 and 2.001.
        assertEquals(1.0, Labels.time(1, 1.0005))
        assertEquals(2.001, Labels.time(1, 2.0005))
    }
}
