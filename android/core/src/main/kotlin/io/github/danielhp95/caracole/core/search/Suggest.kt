package io.github.danielhp95.caracole.core.search

import io.github.danielhp95.caracole.core.db.Db
import io.github.danielhp95.caracole.core.stub

/** search.py's "Did you mean" (lane search-suggest; until then, no suggestion). */
object Suggest {
    fun suggestArtists(db: Db, q: String, limit: Int = 3, lacuerda: Boolean = true, harptabs: Boolean = true): List<Suggestion> =
        stub("lane search-suggest") { emptyList() }

    fun suggestTitles(
        db: Db, q: String, limit: Int = 3, lacuerda: Boolean = true, harptabs: Boolean = true, gtptabs: Boolean = true,
    ): List<Suggestion> = stub("lane search-suggest") { emptyList() }

    fun suggestions(
        db: Db, q: String, index: IndexFound, sites: List<Any> = emptyList(), lacuerda: Boolean = true,
        harptabs: Boolean = true, gtptabs: Boolean = true,
    ): List<Suggestion> = stub("lane search-suggest") { emptyList() }
}
