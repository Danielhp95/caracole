package io.github.danielhp95.caracole.core.json

import io.github.danielhp95.caracole.core.testing.Corpus
import io.github.danielhp95.caracole.core.testing.Record
import io.github.danielhp95.caracole.core.testing.TestDb
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.boolean
import kotlinx.serialization.json.jsonPrimitive
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import java.math.BigDecimal
import kotlin.test.assertEquals
import kotlin.test.assertTrue

/** PyJson against json.dumps's vectors (tests/conformance/vectors/canonical/pydumps.jsonl, float_text.jsonl), and
 * Db.kvSetJson's text against db.kv_set_json's. */
class PyJsonTest {
    @get:Rule val tmp = TemporaryFolder()

    private val records = Corpus.records("canonical/pydumps.jsonl")

    private fun Record.sortKeys() = kw["sort_keys"]?.jsonPrimitive?.boolean == true
    private fun Record.compact() = kw["separators"] == JsonArray(listOf(JsonPrimitive(","), JsonPrimitive(":")))
    private fun Record.valueText() = extra.getValue("value").jsonPrimitive.content
    private fun Record.text() = out!!.jsonPrimitive.content

    /** kv_set_json's own call: json.dumps(value, ensure_ascii=False) and nothing more. */
    private fun Record.isKvText() = kw == JsonObject(mapOf("ensure_ascii" to JsonPrimitive(false)))

    private val FLOATS = setOf("NaN", "Infinity", "-Infinity")
    private var made = 0

    /** [value] with each non-integral number a Double made with PyJson.float, as Kotlin code would build it. */
    private fun doubles(value: JsonElement): JsonElement = when {
        value is JsonArray -> JsonArray(value.map(::doubles))
        value is JsonObject -> JsonObject(value.mapValues { doubles(it.value) })
        value !is JsonPrimitive || value.isString -> value
        value.content in FLOATS || (value.content.first().let { it == '-' || it in '0'..'9' } &&
            value.content.any { it == '.' || it == 'e' || it == 'E' }) -> PyJson.float(value.content.toDouble()).also { made++ }
        else -> value
    }

    @Test fun dumpsIsJsonDumpsForEveryVector() {
        assertTrue(records.size > 80)
        for (r in records) {
            // Read by the strict reading and by kotlinx alike: both keep insertion order and each literal.
            for (value in listOf(Canonical.parse(r.valueText()), Json.parseToJsonElement(r.valueText()))) {
                assertEquals(r.text(), PyJson.dumps(value, sortKeys = r.sortKeys(), compact = r.compact()), "${r.kw} of ${r.valueText().take(80)}")
            }
        }
    }

    @Test fun aDoubleMadeWithFloatIsWrittenAsPythonWritesTheFloat() {
        for (r in records) {
            val value = doubles(Canonical.parse(r.valueText()))
            assertEquals(r.text(), PyJson.dumps(value, sortKeys = r.sortKeys(), compact = r.compact()), "${r.kw} of ${r.valueText().take(80)}")
        }
        assertTrue(made > 40) // the floats of the kv values, under each of the four calls
        for (r in Corpus.records("canonical/dumps.jsonl")) {
            assertEquals(r.out!!.jsonPrimitive.content, Canonical.write(doubles(r.args[0])), "dumps of ${r.args[0].toString().take(80)}")
        }
    }

    @Test fun floatTextIsJsonDumpsOfEveryFloatVector() {
        val floats = Corpus.records("canonical/float_text.jsonl")
        assertTrue(floats.size > 4000)
        var other = 0
        for (r in floats) {
            val x = r.args[0].jsonPrimitive.content.toDouble()
            val text = PyJson.floatText(x)
            assertEquals(r.text(), text, "json.dumps of ${r.args[0]} (bits ${java.lang.Long.toHexString(x.toRawBits())})")
            assertEquals(x.toRawBits(), text.toDouble().toRawBits(), "$text reads back as itself")
            if (x.isFinite() && BigDecimal(x.toString()).compareTo(BigDecimal(text)) != 0) other++
        }
        // The vectors hold doubles whose Double.toString digits are another number (5e-324's 4.9E-324 on every JDK).
        assertTrue(other > 0)
    }

    @Test fun compactSortedDumpsIsTheCorpussLineFormat() {
        val line = Corpus.text("canonical/pydumps.jsonl").split('\n')[1]
        assertEquals(line, PyJson.dumps(Json.parseToJsonElement(line), sortKeys = true, compact = true))
    }

    @Test fun kvSetJsonWritesExactlyDbKvSetJsonsText() {
        val kv = records.filter { it.isKvText() }
        assertTrue(kv.size > 20)
        TestDb.fresh(tmp.root).use { database ->
            database.writeBlocking { db ->
                kv.forEachIndexed { k, r ->
                    db.kvSetJson("test:$k", Canonical.parse(r.valueText()))
                    db.kvSetJson("double:$k", doubles(Canonical.parse(r.valueText())))
                }
            }
            database.read { db ->
                kv.forEachIndexed { k, r ->
                    assertEquals(r.text(), db.kvGet("test:$k"), "kv text of ${r.valueText().take(80)}")
                    assertEquals(r.text(), db.kvGet("double:$k"), "kv text of ${r.valueText().take(80)}, its Doubles made")
                    // Read back and written again, a record is the same text.
                    assertEquals(r.text(), PyJson.dumps(db.kvGetJson("test:$k")!!))
                }
            }
        }
    }
}
