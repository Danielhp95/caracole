package io.github.danielhp95.caracole.core.sites

import io.github.danielhp95.caracole.core.config.PhoneConfig
import io.github.danielhp95.caracole.core.health.ProviderState
import io.github.danielhp95.caracole.core.http.GameTabsParseError
import io.github.danielhp95.caracole.core.http.HttpAnswer
import io.github.danielhp95.caracole.core.http.PoliteClient
import io.github.danielhp95.caracole.core.http.ProviderBlocked
import io.github.danielhp95.caracole.core.library.LibraryStore
import io.github.danielhp95.caracole.core.library.Overrides
import io.github.danielhp95.caracole.core.library.Songs
import io.github.danielhp95.caracole.core.lookup.Asked
import io.github.danielhp95.caracole.core.lookup.StageContext
import io.github.danielhp95.caracole.core.lookup.StageEnd
import io.github.danielhp95.caracole.core.lookup.sites.GameTabsStage
import io.github.danielhp95.caracole.core.testing.Corpus
import io.github.danielhp95.caracole.core.testing.FakeAsking
import io.github.danielhp95.caracole.core.testing.FakeTransport
import io.github.danielhp95.caracole.core.testing.Fixtures
import io.github.danielhp95.caracole.core.testing.Misses
import io.github.danielhp95.caracole.core.testing.Scenarios
import io.github.danielhp95.caracole.core.testing.TestDb
import io.github.danielhp95.caracole.core.testing.replays.GameTabsReplay
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.int
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import kotlinx.serialization.json.long
import org.junit.Assume.assumeTrue
import org.junit.Test
import java.nio.file.Files
import java.time.Instant
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith
import kotlin.test.assertTrue

/**
 * gametabs.net on the phone: GameTabsReplay (vectors/sites/gametabs.jsonl, vectors/lookup/gametabs.jsonl) on the JVM,
 * and the lookup's gametabs stage over the corpus's worlds, asked through FakeAsking, in get.py's words.
 */
class GameTabsTest {
    @Test fun theCorpusIsAnsweredAsPythonAnswersIt() {
        val misses = Misses("gametabs")
        GameTabsReplay.replay(misses)
        misses.assertNone()
    }

    @Test fun aPageNumberIntRefusesIsAParseErrorNeverACrash() {
        assumeTrue("waiting on html-tree", GameTabsReplay.htmlReady)
        val page = Corpus.fixture("gametabs/game_final-fantasy-vii.html").toString(Charsets.UTF_8)
        for (number in listOf("²", "①", "1²")) {
            val e = assertFailsWith<GameTabsParseError> {
                GameTabsPages.parseGamePage(page.replaceFirst("\n            5\n", "\n            $number\n").toByteArray())
            }
            assertTrue("page number" in e.message!!, e.message)
        }
        val seven = page.replaceFirst("\n            5\n", "\n            ٧\n").toByteArray()
        assertEquals(7, GameTabsPages.parseGamePage(seven).pages.toInt())
    }

    // --- the stage -----------------------------------------------------------------------------------------------

    /** The stage for the song of the lookup record [case], in its world, its answers [answers] (the record's by
     * default), its client's budget [budget]; no client at all with [client] false. */
    private fun stage(case: String, answers: Map<String, HttpAnswer>? = null, budget: Long = 6,
                      client: Boolean = true): StageEnd {
        val record = Corpus.lines(GameTabsReplay.LOOKUP).first { it["case"]?.jsonPrimitive?.content == case }
        val dir = Files.createTempDirectory("caracole-gametabs").toFile()
        try {
            val library = java.io.File(dir, "library").apply { mkdirs() }
            val now = Instant.parse(record.getValue("now").jsonPrimitive.content)
            return TestDb.fresh(dir).use { database ->
                database.writeBlocking { db ->
                    Fixtures.loadRecords(db, record.getValue("fixture").jsonArray.map { it.jsonObject }, library, case)
                    val id = record.getValue("kw").jsonObject.getValue("only").jsonArray[0].jsonPrimitive.long
                    val transport = FakeTransport(answers ?: recorded(record))
                    val made = PoliteClient(GameTabsPages.PROVIDER,
                                            PhoneConfig.DEFAULTS.provider(GameTabsPages.PROVIDER).copy(budget = budget, delay = 0.0 to 0.0),
                                            java.io.File(dir, "cache"), PhoneConfig.DEFAULTS.userAgent, transport,
                                            sleep = {}, draws = { low, _ -> low }, monotonic = { 0.0 }, wallClock = { now })
                    made.use {
                        val asking = FakeAsking(if (client) mapOf(GameTabsPages.PROVIDER to made) else emptyMap())
                        GameTabsStage.run(StageContext(db, Songs.byId(db, id)!!, Overrides.read(db), PhoneConfig.DEFAULTS,
                                                       LibraryStore(library), asking, now))
                    }
                }
            }
        } finally {
            dir.deleteRecursively()
        }
    }

