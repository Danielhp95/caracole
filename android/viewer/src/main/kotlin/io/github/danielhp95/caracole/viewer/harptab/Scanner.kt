package io.github.danielhp95.caracole.viewer.harptab

import io.github.danielhp95.caracole.core.py.Py
import io.github.danielhp95.caracole.core.py.PyRe
import io.github.danielhp95.caracole.core.py.PyText
import io.github.danielhp95.caracole.core.py.PyUnicode
import io.github.danielhp95.caracole.viewer.harptab.HarpTabText.at
import io.github.danielhp95.caracole.viewer.harptab.HarpTabText.before

/**
 * harptab.scan and its passes, in order, each reading only what those before it left: holes in brackets, holes
 * together, single holes, effects written apart, joins, the marks every notation shares, what is left (the tabber's
 * words, or unread), words together, joins' groups.
 *
 * The text is Kotlin's (UTF-16) while the passes run, every place a code point's start and every step a code point,
 * as Python steps; the scan's groups come out at code-point columns, Python's ([Group]).
 */
internal object Scanner {
    private val B = HarptabData

    /** A group as the passes find it: its places UTF-16's. */
    private data class G(val holes: List<Hole>, val kind: String, val col: Int, val digit: Int, val text: String,
                         val hold: Boolean = false, val effects: List<String> = emptyList(), val join: Boolean = false) {
        val end: Int get() = col + text.length
    }

    /** harptab._Read: a hole as a notation reads it, and what its marks say. */
    private class Read(var start: Int, var end: Int, val num: Int, val digit: Int = 0) {
        var breath: String? = null
        var bend = 0
        var over = false
        var slide = false
        var effects: MutableList<String> = ArrayList()
        var used: MutableList<Pair<String, Symbol>> = ArrayList()

        fun state(): State = State(breath, bend, over, slide, ArrayList(effects), ArrayList(used))

        fun restore(s: State) {
            breath = s.breath
            bend = s.bend
            over = s.over
            slide = s.slide
            effects = ArrayList(s.effects)
            used = ArrayList(s.used)
        }
    }

    private data class State(val breath: String?, val bend: Int, val over: Boolean, val slide: Boolean,
                             val effects: List<String>, val used: List<Pair<String, Symbol>>)

    /** harptab._Line: a line as scan reads it, pass by pass. */
    private class Line(val text: String, val notation: Notation, val tokens: Tokens, val label: String?,
                       val prose: BooleanArray) {
        val covered = BooleanArray(text.length)
        val groups = ArrayList<G>()
        val used = LinkedHashMap<Used, Int>()
        val joins = ArrayList<Pair<Int, String>>()

        fun taken(a: Int, b: Int): Boolean {
            for (i in a until minOf(b, text.length)) if (covered[i] || prose[i]) return true
            return false
        }

        fun mark(a: Int, b: Int) {
            for (i in a until minOf(b, text.length)) covered[i] = true
        }

        fun add(group: G) {
            groups += group
            mark(group.col, group.end)
        }

        fun count(key: Used, n: Int = 1) {
            used[key] = (used[key] ?: 0) + n
        }

        fun note(read: Read, bare: String? = null) {
            for ((written, sym) in read.used) count(Used(written, sym.means, sym.at, sym.count))
            if (bare != null) count(Used("", bare, "bare", 1))
        }
    }

    private class Piece(val start: Int, val end: Int, val text: String, val sym: Symbol)

    fun scan(line: String, notation: Notation): Scan {
        val expanded = HarpTabText.expand(line)
        val tokens = Tokens.of(notation)
        val (label, text) = leadLabel(expanded, tokens)
        val work = Line(text, notation, tokens, label, proseMask(text, tokens))
        holesInBrackets(work)
        holesTogether(work)
        singleHoles(work)
        work.groups.sortBy { it.col }
        effectsApart(work)
        joins(work)
        sharedMarks(work)
        leftovers(work)
        work.groups.sortBy { it.col }
        wordsTogether(work)
        joined(work)
        return scanned(work)
    }

    // --- a hole and its marks -------------------------------------------------------------------------------------

