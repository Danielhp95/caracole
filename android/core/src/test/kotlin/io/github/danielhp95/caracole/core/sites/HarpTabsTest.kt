package io.github.danielhp95.caracole.core.sites

import io.github.danielhp95.caracole.core.config.PhoneConfig
import io.github.danielhp95.caracole.core.config.ProviderPolicy
import io.github.danielhp95.caracole.core.db.Db
import io.github.danielhp95.caracole.core.http.HttpAnswer
import io.github.danielhp95.caracole.core.http.PoliteClient
import io.github.danielhp95.caracole.core.index.Reads
import io.github.danielhp95.caracole.core.library.LibraryStore
import io.github.danielhp95.caracole.core.library.Overrides
import io.github.danielhp95.caracole.core.library.SongRow
import io.github.danielhp95.caracole.core.lookup.StageContext
import io.github.danielhp95.caracole.core.lookup.sites.HarpTabsStage
import io.github.danielhp95.caracole.core.sites.internal.harptabs.HarpTabsPages
import io.github.danielhp95.caracole.core.testing.FakeAsking
import io.github.danielhp95.caracole.core.testing.FakeTransport
import io.github.danielhp95.caracole.core.testing.Misses
import io.github.danielhp95.caracole.core.testing.TestDb
import io.github.danielhp95.caracole.core.testing.replays.HarpTabsReplay
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import java.io.File
import java.time.Instant
import kotlin.test.assertEquals
import kotlin.test.assertNull
import kotlin.test.assertTrue

/** harptabs.com on the phone: vectors/sites/harptabs.jsonl, lookup/harptabs.jsonl and lookup/harptabs_artist.jsonl
 * answered as Python answered them, and the rules harptabs*.py's own tests hold that need no page parsed. */
class HarpTabsTest {
    @get:Rule val tmp = TemporaryFolder()

    private val now: Instant = Instant.parse("2026-11-03T12:00:00Z")
    private val stamp = "2026-11-03T12:00:00Z"

    @Test fun everyRecordIsAnsweredAsPythonAnsweredIt() {
        val misses = Misses("harptabs")
        HarpTabsReplay.pages(misses)
        HarpTabsReplay.lookups(misses)
        HarpTabsReplay.artists(misses)
        misses.assertNone()
        assertTrue(misses.checked > 900, "answers checked: ${misses.checked}")
    }

    @Test fun aTabsKeyJoinsAContractionsEndToItsWordWhicheverWayTheSlugWroteIt() {
        for (slug in listOf("can-t-help-falling-in-love", "cant-help-falling-in-love")) {
            assertEquals("cant-help-falling-in-love", HarpTabsPages.parsePageUrl("${HarpTabs.BASE_URL}/tab/1/$slug")?.key)
        }
        assertEquals(HarpTabsPages.IndexRow("tab/89/la-bamba", "tab", 89, "la-bamba"),
                     HarpTabsPages.parsePageUrl("https://harptabs.com/tab/89/la-bamba"))
        assertEquals("guns-n-roses", HarpTabsPages.parsePageUrl("${HarpTabs.BASE_URL}/artist/5/guns-n-roses")?.key)
        assertNull(HarpTabsPages.parsePageUrl("${HarpTabs.BASE_URL}/artist/4"))  // the catch-all: no slug, no row
        assertEquals(listOf("cant-help-falling-in-love"), HarpTabsPages.titleKeys("Can't Help Falling in Love"))
        assertEquals(listOf("obriens-lament", "o-briens-lament"), HarpTabsPages.titleKeys("O'Brien's Lament"))
    }

    @Test fun viewsAndRatingsAreReadAsPythonsFloatReadsThem() {
        assertEquals(1_100_000, HarpTabsPages.views("1.1M"))
        assertEquals(57_000, HarpTabsPages.views("57k"))
        assertEquals(12_000, HarpTabsPages.views("١٢k"))  // Python's \d and float(): a digit of any script
        assertEquals(0, HarpTabsPages.views("12x"))
        assertEquals(0, HarpTabsPages.views(null))
        assertEquals(4.0, HarpTabsPages.rating(" 4.0 "))
        assertNull(HarpTabsPages.rating("5.0001"))
        assertNull(HarpTabsPages.rating("nan"))
    }

    // --- a lookup's stage, with no page parsed --------------------------------------------------------------------

