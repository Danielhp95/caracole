package io.github.danielhp95.caracole.autochords

import io.github.danielhp95.caracole.autochords.testing.ScoresRecords
import io.github.danielhp95.caracole.core.testing.Misses
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith

/** [Scores] against mir_eval (vectors/autochords/scores.jsonl). */
class ScoresTest {
    @Test
    fun `every record is mir_eval's within 1e-12, and in fact bit for bit`() {
        val misses = Misses("autochords/scores.jsonl")
        ScoresRecords.replay(misses)
        misses.assertNone()
        // Each score's sums are numpy's pairwise ones, in its order: none differs in its last bit.
        assertEquals(ScoresRecords.scored, ScoresRecords.exact)
    }

    @Test
    fun `majmin compares a seventh as its triad, tetrads as itself, and neither scores X`() {
        val ref = listOf(ChordSegment(0.0, 1.0, "C:7"), ChordSegment(1.0, 2.0, "X"), ChordSegment(2.0, 4.0, "A#:min"))
        val est = listOf(ChordSegment(0.0, 1.0, "C"), ChordSegment(1.0, 2.0, "C"), ChordSegment(2.0, 4.0, "Bb:min"))
        assertEquals(1.0, Scores.wcsr(ref, est, "majmin"))
        assertEquals(2.0 / 3, Scores.wcsr(ref, est, "tetrads"), 1e-15)
        assertFailsWith<IllegalArgumentException> { Scores.wcsr(ref, est, "thirds") }
        assertFailsWith<IllegalArgumentException> { Scores.wcsr(ref, listOf(ChordSegment(0.0, 4.0, "Am")), "majmin") }
    }

    @Test
    fun `beat F counts a hit within the window, and trimBeats leaves out the first 5 s`() {
        assertEquals(1.0, Scores.beatF(listOf(6.0, 7.0), listOf(6.05, 6.95)))
        assertEquals(0.0, Scores.beatF(emptyList(), listOf(6.0)))
        assertEquals(listOf(5.0, 6.0), Scores.trimBeats(listOf(1.0, 4.99, 5.0, 6.0)))
        assertFailsWith<IllegalArgumentException> { Scores.beatF(listOf(7.0, 6.0), listOf(6.0)) }
    }
}
