package io.github.danielhp95.caracole.server.lookups

import io.github.danielhp95.caracole.core.db.Database
import io.github.danielhp95.caracole.core.index.Stamps
import io.github.danielhp95.caracole.core.library.AudioStore
import io.github.danielhp95.caracole.core.library.Kept
import io.github.danielhp95.caracole.core.library.Songs
import io.github.danielhp95.caracole.core.library.Versions
import io.github.danielhp95.caracole.core.lookup.LookupWords
import io.github.danielhp95.caracole.core.testing.Corpus
import io.github.danielhp95.caracole.core.testing.TestDb
import io.github.danielhp95.caracole.server.PhoneParts
import io.github.danielhp95.caracole.server.jobs.CommandRunner
import io.github.danielhp95.caracole.server.jobs.Commands
import io.github.danielhp95.caracole.server.jobs.Job
import io.github.danielhp95.caracole.server.jobs.JobCommands
import io.github.danielhp95.caracole.server.jobs.JobQueue
import io.github.danielhp95.caracole.server.jobs.JobSpec
import io.github.danielhp95.caracole.server.page.LibraryPage
import io.github.danielhp95.caracole.server.testing.TestParts
import io.github.danielhp95.caracole.server.testing.replays.AudioSheetReplay
import io.github.danielhp95.caracole.viewer.autochords.AudioUnreadable
import io.github.danielhp95.caracole.viewer.autochords.ChordModels
import io.github.danielhp95.caracole.viewer.autochords.ChordSegment
import io.github.danielhp95.caracole.viewer.autochords.ChordsUnavailable
import io.github.danielhp95.caracole.viewer.autochords.Heard
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.withTimeout
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import org.junit.After
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import java.io.File
import java.util.Base64
import java.util.concurrent.CopyOnWriteArrayList
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertNull
import kotlin.test.assertTrue

/** `caracole audio --upload` on the phone through the real queue: the refusals before any stage, a lookup queued
 * meanwhile running while the models hear, one of the job's own song waiting for it, a human sheet kept meanwhile
 * ending the job as a refusal, and the hearing's failures told apart. The replay (AudioSheetReplayTest) holds the
 * stages to Python's; here what only the phone does. The upload is the vector's own staged M4A, the song's lyrics
 * instrumental, so that no site is asked. */
class AudioRunnerTest {
    @get:Rule val tmp = TemporaryFolder()

    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
    private val opened = mutableListOf<Database>()

    @After fun close() {
        scope.cancel()
        opened.forEach { it.close() }
    }

    private val display = "Calla Lake - River Road"

    /** The examiner's read, a test's to make fail. */
    private var examine: (File, String) -> AudioStore.Audio = { _, _ -> AudioStore.Audio("M4A", 213.0, emptyMap()) }

    /** The vector's staged upload (its record and its M4A), the same bytes the computer's job kept. */
    private val upload = "0000000000000001"
    private val staged: Map<String, ByteArray> by lazy {
        val record = Corpus.lines(AudioSheetReplay.VECTOR).first { it["header"] != JsonPrimitive(true) }
        record.getValue("kw").jsonObject.getValue("store").jsonObject.mapValues { (_, spec) ->
            val o = spec.jsonObject
            o["text"]?.jsonPrimitive?.content?.toByteArray() ?: Base64.getDecoder().decode(o.getValue("base64").jsonPrimitive.content)
        }
    }

    private class Phone(val parts: PhoneParts, val queue: JobQueue, val store: AudioStore, val database: Database,
                        val runners: MutableMap<String, CommandRunner>)

