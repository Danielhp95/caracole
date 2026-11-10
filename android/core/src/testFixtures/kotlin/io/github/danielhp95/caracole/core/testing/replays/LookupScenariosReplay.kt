package io.github.danielhp95.caracole.core.testing.replays

import io.github.danielhp95.caracole.core.config.PhoneConfig
import io.github.danielhp95.caracole.core.db.Database
import io.github.danielhp95.caracole.core.db.Db
import io.github.danielhp95.caracole.core.health.Alerts
import io.github.danielhp95.caracole.core.http.HttpAnswer
import io.github.danielhp95.caracole.core.index.Reads
import io.github.danielhp95.caracole.core.json.PyJson
import io.github.danielhp95.caracole.core.library.LibraryStore
import io.github.danielhp95.caracole.core.lookup.Clients
import io.github.danielhp95.caracole.core.lookup.Lookup
import io.github.danielhp95.caracole.core.lookup.LookupRequest
import io.github.danielhp95.caracole.core.lookup.LookupResult
import io.github.danielhp95.caracole.core.lookup.Pacing
import io.github.danielhp95.caracole.core.lookup.Progress
import io.github.danielhp95.caracole.core.lookup.SongPages
import io.github.danielhp95.caracole.core.lookup.SongbookPages
import io.github.danielhp95.caracole.core.testing.AreaReplay
import io.github.danielhp95.caracole.core.testing.Corpus
import io.github.danielhp95.caracole.core.testing.FakeTransport
import io.github.danielhp95.caracole.core.testing.Fixtures
import io.github.danielhp95.caracole.core.testing.Misses
import io.github.danielhp95.caracole.core.testing.Scenarios
import io.github.danielhp95.caracole.core.testing.TestDb
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.boolean
import kotlinx.serialization.json.booleanOrNull
import kotlinx.serialization.json.int
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import kotlinx.serialization.json.longOrNull
import java.io.File
import java.nio.file.Files
import java.time.Instant
import java.util.zip.GZIPOutputStream

/**
 * Whole lookups replayed from the computer's records (vectors/lookup/get.jsonl and commands_get.jsonl, written by
 * tests/test_conformance_lookup_scenarios.py, whose docstring says what each record holds): each record's fixture
 * loaded into a database of its own, its cache written as http.py writes one, its answers served by a [FakeTransport],
 * its providers' settings over config.json's, every clock at the record's `now` (no pause slept, each one counted),
 * then the record's [Run] in that [World]: [LOOK_UP], [Lookup.run] over every site stage ([SiteStages.ALL], as
 * GetRunner runs it) with [SongPages.NONE] and [SongbookPages.NONE] as the phone of milestone 4 has them, for get.jsonl
 * (this area's); the phone's VersionsRunner for commands_get.jsonl's `caracole versions --choose` and `--clear`, which
 * :core can't reach (server.lookups.LookupScenariosCommandsTest gives it).
 *
 * Compared with Python's: what the lookup came to (the fields of LookupResult the run can tell: every one for
 * [LOOK_UP]) and told as it went (in the phone's words, the record's), a command's lines and the address it looked the
 * song up at, the requests in order, the events the lookup logged (`[run, provider, url, status, decision]`), the rows
 * of every table it changed (`phone_overrides` by table and key, the rest in rowid order), the kv records it changed
 * and the library's files it wrote or deleted (each by its SHA-256), less what the record `leaves_out` (the kv
 * prefixes and file names the phone never writes), and the number of pauses; and what the phone writes and Python
 * doesn't, the index pages its stores noted for the next push to the computer ([Reads], kv `phone:read:<site>:<page>`),
 * against the record's `noted`, left out of the kv compared.
 */
object LookupScenariosReplay : AreaReplay {
    override val area = "lookup-scenarios"

    const val GET = "lookup/get.jsonl"
    const val COMMANDS = "lookup/commands_get.jsonl"

    /** get.jsonl's records, each through [LOOK_UP]. */
    override fun replay(misses: Misses) {
        replay(GET, misses, LOOK_UP)
    }

