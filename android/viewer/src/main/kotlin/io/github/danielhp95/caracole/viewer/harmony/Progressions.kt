package io.github.danielhp95.caracole.viewer.harmony

import io.github.danielhp95.caracole.core.py.Py
import io.github.danielhp95.caracole.core.py.PyRe
import io.github.danielhp95.caracole.viewer.theory.Chord
import io.github.danielhp95.caracole.viewer.theory.Key
import io.github.danielhp95.caracole.viewer.theory.Theory
import java.util.Collections

/**
 * harmony.py's progressions half, line for line: a section's chords as numerals, the cycle its repeats fold to
 * (`_fold`, `_passes`, `_varies`: a pass may vary it), its name from CATALOGUE when the cycle is a row of it whole
 * (`_whole`, read in the key's own tonic and in its relative key, `_rows`), the rows it plays within it with the times
 * (`_contained`), how it ends (`_ending`); `progression_key`, the same in every key, turn and repeat; `name_of` and
 * `read_typed`, numerals typed; `catalogue_keys`. harmony.py's docstring ("Progressions") holds the rules; each
 * function here is the one of the same name there, its private ones public for HarmonyReplay's records of them.
 *
 * Names compare the chords' roots and thirds ([Token]): (semitones above the tonic, "M", "m" or "?" for none, which
 * fits either). CATALOGUE, _LOOPS and the other tables are harmony.py's own ([HarmonyData]); a numeral is read with
 * its patterns compiled as Python reads them, a roman's case as `str.islower` and `str.upper` read its ASCII letters
 * (the generator checks they are), and a key turned where its numerals sort first by code point, as Python compares
 * str. The answers asked most are kept as Python's `functools` caches keep them, each one nothing can change.
 */
object HarmonyProgressions {
    /** _NO_TOKEN: the token of a text that is no numeral, which fits nothing. */
    val NO_TOKEN: Pair<Int, String> = -1 to ""

    /** CATALOGUE: (name, numerals, source) for each progression with a common name, in its order. */
    val CATALOGUE: List<Triple<String, List<String>, String>> get() = HarmonyData.catalogue

    /** harmony._Row: a row of the catalogue as a key reads it, on the key's tonic ([own]) or in its relative key;
     * [forms], every run of chords that plays it (a loop's each turn, its own first). */
    class Row(val name: String, val tokens: List<Pair<Int, String>>, val numerals: List<String>, val own: Boolean,
              val loops: Boolean, val forms: List<List<Pair<Int, String>>>)

    /** _fold's answer: one [cycle], played [repeats] times, [varied] of them otherwise, each pass after the first
     * starting at one of [seams]. */
    class Fold(val cycle: List<String>, val repeats: Int, val varied: Int, val seams: List<Int>)

    // --- a numeral's parts ---------------------------------------------------------------------------------------

    private fun sign(accidental: String): String = when (accidental) {
        "b" -> "♭"
        "#" -> "♯"
        else -> accidental
    }

    /** _core: a numeral's root, its case and the chord it is the V of: "Imaj7" is "I", "V7/V/3" "V/V", "bVII"
     * "♭VII", "V7/IV" "I". A text that is no numeral stays as it is. */
    fun core(text: String): String {
        val m = PyRe.match(HarmonyData.numeral, text) ?: return text
        var core = sign(m.groupValues[1]) + m.groupValues[2]
        for (part in m.groupValues[4].split("/").drop(1)) {
            val of = PyRe.match(HarmonyData.romanOnly, part) ?: continue
            core += "/" + sign(of.groupValues[1]) + of.groupValues[2]
            break
        }
        return HarmonyData.onTheTonic[core] ?: core
    }

    /** _collapse: a chord held over several lines once. */
    fun collapse(items: List<String>): List<String> = items.filterIndexed { i, x -> i == 0 || x != items[i - 1] }

    /** _period: the length of the shortest cycle [items] repeats whole; none for no items (Python's StopIteration). */
    fun period(items: List<String>): Int {
        val n = items.size
        for (p in 1..n) if (n % p == 0 && (0 until n).all { items[it] == items[it % p] }) return p
        throw NoSuchElementException("no cycle of no items")
    }

