package io.github.danielhp95.caracole.core.ug

import io.github.danielhp95.caracole.core.db.Db
import io.github.danielhp95.caracole.core.http.CachedAnswers
import io.github.danielhp95.caracole.core.http.PageParseError
import io.github.danielhp95.caracole.core.index.Reads
import io.github.danielhp95.caracole.core.index.Stamps
import io.github.danielhp95.caracole.core.keys.Normalize
import io.github.danielhp95.caracole.core.library.OverrideUrls
import io.github.danielhp95.caracole.core.library.Overrides
import io.github.danielhp95.caracole.core.py.Py
import io.github.danielhp95.caracole.core.py.PyUrl
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive

/**
 * ug/artist_tabs.py's keys: how the tabs of the artist pages caracole read (`ug_artist_tabs`) are filed, made again
 * where they came in from another database's index ([refile]) or after a change to caracole's keys
 * ([ensureCurrentKeys]), with no request.
 *
 * A tab is filed under the index's keys where the index lists one of its page's tabs (the artist, by the key most of
 * them have) or of its song's (the song, by that tab's), so that a song with both slugged and bare-id tabs is one
 * search hit; else under its names' slug keys (`'song-dongye-宋冬野'`). Its names' forms (Normalize.nameForms and
 * listingForms) are kept beside, for the search's prefilter and its scores. Every call runs inside Database.write.
 *
 * A lookup stores each list page of an artist page it reads ([store]: an older read never overwrites a newer one,
 * only public tabs of caracole's kinds at a tab page kept), keeps a list read whole to the tabs it lists
 * ([keepOnly]), forgets a page UG answers 404 for ([forget]), and once reads what the HTTP cache holds of every
 * artist page caracole knows ([backfill]).
 */
object ArtistTabs {
    /** artist_tabs.KEYS_KEY: the Normalize.KEY_VERSION the keys were made with. */
    const val KEYS_KEY = "ug:artist_tabs:keys"

    private const val MADE =
        "SELECT page, tab_id, artist_key, song_key, artist_forms, title_forms, forms FROM ug_artist_tabs"

    /** ensure_current_keys: every row's keys and forms made again from its names after a change to caracole's keys,
     * once (kv [KEYS_KEY]); how many rows changed. */
    fun ensureCurrentKeys(db: Db): Int {
        val version = Normalize.KEY_VERSION.toString()
        if (db.kvGet(KEYS_KEY) == version) return 0
        return db.savepoint("ug_artist_tabs_keys") {
            val before = made(db)
            val rows = db.query("SELECT page, tab_id, artist, title FROM ug_artist_tabs") {
                listOf(it.text(0)!!, it.long(1)!!, it.text(2)!!, it.text(3)!!)
            }
            for ((page, tabId, artist, title) in rows) {
                val n = names(artist as String, title as String)
                db.execute(
                    "UPDATE ug_artist_tabs SET artist_key = ?, song_key = ?, artist_forms = ?, title_forms = ?, " +
                        "forms = ? WHERE page = ? AND tab_id = ?",
                    n.artistKey, n.songKey, n.artistForms, n.titleForms, n.forms, page, tabId,
                )
            }
            for (page in before.keys.map { it.first }.distinct().sortedWith(Py.CODE_POINT_ORDER)) file(db, page)
            val after = made(db)
            db.kvSet(KEYS_KEY, version)
            before.count { (k, v) -> after[k] != v }
        }
    }

    /**
     * refile: the tabs of these artist pages (their addresses; every page the table holds for null) filed again, as
     * tabs merged from another database's index came in (index_transfer.py); how many rows it filed under other keys.
     * Python's refile takes the pages too, and answers nothing.
     */
    fun refile(db: Db, pages: Collection<String>? = null): Int {
        val before = keysOf(db)
        val which = pages?.toList()
            ?: db.query("SELECT DISTINCT page FROM ug_artist_tabs") { it.text(0)!! }.sortedWith(Py.CODE_POINT_ORDER)
        for (page in which) file(db, page)
        val after = keysOf(db)
        return before.count { (k, v) -> after[k] != v }
    }

    /** _names: a tab's slug keys (the artist's, the song's without a variant label, and that label), its names'
     * forms, space-separated, and every form both hyphenated and written together, for the prefilter ("banma" is in
     * `ban-ma-ban-ma`, a Chinese name's pinyin). */
    internal fun names(artist: String, title: String): Names {
        val clean = Normalize.cleanTitle(title)
        val (base, variant) = Normalize.splitVariant(Normalize.slugKey(clean))
        val artistForms = Normalize.nameForms(artist)
        val titleForms = Normalize.listingForms(clean)
        val every = artistForms + titleForms
        val forms = LinkedHashSet(every + every.map { it.replace("-", "") }).joinToString(" ")
        return Names(Normalize.slugKey(artist), base, variant, artistForms.joinToString(" "),
                     titleForms.joinToString(" "), forms)
    }

