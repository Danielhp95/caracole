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
import io.github.danielhp95.caracole.server.PhoneParts
import io.github.danielhp95.caracole.server.http.Refused
import io.github.danielhp95.caracole.server.http.Response
import io.github.danielhp95.caracole.server.http.Route
import io.github.danielhp95.caracole.server.jobs.JobQueue
import io.github.danielhp95.caracole.server.page.MirrorPageData
import io.github.danielhp95.caracole.server.page.PhonePageData
import io.github.danielhp95.caracole.server.routes.LyricsRoutes
import io.github.danielhp95.caracole.server.testing.TestApp
import io.github.danielhp95.caracole.server.testing.WebJson
import io.github.danielhp95.caracole.server.testing.bytes
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Job
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import java.io.File
import java.net.URLEncoder
import java.nio.file.Files
import java.time.Instant

/**
 * vectors/web/lyrics_routes.jsonl (tests/test_conformance_lyrics_routes.py, whose docstring says what each record
 * holds): each scene's fixture loaded into a database of its own, then each record over it asked of the phone's
 * LyricsRoutes at the vectors' time, over a queue that runs nothing (the record's `queued` forms posted to it first):
 * a refusal's status, title and words, or the answer's status, JSON body, Location and the job queued (its title, key,
 * steps, display, stages) and how many the queue holds.
 */
object LyricsRoutesReplay {
    const val VECTOR = "web/lyrics_routes.jsonl"
    private const val NOW = "2026-11-03T12:00:00Z"
    private val NOWHERE = CoroutineScope(Job().apply { cancel() })

    fun replay(misses: Misses) {
        val all = Corpus.lines(VECTOR).filter { it["header"] != JsonPrimitive(true) }
        var at = 0
        while (at < all.size) {
            val fixture = all[at]
            check(fixture["fn"] == JsonPrimitive("fixture")) { "a record before its scene's fixture: ${fixture["fn"]}" }
            val scene = fixture.getValue("scene").jsonPrimitive.content
            val asked = all.drop(at + 1).takeWhile { it["fn"] != JsonPrimitive("fixture") }
            at += 1 + asked.size
            val dir = Files.createTempDirectory("caracole-lyrics-routes").toFile()
            try {
                TestDb.fresh(dir).use { database ->
                    database.writeBlocking { db ->
                        Fixtures.loadRecords(db, fixture.getValue("records").jsonArray.map { it.jsonObject },
                                             File(dir, "library").apply { mkdirs() }, scene)
                    }
                    for (r in asked) request(misses, database, dir, r)
                }
            } finally {
                dir.deleteRecursively()
            }
        }
    }

    private fun request(misses: Misses, database: Database, dir: File, r: JsonObject) {
        val fn = r.getValue("fn").jsonPrimitive.content
        val case = "$fn ${r.getValue("scene").jsonPrimitive.content}: ${r.getValue("case").jsonPrimitive.content}"
        val queue = JobQueue(NOWHERE)
        val routes = LyricsRoutes(parts(database, dir, queue), clock = { Instant.parse(NOW) })
        val (method, path) = fn.split(' ', limit = 2)
        val route: Route = routes.routes.firstOrNull { it.method == method && it.path == path }
            ?: return misses.check(false) { "$case: no route of the phone's" }
        fun post(form: JsonObject): Response = route.post!!.answer(
            TestApp.request("POST", path, mapOf("accept" to "application/json"), ByteArray(0), TestApp.SECRET),
            mapOf("csrf" to "tok") + form.mapValues { it.value.jsonPrimitive.content })
        val out = r.getValue("out").jsonObject
        val answer: Response = try {
            if (method == "GET") {
                val query = r.getValue("query").jsonObject.entries.joinToString("&") { (k, v) ->
                    "$k=${URLEncoder.encode(v.jsonPrimitive.content, Charsets.UTF_8)}"
                }
                route.get!!.answer(TestApp.request("GET", "$path?$query", mapOf("accept" to "application/json"),
                                                   ByteArray(0), TestApp.SECRET))
            } else {
                for (earlier in r["queued"]?.jsonArray.orEmpty()) post(earlier.jsonObject)
                post(r.getValue("form").jsonObject)
            }
        } catch (e: Refused) {
            val got = JsonObject(linkedMapOf("message" to JsonPrimitive(e.message), "status" to JsonPrimitive(e.status),
                                             "title" to JsonPrimitive(e.title)))
            misses.check("job" !in out && "body" !in out && got == out) { "$case: refused $got, caracole serve's $out" }
            return
        }
        if ("status" !in out || "message" in out) {
            return misses.check(false) { "$case: answered ${answer.status}, caracole serve refused $out" }
        }
        misses.check(answer.status == out.getValue("status").jsonPrimitive.content.toInt()) {
            "$case: status ${answer.status}, caracole serve's ${out["status"]}"
        }
        out["body"]?.let { want ->
            val body = Json.parseToJsonElement(answer.bytes.toString(Charsets.UTF_8))
            WebJson.difference(want, body)?.let { misses.check(false) { "$case: its answer at $it" } }
        }
        out["location"]?.let { want ->
            val location = answer.headers.firstOrNull { it.first.equals("location", ignoreCase = true) }?.second
            misses.check(location == want.jsonPrimitive.content) { "$case: to $location, caracole serve's $want" }
        }
        val python = out["job"] as? JsonObject ?: return
        val jobs = queue.snapshot()
        misses.check(jobs.size == out.getValue("jobs").jsonPrimitive.content.toInt()) { "$case: ${jobs.size} jobs queued" }
        val job = jobs.last()
        val phone = JsonObject(linkedMapOf(
            "display" to JsonPrimitive(job.display), "key" to JsonPrimitive(job.key),
            "stages" to JsonArray(job.stages.map { JsonArray(listOf(JsonPrimitive(it.name), JsonPrimitive(it.label))) }),
            "steps" to JsonArray(job.steps.map { JsonArray(listOf(JsonPrimitive(it.label), JsonArray(it.args.map(::JsonPrimitive)))) }),
            "title" to JsonPrimitive(job.spec.title),
        ))
        WebJson.difference(python, phone)?.let { misses.check(false) { "$case: its job at $it: $phone" } }
    }

    /** The phone's parts over [database]: its settings the database's (kv `phone:settings`), its cards its own. */
    private fun parts(database: Database, dir: File, queue: JobQueue): PhoneParts {
        val state = File(dir, "state")
        val store = LibraryStore(File(dir, "library"))
        val config = { database.read { PhoneConfig.read(it) } }
        return PhoneParts(database, store, state, config, queue, PhonePageData(MirrorPageData(null), store),
                          { Clients(config(), File(state, "cache"), { RefusingTransport }, Pacing.REAL) },
                          SongPages.NONE, SongbookPages.NONE, Alerts.NONE, Pacing.REAL, searchesLacuerda = false)
    }
}
