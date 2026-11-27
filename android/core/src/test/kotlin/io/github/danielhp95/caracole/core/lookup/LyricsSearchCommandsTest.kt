package io.github.danielhp95.caracole.core.lookup

import io.github.danielhp95.caracole.core.lookup.sites.LyricsSearchCommands
import io.github.danielhp95.caracole.core.testing.Corpus
import io.github.danielhp95.caracole.core.testing.Misses
import io.github.danielhp95.caracole.core.testing.replays.LookupScenariosReplay
import io.github.danielhp95.caracole.core.testing.replays.LyricsSearchReplay
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import io.github.danielhp95.caracole.core.testing.TestDb
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonNull
import org.junit.Test
import java.time.Instant
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith
import kotlin.test.assertTrue

/** `caracole lyrics --as` on the phone against the computer's records (LyricsSearchReplay;
 * vectors/lookup/lyrics_search.jsonl): every search's lines, requests, events, rows and kv; 2 to 4 requests a search. */
class LyricsSearchCommandsTest {
    private val records = Corpus.lines(LyricsSearchReplay.SEARCHES).filter { it["header"] != JsonPrimitive(true) }

    private companion object {
        const val KEPT = "lookup/lyrics_kept.jsonl"
    }

    @Test fun everySearchDoesWhatCaracoleLyricsAsDid() {
        val misses = Misses("lyrics-search")
        val replayed = LookupScenariosReplay.replay(LyricsSearchReplay.SEARCHES, misses, LyricsSearchReplay.SEARCH)
        misses.assertNone()
        assertEquals(records.map { it.getValue("case").jsonPrimitive.content }, replayed)
    }

    @Test fun aSearchThatStraysFromPythonsIsTold() {
        val first = records.first().getValue("case").jsonPrimitive.content
        fun edited(r: JsonObject, edit: (JsonObject) -> JsonObject): JsonObject {
            val out = r.getValue("out").jsonObject
            return JsonObject(r + ("out" to JsonObject(out + edit(out))))
        }
        val strays = listOf<(JsonObject) -> JsonObject>(
            { out -> mapOf("kv" to JsonObject(out.getValue("kv").jsonObject.mapValues { JsonPrimitive("x") })).let(::JsonObject) },
            { out -> mapOf("requests" to JsonArray(emptyList())).let(::JsonObject) },
            { out -> mapOf("result" to JsonObject(mapOf("result" to JsonObject(mapOf("lines" to JsonArray(emptyList()))),
                                                       "progress" to JsonArray(emptyList())))).let(::JsonObject) },
        )
        for (stray in strays) {
            val misses = Misses("lyrics-search")
            LookupScenariosReplay.replay(LyricsSearchReplay.SEARCHES, misses, LyricsSearchReplay.SEARCH, only = setOf(first),
                                         edit = { edited(it, stray) })
            assertFailsWith<AssertionError>("a stray record replayed clean") { misses.assertNone() }
        }
    }

    @Test fun aSearchSendsAtMostFourRequestsAndTheCacheSavesThem() {
        val sent = records.associate {
            it.getValue("case").jsonPrimitive.content to it.getValue("out").jsonObject.getValue("requests").jsonArray.size
        }
        assertTrue(sent.values.all { it in 0..4 }, "$sent")
        assertTrue(sent.values.any { it == 4 } && sent.values.any { it == 2 } && sent.values.any { it == 0 }, "$sent")
    }

    /** lyrics_search.last_search and what reads it (kept_search, pickable, asked_line, row_of) over kv texts kept and
     * edited (vectors/lookup/lyrics_kept.jsonl), within the week and past it, a text that isn't JSON raising. */
    @Test fun aKeptSearchIsReadBackAsPythonReadsIt() {
        val misses = Misses("lyrics-kept")
        val dir = kotlin.io.path.createTempDirectory("caracole-kept").toFile()
        try {
            TestDb.fresh(dir).use { database ->
                for (r in Corpus.lines(KEPT).filter { it["header"] != JsonPrimitive(true) }) {
                    val case = "${r.getValue("case").jsonPrimitive.content} at ${r.getValue("now").jsonPrimitive.content}"
                    val kept = r.getValue("kept")
                    val text = (kept as? JsonObject)?.get("open")?.jsonPrimitive?.content?.toInt()
                        ?.let { "[".repeat(it) + "]".repeat(it) } ?: kept.jsonPrimitive.content
                    val now = Instant.parse(r.getValue("now").jsonPrimitive.content)
                    val got: JsonElement = try {
                        database.writeBlocking { db ->
                            db.kvSet("${LyricsSearchCommands.KV}1", text)
                            val found = LyricsSearchCommands.lastSearch(db, 1, now) ?: return@writeBlocking JsonNull
                            JsonObject(linkedMapOf(
                                "search" to found.json(),
                                "pickable" to JsonPrimitive(LyricsSearchCommands.pickable(found, now)),
                                "asked_line" to JsonPrimitive(LyricsSearchCommands.askedLine(found, now)),
                                "kept" to JsonPrimitive(LyricsSearchCommands.keptSearch(db, 1, now) != null),
                                "row_of" to JsonObject(listOf("lrclib:77", "lrclib:5", "lrclib:0", "megalobiz:5001")
                                                           .associateWith { LyricsSearchCommands.rowOf(found, it)?.json() ?: JsonNull }),
                            ))
                        }
                    } catch (e: IllegalArgumentException) {
                        JsonObject(mapOf("err" to JsonPrimitive("ValueError")))
                    }
                    val want = r["out"] ?: JsonObject(mapOf("err" to r.getValue("err")))
                    misses.check(got == want) { "$case: $got,\n  Python's $want" }
                }
            }
        } finally {
            dir.deleteRecursively()
        }
        misses.assertNone()
    }

    @Test fun aNameIsQuotedForTheShellAsShlexQuotesIt() {
        assertEquals("Blur", LyricsSearchCommands.shellQuoted("Blur"))
        assertEquals("''", LyricsSearchCommands.shellQuoted(""))
        assertEquals("'Sinéad O'\"'\"'Connor - X'", LyricsSearchCommands.shellQuoted("Sinéad O'Connor - X"))
    }
}
