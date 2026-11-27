package io.github.danielhp95.caracole.ml

import io.github.danielhp95.caracole.autochords.AudioUnreadable
import io.github.danielhp95.caracole.autochords.Checkpoints
import io.github.danielhp95.caracole.autochords.ChordSegment
import io.github.danielhp95.caracole.autochords.ChordsUnavailable
import io.github.danielhp95.caracole.autochords.Chunks
import io.github.danielhp95.caracole.autochords.Heard
import io.github.danielhp95.caracole.autochords.Labels
import io.github.danielhp95.caracole.autochords.Peaks
import io.github.danielhp95.caracole.autochords.frontend.Cqt
import io.github.danielhp95.caracole.autochords.frontend.Mel
import io.github.danielhp95.caracole.autochords.frontend.Soxr
import java.io.File
import java.nio.ByteBuffer
import java.nio.ByteOrder
import java.nio.FloatBuffer
import java.nio.channels.FileChannel
import java.nio.file.StandardOpenOption

/**
 * The whole hearing of an audio file (the design's §3.3), the computer's path step for step
 * (tests/helpers/autochords_reference.py), each step's answer a checkpoint ([Checkpoints], under [work]), so a
 * hearing cut off (the `:ml` process killed) goes on from the last one whole:
 *
 * 1. **pcm** ([Checkpoints.PCM]): [Decoder] (as audio.py `load_mono` decodes, at the file's rate, to a file), mixed
 *    down ([Mixdown], librosa's `to_mono`), and, at another rate than [RATE], resampled by libsoxr HQ ([Soxr],
 *    python-soxr's `resample` of float32, as librosa's `soxr_hq`): mono float32 at 22,050 Hz, which BTC and beat_this
 *    both read. On the computer beat_this reads the file again itself (torchaudio, float64 mixed down and resampled):
 *    the same samples for a file at 22,050 Hz, within float32's last bits for another (the B1 decode and resample
 *    gates hold the steps; PipelineTest the whole). Its length is [Decoded.durationS], the one music.py
 *    `read_audio` states ([Checkpoints.PCM_META]), never the samples over the rate;
 * 2. **chords** ([Checkpoints.CHORDS]): btc.py `cqt_features` in its 10 s chunks ([Cqt.CHUNK], its tail rule), read
 *    a chunk at a time from the memory-mapped pcm; BTC in windows of [OrtModels.WINDOW] frames, the last padded with
 *    the features' mean ([OrtModels.padding]), [BTC_BATCH] windows a run; each frame's argmax (its first highest
 *    logit, as torch's), runs of them as segments ([Labels.framesToSegments], [Labels.vocabulary]`(170)`), spelled
 *    for the key ([Labels.spellForKey]): the Harte labels the gates compare;
 * 3. **beats** ([Checkpoints.BEATS]): beat_this's log-mel ([Mel]) of the whole pcm, its 1500-frame chunks
 *    ([Chunks], border 6) through the fp16-stored graph, and its minimal postprocessor ([Peaks]);
 * 4. **heard** ([Checkpoints.HEARD]): [Heard] of the pcm's length, the chords in common names ([Labels.recognized],
 *    `recognize`'s), the beats.
 *
 * One model at a time: each stage's [OrtModels] opened at its start and closed at its end, BTC's first, so the first
 * checkpoint after the pcm comes soonest. The steps are told to [say] as they start, in run.py's words ([STEPS]), and
 * the heat ([HeatRules]) read before each model's stage (waited out there, "waiting for the phone to cool") and before
 * each window batch and chunk (stopping there when critical). [most] caps the threads the heat allows (0: none).
 */
