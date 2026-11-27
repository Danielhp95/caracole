package io.github.danielhp95.caracole.server.testing.replays

import io.github.danielhp95.caracole.core.config.PhoneConfig
import io.github.danielhp95.caracole.core.db.Database
import io.github.danielhp95.caracole.core.db.Db
import io.github.danielhp95.caracole.core.health.Alerts
import io.github.danielhp95.caracole.core.json.PyJson
import io.github.danielhp95.caracole.core.library.AudioStore
import io.github.danielhp95.caracole.core.library.LibraryStore
import io.github.danielhp95.caracole.core.lookup.Clients
import io.github.danielhp95.caracole.core.lookup.Pacing
import io.github.danielhp95.caracole.core.lookup.SongPages
import io.github.danielhp95.caracole.core.lookup.SongbookPages
import io.github.danielhp95.caracole.core.testing.AreaReplay
import io.github.danielhp95.caracole.core.testing.Corpus
import io.github.danielhp95.caracole.core.testing.FakeTransport
import io.github.danielhp95.caracole.core.testing.Fixtures
import io.github.danielhp95.caracole.core.testing.Misses
import io.github.danielhp95.caracole.core.testing.TestDb
import io.github.danielhp95.caracole.core.youtube.HostGate
import io.github.danielhp95.caracole.core.youtube.Ran
import io.github.danielhp95.caracole.core.youtube.YouTubeAudio
import io.github.danielhp95.caracole.core.youtube.YouTubeData
import io.github.danielhp95.caracole.core.youtube.YouTubeEngine
import io.github.danielhp95.caracole.core.youtube.YtDlpGate
import io.github.danielhp95.caracole.core.youtube.YtDlpProcess
import io.github.danielhp95.caracole.server.PhoneParts
import io.github.danielhp95.caracole.server.jobs.CommandExit
import io.github.danielhp95.caracole.server.jobs.JobQueue
import io.github.danielhp95.caracole.server.lookups.AudioRunner
import io.github.danielhp95.caracole.server.lookups.YouTubeSheetRunner
import io.github.danielhp95.caracole.server.page.MirrorPageData
import io.github.danielhp95.caracole.server.testing.replays.AudioSheetReplay.Tables
import io.github.danielhp95.caracole.server.testing.replays.AudioSheetReplay.Told
import io.github.danielhp95.caracole.viewer.autochords.ChordModels
import io.github.danielhp95.caracole.viewer.autochords.Heard
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.runBlocking
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.double
import kotlinx.serialization.json.int
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import kotlinx.serialization.json.long
import java.io.File
import java.nio.file.Files
import java.nio.file.attribute.FileTime
import java.time.Instant
import java.util.Base64

/**
 * `caracole youtube --song --sheet` replayed from the computer's records (vectors/lookup/youtube_sheet.jsonl, written by
 * tests/test_conformance_youtube_sheet.py, whose docstring says what each record holds), area `youtube-sheet`, as
 * [AudioSheetReplay] replays `caracole audio`: each record's fixture loaded (`{state}` its own state folder, `{cache}`
 * the phone's cache under it), its kv `sync:id` the record's `own`, the cache's and the store's files written with
 * their times, its lyrics sites served by a [FakeTransport], every clock at its `now`; then the phone's own
 * [YouTubeSheetRunner] given the command line caracole serve queues (`youtube --sheet --progress [--url=…] --song=…`),
 * its pages [SongPages.NONE], its chord models a fake answering `heard`, its examiner `audio`, its yt-dlp [Plan] (the
 * record's `ytdlp`, FakeYtDlp's plan: a search's entries, a video's bytes and time, or its error) through a gate of no
 * host. At the job's chords yield, never the download's, `at_yield`'s records and store files are written, as another
 * caracole wrote them meanwhile.
 *
 * Compared with Python's: AudioSheetReplay's (each stage's end, the song, the files readable, the stages as told, the
 * exit, the requests, the events, the rows, kv and library files changed, the store after, the maker the phone's), and
 * the yt-dlp runs (what each was, its target, a download's folder) and the cache's YouTube files after. Apart, as the
 * record says (`apart`): the lyrics stage's words, the events' runs, the pauses, and the kv the phone writes or the
 * computer does (`http:last_request:youtube` the runner's). And apart by design, the phone's own (the design's §5.4):
 * once its sheet is kept, the phone lets the video's audio go, so where Python's job kept a sheet the song's
 * `audio_path` and `audio_mtime` are none (its `updated_at` the job's), its record's `audio` none, and the file gone
 * from the cache: Python's after-state is so changed before it is compared ([letGo]).
 */
