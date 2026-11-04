package io.github.danielhp95.caracole.viewer.harptab

import io.github.danielhp95.caracole.core.py.PyText
import io.github.danielhp95.caracole.core.testing.Corpus
import io.github.danielhp95.caracole.viewer.testing.replays.HarptabReplay
import org.junit.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertIs
import kotlin.test.assertNull
import kotlin.test.assertTrue

/** viewer.harptab lays a read tab out as viewer/harptab.py does: every record of vectors/viewer/harptab_layout.jsonl
 * (HarptabReplay), and test_viewer_harptab_layout.py's and test_viewer_harptab.py's layout cases, by hand. */
class LayoutTest {
    @Test fun everyLayoutRecordIsHarptabPys() = HarptabReplay.layout()

    private fun fixture(path: String): String = PyText.utf8(Corpus.fixture("harptabs/$path.txt"))!!

    private fun tab(stem: String): Tab = HarpTabs.parse(fixture("tabs/$stem"))

    /** test_viewer_harptab_layout.CHIPS: each layout fixture's harp chip, as its page shows it. */
    private val chips = mapOf("5370_19-dias-y-500-noches" to "Diatonic", "12631_en-brazos-de-la-fiebre-with-lyric" to "Diatonic",
                              "16988_l-l-og-mere-l" to "Diatonic", "29720_te-amar-a-massa-demais" to null,
                              "14346_william-tell-overture" to "Diatonic", "23467_mon-anci-1-2tre-gurdil" to "Diatonic",
                              "7018_music-of-the-day" to "Diatonic", "28721_atun" to "Diatonic",
                              "20960_when-the-ship-comes-in-solo" to "Diatonic")

    private fun laid(stem: String): Tab = HarpTabs.parse(fixture("layout/$stem"), chips.getValue(stem))

    /** The fixture's lines as parse reads them. */
    private fun textOf(stem: String): List<String> =
        fixture("layout/$stem").split("\n").map { HarpTabText.rstrip(HarpTabText.expand(it)) }

    /** A row's parts as the page shows them: each place's holes, and the words sung from there. */
    private fun holesOf(row: Row): List<Pair<List<String>, String>> =
        row.parts.map { (groups, text) -> groups.filter { it.holes.isNotEmpty() }.map { it.label() } to text }

    private fun row(holes: String, lyric: String): List<Pair<List<String>, String>> =
        holesOf(HarpTabs.align(Row(HarpTabs.scan(holes).groups, lyric)))

    // --- a section's name, or words sung; a line of holes, never a row's words ---------------------------------------

    @Test fun aLineSungThatStartsAsASectionsNameIsARowsWordsBesideARow() {
        val read = HarpTabs.parse("4 5 6 6\nEnd of the road\n-4 -5 6\nBreak my heart\n")
        assertEquals(listOf("End of the road", "Break my heart"), read.rows().map { it.lyric })
        assertEquals(listOf<String?>(null), read.sections.map { it.label })
    }

    @Test fun aSectionsNameBesideARowIsASectionStill() {
        for (name in listOf("Chorus", "INTRO", "fade:", "(D harp):", "Synth 1:", "bar 12:", "Refr.:", "(Chorus)", "[V1]",
                            "2. Strophe:", "Harp: C", "A part:", "refrain :", "(Repetir 2x)", "Verse 2", "Harmonica solo",
                            "Repeat chorus x2")) {
            val read = HarpTabs.parse("4 5 6\n$name\n-4 -5 6\nla la la\n")
            assertNull(read.rows()[0].lyric, name)
            assertTrue(read.sections.size == 2 && !read.sections[1].label.isNullOrEmpty(), name)
        }
        assertEquals("Break it down", HarpTabs.parse("Break it down\n\n4 5 6\nla la la\n").sections[0].label)
    }

