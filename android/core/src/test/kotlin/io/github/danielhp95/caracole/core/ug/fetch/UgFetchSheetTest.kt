package io.github.danielhp95.caracole.core.ug.fetch

import io.github.danielhp95.caracole.core.config.PhoneConfig
import io.github.danielhp95.caracole.core.config.ProviderPolicy
import io.github.danielhp95.caracole.core.db.Db
import io.github.danielhp95.caracole.core.health.ProviderState
import io.github.danielhp95.caracole.core.http.Client
import io.github.danielhp95.caracole.core.http.ProviderBlocked
import io.github.danielhp95.caracole.core.http.ProviderError
import io.github.danielhp95.caracole.core.library.LibraryStore
import io.github.danielhp95.caracole.core.library.Overrides
import io.github.danielhp95.caracole.core.library.SongRow
import io.github.danielhp95.caracole.core.library.Songs
import io.github.danielhp95.caracole.core.library.Versions
import io.github.danielhp95.caracole.core.lookup.Asked
import io.github.danielhp95.caracole.core.lookup.Asking
import io.github.danielhp95.caracole.core.lookup.Clients
import io.github.danielhp95.caracole.core.lookup.InteractiveAsk
import io.github.danielhp95.caracole.core.lookup.LookupWords
import io.github.danielhp95.caracole.core.lookup.Pace
import io.github.danielhp95.caracole.core.lookup.Pacing
import io.github.danielhp95.caracole.core.lookup.SiteStage
import io.github.danielhp95.caracole.core.lookup.StageContext
import io.github.danielhp95.caracole.core.lookup.StageEnd
import io.github.danielhp95.caracole.core.lookup.sites.UgSheetStage
import io.github.danielhp95.caracole.core.lookup.sites.UgStage
import io.github.danielhp95.caracole.core.lookup.sites.UgStages
import io.github.danielhp95.caracole.core.match.Match
import io.github.danielhp95.caracole.core.testing.FakeAsking
import io.github.danielhp95.caracole.core.testing.Misses
import io.github.danielhp95.caracole.core.testing.RefusingTransport
import io.github.danielhp95.caracole.core.testing.ScenarioWorld
import io.github.danielhp95.caracole.core.testing.Scenarios
import io.github.danielhp95.caracole.core.testing.TestDb
import io.github.danielhp95.caracole.core.testing.replays.UgFetchReplay
import io.github.danielhp95.caracole.core.ug.FetchContext
import io.github.danielhp95.caracole.core.ug.SongFetchOutcome
import io.github.danielhp95.caracole.core.ug.UgFetch
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import kotlinx.serialization.json.long
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import java.time.Instant

/**
 * UgFetch.processSong replays vectors/lookup/ug_sheet.jsonl (a lookup's two passes, pins and the pinned URL, rating
 * pages, the versions kept beside the sheet and beside a pin, yours, unreadable pages and their doubling retry,
 * robots.txt, a 404, a block, a spent budget, another site's sheet, a variant, links of another shape, a folder two
 * songs share, a pin robots.txt closes); the lookup's UG stages ask through a StageContext's asking and say what it
 * came to as get.py says it (ug_sheet_stages.jsonl, and LookupWords for the envelope's ends); and a song whose
 * versions come from its artist's UG page waits for ug-fetch-artist's route, never checked.
 */
class UgFetchSheetTest {
    @get:Rule val tmp = TemporaryFolder()

    @Test fun everyRecordOfProcessSongReplays() {
        val misses = Misses(UgFetchReplay.SHEET)
        UgFetchReplay.sheet(misses)
        misses.assertNone()
    }

    private fun record(case: String): JsonObject =
        UgFetchReplay.records(UgFetchReplay.SHEET).first { it.getValue("case").jsonPrimitive.content.startsWith(case) }

    /** A record whose pass raised, as one that returned nothing: what the stage, which says it, leaves. */
    private fun said(record: JsonObject): JsonObject = JsonObject(record.filterKeys { it != "raises" && it != "after" } +
        ("out" to JsonObject(record.getValue("after").jsonObject + ("result" to JsonNull))))

