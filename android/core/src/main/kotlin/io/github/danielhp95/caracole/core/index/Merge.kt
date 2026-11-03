package io.github.danielhp95.caracole.core.index

import io.github.danielhp95.caracole.core.db.Db
import io.github.danielhp95.caracole.core.json.Canonical
import io.github.danielhp95.caracole.core.json.CanonicalError
import io.github.danielhp95.caracole.core.json.PyJson
import io.github.danielhp95.caracole.core.lacuerda.LaCuerda
import io.github.danielhp95.caracole.core.sites.SiteKeys
import io.github.danielhp95.caracole.core.ug.ArtistTabs
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import java.io.File
import java.math.BigInteger

/**
 * index_transfer.py's deciding and applying, site by site: [plan] reads both databases and decides what the file read
 * more recently (each action a noun, how many, and what does it; the kv records set, or let go to be made again
 * whole), [apply] does it in one savepoint, then makes the site's keys current. The export is attached as [THEIRS].
 */
internal object Merge {
    const val THEIRS = "theirs"
    private const val TAKEN = "temp._merge_taken"

    // The kv records of each site's progress (index_transfer.SITES' kv), as Python names them.
    const val UG_SITEMAPS = "ug:sitemaps"
    const val UG_LISTED = "ug:index:listed"
    const val UG_BUILT = "ug:index:built_at"
    const val UG_REFRESHED = "ug:index:refreshed_at"
    const val UG_TAB_KEYS = "ug:artist_tabs:keys"
    const val LC_PAGES = "lacuerda:index:pages"
    const val LC_COMPLETE = "lacuerda:index:complete_at"
    const val LC_KEYS = "lacuerda:index:keys"
    const val HARP_ROW_KEYS = "harptabs:index:keys"
    const val HARP_SONG_KEYS = "harptabs:artists:keys"
    const val GAME_TITLE_KEYS = "gametabs:games:keys"

    /** lacuerda_index.SEARCH_PAGE: the page of the rows LaCuerda's search answered. */
    private const val LC_SEARCH_PAGE = "busca.php"

    fun sitemapsKey(provider: String) = "$provider:sitemaps"
    fun completeKey(provider: String) = "$provider:index:complete_at"

    /** _Plan: what a merge takes of a site. */
    class Plan(val site: String) {
        class Action(val noun: String, val count: Int, val run: (Db) -> Unit)

        val actions = ArrayList<Action>()
        val kv = LinkedHashMap<String, String?>()
        val records = ArrayList<String>()

        val changes: Boolean get() = actions.isNotEmpty() || kv.isNotEmpty()

        fun take(noun: String, count: Int, run: (Db) -> Unit) {
            if (count != 0) actions.add(Action(noun, count, run))
        }
    }

    // --- reading ---------------------------------------------------------------------------------------------------

    fun kv(db: Db, schema: String, key: String): String? =
        db.one("SELECT value FROM $schema.kv WHERE key = ?", key) { it.text(0) }

    /** _records: a kv record of records by name, as json.loads reads it; none for no object. */
    fun records(db: Db, schema: String, key: String): Map<String, JsonElement> {
        val value = kv(db, schema, key)
        if (value.isNullOrEmpty()) return emptyMap()
        val parsed = try {
            Canonical.parse(value)
        } catch (_: CanonicalError) {
            return emptyMap()
        }
        return parsed as? JsonObject ?: emptyMap()
    }

    fun columns(db: Db, schema: String, table: String): List<String> =
        db.query("PRAGMA $schema.table_info($table)") { it.text(1)!! }

    /** _check_columns: every table of the sites merged has the database's columns, in order. */
    fun checkColumns(db: Db, export: File, names: List<String>) {
        for (name in names) {
            for (table in Sites.named(name)!!.tables) {
                val mine = columns(db, "main", table)
                val theirs = columns(db, THEIRS, table)
                if (mine != theirs) {
                    val listed = theirs.joinToString().ifEmpty { "none" }
                    throw TransferError("$export's $table has the columns ($listed), and the database's " +
                                            "(${mine.joinToString()}): nothing changed")
                }
            }
        }
    }

    /** _newer: whether a time the file recorded is later than the database's; a time missing is earlier than any. */
    private fun newer(theirs: Long?, mine: Long?): Boolean = theirs != null && (mine == null || theirs > mine)

    private fun newer(theirs: String?, mine: String?): Boolean = newer(Stamps.parse(theirs), Stamps.parse(mine))

