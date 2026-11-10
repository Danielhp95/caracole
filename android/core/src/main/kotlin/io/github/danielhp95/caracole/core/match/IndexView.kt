package io.github.danielhp95.caracole.core.match

import io.github.danielhp95.caracole.core.db.Db
import io.github.danielhp95.caracole.core.keys.Normalize
import io.github.danielhp95.caracole.core.py.Py

/** match.IndexTitle: one title of an artist in the index, its base key, the song keys filed under it (`creep`,
 * `creep-acoustic`), and how many tabs they list. */
data class IndexTitle(val baseKey: String, val songKeys: List<String>, val tabs: Int)

/** One song of a catch-all artist (match.IndexView.catch_all_songs): its artist key, its base key, its tabs. */
data class CatchAllSong(val artistKey: String, val baseKey: String, val tabs: Int)

/**
 * match.IndexView: `ug_index` as the matcher reads it during one run, each answer Python's, with its SQL.
 *
 * The artist keys (about 150,000) are loaded once, when a step first needs them all (steps 3 and 4); until then the
 * index itself answers whether it has an artist and which artists read the same without hyphens, so a song steps 1
 * and 2 settle (an override, or its title under its own artist: a lookup) never loads them. The title keys (about
 * 720,000), which title-only matching alone needs, and the catch-alls' songs (about 90,000) load once too, on first
 * use. An artist's titles are read when a song first asks for that artist. [loaded] says what has loaded.
 *
 * Lists sort by code point (Python's str order, SQLite's BINARY collation); a range's upper bound is U+10FFFF as one
 * code point, as Python binds it.
 */
class IndexView(val db: Db) {
    private var artists: List<String>? = null
    private var artistSet: Set<String> = emptySet()
    private var byCompact: Map<String, List<String>> = emptyMap()
    private var compactArtists: List<String>? = null
    private val titlesByArtist = HashMap<String, List<IndexTitle>>()
    private val tabs = HashMap<String, Int>()
    private var titles: List<String>? = null
    private var compactTitles: List<String>? = null
    private var catchAll: List<CatchAllSong>? = null
    private var catchAllText = ""
    private var catchAllStarts = IntArray(0)

    /** What has loaded whole: "artists", "titles", "catch_all". */
    val loaded: Set<String>
        get() = buildSet {
            if (artists != null) add("artists")
            if (titles != null) add("titles")
            if (catchAll != null) add("catch_all")
        }

    /** Every artist key in the index, sorted. */
    fun artistKeys(): List<String> {
        artists?.let { return it }
        val keys = db.query("SELECT DISTINCT artist_key FROM ug_index ORDER BY artist_key") { it.text(0)!! }
        val grouped = LinkedHashMap<String, MutableList<String>>()
        for (a in keys) grouped.getOrPut(Normalize.compact(a)) { ArrayList(1) }.add(a)
        artists = keys
        artistSet = keys.toHashSet()
        byCompact = grouped
        return keys
    }

    fun hasArtist(artistKey: String): Boolean {
        if (artists == null) {
            return db.one("SELECT 1 FROM ug_index WHERE artist_key = ? LIMIT 1", artistKey) { true } != null
        }
        return artistKey in artistSet
    }

    /** The artist keys that read [compactKey] once hyphens are removed, sorted. */
    fun compactArtists(compactKey: String): List<String> {
        if (compactKey.isEmpty()) return emptyList()
        if (artists == null) {
            // A key never starts or ends with a hyphen, nor holds two in a row: one that reads `acdc` starts with
            // acd, ac-d, a-cd or a-c-d, a range of keys each. UNION, as SQLite reads an OR of ranges as a full scan.
            val head = Py.codePoints(Py.slice(compactKey, 0, 3))
            val starts = (0 until (1 shl (head.size - 1))).map { seps ->
                buildString {
                    head.forEachIndexed { i, cp ->
                        appendCodePoint(cp)
                        if (i < head.size - 1 && (seps shr (head.size - 2 - i)) and 1 == 1) append('-')
                    }
                }
            }
            val sql = List(starts.size) {
                "SELECT DISTINCT artist_key FROM ug_index WHERE artist_key >= ? AND artist_key < ?"
            }.joinToString(" UNION ")
            val args = starts.flatMap { listOf(it, it + LAST) }.toTypedArray()
            return db.query("$sql ORDER BY 1", *args) { it.text(0)!! }.filter { Normalize.compact(it) == compactKey }
        }
        return byCompact[compactKey].orEmpty()
    }

    /** [artistKeys] with hyphens removed, in the same order. */
    fun compactArtistKeys(): List<String> {
        compactArtists?.let { return it }
        return artistKeys().map(Normalize::compact).also { compactArtists = it }
    }

    /** How many tabs the index lists under the artist. */
    fun artistTabs(artistKey: String): Int = tabs.getOrPut(artistKey) {
        db.one("SELECT COUNT(*) FROM ug_index WHERE artist_key = ?", artistKey) { it.long(0)!!.toInt() } ?: 0
    }

    /** The artist's titles, variant keys such as `x-acoustic` with their `x`. */
    fun titlesForArtist(artistKey: String): List<IndexTitle> = titlesByArtist.getOrPut(artistKey) {
        titlesOf(db.query("SELECT song_key, COUNT(*) FROM ug_index WHERE artist_key = ? GROUP BY song_key " +
                              "ORDER BY song_key", artistKey) { it.text(0)!! to it.long(1)!!.toInt() })
    }

