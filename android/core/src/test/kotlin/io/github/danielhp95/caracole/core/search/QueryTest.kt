package io.github.danielhp95.caracole.core.search

import io.github.danielhp95.caracole.core.testing.Misses
import io.github.danielhp95.caracole.core.testing.replays.SearchReplay
import org.junit.Test
import kotlin.test.assertEquals

/**
 * search.py's scoring seam against vectors/search/query.jsonl: `_forms`, `_patterns`, `_pinyin_runs`, `_queries`, a
 * `_Query`'s readings, score, name and holds, `_reading` and `_names_reading`, each record Python's answer to the
 * same call (tests/test_conformance_search.py), replayed by SearchReplay (which the device runs too). Scores compare as
 * doubles, with ==. KeySearchTest checks the file's `rows_like` records.
 */
class QueryTest {
    private fun replayed(fn: String) = Misses("$VECTOR $fn").also { SearchReplay.query(fn, it) }.assertNone()

    @Test fun everyRecordIsAFunctionOfTheSeam() {
        val known = SearchReplay.QUERY_FNS.toSet() + ROWS_LIKE
        assertEquals(emptySet(), SearchReplay.queryFunctions() - known)
    }

    @Test fun formsAreTheWordsAndForChineseThePinyinToo() = replayed(FORMS)

    @Test fun patternsAreTheMostSelectiveTwo() = replayed(PATTERNS)

    @Test fun pinyinRunsAreEachChineseWordsSyllablesTogether() = replayed(PINYIN_RUNS)

    @Test fun queriesAreTheFormsReadyToScore() = replayed(QUERIES)

    @Test fun aQueryReadsASongAsItsTitleBothOrItsArtist() = replayed(QUERY)

    @Test fun theBestReadingTiesToTheTitleThenBoth() = replayed(READING)

    @Test fun namesAreReadEachArtistWithTheTitle() = replayed(NAMES_READING)

    companion object {
        const val VECTOR = SearchReplay.QUERY_VECTOR
        const val FORMS = SearchReplay.FORMS
        const val PATTERNS = SearchReplay.PATTERNS
        const val PINYIN_RUNS = SearchReplay.PINYIN_RUNS
        const val QUERIES = SearchReplay.QUERIES
        const val QUERY = SearchReplay.QUERY
        const val READING = SearchReplay.READING
        const val NAMES_READING = SearchReplay.NAMES_READING
        const val ROWS_LIKE = SearchReplay.ROWS_LIKE
    }
}
