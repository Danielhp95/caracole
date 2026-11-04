package io.github.danielhp95.caracole.core.testing.replays

import io.github.danielhp95.caracole.core.config.ProviderPolicy
import io.github.danielhp95.caracole.core.http.Client
import io.github.danielhp95.caracole.core.http.ProviderBlocked
import io.github.danielhp95.caracole.core.http.ProviderError
import io.github.danielhp95.caracole.core.http.Response
import io.github.danielhp95.caracole.core.json.PyJson
import io.github.danielhp95.caracole.core.library.Overrides
import io.github.danielhp95.caracole.core.library.LibraryStore
import io.github.danielhp95.caracole.core.library.PassStats
import io.github.danielhp95.caracole.core.lyrics.AzLyrics
import io.github.danielhp95.caracole.core.lyrics.AzLyricsStats
import io.github.danielhp95.caracole.core.lyrics.Lrclib
import io.github.danielhp95.caracole.core.lyrics.LyricsStats
import io.github.danielhp95.caracole.core.lyrics.Lyrics
import io.github.danielhp95.caracole.core.lyrics.Megalobiz
import io.github.danielhp95.caracole.core.lyrics.MegalobizStats
import io.github.danielhp95.caracole.core.lyrics.internal.PyValues
import io.github.danielhp95.caracole.core.py.PyFloat
import io.github.danielhp95.caracole.core.testing.AreaReplay
import io.github.danielhp95.caracole.core.testing.Corpus
import io.github.danielhp95.caracole.core.testing.Misses
import io.github.danielhp95.caracole.core.testing.Scenarios
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
import java.math.BigInteger
import java.time.Duration

/**
 * LRCLIB, Megalobiz and AZLyrics (tests/test_conformance_lyrics.py) replayed as Python recorded them:
 *
 * - vectors/sites/{lrclib,megalobiz,azlyrics}.jsonl: each parser's and picker's record over its fixture or the
 *   record's own JSON (a float a record writes as its repr), its answer or what it raised compared;
 * - vectors/lookup/{lrclib,megalobiz,azlyrics}.jsonl: each pass of a lookup's song in its record's world
 *   (core.testing.Scenarios: the requests in order, the rows, kv and files written, the events and the stats).
 *
 * LrclibTest, MegalobizTest and AzLyricsTest call each part on the JVM; CorpusOnDeviceTest runs them all under ART.
 */
object LyricsReplay : AreaReplay {
    override val area = "lyrics"

    const val LRCLIB_SITES = "sites/lrclib.jsonl"
    const val MEGALOBIZ_SITES = "sites/megalobiz.jsonl"
    const val AZLYRICS_SITES = "sites/azlyrics.jsonl"
    const val LRCLIB_LOOKUP = "lookup/lrclib.jsonl"
    const val MEGALOBIZ_LOOKUP = "lookup/megalobiz.jsonl"
    const val AZLYRICS_LOOKUP = "lookup/azlyrics.jsonl"

    override fun replay(misses: Misses) {
        lrclibSites(misses)
        megalobizSites(misses)
        azlyricsSites(misses)
        lrclibLookups(misses)
        megalobizLookups(misses)
        azlyricsLookups(misses)
    }

    /** The records of a vector, its header left out. */
    fun records(name: String): List<JsonObject> = Corpus.lines(name).filter { it["header"] != JsonPrimitive(true) }

    // --- what a record holds ----------------------------------------------------------------------------------------

    private fun str(e: JsonElement?): String = e!!.jsonPrimitive.content
    private fun strOrNull(e: JsonElement?): String? = if (e == null || e is JsonNull) null else e.jsonPrimitive.content

    /** A float a record writes as its repr (null: None). */
    private fun float(e: JsonElement?): Double? = strOrNull(e)?.let { PyFloat.parse(it) ?: error("not a float: $it") }

    private fun repr(x: Double?): JsonElement = x?.let { JsonPrimitive(PyValues.reprFloat(it)) } ?: JsonNull

    /** A JSON value as json.loads reads it: a fixture's bytes, or the record's own value read again as Python reads
     * the line (numbers in Python's forms). */
    private fun value(e: JsonElement): JsonElement {
        if (e is JsonObject && e.keys == setOf("fixture")) return PyJson.loads(Corpus.fixture(str(e["fixture"])))
        return PyJson.loads(e.toString())
    }

    private fun response(record: JsonObject): Response =
        Response(str(record["url"]), record.getValue("status").jsonPrimitive.int, Scenarios.body(record.getValue("body")),
                 emptyMap())

