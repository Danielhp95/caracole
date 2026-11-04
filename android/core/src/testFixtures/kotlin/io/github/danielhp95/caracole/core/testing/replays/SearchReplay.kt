package io.github.danielhp95.caracole.core.testing.replays

import io.github.danielhp95.caracole.core.db.Database
import io.github.danielhp95.caracole.core.db.Db
import io.github.danielhp95.caracole.core.lacuerda.LaCuerda
import io.github.danielhp95.caracole.core.library.SongRow
import io.github.danielhp95.caracole.core.library.Songs
import io.github.danielhp95.caracole.core.names.SongNames
import io.github.danielhp95.caracole.core.search.ArtistHit
import io.github.danielhp95.caracole.core.search.IndexFound
import io.github.danielhp95.caracole.core.search.IndexHit
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
 * answered it, on the JVM (QueryTest, KeySearchTest, SearchUgTest, SuggestTest, SongNamesTest, SiteSearchTest and
 * LaCuerdaTest call these) and on the device
 * (CorpusOnDeviceTest):
 *
 * - [query]: query.jsonl's scoring seam (`_forms`, `_patterns`, `_pinyin_runs`, `_queries`, a `_Query`'s readings,
 *   score, name and holds, `_reading`, `_names_reading`), scores compared as doubles with ==; and [rowsLike], its
 *   `rows_like` records, each over its fixture;
 * - [library] and [index]: library.jsonl's and index.jsonl's answers over your songs and UG's index;
 * - [suggestArtists], [suggestTitles] and [suggestions]: suggest.jsonl's "Did you mean", a record with `kw.sites`
 *   "api" handed the other sites' answers /api/search hands it (as the corpus recorded them, else asked of :core);
 * - [names]: names.jsonl, song_names.py's `clean`, `clean_channel` and `read_names` (with no database, or over a
 *   fixture with its songs), SongNamesTest's;
 * - [sites]: sites.jsonl, search.py's other sites (gtptabs.com, MuseScore, harptabs.com, gametabs.net), SiteSearchTest's;
 * - [lacuerda]: lacuerda.jsonl, lacuerda_index.py's read side and search.py's LaCuerda glue, `lacuerda_leads` handed
 *   UG's answer as index.jsonl records Python's `find_index` of the query, LaCuerdaTest's.
 *
 * Each record of a fixture is answered over a fresh database with that fixture loaded (vectors/search/fixtures/), read
 * through Database.read as the phone reads it, in a temporary folder of its own, once a vector; answers compare whole
 * as helpers.corpus.plain wrote them ([diff]: objects as maps, arrays in order, numbers as doubles with ==).
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

    const val NAMES = "search/names.jsonl"
    const val CLEAN = "caracole.song_names.clean"
    const val CLEAN_CHANNEL = "caracole.song_names.clean_channel"
    const val READ_NAMES = "caracole.song_names.read_names"
    val NAMES_FNS = setOf(CLEAN, CLEAN_CHANNEL, READ_NAMES)

    const val SITES = "search/sites.jsonl"
    const val GTPTABS = "caracole.search.search_gtptabs"
    const val GTPTABS_SONGS = "caracole.search.gtptabs_songs"
    const val MUSESCORE = "caracole.search.search_musescore"
    const val HARPTABS = "caracole.search.search_harptabs"
    const val HARPTABS_ARTIST = "caracole.search.harptabs_artist"
    const val HARPTABS_SONGS = "caracole.search.harptabs_songs"
    const val GAMETABS = "caracole.search.search_gametabs"
    val SITES_FNS = setOf(GTPTABS, GTPTABS_SONGS, MUSESCORE, HARPTABS, HARPTABS_ARTIST, HARPTABS_SONGS, GAMETABS)

    const val LACUERDA = "search/lacuerda.jsonl"
    const val LC_FIND = "caracole.lacuerda_index.find"
    const val LC_SEARCH = "caracole.search.search_lacuerda"
    const val LC_LEADS = "caracole.search.lacuerda_leads"
    const val LC_ARTIST = "caracole.search.lacuerda_artist"
    const val LC_SONGS = "caracole.search.lacuerda_songs"
    const val LC_ARTIST_NAMED = "caracole.search.lacuerda_artist_named"
    const val LC_LEFT_OUT = "caracole.search.lacuerda_left_out"
    const val LC_LETTERS_READ = "caracole.lacuerda_index.letters_read"
    val LACUERDA_FNS = setOf(LC_FIND, LC_SEARCH, LC_LEADS, LC_ARTIST, LC_SONGS, LC_ARTIST_NAMED, LC_LEFT_OUT,
                             LC_LETTERS_READ)

    override fun replay(misses: Misses) {
        for (fn in QUERY_FNS) query(fn, misses)
        rowsLike(misses)
        library(misses)
        index(misses)
        suggestArtists(misses)
        suggestTitles(misses)
        suggestions(api = false, misses = misses)
        suggestions(api = true, misses = misses)
        names(misses)
        sites(misses)
        lacuerda(misses)
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

    // --- names.jsonl ------------------------------------------------------------------------------------------------

    /** names.jsonl's records of [fns]: `clean` and `clean_channel` of a text, `read_names` with no database and no
     * songs, or over its fixture with the fixture's songs (`songs.list_songs`), a name an [artist, title] pair. */
    fun names(misses: Misses, fns: Set<String> = NAMES_FNS) {
        var songs: Pair<Db, List<SongRow>>? = null
        fun songsOf(db: Db): List<SongRow> = songs?.takeIf { it.first === db }?.second
            ?: Songs.list(db).also { songs = db to it }
        vector(NAMES, fns, misses) { db, r ->
            val text = r.args[0].jsonPrimitive.content
            when (r.fn) {
                CLEAN -> JsonPrimitive(SongNames.clean(text))
                CLEAN_CHANNEL -> JsonPrimitive(SongNames.cleanChannel(text))
                READ_NAMES -> {
                    val read = if (db == null) SongNames.readNames(null, text, emptyList(), r.string("channel"))
                    else SongNames.readNames(db, text, songsOf(db), r.string("channel"))
                    read?.let { (artist, title) -> JsonArray(listOf(JsonPrimitive(artist), JsonPrimitive(title))) } ?: JsonNull
                }
                else -> throw IllegalStateException("not a record of $NAMES: ${r.fn}")
            }
        }
    }

    // --- sites.jsonl ------------------------------------------------------------------------------------------------

    /** sites.jsonl's records of [fns]: search.py's searches of gtptabs.com's, MuseScore's, harptabs.com's and
     * gametabs.net's indexes, and an artist's of harptabs.com, over each fixture. */
    fun sites(misses: Misses, fns: Set<String> = SITES_FNS) = vector(SITES, fns, misses) { db, r ->
        db!!
        val q = r.args[0].jsonPrimitive.content
        when (r.fn) {
            GTPTABS -> hits(SiteSearch.searchGtptabs(db, q, r.int("limit") ?: 5))
            GTPTABS_SONGS -> JsonPrimitive(SiteSearch.gtptabsSongs(db, q))
            MUSESCORE -> hits(SiteSearch.searchMusescore(db, q, r.int("limit") ?: 5))
            HARPTABS -> {
                val (artists, songs) = SiteSearch.searchHarptabs(db, q, r.int("songs") ?: 5, r.int("artists") ?: 3)
                JsonArray(listOf(JsonArray(artists.map { it.toJson() }), hits(songs)))
            }
            HARPTABS_ARTIST -> SiteSearch.harptabsArtist(db, q)?.toJson() ?: JsonNull
            HARPTABS_SONGS -> hits(SiteSearch.harptabsSongs(db, q, r.string("title")))
            GAMETABS -> hits(SiteSearch.searchGametabs(db, q, r.int("limit") ?: 5))
            else -> throw IllegalStateException("not a record of $SITES: ${r.fn}")
        }
    }

    private fun hits(hits: List<SiteHit>): JsonElement = JsonArray(hits.map { it.toJson() })

    // --- lacuerda.jsonl ---------------------------------------------------------------------------------------------

    /** lacuerda.jsonl's records of [fns] over each fixture: LaCuerda's index found, searched, leading UG's answer (as
     * index.jsonl records Python's `find_index` of the query, so that it is checked apart from Search), an artist, their
     * songs, an artist by name, what the index leaves out and the letters it read whole. */
    fun lacuerda(misses: Misses, fns: Set<String> = LACUERDA_FNS) = vector(LACUERDA, fns, misses) { db, r ->
        db!!
        val q = r.args.firstOrNull()?.jsonPrimitive?.content.orEmpty()
        when (r.fn) {
            LC_FIND -> LaCuerda.find(db, q, r.int("artists") ?: 3, r.int("songs") ?: 5).toJson()
            LC_SEARCH -> {
                val (artists, songs) = LaCuerda.searchLacuerda(db, q, r.int("songs") ?: 5, r.int("artists") ?: 3)
                JsonArray(listOf(JsonArray(artists.map { it.toJson() }), JsonArray(songs.map { it.toJson() })))
            }
            LC_LEADS -> {
                val ug = UG_FOUND.getValue(r.extra.getValue("fixture").jsonPrimitive.content to q)
                JsonPrimitive(LaCuerda.lacuerdaLeads(ug, LaCuerda.searchLacuerda(db, q).first))
            }
            LC_ARTIST -> LaCuerda.lacuerdaArtist(db, q)?.toJson() ?: JsonNull
            LC_SONGS -> JsonArray(LaCuerda.lacuerdaSongs(db, q, r.string("title")).map { it.toJson() })
            LC_ARTIST_NAMED -> LaCuerda.lacuerdaArtistNamed(db, q)?.toJson() ?: JsonNull
            LC_LEFT_OUT -> LaCuerda.lacuerdaLeftOut(db)?.let { JsonArray(listOf(JsonPrimitive(it.first), JsonPrimitive(it.second))) }
                ?: JsonNull
            LC_LETTERS_READ -> JsonArray(LaCuerda.letters(db).map { JsonPrimitive(it) })
            else -> throw IllegalStateException("not a record of $LACUERDA: ${r.fn}")
        }
    }

    /** Python's find_index of each fixture's queries (index.jsonl), by (fixture, query): what `lacuerda_leads` is
     * handed. */
    private val UG_FOUND: Map<Pair<String, String>, IndexFound> by lazy {
        Corpus.records(INDEX).filter { it.fn == FIND_INDEX && it.kw.isEmpty() }.associate {
            (it.extra.getValue("fixture").jsonPrimitive.content to it.args[0].jsonPrimitive.content) to
                indexFound(it.out!!.jsonObject)
        }
    }

    private fun indexFound(o: JsonObject) = IndexFound(
        artists = o.getValue("artists").jsonArray.map { artistHit(it.jsonObject) },
        songs = o.getValue("songs").jsonArray.map { indexHit(it.jsonObject) },
        lead = o.textOrNull("lead"),
        best = (o["best"] as? JsonObject)?.let { indexHit(it) },
    )

    private fun artistHit(o: JsonObject) = ArtistHit(
        o.text("artist_key"), o.text("artist"), o.getValue("score").jsonPrimitive.double, o.getValue("songs").jsonPrimitive.int,
        o.getValue("tabs").jsonPrimitive.int, o.getValue("top").jsonArray.map { indexHit(it.jsonObject) }, o.text("page"),
        o.getValue("part").jsonPrimitive.boolean,
    )

    private fun indexHit(o: JsonObject) = IndexHit(
        o.text("artist_key"), o.text("song_key"),
        LinkedHashMap(o.getValue("counts").jsonObject.mapValues { it.value.jsonPrimitive.int }),
        o.getValue("score").jsonPrimitive.double, o.text("url"), o.getValue("labels").jsonArray.map { it.jsonPrimitive.content },
        o.text("artist"), o.text("title"), o.text("via"), o.getValue("rating").jsonPrimitive.doubleOrNull,
        o.getValue("votes").jsonPrimitive.int, o.text("page"),
    )

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
