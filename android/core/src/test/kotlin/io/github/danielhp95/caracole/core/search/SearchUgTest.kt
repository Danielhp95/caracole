package io.github.danielhp95.caracole.core.search

import io.github.danielhp95.caracole.core.db.Database
import io.github.danielhp95.caracole.core.db.Db
import io.github.danielhp95.caracole.core.library.Songs
import io.github.danielhp95.caracole.core.testing.Corpus
import io.github.danielhp95.caracole.core.testing.Fixtures
import io.github.danielhp95.caracole.core.testing.Record
import io.github.danielhp95.caracole.core.testing.TestDb
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.booleanOrNull
import kotlinx.serialization.json.doubleOrNull
import kotlinx.serialization.json.int
import kotlinx.serialization.json.jsonPrimitive
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import java.io.File
import kotlin.test.assertEquals
import kotlin.test.assertNull
import kotlin.test.assertTrue
import kotlin.test.fail

/**
 * search.py's answers over your songs and UG's index, against vectors/search/library.jsonl and index.jsonl: each
 * record's call over its fixture (vectors/search/fixtures/<name>.jsonl) replayed into a fresh database, as Python ran
 * it (tests/test_conformance_search.py, whose docstring names each composed record). Every answer compares whole, as
 * helpers.corpus.plain wrote it (a song as its key), numbers as doubles with ==.
 */
class SearchUgTest {
    @get:Rule val tmp = TemporaryFolder()

    @Test fun everyRecordOfTheLibraryVectorIsWhatSearchPyAnswers() =
        SearchVectors.replay(tmp, LIBRARY, setOf(SEARCH_LIBRARY, SEARCH_REMOVED, LIBRARY_BY_ARTIST)) { db, r -> library(db!!, r) }

    @Test fun everyRecordOfTheIndexVectorIsWhatSearchPyAnswers() = SearchVectors.replay(
        tmp, INDEX, setOf(FIND_INDEX, FOUND, BARE_ID_HINT, BARE_ID_UNSEEN, INDEX_ARTIST, ARTIST_SONGS, NO_ONES),
    ) { db, r -> index(db, r) }

    @Test fun bothVectorsHoldEveryFunctionThisLanePorts() {
        val fns = (Corpus.records(LIBRARY) + Corpus.records(INDEX)).map { it.fn }.toSet()
        assertEquals(setOf(SEARCH_LIBRARY, SEARCH_REMOVED, LIBRARY_BY_ARTIST, FIND_INDEX, FOUND, BARE_ID_HINT,
                           BARE_ID_UNSEEN, INDEX_ARTIST, ARTIST_SONGS, NO_ONES), fns)
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

    private fun library(db: Db, r: Record): JsonElement {
        val q = r.args[0].jsonPrimitive.content
        return when (r.fn) {
            SEARCH_LIBRARY -> JsonArray(Search.searchLibrary(db, q, r.int("limit") ?: 10, r.string("reading")).map { it.toJson() })
            SEARCH_REMOVED -> JsonArray(Search.searchRemoved(db, q, r.int("limit") ?: 10).map { it.toJson() })
            LIBRARY_BY_ARTIST -> JsonArray(Search.libraryByArtist(Songs.list(db), q, r.string("artist_key")).map { JsonPrimitive(it.key) })
            else -> error("not a record of $LIBRARY: ${r.fn}")
        }
    }

    private fun index(db: Db?, r: Record): JsonElement {
        val q = r.args[0].jsonPrimitive.content
        if (r.fn == NO_ONES) return JsonPrimitive(Search.noOnes(q))
        db!!
        fun hits(): List<Any> = Search.findIndex(db, q).let { it.songs + it.artists }
        return when (r.fn) {
            FIND_INDEX -> Search.findIndex(db, q, r.int("artists") ?: 3, r.int("songs") ?: 8, r.string("reading")).toJson()
            FOUND -> Search.found(Search.searchLibrary(db, q, 5), Search.findIndex(db, q)).toJson()
            BARE_ID_HINT -> Search.bareIdHint(q, hits(), r.string("artist"))?.let { JsonPrimitive(it) } ?: JsonNull
            BARE_ID_UNSEEN -> Search.bareIdUnseen(q, hits()) ?: JsonNull
            INDEX_ARTIST -> Search.indexArtist(db, q)?.toJson() ?: JsonNull
            ARTIST_SONGS -> Search.artistSongs(db, q, r.int("limit") ?: 50, r.int("offset") ?: 0, r.string("title")).let { (hits, n) ->
                JsonArray(listOf(JsonArray(hits.map { it.toJson() }), JsonPrimitive(n)))
            }
            else -> error("not a record of $INDEX: ${r.fn}")
        }
    }

    companion object {
        const val LIBRARY = "search/library.jsonl"
        const val INDEX = "search/index.jsonl"
        const val SEARCH_LIBRARY = "caracole.search.search_library"
        const val SEARCH_REMOVED = "caracole.search.search_removed"
        const val LIBRARY_BY_ARTIST = "caracole.search.library_by_artist"
        const val FIND_INDEX = "caracole.search.find_index"
        const val FOUND = "caracole.search.found"
        const val BARE_ID_HINT = "caracole.search.bare_id_hint"
        const val BARE_ID_UNSEEN = "caracole.search.bare_id_unseen"
        const val INDEX_ARTIST = "caracole.search.index_artist"
        const val ARTIST_SONGS = "caracole.search.artist_songs"
        const val NO_ONES = "caracole.search.no_ones"
    }
}

/** How the search lanes' tests replay a vector of search.py's answers over its fixtures. */
internal object SearchVectors {
    /** A record whose answer needs a port another lane has yet to land: [replay] fails it as one that "waits", never
     * passes or skips it. */
    class Waiting(message: String) : Exception(message)

