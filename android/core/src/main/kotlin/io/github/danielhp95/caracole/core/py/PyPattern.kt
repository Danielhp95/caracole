package io.github.danielhp95.caracole.core.py

/**
 * One Python pattern translated for java.util.regex ([PyRegex.compile] documents what it means): sre_parse's rules
 * (what it refuses, how it reads an escape, a `{`, a class), written as java.util.regex reads them. It also measures
 * each group's width in code points, as sre does, since a lookbehind must have one width in Python
 * (java.util.regex takes some that Python refuses).
 */
internal class PyPattern(private val pattern: String) {
    private val cps = Py.codePoints(pattern)
    private var i = 0
    private val out = StringBuilder()
    private var ignoreCase = false
    private var multiline = false
    private var atStart = true

    /** What came last, for Python's "nothing to repeat" and "multiple repeat". */
    private enum class Last { NOTHING, ITEM, AT, REPEAT, MODIFIED }

    private var last = Last.NOTHING

    private enum class Kind { ROOT, GROUP, LOOKAHEAD, LOOKBEHIND }

    /** A group being read: the case folding and MULTILINE outside it, its number (0 for none), and its width so
     * far, in code points: the alternatives done (low and high), the current one without its last item, and that
     * item. */
    private class Frame(val kind: Kind, val ignoreCaseBefore: Boolean, val multilineBefore: Boolean, val number: Int) {
        var doneLo = -1L
        var doneHi = 0L
        var lo = 0L
        var hi = 0L
        var lastLo = 0L
        var lastHi = 0L

        fun item(lo: Long, hi: Long) {
            commit()
            lastLo = lo
            lastHi = hi
        }

        fun commit() {
            lo = sum(lo, lastLo)
            hi = sum(hi, lastHi)
            lastLo = 0
            lastHi = 0
        }

        fun repeat(min: Long, max: Long) {
            lastLo = product(lastLo, min)
            lastHi = if (max >= INFINITE) (if (lastHi == 0L) 0L else INFINITE) else product(lastHi, max)
        }

        fun alternative() {
            commit()
            doneLo = if (doneLo < 0) lo else minOf(doneLo, lo)
            doneHi = maxOf(doneHi, hi)
            lo = 0
            hi = 0
        }
    }

    private val root = Frame(Kind.ROOT, false, false, 0)
    private val open = ArrayDeque<Frame>()
    private val frame: Frame get() = open.lastOrNull() ?: root
    private var groups = 0
    private val widths = HashMap<Int, Pair<Long, Long>>()
    private val names = HashMap<String, Int>()

    fun translate(): String {
        out.append(BY_CODE_POINT)
        while (i < cps.size) {
            val start = atStart
            atStart = false
            item(start)
        }
        if (open.isNotEmpty()) fail("missing ), unterminated subpattern")
        return out.toString()
    }

    private fun fail(why: String): Nothing = throw IllegalArgumentException("$why, in the Python pattern $pattern")
    private fun unsupported(what: String): Nothing =
        throw IllegalArgumentException("$what is Python's, but not on the phone: $pattern")

    private fun peek(): Int = if (i < cps.size) cps[i] else -1
    private fun next(): Int = if (i < cps.size) cps[i++] else fail("the pattern ends too soon")

    /** One item of width one code point (a literal, a class, `.`). */
    private fun one(text: CharSequence) {
        out.append(text)
        frame.item(1, 1)
        last = Last.ITEM
    }

    /** A zero-width assertion (`^`, `\b`, …), which nothing may repeat. */
    private fun at(text: String) {
        out.append(text)
        frame.item(0, 0)
        last = Last.AT
    }

