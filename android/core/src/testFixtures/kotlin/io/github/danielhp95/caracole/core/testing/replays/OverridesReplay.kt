package io.github.danielhp95.caracole.core.testing.replays

import io.github.danielhp95.caracole.core.db.Db
import io.github.danielhp95.caracole.core.library.GameTabsPick
import io.github.danielhp95.caracole.core.library.HarpTabsPick
import io.github.danielhp95.caracole.core.library.LaCuerdaPick
import io.github.danielhp95.caracole.core.library.OverrideUrls
import io.github.danielhp95.caracole.core.library.OverrideWriters
import io.github.danielhp95.caracole.core.library.Overrides
import io.github.danielhp95.caracole.core.library.OverridesError
import io.github.danielhp95.caracole.core.library.TabUrlRow
import io.github.danielhp95.caracole.core.py.Py
import io.github.danielhp95.caracole.core.testing.AreaReplay
import io.github.danielhp95.caracole.core.testing.Corpus
import io.github.danielhp95.caracole.core.testing.Misses
import io.github.danielhp95.caracole.core.testing.Record
import io.github.danielhp95.caracole.core.testing.TestDb
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.int
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import kotlinx.serialization.json.long
import java.nio.file.Files

/**
 * overrides.toml on the phone (tests/test_conformance_overrides.py): each record's rows put into `phone_overrides`
 * of a fresh database, in their order, then
 * - `library/overrides_read.jsonl`: [Overrides.read] (every field as Python reads the rows' entries, or its
 *   OverridesError's words) and [Overrides.artistUrlEntry];
 * - `library/overrides_writes.jsonl`: the writer of [OverrideWriters] (what it returned and the table whole after it,
 *   byte for byte, or its refusal's class and words with the table as before);
 * - `library/override_urls.jsonl`: [OverrideUrls]' readers and [LaCuerdaPick.holds].
 * The viewer's checks a record names (`checks`: key_version, check_spec) are given to the call as the record says
 * Python's answered, each call compared with Python's, in order.
 */
object OverridesReplay : AreaReplay {
    override val area = "overrides"

    const val READ = "library/overrides_read.jsonl"
    const val WRITES = "library/overrides_writes.jsonl"
    const val URLS = "library/override_urls.jsonl"

    override fun replay(misses: Misses) {
        reads(misses)
        writes(misses)
        urls(misses)
    }

    fun reads(misses: Misses) = withDb { db ->
        for (record in Corpus.records(READ)) {
            val case = "${record.fn.substringAfterLast('.')}: ${text(record.extra.getValue("case"))}"
            load(db, record)
            val (got, raised) = if (record.fn.endsWith("artist_url_entry")) {
                attempt {
                    val keys = record.args[0].jsonArray.map { text(it) }
                    Overrides.read(db).artistUrlEntry(keys)
                        ?.let { JsonArray(listOf(JsonPrimitive(it.first), JsonPrimitive(it.second))) } ?: JsonNull
                }
            } else {
                val checks = Checks(record.extra.getValue("checks").jsonArray, case, misses)
                attempt { fields(Overrides.read(db, checks.keyVersion, checks.checkSpec)) }.also { checks.done() }
            }
            answered(misses, case, record, got, raised)
        }
    }

    fun writes(misses: Misses) = withDb { db ->
        for (record in Corpus.records(WRITES)) {
            val case = "${record.fn.substringAfterLast('.')}: ${text(record.extra.getValue("case"))}"
            load(db, record)
            val before = rows(db)
            val checks = Checks(record.extra.getValue("checks").jsonArray, case, misses)
            val (got, raised) = attempt { write(db, record.fn.substringAfterLast('.'), record.kw, checks) }
            val after = rows(db)
            if (record.err != null) {
                answered(misses, case, record, got, raised)
                misses.check(after == before) { "$case: refused, but the rows are ${after}, not as before" }
            } else {
                val want = record.out!!.jsonObject
                answered(misses, case, record, got, raised, want.getValue("returned"))
                misses.check(after == want.getValue("rows")) { "$case: the rows are\n  $after\nPython's\n  ${want["rows"]}" }
            }
            checks.done()
        }
    }

