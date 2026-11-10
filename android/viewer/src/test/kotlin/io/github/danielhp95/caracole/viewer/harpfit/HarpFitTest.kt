package io.github.danielhp95.caracole.viewer.harpfit

import io.github.danielhp95.caracole.viewer.harp.Harp
import io.github.danielhp95.caracole.viewer.harptab.HarpTabs
import io.github.danielhp95.caracole.viewer.harptab.Tab
import io.github.danielhp95.caracole.viewer.testing.replays.HarmonicaPageReplay
import kotlinx.serialization.json.JsonPrimitive
import org.junit.Test
import kotlin.test.assertEquals
import kotlin.test.assertNull
import kotlin.test.assertTrue

/** viewer.harpfit chooses a harmonica tab's harp as viewer/harpfit.py does: every record of vectors/viewer/harpfit.jsonl
 * (HarmonicaPageReplay), and test_viewer_harpfit.py's own cases, by hand. */
class HarpFitTest {
    @Test fun everyHarpfitRecordIsHarpfitPys() = HarmonicaPageReplay.harpfit()

    private val lines = listOf("made up words for row one", "made up words for row two", "made up words for row three",
                               "made up words for row four", "made up words for row five")

    /** test_viewer_harpfit.sung: a row of [holes], one over each word of [lyric], then the lyric. */
    private fun sung(lyric: String, holes: List<String>): String {
        val starts = lyric.indices.filter { lyric[it] != ' ' && (it == 0 || lyric[it - 1] == ' ') }
        val line = CharArray(lyric.length + 4) { ' ' }
        for ((at, hole) in starts.zip(holes)) hole.forEachIndexed { k, c -> line[at + k] = c }
        return String(line).trimEnd() + "\n" + lyric + "\n"
    }

    /** A tab of [rows] sung rows, each blowing C E G C E G on a C harp (holes 4 5 6 7 8 9). */
    private fun aTab(rows: Int = 4, before: String = ""): String =
        before + (0 until rows).joinToString("\n") { sung(lines[it], listOf("4", "5", "6", "7", "8", "9")) }

    /** A ChordPro sheet, as caracole writes one, playing [chord] under each line. */
    private fun aSheet(chord: String = "D", key: String = "D", capo: Int = 0, lines: List<String> = this.lines): String =
        "{title: Synthetic}\n{artist: Placeholder Band}\n{key: $key}\n" + (if (capo != 0) "{capo: $capo}\n" else "") +
            lines.joinToString("") { "[$chord]$it\n" }

    private fun parse(text: String): Tab = HarpTabs.parse(text)

    @Test fun theHarpThatPutsTheTabsNotesOnTheRecordsChords() {
        val fits = HarpFit.recordFit(parse(aTab()), aSheet("D"))
        assertEquals(Fit(2, 1.0, 24), fits[0])
        assertTrue(fits.size == 12 && fits[1].share < 1.0)
        val chosen = HarpFit.choose(parse(aTab()), cho = aSheet("D"), pageKey = "C")
        assertEquals(Triple(2, "record", 0), Triple(chosen.harp, chosen.why, chosen.page))
    }

    @Test fun theChordAsItSoundsWithTheCapo() =
        assertEquals(Fit(2, 1.0, 24), HarpFit.recordFit(parse(aTab()), aSheet("C", key = "C", capo = 2))[0])

    @Test fun aLineMatchedWordByWordThoughItReadsALittleDifferently() {
        val sheet = aSheet("D", lines = lines.map { it.replace("made up", "made-up") })
        assertEquals(2, HarpFit.recordFit(parse(aTab()), sheet)[0].harp)
    }

    @Test fun tooFewNotesCountedAndTheTabsWordsNameTheHarp() {
        val small = parse(aTab(3, before = "We play it, so I use an A harp\n\n"))
        assertTrue(3 * 6 < HarpFit.MIN_NOTES)
        val chosen = HarpFit.choose(small, cho = aSheet("D"), pageKey = "C")
        assertEquals(Triple(9, "tab", 9), Triple(chosen.harp, chosen.why, chosen.named))
        assertEquals(Fit(2, 1.0, 18), chosen.fits[0])  // counted, too few to say
    }

    @Test fun thenHarptabsComsKeyThenTheSongsKeyThenACHarp() {
        val elsewhere = aSheet("G", key = "G", lines = listOf("other words than the tab", "and more of them here"))
        assertEquals("page", HarpFit.choose(parse(aTab()), cho = elsewhere, pageKey = "Bb").why)
        assertEquals(10, HarpFit.choose(parse(aTab()), cho = elsewhere, pageKey = "Bb").harp)
        val byKey = HarpFit.choose(parse(aTab()), cho = elsewhere)
        assertEquals(Triple(7, "song", 7), Triple(byKey.harp, byKey.why, byKey.tonic))  // G major: a G harp, 1st position
        val alone = HarpFit.choose(parse(aTab()))
        assertEquals(listOf(0, "usual", null, emptyList<Fit>()), listOf(alone.harp, alone.why, alone.tonic, alone.fits))
    }