    /** progression_key: a progression's key for searching, the same in every key, turn and repeat. */
    fun progressionKey(numerals: List<String>): String {
        val cycle = cycle(numerals)
        if (cycle.isEmpty()) return ""
        return cycle.indices.map { cycle.drop(it) + cycle.take(it) }.minWith(TUPLES).joinToString(" ")
    }

    /** progression_key of one string ("vi IV I V", "vi–IV–I–V"): its numerals as [typed] cuts them. */
    fun progressionKey(text: String): String = progressionKey(typed(text))

    /** A string of numerals cut at its separators (spaces, commas, dashes), as harmony.py cuts one typed. */
    fun typed(text: String): List<String> = PyRe.split(HarmonyData.separators, text).filterNotNull().filter { it.isNotEmpty() }

    /** _cycle: the numerals' roots, a chord held twice once, a last chord that is the first again dropped, the cycle
     * once, as written. */
    fun cycle(numerals: List<String>): List<String> {
        val cores = collapse(numerals.map(::core)).toMutableList()
        while (cores.size > 1 && cores[0] == cores[cores.size - 1]) cores.removeAt(cores.size - 1)
        return if (cores.isEmpty()) emptyList() else cores.subList(0, period(cores)).toList()
    }

    /** Python's tuple order of str: element by element, each by code point, a shorter one first. */
    private val TUPLES = Comparator<List<String>> { a, b ->
        for (i in 0 until minOf(a.size, b.size)) {
            val c = Py.CODE_POINT_ORDER.compare(a[i], b[i])
            if (c != 0) return@Comparator c
        }
        a.size.compareTo(b.size)
    }

    // --- the catalogue's names, where songs play them ------------------------------------------------------------

    private val tokens = Kept<String, Pair<Int, String>>(4096)

    /** _token: a numeral as names compare it: "Imaj7" and "I/3" are (0, "M"), "vi7" (9, "m"), "♭VIIsus4" (10, "?"),
     * a secondary chord on its own root: "V7/V" is (2, "M"). */
    fun token(text: String): Pair<Int, String> = tokens.getOrPut(text) {
        val m = PyRe.match(HarmonyData.numeral, text) ?: return@getOrPut NO_TOKEN
        val roman = m.groupValues[2]
        val rest = m.groupValues[3]
        var root = HarmonyData.steps.getValue(upper(roman)) + HarmonyData.accidentals.getValue(m.groupValues[1])
        for (part in m.groupValues[4].split("/").drop(1)) {
            val of = PyRe.match(HarmonyData.romanOnly, part) ?: continue
            root += HarmonyData.steps.getValue(upper(of.groupValues[2])) + HarmonyData.accidentals.getValue(of.groupValues[1])
            break
        }
        val third = if ("sus" in rest || rest == "5") "?" else if (isLower(roman)) "m" else "M"
        Math.floorMod(root, 12) to third
    }

    /** str.upper and str.islower of a roman, whose letters are the pattern's ASCII ones. */
    private fun upper(roman: String): String = buildString { for (ch in roman) append(if (ch in 'a'..'z') ch - 32 else ch) }

    private fun isLower(roman: String): Boolean = roman.any { it in 'a'..'z' } && roman.none { it in 'A'..'Z' }

    /** _fits: a chord played fits one of a progression: the same root, and the same third or none. */
    fun fits(played: Pair<Int, String>, wanted: Pair<Int, String>): Boolean =
        played.first == wanted.first && (played.second == wanted.second || played.second == "?")

    /** _same: two chords played are one harmony: the same root, and the same third or one with none. */
    fun same(a: Pair<Int, String>, b: Pair<Int, String>): Boolean =
        a.first == b.first && (a.second == b.second || a.second == "?" || b.second == "?")

