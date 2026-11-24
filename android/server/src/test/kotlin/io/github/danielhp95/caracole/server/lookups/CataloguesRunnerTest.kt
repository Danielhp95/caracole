package io.github.danielhp95.caracole.server.lookups

import androidx.sqlite.driver.bundled.BundledSQLiteDriver
import androidx.sqlite.execSQL
import com.sun.net.httpserver.HttpServer
import io.github.danielhp95.caracole.core.catalogues.CatalogueSource
import io.github.danielhp95.caracole.core.catalogues.Catalogues
import io.github.danielhp95.caracole.core.catalogues.Limited
import io.github.danielhp95.caracole.core.db.Database
import io.github.danielhp95.caracole.core.index.Stamps
import io.github.danielhp95.caracole.core.json.PyJson
import io.github.danielhp95.caracole.core.testing.Fixtures
import io.github.danielhp95.caracole.core.testing.TestDb
import io.github.danielhp95.caracole.mirror.Http
import io.github.danielhp95.caracole.server.PhoneParts
import io.github.danielhp95.caracole.server.jobs.CommandRunner
import io.github.danielhp95.caracole.server.jobs.Commands
import io.github.danielhp95.caracole.server.jobs.Job
import io.github.danielhp95.caracole.server.jobs.JobContext
import io.github.danielhp95.caracole.server.jobs.JobQueue
import io.github.danielhp95.caracole.server.jobs.JobSpec
import io.github.danielhp95.caracole.server.jobs.JobViews
import io.github.danielhp95.caracole.server.jobs.PhoneKinds
import io.github.danielhp95.caracole.server.testing.TestParts
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.withTimeout
import kotlinx.serialization.json.JsonObject
import org.junit.After
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import java.io.ByteArrayOutputStream
import java.io.File
import java.net.InetAddress
import java.net.InetSocketAddress
import java.net.URI
import java.security.MessageDigest
import java.time.Instant
import java.util.concurrent.ConcurrentHashMap
import java.util.concurrent.CopyOnWriteArrayList
import java.util.concurrent.Executors
import java.util.zip.GZIPOutputStream
import kotlin.random.Random
import kotlin.test.assertEquals
import kotlin.test.assertNull
import kotlin.test.assertTrue

/** `caracole catalogues` on the phone: the release listed, its file of this schema downloaded, checked and merged,
 * as a queued job of PhoneKinds' catalogues kind, its lines the kind's words. GitHub is a server on loopback that
 * serves the release's `indexes.json` and its files (CatalogueSource.Download's layout). */
class CataloguesRunnerTest {
    @get:Rule val tmp = TemporaryFolder()

    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
    private val opened = mutableListOf<Database>()
    private val github = Release()
    private var now: Instant = Instant.parse("2026-11-24T12:00:00Z")
    private var metered = false
    private var free = Long.MAX_VALUE
    private var forgotten = 0

    @After fun close() {
        scope.cancel()
        opened.forEach { it.close() }
        github.close()
    }

    private val newest = "indexes-s17-20261124T0312Z.sqlite.gz"
    private val older = "indexes-s17-20261117T0312Z.sqlite.gz"

    /** The release on loopback: a route a path, a path with none 404; [asked] each path asked, in order. */
    private class Release : AutoCloseable {
        class Reply(val status: Int, val body: ByteArray = ByteArray(0), val headers: Map<String, String> = emptyMap())

        val routes = ConcurrentHashMap<String, Reply>()
        val asked = CopyOnWriteArrayList<String>()
        private val server = HttpServer.create(InetSocketAddress(InetAddress.getLoopbackAddress(), 0), 0)
        val base: URI get() = URI("http://127.0.0.1:${server.address.port}")

        init {
            server.executor = Executors.newFixedThreadPool(2) { r -> Thread(r, "fake-release").apply { isDaemon = true } }
            server.createContext("/") { exchange ->
                val path = exchange.requestURI.rawPath
                asked += path
                val reply = routes[path] ?: Reply(404)
                for ((name, value) in reply.headers) exchange.responseHeaders.add(name, value)
                exchange.sendResponseHeaders(reply.status, if (reply.body.isEmpty()) -1 else reply.body.size.toLong())
                exchange.responseBody.use { it.write(reply.body) }
            }
            server.start()
        }

        override fun close() = server.stop(0)
    }

    private val folder = "/${Catalogues.REPO}/releases/download/${Catalogues.TAG}/"

