package io.github.danielhp95.caracole.core.share

import io.github.danielhp95.caracole.core.config.PhoneConfig
import io.github.danielhp95.caracole.core.db.Db
import io.github.danielhp95.caracole.core.health.Alerts
import io.github.danielhp95.caracole.core.health.Health
import io.github.danielhp95.caracole.core.http.Draws
import io.github.danielhp95.caracole.core.http.HttpAnswer
import io.github.danielhp95.caracole.core.lookup.Clients
import io.github.danielhp95.caracole.core.lookup.Pace
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
import kotlin.test.assertIs
import kotlin.test.assertNotNull
import kotlin.test.assertNull
import kotlin.test.assertTrue

/**
 * A shared link's service asked once (ShareAsk), as a lookup asks a site, over a fake site behind the phone's real
 * PoliteClient (never the network): caracole's user agent, the lookup pace after this side's last request, the
 * requests one share needs and no more, the hour's `lookup_per_hour`, every answer cached forever, a block cooling
 * the service down and alerting once, an error no miss, and a service turned off asked nothing.
 */
class ShareAskTest {
    @get:Rule val tmp = TemporaryFolder()

    private val now: Instant = Instant.parse("2026-11-10T18:00:00Z")
    private val slept = ArrayList<Double>()
    private val pacing = Pacing(sleep = { slept += it }, draws = Draws { a, _ -> a }, wallSeconds = { now.epochSecond.toDouble() },
                                monotonic = { 0.0 }, clock = { now })

    private val track = "https://open.spotify.com/track/4u7EnebtmKWzUH433cf5Qv"
    private val link = "$track?si=0f3c1c4d5e6f4a7b"
    private val short = "https://spotify.link/j7xk2xnhzDb"
    private val page = HttpAnswer(200, listOf("content-type" to "text/html; charset=utf-8"), Corpus.fixture("spotify/track.html"))

    private class Heard : Alerts {
        val blocks = ArrayList<String>()
        override fun blocked(provider: String, until: Instant?, message: String) {
            blocks += provider
        }

        override fun failed(title: String, line: String) {}
    }

    private fun db(block: (Db, File) -> Unit): Unit = TestDb.fresh(tmp.newFolder()).use { database ->
        val cache = tmp.newFolder("cache")
        database.writeBlocking { block(it, cache) }
    }

    private fun ask(db: Db, cache: File, site: FakeTransport, link: String = this.link, alerts: Alerts = Alerts.NONE,
                    cfg: PhoneConfig = PhoneConfig.DEFAULTS): Read =
        ShareAsk.ask(db, ShareLinks.of(link)!!, Clients(cfg, cache, { site }, pacing), alerts, cfg, now)

    private fun events(db: Db): List<List<String?>> =
        db.query("SELECT run, provider, url, status, decision FROM events ORDER BY id") { r ->
            listOf(r.text(0), r.text(1), r.text(2), r.long(3)?.toString(), r.text(4))
        }

    @Test fun `a song's link is one request with caracole's user agent, logged as a lookup's, and cached forever`() = db { db, cache ->
        val site = FakeTransport(mapOf("GET $track" to page))
        assertEquals(Read.Named(ShareLinks.SPOTIFY, "Queen", "Bohemian Rhapsody - Remastered 2011"), ask(db, cache, site))
        assertEquals(listOf("GET $track"), site.said)
        assertEquals(PhoneConfig.DEFAULTS.userAgent, site.requests.single().headers.first { it.first == "User-Agent" }.second)
        assertEquals(listOf(listOf("lookup:share:2026-11-10T18:00:00Z", "spotify", track, "200", "ok")), events(db))
        assertEquals("1794333600.000", db.kvGet(Pace.LAST_SENT + "spotify"))
        assertEquals(now, Health.state(db, "spotify").lastOk)
        // Shared again: the cache's answer, read with no request and no write; and asked again, still none sent.
        assertEquals(Read.Named(ShareLinks.SPOTIFY, "Queen", "Bohemian Rhapsody - Remastered 2011"),
                     ShareAsk.cached(ShareLinks.of(link)!!, cache))
        ask(db, cache, site)
        assertEquals(1, site.said.size)
        assertNull(ShareAsk.cached(ShareLinks.of("https://open.spotify.com/track/3RkrwOau4TphkM84H6ELPi")!!, cache))
    }

    @Test fun `its first request waits the lookup pace after this side's last one to the service`() = db { db, cache ->
        db.kvSet(Pace.LAST_SENT + "spotify", "1794333599.900")  // a tenth of a second before now
        ask(db, cache, FakeTransport(mapOf("GET $track" to page)))
        assertEquals(1, slept.size)
        assertEquals(PhoneConfig.DEFAULTS.provider("spotify").lookupDelay.first - 0.1, slept.single(), 1e-6)
    }

    @Test fun `a short link costs its one hop more, never another`() = db { db, cache ->
        val site = FakeTransport(mapOf(
            "GET $short" to HttpAnswer(307, listOf("Location" to "$track?si=a1&_branch_match_id=9"), ByteArray(0)),
            "GET $track" to page,
        ))
        assertEquals(Read.Named(ShareLinks.SPOTIFY, "Queen", "Bohemian Rhapsody - Remastered 2011"), ask(db, cache, site, short))
        assertEquals(listOf("GET $short", "GET $track"), site.said)
        assertEquals(listOf("ok", "ok"), events(db).map { it[4] })
        // A song's link whose page redirects once more has spent its one request: said, nothing more sent.
        val moved = "https://open.spotify.com/track/3RkrwOau4TphkM84H6ELPi"
        val again = FakeTransport(mapOf("GET $moved" to HttpAnswer(301, listOf("Location" to track), ByteArray(0))))
        assertEquals(Read.NotRead(ShareLinks.SPOTIFY, "the one request to Spotify a share of this link may send is spent"),
                     ask(db, cache, again, moved))
        assertEquals(listOf("GET $moved"), again.said)
    }

