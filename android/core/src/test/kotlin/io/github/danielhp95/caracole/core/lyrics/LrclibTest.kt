package io.github.danielhp95.caracole.core.lyrics

import io.github.danielhp95.caracole.core.json.PyJson
import io.github.danielhp95.caracole.core.testing.FakeTransport.Companion.answer
import io.github.danielhp95.caracole.core.testing.Misses
import io.github.danielhp95.caracole.core.testing.replays.LyricsReplay
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.long
import kotlinx.serialization.json.jsonPrimitive
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import java.io.File
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith
import kotlin.test.assertFalse
import kotlin.test.assertNull
import kotlin.test.assertTrue

/** lyrics.py on the phone: vectors/sites/lrclib.jsonl and lookup/lrclib.jsonl (tests/test_conformance_lyrics.py),
 * and a few of tests/test_lyrics.py's cases by hand. */
class LrclibTest {
    @get:Rule val tmp = TemporaryFolder()

    @Test fun theParsersAndPickersAnswerAsLyricsPyDoes() {
        val misses = Misses("lyrics: ${LyricsReplay.LRCLIB_SITES}")
        LyricsReplay.lrclibSites(misses)
        misses.assertNone()
    }

    @Test fun aLookupsPassAsksDecidesAndWritesAsLyricsPyDoes() {
        val misses = Misses("lyrics: ${LyricsReplay.LRCLIB_LOOKUP}")
        LyricsReplay.lrclibLookups(misses)
        misses.assertNone()
    }

    private fun record(vararg fields: Pair<String, Any?>): JsonObject {
        val base = PyJson.loads(LyricsWorld.fixture("lrclib/get_hit.json")).jsonObject
        return JsonObject(base + fields.associate { (k, v) ->
            k to when (v) {
                null -> kotlinx.serialization.json.JsonNull
                is Double -> PyJson.float(v)
                is Number -> JsonPrimitive(v)
                else -> JsonPrimitive(v.toString())
            }
        })
    }

    private fun id(o: JsonObject?) = o?.get("id")?.jsonPrimitive?.long

    @Test fun aCloseLengthComesFirstThenSyncedLyrics() {
        val pick = { cands: List<JsonObject> -> id(Lrclib.pickCandidate(cands, "Soda Stereo", "De Música Ligera", 200.0)) }
        val farSynced = record("id" to 1, "duration" to 205.0)
        val closePlain = record("id" to 2, "duration" to 201.0, "syncedLyrics" to null)
        val closeSynced = record("id" to 3, "duration" to 201.8)
        val closestPlain = record("id" to 4, "duration" to 200.2, "syncedLyrics" to null)
        assertEquals(3L, pick(listOf(farSynced, closePlain, closeSynced, closestPlain)))
        assertEquals(4L, pick(listOf(farSynced, closePlain, closestPlain)))
        assertEquals(1L, pick(listOf(record("id" to 5, "duration" to 207.0), farSynced)))
    }

    @Test fun beyondTenSecondsOnlyTheSameKeysFit() {
        assertEquals(2 to 30.0, Lrclib.fits("Soda Stereo", "De Música Ligera", 213.0, "Soda Stereo", "De Musica Ligera", 243.0))
        assertNull(Lrclib.fits("Soda Stereo", "De Música Ligera", 213.0, "Soda Stereo", "De Música Ligeras", 243.0))
        assertEquals(0 to 0.0, Lrclib.fits("Soda Stereo", "De Música Ligera", null, "Soda Stereo", "De Música Ligera", 999.0))
    }

    @Test fun anotherKindOfVersionIsOneTheSongsTitleDoesntName() {
        assertTrue(Lrclib.anotherVersion("Song", "Song (Cover)"))
        assertFalse(Lrclib.anotherVersion("Song (Remix)", "Song - Remix"))
        assertFalse(Lrclib.anotherVersion("Song", "Discovery"))
    }

    @Test fun hanTextSplitByPunctuationIsJoinedForTheSearch() {
        assertEquals("斑马斑马", Lrclib.searchTitle("斑马，斑马"))
        assertEquals("너의 의미", Lrclib.searchTitle("너의 의미"))
    }