object YouTubeSheetReplay : AreaReplay {
    override val area = "youtube-sheet"
    const val VECTOR = "lookup/youtube_sheet.jsonl"

    override fun replay(misses: Misses) {
        for (record in Corpus.lines(VECTOR).filter { it["header"] != JsonPrimitive(true) }) {
            for (f in one(record)) misses.check(false) { f }
            misses.check(true) { "" }
        }
    }

    fun cases(): List<String> = Corpus.lines(VECTOR).filter { it["header"] != JsonPrimitive(true) }
        .map { it.getValue("case").jsonPrimitive.content }

    /** The differences of [record] replayed, each "case: what differs". */
    fun one(record: JsonObject): List<String> {
        val case = record.getValue("case").jsonPrimitive.content
        val found = ArrayList<String>()
        fun check(ok: Boolean, what: () -> String) {
            if (!ok) found += "$case: ${what()}"
        }
        val dir = Files.createTempDirectory("caracole-youtube-sheet").toFile()
        try {
            val state = File(dir, "state").apply { mkdirs() }
            val cache = File(state, "cache")
            val library = File(dir, "library").apply { mkdirs() }
            val path = state.absolutePath
            fun placedText(text: String) = text.replace("{cache}", cache.absolutePath).replace("{state}", path)
            val placed = Json.parseToJsonElement(placedText(record.toString())).jsonObject
            val kw = placed.getValue("kw").jsonObject
            val done = placed.getValue("out").jsonObject
            val apart = placed["apart"]?.jsonObject ?: JsonObject(emptyMap())
            val leaves = placed.getValue("leaves_out").jsonObject
            val prefixes = leaves["kv"]?.jsonArray?.map { it.jsonPrimitive.content }.orEmpty() +
                apart["kv"]?.jsonArray?.map { it.jsonPrimitive.content }.orEmpty()
            val names = leaves["files"]?.jsonArray?.map { it.jsonPrimitive.content }.orEmpty().toSet()
            val now = Instant.parse(placed.getValue("now").jsonPrimitive.content)
            val folder = YouTubeAudio.folder(cache)
            TestDb.fresh(File(dir, "db").apply { mkdirs() }).use { database ->
                database.writeBlocking { db ->
                    Fixtures.loadRecords(db, placed.getValue("fixture").jsonArray.map { it.jsonObject }, library, case)
                    db.kvSet("sync:id", kw.getValue("own").jsonPrimitive.content)
                }
                AudioSheetReplay.writeStore(File(state, AudioStore.FOLDER), kw["store"]?.jsonObject ?: JsonObject(emptyMap()))
                AudioSheetReplay.writeStore(folder, kw["cache"]?.jsonObject ?: JsonObject(emptyMap()))
                val before = database.read { Tables.of(it) }
                val kvBefore = database.read { AudioSheetReplay.kv(it, prefixes) }
                val filesBefore = AudioSheetReplay.files(library, names)
                val eventsBefore = database.read { db -> db.one("SELECT COALESCE(MAX(id), 0) FROM events") { it.long(0)!! }!! }
                val transport = FakeTransport(AudioSheetReplay.answers(placed["answers"]?.jsonObject ?: JsonObject(emptyMap())))
                val pacing = Pacing(sleep = {}, draws = { low, high -> low + (high - low) * 0.5 },
                                    wallSeconds = { now.epochSecond.toDouble() }, monotonic = { 0.0 }, clock = { now })
                val lib = LibraryStore(library, File(state, AudioStore.FOLDER), folder)
                val plan = Plan(kw.getValue("ytdlp").jsonObject)
                val result = job(kw, done, apart, database, lib, state, transport, pacing, plan, ::check)
                check(JsonArray(transport.said.map(::JsonPrimitive)) == done["requests"]) {
                    "requests ${transport.said}, Python's ${done["requests"]}"
                }
                check(plan.runs == done["runs"]) { "yt-dlp ran ${plan.runs}, Python's ${done["runs"]}" }
                // Python's after-state, the phone's let-go of the audio applied where its sheet was kept.
                val sheetKept = result.getValue("states").jsonObject["chords"] == JsonPrimitive("done")
                val songId = result["song_id"]?.takeIf { it !is JsonNull }?.jsonPrimitive?.long
                val wantRows = LinkedHashMap<String, JsonElement>()
                for ((table, rows) in before) wantRows[table] = JsonArray(rows.map { AudioSheetReplay.unmade(it, KEEP_PATHS, true) })
                for ((table, rows) in done.getValue("rows").jsonObject) wantRows[table] = rows
                val kvWant = LinkedHashMap<String, String?>(kvBefore)
                for ((k, v) in done.getValue("kv").jsonObject) kvWant[k] = (v as? JsonPrimitive)?.takeIf { it.isString }?.content
                val youtubeWant = LinkedHashMap(done.getValue("youtube").jsonObject)
                if (sheetKept && songId != null) letGo(songId, placed.getValue("now").jsonPrimitive.content, wantRows,
                                                       kvWant, youtubeWant)
                database.read { db ->
                    val events = JsonArray(db.query("SELECT provider, url, status, decision FROM events WHERE id > ? " +
                                                        "ORDER BY id", eventsBefore) { r ->
                        JsonArray(listOf(JsonPrimitive(r.text(0)), JsonPrimitive(r.text(1)),
                                         r.long(2)?.let(::JsonPrimitive) ?: JsonNull, JsonPrimitive(r.text(3))))
                    })
                    val want = JsonArray(done.getValue("events").jsonArray.map { JsonArray(it.jsonArray.drop(1)) })
                    check(events == want) { "events $events, Python's $want" }
                    val after = Tables.of(db).mapValues { (_, rows) -> rows.map { AudioSheetReplay.unmade(it, KEEP_PATHS, true) } }
                    for (table in after.keys - "events") {
                        check(JsonArray(after[table].orEmpty()) == wantRows[table]) {
                            "$table holds ${after[table]},\n  Python's ${wantRows[table]}"
                        }
                    }
                    val kvAfter = AudioSheetReplay.kv(db, prefixes)
                    val kvWanted = kvWant.filterValues { it != null }
                    check(kvAfter == kvWanted) {
                        val keys = (kvAfter.keys + kvWanted.keys).filter { kvAfter[it] != kvWanted[it] }.sorted()
                        "kv ${keys.associateWith { kvAfter[it] }}, Python's ${keys.associateWith { kvWanted[it] }}"
                    }
                }
                val filesAfter = AudioSheetReplay.files(library, names)
                val filesChanged = JsonObject((filesBefore.keys + filesAfter.keys)
                    .filter { filesBefore[it] != filesAfter[it] }.sorted()
                    .associateWith { p -> filesAfter[p]?.let(::JsonPrimitive) ?: JsonNull })
                check(filesChanged == done["library"]) { "files $filesChanged, Python's ${done["library"]}" }
                done["store"]?.let { want ->
                    val got = AudioSheetReplay.storeAfter(File(state, AudioStore.FOLDER))
                    check(got == want) { "the store holds $got, Python's $want" }
                }
                val youtube = JsonObject((folder.listFiles() ?: emptyArray()).filter { it.isFile }.sortedBy { it.name }
                                             .associate { it.name to JsonPrimitive(AudioSheetReplay.sha256(it.readBytes())) })
                check(youtube == JsonObject(youtubeWant)) { "the cache holds $youtube, the phone's of Python's $youtubeWant" }
                val parts = (folder.listFiles() ?: emptyArray()).filter { it.isDirectory }
                check(parts.isEmpty()) { "a download's own folder left: ${parts.map { it.name }}" }
            }
        } finally {
            dir.deleteRecursively()
        }
        return found
    }

