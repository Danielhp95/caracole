package io.github.danielhp95.caracole.core.py

import io.github.danielhp95.caracole.core.testing.Corpus
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.boolean
import kotlinx.serialization.json.int
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import org.junit.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertTrue
import kotlin.test.fail

/** PyUnicode against vectors/unicode/strings.jsonl: what Python 3.14's str and unicodedata answer, everywhere. */
class PyUnicodeTest {
    private val corpus = "unicode/strings.jsonl"

    @Test fun theTablesAreTheVersionTheVectorsWereMadeWith() {
        val versions = Corpus.header(corpus)["versions"]!!.jsonObject
        assertEquals(PyUnicode.UNIDATA_VERSION, versions["unicodedata"]!!.jsonPrimitive.content)
    }

    @Test fun everyCodePointHasPythonsPropertiesAndCategory() {
        val predicates: Map<String, (Int) -> Boolean> = mapOf(
            "str.isalnum" to PyUnicode::isAlnum, "str.isalpha" to PyUnicode::isAlpha,
            "str.isdecimal" to PyUnicode::isDecimal, "str.isdigit" to PyUnicode::isDigit,
            "str.isnumeric" to PyUnicode::isNumeric, "str.isspace" to PyUnicode::isSpace,
            "str.isprintable" to PyUnicode::isPrintable, "re.\\w" to PyUnicode::isWord, "re.\\s" to PyUnicode::isSpace,
            "re.\\d" to PyUnicode::isDecimal, "latin_by_name" to PyUnicode::latinByName,
            "cased" to PyUnicode::isCased, "case_ignorable" to PyUnicode::isCaseIgnorable,
        )
        val seen = mutableSetOf<String>()
        for (record in Corpus.records(corpus).filter { it.fn.endsWith(".code_points") }) {
            val name = record.args[0].jsonPrimitive.content
            seen += name
            val runs = record.out!!.jsonArray.map { it.jsonArray }
            when (name) {
                "unicodedata.category" -> eachCodePoint(name, runs, "Cn", { it[2].jsonPrimitive.content }) {
                    PyUnicode.category(it)
                }
                "unicodedata.combining" -> eachCodePoint(name, runs, 0, { it[2].jsonPrimitive.int }) {
                    PyUnicode.combining(it)
                }
                else -> {
                    val test = predicates[name] ?: fail("no Kotlin predicate for $name")
                    eachCodePoint(name, runs, false, { true }) { test(it) }
                }
            }
        }
        assertEquals(predicates.keys + setOf("unicodedata.category", "unicodedata.combining"), seen)
    }

    private fun <T> eachCodePoint(name: String, runs: List<JsonArray>, default: T, value: (JsonArray) -> T,
                                  actual: (Int) -> T) {
        val wrong = mutableListOf<String>()
        var cp = 0
        fun check(upTo: Int, expected: T) {
            while (cp <= upTo) {
                val got = actual(cp)
                if (got != expected && wrong.size < 10) wrong += "U+%04X: %s, Python %s".format(cp, got, expected)
                cp++
            }
        }
        for (run in runs) {
            check(run[0].jsonPrimitive.int - 1, default)
            check(run[1].jsonPrimitive.int, value(run))
        }
        check(0x10FFFF, default)
        assertTrue(wrong.isEmpty(), "$name differs from Python's: $wrong")
    }

    @Test fun everyCodePointATableMapsMapsAsPythonsStrMethodsDo() {
        val names = listOf("lower", "upper", "casefold", "nfc", "nfd", "nfkc", "nfkd", "ignorecase")
        val wrong = mutableListOf<String>()
        val records = Corpus.records(corpus).filter { it.fn.endsWith(".mapped") }
        assertTrue(records.size > 8000)
        for (record in records) {
            val s = Py.string(intArrayOf(record.args[0].jsonPrimitive.int))
            val out = record.out!!.jsonArray.map { it.jsonPrimitive.content }
            names.forEachIndexed { i, name ->
                val got = stringFunction(name, s)
                if (got != out[i] && wrong.size < 20) wrong += "$name(${hex(s)}) = ${hex(got)}, Python ${hex(out[i])}"
            }
        }
        assertTrue(wrong.isEmpty(), wrong.joinToString("\n"))
    }

    @Test fun curatedAndRandomStringsAnswerAsInPython() {
        val wrong = mutableListOf<String>()
        val records = Corpus.records(corpus).filter { it.fn.endsWith(".answers") }
        assertTrue(records.size >= 3000)
        for (record in records) {
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
                if (got != want && wrong.size < 20) wrong += "$name(${hex(s)}) = ${show(got)}, Python ${show(want)}"
            }
        }
        assertTrue(wrong.isEmpty(), wrong.joinToString("\n"))
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
        else -> fail("no Kotlin function for $name")
    }

    @Test fun whatCaracolesCodeLeansOn() {
        assertEquals("τρυπες", PyUnicode.lower("ΤΡΥΠΕΣ"))
        assertEquals("τρυπες σας", PyUnicode.lower("ΤΡΥΠΕΣ ΣΑΣ"))
        assertEquals("σ", PyUnicode.lower("Σ"))
        assertEquals("α'ς'", PyUnicode.lower("Α'Σ'"))
        assertEquals("SS", PyUnicode.upper("ß"))
        assertEquals("ss", PyUnicode.casefold("ẞ"))
        assertEquals("i\u0307stanbul", PyUnicode.lower("İstanbul"))
        assertEquals("2011", PyUnicode.nfkc("２０１１"))
        assertEquals("e\u0301", PyUnicode.nfd("é"))
        assertEquals("é", PyUnicode.nfc("e\u0301"))
        assertEquals("각", PyUnicode.nfc("각"))
        assertEquals("fi", PyUnicode.nfkd("ﬁ"))
        assertEquals("Mn", PyUnicode.category(0x0301))
        assertEquals(230, PyUnicode.combining(0x0301))
        assertTrue(PyUnicode.latinByName('é'.code) && !PyUnicode.latinByName('宋'.code))
        assertTrue(PyUnicode.isSpace(0x1c) && PyUnicode.isSpace(0x85) && !PyUnicode.isSpace(0x200b))
        assertFalse(PyUnicode.isWord(0x093f)) // a Devanagari vowel sign, Mc: no \w
        assertTrue(PyUnicode.allDigit("²") && !PyUnicode.allDigit("") && PyUnicode.isDecimal('２'.code))
        assertEquals('K'.code, PyUnicode.ignoreCaseKey(0x212a))
        assertEquals("ISS", PyRegex.ignoreCase("ıſs"))
    }

    @Test fun aCodePointBeyondUnicodeHasNoProperty() {
        for (cp in listOf(-1, 0x110000, Int.MAX_VALUE)) {
            assertEquals("Cn", PyUnicode.category(cp))
            assertFalse(PyUnicode.isAlnum(cp) || PyUnicode.isSpace(cp))
            assertEquals(0, PyUnicode.combining(cp))
            assertEquals(cp, PyUnicode.ignoreCaseKey(cp))
        }
    }

    private fun hex(s: String): String = Py.codePoints(s).joinToString(" ", "[", "]") { "%04X".format(it) }
    private fun show(x: Any): String = if (x is String) hex(x) else x.toString()
}
