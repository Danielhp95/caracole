package io.github.danielhp95.caracole.core.testing.replays

import io.github.danielhp95.caracole.core.config.PhoneConfig
import io.github.danielhp95.caracole.core.db.Db
import io.github.danielhp95.caracole.core.health.Alerts
import io.github.danielhp95.caracole.core.http.HttpAnswer
import io.github.danielhp95.caracole.core.json.PyJson
import io.github.danielhp95.caracole.core.keys.Normalize
import io.github.danielhp95.caracole.core.library.LibraryStore
import io.github.danielhp95.caracole.core.library.OverrideWriters
import io.github.danielhp95.caracole.core.library.Overrides
import io.github.danielhp95.caracole.core.library.SongRow
import io.github.danielhp95.caracole.core.library.Songs
import io.github.danielhp95.caracole.core.lookup.Clients
import io.github.danielhp95.caracole.core.lookup.Lookup
import io.github.danielhp95.caracole.core.lookup.LookupRequest
import io.github.danielhp95.caracole.core.lookup.LookupResult
import io.github.danielhp95.caracole.core.lookup.LookupWords
import io.github.danielhp95.caracole.core.lookup.Pacing
import io.github.danielhp95.caracole.core.lookup.Progress
import io.github.danielhp95.caracole.core.lookup.SiteStage
import io.github.danielhp95.caracole.core.lookup.SiteStages
import io.github.danielhp95.caracole.core.lookup.SongPages
import io.github.danielhp95.caracole.core.lookup.SongbookPages
import io.github.danielhp95.caracole.core.lookup.StageEnd
import io.github.danielhp95.caracole.core.lookup.sites.NotYet
import io.github.danielhp95.caracole.core.testing.AreaReplay
import io.github.danielhp95.caracole.core.testing.Corpus
import io.github.danielhp95.caracole.core.testing.FakeTransport
import io.github.danielhp95.caracole.core.testing.Fixtures
import io.github.danielhp95.caracole.core.testing.Misses
import io.github.danielhp95.caracole.core.testing.Scenarios
import io.github.danielhp95.caracole.core.testing.TestDb
import io.github.danielhp95.caracole.core.ug.SheetVersions
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
 * then [Lookup.run] over every site stage, with [SongPages.NONE] and [SongbookPages.NONE] as the phone of milestone 4
 * has them; `caracole versions --choose` and `--clear` as versions_cmd.py runs them: get `--tab` at the version's own
 * address ([SheetVersions.inLibrary]), or the song's chords pins out of `[pin]` ([OverrideWriters.removePin]) then get.
 *
 * Compared with Python's: what the lookup came to and told as it went (in the phone's words, the record's), the
 * requests in order, the events the lookup logged (`[run, provider, url, status, decision]`), the rows of every table
 * it changed (`phone_overrides` by table and key, the rest in rowid order), the kv records it changed and the
 * library's files it wrote or deleted (each by its SHA-256), less what the record `leaves_out` (the kv prefixes and file
 * names the phone never writes), and the number of pauses.
 */
object LookupScenariosReplay : AreaReplay {
    override val area = "lookup-scenarios"

    const val GET = "lookup/get.jsonl"
    const val COMMANDS = "lookup/commands_get.jsonl"

    /** Phase A: the site lanes a stage stands in for while each hasn't landed, by the provider its stage asks
     * (waiting on lacuerda-sheets, tab-files, harptabs, gametabs); and ug-fetch-artist for a song through its
     * artist's page. Lane lookup-scenarios' Phase B takes these out. */
    private val WAITING_ON = mapOf("lacuerda" to "lacuerda-sheets", "gtptabs" to "tab-files", "harptabs" to "harptabs",
                                   "gametabs" to "gametabs")
    private const val ARTIST_PAGES = "ug-fetch-artist"

    /** Phase A: each record that waits on a site lane not landed yet (waiting on), by its case: the lanes. */
    val waiting: MutableMap<String, Set<String>> = LinkedHashMap()

    /** Every record replayed, by its case. */
    val replayed: MutableList<String> = ArrayList()

    override fun replay(misses: Misses) {
        replay(misses) { it }
    }

    /** Every record, each [edit]ed first (a test's, to see a difference found). */
    fun replay(misses: Misses, edit: (JsonObject) -> JsonObject) {
        waiting.clear()
        replayed.clear()
        for (name in listOf(GET, COMMANDS)) {
            for (line in Corpus.lines(name).filter { it["header"] != JsonPrimitive(true) }) one(edit(line), misses)
        }
    }

    // --- one record ---------------------------------------------------------------------------------------------

