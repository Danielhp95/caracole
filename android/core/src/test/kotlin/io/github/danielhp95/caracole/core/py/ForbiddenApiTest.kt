package io.github.danielhp95.caracole.core.py

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
        assertTrue(root.isDirectory, "no ${root.absolutePath}: Gradle runs :core's tests in android/core")
        val files = root.walk().filter { it.isFile && it.name.endsWith(".kt") }.sortedBy { it.path }.toList()
        assertTrue(files.any { it.name == "PyUnicode.kt" }, "PyUnicode.kt is not among ${files.size} files read")
        val found = files.flatMap { ForbiddenApis.scan(it.relativeTo(root).invariantSeparatorsPath, it.readText()) }
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
        // A finding a file keeps: core-db's Database.kt's trim of phone.sql's statements, on that line alone.
        val db = "io/github/danielhp95/caracole/core/db/Database.kt"
        assertEquals(emptyList(), found("for (st in sql.split(';').map { it.trim() }.filter { it.isNotEmpty() }) {}", db))
        assertEquals(listOf(".trim()"), found("val name = row.trim()", db))
        // core/py writes the regexes the rest of :core compiles.
        assertEquals(emptyList(), found("val r = Regex(\"\\\\w\")", "io/github/danielhp95/caracole/core/py/X.kt"))
        assertEquals(listOf(".lowercase("), found("s.lowercase()", "io/github/danielhp95/caracole/core/py/X.kt"))
    }
}

/** The scan [ForbiddenApiTest] runs: a Kotlin source's code, its comments and strings set apart. */
internal object ForbiddenApis {
    private class Rule(val pattern: Regex, val why: String)

    private val ALLOWED_CHARACTER = setOf(
        "isHighSurrogate", "isLowSurrogate", "isSurrogate", "isSurrogatePair", "toChars", "charCount", "toCodePoint",
        "highSurrogate", "lowSurrogate", "isBmpCodePoint", "isSupplementaryCodePoint", "isValidCodePoint",
        "MIN_SUPPLEMENTARY_CODE_POINT", "MIN_CODE_POINT", "MAX_CODE_POINT", "MIN_HIGH_SURROGATE",
        "MAX_HIGH_SURROGATE", "MIN_LOW_SURROGATE", "MAX_LOW_SURROGATE", "MIN_SURROGATE", "MAX_SURROGATE",
        "MIN_VALUE", "MAX_VALUE",
    )

    private const val PREDICATES = "isLetter|isDigit|isLetterOrDigit|isWhitespace|isUpperCase|isLowerCase|" +
        "isTitleCase|isDefined|isIdentifierIgnorable|isJavaIdentifierStart|isJavaIdentifierPart"
    private const val CASE_MAPS = "lowercaseChar|uppercaseChar|titlecaseChar|titlecase|toLowerCase|toUpperCase|" +
        "toTitleCase|capitalize|decapitalize"
    private const val TRIMS = "trim|trimStart|trimEnd|trimIndent|isBlank|isNotBlank|isNullOrBlank"

    /** Kotlin's members that take an `ignoreCase` Boolean: a `true` passed in its place, by position, is caught. */
    private val IGNORE_CASE_MEMBERS = Regex(
        """\.\s*(?:equals|startsWith|endsWith|contains|compareTo|indexOf|lastIndexOf|indexOfAny|lastIndexOfAny|""" +
            """replace|replaceFirst|regionMatches|commonPrefixWith|commonSuffixWith|findAnyOf|findLastAnyOf)\s*\(""",
    )

    private val RULES = listOf(
        Rule(Regex("""\.lowercase\("""), "the JDK's case mapping: PyUnicode.lower, or Py.asciiLower for ASCII"),
        Rule(Regex("""\.uppercase\("""), "the JDK's case mapping: PyUnicode.upper"),
        Rule(Regex("""\bNormalizer\b"""), "java.text.Normalizer is Unicode 13: PyUnicode.nfc, nfd, nfkc, nfkd"),
        Rule(Regex("""\b(?:IGNORE_CASE|CASE_INSENSITIVE|CASE_INSENSITIVE_ORDER|UNICODE_CHARACTER_CLASS|UNICODE_CASE)\b"""),
             "the JDK's or ICU's case folding and classes: PyRegex.compile(\"(?i)…\"), PyUnicode.casefold"),
        Rule(Regex("""\.(?:$PREDICATES)\(\s*\)"""), "Kotlin's Char predicates are Character's: PyUnicode's"),
        Rule(Regex("""\.(?:$CASE_MAPS)\("""), "the JDK's case mapping: PyUnicode.lower, upper, casefold"),
        Rule(Regex("""\.(?:$TRIMS)\(\s*\)|\.trimMargin\("""),
             "Kotlin's trim and blank are Char.isWhitespace, the JDK's: Py.strip, or trim with the characters named"),
        Rule(Regex("""\.(?:digitToInt|digitToIntOrNull)\("""), "the JDK's digits: PyUnicode.isDecimal's"),
        Rule(Regex("""\.(?:category|directionality)\b(?!\s*\()"""), "Kotlin's Char.category is the JDK's: PyUnicode.category"),
        Rule(Regex("""::\s*(?:$PREDICATES|$CASE_MAPS|$TRIMS|trimMargin|lowercase|uppercase|digitToInt|digitToIntOrNull)\b"""),
             "a reference to the JDK's Unicode: PyUnicode's, Py's"),
        Rule(Regex("""[(,]\s*ignoreCase\s*=\s*true\b"""), "the JDK's case folding: compare PyUnicode.casefold's"),
        Rule(Regex("""\b(?:CharCategory|Collator|BreakIterator)\b|\bandroid\.icu\b"""), "the JDK's or ICU's Unicode"),
    )
    private val CHARACTER = Regex("""\bCharacter\s*(?:\.|::)\s*([A-Za-z_][A-Za-z0-9_]*)""")

