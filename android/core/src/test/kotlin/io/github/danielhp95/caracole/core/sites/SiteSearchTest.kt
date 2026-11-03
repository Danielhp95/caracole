package io.github.danielhp95.caracole.core.sites

import io.github.danielhp95.caracole.core.search.SiteArtist
import io.github.danielhp95.caracole.core.search.SiteHit
import io.github.danielhp95.caracole.core.sites.Replay.Companion.int
import io.github.danielhp95.caracole.core.sites.Replay.Companion.list
import io.github.danielhp95.caracole.core.sites.Replay.Companion.string
import io.github.danielhp95.caracole.core.sites.Replay.Companion.text
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonPrimitive
import org.junit.AfterClass
import org.junit.ClassRule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import kotlin.test.assertEquals

/**
 * search.py's other sites against vectors/search/sites.jsonl: `search_gtptabs`, `gtptabs_songs`, `search_musescore`,
 * `search_harptabs`, `harptabs_artist`, `harptabs_songs` and `search_gametabs`, each record Python's answer to the
 * same call over the same fixture (tests/test_conformance_search.py), compared whole.
 */
class SiteSearchTest {
    @Test fun everyRecordIsAFunctionOfSiteSearch() {
        val known = setOf(GTPTABS, GTPTABS_SONGS, MUSESCORE, HARPTABS, HARPTABS_ARTIST, HARPTABS_SONGS, GAMETABS)
        assertEquals(emptySet(), replay.records.map { it.fn }.toSet() - known)
    }

    @Test fun gtptabsSongPagesAreScoredAsTheIndexsSongs() = replay.check(GTPTABS) { db, r ->
        hits(SiteSearch.searchGtptabs(db, text(r, 0), int(r, "limit", 5)))
    }

    @Test fun gtptabsSongsAreCountedUnderTheNamesForms() = replay.check(GTPTABS_SONGS) { db, r ->
        JsonPrimitive(SiteSearch.gtptabsSongs(db, text(r, 0)))
    }

    @Test fun museScoreTitlesAreTheQueryOrTheQueryLessAKnownArtist() = replay.check(MUSESCORE) { db, r ->
        hits(SiteSearch.searchMusescore(db, text(r, 0), int(r, "limit", 5)))
    }

    @Test fun harptabsAnswersArtistsThenSongs() = replay.check(HARPTABS) { db, r ->
        val (artists, songs) = SiteSearch.searchHarptabs(db, text(r, 0), int(r, "songs", 5), int(r, "artists", 3))
        list(listOf(artists(artists), hits(songs)))
    }

    @Test fun aHarptabsArtistIsTheirPagesRow() = replay.check(HARPTABS_ARTIST) { db, r ->
        SiteSearch.harptabsArtist(db, text(r, 0))?.toJson() ?: JsonNull
    }

    @Test fun aHarptabsArtistsSongsAreTheirPagesMostViewedFirst() = replay.check(HARPTABS_SONGS) { db, r ->
        hits(SiteSearch.harptabsSongs(db, text(r, 0), string(r, "title")))
    }

    @Test fun gametabsTracksAreSongsOfTheirGames() = replay.check(GAMETABS) { db, r ->
        hits(SiteSearch.searchGametabs(db, text(r, 0), int(r, "limit", 5)))
    }

    @Test fun aGameTabsListIsTheNamesOfTheArrayJsonLoadsReads() {
        // search._listed_names' answers, asked of Python 3.14: a text json.loads refuses names nobody.
        val cases = listOf(
            """["Guitar", "Piano"]""" to listOf("Guitar", "Piano"), """ ["a" ,"b"]""" + "\n" to listOf("a", "b"),
            """["a", 1, null, true, 2.5e3]""" to listOf("a"), """["a", NaN, -Infinity]""" to listOf("a"),
            """[1e999, "x"]""" to listOf("x"), """["a", {"k": "v"}, ["b"]]""" to listOf("a"),
            """["é", "\n"]""" to listOf("é", "\n"), """{"a": "b"}""" to listOf(), "null" to listOf(),
            "" to listOf(), null to listOf(), """["a", abc]""" to listOf(), """["a"] x""" to listOf(),
            """["a", ]""" to listOf(), "['a']" to listOf(), """[01, "a"]""" to listOf(), """["a", .5]""" to listOf(),
            """["a", +1]""" to listOf(), "[\"a\" ]" to listOf(),
        )
        for ((text, names) in cases) assertEquals(names, SiteText.listedNames(text), "$text")
    }

    private fun hits(hits: List<SiteHit>): JsonElement = JsonArray(hits.map { it.toJson() })

    private fun artists(artists: List<SiteArtist>): JsonElement = JsonArray(artists.map { it.toJson() })

    companion object {
        const val VECTOR = "search/sites.jsonl"
        const val GTPTABS = "caracole.search.search_gtptabs"
        const val GTPTABS_SONGS = "caracole.search.gtptabs_songs"
        const val MUSESCORE = "caracole.search.search_musescore"
        const val HARPTABS = "caracole.search.search_harptabs"
        const val HARPTABS_ARTIST = "caracole.search.harptabs_artist"
        const val HARPTABS_SONGS = "caracole.search.harptabs_songs"
        const val GAMETABS = "caracole.search.search_gametabs"

        @get:ClassRule @JvmStatic val tmp = TemporaryFolder()

        private val replaying = lazy { Replay(VECTOR) { tmp.root } }
        private val replay by replaying

        @AfterClass @JvmStatic fun close() {
            if (replaying.isInitialized()) replay.close()
        }
    }
}
