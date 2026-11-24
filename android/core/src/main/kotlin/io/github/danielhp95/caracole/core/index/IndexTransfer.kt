package io.github.danielhp95.caracole.core.index

import io.github.danielhp95.caracole.core.db.Database
import io.github.danielhp95.caracole.core.db.Db
import io.github.danielhp95.caracole.core.db.Warmup
import io.github.danielhp95.caracole.core.db.isSqliteError
import io.github.danielhp95.caracole.core.json.Canonical
import io.github.danielhp95.caracole.core.json.CanonicalError
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import java.io.File

/**
 * index_transfer.py's merge on the phone: a `caracole index export` file into the database, taking what the file read
 * more recently, site by site, exactly as `caracole index merge` takes it (tests/conformance/vectors/index/merge.jsonl:
 * the database after equals Python's, its kv text byte for byte).
 *
 * **A merge** attaches the file as `theirs`, read as anyone's (index_transfer._attached: `trusted_schema` off while
 * it is attached, so that no function its schema names runs), and refuses it, writing nothing ([TransferError]),
 * unless it holds tables alone (no view, trigger, index of its own or virtual table: index_transfer._meta's check,
 * made before any of its tables is read), its META table (`caracole_export`) says format [FORMAT] and schema
 * [Database.SCHEMA_VERSION], it holds each site asked for, and kv and every table it merges have the database's
 * columns (PRAGMA table_info, in order). Then it plans each site, the two
 * databases' records compared (stamps.parse's times: [Stamps]):
 *
 * - a sitemap (UG's `ug:sitemaps` by `indexed_at`, a site_index.py site's `<provider>:sitemaps` by `checked_at`) or a
 *   listing page of LaCuerda's (`lacuerda:index:pages`) the file read later, or the database never read, replaces its
 *   rows and its record: UG's rows upserted as a refresh stores them (a row the database has keeps its sitemap and
 *   first sighting), the songs its new tabs are for marked to fetch again ([NewTabs]); the others' deleted and
 *   inserted;
 * - a page the file read later by its `read_at` (harptabs.com's artist pages, gametabs.net's game pages), or one the
 *   database never read, replaces its tabs and its row; UG's artist pages' tabs a row at a time, where the file's read
 *   is later, then filed again (ArtistTabs.refile);
 * - with no time to tell (an artist page of LaCuerda's; the songs its search answered), only what the database lacks;
 * - UG's artist directory (`ug_directory`) a row at a time: the listing's columns of a row the file saw later
 *   (`seen_at`), or one the database lacks; the read's of a page it read later (`read_at`); never a row removed;
 * - a progress record moves on, never back: `complete_at` and UG's refresh to the later time, UG's index built once
 *   the file's was, the listing of UG's sitemaps the later refresh's, a directory listing's round where the file's got
 *   further (its last whole read, its start, its next page).
 *
 * When nothing changes, nothing is written and [merge]'s `backup` is never called; else it is called once, before
 * the first change; once UG's sitemaps' rows changed by many (an import: Warmup.optimizes), UG's full-text indexes
 * are made one segment each as the merge ends (Warmup.optimize), for the searches after it. Each site is one savepoint: its actions, its kv records, then its
 * keys made current (ensure_current_keys, whole where the file's keys record differs from the database's, which is let
 * go first). A
 * record rewritten whole is written as Python's `json.dumps` of `json.loads`'s reading writes it (Merge.pyLoaded).
 *
 * Runs on the writer, inside Database.write, in no transaction (ATTACH and DETACH run in none).
 */
object IndexTransfer {
    const val FORMAT = "1"

    /** The export's own table of what it is (index_transfer.META). */
    const val META = "caracole_export"

    /** The sites a merge knows, by name, in caracole's order (index_transfer.SITES' names). */
    val SITES: List<String> get() = Sites.ALL.map { it.name }

