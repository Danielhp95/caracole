package io.github.danielhp95.caracole

import io.github.danielhp95.caracole.server.lookups.AudioRunner
import io.github.danielhp95.caracole.server.lookups.YouTubeSheetRunner
import org.junit.Test
import java.time.Instant
import kotlin.test.assertEquals
import kotlin.test.assertNull

/** Settings' row "YouTube audio" (the phone-youtube design's §7): each state's line, in its order; the UTC day its runs
 * are counted from; out of date for this version alone. (The app's JVM tests have no SQLite: the reads are
 * YouTubeEndToEndTest's on the device.) */
class YouTubeRowTest {
    private val on = YouTubeRow.State(null, null, null, "2026.11.23", 2, 50)

    @Test fun eachStatesLine() {
        assertEquals("On · yt-dlp 2026.11.23 · 2 of 50 runs today", YouTubeRow.line(on))
        assertEquals("Off (the computer's settings)", YouTubeRow.line(on.copy(problem = YouTubeSheetRunner.OFF)))
        assertEquals("Needs the chord models", YouTubeRow.line(on.copy(problem = AudioRunner.NOT_DOWNLOADED)))
        assertEquals("Chords from audio need Android 13 or later",
                     YouTubeRow.line(on.copy(problem = "chords from audio need Android 13 or later")))
        assertEquals("Cooling down until 2026-11-28 13:00 UTC",
                     YouTubeRow.line(on.copy(coolingUntil = "2026-11-28 13:00 UTC")))
        assertEquals("Out of date: YouTube changed what yt-dlp 2026.11.23 reads: caracole's next release brings a fix",
                     YouTubeRow.line(on.copy(outdated = "2026.11.23")))
        assertNull(YouTubeRow.line(on.copy(problem = YouTubeSheetRunner.NO_YTDLP)), "no yt-dlp in this build: no row")
        // the first that holds: off before a cooldown, a cooldown before out of date
        assertEquals("Off (the computer's settings)",
                     YouTubeRow.line(on.copy(problem = YouTubeSheetRunner.OFF, coolingUntil = "later")))
        assertEquals("Cooling down until later", YouTubeRow.line(on.copy(coolingUntil = "later", outdated = "2026.11.23")))
    }

    @Test fun theDaysRunsAreCountedFromItsFirstSecondInUtc() {
        assertEquals("2026-11-27T00:00:00Z", YouTubeRow.dayOf(Instant.parse("2026-11-27T12:00:00Z")))
        assertEquals("2026-11-27T00:00:00Z", YouTubeRow.dayOf(Instant.parse("2026-11-27T23:59:59Z")))
        assertEquals("2026-11-28T00:00:00Z", YouTubeRow.dayOf(Instant.parse("2026-11-28T00:00:00Z")))
    }

    @Test fun outOfDateOnlyForThisVersion() {
        val kv = """{"version": "2026.08.19", "at": "2026-11-27T10:00:00Z", "reason": "x"}"""
        assertEquals("2026.08.19", YouTubeRow.outdated(kv, "2026.08.19"))
        assertNull(YouTubeRow.outdated(kv, "2026.11.23"), "another version's: a new yt-dlp")
        assertNull(YouTubeRow.outdated(null, "2026.11.23"))
        assertNull(YouTubeRow.outdated("not json", "2026.11.23"))
        assertNull(YouTubeRow.outdated("""{"version": 2026}""", "2026"))
    }
}
