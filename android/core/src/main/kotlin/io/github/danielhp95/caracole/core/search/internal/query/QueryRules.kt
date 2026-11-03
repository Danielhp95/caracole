package io.github.danielhp95.caracole.core.search.internal.query

import io.github.danielhp95.caracole.core.py.Py

/**
 * The rules of the query seam that the search lanes share and no declared signature names (lane search-query): the
 * same module's lanes read them here, never a copy of their own (search-lacuerda's lacuerda_index.py port among them,
 * whose `_Query` scales a pinyin part by normalize.PINYIN_PARTIAL_SCALE too).
 */
internal object QueryRules {
    /** normalize.PINYIN_PARTIAL_SCALE: a part of a name matched in pinyin tops out at 85, never a strong hit (search.py
     * `_Query`, lacuerda_index.py). */
    const val PINYIN_PARTIAL_SCALE = 0.85

    /** ug/key_search.py `indexed`: whether the trigram index can answer a `LIKE` pattern, a run of three characters
     * or more between its `%`s. */
    fun indexed(pattern: String): Boolean = pattern.split("%").any { Py.len(it) >= 3 }
}
