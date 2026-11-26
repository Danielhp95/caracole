package io.github.danielhp95.caracole.core.index

import io.github.danielhp95.caracole.core.db.Db
import io.github.danielhp95.caracole.core.json.Canonical
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive

/**
 * What the phone holds of the computer's site indexes, as it asks the computer for the part it doesn't
 * (`POST /peer/index/newer`, index_transfer.read_have): `{"sites": [site, …], "have": {site: {"sitemaps": {name:
 * record}, "since": stamp or null}}}`.
 *
 * - **sitemaps**: the phone's own record of each sitemap it holds (UG's `ug:sitemaps`, LaCuerda's listing pages'
 *   `lacuerda:index:pages`, a site_index.py site's `<provider>:sitemaps`), each as the phone keeps it but its
 *   `checked_at`, which the computer never compares (index_transfer._unchanged: a re-check that found it unchanged
 *   moves it alone); a record that isn't an object left out (the computer sends that sitemap whole).
 * - **since**: kv [CUT_KEY]`<computer id>`'s stamp of the site, the computer's own clock as it made the last partial
 *   export of the cut asked that the phone merged (its META's `exported_at`, recorded only when that time is no later
 *   than the merge's clock bound, `notAfter`: SyncEngine.merge), null when none: a whole export (an older computer's,
 *   which notes no arrivals) is never a cut, nor is a stamp of another caracole's (a catalogue's, a file's), and the
 *   stamps of `sync:index:` aren't either (the phone's own pushed pages move them).
 */
object Have {
    /** kv: the time of each site's last partial export of the cut asked that the phone merged from a computer, by its
     * id ({site: stamp}), within the merge's clock bound: the computer's clock, as it made the file (its META
     * `exported_at`). Kept through a restore (OwnRecords' `sync:`). */
    const val CUT_KEY = "sync:cut:"

    /** The request's document for [sites] of the computer [computer] (its id). */
    fun document(db: Db, computer: String, sites: List<String>): JsonObject {
        val since = cuts(db, computer)
        return JsonObject(linkedMapOf(
            "sites" to JsonArray(sites.map(::JsonPrimitive)),
            "have" to JsonObject(sites.associateWithTo(LinkedHashMap()) { site ->
                JsonObject(linkedMapOf(
                    "sitemaps" to JsonObject(records(db, site)),
                    "since" to (since[site]?.let(::JsonPrimitive) ?: JsonNull),
                ))
            }),
        ))
    }

    /** Each site's cut of the computer [computer], kv [CUT_KEY]; none for no record, and an entry that isn't a text
     * none. */
    fun cuts(db: Db, computer: String): Map<String, String> =
        Merge.records(db, "main", CUT_KEY + computer).mapNotNull { (site, stamp) ->
            (stamp as? JsonPrimitive)?.takeIf { it.isString }?.let { site to it.content }
        }.toMap()

    /** [cuts] moved on to [exported] for [sites], every other site's as it was; its sites in code-point order. Called
     * in the merge's write, once the file is checked to be what was asked. */
    fun record(db: Db, computer: String, sites: List<String>, exported: String) {
        val now = LinkedHashMap(cuts(db, computer))
        for (site in sites) now[site] = exported
        db.kvSetJson(CUT_KEY + computer,
                     JsonObject(now.toSortedMap(Canonical.KEY_ORDER).mapValues { JsonPrimitive(it.value) }))
    }

    /** The phone's records of [site]'s sitemaps (listing pages) by name, each but its `checked_at`. */
    private fun records(db: Db, site: String): Map<String, JsonObject> {
        val key = when (site) {
            "ug" -> Merge.UG_SITEMAPS
            "lacuerda" -> Merge.LC_PAGES
            else -> Merge.sitemapsKey(site)
        }
        return Merge.records(db, "main", key).entries.mapNotNull { (name, record) ->
            (record as? JsonObject)?.let { name to JsonObject(it.filterKeys { k -> k != "checked_at" }) }
        }.toMap(LinkedHashMap())
    }

    /** Whether a partial export's [cut] is the part asked for with [asked] (this side's [document] of its sites):
     * every site asked cut, each by the `since` asked, leaving out only sitemaps the phone holds. Its words when it
     * isn't, else null. */
    fun mismatch(cut: Map<String, PartialSite>, asked: JsonObject): String? {
        val sites = (asked["sites"] as? JsonArray).orEmpty().mapNotNull { (it as? JsonPrimitive)?.content }
        val have = asked["have"] as? JsonObject
        for (site in sites) {
            val got = cut[site] ?: return "it holds no part of $site"
            val held = have?.get(site) as? JsonObject
            val since = (held?.get("since") as? JsonPrimitive)?.takeIf { it.isString }?.content
            if (got.since != since) return "its $site was cut since ${got.since}, and the phone asked since $since"
            val names = (held?.get("sitemaps") as? JsonObject)?.keys.orEmpty()
            got.same.firstOrNull { it !in names }?.let { return "it left out $site's $it, which the phone hasn't got" }
        }
        return null
    }
}
