package io.github.danielhp95.caracole.core.py

import io.github.danielhp95.caracole.core.testing.Misses
import io.github.danielhp95.caracole.core.testing.replays.PyFormatRecords
import org.junit.Test
import kotlin.test.assertEquals
import kotlin.test.assertSame

/** PySequence.SequenceMatcher against vectors/py/format_sequence.jsonl: difflib.SequenceMatcher(None, a, b,
 * autojunk=False). */
class PySequenceTest {
    @Test fun everyPairMatchesAsPythonsDifflibMatchesIt() {
        val misses = Misses("py/format_sequence.jsonl")
        PyFormatRecords.sequences(misses)
        misses.assertNone()
    }

    private fun chars(s: String): List<String> = s.map { it.toString() }

    @Test fun difflibsOwnExamples() {
        val m = PySequence.SequenceMatcher(chars("abxcd"), chars("abcd"))
        assertEquals(listOf(Triple(0, 0, 2), Triple(3, 2, 2), Triple(5, 4, 0)), m.matchingBlocks())
        assertEquals(0.8888888888888888, m.ratio())
        // find_longest_match's tie: the earliest in a, then in b; " abcd" is found whole at b's second abcd.
        val n = PySequence.SequenceMatcher(chars(" abcd"), chars("abcd abcd"))
        assertEquals(listOf(Triple(0, 4, 5), Triple(5, 9, 0)), n.matchingBlocks())
        assertEquals(0.7142857142857143, n.ratio())
    }

    @Test fun nothingAgainstNothingIsAlike() {
        val m = PySequence.SequenceMatcher(emptyList<String>(), emptyList())
        assertEquals(listOf(Triple(0, 0, 0)), m.matchingBlocks())
        assertEquals(1.0, m.ratio())
        assertEquals(0.0, PySequence.SequenceMatcher(listOf("a"), emptyList()).ratio())
    }

    @Test fun aPopularElementPast200IsKeptAsAutojunkFalseKeepsIt() {
        val m = PySequence.SequenceMatcher(chars("a".repeat(10) + "b"), chars("aaac".repeat(60)))
        assertEquals(0.0796812749003984, m.ratio())  // autojunk=True would say 0.02390438247011952
        assertEquals(listOf(Triple(0, 0, 3), Triple(3, 4, 3), Triple(6, 8, 3), Triple(9, 12, 1), Triple(11, 240, 0)),
                     m.matchingBlocks())
    }

    @Test fun harpfitsWordsMatchedLineToLine() {
        val m = PySequence.SequenceMatcher("made up words for row one".split(' '), "made-up words for row one".split(' '))
        assertEquals(listOf(Triple(2, 1, 4), Triple(6, 5, 0)), m.matchingBlocks())
        assertEquals(0.7272727272727273, m.ratio())
    }

    @Test fun theBlocksAreReadOnce() {
        val m = PySequence.SequenceMatcher(chars("abc"), chars("abd"))
        assertSame(m.matchingBlocks(), m.matchingBlocks())
    }
}
