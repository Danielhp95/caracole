package io.github.danielhp95.caracole.core.search.internal.ug

import io.github.danielhp95.caracole.core.db.Db
import io.github.danielhp95.caracole.core.keys.Normalize
import io.github.danielhp95.caracole.core.py.Py
import io.github.danielhp95.caracole.core.py.PyRegex
import io.github.danielhp95.caracole.core.py.PyUnicode
import io.github.danielhp95.caracole.core.search.ArtistHit
import io.github.danielhp95.caracole.core.search.IndexHit
import io.github.danielhp95.caracole.core.search.SearchLimits
import io.github.danielhp95.caracole.core.ug.ListedTab
import io.github.danielhp95.caracole.core.ug.ListedTabs
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonPrimitive

/** A tab of the offline UG index (ug/lookup.py `IndexTab`): a variant's [label], and the sitemap [path] its page is
 * served at ("" for a bare id). */
internal data class IndexTab(val tabId: Long, val type: String, val songKey: String, val label: String?,
                             val path: String = "") {
    /** The tab page URL; slugged tabs are only served at their slugged path. */
    val url: String get() = UgHits.pageUrl(tabId, path.ifEmpty { null })
}

/**
 * The UG index's songs and artists as search.py makes them hits (`_index_hit`, `_artist_hit`, `_artist_groups`,
 * `_song_counts`, `_best_listed`, `_Yours`, `_names_from_path`, `display_from_keys`), with what search needs of
 * ug/lookup.py (`song_tabs`), ug/page.py (`page_url`) and match.py (`is_catch_all`, `SHOW_WORDS`). Shared by Search
 * and Suggest, which make the same hits.
 */
internal object UgHits {
    /** match.SHOW_WORDS: the words a catch-all's title holds beside the show's name. */
    val SHOW_WORDS: Set<String> = setOf(
        "the", "musical", "soundtrack", "ost", "movie", "film", "show", "series", "tv", "theme", "from",
        "original", "cast", "broadway", "game", "anime", "opening", "ending",
    )

    /** config.RankPolicy().prior_votes. */
    const val PRIOR_VOTES = 10

    private const val TAB_BASE = "https://tabs.ultimate-guitar.com/tab/"

    /** match.is_catch_all: every misc-… key but misc-mashups files many artists' songs. */
    fun isCatchAll(artistKey: String): Boolean =
        artistKey.startsWith(SearchLimits.CATCH_ALL_PREFIX) && artistKey != "misc-mashups"

    /** search.no_ones: every misc-… key, misc-mashups too, is no one's name. */
    fun noOnes(artistKey: String): Boolean = artistKey.startsWith(SearchLimits.CATCH_ALL_PREFIX)

    /** ug/page.py page_url: the slugged URL with the sitemap [path], else the bare one. */
    fun pageUrl(tabId: Long, path: String? = null): String =
        if (!path.isNullOrEmpty()) TAB_BASE + path.trimStart('/') else "$TAB_BASE$tabId"

    /** ug/lookup.py song_tabs: every indexed tab of a song, its variant slugs (`song-key-acoustic`) included. */
    fun songTabs(db: Db, artistKey: String, songKey: String): List<IndexTab> {
        val rows = db.query(
            "SELECT tab_id, type, song_key, path FROM ug_index WHERE artist_key = ? AND (song_key = ? OR song_key LIKE ?) " +
                "ORDER BY tab_id",
            artistKey, songKey, "$songKey-%",
        ) { IndexTab(it.long(0)!!, it.text(1)!!, it.text(2)!!, null, it.text(3)!!) }
        val out = ArrayList<IndexTab>()
        for (r in rows) {
            if (r.songKey == songKey) {
                out.add(r)
                continue
            }
            val (base, label) = Normalize.splitVariant(r.songKey)
            if (base == songKey) out.add(r.copy(label = label))
        }
        return out
    }

    /** _title_words: each word of a key or slug capitalized, its first letter alone ("3am" stays "3am"). */
    fun titleWords(key: String): String = key.split("-").filter { it.isNotEmpty() }.joinToString(" ") { w ->
        val n = Character.charCount(w.codePointAt(0))
        PyUnicode.upper(w.substring(0, n)) + w.substring(n)
    }

    /** display_from_keys: an artist and a title made from UG keys or slugs. */
    fun displayFromKeys(artistKey: String, songKey: String): Pair<String, String> =
        titleWords(artistKey) to titleWords(songKey)

    /** _type_rank: chords, then tabs, then ukulele, then any other kind by its name. */
    fun typeRank(kind: String): List<Any> {
        val at = SearchLimits.TYPE_ORDER.indexOf(kind)
        return listOf(if (at >= 0) at else SearchLimits.TYPE_ORDER.size, kind)
    }

