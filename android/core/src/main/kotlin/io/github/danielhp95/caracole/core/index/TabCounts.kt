package io.github.danielhp95.caracole.core.index

import io.github.danielhp95.caracole.core.db.Db

/**
 * index_transfer.tab_counts on the phone: the tabs each site's index tracks, the rows of its first table
 * (IndexTransfer's sites: UG's `ug_index`, LaCuerda's `lacuerda_index`, …), which a sync's report counts before and
 * after it merges an index (the sync redesign's §3.5) and `GET /api/sync/indexes` answers.
 */
object TabCounts {
    /** Each site's rows of its first table, in caracole's order. */
    fun of(db: Db): Map<String, Long> = Sites.ALL.associateTo(LinkedHashMap()) { site ->
        site.name to db.one("SELECT COUNT(*) FROM main.${site.tables.first()}") { it.long(0)!! }!!
    }
}