    private fun phone(): Phone {
        val dir = tmp.newFolder()
        val database = TestDb.fresh(dir).also { opened += it }
        val runners = HashMap<String, CommandRunner>()
        val queue = JobQueue(scope, commands = Commands(runners))
        val parts = TestParts.of(database, dir, scope, queue)
        val root = File(parts.stateDir, AudioStore.FOLDER).apply { mkdirs() }
        for ((name, bytes) in staged) File(root, name).writeBytes(bytes)
        val store = AudioStore(parts.stateDir, { file, format -> examine(file, format) })
        database.writeBlocking { db ->
            val song = parts.store.add(db, "Calla Lake", "River Road", now = Stamps.now())
            Versions.updateSong(db, song.id, mapOf("lyrics_status" to "instrumental"))
        }
        return Phone(parts, queue, store, database, runners)
    }

    private val heard = Heard(1, 213.0, listOf(ChordSegment(0.0, 10.0, "Am"), ChordSegment(10.0, 20.0, "F")),
                              (0..40).map { it * 0.5 }, (0..10).map { it * 2.0 })

    /** Models that answer [heard], calling [during] once they start (the job's thread, no write held) and [waiting]
     * as the real ones do. */
    private open inner class Models(private val during: (() -> Unit) -> Unit = { it() }) : ChordModels {
        val heardOf = CopyOnWriteArrayList<File>()
        override fun ready(): String? = null
        override fun hear(audio: File, onStep: (String) -> Unit, waiting: () -> Unit): Heard {
            heardOf += audio
            onStep("setting up the models")
            during(waiting)
            onStep("hearing the chords")
            return heard
        }
    }

    private fun spec(key: String = JobCommands.AUDIO_SHEET + "calla-lake/river-road"): JobSpec {
        val commands = JobCommands.audioSheetSteps(display, upload)
        return JobSpec("Sheet from an audio file: $display", key, "song", JobCommands.stages(commands.map { it.args }),
                       display = display, commands = commands)
    }

    private fun run(phone: Phone, runner: AudioRunner): Job = runBlocking {
        phone.runners[AudioRunner.COMMAND] = runner
        val job = phone.queue.submit(spec()).first
        withTimeout(60_000) { phone.queue.await(job.id) }
    }

    private fun ends(job: Job): Map<String, Pair<String, String>> = job.stages.associate { it.name to (it.state to it.detail) }

    private fun autoSheet(phone: Phone): Boolean = phone.database.read { db ->
        Kept.keptFiles(db, Songs.byKey(db, "calla-lake/river-road")!!.id).any { it.name == "sheet (auto).txt" }
    }

    // --- before any stage ---------------------------------------------------------------------------------------------

    @Test fun aPhoneWithNoWayToHearRefusesBeforeAnythingIsKept() {
        val phone = phone()
        val job = run(phone, AudioRunner(phone.parts, null, phone.store))
        assertEquals(Job.FAILED, job.state)
        assertEquals(listOf("error: caracole makes no sheet from an audio file here: ${LibraryPage.AUDIO_PROBLEM}"),
                     job.steps.single().output)
        assertTrue(job.stages.none { it.state == Job.DONE || it.detail.isNotEmpty() }, "${ends(job)}")
        assertFalse(phone.store.gone(upload))  // still staged
    }

    @Test fun chordModelsNotDownloadedAreARefusalThatSaysWhereToDownloadThem() {
        val phone = phone()
        val models = Models()
        val job = run(phone, AudioRunner(phone.parts, models, phone.store,
                                         problem = { AudioRunner.problemOf(models, "The chord models aren't on the phone.") }))
        assertEquals(Job.FAILED, job.state)
        assertEquals("error: caracole makes no sheet from an audio file here: the chord models aren't downloaded " +
                         "(Settings › Chords from audio)", job.steps.single().output.single())
        assertTrue(models.heardOf.isEmpty())
        assertFalse(phone.store.gone(upload))
    }

