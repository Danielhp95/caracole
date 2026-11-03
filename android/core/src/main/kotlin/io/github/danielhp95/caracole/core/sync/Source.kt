package io.github.danielhp95.caracole.core.sync

import kotlinx.serialization.json.JsonObject

/** Where a take reads the units and files it takes: the computer (PeerClient), or a test's fake. */
interface UnitSource {
    /** The unit's document, as /api/peer/unit's "unit"; null when the other side holds none. */
    fun unit(id: String): JsonObject?

    /** A file of a song the unit names, checked against [sha256] by the caller. */
    fun file(songKey: String, name: String, sha256: String): ByteArray
}
