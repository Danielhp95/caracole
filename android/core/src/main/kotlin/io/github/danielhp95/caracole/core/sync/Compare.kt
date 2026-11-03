package io.github.danielhp95.caracole.core.sync

import io.github.danielhp95.caracole.core.db.Db

/** peer_sync.py's three-way comparison (lane sync-units). */
object Compare {
    /** kv sync:id, which migration 15 makes. */
    fun ownId(db: Db): String = TODO("lane sync-units")
    fun baseOf(db: Db, peer: String): Base? = TODO("lane sync-units")
    fun mergedBase(mine: Base?, theirs: Base?): Map<String, String?>? = TODO("lane sync-units")
    fun compare(mine: Map<String, SyncUnit>, theirs: Map<String, SyncUnit>, base: Map<String, String?>?): List<Difference> =
        TODO("lane sync-units")
    fun decide(found: List<Difference>, prefer: String? = null, choose: ((Difference) -> String?)? = null): Pair<List<Difference>, List<Difference>> =
        TODO("lane sync-units")

    /** peer_sync._order. */
    fun order(found: List<Difference>): List<Difference> = TODO("lane sync-units")

    /** The SHA-256 of C([[id, proposal, here, there], …]) in order. */
    fun comparedHash(found: List<Difference>): String = TODO("lane sync-units")
    fun recordAgreement(db: Db, peer: String, mine: Map<String, SyncUnit>, theirs: Map<String, SyncUnit>, at: String): Int =
        TODO("lane sync-units")
}
