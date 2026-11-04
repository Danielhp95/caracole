package io.github.danielhp95.caracole.core.match

import io.github.danielhp95.caracole.core.config.MatchPolicy
import io.github.danielhp95.caracole.core.db.Db
import io.github.danielhp95.caracole.core.library.Overrides
import io.github.danielhp95.caracole.core.library.SongRow

/** match.MatchCandidate. */
data class MatchCandidate(val artistKey: String, val songKey: String, val score: Double?, val step: String)

/** match.MatchResult. */
data class MatchResult(val decision: String, val step: String?, val score: Double?, val artistKey: String?,
                       val songKey: String?, val candidates: List<MatchCandidate> = emptyList(),
                       val pinned: List<Long> = emptyList())

/** match.MatchChange. */
data class MatchChange(val song: SongRow, val old: String?, val new: MatchResult)

/** match.py for a lookup's song. */
object Matcher {
    fun matchAll(db: Db, overrides: Overrides, policy: MatchPolicy, songs: List<SongRow>,
                 dryRun: Boolean = false): List<MatchChange> = TODO("lane matcher")
    fun candidatesOf(song: SongRow): List<MatchCandidate> = TODO("lane matcher")
}