    /** One answer, the job's and the routes' (Phone.audioProblem): no chords, the models' not downloaded, else the
     * chords' own reason (design §8.1), never the models' words for a reason that isn't theirs. */
    @Test fun eachReasonNotToHearIsSaidAsItIs() {
        val older = object : Models() {
            override fun ready(): String = "chords from audio need Android 13 or later"
        }
        assertEquals(LibraryPage.AUDIO_PROBLEM, AudioRunner.problemOf(null, "The chord models aren't on the phone."))
        assertEquals(AudioRunner.NOT_DOWNLOADED, AudioRunner.problemOf(older, "The chord models aren't on the phone."))
        assertEquals("chords from audio need Android 13 or later", AudioRunner.problemOf(older, null))
        assertNull(AudioRunner.problemOf(Models(), null))
        val phone = phone()
        val job = run(phone, AudioRunner(phone.parts, older, phone.store, problem = { AudioRunner.problemOf(older, null) }))
        assertEquals("error: caracole makes no sheet from an audio file here: chords from audio need Android 13 or later",
                     job.steps.single().output.single())
        assertTrue(older.heardOf.isEmpty())
        assertFalse(phone.store.gone(upload))
    }

    /** A phone that can't hear chords whatever the files (an x86_64 release, Android 12, under 6 GB) is told its own
     * reason before "aren't downloaded": Settings offers it no download to make. */
    @Test fun thePhonesOwnProblemComesBeforeTheModelsNotDownloaded() {
        val x86 = object : Models() {
            override fun ready(): String = "no chord models for this phone's processor"
            override fun phoneProblem(): String = "no chord models for this phone's processor"
        }
        assertEquals("no chord models for this phone's processor",
                     AudioRunner.problemOf(x86, "The chord models aren't on the phone."))
        val phone = phone()
        val job = run(phone, AudioRunner(phone.parts, x86, phone.store,
                                         problem = { AudioRunner.problemOf(x86, "The chord models aren't on the phone.") }))
        assertEquals("error: caracole makes no sheet from an audio file here: no chord models for this phone's processor",
                     job.steps.single().output.single())
        assertTrue(x86.heardOf.isEmpty())
    }

    /** commands/audio.py's OSError reading the file before any stage: exit 1, "can't read …", never a bug. */
    @Test fun theKeptFileUnreadableBeforeAnyStageExitsOneInWords() {
        val phone = phone()
        assertEquals(Job.DONE, run(phone, AudioRunner(phone.parts, Models(), phone.store, problem = { null })).state)
        examine = { _, _ -> throw java.io.IOException("Input/output error") }
        val again = run(phone, AudioRunner(phone.parts, Models(), phone.store, problem = { null }))
        assertEquals(Job.FAILED, again.state)
        assertEquals(1, again.steps.single().code)
        assertEquals("error: can't read the upload: Input/output error", again.steps.single().output.single())
    }

    /** info.json failing once the sheet is kept: the stage says the sheet was kept, and the song is made of this
     * audio (its autochords_mtime set), so the next job doesn't hear it again. */
    @Test fun infoJsonFailingAfterTheKeepSaysTheSheetWasKept() {
        val phone = phone()
        File(phone.parts.store.libraryDir, "Calla Lake/River Road/info.json").mkdirs()  // a folder where it goes
        val job = run(phone, AudioRunner(phone.parts, Models(), phone.store, problem = { null }))
        assertEquals(Job.FAILED, job.state)
        val (state, said) = ends(job).getValue("chords")
        assertEquals(Job.FAILED, state)
        assertTrue(said.startsWith("the sheet was kept (chords only, no lyrics), but its info.json couldn't be written: "),
                   said)
        assertTrue(autoSheet(phone))
        // A sheet was kept: the later stages go by it, never by the chords stage's state (its pages made, the sheet
        // announced readable).
        assertEquals(Job.SKIPPED to LookupWords.NO_PDFS, ends(job)["pdf"])
        assertEquals("done" to LookupWords.LIBRARY_PAGE, ends(job)["pages"])
        assertEquals("Calla Lake/River Road/sheet (auto).txt", job.files["sheet"])
        val song = phone.database.read { db -> Songs.byKey(db, "calla-lake/river-road")!! }
        assertEquals(song.audioMtime, song.autochordsMtime)
        val models = Models()
        val again = run(phone, AudioRunner(phone.parts, models, phone.store, problem = { null }))
        assertEquals("done" to "up to date: chords only, no lyrics", ends(again)["chords"])
        assertTrue(models.heardOf.isEmpty())
    }

