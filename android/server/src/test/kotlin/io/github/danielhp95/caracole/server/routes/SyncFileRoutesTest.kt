package io.github.danielhp95.caracole.server.routes

import io.github.danielhp95.caracole.core.json.PyJson
import io.github.danielhp95.caracole.core.library.LibraryStore
import io.github.danielhp95.caracole.core.sync.SyncEngine
import io.github.danielhp95.caracole.core.sync.file.SyncFiles
import io.github.danielhp95.caracole.core.testing.Corpus
import io.github.danielhp95.caracole.core.testing.Fixtures
import io.github.danielhp95.caracole.core.testing.Misses
import io.github.danielhp95.caracole.mirror.LayerPolicy
import io.github.danielhp95.caracole.mirror.Looked
import io.github.danielhp95.caracole.mirror.Mirror
import io.github.danielhp95.caracole.mirror.pageFor
import io.github.danielhp95.caracole.server.files.PhoneGate
import io.github.danielhp95.caracole.server.http.Response
import io.github.danielhp95.caracole.server.jobs.Job
import io.github.danielhp95.caracole.server.jobs.JobQueue
import io.github.danielhp95.caracole.server.routes.sync.Exports
import io.github.danielhp95.caracole.server.routes.sync.Imports
import io.github.danielhp95.caracole.server.testing.TestApp
import io.github.danielhp95.caracole.server.testing.bytes
import io.github.danielhp95.caracole.server.testing.header
import io.github.danielhp95.caracole.server.testing.json
import io.github.danielhp95.caracole.server.testing.replays.WebReplay
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.withTimeout
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.int
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import org.junit.After
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import java.io.File
import java.time.Instant
import java.time.ZoneOffset
import java.util.concurrent.atomic.AtomicLong
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertIs
import kotlin.test.assertTrue

/** The phone's Export and Import a file (SyncFileRoutes), and Sync on a file's comparison (SyncRoutes' apply handing
 * it over): what caracole serve's web/sync_file_routes.py answers, and an import that runs, its pages kept as a layer
 * of the mirror. */