    /** The phone's let-go of a song's YouTube audio once its sheet is kept (YouTubeAudio.letGo), on Python's after
     * state: the song unlinked (`updated_at` [stamp]), its record's `audio` none, its file gone from the cache. */
    private fun letGo(songId: Long, stamp: String, rows: MutableMap<String, JsonElement>, kv: MutableMap<String, String?>,
                      youtube: MutableMap<String, JsonElement>) {
        val songs = rows["songs"]?.jsonArray?.map { it.jsonObject }.orEmpty()
        val song = songs.firstOrNull { it["id"] == JsonPrimitive(songId) }
        val record = kv["youtube:$songId"]?.let { PyJson.loads(it).jsonObject } ?: return
        val audio = (record["audio"] as? JsonPrimitive)?.takeIf { it.isString }?.content ?: return
        if (song != null && song["audio_path"] == JsonPrimitive(audio)) {
            rows["songs"] = JsonArray(songs.map { row ->
                if (row !== song) row
                else JsonObject(row + mapOf("audio_path" to JsonNull, "audio_mtime" to JsonNull, "updated_at" to JsonPrimitive(stamp)))
            })
        }
        kv["youtube:$songId"] = PyJson.dumps(JsonObject(record + ("audio" to JsonNull)))
        youtube.remove(File(audio).name)
    }