    /** The queue stopped while the models hear: what `waiting` throws propagates as itself (ChordModels' contract),
     * the job ends as the queue's stop, its audio kept and no sheet written. */
    @Test fun aStopMidHearingEndsTheJobAsTheQueuesStop() {
        val phone = phone()
        val models = Models { waiting ->
            scope.cancel()  // the queue's stop, as the app's process ends
            waiting()
        }
        val job = run(phone, AudioRunner(phone.parts, models, phone.store, problem = { null }))
        assertEquals(Job.INTERRUPTED, job.state)
        assertFalse(autoSheet(phone))
        val song = phone.database.read { db -> Songs.byKey(db, "calla-lake/river-road")!! }
        assertTrue(phone.store.uploaded(song)?.isFile == true, "the audio kept")
    }

    @Test fun anUploadGoneWithNoMarkerIsRefusedInTheStoresWords() {
        val phone = phone()
        phone.store.drop(upload)
        val job = run(phone, AudioRunner(phone.parts, Models(), phone.store, problem = { null }))
        assertEquals(Job.FAILED, job.state)
        assertEquals("error: " + AudioStore.WORDS.getValue("gone"), job.steps.single().output.single())
        assertEquals(1, job.steps.single().code)
    }

    // --- the whole way, and lookups going first ----------------------------------------------------------------------

    /** The design's §3.2: while the models run the job holds no write, and a lookup queued meanwhile runs there, in
     * the job's stead; one of the job's own song waits until the job ends (a song never has two jobs running). */
    @Test fun aLookupQueuedMeanwhileRunsWhileTheModelsDo() {
        val phone = phone()
        val log = CopyOnWriteArrayList<String>()
        phone.runners["get"] = CommandRunner { args, _ ->
            phone.database.writeBlocking { }  // a lookup writes: no write of the job's is held
            log += "get ${args.last()}"
        }
        val models = Models { waiting ->
            runBlocking {
                phone.queue.submit(JobSpec("Get Harbour Lights - Paper Boats", "harbour-lights/paper-boats", "song",
                                           emptyList(), commands = JobCommands.lookupSteps("Harbour Lights", "Paper Boats"),
                                           fetching = true))
                phone.queue.submit(JobSpec("Get $display", "calla-lake/river-road", "song", emptyList(),
                                           commands = JobCommands.lookupSteps("Calla Lake", "River Road"), fetching = true))
            }
            log += "hearing"
            waiting()
            log += "heard"
        }
        val job = run(phone, AudioRunner(phone.parts, models, phone.store, problem = { null }))
        assertEquals(Job.DONE, job.state, "${job.steps.single().output}")
        assertEquals(listOf("hearing", "get Paper Boats", "heard"), log.take(3))
        runBlocking { withTimeout(30_000) { while (log.size < 4) kotlinx.coroutines.delay(10) } }
        assertEquals("get River Road", log[3])  // the job's own song's, once the job was over
        val ends = ends(job)
        assertEquals("done" to "kept as its audio: M4A, 3:33", ends["audio"])
        assertEquals("skipped" to "not transcribed: its lyrics are instrumental", ends["vocals"])
        assertEquals("done" to "chords only, no lyrics", ends["chords"])
        assertTrue(autoSheet(phone))
        val raw = phone.database.read { db -> Versions.get(db, 1)!!.raw }
        assertEquals(JsonPrimitive("phone"), raw["made_on"])
        assertEquals(JsonPrimitive("river road.m4a"), raw["audio_name"])
    }

