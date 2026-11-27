package io.github.danielhp95.caracole.autochords

import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.int
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import java.math.BigDecimal
import java.math.RoundingMode

/** A chord sounding from [start] to [end] seconds, merge.py's `ChordSegment`; the label "N" means no chord. The design
 * places it in `:viewer`'s `viewer.autochords` (a later task, merge.py's port): then one of the two becomes an alias of
 * the other. */
data class ChordSegment(val start: Double, val end: Double, val label: String)

/**
 * btc.py's labels (the chords-on-the-phone design's §3.7): the Harte labels of a BTC model's classes ([vocabulary]),
 * a guitarist's name for one ([commonName]), black-key roots spelled for the song's key ([spellForKey]), and runs of
 * frame predictions as timed segments ([framesToSegments]), their times Python's `round(…, 3)` ([time]). Every table
 * is btc.py's own, read from caracole/autochords/labels.json (tests/test_conformance_autochords.py `labels_json`);
 * labels are ASCII, read by characters.
 */
object Labels {
    /** btc.py's `FRAME_SECONDS`: a 10 s chunk's 108 frames. */
    const val FRAME_SECONDS = 10.0 / 108

    private val doc: JsonObject by lazy {
        val stream = Labels::class.java.getResourceAsStream("/caracole/autochords/labels.json")
            ?: error("no caracole/autochords/labels.json on the classpath")
        Json.parseToJsonElement(stream.use { it.readBytes().toString(Charsets.UTF_8) }).jsonObject
    }

    private fun JsonObject.texts(key: String): List<String> = this[key]!!.jsonArray.map { it.jsonPrimitive.content }
    private fun JsonObject.map(key: String): Map<String, String> =
        this[key]!!.jsonObject.mapValues { it.value.jsonPrimitive.content }

    private val roots: List<String> by lazy { doc.texts("roots") }
    private val vocabularies: JsonObject by lazy { doc["vocabularies"]!!.jsonObject }
    private val common: Map<String, String> by lazy { doc.map("common") }
    private val flats: Map<String, String> by lazy { doc.map("flats") }
    private val cMajorSpelling: Map<String, String> by lazy { doc.map("c_major_spelling") }
    private val majorScale: List<Int> by lazy { doc["major_scale"]!!.jsonArray.map { it.jsonPrimitive.int } }
    private val flatKeys: Set<Int> by lazy { doc["flat_keys"]!!.jsonArray.map { it.jsonPrimitive.int }.toSet() }
    private val noChord: String by lazy { doc["no_chord"]!!.jsonPrimitive.content }
    private val unknown: String by lazy { doc["unknown"]!!.jsonPrimitive.content }

    /** The Harte labels of a BTC model's classes, by index: 170 (the large vocabulary) or 25; any other size
     * refused in btc.py's words. */
    fun vocabulary(n: Int): List<String> {
        val qualities = vocabularies["qualities"]!!.jsonObject["$n"]?.jsonArray?.map { it.jsonPrimitive.content }
            ?: throw IllegalArgumentException("no BTC vocabulary has $n classes")
        val tail = vocabularies["tails"]!!.jsonObject.texts("$n")
        return roots.flatMap { root -> qualities.map { q -> if (q == "maj") root else "$root:$q" } } + tail
    }

    /** A guitarist's name for a Harte label ("A:min7" → "Am7", "C:maj" → "C"); "N" and "X" both "N". A quality the
     * table hasn't got is kept as written, and a bass (after "/") left out, as btc.py's `common_name`. */
    fun commonName(label: String): String {
        if (label == noChord || label == unknown) return noChord
        val chord = before(label, '/')
        val colon = chord.indexOf(':')
        val root = if (colon < 0) chord else chord.substring(0, colon)
        val quality = (if (colon < 0) "" else chord.substring(colon + 1)).ifEmpty { "maj" }
        return root + (common[quality] ?: quality)
    }

