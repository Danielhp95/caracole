package io.github.danielhp95.caracole.core.sites

import io.github.danielhp95.caracole.core.db.Db
import io.github.danielhp95.caracole.core.html.Html
import io.github.danielhp95.caracole.core.html.HtmlNode
import io.github.danielhp95.caracole.core.http.Client
import io.github.danielhp95.caracole.core.inbox.GuitarFiles
import io.github.danielhp95.caracole.core.http.GtpTabsParseError
import io.github.danielhp95.caracole.core.http.PagesNotFiles
import io.github.danielhp95.caracole.core.http.Robots
import io.github.danielhp95.caracole.core.keys.Normalize
import io.github.danielhp95.caracole.core.library.LibraryStore
import io.github.danielhp95.caracole.core.library.Overrides
import io.github.danielhp95.caracole.core.library.PassStats
import io.github.danielhp95.caracole.core.library.Passes
import io.github.danielhp95.caracole.core.library.SongRow
import io.github.danielhp95.caracole.core.py.Py
import io.github.danielhp95.caracole.core.py.PyFloat
import io.github.danielhp95.caracole.core.py.PyInt
import io.github.danielhp95.caracole.core.py.PyRe
import io.github.danielhp95.caracole.core.py.PyRegex
import io.github.danielhp95.caracole.core.sites.internal.gtptabs.GtpIndex
import io.github.danielhp95.caracole.core.sites.internal.gtptabs.GtpPass
import io.github.danielhp95.caracole.core.sites.internal.gtptabs.ZipNames
import java.time.Instant

/** gtptabs_fetch.GtpTabsStats: what one pass did, [sitemaps] the sitemaps read into the index (never on the phone,
 * which reads none), [kept] the songs given a file, [missing] those whose artist's pages answered with no candidate. */
class GtpTabsStats(var sitemaps: Int = 0, var kept: Int = 0, var missing: Int = 0) : PassStats()

/** gtptabs.IndexRow: one page a sitemap lists, by its path; an artist page's [titleKey] and [baseKey] are "", and
 * [baseKey] is the title without an upload number ("song-2" for `song-2-2`). */
data class GtpIndexRow(val path: String, val artistPath: String, val artistKey: String, val titleKey: String,
                       val baseKey: String)

/** gtptabs.GtpTab: one tab of an artist page, [version] its upload number (1 for the first). */
data class GtpTab(val tabId: Long, val title: String, val version: Int, val path: String, val format: String,
                  val stars: Int, val sizeKb: Double?, val instruments: List<String>) {
    /** Whether it may hold a guitar part: it lists one, or (an older upload) no instrument. */
    val guitar: Boolean get() = instruments.isEmpty() || instruments.any { it in GtpTabsPages.GUITARS }
}

/**
 * gtptabs.py on the phone: gtptabs.com's addresses, its sitemaps' rows, a song's keys there, its artist pages read,
 * every regex Python's (PyRegex) and every key Normalize's. The site is described in gtptabs.py's docstring.
 */
object GtpTabsPages {
    const val PROVIDER = "gtptabs"
    const val HOST = "gtptabs.com"
    const val BASE_URL = "https://$HOST"

    // Every slug the sitemaps list is lowercase ASCII letters, digits and hyphens; \d is Python's (any script's digit).
    private val PAGE by lazy {
        PyRegex.compile("""https?://gtptabs\.com/(tabs/\d{1,4}/([a-z0-9-]{1,200}))(?:/([a-z0-9-]{1,200}))?\.html""")
    }
    private val SITEMAP by lazy { PyRegex.compile("""https?://gtptabs\.com/sitemapGoogle(\d{1,4})\.xml""") }
    private val VERSION by lazy { PyRegex.compile("""(.+)-(\d{1,3})""") }
    private val TITLE_VERSION by lazy { PyRegex.compile("""(.*\S)\s*\((\d{1,3})\)""") }
    private val SIZE by lazy { PyRegex.compile("""(?i)\(\s*(\d{1,7}(?:\.\d{1,3})?)\s*Kb\s*\)""") }

