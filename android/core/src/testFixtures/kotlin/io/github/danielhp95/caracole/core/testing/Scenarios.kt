package io.github.danielhp95.caracole.core.testing

import io.github.danielhp95.caracole.core.config.PhoneConfig
import io.github.danielhp95.caracole.core.config.ProviderPolicy
import io.github.danielhp95.caracole.core.db.Db
import io.github.danielhp95.caracole.core.http.Event
import io.github.danielhp95.caracole.core.http.HttpAnswer
import io.github.danielhp95.caracole.core.http.PoliteClient
import io.github.danielhp95.caracole.core.json.PyJson
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
import java.security.MessageDigest
import java.time.Instant
import java.util.Base64
import java.util.zip.GZIPOutputStream

/** What a scenario record is replayed in: its fixture's database, a library folder, a cache seeded from the record,
 * a [FakeTransport] serving its answers and a [PoliteClient] per client of the record, its clocks at [now]. */
class ScenarioWorld(val db: Db, val library: File, val cacheDir: File, val transport: FakeTransport,
                    val clients: Map<String, PoliteClient>, val now: Instant = Instant.EPOCH)

/**
 * Scenario records (docs/superpowers/specs/2026-11-03-conformance-corpus.md, "Scenario records"; Python's
 * tests/helpers/scenario.py): [replay] builds the record's world, runs [pass] in it, and compares the result (or what
 * it raised: its class's simple name and its message), the requests, the rows of the tables the pass changed, the kv
 * records, the library's files, the events and the number of pauses with the record's.
 *
 * Each client's policy is config.py's default for its provider (data/caracole/config/config.json; none: no budget,
 * no pause) with the record's budget and delay, its user agent config.py's; its pauses counted and never slept (a
 * pause's length is random in Python, so only how many is compared), its clocks fixed at the record's `now`. The
 * events are those the clients told (each [Event] as `[provider, url, status, decision]`, as EventLog writes their
 * rows); [eventLog], when given, is told them too (health-pace's EventLog, so the pass sees its rows).
 */
object Scenarios {
    /** Python's draw for a pause a scenario never sleeps: any u will do, and u = 0.5 is the middle of the delay. */
    private const val U = 0.5

    fun replay(record: JsonObject, eventLog: ((Db, String) -> ((Event) -> Unit))? = null,
               pass: (ScenarioWorld) -> Any?) {
        val misses = Misses(record["case"]?.jsonPrimitive?.content ?: "a scenario")
        replay(record, misses, eventLog, pass)
        misses.assertNone()
    }

