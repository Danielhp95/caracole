package io.github.danielhp95.caracole.core.search

import io.github.danielhp95.caracole.core.db.Db
import io.github.danielhp95.caracole.core.keys.Normalize
import io.github.danielhp95.caracole.core.library.SongRow
import io.github.danielhp95.caracole.core.library.Songs
import io.github.danielhp95.caracole.core.py.Py
import io.github.danielhp95.caracole.core.py.PyUnicode
import io.github.danielhp95.caracole.core.search.internal.ug.PyKeys
import io.github.danielhp95.caracole.core.search.internal.ug.ScoredRows
import io.github.danielhp95.caracole.core.search.internal.ug.UgHits
import io.github.danielhp95.caracole.core.search.internal.ug.Yours
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive

/**
 * search.py: your songs, UG's offline index and its artists, read from the phone's database alone (lane search-ug).
 * Every answer is the one search.py gives over the same rows (tests/conformance/vectors/search/library.jsonl and
 * index.jsonl): the same SQL, the same scores (Query, Queries and KeySearch are search.py's seam), the same orders,
 * strings by code point and floats as Python compares them. Nothing here asks any site or writes anything: it runs
 * inside Database.read.
 */
object Search {
    /** search_library: your songs that match [q], best first, whatever their status; with [reading] ("title"), only
     * as that reading scores them. */
    fun searchLibrary(db: Db, q: String, limit: Int = 10, reading: String? = null): List<LibraryHit> {
        val queries = Queries.of(q)
        if (queries.isEmpty()) return emptyList()
        val hits = ArrayList<LibraryHit>()
        for (song in Songs.list(db)) {
            val (score, via) = Queries.songReading(queries, song, reading)
            if (score >= SearchLimits.MIN_SCORE) hits.add(LibraryHit(song, Py.round(score, 1), via))
        }
        val sorted = hits.sortedWith(PyKeys.by({ -it.score }, { PyUnicode.casefold(it.song.display) }, { it.song.id }))
        return PyKeys.head(sorted, limit)
    }

    /** search_removed: the removed songs that match [q], scored as [searchLibrary] scores your songs, best first,
     * the latest removed first among equals. */
    fun searchRemoved(db: Db, q: String, limit: Int = 10): List<RemovedHit> {
        val queries = Queries.of(q)
        if (queries.isEmpty()) return emptyList()
        val hits = ArrayList<RemovedHit>()
        for (gone in Songs.removed(db)) {
            val (score, via) = Queries.namesReading(queries, listOf(gone.artist), gone.title)
            if (score >= SearchLimits.MIN_SCORE) {
                hits.add(RemovedHit(gone.artist, gone.title, gone.key, gone.removedAt, Py.round(score, 1), via))
            }
        }
        return PyKeys.head(hits.sortedWith(PyKeys.by({ -it.score })), limit) // stable: the latest removed first
    }

    /** find_index: the offline index's artists and songs for [q]; with [reading] "title", songs of that title
     * alone, by any artist, and no artist rows. */
    fun findIndex(db: Db, q: String, artists: Int = 3, songs: Int = 8, reading: String? = null): IndexFound {
        val scored = ScoredRows.of(db, q, reading)
        val (rowsScored, named) = ScoredRows.withoutNearNames(scored.rows, scored.named)
        val rows = ScoredRows.artistRows(db, named, scored.parts, artists)
        val shown = rows.mapTo(HashSet()) { it.artistKey }
        val hits = ScoredRows.hits(db, PyKeys.head(rowsScored.filter { !(it.via == "artist" && it.artistKey in shown) }, songs))
        if (rows.isEmpty() && hits.isEmpty()) return IndexFound()
        if (rows.isNotEmpty() && ScoredRows.artistLeads(rows[0], rowsScored, hits)) return IndexFound(rows, hits, "artist", null)
        if (hits.isEmpty()) return IndexFound(rows, emptyList(), "song", null) // only artists a word names, none leads
        val first = hits[0]
        // Never one only an artist's name matched, nor one of a catch-all's: its artist is no one's name.
        val best = if (first.score >= SearchLimits.STRONG && first.via != "artist" && !first.catchAll) first else null
        return IndexFound(rows, hits, "song", best)
    }

