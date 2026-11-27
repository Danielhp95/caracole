package io.github.danielhp95.caracole

import android.content.Context
import io.github.danielhp95.caracole.ml.BenchReport
import io.github.danielhp95.caracole.ml.EndToEnd
import io.github.danielhp95.caracole.ml.HeardSong
import io.github.danielhp95.caracole.ml.MlChordModels
import io.github.danielhp95.caracole.ml.Pipeline
import io.github.danielhp95.caracole.autochords.Checkpoints
import java.io.File
import kotlinx.serialization.json.JsonObject

/**
 * The Chords bench's whole-pipeline mode (Gate B1, the design's §4.2 and §9.1): each song of a [folder] in the app's
 * own storage (its audio files, the computer's hearing of each, `<stem>.hearing.json`, and their `meta.json`: what
 * tests/helpers/autochords_reference.py `--hearings` writes) heard whole by [Pipeline] through [MlChordModels], the
 * real process boundary, a fresh `:ml` process a song and no checkpoint kept from before, each stage timed, the `:ml`
 * process's peak RSS read, and scored by [EndToEnd] against the computer's hearing, its thresholds the meta's; the
 * report's `hearings` member ([BenchReport.hearings]). A record finds its audio by its name, else by its bytes'
 * SHA-256, so the owner's songs may keep their own names on the phone. [BenchService] copies the owner's folder there;
 * ChordsBenchTest gives it the committed hearing files.
 */
internal object BenchHearings {
    const val META = "meta.json"
    const val HEARING = ".hearing.json"

    /** The subfolder of the owner's bench folder that holds the hearings. */
    const val FOLDER = "hearings"
    val AUDIO = setOf("wav", "flac", "mp3", "ogg", "opus", "m4a", "aac", "aiff", "aif")

    fun isAudio(name: String) = name.substringAfterLast('.', "").lowercase() in AUDIO

    fun run(context: Context, models: File, folder: File, say: (String) -> Unit,
            stopped: () -> Boolean = { false }): JsonObject {
        val gates = EndToEnd.Gates.of(File(folder, META).readText(Charsets.UTF_8))
        val records = folder.listFiles().orEmpty().filter { it.name.endsWith(HEARING) }.sortedBy { it.name }
            .map { EndToEnd.Hearing.read(it.readText(Charsets.UTF_8)) }
        val audio = folder.listFiles().orEmpty().filter { it.isFile && isAudio(it.name) }.sortedBy { it.name }
        val shas by lazy { audio.associateWith { MlChordModels.sha256(it) } }
        val work = File(context.applicationContext.noBackupFilesDir, "bench-hearing-work")
        val heard = mutableListOf<HeardSong>()
        val unmatched = mutableListOf<String>()
        val matched = mutableSetOf<File>()
        for (record in records) {
            val file = audio.firstOrNull { it.name == record.name }
                ?: record.sha256?.let { sha -> audio.firstOrNull { shas[it] == sha } }
            if (file == null) {
                unmatched += "the hearing of ${record.name}: no audio file of its"
                continue
            }
            matched += file
            if (stopped()) {
                heard += HeardSong(file.name, null, emptyMap(), null, null, "stopped before it was heard")
                continue
            }
            say("hearing ${file.name} whole…")
            work.deleteRecursively()
            val chords = MlChordModels(context, models, work)
            val started = System.nanoTime()
            val song = try {
                val result = chords.hear(file, {}, {})
                val seconds = (System.nanoTime() - started) / 1e9
                val points = chords.checkpoints(file)
                val scored = EndToEnd.score(record, Checkpoints.readChords(points.read(Checkpoints.CHORDS)!!), result,
                    Checkpoints.readPcm(points.read(Checkpoints.PCM_META)!!), gates)
                HeardSong(file.name, seconds, chords.lastStagesNanos, chords.lastPeakKb, scored)
            } catch (e: Exception) {
                HeardSong(file.name, null, emptyMap(), chords.lastPeakKb, null,
                    "${e.javaClass.simpleName}: ${e.message}")
            }
            heard += song
            say("${file.name}: " + (song.scored?.let { s ->
                "${if (s.pass(gates)) "passes" else "fails: " + s.failures(gates).joinToString("; ")}; " +
                    "${"%.1f".format(song.seconds)} s (" + Pipeline.STAGES.mapNotNull { st ->
                    song.stagesNanos[st]?.let { "$st ${"%.1f".format(it / 1e9)} s" }
                }.joinToString() + "), :ml's peak ${song.peakKb?.let { it / 1024 }} MB"
            } ?: "not heard: ${song.failure}"))
        }
        work.deleteRecursively()
        for (file in audio - matched) unmatched += "${file.name}: no hearing of it"
        return BenchReport.hearings(heard, gates, unmatched)
    }
}