    /** _merged: the numerals as names compare them, each with the index of its first: a chord held, whatever its
     * extensions, its bass or its suspension, once. */
    fun merged(texts: List<String>): List<Pair<Pair<Int, String>, Int>> {
        val out = ArrayList<Pair<Pair<Int, String>, Int>>()
        for ((i, text) in texts.withIndex()) {
            val token = token(text)
            if (out.isNotEmpty() && token != NO_TOKEN && same(out[out.size - 1].first, token)) {
                val (held, first) = out[out.size - 1]
                out[out.size - 1] = (held.first to (if (held.second == "?") token.second else held.second)) to first
            } else {
                out.add(token to i)
            }
        }
        return out
    }

    /** _closed: a cycle of chords, a last chord that is the first again dropped, the shortest cycle it repeats once. */
    fun closed(tokens: List<Pair<Int, String>>): List<Pair<Int, String>> {
        val cycle = tokens.toMutableList()
        while (cycle.size > 1 && same(cycle[0], cycle[cycle.size - 1])) cycle.removeAt(cycle.size - 1)
        val n = cycle.size
        val period = (1..n).firstOrNull { p -> n % p == 0 && (0 until n).all { same(cycle[it], cycle[it % p]) } } ?: n
        return cycle.subList(0, period).toList()
    }

    private fun row(name: String, tokens: List<Pair<Int, String>>, numerals: List<String>, own: Boolean, loops: Boolean): Row {
        val forms = if (loops) {
            val cycle = closed(tokens)
            LinkedHashSet(cycle.indices.map { cycle.drop(it) + cycle.take(it) }).map(::frozen)
        } else {
            listOf(frozen(tokens))
        }
        return Row(name, frozen(tokens), frozen(numerals), own, loops, frozen(forms))
    }

    /** _PARENT: the tonic of each mode above the tonic of the major scale with its notes. */
    private fun parent(mode: String): Int = Theory.SCALES.getValue("ionian")[Theory.MODES.indexOf(mode).also {
        if (it < 0) throw NoSuchElementException("no mode $mode")
    }]

    private val rowsOf = HashMap<String, List<Row>>()

    /** _rows: the catalogue as a key in [mode] reads it: each row on the key's tonic, then each read in the key's
     * relative one (but those on their own tonic alone, and the turns of those that turn on it). */
    fun rows(mode: String): List<Row> {
        synchronized(rowsOf) { rowsOf[mode]?.let { return it } }
        val own = ArrayList<Row>()
        val relative = ArrayList<Row>()
        for ((name, numerals, _) in HarmonyData.catalogue) {
            val tokens = numerals.map(::token)
            val loops = numerals in HarmonyData.loops
            own.add(row(name, tokens, numerals, true, loops))
            val home = if ((0 to "m") in tokens) "aeolian" else "ionian"
            val shift = Math.floorMod(parent(home) - parent(mode), 12)
            if (name in HarmonyData.onItsTonic || shift == 0) continue
            val moved = tokens.map { (root, third) -> Math.floorMod(root + shift, 12) to third }
            relative.add(row(name, moved, written(moved, Key(0, mode), loops), false,
                             loops && name !in HarmonyData.turnsOnItsTonic))
        }
        val found = frozen(own + relative)
        synchronized(rowsOf) { return rowsOf.getOrPut(mode) { found } }
    }

    /** _written: the numerals numeral() gives the triads of [tokens] in [key], each read with the next (a loop's last
     * with its first). */
    fun written(tokens: List<Pair<Int, String>>, key: Key, loops: Boolean): List<String> {
        val chords = tokens.map { (root, third) -> Chord(root, if (third == "m") "m" else "") }
        val after: List<Chord?> = chords.drop(1) + listOf(if (loops) chords[0] else null)
        return chords.zip(after).map { (c, a) -> HarmonyChords.numeral(c, key, a).text }
    }

    /** _whole: the catalogue's name for a cycle played whole, the first row that fits, those on the tonic first. */
    fun whole(tokens: List<Pair<Int, String>>, mode: String): String? {
        val cycle = closed(tokens)
        for (row in rows(mode)) {
            val forms = if (row.loops) row.forms else listOf(closed(row.tokens))
            if (forms.any { form -> form.size == cycle.size && cycle.indices.all { fits(cycle[it], form[it]) } }) return row.name
        }
        return null
    }

