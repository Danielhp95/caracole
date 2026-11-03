package io.github.danielhp95.caracole.core.keys

import io.github.danielhp95.caracole.core.testing.Record
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonPrimitive
import kotlin.test.fail

/** How the keys tests compare the phone with the vectors: a Kotlin answer as JSON, and every miss of a file
 * gathered, so a failure names the first ones with their inputs rather than stopping at one. */
internal class KeyVectors(private val name: String) {
    private val misses = ArrayList<String>()
    var checked = 0
        private set

    /** Compare [got]'s answer with [want], Python's (`{"err": …}` when Python raised: then [got] must throw). */
    fun expect(fn: String, args: List<Any?>, want: JsonElement?, got: () -> Any?) {
        checked++
        val raised = (want as? JsonObject)?.get("err")
        val answer = try {
            json(got())
        } catch (e: Exception) {  // a TODO of a lane not merged yet is an Error: it fails the test as it is
            if (raised == null) misses += "$fn${show(args)} threw $e, Python answered ${want}"
            return
        }
        if (raised != null) misses += "$fn${show(args)} answered $answer, Python raised $raised"
        else if (answer != (want ?: JsonNull)) misses += "$fn${show(args)} = $answer, Python's ${want}"
    }

    /** A record's own answer: `out`, or `{"err": …}`. */
    fun expect(record: Record, got: () -> Any?) =
        expect(record.fn, record.args.map { it.toString() }, record.err?.let { JsonObject(mapOf("err" to JsonPrimitive(it))) } ?: record.out, got)

    fun assertNoMiss() {
        if (checked == 0) fail("$name: no record checked")
        if (misses.isNotEmpty()) {
            fail("$name: ${misses.size} of $checked answers differ from Python's; the first:\n" + misses.take(25).joinToString("\n"))
        }
    }

    private fun show(args: List<Any?>): String = args.joinToString(", ", "(", ")") { it.toString().take(120) }

    companion object {
        fun json(value: Any?): JsonElement = when (value) {
            null -> JsonNull
            is JsonElement -> value
            is String -> JsonPrimitive(value)
            is Boolean -> JsonPrimitive(value)
            is Int -> JsonPrimitive(value)
            is Pair<*, *> -> JsonArray(listOf(json(value.first), json(value.second)))
            is List<*> -> JsonArray(value.map { json(it) })
            else -> error("no JSON for $value")
        }

        fun JsonElement.str(): String = jsonPrimitive.content
        fun JsonElement.strings(): List<String> = jsonArray.map { it.jsonPrimitive.content }
    }
}
