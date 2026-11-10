package io.github.danielhp95.caracole.core.sites.internal.gtptabs

import io.github.danielhp95.caracole.core.db.Db
import io.github.danielhp95.caracole.core.http.BudgetExhausted
import io.github.danielhp95.caracole.core.http.Client
import io.github.danielhp95.caracole.core.http.GtpTabsParseError
import io.github.danielhp95.caracole.core.http.HttpRules
import io.github.danielhp95.caracole.core.http.PagesNotFiles
import io.github.danielhp95.caracole.core.http.Response
import io.github.danielhp95.caracole.core.http.RobotsClosed
import io.github.danielhp95.caracole.core.index.Stamps
import io.github.danielhp95.caracole.core.json.PyJson
import io.github.danielhp95.caracole.core.keys.Normalize
import io.github.danielhp95.caracole.core.library.Kept
import io.github.danielhp95.caracole.core.library.LibraryStore
import io.github.danielhp95.caracole.core.library.Numbering
import io.github.danielhp95.caracole.core.library.Overrides
import io.github.danielhp95.caracole.core.library.SongRow
import io.github.danielhp95.caracole.core.library.Songs
import io.github.danielhp95.caracole.core.library.Versions
import io.github.danielhp95.caracole.core.py.Py
import io.github.danielhp95.caracole.core.sites.GtpTab
import io.github.danielhp95.caracole.core.sites.GtpTabsFetch
import io.github.danielhp95.caracole.core.sites.GtpTabsPages
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import java.time.Duration
import java.time.Instant

/** gtptabs_fetch._Index: `gtptabs_index` as a pass reads it, every artist key with its pages, loaded once. */
internal class GtpIndex(private val db: Db) {
    private val pages = HashMap<String, MutableSet<String>>()
    private val byCompact = HashMap<String, MutableSet<String>>()

    init {
        db.query("SELECT DISTINCT artist_key, artist_path FROM gtptabs_index") { it.text(0)!! to it.text(1)!! }
            .forEach { (key, path) ->
                pages.getOrPut(key) { HashSet() }.add(path)
                byCompact.getOrPut(Normalize.compact(key)) { HashSet() }.add(key)
            }
    }

    /** The index's keys for the song's artists: their own and the site's "Last, First" ones, each also without its
     * hyphens, so `acdc` meets `ac-dc`. */
    fun keys(song: SongRow): List<String> {
        val found = LinkedHashSet<String>()
        for (name in song.artists.ifEmpty { listOf(song.artist) }) {
            for (key in GtpTabsPages.artistKeys(name)) {
                if (key in pages) found.add(key)
                for (other in (byCompact[Normalize.compact(key)] ?: emptySet()).sortedWith(Py.CODE_POINT_ORDER)) {
                    found.add(other)
                }
            }
        }
        return found.toList()
    }

    fun artistPages(song: SongRow): List<String> =
        keys(song).flatMap { key -> pages.getValue(key).sortedWith(Py.CODE_POINT_ORDER) }.distinct()

    /** Whether the sitemaps list the song's title under one of its artists. */
    fun lists(song: SongRow): Boolean {
        val keys = keys(song)
        val title = GtpTabsPages.titleKey(song.title)
        if (keys.isEmpty() || title.isEmpty()) return false
        val marks = keys.joinToString(",") { "?" }
        return db.one("SELECT 1 FROM gtptabs_index WHERE artist_key IN ($marks) AND (title_key = ? OR base_key = ?) " +
                          "LIMIT 1", *keys.toTypedArray(), title, title) { true } != null
    }
}

/**
 * gtptabs_fetch._Pass and one song's turn (`_look_up`): its artist's pages, its candidates, at most three downloads,
 * the file kept. [fetched] are the pages this pass fetched from the site, [pagesInARow] the downloads answered with a
 * page, one after another, across the pass's songs.
 */
