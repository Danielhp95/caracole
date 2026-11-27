package io.github.danielhp95.caracole.autochords

import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.double
import kotlinx.serialization.json.int
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive

/**
 * The two scores the design's gates read (§4.2), mir_eval 0.8.2's, step for step:
 *
 * - [wcsr], a chord estimate's weighted chord symbol recall against a reference, as `mir_eval.chord.evaluate` scores
 *   one rule: `util.adjust_intervals` of the estimate to the reference's span (cut, or padded with "N"),
 *   `merge_labeled_intervals`, `intervals_to_durations`, then `chord.weighted_accuracy` of `chord.majmin` or
 *   `chord.tetrads`, its sums numpy's pairwise ones in numpy's order ([numpySum]), so the score is mir_eval's to the
 *   bit. Its labels are BTC's Harte labels (a root, sharp or flat, and a quality, or "N" or "X": [Labels.vocabulary],
 *   [Labels.spellForKey]); a bass or an interval list is refused, as a label mir_eval refuses is;
 * - [beatF], `mir_eval.beat.f_measure`: the largest matching of reference to estimated beats within the window, its
 *   precision and recall; with no trim: [trimBeats] is `beat.trim_beats`, which `beat.evaluate` applies first.
 *
 * mir_eval's tables (its pitch classes, its qualities' bitmaps, MAX_TIME) are read from caracole/autochords/
 * scores.json (tests/test_conformance_autochords_models.py `scores_json`). A refusal is an [IllegalArgumentException].
 */
object Scores {
    private val doc: JsonObject by lazy {
        val stream = Scores::class.java.getResourceAsStream("/caracole/autochords/scores.json")
            ?: error("no caracole/autochords/scores.json on the classpath")
        Json.parseToJsonElement(stream.use { it.readBytes().toString(Charsets.UTF_8) }).jsonObject
    }
    private val pitchClasses: Map<Char, Int> by lazy {
        doc["pitch_classes"]!!.jsonObject.entries.associate { it.key.single() to it.value.jsonPrimitive.int }
    }
    private val qualities: Map<String, IntArray> by lazy {
        doc["qualities"]!!.jsonObject.mapValues { e -> e.value.jsonArray.map { it.jsonPrimitive.int }.toIntArray() }
    }
    private val noChord: String by lazy { doc["no_chord"]!!.jsonPrimitive.content }
    private val xChord: String by lazy { doc["x_chord"]!!.jsonPrimitive.content }
    private val maxTime: Double by lazy { doc["max_time"]!!.jsonPrimitive.double }

    /** `majmin` and `tetrads` compare a chord's first 8 semitones and all 12. */
    private const val TRIAD = 8

    /** mir_eval's `encode` of a label: its root's semitone (−1 for "N" and "X") and its 12 semitones relative to it
     * (all 0 for "N", all −1 for "X"). */
    private class Encoded(val root: Int, val semitones: IntArray)

    private fun encode(label: String): Encoded {
        if (label == noChord) return Encoded(-1, IntArray(12))
        if (label == xChord) return Encoded(-1, IntArray(12) { -1 })
        val colon = label.indexOf(':')
        val root = if (colon < 0) label else label.substring(0, colon)
        val quality = if (colon < 0) "maj" else label.substring(colon + 1)
        val letter = root.firstOrNull()?.let { pitchClasses[it] }
        val accidentals = root.drop(1)
        require(letter != null && (accidentals.all { it == '#' } || accidentals.all { it == 'b' }) &&
                    quality.isNotEmpty() && quality in qualities) {
            "Invalid chord label: $label (Scores reads a root and a quality, \"N\" or \"X\")"
        }
        val semitone = Math.floorMod(letter + accidentals.count { it == '#' } - accidentals.count { it == 'b' }, 12)
        val bits = qualities[quality]!!.copyOf()
        bits[0] = 1 // the root, and the bass "1"
        return Encoded(semitone, IntArray(12) { if (bits[it] > 0) 1 else 0 })
    }

    private fun equal(a: IntArray, b: IntArray, n: Int): Boolean = (0 until n).all { a[it] == b[it] }

