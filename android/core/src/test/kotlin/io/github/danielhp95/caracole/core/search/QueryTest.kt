package io.github.danielhp95.caracole.core.search

import io.github.danielhp95.caracole.core.testing.Corpus
import io.github.danielhp95.caracole.core.testing.Record
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.boolean
import kotlinx.serialization.json.double
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import org.junit.Test
import kotlin.test.assertEquals
import kotlin.test.assertTrue
import kotlin.test.fail

/**
 * search.py's scoring seam against vectors/search/query.jsonl: `_forms`, `_patterns`, `_pinyin_runs`, `_queries`, a
 * `_Query`'s readings, score, name and holds, `_reading` and `_names_reading`, each record Python's answer to the
 * same call (tests/test_conformance_search.py). Scores compare as doubles, with ==. KeySearchTest checks the file's
 * `rows_like` records.
 */
class QueryTest {
    private val records = Corpus.records(VECTOR)

    private fun of(fn: String): List<Record> = records.filter { it.fn == fn }.also {
        assertTrue(it.isNotEmpty(), "$VECTOR has no record of $fn")
    }

    private fun strings(element: JsonElement): List<String> = element.jsonArray.map { it.jsonPrimitive.content }

    private fun reading(element: JsonElement): String? = (element as? JsonPrimitive)?.takeUnless { it is JsonNull }?.content

    /** Every record's mismatch, so one run names them all. */
    private fun check(fn: String, compare: (Record) -> String?) {
        val wrong = of(fn).mapNotNull { record ->
            assertEquals(null, record.err, "Python raised on $record")
            try {
                compare(record)
            } catch (e: Exception) {
                "${record.args}: ${e::class.simpleName}: ${e.message}"
            }
        }
        if (wrong.isNotEmpty()) fail("${wrong.size} of ${of(fn).size} $fn records differ:\n" + wrong.take(20).joinToString("\n"))
    }

    private fun differs(record: Record, expected: Any?, actual: Any?): String? =
        if (expected == actual) null else "${record.args} ${record.kw}: Python $expected, Kotlin $actual"

    @Test fun everyRecordIsAFunctionOfTheSeam() {
        val known = setOf(FORMS, PATTERNS, PINYIN_RUNS, QUERIES, QUERY, READING, NAMES_READING, ROWS_LIKE)
        assertEquals(emptySet(), records.map { it.fn }.toSet() - known)
    }

    @Test fun formsAreTheWordsAndForChineseThePinyinToo() = check(FORMS) { r ->
        differs(r, strings(r.out!!), Queries.forms(r.args[0].jsonPrimitive.content))
    }

    @Test fun patternsAreTheMostSelectiveTwo() = check(PATTERNS) { r ->
        differs(r, strings(r.out!!), Queries.patterns(strings(r.args[0])))
    }

    @Test fun pinyinRunsAreEachChineseWordsSyllablesTogether() = check(PINYIN_RUNS) { r ->
        differs(r, strings(r.out!!), Queries.pinyinRuns(strings(r.args[0])))
    }

    @Test fun queriesAreTheFormsReadyToScore() = check(QUERIES) { r ->
        val expected = r.out!!.jsonArray.map {
            val q = it.jsonObject
            Triple(q.getValue("text").jsonPrimitive.content, q.getValue("compact").jsonPrimitive.content, strings(q.getValue("runs")))
        }
        differs(r, expected, Queries.of(r.args[0].jsonPrimitive.content).map { Triple(it.text, it.compact, it.runs) })
    }

    @Test fun aQueryReadsASongAsItsTitleBothOrItsArtist() = check(QUERY) { r ->
        val (text, runs, artist, title) = r.args
        val q = Query(text.jsonPrimitive.content, strings(runs))
        val a = artist.jsonPrimitive.content
        val t = title.jsonPrimitive.content
        val out = r.out!!.jsonObject
        val readings = out.getValue("readings").jsonArray.map { it.jsonPrimitive.double }
        differs(r, Readings(readings[0], readings[1], readings[2]), q.readings(a, t))
            ?: differs(r, out.getValue("score").jsonPrimitive.double, q.score(a, t))
            ?: differs(r, out.getValue("name").jsonPrimitive.double, q.name(a))
            ?: differs(r, out.getValue("holds").jsonPrimitive.boolean, q.holds(a, t))
    }

    @Test fun theBestReadingTiesToTheTitleThenBoth() = check(READING) { r ->
        val scores = r.args[0].jsonArray.map { triple ->
            val (t, b, a) = triple.jsonArray.map { it.jsonPrimitive.double }
            Readings(t, b, a)
        }
        differs(r, expected(r.out!!), Queries.reading(scores, reading(r.kw.getValue("reading"))))
    }

    @Test fun namesAreReadEachArtistWithTheTitle() = check(NAMES_READING) { r ->
        val queries = Queries.of(r.args[0].jsonPrimitive.content)
        val actual = Queries.namesReading(queries, strings(r.args[1]), r.args[2].jsonPrimitive.content, reading(r.kw.getValue("reading")))
        differs(r, expected(r.out!!), actual)
    }

    private fun expected(out: JsonElement): Reading {
        val (score, via) = out as JsonArray
        return Reading(score.jsonPrimitive.double, via.jsonPrimitive.content)
    }

    companion object {
        const val VECTOR = "search/query.jsonl"
        const val FORMS = "caracole.search._forms"
        const val PATTERNS = "caracole.search._patterns"
        const val PINYIN_RUNS = "caracole.search._pinyin_runs"
        const val QUERIES = "caracole.search._queries"
        const val QUERY = "caracole.search._Query"
        const val READING = "caracole.search._reading"
        const val NAMES_READING = "caracole.search._names_reading"
        const val ROWS_LIKE = "caracole.ug.key_search.rows_like"
    }
}
