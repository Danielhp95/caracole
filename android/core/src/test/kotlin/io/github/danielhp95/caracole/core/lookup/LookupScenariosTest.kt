package io.github.danielhp95.caracole.core.lookup

import io.github.danielhp95.caracole.core.testing.Corpus
import io.github.danielhp95.caracole.core.testing.Misses
import io.github.danielhp95.caracole.core.testing.replays.LookupScenariosReplay
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import org.junit.Test
import kotlin.test.assertEquals
import kotlin.test.assertTrue

/** Whole lookups on the phone against the computer's records (LookupScenariosReplay; vectors/lookup/get.jsonl and
 * commands_get.jsonl): each record's requests, stage stream, events, rows, kv and files, and that the replay tells a
 * lookup that strays from Python's. */
class LookupScenariosTest {
    private val cases: List<String> = listOf(LookupScenariosReplay.GET, LookupScenariosReplay.COMMANDS).flatMap { name ->
        Corpus.lines(name).filter { it["header"] != JsonPrimitive(true) }.map { it.getValue("case").jsonPrimitive.content }
    }

    @Test
    fun everyWholeLookupDoesWhatCaracoleGetDid() {
        val misses = Misses("lookup-scenarios")
        LookupScenariosReplay.replay(misses)
        misses.assertNone()
        println("replayed ${LookupScenariosReplay.replayed.size}: ${LookupScenariosReplay.replayed}")
        println("waiting on: ${LookupScenariosReplay.waiting}")
        // Phase A: the records whose site lanes haven't landed wait for them, each naming its lanes (waiting on).
        assertEquals(cases.toSet(), (LookupScenariosReplay.replayed + LookupScenariosReplay.waiting.keys).toSet())
        assertTrue(LookupScenariosReplay.replayed.isNotEmpty(), "no whole lookup replayed")
    }

    @Test
    fun theVectorsHoldEveryCaseTheLaneNames() {
        val wanted = listOf("a new song found", "a tab picked", "a LaCuerda sheet picked", "a block on Ultimate Guitar",
                            "this hour's lookups spent", "kept for sheets", "an ignored song refused",
                            "a tab of a kind caracole doesn't use", "lyrics put together", "through its artist's page",
                            "an error on Ultimate Guitar", "--choose", "--clear")
        for (w in wanted) assertTrue(cases.any { w in it }, "no case of $w among $cases")
    }

    @Test
    fun aLookupThatStraysFromPythonsIsTold() {
        val strays = listOf<(JsonObject) -> JsonObject>(
            { r -> r.with("out", "requests", JsonArray(listOf(JsonPrimitive("GET https://example.invalid/")))) },
            { r -> r.with("out", "pauses", JsonPrimitive(99)) },
            { r -> r.with("out", "kv", JsonObject(mapOf("lookup:songs" to JsonPrimitive("[]")))) },
            { r -> r.with("out", "rows", JsonObject(mapOf("songs" to JsonArray(emptyList())))) },
            { r -> r.with("out", "library", JsonObject(mapOf("Nobody/Nothing/sheet.txt" to JsonPrimitive("0")))) },
            { r ->
                val said = r.getValue("out").jsonObject.getValue("result").jsonObject
                r.with("out", "result", JsonObject(said + ("progress" to JsonArray(emptyList()))))
            },
        )
        LookupScenariosReplay.replay(Misses("as recorded"))
        val replayed = LookupScenariosReplay.replayed.toSet()
        for (stray in strays) {
            val misses = Misses("strayed")
            LookupScenariosReplay.replay(misses) { r -> if (r["case"]?.jsonPrimitive?.content in replayed) stray(r) else r }
            val failed = runCatching { misses.assertNone() }.isFailure
            assertTrue(failed, "a stray record passed")
        }
    }

    private fun JsonObject.with(member: String, field: String, value: kotlinx.serialization.json.JsonElement): JsonObject {
        val inner = getValue(member).jsonObject
        return JsonObject(this + (member to JsonObject(inner + (field to value))))
    }
}