    /**
     * Findings a file may keep, by its path and the text of its line: each with why.
     * - core-db's branch names the characters Database.kt trims (`trim(' ', '\t', '\n', '\r')`); until it merges,
     *   the skeleton's trims phone.sql's statements, caracole's own ASCII, with Kotlin's whitespace.
     */
    private val KEPT = listOf(
        Triple("io/github/danielhp95/caracole/core/db/Database.kt", "sql.split(';').map { it.trim() }", ".trim()"),
    )
    private val REGEX_CALL = Regex("""(?<![A-Za-z0-9_])(?:Regex|Pattern\s*\.\s*compile|Pattern\s*\.\s*matches)\s*\(""")
    private val REGEX_RECEIVER = Regex("""\.\s*(?:toRegex|toPattern)\s*\(""")
    private const val PY = "io/github/danielhp95/caracole/core/py/"

    /** "path:line: what — why" for each forbidden call in [source], its file named [path]. */
    fun scan(path: String, source: String): List<String> {
        val lexed = Lexed(source)
        val code = lexed.code
        val out = mutableListOf<Pair<Int, String>>()
        fun at(offset: Int, what: String, why: String) {
            out += offset to "$path:${line(source, offset)}: $what — $why"
        }
        for (rule in RULES) {
            for (m in rule.pattern.findAll(code)) {
                // As written, too: `trimStart('0')` is no `trimStart()`, its char blanked in the code.
                if (rule.pattern.matchAt(source, m.range.first)?.value != m.value) continue
                val what = m.value.trim(' ', '\t', '\n', '\r')
                if (KEPT.none { (p, text, w) -> p == path && w == what && text in lineAt(source, m.range.first) }) {
                    at(m.range.first, what, rule.why)
                }
            }
        }
        for (m in IGNORE_CASE_MEMBERS.findAll(code)) {
            val open = m.range.last
            if (arguments(code, open).any { it == "true" }) {
                at(m.range.first, m.value.substringAfter('.').substringBefore('(').trim(' ') + "(…, true)",
                   "an ignoreCase passed by position is the JDK's case folding: compare PyUnicode.casefold's")
            }
        }
        for (m in CHARACTER.findAll(code)) {
            if (m.groupValues[1] !in ALLOWED_CHARACTER) {
                at(m.range.first, "Character.${m.groupValues[1]}", "the JDK's Unicode 13: PyUnicode's tables")
            }
        }
        if (!path.startsWith(PY) && !path.contains("/$PY")) {
            for (m in REGEX_CALL.findAll(code)) {
                val open = m.range.last
                val close = closing(code, open)
                lexed.literals.filter { it.start > open && it.start < close }.forEach { regexLiteral(it, ::at) }
            }
            for (m in REGEX_RECEIVER.findAll(code)) {
                var k = m.range.first - 1
                while (k >= 0 && code[k].isAsciiSpace()) k--
                lexed.literals.firstOrNull { it.end - 1 == k }?.let { regexLiteral(it, ::at) }
            }
        }
        return out.sortedBy { it.first }.map { it.second }.distinct()
    }

    private fun Char.isAsciiSpace() = this == ' ' || this == '\t' || this == '\n' || this == '\r'

    private val REGEX_ESCAPES = "wWsSdDbBpPhHvVRX"

    private fun regexLiteral(literal: Lexed.Literal, at: (Int, String, String) -> Unit) {
        val text = literal.value
        var k = 0
        while (k < text.length) {
            val c = text[k]
            if (c == '\\' && k + 1 < text.length) {
                if (text[k + 1] in REGEX_ESCAPES) {
                    at(literal.start, "\\${text[k + 1]}", "java.util.regex's classes are the JDK's or ICU's Unicode: PyRegex.compile")
                }
                k += 2
                continue
            }
            if (c == '(' && text.startsWith("(?", k)) {
                val flags = text.substring(k + 2).takeWhile { it.isAsciiLetterOrDash() }
                if (flags.any { it == 'i' || it == 'u' || it == 'U' }) {
                    at(literal.start, "(?i", "java.util.regex's case folding: PyRegex.compile(\"(?i)…\")")
                }
            }
            k++
        }
    }

