package io.github.danielhp95.caracole.viewer.harptab

import io.github.danielhp95.caracole.core.py.Py
import io.github.danielhp95.caracole.core.py.PyUnicode
import io.github.danielhp95.caracole.viewer.harp.Harp

/**
 * Which notation, as harptab.py chooses one (its docstring's "Which notation"): the candidates (`_candidates`), each
 * scored on the tab's lines by Q = P × T and weighed by its legend (`_weighed`), the best kept (`read`), every
 * reading weighed (`readings`), and the words a reading is said in (`said`, `Reading.standard`). Floats are summed as
 * Python's builtin sum sums them (core.py.Py.fsum) and divided as Python divides.
 */
internal object Weighing {
    private val B = HarptabData

    /** harptab._prepared. */
    fun prepared(body: String, harp: String?): Prepared {
        val chip = if (harp.isNullOrEmpty()) null else B.CHIPS.firstOrNull { (_, p) -> p.find(harp) != null }?.first
        val lines = body.replace("\r\n", "\n").replace("\r", "\n").split("\n")
            .map { HarpTabText.rstrip(HarpTabText.expand(it)) }
        val legends = Legends.legend(lines)
        return Prepared(chip, lines, legends, legends.flatMapTo(LinkedHashSet()) { it.at })
    }

    /** The best result, by score, then the commoner (Python's `max(…, key=lambda r: (r[0], -r[1]))`). */
    fun best(results: List<Weighed.Result>): Weighed.Result? {
        var best: Weighed.Result? = null
        for (r in results) if (best == null || r.score > best.score || (r.score == best.score && r.k < best.k)) best = r
        return best
    }

    val USED_ORDER: Comparator<Pair<Used, Int>> = Comparator { (a, x), (b, y) ->
        Py.CODE_POINT_ORDER.compare(a.text, b.text).takeIf { it != 0 }
            ?: Py.CODE_POINT_ORDER.compare(a.means, b.means).takeIf { it != 0 }
            ?: Py.CODE_POINT_ORDER.compare(a.at, b.at).takeIf { it != 0 }
            ?: a.count.compareTo(b.count).takeIf { it != 0 }
            ?: x.compareTo(y)
    }

    fun read(lines: List<String>, harpChip: String?, notation: Notation?, legends: List<Legend>): Pair<Reading, List<Scan>> {
        val (candidates, found) = if (notation != null) listOf(notation to "pinned") to emptyList()
                                  else candidates(lines, harpChip, legends)
        val weighed = weighed(lines, candidates, harpChip, found)
        val k = weighed.best
        return weighed.reading(k) to weighed.scanned[k]
    }

    /** harptab._candidates: the notations a tab is read under, the commonest first, each with its source, and its
     * legends' symbols placed. */
    fun candidates(lines: List<String>, harpChip: String?, legends: List<Legend>): Pair<List<Pair<Notation, String>>, List<Symbol>> {
        val holey = lines.filter { B.DIGIT.find(it) != null }
        val placed = legends.flatMap { it.symbols }.mapNotNull { Legends.where(it, holey) }.distinct()
        var candidates = ArrayList<Pair<Notation, String>>()
        var found: List<Symbol> = emptyList()
        val made = Legends.withLegend(placed, holey)
        if (made != null) {
            found = made.second
            candidates += made.first to "legend"
        }
        for (preset in B.PRESETS) {
            if (preset === B.PRESETS[0] && harpChip == "Diatonic") candidates += B.STAR_BENDS to "guessed"
            candidates += preset to "guessed"
        }
        if (dotted(lines)) candidates = candidates.mapTo(ArrayList()) { (n, source) -> n.changed(listOf(B.DOTS)) to source }
        return candidates to found
    }

    fun dotted(lines: List<String>): Boolean = lines.any { B.DOT_BEFORE.find(it) != null }

    /** harptab._playable: whether a Richter harp plays [hole] (a slide, unless the chip says Diatonic). */
    fun playable(hole: Hole, harpChip: String?): Boolean =
        if (hole.button) harpChip != "Diatonic" else Harp.holeNote(0, hole.hole, hole.breath, hole.bend, hole.over) != null

    /** harptab._weighed: each candidate scored on the tab's lines, Q = P × T, weighed by the legend's [found]. */
    fun weighed(lines: List<String>, candidates: List<Pair<Notation, String>>, harpChip: String?, found: List<Symbol>): Weighed {
        val scanned = candidates.map { (n, _) -> lines.map { if (Py.strip(it).isNotEmpty()) Scanner.scan(it, n) else Scan.BLANK } }
        val scored = lines.indices.filter { i -> scanned.any { it[i].isRow || it[i].missed } }
        val sizes = scored.associateWith { HarpTabText.solid(lines[it]) }
        val said = scored.associateWith { i -> scanned.maxOf { it[i].prose } * sizes.getValue(i) }
        val results = candidates.mapIndexed { k, (n, _) ->
            val explained = if (scored.isEmpty()) 0.0 else {
                val chars = Py.fsum(scored.map { sizes.getValue(it) - said.getValue(it) })
                if (chars != 0.0) pyMin(1.0, Py.fsum(scored.map { scanned[k][it].coverage * sizes.getValue(it) }) / chars)
                else 0.0
            }
            val holes = scored.flatMap { i -> scanned[k][i].holes.flatMap { it.holes } }
            val playable = if (holes.isEmpty()) 0.0 else holes.count { playable(it, harpChip) }.toDouble() / holes.size
            val weight = if (found.isNotEmpty()) 1 + B.LEGEND_WEIGHT * Legends.agreement(n, found) else 1.0
            Weighed.Result(explained * playable * weight, k, explained, playable,
                   scored.map { i -> scanned[k][i].holes.map { it.kind to it.holes } })
        }
        return Weighed(candidates, scanned, scored, results)
    }