    private fun newer(theirs: JsonElement?, mine: JsonElement?): Boolean =
        newer(Stamps.parse(theirs), Stamps.parse(mine))

    private fun seen(entry: JsonElement?, stamp: String): JsonElement? = (entry as? JsonObject)?.get(stamp)

    /** _newer_records: the sitemaps (pages) of a record of them the file read later, or the database never read. */
    private fun newerRecords(db: Db, key: String, stamp: String): List<String> {
        val mine = records(db, "main", key)
        val theirs = records(db, THEIRS, key)
        return theirs.entries.filter { (name, entry) ->
            entry is JsonObject && (name !in mine || newer(seen(entry, stamp), seen(mine[name], stamp)))
        }.map { it.key }
    }

    // --- deciding --------------------------------------------------------------------------------------------------

    fun plan(db: Db, name: String, now: String): Plan {
        val plan = Plan(name)
        when (name) {
            "ug" -> planUg(db, plan, now)
            "lacuerda" -> planLacuerda(db, plan)
            "gtptabs", "musescore" -> sitemaps(db, plan, name, "${name}_index")
            "harptabs" -> planHarptabs(db, plan)
            "gametabs" -> planGametabs(db, plan)
            else -> error("no site $name")
        }
        return plan
    }

    /** _later: a time that moves on, never back: the file's, when later. */
    private fun later(db: Db, plan: Plan, key: String, what: String) {
        val theirs = kv(db, THEIRS, key)
        if (newer(theirs, kv(db, "main", key))) {
            plan.kv[key] = theirs
            plan.records.add(what)
        }
    }

    /** _keys_again: rows of the file's keyed by another normalizer than the database's: made again whole after. */
    private fun keysAgain(db: Db, plan: Plan, key: String) {
        if (plan.actions.isNotEmpty() && kv(db, THEIRS, key) != kv(db, "main", key)) plan.kv[key] = null
    }

    /** _sitemaps: a site_index.py site's sitemaps the file read later, and its `complete_at`. */
    private fun sitemaps(db: Db, plan: Plan, provider: String, table: String, noun: String = "sitemap") {
        val key = sitemapsKey(provider)
        val names = newerRecords(db, key, "checked_at")
        plan.take(noun, names.size) { c ->
            taken(c, names)
            replace(c, table, "sitemap")
            takeRecords(c, key, names)
        }
        later(db, plan, completeKey(provider), "${noun}s read whole")
    }

    /** _pages: the pages (path, read_at) the file read later, with their tabs (by [column]). */
    private fun pages(db: Db, plan: Plan, noun: String, pages: String, tabs: String, column: String) {
        val names = db.query(
            "SELECT t.path FROM $THEIRS.$pages t LEFT JOIN main.$pages m ON m.path = t.path " +
                "WHERE m.path IS NULL OR t.read_at > m.read_at ORDER BY t.path",
        ) { it.text(0)!! }
        plan.take(noun, names.size) { c ->
            taken(c, names)
            replace(c, tabs, column)
            replace(c, pages, "path")
        }
    }

    private fun planHarptabs(db: Db, plan: Plan) {
        sitemaps(db, plan, "harptabs", "harptabs_index")
        keysAgain(db, plan, HARP_ROW_KEYS)
        val sitemapActions = plan.actions.size
        pages(db, plan, "artist page", "harptabs_artists", "harptabs_artist_tabs", "artist")
        if (plan.actions.size > sitemapActions) keysAgain(db, plan, HARP_SONG_KEYS)
    }

    private fun planGametabs(db: Db, plan: Plan) {
        sitemaps(db, plan, "gametabs", "gametabs_index")
        val sitemapActions = plan.actions.size
        pages(db, plan, "game page", "gametabs_games", "gametabs_game_tabs", "page")
        if (plan.actions.size > sitemapActions) keysAgain(db, plan, GAME_TITLE_KEYS)
    }