    /** One `make_sheet` record through the phone's runner; Python's result, as said. */
    private fun job(kw: JsonObject, done: JsonObject, apart: JsonObject, database: Database, lib: LibraryStore,
                    state: File, transport: FakeTransport, pacing: Pacing, plan: Plan,
                    check: (Boolean, () -> String) -> Unit): JsonObject {
        val audio = kw.getValue("audio").jsonObject
        val examined = AudioStore.Audio(audio.getValue("format").jsonPrimitive.content,
                                        audio.getValue("duration").jsonPrimitive.double, emptyMap())
        val store = AudioStore(state, { _, _ -> examined }, freeSpace = { Long.MAX_VALUE })
        val heard = Heard.of(kw.getValue("heard"))
        val chords = object : ChordModels {
            override fun ready(): String? = null
            override val runtime: String = AudioSheetReplay.RUNTIME
            override fun hear(audio: File, onStep: (String) -> Unit, waiting: () -> Unit): Heard {
                onStep("setting up the models")
                onStep("hearing the chords")
                waiting()
                onStep("finding the beats")
                return heard
            }
        }
        val engine = object : YouTubeEngine {
            override fun ready(): String? = null
            override fun process(): YtDlpProcess = plan
            override fun gate(): YtDlpGate = NoHost
            override val qjs = File("/qjs")
            override val cacheDir = File(state, "cache")
        }
        val atYield = kw["at_yield"]?.takeIf { it !is JsonNull }?.jsonObject
        val scope = CoroutineScope(SupervisorJob())
        try {
            val parts = PhoneParts(database, lib, state, { PhoneConfig.DEFAULTS }, JobQueue(scope), MirrorPageData(null),
                                   { Clients(PhoneConfig.DEFAULTS, File(state, "cache"), { transport }, pacing) },
                                   SongPages.NONE, SongbookPages.NONE, Alerts.NONE, pacing, searchesLacuerda = false)
            val told = Told()
            var yielded = false
            told.onYield = { t ->
                if (atYield != null && !yielded && t.running == atYield.getValue("stage").jsonPrimitive.content) {
                    yielded = true
                    database.writeBlocking { db -> written(db, atYield.getValue("fixture").jsonArray.map { it.jsonObject }, lib) }
                    AudioSheetReplay.writeStore(File(state, AudioStore.FOLDER), atYield["store"]?.jsonObject ?: JsonObject(emptyMap()))
                }
            }
            val request = kw.getValue("request").jsonObject
            val url = request["url"]?.takeIf { it !is JsonNull }?.jsonPrimitive?.content
            val args = listOfNotNull("youtube", "--sheet", "--progress", url?.let { "--url=$it" },
                                     "--song=${request.getValue("artist").jsonPrimitive.content} - " +
                                         request.getValue("title").jsonPrimitive.content)
            val exit = try {
                runBlocking {
                    YouTubeSheetRunner(parts, engine, chords, store, problem = { null }, names = { AudioSheetReplay.NAMES },
                                       chordsProblem = { null }).run(args, told)
                }
                0
            } catch (e: CommandExit) {
                e.code
            }
            check(atYield == null || yielded) { "the job never yielded in its ${atYield?.get("stage")} stage" }
            val said = done.getValue("result").jsonObject
            val want = said.getValue("result").jsonObject
            check(exit == want.getValue("exit").jsonPrimitive.int) { "exited $exit, Python's ${want["exit"]}: ${told.said}" }
            val wantStates = want.getValue("states").jsonObject
            val wantDetails = want.getValue("details").jsonObject
            val apartStages = setOfNotNull("lyrics".takeIf { apart["lyrics"]?.jsonPrimitive?.content == "true" })
            check(told.states.keys == wantStates.keys) { "stages ${told.states.keys}, Python's ${wantStates.keys}" }
            for ((name, s) in wantStates) {
                check(told.states[name] == s.jsonPrimitive.content) { "$name ${told.states[name]}, Python's $s" }
                if (name in apartStages) continue
                check(told.details[name] == wantDetails[name]?.jsonPrimitive?.content) {
                    "$name said “${told.details[name]}”, Python's “${wantDetails[name]?.jsonPrimitive?.content}”"
                }
            }
            check((told.song?.first?.let(::JsonPrimitive) ?: JsonNull) == want["song_id"]) {
                "the song ${told.song}, Python's ${want["song_id"]}"
            }
            check(JsonObject(told.files.mapValues { JsonPrimitive(it.value) }) == want["files"]) {
                "readable ${told.files}, Python's ${want["files"]}"
            }
            fun outside(e: JsonElement): Boolean {
                val a = e.jsonArray
                return !(a[0].jsonPrimitive.content == "stage" && a[1].jsonPrimitive.content in apartStages)
            }
            val progress = JsonArray(told.events.filter(::outside))
            val wantProgress = JsonArray(said.getValue("progress").jsonArray.filter(::outside))
            check(progress == wantProgress) { "told $progress,\n  Python's $wantProgress" }
            val raw = database.read { db ->
                db.one("SELECT raw FROM versions WHERE provider = 'auto' ORDER BY id LIMIT 1") { it.text(0) }
            }?.let { PyJson.loads(it).jsonObject }
            val maker = done["maker"]
            if (maker != null && maker != JsonNull) {
                check(raw != null) { "no auto version, Python's maker $maker" }
                if (raw != null) {
                    val phone = JsonObject(linkedMapOf("made_on" to JsonPrimitive(AudioRunner.MADE_ON),
                                                       "made_by" to kw.getValue("own"),
                                                       "models" to JsonObject(AudioSheetReplay.NAMES.mapValues { JsonPrimitive(it.value) }),
                                                       "runtime" to JsonPrimitive(AudioSheetReplay.RUNTIME)))
                    val got = JsonObject(AudioSheetReplay.MAKER.filter { it in raw }.associateWith { raw.getValue(it) })
                    check(got == phone) { "the maker $got, the phone's $phone" }
                }
            }
            return want
        } finally {
            scope.cancel()
        }
    }

