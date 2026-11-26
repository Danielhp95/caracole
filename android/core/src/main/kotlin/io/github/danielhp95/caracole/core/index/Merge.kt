package io.github.danielhp95.caracole.core.index

import io.github.danielhp95.caracole.core.db.Db
import io.github.danielhp95.caracole.core.json.Canonical
import io.github.danielhp95.caracole.core.json.CanonicalError
import io.github.danielhp95.caracole.core.json.PyJson
import io.github.danielhp95.caracole.core.lacuerda.LaCuerda
import io.github.danielhp95.caracole.core.py.Py
import io.github.danielhp95.caracole.core.sites.SiteKeys
import io.github.danielhp95.caracole.core.ug.ArtistTabs
import io.github.danielhp95.caracole.core.ug.UgDirectory
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
    const val UG_DIR_LETTERS = UgDirectory.LETTERS_KEY
    const val UG_DIR_KEYS = UgDirectory.KEYS_KEY
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

    /** _Plan: what a merge takes of a site; [chunk], how many of UG's sitemaps' rows a statement takes. */
    class Plan(val site: String, val notAfter: Long? = null, val chunk: Int = IndexTransfer.UG_CHUNK) {
        /** An action: what it takes and how many ([count], Merged's, which [apply] tells before it runs), and what
         * does it, told how far its rows have got ([run]'s second argument, rows done of rows: UG's sitemaps' chunks,
         * MergeProgress.TAB). */
        class Action(val noun: String, val count: Int, val run: (Db, (Long, Long) -> Unit) -> Unit)

        val actions = ArrayList<Action>()
        val kv = LinkedHashMap<String, String?>()

        /** _Plan.checked: the file's rows of the site's first table its actions took (Merged.checked), by the
         * statements' own counts, no table scanned for it: the rows of the sitemaps and listing pages taken, read new
         * or not; LaCuerda's artist pages' and search's rows, inserted where the phone had none (new by construction). */
        var checked = 0L

        val changes: Boolean get() = actions.isNotEmpty() || kv.isNotEmpty()

        fun take(noun: String, count: Int, run: (Db) -> Unit) {
            if (count != 0) actions.add(Action(noun, count) { db, _ -> run(db) })
        }

        /** An action that tells how far its rows have got, a chunk at a time. */
        fun takeInChunks(noun: String, count: Int, run: (Db, (Long, Long) -> Unit) -> Unit) {
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

    /** _check_columns: every table of the sites merged has the database's columns, in order, kv too (its records of
     * how far each index has got). */
    fun checkColumns(db: Db, export: File, names: List<String>) {
        for (name in names) {
            for (table in listOf("kv") + Sites.named(name)!!.tables) {
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

    /** _newer: whether a time the file recorded is later than the database's; a time missing is earlier than any.
     * On the phone, a time after the plan's [Plan.notAfter] (the merge's clock) is never newer: a file dated in the
     * future would otherwise replace a site's rows with its own for good, the phone reading no sitemap itself. */
    private fun Plan.newer(theirs: Long?, mine: Long?): Boolean =
        theirs != null && (notAfter == null || theirs <= notAfter) && (mine == null || theirs > mine)

    private fun Plan.newer(theirs: String?, mine: String?): Boolean = newer(Stamps.parse(theirs), Stamps.parse(mine))

    private fun Plan.newer(theirs: JsonElement?, mine: JsonElement?): Boolean =
        newer(Stamps.parse(theirs), Stamps.parse(mine))

    /** The SQL condition that a file's `t.read_at` is no later than [Plan.notAfter] (always, with none), and its
     * argument: stored times are ISO 8601 UTC to the second, compared as text as the merge compares them. */
    private fun Plan.readNoLater(): Pair<String, Array<Any?>> = noLater("t.read_at")

    /** The SQL condition that a file's [column] (a stored time) is no later than [Plan.notAfter] (always, with none),
     * and its argument. */
    private fun Plan.noLater(column: String): Pair<String, Array<Any?>> =
        if (notAfter == null) "" to emptyArray() else " AND $column <= ?" to arrayOf(Stamps.stamp(notAfter))

    private fun seen(entry: JsonElement?, stamp: String): JsonElement? = (entry as? JsonObject)?.get(stamp)

    /** _newer_records: the sitemaps (pages) of a record of them the file read later, or the database never read. */
    private fun Plan.newerRecords(db: Db, key: String, stamp: String): List<String> {
        val mine = records(db, "main", key)
        val theirs = records(db, THEIRS, key)
        return theirs.entries.filter { (name, entry) ->
            entry is JsonObject && (name !in mine || newer(seen(entry, stamp), seen(mine[name], stamp)))
        }.map { it.key }
    }

    // --- deciding --------------------------------------------------------------------------------------------------

    fun plan(db: Db, name: String, now: String, notAfter: Long? = null, chunk: Int = IndexTransfer.UG_CHUNK): Plan {
        val plan = Plan(name, notAfter, chunk)
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
    private fun later(db: Db, plan: Plan, key: String) {
        val theirs = kv(db, THEIRS, key)
        if (plan.newer(theirs, kv(db, "main", key))) plan.kv[key] = theirs
    }

    /** _keys_again: rows of the file's keyed by another normalizer than the database's: made again whole after. */
    private fun keysAgain(db: Db, plan: Plan, key: String) {
        if (plan.actions.isNotEmpty() && kv(db, THEIRS, key) != kv(db, "main", key)) plan.kv[key] = null
    }

    /** _sitemaps: a site_index.py site's sitemaps the file read later, and its `complete_at`. */
    private fun sitemaps(db: Db, plan: Plan, provider: String, table: String) {
        val key = sitemapsKey(provider)
        val names = plan.newerRecords(db, key, "checked_at")
        plan.take("sitemap", names.size) { c ->
            taken(c, names)
            plan.checked += replace(c, table, "sitemap")
            takeRecords(c, key, names)
        }
        later(db, plan, completeKey(provider))
    }

    /** _pages: the pages (path, read_at) the file read later, with their tabs (by [column]). */
    private fun pages(db: Db, plan: Plan, noun: String, pages: String, tabs: String, column: String) {
        val (noLater, args) = plan.readNoLater()
        val names = db.query(
            "SELECT t.path FROM $THEIRS.$pages t LEFT JOIN main.$pages m ON m.path = t.path " +
                "WHERE (m.path IS NULL OR t.read_at > m.read_at)$noLater ORDER BY t.path", *args,
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
        val listings = plan.newerRecords(db, LC_PAGES, "checked_at")
        plan.take("listing page", listings.size) { c ->
            taken(c, listings)
            plan.checked += replace(c, "lacuerda_index", "page")
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
            plan.checked += replace(c, "lacuerda_index", "page")
        }
        val search = "FROM $THEIRS.lacuerda_index t WHERE t.page = ? AND NOT EXISTS " +
            "(SELECT 1 FROM main.lacuerda_index m WHERE m.path = t.path)"
        val found = db.one("SELECT COUNT(*) $search", LC_SEARCH_PAGE) { it.long(0)!! }!!.toInt()
        plan.take("row of its search's answers", found) { c ->
            val cols = columns(c, "main", "lacuerda_index").joinToString(", ") { "t.$it" }
            plan.checked += c.execute("INSERT OR IGNORE INTO main.lacuerda_index SELECT $cols $search", LC_SEARCH_PAGE)
        }
        keysAgain(db, plan, LC_KEYS)
        later(db, plan, LC_COMPLETE)
    }

    private fun planUg(db: Db, plan: Plan, now: String) {
        val names = plan.newerRecords(db, UG_SITEMAPS, "indexed_at")
        plan.takeInChunks("sitemap", names.size) { c, said ->
            taken(c, names)
            // The tabs the database never had, kept for the songs they may be for (none on a new phone).
            val songs = NewTabs.songs(c)
            if (songs.isNotEmpty()) {
                NewTabs.remember(
                    c,
                    "SELECT t.tab_id FROM $THEIRS.ug_index t WHERE t.sitemap IN (SELECT name FROM $TAKEN) " +
                        "AND NOT EXISTS (SELECT 1 FROM main.ug_index m WHERE m.tab_id = t.tab_id)",
                )
            }
            // As a refresh stores a sitemap (ug/index.py upsert_rows): a row the database has keeps where and when it
            // was first seen, and takes the file's keys and path. As index_transfer._take_ug_rows: a statement for each
            // plan.chunk rows, in tab_id order (the order one statement's scan of the file's rows, by its rowid, took
            // them in, so that the rows the triggers add, the keys and the artists, are numbered as one statement
            // numbered them), a chunk ending at the chunk-th row's tab_id after the last chunk's, the rest one chunk
            // with no bound; each told, the last with done == total (no rows: one chunk of none, 0 of 0). A file
            // whose table repeats a tab_id (made by hand: an export's has a primary key) has fewer rows past a chunk
            // than the count left says: where no chunk-th row is there (or its tab_id is none), the rest is the last
            // chunk.
            val rows = "FROM $THEIRS.ug_index WHERE $IN_TAKEN"
            val total = c.one("SELECT COUNT(*) $rows") { it.long(0)!! }!!
            var done = 0L
            var after: Long? = null
            while (true) {
                val lower = if (after == null) "" else " AND tab_id > ?"
                val low: List<Any?> = listOfNotNull(after)
                val upto: Long? = if (total - done > plan.chunk) {
                    // null: no such row (one statement's `fetchone()` of none), the rest taken in one chunk
                    c.one("SELECT tab_id $rows$lower ORDER BY tab_id LIMIT 1 OFFSET ?",
                          *(low + (plan.chunk - 1)).toTypedArray()) { it.long(0) }
                } else null
                val upper = if (upto == null) "" else " AND tab_id <= ?"
                c.execute(
                    "INSERT INTO main.ug_index (tab_id, artist_key, song_key, type, sitemap, first_seen, path) " +
                        "SELECT tab_id, artist_key, song_key, type, sitemap, first_seen, path $rows$lower$upper " +
                        "ON CONFLICT (tab_id) DO UPDATE SET artist_key = excluded.artist_key, " +
                        "song_key = excluded.song_key, " +
                        "type = excluded.type, path = excluded.path " +
                        "WHERE ug_index.artist_key != excluded.artist_key OR ug_index.song_key != excluded.song_key " +
                        "OR ug_index.type != excluded.type OR ug_index.path != excluded.path",
                    *(low + listOfNotNull(upto)).toTypedArray(),
                )
                done = if (upto == null) total else done + plan.chunk
                said(done, total)
                after = upto ?: break
            }
            plan.checked += total
            takeRecords(c, UG_SITEMAPS, names)
            if (songs.isNotEmpty()) NewTabs.markDirty(c, songs, now)
        }
        val (noLater, args) = plan.readNoLater()
        val newerTabs = "FROM $THEIRS.ug_artist_tabs t LEFT JOIN main.ug_artist_tabs m ON m.page = t.page AND " +
            "m.tab_id = t.tab_id WHERE (m.page IS NULL OR t.read_at > m.read_at)$noLater"
        val tabs = db.one("SELECT COUNT(*) $newerTabs", *args) { it.long(0)!! }!!.toInt()
        plan.take("tab of its artist pages", tabs) { c ->
            val pages = c.query("SELECT DISTINCT t.page $newerTabs", *args) { it.text(0)!! }
            val cols = columns(c, "main", "ug_artist_tabs")
            c.execute(
                "INSERT INTO main.ug_artist_tabs (${cols.joinToString(", ")}) SELECT ${cols.joinToString(", ")} FROM " +
                    "$THEIRS.ug_artist_tabs t WHERE true$noLater ON CONFLICT (page, tab_id) DO UPDATE SET " +
                    cols.drop(2).joinToString(", ") { "$it = excluded.$it" } +
                    " WHERE excluded.read_at > ug_artist_tabs.read_at", *args,
            )
            ArtistTabs.refile(c, pages)
        }
        if (tabs != 0) keysAgain(db, plan, UG_TAB_KEYS)
        planDirectory(db, plan)
        // The index's state: refreshed at the later time, built once either was, and listed as the later read saw it.
        fun seen(schema: String) = listOfNotNull(Stamps.parse(kv(db, schema, UG_REFRESHED)),
                                                 Stamps.parse(kv(db, schema, UG_BUILT))).maxOrNull()
        val mineSeen = seen("main")
        val theirsSeen = seen(THEIRS)
        val listed = kv(db, THEIRS, UG_LISTED)
        if (listed != null && plan.newer(theirsSeen, mineSeen) &&
            listed != kv(db, "main", UG_LISTED)
        ) {
            plan.kv[UG_LISTED] = listed
        }
        later(db, plan, UG_REFRESHED)
        val built = kv(db, THEIRS, UG_BUILT)
        if (built != null && kv(db, "main", UG_BUILT) == null) {
            plan.kv[UG_BUILT] = built
        }
    }

    /**
     * _plan_directory: UG's artist directory (UgDirectory): a row the file saw later in a listing (`seen_at`), or one
     * the database lacks, takes the file's listing columns; a page the file read later (`read_at`) its read columns;
     * and a listing's round, the file's where it got further ([round]), never back. A listing never removes an artist,
     * so neither does a merge. The read columns are taken first: a row the file saw later takes its listing columns
     * alone. With [Plan.notAfter], a time the file gives after it is never later than the database's: a row it saw
     * then is left, a new row it read then comes as never read, and a round it began or ended then is left.
     */
    private fun planDirectory(db: Db, plan: Plan) {
        val (seenNoLater, seenArgs) = plan.noLater("t.seen_at")
        val (readNoLater, readArgs) = plan.noLater("t.read_at")
        val seen = "FROM $THEIRS.ug_directory t LEFT JOIN main.ug_directory m ON m.artist_id = t.artist_id " +
            "WHERE (m.artist_id IS NULL OR t.seen_at > m.seen_at)$seenNoLater"
        val read = "FROM $THEIRS.ug_directory t JOIN main.ug_directory m ON m.artist_id = t.artist_id " +
            "WHERE t.read_at > m.read_at$readNoLater"
        val seenN = db.one("SELECT COUNT(*) $seen", *seenArgs) { it.long(0)!! }!!.toInt()
        val readN = db.one("SELECT COUNT(*) $read", *readArgs) { it.long(0)!! }!!.toInt()
        plan.take("artist page read of its directory", readN) { c ->
            c.execute(
                "UPDATE main.ug_directory AS m SET read_at = t.read_at, read_tabs = t.read_tabs, " +
                    "read_updated = t.read_updated FROM $THEIRS.ug_directory AS t " +
                    "WHERE t.artist_id = m.artist_id AND t.read_at > m.read_at$readNoLater", *readArgs,
            )
        }
        plan.take("artist of its directory", seenN) { c ->
            val cols = columns(c, "main", "ug_directory")
            // A new row's read, under the clock: one the file says it made later comes as never read.
            val read = if (plan.notAfter == null) emptyMap() else mapOf(
                "read_at" to "CASE WHEN t.read_at <= ?1 THEN t.read_at ELSE '' END",
                "read_tabs" to "CASE WHEN t.read_at <= ?1 THEN t.read_tabs ELSE 0 END",
                "read_updated" to "CASE WHEN t.read_at <= ?1 THEN t.read_updated ELSE '' END",
            )
            val picked = cols.joinToString(", ") { read[it] ?: "t.$it" }
            val bound = if (plan.notAfter == null) "" else " AND t.seen_at <= ?1"
            c.execute(
                "INSERT INTO main.ug_directory (${cols.joinToString(", ")}) SELECT $picked FROM " +
                    "$THEIRS.ug_directory t WHERE true$bound ON CONFLICT (artist_id) DO UPDATE SET " +
                    DIRECTORY_LISTED.joinToString(", ") { "$it = excluded.$it" } +
                    " WHERE excluded.seen_at > ug_directory.seen_at", *seenArgs,
            )
        }
        if (seenN != 0) keysAgain(db, plan, UG_DIR_KEYS)
        val mine = records(db, "main", UG_DIR_LETTERS)
        val theirs = records(db, THEIRS, UG_DIR_LETTERS)
        val moved = theirs.entries.filter { (letter, entry) ->
            entry is JsonObject && plan.onTheClock(entry) && compareRounds(round(entry), round(mine[letter])) > 0
        }.map { it.key }.sortedWith(Py.CODE_POINT_ORDER)
        if (moved.isNotEmpty()) {
            val merged = LinkedHashMap(mine)
            for (letter in moved) merged[letter] = theirs.getValue(letter)
            val sorted = merged.entries.sortedWith(compareBy(Py.CODE_POINT_ORDER) { it.key })
                .associateTo(LinkedHashMap()) { it.key to it.value }
            plan.kv[UG_DIR_LETTERS] = PyJson.dumps(pyLoaded(JsonObject(sorted)))  // json.dumps, ensure_ascii=False
        }
    }

    /** _plan_directory's listing columns: those a row the file saw later takes. */
    private val DIRECTORY_LISTED =
        listOf("name", "slug", "letter", "place", "tabs", "updated_at", "artist_key", "forms", "seen_at")

    /** A listing's round as a merge compares two (_round): its last whole read, then its round's start (a time
     * missing, not text or unreadable earlier than any: 0001-01-01's), then its next page (an int as json.loads reads
     * one, else 0). */
    private class Round(val done: Long, val started: Long, val next: BigInteger)

    private fun round(entry: JsonElement?): Round {
        val o = entry as? JsonObject ?: JsonObject(emptyMap())
        fun time(key: String): Long =
            (o[key] as? JsonPrimitive)?.takeIf { it.isString }?.let { Stamps.parse(it.content) } ?: 0L
        val page = o["next"] as? JsonPrimitive
        val next = if (page != null && !page.isString && INTEGER.matches(page.content)) BigInteger(page.content)
        else BigInteger.ZERO
        return Round(time("done"), time("started"), next)
    }

    private fun compareRounds(a: Round, b: Round): Int =
        compareValuesBy(a, b, { it.done }, { it.started }, { it.next })

    /** Whether a round's times are none of them after the plan's clock ([Plan.notAfter]): always, with none. */
    private fun Plan.onTheClock(entry: JsonObject): Boolean {
        val bound = notAfter ?: return true
        return listOf("done", "started").none { key ->
            val at = (entry[key] as? JsonPrimitive)?.takeIf { it.isString }?.let { Stamps.parse(it.content) }
            at != null && at > bound
        }
    }

    // --- applying --------------------------------------------------------------------------------------------------

    /** _apply: the plan's actions and kv records, then the site's keys made current, in one savepoint; what it
     * took. [progress] told each action before it runs, `(site, noun, 0, count)`, and an action's chunks of rows as
     * it tells them, `(site, TAB, done, total)` (MergeProgress). */
    fun apply(db: Db, plan: Plan, progress: ((MergeProgress) -> Unit)? = null): Map<String, Int> {
        db.savepoint("index_merge") {
            for (action in plan.actions) {
                progress?.invoke(MergeProgress(plan.site, action.noun, 0, action.count.toLong()))
                action.run(db) { done, total -> progress?.invoke(MergeProgress(plan.site, MergeProgress.TAB, done, total)) }
            }
            for ((key, value) in plan.kv) if (value == null) db.kvDelete(key) else db.kvSet(key, value)
            currentKeys(db, plan.site)
            db.execute("DROP TABLE IF EXISTS $TAKEN")
        }
        return plan.actions.associateTo(LinkedHashMap()) { it.noun to it.count }
    }

    /** _current_keys: each index's keys made current, as its next read would make them. */
    private fun currentKeys(db: Db, site: String) {
        when (site) {
            "ug" -> {
                ArtistTabs.ensureCurrentKeys(db)
                UgDirectory.ensureCurrentKeys(db)
            }
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

    /** A row of the sitemaps an action takes. */
    private const val IN_TAKEN = "sitemap IN (SELECT name FROM $TAKEN)"

    /** _replace: the database's rows of the pages taken (by [column]) in place of the file's; how many of the file's
     * it took (its insert's own count). */
    private fun replace(db: Db, table: String, column: String): Int {
        val cols = columns(db, "main", table).joinToString(", ")
        db.execute("DELETE FROM main.$table WHERE $column IN (SELECT name FROM $TAKEN)")
        return db.execute("INSERT OR REPLACE INTO main.$table ($cols) SELECT $cols FROM $THEIRS.$table " +
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
