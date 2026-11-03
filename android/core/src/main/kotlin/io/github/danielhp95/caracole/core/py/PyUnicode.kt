package io.github.danielhp95.caracole.core.py

/**
 * Python 3.14's unicodedata (16.0.0) and str methods, from the tables in caracole/unicode/ (tests/conformance/data,
 * made by tests/test_conformance_unicode.py from Python's own answers): never the JDK's or ICU's, whose Unicode is
 * another (13 on the JVM, the device's on Android). Each table loads on first use.
 *
 * A string is read by code point, as Python reads it; a lone surrogate is a code point of its own (category Cs).
 */
object PyUnicode {
    const val UNIDATA_VERSION = "16.0.0"

    private const val ALNUM = 1 shl 0
    private const val ALPHA = 1 shl 1
    private const val DECIMAL = 1 shl 2
    private const val DIGIT = 1 shl 3
    private const val NUMERIC = 1 shl 4
    private const val SPACE = 1 shl 5
    private const val WORD = 1 shl 6
    private const val PRINTABLE = 1 shl 7
    private const val LATIN = 1 shl 8
    private const val CASED = 1 shl 9
    private const val CASE_IGNORABLE = 1 shl 10

    fun isAlnum(cp: Int): Boolean = has(cp, ALNUM)
    fun isAlpha(cp: Int): Boolean = has(cp, ALPHA)
    fun isDecimal(cp: Int): Boolean = has(cp, DECIMAL)
    fun isDigit(cp: Int): Boolean = has(cp, DIGIT)
    fun isNumeric(cp: Int): Boolean = has(cp, NUMERIC)
    fun isSpace(cp: Int): Boolean = has(cp, SPACE)

    /** re's \w: isalnum() or '_'. */
    fun isWord(cp: Int): Boolean = has(cp, WORD)
    fun isPrintable(cp: Int): Boolean = has(cp, PRINTABLE)

    /** "Lu", "Mn", … */
    fun category(cp: Int): String = Categories.NAMES[Categories.table[cp]]
    fun combining(cp: Int): Int = Combining.table[cp]

    /** "LATIN" in unicodedata.name(c). */
    fun latinByName(cp: Int): Boolean = has(cp, LATIN)

    /** Cased (Lowercase, Uppercase or Lt), as lower()'s Final_Sigma reads it. */
    internal fun isCased(cp: Int): Boolean = has(cp, CASED)

    /** Case_Ignorable, as lower()'s Final_Sigma reads it. */
    internal fun isCaseIgnorable(cp: Int): Boolean = has(cp, CASE_IGNORABLE)

    private fun has(cp: Int, bit: Int): Boolean = Flags.table[cp] and bit != 0

    /** The code points of a flag ([WORD_FLAG], …), for PyRegex's classes. */
    internal fun flagSet(flag: Int): CodePointSet = Flags.sets.getOrPut(flag) {
        val runs = Flags.runs
        val ranges = ArrayList<Int>()
        for (i in 0 until runs.size / 3) if (runs[3 * i + 2] and flag != 0) { ranges += runs[3 * i]; ranges += runs[3 * i + 1] }
        CodePointSet.of(ranges.toIntArray())
    }

    internal const val WORD_FLAG = WORD
    internal const val SPACE_FLAG = SPACE
    internal const val DECIMAL_FLAG = DECIMAL

    /** str.lower(): each code point's full lower case, and Σ as Python's Final_Sigma rule reads its place. */
    fun lower(s: String): String {
        if (isAscii(s)) return Py.asciiLower(s)
        val cps = Py.codePoints(s)
        val out = StringBuilder(s.length)
        for (i in cps.indices) {
            val cp = cps[i]
            if (cp == CAPITAL_SIGMA) out.append(if (finalSigma(cps, i)) 'ς' else 'σ')
            else append(out, cp, Case.lower)
        }
        return out.toString()
    }

    fun upper(s: String): String = mapped(s, Case.upper)
    fun casefold(s: String): String = if (isAscii(s)) Py.asciiLower(s) else mapped(s, Case.fold)

    fun nfc(s: String): String = if (isAscii(s)) s else Py.string(compose(decompose(s, compat = false)))
    fun nfkc(s: String): String = if (isAscii(s)) s else Py.string(compose(decompose(s, compat = true)))
    fun nfd(s: String): String = if (isAscii(s)) s else Py.string(decompose(s, compat = false))
    fun nfkd(s: String): String = if (isAscii(s)) s else Py.string(decompose(s, compat = true))

    /** sre's IGNORECASE class representative: the smallest code point the class's members match. */
    fun ignoreCaseKey(cp: Int): Int = IgnoreCase.table[cp].let { if (it == 0) cp else it }

    /** The members of [cp]'s IGNORECASE class, ascending; null for a class of one. */
    internal fun ignoreCaseClass(cp: Int): IntArray? {
        val key = IgnoreCase.table[cp]
        return if (key == 0) null else IgnoreCase.byKey.getValue(key)
    }