    /** found: your songs with the index's answer: a song of yours read by its title (or both) at STRONG or more
     * comes first and is best; never one read only by its artist, nor one under a placeholder artist. */
    fun found(library: List<LibraryHit>, index: IndexFound): Found {
        val yours = library.firstOrNull {
            it.via != "artist" && it.score >= SearchLimits.STRONG && !Normalize.placeholderArtist(it.song.artist)
        }
        if (yours != null) return Found(library, index.artists, index.songs, "song", yours)
        val lead = index.lead ?: if (library.isNotEmpty()) "song" else null
        return Found(library, index.artists, index.songs, lead, index.best)
    }

    /** artist_songs: every song of an artist of the offline index, most tabbed first: [limit] of them from
     * [offset], and how many there are. With [title], only those whose title it matches, best first. */
    fun artistSongs(db: Db, artistKey: String, limit: Int = 50, offset: Int = 0, title: String? = null): Pair<List<IndexHit>, Int> {
        var groups = UgHits.artistGroups(db, artistKey).map { Triple(100.0, it.first, it.second) }
        var via = "artist"
        val queries = Queries.of(title ?: "")
        if (queries.isNotEmpty()) {
            groups = groups.map { (_, base, n) -> Triple(queries.maxOf { it.score("", base.replace("-", " ")) }, base, n) }
                .filter { it.first >= SearchLimits.MIN_SCORE }
                .sortedWith(PyKeys.by({ -it.first }, { -it.third }, { it.second }))
            via = "title"
        }
        val from = minOf(maxOf(offset, 0), groups.size)
        val page = groups.subList(from, minOf(from.toLong() + maxOf(limit, 0).toLong(), groups.size.toLong()).toInt())
        val yours = Yours(db)
        return page.mapNotNull { (score, base, _) -> UgHits.indexHit(db, artistKey, base, score, via, yours) } to groups.size
    }

    /** index_artist: one artist of the index as [findIndex] gives it (score 100); null when the index has no tab of
     * theirs. */
    fun indexArtist(db: Db, artistKey: String): ArtistHit? = UgHits.artistHit(db, artistKey, 100.0)

    /** index_song: one UG song of the index as a hit, as a search shows it (its tabs per type, a sample page, its
     * names as UG writes them); null when the index has no tab of it. The library page's review picker reads it. */
    fun indexSong(db: Db, artistKey: String, songKey: String, score: Double = 0.0): IndexHit? =
        UgHits.indexHit(db, artistKey, songKey, score)

    /** library_by_artist: your songs by an artist, as [name] or UG's [artistKey] writes them, or matched to that
     * artist's songs; by title. */
    fun libraryByArtist(songs: List<SongRow>, name: String, artistKey: String? = null): List<SongRow> {
        val wanted = HashSet<String>()
        Normalize.nameForms(name).mapTo(wanted) { Normalize.compact(it) }
        if (!artistKey.isNullOrEmpty()) wanted.add(Normalize.compact(artistKey))
        wanted.remove("")
        val mine = songs.filter { song ->
            val forms = LinkedHashSet(song.artists.ifEmpty { listOf(song.artist) })
                .flatMap { a -> Normalize.nameForms(a).map { Normalize.compact(it) } }
            val matched = artistKey != null && song.matchDecision in setOf("accept", "pinned") && song.matchArtistKey == artistKey
            forms.any { it in wanted } || matched
        }
        return mine.sortedWith(PyKeys.by({ PyUnicode.casefold(Normalize.cleanTitle(it.title)) }, { it.id }))
    }

