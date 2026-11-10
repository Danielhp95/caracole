package io.github.danielhp95.caracole.viewer.version

import io.github.danielhp95.caracole.core.library.Overrides
import io.github.danielhp95.caracole.core.testing.Misses
import io.github.danielhp95.caracole.core.testing.replays.LibraryWritesReplay
import io.github.danielhp95.caracole.viewer.sheet.SheetView
import io.github.danielhp95.caracole.viewer.sheet.Sheets
import io.github.danielhp95.caracole.viewer.shapes.Instruments
import io.github.danielhp95.caracole.viewer.shapes.Voicings
import io.github.danielhp95.caracole.viewer.testing.replays.VersionReplay
import io.github.danielhp95.caracole.viewer.theory.Key
import io.github.danielhp95.caracole.viewer.theory.Theory
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonPrimitive
import org.junit.Test
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith
import kotlin.test.assertNotEquals
import kotlin.test.assertNull
import kotlin.test.assertTrue

/** viewer.version answers as viewer/version.py and render.own_version do: every record of
 * vectors/viewer/version.jsonl (VersionReplay), and tests/test_viewer_version.py's cases, by hand. */
class VersionsTest {
    @Test fun everyRecordIsVersionPys() {
        val misses = Misses("version")
        VersionReplay.versions(misses)
        misses.assertNone()
        assertTrue(misses.checked > 300, "only ${misses.checked} answers checked")
    }

    private val g = Key(7, "ionian")
    private val eMinor = Key(4, "aeolian")

    private fun q(text: String): Version = Versions.fromQuery(text)

    // --- the address ---------------------------------------------------------------------------------------------

    @Test fun theQueryRoundTrips() {
        val v = Version(t = -3, mode = "dorian", capo = 0, at = linkedMapOf(3 to 2, 0 to 1),
                        alt = linkedMapOf("dorian" to linkedMapOf(3 to Swap(1, "7#9", null), 0 to Swap(4, "m7", 11)),
                                          "lydian" to linkedMapOf(2 to Swap(0, "6/9.x", 4))))
        val query = "t=-3&mode=dorian&capo=0&alt=dorian.0.4.m7.11%2Cdorian.3.1.7%25239.%2Clydian.2.0.6%252F9%252Ex.4" +
            "&at=0.1%2C3.2"
        assertEquals(query, Versions.query(v))
        assertEquals(v, q(query))
        assertEquals(v, q("#$query"))
        assertEquals("", Versions.query(Version()))
        assertEquals(Version(), q(""))
        assertEquals(Version(t = 2), q("fs=20&t=2&speed=8&chord=3&panel=1"))
        assertEquals(Version(t = 11), q("t=40"))
        assertEquals(Version(t = -3), q("t=-2.6"))
        assertEquals(Version(), q("t=up&mode=funky&capo=-1"))
        assertEquals(Version(), q("capo="))
        assertEquals(Version(capo = 3), q("capo=2.5"))
        assertEquals(Version(at = mapOf(4 to 2)), q("at=1.0,2.x,03.1,4.2,4"))
        assertEquals(Version(alt = mapOf("dorian" to mapOf(1 to Swap(2, "m", null)))),
                     q("alt=dorian.1.2.m.,funky.1.2.m.,dorian.x.2.m.,dorian.2.2.m.y,dorian.3.2.%25zz.,dorian.4.2.%25E0%25A4."))
        assertEquals(Version(alt = mapOf("dorian" to mapOf(1 to Swap(2, "", null)))), q("alt=dorian.1.2"))
        assertEquals(q(query).hashCode(), v.hashCode())
        assertEquals(Version(mode = "dorian", capo = 0, at = v.at, alt = v.alt), v.copy(t = 0))
    }

    @Test fun anIndexOrANumberPastAnIntIsDroppedAsOneTheViewerCantRead() {
        assertEquals(Version(at = mapOf(1 to 2)), q("at=99999999999.1,1.2,2.99999999999"))
        assertEquals(Version(), q("alt=dorian.99999999999.2.m.,dorian.1.99999999999.m.,dorian.1.2.m.99999999999"))
    }

    @Test fun aVersionNamesItsInstrumentAsTheViewerDoes() {
        val v = Version(t = 2, capo = 0, at = mapOf(1 to 1), inst = "ukulele")
        assertEquals("t=2&capo=0&at=1.1&inst=ukulele", Versions.query(v))
        assertEquals(v, q(Versions.query(v)))
        assertEquals(Version(inst = "piano"), q("inst=piano"))
        assertEquals(setOf("harmonica", "flute", "recorder"), listOf("harmonica", "flute", "recorder").map { q("inst=$it").inst }.toSet())
        assertEquals(Version(), q("inst=guitar"))
        assertEquals(Version(), q("inst=banjo"))
        assertNotEquals(Version(inst = "piano"), Version())
        assertEquals("guitar", Versions.instrumentIds()[0])
        assertTrue("piano" in Versions.instrumentIds())
    }

