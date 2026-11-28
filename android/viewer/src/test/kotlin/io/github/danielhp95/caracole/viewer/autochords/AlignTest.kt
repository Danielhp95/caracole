package io.github.danielhp95.caracole.viewer.autochords

import io.github.danielhp95.caracole.core.py.Py
import io.github.danielhp95.caracole.viewer.testing.replays.AutochordsReplay
import org.junit.Test
import kotlin.test.assertEquals
import kotlin.test.assertNull

/** viewer.autochords finds and makes a shift as align.py does: every record of vectors/autochords-sheet/align.jsonl
 * (AutochordsReplay), and test_autochords_align.py's own cases, by hand. */
class AlignTest {
    @Test fun everyRecordIsAlignPys() = AutochordsReplay.align()

    @Test fun shiftedLrcMovesEveryLineAndDropsThoseBeforeTheStart() {
        val text = "[ti:Longships]\n[00:01.00]First\n[00:04.50]Second\n[00:06.00]\n[00:10][01:02.25]Third\n"
        assertEquals(listOf("[ti:Longships]", "[00:13.000]First"), Align.shiftedLrc(text, 12.0).lines().take(2))
        assertEquals(listOf(2.5 to "Second", 4.0 to "", 8.0 to "Third", 60.25 to "Third"),
                     Lrc.parse(Align.shiftedLrc(text, -2.0)))
    }

    @Test fun tooFewLinesKeepNoOffset() {
        val found = Align.lyricsOffset(listOf(1.0 to "a", 2.0 to "b"), emptyList(), emptyList(), emptyList(), 10.0, 9.0)
        assertNull(found.offset)
        assertEquals("2 sung lines, too few to place", found.why)
    }

    @Test fun mathFsumIsTheSumCorrectlyRounded() {
        assertEquals(2.0, Py.mathFsum(listOf(1.0, 1e100, 1.0, -1e100)))
        assertEquals(1.0, Py.mathFsum(List(10) { 0.1 }))
    }
}
