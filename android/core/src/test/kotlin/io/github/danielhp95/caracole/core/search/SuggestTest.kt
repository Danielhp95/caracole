package io.github.danielhp95.caracole.core.search

import io.github.danielhp95.caracole.core.db.Db
import io.github.danielhp95.caracole.core.lacuerda.LaCuerda
import io.github.danielhp95.caracole.core.search.internal.suggest.Close
import io.github.danielhp95.caracole.core.search.internal.suggest.Titles
import io.github.danielhp95.caracole.core.sites.SiteSearch
import io.github.danielhp95.caracole.core.testing.Corpus
import io.github.danielhp95.caracole.core.testing.Record
import io.github.danielhp95.caracole.core.testing.TestDb
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.boolean
import kotlinx.serialization.json.double
import kotlinx.serialization.json.int
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import org.junit.Assume
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import kotlin.test.assertEquals
import kotlin.test.assertTrue

/**
 * search.py's "Did you mean" against vectors/search/suggest.jsonl: `suggest_artists`, `suggest_titles` and
 * `suggestions` of `find_index(conn, q)` over each record's fixture replayed into a fresh database, answers compared
 * whole (SearchVectors).
 *
 * A record with `kw.sites` "api" hands `suggestions` the other sites' answers /api/search hands it: LaCuerda's,
 * gtptabs.com's, MuseScore's and harptabs.com's searches of the query (tests/test_conformance_search.py `_sites`).
 * Those searches are other lanes' (search-sites, search-lacuerda), so this test reads them where the corpus recorded
 * them for that fixture and query (vectors/search/lacuerda.jsonl and sites.jsonl, the same calls), and asks
 * SiteSearch and LaCuerda for the rest: until those lanes land, those records wait, and the test says how many.
 */
class SuggestTest {
    @get:Rule val tmp = TemporaryFolder()

    private val pending = HashSet<String>()

    @Test fun everyArtistSuggestionIsWhatSearchPySuggests() =
        SearchVectors.replay(tmp, VECTOR, setOf(SUGGEST_ARTISTS)) { db, r ->
            val q = r.args[0].jsonPrimitive.content
            JsonArray(Suggest.suggestArtists(db!!, q, r.int("limit") ?: 3, r.bool("lacuerda") ?: true, r.bool("harptabs") ?: true)
                          .map { it.toJson() })
        }

    @Test fun everyTitleSuggestionIsWhatSearchPySuggests() =
        SearchVectors.replay(tmp, VECTOR, setOf(SUGGEST_TITLES)) { db, r ->
            val q = r.args[0].jsonPrimitive.content
            JsonArray(Suggest.suggestTitles(db!!, q, r.int("limit") ?: 3, r.bool("lacuerda") ?: true, r.bool("harptabs") ?: true,
                                            r.bool("gtptabs") ?: true).map { it.toJson() })
        }

    @Test fun everySuggestionBesideTheIndexsAnswerIsWhatSearchPySuggests() = SearchVectors.replay(
        tmp, VECTOR, setOf(SUGGESTIONS), only = { it.string("sites") == null },
    ) { db, r -> suggestions(db!!, r, emptyList()) }

    @Test fun everySuggestionBesideTheOtherSitesAnswersIsWhatSearchPySuggests() {
        SearchVectors.replay(tmp, VECTOR, setOf(SUGGESTIONS), only = { it.string("sites") == "api" }, waiting = pending) { db, r ->
            suggestions(db!!, r, sites(db, r))
        }
        Assume.assumeTrue("${pending.size} records wait for lanes search-sites and search-lacuerda: " +
                              pending.take(3).joinToString("; "), pending.isEmpty())
    }

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

    private fun suggestions(db: Db, r: Record, sites: List<Any>): JsonElement {
        val q = r.args[0].jsonPrimitive.content
        return JsonArray(Suggest.suggestions(db, q, Search.findIndex(db, q), sites, r.bool("lacuerda") ?: true,
                                             r.bool("harptabs") ?: true, r.bool("gtptabs") ?: true).map { it.toJson() })
    }