    private fun <T> db(block: (Db) -> T): T = TestDb.fresh(tmp.newFolder()).use { it.writeBlocking(block) }

    private fun index(db: Db, vararg paths: String) {
        for (path in paths) {
            val row = HarpTabsPages.parsePageUrl(HarpTabsPages.pageUrl(path))!!
            db.execute("INSERT INTO harptabs_index (path, kind, page_id, key, sitemap) VALUES (?, ?, ?, ?, 'sitemap')",
                       row.path, row.kind, row.pageId, row.key)
        }
    }

    private fun song(db: Db, lib: LibraryStore, artist: String, title: String): SongRow =
        lib.add(db, artist, title, now = "2026-10-01T00:00:00Z")

    private fun client(cache: File, answers: Map<String, HttpAnswer>, budget: Long = 6) = PoliteClient(
        "harptabs", ProviderPolicy(budget = budget, delay = 0.0 to 0.0), cache, PhoneConfig.DEFAULTS.userAgent,
        FakeTransport(answers), sleep = {}, draws = { low, _ -> low }, monotonic = { 0.0 }, wallClock = { now })

    private fun stage(db: Db, lib: LibraryStore, song: SongRow, client: PoliteClient) = HarpTabsStage.run(
        StageContext(db, song, Overrides.read(db), PhoneConfig.DEFAULTS, lib, FakeAsking(mapOf("harptabs" to client)), now))

    @Test fun aSongWhoseArtistTheSitemapDoesntListIsSkippedAndCostsNoPage() = db { db ->
        index(db, "artist/1178/billy-joel", "tab/6/silent-night")
        val lib = LibraryStore(tmp.newFolder())
        val end = stage(db, lib, song(db, lib, "Mariah Carey", "Silent Night"), client(tmp.newFolder(), emptyMap()))
        assertEquals("skipped" to HarpTabsStage.NOT_TRIED, end.state to end.detail)
    }

    @Test fun aBlockEndsTheStageAndNothingIsMarkedNotFound() = db { db ->
        index(db, "artist/7829/ritchie-valens", "tab/89/la-bamba")
        val lib = LibraryStore(tmp.newFolder())
        val bamba = song(db, lib, "Ritchie Valens", "La Bamba")
        val c = client(tmp.newFolder(), mapOf("GET ${HarpTabs.BASE_URL}/tab/89/la-bamba" to FakeTransport.answer(403, "no")))
        val end = stage(db, lib, bamba, c)
        assertEquals("skipped", end.state)
        assertEquals("harptabs.com blocked caracole (harptabs: 403: ${HarpTabs.BASE_URL}/tab/89/la-bamba: HTTP 403): no " +
                         "more requests to it until later. Nothing was marked not found.", end.detail)
        assertNull(db.kvGet("${HarpTabsFetch.CHECKED_PREFIX}${bamba.id}"))
    }

    @Test fun aServerErrorFailsTheStageAndTheSongWaits() = db { db ->
        index(db, "artist/7829/ritchie-valens", "tab/89/la-bamba")
        val lib = LibraryStore(tmp.newFolder())
        val bamba = song(db, lib, "Ritchie Valens", "La Bamba")
        val c = client(tmp.newFolder(), mapOf("GET ${HarpTabs.BASE_URL}/tab/89/la-bamba" to FakeTransport.answer(530, "x")))
        val end = stage(db, lib, bamba, c)
        assertEquals("failed" to "harptabs.com failed (harptabs: 530: ${HarpTabs.BASE_URL}/tab/89/la-bamba: HTTP 530); " +
                         "the nightly run tries again", end.state to end.detail)
        assertNull(db.kvGet("${HarpTabsFetch.CHECKED_PREFIX}${bamba.id}"))
    }

    @Test fun candidatesGoneAreAMissAskedAgainAfter30Days() = db { db ->
        index(db, "artist/1178/billy-joel", "tab/25/piano-man", "tab/29525/piano-man")
        val lib = LibraryStore(tmp.newFolder())
        val piano = song(db, lib, "Billy Joel", "Piano Man")
        val gone = FakeTransport.answer(404, "<html><body>Not found</body></html>")
        val c = client(tmp.newFolder(), mapOf("GET ${HarpTabs.BASE_URL}/tab/25/piano-man" to gone,
                                              "GET ${HarpTabs.BASE_URL}/tab/29525/piano-man" to gone))
        val end = stage(db, lib, piano, c)
        assertEquals("done" to HarpTabsStage.NONE_THERE, end.state to end.detail)
        assertEquals(stamp, db.kvGet("${HarpTabsFetch.CHECKED_PREFIX}${piano.id}"))
        assertEquals(2, c.requestsMade)
        val again = stage(db, lib, piano, client(tmp.newFolder(), emptyMap()))  // within 30 days: no request
        assertEquals("skipped", again.state)
    }

