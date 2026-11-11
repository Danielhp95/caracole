package io.github.danielhp95.caracole.core.sync

import io.github.danielhp95.caracole.core.db.Db
import io.github.danielhp95.caracole.core.json.Canonical
import io.github.danielhp95.caracole.core.json.CanonicalError
import io.github.danielhp95.caracole.core.py.Py
import io.github.danielhp95.caracole.core.py.PyUnicode
import io.github.danielhp95.caracole.core.sync.internal.units.Python
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive

/** An answer an import remembered (peer_sync.Kept's entry): this side's digest kept, the other's not taken (null:
 * lacking it), and [at], the file's `made`. */
data class KeptEntry(val here: String?, val there: String?, val at: String)

/** The answers an import of a peer's files remembered, by unit (the base's `"kept"`). */
typealias Kept = Map<String, KeptEntry>

/** A kept answer as a comparison reads it ([Compare.mergedKept]): the digest here and there when it was kept, and
 * whose it was, [Compare.MINE] or [Compare.THEIRS]. */
data class KeptPair(val here: String?, val there: String?, val chooser: String)

/**
 * peer_sync.py's three-way comparison on the phone. Once two sides have synced, each unit has a base: its digest
 * when the two last held it the same (or null, both lacking it). Each side keeps its own (kv `sync:base:<peer id>`,
 * `{"format": 3, "units": {id: [digest or null, when]}}`, [recordAgreement]) and the later of the two counts
 * ([mergedBase]). A unit only one side changed since is that side's (`mine`, `theirs`); one both changed, differently,
 * a `conflict` for the owner; with no base (a first sync), a unit on one side alone is that side's, and one both hold,
 * differently, a conflict. The words of each proposal (`why`) are Python's.
 *
 * **The remembered answer** (the sync redesign's §3.1): a conflict an import answered "keep mine" is kept beside the
 * base ([recordKept]: its `"kept"`, `{id: [digest here, digest there, when]}`, at the file's `made`), since a file
 * can't take this side's version. The state document gives the asker the entries kept for it ([PeerState.kept]),
 * and for each unit the latest of the four records (each side's agreement and kept answer) counts, an agreement on a
 * tie ([mergedKept]); while neither side changed the unit since, it is the chooser's ([KEPT_HERE], [KEPT_THERE]),
 * never a conflict asked again. An agreement drops the kept answer of each unit it agrees on ([recordAgreement]).
 */
object Compare {
    /** What a comparison proposes for a unit: this side's (the peer takes it), the peer's, or the owner's choice. */
    const val MINE = "mine"
    const val THEIRS = "theirs"
    const val CONFLICT = "conflict"

    /** Why a unit is one side's though both hold it otherwise than the base: an import's "keep mine", remembered. */
    const val KEPT_HERE = "ours kept, as you chose when reading their file"
    const val KEPT_THERE = "theirs kept, as you chose when they read our file"

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

    /** peer_sync._read_base: `{"format": 3, "units": …}`, else none. */
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

    /** peer_sync.kept_of: the answers this side's imports of [peer]'s files remembered (the base's `"kept"`); none
     * if there are none, or the base is of another format or can't be read. */
    fun keptOf(db: Db, peer: String): Kept {
        val text = db.kvGet(BASE_KEY + peer) ?: return emptyMap()
        val value = try {
            Canonical.parse(text)
        } catch (e: CanonicalError) {
            return emptyMap()
        }
        if (value !is JsonObject || !Python.numberEquals(value["format"], Units.FORMAT)) return emptyMap()
        return readKept(value["kept"])
    }

    /** peer_sync._read_kept: `{unit: [here, there, when]}`, its odd entries left out; none for no object. */
    fun readKept(value: JsonElement?): Kept {
        if (value !is JsonObject) return emptyMap()
        val read = LinkedHashMap<String, KeptEntry>()
        for ((id, entry) in value) {
            if (entry !is JsonArray || entry.size != 3) continue
            val (here, there, at) = entry
            if (!(here is JsonNull || isText(here)) || !(there is JsonNull || isText(there)) || !isText(at)) continue
            read[id] = KeptEntry(textOrNull(here), textOrNull(there), (at as JsonPrimitive).content)
        }
        return read
    }

    private fun textOrNull(e: JsonElement): String? = if (e is JsonNull) null else (e as JsonPrimitive).content

    /** peer_sync.record_kept: remember, beside the base kept for [peer], each conflict an import of its file answered
     * "keep mine", [chosen] `{unit: (this side's digest, the file's)}`, at [at], the file's `made`; a unit kept before
     * takes the new answer. The base's units stay as they are, and none answered writes nothing. Called inside
     * Database.write. How many were recorded. */
    fun recordKept(db: Db, peer: String, chosen: Map<String, Pair<String?, String?>>, at: String): Int {
        if (chosen.isEmpty()) return 0
        val base = baseOf(db, peer) ?: emptyMap()
        val kept = LinkedHashMap(keptOf(db, peer))
        for ((id, pair) in chosen) kept[id] = KeptEntry(pair.first, pair.second, at)
        writeBase(db, peer, base, kept)
        return chosen.size
    }