    internal fun ignoreCaseClasses(): List<IntArray> = IgnoreCase.classes

    fun allAlnum(s: String): Boolean = all(s, ALNUM)
    fun allDigit(s: String): Boolean = all(s, DIGIT)
    fun allAlpha(s: String): Boolean = all(s, ALPHA)
    fun allSpace(s: String): Boolean = all(s, SPACE)

    private fun all(s: String, bit: Int): Boolean {
        if (s.isEmpty()) return false
        var i = 0
        while (i < s.length) {
            val cp = s.codePointAt(i)
            if (!has(cp, bit)) return false
            i += Character.charCount(cp)
        }
        return true
    }

    private fun isAscii(s: String): Boolean {
        for (c in s) if (c.code >= 0x80) return false
        return true
    }

    // --- case ---------------------------------------------------------------------------------------------------

    private const val CAPITAL_SIGMA = 0x3A3

    /** Python's handle_capital_sigma: cased case-ignorable* Σ, not followed by case-ignorable* cased. */
    private fun finalSigma(cps: IntArray, i: Int): Boolean {
        var j = i - 1
        while (j >= 0 && isCaseIgnorable(cps[j])) j--
        if (j < 0 || !isCased(cps[j])) return false
        j = i + 1
        while (j < cps.size && isCaseIgnorable(cps[j])) j++
        return j == cps.size || !isCased(cps[j])
    }

    private fun mapped(s: String, table: CodePointTable): String {
        val out = StringBuilder(s.length)
        var i = 0
        while (i < s.length) {
            val cp = s.codePointAt(i)
            append(out, cp, table)
            i += Character.charCount(cp)
        }
        return out.toString()
    }

    private fun append(out: StringBuilder, cp: Int, table: CodePointTable) {
        val k = table[cp]
        if (k == 0) out.appendCodePoint(cp) else for (x in Case.sequences[k - 1]) out.appendCodePoint(x)
    }

    // --- normalization ------------------------------------------------------------------------------------------

    private const val S_BASE = 0xAC00
    private const val L_BASE = 0x1100
    private const val V_BASE = 0x1161
    private const val T_BASE = 0x11A7
    private const val L_COUNT = 19
    private const val V_COUNT = 21
    private const val T_COUNT = 28
    private const val N_COUNT = V_COUNT * T_COUNT
    private const val S_COUNT = L_COUNT * N_COUNT

    /** The canonical (or, [compat], compatibility) decomposition, canonically ordered: NFD's and NFKD's. */
    private fun decompose(s: String, compat: Boolean): IntArray {
        val out = IntBuffer(s.length + 8)
        var i = 0
        while (i < s.length) {
            val cp = s.codePointAt(i)
            decomposeInto(cp, compat, out)
            i += Character.charCount(cp)
        }
        reorder(out)
        return out.toArray()
    }

    private fun decomposeInto(cp: Int, compat: Boolean, out: IntBuffer) {
        val syllable = cp - S_BASE
        if (syllable in 0 until S_COUNT) {
            out.add(L_BASE + syllable / N_COUNT)
            out.add(V_BASE + syllable % N_COUNT / T_COUNT)
            if (syllable % T_COUNT != 0) out.add(T_BASE + syllable % T_COUNT)
            return
        }
        val k = Decomposition.table[cp]
        if (k != 0 && (compat || Decomposition.kinds[k - 1] != Decomposition.COMPAT)) {
            for (x in Decomposition.sequences[k - 1]) decomposeInto(x, compat, out)
        } else {
            out.add(cp)
        }
    }

    /** Canonical ordering: each run of non-starters sorted by combining class, stably. */
    private fun reorder(b: IntBuffer) {
        for (i in 1 until b.size) {
            val c = combining(b[i])
            if (c == 0) continue
            var j = i
            val cp = b[i]
            while (j > 0 && combining(b[j - 1]) > c) {
                b[j] = b[j - 1]
                j--
            }
            b[j] = cp
        }
    }

    /** Canonical composition (Unicode §3.11), Hangul's by arithmetic: NFC's and NFKC's after decomposing. */
    private fun compose(d: IntArray): IntArray {
        if (d.isEmpty()) return d
        var starterPos = 0
        var starter = d[0]
        var lastClass = combining(starter).let { if (it != 0) 256 else 0 }
        var out = 1
        for (i in 1 until d.size) {
            val ch = d[i]
            val cls = combining(ch)
            val composite = pair(starter, ch)
            if (composite >= 0 && (lastClass < cls || lastClass == 0)) {
                d[starterPos] = composite
                starter = composite
            } else {
                if (cls == 0) {
                    starterPos = out
                    starter = ch
                }
                lastClass = cls
                d[out++] = ch
            }
        }
        return d.copyOf(out)
    }

