package io.github.danielhp95.caracole.core.ug.fetch

import io.github.danielhp95.caracole.core.testing.Misses
import io.github.danielhp95.caracole.core.testing.replays.UgFetchReplay
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import org.junit.Assert.assertEquals
import org.junit.Test

/**
 * UgFetch.keepVersion replays vectors/lookup/ug_keep.jsonl: each of keep_version's answers in turn over a library a
 * lookup filled (kept, same, held, sheet, gone, unreadable, closed, no text, unknown), the requests, the rows, the kv
 * (`sheet_versions:yours:`, `sheet_versions:same:`, `ug:unreadable:`) and the files as Python left them.
 */
class KeepVersionTest {
    @Test fun everyAnswerOfKeepVersionIsRecorded() {
        val answers = UgFetchReplay.records(UgFetchReplay.KEEP)
            .flatMap { it.getValue("out").jsonObject.getValue("result").jsonArray.map { a -> a.jsonPrimitive.content } }
        assertEquals(setOf("kept", "same", "held", "sheet", "gone", "unreadable", "closed", "no text", "unknown"),
                     answers.toSet())
    }

    @Test fun everyRecordOfKeepVersionReplays() {
        val misses = Misses(UgFetchReplay.KEEP)
        UgFetchReplay.keep(misses)
        misses.assertNone()
    }
}
