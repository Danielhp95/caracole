package io.github.danielhp95.caracole.core.search

import io.github.danielhp95.caracole.core.library.SongRow

// search.py's scoring seam, which search-ug, search-suggest, search-sites and search-lacuerda score through
// (lane search-query).

data class Readings(val title: Double, val both: Double, val artist: Double)
data class Reading(val score: Double, val via: String)

/** One reading of a query (its text and, for Chinese, its pinyin runs). */
class Query(val text: String, val runs: List<String> = emptyList()) {
    val compact: String get() = TODO("lane search-query")
    fun holds(vararg names: String): Boolean = TODO("lane search-query")
    fun score(artist: String, title: String): Double = TODO("lane search-query")
    fun readings(artist: String, title: String): Readings = TODO("lane search-query")
    fun name(artist: String): Double = TODO("lane search-query")
}

object Queries {
    fun forms(text: String): List<String> = TODO("lane search-query")
    fun patterns(tokens: List<String>): List<String> = TODO("lane search-query")
    fun of(text: String): List<Query> = TODO("lane search-query")
    fun pinyinRuns(words: List<String>): List<String> = TODO("lane search-query")
    fun reading(scores: Iterable<Readings>, reading: String? = null): Reading = TODO("lane search-query")
    fun namesReading(queries: List<Query>, artists: List<String>, title: String, reading: String? = null): Reading =
        TODO("lane search-query")
    fun songReading(queries: List<Query>, song: SongRow, reading: String? = null): Reading = TODO("lane search-query")
}
