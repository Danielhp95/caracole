package io.github.danielhp95.caracole.server.testing.replays

import io.github.danielhp95.caracole.core.config.PhoneConfig
import io.github.danielhp95.caracole.core.db.Database
import io.github.danielhp95.caracole.core.health.Alerts
import io.github.danielhp95.caracole.core.library.AudioStore
import io.github.danielhp95.caracole.core.library.LibraryStore
import io.github.danielhp95.caracole.core.lookup.Clients
import io.github.danielhp95.caracole.core.lookup.Pacing
import io.github.danielhp95.caracole.core.lookup.SongPages
import io.github.danielhp95.caracole.core.lookup.SongbookPages
import io.github.danielhp95.caracole.core.testing.Corpus
import io.github.danielhp95.caracole.core.testing.Fixtures
import io.github.danielhp95.caracole.core.testing.Misses
import io.github.danielhp95.caracole.core.testing.Record
import io.github.danielhp95.caracole.core.testing.RefusingTransport
import io.github.danielhp95.caracole.server.PhoneParts
import io.github.danielhp95.caracole.server.http.Request
import io.github.danielhp95.caracole.server.http.Response
import io.github.danielhp95.caracole.server.jobs.JobQueue
import io.github.danielhp95.caracole.server.page.MirrorPageData
import io.github.danielhp95.caracole.server.page.PhonePageData
import io.github.danielhp95.caracole.server.routes.AudioRoutes
import io.github.danielhp95.caracole.server.testing.TestApp
import io.github.danielhp95.caracole.server.testing.json
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Job
import kotlinx.serialization.json.Json
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
import java.io.File
import java.io.InputStream
import java.nio.file.Files
import java.nio.file.attribute.PosixFilePermissions
import java.util.Base64

/**
 * vectors/web/audio_routes.jsonl (tests/test_conformance_audio_routes.py's docstring has the shapes), answered by the
 * phone's AudioRoutes as caracole serve answered it:
 *
 * - [routes]: each scene over a fresh copy of the vector's library (its fixture, `{state}` this phone's state folder,
 *   the store's files written there), the phone's App with AudioRoutes alone and a queue that runs nothing; each
 *   step's request sent as the page's script sends it (the phone's host and origin for caracole serve's), its
 *   upload read by an examiner that answers what the store's reader read of it on the computer (the step's `audio`;
 *   null: it refuses the file); its status and its JSON Python's, each upload's id masked in the order it was
 *   staged, a job's view by its id; a body past the route's limit sent by its Content-Length alone, a stream that
 *   fails if read. After the last step, the uploads still staged and the queue's jobs (title, key, commands,
 *   display; a job caracole serve wrote wanted.txt for has the phone's note, none). A scene where caracole serve
 *   makes no sheet is the phone's with the reason `<reason>`.
 * - [limits]: each route's declared kind and limit.
 */
object AudioRoutesReplay {
    const val VECTOR = "web/audio_routes.jsonl"
    private const val CSRF = "tok"
    private const val REASON = "<reason>"
    private val NOWHERE = CoroutineScope(Job().apply { cancel() })

    fun records(): List<Record> = Corpus.records(VECTOR)

    fun routes(misses: Misses) {
        val records = records()
        val fixture = records.first { it.fn == "fixture" }
        val scenes = records.filter { it.fn == "scene" }
        misses.check(scenes.size >= 8) { "audio_routes.jsonl holds ${scenes.size} scenes" }
        for (scene in scenes) inFolder("audio-routes") { dir -> scene(misses, dir, fixture, scene) }
    }

    fun limits(misses: Misses) = inFolder("audio-routes-limits") { dir ->
        val record = records().single { it.fn == "limits" }
        val routes = withRoutes(dir, null) { it.routes }
        val declared = JsonObject(routes.associate { route ->
            "${route.method} ${route.path}" to JsonArray(listOf(JsonPrimitive(route.body), JsonPrimitive(route.limit)))
        })
        misses.check(declared == record.out) { "the routes declare $declared, Python's ${record.out}" }
        misses.check(routes.single { it.path == "/audio/upload" }.spool) { "POST /audio/upload isn't spooled" }
    }

    private fun <T> withRoutes(dir: File, problem: String?, block: (AudioRoutes) -> T): T {
        val app = TestApp(dir)
        try {
            val queue = JobQueue(NOWHERE)
            val store = AudioStore(File(dir, "state"), READS_NOTHING)
            return block(AudioRoutes(parts(app.database, dir, queue), store, problem = { problem }))
        } finally {
            app.close()
        }
    }

