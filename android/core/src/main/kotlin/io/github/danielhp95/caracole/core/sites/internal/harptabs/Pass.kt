package io.github.danielhp95.caracole.core.sites.internal.harptabs

import io.github.danielhp95.caracole.core.db.Db
import io.github.danielhp95.caracole.core.http.Client
import io.github.danielhp95.caracole.core.http.HarpTabsParseError
import io.github.danielhp95.caracole.core.http.HttpRules
import io.github.danielhp95.caracole.core.http.RobotsClosed
import io.github.danielhp95.caracole.core.index.Stamps
import io.github.danielhp95.caracole.core.keys.Normalize
import io.github.danielhp95.caracole.core.library.HarpTabsPick
import io.github.danielhp95.caracole.core.library.Kept
import io.github.danielhp95.caracole.core.library.LibraryStore
import io.github.danielhp95.caracole.core.library.Numbering
import io.github.danielhp95.caracole.core.library.Overrides
import io.github.danielhp95.caracole.core.library.Passes
import io.github.danielhp95.caracole.core.library.SongRow
import io.github.danielhp95.caracole.core.library.Songs
import io.github.danielhp95.caracole.core.library.Versions
import io.github.danielhp95.caracole.core.py.Py
import io.github.danielhp95.caracole.core.sites.HarpTabs
import io.github.danielhp95.caracole.core.sites.HarpTabsFetch
import io.github.danielhp95.caracole.core.sites.HarpTabsFetch.CANDIDATES
import io.github.danielhp95.caracole.core.sites.HarpTabsFetch.CHECKED_PREFIX
import io.github.danielhp95.caracole.core.sites.HarpTabsFetch.PICKED
import io.github.danielhp95.caracole.core.sites.HarpTabsStats
import io.github.danielhp95.caracole.core.sites.SiteKeys
import io.github.danielhp95.caracole.core.sites.internal.harptabs.HarpTabsPages.HarpTab
import java.time.Instant

/** harptabs_fetch.py's pass for one song, on the phone (HarpTabsFetch's docs say what it does). */
internal object HarpPass {
    private const val KEPT = "kept"
    private const val MISSING = "missing"
    private const val HARMONICA = "harmonica"  // inbox.HARMONICA_KIND

    fun harptabsTabs(db: Db, client: Client, lib: LibraryStore, now: Instant, overrides: Overrides,
                     only: Set<Long>): HarpTabsStats {
        val stats = HarpTabsStats()
        SiteKeys.harptabsRowKeys(db)  // harptabs_fetch.ensure_current_keys: the sitemap's rows keyed as now
        val wanting = wanting(db, now, overrides).filter { it.id in only }
        if (wanting.isEmpty()) return stats
        val index = Index(db)
        val run = Run(db, client, lib, now)
        // Each song is checked just before its turn, as Python's generator checks it.
        val songs = wanting.asSequence()
            .filter { (pick(overrides, it) != null || index.candidates(it).isNotEmpty()) && wants(db, it, overrides) }
        for ((_, outcome) in Passes.eachSong(songs, stats, "harptabs.com") { lookUp(run, it, index, pick(overrides, it)) }) {
            if (outcome == KEPT) stats.kept++
            if (outcome == MISSING) stats.missing++
        }
        return stats
    }

    /** _forms: the keys the song's artists are compared by (normalize.name_forms). */
    private fun forms(song: SongRow): List<String> =
        song.artists.ifEmpty { listOf(song.artist) }.flatMap { Normalize.nameForms(it) }.filter { it.isNotEmpty() }

    fun sameArtist(song: SongRow, artist: String?): Boolean {
        if (artist == null) return false
        val theirs = forms(song).map(Normalize::compact).toSet()
        return Normalize.nameForms(artist).filter { it.isNotEmpty() }.any { Normalize.compact(it) in theirs }
    }

    // --- which songs ----------------------------------------------------------------------------------------------

    /** _songs_wanting_a_tab: the songs, newest first, not ignored, with no harmonica tab (or not the one you picked),
     * not looked up on harptabs.com in the last 30 days unless a pick is new. */
    private fun wanting(db: Db, now: Instant, overrides: Overrides): List<SongRow> {
        val withTab = withATab(db)
        val cutoff = Stamps.micros(now.minus(HarpTabsFetch.RECHECK_AFTER))
        return Songs.list(db).filter { song ->
            song.status != "ignored" && song.key !in overrides.ignore &&
                (if (pick(overrides, song) == null) song.id !in withTab else wants(db, song, overrides)) &&
                (before(db.kvGet("$CHECKED_PREFIX${song.id}"), cutoff) || newlyPicked(db, song, overrides))
        }
    }

