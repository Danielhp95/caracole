package io.github.danielhp95.caracole.core.search

import io.github.danielhp95.caracole.core.fuzz.Fuzz
import io.github.danielhp95.caracole.core.keys.Normalize
import io.github.danielhp95.caracole.core.library.SongRow
import io.github.danielhp95.caracole.core.py.Py
import io.github.danielhp95.caracole.core.search.internal.query.QueryRules

// search.py's scoring seam, which search-ug, search-suggest, search-sites and search-lacuerda score through
// (lane search-query): _forms, _patterns, _queries, _pinyin_runs, _Query, _reading, _song_reading and _names_reading,
// checked against tests/conformance/vectors/search/query.jsonl. Lengths and indexes are Python's, in code points;
// every word and pinyin decision is Normalize's.

/** A query's scores against one song by each way it may name it, in [SearchLimits.READINGS]' order. */
data class Readings(val title: Double, val both: Double, val artist: Double)

/** The best of several readings, and which reading gave it ("title", "both" or "artist"). */
data class Reading(val score: Double, val via: String)

/**
 * One form of a query, ready to be scored against many songs (search.py's `_Query`).
 *
 * [runs] is set on the pinyin form of a Chinese query: each Chinese word's pinyin, its syllables written together
 * ("宋冬野" is `songdongye`). That form counts for a song only where each of them is a whole run of the artist's
 * words or of the title's ([holds]), and a part of a name it matches tops out at the pinyin partial scale (0.85),
 * below a strong hit.
 */
class Query(val text: String, val runs: List<String> = emptyList()) {
    /** The text without its spaces. */
    val compact: String get() = compactText

    private val compactText = text.replace(" ", "")
    private val length = Py.len(text)
    private val compactLength = Py.len(compactText)

    /** Whether each Chinese word's pinyin is a whole run of the words of one of [names] (space-separated words):
     * `song dongye`, `songdongye` and `song dong ye` hold 宋冬野. True for a form with no Chinese. */
    fun holds(vararg names: String): Boolean {
        val words = names.map { Py.split(it) }
        return runs.all { run -> words.any { Normalize.holdsRun(it, run) } }
    }

    /** How well this query matches a song, 0–100 (artist and title are space-separated words): the best of its
     * [readings]. Unrounded, as search.py's: a hit's score is rounded where search.py rounds it (`Py.round(x, 1)`),
     * never here. */
    fun score(artist: String, title: String): Double {
        val r = readings(artist, title)
        return maxOf(maxOf(r.title, r.both), r.artist)
    }

    /**
     * The score split by the reading that gives it: the query as the song's title, as both its names (their words
     * in any order), as its artist. A part of the names counts for the title or the artist when it lies within that
     * name, else for both. Unrounded, as [score].
     */
    fun readings(artist: String, title: String): Readings {
        if (runs.isNotEmpty() && !holds(artist, title)) return Readings(0.0, 0.0, 0.0)
        val a = artist.replace(" ", "")
        val t = title.replace(" ", "")
        val full = "$artist $title"
        var byTitle = maxOf(Fuzz.ratio(text, title), Fuzz.ratio(compactText, t))
        var byBoth = maxOf(Fuzz.tokenSortRatio(text, full), Fuzz.ratio(compactText, a + t))
        var byArtist = maxOf(Fuzz.ratio(text, artist), Fuzz.ratio(compactText, a))
        val scale = if (runs.isNotEmpty()) QueryRules.PINYIN_PARTIAL_SCALE else SearchLimits.PARTIAL_SCALE
        // Spaced, the title starts after the artist and a space; compact, right after the artist.
        val spacedEdge = Py.len(artist)
        val compactEdge = Py.len(a)
        val sides = listOf(
            Side(text, length, full, spacedEdge, 1),
            Side(compactText, compactLength, a + t, compactEdge, 0),
        )
        for (side in sides) {
            if (side.needleLength < Py.len(side.names)) {
                val part = Fuzz.partialRatioAlignment(side.needle, side.names)
                val scored = scale * part.score
                when {
                    part.destStart >= side.edge -> byTitle = maxOf(byTitle, scored)
                    part.destEnd <= side.edge + side.gap -> byArtist = maxOf(byArtist, scored)
                    else -> byBoth = maxOf(byBoth, scored)
                }
            }
        }
        return Readings(byTitle, byBoth, byArtist)
    }

    /** How well this query is an artist's whole name, never a part of it: what makes an artist row. */
    fun name(artist: String): Double {
        if (runs.isNotEmpty() && !holds(artist)) return 0.0
        return maxOf(Fuzz.ratio(text, artist), Fuzz.ratio(compactText, artist.replace(" ", "")))
    }

    override fun toString(): String = "Query(text=$text, runs=$runs)"

    private class Side(val needle: String, val needleLength: Int, val names: String, val edge: Int, val gap: Int)
}

