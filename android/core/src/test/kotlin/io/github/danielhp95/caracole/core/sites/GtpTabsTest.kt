package io.github.danielhp95.caracole.core.sites

import io.github.danielhp95.caracole.core.config.PhoneConfig
import io.github.danielhp95.caracole.core.config.ProviderPolicy
import io.github.danielhp95.caracole.core.db.Db
import io.github.danielhp95.caracole.core.http.HttpAnswer
import io.github.danielhp95.caracole.core.http.PoliteClient
import io.github.danielhp95.caracole.core.library.LibraryStore
import io.github.danielhp95.caracole.core.library.Overrides
import io.github.danielhp95.caracole.core.library.SongRow
import io.github.danielhp95.caracole.core.lookup.StageContext
import io.github.danielhp95.caracole.core.lookup.StageEnd
import io.github.danielhp95.caracole.core.lookup.sites.GtpTabsStage
import io.github.danielhp95.caracole.core.sites.internal.gtptabs.GtpPass
import io.github.danielhp95.caracole.core.testing.FakeAsking
import io.github.danielhp95.caracole.core.testing.FakeTransport
import io.github.danielhp95.caracole.core.testing.Misses
import io.github.danielhp95.caracole.core.testing.TestDb
import io.github.danielhp95.caracole.core.testing.replays.TabFilesReplay
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import java.io.ByteArrayOutputStream
import java.io.File
import java.time.Instant
import java.util.zip.ZipEntry
import java.util.zip.ZipOutputStream
import kotlin.test.assertEquals
import kotlin.test.assertNull
import kotlin.test.assertTrue

/**
 * gtptabs.py and gtptabs_fetch.py on the phone: every record of vectors/sites/gtptabs*.jsonl and lookup/gtptabs.jsonl
 * answered as Python answered it (TabFilesReplay), and tests/test_gtptabs.py's and test_gtptabs_fetch.py's rules by
 * hand, the lookup's gtptabs stage through FakeAsking.
 */
class GtpTabsTest {
    @get:Rule val tmp = TemporaryFolder()

    private val now: Instant = Instant.parse("2026-11-03T12:00:00Z")

    // --- the corpus ---------------------------------------------------------------------------------------------

    @Test fun everyPageAndFileIsGtptabsPys() {
        val misses = Misses("tab-files: gtptabs.py")
        TabFilesReplay.pages(misses)
        misses.assertNone()
    }

    @Test fun everyTitlePageIsGtptabsFetchPys() {
        val misses = Misses("tab-files: gtptabs_fetch.title_page")
        TabFilesReplay.titlePages(misses)
        misses.assertNone()
    }

    @Test fun everyLookupIsPythons() {
        val misses = Misses("tab-files: gtptabs_fetch.gtptabs_files and get.py's gtptabs stage")
        TabFilesReplay.lookups(misses)
        misses.assertNone()
    }

    // --- pages ----------------------------------------------------------------------------------------------------

    @Test fun anArtistPageAndASongPageAreIndexRows() {
        assertEquals(GtpIndexRow("tabs/2/blur.html", "tabs/2/blur.html", "blur", "", ""),
                     GtpTabsPages.parsePageUrl("http://gtptabs.com/tabs/2/blur.html"))
        assertEquals(GtpIndexRow("tabs/2/blur/song-2-2.html", "tabs/2/blur.html", "blur", "song-2-2", "song-2"),
                     GtpTabsPages.parsePageUrl("http://gtptabs.com/tabs/2/blur/song-2-2.html"))
        assertEquals("beatles", GtpTabsPages.parsePageUrl("http://gtptabs.com/tabs/2/beatles-the/yesterday-13.html")?.artistKey)
        assertEquals("the", GtpTabsPages.parsePageUrl("http://gtptabs.com/tabs/20/the-the.html")?.artistKey)
        for (url in listOf("http://gtptabs.com/ru/tabs/2/blur/country-house.html", "http://gtptabs.com/tabs/2/Blur.html",
                           "https://example.com/tabs/2/blur.html", "http://gtptabs.com/tabs/2/blur/a/b.html")) {
            assertNull(GtpTabsPages.parsePageUrl(url), url)
        }
        // \d is Python's: a digit of any script is one
        assertEquals("tabs/٢/blur.html", GtpTabsPages.parsePageUrl("http://gtptabs.com/tabs/٢/blur.html")?.path)
    }