    /** harptab._marks: one mark added to [read]; false when it can't take it. */
    private fun marks(text: String, s: Symbol, read: Read): Boolean {
        when {
            s.means in B.BREATHS -> {
                if (read.breath != null) return false
                read.breath = s.means
            }
            s.means == "bend" -> {
                if (read.bend + s.count > 3) return false
                read.bend += s.count
            }
            s.means == "over" -> {
                if (read.over) return false
                read.over = true
            }
            s.means == "slide" -> {
                if (read.slide) return false
                read.slide = true
            }
            s.means in B.EFFECTS -> read.effects.add(s.means)
        }
        read.used.add(text to s)
        return true
    }

    /** `pattern.match(text, pos, endpos)`. */
    private fun matchAt(regex: Regex, text: String, pos: Int, endpos: Int = text.length): MatchResult? =
        regex.matchAt(if (endpos >= text.length) text else text.substring(0, endpos), pos)

    private fun start(m: MatchResult, group: String): Int = m.groups[group]!!.range.first
    private fun end(m: MatchResult, group: String): Int = m.groups[group]!!.range.let { it.last + 1 }

    /** harptab._read_hole: the hole [m] ([Tokens.start]) found, its before-symbols read from the number back, its
     * after-symbols up to [limit], the longest that leaves no letter touching it; null for a number in a word. */
    private fun readHole(text: String, m: MatchResult, notation: Notation, tokens: Tokens, limit: Int): Read? {
        val pieces = ArrayList<Piece>()
        var pos = start(m, "pre")
        val preEnd = end(m, "pre")
        while (pos < preEnd) {
            val s = tokens.before!!.matchAt(text, pos)!!
            pieces += Piece(s.range.first, s.range.last + 1, s.value, notation.read(s.value, "before"))
            pos = s.range.last + 1
        }
        val num = m.groups["num"]!!
        val read = Read(num.range.first, num.range.last + 1, num.value.toInt(), num.range.first)
        val taken = ArrayList<Piece>()
        for (piece in pieces.asReversed()) {
            if (!marks(piece.text, piece.sym, read)) break
            taken += piece
        }
        if (taken.isNotEmpty()) read.start = taken.last().start
        if (read.start > 0 && PyUnicode.isAlpha(before(text, read.start))) return null
        val options = arrayListOf(read.end to read.state())
        pos = read.end
        while (tokens.after != null && pos < limit) {
            val s = matchAt(tokens.after, text, pos, limit) ?: break
            val sym = notation.read(s.value, "after")
            if (sym.means in B.BREATHS && s.value in B.SIGNS) {
                val next = s.range.last + 1
                val glued = next < text.length && at(text, next).let { cp ->
                    String(Character.toChars(cp)) in B.SIGNS || PyUnicode.isAlnum(cp)
                }
                if (glued || (read.start > 0 && PyUnicode.isDigit(before(text, read.start)))) break
            }
            if (!marks(s.value, sym, read)) break
            pos = s.range.last + 1
            options += pos to read.state()
        }
        for ((end, state) in options.asReversed()) {
            if (end >= text.length || !PyUnicode.isAlpha(at(text, end))) {
                read.end = end
                read.restore(state)
                return read
            }
        }
        return null
    }

    // --- the passes -----------------------------------------------------------------------------------------------

    /** harptab._lead_label: the label a line leads with, and the line with it blanked, its columns kept. */
    private fun leadLabel(text: String, tokens: Tokens): Pair<String?, String> {
        val lead = PyRe.match(B.LEAD_LABEL, text) ?: return null to text
        val end = lead.range.last + 1
        val label = lead.groups["label"]!!.value
        if (tokens.start.find(text.substring(end)) != null && !PyUnicode.allDigit(Py.strip(label)) &&
            PyRe.finditer(B.TIME, text).none { it.range.first < end }) {
            return PyText.strip(label, "() ") to " ".repeat(Py.len(text.substring(0, end))) + text.substring(end)
        }
        return null to text
    }

    /** harptab._prose_mask: where a line writes a time or the tabber's words in brackets. */
    private fun proseMask(text: String, tokens: Tokens): BooleanArray {
        val prose = BooleanArray(text.length)
        for (m in PyRe.finditer(B.TIME, text)) for (i in m.range) prose[i] = true
        for (m in PyRe.finditer(B.ASIDE, text)) {
            val whole = m.value
            if (Py.split(m.groups["body"]!!.value).any { HarpTabText.isWord(it, alone = true) } &&
                B.DECOR.matchEntire(whole) == null && !(tokens.apart != null && tokens.apart.matchEntire(whole) != null)) {
                for (i in m.range) prose[i] = true
            }
        }
        return prose
    }

