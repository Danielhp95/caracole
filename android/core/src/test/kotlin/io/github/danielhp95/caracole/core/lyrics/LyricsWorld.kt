package io.github.danielhp95.caracole.core.lyrics

import io.github.danielhp95.caracole.core.config.PhoneConfig
import io.github.danielhp95.caracole.core.db.Database
import io.github.danielhp95.caracole.core.db.Db
import io.github.danielhp95.caracole.core.http.HttpAnswer
import io.github.danielhp95.caracole.core.http.PoliteClient
import io.github.danielhp95.caracole.core.library.LibraryStore
import io.github.danielhp95.caracole.core.library.SongRow
import io.github.danielhp95.caracole.core.library.Versions
import io.github.danielhp95.caracole.core.testing.FakeTransport
import io.github.danielhp95.caracole.core.testing.TestDb
import java.io.File
import java.time.Instant

/** A phone's library of songs for the lyrics tests: its database, its folder, and a client per site over a fake one
 * (no pause, the record's clock). */
class LyricsWorld(val dir: File) : AutoCloseable {
    val database: Database = TestDb.fresh(dir)
    val library = LibraryStore(File(dir, "library").apply { mkdirs() })
    val now: Instant = Instant.parse("2026-11-03T12:00:00Z")

    fun <T> db(block: (Db) -> T): T = database.writeBlocking(block)

    fun song(artist: String, title: String, durationMs: Long? = null, vararg columns: Pair<String, Any?>): SongRow = db { db ->
        val song = library.add(db, artist, title, durationMs = durationMs, now = "2026-10-01T00:00:00Z")
        if (columns.isNotEmpty()) Versions.updateSong(db, song.id, linkedMapOf(*columns), now = "2026-10-01T00:00:00Z")
        io.github.danielhp95.caracole.core.library.Songs.byId(db, song.id)!!
    }

    fun client(provider: String, answers: Map<String, HttpAnswer>, budget: Long = 6): Pair<PoliteClient, FakeTransport> {
        val transport = FakeTransport(answers)
        val base = PhoneConfig.DEFAULTS.provider(provider)
        val client = PoliteClient(provider, base.copy(budget = budget, delay = 0.0 to 0.0), File(dir, "cache"),
                                  PhoneConfig.DEFAULTS.userAgent, transport, sleep = {}, draws = { low, _ -> low },
                                  monotonic = { 0.0 }, wallClock = { now })
        return client to transport
    }

    override fun close() = database.close()

    companion object {
        /** A fixture of tests/fixtures/, as text. */
        fun fixture(path: String): String =
            io.github.danielhp95.caracole.core.testing.Corpus.fixture(path).toString(Charsets.UTF_8)
    }
}
