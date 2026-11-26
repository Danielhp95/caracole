package io.github.danielhp95.caracole.core.lyrics

import io.github.danielhp95.caracole.core.http.MegalobizParseError
import io.github.danielhp95.caracole.core.http.Response
import io.github.danielhp95.caracole.core.testing.FakeTransport.Companion.answer
import io.github.danielhp95.caracole.core.testing.Misses
import io.github.danielhp95.caracole.core.testing.replays.LyricsReplay
import kotlinx.serialization.json.jsonPrimitive
import io.github.danielhp95.caracole.core.library.LyricsPick
import io.github.danielhp95.caracole.core.library.LyricsRecord
import io.github.danielhp95.caracole.core.library.OverrideUrls
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import java.math.BigInteger
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith
import kotlin.test.assertNull
import kotlin.test.assertTrue

/** megalobiz.py and megalobiz_fetch.py on the phone: vectors/sites/megalobiz.jsonl and lookup/megalobiz.jsonl, and a
 * few cases by hand. */
class MegalobizTest {
    @get:Rule val tmp = TemporaryFolder()

    @Test fun theApisAnswersReadAsMegalobizPyReadsThem() {
        val misses = Misses("lyrics: ${LyricsReplay.MEGALOBIZ_SITES}")
        LyricsReplay.megalobizSites(misses)
        misses.assertNone()
    }

    @Test fun aLookupsPassAsksDecidesAndWritesAsMegalobizFetchPyDoes() {
        val misses = Misses("lyrics: ${LyricsReplay.MEGALOBIZ_LOOKUP}")
        LyricsReplay.megalobizLookups(misses)
        misses.assertNone()
    }

    private fun response(body: String) = Response(Megalobiz.lrcUrl(BigInteger.ONE), 200, body.toByteArray(), emptyMap())

    @Test fun aRecordsLinesAreStampedAsPythonRoundsThem() {
        val lrc = Megalobiz.parseLrc(response("""{"id": 1, "url": "https://megalobiz.com/lrc/1/x", "lrc": null,
            "lines": [{"time_ms": 1005, "text": "a"}, {"time_ms": 1015, "text": "b"}, {"time_ms": -61005, "text": "c"},
                      {"time_ms": true, "text": "d"}, {"time_ms": 2.5, "text": "e"}]}"""))
        assertEquals("[00:01.00]a\n[00:01.01]b\n[-2:58.99]c\n[00:00.00]d", lrc.lrc)
    }

    @Test fun aRecordNotAsDocumentedIsAParseErrorWithPythonsWords() {
        val e = assertFailsWith<MegalobizParseError> { Megalobiz.parseSearch(response("""{"results": [{"id": "1"}]}""")) }
        assertTrue(e.message!!.endsWith("a record without a numeric id: '1'"), e.message)
        val nested = assertFailsWith<MegalobizParseError> {
            Megalobiz.parseSearch(response("""{"results": [{"id": {"a": [1, null, "x'y", 1.5e-7, true]}}]}"""))
        }
        assertTrue(nested.message!!.endsWith("""a record without a numeric id: {'a': [1, None, "x'y", 1.5e-07, True]}"""),
                   nested.message)
    }

    @Test fun aCoverOrAResultCreditedToNoOneIsNoFit() {
        fun r(id: Long, title: String, artist: String) =
            Megalobiz.Result(BigInteger.valueOf(id), title, artist, 200.0, "https://megalobiz.com/lrc/$id/x")
        assertNull(Megalobiz.pickResult(listOf(r(1, "Song (Cover)", "A"), r(2, "Song", " ")), "A", "Song", 200.0))
        assertEquals(BigInteger.valueOf(3), Megalobiz.pickResult(listOf(r(1, "Song (Cover)", "A"), r(3, "Song", "A")),
                                                                 "A", "Song", 200.0)?.id)
    }

