package io.github.danielhp95.caracole.core.index

import io.github.danielhp95.caracole.core.db.Db
import io.github.danielhp95.caracole.core.json.Canonical
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive

/**
 * kv [KEY] (`index:merged`), the phone's own: each site's newest read of the whole index exports the phone merged
 * (a sync's download from the computer, a `.caracole` file's indexes, the site catalogues, an index imported),
 * `{site: stamp}`, each site's the latest of every merge's. Each is what the file read (Merged.newest), never the
 * phone's own newest, which its lookups' reads move: the phone holds every record of that site's that the computer
 * held as of it. A sync's index stage asks the computer for a site only once the computer's newest read is later than
 * this, and than what it took of that computer last (SyncEngine). Written in the merge's write; kept through a
 * restore (OwnRecords), as the index tables are.
 */
object MergedIndexes {
    const val KEY = "index:merged"

    /** Each site's stamp; none for no record, and an entry that isn't a text none. */
    fun of(db: Db): Map<String, String> =
        Merge.records(db, "main", KEY).mapNotNull { (site, stamp) ->
            (stamp as? JsonPrimitive)?.takeIf { it.isString }?.let { site to it.content }
        }.toMap()

    /** What [merged] read of each site recorded, a site's stamp moved on to it only where it is later (an older file
     * never moves one back), every other site's as it was; its sites in code-point order, written only when it
     * changes. Called in the merge's write. */
    fun record(db: Db, merged: Merged) {
        val had = of(db)
        val now = LinkedHashMap(had)
        for ((site, stamp) in merged.newest) {
            val was = had[site]
            if (was == null || later(stamp, was)) now[site] = stamp
        }
        if (now == had) return
        db.kvSetJson(KEY, JsonObject(now.toSortedMap(Canonical.KEY_ORDER).mapValues { JsonPrimitive(it.value) }))
    }

    /** Whether [stamp] is a later time than [than]: never when it is no time, always when [than] is none. */
    private fun later(stamp: String, than: String): Boolean {
        val a = read(stamp) ?: return false
        val b = read(than) ?: return true
        return a > b
    }

    private fun read(text: String): Long? = try {
        Stamps.parse(text)
    } catch (_: ArithmeticException) {
        null
    }
}
