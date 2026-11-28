package io.github.danielhp95.caracole.server.lookups

import io.github.danielhp95.caracole.core.backup.OwnRecords
import io.github.danielhp95.caracole.core.catalogues.FakeGitHub
import io.github.danielhp95.caracole.core.catalogues.FakeGitHub.Reply
import io.github.danielhp95.caracole.core.catalogues.Limited
import io.github.danielhp95.caracole.core.db.Database
import io.github.danielhp95.caracole.core.index.Stamps
import io.github.danielhp95.caracole.core.models.From
import io.github.danielhp95.caracole.core.models.ModelFiles
import io.github.danielhp95.caracole.core.models.ModelsNotCarried
import io.github.danielhp95.caracole.core.models.ModelsSource
import io.github.danielhp95.caracole.core.models.Pin
import io.github.danielhp95.caracole.core.models.Pins
import io.github.danielhp95.caracole.core.testing.TestDb
import io.github.danielhp95.caracole.server.jobs.CommandRunner
import io.github.danielhp95.caracole.server.jobs.Commands
import io.github.danielhp95.caracole.server.jobs.Job
import io.github.danielhp95.caracole.server.jobs.JobQueue
import io.github.danielhp95.caracole.server.jobs.JobSpec
import io.github.danielhp95.caracole.server.jobs.JobViews
import io.github.danielhp95.caracole.server.jobs.Line
import io.github.danielhp95.caracole.server.jobs.PhoneKinds
import io.github.danielhp95.caracole.server.testing.TestParts
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.withTimeout
import org.junit.After
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import java.io.File
import java.nio.file.Files
import java.time.Instant
import java.util.concurrent.CopyOnWriteArrayList
import kotlin.random.Random
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertNotNull
import kotlin.test.assertNull
import kotlin.test.assertTrue

/** `caracole models [--metered-ok]` on the phone: the chord models downloaded as a queued job of PhoneKinds' models
 * kind, its lines the kind's words (§8.4), its records kv `models:installed` and `models:not-before`. GitHub is
 * FakeGitHub on loopback (the release, the asset's hop, BTC's blob), the pins a test's own. */
class ModelsRunnerTest {
    @get:Rule val tmp = TemporaryFolder()

    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
    private val opened = mutableListOf<Database>()
    private val github = FakeGitHub()
    private var now: Instant = Instant.parse("2026-11-27T12:00:00Z")
    private var metered = false

    @After fun close() {
        scope.cancel()
        opened.forEach { it.close() }
        github.close()
    }

    private val graph = Random(1).nextBytes(3_000)
    private val weights = Random(2).nextBytes(300_000)
    private val beats = Random(3).nextBytes(500_000)
    private val blob = "11c6edbaaaee33737aa7a41dcb9044191630326f"

    private fun pin(name: String, bytes: ByteArray, from: From) =
        Pin(name, bytes.size.toLong(), FakeGitHub.sha256(bytes), from)

    private val pins = Pins(1, "models", listOf(
        pin("btc-graph.onnx", graph, From.App),
        pin("btc_model_large_voca.pt", weights,
            From.Blob("jayg996/BTC-ISMIR19", "2682317be668032e6e4b269ded36adaa2ad57df0", "test/btc_model_large_voca.pt",
                      blob)),
        pin("beat_this-final0-fp16.onnx", beats, From.Release("beat_this-final0-fp16.onnx")),
    ))

    private val listPath = "/repos/Danielhp95/caracole/releases/tags/models"
    private val assetPath = "/repos/Danielhp95/caracole/releases/assets/9"
    private val blobPath = "/repos/jayg996/BTC-ISMIR19/git/blobs/$blob"

    private fun served() {
        github.route(listPath, Reply(200, ("""{"tag_name":"models","assets":[{"name":"beat_this-final0-fp16.onnx",""" +
            """"url":"${github.base}$assetPath","size":${beats.size},"state":"uploaded",""" +
            """"digest":"sha256:${FakeGitHub.sha256(beats)}"}]}""").toByteArray()))
        github.route(assetPath, Reply(302, headers = mapOf("Location" to "${github.base}/assets/9?sig=x")))
        github.route("/assets/9", Reply(200, beats))
        github.route(blobPath, Reply(200, weights))
    }

