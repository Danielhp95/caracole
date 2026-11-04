package io.github.danielhp95.caracole.core.testing

import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import org.junit.Assert.fail

/** The answers of one vector (or one area, [name]) that differ from Python's, gathered so that a failure names the
 * first ones; [checked] counts every answer compared. */
class Misses(private val name: String) {
    private val found = ArrayList<String>()
    var checked = 0
        private set

    fun check(ok: Boolean, said: () -> String) {
        checked++
        if (!ok && found.size < 1000) found += said()
    }

    /** [got]'s answer as JSON against [want], Python's (`{"err": …}` when Python raised: then [got] must throw). */
    fun expect(fn: String, args: Any?, want: JsonElement?, got: () -> Any?) {
        val raised = (want as? JsonObject)?.get("err")
        val answer = try {
            json(got())
        } catch (e: Exception) {
            check(raised != null) { "$fn($args) threw $e, Python answered $want" }
            return
        }
        if (raised != null) check(false) { "$fn($args) answered $answer, Python raised $raised" }
        else check(answer == (want ?: JsonNull)) { "$fn(${args.toString().take(120)}) = $answer, Python's $want" }
    }

    fun expect(record: Record, got: () -> Any?) = expect(record.fn, record.args.toString().take(120),
        record.err?.let { JsonObject(mapOf("err" to JsonPrimitive(it))) } ?: record.out, got)

    /** Fails naming the first answers that differ; and, when [required], when nothing was checked at all. */
    fun assertNone(required: Boolean = true) {
        if (required && checked == 0) fail("$name: no record checked")
        if (found.isNotEmpty()) {
            fail("$name: ${found.size} of $checked answers differ from Python's; the first:\n" +
                found.take(25).joinToString("\n"))
        }
    }

    private fun json(value: Any?): JsonElement = when (value) {
        null -> JsonNull
        is JsonElement -> value
        is String -> JsonPrimitive(value)
        is Boolean -> JsonPrimitive(value)
        is Int -> JsonPrimitive(value)
        is Pair<*, *> -> JsonArray(listOf(json(value.first), json(value.second)))
        is List<*> -> JsonArray(value.map { json(it) })
        else -> throw AssertionError("no JSON for $value")
    }
}