    private val READS_NOTHING = AudioStore.Examiner { _, _ -> throw IllegalStateException("no file is read here") }

    private class Reader : AudioStore.Examiner {
        var next: JsonElement? = null
        var read = false
        override fun examine(file: File, format: String): AudioStore.Audio {
            read = true
            val audio = next as? JsonObject ?: throw IllegalStateException("the computer's reader refused this file")
            val tags = audio.getValue("tags").jsonObject.mapValues { (_, v) ->
                if (v is JsonNull) emptyList() else listOf(v.jsonPrimitive.content)
            }
            return AudioStore.Audio(audio.getValue("format").jsonPrimitive.content,
                                    audio.getValue("duration").jsonPrimitive.double, tags)
        }
    }

    private fun scene(misses: Misses, dir: File, fixture: Record, scene: Record) {
        val name = scene.extra.getValue("scene").jsonPrimitive.content
        val can = scene.extra.getValue("can").jsonPrimitive.boolean
        val state = File(dir, "state").apply { mkdirs() }
        val reader = Reader()
        val queue = JobQueue(NOWHERE)
        val store = AudioStore(state, reader)
        lateinit var routes: AudioRoutes
        val app = TestApp(dir, csrf = CSRF, modules = { database ->
            routes = AudioRoutes(parts(database, dir, queue), store, problem = { if (can) null else REASON })
            listOf(routes)
        })
        try {
            val folder = File(state, AudioStore.FOLDER).apply { mkdirs() }
            Files.setPosixFilePermissions(folder.toPath(), PosixFilePermissions.fromString("rwx------"))
            for ((file, data) in fixture.extra.getValue("store").jsonObject) {
                File(folder, file).writeBytes(Base64.getDecoder().decode(data.jsonPrimitive.content))
            }
            val text = fixture.extra.getValue("records").toString()
                .replace("{state}", state.path.replace("\\", "\\\\").replace("\"", "\\\""))
            app.database.writeBlocking { db ->
                Fixtures.loadRecords(db, Json.parseToJsonElement(text).jsonArray.map { it.jsonObject }, app.libraryDir)
            }
            val ids = LinkedHashMap<String, String>()  // real id to "<upload N>", as they were staged
            fun mask(e: JsonElement): JsonElement = when (e) {
                is JsonObject -> JsonObject(e.mapValues { mask(it.value) })
                is JsonArray -> JsonArray(e.map(::mask))
                is JsonPrimitive -> if (!e.isString) e else JsonPrimitive(ids.entries.fold(e.content) { t, (id, m) -> t.replace(id, m) })
                else -> e
            }
            fun real(text: String): String = ids.entries.firstOrNull { it.value == text }?.key ?: text
            for ((n, s) in scene.extra.getValue("steps").jsonArray.withIndex()) {
                val step = s.jsonObject
                val ask = step.getValue("ask").jsonObject
                val note = "$name, step ${n + 1}: ${ask.getValue("method").jsonPrimitive.content} " +
                    ask.getValue("target").jsonPrimitive.content
                reader.next = step["audio"]
                reader.read = false
                val answer = app.handle(request(ask, ::real))
                misses.check(reader.read == ("audio" in step)) {
                    "$note: the examiner ${if (reader.read) "read" else "didn't read"} the file, the computer's " +
                        if ("audio" in step) "did" else "didn't"
                }
                var out = answer.json
                if (answer.status == 200 && ask.getValue("target").jsonPrimitive.content.startsWith("/audio/upload")) {
                    val id = out.jsonObject.getValue("upload").jsonPrimitive.content
                    ids.putIfAbsent(id, "<upload ${ids.size + 1}>")
                }
                val job = (out as? JsonObject)?.get("job") as? JsonObject
                if (job != null) out = JsonObject(mapOf("job" to JsonObject(mapOf("id" to job.getValue("id")))))
                val want = step.getValue("out")
                val status = step.getValue("status").jsonPrimitive.int
                misses.check(answer.status == status && mask(out) == want) {
                    "$note: ${answer.status} ${mask(out)}\n   Python: $status $want"
                }
                // A JsonObject's == is a map's, order-blind, and `out` is written with sorted keys: the members' order
                // is held by `keys`, Python's as it wrote them.
                val wantKeys = step["keys"]?.jsonArray?.map { it.jsonPrimitive.content }
                misses.check(wantKeys != null && keyOrder(out) == wantKeys) {
                    "$note: members in the order ${keyOrder(out)}\n   Python: $wantKeys"
                }
            }
            val staged = folder.list().orEmpty().mapNotNull { AudioStore.STAGED_AUDIO.matchEntire(it)?.groupValues?.get(1) }
                .map { ids[it] ?: it }.sorted()
            val wantStaged = scene.extra.getValue("staged").jsonArray.map { it.jsonPrimitive.content }
            misses.check(staged == wantStaged) { "$name: staged after it $staged, Python's $wantStaged" }
            val jobs = JsonArray(queue.snapshot().map { j ->
                JsonObject(linkedMapOf(
                    "title" to JsonPrimitive(j.spec.title), "key" to JsonPrimitive(j.key),
                    "steps" to JsonArray(j.steps.map { JsonArray(listOf(JsonPrimitive(it.label), JsonArray(it.args.map(::JsonPrimitive)))) }),
                    "display" to JsonPrimitive(j.display), "note" to JsonPrimitive(j.spec.note),
                ))
            })
            val wantJobs = JsonArray(scene.extra.getValue("jobs").jsonArray.map { e ->
                val o = e.jsonObject
                // the phone writes no wanted.txt: no line to name
                val noted = if (o.getValue("wanted").jsonPrimitive.boolean) JsonPrimitive("") else o.getValue("note")
                JsonObject(o - "wanted" + ("note" to noted))
            })
            misses.check(mask(jobs) == wantJobs) { "$name: jobs ${mask(jobs)}\n   Python: $wantJobs" }
        } finally {
            app.close()
        }
    }

