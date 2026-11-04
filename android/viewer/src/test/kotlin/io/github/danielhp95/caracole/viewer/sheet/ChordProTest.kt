package io.github.danielhp95.caracole.viewer.sheet

import io.github.danielhp95.caracole.core.py.PyStr
import io.github.danielhp95.caracole.core.testing.Corpus
import io.github.danielhp95.caracole.viewer.testing.replays.SheetReplay
import org.junit.Test
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith
import kotlin.test.assertFalse
import kotlin.test.assertTrue

/** viewer.sheet.ChordPro converts UG markup as chordpro.py does, with render._as_latin and ug.page.decode_twice:
 * every record of vectors/viewer/chordpro.jsonl (SheetReplay), and test_chordpro.py's own cases, by hand. */
class ChordProTest {
    @Test fun everyRecordIsChordProPys() = SheetReplay.chordPro()

    private fun fixture(name: String): String = String(Corpus.fixture("chordpro/$name"), Charsets.UTF_8)

    /** The converted document without its header directives. */
    private fun body(content: String, key: String? = null): List<String> =
        PyStr.splitlines(ChordPro.toChordPro(content, "Test Song", "Test Artist", key))
            .filterNot { it.startsWith("{title:") || it.startsWith("{artist:") }

    @Test fun aChordLineOverALyricLineIsOneLine() {
        assertEquals(listOf("[G]Hello there my [D]friend"), body("[tab][ch]G[/ch]              [ch]D[/ch]\nHello there my friend[/tab]"))
        assertEquals("One [Am]two [F]three", ChordPro.mergeChordLine("    [ch]Am[/ch]  [ch]F[/ch]", "One two three"))
        assertEquals("[C]Hi      [G]", ChordPro.mergeChordLine("[ch]C[/ch]       [ch]G[/ch]", "Hi"))
        assertEquals(listOf("[G] [D] [Em] [C]", "", "A lyric after a blank"),
                     body("[ch]G[/ch]   [ch]D[/ch]  [ch]Em[/ch]    [ch]C[/ch]\n\nA lyric after a blank"))
        assertEquals(listOf("[G] [D]", "[Em]Words [C]under the second"),
                     body("[ch]G[/ch]  [ch]D[/ch]\n[ch]Em[/ch]    [ch]C[/ch]\nWords under the second"))
    }

    @Test fun sectionsHeadersTabsAndTheHeader() {
        for ((header, comment) in listOf("[Verse 1]" to "Verse 1", "  [Pre-Chorus]  " to "Pre-Chorus")) {
            assertEquals(listOf("{comment: $comment}"), body(header))
        }
        assertEquals(listOf("{start_of_tab}", "e|---3---|", "B|---0---|", "G|---0---|", "{end_of_tab}"),
                     body("[tab]e|---3---|\nB|---0---|\nG|---0---|[/tab]"))
        assertEquals(listOf("{title: De Música Ligera}", "{artist: Soda Stereo}", "{key: Bm}", "{capo: 2}"),
                     PyStr.splitlines(ChordPro.toChordPro("", "De Música Ligera", "Soda Stereo", "Bm", 2)).take(4))
        assertEquals(listOf("{title: T}", "{artist: A}", "[G]"), PyStr.splitlines(ChordPro.toChordPro("[ch]G[/ch]", "T", "A")))
        assertTrue("{comment: auto-generated, unverified}" in ChordPro.toChordPro("[ch]G[/ch]", "T", "A", auto = true))
        for ((key, capo) in listOf("  " to null, null to "0", "" to " ")) {
            assertEquals(listOf("{title: T}", "{artist: A}"), PyStr.splitlines(ChordPro.toChordPro("", "T", "A", key, capo)))
        }
        assertTrue("{capo: 3}" in PyStr.splitlines(ChordPro.toChordPro("", "T", "A", null, " 3 ")))
        assertEquals(listOf("{comment: Chorus x2}"), body("[Chorus] x2"))
        assertEquals(listOf("{comment: Intro}", "[G] [D]", "Words"), body("[Intro] [ch]G[/ch] [ch]D[/ch]\nWords"))
    }