    /** [replay], each difference told to [misses]. */
    fun replay(record: JsonObject, misses: Misses, eventLog: ((Db, String) -> ((Event) -> Unit))? = null,
               pass: (ScenarioWorld) -> Any?) {
        val case = record["case"]?.jsonPrimitive?.content ?: ""
        val dir = Files.createTempDirectory("caracole-scenario").toFile()
        try {
            val library = File(dir, "library").apply { mkdirs() }
            val cacheDir = File(dir, "cache")
            val now = Instant.parse(record.getValue("now").jsonPrimitive.content)
            TestDb.fresh(dir).use { database ->
                database.writeBlocking { db ->
                    Fixtures.loadRecords(db, (record["fixture"] as? JsonArray ?: JsonArray(emptyList())).map { it.jsonObject },
                                         library, case)
                    seedCache(cacheDir, record["cache"] as? JsonObject ?: JsonObject(emptyMap()))
                    val transport = FakeTransport(answers(record["answers"] as? JsonObject ?: JsonObject(emptyMap())))
                    val events = ArrayList<Event>()
                    var pauses = 0
                    val log = eventLog?.invoke(db, record["run"]?.jsonPrimitive?.content ?: "lookup:${record.getValue("now").jsonPrimitive.content}")
                    val clients = (record["clients"] as? JsonObject ?: JsonObject(emptyMap())).mapValues { (provider, c) ->
                        val spec = c.jsonObject
                        val delay = spec.getValue("delay").jsonArray
                        val base = PhoneConfig.DEFAULTS.providers[provider] ?: ProviderPolicy(budget = 0, delay = 0.0 to 0.0)
                        PoliteClient(provider, base.copy(budget = spec.getValue("budget").jsonPrimitive.long,
                                                         delay = delay[0].jsonPrimitive.double to delay[1].jsonPrimitive.double),
                                     cacheDir, PhoneConfig.DEFAULTS.userAgent, transport, sleep = { pauses++ },
                                     draws = { low, high -> low + (high - low) * U },
                                     onEvent = { e -> events += e; log?.invoke(e) },
                                     monotonic = { 0.0 }, wallClock = { now })
                    }
                    val before = tables(db)
                    val kvBefore = kv(db)
                    val filesBefore = files(library)
                    var result: Any? = null
                    var raised: Throwable? = null
                    try {
                        result = pass(ScenarioWorld(db, library, cacheDir, transport, clients, now))
                    } catch (e: AssertionError) {
                        throw e
                    } catch (e: Exception) {
                        raised = e
                    } finally {
                        clients.values.forEach { it.close() }
                    }
                    val done: JsonObject
                    if (record["raises"] != null) {
                        val want = record.getValue("raises").jsonObject
                        misses.check(raised != null) { "$case: Python raised $want, the phone answered ${json(result)}" }
                        if (raised != null) {
                            misses.check(raised::class.simpleName == want.getValue("type").jsonPrimitive.content &&
                                             raised.message == want.getValue("message").jsonPrimitive.content) {
                                "$case: raised ${raised::class.simpleName}: ${raised.message}, Python $want"
                            }
                        }
                        done = record.getValue("after").jsonObject
                    } else {
                        done = record.getValue("out").jsonObject
                        misses.check(raised == null) { "$case: the phone raised $raised, Python answered ${done["result"]}" }
                        if (raised == null) {
                            val got = json(result)
                            misses.check(got == done["result"]) { "$case: result $got, Python's ${done["result"]}" }
                        }
                    }
                    val requests = transport.said.map { JsonPrimitive(it) }
                    misses.check(JsonArray(requests) == done["requests"]) { "$case: requests $requests, Python's ${done["requests"]}" }
                    val gotEvents = events.map { e ->
                        JsonArray(listOf(JsonPrimitive(e.provider), JsonPrimitive(e.url), e.status?.let { JsonPrimitive(it) } ?: JsonNull,
                                         JsonPrimitive(e.decision)))
                    }
                    misses.check(JsonArray(gotEvents) == done["events"]) { "$case: events $gotEvents, Python's ${done["events"]}" }
                    misses.check(pauses == done["pauses"]?.jsonPrimitive?.int) { "$case: $pauses pauses, Python ${done["pauses"]}" }
                    val after = tables(db)
                    val changed = (before.keys + after.keys).filter { it != "events" && before[it] != after[it] }.toSet()
                    val wantRows = done["rows"] as? JsonObject ?: JsonObject(emptyMap())
                    misses.check(changed == wantRows.keys) { "$case: the pass changed ${changed.sorted()}, Python's ${wantRows.keys.sorted()}" }
                    for ((table, rows) in wantRows) {
                        misses.check(JsonArray(after[table].orEmpty()) == rows) { "$case: $table holds ${after[table]}, Python's $rows" }
                    }
                    val kvAfter = kv(db)
                    val kvChanged = (kvBefore.keys + kvAfter.keys).filter { kvBefore[it] != kvAfter[it] }.sorted()
                        .associateWith { k -> kvAfter[k]?.let { JsonPrimitive(it) } ?: JsonNull }
                    misses.check(JsonObject(kvChanged) == (done["kv"] ?: JsonObject(emptyMap()))) { "$case: kv $kvChanged, Python's ${done["kv"]}" }
                    val filesAfter = files(library)
                    val filesChanged = (filesBefore.keys + filesAfter.keys).filter { filesBefore[it] != filesAfter[it] }.sorted()
                        .associateWith { p -> filesAfter[p]?.let { JsonPrimitive(it) } ?: JsonNull }
                    misses.check(JsonObject(filesChanged) == (done["library"] ?: JsonObject(emptyMap()))) {
                        "$case: the library's files $filesChanged, Python's ${done["library"]}"
                    }
                }
            }
        } finally {
            dir.deleteRecursively()
        }
    }

    /** A record's body: `{"text"}`, `{"base64"}` or `{"fixture"}` (Corpus.fixture). */
    fun body(spec: JsonElement): ByteArray {
        val o = spec.jsonObject
        return when {
            "text" in o -> o.getValue("text").jsonPrimitive.content.toByteArray(Charsets.UTF_8)
            "base64" in o -> Base64.getDecoder().decode(o.getValue("base64").jsonPrimitive.content)
            "fixture" in o -> Corpus.fixture(o.getValue("fixture").jsonPrimitive.content)
            else -> throw AssertionError("not a body: $spec")
        }
    }

