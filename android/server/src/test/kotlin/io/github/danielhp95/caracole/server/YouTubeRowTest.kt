package io.github.danielhp95.caracole.server

import io.github.danielhp95.caracole.core.health.Health
import io.github.danielhp95.caracole.core.testing.TestDb
import io.github.danielhp95.caracole.server.lookups.AudioRunner
import io.github.danielhp95.caracole.server.lookups.YouTubeSheetRunner
import io.github.danielhp95.caracole.server.page.LibraryPage
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import java.time.Instant
import kotlin.test.assertEquals
import kotlin.test.assertNull

/** Settings' row "YouTube audio" (the phone-youtube design's §7): no row without an engine (a release), whatever the
 * problem says; each state's line in its order; the runs of the last 24 hours, `events` of youtube that ran (ok, error
 * or blocked: never a budget's refusal); a cooldown; out of date for this version alone. */
class YouTubeRowTest {
    @get:Rule val tmp = TemporaryFolder()

    private val on = YouTubeRow.State(engine = true, problem = null, coolingUntil = null, outdated = null,
                                      version = "2026.11.23", runs = 2)

    @Test fun aReleaseHasNoRowWhateverItsProblem() {
        for (problem in listOf(null, LibraryPage.AUDIO_PROBLEM, YouTubeSheetRunner.OFF, YouTubeSheetRunner.NO_YTDLP)) {
            assertNull(YouTubeRow.line(on.copy(engine = false, problem = problem)), "no engine, $problem: no row")
        }
    }

    @Test fun eachStatesLine() {
        assertEquals("On · yt-dlp 2026.11.23 · 2 runs in the last 24 hours", YouTubeRow.line(on))
        assertEquals("On · yt-dlp 2026.11.23 · 1 run in the last 24 hours", YouTubeRow.line(on.copy(runs = 1)))
        assertEquals("On · yt-dlp 2026.11.23 · no runs in the last 24 hours", YouTubeRow.line(on.copy(runs = 0)))
        assertEquals("On · yt-dlp 2026.11.23 · 2 of 50 runs in the last 24 hours", YouTubeRow.line(on.copy(budget = 50)))
        assertEquals("Off (the computer's settings)", YouTubeRow.line(on.copy(problem = YouTubeSheetRunner.OFF)))
        assertEquals("Needs the chord models", YouTubeRow.line(on.copy(problem = AudioRunner.NOT_DOWNLOADED)))
        assertEquals("Chords from audio need Android 13 or later",
                     YouTubeRow.line(on.copy(problem = "chords from audio need Android 13 or later")))
        assertEquals("Cooling down until 2026-11-28 13:00 UTC",
                     YouTubeRow.line(on.copy(coolingUntil = "2026-11-28 13:00 UTC")))
        assertEquals("Out of date: YouTube changed what yt-dlp 2026.11.23 reads: caracole's next release brings a fix",
                     YouTubeRow.line(on.copy(outdated = "2026.11.23")))
        assertEquals("Off (the computer's settings)",
                     YouTubeRow.line(on.copy(problem = YouTubeSheetRunner.OFF, coolingUntil = "later")))
        assertEquals("Cooling down until later", YouTubeRow.line(on.copy(coolingUntil = "later", outdated = "2026.11.23")))
    }

    @Test fun theStateAsTheDatabaseHoldsIt() {
        val database = TestDb.fresh(tmp.newFolder())
        val now = Instant.parse("2026-11-27T12:00:00Z")
        database.writeBlocking { db ->
            for ((at, decision) in listOf("2026-11-26T11:00:00Z" to "ok",     // 25 hours ago: not counted
                                          "2026-11-26T12:30:00Z" to "ok",
                                          "2026-11-27T01:00:00Z" to "error",
                                          "2026-11-27T02:00:00Z" to "blocked",
                                          "2026-11-27T03:00:00Z" to "budget")) {  // refused before any run: not one
                db.execute("INSERT INTO events (run, at, provider, url, status, decision) VALUES ('r', ?, 'youtube', " +
                               "'u', NULL, ?)", at, decision)
            }
            db.execute("INSERT INTO events (run, at, provider, url, status, decision) VALUES ('r', ?, 'lrclib', 'u', " +
                           "200, 'ok')", "2026-11-27T11:30:00Z")
        }
        database.read { db ->
            assertEquals(YouTubeRow.State(true, null, null, null, "2026.11.23", 3, 50),
                         YouTubeRow.of(db, engine = true, problem = null, version = "2026.11.23", now = now))
        }
        database.writeBlocking { db ->
            db.kvSet("youtube-outdated", """{"version": "2026.08.19", "at": "2026-11-27T10:00:00Z", "reason": "x"}""")
        }
        database.read { db ->
            assertNull(YouTubeRow.of(db, true, null, "2026.11.23", now).outdated, "another version's")
            assertEquals("2026.08.19", YouTubeRow.of(db, true, null, "2026.08.19", now).outdated)
        }
        database.writeBlocking { db ->
            db.kvSet("youtube-outdated", """{"version": "2026.08.19", "at": "2026-11-20T12:00:00Z", "reason": "x"}""")
        }
        database.read { db -> assertNull(YouTubeRow.of(db, true, null, "2026.08.19", now).outdated, "7 days on") }
        database.writeBlocking { db -> db.kvSet("youtube-outdated", "not json") }
        database.read { db -> assertNull(YouTubeRow.of(db, true, null, "2026.08.19", now).outdated) }
        database.writeBlocking { db -> Health.recordBlock(db, "youtube", now.minusSeconds(3600), "blocked") }
        database.read { db ->
            assertEquals("Cooling down until 2026-11-28 13:00 UTC",
                         YouTubeRow.line(YouTubeRow.of(db, true, null, "2026.11.23", now)))
        }
        database.close()
    }
}
