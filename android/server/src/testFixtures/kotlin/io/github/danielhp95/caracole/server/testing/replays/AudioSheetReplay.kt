package io.github.danielhp95.caracole.server.testing.replays

import io.github.danielhp95.caracole.core.config.PhoneConfig
import io.github.danielhp95.caracole.core.db.Database
import io.github.danielhp95.caracole.core.db.Db
import io.github.danielhp95.caracole.core.health.Alerts
import io.github.danielhp95.caracole.core.http.HttpAnswer
import io.github.danielhp95.caracole.core.index.Reads
import io.github.danielhp95.caracole.core.json.PyJson
import io.github.danielhp95.caracole.core.library.AudioStore
import io.github.danielhp95.caracole.core.library.LibraryStore
import io.github.danielhp95.caracole.core.library.Overrides
import io.github.danielhp95.caracole.core.lookup.Clients
import io.github.danielhp95.caracole.core.lookup.Pacing
import io.github.danielhp95.caracole.core.lookup.SongPages
import io.github.danielhp95.caracole.core.lookup.SongbookPages
import io.github.danielhp95.caracole.core.testing.AreaReplay
import io.github.danielhp95.caracole.core.testing.Corpus
import io.github.danielhp95.caracole.core.testing.FakeTransport
import io.github.danielhp95.caracole.core.testing.Fixtures
import io.github.danielhp95.caracole.core.testing.Misses
import io.github.danielhp95.caracole.core.testing.Scenarios
import io.github.danielhp95.caracole.core.testing.TestDb
import io.github.danielhp95.caracole.server.PhoneParts
import io.github.danielhp95.caracole.server.jobs.CommandExit
import io.github.danielhp95.caracole.server.jobs.JobContext
import io.github.danielhp95.caracole.server.jobs.JobQueue
import io.github.danielhp95.caracole.server.lookups.AudioRunner
import io.github.danielhp95.caracole.server.page.MirrorPageData
import io.github.danielhp95.caracole.viewer.autochords.AudioUnreadable
import io.github.danielhp95.caracole.viewer.autochords.ChordModels
import io.github.danielhp95.caracole.viewer.autochords.ChordsUnavailable
import io.github.danielhp95.caracole.viewer.autochords.Heard
import io.github.danielhp95.caracole.viewer.autochords.Relay
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
import kotlinx.serialization.json.boolean
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
 * `caracole audio --upload` replayed from the computer's records (vectors/lookup/audio_sheet.jsonl, written by
 * tests/test_conformance_audio_sheet.py, whose docstring says what each record holds), area `audio-sheet`: each
 * record's fixture loaded into a database of its own (`{state}` its own state folder), its kv `sync:id` the record's
 * `own`, the store's files written with their times, its answers served by a [FakeTransport], every clock at its
 * `now`; then the phone's own [AudioRunner] given the command line caracole serve queues (`audio --progress
 * --upload=ID --song=…`), its pages [SongPages.NONE], its chord models a fake that answers the record's `heard` (or
 * fails as its `hearing` says), its examiner the record's `audio`.
 *
 * Compared with Python's: each stage's end, the song, the files readable, the stages as told in order, the command's
 * exit, the requests, the events (provider, address, status and decision), the rows of every table it changed (a
 * version's raw less the maker's side, `made_on`, `made_by`, `models`, `runtime`, which are checked to be the
 * phone's), the kv records and library files it changed, and the store's files after. What the record keeps `apart`
 * is compared apart: the lyrics stage's words (the lookup's, get.py's, where the computer's job says
 * youtube_sheet.py's: its state alone compared), a failing hearing's chords words (the phone's own; its state alone),
 * the events' runs and the pauses (the lookup's pace against the bulk's), and the kv the phone never writes.
 *
 * A record of `relay_onto_sheets` is a sheet the phone made re-laid on the computer: the phone's own re-lay
 * ([Relay.onto], its kv `sync:id` the sheet's maker) must write the same rows and the same sheet.
 */
object AudioSheetReplay : AreaReplay {
    override val area = "audio-sheet"
    const val VECTOR = "lookup/audio_sheet.jsonl"

    override fun replay(misses: Misses) {
        for (record in Corpus.lines(VECTOR).filter { it["header"] != JsonPrimitive(true) }) {
            for (f in one(record)) misses.check(false) { f }
            misses.check(true) { "" }
        }
    }

    /** The cases of the vector, in order. */
    fun cases(): List<String> = Corpus.lines(VECTOR).filter { it["header"] != JsonPrimitive(true) }
        .map { it.getValue("case").jsonPrimitive.content }

    /** The differences of [record] replayed, each "case: what differs". */
    fun one(record: JsonObject): List<String> {
        val case = record.getValue("case").jsonPrimitive.content
        val found = ArrayList<String>()
        fun check(ok: Boolean, what: () -> String) {
            if (!ok) found += "$case: ${what()}"
        }
        val dir = Files.createTempDirectory("caracole-audio-sheet").toFile()
        try {
            val state = File(dir, "state").apply { mkdirs() }
            val library = File(dir, "library").apply { mkdirs() }
            val path = state.absolutePath
            val placed = Json.parseToJsonElement(record.toString().replace("{state}", path)).jsonObject
            val kw = placed.getValue("kw").jsonObject
            val done = record.getValue("out").jsonObject  // as Python wrote it: `{state}`, which what the phone did is
                                                              // written in before it is compared
            val apart = placed["apart"]?.jsonObject ?: JsonObject(emptyMap())
            val leaves = placed.getValue("leaves_out").jsonObject
            val prefixes = leaves["kv"]?.jsonArray?.map { it.jsonPrimitive.content }.orEmpty() +
                apart["kv"]?.jsonArray?.map { it.jsonPrimitive.content }.orEmpty()
            val names = leaves["files"]?.jsonArray?.map { it.jsonPrimitive.content }.orEmpty().toSet()
            val now = Instant.parse(placed.getValue("now").jsonPrimitive.content)
            TestDb.fresh(File(dir, "db").apply { mkdirs() }).use { database ->
                database.writeBlocking { db ->
                    Fixtures.loadRecords(db, placed.getValue("fixture").jsonArray.map { it.jsonObject }, library, case)
                    db.kvSet("sync:id", kw.getValue("own").jsonPrimitive.content)
                }
                writeStore(File(state, AudioStore.FOLDER), kw["store"]?.jsonObject ?: JsonObject(emptyMap()))
                val before = database.read { Tables.of(it) }
                val kvBefore = database.read { kv(it, prefixes) }
                val filesBefore = files(library, names)
                val eventsBefore = database.read { db -> db.one("SELECT COALESCE(MAX(id), 0) FROM events") { it.long(0)!! }!! }
                val transport = FakeTransport(answers(placed["answers"]?.jsonObject ?: JsonObject(emptyMap())))
                val pacing = Pacing(sleep = {}, draws = { low, high -> low + (high - low) * 0.5 },
                                    wallSeconds = { now.epochSecond.toDouble() }, monotonic = { 0.0 }, clock = { now })
                val lib = LibraryStore(library, File(state, AudioStore.FOLDER))
                if (placed.getValue("fn").jsonPrimitive.content == RELAY) {
                    val relaid = database.writeBlocking { db ->
                        val stamps = db.query("SELECT id, created_at FROM files") { it.long(0)!! to it.text(1) }.toMap()
                        Relay.onto(db, library, Overrides.read(db)).also {
                            // Kept at the clock's time, as Python's keep_file at SQLite's: both settled at `now`.
                            for ((id, at) in db.query("SELECT id, created_at FROM files") { it.long(0)!! to it.text(1) }) {
                                if (stamps[id] != at) {
                                    db.execute("UPDATE files SET created_at = ? WHERE id = ?",
                                               placed.getValue("now").jsonPrimitive.content, id)
                                }
                            }
                        }
                    }
                    check(JsonArray(relaid.songs.map { JsonPrimitive(it.id) }) == done["result"]) {
                        "re-laid ${relaid.songs.map { it.id }} (failed ${relaid.failed}), Python's ${done["result"]}"
                    }
                } else {
                    job(placed, kw, done, apart, database, lib, state, transport, pacing, ::check)
                }
                check(JsonArray(transport.said.map(::JsonPrimitive)) == done["requests"]) {
                    "requests ${transport.said}, Python's ${done["requests"]}"
                }
                database.read { db ->
                    val events = JsonArray(db.query("SELECT provider, url, status, decision FROM events WHERE id > ? " +
                                                        "ORDER BY id", eventsBefore) { r ->
                        JsonArray(listOf(JsonPrimitive(r.text(0)), JsonPrimitive(r.text(1)),
                                         r.long(2)?.let(::JsonPrimitive) ?: JsonNull, JsonPrimitive(r.text(3))))
                    })
                    val want = JsonArray(done.getValue("events").jsonArray.map { JsonArray(it.jsonArray.drop(1)) })
                    check(events == want) { "events $events, Python's $want" }
                    val strip = placed.getValue("fn").jsonPrimitive.content != RELAY
                    val after = Tables.of(db).mapValues { (_, rows) -> rows.map { unmade(it, path, strip) } }
                    val changed = (before.keys + after.keys).filter { it != "events" && before[it] != Tables.of(db)[it] }.toSet()
                    val wantRows = done.getValue("rows").jsonObject
                    check(changed == wantRows.keys) { "changed ${changed.sorted()}, Python ${wantRows.keys.sorted()}" }
                    for ((table, rows) in wantRows) {
                        check(JsonArray(after[table].orEmpty()) == rows) { "$table holds ${after[table]},\n  Python's $rows" }
                    }
                    val kvAfter = kv(db, prefixes)
                    val kvChanged = (kvBefore.keys + kvAfter.keys).filter { kvBefore[it] != kvAfter[it] }.sorted()
                        .associateWith { k -> kvAfter[k]?.let(::JsonPrimitive) ?: JsonNull }
                    check(JsonObject(kvChanged) == done["kv"]) { "kv $kvChanged, Python's ${done["kv"]}" }
                }
                val filesAfter = files(library, names)
                val filesChanged = JsonObject((filesBefore.keys + filesAfter.keys)
                    .filter { filesBefore[it] != filesAfter[it] }.sorted()
                    .associateWith { p -> filesAfter[p]?.let(::JsonPrimitive) ?: JsonNull })
                check(filesChanged == done["library"]) { "files $filesChanged, Python's ${done["library"]}" }
                done["store"]?.let { want ->
                    val got = storeAfter(File(state, AudioStore.FOLDER))
                    check(got == want) { "the store holds $got, Python's $want" }
                }
            }
        } finally {
            dir.deleteRecursively()
        }
        return found
    }

    private const val RELAY = "caracole.autochords.sheet_lyrics.relay_onto_sheets"
    internal val MAKER = listOf("made_on", "made_by", "models", "runtime")

    /** The fake models' names and runtime, the phone's side of a sheet's maker. */
    val NAMES = linkedMapOf("chords" to "btc_large_voca@1673d23f8f9a55ae",
                            "beats" to "beat_this final0@8c328b45f59d8dd3 fp16")
    const val RUNTIME = "onnxruntime 1.32.0"

    /** One `make_audio_sheet` record through the phone's runner. */
    private fun job(record: JsonObject, kw: JsonObject, done: JsonObject, apart: JsonObject, database: Database,
                    lib: LibraryStore, state: File, transport: FakeTransport, pacing: Pacing,
                    check: (Boolean, () -> String) -> Unit) {
        val audio = kw.getValue("audio").jsonObject
        val examined = AudioStore.Audio(audio.getValue("format").jsonPrimitive.content,
                                        audio.getValue("duration").jsonPrimitive.double,
                                        audio["tags"]?.jsonObject.orEmpty().mapValues { (_, v) ->
                                            listOfNotNull((v as? JsonPrimitive)?.takeIf { it.isString }?.content)
                                        })
        val store = AudioStore(state, { _, _ -> examined }, freeSpace = { Long.MAX_VALUE })
        val heard = Heard.of(kw.getValue("heard"))
        val hearing = kw.getValue("hearing").jsonPrimitive.content
        val chords = object : ChordModels {
            override fun ready(): String? = null
            override val runtime: String = RUNTIME
            override fun hear(audio: File, onStep: (String) -> Unit, waiting: () -> Unit): Heard {
                onStep("setting up the models")
                if (hearing == "setup") throw ChordsUnavailable("the chord models stopped (the phone may have run out of memory); try again")
                onStep("hearing the chords")
                waiting()
                if (hearing == "audio") throw AudioUnreadable("MediaExtractor can't read the file")
                onStep("finding the beats")
                return heard
            }
        }
        val scope = CoroutineScope(SupervisorJob())
        try {
            val parts = PhoneParts(database, lib, state, { PhoneConfig.DEFAULTS }, JobQueue(scope), MirrorPageData(null),
                                   { Clients(PhoneConfig.DEFAULTS, File(state, "cache"), { transport }, pacing) },
                                   SongPages.NONE, SongbookPages.NONE, Alerts.NONE, pacing, searchesLacuerda = false)
            val told = Told()
            val request = kw.getValue("request").jsonObject
            val args = listOf("audio", "--progress", "--upload=${request.getValue("upload").jsonPrimitive.content}",
                              "--song=${request.getValue("artist").jsonPrimitive.content} - " +
                                  request.getValue("title").jsonPrimitive.content)
            val exit = try {
                runBlocking { AudioRunner(parts, chords, store, problem = { null }, names = { NAMES }).run(args, told) }
                0
            } catch (e: CommandExit) {
                e.code
            }
            val said = done.getValue("result").jsonObject
            val want = said.getValue("result").jsonObject
            check(exit == want.getValue("exit").jsonPrimitive.int) { "exited $exit, Python's ${want["exit"]}: ${told.said}" }
            val wantStates = want.getValue("states").jsonObject
            val wantDetails = want.getValue("details").jsonObject
            val apartStages = setOfNotNull("lyrics".takeIf { apart["lyrics"]?.jsonPrimitive?.boolean == true },
                                           "chords".takeIf { apart["chords"]?.jsonPrimitive?.boolean == true })
            check(told.states.keys == wantStates.keys) { "stages ${told.states.keys}, Python's ${wantStates.keys}" }
            for ((name, state) in wantStates) {
                check(told.states[name] == state.jsonPrimitive.content) { "$name ${told.states[name]}, Python's $state" }
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
            // The maker: the phone's side, the version's raw the record's but for it.
            val raw = database.read { db ->
                db.one("SELECT raw FROM versions WHERE provider = 'auto' ORDER BY id LIMIT 1") { it.text(0) }
            }?.let { PyJson.loads(it).jsonObject }
            val maker = done["maker"]
            if (maker != null && maker != JsonNull) {
                check(raw != null) { "no auto version, Python's maker $maker" }
                if (raw != null) {
                    val phone = JsonObject(linkedMapOf("made_on" to JsonPrimitive(AudioRunner.MADE_ON),
                                                       "made_by" to kw.getValue("own"),
                                                       "models" to JsonObject(NAMES.mapValues { JsonPrimitive(it.value) }),
                                                       "runtime" to JsonPrimitive(RUNTIME)))
                    val got = JsonObject(MAKER.filter { it in raw }.associateWith { raw.getValue(it) })
                    check(got == phone) { "the maker $got, the phone's $phone" }
                }
            }
        } finally {
            scope.cancel()
        }
    }

    /** A job's context that keeps what it is told. */
    internal class Told : JobContext {
        val said = ArrayList<String>()
        val events = ArrayList<JsonElement>()
        val states = LinkedHashMap<String, String>()
        val details = LinkedHashMap<String, String>()
        var song: Pair<Long, String>? = null
        var files: Map<String, String> = emptyMap()

        override fun stage(name: String, state: String, detail: String) {
            events.add(JsonArray(listOf("stage", name, state, detail).map(::JsonPrimitive)))
            running = if (state == "running") name else null
            if (state == "running") return
            states[name] = state
            details[name] = detail
        }

        override fun say(line: String) {
            said += line
        }

        override fun song(id: Long, display: String) {
            events.add(JsonArray(listOf(JsonPrimitive("song"), JsonPrimitive(id), JsonPrimitive(display))))
            song = id to display
        }

        override fun readable(files: Map<String, String>, seconds: Double) {
            events.add(JsonArray(listOf(JsonPrimitive("readable"), JsonObject(files.mapValues { JsonPrimitive(it.value) }))))
            this.files = files
        }

        override fun outcome(value: JsonObject) {}
        override val isCancelled: Boolean = false

        /** The stage running now, and what a yield to the queued lookups does (nothing, unless a replay says). */
        var running: String? = null
        var onYield: (Told) -> Unit = {}

        override fun yieldToQueued() = onYield(this)
    }

    /** A row as the record carries it: the state folder written `{state}`; a job's auto version's raw less the maker's
     * side ([strip]: a job's records carry it apart, a re-lay's raw keeps its maker as it was). */
    internal fun unmade(row: JsonObject, state: String, strip: Boolean): JsonObject = JsonObject(row.mapValues { (column, value) ->
        if (value !is JsonPrimitive || !value.isString) return@mapValues value
        var text = value.content.replace(state, "{state}")
        if (strip && column == "raw" && row["provider"] == JsonPrimitive("auto")) {
            val raw = PyJson.loads(text).jsonObject
            if ("made_on" in raw) text = PyJson.dumps(JsonObject(raw.filterKeys { it !in MAKER }))
        }
        JsonPrimitive(text)
    })

    internal fun writeStore(root: File, files: JsonObject) {
        if (files.isEmpty()) return
        root.mkdirs()
        for ((name, spec) in files) {
            val o = spec.jsonObject
            val file = File(root, name)
            if ("text" in o) file.writeText(o.getValue("text").jsonPrimitive.content)
            else file.writeBytes(Base64.getDecoder().decode(o.getValue("base64").jsonPrimitive.content))
            o["mtime"]?.let { Files.setLastModifiedTime(file.toPath(), FileTime.fromMillis((it.jsonPrimitive.double * 1000).toLong())) }
        }
    }

    internal fun storeAfter(root: File): JsonObject = JsonObject(
        (root.listFiles()?.sortedBy { it.name } ?: emptyList()).associate { f ->
            f.name to JsonPrimitive(when {
                f.name.endsWith(".json") -> "record"
                f.name.endsWith(".kept") -> "marker"
                else -> sha256(f.readBytes())
            })
        })

    internal fun answers(record: JsonObject): Map<String, HttpAnswer> = record.mapValues { (_, a) ->
        val o = a.jsonObject
        HttpAnswer(o.getValue("status").jsonPrimitive.int,
                   (o["headers"] as? JsonArray ?: JsonArray(emptyList())).map { h ->
                       h.jsonArray[0].jsonPrimitive.content to h.jsonArray[1].jsonPrimitive.content
                   }, Scenarios.body(o["body"] ?: JsonObject(mapOf("text" to JsonPrimitive("")))))
    }

    internal fun sha256(data: ByteArray): String = java.security.MessageDigest.getInstance("SHA-256").digest(data)
        .joinToString("") { b -> "0123456789abcdef"[(b.toInt() shr 4) and 15].toString() + "0123456789abcdef"[b.toInt() and 15] }

    internal fun kv(db: Db, leftOut: List<String>): Map<String, String> =
        db.query("SELECT key, value FROM kv ORDER BY key") { it.text(0)!! to it.text(1)!! }
            .filter { (k, _) -> k != "sync:id" && !k.startsWith(Reads.READ) && leftOut.none { k.startsWith(it) } }.toMap()

    internal fun files(library: File, leftOut: Set<String>): Map<String, String> = library.walkTopDown()
        .filter { it.isFile && it.name !in leftOut }
        .associate { it.relativeTo(library).invariantSeparatorsPath to sha256(it.readBytes()) }

    /** The tables a job may change, as dump_fixture reads them. */
    internal object Tables {
        val NAMES = listOf("songs", "versions", "files", "removed", "events", "phone_overrides")

        private fun quoted(name: String) = "\"" + name.replace("\"", "\"\"") + "\""

        fun of(db: Db): Map<String, List<JsonObject>> = NAMES.associateWith { table ->
            val columns = db.query("PRAGMA main.table_info(${quoted(table)})") { it.text(1)!! }
            val select = columns.joinToString(", ") { "typeof(${quoted(it)}), ${quoted(it)}" }
            db.query("SELECT $select FROM ${quoted(table)} ORDER BY rowid") { row ->
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
            }
        }
    }
}
