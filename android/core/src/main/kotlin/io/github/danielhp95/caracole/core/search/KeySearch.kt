package io.github.danielhp95.caracole.core.search

import io.github.danielhp95.caracole.core.db.Db

/** ug/key_search.py: the keys' trigram index, as search's prefilter (lane search-query). */
object KeySearch {
    const val KEYS_PER_PATTERN = 1000

    /** rows_like: (artist_key, song_key, tab count) of the UG index's rows a pattern finds. */
    fun rowsLike(db: Db, patterns: List<String>): List<Triple<String, String, Int>> = TODO("lane search-query")
}
