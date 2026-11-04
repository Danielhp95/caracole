package io.github.danielhp95.caracole.core.ug

import io.github.danielhp95.caracole.core.config.RankPolicy
import io.github.danielhp95.caracole.core.testing.Misses
import io.github.danielhp95.caracole.core.testing.replays.RankReplay
import org.junit.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertNull
import kotlin.test.assertTrue

/**
 * rank.py and coverage.py as Python answers them (vectors/sites/ug_rank.jsonl and ug_coverage.jsonl, every float
 * compared as Python's repr), and tests/test_rank.py's and test_coverage.py's rules by hand.
 */
class RankCoverageTest {
    private val p = RankPolicy()

    private fun c(tab: Any, rating: Double, votes: Int, version: Int = 1, coverage: Double? = null,
                  label: String? = null, kind: String = "chords") =
        Candidate("ug", tab.toString(), kind, rating, votes, version, label, coverage)

    @Test fun rankingIsRankPys() {
        val misses = Misses("rank: rank.py")
        RankReplay.rank(misses)
        misses.assertNone()
    }

    @Test fun coverageIsCoveragePys() {
        val misses = Misses("rank: coverage.py")
        RankReplay.coverage(misses)
        misses.assertNone()
    }

    @Test fun fewVotesShrinkTowardTheSongsMean() {
        val ranked = Rank.rankByRating(listOf(c(1, 5.0, 1), c(2, 4.8, 270), c(3, 4.4, 200)), p)
        assertEquals(listOf("2", "1", "3"), ranked.map { it.tabId })
        assertEquals(0.0, Rank.bayes(5.0, 0, 4.2, 0))
        assertEquals(4.2, Rank.bayes(5.0, 0, 4.2, 10), 1e-12)
    }

    @Test fun aCompleteSheetBeatsAHigherRatedPartialOneAndUnknownIsIncomplete() {
        assertEquals(listOf("2", "1"), Rank.rankSheets(listOf(c(1, 4.9, 300, coverage = 0.5),
                                                               c(2, 4.2, 20, coverage = 0.95)), p).map { it.tabId })
        assertEquals(listOf("2", "1"), Rank.rankSheets(listOf(c(1, 4.9, 500), c(2, 3.0, 2, coverage = 0.81)), p)
            .map { it.tabId })
    }

    @Test fun aPartialLabelIsPenalizedAndTheSongsVariantWins() {
        val tabs = listOf(c(1, 4.9, 100, label = "solo", kind = "tabs"), c(2, 4.6, 100, kind = "tabs"),
                          c(3, 4.5, 100, label = "acoustic", kind = "tabs"))
        assertEquals(listOf("2", "3", "1"), Rank.rankGuitar(tabs, p).map { it.tabId })
        assertEquals(listOf("3", "2", "1"), Rank.rankGuitar(tabs, p, "acoustic").map { it.tabId })
        val unplugged = listOf(c(4, 4.5, 100, label = "unplugged", kind = "tabs"), c(5, 4.6, 100, kind = "tabs"))
        assertEquals("4", Rank.rankGuitar(unplugged, p, "acoustic")[0].tabId)
    }

    @Test fun tiesBreakOnVersionThenTheTabIdsLengthThenTheTabId() {
        val ranked = Rank.rankGuitar(listOf(c(9, 0.0, 0, version = 2), c(10, 0.0, 0), c(8, 0.0, 0), c("08", 0.0, 0)), p)
        assertEquals(listOf("8", "08", "10", "9"), ranked.map { it.tabId })
    }

    @Test fun theScoresAreSetOnTheCandidates() {
        val cands = listOf(c(1, 4.0, 10), c(2, 5.0, 30))
        Rank.rankByRating(cands, p)
        assertTrue(cands.all { it.score > 0 })
    }

    @Test fun aSheetReplacesAKeptOneByCoverageAlone() {
        assertTrue(Rank.replacesSheet(0.9, 0.5, 0.8))
        assertFalse(Rank.replacesSheet(1.0, 0.8, 0.8))
        assertTrue(Rank.replacesSheet(0.6, 0.5, 0.8))
        assertFalse(Rank.replacesSheet(0.5, 0.5, 0.8))
        assertFalse(Rank.replacesSheet(null, 0.1, 0.8))
        assertFalse(Rank.replacesSheet(0.7, null, 0.8))
        assertTrue(Rank.replacesSheet(0.8, null, 0.8))
    }

    private val lyrics = """
        Walking down the empty road tonight
        Counting every light along the way

        Walking down the empty road tonight
        I keep on singing till the break of day
        Nothing else will ever feel the same
    """.trimIndent()

    @Test fun lyricLinesAreDistinctAndNormalized() {
        assertEquals(listOf("walking down the empty road tonight", "counting every light along the way",
                            "i keep on singing till the break of day", "nothing else will ever feel the same"),
                     Coverage.lyricLines(lyrics))
        assertEquals("donde estas corazon", Coverage.normalizeLine("¿Dónde estás, corazón?"))
        assertEquals("斑马 斑马 你不要睡着啦", Coverage.normalizeLine("斑马，斑马，你不要睡着啦"))
    }

    @Test fun aSheetCoversTheLinesItHolds() {
        val full = "[Verse 1]\n[tab][ch]G[/ch]   [ch]D[/ch]\nWalking down the empty road tonight[/tab]\n" +
            "[ch]Em[/ch]\nCounting every light along the way\n[Chorus]\nI keep on singing till the break of day\n" +
            "Nothing else will ever feel the same\n"
        assertEquals(1.0, Coverage.coverage(full, Coverage.lyricLines(lyrics)))
        assertEquals(0.5, Coverage.coverage(full.substringBefore("[Chorus]"), Coverage.lyricLines(lyrics)))
        assertEquals(1.0, Coverage.coverage(full, lyrics, p))
        assertNull(Coverage.coverage(full, emptyList()))
    }

    @Test fun aSheetWithOneStrayWordCoversNothing() {
        val sheet = "[Intro]\n[ch]G[/ch] [ch]D[/ch] [ch]Em[/ch] [ch]C[/ch]\nI\n[ch]G[/ch] [ch]D[/ch]\n"
        assertEquals(0.0, Coverage.coverage(sheet, Coverage.lyricLines(lyrics)))
        // a sheet shorter than a line is compared whole: the one line it nearly holds counts
        assertEquals(0.25, Coverage.coverage("[ch]G[/ch]\nWalking down the empty road\n", Coverage.lyricLines(lyrics)))
    }

    @Test fun plainChordNamesAndCaseFoldedMarkupAreDropped() {
        assertEquals("walking down the empty road tonight",
                     Coverage.sheetLyricText("G  D/F#  Em  C\nWalking down the empty road tonight\nAm7 Cadd9 Dsus4\n"))
        assertEquals("hello there", Coverage.sheetLyricText("[CH]Am[/CH] hello [Ch]G[/cH] there"))
        assertTrue(Coverage.isPlainChordLine("ſol mı Rem7"))  // ſ is s and ı is i to Python's IGNORECASE
    }

    @Test fun aSimplifiedSheetCoversTraditionalLyrics() {
        val lines = Coverage.lyricLines("斑馬斑馬你不要睡著啦\n再給我看看你受傷的尾巴")
        val sheet = "[ch]C[/ch]      [ch]G[/ch]\n斑马斑马 你不要睡着啦\n[ch]Am[/ch]     [ch]F[/ch]\n再给我看看你受伤的尾巴"
        assertEquals(1.0, Coverage.coverage(sheet, lines))
    }
}