    @Test fun theCandidatesAreAtMostEightLowestIdFirst() = db { db ->
        index(db, "artist/1178/billy-joel", *(100 until 120).map { "tab/$it/piano-man" }.toTypedArray())
        val lib = LibraryStore(tmp.newFolder())
        val gone = FakeTransport.answer(404)
        val answers = (100 until 120).associate { "GET ${HarpTabs.BASE_URL}/tab/$it/piano-man" to gone }
        val transport = FakeTransport(answers)
        val c = PoliteClient("harptabs", ProviderPolicy(budget = 40, delay = 0.0 to 0.0), tmp.newFolder(),
                             PhoneConfig.DEFAULTS.userAgent, transport, sleep = {}, draws = { low, _ -> low },
                             monotonic = { 0.0 }, wallClock = { now })
        stage(db, lib, song(db, lib, "Billy Joel", "Piano Man"), c)
        assertEquals((100 until 108).map { "GET ${HarpTabs.BASE_URL}/tab/$it/piano-man" }, transport.said)
        assertTrue(transport.requests.all { r -> r.headers.any { it.first == "User-Agent" && it.second == PhoneConfig.DEFAULTS.userAgent } })
    }

    // --- an artist's page stored, and noted for the next push ------------------------------------------------------

    @Test fun anArtistPageStoredIsNotedForTheNextPushToTheComputer() = db { db ->
        index(db, "artist/1178/billy-joel")
        val page = HarpArtistPage("billy joel", 98, listOf(HarpListedTab(25, "tab/25/piano-man", "piano man", "C",
                                                                        "Beginner", 1_100_000, 4.0)))
        HarpTabsFetch.storeArtistPage(db, "artist/1178/billy-joel", page, now)
        assertEquals(stamp, db.kvGet("${Reads.READ}harptabs:artist/1178/billy-joel"))
        assertEquals(mapOf("harptabs" to listOf("artist/1178/billy-joel")), Reads.since(db, "computer"))
        assertEquals(listOf(listOf<Any?>(1178L, "billy-joel", "billy joel", 98L, stamp)), db.query(
            "SELECT page_id, key, name, tabs, read_at FROM harptabs_artists") { listOf(it.long(0), it.text(1), it.text(2), it.long(3), it.text(4)) })
        assertEquals(listOf(listOf<Any?>(25L, "piano-man", "C", 1_100_000L, 4.0, 0L)), db.query(
            "SELECT tab_id, song_key, harp_key, views, rating, place FROM harptabs_artist_tabs") {
            listOf(it.long(0), it.text(1), it.text(2), it.long(3), it.double(4), it.long(5))
        })
        HarpTabsFetch.storeGone(db, "artist/1178/billy-joel", now.plusSeconds(60))
        assertEquals(0, db.one("SELECT COUNT(*) FROM harptabs_artist_tabs") { it.long(0)!!.toInt() })
        assertEquals("", db.one("SELECT name FROM harptabs_artists") { it.text(0) })
        assertEquals("2026-11-03T12:01:00Z", db.kvGet("${Reads.READ}harptabs:artist/1178/billy-joel"))
    }

    @Test fun anArtistsPagesByNamePathOrAddress() = db { db ->
        index(db, "artist/50/the-beatles", "artist/1178/billy-joel", "artist/7829/ritchie-valens")
        assertEquals(listOf("artist/1178/billy-joel"), HarpTabsFetch.artistPaths(db, "Billy  Joel"))
        assertEquals(listOf("artist/50/the-beatles"), HarpTabsFetch.artistPaths(db, "beatles"))
        assertEquals(listOf("artist/7829/ritchie-valens"),
                     HarpTabsFetch.artistPaths(db, "harptabs.com/artist/7829/ritchie-valens"))
        assertEquals(emptyList(), HarpTabsFetch.artistPaths(db, "artist/9/nobody"))
    }
}
