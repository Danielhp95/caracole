package io.github.danielhp95.caracole.autochords.testing

import io.github.danielhp95.caracole.autochords.ChordSegment
import io.github.danielhp95.caracole.autochords.Chunks
import io.github.danielhp95.caracole.autochords.Labels
import io.github.danielhp95.caracole.autochords.Peaks
import io.github.danielhp95.caracole.autochords.Scores
import io.github.danielhp95.caracole.core.testing.Corpus
import io.github.danielhp95.caracole.core.testing.Misses
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.double
import kotlinx.serialization.json.int
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import java.nio.ByteBuffer
import java.nio.ByteOrder
import java.util.Base64
import java.util.zip.Inflater
import kotlin.math.abs

/** What the records around the models share: a record's members read. */
private fun JsonObject.str(key: String): String = this[key]!!.jsonPrimitive.content
private fun JsonObject.num(key: String): Double = this[key]!!.jsonPrimitive.double
private fun JsonObject.whole(key: String): Int = this[key]!!.jsonPrimitive.int
private fun JsonObject.list(key: String): JsonArray = this[key]!!.jsonArray
private fun JsonArray.doubles(): List<Double> = map { it.jsonPrimitive.double }
private fun lines(name: String): List<JsonObject> = Corpus.lines(name).drop(1)

/** `[start, end, label]` rows as segments. */
private fun segments(rows: JsonArray): List<ChordSegment> = rows.map {
    val row = it.jsonArray
    ChordSegment(row[0].jsonPrimitive.double, row[1].jsonPrimitive.double, row[2].jsonPrimitive.content)
}

/** Whether [run] threw an [IllegalArgumentException] (Python's ValueError and mir_eval's InvalidChordException). */
private fun refuses(run: () -> Any?): Boolean = try {
    run()
    false
} catch (e: IllegalArgumentException) {
    true
}

/**
 * vectors/autochords/labels.jsonl (tests/test_conformance_autochords.py): btc.py's vocabularies and their refusals,
 * common names, the spelling for a key, frames to segments, and the times those segments round to.
 */
object LabelsRecords {
    val records: List<JsonObject> by lazy { lines("autochords/labels.jsonl") }

    fun replay(misses: Misses) {
        for (r in records) when (r.str("kind")) {
            "meta" -> misses.check(r.num("frame_seconds") == Labels.FRAME_SECONDS) {
                "FRAME_SECONDS ${Labels.FRAME_SECONDS}, Python's ${r.num("frame_seconds")}"
            }
            "vocabulary" -> {
                val n = r.whole("n")
                val error = r["error"]?.jsonPrimitive?.content
                if (error != null) {
                    val said = try {
                        Labels.vocabulary(n)
                        null
                    } catch (e: IllegalArgumentException) {
                        e.message
                    }
                    misses.check(said == error) { "vocabulary($n) said $said, Python raised $error" }
                } else {
                    val want = r.list("names").map { it.jsonPrimitive.content }
                    misses.check(Labels.vocabulary(n) == want) { "vocabulary($n) = ${Labels.vocabulary(n)}" }
                }
            }
            "common_name" -> for (pair in r.list("pairs")) {
                val (label, name) = pair.jsonArray.map { it.jsonPrimitive.content }
                val got = Labels.commonName(label)
                misses.check(got == name) { "commonName(\"$label\") = \"$got\", Python's \"$name\"" }
            }
            "spell" -> {
                val given = segments(r.list("segments"))
                val want = r.list("spelled").map { it.jsonPrimitive.content }
                val got = Labels.spellForKey(given)
                misses.check(got.map { it.label } == want && got.map { it.start to it.end } ==
                                 given.map { it.start to it.end }) { "spellForKey($given) = $got, Python's $want" }
            }
            "frames" -> {
                val predictions = r.list("predictions").map { it.jsonPrimitive.int }.toIntArray()
                val want = segments(r.list("segments"))
                val got = Labels.framesToSegments(predictions, r.num("frame_seconds"),
                                                  Labels.vocabulary(r.whole("vocabulary")))
                misses.check(got == want) {
                    "framesToSegments(${predictions.size} frames) = ${got.take(5)}…, Python's ${want.take(5)}…"
                }
            }
            "round" -> {
                val want = r.list("seconds").doubles()
                val frames = (r.whole("from") until r.whole("to") step r.whole("step")).toList()
                misses.check(frames.size == want.size) { "round: ${frames.size} frames, ${want.size} answers" }
                for ((k, seconds) in frames.zip(want)) {
                    val got = Labels.time(k, Labels.FRAME_SECONDS)
                    misses.check(got == seconds) { "time($k) = $got, Python's round(…, 3) $seconds" }
                }
            }
            else -> misses.check(false) { "labels.jsonl: no record of kind ${r.str("kind")}" }
        }
    }
}