    /** Each of [stages] run in the record's world through [asking] (FakeAsking, else the lookup's own envelope), its
     * words; the record's passes are theirs. */
    private fun stages(record: JsonObject, vararg stages: SiteStage,
                       asking: (ScenarioWorld) -> Asking = { FakeAsking(it.clients) }): List<StageEnd> {
        val song = record.getValue("kw").jsonObject.getValue("song").jsonPrimitive.long
        val ends = ArrayList<StageEnd>()
        Scenarios.replay(record) { world ->
            val ask = asking(world)
            for (stage in stages) {
                val ctx = StageContext(world.db, Songs.byId(world.db, song)!!, Overrides.read(world.db),
                                       PhoneConfig.DEFAULTS, LibraryStore(world.library), ask, world.now)
                ends += stage.run(ctx)
            }
            record.getValue("out").jsonObject["result"]
        }
        return ends
    }

    /** InteractiveAsk, the lookup's envelope, asking through the world's own clients: its words for a spent budget are
     * get.py's for the client's budget. No song is owed (no `owedSong`), so it writes nothing the record didn't. */
    private fun envelope(world: ScenarioWorld): Asking {
        val pacing = Pacing(sleep = {}, draws = { low, _ -> low }, wallSeconds = { world.now.epochSecond.toDouble() },
                            monotonic = { 0.0 }, clock = { world.now })
        return InteractiveAsk(Clients(PhoneConfig.DEFAULTS, world.cacheDir, { RefusingTransport }, pacing), world.db,
                              Pace.lookupRunId(world.now), world.now, make = { p, _ -> world.clients.getValue(p) })
    }

    @Test fun theLookupsTwoStagesAreItsTwoPassesWordedAsGetPyWordsThem() {
        val ends = stages(record("a lookup's sheet pass, then the rest"), UgSheetStage, UgStage)
        assertEquals(listOf(StageEnd("done", "tab 102 from Ultimate Guitar"),
                            StageEnd("done", "sheet 103 · tab 202 · kept beside it: tab 104, tab 102")), ends)
    }

    @Test fun aSheetPassWithNoSheetSaysSoAndTheUgStageItsSheetAlone() {
        val ends = stages(record("another site's complete sheet stays"), UgStage)
        assertEquals(listOf(StageEnd("done", "no UG sheet · kept beside it: tab 102")), ends)
    }

    @Test fun aBlockAndASpentBudgetEndTheStageWithTheEnvelopesWords() {
        val blocked = said(record("a block raises"))
        assertEquals(listOf(StageEnd("skipped", "Ultimate Guitar blocked caracole (ug: 403: https://tabs.ultimate-guitar.com/" +
            "tab/soda-stereo/persiana-americana-chords-101: HTTP 403): no more requests to it until later. Nothing was " +
            "marked not found.")), stages(blocked, UgStage))
        // The record's client had 2 requests left, fewer than a lookup's 6: the hour's were spent, as get.py says.
        val spent = said(record("a spent budget raises"))
        assertEquals(listOf(StageEnd("skipped", "this hour's 60 lookup requests to Ultimate Guitar are spent; the " +
            "nightly run does the rest")), stages(spent, UgStage, asking = ::envelope))
    }

    @Test fun aSheetThatWouldGoWhereAnotherSongKeepsOneFailsTheStageInReportsWords() {
        val shared = record("a sheet that would go where another song keeps its own")
        val message = shared.getValue("raises").jsonObject.getValue("message").jsonPrimitive.content
        val (end) = stages(said(shared), UgStage)
        assertEquals("failed", end.state)
        assertTrue(end.detail, end.detail.startsWith("$message. Nothing is written over it, and the song waits"))
    }

    @Test fun everyWordOfTheTwoStagesAndOfUgReadyIsGetPys() {
        val misses = Misses(UgFetchReplay.STAGES)
        UgFetchReplay.stages(misses)
        misses.assertNone()
    }

