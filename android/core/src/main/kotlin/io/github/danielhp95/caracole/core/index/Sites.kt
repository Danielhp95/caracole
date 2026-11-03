package io.github.danielhp95.caracole.core.index

/** index_transfer.Site: a site's index, its name (`--site`), its name for people, its tables, and the kv records of
 * its progress (tests/conformance/vectors/index/sites.jsonl). */
internal class Site(val name: String, val title: String, val tables: List<String>, val kv: List<String>)

/** index_transfer.SITES, in caracole's order. */
internal object Sites {
    val ALL: List<Site> = listOf(
        Site("ug", "Ultimate Guitar", listOf("ug_index", "ug_artist_tabs"),
             listOf(Merge.UG_SITEMAPS, Merge.UG_LISTED, Merge.UG_BUILT, Merge.UG_REFRESHED, Merge.UG_TAB_KEYS)),
        Site("lacuerda", "LaCuerda", listOf("lacuerda_index"),
             listOf(Merge.LC_PAGES, Merge.LC_COMPLETE, Merge.LC_KEYS)),
        Site("gtptabs", "gtptabs.com", listOf("gtptabs_index"), sitemaps("gtptabs")),
        Site("musescore", "MuseScore", listOf("musescore_index"), sitemaps("musescore")),
        Site("harptabs", "harptabs.com", listOf("harptabs_index", "harptabs_artists", "harptabs_artist_tabs"),
             sitemaps("harptabs") + listOf(Merge.HARP_ROW_KEYS, Merge.HARP_SONG_KEYS)),
        Site("gametabs", "gametabs.net", listOf("gametabs_index", "gametabs_games", "gametabs_game_tabs"),
             sitemaps("gametabs") + Merge.GAME_TITLE_KEYS),
    )

    fun named(name: String): Site? = ALL.firstOrNull { it.name == name }

    /** site_index.Site's `sitemaps_key` and `complete_key`. */
    private fun sitemaps(provider: String) = listOf(Merge.sitemapsKey(provider), Merge.completeKey(provider))
}
