package io.github.danielhp95.caracole.viewer.autochords

import io.github.danielhp95.caracole.core.library.Overrides
import io.github.danielhp95.caracole.core.library.SongRow
import io.github.danielhp95.caracole.core.library.Songs
import io.github.danielhp95.caracole.viewer.testing.replays.AutochordsReplay
import org.junit.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertTrue

/** An auto sheet laid out again from what was heard is sheet_lyrics.py's: relay_onto_sheets over
 * vectors/autochords-sheet/relay.jsonl's library, step by step (a phone-made sheet over words that came; one made
 * here from the audio held now; none from audio since replaced; one made elsewhere though this side holds other
 * audio; an unreadable heard; ignored, in [ignore], beside a human sheet; a transcript and nothing sung noted here; one
 * up to date; a second pass that writes nothing), and its guards by hand. */
class RelayTest {
    @Test fun everyStepIsRelayOntoSheets() = AutochordsReplay.relay()

    private fun song(path: String?, mtime: Double?, heardFrom: Double?) = SongRow(
        id = 1, key = "k", artist = "A", title = "T", artists = listOf("A"), album = null, durationMs = null, isrc = null,
        sourceIds = "{}", addedAt = "", variant = null, status = "found", review = false, matchDecision = null,
        matchStep = null, matchScore = null, matchArtistKey = null, matchSongKey = null, matchCandidates = "[]",
        matchedAt = null, ugDirty = true, ugCheckedAt = null, lyricsStatus = "found", lyricsJson = null, lyricsAt = null,
        lacuerdaCheckedAt = null, createdAt = "", audioPath = path, audioMtime = mtime, autochordsMtime = heardFrom,
    )

    @Test fun aSheetIsReLaidOnlyFromTheAudioItWasHeardFromOrWhereThisSideHoldsNone() {
        assertTrue(Relay.relaysHere(song(null, null, null)))
        assertTrue(Relay.relaysHere(song("/a.m4a", 100.0, 100.0)))
        assertTrue(Relay.relaysHere(song("/a.m4a", 0.0, -0.0))) // Python's ==: -0.0 is 0.0
        assertFalse(Relay.relaysHere(song("/a.m4a", 200.0, 100.0)))
        assertFalse(Relay.relaysHere(song("/a.m4a", Double.NaN, Double.NaN)))
        assertTrue(Relay.relaysHere(song("/a.m4a", 200.0, 100.0), elsewhere = true))
    }

    @Test fun aReLayThatFailsIsReportedInWordsAndCostsTheOtherSongsNothing() {
        AutochordsReplay.relayLibrary { database, library ->
            database.writeBlocking { db ->
                val titles = Songs.list(db).associate { it.id to it.title }
                val relayed = Relay.onto(db, library, Overrides.read(db)) { song, raw, noted ->
                    if (song.title == "Made Here") throw IllegalStateException("injected") else Relay.relay(song, raw, noted)
                }
                val failed = relayed.failed.mapKeys { titles.getValue(it.key) }
                assertEquals(setOf("Made Here", "Unlaid Bug"), failed.keys) // the injected one, and the library's own bug
                assertEquals("Nobody - Made Here: a bug in caracole: java.lang.IllegalStateException: injected",
                             failed.getValue("Made Here"))
                assertTrue(failed.getValue("Unlaid Bug").startsWith("Nobody - Unlaid Bug: a bug in caracole: "))
                // every other song due is re-laid all the same
                assertEquals(setOf("Phone Made", "From A Video", "Made Elsewhere", "Transcribed Since", "Nothing Sung",
                                   "Over A Transcript", "Columns", "Not Sung You Said", "Instrumental Since"),
                             relayed.songs.map { it.title }.toSet())
            }
        }
    }
}
