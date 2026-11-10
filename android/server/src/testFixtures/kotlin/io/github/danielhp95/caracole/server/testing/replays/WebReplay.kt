package io.github.danielhp95.caracole.server.testing.replays

import io.github.danielhp95.caracole.core.db.Db
import io.github.danielhp95.caracole.core.json.PyJson
import io.github.danielhp95.caracole.core.library.LibraryStore
import io.github.danielhp95.caracole.core.py.PyText
import io.github.danielhp95.caracole.core.py.PyUrl
import io.github.danielhp95.caracole.core.sync.PeerClient
import io.github.danielhp95.caracole.core.sync.SyncEngine
import io.github.danielhp95.caracole.core.testing.AreaReplay
import io.github.danielhp95.caracole.core.testing.Corpus
import io.github.danielhp95.caracole.core.testing.Fixtures
import io.github.danielhp95.caracole.core.testing.Misses
import io.github.danielhp95.caracole.core.testing.Record
import io.github.danielhp95.caracole.core.web.DownloadNames
import io.github.danielhp95.caracole.core.web.Inline
import io.github.danielhp95.caracole.mirror.ServerAddress
import io.github.danielhp95.caracole.server.files.FileTypes
import io.github.danielhp95.caracole.server.http.App
import io.github.danielhp95.caracole.server.http.Body
import io.github.danielhp95.caracole.server.http.GetAnswer
import io.github.danielhp95.caracole.server.http.MessagePage
import io.github.danielhp95.caracole.server.http.PostAnswer
import io.github.danielhp95.caracole.server.http.Refused
import io.github.danielhp95.caracole.server.http.Request
import io.github.danielhp95.caracole.server.http.Response
import io.github.danielhp95.caracole.server.http.Route
import io.github.danielhp95.caracole.server.http.RouteModule
import io.github.danielhp95.caracole.server.http.Security
import io.github.danielhp95.caracole.server.jobs.JobQueue
import io.github.danielhp95.caracole.server.routes.SyncRoutes
import io.github.danielhp95.caracole.server.routes.SyncSettings
import io.github.danielhp95.caracole.server.testing.SearchApp
import io.github.danielhp95.caracole.server.testing.TestApp
import io.github.danielhp95.caracole.server.testing.WebJson
import io.github.danielhp95.caracole.server.testing.header
import io.github.danielhp95.caracole.server.testing.json
import io.github.danielhp95.caracole.server.testing.text
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Job
import kotlinx.coroutines.cancel
import kotlinx.serialization.json.Json
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
import java.io.BufferedInputStream
import java.io.File
import java.net.InetAddress
import java.net.ServerSocket
import java.net.Socket
import java.net.URLEncoder
import java.nio.file.Files
import java.time.ZoneOffset
import java.util.Base64
import java.util.concurrent.atomic.AtomicInteger
import kotlin.concurrent.thread

/**
 * M1–3's web vectors (vectors/web/, tests/test_conformance_web.py, test_conformance_search.py and
 * test_conformance_sync_routes.py), every record answered by :server as caracole serve answered it, on the JVM
 * (ApiSearchTest's records, OwnersTest, RoutingTest, SyncRoutesVectorsTest, SecurityTest and FileTypesTest's call
 * these) and on the
 * device (CorpusOnDeviceTest):
 *
 * - [apiSearch]: api_search.jsonl, /api/search and /api/artist over each search fixture, through the phone's App, the
 *   cards' members masked on both sides; and [owners], each site's row naming its song of yours, Python's answers
 *   over the fixtures and the songs [SONGS] adds;
 * - [routing]: routing.jsonl's requests, behind the launch's secret, each answer's status, headers and body; and
 *   [jsonAnswers], what every JSON answer and data block is written as;
 * - [syncRoutes]: sync_routes.jsonl, the Sync tab's routes over a fixture of the sync corpus and a computer answering
 *   its state as the record gives it (a server on 127.0.0.1 of the replay's own, so that the device runs it too);
 * - [downloads]: downloads.jsonl, files.py's kinds of file and download_names.py's names;
 * - [security]: security.jsonl, security.py's host, origin, own-page and token checks, and Python's `str.isdigit` and
 *   `str.isspace` over every code point (SecurityTest's).
 *
 * Each phone is a database of its own in a temporary folder. (job_views.jsonl and library_page.json are lanes
 * job-views' and requests-feed's.)
 */
object WebReplay : AreaReplay {
    override val area = "web"

    override fun replay(misses: Misses) {
        apiSearch(misses)
        owners(misses)
        routing(misses)
        jsonAnswers(misses)
        syncRoutes(misses)
        downloads(misses)
        security(misses)
    }

    // --- api_search.jsonl -------------------------------------------------------------------------------------------