    @Test fun `the hour's lookup requests spent, nothing is sent and the page says so`() = db { db, cache ->
        val hour = PhoneConfig.DEFAULTS.provider("spotify").lookupPerHour
        repeat(hour) {
            db.execute("INSERT INTO events (run, at, provider, url, status, decision) VALUES (?, ?, ?, ?, ?, ?)",
                       "lookup:2026-11-10T17:30:00Z", "2026-11-10T17:30:00Z", "spotify", track, 200, "ok")
        }
        val site = FakeTransport(emptyMap())
        assertEquals(Read.NotRead(ShareLinks.SPOTIFY, "this hour's $hour requests to Spotify are spent"),
                     ask(db, cache, site))
        assertEquals(emptyList(), site.said)
    }

    @Test fun `a block cools the service down, alerts once, and the next share asks nothing`() = db { db, cache ->
        val alerts = Heard()
        val site = FakeTransport(mapOf("GET $track" to HttpAnswer(429, emptyList(), "Too Many Requests".toByteArray())))
        val read = ask(db, cache, site, alerts = alerts)
        assertIs<Read.NotRead>(read)
        assertEquals("Spotify blocked caracole (HTTP 429), and caracole asks it nothing more until 2026-11-11 20:00 UTC", read.why)
        assertEquals(Instant.parse("2026-11-11T20:00:00Z"), Health.state(db, "spotify").cooldownUntil)
        assertEquals(listOf("spotify"), alerts.blocks)
        val later = ask(db, cache, site, alerts = alerts)
        assertEquals(Read.NotRead(ShareLinks.SPOTIFY, "Spotify blocked caracole earlier, and caracole asks it nothing until " +
                                      "2026-11-11 20:00 UTC"), later)
        assertEquals(1, site.said.size)
        assertEquals(listOf("spotify"), alerts.blocks)
        // Another service is no one's cooldown.
        assertNull(Health.state(db, "tidal").cooldownUntil)
    }

    @Test fun `an error or an answer that won't parse is said, never read as a link that names no song`() = db { db, cache ->
        val site = FakeTransport(mapOf(
            "GET $track" to HttpAnswer(500, emptyList(), "boom".toByteArray()),
            "GET https://itunes.apple.com/lookup?id=1440833334&country=zz" to
                HttpAnswer(400, emptyList(), Corpus.fixture("itunes/lookup-bad-country.json")),
            "GET https://tidal.com/track/196435445" to HttpAnswer(200, emptyList(), "<html><title>TIDAL</title></html>".toByteArray()),
        ))
        assertEquals(Read.NotRead(ShareLinks.SPOTIFY, "asking Spotify failed (HTTP 500)"), ask(db, cache, site))
        assertTrue("500" in Health.state(db, "spotify").lastError.orEmpty())
        assertNull(Health.state(db, "spotify").cooldownUntil, "an error is no block")
        assertEquals(Read.NotRead(ShareLinks.APPLE, "asking Apple Music failed (HTTP 400)"),
                     ask(db, cache, site, "https://music.apple.com/zz/album/love-me-do/1440833098?i=1440833334"))
        assertEquals(Read.NotRead(ShareLinks.TIDAL, "asking TIDAL failed (a page that names no song)"),
                     ask(db, cache, site, "https://tidal.com/track/196435445/u"))
        // The page that wouldn't parse was cached (a 200): read from the cache alone it is no answer, so the next share
        // asks again, past the cache.
        assertNull(ShareAsk.cached(ShareLinks.of("https://tidal.com/track/196435445")!!, cache))
    }

    @Test fun `a service turned off is asked nothing, its cache read neither`() = db { db, cache ->
        val on = FakeTransport(mapOf("GET $track" to page))
        ask(db, cache, on)
        val doc = """{"providers": {"spotify": {"enabled": false}}}"""
        db.kvSet(PhoneConfig.SETTINGS_KV, doc)
        val cfg = PhoneConfig.read(db)
        val off = ShareAsk.off(ShareLinks.of(link)!!, cfg)
        assertNotNull(off)
        assertEquals("reading Spotify's links is off ([providers.spotify] enabled = false in the computer's caracole.toml, " +
                         "which the phone took at its last sync)", (off as Read.NotRead).why)
        val site = FakeTransport(emptyMap())
        assertEquals(off, ask(db, cache, site, cfg = cfg))
        assertEquals(emptyList(), site.said)
        assertNotNull(ShareAsk.off(ShareLinks.of("https://youtu.be/fJ9rUzIMcZQ")!!, PhoneConfig.over(PhoneConfig.DEFAULTS,
            kotlinx.serialization.json.Json.parseToJsonElement("""{"providers": {"youtube-oembed": {"enabled": false}}}""")
                as kotlinx.serialization.json.JsonObject)))
    }

    @Test fun `an album's link sends nothing and logs nothing`() = db { db, cache ->
        val site = FakeTransport(emptyMap())
        assertEquals(Read.NoSong(ShareLinks.SPOTIFY, "a link to an album"),
                     ask(db, cache, site, "https://open.spotify.com/album/1GbtB4zTqAsyfZEsm1RZfx"))
        assertEquals(emptyList(), site.said)
        assertEquals(emptyList(), events(db))
    }
}