    @Test fun aLineOfHolesUnderARowIsNeverItsWords() {
        val read = laid("14346_william-tell-overture")
        assertNull(read.rows().first { it.line == 2 }.lyric)
        assertTrue(read.sections.any { s -> s.items.any { it is Prose && it.text == "te 3, dbiz zi 6" } })
        assertEquals("I've got 99 problems now", HarpTabs.parse("4 5 6 7\nI've got 99 problems now\n").rows()[0].lyric)
    }

    // --- words written above their holes -----------------------------------------------------------------------------

    @Test fun nineteenDiasWritesEachRowsWordsAboveIt() {
        val read = laid("5370_19-dias-y-500-noches")
        val lines = textOf("5370_19-dias-y-500-noches")
        val rows = read.rows()
        assertTrue(rows.all { it.above && it.lyric == lines[it.line - 1] })
        assertEquals(74, rows.size)
        assertEquals(emptyList(), read.notes)
        assertEquals(listOf(listOf("−5") to "Xo ", listOf("−5") to "ruav", listOf("5") to "tfi ", listOf("−4") to "ki",
                            listOf("4") to "pu"), holesOf(rows[0]))
    }

    @Test fun aTabWhoseWordsSitAboveWithABlankLineUnderEachRow() {
        val read = laid("16988_l-l-og-mere-l")
        val lines = textOf("16988_l-l-og-mere-l")
        assertEquals(12, read.rows().size)
        assertTrue(read.rows().all { it.above && it.lyric == lines[it.line - 1] })
        assertEquals(listOf(listOf("6") to "Ib, ", listOf("6") to "es ", listOf("−5") to "aq ", listOf("−5") to "xi",
                            listOf("5") to "wo ", listOf("5") to "ev."), holesOf(read.rows()[0]))
    }

    @Test fun teAmarWritesItsWordsAboveHolesWrittenTogether() {
        val rows = laid("29720_te-amar-a-massa-demais").rows()
        val lines = textOf("29720_te-amar-a-massa-demais")
        assertEquals(0, rows[0].line)
        assertNull(rows[0].lyric)
        assertTrue(rows.drop(1).all { it.above && it.lyric == lines[it.line - 1] })
        assertEquals(31, rows.size)
    }

    @Test fun enBrazosWritesAPieceOfAWordAboveEachRow() {
        val rows = laid("12631_en-brazos-de-la-fiebre-with-lyric").rows()
        val lines = textOf("12631_en-brazos-de-la-fiebre-with-lyric")
        assertEquals(120, rows.size)
        assertTrue(rows.filter { it.lyric != null }.all { it.lyric == lines[it.line - 1] })
        assertTrue(rows.count { it.lyric != null } >= 110)
        assertEquals("Raw zog" to "vjedap", rows[0].lyric to rows[1].lyric)
    }

    @Test fun wordsUnderTheirRowsStayUnderThem() {
        val read = HarpTabs.parse("A Title Here\n4 5 6 7\nla la la la\n5 6 7 8\nlo lo lo lo\n")
        assertEquals(listOf("la la la la" to false, "lo lo lo lo" to false), read.rows().map { it.lyric to it.above })
        assertEquals(listOf("A Title Here"), read.notes)
    }

    @Test fun aLineOfLettersAboveEachRowIsNoWords() {
        val read = HarpTabs.parse(" w    q q  q  q\n-4 / -4 4 -3 -2\n\n h  q  q   q q q q\n-2 -1 -2 / -2 -1 -2 -1\n\n" +
                                  "  e  e e  e  h\n-4 -1 -4 -1 4\n")
        assertEquals(listOf<String?>(null, null, null), read.rows().map { it.lyric })
    }

    // --- the tabber's words inside a line of holes -------------------------------------------------------------------

    @Test fun monAncetreGurdilReadsEveryRowItsPercussionsInPlace() {
        val rows = laid("23467_mon-anci-1-2tre-gurdil").rows()
        assertEquals(7, rows.size)
        assertTrue(rows.all { it.trusted })
        assertEquals(listOf("GER VIX (viqmirriujp)", "MOH HOS", "(mo wadpem :D )"),
                     rows.flatMap { r -> r.groups.filter { it.kind == "words" }.map { it.text } })
    }

