package io.github.danielhp95.caracole.core.lookup

import io.github.danielhp95.caracole.core.config.PhoneConfig
import io.github.danielhp95.caracole.core.config.ProviderPolicy
import io.github.danielhp95.caracole.core.db.Db
import io.github.danielhp95.caracole.core.health.EventLog
import io.github.danielhp95.caracole.core.health.Health
import io.github.danielhp95.caracole.core.http.HttpAnswer
import io.github.danielhp95.caracole.core.http.PoliteClient
import io.github.danielhp95.caracole.core.index.Reads
import io.github.danielhp95.caracole.core.lookup.sites.HarpTabsCommands
import io.github.danielhp95.caracole.core.sites.internal.harptabs.HarpTabsPages
import io.github.danielhp95.caracole.core.testing.FakeTransport
import io.github.danielhp95.caracole.core.testing.Misses
import io.github.danielhp95.caracole.core.testing.TestDb
import io.github.danielhp95.caracole.core.testing.replays.HarpTabsReplay
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import java.time.Instant
import kotlin.test.assertEquals
import kotlin.test.assertNotNull
import kotlin.test.assertNull
import kotlin.test.assertTrue

/** `caracole harptabs --artist` on the phone: vectors/lookup/commands_harptabs.jsonl answered as Python answered it,
 * and its lines where no page is parsed. */
class HarpTabsCommandsTest {
    @get:Rule val tmp = TemporaryFolder()

    private val now: Instant = Instant.parse("2026-11-03T12:00:00Z")
    private val beatles = HarpTabsPages.pageUrl("artist/50/the-beatles")

    @Test fun everyRecordIsAnsweredAsPythonAnsweredIt() {
        val misses = Misses("lookup/commands_harptabs.jsonl")
        HarpTabsReplay.commands(misses)
        misses.assertNone()
        assertTrue(misses.checked > 60, "answers checked: ${misses.checked}")
    }

    private class Said(override val db: Db, override val asking: Asking, override val now: Instant) : CommandContext {
        val lines = ArrayList<String>()
        override fun say(line: String) {
            lines += line
        }
    }

    private fun <T> db(block: (Db) -> T): T = TestDb.fresh(tmp.newFolder()).use { it.writeBlocking(block) }

    private fun index(db: Db) {
        for (path in listOf("artist/50/the-beatles", "artist/1178/billy-joel", "tab/25/piano-man")) {
            val row = HarpTabsPages.parsePageUrl(HarpTabsPages.pageUrl(path))!!
            db.execute("INSERT INTO harptabs_index (path, kind, page_id, key, sitemap) VALUES (?, ?, ?, ?, 'sitemap')",
                       row.path, row.kind, row.pageId, row.key)
        }
    }

    private fun run(db: Db, artist: String, answers: Map<String, HttpAnswer> = emptyMap()): Pair<String, FakeTransport> {
        val transport = FakeTransport(answers)
        val client = PoliteClient("harptabs", ProviderPolicy(budget = 6, delay = 0.0 to 0.0), tmp.newFolder(),
                                  PhoneConfig.DEFAULTS.userAgent, transport, sleep = {}, draws = { low, _ -> low },
                                  onEvent = EventLog(db, Pace.lookupRunId(now)) { now }, monotonic = { 0.0 },
                                  wallClock = { now })
        val pacing = Pacing(sleep = {}, draws = { low, _ -> low }, wallSeconds = { 0.0 }, monotonic = { 0.0 },
                            clock = { now })
        val config = PhoneConfig.read(db)
        val ask = InteractiveAsk(Clients(config, tmp.newFolder(), { transport }, pacing), db, Pace.lookupRunId(now), now,
                                 config = config, make = { _, _ -> client })
        val c = Said(db, ask, now)
        val last = HarpTabsCommands.artist(c, artist)
        assertEquals(emptyList(), c.lines)  // its one line is its last
        return last to transport
    }

    @Test fun anIndexEmptySaysSoAndAsksNothing() = db { db ->
        val (said, site) = run(db, "Billy Joel")
        assertEquals("Not read: harptabs' index is empty; tonight's run reads its sitemap (or caracole harptabs " +
                         "--index).", said)
        assertEquals(emptyList(), site.said)
    }

    @Test fun aNameTheSitemapListsNoPageOfIsNotFoundAndAsksNothing() = db { db ->
        index(db)
        val (said, site) = run(db, "Nobody Known")
        assertEquals("Not found: harptabs lists no artist named Nobody Known.", said)
        assertEquals(emptyList(), site.said)
    }

    @Test fun aPageGoneIsStoredAsGoneNotedAndAGoodRun() = db { db ->
        index(db)
        val (said, site) = run(db, "The Beatles", mapOf("GET $beatles" to FakeTransport.answer(404)))
        assertEquals("Not found: harptabs no longer has The Beatles's page.", said)
        assertEquals(listOf("GET $beatles"), site.said)
        assertEquals("", db.one("SELECT name FROM harptabs_artists WHERE path = 'artist/50/the-beatles'") { it.text(0) })
        assertEquals("2026-11-03T12:00:00Z", db.kvGet("${Reads.READ}harptabs:artist/50/the-beatles"))
        assertEquals(now, Health.state(db, "harptabs").lastOk)
    }

    @Test fun aBlockCoolsTheSiteDownAndChangesNothing() = db { db ->
        index(db)
        val (said, _) = run(db, "The Beatles", mapOf("GET $beatles" to FakeTransport.answer(403, "Forbidden")))
        assertEquals("Not read: harptabs turned us back (harptabs: 403: $beatles: HTTP 403); no asks " +
                         "until 2026-11-04 14:00 UTC.", said)
        assertNotNull(Health.state(db, "harptabs").cooldownUntil)
        assertNull(db.one("SELECT 1 FROM harptabs_artists") { true })
        val (again, site) = run(db, "The Beatles")
        assertEquals("Not read: waiting out harptabs until " +
                         "2026-11-04 14:00 UTC.", again)
        assertEquals(emptyList(), site.said)
    }

    @Test fun theSiteTurnedOffAsksNothing() = db { db ->
        index(db)
        db.kvSet(PhoneConfig.SETTINGS_KV, """{"providers": {"harptabs": {"enabled": false}}}""")
        val (said, site) = run(db, "Billy Joel")
        assertEquals("Not read: harptabs is off (caracole.toml). Nothing asked.", said)
        assertEquals(emptyList(), site.said)
    }
}