    /** One record's world: its database, library, settings, cache and fake sites, the pace at its `now`, and the
     * progress that keeps what the run tells. */
    class World(val record: JsonObject, val database: Database, val store: LibraryStore, val config: PhoneConfig,
                val cacheDir: File, val transport: FakeTransport, val progress: Progress, val now: Instant) {
        var pauses = 0
            private set

        /** The pace: no pause slept (each counted), every draw its range's middle, every clock at `now`. */
        val pacing = Pacing(sleep = { pauses++ }, draws = { low, high -> low + (high - low) * 0.5 },
                            wallSeconds = { now.epochSecond.toDouble() }, monotonic = { 0.0 }, clock = { now })

        /** The record's `kw`. */
        val kw: JsonObject get() = record.getValue("kw").jsonObject

        val fn: String get() = text(record.getValue("fn"))

        /** A lookup's clients, as Assembly's PhoneParts makes them for each lookup. */
        fun clients(): Clients = Clients(config, cacheDir, { transport }, pacing)
    }

    /**
     * What a record's run came to: [result], the fields of LookupResult it can tell by Python's names (song_id,
     * display, states, details, files, seconds_to_sheet, seconds, requests, bug, refused), each compared with the
     * record's, and with no `states` and `details` the run fails; a command's lines ([said], compared with the
     * record's `said`: its own lines and get's totals) and the tab address it looked the song up at ([address]).
     */
    class Ran(val result: JsonObject, val said: List<String>? = null, val address: String? = null)

    /** How a record is run in its [World]; one that can't run a record's `fn` throws. */
    fun interface Run {
        fun run(world: World): Ran
    }

    /** get.py's look_up, as GetRunner runs it (LookupJobs.lookUp): [Lookup.run] in one write, over every site stage. */
    val LOOK_UP = Run { w ->
        if (w.fn != "caracole.get.look_up") throw AssertionError("LOOK_UP runs no ${w.fn}")
        val lookup = Lookup(w.config, w.database, w.store, w.clients(), SongPages.NONE, SongbookPages.NONE, Alerts.NONE,
                            request(w.kw.getValue("request").jsonObject), w.progress, w.pacing)
        Ran(resultOf(w.database.writeBlocking { lookup.run(it) }))
    }

    /**
     * Every record of [name] ([only] those of these cases, when given), each [edit]ed first (a test's, to see a
     * difference found), run by [run]; the cases replayed, in order.
     */
    fun replay(name: String, misses: Misses, run: Run, only: Set<String>? = null,
               edit: (JsonObject) -> JsonObject = { it }): List<String> {
        val replayed = ArrayList<String>()
        for (line in Corpus.lines(name).filter { it["header"] != JsonPrimitive(true) }) {
            val case = text(line.getValue("case"))
            if (only != null && case !in only) continue
            for (f in one(edit(line), run)) misses.check(false) { f }
            misses.check(true) { "" }  // the record, compared
            replayed += case
        }
        return replayed
    }

    // --- one record ---------------------------------------------------------------------------------------------

