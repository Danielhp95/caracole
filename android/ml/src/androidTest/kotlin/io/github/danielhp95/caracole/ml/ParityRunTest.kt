package io.github.danielhp95.caracole.ml

import android.media.MediaExtractor
import android.media.MediaFormat
import android.os.Build
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import io.github.danielhp95.caracole.autochords.Checkpoints
import java.io.File
import org.junit.Assert.assertTrue
import org.junit.After
import org.junit.Assume.assumeTrue
import org.junit.Test
import org.junit.runner.RunWith

/**
 * The design's B1 end-to-end gate (§4.2) over audio given at run time, outside the repository (the owner's own songs:
 * `android/scripts/device-test.sh --data DIR`, `-e data` the folder pushed): each audio file there heard whole by the
 * real [Pipeline] through [MlChordModels] (the `:ml` process; a copy in the app's own files, as the app's audio is),
 * with no checkpoint kept from before, against the computer's hearing of it beside it (`<stem>.hearing.json`,
 * tests/helpers/autochords_reference.py `--hearings`, found by its `file.name`, else by its bytes' SHA-256), every
 * threshold read from the folder's `meta.json` ([EndToEnd.Gates]), none typed here. Each file says its WCSR majmin
 * and tetrads, its beats' and downbeats' F, the samples and frames each model read and its length against the
 * computer's, the platform's encoder delay and padding and what the decoder trimmed (a decode apart, in this
 * process), where its frames part from the computer's, its time end to end and each stage's, and the `:ml` process's
 * peak RSS; then all of them over all ([EndToEnd.overAll]). It fails on any gate or length that isn't the computer's,
 * and on a record with no audio or an audio file with no record. With no `-e data` it is skipped, so the ordinary
 * `--ml` run never fails for it.
 */
@RunWith(AndroidJUnit4::class)
class ParityRunTest {
    @Test fun eachFileOfTheFolderHeardWholeMeetsB1sGatesAgainstTheComputersHearing() {
        val arguments = InstrumentationRegistry.getArguments()
        val given = arguments.getString("data")
        assumeTrue("no -e data: run it through android/scripts/device-test.sh --data DIR", given != null)
        val folder = File(given!!)
        val models = File(arguments.getString("models")
            ?: throw AssertionError("no models: run it through android/scripts/device-test.sh --data DIR"))
        val threads = arguments.getString("threads")?.toInt() ?: 0
        val gates = EndToEnd.Gates.of(File(folder, META).readText(Charsets.UTF_8))
        val hearings = folder.listFiles().orEmpty().filter { it.name.endsWith(HEARING) }.sortedBy { it.name }
            .map { EndToEnd.Hearing.read(it.readText(Charsets.UTF_8)) }
        val audio = folder.listFiles().orEmpty().filter { it.isFile && it.extension.lowercase() in AUDIO }
        assertTrue("no hearing record in $folder", hearings.isNotEmpty())
        val failures = mutableListOf<String>()
        val scored = mutableListOf<EndToEnd.Scored>()
        val matched = mutableSetOf<File>()
        PipelineTest.report("B1 over ${hearings.size} file(s): ${EndToEnd.gatesJson(gates)}")
        for (hearing in hearings) {
            val file = audio.firstOrNull { it.name == hearing.name }
                ?: hearing.sha256?.let { sha -> audio.firstOrNull { MlChordModels.sha256(it) == sha } }
            if (file == null) {
                failures += "${hearing.name}: no audio file of its in $folder"
                continue
            }
            matched += file
            // A copy of the app's own, as the app's audio is (its decoders never read the shell's folder); it and
            // its checkpoints (the pcm among them) gone whatever happens.
            val own = File(parity, file.name)
            try {
                work.deleteRecursively()
                parity.mkdirs()
                file.copyTo(own, overwrite = true)
                PipelineTest.report("${file.name}: ${decoding(own)}")
                val chords = MlChordModels(context, models, work, threads)
                val started = System.nanoTime()
                val heard = chords.hear(own, {}, {})
                val took = (System.nanoTime() - started) / 1e9
                val points = chords.checkpoints(own)
                val pcm = Checkpoints.readPcm(points.read(Checkpoints.PCM_META)!!)
                val harte = Checkpoints.readChords(points.read(Checkpoints.CHORDS)!!)
                val s = EndToEnd.score(hearing, harte, heard, pcm, gates)
                scored += s
                val stages = Pipeline.STAGES.mapNotNull { stage ->
                    chords.lastStagesNanos[stage]?.let { "$stage ${"%.1f".format(it / 1e9)} s" }
                }
                PipelineTest.report("${file.name}: ${s.line()}; ${"%.1f".format(took)} s end to end (RTF " +
                    "${"%.3f".format(took / heard.duration)}: ${stages.joinToString()}), :ml's " +
                    PipelineTest.peak(chords))
                failures += s.failures(gates).map { "${file.name}: $it" }
            } catch (e: Exception) {
                failures += "${file.name}: not heard or scored: $e"
            } finally {
                own.delete()
                work.deleteRecursively()
            }
        }
        for (file in audio - matched) failures += "${file.name}: no hearing record of it"
        PipelineTest.report("over all: ${EndToEnd.overAll(scored, gates)}")
        assertTrue(failures.joinToString("\n"), failures.isEmpty())
    }