    /** _names_from_path: artist and title from the tab's sitemap path (`the-rifles/local-boy-chords-123`), UG's slugs
     * as written, a variant's label cut off; null for a bare or unexpected path. */
    fun namesFromPath(tab: IndexTab): Pair<String, String>? {
        val slash = tab.path.indexOf('/')
        if (slash < 0) return null
        val artistSlug = tab.path.substring(0, slash)
        val rest = tab.path.substring(slash + 1)
        val suffix = "-${tab.type}-${tab.tabId}"
        if (!rest.endsWith(suffix)) return null
        var songSlug = rest.substring(0, rest.length - suffix.length)
        val label = tab.label
        if (!label.isNullOrEmpty() && songSlug.endsWith("-$label")) songSlug = songSlug.substring(0, songSlug.length - label.length - 1)
        val (artist, title) = displayFromKeys(artistSlug, songSlug)
        return if (artist.isNotEmpty() && title.isNotEmpty()) artist to title else null
    }

    private val HAN_SPACE: Regex by lazy { PyRegex.compile("(?<=[\\u3400-\\u9fff])\\s+(?=[\\u3400-\\u9fff])") }

    /** _original_title: a title as UG lists it on an artist page, by its original name, Chinese written together. */
    fun originalTitle(title: String): String =
        HAN_SPACE.replace(Normalize.originalPart(Normalize.cleanTitle(title)), "") // \s+ matches no empty run

    /** _artist_groups: each song of an artist with its tabs (a song's variants with it), most tabbed first: the
     * index's, with the tabs only an artist page caracole read lists. */
    fun artistGroups(db: Db, artistKey: String): List<Pair<String, Int>> {
        val groups = LinkedHashMap<String, Int>()
        db.query("SELECT song_key, COUNT(*) FROM ug_index WHERE artist_key = ? GROUP BY song_key", artistKey) {
            it.text(0)!! to it.long(1)!!.toInt()
        }.forEach { (songKey, n) ->
            val base = Normalize.splitVariant(songKey).first
            groups[base] = (groups[base] ?: 0) + n
        }
        for ((base, n) in ListedTabs.unindexedSongs(db, artistKey)) groups[base] = (groups[base] ?: 0) + n
        return groups.entries.map { it.key to it.value }.sortedWith(PyKeys.by({ -it.second }, { it.first }))
    }

    /** _artist_hit: an artist with its songs and tabs counted and its most tabbed songs; null for no tab of theirs. */
    fun artistHit(db: Db, artistKey: String, score: Double, yours: Yours? = null, part: Boolean = false): ArtistHit? {
        val groups = artistGroups(db, artistKey)
        if (groups.isEmpty()) return null
        val mine = yours ?: Yours(db)
        val top = groups.take(SearchLimits.TOP_SONGS).mapNotNull { (base, _) -> indexHit(db, artistKey, base, score, "artist", mine) }
        val name = top.firstOrNull()?.artist ?: titleWords(artistKey)
        return ArtistHit(artistKey, name, Py.round(score, 1), groups.size, groups.sumOf { it.second }, top,
                         ListedTabs.artistPage(db, artistKey) ?: "", part)
    }

    /** _song_counts: how many song keys the index has of each artist key (a song's variants each one), and the artist
     * pages caracole read. */
    fun songCounts(db: Db, keys: List<String>): Map<String, Int> {
        val counts = LinkedHashMap<String, Int>()
        for (start in keys.indices step 500) {
            val part = keys.subList(start, minOf(start + 500, keys.size))
            val marks = part.joinToString(", ") { "?" }
            for (table in listOf("ug_index", "ug_artist_tabs")) {
                db.query(
                    "SELECT artist_key, COUNT(DISTINCT song_key) FROM $table WHERE artist_key IN ($marks) GROUP BY artist_key",
                    *part.toTypedArray(),
                ) { it.text(0)!! to it.long(1)!!.toInt() }.forEach { (k, n) -> counts[k] = (counts[k] ?: 0) + n }
            }
        }
        return counts
    }

