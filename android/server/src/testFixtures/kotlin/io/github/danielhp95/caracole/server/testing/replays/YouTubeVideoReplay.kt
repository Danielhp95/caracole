package io.github.danielhp95.caracole.server.testing.replays

import io.github.danielhp95.caracole.core.youtube.DayBudget
import io.github.danielhp95.caracole.core.config.PhoneConfig
import io.github.danielhp95.caracole.core.db.Db
import io.github.danielhp95.caracole.core.health.Alerts
import io.github.danielhp95.caracole.core.http.HttpAnswer
import io.github.danielhp95.caracole.core.library.AudioStore
import io.github.danielhp95.caracole.core.library.LibraryStore
import io.github.danielhp95.caracole.core.lookup.Clients
import io.github.danielhp95.caracole.core.lookup.Pacing
import io.github.danielhp95.caracole.core.lookup.SongPages
import io.github.danielhp95.caracole.core.lookup.SongbookPages
import io.github.danielhp95.caracole.core.testing.AreaReplay
import io.github.danielhp95.caracole.core.testing.Corpus
import io.github.danielhp95.caracole.core.testing.FakeTransport
import io.github.danielhp95.caracole.core.testing.Misses
import io.github.danielhp95.caracole.core.testing.TestDb
import io.github.danielhp95.caracole.core.youtube.HostGate
import io.github.danielhp95.caracole.core.youtube.Thumbs
import io.github.danielhp95.caracole.core.youtube.YouTubeAudio
import io.github.danielhp95.caracole.core.youtube.YouTubeData
import io.github.danielhp95.caracole.core.youtube.YouTubeEngine
import io.github.danielhp95.caracole.core.youtube.YtDlpGate
import io.github.danielhp95.caracole.core.youtube.YtDlpProcess
import io.github.danielhp95.caracole.server.PhoneParts
import io.github.danielhp95.caracole.server.jobs.CommandExit
import io.github.danielhp95.caracole.server.jobs.CommandRunner
import io.github.danielhp95.caracole.server.jobs.JobQueue
import io.github.danielhp95.caracole.server.lookups.YouTubeVideoRunner
import io.github.danielhp95.caracole.server.page.MirrorPageData
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.runBlocking
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
import java.io.File
import java.nio.file.Files
import java.time.Instant
import java.util.Base64

/**
 * `caracole youtube --video=URL|ID --progress` replayed from the computer's records (vectors/youtube/video_cmd.jsonl,
 * written by tests/test_conformance_youtube.py, whose comment over its records says what each holds), area
 * `youtube-video`: each scene's kv texts and events written on a fresh database, a thumbnail kept before written in
 * the phone's cache, YouTube and its image host on or off in the phone's settings (YouTube's pause none, as the
 * record's), every clock at its `now`; then the phone's own [YouTubeVideoRunner] given the command line, its yt-dlp
 * the record's answer for the video ([YouTubeSheetReplay.Plan], FakeYtDlp's plan) through a gate of no host, its image
 * host a [FakeTransport] of the record's answer (none asked of it where it has none).
 *
 * Compared with Python's: the exit (and an exit 2's words), the lines, the progress events, each yt-dlp run's target,
 * the image host's addresses asked, the kv texts changed, the events (provider, run, url, status, decision), the
 * thumbnail kept after and the providers whose block was told. Apart, as the record says: kv `http:last_request:`
 * (the phone's runner keeps YouTube's there too) and the events' times. Its `checked_jpeg` records are core's
 * (YouTubeReplay).
 */
object YouTubeVideoReplay : AreaReplay {
    override val area = "youtube-video"
    const val VECTOR = "youtube/video_cmd.jsonl"

    override fun replay(misses: Misses) {
        for (record in cases()) {
            for (f in one(record)) misses.check(false) { f }
            misses.check(true) { "" }
        }
    }

    fun cases(): List<JsonObject> = Corpus.lines(VECTOR).filter { "case" in it }

    /** The differences of [record] replayed, each "case: what differs". */
    fun one(record: JsonObject): List<String> {
        val kw = record.getValue("kw").jsonObject
        val id = kw.getValue("video_id").jsonPrimitive.content
        val plan = JsonObject(mapOf("searches" to JsonObject(emptyMap()), "videos" to videos(id, kw["video"])))
        return command(record, listOf("youtube", "--video", kw.getValue("link").jsonPrimitive.content, "--progress"),
                       plan) { parts, engine -> YouTubeVideoRunner(parts, engine, routeWhy = { null }) }
    }

