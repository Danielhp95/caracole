package io.github.danielhp95.caracole.core.sync

import io.github.danielhp95.caracole.core.db.Db
import io.github.danielhp95.caracole.core.json.Canonical
import io.github.danielhp95.caracole.core.json.CanonicalError
import io.github.danielhp95.caracole.core.py.PyUnicode
import io.github.danielhp95.caracole.core.sync.internal.units.Python
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive

/**
 * peer_sync.py's three-way comparison on the phone. Once two sides have synced, each unit has a base: its digest
 * when the two last held it the same (or null, both lacking it). Each side keeps its own (kv `sync:base:<peer id>`,
 * `{"format": 2, "units": {id: [digest or null, when]}}`, [recordAgreement]) and the later of the two counts
 * ([mergedBase]). A unit only one side changed since is that side's (`mine`, `theirs`); one both changed, differently,
 * a `conflict` for the owner; with no base (a first sync), a unit on one side alone is that side's, and one both hold,
 * differently, a conflict. The words of each proposal (`why`) are Python's.
 */
object Compare {
    /** What a comparison proposes for a unit: this side's (the peer takes it), the peer's, or the owner's choice. */
    const val MINE = "mine"
    const val THEIRS = "theirs"
    const val CONFLICT = "conflict"

    private const val ID_KEY = "sync:id"
    private const val BASE_KEY = "sync:base:"
    private val KINDS = listOf("song", "removed", "songbook", "alias", "artist_url", "block")

    /** kv sync:id, which migration 15 makes; an error for a database that has none. */
    fun ownId(db: Db): String = db.kvGet(ID_KEY)?.takeIf { it.isNotEmpty() }
        ?: throw IllegalStateException("this database has no sync id (kv $ID_KEY): schema 15 makes one")

    /** What this side last agreed on with [peer], unit by unit; null if the two never synced, or synced in another
     * format (an untagged base is none, never translated), or the record isn't JSON. */
    fun baseOf(db: Db, peer: String): Base? {
        val text = db.kvGet(BASE_KEY + peer) ?: return null
        val value = try {
            Canonical.parse(text)
        } catch (e: CanonicalError) {
            return null
        }
        return readBase(value)
    }

    /** peer_sync._read_base: `{"format": 2, "units": …}`, else none. */
    internal fun readBase(value: JsonElement?): Base? {
        if (value !is JsonObject || !Python.numberEquals(value["format"], Units.FORMAT)) return null
        return readUnits(value["units"])
    }

    /** peer_sync._read_units: a base's units, its odd entries left out; null for no object. */
    internal fun readUnits(value: JsonElement?): Base? {
        if (value !is JsonObject) return null
        val read = LinkedHashMap<String, Pair<String?, String>>()
        for ((id, entry) in value) {
            if (entry !is JsonArray || entry.size != 2) continue
            val digest = entry[0]
            val at = entry[1]
            if (!(digest is JsonNull || isText(digest)) || !isText(at)) continue
            read[id] = (if (digest is JsonNull) null else (digest as JsonPrimitive).content) to (at as JsonPrimitive).content
        }
        return read
    }

    private fun isText(e: JsonElement) = e is JsonPrimitive && e.isString

    /** The base a comparison reads: for each unit, the later of the two sides' agreements on it (stamps compared as
     * text, mine on a tie); null when neither side has one. */
    fun mergedBase(mine: Base?, theirs: Base?): Map<String, String?>? {
        if (mine == null && theirs == null) return null
        val merged = LinkedHashMap<String, Pair<String?, String>>(mine ?: emptyMap())
        for ((id, entry) in theirs ?: emptyMap()) {
            val had = merged[id]
            if (had == null || Canonical.KEY_ORDER.compare(entry.second, had.second) > 0) merged[id] = entry
        }
        return merged.mapValuesTo(LinkedHashMap()) { it.value.first }
    }

