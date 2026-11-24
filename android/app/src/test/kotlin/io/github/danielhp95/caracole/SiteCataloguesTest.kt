package io.github.danielhp95.caracole

import io.github.danielhp95.caracole.SiteCatalogues.Age
import io.github.danielhp95.caracole.SiteCatalogues.Asking
import io.github.danielhp95.caracole.SiteCatalogues.Unit.DAYS
import io.github.danielhp95.caracole.SiteCatalogues.Unit.MONTHS
import io.github.danielhp95.caracole.SiteCatalogues.Unit.TODAY
import io.github.danielhp95.caracole.SiteCatalogues.Unit.WEEKS
import io.github.danielhp95.caracole.SiteCatalogues.Unit.YEARS
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import java.time.Instant

class SiteCataloguesTest {
    private val now = Instant.parse("2026-11-24T12:00:00Z")

    @Test
    fun theDateShownIsTheNewestOfTheSitesIndexes() {
        val times = mapOf("ug" to "2026-11-03T03:12:00Z", "lacuerda" to "2026-11-02T10:00:00Z",
                          "gtptabs" to "2026-10-30T00:00:00Z")
        assertEquals(Instant.parse("2026-11-03T03:12:00Z"), SiteCatalogues.newest(times))
        assertNull(SiteCatalogues.newest(emptyMap()))
        // A record caracole can't read as a time is none (Stamps.parse's reading).
        assertEquals(Instant.parse("2026-10-30T00:00:00Z"), SiteCatalogues.newest(mapOf("ug" to "soon",
                                                                                         "gtptabs" to "2026-10-30T00:00:00Z")))
    }

    @Test
    fun theDayIsSaidInEnglishInUtc() {
        assertEquals("3 Nov 2026", SiteCatalogues.day(Instant.parse("2026-11-03T03:12:00Z")))
        assertEquals("31 Dec 2025", SiteCatalogues.day(Instant.parse("2025-12-31T23:59:59Z")))
    }

    @Test
    fun theAgeIsInDaysThenWeeksThenMonthsThenYears() {
        fun age(at: String) = SiteCatalogues.age(Instant.parse(at), now)
        assertEquals(Age(TODAY, 0), age("2026-11-24T03:00:00Z"))
        assertEquals(Age(TODAY, 0), age("2026-11-25T03:00:00Z"))  // a laptop's clock ahead of the phone's
        assertEquals(Age(DAYS, 1), age("2026-11-23T11:00:00Z"))
        assertEquals(Age(DAYS, 13), age("2026-11-11T11:00:00Z"))
        assertEquals(Age(WEEKS, 2), age("2026-11-10T11:00:00Z"))
        assertEquals(Age(WEEKS, 3), age("2026-11-03T03:12:00Z"))
        assertEquals(Age(WEEKS, 8), age("2026-09-26T11:00:00Z"))
        assertEquals(Age(MONTHS, 2), age("2026-09-25T11:00:00Z"))
        assertEquals(Age(MONTHS, 11), age("2025-12-25T11:00:00Z"))
        assertEquals(Age(YEARS, 1), age("2025-11-24T11:00:00Z"))
        assertEquals(Age(YEARS, 3), age("2023-10-01T11:00:00Z"))
    }

    @Test
    fun theFirstStartOffersThemOnceToAPhoneWithNoComputerAndNoIndex() {
        val none = mapOf("ug" to 0L, "lacuerda" to 0L, "gtptabs" to 0L)
        assertTrue(SiteCatalogues.offers(server = "", counts = none, offered = null))
        assertTrue(SiteCatalogues.offers(server = "   ", counts = none, offered = null))
        assertFalse(SiteCatalogues.offers(server = "http://192.168.1.20:8737", counts = none, offered = null))
        assertFalse(SiteCatalogues.offers(server = "", counts = none + ("gtptabs" to 4L), offered = null))
        assertFalse(SiteCatalogues.offers(server = "", counts = none, offered = "2026-11-24T12:00:00Z"))
    }

    @Test
    fun theQuestionIsAskedOfAJobAMeteredNetworkStopped() {
        val asking = Asking("indexes-s17-20261124T0312Z.sqlite.gz", 52_000_000)
        assertEquals(asking, SiteCatalogues.asking("""{"name": "indexes-s17-20261124T0312Z.sqlite.gz", "bytes": 52000000}"""))
        assertNull(SiteCatalogues.asking(null))
        assertNull(SiteCatalogues.asking("not json"))
        assertNull(SiteCatalogues.asking("""{"name": "x"}"""))
        assertNull(SiteCatalogues.asking("""{"name": 3, "bytes": 52}"""))
        assertNull(SiteCatalogues.asking("""[1, 2]"""))

        // Done, its line a wait (the kind's otherwise), and the file it waits for: asked.
        assertEquals(asking, SiteCatalogues.asks("done", "waiting", asking))
        // Imported, up to date, or failed: never asked, whatever an earlier stop left.
        assertNull(SiteCatalogues.asks("done", "ok", asking))
        assertNull(SiteCatalogues.asks("failed", "error", asking))
        assertNull(SiteCatalogues.asks("done", "waiting", null))
    }

    @Test
    fun aJobIsFollowedUntilItIsOver() {
        for (state in listOf("done", "failed", "cancelled", "interrupted")) assertTrue(state, SiteCatalogues.over(state))
        for (state in listOf("queued", "running")) assertFalse(state, SiteCatalogues.over(state))
    }

    @Test
    fun theQuestionSaysTheSizeAsTheJobSaysIt() {
        assertEquals("52 MB", SiteCatalogues.size(52_000_000))
        assertEquals("1.2 GB", SiteCatalogues.size(1_200_000_000))
    }
}
