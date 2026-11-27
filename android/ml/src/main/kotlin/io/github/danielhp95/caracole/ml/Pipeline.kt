package io.github.danielhp95.caracole.ml

import io.github.danielhp95.caracole.autochords.AudioUnreadable
import io.github.danielhp95.caracole.autochords.BeatsGraph
import io.github.danielhp95.caracole.autochords.Checkpoints
import io.github.danielhp95.caracole.autochords.ChordsGraph
import io.github.danielhp95.caracole.autochords.ChordsUnavailable
import io.github.danielhp95.caracole.autochords.Heard
import io.github.danielhp95.caracole.autochords.Labels
import io.github.danielhp95.caracole.autochords.Stages
import java.io.File
import java.io.IOException

/**
 * The whole hearing of an audio file (the design's §3.3), the computer's path step for step
 * (tests/helpers/autochords_reference.py), each step's answer a checkpoint ([Checkpoints], under the work folder), so
 * a hearing cut off (the `:ml` process killed) goes on from the last one whole, and no array holds the song whole
 * ([Stages]):
 *
 * 1. **pcm** ([Checkpoints.PCM]): [Decoder] (as audio.py `load_mono` decodes, at the file's rate, to a file), mixed
 *    down a block at a time ([Mixdown], librosa's `to_mono`), and, at another rate than [RATE], resampled by libsoxr HQ
 *    through its stream ([Stages.resample]): mono float32 at 22,050 Hz of soxr's own length, which beat_this reads.
 *    BTC reads librosa's length of it, `ceil(n · ratio)` ([Stages.btcSamples], librosa's `fix_length`: zeros past
 *    soxr's last sample). On the computer beat_this reads the file again itself (torchaudio, float64 mixed down and
 *    resampled): the same samples for a file at 22,050 Hz, float32's last bits else (PipelineTest's hearing.mp3 and
 *    hearing.m4a hold the whole). Its length is [Decoded.durationS], the one music.py `read_audio` states
 *    ([Checkpoints.PCM_META]), never the samples over the rate; the samples are deleted once the beats are kept;
 * 2. **chords** ([Checkpoints.CHORDS]): [Stages.chords] through BTC's graph, Harte labels spelled for the key;
 * 3. **beats** ([Checkpoints.BEATS]): [Stages.beats] through beat_this's fp16-stored graph;
 * 4. **heard** ([Checkpoints.HEARD]): [Heard] of the pcm's length, the chords in common names ([Labels.recognized],
 *    `recognize`'s), the beats.
 *
 * One model at a time ([graphs]: each opened at its stage's start and closed at its end, BTC's first, so the first
 * checkpoint after the pcm comes soonest). The steps are told to [say] as they start, in run.py's words ([STEPS]); the
 * heat ([HeatRules]) is read before each stage (waited out there, "waiting for the phone to cool") and before each
 * chunk and window batch (stopping there when critical), where [cancelled] is asked too ([Cancelled]), as it is in
 * the decode's, the mixdown's and the resample's loops and at each reading of a heat waited out. [most] caps
 * the threads the heat allows (0: none). One hearing at a time under a work folder: [hear] first sweeps what a
 * hearing cut off left there ([Checkpoints.sweep]). A file between stages that can't be moved into place is an
 * [IOException], as a full disk's is (MlProtocol's words for both). [syncFolder] forces the checkpoints' folder after
 * each rename (the platform's: [Checkpoints.syncFolder] on a JVM, MlService's `Os.fsync` on Android).
 */