    @Test fun aMissIsRememberedAndAskedAgainOnlyAfterThirtyDays() {
        LyricsWorld(tmp.newFolder()).use { w ->
            val song = w.song("Toby Fox", "Megalovania", 214_000L, "lyrics_status" to "missing")
            val search = "GET https://api.megalobiz.com/api/public/v1/search?title=Megalovania&artist=Toby+Fox&duration=214&limit=10"
            val (client, site) = w.client("megalobiz", mapOf(search to answer(200, LyricsWorld.fixture("megalobiz/search_megalovania.json"))))
            val stats = w.db { Megalobiz.megalobizLyrics(it, client, w.library, w.now, setOf(song.id)) }
            assertEquals(1, stats.missing)
            assertEquals(listOf(search), site.said)
            assertEquals("2026-11-03T12:00:00Z", w.db { it.kvGet("${Megalobiz.CHECKED}${song.id}") })
            assertTrue(w.db { Megalobiz.songsToAsk(it, w.now, only = setOf(song.id)) }.isEmpty())
            assertEquals(listOf(song.id), w.db { Megalobiz.songsToAsk(it, w.now.plusSeconds(31L * 86400), only = setOf(song.id)) }.map { it.id })
        }
    }

    @Test fun theVectorsHoldEveryParserAndAPassForEachAnswer() {
        val fns = LyricsReplay.records(LyricsReplay.MEGALOBIZ_SITES).map { it.getValue("fn").jsonPrimitive.content }.toSet()
        assertEquals(setOf("caracole.megalobiz.search_params", "caracole.megalobiz.lrc_url", "caracole.megalobiz.parse_search",
                           "caracole.megalobiz.parse_lrc", "caracole.megalobiz.pick_result"), fns)
        assertTrue(LyricsReplay.records(LyricsReplay.MEGALOBIZ_LOOKUP).size >= 15)
    }

    @Test fun aPickedRecordIsAskedAloneItsMissMakesTheSongMissingAndAnotherSitesIsPassedOver() {
        LyricsWorld(tmp.newFolder()).use { w ->
            val song = w.song("Los Águilas", "Hotel Californio", 391_000L)
            val other = w.song("Eagles", "Hotel California", 391_000L, "lyrics_status" to "missing")
            val picks = mapOf(OverrideUrls.overrideKey(song.display) to LyricsPick(null, LyricsRecord("megalobiz", "24519")),
                              OverrideUrls.overrideKey(other.display) to LyricsPick(null, LyricsRecord("lrclib", "7")))
            val lrc = "GET https://api.megalobiz.com/api/public/v1/lrc/24519"
            val (client, site) = w.client("megalobiz", mapOf(lrc to answer(404, "{\"error\": \"not_found\"}")))
            val stats = w.db { Megalobiz.megalobizLyrics(it, client, w.library, w.now, setOf(song.id, other.id), picks = picks) }
            assertEquals(1, stats.missing)
            assertEquals(listOf(lrc), site.said)
            assertEquals("missing", w.db { io.github.danielhp95.caracole.core.library.Songs.byId(it, song.id) }!!.lyricsStatus)
        }
    }

    @Test fun aPickedRecordAskedAgainAfterAnErrorIsAskedPastTheCache() {
        // Its 404 is cached forever; the re-check 30 days on meets an error (back to pending), and the next run asks
        // Megalobiz itself, never reading the old 404 for a new miss.
        LyricsWorld(tmp.newFolder()).use { w ->
            val song = w.song("Eagles", "Hotel California", 391_000L)
            val picks = mapOf(OverrideUrls.overrideKey(song.display) to LyricsPick(null, LyricsRecord("megalobiz", "24519")))
            val lrc = "GET https://api.megalobiz.com/api/public/v1/lrc/24519"
            fun pass(answer: io.github.danielhp95.caracole.core.http.HttpAnswer, days: Long): Pair<MegalobizStats, List<String>> {
                val (client, site) = w.client("megalobiz", mapOf(lrc to answer))
                val stats = w.db {
                    Megalobiz.megalobizLyrics(it, client, w.library, w.now.plusSeconds(days * 86400), setOf(song.id), picks = picks)
                }
                return stats to site.said
            }
            assertEquals(1, pass(answer(404, "{\"error\": \"not_found\"}"), 0).first.missing)
            assertEquals(1, pass(answer(502, "Bad Gateway"), 31).first.errors)
            val (stats, said) = pass(answer(200, LyricsWorld.fixture("megalobiz/lrc_24519.json")), 32)
            assertEquals(1, stats.found)
            assertEquals(listOf(lrc), said)
        }
    }
}
