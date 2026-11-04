package io.github.danielhp95.caracole.core.pinyin

/**
 * pypinyin 0.55.0 as caracole asks it: in Style.NORMAL (normalize.py) `lazy_pinyin(text)` and
 * `lazy_pinyin(text, errors="ignore")` are [lazyPinyin], `pinyin(c, style=Style.NORMAL, heteronym=True)[0]` is
 * [heteronyms]; in Style.TONE (viewer/pinyin.py) `lazy_pinyin(text, style=Style.TONE, errors=_none)` is
 * [lazyPinyin] with [Style.TONE] and [Errors.EMPTY_EACH]. It reads a text as pypinyin does (core.py, converter.py,
 * utils.py, seg/simpleseg.py, seg/mmseg.py):
 *
 * 1. The text is cut into runs of the characters pypinyin's `RE_HANS` matches (hans.txt) and runs of the others.
 * 2. A run of others is itself ([Errors.DEFAULT]), nothing ([Errors.IGNORE]) or "" for each of its code points
 *    ([Errors.EMPTY_EACH]).
 * 3. A run of Han is cut by mmseg's forward maximum matching over pypinyin's phrases: from where it stands, it reads
 *    one more character at a time while what it read begins some phrase; the word is the longest phrase among
 *    those, or with none its first character alone. When the whole rest of the run begins a phrase, the word is
 *    again the longest phrase among its prefixes and the cut goes on after it; with none, each character of the
 *    rest is a word alone, and the run ends there.
 * 4. A phrase reads as its syllables (phrases.txt); a lone character as its first reading (chars.txt), else as
 *    itself ([Errors.DEFAULT]), nothing ([Errors.IGNORE]) or "" ([Errors.EMPTY_EACH]).
 *
 * Each reading is in the [Style] asked: [Style.TONE] is the dictionaries' own (pypinyin's `to_tone` gives it as it
 * is), [Style.NORMAL] pypinyin's `to_normal` of it ([normal]: each tone mark of symbols.txt replaced, those of one
 * character first, then those of two, then every digit dropped: tone marks dropped, ü written v).
 *
 * Its dictionaries are pypinyin's own, in Style.TONE alone, written by tests/test_conformance_pinyin.py into
 * caracole/pinyin/ on the classpath, each read on first use (UTF-8, a line each; that file's docstring is their
 * format's too, and checks what this takes for granted: a reading holds no digit of its own, and every reading's
 * [normal] is pypinyin's):
 * - hans.txt: `<first> <last>`, the ranges of code points `RE_HANS` matches, inclusive, in lowercase hex, in order;
 * - chars.txt: `<code point in lowercase hex> <reading>,<reading>,…`, PINYIN_DICT by code point, in its order;
 * - phrases.txt: `<phrase> <syllable> <syllable> …`, PHRASES_DICT in UTF-16 order (a binary search finds a word in
 *   it, and whether it begins a phrase);
 * - symbols.txt: `<symbol> <replacement>`, pypinyin's tone marks (a character or two) in its order.
 *
 * Everything is on code points, with no JDK text API: nothing here depends on the JDK's Unicode or Android's ICU.
 */
object Pinyin {
    /** What pypinyin gives what it reads no pinyin in: itself, nothing, or "" for each of its code points
     * (viewer/pinyin.py's `_none`, a callable `errors`). */
    enum class Errors { DEFAULT, IGNORE, EMPTY_EACH }

    /** Style.TONE, the dictionaries' readings as they are (zhōng), or Style.NORMAL, `to_normal`'s of them (zhong). */
    enum class Style { TONE, NORMAL }