    /** api_search.jsonl: each record's request asked through the App over its fixture, in the vectors' order. */
    fun apiSearch(misses: Misses) {
        val records = Corpus.records("web/api_search.jsonl")
        misses.check(records.size > 800) { "api_search.jsonl holds ${records.size} records" }
        for ((fixture, asked) in records.groupBy { it.extra.getValue("fixture").jsonPrimitive.content }) {
            inFolder("caracole-api-search") { dir ->
                SearchApp(dir, fixture).use { search ->
                    for (record in asked) {
                        misses.check(record.fn == "caracole.web.app.WebApp.handle") { "a record of ${record.fn}" }
                        val target = record.args[1].jsonPrimitive.content
                        val out = record.out!!.jsonObject
                        val response = search.app.get(target)
                        val status = out.getValue("status").jsonPrimitive.int
                        if (response.status != status) {
                            misses.check(false) { "$fixture $target: status ${response.status}, not $status" }
                            continue
                        }
                        misses.check(response.header("Content-Type") == "application/json; charset=utf-8") {
                            "$fixture $target: ${response.header("Content-Type")}"
                        }
                        val wrong = WebJson.difference(out.getValue("json"), WebJson.masked(response.json))
                        misses.check(wrong == null) { "$fixture $target: $wrong" }
                    }
                }
            }
        }
    }

    /** caracole serve's answers over [SONGS], [ownersOf] each: a site's rows' songs of yours. */
    fun owners(misses: Misses) {
        for ((fixture, asked) in ANSWERS.groupBy { it.first }) {
            inFolder("caracole-owners") { dir ->
                SearchApp(dir, fixture).use { search ->
                    search.app.database.writeBlocking { db -> for (sql in SONGS.getValue(fixture)) sql(db) }
                    for ((_, q, expected) in asked) {
                        val answer = search.app.get("/api/search?q=${URLEncoder.encode(q, "UTF-8")}&box=t")
                        if (answer.status != 200) {
                            misses.check(false) { "$fixture \"$q\": status ${answer.status}" }
                            continue
                        }
                        val wrong = WebJson.difference(Json.parseToJsonElement(expected),
                                                       ownersOf(WebJson.masked(answer.json).jsonObject))
                        misses.check(wrong == null) { "$fixture \"$q\": $wrong" }
                    }
                }
            }
        }
    }

    private const val STAMP = "2026-11-03T10:00:00Z"

    /** A song of yours, as the generator's INSERT writes it: added a minute after the one before. */
    private fun song(id: Int, artist: String, title: String, key: String, minute: Int, vararg more: Pair<String, String>):
        (Db) -> Unit = { db ->
        val columns = linkedMapOf<String, Any>(
            "id" to id, "key" to key, "artist" to artist, "title" to title,
            "artists" to JsonArray(listOf(JsonPrimitive(artist))).toString(),
            "added_at" to "2026-10-02T00:${minute.toString().padStart(2, '0')}:00Z", "created_at" to STAMP,
            "updated_at" to STAMP,
        )
        columns.putAll(more)
        db.execute("INSERT INTO songs (${columns.keys.joinToString()}) VALUES (${columns.keys.joinToString { "?" }})",
                   *columns.values.toTypedArray())
    }

    /** The songs of yours the owners' answers were made over: the search corpus's own fixtures hold none such. */
    val SONGS: Map<String, List<(Db) -> Unit>> = mapOf(
        "sites" to listOf(
            song(10, "Elton John", "Your Song", "elton-john/your-song", 1),
            song(11, "Beatles", "Yesterday", "beatles/yesterday", 2),
            song(12, "BillyJoel", "Piano Man", "billyjoel/piano-man", 3, "status" to "found"),
            song(13, "Moby", "Creep", "moby/creep", 4, "match_decision" to "accept", "match_artist_key" to "radiohead",
                 "match_song_key" to "creep"),
            song(14, "HollowKnight", "Resting Grounds", "hollowknight/resting-grounds", 5),
            song(15, "Lindsey Stirling", "The White Lady", "lindsey-stirling/white-lady", 6,
                 "match_decision" to "pinned", "match_artist_key" to "hollow-knight", "match_song_key" to "white-lady"),
            song(16, "Ben Folds", "Vienna", "ben-folds/vienna", 7, "match_decision" to "accept",
                 "match_artist_key" to "billy-joel", "match_song_key" to "vienna"),
            song(17, "StoneTemplePilots", "Creep", "stonetemplepilots/creep", 8),
        ),
        "lacuerda" to listOf(
            song(10, "SodaStereo", "Persiana Americana", "sodastereo/persiana-americana", 1),
            song(11, "Shakira", "Té para 3", "shakira/te-para-3", 2, "match_decision" to "pinned",
                 "match_artist_key" to "soda-stereo", "match_song_key" to "te-para-3"),
        ),
    )

    /** A row's song of yours (`song`, `same_artist`, `library`) beside its names; a row with no artist (a
     * harptabs.com tab by its title alone) whole. */
    private fun owner(row: JsonElement): JsonElement {
        val r = row.jsonObject
        if ("artist" !in r) return r
        return JsonObject(listOf("artist", "title", "song", "same_artist", "library").associateWith { r.getValue(it) })
    }

    /** What the owners' answers compare of an answer: each site's rows' owners, and those of each artist's most
     * tabbed. */
    fun ownersOf(answer: JsonObject): JsonObject {
        val out = LinkedHashMap<String, JsonElement>()
        for (site in listOf("index", "gtptabs", "harptabs", "gametabs", "lacuerda")) {
            out[site] = JsonArray(answer.getValue(site).jsonArray.map { owner(it) })
        }
        for (group in listOf("artists", "harptabs_artists", "lacuerda_artists")) {
            out[group] = JsonArray(answer.getValue(group).jsonArray.map { a ->
                JsonObject(mapOf("artist" to a.jsonObject.getValue("artist"),
                                 "top" to JsonArray(a.jsonObject.getValue("top").jsonArray.map { owner(it) })))
            })
        }
        return JsonObject(out)
    }

