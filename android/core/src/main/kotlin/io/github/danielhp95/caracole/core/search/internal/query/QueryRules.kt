package io.github.danielhp95.caracole.core.search.internal.query

import io.github.danielhp95.caracole.core.py.Py

/**
 * The rules of the query seam that the search lanes share and no declared signature names (lane search-query): the
 * same module's lanes read them here, never a copy of their own. A pinyin part's scale is normalize.py's, as both
 * search.py's `_Query` and lacuerda_index.py's read it there: Normalize.PINYIN_PARTIAL_SCALE.
 */
internal object QueryRules {
    /** ug/key_search.py `indexed`: whether the trigram index can answer a `LIKE` pattern, a run of three characters
     * or more between its `%`s. */
    fun indexed(pattern: String): Boolean = pattern.split("%").any { Py.len(it) >= 3 }
}