    /** `chord.majmin`: 1 or 0 by root and triad where the reference is a major or minor triad's (a seventh's too) or
     * "N", else −1, left out. */
    private fun majmin(ref: Encoded, est: Encoded): Double {
        val maj = qualities["maj"]!!
        val min = qualities["min"]!!
        val score = if (ref.root == est.root && equal(ref.semitones, est.semitones, TRIAD)) 1.0 else 0.0
        val isNone = ref.root < 0 && ref.semitones.all { it == 0 }
        val kept = equal(ref.semitones, maj, TRIAD) || equal(ref.semitones, min, TRIAD) || isNone
        return if (kept) score else -1.0
    }

    /** `chord.tetrads`: 1 or 0 by root and every semitone; a reference "X" −1, left out. */
    private fun tetrads(ref: Encoded, est: Encoded): Double {
        if (ref.semitones.any { it < 0 }) return -1.0
        return if (ref.root == est.root && equal(ref.semitones, est.semitones, 12)) 1.0 else 0.0
    }

    /** The weighted chord symbol recall of [est] against [ref] by [rule], "majmin" or "tetrads". */
    fun wcsr(ref: List<ChordSegment>, est: List<ChordSegment>, rule: String): Double {
        val compare: (Encoded, Encoded) -> Double = when (rule) {
            "majmin" -> ::majmin
            "tetrads" -> ::tetrads
            else -> throw IllegalArgumentException("no rule $rule: majmin or tetrads")
        }
        require(ref.isNotEmpty()) { "no reference chords" }
        val tMin = ref.minOf { minOf(it.start, it.end) }
        val tMax = ref.maxOf { maxOf(it.start, it.end) }
        val (estimate, estLabels) = adjusted(est.map { doubleArrayOf(it.start, it.end) }, est.map { it.label },
                                             tMin, tMax)
        val (intervals, refOut, estOut) = merged(ref.map { doubleArrayOf(it.start, it.end) }, ref.map { it.label },
                                                 estimate, estLabels)
        for (iv in intervals) {
            require(iv[0] >= 0 && iv[1] >= 0) { "Negative interval times found" }
            require(iv[1] > iv[0]) { "All interval durations must be strictly positive" }
        }
        val durations = intervals.map { Math.abs(it[1] - it[0]) }
        // chord.validate reads every label, the comparison's own encode_many each.
        val refCodes = refOut.map(::encode)
        val estCodes = estOut.map(::encode)
        val comparisons = refCodes.indices.map { compare(refCodes[it], estCodes[it]) }
        return weightedAccuracy(comparisons, durations)
    }

    /** `chord.weighted_accuracy`: 0 for no weight or no comparable chord; else the comparable ones' durations
     * normalized by their sum, then the sum of each comparison times its weight. */
    private fun weightedAccuracy(comparisons: List<Double>, weights: List<Double>): Double {
        if (numpySum(weights) == 0.0) return 0.0
        val valid = comparisons.indices.filter { comparisons[it] >= 0 }
        if (valid.isEmpty()) return 0.0
        val total = numpySum(valid.map { weights[it] })
        return numpySum(valid.map { comparisons[it] * (weights[it] / total) })
    }

    /** `util.adjust_intervals(intervals, labels, tMin, tMax, "N", "N")`, step for step. */
    private fun adjusted(given: List<DoubleArray>, givenLabels: List<String>, tMin: Double,
                         tMax: Double): Pair<List<DoubleArray>, List<String>> {
        if (given.isEmpty()) return listOf(doubleArrayOf(tMin, tMax)) to listOf(noChord)
        var intervals = given.map { it.copyOf() }
        var labels = givenLabels.toMutableList()
        val first = intervals.indexOfFirst { it[1] >= tMin }
        if (first >= 0) {
            labels = labels.subList(first, labels.size).toMutableList()
            intervals = intervals.subList(first, intervals.size)
        }
        intervals = intervals.map { doubleArrayOf(maxOf(tMin, it[0]), maxOf(tMin, it[1])) }
        val least = intervals.minOf { minOf(it[0], it[1]) }
        if (least > tMin) {
            intervals = listOf(doubleArrayOf(tMin, least)) + intervals
            labels.add(0, noChord)
        }
        val last = intervals.indexOfFirst { it[0] > tMax }
        if (last >= 0) {
            labels = labels.subList(0, last).toMutableList()
            intervals = intervals.subList(0, last)
        }
        intervals = intervals.map { doubleArrayOf(minOf(tMax, it[0]), minOf(tMax, it[1])) }
        require(intervals.isNotEmpty()) { "zero-size array to reduction operation maximum which has no identity" }
        val most = intervals.maxOf { maxOf(it[0], it[1]) }
        if (most < tMax) {
            intervals = intervals + listOf(doubleArrayOf(most, tMax))
            labels.add(noChord)
        }
        return intervals to labels
    }

