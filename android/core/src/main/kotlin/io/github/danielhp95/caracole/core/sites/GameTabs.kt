package io.github.danielhp95.caracole.core.sites

import io.github.danielhp95.caracole.core.db.Db
import io.github.danielhp95.caracole.core.http.Client
import io.github.danielhp95.caracole.core.library.LibraryStore
import io.github.danielhp95.caracole.core.library.Overrides
import io.github.danielhp95.caracole.core.library.PassStats
import java.time.Instant

/** gametabs_fetch.GameTabsStats. */
class GameTabsStats(var sitemaps: Int = 0, var kept: Int = 0, var missing: Int = 0) : PassStats()

/** gametabs_fetch.py for a lookup's song. */
object GameTabsFetch {
    fun gametabsTabs(db: Db, client: Client, lib: LibraryStore, now: Instant, overrides: Overrides,
                     only: Set<Long>): GameTabsStats = TODO("lane gametabs")
}
