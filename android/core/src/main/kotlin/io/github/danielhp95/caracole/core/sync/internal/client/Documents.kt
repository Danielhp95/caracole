package io.github.danielhp95.caracole.core.sync.internal.client

import io.github.danielhp95.caracole.core.sync.Base
import io.github.danielhp95.caracole.core.sync.PeerState
import io.github.danielhp95.caracole.core.sync.SyncUnit
import io.github.danielhp95.caracole.core.sync.Units
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.contentOrNull

/** The computer's sync documents read as peer_sync.py reads another side's (read_state_document, _read_units). */
internal object Documents {
    /** A state document that isn't one this side reads: why, in words peer_sync's StateError says. */
    class Unreadable(message: String) : Exception(message)

    /** A text value, or null for anything else (a number, null, an object). */
    fun text(e: JsonElement?): String? = (e as? JsonPrimitive)?.takeIf { it.isString }?.content

    /** Whether [e] is the number [n], as Python's `==` compares a JSON number with an int (2.0 is 2). */
    fun isNumber(e: JsonElement?, n: Int): Boolean {
        val p = e as? JsonPrimitive ?: return false
        if (p.isString || p is JsonNull) return false
        val content = p.contentOrNull ?: return false
        if (content == "true" || content == "false") return false
        return content.toBigDecimalOrNull()?.let { it.compareTo(n.toBigDecimal()) == 0 } ?: false
    }

    /** read_state_document, with the form token, the computer's clock, its indexes' stamps and its settings (a
     * member that isn't an object is none, as from a computer older than them: the phone's stay as they were). */
    fun state(data: JsonElement): PeerState {
        if (data !is JsonObject || !isNumber(data["format"], Units.FORMAT)) {
            throw Unreadable("not a caracole sync state of format ${Units.FORMAT} (the other caracole may be of " +
                             "another version)")
        }
        val server = data["server"]
        val units = data["units"]
        val serverId = text(server)
        if (!(server == null || server is JsonNull || (serverId != null && serverId.isNotEmpty())) || units !is JsonObject) {
            throw Unreadable("a sync state with no units, or a server id that can't be read")
        }
        val read = LinkedHashMap<String, SyncUnit>()
        for ((id, unit) in units) {
            val label = text((unit as? JsonObject)?.get("label"))
            val digest = text((unit as? JsonObject)?.get("digest"))
            if ('/' !in id || label == null || digest == null) {
                throw Unreadable("a unit that can't be read: '${id.take(80)}'")
            }
            read[id] = SyncUnit(id, label, digest)
        }
        val version = data["caracole"].let { if (it == null || it is JsonNull) null else text(it) ?: it.toString() }
        val name = data["name"].let { if (it == null || it is JsonNull) null else text(it) ?: it.toString() }
        val indexes = LinkedHashMap<String, String>()
        (data["indexes"] as? JsonObject)?.forEach { (site, stamp) -> text(stamp)?.let { indexes[site] = it } }
        return PeerState(
            format = Units.FORMAT, server = serverId, caracole = version?.ifEmpty { null } ?: "?", name = name ?: "",
            now = text(data["now"]), units = read, base = base(data["base"]),
            token = text(data["token"]) ?: "", indexes = indexes, settings = data["settings"] as? JsonObject,
        )
    }

    /** _read_units: `{unit: [digest or null, when]}`, its odd entries left out; null for no mapping. */
    fun base(value: JsonElement?): Base? {
        if (value !is JsonObject) return null
        val read = LinkedHashMap<String, Pair<String?, String>>()
        for ((id, entry) in value) {
            if (entry !is JsonArray || entry.size != 2) continue
            val digest = entry[0]
            val at = text(entry[1]) ?: continue
            when {
                digest is JsonNull -> read[id] = null to at
                text(digest) != null -> read[id] = text(digest) to at
            }
        }
        return read
    }

    /** A query's value, percent-encoded as UTF-8: every byte but RFC 3986's unreserved ones. */
    fun quote(value: String): String = buildString {
        for (b in value.toByteArray(Charsets.UTF_8)) {
            val c = b.toInt() and 0xff
            if (c in 'A'.code..'Z'.code || c in 'a'.code..'z'.code || c in '0'.code..'9'.code || c == '-'.code ||
                c == '.'.code || c == '_'.code || c == '~'.code) {
                append(c.toChar())
            } else {
                append('%').append(HEX[c shr 4]).append(HEX[c and 15])
            }
        }
    }

    private const val HEX = "0123456789ABCDEF"
}