    private fun raised(e: Throwable): JsonObject =
        JsonObject(mapOf("type" to JsonPrimitive(e::class.simpleName), "message" to JsonPrimitive(e.message ?: "")))

    /** The record's answer, or what it raised, against what [call] gives (a throw is compared as `raises`). */
    private fun compare(misses: Misses, record: JsonObject, what: String, call: () -> JsonElement) {
        val got: JsonElement = try {
            JsonObject(mapOf("out" to call()))
        } catch (e: AssertionError) {
            throw e
        } catch (e: Exception) {
            JsonObject(mapOf("raises" to raised(e)))
        }
        val want = if ("raises" in record) JsonObject(mapOf("raises" to record.getValue("raises")))
                   else JsonObject(mapOf("out" to record.getValue("out")))
        misses.check(got == want) { "$what: got $got, Python's $want" }
    }

    private fun label(record: JsonObject) =
        str(record["fn"]) + (record["case"]?.let { " (${it.jsonPrimitive.content})" } ?: (record["args"]?.let { " $it" } ?: ""))

    // --- LRCLIB's parsers and pickers -------------------------------------------------------------------------------

    fun lrclibSites(misses: Misses) {
        for (record in records(LRCLIB_SITES)) {
            val kw = record["kw"]?.jsonObject
            when (str(record["fn"])) {
                "caracole.lyrics.Lyrics.from_record" -> compare(misses, record, label(record)) {
                    val lyrics = Lyrics.fromRecord(value(record.getValue("record")).jsonObject)
                    JsonObject(linkedMapOf(
                        "plain" to JsonPrimitive(lyrics.plain), "synced" to (lyrics.synced?.let(::JsonPrimitive) ?: JsonNull),
                        "instrumental" to JsonPrimitive(lyrics.instrumental), "duration" to repr(lyrics.duration),
                        "lrclib_id" to (lyrics.lrclibId?.let(::JsonPrimitive) ?: JsonNull),
                        "to_json" to JsonPrimitive(lyrics.toJson()),
                    ))
                }
                "caracole.lyrics.fits" -> compare(misses, record, label(record)) {
                    val k = kw!!
                    val fit = Lrclib.fits(str(k["artist"]), str(k["title"]), float(k["duration_s"]), str(k["got_artist"]),
                                          str(k["got_title"]), float(k["got_duration"]))
                    fit?.let { JsonArray(listOf(JsonPrimitive(it.first), repr(it.second))) } ?: JsonNull
                }
                "caracole.lyrics.another_version" -> compare(misses, record, label(record)) {
                    val args = record.getValue("args").jsonArray
                    JsonPrimitive(Lrclib.anotherVersion(str(args[0]), str(args[1])))
                }
                "caracole.lyrics._search_title" -> compare(misses, record, label(record)) {
                    JsonPrimitive(Lrclib.searchTitle(str(record.getValue("args").jsonArray[0])))
                }
                "caracole.lyrics.pick_candidate" -> compare(misses, record, label(record)) {
                    val cands = value(record.getValue("cands")).jsonArray
                    val k = kw!!
                    val best = Lrclib.pickCandidate(cands, str(k["artist"]), str(k["title"]), float(k["duration_s"]))
                    best?.let { b -> JsonPrimitive(cands.indexOfFirst { it === b }) } ?: JsonNull
                }
                "caracole.lyrics.read" -> compare(misses, record, label(record)) {
                    val resp = response(record)
                    if (str(record["read"]) == "get") Lrclib.getRecord(resp) ?: JsonNull else Lrclib.searchRecords(resp)
                }
                "caracole.lyrics.fetch_lyrics" -> fetchLyrics(misses, record)
                else -> misses.check(false) { "an LRCLIB record of no function the phone knows: ${record["fn"]}" }
            }
        }
    }

    /** lyrics.fetch_lyrics over [Replies], its calls compared beside its answer. */
    private fun fetchLyrics(misses: Misses, record: JsonObject) {
        val kw = record.getValue("kw").jsonObject
        val client = Replies(record["get"]?.takeIf { it !is JsonNull }?.jsonObject,
                             record["search"]?.takeIf { it !is JsonNull }?.jsonObject)
        compare(misses, record, label(record)) {
            val result = Lrclib.fetchLyrics(client, str(kw["artist"]), str(kw["title"]), strOrNull(kw["album"]),
                                            float(kw["duration_s"]), cache = kw["cache"]?.jsonPrimitive?.boolean ?: true)
            JsonObject(linkedMapOf("status" to JsonPrimitive(result.status),
                                   "lyrics" to (result.lyrics?.let { JsonPrimitive(it.toJson()) } ?: JsonNull)))
        }
        misses.check(JsonArray(client.calls) == record["calls"]) { "${label(record)}: calls ${client.calls}, Python's ${record["calls"]}" }
    }

