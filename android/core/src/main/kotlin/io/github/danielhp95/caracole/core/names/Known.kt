package io.github.danielhp95.caracole.core.names

import io.github.danielhp95.caracole.core.db.Db
import io.github.danielhp95.caracole.core.keys.Normalize
import io.github.danielhp95.caracole.core.library.SongRow
import io.github.danielhp95.caracole.core.py.Py
import io.github.danielhp95.caracole.core.py.PyUnicode
import io.github.danielhp95.caracole.core.search.SearchLimits

/**
 * song_names._Known: the artists and titles known to the library, the channels given and the local indexes, each name
 * looked up once (song_names.py's module docstring, "A known artist").
 *
 * The few lines of search.py it reads (`library_by_artist`, `_song_counts`, `gtptabs_songs`, `no_ones`) are ported
 * here beside it, so that song names stand on the keys alone, as the plan orders the lanes: core.search.Search's and
 * core.sites.SiteSearch's own are the same rules, and KnownTest replays search.py's own vectors of them (sites.jsonl,
 * library.jsonl, index.jsonl) against these copies, so neither drifts unseen.
 */
internal class Known(private val db: Db?, private val songs: List<SongRow>, private val hints: List<String>) {
    private val artists = HashMap<String, String?>()
    private val titles = HashMap<String, Boolean>()
    private val indexed = HashMap<String, Int>()

    /** The artist [name] is, as your library writes them, else as a channel does, else as written; null for a name no
     * one knows as an artist's whole name. */
    fun artist(name: String): String? {
        val spaced = Py.split(name).joinToString(" ")
        if (spaced !in artists) artists[spaced] = artistOf(spaced)
        return artists[spaced]
    }

    private fun artistOf(name: String): String? {
        if (Normalize.placeholderArtist(name) || Normalize.nameWords(name).isEmpty()) return null
        val wanted = forms(name)
        val mine = libraryByArtist(songs, name)
        val spelled = mine.asSequence()
            .flatMap { s -> LinkedHashSet(s.artists.ifEmpty { listOf(s.artist) }).asSequence() }
            .firstOrNull { a -> forms(a).any { it in wanted } }
        if (spelled != null &&
            (Normalize.nameWords(spelled).size > 1 || credible(mine) || indexSongs(name) >= 1)
        ) {
            return spelled
        }
        for (given in hints) {
            if (!Normalize.placeholderArtist(given) && forms(given).any { it in wanted }) return Py.split(given).joinToString(" ")
        }
        val least = if (Normalize.nameWords(name).size == 1) ONE_WORD_ARTIST else 1
        return if (indexSongs(name) >= least) name else null
    }

    /** Whether a one-word artist of yours is one: two songs of theirs or more, or a sheet from a site for one. */
    private fun credible(mine: List<SongRow>): Boolean {
        if (mine.size > 1) return true
        val ids = mine.map { it.id }
        if (ids.isEmpty() || db == null) return false
        return db.one(
            "SELECT 1 FROM files WHERE name = ? AND song_id IN (${marks(ids.size)}) LIMIT 1", HUMAN_SHEET, *ids.toTypedArray(),
        ) { 1 } != null
    }

    /** The most songs an index has of the artist [name] is: Ultimate Guitar's and the artist pages caracole read,
     * gtptabs.com's, LaCuerda's listings (an artist's row counts their songs), harptabs.com's (as many tabs as their
     * page says once read, else one). No one's name ("misc-…") has none. */
    private fun indexSongs(name: String): Int {
        indexed[name]?.let { return it }
        val forms = Normalize.nameForms(name).filter { it.isNotEmpty() && !noOnes(it) }
        val counts = mutableListOf(0L)
        if (forms.isNotEmpty() && db != null) {
            counts.add(songCounts(db, forms).values.maxOrNull() ?: 0L)
            counts.add(gtptabsSongs(db, name))
            val lcKeys = LinkedHashSet((listOf(name) + forms).map { Normalize.lacuerdaNameKey(it) }.filter { it.isNotEmpty() }).toList()
            if (lcKeys.isNotEmpty()) {
                counts.add(db.one(
                    "SELECT COALESCE(MAX(songs), 0) FROM lacuerda_index WHERE artist_key IN (${marks(lcKeys.size)}) AND title = ''",
                    *lcKeys.toTypedArray(),
                ) { it.long(0)!! }!!)
            }
            counts.add(db.one(
                "SELECT COALESCE(MAX(COALESCE(a.tabs, 1)), 0) FROM harptabs_index i LEFT JOIN harptabs_artists a " +
                    "ON a.path = i.path WHERE i.kind = 'artist' AND i.key IN (${marks(forms.size)}) " +
                    "AND (a.name IS NULL OR a.name != '')",
                *forms.toTypedArray(),
            ) { it.long(0)!! }!!)
        }
        return counts.max().toInt().also { indexed[name] = it }
    }

