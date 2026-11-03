package io.github.danielhp95.caracole.core.search.internal.suggest

import io.github.danielhp95.caracole.core.db.Db
import io.github.danielhp95.caracole.core.fuzz.Fuzz
import io.github.danielhp95.caracole.core.keys.Normalize
import io.github.danielhp95.caracole.core.py.Py
import io.github.danielhp95.caracole.core.search.IndexHit
import io.github.danielhp95.caracole.core.search.SearchLimits
import io.github.danielhp95.caracole.core.search.SiteHit
import io.github.danielhp95.caracole.core.search.Suggestion
import io.github.danielhp95.caracole.core.search.internal.ug.PyKeys
import io.github.danielhp95.caracole.core.search.internal.ug.UgHits
import io.github.danielhp95.caracole.core.search.internal.ug.Yours

/**
 * search.py `_Titled`: a song of one index a title suggestion may be: its weight, how close the query's words are,
 * the keys it is told from another song by (its artist's and its title's, compact), its [source], its artist there
 * ([band]: Ultimate Guitar's artist key, the slug of their LaCuerda page, the path of their harptabs.com page), and
 * what makes its hit: Ultimate Guitar's song key, LaCuerda's SiteHit, harptabs.com's song key.
 */
internal class Titled(val weight: Double, val score: Double, val artist: String, val title: String, val source: String,
                      val band: String, val hit: Any)

/**
 * search.py's close spellings of titles: `_title_suggestions`, `_title_suggestion`, `_title_closeness`,
 * `_word_closeness`, `_ug_titled`, `_lacuerda_titled`, `_harptabs_titled`, `_gtptabs_titled`, `_needles`, `_holds`.
 */
internal object Titles {
    /** _title_suggestions: the songs spelled close to the query on each index, a song several have once, weighed
     * together (a tab as TAB_SONGS of an artist's songs): those `_cut` may keep, each made a Suggestion. */
    fun suggestions(db: Db, words: List<String>, lacuerda: Boolean, harptabs: Boolean, gtptabs: Boolean): List<Weighed> {
        val near = words.map { Close.near(db, it) }
        val found = ArrayList(ug(db, words, near))
        if (lacuerda) found += lacuerda(db, words, near)
        if (harptabs) found += harptabs(db, words, near)
        val songs = LinkedHashMap<Pair<String, String>, MutableList<Titled>>()
        for (t in found) songs.getOrPut(t.artist to t.title) { ArrayList() }.add(t)
        val merged = songs.values.map { ts ->
            Triple(SearchLimits.TAB_SONGS.toDouble() * Py.fsum(ts.map { it.weight }), ts.map { it.score }.reduce { a, b -> if (b > a) b else a },
                   ts.sortedWith(PyKeys.by({ Close.suggesting(it.source) })))
        }
        val closest = merged.map { it.second }.fold(0.0) { a, b -> if (b > a) b else a }
        val sorted = merged.sortedWith(PyKeys.by({ -it.first }, { -it.second }, { it.third[0].artist }, { it.third[0].title }))
        val kept = ArrayList<Triple<Double, Double, List<Titled>>>()
        val titles = ArrayList<String>()
        for (m in sorted) { // as _cut keeps them, before each is made
            val (weight, score, ts) = m
            if (score < closest - SearchLimits.CLOSE_MARGIN || titles.any { Fuzz.ratio(ts[0].title, it) >= SearchLimits.CLOSE }) continue
            titles.add(ts[0].title)
            if (weight * SearchLimits.SUGGEST_SHARE < (kept.firstOrNull()?.first ?: weight) || kept.size >= SearchLimits.SUGGESTED) break
            kept.add(m)
        }
        val yours = Yours(db)
        return kept.mapNotNull { (weight, score, ts) -> suggestion(db, ts, score, yours, gtptabs)?.let { weight to it } }
    }

    /** _title_suggestion: a song spelled close to the query, from each index that has it (Ultimate Guitar's first, one
     * hit an index), under the artist of the first: their songs counted, as an artist's suggestion counts them. */
    private fun suggestion(db: Db, songs: List<Titled>, score: Double, yours: Yours, gtptabs: Boolean): Suggestion? {
        val hits = ArrayList<Any>()
        var band: Band? = null
        for (t in songs) {
            if (hits.any { sourceOf(it) == t.source }) continue
            if (t.source == "ug") {
                val hit = UgHits.indexHit(db, t.band, t.hit as String, score, "title", yours)
                if (hit != null) {
                    hits.add(hit)
                    band = band ?: Band("ug", hit.artist, t.band, UgHits.artistGroups(db, t.band).size)
                }
                continue
            }
            val hit: SiteHit?
            val artist: Triple<String, String, Int>?
            if (t.source == "lacuerda") {
                hit = t.hit as SiteHit
                artist = SiteRows.lacuerdaArtist(db, t.band)
            } else {
                hit = SiteRows.harpGrouped(db, "t.artist = ? AND t.song_key = ?", listOf(t.band, t.hit as String)).firstOrNull()
                artist = SiteRows.harptabsArtist(db, t.band)
            }
            if (hit != null && artist != null) {
                hits.add(hit.copy(score = Py.round(score, 1), via = "title"))
                band = band ?: Band(t.source, artist.first, artist.second, artist.third)
            }
        }
        if (band == null) return null
        if (gtptabs) hits.addAll(gtptabs(db, hits[0], score))
        return Suggestion(band.source, band.artist, band.key, band.songs, Py.round(score, 1), title = titleOf(hits[0]), hits = hits)
    }

