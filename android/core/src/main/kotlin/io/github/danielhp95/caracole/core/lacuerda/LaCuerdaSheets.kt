package io.github.danielhp95.caracole.core.lacuerda

import io.github.danielhp95.caracole.core.config.RankPolicy
import io.github.danielhp95.caracole.core.db.Db
import io.github.danielhp95.caracole.core.http.Client
import io.github.danielhp95.caracole.core.library.LibraryStore
import io.github.danielhp95.caracole.core.library.Overrides
import io.github.danielhp95.caracole.core.library.PassStats
import io.github.danielhp95.caracole.core.library.SharedFolder
import java.time.Instant

/** lacuerda_fetch.LaCuerdaStats: the sheets kept, the misses, and the songs that wait for a shared folder. */
class LaCuerdaStats(var kept: Int = 0, var missing: Int = 0, val shared: MutableList<SharedFolder> = mutableListOf()) :
    PassStats()

/** lacuerda_fetch.py for a lookup's song, and an artist's page read (`caracole lacuerda --artist`). */
object LaCuerdaSheets {
    fun lacuerdaSheets(db: Db, client: Client, lib: LibraryStore, rank: RankPolicy, now: Instant, overrides: Overrides,
                       only: Set<Long>): LaCuerdaStats = TODO("lane lacuerda-sheets")

    /** The artist's slug and the songs stored, or null for a page LaCuerda doesn't have. */
    fun readArtistPage(db: Db, client: Client, artist: String, now: Instant, first: String? = null): Pair<String, Int>? =
        TODO("lane lacuerda-sheets")
}