    /**
     * The export's sites into [db] (every one it holds, with none asked for; else those of [sites], in caracole's
     * order), [now] (a stamp) the time a song marked to fetch again is updated at, [backup] called once before the
     * first change. Called inside Database.write, in no transaction or savepoint of the caller's: else an
     * IllegalStateException, nothing written (a [TransferError] is the file's alone). UG's full-text indexes are made
     * one segment each once its sitemaps' rows changed by [optimizeAfter] rows or more, the triggers' included
     * (Warmup.optimizes: an import, never a sync's nightly few); Long.MAX_VALUE never. With [notAfter] (a time as
     * Stamps.parse gives one), a record or page the file says it read after it is never newer than the database's,
     * so that a file dated in the future can't take a site's rows for good (the phone's sync passes its clock; Python's
     * merge has no such bound, and the replays none). UG's sitemaps' rows are taken [chunk] a statement ([UG_CHUNK]),
     * in the same savepoint and order as one statement took them (the database after is the same), so that
     * [progress] is told how far it has got as it goes ([MergeProgress]), on the caller's thread, inside its write.
     */
    fun merge(db: Db, export: File, now: String, sites: List<String>? = null,
              optimizeAfter: Long = Warmup.OPTIMIZE_AFTER, notAfter: Long? = null, chunk: Int = UG_CHUNK,
              progress: ((MergeProgress) -> Unit)? = null, backup: (() -> Unit)? = null): Merged {
        require(chunk > 0) { "a chunk of UG's rows holds one row at least, not $chunk" }
        // A caller's mistake, never the file's: SQLite attaches no database within a transaction.
        check(!db.raw.inTransaction()) { "an index merge runs in no transaction (ATTACH runs in none)" }
        check(Merge.THEIRS !in attached(db)) { "a database is attached as ${Merge.THEIRS} already" }
        if (!export.exists()) throw TransferError("$export: no such file")
        if (sameFile(export, mainFile(db))) throw TransferError("$export is the database itself")
        // The file may be anyone's (another phone's .caracole, a catalogue someone else published): no function its
        // schema names runs while it is attached (index_transfer._attached), and the connection as it was after.
        val trusted = db.one("PRAGMA trusted_schema") { it.long(0)!! }!!
        db.execute("PRAGMA trusted_schema = OFF")
        try {
            return mergeAttached(db, export, now, sites, optimizeAfter, notAfter, chunk, progress, backup)
        } finally {
            db.execute("PRAGMA trusted_schema = ${if (trusted != 0L) "ON" else "OFF"}")
        }
    }

    /** [merge] with the file read as anyone's: attached as [Merge.THEIRS], refused unless it is an export of this
     * layout and schema, then planned and applied. */
    private fun mergeAttached(db: Db, export: File, now: String, sites: List<String>?, optimizeAfter: Long,
                              notAfter: Long?, chunk: Int, progress: ((MergeProgress) -> Unit)?,
                              backup: (() -> Unit)?): Merged {
        try {
            db.attach(export, Merge.THEIRS)
        } catch (e: Exception) {
            if (!e.isSqliteError()) throw e
            throw noExport(export, e)
        }
        try {
            tablesAlone(db, export)
            val meta = meta(db, export)
            val names = mergedSites(export, meta, sites)
            Merge.checkColumns(db, export, names)
            progress?.invoke(MergeProgress("", MergeProgress.PLAN, 0, names.size.toLong()))
            val plans = names.map { Merge.plan(db, it, now, notAfter, chunk) }
            if (plans.none { it.changes }) {
                return Merged(names.associateWithTo(LinkedHashMap()) { emptyMap<String, Int>() }, false)
            }
            backup?.invoke()
            val taken = LinkedHashMap<String, Map<String, Int>>()
            var ugChanges = 0L
            for (plan in plans) {
                val before = Warmup.changes(db)
                taken[plan.site] = Merge.apply(db, plan, progress)
                if (plan.site == "ug") ugChanges = Warmup.changes(db) - before
            }
            if (Warmup.optimizes(taken["ug"], ugChanges, optimizeAfter)) {
                progress?.invoke(MergeProgress("ug", MergeProgress.OPTIMIZE, 0, 0))
                Warmup.optimize(db)  // one segment each (prep-db)
            }
            return Merged(taken, true)
        } finally {
            db.detach(Merge.THEIRS)
        }
    }

    /** How many of UG's sitemaps' rows each statement of a merge takes (index_transfer.py's chunk alike): each chunk
     * a range of `tab_id`s, in `tab_id` order, as the one statement it replaces read them. */
    const val UG_CHUNK = 50_000

    /**
     * The kv records a fresh caracole database holds once each site's index made its keys current on its empty tables
     * (caracole/schema/fresh_kv.json, `{"kv": {key: value}}`), each where the database holds none: so that a new
     * phone's first merge of an export finds the keys records the export holds, and re-keys nothing. Called inside
     * Database.write, once the database is made.
     */
    fun seedFresh(db: Db) {
        val records = Json.parseToJsonElement(Database.resource(FRESH_KV)).jsonObject.getValue("kv").jsonObject
        db.savepoint("seed_fresh") {
            for ((key, value) in records) {
                db.execute("INSERT INTO kv (key, value) VALUES (?, ?) ON CONFLICT(key) DO NOTHING",
                           key, value.jsonPrimitive.content)
            }
        }
    }

