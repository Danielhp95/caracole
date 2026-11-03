package io.github.danielhp95.caracole.core.search.internal.ug

import io.github.danielhp95.caracole.core.db.Db
import io.github.danielhp95.caracole.core.keys.Normalize
import io.github.danielhp95.caracole.core.py.Py
import io.github.danielhp95.caracole.core.search.ArtistHit
import io.github.danielhp95.caracole.core.search.IndexHit
import io.github.danielhp95.caracole.core.search.KeySearch
import io.github.danielhp95.caracole.core.search.Queries
import io.github.danielhp95.caracole.core.search.Query
import io.github.danielhp95.caracole.core.search.Readings
import io.github.danielhp95.caracole.core.search.SearchLimits
import io.github.danielhp95.caracole.core.ug.ListedTab
import io.github.danielhp95.caracole.core.ug.ListedTabs

/** search.py `_Row`: a song of the rows the prefilter read (its variants with it), scored. */
internal data class ScoredRow(val score: Double, val tabs: Int, val artistTabs: Int, val artistKey: String,
                              val base: String, val via: String)

/** search.py `_Named`: an artist of the rows whose whole name the query is, with what the rows hold of theirs. */
internal data class Named(val score: Double, val top: Int, val tabs: Int)

/** What `_scored_rows` answers: the songs scored best first, the artists named whole, and those named in part with
 * how much of their name the query is. */
internal class Scored(val rows: List<ScoredRow>, val named: LinkedHashMap<String, Named>,
                      val parts: LinkedHashMap<String, Double>)

/**
 * search.py's reading of the UG index for a query: the rows the prefilter reads scored (`_scored_rows`), with the
 * artist pages caracole read (`_listed_rows`, `_merged`), the artists named in part (`_parts`), and the artist rows
 * shown (`_artist_rows`, `_part_rows`, `_with_parts`) and whether one leads.
 */
internal object ScoredRows {
    /** _scored_rows: every song of the rows the prefilter reads scored against the query, best first (ties to more
     * tabs, then to the artist with more of the rows), the artists the query names, and those it names in part. */
    fun of(db: Db, query: String, reading: String? = null): Scored {
        val patterns = Queries.patterns(Normalize.nameWords(query))
        if (patterns.isEmpty()) return Scored(emptyList(), LinkedHashMap(), LinkedHashMap())
        val queries = Queries.of(query)
        // Every row whose artist or song key matches a pattern, read from the keys' trigram index.
        val groups = LinkedHashMap<Pair<String, String>, Int>()
        for ((artistKey, songKey, n) in KeySearch.rowsLike(db, patterns)) {
            val key = artistKey to Normalize.splitVariant(songKey).first
            groups[key] = (groups[key] ?: 0) + n
        }
        val tabs = LinkedHashMap<String, Int>()
        val top = LinkedHashMap<String, Int>()
        for ((key, n) in groups) {
            tabs[key.first] = (tabs[key.first] ?: 0) + n
            top[key.first] = maxOf(top[key.first] ?: 0, n)
        }
        var scored = ArrayList<ScoredRow>()
        for ((key, n) in groups) {
            val (artistKey, base) = key
            val artist = artistKey.replace("-", " ")
            val title = base.replace("-", " ")
            var (score, via) = Queries.reading(queries.map { it.readings(artist, title) }, reading)
            if (UgHits.isCatchAll(artistKey)) { // no one's name: the title holds the show's, so it is scored alone
                val show = base.split("-").filter { it !in UgHits.SHOW_WORDS }.joinToString(" ")
                var alone = 0.0
                var any = false
                for (q in queries) for (t in listOf(title, show)) {
                    if (t.isEmpty()) continue
                    val s = q.score("", t)
                    if (!any || s > alone) alone = s
                    any = true
                }
                if (alone > score) {
                    score = alone
                    via = "title"
                }
            }
            if (score >= SearchLimits.MIN_SCORE) scored.add(ScoredRow(score, n, tabs.getValue(artistKey), artistKey, base, via))
        }
        val named = LinkedHashMap<String, Named>()
        if (reading == null) {
            for (artistKey in tabs.keys) {
                if (UgHits.noOnes(artistKey)) continue
                val score = queries.maxOf { it.name(artistKey.replace("-", " ")) }
                if (score >= SearchLimits.STRONG) named[artistKey] = Named(score, top.getValue(artistKey), tabs.getValue(artistKey))
            }
        }
        val listed = listedRows(db, queries, patterns, reading)
        scored = ArrayList(merged(scored, listed.rows))
        for ((artistKey, n) in listed.named) {
            val old = named[artistKey]
            named[artistKey] = if (old == null) n else Named(maxOf(old.score, n.score), maxOf(old.top, n.top), maxOf(old.tabs, n.tabs))
        }
        val sorted = scored.sortedWith(PyKeys.by({ -it.score }, { -it.tabs }, { -it.artistTabs }, { it.artistKey }, { it.base }))
        val parts = if (reading == null) parts(db, query, tabs.keys, listed.forms) else LinkedHashMap()
        return Scored(sorted, named, parts)
    }