    @Test fun aLineOfHolesAndItsWordsAfterThemIsARow() {
        val row = laid("7018_music-of-the-day").rows().first { it.line == 47 }
        assertTrue(row.trusted)
        assertEquals(12, row.groups.count { it.holes.isNotEmpty() })
        assertEquals(listOf("Aaa mov chiirz ap lqi oeh rel-tez bu e-dka weejp"),
                     row.groups.filter { it.kind == "words" }.map { it.text })
    }

    @Test fun atunReadsItsRowsWithTheirSyllablesAgainstTheHoles() {
        val read = laid("28721_atun")
        assertEquals("brackets", read.convention)
        assertTrue(read.readable)
        assertTrue(read.rows().all { it.trusted })
        assertEquals(9, read.rows().size)
    }

    @Test fun whenTheShipComesInKeepsItsPartsNameInItsRow() {
        val first = laid("20960_when-the-ship-comes-in-solo").rows().first { it.line == 1 }
        assertTrue(first.trusted)
        assertEquals(listOf("unread" to "-", "words" to "Gozpq Pamj"),
                     first.groups.filter { it.holes.isEmpty() }.map { it.kind to it.text })
    }

    // --- the sampled tabs (test_viewer_harptab.py) -------------------------------------------------------------------

    private val sampled = listOf("10228_whammer-jammer", "124_heart-of-gold", "1278_house-of-the-rising-sun",
                                 "164_blowin-in-the-wind", "16_amazing-grace", "1786_simple-man", "1882_juke", "25_piano-man",
                                 "28841_isnt-she-lovely", "29910_knockin-on-heavens-door", "3489_wonderwall", "53_love-me-do",
                                 "588_hotel-california", "99_free-bird")

    @Test fun everySampledTabIsReadableWithItsRows() {
        assertEquals(emptyList(), sampled.filter { !tab(it).readable })
        assertEquals(mapOf("10228_whammer-jammer" to 48, "124_heart-of-gold" to 9, "1278_house-of-the-rising-sun" to 4,
                           "164_blowin-in-the-wind" to 11, "16_amazing-grace" to 4, "1786_simple-man" to 8, "1882_juke" to 23,
                           "25_piano-man" to 15, "28841_isnt-she-lovely" to 8, "29910_knockin-on-heavens-door" to 2,
                           "3489_wonderwall" to 33, "53_love-me-do" to 4, "588_hotel-california" to 19, "99_free-bird" to 22),
                     sampled.associateWith { tab(it).rows().size })
        val knockin = tab("29910_knockin-on-heavens-door")
        assertEquals(emptyList(), knockin.missed)
        assertEquals("brackets", knockin.convention)
        assertEquals(listOf("−3", "mua", "−3", "do", "−3", "be", "−3", "pi", "−3", "va", "3", "−3", "fa"),
                     knockin.rows()[0].groups.map { it.label() })
    }

    @Test fun nearlyEverySungHoleFindsItsOwnSyllable() {
        val placed = HashMap<String, Int>()
        for (stem in sampled) for (r in tab(stem).rows()) if (r.lyric != null) {
            for ((k, v) in r.placement) placed.merge(k, v, Int::plus)
        }
        assertEquals(mapOf("snap" to 805, "split" to 54, "held" to 27), placed)
    }

    @Test fun theHarpATabsWordsName() {
        assertEquals("A", tab("1882_juke").key)
        assertEquals("C", tab("28841_isnt-she-lovely").key)
        assertNull(tab("588_hotel-california").key)
        assertEquals("A", HarpTabs.namedKey(listOf("The band plays in E so I use an A harp")))
        assertEquals("Bb", HarpTabs.namedKey(listOf("harp in Bb")))
        assertEquals("C", HarpTabs.namedKey(listOf("ARMONICA EN C")))
        assertEquals("A", HarpTabs.namedKey(listOf("A harp is a fine thing")))
        assertNull(HarpTabs.namedKey(listOf("a harp in a minor key", "harmonica Diatonic")))
    }

