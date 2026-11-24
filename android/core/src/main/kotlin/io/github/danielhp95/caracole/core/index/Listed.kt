package io.github.danielhp95.caracole.core.index

import io.github.danielhp95.caracole.core.db.Db
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive

/**
 * How fresh a phone's site indexes are by their sitemap and listing records alone, whoever merged them (a `.caracole`
 * file's indexes, an index import, the catalogues, a sync): the phone app's Settings row for a phone that imported no
 * catalogue and synced with no computer. IndexTransfer.newest reads these records too, and the pages each site's index
 * holds a read of, among them the pages a phone reads itself (a lookup's UG artist page, an artist's Songs on
 * harptabs.com, a game page, a directory artist's page), which say nothing of how old the rest is: those are left out
 * here.
 */
object ListedIndexes {
    /**
     * The newest of: UG's sitemaps' records (`indexed_at`), its index's refresh and build, its directory's listings
     * (each artist's `seen_at`, each letter's round `started` and `done`); LaCuerda's listing pages' records
     * (`checked_at`) and their reading whole; and each other site's sitemaps' records (`checked_at`) and their reading
     * whole. As stored ("2026-10-28T03:30:00Z"); none when no record holds a time.
     */
    fun newest(db: Db): String? {
        fun kv(key: String) = Merge.kv(db, "main", key)
        fun recorded(key: String, field: String) = Merge.records(db, "main", key).values.mapNotNull { record ->
            ((record as? JsonObject)?.get(field) as? JsonPrimitive)?.takeIf { it.isString }?.content
        }
        val seen = db.one("SELECT MAX(seen_at), typeof(MAX(seen_at)) FROM main.ug_directory") {
            if (it.text(1) == "text") it.text(0) else null
        }
        // The sites of a site_index (their sitemaps' record and its reading whole), UG's own records apart.
        val sitemapped = Sites.ALL.filter { it.name != "ug" && Merge.sitemapsKey(it.name) in it.kv }.map { it.name }
        val times = recorded(Merge.UG_SITEMAPS, "indexed_at") + listOf(kv(Merge.UG_REFRESHED), kv(Merge.UG_BUILT), seen) +
            recorded(Merge.UG_DIR_LETTERS, "started") + recorded(Merge.UG_DIR_LETTERS, "done") +
            recorded(Merge.LC_PAGES, "checked_at") + kv(Merge.LC_COMPLETE) +
            sitemapped.flatMap { recorded(Merge.sitemapsKey(it), "checked_at") + kv(Merge.completeKey(it)) }
        val latest = times.mapNotNull { stamp ->
            try {
                Stamps.parse(stamp)
            } catch (e: ArithmeticException) {
                null  // a time out of range: none
            }
        }.maxOrNull() ?: return null
        return Stamps.stamp(latest)
    }
}