    private fun holesInBrackets(line: Line) {
        for (m in PyRe.finditer(B.BRACKET, line.text)) {
            if (line.taken(m.range.first, m.range.last + 1)) continue
            val reads = readsInside(line, m)
            if (reads.isNotEmpty()) bracketed(line, m, reads)
        }
    }

    private fun readsInside(line: Line, m: MatchResult): List<Read> {
        val text = line.text
        val tokens = line.tokens
        val reads = ArrayList<Read>()
        val end = end(m, "body")
        var pos = matchAt(B.SEPARATOR, text, start(m, "body"), end)!!.let { it.range.last + 1 }
        while (pos < end) {
            val found = matchAt(tokens.start, text, pos, end)
            val read = found?.let { readHole(text, it, line.notation, tokens, end) }
            if (read == null || read.start != pos) break
            reads += read
            pos = matchAt(B.SEPARATOR, text, read.end, end)!!.let { it.range.last + 1 }
        }
        return if (pos >= end) reads else emptyList()
    }

    private fun afterBrackets(line: Line, m: MatchResult, reads: List<Read>): Pair<Read, Int> {
        val text = line.text
        val tokens = line.tokens
        var stop = m.range.last + 1
        val outer = Read(m.range.first, m.range.last + 1, 0)
        while (tokens.after != null && reads.size == 1) {
            val s = tokens.after.matchAt(text, stop)
            if (s == null || !marks(s.value, line.notation.read(s.value, "after"), outer)) break
            stop = s.range.last + 1
        }
        if (stop < text.length && PyUnicode.isAlpha(at(text, stop))) {
            return Read(m.range.first, m.range.last + 1, 0) to m.range.last + 1
        }
        return outer to stop
    }

    private fun bracketed(line: Line, m: MatchResult, reads: List<Read>) {
        val text = line.text
        val notation = line.notation
        val (outer, stop) = afterBrackets(line, m, reads)
        val open = m.groups["open"]!!.value
        val around = notation.meaning(B.CLOSE.getValue(open), "around")
        val given = if (around != null && around.means in B.BREATHS) around.means else null
        val breaths = reads.map { it.breath ?: outer.breath ?: given ?: notation.bare }
        if (null in breaths) return
        noteBracketed(line, open, reads, outer, given, breaths)
        val kind = if (reads.size == 1 && open == "(") "note" else B.KINDS.getValue(open)
        if (kind == "note" && given == null && reads[0].breath == null && outer.breath == null) {
            line.add(holeAlone(text, reads[0], breaths[0]!!))
            return
        }
        val holes = reads.zip(breaths).map { (r, b) ->
            Hole(r.num, b!!, minOf(r.bend + outer.bend, 3), r.over || outer.over, r.slide || outer.slide)
        }
        val effects = outer.effects + reads.flatMap { it.effects }
        line.add(G(holes, kind, m.range.first, reads[0].digit, text.substring(m.range.first, stop), "hold" in effects,
                   others(effects)))
    }

    private fun noteBracketed(line: Line, open: String, reads: List<Read>, outer: Read, given: String?,
                              breaths: List<String?>) {
        for ((r, b) in reads.zip(breaths)) line.note(r, if (r.breath == null && outer.breath == null && given == null) b else null)
        line.note(outer)
        if (given != null && reads.any { it.breath == null && outer.breath == null }) {
            line.count(Used(B.CLOSE.getValue(open), given, "around", 1))
        }
    }

    private fun holeAlone(text: String, read: Read, breath: String): G =
        G(listOf(Hole(read.num, breath, read.bend, read.over, read.slide)), "note", read.start, read.digit,
          text.substring(read.start, read.end), "hold" in read.effects, others(read.effects))

