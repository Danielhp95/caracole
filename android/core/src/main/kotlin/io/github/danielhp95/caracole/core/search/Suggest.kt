package io.github.danielhp95.caracole.core.search

import io.github.danielhp95.caracole.core.db.Db
import io.github.danielhp95.caracole.core.keys.Normalize
import io.github.danielhp95.caracole.core.search.internal.suggest.Close
import io.github.danielhp95.caracole.core.search.internal.suggest.Titles
import io.github.danielhp95.caracole.core.search.internal.suggest.Weighed

/**
 * search.py's "Did you mean" (lane search-suggest): for a query nothing matches well, the artists whose names are
 * spelled close to it ([suggestArtists]) and the songs whose titles are ([suggestTitles]), from the Ultimate Guitar
 * index's words (`ug_artist_words`, `ug_index_fts`, `ug_key_words` through [Vocabulary]), LaCuerda's listings and
 * harptabs.com's sitemap and artist pages, ranked together ([suggestions]); never a site, and nothing for Chinese.
 * Every answer is search.py's over the same rows (tests/conformance/vectors/search/suggest.jsonl). It runs inside
 * Database.read.
 */
object Suggest {
    /** suggest_artists: the artists whose name is spelled close to [q], from the Ultimate Guitar index and, with
     * [lacuerda], LaCuerda's, and with [harptabs], harptabs.com's, ranked together, up to [limit]. */
    fun suggestArtists(db: Db, q: String, limit: Int = 3, lacuerda: Boolean = true, harptabs: Boolean = true): List<Suggestion> {
        val words = Close.suggestible(q) ?: return emptyList()
        return Close.cut(Close.artistSuggestions(db, words, lacuerda, harptabs), limit).map { it.second }
    }

    /** suggest_titles: the songs whose title is spelled close to [q], each under its artist, the song on each index
     * that has it in its hits (with [gtptabs], gtptabs.com's page of it too), up to [limit]. */
    fun suggestTitles(
        db: Db, q: String, limit: Int = 3, lacuerda: Boolean = true, harptabs: Boolean = true, gtptabs: Boolean = true,
    ): List<Suggestion> {
        val words = Close.suggestible(q) ?: return emptyList()
        return Close.cut(Titles.suggestions(db, words, lacuerda, harptabs, gtptabs), limit).map { it.second }
    }

    /**
     * suggestions: [suggestArtists] and [suggestTitles] for a query nothing matches well, as the pages offer them,
     * ranked together, at most three in all; none when the Ultimate Guitar index ([index], Search.findIndex's answer)
     * or another site's ([sites]: SiteArtists and SiteHits, LaCuerda's, gtptabs.com's, MuseScore's and harptabs.com's
     * as /api/search hands them) leaves no room for one.
     */
    fun suggestions(
        db: Db, q: String, index: IndexFound, sites: List<Any> = emptyList(), lacuerda: Boolean = true,
        harptabs: Boolean = true, gtptabs: Boolean = true,
    ): List<Suggestion> {
        if (noRoom(index, sites)) return emptyList()
        val words = Close.suggestible(q) ?: return emptyList()
        // The artists shown: one suggested has more songs than any of them, and is none of them.
        val shown = index.artists.map { key(it.artist) to it.songs } + sites.filterIsInstance<SiteArtist>().map { key(it.artist) to it.songs }
        val most = shown.maxOfOrNull { it.second } ?: 0
        val names = shown.mapTo(HashSet()) { it.first }
        val artists = Close.cut(Close.artistSuggestions(db, words, lacuerda, harptabs))
            .filter { it.second.songs > most && key(it.second.artist) !in names }
        val titled = index.songs.any { it.score >= SearchLimits.STRONG && it.via != "artist" }
        val titles = if (titled) emptyList() else unshownTitles(db, words, index, sites, lacuerda, harptabs, gtptabs)
        return Close.cut(artists + titles).map { it.second }
    }

    private fun key(name: String): String = Normalize.compact(Close.nameWordsKey(name))

    /** _no_room: an artist whose whole name the query is, or a name near it, on the Ultimate Guitar index or another
     * site's; a song whose title (or title and artist) the query is whole; any page of MuseScore's. */
    private fun noRoom(index: IndexFound, sites: List<Any>): Boolean {
        if (index.artists.any { !it.part }) return true
        if (index.songs.any { it.score >= 100 && it.via != "artist" }) return true
        for (h in sites) {
            when (h) {
                is SiteArtist -> if (h.score > SearchLimits.PART && !h.part) return true // a part tops out at PART
                is SiteHit -> if (h.source == "musescore" || (h.score >= 100 && h.via != "artist")) return true
                else -> throw IllegalArgumentException("not another site's answer: ${h::class.simpleName}")
            }
        }
        return false
    }

    /** _unshown_titles: the songs spelled close to the query worth suggesting beside the results: none whose every
     * hit the results show. */
    private fun unshownTitles(db: Db, words: List<String>, index: IndexFound, sites: List<Any>, lacuerda: Boolean,
                              harptabs: Boolean, gtptabs: Boolean): List<Weighed> {
        val hits = HashSet<List<String>>()
        index.songs.mapTo(hits) { shown(it) }
        sites.filterIsInstance<SiteHit>().mapTo(hits) { shown(it) }
        return Close.cut(Titles.suggestions(db, words, lacuerda, harptabs, gtptabs))
            .filter { (_, s) -> !s.hits.all { shown(it) in hits } }
    }

    /** _shown: what tells a hit among the results: an Ultimate Guitar song by its keys, another site's page by its
     * address. */
    private fun shown(hit: Any): List<String> = when (hit) {
        is IndexHit -> listOf("ug", hit.artistKey, hit.songKey)
        is SiteHit -> listOf(hit.source, hit.url)
        else -> throw IllegalArgumentException("not a hit: ${hit::class.simpleName}")
    }
}