    /**
     * The differences of a `caracole youtube` command's [record] (video_cmd.jsonl's shape, search_cmd.jsonl's too)
     * replayed: [args] given to the runner [make] builds over the scene's phone, its yt-dlp FakeYtDlp's [answers].
     */
    fun command(record: JsonObject, args: List<String>, answers: JsonObject,
                make: (PhoneParts, YouTubeEngine) -> CommandRunner): List<String> {
        val case = record.getValue("case").jsonPrimitive.content
        val found = ArrayList<String>()
        fun check(ok: Boolean, what: () -> String) {
            if (!ok) found += "$case: ${what()}"
        }
        val kw = record.getValue("kw").jsonObject
        val want = record.getValue("out").jsonObject
        val apart = record["apart"]?.jsonObject?.get("kv")?.jsonArray?.map { it.jsonPrimitive.content }.orEmpty()
        val now = Instant.parse(record.getValue("now").jsonPrimitive.content)
        val dir = Files.createTempDirectory("caracole-youtube-command").toFile()
        val scope = CoroutineScope(SupervisorJob())
        try {
            val state = File(dir, "state").apply { mkdirs() }
            val cache = File(state, "cache")
            TestDb.fresh(File(dir, "db").apply { mkdirs() }).use { database ->
                val id = kw.getValue("video_id").jsonPrimitive.content
                database.writeBlocking { db ->
                    for ((k, v) in kw.getValue("kv").jsonObject) db.kvSet(k, v.jsonPrimitive.content)
                    for (e in kw.getValue("events").jsonArray) {
                        val (run, at, provider) = e.jsonArray.map { it.jsonPrimitive.content }
                        db.execute("INSERT INTO events (run, at, provider, url, status, decision, message) " +
                                       "VALUES (?, ?, ?, ?, NULL, 'ok', NULL)", run, at, provider,
                                   YouTubeData.read().watchUrl(id))
                    }
                }
                val thumbs = Thumbs(cache)
                kw["kept"]?.takeIf { it !is JsonNull }?.let { kept ->
                    thumbs.path(id).apply { parentFile.mkdirs() }.writeBytes(Base64.getDecoder().decode(kept.jsonPrimitive.content))
                }
                val kvBefore = database.read { kv(it, apart) }
                val eventsBefore = database.read { db -> db.one("SELECT COALESCE(MAX(id), 0) FROM events") { it.long(0)!! }!! }
                val defaults = PhoneConfig.DEFAULTS
                val config = defaults.copy(providers = defaults.providers +
                    ("youtube" to defaults.provider("youtube").copy(delay = 0.0 to 0.0,
                                                                     enabled = kw.getValue("youtube").jsonPrimitive.boolean)) +
                    ("ytimg" to defaults.provider("ytimg").copy(enabled = kw.getValue("ytimg").jsonPrimitive.boolean)))
                val thumb = kw["thumb"]?.takeIf { it !is JsonNull }?.jsonObject
                val transport = FakeTransport(if (thumb == null) emptyMap() else mapOf(
                    "GET " + YouTubeData.read().json.getValue("thumb").jsonObject.getValue("url").jsonPrimitive.content
                        .replace("{id}", id) to HttpAnswer(thumb.getValue("status").jsonPrimitive.int,
                            listOf("content-type" to "image/jpeg"),
                            Base64.getDecoder().decode(thumb.getValue("base64").jsonPrimitive.content))))
                val pacing = Pacing(sleep = {}, draws = { low, high -> low + (high - low) * 0.5 },
                                    wallSeconds = { now.epochSecond.toDouble() }, monotonic = { 0.0 }, clock = { now })
                val alerted = ArrayList<String>()
                val alerts = object : Alerts {
                    override fun blocked(provider: String, until: Instant?, message: String) {
                        alerted += provider
                    }
                    override fun failed(title: String, line: String) {}
                }
                val lib = LibraryStore(File(dir, "library").apply { mkdirs() }, File(state, AudioStore.FOLDER),
                                       YouTubeAudio.folder(cache))
                val parts = PhoneParts(database, lib, state, { config }, JobQueue(scope), MirrorPageData(null),
                                       { Clients(config, cache, { transport }, pacing) }, SongPages.NONE,
                                       SongbookPages.NONE, alerts, pacing, searchesLacuerda = false)
                val plan = YouTubeSheetReplay.Plan(answers)
                val engine = object : YouTubeEngine {
                    override fun ready(): String? = null
                    override fun process(): YtDlpProcess = plan
                    override fun gate(): YtDlpGate = NoHost
                    override val qjs = File("/qjs")
                    override val cacheDir = cache
                }
                val told = AudioSheetReplay.Told()
                val (exit, error) = try {
                    runBlocking {
                        make(parts, engine).run(args, told)
                    }
                    0 to null
                } catch (e: CommandExit) {
                    e.code to e.message
                }
                check(exit == want.getValue("exit").jsonPrimitive.int) { "exited $exit ($error), Python's ${want["exit"]}" }
                want["error"]?.takeIf { it !is JsonNull }?.let { w ->
                    check(error == w.jsonPrimitive.content) { "said “$error”, Python's “${w.jsonPrimitive.content}”" }
                }
                val lines = JsonArray(told.said.map(::JsonPrimitive))
                if (exit == 0) check(lines == want["lines"]) { "its lines $lines, Python's ${want["lines"]}" }
                val progress = JsonArray(told.events.map { JsonArray(it.jsonArray.drop(1)) })
                check(progress == want["progress"]) { "told $progress,\n  Python's ${want["progress"]}" }
                val runs = JsonArray(plan.runs.map { it.getValue("target") })
                check(runs == want["runs"]) { "yt-dlp ran $runs, Python's ${want["runs"]}" }
                val asked = JsonArray(transport.said.map { JsonPrimitive(it.removePrefix("GET ")) })
                check(asked == want["asked"]) { "the image host was asked $asked, Python's ${want["asked"]}" }
                database.read { db ->
                    val kvAfter = kv(db, apart)
                    val changed = JsonObject((kvBefore.keys + kvAfter.keys).filter { kvBefore[it] != kvAfter[it] }.sorted()
                        .associateWith { k -> kvAfter[k]?.let(::JsonPrimitive) ?: JsonNull })
                    check(changed == want["kv"]) { "kv changed $changed,\n  Python's ${want["kv"]}" }
                    val events = JsonArray(db.query("SELECT provider, run, url, status, decision FROM events WHERE id > ? " +
                                                        "ORDER BY id", eventsBefore) { r ->
                        JsonArray(listOf(JsonPrimitive(r.text(0)), JsonPrimitive(r.text(1)), JsonPrimitive(r.text(2)),
                                         r.long(3)?.let(::JsonPrimitive) ?: JsonNull, JsonPrimitive(r.text(4))))
                    })
                    check(events == want["events"]) { "events $events,\n  Python's ${want["events"]}" }
                }
                val kept = thumbs.path(id).takeIf { it.isFile }?.let { JsonPrimitive(AudioSheetReplay.sha256(it.readBytes())) }
                    ?: JsonNull
                check(kept == want["thumb"]) { "the thumbnail kept $kept, Python's ${want["thumb"]}" }
                check(JsonArray(alerted.map(::JsonPrimitive)) == want["alerts"]) { "told $alerted's blocks, Python's ${want["alerts"]}" }
            }
        } finally {
            scope.cancel()
            dir.deleteRecursively()
        }
        return found
    }