    /** caracole serve's answers, [ownersOf] each (the generator: WebApp.handle over the fixture and [SONGS]). */
    val ANSWERS = listOf(
        Triple("sites", "your song", """{"index":[{"artist":"Elton John","title":"Your Song","song":10,"same_artist":true,"library":{"id":10,"artist":"Elton John","title":"Your Song","display":"Elton John - Your Song","status":"wanted","links":"*"}}],"gtptabs":[{"artist":"Elton John","title":"Your Song","song":10,"same_artist":true,"library":{"id":10,"artist":"Elton John","title":"Your Song","display":"Elton John - Your Song","status":"wanted","links":"*"}}],"harptabs":[],"gametabs":[],"lacuerda":[],"artists":[],"harptabs_artists":[],"lacuerda_artists":[]}"""),
        Triple("sites", "yesterday", """{"index":[],"gtptabs":[{"artist":"Beatles","title":"Yesterday","song":11,"same_artist":true,"library":{"id":11,"artist":"Beatles","title":"Yesterday","display":"Beatles - Yesterday","status":"wanted","links":"*"}}],"harptabs":[{"artist":"the beatles","title":"yesterday","song":11,"same_artist":true,"library":{"id":11,"artist":"Beatles","title":"Yesterday","display":"Beatles - Yesterday","status":"wanted","links":"*"}},{"source":"harptabs","title":"Yesterday","url":"https://www.harptabs.com/tab/1999/yesterday","score":100.0}],"gametabs":[],"lacuerda":[],"artists":[],"harptabs_artists":[],"lacuerda_artists":[]}"""),
        Triple("sites", "piano man", """{"index":[{"artist":"Billy Joel","title":"Piano Man","song":12,"same_artist":true,"library":{"id":12,"artist":"BillyJoel","title":"Piano Man","display":"BillyJoel - Piano Man","status":"found","links":"*"}}],"gtptabs":[],"harptabs":[{"artist":"billy joel","title":"piano man","song":12,"same_artist":true,"library":{"id":12,"artist":"BillyJoel","title":"Piano Man","display":"BillyJoel - Piano Man","status":"found","links":"*"}},{"source":"harptabs","title":"Piano Man","url":"https://www.harptabs.com/tab/29525/piano-man","score":100.0}],"gametabs":[],"lacuerda":[],"artists":[],"harptabs_artists":[],"lacuerda_artists":[]}"""),
        Triple("sites", "creep", """{"index":[{"artist":"Radiohead","title":"Creep","song":13,"same_artist":false,"library":{"id":13,"artist":"Moby","title":"Creep","display":"Moby - Creep","status":"wanted","links":"*"}}],"gtptabs":[{"artist":"Radiohead","title":"Creep","song":13,"same_artist":false,"library":{"id":13,"artist":"Moby","title":"Creep","display":"Moby - Creep","status":"wanted","links":"*"}},{"artist":"Stone Temple Pilots","title":"Creep","song":17,"same_artist":true,"library":{"id":17,"artist":"StoneTemplePilots","title":"Creep","display":"StoneTemplePilots - Creep","status":"wanted","links":"*"}},{"artist":"Metallica","title":"Creeping Death","song":null,"same_artist":false,"library":null}],"harptabs":[],"gametabs":[],"lacuerda":[],"artists":[],"harptabs_artists":[],"lacuerda_artists":[]}"""),
        Triple("sites", "resting grounds", """{"index":[],"gtptabs":[],"harptabs":[],"gametabs":[{"artist":"Hollow Knight","title":"Resting Grounds","song":14,"same_artist":true,"library":{"id":14,"artist":"HollowKnight","title":"Resting Grounds","display":"HollowKnight - Resting Grounds","status":"wanted","links":"*"}}],"lacuerda":[],"artists":[],"harptabs_artists":[],"lacuerda_artists":[]}"""),
        Triple("sites", "white lady", """{"index":[],"gtptabs":[],"harptabs":[],"gametabs":[{"artist":"Hollow Knight","title":"The White Lady","song":15,"same_artist":false,"library":{"id":15,"artist":"Lindsey Stirling","title":"The White Lady","display":"Lindsey Stirling - The White Lady","status":"wanted","links":"*"}}],"lacuerda":[],"artists":[],"harptabs_artists":[],"lacuerda_artists":[]}"""),
        Triple("sites", "vienna", """{"index":[],"gtptabs":[],"harptabs":[{"artist":"billy joel","title":"Vienna!","song":16,"same_artist":false,"library":{"id":16,"artist":"Ben Folds","title":"Vienna","display":"Ben Folds - Vienna","status":"wanted","links":"*"}}],"gametabs":[],"lacuerda":[],"artists":[],"harptabs_artists":[],"lacuerda_artists":[]}"""),
        Triple("sites", "billy joel", """{"index":[],"gtptabs":[],"harptabs":[],"gametabs":[],"lacuerda":[],"artists":[{"artist":"Billy Joel","top":[{"artist":"Billy Joel","title":"Piano Man","song":12,"same_artist":true,"library":{"id":12,"artist":"BillyJoel","title":"Piano Man","display":"BillyJoel - Piano Man","status":"found","links":"*"}}]}],"harptabs_artists":[{"artist":"billy joel","top":[{"artist":"billy joel","title":"piano man","song":12,"same_artist":true,"library":{"id":12,"artist":"BillyJoel","title":"Piano Man","display":"BillyJoel - Piano Man","status":"found","links":"*"}},{"artist":"billy joel","title":"Vienna!","song":16,"same_artist":false,"library":{"id":16,"artist":"Ben Folds","title":"Vienna","display":"Ben Folds - Vienna","status":"wanted","links":"*"}},{"artist":"billy joel","title":"She's Always a Woman","song":null,"same_artist":false,"library":null}]}],"lacuerda_artists":[]}"""),
        Triple("sites", "the beatles", """{"index":[],"gtptabs":[{"artist":"Beatles","title":"Yesterday","song":11,"same_artist":true,"library":{"id":11,"artist":"Beatles","title":"Yesterday","display":"Beatles - Yesterday","status":"wanted","links":"*"}}],"harptabs":[],"gametabs":[],"lacuerda":[],"artists":[],"harptabs_artists":[{"artist":"the beatles","top":[{"artist":"the beatles","title":"yesterday","song":11,"same_artist":true,"library":{"id":11,"artist":"Beatles","title":"Yesterday","display":"Beatles - Yesterday","status":"wanted","links":"*"}}]}],"lacuerda_artists":[]}"""),
        Triple("lacuerda", "persiana americana", """{"index":[],"gtptabs":[],"harptabs":[],"gametabs":[],"lacuerda":[{"artist":"Soda Stereo","title":"Persiana Americana","song":10,"same_artist":true,"library":{"id":10,"artist":"SodaStereo","title":"Persiana Americana","display":"SodaStereo - Persiana Americana","status":"wanted","links":"*"}}],"artists":[],"harptabs_artists":[],"lacuerda_artists":[]}"""),
        Triple("lacuerda", "te para 3", """{"index":[],"gtptabs":[],"harptabs":[],"gametabs":[],"lacuerda":[{"artist":"Soda Stereo","title":"Té para 3","song":11,"same_artist":false,"library":{"id":11,"artist":"Shakira","title":"Té para 3","display":"Shakira - Té para 3","status":"wanted","links":"*"}}],"artists":[],"harptabs_artists":[],"lacuerda_artists":[]}"""),
        Triple("lacuerda", "soda stereo", """{"index":[],"gtptabs":[],"harptabs":[],"gametabs":[],"lacuerda":[],"artists":[],"harptabs_artists":[],"lacuerda_artists":[{"artist":"Soda Stereo","top":[{"artist":"Soda Stereo","title":"De Música Ligera","song":null,"same_artist":false,"library":null},{"artist":"Soda Stereo","title":"Persiana Americana","song":10,"same_artist":true,"library":{"id":10,"artist":"SodaStereo","title":"Persiana Americana","display":"SodaStereo - Persiana Americana","status":"wanted","links":"*"}},{"artist":"Soda Stereo","title":"Té para 3","song":11,"same_artist":false,"library":{"id":11,"artist":"Shakira","title":"Té para 3","display":"Shakira - Té para 3","status":"wanted","links":"*"}}]}]}"""),
    )

