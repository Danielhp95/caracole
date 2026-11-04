package io.github.danielhp95.caracole.core.sync

import io.github.danielhp95.caracole.core.config.MatchPolicy
import io.github.danielhp95.caracole.core.config.PhoneConfig
import io.github.danielhp95.caracole.core.config.RankPolicy
import io.github.danielhp95.caracole.core.db.Db
import io.github.danielhp95.caracole.core.json.PyJson
import io.github.danielhp95.caracole.core.sync.internal.client.Documents
import io.github.danielhp95.caracole.core.testing.Fixtures
import io.github.danielhp95.caracole.core.testing.Misses
import io.github.danielhp95.caracole.core.testing.TestDb
import io.github.danielhp95.caracole.core.testing.replays.SettingsReplay
import io.github.danielhp95.caracole.core.testing.sync.FakeComputer
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith
import kotlin.test.assertNull
import kotlin.test.assertTrue

/**
 * The computer's settings on the phone (docs/superpowers/specs/2026-11-03-politeness-crossing.md, "Settings"): the
 * state document's `settings` read as the computer gave them, kept by PhoneConfig.take as kv `phone:settings`, which
 * PhoneConfig.read lays over config.py's defaults; vectors/sync/settings.jsonl answered as Python answered it. A take
 * changes no unit, and nothing of either side's politeness is in it.
 */
class SettingsTest {
    @get:Rule val tmp = TemporaryFolder()

    private fun <T> db(block: (Db) -> T): T = TestDb.fresh(tmp.newFolder()).use { it.writeBlocking(block) }

    private val settings = FakeComputer.SETTINGS

    @Test fun `every record of vectors sync settings and settings_take is answered as Python answered it`() {
        val misses = Misses("settings")
        SettingsReplay.replay(misses)
        misses.assertNone()
        assertTrue(misses.checked >= 24, "answers checked: ${misses.checked}")
    }

    /** A state document as GET /api/peer/state answers it, with [members] laid over it. */
    private fun state(vararg members: Pair<String, JsonElement>): JsonObject = JsonObject(linkedMapOf(
        "format" to JsonPrimitive(Units.FORMAT), "server" to JsonPrimitive("0123456789abcdef"),
        "caracole" to JsonPrimitive("0.1.0"), "name" to JsonPrimitive("Desk"),
        "now" to JsonPrimitive("2026-11-03T12:00:00Z"), "indexes" to JsonObject(emptyMap()),
        "units" to JsonObject(emptyMap()), "base" to JsonNull,
    ) + members + ("token" to JsonPrimitive("computer-token-1")))

    @Test fun `the state document's settings are read as the computer gave them`() {
        assertEquals(settings, Documents.state(state("settings" to settings)).settings)
        // A computer older than them gives none; a member that isn't an object is none too, and the rest is read.
        assertNull(Documents.state(state()).settings)
        for (none in listOf(JsonNull, JsonArray(listOf(settings)), JsonPrimitive("settings"), JsonPrimitive(1))) {
            val read = Documents.state(state("settings" to none))
            assertNull(read.settings, "$none")
            assertEquals("Desk", read.name)
            assertEquals("computer-token-1", read.token)
        }
        // PeerState.read, the replay's way in, is the same reading; a document that isn't a state is a PeerError.
        assertEquals(Documents.state(state("settings" to settings)), PeerState.read(state("settings" to settings)))
        assertFailsWith<PeerError> { PeerState.read(JsonObject(mapOf("settings" to settings))) }
    }

    @Test fun `the agree stage's take keeps what a state gives and nothing of one that gives none`() = db { db ->
        SyncEngine.takeSettings(db, PeerState.read(state("settings" to settings)))
        assertEquals(PyJson.dumps(settings), db.kvGet(PhoneConfig.SETTINGS_KV))
        for (none in listOf(state(), state("settings" to JsonNull), state("settings" to JsonArray(emptyList())))) {
            SyncEngine.takeSettings(db, PeerState.read(none))
            assertEquals(PyJson.dumps(settings), db.kvGet(PhoneConfig.SETTINGS_KV), "$none")
        }
    }

