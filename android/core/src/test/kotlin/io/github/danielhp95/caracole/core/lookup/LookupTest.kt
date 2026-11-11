package io.github.danielhp95.caracole.core.lookup

import io.github.danielhp95.caracole.core.config.PhoneConfig
import io.github.danielhp95.caracole.core.db.Database
import io.github.danielhp95.caracole.core.db.Db
import io.github.danielhp95.caracole.core.health.Alerts
import io.github.danielhp95.caracole.core.health.Health
import io.github.danielhp95.caracole.core.http.Draws
import io.github.danielhp95.caracole.core.index.Stamps
import io.github.danielhp95.caracole.core.keys.Normalize
import io.github.danielhp95.caracole.core.library.Kept
import io.github.danielhp95.caracole.core.library.LibraryStore
import io.github.danielhp95.caracole.core.library.Overrides
import io.github.danielhp95.caracole.core.library.SharedFolder
import io.github.danielhp95.caracole.core.library.SongRow
import io.github.danielhp95.caracole.core.library.Songs
import io.github.danielhp95.caracole.core.library.Versions
import io.github.danielhp95.caracole.core.testing.FakeTransport
import io.github.danielhp95.caracole.core.testing.Misses
import io.github.danielhp95.caracole.core.testing.TestDb
import io.github.danielhp95.caracole.core.testing.replays.LookupReplay
import kotlinx.serialization.json.JsonObject
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import java.io.File
import java.time.Instant
import java.util.concurrent.CancellationException
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith
import kotlin.test.assertFalse
import kotlin.test.assertNotNull
import kotlin.test.assertNull
import kotlin.test.assertTrue

/** get.py's frame on the phone, over fake site stages: the stages in order and what each says, the envelope's ends
 * and records, what can be read when, and the seams of milestones 5 and 6. */
class LookupTest {
    @get:Rule val tmp = TemporaryFolder()

    private val now: Instant = Instant.parse("2026-11-03T12:00:00Z")
    private var clock = 0.0
    private val pacing = Pacing(sleep = {}, draws = Draws { a, _ -> a }, wallSeconds = { now.epochSecond.toDouble() },
                                monotonic = { clock }, clock = { now })
    private val ug = "https://tabs.ultimate-guitar.com/tab/radiohead/creep-chords-4169"
    private val lrclib = "https://lrclib.net/api/get?artist_name=Radiohead&track_name=Creep"
    private val site = FakeTransport(mapOf(
        "GET $ug" to FakeTransport.answer(403, "Forbidden"),
        "GET $lrclib" to FakeTransport.answer(200, "{}", listOf("content-type" to "application/json")),
    ))
    private val quiet = SiteStage { StageEnd("skipped", "nothing to do") }
    private val heard = ArrayList<List<Any>>()
    private val progress = object : Progress {
        override fun stage(name: String, state: String, detail: String) {
            heard += listOf("stage", name, state, detail)
        }

        override fun song(id: Long, display: String) {
            heard += listOf("song", id, display)
        }

        override fun readable(files: Map<String, String>, seconds: Double) {
            heard += listOf("readable", files, seconds)
        }
    }

    private class Heard : Alerts {
        val blocks = ArrayList<String>()
        override fun blocked(provider: String, until: Instant?, message: String) {
            blocks += provider
        }

        override fun failed(title: String, line: String) {}
    }

    private lateinit var database: Database
    private lateinit var store: LibraryStore
    private lateinit var cache: File

    private fun phone(block: (Db) -> Unit): Unit = TestDb.fresh(tmp.newFolder()).use { db ->
        database = db
        store = LibraryStore(tmp.newFolder("library"))
        cache = tmp.newFolder("cache")
        db.writeBlocking(block)
    }