class Pipeline(
    private val models: File, private val gauge: HeatGauge, private val most: Int = 0,
    private val sleep: (Long) -> Unit = Thread::sleep, private val clock: () -> Long = System::currentTimeMillis,
    private val cancelled: () -> Boolean = { false },
    private val graphs: Graphs = OrtGraphs(models),
    private val syncFolder: (File) -> Unit = Checkpoints::syncFolder,
) {
    /** The two models, each opened for its stage on so many threads. */
    interface Graphs {
        fun chords(threads: Int): ChordsGraph
        fun beats(threads: Int): BeatsGraph
    }

    /** What a hearing came to, and where its checkpoints are. */
    class Result(val heard: Heard, val points: Checkpoints)

    /** The hearing stopped by its client. */
    class Cancelled : Exception("the hearing was stopped")

    /** [audio] heard, its checkpoints in [work]'s folder for it. */
    fun hear(audio: File, work: File, say: (String) -> Unit): Result {
        if (!audio.isFile) throw AudioUnreadable("no audio file: $audio")
        Checkpoints.sweep(work)
        val points = Checkpoints.of(work, audio, syncFolder)
        points.parsed(Checkpoints.HEARD, Heard::read)?.let { return Result(it, points) }
        say(STEPS[0])
        HeatRules.start(gauge.read())?.let { throw ChordsUnavailable(it) }
        var chords = points.parsed(Checkpoints.CHORDS, Checkpoints::readChords)
        var beats = points.parsed(Checkpoints.BEATS, Checkpoints::readBeats)
        var pcm = points.parsed(Checkpoints.PCM_META, Checkpoints::readPcm)
        // The samples are wanted while a model's stage is left; the meta always (its length).
        if (pcm == null || ((chords == null || beats == null) && !points.pcmWhole(pcm))) {
            threads(say)
            pcm = pcm(audio, points)
        }
        if (chords == null) {
            say(STEPS[1])
            val threads = threads(say)
            val file = points.file(Checkpoints.PCM)
            chords = graphs.chords(threads).use { Stages.chords(file, pcm.btcSamples, it, ::check) }
            points.write(Checkpoints.CHORDS, Checkpoints.chordsJson(chords))
        }
        if (beats == null) {
            say(STEPS[2])
            val threads = threads(say)
            beats = graphs.beats(threads).use { Stages.beats(points.file(Checkpoints.PCM), it, ::check) }
            points.write(Checkpoints.BEATS, Checkpoints.beatsJson(beats.first, beats.second))
        }
        points.delete(Checkpoints.PCM)
        val heard = Heard(Heard.CONTRACT, pcm.duration, Labels.recognized(chords), beats.first, beats.second)
        points.write(Checkpoints.HEARD, heard.json())
        return Result(heard, points)
    }

    private fun check() {
        stop()
        HeatRules.check(gauge)
    }

    /** [Cancelled], once [cancelled] says so. */
    private fun stop() {
        if (cancelled()) throw Cancelled()
    }

    private fun threads(say: (String) -> Unit): Int {
        stop()
        val allowed = HeatRules.cool(gauge, sleep, clock, say, ::stop)
        return if (most > 0) minOf(most, allowed) else allowed
    }

    /** The pcm checkpoint, made again: its meta written first, the samples renamed into place last. */
    internal fun pcm(audio: File, points: Checkpoints): Checkpoints.Pcm {
        points.delete(Checkpoints.PCM)
        points.folder.mkdirs()
        val decoded = points.file(DECODED)
        val mono = points.file(MONO)
        try {
            val d = try {
                Decoder.decode(audio, decoded, ::stop)
            } catch (e: UndecodableAudio) {
                throw AudioUnreadable(e.message ?: "the audio can't be decoded", e)
            }
            val duration = d.durationS ?: throw AudioUnreadable("its length can't be read")
            if (d.channels == 1) move(decoded, mono)
            else Mixdown.mono(decoded, d.channels, mono, ::stop)
            decoded.delete()
            val frames = mono.length() / 4
            val meta: Checkpoints.Pcm
            if (d.rate == RATE) {
                meta = Checkpoints.Pcm(duration, frames, frames)
                points.write(Checkpoints.PCM_META, Checkpoints.pcmJson(meta))
                points.into(Checkpoints.PCM) { part -> move(mono, part) }
            } else {
                val resampled = points.file(RESAMPLED)
                val samples = Stages.resample(mono, d.rate, resampled, ::stop)
                mono.delete()
                meta = Checkpoints.Pcm(duration, samples, Stages.btcSamples(frames, d.rate))
                points.write(Checkpoints.PCM_META, Checkpoints.pcmJson(meta))
                points.into(Checkpoints.PCM) { part -> move(resampled, part) }
            }
            return meta
        } finally {
            decoded.delete()
            mono.delete()
        }
    }

    private fun move(from: File, to: File) {
        if (!from.renameTo(to)) throw IOException("can't move $from to $to")
    }

    companion object {
        /** BTC's and beat_this's rate (btc.py SAMPLE_RATE, beat_this's 22,050). */
        const val RATE = Stages.RATE

        /** run.py's `STEPS` that a hearing tells, as each starts. */
        val STEPS = listOf("setting up the models", "hearing the chords", "finding the beats")

        private const val DECODED = "decoded.f32"
        private const val MONO = "mono.f32"
        private const val RESAMPLED = "resampled.f32"
    }
}

/** The two graphs on ONNX Runtime, each its own [OrtModels] (BTC's; beat_this's fp16-stored file). */
class OrtGraphs(private val models: File) : Pipeline.Graphs {
    override fun chords(threads: Int): ChordsGraph = object : ChordsGraph {
        private val ort = OrtModels(models, threads)
        override val padding: Float get() = ort.padding
        override fun chords(features: FloatArray, windows: Int) = ort.chords(features, windows)
        override fun close() = ort.close()
    }

    override fun beats(threads: Int): BeatsGraph = object : BeatsGraph {
        private val ort = OrtModels(models, threads, OrtModels.BEATS_FP16)
        override fun beats(spect: FloatArray, frames: Int) = ort.beats(spect, frames)
        override fun close() = ort.close()
    }
}
