package io.github.danielhp95.caracole.viewer

import io.github.danielhp95.caracole.core.lookup.RenderStats
import io.github.danielhp95.caracole.core.testing.Replays
import io.github.danielhp95.caracole.core.testing.TestDb
import io.github.danielhp95.caracole.viewer.chinese.OpenCC
import io.github.danielhp95.caracole.viewer.harmony.Numeral
import io.github.danielhp95.caracole.viewer.harmony.Progression
import io.github.danielhp95.caracole.viewer.harp.HarpChoice
import io.github.danielhp95.caracole.viewer.harpfit.Choice
import io.github.danielhp95.caracole.viewer.harpfit.Fit
import io.github.danielhp95.caracole.viewer.harptab.Notation
import io.github.danielhp95.caracole.viewer.harptab.Symbol
import io.github.danielhp95.caracole.viewer.pages.BookSong
import io.github.danielhp95.caracole.viewer.pages.ViewerInputs
import io.github.danielhp95.caracole.viewer.progressions.Wanted
import io.github.danielhp95.caracole.viewer.render.PhoneRender
import io.github.danielhp95.caracole.viewer.render.Written
import io.github.danielhp95.caracole.viewer.shapes.Instrument
import io.github.danielhp95.caracole.viewer.shapes.Voicings
import io.github.danielhp95.caracole.viewer.sheet.Item
import io.github.danielhp95.caracole.viewer.sheet.Lyrics
import io.github.danielhp95.caracole.viewer.sheet.Sheet
import io.github.danielhp95.caracole.viewer.sheet.SongKey
import io.github.danielhp95.caracole.viewer.testing.ViewerReplays
import io.github.danielhp95.caracole.viewer.theory.Chord
import io.github.danielhp95.caracole.viewer.theory.Key
import io.github.danielhp95.caracole.viewer.version.Setting
import io.github.danielhp95.caracole.viewer.version.Version
import io.github.danielhp95.caracole.viewer.winds.Winds
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import java.io.File
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertNull
import kotlin.test.assertTrue

/** :viewer's declarations (milestone 5, skeleton-m5m6's): each package's types are values, the neutral seams answer
 * as the phone did before them, the corpus's viewer areas are registered, and every stub names its lane. What each
 * declaration answers is its lane's tests'. */
class ViewerSkeletonTest {
    @get:Rule val tmp = TemporaryFolder()

    @Test fun theoryChordsAndKeysAreValues() {
        assertEquals(Chord(0, "maj7", shown = "M7"), Chord(0, "maj7", shown = "M7"))
        assertEquals(Key(9, "aeolian"), Key(9, "aeolian").copy())
    }

    @Test fun aSheetIsAValueWithPythonsDefaults() {
        assertEquals(Sheet(), Sheet(title = "", artist = "", key = null, capo = null, auto = false))
        assertEquals(Lyrics(listOf(null to "Hello ", Item.Chord(0) to "world")).parts[1].first, Item.Chord(0))
        assertEquals("tab", SongKey("Am", "tab").source)
    }

    @Test fun theGuitarsTuningIsTheSkeletonsWhole() {
        assertEquals(listOf(40, 45, 50, 55, 59, 64), Voicings.TUNING)
        assertEquals("guitar", Instrument("piano", "Piano", "keys", capo = false).voice)
    }

    @Test fun theHarpTheWindsAndChineseAreDeclared() {
        assertEquals(HarpChoice(1, 0, "ionian", 1.0, 3, 3, 0), HarpChoice(1, 0, "ionian", 1.0, 3, 3, 0))
        assertEquals("Winds", Winds::class.simpleName)
        assertEquals(listOf("T2S", "TW2S", "S2TW"), OpenCC.Config.entries.map { it.name })
    }

    @Test fun harmonysAnswersAreValues() {
        assertEquals(Numeral("", "V", "", "7", null, "V"), Numeral("", "V", "", "7", null, "V"))
        assertEquals(0, Progression(listOf("I", "V"), 2, null, "authentic").variations)
    }

    @Test fun aVersionsSettingIsTheSongbooksOwnType() {
        assertEquals(Version(), Version(t = 0, mode = null, capo = null))
        assertEquals(io.github.danielhp95.caracole.core.songbooks.Setting::class, Setting::class)
        assertEquals("I–V–vi–IV", Wanted("1.5.6.4", setOf("1.5.6.4"), null, "I–V–vi–IV").label)
    }

    @Test fun aHarmonicaTabsNotationAndItsHarpAreValues() {
        assertEquals("blow", Notation("signs", listOf(Symbol("-", "draw", "before"))).bare)
        assertEquals(Choice(7, "page", listOf(Fit(7, 0.5, 20))), Choice(7, "page", listOf(Fit(7, 0.5, 20))))
    }

    @Test fun thePagesInputsKeepPythonsDefaults() {
        val inputs = ViewerInputs("{title: T}")
        assertTrue(inputs.export)
        assertEquals(emptyList(), inputs.guitar)
        assertNull(BookSong("T", "A").start)
    }

    @Test fun thePhonesRenderIsNeutralUntilItsLaneLands() {
        TestDb.fresh(tmp.root).use { database ->
            val render = PhoneRender(database, File(tmp.root, "library"), null)
            assertEquals(RenderStats(), database.read { db -> render.render(db, listOf(1L, 2L), null) })
            assertFalse(render.stale())
            render.afterSync()
        }
        assertEquals("x", Written("x", 1, "d").sha256)
    }

    @Test fun theViewersCorpusAreasAreRegisteredOnceEach() {
        val areas = ViewerReplays.all.map { it.area }
        assertEquals(listOf("theory", "sheet", "shapes", "chinese", "harmony", "version", "harptab", "pages",
                            "harmonica-page", "render"), areas)
        assertEquals(listOf("harmonica-page"), Replays.named(listOf("harmonica_page"), ViewerReplays.all).map { it.area })
        val elsewhere = Replays.all.map { it.area }.toSet()
        assertEquals(emptySet(), areas.toSet() intersect elsewhere)
    }

    @Test fun everyStubNamesItsLane() {
        val stub = Regex("""TODO\(([^)]*)\)""")
        val named = Regex(""""lane [a-z-]+"""")
        val bad = File("src/main/kotlin").walk().filter { it.isFile && it.extension == "kt" }.flatMap { file ->
            stub.findAll(file.readText()).map { it.groupValues[1] }.filterNot { named.matches(it) }
                .map { "${file.name}: TODO($it)" }
        }.toList()
        assertEquals(emptyList(), bad)
    }
}