    private fun planLacuerda(db: Db, plan: Plan) {
        val listings = newerRecords(db, LC_PAGES, "checked_at")
        plan.take("listing page", listings.size) { c ->
            taken(c, listings)
            replace(c, "lacuerda_index", "page")
            takeRecords(c, LC_PAGES, listings)
        }
        // An artist page's rows have no time of their own: the file's are taken where the database has none.
        val artists = db.query(
            "SELECT DISTINCT t.page FROM $THEIRS.lacuerda_index t WHERE t.page LIKE '%/' " +
                "AND t.page NOT LIKE 'tabs/%' " +
                "AND NOT EXISTS (SELECT 1 FROM main.lacuerda_index m WHERE m.page = t.page) ORDER BY t.page",
        ) { it.text(0)!! }
        plan.take("artist page", artists.size) { c ->
            taken(c, artists)
            replace(c, "lacuerda_index", "page")
        }
        val search = "FROM $THEIRS.lacuerda_index t WHERE t.page = ? AND NOT EXISTS " +
            "(SELECT 1 FROM main.lacuerda_index m WHERE m.path = t.path)"
        val found = db.one("SELECT COUNT(*) $search", LC_SEARCH_PAGE) { it.long(0)!! }!!.toInt()
        plan.take("row of its search's answers", found) { c ->
            val cols = columns(c, "main", "lacuerda_index").joinToString(", ") { "t.$it" }
            c.execute("INSERT OR IGNORE INTO main.lacuerda_index SELECT $cols $search", LC_SEARCH_PAGE)
        }
        keysAgain(db, plan, LC_KEYS)
        later(db, plan, LC_COMPLETE, "listings read whole")
    }

    private fun planUg(db: Db, plan: Plan, now: String) {
        val names = newerRecords(db, UG_SITEMAPS, "indexed_at")
        plan.take("sitemap", names.size) { c ->
            taken(c, names)
            val new = c.query(
                "SELECT t.tab_id FROM $THEIRS.ug_index t WHERE t.sitemap IN (SELECT name FROM $TAKEN) " +
                    "AND NOT EXISTS (SELECT 1 FROM main.ug_index m WHERE m.tab_id = t.tab_id) ORDER BY t.tab_id",
            ) { it.long(0)!! }
            // As a refresh stores a sitemap (ug/index.py upsert_rows): a row the database has keeps where and when it
            // was first seen, and takes the file's keys and path.
            c.execute(
                "INSERT INTO main.ug_index (tab_id, artist_key, song_key, type, sitemap, first_seen, path) " +
                    "SELECT tab_id, artist_key, song_key, type, sitemap, first_seen, path FROM $THEIRS.ug_index " +
                    "WHERE sitemap IN (SELECT name FROM $TAKEN) " +
                    "ON CONFLICT (tab_id) DO UPDATE SET artist_key = excluded.artist_key, " +
                    "song_key = excluded.song_key, " +
                    "type = excluded.type, path = excluded.path " +
                    "WHERE ug_index.artist_key != excluded.artist_key OR ug_index.song_key != excluded.song_key " +
                    "OR ug_index.type != excluded.type OR ug_index.path != excluded.path",
            )
            takeRecords(c, UG_SITEMAPS, names)
            NewTabs.markDirty(c, new, now)
        }
        val newer = "FROM $THEIRS.ug_artist_tabs t LEFT JOIN main.ug_artist_tabs m ON m.page = t.page AND " +
            "m.tab_id = t.tab_id WHERE m.page IS NULL OR t.read_at > m.read_at"
        val tabs = db.one("SELECT COUNT(*) $newer") { it.long(0)!! }!!.toInt()
        plan.take("tab of its artist pages", tabs) { c ->
            val pages = c.query("SELECT DISTINCT t.page $newer") { it.text(0)!! }
            val cols = columns(c, "main", "ug_artist_tabs")
            c.execute(
                "INSERT INTO main.ug_artist_tabs (${cols.joinToString(", ")}) SELECT ${cols.joinToString(", ")} FROM " +
                    "$THEIRS.ug_artist_tabs WHERE true ON CONFLICT (page, tab_id) DO UPDATE SET " +
                    cols.drop(2).joinToString(", ") { "$it = excluded.$it" } +
                    " WHERE excluded.read_at > ug_artist_tabs.read_at",
            )
            ArtistTabs.refile(c, pages)
        }
        if (tabs != 0) keysAgain(db, plan, UG_TAB_KEYS)
        // The index's state: refreshed at the later time, built once either was, and listed as the later read saw it.
        fun seen(schema: String) = listOfNotNull(Stamps.parse(kv(db, schema, UG_REFRESHED)),
                                                 Stamps.parse(kv(db, schema, UG_BUILT))).maxOrNull()
        val mineSeen = seen("main")
        val theirsSeen = seen(THEIRS)
        val listed = kv(db, THEIRS, UG_LISTED)
        if (listed != null && theirsSeen != null && (mineSeen == null || theirsSeen > mineSeen) &&
            listed != kv(db, "main", UG_LISTED)
        ) {
            plan.kv[UG_LISTED] = listed
            plan.records.add("the sitemaps UG lists")
        }
        later(db, plan, UG_REFRESHED, "its last refresh")
        val built = kv(db, THEIRS, UG_BUILT)
        if (built != null && kv(db, "main", UG_BUILT) == null) {
            plan.kv[UG_BUILT] = built
            plan.records.add("the index built whole")
        }
    }

