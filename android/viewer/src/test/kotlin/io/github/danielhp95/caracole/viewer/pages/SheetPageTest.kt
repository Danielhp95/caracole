package io.github.danielhp95.caracole.viewer.pages

import io.github.danielhp95.caracole.core.testing.Misses
import io.github.danielhp95.caracole.viewer.pages.internal.PageConstants
import io.github.danielhp95.caracole.viewer.sheet.Blank
import io.github.danielhp95.caracole.viewer.sheet.ChordRow
import io.github.danielhp95.caracole.viewer.sheet.Item
import io.github.danielhp95.caracole.viewer.sheet.Lyrics
import io.github.danielhp95.caracole.viewer.sheet.Section
import io.github.danielhp95.caracole.viewer.sheet.Sheets
import io.github.danielhp95.caracole.viewer.sheet.Text
import io.github.danielhp95.caracole.viewer.testing.replays.PagesReplay
import io.github.danielhp95.caracole.viewer.theory.Key
import org.junit.Test
import kotlin.test.assertEquals
import kotlin.test.assertTrue

/** viewer.pages.SheetPage is viewer/page.py: every record of vectors/viewer/pages_parts.jsonl, pages-*.jsonl and
 * page_whole.json (PagesReplay), and a few cases by hand. */
class SheetPageTest {
    @Test fun everyPartOfThePagesFrameIsPagePys() = each("viewer/pages_parts.jsonl", PagesReplay::everyPartIsPagePys)

    @Test fun everyPageIsPagePys() = each("viewer/pages-*.jsonl", PagesReplay::everyPageIsPagePys)

    @Test fun theSmallPageIsPagePysWhole() = each("viewer/page_whole.json", PagesReplay::theWholePageIsPagePys)

    private fun each(name: String, replay: (Misses) -> Unit) {
        val misses = Misses(name)
        replay(misses)
        misses.assertNone()
    }

    @Test fun theControlsHoldTheFullScreenRowOnceForTheGuitarProRowToFollow() {
        assertEquals(1, SheetPage.CONTROLS.split(PageConstants.FULL_ROW).size - 1)
        assertTrue("<div id=\"harmony-row\"" !in SheetPage.CONTROLS)  // Harmony is the overlay's third tab
        assertEquals("../../index.html", SheetPage.LIBRARY_PAGE)
    }

    @Test fun aServerSendsThePagesOwnPolicyInASandbox() {
        val page = SheetPage.page("A & B", "<p>x</p>\n", listOf("a{}"), listOf("1"))
        val policy = Regex("<meta http-equiv=\"Content-Security-Policy\" content=\"([^\"]*)\">").find(page)!!.groupValues[1]
        assertEquals("sandbox allow-scripts allow-downloads; $policy", SheetPage.viewerCsp(page.toByteArray()))
        assertTrue("<title>A &amp; B</title>" in page)
        assertEquals("sandbox; default-src 'none'; base-uri 'none'; form-action 'none'",
                     SheetPage.viewerCsp("<p>no policy</p>".toByteArray()))
    }

    @Test fun aLineWrapsBetweenWordsAndAroundEachWideCharacter() {
        assertEquals(listOf("我", "们 ", "a ", "b"), SheetPage.words("我们 a b"))
        assertEquals(listOf("  ", "a  ", "b"), SheetPage.words("  a  b"))
        assertEquals(emptyList<String>(), SheetPage.words(""))
    }

    @Test fun aSungLineSetsEachChordOverItsSyllable() {
        val line = Lyrics(listOf(null to "Hey ", Item.Chord(0) to "Jude don't", Item.Mark("x2") to ""))
        val section = Section("Verse <1>", lines = listOf(line, Blank, ChordRow(listOf(Item.Chord(0), Item.Mark("|")))))
        assertEquals(
            "<section class=\"sec\">\n<h2 class=\"lbl\">Verse &lt;1&gt;</h2>\n" +
                "<p class=\"l\"><span class=\"w\">Hey </span><span class=\"s\"><b class=\"c\" data-c=\"0\" tabindex=\"0\" " +
                "role=\"button\">G</b><span class=\"y\">Jude </span></span><span class=\"w\">don&#x27;t</span>" +
                "<span class=\"s\"><i class=\"m\">x2</i><span class=\"y\"></span></span></p>\n" +
                "<div class=\"gap\"></div>\n" +
                "<p class=\"l chords bars\"><span class=\"barcell\"><b class=\"c\" data-c=\"0\" tabindex=\"0\" " +
                "role=\"button\">G</b>" + "<span class=\"beat\" aria-hidden=\"true\">·</span>".repeat(3) + "</span></p>\n" +
                "</section>\n",
            SheetPage.sectionHtml(section, listOf("G")),
        )
    }

