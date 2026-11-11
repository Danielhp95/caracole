package io.github.danielhp95.caracole.core.lacuerda

import io.github.danielhp95.caracole.core.config.PhoneConfig
import io.github.danielhp95.caracole.core.config.ProviderPolicy
import io.github.danielhp95.caracole.core.db.Db
import io.github.danielhp95.caracole.core.http.Client
import io.github.danielhp95.caracole.core.http.PoliteClient
import io.github.danielhp95.caracole.core.index.Stamps
import io.github.danielhp95.caracole.core.library.Kept
import io.github.danielhp95.caracole.core.library.LaCuerdaPick
import io.github.danielhp95.caracole.core.library.LibraryStore
import io.github.danielhp95.caracole.core.library.Overrides
import io.github.danielhp95.caracole.core.library.SongRow
import io.github.danielhp95.caracole.core.library.Songs
import io.github.danielhp95.caracole.core.library.Versions
import io.github.danielhp95.caracole.core.lookup.Asked
import io.github.danielhp95.caracole.core.lookup.Asking
import io.github.danielhp95.caracole.core.lookup.StageContext
import io.github.danielhp95.caracole.core.lookup.StageEnd
import io.github.danielhp95.caracole.core.lookup.sites.LaCuerdaPickStage
import io.github.danielhp95.caracole.core.lookup.sites.LaCuerdaStage
import io.github.danielhp95.caracole.core.testing.FakeAsking
import io.github.danielhp95.caracole.core.testing.FakeTransport
import io.github.danielhp95.caracole.core.testing.Misses
import io.github.danielhp95.caracole.core.testing.TestDb
import io.github.danielhp95.caracole.core.testing.replays.LaCuerdaReplay
import kotlinx.serialization.json.JsonObject
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import java.io.File
import java.time.Instant
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertTrue

/** lacuerda_fetch.py for a lookup's song against Python's answers (vectors/lookup/lacuerda_sheets.jsonl), and get.py's
 * LaCuerda stages, worded as get.py words them, over what a corpus line can't hold (a fake site, a fake asking). */
class LaCuerdaSheetsTest {
    @get:Rule val folder = TemporaryFolder()

    private val now = Instant.parse("2026-11-03T12:00:00Z")
    private val stamp = Stamps.of(now)
    private val soda = "https://acordes.lacuerda.net/soda_stereo/"

    /** A sheet kept, picked, or not replacing a better one; the artist's slugs in order, a 404 or "aqui llega:" moving
     * on; the index's rows; sheet.json; the misses and errors; read_artist_page; and get.py's words for each of the
     * stage's own ends, and what its work raises. */
    @Test fun everySheetScenarioReplays() = Misses("lookup/lacuerda_sheets.jsonl").also { LaCuerdaReplay.sheets(it) }.assertNone()

    private fun <T> world(block: (Db, LibraryStore) -> T): T = TestDb.fresh(folder.root).use { database ->
        database.writeBlocking { db -> block(db, LibraryStore(File(folder.root, "library").apply { mkdirs() })) }
    }

    private fun song(db: Db, lib: LibraryStore, artist: String = "Soda Stereo", title: String = "De Música Ligera"): SongRow =
        lib.add(db, artist, title, now = "2026-10-01T00:00:00Z")

    private fun client(answers: Map<String, Pair<Int, String>> = emptyMap(), budget: Long = 6,
                       site: FakeTransport = FakeTransport(answers.mapValues { (_, a) -> FakeTransport.answer(a.first, a.second) }),
                       cache: String = "cache"): Client =
        PoliteClient(LaCuerdaSheets.PROVIDER, ProviderPolicy(budget = budget, delay = 0.0 to 0.0), File(folder.root, cache),
                     PhoneConfig.DEFAULTS.userAgent, site, sleep = {}, draws = { low, _ -> low }, monotonic = { 0.0 },
                     wallClock = { now })

    private fun ctx(db: Db, lib: LibraryStore, song: SongRow, asking: Asking, overrides: Overrides = Overrides()) =
        StageContext(db, song, overrides, PhoneConfig.DEFAULTS, lib, asking, now)

    /** A version of the song kept as its sheet: [provider]'s [tabId], its `sheet.txt`. */
    private fun kept(db: Db, lib: LibraryStore, song: SongRow, provider: String, tabId: String, coverage: Double? = 0.5) {
        val vid = Versions.upsert(db, provider, tabId, song.id, "sheet", if (provider == "ug") "chords" else "acordes",
                                  0.0, 0, 1, null, "https://example.invalid/$tabId", JsonObject(emptyMap()), stamp)
        Versions.setCoverage(db, vid, coverage)
        Kept.keepFile(db, lib, song, vid, "sheet.txt", "Am F C G\n".toByteArray(), rank = 1, now = stamp)
    }