    /** gtptabs._INSTRUMENTS: the artist page's label classes, in words. */
    val INSTRUMENTS: Map<String, String> = linkedMapOf(
        "electroGuitarLabelSmall" to "electric guitar",
        "acousticGuitarLabelSmall" to "acoustic guitar",
        "bassGuitarLabelSmall" to "bass",
        "drumsLabelSmall" to "drums",
        "vocalsLabelSmall" to "vocals",
        "keyboardsLabelSmall" to "keyboards",
        "violinLabelSmall" to "violin",
    )
    val GUITARS: Set<String> = setOf("electric guitar", "acoustic guitar")

    /** The address of a page, from its path as the index keeps it (`tabs/2/blur.html`). */
    fun pageUrl(path: String): String = "$BASE_URL/$path"

    fun downloadUrl(tabId: Long): String = "$BASE_URL/tabs/download/$tabId.html"

    /** A gtptabs.com address over https (the sitemaps list http:// ones). */
    fun https(url: String): String = if (url.startsWith("http://$HOST/")) "https://" + url.substring("http://".length) else url

    /** `"6"` for the child sitemap `sitemapGoogle6.xml`; null for any other URL. */
    fun sitemapName(url: String): String? = PyRe.fullmatch(SITEMAP, url)?.groupValues?.get(1)

    /** The index row of a sitemap URL, or null when it is no artist or song page, or robots.txt closes it. */
    fun parsePageUrl(url: String): GtpIndexRow? {
        val m = PyRe.fullmatch(PAGE, url) ?: return null
        val base = m.groupValues[1]
        val artistSlug = m.groupValues[2]
        val songSlug = m.groups[3]?.value
        val artistPath = "$base.html"
        val path = if (songSlug != null) "$base/$songSlug.html" else artistPath
        if (Robots.disallows(pageUrl(path)) != null) return null
        val artist = artistKey(artistSlug)
        if (artist.isEmpty()) return null
        if (songSlug == null) return GtpIndexRow(path, artistPath, artist, "", "")
        val title = Normalize.ugSlugKey(songSlug)
        if (title.isEmpty()) return null
        return GtpIndexRow(path, artistPath, artist, title, base(title))
    }

    /** gtptabs._artist_key: an artist slug's key, ug_slug_key's, once the "the" the site puts last is gone. */
    private fun artistKey(slug: String): String {
        var words = Normalize.fold(slug).split("-").filter { it.isNotEmpty() }
        if (words.size > 1 && words.last() == "the") words = words.dropLast(1)
        return Normalize.ugSlugKey(words.joinToString("-"))
    }

    /** gtptabs._base: a title key without its upload number (2 or more). The number is `\d{1,3}`, so it fits an Int;
     * never BigInteger.TWO, which Android has only from API 33. */
    private fun base(key: String): String {
        val m = PyRe.fullmatch(VERSION, key) ?: return key
        return if (PyInt.parse(m.groupValues[2])!!.toInt() >= 2) m.groupValues[1] else key
    }

    /** The keys an artist may have in the index: the name's own and, for two words or more, the same with its last
     * word first, as the site files people. */
    fun artistKeys(name: String): List<String> {
        val own = Normalize.slugKey(name)
        if (own.isEmpty()) return emptyList()
        val words = own.split("-")
        val rotated = if (words.size > 1) (listOf(words.last()) + words.dropLast(1)).joinToString("-") else own
        return listOf(own, rotated).distinct()
    }

    /** The key a song's title meets the site's titles with: its version suffixes go first (clean_title). */
    fun titleKey(title: String): String = Normalize.slugKey(Normalize.cleanTitle(title))

    /** gtptabs._title: ("Song 2", 2) for "Song 2 (2)"; a title without an upload number is the first upload. */
    fun title(text: String): Pair<String, Int> {
        val m = PyRe.fullmatch(TITLE_VERSION, text) ?: return text to 1
        return m.groupValues[1] to PyInt.parse(m.groupValues[2])!!.toInt()
    }

    /** Every tab an artist page lists; a page without the artist's heading and list is a [GtpTabsParseError], and an
     * entry that doesn't read as a tab of this site (no download id, a link outside /tabs/) is left out. */
    fun parseArtistPage(html: String, url: String?): List<GtpTab> {
        val tree = Html.parse(html)
        if (tree.cssFirst("div.autorInfo h1") == null || tree.cssFirst("div.autorSongs") == null) {
            throw GtpTabsParseError("not an artist page: no artist heading and list of tabs", url)
        }
        return tree.css("div.autorSongs div.autorSong").mapNotNull(::tab)
    }

