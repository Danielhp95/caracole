package io.github.danielhp95.caracole.core.sites

import io.github.danielhp95.caracole.core.testing.Corpus
import io.github.danielhp95.caracole.core.testing.Misses
import io.github.danielhp95.caracole.core.testing.replays.SearchReplay
import org.junit.Test
import kotlin.test.assertEquals

/**
 * search.py's other sites against vectors/search/sites.jsonl: `search_gtptabs`, `gtptabs_songs`, `search_musescore`,
 * `search_harptabs`, `harptabs_artist`, `harptabs_songs` and `search_gametabs`, each record Python's answer to the
 * same call over the same fixture (tests/test_conformance_search.py), compared whole. The records are
 * SearchReplay.sites', which the device runs too: one replay of the vector, each fixture loaded once, a miss naming its
 * function.
 */
class SiteSearchTest {
    @Test fun everyRecordIsAFunctionOfSiteSearch() {
        assertEquals(emptySet(), Corpus.records(VECTOR).map { it.fn }.toSet() - SearchReplay.SITES_FNS)
        assertEquals(SearchReplay.SITES_FNS, Corpus.records(VECTOR).map { it.fn }.toSet(), "a record of each")
    }

    /** gtptabs.com's song pages scored as the index's songs, and counted under the names' forms; MuseScore's titles,
     * the query or the query less a known artist; harptabs.com's artists then songs, an artist their page's row, their
     * songs the page's most viewed first; gametabs.net's tracks, songs of their games. */
    @Test fun everySiteAnswersAsSearchPyDoes() = Misses(VECTOR).also { SearchReplay.sites(it) }.assertNone()

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

    companion object {
        const val VECTOR = SearchReplay.SITES
    }
}