    /** _parts: the artists the query names in part: those whose name holds every word of the query as a word of its
     * own, among others, a Chinese word as its pinyin, a whole run of the name's words; each with how much of the
     * name the query is (its letters over the name's). Bounded by WORD_LETTERS and WORD_ARTISTS. */
    fun parts(db: Db, query: String, read: Collection<String>, listed: Map<String, Set<String>>): LinkedHashMap<String, Double> {
        val words = Normalize.nameWords(query)
        val latin = words.filter { !Normalize.hasHan(it) }
        val runs = Queries.pinyinRuns(words)
        if (latin.none { Py.len(it) >= SearchLimits.WORD_LETTERS } && runs.none { Py.len(it) >= 4 }) return LinkedHashMap()
        val names = partNames(db, latin, runs, read, listed) ?: return LinkedHashMap()
        val letters = (latin.sumOf { Py.len(it) } + runs.sumOf { Py.len(it) }).toDouble()
        val found = LinkedHashMap<String, Double>()
        for ((key, forms) in names) {
            if (UgHits.noOnes(key)) continue
            val shares = forms.filter { name -> latin.all { it in name } && runs.all { Normalize.holdsRun(name, it) } }
                .map { name -> letters / Py.len(name.joinToString("")).toDouble() }
            if (shares.isNotEmpty()) found[key] = shares.reduce { a, b -> if (b > a) b else a }
        }
        return if (found.size <= SearchLimits.WORD_ARTISTS) found else LinkedHashMap()
    }

    /** _part_names: the artists `_parts` looks among, each with its names' words; null when more than WORD_ARTISTS
     * keys hold the words. */
    private fun partNames(db: Db, latin: List<String>, runs: List<String>, read: Collection<String>,
                          listed: Map<String, Set<String>>): LinkedHashMap<String, MutableList<List<String>>>? {
        val keys = if (runs.isNotEmpty()) LinkedHashSet(read).toList() else artistsWithWords(db, latin) ?: return null
        val names = LinkedHashMap<String, MutableList<List<String>>>()
        for (k in keys) names[k] = mutableListOf(k.split("-"))
        for ((k, forms) in listed) {
            names.getOrPut(k) { mutableListOf() }.addAll(forms.filter { isAscii(it) }.map { it.split("-") })
        }
        return names
    }

    /** _artists_with_words: the artist keys of the index that hold every one of [words] as a word, from the index of
     * their words; null when more than WORD_ARTISTS do. */
    private fun artistsWithWords(db: Db, words: List<String>): List<String>? {
        val match = words.joinToString(" AND ") { "\"" + it.replace("\"", "\"\"") + "\"" }
        val keys = db.query(
            "SELECT artist_key FROM ug_artists WHERE id IN (SELECT rowid FROM ug_artists_fts WHERE ug_artists_fts MATCH ?) " +
                "LIMIT ?",
            match, SearchLimits.WORD_ARTISTS + 1,
        ) { it.text(0)!! }
        return if (keys.size <= SearchLimits.WORD_ARTISTS) keys else null
    }

    internal class Listed(val rows: List<ScoredRow>, val named: LinkedHashMap<String, Named>,
                          val forms: LinkedHashMap<String, LinkedHashSet<String>>)

