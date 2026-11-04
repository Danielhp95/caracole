package io.github.danielhp95.caracole.viewer.harptab

import io.github.danielhp95.caracole.core.py.PyText
import io.github.danielhp95.caracole.core.testing.Corpus
import io.github.danielhp95.caracole.core.testing.Misses
import io.github.danielhp95.caracole.viewer.testing.replays.HarptabReplay
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonPrimitive
import org.junit.Test
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith
import kotlin.test.assertFalse
import kotlin.test.assertNull
import kotlin.test.assertTrue

/** viewer.harptab reads a tab as viewer/harptab.py does: every record of vectors/viewer/harptab_read.jsonl
 * (HarptabReplay), and test_viewer_harptab_notation.py's own cases, by hand. */
class ReadingTest {
    @Test fun theDataIsTheModules() = Misses("harptab.json").let { HarptabReplay.dataIsTheModules(it); it.assertNone() }
    @Test fun everyReadingRecordIsHarptabPys() = HarptabReplay.read()

    private val signs = HarpTabs.SIGNS
    private val brackets = HarpTabs.BRACKETS
    private val letters = HarpTabs.LETTERS
    private val signsAfter = HarpTabs.SIGNS_AFTER
    private val barrett = HarpTabs.BARRETT

    /** test_viewer_harptab_notation.reads: each group's label, an unread span as `?` and its text, a run `~`, an
     * effect in brackets, a hold `…`. */
    private fun reads(token: String, notation: Notation): List<String> = HarpTabs.scan(token, notation).groups.map { g ->
        (if (g.kind == "unread") "?" + g.text else g.label()) + g.effects.joinToString("") { "[$it]" } +
            (if (g.hold) "…" else "") + (if (g.join) "~" else "")
    }

    @Test fun eachPresetReadsItsTokens() {
        val tokens = listOf(
            Triple(signs, "4", listOf("4")), Triple(signs, "-4", listOf("−4")), Triple(signs, "–4", listOf("−4")),
            Triple(signs, "-3''", listOf("−3′′")), Triple(signs, "-3bb", listOf("−3′′")), Triple(signs, "bb-3", listOf("−3′′")),
            Triple(signs, "-b3", listOf("−3′")), Triple(signs, "6o", listOf("6°")), Triple(signs, "-4<", listOf("−4<")),
            Triple(signs, "<-4", listOf("−4<")), Triple(signs, "-45", listOf("−4", "5")), Triple(signs, "4----", listOf("4…")),
            Triple(signs, "4d", listOf("?4d")), Triple(signs, "(5)", listOf("?(", "5", "?)")), Triple(signs, "(-5)", listOf("−5")),
            Triple(signs, "(4 5)", listOf("(4 5)")), Triple(signs, "2nd", listOf("?2nd")), Triple(signs, "x2", emptyList()),
            Triple(brackets, "(5)", listOf("−5")), Triple(brackets, "(45)", listOf("(−4 −5)")), Triple(brackets, "(3)b", listOf("−3′")),
            Triple(brackets, "(4)-(5)", listOf("−4~", "−5")), Triple(brackets, "-4", listOf("?-", "4")),
            Triple(letters, "4B", listOf("4")), Triple(letters, "3**d", listOf("−3′′")), Triple(letters, "-3'D", listOf("?-", "−3′")),
            Triple(letters, "3**d-3*d-3d", listOf("−3′′~", "−3′~", "−3")), Triple(letters, "3-4b", listOf("?3~", "4")),
            Triple(letters, "4d-$-5d", listOf("−4~", "?$~", "−5")), Triple(letters, "7,8B", listOf("(7 8)")),
            Triple(letters, "4", listOf("?4")), Triple(letters, "3*d(W)", listOf("−3′", "?(W)")),
            Triple(signsAfter, "6-", listOf("−6")), Triple(signsAfter, "6--", listOf("6…")), Triple(signsAfter, "6-7", listOf("6", "?-", "7")),
            Triple(signsAfter, "456-", listOf("4", "5", "6", "?-")), Triple(signsAfter, "4-'", listOf("−4′")),
            Triple(barrett, "3", listOf("−3")), Triple(barrett, "4+", listOf("4")), Triple(barrett, "2’’", listOf("−2′′")),
            Triple(barrett, "-4", listOf("?-", "−4")),
        )
        for ((notation, token, found) in tokens) assertEquals(found, reads(token, notation), "${notation.name}: $token")
    }