    fun urls(misses: Misses) {
        for (record in Corpus.records(URLS)) {
            val name = record.fn.substringAfterLast('.')
            val arg = record.args[0]
            val case = "$name(${arg.toString().take(120)})"
            val (got, raised) = attempt { address(record.fn, record.args) }
            answered(misses, case, record, got, raised)
        }
    }

    // --- the calls ------------------------------------------------------------------------------------------------

    private fun write(db: Db, fn: String, kw: JsonObject, checks: Checks): JsonElement {
        fun s(name: String): String = text(kw.getValue(name))
        fun strings(name: String): List<String> = kw.getValue(name).jsonArray.map { text(it) }
        when (fn) {
            "add_match" -> OverrideWriters.addMatch(db, s("display"), s("ug_ref"))
            "add_pin" -> OverrideWriters.addPin(db, s("display"), strings("urls"))
            "remove_pin" -> {
                val tabs = (kw.getValue("tabs") as? JsonArray)?.map { it.jsonPrimitive.long }?.toSet()
                return JsonPrimitive(OverrideWriters.removePin(db, s("display"), tabs))
            }
            "add_lacuerda" -> OverrideWriters.addLacuerda(db, s("display"), s("url"))
            "add_harptabs" -> OverrideWriters.addHarptabs(db, s("display"), s("url"))
            "add_gametabs" -> OverrideWriters.addGametabs(db, s("display"), s("url"))
            "add_reject" -> OverrideWriters.addReject(db, s("display"), strings("ug_refs"))
            "add_alias" -> OverrideWriters.addAlias(db, s("source_artist"), s("ug_artist"))
            "add_ignore" -> OverrideWriters.addIgnore(db, s("display"))
            "add_version" -> OverrideWriters.addVersion(db, s("display"), (kw.getValue("query") as? JsonPrimitive)
                ?.takeIf { it.isString }?.content, checks.keyVersion)
            "add_harmonica" -> OverrideWriters.addHarmonica(db, s("display"), s("tab"),
                                                            kw.getValue("reading").takeIf { it !is JsonNull },
                                                            checks.checkSpec)
            else -> throw AssertionError("no writer $fn")
        }
        return JsonNull
    }

    private fun address(fn: String, args: JsonArray): JsonElement {
        val s = if (args[0] is JsonPrimitive) text(args[0]) else ""
        return when (fn.substringAfterLast('.')) {
            "override_key" -> JsonPrimitive(OverrideUrls.overrideKey(s))
            "tab_id_from_url" -> JsonPrimitive(OverrideUrls.tabIdFromUrl(s))
            "pin_url" -> JsonPrimitive(OverrideUrls.pinUrl(s))
            "artist_page_address" -> nullable(OverrideUrls.artistPageAddress(s))
            "_artist_url_value" -> nullable(OverrideUrls.artistUrlValue(s))
            "pasted_tab_id" -> OverrideUrls.pastedTabId(s)?.let { JsonPrimitive(it) } ?: JsonNull
            "lacuerda_pick_from_url" -> pick(OverrideUrls.lacuerdaPickFromUrl(s))
            "harptabs_pick_from_url" -> pick(OverrideUrls.harptabsPickFromUrl(s))
            "gametabs_pick_from_url" -> pick(OverrideUrls.gametabsPickFromUrl(s))
            "azlyrics_page_from_url" -> JsonPrimitive(OverrideUrls.azlyricsPageFromUrl(s))
            "video_id_from_url" -> nullable(OverrideUrls.videoIdFromUrl(s))
            "classify_tab_url" -> OverrideUrls.classifyTabUrl(s)?.let { JsonPrimitive(it) }
                ?: OverrideUrls.parseTabUrl(s)!!.let(::row)
            "holds" -> {
                val p = args[0].jsonObject
                val pick = LaCuerdaPick(text(p.getValue("artist")), text(p.getValue("song")),
                                        (p.getValue("version") as? JsonPrimitive)?.takeIf { it !is JsonNull }?.int)
                JsonPrimitive(pick.holds(text(args[1])))
            }
            else -> throw AssertionError("no reader $fn")
        }
    }

