package io.github.danielhp95.caracole.core.testing.replays

import io.github.danielhp95.caracole.core.db.Database
import io.github.danielhp95.caracole.core.db.Db
import io.github.danielhp95.caracole.core.lacuerda.LaCuerda
import io.github.danielhp95.caracole.core.library.Songs
import io.github.danielhp95.caracole.core.search.KeySearch
import io.github.danielhp95.caracole.core.search.Queries
import io.github.danielhp95.caracole.core.search.Query
import io.github.danielhp95.caracole.core.search.Reading
import io.github.danielhp95.caracole.core.search.Readings
import io.github.danielhp95.caracole.core.search.Search
import io.github.danielhp95.caracole.core.search.SiteArtist
import io.github.danielhp95.caracole.core.search.SiteHit
import io.github.danielhp95.caracole.core.search.Suggest
import io.github.danielhp95.caracole.core.sites.SiteSearch
import io.github.danielhp95.caracole.core.testing.AreaReplay
import io.github.danielhp95.caracole.core.testing.Corpus
import io.github.danielhp95.caracole.core.testing.Fixtures
import io.github.danielhp95.caracole.core.testing.Misses
import io.github.danielhp95.caracole.core.testing.Record
import io.github.danielhp95.caracole.core.testing.TestDb
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.boolean
import kotlinx.serialization.json.booleanOrNull
import kotlinx.serialization.json.double
import kotlinx.serialization.json.doubleOrNull
import kotlinx.serialization.json.int
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import java.io.File
import java.nio.file.Files

/**
 * The search vectors (vectors/search/, tests/test_conformance_search.py), every record answered by :core as Python
 * answered it, on the JVM (QueryTest, KeySearchTest, SearchUgTest, SuggestTest call these) and on the device
 * (CorpusOnDeviceTest):
 *
 * - [query]: query.jsonl's scoring seam (`_forms`, `_patterns`, `_pinyin_runs`, `_queries`, a `_Query`'s readings,
 *   score, name and holds, `_reading`, `_names_reading`), scores compared as doubles with ==; and [rowsLike], its
 *   `rows_like` records, each over its fixture;
 * - [library] and [index]: library.jsonl's and index.jsonl's answers over your songs and UG's index;
 * - [suggestArtists], [suggestTitles] and [suggestions]: suggest.jsonl's "Did you mean", a record with `kw.sites`
 *   "api" handed the other sites' answers /api/search hands it (as the corpus recorded them, else asked of :core).
 *
 * Each record of a fixture is answered over a fresh database with that fixture loaded (vectors/search/fixtures/), read
 * through Database.read as the phone reads it, in a temporary folder of its own; answers compare whole as
 * helpers.corpus.plain wrote them ([diff]: objects as maps, arrays in order, numbers as doubles with ==).
 */
object SearchReplay : AreaReplay {
    override val area = "search"

    const val QUERY_VECTOR = "search/query.jsonl"
    const val LIBRARY = "search/library.jsonl"
    const val INDEX = "search/index.jsonl"
    const val SUGGEST = "search/suggest.jsonl"

    const val FORMS = "caracole.search._forms"
    const val PATTERNS = "caracole.search._patterns"
    const val PINYIN_RUNS = "caracole.search._pinyin_runs"
    const val QUERIES = "caracole.search._queries"
    const val QUERY = "caracole.search._Query"
    const val READING = "caracole.search._reading"
    const val NAMES_READING = "caracole.search._names_reading"
    const val ROWS_LIKE = "caracole.ug.key_search.rows_like"
    val QUERY_FNS = listOf(FORMS, PATTERNS, PINYIN_RUNS, QUERIES, QUERY, READING, NAMES_READING)

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
    val LIBRARY_FNS = setOf(SEARCH_LIBRARY, SEARCH_REMOVED, LIBRARY_BY_ARTIST)
    val INDEX_FNS = setOf(FIND_INDEX, FOUND, BARE_ID_HINT, BARE_ID_UNSEEN, INDEX_ARTIST, ARTIST_SONGS, NO_ONES)

    const val SUGGEST_ARTISTS = "caracole.search.suggest_artists"
    const val SUGGEST_TITLES = "caracole.search.suggest_titles"
    const val SUGGESTIONS = "caracole.search.suggestions"