object Queries {
    /** The text as space-separated words; Chinese gets a second form, in pinyin (search.py `_forms`). */
    fun forms(text: String): List<String> {
        val tokens = Normalize.nameWords(text)
        val plain = tokens.joinToString(" ")
        if (plain.isEmpty()) return emptyList()
        if (!Normalize.hasHan(plain)) return listOf(plain)
        return listOf(plain, tokens.joinToString(" ") { if (Normalize.hasHan(it)) Normalize.fold(Normalize.romanize(it)) else it })
    }

    /**
     * At most two `LIKE` patterns for the SQL prefilter, the most selective first (search.py `_patterns`): the
     * longest words of three letters or more, a Chinese word of four letters of pinyin or more as `%syl%lab%le%`, or,
     * for a name of initials, the initials hyphenated and written together. The tokens come from
     * [Normalize.nameWords], so they never hold a `LIKE` wildcard.
     */
    fun patterns(tokens: List<String>): List<String> {
        var found = mutableListOf<Pair<Int, String>>()
        for (token in tokens) {
            if (Normalize.hasHan(token)) {
                val syllables = Py.split(Normalize.romanize(token))
                val letters = syllables.sumOf { Py.len(it) }
                if (letters >= 4) found.add(letters to "%" + syllables.joinToString("%") { Normalize.fold(it) } + "%")
            } else if (Py.len(token) >= 3) {
                found.add(Py.len(token) to "%$token%")
            }
        }
        if (found.isEmpty()) { // names made of initials
            val latin = tokens.filter { !Normalize.hasHan(it) }
            if (latin.isNotEmpty() && Py.len(latin.joinToString("")) >= 2) {
                val key = latin.joinToString("-")
                found = mutableListOf(Py.len(key) to "%$key%", Py.len(key) to "%${key.replace("-", "")}%")
            }
        }
        val patterns = mutableListOf<String>()
        for ((_, pattern) in found.sortedByDescending { it.first }) { // stable, as Python's sorted
            if (pattern !in patterns) patterns.add(pattern)
        }
        return patterns.take(SearchLimits.MAX_PATTERNS)
    }

    /** The query's forms, ready to be scored: its words, and for Chinese its pinyin too, which carries each Chinese
     * word's pinyin ([Query.runs]) for the rule that pinyin counts only as words (search.py `_queries`). */
    fun of(text: String): List<Query> {
        val forms = forms(text)
        if (forms.size < 2) return forms.map { Query(it) }
        return listOf(Query(forms[0]), Query(forms[1], pinyinRuns(Normalize.nameWords(text))))
    }

    /** Each Chinese word's pinyin, its syllables written together ("宋冬野" is `songdongye`). */
    fun pinyinRuns(words: List<String>): List<String> =
        words.filter { Normalize.hasHan(it) }.map { word -> Py.split(Normalize.romanize(word)).joinToString("") { Normalize.fold(it) } }

    /** The best of several (title, both, artist) readings, and which reading it is; a tie goes to the title, then
     * both. With [reading], that reading's alone (search.py `_reading`). Unrounded, as search.py's: a hit's score is
     * rounded where search.py rounds it (`Py.round(x, 1)`), never here. */
    fun reading(scores: Iterable<Readings>, reading: String? = null): Reading {
        var best = 0.0
        var via = SearchLimits.READINGS[0]
        for (triple in scores) {
            for ((name, score) in SearchLimits.READINGS.zip(listOf(triple.title, triple.both, triple.artist))) {
                if (score > best && (reading == null || reading == name)) {
                    best = score
                    via = name
                }
            }
        }
        return Reading(best, via)
    }

    /** [songReading] for bare names: each artist paired with the title, plain words with plain words and pinyin
     * with pinyin, each pair once in the order it first comes (search.py `_names_reading`). */
    fun namesReading(queries: List<Query>, artists: List<String>, title: String, reading: String? = null): Reading {
        val titles = forms(Normalize.cleanTitle(title)).ifEmpty { listOf("") }
        val scores = mutableListOf<Readings>()
        for (artist in LinkedHashSet(artists)) {
            val forms = forms(artist).ifEmpty { listOf("") }
            // Plain words with plain words, pinyin with pinyin (a form missing on one side is its plain one).
            val pairs = LinkedHashSet(listOf(forms.first() to titles.first(), forms.last() to titles.last()))
            for ((a, t) in pairs) queries.mapTo(scores) { it.readings(a, t) }
        }
        return reading(scores, reading)
    }

    /** The best score over a song's artists, each paired with its title, plain and in pinyin, and the reading that
     * gave it (search.py `_song_reading`). */
    fun songReading(queries: List<Query>, song: SongRow, reading: String? = null): Reading =
        namesReading(queries, song.artists.ifEmpty { listOf(song.artist) }, song.title, reading)
}