    /** [check] run in the world of the record of the lookup's two passes, its song [prepare]d first; nothing compared
     * with the record, which is of another pass. */
    private fun inTheTwoPassesWorld(prepare: (Db, Long) -> Unit, check: (ScenarioWorld, SongRow, FetchContext) -> Unit) {
        val record = record("a lookup's sheet pass, then the rest")
        val kw = record.getValue("kw").jsonObject
        val id = kw.getValue("song").jsonPrimitive.long
        val rest = kw.getValue("passes").jsonArray[1].jsonObject
        Scenarios.replay(record, Misses("not compared")) { world ->
            prepare(world.db, id)
            check(world, Songs.byId(world.db, id)!!, UgFetchReplay.context(world, rest))
            null
        }
    }

    /** What the phone answers for a song whose versions come from its artist's UG lists (until ug-fetch-artist reads
     * them): Python's answer for a list the page cap cut short. No request, the song marked dirty, neither checked
     * nor clean, nothing kept; so a sync never tells the computer UG was asked. */
    private fun waitsForItsArtistsPage(world: ScenarioWorld, song: SongRow, ctx: FetchContext) {
        val out = UgFetch.processSong(ctx, song, guitar = true)
        assertEquals(SongFetchOutcome(song.id, null, null, 0), out)
        assertEquals(emptyList<String>(), world.transport.said)
        val after = Songs.byId(world.db, song.id)!!
        assertTrue(after.ugDirty)
        assertEquals(null, after.ugCheckedAt)
        assertEquals(null, world.db.kvGet("ug:artist_page_checked:${song.id}"))
        assertFalse(UgFetch.checkedSince(world.db, after, NOW))
    }

    @Test fun aSongFoundOnItsArtistsPageWaitsForItsListsNeverCheckedOrClean() = inTheTwoPassesWorld(
        { db, id -> Versions.updateSong(db, id, mapOf("match_step" to Match.ARTIST_PAGE, "ug_dirty" to false)) },
        ::waitsForItsArtistsPage)

    @Test fun aSongWhoseIndexTabsHoldNoChordsWaitsForItsArtistsChordsList() = inTheTwoPassesWorld(
        { db, id ->
            db.execute("DELETE FROM ug_index WHERE type = 'chords'")
            Versions.updateSong(db, id, mapOf("ug_dirty" to false))
        },
        ::waitsForItsArtistsPage)

    /** [check] given a stage's context of [song] in a library of no song, with no client. */
    private fun withContext(song: SongRow, check: (StageContext) -> Unit) {
        TestDb.fresh(tmp.newFolder()).use { database ->
            database.writeBlocking { db ->
                check(StageContext(db, song, Overrides(), PhoneConfig.DEFAULTS, LibraryStore(tmp.newFolder()),
                                   FakeAsking(emptyMap()), NOW))
            }
        }
    }

    @Test fun aSongUltimateGuitarCantBeAskedAboutIsSkippedWithGetPysWords() {
        withContext(song(decision = "not_found")) { assertEquals(LookupWords.NOT_IN_INDEX, UgStages.notReady(it)) }
        withContext(song(decision = "review")) {
            assertEquals("caracole isn't sure which Ultimate Guitar song this is: pick it on the lookup page, or run " +
                             "caracole review", UgStages.notReady(it))
            assertEquals(StageEnd("skipped", UgStages.REVIEW), UgSheetStage.run(it))
        }
        withContext(song(decision = "accept")) { assertEquals(null, UgStages.notReady(it)) }
        withContext(song(decision = "pinned")) { assertEquals(null, UgStages.notReady(it)) }
    }

    /** An Asking whose every answer is [asked]: nothing is sent. */
    private class Answering(val asked: Asked<Nothing>) : Asking {
        override fun <T> ask(provider: String, policy: ProviderPolicy?, work: (Client) -> T): Asked<T> = asked
        override val requests: Map<String, Int> get() = emptyMap()
    }

