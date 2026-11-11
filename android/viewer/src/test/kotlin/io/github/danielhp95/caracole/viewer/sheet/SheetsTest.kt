package io.github.danielhp95.caracole.viewer.sheet

import io.github.danielhp95.caracole.core.testing.Corpus
import io.github.danielhp95.caracole.core.testing.ForbiddenApis
import io.github.danielhp95.caracole.viewer.testing.replays.SheetReplay
import org.junit.Test
import java.io.File
import kotlin.test.assertEquals
import kotlin.test.assertNull
import kotlin.test.assertTrue

/** viewer.sheet reads a sheet as viewer/sheet.py and page.py's reading functions do: every record of
 * vectors/viewer/sheet.jsonl (SheetReplay), and test_viewer_sheet.py's own cases, by hand. */
class SheetsTest {
    @Test fun everyRecordIsSheetPysAndPagePys() = SheetReplay.sheets()

    @Test fun viewerSheetNeverAsksTheJdkAboutText() {
        // as :core and :server never do (core.testing.ForbiddenApis); Gradle runs the tests in :viewer's folder
        val found = ForbiddenApis.check(File("src/main/kotlin/io/github/danielhp95/caracole/viewer/sheet"))
        assertEquals(emptyList(), found)
    }

    private fun fixture(name: String): String = String(Corpus.fixture("chordpro/$name"), Charsets.UTF_8)

    private val ug by lazy { Sheets.parse(fixture("ug_sheet.cho")) }

    @Test fun theHeaderGivesTitleArtistKeyAndCapo() {
        assertEquals(listOf("Synthetic Test Song", "The Placeholders", "G", 2, false),
                     listOf(ug.title, ug.artist, ug.key, ug.capo, ug.auto))
    }

    @Test fun eachCommentOpensASectionNamedAfterIt() {
        assertEquals(listOf("Intro", "Verse 1", "Chorus", "Riff", "Outro"), ug.sections.map { it.label })
        assertEquals(listOf(false, false, true, false, false), ug.sections.map { it.chorus })
        assertEquals(listOf("G", "D", "Em", "C", "G/B", "Am", "F"), ug.chords)
    }

    private fun c(i: Int) = Item.Chord(i)

    @Test fun aLyricLineIsSplitAtItsChordsAndALineOfChordsAloneIsARow() {
        assertEquals(listOf(Lyrics(listOf(c(0) to "Tiny test ", c(1) to "words go here")),
                            Lyrics(listOf(null to "Made ", c(2) to "up only for a ", c(3) to "parser"))),
                     ug.sections[1].lines)
        assertEquals(listOf(ChordRow(listOf(c(0), c(1), c(2), c(3), Item.Mark("x2")))), ug.sections[0].lines)
        assertEquals(listOf(Tab(listOf("e|-----0---0---|", "B|---1---1---1-|", "G|-2-----------|"))), ug.sections[3].lines)
        assertEquals(listOf(Lyrics(listOf(c(0) to "la la ", Item.Mark("x2") to " ", c(1) to "lo"))),
                     Sheets.parse("{title: T}\n[G]la la [*x2] [D]lo\n").sections[0].lines)
    }

    @Test fun blankLinesSeparateStanzasButNeverStartOrEndASection() {
        val s = Sheets.parse("{title: T}\n{artist: A}\n{comment: Verse}\n\n[G]one\n\n[D]two\n\n{comment: Chorus}\nthree\n")
        assertEquals(listOf(Lyrics(listOf(c(0) to "one")), Blank, Lyrics(listOf(c(1) to "two"))), s.sections[0].lines)
        assertEquals(listOf<Line>(Text("three")), s.sections[1].lines)
        val unnamed = Sheets.parse("{title: T}\n{artist: A}\nIntro words\n[G]Sing\n")
        assertEquals(listOf(Section(null, false, listOf(Text("Intro words"), Lyrics(listOf(c(0) to "Sing"))))),
                     unnamed.sections)
    }

