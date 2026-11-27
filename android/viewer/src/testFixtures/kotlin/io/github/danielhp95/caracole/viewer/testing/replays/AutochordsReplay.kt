package io.github.danielhp95.caracole.viewer.testing.replays

import io.github.danielhp95.caracole.core.json.Canonical
import io.github.danielhp95.caracole.core.py.Py
import io.github.danielhp95.caracole.core.testing.AreaReplay
import io.github.danielhp95.caracole.core.testing.Corpus
import io.github.danielhp95.caracole.core.testing.Misses
import io.github.danielhp95.caracole.core.testing.Record
import io.github.danielhp95.caracole.viewer.autochords.Align
import io.github.danielhp95.caracole.viewer.autochords.Alignment
import io.github.danielhp95.caracole.viewer.autochords.AutoSheet
import io.github.danielhp95.caracole.viewer.autochords.ChordSegment
import io.github.danielhp95.caracole.viewer.autochords.Lrc
import io.github.danielhp95.caracole.viewer.autochords.LrcLine
import io.github.danielhp95.caracole.viewer.autochords.WordStart
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.double
import kotlinx.serialization.json.int
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import org.junit.Assert.assertTrue
import org.junit.Assert.fail

/**
 * merge.py and align.py (vectors/autochords-sheet/merge.jsonl and align.jsonl), every record answered by :viewer's
 * viewer.autochords as Python answered it: AutoSheetTest's and AlignTest's record loops, run on the device by
 * CorpusOnDeviceTest. tests/test_conformance_autochords.py's docstring says each record's shape. A float is compared
 * to the bit (0.0 and -0.0 apart), a text whole or by its digest, a raise by its having raised (Python's ValueError
 * an IllegalArgumentException, its OverflowError an ArithmeticException).
 */
object AutochordsReplay : AreaReplay {
    override val area = "autochords-sheet"

    override fun replay(misses: Misses) {
        merge()
        align()
    }

    // --- vectors/autochords-sheet/merge.jsonl ------------------------------------------------------------------

    fun merge() {
        val misses = Misses("autochords-sheet/merge.jsonl")
        val counts = HashMap<String, Int>()
        for (record in Corpus.records("autochords-sheet/merge.jsonl")) {
            counts.merge(record.fn, 1, Int::plus)
            val a = record.args
            when (record.fn) {
                "parse_lrc_words" -> {
                    val text = a[0].jsonPrimitive.content
                    raises(record, misses) { lrcLines(Lrc.parseWords(text)) }
                    if (record.err == null) {
                        val want = record.out!!.jsonArray.map { JsonArray(it.jsonArray.take(2)) }
                        check(misses, record, JsonArray(want)) {
                            JsonArray(Lrc.parse(text).map { (t, s) -> JsonArray(listOf(num(t), JsonPrimitive(s))) })
                        }
                    }
                }
                "snap_to_beats" -> check(misses, record, record.out!!) {
                    segs(AutoSheet.snapToBeats(segments(a[0]), times(a[1])))
                }
                "_beat_grid" -> check(misses, record, record.out!!) {
                    JsonArray(AutoSheet.beatGrid(times(a[0]), a[1].jsonPrimitive.double).map(::num))
                }
                "youtube_credit" -> check(misses, record, record.out!!) {
                    JsonPrimitive(AutoSheet.youtubeCredit(str(a[0]), str(a[1]), str(a[2])))
                }
                "_word_start" -> check(misses, record, record.out!!) {
                    val text = str(a[0])
                    if (a[1] is JsonNull) JsonArray((0 until Py.len(text) + 2).map { JsonPrimitive(AutoSheet.wordStart(text, it)) })
                    else JsonPrimitive(AutoSheet.wordStart(text, a[1].jsonPrimitive.int))
                }
                "_on_words" -> check(misses, record, record.out!!) {
                    placed(AutoSheet.onWords(str(a[0]), placed(a[1])))
                }
                "_chord_line" -> check(misses, record, record.out!!) { JsonPrimitive(AutoSheet.chordLine(placed(a[0]))) }
                "with_plain_lyrics" -> check(misses, record, record.out!!) {
                    text(AutoSheet.withPlainLyrics(str(a[0]), str(a[1])), record.out!!)
                }
                "build_sheet" -> check(misses, record, record.out!!) { text(build(record.kw), record.out!!) }
                else -> fail("an unknown record: ${record.fn}")
            }
        }
        val kinds = setOf("parse_lrc_words", "snap_to_beats", "_beat_grid", "youtube_credit", "_word_start", "_on_words",
                          "_chord_line", "with_plain_lyrics", "build_sheet")
        assertTrue("records of every kind: $counts", counts.keys == kinds && counts.getValue("build_sheet") > 100)
        misses.assertNone()
    }

