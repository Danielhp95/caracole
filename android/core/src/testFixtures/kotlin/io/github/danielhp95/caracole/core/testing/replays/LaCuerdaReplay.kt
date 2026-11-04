package io.github.danielhp95.caracole.core.testing.replays

import io.github.danielhp95.caracole.core.config.PhoneConfig
import io.github.danielhp95.caracole.core.db.Db
import io.github.danielhp95.caracole.core.html.Html
import io.github.danielhp95.caracole.core.http.LaCuerdaParseError
import io.github.danielhp95.caracole.core.index.Reads
import io.github.danielhp95.caracole.core.index.Stamps
import io.github.danielhp95.caracole.core.json.PyJson
import io.github.danielhp95.caracole.core.lacuerda.LaCuerda
import io.github.danielhp95.caracole.core.lacuerda.LaCuerdaArtist
import io.github.danielhp95.caracole.core.lacuerda.LaCuerdaPages
import io.github.danielhp95.caracole.core.lacuerda.LaCuerdaSearch
import io.github.danielhp95.caracole.core.lacuerda.LaCuerdaSearchAnswer
import io.github.danielhp95.caracole.core.lacuerda.LaCuerdaSearchSong
import io.github.danielhp95.caracole.core.lacuerda.LaCuerdaSong
import io.github.danielhp95.caracole.core.lacuerda.SearchGate
import io.github.danielhp95.caracole.core.py.PyCodec
import io.github.danielhp95.caracole.core.py.PyUrl
import io.github.danielhp95.caracole.core.testing.AreaReplay
import io.github.danielhp95.caracole.core.testing.Corpus
import io.github.danielhp95.caracole.core.testing.Fixtures
import io.github.danielhp95.caracole.core.testing.Misses
import io.github.danielhp95.caracole.core.testing.Record
import io.github.danielhp95.caracole.core.testing.Scenarios
import io.github.danielhp95.caracole.core.testing.TestDb
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.boolean
import kotlinx.serialization.json.int
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import kotlinx.serialization.json.long
import java.nio.file.Files
import java.time.Instant

/**
 * LaCuerda's pages, its index writers and its own search (vectors/sites/lacuerda_pages.jsonl, lacuerda_store.jsonl,
 * vectors/lookup/lacuerda_gate.jsonl, lacuerda_search.jsonl; tests/test_conformance_lacuerda_lookups.py) answered by
 * core.lacuerda as Python answered them. LaCuerdaPagesTest and LaCuerdaSearchTest call each part on the JVM;
 * CorpusOnDeviceTest runs them all under ART. Lane lacuerda-sheets adds its sheets' records after these.
 *
 * The phone notes each page a store writes for the next push to the computer (kv `phone:read:lacuerda:<page>`, the
 * store's `at`), which Python doesn't: checked here, and left out of the kv compared with Python's.
 */
object LaCuerdaReplay : AreaReplay {
    override val area = "lacuerda"

    /** Phase A guard: core.html is lane html-tree's, and until it merges a page can't be parsed; the records that
     * parse a page wait on it (waiting on html-tree). */
    val htmlReady: Boolean by lazy { runCatching { Html.parse("<p>") }.isSuccess }

    override fun replay(misses: Misses) {
        pages(misses)
        store(misses)
        gate(misses)
        search(misses)
    }

    // --- what a record holds ---------------------------------------------------------------------------------

    private fun str(s: String?): JsonElement = s?.let { JsonPrimitive(it) } ?: JsonNull

    fun song(s: LaCuerdaSong): JsonObject = JsonObject(linkedMapOf(
        "slug" to str(s.slug), "title" to str(s.title), "types" to str(s.types),
        "ranking" to JsonArray(s.ranking.map { JsonPrimitive(it) }), "lcd" to str(s.lcd),
    ))

    fun artist(a: LaCuerdaArtist): JsonObject = JsonObject(linkedMapOf(
        "slug" to str(a.slug), "name" to str(a.name), "songs" to JsonPrimitive(a.songs),
    ))

    fun answer(a: LaCuerdaSearchAnswer): JsonObject = JsonObject(linkedMapOf(
        "songs" to JsonArray(a.songs.map { s ->
            JsonObject(linkedMapOf("artist_slug" to str(s.artistSlug), "artist" to str(s.artist), "song" to song(s.song)))
        }),
        "artists" to JsonArray(a.artists.map { artist(it) }), "stated" to JsonPrimitive(a.stated),
    ))

