package io.github.danielhp95.caracole.core.db

import io.github.danielhp95.caracole.core.lacuerda.LaCuerda
import io.github.danielhp95.caracole.core.library.Songs
import io.github.danielhp95.caracole.core.names.SongNames
import io.github.danielhp95.caracole.core.search.Search
import io.github.danielhp95.caracole.core.search.Suggest
import io.github.danielhp95.caracole.core.sites.SiteSearch

/**
 * What makes the first search after a start, or after an import, as quick as the next ones (the plan's prep-db;
 * android/README.md's Performance notes say what was measured):
 *
 * - [optimize]: an import's merge of UG's rows leaves each of UG's three full-text indexes (its keys' trigrams, its
 *   artists' words, its rows' words) in the many segments its triggers wrote them in, which every search then reads
 *   and merges; FTS5's `optimize` makes each one segment, once, as the merge ends (IndexTransfer.merge). It rewrites
 *   each index whole, on the writer, so only a merge that changed many of UG's rows asks it ([optimizes]: an import,
 *   never a sync's nightly few or a merge of UG's artist pages alone, which FTS5's own automerge keeps).
 * - [run], Database.warmUp: one search, through the reader pool, of what search_routes._found_for asks of :core
 *   (your songs, UG's index, each site's, the close spellings of a query nothing matches, the names it reads): the
 *   lazily loaded data and the code it runs loaded, and the pages it reads read, before the owner's first search.
 *   It answers nothing and writes nothing; the app's start launches it on Dispatchers.IO, and a search that comes
 *   meanwhile runs beside it, never behind it. Each step is timed (Timings) while timings are on.
 */
internal object Warmup {
    /** UG's full-text indexes, each FTS5's: an import's merge of UG's rows makes each one segment. */
    val UG_FTS = listOf("ug_index_fts", "ug_keys_fts", "ug_artists_fts")

    /** A query that names nothing an index holds well, so that the warm-up looks for close spellings too, as a
     * misspelt first search does. */
    const val QUERY = "warmup quiet cello"

    /** The rows changed (sqlite3_total_changes: each statement's, its triggers' included) past which a merge's UG
     * rows make it worth [optimize]: an import of an index (hundreds of thousands), never a nightly refresh's few
     * sitemaps (a few thousand new tabs at most). */
    const val OPTIMIZE_AFTER = 100_000L

    /** The rows the connection changed since it opened (`total_changes()`). */
    fun changes(db: Db): Long = db.one("SELECT total_changes()") { it.long(0)!! }!!

    /** Whether a merge whose UG actions were [actions] ([Merge.apply]'s, null for none), having changed [changes]
     * rows, makes UG's full-text indexes one segment each: its sitemaps' rows taken, and [changes] at least [after]. */
    fun optimizes(actions: Map<String, Int>?, changes: Long, after: Long = OPTIMIZE_AFTER): Boolean =
        actions.orEmpty().containsKey("sitemap") && changes >= after

    /** FTS5's optimize of each of UG's full-text indexes ([UG_FTS]): on the writer, in no transaction of the
     * caller's; each one is its own. */
    fun optimize(db: Db) {
        for (table in UG_FTS) {
            Timings.time("optimize $table") { db.execute("INSERT INTO $table($table) VALUES ('optimize')") }
        }
    }

    fun run(database: Database) {
        database.read { db -> Timings.time("warm-up") { search(db, QUERY) } }
    }

    /** search_routes._found_for's calls of :core, in their order (Found.answer, without the rows it makes). */
    private fun search(db: Db, q: String) {
        val mine = Timings.time("warm-up: library") { Search.searchLibrary(db, q, 5) }
        Search.searchRemoved(db, q, 5)
        val found = Timings.time("warm-up: ug index") { Search.findIndex(db, q, songs = 8) }
        Search.bareIdHint(q, found.songs + found.artists)
        val sites: List<Any> = Timings.time("warm-up: sites") {
            val (lcArtists, lacuerda) = LaCuerda.searchLacuerda(db, q, songs = 5)
            val (harpArtists, harptabs) = SiteSearch.searchHarptabs(db, q, songs = 5)
            SiteSearch.searchGametabs(db, q, 5)
            lcArtists + lacuerda + SiteSearch.searchGtptabs(db, q, 5) + SiteSearch.searchMusescore(db, q, 5) +
                harpArtists + harptabs
        }
        Timings.time("warm-up: close spellings") { Suggest.suggestions(db, q, found, sites) }
        Search.found(mine, found)
        Timings.time("warm-up: names") { SongNames.readNames(db, q, Songs.list(db)) }
    }
}
