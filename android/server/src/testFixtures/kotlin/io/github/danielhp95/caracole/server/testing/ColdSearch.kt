package io.github.danielhp95.caracole.server.testing

import io.github.danielhp95.caracole.core.db.Database
import io.github.danielhp95.caracole.core.db.Db
import io.github.danielhp95.caracole.core.db.Timings
import io.github.danielhp95.caracole.core.index.IndexTransfer
import io.github.danielhp95.caracole.core.lacuerda.LaCuerda
import io.github.danielhp95.caracole.core.library.Songs
import io.github.danielhp95.caracole.core.names.SongNames
import io.github.danielhp95.caracole.core.py.PyUrl
import io.github.danielhp95.caracole.core.search.Search
import io.github.danielhp95.caracole.core.search.SiteArtist
import io.github.danielhp95.caracole.core.search.SiteHit
import io.github.danielhp95.caracole.core.search.Suggest
import io.github.danielhp95.caracole.core.sites.SiteSearch
import io.github.danielhp95.caracole.core.testing.BigIndex
import io.github.danielhp95.caracole.server.page.MirrorPageData
import io.github.danielhp95.caracole.server.routes.SearchRoutes
import java.io.File

/**
 * The first search after an import and a start, timed (lane prep-db: ColdSearchBench on the JVM, ColdSearchTest on the
 * emulator; android/README.md's Performance notes): a phone imports a [BigIndex] of [rows] tabs as Settings' Import
 * does (IndexTransfer.merge on the writer, then Database.checkpoint, as Assembly.importIndex), and is killed with it
 * open; it starts again on what that left (its WAL and all), launches its warm-up as Phone does, and answers
 * /api/search through its own SearchRoutes, as the library page asks it. What it measures:
 *
 * - [Result.merge] and [Result.checkpoint]: the import's two steps; [Result.wal], the WAL the import left;
 * - [Result.open]: the start's Database opened again (its own checkpoint, when the WAL is over its limit), and
 *   [Result.walOpened] the WAL after it;
 * - [Result.steps]: the first search's steps one by one, search_routes._found_for's calls of :core in their order,
 *   over a copy of their own of what the import left, before anything else in the process searched (lazily loaded
 *   data, and the database's pages, cold);
 * - [Result.warmUp]: Database.warmUp, run to its end; [Result.first]: the first /api/search answer after it, the
 *   misspelt query, which nothing matches well (so it looks for close spellings too); [Result.warm]: the same once
 *   its answers are forgotten (SearchRoutes.invalidate), the median of three;
 * - an import while the app runs, on a phone of its own: the same search asked before it, over no index yet (so the
 *   letters its words begin with are read, as an owner's first search before an import reads them), then the import
 *   ([Result.imported], merge and checkpoint), then [Result.afterImport], the first search after it, and
 *   [Result.warmAfterImport], the next ones'.
 *
 * The folder [dir] holds the export and four phones; nothing else is written.
 */
class ColdSearch(private val dir: File, private val rows: Int, private val now: String = "2026-11-03T12:00:00Z") {
    class Result(
        val rows: Int, val words: Long, val merge: Long, val checkpoint: Long, val wal: Long, val open: Long,
        val walOpened: Long,
        val steps: List<Timings.Step>, val warmUp: Long, val first: Long, val warm: Long, val imported: Long,
        val afterImport: Long, val warmAfterImport: Long, val queries: List<String>,
    ) {
        override fun toString(): String = buildString {
            append("$rows ug_index rows ($words words of their keys): merged in $merge ms, ")
            append("checkpoint $checkpoint ms, WAL left ${mib(wal)}; ")
            append("a start opened in $open ms, its WAL ${mib(walOpened)}; ")
            append("warm-up $warmUp ms; the first /api/search after it $first ms, warm $warm ms; ")
            append("an import while the app runs $imported ms, the first search after it $afterImport ms, ")
            append("warm $warmAfterImport ms\n")
            append("the first search's steps, cold: ").append(steps.joinToString(", "))
            append("\nqueries: ").append(queries)
        }

        private fun mib(bytes: Long) = "${Math.round(bytes / 1048576.0 * 10) / 10.0} MiB"
    }