    @Test fun theKeyTheSongSoundsInNamesThePosition() {
        val chosen = HarpFit.choose(parse(aTab()), cho = aSheet("D", key = "Bm"))
        assertEquals(11, chosen.tonic)
        assertEquals("4th position, aeolian", Harp.positionText(chosen.tonic!!, chosen.harp))
        val withCapo = HarpFit.choose(parse(aTab()), cho = aSheet("C", key = "Am", capo = 2))  // Am shapes, capo 2: B minor
        assertEquals(11, withCapo.tonic)
    }

    @Test fun aSheetsKeyNamedByItsLetterAloneOverMinorChordsIsMinorForTheHarpToo() {
        // UG's Hotel California: {key: A}, capo 2, Am E7 G D F C Dm E. The song sounds B minor: an A harp in the 3rd
        // position, a D harp in the 4th, never a B harp in the 1st.
        val words = listOf("other words than the tab", "and more of them here", "a third line of them", "and a fourth")
        val pairs = listOf("Am" to "E7", "G" to "D", "F" to "C", "Dm" to "E")
        val cho = "{title: Hotel}\n{artist: Placeholder Band}\n{key: A}\n{capo: 2}\n" +
            pairs.zip(words).joinToString("") { (chords, line) -> "[${chords.first}]$line [${chords.second}]and on\n" }
        for ((key, source) in listOf(null to null, "A minor" to "tab")) {
            val chosen = HarpFit.choose(parse(aTab()), cho = cho, key = key, keySource = source)
            assertEquals(Triple(9, "song", 11), Triple(chosen.harp, chosen.why, chosen.tonic), key)
            assertEquals("3rd position, dorian", Harp.positionText(chosen.tonic!!, chosen.harp))
        }
    }

    @Test fun theSongsOwnKeyWinsOverTheSheets() =
        assertEquals(11, HarpFit.choose(parse(aTab()), cho = aSheet("D", key = "D"), key = "Bm", keySource = "chords").tonic)

    @Test fun aTabShownAsWrittenHasNoFit() {
        val chosen = HarpFit.choose(parse("(3)tue (3)te (3)te\n"), cho = aSheet("D"), pageKey = "E")
        assertEquals("page" to emptyList<Fit>(), chosen.why to chosen.fits)
    }

    @Test fun wordsAsTheFitComparesThem() {
        assertEquals(listOf("on", "a", "dark", "desert", "highway"), HarpFit.words("On a dark des-ert high-way, (background)"))
        assertEquals(listOf("i'm", "sure", "you've"), HarpFit.words("I'm sure you’ve"))
    }

    @Test fun aKeysNameAsAPitchClass() {
        assertEquals(listOf(0, 10, 10, 6, 3, 7), listOf("C", "Bb", "A#", "F#", "E♭", " G ").map { HarpFit.pitch(it) })
        assertNull(HarpFit.pitch(null))
        assertNull(HarpFit.pitch("H"))
        assertNull(HarpFit.pitch(""))
    }

    @Test fun theTabsHarpIsTheRecordsOrTheTabsWordsAlone() {
        assertEquals(listOf(2, 9, null, null, null), listOf("record", "tab", "page", "song", "usual").map { why ->
            Choice(if (why == "tab") 9 else 2, why).tabsHarp
        })
    }

    @Test fun aSheetsSungLinesEachWordUnderTheChordSoundingWithTheCapo() {
        val lines = HarpFit.sheetLines("{title: X}\n{capo: 2}\n{comment: Verse}\nno chord yet [C]then a [N.C.]none\n\n" +
                                           "{comment: Chorus}\nfresh [G/B]section\n[x2]\n")
        assertEquals(listOf(listOf("no" to null, "chord" to null, "yet" to null, "then" to setOf(2, 6, 9),
                                   "a" to setOf(2, 6, 9), "none" to null),
                            listOf("fresh" to null, "section" to setOf(1, 4, 9))), lines)
    }

    @Test fun eachTabsHarpForItsSheetsViewersAndNoneForATabItCantRead() {
        val tabs = listOf(HarmonicaTab("harmonica-1.txt", aTab()), HarmonicaTab("harmonica-2.txt", null),
                          HarmonicaTab("harmonica-3.txt", aTab(3, before = "I use an A harp\n\n")),
                          HarmonicaTab("harmonica-4.txt", aTab(), pin = JsonPrimitive("nope")),
                          HarmonicaTab("harmonica-5.txt", aTab(), pageKey = "Bb"))
        assertEquals(mapOf("harmonica-1.txt" to 2, "harmonica-3.txt" to 9, "harmonica-5.txt" to 2),
                     HarpFit.tabHarps(tabs, aSheet("D")))
    }
}