    /** _index_hit: every tab of the song, counted per type, with a sample page and names to show: the index's, and
     * those an artist page caracole read lists, each tab once. */
    fun indexHit(db: Db, artistKey: String, songKey: String, score: Double, via: String = "both",
                 yours: Yours? = null): IndexHit? {
        val tabs = songTabs(db, artistKey, songKey)
        val listed = ListedTabs.songTabs(db, artistKey, songKey)
        if (tabs.isEmpty() && listed.isEmpty()) return null
        val ids = tabs.mapTo(HashSet()) { it.tabId }
        val others = listed.filter { it.tabId !in ids }
        val counts = LinkedHashMap<String, Int>()
        for (kind in tabs.map { it.type } + others.map { it.type }) counts[kind] = (counts[kind] ?: 0) + 1
        val ordered = LinkedHashMap<String, Int>()
        for (kind in counts.keys.sortedWith(PyKeys.by({ typeRank(it) }))) ordered[kind] = counts.getValue(kind)
        val labels = (tabs.map { it.label } + others.map { it.label }).filter { !it.isNullOrEmpty() }
            .map { it!! }.distinct().sortedWith(Py.CODE_POINT_ORDER)
        var rating: Double? = null
        var votes = 0
        var page = ""
        var url = ""
        var artist = ""
        var title = ""
        var sample: IndexTab? = null
        if (tabs.isNotEmpty()) {
            sample = PyKeys.min(tabs) { listOf(it.label != null, typeRank(it.type), it.tabId) }!!
            url = sample.url
            val names = namesFromPath(sample) ?: displayFromKeys(artistKey, songKey)
            artist = names.first
            title = names.second
        }
        if (listed.isNotEmpty()) { // UG's ratings: the page's best tab, of the best type, unless the index has a better type
            val best = bestListed(listed)
            page = best.page
            if (sample == null || PyKeys.compare(listOf(best.label != null, typeRank(best.type)),
                                                 listOf(sample.label != null, typeRank(sample.type))) <= 0) {
                url = best.url
                rating = if (best.votes != 0) best.rating else null // no vote: unrated
                votes = best.votes
            }
            if (sample == null) {
                artist = (yours ?: Yours(db)).artist(best.artist)
                title = originalTitle(best.title)
            }
        }
        return IndexHit(artistKey, songKey, ordered, Py.round(score, 1), url, labels, artist, title, via, rating, votes, page)
    }

    /** _best_listed: the tab a song's hit shows of those an artist page lists: of the best type (no part or
     * "acoustic" label first), the best rated as a fetch rates versions (rank.py `bayes`, `prior_mean`). */
    fun bestListed(listed: List<ListedTab>): ListedTab {
        fun kind(t: ListedTab): List<Any> = listOf(t.label != null, typeRank(t.type))
        val first = listed.map { kind(it) }.reduce { a, b -> if (PyKeys.compare(b, a) < 0) b else a }
        val group = listed.filter { PyKeys.compare(kind(it), first) == 0 }
        val prior = priorMean(group)
        return PyKeys.min(group) { listOf(-bayes(it.rating, it.votes, prior, PRIOR_VOTES), -it.votes, it.tabId) }!!
    }

    /** rank.bayes. */
    fun bayes(rating: Double, votes: Int, prior: Double, m: Int): Double =
        if (votes + m != 0) (votes.toDouble() * rating + m.toDouble() * prior) / (votes + m).toDouble() else 0.0

    /** rank.prior_mean: the vote-weighted mean rating (0 when nobody voted), its sum CPython's builtin sum. */
    fun priorMean(tabs: List<ListedTab>): Double {
        val total = tabs.sumOf { it.votes.toLong() }
        return if (total != 0L) Py.fsum(tabs.map { it.votes.toDouble() * it.rating }) / total.toDouble() else 0.0
    }
}

/**
 * search.py `_Yours`: your songs' artists, those you removed too, read once: a song only an artist page lists is
 * named as your songs name its artist (UG's "Song Dongye (宋冬野)" is your 宋冬野), else by the original of UG's two
 * names (Normalize.originalPart).
 */
internal class Yours(private val db: Db) {
    private var names: List<Pair<String, Set<String>>>? = null

    fun artist(name: String): String {
        val known = names ?: run {
            val all = ArrayList<String>()
            db.query("SELECT artist, artists FROM songs ORDER BY id") { listOf(it.text(0) ?: "") + jsonNames(it.text(1)) }
                .forEach { all += it }
            all += db.query("SELECT artist FROM removed ORDER BY removed_at DESC, key") { it.text(0) ?: "" }
            LinkedHashSet(all).filter { it.isNotEmpty() }.map { n -> n to forms(n) }.also { names = it }
        }
        val wanted = forms(name)
        return known.firstOrNull { (_, f) -> f.any { it in wanted } }?.first ?: Normalize.originalPart(name)
    }

    private fun forms(name: String): Set<String> = Normalize.nameForms(name).mapTo(HashSet()) { Normalize.compact(it) }

    private fun jsonNames(value: String?): List<String> {
        val parsed = try {
            Json.parseToJsonElement(value ?: return emptyList())
        } catch (e: IllegalArgumentException) {
            return emptyList()
        }
        return (parsed as? JsonArray)?.mapNotNull { (it as? JsonPrimitive)?.takeIf { p -> p.isString }?.content } ?: emptyList()
    }
}