    @Test fun aWordWithAChordInsideItWrapsWhole() {
        fun sung(line: String): String {
            val sheet = Sheets.parse("{title: T}\n{artist: A}\n$line\n")
            return sheet.sections.joinToString("") { SheetPage.sectionHtml(it, sheet.chords) }
        }
        fun c(i: Int, name: String) = "<b class=\"c\" data-c=\"$i\" tabindex=\"0\" role=\"button\">$name</b>"
        val sheet = sung("[Am]To cast me off dis[E]courteously, [C]a[G]la[D]bama")
        assertTrue("<span class=\"word\"><span class=\"w\">dis</span><span class=\"s\">${c(1, "E")}" +
                       "<span class=\"y\">courteously, </span></span></span>" in sheet, sheet)
        assertTrue("<span class=\"word\"><span class=\"s\">${c(2, "C")}<span class=\"y\">a</span></span>" +
                       "<span class=\"s\">${c(3, "G")}<span class=\"y\">la</span></span><span class=\"s\">${c(4, "D")}" +
                       "<span class=\"y\">bama</span></span></span>" in sheet, sheet)
        assertEquals(2, sheet.split("class=\"word\"").size - 1)

        val two = sung("[Am]a wo[G][D]rd here")
        assertEquals(1, two.split("class=\"word\"").size - 1)
        val word = two.substring(two.indexOf("<span class=\"word\">"))
        val at = listOf("<span class=\"w\">wo</span>", "data-c=\"1\"", "data-c=\"2\"", "<span class=\"y\">rd").map(word::indexOf)
        assertTrue(at.first() >= 0 && at == at.sorted(), two)

        assertTrue(SheetPage.glued("dis", "courteously") && SheetPage.glued("la", "bama"))
        assertTrue(!SheetPage.glued("courteously, ", "a") && !SheetPage.glued("dis", " a") && !SheetPage.glued("", "a"))
        assertTrue(!SheetPage.glued("我", "们") && !SheetPage.glued("a", "们") && !SheetPage.glued("a\u3000", "b"))
        // 𠀀 (U+20000) is wide, and one code point past U+FFFF, never its two surrogates
        assertTrue(!SheetPage.glued("a", "\uD840\uDC00") && !SheetPage.glued("\uD840\uDC00", "a"))
    }

    @Test fun notesOfMoreThanTwoLinesFoldAfterTheirFirstTwo() {
        val notes = Section(null, lines = listOf(Text("One"), Text("Two"), Blank, Text("Three")))
        val html = SheetPage.preambleHtml(notes, emptyList())
        assertTrue(html.startsWith("<details class=\"pre\">\n<summary><span class=\"peek\">One<br>Two</span>"), html)
        assertEquals("<div class=\"pre\">\n<p class=\"l\">One</p>\n<p class=\"l\">Two</p>\n</div>\n",
                     SheetPage.preambleHtml(Section(null, lines = listOf(Text("One"), Text("Two"))), emptyList()))
    }

    @Test fun theFactsAreTuningCapoAndKeyTheKeySayingTheShapesAndTheSound() {
        assertEquals("E A D G B E", SheetPage.GUITAR_STRINGS)
        assertEquals("<dl class=\"facts\" id=\"facts\">\n" +
                     "<div class=\"fact\" data-fact=\"tuning\"><dt>Tuning</dt><dd>E A D G B E</dd></div>\n" +
                     "<div class=\"fact\" data-fact=\"capo\"><dt>Capo</dt><dd>none</dd></div>\n" +
                     "<div class=\"fact\" data-fact=\"key\"><dt>Key</dt><dd><b>Am</b> · " +
                     "<span class=\"from\">from the tab</span></dd></div>\n</dl>\n",
                     SheetPage.factsHtml(Key(9, "aeolian"), "from the tab", 0, null, chords = true))
        val capo = SheetPage.factsHtml(Key(4, "aeolian"), null, 2, "Drop <D>", chords = true, suffix = "-3")
        assertTrue(capo.startsWith("<dl class=\"facts\" id=\"facts-3\">\n"), capo)
        assertTrue("<dd>Drop &lt;D&gt;</dd>" in capo && "<dd>2</dd>" in capo, capo)
        assertTrue("<dd><b>Em</b> shapes · sounds <b>F#m</b></dd>" in capo, capo)
        assertTrue("data-fact=\"key\"" !in SheetPage.factsHtml(null, "from the tab", 3, null, chords = true))
        // A sheet with no chords (a tab alone): its Capo line alone, where it names a capo.
        assertEquals("<dl class=\"facts\" id=\"facts\">\n<div class=\"fact\" data-fact=\"capo\"><dt>Capo</dt><dd>3</dd></div>\n" +
                     "</dl>\n", SheetPage.factsHtml(Key(4, "aeolian"), "from the tab", 3, null, chords = false))
        assertEquals("", SheetPage.factsHtml(Key(4, "aeolian"), "from the tab", 0, "Drop D", chords = false))
    }
}