    /** The release's files: each name with its gzip (and the size its manifest lists, its own by default). */
    private fun publish(vararg files: Pair<String, ByteArray>, listed: Map<String, Long> = emptyMap()) {
        val entries = files.joinToString(", ") { (name, gz) ->
            """{"file": "$name", "bytes": ${listed[name] ?: gz.size.toLong()}, "sha256": "${sha256(gz)}"}"""
        }
        github.routes[folder + "indexes.json"] = Release.Reply(200, """{"format": 1, "files": [$entries]}""".toByteArray())
        for ((name, gz) in files) github.routes[folder + name] = Release.Reply(200, gz)
    }

    /** An index export of gtptabs.com's and MuseScore's indexes (the corpus's partial export), its META's schema and
     * sites as given, gzipped. */
    private fun export(schema: Int = Database.SCHEMA_VERSION, sites: String = """["gtptabs", "musescore"]"""): ByteArray {
        val file = File(tmp.newFolder(), "export.sqlite")
        Fixtures.loadRaw(file, "index/fixtures/partial-export.jsonl")
        val c = BundledSQLiteDriver().open(file.path)
        try {
            c.prepare("UPDATE caracole_export SET value = ? WHERE key = 'schema'").use { it.bindText(1, "$schema"); it.step() }
            c.prepare("UPDATE caracole_export SET value = ? WHERE key = 'sites'").use { it.bindText(1, sites); it.step() }
            // Bytes that don't compress, in a table no merge reads: a few pages of rows unpack to more than
            // Catalogues.CAP_FACTOR times their gzip, which a real index never does.
            c.execSQL("CREATE TABLE padding (bytes BLOB NOT NULL)")
            c.prepare("INSERT INTO padding (bytes) VALUES (?)").use { it.bindBlob(1, Random(17).nextBytes(40_000)); it.step() }
        } finally {
            c.close()
        }
        return gzip(file.readBytes())
    }

    private class Phone(val parts: PhoneParts, val queue: JobQueue, val runner: CataloguesRunner) {
        val cache: File get() = File(parts.stateDir, "cache/catalogues")
        fun kv(key: String): String? = parts.database.read { it.kvGet(key) }
        fun tabs(): Long = parts.database.read { db -> db.one("SELECT COUNT(*) FROM gtptabs_index") { it.long(0)!! }!! }
    }

    private fun phone(): Phone {
        val dir = tmp.newFolder()
        val database = TestDb.fresh(dir).also { opened += it }
        val runners = HashMap<String, CommandRunner>()
        val queue = JobQueue(scope, commands = Commands(runners))
        val parts = TestParts.of(database, dir, scope, queue)
        val runner = CataloguesRunner(parts, CatalogueSource.Download(Http(), base = github.base), clock = { now },
                                      http = Http(), metered = { metered }, forget = { forgotten++ }, free = { free })
        runners[CataloguesRunner.COMMAND] = runner
        return Phone(parts, queue, runner)
    }

    private fun run(phone: Phone, meteredOk: Boolean = false): Job = runBlocking {
        val job = phone.queue.submit(phone.runner.spec(meteredOk)).first
        withTimeout(60_000) { phone.queue.await(job.id) }
    }

    private fun detail(job: Job): String = job.stages.single().detail

    @Test fun theJobIsOneOfThePhonesOwnOneAtATime() {
        val phone = phone()
        val kind = PhoneKinds.CATALOGUES
        val spec = phone.runner.spec(false)
        assertEquals(listOf(kind.title, "catalogues:", "catalogues", kind.display),
                     listOf(spec.title, spec.key, spec.kind, spec.display))
        assertEquals(listOf(kind.stage), spec.stages)
        assertEquals(emptyList(), spec.commands)
        assertEquals(false, spec.join)
        assertEquals("catalogues:", phone.runner.spec(true).key)
    }

    @Test fun importsTheNewestOfItsSchemaAndSaysItsDate() {
        val phone = phone()
        publish(older to export(), newest to export(), "indexes-s18-20261124T0400Z.sqlite.gz" to export(18))
        val job = run(phone)
        assertEquals(Job.DONE, job.state, job.asJson().toString())
        assertEquals("Catalogues of 24 Nov 2026", JobViews.line(job).text)
        assertEquals(newest, phone.kv(Catalogues.IMPORTED))
        assertEquals(4L, phone.tabs())
        assertEquals(listOf(folder + "indexes.json", folder + newest), github.asked)
        assertTrue(forgotten > 0, "the search's answers forgotten")
        assertEquals(emptyList(), phone.cache.listFiles().orEmpty().toList())
    }