    // --- what an answer is, as the corpus writes it ---------------------------------------------------------------

    private fun nullable(s: String?): JsonElement = s?.let { JsonPrimitive(it) } ?: JsonNull

    private fun strings(xs: Iterable<String>) = JsonArray(xs.map { JsonPrimitive(it) })

    private fun <V> obj(m: Map<String, V>, value: (V) -> JsonElement) = JsonObject(m.mapValues { value(it.value) })

    private fun pick(p: Any): JsonElement = when (p) {
        is LaCuerdaPick -> JsonObject(mapOf("artist" to JsonPrimitive(p.artist), "song" to JsonPrimitive(p.song),
                                            "version" to (p.version?.let { JsonPrimitive(it) } ?: JsonNull),
                                            "url" to JsonPrimitive(p.url)))
        is HarpTabsPick -> JsonObject(mapOf("tab_id" to JsonPrimitive(p.tabId), "slug" to JsonPrimitive(p.slug),
                                            "path" to JsonPrimitive(p.path), "url" to JsonPrimitive(p.url)))
        is GameTabsPick -> JsonObject(mapOf("game" to JsonPrimitive(p.game), "slug" to JsonPrimitive(p.slug),
                                            "path" to JsonPrimitive(p.path), "url" to JsonPrimitive(p.url)))
        else -> throw AssertionError("no pick $p")
    }

    private fun row(r: TabUrlRow) = JsonObject(mapOf(
        "tab_id" to JsonPrimitive(r.tabId), "artist_key" to JsonPrimitive(r.artistKey),
        "song_key" to JsonPrimitive(r.songKey), "type" to JsonPrimitive(r.type), "path" to JsonPrimitive(r.path),
    ))

    private val PAIRS = compareBy<Pair<String, String>, String>(Py.CODE_POINT_ORDER) { it.first }
        .thenBy(Py.CODE_POINT_ORDER) { it.second }

    private fun pair(p: Pair<String, String>) = strings(listOf(p.first, p.second))

    /** Every field of an Overrides as the corpus writes it (a set sorted by code point, a pair an array, a pick its
     * fields: tests/test_conformance_overrides.py's `fields`). */
    fun fields(o: Overrides): JsonObject = JsonObject(mapOf(
        "alias" to obj(o.alias, ::strings),
        "match" to obj(o.match, ::pair),
        "artist_url" to obj(o.artistUrl) { JsonPrimitive(it) },
        "pin" to obj(o.pin) { tabs -> JsonArray(tabs.map { JsonPrimitive(it) }) },
        "transpose" to obj(o.transpose) { JsonPrimitive(it) },
        "ignore" to strings(o.ignore.sortedWith(Py.CODE_POINT_ORDER)),
        "block" to JsonArray(o.block.sorted().map { JsonPrimitive(it) }),
        "pin_urls" to obj(o.pinUrls, ::strings),
        "reject" to obj(o.reject) { set -> JsonArray(set.sortedWith(PAIRS).map(::pair)) },
        "artist_url_names" to obj(o.artistUrlNames) { JsonPrimitive(it) },
        "youtube" to obj(o.youtube, ::nullable),
        "lacuerda" to obj(o.lacuerda) { p -> (pick(p) as JsonObject).let { JsonObject(it - "url") } },
        "harptabs" to obj(o.harptabs) { p -> JsonObject((pick(p) as JsonObject) - "url" - "path") },
        "gametabs" to obj(o.gametabs) { p -> JsonObject((pick(p) as JsonObject) - "url" - "path") },
        "azlyrics" to obj(o.azlyrics) { JsonPrimitive(it) },
        "version" to obj(o.version) { JsonPrimitive(it) },
        "harmonica" to obj(o.harmonica) { JsonObject(it) },
        "tables" to strings(o.tables.sortedWith(Py.CODE_POINT_ORDER)),
    ))