    /** The acceptance: a song given a human sheet while the models ran ends the job as a refusal, in the computer's
     * words, and no auto sheet is kept. The sheet is written from the fake models' own callback: under the yield rule
     * only another song's lookups run during a yield and no sync or removal runs mid-job, so in practice the guard is
     * reached only through a re-key or merge another song's lookup makes; it is kept, as the computer's is. */
    @Test fun aSongGivenAHumanSheetMeanwhileEndsTheJobAsARefusal() {
        val phone = phone()
        val models = Models { waiting ->
            phone.database.writeBlocking { db ->
                val song = Songs.byKey(db, "calla-lake/river-road")!!
                val id = Versions.upsert(db, "ug", "101", song.id, "sheet", "chords", 4.8, 120, 1, null,
                                         "https://tabs.ultimate-guitar.com/tab/x", kotlinx.serialization.json.JsonObject(emptyMap()),
                                         Stamps.now())
                Kept.keepFile(db, phone.parts.store, song, id, "sheet.txt", "[ch]G[/ch]\nHi".toByteArray(), 1, Stamps.now())
            }
            waiting()
        }
        val job = run(phone, AudioRunner(phone.parts, models, phone.store, problem = { null }))
        assertEquals(Job.FAILED, job.state)
        val ends = ends(job)
        assertEquals(Job.FAILED to "$display already has a sheet", ends["song"])
        assertEquals(Job.SKIPPED to "", ends["chords"])
        assertEquals("No sheet made: $display already has a sheet.", job.steps.single().output.last().removePrefix("error: "))
        assertFalse(autoSheet(phone))
    }

    // --- failures told apart -----------------------------------------------------------------------------------------

    @Test fun eachFailureOfTheHearingIsSaidInItsOwnWordsAndRecordsNothing() {
        for ((thrown, said) in listOf(
            AudioUnreadable("MediaExtractor can't read the file") to "audio the phone can't read: MediaExtractor can't read the file",
            ChordsUnavailable("the phone is too hot to work out chords now; try again once it cools") to
                "the phone is too hot to work out chords now; try again once it cools",
        )) {
            val phone = phone()
            val models = object : Models() {
                override fun hear(audio: File, onStep: (String) -> Unit, waiting: () -> Unit): Heard = throw thrown
            }
            val job = run(phone, AudioRunner(phone.parts, models, phone.store, problem = { null }))
            assertEquals(Job.FAILED, job.state)
            assertEquals(Job.FAILED to said, ends(job)["chords"])
            assertEquals(Job.SKIPPED to "no sheet", ends(job)["pdf"])
            assertEquals(1, job.steps.single().code)
            assertFalse(autoSheet(phone))
            assertNull(phone.database.read { it.kvGet("autochords:failed:1") })
        }
        // A bug laying the sheet out: caracole's, said so.
        val phone = phone()
        val job = run(phone, AudioRunner(phone.parts, Models(), phone.store, problem = { null },
                                         names = { throw IllegalStateException("no names") }))
        assertEquals(Job.FAILED to "a bug in caracole: IllegalStateException: no names", ends(job)["chords"])
        assertEquals(1, job.steps.single().code)
        assertFalse(autoSheet(phone))
    }

    /** The models' checkpoints (the design's §3.3) go once the sheet is kept, never before: a keep that fails leaves
     * them, and the job tried again lays the sheet out from them with no hearing, then lets them go. */
    @Test fun aKeepThatFailsLeavesTheCheckpointsAndTheNextJobHearsNothingAgain() {
        val phone = phone()
        val models = object : Models() {
            val kept = HashMap<String, Heard>()
            var heardWhole = 0
            val forgotten = CopyOnWriteArrayList<File>()
            override fun hear(audio: File, onStep: (String) -> Unit, waiting: () -> Unit): Heard =
                kept[audio.path] ?: super.hear(audio, onStep, waiting).also { heardWhole++; kept[audio.path] = it }
            override fun forget(audio: File) {
                forgotten += audio
                kept.remove(audio.path)
            }
        }
        var names: () -> Map<String, String> = { throw IllegalStateException("no names") }
        val failed = run(phone, AudioRunner(phone.parts, models, phone.store, problem = { null }, names = { names() }))
        assertEquals(Job.FAILED to "a bug in caracole: IllegalStateException: no names", ends(failed)["chords"])
        assertEquals(1, models.heardWhole)
        assertTrue(models.forgotten.isEmpty())
        assertEquals(1, models.kept.size)
        names = { emptyMap() }
        val again = run(phone, AudioRunner(phone.parts, models, phone.store, problem = { null }, names = { names() }))
        assertEquals(Job.DONE, again.state, "${ends(again)}")
        assertEquals(1, models.heardWhole, "laid out from the checkpoints, never heard again")
        assertTrue(autoSheet(phone))
        val song = phone.database.read { db -> Songs.byKey(db, "calla-lake/river-road")!! }
        assertEquals(listOf(phone.store.uploaded(song)!!), models.forgotten)
        assertTrue(models.kept.isEmpty())
    }