    // --- routing.jsonl ----------------------------------------------------------------------------------------------

    private val routingRecords: List<Record> get() = Corpus.records("web/routing.jsonl")

    private fun setup(records: List<Record>): JsonObject = records.first().also { check(it.fn == "routes") }.out!!.jsonObject

    /** The vector's routes, each answering as test_conformance_web.py's ANSWERS say. */
    private fun vectorRoutes(setup: JsonObject, app: () -> App): RouteModule = object : RouteModule {
        override val routes = setup.getValue("routes").jsonArray.map { it.jsonObject }.map { spec ->
            val method = spec.getValue("method").jsonPrimitive.content
            val path = spec.getValue("path").jsonPrimitive.content
            fun answer(request: Request, form: Map<String, String>?): Response =
                when (spec.getValue("answer").jsonPrimitive.content) {
                    "echo" -> app().json(JsonObject(buildMap {
                        put("route", JsonPrimitive(path))
                        put("method", JsonPrimitive(request.method))
                        if (form != null) put("form", JsonObject(form.mapValues { JsonPrimitive(it.value) }))
                    }))
                    "page" -> Response(200, Body.Bytes("<!doctype html>\n<p>page</p>\n".toByteArray()), mutableListOf(
                        "Content-Type" to "text/html; charset=utf-8", "Content-Security-Policy" to "default-src 'none'"))
                    "refuse" -> throw Refused(409, "Not here yet", "That isn't here yet.")
                    "kept" -> Response(200, Body.Bytes("kept\n".toByteArray()), mutableListOf(
                        "Content-Type" to "text/plain; charset=utf-8", "Cache-Control" to "max-age=60",
                        "x-frame-options" to "SAMEORIGIN"))
                    "queued" -> app().queued(JsonObject(mapOf("id" to JsonPrimitive(7), "state" to JsonPrimitive("queued"))))
                    else -> throw IllegalStateException("no such answer: $spec")
                }
            Route(method, path, "the vector's ${spec["answer"]}", under = spec.getValue("under").jsonPrimitive.boolean,
                  scriptOnly = spec.getValue("script_only").jsonPrimitive.boolean,
                  page = spec.getValue("page").jsonPrimitive.content,
                  get = if (method == "GET") GetAnswer { answer(it, null) } else null,
                  post = if (method == "POST") PostAnswer { request, form -> answer(request, form) } else null)
        }
    }