    private fun build(kw: JsonObject): String {
        val synced = kw["synced"].orNull()?.jsonPrimitive?.content
        val words = when (val w = kw["synced_words"]) {
            null, JsonNull -> null
            JsonPrimitive(true) -> Lrc.parseWords(synced!!)
            else -> w.jsonArray.map(::lrcLine)
        }
        return AutoSheet.build(
            segments(kw.getValue("segments")), str(kw.getValue("title")), str(kw.getValue("artist")), synced, words,
            kw["plain"].orNull()?.jsonPrimitive?.content, kw["beats"].orNull()?.let(::times),
            kw["downbeats"].orNull()?.let(::times), kw["source"].orNull()?.jsonPrimitive?.content,
        )
    }

    // --- vectors/autochords-sheet/align.jsonl ------------------------------------------------------------------

    fun align() {
        val misses = Misses("autochords-sheet/align.jsonl")
        val counts = HashMap<String, Int>()
        for (record in Corpus.records("autochords-sheet/align.jsonl")) {
            counts.merge(record.fn, 1, Int::plus)
            when (record.fn) {
                "shifted_lrc" -> {
                    val (text, offset) = record.args.let { str(it[0]) to it[1].jsonPrimitive.double }
                    raises(record, misses) { text(Align.shiftedLrc(text, offset), record.out!!) }
                }
                "lyrics_offset" -> check(misses, record, record.out!!) {
                    val kw = record.kw
                    val lines = kw.getValue("lines").jsonArray.map { it.jsonArray[0].jsonPrimitive.double to str(it.jsonArray[1]) }
                    alignment(Align.lyricsOffset(lines, segments(kw.getValue("segments")), times(kw.getValue("beats")),
                                                 times(kw.getValue("downbeats")), kw.getValue("audio_s").jsonPrimitive.double,
                                                 kw.getValue("lyrics_s").jsonPrimitive.double))
                }
                "math.fsum" -> raises(record, misses) {
                    num(Py.mathFsum(record.args[0].jsonArray.map { it.jsonPrimitive.double }))
                }
                else -> fail("an unknown record: ${record.fn}")
            }
        }
        assertTrue("records of every kind: $counts",
                   counts.keys == setOf("shifted_lrc", "lyrics_offset", "math.fsum") && counts.getValue("lyrics_offset") > 30)
        misses.assertNone()
    }

    // --- shapes -------------------------------------------------------------------------------------------------

    /** Checks [got] against [want], numbers to the bit. */
    private fun check(misses: Misses, record: Record, want: JsonElement, got: () -> JsonElement) {
        val answer = try {
            got()
        } catch (e: Exception) {
            misses.check(false) { "${record.fn}(${record.args.toString().take(160)}${record.kw.toString().take(160)}) threw $e" }
            return
        }
        misses.check(same(answer, want)) {
            "${record.fn}(${record.args.toString().take(160)}${record.kw.toString().take(200)}) = " +
                "${answer.toString().take(600)}, Python's ${want.toString().take(600)}"
        }
    }

    /** A record that may have raised: then the call must throw what Python's exception stands for. */
    private fun raises(record: Record, misses: Misses, got: () -> JsonElement) {
        val err = record.err ?: return check(misses, record, record.out!!, got)
        val thrown = try {
            got()
            null
        } catch (e: Exception) {
            e
        }
        val expected = when (err) {
            "ValueError" -> thrown is IllegalArgumentException
            "OverflowError" -> thrown is ArithmeticException
            else -> false
        }
        misses.check(expected) { "${record.fn}(${record.args.toString().take(120)}) gave ${thrown ?: "no error"}, Python raised $err" }
    }