    /** Every record of [vector] (its functions [fns], those [only] keeps) answered by [answer] over its fixture,
     * loaded once into a fresh database and read through Database.read as the phone reads; a record of no fixture
     * gets no database. Fails naming every record whose answer differs, with where; a record [answer] says is
     * [Waiting] fails as one that waits. */
    fun replay(tmp: TemporaryFolder, vector: String, fns: Set<String>, only: (Record) -> Boolean = { true },
               answer: (Db?, Record) -> JsonElement) {
        val records = Corpus.records(vector).filter { it.fn in fns && only(it) }
        assertTrue(records.isNotEmpty(), "$vector has no record of $fns")
        val wrong = ArrayList<String>()
        val pending = ArrayList<String>()
        for ((fixture, group) in records.groupBy { it.fixture() }) {
            if (fixture == null) {
                group.forEach { check(it, null, answer, wrong, pending) }
                continue
            }
            withFixture(tmp, fixture) { database ->
                database.read { db -> group.forEach { check(it, db, answer, wrong, pending) } }
            }
        }
        wrong.addAll(pending.map { "waits: $it" })
        if (wrong.isNotEmpty()) fail("${wrong.size} of ${records.size} records of $vector differ:\n" + wrong.take(25).joinToString("\n"))
    }

    /** A fresh database with the search fixture [name] loaded, for [block]. */
    fun <T> withFixture(tmp: TemporaryFolder, name: String, block: (Database) -> T): T {
        val dir = tmp.newFolder()
        return TestDb.fresh(dir).use { database ->
            database.writeBlocking { db -> Fixtures.load(db, "search/fixtures/$name.jsonl", File(dir, "library")) }
            block(database)
        }
    }

    private fun check(r: Record, db: Db?, answer: (Db?, Record) -> JsonElement, wrong: MutableList<String>,
                      waiting: MutableList<String>) {
        val where = "${r.fn.substringAfterLast('.')} ${r.fixture()} ${r.args} ${r.kw}"
        if (r.err != null) {
            val raised = try {
                answer(db, r)
                null
            } catch (e: Exception) {
                e::class.simpleName
            }
            if (raised == null) wrong.add("$where: Python raised ${r.err}, Kotlin answered")
            return
        }
        try {
            val actual = answer(db, r)
            diff(r.out ?: JsonNull, actual, "")?.let { wrong.add("$where: $it") }
        } catch (e: Waiting) {
            waiting.add("$where: ${e.message}")
        } catch (e: Exception) {
            wrong.add("$where: ${e::class.simpleName}: ${e.message}")
        } catch (e: NotImplementedError) {
            wrong.add("$where: ${e.message}")
        }
    }

    /** Where Python's answer and Kotlin's first differ, or null when they agree: objects as maps, arrays in order,
     * numbers as doubles with ==. */
    fun diff(python: JsonElement, kotlin: JsonElement, at: String): String? {
        fun differs() = "at '$at' Python ${clip(python)}, Kotlin ${clip(kotlin)}"
        return when {
            python is JsonNull || kotlin is JsonNull -> if (python is JsonNull && kotlin is JsonNull) null else differs()
            python is JsonObject && kotlin is JsonObject -> {
                if (python.keys != kotlin.keys) return "at '$at' keys ${python.keys} against ${kotlin.keys}"
                python.keys.firstNotNullOfOrNull { diff(python.getValue(it), kotlin.getValue(it), "$at.$it") }
            }
            python is JsonArray && kotlin is JsonArray -> {
                if (python.size != kotlin.size) return "${differs()} (${python.size} items against ${kotlin.size})"
                python.indices.firstNotNullOfOrNull { diff(python[it], kotlin[it], "$at[$it]") }
            }
            python is JsonPrimitive && kotlin is JsonPrimitive -> when {
                python.isString || kotlin.isString -> if (python.isString == kotlin.isString && python.content == kotlin.content) null else differs()
                python.booleanOrNull != null || kotlin.booleanOrNull != null -> if (python.booleanOrNull == kotlin.booleanOrNull) null else differs()
                else -> if (python.doubleOrNull != null && python.doubleOrNull == kotlin.doubleOrNull) null else differs()
            }
            else -> differs()
        }
    }

    private fun clip(e: JsonElement): String = e.toString().let { if (it.length > 400) it.take(400) + "…" else it }

    private fun Record.fixture(): String? = (extra["fixture"] as? JsonPrimitive)?.takeIf { it.isString }?.content
}

internal fun Record.int(name: String): Int? = (kw[name] as? JsonPrimitive)?.takeUnless { it is JsonNull }?.int

internal fun Record.string(name: String): String? = (kw[name] as? JsonPrimitive)?.takeIf { it.isString }?.content

internal fun Record.bool(name: String): Boolean? = (kw[name] as? JsonPrimitive)?.booleanOrNull
