package io.github.danielhp95.caracole.core.py

import io.github.danielhp95.caracole.core.testing.ForbiddenApis
import org.junit.Test
import java.io.File
import kotlin.test.assertEquals
import kotlin.test.assertTrue

/**
 * :core never asks the JDK or Android's ICU about text: the JDK is Unicode 13 on the JVM and Android's ICU varies by
 * device, while the phone must answer as Python 3.14 (unicodedata 16.0.0) does. So every file under
 * android/core/src/main/kotlin is read for the calls that would, and the test fails naming each file and line.
 *
 * Code alone is read: comments and string literals are not, but the code inside a string's `${…}` is. A string
 * literal is read as a regex only where it is the argument of `Regex(…)`, `Pattern.compile(…)` or
 * `Pattern.matches(…)`, or the receiver of `.toRegex()` or `.toPattern()`, outside core/py/ (whose PyRegex writes
 * them): a JSON writer's `"\\b"` is no regex.
 */
class ForbiddenApiTest {
    @Test fun coreNeverAsksTheJdkOrIcuAboutText() {
        val root = File("src/main/kotlin")
        assertTrue(root.walk().any { it.name == "PyUnicode.kt" }, "PyUnicode.kt is not under ${root.absolutePath}")
        val found = ForbiddenApis.check(root)
        assertTrue(found.isEmpty(), "forbidden in :core (use core.py's Py, PyUnicode, PyRegex):\n" + found.joinToString("\n"))
    }

    private fun found(source: String, path: String = "io/github/danielhp95/caracole/core/keys/K.kt") =
        ForbiddenApis.scan(path, source).map { it.substringAfter(": ").substringBefore(" —") }

    @Test fun eachForbiddenCallIsFound() {
        assertEquals(listOf("K.kt:1"), ForbiddenApis.scan("K.kt", "val a = s.lowercase()").map { it.substringBefore(": ") })
        assertEquals(listOf(".lowercase("), found("val a = s.lowercase()"))
        assertEquals(listOf(".uppercase("), found("val a = s.uppercase(java.util.Locale.ROOT)"))
        assertEquals(listOf("Normalizer"), found("import java.text.Normalizer"))
        assertEquals(listOf("Character.getType"), found("val t = Character.getType(cp)"))
        assertEquals(listOf("Character.getName"), found("val n = Character.getName(cp)"))
        assertEquals(listOf("Character.isLetter"), found("if (Character.isLetter(cp)) x()"))
        assertEquals(listOf("Character.toLowerCase", ".toLowerCase("), found("Character.toLowerCase(cp)"))
        assertEquals(listOf("IGNORE_CASE"), found("Regex(p, RegexOption.IGNORE_CASE)"))
        assertEquals(listOf("CASE_INSENSITIVE"), found("Pattern.compile(p, Pattern.CASE_INSENSITIVE)"))
        assertEquals(listOf("UNICODE_CHARACTER_CLASS"), found("Pattern.compile(p, Pattern.UNICODE_CHARACTER_CLASS)"))
        assertEquals(listOf(".isLetter()"), found("c.isLetter()"))
        assertEquals(listOf(".isWhitespace()"), found("s.all { it.isWhitespace() }"))
        assertEquals(listOf(".lowercaseChar("), found("c.lowercaseChar()"))
        assertEquals(listOf(", ignoreCase = true"), found("a.equals(b, ignoreCase = true)"))
        assertEquals(listOf("(ignoreCase=true"), found("a.startsWith(ignoreCase=true, prefix = b)"))
        assertEquals(listOf("\\w"), found("val r = Regex(\"\\\\w+\")"))
        assertEquals(listOf("\\s"), found("val r = Regex(\"\"\"\\s+\"\"\")"))
        assertEquals(listOf("\\d"), found("val r = \"[\\\\d]\".toRegex()"))
        assertEquals(listOf("\\b"), found("val r = Pattern.compile(\"\\\\bx\")"))
        assertEquals(listOf("\\S"), found("val r = Regex(\"a\" + \"\\\\S\")"))
        assertEquals(listOf("\\p"), found("val r = Regex(\"\\\\p{L}\")"))
        assertEquals(listOf("(?i"), found("val r = Regex(\"(?i)x\")"))
        assertEquals(listOf(".trim()"), found("val a = s.trim()"))
        assertEquals(listOf(".trimStart()", ".trimEnd( )"), found("s.trimStart() + s.trimEnd( )"))
        assertEquals(listOf(".trimIndent()", ".trimMargin("), found("val a = x.trimIndent() + y.trimMargin(\"|\")"))
        assertEquals(listOf(".isBlank()", ".isNotBlank()", ".isNullOrBlank()"),
                     found("s.isBlank() || s.isNotBlank() || t.isNullOrBlank()"))
        assertEquals(listOf(".capitalize(", ".digitToInt("), found("s.capitalize() + c.digitToInt()"))
        assertEquals(listOf(".category"), found("val k = c.category.code"))
        assertEquals(listOf("equals(…, true)"), found("if (a.equals(b, true)) x()"))
        assertEquals(listOf("startsWith(…, true)"), found("s.startsWith(p, 2, true)"))
        assertEquals(listOf("endsWith(…, true)", "contains(…, true)"), found("s.endsWith(p,true) && s.contains(q, true)"))
        assertEquals(listOf("compareTo(…, true)"), found("list.sortedWith { a, b -> a.compareTo(b, true) }"))
        assertEquals(listOf("indexOf(…, true)", "replace(…, true)"),
                     found("s.indexOf(\"x\", 0, true); s.replace(\"a\", \"b\", true)"))
        assertEquals(listOf("regionMatches(…, true)"), found("a.regionMatches(0, b, 0, f(1, 2), true)"))
        assertEquals(listOf("CASE_INSENSITIVE_ORDER"), found("names.sortedWith(String.CASE_INSENSITIVE_ORDER)"))
        assertEquals(listOf("::isLetter"), found("s.filter(Char::isLetter)"))
        assertEquals(listOf("::isWhitespace", "::lowercase"), found("s.all(Char::isWhitespace); xs.map(String::lowercase)"))
        assertEquals(listOf(":: trim", "::isBlank"), found("xs.map(String:: trim).filterNot(String::isBlank)"))
        assertEquals(listOf("Character.isLetter", "::isLetter"), found("s.codePoints().allMatch(Character::isLetter)"))
        assertEquals(listOf(".lowercase("), found("val s = \"name: \${name.lowercase()}\""))
        assertEquals(listOf(".lowercase("), found("val q = '\"'; val a = s.lowercase()"))
    }

