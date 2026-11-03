package io.github.danielhp95.caracole.core.search.internal.suggest

import io.github.danielhp95.caracole.core.db.Db
import io.github.danielhp95.caracole.core.fuzz.Fuzz
import io.github.danielhp95.caracole.core.keys.Normalize
import io.github.danielhp95.caracole.core.py.Py
import io.github.danielhp95.caracole.core.py.PyUnicode
import io.github.danielhp95.caracole.core.search.SearchLimits
import io.github.danielhp95.caracole.core.search.Suggestion
import io.github.danielhp95.caracole.core.search.Vocabulary
import io.github.danielhp95.caracole.core.search.internal.ug.PyKeys
import io.github.danielhp95.caracole.core.search.internal.ug.UgHits

/** A suggestion and its weight, as search.py's `(float, Suggestion)` pairs. */
internal typealias Weighed = Pair<Double, Suggestion>

/**
 * search.py's close spellings of artists' names (`_artist_suggestions`, `_ug_suggestions`, `_lacuerda_suggestions`,
 * `_harptabs_suggestions`) and what every suggestion is weighed, ranked and cut by (`_closeness`, `_close_words`,
 * `_near`, `_weighed`, `_ranked`, `_cut`, `_suggesting`).
 */
internal object Close {
    /** search.SUGGESTING: an artist several indexes have is suggested once, as the first's. */
    val SUGGESTING = listOf("ug", "lacuerda", "harptabs")

    fun suggesting(source: String): Int = SUGGESTING.indexOf(source).let { if (it >= 0) it else SUGGESTING.size }

    /** name_words_key: a name's words written together, as a suggestion is told from another of the same artist. */
    fun nameWordsKey(name: String): String = Normalize.nameWords(name).joinToString("")

    /** _suggestible: the query's words a close spelling is looked for by: null for none, Chinese, or no word of
     * CLOSE_LETTERS letters or more. */
    fun suggestible(query: String): List<String>? {
        val words = Normalize.nameWords(query)
        if (words.isEmpty() || words.any { Normalize.hasHan(it) } || words.none { Py.len(it) >= SearchLimits.CLOSE_LETTERS }) {
            return null
        }
        return words
    }

    /** _cut: the weighed suggestions worth showing, the heaviest first, at most [limit]: none CLOSE_MARGIN less close
     * than the closest, an artist several indexes have once, a title once, none weighing less than a SUGGEST_SHARE-th
     * of the first. */
    fun cut(found: List<Weighed>, limit: Int = SearchLimits.SUGGESTED): List<Weighed> {
        val closest = found.map { it.second.score }.fold(0.0) { a, b -> if (b > a) b else a } // scores are never below 0
        val close = found.filter { it.second.score >= closest - SearchLimits.CLOSE_MARGIN }
        val first = HashMap<String, Int>() // the first index of SUGGESTING that has an artist of each name
        for ((_, s) in close) {
            if (s.title.isEmpty()) {
                val name = Normalize.compact(nameWordsKey(s.artist))
                first[name] = minOf(first[name] ?: SUGGESTING.size, suggesting(s.source))
            }
        }
        val kept = ArrayList<Weighed>()
        val names = HashSet<String>()
        val titles = ArrayList<String>()
        for (w in ranked(close)) {
            val s = w.second
            if (s.title.isNotEmpty()) {
                val title = Normalize.compact(nameWordsKey(s.title))
                if (titles.any { Fuzz.ratio(title, it) >= SearchLimits.CLOSE }) continue
                titles.add(title)
            } else {
                val name = Normalize.compact(nameWordsKey(s.artist))
                if (name in names || suggesting(s.source) != first.getValue(name)) continue
                names.add(name)
            }
            kept.add(w)
        }
        val top = kept.firstOrNull()?.first ?: 0.0
        return kept.filter { it.first * SearchLimits.SUGGEST_SHARE >= top }.take(maxOf(limit, 0))
    }

    /** _ranked: the heaviest first, then the closest; every index's together. */
    fun ranked(found: List<Weighed>): List<Weighed> = found.sortedWith(PyKeys.by(
        { -it.first }, { -it.second.score }, { PyUnicode.casefold(it.second.artist) }, { PyUnicode.casefold(it.second.title) },
        { suggesting(it.second.source) },
    ))