    private fun Char.isAsciiLetterOrDash() = this in 'a'..'z' || this in 'A'..'Z' || this == '-'

    /** The offset of the `)` closing the `(` at [open] in code whose strings and comments are blanked. */
    private fun closing(code: String, open: Int): Int {
        var depth = 0
        for (k in open until code.length) {
            when (code[k]) {
                '(' -> depth++
                ')' -> if (--depth == 0) return k
            }
        }
        return code.length
    }

    /** The arguments of the call whose `(` is at [open], each as written (strings blanked), outer spaces cut. */
    private fun arguments(code: String, open: Int): List<String> {
        val out = mutableListOf<String>()
        var depth = 0
        var from = open + 1
        for (k in open until code.length) {
            when (code[k]) {
                '(', '[', '{' -> depth++
                ')', ']', '}' -> if (--depth == 0) {
                    out += code.substring(from, k).trim(' ', '\t', '\n', '\r')
                    return out
                }
                ',' -> if (depth == 1) {
                    out += code.substring(from, k).trim(' ', '\t', '\n', '\r')
                    from = k + 1
                }
            }
        }
        return out
    }

    private fun line(source: String, offset: Int): Int = 1 + (0 until offset).count { source[it] == '\n' }

    private fun lineAt(source: String, offset: Int): String {
        val start = source.lastIndexOf('\n', offset - 1) + 1
        val end = source.indexOf('\n', offset).let { if (it < 0) source.length else it }
        return source.substring(start, end)
    }
}

/** A Kotlin source with its comments and string literals' text blanked ([code], offsets kept), and each literal's
 * value as Kotlin reads it ([literals]); the code of a string's `${…}` stays code. */
internal class Lexed(private val src: String) {
    class Literal(val start: Int, val end: Int, val value: String)

    private val blanked = StringBuilder(src)
    val literals = mutableListOf<Literal>()
    private var i = 0
    val code: String

    init {
        codeUntilClose(template = false)
        code = blanked.toString()
    }

    private fun blank(from: Int, to: Int) {
        for (k in from until minOf(to, src.length)) if (blanked[k] != '\n') blanked[k] = ' '
    }

    private fun codeUntilClose(template: Boolean) {
        var depth = 0
        while (i < src.length) {
            val c = src[i]
            when {
                src.startsWith("//", i) -> {
                    val end = src.indexOf('\n', i).let { if (it < 0) src.length else it }
                    blank(i, end)
                    i = end
                }
                src.startsWith("/*", i) -> blockComment()
                src.startsWith("\"\"\"", i) -> string(raw = true)
                c == '"' -> string(raw = false)
                c == '\'' -> charLiteral()
                c == '{' -> { depth++; i++ }
                c == '}' -> {
                    if (template && depth == 0) return
                    depth--
                    i++
                }
                else -> i++
            }
        }
    }

    private fun blockComment() {
        val start = i
        var depth = 0
        while (i < src.length) {
            if (src.startsWith("/*", i)) { depth++; i += 2 }
            else if (src.startsWith("*/", i)) { depth--; i += 2; if (depth == 0) break }
            else i++
        }
        blank(start, i)
    }

    private fun charLiteral() {
        val start = i
        i++
        if (i < src.length && src[i] == '\\') i += if (src.startsWith("u", i + 1)) 6 else 2 else i++
        if (i < src.length && src[i] == '\'') {
            i++
            blank(start, i)
        } else {
            i = start + 1 // not a char literal after all
        }
    }

    private fun string(raw: Boolean) {
        val start = i
        i += if (raw) 3 else 1
        val value = StringBuilder()
        var from = i // the start of the text not yet blanked
        while (i < src.length) {
            if (raw && src.startsWith("\"\"\"", i)) {
                var close = i
                while (close + 3 < src.length && src[close + 3] == '"') close++
                value.append(src, i, close)
                blank(from, close)
                i = close + 3
                break
            }
            val c = src[i]
            if (!raw && c == '"') { blank(from, i); i++; break }
            if (!raw && c == '\n') { blank(from, i); break } // an unterminated string: stop at the line's end
            if (!raw && c == '\\' && i + 1 < src.length) {
                val e = src[i + 1]
                when (e) {
                    't' -> value.append('\t')
                    'b' -> value.append('\b')
                    'n' -> value.append('\n')
                    'r' -> value.append('\r')
                    'u' -> {
                        value.append(src.substring(i + 2, minOf(i + 6, src.length)).toIntOrNull(16)?.toChar() ?: '?')
                        i += 4
                    }
                    else -> value.append(e)
                }
                i += 2
                continue
            }
            if (c == '$' && i + 1 < src.length && src[i + 1] == '{') {
                blank(from, i)
                i += 2
                codeUntilClose(template = true)
                i++ // the template's '}'
                from = i
                value.append('\u0000')
                continue
            }
            value.append(c)
            i++
        }
        literals += Literal(start, i, value.toString())
    }
}