    private fun recorded(record: JsonObject): Map<String, HttpAnswer> =
        (record["answers"] as? JsonObject ?: JsonObject(emptyMap())).mapValues { (_, a) ->
            val o = a.jsonObject
            HttpAnswer(o.getValue("status").jsonPrimitive.int,
                       (o["headers"] as? JsonArray ?: JsonArray(emptyList())).map { h ->
                           h.jsonArray[0].jsonPrimitive.content to h.jsonArray[1].jsonPrimitive.content
                       }, Scenarios.body(o.getValue("body")))
        }

    @Test fun aTabKeptIsSaidSo() {
        assumeTrue("waiting on html-tree", GameTabsReplay.htmlReady)
        assertEquals(StageEnd("done", "game music tab kept"),
                     stage("a song named by its game: the first candidate gone, the second kept as gametab-1.txt"))
    }

    @Test fun candidatesNoneOfWhichIsTheSongsAreNoTabThere() {
        assumeTrue("waiting on html-tree", GameTabsReplay.htmlReady)
        assertEquals(StageEnd("done", "no tab there of its game or composer"),
                     stage("a page of another title, and one of another game: a miss"))
    }

    @Test fun aSongWithNoCandidateIsSkippedAndNothingIsAsked() {
        assertEquals(StageEnd("skipped", "no tab wanted, or gametabs.net's index has no tab of the title of its game " +
                                             "or composer"),
                     stage("the title, by no game or composer of it: nothing asked"))
    }

    @Test fun aBlockIsSaidAsGetPySaysItNothingMarkedNotFound() {
        val end = stage("a block propagates and keeps nothing")
        assertEquals(StageEnd("skipped", "gametabs.net blocked caracole (gametabs: 429: " +
            "https://gametabs.net/tabs/hollow-knight/resting-grounds: HTTP 429): no more requests to it until later. " +
            "Nothing was marked not found."), end)
    }

    @Test fun aSpentBudgetLeavesTheRestToTheNightlyRun() {
        assertEquals(StageEnd("skipped", "the lookup's 6 requests to gametabs.net are spent; the nightly run does the rest"),
                     stage("a spent budget ends the pass, no miss", budget = 1))
    }

    @Test fun anErrorFailsTheStageNeverAMiss() {
        assertEquals(StageEnd("failed", "gametabs.net failed (gametabs: 502: " +
            "https://gametabs.net/tabs/hollow-knight/resting-grounds-2: HTTP 502); the nightly run tries again"),
                     stage("a server error leaves the song for the next run"))
    }

    @Test fun aSiteThatCantBeAskedIsSkippedInTheAskingsWords() {
        assertEquals(StageEnd("skipped", "no client for gametabs"),
                     stage("the title, by no game or composer of it: nothing asked", client = false))
    }

    @Test fun theEnvelopesOtherEndsInGetPysWords() {
        val cfg = PhoneConfig.DEFAULTS
        assertEquals(StageEnd("skipped", "gametabs.net is cooling down after a block, until 2026-11-04 14:00 UTC"),
                     GameTabsStage.end(cfg, Asked.Cooling(Instant.parse("2026-11-04T14:00:30Z"))))
        assertEquals(StageEnd("skipped", "gametabs.net is cooling down after a block, until later"),
                     GameTabsStage.end(cfg, Asked.Cooling(null)))
        val block = ProviderBlocked("gametabs", "https://gametabs.net/x", 403)
        val state = ProviderState("gametabs", strikes = java.math.BigInteger.ONE, cooldownUntil = Instant.parse("2026-11-05T02:00:00Z"))
        assertEquals(StageEnd("skipped", "gametabs.net blocked caracole (${block.message}): no more requests to it " +
            "until 2026-11-05 02:00 UTC. Nothing was marked not found."), GameTabsStage.end(cfg, Asked.Blocked(block, state)))
        assertEquals(StageEnd("skipped", "this hour's 60 lookup requests to gametabs.net are spent; the nightly run " +
            "does the rest"), GameTabsStage.end(cfg, Asked.Spent(hour = true, keptForSheets = false)))
        assertEquals(StageEnd("skipped", "gametabs.net is off in caracole.toml"),
                     GameTabsStage.end(cfg, Asked.Off("gametabs.net is off in caracole.toml")))
    }
}