class SyncFileRoutesTest {
    @get:Rule val tmp = TemporaryFolder()

    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Default)
    private val clock = AtomicLong(System.currentTimeMillis())

    @After fun stop() = scope.cancel()

    /** A phone over the sync corpus's [fixture] (its id `0f1e2d3c4b5a6978`), its routes and its queue running, a
     * mirror its import keeps a file's pages in. */
    private inner class Phone(fixture: String = "plain") : AutoCloseable {
        val dir: File = tmp.newFolder()
        val state = File(dir, "state")
        val mirror = Mirror(File(dir, "mirror"))
        val imports = Imports(state, clock::get)
        val exports = Exports(File(state, "cache"), clock::get)
        val queue = JobQueue(scope)
        lateinit var engine: SyncEngine
        val app = TestApp(dir, mirror = mirror, modules = { database ->
            engine = SyncEngine(database, LibraryStore(File(dir, "library")), state, client = { error("no computer") },
                                mirrorRefresh = null,
                                pagesFromFile = SyncFileRoutes.pagesFromFile(mirror, File(dir, "library"), PhoneGate(database)))
            val settings = object : SyncSettings {
                override val address: String? = null
                override fun remember(address: String) = Unit
            }
            val sync = SyncRoutes(engine, queue, settings, database, afterSync = {})
            val files = SyncFileRoutes(engine, queue, database, File(dir, "library"), imports, exports, pages = { null },
                                       afterSync = {}, name = { "lib" }, now = { Instant.parse("2026-11-03T22:00:00Z") },
                                       zone = { ZoneOffset.UTC })
            sync.files = files
            listOf(sync, files)
        })

        init {
            app.database.writeBlocking { db ->
                Fixtures.load(db, "sync/fixtures/$fixture.jsonl", app.libraryDir)
                db.kvSet("sync:id", "0f1e2d3c4b5a6978")
            }
        }

        private val own = mapOf("sec-fetch-site" to "same-origin", "accept" to "application/json",
                                TestApp.TOKEN_HEADER to app.csrf)

        fun get(target: String): Response = app.handle(app.request("GET", target, own))

        fun json(target: String, doc: JsonElement): Response = app.handle(app.request(
            "POST", target, own + ("content-type" to "application/json"), PyJson.dumps(doc).toByteArray()))

        fun part(id: String, at: Int, data: ByteArray): Response = app.handle(app.request(
            "POST", "/sync/import/part?import=$id&at=$at", own + ("content-type" to "application/octet-stream"), data))

        fun opened(size: Int): String = json("/sync/import/open", JsonObject(mapOf(
            "size" to JsonPrimitive(size), "name" to JsonPrimitive("Desk-03-11-26.caracole"),
        ))).json.jsonObject.getValue("import").jsonPrimitive.content

        fun send(data: ByteArray): String {
            val id = opened(data.size)
            for (at in data.indices step 4096) assertEquals(200, part(id, at, data.copyOfRange(at, minOf(at + 4096, data.size))).status)
            return id
        }

        fun staged(): List<String> = File(state, "peer").listFiles().orEmpty().map { it.name }.filter { it.startsWith("import-") }

        override fun close() = app.close()
    }

    private fun full(): ByteArray = Corpus.open("sync/files/full.caracole")!!.use { it.readBytes() }

    @Test
    fun `every record of sync file routes jsonl replays`() =
        Misses("web/sync_file_routes.jsonl").also { WebReplay.syncFileRoutes(it) }.assertNone()

    @Test
    fun `an upload cut short is never compared, and is swept an hour after`() = Phone().use { phone ->
        val data = full()
        val id = phone.opened(data.size)
        assertEquals(200, phone.part(id, 0, data.copyOfRange(0, 4096)).status)
        val compared = phone.app.postScript("/sync/import/compare", listOf("import" to id))
        assertEquals(400 to Imports.NOT_WHOLE, compared.status to compared.json.jsonObject.getValue("error").jsonPrimitive.content)
        assertEquals(listOf("import-$id"), phone.staged(), "kept for the rest")

        clock.addAndGet(Imports.EXPIRES + 1)
        phone.opened(10)  // opening another sweeps what an hour has left first
        assertFalse("import-$id" in phone.staged(), "swept an hour after its last part")
        val gone = phone.app.postScript("/sync/import/compare", listOf("import" to id))
        assertEquals(404 to SyncFileRoutes.GONE_FILE, gone.status to gone.json.jsonObject.getValue("error").jsonPrimitive.content)
    }

    @Test
    fun `an export is sent once and leaves nothing in the cache`() = Phone("rich").use { phone ->
        val made = phone.json("/sync/export", JsonObject(mapOf("parts" to kotlinx.serialization.json.JsonArray(listOf(JsonPrimitive("library"))))))
        assertEquals(200, made.status)
        val id = made.json.jsonObject.getValue("export").jsonPrimitive.content
        val folder = File(phone.state, "cache/peer")
        assertEquals(listOf("export-$id.caracole"), folder.list()!!.toList())

        val sent = phone.get("/api/sync/export?export=$id")
        assertEquals(200, sent.status)
        assertEquals(SyncFiles.MEDIA_TYPE, sent.header("Content-Type"))
        val file = tmp.newFile("sent.caracole").apply { writeBytes(sent.bytes) }
        assertEquals("0f1e2d3c4b5a6978", SyncFiles.read(file).id, "the file whole, read once it was opened")
        assertEquals(emptyList(), folder.list()!!.toList(), "nothing left in the cache once it is opened")
        assertEquals(404, phone.get("/api/sync/export?export=$id").status, "sent once")
    }

    @Test
    fun `a file's import takes what it gives, keeps its pages as a layer, and leaves no staging behind`() = Phone().use { phone ->
        val id = phone.send(full())
        val compared = phone.app.postScript("/sync/import/compare", listOf("import" to id))
        assertEquals(200, compared.status)
        val answer = compared.json.jsonObject
        assertEquals(JsonPrimitive("file"), answer.getValue("peer").jsonObject["kind"])
        val queued = phone.app.postScript("/sync/apply", listOf("comparison" to answer.getValue("comparison").jsonPrimitive.content,
                                                                 "prefer" to "", "choices" to ""))
        assertEquals(200, queued.status)
        val jobId = queued.json.jsonObject.getValue("job").jsonObject.getValue("id").jsonPrimitive.int
        val job = runBlocking { withTimeout(60_000) { phone.queue.await(jobId) } }
        assertEquals(Job.DONE, job.state, job.output.joinToString("\n"))
        assertEquals("import:$id", job.spec.key)
        assertEquals(SyncEngine.FILE_STAGES.map { it.first }, job.stages.map { it.name })
        assertEquals("done", job.stages.single { it.name == SyncEngine.MIRROR }.state, job.stages.toString())
        assertEquals(emptyList(), phone.staged(), "its staging deleted once the job is over")

        val layer = phone.mirror.layers().single()
        assertEquals("a1b2c3d4e5f60718", layer.id, "the layer of the file's caracole")
        val sheet = assertIs<Looked.Page>(phone.mirror.pageFor("Radiohead/Creep/sheet.html", PhoneGate(phone.app.database)))
        assertEquals("text/html; charset=utf-8", sheet.entry.type)
        assertEquals(LayerPolicy.NOTHING, sheet.entry.headers["Content-Security-Policy"],
                     "the file's page named no sandbox: served in one that runs nothing")
        val served = phone.app.get("/Radiohead/Creep/sheet.html")
        assertEquals(200, served.status)
        assertEquals(LayerPolicy.NOTHING, served.header("Content-Security-Policy"))
        assertTrue(phone.app.database.read { db -> db.one("SELECT COUNT(*) FROM songs WHERE key = 'radiohead/creep'") { it.long(0) } } == 1L)
    }
}