    private class Candidate(val k: Int, val order: Int, val own: Boolean, val closes: Boolean, val name: String)

    private class Pick(val k: Int, val closes: Boolean, val name: String)

    /** Python's (chords held, -runs, runs on the tonic), compared as a tuple. */
    private data class Score(val held: Int, val runs: Int, val own: Int) : Comparable<Score> {
        override fun compareTo(other: Score): Int = compareValuesBy(this, other, { it.held }, { it.runs }, { it.own })
    }

    /** _contained: the catalogue's progressions a section plays ([held]: its numerals, a chord held once) as runs of
     * its chords, in the order it first plays each, with the times; a loop from another of its chords only when
     * played twice, one that goes somewhere within each pass of a section played round ([seams]: where each pass
     * after the first starts). */
    fun contained(held: List<String>, mode: String, seams: List<Int> = emptyList()): List<Contained> {
        val merged = merged(held)
        val tokens = merged.map { it.first }
        val n = tokens.size
        val cuts = seams.map { seam -> merged.indices.filter { merged[it].second <= seam }.max() }.toSortedSet().toList()
        val starting = HashMap<Int, MutableList<Candidate>>()
        for ((order, row) in rows(mode).withIndex()) {
            for ((turn, form) in row.forms.withIndex()) {
                val k = form.size
                val closes = form[0] == form[k - 1]
                var found = (0..n - k).filter { start -> (0 until k).all { j -> fits(tokens[start + j], form[j]) } }
                if (!row.loops) {
                    val last = if (closes) k - 2 else k - 1  // the run's last chord a seam may not fall within
                    found = found.filter { start -> cuts.none { cut -> start < cut && cut <= start + last } }
                } else if (turn != 0 && apart(found, k) < 2) {
                    continue
                }
                for (start in found) starting.getOrPut(start) { ArrayList() }.add(Candidate(k, order, row.own, closes, row.name))
            }
        }
        // best[pos]: the best reading of the chords from pos on, and the run it starts with there (null: none).
        val best = Array(n + 1) { Score(0, 0, 0) }
        val pick = arrayOfNulls<Pick>(n + 1)
        for (pos in n - 1 downTo 0) {
            best[pos] = best[pos + 1]
            val candidates = starting[pos].orEmpty().sortedWith(compareBy({ -it.k }, { !it.own }, { it.order }))
            for (c in candidates) {
                val end = if (c.closes) pos + c.k - 1 else pos + c.k
                val rest = best[end]
                // A chord lent to the next run is held once.
                val score = Score(rest.held + c.k - (if (c.closes && pick[end] != null) 1 else 0), rest.runs - 1,
                                  rest.own + (if (c.own) 1 else 0))
                if (score > best[pos] || (score == best[pos] && pick[pos] == null)) {
                    best[pos] = score
                    pick[pos] = Pick(c.k, c.closes, c.name)
                }
            }
        }
        val times = LinkedHashMap<String, Int>()
        val first = HashMap<String, List<String>>()
        var pos = 0
        while (pos < n) {
            val p = pick[pos]
            if (p == null) {
                pos++
                continue
            }
            times[p.name] = (times[p.name] ?: 0) + 1
            if (p.name !in first) first[p.name] = frozen((pos until pos + p.k).map { held[merged[it].second] })
            pos += if (p.closes) p.k - 1 else p.k
        }
        val keys = nameKeys()
        return frozen(times.map { (name, count) -> Contained(name, count, first.getValue(name), keys.getValue(name)) })
    }

    /** _apart: how many runs of [k] chords starting at [starts] (in order) a section plays one after another, none
     * sharing a chord. */
    fun apart(starts: List<Int>, k: Int): Int {
        var count = 0
        var free = 0
        for (start in starts) {
            if (start >= free) {
                count++
                free = start + k
            }
        }
        return count
    }

