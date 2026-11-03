package io.github.danielhp95.caracole.core.py

import io.github.danielhp95.caracole.core.testing.Corpus
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonPrimitive
import org.junit.Test
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith
import kotlin.test.assertFalse
import kotlin.test.assertNull
import kotlin.test.assertTrue

/** PyRegex and PyRe against vectors/unicode/regex.jsonl: what Python's re answers, through java.util.regex. */
class PyRegexTest {
    @Test fun everyRecordAnswersAsPythonsReDid() {
        val wrong = mutableListOf<String>()
        val records = Corpus.records("unicode/regex.jsonl")
        assertTrue(records.size > 9000)
        val compiled = HashMap<String, Regex>()
        for (r in records) {
            val pattern = r.args[0].jsonPrimitive.content
            if (r.err != null) {
                val refused = runCatching { PyRegex.compile(pattern) }.isFailure
                if (!refused && wrong.size < 30) wrong += "$pattern compiles, Python refuses it (${r.err})"
                continue
            }
            val s = r.args[1].jsonPrimitive.content
            val ignoreCase = r.kw["flags"]?.jsonPrimitive?.content == "IGNORECASE"
            val regex = try {
                compiled.getOrPut((if (ignoreCase) "(?i)" else "") + pattern) {
                    PyRegex.compile((if (ignoreCase) "(?i)" else "") + pattern)
                }
            } catch (e: Exception) {
                if (wrong.size < 30) wrong += "$pattern doesn't compile: $e"
                continue
            }
            val got: Any? = when (r.fn) {
                "re.findall" -> PyRe.findall(regex, s)
                "re.split" -> PyRe.split(regex, s)
                "re.sub" -> r.kw["repl"]!!.jsonPrimitive.content.let { repl -> PyRe.sub(regex, s) { repl } }
                "re.fullmatch" -> PyRe.fullmatch(regex, s)?.value
                else -> error("no Kotlin function for ${r.fn}")
            }
            val out = r.out!!
            val want: Any? = when (out) {
                is JsonNull -> null
                is kotlinx.serialization.json.JsonArray -> out.map { if (it is JsonNull) null else it.jsonPrimitive.content }
                else -> out.jsonPrimitive.content
            }
            if (got != want && wrong.size < 30) {
                wrong += "${r.fn}(${show(pattern)}, ${show(s)}${if (ignoreCase) ", IGNORECASE" else ""}) = " +
                    "${show(got)}, Python ${show(want)}"
            }
        }
        assertTrue(wrong.isEmpty(), wrong.joinToString("\n"))
    }

    private fun show(x: Any?): String = when (x) {
        is String -> buildString {
            append('"')
            for (cp in Py.codePoints(x)) if (cp in 0x20..0x7e) appendCodePoint(cp) else append("\\x{%X}".format(cp))
            append('"')
        }
        is List<*> -> x.joinToString(", ", "[", "]") { show(it) }
        else -> x.toString()
    }

    @Test fun theClassesAreBodiesThatJoin() {
        val wordOrDash = Regex("[" + PyRegex.WORD + "-]+")
        assertEquals("ह", wordOrDash.find("ह\u093F")?.value) // a vowel sign is no \w
        val notWord = Regex("[" + PyRegex.NOT_WORD + "_]+")
        assertEquals(listOf("ह", "द"), notWord.split("ह\u093F\u0902द\u0940").filter { it.isNotEmpty() })
        assertTrue(Regex("[" + PyRegex.DIGIT + "]+").matches("２０١١𝟎"))
        assertTrue(Regex("[" + PyRegex.SPACE + "]+").matches("\u001c\u0085\u3000"))
        assertFalse(Regex("[" + PyRegex.SPACE + "]").matches("\u200B"))
    }

    @Test fun aBoundaryReadsCodePointsBeyondTheBmp() {
        val deseret = "𐐀" // 𐐀, a letter
        assertEquals(listOf("", "$deseret$deseret", " ", deseret, ""),
                     PyRe.split(PyRegex.compile("\\b"), "$deseret$deseret $deseret"))
        assertEquals(listOf("𐐀"), PyRe.findall(PyRegex.compile("\\b\\w\\b"), " $deseret "))
        assertNull(PyRe.search(PyRegex.compile("\\W"), deseret))
    }

    @Test fun ignoreCaseIsSres() {
        val slug = PyRegex.compile("(?i)\\b(?:live|vivo|directo)\\b")
        assertEquals(listOf("LIVE", "Vivo"), PyRe.findall(slug, "LIVE and En Vivo, Olive"))
        assertEquals(listOf("K", "k", "K"), PyRe.findall(PyRegex.compile("(?i)k"), "KkK"))
        assertEquals(listOf("I", "i", "İ", "ı"), PyRe.findall(PyRegex.compile("(?i)i"), "IiİıJ"))
        assertEquals(listOf("S", "s", "ſ"), PyRe.findall(PyRegex.compile("(?i)[a-z]"), "Ssſ1"))
        assertEquals("ISS", PyRegex.ignoreCase("ıſs"))
        assertEquals(4, PyRegex.ignoreCase("𐐨𐐀").length) // Deseret keeps its UTF-16 length
    }

    @Test fun whatThePhoneRefusesItSaysSo() {
        // Valid Python the translation doesn't carry: refused, never read otherwise.
        for (pattern in listOf("\\N{LATIN SMALL LETTER A}", "(?x)a b", "(?a)\\w", "(a)(?(1)a|b)", "(?P<a_b>x)",
                               "(?i)(a)\\1", "a(?i)b")) {
            assertFailsWith<IllegalArgumentException>(pattern) { PyRegex.compile(pattern) }
        }
    }

    @Test fun pythonsLineEndsAndDots() {
        assertEquals(listOf("a", "\u0085", "b"), PyRe.findall(PyRegex.compile("."), "a\u0085b"))
        assertEquals("abc\u2028", PyRe.fullmatch(PyRegex.compile(".*"), "abc\u2028")?.value)
        assertTrue(PyRe.search(PyRegex.compile("c$"), "abc\n") != null)
        assertNull(PyRe.search(PyRegex.compile("c$"), "abc\u0085"))
        assertNull(PyRe.search(PyRegex.compile("c\\Z"), "abc\n"))
    }
}