/**
 * vectors/autochords/peaks.jsonl (tests/test_conformance_autochords_models.py): beat_this's minimal postprocessor
 * over seeded and hand-made logits, each an int8 q a frame (the logit q · scale in float32) or float32s.
 */
object PeaksRecords {
    val records: List<JsonObject> by lazy { lines("autochords/peaks.jsonl") }

    fun logits(array: JsonObject): FloatArray {
        val bytes = ByteBuffer.wrap(Base64.getDecoder().decode(array.str("base64"))).order(ByteOrder.LITTLE_ENDIAN)
        return when (array.str("dtype")) {
            "int8" -> {
                val scale = array.num("scale").toFloat()
                FloatArray(bytes.remaining()) { bytes.get().toFloat() * scale }
            }
            "float32" -> FloatArray(bytes.remaining() / 4) { bytes.float }
            else -> error("no logits of ${array.str("dtype")}")
        }
    }

    fun replay(misses: Misses) {
        for (r in records) when (r.str("kind")) {
            "meta" -> misses.check(r.whole("fps") == Peaks.FPS) { "FPS ${Peaks.FPS}, beat_this's ${r.whole("fps")}" }
            "peaks" -> {
                val (beats, downbeats) = Peaks.of(logits(r["beat"]!!.jsonObject), logits(r["downbeat"]!!.jsonObject))
                val want = r.list("beats").doubles() to r.list("downbeats").doubles()
                misses.check(beats to downbeats == want) {
                    "peaks of ${r.str("what")}: $beats, $downbeats; beat_this's ${want.first}, ${want.second}"
                }
            }
            else -> misses.check(false) { "peaks.jsonl: no record of kind ${r.str("kind")}" }
        }
    }
}

/**
 * vectors/autochords/chunks.jsonl: beat_this's `split_piece` and `aggregate_prediction` of every piece of 0 to 4,000
 * frames, each length's chunks (their starts and lengths) and the runs of the piece each chunk's predictions fill,
 * read from its deflated table.
 */
object ChunksRecords {
    val records: List<JsonObject> by lazy { lines("autochords/chunks.jsonl") }

    class Answer(val frames: Int, val starts: List<Int>, val lengths: List<Int>, val runs: List<List<Int>>)

    /** Each length's answer, in order. */
    val answers: List<Answer> by lazy {
        records.filter { it.str("kind") == "lengths" }.flatMap { r ->
            val ints = table(r.str("table"), r.whole("count"))
            val out = ArrayList<Answer>()
            var i = 0
            while (i < ints.size) {
                val n = ints[i++]
                val k = ints[i++]
                val starts = ints.subList(i, i + k).toList().also { i += k }
                val lengths = ints.subList(i, i + k).toList().also { i += k }
                val m = ints[i++]
                val runs = (0 until m).map { ints.subList(i + 4 * it, i + 4 * it + 4).toList() }.also { i += 4 * m }
                out += Answer(n, starts, lengths, runs)
            }
            check(out.map { it.frames } == (r.whole("from") until r.whole("until")).toList()) { "a block's lengths" }
            out
        }
    }

    private fun table(base64: String, count: Int): List<Int> {
        val inflater = Inflater()
        inflater.setInput(Base64.getDecoder().decode(base64))
        val bytes = ByteArray(4 * count)
        var at = 0
        while (at < bytes.size && !inflater.finished()) at += inflater.inflate(bytes, at, bytes.size - at)
        inflater.end()
        check(at == bytes.size) { "a table of $at bytes, not ${bytes.size}" }
        val buffer = ByteBuffer.wrap(bytes).order(ByteOrder.LITTLE_ENDIAN)
        return List(count) { buffer.int }
    }

    val meta: JsonObject by lazy { records.first { it.str("kind") == "meta" } }