    /** The differences of [record] run by [run], each "case: what differs". */
    private fun one(record: JsonObject, run: Run): List<String> {
        val case = text(record.getValue("case"))
        val done = (record["out"] ?: record.getValue("after")).jsonObject
        val said = done.getValue("result").jsonObject
        val events = done.getValue("events").jsonArray
        val found = ArrayList<String>()
        fun check(ok: Boolean, what: () -> String) {
            if (!ok) found += "$case: ${what()}"
        }

        val now = Instant.parse(text(record.getValue("now")))
        val leaves = record["leaves_out"]?.jsonObject ?: JsonObject(emptyMap())
        val prefixes = leaves["kv"]?.jsonArray?.map(::text).orEmpty()
        val names = leaves["files"]?.jsonArray?.map(::text).orEmpty().toSet()
        val dir = Files.createTempDirectory("caracole-lookup-scenario").toFile()
        try {
            val library = File(dir, "library").apply { mkdirs() }
            val cache = File(dir, "cache")
            TestDb.fresh(File(dir, "db").apply { mkdirs() }).use { database ->
                database.writeBlocking { db ->
                    Fixtures.loadRecords(db, record.getValue("fixture").jsonArray.map { it.jsonObject }, library, case)
                }
                seedCache(cache, record["cache"]?.jsonObject ?: JsonObject(emptyMap()))
                val heard = ArrayList<JsonElement>()
                val progress = object : Progress {
                    override fun stage(name: String, state: String, detail: String) {
                        heard.add(JsonArray(listOf("stage", name, state, detail).map(::JsonPrimitive)))
                    }

                    override fun song(id: Long, display: String) {
                        heard.add(JsonArray(listOf(JsonPrimitive("song"), JsonPrimitive(id), JsonPrimitive(display))))
                    }

                    override fun readable(files: Map<String, String>, seconds: Double) {
                        heard.add(JsonArray(listOf(JsonPrimitive("readable"),
                                                  JsonObject(files.mapValues { JsonPrimitive(it.value) }))))
                    }
                }
                val kw = record.getValue("kw").jsonObject
                val world = World(record, database, LibraryStore(library),
                                  configured(kw["providers"]?.jsonObject ?: JsonObject(emptyMap())), cache,
                                  FakeTransport(answers(record["answers"]?.jsonObject ?: JsonObject(emptyMap()))),
                                  progress, now)
                val before = database.read { Tables.of(it) }
                val kvBefore = database.read { kv(it, prefixes) }
                val filesBefore = files(library, names)
                val eventsBefore = database.read { db -> db.one("SELECT COALESCE(MAX(id), 0) FROM events") { it.long(0)!! }!! }

                val ran = try {
                    run.run(world)
                } catch (e: Throwable) {
                    check(false) { "the run threw $e" }
                    return found
                }

                val want = said.getValue("result").jsonObject
                check("states" in ran.result && "details" in ran.result) { "the run told no stage's end" }
                for (k in ran.result.keys) {
                    check(k in want) { "the run tells $k, which Python's result hasn't" }
                }
                for ((k, v) in want) {
                    if (k in ran.result) check(ran.result[k] == v) { "$k ${ran.result[k]}, Python's $v" }
                }
                check(JsonArray(heard) == said.getValue("progress")) {
                    "told ${JsonArray(heard)},\n  Python's ${said["progress"]}"
                }
                check((ran.said == null) == (said["said"] == null)) {
                    "said ${ran.said}, Python's ${said["said"]}"
                }
                said["said"]?.let { s ->
                    check(JsonArray(ran.said.orEmpty().map(::JsonPrimitive)) == s) { "said ${ran.said}, Python's $s" }
                }
                said["address"]?.let { a ->
                    check((ran.address?.let(::JsonPrimitive) ?: JsonNull) == a) { "asked ${ran.address}, Python's $a" }
                }
                val requests = JsonArray(world.transport.said.map(::JsonPrimitive))
                check(requests == done["requests"]) { "requests $requests, Python's ${done["requests"]}" }
                database.read { db ->
                    val gotEvents = JsonArray(db.query("SELECT run, provider, url, status, decision FROM events " +
                                                           "WHERE id > ? ORDER BY id", eventsBefore) { r ->
                        JsonArray(listOf(JsonPrimitive(r.text(0)), JsonPrimitive(r.text(1)), JsonPrimitive(r.text(2)),
                                         r.long(3)?.let(::JsonPrimitive) ?: JsonNull, JsonPrimitive(r.text(4))))
                    })
                    check(gotEvents == events) { "events $gotEvents, Python's $events" }
                    check(world.pauses == done.getValue("pauses").jsonPrimitive.int) {
                        "${world.pauses} pauses, Python's ${done["pauses"]}"
                    }
                    val after = Tables.of(db)
                    val changed = (before.keys + after.keys).filter { it != "events" && before[it] != after[it] }.toSet()
                    val wantRows = done.getValue("rows").jsonObject
                    check(changed == wantRows.keys) { "changed ${changed.sorted()}, Python ${wantRows.keys.sorted()}" }
                    for ((table, rows) in wantRows) {
                        val gotRows = JsonArray(after[table].orEmpty())
                        check(Tables.ordered(table, gotRows) == Tables.ordered(table, rows.jsonArray)) {
                            "$table holds $gotRows,\n  Python's $rows"
                        }
                    }
                    val kvAfter = kv(db, prefixes)
                    val kvChanged = (kvBefore.keys + kvAfter.keys).filter { kvBefore[it] != kvAfter[it] }.sorted()
                        .associateWith { k -> kvAfter[k]?.let(::JsonPrimitive) ?: JsonNull }
                    val (notes, rest) = kvChanged.entries.partition { it.key.startsWith(Reads.READ) }
                    check(JsonObject(rest.associate { it.toPair() }) == done["kv"]) { "kv $rest, Python's ${done["kv"]}" }
                    val noted = JsonObject(notes.associate { it.toPair() })
                    check(noted == done.getValue("noted")) { "noted $noted for the push, Python's ${done["noted"]}" }
                }
                val filesAfter = files(library, names)
                val filesChanged = JsonObject((filesBefore.keys + filesAfter.keys)
                    .filter { filesBefore[it] != filesAfter[it] }.sorted()
                    .associateWith { p -> filesAfter[p]?.let(::JsonPrimitive) ?: JsonNull })
                check(filesChanged == done["library"]) { "files $filesChanged, Python's ${done["library"]}" }
            }
        } finally {
            dir.deleteRecursively()
        }
        return found
    }

