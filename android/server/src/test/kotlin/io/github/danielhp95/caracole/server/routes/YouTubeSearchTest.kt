package io.github.danielhp95.caracole.server.routes

import io.github.danielhp95.caracole.core.config.PhoneConfig
import io.github.danielhp95.caracole.core.db.Database
import io.github.danielhp95.caracole.core.health.Alerts
import io.github.danielhp95.caracole.core.health.Health
import io.github.danielhp95.caracole.core.library.LibraryStore
import io.github.danielhp95.caracole.core.lookup.Clients
import io.github.danielhp95.caracole.core.lookup.Pacing
import io.github.danielhp95.caracole.core.lookup.SongPages
import io.github.danielhp95.caracole.core.lookup.SongbookPages
import io.github.danielhp95.caracole.core.index.Stamps
import io.github.danielhp95.caracole.core.testing.RefusingTransport
import io.github.danielhp95.caracole.core.testing.TestDb
import io.github.danielhp95.caracole.server.PhoneParts
import io.github.danielhp95.caracole.server.http.Refused
import io.github.danielhp95.caracole.server.jobs.JobQueue
import io.github.danielhp95.caracole.server.page.MirrorPageData
import io.github.danielhp95.caracole.server.testing.TestApp
import io.github.danielhp95.caracole.server.testing.bytes
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Job
import kotlinx.coroutines.cancel
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import org.junit.After
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import java.io.File
import java.net.URLEncoder
import java.time.Instant
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith

/**
 * YouTube's first video for a search on the phone, where the computer's answers can't show it (vectors/web/
 * youtube_routes.jsonl holds the rest, YouTubeRoutesTest's replay): /api/search's `youtube` and `POST /youtube/search`
 * read one gate, a query once in 30 days and the hour's 10 (the pasted videos' reads among them), none while YouTube
 * cools down, and none sent by itself on a metered network (`off`, "waiting for Wi-Fi"), what was searched this month
 * shown all the same; a search's answer queues nothing (its row fills the request form and sends nothing: library.js's
 * `ytRow`, the computer's bytes), only the post queues the search, once a query while it waits.
 */
class YouTubeSearchTest {
    @get:Rule val tmp = TemporaryFolder()
    private val opened = mutableListOf<Database>()
    private val nowhere = CoroutineScope(Job().apply { cancel() })  // a job queued here waits for ever

    @After fun close() {
        opened.forEach { it.close() }
    }

    private val now = Instant.parse("2026-11-27T12:00:00Z")
    private val q = "Una canción nueva"
    private val key = "cancion-nueva-una"

    private inner class World {
        val dir = tmp.newFolder()
        val database = TestDb.fresh(dir).also { opened += it }
        var metered = false
        val queue = JobQueue(nowhere)
        val parts = PhoneParts(database, LibraryStore(File(dir, "library")), File(dir, "state"), { PhoneConfig.DEFAULTS },
                               queue, MirrorPageData(null),
                               { Clients(PhoneConfig.DEFAULTS, File(dir, "cache"), { RefusingTransport }, Pacing.REAL) },
                               SongPages.NONE, SongbookPages.NONE, Alerts.NONE, Pacing.REAL, searchesLacuerda = false)
        val routes = YouTubeRoutes(parts, null, problem = { null }, metered = { metered }) { now }
        val search = SearchRoutes(database, parts.cards, clock = { now },
                                  youtube = { SearchRoutes.YouTubeAsked(null, routes.heldBack()) })

        fun api(query: String = q): JsonObject {
            val target = "/api/search?q=" + URLEncoder.encode(query, Charsets.UTF_8) + "&box=t"
            val answer = search.routes.first { it.path == "/api/search" }.get!!
                .answer(TestApp.request("GET", target, emptyMap(), ByteArray(0), TestApp.SECRET))
            return Json.parseToJsonElement(answer.bytes.toString(Charsets.UTF_8)).jsonObject
        }

        fun youtube(query: String = q): JsonObject? = api(query)["youtube"]?.takeIf { it !is JsonNull }?.jsonObject

        fun post(query: String = q): Int {
            val route = routes.routes.first { it.path == "/youtube/search" }.post!!
            return route.answer(TestApp.request("POST", "/youtube/search", mapOf("accept" to "application/json"),
                                                ByteArray(0), TestApp.SECRET), mapOf("q" to query)).status
        }

        fun refused(query: String = q): Refused = assertFailsWith<Refused> { post(query) }

        fun searched(video: Boolean) = database.writeBlocking { db ->
            db.kvSet("youtube-search:$key", """{"at": "2026-11-25T09:00:00Z", "query": "$q", "video": """ +
                (if (video) """{"id": "lzN7Thn3FV4", "title": "Una canción nueva", "channel": "Nueva Banda", """ +
                    """"duration": 200.0, "url": "https://www.youtube.com/watch?v=lzN7Thn3FV4"}""" else "null") +
                """, "thumb": false}""")
        }
    }