    private class Band(val source: String, val artist: String, val key: String, val songs: Int)

    private fun sourceOf(hit: Any): String = if (hit is IndexHit) "ug" else (hit as SiteHit).source

    private fun titleOf(hit: Any): String = if (hit is IndexHit) hit.title else (hit as SiteHit).title

    /** _word_closeness: fuzz.ratio for a long word of the same first letter; a short one is the word itself or
     * nothing. */
    private fun wordCloseness(word: String, other: String): Double {
        if (Py.len(word) < SearchLimits.CLOSE_LETTERS) return if (word == other) 100.0 else 0.0
        return if (Close.firstLetter(other) == Close.firstLetter(word)) Fuzz.ratio(word, other) else 0.0
    }

    /** max(((score, i) for i, w in enumerate(words)), default=(0.0, -1)): the best score, the last word of it. */
    private fun closest(word: String, names: List<String>): Pair<Double, Int> {
        var best = 0.0
        var at = -1
        for ((i, n) in names.withIndex()) {
            val score = wordCloseness(word, n)
            if (at < 0 || score > best || score == best) {
                best = score
                at = i
            }
        }
        return best to at
    }

    /** _title_closeness: how close the query's words are to a song's title and artist (the mean of each one's
     * closest), and what the song's tabs are weighed by: the share of the title the words close to it are, squared,
     * times as much of the artist's name where words are close to it, times how close it is above MIN_SCORE; null
     * when a word is close to no word of either, or none is closer to the title than to the artist. */
    fun titleCloseness(words: List<String>, title: List<String>, artist: List<String>): Pair<Double, Double>? {
        val scores = ArrayList<Double>()
        val held = LinkedHashSet<Int>()
        val named = LinkedHashSet<Int>()
        for (w in words) {
            val (byTitle, at) = closest(w, title)
            val (byArtist, of) = closest(w, artist)
            val best = maxOf(byTitle, byArtist)
            if (best < SearchLimits.CLOSE) return null
            if (byTitle >= byArtist) held.add(at) else named.add(of)
            scores.add(best)
        }
        val letters = title.sumOf { Py.len(it) }
        if (held.isEmpty() || letters == 0) return null
        val closeness = Py.fsum(scores) / scores.size.toDouble()
        val part = held.sumOf { Py.len(title[it]) }.toDouble() / letters.toDouble()
        var share = part * part
        if (named.isNotEmpty()) share *= named.sumOf { Py.len(artist[it]) }.toDouble() / artist.sumOf { Py.len(it) }.toDouble()
        return closeness to share * maxOf(closeness - SearchLimits.MIN_SCORE, 0.0) / (100 - SearchLimits.MIN_SCORE).toDouble()
    }

    /** _ug_titled: the Ultimate Guitar index's songs spelled close to the query: the rows holding a word close to each
     * of its words (ug_index_fts), at most CLOSE_TABS, a song's variants with it, the most tabbed first; none of a
     * catch-all's. Read until a song's tabs can no longer weigh a SUGGEST_SHARE-th of the heaviest's. */
    private fun ug(db: Db, words: List<String>, near: List<List<String>>): List<Titled> {
        val match = near.joinToString(" AND ") { n -> "(" + n.joinToString(" OR ") { "\"" + it.replace("\"", "\"\"") + "\"" } + ")" }
        val rows = db.query(
            "SELECT artist_key, song_key FROM ug_index WHERE tab_id IN " +
                "(SELECT rowid FROM ug_index_fts WHERE ug_index_fts MATCH ? LIMIT ?)",
            match, SearchLimits.CLOSE_TABS + 1,
        ) { it.text(0)!! to it.text(1)!! }
        if (rows.size > SearchLimits.CLOSE_TABS) return emptyList()
        val tabs = LinkedHashMap<Pair<String, String>, Int>()
        for ((artistKey, songKey) in rows) {
            val key = artistKey to Normalize.splitVariant(songKey).first
            tabs[key] = (tabs[key] ?: 0) + 1
        }
        val titled = near.flatten().toHashSet() // a title that holds none was found by its artist's name alone
        val found = ArrayList<Titled>()
        var heaviest = 0.0
        for ((key, n) in tabs.entries.map { it.key to it.value }.sortedWith(PyKeys.by({ -it.second }, { it.first }))) {
            val (artistKey, base) = key
            if (n.toDouble() * SearchLimits.SUGGEST_SHARE < heaviest) break
            if (UgHits.noOnes(artistKey) || base.split("-").none { it in titled }) continue
            val read = titleCloseness(words, base.split("-"), artistKey.split("-")) ?: continue
            val weight = n.toDouble() * read.second
            heaviest = maxOf(heaviest, weight)
            found.add(Titled(weight, read.first, Normalize.compact(artistKey), Normalize.compact(base), "ug", artistKey, base))
        }
        return found
    }

