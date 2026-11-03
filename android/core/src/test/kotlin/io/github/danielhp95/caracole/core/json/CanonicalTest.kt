package io.github.danielhp95.caracole.core.json

import io.github.danielhp95.caracole.core.testing.Corpus
import kotlinx.serialization.ExperimentalSerializationApi
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.JsonUnquotedLiteral
import kotlinx.serialization.json.boolean
import kotlinx.serialization.json.int
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonPrimitive
import org.junit.Test
import java.math.BigDecimal
import kotlin.random.Random
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith
import kotlin.test.assertNotEquals
import kotlin.test.assertTrue

/** Canonical against caracole.canonical's vectors (tests/conformance/vectors/canonical/), and the spec's rules. */
@OptIn(ExperimentalSerializationApi::class)
class CanonicalTest {
    private fun JsonElement?.textOrNull(): String? = if (this == null || this is JsonNull) null else jsonPrimitive.content

    @Test fun writeIsPythonsDumpsForEveryVector() {
        val records = Corpus.records("canonical/dumps.jsonl")
        assertTrue(records.size > 50)
        for (r in records) {
            assertEquals(r.out!!.jsonPrimitive.content, Canonical.write(r.args[0]), "dumps of ${r.args[0].toString().take(80)}")
        }
    }

    @Test fun digestIsPythonsDigestForEveryVector() {
        val records = Corpus.records("canonical/digest.jsonl")
        assertTrue(records.size > 50)
        for (r in records) {
            assertEquals(r.out!!.jsonPrimitive.content, Canonical.digest(r.args[0]), "digest of ${r.args[0].toString().take(80)}")
        }
    }

    @Test fun hashStoredJsonIsPythonsStoredHashForEveryVector() {
        val records = Corpus.records("canonical/stored_hash.jsonl")
        assertTrue(records.size > 150)
        for (r in records) {
            val text = r.args[0].textOrNull()
            val shown = text?.take(60)
            assertEquals(r.out.textOrNull(), Canonical.hashStoredJson(text), "stored_hash of $shown")
            if (text == null) continue
            val reads = r.extra.getValue("reads").jsonPrimitive.boolean
            val canonical = r.extra["canonical"].textOrNull()
            if (!reads) {
                assertFailsWith<CanonicalError>("$shown is no JSON") { Canonical.parse(text) }
                continue
            }
            val value = Canonical.parse(text)
            if (canonical != null) {
                assertEquals(canonical, Canonical.write(value), "C of $shown")
                assertEquals(Canonical.sha256Hex(JsonText.utf8(canonical)), Canonical.hashStoredJson(text))
            } else {
                assertFailsWith<CanonicalError>("$shown is not canonicalizable") { Canonical.write(value) }
            }
        }
    }

    @Test fun aTextWithARawLoneSurrogateHashesAsPythonsSurrogatepassBytes() {
        val records = Corpus.records("canonical/stored_hash_utf16.jsonl")
        assertTrue(records.size > 10)
        for (r in records) {
            val units = r.extra.getValue("utf16").jsonArray.map { it.jsonPrimitive.int.toChar() }
            val text = String(units.toCharArray())
            assertEquals(r.out.textOrNull(), Canonical.hashStoredJson(text), "stored_hash of ${units.map { it.code }}")
            val reads = r.extra.getValue("reads").jsonPrimitive.boolean
            if (reads) Canonical.parse(text) else assertFailsWith<CanonicalError> { Canonical.parse(text) }
            r.extra["canonical"].textOrNull()?.let { assertEquals(it, Canonical.write(Canonical.parse(text))) }
        }
    }

    @Test fun keysSortByCodePointNotByUtf16() {
        val keys = listOf("\uD83D\uDE00", "\uFF61", "a", "", "\uD83C\uDFB8", "\uE000", "\uD800")
        assertEquals(listOf("", "a", "\uD800", "\uE000", "\uFF61", "\uD83C\uDFB8", "\uD83D\uDE00"), keys.sortedWith(Canonical.KEY_ORDER))
        assertNotEquals(keys.sorted(), keys.sortedWith(Canonical.KEY_ORDER)) // String.compareTo is UTF-16's
        val value = JsonObject(mapOf("\uD83D\uDE00" to JsonPrimitive(1), "\uFF61" to JsonPrimitive(2)))
        assertEquals("{\"\uFF61\":2,\"\uD83D\uDE00\":1}", Canonical.write(value))
        assertEquals(0, Canonical.KEY_ORDER.compare("ab", "ab"))
        assertTrue(Canonical.KEY_ORDER.compare("a", "ab") < 0 && Canonical.KEY_ORDER.compare("ab", "a") > 0)
    }

