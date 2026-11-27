package io.github.danielhp95.caracole.viewer.autochords

import io.github.danielhp95.caracole.core.library.SongRow
import io.github.danielhp95.caracole.core.lyrics.Lyrics
import io.github.danielhp95.caracole.viewer.testing.replays.AutochordsReplay
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import org.junit.Test
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith
import kotlin.test.assertNull
import kotlin.test.assertTrue

/** viewer.autochords' sheet half is sheet.py's: every record of vectors/autochords-sheet/sheet.jsonl (make_sheet and
 * raw_of, read_heard and heard_record, relay_due and relay, relays_here, made_by_another, Timed.note), and a few of
 * its cases by hand. */
class SheetHalfTest {
    @Test fun everyRecordIsSheetPys() = AutochordsReplay.sheet()

    private val heard = Heard(Heard.CONTRACT, 10.0, (0 until 5).map {
        ChordSegment(2.0 * it, 2.0 * (it + 1), listOf("C", "G", "Am", "F")[it % 4])
    }, (0..20).map { it * 0.5 }, (0..20 step 4).map { it * 0.5 })

    private fun song(lyrics: Lyrics?, status: String = "found") = SongRow(
        id = 7, key = "k", artist = "Nobody", title = "River Road", artists = listOf("Nobody"), album = null,
        durationMs = null, isrc = null, sourceIds = "{}", addedAt = "", variant = null, status = "found", review = false,
        matchDecision = null, matchStep = null, matchScore = null, matchArtistKey = null, matchSongKey = null,
        matchCandidates = "[]", matchedAt = null, ugDirty = true, ugCheckedAt = null, lyricsStatus = status,
        lyricsJson = lyrics?.toJson(), lyricsAt = null, lacuerdaCheckedAt = null, createdAt = "", audioPath = "/a.m4a",
    )

    @Test fun heardIsWrittenAsPythonWritesItsFloats() {
        val corners = Heard(Heard.CONTRACT, 0.1 + 0.2, listOf(ChordSegment(-0.0, 1e-7, "C")), listOf(1e21, 3.0), emptyList())
        assertEquals("{\"contract\": 1, \"duration\": 0.30000000000000004, \"chords\": [[-0.0, 1e-07, \"C\"]], " +
                         "\"beats\": [1e+21, 3.0], \"downbeats\": []}", corners.json())
        assertEquals(corners, Heard.read(corners.json()))
        assertNull(Heard.read("{\"contract\": 1, \"duration\": null, \"chords\": [], \"beats\": [], \"downbeats\": []}").duration)
    }

    @Test fun heardIsReadStrictly() {
        val good = "\"duration\": 1.0, \"chords\": [], \"beats\": [], \"downbeats\": []"
        for (bad in listOf("{\"contract\": true, $good}", "{\"contract\": 2, $good}", "{\"contract\": \"1\", $good}",
                           "{\"contract\": 1, \"duration\": 1" + "0".repeat(400) + ", \"chords\": [], \"beats\": [], \"downbeats\": []}",
                           "{\"contract\": 1, \"duration\": 1.0, \"chords\": [], \"beats\": [true], \"downbeats\": []}",
                           "[1]")) {
            assertFailsWith<IllegalArgumentException>(bad) { Heard.read(bad) }
        }
        assertEquals(1.0, Heard.read("{\"contract\": 1.0, $good}").duration)
    }

    @Test fun aSitesWordsGoUnderTheChordsAndTheRawSaysWhoMadeIt() {
        val lyrics = Lyrics("Walking down the river road\nSinging to the morning light",
                            "[00:00.50]Walking down the river road\n[00:05.20]Singing to the morning light\n", false,
                            10.0, null)
        val made = SheetHalf.make(song(lyrics), lyrics, heard)
        assertEquals("synced", made.used)
        val maker = Maker("phone", "f0f0f0f0f0f0f0f0", mapOf("chords" to "btc_large_voca@0123456789abcdef"),
                          "onnxruntime 1.32.0", "song.mp3", "00112233aabbccdd")
        val raw = SheetHalf.raw(song(lyrics), lyrics, made, maker = maker)
        assertEquals(listOf("audio", "model", "lyrics", "columns", "key", "synced_lyrics", "lyrics_key", "heard",
                            "made_on", "made_by", "models", "runtime", "audio_name", "audio_sha16"), raw.keys.toList())
        assertEquals("phone", raw.getValue("made_on").jsonPrimitive.content)
        assertEquals(heard, Heard.of(raw.getValue("heard")))
    }

    @Test fun aTranscriptGoesUnderTheChordsOnlyWhereNoSiteHasWords() {
        val transcript = Transcript("[00:01.00]heard words\n", "2026-11-20T01:00:00Z")
        val over = SheetHalf.make(song(null, "missing"), null, heard, transcript = transcript)
        assertEquals("synced", over.used)
        assertTrue(over.text.contains("Lyrics transcribed from the audio (Whisper), unverified"))
        val music = SheetHalf.make(song(null, "instrumental"), null, heard, transcript = transcript, silent = true)
        assertEquals("none", music.used)
        assertNull(music.transcript)
        val raw: JsonObject = SheetHalf.raw(song(null, "missing"), null, over)
        assertEquals("transcript", raw.getValue("lyrics_source").jsonPrimitive.content)
        assertTrue("lyrics_key" !in raw.jsonObject)
    }
}
