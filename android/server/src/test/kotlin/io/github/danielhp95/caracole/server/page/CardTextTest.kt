package io.github.danielhp95.caracole.server.page

import io.github.danielhp95.caracole.core.testing.Corpus
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonPrimitive
import org.junit.Test
import kotlin.test.assertEquals
import kotlin.test.assertTrue

/** What a phone song's card writes for the page to sort, letter, filter and list it by: library_page.py's. */
class CardTextTest {
    @Test
    fun `sort keys, letters, initials and haystacks are library_page's (cards_jsonl)`() {
        waitingOnKeys()
        val records = Corpus.records("web/cards.jsonl")
        assertTrue(records.size > 200)
        for (r in records) {
            val made = when (r.fn) {
                "caracole.library_page._sort_key" -> CardText.sortKey(r.args[0].jsonPrimitive.content)
                "caracole.library_page._letter" -> CardText.letter(r.args[0].jsonPrimitive.content)
                "caracole.library_page._initials" -> CardText.initials(r.args[0].jsonPrimitive.content)
                "caracole.library_page._haystack" -> CardText.haystack(r.args[0].jsonArray.map { it.jsonPrimitive.content })
                else -> throw AssertionError("no port of ${r.fn}")
            }
            assertEquals(r.out!!.jsonPrimitive.content, made, "${r.fn}(${r.args})")
        }
    }

    @Test
    fun `a letter is the sort key's first, A to Z, else #`() {
        assertEquals(listOf("B", "Z", "#", "#", "#", "#"), listOf("beatles", "zz", "1999", "", "é", "😀").map { CardText.letter(it) })
    }

    @Test
    fun `a kept file is listed in its line's order, labelled as the computer's page labels it`() {
        val names = setOf("info.json", "tab.txt", "harmonica-1.txt", "score-1.mxl", "score-1.pdf", "score-2.mscz",
                          "guitar-10.gp5", "guitar-2.ptb", "sheet.txt", "sheet.pdf", "lyrics.lrc", "gametab-1.txt",
                          "sheet.json", "version-12.txt", "score-3.doc")
        assertEquals(listOf("sheet.pdf", "sheet.txt", "lyrics.lrc", "guitar-2.ptb", "guitar-10.gp5", "score-1.mxl",
                            "score-1.pdf", "score-2.mscz", "harmonica-1.txt", "gametab-1.txt", "tab.txt", "info.json"),
                     CardText.inLineOrder(names))
        assertEquals(listOf("Sheet PDF", "Sheet text", "Timed lyrics", "Power Tab 2", "Guitar Pro 10", "Score 1 (MusicXML)",
                            "Score 1 (PDF)", "Score 2 (MuseScore)", "Harmonica tab 1", "Game music tab 1", "Tab", "Info"),
                     CardText.inLineOrder(names).map { CardText.label(it) })
    }

    @Test
    fun `a file's link is its path, each part percent-encoded as quote(part, safe="") encodes it`() {
        assertEquals("Guns%20N%27%20Roses/100%25%20%231%20Hit/sheet%20%28auto%29.html",
                     CardText.href("Guns N' Roses/100% #1 Hit/sheet (auto).html"))
        assertEquals("%C3%91and%C3%BA/%E6%96%91%E9%A9%AC/a_b.c-d~e.txt", CardText.href("Ñandú/斑马/a_b.c-d~e.txt"))
    }
}