    private fun item(start: Boolean) {
        when (val c = cps[i]) {
            '('.code -> group(start)
            ')'.code -> close()
            '['.code -> { i++; one(charClass()) }
            '\\'.code -> escape()
            '{'.code -> brace()
            '}'.code -> { i++; one("\\}") }
            ']'.code -> { i++; one("\\]") }
            '.'.code -> { i++; one(".") }
            '^'.code -> { i++; at(if (multiline) LINE_START else "^") }
            '$'.code -> { i++; at("$") }
            '|'.code -> {
                i++
                out.append('|')
                frame.alternative()
                last = Last.NOTHING
            }
            '*'.code -> { i++; quantifier("*", 0, INFINITE, modifier = false) }
            '+'.code -> { i++; quantifier("+", 1, INFINITE, modifier = true) }
            '?'.code -> { i++; quantifier("?", 0, 1, modifier = true) }
            else -> { i++; literal(c) }
        }
    }

    /** A quantifier, or after one a lazy `?` or possessive `+`, where Python allows one. */
    private fun quantifier(text: String, min: Long, max: Long, modifier: Boolean) {
        last = when (last) {
            Last.NOTHING, Last.AT -> fail("nothing to repeat")
            Last.MODIFIED -> fail("multiple repeat")
            Last.REPEAT -> if (modifier) Last.MODIFIED else fail("multiple repeat")
            Last.ITEM -> Last.REPEAT
        }
        if (last == Last.REPEAT) frame.repeat(min, max)
        out.append(text)
    }

    // --- groups -------------------------------------------------------------------------------------------------

    private fun group(start: Boolean) {
        i++
        val before = last
        last = Last.NOTHING
        if (peek() != '?'.code) {
            opened("(", Kind.GROUP, ++groups)
            return
        }
        i++
        when (val c = next()) {
            ':'.code -> opened("(?:", Kind.GROUP)
            '='.code -> opened("(?=", Kind.LOOKAHEAD)
            '!'.code -> opened("(?!", Kind.LOOKAHEAD)
            '>'.code -> opened("(?>", Kind.GROUP)
            '<'.code -> when (next()) {
                '='.code -> opened("(?<=", Kind.LOOKBEHIND)
                '!'.code -> opened("(?<!", Kind.LOOKBEHIND)
                else -> fail("unknown extension ?<")
            }
            'P'.code -> when (next()) {
                '<'.code -> namedGroup()
                '='.code -> namedReference()
                else -> fail("unknown extension ?P")
            }
            '#'.code -> {
                while (i < cps.size && cps[i] != ')'.code) i++
                if (i >= cps.size) fail("missing ), unterminated comment")
                i++
                atStart = start
                last = before
            }
            '('.code -> unsupported("a conditional group")
            else -> flags(c, start, before)
        }
    }

    private fun opened(text: String, kind: Kind, number: Int = 0) {
        open.addLast(Frame(kind, ignoreCase, multiline, number))
        out.append(text)
    }

    private fun close() {
        i++
        val group = open.removeLastOrNull() ?: fail("unbalanced parenthesis")
        group.alternative()
        ignoreCase = group.ignoreCaseBefore
        multiline = group.multilineBefore
        val lo = group.doneLo
        val hi = group.doneHi
        if (group.kind == Kind.LOOKBEHIND && lo != hi) fail("look-behind requires fixed-width pattern")
        if (group.number > 0) widths[group.number] = lo to hi
        out.append(')')
        if (group.kind == Kind.GROUP) frame.item(lo, hi) else frame.item(0, 0)
        last = Last.ITEM
    }

    private fun name(end: Int): String {
        val from = i
        while (i < cps.size && cps[i] != end) i++
        if (i >= cps.size) fail("missing ${end.toChar()}, unterminated name")
        val name = Py.string(cps, from, i)
        i++
        if (name.isEmpty()) fail("missing group name")
        val javaName = (name[0] in 'a'..'z' || name[0] in 'A'..'Z') &&
            name.all { it in 'a'..'z' || it in 'A'..'Z' || it in '0'..'9' }
        if (!javaName) {
            if (name[0] in '0'..'9' || name.any { it in "()<>=!:#\\-+*?[]{}|.,;'\" " }) {
                fail("bad character in group name '$name'")
            }
            unsupported("the group name '$name' (java.util.regex's take ASCII letters and digits)")
        }
        return name
    }