    // --- its name ------------------------------------------------------------------------------------------------

    @Test fun aVersionIsNamedByTheKeyOfItsShapesAndItsCapo() {
        assertEquals("G Dorian, capo 0", Versions.label(Version(mode = "dorian", capo = 0), g, 0))
        assertEquals("G Major, capo 2", Versions.label(Version(), g, 2))
        assertEquals("A Major, capo 3", Versions.label(Version(t = 3, capo = 3), g, 2))
        assertEquals("F Minor, capo 2", Versions.label(Version(t = 1), eMinor, 2))
        assertEquals("C Major, capo 0", Versions.label(Version(t = -1, mode = "ionian"), Key(1, "ionian"), null))
        assertEquals("D Lydian, capo 0", Versions.label(Version(t = 2, mode = "lydian"), Key(0, "ionian"), null))
        assertEquals("As written, capo 3", Versions.label(Version(), null, 3))
        assertEquals("Transposed +2, capo 0", Versions.label(Version(t = 2, capo = 0), null, 3))
        assertEquals("Transposed -4, capo 0", Versions.label(Version(t = -4), null, null))
    }

    @Test fun whereASongbookPlaysAVersionSaysNothingOfACapoItPlaysWithout() {
        assertEquals("G Dorian", Versions.playedLabel(Version(mode = "dorian", capo = 0), g, 0))
        assertEquals("F# Minor", Versions.playedLabel(Version(capo = 0), eMinor, 2))
        assertEquals("Transposed +2", Versions.playedLabel(Version(t = 2, capo = 0), null, 3))
        assertEquals("As written", Versions.playedLabel(Version(), null, null))
        assertEquals("G Major, capo 2", Versions.playedLabel(Version(), g, 2))
        assertEquals("Transposed -4, capo 1", Versions.playedLabel(Version(t = -4, capo = 1), null, null))
    }

    @Test fun anInstrumentWithNoCapoIsNamedByTheKeyItSoundsIn() {
        assertEquals("A Major, piano", Versions.label(Version(inst = "piano"), g, 2))
        assertEquals("F Major, capo 4", Versions.label(Version(capo = 4), g, 2))
        assertEquals("A Major, harmonica", Versions.label(Version(capo = 4, inst = "harmonica"), g, 2))
        assertEquals("G Major, capo 2, ukulele", Versions.label(Version(inst = "ukulele"), g, 2))
        assertEquals("G Major, capo 2, low-G ukulele", Versions.label(Version(inst = "ukulele-low-g"), g, 2))
        assertEquals("A Major, baritone ukulele", Versions.playedLabel(Version(capo = 0, inst = "baritone"), g, 2))
        assertEquals("A Major, flute", Versions.playedLabel(Version(inst = "flute"), g, 2))
        assertEquals("Transposed +3, piano", Versions.label(Version(inst = "piano"), null, 3))
        assertEquals("As written, recorder", Versions.label(Version(t = -3, capo = 0, inst = "recorder"), null, 3))
        assertEquals(Key(9, "ionian") to 0, Versions.playedKey(Version(inst = "piano"), g, 2))
        assertEquals(g to 2, Versions.playedKey(Version(inst = "ukulele"), g, 2))
    }

    // --- a songbook's setting -------------------------------------------------------------------------------------

    @Test fun aSettingPlaysTheSongOnItsInstrument() {
        val shapes = SheetView.viewerKey(UG)
        assertEquals(g, shapes)
        val own = Version(t = 1, at = mapOf(0 to 1))
        assertEquals(Version(t = 1, inst = "ukulele"), Versions.inSetting(own, Setting(instrument = "ukulele"), shapes, 2))
        val piano = Versions.inSetting(own, Setting(key = "C", instrument = "piano"), shapes, 2)
        assertEquals(0, piano.capo)
        assertEquals(Key(0, "ionian") to 0, Versions.playedKey(piano, shapes, 2))
        assertEquals(Version(), Versions.inSetting(Version(inst = "piano"), Setting(instrument = "guitar"), shapes, 2))
        assertEquals("piano", Versions.inSetting(Version(inst = "piano"), Setting(key = "G"), shapes, 2).inst)
        assertEquals(Version(inst = "piano"), Versions.inSetting(Version(inst = "piano"), Setting(key = "G"), null, null))
        assertTrue(Versions.settingProblem(instrument = "banjo")!!.startsWith("instrument must be one of guitar, ukulele"))
        assertNull(Versions.settingProblem(instrument = "harmonica"))
        assertEquals(own, Versions.inSetting(own, Setting(), shapes, 2))
        assertEquals(own, Versions.inSetting(own, null, shapes, 2))
    }