    @Test fun anArtistIsFiledLastNameFirstToo() {
        assertEquals(listOf("elton-john", "john-elton"), GtpTabsPages.artistKeys("Elton John"))
        assertEquals(listOf("blur"), GtpTabsPages.artistKeys("Blur"))
        assertEquals(emptyList(), GtpTabsPages.artistKeys("!!!"))
        assertEquals("song-2", GtpTabsPages.titleKey("Song 2 - 2012 Remaster"))
        assertEquals("Song 2" to 2, GtpTabsPages.title("Song 2 (2)"))
        assertEquals("Song" to 3, GtpTabsPages.title("Song (٣)"))
        assertEquals("Song (2)\n" to 1, GtpTabsPages.title("Song (2)\n"))
    }

    // --- files ----------------------------------------------------------------------------------------------------

    private fun gp(version: String, word: String = "GUITAR"): ByteArray {
        val head = "FICHIER $word PRO $version".toByteArray(Charsets.US_ASCII)
        return byteArrayOf(head.size.toByte()) + head + ByteArray(30 - head.size) + "filler\n".toByteArray()
    }

    private fun zip(vararg names: String, comment: String? = null): ByteArray {
        val out = ByteArrayOutputStream()
        ZipOutputStream(out).use { z ->
            for (name in names) {
                z.putNextEntry(ZipEntry(name))
                z.write("<x/>".toByteArray())
                z.closeEntry()
            }
            if (comment != null) z.setComment(comment)
        }
        return out.toByteArray()
    }

    @Test fun aFileIsKnownByItsFirstBytes() {
        assertEquals(".gp3", GtpTabsFetch.sniff(gp("v3.00")))
        assertEquals(".gp4", GtpTabsFetch.sniff(gp("v4.06")))
        assertEquals(".gp5", GtpTabsFetch.sniff(gp("L5.10")))
        assertEquals(".gpx", GtpTabsFetch.sniff("BCFZ".toByteArray() + ByteArray(8)))
        assertEquals(".ptb", GtpTabsFetch.sniff("ptab".toByteArray()))
        assertEquals(".gp", GtpTabsFetch.sniff(zip("VERSION", "Content/score.gpif")))
        assertEquals(".gp", GtpTabsFetch.sniff(zip("Content/score.gpif", comment = "a comment, PK")))
        for (data in listOf(ByteArray(0), gp("v1.04", word = "GUITARE"), gp("v6.00"), zip("Content/notes.txt"),
                            "PK\u0003\u0004 not really a zip".toByteArray(), gp("v5.00").copyOf(25),
                            "<!DOCTYPE html><html><body>Too many downloads</body></html>".toByteArray())) {
            assertNull(GtpTabsFetch.sniff(data))
        }
        val gp7 = zip("Content/score.gpif")
        assertNull(GtpTabsFetch.sniff(gp7.copyOf(gp7.size - 1)), "a zip cut short is no file")
    }

    // --- the pass and its stage -----------------------------------------------------------------------------------

    private fun tab(id: Long, stars: Int, version: Int, title: String = "Crocodile Rock", format: String = "gp5",
                    size: Double? = 30.0, instruments: List<String> = emptyList()) =
        GtpTab(id, title, version, "tabs/10/john-elton/x-$id.html", format, stars, size, instruments)

    @Test fun candidatesAreTheTitlesUploadsBestFirst() {
        val song = song("Elton John", "Crocodile Rock")
        val tabs = listOf(tab(9, 3, 1), tab(4, 5, 2), tab(7, 5, 3), tab(3, 5, 3), tab(2, 3, 4),
                          tab(20, 5, 1, instruments = listOf("bass", "drums")), tab(21, 5, 1, size = 6000.0),
                          tab(22, 5, 1, format = "pdf"), tab(23, 5, 1, title = "Rocket Man"),
                          tab(24, 1, 1, instruments = listOf("vocals", "acoustic guitar")), tab(25, 0, 1, size = 5120.0))
        assertEquals(listOf(4L, 3, 7, 9, 2, 24, 25), GtpPass.candidates(song, tabs).map { it.tabId })
        // An upload listed twice is its last listing.
        assertEquals(listOf(3), GtpPass.candidates(song, listOf(tab(5, 5, 1), tab(5, 1, 3))).map { it.version })
    }

    private fun song(artist: String, title: String): SongRow = SongRow(
        id = 1, key = "k", artist = artist, title = title, artists = listOf(artist), album = null, durationMs = null,
        isrc = null, sourceIds = "[]", addedAt = "2026-10-01T00:00:00Z", variant = null, status = "pending",
        review = false, matchDecision = null, matchStep = null, matchScore = null, matchArtistKey = null,
        matchSongKey = null, matchCandidates = "[]", matchedAt = null, ugDirty = false, ugCheckedAt = null,
        lyricsStatus = "pending", lyricsJson = null, lyricsAt = null, lacuerdaCheckedAt = null,
        createdAt = "2026-10-01T00:00:00Z",
    )