    /** The paths GitHub was asked, in order. */
    private fun asked(): List<String> = github.asked.map { it.removePrefix("GET ").substringBefore(" ·") }

    private class Phone(val runner: ModelsRunner, val queue: JobQueue, val database: Database, val stateDir: File) {
        fun kv(key: String): String? = database.read { it.kvGet(key) }
        val folder: File get() = runner.folder()!!
    }

    private fun source(): ModelsSource = ModelsSource(
        base = github.base, redirects = setOf("127.0.0.1"), pins = { pins },
        app = { name -> if (name == "btc-graph.onnx") graph.inputStream() else null },
    )

    private fun phone(source: ModelsSource? = source()): Phone {
        val dir = tmp.newFolder()
        val database = TestDb.fresh(dir).also { opened += it }
        val runners = HashMap<String, CommandRunner>()
        val queue = JobQueue(scope, commands = Commands(runners))
        val parts = TestParts.of(database, dir, scope, queue)
        // Each reading of the clock its words are paced by a second on: every word told as it comes.
        var tick = 0L
        val runner = ModelsRunner(parts, source, clock = { now }, metered = { metered },
                                  ticks = { tick.also { tick += 1_000_000_001L } })
        runners[ModelsRunner.COMMAND] = runner
        return Phone(runner, queue, database, parts.stateDir)
    }

    private fun run(phone: Phone, meteredOk: Boolean = false): Job = runBlocking {
        val job = phone.queue.submit(phone.runner.spec(meteredOk)).first
        withTimeout(60_000) { phone.queue.await(job.id) }
    }

    private fun detail(job: Job): String = job.stages.single().detail

    // --- a download ---------------------------------------------------------------------------------------------------

    @Test fun aDownloadInstallsTheModelsRecordsThemAndSaysTheKindsWords() {
        served()
        val phone = phone()
        assertEquals("The chord models aren't on the phone.", phone.runner.ready())
        val job = run(phone)
        assertEquals(Job.DONE, job.state, job.steps.joinToString { it.output.joinToString() })
        assertEquals("Chord models ready · 0.8 MB", detail(job))
        assertEquals(Line("ready", "Chord models ready · 0.8 MB"), JobViews.line(job))
        assertEquals(listOf(listPath, assetPath, "/assets/9", blobPath), asked())
        assertNull(ModelFiles.verify(phone.folder, pins))
        assertEquals(File(phone.stateDir, "models/c1"), phone.folder)
        assertNull(phone.runner.ready())
        // models:installed: what was installed and when, as kv_set_json writes it.
        assertEquals("""{"contract": 1, "files": ["btc-graph.onnx", "btc_model_large_voca.pt", """ +
                         """"beat_this-final0-fp16.onnx"], "bytes": 803000, "when": "2026-11-27T12:00:00Z"}""",
                     phone.kv(ModelsRunner.INSTALLED))
        assertEquals(PhoneKinds.MODELS.kind, job.spec.kind)
        assertEquals("models:", job.spec.key)
        assertEquals("The chord models", job.spec.display)
        assertEquals("Download the chord models", job.spec.title)
    }

    @Test fun aSecondRunAsksNothingAndAnInstallTheRecordLostIsRecordedAgain() {
        served()
        val phone = phone()
        run(phone)
        github.asked.clear()
        phone.database.writeBlocking { it.kvDelete(ModelsRunner.INSTALLED) }
        now = Instant.parse("2026-11-28T09:30:00Z")
        val again = run(phone)
        assertEquals("Chord models ready · 0.8 MB", detail(again))
        assertEquals(emptyList(), github.asked)
        assertTrue(phone.kv(ModelsRunner.INSTALLED)!!.endsWith(""""when": "2026-11-28T09:30:00Z"}"""))
    }

