package io.github.danielhp95.caracole.core.search

import io.github.danielhp95.caracole.core.db.Db
import io.github.danielhp95.caracole.core.search.internal.query.QueryRules

/**
 * ug/key_search.py: substring search over the UG index's keys, search's prefilter, read from the keys' trigram index
 * (lane search-query).
 *
 * `ug_keys` holds each distinct key once and `ug_keys_fts` indexes their trigrams (schema 5): a pattern with a run of
 * three letters or more reads the trigram index through `LIKE` (never `MATCH`: the table is `detail=none`, which
 * refuses phrase queries), a shorter one reads the keys, never the rows. A pattern in more than [KEYS_PER_PATTERN]
 * keys brings in its shortest ones, with the keys every pattern of the query is in. The keys found reach the rows
 * through `ug_index`'s own indexes, by artist and by song, and the rows come in the keys' order, artist key then song
 * key (SQLite's BINARY collation: code points), as Python's do.
 */
object KeySearch {
    const val KEYS_PER_PATTERN = 1000

    private const val KEYS = "temp._ug_like"
    private const val CREATE = "CREATE TEMP TABLE IF NOT EXISTS _ug_like (key TEXT PRIMARY KEY) WITHOUT ROWID"
    private const val SHORTEST = "ORDER BY length(key), key LIMIT ?"
    private const val BY_TRIGRAMS = "INSERT OR IGNORE INTO $KEYS SELECT key FROM ug_keys " +
        "WHERE id IN (SELECT rowid FROM ug_keys_fts WHERE key LIKE ?) $SHORTEST"
    private const val BY_SCAN = "INSERT OR IGNORE INTO $KEYS SELECT key FROM ug_keys WHERE key LIKE ? $SHORTEST"
    private const val ROWS =
        "SELECT artist_key, song_key, COUNT(*) FROM ug_index WHERE artist_key IN (SELECT key FROM $KEYS) " +
            "GROUP BY artist_key, song_key " +
            "UNION ALL " +
            "SELECT artist_key, song_key, COUNT(*) FROM ug_index WHERE song_key IN (SELECT key FROM $KEYS) " +
            "AND artist_key NOT IN (SELECT key FROM $KEYS) GROUP BY artist_key, song_key " +
            "ORDER BY artist_key, song_key"

    /** The keys every pattern is in, from the trigram index: the shortest [KEYS_PER_PATTERN] too. */
    private fun every(patterns: List<String>): String =
        "INSERT OR IGNORE INTO $KEYS SELECT key FROM ug_keys " +
            "WHERE id IN (SELECT rowid FROM ug_keys_fts WHERE ${patterns.joinToString(" AND ") { "key LIKE ?" }}) $SHORTEST"

    /**
     * rows_like: (artist key, song key, rows) for each song key of an artist whose artist key or song key matches any
     * of [patterns] (`LIKE`, without `_` or an escape), a pattern of more than [KEYS_PER_PATTERN] keys reading its
     * shortest ones and the keys every pattern is in; in the keys' order. It writes only its own TEMP table, so it runs
     * on a reader's connection.
     */
    fun rowsLike(db: Db, patterns: List<String>): List<Triple<String, String, Int>> {
        if (patterns.isEmpty()) return emptyList()
        db.execute(CREATE)
        db.execute("DELETE FROM $KEYS")
        try {
            if (patterns.size > 1 && patterns.all { QueryRules.indexed(it) }) {
                db.execute(every(patterns), *patterns.toTypedArray(), KEYS_PER_PATTERN)
            }
            for (pattern in patterns) {
                db.execute(if (QueryRules.indexed(pattern)) BY_TRIGRAMS else BY_SCAN, pattern, KEYS_PER_PATTERN)
            }
            return db.query(ROWS) { Triple(it.text(0)!!, it.text(1)!!, it.long(2)!!.toInt()) }
        } finally {
            db.execute("DELETE FROM $KEYS")
        }
    }
}
