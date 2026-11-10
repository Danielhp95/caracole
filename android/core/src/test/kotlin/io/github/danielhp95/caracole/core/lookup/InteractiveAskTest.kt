package io.github.danielhp95.caracole.core.lookup

import io.github.danielhp95.caracole.core.config.PhoneConfig
import io.github.danielhp95.caracole.core.db.Db
import io.github.danielhp95.caracole.core.health.Alerts
import io.github.danielhp95.caracole.core.health.Health
import io.github.danielhp95.caracole.core.http.BudgetExhausted
import io.github.danielhp95.caracole.core.http.Client
import io.github.danielhp95.caracole.core.http.Draws
import io.github.danielhp95.caracole.core.http.ProviderError
import io.github.danielhp95.caracole.core.index.Stamps
import io.github.danielhp95.caracole.core.library.LibraryStore
import io.github.danielhp95.caracole.core.library.Songs
import io.github.danielhp95.caracole.core.library.Versions
import io.github.danielhp95.caracole.core.testing.FakeTransport
import io.github.danielhp95.caracole.core.testing.RefusingTransport
import io.github.danielhp95.caracole.core.testing.TestDb
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import java.io.File
import java.time.Instant
import kotlin.test.assertEquals
import kotlin.test.assertIs
import kotlin.test.assertNull
import kotlin.test.assertSame
import kotlin.test.assertTrue

/** get.py's envelope on the phone: what asking a site came to, each record it leaves, the alert a block sends, and
 * what follows the sheet held to its share (vectors/lookup/asking.jsonl and after_the_sheet.jsonl hold the words). */
class InteractiveAskTest {
    @get:Rule val tmp = TemporaryFolder()

    private val now: Instant = Instant.parse("2026-11-03T12:00:00Z")
    private val pacing = Pacing(sleep = {}, draws = Draws { a, _ -> a }, wallSeconds = { now.epochSecond.toDouble() },
                                monotonic = { 0.0 }, clock = { now })
    private val ug = "https://tabs.ultimate-guitar.com/tab/radiohead/creep-chords-4169"
    private val lrclib = "https://lrclib.net/api/get?artist_name=Radiohead&track_name=Creep"
    private val site = FakeTransport(mapOf(
        "GET $ug" to FakeTransport.answer(403, "Forbidden"),
        "GET $lrclib" to FakeTransport.answer(200, "{}", listOf("content-type" to "application/json")),
        "GET https://lrclib.net/api/get?x=502" to FakeTransport.answer(502, "Bad Gateway"),
    ))

    private class Heard : Alerts {
        val blocks = ArrayList<Triple<String, Instant?, String>>()
        override fun blocked(provider: String, until: Instant?, message: String) {
            blocks += Triple(provider, until, message)
        }

        override fun failed(title: String, line: String) {}
    }

    private fun db(block: (Db, File) -> Unit): Unit = TestDb.fresh(tmp.newFolder()).use { database ->
        val cache = tmp.newFolder("cache")
        database.writeBlocking { block(it, cache) }
    }

    private fun ask(db: Db, cache: File, alerts: Alerts = Alerts.NONE, cfg: PhoneConfig = PhoneConfig.DEFAULTS) =
        InteractiveAsk(Clients(cfg, cache, { site }, pacing), db, Pace.lookupRunId(now), now, alerts, cfg)

    @Test fun aBlockCoolsTheSiteDownAlertsOnceAndEndsItsPartOfTheLookup() = db { db, cache ->
        val alerts = Heard()
        val ask = ask(db, cache, alerts)
        val first = ask.ask("ug") { it.get(ug) }
        assertIs<Asked.Blocked>(first)
        assertEquals(Instant.parse("2026-11-04T14:00:00Z"), first.state.cooldownUntil)
        assertEquals(listOf(Triple("ug", first.state.cooldownUntil, first.error.message!!)), alerts.blocks)
        assertEquals(Health.state(db, "ug"), first.state)
        val again = ask.ask("ug") { error("asked again") }
        assertEquals(Asked.Off(LookupWords.blockedEarlier("ug")), again)
        assertEquals(1, alerts.blocks.size)  // once a block
        assertEquals(mapOf("ug" to 1), ask.requests)
        val (run, decision) = db.one("SELECT run, decision FROM events") { it.text(0) to it.text(1) }!!
        assertEquals("lookup:2026-11-03T12:00:00Z" to "blocked", run to decision)
        assertEquals("1793707200.000", db.kvGet(Pace.LAST_SENT + "ug"))
    }

    @Test fun anErrorIsCountedAndTheSiteIsAskedNothingMore() = db { db, cache ->
        val ask = ask(db, cache)
        val failed = ask.ask("lrclib") { it.get("https://lrclib.net/api/get?x=502") }
        assertIs<Asked.Failed>(failed)
        assertTrue("502" in Health.state(db, "lrclib").lastError.orEmpty())
        assertEquals(setOf("lrclib"), ask.failed)
        assertEquals(Asked.Off(LookupWords.failedEarlier("lrclib")), ask.ask("lrclib") { error("asked again") })
        assertEquals(StageEnd("failed", LookupWords.failed(failed.error)),
                     LookupWords.end(PhoneConfig.DEFAULTS, "lrclib", failed))
    }