class Pipeline(
    private val models: File, private val gauge: HeatGauge, private val most: Int = 0,
    private val sleep: (Long) -> Unit = Thread::sleep, private val clock: () -> Long = System::currentTimeMillis,
) {
    /** What the hearing of [audio] came to, its checkpoints in [work]'s folder for it. */
    fun hear(audio: File, work: File, say: (String) -> Unit): Heard {
        if (!audio.isFile) throw AudioUnreadable("no audio file: $audio")
        val points = Checkpoints.of(work, audio)
        points.read(Checkpoints.HEARD)?.let { return Heard.read(it) }
        say(STEPS[0])
        HeatRules.start(gauge.read())?.let { throw ChordsUnavailable(it) }
        val pcm = pcm(audio, points)
        val chords = points.read(Checkpoints.CHORDS)?.let(Checkpoints::readChords) ?: run {
            say(STEPS[1])
            chords(points.file(Checkpoints.PCM), threads(say)).also {
                points.write(Checkpoints.CHORDS, Checkpoints.chordsJson(it))
            }
        }
        val (beats, downbeats) = points.read(Checkpoints.BEATS)?.let(Checkpoints::readBeats) ?: run {
            say(STEPS[2])
            beats(points.file(Checkpoints.PCM), threads(say)).also {
                points.write(Checkpoints.BEATS, Checkpoints.beatsJson(it.first, it.second))
            }
        }
        val heard = Heard(Heard.CONTRACT, pcm.duration, Labels.recognized(chords), beats, downbeats)
        points.write(Checkpoints.HEARD, heard.json())
        return heard
    }

    private fun threads(say: (String) -> Unit): Int {
        val allowed = HeatRules.cool(gauge, sleep, clock, say)
        return if (most > 0) minOf(most, allowed) else allowed
    }

    /** The pcm checkpoint, made where it isn't whole: its meta written first, the samples renamed into place last. */
    internal fun pcm(audio: File, points: Checkpoints): Checkpoints.Pcm {
        val meta = points.read(Checkpoints.PCM_META)?.let(Checkpoints::readPcm)
        if (meta != null && points.has(Checkpoints.PCM)) return meta
        points.folder.mkdirs()
        val decoded = points.file("decoded.f32")
        val mono = points.file("mono.f32")
        try {
            val d = try {
                Decoder.decode(audio, decoded)
            } catch (e: UndecodableAudio) {
                throw AudioUnreadable(e.message ?: "the audio can't be decoded", e)
            }
            val duration = d.durationS ?: throw AudioUnreadable("its length can't be read")
            val samples: Long
            if (d.channels == 1) check(decoded.renameTo(mono)) { "can't move $decoded" }
            else Mixdown.mono(decoded, d.channels, mono)
            decoded.delete()
            val out = Checkpoints.Pcm(duration, 0)
            if (d.rate == RATE) {
                samples = mono.length() / 4
                points.write(Checkpoints.PCM_META, Checkpoints.pcmJson(out.copy(samples = samples)))
                points.into(Checkpoints.PCM) { part -> check(mono.renameTo(part)) { "can't move $mono" } }
            } else {
                // libsoxr resamples in one call (python-soxr's, the vectors' own): the mono song once in memory, and
                // its resampled copy, both let go before any model loads.
                val resampled = Soxr.resample(read(mono), d.rate.toDouble(), RATE.toDouble())
                mono.delete()
                samples = resampled.size.toLong()
                points.write(Checkpoints.PCM_META, Checkpoints.pcmJson(out.copy(samples = samples)))
                points.into(Checkpoints.PCM) { part -> write(part, resampled) }
            }
            return out.copy(samples = samples)
        } finally {
            decoded.delete()
            mono.delete()
        }
    }

    /** BTC's chords of [pcm], Harte labels spelled for the key. */
    private fun chords(pcm: File, threads: Int): List<ChordSegment> {
        val features = mapped(pcm) { samples ->
            val n = samples.remaining()
            if (n < Cqt.MIN_AUDIO) throw AudioUnreadable("audio is too short to recognize chords in")
            val parts = ArrayList<FloatArray>()
            var start = 0
            fun part(from: Int, to: Int) {
                HeatRules.check(gauge)
                val piece = FloatArray(to - from)
                samples.position(from)
                samples.get(piece)
                parts += Cqt.logFeatures(piece)
            }
            while (n > start + Cqt.CHUNK) {
                part(start, start + Cqt.CHUNK)
                start += Cqt.CHUNK
            }
            if (n - start >= Cqt.MIN_AUDIO || parts.isEmpty()) part(start, n)
            val out = FloatArray(parts.sumOf { it.size })
            var at = 0
            for (p in parts) {
                p.copyInto(out, at)
                at += p.size
            }
            out
        }
        val frames = features.size / OrtModels.BINS
        val predictions = IntArray(frames)
        OrtModels(models, threads).use { ort ->
            val padding = ort.padding
            val windows = (frames + OrtModels.WINDOW - 1) / OrtModels.WINDOW
            val frame = OrtModels.WINDOW * OrtModels.BINS
            var w = 0
            while (w < windows) {
                HeatRules.check(gauge)
                val count = minOf(BTC_BATCH, windows - w)
                val batch = FloatArray(count * frame) { padding }
                val first = w * OrtModels.WINDOW
                val last = minOf(frames, first + count * OrtModels.WINDOW)
                System.arraycopy(features, first * OrtModels.BINS, batch, 0, (last - first) * OrtModels.BINS)
                val logits = ort.chords(batch, count)
                for (t in first until last) {
                    val row = (t - first) * OrtModels.CLASSES
                    var best = 0
                    for (k in 1 until OrtModels.CLASSES) if (logits[row + k] > logits[row + best]) best = k
                    predictions[t] = best
                }
                w += count
            }
        }
        return Labels.spellForKey(Labels.framesToSegments(predictions, Labels.FRAME_SECONDS,
            Labels.vocabulary(OrtModels.CLASSES)))
    }

    /** beat_this's beats and downbeats of [pcm], in seconds. */
    private fun beats(pcm: File, threads: Int): Pair<List<Double>, List<Double>> {
        val mel = Mel.logMel(read(pcm))
        // The song's samples (53 MB for ten minutes) let go before beat_this's session opens: the collector frees a
        // large array's pages at once.
        System.gc()
        val frames = mel.size / OrtModels.MELS
        val (beat, downbeat) = OrtModels(models, threads, OrtModels.BEATS_FP16).use { ort ->
            BeatThis.logits(mel, frames, OrtModels.MELS, Chunks.SIZE, Chunks.BORDER) { piece, length ->
                HeatRules.check(gauge)
                ort.beats(piece, length)
            }
        }
        return BeatThis.peaks(beat, downbeat, Peaks.FPS)
    }

    companion object {
        /** BTC's and beat_this's rate (btc.py SAMPLE_RATE, beat_this's 22,050). */
        const val RATE = 22050

        /** BTC's windows a run of its graph: 32 of 108 frames, 2 MB of features. */
        const val BTC_BATCH = 32

        /** run.py's `STEPS` that a hearing tells, as each starts. */
        val STEPS = listOf("setting up the models", "hearing the chords", "finding the beats")

        private fun <T> mapped(file: File, use: (FloatBuffer) -> T): T =
            FileChannel.open(file.toPath(), StandardOpenOption.READ).use { channel ->
                use(channel.map(FileChannel.MapMode.READ_ONLY, 0, channel.size()).order(ByteOrder.LITTLE_ENDIAN)
                    .asFloatBuffer())
            }

        /** [file]'s little-endian float32 samples, whole. */
        internal fun read(file: File): FloatArray = mapped(file) { b -> FloatArray(b.remaining()).also { b.get(it) } }

        internal fun write(file: File, samples: FloatArray) {
            FileChannel.open(file.toPath(), StandardOpenOption.WRITE, StandardOpenOption.CREATE,
                StandardOpenOption.TRUNCATE_EXISTING).use { channel ->
                val bytes = ByteBuffer.allocate(1 shl 16).order(ByteOrder.LITTLE_ENDIAN)
                var at = 0
                while (at < samples.size) {
                    bytes.clear()
                    val n = minOf(bytes.capacity() / 4, samples.size - at)
                    bytes.asFloatBuffer().put(samples, at, n)
                    bytes.limit(n * 4)
                    while (bytes.hasRemaining()) channel.write(bytes)
                    at += n
                }
            }
        }
    }
}