    private fun holesTogether(line: Line) {
        val text = line.text
        val notation = line.notation
        val tokens = line.tokens
        val together = tokens.together ?: return
        for (m in PyRe.finditer(together, text)) {
            val a = m.range.first
            val b = m.range.last + 1
            if (line.taken(a, b) || (a > 0 && PyUnicode.isAlnum(before(text, a)))) continue
            val body = m.groups["body"]!!.value
            val lastNum = B.LAST_NUM.find(body)!!.value
            val last = tokens.start.matchAt(text, b - lastNum.length)
            val read = last?.let { readHole(text, it, notation, tokens, text.length) } ?: continue
            val breath = read.breath ?: notation.bare ?: continue
            val nums = PyRe.findall(B.NUM_ALONE, body).map { it.toInt() }
            line.note(read, if (read.breath == null) breath else null)
            val sep = B.NOT_DIGITS.find(body)!!.value
            val sym = notation.read(sep, "between")
            line.count(Used(sep, sym.means, "between", 1), nums.size - 1)
            line.add(G(nums.map { Hole(it, breath, read.bend, read.over, read.slide) }, "chord", a, a,
                       text.substring(a, read.end), "hold" in read.effects, others(read.effects)))
        }
    }

    private fun singleHoles(line: Line) {
        val text = line.text
        val notation = line.notation
        val tokens = line.tokens
        var pos = 0
        while (true) {
            val found = tokens.start.find(text, pos) ?: break
            val a = found.range.first
            val b = found.range.last + 1
            if (line.taken(a, b)) {
                pos = if (line.covered[a] || line.prose[a]) a + Character.charCount(text.codePointAt(a)) else b
                continue
            }
            val read = readHole(text, found, notation, tokens, freeUntil(line, b))
            if (read == null) {
                pos = b
                continue
            }
            val breath = read.breath ?: notation.bare
            pos = read.end
            if (breath == null) continue
            line.note(read, if (read.breath == null) breath else null)
            line.add(holeAlone(text, read, breath))
        }
    }

    private fun effectsApart(line: Line) {
        val apart = line.tokens.apart ?: return
        for (m in PyRe.finditer(apart, line.text)) {
            val a = m.range.first
            val b = m.range.last + 1
            if (line.taken(a, b)) continue
            val sym = line.notation.read(m.value, "after")
            line.mark(a, b)
            line.count(Used(m.value, sym.means, "after", sym.count))
            if (sym.means in B.EFFECTS) effectBefore(line.groups, a, sym.means)
        }
    }

    private fun joins(line: Line) {
        val text = line.text
        val join = line.tokens.join ?: return
        for (m in PyRe.finditer(join, text)) {
            val a = m.range.first
            val b = m.range.last + 1
            val written = m.value
            if (line.taken(a, b) || a == 0 || b >= text.length || PyUnicode.isSpace(before(text, a)) ||
                PyUnicode.isSpace(at(text, b)) || before(text, a) == written.codePointAt(0) ||
                at(text, b) == written.codePointBefore(written.length)) continue
            val sym = line.notation.read(written, "between")
            line.mark(a, b)
            line.count(Used(written, sym.means, "between", 1))
            line.joins += a to sym.means
        }
    }

    private fun sharedMarks(line: Line) {
        for (m in PyRe.finditer(B.DECOR, line.text)) {
            val a = m.range.first
            val b = m.range.last + 1
            if (line.taken(a, b)) continue
            line.mark(a, b)
            if (B.HOLD.matchEntire(m.value) != null) effectBefore(line.groups, a, "hold")
        }
    }

    private fun leftovers(line: Line) {
        val text = line.text
        val covered = line.covered
        for (m in PyRe.finditer(B.WORD, text)) {
            val first = m.range.first
            val last = m.range.last + 1
            var a = first
            var i = first
            while (i <= last) {
                if (i == last || covered[i]) {
                    if (i > a) {
                        val alone = a == first && i == last
                        var prose = false
                        for (k in a until i) if (line.prose[k]) prose = true
                        val piece = text.substring(a, i)
                        val words = prose || HarpTabText.isWord(piece, alone)
                        line.groups += G(emptyList(), if (words) "words" else "unread", a, a, piece)
                    }
                    a = if (i < last) i + Character.charCount(text.codePointAt(i)) else i + 1
                }
                i += if (i < last) Character.charCount(text.codePointAt(i)) else 1
            }
        }
    }

    private fun wordsTogether(line: Line) {
        val groups = line.groups
        val text = line.text
        for (n in groups.size - 1 downTo 1) {
            val one = groups[n - 1]
            val two = groups[n]
            if (one.kind == "words" && two.kind == "words" && Py.strip(text.substring(one.end, maxOf(one.end, two.col))).isEmpty()) {
                groups.removeAt(n)
                groups[n - 1] = G(emptyList(), "words", one.col, one.col, text.substring(one.col, two.end))
            }
        }
    }