    private fun tab(node: HtmlNode): GtpTab? {
        val link = node.cssFirst("div.title > a[href]")
        val rating = node.cssFirst("div.ratingSmall[data-item]")
        if (link == null || rating == null) return null
        val href = link.attributes["href"] ?: ""
        val row = if (href.startsWith("/tabs/")) parsePageUrl(BASE_URL + href) else null
        val item = rating.attributes["data-item"] ?: ""
        if (row == null || row.titleKey.isEmpty() || !isId(item)) return null
        val classes = Py.split(node.attributes["class"] ?: "")
        val (title, version) = title(Py.split(link.text()).joinToString(" "))
        val size = PyRe.search(SIZE, node.cssFirst("div.songInfo")?.text() ?: "")
        val labels = node.css("div.instrumentsSmall div.labelSmall").flatMap { label ->
            Py.split(label.attributes["class"] ?: "").filter { it != "labelSmall" }
        }
        return GtpTab(tabId = item.toLong(), title = title, version = version, path = row.path,
                      format = classes.firstOrNull { it != "autorSong" } ?: "", stars = rating.css("a.active").size,
                      sizeKb = size?.let { PyFloat.parse(it.groupValues[1])!! },
                      instruments = labels.map { INSTRUMENTS[it] ?: it.removeSuffix("LabelSmall") })
    }

    /** gtptabs._ID: `[0-9]{1,12}`, ASCII digits alone. */
    private fun isId(s: String): Boolean = s.length in 1..12 && s.all { it in '0'..'9' }
}

/** gtptabs_fetch.py (and gtptabs.sniff) for a lookup's song: a song's Guitar Pro file. */
object GtpTabsFetch {
    const val PROVIDER = GtpTabsPages.PROVIDER

    /** gtptabs_fetch's records: when a song's artist's page last answered for it, and when an upload's download last
     * gave no file (each + the id). */
    const val CHECKED_PREFIX = "gtptabs:checked:"
    const val UNUSABLE_PREFIX = "gtptabs:unusable:"
    const val DOWNLOADS_PER_SONG = 3
    const val PAGES_IN_A_ROW = 3
    const val MAX_SIZE_KB = 5 * 1024
    val FORMATS: Set<String> = setOf("gp3", "gp4", "gp5", "gpx", "gp", "ptb")

    /**
     * gtptabs_fetch.gtptabs_files for the songs of [only] (a lookup's song), with `refresh_index=False`: the phone
     * reads no sitemap, so the index is the computer's. A song not ignored, with no Guitar Pro or Power Tab file and
     * not looked up there in 30 days, by an artist the index knows: its artist's pages (cached 30 days; a stale copy
     * with the budget spent is BudgetExhausted), its candidates downloaded best first, three at most, the first whose
     * bytes [sniff] reads kept as its lowest free `guitar-N` (Kept, Versions, Numbering). ProviderBlocked propagates;
     * a spent budget ends the pass; any other provider error leaves the song in `failures`; three downloads in a row
     * answered with a page end the pass ([PagesNotFiles]). No file is ever replaced or deleted.
     */
    fun gtptabsFiles(db: Db, client: Client, lib: LibraryStore, now: Instant, overrides: Overrides,
                     only: Set<Long>): GtpTabsStats {
        val stats = GtpTabsStats()
        val wanting = GtpPass.songsWantingAFile(db, now, overrides, only)
        if (wanting.isEmpty()) return stats
        val index = GtpIndex(db)
        val run = GtpPass(db, client, lib, now)
        // Each song is checked just before its turn: one may have got a file meanwhile.
        val songs = GtpPass.songsToTry(index, wanting).asSequence().filter { it.id !in songsWithAGuitarFile(db) }
        for ((_, outcome) in Passes.eachSong(songs, stats, "gtptabs.com", stopOn = setOf(PagesNotFiles::class)) { song ->
            run.lookUp(song, index)
        }) {
            if (outcome == GtpPass.KEPT) stats.kept++
            if (outcome == GtpPass.MISSING) stats.missing++
        }
        return stats
    }

