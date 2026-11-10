package io.github.danielhp95.caracole.core.sync.file

import io.github.danielhp95.caracole.core.db.Database
import io.github.danielhp95.caracole.core.db.Db
import io.github.danielhp95.caracole.core.index.IndexTransfer
import io.github.danielhp95.caracole.core.index.Merge
import io.github.danielhp95.caracole.core.index.Sites
import io.github.danielhp95.caracole.core.json.PyJson
import io.github.danielhp95.caracole.core.keys.Normalize
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonPrimitive
import java.io.File

/**
 * index_transfer.export of every site on the phone, for a `.caracole` file's `indexes.sqlite`: each site's tables
 * made as the database has them (their `CREATE` text from `sqlite_master`), every row copied, the kv records of each
 * site's progress (Sites' `kv`), and its META (`caracole_export`: format, schema, keys, caracole, exported_at, sites,
 * source), as `caracole index export` writes one, in one savepoint, so every table is of one snapshot. IndexExport
 * (index-push's) exports a lookup's pages alone; this, the whole of each index. Runs on the writer, inside
 * Database.write, in no transaction (ATTACH runs in none).
 */
internal object IndexFile {
    private const val EXPORTED = "exported"

    /** Every site's index into a new file at [to] (none there yet), stamped [now], made by caracole [caracole]: the
     * sites it holds, in caracole's order. */
    fun export(db: Db, to: File, now: String, caracole: String): List<String> {
        check(!db.raw.inTransaction()) { "an index export runs in no transaction (ATTACH runs in none)" }
        check(!to.exists()) { "$to already exists" }
        val sites = Sites.ALL
        val names = sites.map { it.name }
        val tables = sites.flatMap { it.tables }
        val keys = sites.flatMap { it.kv }
        db.attach(to, EXPORTED)
        try {
            db.savepoint("index_file") {
                for (table in tables) {
                    val sql = db.one("SELECT sql FROM main.sqlite_master WHERE type = 'table' AND name = ?", table) {
                        it.text(0)
                    } ?: throw FileError("its indexes can't be exported: the database has no table $table")
                    val head = "CREATE TABLE $table"
                    check(sql.startsWith(head) && sql.getOrNull(head.length)?.let { it == ' ' || it == '(' } == true) {
                        "not a plain CREATE TABLE of $table: ${sql.take(80)}"
                    }
                    db.execute("CREATE TABLE $EXPORTED.$table" + sql.substring(head.length))
                }
                db.execute("CREATE TABLE $EXPORTED.kv (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
                db.execute("CREATE TABLE $EXPORTED.${IndexTransfer.META} (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
                val source = db.query("PRAGMA database_list") { it.text(1) to it.text(2) }
                    .firstOrNull { it.first == "main" }?.second.orEmpty()
                for ((key, value) in listOf(
                    "format" to IndexTransfer.FORMAT, "schema" to Database.SCHEMA_VERSION.toString(),
                    "keys" to Normalize.KEY_VERSION.toString(), "caracole" to caracole, "exported_at" to now,
                    "sites" to PyJson.dumps(JsonArray(names.map(::JsonPrimitive))), "source" to source,
                )) {
                    db.execute("INSERT INTO $EXPORTED.${IndexTransfer.META} (key, value) VALUES (?, ?)", key, value)
                }
                for (table in tables) {
                    val cols = Merge.columns(db, "main", table).joinToString(", ")
                    db.execute("INSERT INTO $EXPORTED.$table ($cols) SELECT $cols FROM main.$table")
                }
                db.execute("INSERT INTO $EXPORTED.kv (key, value) SELECT key, value FROM main.kv WHERE key IN " +
                               "(${keys.joinToString(", ") { "?" }})", *keys.toTypedArray())
            }
        } finally {
            db.detach(EXPORTED)
        }
        return names
    }

    /** What an export of every index would be, in bytes (`GET /api/sync/sizes`' `indexes`): the pages their tables
     * fill (SQLite's dbstat); null where SQLite can't say. */
    fun size(db: Db): Long? = try {
        val tables = Sites.ALL.flatMap { it.tables }
        db.one("SELECT SUM(pgsize) FROM dbstat WHERE name IN (${tables.joinToString(", ") { "?" }})",
               *tables.toTypedArray()) { it.long(0) ?: 0L }
    } catch (e: Exception) {
        null
    }
}