    @Test fun aSettingsPartsAreCheckedAsPythonHoldsThem() {
        assertNull(Versions.settingProblem("G", "dorian", 0, "guitar"))
        assertEquals("key must be a tonic such as \"G\", \"F#\" or \"Bb\", got 'g'", Versions.settingProblem(key = "g"))
        assertEquals("key must be a tonic such as \"G\", \"F#\" or \"Bb\", got 1", Versions.settingProblem(key = 1))
        assertEquals("capo must be a fret from 0 to 11, got True", Versions.settingProblem(capo = true))
        assertEquals("capo must be a fret from 0 to 11, got 2.0", Versions.settingProblem(capo = 2.0))
        assertEquals("capo must be a fret from 0 to 11, got 12", Versions.settingProblem(capo = 12L))
        assertEquals("capo must be a fret from 0 to 11, got '2'", Versions.settingProblem(capo = JsonPrimitive("2")))
        assertNull(Versions.settingProblem(capo = JsonPrimitive(11)))
        assertEquals("mode must be one of ionian, dorian, phrygian, lydian, mixolydian, aeolian, locrian, got ['dorian']",
                     Versions.settingProblem(mode = JsonArray(listOf(JsonPrimitive("dorian")))))
    }

    // --- a version kept by its key --------------------------------------------------------------------------------

    private fun keptOn(entry: String, cho: String): Version =
        Versions.inKey(Versions.keyVersion(entry)!!, cho, SheetView.viewerKey(cho), Sheets.parse(cho).capo)

    private fun entryOf(v: Version, cho: String): String? =
        Versions.entry(v, cho, SheetView.viewerKey(cho), Sheets.parse(cho).capo)

    @Test fun myVersionIsKeptAsTheKeyItPlaysInItsModeAndItsCapo() {
        assertEquals("key=Gm&mode=dorian&capo=0", entryOf(Version(t = -2, mode = "dorian"), IN_A_MINOR))
        assertEquals(KeyVersion(Key(7, "aeolian"), "dorian", 0), Versions.keyVersion("key=Gm&mode=dorian&capo=0"))
        assertEquals(Version(t = -2, mode = "dorian", capo = 0), keptOn("key=Gm&mode=dorian&capo=0", IN_A_MINOR))
        val moved = keptOn("key=Gm&mode=dorian&capo=0", IN_D_MINOR_CAPO_3)
        assertEquals(Version(t = 2, mode = "dorian", capo = 0), moved)
        assertEquals("G Dorian, capo 0", Versions.label(moved, SheetView.viewerKey(IN_D_MINOR_CAPO_3), 3))
        assertEquals("key=Gm&capo=0", entryOf(Version(t = -2), IN_A_MINOR))
        assertEquals("key=Gm&capo=0", entryOf(Version(t = -2, mode = "aeolian"), IN_A_MINOR))
        assertEquals(Version(t = -2, capo = 0), keptOn("key=Gm&capo=0", IN_A_MINOR))
        assertEquals("key=Em&capo=2", entryOf(Version(t = 1, capo = 2), IN_D_MINOR_CAPO_3))
        assertEquals("key=Dm&capo=3", entryOf(Version(), IN_D_MINOR_CAPO_3))
        assertEquals("key=D&capo=0", entryOf(Version(t = 2), IN_C_MAJOR))
        assertEquals("key=C&mode=aeolian&capo=0", entryOf(Version(mode = "aeolian"), IN_C_MAJOR))
    }

    @Test fun aSheetTaggedInTheParallelKeyPlaysMyVersionsChords() {
        val taggedA = IN_A_MINOR.replace("{key: Am}", "{key: A}")
        assertEquals(Key(9, "aeolian"), SheetView.viewerKey(taggedA))
        val heard = SheetView.viewerKey(taggedA, "A", "audio")
        assertEquals(Key(9, "ionian"), heard)
        for (key in listOf(SheetView.viewerKey(taggedA), heard)) {
            fun on(entry: String) = Versions.inKey(Versions.keyVersion(entry)!!, taggedA, key, null)
            assertEquals(Version(t = 2, capo = 0), on("key=Bm&capo=0"), "$key")
            assertEquals(Version(t = -2, mode = "dorian", capo = 0), on("key=Gm&mode=dorian&capo=0"), "$key")
        }
    }

