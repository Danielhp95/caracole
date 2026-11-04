package io.github.danielhp95.caracole.viewer.sheet

import io.github.danielhp95.caracole.core.db.Database
import io.github.danielhp95.caracole.core.db.Db
import io.github.danielhp95.caracole.core.library.LibraryStore
import io.github.danielhp95.caracole.core.testing.TestDb
import io.github.danielhp95.caracole.viewer.testing.replays.SheetReplay
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import java.io.File
import java.nio.file.Files
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith
import kotlin.test.assertFalse
import kotlin.test.assertNull
import kotlin.test.assertTrue

/** viewer.sheet.MusicKeys gives keys.py's key and source: every record of vectors/viewer/musickeys.jsonl
 * (SheetReplay), and test_keys.py's own cases, by hand. */
class MusicKeysTest {
    @get:Rule val folder = TemporaryFolder()

    @Test fun everyRecordIsKeysPys() = SheetReplay.musicKeys()

    @Test fun aKeyIsReadTheWaysTabsWriteOne() {
        for ((text, key) in listOf("Am" to "A minor", "A min" to "A minor", "Amin" to "A minor", "F#m" to "F# minor",
                                   "E♭" to "Eb", "C♯m" to "C# minor", "C major" to "C", "  G " to "G", "Do" to "C",
                                   "do mayor" to "C", "La menor" to "A minor", "Lam" to "A minor", "Sib" to "Bb",
                                   "Fa#m" to "F# minor", "Re menor" to "D minor")) {
            assertEquals(key, MusicKeys.parseKey(text), text)
        }
        for (text in listOf("", "   ", "H", "Am7", "C/G", "Hello", "am", "A minor blues", "x2")) {
            assertNull(MusicKeys.parseKey(text), text)
        }
        assertEquals("C major", MusicKeys.keyName("C"))
        assertEquals("A minor", MusicKeys.keyName("A minor"))
        assertTrue(MusicKeys.sameKey("F# minor", "Gb minor"))
        assertFalse(MusicKeys.sameKey("A minor", "A"))
        assertEquals("A minor (from the tab)", SongKey("A minor", "tab").describe())
        assertEquals("C major (estimated from the chords)", SongKey("C", "chords").describe())
    }

    @Test fun aSheetStatesItsKeyBeforeItsChords() {
        assertEquals("A minor", MusicKeys.keyInText("{title: Song}\n{key: Am}\n[Verse]\n[ch]Am[/ch] [ch]F[/ch]\nWords"))
        assertEquals("G", MusicKeys.keyInText("Capo 2\nKey: G\n\n[Intro]\n[ch]G[/ch] [ch]C[/ch]\nWords here\n"))
        for ((line, key) in listOf("Tono: La menor" to "A minor", "TONO: Re" to "D", "Tono original: Do" to "C",
                                   "Key: [ch]F#m[/ch]" to "F# minor", "Key of Bb" to "Bb", "Key - Em (capo 3)" to "E minor",
                                   "Tuning: E A D G B E, Key: Em" to "E minor", "Tono: la menor" to "A minor",
                                   "Key: Sol" to "G")) {
            assertEquals(key, MusicKeys.keyInText("$line\n\n[ch]Am[/ch] [ch]G[/ch]\nWords\n"), line)
        }
        for (line in listOf("The key: I lost it", "Monkey: G", "Keys: Am", "Key: do not use a capo", "Key: la la la",
                            "Tonality: si señor")) {
            assertNull(MusicKeys.keyInText("$line\n[ch]G[/ch]\nWords\n"), line)
        }
        assertNull(MusicKeys.keyInText("[Verse]\n[ch]G[/ch]        [ch]C[/ch]\nKey: D is where it goes after\n"))
        assertNull(MusicKeys.keyInText("Intro: [ch]Am[/ch] [ch]G[/ch]\nKey: D\n[ch]D[/ch]\nWords\n"))
    }