    private fun songOf(o: JsonElement): LaCuerdaSong = o.jsonObject.let { s ->
        LaCuerdaSong(s.getValue("slug").jsonPrimitive.content, s.getValue("title").jsonPrimitive.content,
                     s.getValue("types").jsonPrimitive.content, s.getValue("ranking").jsonArray.map { it.jsonPrimitive.int },
                     s.getValue("lcd").jsonPrimitive.content)
    }

    private fun answerOf(o: JsonObject): LaCuerdaSearchAnswer = LaCuerdaSearchAnswer(
        songs = o.getValue("songs").jsonArray.map { s ->
            val f = s.jsonObject
            LaCuerdaSearchSong(f.getValue("artist_slug").jsonPrimitive.content, f.getValue("artist").jsonPrimitive.content,
                               songOf(f.getValue("song")))
        },
        artists = o.getValue("artists").jsonArray.map { a ->
            val f = a.jsonObject
            LaCuerdaArtist(f.getValue("slug").jsonPrimitive.content, f.getValue("name").jsonPrimitive.content,
                           f.getValue("songs").jsonPrimitive.long)
        },
        stated = o.getValue("stated").jsonPrimitive.long,
    )

    /** A page's text, as the parsers are handed it: `resp.text`. */
    private fun text(body: JsonElement): String = PyCodec.utf8Replace(Scenarios.body(body))

    /** What a parser answered, or its error's words as the record writes Python's. */
    private fun answered(compute: () -> JsonElement): JsonElement = try {
        compute()
    } catch (e: LaCuerdaParseError) {
        JsonObject(mapOf("err" to JsonPrimitive("LaCuerdaParseError: ${e.message}")))
    } catch (e: PyUrl.Invalid) {
        JsonObject(mapOf("err" to JsonPrimitive("ValueError: ${e.message}")))
    } catch (e: IllegalArgumentException) {
        JsonObject(mapOf("err" to JsonPrimitive("ValueError: ${e.message}")))
    }

    private fun want(r: Record): JsonElement = r.err?.let { JsonObject(mapOf("err" to JsonPrimitive(it))) } ?: (r.out ?: JsonNull)

    // --- the pages -------------------------------------------------------------------------------------------

    private const val PAGES = "sites/lacuerda_pages.jsonl"

    /** Every record of sites/lacuerda_pages.jsonl; the parsers' records only once core.html is there. */
    fun pages(misses: Misses = Misses(PAGES)) {
        var parsed = 0
        for (r in Corpus.records(PAGES)) {
            val case = r.extra["case"]?.jsonPrimitive?.content ?: ""
            val fn = r.fn.removePrefix("caracole.lacuerda.")
            val inputs = r.args.firstOrNull()
            if (fn in PARSERS) {
                val html = text(inputs!!)
                val url = r.kw["url"]?.takeUnless { it is JsonNull }?.jsonPrimitive?.content
                val got = try {
                    answered { parse(fn, html, url) }
                } catch (e: NotImplementedError) {
                    if (htmlReady) throw e
                    continue  // waiting on html-tree
                }
                parsed++
                misses.check(got == want(r)) { "$fn, $case: ${got.toString().take(400)}, Python's ${want(r).toString().take(400)}" }
                continue
            }
            val xs = inputs!!.jsonArray
            val outs = r.out!!.jsonArray
            val answers: List<JsonElement> = when (fn) {
                "match_title" -> {
                    val songs = xs.map { songOf(it) }
                    val cutoff = r.kw.getValue("cutoff").jsonPrimitive.content.toDouble()
                    r.args[1].jsonArray.map { t -> str(LaCuerdaPages.matchTitle(songs, t.jsonPrimitive.content, cutoff)?.slug) }
                }
                else -> xs.map { x -> answered { batch(fn, case, x) } }
            }
            misses.check(answers.size == outs.size) { "$fn, $case: ${answers.size} answers for ${outs.size}" }
            for ((i, got) in answers.withIndex()) {
                misses.check(got == outs.getOrNull(i)) { "$fn, $case, ${xs.getOrNull(i) ?: r.args[1].jsonArray[i]}: $got, Python's ${outs.getOrNull(i)}" }
            }
        }
        if (htmlReady) misses.check(parsed >= 100) { "$PAGES: $parsed pages parsed" }
    }

    private val PARSERS = setOf("parse_artist_page", "parse_popularity", "parse_artist_name", "is_missing_artist_page",
                                "parse_version_page", "parse_search")