    // --- the record's world -------------------------------------------------------------------------------------

    /** get.LookupRequest from its fields by Python's names. */
    fun request(r: JsonObject): LookupRequest {
        fun opt(name: String) = r[name]?.takeIf { it != JsonNull }?.let(::text)
        return LookupRequest(text(r.getValue("artist")), text(r.getValue("title")), opt("album"),
                             r["duration_ms"]?.jsonPrimitive?.longOrNull, opt("ug"), opt("tab"), opt("lacuerda"),
                             opt("harptabs"), opt("gametabs"), r["songbooks"]?.jsonPrimitive?.booleanOrNull ?: true)
    }

    /** What the lookup came to, as the record writes Python's LookupResult. */
    fun resultOf(r: LookupResult): JsonObject = JsonObject(mapOf(
        "song_id" to (r.songId?.let(::JsonPrimitive) ?: JsonNull),
        "display" to JsonPrimitive(r.display),
        "states" to JsonObject(r.states.mapValues { JsonPrimitive(it.value) }),
        "details" to JsonObject(r.details.mapValues { JsonPrimitive(it.value) }),
        "files" to JsonObject(r.files.mapValues { JsonPrimitive(it.value) }),
        "seconds_to_sheet" to (r.secondsToSheet?.let { PyJson.float(it) } ?: JsonNull),
        "seconds" to PyJson.float(r.seconds),
        "requests" to JsonObject(r.requests.mapValues { JsonPrimitive(it.value) }),
        "bug" to (r.bug?.let(::JsonPrimitive) ?: JsonNull),
        "refused" to (r.refused?.let(::JsonPrimitive) ?: JsonNull),
    ))

    /** The provider fields a record may set, config.py's names. */
    private val CONFIGURED = setOf("enabled", "lookup_requests", "lookup_per_hour")

    /** config.DEFAULT_PROVIDERS with a record's fields over theirs; a field the replay doesn't apply fails it. */
    private fun configured(overrides: JsonObject): PhoneConfig {
        for ((name, f) in overrides) {
            if (name !in PhoneConfig.DEFAULTS.providers) throw AssertionError("a record configures no provider of the phone's: $name")
            val fields = f.jsonObject.keys - CONFIGURED
            if (fields.isNotEmpty()) throw AssertionError("a record sets $name's $fields, which the replay doesn't apply")
        }
        return PhoneConfig.DEFAULTS.copy(providers = PhoneConfig.DEFAULTS.providers.mapValues { (name, p) ->
            overrides[name]?.jsonObject?.let { f ->
                p.copy(enabled = f["enabled"]?.jsonPrimitive?.boolean ?: p.enabled,
                       lookupRequests = f["lookup_requests"]?.jsonPrimitive?.int ?: p.lookupRequests,
                       lookupPerHour = f["lookup_per_hour"]?.jsonPrimitive?.int ?: p.lookupPerHour)
            } ?: p
        })
    }