    fun run(): Result {
        val big = BigIndex(rows)
        val export = big.export(File(dir, "export.sqlite"))
        val imported = File(dir, "import/caracole.sqlite")
        var merge = 0L
        var checkpoint = 0L
        Database(imported).use { database ->
            database.writeBlocking { IndexTransfer.seedFresh(it) }
            merge = ms { database.writeBlocking { db -> IndexTransfer.merge(db, export, now) } }
            checkpoint = ms { database.checkpoint() }
            // The phone killed with the database open, as Android stops an app: what it wrote, its WAL and all.
            BigIndex.killedCopy(imported, File(dir, "steps/caracole.sqlite"))
            BigIndex.killedCopy(imported, File(dir, "started/caracole.sqlite"))
        }
        val wal = File(File(dir, "started"), "caracole.sqlite-wal").length()
        val query = big.queries[1]

        // The first search's steps, cold: the process has searched nothing yet.
        val was = Timings.enabled
        Timings.enabled = true
        Timings.take()
        val steps = try {
            Database(File(dir, "steps/caracole.sqlite")).use { database -> database.read { db -> steps(db, query) } }
            Timings.take()
        } finally {
            Timings.enabled = was
        }

        // A start: the database opened, its warm-up, then the first search the library page asks.
        val started = File(dir, "started")
        lateinit var routes: SearchRoutes
        val opening = System.nanoTime()
        val app = TestApp(started, { db -> listOf(SearchRoutes(db, MirrorPageData(null)).also { routes = it }) })
        val open = (System.nanoTime() - opening) / 1_000_000
        val target = "/api/search?q=${PyUrl.quote(query, safe = "")}&box=a"
        val walOpened: Long
        val warmUp: Long
        val first: Long
        val warm: Long
        app.use {
            walOpened = File(started, "caracole.sqlite-wal").length()
            warmUp = ms { app.database.warmUp() }
            first = ms { check(app.script(target).status == 200) }
            warm = median { routes.invalidate(); check(app.script(target).status == 200) }
        }

        // An import while the app runs: a search before it, the import, the first search after it.
        val running = File(dir, "running")
        var words = 0L
        lateinit var live: SearchRoutes
        TestApp(running, { db -> listOf(SearchRoutes(db, MirrorPageData(null)).also { live = it }) }).use { phone ->
            phone.database.writeBlocking { IndexTransfer.seedFresh(it) }
            check(phone.script(target).status == 200)
            val imported = ms {
                phone.database.writeBlocking { db -> IndexTransfer.merge(db, export, now) }
                phone.database.checkpoint()
                live.invalidate()  // as Assembly.importIndex's job and afterJob do
            }
            words = phone.database.read { db -> db.one("SELECT COUNT(*) FROM ug_key_words") { it.long(0)!! }!! }
            val afterImport = ms { check(phone.script(target).status == 200) }
            val warmAfterImport = median { live.invalidate(); check(phone.script(target).status == 200) }
            return Result(rows, words, merge, checkpoint, wal, open, walOpened, steps, warmUp, first, warm, imported,
                          afterImport, warmAfterImport, big.queries)
        }
    }

    /** The median time of three runs of [block]. */
    private inline fun median(block: () -> Unit): Long = List(3) { ms(block) }.sorted()[1]

    /** search_routes._found_for's calls of :core, in their order, each a step (Found.answer, without its rows). */
    private fun steps(db: Db, q: String) {
        val mine = Timings.time("library") { Search.searchLibrary(db, q, 5) }
        Timings.time("removed") { Search.searchRemoved(db, q, 5) }
        val found = Timings.time("ug index") { Search.findIndex(db, q, songs = 8) }
        Timings.time("bare-id hint") { Search.bareIdHint(q, found.songs + found.artists) }
        val gtptabs = Timings.time("gtptabs.com") { SiteSearch.searchGtptabs(db, q, 5) }
        val musescore = Timings.time("musescore") { SiteSearch.searchMusescore(db, q, 5) }
        val (harpArtists, harptabs) = Timings.time("harptabs.com") { SiteSearch.searchHarptabs(db, q, songs = 5) }
        val (lcArtists, lacuerda) = Timings.time("lacuerda") { LaCuerda.searchLacuerda(db, q, songs = 5) }
        Timings.time("gametabs.net") { SiteSearch.searchGametabs(db, q, 5) }
        val sites: List<Any> = lcArtists + lacuerda + gtptabs + musescore + harpArtists + harptabs
        Timings.time("close spellings") { Suggest.suggestions(db, q, found, sites) }
        Timings.time("found") { Search.found(mine, found) }
        val songs = Timings.time("songs") { Songs.list(db) }
        Timings.time("names") { SongNames.readNames(db, q, songs) }
        check(sites.all { it is SiteArtist || it is SiteHit })
    }

    private inline fun ms(block: () -> Unit): Long {
        val t0 = System.nanoTime()
        block()
        return (System.nanoTime() - t0) / 1_000_000
    }
}