    private fun parse(fn: String, html: String, url: String?): JsonElement = when (fn) {
        "parse_artist_page" -> JsonArray(LaCuerdaPages.parseArtistPage(html, url).map { song(it) })
        "parse_popularity" -> JsonArray(LaCuerdaPages.parsePopularity(html).map { (k, v) ->
            JsonArray(listOf(JsonPrimitive(k), JsonPrimitive(v)))
        })
        "parse_artist_name" -> str(LaCuerdaPages.parseArtistName(html))
        "is_missing_artist_page" -> JsonPrimitive(LaCuerdaPages.isMissingArtistPage(html))
        "parse_version_page" -> JsonPrimitive(LaCuerdaPages.parseVersionPage(html, url))
        "parse_search" -> answer(LaCuerdaPages.parseSearch(html, url))
        else -> throw AssertionError(fn)
    }

    private fun batch(fn: String, case: String, x: JsonElement): JsonElement = when (fn) {
        "parse_lcd" -> LaCuerdaPages.parseLcd(x.jsonPrimitive.content).let { (types, ranking) ->
            JsonArray(listOf(JsonPrimitive(types), JsonArray(ranking.map { JsonPrimitive(it) })))
        }
        "best_acordes_version" -> x.jsonArray.let { (types, ranking) ->
            val s = LaCuerdaSong("s", "t", types.jsonPrimitive.content, ranking.jsonArray.map { it.jsonPrimitive.int })
            LaCuerdaPages.bestAcordesVersion(s)?.let { JsonPrimitive(it) } ?: JsonNull
        }
        "search_words" -> JsonArray(LaCuerdaPages.searchWords(x.jsonPrimitive.content).map { JsonPrimitive(it) })
        "search_url" -> JsonPrimitive(LaCuerdaPages.searchUrl(x.jsonPrimitive.content, songsOnly = "general" !in case))
        "_language_counts" -> LaCuerdaPages.languageCounts(x.jsonPrimitive.content).let { (s, e, t) ->
            JsonArray(listOf(JsonPrimitive(s), JsonPrimitive(e), JsonPrimitive(t)))
        }
        "is_spanish" -> JsonPrimitive(LaCuerdaPages.isSpanish(x.jsonPrimitive.content))
        "looks_spanish" -> x.jsonArray.let { (title, lyrics) ->
            JsonPrimitive(LaCuerdaPages.looksSpanish(title.jsonPrimitive.content,
                                                     lyrics.takeUnless { it is JsonNull }?.jsonPrimitive?.content))
        }
        else -> throw AssertionError("no batch $fn")
    }

    // --- the store writers -----------------------------------------------------------------------------------

    private const val STORE = "sites/lacuerda_store.jsonl"

    /** Every record of sites/lacuerda_store.jsonl, each op in turn on its database; until core.html is there, a
     * record's ops up to the first that parses a page. */
    fun store(misses: Misses = Misses(STORE)) {
        for (r in Corpus.records(STORE)) {
            val case = r.extra.getValue("case").jsonPrimitive.content
            val ops = r.extra.getValue("ops").jsonArray.map { it.jsonObject }
            val outs = r.out!!.jsonArray
            withDb(r.extra["fixture"]) { db ->
                val noted = LinkedHashMap<String, String>()
                for ((i, op) in ops.withIndex()) {
                    val kind = op.getValue("op").jsonPrimitive.content
                    val at = op.getValue("at").jsonPrimitive.content
                    val kvBefore = kv(db)
                    val result: JsonElement = try {
                        when (kind) {
                            "store_songs" -> {
                                val popular = op["popular"]?.takeUnless { it is JsonNull }?.jsonObject
                                    ?.mapValues { it.value.jsonPrimitive.int }
                                LaCuerda.storeSongs(db, op.getValue("slug").jsonPrimitive.content,
                                                    op["name"]?.takeUnless { it is JsonNull }?.jsonPrimitive?.content,
                                                    op.getValue("songs").jsonArray.map { songOf(it) }, popular, at)
                                noted["${op.getValue("slug").jsonPrimitive.content}/"] = at
                                JsonNull
                            }
                            "store_artist_page" -> {
                                val slug = op.getValue("slug").jsonPrimitive.content
                                val stored = LaCuerda.storeArtistPage(db, slug, text(op.getValue("body")), at)
                                if (stored) noted["$slug/"] = at
                                JsonPrimitive(stored)
                            }
                            "store_search" -> {
                                val given = op["answer"]?.jsonObject?.let { answerOf(it) }
                                    ?: LaCuerdaPages.parseSearch(text(op.getValue("body")))
                                val n = LaCuerda.storeSearch(db, given, at)
                                if (n > 0) noted[LaCuerda.SEARCH_PAGE] = at
                                JsonPrimitive(n)
                            }
                            else -> throw AssertionError(kind)
                        }
                    } catch (e: NotImplementedError) {
                        if (htmlReady) throw e
                        return@withDb  // waiting on html-tree: the ops after this one stand on it
                    }
                    val want = outs[i].jsonObject
                    val what = "$case, op ${i + 1} ($kind)"
                    misses.check(result == want["result"]) { "$what: $result, Python's ${want["result"]}" }
                    val rows = want.getValue("rows")
                    if (rows !is JsonNull) {
                        val got = rows(db, "lacuerda_index")
                        misses.check(got == rows) { "$what: lacuerda_index holds $got, Python's $rows" }
                    }
                    val kvAfter = kv(db)
                    val changed = (kvBefore.keys + kvAfter.keys).filter { !it.startsWith(Reads.READ) && kvBefore[it] != kvAfter[it] }
                        .sorted().associateWith { k -> kvAfter[k]?.let { JsonPrimitive(it) } ?: JsonNull }
                    misses.check(JsonObject(changed) == want["kv"]) { "$what: kv $changed, Python's ${want["kv"]}" }
                    misses.check(notes(db) == noted) { "$what: the pages noted ${notes(db)}, the stores' $noted" }
                }
            }
        }
    }