    /** Two JSON values alike, a number by its double to the bit (a string "inf", "-inf" or "nan" a float's repr). */
    private fun same(a: JsonElement, b: JsonElement): Boolean = when {
        a is JsonArray && b is JsonArray -> a.size == b.size && a.indices.all { same(a[it], b[it]) }
        a is JsonObject && b is JsonObject -> a.keys == b.keys && a.keys.all { same(a.getValue(it), b.getValue(it)) }
        a is JsonPrimitive && b is JsonPrimitive && !a.isString && !b.isString && a !is JsonNull && b !is JsonNull &&
            a.content != "true" && a.content != "false" ->
            java.lang.Double.compare(a.double, b.double) == 0
        else -> a == b
    }

    private fun JsonElement?.orNull(): JsonElement? = if (this == null || this is JsonNull) null else this

    private fun str(e: JsonElement): String = e.jsonPrimitive.content

    private fun num(x: Double): JsonElement = when {
        x.isNaN() -> JsonPrimitive("nan")
        x == Double.POSITIVE_INFINITY -> JsonPrimitive("inf")
        x == Double.NEGATIVE_INFINITY -> JsonPrimitive("-inf")
        else -> JsonPrimitive(x)
    }

    /** A list of times, or the series `{"start", "step", "n"}` it is: `start + k * step`. */
    private fun times(e: JsonElement): List<Double> {
        if (e is JsonObject) {
            val start = e.getValue("start").jsonPrimitive.double
            val step = e.getValue("step").jsonPrimitive.double
            return (0 until e.getValue("n").jsonPrimitive.int).map { start + it * step }
        }
        return e.jsonArray.map { it.jsonPrimitive.double }
    }

    private fun segments(e: JsonElement): List<ChordSegment> = e.jsonArray.map {
        val s = it.jsonArray
        ChordSegment(s[0].jsonPrimitive.double, s[1].jsonPrimitive.double, str(s[2]))
    }

    private fun segs(segs: List<ChordSegment>): JsonElement =
        JsonArray(segs.map { JsonArray(listOf(num(it.start), num(it.end), JsonPrimitive(it.label))) })

    private fun placed(e: JsonElement): List<Pair<Int, String>> =
        e.jsonArray.map { it.jsonArray[0].jsonPrimitive.int to str(it.jsonArray[1]) }

    private fun placed(p: List<Pair<Int, String>>): JsonElement =
        JsonArray(p.map { JsonArray(listOf(JsonPrimitive(it.first), JsonPrimitive(it.second))) })

    private fun lrcLine(e: JsonElement): LrcLine {
        val l = e.jsonArray
        val words = l[2].orNull()?.jsonArray?.map { WordStart(it.jsonArray[0].jsonPrimitive.double, it.jsonArray[1].jsonPrimitive.int) }
        return LrcLine(l[0].jsonPrimitive.double, str(l[1]), words)
    }

    private fun lrcLines(lines: List<LrcLine>): JsonElement = JsonArray(lines.map { line ->
        JsonArray(listOf(num(line.time), JsonPrimitive(line.text), line.words?.let { w ->
            JsonArray(w.map { JsonArray(listOf(num(it.time), JsonPrimitive(it.column))) })
        } ?: JsonNull))
    })

    /** A text as the record holds it: whole, or its digest and length when the record has them. */
    private fun text(got: String, want: JsonElement): JsonElement {
        if (want !is JsonObject) return JsonPrimitive(got)
        val sha = Canonical.sha256Hex(got.toByteArray(Charsets.UTF_8)).substring(0, 16)
        return JsonObject(mapOf("sha256" to JsonPrimitive(sha), "size" to JsonPrimitive(Py.len(got))))
    }

    private fun alignment(a: Alignment): JsonElement = JsonObject(mapOf(
        "offset" to (a.offset?.let(::num) ?: JsonNull), "why" to JsonPrimitive(a.why),
        "best" to (a.best?.let(::num) ?: JsonNull), "score" to (a.score?.let(::num) ?: JsonNull),
        "runner_up" to (a.runnerUp?.let(::num) ?: JsonNull),
    ))
}