    @Test fun aHitWritesBothFilesAndAMissIsAskedAgainPastTheCacheAfterThirtyDays() {
        LyricsWorld(tmp.newFolder()).use { w ->
            val song = w.song("Soda Stereo", "De Música Ligera", 213_000L)
            val get = "GET https://lrclib.net/api/get?artist_name=Soda+Stereo&track_name=De+M%C3%BAsica+Ligera&duration=213"
            val (client, site) = w.client("lrclib", mapOf(get to answer(200, LyricsWorld.fixture("lrclib/get_hit.json"))))
            val stats = w.db { Lrclib.fetchPendingLyrics(it, client, w.library, w.now, setOf(song.id)) }
            assertEquals(1, stats.found)
            assertEquals(listOf(get), site.said)
            val folder = w.library.folderOf(song)
            assertTrue(File(folder, "lyrics.txt").readText().endsWith("de prueba\n"))
            assertTrue(File(folder, "lyrics.lrc").isFile)
            val stored = w.db { songLyrics(it, song.id) }!!
            assertEquals("lrclib", stored.provider)
            assertEquals(1040023L, stored.lrclibId)
        }
    }

    @Test fun numbersTooBigForAFloatAreAnErrorAsPythonsIntAndFloatMakeThem() {
        // Python: float(10**400) is an OverflowError; int() of 4301 digits a ValueError; a float literal past the
        // largest double json.loads reads as inf.
        val big = "1" + "0".repeat(400)
        assertFailsWith<ArithmeticException> { Lyrics.fromRecord(PyJson.loads("""{"duration": $big}""").jsonObject) }
        assertEquals(Double.POSITIVE_INFINITY, Lyrics.fromRecord(PyJson.loads("""{"duration": 1e309}""").jsonObject).duration)
        assertFailsWith<ArithmeticException> { Lyrics.syncedLines("[${"1".repeat(400)}:00.25]Far") }
        assertFailsWith<IllegalArgumentException> { Lyrics.syncedLines("[${"1".repeat(4301)}:00.25]Far") }
        assertFailsWith<IllegalArgumentException> { Lyrics.syncedLines("[${"\u0660".repeat(4301)}:00.25]Far") }
        assertEquals(listOf(0.25 to "Near"), Lyrics.syncedLines("[${"0".repeat(4300)}:00.25]Near"))
        // A word stamp is taken out, never read as a number.
        assertEquals(listOf(1.0 to "a b"), Lyrics.syncedLines("[00:01.00]a <${"9".repeat(4301)}:00.00> b"))
    }

    @Test fun plainLyricsAloneTakeAStaleLrcAway() {
        val dir = tmp.newFolder()
        File(dir, "lyrics.lrc").writeText("[00:01.00]old\n")
        val written = Lrclib.writeLyrics(dir, Lyrics("one\ntwo\n\n", null, false, null, null))
        assertEquals(listOf(File(dir, "lyrics.txt")), written)
        assertEquals("one\ntwo\n", File(dir, "lyrics.txt").readText())
        assertFalse(File(dir, "lyrics.lrc").exists())
        assertEquals(emptyList(), Lrclib.writeLyrics(dir, Lyrics("", null, true, null, null)))
        assertFalse(File(dir, "lyrics.txt").exists())
    }

    @Test fun everyRecordOfTheVectorsIsReplayed() {
        val fns = LyricsReplay.records(LyricsReplay.LRCLIB_SITES).map { it.getValue("fn").jsonPrimitive.content }.toSet()
        assertEquals(setOf("caracole.lyrics.Lyrics.from_record", "caracole.lyrics.fits", "caracole.lyrics.another_version",
                           "caracole.lyrics._search_title", "caracole.lyrics.pick_candidate", "caracole.lyrics.read",
                           "caracole.lyrics.fetch_lyrics"), fns)
        val cases = LyricsReplay.records(LyricsReplay.LRCLIB_LOOKUP)
        assertTrue(cases.size >= 15)
        assertTrue(cases.any { r -> (r["out"]?.jsonObject?.get("requests") as? JsonArray)?.size == 2 &&
            r.getValue("case").jsonPrimitive.content.startsWith("LRCLIB's 503") })
        assertTrue(cases.first().getValue("kw").jsonObject.getValue("only").jsonArray.isNotEmpty())
    }
}
