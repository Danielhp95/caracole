package io.github.danielhp95.caracole.viewer.pages

import io.github.danielhp95.caracole.core.testing.Misses
import io.github.danielhp95.caracole.viewer.harpfit.Choice
import io.github.danielhp95.caracole.viewer.harpfit.Fit
import io.github.danielhp95.caracole.viewer.testing.replays.HarmonicaPageReplay
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import org.junit.Assume
import org.junit.Test
import kotlin.test.assertEquals
import kotlin.test.assertTrue

/** viewer.pages.HarmonicaPage writes a harmonica tab's page as viewer/harptab_page.py does: every record of
 * vectors/viewer/harmonica_pages.jsonl and the page kept whole (HarmonicaPageReplay), and test_viewer_harptab_page.py's
 * own cases of its parts, by hand. */
class HarmonicaPageTest {
    @Test fun theDataIsTheModules() = Misses("harmonica_page.json").let { HarmonicaPageReplay.data(it); it.assertNone() }

    @Test fun everyPageRecordIsHarptabPagePys() = waiting { HarmonicaPageReplay.pages() }

    @Test fun aSmallPageIsPythonsByteForByte() = waiting { HarmonicaPageReplay.whole() }

    /** Phase A: [block], then the test skipped where a record waited on lane harptab-layout (HarpTabs.parse) or lane
     * pages (SheetPage's frame). */
    private fun waiting(block: () -> Unit) {
        val before = HarmonicaPageReplay.waiting
        block()
        Assume.assumeTrue("waiting on lanes harptab-layout and pages: ${HarmonicaPageReplay.waiting - before} records",
                          HarmonicaPageReplay.waiting == before)
    }

    @Test fun aHarpsArticle() =
        assertEquals(listOf("a C harp", "an A harp", "an F harp", "an Eb harp", "a Db harp"),
                     listOf("C", "A", "F", "Eb", "Db").map(HarmonicaPage::a))

    @Test fun theHarpWithTheRecordAndHowWellItFits() {
        val choice = Choice(2, "record", listOf(Fit(2, 1.0, 24), Fit(5, 1.0 / 3, 24)), null, 0, 11)
        assertEquals("<p class=\"facts\" id=\"facts\">Harmonica tab · <b>D harp</b> with the record (4th position, aeolian)</p>\n" +
                         "<p class=\"why\">100% of the sung notes fall on the sheet's chords on a D harp, 33% on an F harp</p>\n",
                     HarmonicaPage.harpLines(choice))
        assertEquals("<p class=\"facts\" id=\"facts\">Harmonica tab · <b>A harp</b>, as the tab says</p>\n",
                     HarmonicaPage.harpLines(Choice(9, "tab", named = 9, page = 4)))
        assertEquals("<p class=\"facts\" id=\"facts\">Harmonica tab · <b>G harp</b> for the song's key (1st position)</p>\n",
                     HarmonicaPage.harpLines(Choice(7, "song", tonic = 7)))
        assertTrue(HarmonicaPage.harpLines(Choice(2, "record", listOf(Fit(2, 1.0, 24)), 9, null, null))
                       .contains(" · the tab says A harp</p>"))
    }

    @Test fun theFootLinksTheTabsTextAndWhereItCameFrom() {
        val foot = HarmonicaPage.footer("harmonica 1 (x).txt", "javascript:alert(1)", placed = true, change = true)
        assertTrue("<a class=\"pdf\" href=\"harmonica%201%20%28x%29.txt\">The tab as text</a>" in foot)
        assertTrue("<a href=\"https://www.harptabs.com/\">harptabs.com</a>, as its tabber wrote it; caracole placed" in foot)
        assertTrue("id=\"reading-foot\" hidden" in foot)
        val kept = HarmonicaPage.footer("harmonica-1.txt", "https://www.harptabs.com/tab/588/x", placed = false)
        assertTrue("<a href=\"https://www.harptabs.com/tab/588/x\">harptabs.com</a>, as its tabber wrote it.</p>" in kept)
        assertTrue("reading-foot" !in kept)
    }

    @Test fun theOverlayWithNoSheetOrNoKeySaysSoAndGivesEachHarpsNotes() {
        val none = HarmonicaPage.overlayData(Choice(0, "usual"), null, null, null)
        assertEquals(JsonPrimitive(null as String?), none.getValue("guitar"))
        val harp = none.getValue("harp").jsonObject
        assertEquals(listOf("key", "none", "holes"), harp.keys.toList())
        assertEquals(12, harp.getValue("holes").jsonArray.size)
        val keyless = HarmonicaPage.overlayData(Choice(0, "usual"), "{title: X}\nwords alone\n", null, null)
        assertTrue(keyless.getValue("harp").jsonObject.getValue("none").toString().contains("no key in its chord sheet"))
    }
}