    private fun answers(record: JsonObject): Map<String, HttpAnswer> = record.mapValues { (_, a) ->
        val o = a.jsonObject
        HttpAnswer(o.getValue("status").jsonPrimitive.int,
                   (o["headers"] as? JsonArray ?: JsonArray(emptyList())).map { h -> text(h.jsonArray[0]) to text(h.jsonArray[1]) },
                   Scenarios.body(o["body"] ?: JsonObject(mapOf("text" to JsonPrimitive("")))))
    }

    /** The record's cache, written as http.py writes one (scenario.py's `_seed_cache`). */
    private fun seedCache(cacheDir: File, cache: JsonObject) {
        for ((provider, entries) in cache) {
            for ((request, e) in entries.jsonObject) {
                val url = request.substringAfter(' ')
                val entry = e.jsonObject
                val key = Scenarios.sha256(url.toByteArray(Charsets.UTF_8))
                val folder = File(File(File(cacheDir, "http"), provider), key.substring(0, 2)).apply { mkdirs() }
                val out = java.io.ByteArrayOutputStream()
                GZIPOutputStream(out).use { it.write(Scenarios.body(entry.getValue("body"))) }
                File(folder, "$key.body").writeBytes(out.toByteArray())
                val meta = JsonObject(linkedMapOf("url" to JsonPrimitive(url), "status" to entry.getValue("status"),
                                                  "headers" to (entry["headers"] ?: JsonObject(emptyMap())),
                                                  "fetched_at" to entry.getValue("fetched_at")))
                File(folder, "$key.json").writeBytes(PyJson.dumps(meta).toByteArray(Charsets.UTF_8))
            }
        }
    }

    private fun kv(db: Db, leftOut: List<String>): Map<String, String> =
        db.query("SELECT key, value FROM kv ORDER BY key") { it.text(0)!! to it.text(1)!! }
            .filter { (k, _) -> k != "sync:id" && leftOut.none { k.startsWith(it) } }.toMap()

    private fun files(library: File, leftOut: Set<String>): Map<String, String> = library.walkTopDown()
        .filter { it.isFile && it.name !in leftOut }
        .associate { it.relativeTo(library).invariantSeparatorsPath to Scenarios.sha256(it.readBytes()) }

    private fun text(e: JsonElement): String = e.jsonPrimitive.content

    /** The tables a lookup may change, as dump_fixture reads them (helpers.corpus.FIXTURE_TABLES, then the phone's). */
    private object Tables {
        val NAMES = listOf(
            "songs", "versions", "files", "removed", "events", "ug_index", "ug_artist_tabs", "lacuerda_index",
            "gtptabs_index", "musescore_index", "harptabs_index", "harptabs_artists", "harptabs_artist_tabs",
            "gametabs_index", "gametabs_games", "gametabs_game_tabs", "phone_overrides", "phone_songbooks",
        )

        private fun quoted(name: String) = "\"" + name.replace("\"", "\"\"") + "\""

        fun of(db: Db): Map<String, List<JsonObject>> = NAMES.associateWith { table ->
            val columns = db.query("PRAGMA main.table_info(${quoted(table)})") { it.text(1)!! }
            if (columns.isEmpty()) return@associateWith emptyList()
            val select = columns.joinToString(", ") { "typeof(${quoted(it)}), ${quoted(it)}" }
            db.query("SELECT $select FROM ${quoted(table)} ORDER BY rowid") { row ->
                val values = LinkedHashMap<String, JsonElement>()
                columns.forEachIndexed { i, column ->
                    values[column] = when (val type = row.text(2 * i)) {
                        "null" -> JsonNull
                        "integer" -> JsonPrimitive(row.long(2 * i + 1)!!)
                        "real" -> PyJson.float(row.double(2 * i + 1)!!)
                        "text" -> JsonPrimitive(row.text(2 * i + 1)!!)
                        else -> error("$table holds a $type, which a fixture can't carry")
                    }
                }
                JsonObject(values)
            }
        }

        /** A table's rows as compared: `phone_overrides` by its table and key (an entry written again may take a new
         * rowid on either side), the rest as they are, in rowid order. */
        fun ordered(table: String, rows: JsonArray): List<JsonElement> =
            if (table == "phone_overrides") rows.sortedWith(compareBy({ text(it.jsonObject.getValue("tbl")) },
                                                                      { text(it.jsonObject.getValue("key")) }))
            else rows
    }
}
