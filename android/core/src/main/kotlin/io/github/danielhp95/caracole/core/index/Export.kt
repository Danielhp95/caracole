package io.github.danielhp95.caracole.core.index

import androidx.sqlite.SQLiteException
import io.github.danielhp95.caracole.core.db.Database
import io.github.danielhp95.caracole.core.db.Db
import io.github.danielhp95.caracole.core.json.PyJson
import io.github.danielhp95.caracole.core.keys.Normalize
import io.github.danielhp95.caracole.core.sync.SyncEngine
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonPrimitive
import java.io.File
import java.io.IOException
import java.nio.file.Files

/** index_transfer.Exported: the file made, its sites, each table's rows and its size. */
data class Exported(val path: File, val sites: List<String>, val rows: Map<String, Int>, val size: Long)

/**
 * index_transfer.export(pages=) on the phone: the pages its lookups read ([Reads] noted them), as an index export the
 * computer merges (`POST /peer/index`, `caracole index merge --delete --progress`), its tables row for row and its
 * META as Python's export of the same pages (tests/conformance/vectors/index/export.jsonl).
 *
 * Each site the pages name gets every table of its index, made as the database has it (its `CREATE` text from
 * `sqlite_master`), but holding only the rows of those pages, by the column that names a page ([PAGES]: UG's artist
 * pages' tabs, LaCuerda's artist pages and its search's rows, `busca.php`, harptabs.com's artist pages and their
 * tabs, gametabs.net's game pages and theirs), each table's in the database's rowid order; and its kv only the
 * records of how those rows are keyed, which a merge compares, by key: never a sitemap's or a listing page's record,
 * nor how far an index has got, whose rows such a file never holds. A site whose index has no page a lookup reads
 * (gtptabs.com's, MuseScore's) is a [TransferError], as an unknown site is; no page at all, an export of no site.
 *
 * The file is made under a name of its own beside [export]'s `to` (`<name>.<12 hex>.part`), attached to the writer
 * as `exported` and filled in one savepoint, so that every table is of one snapshot; then renamed. A file there
 * already, the database itself, or a folder that isn't one, is refused before anything is written. Runs on the writer,
 * inside Database.write, in no transaction (ATTACH runs in none).
 */
object IndexExport {
    /** index_transfer.PAGES: each site's tables a lookup reads a page into, by the column naming the page, and the kv
     * records of how their rows are keyed. */
    internal class Pages(val tables: List<Pair<String, String>>, val kv: List<String>)

    internal val PAGES: Map<String, Pages> = linkedMapOf(
        "ug" to Pages(listOf("ug_artist_tabs" to "page"), listOf(Merge.UG_TAB_KEYS)),
        "lacuerda" to Pages(listOf("lacuerda_index" to "page"), listOf(Merge.LC_KEYS)),
        "harptabs" to Pages(listOf("harptabs_artists" to "path", "harptabs_artist_tabs" to "artist"),
                            listOf(Merge.HARP_SONG_KEYS)),
        "gametabs" to Pages(listOf("gametabs_games" to "path", "gametabs_game_tabs" to "page"),
                            listOf(Merge.GAME_TITLE_KEYS)),
    )

    private const val EXPORTED = "exported"

    /**
     * The pages of [pages] (`{site: [page, …]}`, Reads.since's) into a new index export at [to]: its sites in
     * caracole's order, each table's rows. [now], a stamp, is META's `exported_at`; [caracole] its `caracole`, the
     * version of the caracole that made it. A [TransferError] for a site with no pages or none caracole knows, a file
     * at [to] already, the database itself, or no folder to write in; nothing is left behind.
     */
    fun export(db: Db, to: File, pages: Map<String, List<String>>, now: String = Stamps.stamp(System.currentTimeMillis() * 1000L),
               caracole: String = SyncEngine.CARACOLE): Exported {
        check(!db.raw.inTransaction()) { "an index export runs in no transaction (ATTACH runs in none)" }
        val names = chosen(pages.keys.toList())
        names.firstOrNull { it !in PAGES }?.let {
            throw TransferError("${Sites.named(it)!!.title}'s index has no pages a lookup reads, its sitemaps alone: " +
                                    "pages are of ${PAGES.keys.joinToString()}")
        }
        if (sameFile(to, mainFile(db))) throw TransferError("$to is the database itself: name a new file")
        if (to.exists() || Files.isSymbolicLink(to.toPath())) {
            throw TransferError("$to already exists: name a new file, or remove that one first")
        }
        val folder = to.absoluteFile.parentFile
        if (folder == null || !folder.isDirectory) throw TransferError("${to.parentFile ?: "."} is no folder: name a file in one")
        val part = File(folder, "${to.name}.${Database.token()}.part")
        val sites = names.map { Sites.named(it)!! }
        val tables = sites.flatMap { it.tables }
        val named = HashMap<String, Pair<String, List<String>>>()
        for (name in names) {
            for ((table, column) in PAGES.getValue(name).tables) named[table] = column to pages.getValue(name).distinct()
        }
        val keys = names.flatMap { PAGES.getValue(it).kv }
        try {
            val rows = write(db, part, names, tables, named, keys, now, caracole)
            Database.replace(part, to)
            return Exported(to, names, rows, to.length())
        } catch (e: IOException) {
            throw TransferError("can't write $to: ${e.message}")
        } catch (e: SQLiteException) {
            throw TransferError("can't write $to: ${e.message}")
        } finally {
            part.delete()
            File(part.path + "-journal").delete()
        }
    }