    /** _weighed: their songs, weighed by how much of the name (its letters) the query's letters are. */
    fun weighed(songs: Int, letters: Int, name: String): Double =
        songs.toDouble() * minOf(1.0, letters.toDouble() / maxOf(Py.len(Normalize.compact(name)), 1).toDouble())

    /** _closeness: the mean of each query word's closest word of the name (0–100); null when one has none CLOSE, a
     * short one none equal. */
    fun closeness(words: List<String>, name: List<String>): Double? {
        val scores = ArrayList<Double>()
        for (w in words) {
            val best = if (Py.len(w) < SearchLimits.CLOSE_LETTERS) {
                if (w in name) 100.0 else 0.0
            } else {
                name.map { Fuzz.ratio(w, it) }.fold(0.0) { a, b -> if (b > a) b else a }
            }
            if (best < SearchLimits.CLOSE) return null
            scores.add(best)
        }
        return Py.fsum(scores) / scores.size.toDouble()
    }

    /** _close_words: the words of the index's artists' names spelled close to [word]: of its first letter, at most two
     * letters longer or shorter, CLOSE or more, the closest CLOSE_WORDS. */
    private fun closeWords(db: Db, word: String): List<String> {
        val start = firstLetter(word)
        val n = Py.len(word)
        val terms = db.query("SELECT term FROM ug_artist_words WHERE term >= ? AND term < ?", start, after(start)) {
            it.text(0)!!
        }.filter { kotlin.math.abs(Py.len(it) - n) <= 2 }
        return Fuzz.extract(word, terms, SearchLimits.CLOSE.toDouble(), SearchLimits.CLOSE_WORDS).map { it.choice }
    }

    /** _near: [word] and the words of the index's keys spelled close to it (CLOSE or more, the closest CLOSE_WORDS),
     * among those of its first letter a couple of letters longer or shorter (Vocabulary); a short word alone. */
    fun near(db: Db, word: String): List<String> {
        if (Py.len(word) < SearchLimits.CLOSE_LETTERS) return listOf(word)
        val terms = Vocabulary.of(db).among(db, word)
        val close = Fuzz.extract(word, terms, SearchLimits.CLOSE.toDouble(), SearchLimits.CLOSE_WORDS)
        return LinkedHashSet(listOf(word) + close.map { it.choice }).toList()
    }

    fun artistSuggestions(db: Db, words: List<String>, lacuerda: Boolean, harptabs: Boolean): List<Weighed> =
        ug(db, words) + (if (lacuerda) lacuerda(db, words) else emptyList()) +
            (if (harptabs) harptabs(db, words) else emptyList())

    /** _ug_suggestions: the Ultimate Guitar index's artists spelled close to the query, each weighed: the heaviest
     * few, counted exactly. */
    private fun ug(db: Db, words: List<String>): List<Weighed> {
        val longest = longestOf(words.filter { Py.len(it) >= SearchLimits.CLOSE_LETTERS })
        val close = closeWords(db, longest)
        if (close.isEmpty()) return emptyList()
        val match = close.joinToString(" OR ") { "\"$it\"" }
        val keys = db.query(
            "SELECT artist_key FROM ug_artists WHERE id IN (SELECT rowid FROM ug_artists_fts WHERE ug_artists_fts MATCH ?) " +
                "ORDER BY artist_key LIMIT ?",
            match, SearchLimits.CLOSE_ARTISTS,
        ) { it.text(0)!! }
        val scored = LinkedHashMap<String, Double>()
        for (k in keys) {
            if (UgHits.noOnes(k)) continue
            closeness(words, k.split("-"))?.let { scored[k] = it }
        }
        if (scored.isEmpty()) return emptyList()
        val counts = UgHits.songCounts(db, scored.keys.toList())
        val letters = words.sumOf { Py.len(it) }
        val ranked = ranked(scored.filter { (counts[it.key] ?: 0) != 0 }.map { (k, c) ->
            weighed(counts.getValue(k), letters, k) to Suggestion("ug", "", k, 0, Py.round(c, 1))
        })
        val out = ArrayList<Weighed>()
        for ((_, s) in ranked.take(SearchLimits.SUGGESTED * 2)) {
            val hit = UgHits.artistHit(db, s.key, s.score) ?: continue
            out.add(weighed(hit.songs, letters, s.key) to Suggestion("ug", hit.artist, s.key, hit.songs, s.score))
        }
        return out
    }