    override fun replay(misses: Misses) {
        for (fn in QUERY_FNS) query(fn, misses)
        rowsLike(misses)
        library(misses)
        index(misses)
        suggestArtists(misses)
        suggestTitles(misses)
        suggestions(api = false, misses = misses)
        suggestions(api = true, misses = misses)
    }

    // --- query.jsonl ------------------------------------------------------------------------------------------------

    /** query.jsonl's records of [fn], each Python's answer to the same call of the scoring seam. */
    fun query(fn: String, misses: Misses) {
        val records = Corpus.records(QUERY_VECTOR).filter { it.fn == fn }
        misses.check(records.isNotEmpty()) { "$QUERY_VECTOR has no record of $fn" }
        for (r in records) {
            misses.check(r.err == null) { "Python raised on $r" }
            val wrong = try {
                when (fn) {
                    FORMS -> differs(r, strings(r.out!!), Queries.forms(r.args[0].jsonPrimitive.content))
                    PATTERNS -> differs(r, strings(r.out!!), Queries.patterns(strings(r.args[0])))
                    PINYIN_RUNS -> differs(r, strings(r.out!!), Queries.pinyinRuns(strings(r.args[0])))
                    QUERIES -> {
                        val expected = r.out!!.jsonArray.map {
                            val q = it.jsonObject
                            Triple(q.getValue("text").jsonPrimitive.content, q.getValue("compact").jsonPrimitive.content,
                                   strings(q.getValue("runs")))
                        }
                        differs(r, expected, Queries.of(r.args[0].jsonPrimitive.content).map { Triple(it.text, it.compact, it.runs) })
                    }
                    QUERY -> {
                        val (text, runs, artist, title) = r.args
                        val q = Query(text.jsonPrimitive.content, strings(runs))
                        val a = artist.jsonPrimitive.content
                        val t = title.jsonPrimitive.content
                        val out = r.out!!.jsonObject
                        val readings = out.getValue("readings").jsonArray.map { it.jsonPrimitive.double }
                        differs(r, Readings(readings[0], readings[1], readings[2]), q.readings(a, t))
                            ?: differs(r, out.getValue("score").jsonPrimitive.double, q.score(a, t))
                            ?: differs(r, out.getValue("name").jsonPrimitive.double, q.name(a))
                            ?: differs(r, out.getValue("holds").jsonPrimitive.boolean, q.holds(a, t))
                    }
                    READING -> {
                        val scores = r.args[0].jsonArray.map { triple ->
                            val (t, b, a) = triple.jsonArray.map { it.jsonPrimitive.double }
                            Readings(t, b, a)
                        }
                        differs(r, reading(r.out!!), Queries.reading(scores, textOrNull(r.kw.getValue("reading"))))
                    }
                    NAMES_READING -> {
                        val queries = Queries.of(r.args[0].jsonPrimitive.content)
                        val actual = Queries.namesReading(queries, strings(r.args[1]), r.args[2].jsonPrimitive.content,
                                                          textOrNull(r.kw.getValue("reading")))
                        differs(r, reading(r.out!!), actual)
                    }
                    else -> "no such function of the seam: $fn"
                }
            } catch (e: Exception) {
                "${r.args}: ${e::class.simpleName}: ${e.message}"
            }
            misses.check(wrong == null) { "$fn $wrong" }
        }
    }

    /** query.jsonl's functions: the seam's, and rows_like. */
    fun queryFunctions(): Set<String> = Corpus.records(QUERY_VECTOR).map { it.fn }.toSet()

    /** query.jsonl's `rows_like` records: each record's patterns over its fixture, rows and order alike. */
    fun rowsLike(misses: Misses) {
        val records = Corpus.records(QUERY_VECTOR).filter { it.fn == ROWS_LIKE }
        misses.check(records.isNotEmpty()) { "$QUERY_VECTOR has no rows_like record" }
        for ((fixture, group) in records.groupBy { it.extra.getValue("fixture").jsonPrimitive.content }) {
            withFixture(fixture) { database ->
                for (record in group) {
                    val patterns = record.args[0].jsonArray.map { it.jsonPrimitive.content }
                    val expected = record.out!!.jsonArray.map { row ->
                        val (artist, song, count) = row.jsonArray.map { it.jsonPrimitive }
                        Triple(artist.content, song.content, count.int)
                    }
                    val actual = database.read { db -> KeySearch.rowsLike(db, patterns) }
                    misses.check(actual == expected) { "rows_like $fixture $patterns: Python $expected, Kotlin $actual" }
                }
            }
        }
    }

