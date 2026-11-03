package io.github.danielhp95.caracole.core.py

import io.github.danielhp95.caracole.core.testing.Corpus
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.int
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonPrimitive
import org.junit.Test
import kotlin.test.assertEquals
import kotlin.test.assertNull
import kotlin.test.assertTrue
import kotlin.test.fail

/** Py against vectors/unicode/py.jsonl: Python's numbers and str methods. */
class PyTest {
    @Test fun everyRecordAnswersAsPythonDid() {
        val wrong = mutableListOf<String>()
        val records = Corpus.records("unicode/py.jsonl")
        val fns = records.map { it.fn }.toSet()
        assertEquals(setOf("round", "sum", "str.split", "str.strip", "len", "slice", "sorted",
                           "collections.Counter.most_common", "bytes.lower", "operator.mod"), fns)
        for (r in records) {
            val a = r.args
            val got: Any? = when (r.fn) {
                "round" -> Py.round(double(a[0]), a[1].jsonPrimitive.int)
                "sum" -> Py.fsum(a[0].jsonArray.map(::double))
                "str.split" -> Py.split(text(a[0]))
                "str.strip" -> Py.strip(text(a[0]))
                "len" -> Py.len(text(a[0]))
                "slice" -> Py.slice(text(a[0]), a[1].intOrNull(), a[2].intOrNull())
                "sorted" -> a[0].jsonArray.map(::text).sortedWith(Py.CODE_POINT_ORDER)
                "collections.Counter.most_common" -> Py.mostCommonFirst(a[0].jsonArray.map(::text))
                "bytes.lower" -> Py.asciiLower(text(a[0]))
                "operator.mod" -> Py.floorMod(a[0].jsonPrimitive.int, a[1].jsonPrimitive.int)
                else -> fail("no Kotlin function for ${r.fn}")
            }
            val out = r.out!!
            val want: Any? = when {
                out is JsonNull -> null
                got is Double -> double(out)
                got is Int -> out.jsonPrimitive.int
                got is List<*> -> out.jsonArray.map(::text)
                else -> text(out)
            }
            // Boxed equality: -0.0 is not 0.0, and NaN is NaN.
            if (got != want && wrong.size < 20) wrong += "${r.fn}${r.args} = $got, Python $want"
        }
        assertTrue(wrong.isEmpty(), wrong.joinToString("\n"))
    }

    private fun text(e: JsonElement): String = e.jsonPrimitive.content
    private fun JsonElement.intOrNull(): Int? = if (this is JsonNull) null else jsonPrimitive.int
    private fun double(e: JsonElement): Double {
        val p = e as JsonPrimitive
        if (p.isString) return when (p.content) {
            "inf" -> Double.POSITIVE_INFINITY
            "-inf" -> Double.NEGATIVE_INFINITY
            "nan" -> Double.NaN
            else -> fail("not a float: $p")
        }
        return p.content.toDouble()
    }

    @Test fun pythonsRoundingAndSums() {
        assertEquals(0.2, Py.round(0.25, 1))
        assertEquals(0.3, Py.round(0.35, 1))
        assertEquals(2.67, Py.round(2.675, 2))
        assertEquals(94.75, Py.round(94.75, 2))
        assertEquals(-0.0, Py.round(-0.04, 1))
        assertEquals(1.0, Py.fsum(List(10) { 0.1 }))
        assertEquals(2.0, Py.fsum(listOf(1e100, 1.0, -1e100, 1.0)))
        assertEquals(0.0, Py.fsum(emptyList()))
        assertEquals(-2, Py.floorMod(3, -5))
    }

    @Test fun stringsAreCodePoints() {
        val s = "a😀b" // a😀b
        assertEquals(3, Py.len(s))
        assertEquals("😀b", Py.slice(s, -2, null))
        assertEquals(listOf(0x61, 0x1F600, 0x62), Py.codePoints(s).toList())
        assertEquals("😀", Py.string(Py.codePoints(s), 1, 2))
        assertTrue(Py.CODE_POINT_ORDER.compare("\uE000", "𐀀") < 0) // U+E000 before U+10000, as Python sorts
        assertEquals(listOf("a", "b"), Py.split("\u0085a\u001cb\u3000"))
        assertEquals("x", Py.strip("\u2028x\u00A0"))
        assertEquals("content-type À\u212a", Py.asciiLower("Content-TYPE À\u212a"))
        assertEquals("b", Py.mostCommonFirst(listOf("b", "a", "a", "b")))
        assertNull(Py.mostCommonFirst(emptyList<String>()))
    }
}