    @Test fun aSongLaCuerdaMayHaveLooksSpanishAndHasASlug() = world { db, lib ->
        assertTrue(LaCuerdaSheets.mayAsk(song(db, lib)))
        assertFalse(LaCuerdaSheets.mayAsk(song(db, lib, "Oasis", "Wonderwall")))
    }

    @Test fun aSongAskedAboutWithinThirtyDaysIsLeftAlone() = world { db, lib ->
        val s = song(db, lib)
        assertFalse(LaCuerdaSheets.askedLately(s, now))
        Versions.updateSong(db, s.id, mapOf("lacuerda_checked_at" to "2026-10-05T12:00:00Z"), stamp)
        assertTrue(LaCuerdaSheets.askedLately(Songs.byId(db, s.id)!!, now))
        assertFalse(LaCuerdaSheets.askedLately(Songs.byId(db, s.id)!!, now.plusSeconds(86_400L * 3)))
    }

    @Test fun aSongNotForLaCuerdaIsSkippedWithNothingAsked() = world { db, lib ->
        val client = client()
        val end = LaCuerdaStage.run(ctx(db, lib, song(db, lib, "Oasis", "Wonderwall"), FakeAsking(mapOf("lacuerda" to client))))
        assertEquals(StageEnd("skipped", "not for LaCuerda: not Spanish, a full sheet already, or asked this month"), end)
        assertEquals(0, client.requestsMade)
    }

    @Test fun aBlockAnErrorAndASpentBudgetAreSaidAsGetPySaysThem() = world { db, lib ->
        val s = song(db, lib)
        val blocked = LaCuerdaStage.run(ctx(db, lib, s, FakeAsking(mapOf("lacuerda" to client(mapOf("GET $soda" to (403 to "no")))))))
        assertEquals(StageEnd("skipped", "LaCuerda blocked caracole (lacuerda: 403: $soda: HTTP 403): no more requests to it " +
                                  "until later. Nothing was marked not found."), blocked)
        val failed = LaCuerdaStage.run(ctx(db, lib, s, FakeAsking(mapOf("lacuerda" to client(mapOf("GET $soda" to (500 to "x")))))))
        assertEquals(StageEnd("failed", "LaCuerda failed (lacuerda: 500: $soda: HTTP 500); tried again tonight"), failed)
        val spent = LaCuerdaStage.run(ctx(db, lib, s, FakeAsking(mapOf("lacuerda" to client(budget = 0)))))
        assertEquals(StageEnd("skipped", "this fetch's 6 asks of LaCuerda are spent; tonight's run does the rest"), spent)
        assertEquals(null, Songs.byId(db, s.id)!!.lacuerdaCheckedAt)  // an error is never a miss
    }

    @Test fun whatTheEnvelopeSaysOfAnAskingThatSentNothing() = world { db, lib ->
        val s = song(db, lib)
        fun said(asked: Asked<Nothing>): StageEnd = LaCuerdaPickStage.run(ctx(db, lib, s, object : Asking {
            override fun <T> ask(provider: String, policy: ProviderPolicy?, work: (Client) -> T): Asked<T> = asked
            override val requests: Map<String, Int> = emptyMap()
        }))
        assertEquals(StageEnd("skipped", "Waiting out LaCuerda until 2026-11-04 14:00 UTC"),
                     said(Asked.Cooling(Instant.parse("2026-11-04T14:00:00Z"))))
        assertEquals(StageEnd("skipped", "no more asks of LaCuerda this hour (60 spent); tonight's run does the rest"),
                     said(Asked.Spent(hour = true, keptForSheets = false)))
        assertEquals(StageEnd("skipped", "this hour's lookups have spent half of their 60 requests to LaCuerda, and the " +
                                  "other half is kept for sheets; the nightly run does the rest"),
                     said(Asked.Spent(hour = false, keptForSheets = true)))
        assertEquals(StageEnd("skipped", "LaCuerda failed earlier in this lookup; the nightly run tries again"),
                     said(Asked.Off("LaCuerda failed earlier in this lookup; the nightly run tries again")))
    }

