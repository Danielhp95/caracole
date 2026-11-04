package io.github.danielhp95.caracole.core.lyrics

import io.github.danielhp95.caracole.core.db.Db
import io.github.danielhp95.caracole.core.http.Client
import io.github.danielhp95.caracole.core.library.LibraryStore
import io.github.danielhp95.caracole.core.library.PassStats
import java.time.Instant

/** lyrics.LyricsStats: what one `fetch_pending_lyrics` pass did, and what LRCLIB answered. */
class LyricsStats(var found: Int = 0, var missing: Int = 0, var instrumental: Int = 0) : PassStats()

/** lyrics.py's pass for a lookup's song: LRCLIB's lyrics. */
object Lrclib {
    fun fetchPendingLyrics(db: Db, client: Client, lib: LibraryStore, now: Instant, only: Set<Long>): LyricsStats =
        TODO("lane lyrics")
}