    @Test fun commentsOtherStringsAndPythonsOwnWordsAreNoCalls() {
        assertEquals(emptyList(), found("// s.lowercase() and Character.isLetter(c)"))
        assertEquals(emptyList(), found("/* a /* nested */ s.uppercase() */ val x = 1"))
        assertEquals(emptyList(), found("val doc = \"s.lowercase() Normalizer\""))
        assertEquals(emptyList(), found("val raw = \"\"\"Character.getType\"\"\""))
        assertEquals(emptyList(), found("val json = \"\\\\b\\\\u0000\" // a JSON writer's escapes"))
        assertEquals(emptyList(), found("val r = Regex(\"[a-z]+\\\\.\")"))
        assertEquals(emptyList(), found("val r = Regex(\"\\\\\\\\w\")")) // an escaped backslash, then w
        assertEquals(emptyList(), found("val ok = PyUnicode.isDigit(cp) && Character.isHighSurrogate(c)"))
        assertEquals(emptyList(), found("val cs = Character.toChars(cp); val n = Character.charCount(cp)"))
        assertEquals(emptyList(), found("var ignoreCase = false; if (x) ignoreCase = true"))
        assertEquals(emptyList(), found("val r = PyRegex.compile(\"\\\\w+\\\\b\")"))
        // Trims of the characters named, a false ignoreCase, a true that is another argument's, Python's category.
        assertEquals(emptyList(), found("s.trim(' ', '\\n'); s.trimStart('0'); s.trimEnd { it == ' ' }; Py.strip(s)"))
        assertEquals(emptyList(), found("a.equals(b, false); a.startsWith(p); a.contains(f(x, true))"))
        assertEquals(emptyList(), found("val k = PyUnicode.category(cp); val ok = map.put(k, true)"))
        assertEquals(emptyList(), found("s.contains(\"a, true\")")) // a string's comma and true are no arguments
        assertEquals(emptyList(), found("xs.map(Py::strip).sortedWith(Py.CODE_POINT_ORDER)"))
        // core/py writes the regexes the rest of :core compiles.
        assertEquals(emptyList(), found("val r = Regex(\"\\\\w\")", "io/github/danielhp95/caracole/core/py/X.kt"))
        assertEquals(listOf(".lowercase("), found("s.lowercase()", "io/github/danielhp95/caracole/core/py/X.kt"))
    }
}

