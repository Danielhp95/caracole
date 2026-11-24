package io.github.danielhp95.caracole

import io.github.danielhp95.caracole.SiteCatalogues.Age
import io.github.danielhp95.caracole.SiteCatalogues.Asking
import io.github.danielhp95.caracole.SiteCatalogues.FirstStart
import io.github.danielhp95.caracole.SiteCatalogues.Fresh
import io.github.danielhp95.caracole.SiteCatalogues.Source
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
    fun theDateShownIsTheImportedCataloguesNeverThePhonesOwnReads() {
        // The file imported last names its minute: the catalogues' date, whatever the phone read since (a lookup's
        // UG artist page moves IndexTransfer.newest, never this).
        assertEquals(Fresh(Source.CATALOGUES, Instant.parse("2026-11-24T03:12:00Z")),
                     SiteCatalogues.fresh("indexes-s17-20261124T0312Z.sqlite.gz", emptyList()))
        // None imported, none synced: none yet.
        assertNull(SiteCatalogues.fresh(null, emptyList()))
        // A record that is no file's name is none.
        assertNull(SiteCatalogues.fresh("indexes.json", emptyList()))
    }

    @Test
    fun aPhoneSyncedWithAComputerSaysTheComputersIndexesAsItMergedThem() {
        // kv sync:index:<id>: the computer's indexes' stamps, as the phone merged them last, for each computer.
        val studio = """{"gtptabs": "2026-10-30T00:00:00Z", "ug": "2026-11-03T03:12:00Z"}"""
        val desk = """{"lacuerda": "2026-11-01T10:00:00Z"}"""
        assertEquals(Fresh(Source.COMPUTER, Instant.parse("2026-11-03T03:12:00Z")),
                     SiteCatalogues.fresh(null, listOf(studio, desk)))
        // Both: the newer of the two, and the catalogues on a tie.
        assertEquals(Fresh(Source.CATALOGUES, Instant.parse("2026-11-24T03:12:00Z")),
                     SiteCatalogues.fresh("indexes-s17-20261124T0312Z.sqlite.gz", listOf(studio)))
        assertEquals(Fresh(Source.COMPUTER, Instant.parse("2026-11-03T03:12:00Z")),
                     SiteCatalogues.fresh("indexes-s17-20261001T0000Z.sqlite.gz", listOf(studio)))
        assertEquals(Fresh(Source.CATALOGUES, Instant.parse("2026-11-03T03:12:00Z")),
                     SiteCatalogues.fresh("indexes-s17-20261103T0312Z.sqlite.gz", listOf(studio)))
        // What can't be read counts for nothing: not JSON, not an object, a stamp that isn't a time.
        assertEquals(Fresh(Source.COMPUTER, Instant.parse("2026-10-30T00:00:00Z")),
                     SiteCatalogues.fresh(null, listOf("not json", "[1]", null,
                                                       """{"ug": "soon", "gtptabs": "2026-10-30T00:00:00Z", "x": 3}""")))
        assertNull(SiteCatalogues.fresh(null, listOf("{}")))
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
        // 360 to 364 days: still 11 months (of 30 days), never 12, until the year.
        assertEquals(Age(MONTHS, 11), SiteCatalogues.age(now.minusSeconds(360L * 86_400), now))
        assertEquals(Age(MONTHS, 11), SiteCatalogues.age(now.minusSeconds(364L * 86_400), now))
        assertEquals(Age(YEARS, 1), age("2025-11-24T11:00:00Z"))
        assertEquals(Age(YEARS, 3), age("2023-10-01T11:00:00Z"))
    }

    @Test
    fun theFirstStartOffersThemOnceToAPhoneWithNoComputerAndNoIndex() {
        val none = { false }
        assertEquals(FirstStart.OFFER, SiteCatalogues.firstStart(server = "", offered = null, holdsIndex = none))
        assertEquals(FirstStart.OFFER, SiteCatalogues.firstStart(server = "   ", offered = null, holdsIndex = none))
        // An index there already: nothing offered, and decided for good, so no later start looks again.
        assertEquals(FirstStart.DECIDED, SiteCatalogues.firstStart(server = "", offered = null, holdsIndex = { true }))
    }

    @Test
    fun aStartWithAComputerOrAfterTheOfferCountsNothing() {
        // The index is looked at only when nothing cheaper has decided: a computer set, or offered (or decided) before.
        val counted = { error("the index was looked at") }
        assertEquals(FirstStart.NOTHING, SiteCatalogues.firstStart(server = "http://192.168.1.20:8737", offered = null,
                                                                   holdsIndex = counted))
        assertEquals(FirstStart.NOTHING, SiteCatalogues.firstStart(server = "", offered = "2026-11-24T12:00:00Z",
                                                                   holdsIndex = counted))
    }

    @Test
    fun theFileAMeteredNetworkLeftIsReadFromItsRecord() {
        val asking = Asking("indexes-s17-20261124T0312Z.sqlite.gz", 52_000_000)
        assertEquals(asking, SiteCatalogues.asking("""{"name": "indexes-s17-20261124T0312Z.sqlite.gz", "bytes": 52000000}"""))
        assertNull(SiteCatalogues.asking(null))
        assertNull(SiteCatalogues.asking("not json"))
        assertNull(SiteCatalogues.asking("""{"name": "x"}"""))
        assertNull(SiteCatalogues.asking("""{"name": 3, "bytes": 52}"""))
        assertNull(SiteCatalogues.asking("""[1, 2]"""))
    }

    @Test
    fun aJobIsFollowedUntilItIsOver() {
        for (state in listOf("done", "failed", "cancelled", "interrupted")) assertTrue(state, SiteCatalogues.over(state))
        for (state in listOf("queued", "running")) assertFalse(state, SiteCatalogues.over(state))
    }

    @Test
    fun theNewestJobAMeteredNetworkStoppedIsAskedAboutWhoeverQueuedIt() {
        // Settings' Download, the first start's, or the Journal's Try again: the newest catalogues job that stopped at
        // the metered step, with kv catalogues:asking naming its file, is asked about once, until it is answered.
        val asking = Asking("indexes-s17-20261124T0312Z.sqlite.gz", 52_000_000)
        val job = SiteCatalogues.keyOf(41, Instant.parse("2026-11-24T12:00:00.250Z"))
        assertEquals(asking, SiteCatalogues.question("done", "waiting", asking, job, answered = null))
        assertEquals("an older job's answer is no answer of this one's",
                     asking, SiteCatalogues.question("done", "waiting", asking, job,
                                                     SiteCatalogues.keyOf(40, Instant.parse("2026-11-24T11:00:00Z"))))
        assertNull("answered: never asked again", SiteCatalogues.question("done", "waiting", asking, job, answered = job))
        assertNull(SiteCatalogues.question("done", "waiting", null, job, answered = null))
        assertNull(SiteCatalogues.question("done", "ok", asking, job, answered = null))
        assertNull(SiteCatalogues.question("failed", "error", asking, job, answered = null))
        // A job's key is its id and the second it was queued, as the Journal's history keeps them across a restart.
        assertEquals(job, SiteCatalogues.keyOf(41, Instant.parse("2026-11-24T12:00:00Z")))
    }

    @Test
    fun theQuestionPromisesNoWiFiAndSaysNoWiFiItIsnt() {
        // Nothing downloads by itself once on Wi-Fi, and a metered Wi-Fi is no mobile data's absence of Wi-Fi.
        val strings = java.io.File("src/main/res/values/strings.xml").readText()
        val message = Regex("<string name=\"catalogues_asking_message\">([^<]*)</string>").find(strings)!!.groupValues[1]
        val title = Regex("<string name=\"catalogues_asking_title\">([^<]*)</string>").find(strings)!!.groupValues[1]
        assertEquals("%1\$s on a metered network?", title)
        assertTrue(message, message.contains("a Wi-Fi marked metered"))
        assertFalse(message, message.contains("isn\\'t on Wi-Fi"))
        assertFalse(message, Regex("once (it is|on Wi-Fi)|when .*Wi-Fi|by itself on Wi-Fi").containsMatchIn(message))
        assertFalse("no line of the app's waits for Wi-Fi", strings.contains("waiting for Wi-Fi"))
    }

    @Test
    fun theQuestionSaysTheSizeAsTheJobSaysIt() {
        assertEquals("52 MB", SiteCatalogues.size(52_000_000))
        assertEquals("1.2 GB", SiteCatalogues.size(1_200_000_000))
    }
}
