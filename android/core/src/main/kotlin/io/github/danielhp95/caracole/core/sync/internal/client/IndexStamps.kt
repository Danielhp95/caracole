package io.github.danielhp95.caracole.core.sync.internal.client

import io.github.danielhp95.caracole.core.index.Stamps
import io.github.danielhp95.caracole.core.json.Canonical
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive

/** kv `sync:index:<computer id>`: the stamp of each of the computer's site indexes the phone merged, {site: stamp},
 * each read as stamps.parse reads it (core.index.Stamps). */
internal object IndexStamps {
    /** Whether [stamp] is newer than [than]: never when it is no time (or none in years 1 to 9999 once in UTC),
     * always when [than] is. */
    fun newer(stamp: String, than: String): Boolean {
        val a = read(stamp) ?: return false
        val b = read(than) ?: return true
        return a > b
    }

    /** kv's {site: stamp}, its odd entries left out; empty for none. */
    fun sites(value: JsonElement?): Map<String, String> =
        (value as? JsonObject)?.mapNotNull { (site, stamp) -> Documents.text(stamp)?.let { site to it } }?.toMap() ?: emptyMap()

    /** {site: stamp}, its keys in code-point order, as kv text. */
    fun json(sites: Map<String, String>): JsonObject =
        JsonObject(sites.toSortedMap(Canonical.KEY_ORDER).mapValues { JsonPrimitive(it.value) })

    private fun read(text: String): Long? = try {
        Stamps.parse(text)
    } catch (_: ArithmeticException) {
        null
    }
}