    fun readings(body: String, harp: String?): List<Reading> {
        val prepared = prepared(body, harp)
        val lines = prepared.read
        val (candidates, found) = candidates(lines, prepared.chip, prepared.legends)
        val weighed = weighed(lines, candidates, prepared.chip, found)
        val out = LinkedHashMap<Pair<List<List<Pair<String, List<Hole>>>>, String>, Reading>()
        val order = weighed.results.sortedWith { a, b ->  // (-score, k), the scores compared as Python's floats
            when {
                a.score > b.score -> -1
                a.score < b.score -> 1
                else -> a.k.compareTo(b.k)
            }
        }
        for (r in order) {
            val reading = weighed.reading(r.k)
            out.putIfAbsent(r.signature to reading.said(), reading)
        }
        return out.values.toList()
    }

    /** Reading.standard. */
    fun standard(r: Reading): Boolean {
        val signs = B.PRESETS[0]
        val dots = B.DOTS
        return r.source == "guessed" && r.notation.name == signs.name && r.used.all { (u, _) ->
            if (u.at == "bare") u.means == signs.bare
            else (u.text == dots.text && u.means == dots.means && u.at == dots.at) ||
                signs.meaning(u.text, u.at)?.let { own -> own.means == u.means && own.count == u.count } == true
        }
    }

    /** harptab.said: the symbols [used] (`Scan.used`'s), each as the tab writes it most, and what it means in words. */
    fun said(used: Map<Used, Int>): List<Pair<String, String>> {
        data class Key(val means: String, val at: String, val count: Int)
        val entries = LinkedHashMap<Key, LinkedHashMap<String, Int>>()
        for ((u, times) in used) {
            if (u.means == "mark") continue
            val texts = entries.getOrPut(Key(u.means, u.at, u.count)) { LinkedHashMap() }
            texts[u.text] = (texts[u.text] ?: 0) + times
        }
        val rank = B.MEANINGS.withIndex().associate { (n, m) -> m to n }
        fun order(key: Key): List<Int> = if (key.means in B.BREATHS) {
            val at = B.ORDER.indexOf(key.at)
            if (at < 0) throw IllegalArgumentException("'${key.at}' is not in list")
            listOf(0, at, rank.getValue(key.means))
        } else listOf(1, rank.getValue(key.means), key.count)
        val sorted = entries.keys.sortedWith { a, b ->
            val x = order(a)
            val y = order(b)
            (0 until 3).asSequence().map { x[it].compareTo(y[it]) }.firstOrNull { it != 0 } ?: 0
        }
        val out = ArrayList<Pair<String, String>>()
        for (key in sorted) {
            val spelled = LinkedHashMap<String, LinkedHashMap<String, Int>>()
            for ((text, times) in entries.getValue(key)) {
                val forms = spelled.getOrPut(PyUnicode.casefold(text)) { LinkedHashMap() }
                forms[text] = (forms[text] ?: 0) + times
            }
            val keys = spelled.keys.sortedWith(compareBy<String> { -spelled.getValue(it).values.sum() }.then(Py.CODE_POINT_ORDER))
            val shown = keys.map { t ->
                var best: Map.Entry<String, Int>? = null
                for (kv in spelled.getValue(t)) {
                    if (best == null || kv.value > best.value ||
                        (kv.value == best.value && isLower(kv.key) && !isLower(best.key))) best = kv
                }
                best!!.key
            }
            val word = if (key.means == "bend") listOf("bend", "double bend", "triple bend")[minOf(key.count, 3) - 1]
                       else B.SAY[key.means] ?: key.means
            val text = if (key.at == "bare") "4" else if (shown == listOf("()")) "(4)" else shown.joinToString(" or ")
            out += text to word
        }
        return out
    }

    private fun isLower(text: String): Boolean = PyUnicode.lower(text) == text
}

/** harptab._Weighed: each candidate's scans of the tab's lines ([scanned], a line blank a blank scan), the lines
 * scored (those any candidate reads as a row, or as holes it missed), and each candidate's [results]. */
class Weighed internal constructor(val candidates: List<Pair<Notation, String>>, val scanned: List<List<Scan>>,
                                   val scored: List<Int>, val results: List<Result>) {
    /** One candidate's result: `(score, k, explained, playable, signature)`, its signature each scored line's groups
     * of holes, their kinds and holes. */
    class Result(val score: Double, val k: Int, val explained: Double, val playable: Double,
                 val signature: List<List<Pair<String, List<Hole>>>>)

    /** The place of the candidate `read` keeps: the best score, a tie to the commoner. */
    val best: Int get() = Weighing.best(results)!!.k

    /** The candidate [k]'s reading: its margin over the best that reads the tab differently, and whether a commoner
     * one that does is within MARGIN of it. */
    fun reading(k: Int): Reading {
        val mine = results[k]
        val rivals = results.filter { it.signature != mine.signature }
        val runner = Weighing.best(rivals)
        val thin = rivals.any { it.k < k && mine.score - it.score < HarptabData.MARGIN }
        val used = LinkedHashMap<Used, Int>()
        for (i in scored) for ((key, n) in scanned[k][i].used) used[key] = (used[key] ?: 0) + n
        val (notation, source) = candidates[k]
        return Reading(notation, source, mine.explained, mine.playable, mine.score,
                       if (runner != null) mine.score - runner.score else mine.score,
                       runner?.let { candidates[it.k].first.name },
                       source == "pinned" || (mine.explained * mine.playable >= HarptabData.TAB_Q && !thin),
                       used.entries.map { it.key to it.value }.sortedWith(Weighing.USED_ORDER))
    }
}
