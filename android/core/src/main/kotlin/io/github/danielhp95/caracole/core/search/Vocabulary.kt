package io.github.danielhp95.caracole.core.search

import io.github.danielhp95.caracole.core.db.Db
import io.github.danielhp95.caracole.core.py.Py

/**
 * search.py `_Vocabulary`: the words of the Ultimate Guitar index's keys (`ug_key_words`), by first letter and
 * length, as a process keeps them. A letter's words are read the first time a word of a query begins with it, and
 * then only the words the table gained since (it only grows), so that a search reads no word twice; [last] is the
 * newest word's id read. A length's words are kept in code point order, whenever they came (bisect.insort), so a
 * close spelling's ties come in that order.
 *
 * A letter is a word's first code point, and its words' range ends at the next code point, as Python's
 * `chr(ord(start) + 1)` builds it: where that is a lone surrogate (a word beginning with U+D7FF) Python can't bind
 * it and raises, and so does this ([among] throws IllegalArgumentException, as it does past U+10FFFF).
 */
internal class Vocabulary {
    private var last = 0L
    private var letters = HashMap<String, HashMap<Int, MutableList<String>>>()

    /** The words that begin with [word]'s letter, at most two letters longer or shorter, shorter ones first. */
    @Synchronized
    fun among(db: Db, word: String): List<String> {
        val top = db.one("SELECT COALESCE(MAX(id), 0) FROM ug_key_words") { it.long(0)!! }!!
        if (top < last) { // another database, made since at that path
            letters = HashMap()
            last = 0
        }
        if (top > last) {
            val new = if (letters.isNotEmpty()) {
                db.query("SELECT term FROM ug_key_words WHERE id > ? AND id <= ?", last, top) { it.text(0)!! }
            } else {
                emptyList()
            }
            for (term in new) {
                val byLength = letters[first(term)] ?: continue
                insort(byLength.getOrPut(Py.len(term)) { ArrayList() }, term)
            }
            last = top
        }
        val start = first(word)
        val letter = letters.getOrPut(start) {
            val byLength = HashMap<Int, MutableList<String>>()
            db.query("SELECT term FROM ug_key_words WHERE term >= ? AND term < ? AND id <= ? ORDER BY term",
                     start, next(start), top) { it.text(0)!! }
                .forEach { byLength.getOrPut(Py.len(it)) { ArrayList() }.add(it) }
            byLength
        }
        val n = Py.len(word)
        return (n - 2..n + 2).flatMap { letter[it] ?: emptyList() }
    }

    private fun first(s: String): String = if (s.isEmpty()) "" else s.substring(0, Character.charCount(s.codePointAt(0)))

    /** chr(ord(start) + 1), refused where Python refuses to bind or make it. */
    private fun next(start: String): String {
        val cp = start.codePointAt(0) + 1
        require(cp <= Character.MAX_CODE_POINT) { "chr() arg not in range(0x110000)" }
        require(cp !in Character.MIN_SURROGATE.code..Character.MAX_SURROGATE.code) { "surrogates not allowed" }
        return String(Character.toChars(cp))
    }

    /** bisect.insort: after the words equal to it, in code point order. */
    private fun insort(words: MutableList<String>, term: String) {
        var lo = 0
        var hi = words.size
        while (lo < hi) {
            val mid = (lo + hi) ushr 1
            if (Py.CODE_POINT_ORDER.compare(term, words[mid]) < 0) hi = mid else lo = mid + 1
        }
        words.add(lo, term)
    }

    companion object {
        /** VOCABULARIES: the databases whose words a process keeps. */
        const val VOCABULARIES = 4

        private val kept = LinkedHashMap<String, Vocabulary>()

        /** _vocabulary: the words this process keeps of the database [db] is open on, by its file; one in memory
         * keeps none. */
        fun of(db: Db): Vocabulary {
            val path = db.query("PRAGMA database_list") { (it.text(1) ?: "") to (it.text(2) ?: "") }
                .firstOrNull { it.first == "main" }?.second ?: ""
            if (path.isEmpty()) return Vocabulary()
            synchronized(kept) {
                val vocabulary = kept.remove(path) ?: Vocabulary()
                kept[path] = vocabulary
                while (kept.size > VOCABULARIES) kept.remove(kept.keys.first())
                return vocabulary
            }
        }
    }
}
