package io.github.danielhp95.caracole.core.ug

import io.github.danielhp95.caracole.core.config.RankPolicy
import io.github.danielhp95.caracole.core.db.Db
import io.github.danielhp95.caracole.core.http.Client
import io.github.danielhp95.caracole.core.library.LibraryStore
import io.github.danielhp95.caracole.core.library.Overrides
import java.time.Duration
import java.time.Instant

/** ug/fetch.FetchContext: what a fetch reads (its reload_overrides the phone never needs: one worker, no handoff). */
class FetchContext(val db: Db, val client: Client, val overrides: Overrides, val rank: RankPolicy,
                   val library: LibraryStore, val now: Instant, val maxPagesPerGroup: Int = 3,
                   val guitarPagesPerGroup: Int = 1, val artistPageMaxAge: Duration = Duration.ofDays(30),
                   val artistPagesPerKind: Int = 3, val versions: Boolean = true)

/** ug/fetch.SongFetchOutcome. */
data class SongFetchOutcome(val songId: Long, val sheet: Long?, val tab: Long?, val requests: Int,
                            val settled: Boolean = false, val keptVersions: List<String> = emptyList())
