package io.github.danielhp95.caracole.core.search

import io.github.danielhp95.caracole.core.search.internal.suggest.Close
import io.github.danielhp95.caracole.core.search.internal.suggest.Titles
import io.github.danielhp95.caracole.core.testing.Corpus
import io.github.danielhp95.caracole.core.testing.Misses
import io.github.danielhp95.caracole.core.testing.TestDb
import io.github.danielhp95.caracole.core.testing.replays.SearchReplay
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import kotlin.test.assertEquals
import kotlin.test.assertTrue

/**
 * search.py's "Did you mean" against vectors/search/suggest.jsonl: `suggest_artists`, `suggest_titles` and
 * `suggestions` of `find_index(conn, q)` over each record's fixture replayed into a fresh database, answers compared
 * whole (SearchReplay.vector).
 *
 * A record with `kw.sites` "api" hands `suggestions` the other sites' answers /api/search hands it: LaCuerda's,
 * gtptabs.com's, MuseScore's and harptabs.com's searches of the query (tests/test_conformance_search.py `_sites`),
 * read where the corpus recorded them for that fixture and query (vectors/search/lacuerda.jsonl and sites.jsonl, the
 * same calls), else asked of SiteSearch and LaCuerda. The records are SearchReplay's, which the device runs too.
 */
class SuggestTest {
    @get:Rule val tmp = TemporaryFolder()

    @Test fun everyArtistSuggestionIsWhatSearchPySuggests() =
        Misses("$VECTOR $SUGGEST_ARTISTS").also { SearchReplay.suggestArtists(it) }.assertNone()

    @Test fun everyTitleSuggestionIsWhatSearchPySuggests() =
        Misses("$VECTOR $SUGGEST_TITLES").also { SearchReplay.suggestTitles(it) }.assertNone()

    @Test fun everySuggestionBesideTheIndexsAnswerIsWhatSearchPySuggests() =
        Misses("$VECTOR $SUGGESTIONS").also { SearchReplay.suggestions(api = false, misses = it) }.assertNone()

    @Test fun everySuggestionBesideTheOtherSitesAnswersIsWhatSearchPySuggests() =
        Misses("$VECTOR $SUGGESTIONS, sites").also { SearchReplay.suggestions(api = true, misses = it) }.assertNone()

    @Test fun theVectorHoldsTheThreeFunctions() {
        assertEquals(setOf(SUGGEST_ARTISTS, SUGGEST_TITLES, SUGGESTIONS), Corpus.records(VECTOR).map { it.fn }.toSet())
    }

    @Test fun nothingIsSuggestedForChineseOrShortWordsAndAnEmptyIndexHasNothingToSuggest() {
        TestDb.fresh(tmp.root).use { database ->
            database.read { db ->
                for (q in listOf("", "ab cd", "宋冬野", "lynrd", "hotl califronia")) {
                    assertEquals(emptyList(), Suggest.suggestArtists(db, q), q)
                    assertEquals(emptyList(), Suggest.suggestTitles(db, q), q)
                    assertEquals(emptyList(), Suggest.suggestions(db, q, IndexFound()), q)
                }
            }
        }
    }

    @Test fun anArtistNamedWholeLeavesNoRoomForASuggestion() {
        val named = ArtistHit("lynyrd-skynyrd", "Lynyrd Skynyrd", 100.0, 1, 1)
        TestDb.fresh(tmp.root).use { database ->
            database.read { db ->
                assertEquals(emptyList(), Suggest.suggestions(db, "lynyrd skynyrd", IndexFound(listOf(named), emptyList(), "artist")))
                assertEquals(emptyList(), Suggest.suggestions(db, "lynrd", IndexFound(),
                                                              listOf(SiteHit("musescore", "Lynrd", "https://musescore.com/x", 100.0))))
            }
        }
    }

    @Test fun aWordTiedBetweenTwoWordsOfATitleIsHeldByTheLaterAsPythonsMaxOfPairsHoldsIt() {
        // _title_closeness's max(((score, i) …)): "abcdefgh" is 80 of both "abcdefq" and "abcdefghwxyz", and the second
        // is the one held: (12/19)² of the title, as Python answers.
        assertEquals(80.0 to 0.13296398891966757, Titles.titleCloseness(listOf("abcdefgh"), listOf("abcdefq", "abcdefghwxyz"), listOf("zz")))
        assertEquals(90.0 to 0.17728531855955676,
                     Titles.titleCloseness(listOf("abcdefgh", "zzzz"), listOf("abcdefq", "abcdefghwxyz"), listOf("zzzz", "yy")))
        assertEquals(null, Titles.titleCloseness(listOf("abcdefgh"), listOf("zz"), listOf("abcdefgh")))
        assertEquals(95.45454545454545, Close.closeness(listOf("lynrd", "ab"), listOf("lynyrd", "ab")))
        assertEquals(2.6923076923076925, Close.weighed(7, 5, "lynyrd-skynyrd"))
    }

    @Test fun theVocabularyReadsALetterOnceThenOnlyTheWordsAddedSinceInOrder() {
        TestDb.fresh(tmp.root).use { database ->
            database.writeBlocking { db ->
                for (t in listOf("bertles", "beatles", "zebra", "be")) db.execute("INSERT INTO ug_key_words(term) VALUES (?)", t)
                val words = Vocabulary.of(db)
                assertTrue(words === Vocabulary.of(db), "a database's words are kept by its file")
                assertEquals(listOf("beatles", "bertles"), words.among(db, "beatls"))
                for (t in listOf("beatlez", "beates", "bob")) db.execute("INSERT INTO ug_key_words(term) VALUES (?)", t)
                // A word added since goes among its length's in code point order; a word's lengths are two either side.
                assertEquals(listOf("be", "bob", "beates"), words.among(db, "beat"))
                assertEquals(listOf("beates", "beatles", "beatlez", "bertles"), words.among(db, "beatls"))
                assertEquals(listOf("beatls", "beatles", "beates"), Close.near(db, "beatls")) // the closest first, 80 or more
                assertEquals(listOf("abc"), Close.near(db, "abc"))
            }
        }
    }

    @Test fun aWordWhoseLettersRangeEndsInALoneSurrogateIsRefusedAsPythonRefusesToBindIt() {
        // chr(ord("\ud7ff") + 1) is a lone surrogate, which sqlite3 can't encode: UnicodeEncodeError in Python. No
        // query's word starts so (name_words drops U+D7FF), but U+D7FB's does, and finds nothing on an empty index.
        TestDb.fresh(tmp.root).use { database ->
            database.read { db ->
                kotlin.test.assertFailsWith<IllegalArgumentException> { Vocabulary().among(db, "\uD7FFabcd") }
                assertEquals(listOf("\uD7FBabcd"), Close.near(db, "\uD7FBabcd"))
            }
        }
    }

    companion object {
        const val VECTOR = SearchReplay.SUGGEST
        const val SUGGEST_ARTISTS = SearchReplay.SUGGEST_ARTISTS
        const val SUGGEST_TITLES = SearchReplay.SUGGEST_TITLES
        const val SUGGESTIONS = SearchReplay.SUGGESTIONS
    }
}