    private fun namedGroup() {
        val name = name('>'.code)
        if (name in names) fail("redefinition of group name '$name'")
        names[name] = ++groups
        opened("(?<$name>", Kind.GROUP, groups)
    }

    private fun namedReference() {
        val name = name(')'.code)
        reference(names[name] ?: fail("unknown group name '$name'"), "\\k<$name>")
    }

    /** A backreference: to a group closed before it, and never under IGNORECASE. */
    private fun reference(number: Int, text: String) {
        val width = widths[number] ?: fail("cannot refer to an open group")
        if (ignoreCase) unsupported("a backreference under IGNORECASE")
        out.append(text)
        frame.item(width.first, width.second)
        last = Last.ITEM
    }

    private fun flags(first: Int, start: Boolean, before: Last) {
        var c = first
        val on = StringBuilder()
        val off = StringBuilder()
        while (c >= 0 && c.toChar() in "aiLmsux") {
            on.appendCodePoint(c)
            c = next()
        }
        if (c == '-'.code) {
            c = next()
            while (c >= 0 && c.toChar() in "imsx") {
                off.appendCodePoint(c)
                c = next()
            }
            if (off.isEmpty()) fail("missing flag")
        }
        if (on.isEmpty() && off.isEmpty()) fail("unknown extension ?${c.toChar()}")
        if ('L' in on) fail("bad inline flags: cannot use 'L' flag with a str pattern")
        if ('a' in on && 'u' in on) fail("bad inline flags: flags 'a' and 'u' are incompatible")
        if ('a' in on) unsupported("ASCII matching, (?a)")
        if ('x' in on || 'x' in off) unsupported("a verbose pattern, (?x)")
        val ms = on.filter { it == 'm' || it == 's' }
        val msOff = off.filter { it == 'm' || it == 's' }
        when (c) {
            ')'.code -> {
                if (off.isNotEmpty()) fail("missing :")
                if (!start) fail("global flags not at the start of the expression")
                atStart = true
                last = before
                if ('i' in on) ignoreCase = true
                if ('m' in on) multiline = true
                if (ms.isNotEmpty()) out.append("(?").append(ms).append(')')
            }
            ':'.code -> {
                opened("(?" + ms + (if (msOff.isNotEmpty()) "-$msOff" else "") + ":", Kind.GROUP)
                if ('i' in on) ignoreCase = true
                if ('i' in off) ignoreCase = false
                if ('m' in on) multiline = true
                if ('m' in off) multiline = false
            }
            else -> fail("missing -, : or )")
        }
    }

    // --- escapes, literals, quantifiers -------------------------------------------------------------------------

    private fun escape() {
        i++
        if (i >= cps.size) fail("bad escape (end of pattern)")
        when (val e = cps[i++]) {
            'w'.code -> one(PyRegex.Sets.word.asClass())
            'W'.code -> one(PyRegex.Sets.notWord.asClass())
            's'.code -> one(PyRegex.Sets.space.asClass())
            'S'.code -> one(PyRegex.Sets.notSpace.asClass())
            'd'.code -> one(PyRegex.Sets.digit.asClass())
            'D'.code -> one(PyRegex.Sets.notDigit.asClass())
            'b'.code -> at(BOUNDARY)
            'B'.code -> at(NOT_BOUNDARY)
            'A'.code -> at("\\A")
            'Z'.code, 'z'.code -> at("\\z")
            '0'.code -> literal(octal(0, 2))
            in '1'.code..'9'.code -> digits(e)
            else -> literal(simpleEscape(e) ?: codeEscape(e) ?: badEscape(e))
        }
    }

    /** \a \f \n \r \t \v \\: what a pattern and a class read alike. */
    private fun simpleEscape(e: Int): Int? = when (e) {
        'a'.code -> 7
        'f'.code -> 12
        'n'.code -> 10
        'r'.code -> 13
        't'.code -> 9
        'v'.code -> 11
        '\\'.code -> '\\'.code
        else -> null
    }