    internal data class Names(val artistKey: String, val songKey: String, val variant: String?,
                              val artistForms: String, val titleForms: String, val forms: String)

    /** _file: the page's tabs filed: the artist under the index's key of most of the page's tabs the index lists, a
     * song under the index's key of one of its tabs, and the rest under their names' slug keys. */
    internal fun file(db: Db, page: String) {
        val rows = db.query("SELECT tab_id, artist, title FROM ug_artist_tabs WHERE page = ? ORDER BY tab_id", page) {
            Triple(it.long(0)!!, it.text(1)!!, it.text(2)!!)
        }
        if (rows.isEmpty()) return
        val indexed = LinkedHashMap<Long, Pair<String, String>>()
        db.query(
            "SELECT i.tab_id, i.artist_key, i.song_key FROM ug_index i JOIN ug_artist_tabs a ON a.tab_id = i.tab_id " +
                "WHERE a.page = ? ORDER BY i.tab_id",
            page,
        ) { Triple(it.long(0)!!, it.text(1)!!, it.text(2)!!) }
            .forEach { (tabId, artistKey, songKey) -> indexed[tabId] = artistKey to Normalize.splitVariant(songKey).first }
        val own = LinkedHashMap<Long, Pair<String, String>>()
        for ((tabId, artist, title) in rows) own[tabId] = names(artist, title).let { it.artistKey to it.songKey }
        val artistKey = Py.mostCommonFirst(indexed.values.map { it.first })
            ?: Py.mostCommonFirst(own.values.map { it.first })!!
        val songs = LinkedHashMap<String, String>() // a song's own key -> the index's
        for ((tabId, keys) in indexed) songs.putIfAbsent(own.getValue(tabId).second, keys.second)
        for ((tabId, keys) in own) {
            db.execute("UPDATE ug_artist_tabs SET artist_key = ?, song_key = ? WHERE page = ? AND tab_id = ?",
                       artistKey, songs[keys.second] ?: keys.second, page, tabId)
        }
    }

    private fun made(db: Db): LinkedHashMap<Pair<String, Long>, List<String>> {
        val out = LinkedHashMap<Pair<String, Long>, List<String>>()
        db.query(MADE) { r -> (r.text(0)!! to r.long(1)!!) to (2..6).map { r.text(it)!! } }.forEach { out[it.first] = it.second }
        return out
    }

    private fun keysOf(db: Db): Map<Pair<String, Long>, Pair<String, String>> =
        db.query("SELECT page, tab_id, artist_key, song_key FROM ug_artist_tabs") {
            (it.text(0)!! to it.long(1)!!) to (it.text(2)!! to it.text(3)!!)
        }.toMap()

    // --- an artist page's lists stored as a lookup reads them (lane ug-pages) ----------------------------------

    /** artist_tabs.BACKFILL_KEY: set once the backfill has read the cache. */
    const val BACKFILL_KEY = "ug:artist_tabs:backfill"

    /** artist_tabs.KINDS: the lists of an artist page caracole reads (UgArtist.KIND_FILTERS). */
    val KINDS: List<String> = UgArtist.KIND_FILTERS.keys.toList()

    private val TAB_HOST = PyUrl.urlsplit(UgPage.TAB_BASE_URL).netloc

    private val COLUMNS = listOf("page", "tab_id", "type", "artist", "title", "label", "rating", "votes", "url",
                                 "artist_key", "song_key", "artist_forms", "title_forms", "forms", "read_at")
    private val STORE = "INSERT INTO ug_artist_tabs (${COLUMNS.joinToString(", ")}) VALUES " +
        "(${COLUMNS.joinToString(", ") { "?" }}) ON CONFLICT (page, tab_id) DO UPDATE SET " +
        COLUMNS.drop(2).joinToString(", ") { "$it = excluded.$it" } + " WHERE excluded.read_at >= ug_artist_tabs.read_at"

    /** _kept: a public tab of a kind caracole uses, at a tab page: never Official, nor a link to UG's app. */
    internal fun kept(tab: UgVersion): Boolean {
        if (tab.kind == null || tab.access != "public") return false
        val parts = try {
            PyUrl.urlsplit(tab.url)
        } catch (e: PyUrl.Invalid) {  // a link urllib can't split: no tab page
            return false
        }
        return (parts.scheme == "http" || parts.scheme == "https") && parts.netloc == TAB_HOST &&
            parts.path.startsWith("/tab/")
    }