    private fun stages(match: SiteStage = quiet, ugSheet: SiteStage = quiet, ug: SiteStage = quiet,
                       lacuerdaPick: SiteStage = quiet, lacuerda: SiteStage = quiet, lrclib: SiteStage = quiet,
                       megalobiz: SiteStage = SiteStage { LookupWords.NOTHING_TO_ASK },
                       azlyrics: SiteStage = SiteStage { LookupWords.NOTHING_TO_ASK }, gtptabs: SiteStage = quiet,
                       harptabs: SiteStage = quiet, gametabs: SiteStage = quiet) =
        SiteStages(match, ugSheet, ug, lacuerdaPick, lacuerda, lrclib, megalobiz, azlyrics, gtptabs, harptabs, gametabs)

    private fun lookup(stages: SiteStages, request: LookupRequest = LookupRequest("Radiohead", "Creep"),
                       overrides: Overrides = Overrides(), alerts: Alerts = Alerts.NONE,
                       pages: SongPages = SongPages.NONE, songbooks: SongbookPages = SongbookPages.NONE) =
        Lookup(PhoneConfig.DEFAULTS, database, store, Clients(PhoneConfig.DEFAULTS, cache, { site }, pacing), pages,
               songbooks, alerts, request, progress, pacing, stages, readOverrides = { overrides })

    private fun ends(): List<Pair<String, String>> =
        heard.filter { it[0] == "stage" && it[2] != "running" }.map { it[1] as String to it[2] as String }

    /** The song's sheet.txt kept from a version of [provider]'s. */
    private fun keepSheet(db: Db, song: SongRow, provider: String = "ug", text: String = "[C]Creep\n") {
        val id = Versions.upsert(db, provider, "4169", song.id, "sheet", "chords", 4.5, 10, 1, null,
                                 "https://example.invalid/4169", JsonObject(emptyMap()), Stamps.of(now))
        Kept.keepFile(db, store, song, id, "sheet.txt", text.toByteArray(), 0, Stamps.of(now))
    }

    @Test fun everyRecordOfTheCorpusIsAnsweredAsGetPyAnswersIt() {
        val misses = Misses("lookup")
        LookupReplay.replay(misses)
        misses.assertNone()
    }

    @Test fun theStagesRunInGetPysOrderAndANewSongIsAdded() = phone { db ->
        val result = lookup(stages()).run(db)
        assertEquals(LookupWords.STAGES.map { it.first }, heard.filter { it[0] == "stage" && it[2] == "running" }
            .map { it[1] }.distinct())
        assertEquals(LookupWords.STAGES.map { it.first }, result.states.keys.toList())
        val song = Songs.byKey(db, Normalize.identityKey("Radiohead", "Creep"))!!
        assertEquals(listOf("song", song.id, "Radiohead - Creep"), heard.first { it[0] == "song" })
        assertEquals("done" to LookupWords.ADDED, result.states["song"] to result.details["song"])
        assertEquals(song.id, result.songId)
        assertEquals("skipped" to LookupWords.NO_SHEET_YET, result.states["pdf"] to result.details["pdf"])
        assertEquals("done" to LookupWords.LIBRARY_PAGE, result.states["pages"] to result.details["pages"])
        assertEquals("skipped" to "not on the phone yet", result.states["songbooks"] to result.details["songbooks"])
        assertTrue(result.ok)
        assertNull(result.refused)
        assertEquals("[${song.id}]", db.kvGet("lookup:songs"))
        heard.clear()
        assertEquals("in the book", lookup(stages()).run(db).details["song"])
    }

    @Test fun aSongIgnoredIsRefusedTheSongStageFailedAndTheRestSkipped() = phone { db ->
        val key = Normalize.identityKey("Radiohead", "Creep")
        val result = lookup(stages(match = SiteStage { error("asked") }), overrides = Overrides(ignore = setOf(key)))
            .run(db)
        val why = "Radiohead - Creep is ignored (overrides.toml [ignore]). Take it out to fetch it"
        assertEquals(why, result.refused)
        assertEquals(listOf("song" to "failed") + LookupWords.STAGES.drop(1).map { it.first to "skipped" }, ends())
        assertEquals(why, result.details["song"])
        assertEquals(LookupWords.STAGES.drop(1).map { "" }, LookupWords.STAGES.drop(1).map { result.details[it.first] })
        assertNull(Songs.byKey(db, key))  // nothing added
        assertNull(result.songId)
        assertEquals(emptyMap(), result.requests)
    }