    private object None : RouteModule {
        override val routes = emptyList<Route>()
    }

    /** routing.jsonl's requests, each answered as WebApp.handle answered it: its status, headers and body, the
     * message pages' style put back where the vector marks it. */
    fun routing(misses: Misses) {
        val records = routingRecords
        val setup = setup(records)
        lateinit var built: App
        inFolder("caracole-routing") { dir ->
            TestApp(dir, { listOf(vectorRoutes(setup) { built }) }, stubs = None, csrf = setup.getValue("csrf").jsonPrimitive.content,
                    allowed = setup.getValue("allowed").jsonArray.map { it.jsonPrimitive.content }.toSet(),
                    libraryName = setup.getValue("library_name").jsonPrimitive.content).use { test ->
                built = test.app
                misses.check(MessagePage.PHONE_BADGE == setup.getValue("badge").jsonPrimitive.content) {
                    "the badge ${MessagePage.PHONE_BADGE}, Python's ${setup["badge"]}"
                }
                val requests = records.filter { it.fn == "caracole.web.app.WebApp.handle" }
                misses.check(requests.size > 100) { "routing.jsonl holds ${requests.size} requests" }
                val mark = "<style>${setup.getValue("style_mark").jsonPrimitive.content}</style>"
                val style = "<style>${MessagePage.style}</style>"
                for (record in requests) {
                    val asked = record.args[0].jsonObject
                    val headers = asked.getValue("headers").jsonObject.mapValues { it.value.jsonPrimitive.content } +
                        ("cookie" to "${Security.SECRET_COOKIE}=${test.secret}")
                    val response = test.handle(Request(asked.getValue("method").jsonPrimitive.content,
                                                       asked.getValue("target").jsonPrimitive.content, headers, body(asked)))
                    val out = record.out!!.jsonObject
                    val expected = Triple(out.getValue("status").jsonPrimitive.content.toInt(),
                                          out.getValue("headers").jsonArray.map { h -> h.jsonArray.map { it.jsonPrimitive.content } },
                                          body(out).toString(Charsets.UTF_8).replace(mark, style))
                    val got = Triple(response.status, response.headers.map { listOf(it.first, it.second) }, response.text)
                    misses.check(got == expected) { "${record.extra["note"]}: $got\n   Python: $expected" }
                }
            }
        }
    }

    private fun body(o: JsonObject): ByteArray = o["body"]?.jsonPrimitive?.content?.toByteArray()
        ?: Base64.getDecoder().decode(o.getValue("body_b64").jsonPrimitive.content)

    /** A number written with a point or an exponent (never true, false or null). */
    private fun isFloat(value: JsonPrimitive) = !value.isString && value !is JsonNull &&
        (value.content.first() == '-' || value.content.first() in '0'..'9') && value.content.any { it in ".eE" }

    /** [value] as Kotlin would build it: every float a Double, through PyJson.float (never JsonPrimitive(Double)). */
    private fun builtInKotlin(value: JsonElement): JsonElement = when (value) {
        is JsonObject -> JsonObject(value.mapValues { builtInKotlin(it.value) })
        is JsonArray -> JsonArray(value.map(::builtInKotlin))
        is JsonPrimitive -> if (isFloat(value)) PyJson.float(value.content.toDouble()) else value
    }

    private fun floats(value: JsonElement): Int = when (value) {
        is JsonObject -> value.values.sumOf(::floats)
        is JsonArray -> value.sumOf(::floats)
        is JsonPrimitive -> if (isFloat(value)) 1 else 0
    }

    /** routing.jsonl's json_response, json_block and sha256_source records: every JSON answer and data block written
     * as Python writes it, from the text Python read it from and as Kotlin would build it. */
    fun jsonAnswers(misses: Misses) {
        val records = routingRecords.filter { it.fn.startsWith("caracole.inline.") || it.fn == "caracole.web.app.json_response" }
        misses.check(records.count { it.fn == "caracole.inline.json_block" } > 20) { "routing.jsonl's data blocks" }
        var counted = 0
        inFolder("caracole-json") { dir ->
            TestApp(dir).use { test ->
                for (record in records) {
                    val args = record.args.map { it.jsonPrimitive.content }
                    val expected = record.out!!.jsonPrimitive.content
                    when (record.fn) {
                        "caracole.inline.sha256_source" -> misses.check(expected == Inline.sha256Source(args[0])) {
                            "sha256_source(${args[0].take(80)})"
                        }
                        "caracole.inline.json_block" -> {
                            val data = Json.parseToJsonElement(args[1])
                            misses.check(expected == Inline.jsonBlock(args[0], data)) { "json_block(${args[1].take(80)})" }
                            misses.check(expected == Inline.jsonBlock(args[0], builtInKotlin(data))) {
                                "json_block built in Kotlin: ${args[1].take(80)}"
                            }
                        }
                        else -> {
                            val data = Json.parseToJsonElement(args[0])
                            misses.check(expected == test.app.json(data).text) { "json_response(${args[0].take(80)})" }
                            misses.check(expected == test.app.json(builtInKotlin(data)).text) {
                                "json_response built in Kotlin: ${args[0].take(80)}"
                            }
                            counted += floats(data)
                        }
                    }
                }
            }
        }
        misses.check(counted > 20) { "the vectors hold $counted floats" }
    }

