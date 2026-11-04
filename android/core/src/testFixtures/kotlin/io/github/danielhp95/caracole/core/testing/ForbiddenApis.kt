package io.github.danielhp95.caracole.core.testing

/**
 * The check that :core, :viewer and :server never ask the JDK or Android's ICU about text (AGENTS.md, "The phone
 * agrees with the computer to the byte"): the JDK is Unicode 13 on the JVM and Android's ICU varies by device, while
 * the phone must answer as Python 3.14 (unicodedata 16.0.0) does. Each module's ForbiddenApiTest runs [check] over its
 * src/main/kotlin; [scan] reads one source.
 *
 * Code alone is read: comments and string literals are not, but the code inside a string's `${…}` is. A string
 * literal is read as a regex only where it is the argument of `Regex(…)`, `Pattern.compile(…)` or
 * `Pattern.matches(…)`, or the receiver of `.toRegex()` or `.toPattern()`, outside core/py/ (whose PyRegex writes
 * them): a JSON writer's `"\\b"` is no regex.
 */
object ForbiddenApis {
    /**
     * Every forbidden call in the `.kt` files under [root] (a module's src/main/kotlin), as "path:line: what — why",
     * but in the files [allowed] names (a path under [root], to the lane that ports it: an M1–3 file a later lane
     * rewrites). An allowed file that has nothing forbidden left is named too, so the list only shrinks.
     */
    fun check(root: java.io.File, allowed: Map<String, String> = emptyMap()): List<String> {
        require(root.isDirectory) { "no ${root.absolutePath}: Gradle runs a module's tests in its folder" }
        val files = root.walk().filter { it.isFile && it.name.endsWith(".kt") }.sortedBy { it.path }.toList()
        val out = mutableListOf<String>()
        for (file in files) {
            val path = file.relativeTo(root).invariantSeparatorsPath
            val found = scan(path, file.readText())
            val lane = allowed.entries.firstOrNull { path.endsWith(it.key) }?.value
            if (lane == null) out += found
            else if (found.isEmpty()) out += "$path: nothing forbidden is left: take it off the allow list (lane $lane)"
        }
        return out
    }

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
                at(m.range.first, m.value.trim(' ', '\t', '\n', '\r'), rule.why)
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

}

/** A Kotlin source with its comments and string literals' text blanked ([code], offsets kept), and each literal's
 * value as Kotlin reads it ([literals]); the code of a string's `${…}` stays code. */
class Lexed internal constructor(private val src: String) {
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
