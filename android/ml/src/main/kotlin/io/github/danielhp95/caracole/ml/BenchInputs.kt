package io.github.danielhp95.caracole.ml

import android.util.Half
import android.util.JsonReader
import android.util.JsonToken
import java.io.BufferedReader
import java.io.InputStream
import java.io.Reader
import java.nio.ByteBuffer
import java.nio.ByteOrder
import java.util.Base64
import org.json.JSONArray
import org.json.JSONObject

/**
 * One file the Chords bench runs the models over, as the computer heard it (the design's §9.1, at B0: the models on
 * the computer's own features, no decoder and no front end on the phone yet): BTC's raw log-CQT `[btcFrames, BINS]`
 * and the computer's logits of it `[btcFrames, CLASSES]` with each frame's top-two [margins]; beat_this's log-mel
 * `[melFrames, MELS]` and the computer's beat and downbeat logits of it, and its beats and downbeats in seconds; the
 * audio's length in seconds, which a run's RTF divides by.
 */
class BenchInput(
    val name: String, val kind: String, val duration: Double,
    val cqt: FloatArray, val btcFrames: Int, val btcLogits: FloatArray, val margins: FloatArray,
    val mel: FloatArray, val melFrames: Int, val beat: FloatArray, val downbeat: FloatArray,
    val beats: List<Double>, val downbeats: List<Double>,
) {
    init {
        require(btcFrames > 0 && cqt.size == btcFrames * OrtModels.BINS) { "$name: ${cqt.size} CQT values" }
        require(btcLogits.size == btcFrames * OrtModels.CLASSES && margins.size == btcFrames) { "$name: BTC's logits" }
        require(melFrames > 0 && mel.size == melFrames * OrtModels.MELS) { "$name: ${mel.size} mel values" }
        require(beat.size == melFrames && downbeat.size == melFrames) { "$name: beat_this's logits" }
        require(duration > 0) { "$name: a length of $duration s" }
        require(kind == CLIP || kind == REFERENCE) { "$name: a kind of $kind" }
    }

    companion object {
        /** A committed clip: parity's, its chunks' overhead no measure of a song's. */
        const val CLIP = "clip"

        /** One of the owner's songs: Gate B0's. */
        const val REFERENCE = "reference"
    }
}

/** The bench's inputs: the committed clips (tests/conformance/vectors/autochords/, the debug build's assets) and the
 * owner's references (`python -m tests.helpers.autochords_reference IN OUT`, one JSON a song, never committed). */
object BenchInputs {
    /** The committed clips and B0's gates, from models.jsonl (the computer's outputs, its meta's `gates`) and
     * frontend.jsonl (its features), each a header line then a record a line. */
    class Clips(val gates: Gates, val inputs: List<BenchInput>)

    fun clips(models: Reader, frontend: Reader): Clips {
        val outputs = records(models)
        val features = records(frontend).filter { it.optString("kind") == "clip" }.associateBy { it.getString("clip") }
        val g = outputs.first { it.optString("kind") == "meta" }.getJSONObject("gates")
        val gates = Gates(
            btcMarginUnder = g.getJSONObject("btc").getDouble("margin_under"),
            btcLogitsMaxAbs = g.getJSONObject("btc").getDouble("logits_max_abs"),
            fp32LogitsMaxAbs = g.getJSONObject("beats_fp32").getDouble("logits_max_abs"),
            fp16FMin = g.getJSONObject("beats_fp16").getDouble("f_measure_min"),
            trim = g.getJSONObject("beats_fp16").getDouble("trim"),
            window = g.getJSONObject("beats_fp16").getDouble("window"),
        )
        val inputs = outputs.filter { it.optString("kind") == "clip" }.map { clip ->
            val name = clip.getString("clip")
            val front = features.getValue(name)
            val btc = clip.getJSONObject("btc")
            val beats = clip.getJSONObject("beats")
            val mel = halves(front.getJSONObject("mel"))
            BenchInput(
                name = name, kind = BenchInput.CLIP, duration = front.getDouble("duration"),
                cqt = floats(front.getJSONObject("cqt")), btcFrames = btc.getInt("frames"),
                btcLogits = floats(btc.getJSONObject("logits")),
                margins = btc.getJSONArray("margin").let { a -> FloatArray(a.length()) { a.getDouble(it).toFloat() } },
                mel = mel, melFrames = mel.size / OrtModels.MELS,
                beat = floats(beats.getJSONObject("beat")), downbeat = floats(beats.getJSONObject("downbeat")),
                beats = doubles(beats.getJSONArray("beats")), downbeats = doubles(beats.getJSONArray("downbeats")),
            )
        }
        return Clips(gates, inputs)
    }