    @Test fun hotelCaliforniaHolesOverTheirSyllablesAndItsChorus() {
        val read = tab("588_hotel-california")
        val rows = read.rows().filter { it.lyric != null }
        assertEquals(listOf(listOf("8") to "At ", listOf("8") to "e ", listOf("8") to "nirs ", listOf("−8") to "lom-",
                            listOf("−8") to "udb ", listOf("−8") to "pavf-"), holesOf(rows[0]).take(6))
        assertEquals(listOf("−8", "7", "−6") to "eiv--", holesOf(rows[1]).last())
        assertEquals(mapOf("snap" to 12, "held" to 2), rows[1].placement)
        assertEquals(listOf(null to false, "chorus" to true), read.sections.map { it.label to it.chorus })
        assertEquals(listOf("Prose", "Gap", "Row"), read.sections[1].items.takeLast(3).map { it::class.simpleName })
    }

    @Test fun wonderwallGivesItsNextVerseAsWordsAndItsAddressAsProse() {
        val read = tab("3489_wonderwall")
        assertEquals(listOf("Tanrs elm Dibop vu Faoz Tenrislam"), read.notes)
        val last = read.sections.last()
        assertEquals("Next verse", last.label)
        val words = last.items.filterIsInstance<Words>()
        assertEquals(1, words.size)
        assertEquals(17, words[0].lines.size)
        assertEquals(listOf("Norsul ma dbo pevf", "https://example.com/watch?v=0"),
                     last.items.filterIsInstance<Prose>().map { it.text })
        val row = read.rows().first { it.lyric?.startsWith("A vof'z") == true }
        assertEquals(listOf("8", "9", "8", "9", "9", "−10", "9", "−8", "7").map { listOf(it) }, holesOf(row).map { it.first })
    }

    @Test fun aTabWithNoRowIsShownAsWritten() {
        assertFalse(HarpTabs.parse("").readable)
        assertFalse(HarpTabs.parse("Just some words\nabout the song\n").readable)
    }

    @Test fun aChromaticsSlideOrItsPagesChipIsShownAsWritten() {
        assertTrue(HarpTabs.parse("4 -4< 5 6 -6\nla la la la la\n").chromatic)
        val chip = HarpTabs.parse("4 -4 5 6 -6\nla la la la la\n", "Chromatic")
        assertTrue(chip.chromatic)
        assertFalse(chip.readable)
        assertEquals("Chromatic", chip.harp)
    }

    @Test fun aTabWithWindowsLineEndsTabsAndNoBreakSpacesReadsAsOneWithout() {
        val plain = HarpTabs.parse("4  5  6\nla la la\n")
        for (body in listOf("4  5  6\r\nla la la\r\n", "4  5  6\nla la la\n")) {
            assertEquals(holesOf(plain.rows()[0]), holesOf(HarpTabs.parse(body).rows()[0]))
        }
        assertEquals(listOf(listOf("4") to "la      ", listOf("5") to "la"), holesOf(HarpTabs.parse("4\t5\nla\tla\n").rows()[0]))
    }

    // --- holes over syllables ----------------------------------------------------------------------------------------

    @Test fun syllablesStartAtEachWordAndAfterAHyphenOrACommaInsideOne() {
        assertEquals(listOf(0, 4, 8, 12, 15), HarpTabs.syllableStarts("des-ert hea-vy,and"))
        // a code point is a column: 🎵 is two UTF-16 units and one column
        assertEquals(listOf(0, 2, 4), HarpTabs.syllableStarts("🎵 a-b"))
    }

    @Test fun aHoleSnapsToTheSyllableItIsWrittenOver() {
        assertEquals(listOf(listOf("8") to "On ", listOf("−8") to "des-", listOf("−8") to "ert"), row("8  -8  -8", "On des-ert"))
    }