    /** peer_sync.merged_kept: the kept answers a comparison reads. For each unit either side kept an answer for, the
     * latest of the four records by when (code-point order, so the latest sorts last): this side's agreement, the
     * other's, this side's kept answer, the other's, the earlier of them on a tie. A unit whose latest record is a
     * kept answer comes back as a [KeptPair]: this side's as stored, [MINE]'s; the other's with its two digests
     * swapped, [THEIRS]'s. By unit id, in code-point order. */
    fun mergedKept(mine: Base?, mineKept: Kept, theirs: Base?, theirsKept: Kept): Map<String, KeptPair> {
        val merged = LinkedHashMap<String, KeptPair>()
        for (id in (mineKept.keys + theirsKept.keys).sortedWith(Canonical.KEY_ORDER)) {
            val records = ArrayList<Pair<String, KeptPair?>>()
            for (agreed in listOf(mine, theirs)) agreed?.get(id)?.let { records.add(it.second to null) }
            mineKept[id]?.let { records.add(it.at to KeptPair(it.here, it.there, MINE)) }
            theirsKept[id]?.let { records.add(it.at to KeptPair(it.there, it.here, THEIRS)) }
            var latest = records.first()
            for (record in records.drop(1)) if (Py.CODE_POINT_ORDER.compare(record.first, latest.first) > 0) latest = record
            latest.second?.let { merged[id] = it }
        }
        return merged
    }

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

    /** Every unit the two sides hold differently, with what the sync proposes for it, in [order]. A unit [kept]
     * names ([mergedKept]) is compared with the two versions kept, whatever the base says: changed on neither side
     * since, the chooser's ([KEPT_HERE], [KEPT_THERE]); else as usual. */
    fun compare(mine: Map<String, SyncUnit>, theirs: Map<String, SyncUnit>, base: Map<String, String?>?,
                kept: Map<String, KeptPair>? = null): List<Difference> {
        val found = ArrayList<Difference>()
        for (id in mine.keys + theirs.keys) {
            val a = mine[id]
            val b = theirs[id]
            if (a?.digest == b?.digest) continue
            val label = (a ?: b)!!.label
            val pair = kept?.get(id)
            val (proposal, why) = if (pair != null) {
                sinceKept(a, b, pair)
            } else if (base == null) {
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

    private fun sinceKept(a: SyncUnit?, b: SyncUnit?, pair: KeptPair): Pair<String, String> {
        val aChanged = a?.digest != pair.here
        val bChanged = b?.digest != pair.there
        return when {
            !aChanged && !bChanged -> if (pair.chooser == MINE) MINE to KEPT_HERE else THEIRS to KEPT_THERE
            aChanged && !bChanged -> MINE to changed("here", a, pair.here)
            bChanged && !aChanged -> THEIRS to changed("there", b, pair.there)
            else -> CONFLICT to "both books changed it since the last share"
        }
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
     * names or an answer was kept for), dropping the kept answer of each ([recordKept]); the others keep what they
     * had. The base is written as Python writes it (json.dumps of its units, then of its kept answers when there are
     * any, each in code-point order), byte for byte. Called inside Database.write. How many were agreed. */
    fun recordAgreement(db: Db, peer: String, mine: Map<String, SyncUnit>, theirs: Map<String, SyncUnit>, at: String): Int {
        val base = LinkedHashMap<String, Pair<String?, String>>(baseOf(db, peer) ?: emptyMap())
        val kept = LinkedHashMap(keptOf(db, peer))
        var agreed = 0
        for (id in mine.keys + theirs.keys + base.keys.toList() + kept.keys.toList()) {
            val a = mine[id]
            val b = theirs[id]
            if (a != null && b != null && a.digest == b.digest) {
                base[id] = a.digest to at
                kept.remove(id)
                agreed++
            } else if (a == null && b == null) {
                base[id] = null to at
                kept.remove(id)
            }
        }
        writeBase(db, peer, base, kept)
        return agreed
    }

    /** peer_sync._write_base: `{"format": FORMAT, "units": …}` and, when there are any, `"kept": …`, each by unit id
     * in code-point order. */
    internal fun writeBase(db: Db, peer: String, base: Map<String, Pair<String?, String>>, kept: Kept) {
        val units = LinkedHashMap<String, JsonElement>()
        for (id in base.keys.sortedWith(Canonical.KEY_ORDER)) {
            val (digest, stamp) = base.getValue(id)
            units[id] = JsonArray(listOf(JsonPrimitive(digest), JsonPrimitive(stamp)))
        }
        val stored = linkedMapOf<String, JsonElement>("format" to JsonPrimitive(Units.FORMAT), "units" to JsonObject(units))
        if (kept.isNotEmpty()) {
            stored["kept"] = JsonObject(kept.keys.sortedWith(Canonical.KEY_ORDER).associateWithTo(LinkedHashMap()) { id ->
                val entry = kept.getValue(id)
                JsonArray(listOf(JsonPrimitive(entry.here), JsonPrimitive(entry.there), JsonPrimitive(entry.at)))
            })
        }
        db.kvSetJson(BASE_KEY + peer, JsonObject(stored))
    }
}