    private fun notes(db: Db): Map<String, String> = kv(db).filterKeys { it.startsWith("${Reads.READ}${LaCuerda.SITE}:") }
        .mapKeys { it.key.removePrefix("${Reads.READ}${LaCuerda.SITE}:") }

    // --- the gate --------------------------------------------------------------------------------------------

    private const val GATE = "lookup/lacuerda_gate.jsonl"

    /** Every record of lookup/lacuerda_gate.jsonl. */
    fun gate(misses: Misses = Misses(GATE)) {
        for (r in Corpus.records(GATE)) {
            val case = r.extra["case"]?.jsonPrimitive?.content ?: ""
            val fn = r.fn.removePrefix("caracole.lacuerda_search.")
            if (fn == "query_key") {
                val xs = r.args[0].jsonArray
                for ((i, q) in xs.withIndex()) {
                    val got = LaCuerdaSearch.queryKey(q.jsonPrimitive.content)
                    misses.check(JsonPrimitive(got) == r.out!!.jsonArray[i]) { "query_key($q) = $got, Python's ${r.out!!.jsonArray[i]}" }
                }
                continue
            }
            withDb(r.extra["fixture"]) { db ->
                when (fn) {
                    "gate" -> {
                        val q = r.kw.getValue("query").jsonPrimitive.content
                        val got = gateOf(LaCuerdaSearch.gate(config(r.kw.getValue("provider").jsonObject), db, q,
                                                             r.kw.getValue("strong").jsonPrimitive.boolean,
                                                             instant(r.kw.getValue("now"))), q)
                        misses.check(got == (r.out ?: JsonNull)) { "gate, $case: $got, Python's ${r.out}" }
                    }
                    "record_failure", "_forget_failure" -> {
                        val key = r.kw.getValue("key").jsonPrimitive.content
                        val now = instant(r.kw.getValue("now"))
                        if (fn == "record_failure") {
                            LaCuerdaSearch.recordFailure(db, key, now, r.kw.getValue("error").jsonPrimitive.content)
                        } else {
                            LaCuerdaSearch.forgetFailure(db, key, now)
                        }
                        val got = str(db.kvGet(LaCuerdaSearch.FAILED_KEY))
                        val want = r.out!!.jsonObject.getValue("kv")
                        misses.check(got == want) { "$fn, $case: $got, Python's $want" }
                    }
                    "searches_used" -> {
                        val got = LaCuerdaSearch.searchesUsed(db, instant(r.kw.getValue("now")))
                        misses.check(JsonPrimitive(got) == r.out) { "searches_used, $case: $got, Python's ${r.out}" }
                    }
                    "answered" -> {
                        val qs = r.args[0].jsonArray
                        for ((i, q) in qs.withIndex()) {
                            val got = LaCuerdaSearch.answered(db, q.jsonPrimitive.content)
                            misses.check(JsonPrimitive(got) == r.out!!.jsonArray[i]) { "answered($q) = $got, Python's ${r.out!!.jsonArray[i]}" }
                        }
                    }
                    else -> throw AssertionError("no gate record $fn")
                }
            }
        }
    }