    @Test fun myVersionsSwapsAndShapesAreKeptForTheChordsTheyWereChosenFor() {
        val fmaj7 = Theory.alternatives(Theory.parseChord("G")!!, Key(9, "dorian")).first { it.suffix == "maj7" }
        val mine = Version(t = -2, mode = "dorian", at = mapOf(0 to 2),
                           alt = mapOf("dorian" to mapOf(3 to Swap(fmaj7.root, fmaj7.suffix, fmaj7.bass)),
                                       "lydian" to mapOf(1 to Swap(5, "maj7", null))))
        val entry = entryOf(mine, IN_A_MINOR)!!
        assertEquals("key=Gm&mode=dorian&capo=0&alt=F.Fmaj7&at=Gm.x-x-5-7-8-6", entry)
        assertEquals(mine.copy(capo = 0, alt = mapOf("dorian" to mine.alt.getValue("dorian"))), keptOn(entry, IN_A_MINOR))
        assertEquals(mapOf(0 to 2), keptOn(entry, IN_D_MINOR_CAPO_3).at)
        val other = "{title: T}\n{artist: A}\n{key: Am}\n[Am]la [Dm]lo [E7]li\n"
        assertEquals(emptyMap(), keptOn(entry, other).alt)
        assertEquals(mapOf(0 to 2), keptOn(entry, other).at)
        assertEquals(mapOf(2 to 2), keptOn("key=Gm&mode=dorian&capo=0&at=Gm.1-1-1-1-1-1,Bb.6-8-8-7-6-6", IN_A_MINOR).at)
    }

    @Test fun aSheetWithNoKeyPlaysMyVersionAsWritten() {
        assertEquals(Version(), keptOn("key=Gm&mode=dorian&capo=0", NO_KEY))
        assertNull(entryOf(Version(t = 2, capo = 1), NO_KEY))
        assertNull(entryOf(Version(), NO_KEY))
    }

    @Test fun anEntryWithoutAKeyIsAMoveAndOneThatCantBeReadSaysWhy() {
        assertNull(Versions.keyVersion("t=2&mode=dorian&capo=0"))
        assertNull(Versions.keyVersion(""))
        assertEquals(KeyVersion(Key(6, "aeolian"), "dorian", 2), Versions.keyVersion("#key=F#m&mode=dorian&capo=2"))
        assertEquals(KeyVersion(Key(10, "ionian")), Versions.keyVersion("key=Bb"))
        assertEquals(KeyVersion(Key(9, "dorian"), null, 0), Versions.keyVersion("key=A dorian&capo=0"))
        for ((bad, why) in listOf("key=H" to "key must be a key", "key=g" to "key must be a key", "key=" to "key must be a key",
                                  "key=Gmin" to "key must be a key", "key=G dorien" to "key must be a key",
                                  "key=G&mode=dorien" to "mode must be one of", "key=G&capo=12" to "capo must be a fret",
                                  "key=G&capo=two" to "capo must be a fret", "key=G&t=2" to "not both")) {
            val e = assertFailsWith<IllegalArgumentException>(bad) { Versions.keyVersion(bad) }
            assertTrue(why in e.message!!, "$bad: ${e.message}")
        }
        val kept = Versions.keyVersion("key=G&alt=F.Fmaj7,F,Hm.Gm,F.x,a.b.c" +
                                       "&at=Gm.x-x-5-7-8-6,3.1,Hm.x-0-2-2-1-0,Gm.2,Gm.x-x-x-x-x-x,Gm.1-2-3,Bb")!!
        assertEquals(listOf("F" to "Fmaj7"), kept.alt)
        assertEquals(listOf("Gm" to listOf(null, null, 5, 7, 8, 6)), kept.at)
    }

    @Test fun anEntryRoundTripsWithAnyChordsName() {
        val kept = KeyVersion(Key(6, "aeolian"), "dorian", 0, alt = listOf("C#7" to "C#7(b9)"),
                              at = listOf("F#m" to listOf(null, 4, 4, 6, 7, 5), "C6.9" to listOf(null, 3, 2, 2, 3, 3),
                                          "A,B" to listOf(5, 7, 7, 6, 5, 5), "D&=%" to listOf(null, null, 0, 2, 3, 2)))
        val query = kept.query()
        assertEquals("key=F#m&mode=dorian&capo=0&alt=C#7.C#7(b9)&at=F#m.x-4-4-6-7-5,C6%2E9.x-3-2-2-3-3," +
                     "A%2CB.5-7-7-6-5-5,D%26%3D%25.x-x-0-2-3-2", query)
        assertEquals(kept, Versions.keyVersion(query))
        assertEquals("key=Bb dorian", KeyVersion(Key(10, "dorian")).query())
    }

