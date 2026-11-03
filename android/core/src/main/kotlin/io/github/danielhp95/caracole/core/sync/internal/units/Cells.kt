package io.github.danielhp95.caracole.core.sync.internal.units

import androidx.sqlite.SQLITE_DATA_FLOAT
import androidx.sqlite.SQLITE_DATA_INTEGER
import androidx.sqlite.SQLITE_DATA_NULL
import androidx.sqlite.SQLITE_DATA_TEXT
import androidx.sqlite.SQLiteStatement
import io.github.danielhp95.caracole.core.db.Db
import io.github.danielhp95.caracole.core.json.PyJson
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonPrimitive

/**
 * A query's rows as Python's sqlite3 reads them into a document: each cell by the type SQLite holds it in (an
 * integer, a float written as Python's repr, a text, or null), never by the column's declared type, so a song's
 * `match_score` is a float and its `review` an integer exactly where Python's are.
 */
internal object Cells {
    /** Each row of [sql], its cells by column name, in the columns' order. */
    fun rows(db: Db, sql: String, vararg args: Any?): List<LinkedHashMap<String, JsonElement>> =
        db.raw.prepare(sql).use { st ->
            args.forEachIndexed { i, arg -> bind(st, i + 1, arg) }
            val names = (0 until st.getColumnCount()).map { st.getColumnName(it) }
            val out = ArrayList<LinkedHashMap<String, JsonElement>>()
            while (st.step()) {
                val row = LinkedHashMap<String, JsonElement>()
                names.forEachIndexed { i, name -> row[name] = cell(st, i) }
                out.add(row)
            }
            out
        }

    /** The one row of [sql], or null for none. */
    fun row(db: Db, sql: String, vararg args: Any?): LinkedHashMap<String, JsonElement>? =
        rows(db, sql, *args).firstOrNull()

    private fun cell(st: SQLiteStatement, i: Int): JsonElement = when (st.getColumnType(i)) {
        SQLITE_DATA_NULL -> JsonNull
        SQLITE_DATA_INTEGER -> JsonPrimitive(st.getLong(i))
        SQLITE_DATA_FLOAT -> PyJson.float(st.getDouble(i))
        SQLITE_DATA_TEXT -> JsonPrimitive(st.getText(i))
        // json.dumps refuses the bytes a BLOB reads as; no column a unit carries holds one.
        else -> throw IllegalStateException("column ${st.getColumnName(i)} holds a blob, which no document carries")
    }

    private fun bind(st: SQLiteStatement, at: Int, arg: Any?) {
        when (arg) {
            null -> st.bindNull(at)
            is Long -> st.bindLong(at, arg)
            is Int -> st.bindLong(at, arg.toLong())
            is String -> st.bindText(at, arg)
            else -> throw IllegalArgumentException("can't bind a ${arg::class.simpleName}")
        }
    }

    /** A cell's text, or null for any other cell. */
    fun text(cell: JsonElement?): String? = (cell as? JsonPrimitive)?.takeIf { it.isString }?.content
}
