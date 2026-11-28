package io.github.danielhp95.caracole.core.youtube

import io.github.danielhp95.caracole.core.db.Db
import io.github.danielhp95.caracole.core.testing.TestDb
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import java.time.Duration
import java.time.Instant
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertNull
import kotlin.test.assertTrue

/** Out of date (the phone-youtube design's §7): two runs yt-dlp can't read, on two different videos within 24 hours,
 * set kv `youtube-outdated` for that yt-dlp version; a new version or 7 days clear it. */
class OutdatedTest {
    @get:Rule val tmp = TemporaryFolder()

    private val now = Instant.parse("2026-11-27T12:00:00Z")
    private val v = "2026.11.23"

    private fun <T> db(block: (Db) -> T): T = TestDb.fresh(tmp.newFolder()).use { it.writeBlocking(block) }

    @Test fun twoVideosWithin24HoursSetIt() = db { db ->
        assertFalse(Outdated.note(db, v, "aaa", "Unable to extract yt initial data", now.minusSeconds(3600)))
        assertNull(Outdated.state(db, v, now))
        assertTrue(Outdated.note(db, v, "bbb", "nsig extraction failed", now))
        assertEquals("nsig extraction failed", Outdated.state(db, v, now))
        assertFalse(Outdated.note(db, v, "ccc", "again", now), "set already: no second alert")
    }

    @Test fun oneVideoTwiceDoesnt() = db { db ->
        Outdated.note(db, v, "aaa", "x", now.minusSeconds(60))
        assertFalse(Outdated.note(db, v, "aaa", "x", now))
        assertNull(Outdated.state(db, v, now))
    }

    @Test fun twoVideosADayApartDont() = db { db ->
        Outdated.note(db, v, "aaa", "x", now.minus(Duration.ofHours(25)))
        assertFalse(Outdated.note(db, v, "bbb", "x", now))
        assertNull(Outdated.state(db, v, now))
    }

    @Test fun aNewVersionOrSevenDaysClearIt() = db { db ->
        Outdated.note(db, v, "aaa", "x", now.minusSeconds(60))
        Outdated.note(db, v, "bbb", "x", now)
        assertNull(Outdated.state(db, "2026.12.01", now), "another version")
        assertEquals("x", Outdated.state(db, v, now.plus(Duration.ofDays(7)).minusSeconds(1)))
        assertNull(Outdated.state(db, v, now.plus(Duration.ofDays(7))), "7 days on")
        // A new version's videos count apart from the old one's.
        assertFalse(Outdated.note(db, "2026.12.01", "ccc", "x", now))
        assertNull(Outdated.state(db, "2026.12.01", now))
    }

    @Test fun noVersionKnownNeverSetsIt() = db { db ->
        Outdated.note(db, null, "aaa", "x", now.minusSeconds(60))
        assertFalse(Outdated.note(db, null, "bbb", "x", now))
        assertNull(Outdated.state(db, null, now))
    }
}
