package io.github.danielhp95.caracole.core.testing.replays

import io.github.danielhp95.caracole.core.fuzz.Fuzz
import io.github.danielhp95.caracole.core.json.Canonical
import io.github.danielhp95.caracole.core.json.CanonicalError
import io.github.danielhp95.caracole.core.json.PyJson
import io.github.danielhp95.caracole.core.keys.Normalize
import io.github.danielhp95.caracole.core.keys.SafeName
import io.github.danielhp95.caracole.core.pinyin.Pinyin
import io.github.danielhp95.caracole.core.py.Py
import io.github.danielhp95.caracole.core.py.PyRe
import io.github.danielhp95.caracole.core.py.PyRegex
import io.github.danielhp95.caracole.core.py.PyUnicode
import io.github.danielhp95.caracole.core.testing.Corpus
import io.github.danielhp95.caracole.core.testing.Record
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.boolean
import kotlinx.serialization.json.double
import kotlinx.serialization.json.int
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Assert.fail
import java.security.MessageDigest
import io.github.danielhp95.caracole.core.testing.AreaReplay
import io.github.danielhp95.caracole.core.testing.Misses

/** The unicode: every code point's properties, case mappings and normalizations, the regex records and core.py's (vectors/unicode/), every record answered by :core as Python answered it: the JVM's
 * tests' record loops, run on the device by CorpusOnDeviceTest. */
object UnicodeReplay : AreaReplay {
    override val area = "unicode"

    override fun replay(misses: Misses) {
        everyCodePointHasPythonsPropertiesAndCategory()
        everyMappedCodePointAndEveryStringAnswersAsPythonsStrDoes()
        everyRegexRecordAnswersAsPythonsReDidThroughAndroidsRegex()
        everyPyRecordAnswersAsPythonDid()
    }

    private fun everyCodePointHasPythonsPropertiesAndCategory() {
        val predicates: Map<String, (Int) -> Boolean> = mapOf(
            "str.isalnum" to PyUnicode::isAlnum, "str.isalpha" to PyUnicode::isAlpha,
            "str.isdecimal" to PyUnicode::isDecimal, "str.isdigit" to PyUnicode::isDigit,
            "str.isnumeric" to PyUnicode::isNumeric, "str.isspace" to PyUnicode::isSpace,
            "str.isprintable" to PyUnicode::isPrintable, "re.\\w" to PyUnicode::isWord, "re.\\s" to PyUnicode::isSpace,
            "re.\\d" to PyUnicode::isDecimal, "latin_by_name" to PyUnicode::latinByName,
        )
        val misses = Misses("unicode/strings.jsonl code points")
        var checked = 0
        for (record in Corpus.records("unicode/strings.jsonl").filter { it.fn.endsWith(".code_points") }) {
            val name = record.args[0].jsonPrimitive.content
            val runs = record.out!!.jsonArray.map { it.jsonArray }
            when (name) {
                "unicodedata.category" -> eachCodePoint(misses, name, runs, "Cn", { it[2].jsonPrimitive.content }) {
                    PyUnicode.category(it)
                }
                "unicodedata.combining" -> eachCodePoint(misses, name, runs, 0, { it[2].jsonPrimitive.int }) {
                    PyUnicode.combining(it)
                }
                // cased and case_ignorable are :core's own (internal): their answers reach the mapped strings below.
                "cased", "case_ignorable" -> continue
                else -> {
                    val test = predicates[name] ?: throw AssertionError("no Kotlin predicate for $name")
                    eachCodePoint(misses, name, runs, false, { true }) { test(it) }
                }
            }
            checked++
        }
        assertEquals(predicates.size + 2, checked)
        misses.assertNone()
    }

    private fun <T> eachCodePoint(misses: Misses, name: String, runs: List<JsonArray>, default: T, value: (JsonArray) -> T,
                                  actual: (Int) -> T) {
        var cp = 0
        fun check(upTo: Int, expected: T) {
            while (cp <= upTo) {
                val got = actual(cp)
                misses.check(got == expected) { "$name(U+%04X) = %s, Python %s".format(cp, got, expected) }
                cp++
            }
        }
        for (run in runs) {
            check(run[0].jsonPrimitive.int - 1, default)
            check(run[1].jsonPrimitive.int, value(run))
        }
        check(0x10FFFF, default)
    }