    /** What another caracole wrote at the yield: a new row inserted, a row it changed (one the database has by its
     * id) written over. */
    private fun written(db: Db, records: List<JsonObject>, lib: LibraryStore) {
        for (record in records) {
            val table = record["table"]?.jsonPrimitive?.content
            val row = record["row"]?.jsonObject
            val id = row?.get("id")?.jsonPrimitive?.long
            if (table != null && id != null && db.one("SELECT 1 FROM \"$table\" WHERE id = ?", id) { true } != null) {
                val columns = row.keys.filter { it != "id" }
                db.execute("UPDATE \"$table\" SET " + columns.joinToString(", ") { "\"$it\" = ?" } + " WHERE id = ?",
                           *columns.map { c -> row.getValue(c).let { v ->
                               when {
                                   v is JsonNull -> null
                                   v is JsonPrimitive && v.isString -> v.content
                                   v is JsonPrimitive && '.' in v.content -> v.double
                                   else -> v.jsonPrimitive.long
                               }
                           } }.toTypedArray(), id)
            } else {
                Fixtures.loadRecords(db, listOf(record), lib.libraryDir)
            }
        }
    }

    /** No folder: the rows compared with their paths as they are (Python's placed in the replay's folders), less the
     * maker's side alone. */
    private const val KEEP_PATHS = "\u0000"

