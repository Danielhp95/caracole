package io.github.danielhp95.caracole.autochords.frontend

import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.boolean
import kotlinx.serialization.json.double
import kotlinx.serialization.json.int
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import java.nio.ByteBuffer
import java.nio.ByteOrder
import java.util.Base64

/**
 * caracole/autochords/frontend.json, what the front ends apply, every number of it Python's own object
 * (tests/test_conformance_autochords_models.py `frontend_json`): librosa 1.0's CQT at btc.py's settings as it ran
 * over a chunk ([cqt]: its steps, each a resample or an octave's sparse FFT basis, and the lengths its scale divides
 * by), and beat_this's log-mel ([mel]: torchaudio's window, norm and slaney filterbank). Nothing here is recomputed.
 */
object FrontendData {
    /** A matrix of [rows] × [cols] by its rows (CSR): row r's values are at `indptr[r] until indptr[r + 1]`, each in
     * column `indices[i]`, its value `re[i] + i·im[i]` ([im] null for a real matrix). */
    class Sparse(val rows: Int, val cols: Int, val indptr: IntArray, val indices: IntArray, val re: DoubleArray,
                 val im: DoubleArray?)

    sealed interface Step

    /** librosa's `audio.resample(y, orig_sr=from, target_sr=to, res_type=, fix=, scale=)`. */
    class Resample(val from: Double, val to: Double, val resType: String, val fix: Boolean, val scale: Boolean) : Step

    /** librosa's `__cqt_response`: an STFT of [nFft] every [hop] samples ([window], centred with [padMode]
     * padding), each frame's spectrum times [basis], one row a bin. */
    class Octave(val nFft: Int, val hop: Int, val window: String, val padMode: String, val basis: Sparse) : Step

    /** btc.py's settings ([rate], [hop], [bins], [chunk] samples, [minTail], the log's [floor]) and librosa's
     * [steps] for one chunk, then each bin divided by the root of its [lengths]. */
    class Cqt(val rate: Int, val hop: Int, val bins: Int, val chunk: Int, val minTail: Int, val floor: Double,
              val steps: List<Step>, val lengths: DoubleArray)

    /** torchaudio's MelSpectrogram as beat_this sets it, then `log1p(logMultiplier · x)`. */
    class Mel(val rate: Int, val nFft: Int, val hop: Int, val padMode: String, val window: FloatArray,
              val norm: Double, val filterbank: Sparse, val logMultiplier: Double)

    private val doc: JsonObject by lazy {
        val stream = FrontendData::class.java.getResourceAsStream("/caracole/autochords/frontend.json")
            ?: error("no caracole/autochords/frontend.json on the classpath")
        Json.parseToJsonElement(stream.use { it.readBytes().toString(Charsets.UTF_8) }).jsonObject
    }

    val cqt: Cqt by lazy { cqtOf(doc["cqt"]!!.jsonObject) }
    val mel: Mel by lazy { melOf(doc["mel"]!!.jsonObject) }

    private fun JsonObject.int(key: String) = this[key]!!.jsonPrimitive.int
    private fun JsonObject.double(key: String) = this[key]!!.jsonPrimitive.double
    private fun JsonObject.text(key: String) = this[key]!!.jsonPrimitive.content
    private fun JsonObject.obj(key: String) = this[key]!!.jsonObject

    private fun cqtOf(o: JsonObject): Cqt {
        val steps = o["steps"]!!.jsonArray.map { element ->
            val step = element.jsonObject
            step["resample"]?.jsonObject?.let { r ->
                return@map Resample(r.double("from"), r.double("to"), r.text("res_type"),
                                    r["fix"]!!.jsonPrimitive.boolean, r["scale"]!!.jsonPrimitive.boolean)
            }
            val octave = step.obj("octave")
            Octave(octave.int("n_fft"), octave.int("hop"), octave.text("window"), octave.text("pad_mode"),
                   sparse(octave.obj("basis")))
        }
        val lengths = values(o.obj("lengths"), "float64")
        return Cqt(o.int("rate"), o.int("hop"), o.int("bins"), o.int("chunk"), o.int("min_tail"), o.double("floor"),
                   steps, lengths)
    }

    private fun melOf(o: JsonObject): Mel {
        val window = values(o.obj("window"), "float32")
        return Mel(o.int("rate"), o.int("n_fft"), o.int("hop"), o.text("pad_mode"),
                   FloatArray(window.size) { window[it].toFloat() }, o.double("norm"), sparse(o.obj("filterbank")),
                   o.double("log_multiplier"))
    }

    private fun sparse(o: JsonObject): Sparse {
        val shape = o["shape"]!!.jsonArray.map { it.jsonPrimitive.int }
        val indptr = o["indptr"]!!.jsonArray.map { it.jsonPrimitive.int }.toIntArray()
        val indices = o["indices"]!!.jsonArray.map { it.jsonPrimitive.int }.toIntArray()
        val stored = o.obj("values")
        val flat = values(stored, "float32")
        val complex = stored["shape"]!!.jsonArray.size == 2
        require(shape.size == 2 && indptr.size == shape[0] + 1 && indptr.last() == indices.size)
        require(flat.size == indices.size * (if (complex) 2 else 1))
        return if (complex) {
            Sparse(shape[0], shape[1], indptr, indices, DoubleArray(indices.size) { flat[2 * it] },
                   DoubleArray(indices.size) { flat[2 * it + 1] })
        } else {
            Sparse(shape[0], shape[1], indptr, indices, flat, null)
        }
    }

    /** A corpus array's values (base64 of little-endian [dtype]s), each as a double, exactly. */
    private fun values(array: JsonObject, dtype: String): DoubleArray {
        require(array.text("dtype") == dtype) { "a $dtype array, not ${array.text("dtype")}" }
        val bytes = ByteBuffer.wrap(Base64.getDecoder().decode(array.text("base64"))).order(ByteOrder.LITTLE_ENDIAN)
        return when (dtype) {
            "float32" -> DoubleArray(bytes.remaining() / 4) { bytes.float.toDouble() }
            else -> DoubleArray(bytes.remaining() / 8) { bytes.double }
        }
    }
}