    @Test fun myVersionKeepsItsInstrumentAndTheCapoTheGuitarPlaysAt() {
        assertEquals("key=Gm&capo=0&inst=piano", entryOf(Version(t = -2, inst = "piano"), IN_A_MINOR))
        assertEquals("key=Dm&capo=3&inst=piano", entryOf(Version(inst = "piano"), IN_D_MINOR_CAPO_3))
        assertEquals(Version(capo = 3, inst = "piano"), keptOn("key=Dm&capo=3&inst=piano", IN_D_MINOR_CAPO_3))
        assertEquals("D Minor, piano", Versions.keyVersion("key=Dm&capo=3&inst=piano")!!.label())
        assertEquals("D Minor, capo 3, ukulele", Versions.keyVersion("key=Dm&capo=3&inst=ukulele")!!.label())
        val am = Sheets.parse(IN_A_MINOR).chords.indexOf("Am")
        val second = Instruments.chordShapes(Instruments.UKULELE, Theory.parseChord("Gm")!!, 0)[1] as JsonArray
        val entry = entryOf(Version(t = -2, at = mapOf(am to 1), inst = "ukulele"), IN_A_MINOR)
        assertEquals("key=Gm&capo=0&at=Gm.${Voicings.fretsFromNut(second).joinToString("-")}&inst=ukulele", entry)
        assertEquals(Version(t = 2, capo = 0, at = mapOf(0 to 1), inst = "ukulele"), keptOn(entry!!, IN_D_MINOR_CAPO_3))
        assertEquals(Version(inst = "ukulele"), keptOn(entry, NO_KEY))
        assertEquals(emptyList(), Versions.keyVersion("key=G&at=G.3-2-0-0-0-3&inst=ukulele")!!.at)
        assertEquals(emptyList(), Versions.keyVersion("key=G&at=G.0-2-3-2&inst=piano")!!.at)
        assertFailsWith<IllegalArgumentException> { Versions.keyVersion("key=G&inst=banjo") }
    }

    // --- render.own_version ---------------------------------------------------------------------------------------

    @Test fun theSongsOwnVersionIsItsEntryElseItsTransposeElseTheSheetAsWritten() {
        val song = LibraryWritesReplay.stub("artist - title")
        fun own(version: String?, transpose: Int?): Version = Versions.ownVersion(
            Overrides(version = version?.let { mapOf(song.key to it) } ?: emptyMap(),
                      transpose = transpose?.let { mapOf(song.key to it) } ?: emptyMap()),
            song, IN_A_MINOR, null)
        assertEquals(Version(), own(null, null))
        assertEquals(Version(t = 3), own(null, 3))
        assertEquals(Version(t = 5, mode = "dorian"), own("mode=dorian", 5))  // a move from the sheet, at its [transpose]
        assertEquals(Version(t = 2, mode = "dorian"), own("t=2&mode=dorian", 5))
        assertEquals(Version(t = -2, mode = "dorian", capo = 0), own("key=Gm&mode=dorian&capo=0", 4))
        assertFailsWith<IllegalArgumentException> { own("key=H", null) }  // as key_version raises in _own
    }

    // --- the data ---------------------------------------------------------------------------------------------------

    @Test fun theModesAreNamedAsTheViewersSettingsNameThem() {
        assertEquals(Theory.MODES.toSet(), Versions.MODE_NAMES.keys)
        assertEquals("Minor", Versions.MODE_NAMES["aeolian"])
        assertEquals(11, Versions.CAPO_MAX)
    }

    private companion object {
        const val IN_A_MINOR = "{title: T}\n{artist: A}\n{key: Am}\n[Am]una [F]can[C]ción [G]más\n"
        const val IN_D_MINOR_CAPO_3 = "{title: T}\n{artist: A}\n{key: Dm}\n{capo: 3}\n[Dm]otra [Bb]le[F]tra [C]más\n"
        val IN_C_MAJOR = IN_A_MINOR.replace("{key: Am}", "{key: C major}")
        const val NO_KEY = "{title: T}\n{artist: A}\n[N.C.]la [Hm]lo\n"
        const val UG = "{title: Synthetic Test Song}\n{artist: The Placeholders}\n{key: G}\n{capo: 2}\n" +
            "{comment: Intro}\n[G] [D] [Em] [C] [*x2]\n"
    }
}
