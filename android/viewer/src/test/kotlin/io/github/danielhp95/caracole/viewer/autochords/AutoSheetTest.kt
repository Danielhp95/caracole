package io.github.danielhp95.caracole.viewer.autochords

import io.github.danielhp95.caracole.core.testing.ForbiddenApis
import io.github.danielhp95.caracole.viewer.testing.replays.AutochordsReplay
import org.junit.Test
import java.io.File
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith
import kotlin.test.assertNull

/** viewer.autochords lays a sheet out as merge.py does: every record of vectors/autochords-sheet/merge.jsonl
 * (AutochordsReplay), and test_autochords_merge.py's own cases, by hand. */
class AutoSheetTest {
    @Test fun everyRecordIsMergePys() = AutochordsReplay.merge()

    @Test fun viewerAutochordsNeverAsksTheJdkAboutText() {
        val found = ForbiddenApis.check(File("src/main/kotlin/io/github/danielhp95/caracole/viewer/autochords"))
        assertEquals(emptyList(), found)
    }

    private val beats = (0..120).map { it * 0.5 }
    private fun seg(a: Double, b: Double, label: String) = ChordSegment(a, b, label)

    @Test fun aChordGoesOverTheWordAtItsTimesColumn() {
        val synced = "[00:08.00]Walking down the river road\n[00:12.00]Singing to the morning light\n" +
            "[00:16.00]Nothing left to say\n"
        val segs = listOf(seg(8.0, 10.0, "G"), seg(10.0, 12.0, "D"), seg(12.0, 16.0, "Em"), seg(16.0, 18.0, "C"),
                          seg(18.0, 20.0, "G"))
        assertEquals(
            "auto-generated, unverified\nNobody - River Road\n\n[ch]G[/ch]            [ch]D[/ch]\n" +
                "Walking down the river road\n[ch]Em[/ch]\nSinging to the morning light\n[ch]C[/ch]       [ch]G[/ch]\n" +
                "Nothing left to say\n",
            AutoSheet.build(segs, "River Road", "Nobody", synced = synced, beats = beats))
    }

    @Test fun aChordOverAChineseLineGoesAtItsCharactersDisplayColumn() {
        val synced = "[00:08.00]第一行歌词在这里\n[00:12.00]第二行歌词在这里\n"
        val lines = AutoSheet.build(listOf(seg(8.0, 10.0, "G"), seg(10.0, 16.0, "D")), "斑马斑马", "宋冬野",
                                    synced = synced, beats = beats).lines()
        assertEquals(listOf("[ch]G[/ch]       [ch]D[/ch]", "第一行歌词在这里"), lines.subList(3, 5))
    }

    @Test fun aChangeHalfWayBetweenTwoBeatsGoesToTheEarlier() {
        assertEquals(listOf(seg(0.0, 1.0, "G"), seg(1.0, 2.0, "D")),
                     AutoSheet.snapToBeats(listOf(seg(0.25, 1.25, "G"), seg(1.25, 2.0, "D")), beats))
    }

    @Test fun aWordStartsAfterPunctuationAndAnApostropheJoinsTwoLetters() {
        assertEquals(1, AutoSheet.wordStart("¿Dónde estás?", 0))
        assertEquals(6, AutoSheet.wordStart("can't stop", 4))
        assertEquals(listOf(0, 1, 2, 3), (0..3).map { AutoSheet.wordStart("君の名は", it) })
    }

    @Test fun theYoutubeCreditNamesTheVideoByItsTitleElseItsId() {
        assertEquals("Audio from YouTube: Creep", AutoSheet.youtubeCredit("Creep", "", "XFkzRNyygfk"))
        assertEquals("Audio from YouTube: XFkzRNyygfk (Radiohead - Topic)",
                     AutoSheet.youtubeCredit("", "Radiohead - Topic", "XFkzRNyygfk"))
    }

    @Test fun plainLyricsGoOnASheetOfNoneAsItsLastSection() {
        val bare = AutoSheet.build(listOf(seg(0.0, 2.0, "G")), "T", "A", beats = beats.take(5))
        assertEquals(bare.trimEnd('\n') + "\n\n[Lyrics]\nLa la\n\nla\n", AutoSheet.withPlainLyrics(bare, "\nLa la  \n\nla\n\n"))
    }

    @Test fun lrcIsReadAsMergePyReadsIt() {
        val lines = Lrc.parseWords("[offset:+500]\n[00:16.00] <00:16.00> Hel<00:16.40>lo <00:17.00>world\n[00:18.00]\n")
        assertEquals(listOf(LrcLine(15.5, "Hello world", listOf(WordStart(15.5, 0), WordStart(15.9, 3), WordStart(16.5, 6))),
                            LrcLine(17.5, "", null)), lines)
        assertEquals(listOf(12.5 to "x"), Lrc.parse("[٠٠:١٢.٥٠]x"))
        assertNull(Lrc.parseWords("[00:01]no words").single().words)
        assertFailsWith<IllegalArgumentException> { Lrc.parse("[0" + "9".repeat(5000) + ":01]x") }
        assertFailsWith<ArithmeticException> { Lrc.parse("[" + "9".repeat(400) + ":01]x") }
    }
}