    /** _listed_rows: the songs of the artist pages caracole read whose names hold a pattern, scored as the index's
     * are but on every form of UG's names, their artists the query names (none with [reading]), and each artist's
     * forms. */
    private fun listedRows(db: Db, queries: List<Query>, patterns: List<String>, reading: String?): Listed {
        val songs = LinkedHashMap<Pair<String, String>, LinkedHashMap<Long, ListedTab>>()
        for (tab in ListedTabs.rowsLike(db, patterns)) {
            songs.getOrPut(tab.artistKey to tab.songKey) { LinkedHashMap() }.putIfAbsent(tab.tabId, tab)
        }
        val tabs = LinkedHashMap<String, Int>()
        val top = LinkedHashMap<String, Int>()
        for ((key, group) in songs) {
            tabs[key.first] = (tabs[key.first] ?: 0) + group.size
            top[key.first] = maxOf(top[key.first] ?: 0, group.size)
        }
        val scored = ArrayList<ScoredRow>()
        for ((key, group) in songs) {
            val names = LinkedHashSet(group.values.map { it.artistForms to it.titleForms })
            val readings = names.flatMap { (a, t) -> formsReadings(queries, a, t) }
            val (score, via) = Queries.reading(readings, reading)
            if (score >= SearchLimits.MIN_SCORE) {
                scored.add(ScoredRow(score, group.size, tabs.getValue(key.first), key.first, key.second, via))
            }
        }
        val forms = LinkedHashMap<String, LinkedHashSet<String>>()
        for ((key, group) in songs) forms.getOrPut(key.first) { LinkedHashSet() }.addAll(group.values.flatMap { it.artistForms })
        val named = LinkedHashMap<String, Named>()
        if (reading == null) {
            for ((artistKey, names) in forms) {
                if (UgHits.noOnes(artistKey)) continue
                var score = 0.0
                for (q in queries) for (f in sameScript(q, names)) score = maxOf(score, q.name(f.replace("-", " ")))
                if (score >= SearchLimits.STRONG) named[artistKey] = Named(score, top.getValue(artistKey), tabs.getValue(artistKey))
            }
        }
        return Listed(scored, named, forms)
    }

    /** _same_script: the forms worth scoring against a form of the query: in Latin letters alone for a query in
     * Latin letters alone, the others for one in another script. */
    private fun sameScript(q: Query, forms: Collection<String>): List<String> {
        val ascii = isAscii(q.text)
        return forms.filter { isAscii(it) == ascii }
    }

    /** _forms_readings: each query form's readings of each pair of an artist's form and a title's, of its script. */
    private fun formsReadings(queries: List<Query>, artistForms: List<String>, titleForms: List<String>): List<Readings> {
        val out = ArrayList<Readings>()
        for (q in queries) {
            val artists = sameScript(q, artistForms)
            val titles = sameScript(q, titleForms)
            if (artists.isEmpty() && titles.isEmpty()) continue
            for (a in artists.ifEmpty { listOf("") }) {
                for (t in titles.ifEmpty { listOf("") }) out.add(q.readings(a.replace("-", " "), t.replace("-", " ")))
            }
        }
        return out
    }

    /** _merged: the index's songs with the artist pages', one row a song: the better score, and the more tabs. */
    private fun merged(rows: List<ScoredRow>, listed: List<ScoredRow>): List<ScoredRow> {
        val merged = LinkedHashMap<Pair<String, String>, ScoredRow>()
        for (r in rows) merged[r.artistKey to r.base] = r
        for (listedRow in listed) {
            var r = listedRow
            val old = merged[r.artistKey to r.base]
            if (old != null) {
                val best = if (r.score > old.score) r else old
                r = best.copy(tabs = maxOf(r.tabs, old.tabs), artistTabs = maxOf(r.artistTabs, old.artistTabs))
            }
            merged[r.artistKey to r.base] = r
        }
        return merged.values.toList()
    }

    /** _without_near_names: beside an artist whose whole name the query is, those whose name is only near it go, and
     * the songs only their name matched. */
    fun withoutNearNames(scored: List<ScoredRow>, named: LinkedHashMap<String, Named>): Pair<List<ScoredRow>, LinkedHashMap<String, Named>> {
        if (named.values.none { it.score >= 100 }) return scored to named
        val near = named.filter { it.value.score < 100 }.keys
        val kept = LinkedHashMap<String, Named>()
        for ((k, n) in named) if (k !in near) kept[k] = n
        return scored.filter { !(it.via == "artist" && it.artistKey in near) } to kept
    }