    private val nameKeys: Map<String, String> by lazy {
        val keys = LinkedHashMap<String, String>()
        for ((name, numerals, _) in HarmonyData.catalogue) keys.putIfAbsent(name, progressionKey(numerals))
        Collections.unmodifiableMap(keys)
    }

    /** _name_keys: each name's key for searching, its first row's progression_key. */
    fun nameKeys(): Map<String, String> = nameKeys

    private val namedKeys: Map<String, String> by lazy {
        val found = LinkedHashMap<String, String>()
        for (mode in listOf("ionian", "aeolian")) for (row in rows(mode)) found.putIfAbsent(progressionKey(row.numerals), row.name)
        Collections.unmodifiableMap(found)
    }

    /** catalogue_keys: each reading of the catalogue's progressions by its progression_key, every row on its own tonic
     * first, then read in a major key and in a minor one. */
    fun catalogueKeys(): Map<String, String> = namedKeys

    /** name_of: the catalogue's name for numerals typed, played whole, read in a major key or in a minor one. */
    fun nameOf(numerals: List<String>): String? = nameOfRead(readTyped(numerals))

    private class Name(val name: String?)

    private val names = Kept<List<String>, Name>(1024)

    private fun nameOfRead(numerals: List<String>): String? = names.getOrPut(numerals) {
        val tokens = merged(numerals).map { it.first }
        Name(if (tokens.isEmpty() || NO_TOKEN in tokens) null else whole(tokens, "ionian") ?: whole(tokens, "aeolian"))
    }.name

    /** read_typed: numerals as typed, in harmony.py's notation: written in a minor key's own way (a minor tonic, i, and
     * no accidental), a major III, VI or VII is its ♭III, ♭VI or ♭VII; others are as typed. */
    fun readTyped(numerals: List<String>): List<String> {
        val found = numerals.map { PyRe.match(HarmonyData.numeral, it) }
        if (found.any { it == null || it.groupValues[1].isNotEmpty() } || found.none { it!!.groupValues[2] == "i" }) {
            return frozen(numerals)
        }
        return frozen(numerals.zip(found).map { (n, m) -> if (m!!.groupValues[2] in HarmonyData.naturalMinor) "♭$n" else n })
    }

    // --- a section's repeats -------------------------------------------------------------------------------------

    /** _fold: a section's numerals (a chord held once) as one cycle, the times it is played, how many of those play
     * it otherwise, and where each pass after the first starts. */
    fun fold(held: List<String>): Fold {
        val n = held.size
        val period = period(held)
        if (period < n) return Fold(frozen(held.subList(0, period)), n / period, 0, frozen((period until n step period).toList()))
        for (p in 2..minOf(HarmonyData.longestCycle, n / 2)) {
            val at = HashMap<List<String>, MutableList<Int>>()
            for (i in 0..n - p) at.getOrPut(held.subList(i, i + p).toList()) { ArrayList() }.add(i)
            var best: Pair<List<String>, Passes>? = null
            for (s in 0..minOf(p + 1, n - p)) {  // a first pass that varies it has a chord more at most
                val cycle = held.subList(s, s + p).toList()
                val passes = passes(held, cycle, at.getValue(cycle))
                if (passes != null && (best == null || compareValuesBy(passes, best.second, { it.whole }, { -it.varied }) > 0)) {
                    best = cycle to passes
                }
            }
            if (best != null) {
                val (cycle, passes) = best
                return Fold(frozen(cycle), passes.whole + passes.varied, passes.varied, passes.seams)
            }
        }
        return Fold(frozen(held), 1, 0, emptyList())
    }

    /** _passes' answer: the passes played whole, the others, and where each after the first starts. */
    class Passes(val whole: Int, val varied: Int, val seams: List<Int>)