    // --- the plumbing ---------------------------------------------------------------------------------------------

    /** The viewer's checks as Python's answered them: each call compared with the record's next, in order, and its
     * ValueError (IllegalArgumentException, with its words) raised where Python's raised. */
    private class Checks(private val expected: JsonArray, private val case: String, private val misses: Misses) {
        private var at = 0

        private fun call(fn: String, arg: JsonElement) {
            val want = expected.getOrNull(at++)?.jsonObject
            if (want == null || text(want.getValue("fn")) != fn || want["arg"] != arg) {
                misses.check(false) { "$case: called $fn($arg), Python's call ${at}: $want" }
                return
            }
            val error = want["error"]
            if (error != null && error !is JsonNull) throw IllegalArgumentException(text(error))
        }

        val keyVersion: (String) -> Any? = { call("key_version", JsonPrimitive(it)) }
        val checkSpec: (JsonElement) -> Unit = { call("check_spec", it) }

        fun done() = misses.check(at == expected.size) { "$case: ${at} checks called, Python's ${expected.size}" }
    }

    private fun <T> attempt(block: () -> T): Pair<T?, Exception?> = try {
        block() to null
    } catch (e: Exception) {
        null to e
    }

    /** [got] (or what it [raised]) against the record's out, or its err and message. */
    private fun answered(misses: Misses, case: String, record: Record, got: Any?, raised: Exception?,
                         out: JsonElement? = record.out) {
        when {
            record.err == null && raised != null -> misses.check(false) { "$case: threw $raised, Python answered $out" }
            record.err == null -> misses.check(got == (out ?: JsonNull)) { "$case: answered $got, Python $out" }
            else -> {
                val kind = when (raised) {
                    is OverridesError -> "OverridesError"
                    is IllegalArgumentException -> "ValueError"
                    else -> raised?.let { it::class.simpleName }
                }
                misses.check(kind == record.err) { "$case: ${raised ?: "answered $got"}, Python raised ${record.err}" }
                val message = text(record.extra.getValue("message"))
                misses.check(raised?.message == message) { "$case: said ${raised?.message}, Python $message" }
            }
        }
    }

    private fun load(db: Db, record: Record) {
        db.execute("DELETE FROM phone_overrides")
        for (row in record.extra.getValue("rows").jsonArray) {
            val r = row.jsonObject
            db.execute("INSERT INTO phone_overrides (tbl, key, written, value) VALUES (?, ?, ?, ?)",
                       text(r.getValue("tbl")), text(r.getValue("key")), text(r.getValue("written")),
                       text(r.getValue("value")))
        }
    }

    /** The table whole, as the corpus writes it: by table and key, in code-point order (SQLite's BINARY over UTF-8). */
    private fun rows(db: Db): JsonArray = JsonArray(
        db.query("SELECT tbl, key, written, value FROM phone_overrides ORDER BY tbl, key") {
            JsonObject(mapOf("tbl" to JsonPrimitive(it.text(0)), "key" to JsonPrimitive(it.text(1)),
                             "written" to JsonPrimitive(it.text(2)), "value" to JsonPrimitive(it.text(3))))
        },
    )

    private fun withDb(block: (Db) -> Unit) {
        val dir = Files.createTempDirectory("overrides").toFile()
        try {
            TestDb.fresh(dir).use { database -> database.writeBlocking(block) }
        } finally {
            dir.deleteRecursively()
        }
    }
}
