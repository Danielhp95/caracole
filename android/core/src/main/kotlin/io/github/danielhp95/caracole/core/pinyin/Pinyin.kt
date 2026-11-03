package io.github.danielhp95.caracole.core.pinyin

/**
 * pypinyin 0.55.0 in Style.NORMAL, as caracole asks it (normalize.py): `lazy_pinyin(text)` and
 * `lazy_pinyin(text, errors="ignore")` are [lazyPinyin], `pinyin(c, style=Style.NORMAL, heteronym=True)[0]` is
 * [heteronyms]. It reads a text as pypinyin does (core.py, converter.py, utils.py, seg/simpleseg.py, seg/mmseg.py):
 *
 * 1. The text is cut into runs of the characters pypinyin's `RE_HANS` matches (hans.txt) and runs of the others.
 * 2. A run of others is itself ([Errors.DEFAULT]) or nothing ([Errors.IGNORE]).
 * 3. A run of Han is cut by mmseg's forward maximum matching over pypinyin's phrases: from where it stands, it reads
 *    one more character at a time while what it read begins some phrase; the word is the longest phrase among
 *    those, or with none its first character alone. When the whole rest of the run begins a phrase, the word is
 *    again the longest phrase among its prefixes and the cut goes on after it; with none, each character of the
 *    rest is a word alone, and the run ends there.
 * 4. A phrase reads as its syllables (phrases.txt); a lone character as its first reading (chars.txt), else as
 *    itself ([Errors.DEFAULT]) or nothing ([Errors.IGNORE]).
 *
 * Its dictionaries are pypinyin's own, made in Style.NORMAL by pypinyin (tone marks dropped, ü written v) and written
 * by tests/test_conformance_pinyin.py into caracole/pinyin/ on the classpath, each read on first use (UTF-8, a line
 * each; that file's docstring is their format's too):
 * - hans.txt: `<first> <last>`, the ranges of code points `RE_HANS` matches, inclusive, in lowercase hex, in order;
 * - chars.txt: `<code point in lowercase hex> <reading>,<reading>,…`, PINYIN_DICT by code point, in its order;
 * - phrases.txt: `<phrase> <syllable> <syllable> …`, PHRASES_DICT in UTF-16 order (a binary search finds a word in
 *   it, and whether it begins a phrase).
 *
 * Everything is on code points, with no JDK text API: nothing here depends on the JDK's Unicode or Android's ICU.
 */
object Pinyin {
    enum class Errors { DEFAULT, IGNORE }

    /** `lazy_pinyin(text, errors=…)`: a reading for each Han character read, and each run of others itself. */
    fun lazyPinyin(text: String, errors: Errors = Errors.DEFAULT): List<String> {
        val out = ArrayList<String>()
        var start = 0
        while (start < text.length) {
            val han = isHan(text.codePointAt(start))
            var end = start
            while (end < text.length) {
                val cp = text.codePointAt(end)
                if (isHan(cp) != han) break
                end += Character.charCount(cp)
            }
            val run = text.substring(start, end)
            if (han) readRun(run, errors, out) else if (errors == Errors.DEFAULT) out.add(run)
            start = end
        }
        return out
    }

    /**
     * pinyin(c, style=NORMAL, heteronym=True)[0]: each of the character's readings once, in pypinyin's order (an
     * empty one dropped, `[""]` were none left); a Han character with no reading, or any other character, is itself.
     * A code point beyond U+10FFFF is an [IllegalArgumentException], as `chr` raises ValueError. (pypinyin would read a
     * phrase of one character as its phrase; it has none, which the generator checks.)
     */
    fun heteronyms(cp: Int): List<String> {
        val c = String(Character.toChars(cp))
        if (!isHan(cp)) return listOf(c)
        val readings = chars.readings(cp) ?: return listOf(c)
        val kept = LinkedHashSet<String>()
        for (reading in readings) if (reading.isNotEmpty()) kept.add(reading)
        return if (kept.isEmpty()) listOf("") else kept.toList()
    }

    private fun isHan(cp: Int): Boolean = hans.holds(cp)

    /** A run of Han, cut by mmseg (seg/mmseg.py, `Seg.cut` with no_non_phrases=True), each word read. */
    private fun readRun(run: String, errors: Errors, out: MutableList<String>) {
        var start = 0
        while (start < run.length) {
            var valid = -1  // where the longest phrase read so far ends
            var end = start
            var stopped = false
            while (end < run.length) {
                end += Character.charCount(run.codePointAt(end))
                val word = run.substring(start, end)
                val at = phrases.begins(word)
                if (at < 0) {
                    stopped = true
                    break
                }
                if (phrases.isPhrase(at, word)) valid = end
            }
            if (!stopped && valid < 0) {
                // The rest begins a phrase whole and none of its prefixes is one: each character alone, and done.
                var i = start
                while (i < run.length) {
                    val next = i + Character.charCount(run.codePointAt(i))
                    readWord(run.substring(i, next), errors, out)
                    i = next
                }
                return
            }
            if (valid < 0) valid = start + Character.charCount(run.codePointAt(start))
            readWord(run.substring(start, valid), errors, out)
            start = valid
        }
    }

    /** A word as converter.py's `_phrase_pinyin` reads it: a phrase's syllables, else each character's first reading. */
    private fun readWord(word: String, errors: Errors, out: MutableList<String>) {
        val at = phrases.begins(word)
        if (at >= 0 && phrases.isPhrase(at, word)) {
            out.addAll(phrases.syllables[at])
            return
        }
        var i = 0
        while (i < word.length) {
            val cp = word.codePointAt(i)
            val next = i + Character.charCount(cp)
            val readings = chars.readings(cp)
            if (readings != null) out.add(readings[0]) else if (errors == Errors.DEFAULT) out.add(word.substring(i, next))
            i = next
        }
    }