    /** A gate that lets yt-dlp reach no host: the plan answers every run itself. */
    private object NoHost : YtDlpGate {
        override val proxyArg = "http://replay:secret@127.0.0.1:9"
        override fun log(): Map<String, HostGate.HostUse> = emptyMap()
        override fun close() {}
    }

    /**
     * tests/helpers/fake_ytdlp.py's FakeYtDlp as the phone's process sees it, from a record's plan: a search
     * (`ytsearchN:<query>`) prints its entries (at most N) as the playlist yt-dlp's JSON is; a video's download writes
     * its bytes where `-o` says, dated its `mtime`, and prints its fields with `filepath`; either fails as its
     * `stderr` and `exit` say; a video the plan lacks is unavailable. [runs] is what each run was, as the record's
     * `out.runs` names it.
     */
    class Plan(private val plan: JsonObject) : YtDlpProcess {
        val runs = ArrayList<JsonObject>()

        override fun run(argv: List<String>, timeoutS: Double, onLine: (String) -> Unit, waiting: () -> Unit): Ran {
            val target = argv[argv.indexOf("--") + 1]
            val download = "-o" in argv
            val what = if (download) "download" else if ("--skip-download" in argv) "video" else "search"
            runs += JsonObject(buildMap {
                if (download) {
                    val into = argv[argv.indexOf("-o") + 1]
                    if (into.endsWith("/" + YouTubeData.read().json.getValue("output_name").jsonPrimitive.content)) {
                        put("into", JsonPrimitive("<into>"))
                    }
                }
                put("target", JsonPrimitive(target))
                put("what", JsonPrimitive(what))
            })
            if (target.startsWith("ytsearch")) {
                val n = target.substring("ytsearch".length).substringBefore(':').toInt()
                val query = target.substringAfter(':')
                val spec = plan.getValue("searches").jsonObject[query]?.jsonObject ?: JsonObject(emptyMap())
                failed(spec)?.let { return it }
                val entries = spec["entries"]?.jsonArray.orEmpty().take(n)
                val out = JsonObject(linkedMapOf("_type" to JsonPrimitive("playlist"), "id" to JsonPrimitive(query),
                                                 "title" to JsonPrimitive(query), "entries" to JsonArray(entries)))
                return Ran(0, out.toString() + "\n", "")
            }
            val id = target.substringAfter("v=", "").take(11)
            val spec = plan.getValue("videos").jsonObject[id]?.jsonObject
                ?: return Ran(1, "", "ERROR: [youtube] $id: Video unavailable\n")
            failed(spec)?.let { return it }
            val fields = listOf("id", "title", "channel", "uploader", "duration").filter { it in spec }
                .associateWith { spec.getValue(it) }
            if (!download) return Ran(0, JsonObject(linkedMapOf("_type" to JsonPrimitive("video")) + fields).toString() + "\n", "")
            val template = argv[argv.indexOf("-o") + 1]
            val file = File(template.replace("%(ext)s", spec["ext"]?.jsonPrimitive?.content ?: "m4a"))
            file.writeBytes(Base64.getDecoder().decode(spec.getValue("base64").jsonPrimitive.content))
            spec["mtime"]?.let { Files.setLastModifiedTime(file.toPath(), FileTime.fromMillis((it.jsonPrimitive.double * 1000).toLong())) }
            return Ran(0, JsonObject(fields + ("filepath" to JsonPrimitive(file.path))).toString() + "\n", "")
        }

        private fun failed(spec: JsonObject): Ran? {
            val stderr = spec["stderr"]?.jsonPrimitive?.content ?: return null
            val exit = spec["exit"]?.jsonPrimitive?.int ?: 0
            return if (exit != 0) Ran(exit, "", stderr + "\n") else null
        }
    }
}