    /**
     * index_transfer.newest: each site's newest read, in caracole's order (the latest of the times a merge compares:
     * its sitemaps' or listing pages' records, the read of each page of its that has one, its progress records), as
     * stored ("2026-10-28T03:30:00Z"); a site with none is left out. The state document's `indexes`.
     */
    fun newest(db: Db): Map<String, String> {
        fun recorded(key: String, stamp: String) =
            Merge.records(db, "main", key).values.filterIsInstance<JsonObject>().map { it[stamp].text() }
        fun readAt(table: String) = db.query("SELECT DISTINCT read_at, typeof(read_at) FROM main.$table") {
            if (it.text(1) == "text") it.text(0) else null
        }
        fun kv(key: String) = Merge.kv(db, "main", key)
        // The directory's latest listing seen and page read: SQLite's MAX of each, a text alone (Python's isinstance).
        val directory = db.one(
            "SELECT MAX(seen_at), typeof(MAX(seen_at)), MAX(read_at), typeof(MAX(read_at)) FROM main.ug_directory",
        ) { listOf(if (it.text(1) == "text") it.text(0) else null, if (it.text(3) == "text") it.text(2) else null) }
            .orEmpty()
        fun siteIndex(provider: String) =
            recorded(Merge.sitemapsKey(provider), "checked_at") + kv(Merge.completeKey(provider))

        val times: Map<String, List<String?>> = linkedMapOf(
            "ug" to recorded(Merge.UG_SITEMAPS, "indexed_at") + readAt("ug_artist_tabs") +
                listOf(kv(Merge.UG_REFRESHED), kv(Merge.UG_BUILT)) + directory +
                recorded(Merge.UG_DIR_LETTERS, "done") + recorded(Merge.UG_DIR_LETTERS, "started"),
            "lacuerda" to recorded(Merge.LC_PAGES, "checked_at") + kv(Merge.LC_COMPLETE),
            "gtptabs" to siteIndex("gtptabs"),
            "musescore" to siteIndex("musescore"),
            "harptabs" to siteIndex("harptabs") + readAt("harptabs_artists"),
            "gametabs" to siteIndex("gametabs") + readAt("gametabs_games"),
        )
        val found = LinkedHashMap<String, String>()
        for (site in Sites.ALL) {
            val latest = times.getValue(site.name).mapNotNull { Stamps.parse(it) }.maxOrNull() ?: continue
            found[site.name] = Stamps.stamp(latest)
        }
        return found
    }

    private const val FRESH_KV = "caracole/schema/fresh_kv.json"

    /** A record's value that is a JSON string, else none (Python's `isinstance(t, str)`). */
    private fun JsonElement?.text(): String? =
        (this as? JsonPrimitive)?.takeIf { it.isString }?.content

    private fun mainFile(db: Db): File? = db.query("PRAGMA database_list") { it.text(1) to it.text(2) }
        .firstOrNull { it.first == "main" && !it.second.isNullOrEmpty() }?.second?.let(::File)

    private fun attached(db: Db): List<String> = db.query("PRAGMA database_list") { it.text(1)!! }

    private fun sameFile(a: File, b: File?): Boolean = b != null && try {
        a.canonicalFile == b.canonicalFile
    } catch (_: java.io.IOException) {
        false
    }

    /**
     * _meta's first check: a file of tables alone, as an export makes it (no view, trigger, index of its own or virtual
     * table, whose reading could run what its maker wrote, or never end: a view of a recursive query), read in its
     * `sqlite_master` before any of its tables is; the one it holds first refused in Python's words.
     */
    private fun tablesAlone(db: Db, export: File) {
        val odd = try {
            db.one(
                "SELECT type, name FROM ${Merge.THEIRS}.sqlite_master WHERE NOT (type = 'table' AND sql LIKE " +
                    "'CREATE TABLE %') AND NOT (type = 'index' AND sql IS NULL) ORDER BY rowid",
            ) { it.text(0) to it.text(1) }
        } catch (e: Exception) {
            if (!e.isSqliteError()) throw e
            throw noExport(export, e)
        }
        if (odd != null) {
            throw TransferError("$export holds the ${odd.first} ${odd.second}, and an index export of caracole's holds " +
                                    "tables alone: `caracole index export` makes one")
        }
    }

