package io.github.danielhp95.caracole.core.sync.file

import io.github.danielhp95.caracole.core.sync.Base
import io.github.danielhp95.caracole.core.sync.Compare
import io.github.danielhp95.caracole.core.sync.Kept
import io.github.danielhp95.caracole.core.sync.PeerState
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import java.io.File

/**
 * peer_file.SyncFile on the phone: a `.caracole` file read back (SyncFiles.read): its path, its manifest, its state
 * (null for an index export), the bases it keeps (`{peer id: {"units", "kept"}}`), the parts it holds ([holds]: its
 * manifest's, the indexes only when its schema is this database's) and whether it is an index export alone
 * ([indexOnly]). It holds no open file.
 */
class SyncFile(val file: File, val manifest: JsonObject, val state: PeerState?, val bases: JsonObject,
               val holds: List<String>, val indexOnly: Boolean) {
    /** The id of the caracole that made it (kv `sync:id`); null for an index export. */
    val id: String? get() = text("id")?.takeIf { ID.matches(it) }

    /** The name of the library it is of; an index export's own file name. */
    val name: String get() = text("name") ?: ""

    /** When it was made, a stamp. */
    val made: String? get() = text("made")

    /** What the file's caracole last agreed on with [peer] (null: never) and the answers it kept for it, as
     * Compare.baseOf and keptOf read them there: here the file's, there [peer]'s. */
    fun baseFor(peer: String?): Pair<Base?, Kept> {
        val entry = peer?.let { bases[it] } as? JsonObject ?: return null to emptyMap()
        return Compare.readUnits(entry["units"]) to Compare.readKept(entry["kept"])
    }

    private fun text(name: String): String? = (manifest[name] as? JsonPrimitive)?.takeIf { it.isString }?.content

    private companion object {
        val ID = Regex("[0-9a-f]{16}")
    }
}