    /** `util.merge_labeled_intervals`: every boundary of either side, sorted, each once; each interval of them
     * labelled by each side's last interval that starts at or before it. */
    private fun merged(x: List<DoubleArray>, xLabels: List<String>, y: List<DoubleArray>,
                       yLabels: List<String>): Triple<List<DoubleArray>, List<String>, List<String>> {
        require(x[0][0] == y[0][0] && x.last()[1] == y.last()[1]) {
            "Time intervals do not align; did you mean to call 'adjust_intervals()' first?"
        }
        val boundaries = (x + y).flatMap { listOf(it[0], it[1]) }.sorted()
        val unique = ArrayList<Double>()
        for (b in boundaries) if (unique.isEmpty() || unique.last() != b) unique += b
        val intervals = (0 until unique.size - 1).map { doubleArrayOf(unique[it], unique[it + 1]) }
        fun labelAt(t0: Double, side: List<DoubleArray>, labels: List<String>): String {
            val at = side.indices.lastOrNull { t0 >= side[it][0] }
                ?: throw IllegalArgumentException("index -1 is out of bounds for axis 0 with size 0")
            return labels[at]
        }
        return Triple(intervals, intervals.map { labelAt(it[0], x, xLabels) }, intervals.map { labelAt(it[0], y, yLabels) })
    }

    /** numpy's `np.sum` of a contiguous float64 array: 0.0 plus its pairwise sum (blocks under 8 summed in turn, up to
     * 128 by eight running sums, longer ones halved at a multiple of 8), which the generator holds to np.sum. */
    fun numpySum(values: List<Double>): Double = 0.0 + pairwise(values, 0, values.size)

    private fun pairwise(a: List<Double>, i: Int, n: Int): Double {
        if (n < 8) {
            var r = -0.0
            for (k in 0 until n) r += a[i + k]
            return r
        }
        if (n <= 128) {
            val r = DoubleArray(8) { a[i + it] }
            var k = 8
            while (k < n - n % 8) {
                for (j in 0 until 8) r[j] += a[i + k + j]
                k += 8
            }
            var s = ((r[0] + r[1]) + (r[2] + r[3])) + ((r[4] + r[5]) + (r[6] + r[7]))
            while (k < n) s += a[i + k++]
            return s
        }
        var half = n / 2
        half -= half % 8
        return pairwise(a, i, half) + pairwise(a, i + half, n - half)
    }

    /** `beat.trim_beats`: the beats at [minBeatTime] or after. */
    fun trimBeats(beats: List<Double>, minBeatTime: Double = 5.0): List<Double> = beats.filter { it >= minBeatTime }

    /** `beat.f_measure(ref, est, window)`, after `beat.validate`: beats past MAX_TIME or out of order refused, an
     * empty side 0. */
    fun beatF(ref: List<Double>, est: List<Double>, window: Double = 0.07): Double {
        for (beats in listOf(ref, est)) {
            require(beats.none { it > maxTime }) { "An event was found which is greater than $maxTime" }
            require((1 until beats.size).none { beats[it] < beats[it - 1] }) { "Events should be in increasing order." }
        }
        if (ref.isEmpty() || est.isEmpty()) return 0.0
        // util._fast_hit_windows: a reference beat in [est − window, est + window].
        val hits = est.map { e -> ref.indices.filter { ref[it] >= e - window && ref[it] <= e + window } }
        val matchOf = IntArray(ref.size) { -1 }
        fun augment(e: Int, seen: BooleanArray): Boolean {
            for (r in hits[e]) {
                if (seen[r]) continue
                seen[r] = true
                if (matchOf[r] < 0 || augment(matchOf[r], seen)) {
                    matchOf[r] = e
                    return true
                }
            }
            return false
        }
        // Any maximum matching is as large as util._bipartite_match's (Hopcroft–Karp): its size is all F reads.
        val matched = est.indices.count { augment(it, BooleanArray(ref.size)) }
        val precision = matched.toDouble() / est.size
        val recall = matched.toDouble() / ref.size
        if (precision == 0.0 && recall == 0.0) return 0.0
        return (1 + 1.0) * precision * recall / (1.0 * precision + recall)
    }
}
