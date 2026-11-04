package io.github.danielhp95.caracole.core.search

import io.github.danielhp95.caracole.core.testing.Corpus
import io.github.danielhp95.caracole.core.testing.Misses
import io.github.danielhp95.caracole.core.testing.TestDb
import io.github.danielhp95.caracole.core.testing.replays.SearchReplay
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import kotlin.test.assertEquals
import kotlin.test.assertNull
import kotlin.test.assertTrue

/**
 * search.py's answers over your songs and UG's index, against vectors/search/library.jsonl and index.jsonl: each
 * record's call over its fixture (vectors/search/fixtures/<name>.jsonl) replayed into a fresh database, as Python ran
 * it (tests/test_conformance_search.py, whose docstring names each composed record): SearchReplay's, which the device
 * runs too. Every answer compares whole, as helpers.corpus.plain wrote it (a song as its key), numbers as doubles
 * with ==.
 */
class SearchUgTest {
    @get:Rule val tmp = TemporaryFolder()

    @Test fun everyRecordOfTheLibraryVectorIsWhatSearchPyAnswers() =
        Misses(LIBRARY).also { SearchReplay.library(it) }.assertNone()

    @Test fun everyRecordOfTheIndexVectorIsWhatSearchPyAnswers() =
        Misses(INDEX).also { SearchReplay.index(it) }.assertNone()

    @Test fun bothVectorsHoldEveryFunctionThisLanePorts() {
        val fns = (Corpus.records(LIBRARY) + Corpus.records(INDEX)).map { it.fn }.toSet()
        assertEquals(SearchReplay.LIBRARY_FNS + SearchReplay.INDEX_FNS, fns)
    }

    @Test fun noOnesIsEveryMiscKey() {
        assertTrue(Search.noOnes("misc-musicals"))
        assertTrue(Search.noOnes("misc-mashups"))
        assertEquals(false, Search.noOnes("misc"))
        assertEquals(false, Search.noOnes("radiohead"))
    }

    @Test fun aKeyIsShownWithEachWordsFirstLetterUpper() {
        assertEquals("Soda Stereo" to "De Musica Ligera", Search.displayFromKeys("soda-stereo", "de-musica-ligera"))
        assertEquals("3am" to "", Search.displayFromKeys("3am", ""))
        assertEquals("SSo Ǆx" to "Élan", Search.displayFromKeys("ßo-ǆx", "élan"))
    }

    @Test fun anEmptyDatabaseFindsNothingAndHintsAtBareIds() {
        TestDb.fresh(tmp.root).use { database ->
            database.read { db ->
                assertEquals(emptyList(), Search.searchLibrary(db, "creep"))
                assertEquals(IndexFound(), Search.findIndex(db, "creep"))
                assertNull(Search.indexArtist(db, "radiohead"))
                assertEquals(emptyList<IndexHit>() to 0, Search.artistSongs(db, "radiohead"))
            }
        }
        assertEquals(
            JsonObject(mapOf("strong" to JsonPrimitive(false), "entry" to JsonPrimitive(
                "[artist_url]\n\"a \\\"b\\\"\" = \"https://www.ultimate-guitar.com/artist/…\""),
                "add" to JsonPrimitive("caracole add ARTIST \"a \\\"b\\\"\""))),
            Search.bareIdUnseen(" a  \"b\" ", emptyList()),
        )
    }

    companion object {
        const val LIBRARY = SearchReplay.LIBRARY
        const val INDEX = SearchReplay.INDEX
    }
}