    private fun one(record: JsonObject, misses: Misses) {
        val case = text(record.getValue("case"))
        val fn = text(record.getValue("fn"))
        val kw = record.getValue("kw").jsonObject
        val done = (record["out"] ?: record.getValue("after")).jsonObject
        val said = done.getValue("result").jsonObject
        val events = done.getValue("events").jsonArray
        val request = kw["request"]?.jsonObject
        val asks = events.map { text(it.jsonArray[1]) }.toSet()
        val picks = listOfNotNull(request?.get("lacuerda")?.takeIf { it != JsonNull }?.let { "lacuerda" },
                                  request?.get("harptabs")?.takeIf { it != JsonNull }?.let { "harptabs" },
                                  request?.get("gametabs")?.takeIf { it != JsonNull }?.let { "gametabs" })
        val lanes = (asks + picks).mapNotNull { WAITING_ON[it] }.toSet()
        if (lanes.isNotEmpty()) {  // Phase A: waiting on a site lane
            waiting[case] = lanes
            return
        }
        val found = ArrayList<String>()
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
                    seedCache(cache, record["cache"]?.jsonObject ?: JsonObject(emptyMap()))
                    val transport = FakeTransport(answers(record["answers"]?.jsonObject ?: JsonObject(emptyMap())))
                    val cfg = configured(kw["providers"]?.jsonObject ?: JsonObject(emptyMap()))
                    var pauses = 0
                    val pacing = Pacing(sleep = { pauses++ }, draws = { low, high -> low + (high - low) * 0.5 },
                                        wallSeconds = { now.epochSecond.toDouble() }, monotonic = { 0.0 },
                                        clock = { now })
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
                    val store = LibraryStore(library)
                    val before = Tables.of(db)
                    val kvBefore = kv(db, prefixes)
                    val filesBefore = files(library, names)
                    val eventsBefore = db.one("SELECT COALESCE(MAX(id), 0) FROM events") { it.long(0)!! }!!
                    val saidLines = ArrayList<String>()
                    var address: String? = null

                    fun lookUp(req: LookupRequest): LookupResult =
                        Lookup(cfg, database, store, Clients(cfg, cache, { transport }, pacing), SongPages.NONE,
                               SongbookPages.NONE, Alerts.NONE, req, progress, pacing, standIns(said)).run(db)

                    val result = when (fn) {
                        "caracole.get.look_up" -> lookUp(request(request!!))
                        "caracole.versions_cmd.choose" -> {
                            val song = songNamed(db, text(kw.getValue("display")))
                            val tab = kw.getValue("tab").jsonPrimitive.content
                            val v = SheetVersions.inLibrary(db, song.id, cfg.rank).first { it.tabId == tab }
                            address = v.url
                            lookUp(LookupRequest(song.artist, song.title, tab = v.url))
                        }
                        "caracole.versions_cmd.clear" -> {
                            val song = songNamed(db, text(kw.getValue("display")))
                            val pins = SheetVersions.sheetPins(db, song.id, Overrides.read(db).pin[song.key].orEmpty())
                            OverrideWriters.removePin(db, song.display, pins.toSet())
                            saidLines += "Took ${pins.joinToString(", ") { "tab $it" }} out of [pin] in overrides.toml; " +
                                "caracole's pick is the sheet again."
                            lookUp(LookupRequest(song.artist, song.title))
                        }
                        else -> throw AssertionError("$case: no replay of $fn")
                    }
                    saidLines += LookupWords.totals(result)

                    fun check(ok: Boolean, what: () -> String) {
                        if (!ok) found += "$case: ${what()}"
                    }

                    val want = said.getValue("result").jsonObject
                    val got = resultOf(result)
                    for ((k, v) in want) check(got[k] == v) { "$k ${got[k]}, Python's $v" }
                    check(JsonArray(heard) == said.getValue("progress")) {
                        "told ${JsonArray(heard)},\n  Python's ${said["progress"]}"
                    }
                    said["said"]?.let { s -> check(JsonArray(saidLines.map(::JsonPrimitive)) == s) { "said $saidLines, Python's $s" } }
                    said["address"]?.let { a -> check((address?.let(::JsonPrimitive) ?: JsonNull) == a) { "asked $address, Python's $a" } }
                    val requests = JsonArray(transport.said.map(::JsonPrimitive))
                    check(requests == done["requests"]) { "requests $requests, Python's ${done["requests"]}" }
                    val gotEvents = JsonArray(db.query("SELECT run, provider, url, status, decision FROM events WHERE id > ? " +
                                                           "ORDER BY id", eventsBefore) { r ->
                        JsonArray(listOf(JsonPrimitive(r.text(0)), JsonPrimitive(r.text(1)), JsonPrimitive(r.text(2)),
                                         r.long(3)?.let(::JsonPrimitive) ?: JsonNull, JsonPrimitive(r.text(4))))
                    })
                    check(gotEvents == events) { "events $gotEvents, Python's $events" }
                    check(pauses == done.getValue("pauses").jsonPrimitive.int) { "$pauses pauses, Python's ${done["pauses"]}" }
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
                    val kvChanged = JsonObject((kvBefore.keys + kvAfter.keys).filter { kvBefore[it] != kvAfter[it] }.sorted()
                        .associateWith { k -> kvAfter[k]?.let(::JsonPrimitive) ?: JsonNull })
                    check(kvChanged == done["kv"]) { "kv $kvChanged, Python's ${done["kv"]}" }
                    val filesAfter = files(library, names)
                    val filesChanged = JsonObject((filesBefore.keys + filesAfter.keys).filter { filesBefore[it] != filesAfter[it] }
                        .sorted().associateWith { p -> filesAfter[p]?.let(::JsonPrimitive) ?: JsonNull })
                    check(filesChanged == done["library"]) { "files $filesChanged, Python's ${done["library"]}" }

                    // Phase A: a stage the phone hasn't yet (waiting on ug-fetch-artist's artist pages) says so.
                    val notYet = heard.any { e ->
                        val a = e.jsonArray
                        text(a[0]) == "stage" && text(a[1]) != "songbooks" && text(a[3]) == NotYet.WORDS
                    }
                    if (notYet && found.isNotEmpty()) waiting[case] = setOf(ARTIST_PAGES)
                }
            }
        } finally {
            dir.deleteRecursively()
        }
        if (case in waiting) return
        replayed += case
        misses.check(found.isEmpty()) { found.joinToString("\n") }
        for (f in found.drop(1)) misses.check(false) { f }
    }

    /** Phase A (waiting on lacuerda-sheets, tab-files, harptabs and gametabs): the stages of the site lanes not landed,
     * each asking its site through the envelope as get.py's does (its client made, nothing sent) and answering what
     * Python's said; LaCuerda's, asked for the sheet first, what its stage then said it came to. A record that asked
     * any of them a request waits for its lane instead ([one]). */
    private fun standIns(said: JsonObject): SiteStages {
        val result = said.getValue("result").jsonObject
        val states = result.getValue("states").jsonObject
        val details = result.getValue("details").jsonObject

        fun python(stage: String): StageEnd {
            val state = text(states[stage] ?: JsonPrimitive("skipped"))
            val detail = text(details[stage] ?: JsonPrimitive(""))
            val again = "asked already, for the sheet"
            if (stage == "lacuerda" && detail.startsWith(again)) {
                return StageEnd(if (state == "skipped") "done" else state, detail.removePrefix(again).removePrefix(": "))
            }
            return StageEnd(state, detail)
        }

        fun standIn(provider: String, stage: String) = SiteStage { ctx ->
            LookupWords.end(ctx.config, provider, ctx.asking.ask(provider) { python(stage) })
        }
        val all = SiteStages.ALL
        return SiteStages(all.match, all.ugSheet, all.ug, standIn("lacuerda", "lacuerda"), standIn("lacuerda", "lacuerda"),
                          all.lrclib, all.megalobiz, all.azlyrics, standIn("gtptabs", "gtptabs"),
                          standIn("harptabs", "harptabs"), standIn("gametabs", "gametabs"))
    }

    // --- the record's world -------------------------------------------------------------------------------------

    /** get.LookupRequest from its fields by Python's names. */
    private fun request(r: JsonObject): LookupRequest {
        fun opt(name: String) = r[name]?.takeIf { it != JsonNull }?.let(::text)
        return LookupRequest(text(r.getValue("artist")), text(r.getValue("title")), opt("album"),
                             r["duration_ms"]?.jsonPrimitive?.longOrNull, opt("ug"), opt("tab"), opt("lacuerda"),
                             opt("harptabs"), opt("gametabs"), r["songbooks"]?.jsonPrimitive?.booleanOrNull ?: true)
    }

    /** _common.song_named over "Artist - Title". */
    private fun songNamed(db: Db, display: String): SongRow {
        val (artist, title) = display.split(" - ", limit = 2)
        return Songs.byKey(db, Normalize.identityKey(artist, title)) ?: throw AssertionError("no song $display")
    }

    /** What the lookup came to, as the record writes Python's LookupResult. */
    private fun resultOf(r: LookupResult): JsonObject = JsonObject(mapOf(
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