    private fun answers(record: JsonObject): Map<String, HttpAnswer> = record.mapValues { (_, a) ->
        val o = a.jsonObject
        HttpAnswer(o.getValue("status").jsonPrimitive.int,
                   (o["headers"] as? JsonArray ?: JsonArray(emptyList())).map { h ->
                       h.jsonArray[0].jsonPrimitive.content to h.jsonArray[1].jsonPrimitive.content
                   }, body(o["body"] ?: JsonObject(mapOf("text" to JsonPrimitive("")))))
    }

    /** The record's cache, written as http.py writes one: the body gzip'd, the meta as json.dumps writes it. */
    private fun seedCache(cacheDir: File, cache: JsonObject) {
        for ((provider, entries) in cache) {
            for ((request, e) in entries.jsonObject) {
                val url = request.substringAfter(' ')
                val entry = e.jsonObject
                val key = sha256(url.toByteArray(Charsets.UTF_8))
                val folder = File(File(File(cacheDir, "http"), provider), key.substring(0, 2)).apply { mkdirs() }
                File(folder, "$key.body").writeBytes(gzip(body(entry.getValue("body"))))
                val meta = JsonObject(linkedMapOf("url" to JsonPrimitive(url), "status" to entry.getValue("status"),
                                                  "headers" to (entry["headers"] ?: JsonObject(emptyMap())),
                                                  "fetched_at" to entry.getValue("fetched_at")))
                File(folder, "$key.json").writeBytes(PyJson.dumps(meta).toByteArray(Charsets.UTF_8))
            }
        }
    }

    private fun gzip(data: ByteArray): ByteArray {
        val out = java.io.ByteArrayOutputStream()
        GZIPOutputStream(out).use { it.write(data) }
        return out.toByteArray()
    }

    internal fun sha256(data: ByteArray): String = MessageDigest.getInstance("SHA-256").digest(data)
        .joinToString("") { b -> "0123456789abcdef"[(b.toInt() shr 4) and 15].toString() + "0123456789abcdef"[b.toInt() and 15] }

    /** helpers.corpus.FIXTURE_TABLES, then the phone's. */
    private val TABLES = listOf(
        "songs", "versions", "files", "removed", "events", "ug_index", "ug_artist_tabs", "lacuerda_index",
        "gtptabs_index", "musescore_index", "harptabs_index", "harptabs_artists", "harptabs_artist_tabs",
        "gametabs_index", "gametabs_games", "gametabs_game_tabs", "phone_overrides", "phone_songbooks",
    )

    private fun quoted(name: String) = "\"" + name.replace("\"", "\"\"") + "\""

    /** Each table's rows in rowid order, as dump_fixture reads them. */
    private fun tables(db: Db): Map<String, List<JsonObject>> = TABLES.associateWith { table ->
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

    private fun kv(db: Db): Map<String, String> =
        db.query("SELECT key, value FROM kv ORDER BY key") { it.text(0)!! to it.text(1)!! }.filter { it.first != "sync:id" }.toMap()

    private fun files(library: File): Map<String, String> = library.walkTopDown().filter { it.isFile }
        .associate { it.relativeTo(library).invariantSeparatorsPath to sha256(it.readBytes()) }

    /** A pass's result as a corpus writes it (helpers.corpus.plain). */
    fun json(value: Any?): JsonElement = when (value) {
        null -> JsonNull
        is JsonElement -> value
        is String -> JsonPrimitive(value)
        is Boolean -> JsonPrimitive(value)
        is Int -> JsonPrimitive(value)
        is Long -> JsonPrimitive(value)
        is Double -> PyJson.float(value)
        is Pair<*, *> -> JsonArray(listOf(json(value.first), json(value.second)))
        is Triple<*, *, *> -> JsonArray(listOf(json(value.first), json(value.second), json(value.third)))
        is List<*> -> JsonArray(value.map { json(it) })
        is Map<*, *> -> JsonObject(value.entries.associate { (k, v) -> k as String to json(v) })
        else -> throw AssertionError("no corpus form for $value")
    }
}
