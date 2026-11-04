package io.github.danielhp95.caracole.core.testing.replays

import androidx.sqlite.driver.bundled.BundledSQLiteDriver
import androidx.sqlite.execSQL
import io.github.danielhp95.caracole.core.index.IndexExport
import io.github.danielhp95.caracole.core.index.IndexTransfer
import io.github.danielhp95.caracole.core.index.Reads
import io.github.danielhp95.caracole.core.index.TransferError
import io.github.danielhp95.caracole.core.json.PyJson
import io.github.danielhp95.caracole.core.testing.AreaReplay
import io.github.danielhp95.caracole.core.testing.Corpus
import io.github.danielhp95.caracole.core.testing.Fixtures
import io.github.danielhp95.caracole.core.testing.Misses
import io.github.danielhp95.caracole.core.testing.Record
import io.github.danielhp95.caracole.core.testing.TestDb
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.int
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import java.io.File
import java.nio.file.Files

/**
 * The phone's index export (vectors/index/export.jsonl, lane index-push): each record's phone
 * (`index/fixtures/reads-before`) loaded into a new database, the pages core.index.Reads gives since the last push to
 * that computer equal to the record's `pages`, then those pages exported (IndexExport.export, at the record's `now`,
 * by its `caracole`): the export's sites and rows as Python's Exported says, and the file itself, dumped as
 * helpers.corpus.dump_fixture(raw=True) dumps one (its `CREATE` lines, then each table's rows in rowid order, each
 * line as the corpus writes it), equal to Python's fixture line by line once its META `source`, the phone's own
 * database (checked first), is the fixture's. A refusal is a TransferError that leaves no file. tests/
 * test_conformance_index.py says the vector's form.
 */
object IndexExportReplay : AreaReplay {
    override val area = "index-export"

    override fun replay(misses: Misses) {
        for (record in Corpus.records("index/export.jsonl")) replay(misses, record)
    }

    /** One record of export.jsonl, answered by the phone. */
    fun replay(misses: Misses, record: Record) {
        val dir = Files.createTempDirectory("caracole-index-export").toFile()
        val note = record.extra["note"]?.jsonPrimitive?.contentOrNull ?: record.kw.toString()
        try {
            val fixture = record.extra.getValue("fixture").jsonObject
            val pages = record.kw.getValue("pages").jsonObject.mapValues { (_, list) ->
                list.jsonArray.map { it.jsonPrimitive.content }
            }
            val peer = record.kw["peer"]?.jsonPrimitive?.contentOrNull
            val now = record.kw.getValue("now").jsonPrimitive.content
            val caracole = record.kw.getValue("caracole").jsonPrimitive.content
            val to = File(dir, "reads.sqlite")
            TestDb.fresh(dir).use { database ->
                database.writeBlocking {
                    Fixtures.load(it, "index/fixtures/${fixture.getValue("before").jsonPrimitive.content}.jsonl")
                }
                if (peer != null) {
                    val since = database.read { Reads.since(it, peer) }
                    misses.check(since == pages) { "$note: Reads.since(…, $peer) = $since, Python's $pages" }
                }
                if (record.err != null) {
                    val refused = try {
                        database.writeBlocking { IndexExport.export(it, to, pages, now, caracole) }
                        null
                    } catch (e: TransferError) {
                        e
                    }
                    misses.check(refused != null) { "$note: exported, Python raised ${record.err}" }
                    misses.check(!to.exists() && dir.list().orEmpty().none { it.endsWith(".part") }) {
                        "$note: a refusal left ${dir.list().orEmpty().toList()}"
                    }
                    return
                }
                val exported = database.writeBlocking { IndexExport.export(it, to, pages, now, caracole) }
                val out = record.out!!.jsonObject
                val sites = out.getValue("sites").jsonArray.map { it.jsonPrimitive.content }
                val rows = out.getValue("rows").jsonObject.mapValues { it.value.jsonPrimitive.int }
                misses.check(exported.sites == sites) { "$note: sites ${exported.sites}, Python's $sites" }
                misses.check(exported.rows == rows) { "$note: rows ${exported.rows}, Python's $rows" }
                misses.check(exported.path == to && exported.size == to.length()) { "$note: $exported is no file at $to" }
                val expected = Corpus.text("index/fixtures/${fixture.getValue("export").jsonPrimitive.content}.jsonl")
                    .split('\n').filter { it.isNotEmpty() }.drop(1)
                val source = meta(to, "source")
                misses.check(source != null && File(source).canonicalFile == database.path.canonicalFile) {
                    "$note: META source $source, not the phone's ${database.path}"
                }
                setMeta(to, "source", expectedSource(expected))
                val got = rawLines(to)
                val first = got.indices.firstOrNull { it >= expected.size || got[it] != expected[it] }
                misses.check(got == expected) {
                    "$note: the export differs from Python's at line ${(first ?: expected.size) + 2}: " +
                        "${got.getOrNull(first ?: expected.size)?.take(300)} vs ${expected.getOrNull(first ?: got.size)?.take(300)}"
                }
            }
        } finally {
            dir.deleteRecursively()
        }
    }