    @Test fun chordLinesAndChordNames() {
        for (line in listOf("[ch]G[/ch]  [ch]D[/ch]", "| [ch]G[/ch] | [ch]D[/ch] |", "[ch]Bm[/ch]-[ch]G[/ch]-[ch]D[/ch]-[ch]A[/ch](4)",
                            "[ch]G[/ch] / / / [ch]D[/ch] / / /  x2", "[ch]Dm[/ch]    Dm/F    [ch]E[/ch]")) {
            assertTrue(ChordPro.isChordLine(line), line)
        }
        for (line in listOf("Hello there my friend", "", "CHORDS:[ch]Bm[/ch], [ch]G[/ch], [ch]D[/ch]", "[Verse 1]",
                            "[ch]G[/ch] La la la", "[ch]G[/ch]  C D E F")) {
            assertFalse(ChordPro.isChordLine(line), line)
        }
        for ((typed, name) in listOf("am" to "Am", "em7" to "Em7", "dm/f" to "Dm/F", "Do#m7" to "C#m7", "Sib" to "Bb",
                                     "Mi7/Sol#" to "E7/G#", "Famaj7" to "Fmaj7", "LAm" to "Am", "Fadd9" to "Fadd9",
                                     "x2" to "x2", "capo" to "capo", "A/" to "A/", "" to "")) {
            assertEquals(name, ChordPro.normalizeChord(typed), typed)
        }
        // a solfège name sre's IGNORECASE reads but no table holds raises, as Python's KeyError does
        assertFailsWith<NoSuchElementException> { ChordPro.normalizeChord("ſol") }
    }

    @Test fun whatChordProWouldMisreadIsEscaped() {
        val esc = "\\u005c"
        assertEquals(listOf("Sing it again (x2)"), body("Sing it again [x2]"))
        assertEquals(listOf("Worth 100%(title) of it"), body("Worth 100%{title} of it"))
        assertEquals(listOf(" #1 in my heart"), body("#1 in my heart"))
        assertEquals(listOf("Line ends here $esc", "Next line"), body("Line ends here \\\nNext line"))
        assertEquals(listOf("Odd ${esc}u0041 text"), body("Odd \\u0041 text"))
        assertEquals(listOf("Hold ‹b>this‹/b> note"), body("Hold <b>this</b> note"))
        assertEquals(listOf("I <3 you"), body("I <3 you"))
        assertEquals("[‹img src=\"x.png\"/>]Hi", ChordPro.mergeChordLine("[ch]<img src=\"x.png\"/>[/ch]", "Hi"))
        assertEquals(listOf("[‹b>G‹/b>] [(D)]"), body("[ch]<b>G</b>[/ch] [ch]{D}[/ch]"))
        assertEquals(listOf("{start_of_tab}", " #riff", "e|--5\\3--[x]--|", "B|--------$esc", "(eot)", "G|---<b>---|", "{end_of_tab}"),
                     body("[tab]#riff\ne|--5\\3--[x]--|\nB|--------\\\n{eot}\nG|---<b>---|[/tab]"))
    }

    @Test fun columnsAreDisplayColumns() {
        assertEquals("[C]这是一个[G]合成的例子", ChordPro.mergeChordLine("[ch]C[/ch]       [ch]G[/ch]", "这是一个合成的例子"))
        assertEquals("[Am]测试", ChordPro.mergeChordLine(" [ch]Am[/ch]", "测试"))
        assertEquals("[G]Once more[*(x2)] again", ChordPro.mergeChordLine("[ch]G[/ch]        (x2)", "Once more again"))
        assertEquals(listOf(0, 1, 2, 8, 10, 11, 11, 12), ChordPro.displayColumns("ab\t我e\u0301x"))
        // an astral character is one code point: two columns, and the chord after it where Python puts it
        assertEquals(listOf(0, 2, 3), ChordPro.displayColumns("\uD83D\uDE00a"))
        assertEquals("\uD83D\uDE00 [G]rock", ChordPro.mergeChordLine("   [ch]G[/ch]", "\uD83D\uDE00 rock"))
        assertEquals("[Em7]Today is gonn[G]a be the day",
                     PyStr.splitlines(ChordPro.toChordPro("[Verse]\n[ch]Em7[/ch]            [ch]G[/ch]\n  Today is gonna be the day\n", "T", "A")).last())
    }