    /** The files judge: a record that says installed over a folder gone is a note, never the answer; the job
     * downloads them again. */
    @Test fun theFilesJudgeWhetherTheyAreInstalledNeverTheRecord() {
        served()
        val phone = phone()
        run(phone)
        File(phone.folder, "beat_this-final0-fp16.onnx").delete()
        assertNotNull(phone.kv(ModelsRunner.INSTALLED))
        assertEquals("The chord models on the phone aren't whole: no beat_this-final0-fp16.onnx.", phone.runner.ready())
        github.asked.clear()
        assertEquals("Chord models ready · 0.8 MB", detail(run(phone)))
        assertEquals(listOf(listPath, assetPath, "/assets/9"), asked())
        assertNull(phone.runner.ready())
    }

    @Test fun whileItDownloadsItSaysHowFarAndTheShareAsData() {
        served()
        val phone = phone()
        val said = CopyOnWriteArrayList<String>()
        val shares = CopyOnWriteArrayList<Pair<Long?, Long?>>()
        // The answer of the blob held until the job has said its download: the line read as it runs.
        val gate = CompletableDeferred<Unit>()
        github.routes[blobPath] = { runBlocking { gate.await() }; Reply(200, weights) }
        val job = phone.queue.submit(phone.runner.spec()).first
        runBlocking {
            withTimeout(30_000) {
                while (true) {
                    val seen = phone.queue.job(job.id)!!
                    val stage = seen.stages.single()
                    if (stage.detail.isNotEmpty() && said.lastOrNull() != stage.detail) said += stage.detail
                    shares += stage.done to stage.total
                    // beat_this's last byte in (491,520 of them already say "0.5 of 0.8 MB"), BTC's held.
                    if (stage.detail.startsWith("Downloading the chord models · 0.5 of 0.8 MB") &&
                        stage.done == 500_000L) break
                    Thread.sleep(5)
                }
            }
        }
        assertEquals(Line("running", "Downloading the chord models · 0.5 of 0.8 MB"), JobViews.line(phone.queue.job(job.id)!!))
        assertEquals(500_000L to 800_000L, phone.queue.job(job.id)!!.stages.single().let { it.done to it.total })
        gate.complete(Unit)
        val over = runBlocking { withTimeout(30_000) { phone.queue.await(job.id) } }
        assertEquals("Chord models ready · 0.8 MB", detail(over))
        assertEquals("Asking GitHub for the chord models…", said.first())
        assertTrue(said.all { it == "Asking GitHub for the chord models…" || it.startsWith("Downloading the chord models · ") ||
                              it == "Checking the chord models…" }, "$said")
    }

    // --- one at a time ------------------------------------------------------------------------------------------------

    @Test fun aSecondRequestWhileOneWaitsOrRunsIsAnsweredByThatOne() {
        served()
        val phone = phone()
        val gate = CompletableDeferred<Unit>()
        github.routes[blobPath] = { runBlocking { gate.await() }; Reply(200, weights) }
        val first = phone.queue.submit(phone.runner.spec()).first
        runBlocking { withTimeout(30_000) { while (phone.queue.job(first.id)!!.state != Job.RUNNING) Thread.sleep(5) } }
        val (second, made) = phone.queue.submit(phone.runner.spec())
        assertEquals(first.id, second.id)
        assertFalse(made)
        // Removing them while the download runs is refused, and leaves what it writes alone.
        assertEquals(ModelsRunner.IN_USE, phone.runner.remove())
        gate.complete(Unit)
        runBlocking { withTimeout(30_000) { phone.queue.await(first.id) } }
        assertNull(phone.runner.ready())
    }

    // --- the waits ----------------------------------------------------------------------------------------------------

