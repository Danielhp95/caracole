package io.github.danielhp95.caracole.server.testing.replays

import io.github.danielhp95.caracole.core.db.Db
import io.github.danielhp95.caracole.core.json.PyJson
import io.github.danielhp95.caracole.core.library.LibraryStore
import io.github.danielhp95.caracole.core.py.PyText
import io.github.danielhp95.caracole.core.py.PyUrl
import io.github.danielhp95.caracole.core.sync.PeerClient
import io.github.danielhp95.caracole.core.sync.SyncEngine
import io.github.danielhp95.caracole.core.sync.file.SyncFiles
import io.github.danielhp95.caracole.core.testing.AreaReplay
import io.github.danielhp95.caracole.core.testing.Corpus
import io.github.danielhp95.caracole.core.testing.Fixtures
import io.github.danielhp95.caracole.core.testing.TestDb
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
import io.github.danielhp95.caracole.server.routes.SyncFileRoutes
import io.github.danielhp95.caracole.server.routes.SyncRoutes
import io.github.danielhp95.caracole.server.routes.sync.Exports
import io.github.danielhp95.caracole.server.routes.sync.Imports
import io.github.danielhp95.caracole.server.routes.SyncSettings
import io.github.danielhp95.caracole.server.testing.SearchApp
import io.github.danielhp95.caracole.server.testing.TestApp
import io.github.danielhp95.caracole.server.testing.WebJson
import io.github.danielhp95.caracole.server.testing.bytes
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
import java.time.Instant
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
 * - [syncFileRoutes]: sync_file_routes.jsonl, Export and Import a file over a fixture of the sync corpus and the sync
 *   file corpus's files (SyncFileRoutes, and SyncRoutes' Sync on a file's comparison);
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
        syncFileRoutes(misses)
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

    /** The phone's sync's stages the computer's hasn't (§5.3): its mirror; the index stage both have
     * (jobs.PEER_SYNC_STAGES' index, `caracole peer sync`'s indexes both ways). */
    private val PHONE_ALONE = setOf("mirror")

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

    // --- sync_file_routes.jsonl -------------------------------------------------------------------------------------

    /** Every request of Export and Import a file sync_file_routes.jsonl asks (the sync redesign's §3.4.2), and the
     * routes' declared bodies (`limits`). */
    val SYNC_FILE_ROUTES = setOf("GET /api/sync/sizes", "POST /sync/export", "GET /api/sync/export",
                                 "HEAD /api/sync/export", "POST /sync/import/open", "POST /sync/import/part",
                                 "POST /sync/import/compare", "POST /sync/import/drop", "POST /sync/apply", "limits")

    /** The routes' clock as the vectors' (test_conformance_sync_file_routes.NOW), and the name a file is sent by. */
    private val FILE_ROUTES_NOW: Instant = Instant.parse("2026-11-03T22:00:00Z")
    private const val SENT_AS = "lib-03-11-26.caracole"
    private const val EXPORT = "<export>"
    private const val IMPORT = "<import>"

    /** An import's stages the computer's import has and the phone's hasn't (its render, which the phone's pages make
     * after the job), and the phone's it hasn't (the file's pages kept as a layer of the mirror). */
    private val COMPUTER_IMPORT_ALONE = setOf("render")

    /**
     * sync_file_routes.jsonl: each record's request asked of the phone's SyncFileRoutes (and SyncRoutes, whose Sync
     * hands a file's comparison to it) over a phone of its own, the record's `here` (a fixture of the sync corpus
     * loaded, its id and kv, its library's name), under UTC with the routes' clock at the vectors' time; its status
     * and its answer Python's, the ids masked as the record masks them. A record's request follows what it says
     * came before it: an export made of the parts it names (`export`); the file it names sent whole, or its first
     * `sent` bytes, in parts of 4096 (`file`), and for a Sync, compared, with a song added between (`moved`); and
     * where the record's answer says an earlier request of the same phone is its cause, that one: an open refused for
     * one open already (409) opens one first, a part is sent to an import opened of the size its accepted parts end
     * at, a drop refused for its request (409) follows that file's Sync, and a drop of a file gone (404) follows its
     * drop. A Sync queued is the computer's view of the same job but for the import's stages each side has alone
     * ([COMPUTER_IMPORT_ALONE], the phone's mirror), its comparison the one the computer's queued command names.
     */
    fun syncFileRoutes(misses: Misses) {
        val records = Corpus.records("web/sync_file_routes.jsonl")
        misses.check(records.map { it.fn }.toSet() == SYNC_FILE_ROUTES) {
            "sync_file_routes.jsonl's routes: ${records.map { it.fn }.toSet()}"
        }
        misses.check(records.size >= 40) { "sync_file_routes.jsonl holds ${records.size} records" }
        misses.check(records.any { (it.out as? JsonObject)?.get("job") is JsonObject }) {
            "sync_file_routes.jsonl holds no Sync queued"
        }
        for (record in records) {
            if (record.fn == "limits") limits(record, misses) else syncFileRoute(record, misses)
        }
    }

    /** `limits`: each POST route's body and limit, the phone's routes' (SyncFileRoutes', SyncRoutes') as Python's. */
    private fun limits(record: Record, misses: Misses) = inFolder("caracole-sync-file-limits") { dir ->
        val routes = TestDb.fresh(dir).use { database ->
            val engine = SyncEngine(database, LibraryStore(File(dir, "library")), File(dir, "state"),
                                    client = { throw IllegalStateException("no computer") }, mirrorRefresh = null)
            val queue = JobQueue(CoroutineScope(Job().apply { cancel() }))
            val settings = object : SyncSettings {
                override val address: String? = null
                override fun remember(address: String) {}
            }
            SyncRoutes(engine, queue, settings, database, afterSync = {}).routes +
                SyncFileRoutes(engine, queue, database, File(dir, "library"), Imports(File(dir, "state")),
                               Exports(File(dir, "cache")), pages = { null }, afterSync = {}).routes
        }
        val declared = JsonObject(routes.filter { it.method == "POST" }.associate { route ->
            "${route.method} ${route.path}" to JsonArray(listOf(JsonPrimitive(route.body), JsonPrimitive(route.limit)))
        })
        misses.check(declared == record.out) { "the routes declare $declared, Python's ${record.out}" }
    }

    private fun syncFileRoute(record: Record, misses: Misses) = inFolder("caracole-sync-file-routes") { dir ->
        val here = record.extra.getValue("here").jsonObject
        val note = "${record.fn}: ${record.extra["note"]?.jsonPrimitive?.content}"
        val name = here.getValue("name").jsonPrimitive.content
        val scope = CoroutineScope(Job().apply { cancel() })  // a Sync queued stays so: the record is its answer
        val queue = JobQueue(scope)
        val settings = object : SyncSettings {
            override var address: String? = null
            override fun remember(address: String) {}
        }
        val imports = Imports(File(dir, "state"))
        val exports = Exports(File(dir, "state/cache"))
        lateinit var engine: SyncEngine
        val app = TestApp(dir, modules = { database ->
            engine = SyncEngine(database, LibraryStore(File(dir, "library")), File(dir, "state"),
                                client = { throw IllegalStateException("$note: no computer to ask") }, mirrorRefresh = null)
            val sync = SyncRoutes(engine, queue, settings, database, afterSync = {}, name = name, zone = { ZoneOffset.UTC })
            val files = SyncFileRoutes(engine, queue, database, File(dir, "library"), imports, exports, pages = { null },
                                       afterSync = {}, name = { name }, now = { FILE_ROUTES_NOW }, zone = { ZoneOffset.UTC })
            sync.files = files
            listOf(sync, files)
        })
        try {
            app.database.writeBlocking { db ->
                Fixtures.load(db, here.getValue("fixture").jsonPrimitive.content + ".jsonl", app.libraryDir)
                db.kvSet("sync:id", here.getValue("id").jsonPrimitive.content)
                for ((key, value) in here.getValue("kv").jsonObject) db.kvSet(key, value.jsonPrimitive.content)
            }
            val asking = FileAsking(app)
            val status = record.extra["status"]?.takeIf { it !is JsonNull }?.jsonPrimitive?.int
            fun answered(answer: Response, out: JsonElement) {
                misses.check(status == answer.status) { "$note: status ${answer.status}, not $status: ${out.toString().take(300)}" }
                misses.check(record.out == out) { "$note: ${out.toString().take(600)}\n   Python: ${record.out.toString().take(600)}" }
            }
            fun staged() = File(dir, "state/peer").listFiles().orEmpty().any { it.name.startsWith("import-") }
            fun sent(): String? {
                val given = record.extra["file"] ?: return null
                val data = fileOf(given)
                val upto = record.extra["sent"]?.jsonPrimitive?.int ?: data.size
                return asking.send(data, upto)
            }
            when (record.fn) {
                "GET /api/sync/sizes" -> {
                    val answer = asking.get("/api/sync/sizes")
                    val out = answer.json.jsonObject
                    // The indexes' bytes are SQLite's pages (masked); null where its build has no dbstat, as the
                    // phone's bundled SQLite's may (peer_file.indexes_size's None): Python's then, whatever it says.
                    val dbstat = app.database.read { db -> db.query("PRAGMA compile_options") { it.text(0) } }
                        .any { it == "ENABLE_DBSTAT_VTAB" }
                    val indexes = out["indexes"]
                    misses.check(dbstat == (indexes != null && indexes !is JsonNull)) {
                        "$note: the indexes' bytes $indexes, with dbstat $dbstat"
                    }
                    answered(answer, JsonObject(out + ("indexes" to (record.out!!.jsonObject["indexes"].takeIf { !dbstat } ?: JsonPrimitive("<bytes>")))))
                }
                "POST /sync/export" -> {
                    val doc = record.extra.getValue("json")
                    val answer = if (record.extra["making"] == JsonPrimitive(true)) {
                        var asked: Response? = null
                        exports.make("busy.caracole") { file -> asked = asking.json("/sync/export", doc); file.writeBytes(ByteArray(1)) }
                        asked!!
                    } else asking.json("/sync/export", doc)
                    val out = answer.json.jsonObject
                    if (answer.status == 200) {
                        misses.check(Imports.ID.matches(out.getValue("export").jsonPrimitive.content)) { "$note: an export's id $out" }
                        misses.check(out.getValue("size").jsonPrimitive.content.toLongOrNull() != null) { "$note: its size $out" }
                        answered(answer, JsonObject(out + ("export" to JsonPrimitive(EXPORT)) + ("size" to JsonPrimitive("<size>"))))
                    } else answered(answer, out)
                }
                "GET /api/sync/export" -> {
                    val made = record.extra["export"]?.let { parts ->
                        asking.json("/sync/export", parts).json.jsonObject.getValue("export").jsonPrimitive.content
                    }
                    val asked = record.extra.getValue("query").jsonObject.getValue("export").jsonPrimitive.content
                    val target = "/api/sync/export?export=" + URLEncoder.encode(if (asked == EXPORT) made!! else asked, "UTF-8")
                    val answer = asking.get(target)
                    val out = if (answer.status == 200) {
                        val file = File(dir, "downloaded.caracole").apply { writeBytes(answer.bytes) }
                        JsonObject(linkedMapOf(
                            "headers" to JsonObject(listOf("Content-Type", "Content-Disposition").associateWith {
                                answer.header(it)?.let(::JsonPrimitive) ?: JsonNull
                            }),
                            "manifest" to Json.parseToJsonElement(SyncFiles.read(file).manifest.toString()),
                        ))
                    } else answer.json
                    answered(answer, out)
                    record.extra["again"]?.let { again ->
                        val second = asking.get(target)
                        misses.check(JsonArray(listOf(JsonPrimitive(second.status), second.json)) == again) {
                            "$note: asked again, ${second.status} ${second.text}"
                        }
                    }
                    misses.check(File(dir, "state/cache/peer").listFiles().orEmpty().none { it.name.endsWith(".caracole") }) {
                        "$note: the export left in the cache once sent: ${File(dir, "state/cache/peer").list()?.toList()}"
                    }
                }
                "HEAD /api/sync/export" -> {
                    val query = record.extra.getValue("query").jsonObject.getValue("export").jsonPrimitive.content
                    val answer = asking.get("/api/sync/export?export=$query", "HEAD")
                    answered(answer, JsonObject(mapOf("Allow" to (answer.header("Allow")?.let(::JsonPrimitive) ?: JsonNull))))
                }
                "POST /sync/import/open" -> {
                    if (status == 409) asking.json("/sync/import/open", obj("size" to 10, "name" to "first.caracole"))
                    val answer = asking.json("/sync/import/open", record.extra.getValue("json"))
                    val out = answer.json.jsonObject
                    answered(answer, if ("import" in out) JsonObject(out + ("import" to JsonPrimitive(IMPORT))) else out)
                }
                "POST /sync/import/part" -> {
                    val parts = record.extra.getValue("parts").jsonArray.map { it.jsonObject }
                    val answers = (record.out as JsonArray).map { it.jsonArray[0].jsonPrimitive.int }
                    val size = parts.zip(answers).filter { it.second == 200 }
                        .maxOfOrNull { (p, _) -> p.getValue("at").jsonPrimitive.int + p.getValue("bytes").jsonPrimitive.int } ?: 1000
                    val opened = asking.json("/sync/import/open", obj("size" to size, "name" to SENT_AS)).json.jsonObject
                        .getValue("import").jsonPrimitive.content
                    val got = parts.map { part ->
                        val id = part["import"]?.jsonPrimitive?.content?.let { if (it == IMPORT) opened else it } ?: opened
                        val at = part.getValue("at").jsonPrimitive.content
                        val answer = asking.bytes("/sync/import/part?import=$id&at=$at", ByteArray(part.getValue("bytes").jsonPrimitive.int) { 'x'.code.toByte() })
                        JsonArray(listOf(JsonPrimitive(answer.status), answer.json))
                    }
                    misses.check(JsonArray(got) == record.out) { "$note: $got\n   Python: ${record.out}" }
                }
                "POST /sync/import/compare" -> {
                    val id = sent()
                    val form = record.extra.getValue("form").jsonObject.mapValues { (_, v) ->
                        v.jsonPrimitive.content.let { if (it == IMPORT) id!! else it }
                    }
                    val answer = asking.form("/sync/import/compare", form)
                    val out = answer.json.jsonObject
                    answered(answer, if ("comparison" in out) JsonObject(out + ("comparison" to JsonPrimitive(MASKED))) else out)
                    record.extra["staged"]?.let { want ->
                        misses.check(JsonPrimitive(staged()) == want) { "$note: staged after it ${staged()}, Python's $want" }
                    }
                }
                "POST /sync/apply" -> {
                    val id = sent()!!
                    val compared = asking.form("/sync/import/compare", mapOf("import" to id))
                    if (compared.status != 200) {
                        misses.check(false) { "$note: its comparison ${compared.text}" }
                        return@inFolder
                    }
                    val made = compared.json.jsonObject.getValue("comparison").jsonPrimitive.content
                    val hash = engine.comparison(made)?.hash
                    record.extra["moved"]?.takeIf { it !is JsonNull }?.jsonPrimitive?.content?.let { moved ->
                        val (artist, title) = moved.split(" - ", limit = 2)
                        app.database.writeBlocking { db -> LibraryStore(app.libraryDir).add(db, artist, title, now = "2026-11-03T22:00:00Z") }
                    }
                    val queued = record.extra.getValue("queued").jsonArray
                    if (queued.isNotEmpty()) {
                        misses.check("--compared=$hash" in queued.single().jsonArray.map { it.jsonPrimitive.content }) {
                            "$note: the comparison the computer's command names isn't the phone's ($hash)"
                        }
                    }
                    val form = record.extra.getValue("form").jsonObject.mapValues { (k, v) ->
                        v.jsonPrimitive.content.let { if (k == "comparison" && it == MASKED) made else it }
                    }
                    val answer = asking.form("/sync/apply", form)
                    misses.check(status == answer.status) { "$note: status ${answer.status}, not $status: ${answer.text.take(300)}" }
                    val want = importJob(record.out!!, COMPUTER_IMPORT_ALONE)
                    val got = importJob(answer.json, setOf(SyncEngine.MIRROR))
                    misses.check(want == got) { "$note: ${got.toString().take(600)}\n   Python: ${want.toString().take(600)}" }
                    (answer.json.jsonObject["job"] as? JsonObject)?.let { job ->
                        val names = job.getValue("steps").jsonArray.map { it.jsonObject.getValue("name").jsonPrimitive.content }
                        misses.check(names == SyncEngine.FILE_STAGES.map { it.first }) { "$note: the phone's import's stages $names" }
                    }
                    misses.check(queue.snapshot().isEmpty() == queued.isEmpty()) {
                        "$note: the phone queued ${queue.snapshot().map { it.spec.key }}, Python ${queued.size}"
                    }
                    queue.snapshot().singleOrNull()?.let { job ->
                        misses.check(job.spec.key == SyncFileRoutes.IMPORTING + id) { "$note: its job's key ${job.spec.key}" }
                    }
                }
                "POST /sync/import/drop" -> {
                    val id = sent()
                    if (status == 409 && id != null) {
                        val made = asking.form("/sync/import/compare", mapOf("import" to id)).json.jsonObject
                            .getValue("comparison").jsonPrimitive.content
                        asking.form("/sync/apply", mapOf("comparison" to made, "prefer" to "", "choices" to ""))
                    }
                    val doc = record.extra.getValue("json").jsonObject.mapValues { (_, v) ->
                        v.jsonPrimitive.content.let { JsonPrimitive(if (it == IMPORT) id!! else it) }
                    }
                    if (status == 404 && id != null) asking.json("/sync/import/drop", JsonObject(doc))
                    val answer = asking.json("/sync/import/drop", JsonObject(doc))
                    val out = answer.json.jsonObject
                    answered(answer, if (id != null && out["dropped"] == JsonPrimitive(id)) JsonObject(mapOf("dropped" to JsonPrimitive(IMPORT))) else out)
                }
                else -> misses.check(false) { "$note: no such route" }
            }
        } finally {
            app.close()
            scope.cancel()
        }
    }

    /** A Sync's answer with the import's stages of one side alone ([alone]) left out. */
    private fun importJob(answer: JsonElement, alone: Set<String>): JsonElement {
        val job = answer.jsonObject["job"] as? JsonObject ?: return answer
        return JsonObject(mapOf("job" to JsonObject(job + ("steps" to JsonArray(job.getValue("steps").jsonArray.filter {
            it.jsonObject.getValue("name").jsonPrimitive.content !in alone
        })))))
    }

    /** The sync file corpus's file a record names (`sync/files/<name>.caracole`), its bytes (`{"bytes": base64}`), or
     * one cut short (`{"file", "cut"}`: less its last `cut` bytes). */
    private fun fileOf(given: JsonElement): ByteArray = when {
        given is JsonPrimitive -> Corpus.open(given.content)!!.use { it.readBytes() }
        "bytes" in given.jsonObject -> Base64.getDecoder().decode(given.jsonObject.getValue("bytes").jsonPrimitive.content)
        else -> fileOf(given.jsonObject.getValue("file")).let { it.copyOf(it.size - given.jsonObject.getValue("cut").jsonPrimitive.int) }
    }

    /** The page's script asking the phone's App, as test_conformance_sync_file_routes.Here asks caracole serve. */
    private class FileAsking(private val app: TestApp) {
        private val own = mapOf("sec-fetch-site" to "same-origin", "accept" to "application/json",
                                TestApp.TOKEN_HEADER to app.csrf)

        fun get(target: String, method: String = "GET"): Response = app.handle(app.request(method, target, own))

        fun json(target: String, doc: JsonElement): Response = app.handle(app.request(
            "POST", target, own + ("content-type" to "application/json"), PyJson.dumps(doc).toByteArray(Charsets.UTF_8)))

        fun bytes(target: String, data: ByteArray): Response =
            app.handle(app.request("POST", target, own + ("content-type" to "application/octet-stream"), data))

        fun form(target: String, form: Map<String, String>): Response = app.postScript(target, form.toList())

        /** [data] sent to Import a file as the page sends one, its first [upto] bytes, in parts of 4096: its id. */
        fun send(data: ByteArray, upto: Int): String {
            val opened = json("/sync/import/open", JsonObject(linkedMapOf("size" to JsonPrimitive(data.size),
                                                                          "name" to JsonPrimitive(SENT_AS))))
            check(opened.status == 200) { "open: ${opened.text}" }
            val id = opened.json.jsonObject.getValue("import").jsonPrimitive.content
            var at = 0
            while (at < upto) {
                val end = minOf(at + 4096, upto)
                val part = bytes("/sync/import/part?import=$id&at=$at", data.copyOfRange(at, end))
                check(part.status == 200) { "part at $at: ${part.text}" }
                at = end
            }
            return id
        }
    }

    private fun obj(vararg pairs: Pair<String, Any>): JsonObject = JsonObject(pairs.associate { (k, v) ->
        k to when (v) {
            is Int -> JsonPrimitive(v)
            else -> JsonPrimitive(v.toString())
        }
    })

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
