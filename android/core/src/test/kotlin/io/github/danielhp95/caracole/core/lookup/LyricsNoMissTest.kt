package io.github.danielhp95.caracole.core.lookup

import io.github.danielhp95.caracole.core.config.PhoneConfig
import io.github.danielhp95.caracole.core.db.Db
import io.github.danielhp95.caracole.core.http.Draws
import io.github.danielhp95.caracole.core.http.HttpAnswer
import io.github.danielhp95.caracole.core.http.Transport
import io.github.danielhp95.caracole.core.index.Stamps
import io.github.danielhp95.caracole.core.library.LibraryStore
import io.github.danielhp95.caracole.core.library.Overrides
import io.github.danielhp95.caracole.core.library.Songs
import io.github.danielhp95.caracole.core.library.Versions
import io.github.danielhp95.caracole.core.lookup.sites.AzLyricsStage
import io.github.danielhp95.caracole.core.lookup.sites.MegalobizStage
import io.github.danielhp95.caracole.core.testing.TestDb
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import java.io.File
import java.time.Instant
import kotlin.test.assertEquals
import kotlin.test.assertNull

/**
 * "A song's lyrics are missing only once every site asked answered a miss": Megalobiz's error, its block (a 403 or a
 * 429) and a spent budget alike put a song LRCLIB missed back to pending, and AZLyrics then asks nothing about it, as
 * megalobiz_fetch.py's pass does.
 */
class LyricsNoMissTest {
    @get:Rule val tmp = TemporaryFolder()

    private val now: Instant = Instant.parse("2026-11-03T12:00:00Z")
    private val pacing = Pacing(sleep = {}, draws = Draws { a, _ -> a }, wallSeconds = { now.epochSecond.toDouble() },
                                monotonic = { 0.0 }, clock = { now })

    private fun db(block: (Db, File) -> Unit): Unit = TestDb.fresh(tmp.newFolder()).use { database ->
        val cache = tmp.newFolder("cache")
        database.writeBlocking { block(it, cache) }
    }

    /** One lookup's Megalobiz then AZLyrics stages for a song LRCLIB just missed: its status and AZLyrics' check. */
    private fun after(db: Db, cache: File, megalobiz: Int): Pair<String, String?> {
        val store = LibraryStore(tmp.newFolder("library$megalobiz"))
        val song = store.add(db, "Radiohead", "Creep $megalobiz", now = Stamps.of(now))
        Versions.updateSong(db, song.id, mapOf("lyrics_status" to "missing", "lyrics_at" to Stamps.of(now)))
        val sites: (String) -> Transport = { provider ->
            Transport { _ ->
                if (provider == "megalobiz") HttpAnswer(megalobiz, emptyList(), "no".toByteArray())
                else HttpAnswer(404, emptyList(), "no such artist".toByteArray())
            }
        }
        val ask = InteractiveAsk(Clients(PhoneConfig.DEFAULTS, cache, sites, pacing), db, Pace.lookupRunId(now), now)
        for (stage in listOf(MegalobizStage, AzLyricsStage)) {
            val current = Songs.byId(db, song.id)!!
            stage.run(StageContext(db, current, Overrides.read(db), PhoneConfig.DEFAULTS, store, ask, now, cache))
        }
        return Songs.byId(db, song.id)!!.lyricsStatus to db.kvGet("azlyrics:checked:${song.id}")
    }

    @Test fun `Megalobiz's error puts the song back to pending`() = db { db, cache ->
        val (status, checked) = after(db, cache, megalobiz = 500)
        assertEquals("pending", status)
        assertNull(checked)
    }

    @Test fun `so does its block`() = db { db, cache ->
        val (status, checked) = after(db, cache, megalobiz = 429)
        assertEquals("pending", status)
        assertNull(checked)
    }
}