    /** Every title in the index as a base key (`creep-acoustic` is `creep`), sorted. */
    fun titleKeys(): List<String> {
        titles?.let { return it }
        val bases = HashSet<String>()
        db.query("SELECT DISTINCT song_key FROM ug_index") { bases.add(Normalize.splitVariant(it.text(0)!!).first) }
        return bases.sortedWith(Py.CODE_POINT_ORDER).also { titles = it }
    }

    /** [titleKeys] with hyphens removed, in the same order. */
    fun compactTitleKeys(): List<String> {
        compactTitles?.let { return it }
        return titleKeys().map(Normalize::compact).also { compactTitles = it }
    }

    /** The title keys that read [compactKey] once hyphens are removed. */
    fun titlesReading(compactKey: String): List<String> {
        val keys = titleKeys()
        val compacts = compactTitleKeys()
        return keys.indices.filter { compacts[it] == compactKey }.map { keys[it] }
    }

    /** Every artist key with a title whose base key is [titleKey], with its tabs, by artist key. */
    fun artistsForTitle(titleKey: String): Map<String, Int> {
        // A range instead of LIKE, so the song_key index serves the variant keys too.
        val rows = db.query(
            "SELECT artist_key, song_key, COUNT(*) FROM ug_index WHERE song_key = ? OR (song_key > ? AND song_key < ?) " +
                "GROUP BY artist_key, song_key ORDER BY artist_key, song_key",
            titleKey, "$titleKey-", "$titleKey.",
        ) { Triple(it.text(0)!!, it.text(1)!!, it.long(2)!!.toInt()) }
        val out = LinkedHashMap<String, Int>()
        for ((artist, song, n) in rows) {
            if (Normalize.splitVariant(song).first == titleKey) out[artist] = (out[artist] ?: 0) + n
        }
        return out
    }

    /** Every song of the catch-all artists step 4 reads ([Match.SHOW_CATCH_ALLS], [Match.PERFORMER_CATCH_ALLS]),
     * variant keys counted with their song, sorted. */
    fun catchAllSongs(): List<CatchAllSong> {
        catchAll?.let { return it }
        val keys = (Match.SHOW_CATCH_ALLS + Match.PERFORMER_CATCH_ALLS).sortedWith(Py.CODE_POINT_ORDER)
        val marks = keys.joinToString(", ") { "?" }
        val counted = LinkedHashMap<Pair<String, String>, Int>()
        db.query("SELECT artist_key, song_key, COUNT(*) FROM ug_index WHERE artist_key IN ($marks) " +
                     "GROUP BY artist_key, song_key", *keys.toTypedArray()) {
            val key = it.text(0)!! to Normalize.splitVariant(it.text(1)!!).first
            counted[key] = (counted[key] ?: 0) + it.long(2)!!.toInt()
        }
        val songs = counted.map { (k, n) -> CatchAllSong(k.first, k.second, n) }.sortedWith(
            Comparator<CatchAllSong> { x, y -> Py.CODE_POINT_ORDER.compare(x.artistKey, y.artistKey) }
                .thenComparing({ it.baseKey }, Py.CODE_POINT_ORDER).thenBy { it.tabs },
        )
        val text = StringBuilder()
        val starts = IntArray(songs.size)
        songs.forEachIndexed { i, s ->
            starts[i] = text.length
            text.append('-').append(s.baseKey).append("-\n")
        }
        catchAllText = text.toString()
        catchAllStarts = starts
        catchAll = songs
        return songs
    }

    /** The [catchAllSongs] whose line `-base-` holds any of [needles], in the same order; a needle that ends in a
     * newline holds the line's end (`-my-shot-\n` is a title that ends in `my-shot`). */
    fun catchAllHolding(needles: List<String>): List<CatchAllSong> {
        val songs = catchAllSongs()
        val text = catchAllText
        val found = java.util.TreeSet<Int>()
        for (needle in needles) {
            var i = if (needle.isEmpty()) 0 else text.indexOf(needle)
            while (i != -1 && i <= text.length) {
                lineAt(i)?.let(found::add)
                i = if (needle.isEmpty()) i + 1 else text.indexOf(needle, i + 1)
            }
        }
        return found.map { songs[it] }
    }

    /** bisect_right(starts, i) - 1: the line [i] is in (null before the first, as Python's index -1 is no line
     * there: no text, no line). */
    private fun lineAt(i: Int): Int? {
        var lo = 0
        var hi = catchAllStarts.size
        while (lo < hi) {
            val mid = (lo + hi) ushr 1
            if (i < catchAllStarts[mid]) hi = mid else lo = mid + 1
        }
        return (lo - 1).takeIf { it >= 0 }
    }

    /** The (artist key, song key) a tab is indexed under, if it is indexed. */
    fun tabKeys(tabId: Long): Pair<String, String>? =
        db.one("SELECT artist_key, song_key FROM ug_index WHERE tab_id = ?", tabId) { it.text(0)!! to it.text(1)!! }

    companion object {
        /** U+10FFFF, one code point: a range's upper bound, as Python's `"\U0010ffff"`. */
        private val LAST = String(Character.toChars(0x10FFFF))

        /** match._titles_of: (song key, tabs) rows, sorted by song key, grouped by base key in the order each base
         * first comes. */
        internal fun titlesOf(rows: List<Pair<String, Int>>): List<IndexTitle> {
            val keys = LinkedHashMap<String, MutableList<String>>()
            val tabs = HashMap<String, Int>()
            for ((songKey, n) in rows) {
                val base = Normalize.splitVariant(songKey).first
                keys.getOrPut(base) { ArrayList(1) }.add(songKey)
                tabs[base] = (tabs[base] ?: 0) + n
            }
            return keys.map { (base, k) -> IndexTitle(base, k, tabs.getValue(base)) }
        }
    }
}
