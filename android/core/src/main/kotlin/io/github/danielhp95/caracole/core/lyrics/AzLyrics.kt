package io.github.danielhp95.caracole.core.lyrics

import io.github.danielhp95.caracole.core.db.Db
import io.github.danielhp95.caracole.core.http.Client
import io.github.danielhp95.caracole.core.library.LibraryStore
import io.github.danielhp95.caracole.core.library.Overrides
import io.github.danielhp95.caracole.core.library.PassStats
import java.time.Instant

/** azlyrics_fetch.AzLyricsStats. */
class AzLyricsStats(var found: Int = 0, var missing: Int = 0) : PassStats()

/** azlyrics_fetch.py's pass for a lookup's song. */
object AzLyrics {
    fun azlyricsLyrics(db: Db, client: Client, lib: LibraryStore, now: Instant, overrides: Overrides,
                       only: Set<Long>): AzLyricsStats = TODO("lane lyrics")
}
