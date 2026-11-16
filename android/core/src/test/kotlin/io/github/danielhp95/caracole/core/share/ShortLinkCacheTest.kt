package io.github.danielhp95.caracole.core.share

import io.github.danielhp95.caracole.core.config.PhoneConfig
import io.github.danielhp95.caracole.core.db.Db
import io.github.danielhp95.caracole.core.health.Alerts
import io.github.danielhp95.caracole.core.http.Draws
import io.github.danielhp95.caracole.core.http.HttpAnswer
import io.github.danielhp95.caracole.core.lookup.Clients
import io.github.danielhp95.caracole.core.lookup.Pacing
import io.github.danielhp95.caracole.core.share.ShareLinks.Read
import io.github.danielhp95.caracole.core.testing.Corpus
import io.github.danielhp95.caracole.core.testing.FakeTransport
import io.github.danielhp95.caracole.core.testing.TestDb
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import java.io.File
import java.time.Instant
import kotlin.test.assertEquals

/**
 * A short link (spotify.link, tidal.link) as the cache keeps it: its hop, a redirect PoliteClient never caches, kept
 * beside the cache once the link was read, so the share page loaded again asks nothing; and a track page cached
 * unreadable asked for once more past the cache, its hop not asked twice.
 */
class ShortLinkCacheTest {
    @get:Rule val tmp = TemporaryFolder()

    private val now: Instant = Instant.parse("2026-11-10T18:00:00Z")
    private val pacing = Pacing(sleep = {}, draws = Draws { a, _ -> a }, wallSeconds = { now.epochSecond.toDouble() },
                                monotonic = { 0.0 }, clock = { now })
    private val track = "https://open.spotify.com/track/4u7EnebtmKWzUH433cf5Qv"
    private val short = "https://spotify.link/j7xk2xnhzDb"
    private val good = HttpAnswer(200, listOf("content-type" to "text/html; charset=utf-8"), Corpus.fixture("spotify/track.html"))
    private val notice = FakeTransport.answer(200, "<html><head><title>Spotify</title></head><body>One moment</body></html>")
    private val hop = HttpAnswer(307, listOf("Location" to track), ByteArray(0))
    private val named = Read.Named(ShareLinks.SPOTIFY, "Queen", "Bohemian Rhapsody - Remastered 2011")

    private fun db(block: (Db, File) -> Unit): Unit = TestDb.fresh(tmp.newFolder()).use { database ->
        val cache = tmp.newFolder("cache")
        database.writeBlocking { block(it, cache) }
    }

    private fun ask(db: Db, cache: File, site: FakeTransport, link: String): Read =
        ShareAsk.ask(db, ShareLinks.of(link)!!, Clients(PhoneConfig.DEFAULTS, cache, { site }, pacing), Alerts.NONE,
                     PhoneConfig.DEFAULTS, now)

    @Test fun `a short link read once is answered by the cache alone after`() = db { db, cache ->
        val site = FakeTransport(mapOf("GET $short" to hop, "GET $track" to good))
        assertEquals(named, ask(db, cache, site, short))
        assertEquals(listOf("GET $short", "GET $track"), site.said)
        assertEquals(named, ShareAsk.cached(ShareLinks.of(short)!!, cache))
        assertEquals(named, ask(db, cache, site, short))
        assertEquals(2, site.said.size)  // nothing more sent
    }

    @Test fun `a short link whose track page is cached unreadable is asked for it once more past the cache`() = db { db, cache ->
        val bad = FakeTransport(mapOf("GET $short" to hop, "GET $track" to notice))
        assertEquals(Read.NotRead(ShareLinks.SPOTIFY, "asking Spotify failed (a page that names no song)"),
                     ask(db, cache, bad, short))
        assertEquals(null, ShareAsk.cached(ShareLinks.of(short)!!, cache))  // a link not read whole keeps no hop

        val well = FakeTransport(mapOf("GET $short" to hop, "GET $track" to good))
        assertEquals(named, ask(db, cache, well, short))
        assertEquals(listOf("GET $short", "GET $track"), well.said)  // the hop once, the page past the cache
        assertEquals(named, ShareAsk.cached(ShareLinks.of(short)!!, cache))
    }
}
