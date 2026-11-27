package io.github.danielhp95.caracole.server.testing.replays

import io.github.danielhp95.caracole.core.config.PhoneConfig
import io.github.danielhp95.caracole.core.db.Database
import io.github.danielhp95.caracole.core.health.Alerts
import io.github.danielhp95.caracole.core.library.LibraryStore
import io.github.danielhp95.caracole.core.lookup.Clients
import io.github.danielhp95.caracole.core.lookup.Pacing
import io.github.danielhp95.caracole.core.lookup.SongPages
import io.github.danielhp95.caracole.core.lookup.SongbookPages
import io.github.danielhp95.caracole.core.testing.Corpus
import io.github.danielhp95.caracole.core.testing.Fixtures
import io.github.danielhp95.caracole.core.testing.Misses
import io.github.danielhp95.caracole.core.testing.RefusingTransport
import io.github.danielhp95.caracole.core.testing.TestDb
import io.github.danielhp95.caracole.core.youtube.Thumbs
import io.github.danielhp95.caracole.server.PhoneParts
import io.github.danielhp95.caracole.server.http.Refused
import io.github.danielhp95.caracole.server.http.Response
import io.github.danielhp95.caracole.server.jobs.JobQueue
import io.github.danielhp95.caracole.server.page.MirrorPageData
import io.github.danielhp95.caracole.server.routes.LibraryRoutes
import io.github.danielhp95.caracole.server.routes.YouTubeRoutes
import io.github.danielhp95.caracole.server.testing.TestApp
import io.github.danielhp95.caracole.server.testing.WebJson
import io.github.danielhp95.caracole.server.testing.bytes
import io.github.danielhp95.caracole.server.testing.header
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
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import java.io.File
import java.net.URLEncoder
import java.nio.file.Files
import java.time.Instant
import java.util.Base64

/**
 * vectors/web/youtube_routes.jsonl (tests/test_conformance_youtube_routes.py, whose docstring says what each record
 * holds): each scene's library loaded on a fresh database with its thumbnails in the phone's cache, then each record
 * asked of the phone's YouTubeRoutes (and LibraryRoutes' `POST /request`, handed the video's request), its reason for
 * no sheet from a video the record's `problem`, every gate read at the record's time, over a queue that runs nothing
 * (`full`: one that holds no job). Compared with caracole serve's: a refusal's status, title and words; else the
 * status, the Location, the body less the job's view, and the job (title, key, steps, display, note: the phone writes
 * no wanted.txt, so a job of a song new to the library has none); `GET /api/youtube/video`'s JSON whole; a
 * thumbnail's status, type, policy and body's SHA-256, or its 404's body.
 */
object YouTubeRoutesReplay {
    const val VECTOR = "web/youtube_routes.jsonl"

    /** A scope that runs nothing: a job queued in it waits for ever, as the generator's queue was never started. */
    private val NOWHERE = CoroutineScope(Job().apply { cancel() })

    fun replay(misses: Misses) {
        val lines = Corpus.lines(VECTOR).filter { it["header"] != JsonPrimitive(true) }
        val fixtures = lines.filter { it["fn"]?.jsonPrimitive?.content == "fixture" }
        misses.check(fixtures.size == 4) { "youtube_routes.jsonl holds ${fixtures.size} scenes" }
        for (fixture in fixtures) {
            val scene = fixture.getValue("scene").jsonPrimitive.content
            val dir = Files.createTempDirectory("caracole-youtube-routes").toFile()
            try {
                TestDb.fresh(dir).use { database ->
                    val library = File(dir, "library").apply { mkdirs() }
                    database.writeBlocking { db ->
                        Fixtures.loadRecords(db, fixture.getValue("records").jsonArray.map { it.jsonObject }, library)
                    }
                    val state = File(dir, "state").apply { mkdirs() }
                    val thumbs = Thumbs(File(state, "cache"))
                    for ((name, data) in fixture.getValue("thumbs").jsonObject) {
                        thumbs.path(name.removeSuffix(".jpg")).apply { parentFile.mkdirs() }
                            .writeBytes(Base64.getDecoder().decode(data.jsonPrimitive.content))
                    }
                    for (r in lines.filter { it["scene"]?.jsonPrimitive?.content == scene && "case" in it }) {
                        one(misses, database, dir, r)
                    }
                }
            } finally {
                dir.deleteRecursively()
            }
        }
    }