    @Test fun aNotationIsItsTableAndItsTokenizerIsMadeFromIt() {
        val mine = Notation("mine", listOf(Symbol("^", "draw", "before"), Symbol("u", "bend", "after"),
                                           Symbol("~", "join", "between")))
        assertEquals(listOf("−3′~", "4", "−2′′"), reads("^3u~4 ^2uu", mine))
        val changed = signs.changed(listOf(Symbol("*", "bend", "after"), Symbol("(w)", "wah", "after")))
        assertEquals(Symbol("*", "bend", "after"), changed.meaning("*", "after"))
        assertEquals("slide", changed.meaning("<", "after")!!.means)
        assertEquals(listOf("−3′", "4[wah]"), reads("-3* 4(w)", changed))
        assertEquals(listOf("−3′", "4[wah]"), reads("-3* 4 (w)", changed))
    }

    @Test fun whatAScanUsedIsCountedAsWritten() {
        assertEquals(mapOf(Used("b", "blow", "after", 1) to 2, Used("B", "blow", "after", 1) to 1,
                           Used("d", "draw", "after", 1) to 1, Used("*", "bend", "after", 1) to 1,
                           Used("-", "join", "between", 1) to 1),
                     HarpTabs.scan("3*d 3b 3B 3-4b", letters).used)
        assertEquals(mapOf(Used("", "blow", "bare", 1) to 2, Used("()", "draw", "around", 1) to 1),
                     HarpTabs.scan("4 -4 (5)", brackets).used)
    }

    @Test fun aColumnIsACodePointAsPythonCountsIt() {
        // 🎵 is two UTF-16 units and one code point: the hole after it is at Python's column 2
        val found = HarpTabs.scan("🎵 4 -5", signs)
        assertEquals(listOf(2, 4), found.groups.filter { it.holes.isNotEmpty() }.map { it.col })
        assertEquals(6, found.groups.last().end)
        // a tab is expanded by code points too
        assertEquals("🎵       4", HarpTabs.expand("🎵\t4"))
    }

    @Test fun theReadingThatExplainsTheMostOfWhatAHarpPlaysWins() {
        val (reading, _) = HarpTabs.read(listOf("3b 3b 2b 3d", ""))
        assertEquals("letters", reading.notation.name)
        assertEquals(Triple(1.0, 1.0, 1.0), Triple(reading.explained, reading.playable, reading.q))
        assertEquals("signs", reading.runner)
        val (tie, _) = HarpTabs.read(listOf("4 4 5 5 6 6 5"))
        assertEquals("signs", tie.notation.name)
        assertEquals(0.0, tie.margin)
        assertEquals("barrett", tie.runner)
    }

    @Test fun anUnusualReadingMustBeatACommonerOneByTheMargin() {
        val thin = HarpTabs.read(listOf(List(14) { "4 5 6" }.joinToString(" ") + " (5)")).first
        assertEquals("brackets", thin.notation.name)
        assertTrue(thin.margin < 0.05)
        assertFalse(thin.confident)
        val clear = HarpTabs.read(listOf(List(8) { "4 5 6" }.joinToString(" ") + " (5) (6)")).first
        assertTrue(clear.confident)
    }

    @Test fun aLegendInEachShapeTheTabsWrite() {
        val found = HarpTabs.legend(listOf("4b 5d", "", "(w) = Wah effect", "(h) = Hold", "* = bend", "D= draw", "b= blow"))
        assertEquals(1, found.size)
        assertEquals(listOf(2, 3, 4, 5, 6), found[0].at)
        assertEquals(listOf(Symbol("(w)", "wah", ""), Symbol("(h)", "hold", ""), Symbol("*", "bend", ""),
                            Symbol("D", "draw", ""), Symbol("b", "blow", "")), found[0].symbols)
        assertEquals(listOf(Symbol("b", "bend", ""), Symbol("()", "draw", "around"), Symbol("", "blow", "bare")),
                     HarpTabs.legend(listOf("b = bending", "(numero) = aspirar", "numero = soplar"))[0].symbols)
        for (none in listOf(listOf("Key: D", "Tuning: standard"), listOf("b = blow"), listOf("Chorus: x2", "Verse: 3"),
                            listOf("4  -4  5", "-5  6  -6"))) {
            assertEquals(emptyList(), HarpTabs.legend(none), none.toString())
        }
    }