    @Test fun aSiteThatBlockedIsSkippedAfterItAndAlertsOnce() = phone { db ->
        val alerts = Heard()
        val asks = SiteStage { ctx -> LookupWords.end(ctx.config, "ug", ctx.asking.ask("ug") { it.get(ug); StageEnd("done", "x") }) }
        val result = lookup(stages(ugSheet = asks, ug = asks), alerts = alerts).run(db)
        val block = result.details.getValue("sheet")
        assertTrue(block.startsWith("Ultimate Guitar blocked caracole (ug: 403: $ug"), block)
        assertEquals("skipped" to LookupWords.blockedEarlier("ug"), result.states["ug"] to result.details["ug"])
        assertEquals(listOf("ug"), alerts.blocks)
        assertEquals(mapOf("ug" to 1), result.requests)
        assertNull(Health.state(db, "ug").lastOk)  // a site that blocked had no good run
        assertNotNull(Health.state(db, "ug").cooldownUntil)
    }

    @Test fun aSiteThatAnsweredHadAGoodRunAndTheLyricsArePutTogether() = phone { db ->
        val lyrics = SiteStage { ctx ->
            LookupWords.end(ctx.config, "lrclib", ctx.asking.ask("lrclib") { it.get(lrclib); StageEnd("done", "LRCLIB has none") })
        }
        val az = SiteStage { ctx ->
            Versions.updateSong(ctx.db, ctx.song.id, mapOf("lyrics_status" to "found"))
            StageEnd("done", "lyrics from AZLyrics")
        }
        val result = lookup(stages(lrclib = lyrics, azlyrics = az)).run(db)
        assertEquals("done" to "LRCLIB has none; lyrics from AZLyrics", result.states["lyrics"] to result.details["lyrics"])
        assertEquals(now, Health.state(db, "lrclib").lastOk)
        assertEquals(mapOf("lrclib" to 1), result.requests)
    }

    @Test fun aStagesExceptionIsABugTheOtherStagesGoOn() = phone { db ->
        val result = lookup(stages(lrclib = SiteStage { throw IllegalStateException("no such column") })).run(db)
        assertEquals("failed" to "a bug in caracole: IllegalStateException: no such column",
                     result.states["lyrics"] to result.details["lyrics"])
        assertEquals("lyrics: IllegalStateException: no such column", result.bug)
        assertFalse(result.ok)
        assertEquals("done", result.states["pages"])
    }

    @Test fun aFileWhereAnotherSongKeepsOneFailsTheStageInGetPysWords() = phone { db ->
        val other = store.add(db, "Radiohead", "Creep (Acoustic)", now = Stamps.of(now))
        val result = lookup(stages(gtptabs = SiteStage { ctx -> throw SharedFolder(ctx.song, other, "guitar-1.gp5") }))
            .run(db)
        assertEquals("failed", result.states["gtptabs"])
        assertTrue(result.details.getValue("gtptabs").endsWith("ask for it again under a shorter title."))
        assertTrue(result.ok)
    }

    @Test fun theSheetIsReadableOnceKeptAndTheRunningStageSaysWhichSiteItAsks() = phone { db ->
        val sheet = SiteStage { ctx ->
            ctx.asking.ask("lrclib") { }  // a site asked: the sheet stage says which, from LRCLIB being none of them
            ctx.asking.ask("ug") { }
            keepSheet(ctx.db, ctx.song)
            clock = 2.5
            StageEnd("done", "tab 4169 from Ultimate Guitar")
        }
        val result = lookup(stages(ugSheet = sheet)).run(db)
        val running = heard.filter { it[0] == "stage" && it[1] == "sheet" && it[2] == "running" }.map { it[3] }
        assertEquals(listOf("", "from UG"), running)
        val readable = heard.filter { it[0] == "readable" }
        assertEquals(listOf(listOf("readable", mapOf("sheet" to "Radiohead/Creep/sheet.txt"), 2.5)), readable)
        assertEquals(2.5, result.secondsToSheet)
        assertEquals(mapOf("sheet" to "Radiohead/Creep/sheet.txt"), result.files)
        assertEquals("skipped" to LookupWords.NO_PDFS, result.states["pdf"] to result.details["pdf"])
    }

