package io.github.danielhp95.caracole.viewer.pages

import io.github.danielhp95.caracole.core.testing.Corpus
import io.github.danielhp95.caracole.core.testing.Misses
import io.github.danielhp95.caracole.viewer.harpfit.Choice
import io.github.danielhp95.caracole.viewer.harpfit.Fit
import io.github.danielhp95.caracole.viewer.testing.replays.HarmonicaPageReplay
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import org.junit.Test
import kotlin.test.assertEquals
import kotlin.test.assertTrue

/** viewer.pages.HarmonicaPage writes a harmonica tab's page as viewer/harptab_page.py does: every record of
 * vectors/viewer/harmonica_pages.jsonl and the page kept whole (HarmonicaPageReplay), and test_viewer_harptab_page.py's
 * own cases of its parts, by hand. */
class HarmonicaPageTest {
    @Test fun theDataIsTheModules() = Misses("harmonica_page.json").let { HarmonicaPageReplay.data(it); it.assertNone() }

    @Test fun everyPageRecordIsHarptabPagePys() = HarmonicaPageReplay.pages()

    @Test fun aSmallPageIsPythonsByteForByte() = HarmonicaPageReplay.whole()

    @Test fun aHarpsArticle() =
        assertEquals(listOf("a C harp", "an A harp", "an F harp", "an Eb harp", "a Db harp"),
                     listOf("C", "A", "F", "Eb", "Db").map(HarmonicaPage::a))

    @Test fun theHarpWithTheRecordAndHowWellItFits() {
        val choice = Choice(2, "record", listOf(Fit(2, 1.0, 24), Fit(5, 1.0 / 3, 24)), null, 0, 11)
        assertEquals("<p class=\"facts\" id=\"facts\">Harmonica tab · <b>D harp</b> with the record (4th position, aeolian)</p>\n" +
                         "<p class=\"why\">100% of the sung notes fit the sheet's chords on a D harp, 33% on an F harp</p>\n",
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
        assertTrue("<a class=\"pdf\" href=\"harmonica%201%20%28x%29.txt\">Tab as text</a>" in foot)
        assertTrue("<a href=\"https://www.harptabs.com/\">harptabs.com</a>, as its tabber wrote it. We placed" in foot)
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
        assertTrue(keyless.getValue("harp").jsonObject.getValue("none").toString().contains("The chord sheet has no key"))
    }

    private val hotel = String(Corpus.fixture("harptabs/tabs/588_hotel-california.txt"), Charsets.UTF_8)

    private fun page(text: String = hotel, facts: JsonObject? = null, cho: String? = null, pageKey: String? = null,
                     back: String? = null): String =
        HarmonicaPage.build(text, title = "Synthetic Song", artist = "Placeholder Band", tabFile = "harmonica-1.txt",
                            pageKey = pageKey, facts = facts, cho = cho, back = back)

    private fun data(html: String): JsonObject {
        val at = html.indexOf("<script type=\"application/json\" id=\"harp-data\">")
        val from = html.indexOf('>', at) + 1
        return Json.parseToJsonElement(html.substring(from, html.indexOf("</script>", from))).jsonObject
    }

    @Test fun aTabInHarptabsComsOwnNotationHasItsLegendAndWhatHarptabsComSaysOfIt() {
        val facts = Json.parseToJsonElement("""{"difficulty": "Beginner", "views": 224000, "rating": 3.3}""").jsonObject
        val html = page(facts = facts, pageKey = "Bb", back = "sheet (auto).html")
        assertTrue("<p class=\"facts\" id=\"facts\">Harmonica tab · <b>Bb harp</b>, as harptabs' key says</p>" in html)
        assertTrue("(<span class=\"b\">4</span> <span class=\"b\">5</span>)</span> together · Beginner · 224k views · 3.3★</p>" in html)
        assertTrue("<a class=\"back\" href=\"sheet%20%28auto%29.html\" data-sheet>‹ Chord sheet</a>" in html)
        assertTrue("<p class=\"reading\" id=\"reading-foot\" hidden>" in html)
        assertEquals(JsonPrimitive(10), data(html)["start"])
        assertEquals("""{"10":"harptabs' key"}""", data(html)["why"].toString())
    }

    @Test fun aTabCaracoleCantReadIsItsTextAsWrittenWithTheBarOfOne() {
        val html = page("ARMONICA C\n↑3 ↓3 ↑4 ↓4 ↑5\n↓5 ↑6 ↓6 ↑6\n", pageKey = "C")
        assertTrue("<pre class=\"tab\">ARMONICA C\n↑3 ↓3 ↑4 ↓4 ↑5\n↓5 ↑6 ↓6 ↑6</pre>" in html)
        assertTrue("We can't read its notation." in html && HarmonicaPage.BAR_RAW in html && "\"groups\"" !in html)
        assertTrue("<a class=\"back\" href=\"../../index.html\">‹ Library</a>" in html)
    }
}
