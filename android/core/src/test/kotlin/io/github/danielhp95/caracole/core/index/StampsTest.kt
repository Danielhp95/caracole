package io.github.danielhp95.caracole.core.index

import io.github.danielhp95.caracole.core.testing.Corpus
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.jsonPrimitive
import org.junit.Test
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith
import kotlin.test.assertTrue

/** Stamps against stamps.parse's vectors (tests/conformance/vectors/index/stamps.jsonl): datetime.fromisoformat's C
 * reading, its edges and a seeded sample around them, then the time in UTC. */
class StampsTest {
    @Test fun parseIsStampsParseForEveryVector() {
        val records = Corpus.records("index/stamps.jsonl")
        assertTrue(records.size > 1000)
        var strings = 0
        for (r in records) {
            val value = r.args[0]
            val shown = value.toString()
            when (r.err) {
                null -> {
                    val expected = (r.out as? JsonPrimitive)?.takeIf { it !is JsonNull }?.content
                    assertEquals(expected, Stamps.parse(value)?.let(Stamps::isoformat), shown)
                    if (value is JsonPrimitive && value.isString) {
                        strings++
                        assertEquals(expected, Stamps.parse(value.content)?.let(Stamps::isoformat), shown)
                    }
                }
                "OverflowError" -> assertFailsWith<ArithmeticException>(shown) { Stamps.parse(value) }
                "TypeError" -> assertFailsWith<IllegalArgumentException>(shown) { Stamps.parse(value) }
                else -> error("no such error: ${r.err}")
            }
        }
        assertTrue(strings > 1000)
    }

    @Test fun aStampIsWrittenToTheSecondInUtc() {
        val at = Stamps.parse("2026-10-18T05:30:00.75+02:00")!!
        assertEquals("2026-10-18T03:30:00Z", Stamps.stamp(at))
        assertEquals("2026-10-18T03:30:00.750000+00:00", Stamps.isoformat(at))
        assertEquals("0001-01-01T00:00:00Z", Stamps.stamp(Stamps.parse("0001-01-01")!!))
        assertEquals("9999-12-31T23:59:59Z", Stamps.stamp(Stamps.parse("9999-12-31T23:59:59.999999")!!))
        assertEquals(null, Stamps.parse(null as String?))
        assertEquals("2026-10-18T03:30:00Z", Stamps.stamp(Stamps.parse("2026-10-18T03:30:00Z".jsonPrimitiveOf())!!))
    }

    private fun String.jsonPrimitiveOf() = JsonPrimitive(this).jsonPrimitive
}
