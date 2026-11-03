package io.github.danielhp95.caracole.server.routes.search

import io.github.danielhp95.caracole.core.keys.Normalize
import io.github.danielhp95.caracole.core.py.Py
import io.github.danielhp95.caracole.core.py.PyUnicode

/** What /api/search folds a query to before it searches, and when it searches nowhere (search_routes.api_search). */
internal object SearchQuery {
    /** search_routes.QUERY_LIMIT: the code points of a search. */
    const val LIMIT = 200

    /** `" ".join(query.split())[:QUERY_LIMIT]`: its words (split on Python's whitespace) joined by one space, cut at
     * [LIMIT] code points. */
    fun of(query: String): String = Py.slice(Py.split(query).joinToString(" "), 0, LIMIT)

    /** Too short to search: fewer than three letters or digits (str.isalnum), two for a query with Chinese. */
    fun short(q: String): Boolean = q.codePoints().filter { PyUnicode.isAlnum(it) }.count() < (if (Normalize.hasHan(q)) 2 else 3)
}