    /** The test's Replies: each endpoint answered as the record says, a status not accepted a ProviderError, as
     * PoliteClient's; each call recorded. */
    private class Replies(get: JsonObject?, search: JsonObject?) : Client {
        private val replies = mapOf("${Lrclib.API}/get" to get, "${Lrclib.API}/search" to search)
        val calls = ArrayList<JsonElement>()
        override val provider = Lrclib.PROVIDER
        override var requestsMade = 0
        override var policy = ProviderPolicy(budget = 100, delay = 0.0 to 0.0)

        override fun get(url: String, params: List<Pair<String, String>>?, cache: Boolean, conditional: Boolean,
                         accept: Set<Int>, maxAge: Duration?): Response {
            calls += JsonObject(linkedMapOf(
                "url" to JsonPrimitive(url),
                "params" to JsonArray(params.orEmpty().map { (k, v) -> JsonArray(listOf(JsonPrimitive(k), JsonPrimitive(v))) }),
                "accept" to JsonArray(accept.sorted().map(::JsonPrimitive)), "cache" to JsonPrimitive(cache),
            ))
            val reply = replies[url] ?: throw AssertionError("unanswered: $url")
            val status = reply.getValue("status").jsonPrimitive.int
            if (status !in accept) throw ProviderError(provider, url, status, "status not accepted")
            requestsMade++
            return Response(url, status, Scenarios.body(reply.getValue("body")), emptyMap())
        }

        override fun cached(url: String, accept: Set<Int>): Response? = null
        override fun hasCached(url: String, accept: Set<Int>): Boolean = false
    }

    // --- Megalobiz's ------------------------------------------------------------------------------------------------

    private fun result(r: Megalobiz.Result): JsonObject = JsonObject(linkedMapOf(
        "id" to JsonPrimitive(r.id.toString()), "title" to JsonPrimitive(r.title), "artist" to JsonPrimitive(r.artist),
        "duration" to repr(r.duration), "url" to JsonPrimitive(r.url),
    ))

    fun megalobizSites(misses: Misses) {
        for (record in records(MEGALOBIZ_SITES)) {
            when (str(record["fn"])) {
                "caracole.megalobiz.search_params" -> compare(misses, record, label(record)) {
                    val args = record.getValue("args").jsonArray
                    JsonArray(Megalobiz.searchParams(str(args[0]), str(args[1]), float(args[2])).map { (k, v) ->
                        JsonArray(listOf(JsonPrimitive(k), JsonPrimitive(v)))
                    })
                }
                "caracole.megalobiz.lrc_url" -> compare(misses, record, label(record)) {
                    JsonPrimitive(Megalobiz.lrcUrl(BigInteger(str(record.getValue("args").jsonArray[0]))))
                }
                "caracole.megalobiz.parse_search" -> compare(misses, record, label(record)) {
                    JsonArray(Megalobiz.parseSearch(response(record)).map(::result))
                }
                "caracole.megalobiz.parse_lrc" -> compare(misses, record, label(record)) {
                    val lrc = Megalobiz.parseLrc(response(record))
                    JsonObject(result(Megalobiz.Result(lrc.id, lrc.title, lrc.artist, lrc.duration, lrc.url)) +
                                   ("lrc" to JsonPrimitive(lrc.lrc)))
                }
                "caracole.megalobiz.pick_result" -> compare(misses, record, label(record)) {
                    val results = record.getValue("results").jsonArray.map {
                        val r = it.jsonObject
                        Megalobiz.Result(BigInteger(str(r["id"])), str(r["title"]), str(r["artist"]), float(r["duration"]),
                                         str(r["url"]))
                    }
                    val kw = record.getValue("kw").jsonObject
                    val best = Megalobiz.pickResult(results, str(kw["artist"]), str(kw["title"]), float(kw["duration_s"]))
                    best?.let { b -> JsonPrimitive(results.indexOfFirst { it === b }) } ?: JsonNull
                }
                else -> misses.check(false) { "a Megalobiz record of no function the phone knows: ${record["fn"]}" }
            }
        }
    }

    // --- AZLyrics' --------------------------------------------------------------------------------------------------

