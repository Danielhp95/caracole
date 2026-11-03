package io.github.danielhp95.caracole.core.testing

import androidx.sqlite.SQLiteStatement
import androidx.sqlite.driver.bundled.BundledSQLiteDriver
import androidx.sqlite.execSQL
import io.github.danielhp95.caracole.core.db.Db
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import java.io.File
import java.util.Base64

/**
 * A fixture of the corpus (vectors/<area>/fixtures/<name>.jsonl) replayed as helpers.corpus.replay_fixture replays
 * it: one plain INSERT per row in file order, so the triggers number what they fill alike; kv lines as upserts; each
 * file written under the library folder.
 */
object Fixtures {
    /** [name] into [db], a freshly migrated database (TestDb.fresh), in one savepoint. */
    fun load(db: Db, name: String, libraryDir: File? = null) {
        val records = Corpus.lines(name).filter { it["header"] != JsonPrimitive(true) }
        require(records.none { "sql" in it }) { "$name makes its own tables: Fixtures.loadRaw" }
        db.savepoint("fixture") {
            for (record in records) {
                when {
                    "table" in record -> {
                        val row = record.getValue("row").jsonObject
                        val names = row.keys.toList()
                        db.execute(insert(record.getValue("table").jsonPrimitive.content, names),
                                   *names.map { value(row.getValue(it)) }.toTypedArray())
                    }
                    "kv" in record -> db.kvSet(record.getValue("kv").jsonPrimitive.content,
                                               record.getValue("value").jsonPrimitive.content)
                    "file" in record -> write(record, libraryDir ?: error("$name has files: give it a library folder"))
                    else -> error("not a fixture record: $record")
                }
            }
        }
    }

    /** [name], a fixture with its own tables (an index export), into the empty database file [file]. */
    fun loadRaw(file: File, name: String) {
        val records = Corpus.lines(name).filter { it["header"] != JsonPrimitive(true) }
        val connection = BundledSQLiteDriver().open(file.path)
        try {
            connection.execSQL("BEGIN IMMEDIATE")
            for (record in records) {
                when {
                    "sql" in record -> connection.prepare(record.getValue("sql").jsonPrimitive.content).use { it.step() }
                    "table" in record -> {
                        val row = record.getValue("row").jsonObject
                        val names = row.keys.toList()
                        connection.prepare(insert(record.getValue("table").jsonPrimitive.content, names)).use { st ->
                            names.forEachIndexed { i, n -> bind(st, i + 1, value(row.getValue(n))) }
                            st.step()
                        }
                    }
                    "kv" in record -> connection.prepare(
                        "INSERT INTO kv (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                    ).use {
                        it.bindText(1, record.getValue("kv").jsonPrimitive.content)
                        it.bindText(2, record.getValue("value").jsonPrimitive.content)
                        it.step()
                    }
                    else -> error("a raw fixture holds statements, rows and kv: $record")
                }
            }
            connection.execSQL("COMMIT")
        } finally {
            connection.close()
        }
    }

    private fun quoted(name: String) = "\"" + name.replace("\"", "\"\"") + "\""

    private fun insert(table: String, names: List<String>) =
        "INSERT INTO ${quoted(table)} (${names.joinToString { quoted(it) }}) VALUES (${names.joinToString { "?" }})"

    /** A JSON value as SQLite holds it: text, an integer, a real, or NULL. */
    private fun value(element: JsonElement): Any? = when {
        element is JsonNull -> null
        element is JsonPrimitive && element.isString -> element.content
        element is JsonPrimitive -> element.content.toLongOrNull() ?: element.content.toDouble()
        else -> error("a fixture's column holds no ${element::class.simpleName}")
    }

    private fun bind(st: SQLiteStatement, at: Int, value: Any?) = when (value) {
        null -> st.bindNull(at)
        is Long -> st.bindLong(at, value)
        is Double -> st.bindDouble(at, value)
        else -> st.bindText(at, value.toString())
    }

    private fun write(record: JsonObject, libraryDir: File) {
        val name = record.getValue("file").jsonPrimitive.content
        require(name.split('/').none { it.isEmpty() || it == "." || it == ".." }) { "not a path in the library: $name" }
        val file = File(libraryDir, name)
        file.parentFile.mkdirs()
        file.writeBytes(Base64.getDecoder().decode(record.getValue("base64").jsonPrimitive.content))
    }
}
