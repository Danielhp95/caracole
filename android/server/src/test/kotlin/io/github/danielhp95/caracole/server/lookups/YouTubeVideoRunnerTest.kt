package io.github.danielhp95.caracole.server.lookups

import io.github.danielhp95.caracole.core.config.PhoneConfig
import io.github.danielhp95.caracole.core.db.Database
import io.github.danielhp95.caracole.core.health.Alerts
import io.github.danielhp95.caracole.core.http.HttpAnswer
import io.github.danielhp95.caracole.core.http.Robots
import io.github.danielhp95.caracole.core.http.RobotsClosed
import io.github.danielhp95.caracole.core.library.LibraryStore
import io.github.danielhp95.caracole.core.lookup.Clients
import io.github.danielhp95.caracole.core.lookup.Pacing
import io.github.danielhp95.caracole.core.lookup.SongPages
import io.github.danielhp95.caracole.core.lookup.SongbookPages
import io.github.danielhp95.caracole.core.testing.Corpus
import io.github.danielhp95.caracole.core.testing.FakeTransport
import io.github.danielhp95.caracole.core.testing.Misses
import io.github.danielhp95.caracole.core.testing.TestDb
import io.github.danielhp95.caracole.core.youtube.HostGate
import io.github.danielhp95.caracole.core.youtube.Ran
import io.github.danielhp95.caracole.core.youtube.Thumbs
import io.github.danielhp95.caracole.core.youtube.YouTubeEngine
import io.github.danielhp95.caracole.core.youtube.YtDlpGate
import io.github.danielhp95.caracole.core.youtube.YtDlpProcess
import io.github.danielhp95.caracole.server.PhoneParts
import io.github.danielhp95.caracole.server.jobs.CommandExit
import io.github.danielhp95.caracole.server.jobs.JobContext
import io.github.danielhp95.caracole.server.jobs.JobQueue
import io.github.danielhp95.caracole.server.page.MirrorPageData
import io.github.danielhp95.caracole.server.testing.replays.YouTubeVideoReplay
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.runBlocking
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.jsonObject
import org.junit.After
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import java.io.File
import java.time.Instant
import java.util.Base64
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith
import kotlin.test.assertNotNull
import kotlin.test.assertTrue

/** `caracole youtube --video` on the phone: the computer's command replayed (vectors/youtube/video_cmd.jsonl, area
 * `youtube-video`: YouTubeVideoReplay's KDoc says what is compared), a record that strays told, and what only the
 * phone shows: one yt-dlp run and one image a video within the gate's 30 days, `/sb/` refused by robots, and YouTube
 * switched off by the computer's settings at a sync a refusal in the computer's words. */
class YouTubeVideoRunnerTest {
    @get:Rule val tmp = TemporaryFolder()
    private val scope = CoroutineScope(SupervisorJob())
    private val opened = mutableListOf<Database>()

    @After fun close() {
        scope.cancel()
        opened.forEach { it.close() }
    }

    @Test fun everyReadIsThePythonCommands() {
        val misses = Misses("youtube-video")
        YouTubeVideoReplay.replay(misses)
        misses.assertNone()
        assertEquals(22, YouTubeVideoReplay.cases().size)
    }

    private fun edited(record: JsonObject, path: List<String>, value: JsonElement): JsonObject {
        if (path.size == 1) return JsonObject(record + (path[0] to value))
        return JsonObject(record + (path[0] to edited(record.getValue(path[0]).jsonObject, path.drop(1), value)))
    }

    @Test fun aRecordThatStraysIsTold() {
        val first = YouTubeVideoReplay.cases().first()
        assertEquals(emptyList(), YouTubeVideoReplay.one(first))
        val strays = mapOf(
            "a line" to edited(first, listOf("out", "lines"), JsonArray(listOf(JsonPrimitive("Searched: no")))),
            "the progress" to edited(first, listOf("out", "progress"), JsonArray(emptyList())),
            "a run" to edited(first, listOf("out", "runs"), JsonArray(emptyList())),
            "the image host's ask" to edited(first, listOf("out", "asked"), JsonArray(emptyList())),
            "a kv record" to edited(first, listOf("out", "kv"), JsonObject(emptyMap())),
            "an event" to edited(first, listOf("out", "events"), JsonArray(emptyList())),
            "the thumbnail" to edited(first, listOf("out", "thumb"), JsonPrimitive("0")),
            "the exit" to edited(first, listOf("out", "exit"), JsonPrimitive(2)),
        )
        for ((what, record) in strays) {
            assertTrue(YouTubeVideoReplay.one(record).isNotEmpty(), "a record whose $what strays passed")
        }
    }

    // --- the phone's own ----------------------------------------------------------------------------------------

    private val id = "lzN7Thn3FV4"
    private val now = Instant.parse("2026-11-27T12:00:00Z")
    private val jpeg: ByteArray = Base64.getDecoder().decode(
        Corpus.lines(YouTubeVideoReplay.VECTOR).first { "case" in it }.getValue("kw").jsonObject.getValue("thumb")
            .jsonObject.getValue("base64").let { (it as JsonPrimitive).content })

