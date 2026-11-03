package io.github.danielhp95.caracole.core.sync

import io.github.danielhp95.caracole.core.db.Database
import io.github.danielhp95.caracole.core.library.LibraryStore
import java.io.File

enum class Side { HERE, THERE, SKIP }

/** A comparison with the computer, kept by [id] for 10 minutes. */
data class Comparison(val id: String, val address: String, val peer: PeerState, val syncedBefore: Boolean,
                      val differences: List<Difference>, val hash: String)

data class SyncOutcome(val taken: List<String>, val given: List<String>, val left: List<Pair<String, String>>,
                       val agreed: Int, val indexed: List<String>)

/** The phone's sync: compare, take, give, mirror, agree, index (lane sync-client). */
class SyncEngine(val database: Database, val store: LibraryStore, val stateDir: File,
                 val client: (String) -> PeerClient, val mirrorRefresh: (suspend (String) -> Unit)?) {
    fun compare(address: String): Comparison = TODO("lane sync-client")

    suspend fun apply(c: Comparison, choices: Map<String, Side>, prefer: Side?,
                      stage: (name: String, state: String, detail: String) -> Unit): SyncOutcome = TODO("lane sync-client")
}
