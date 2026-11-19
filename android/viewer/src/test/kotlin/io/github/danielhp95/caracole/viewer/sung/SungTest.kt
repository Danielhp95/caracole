package io.github.danielhp95.caracole.viewer.sung

import org.junit.Test
import kotlin.test.assertEquals
import kotlin.test.assertNull

/** viewer.sung.Sung is viewer/sung.py: tests/test_viewer_sung.py's cases by hand, beside the corpus's records of
 * line_key and sung_lines (PagesReplay). */
class SungTest {
    private val drawn = listOf("Synthetic morning on the river", "", "Paper boats are drifting slowly",
                               "Nobody counts the hours", "Sing it back to me", "Over the hills and home")
    private val five = drawn.filter { it.isNotEmpty() }

    private fun lrc(vararg lines: String, start: Double = 8.0, gap: Double = 4.0): List<Pair<Double, String>> =
        lines.mapIndexed { k, text -> start + gap * k to text }

    @Test fun itsNumbersAreTheOnesPythonsSungFollows() {
        assertEquals(listOf(80.0, 0.5, 4.0, 86400.0),
                     listOf(Sung.LINE_MATCH, Sung.MIN_SHARE, Sung.MIN_LINES.toDouble(), Sung.MAX_SECONDS))
    }

    @Test fun aLinesKeyIsItsWordsAndAChineseLinesItsPinyin() {
        assertEquals("paper boats are drifting", Sung.lineKey("Paper Boats, are drifting!"))
        assertEquals("ban ma ban ma", Sung.lineKey("斑馬，斑馬"))
        assertEquals("ban ma ban ma", Sung.lineKey("斑 马 斑 马"))
        assertEquals("wo men love you", Sung.lineKey("我们 love you"))
        assertEquals(listOf("", "", ""), listOf("", "  ", "(…)").map(Sung::lineKey))
    }

    @Test fun eachTimedLineLightsTheSheetLineItIsSungOn() {
        assertEquals(listOf(8000L to 0, 12000L to 2, 16000L to 3, 20000L to 4, 24000L to 5),
                     Sung.lines(drawn, lrc(*five.toTypedArray())))
    }

    @Test fun aChorusTheSheetWritesOnceIsLitTheFirstTimeAlone() {
        val timed = lrc(drawn[0], drawn[2], drawn[3], drawn[4], drawn[5], drawn[4], drawn[5])
        assertEquals(listOf(0, 2, 3, 4, 5, null, null), Sung.lines(drawn, timed)!!.map { it.second })
    }

    @Test fun tooFewMatchesGiveNoHighlight() {
        assertNull(Sung.lines(drawn, lrc(*five.take(3).toTypedArray(), "Other words", "And more of them")))
        assertEquals(4, Sung.lines(drawn, lrc(*five.take(4).toTypedArray()))!!.size)
        assertNull(Sung.lines(drawn, emptyList()))
        assertNull(Sung.lines(emptyList(), lrc(*five.toTypedArray())))
    }

    @Test fun aTimePastADayIsLeftOut() {
        val timed = listOf(0.0 to five[0], 1.5 to five[1], 2.5 to five[2], 86399.999 to five[3], 86400.0 to five[4],
                           1e300 to five[4], -0.5 to five[4], Double.NaN to five[4])
        assertEquals(listOf(0L to 0, 1500L to 2, 2500L to 3, 86399999L to 4), Sung.lines(drawn, timed))
    }

    @Test fun aTimeIsRoundedToTheMillisecondHalfToEven() {
        val timed = listOf(0.0005 to five[0], 0.0015 to five[1], 0.0025 to five[2], 12.3456 to five[3], 20.0 to five[4])
        assertEquals(listOf(0L, 2L, 2L, 12346L, 20000L), Sung.lines(drawn, timed)!!.map { it.first })
    }
}
