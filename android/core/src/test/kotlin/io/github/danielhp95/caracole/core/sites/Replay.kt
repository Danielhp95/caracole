package io.github.danielhp95.caracole.core.sites

import io.github.danielhp95.caracole.core.db.Database
import io.github.danielhp95.caracole.core.db.Db
import io.github.danielhp95.caracole.core.testing.Corpus
import io.github.danielhp95.caracole.core.testing.Fixtures
import io.github.danielhp95.caracole.core.testing.Record
import io.github.danielhp95.caracole.core.testing.TestDb
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.booleanOrNull
import kotlinx.serialization.json.int
import kotlinx.serialization.json.jsonPrimitive
import java.io.File
import kotlin.test.assertEquals
import kotlin.test.assertTrue
import kotlin.test.fail

/**
 * A search vector replayed (vectors/search/<name>.jsonl, tests/test_conformance_search.py): each record's call over
 * its fixture (vectors/search/fixtures/<fixture>.jsonl) replayed into a fresh database, as Python ran it, its answer
 * compared whole with Python's. Each fixture is loaded once, into a folder of [root]'s, and its database read by every
 * record of it. Objects compare as maps, arrays in order, numbers by value (Python's 100.0 is Kotlin's 100.0, its
 * 1100000 a views count), strings, booleans and null exactly.
 */
class Replay(private val vector: String, private val root: () -> File) : AutoCloseable {
    val records: List<Record> = Corpus.records(vector)
    private val databases = LinkedHashMap<String, Database>()

    /** The records of [fn]: there is at least one. */
    fun of(fn: String): List<Record> = records.filter { it.fn == fn }.also {
        assertTrue(it.isNotEmpty(), "$vector has no record of $fn")
    }

    /** The database of [fixture], replayed on first use. */
    fun database(fixture: String): Database = databases.getOrPut(fixture) {
        val dir = File(root(), fixture).also { it.mkdirs() }
        TestDb.fresh(dir).also { database ->
            database.writeBlocking { db -> Fixtures.load(db, "search/fixtures/$fixture.jsonl", File(dir, "library")) }
        }
    }

    /** Every record of [fn] answered by [call] over its fixture; one failure names every record that differs. */
    fun check(fn: String, call: (Db, Record) -> JsonElement) {
        val wanted = of(fn)
        val wrong = wanted.mapNotNull { record ->
            assertEquals(null, record.err, "Python raised on $record")
            val fixture = record.extra.getValue("fixture").jsonPrimitive.content
            try {
                val actual = database(fixture).read { db -> call(db, record) }
                if (same(record.out ?: JsonNull, actual)) null
                else "$fixture ${record.args} ${record.kw}:\n  Python ${record.out}\n  Kotlin $actual"
            } catch (e: Exception) {
                "$fixture ${record.args} ${record.kw}: ${e::class.simpleName}: ${e.message}"
            }
        }
        if (wrong.isNotEmpty()) {
            fail("${wrong.size} of ${wanted.size} $fn records differ:\n" + wrong.take(15).joinToString("\n"))
        }
    }

    override fun close() {
        databases.values.forEach { it.close() }
        databases.clear()
    }

    companion object {
        /** A string argument of a record. */
        fun text(record: Record, at: Int): String = record.args[at].jsonPrimitive.content

        /** An int keyword of a record, else [default]. */
        fun int(record: Record, name: String, default: Int): Int = record.kw[name]?.jsonPrimitive?.int ?: default

        /** A string keyword of a record, else null. */
        fun string(record: Record, name: String): String? =
            (record.kw[name] as? JsonPrimitive)?.takeUnless { it is JsonNull }?.content

        /** A list as Python's plain() writes it. */
        fun list(items: List<JsonElement>): JsonArray = JsonArray(items)

        /** JSON values alike, numbers by value. */
        fun same(a: JsonElement, b: JsonElement): Boolean = when {
            a is JsonObject && b is JsonObject -> a.keys == b.keys && a.all { (k, v) -> same(v, b.getValue(k)) }
            a is JsonArray && b is JsonArray -> a.size == b.size && a.indices.all { same(a[it], b[it]) }
            a is JsonNull || b is JsonNull -> a is JsonNull && b is JsonNull
            a is JsonPrimitive && b is JsonPrimitive -> when {
                a.isString || b.isString -> a.isString && b.isString && a.content == b.content
                a.booleanOrNull != null || b.booleanOrNull != null -> a.booleanOrNull == b.booleanOrNull
                else -> a.content.toDouble() == b.content.toDouble()
            }
            else -> false
        }
    }
}