    /** FakeYtDlp's plan of the video, as `fake.video` makes it of the record's answer: its fields, the channel its
     * uploader too, or its error; none for a video never asked of it. */
    private fun videos(id: String, answer: JsonElement?): JsonObject {
        if (answer == null || answer is JsonNull) return JsonObject(emptyMap())
        val a = answer.jsonObject
        val channel = a["channel"] ?: JsonPrimitive("")
        val spec = linkedMapOf("id" to JsonPrimitive(id), "title" to (a["title"] ?: JsonPrimitive("")), "channel" to channel,
                               "uploader" to channel, "duration" to (a["duration"] ?: JsonPrimitive(0)))
        for ((k, v) in a) if (k !in spec) spec[k] = v
        return JsonObject(mapOf(id to JsonObject(spec)))
    }

    /** The kv texts a job may change, those compared apart left out. */
    private fun kv(db: Db, apart: List<String>): Map<String, String> =
        db.query("SELECT key, value FROM kv ORDER BY key") { it.text(0)!! to it.text(1)!! }
            // DayBudget's reservations are the phone's own (Python's runner reserves none).
            .filter { (k, _) -> k != DayBudget.RESERVED && apart.none { k.startsWith(it) } }.toMap()

    /** A gate that lets yt-dlp reach no host: the plan answers every run itself. */
    private object NoHost : YtDlpGate {
        override val proxyArg = "http://replay:secret@127.0.0.1:9"
        override fun log(): Map<String, HostGate.HostUse> = emptyMap()
        override fun close() {}
    }
}