    /** The fixture's META `source`. */
    private fun expectedSource(lines: List<String>): String = lines.map { Json.parseToJsonElement(it).jsonObject }.first { it["table"] == JsonPrimitive(IndexTransfer.META) && it["row"]!!.jsonObject["key"] == JsonPrimitive("source") }
        .getValue("row").jsonObject.getValue("value").jsonPrimitive.content

    private fun meta(file: File, key: String): String? {
        val connection = BundledSQLiteDriver().open(file.path)
        try {
            return connection.prepare("SELECT value FROM ${IndexTransfer.META} WHERE key = ?").use {
                it.bindText(1, key)
                if (it.step()) it.getText(0) else null
            }
        } finally {
            connection.close()
        }
    }

    private fun setMeta(file: File, key: String, value: String) {
        val connection = BundledSQLiteDriver().open(file.path)
        try {
            connection.prepare("UPDATE ${IndexTransfer.META} SET value = ? WHERE key = ?").use {
                it.bindText(1, value)
                it.bindText(2, key)
                it.step()
            }
        } finally {
            connection.close()
        }
    }

    /**
     * helpers.corpus.dump_fixture(conn, raw=True) of [file], each record a line as the corpus writes it
     * (`json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":"))`): the `CREATE` statements,
     * tables then indexes, as sqlite_master holds them, then every table's rows in that order, by rowid.
     */
    fun rawLines(file: File): List<String> {
        val connection = BundledSQLiteDriver().open(file.path)
        try {
            connection.execSQL("BEGIN")
            val objects = ArrayList<Triple<String, String, String>>()
            connection.prepare(
                "SELECT type, name, sql FROM sqlite_master WHERE type IN ('table', 'index') AND sql IS NOT NULL " +
                    "ORDER BY CASE type WHEN 'table' THEN 0 ELSE 1 END, rowid",
            ).use { st -> while (st.step()) objects += Triple(st.getText(0), st.getText(1), st.getText(2)) }
            val out = objects.map { line(mapOf("sql" to JsonPrimitive(it.third))) }.toMutableList()
            for ((type, table) in objects) {
                if (type != "table") continue
                val columns = ArrayList<String>()
                connection.prepare("PRAGMA table_info(${quoted(table)})").use { st ->
                    while (st.step()) columns += st.getText(1)
                }
                val select = columns.joinToString(", ") { "typeof(${quoted(it)}), ${quoted(it)}" }
                connection.prepare("SELECT $select FROM ${quoted(table)} ORDER BY rowid").use { st ->
                    while (st.step()) {
                        val values = LinkedHashMap<String, JsonElement>()
                        columns.forEachIndexed { i, column ->
                            values[column] = when (val kind = st.getText(2 * i)) {
                                "null" -> JsonNull
                                "integer" -> JsonPrimitive(st.getLong(2 * i + 1))
                                "real" -> PyJson.float(st.getDouble(2 * i + 1))
                                "text" -> JsonPrimitive(st.getText(2 * i + 1))
                                else -> error("$table holds a $kind, which a fixture can't carry")
                            }
                        }
                        out += line(mapOf("table" to JsonPrimitive(table), "row" to JsonObject(values)))
                    }
                }
            }
            connection.execSQL("COMMIT")
            return out
        } finally {
            connection.close()
        }
    }

    private fun line(record: Map<String, JsonElement>) = PyJson.dumps(JsonObject(record), sortKeys = true, compact = true)

    private fun quoted(name: String) = "\"" + name.replace("\"", "\"\"") + "\""
}