    private fun config(settings: JsonObject): PhoneConfig {
        val base = PhoneConfig.DEFAULTS
        val p = base.provider(LaCuerdaSearch.PROVIDER).copy(
            enabled = settings.getValue("enabled").jsonPrimitive.boolean,
            lookupRequests = settings.getValue("lookup_requests").jsonPrimitive.int,
            lookupPerHour = settings.getValue("lookup_per_hour").jsonPrimitive.int,
        )
        return base.copy(providers = base.providers + (LaCuerdaSearch.PROVIDER to p))
    }

    fun gateOf(g: LaCuerdaSearch.Gate?, query: String): JsonElement {
        if (g == null) return JsonNull
        val route = SearchGate.of(query, g)!!
        return JsonObject(linkedMapOf(
            "state" to str(g.state), "key" to str(g.key), "asked" to (g.asked ?: JsonNull),
            "failure" to (g.failure?.let { f ->
                JsonObject(linkedMapOf("own" to JsonPrimitive(f.own), "count" to JsonPrimitive(f.count),
                                       "error" to str(f.error), "until" to str(Stamps.isoformat(f.until))))
            } ?: JsonNull),
            "route" to JsonObject(linkedMapOf<String, JsonElement>(
                "state" to str(route.state), "query" to str(route.query), "key" to str(route.key),
            ).also { m -> route.why?.let { m["why"] = str(it) } }),
        ))
    }

    // --- the search ------------------------------------------------------------------------------------------

    private const val SEARCH = "lookup/lacuerda_search.jsonl"

    /** Every scenario of lookup/lacuerda_search.jsonl; those that parse a page only once core.html is there. */
    fun search(misses: Misses = Misses(SEARCH)) {
        for (line in Corpus.lines(SEARCH)) {
            if (line["header"] == JsonPrimitive(true)) continue
            val q = line.getValue("kw").jsonObject.getValue("query").jsonPrimitive.content
            try {
                Scenarios.replay(line, misses) { world ->
                    val got = LaCuerdaSearch.search(world.db, world.clients.getValue("lacuerda"), q, world.now)
                    val wanted = if (got.songs.isNotEmpty() || got.artists.isNotEmpty()) {
                        mapOf(LaCuerda.SEARCH_PAGE to Stamps.of(world.now))
                    } else emptyMap()
                    misses.check(notes(world.db) == wanted) { "${line["case"]}: the pages noted ${notes(world.db)}, $wanted" }
                    world.db.execute("DELETE FROM kv WHERE key >= ? AND key < ?", Reads.READ, Reads.READ.dropLast(1) + ";")
                    answer(got)
                }
            } catch (e: NotImplementedError) {
                if (htmlReady) throw e  // waiting on html-tree otherwise
            }
        }
    }

    // --- a database ------------------------------------------------------------------------------------------

    private fun instant(e: JsonElement): Instant = Instant.parse(e.jsonPrimitive.content)

    /** [block] over a fresh database holding the record's fixture. */
    private fun withDb(fixture: JsonElement?, block: (Db) -> Unit) {
        val dir = Files.createTempDirectory("caracole-lacuerda").toFile()
        try {
            TestDb.fresh(dir).use { database ->
                database.writeBlocking { db ->
                    Fixtures.loadRecords(db, (fixture as? JsonArray ?: JsonArray(emptyList())).map { it.jsonObject })
                    block(db)
                }
            }
        } finally {
            dir.deleteRecursively()
        }
    }

    private fun kv(db: Db): Map<String, String> =
        db.query("SELECT key, value FROM kv ORDER BY key") { it.text(0)!! to it.text(1)!! }.toMap()

    private fun quoted(name: String) = "\"" + name.replace("\"", "\"\"") + "\""

    /** A table's rows in rowid order, as dump_fixture reads them. */
    private fun rows(db: Db, table: String): JsonArray {
        val columns = db.query("PRAGMA main.table_info(${quoted(table)})") { it.text(1)!! }
        val select = columns.joinToString(", ") { "typeof(${quoted(it)}), ${quoted(it)}" }
        return JsonArray(db.query("SELECT $select FROM ${quoted(table)} ORDER BY rowid") { row ->
            val values = LinkedHashMap<String, JsonElement>()
            columns.forEachIndexed { i, column ->
                values[column] = when (val type = row.text(2 * i)) {
                    "null" -> JsonNull
                    "integer" -> JsonPrimitive(row.long(2 * i + 1)!!)
                    "real" -> PyJson.float(row.double(2 * i + 1)!!)
                    "text" -> JsonPrimitive(row.text(2 * i + 1)!!)
                    else -> error("$table holds a $type")
                }
            }
            JsonObject(values)
        })
    }
}