    /** The song's `autochords_mtime`, the last write of a keep (run.py `_keep`'s order), failing after the sheet was
     * kept: the checkpoints stay, as for any keep that fails, so that Try again, which finds the sheet of no audio
     * yet, lays it out from them with no hearing. */
    @Test fun aKeepWhoseLastWriteFailsLeavesTheCheckpoints() {
        val phone = phone()
        val models = object : Models() {
            var heardWhole = 0
            val kept = HashMap<String, Heard>()
            val forgotten = CopyOnWriteArrayList<File>()
            override fun hear(audio: File, onStep: (String) -> Unit, waiting: () -> Unit): Heard =
                kept[audio.path] ?: super.hear(audio, onStep, waiting).also { heardWhole++; kept[audio.path] = it }
            override fun forget(audio: File) {
                forgotten += audio
                kept.remove(audio.path)
            }
        }
        phone.database.writeBlocking { db ->
            db.execute("CREATE TRIGGER no_mtime BEFORE UPDATE OF autochords_mtime ON songs " +
                           "WHEN NEW.autochords_mtime IS NOT NULL BEGIN SELECT RAISE(ABORT, 'no mtime'); END")
        }
        val failed = run(phone, AudioRunner(phone.parts, models, phone.store, problem = { null }))
        assertEquals(Job.FAILED, failed.state, "${ends(failed)}")
        assertTrue(models.forgotten.isEmpty(), "the checkpoints kept")
        phone.database.writeBlocking { db -> db.execute("DROP TRIGGER no_mtime") }
        val again = run(phone, AudioRunner(phone.parts, models, phone.store, problem = { null }))
        assertEquals(Job.DONE, again.state, "${ends(again)}")
        assertEquals(1, models.heardWhole, "laid out from the checkpoints, never heard again")
        assertEquals(1, models.forgotten.size)
    }

    /** The models removed after the job was queued (Settings' Remove, before the job held them): the hearing holds
     * the models' files ([AudioRunner]'s `hold`, ModelsRunner.holding) and asks again under it, so the chords stage
     * fails in the one answer's words, Try again once they are downloaded, the models never asked and nothing kept
     * but its audio. */
    @Test fun theModelsRemovedOnceTheJobWasQueuedFailItsChordsInWordsAndHearNothing() {
        val phone = phone()
        val models = Models()
        var asked = 0
        var holds = 0
        val job = run(phone, AudioRunner(phone.parts, models, phone.store,
                                         problem = { if (asked++ == 0) null else AudioRunner.NOT_DOWNLOADED },
                                         hold = { block -> holds++; block() }))
        assertEquals(Job.FAILED, job.state)
        assertEquals(Job.FAILED to AudioRunner.NOT_DOWNLOADED, ends(job)["chords"])
        assertEquals(1, holds)
        assertTrue(models.heardOf.isEmpty())
        assertFalse(autoSheet(phone))
        val song = phone.database.read { db -> Songs.byKey(db, "calla-lake/river-road")!! }
        assertTrue(phone.store.uploaded(song)?.isFile == true, "the audio kept")
    }
}