    @Test fun upToDateDownloadsNothing() {
        val phone = phone()
        publish(newest to export())
        phone.parts.database.writeBlocking { it.kvSet(Catalogues.IMPORTED, newest) }
        val job = run(phone)
        assertEquals(Job.DONE, job.state, job.asJson().toString())
        assertEquals("Up to date: the catalogues of 24 Nov 2026", JobViews.line(job).text)
        assertEquals(listOf(folder + "indexes.json"), github.asked)
        assertEquals(0L, phone.tabs())
    }

    @Test fun aNewerSchemaFailsInTheSpecsWords() {
        val phone = phone()
        publish("indexes-s18-20261124T0400Z.sqlite.gz" to export(18))
        val job = run(phone)
        assertEquals(Job.FAILED, job.state)
        assertEquals("Not imported: The published catalogues are for a newer caracole (schema 18). Update the app.",
                     detail(job))
        assertEquals("Not imported: The published catalogues are for a newer caracole (schema 18).",
                     JobViews.line(job).text)
        assertEquals(listOf(folder + "indexes.json"), github.asked)
        // No file at all: none published yet.
        github.routes.clear()
        val none = run(phone)
        assertEquals("Not imported: No catalogues are published yet.", detail(none))
    }

    @Test fun aRefusedMergeLeavesNothingImported() {
        val phone = phone()
        publish(newest to export(schema = 16))
        val job = run(phone)
        assertEquals(Job.FAILED, job.state)
        assertTrue(detail(job).startsWith("Not imported: The file was exported at schema version 16, and this " +
                                              "caracole's database is at 17"), detail(job))
        assertTrue(phone.parts.stateDir.path !in detail(job), "no path of the phone's in its words")
        assertNull(phone.kv(Catalogues.IMPORTED))
        assertEquals(0L, phone.tabs())
        assertEquals(emptyList(), phone.cache.listFiles().orEmpty().toList())
    }

    @Test fun aSiteItDoesntKnowIsImportedAndSaid() {
        val phone = phone()
        publish(newest to export(sites = """["gtptabs", "musescore", "ireal"]"""))
        val job = run(phone)
        assertEquals(Job.DONE, job.state, job.asJson().toString())
        assertEquals("Catalogues of 24 Nov 2026. It also holds ireal's, which this version doesn't read. Update " +
                         "the app to search it.", detail(job))
        assertEquals(4L, phone.tabs())
        assertEquals(newest, phone.kv(Catalogues.IMPORTED))
        // Several, joined as a sentence joins them.
        assertEquals(" It also holds a's, b's and c's, which this version doesn't read. Update the app to search them.",
                     CataloguesRunner.unknown(listOf("a", "b", "c")))
        assertEquals(" It also holds a's and b's, which this version doesn't read. Update the app to search them.",
                     CataloguesRunner.unknown(listOf("a", "b")))
        assertEquals("", CataloguesRunner.unknown(emptyList()))
    }

    @Test fun noRoomFailsBeforeAnyDownload() {
        val phone = phone()
        publish(newest to export(), listed = mapOf(newest to 52_000_000L))
        free = 700_000_000L
        val job = run(phone)
        assertEquals(Job.FAILED, job.state)
        assertEquals("Not imported: The import needs about 1.2 GB free; the phone has 700 MB.", detail(job))
        assertEquals(listOf(folder + "indexes.json"), github.asked, "the file never asked for")
        assertNull(phone.kv(Catalogues.IMPORTED))
    }

    @Test fun limitedIsKeptAndNothingIsAskedBeforeIt() {
        val phone = phone()
        val until = now.plusSeconds(3600)
        github.routes[folder + "indexes.json"] = Release.Reply(
            403, """{"message": "API rate limit exceeded"}""".toByteArray(),
            mapOf("x-ratelimit-remaining" to "0", "x-ratelimit-reset" to until.epochSecond.toString()),
        )
        val job = run(phone)
        assertEquals(Job.FAILED, job.state)
        val words = "Not imported: " + Limited(until).message
        assertEquals(words, detail(job))
        assertEquals(Stamps.of(until), phone.kv(Catalogues.NOT_BEFORE))
        assertEquals(1, github.asked.size)
        // Before then nothing is asked, and the job says so in the same words.
        publish(newest to export())
        val again = run(phone)
        assertEquals(Job.FAILED, again.state)
        assertEquals(words, detail(again))
        assertEquals(1, github.asked.size)
        // Once it has passed, the release is asked again.
        now = until.plusSeconds(1)
        assertEquals(Job.DONE, run(phone).state)
        assertEquals(newest, phone.kv(Catalogues.IMPORTED))
    }

