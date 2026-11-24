package io.github.danielhp95.caracole.server.lookups

import androidx.sqlite.driver.bundled.BundledSQLiteDriver
import androidx.sqlite.execSQL
import io.github.danielhp95.caracole.core.catalogues.CatalogueSource
import io.github.danielhp95.caracole.core.catalogues.Catalogues
import io.github.danielhp95.caracole.core.catalogues.FakeGitHub
import io.github.danielhp95.caracole.core.catalogues.Limited
import io.github.danielhp95.caracole.core.config.PhoneConfig
import io.github.danielhp95.caracole.core.db.Database
import io.github.danielhp95.caracole.core.index.Stamps
import io.github.danielhp95.caracole.core.json.PyJson
import io.github.danielhp95.caracole.core.testing.Fixtures
import io.github.danielhp95.caracole.core.testing.TestDb
import io.github.danielhp95.caracole.server.PhoneParts
import io.github.danielhp95.caracole.server.jobs.CommandRunner
import io.github.danielhp95.caracole.server.jobs.Commands
import io.github.danielhp95.caracole.server.jobs.Job
import io.github.danielhp95.caracole.server.jobs.JobContext
import io.github.danielhp95.caracole.server.jobs.JobQueue
import io.github.danielhp95.caracole.server.jobs.JobSpec
import io.github.danielhp95.caracole.server.jobs.JobViews
import io.github.danielhp95.caracole.server.jobs.Line
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
import java.io.File
import java.time.Instant
import java.util.concurrent.ConcurrentHashMap
import java.util.concurrent.CopyOnWriteArrayList
import kotlin.random.Random
import kotlin.test.assertEquals
import kotlin.test.assertNull
import kotlin.test.assertTrue

/** `caracole catalogues` on the phone: the release listed, its file of this schema downloaded, checked and merged,
 * as a queued job of PhoneKinds' catalogues kind, its lines the kind's words. GitHub is a server on loopback that
 * answers GitHub's API's release by its tag and serves its assets (CatalogueSource.Api's layout). */
class CataloguesRunnerTest {
    @get:Rule val tmp = TemporaryFolder()

    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
    private val opened = mutableListOf<Database>()
    private val github = FakeGitHub()
    private var now: Instant = Instant.parse("2026-11-24T12:00:00Z")
    private var metered = false
    private var free = Long.MAX_VALUE
    private var forgotten = 0
    private var tick = 0L
    private var tickBy = 0L  // how far the clock the job paces its words by moves at each reading
    private var chunk = io.github.danielhp95.caracole.core.index.IndexTransfer.UG_CHUNK  // UG's rows a statement

    @After fun close() {
        scope.cancel()
        opened.forEach { it.close() }
        github.close()
    }

    private val schema = Database.SCHEMA_VERSION
    private val newest = "indexes-s$schema-20261124T0312Z.sqlite.gz"
    private val older = "indexes-s$schema-20261117T0312Z.sqlite.gz"
    private val newer = "indexes-s${schema + 1}-20261124T0400Z.sqlite.gz"

    /** The paths GitHub was asked, in order. */
    private fun asked(): List<String> = github.asked.map { it.removePrefix("GET ").substringBefore(" ·") }

    /** GitHub's API's release of the catalogues, and an asset's address (each file's id its place in the list). */
    private val release = "/repos/${Catalogues.REPO}/releases/tags/${Catalogues.TAG}"
    private val ids = ConcurrentHashMap<String, Int>()
    private fun asset(name: String) = "/repos/${Catalogues.REPO}/releases/assets/${ids.getOrPut(name) { ids.size + 1 }}"