    // --- applying --------------------------------------------------------------------------------------------------

    /** _apply: the plan's actions and kv records, then the site's keys made current, in one savepoint; what it
     * took. */
    fun apply(db: Db, plan: Plan): Map<String, Int> {
        db.savepoint("index_merge") {
            for (action in plan.actions) action.run(db)
            for ((key, value) in plan.kv) if (value == null) db.kvDelete(key) else db.kvSet(key, value)
            currentKeys(db, plan.site)
            db.execute("DROP TABLE IF EXISTS $TAKEN")
        }
        return plan.actions.associateTo(LinkedHashMap()) { it.noun to it.count }
    }

    /** _current_keys: each index's keys made current, as its next read would make them. */
    private fun currentKeys(db: Db, site: String) {
        when (site) {
            "ug" -> ArtistTabs.ensureCurrentKeys(db)
            "lacuerda" -> LaCuerda.ensureCurrentKeys(db)
            "harptabs" -> SiteKeys.harptabsEnsureCurrentKeys(db)
            "gametabs" -> SiteKeys.gametabsEnsureCurrentKeys(db)
        }
    }

    /** _taken: the names of the pages or sitemaps an action takes, in a temporary table its statements read. */
    private fun taken(db: Db, names: List<String>) {
        db.execute("CREATE TEMP TABLE IF NOT EXISTS _merge_taken (name TEXT PRIMARY KEY)")
        db.execute("DELETE FROM $TAKEN")
        for (chunk in names.chunked(TAKEN_CHUNK)) {
            val list = PyJson.dumps(JsonArray(chunk.map(::JsonPrimitive)))
            db.execute("INSERT OR IGNORE INTO $TAKEN (name) SELECT value FROM json_each(?)", list)
        }
    }

    private const val TAKEN_CHUNK = 10_000

    /** _replace: the database's rows of the pages taken (by [column]) in place of the file's. */
    private fun replace(db: Db, table: String, column: String) {
        val cols = columns(db, "main", table).joinToString(", ")
        db.execute("DELETE FROM main.$table WHERE $column IN (SELECT name FROM $TAKEN)")
        db.execute("INSERT OR REPLACE INTO main.$table ($cols) SELECT $cols FROM $THEIRS.$table " +
                       "WHERE $column IN (SELECT name FROM $TAKEN)")
    }

    /** _take_records: the file's records of the sitemaps (pages) taken, in place of the database's, the whole record
     * written as db.kv_set_json writes Python's reading of it. */
    private fun takeRecords(db: Db, key: String, names: List<String>) {
        val merged = LinkedHashMap(records(db, "main", key))
        val theirs = records(db, THEIRS, key)
        for (name in names) merged[name] = theirs.getValue(name)
        db.kvSetJson(key, pyLoaded(JsonObject(merged)))
    }

    /**
     * A value as json.loads gives it to json.dumps: each number as Python holds it, an integer its decimal (`-0` is
     * `0`), any other literal the float it reads as, written as Python's repr (`1.50` is `1.5`, `1E2` is `100.0`,
     * `1e400` is `Infinity`); objects in their order, a repeated key in its first place with its last value.
     */
    fun pyLoaded(value: JsonElement): JsonElement = when (value) {
        is JsonObject -> JsonObject(value.mapValuesTo(LinkedHashMap()) { pyLoaded(it.value) })
        is JsonArray -> JsonArray(value.map(::pyLoaded))
        is JsonNull -> value
        is JsonPrimitive -> when {
            value.isString || value.content == "true" || value.content == "false" -> value
            INTEGER.matches(value.content) -> JsonPrimitive(BigInteger(value.content))
            else -> PyJson.float(value.content.toDouble())
        }
    }

    private val INTEGER = Regex("-?[0-9]+")
}