    @Test fun eachSiteHasOneClientALookupAndAnAnswerIsAGoodRun() = db { db, cache ->
        val ask = ask(db, cache)
        val clients = ArrayList<Client>()
        assertEquals(Asked.Done(200), ask.ask("lrclib") { clients += it; it.get(lrclib).status })
        assertEquals(Asked.Done(200), ask.ask("lrclib") { clients += it; it.get(lrclib).status })  // the cache's
        assertSame(clients[0], clients[1])
        assertEquals(mapOf("lrclib" to 1), ask.requests)
        assertNull(Health.state(db, "lrclib").lastOk)
        ask.recordAnswers()
        assertEquals(now, Health.state(db, "lrclib").lastOk)
        ask.close()
        assertEquals(mapOf("lrclib" to 1), ask.requests)  // still said once closed
    }

    @Test fun aSiteThatBlockedHasNoGoodRunWhateverItAnsweredBefore() = db { db, cache ->
        val ask = ask(db, cache)
        ask.ask("ug") { it.get(ug) }
        ask.recordAnswers()
        assertNull(Health.state(db, "ug").lastOk)
    }

    @Test fun aSiteOffOrCoolingIsAskedNothingAndSendsNothing() = db { db, cache ->
        val cfg = PhoneConfig.DEFAULTS.copy(providers = PhoneConfig.DEFAULTS.providers +
                                                ("megalobiz" to PhoneConfig.DEFAULTS.provider("megalobiz").copy(enabled = false)))
        val ask = InteractiveAsk(Clients(cfg, cache, { RefusingTransport }, pacing), db, Pace.lookupRunId(now), now,
                                 config = cfg)
        assertEquals(Asked.Off(LookupWords.off("megalobiz")), ask.ask("megalobiz") { error("asked") })
        Health.recordBlock(db, "azlyrics", now.minusSeconds(60), "azlyrics: 403")
        assertEquals(Asked.Cooling(Health.state(db, "azlyrics").cooldownUntil), ask.ask("azlyrics") { error("asked") })
        assertEquals(emptyMap(), ask.requests)
    }

    @Test fun aSpentBudgetSaysWhoseItWas() = db { db, cache ->
        val ask = ask(db, cache)
        assertEquals(Asked.Spent(hour = false, keptForSheets = false), ask.ask("lrclib") { throw BudgetExhausted("lrclib") })
        repeat(57) {
            db.execute("INSERT INTO events (run, at, provider, url, status, decision) VALUES ('lookup:x', ?, 'ug', 'u', " +
                       "200, 'ok')", "2026-11-03T11:30:00Z")
        }
        assertEquals(Asked.Spent(hour = true, keptForSheets = false), ask(db, cache).ask("ug") { throw BudgetExhausted("ug") })
    }

    @Test fun whatFollowsTheSheetKeepsHalfOfTheHourForSheets() = db { db, cache ->
        repeat(28) {
            db.execute("INSERT INTO events (run, at, provider, url, status, decision) VALUES ('lookup:x', ?, 'ug', 'u', " +
                       "200, 'ok')", "2026-11-03T11:30:00Z")
        }
        val ask = ask(db, cache)
        assertEquals(2, ask.left("ug"))
        assertEquals(Asked.Done(2L), ask.afterTheSheet.ask("ug") { it.policy.budget })
        assertEquals(setOf("ug"), ask.keptForSheets)
        assertEquals(Asked.Spent(hour = false, keptForSheets = true),
                     ask.afterTheSheet.ask("ug") { throw BudgetExhausted("ug") })
        repeat(2) {
            db.execute("INSERT INTO events (run, at, provider, url, status, decision) VALUES ('lookup:x', ?, 'ug', 'u', " +
                       "200, 'ok')", "2026-11-03T11:30:00Z")
        }
        val spent = ask(db, cache)
        assertEquals(Asked.Spent(hour = false, keptForSheets = true), spent.afterTheSheet.ask("ug") { error("asked") })
        assertEquals(emptyMap(), spent.requests)  // nothing sent, no client made
    }

    @Test fun aMatchedSongWhoseUltimateGuitarPartWasCutShortIsOwedAFetch() = db { db, cache ->
        val store = LibraryStore(tmp.newFolder("library"))
        val song = store.add(db, "Radiohead", "Creep", now = Stamps.of(now))
        Versions.updateSong(db, song.id, mapOf("match_decision" to "accept", "ug_dirty" to false))
        val ask = ask(db, cache)
        ask.owedSong = song.id
        ask.ask("lrclib") { throw ProviderError("lrclib", null, 500, null) }
        assertEquals(false, Songs.byId(db, song.id)!!.ugDirty)  // another site's error owes UG nothing
        ask.ask("ug") { throw BudgetExhausted("ug") }
        assertEquals(true, Songs.byId(db, song.id)!!.ugDirty)
    }

    @Test fun aCommandsRunIsItsOwn() = db { db, cache ->
        val ask = InteractiveAsk(Clients(PhoneConfig.DEFAULTS, cache, { site }, pacing), db,
                                 "lacuerda-search:2026-11-03T12:00:00Z", now)
        ask.ask("lrclib") { it.get(lrclib) }
        assertEquals("lookup:lacuerda-search:2026-11-03T12:00:00Z", db.one("SELECT run FROM events") { it.text(0) })
        ask.recordAnswers()
        assertEquals(now, Health.state(db, "lrclib").lastOk)
    }
}