    private val hans: Hans by lazy { Hans(Data.text("hans.txt")) }
    private val chars: Chars by lazy { Chars(Data.text("chars.txt")) }
    private val phrases: Phrases by lazy { Phrases(Data.text("phrases.txt")) }

    /** RE_HANS's ranges. */
    private class Hans(text: String) {
        private val firsts: IntArray
        private val lasts: IntArray

        init {
            val lines = Data.lines("hans.txt", text)
            firsts = IntArray(lines.size)
            lasts = IntArray(lines.size)
            for ((n, line) in lines.withIndex()) {
                val fields = Data.fields("hans.txt", n, line, 2)
                firsts[n] = Data.hex("hans.txt", n, fields[0])
                lasts[n] = Data.hex("hans.txt", n, fields[1])
                Data.wellFormed(firsts[n] <= lasts[n] && (n == 0 || firsts[n] > lasts[n - 1] + 1), "hans.txt", n)
            }
        }

        fun holds(cp: Int): Boolean {
            var lo = 0
            var hi = firsts.size
            while (lo < hi) {  // the first range that starts after cp
                val mid = (lo + hi) ushr 1
                if (firsts[mid] <= cp) lo = mid + 1 else hi = mid
            }
            return lo > 0 && cp <= lasts[lo - 1]
        }
    }

    /** PINYIN_DICT: each character's readings. */
    private class Chars(text: String) {
        private val cps: IntArray
        private val readings: Array<Array<String>>

        init {
            val lines = Data.lines("chars.txt", text)
            val names = HashMap<String, String>()
            cps = IntArray(lines.size)
            readings = Array(lines.size) { n ->
                val fields = Data.fields("chars.txt", n, lines[n], 2)
                cps[n] = Data.hex("chars.txt", n, fields[0])
                Data.wellFormed(n == 0 || cps[n] > cps[n - 1], "chars.txt", n)
                fields[1].split(',').map { names.getOrPut(it) { it } }.toTypedArray()
            }
        }

        /** Its readings, never empty, or null for a character with none. */
        fun readings(cp: Int): Array<String>? {
            var lo = 0
            var hi = cps.size - 1
            while (lo <= hi) {
                val mid = (lo + hi) ushr 1
                when {
                    cps[mid] < cp -> lo = mid + 1
                    cps[mid] > cp -> hi = mid - 1
                    else -> return readings[mid]
                }
            }
            return null
        }
    }

    /** PHRASES_DICT: each phrase's syllables, the phrases in UTF-16 order. */
    private class Phrases(text: String) {
        private val keys: Array<String>
        val syllables: Array<Array<String>>

        init {
            val lines = Data.lines("phrases.txt", text)
            val names = HashMap<String, String>()
            keys = Array(lines.size) { "" }
            syllables = Array(lines.size) { n ->
                val fields = lines[n].split(' ')
                Data.wellFormed(fields.size >= 3 && fields.all { it.isNotEmpty() }, "phrases.txt", n)
                keys[n] = fields[0]
                Data.wellFormed(n == 0 || keys[n] > keys[n - 1], "phrases.txt", n)
                Array(fields.size - 1) { names.getOrPut(fields[it + 1]) { fields[it + 1] } }
            }
        }

        /** The index of the first phrase not below [word], when it begins with [word]; else -1. Every phrase that
         * begins with [word] sorts in one block from there, so this says whether [word] is a prefix of one. */
        fun begins(word: String): Int {
            var lo = 0
            var hi = keys.size
            while (lo < hi) {
                val mid = (lo + hi) ushr 1
                if (keys[mid] < word) lo = mid + 1 else hi = mid
            }
            return if (lo < keys.size && keys[lo].startsWith(word)) lo else -1
        }

        /** Whether the phrase [begins] found at [at] is [word] itself. */
        fun isPhrase(at: Int, word: String): Boolean = keys[at].length == word.length
    }

    /** The files of caracole/pinyin/, and the checks of their format. */
    private object Data {
        fun text(name: String): String {
            val path = "caracole/pinyin/$name"
            val stream = Pinyin::class.java.classLoader?.getResourceAsStream(path)
                ?: Pinyin::class.java.getResourceAsStream("/$path")
                ?: throw IllegalStateException("the resource $path is missing")
            return stream.use { it.readBytes().toString(Charsets.UTF_8) }
        }

        fun lines(name: String, text: String): List<String> {
            wellFormed(text.isEmpty() || text.endsWith('\n'), name, -1)
            return if (text.isEmpty()) emptyList() else text.substring(0, text.length - 1).split('\n')
        }

        fun fields(name: String, n: Int, line: String, count: Int): List<String> =
            line.split(' ').also { fields -> wellFormed(fields.size == count && fields.all { it.isNotEmpty() }, name, n) }

        fun hex(name: String, n: Int, digits: String): Int {
            wellFormed(digits.length in 1..6, name, n)
            var value = 0
            for (c in digits) {
                val digit = when (c) {
                    in '0'..'9' -> c - '0'
                    in 'a'..'f' -> c - 'a' + 10
                    else -> -1
                }
                wellFormed(digit >= 0, name, n)
                value = value * 16 + digit
            }
            return value
        }

        fun wellFormed(ok: Boolean, name: String, n: Int) {
            if (!ok) throw IllegalStateException(
                "caracole/pinyin/$name is not tests/test_conformance_pinyin.py's" + if (n >= 0) " at line ${n + 1}" else "",
            )
        }
    }
}