    /** search_routes' `_suggested` sites for the record's query: recorded, else asked of the other lanes' ports. */
    private fun sites(db: Db, r: Record): List<Any> {
        val fixture = r.extra.getValue("fixture").jsonPrimitive.content
        val q = r.args[0].jsonPrimitive.content
        val recorded = RECORDED[fixture to q]
        if (recorded != null) return recorded
        return try {
            val (lcArtists, lcSongs) = LaCuerda.searchLacuerda(db, q, songs = 5)
            val (harpArtists, harpSongs) = SiteSearch.searchHarptabs(db, q, songs = 5)
            lcArtists + lcSongs + SiteSearch.searchGtptabs(db, q, 5) + SiteSearch.searchMusescore(db, q, 5) + harpArtists + harpSongs
        } catch (e: NotImplementedError) {
            throw SearchVectors.Waiting("$fixture '$q': ${e.message}")
        }
    }

    companion object {
        const val VECTOR = "search/suggest.jsonl"
        const val SUGGEST_ARTISTS = "caracole.search.suggest_artists"
        const val SUGGEST_TITLES = "caracole.search.suggest_titles"
        const val SUGGESTIONS = "caracole.search.suggestions"

        /** The other sites' searches the corpus recorded, by fixture and query, in `_sites`' order. */
        private val RECORDED: Map<Pair<String, String>, List<Any>> by lazy {
            fun calls(vector: String, fn: String): Map<Pair<String, String>, JsonElement> =
                Corpus.records(vector).filter { it.fn == fn && it.kw.isEmpty() && it.err == null }
                    .associate { (it.extra.getValue("fixture").jsonPrimitive.content to it.args[0].jsonPrimitive.content) to it.out!! }
            val lacuerda = calls("search/lacuerda.jsonl", "caracole.search.search_lacuerda")
            val gtptabs = calls("search/sites.jsonl", "caracole.search.search_gtptabs")
            val musescore = calls("search/sites.jsonl", "caracole.search.search_musescore")
            val harptabs = calls("search/sites.jsonl", "caracole.search.search_harptabs")
            lacuerda.keys.filter { it in gtptabs && it in musescore && it in harptabs }.associateWith { key ->
                val (lcArtists, lcSongs) = lacuerda.getValue(key).jsonArray
                val (harpArtists, harpSongs) = harptabs.getValue(key).jsonArray
                lcArtists.jsonArray.map { siteArtist(it) } + lcSongs.jsonArray.map { siteHit(it) } +
                    gtptabs.getValue(key).jsonArray.map { siteHit(it) } + musescore.getValue(key).jsonArray.map { siteHit(it) } +
                    harpArtists.jsonArray.map { siteArtist(it) } + harpSongs.jsonArray.map { siteHit(it) }
            }
        }

        private fun JsonObject.text(name: String): String = getValue(name).jsonPrimitive.content
        private fun JsonObject.textOrNull(name: String): String? = (get(name) as? JsonPrimitive)?.takeIf { it.isString }?.content

        /** A SiteHit as helpers.corpus.plain wrote it (its tabs, which a suggestion never reads, left out). */
        fun siteHit(e: JsonElement): SiteHit = e.jsonObject.let {
            SiteHit(it.text("source"), it.text("title"), it.text("url"), it.getValue("score").jsonPrimitive.double,
                    it.text("artist"), it.text("artist_key"), it.text("title_key"), it.getValue("uploads").jsonPrimitive.int,
                    it.text("via"), it.textOrNull("sheet"), emptyList(), it.text("page"))
        }

        fun siteArtist(e: JsonElement): SiteArtist = e.jsonObject.let {
            SiteArtist(it.text("source"), it.text("artist"), it.text("slug"), it.text("url"),
                       it.getValue("score").jsonPrimitive.double, it.getValue("songs").jsonPrimitive.int,
                       it.getValue("known").jsonPrimitive.int, it.text("via"), it.getValue("top").jsonArray.map { t -> siteHit(t) },
                       it.getValue("part").jsonPrimitive.boolean, it.getValue("read").jsonPrimitive.boolean)
        }
    }
}
