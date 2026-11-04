package io.github.danielhp95.caracole.core.testing

import io.github.danielhp95.caracole.core.db.Db
import io.github.danielhp95.caracole.core.json.PyJson
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive

/**
 * helpers.corpus.dump_fixture on the phone: a database's fixture records, each line as the corpus writes it
 * (`json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":"))`), so that a database after a
 * merge compares with Python's dump line by line, its kv text byte for byte (IndexReplay, on the JVM and the device).
 */
object Dumps {
    /** helpers.corpus.FIXTURE_TABLES, then PHONE_TABLES, which every phone database has. */
    private val TABLES = listOf(
        "songs", "versions", "files", "removed", "events", "ug_index", "ug_artist_tabs", "lacuerda_index",
        "gtptabs_index", "musescore_index", "harptabs_index", "harptabs_artists", "harptabs_artist_tabs",
        "gametabs_index", "gametabs_games", "gametabs_game_tabs", "phone_overrides", "phone_songbooks",
    )

    private fun quoted(name: String) = "\"" + name.replace("\"", "\"\"") + "\""

    private fun line(record: Map<String, JsonElement>) =
        PyJson.dumps(JsonObject(record), sortKeys = true, compact = true)

    /** The fixture lines of [db]: every table's rows in rowid order, then kv by key without `sync:id`. */
    fun lines(db: Db): List<String> {
        val out = ArrayList<String>()
        for (table in TABLES) {
            val columns = db.query("PRAGMA main.table_info(${quoted(table)})") { it.text(1)!! }
            val select = columns.joinToString(", ") { "typeof(${quoted(it)}), ${quoted(it)}" }
            out += db.query("SELECT $select FROM ${quoted(table)} ORDER BY rowid") { row ->
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
                line(mapOf("table" to JsonPrimitive(table), "row" to JsonObject(values)))
            }
        }
        out += db.query("SELECT key, value FROM kv ORDER BY key") { it.text(0)!! to it.text(1)!! }
            .filter { it.first != "sync:id" }
            .map { (key, value) -> line(mapOf("kv" to JsonPrimitive(key), "value" to JsonPrimitive(value))) }
        return out
    }

    /** A fixture's lines, its header left out. */
    fun fixture(name: String): List<String> =
        Corpus.text("index/fixtures/$name.jsonl").split('\n').filter { it.isNotEmpty() }.drop(1)
}