    @Test fun whatAskingCameToIsSaidInTheLookupsWords() = withContext(song(decision = "accept")) { ctx ->
        val until = Instant.parse("2026-11-04T14:30:59Z")
        for (asked in listOf(Asked.Off("Ultimate Guitar is off in caracole.toml"), Asked.Cooling(until),
                             Asked.Blocked(ProviderBlocked("ug", "https://x", 429), ProviderState("ug", cooldownUntil = until)),
                             Asked.Spent(hour = true, keptForSheets = false), Asked.Spent(hour = false, keptForSheets = true),
                             Asked.Spent(hour = false, keptForSheets = false), Asked.Failed(ProviderError("ug", "https://x", 500)))) {
            val words = LookupWords.end(PhoneConfig.DEFAULTS, "ug", asked) { error("not done") }
            for (stage in listOf(UgSheetStage, UgStage)) assertEquals(words, stage.run(ctx.copy(asking = Answering(asked))))
        }
    }

    @Test fun aSongTheIndexCantSettleWhoseArtistIsKnownIsNotLookedUpOnThePhoneYet() {
        withContext(song(decision = "not_found")) { ctx ->
            ctx.db.execute("INSERT INTO ug_index (tab_id, artist_key, song_key, type, sitemap, first_seen, path) " +
                               "VALUES (7, 'soda-stereo', 'a-song', 'chords', 'last', '2026-10-01T00:00:00Z', '')")
            assertEquals(StageEnd("skipped", "not on the phone yet"), UgSheetStage.run(ctx))
            assertEquals(StageEnd("skipped", "not on the phone yet"), UgStage.run(ctx))
        }
    }

    @Test fun aSongTheIndexCantSettleNeedsItsArtistsPage() {
        assertTrue(UgFetch.needsArtistPage(song(decision = "not_found")))
        assertTrue(UgFetch.needsArtistPage(song(decision = "review",
                                                candidates = """[{"step": "title_only"}, {"step": "catch_all"}]""")))
        assertFalse(UgFetch.needsArtistPage(song(decision = "review",
                                                 candidates = """[{"step": "title_only"}, {"step": "exact"}]""")))
        assertFalse(UgFetch.needsArtistPage(song(decision = "review", candidates = "[]")))
        assertFalse(UgFetch.needsArtistPage(song(decision = "accept")))
    }

    @Test fun aFetchSettledASongOnceItsCheckIsAtOrAfterTheTimeAskedToTheSecond() {
        TestDb.fresh(tmp.newFolder()).use { database ->
            database.writeBlocking { db ->
                val since = Instant.parse("2026-11-03T12:00:00.700Z")
                assertTrue(UgFetch.checkedSince(db, song(decision = "accept", checked = "2026-11-03T12:00:00Z"), since))
                assertFalse(UgFetch.checkedSince(db, song(decision = "accept", checked = "2026-11-03T11:59:59Z"), since))
                assertFalse(UgFetch.checkedSince(db, song(decision = "accept"), since))
                assertFalse(UgFetch.checkedSince(db, song(decision = "not_found"), since))
                db.kvSet("ug:artist_page_checked:1", "2026-11-03T12:00:01Z")
                assertTrue(UgFetch.checkedSince(db, song(decision = "not_found"), since))
                assertFalse(UgFetch.checkedSince(db, song(decision = "pinned"), since))
            }
        }
    }

    companion object {
        val NOW: Instant = Instant.parse("2026-11-03T12:00:00Z")

        fun song(decision: String?, candidates: String = "[]", checked: String? = null) = SongRow(
            id = 1, key = "soda-stereo/persiana-americana", artist = "Soda Stereo", title = "Persiana Americana",
            artists = listOf("Soda Stereo"), album = null, durationMs = null, isrc = null, sourceIds = "{}",
            addedAt = "2026-10-01T00:00:00Z", variant = null, status = "wanted", review = false, matchDecision = decision,
            matchStep = "exact", matchScore = null, matchArtistKey = "soda-stereo", matchSongKey = "persiana-americana",
            matchCandidates = candidates, matchedAt = null, ugDirty = true, ugCheckedAt = checked, lyricsStatus = "pending",
            lyricsJson = null, lyricsAt = null, lacuerdaCheckedAt = null, createdAt = "2026-10-01T00:00:00Z",
        )
    }
}
