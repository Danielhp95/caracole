package io.github.danielhp95.caracole.autochords

import io.github.danielhp95.caracole.autochords.frontend.Cqt
import io.github.danielhp95.caracole.autochords.frontend.Mel
import io.github.danielhp95.caracole.autochords.frontend.Soxr
import java.io.File
import java.nio.ByteOrder
import java.nio.FloatBuffer
import java.nio.channels.FileChannel
import java.nio.file.StandardOpenOption
import kotlin.math.ceil

/** BTC's graph as a hearing runs it: its windows' logits, and what a short last window is padded with (the features'
 * mean: the graph normalizes inside). */
interface ChordsGraph : AutoCloseable {
    val padding: Float

    /** The logits, `[windows, WINDOW, CLASSES]`, of raw log-CQT features `[windows, WINDOW, BINS]`. */
    fun chords(features: FloatArray, windows: Int): FloatArray
}

/** beat_this's graph: a chunk's beat and downbeat logits, `[frames]` each, of its log-mel `[frames, MELS]`. */
interface BeatsGraph : AutoCloseable {
    fun beats(spect: FloatArray, frames: Int): Pair<FloatArray, FloatArray>
}

/**
 * The hearing's stages after the decode (the design's §3.3), each over a file of little-endian float32 samples, none
 * holding a song whole: what they hold is fixed by the rates and the models (a resampler's piece and block, a CQT
 * chunk of 10 s, a beat_this chunk of 1500 frames), and what grows with the song is the models' outputs alone (BTC's
 * features, 0.37 MB a minute; the beat logits, 24 KB a minute; the chords and beats). StagesHeapTest hears a long
 * signal under a heap smaller than the song.
 *
 * - [resample]: mono at the file's rate to [RATE], libsoxr HQ through its stream ([Soxr.resample] of a file), soxr's
 *   own length, which beat_this reads (its `soxr.resample`);
 * - [chords]: btc.py's chords of the first [btcSamples] of it ([btcSamples], librosa's `fix_length` to
 *   `ceil(n · ratio)`: zeros past soxr's last sample, or cut), `cqt_features`' 10 s chunks and tail rule read from the
 *   memory-mapped file, BTC in batches of [BATCH] windows of [WINDOW] frames, the last padded with
 *   [ChordsGraph.padding], each frame's first highest logit (torch's argmax), runs as Harte segments spelled for the
 *   key ([Labels]);
 * - [beats]: beat_this's mel made a chunk at a time ([Mel.logMel] of frames, bit for bit the whole signal's), its
 *   1500-frame chunks ([Chunks]) through the graph, aggregated, the minimal postprocessor ([Peaks]).
 *
 * [check] is called before each chunk and window batch (the heat, a cancel), and the resample's before each piece;
 * what it throws ends the stage.
 */
object Stages {
    /** BTC's and beat_this's rate (btc.py SAMPLE_RATE). */
    const val RATE = 22050

    /** BTC's frames a window and classes (models.json's `btc.window`, `btc.classes`). */
    const val WINDOW = 108
    const val CLASSES = 170

    /** BTC's windows a run of its graph: 32 of 108 frames, 2 MB of features. */
    const val BATCH = 32

    /** The samples btc.py reads of [n] at [rate] resampled to [RATE]: librosa's `resample(fix=True)`,
     * `int(np.ceil(n * (RATE / rate)))`, [n] itself at [RATE]. */
    fun btcSamples(n: Long, rate: Int): Long =
        if (rate == RATE) n else ceil(n.toDouble() * (RATE.toDouble() / rate)).toLong()

    /** [mono], at [rate], as [RATE] into [pcm]; its samples. */
    fun resample(mono: File, rate: Int, pcm: File, check: () -> Unit = {}): Long =
        Soxr.resample(mono, rate.toDouble(), RATE.toDouble(), pcm, check)

    /** The Harte chords of the first [btcSamples] of [pcm]. */
    fun chords(pcm: File, btcSamples: Long, graph: ChordsGraph, check: () -> Unit = {}): List<ChordSegment> {
        val features = mapped(pcm) { samples ->
            require(btcSamples <= Int.MAX_VALUE) { "a song of $btcSamples samples" }
            val n = btcSamples.toInt()
            val had = samples.remaining()
            if (n < Cqt.MIN_AUDIO) throw AudioUnreadable("audio is too short to recognize chords in")
            val parts = ArrayList<FloatArray>()
            var start = 0
            fun part(from: Int, to: Int) {
                check()
                val piece = FloatArray(to - from)
                val real = minOf(to, had) - from
                if (real > 0) {
                    samples.position(from)
                    samples.get(piece, 0, real)
                }
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
        val bins = Cqt.BINS
        val frames = features.size / bins
        val predictions = IntArray(frames)
        val windows = (frames + WINDOW - 1) / WINDOW
        val padding = graph.padding
        var w = 0
        while (w < windows) {
            check()
            val count = minOf(BATCH, windows - w)
            val batch = FloatArray(count * WINDOW * bins) { padding }
            val first = w * WINDOW
            val last = minOf(frames, first + count * WINDOW)
            System.arraycopy(features, first * bins, batch, 0, (last - first) * bins)
            val logits = graph.chords(batch, count)
            for (t in first until last) {
                val row = (t - first) * CLASSES
                var best = 0
                for (k in 1 until CLASSES) if (logits[row + k] > logits[row + best]) best = k
                predictions[t] = best
            }
            w += count
        }
        val names = Labels.vocabulary(CLASSES)
        return Labels.spellForKey(Labels.framesToSegments(predictions, Labels.FRAME_SECONDS, names))
    }

    /** beat_this's beats and downbeats of [pcm], in seconds. */
    fun beats(pcm: File, graph: BeatsGraph, check: () -> Unit = {}): Pair<List<Double>, List<Double>> =
        mapped(pcm) { samples ->
            val n = samples.remaining()
            val frames = Mel.frames(n)
            val mels = Mel.MELS
            val chunks = Chunks.split(frames)
            val beats = ArrayList<FloatArray>(chunks.size)
            val downbeats = ArrayList<FloatArray>(chunks.size)
            for (c in chunks) {
                check()
                val piece = FloatArray(c.length * mels)
                Mel.logMel(n, samples::get, c.from, c.to).copyInto(piece, c.left * mels)
                val (b, d) = graph.beats(piece, c.length)
                require(b.size == c.length && d.size == c.length) { "the graph gave ${b.size} frames of ${c.length}" }
                beats += b
                downbeats += d
            }
            val starts = chunks.map { it.start }
            Peaks.of(Chunks.aggregate(beats, starts, frames), Chunks.aggregate(downbeats, starts, frames))
        }

    /** [file]'s samples as a read-only map, its own pages, never the heap's. */
    fun <T> mapped(file: File, use: (FloatBuffer) -> T): T =
        FileChannel.open(file.toPath(), StandardOpenOption.READ).use { channel ->
            use(channel.map(FileChannel.MapMode.READ_ONLY, 0, channel.size()).order(ByteOrder.LITTLE_ENDIAN)
                .asFloatBuffer())
        }
}