    /** On a metered network, nothing is asked: the kind's second way to end, a wait for the go-ahead given in
     * Settings, the catalogues' rule and words; the go-ahead, a job of its own key, downloads whatever the network. */
    @Test fun aMeteredNetworkWaitsForTheGoAheadAndTheGoAheadDownloads() {
        served()
        metered = true
        val phone = phone()
        val waiting = run(phone)
        assertEquals("0.8 MB to download: waiting for your go-ahead in Settings (a metered network)", detail(waiting))
        assertEquals(Line("waiting", detail(waiting), details = "#tab=requests&job=${waiting.id}"), JobViews.line(waiting))
        assertEquals(emptyList(), github.asked)
        assertNull(phone.kv(ModelsRunner.INSTALLED))
        val go = phone.runner.spec(meteredOk = true)
        assertEquals("models:go", go.key)
        val done = run(phone, meteredOk = true)
        assertEquals("Chord models ready · 0.8 MB", detail(done))
        assertNull(phone.runner.ready())
    }

    /** The metered wait's size, and the row's, is what is left to download: a file a fetch that failed kept whole
     * beside the folder (`.c1.kept`) is never counted (nor the app's own graph); one kept short, or changed, is. */
    @Test fun theMeteredWaitCountsWhatIsLeftToDownloadNeverAFileKeptWhole() {
        metered = true
        val phone = phone()
        assertEquals(800_000L, phone.runner.toDownload())
        val kept = File(phone.folder.parentFile, "." + phone.folder.name + ModelFiles.KEPT).apply { mkdirs() }
        File(kept, "beat_this-final0-fp16.onnx").writeBytes(beats)
        File(kept, "btc_model_large_voca.pt").writeBytes(weights.copyOf(1000))
        assertEquals(300_000L, phone.runner.toDownload())
        assertEquals("0.3 MB to download: waiting for your go-ahead in Settings (a metered network)", detail(run(phone)))
        assertEquals(emptyList(), github.asked)
        assertNull(phone(null).runner.toDownload(), "a build that carries none")
    }

    /** GitHub's hour spent is a wait with its time, never a failure: kept in kv models:not-before, and nothing asked
     * before it; a time further ahead than two hours (a clock that was wrong) passed over. */
    @Test fun githubsHourSpentIsAWaitWithItsTimeAndNothingIsAskedBeforeIt() {
        served()
        val reset = now.plusSeconds(1800)
        github.route(listPath, Reply(403, headers = mapOf("x-ratelimit-remaining" to "0",
                                                          "x-ratelimit-reset" to "${reset.epochSecond}")))
        val phone = phone()
        val limited = run(phone)
        val words = Limited(reset).message!!
        assertEquals(Job.DONE, limited.state)
        assertEquals(words, detail(limited))
        assertEquals(Line("waiting", words, details = "#tab=requests&job=${limited.id}"), JobViews.line(limited))
        assertTrue(PhoneKinds.MODELS.waits(words))
        assertEquals(Stamps.of(reset), phone.kv(ModelsRunner.NOT_BEFORE))
        assertEquals(listOf(listPath), asked())
        // Before that time: the same wait, no request.
        served()
        github.asked.clear()
        now = now.plusSeconds(600)
        assertEquals(words, detail(run(phone)))
        assertEquals(emptyList(), github.asked)
        // After it: asked.
        now = reset.plusSeconds(1)
        assertEquals("Chord models ready · 0.8 MB", detail(run(phone)))
        // A time too far ahead is passed over.
        phone.runner.remove()
        phone.database.writeBlocking { it.kvSet(ModelsRunner.NOT_BEFORE, Stamps.of(now.plusSeconds(3 * 3600))) }
        github.asked.clear()
        assertEquals("Chord models ready · 0.8 MB", detail(run(phone)))
        assertEquals(listOf(listPath, assetPath, "/assets/9", blobPath), asked())
    }