    /** Black-key roots renamed as the song's key writes them (Bb in F major, A# in F# major): the key the major scale
     * (or its relative minor) whose notes carry the most chord time, the first of those that tie. */
    fun spellForKey(segments: List<ChordSegment>): List<ChordSegment> {
        val weights = DoubleArray(12)
        for (s in segments) {
            val at = roots.indexOf(before(s.label, ':'))
            if (at >= 0) weights[at] += s.end - s.start
        }
        if (weights.all { it == 0.0 }) return segments.toList()
        fun fit(tonic: Int): Double = pySum(majorScale.map { weights[(tonic + it) % 12] })
        var tonic = 0
        for (t in 1 until 12) if (fit(t) > fit(tonic)) tonic = t
        val names = if (tonic in flatKeys) flats else if (tonic == 0) cMajorSpelling else emptyMap()
        return segments.map { s ->
            val colon = s.label.indexOf(':')
            val root = if (colon < 0) s.label else s.label.substring(0, colon)
            val renamed = names[root]
            if (renamed == null) s else s.copy(label = renamed + (if (colon < 0) "" else s.label.substring(colon)))
        }
    }

    /** btc.py `recognize`'s last step: each of [segments] (spelled for the key) in its [commonName], a run of one
     * name joined into one segment. */
    fun recognized(segments: List<ChordSegment>): List<ChordSegment> {
        val out = ArrayList<ChordSegment>()
        for (s in segments) {
            val label = commonName(s.label)
            if (out.isNotEmpty() && out.last().label == label) out[out.size - 1] = out.last().copy(end = s.end)
            else out += s.copy(label = label)
        }
        return out
    }

    /** Runs of equal frame [predictions] as timed segments named from [names], each time [time]'s. */
    fun framesToSegments(predictions: IntArray, frameSeconds: Double, names: List<String>): List<ChordSegment> {
        val out = ArrayList<ChordSegment>()
        var start = 0
        for (i in 1..predictions.size) {
            if (i == predictions.size || predictions[i] != predictions[start]) {
                out += ChordSegment(time(start, frameSeconds), time(i, frameSeconds), names[predictions[start]])
                start = i
            }
        }
        return out
    }

    /** Frame [frame]'s time, `round(frame * frameSeconds, 3)` as Python rounds a float: half to even on the exact
     * binary value, then the nearest double (:core's Py.round, ported here, as :autochords depends on no :core). */
    fun time(frame: Int, frameSeconds: Double): Double = pyRound(frame * frameSeconds, 3)

    private fun pyRound(x: Double, digits: Int): Double {
        if (x.isNaN() || x.isInfinite() || x == 0.0) return x
        val rounded = BigDecimal(x).abs().setScale(digits, RoundingMode.HALF_EVEN)
        return Math.copySign(nearestDouble(rounded), x)
    }

    private val EXACT_POWERS = DoubleArray(23) { var p = 1.0; repeat(it) { p *= 10.0 }; p }

    /** The double nearest a decimal: one IEEE division where both are exact, else the shortest decimal parsed. */
    private fun nearestDouble(d: BigDecimal): Double {
        val unscaled = d.unscaledValue()
        val scale = d.scale()
        if (unscaled.bitLength() <= 52 && scale in -22..22) {
            val u = unscaled.toLong().toDouble()
            return if (scale >= 0) u / EXACT_POWERS[scale] else u * EXACT_POWERS[-scale]
        }
        return d.toString().toDouble()
    }

    /** Python 3.12+'s builtin sum() of floats (:core's Py.fsum): 0 + the first, then each Neumaier-compensated, the
     * compensation added last when it is finite and not zero. */
    private fun pySum(xs: List<Double>): Double {
        if (xs.isEmpty()) return 0.0
        var sum = 0.0 + xs[0]
        var c = 0.0
        for (k in 1 until xs.size) {
            val x = xs[k]
            val t = sum + x
            c += if (Math.abs(sum) >= Math.abs(x)) (sum - t) + x else (x - t) + sum
            sum = t
        }
        if (c != 0.0 && c.isFinite()) sum += c
        return sum
    }

    /** [s] up to the first [c] (all of it when there is none): Python's `split(c)[0]` and `partition(c)[0]`. */
    private fun before(s: String, c: Char): String {
        val at = s.indexOf(c)
        return if (at < 0) s else s.substring(0, at)
    }
}