    /** _meta: the export's META, refused unless it is an export of this layout and schema. */
    private fun meta(db: Db, export: File): Map<String, String?> {
        val meta = try {
            db.query("SELECT key, value, typeof(value) FROM ${Merge.THEIRS}.$META") {
                it.text(0)!! to (if (it.text(2) == "text") it.text(1) else null)
            }.toMap()
        } catch (e: Exception) {
            if (!e.isSqliteError()) throw e
            throw noExport(export, e)
        }
        if (meta["format"] != FORMAT) {
            throw TransferError("$export is an index export of another layout (${repr(meta["format"])}, this " +
                                    "caracole's is $FORMAT): export it again with this caracole")
        }
        val schema = Database.SCHEMA_VERSION.toString()
        if (meta["schema"] != schema) {
            throw TransferError("$export was exported at schema version ${meta["schema"]}, and this caracole's " +
                                    "database is at $schema: merge it with a caracole of the same version (export it " +
                                    "again with this one, or bring both to the same caracole); nothing changed")
        }
        return meta
    }

    private fun repr(value: String?): String = if (value == null) "None" else "'$value'"

    private fun noExport(export: File, e: Exception) =
        TransferError("$export is no index export of caracole's (${e.message}): `caracole index export` makes one")

    /** _merged_sites: the sites the file holds (META's `sites`), and of them those asked for. */
    private fun mergedSites(export: File, meta: Map<String, String?>, sites: List<String>?): List<String> {
        val listed = meta["sites"] ?: "[]"
        val held = try {
            (Canonical.parse(listed) as? JsonArray).orEmpty()
                .mapNotNull { (it as? JsonPrimitive)?.takeIf { p -> p.isString }?.content }
                .filter { Sites.named(it) != null }
        } catch (_: CanonicalError) {
            emptyList()
        }
        val names = chosen(sites, if (held.isNotEmpty()) chosen(held, null) else emptyList())
        for (name in names) {
            if (name !in held) {
                throw TransferError("$export holds no $name index; it holds ${held.joinToString().ifEmpty { "none" }}")
            }
        }
        return names
    }

    /** index_transfer.chosen: the sites [names] names, in caracole's order (every one of [among], else of every site,
     * with none). */
    private fun chosen(names: List<String>?, among: List<String>?): List<String> {
        val known = among ?: Sites.ALL.map { it.name }
        if (names.isNullOrEmpty()) return known
        val wanted = LinkedHashSet(names)
        val unknown = wanted.firstOrNull { Sites.named(it) == null }
        if (unknown != null) {
            throw TransferError("no site '$unknown': the indexes are ${Sites.ALL.joinToString { it.name }}")
        }
        return Sites.ALL.map { it.name }.filter { it in wanted }
    }
}

/** What a merge took: per site merged (in caracole's order), each kind of page it took and how many (index_transfer's
 * `SiteMerge.taken`: "sitemap", "tab of its artist pages", "listing page"…), and whether anything changed (a page
 * taken or a progress record moved on). */
data class Merged(val sites: Map<String, Map<String, Int>>, val changed: Boolean)

/**
 * How far a merge has got (IndexTransfer.merge's `progress`, index_transfer.merge's `progress(site, action, done,
 * total)` alike), told on the writer's thread as the merge goes:
 *
 * - `("", [PLAN], 0, n)`: before the [n] sites asked are planned (both databases read: what the file read later);
 * - `(site, "", 0, n)`: before a site that changes anything is applied, [n] its actions (0: its records alone);
 * - `(site, action, 0, count)`: before each action, named as Merged names it ("sitemap", "artist page"…), [total]
 *   its count;
 * - but UG's sitemaps, counted by their rows: `("ug", "sitemap", 0, rows)` before, then `("ug", "sitemap", done,
 *   rows)` after each chunk of [IndexTransfer.UG_CHUNK] rows;
 * - `("ug", [OPTIMIZE], 0, 0)`: once UG's rows are in, before its full-text indexes are made one segment each (the
 *   phone's alone: Warmup.optimize).
 *
 * A merge of nothing newer tells the plan alone.
 */
data class MergeProgress(val site: String, val action: String, val done: Long, val total: Long) {
    companion object {
        const val PLAN = "plan"
        const val OPTIMIZE = "optimize"
    }
}

/** An export or a merge refused, nothing written: its words say why. */
class TransferError(message: String) : Exception(message)