    /** _needles: what another site's songs are looked for by: the query's longest word's first three letters, or one of
     * its close spellings that doesn't hold them (CLOSE_PATTERNS of them at most). */
    fun needles(words: List<String>, near: List<List<String>>): List<String> {
        var longest = 0
        for (i in words.indices) if (Py.len(words[i]) > Py.len(words[longest])) longest = i
        val start = Py.slice(words[longest], null, 3)
        return listOf(start) + near[longest].filter { !it.contains(start) }.take(SearchLimits.CLOSE_PATTERNS)
    }

    /** _holds: SQL: whether [column] holds one of [needles] (as many parameters). */
    fun holds(column: String, needles: List<String>): String = "(" + needles.joinToString(" OR ") { "instr($column, ?) > 0" } + ")"

    /** _lacuerda_titled: LaCuerda's songs spelled close to the query (lacuerda_index.songs_like), by their versions. */
    private fun lacuerda(db: Db, words: List<String>, near: List<List<String>>): List<Titled> {
        val found = ArrayList<Titled>()
        for (h in SiteRows.songsLike(db, needles(words, near).map { "%$it%" }, SiteRows.SITE_TITLES_READ)) {
            val read = titleCloseness(words, h.titleKey.split("-"), h.artistKey.split("-")) ?: continue
            found.add(Titled(maxOf(Py.len(h.versions), 1).toDouble() * read.second, read.first, Normalize.compact(h.artistKey),
                             Normalize.compact(h.titleKey), "lacuerda", h.artistSlug, h.hit))
        }
        return found
    }

    /** _harptabs_titled: harptabs.com's songs spelled close to the query, of the artist pages caracole read: those
     * whose title's key holds a needle, by their harmonica tabs, the hit made once suggested. */
    private fun harptabs(db: Db, words: List<String>, near: List<List<String>>): List<Titled> {
        val needles = needles(words, near)
        val rows = db.query(
            "SELECT artist, song_key, COUNT(*) FROM harptabs_artist_tabs WHERE song_key IN (SELECT DISTINCT song_key FROM " +
                "harptabs_artist_tabs WHERE " + holds("song_key", needles) + ") GROUP BY artist, song_key " +
                "ORDER BY artist, song_key LIMIT ?",
            *(needles + SiteRows.SITE_TITLES_READ).toTypedArray(),
        ) { Triple(it.text(0)!!, it.text(1)!!, it.long(2)!!.toInt()) }
        val paths = rows.map { it.first }.distinct().sortedWith(Py.CODE_POINT_ORDER)
        val names = HashMap<String, Pair<String, String>>()
        if (paths.isNotEmpty()) {
            db.query("SELECT path, key, name FROM harptabs_artists WHERE path IN (${paths.joinToString(", ") { "?" }})",
                     *paths.toTypedArray()) { Triple(it.text(0)!!, it.text(1)!!, it.text(2)!!) }
                .forEach { (path, key, name) -> names[path] = key to name }
        }
        val found = ArrayList<Titled>()
        for ((path, songKey, tabs) in rows) {
            val (key, name) = names[path] ?: ("" to "")
            val read = titleCloseness(words, songKey.split("-"), key.split("-"))
            if (read != null && name.isNotEmpty()) {
                val artistKey = Normalize.identityKey(name, "").substringBefore('/')
                found.add(Titled(tabs.toDouble() * read.second, read.first, Normalize.compact(artistKey),
                                 Normalize.compact(songKey), "harptabs", path, songKey))
            }
        }
        return found
    }

    /** _gtptabs_titled: gtptabs.com's page of a song (its artist's name and its title), as search_gtptabs gives one;
     * none for none. */
    private fun gtptabs(db: Db, hit: Any, score: Double): List<SiteHit> {
        val artist = if (hit is IndexHit) hit.artist else (hit as SiteHit).artist
        val keys = SiteRows.gtptabsKeys(artist)
        val base = if (hit is IndexHit) Normalize.splitVariant(hit.songKey).first else Normalize.slugKey((hit as SiteHit).title)
        if (keys.isEmpty() || base.isEmpty()) return emptyList()
        val rows = db.query(
            "SELECT path, artist_key FROM gtptabs_index WHERE artist_key IN (${keys.joinToString(", ") { "?" }}) " +
                "AND base_key = ? AND title_key != '' ORDER BY path",
            *(keys + base).toTypedArray(),
        ) { it.text(0)!! to it.text(1)!! }
        if (rows.isEmpty()) return emptyList()
        return listOf(SiteHit("gtptabs", UgHits.titleWords(base), SiteRows.gtptabsUrl(rows[0].first), Py.round(score, 1),
                              artist, rows[0].second, base, rows.size, "title"))
    }
}
