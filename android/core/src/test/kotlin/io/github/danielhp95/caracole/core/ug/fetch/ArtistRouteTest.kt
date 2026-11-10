package io.github.danielhp95.caracole.core.ug.fetch

import io.github.danielhp95.caracole.core.library.Overrides
import io.github.danielhp95.caracole.core.library.SongRow
import io.github.danielhp95.caracole.core.testing.Misses
import io.github.danielhp95.caracole.core.testing.TestDb
import io.github.danielhp95.caracole.core.testing.replays.UgFetchReplay
import io.github.danielhp95.caracole.core.ug.ArtistRoute
import io.github.danielhp95.caracole.core.ug.UgVersion
import io.github.danielhp95.caracole.core.ug.internal.fetch.ArtistPages
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.jsonPrimitive
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder

/**
 * The artist-page route replays vectors/lookup/ug_artist.jsonl (a song the index can't place found on its artist's
 * page, learned (LEARN_TRIES tabs at most) or pasted; a pasted tab page that leads nowhere; the lists, their pages and
 * the cache's 30 days; a 404 and a page gone; titles and `[reject]`; a matched song with no chords in the index), and
 * reads titles, keys and a pasted page's problem as ug/fetch.py reads them.
 */
class ArtistRouteTest {
    @get:Rule val tmp = TemporaryFolder()

    @Test fun everyRecordOfTheArtistRouteReplays() {
        val misses = Misses(UgFetchReplay.ARTIST)
        UgFetchReplay.artist(misses)
        misses.assertNone()
    }

    @Test fun theVectorHoldsEveryWayTheArtistsPageAnswers() {
        val cases = UgFetchReplay.records(UgFetchReplay.ARTIST).map { it.getValue("case").jsonPrimitive.content }
        for (words in listOf("learned from another of their tabs", "the fourth never read",
                             "pasted under [artist_url] read once", "answers 404 for", "robots.txt closes",
                             "links no artist page", "won't parse",
                             "straddling two pages", "cut short", "within 30 days", "past 30 days",
                             "the unfiltered page", "an artist page gone", "leading the next by 8",
                             "closer than 8", "you rejected", "doesn't list", "no chords in the index")) {
            assertTrue("no record of $words", cases.any { words in it })
        }
        for (record in UgFetchReplay.records(UgFetchReplay.ARTIST)) assertTrue(record["noted"] is JsonObject)
    }

    private fun tab(title: String) = UgVersion(
        tabId = 1, songId = null, songName = title, artistName = "Soda Stereo", type = "Chords", part = "", version = 1,
        rating = 4.5, votes = 10, access = "public", url = "https://tabs.ultimate-guitar.com/tab/1", description = null,
        isAcoustic = false, raw = JsonObject(emptyMap()),
    )

    @Test fun aTitleIsTheSongsSameInEitherScriptOnceHyphensGoElseItsRatio() {
        assertEquals(100.0, ArtistPages.titleScore(listOf("te-para-tres"), listOf("te-para-tres")), 0.0)
        assertEquals(100.0, ArtistPages.titleScore(listOf("banma-banma"), listOf("banmabanma")), 0.0)
        assertEquals(95.65217391304348, ArtistPages.titleScore(listOf("te-para-tres"), listOf("te-para-tre")), 1e-9)
        assertEquals(null, ArtistPages.titleHit(tab("Te Para Dos"), listOf("te-para-tres"), fresh = true))
        val hit = ArtistPages.titleHit(tab("Té Para Tres (Live)"), listOf("te-para-tres"), fresh = false)!!
        assertEquals("te-para-tres" to 100.0, hit.key to hit.score)
    }