    @Test fun wholeSheets() {
        assertEquals(fixture("ug_sheet.cho"),
                     ChordPro.toChordPro(fixture("ug_sheet.txt"), "Synthetic Test Song", "The Placeholders", "G", 2))
        assertEquals(listOf("{comment: Verse}", "[C]这是一个[G]合成的例子", "[Am]测试歌词第二[F]行", "", "{comment: Chorus}",
                            "[F]和弦[C]只为检查[G]对齐"), body(fixture("zh_sheet.txt")))
        assertEquals(listOf("Intro:", "", "[Bm] [G] [D] [A] [*(4)]", "", "[Bm]Palabras [G]de prueba aqui"),
                     body("Intro:\n\n[ch]Sim[/ch]-[ch]Sol[/ch]-[ch]Re[/ch]-[ch]La[/ch](4)\n\n[ch]Sim[/ch]      [ch]Sol[/ch]\nPalabras de prueba aqui"))
        assertEquals(listOf("[G]Hello", "", "Bye"), body("[ch]G[/ch]\r\nHello\r\n\r\nBye\r\n"))
        assertEquals(listOf("[G]Hello", "Next"), body("[tab]\n[ch]G[/ch]\nHello\n[/tab]\nNext"))
        assertEquals(listOf("One", "", "", "Two"), body("\n\nOne\n\n\nTwo\n\n"))
        assertEquals(listOf("{comment: Intro}", "{start_of_tab}", "e|-----0-----|", "B|---1---1---|", "G|-2-------2-|",
                            "{end_of_tab}", "Some words"),
                     body("[Intro]\ne|-----0-----|\nB|---1---1---|\nG|-2-------2-|\nSome words"))
    }

    @Test fun aChordNobodyTaggedIsAChordAllTheSame() {
        val forgotten = "[tab][ch]Am[/ch]    [ch]Am/C[/ch]    [ch]Dm[/ch]    Dm/F    [ch]E[/ch]   x2\nQue lindo que es estar en la tierra[/tab]"
        val tagged = forgotten.replace("    Dm/F    ", "    [ch]Dm/F[/ch]    ")
        assertEquals(ChordPro.toChordPro(tagged, "T", "A"), ChordPro.toChordPro(forgotten, "T", "A"))
        assertEquals("[Am] [Dm/F] [E]", PyStr.splitlines(ChordPro.toChordPro("[ch]Am[/ch]  Dm/F  [ch]E[/ch]\n\nNext line", "T", "A"))[2])
        // the columns a forgotten tag goes in are code points, past an astral character too
        assertEquals("[ch]\uD83D\uDE00[/ch] [ch]Am[/ch]", ChordPro.tagForgotten("[ch]\uD83D\uDE00[/ch] Am"))
    }

    @Test fun lookAlikeLettersAreWrittenInLatinOnlyWhenTheyAreAllTheFontsLose() {
        assertEquals("x2 AB", ChordPro.asLatin("\u04452 \u0410\u0412"))
        assertEquals("Русский \u04452", ChordPro.asLatin("Русский \u04452"))
        assertEquals("€ café — x2", ChordPro.asLatin("€ café — x2"))
        assertFalse(ChordPro.needsFontFile("€ café — ‰ Ÿ"))
        assertTrue(ChordPro.needsFontFile("\u0081"))
        assertTrue(ChordPro.needsFontFile("我"))
        assertEquals("[ch]Am[/ch] &feature", ChordPro.decodeTwice("[ch]Am[/ch] &amp;amp;feature"))
        assertEquals("&amp;x", ChordPro.decodeTwice("&amp;amp;amp;x")) // twice, never more
    }
}