    @Test fun theFileIsDeletedWhateverCameOfIt() {
        val phone = phone()
        // One a killed job left goes too.
        phone.cache.mkdirs()
        File(phone.cache, "indexes-s17-20261110T0312Z.sqlite").writeText("left")
        val gz = export()
        publish(newest to gz)
        github.routes[folder + newest] = Release.Reply(200, gz + byteArrayOf(0))  // not its bytes
        val bad = run(phone)
        assertEquals(Job.FAILED, bad.state)
        assertEquals("Not imported: The download isn't the file GitHub listed. Try again.", detail(bad))
        assertEquals(emptyList(), phone.cache.listFiles().orEmpty().toList())
        assertNull(phone.kv(Catalogues.IMPORTED))
        publish(newest to gz)
        assertEquals(Job.DONE, run(phone).state)
        assertEquals(emptyList(), phone.cache.listFiles().orEmpty().toList())
    }

    @Test fun aMeteredNetworkStopsBeforeTheDownloadAndSaysTheSize() {
        val phone = phone()
        metered = true
        publish(newest to export(), listed = mapOf(newest to 52_000_000L))
        val job = run(phone)
        assertEquals(Job.DONE, job.state, job.asJson().toString())
        assertEquals("52 MB to download: waiting for Wi-Fi or your go-ahead", JobViews.line(job).text)
        assertEquals(PyJson.loads("""{"name": "$newest", "bytes": 52000000}"""),
                     PyJson.loads(phone.kv(CataloguesRunner.ASKING)!!) as JsonObject)
        assertEquals(listOf(folder + "indexes.json"), github.asked, "nothing downloaded")
        assertNull(phone.kv(Catalogues.IMPORTED))
        // The go-ahead: downloaded on the metered network, the question gone.
        publish(newest to export())
        val ahead = run(phone, meteredOk = true)
        assertEquals(Job.DONE, ahead.state, ahead.asJson().toString())
        assertEquals(newest, phone.kv(Catalogues.IMPORTED))
        assertNull(phone.kv(CataloguesRunner.ASKING))
    }

    @Test fun theDownloadSaysHowFarItHasGot() {
        val phone = phone()
        publish(newest to export())
        val said = CopyOnWriteArrayList<String>()
        val context = object : JobContext {
            override fun stage(name: String, state: String, detail: String) { said += "$state $detail" }
            override fun say(line: String) {}
            override fun outcome(value: JsonObject) {}
            override val isCancelled: Boolean = false
        }
        runBlocking { phone.runner.run(listOf(CataloguesRunner.COMMAND), context) }
        assertTrue(said.any { it.startsWith("running Downloading · ") && it.endsWith(" MB") }, "$said")
        assertEquals("done Catalogues of 24 Nov 2026", said.last())
        assertEquals("Downloading · 31 of 52 MB", CataloguesRunner.downloading(31_000_000, 52_000_000))
        assertEquals("Downloading · 0.4 of 1.2 GB", CataloguesRunner.downloading(400_000_000, 1_196_000_000))
    }

    @Test fun sizesAreSaidAsThePagesSayThem() {
        assertEquals(listOf("0.1 MB", "0.4 MB", "3.4 MB", "52 MB", "207 MB", "700 MB", "1.2 GB", "12.0 GB"),
                     listOf(0L, 400_000L, 3_400_000L, 52_000_000L, 207_000_000L, 700_000_000L, 1_196_000_000L,
                            12_000_000_000L).map(CataloguesRunner::size))
    }

    @Test fun aWrongCommandLineIsRefused() {
        val phone = phone()
        val context = object : JobContext {
            override fun stage(name: String, state: String, detail: String) {}
            override fun say(line: String) {}
            override fun outcome(value: JsonObject) {}
            override val isCancelled: Boolean = false
        }
        val e = runCatching { runBlocking { phone.runner.run(listOf("catalogues", "--now"), context) } }.exceptionOrNull()
        assertEquals(io.github.danielhp95.caracole.server.jobs.CommandExit::class, e!!::class)
    }

    private fun gzip(bytes: ByteArray): ByteArray {
        val out = ByteArrayOutputStream()
        GZIPOutputStream(out).use { it.write(bytes) }
        return out.toByteArray()
    }

    private fun sha256(bytes: ByteArray): String =
        MessageDigest.getInstance("SHA-256").digest(bytes).joinToString("") { "%02x".format(it) }
}
