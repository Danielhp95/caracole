package io.github.danielhp95.caracole.ml

import ai.onnxruntime.OnnxTensor
import ai.onnxruntime.OrtEnvironment
import ai.onnxruntime.OrtSession
import android.system.Os
import java.io.Closeable
import java.io.File
import java.nio.FloatBuffer

/**
 * caracole's two models on ONNX Runtime (the design's §3.5 prototype): BTC's chords and beat_this's beats, from the
 * files `nix build .#chord-models` makes (src/caracole/autochords/export.py, contract 1) in [dir]:
 *
 * - [BTC_GRAPH], with [BTC_WEIGHTS] beside it: the graph reads every weight at its offset in its authors' file;
 * - [beatsFile]: [BEATS_FP16], its weights stored as float16 and computed in float32, or [BEATS_FP32].
 *
 * Each session is opened at its first run, on [threads] intra-op threads, and closed by [close]; [arena] keeps ONNX
 * Runtime's own CPU arena and memory patterns, off by default (below), so that the Chords bench measures both on the
 * phone. The runtime's
 * telemetry is off: `ORT_DISABLE_TELEMETRY` is set before the process's first [OrtEnvironment], which nothing but this
 * class makes, and the environment's events are turned off; `:ml`'s manifest removes the AAR's TelemetryInitializer,
 * which would hand the native side an HTTP client at the app's start.
 */
class OrtModels(private val dir: File, private val threads: Int, private val beatsFile: String = BEATS_FP16,
                private val arena: Boolean = false) : Closeable {
    private val env = environment()
    private var btc: OrtSession? = null
    private var beat: OrtSession? = null

    /** What a last short window of [chords]' features is padded with: the features' mean, as the graph's metadata
     * says (it normalizes inside), never 0. */
    val padding: Float
        get() = btc().metadata.customMetadata.getValue("mean").toFloat()

    /** BTC's logits, `[windows, WINDOW, CLASSES]` row-major, of raw log-CQT features `[windows, WINDOW, BINS]`. */
    fun chords(features: FloatArray, windows: Int): FloatArray {
        require(features.size == windows * WINDOW * BINS) { "${features.size} features for $windows windows" }
        return run(btc(), "features", features, longArrayOf(windows.toLong(), WINDOW.toLong(), BINS.toLong()),
            listOf("logits"))[0]
    }

    /** beat_this's beat and downbeat logits, `[frames]` each, of one chunk's log-mel `[frames, MELS]`. */
    fun beats(spect: FloatArray, frames: Int): Pair<FloatArray, FloatArray> {
        require(spect.size == frames * MELS) { "${spect.size} values for $frames frames" }
        val session = beat ?: open(beatsFile).also { beat = it }
        val (b, d) = run(session, "spect", spect, longArrayOf(1, frames.toLong(), MELS.toLong()),
            listOf("beat", "downbeat"))
        return b to d
    }

    private fun btc(): OrtSession = btc ?: open(BTC_GRAPH).also { btc = it }

    /** Opens the session [chords] runs on ([btc]) or the one [beats] runs on, before its first run, so that its load
     * is timed apart from it (the Chords bench). */
    fun load(btc: Boolean) {
        if (btc) btc() else if (beat == null) beat = open(beatsFile)
    }

    private fun open(name: String): OrtSession {
        val file = File(dir, name)
        require(file.isFile) { "no $name in $dir" }
        if (name == BTC_GRAPH) require(File(dir, BTC_WEIGHTS).isFile) { "no $BTC_WEIGHTS beside $BTC_GRAPH in $dir" }
        val options = OrtSession.SessionOptions().apply {
            setIntraOpNumThreads(threads)
            setInterOpNumThreads(1)
            // No arena and no memory pattern: beat_this over a 1500-frame chunk then peaks at about 0.8 GB of the
            // process's RSS on the emulator, against 1.6 GB with ORT's defaults (ModelParityTest's numbers); the
            // design's gate is 1 GB. The Chords bench's runs on the emulator found it up to twice as slow as the
            // defaults: the emulator's numbers alone, which the bench measures both ways on the phone.
            if (!arena) {
                setMemoryPatternOptimization(false)
                setCPUArenaAllocator(false)
            }
        }
        return options.use { env.createSession(file.path, it) }
    }

    private fun run(session: OrtSession, input: String, values: FloatArray, shape: LongArray,
                    outputs: List<String>): List<FloatArray> =
        OnnxTensor.createTensor(env, FloatBuffer.wrap(values), shape).use { tensor ->
            session.run(mapOf(input to tensor), outputs.toSet()).use { result ->
                outputs.map { name ->
                    val buffer = (result.get(name).get() as OnnxTensor).floatBuffer
                    FloatArray(buffer.remaining()).also { buffer.get(it) }
                }
            }
        }

    /** Closes the sessions; the process's [OrtEnvironment] is kept on purpose, one a process, for the next. */
    override fun close() {
        try {
            btc?.close()
        } finally {
            btc = null
            try {
                beat?.close()
            } finally {
                beat = null
            }
        }
    }

    companion object {
        /** What a version's `raw["runtime"]` names (the design's §4.4). */
        const val RUNTIME = "onnxruntime " + BuildConfig.ONNX_RUNTIME

        const val BTC_GRAPH = "btc-graph.onnx"
        const val BTC_WEIGHTS = "btc_model_large_voca.pt"
        const val BEATS_FP32 = "beat_this-final0.onnx"
        const val BEATS_FP16 = "beat_this-final0-fp16.onnx"

        /** BTC's frames a window, CQT bins and chord classes; beat_this's mel bands (models.json's). */
        const val WINDOW = 108
        const val BINS = 144
        const val CLASSES = 170
        const val MELS = 128

        @Synchronized private fun environment(): OrtEnvironment {
            Os.setenv("ORT_DISABLE_TELEMETRY", "1", true)
            return OrtEnvironment.getEnvironment().also { it.setTelemetry(false) }
        }
    }
}
