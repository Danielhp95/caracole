package io.github.danielhp95.caracole.core.json

import io.github.danielhp95.caracole.core.testing.Corpus
import io.github.danielhp95.caracole.core.testing.Record
import io.github.danielhp95.caracole.core.testing.TestDb
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.boolean
import kotlinx.serialization.json.jsonPrimitive
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import kotlin.test.assertEquals
import kotlin.test.assertTrue

/** PyJson against json.dumps's vectors (tests/conformance/vectors/canonical/pydumps.jsonl), and Db.kvSetJson's text
 * against db.kv_set_json's. */
class PyJsonTest {
    @get:Rule val tmp = TemporaryFolder()

    private val records = Corpus.records("canonical/pydumps.jsonl")

    private fun Record.sortKeys() = kw["sort_keys"]?.jsonPrimitive?.boolean == true
    private fun Record.compact() = kw["separators"] == JsonArray(listOf(JsonPrimitive(","), JsonPrimitive(":")))
    private fun Record.valueText() = extra.getValue("value").jsonPrimitive.content
    private fun Record.text() = out!!.jsonPrimitive.content

    /** kv_set_json's own call: json.dumps(value, ensure_ascii=False) and nothing more. */
    private fun Record.isKvText() = kw == JsonObject(mapOf("ensure_ascii" to JsonPrimitive(false)))

    @Test fun dumpsIsJsonDumpsForEveryVector() {
        assertTrue(records.size > 80)
        for (r in records) {
            // Read by the strict reading and by kotlinx alike: both keep insertion order and each literal.
            for (value in listOf(Canonical.parse(r.valueText()), Json.parseToJsonElement(r.valueText()))) {
                assertEquals(r.text(), PyJson.dumps(value, sortKeys = r.sortKeys(), compact = r.compact()), "${r.kw} of ${r.valueText().take(80)}")
            }
        }
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
                kv.forEachIndexed { k, r -> db.kvSetJson("test:$k", Canonical.parse(r.valueText())) }
            }
            database.read { db ->
                kv.forEachIndexed { k, r ->
                    assertEquals(r.text(), db.kvGet("test:$k"), "kv text of ${r.valueText().take(80)}")
                    // Read back and written again, a record is the same text.
                    assertEquals(r.text(), PyJson.dumps(db.kvGetJson("test:$k")!!))
                }
            }
        }
    }
}