    @Test fun thePagesOfASongAreTheSeamsOnceTheyAreNotNone() = phone { db ->
        val rendered = ArrayList<List<Long>>()
        val pages = SongPages { _, ids, between ->
            rendered.add(ids.toList())
            assertNull(between)
            RenderStats(written = 1)
        }
        val result = lookup(stages(ugSheet = SiteStage { ctx -> keepSheet(ctx.db, ctx.song); StageEnd("done", "x") }),
                            pages = pages).run(db)
        assertEquals("done" to LookupWords.PAGES_MADE, result.states["pdf"] to result.details["pdf"])
        assertEquals(listOf(listOf(result.songId!!), listOf(result.songId!!)), rendered)  // the pdf stage, then pages
        heard.clear()
        val failing = SongPages { _, ids, _ -> RenderStats(failed = mapOf(ids.first() to "the page can't be made")) }
        assertEquals("the page can't be made", lookup(stages(), pages = failing).run(db).details["pdf"])
    }

    @Test fun eachWriteCommitsAsItHappensSoAStoppedLookupLeavesItsRecords() {
        TestDb.fresh(tmp.newFolder()).use { db ->
            database = db
            store = LibraryStore(tmp.newFolder("library"))
            cache = tmp.newFolder("cache")
            val asks = SiteStage { ctx -> LookupWords.end(ctx.config, "ug", ctx.asking.ask("ug") { it.get(ug); StageEnd("done", "x") }) }
            val stops = SiteStage { throw CancellationException("the queue stopped") }
            assertFailsWith<CancellationException> {
                db.writeBlocking { lookup(stages(ugSheet = asks, lrclib = stops)).run(it) }
            }
            db.read { read ->
                assertEquals("blocked", read.one("SELECT decision FROM events WHERE provider = 'ug'") { it.text(0) })
                assertNotNull(Health.state(read, "ug").cooldownUntil)
                assertEquals("1793707200.000", read.kvGet(Pace.LAST_SENT + "ug"))
                assertNotNull(Songs.byKey(read, Normalize.identityKey("Radiohead", "Creep")))
            }
        }
    }

    @Test fun aLookupInsideAnotherWriteIsRefused() {
        TestDb.fresh(tmp.newFolder()).use { db ->
            database = db
            store = LibraryStore(tmp.newFolder("library"))
            cache = tmp.newFolder("cache")
            val nested = SiteStage { database.writeBlocking { StageEnd("done", "written beside") } }
            val result = db.writeBlocking { lookup(stages(match = nested)).run(it) }
            assertTrue(result.details.getValue("match").startsWith("a bug in caracole: IllegalStateException: a write " +
                                                                   "inside a write's block"))
        }
    }

    @Test fun laCuerdaIsAskedOnceForTheSheetAndTheLacuerdaStageSaysWhatItCameTo() = phone { db ->
        var asked = 0
        val lc = SiteStage { asked++; StageEnd("done", "not on LaCuerda") }
        val result = lookup(stages(lacuerda = lc)).run(db)
        assertEquals(1, asked)
        assertEquals("skipped" to "nothing to do", result.states["sheet"] to result.details["sheet"])
        assertEquals("skipped" to "asked already, for the sheet: not on LaCuerda",
                     result.states["lacuerda"] to result.details["lacuerda"])
    }