    /**
     * bare_id_hint with no overrides.toml to read (the phone has none): what to do when the index can't see an artist,
     * or null when the search went fine. [hits] are the search's [IndexHit]s and [ArtistHit]s; with [artist], the
     * name is known to be the artist's.
     */
    fun bareIdHint(q: String, hits: List<Any>, artist: String? = null): String? {
        val strong = unseen(q, hits) ?: return null
        val lead = if (strong) "UG's sitemaps list artists with accented or non-Latin names only by bare ids." else
            "Nothing in the offline Ultimate Guitar index matches well. UG's sitemaps list some artists only " +
                "by bare ids, usually because of accents or non-Latin letters (Joaquín Sabina, Maná, 宋冬野), so " +
                "caracole can't see their tabs."
        val shown = if (!artist.isNullOrEmpty()) artist else Py.split(q).joinToString(" ")
        val name = shown.replace("\\", "\\\\").replace("\"", "\\\"")
        val line = "\"$name\" = \"$ARTIST_PAGE_SHAPE\""
        val where = ""
        val block = "    [artist_url]\n    $line"
        if (strong) {
            return "$lead If the one you want isn't above, find their page on ultimate-guitar.com, or one of " +
                "their tab pages, and paste its address, as your browser shows it, into overrides.toml$where:\n\n$block"
        }
        val find = if (!artist.isNullOrEmpty()) "Find the artist's page" else "If $shown is the artist's name, find their page"
        var hint = "$lead $find on ultimate-guitar.com once, or one of their tab pages, and " +
            "paste its address, as your browser shows it (an artist page's ends in the artist's number, " +
            "as …/artist/634073 does), into overrides.toml$where:\n\n$block\n\n" +
            "The key is the artist's name as your songs write it, so take any title words out of it. " +
            "Then add the song with `caracole add`; the nightly run looks for its tabs on that page."
        if (artist.isNullOrEmpty()) { // the query may be the song's title: no site is asked for its artist
            hint += "\n\nIf $shown is a title, caracole needs its artist too: `caracole add ARTIST ${shell(shown)}`."
        }
        return hint
    }

    /** bare_id_unseen: [bareIdHint]'s case as facts, for the pages' "Why can't caracole find it?": `strong`, the
     * `[artist_url]` lines to paste (`entry`) and the line that adds a song by its title (`add`); null for no hint. */
    fun bareIdUnseen(q: String, hits: List<Any>): JsonObject? {
        val strong = unseen(q, hits) ?: return null
        val shown = Py.split(q).joinToString(" ")
        val name = shown.replace("\\", "\\\\").replace("\"", "\\\"")
        return JsonObject(linkedMapOf(
            "strong" to JsonPrimitive(strong),
            "entry" to JsonPrimitive("[artist_url]\n\"$name\" = \"$ARTIST_PAGE_SHAPE\""),
            "add" to JsonPrimitive("caracole add ARTIST ${shell(shown)}"),
        ))
    }

    /** no_ones: whether an artist key is no one's name: every misc-… of UG's, misc-mashups too. */
    fun noOnes(artistKey: String): Boolean = UgHits.noOnes(artistKey)

    /** display_from_keys: an artist and a title made from UG keys or slugs, each word capitalized. */
    fun displayFromKeys(artistKey: String, songKey: String): Pair<String, String> = UgHits.displayFromKeys(artistKey, songKey)

    /** overrides.ARTIST_PAGE_SHAPE. */
    private const val ARTIST_PAGE_SHAPE = "https://www.ultimate-guitar.com/artist/…"

    /** _unseen: whether the query may name an artist the index can't see: null when not, else whether something
     * matched it strongly all the same. */
    private fun unseen(q: String, hits: List<Any>): Boolean? {
        val scored = hits.map { hit ->
            when (hit) {
                is IndexHit -> hit.score to hit.page
                is ArtistHit -> hit.score to hit.page
                else -> throw IllegalArgumentException("not a hit of the index: ${hit::class.simpleName}")
            }
        }
        val strong = scored.any { it.first >= SearchLimits.STRONG }
        if (strong && Py.codePoints(q).none { PyUnicode.isAlpha(it) && it >= 0x80 }) return null
        if (scored.any { it.first >= SearchLimits.STRONG && it.second.isNotEmpty() }) return null // a page read answers it
        return strong
    }

    /** _shell: double-quoted for a POSIX shell, as the lines to paste are printed. */
    private fun shell(s: String): String {
        val out = StringBuilder("\"")
        for (c in s) {
            if (c == '"' || c == '\\' || c == '$' || c == '`') out.append('\\')
            out.append(c)
        }
        return out.append('"').toString()
    }
}