    /** _artist_rows: up to [n] artist rows: the artists the query names, with those it names in part, in one order. */
    fun artistRows(db: Db, named: Map<String, Named>, parts: Map<String, Double>, n: Int): List<ArtistHit> {
        if (n <= 0) return emptyList()
        val order = named.keys.sortedWith(PyKeys.by({ -named.getValue(it).score }, { -named.getValue(it).top },
                                                    { -named.getValue(it).tabs }, { it }))
        val yours = Yours(db)
        val rows = PyKeys.head(order, n + 2).mapNotNull { UgHits.artistHit(db, it, named.getValue(it).score, yours) }
            .sortedWith(PyKeys.by({ -it.score }, { -it.topTabs }, { -it.tabs }, { it.artistKey }))
        val others = LinkedHashMap<String, Double>()
        for ((k, c) in parts) if (k !in named) others[k] = c
        return withParts(PyKeys.head(rows, n), partRows(db, others, n, yours), n)
    }

    /** _part_rows: up to [n] of the artists the query names in part, by their songs weighed by that share. */
    private fun partRows(db: Db, parts: Map<String, Double>, n: Int, yours: Yours): List<ArtistHit> {
        if (n <= 0 || parts.isEmpty()) return emptyList()
        val counts = UgHits.songCounts(db, parts.keys.toList())
        val order = PyKeys.head(parts.keys.sortedWith(PyKeys.by({ -(counts[it] ?: 0).toDouble() * parts.getValue(it) }, { it })), n + 2)
        val rows = order.mapNotNull { UgHits.artistHit(db, it, SearchLimits.PART, yours, part = true) }
        return PyKeys.head(rows.sortedWith(PyKeys.by({ -it.songs.toDouble() * parts.getValue(it.artistKey) }, { -it.tabs },
                                                     { it.artistKey })), n)
    }

    /** _with_parts: those named whole, then those named in part, except that a well-known one named in part goes
     * before each one named whole they outweigh; up to [n]. */
    private fun withParts(rows: List<ArtistHit>, parts: List<ArtistHit>, n: Int): List<ArtistHit> {
        val out = ArrayList(rows)
        var at = 0 // an artist named in part goes after the one before them
        for (p in parts) {
            val i = (at until out.size).firstOrNull { !out[it].part && outweighs(p.songs, out[it].songs) } ?: out.size
            out.add(i, p)
            at = i + 1
        }
        while (out.size > maxOf(n, 0)) {
            out.removeAt(out.indices.filter { out[it].part && it > 0 }.maxOrNull() ?: (out.size - 1))
        }
        return out
    }

    /** _outweighs: well known (WELL_KNOWN songs or more) and with OUTWEIGHS times their songs. */
    fun outweighs(part: Int, whole: Int): Boolean = part >= SearchLimits.WELL_KNOWN && part > SearchLimits.OUTWEIGHS * whole

    /** _artist_leads: a better score than the first song's, or the same and a more tabbed song of its own; one the
     * query names in part, by `_part_leads`. */
    fun artistLeads(artist: ArtistHit, scored: List<ScoredRow>, hits: List<IndexHit>): Boolean {
        if (artist.part) return partLeads(artist, scored, hits)
        if (hits.isEmpty()) return true
        val first = hits[0]
        return artist.score > first.score || (artist.score == first.score && artist.topTabs > first.tabs)
    }

    /** _part_leads: their songs most of the songs matched (MOST_SONGS of them at least), or well known with a song
     * tabbed more than the first song read by its title (or both). */
    private fun partLeads(artist: ArtistHit, scored: List<ScoredRow>, hits: List<IndexHit>): Boolean {
        if (!artist.part) return false
        if (artist.songs >= SearchLimits.MOST_SONGS && 2 * scored.count { it.artistKey == artist.artistKey } > scored.size) return true
        val titled = hits.firstOrNull { it.via != "artist" }?.tabs ?: 0
        return artist.songs >= SearchLimits.WELL_KNOWN && artist.topTabs > titled
    }

    /** _hits: the rows as index hits. */
    fun hits(db: Db, rows: List<ScoredRow>): List<IndexHit> {
        val yours = Yours(db)
        return rows.mapNotNull { UgHits.indexHit(db, it.artistKey, it.base, it.score, it.via, yours) }
    }

    /** str.isascii(). */
    fun isAscii(s: String): Boolean = s.all { it.code < 0x80 }
}