    /** _write_export with pages: the tables made, then filled, in one savepoint on the database's writer; each table's
     * rows counted. */
    private fun write(db: Db, part: File, names: List<String>, tables: List<String>,
                      named: Map<String, Pair<String, List<String>>>, keys: List<String>, now: String,
                      caracole: String): Map<String, Int> {
        db.attach(part, EXPORTED)
        try {
            return db.savepoint("index_export") {
                for (table in tables) {
                    val sql = db.one("SELECT sql FROM main.sqlite_master WHERE type = 'table' AND name = ?", table) {
                        it.text(0)
                    } ?: throw TransferError("the database has no table $table")
                    db.execute(qualified(sql, table))
                }
                db.execute("CREATE TABLE $EXPORTED.kv (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
                db.execute("CREATE TABLE $EXPORTED.${IndexTransfer.META} (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
                val meta = listOf(
                    "format" to IndexTransfer.FORMAT, "schema" to Database.SCHEMA_VERSION.toString(),
                    "keys" to Normalize.KEY_VERSION.toString(), "caracole" to caracole, "exported_at" to now,
                    "sites" to PyJson.dumps(JsonArray(names.map(::JsonPrimitive))), "source" to (mainFile(db)?.path ?: ""),
                )
                for ((key, value) in meta) {
                    db.execute("INSERT INTO $EXPORTED.${IndexTransfer.META} (key, value) VALUES (?, ?)", key, value)
                }
                for (table in tables) {
                    val (column, pages) = named[table] ?: continue
                    val cols = Merge.columns(db, "main", table).joinToString(", ")
                    db.execute("INSERT INTO $EXPORTED.$table ($cols) SELECT $cols FROM main.$table WHERE $column IN " +
                                   "(SELECT value FROM json_each(?)) ORDER BY rowid",
                               PyJson.dumps(JsonArray(pages.map(::JsonPrimitive))))
                }
                db.execute("INSERT INTO $EXPORTED.kv (key, value) SELECT key, value FROM main.kv WHERE key IN " +
                               "(${keys.joinToString(", ") { "?" }}) ORDER BY key", *keys.toTypedArray())
                tables.associateWithTo(LinkedHashMap()) { table ->
                    db.one("SELECT COUNT(*) FROM $EXPORTED.$table") { it.long(0)!!.toInt() }!!
                }
            }
        } finally {
            db.detach(EXPORTED)
        }
    }

    /** A table's `CREATE TABLE <name> …` text (sqlite_master's, its schema qualifier removed) made in the export:
     * `CREATE TABLE exported.<name> …`, which SQLite stores as the database's own text. */
    private fun qualified(sql: String, table: String): String {
        val head = "CREATE TABLE $table"
        require(sql.startsWith(head) && sql.getOrNull(head.length)?.let { it == ' ' || it == '(' } == true) {
            "not a plain CREATE TABLE of $table: ${sql.take(80)}"
        }
        return "CREATE TABLE $EXPORTED.$table" + sql.substring(head.length)
    }

    /** index_transfer.chosen: the sites [names] names, in caracole's order; a TransferError for one it has no index of. */
    private fun chosen(names: List<String>): List<String> {
        names.firstOrNull { Sites.named(it) == null }?.let {
            throw TransferError("no site '$it': the indexes are ${Sites.ALL.joinToString { s -> s.name }}")
        }
        return Sites.ALL.map { it.name }.filter { it in names }
    }

    private fun mainFile(db: Db): File? = db.query("PRAGMA database_list") { it.text(1) to it.text(2) }
        .firstOrNull { it.first == "main" && !it.second.isNullOrEmpty() }?.second?.let(::File)

    private fun sameFile(a: File, b: File?): Boolean = b != null && try {
        a.canonicalFile == b.canonicalFile
    } catch (_: IOException) {
        false
    }
}