    /** \x \u \U, \N refused; null for an escape that is none of these. */
    private fun codeEscape(e: Int): Int? = when (e) {
        'x'.code -> hex(2)
        'u'.code -> hex(4)
        'U'.code -> hex(8).also { if (it > 0x10FFFF) fail("bad escape \\U") }
        'N'.code -> unsupported("a named character, \\N{…}")
        else -> null
    }

    /** An escaped ASCII letter Python doesn't know is an error; anything else escaped is itself. */
    private fun badEscape(e: Int): Int =
        if (e in 'a'.code..'z'.code || e in 'A'.code..'Z'.code) fail("bad escape \\${e.toChar()}") else e

    private fun hex(n: Int): Int {
        var v = 0
        repeat(n) {
            val d = peek()
            val x = when (d) {
                in '0'.code..'9'.code -> d - '0'.code
                in 'a'.code..'f'.code -> d - 'a'.code + 10
                in 'A'.code..'F'.code -> d - 'A'.code + 10
                else -> fail("incomplete escape")
            }
            i++
            v = v * 16 + x
        }
        return v
    }

    /** An octal escape whose first digit's value is [first]: up to [more] octal digits more. */
    private fun octal(first: Int, more: Int): Int {
        var v = first
        repeat(more) {
            val d = peek()
            if (d !in '0'.code..'7'.code) return v
            v = v * 8 + (d - '0'.code)
            i++
        }
        return v
    }

    /** \1–\99, or an octal escape of three digits (sre_parse's "octal escape *or* decimal group reference"). */
    private fun digits(first: Int) {
        var number = first - '0'.code
        val second = peek()
        if (second in '0'.code..'9'.code) {
            val third = if (i + 1 < cps.size) cps[i + 1] else -1
            if (first in '0'.code..'7'.code && second in '0'.code..'7'.code && third in '0'.code..'7'.code) {
                i += 2
                val v = (first - '0'.code) * 64 + (second - '0'.code) * 8 + (third - '0'.code)
                if (v > 0xFF) fail("octal escape value outside of range 0-0o377")
                literal(v)
                return
            }
            number = number * 10 + (second - '0'.code)
            i++
        }
        if (number > groups) fail("invalid group reference $number")
        reference(number, "(?:\\$number)")
    }

    /** `{m}`, `{m,}`, `{,n}`, `{m,n}` and `{,}` are quantifiers; any other `{` is itself, as in Python. */
    private fun brace() {
        val at = i
        i++
        if (peek() == '}'.code) {
            literal('{'.code)
            return
        }
        val lo = number()
        var hi = lo
        val comma = peek() == ','.code
        if (comma) {
            i++
            hi = number()
        }
        if (peek() != '}'.code) {
            i = at + 1
            literal('{'.code)
            return
        }
        i++
        val min = lo.toLongOrNull() ?: if (lo.isEmpty()) 0L else fail("the repeat count is too large")
        val max = hi.toLongOrNull() ?: if (hi.isEmpty()) INFINITE else fail("the repeat count is too large")
        if (min >= MAX_REPEAT || (max < INFINITE && max >= MAX_REPEAT)) fail("the repeat count is too large")
        if (max < min) fail("min repeat greater than max repeat")
        quantifier("{$min" + (if (comma) "," + hi else "") + "}", min, max, modifier = false)
    }

    private fun number(): String {
        val from = i
        while (peek() in '0'.code..'9'.code) i++
        return Py.string(cps, from, i)
    }

    private fun literal(c: Int) {
        if (ignoreCase) {
            val members = PyUnicode.ignoreCaseClass(c)
            if (members != null) {
                one(CodePointSet.points(*members).asClass())
                return
            }
        }
        when {
            c in 'a'.code..'z'.code || c in 'A'.code..'Z'.code || c in '0'.code..'9'.code || c > 0xFFFF ->
                one(StringBuilder().appendCodePoint(c))
            else -> one("\\x{" + c.toString(16) + "}")
        }
    }