    @Test fun `a take keeps the document whole as kv phone settings, as kv_set_json writes a value`() = db { db ->
        assertNull(db.kvGet(PhoneConfig.SETTINGS_KV))
        PhoneConfig.take(db, settings)
        assertEquals(PyJson.dumps(settings), db.kvGet(PhoneConfig.SETTINGS_KV))
        assertTrue("\"accept\": 85.5" in db.kvGet(PhoneConfig.SETTINGS_KV)!!, "a number as the computer wrote it")
        assertTrue("歌" in db.kvGet(PhoneConfig.SETTINGS_KV)!!, "ensure_ascii=False")

        // The next sync's replaces it whole: a member the computer no longer gives is gone.
        val later = JsonObject(linkedMapOf("name" to JsonNull, "user_agent" to JsonPrimitive("caracole/0.1 (later)")))
        PhoneConfig.take(db, later)
        assertEquals("""{"name": null, "user_agent": "caracole/0.1 (later)"}""", db.kvGet(PhoneConfig.SETTINGS_KV))
    }

    @Test fun `a take changes no unit's digest and writes no other record`() = db { db ->
        val library = tmp.newFolder("library")
        Fixtures.load(db, "sync/fixtures/rich.jsonl", library)
        db.kvSet("provider:ug", """{"strikes": 1, "cooldown_until": "2026-11-04T14:00:00Z"}""")
        db.kvSet("http:last_request:ug", "1762171200.250")
        val units = Units.libraryState(db)
        val kv = kv(db)
        val songs = db.query("SELECT * FROM songs ORDER BY id") { row -> row.columns.indices.map { row.text(it) } }
        val events = db.one("SELECT COUNT(*) FROM events") { it.long(0) }

        PhoneConfig.take(db, settings)

        assertEquals(units, Units.libraryState(db))
        assertEquals(kv + (PhoneConfig.SETTINGS_KV to PyJson.dumps(settings)), kv(db))
        assertEquals(songs, db.query("SELECT * FROM songs ORDER BY id") { row -> row.columns.indices.map { row.text(it) } })
        assertEquals(events, db.one("SELECT COUNT(*) FROM events") { it.long(0) })
        assertTrue(Units.libraryState(db).keys.none { "settings" in it })
    }

    @Test fun `what a take keeps is what PhoneConfig read answers`() = db { db ->
        db.kvDelete(PhoneConfig.SETTINGS_KV)
        PhoneConfig.take(db, settings)
        val cfg = PhoneConfig.read(db)
        assertEquals("Canciones de Dani · 歌", cfg.libraryName)
        assertEquals("caracole/0.1 (Dani's tabs)", cfg.userAgent)
        assertEquals(PhoneConfig.DEFAULTS.provider("ug").copy(lookupDelay = 0.5 to 1.5, lookupRequests = 3,
                                                              lookupPerHour = 30), cfg.provider("ug"))
        assertEquals(PhoneConfig.DEFAULTS.provider("megalobiz").copy(enabled = false), cfg.provider("megalobiz"))
        assertEquals(PhoneConfig.DEFAULTS.provider("lacuerda"), cfg.provider("lacuerda"))
        assertEquals(PhoneConfig.DEFAULTS.provider("lrclib"), cfg.provider("lrclib"), "a provider it doesn't name")
        assertEquals(MatchPolicy(accept = 85.5, review = 70.0), cfg.match)
        assertEquals(RankPolicy(coverageThreshold = 0.75, lineMatch = 80.0, priorVotes = 12.0, scoredSheets = 4), cfg.rank)
    }

    private fun kv(db: Db): Map<String, String?> =
        db.query("SELECT key, value FROM kv ORDER BY key") { it.text(0)!! to it.text(1) }.toMap()
}