    // --- library.jsonl and index.jsonl ---------------------------------------------------------------------------

    /** library.jsonl: search_library, search_removed and library_by_artist over each fixture. */
    fun library(misses: Misses) = vector(LIBRARY, LIBRARY_FNS, misses) { db, r ->
        val q = r.args[0].jsonPrimitive.content
        db!!
        when (r.fn) {
            SEARCH_LIBRARY -> JsonArray(Search.searchLibrary(db, q, r.int("limit") ?: 10, r.string("reading")).map { it.toJson() })
            SEARCH_REMOVED -> JsonArray(Search.searchRemoved(db, q, r.int("limit") ?: 10).map { it.toJson() })
            LIBRARY_BY_ARTIST -> JsonArray(Search.libraryByArtist(Songs.list(db), q, r.string("artist_key")).map { JsonPrimitive(it.key) })
            else -> throw IllegalStateException("not a record of $LIBRARY: ${r.fn}")
        }
    }

    /** index.jsonl: find_index, found, the bare-id hint, index_artist, artist_songs and no_ones over each fixture. */
    fun index(misses: Misses) = vector(INDEX, INDEX_FNS, misses) { db, r ->
        val q = r.args[0].jsonPrimitive.content
        if (r.fn == NO_ONES) return@vector JsonPrimitive(Search.noOnes(q))
        db!!
        fun hits(): List<Any> = Search.findIndex(db, q).let { it.songs + it.artists }
        when (r.fn) {
            FIND_INDEX -> Search.findIndex(db, q, r.int("artists") ?: 3, r.int("songs") ?: 8, r.string("reading")).toJson()
            FOUND -> Search.found(Search.searchLibrary(db, q, 5), Search.findIndex(db, q)).toJson()
            BARE_ID_HINT -> Search.bareIdHint(q, hits(), r.string("artist"))?.let { JsonPrimitive(it) } ?: JsonNull
            BARE_ID_UNSEEN -> Search.bareIdUnseen(q, hits()) ?: JsonNull
            INDEX_ARTIST -> Search.indexArtist(db, q)?.toJson() ?: JsonNull
            ARTIST_SONGS -> Search.artistSongs(db, q, r.int("limit") ?: 50, r.int("offset") ?: 0, r.string("title"))
                .let { (hits, n) -> JsonArray(listOf(JsonArray(hits.map { it.toJson() }), JsonPrimitive(n))) }
            else -> throw IllegalStateException("not a record of $INDEX: ${r.fn}")
        }
    }

    // --- suggest.jsonl ----------------------------------------------------------------------------------------------

    fun suggestArtists(misses: Misses) = vector(SUGGEST, setOf(SUGGEST_ARTISTS), misses) { db, r ->
        val q = r.args[0].jsonPrimitive.content
        JsonArray(Suggest.suggestArtists(db!!, q, r.int("limit") ?: 3, r.bool("lacuerda") ?: true, r.bool("harptabs") ?: true)
                      .map { it.toJson() })
    }

    fun suggestTitles(misses: Misses) = vector(SUGGEST, setOf(SUGGEST_TITLES), misses) { db, r ->
        val q = r.args[0].jsonPrimitive.content
        JsonArray(Suggest.suggestTitles(db!!, q, r.int("limit") ?: 3, r.bool("lacuerda") ?: true, r.bool("harptabs") ?: true,
                                        r.bool("gtptabs") ?: true).map { it.toJson() })
    }

    /** suggestions beside the index's answer alone ([api] false), or beside the other sites' answers too (`kw.sites`
     * "api", as /api/search hands them). */
    fun suggestions(api: Boolean, misses: Misses) =
        vector(SUGGEST, setOf(SUGGESTIONS), misses, only = { (it.string("sites") == "api") == api }) { db, r ->
            val q = r.args[0].jsonPrimitive.content
            val sites = if (api) sites(db!!, r) else emptyList()
            JsonArray(Suggest.suggestions(db!!, q, Search.findIndex(db, q), sites, r.bool("lacuerda") ?: true,
                                          r.bool("harptabs") ?: true, r.bool("gtptabs") ?: true).map { it.toJson() })
        }