    /** `lazy_pinyin(text, style=…, errors=…)`: a reading for each Han character read, and each run of others as
     * [errors] says. */
    fun lazyPinyin(text: String, errors: Errors = Errors.DEFAULT, style: Style = Style.NORMAL): List<String> {
        val tone = style == Style.TONE
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
            if (han) readRun(run, errors, tone, out) else others(run, errors, out)
            start = end
        }
        return out
    }

    /** Whether [text] is a phrase of PHRASES_DICT, a word pypinyin reads whole (viewer/pinyin.py's `_zhu`). */
    fun isPhrase(text: String): Boolean {
        val at = phrases.begins(text)
        return at >= 0 && phrases.isPhrase(at, text)
    }

    /**
     * pypinyin's `to_normal` of a reading in Style.TONE: each of symbols.txt's one-character symbols replaced, then
     * each of its two-character ones, in its order, then every digit dropped (ASCII's: a reading holds none of its
     * own, the generator checks, so the digits are the replacements').
     */
    fun normal(reading: String): String {
        val out = StringBuilder(reading.length)
        var i = 0
        while (i < reading.length) {
            val cp = reading.codePointAt(i)
            val replacement = symbols.single[cp]
            if (replacement != null) out.append(replacement) else out.appendCodePoint(cp)
            i += Character.charCount(cp)
        }
        var replaced = out.toString()
        for ((symbol, to) in symbols.double) replaced = replaced.replace(symbol, to)
        val kept = StringBuilder(replaced.length)
        for (c in replaced) if (c !in '0'..'9') kept.append(c)
        return kept.toString()
    }

    /**
     * pinyin(c, style=NORMAL, heteronym=True)[0]: each of the character's readings in Style.NORMAL once, in
     * pypinyin's order (an empty one dropped, `[""]` were none left); a Han character with no reading, or any other
     * character, is itself.
     * A code point beyond U+10FFFF is an [IllegalArgumentException], as `chr` raises ValueError. (pypinyin would read a
     * phrase of one character as its phrase; it has none, which the generator checks.)
     */
    fun heteronyms(cp: Int): List<String> {
        val c = String(Character.toChars(cp))
        if (!isHan(cp)) return listOf(c)
        val readings = chars.readings(cp, tone = false) ?: return listOf(c)
        val kept = LinkedHashSet<String>()
        for (reading in readings) if (reading.isNotEmpty()) kept.add(reading)
        return if (kept.isEmpty()) listOf("") else kept.toList()
    }

    private fun isHan(cp: Int): Boolean = hans.holds(cp)

    /** A run of others, as [errors] says. */
    private fun others(run: String, errors: Errors, out: MutableList<String>) {
        when (errors) {
            Errors.DEFAULT -> out.add(run)
            Errors.IGNORE -> {}
            Errors.EMPTY_EACH -> {
                var i = 0
                while (i < run.length) {
                    out.add("")
                    i += Character.charCount(run.codePointAt(i))
                }
            }
        }
    }

    /** A run of Han, cut by mmseg (seg/mmseg.py, `Seg.cut` with no_non_phrases=True), each word read. */
    private fun readRun(run: String, errors: Errors, tone: Boolean, out: MutableList<String>) {
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
                    readWord(run.substring(i, next), errors, tone, out)
                    i = next
                }
                return
            }
            if (valid < 0) valid = start + Character.charCount(run.codePointAt(start))
            readWord(run.substring(start, valid), errors, tone, out)
            start = valid
        }
    }

    /** A word as converter.py's `_phrase_pinyin` reads it: a phrase's syllables, else each character's first reading
     * (a Han character with none as [errors] says: in Style.TONE and NORMAL alike it stays itself). */
    private fun readWord(word: String, errors: Errors, tone: Boolean, out: MutableList<String>) {
        val at = phrases.begins(word)
        if (at >= 0 && phrases.isPhrase(at, word)) {
            out.addAll(phrases.syllables(at, tone))
            return
        }
        var i = 0
        while (i < word.length) {
            val cp = word.codePointAt(i)
            val next = i + Character.charCount(cp)
            val readings = chars.readings(cp, tone)
            when {
                readings != null -> out.add(readings[0])
                errors == Errors.DEFAULT -> out.add(word.substring(i, next))
                errors == Errors.EMPTY_EACH -> out.add("")
                else -> {}
            }
            i = next
        }
    }

    private val hans: Hans by lazy { Hans(Data.text("hans.txt")) }
    private val symbols: Symbols by lazy { Symbols(Data.text("symbols.txt")) }
    private val chars: Chars by lazy { Chars(Data.text("chars.txt"), Normals()) }
    private val phrases: Phrases by lazy { Phrases(Data.text("phrases.txt"), Normals()) }

    /** symbols.txt: the tone marks [normal] replaces, those of one code point by it and those of two in order. */
    private class Symbols(text: String) {
        val single = HashMap<Int, String>()
        val double = ArrayList<Pair<String, String>>()

        init {
            for ((n, line) in Data.lines("symbols.txt", text).withIndex()) {
                val fields = Data.fields("symbols.txt", n, line, 2)
                val cps = fields[0].codePoints().toArray()
                Data.wellFormed(cps.size in 1..2, "symbols.txt", n)
                if (cps.size == 1) single[cps[0]] = fields[1] else double.add(fields[0] to fields[1])
            }
        }
    }

    /** Each reading's Style.NORMAL, derived once a distinct reading as the data loads. */
    private class Normals {
        private val seen = HashMap<String, String>()

        fun of(tone: String): String = seen.getOrPut(tone) { normal(tone) }
    }

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

    /** PINYIN_DICT: each character's readings, in Style.TONE and, derived, Style.NORMAL. */
    private class Chars(text: String, normals: Normals) {
        private val cps: IntArray
        private val tones: Array<Array<String>>
        private val normals: Array<Array<String>>

        init {
            val lines = Data.lines("chars.txt", text)
            val names = HashMap<String, String>()
            cps = IntArray(lines.size)
            tones = Array(lines.size) { n ->
                val fields = Data.fields("chars.txt", n, lines[n], 2)
                cps[n] = Data.hex("chars.txt", n, fields[0])
                Data.wellFormed(n == 0 || cps[n] > cps[n - 1], "chars.txt", n)
                fields[1].split(',').map { names.getOrPut(it) { it } }.toTypedArray()
            }
            this.normals = Array(tones.size) { n -> Array(tones[n].size) { normals.of(tones[n][it]) } }
        }

        /** Its readings in Style.TONE or NORMAL, never empty, or null for a character with none. */
        fun readings(cp: Int, tone: Boolean): Array<String>? {
            var lo = 0
            var hi = cps.size - 1
            while (lo <= hi) {
                val mid = (lo + hi) ushr 1
                when {
                    cps[mid] < cp -> lo = mid + 1
                    cps[mid] > cp -> hi = mid - 1
                    else -> return if (tone) tones[mid] else normals[mid]
                }
            }
            return null
        }
    }

    /** PHRASES_DICT: each phrase's syllables in Style.TONE and, derived, Style.NORMAL, the phrases in UTF-16 order. */
    private class Phrases(text: String, normals: Normals) {
        private val keys: Array<String>
        private val tones: Array<Array<String>>
        private val normals: Array<Array<String>>

        init {
            val lines = Data.lines("phrases.txt", text)
            val names = HashMap<String, String>()
            keys = Array(lines.size) { "" }
            tones = Array(lines.size) { n ->
                val fields = lines[n].split(' ')
                Data.wellFormed(fields.size >= 3 && fields.all { it.isNotEmpty() }, "phrases.txt", n)
                keys[n] = fields[0]
                Data.wellFormed(n == 0 || keys[n] > keys[n - 1], "phrases.txt", n)
                Array(fields.size - 1) { names.getOrPut(fields[it + 1]) { fields[it + 1] } }
            }
            this.normals = Array(tones.size) { n -> Array(tones[n].size) { normals.of(tones[n][it]) } }
        }

        /** The syllables of the phrase at [at], in Style.TONE or NORMAL. */
        fun syllables(at: Int, tone: Boolean): List<String> = (if (tone) tones[at] else normals[at]).asList()

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