    /** What the platform says of [audio]'s track (its extractor's `encoder-delay` and `encoder-padding`, which Decoder
     * takes out of the format before the codec sees them) and what [Decoder] made of it here (the codec, the frames it
     * trimmed first and last, the frames kept): where a decoded length parts from the computer's. */
    private fun decoding(audio: File): String {
        val extractor = MediaExtractor()
        val said = try {
            extractor.setDataSource(audio.path)
            val f = (0 until extractor.trackCount).map(extractor::getTrackFormat)
                .first { it.getString(MediaFormat.KEY_MIME).orEmpty().startsWith("audio/") }
            fun key(k: String) = if (f.containsKey(k)) f.getInteger(k).toString() else "none"
            "${f.getString(MediaFormat.KEY_MIME)} at ${key(MediaFormat.KEY_SAMPLE_RATE)} Hz, " +
                "${key(MediaFormat.KEY_CHANNEL_COUNT)} ch, the extractor's encoder-delay ${key("encoder-delay")}, " +
                "encoder-padding ${key("encoder-padding")}"
        } finally {
            extractor.release()
        }
        val pcm = File(context.cacheDir, DECODE_FILE)
        return try {
            val d = Decoder.decode(audio, pcm)
            "$said (API ${Build.VERSION.SDK_INT}); decoded by ${d.codec}, ${d.delay} frames trimmed first and " +
                "${d.padding} last, ${d.frames} frames at ${d.rate} Hz kept, stated ${d.durationS} s"
        } finally {
            pcm.delete()
        }
    }

    /** Nothing of the songs stays in this APK's storage, however a test ends: their copies, their checkpoints (the
     * 22,050 Hz pcm among them), a decode's file (device-test.sh's EXIT trap clears this APK's data too). */
    @After fun forget() {
        parity.deleteRecursively()
        File(context.filesDir, "state").deleteRecursively()
        File(context.cacheDir, DECODE_FILE).delete()
    }

    companion object {
        private val context get() = InstrumentationRegistry.getInstrumentation().targetContext
        private val parity get() = File(context.filesDir, "parity")
        private val work get() = File(context.filesDir, "state/cache/autochords")
        private const val DECODE_FILE = "parity-decode.f32"
        const val META = "meta.json"
        const val HEARING = ".hearing.json"
        val AUDIO = setOf("wav", "flac", "mp3", "ogg", "opus", "m4a", "aac", "aiff", "aif")
    }
}