    @Test fun chorusSectionsAreToldByTheirNameInSeveralLanguages() {
        for (label in listOf("Chorus", "Pre-Chorus 2", "Coro", "Estribillo", "Refrain", "副歌", "REFRÁN")) {
            assertTrue(Sheets.parse("{title: T}\n{comment: $label}\nla\n").sections[0].chorus, label)
        }
        val s = Sheets.parse("{title: T}\n{start_of_chorus}\nla\n{end_of_chorus}\nlo\n")
        assertEquals(listOf(true to listOf<Line>(Text("la")), false to listOf<Line>(Text("lo"))),
                     s.sections.map { it.chorus to it.lines })
    }

    @Test fun commentLinesUnknownDirectivesAndTheAutoMarkerAreNoLines() {
        assertEquals(listOf<Line>(Lyrics(listOf(c(0) to "la"))),
                     Sheets.parse("{title: T}\n# a note\n{tempo: 90}\n{new_page}\n[C]la\n").sections[0].lines)
        val auto = Sheets.parse(ChordPro.toChordPro("[ch]Am[/ch]\nla la", "T", "A", auto = true))
        assertTrue(auto.auto)
        assertEquals(listOf<String?>(null), auto.sections.map { it.label })
    }

    @Test fun escapesChordProNeededAreUndone() {
        val s = Sheets.parse(ChordPro.toChordPro("Ends with \\\nWorth 100%{title}", "Back\\slash", "A"))
        assertEquals("Back\\slash", s.title)
        assertEquals(listOf<Line>(Text("Ends with \\"), Text("Worth 100%(title)")), s.sections[0].lines)
    }

    @Test fun aCapoThatIsNoNumberIsNone() {
        assertNull(Sheets.parse("{title: T}\n{capo: two}\n").capo)
        assertNull(Sheets.parse("{title: T}\n{capo: ²}\n").capo) // a digit to str.isdigit, not to int
        assertNull(Sheets.parse("{title: T}\n{capo: ٣}\n").capo) // nor an Arabic-Indic three
        assertNull(Sheets.parse("{title: T}\n{capo: 0}\n").capo)
        assertNull(Sheets.parse("{title: T}\n{capo: 99999999999}\n").capo) // past an Int: none
        assertEquals(3, Sheets.parse("{title: T}\n{capo: 003}\n").capo)
    }

    @Test fun theChordsASheetDefinesAreKeptAsWritten() {
        val s = Sheets.parse("{title: T}\n{define: Cadd9 base-fret 1 frets x 3 2 0 3 3 fingers 0 2 1 0 3 4}\n" +
                             "{chord: G frets 3 2 0 0 3 3}\n{define: }\n[Cadd9]la\n")
        assertEquals(listOf("Cadd9 base-fret 1 frets x 3 2 0 3 3 fingers 0 2 1 0 3 4", "G frets 3 2 0 0 3 3"), s.defines)
        assertEquals(listOf(listOf<Line>(Lyrics(listOf(c(0) to "la")))), s.sections.map { it.lines })
    }

    @Test fun linesArePythonsAndTheirWhitespaceToo() {
        // str.splitlines: \x0b, \x1c and U+2028 end a line; a no-break space is whitespace, a zero-width one is not
        val s = Sheets.parse("{title: T}\n[G]one\u000b[D]two\u2028three\u00a0\n\u200b\n")
        assertEquals(listOf(Lyrics(listOf(c(0) to "one")), Lyrics(listOf(c(1) to "two")), Text("three"), Text("\u200b")),
                     s.sections[0].lines)
        assertEquals("Verse", Sheets.parse("{ COMMENT :\u3000Verse\u3000}\nla\n").sections[0].label)
        assertEquals("comment" to "Verse 1", Sheets.directive("{comment: Verse 1}"))
        assertNull(Sheets.directive("[Am]la"))
    }

    @Test fun aSectionsLabelIsWrittenAsTheSheetWritesIt() {
        // {comment: } with nothing after it opens a section labelled "", which is kept only for its lines
        val s = Sheets.parse("{title: T}\n{comment: Verse}\n[G]la\n{comment: }\nlo\n{comment: }\n")
        assertEquals(listOf("Verse", ""), s.sections.map { it.label })
    }

