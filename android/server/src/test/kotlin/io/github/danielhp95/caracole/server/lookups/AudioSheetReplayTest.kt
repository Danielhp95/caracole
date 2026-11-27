package io.github.danielhp95.caracole.server.lookups

import io.github.danielhp95.caracole.core.testing.Corpus
import io.github.danielhp95.caracole.core.testing.Misses
import io.github.danielhp95.caracole.server.testing.replays.AudioSheetReplay
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.jsonObject
import org.junit.Test
import kotlin.test.assertEquals
import kotlin.test.assertTrue

/** The computer's `caracole audio --upload` against the phone's AudioRunner (vectors/lookup/audio_sheet.jsonl, area
 * `audio-sheet`: AudioSheetReplay's KDoc says what is compared, and what apart), and a record that strays told. */
class AudioSheetReplayTest {
    @Test fun everyJobDoesWhatPythonsDid() {
        val misses = Misses("audio-sheet")
        AudioSheetReplay.replay(misses)
        misses.assertNone()
        assertEquals(12, AudioSheetReplay.cases().size)
    }

    /** The words the phone's job says of its pages are get.py's as staged.py names them (audio_sheet.json's `pdf`),
     * the lookup's own constants, and its stages audio_sheet.py's, the queue's AUDIO_SHEET_STAGES. */
    @Test fun thePagesWordsAndTheStagesAreTheComputersAsRecorded() {
        val data = kotlinx.serialization.json.Json.parseToJsonElement(
            io.github.danielhp95.caracole.server.http.caracoleResource(AudioRunner.DATA)).jsonObject
        val pdf = data.getValue("pdf").jsonObject.mapValues { (it.value as JsonPrimitive).content }
        val LW = io.github.danielhp95.caracole.core.lookup.LookupWords
        assertEquals(mapOf("no_pdfs" to LW.NO_PDFS, "pages_made" to LW.PAGES_MADE, "library_page" to LW.LIBRARY_PAGE), pdf)
        assertEquals(io.github.danielhp95.caracole.server.jobs.JobCommands.AUDIO_SHEET_STAGES, AudioRunner.STAGES)
    }

    private fun edited(record: JsonObject, path: List<String>, value: JsonElement): JsonObject {
        if (path.size == 1) return JsonObject(record + (path[0] to value))
        return JsonObject(record + (path[0] to edited(record.getValue(path[0]).jsonObject, path.drop(1), value)))
    }

    @Test fun aRecordThatStraysIsTold() {
        val first = Corpus.lines(AudioSheetReplay.VECTOR).filter { it["header"] != JsonPrimitive(true) }.first()
        assertEquals(emptyList(), AudioSheetReplay.one(first))
        val strays = mapOf(
            "a stage's words" to edited(first, listOf("out", "result", "result", "details", "audio"), JsonPrimitive("kept")),
            "the exit" to edited(first, listOf("out", "result", "result", "exit"), JsonPrimitive(1)),
            "a request" to edited(first, listOf("out", "requests"), JsonArray(emptyList())),
            "a row" to edited(first, listOf("out", "rows"), JsonObject(emptyMap())),
            "a kv record" to edited(first, listOf("out", "kv"), JsonObject(emptyMap())),
            "a file" to edited(first, listOf("out", "library"), JsonObject(emptyMap())),
            "the store" to edited(first, listOf("out", "store"), JsonObject(emptyMap())),
            "the progress" to edited(first, listOf("out", "result", "progress"), JsonArray(emptyList())),
        )
        for ((what, record) in strays) {
            assertTrue(AudioSheetReplay.one(record).isNotEmpty(), "a record whose $what strays passed")
        }
    }
}