    /** The step's request, as the page's script sends it to the phone (the phone's host and its own origin). */
    private fun request(ask: JsonObject, real: (String) -> String): Request {
        val kind = ask.getValue("kind").jsonPrimitive.content
        val headers = linkedMapOf<String, String?>("accept" to "application/json", "sec-fetch-site" to "same-origin",
                                                   "origin" to "http://${TestApp.HOST}")
        val body = ask.getValue("body")
        var stream: InputStream? = null
        val bytes: ByteArray = when (kind) {
            "form" -> {
                headers["content-type"] = "application/x-www-form-urlencoded"
                TestApp.form(body.jsonArray.map { it.jsonArray[0].jsonPrimitive.content to real(it.jsonArray[1].jsonPrimitive.content) })
            }
            "json" -> {
                headers["content-type"] = "application/json"
                headers[TestApp.TOKEN_HEADER] = CSRF
                unmasked(body, real).toString().toByteArray()
            }
            else -> {
                headers["content-type"] = "application/octet-stream"
                headers[TestApp.TOKEN_HEADER] = CSRF
                if (body is JsonObject) {  // past the route's limit: its Content-Length alone, never read
                    headers["content-length"] = body.getValue("length").jsonPrimitive.content
                    stream = object : InputStream() {
                        override fun read(): Int = throw AssertionError("a body past the route's limit was read")
                    }
                    ByteArray(0)
                } else Base64.getDecoder().decode(body.jsonPrimitive.content)
            }
        }
        for ((name, value) in ask.getValue("headers").jsonObject) headers[name] = (value as? JsonPrimitive)?.takeIf { it !is JsonNull }?.content
        val target = ask.getValue("target").jsonPrimitive.content
        val made = TestApp.request("POST", target, headers, bytes, TestApp.SECRET)
        return if (stream != null) made.copy(stream = stream) else made
    }

    private fun unmasked(e: JsonElement, real: (String) -> String): JsonElement = when (e) {
        is JsonObject -> JsonObject(e.mapValues { unmasked(it.value, real) })
        is JsonArray -> JsonArray(e.map { unmasked(it, real) })
        is JsonPrimitive -> if (e.isString) JsonPrimitive(real(e.content)) else e
        else -> e
    }

    private fun parts(database: Database, dir: File, queue: JobQueue): PhoneParts {
        val state = File(dir, "state")
        val store = LibraryStore(File(dir, "library"), File(state, AudioStore.FOLDER))
        val config = { database.read { PhoneConfig.read(it) } }
        return PhoneParts(database, store, state, config, queue, PhonePageData(MirrorPageData(null), store),
                          { Clients(config(), File(state, "cache"), { RefusingTransport }, Pacing.REAL) },
                          SongPages.NONE, SongbookPages.NONE, Alerts.NONE, Pacing.REAL, searchesLacuerda = false)
    }

    /** Every member of [value] in its order, by its path ("song.id", "jobs.0.id"): the generator's key_order. */
    private fun keyOrder(value: JsonElement, at: String = ""): List<String> = when (value) {
        is JsonObject -> value.entries.flatMap { (key, member) -> listOf(at + key) + keyOrder(member, "$at$key.") }
        is JsonArray -> value.withIndex().flatMap { (n, item) -> keyOrder(item, "$at$n.") }
        else -> emptyList()
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