    /** search_routes' `_suggested` sites for the record's query: recorded, else asked of :core. */
    private fun sites(db: Db, r: Record): List<Any> {
        val fixture = r.extra.getValue("fixture").jsonPrimitive.content
        val q = r.args[0].jsonPrimitive.content
        RECORDED[fixture to q]?.let { return it }
        val (lcArtists, lcSongs) = LaCuerda.searchLacuerda(db, q, songs = 5)
        val (harpArtists, harpSongs) = SiteSearch.searchHarptabs(db, q, songs = 5)
        return lcArtists + lcSongs + SiteSearch.searchGtptabs(db, q, 5) + SiteSearch.searchMusescore(db, q, 5) +
            harpArtists + harpSongs
    }

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

    // --- how a vector of search.py's answers is replayed over its fixtures ------------------------------------------

    /**
     * Every record of [vector] (its functions [fns], those [only] keeps) answered by [answer] over its fixture, loaded
     * once into a fresh database and read through Database.read as the phone reads; a record of no fixture gets no
     * database. Each record whose answer differs is a miss, with where; one Python raised on must raise too.
     */
    fun vector(vector: String, fns: Set<String>, misses: Misses, only: (Record) -> Boolean = { true },
               answer: (Db?, Record) -> JsonElement) {
        val records = Corpus.records(vector).filter { it.fn in fns && only(it) }
        misses.check(records.isNotEmpty()) { "$vector has no record of $fns" }
        for ((fixture, group) in records.groupBy { it.fixture() }) {
            if (fixture == null) {
                group.forEach { check(it, null, answer, misses) }
                continue
            }
            withFixture(fixture) { database ->
                database.read { db -> group.forEach { check(it, db, answer, misses) } }
            }
        }
    }

    /** A fresh database with the search fixture [name] loaded, in a temporary folder of its own, for [block]. */
    fun <T> withFixture(name: String, block: (Database) -> T): T {
        val dir = Files.createTempDirectory("caracole-search").toFile()
        try {
            return TestDb.fresh(dir).use { database ->
                database.writeBlocking { db -> Fixtures.load(db, "search/fixtures/$name.jsonl", File(dir, "library")) }
                block(database)
            }
        } finally {
            dir.deleteRecursively()
        }
    }

    private fun check(r: Record, db: Db?, answer: (Db?, Record) -> JsonElement, misses: Misses) {
        val where = "${r.fn.substringAfterLast('.')} ${r.fixture()} ${r.args} ${r.kw}"
        if (r.err != null) {
            val raised = try {
                answer(db, r)
                false
            } catch (e: Exception) {
                true
            }
            misses.check(raised) { "$where: Python raised ${r.err}, Kotlin answered" }
            return
        }
        val wrong = try {
            diff(r.out ?: JsonNull, answer(db, r), "")
        } catch (e: Exception) {
            "${e::class.simpleName}: ${e.message}"
        } catch (e: NotImplementedError) {
            "${e.message}"
        }
        misses.check(wrong == null) { "$where: $wrong" }
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
                python.isString || kotlin.isString ->
                    if (python.isString == kotlin.isString && python.content == kotlin.content) null else differs()
                python.booleanOrNull != null || kotlin.booleanOrNull != null ->
                    if (python.booleanOrNull == kotlin.booleanOrNull) null else differs()
                else -> if (python.doubleOrNull != null && python.doubleOrNull == kotlin.doubleOrNull) null else differs()
            }
            else -> differs()
        }
    }

    private fun clip(e: JsonElement): String = e.toString().let { if (it.length > 400) it.take(400) + "…" else it }

    private fun differs(record: Record, expected: Any?, actual: Any?): String? =
        if (expected == actual) null else "${record.args} ${record.kw}: Python $expected, Kotlin $actual"

    private fun strings(element: JsonElement): List<String> = element.jsonArray.map { it.jsonPrimitive.content }

    private fun textOrNull(element: JsonElement): String? =
        (element as? JsonPrimitive)?.takeUnless { it is JsonNull }?.content

    private fun reading(out: JsonElement): Reading {
        val (score, via) = out as JsonArray
        return Reading(score.jsonPrimitive.double, via.jsonPrimitive.content)
    }

    private fun Record.fixture(): String? = (extra["fixture"] as? JsonPrimitive)?.takeIf { it.isString }?.content
    private fun Record.int(name: String): Int? = (kw[name] as? JsonPrimitive)?.takeUnless { it is JsonNull }?.int
    private fun Record.string(name: String): String? = (kw[name] as? JsonPrimitive)?.takeIf { it.isString }?.content
    private fun Record.bool(name: String): Boolean? = (kw[name] as? JsonPrimitive)?.booleanOrNull
}
