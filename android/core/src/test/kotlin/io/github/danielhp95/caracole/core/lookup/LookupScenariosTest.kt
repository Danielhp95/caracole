package io.github.danielhp95.caracole.core.lookup

import io.github.danielhp95.caracole.core.testing.Corpus
import io.github.danielhp95.caracole.core.testing.Misses
import io.github.danielhp95.caracole.core.testing.replays.LookupScenariosReplay
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import org.junit.Test
import kotlin.test.assertEquals
import kotlin.test.assertNotNull
import kotlin.test.assertTrue

/** Whole lookups on the phone against the computer's records (LookupScenariosReplay; vectors/lookup/get.jsonl): each
 * record's requests, stage stream, events, rows, kv and files, and that the replay tells a lookup that strays from
 * Python's. commands_get.jsonl is :server's (server.lookups.LookupScenariosCommandsTest). */
class LookupScenariosTest {
    private val records: List<JsonObject> =
        Corpus.lines(LookupScenariosReplay.GET).filter { it["header"] != JsonPrimitive(true) }
    private val cases: List<String> = records.map { it.getValue("case").jsonPrimitive.content }

    @Test
    fun everyWholeLookupDoesWhatCaracoleGetDid() {
        val misses = Misses("lookup-scenarios")
        val replayed = LookupScenariosReplay.replay(LookupScenariosReplay.GET, misses, LookupScenariosReplay.LOOK_UP)
        misses.assertNone()
        assertEquals(cases, replayed)
    }

    @Test
    fun theVectorsHoldEveryCaseTheLaneNames() {
        val wanted = listOf("a new song found", "a tab picked", "a LaCuerda sheet picked", "a block on Ultimate Guitar",
                            "this hour's lookups spent", "kept for sheets", "an ignored song refused",
                            "a tab of a kind caracole doesn't use", "lyrics put together", "through its artist's page",
                            "an error on Ultimate Guitar", "LaCuerda's sheet unpicked", "gtptabs.com and harptabs.com",
                            "gametabs.net", "a harmonica tab picked", "a game's tab picked")
        for (w in wanted) assertTrue(cases.any { w in it }, "no case of $w among $cases")
        val commands = Corpus.lines(LookupScenariosReplay.COMMANDS).filter { it["header"] != JsonPrimitive(true) }
            .map { it.getValue("case").jsonPrimitive.content }
        for (w in listOf("--choose", "--clear")) assertTrue(commands.any { w in it }, "no case of $w among $commands")
    }

    /** Each site asked within a whole lookup keeps what it gave, as the record says: a file of the song's folder. */
    @Test
    fun everySiteKeepsSomethingWithinAWholeLookup() {
        val kept = records.flatMap { r ->
            r.getValue("out").jsonObject.getValue("rows").jsonObject["versions"]?.jsonArray.orEmpty()
                .map { it.jsonObject.getValue("provider").jsonPrimitive.content }
        }.toSet()
        assertEquals(setOf("ug", "lacuerda", "gtptabs", "harptabs", "gametabs"), kept)
    }

    @Test
    fun aLookupThatStraysFromPythonsIsTold() {
        fun result(r: JsonObject): JsonObject = r.getValue("out").jsonObject.getValue("result").jsonObject
        val strays = mapOf<String, (JsonObject) -> JsonObject>(
            "requests" to { r -> r.with("requests", JsonArray(listOf(JsonPrimitive("GET https://example.invalid/")))) },
            "pauses" to { r -> r.with("pauses", JsonPrimitive(99)) },
            "kv" to { r -> r.with("kv", JsonObject(mapOf("lookup:songs" to JsonPrimitive("[]")))) },
            "rows" to { r -> r.with("rows", JsonObject(mapOf("songs" to JsonArray(emptyList())))) },
            "library" to { r -> r.with("library", JsonObject(mapOf("Nobody/Nothing/sheet.txt" to JsonPrimitive("0")))) },
            "progress" to { r -> r.with("result", JsonObject(result(r) + ("progress" to JsonArray(emptyList())))) },
            "result" to { r ->
                val said = result(r).getValue("result").jsonObject
                r.with("result", JsonObject(result(r) + ("result" to JsonObject(said + ("display" to JsonPrimitive("?"))))))
            },
            "events" to { r ->
                val events = r.getValue("out").jsonObject.getValue("events").jsonArray
                r.with("events", if (events.isEmpty()) {
                    JsonArray(listOf(JsonArray(listOf("lookup:x", "ug", "https://example.invalid/", "200", "ok")
                                                   .map(::JsonPrimitive))))
                } else {
                    JsonArray(events.dropLast(1) + JsonArray(events.last().jsonArray.dropLast(1) + JsonPrimitive("blocked")))
                })
            },
        )
        for (case in cases) {
            for ((what, stray) in strays) {
                val misses = Misses("strayed")
                LookupScenariosReplay.replay(LookupScenariosReplay.GET, misses, LookupScenariosReplay.LOOK_UP,
                                             only = setOf(case), edit = stray)
                val failed = runCatching { misses.assertNone() }.exceptionOrNull()
                assertNotNull(failed, "$case: a record whose $what strays passed")
                assertTrue(failed.message.orEmpty().contains("$case: "), "$case: its $what stray isn't told as its own")
            }
        }
    }

    private fun JsonObject.with(field: String, value: JsonElement): JsonObject {
        val inner = getValue("out").jsonObject
        return JsonObject(this + ("out" to JsonObject(inner + (field to value))))
    }
}
