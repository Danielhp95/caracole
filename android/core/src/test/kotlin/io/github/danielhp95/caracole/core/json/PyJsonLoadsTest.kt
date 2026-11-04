package io.github.danielhp95.caracole.core.json

import io.github.danielhp95.caracole.core.testing.replays.PyReplay
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.jsonPrimitive
import org.junit.Test
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith
import kotlin.test.assertTrue

/** PyJson.loads and dumps(indent) against json.loads and json.dumps (vectors/py/sites_json.jsonl: the sites' fixture
 * JSON, an edge set, random texts and their mutations, number literals, bytes), and what a corpus line can't hold. */
class PyJsonLoadsTest {
    @Test fun everyRecordAnswersAsJsonDid() = PyReplay.json()

    @Test fun aDuplicateKeyKeepsItsFirstPlaceWithItsLastValue() {
        val v = PyJson.loads("""{"b":1,"a":2,"b":3}""") as JsonObject
        assertEquals(listOf("b", "a"), v.keys.toList())
        assertEquals("3", v.getValue("b").jsonPrimitive.content)
    }

    @Test fun numbersAreLiteralsInPythonsForm() {
        assertEquals("""[100.0, 0, -0.0, Infinity, 1.5, 123456789012345678901234567890, NaN]""",
                     PyJson.dumps(PyJson.loads("[1E2, -0, -0.0, 1e400, 1.50, 123456789012345678901234567890, NaN]")))
    }

    @Test fun aLoneSurrogateEscapeIsOneUtf16Unit() {
        assertEquals("\uD800", PyJson.loads("\"\\ud800\"").jsonPrimitive.content)
        assertEquals("\uD83D\uDE00", PyJson.loads("\"\\ud83d\\ude00\"").jsonPrimitive.content)
        assertEquals("\"\\ud800\"", PyJson.dumps(PyJson.loads("\"\\ud800\""), indent = null, ensureAscii = true))
    }

    @Test fun anErrorsPlaceCountsCodePoints() {
        val e = assertFailsWith<PyJson.DecodeError> { PyJson.loads("[\"\uD83D\uDE00\", 1 2]") }
        assertEquals("Expecting ',' delimiter: line 1 column 9 (char 8)", e.message)
        assertEquals(8, e.pos)
    }

    /** Python's limit is its C stack's (about 50,000 deep); the phone's is MAX_DEPTH, a RecursionError past it,
     * never a StackOverflowError: a text that loads dumps again, with an indent or none, and is digested, on half the
     * stack ART gives a thread. */
    @Test fun nestingPastMaxDepthIsARecursionErrorAndWhatLoadsDumpsAgain() {
        val depth = PyJson.MAX_DEPTH
        for ((open, close) in listOf("[" to "]", "{\"a\":" to "}")) {
            val deepest = open.repeat(depth - 1) + (if (open == "[") "[]" else "{}") + close.repeat(depth - 1)
            val value = PyJson.loads(deepest)
            val written = onASmallStack {
                listOf(PyJson.dumps(value), PyJson.dumps(value, indent = 2), PyJson.dumps(value, indent = null, ensureAscii = true),
                       Canonical.digest(value))
            }
            assertEquals(PyJson.dumps(value), written[0])
            assertTrue(written[1].startsWith(if (open == "[") "[\n  [\n" else "{\n  \"a\": {\n"))
            val past = open + deepest + close
            val e = assertFailsWith<PyJson.RecursionError> { PyJson.loads(past) }
            val kind = if (open == "[") "array" else "object"
            assertEquals("maximum nesting depth ($depth) exceeded while decoding a JSON $kind from a unicode string", e.message)
            assertFailsWith<PyJson.RecursionError> { PyJson.loads(open.repeat(300_000)) }
        }
        val tooDeep = (1..depth).fold(JsonArray(emptyList())) { inner, _ -> JsonArray(listOf(inner)) }
        for (write in listOf<() -> String>({ PyJson.dumps(tooDeep) }, { PyJson.dumps(tooDeep, indent = 2) })) {
            val e = assertFailsWith<PyJson.RecursionError> { write() }
            assertEquals("maximum nesting depth ($depth) exceeded while encoding a JSON object", e.message)
        }
        val caught: IllegalArgumentException = PyJson.RecursionError("x") // what a site parser catches
        assertTrue(caught.message == "x")
    }

    /** [work]'s answer on a thread whose stack is [kib] KiB (ART's own for a lookup's thread is about 1 MiB). */
    private fun <T> onASmallStack(kib: Long = 512, work: () -> T): T {
        var answer: Result<T>? = null
        val small = Thread(null, { answer = runCatching(work) }, "small stack", kib * 1024)
        small.start()
        small.join()
        return answer!!.getOrThrow()
    }

    @Test fun bytesAreReadAsJsonLoadsReadsThem() {
        assertEquals("1", PyJson.dumps(PyJson.loads(byteArrayOf(0xEF.toByte(), 0xBB.toByte(), 0xBF.toByte(), '1'.code.toByte()))))
        assertFailsWith<PyJson.DecodeError> { PyJson.loads("\uFEFF1") }
        assertEquals("\uD800", PyJson.loads(byteArrayOf('"'.code.toByte(), 0xED.toByte(), 0xA0.toByte(), 0x80.toByte(), '"'.code.toByte())).jsonPrimitive.content)
    }

    @Test fun dumpsWithAnIndentIsPythons() {
        val v = JsonObject(mapOf("a" to JsonArray(listOf(JsonPrimitive(1), JsonObject(emptyMap()))), "é" to JsonArray(emptyList())))
        assertEquals("{\n  \"a\": [\n    1,\n    {}\n  ],\n  \"é\": []\n}", PyJson.dumps(v, indent = 2))
        assertEquals("{\n\"a\": [\n1,\n{}\n],\n\"\\u00e9\": []\n}", PyJson.dumps(v, indent = 0, ensureAscii = true))
    }
}