    /**
     * store: the tabs of one list page of the artist page at [page] (its address, as UG's artist pages are kept:
     * `https://www.ultimate-guitar.com/artist/634073`), whose artist UG names [name] (else each tab's own), as UG gave
     * them at [readAt]: added, or in place of an older read of them, never of a newer one. Only those [kept]; the ids
     * kept. The keys are made current first.
     *
     * The phone's own part: a page it keeps tabs of is noted for the next push to the computer (core.index.Reads,
     * site `ug`) at the store's own time, [now], or [readAt] where that is later, never moved back. Reads.since sends
     * only what was noted after the last push, so a list stored after a push from a copy the cache held from before
     * it is noted at the store, not at its older read, and still goes.
     */
    fun store(db: Db, page: String, name: String, tabs: List<UgVersion>, readAt: String,
              now: String = Stamps.now()): List<Long> {
        val kept = tabs.filter { kept(it) }
        if (kept.isEmpty()) return emptyList()
        ensureCurrentKeys(db)
        db.savepoint("ug_artist_tabs_store") {
            for (t in kept) {
                val artist = name.ifEmpty { t.artistName }
                val n = names(artist, t.songName)
                db.execute(STORE, page, t.tabId, t.kind, artist, t.songName, t.label ?: n.variant, t.rating, t.votes,
                           t.url, n.artistKey, n.songKey, n.artistForms, n.titleForms, n.forms, readAt)
            }
            file(db, page)
            val at = maxOf(readAt, now)
            val noted = db.kvGet("${Reads.READ}ug:$page")
            if (noted == null || at > noted) Reads.note(db, "ug", page, at)
        }
        return kept.map { it.tabId }
    }

    /** keep_only: the page's list of [kind], read whole at [readAt], lists [ids] alone: its other tabs of that kind
     * go, unless a later read gave them. How many went. */
    fun keepOnly(db: Db, page: String, kind: String, ids: Collection<Long>, readAt: String): Int =
        db.savepoint("ug_artist_tabs_keep") {
            val gone = db.execute(
                "DELETE FROM ug_artist_tabs WHERE page = ? AND type = ? AND read_at <= ? " +
                    "AND tab_id NOT IN (SELECT value FROM json_each(?))",
                page, kind, readAt, ids.toSortedSet().joinToString(", ", "[", "]"),
            )
            if (gone > 0) file(db, page)
            gone
        }

    /** forget: UG answers 404 for the artist page at [page]: its tabs go. */
    fun forget(db: Db, page: String) {
        db.execute("DELETE FROM ug_artist_tabs WHERE page = ?", page)
    }

    /** known_pages: every artist page caracole knows, learned from a tab page (kv `ug:artist_url:<key>`) or named by
     * `[artist_url]` (a tab page there is none), each as overrides.artist_page_address writes it, sorted. */
    fun knownPages(db: Db, overrides: Overrides): List<String> {
        val learned = db.query("SELECT value FROM kv WHERE substr(key, 1, ?) = ?", UgLookup.ARTIST_URL_KV.length,
                               UgLookup.ARTIST_URL_KV) { it.text(0)!! }
        val pasted = overrides.artistUrl.values.filter { OverrideUrls.pastedTabId(it) == null }
        return (learned + pasted).mapNotNull { OverrideUrls.artistPageAddress(it) }.distinct()
            .sortedWith(Py.CODE_POINT_ORDER)
    }

    /**
     * backfill: once, the lists [cached] (the HTTP cache, read alone) holds of every artist page caracole knows
     * ([knownPages]) into the table; how many tabs it stored. Nothing is sent, so it works while UG cools down and
     * spends no budget; a list the cache lacks, or one that won't parse, waits for the next time that page is read.
     * The keys are made current first; kv [BACKFILL_KEY] `{"pages", "tabs"}` once done. Each page it stores tabs of
     * is noted at [now], as [store] notes it.
     */
    fun backfill(db: Db, cached: CachedAnswers, overrides: Overrides, now: String = Stamps.now()): Int {
        ensureCurrentKeys(db)
        if (db.kvGet(BACKFILL_KEY) != null) return 0
        val pages = knownPages(db, overrides)
        val stored = LinkedHashSet<Pair<String, Long>>()
        for (page in pages) {
            for (kind in KINDS + listOf<String?>(null)) {  // the unfiltered list last: the others give every tab of a kind
                cachedList(db, cached, page, kind, now).forEach { stored += page to it }
            }
        }
        db.kvSetJson(BACKFILL_KEY, JsonObject(linkedMapOf("pages" to JsonPrimitive(pages.size),
                                                          "tabs" to JsonPrimitive(stored.size))))
        return stored.size
    }

    /** _cached_list: the tabs of one of the page's lists, from as many of its pages as the cache holds in a row,
     * stored. */
    private fun cachedList(db: Db, cached: CachedAnswers, page: String, kind: String?, now: String): List<Long> {
        val ids = ArrayList<Long>()
        var number = 1
        var last = 1
        while (number <= last) {
            val url = UgArtist.pageUrl(page, kind, number)
            val answer = cached.cached(url, setOf(200)) ?: break
            val listed = try {
                UgArtist.parse(answer.content, url)
            } catch (e: PageParseError) {
                break
            }
            last = maxOf(last, listed.pages)
            val tabs = if (kind == null) listed.tabs else listed.tabs.filter { it.kind == kind }
            ids += store(db, page, listed.name, tabs, answer.fetchedAt.orEmpty(), now)
            number++
        }
        return ids
    }
}