    @Test fun whatFollowsTheSheetIsAskedWithinItsShare() = phone { db ->
        var how: Asking? = null
        val ugStage = SiteStage { ctx -> how = ctx.asking; StageEnd("done", "sheet 4169") }
        lookup(stages(ug = ugStage)).run(db)
        assertTrue(how is InteractiveAsk.AfterTheSheet)
    }

    @Test fun aPickIsRecordedInTheOverridesAndSaidInTheSongStage() = phone { db ->
        val result = lookup(stages(), LookupRequest("Radiohead", "Creep", ug = "radiohead/creep")).run(db)
        assertEquals("${LookupWords.ADDED}; recorded in overrides.toml: [match] radiohead/creep", result.details["song"])
    }

    @Test fun aTabPickedKeepsThePinsOfTheOtherKindGroupAsWrittenAndReplacesTheRest() = phone { db ->
        // get.py's `_other_pins`: chords and ukulele chords are one group (either is the sheet), text tabs another; a
        // pin of the pick's group, or of a tab the index doesn't know, is replaced; the others stay as written.
        for ((id, type) in listOf(4169L to "chords", 5000L to "tabs", 6000L to "chords", 6500L to "ukulele",
                                  7000L to "tabs")) {
            db.execute("INSERT INTO ug_index (tab_id, artist_key, song_key, type, sitemap, first_seen, path) " +
                           "VALUES (?, 'radiohead', 'creep', ?, 'test', '2026-11-03T12:00:00Z', ?)",
                       id, type, "radiohead/creep-$type-$id")
        }
        val key = Normalize.identityKey("Radiohead", "Creep")
        val pasted = "https://tabs.ultimate-guitar.com/tab/radiohead/creep-tabs-5000"
        val before = Overrides(pin = mapOf(key to listOf(5000L, 6000L, 6500L, 9999L, 7000L)),
                               pinUrls = mapOf(key to listOf(pasted)))
        val result = lookup(stages(), LookupRequest("Radiohead", "Creep", tab = ug), overrides = before).run(db)
        assertEquals("${LookupWords.ADDED}; recorded in overrides.toml: [pin] tab 4169", result.details["song"])
        val after = Overrides.read(db)
        assertEquals(listOf(4169L, 5000L, 7000L), after.pin[key])  // the tabs beside the chords picked
        assertEquals(listOf(ug, pasted, "https://tabs.ultimate-guitar.com/tab/7000"), after.pinUrls[key])
        // A pick the index doesn't know: nothing of the song's pins stays beside it.
        heard.clear()
        val unknown = "https://tabs.ultimate-guitar.com/tab/radiohead/creep-chords-8888"
        lookup(stages(), LookupRequest("Radiohead", "Creep", tab = unknown), overrides = before).run(db)
        assertEquals(listOf(8888L), Overrides.read(db).pin[key])
    }

    @Test fun aStageWithNothingToAskOutsideTheLyricsIsDoneWithNoWords() = phone { db ->
        val nothing = SiteStage { LookupWords.NOTHING_TO_ASK }
        val result = lookup(stages(lacuerda = nothing, gtptabs = nothing, harptabs = nothing)).run(db)
        assertEquals("done" to "", result.states["gtptabs"] to result.details["gtptabs"])
        assertEquals("done" to "", result.states["harptabs"] to result.details["harptabs"])
        assertEquals("skipped" to "asked already, for the sheet", result.states["lacuerda"] to result.details["lacuerda"])
        assertTrue(ends().none { it.second == LookupWords.NOTHING_TO_ASK.state }, "${ends()}")
    }

    @Test fun aTabOfAKindCaracoleDoesntUseIsRefusedBeforeAnythingIsWritten() = phone { db ->
        val tab = "https://tabs.ultimate-guitar.com/tab/radiohead/creep-guitar-pro-224003"
        val result = lookup(stages(), LookupRequest("Radiohead", "Creep", tab = tab)).run(db)
        assertEquals("tab 224003 isn't chords, a tab or ukulele chords", result.refused)
        assertNull(Songs.byKey(db, Normalize.identityKey("Radiohead", "Creep")))
    }
}
