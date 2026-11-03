package io.github.danielhp95.caracole.core.fuzz

import io.github.danielhp95.caracole.core.testing.Corpus
import io.github.danielhp95.caracole.core.testing.Record
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.double
import kotlinx.serialization.json.int
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import org.junit.Test
import kotlin.test.assertEquals
import kotlin.test.assertTrue

/** core.fuzz.Fuzz gives rapidfuzz 3.14.5's every answer in vectors/fuzz/ (tests/test_conformance_fuzz.py), each
 * double equal with `==`. */
class FuzzTest {
    private fun arg(r: Record, i: Int) = r.args[i].jsonPrimitive.content

    /** Every record whose answer differs, for a message naming the first few. */
    private fun <T> mismatches(name: String, records: List<Record>, expected: (Record) -> T, got: (Record) -> T): List<String> =
        records.mapNotNull { r ->
            val want = expected(r)
            val have = got(r)
            if (want == have) null else "$name ${r.args} (${r.extra["case"]}): rapidfuzz $want, Fuzz $have"
        }

    private fun assertAll(name: String, records: List<Record>, mismatched: List<String>) {
        assertTrue(records.size > 6000, "$name holds ${records.size} records")
        assertTrue(mismatched.isEmpty(), "${mismatched.size} of ${records.size} differ:\n" + mismatched.take(10).joinToString("\n"))
    }

    @Test fun ratioIsRapidfuzzsOnEveryPair() {
        val records = Corpus.records("fuzz/ratio.jsonl")
        assertAll("ratio", records, mismatches("ratio", records, { it.out!!.jsonPrimitive.double }) {
            Fuzz.ratio(arg(it, 0), arg(it, 1))
        })
    }

    @Test fun tokenSortRatioIsRapidfuzzsOnEveryPair() {
        val records = Corpus.records("fuzz/token_sort.jsonl")
        assertAll("token_sort", records, mismatches("token_sort", records, { it.out!!.jsonPrimitive.double }) {
            Fuzz.tokenSortRatio(arg(it, 0), arg(it, 1))
        })
    }

    @Test fun partialRatioAlignmentIsRapidfuzzsOnEveryPair() {
        val records = Corpus.records("fuzz/partial_alignment.jsonl")
        assertAll("partial_alignment", records, mismatches("partial_alignment", records, { r ->
            val o = r.out!!.jsonObject
            Fuzz.Alignment(o["score"]!!.jsonPrimitive.double, o["src_start"]!!.jsonPrimitive.int,
                o["src_end"]!!.jsonPrimitive.int, o["dest_start"]!!.jsonPrimitive.int, o["dest_end"]!!.jsonPrimitive.int)
        }) { Fuzz.partialRatioAlignment(arg(it, 0), arg(it, 1)) })
    }

    @Test fun extractIsRapidfuzzsWithItsTiesAndCutoffs() {
        val records = Corpus.records("fuzz/extract.jsonl")
        assertTrue(records.size > 800, "extract holds ${records.size} records")
        val mismatched = mismatches("extract", records, { r ->
            r.out!!.jsonArray.map { row ->
                val (choice, score, index) = row.jsonArray
                Fuzz.Extracted(choice.jsonPrimitive.content, score.jsonPrimitive.double, index.jsonPrimitive.int)
            }
        }) { r ->
            assertEquals("rapidfuzz.fuzz.ratio", r.kw["scorer"]!!.jsonPrimitive.content)
            val limit = r.kw["limit"].takeUnless { it == null || it is JsonNull }?.jsonPrimitive?.int
            Fuzz.extract(arg(r, 0), (r.args[1] as JsonArray).map { it.jsonPrimitive.content },
                r.kw["score_cutoff"]!!.jsonPrimitive.double, limit)
        }
        assertTrue(mismatched.isEmpty(), "${mismatched.size} of ${records.size} differ:\n" + mismatched.take(10).joinToString("\n"))
    }

    @Test fun theSearchTestsPairAlignsWhereRapidfuzzPutsIt() {
        assertEquals(Fuzz.Alignment(80.0, 0, 5, 19, 24), Fuzz.partialRatioAlignment("banma", "song dongye ban ma ban ma"))
        assertEquals(100.0, Fuzz.ratio("", ""))
        assertEquals(0.0, Fuzz.ratio("", "a"))
    }

    @Test fun aStringIsItsCodePoints() {
        assertEquals(listOf(0x61, 0x1F600, 0x4E2D), Fuzz.codePoints("a😀中").toList())
        assertEquals(listOf(0xD800, 0x61), Fuzz.codePoints("\uD800a").toList())  // a lone surrogate is itself
        // One code point of a supplementary character: 'a' and '😀' are as far apart as 'a' and 'b'.
        assertEquals(Fuzz.ratio("ab", "aa"), Fuzz.ratio("a😀", "aa"))
    }

    @Test fun nbspIsASpaceOnlyInAStringCpythonStoresWide() {
        assertTrue(Fuzz.tokenSortRatio("b a", "a b") < 100.0)
        assertEquals(100.0, Fuzz.tokenSortRatio("b aĀ", "aĀ b"))
        assertEquals(100.0, Fuzz.tokenSortRatio("b\u0085a😀", "a😀 b"))
    }

    @Test fun theBitParallelLcsIsTheDynamicProgrammesAcrossBlocks() {
        val random = java.util.Random(7)
        repeat(500) {
            val a = IntArray(random.nextInt(200)) { 0x61 + random.nextInt(4) }
            val b = IntArray(random.nextInt(200)) { 0x61 + random.nextInt(4) }
            assertEquals(dynamicLcs(a, b), Fuzz.lcs(Fuzz.Pattern(a), b), "${a.size} × ${b.size}")
        }
    }

    private fun dynamicLcs(a: IntArray, b: IntArray): Int {
        var prev = IntArray(b.size + 1)
        for (x in a) {
            val cur = IntArray(b.size + 1)
            for (j in b.indices) cur[j + 1] = if (x == b[j]) prev[j] + 1 else maxOf(prev[j + 1], cur[j])
            prev = cur
        }
        return prev[b.size]
    }
}