    @Test fun whatThePageShowsOfASheetWithNoPreamble() {
        val (pre, sections) = SheetView.shown(ug)
        assertNull(pre)
        assertTrue(sections.zip(ug.sections).all { (a, b) -> a === b })
        assertEquals(listOf(0, 1, 2, 3, 0, 1, 2, 3, 3, 4, 5, 6, 3, 0, 1, 3), SheetView.played(ug).take(16))
        assertEquals(SheetView.places(ug).map { it.first }, SheetView.played(ug))
        assertEquals(listOf("", "Tiny test words go here", "Made up only for a parser"), SheetView.drawnLines(ug).take(3))
        assertEquals(listOf("Intro", "", "Verse 1", "Tiny test words go here"), SheetView.writtenTexts(ug).take(4))
    }

    @Test fun aKeyNamedComesFromItsSourceInWords() {
        assertEquals("from the song's entry", SheetView.origin(null))
        assertEquals("from the tab", SheetView.origin("tab"))
        assertEquals("guessed from the chords", SheetView.origin("  Chords "))
        assertEquals("from MusicBrainz Lookup", SheetView.origin("MusicBrainz \t Lookup"))
        assertEquals("from " + "x".repeat(40), SheetView.origin("x".repeat(50)))
        val sheet = Sheets.parse("{title: T}\n{key: A}\n{capo: 2}\n[Am]la [E7]la [G]la [D]la [F]la [C]la [Dm]la [E]la\n")
        assertEquals("from the sheet", SheetView.songKey(sheet, SheetView.chords(sheet), null, null).second)
        // Hotel California's "A" over its chords with capo 2 is A minor
        assertEquals(io.github.danielhp95.caracole.viewer.theory.Key(9, "aeolian"),
                     SheetView.viewerKey("{key: A}\n{capo: 2}\n[Am]la [E7]la [G]la [D]la [F]la [C]la [Dm]la [E]la [Am]"))
    }

    @Test fun aPreambleOfNotesIsWhatAPageFoldsAway() {
        val lines = listOf("{title: x}", "", "note one", "note two", "", "{comment: Verse}", "[Em]hi", "{comment: Chorus}", "[G]x")
        val pre = Sheets.splitPreamble(lines)
        assertEquals(listOf("note one", "note two"), pre.notes)
        assertEquals(5, pre.end)
        val none = Sheets.splitPreamble(listOf("[Em]Words to [G]sing", "[Am]and more", "", "[C]still more"))
        assertEquals(Preamble(emptyList(), emptyList(), emptyList(), null, null, 0), none)
        assertEquals("half step down",
                     Sheets.splitPreamble(listOf("Tuning: Eb Ab Db Gb Bb Eb (half step down)", "", "{comment: Verse}",
                                                 "[Em]words", "{comment: Chorus}", "[G]more")).tuning)
        for ((note, tuning) in listOf("Tuning: DADGAD" to "DADGAD", "Tuning = Open G" to "Open G",
                                      "(Tuning: DADGAD)" to "DADGAD", "Please drop a comment and rate!" to null,
                                      "Tuning: Standard (EADGBE)" to null, "Capo 2, drop d" to "drop d")) {
            assertEquals(tuning, Sheets.tuning(note), note)
        }
    }

    @Test fun whatAFoldedPreambleShows() {
        val s = Sheets.parse(fixture("legend_sheet.cho"))
        val (pre, sections) = SheetView.shown(s)
        assertTrue(pre != null && pre.lines.isNotEmpty())
        assertEquals("Intro", sections[0].label)
        assertEquals(2, SheetView.peek(pre!!, s.chords).size)
        assertTrue(SheetView.places(s).any { it.second == -1 })
        assertEquals(6, SheetView.givenShapes(s).size)
        assertEquals(6, SheetView.shapesOf(s).size)
    }
}
