package io.github.danielhp95.caracole.core.py

/**
 * Python's re patterns for java.util.regex, meaning what Python's mean: never the JDK's own \w or
 * \s, case folding or line ends, whose Unicode differs from Python's (and is ICU's on Android).
 *
 * [compile] translates a Python pattern:
 * - `\w \W \s \S \d \D` and every character class become explicit classes of code points, computed from Python's
 *   tables (a class's ranges, negation, `\w` inside it, its IGNORECASE closure); `\b` and `\B` become lookarounds
 *   over [WORD].
 * - `(?i)`, `(?i:…)` and `(?-i:…)` are sre's IGNORECASE: each literal stands for its class
 *   ([PyUnicode.ignoreCaseKey]'s), a character class is closed under the classes, and `\w \s \d \b` read the
 *   subject as it is, as sre reads them. `(?s)`, `(?m)` and their scoped forms are passed on, `(?m)`'s `^` written
 *   as Python reads it (after a final `\n` too, where java.util.regex's never matches); `(?u)` is Python's default.
 * - `.`, `^` and `$` know `\n` alone as a line end (java.util.regex's UNIX_LINES), `\Z` and `\z` are the end of
 *   the text, `\v` is U+000B, `\x41`, `\u00e9`, `\U0001F600` and octal escapes are code points, `(?P<name>…)` and
 *   `(?P=name)` are named groups, a `{` that starts no quantifier is itself, and `{,n}` is `{0,n}`.
 * - What Python refuses is refused (IllegalArgumentException). So is what the translation doesn't carry: `\N{…}`,
 *   `(?x)`, `(?a)`, conditional groups, a backreference under IGNORECASE, a group name java.util.regex can't hold.
 *
 * java.util.regex steps over a text by UTF-16 unit unless its pattern holds a code point beyond the BMP as it is,
 * so every compiled pattern carries one (a lookahead that is always true) and every class writes such code points
 * as they are: a lookbehind then reads the code point before it whole.
 *
 * Python's empty matches are [PyRe]'s: findall, split and sub step over a text as Python does.
 *
 * Compile a pattern once, as a top-level or companion `val`, never in a loop: the first compile reads Python's
 * tables (about a second on the JVM), and every compile writes `\w`'s 771 ranges and the like into the pattern. A
 * class of many ranges is written as a search tree ([CodePointSet.asClass]), so matching a title on the JVM costs
 * microseconds, not the quarter of a millisecond a flat class of them would; [WORD] and the other bodies below
 * are flat, for a class of a caller's own.
 */
object PyRegex {
    /** [...] class bodies: ranges to put between brackets, which join by concatenation; flat, so a class made of
     * one is slow to match on the JVM, where [compile]'s `[\w-]` is not. */
    val WORD: String get() = Bodies.word
    val NOT_WORD: String get() = Bodies.notWord
    val SPACE: String get() = Bodies.space
    val DIGIT: String get() = Bodies.digit

    /** [pattern], a Python pattern, as java.util.regex reads it meaning the same; its inline flags are Python's own. */
    fun compile(pattern: String): Regex = Regex(PyPattern(pattern).translate(), RegexOption.UNIX_LINES)

    /**
     * A length-preserving map to [PyUnicode.ignoreCaseKey], for comparing two texts as IGNORECASE does: a text's
     * UTF-16 length is kept, as no class mixes the BMP and the code points beyond it.
     *
     * Not for matching: port `re.compile(p, re.IGNORECASE)` as `compile("(?i)" + p)`. A pattern written over these
     * keys and run on a mapped text reads `\w`, `\W`, `\b` and `\B` wrong where a class mixes word and not word
     * (U+0345, Mn, is the key of ι's class), and its groups and matches come back as keys, not as the text.
     */
    fun ignoreCase(s: String): String {
        val out = StringBuilder(s.length)
        var i = 0
        while (i < s.length) {
            val cp = s.codePointAt(i)
            out.appendCodePoint(PyUnicode.ignoreCaseKey(cp))
            i += Character.charCount(cp)
        }
        return out.toString()
    }

    internal object Sets {
        val word: CodePointSet by lazy { PyUnicode.flagSet(PyUnicode.WORD_FLAG) }
        val notWord: CodePointSet by lazy { word.complement() }
        val space: CodePointSet by lazy { PyUnicode.flagSet(PyUnicode.SPACE_FLAG) }
        val notSpace: CodePointSet by lazy { space.complement() }
        val digit: CodePointSet by lazy { PyUnicode.flagSet(PyUnicode.DECIMAL_FLAG) }
        val notDigit: CodePointSet by lazy { digit.complement() }
    }

    private object Bodies {
        val word: String by lazy { Sets.word.body() }
        val notWord: String by lazy { Sets.notWord.body() }
        val space: String by lazy { Sets.space.body() }
        val digit: String by lazy { Sets.digit.body() }
    }
}