    /** Every unit the two sides hold differently, with what the sync proposes for it, in [order]. */
    fun compare(mine: Map<String, SyncUnit>, theirs: Map<String, SyncUnit>, base: Map<String, String?>?): List<Difference> {
        val found = ArrayList<Difference>()
        for (id in mine.keys + theirs.keys) {
            val a = mine[id]
            val b = theirs[id]
            if (a?.digest == b?.digest) continue
            val label = (a ?: b)!!.label
            val (proposal, why) = if (base == null) {
                firstTime(a, b)
            } else {
                val was = base[id]
                val aChanged = a?.digest != was
                val bChanged = b?.digest != was
                when {
                    aChanged && !bChanged -> MINE to changed("here", a, was)
                    bChanged && !aChanged -> THEIRS to changed("there", b, was)
                    else -> CONFLICT to "both books changed it since the last share"
                }
            }
            found.add(Difference(id, label, a, b, proposal, why))
        }
        return order(found)
    }

    private fun firstTime(a: SyncUnit?, b: SyncUnit?): Pair<String, String> = when {
        b == null -> MINE to "only in our book"
        a == null -> THEIRS to "only in theirs"
        else -> CONFLICT to "in both books, different, never shared"
    }

    private fun changed(where: String, unit: SyncUnit?, was: String?): String = when {
        unit == null -> "gone $where since the last share"
        was == null -> "new $where since the last share"
        else -> "changed $where since the last share"
    }

    /** Which differences this side takes ([THEIRS]) and which the peer takes ([MINE]): each as proposed, each conflict
     * as [choose] answers it, else as [prefer] says, else left. (taken here, taken there). */
    fun decide(found: List<Difference>, prefer: String? = null, choose: ((Difference) -> String?)? = null): Pair<List<Difference>, List<Difference>> {
        val here = ArrayList<Difference>()
        val there = ArrayList<Difference>()
        for (d in found) {
            var side: String? = d.proposal
            if (side == CONFLICT) side = choose?.invoke(d)?.takeIf { it.isNotEmpty() } ?: prefer
            when (side) {
                THEIRS -> here.add(d)
                MINE -> there.add(d)
            }
        }
        return here to there
    }

    /** peer_sync._order: by kind (song, removed, songbook, alias, artist_url, block, then any other), then by label in
     * any case (casefold, code points), then by id. */
    fun order(found: List<Difference>): List<Difference> = found
        .map { d ->
            val kind = KINDS.indexOf(d.id.substringBefore('/')).let { if (it < 0) KINDS.size else it }
            Triple(kind, PyUnicode.casefold(d.label), d)
        }
        .sortedWith { x, y ->
            x.first.compareTo(y.first).takeIf { it != 0 }
                ?: Canonical.KEY_ORDER.compare(x.second, y.second).takeIf { it != 0 }
                ?: Canonical.KEY_ORDER.compare(x.third.id, y.third.id)
        }
        .map { it.third }

    /** What a comparison found, named: the SHA-256 of C([[id, proposal, here, there], …]) in [order], here and there
     * each side's digest or null. */
    fun comparedHash(found: List<Difference>): String = Canonical.digest(JsonArray(order(found).map { d ->
        JsonArray(listOf(JsonPrimitive(d.id), JsonPrimitive(d.proposal), JsonPrimitive(d.mine?.digest),
                         JsonPrimitive(d.theirs?.digest)))
    }))

    /** Keep, as agreed with [peer] at [at], every unit the two hold the same now (and those both lack that the base
     * names); the others keep what they had. The base is written as Python writes it (json.dumps of its units in
     * code-point order), byte for byte. Called inside Database.write. How many were agreed. */
    fun recordAgreement(db: Db, peer: String, mine: Map<String, SyncUnit>, theirs: Map<String, SyncUnit>, at: String): Int {
        val base = LinkedHashMap<String, Pair<String?, String>>(baseOf(db, peer) ?: emptyMap())
        var agreed = 0
        for (id in mine.keys + theirs.keys + base.keys.toList()) {
            val a = mine[id]
            val b = theirs[id]
            if (a != null && b != null && a.digest == b.digest) {
                base[id] = a.digest to at
                agreed++
            } else if (a == null && b == null) {
                base[id] = null to at
            }
        }
        val units = LinkedHashMap<String, JsonElement>()
        for (id in base.keys.sortedWith(Canonical.KEY_ORDER)) {
            val (digest, stamp) = base.getValue(id)
            units[id] = JsonArray(listOf(JsonPrimitive(digest), JsonPrimitive(stamp)))
        }
        db.kvSetJson(BASE_KEY + peer, JsonObject(linkedMapOf("format" to JsonPrimitive(Units.FORMAT), "units" to JsonObject(units))))
        return agreed
    }
}