    private fun one(misses: Misses, database: Database, dir: File, r: JsonObject) {
        val fn = r.getValue("fn").jsonPrimitive.content
        val case = "$fn (${r["scene"]?.jsonPrimitive?.content}: ${r.getValue("case").jsonPrimitive.content})"
        val full = r["full"]?.jsonPrimitive?.boolean == true
        val problem = r["problem"]?.takeIf { it !is JsonNull }?.jsonPrimitive?.content
        val now = Instant.parse("2026-11-27T12:00:00Z")
        val queue = JobQueue(NOWHERE, limit = if (full) 0 else JobQueue.LIMIT)
        val state = File(dir, "state")
        val parts = PhoneParts(database, LibraryStore(File(dir, "library")), state, { PhoneConfig.DEFAULTS }, queue,
                               MirrorPageData(null),
                               { Clients(PhoneConfig.DEFAULTS, File(state, "cache"), { RefusingTransport }, Pacing.REAL) },
                               SongPages.NONE, SongbookPages.NONE, Alerts.NONE, Pacing.REAL, searchesLacuerda = false)
        val routes = YouTubeRoutes(parts, null, problem = { problem }) { now }
        val library = LibraryRoutes(parts.store, queue, parts.cards, database, youtube = routes::sheetFromYoutube)
        val out = r.getValue("out").jsonObject
        when (fn) {
            "GET /api/youtube/video" -> {
                val query = r.getValue("query").jsonObject.entries.joinToString("&") { (k, v) ->
                    "$k=" + URLEncoder.encode(v.jsonPrimitive.content, Charsets.UTF_8)
                }
                val target = "/api/youtube/video" + if (query.isEmpty()) "" else "?$query"
                val route = routes.routes.first { it.path == "/api/youtube/video" }
                val answer = try {
                    route.get!!.answer(TestApp.request("GET", target, emptyMap(), ByteArray(0), TestApp.SECRET))
                } catch (e: Refused) {
                    return refused(misses, case, out, e)
                }
                if ("body" !in out) return misses.check(false) { "$case: answered ${answer.status}, caracole serve refused $out" }
                misses.check(answer.status == 200) { "$case: status ${answer.status}" }
                WebJson.difference(out.getValue("body"), json(answer))?.let { misses.check(false) { "$case: its answer at $it" } }
                misses.check(order(out) == keyOrder(json(answer))) {
                    "$case: its members in another order: ${keyOrder(json(answer))}, caracole serve's ${order(out)}"
                }
            }
            "GET /youtube/thumb/" -> {
                val target = YouTubeRoutes.THUMB + r.getValue("name").jsonPrimitive.content
                val route = routes.routes.first { it.path == YouTubeRoutes.THUMB }
                val answer = route.get!!.answer(TestApp.request("GET", target, emptyMap(), ByteArray(0), TestApp.SECRET))
                misses.check(JsonPrimitive(answer.status) == out["status"]) { "$case: status ${answer.status}, ${out["status"]}" }
                if (answer.status == 200) {
                    val headers = JsonArray(answer.headers.map { (k, v) -> JsonArray(listOf(JsonPrimitive(k), JsonPrimitive(v))) })
                    misses.check(headers == out["headers"]) { "$case: headers $headers, caracole serve's ${out["headers"]}" }
                    val sha = AudioSheetReplay.sha256(answer.bytes)
                    misses.check(JsonPrimitive(sha) == out["sha256"]) { "$case: its bytes $sha" }
                } else {
                    WebJson.difference(out.getValue("body"), json(answer))?.let { misses.check(false) { "$case: its 404 at $it" } }
                }
            }
            else -> {
                val path = fn.removePrefix("POST ")
                val route = (routes.routes + library.routes).first { it.method == "POST" && it.path == path }
                val form = LinkedHashMap<String, String>()
                for (field in r.getValue("form").jsonArray) form[field.jsonArray[0].jsonPrimitive.content] = field.jsonArray[1].jsonPrimitive.content
                val wants = r.getValue("json").jsonPrimitive.boolean
                val asked = TestApp.request("POST", path, if (wants) mapOf("accept" to "application/json") else emptyMap(),
                                            ByteArray(0), TestApp.SECRET)
                val answer: Response = try {
                    if (r["twice"]?.jsonPrimitive?.boolean == true) route.post!!.answer(asked, form)  // its job waits
                    route.post!!.answer(asked, form)
                } catch (e: Refused) {
                    return refused(misses, case, out, e)
                }
                posted(misses, case, out, answer, queue)
            }
        }
    }