    private fun pair(first: Int, second: Int): Int {
        val l = first - L_BASE
        if (l in 0 until L_COUNT) {
            val v = second - V_BASE
            return if (v in 0 until V_COUNT) S_BASE + (l * V_COUNT + v) * T_COUNT else -1
        }
        val s = first - S_BASE
        if (s in 0 until S_COUNT && s % T_COUNT == 0) {
            val t = second - T_BASE
            return if (t in 1 until T_COUNT) first + t else -1
        }
        return Decomposition.compositions[(first.toLong() shl 21) or second.toLong()] ?: -1
    }

    private class IntBuffer(capacity: Int) {
        private var a = IntArray(capacity)
        var size = 0
            private set

        fun add(x: Int) {
            if (size == a.size) a = a.copyOf(a.size * 2)
            a[size++] = x
        }

        operator fun get(i: Int): Int = a[i]
        operator fun set(i: Int, x: Int) { a[i] = x }
        fun toArray(): IntArray = a.copyOf(size)
    }

    // --- the tables ---------------------------------------------------------------------------------------------

    private object Flags {
        val runs: IntArray = UnicodeTables.read("flags.txt").flatMap { (a, b, mask) ->
            listOf(UnicodeTables.hex(a), UnicodeTables.hex(b), UnicodeTables.hex(mask))
        }.toIntArray()
        val table = CodePointTable.ofRuns(runs)
        val sets = java.util.concurrent.ConcurrentHashMap<Int, CodePointSet>()
    }

    private object Categories {
        val NAMES = listOf("Cn", "Lu", "Ll", "Lt", "Lm", "Lo", "Mn", "Mc", "Me", "Nd", "Nl", "No", "Pc", "Pd", "Ps",
                           "Pe", "Pi", "Pf", "Po", "Sm", "Sc", "Sk", "So", "Zs", "Zl", "Zp", "Cc", "Cf", "Cs", "Co")
        val table = CodePointTable.ofRuns(UnicodeTables.read("category.txt").flatMap { (a, b, name) ->
            val i = NAMES.indexOf(name)
            check(i > 0) { "category.txt names a category caracole doesn't know: $name" }
            listOf(UnicodeTables.hex(a), UnicodeTables.hex(b), i)
        }.toIntArray())
    }

    private object Combining {
        val table = CodePointTable.ofRuns(UnicodeTables.read("combining.txt").flatMap { (a, b, ccc) ->
            listOf(UnicodeTables.hex(a), UnicodeTables.hex(b), ccc.toInt())
        }.toIntArray())
    }

    private object Case {
        val sequences = ArrayList<IntArray>()
        val lower: CodePointTable
        val upper: CodePointTable
        val fold: CodePointTable

        init {
            val maps = List(3) { HashMap<Int, Int>() }
            for (line in UnicodeTables.read("case.txt")) {
                val cp = UnicodeTables.hex(line[0])
                for (k in 0 until 3) {
                    if (line[k + 1] == "=") continue
                    sequences += UnicodeTables.sequence(line[k + 1])
                    maps[k][cp] = sequences.size
                }
            }
            lower = CodePointTable.ofPoints(maps[0])
            upper = CodePointTable.ofPoints(maps[1])
            fold = CodePointTable.ofPoints(maps[2])
        }
    }

    private object Decomposition {
        const val COMPOSES: Byte = 0
        const val EXCLUDED: Byte = 1
        const val COMPAT: Byte = 2
        val sequences = ArrayList<IntArray>()
        val kinds: ByteArray
        val table: CodePointTable
        val compositions = HashMap<Long, Int>()

        init {
            val points = HashMap<Int, Int>()
            val kinds = ArrayList<Byte>()
            for (line in UnicodeTables.read("decomposition.txt")) {
                val cp = UnicodeTables.hex(line[0])
                val seq = line.drop(2).map(UnicodeTables::hex).toIntArray()
                val kind = when (line[1]) {
                    "c" -> COMPOSES
                    "x" -> EXCLUDED
                    "k" -> COMPAT
                    else -> error("decomposition.txt: a kind caracole doesn't know: ${line[1]}")
                }
                sequences += seq
                kinds += kind
                points[cp] = sequences.size
                if (kind == COMPOSES) compositions[(seq[0].toLong() shl 21) or seq[1].toLong()] = cp
            }
            this.kinds = kinds.toByteArray()
            table = CodePointTable.ofPoints(points)
        }
    }

    private object IgnoreCase {
        val classes: List<IntArray> = UnicodeTables.read("ignorecase.txt").map { line ->
            line.map(UnicodeTables::hex).toIntArray()
        }
        val table = CodePointTable.ofPoints(classes.flatMap { m -> m.map { it to m[0] } }.toMap())
        val byKey: Map<Int, IntArray> = classes.associateBy { it[0] }
    }
}
