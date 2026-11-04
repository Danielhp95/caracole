package io.github.danielhp95.caracole.core.lyrics

import io.github.danielhp95.caracole.core.db.Db
import io.github.danielhp95.caracole.core.http.Client
import io.github.danielhp95.caracole.core.library.LibraryStore
import io.github.danielhp95.caracole.core.library.PassStats
import java.time.Instant

/** megalobiz_fetch.MegalobizStats. */
class MegalobizStats(var found: Int = 0, var timed: Int = 0, var missing: Int = 0) : PassStats()

/** megalobiz_fetch.py's pass for a lookup's song. */
object Megalobiz {
    fun megalobizLyrics(db: Db, client: Client, lib: LibraryStore, now: Instant, only: Set<Long>): MegalobizStats =
        TODO("lane lyrics")
}