    private fun refused(misses: Misses, case: String, out: JsonObject, e: Refused) {
        val got = JsonObject(linkedMapOf("status" to JsonPrimitive(e.status), "title" to JsonPrimitive(e.title),
                                         "message" to JsonPrimitive(e.message)))
        val want = JsonObject(linkedMapOf("status" to out.getValue("status"), "title" to (out["title"] ?: JsonNull),
                                          "message" to (out["message"] ?: JsonNull)))
        misses.check("job" !in out && "body" !in out && want == got) { "$case: refused $got, caracole serve's $out" }
    }

    private fun posted(misses: Misses, case: String, out: JsonObject, answer: Response, queue: JobQueue) {
        if ("job" !in out) return misses.check(false) { "$case: answered ${answer.status}, caracole serve refused $out" }
        misses.check(JsonPrimitive(answer.status) == out["status"]) { "$case: status ${answer.status}, ${out["status"]}" }
        val location = answer.header("location")
        misses.check((location?.let(::JsonPrimitive) ?: JsonNull) == out["location"]) {
            "$case: Location $location, caracole serve's ${out["location"]}"
        }
        val body = answer.bytes.takeIf { it.isNotEmpty() }?.let { bytes ->
            (Json.parseToJsonElement(bytes.toString(Charsets.UTF_8)) as? JsonObject)?.let { JsonObject(it - "view") }
        } ?: JsonNull
        WebJson.difference(out.getValue("body"), body)?.let { misses.check(false) { "$case: its answer at $it" } }
        misses.check(order(out) == keyOrder(body)) { "$case: its answer's members in another order: ${keyOrder(body)}" }
        val jobs = queue.snapshot()
        if (jobs.size != 1) return misses.check(false) { "$case: ${jobs.size} jobs queued" }
        val job = jobs.single()
        val python = out.getValue("job").jsonObject
        val wanted = out["wanted"]?.jsonPrimitive?.boolean == true
        val phone = JsonObject(linkedMapOf(
            "title" to JsonPrimitive(job.spec.title), "key" to JsonPrimitive(job.key),
            "steps" to JsonArray(job.steps.map { JsonArray(listOf(JsonPrimitive(it.label), JsonArray(it.args.map(::JsonPrimitive)))) }),
            "display" to JsonPrimitive(job.display), "note" to JsonPrimitive(job.spec.note),
        ))
        // the phone writes no wanted.txt: no line to name
        val expected = if (wanted) JsonObject(python + ("note" to JsonPrimitive(""))) else python
        WebJson.difference(expected, phone)?.let { misses.check(false) { "$case: its job at $it: $phone" } }
        // The song wanted.txt's line made there is the one the phone's job adds (its spec's), album and length too.
        val adds = job.spec.song?.let { s ->
            JsonObject(linkedMapOf("artist" to JsonPrimitive(s.artist), "title" to JsonPrimitive(s.title),
                                   "album" to (s.album?.let(::JsonPrimitive) ?: JsonNull),
                                   "duration_ms" to (s.durationMs?.let(::JsonPrimitive) ?: JsonNull)))
        } ?: JsonNull
        val song = out["song"] ?: JsonNull
        misses.check(adds == song) { "$case: the song its job adds $adds, wanted.txt's line there $song" }
    }

    /** The order caracole serve's answer wrote its members in (the vector's own keys are sorted). */
    private fun order(out: JsonObject): List<String> = out.getValue("order").jsonArray.map { it.jsonPrimitive.content }

    /** Every object's members in order, by their path, as the generator's `_order` writes them: what a comparison of
     * values alone passes over. */
    private fun keyOrder(value: JsonElement, at: String = "", into: MutableList<String> = mutableListOf()): List<String> {
        when (value) {
            is JsonObject -> for ((k, v) in value) { into += "$at.$k"; keyOrder(v, "$at.$k", into) }
            is JsonArray -> value.forEachIndexed { i, v -> keyOrder(v, "$at[$i]", into) }
            else -> {}
        }
        return into
    }

    private fun json(answer: Response): JsonElement = Json.parseToJsonElement(answer.bytes.toString(Charsets.UTF_8))
}