    @Test fun eachRefusalOfTheDownloadIsAFailureInItsOwnWords() {
        val phone = phone()
        github.route(blobPath, Reply(200, weights))
        val failed = run(phone)
        val line = "Not downloaded: The chord models aren't published yet: caracole's GitHub release “models” isn't there."
        assertEquals(Job.FAILED, failed.state)
        assertEquals(line, detail(failed))
        assertEquals(Line("failed", line, details = "#tab=requests&job=${failed.id}"), JobViews.line(failed))
        assertNull(phone.kv(ModelsRunner.INSTALLED))
        assertEquals("The chord models aren't on the phone.", phone.runner.ready())

        // A plain 403 (GitHub's secondary limit, a block): a failure, Try again later, no time kept.
        val blocked = phone()
        github.route(listPath, Reply(403))
        val refused = run(blocked)
        val words = "Not downloaded: GitHub answered HTTP 403. Try again later."
        assertEquals(Job.FAILED, refused.state)
        assertEquals(words, detail(refused))
        // The Journal's line, its first sentence (Status's cut of a failure), as every failure says it.
        assertEquals(Line("failed", "Not downloaded: GitHub answered HTTP 403.", details = "#tab=requests&job=${refused.id}"),
                     JobViews.line(refused))
        assertNull(blocked.kv(ModelsRunner.NOT_BEFORE))
        assertNull(blocked.kv(ModelsRunner.INSTALLED))
    }

    /** GitHub's hour spent on BTC's blob after beat_this's file came in whole: a wait with its time, beat_this's file
     * kept beside the folder for the next try, which asks for BTC's alone. */
    @Test fun theHourSpentAfterBeatThisCameInIsAWaitThatKeepsBeatThisForTheNextTry() {
        served()
        val reset = now.plusSeconds(1800)
        github.route(blobPath, Reply(429, headers = mapOf("x-ratelimit-remaining" to "0",
                                                          "x-ratelimit-reset" to "${reset.epochSecond}")))
        val phone = phone()
        val limited = run(phone)
        val words = Limited(reset).message!!
        assertEquals(Job.DONE, limited.state)
        assertEquals(words, detail(limited))
        assertEquals(Line("waiting", words, details = "#tab=requests&job=${limited.id}"), JobViews.line(limited))
        assertEquals(Stamps.of(reset), phone.kv(ModelsRunner.NOT_BEFORE))
        assertEquals(listOf(listPath, assetPath, "/assets/9", blobPath), asked())
        val kept = File(phone.folder.parentFile, ".c1" + ModelFiles.KEPT)
        assertEquals(listOf("beat_this-final0-fp16.onnx"), kept.list()!!.sorted())
        assertEquals(FakeGitHub.sha256(beats), ModelFiles.sha256(File(kept, "beat_this-final0-fp16.onnx")))
        // Past its time: beat_this's file taken from what was kept, BTC's asked for.
        github.route(blobPath, Reply(200, weights))
        github.asked.clear()
        now = reset.plusSeconds(1)
        assertEquals("Chord models ready · 0.8 MB", detail(run(phone)))
        assertFalse("/assets/9" in asked())
        assertTrue(blobPath in asked())
        assertNull(phone.runner.ready())
    }

    // --- a build without the models -----------------------------------------------------------------------------------

    /** The release build carries no models.json: the job is offered all the same and refuses in plain words, with no
     * request and nothing written; ready() says so too. Asked of ModelFiles.carried(), never caught. */
    @Test fun aBuildWithoutTheModelsSaysSoAndAsksNothing() {
        val phone = phone(source = null)
        assertNull(phone.runner.folder())
        assertEquals(ModelsNotCarried().message, ModelsRunner.NOT_CARRIED)
        assertEquals(ModelsRunner.NOT_CARRIED, phone.runner.ready())
        val job = run(phone)
        assertEquals(Job.FAILED, job.state)
        assertEquals("Not downloaded: This build carries no chord models.", detail(job))
        assertEquals(emptyList(), github.asked)
        assertFalse(File(phone.stateDir, ModelFiles.FOLDER).exists())
        assertEquals(ModelsRunner.NOT_CARRIED, phone.runner.remove())
    }

    // --- remove() -----------------------------------------------------------------------------------------------------