    /** stamps.before: a stored time older than [cutoff]; a missing or unreadable one is. */
    private fun before(value: String?, cutoff: Long): Boolean = Stamps.parse(value)?.let { it < cutoff } ?: true

    /** _newly_picked: a tab you picked for the song that wasn't asked for yet. */
    private fun newlyPicked(db: Db, song: SongRow, overrides: Overrides): Boolean {
        val pick = pick(overrides, song) ?: return false
        return db.kvGet("$CHECKED_PREFIX${song.id}$PICKED") != pick.tabId.toString()
    }

    private fun pick(overrides: Overrides, song: SongRow): HarpTabsPick? = overrides.harptabs[song.key]

    /** _wants: the one you picked, while the song hasn't kept it; else any, while it has none. */
    private fun wants(db: Db, song: SongRow, overrides: Overrides): Boolean {
        val pick = pick(overrides, song) ?: return song.id !in withATab(db)
        return db.one(
            "SELECT 1 FROM files f JOIN versions v ON v.id = f.version_id WHERE f.song_id = ? AND v.provider = ? " +
                "AND v.kind = ? AND v.tab_id = ? LIMIT 1", song.id, HarpTabsPages.PROVIDER, HARMONICA, pick.tabId.toString(),
        ) { true } == null
    }

    fun withATab(db: Db): Set<Long> = db.query(
        "SELECT DISTINCT f.song_id FROM files f JOIN versions v ON v.id = f.version_id WHERE v.kind = ?", HARMONICA,
    ) { it.long(0)!! }.toSet()

    // --- the index ------------------------------------------------------------------------------------------------

    /** _Index: harptabs_index as a pass reads it: the artists' keys, hyphens aside, loaded once; and the artist pages
     * read (harptabs_artists), by their slug's key, hyphens aside. */
    private class Index(val db: Db) {
        val artists: Set<String> = db.query("SELECT key FROM harptabs_index WHERE kind = ?", HarpTabs.ARTIST) {
            Normalize.compact(it.text(0)!!)
        }.toSet()
        val pages = LinkedHashMap<String, MutableList<String>>().also { pages ->
            db.query("SELECT path, key FROM harptabs_artists WHERE name != '' ORDER BY page_id") {
                it.text(0)!! to it.text(1)!!
            }.forEach { (path, key) -> pages.getOrPut(Normalize.compact(key)) { mutableListOf() }.add(path) }
        }

        /** The tabs titled as the song is, (id, path), at most CANDIDATES: those of the title the read page of one of
         * its artists lists, the most viewed first, then the sitemap's, lowest id first; none when the sitemap lists
         * no artist by one of its artists' names. */
        fun candidates(song: SongRow): List<Pair<Long, String>> {
            val keys = HarpTabsPages.titleKeys(song.title)
            val forms = forms(song).map(Normalize::compact).toSet()
            if (keys.isEmpty() || forms.none { it in artists }) return emptyList()
            val found = theirs(song, forms).distinct().toMutableList()
            val marks = keys.joinToString(", ") { "?" }
            db.query("SELECT page_id, path FROM harptabs_index WHERE kind = ? AND key IN ($marks) ORDER BY page_id " +
                         "LIMIT ?", HarpTabs.TAB, *keys.toTypedArray(), CANDIDATES) { it.long(0)!! to it.text(1)!! }
                .forEach { if (it !in found) found += it }
            return found.take(CANDIDATES)
        }

        /** _theirs: the tabs of the song's title the read page of one of its artists lists, the most viewed first. */
        private fun theirs(song: SongRow, forms: Set<String>): List<Pair<Long, String>> {
            val paths = forms.sortedWith(Py.CODE_POINT_ORDER).flatMap { pages[it].orEmpty() }
            val key = HarpTabs.songKey(song.title)
            if (paths.isEmpty() || key.isEmpty()) return emptyList()
            val marks = paths.joinToString(", ") { "?" }
            return db.query("SELECT tab_id, path FROM harptabs_artist_tabs WHERE artist IN ($marks) AND song_key = ? " +
                                "ORDER BY views DESC, place LIMIT ?", *paths.toTypedArray(), key, CANDIDATES) {
                it.long(0)!! to it.text(1)!!
            }
        }
    }