    /** The runs of [frames] each chunk's predictions fill in [Chunks.aggregate], given chunk i's frame j as
     * i · tag + j: `[from, until, chunk, frame]`, chunk −1 for frames none fills (−1000). */
    fun runs(frames: Int, size: Int, border: Int, tag: Int): Pair<List<Chunks.Chunk>, List<List<Int>>> {
        val chunks = Chunks.split(frames, size, border)
        val predictions = chunks.mapIndexed { i, c -> FloatArray(c.length) { j -> (i * tag + j).toFloat() } }
        val piece = Chunks.aggregate(predictions, chunks.map { it.start }, frames, size, border)
        val runs = ArrayList<IntArray>()
        for (f in 0 until frames) {
            val v = piece[f].toInt()
            val (chunk, at) = if (piece[f] == -1000f) -1 to -1 else v / tag to v % tag
            val last = runs.lastOrNull()
            if (last != null && last[1] == f && last[2] == chunk && (chunk < 0 || last[3] + (f - last[0]) == at)) {
                last[1] = f + 1
            } else {
                runs += intArrayOf(f, f + 1, chunk, at)
            }
        }
        return chunks to runs.map { it.toList() }
    }

    fun replay(misses: Misses) {
        val size = meta.whole("chunk")
        val border = meta.whole("border")
        val tag = meta.whole("tag")
        misses.check(size == Chunks.SIZE && border == Chunks.BORDER) {
            "Chunks' size and border ${Chunks.SIZE}, ${Chunks.BORDER}; beat_this's $size, $border"
        }
        misses.check(answers.size == 4001) { "${answers.size} lengths, not 0 to 4,000" }
        for (a in answers) {
            val (chunks, runs) = runs(a.frames, size, border, tag)
            misses.check(chunks.map { it.start } == a.starts && chunks.map { it.length } == a.lengths &&
                             runs == a.runs) {
                "${a.frames} frames: starts ${chunks.map { it.start }}, lengths ${chunks.map { it.length }}, runs " +
                    "$runs; beat_this's ${a.starts}, ${a.lengths}, ${a.runs}"
            }
        }
    }
}

/**
 * vectors/autochords/scores.jsonl: mir_eval's WCSR by `majmin` and `tetrads` and its beat F-measure (untrimmed, and
 * after its 5 s trim), each answer or a refusal; [TOLERANCE] the acceptance's, [exact] counting those bit for bit.
 */
object ScoresRecords {
    const val TOLERANCE = 1e-12
    val records: List<JsonObject> by lazy { lines("autochords/scores.jsonl") }
    /** The scores the last [replay] compared (its refusals aside), and those of them equal to mir_eval's. */
    var scored = 0
        private set
    var exact = 0
        private set

    fun replay(misses: Misses) {
        scored = 0
        exact = 0
        val meta = records.first { it.str("kind") == "meta" }
        val trim = meta.num("trim")
        for (r in records) when (r.str("kind")) {
            "meta" -> Unit
            "wcsr" -> {
                val ref = segments(r.list("ref"))
                val est = segments(r.list("est"))
                for (rule in meta.list("rules").map { it.jsonPrimitive.content }) {
                    val want = r[rule]!!
                    if (want is JsonObject) {
                        misses.check(refuses { Scores.wcsr(ref, est, rule) }) {
                            "wcsr(${r.str("what")}, $rule) answered; mir_eval raised ${want.str("raises")}"
                        }
                    } else {
                        score(misses, "wcsr(${r.str("what")}, $rule)", want.jsonPrimitive.double) {
                            Scores.wcsr(ref, est, rule)
                        }
                    }
                }
            }
            "beat" -> {
                val ref = r.list("ref").doubles()
                val est = r.list("est").doubles()
                val window = r.num("window")
                if (r["raises"] != null) {
                    misses.check(refuses { Scores.beatF(ref, est, window) }) {
                        "beatF(${r.str("what")}) answered; mir_eval raised ${r.str("raises")}"
                    }
                } else {
                    score(misses, "beatF(${r.str("what")})", r.num("f")) { Scores.beatF(ref, est, window) }
                    score(misses, "beatF(${r.str("what")}, trimmed)", r.num("f_trimmed")) {
                        Scores.beatF(Scores.trimBeats(ref, trim), Scores.trimBeats(est, trim), window)
                    }
                }
            }
            else -> misses.check(false) { "scores.jsonl: no record of kind ${r.str("kind")}" }
        }
    }

    private fun score(misses: Misses, what: String, want: Double, got: () -> Double) {
        val score = try {
            got()
        } catch (e: IllegalArgumentException) {
            misses.check(false) { "$what refused ($e); mir_eval's $want" }
            return
        }
        scored++
        if (score == want) exact++
        misses.check(abs(score - want) <= TOLERANCE) { "$what = $score, mir_eval's $want" }
    }
}

