package io.github.danielhp95.caracole.server.lookups

import io.github.danielhp95.caracole.core.config.PhoneConfig
import io.github.danielhp95.caracole.core.db.Database
import io.github.danielhp95.caracole.core.health.Alerts
import io.github.danielhp95.caracole.core.http.HttpAnswer
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
import io.github.danielhp95.caracole.core.youtube.YouTubeData
import io.github.danielhp95.caracole.core.youtube.YouTubeEngine
import io.github.danielhp95.caracole.core.youtube.YtDlpGate
import io.github.danielhp95.caracole.core.youtube.YtDlpProcess
import io.github.danielhp95.caracole.server.PhoneParts
import io.github.danielhp95.caracole.server.jobs.CommandExit
import io.github.danielhp95.caracole.server.jobs.CommandRunner
import io.github.danielhp95.caracole.server.jobs.JobContext
import io.github.danielhp95.caracole.server.jobs.JobQueue
import io.github.danielhp95.caracole.server.page.MirrorPageData
import io.github.danielhp95.caracole.server.testing.replays.YouTubeSearchReplay
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
import kotlin.test.assertNull
import kotlin.test.assertTrue

/** `caracole youtube --search` on the phone: the computer's command replayed (vectors/youtube/search_cmd.jsonl, area
 * `youtube-search`: YouTubeSearchReplay's KDoc says what is compared), a record that strays told, and what only the
 * phone shows: a query searched once in 30 days, the hour's 10, none sent on a metered network (the gate's `off`, and
 * a network that became metered before the run held back), the phone's own errors counted against nothing, and
 * `--search` with `--video` refused. */
class YouTubeSearchRunnerTest {
    @get:Rule val tmp = TemporaryFolder()
    private val scope = CoroutineScope(SupervisorJob())
    private val opened = mutableListOf<Database>()

    @After fun close() {
        scope.cancel()
        opened.forEach { it.close() }
    }

    @Test fun everySearchIsThePythonCommands() {
        val misses = Misses("youtube-search")
        YouTubeSearchReplay.replay(misses)
        misses.assertNone()
        assertEquals(25, YouTubeSearchReplay.cases().size)
    }

    private fun edited(record: JsonObject, path: List<String>, value: JsonElement): JsonObject {
        if (path.size == 1) return JsonObject(record + (path[0] to value))
        return JsonObject(record + (path[0] to edited(record.getValue(path[0]).jsonObject, path.drop(1), value)))
    }

    @Test fun aRecordThatStraysIsTold() {
        val first = YouTubeSearchReplay.cases().first()
        assertEquals(emptyList(), YouTubeSearchReplay.one(first))
        val strays = mapOf(
            "a line" to edited(first, listOf("out", "lines"), JsonArray(listOf(JsonPrimitive("Searched: no")))),
            "the progress" to edited(first, listOf("out", "progress"), JsonArray(emptyList())),
            "a run" to edited(first, listOf("out", "runs"), JsonArray(emptyList())),
            "a kv record" to edited(first, listOf("out", "kv"), JsonObject(emptyMap())),
            "an event" to edited(first, listOf("out", "events"), JsonArray(emptyList())),
            "the thumbnail" to edited(first, listOf("out", "thumb"), JsonPrimitive("0")),
        )
        for ((what, record) in strays) {
            assertTrue(YouTubeSearchReplay.one(record).isNotEmpty(), "a record whose $what strays passed")
        }
    }

    // --- the phone's own ----------------------------------------------------------------------------------------

    private val id = "dQw4w9WgXcQ"
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