    /** _lacuerda_suggestions: LaCuerda's artists spelled close to the query, from its listings: those with a word of
     * a long word's first letter (a `LIKE` on their keys), the query folded as those keys are. */
    private fun lacuerda(db: Db, query: List<String>): List<Weighed> {
        val words = Normalize.lacuerdaNameKey(query.joinToString(" ")).split("-").filter { it.isNotEmpty() }.ifEmpty { query }
        val firsts = words.filter { Py.len(it) >= SearchLimits.CLOSE_LETTERS }.map { firstLetter(it) }.distinct()
            .sortedWith(Py.CODE_POINT_ORDER)
        if (firsts.isEmpty()) return emptyList()
        val where = firsts.joinToString(" OR ") { "artist_key LIKE ? OR artist_key LIKE ?" }
        // +path, exactly as search.py writes it: the table scanned, the rows found sorted, never every row read
        // through the paths' index. Same rows, same order, a cheaper plan: keep the `+`.
        val rows = db.query(
            "SELECT artist, artist_slug, artist_key, songs FROM lacuerda_index WHERE title = '' AND ($where) ORDER BY +path",
            *firsts.flatMap { listOf("$it%", "%-$it%") }.toTypedArray<String>(),
        ) { listOf<Any>(it.text(0)!!, it.text(1)!!, it.text(2)!!, it.long(3)!!.toInt()) }
        val letters = words.sumOf { Py.len(it) }
        val close = ArrayList<Weighed>()
        for ((artist, slug, key, songs) in rows) {
            val c = closeness(words, (key as String).split("-")) ?: continue
            close.add(weighed(songs as Int, letters, key) to Suggestion("lacuerda", artist as String, slug as String, songs, Py.round(c, 1)))
        }
        return ranked(close).take(SearchLimits.SUGGESTED * 2)
    }

    /** _harptabs_suggestions: harptabs.com's artists spelled close to the query, from its sitemap: those whose key
     * holds a needle of the query's longest word, by their key's words, of each long word's first letter; weighed by
     * the tabs their page says they have. */
    private fun harptabs(db: Db, words: List<String>): List<Weighed> {
        val longest = longestOf(words)
        val needles = Titles.needles(words, words.map { if (it == longest) near(db, it) else listOf(it) })
        val rows = db.query(
            "${SiteRows.HARP_ARTISTS} WHERE i.kind = 'artist' AND ${Titles.holds("i.key", needles)} ORDER BY i.path",
            *needles.toTypedArray(),
        ) { SiteRows.harpArtist(it) }
        val letters = words.sumOf { Py.len(it) }
        val close = ArrayList<Weighed>()
        for (row in rows) {
            if (row.gone) continue
            val name = row.key.split("-")
            val long = words.filter { Py.len(it) >= SearchLimits.CLOSE_LETTERS }
            if (!long.all { w -> name.any { firstLetter(it) == firstLetter(w) } }) continue
            val c = closeness(words, name) ?: continue
            val songs = row.tabs ?: 0
            close.add(weighed(songs, letters, row.key) to Suggestion("harptabs", row.shown, row.path, songs, Py.round(c, 1)))
        }
        return ranked(close).take(SearchLimits.SUGGESTED * 2)
    }

    /** max(words, key=len): the first of the longest. */
    fun longestOf(words: List<String>): String {
        var best = words.first()
        for (w in words) if (Py.len(w) > Py.len(best)) best = w
        return best
    }

    /** s[:1]: its first code point, "" for none. */
    fun firstLetter(s: String): String = if (s.isEmpty()) "" else s.substring(0, Character.charCount(s.codePointAt(0)))

    /** chr(ord(start) + 1), refused where Python refuses to bind or make it (a lone surrogate, past U+10FFFF). */
    private fun after(start: String): String {
        val cp = start.codePointAt(0) + 1
        require(cp <= Character.MAX_CODE_POINT) { "chr() arg not in range(0x110000)" }
        require(cp !in Character.MIN_SURROGATE.code..Character.MAX_SURROGATE.code) { "surrogates not allowed" }
        return String(Character.toChars(cp))
    }
}