    private fun everyMappedCodePointAndEveryStringAnswersAsPythonsStrDoes() {
        val misses = Misses("unicode/strings.jsonl strings")
        val records = Corpus.records("unicode/strings.jsonl")
        val names = listOf("lower", "upper", "casefold", "nfc", "nfd", "nfkc", "nfkd", "ignorecase")
        val mapped = records.filter { it.fn.endsWith(".mapped") }
        assertTrue(mapped.size > 8000)
        for (record in mapped) {
            val s = Py.string(intArrayOf(record.args[0].jsonPrimitive.int))
            val out = record.out!!.jsonArray.map { it.jsonPrimitive.content }
            names.forEachIndexed { i, name ->
                val got = stringFunction(name, s)
                misses.check(got == out[i]) { "$name(${hex(s)}) = ${hex(got)}, Python ${hex(out[i])}" }
            }
        }
        val answers = records.filter { it.fn.endsWith(".answers") }
        assertTrue(answers.size >= 3000)
        for (record in answers) {
            val s = record.args[0].jsonPrimitive.content
            for ((name, expected) in record.out as JsonObject) {
                val got: Any = when (name) {
                    "isalnum" -> PyUnicode.allAlnum(s)
                    "isalpha" -> PyUnicode.allAlpha(s)
                    "isdigit" -> PyUnicode.allDigit(s)
                    "isspace" -> PyUnicode.allSpace(s)
                    "len" -> Py.len(s)
                    else -> stringFunction(name, s)
                }
                val want: Any = when (got) {
                    is Boolean -> expected.jsonPrimitive.boolean
                    is Int -> expected.jsonPrimitive.int
                    else -> expected.jsonPrimitive.content
                }
                misses.check(got == want) { "$name(${hex(s)}) = ${show(got)}, Python ${show(want)}" }
            }
        }
        misses.assertNone()
    }

    private fun stringFunction(name: String, s: String): String = when (name) {
        "lower" -> PyUnicode.lower(s)
        "upper" -> PyUnicode.upper(s)
        "casefold" -> PyUnicode.casefold(s)
        "nfc" -> PyUnicode.nfc(s)
        "nfd" -> PyUnicode.nfd(s)
        "nfkc" -> PyUnicode.nfkc(s)
        "nfkd" -> PyUnicode.nfkd(s)
        "ignorecase" -> PyRegex.ignoreCase(s)
        else -> throw AssertionError("no Kotlin function for $name")
    }

    private fun everyRegexRecordAnswersAsPythonsReDidThroughAndroidsRegex() {
        val misses = Misses("unicode/regex.jsonl")
        val records = Corpus.records("unicode/regex.jsonl")
        assertTrue(records.size > 9000)
        val compiled = HashMap<String, Regex>()
        for (r in records) {
            val pattern = r.args[0].jsonPrimitive.content
            if (r.err != null) {
                misses.check(runCatching { PyRegex.compile(pattern) }.isFailure) { "$pattern compiles, Python refuses it (${r.err})" }
                continue
            }
            val s = r.args[1].jsonPrimitive.content
            val ignoreCase = r.kw["flags"]?.jsonPrimitive?.content == "IGNORECASE"
            val source = (if (ignoreCase) "(?i)" else "") + pattern
            val regex = try {
                compiled.getOrPut(source) { PyRegex.compile(source) }
            } catch (e: Exception) {
                misses.check(false) { "$pattern doesn't compile: $e" }
                continue
            }
            val got: Any? = when (r.fn) {
                "re.findall" -> PyRe.findall(regex, s)
                "re.split" -> PyRe.split(regex, s, r.kw["maxsplit"]?.jsonPrimitive?.int ?: 0)
                "re.sub" -> r.kw["repl"]!!.jsonPrimitive.content.let { repl ->
                    PyRe.sub(regex, s, r.kw["count"]?.jsonPrimitive?.int ?: 0) { repl }
                }
                "re.fullmatch" -> PyRe.fullmatch(regex, s)?.value
                else -> throw AssertionError("no Kotlin function for ${r.fn}")
            }
            val want: Any? = when (val out = r.out!!) {
                is JsonNull -> null
                is JsonArray -> out.map { if (it is JsonNull) null else it.jsonPrimitive.content }
                else -> out.jsonPrimitive.content
            }
            misses.check(got == want) {
                "${r.fn}(${show(pattern)}, ${show(s)}${if (ignoreCase) ", IGNORECASE" else ""}${r.kw}) = ${show(got)}, Python ${show(want)}"
            }
        }
        misses.assertNone()
    }

    private fun everyPyRecordAnswersAsPythonDid() {
        val misses = Misses("unicode/py.jsonl")
        for (r in Corpus.records("unicode/py.jsonl")) {
            val a = r.args
            val got: Any? = when (r.fn) {
                "round" -> Py.round(double(a[0]), a[1].jsonPrimitive.int)
                "sum" -> Py.fsum(a[0].jsonArray.map(::double))
                "str.split" -> Py.split(text(a[0]))
                "str.strip" -> Py.strip(text(a[0]))
                "len" -> Py.len(text(a[0]))
                "slice" -> Py.slice(text(a[0]), a[1].intOrNull(), a[2].intOrNull())
                "sorted" -> a[0].jsonArray.map(::text).sortedWith(Py.CODE_POINT_ORDER)
                "collections.Counter.most_common" -> Py.mostCommonFirst(a[0].jsonArray.map(::text))
                "bytes.lower" -> Py.asciiLower(text(a[0]))
                "operator.mod" -> Py.floorMod(a[0].jsonPrimitive.int, a[1].jsonPrimitive.int)
                else -> throw AssertionError("no Kotlin function for ${r.fn}")
            }
            val out = r.out!!
            val want: Any? = when {
                out is JsonNull -> null
                got is Double -> double(out)
                got is Int -> out.jsonPrimitive.int
                got is List<*> -> out.jsonArray.map(::text)
                else -> text(out)
            }
            misses.check(got == want) { "${r.fn}${r.args} = $got, Python $want" }
        }
        misses.assertNone()
    }
}