    // --- character classes --------------------------------------------------------------------------------------

    private fun charClass(): String {
        val negate = peek() == '^'.code
        if (negate) i++
        val literals = ArrayList<Int>()
        var categories = CodePointSet.points()
        var first = true
        while (true) {
            if (i >= cps.size) fail("unterminated character set")
            if (cps[i] == ']'.code && !first) {
                i++
                break
            }
            first = false
            val item = classItem()
            if (peek() == '-'.code) {
                i++
                if (i >= cps.size) fail("unterminated character set")
                if (cps[i] == ']'.code) {
                    i++
                    if (item is CodePointSet) categories = categories.union(item) else add(literals, item as Int)
                    add(literals, '-'.code)
                    break
                }
                val end = classItem()
                if (item !is Int || end !is Int || end < item) fail("bad character range")
                literals += item
                literals += end
            } else if (item is CodePointSet) {
                categories = categories.union(item)
            } else {
                add(literals, item as Int)
            }
        }
        var set = CodePointSet.of(literals.toIntArray())
        if (ignoreCase) set = set.closedUnderIgnoreCase()
        set = set.union(categories)
        if (negate) set = set.complement()
        return set.asClass()
    }

    private fun add(ranges: ArrayList<Int>, cp: Int) {
        ranges += cp
        ranges += cp
    }

    /** One member of a class: a code point (Int) or a class escape's set (CodePointSet). */
    private fun classItem(): Any {
        val c = cps[i++]
        if (c != '\\'.code) return c
        if (i >= cps.size) fail("bad escape (end of pattern)")
        return when (val e = cps[i++]) {
            'w'.code -> PyRegex.Sets.word
            'W'.code -> PyRegex.Sets.notWord
            's'.code -> PyRegex.Sets.space
            'S'.code -> PyRegex.Sets.notSpace
            'd'.code -> PyRegex.Sets.digit
            'D'.code -> PyRegex.Sets.notDigit
            'b'.code -> 8
            in '0'.code..'7'.code -> octal(e - '0'.code, 2).also { if (it > 0xFF) fail("octal escape value outside of range 0-0o377") }
            '8'.code, '9'.code -> fail("bad escape \\${e.toChar()}")
            else -> simpleEscape(e) ?: codeEscape(e) ?: badEscape(e)
        }
    }

    companion object {
        /** MULTILINE's `^`: the start, or just after a `\n`, the end of the text included. java.util.regex's own
         * `(?m)^` never matches at the end after a final line end, where Python's does. */
        private const val LINE_START = "(?<![^\\n])"

        /** A lookahead that always holds, carrying U+10FFFF as it is: java.util.regex then steps by code point. */
        private const val BY_CODE_POINT = "(?=|\uDBFF\uDFFF)"

        /** sre's MAXREPEAT on a 64-bit build, which a repeat count must stay under; and an unbounded width. */
        private const val MAX_REPEAT = 4294967295L
        private const val INFINITE = Long.MAX_VALUE / 4

        private fun sum(a: Long, b: Long): Long = minOf(INFINITE, a + b)
        private fun product(a: Long, b: Long): Long =
            if (a == 0L || b == 0L) 0L else if (a >= INFINITE / b) INFINITE else a * b

        private val WORD_CLASS: String by lazy { PyRegex.Sets.word.asClass() }
        private val BOUNDARY: String by lazy {
            "(?:(?<=$WORD_CLASS)(?!$WORD_CLASS)|(?<!$WORD_CLASS)(?=$WORD_CLASS))"
        }
        private val NOT_BOUNDARY: String by lazy {
            "(?:(?<=$WORD_CLASS)(?=$WORD_CLASS)|(?<!$WORD_CLASS)(?!$WORD_CLASS))"
        }
    }
}