    @Test fun aPickKeptAlreadyIsTheSheetAndOneWaitingSaysWhy() = world { db, lib ->
        val s = song(db, lib)
        val pick = Overrides(lacuerda = mapOf(s.key to LaCuerdaPick("soda_stereo", "de_musica_ligera")))
        val asking = FakeAsking(mapOf("lacuerda" to client()))
        kept(db, lib, s, "lacuerda", "soda_stereo/de_musica_ligera-3")
        assertEquals(StageEnd("done", "your LaCuerda pick is the sheet already"),
                     LaCuerdaPickStage.run(ctx(db, lib, s, asking, pick)))

        val pinned = song(db, lib, "Soda Stereo", "Persiana Americana")
        kept(db, lib, pinned, "ug", "85053")
        val both = Overrides(lacuerda = mapOf(pinned.key to LaCuerdaPick("soda_stereo", "persiana_americana")),
                             pin = mapOf(pinned.key to listOf(85053L)))
        assertEquals(StageEnd("skipped", "your pinned UG tab is kept over your LaCuerda pick"),
                     LaCuerdaPickStage.run(ctx(db, lib, pinned, asking, both)))

        val asked = song(db, lib, "Soda Stereo", "Cuando Pase el Temblor")
        Versions.updateSong(db, asked.id, mapOf("lacuerda_checked_at" to "2026-10-30T00:00:00Z"), stamp)
        val waits = Overrides(lacuerda = mapOf(asked.key to LaCuerdaPick("soda_stereo", "cuando_pase_el_temblor", 2)))
        assertEquals(StageEnd("skipped", "your LaCuerda pick waits: asked this month already"),
                     LaCuerdaStage.run(ctx(db, lib, Songs.byId(db, asked.id)!!, asking, waits)))
        assertEquals(0, (asking.requests["lacuerda"] ?: 0))
    }

    @Test fun aMissIsRecordedAndAskedAgainAfterThirtyDays() = world { db, lib ->
        val s = song(db, lib, "Nadie Conocido", "Canción de Nadie")
        val c = client(mapOf("GET https://acordes.lacuerda.net/nadie_conocido/" to (404 to "x")))
        val stats = LaCuerdaSheets.lacuerdaSheets(db, c, lib, PhoneConfig.DEFAULTS.rank, now, Overrides(), setOf(s.id))
        assertEquals(listOf(1, 1, 0), listOf(stats.tried, stats.missing, stats.kept))
        assertEquals(stamp, Songs.byId(db, s.id)!!.lacuerdaCheckedAt)
        assertEquals(1, c.requestsMade)
        val again = LaCuerdaSheets.lacuerdaSheets(db, c, lib, PhoneConfig.DEFAULTS.rank, now.plusSeconds(86_400), Overrides(),
                                                  setOf(s.id))
        assertEquals(0, again.tried)
        assertEquals(1, c.requestsMade)
        val other = LaCuerdaSheets.lacuerdaSheets(db, c, lib, PhoneConfig.DEFAULTS.rank, now, Overrides(), setOf(s.id + 1))
        assertEquals(0, other.tried)  // the lookup's song alone
    }

    @Test fun anArtistPageNoSlugAnswersIsNone() = world { db, _ ->
        val c = client(mapOf("GET https://acordes.lacuerda.net/nadie/" to (404 to "x"),
                             "GET https://acordes.lacuerda.net/los_nadie/" to (200 to "aqui llega:../tabs/l/los_nadie/index.html")))
        assertEquals(null, LaCuerdaSheets.readArtistPage(db, c, "Los Nadie", now))
        assertEquals(2, c.requestsMade)
    }

    /** readArtistPage's `first` (read_artist_page has none; LaCuerdaRunner passes none) is asked before every other
     * slug, in place of the name itself when it is written as a slug, the name's slugs after it as ever. */
    @Test fun aFirstSlugGivenIsAskedBeforeTheNamesOwn() = world { db, _ ->
        val oficial = "GET https://acordes.lacuerda.net/estopa_oficial/"
        val estopa = "GET https://acordes.lacuerda.net/estopa/"
        val site = FakeTransport(mapOf(oficial to FakeTransport.answer(404, "x"), estopa to FakeTransport.answer(404, "x")))
        assertEquals(null, LaCuerdaSheets.readArtistPage(db, client(site = site), "estopa", now, first = "estopa_oficial"))
        assertEquals(listOf(oficial, estopa), site.said)

        val alone = FakeTransport(mapOf(estopa to FakeTransport.answer(404, "x")))
        assertEquals(null, LaCuerdaSheets.readArtistPage(db, client(site = alone, cache = "another cache"), "estopa", now))
        assertEquals(listOf(estopa), alone.said)  // the name written as a slug is its one slug
    }
}
