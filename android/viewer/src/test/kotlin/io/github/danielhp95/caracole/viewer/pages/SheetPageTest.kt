package io.github.danielhp95.caracole.viewer.pages

import io.github.danielhp95.caracole.core.testing.Misses
import io.github.danielhp95.caracole.viewer.sheet.Blank
import io.github.danielhp95.caracole.viewer.sheet.ChordRow
import io.github.danielhp95.caracole.viewer.sheet.Item
import io.github.danielhp95.caracole.viewer.sheet.Lyrics
import io.github.danielhp95.caracole.viewer.sheet.Section
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

    @Test fun theControlsHoldTheHarmonyRowOnceForTheGuitarProRowToFollow() {
        val harmony = "<div id=\"harmony-row\" hidden>"
        assertEquals(1, SheetPage.CONTROLS.split(harmony).size - 1)
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
                "<p class=\"l chords\"><b class=\"c\" data-c=\"0\" tabindex=\"0\" role=\"button\">G</b> <i class=\"m\">|</i></p>\n" +
                "</section>\n",
            SheetPage.sectionHtml(section, listOf("G")),
        )
    }

    @Test fun notesOfMoreThanTwoLinesFoldAfterTheirFirstTwo() {
        val notes = Section(null, lines = listOf(Text("One"), Text("Two"), Blank, Text("Three")))
        val html = SheetPage.preambleHtml(notes, emptyList())
        assertTrue(html.startsWith("<details class=\"pre\">\n<summary><span class=\"peek\">One<br>Two</span>"), html)
        assertEquals("<div class=\"pre\">\n<p class=\"l\">One</p>\n<p class=\"l\">Two</p>\n</div>\n",
                     SheetPage.preambleHtml(Section(null, lines = listOf(Text("One"), Text("Two"))), emptyList()))
    }

    @Test fun theKeyLineSaysTheShapesTheCapoAndTheSound() {
        assertEquals("Key <b>Em</b> <span class=\"from\">from the tab</span>",
                     SheetPage.facts(Key(4, "aeolian"), "from the tab", 0))
        assertEquals("<b>Em</b> shapes · capo <b>2</b> · sounds <b>F#m</b>", SheetPage.facts(Key(4, "aeolian"), null, 2))
        assertEquals("Capo <b>3</b>", SheetPage.facts(null, "from the tab", 3))
        assertEquals("", SheetPage.facts(null, null, 0))
    }
}