    // --- sync_routes.jsonl ------------------------------------------------------------------------------------------

    private const val MASKED = "<comparison>"

    /** The phone's sync's stages the computer's hasn't (§5.3). */
    private val PHONE_ALONE = setOf("mirror", "index")

    /** The six routes of the Sync tab sync_routes.jsonl asks (the sync redesign's §3.4.1). */
    val SYNC_ROUTES = setOf("GET /api/sync", "POST /sync/test", "POST /sync/compare", "GET /api/sync/unit",
                            "GET /api/sync/indexes", "POST /sync/apply")

    /** sync_routes.jsonl: each record's route asked of the phone's SyncRoutes over its own sides, its status and
     * its words Python's, under UTC (a day is said in the server's zone), the comparison's id masked; where the phone
     * says itself (GET /api/sync's `device` "phone") and the computer (a comparison's `peer.kind` "computer"), the
     * record's words for the computer's (`"computer"`) and caracole serve's (`"server"`); a Sync queued the
     * computer's view of the same job but for the stages the phone's sync has alone, its comparison the one the
     * computer's queued command names. */
    fun syncRoutes(misses: Misses) {
        val records = Corpus.records("web/sync_routes.jsonl")
        misses.check(records.map { it.fn }.toSet() == SYNC_ROUTES) {
            "sync_routes.jsonl's routes: ${records.map { it.fn }.toSet()}"
        }
        misses.check(records.size >= 30) { "sync_routes.jsonl holds ${records.size} records" }
        misses.check(records.any { (it.out as? JsonObject)?.get("job") is JsonObject }) {
            "sync_routes.jsonl holds no Sync queued"
        }
        misses.check(records.any { (it.out as? JsonObject)?.get("synced_before").let { at -> at is JsonPrimitive && at !is JsonNull } }) {
            "sync_routes.jsonl holds no record synced before"
        }
        misses.check(records.any { ((it.out as? JsonObject)?.get("songbooks") as? JsonObject)?.isNotEmpty() == true }) {
            "sync_routes.jsonl holds no comparison of a songbook's two documents"
        }
        for (record in records) syncRoute(record, misses)
    }

    private fun syncRoute(record: Record, misses: Misses) = inFolder("caracole-sync-routes") { dir ->
        val here = record.extra.getValue("here").jsonObject
        val note = "${record.fn}: ${record.extra["note"]?.jsonPrimitive?.content}"
        val asked = AtomicInteger()
        val first = record.extra["peer_state"] as? JsonObject
        val then = record.extra["peer_state_then"] as? JsonObject
        val units = (record.extra["peer_units"] as? JsonObject).orEmpty()
        val computer = StateServer(
            state = {
                // Only a state asked moves on to the one Sync reads again: a unit asked between doesn't.
                val state = if (asked.getAndIncrement() == 0 || then == null) first else then
                state?.let { 200 to PyJson.dumps(it, compact = true) } ?: (500 to """{"error": "$note: no state to answer"}""")
            },
            unit = { id -> units[id]?.let { 200 to PyJson.dumps(it, compact = true) } ?: (404 to """{"error": "no unit"}""") },
        )
        val scope = CoroutineScope(Job().apply { cancel() })  // a Sync queued stays so: the record is its answer
        val queue = JobQueue(scope)
        val settings = object : SyncSettings {
            override var address: String? = null
            override fun remember(address: String) {}
        }
        lateinit var engine: SyncEngine
        val app = TestApp(dir, modules = { database ->
            engine = SyncEngine(database, LibraryStore(File(dir, "library")), File(dir, "state"),
                                client = { PeerClient(computer.address) }, mirrorRefresh = null)
            listOf(SyncRoutes(engine, queue, settings, database, afterSync = {},
                              name = here.getValue("name").jsonPrimitive.content, zone = { ZoneOffset.UTC }))
        })
        try {
            app.database.writeBlocking { db ->
                Fixtures.load(db, here.getValue("fixture").jsonPrimitive.content + ".jsonl", app.libraryDir)
                db.kvSet("sync:id", here.getValue("id").jsonPrimitive.content)
                for ((key, value) in here.getValue("kv").jsonObject) db.kvSet(key, value.jsonPrimitive.content)
            }
            val form = (record.extra["form"] as? JsonObject).orEmpty().mapValues { it.value.jsonPrimitive.content }

            /** The comparison the record's route follows, made first: its id, and the hash the phone keeps of it. */
            fun compared(): String? {
                val compare = record.extra.getValue("compare").jsonObject.mapValues { it.value.jsonPrimitive.content }
                val made = app.postScript("/sync/compare", compare.toList())
                if (made.status != 200) {
                    misses.check(false) { "$note: its comparison ${made.text}" }
                    return null
                }
                return made.json.jsonObject.getValue("comparison").jsonPrimitive.content
            }

            val answer = when (record.fn) {
                "GET /api/sync" -> app.script("/api/sync")
                "GET /api/sync/indexes" -> app.script("/api/sync/indexes")
                "POST /sync/test" -> app.postScript("/sync/test", form.toList())
                "POST /sync/compare" -> app.postScript("/sync/compare", form.toList())
                "GET /api/sync/unit" -> {
                    val id = compared() ?: return@inFolder
                    val query = record.extra.getValue("query").jsonObject.mapValues { it.value.jsonPrimitive.content }
                    val made = query.getValue("comparison").let { if (it == MASKED) id else it }
                    app.script("/api/sync/unit?comparison=${URLEncoder.encode(made, "UTF-8")}" +
                               "&id=${URLEncoder.encode(query.getValue("id"), "UTF-8")}")
                }
                "POST /sync/apply" -> {
                    val id = compared() ?: return@inFolder
                    val hash = engine.comparison(id)?.hash
                    val queued = record.extra.getValue("queued").jsonArray
                    if (queued.isNotEmpty()) {
                        misses.check("--compared=$hash" in queued.single().jsonArray.map { it.jsonPrimitive.content }) {
                            "$note: the comparison the computer's command names isn't the phone's ($hash)"
                        }
                    }
                    app.postScript("/sync/apply", form.map { (k, v) -> k to if (k == "comparison" && v == MASKED) id else v })
                }
                else -> {
                    misses.check(false) { "$note: no such route" }
                    return@inFolder
                }
            }
            val status = record.extra.getValue("status").jsonPrimitive.int
            misses.check(status == answer.status) { "$note: status ${answer.status}, not $status: ${answer.text}" }
            val shown = shown(record.fn, answer.json, note, misses)
            misses.check(record.out == shown) { "$note: ${shown.toString().take(400)}\n   Python: ${record.out.toString().take(400)}" }
        } finally {
            app.close()
            computer.close()
            scope.cancel()
        }
    }

