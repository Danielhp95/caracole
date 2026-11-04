package io.github.danielhp95.caracole.core.py

/** difflib, the part caracole uses: harpfit.py matches a harmonica tab's row to the sheet's line its words read most
 * like (vectors/py/format_sequence.jsonl). */
object PySequence {
    /**
     * difflib.SequenceMatcher(None, a, b, autojunk=False), Python 3.14's: no junk and no popular elements, so every
     * element of [b] is indexed, however often it comes. Elements are compared with equals and hashed as Python's dict
     * hashes them, so [T] holds Python's equality (a String is).
     */
    class SequenceMatcher<T>(val a: List<T>, val b: List<T>) {
        /** Each element of [b] and where it is, ascending (difflib's b2j, __chain_b). */
        private val b2j: Map<T, IntArray> = run {
            val found = LinkedHashMap<T, MutableList<Int>>()
            b.forEachIndexed { j, element -> found.getOrPut(element) { ArrayList() } += j }
            found.mapValues { (_, at) -> at.toIntArray() }
        }

        private var blocks: List<Triple<Int, Int, Int>>? = null

        /** ratio(): 2.0 * the elements matched / the length of both, or 1.0 when both are empty. */
        fun ratio(): Double {
            val matches = matchingBlocks().sumOf { it.third }
            val length = a.size + b.size
            return if (length != 0) 2.0 * matches / length else 1.0
        }

        /** get_matching_blocks(): (i, j, n) where a[i:i+n] == b[j:j+n], ascending, adjacent blocks merged, and last
         * the dummy (len(a), len(b), 0). Computed once. */
        fun matchingBlocks(): List<Triple<Int, Int, Int>> {
            blocks?.let { return it }
            val found = ArrayList<Triple<Int, Int, Int>>()
            val queue = ArrayDeque<IntArray>()
            queue.addLast(intArrayOf(0, a.size, 0, b.size))
            while (queue.isNotEmpty()) {
                val (alo, ahi, blo, bhi) = queue.removeLast()  // Python's list.pop(): the last pushed first
                val match = findLongestMatch(alo, ahi, blo, bhi)
                val (i, j, k) = match
                if (k != 0) {
                    found += match
                    if (alo < i && blo < j) queue.addLast(intArrayOf(alo, i, blo, j))
                    if (i + k < ahi && j + k < bhi) queue.addLast(intArrayOf(i + k, ahi, j + k, bhi))
                }
            }
            found.sortWith(compareBy<Triple<Int, Int, Int>>({ it.first }, { it.second }, { it.third }))
            val merged = ArrayList<Triple<Int, Int, Int>>()
            var i1 = 0
            var j1 = 0
            var k1 = 0
            for ((i2, j2, k2) in found) {
                if (i1 + k1 == i2 && j1 + k1 == j2) {
                    k1 += k2
                } else {
                    if (k1 != 0) merged += Triple(i1, j1, k1)
                    i1 = i2
                    j1 = j2
                    k1 = k2
                }
            }
            if (k1 != 0) merged += Triple(i1, j1, k1)
            merged += Triple(a.size, b.size, 0)
            return merged.also { blocks = it }
        }

        /**
         * find_longest_match(alo, ahi, blo, bhi): the longest a[i:i+k] == b[j:j+k] within the bounds, the one that
         * starts earliest in a of those, then earliest in b; (alo, blo, 0) for none.
         *
         * j2len, Python's dict of the matches ending at each j on the row before, is two arrays here, each entry valid
         * only where the row set it ([touched]), cleared before the arrays swap.
         */
        private fun findLongestMatch(alo: Int, ahi: Int, blo: Int, bhi: Int): Triple<Int, Int, Int> {
            var besti = alo
            var bestj = blo
            var bestsize = 0
            var j2len = IntArray(b.size)
            var newj2len = IntArray(b.size)
            var touched = IntArray(b.size)
            var newTouched = IntArray(b.size)
            var nTouched = 0
            for (i in alo until ahi) {
                var nNew = 0
                val at = b2j[a[i]]
                if (at != null) {
                    for (j in at) {
                        if (j < blo) continue
                        if (j >= bhi) break
                        val k = (if (j > 0) j2len[j - 1] else 0) + 1
                        newj2len[j] = k
                        newTouched[nNew++] = j
                        if (k > bestsize) {
                            besti = i - k + 1
                            bestj = j - k + 1
                            bestsize = k
                        }
                    }
                }
                for (t in 0 until nTouched) j2len[touched[t]] = 0
                j2len = newj2len.also { newj2len = j2len }
                touched = newTouched.also { newTouched = touched }
                nTouched = nNew
            }
            // Python's extensions over the elements it left out of b2j: none are junk and none popular here, so each
            // finds nothing more; kept as written (the two over junk never run with isjunk=None).
            while (besti > alo && bestj > blo && a[besti - 1] == b[bestj - 1]) {
                besti--
                bestj--
                bestsize++
            }
            while (besti + bestsize < ahi && bestj + bestsize < bhi && a[besti + bestsize] == b[bestj + bestsize]) {
                bestsize++
            }
            return Triple(besti, bestj, bestsize)
        }
    }
}
