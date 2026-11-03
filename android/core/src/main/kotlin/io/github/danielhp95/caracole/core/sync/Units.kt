package io.github.danielhp95.caracole.core.sync

import io.github.danielhp95.caracole.core.db.Db
import io.github.danielhp95.caracole.core.stub
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonObject
import java.io.File

/** One unit of a library's state, as peer_sync.library_state lists it. */
data class SyncUnit(val id: String, val label: String, val digest: String) {
    val kind: String get() = id.substringBefore('/')
}

/** A unit the two sides hold differently, and what the comparison proposes (mine, theirs or conflict). */
data class Difference(val id: String, val label: String, val mine: SyncUnit?, val theirs: SyncUnit?,
                      val proposal: String, val why: String)

/** A stored base: per unit, its digest (or null) and the stamp it was agreed at. */
typealias Base = Map<String, Pair<String?, String>>

/** peer_sync.py's units on the phone (lane sync-units). */
object Units {
    const val FORMAT = 2

    fun libraryState(db: Db): Map<String, SyncUnit> = TODO("lane sync-units")

    /** One unit's digest now, for the mirror's gate; null for none (and until the lane lands). */
    fun digestOf(db: Db, unitId: String): String? = stub("lane sync-units") { null }

    fun value(db: Db, unitId: String): JsonElement? = TODO("lane sync-units")

    /** As /api/peer/unit's "unit". */
    fun document(db: Db, libraryDir: File, unitId: String): JsonObject? = TODO("lane sync-units")
    fun valueOfDocument(unitId: String, doc: JsonObject?): JsonElement? = TODO("lane sync-units")
}
