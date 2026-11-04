package io.github.danielhp95.caracole.core.sites

import io.github.danielhp95.caracole.core.db.Db
import io.github.danielhp95.caracole.core.http.Client
import io.github.danielhp95.caracole.core.library.LibraryStore
import io.github.danielhp95.caracole.core.library.Overrides
import io.github.danielhp95.caracole.core.library.PassStats
import java.time.Instant

/** gtptabs_fetch.GtpTabsStats. */
class GtpTabsStats(var sitemaps: Int = 0, var kept: Int = 0, var missing: Int = 0) : PassStats()

/** gtptabs_fetch.py (and gtptabs.sniff) for a lookup's song: a song's Guitar Pro file. */
object GtpTabsFetch {
    fun gtptabsFiles(db: Db, client: Client, lib: LibraryStore, now: Instant, overrides: Overrides,
                     only: Set<Long>): GtpTabsStats = TODO("lane tab-files")

    /** gtptabs.sniff: the file's kind by its header (a Guitar Pro or Power Tab file), else null. */
    fun sniff(data: ByteArray): String? = TODO("lane tab-files")
}