    /** The release's files: each name with its gzip (and the size the API lists, its own by default). */
    private fun publish(vararg files: Pair<String, ByteArray>, listed: Map<String, Long> = emptyMap()) {
        val assets = files.joinToString(", ") { (name, gz) ->
            """{"name": "$name", "url": "${github.base}${asset(name)}", "size": ${listed[name] ?: gz.size.toLong()}, """ +
                """"digest": "sha256:${FakeGitHub.sha256(gz)}", "state": "uploaded"}"""
        }
        github.route(release, FakeGitHub.Reply(200, """{"tag_name": "indexes", "assets": [$assets]}""".toByteArray()))
        for ((name, gz) in files) github.route(asset(name), FakeGitHub.Reply(200, gz))
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
            // Bytes that don't compress, in a table no merge reads, as a real index's mostly don't.
            c.execSQL("CREATE TABLE padding (bytes BLOB NOT NULL)")
            c.prepare("INSERT INTO padding (bytes) VALUES (?)").use { it.bindBlob(1, Random(17).nextBytes(40_000)); it.step() }
        } finally {
            c.close()
        }
        return FakeGitHub.gzip(file.readBytes())
    }

    private class Phone(val parts: PhoneParts, val queue: JobQueue, val runner: CataloguesRunner,
                        val runners: MutableMap<String, CommandRunner> = HashMap()) {
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
        val runner = CataloguesRunner(parts, source = { http -> CatalogueSource.Api(http, base = github.base) },
                                      clock = { now }, metered = { metered }, forget = { forgotten++ }, free = { free },
                                      ticks = { tick.also { tick += tickBy } }, chunk = chunk)
        runners[CataloguesRunner.COMMAND] = runner
        return Phone(parts, queue, runner, runners)
    }

    private fun run(phone: Phone, meteredOk: Boolean = false): Job = runBlocking {
        val job = phone.queue.submit(phone.runner.spec(meteredOk)).first
        withTimeout(60_000) { phone.queue.await(job.id) }
    }

    private fun detail(job: Job): String = job.stages.single().detail

    /** An index export of [rows] UG tabs (BigIndex), gtptabs.com's and MuseScore's beside them, and [padding] bytes
     * that don't compress in a table no merge reads (so the download has counts to say), gzipped. */
    private fun bigExport(rows: Int, padding: Int = 300_000): ByteArray {
        val file = io.github.danielhp95.caracole.core.testing.BigIndex(rows).export(File(tmp.newFolder(), "big.sqlite"))
        val c = BundledSQLiteDriver().open(file.path)
        try {
            c.execSQL("CREATE TABLE padding (bytes BLOB NOT NULL)")
            c.prepare("INSERT INTO padding (bytes) VALUES (?)").use { it.bindBlob(1, Random(5).nextBytes(padding)); it.step() }
        } finally {
            c.close()
        }
        return FakeGitHub.gzip(file.readBytes())
    }

    /** A job's context that keeps what it is told, in order: each stage's state and words, and each yield to the
     * lookups queued (`yield`). */
    private class Told : JobContext {
        val said = CopyOnWriteArrayList<String>()
        override fun stage(name: String, state: String, detail: String) { said += "$state $detail" }
        override fun say(line: String) {}
        override fun outcome(value: JsonObject) {}
        override val isCancelled: Boolean = false
        override fun yieldToQueued() { said += "yield" }
        fun running(): List<String> = said.filter { it.startsWith("running ") }.map { it.removePrefix("running ") }
    }

    /** Whether [said] holds [wanted] in their order (others between them). */
    private fun inOrder(said: List<String>, wanted: List<String>): Boolean {
        var at = 0
        for (line in said) if (at < wanted.size && line == wanted[at]) at++
        return at == wanted.size
    }

    @Test fun theJobIsOneOfThePhonesOwnOneAtATime() {
        val phone = phone()
        val kind = PhoneKinds.CATALOGUES
        val spec = phone.runner.spec(false)
        assertEquals(listOf(kind.title, "catalogues:", "catalogues", kind.display),
                     listOf(spec.title, spec.key, spec.kind, spec.display))
        assertEquals(listOf(kind.stage), spec.stages)
        assertEquals(emptyList(), spec.commands)
        assertEquals(false, spec.join)
        assertEquals("catalogues:go", phone.runner.spec(true).key)
    }

    @Test fun aGoAheadTappedWhileAPlainJobWaitsIsAJobOfItsOwn() {
        val phone = phone()
        val gate = kotlinx.coroutines.CompletableDeferred<Unit>()
        phone.queue.submit(JobSpec("Hold the queue", "hold", "add", emptyList()) { gate.await() })
        val plain = phone.queue.submit(phone.runner.spec(false)).first
        assertEquals(plain.id, phone.queue.submit(phone.runner.spec(false)).first.id, "one at a time")
        val go = phone.queue.submit(phone.runner.spec(true)).first
        assertTrue(go.id != plain.id, "the go-ahead is never answered by the plain job waiting")
        assertEquals(go.id, phone.queue.submit(phone.runner.spec(true)).first.id)
        metered = true
        publish(newest to export())
        gate.complete(Unit)
        val waited = runBlocking { withTimeout(60_000) { phone.queue.await(plain.id) } }
        assertEquals("waiting", JobViews.line(waited).tone, "the plain job stopped for the network")
        assertEquals(Job.DONE, runBlocking { withTimeout(60_000) { phone.queue.await(go.id) } }.state)
        assertEquals(newest, phone.kv(Catalogues.IMPORTED))
    }

    @Test fun importsTheNewestOfItsSchemaAndSaysItsDate() {
        val phone = phone()
        publish(older to export(), newest to export(), newer to export(schema + 1))
        val job = run(phone)
        assertEquals(Job.DONE, job.state, job.asJson().toString())
        assertEquals("Catalogues of 24 Nov 2026", JobViews.line(job).text)
        assertEquals(newest, phone.kv(Catalogues.IMPORTED))
        assertEquals(4L, phone.tabs())
        assertEquals(listOf(release, asset(newest)), asked())
        assertEquals(listOf(PhoneConfig.DEFAULTS.userAgent, PhoneConfig.DEFAULTS.userAgent), github.agents)
        assertTrue(forgotten > 0, "the search's answers forgotten")
        assertEquals(emptyList(), phone.cache.listFiles().orEmpty().toList())
    }

    @Test fun upToDateDownloadsNothing() {
        val phone = phone()
        publish(newest to export())
        phone.parts.database.writeBlocking { it.kvSet(Catalogues.IMPORTED, newest) }
        val job = run(phone)
        assertEquals(Job.DONE, job.state, job.asJson().toString())
        assertEquals(Line("ready", "Up to date: the catalogues of 24 Nov 2026"), JobViews.line(job))
        assertEquals(listOf(release), asked())
        assertEquals(0L, phone.tabs())
    }

    @Test fun aNewerSchemaFailsInTheSpecsWords() {
        val phone = phone()
        publish(newer to export(schema + 1))
        val job = run(phone)
        assertEquals(Job.FAILED, job.state)
        assertEquals("Not imported: The published catalogues are for a newer caracole (schema ${schema + 1}): update the app.",
                     detail(job))
        assertEquals("Not imported: The published catalogues are for a newer caracole (schema ${schema + 1}): update the app.",
                     JobViews.line(job).text, "what to do is kept in the line's one sentence")
        assertEquals(listOf(release), asked())
        // No file at all: none published yet.
        github.routes.clear()
        val none = run(phone)
        assertEquals("Not imported: No catalogues are published yet.", detail(none))
    }

    @Test fun aRefusedMergeLeavesNothingImported() {
        val phone = phone()
        publish(newest to export(schema = schema - 1))
        val job = run(phone)
        assertEquals(Job.FAILED, job.state)
        assertTrue(detail(job).startsWith("Not imported: The file was exported at schema version ${schema - 1}, and " +
                                              "this caracole's database is at $schema"), detail(job))
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
        assertEquals(listOf(release), asked(), "the file never asked for")
        assertNull(phone.kv(Catalogues.IMPORTED))
    }

    @Test fun limitedIsKeptAndNothingIsAskedBeforeIt() {
        val phone = phone()
        val until = now.plusSeconds(3600)
        github.route(release, FakeGitHub.Reply(
            403, """{"message": "API rate limit exceeded"}""".toByteArray(),
            mapOf("x-ratelimit-remaining" to "0", "x-ratelimit-reset" to until.epochSecond.toString()),
        ))
        val job = run(phone)
        assertEquals(Job.FAILED, job.state)
        val words = "Not imported: " + Limited(until).message
        assertEquals(words, detail(job))
        assertEquals(Stamps.of(until), phone.kv(Catalogues.NOT_BEFORE))
        assertEquals(1, asked().size)
        // Before then nothing is asked, and the job says so in the same words.
        publish(newest to export())
        val again = run(phone)
        assertEquals(Job.FAILED, again.state)
        assertEquals(words, detail(again))
        assertEquals(1, asked().size)
        // Once it has passed, the release is asked again.
        now = until.plusSeconds(1)
        assertEquals(Job.DONE, run(phone).state)
        assertEquals(newest, phone.kv(Catalogues.IMPORTED))
    }

    @Test fun theFileIsDeletedWhateverCameOfIt() {
        val phone = phone()
        // One a killed job left goes too.
        phone.cache.mkdirs()
        File(phone.cache, "indexes-s$schema-20261110T0312Z.sqlite").writeText("left")
        val gz = export()
        publish(newest to gz)
        github.route(asset(newest), FakeGitHub.Reply(200, gz + byteArrayOf(0)))  // not its bytes
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
        assertEquals(Line("waiting", "52 MB to download: waiting for your go-ahead in Settings (a metered network)",
                          details = "#tab=requests&job=${job.id}"), JobViews.line(job))
        assertEquals(PyJson.loads("""{"name": "$newest", "bytes": 52000000}"""),
                     PyJson.loads(phone.kv(CataloguesRunner.ASKING)!!) as JsonObject)
        assertEquals(listOf(release), asked(), "nothing downloaded")
        assertNull(phone.kv(Catalogues.IMPORTED))
        // The go-ahead: downloaded on the metered network, the question gone.
        publish(newest to export())
        val ahead = run(phone, meteredOk = true)
        assertEquals(Job.DONE, ahead.state, ahead.asJson().toString())
        assertEquals(newest, phone.kv(Catalogues.IMPORTED))
        assertNull(phone.kv(CataloguesRunner.ASKING))
    }

    /** A restore leaves the index tables as they are (no backup holds them), so it leaves the catalogues' records,
     * which say what those tables hold, as they are too (OwnRecords): after a restore of a backup made before the
     * import, a tap says Up to date and downloads nothing, the catalogue still in the index. */
    @Test fun aRestoreLeavesTheRecordOfTheCatalogueTheIndexStillHolds() {
        val phone = phone()
        val backup = phone.parts.database.writeBlocking { db ->
            io.github.danielhp95.caracole.core.backup.Backups.make(db, phone.parts.store, phone.parts.stateDir, now, "by-hand")
        }!!
        publish(newest to export())
        assertEquals(Job.DONE, run(phone).state)
        phone.parts.database.writeBlocking { it.kvSet(Catalogues.NOT_BEFORE, Stamps.of(now.minusSeconds(60))) }
        io.github.danielhp95.caracole.core.backup.Backups.restore(phone.parts.database, phone.parts.store, backup)
        assertEquals(newest, phone.kv(Catalogues.IMPORTED), "the record of what the index holds kept")
        assertEquals(Stamps.of(now.minusSeconds(60)), phone.kv(Catalogues.NOT_BEFORE), "and GitHub's time, as it is now")
        assertEquals(4L, phone.tabs(), "the index as it was")
        github.asked.clear()
        val again = run(phone)
        assertEquals(Line("ready", "Up to date: the catalogues of 24 Nov 2026"), JobViews.line(again))
        assertEquals(listOf(release), asked(), "nothing downloaded")
    }

    @Test fun aNotBeforeFarAheadOfTheClockIsPassedOver() {
        // GitHub's reset is within the hour: one more than two hours on is a clock that was wrong, never a wait.
        val phone = phone()
        publish(newest to export())
        phone.parts.database.writeBlocking { it.kvSet(Catalogues.NOT_BEFORE, Stamps.of(now.plusSeconds(3 * 3600))) }
        val job = run(phone)
        assertEquals(Job.DONE, job.state, job.asJson().toString())
        assertEquals(newest, phone.kv(Catalogues.IMPORTED))
    }

    @Test fun aNotBeforeWithinTwoHoursStillHolds() {
        val phone = phone()
        publish(newest to export())
        phone.parts.database.writeBlocking { it.kvSet(Catalogues.NOT_BEFORE, Stamps.of(now.plusSeconds(2 * 3600 - 60))) }
        val job = run(phone)
        assertEquals(Job.FAILED, job.state)
        assertEquals(emptyList(), asked())
    }

    @Test fun anUnreadableNotBeforeIsNone() {
        val phone = phone()
        publish(newest to export())
        for (stored in listOf("soon", "0001-01-01T00:00:00+01:00")) {
            phone.parts.database.writeBlocking { it.kvSet(Catalogues.NOT_BEFORE, stored) }
            phone.parts.database.writeBlocking { it.kvDelete(Catalogues.IMPORTED) }
            val job = run(phone)
            assertEquals(Job.DONE, job.state, "$stored: ${job.asJson()}")
        }
    }

    @Test fun theUserAgentIsTheSettingsWhenItRuns() {
        val phone = phone()
        publish(newest to export())
        phone.parts.database.writeBlocking {
            it.kvSet(PhoneConfig.SETTINGS_KV, """{"user_agent": "caracole/0.1 (Dani's tabs)"}""")
        }
        assertEquals(Job.DONE, run(phone).state)
        assertEquals(listOf("caracole/0.1 (Dani's tabs)", "caracole/0.1 (Dani's tabs)"), github.agents)
    }

    @Test fun aRecordReadWithinADayAheadOfThePhonesClockIsStillTaken() {
        val phone = phone()
        // The phone read gtptabs.com's first sitemap before; the laptop read it again with its clock half a day ahead
        // of the phone's, so the file says it read it "after" the phone's now, and its rows are taken all the same.
        phone.parts.database.writeBlocking {
            it.kvSet("gtptabs:sitemaps", """{"sitemap-tabs-1.xml": {"checked_at": "2026-10-01T00:00:00Z", "rows": 0}}""")
        }
        now = Instant.parse("2026-10-27T16:00:00Z")  // the file's 2026-10-28T03:30:00Z is within a day
        publish(newest to export())
        assertEquals(Job.DONE, run(phone).state)
        assertEquals(4L, phone.tabs())
    }

    @Test fun aMergeThatFailsStillForgetsTheSearchsAnswers() {
        val phone = phone()
        publish(newest to export(schema = schema - 1))
        assertEquals(Job.FAILED, run(phone).state)
        assertEquals(1, forgotten)
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

    @Test fun theImportSaysEachOfItsStepsAndHowFarUltimateGuitarsTabsHaveGot() {
        chunk = 5  // a dozen rows, three chunks
        val phone = phone()
        publish(newest to bigExport(12))
        tickBy = 2_000_000_000L  // two seconds a reading: every count is said
        val told = Told()
        runBlocking { phone.runner.run(listOf(CataloguesRunner.COMMAND), told) }
        val steps = listOf(
            "Asking GitHub for the catalogues…", "Downloading · 0.0 of 0.3 MB", "Downloading · 0.3 of 0.3 MB",
            "Comparing with the phone's index…", "Importing · Ultimate Guitar",
            "Importing · Ultimate Guitar · 5 of 12 tabs", "Importing · Ultimate Guitar · 10 of 12 tabs",
            "Importing · Ultimate Guitar · 12 of 12 tabs", "Importing · gtptabs.com", "Importing · MuseScore",
            "Tidying the database…",
        )
        assertTrue(inOrder(told.running(), steps), told.running().joinToString("\n"))
        assertEquals("done Catalogues of 24 Nov 2026", told.said.last())
        assertEquals(12L, phone.parts.database.read { db -> db.one("SELECT COUNT(*) FROM ug_index") { it.long(0)!! } })
    }

    @Test fun itsWordsComeAtMostOnceASecondButEachStepsFirstAndLastAtOnce() {
        chunk = 5
        val phone = phone()
        publish(newest to bigExport(12))
        tickBy = 0  // the clock stands still: a step's first count and its last alone, each once
        val told = Told()
        runBlocking { phone.runner.run(listOf(CataloguesRunner.COMMAND), told) }
        val running = told.running()
        assertTrue(inOrder(running, listOf("Downloading · 0.0 of 0.3 MB", "Downloading · 0.3 of 0.3 MB",
                                           "Comparing with the phone's index…",
                                           "Importing · Ultimate Guitar · 5 of 12 tabs",
                                           "Importing · Ultimate Guitar · 12 of 12 tabs", "Importing · gtptabs.com",
                                           "Tidying the database…")), "$running")
        assertTrue(running.none { "10 of 12" in it }, "$running")
        assertEquals(2, running.count { it.startsWith("Downloading · ") }, "$running")
        assertEquals(running, running.distinct(), "nothing said twice")
    }

    @Test fun theLookupsQueuedMeanwhileGoFirstBetweenItsStepsNeverInsideTheMerge() {
        val phone = phone()
        publish(newest to bigExport(12))
        val told = Told()
        runBlocking { phone.runner.run(listOf(CataloguesRunner.COMMAND), told) }
        val said = told.said.toList()
        val yields = said.indices.filter { said[it] == "yield" }
        assertEquals(2, yields.size, "$said")
        // Once GitHub's list is read, before the download; once the download is in, before the merge.
        assertEquals("running Asking GitHub for the catalogues…", said[yields[0] - 1])
        assertEquals("running Downloading · 0.3 of 0.3 MB", said[yields[1] - 1], "the download's last count first")
        assertEquals("running Comparing with the phone's index…", said[yields[1] + 1])
        // A job of the queue's: a lookup queued as GitHub lists the release runs before anything is downloaded, one
        // queued as the file comes before anything is merged.
        val other = phone()
        val log = CopyOnWriteArrayList<String>()
        other.runners["get"] = CommandRunner { args, _ -> log += "${args.last()} after ${asked().size} asked, ${other.tabs()} tabs" }
        val gz = bigExport(12)
        publish(newest to gz)
        val list = github.routes.getValue(release)
        github.routes[release] = { other.queue.submit(lookupSpec("A", "1")); list() }
        github.routes[asset(newest)] = { other.queue.submit(lookupSpec("B", "2")); FakeGitHub.Reply(200, gz) }
        github.asked.clear()
        val job = run(other)
        assertEquals(Job.DONE, job.state, job.asJson().toString())
        assertEquals(listOf("1 after 1 asked, 0 tabs", "2 after 2 asked, 0 tabs"), log.toList())
        assertEquals(4L, other.tabs())
    }

    private fun lookupSpec(artist: String, title: String) = JobSpec(
        title = "Get $artist - $title", key = "${artist.lowercase()}/${title.lowercase()}", kind = "song",
        stages = emptyList(), commands = io.github.danielhp95.caracole.server.jobs.JobCommands.lookupSteps(artist, title),
        fetching = true)

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
}