    private class Lines : JobContext {
        val said = ArrayList<String>()
        override fun stage(name: String, state: String, detail: String) {}
        override fun say(line: String) {
            said += line
        }
        override fun outcome(value: JsonObject) {}
        override val isCancelled = false
    }

    private inner class World(config: (io.github.danielhp95.caracole.core.db.Db) -> PhoneConfig = { PhoneConfig.read(it) }) {
        val dir = tmp.newFolder()
        val database = TestDb.fresh(dir).also { opened += it }
        val state = File(dir, "state").apply { mkdirs() }
        val runs = ArrayList<List<String>>()
        val transport = FakeTransport(mapOf("GET https://i.ytimg.com/vi/$id/hqdefault.jpg" to
                                                HttpAnswer(200, listOf("content-type" to "image/jpeg"), jpeg)))
        val pacing = Pacing(sleep = {}, draws = { low, _ -> low }, wallSeconds = { now.epochSecond.toDouble() },
                            monotonic = { 0.0 }, clock = { now })
        val parts = PhoneParts(database, LibraryStore(File(dir, "library")), state, { database.read(config) },
                               JobQueue(scope), MirrorPageData(null),
                               { Clients(database.read(config), File(state, "cache"), { transport }, pacing) },
                               SongPages.NONE, SongbookPages.NONE, Alerts.NONE, pacing, searchesLacuerda = false)
        val engine = object : YouTubeEngine {
            override fun ready(): String? = null
            override fun process(): YtDlpProcess = object : YtDlpProcess {
                override fun run(argv: List<String>, timeoutS: Double, onLine: (String) -> Unit, waiting: () -> Unit): Ran {
                    runs += argv
                    return Ran(0, """{"_type": "video", "id": "$id", "title": "Somos vikingos veganos", """ +
                        """"channel": "kintanedu", "duration": 222}""" + "\n", "")
                }
            }
            override fun gate(): YtDlpGate = object : YtDlpGate {
                override val proxyArg = "http://test:secret@127.0.0.1:9"
                override fun log(): Map<String, HostGate.HostUse> = emptyMap()
                override fun close() {}
            }
            override val qjs = File("/qjs")
            override val cacheDir = File(state, "cache")
        }

        fun read(link: String): List<String> {
            val lines = Lines()
            runBlocking { YouTubeVideoRunner(parts, engine, routeWhy = { null }).run(listOf("youtube", "--video=$link"), lines) }
            return lines.said
        }
    }

    /** The gate's 30 days: asked again by any link to it, a read video asks neither yt-dlp nor the image host. */
    @Test fun oneYtDlpRunAndOneImageAVideoWithinTheGatesThirtyDays() {
        val w = World()
        val first = w.read("https://www.youtube.com/watch?v=$id&pp=x")
        assertEquals(listOf("Searched: YouTube video $id: Somos vikingos veganos (kintanedu)."), first)
        for (link in listOf(id, "https://youtu.be/$id?si=abc", "https://music.youtube.com/watch?v=$id")) {
            assertEquals(first, w.read(link), link)
        }
        assertEquals(1, w.runs.size)
        assertEquals(listOf("GET https://i.ytimg.com/vi/$id/hqdefault.jpg"), w.transport.said)
        assertNotNull(Thumbs(File(w.state, "cache")).get(id))
    }

    /** i.ytimg.com closes `/sb/` (its storyboards): never asked, whoever asks. */
    @Test fun theImageHostsSbIsRefusedByRobots() {
        assertNotNull(Robots.disallows("https://i.ytimg.com/sb/$id/storyboard3_L0/default.jpg"))
        val w = World()
        w.database.writeBlocking { db ->
            val client = w.parts.clients().named(db, Thumbs.PROVIDER, "youtube-search:video:x")
            assertFailsWith<RobotsClosed> { client.get("https://i.ytimg.com/sb/$id/storyboard3_L0/default.jpg") }
        }
        assertEquals(emptyList(), w.transport.said)
    }

    /** The computer's `[providers.youtube] enabled = false`, taken at a sync (PhoneConfig.take): not read, in the
     * computer's words, nothing asked. */
    @Test fun youtubeSwitchedOffAtASyncIsARefusalInTheComputersWords() {
        val w = World()
        w.database.writeBlocking { db ->
            PhoneConfig.take(db, JsonObject(mapOf("providers" to JsonObject(mapOf(
                "youtube" to JsonObject(mapOf("enabled" to JsonPrimitive(false))))))))
        }
        assertEquals(listOf("Not searched: YouTube is off. Try again later."), w.read(id))
        assertEquals(0, w.runs.size)
        assertEquals(emptyList(), w.transport.said)
    }

    /** A link that names no video exits 2 in the computer's words, asking nothing. */
    @Test fun aLinkThatIsNoVideosExitsTwo() {
        val w = World()
        val e = assertFailsWith<CommandExit> { w.read("https://www.youtube.com/@nickcani") }
        assertEquals(2, e.code)
        assertEquals("--video: not a YouTube video's link: 'https://www.youtube.com/@nickcani'", e.message)
        assertEquals(0, w.runs.size)
    }
}