    @Test fun theChordsAreReadAndTheirKeyEstimated() {
        assertEquals(listOf("Am", "Dm/F", "E"), MusicKeys.chordsInSheet("[ch]Am[/ch]    Dm/F    [ch]E[/ch]\nlyrics here"))
        assertEquals(listOf("Am", "F", "C", "G7", "N.C."),
                     MusicKeys.chordsInSheet("[Intro]\n[ch]Am[/ch]-[ch]F[/ch]\n[ch]Do[/ch]  [ch]Sol7[/ch]\nWords\n[ch]N.C.[/ch]"))
        for ((progression, key) in listOf("G D Em C G D Em C" to "G", "Am F C G Am F C G" to "A minor",
                                          "A7 A7 A7 A7 D7 D7 A7 A7 E7 D7 A7 E7" to "A", "F5 Bb5 Ab5 Db5 F5 Bb5 Ab5 Db5" to "F minor",
                                          "Am G#+ C/G D/F# Fmaj7 G Am" to "A minor", "Lam Fa Do Sol" to "A minor",
                                          "C#m A E B C#m A E B" to "C# minor", "Gb Db Ebm Cb Gb Db Ebm Cb" to "Gb",
                                          "C7M Am7 Dm7 G7 C7M" to "C")) {
            assertEquals(key, MusicKeys.estimateKey(progression.split(" ")), progression)
        }
        assertEquals("C", MusicKeys.estimateWeighted(listOf("Am" to 1.0, "C" to 20.0, "G" to 4.0, "F" to 4.0, "C" to 20.0)))
        assertEquals("A minor", MusicKeys.estimateWeighted(listOf("C" to 1.0, "Am" to 20.0, "G" to 4.0, "F" to 4.0, "Am" to 20.0)))
        for (chords in listOf(emptyList(), listOf("N.C.", "x2", "N"), listOf("C7", "F#7", "C7", "F#7"))) {
            assertNull(MusicKeys.estimateKey(chords), chords.toString())
        }
        for ((name, triad, notes) in listOf(Triple("Cmaj9", "major", setOf(0, 4, 7, 11)), Triple("CΔ", "major", setOf(0, 4, 7, 11)),
                                             Triple("Am(maj7)", "minor", setOf(9, 0, 4, 8)), Triple("A7sus2", "open", setOf(9, 11, 4, 7)),
                                             Triple("Cº7", null, setOf(0, 3, 6, 9)), Triple("Cadd9", "major", setOf(0, 4, 7)))) {
            val c = MusicKeys.chord(name)!!
            assertEquals(triad, c.triad, name)
            assertEquals(notes, c.tones.map { Math.floorMod(c.root + it.first, 12) }.toSet(), name)
        }
        assertEquals(0.0, MusicKeys.correlation(List(12) { 0.0 }, List(12) { it.toDouble() }))
    }

    /** test_keys.py's HOTEL: Hotel California as UG writes it, tonality "A", capo 2. */
    private val hotel = "[Intro]\n[ch]Am[/ch]  [ch]E7[/ch]  [ch]G[/ch]  [ch]D[/ch]  [ch]F[/ch]  [ch]C[/ch]  [ch]Dm[/ch]  [ch]E[/ch]\n" +
        ("[Verse]\n[ch]Am[/ch]  [ch]E7[/ch]\nWords go here\n[ch]G[/ch]  [ch]D[/ch]\nmore words\n" +
         "[ch]F[/ch]  [ch]C[/ch]\nand more\n[ch]Dm[/ch]  [ch]E7[/ch]\nand back\n").repeat(3)

    private fun raw(tonality: String?): JsonObject = buildJsonObject { if (tonality != null) put("tonality_name", tonality) }

    @Test fun aLetterAloneIsTheMinorKeyTheChordsSayItIs() {
        assertEquals(SongKey("A minor", "tab"), MusicKeys.sheetKey(raw("A"), hotel, 2))
        assertEquals(SongKey("B minor", "tab"), MusicKeys.sheetKey(raw("B"), hotel, 2)) // named by the sound
        assertEquals(SongKey("A", "tab"), MusicKeys.sheetKey(raw(null), "Key: A major\n\n$hotel", 2))
        assertEquals(SongKey("A minor", "tab"),
                     MusicKeys.sheetKey(raw("C"), "[ch]Am[/ch] [ch]F[/ch] [ch]C[/ch] [ch]G[/ch] [ch]Am[/ch]\nwords\n", 3))
        assertEquals(SongKey("A", "tab"), MusicKeys.sheetKey(raw("A"), null, 2)) // no chords to tell
        assertEquals(SongKey("A minor", "chords"), MusicKeys.sheetKey(raw("Standard"), "[ch]Am[/ch] [ch]F[/ch] [ch]C[/ch] [ch]G[/ch]\n"))
        assertNull(MusicKeys.sheetKey(raw(null), null))
    }