    /** Whether [text], whole, is a song's title: yours, Ultimate Guitar's or LaCuerda's. */
    fun title(text: String): Boolean = titles.getOrPut(text) { titleOf(text) }

    private fun titleOf(title: String): Boolean {
        val mine = after(Normalize.identityKey("", title))
        if (mine.isNotEmpty() && songs.any { after(it.key) == mine }) return true
        if (db == null) return false
        val key = Normalize.slugKey(title)
        if (key.isNotEmpty() && db.one("SELECT 1 FROM ug_index WHERE song_key = ? LIMIT 1", key) { 1 } != null) return true
        val lc = Normalize.lacuerdaTitleKey(title)
        return lc.isNotEmpty() &&
            db.one("SELECT 1 FROM lacuerda_index WHERE title_key = ? AND title != '' LIMIT 1", lc) { 1 } != null
    }

    companion object {
        /** A one-word name is an index's artist with this many songs there, or a credible one of yours. */
        const val ONE_WORD_ARTIST = 5

        /** songs.HUMAN_SHEET: a song's sheet from a site, never auto-chords'. */
        const val HUMAN_SHEET = "sheet.txt"

        /** search.py `no_ones`: an artist key that is no one's name, every `misc-…` of UG's. */
        fun noOnes(artistKey: String): Boolean = artistKey.startsWith(SearchLimits.CATCH_ALL_PREFIX)

        /** song_names._forms: a name's forms, each written together, none empty. */
        fun forms(name: String): Set<String> = Normalize.nameForms(name).map { Normalize.compact(it) }.filter { it.isNotEmpty() }.toSet()

        /** search.py `library_by_artist` with no artist key: your songs by an artist as [name] writes them, by
         * title (casefolded, in code points), then id. */
        fun libraryByArtist(songs: List<SongRow>, name: String): List<SongRow> {
            val wanted = forms(name)
            val mine = songs.filter { song ->
                LinkedHashSet(song.artists.ifEmpty { listOf(song.artist) }).any { a -> forms(a).any { it in wanted } }
            }
            val order = compareBy<Pair<String, SongRow>, String>(Py.CODE_POINT_ORDER) { it.first }.thenBy { it.second.id }
            return mine.map { PyUnicode.casefold(Normalize.cleanTitle(it.title)) to it }.sortedWith(order).map { it.second }
        }

        /** search.py `_song_counts`: how many song keys the index has of each artist key, and the artist pages caracole
         * read, both added up. */
        fun songCounts(db: Db, keys: List<String>): Map<String, Long> {
            val counts = LinkedHashMap<String, Long>()
            for (part in keys.chunked(500)) {
                for (table in listOf("ug_index", "ug_artist_tabs")) {
                    db.query(
                        "SELECT artist_key, COUNT(DISTINCT song_key) FROM $table WHERE artist_key IN (${marks(part.size)}) " +
                            "GROUP BY artist_key",
                        *part.toTypedArray(),
                    ) { it.text(0)!! to it.long(1)!! }.forEach { (key, n) -> counts[key] = (counts[key] ?: 0L) + n }
                }
            }
            return counts
        }

        /** search.py `gtptabs_songs`: how many songs gtptabs.com's index lists by [artist], under the keys of the
         * name's forms, each also with its last word first; a title's uploads one song, an artist's page none. */
        fun gtptabsSongs(db: Db, artist: String): Long {
            val keys = LinkedHashSet<String>()
            for (form in Normalize.nameForms(artist)) {
                if (form.isNotEmpty() && !noOnes(form) && !Normalize.placeholderArtist(form)) {
                    val words = form.split("-")
                    keys.add(form)
                    keys.add((listOf(words.last()) + words.dropLast(1)).joinToString("-"))
                }
            }
            if (keys.isEmpty()) return 0
            return db.one(
                "SELECT COUNT(DISTINCT base_key) FROM gtptabs_index WHERE artist_key IN (${marks(keys.size)}) AND title_key != ''",
                *keys.toTypedArray(),
            ) { it.long(0)!! }!!
        }

        private fun marks(n: Int): String = List(n) { "?" }.joinToString(", ")

        /** str.partition("/")[2]: what follows the first "/", "" without one. */
        private fun after(key: String): String = key.substringAfter("/", "")
    }
}