    /** Remove: every contract's folder, the files kept for a next try and what a fetch cut off left, then the record;
     * never a path outside `stateDir/models/`, nor through a link; the not-before time kept (politeness). */
    @Test fun removeDeletesEveryContractsFilesAndTheRecordAndNothingElse() {
        served()
        val phone = phone()
        run(phone)
        val models = File(phone.stateDir, ModelFiles.FOLDER)
        File(models, "c0").mkdirs().also { File(models, "c0/old.onnx").writeText("an older contract's") }
        File(models, ".c0.kept").mkdirs().also { File(models, ".c0.kept/beats.onnx").writeText("kept") }
        File(models, ".c1.kept").mkdirs()
        File(models, ".c1-0123456789abcdef.part").mkdirs()
        val outside = File(phone.stateDir, "precious").apply { mkdirs() }
        File(outside, "keep.txt").writeText("not the models'")
        Files.createSymbolicLink(File(models, "c2").toPath(), outside.toPath())
        phone.database.writeBlocking { it.kvSet(ModelsRunner.NOT_BEFORE, "2026-11-27T13:00:00Z") }
        assertNull(phone.runner.remove())
        assertFalse(models.exists())
        assertEquals("not the models'", File(outside, "keep.txt").readText())
        assertNull(phone.kv(ModelsRunner.INSTALLED))
        assertEquals("2026-11-27T13:00:00Z", phone.kv(ModelsRunner.NOT_BEFORE))
        assertEquals("The chord models aren't on the phone.", phone.runner.ready())
        assertNull(phone.runner.remove())  // nothing there: removed all the same
    }

    @Test fun removeIsRefusedWhileTheDownloadWaitsInTheQueue() {
        served()
        val phone = phone()
        val gate = CompletableDeferred<Unit>()
        val blocker = phone.queue.submit(JobSpec("Hold", "hold", "add", emptyList()) { gate.await() }).first
        val waiting = phone.queue.submit(phone.runner.spec()).first
        assertEquals(Job.QUEUED, phone.queue.job(waiting.id)!!.state)
        assertEquals(ModelsRunner.IN_USE, phone.runner.remove())
        gate.complete(Unit)
        runBlocking { withTimeout(30_000) { phone.queue.await(blocker.id); phone.queue.await(waiting.id) } }
    }

    /** A hearing holds the models' files ([ModelsRunner.holding], the audio job's around `ChordModels.hear`): remove
     * is refused while it does, even for a job no queue lists (one queued as remove looked), and goes once it is
     * over; a hearing that comes after a remove reads the files gone. */
    @Test fun removeIsRefusedWhileAHearingHoldsTheFiles() {
        served()
        val phone = phone()
        run(phone)
        val held = phone.runner.holding {
            assertNull(phone.runner.ready())
            assertEquals(ModelsRunner.IN_USE, phone.runner.remove())
            assertTrue(File(phone.stateDir, ModelFiles.FOLDER).exists())
            "heard"
        }
        assertEquals("heard", held)
        assertNull(phone.runner.remove())
        assertEquals("The chord models aren't on the phone.", phone.runner.holding { phone.runner.ready() })
    }

    // --- the phone's start --------------------------------------------------------------------------------------------

    /** What a download killed in its middle left is swept as the phone starts; an install a kill left aside between
     * its two renames (`.old`, no folder) is left for the next download to put back, never deleted. */
    @Test fun theStartSweepsWhatAKilledDownloadLeftButAnInstallPutAside() {
        served()
        val phone = phone()
        run(phone)
        val models = File(phone.stateDir, ModelFiles.FOLDER)
        val part = File(models, ".c1-0123456789abcdef.part").apply { mkdirs() }
        File(part, "beat_this-final0-fp16.onnx").writeBytes(beats.copyOf(100))
        phone.runner.sweep()
        assertFalse(part.exists())
        assertNull(phone.runner.ready())
        val aside = File(models, ".c1-fedcba9876543210.old")
        check(phone.folder.renameTo(aside))
        phone.runner.sweep()
        assertTrue(aside.isDirectory)
        github.asked.clear()
        assertEquals("Chord models ready · 0.8 MB", detail(run(phone)))
        assertEquals(emptyList(), github.asked)
    }

    // --- a restore ----------------------------------------------------------------------------------------------------

    @Test fun aRestoreKeepsTheModelsRecords() {
        assertTrue(OwnRecords.isOwn(ModelsRunner.INSTALLED))
        assertTrue(OwnRecords.isOwn(ModelsRunner.NOT_BEFORE))
    }
}