    /** _passes: the passes of [cycle] the section plays whole, the others (_varies), and where each after the first
     * starts, the home it may end on too; null when the section is no such cycle. */
    fun passes(held: List<String>, cycle: List<String>, starts: List<Int>): Passes? {
        if (starts.size < 2) return null
        val n = held.size
        val p = cycle.size
        var whole = 0
        var varied = 0
        val seams = ArrayList<Int>()
        var j = 0
        while (j < n) {
            if (j != 0) seams.add(j)
            if (held.subList(j, minOf(j + p, n)) == cycle) {
                whole++
                j += p
                continue
            }
            val k = starts.firstOrNull { it > j }
            val rest = if (k == null) held.subList(j, n) else held.subList(j, k)
            if (k == null && rest.size < p && cycle.subList(0, rest.size) == rest) break  // home: the cycle's first chords
            if (!varies(rest, cycle)) return null
            varied++
            if (k == null) break
            j = k
        }
        return if (whole >= 2 && whole > varied) Passes(whole, varied, frozen(seams)) else null
    }

    /** _varies: a pass [played] plays [cycle] otherwise: one chord changed, or one added or left out, or, in a cycle of
     * four chords or more, a chord changed and one added or left out as well. */
    fun varies(played: List<String>, cycle: List<String>): Boolean {
        val (longer, shorter) = if (played.size >= cycle.size) played to cycle else cycle to played
        if (longer.size == shorter.size) return longer.indices.count { longer[it] != shorter[it] } <= 1
        if (longer.size - shorter.size != 1) return false
        val changed = if (cycle.size >= 4) 1 else 0
        return longer.indices.any { i ->
            val cut = longer.subList(0, i) + longer.subList(i + 1, longer.size)
            cut.indices.count { cut[it] != shorter[it] } <= changed
        }
    }

    /** _ending: how a section ends: V–I authentic, IV–I plagal, V–vi deceptive, on V half. */
    fun ending(cores: List<String>): String? {
        val held = collapse(cores)
        if (held.size < 2) return null
        val before = held[held.size - 2]
        val last = held[held.size - 1]
        if ((last == "I" || last == "i") && before == "V") return "authentic"
        if ((last == "I" || last == "i") && (before == "IV" || before == "iv")) return "plagal"
        if (before == "V" && (last == "vi" || last == "♭VI" || last == "VI")) return "deceptive"
        if (last == "V") return "half"
        return null
    }

    private val found = Kept<Pair<List<Pair<String, List<Chord?>>>, Key>, List<Pair<String, Progression>>>(1024)

    /** progressions: each section's progression, by its name, in the sheet's order, each chord read with the next on
     * the sheet (across sections); a chord caracole can't read (null) left out, a section with none has none. */
    fun progressions(sections: List<Pair<String, List<Chord?>>>, key: Key): List<Pair<String, Progression>> {
        val frozen = sections.map { (name, chords) -> name to ArrayList(chords) as List<Chord?> }
        return found.getOrPut(frozen to key) { read(frozen, key) }
    }

    private fun read(sections: List<Pair<String, List<Chord?>>>, key: Key): List<Pair<String, Progression>> {
        val played = ArrayList<Pair<Int, Chord>>()
        for ((i, section) in sections.withIndex()) for (c in section.second) if (c != null) played.add(i to c)
        val texts = List(sections.size) { ArrayList<String>() }
        val after = HarmonyChords.goesTo(played.map { it.second })
        for ((j, p) in played.withIndex()) texts[p.first].add(HarmonyChords.numeral(p.second, key, after[j]).text)
        val out = ArrayList<Pair<String, Progression>>()
        for ((section, numerals) in sections.zip(texts)) {
            if (numerals.isEmpty()) continue
            val held = collapse(numerals)
            val fold = fold(held)
            val whole = whole(merged(fold.cycle).map { it.first }, key.mode)
            val contains = contained(held, key.mode, fold.seams).filter { it.name != whole }
            out.add(section.first to Progression(fold.cycle, fold.repeats, whole, ending(held.map(::core)), fold.varied,
                                                 frozen(contains)))
        }
        return frozen(out)
    }

    private fun <T> frozen(items: List<T>): List<T> = Collections.unmodifiableList(ArrayList(items))
}