    /** The phone's answer as the record keeps Python's: a comparison's id masked; the phone's device and the
     * computer's kind, checked, in the computer's words for itself and for caracole serve; and a Sync's stages the
     * computer's sync has alone. */
    private fun shown(fn: String, answer: JsonElement, note: String, misses: Misses): JsonElement {
        val data = answer.jsonObject
        if (fn == "GET /api/sync" && "device" in data) {
            misses.check(data["device"] == JsonPrimitive("phone")) { "$note: the phone's device is ${data["device"]}" }
            return JsonObject(data + ("device" to JsonPrimitive("computer")))
        }
        if (fn == "POST /sync/compare" && "comparison" in data) {
            val peer = data.getValue("peer").jsonObject
            misses.check(peer["kind"] == JsonPrimitive("computer")) { "$note: the computer's kind is ${peer["kind"]}" }
            return JsonObject(data + ("comparison" to JsonPrimitive(MASKED)) +
                              ("peer" to JsonObject(peer + ("kind" to JsonPrimitive("server")))))
        }
        val job = data["job"] as? JsonObject ?: return answer
        val steps = job.getValue("steps").jsonArray.filter {
            it.jsonObject.getValue("name").jsonPrimitive.content !in PHONE_ALONE
        }
        return JsonObject(mapOf("job" to JsonObject(job + ("steps" to JsonArray(steps)))))
    }

    /**
     * Another caracole's `GET /api/peer/state` and `GET /api/peer/unit` as a record gives them, on 127.0.0.1 at a free
     * port: [state]'s status and JSON for the first, [unit]'s for the second (by its `id`), 404 for any other path. A
     * plain socket server of the replay's own (no JDK HTTP server, which Android hasn't got): one request a
     * connection, answered and closed.
     */
    private class StateServer(private val state: () -> Pair<Int, String>,
                              private val unit: (String) -> Pair<Int, String> = { 404 to """{"error": "no unit"}""" }) :
        AutoCloseable {
        // 127.0.0.1 by number: Android's getLoopbackAddress() is ::1, where 127.0.0.1 finds nothing.
        private val socket = ServerSocket(0, 16, InetAddress.getByAddress(byteArrayOf(127, 0, 0, 1)))
        val address: ServerAddress = ServerAddress.parse("127.0.0.1:${socket.localPort}")

        private val serving = thread(isDaemon = true, name = "replay-state-server") {
            while (!socket.isClosed) {
                val connection = try {
                    socket.accept()
                } catch (e: java.io.IOException) {
                    break
                }
                connection.use { answer(it) }
            }
        }

        private fun answer(connection: Socket) {
            val input = BufferedInputStream(connection.getInputStream())
            val head = StringBuilder()
            while (!head.endsWith("\r\n\r\n")) {
                val b = input.read()
                if (b < 0) return
                head.append(b.toChar())
            }
            val lines = head.split("\r\n")
            val target = lines.first().split(' ').getOrElse(1) { "" }
            val path = target.substringBefore('?')
            val length = lines.drop(1).firstOrNull { it.startsWith("content-length:", ignoreCase = true) }
                ?.substringAfter(':')?.trim(' ')?.toLongOrNull() ?: 0
            repeat(length.toInt()) { input.read() }
            val (status, body) = when (path) {
                PeerClient.STATE_PATH -> state()
                PeerClient.UNIT_PATH -> unit(PyUrl.query(target)["id"].orEmpty())
                else -> 404 to """{"error": "no such route"}"""
            }
            val bytes = body.toByteArray()
            val out = connection.getOutputStream()
            out.write(("HTTP/1.1 $status ${if (status == 200) "OK" else "Error"}\r\n" +
                "Content-Type: application/json; charset=utf-8\r\nContent-Length: ${bytes.size}\r\n" +
                "Connection: close\r\n\r\n").toByteArray())
            out.write(bytes)
            out.flush()
        }

        override fun close() {
            socket.close()
            serving.join(5_000)
        }
    }