    fun azlyricsSites(misses: Misses) {
        for (record in records(AZLYRICS_SITES)) {
            when (str(record["fn"])) {
                "caracole.azlyrics.artist_url" -> compare(misses, record, label(record)) {
                    AzLyrics.artistUrl(str(record.getValue("args").jsonArray[0]))?.let(::JsonPrimitive) ?: JsonNull
                }
                "caracole.azlyrics.parse_artist" -> compare(misses, record, label(record)) {
                    val page = AzLyrics.parseArtist(response(record))
                    JsonObject(linkedMapOf("name" to JsonPrimitive(page.name), "songs" to JsonArray(page.songs.map {
                        JsonArray(listOf(JsonPrimitive(it.title), JsonPrimitive(it.url)))
                    })))
                }
                "caracole.azlyrics.parse_lyrics" -> compare(misses, record, label(record)) {
                    JsonPrimitive(AzLyrics.parseLyrics(response(record)))
                }
                "caracole.azlyrics.pick_song" -> compare(misses, record, label(record)) {
                    val p = record.getValue("page").jsonObject
                    val page = AzLyrics.ArtistPage(str(p["name"]), p.getValue("songs").jsonArray.map {
                        AzLyrics.SongLink(str(it.jsonArray[0]), str(it.jsonArray[1]))
                    })
                    val kw = record.getValue("kw").jsonObject
                    val best = AzLyrics.pickSong(page, str(kw["artist"]), str(kw["title"]))
                    best?.let { b -> JsonPrimitive(page.songs.indexOfFirst { it === b }) } ?: JsonNull
                }
                else -> misses.check(false) { "an AZLyrics record of no function the phone knows: ${record["fn"]}" }
            }
        }
    }

    // --- the passes -------------------------------------------------------------------------------------------------

    /** A pass's stats as the record holds them: the ladder's counts, each failure's song, class and words, and
     * the site's own counts ([extra]). */
    fun stats(s: PassStats, extra: Map<String, Int>): Map<String, Any?> = linkedMapOf<String, Any?>(
        "tried" to s.tried, "errors" to s.errors, "budget_exhausted" to s.budgetExhausted,
        "failures" to s.failures.map { (song, e) -> listOf(song.id, e::class.simpleName, e.message) },
    ) + extra

    private fun only(kw: JsonObject): Set<Long> = kw.getValue("only").jsonArray.map { it.jsonPrimitive.long }.toSet()

    fun lrclibLookups(misses: Misses) {
        for (record in records(LRCLIB_LOOKUP)) {
            val kw = record.getValue("kw").jsonObject
            val durations = kw["durations"]?.jsonObject?.entries?.associate { (id, d) ->
                id.toLong() to d.jsonPrimitive.content.toDouble()
            }
            Scenarios.replay(record, misses) { world ->
                val s: LyricsStats = Lrclib.fetchPendingLyrics(world.db, world.clients.getValue("lrclib"),
                                                               LibraryStore(world.library), world.now, only(kw), durations)
                stats(s, linkedMapOf("found" to s.found, "missing" to s.missing, "instrumental" to s.instrumental))
            }
        }
    }

    fun megalobizLookups(misses: Misses) {
        for (record in records(MEGALOBIZ_LOOKUP)) {
            val kw = record.getValue("kw").jsonObject
            Scenarios.replay(record, misses) { world ->
                val s: MegalobizStats = Megalobiz.megalobizLyrics(world.db, world.clients.getValue("megalobiz"),
                                                                  LibraryStore(world.library), world.now, only(kw))
                stats(s, linkedMapOf("found" to s.found, "timed" to s.timed, "missing" to s.missing))
            }
        }
    }

    fun azlyricsLookups(misses: Misses) {
        for (record in records(AZLYRICS_LOOKUP)) {
            val kw = record.getValue("kw").jsonObject
            val asked = kw["cached"]?.jsonPrimitive?.content
            Scenarios.replay(record, misses) { world ->
                val client = world.clients.getValue("azlyrics")
                try {
                    val s: AzLyricsStats = AzLyrics.azlyricsLyrics(world.db, client, LibraryStore(world.library),
                                                                   world.now, Overrides.read(world.db), only(kw))
                    stats(s, linkedMapOf("found" to s.found, "missing" to s.missing))
                } catch (e: ProviderBlocked) {
                    // The block page's case: the block, and whether the client kept the page it blocked with.
                    if (asked == null) throw e
                    linkedMapOf("blocked" to raised(e), "cached" to client.hasCached(asked))
                }
            }
        }
    }
}