    /**
     * One reference `autochords_reference` wrote, read as a stream ([JsonReader]), so that its decoded samples (tens
     * of MB, which the bench doesn't need) are read through and dropped, never kept: `features`, `logits`, `mel`,
     * `beat_logits`, `beats`, `downbeats` and `duration` (mutagen's; none, the mel's frames at [fps]). [name] is the
     * file's display name, all the report says of it.
     */
    fun reference(name: String, input: InputStream, fps: Int): BenchInput {
        var features: Shaped? = null
        var logits: Shaped? = null
        var mel: Shaped? = null
        var beat: Shaped? = null
        var downbeat: Shaped? = null
        var beats: List<Double>? = null
        var downbeats: List<Double>? = null
        var duration: Double? = null
        JsonReader(input.reader(Charsets.UTF_8).buffered(1 shl 16)).use { r ->
            r.beginObject()
            while (r.hasNext()) {
                when (r.nextName()) {
                    "features" -> features = shaped(r)
                    "logits" -> logits = shaped(r)
                    "mel" -> mel = shaped(r)
                    "beat_logits" -> {
                        r.beginObject()
                        while (r.hasNext()) when (r.nextName()) {
                            "beat" -> beat = shaped(r)
                            "downbeat" -> downbeat = shaped(r)
                            else -> r.skipValue()
                        }
                        r.endObject()
                    }
                    "beats" -> beats = numbers(r)
                    "downbeats" -> downbeats = numbers(r)
                    "duration" -> duration = if (r.peek() == JsonToken.NULL) {
                        r.nextNull()
                        null
                    } else r.nextDouble()
                    else -> r.skipValue()  // decoded, segments, file
                }
            }
            r.endObject()
        }
        fun <T> need(value: T?, what: String): T = value ?: throw IllegalArgumentException("$name: no $what")
        val f = need(features, "features")
        val l = need(logits, "logits")
        val m = need(mel, "mel")
        val frames = f.rows(OrtModels.BINS, "$name's features")
        l.rows(OrtModels.CLASSES, "$name's logits").also {
            require(it == frames) { "$name: $it frames of logits for $frames of features" }
        }
        val melFrames = m.rows(OrtModels.MELS, "$name's mel")
        return BenchInput(
            name = name, kind = BenchInput.REFERENCE, duration = duration ?: (melFrames.toDouble() / fps),
            cqt = f.values, btcFrames = frames, btcLogits = l.values, margins = BtcParity.margins(l.values, frames),
            mel = m.values, melFrames = melFrames,
            beat = need(beat, "beat logits").values, downbeat = need(downbeat, "downbeat logits").values,
            beats = need(beats, "beats"), downbeats = need(downbeats, "downbeats"),
        )
    }

    /** A float32 array of the corpus's form: its values and its shape. */
    private class Shaped(val values: FloatArray, val shape: List<Int>) {
        fun rows(columns: Int, what: String): Int {
            require(shape.size == 2 && shape[1] == columns && shape[0] * columns == values.size) {
                "$what: shape $shape, ${values.size} values"
            }
            return shape[0]
        }
    }

    private fun shaped(r: JsonReader): Shaped {
        var dtype: String? = null
        var shape: List<Int>? = null
        var base64: String? = null
        r.beginObject()
        while (r.hasNext()) when (r.nextName()) {
            "dtype" -> dtype = r.nextString()
            "shape" -> shape = numbers(r).map { it.toInt() }
            "base64" -> base64 = r.nextString()
            else -> r.skipValue()
        }
        r.endObject()
        require(dtype == "float32") { "an array of $dtype, not float32" }
        val buffer = decoded(base64 ?: throw IllegalArgumentException("an array with no base64")).asFloatBuffer()
        return Shaped(FloatArray(buffer.remaining()).also { buffer.get(it) }, shape ?: listOf(buffer.capacity()))
    }

    private fun numbers(r: JsonReader): List<Double> {
        val out = mutableListOf<Double>()
        r.beginArray()
        while (r.hasNext()) out += r.nextDouble()
        r.endArray()
        return out
    }

    private fun records(reader: Reader): List<JSONObject> =
        BufferedReader(reader).useLines { lines -> lines.drop(1).map { JSONObject(it) }.toList() }

    private fun decoded(base64: String): ByteBuffer =
        ByteBuffer.wrap(Base64.getDecoder().decode(base64)).order(ByteOrder.LITTLE_ENDIAN)

    private fun floats(array: JSONObject): FloatArray {
        require(array.getString("dtype") == "float32")
        val buffer = decoded(array.getString("base64")).asFloatBuffer()
        return FloatArray(buffer.remaining()).also { buffer.get(it) }
    }

    /** A float16 array (the clips' mel, as the computer's beat logits were computed over it), as float32. */
    private fun halves(array: JSONObject): FloatArray {
        require(array.getString("dtype") == "float16")
        val buffer = decoded(array.getString("base64")).asShortBuffer()
        return FloatArray(buffer.remaining()) { Half.toFloat(buffer.get(it)) }
    }

    private fun doubles(array: JSONArray) = List(array.length()) { array.getDouble(it) }
}