    @Test fun theBestTitleIsEveryExactOneElseAFuzzyOneThatLeadsByTheMargin() {
        fun hit(key: String, score: Double) = ArtistPages.Hit(tab(key), key, score, fresh = true)
        val exact = listOf(hit("a", 100.0), hit("b", 96.0), hit("a", 100.0))
        assertEquals(listOf("a", "a"), ArtistPages.bestTitle(exact).map { it.key })
        // a key's best score leads: b's 99 is 8 ahead of c's 91, and b 95 alone isn't
        assertEquals(listOf("b", "b"),
                     ArtistPages.bestTitle(listOf(hit("b", 95.0), hit("c", 91.0), hit("b", 99.0))).map { it.key })
        assertEquals(emptyList<String>(), ArtistPages.bestTitle(listOf(hit("b", 95.0), hit("c", 91.0))).map { it.key })
        assertEquals(listOf("b"), ArtistPages.bestTitle(listOf(hit("b", 99.0), hit("c", 91.0))).map { it.key })
        assertEquals(listOf("c"), ArtistPages.bestTitle(listOf(hit("c", 93.0))).map { it.key })
        assertEquals(emptyList<String>(), ArtistPages.bestTitle(emptyList()).map { it.key })
    }

    @Test fun anArtistsKeysAreYourAliasesThenEachArtistsOwnForms() {
        val overrides = Overrides(alias = mapOf("soda-stereo" to listOf("soda-stereo-tribute", "soda")))
        assertEquals(listOf("soda-stereo-tribute", "soda", "soda-stereo", "gustavo-cerati"),
                     ArtistRoute.artistKeys(song(listOf("Soda Stereo", "Gustavo Cerati")), overrides))
        assertEquals(listOf("soda-stereo"), ArtistRoute.artistKeys(song(emptyList()), Overrides()))
    }

    @Test fun aPastedTabPagesProblemIsWhatReadingItFoundOrWhenItIsAskedAgain() {
        val paste = "https://tabs.ultimate-guitar.com/tab/soda-stereo/persiana-americana-chords-101"
        val overrides = Overrides(artistUrl = mapOf("soda-stereo" to paste))
        TestDb.fresh(tmp.newFolder()).use { database ->
            database.writeBlocking { db ->
                val song = song(listOf("Soda Stereo"))
                assertEquals(null, ArtistRoute.pastedPageProblem(db, song, overrides))
                assertTrue(ArtistRoute.artistIsKnown(db, song, overrides))  // a tab page counts until read
                db.kvSet("ug:unreadable:101", """{"until": "2026-11-10T12:00:00Z", "strikes": 1, "error": "x"}""")
                assertEquals(paste to "UG's copy of it can't be read; caracole asks for it again after 2026-11-10",
                             ArtistRoute.pastedPageProblem(db, song, overrides))
                db.kvSetJson("ug:pasted_tab:101", JsonObject(mapOf("artist_url" to JsonPrimitive(null as String?),
                                                                   "problem" to JsonPrimitive(ArtistRoute.PASTE_GONE))))
                assertEquals(paste to ArtistRoute.PASTE_GONE, ArtistRoute.pastedPageProblem(db, song, overrides))
                assertEquals(null, ArtistRoute.pastedPageProblem(
                    db, song, Overrides(artistUrl = mapOf("soda-stereo" to "https://www.ultimate-guitar.com/artist/soda_stereo_2946"))))
            }
        }
    }

    private fun song(artists: List<String>) = SongRow(
        id = 1, key = "soda-stereo/te-para-tres", artist = "Soda Stereo", title = "Té Para Tres", artists = artists,
        album = null, durationMs = null, isrc = null, sourceIds = "{}", addedAt = "2026-10-01T00:00:00Z", variant = null,
        status = "wanted", review = false, matchDecision = "not_found", matchStep = null, matchScore = null,
        matchArtistKey = null, matchSongKey = null, matchCandidates = "[]", matchedAt = null, ugDirty = false,
        ugCheckedAt = null, lyricsStatus = "found", lyricsJson = null, lyricsAt = null, lacuerdaCheckedAt = null,
        createdAt = "2026-10-01T00:00:00Z",
    )
}