    /** The lookup's gtptabs stage over a phone library of one song by Elton John, gtptabs.com's index knowing
     * his page, [answers] the site's by URL. */
    private fun stage(answers: Map<String, HttpAnswer>, artist: String = "Elton John", budget: Long = 6,
                      check: (Db, StageEnd, FakeTransport) -> Unit) {
        val dir = tmp.newFolder()
        TestDb.fresh(dir).use { database ->
            database.writeBlocking { db ->
                db.execute("INSERT INTO gtptabs_index (path, artist_path, artist_key, title_key, base_key, sitemap) " +
                               "VALUES ('tabs/10/john-elton.html', 'tabs/10/john-elton.html', 'john-elton', '', '', '1')")
                val lib = LibraryStore(File(dir, "library"))
                val song = lib.add(db, artist, "Crocodile Rock", now = "2026-10-01T00:00:00Z")
                val transport = FakeTransport(answers.mapKeys { "GET ${it.key}" })
                PoliteClient("gtptabs", ProviderPolicy(budget = budget, delay = 0.0 to 0.0), File(dir, "cache"),
                             PhoneConfig.DEFAULTS.userAgent, transport, sleep = {}, draws = { low, _ -> low },
                             monotonic = { 0.0 }, wallClock = { now }).use { client ->
                    val ctx = StageContext(db, song, Overrides(), PhoneConfig.DEFAULTS, lib,
                                           FakeAsking(mapOf("gtptabs" to client)), now)
                    check(db, GtpTabsStage.run(ctx), transport)
                }
            }
        }
    }

    private val elton = "https://gtptabs.com/tabs/10/john-elton.html"

    @Test fun aSongWhoseArtistTheIndexDoesntKnowWantsNothing() = stage(emptyMap(), artist = "Nobody Known") { _, end, t ->
        assertEquals(StageEnd("skipped", GtpTabsStage.NOT_WANTED), end)
        assertEquals(emptyList(), t.said)
    }

    @Test fun anArtistsPageGoneIsAMissAndNoFileThere() =
        stage(mapOf(elton to FakeTransport.answer(404, "gone"))) { db, end, _ ->
            assertEquals(StageEnd("done", "no file there"), end)
            assertEquals("2026-11-03T12:00:00Z", db.kvGet("gtptabs:checked:1"))
        }

    @Test fun aBlockSkipsTheStageAndMarksNothing() =
        stage(mapOf(elton to FakeTransport.answer(403, "Forbidden"))) { db, end, _ ->
            assertEquals("skipped", end.state)
            assertTrue(end.detail.startsWith("gtptabs.com turned us back (gtptabs: 403: $elton: HTTP 403)"), end.detail)
            assertNull(db.kvGet("gtptabs:checked:1"))
        }

    @Test fun aServerErrorFailsTheStageNeverAMiss() =
        stage(mapOf(elton to FakeTransport.answer(500, "oops"))) { db, end, _ ->
            assertEquals(StageEnd("failed", "gtptabs.com failed (gtptabs: 500: $elton: HTTP 500); tried again tonight"),
                         end)
            assertNull(db.kvGet("gtptabs:checked:1"))
        }

    /** A spent budget is no miss: the stage is skipped and nothing is sent or recorded. Its words are the envelope's
     * (FakeAsking words every spent budget as the lookup's, where Python words a client's budget under
     * `lookup_requests` as the hour's): the corpus records "the stage: the hour's lookup requests spent" and "the
     * stage: the lookup's requests spent", replayed through InteractiveAsk, hold both. */
    @Test fun aSpentBudgetLeavesTheRestToTheNightlyRun() = stage(emptyMap(), budget = 0) { db, end, t ->
        assertEquals("skipped", end.state)
        assertEquals(emptyList(), t.said)
        assertNull(db.kvGet("gtptabs:checked:1"))
    }

    @Test fun aFileKeptIsTheStagesWords() {
        val page = """<html><body><div class="autorInfo"><h1>Artist "Elton John"</h1></div><div class="autorSongs">
            <div class="autorSong gp5"><div class="title"><a href="/tabs/10/john-elton/crocodile-rock.html">Crocodile
            Rock</a><div class="ratingSmall" data-item="1"><a class="active">1</a></div></div>
            <div class="songInfo">(12 Kb)</div></div></div></body></html>"""
        stage(mapOf(elton to FakeTransport.answer(200, page),
                    "https://gtptabs.com/tabs/download/1.html" to HttpAnswer(200, emptyList(), gp("v5.00")))) { db, end, _ ->
            assertEquals(StageEnd("done", GtpTabsStage.KEPT), end)
            assertEquals(listOf("guitar-1.gp5"), db.query("SELECT name FROM files") { it.text(0)!! })
        }
    }

}
