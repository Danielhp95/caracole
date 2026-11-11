package io.github.danielhp95.caracole.server.routes.library

import io.github.danielhp95.caracole.core.db.Db
import io.github.danielhp95.caracole.core.py.Py
import io.github.danielhp95.caracole.core.sync.Comparison
import io.github.danielhp95.caracole.core.sync.Scope
import io.github.danielhp95.caracole.core.sync.SyncEngine
import io.github.danielhp95.caracole.core.sync.SyncOutcome
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.contentOrNull

/** The Sync tab's documents (the sync redesign's §3.4.1; sync.js reads them), on the phone as caracole serve writes
 * them (web/sync_routes.py). */
internal object SyncJson {
    private fun text(value: String?): JsonElement = value?.let(::JsonPrimitive) ?: JsonNull

    private fun texts(values: List<String>): JsonArray = JsonArray(values.map(::JsonPrimitive))

    /**
     * POST /sync/compare's answer (sync_routes.compare): the comparison's id; the other side, `kind` the comparison's
     * ("computer" on the phone, where caracole serve says "server"), `made` null; when the two last agreed (null:
     * never); the parts the other side holds; each difference with its kind, its proposal, why, each side's digest,
     * a song's names (Scope.namesOf; null for another kind), what each side did since the two last agreed
     * (Scope.changeOf), its part (Scope.partOf) and the songbooks that list it; each songbook difference's two
     * documents; and each site whose newest read differs.
     */
    fun comparison(c: Comparison): JsonObject = JsonObject(linkedMapOf(
        "comparison" to JsonPrimitive(c.id),
        "peer" to JsonObject(linkedMapOf(
            "address" to JsonPrimitive(c.address), "server" to text(c.peer.server),
            "caracole" to JsonPrimitive(c.peer.caracole), "name" to JsonPrimitive(c.peer.name),
            "kind" to JsonPrimitive(c.kind), "made" to JsonNull,
        )),
        "synced_before" to text(c.syncedBefore),
        "holds" to texts(c.holds),
        "differences" to JsonArray(c.differences.map { d ->
            val names = Scope.namesOf(d.id, d.label)
            val (here, there) = Scope.changeOf(d, c.base, c.kept)
            JsonObject(linkedMapOf(
                "id" to JsonPrimitive(d.id), "label" to JsonPrimitive(d.label),
                "kind" to JsonPrimitive(d.id.substringBefore('/')), "proposal" to JsonPrimitive(d.proposal),
                "why" to JsonPrimitive(d.why), "here" to text(d.mine?.digest), "there" to text(d.theirs?.digest),
                "names" to (names?.let { (artist, title) ->
                    JsonObject(linkedMapOf("artist" to JsonPrimitive(artist), "title" to JsonPrimitive(title)))
                } ?: JsonNull),
                "change" to JsonArray(listOf(text(here), text(there))),
                "part" to text(Scope.partOf(d.id)),
                "with" to texts(c.listed[d.id].orEmpty()),
            ))
        }),
        "songbooks" to JsonObject(c.songbooks.entries.associateTo(LinkedHashMap()) { (id, docs) ->
            id to JsonObject(linkedMapOf("here" to (docs.first ?: JsonNull), "there" to (docs.second ?: JsonNull)))
        }),
        "indexes" to JsonArray(c.indexes.map { w ->
            JsonObject(linkedMapOf(
                "site" to JsonPrimitive(w.site), "title" to JsonPrimitive(w.title), "here" to text(w.here),
                "there" to text(w.there), "newer" to JsonPrimitive(w.newer),
            ))
        }),
    ))

    /** A sync job's outcome: the units taken here, given there, left (with why), how many the two agree on, the
     * indexes merged, and the sync's report (the sync redesign's §3.5) when there is one, as jobs_routes.peer_outcome
     * adds it. */
    fun outcome(o: SyncOutcome): JsonObject = JsonObject(linkedMapOf<String, JsonElement>(
        "taken" to texts(o.taken),
        "given" to texts(o.given),
        "left" to JsonArray(o.left.map { (id, why) -> JsonArray(listOf(JsonPrimitive(id), JsonPrimitive(why))) }),
        "agreed" to JsonPrimitive(o.agreed),
        "indexed" to texts(o.indexed),
    ).apply { o.report?.let { put("report", it) } })

    /** The computers this phone synced with (kv `sync:peer:<id>`, which a sync's agree writes), the last first:
     * [{address, server, name, synced_at}]. A record that can't be read, or names no address, is left out. */
    fun peers(db: Db): JsonArray {
        val rows = db.query("SELECT key, value FROM kv WHERE key >= ? AND key < ? ORDER BY key",
                            SyncEngine.PEER_KEY, SyncEngine.PEER_KEY.dropLast(1) + ";") { it.text(0)!! to it.text(1) }
        val peers = rows.mapNotNull { (key, value) ->
            val record = record(value) ?: return@mapNotNull null
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

    /** sync_routes._synced_at: when this phone last synced with [server], as kv `sync:peer:<id>` records it; null for
     * never, or a record that can't be read. */
    fun syncedAt(db: Db, server: String): String? =
        (record(db.kvGet(SyncEngine.PEER_KEY + server))?.get("synced_at") as? JsonPrimitive)
            ?.takeIf { it.isString }?.contentOrNull

    /** A kv record's JSON object; null for none, or text that isn't one. */
    private fun record(value: String?): JsonObject? = try {
        value?.let { Json.parseToJsonElement(it) } as? JsonObject
    } catch (e: IllegalArgumentException) {
        null
    }
}