    @Test fun aQueryWithNoSheetIsAutoAndItsPostQueuesOneJobOnce() {
        val w = World()
        assertEquals("auto", w.youtube()!!["state"]!!.jsonPrimitive.content)
        assertEquals(0, w.queue.snapshot().size, "a search's answer queues nothing")
        assertEquals(202, w.post())
        assertEquals(202, w.post("  una   CANCIÓN nueva "), "asked again while it waits: that job")
        val job = w.queue.snapshot().single()
        assertEquals("youtube-search:$key", job.key)
        assertEquals(listOf("youtube", "--search=$q", "--progress"), job.steps.single().args)
    }

    @Test fun onAMeteredNetworkNoneIsSentByItselfAndWhatWasSearchedIsShown() {
        val w = World()
        w.metered = true
        val off = w.youtube()!!
        assertEquals("off", off["state"]!!.jsonPrimitive.content)
        assertEquals("waiting for Wi-Fi", off["why"]!!.jsonPrimitive.content)
        val e = w.refused()
        assertEquals(429, e.status)
        assertEquals("Not now: waiting for Wi-Fi.", e.message)
        assertEquals(0, w.queue.snapshot().size)
        w.searched(video = true)
        val found = w.youtube()!!
        assertEquals("found", found["state"]!!.jsonPrimitive.content)
        assertEquals("https://www.youtube.com/watch?v=lzN7Thn3FV4",
                     found["video"]!!.jsonObject["url"]!!.jsonPrimitive.content)
        w.metered = false
        assertEquals("found", w.youtube()!!["state"]!!.jsonPrimitive.content)
    }

    @Test fun aQueryOnceInThirtyDaysAndTheHoursTenSharedWithThePastedVideos() {
        val w = World()
        w.database.writeBlocking { db ->
            for (n in 0 until 10) {
                val run = if (n < 5) "youtube-search:2026-11-27T11:0$n:00Z" else "youtube-search:video:x:$n"
                db.execute("INSERT INTO events (run, at, provider, url, status, decision) VALUES (?, ?, 'youtube', 'u', " +
                               "NULL, 'ok')", run, Stamps.of(now.minusSeconds(600L + n)))
            }
        }
        val spent = w.youtube()!!
        assertEquals("spent", spent["state"]!!.jsonPrimitive.content)
        assertEquals("no more YouTube asks this hour (10 spent)", spent["why"]!!.jsonPrimitive.content)
        assertEquals(429, w.refused().status)
        w.searched(video = false)
        assertEquals("none", w.youtube()!!["state"]!!.jsonPrimitive.content, "searched this month: no more asked")
        assertEquals("Searched already this month.", w.refused().message)
        assertEquals(0, w.queue.snapshot().size)
    }

    @Test fun noneWhileYouTubeCoolsDown() {
        val w = World()
        w.database.writeBlocking { db -> Health.recordBlock(db, "youtube", now.minusSeconds(3600), "blocked") }
        assertEquals("spent", w.youtube()!!["state"]!!.jsonPrimitive.content)
        assertEquals("Not now: YouTube turned us back.", w.refused().message)
    }

    /** The row's answer: the video's address the form's YouTube field takes, and the names its Make sheet fills the
     * form with, read with the video's title and channel; reading it sends nothing. */
    @Test fun theRowsAnswerCarriesWhatTheFormTakesAndSendsNothing() {
        val w = World()
        w.searched(video = true)
        val answer = w.api()
        assertEquals("Nueva Banda", answer["names"]!!.jsonObject["artist"]!!.jsonPrimitive.content)
        assertEquals("https://www.youtube.com/watch?v=lzN7Thn3FV4",
                     answer["youtube"]!!.jsonObject["video"]!!.jsonObject["url"]!!.jsonPrimitive.content)
        assertEquals(0, w.queue.snapshot().size)
    }
}