    @Test fun aHoleWrittenInsideAWordWithNoHyphenCutsItWhereASyllableBreaks() {
        assertEquals(listOf(listOf("4") to "to", listOf("5") to "mor", listOf("6") to "row"), row("4   5 6", "tomorrow"))
    }

    @Test fun holesAfterTheLastSyllableAreHeldOnIt() {
        assertEquals(listOf(listOf("−8", "7", "−6") to "air--"), row("-8 7 -6", "air--"))
    }

    @Test fun wordsBeforeTheFirstHoleComeFirstWithNone() {
        assertEquals(listOf(emptyList<String>() to "la la ", listOf("4") to "la"), row("      4", "la la la"))
    }

    @Test fun aWordWithManyHolesInsideNeverTakesLong() {
        val started = System.nanoTime()
        val parts = row(List(30) { "4" }.joinToString(" "), "a" + "bcdefghijklmnopqrstuvwxyz".repeat(3))
        assertTrue(System.nanoTime() - started < 2_000_000_000L)
        assertEquals(30, parts.sumOf { it.first.size })
    }

    @Test fun aRowShownAsWrittenHasNoPartsAndOnePlayedAloneOne() {
        val groups = HarpTabs.scan("4 5 6").groups
        assertEquals(emptyList(), HarpTabs.align(Row(groups, "la la la", trusted = false)).parts)
        assertEquals(listOf(groups to ""), HarpTabs.align(Row(groups, null)).parts)
        assertEquals(emptyMap(), HarpTabs.align(Row(groups, null)).placement)
    }

    @Test fun everyGroupOfARowIsPlacedOnceInItsOrder() {
        for (stem in sampled) for (r in tab(stem).rows()) {
            assertEquals(r.groups, r.parts.flatMap { it.first }, "$stem: ${r.lyric}")
            val lyric = r.lyric ?: continue
            val joined = r.parts.joinToString("") { it.second }
            val stripped = HarpTabText.rstrip(lyric)
            assertTrue(stripped.endsWith(joined) && stripped.dropLast(joined.length).isBlank(), "$stem: $lyric")
        }
    }

    @Test fun theCutsWeighNoMoreThanMaxCutsWays() {
        // 59 holes × 339 places is one more than MAX_CUTS: no cut at all; 59 × 338 is under it: one cut
        val over = "ba".repeat(170)
        assertEquals(List(59) { null }, HarpTabs.cuts(over, 0, 340, (1..59).toList(), listOf(0, 340)))
        val under = over.dropLast(1)
        assertEquals(1, HarpTabs.cuts(under, 0, 339, (1..59).toList(), listOf(0, 339)).count { it != null })
        // a word no piece of which keeps a vowel is never cut
        assertEquals(listOf<Int?>(null), HarpTabs.cuts("brr", 0, 3, listOf(1), listOf(0, 3)))
    }

    @Test fun thePageItemsAreWhatTheTabHolds() {
        val read = HarpTabs.parse("Notes before\n\n4 5\nla la\n\nVerse\n-4 -5\nlo lo\n\nsung the same\nto the tune\n\n" +
                                  "Play it twice to fade\n")
        assertEquals(listOf("Notes before"), read.notes)
        assertEquals(listOf(null, "Verse"), read.sections.map { it.label })
        assertEquals(listOf("Row", "Gap", "Words", "Gap", "Prose"), read.sections[1].items.map { it::class.simpleName })
        assertIs<Group>((read.sections[0].items[0] as Row).groups[0])
    }

    @Test fun aSectionsNameIsALabelAndItsTextHasNoBracketsOrColon() {
        assertTrue(HarpTabs.isLabel("[Bridge]"))
        assertTrue(HarpTabs.isLabel("End of the road"))
        assertFalse(HarpTabs.isLabel("End of the road", besideRow = true))
        assertFalse(HarpTabs.isLabel("la la--"))
        assertEquals("Bridge", HarpTabs.labelText("[Bridge]"))
        assertEquals("chorus", HarpTabs.labelText(" chorus- "))
        assertEquals(6, HarpTabs.syllables("Øl, øl og mere øl."))
    }
}