    @Test fun aNumberIsWrittenByTheDecimalRuleWhateverMadeItsLiteral() {
        assertEquals("[238,0.0000001,10000000,0,4.5]", Canonical.write(JsonArray(listOf(
            JsonPrimitive(238.0), JsonPrimitive(1e-7), JsonPrimitive(1e7), JsonPrimitive(-0.0), JsonPrimitive(4.5),
        ))))
        assertEquals("[NaN,Infinity,-Infinity]", Canonical.write(JsonArray(listOf(
            JsonPrimitive(Double.NaN), JsonPrimitive(Double.POSITIVE_INFINITY), JsonPrimitive(Double.NEGATIVE_INFINITY),
        ))))
        assertEquals(Canonical.digest(JsonPrimitive(238)), Canonical.hashStoredJson("238.0"))
        assertEquals("0.12345678901234567890123456789012345", Canonical.write(Canonical.parse("0.12345678901234567890123456789012345")))
        assertEquals("1" + "0".repeat(1000), Canonical.write(Canonical.parse("1e1000")))
        assertEquals("1" + "0".repeat(997), Canonical.write(Canonical.parse("0.001e+0001000")))
        for (beyond in listOf("1e1001", "1e-1001", "1e+00001001", "1e" + "9".repeat(5000))) {
            assertFailsWith<CanonicalError>(beyond) { Canonical.write(Canonical.parse(beyond)) }
        }
        for (notANumber in listOf("01", "+1", ".5", "1.", "1e", "0x1", "١", "1_0", "nan")) {
            assertFailsWith<CanonicalError>(notANumber) { Canonical.write(JsonUnquotedLiteral(notANumber)) }
        }
        assertFailsWith<CanonicalError> { Canonical.write(JsonUnquotedLiteral("7".repeat(4301))) }
        assertEquals("7".repeat(4300), Canonical.write(JsonUnquotedLiteral("7".repeat(4300))))
    }

    @Test fun theDecimalRuleIsBigDecimalsExactValuePlain() {
        val random = Random(20261103)
        repeat(5000) {
            val whole = if (random.nextInt(4) == 0) "0" else (1 + random.nextInt(9)).toString() +
                (0 until random.nextInt(9)).joinToString("") { random.nextInt(10).toString() }
            val fraction = if (random.nextInt(5) > 0) "." + (0..random.nextInt(12)).joinToString("") { random.nextInt(10).toString() } else ""
            val exponent = if (fraction.isEmpty() || random.nextBoolean()) {
                listOf("e", "E").random(random) + listOf("", "+", "-").random(random) + random.nextInt(60)
            } else {
                ""
            }
            val literal = (if (random.nextBoolean()) "-" else "") + whole + fraction + exponent
            val exact = BigDecimal(literal).stripTrailingZeros().toPlainString()
            assertEquals(if (BigDecimal(literal).signum() == 0) "0" else exact, Canonical.write(JsonUnquotedLiteral(literal)), literal)
        }
    }

    @Test fun parseKeepsEachLiteralAndTheLastOfARepeatedKeyInTheFirstsPlace() {
        val value = Canonical.parse("{\"a\": 1.50, \"b\": -0, \"a\": [1E2, NaN], \"c\": \"\\ud83c\\udfb8\"}")
        value as JsonObject
        assertEquals(listOf("a", "b", "c"), value.keys.toList())
        assertEquals(JsonArray(listOf(JsonUnquotedLiteral("1E2"), JsonUnquotedLiteral("NaN"))), value["a"])
        assertEquals("-0", value.getValue("b").jsonPrimitive.content)
        assertEquals(JsonPrimitive("\uD83C\uDFB8"), value["c"])
        assertEquals("{\"a\":[100,NaN],\"b\":0,\"c\":\"\uD83C\uDFB8\"}", Canonical.write(value))
    }

    @Test fun aLoneSurrogateIsAnErrorInAValue() {
        assertFailsWith<CanonicalError> { Canonical.write(JsonPrimitive("a\uD800")) }
        assertFailsWith<CanonicalError> { Canonical.write(JsonObject(mapOf("\uDFFF" to JsonNull))) }
        assertFailsWith<CanonicalError> { Canonical.digest(JsonArray(listOf(JsonPrimitive("\uDC00\uD800")))) }
        // Escaped, a lone surrogate reads, and leaves the text to be hashed by its own bytes.
        val text = "\"\\ud800\""
        assertEquals(JsonPrimitive("\uD800"), Canonical.parse(text))
        assertEquals(Canonical.sha256Hex(text.toByteArray(Charsets.US_ASCII)), Canonical.hashStoredJson(text))
    }

    private fun nested(depth: Int) = "[".repeat(depth) + "]".repeat(depth)

    @Test fun nestingDeeperThanMaxDepthIsNotCanonicalizableAndNoDepthOverflowsTheReading() {
        assertEquals(nested(512), Canonical.write(Canonical.parse(nested(512))))
        assertFailsWith<CanonicalError> { Canonical.write(Canonical.parse(nested(513))) }
        val deep = nested(300_000)
        Canonical.parse(deep)
        assertEquals(Canonical.sha256Hex(deep.toByteArray(Charsets.US_ASCII)), Canonical.hashStoredJson(deep))
    }

    @Test fun nullStaysNull() {
        assertEquals(null, Canonical.hashStoredJson(null))
        assertEquals("null", Canonical.write(JsonNull))
    }

    @Test fun ownBytesAreUtf8WithEachLoneSurrogateAsItsThreeBytes() {
        val bytes = JsonText.utf8("a\u00E9\u5B8B\uD83C\uDFB8\uD800")
        assertEquals("61c3a9e5ae8bf09f8eb8eda080", JsonText.hex(bytes))
        assertEquals("e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855", Canonical.sha256Hex(ByteArray(0)))
    }
}