    @Test fun theCapoIsAWholeNumberAsFloatReadsOne() {
        fun capo(value: kotlinx.serialization.json.JsonElement) = MusicKeys.sheetCapo(JsonObject(mapOf("capo" to value)))
        assertEquals(2, capo(JsonPrimitive(2)))
        assertEquals(2, capo(JsonPrimitive("2.0")))
        assertEquals(3, capo(JsonPrimitive("３"))) // float() reads a full-width digit
        assertEquals(10, capo(JsonPrimitive("1_0")))
        assertNull(capo(JsonPrimitive(true)))
        assertNull(capo(JsonPrimitive(2.5)))
        assertNull(capo(JsonNull))
        assertNull(capo(JsonPrimitive("inf")))
        assertNull(MusicKeys.sheetCapo(JsonNull))
        assertFailsWith<ArithmeticException> { capo(JsonPrimitive(java.math.BigInteger.TEN.pow(400))) }
    }

    private fun library(block: (Db, File) -> Unit) {
        val dir = folder.newFolder()
        val lib = File(dir, "library")
        TestDb.fresh(dir).use { database: Database -> database.writeBlocking { db -> block(db, lib) } }
    }

    /** A song with a human sheet: its version (UG's raw), sheet.json beside it and sheet.txt, as the fetch keeps them. */
    private fun keepSheet(db: Db, lib: File, raw: String, doc: String): Long {
        val song = LibraryStore(lib).add(db, "A", "T", now = "2026-11-04T00:00:00Z").id
        db.execute("INSERT INTO versions (provider, tab_id, song_id, slot, kind, rating, votes, version, url, raw, fetched_at) " +
                   "VALUES ('ug', '1', ?, 'sheet', 'chords', 4.5, 10, 1, 'https://example.invalid/1', ?, '2026-11-04T00:00:00Z')", song, raw)
        val version = db.lastRowid()
        File(lib, "A/T").mkdirs()
        File(lib, "A/T/sheet.json").writeText(doc)
        File(lib, "A/T/sheet.txt").writeText("Am F C G\n")
        for (name in listOf("sheet.json", "sheet.txt")) {
            db.execute("INSERT INTO files (version_id, song_id, name, path, sha256, kept_rank, created_at) " +
                       "VALUES (?, ?, ?, ?, '0', 1, '2026-11-04T00:00:00Z')", version, song, name, "A/T/$name")
        }
        return song
    }

    @Test fun aLinkInPlaceOfSheetJsonIsNeverRead() = library { db, lib ->
        val song = keepSheet(db, lib, "{}", "{\"content\": \"[ch]Am[/ch] [ch]F[/ch] [ch]C[/ch] [ch]G[/ch]\\n\"}")
        assertEquals(SongKey("A minor", "chords"), MusicKeys.songKey(db, lib, song))
        val elsewhere = folder.newFile("private.json")
        elsewhere.writeText("{\"content\": \"Key: G\\n\\n[ch]G[/ch]\\n\"}")
        val sheetJson = File(lib, "A/T/sheet.json")
        sheetJson.delete()
        Files.createSymbolicLink(sheetJson.toPath(), elsewhere.toPath())
        assertNull(MusicKeys.songKey(db, lib, song))
    }

    @Test fun aSheetJsonNestedTooDeepOrNotJsonIsNoMarkupButUgsKeyStillCounts() = library { db, lib ->
        val song = keepSheet(db, lib, "{\"tonality_name\": \"F\"}", "[".repeat(100_000) + "]".repeat(100_000))
        assertEquals(SongKey("F", "tab"), MusicKeys.songKey(db, lib, song))
        File(lib, "A/T/sheet.json").writeText("{not json")
        assertEquals(SongKey("F", "tab"), MusicKeys.songKey(db, lib, song))
        File(lib, "A/T/sheet.json").writeBytes(byteArrayOf(0xEF.toByte(), 0xBB.toByte(), 0xBF.toByte()) + "{}".toByteArray())
        assertEquals(SongKey("F", "tab"), MusicKeys.songKey(db, lib, song)) // a BOM is json.loads' error
        assertEquals("F", MusicKeys.letterAlone(db, lib, song))
    }

    @Test fun theDataIsOneNothingCanChange() {
        assertFailsWith<UnsupportedOperationException> { (MusicKeys.SOURCES as MutableMap<String, String>)["x"] = "y" }
        assertFailsWith<UnsupportedOperationException> { (Sheets.COMMENTS as MutableSet<String>).add("x") }
        assertFailsWith<UnsupportedOperationException> { (SheetView.SOURCES as MutableMap<String, String>).clear() }
    }
}