internal class GtpPass(private val db: Db, private val client: Client, private val lib: LibraryStore,
                       private val now: Instant) {
    private val fetched = HashSet<String>()
    private var pagesInARow = 0
    private val stamp: String get() = Stamps.of(now)

    /** Download and keep a file for the song: [KEPT]; [MISSING] when its artist's pages answered without a candidate;
     * [WAITING] when every candidate tried gave no file, or none may be tried now. */
    fun lookUp(song: SongRow, index: GtpIndex): String {
        val tabs = ArrayList<GtpTab>()
        for (path in index.artistPages(song)) artistTabs(GtpTabsPages.pageUrl(path))?.let { tabs += it }
        val candidates = candidates(song, tabs)
        if (candidates.isEmpty()) {
            db.kvSet("${GtpTabsFetch.CHECKED_PREFIX}${song.id}", stamp)
            return MISSING
        }
        val usable = candidates.filter { before(db.kvGet("${GtpTabsFetch.UNUSABLE_PREFIX}${it.tabId}"), cutoff(now)) }
        for (tab in usable.take(GtpTabsFetch.DOWNLOADS_PER_SONG)) {
            val found = download(tab) ?: continue
            keep(song, tab, found.first, found.second)
            db.kvSet("${GtpTabsFetch.CHECKED_PREFIX}${song.id}", stamp)
            return KEPT
        }
        return WAITING
    }

    /** The tabs an artist page lists; null when the site has no such page any more, or redirects where robots.txt
     * closes. A cached page that doesn't parse is fetched once more before it is an error, unless this pass fetched
     * it already. */
    private fun artistTabs(url: String): List<GtpTab>? {
        val resp = try {
            client.get(url, accept = ACCEPT, maxAge = ARTIST_PAGE_MAX_AGE)
        } catch (_: RobotsClosed) {
            return null
        }
        if (HttpRules.stale(resp, now, ARTIST_PAGE_MAX_AGE)) throw BudgetExhausted(GtpTabsFetch.PROVIDER)
        return HttpRules.readOnceMore(client, resp, url, { it is GtpTabsParseError }, fetched = fetched, accept = ACCEPT,
                                      read = ::listing)
    }

    private fun listing(resp: Response): List<GtpTab>? =
        if (resp.status == 404) null else GtpTabsPages.parseArtistPage(resp.text, resp.url)

    /** The upload's file and the extension its bytes say; null, and the upload passed over for 30 days, when the site
     * answers 404, a page, or a redirect robots.txt closes. */
    private fun download(tab: GtpTab): Pair<ByteArray, String>? {
        val url = GtpTabsPages.downloadUrl(tab.tabId)
        val resp = try {
            client.get(url, accept = ACCEPT, cache = false)
        } catch (_: RobotsClosed) {
            null
        }
        val ext = if (resp != null && resp.status == 200) GtpTabsFetch.sniff(resp.content) else null
        if (resp != null && ext != null) {
            pagesInARow = 0
            return resp.content to ext
        }
        db.kvSet("${GtpTabsFetch.UNUSABLE_PREFIX}${tab.tabId}", stamp)
        if (resp != null && resp.status == 200) {
            pagesInARow++
            if (pagesInARow >= GtpTabsFetch.PAGES_IN_A_ROW) {
                throw PagesNotFiles(GtpTabsFetch.PROVIDER, url, 200,
                                    "$pagesInARow downloads in a row answered with a page, not a file")
            }
        }
        return null
    }

    /** The file kept as the song's next `guitar-N`, with its version (info.json is the viewer's, milestone 5's). */
    private fun keep(song: SongRow, tab: GtpTab, data: ByteArray, ext: String) {
        val raw = JsonObject(linkedMapOf(
            "title" to JsonPrimitive(tab.title),
            "format" to JsonPrimitive(tab.format),
            "size_kb" to (tab.sizeKb?.let(PyJson::float) ?: JsonNull),
            "instruments" to JsonArray(tab.instruments.map(::JsonPrimitive)),
            "download" to JsonPrimitive(GtpTabsPages.downloadUrl(tab.tabId)),
        ))
        val versionId = Versions.upsert(db, provider = GtpTabsFetch.PROVIDER, tabId = tab.tabId.toString(),
                                        songId = song.id, slot = "guitar",
                                        kind = if (ext == ".ptb") "power" else "guitar-pro",
                                        rating = tab.stars.toDouble(), votes = 0, version = tab.version, label = null,
                                        url = GtpTabsPages.pageUrl(tab.path), raw = raw, now = stamp)
        val number = Numbering.guitar(db, lib, song)
        Kept.keepFile(db, lib, song, versionId, "guitar-$number$ext", data, number, stamp)
    }

    companion object {
        const val KEPT = "kept"
        const val MISSING = "missing"
        const val WAITING = "waiting"
        private val ACCEPT = setOf(200, 404)  // a 404 is an answer: no such artist, or no such file
        private val ARTIST_PAGE_MAX_AGE: Duration = Duration.ofDays(30)
        private const val RECHECK_US = 30L * 86_400_000_000L  // RECHECK_AFTER and UNUSABLE_FOR: 30 days

        /** 30 days before [now], as a time here (Stamps' microseconds). */
        fun cutoff(now: Instant): Long = Stamps.micros(now) - RECHECK_US

        /** stamps.before: whether a stored time is older than [cutoff]; a missing or unreadable one is. */
        fun before(value: String?, cutoff: Long): Boolean {
            val at = Stamps.parse(value)
            return at == null || at < cutoff
        }

        /** The songs, newest first, not ignored, with no Guitar Pro or Power Tab file, and not looked up on
         * gtptabs.com in the last 30 days; of [only] alone when given (a lookup's song), filtered before any song's
         * kv is read, as `gtptabs_files`' filter after it would leave the same. */
        fun songsWantingAFile(db: Db, now: Instant, overrides: Overrides, only: Set<Long>? = null): List<SongRow> {
            val withFile = GtpTabsFetch.songsWithAGuitarFile(db)
            val cutoff = cutoff(now)
            return Songs.list(db).filter { song ->
                (only == null || song.id in only) && song.status != "ignored" && song.key !in overrides.ignore &&
                    song.id !in withFile && before(db.kvGet("${GtpTabsFetch.CHECKED_PREFIX}${song.id}"), cutoff)
            }
        }

        /** Of those, the songs by an artist the index knows: the ones whose title the sitemaps list first, newest
         * first within each group. */
        fun songsToTry(index: GtpIndex, wanting: List<SongRow>): List<SongRow> =
            wanting.filter { index.artistPages(it).isNotEmpty() }.sortedBy { !index.lists(it) }

        /** The uploads of the song's title worth downloading, best first: the same title (its key, or its key
         * without hyphens), a format the library files, a guitar part, at most 5 MB; an upload listed twice is its
         * last listing; most stars first, then the first upload, then the lowest id. */
        fun candidates(song: SongRow, tabs: List<GtpTab>): List<GtpTab> {
            val wanted = GtpTabsPages.titleKey(song.title)
            if (wanted.isEmpty()) return emptyList()
            fun sameTitle(tab: GtpTab): Boolean {
                val key = Normalize.slugKey(tab.title)
                return key == wanted || Normalize.compact(key) == Normalize.compact(wanted)
            }
            val found = LinkedHashMap<Long, GtpTab>()
            for (tab in tabs) {
                if (sameTitle(tab) && tab.format in GtpTabsFetch.FORMATS && tab.guitar &&
                    (tab.sizeKb == null || tab.sizeKb <= GtpTabsFetch.MAX_SIZE_KB)) {
                    found[tab.tabId] = tab
                }
            }
            return found.values.sortedWith(compareBy<GtpTab>({ -it.stars }, { it.version }, { it.tabId }))
        }
    }
}
