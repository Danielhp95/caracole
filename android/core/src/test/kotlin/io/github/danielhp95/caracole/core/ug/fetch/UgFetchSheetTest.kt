package io.github.danielhp95.caracole.core.ug.fetch

import io.github.danielhp95.caracole.core.config.PhoneConfig
import io.github.danielhp95.caracole.core.health.ProviderState
import io.github.danielhp95.caracole.core.http.ProviderBlocked
import io.github.danielhp95.caracole.core.http.ProviderError
import io.github.danielhp95.caracole.core.library.LibraryStore
import io.github.danielhp95.caracole.core.library.Overrides
import io.github.danielhp95.caracole.core.library.SongRow
import io.github.danielhp95.caracole.core.library.Songs
import io.github.danielhp95.caracole.core.lookup.Asked
import io.github.danielhp95.caracole.core.lookup.SiteStage
import io.github.danielhp95.caracole.core.lookup.StageContext
import io.github.danielhp95.caracole.core.lookup.StageEnd
import io.github.danielhp95.caracole.core.lookup.sites.UgSheetStage
import io.github.danielhp95.caracole.core.lookup.sites.UgStage
import io.github.danielhp95.caracole.core.lookup.sites.UgStages
import io.github.danielhp95.caracole.core.testing.FakeAsking
import io.github.danielhp95.caracole.core.testing.Misses
import io.github.danielhp95.caracole.core.testing.Scenarios
import io.github.danielhp95.caracole.core.testing.TestDb
import io.github.danielhp95.caracole.core.testing.replays.UgFetchReplay
import io.github.danielhp95.caracole.core.ug.UgFetch
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import kotlinx.serialization.json.long
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Assume.assumeTrue
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import java.time.Instant

/**
 * UgFetch.processSong replays vectors/lookup/ug_sheet.jsonl (a lookup's two passes, pins and the pinned URL, rating
 * pages, the versions kept beside the sheet and beside a pin, yours, unreadable pages and their doubling retry,
 * robots.txt, a 404, a block, a spent budget, another site's sheet); and the lookup's UG stages ask through a
 * StageContext's asking and say what it came to as get.py says it.
 */
class UgFetchSheetTest {
    @get:Rule val tmp = TemporaryFolder()

    private fun waiting() = assumeTrue("waiting on ug-pages, rank-coverage, overrides-model and html-tree",
                                       UgFetchReplay.ready)

    @Test fun everyRecordOfProcessSongReplays() {
        waiting()
        val misses = Misses(UgFetchReplay.SHEET)
        UgFetchReplay.sheet(misses)
        misses.assertNone()
    }

    private fun record(case: String): JsonObject =
        UgFetchReplay.records(UgFetchReplay.SHEET).first { it.getValue("case").jsonPrimitive.content.startsWith(case) }

    /** A record whose pass raised, as one that returned nothing: what the stage, which says it, leaves. */
    private fun said(record: JsonObject): JsonObject = JsonObject(record.filterKeys { it != "raises" && it != "after" } +
        ("out" to JsonObject(record.getValue("after").jsonObject + ("result" to JsonNull))))

    /** Each of [stages] run in the record's world through FakeAsking, its words; the record's passes are theirs. */
    private fun stages(record: JsonObject, vararg stages: SiteStage): List<StageEnd> {
        val song = record.getValue("kw").jsonObject.getValue("song").jsonPrimitive.long
        val ends = ArrayList<StageEnd>()
        Scenarios.replay(record) { world ->
            for (stage in stages) {
                val ctx = StageContext(world.db, Songs.byId(world.db, song)!!, Overrides.read(world.db),
                                       PhoneConfig.DEFAULTS, LibraryStore(world.library), FakeAsking(world.clients),
                                       world.now)
                ends += stage.run(ctx)
            }
            record.getValue("out").jsonObject["result"]
        }
        return ends
    }

    @Test fun theLookupsTwoStagesAreItsTwoPassesWordedAsGetPyWordsThem() {
        waiting()
        val ends = stages(record("a lookup's sheet pass, then the rest"), UgSheetStage, UgStage)
        assertEquals(listOf(StageEnd("done", "tab 102 from Ultimate Guitar"),
                            StageEnd("done", "sheet 103 · tab 202 · kept beside it: tab 104, tab 102")), ends)
    }

    @Test fun aSheetPassWithNoSheetSaysSoAndTheUgStageItsSheetAlone() {
        waiting()
        val ends = stages(record("another site's complete sheet stays"), UgStage)
        assertEquals(listOf(StageEnd("done", "no UG sheet · kept beside it: tab 102")), ends)
    }

    @Test fun aBlockAndASpentBudgetEndTheStageWithTheEnvelopesWords() {
        waiting()
        val blocked = said(record("a block raises"))
        assertEquals(listOf(StageEnd("skipped", "Ultimate Guitar blocked caracole (ug: 403: https://tabs.ultimate-guitar.com/" +
            "tab/soda-stereo/persiana-americana-chords-101: HTTP 403): no more requests to it until later. Nothing was " +
            "marked not found.")), stages(blocked, UgStage))
        val spent = said(record("a spent budget raises"))
        assertEquals(listOf(StageEnd("skipped", "the lookup's 6 requests to Ultimate Guitar are spent; the nightly run " +
            "does the rest")), stages(spent, UgStage))
    }

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
        withContext(song(decision = "not_found")) { assertEquals(UgStages.NOT_IN_INDEX, UgStages.notReady(it)) }
        withContext(song(decision = "review")) {
            assertEquals("caracole isn't sure which Ultimate Guitar song this is: pick it on the lookup page, or run " +
                             "caracole review", UgStages.notReady(it))
            assertEquals(StageEnd("skipped", UgStages.REVIEW), UgSheetStage.run(it))
        }
        withContext(song(decision = "accept")) { assertEquals(null, UgStages.notReady(it)) }
        withContext(song(decision = "pinned")) { assertEquals(null, UgStages.notReady(it)) }
    }

    @Test fun whatAskingCameToIsSaidAsGetPySaysIt() = withContext(song(decision = "accept")) { ctx ->
        val until = Instant.parse("2026-11-04T14:30:59Z")
        val words = mapOf<Asked<*>, StageEnd>(
            Asked.Off("Ultimate Guitar is off in caracole.toml") to StageEnd("skipped", "Ultimate Guitar is off in caracole.toml"),
            Asked.Cooling(until) to StageEnd("skipped", "Ultimate Guitar is cooling down after a block, until 2026-11-04 14:30 UTC"),
            Asked.Cooling(null) to StageEnd("skipped", "Ultimate Guitar is cooling down after a block, until later"),
            Asked.Blocked(ProviderBlocked("ug", "https://x", 429), ProviderState("ug", cooldownUntil = until)) to
                StageEnd("skipped", "Ultimate Guitar blocked caracole (ug: 429: https://x): no more requests to it until " +
                    "2026-11-04 14:30 UTC. Nothing was marked not found."),
            Asked.Spent(hour = true, keptForSheets = false) to
                StageEnd("skipped", "this hour's 60 lookup requests to Ultimate Guitar are spent; the nightly run does the rest"),
            Asked.Spent(hour = false, keptForSheets = true) to
                StageEnd("skipped", "this hour's lookups have spent half of their 60 requests to Ultimate Guitar, and the " +
                    "other half is kept for sheets; the nightly run does the rest"),
            Asked.Failed(ProviderError("ug", "https://x", 500)) to
                StageEnd("failed", "Ultimate Guitar failed (ug: 500: https://x); the nightly run tries again"),
        )
        for ((asked, end) in words) assertEquals(end, UgStages.ended(ctx, asked))
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
