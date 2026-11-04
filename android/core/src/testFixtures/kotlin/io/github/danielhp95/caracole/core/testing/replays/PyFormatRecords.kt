package io.github.danielhp95.caracole.core.testing.replays

import io.github.danielhp95.caracole.core.py.Py
import io.github.danielhp95.caracole.core.py.PyFormat
import io.github.danielhp95.caracole.core.py.PySequence
import io.github.danielhp95.caracole.core.py.PyUnicode
import io.github.danielhp95.caracole.core.testing.Corpus
import io.github.danielhp95.caracole.core.testing.Misses
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.int
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import kotlinx.serialization.json.long

/**
 * core.py's format records (vectors/py/format_*.jsonl, tests/test_conformance_py.py): f-strings' `f` and `%` specs,
 * round(), difflib.SequenceMatcher and east_asian_width, every record answered by PyFormat, PySequence and PyUnicode
 * as Python answered it. PyFormatTest and PySequenceTest call them on the JVM; PyReplay, the py area's replay, runs
 * them on the device.
 */
object PyFormatRecords {
    fun replay(misses: Misses) {
        numbers(misses)
        sequences(misses)
        widths(misses)
    }

    /** format_numbers.jsonl: each spec of a `format` record, and `round`'s whole numbers. */
    fun numbers(misses: Misses) {
        val records = Corpus.records("py/format_numbers.jsonl")
        check(records.count { it.fn == "format" } >= 500 && records.count { it.fn == "round" } >= 500) {
            "py/format_numbers.jsonl holds too few records"
        }
        for (r in records) {
            val x = double(r.args[0])
            when (r.fn) {
                "format" -> for ((spec, want) in r.out!!.jsonObject) {
                    val got = runCatching { format(x, spec) }.getOrElse { "threw $it" }
                    misses.check(got == text(want)) { "format(${show(x)}, '$spec') = $got, Python ${text(want)}" }
                }
                "round" -> {
                    val got = runCatching { PyFormat.roundHalfEven(x) }
                    if (r.err != null) {
                        val thrown = got.exceptionOrNull()
                        misses.check(thrown != null && thrown::class == RAISED[r.err]) {
                            "round(${show(x)}) = ${got.getOrElse { "threw $it" }}, Python raised ${r.err}"
                        }
                    } else {
                        val want = r.out!!.jsonPrimitive.long
                        misses.check(got.getOrNull() == want) {
                            "round(${show(x)}) = ${got.getOrElse { "threw $it" }}, Python $want"
                        }
                    }
                }
                else -> misses.check(false) { "no Kotlin function for ${r.fn}" }
            }
        }
    }

    /** What PyFormat throws where Python raised the record's `err`. */
    private val RAISED = mapOf(
        "ValueError" to IllegalArgumentException::class,
        "OverflowError" to ArithmeticException::class,
    )

    /** "0W.Nf", "W.Nf", ".Nf" or ".N%" as PyFormat's call. */
    fun format(x: Double, spec: String): String {
        val m = SPEC.matchEntire(spec) ?: throw IllegalArgumentException("no PyFormat call for '$spec'")
        val (zero, width, digits, type) = m.destructured
        val n = digits.toInt()
        return if (type == "%") {
            require(zero.isEmpty() && width.isEmpty()) { "PyFormat.percent takes no width: '$spec'" }
            PyFormat.percent(x, n)
        } else {
            PyFormat.fixed(x, n, if (width.isEmpty()) 0 else width.toInt(), zero = zero.isNotEmpty())
        }
    }

    private val SPEC = Regex("""(0?)([1-9][0-9]*)?\.([0-9]+)([f%])""")

    /** format_sequence.jsonl: each pair's ratio, to the bit, and its matching blocks. */
    fun sequences(misses: Misses) {
        val records = Corpus.records("py/format_sequence.jsonl")
        check(records.size >= 900) { "py/format_sequence.jsonl holds too few records" }
        for (r in records) {
            val a = sequence(r.args[0])
            val b = sequence(r.args[1])
            val out = r.out!!.jsonObject
            val wantBlocks = out.getValue("matching_blocks").jsonArray.map { block ->
                block.jsonArray.let { Triple(it[0].jsonPrimitive.int, it[1].jsonPrimitive.int, it[2].jsonPrimitive.int) }
            }
            val wantRatio = double(out.getValue("ratio"))
            val matcher = PySequence.SequenceMatcher(a, b)
            val blocks = runCatching { matcher.matchingBlocks() }
            misses.check(blocks.getOrNull() == wantBlocks) {
                "SequenceMatcher(${shown(r.args)}).get_matching_blocks() = ${blocks.getOrElse { "threw $it" }}, " +
                    "Python $wantBlocks"
            }
            val ratio = runCatching { matcher.ratio() }
            // Boxed equality, to the bit: 2.0 * matches / length, as Python computes it.
            misses.check(ratio.getOrNull() == wantRatio) {
                "SequenceMatcher(${shown(r.args)}).ratio() = ${ratio.getOrElse { "threw $it" }}, Python $wantRatio"
            }
        }
    }

    /** A string is its code points, each a string; an array its strings. */
    private fun sequence(e: JsonElement): List<String> = when (e) {
        is JsonArray -> e.map(::text)
        is JsonPrimitive -> Py.codePoints(e.content).map { Py.string(intArrayOf(it)) }
        else -> throw AssertionError("no sequence: $e")
    }

    private fun shown(args: JsonArray): String = args.toString().let { if (it.length > 120) it.take(117) + "..." else it }

    /** format_width.jsonl: east_asian_width at every code point. */
    fun widths(misses: Misses) {
        val record = Corpus.records("py/format_width.jsonl").single { it.fn == "unicodedata.east_asian_width.code_points" }
        val runs = record.out!!.jsonArray.map { it.jsonArray }
        var cp = 0
        fun upTo(last: Int, want: String) {
            while (cp <= last) {
                val got = runCatching { PyUnicode.eastAsianWidth(cp) }.getOrElse { "threw $it" }
                misses.check(got == want) { "east_asian_width(U+%04X) = %s, Python %s".format(cp, got, want) }
                cp++
            }
        }
        for (run in runs) {
            upTo(run[0].jsonPrimitive.int - 1, "N")
            upTo(run[1].jsonPrimitive.int, run[2].jsonPrimitive.content)
        }
        upTo(0x10FFFF, "N")
    }

    private fun show(x: Double): String = when {
        x.isNaN() -> "nan"
        x == Double.POSITIVE_INFINITY -> "inf"
        x == Double.NEGATIVE_INFINITY -> "-inf"
        else -> x.toString()
    }
}