    private fun joined(line: Line) {
        val groups = line.groups
        for ((at, means) in line.joins) {
            val n = groups.indexOfLast { it.col < at }
            if (n >= 0) {
                groups[n] = groups[n].copy(join = true)
                if (means in B.EFFECTS && groups[n].holes.isNotEmpty()) effectBefore(groups, at, means)
            }
        }
    }

    private fun scanned(line: Line): Scan {
        val text = line.text
        val covered = line.covered
        val groups = line.groups
        val unknown = ArrayList<String>()
        for (m in PyRe.finditer(B.WORD, text)) {
            val rest = StringBuilder()
            var i = m.range.first
            while (i <= m.range.last) {
                val cp = text.codePointAt(i)
                if (!covered[i]) rest.appendCodePoint(cp)
                i += Character.charCount(cp)
            }
            if (rest.isNotEmpty()) unknown += rest.toString()
        }
        var letters = 0
        var good = 0
        var i = 0
        while (i < text.length) {
            val cp = text.codePointAt(i)
            if (!PyUnicode.isSpace(cp)) {
                letters++
                if (covered[i]) good++
            }
            i += Character.charCount(cp)
        }
        val free = PyRe.finditer(B.WORD, text).count { m ->
            val w = m.value
            !B.DIGIT.containsMatchIn(w) && w.codePoints().filter { PyUnicode.isAlpha(it) }.count() >= 3
        }
        val said = groups.filter { it.kind == "words" }.sumOf { HarpTabText.solid(it.text) }
        val (best, count) = run(text, groups, covered)
        val cps = codePointPlaces(text)
        val out = groups.map { g ->
            Group(g.holes, g.kind, cps[g.col], cps[g.digit], g.text, g.hold, g.effects, g.join)
        }
        return Scan(out, if (letters > 0) good.toDouble() / letters else 0.0, unknown, line.label, LinkedHashMap(line.used),
                    free, if (letters > 0) said.toDouble() / letters else 0.0, best, count)
    }

    /** Each UTF-16 place's code-point place: Python's column. */
    private fun codePointPlaces(text: String): IntArray {
        val out = IntArray(text.length + 1)
        var cp = 0
        var i = 0
        while (i < text.length) {
            val n = Character.charCount(text.codePointAt(i))
            for (k in 0 until n) out[i + k] = cp
            i += n
            cp++
        }
        out[text.length] = cp
        return out
    }

    private fun run(text: String, groups: List<G>, covered: BooleanArray): Pair<Int, Int> {
        val holed = BooleanArray(text.length)
        for (g in groups) if (g.holes.isNotEmpty()) for (k in g.col until minOf(g.end, text.length)) holed[k] = true
        var best = 0
        var run = 0
        var count = 0
        for (m in PyRe.finditer(B.WORD, text)) {
            val range = m.range.first..m.range.last
            if (range.any { holed[it] }) {
                run++
                count++
                best = maxOf(best, run)
            } else if (!range.all { covered[it] }) {
                run = 0
                count++
            }
        }
        return best to count
    }

    private fun freeUntil(line: Line, start: Int): Int {
        for (i in start until line.covered.size) if (line.covered[i] || line.prose[i]) return i
        return line.covered.size
    }

    /** harptab._others: the effects a group shows as labels, every one but a hold. */
    private fun others(effects: List<String>): List<String> {
        val out = ArrayList<String>()
        for (e in effects) if (e != "hold" && e !in out) out += e
        return out
    }

    /** harptab._effect_before: [effect] to the group of holes written last before column [at]. */
    private fun effectBefore(groups: MutableList<G>, at: Int, effect: String) {
        var n = -1
        for ((k, g) in groups.withIndex()) {
            if (g.col < at && g.holes.isNotEmpty() && (n < 0 || g.col > groups[n].col)) n = k
        }
        if (n < 0) return
        val g = groups[n]
        if (effect == "hold") groups[n] = g.copy(hold = true)
        else if (effect !in g.effects) groups[n] = g.copy(effects = g.effects + effect)
    }
}
