package io.github.danielhp95.caracole.server.lookups

import io.github.danielhp95.caracole.core.testing.Corpus
import io.github.danielhp95.caracole.core.testing.Misses
import io.github.danielhp95.caracole.server.jobs.JobCommands
import io.github.danielhp95.caracole.server.testing.replays.YouTubeSheetReplay
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.jsonObject
import org.junit.Test
import kotlin.test.assertEquals
import kotlin.test.assertTrue

/** The computer's `caracole youtube --song --sheet` against the phone's YouTubeSheetRunner
 * (vectors/lookup/youtube_sheet.jsonl, area `youtube-sheet`: YouTubeSheetReplay's KDoc says what is compared, and what
 * apart), and a record that strays told. */
class YouTubeSheetReplayTest {
    @Test fun everyJobDoesWhatPythonsDid() {
        val misses = Misses("youtube-sheet")
        YouTubeSheetReplay.replay(misses)
        misses.assertNone()
        assertEquals(18, YouTubeSheetReplay.cases().size)
    }

    /** Its stages are youtube_sheet.py's as recorded, the queue's YOUTUBE_SHEET_STAGES. */
    @Test fun theStagesAreTheComputersAsRecorded() {
        assertEquals(JobCommands.YOUTUBE_SHEET_STAGES, YouTubeSheetRunner.Words.stages)
    }

    private fun edited(record: JsonObject, path: List<String>, value: JsonElement): JsonObject {
        if (path.size == 1) return JsonObject(record + (path[0] to value))
        return JsonObject(record + (path[0] to edited(record.getValue(path[0]).jsonObject, path.drop(1), value)))
    }

    @Test fun aRecordThatStraysIsTold() {
        val first = Corpus.lines(YouTubeSheetReplay.VECTOR).filter { it["header"] != JsonPrimitive(true) }.first()
        assertEquals(emptyList(), YouTubeSheetReplay.one(first))
        val strays = mapOf(
            "a stage's words" to edited(first, listOf("out", "result", "result", "details", "audio"), JsonPrimitive("kept")),
            "the exit" to edited(first, listOf("out", "result", "result", "exit"), JsonPrimitive(1)),
            "a run" to edited(first, listOf("out", "runs"), JsonArray(emptyList())),
            "a row" to edited(first, listOf("out", "rows"), JsonObject(emptyMap())),
            "a kv record" to edited(first, listOf("out", "kv"), JsonObject(emptyMap())),
            "an event" to edited(first, listOf("out", "events"), JsonArray(emptyList())),
            "the cache" to edited(first, listOf("out", "youtube"), JsonObject(mapOf("x.m4a" to JsonPrimitive("0")))),
            "the progress" to edited(first, listOf("out", "result", "progress"), JsonArray(emptyList())),
            "the done line" to edited(first, listOf("out", "sent"), JsonPrimitive("3 yt-dlp runs")),
        )
        for ((what, record) in strays) {
            assertTrue(YouTubeSheetReplay.one(record).isNotEmpty(), "a record whose $what strays passed")
        }
    }
}