    /** gtptabs.sniff: the extension of a Guitar Pro or Power Tab file (.gp3, .gp4, .gp5, .gpx, .gp, .ptb), told by its
     * first bytes; null for anything else, such as an error page served in its place. A zip (Guitar Pro 7 and later)
     * is one when its central directory lists Content/score.gpif (ZipNames: nothing is unpacked). */
    fun sniff(data: ByteArray): String? {
        if (startsWith(data, "ptab")) return ".ptb"
        if (startsWith(data, "BCFZ") || startsWith(data, "BCFS")) return ".gpx"  // Guitar Pro 6's container
        if (data.size >= 4 && data[0] == 0x50.toByte() && data[1] == 0x4B.toByte() && data[2] == 3.toByte() &&
            data[3] == 4.toByte()) {
            return if (ZipNames.names(data)?.contains("Content/score.gpif") == true) ".gp" else null
        }
        if (data.size >= 31) {
            // Guitar Pro 3 to 5: a length byte, then "FICHIER GUITAR PRO v5.00" (bytes.fullmatch, \d ASCII).
            val n = data[0].toInt() and 0xFF
            val field = data.copyOfRange(1, minOf(1 + n, data.size))
            val head = GP_HEAD.length
            if (field.size == head + 5 && startsWith(field, GP_HEAD)) {
                val v = field[head].toInt().toChar()
                val major = field[head + 1].toInt().toChar()
                val dot = field[head + 2].toInt().toChar()
                val d1 = field[head + 3].toInt().toChar()
                val d2 = field[head + 4].toInt().toChar()
                if ((v == 'v' || v == 'L') && major in '3'..'5' && dot == '.' && d1 in '0'..'9' && d2 in '0'..'9') {
                    return ".gp$major"
                }
            }
        }
        return null
    }

    private const val GP_HEAD = "FICHIER GUITAR PRO "

    private fun startsWith(data: ByteArray, prefix: String): Boolean =
        data.size >= prefix.length && prefix.indices.all { data[it] == prefix[it].code.toByte() }

    /** gtptabs_fetch.songs_with_a_guitar_file: the songs the files table holds a Guitar Pro or Power Tab file for
     * (a version of a kind of inbox.GUITAR_FILE_KINDS, [GuitarFiles.KINDS]), whoever kept it. */
    fun songsWithAGuitarFile(db: Db): Set<Long> =
        db.query("SELECT DISTINCT f.song_id FROM files f JOIN versions v ON v.id = f.version_id " +
                     "WHERE v.kind IN ($KIND_MARKS)", *GuitarFiles.KINDS.toTypedArray()) { it.long(0)!! }.toSet()

    private val KIND_MARKS = GuitarFiles.KINDS.joinToString(",") { "?" }

    /**
     * gtptabs_fetch.title_page: the gtptabs.com page whose sitemaps list the song's title under one of its artists,
     * for a song a pass would look up there now (no Guitar Pro or Power Tab file, not looked up there in 30 days);
     * null otherwise. The index alone, for the Requests tab.
     */
    fun titlePage(db: Db, song: SongRow, now: Instant): String? {
        val kept = db.one("SELECT 1 FROM files f JOIN versions v ON v.id = f.version_id WHERE f.song_id = ? " +
                              "AND v.kind IN ($KIND_MARKS) LIMIT 1", song.id, *GuitarFiles.KINDS.toTypedArray()) { true }
        if (kept == true) return null
        if (!GtpPass.before(db.kvGet("$CHECKED_PREFIX${song.id}"), GtpPass.cutoff(now))) return null
        val keys = song.artists.ifEmpty { listOf(song.artist) }.flatMap(GtpTabsPages::artistKeys).distinct()
        val title = GtpTabsPages.titleKey(song.title)
        if (keys.isEmpty() || title.isEmpty()) return null
        val marks = keys.joinToString(",") { "?" }
        return db.one("SELECT path FROM gtptabs_index WHERE artist_key IN ($marks) AND (title_key = ? OR base_key = ?) " +
                          "ORDER BY title_key != base_key, path LIMIT 1", *keys.toTypedArray(), title, title) {
            GtpTabsPages.pageUrl(it.text(0)!!)
        }
    }
}