    private val spokey: String by lazy { PyText.utf8(Corpus.fixture("harptabs/legends/693_spokey-dokey.txt"))!! }

    @Test fun spokeyDokeyReadsAsItsOwnLegendSays() {
        val found = HarpTabs.readings(spokey)
        assertEquals("letters", found[0].notation.name)
        assertEquals("legend", found[0].source)
        assertEquals("b blow · d draw · * bend · - joins · (h) hold · (w) wah", found[0].said())
        assertEquals(listOf("legend", "letters", "brackets", "signs after", "barrett", "signs"),
                     found.map { (HarpTabs.specOf(it) as JsonPrimitive).content })
        assertEquals(found.map { it.score }.sortedDescending(), found.map { it.score })
    }

    private fun spec(text: String): JsonElement = Json.parseToJsonElement(text)

    @Test fun aPinNamesAPresetTheTabsOwnLegendOrAPresetChanged() {
        assertEquals(letters, HarpTabs.pinned(JsonPrimitive("letters"), "4 5 6\n"))
        val starred = "-1 -2 -3* -3*\nla la la la\n"
        val pinned = HarpTabs.pinned(spec("""{"as": "signs", "*": "bend"}"""), starred)!!
        assertEquals(Symbol("*", "bend", "after"), pinned.meaning("*", "after"))
        assertNull(HarpTabs.pinned(JsonPrimitive("legend"), "4 5 6\n"))
        assertTrue(HarpTabs.DOTS in HarpTabs.pinned(JsonPrimitive("signs"), ". 4 4 -4 5 . 7\n")!!.symbols)
        assertEquals(spec("""{"as": "signs", "*": "bend"}"""), HarpTabs.specOf(HarpTabs.readings(starred, "Diatonic")[0]))
    }

    @Test fun aPinThatCantBeReadSaysWhatItTakes() {
        for ((text, said) in listOf(
            "\"staff\"" to "expected signs, brackets, letters, signs after, barrett or legend, got 'staff'",
            """{"as": "staff"}""" to "as: expected signs, brackets, letters, signs after or barrett, got 'staff'",
            """{"*": 2}""" to "'*': expected what a symbol means",
            """{"": "bend"}""" to "expected a symbol, as the tab writes it, got ''",
            """{"(4)": "bend"}""" to "'(4)': a hole alone, or in brackets, can only be a blow or a draw",
            "3" to "expected a notation's name or a table of what its symbols mean, got 3",
            "[1.5, true, null]" to "expected a notation's name or a table of what its symbols mean, got [1.5, True, None]",
            """{"as": ["signs"]}""" to "cannot use 'list' as a dict key (unhashable type: 'list')",
        )) {
            val e = assertFailsWith<IllegalArgumentException>(text) { HarpTabs.checkSpec(spec(text)) }
            assertTrue(e.message!!.startsWith(said), "$text: ${e.message}")
        }
    }

    @Test fun harptabsComsOwnNotationGuessedIsTheStandardReading() {
        for (stem in listOf("588_hotel-california", "1882_juke", "10228_whammer-jammer")) {
            assertTrue(HarpTabs.readings(PyText.utf8(Corpus.fixture("harptabs/tabs/$stem.txt"))!!)[0].standard, stem)
        }
        assertFalse(HarpTabs.readings(spokey)[0].standard)
        assertFalse(HarpTabs.readings("-1 -2 -3* -3*\nla la la la\n", "Diatonic")[0].standard)
        assertTrue(HarpTabs.readings("-1 -2 -3 4\nla la la la\n", "Diatonic")[0].standard)
    }

    @Test fun pythonsStringMethodsAsPythonsAre() {
        assertEquals("aς", HarpTabText.swapcase("AΣ"))
        assertEquals("aσb", HarpTabText.swapcase("AΣB"))
        assertEquals("ας", HarpTabText.swapcase("ΑΣ"))
        assertEquals("ǅ", HarpTabText.swapcase("ǅ"))
        assertEquals("SS", HarpTabText.swapcase("ß"))
        assertEquals("cafe", HarpTabText.foldAccents("café"))
        assertTrue(HarpTabText.isWord("tue", alone = true))
        assertFalse(HarpTabText.isWord("SB", alone = true))
        assertTrue(HarpTabText.isWord("u", alone = false))
        assertEquals("a       b", HarpTabText.expand("a\tb"))
    }
}