    // --- one song -------------------------------------------------------------------------------------------------

    private class Run(val db: Db, val client: Client, val lib: LibraryStore, val now: Instant) {
        val fetched = HashSet<String>()  // pages fetched from the site in this pass
        val stamp: String = Stamps.of(now)
    }

    /** _look_up: the song's candidates read and the most viewed by its artist kept (KEPT, else MISSING); with [pick],
     * that tab alone, kept whoever its page names (MISSING when the site no longer has it). */
    private fun lookUp(run: Run, song: SongRow, index: Index, pick: HarpTabsPick?): String {
        if (pick != null) {
            val tab = tab(run, pick.url)
            if (tab != null) keep(run, song, pick.tabId, pick.path, tab)
            run.db.kvSet("$CHECKED_PREFIX${song.id}", run.stamp)
            run.db.kvSet("$CHECKED_PREFIX${song.id}$PICKED", pick.tabId.toString())
            return if (tab != null) KEPT else MISSING
        }
        val found = ArrayList<Triple<Long, String, HarpTab>>()
        for ((pageId, path) in index.candidates(song)) {
            val tab = tab(run, HarpTabs.pageUrl(path))
            if (tab != null && sameArtist(song, tab.artist)) found += Triple(pageId, path, tab)
        }
        found.minWithOrNull(BEST)?.let { (pageId, path, tab) -> keep(run, song, pageId, path, tab) }
        run.db.kvSet("$CHECKED_PREFIX${song.id}", run.stamp)
        return if (found.isNotEmpty()) KEPT else MISSING
    }

    /** Python's `min(found, key=lambda f: (-views, -(rating or 0.0), page_id))`: the most viewed, then the best
     * rated (as `<` compares floats: -0.0 is 0.0), then the lowest id; the first of equals. */
    private val BEST = Comparator<Triple<Long, String, HarpTab>> { a, b ->
        val ra = a.third.rating ?: 0.0
        val rb = b.third.rating ?: 0.0
        when {
            a.third.views != b.third.views -> b.third.views.compareTo(a.third.views)
            ra > rb -> -1
            ra < rb -> 1
            else -> a.first.compareTo(b.first)
        }
    }

    /** _tab: a tab page, read; null when the site no longer has it (404), or sends it where robots.txt closes. A
     * cached page that won't parse is asked for once more before it is an error. */
    private fun tab(run: Run, url: String): HarpTab? {
        val resp = try {
            run.client.get(url, accept = HarpTabsFetch.ACCEPT)
        } catch (_: RobotsClosed) {
            return null
        }
        return HttpRules.readOnceMore(run.client, resp, url, { it is HarpTabsParseError }, fetched = run.fetched,
                                      accept = HarpTabsFetch.ACCEPT) { r ->
            if (r.status == 404) null else HarpTabsPages.parseTabPage(r.content, r.url)
        }
    }

    /** _keep: the tab as the song's next `harmonica-N.txt`, with its version; its name. */
    private fun keep(run: Run, song: SongRow, pageId: Long, path: String, tab: HarpTab): String {
        val versionId = Versions.upsert(
            run.db, provider = HarpTabsPages.PROVIDER, tabId = pageId.toString(), songId = song.id, slot = "guitar",
            kind = HARMONICA, rating = tab.rating ?: 0.0, votes = tab.views.coerceAtMost(Int.MAX_VALUE.toLong()).toInt(),
            version = 1, label = null, url = HarpTabs.pageUrl(path), raw = tab.raw(), now = run.stamp,
        )
        // votes is the views, Python's int: a count past an Int written as it is
        if (tab.views > Int.MAX_VALUE) run.db.execute("UPDATE versions SET votes = ? WHERE id = ?", tab.views, versionId)
        val number = Numbering.harmonica(run.db, run.lib, song)
        val name = "harmonica-$number.txt"
        Kept.keepFile(run.db, run.lib, song, versionId, name, tab.body.toByteArray(Charsets.UTF_8), number, run.stamp)
        return name
    }
}
