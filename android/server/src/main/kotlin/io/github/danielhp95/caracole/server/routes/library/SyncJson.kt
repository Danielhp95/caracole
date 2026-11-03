package io.github.danielhp95.caracole.server.routes.library

import io.github.danielhp95.caracole.core.db.Db
import io.github.danielhp95.caracole.core.py.Py
import io.github.danielhp95.caracole.core.sync.Comparison
import io.github.danielhp95.caracole.core.sync.SyncEngine
import io.github.danielhp95.caracole.core.sync.SyncOutcome
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.contentOrNull

/** The Sync tab's documents (the plan's §5.3; sync.js reads them), on the phone as caracole serve writes them. */
internal object SyncJson {
    private fun text(value: String?): JsonElement = value?.let(::JsonPrimitive) ?: JsonNull

    /** POST /sync/compare's answer: the comparison's id, the other side, whether the two synced before, and each
     * difference with its kind, its proposal, why, and each side's digest. */
    fun comparison(c: Comparison): JsonObject = JsonObject(linkedMapOf(
        "comparison" to JsonPrimitive(c.id),
        "peer" to JsonObject(linkedMapOf(
            "address" to JsonPrimitive(c.address), "server" to text(c.peer.server),
            "caracole" to JsonPrimitive(c.peer.caracole), "name" to JsonPrimitive(c.peer.name),
        )),
        "synced_before" to JsonPrimitive(c.syncedBefore),
        "differences" to JsonArray(c.differences.map { d ->
            JsonObject(linkedMapOf(
                "id" to JsonPrimitive(d.id), "label" to JsonPrimitive(d.label),
                "kind" to JsonPrimitive(d.id.substringBefore('/')), "proposal" to JsonPrimitive(d.proposal),
                "why" to JsonPrimitive(d.why), "here" to text(d.mine?.digest), "there" to text(d.theirs?.digest),
            ))
        }),
    ))

    /** A sync job's outcome: the units taken here, given there, left (with why), how many the two agree on, and the
     * indexes merged. */
    fun outcome(o: SyncOutcome): JsonObject = JsonObject(linkedMapOf(
        "taken" to JsonArray(o.taken.map(::JsonPrimitive)),
        "given" to JsonArray(o.given.map(::JsonPrimitive)),
        "left" to JsonArray(o.left.map { (id, why) -> JsonArray(listOf(JsonPrimitive(id), JsonPrimitive(why))) }),
        "agreed" to JsonPrimitive(o.agreed),
        "indexed" to JsonArray(o.indexed.map(::JsonPrimitive)),
    ))

    /** The computers this phone synced with (kv `sync:peer:<id>`, which a sync's agree writes), the last first:
     * [{address, server, name, synced_at}]. A record that can't be read, or names no address, is left out. */
    fun peers(db: Db): JsonArray {
        val rows = db.query("SELECT key, value FROM kv WHERE key >= ? AND key < ? ORDER BY key",
                            SyncEngine.PEER_KEY, SyncEngine.PEER_KEY.dropLast(1) + ";") { it.text(0)!! to it.text(1) }
        val peers = rows.mapNotNull { (key, value) ->
            val record = try {
                value?.let { Json.parseToJsonElement(it) } as? JsonObject
            } catch (e: IllegalArgumentException) {
                null
            } ?: return@mapNotNull null
            fun field(name: String) = (record[name] as? JsonPrimitive)?.takeIf { it.isString }?.contentOrNull
            val address = field("address")?.takeIf { it.isNotEmpty() } ?: return@mapNotNull null
            JsonObject(linkedMapOf(
                "address" to JsonPrimitive(address), "server" to JsonPrimitive(key.removePrefix(SyncEngine.PEER_KEY)),
                "name" to JsonPrimitive(field("name") ?: ""), "synced_at" to text(field("synced_at")),
            ))
        }
        val at = { p: JsonObject -> (p["synced_at"] as? JsonPrimitive)?.contentOrNull ?: "" }
        return JsonArray(peers.sortedWith { a, b -> Py.CODE_POINT_ORDER.compare(at(b), at(a)) })
    }
}