    private inner class World {
        val dir = tmp.newFolder()
        val database = TestDb.fresh(dir).also { opened += it }
        val state = File(dir, "state").apply { mkdirs() }
        val runs = ArrayList<List<String>>()
        var metered = false
        var answer: () -> Ran = {
            Ran(0, """{"_type": "playlist", "entries": [{"_type": "url", "id": "$id", "title": "Radiohead - Creep", """ +
                """"channel": "Radiohead", "duration": 239, "url": "https://www.youtube.com/watch?v=$id"}]}""" + "\n", "")
        }
        val transport = FakeTransport(mapOf("GET https://i.ytimg.com/vi/$id/hqdefault.jpg" to
                                                HttpAnswer(200, listOf("content-type" to "image/jpeg"), jpeg)))
        val pacing = Pacing(sleep = {}, draws = { low, _ -> low }, wallSeconds = { now.epochSecond.toDouble() },
                            monotonic = { 0.0 }, clock = { now })
        val parts = PhoneParts(database, LibraryStore(File(dir, "library")), state, { database.read { PhoneConfig.read(it) } },
                               JobQueue(scope), MirrorPageData(null),
                               { Clients(database.read { PhoneConfig.read(it) }, File(state, "cache"), { transport }, pacing) },
                               SongPages.NONE, SongbookPages.NONE, Alerts.NONE, pacing, searchesLacuerda = false)
        val engine = object : YouTubeEngine {
            override fun ready(): String? = null
            override fun process(): YtDlpProcess = object : YtDlpProcess {
                override fun run(argv: List<String>, timeoutS: Double, onLine: (String) -> Unit, waiting: () -> Unit): Ran {
                    runs += argv
                    return answer()
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
        val runner = YouTubeSearchRunner(parts, engine, routeWhy = { null }, metered = { metered })

        fun search(query: String, with: CommandRunner = runner, args: List<String> = listOf("youtube", "--search=$query")):
            List<String> {
            val lines = Lines()
            runBlocking { with.run(args, lines) }
            return lines.said
        }

        fun kv(key: String): String? = database.read { it.kvGet(key) }
    }

    private val searched = "Searched: YouTube's first video for “Radiohead Creep”: Radiohead - Creep (Radiohead), " +
        "https://www.youtube.com/watch?v=$id."

    /** A query once in 30 days, under any spelling of its words: one yt-dlp run and one image. */
    @Test fun aQueryIsSearchedOnceInThirtyDays() {
        val w = World()
        assertEquals(listOf(searched), w.search("Radiohead Creep"))
        // what it found then, said in the query as typed now
        assertEquals(listOf(searched.replace("“Radiohead Creep”", "“radiohead CREEP”")), w.search("  radiohead   CREEP "))
        assertEquals(1, w.runs.size)
        // Byoutube-3: the run's target is the suggestion's own count (youtube.json's search.results), one of the
        // counts the :youtube service's glue lets through (GlueRefusalTest), never a literal of the runner's.
        val data = YouTubeData.read()
        assertEquals(data.searchTarget("Radiohead Creep", data.suggestResults), w.runs.single().last())
        assertTrue(data.suggestResults in data.searchCounts)
        assertEquals(listOf("GET https://i.ytimg.com/vi/$id/hqdefault.jpg"), w.transport.said)
        assertNotNull(w.kv("youtube-search:creep-radiohead"))
    }

    /** The hour's 10 runs named `youtube-search:` (a pasted video's read among them): the eleventh not searched. */
    @Test fun theHoursTenAreSharedWithThePastedVideosReads() {
        val w = World()
        w.database.writeBlocking { db ->
            for (n in 0 until 10) {
                val run = if (n % 2 == 0) "youtube-search:2026-11-27T11:0$n:00Z" else "youtube-search:video:x:$n"
                db.execute("INSERT INTO events (run, at, provider, url, status, decision) VALUES (?, ?, 'youtube', 'u', NULL, 'ok')",
                           run, "2026-11-27T11:5$n:00Z")
            }
        }
        assertEquals(listOf("Not searched: no more YouTube asks this hour (10 spent). Try again later."),
                     w.search("Radiohead Creep"))
        assertEquals(0, w.runs.size)
    }

    /** On a metered network none goes, in the design's words, nothing recorded against the query; what was searched
     * this month is said all the same. */
    @Test fun noneOnAMeteredNetwork() {
        val w = World()
        w.metered = true
        assertEquals(listOf("Not searched: waiting for Wi-Fi. Try again later."), w.search("Radiohead Creep"))
        assertEquals(0, w.runs.size)
        assertNull(w.kv("youtube-search:creep-radiohead"))
        assertNull(w.kv("youtube-search:failed"))
        w.metered = false
        w.search("Radiohead Creep")
        w.metered = true
        assertEquals(listOf(searched), w.search("Radiohead Creep"))
        assertEquals(1, w.runs.size)
    }

    /** A network that became metered between the gate and the run: the run held back (the runner's `beforeRun`), said,
     * counted against neither the query nor the hour. */
    @Test fun aNetworkThatBecameMeteredBeforeTheRunHoldsItBack() {
        val w = World()
        var asked = 0
        val runner = YouTubeSearchRunner(w.parts, w.engine, routeWhy = { null }, metered = { asked++ > 0 })
        assertEquals(listOf("Not searched: waiting for Wi-Fi."), w.search("Radiohead Creep", runner))
        assertEquals(0, w.runs.size)
        assertNull(w.kv("youtube-search:failed"))
        assertNull(w.kv("youtube-search:creep-radiohead"))
        assertEquals(0L, w.database.read { db -> db.one("SELECT COUNT(*) FROM events") { it.long(0) } })
    }

    /** yt-dlp out of date and a run never started: said, nothing remembered against the query or the hour. */
    @Test fun thePhonesOwnErrorsAreCountedAgainstNothing() {
        for (set in listOf<(World) -> Unit>(
            { w -> w.answer = { throw YtDlpProcess.NotStarted("another run is going in the app") } },
            { w -> w.answer = { Ran(1, "", "ERROR: [youtube] $id: Unable to extract yt initial data\n") } },
        )) {
            val w = World()
            set(w)
            val lines = w.search("Radiohead Creep")
            assertTrue(lines.single().startsWith("Not searched: "), "$lines")
            assertNull(w.kv("youtube-search:failed"))
            assertNull(w.kv("youtube-search:creep-radiohead"))
        }
    }

    /** `--search` and `--video` go alone (exit 2, as the computer's typer says it); the phone's own reason it makes no
     * sheet from a video is said with nothing asked. */
    @Test fun searchAndVideoGoAloneAndThePhonesReasonAsksNothing() {
        val w = World()
        val runners = YouTubeRunners(w.runner, w.runner, w.runner)
        val e = assertFailsWith<CommandExit> {
            w.search("x", runners, listOf("youtube", "--search=x", "--video=$id"))
        }
        assertEquals(2, e.code)
        val off = YouTubeSearchRunner(w.parts, w.engine, routeWhy = { "this phone's caracole has no yt-dlp" })
        assertEquals(listOf("Not searched: no YouTube sheets here (this phone's caracole has no yt-dlp)."),
                     w.search("Radiohead Creep", off))
        assertEquals(0, w.runs.size)
    }
}