    // --- downloads.jsonl --------------------------------------------------------------------------------------------

    /** downloads.jsonl: web/files.py's TYPES (its pairs, in order), DOWNLOADS and MAX_BYTES, and download_names.py's
     * download_name and content_disposition. */
    fun downloads(misses: Misses) {
        val records = Corpus.records("web/downloads.jsonl")
        val types = records.single { it.fn == "caracole.web.files.TYPES" }.out!!.jsonArray.map { pair ->
            pair.jsonArray.let { it[0].jsonPrimitive.content to it[1].jsonPrimitive.content }
        }
        misses.check(types == FileTypes.TYPES.toList()) { "files.py's TYPES ${FileTypes.TYPES.toList()}" }
        val downloads = records.single { it.fn == "caracole.web.files.DOWNLOADS" }.out!!.jsonArray.map { it.jsonPrimitive.content }
        misses.check(downloads == FileTypes.DOWNLOADS.sorted()) { "files.py's DOWNLOADS ${FileTypes.DOWNLOADS.sorted()}" }
        val max = records.single { it.fn == "caracole.web.files.MAX_BYTES" }.out!!.jsonPrimitive.int.toLong()
        misses.check(max == FileTypes.MAX_BYTES) { "files.py's MAX_BYTES ${FileTypes.MAX_BYTES}" }
        val named = records.filter { it.fn.startsWith("caracole.download_names.") }
        misses.check(named.isNotEmpty()) { "downloads.jsonl names no download" }
        for (r in named) {
            val args = r.args.map { it.jsonPrimitive.content }
            val got = runCatching {
                when (r.fn.substringAfterLast('.')) {
                    "download_name" -> DownloadNames.downloadName(args[0], args[1], args[2])
                    else -> DownloadNames.contentDisposition(args[0])
                }
            }.getOrElse { it.toString() }
            misses.check(got == r.out!!.jsonPrimitive.content) { "${r.fn}$args → $got, Python ${r.out}" }
        }
    }

    // --- security.jsonl ---------------------------------------------------------------------------------------------

    /** security.jsonl: each of security.py's checks answered as Python answered it (more than a thousand: the host
     * names, the origins and the fetch metadata a request may carry), none raising; and `str.isdigit` and `str.isspace`,
     * the code points of which the vector holds as ranges, for every code point there is. */
    fun security(misses: Misses) {
        val records = Corpus.records("web/security.jsonl")
        val calls = records.filter { it.fn.startsWith("caracole.web.security.") }
        misses.check(calls.size > 1000) { "security.jsonl's matrix holds ${calls.size} calls" }
        misses.check(records.none { it.err != null }) { "security.py raises for none of them" }
        fun text(e: JsonElement): String? = if (e is JsonNull) null else e.jsonPrimitive.content
        fun headers(e: JsonElement): Map<String, String> = e.jsonObject.mapValues { it.value.jsonPrimitive.content }
        for (r in calls) {
            val got = runCatching<JsonElement> {
                when (r.fn.substringAfterLast('.')) {
                    "host_name" -> Security.hostName(text(r.args[0]))?.let(::JsonPrimitive) ?: JsonNull
                    "answers_to" -> JsonPrimitive(Security.answersTo(text(r.args[0]),
                                                                     r.args[1].jsonArray.map { it.jsonPrimitive.content }.toSet()))
                    "cross_origin_ok" -> JsonPrimitive(Security.crossOriginOk(r.args[0].jsonPrimitive.content,
                                                                              headers(r.args[1]), text(r.args[2])))
                    "own_page_read" -> JsonPrimitive(Security.ownPageRead(headers(r.args[0])))
                    "same_token" -> JsonPrimitive(Security.sameToken(text(r.args[0]), r.args[1].jsonPrimitive.content))
                    else -> throw IllegalStateException("no Kotlin for ${r.fn}")
                }
            }.getOrElse { JsonPrimitive("${it::class.simpleName}: ${it.message}") }
            misses.check(got == r.out) { "${r.fn}${r.args} → $got, Python ${r.out}" }
        }
        fun ranges(fn: String): List<IntRange> = records.single { it.fn == fn }.out!!.jsonArray.map {
            val (first, last) = it.jsonArray.map { n -> n.jsonPrimitive.int }
            first..last
        }
        val digits = ranges("str.isdigit")
        val spaces = ranges("str.isspace")
        var wrong = 0
        var first: String? = null
        for (cp in 0..0x10FFFF) {
            val digit = digits.any { cp in it } == PyText.isDigit(cp)
            val space = spaces.any { cp in it } == PyText.isSpace(cp)
            if (!digit || !space) {
                wrong++
                if (first == null) first = "U+%04X: isdigit %s, isspace %s".format(cp, PyText.isDigit(cp), PyText.isSpace(cp))
            }
        }
        misses.check(wrong == 0) { "$wrong code points' isdigit or isspace differ from Python's, the first $first" }
    }

    private fun <T> inFolder(prefix: String, block: (File) -> T): T {
        val dir = Files.createTempDirectory(prefix).toFile()
        try {
            return block(dir)
        } finally {
            dir.deleteRecursively()
        }
    }
}
