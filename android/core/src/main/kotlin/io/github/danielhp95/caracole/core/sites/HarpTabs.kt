package io.github.danielhp95.caracole.core.sites

import io.github.danielhp95.caracole.core.db.Db
import io.github.danielhp95.caracole.core.http.Client
import io.github.danielhp95.caracole.core.library.LibraryStore
import io.github.danielhp95.caracole.core.library.Overrides
import io.github.danielhp95.caracole.core.library.PassStats
import java.time.Instant

/** harptabs_fetch.HarpTabsStats. */
class HarpTabsStats(var sitemaps: Int = 0, var kept: Int = 0, var missing: Int = 0) : PassStats()

/** harptabs.ListedTab: a tab an artist's page lists. */
data class HarpListedTab(val tabId: Long, val path: String, val title: String)

/** harptabs.ArtistPage: an artist's page read. */
data class HarpArtistPage(val name: String, val tabs: Int, val listed: List<HarpListedTab> = emptyList())

/** harptabs_fetch.py for a lookup's song, and an artist's page read (`caracole harptabs --artist`). */
object HarpTabsFetch {
    fun harptabsTabs(db: Db, client: Client, lib: LibraryStore, now: Instant, overrides: Overrides,
                     only: Set<Long>): HarpTabsStats = TODO("lane harptabs")
    fun readArtist(db: Db, client: Client, path: String, now: Instant): HarpArtistPage? = TODO("lane harptabs")
}
