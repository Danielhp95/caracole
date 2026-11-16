package io.github.danielhp95.caracole.core.lookup

import io.github.danielhp95.caracole.core.config.PhoneConfig
import io.github.danielhp95.caracole.core.db.Db
import io.github.danielhp95.caracole.core.http.Draws
import io.github.danielhp95.caracole.core.index.Stamps
import io.github.danielhp95.caracole.core.library.LibraryStore
import io.github.danielhp95.caracole.core.library.Songs
import io.github.danielhp95.caracole.core.library.Versions
import io.github.danielhp95.caracole.core.testing.RefusingTransport
import io.github.danielhp95.caracole.core.testing.TestDb
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import java.io.File
import java.time.Instant
import kotlin.test.assertEquals

/**
 * get.py's `_owed`: a song whose Ultimate Guitar part was cut short is marked to fetch at night, the ug stage
 * skipped because half the hour's requests are kept for sheets as any other cut.
 */
class OwedAfterTheSheetTest {
    @get:Rule val tmp = TemporaryFolder()

    private val now: Instant = Instant.parse("2026-11-03T12:00:00Z")
    private val pacing = Pacing(sleep = {}, draws = Draws { a, _ -> a }, wallSeconds = { now.epochSecond.toDouble() },
                                monotonic = { 0.0 }, clock = { now })

    private fun db(block: (Db, File) -> Unit): Unit = TestDb.fresh(tmp.newFolder()).use { database ->
        val cache = tmp.newFolder("cache")
        database.writeBlocking { block(it, cache) }
    }

    @Test fun `the ug stage skipped for the sheets' share owes the song a fetch`() = db { db, cache ->
        val store = LibraryStore(tmp.newFolder("library"))
        val song = store.add(db, "Radiohead", "Creep", now = Stamps.of(now))
        Versions.updateSong(db, song.id, mapOf("match_decision" to "accept", "ug_dirty" to false))
        repeat(30) {  // half the hour's 60 lookup requests to Ultimate Guitar are spent
            db.execute("INSERT INTO events (run, at, provider, url, status, decision) VALUES ('lookup:x', ?, 'ug', 'u', " +
                       "200, 'ok')", "2026-11-03T11:30:00Z")
        }
        val ask = InteractiveAsk(Clients(PhoneConfig.DEFAULTS, cache, { RefusingTransport }, pacing), db,
                                 Pace.lookupRunId(now), now)
        ask.owedSong = song.id
        val end = LookupWords.end(PhoneConfig.DEFAULTS, "ug", ask.afterTheSheet.ask("ug") { error("asked") }) { error("done") }
        assertEquals("skipped", end.state)
        assertEquals(true, Songs.byId(db, song.id)!!.ugDirty)
    }
}
