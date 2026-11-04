package io.github.danielhp95.caracole.core.keys

import io.github.danielhp95.caracole.core.pinyin.Pinyin
import io.github.danielhp95.caracole.core.py.Py
import io.github.danielhp95.caracole.core.py.PyUnicode

/**
 * normalize.py on the phone: identity keys, folds and name forms, and lacuerda_index's keys. Its docstrings are
 * normalize.py's; this port follows it function for function, on code points where Python counts them.
 *
 * The logic is here; what normalize.py states as data (its tables, its sets, its patterns, Traditional to
 * Simplified) comes from caracole/keys/ ([KeyTables]), written from the module by tests/test_conformance_keys.py.
 * Every Unicode decision goes through core.py (PyUnicode, Py, PyRegex by [KeyPattern]) and every pinyin through
 * core.pinyin: no JDK or ICU text API, whose Unicode isn't Python's. The vectors of tests/conformance/vectors/keys/
 * hold it to Python's answers.
 *
 * As in normalize.py, [nameForms] and [listingForms] keep their last 8,192 answers, and an original's readings
 * their last 4,096.
 */
object Normalize {
    /** normalize.KEY_VERSION: a bump re-keys the phone's songs too (LibraryStore.ensureCurrentKeys). */
    const val KEY_VERSION = 2

    /** normalize.PINYIN_PARTIAL_SCALE: a part of a name matched in pinyin tops out at 85 (short syllables are no
     * proof), never a strong hit; search.py's `_Query` and lacuerda_index.py's scale one by it. */
    const val PINYIN_PARTIAL_SCALE = 0.85

    // --- folds and slug keys ---------------------------------------------------------------------------------------

    /** Lowercase, strip accents and transliterate letters NFKD can't decompose. */
    fun fold(s: String): String {
        if (isAscii(s)) return Py.asciiLower(s)  // NFKD, the combining marks and _TRANSLIT all leave ASCII as it is
        val decomposed = PyUnicode.nfkd(s)
        val out = StringBuilder(decomposed.length)
        val translit = KeyTables.translit
        forEachCodePoint(decomposed) { cp ->
            if (PyUnicode.combining(cp) == 0) {
                val t = translit[cp]
                if (t != null) out.append(t) else out.appendCodePoint(cp)
            }
        }
        return PyUnicode.lower(out.toString())
    }

    /** The words of a name, as [slugKey] makes them, but with CJK runs kept apart. */
    fun nameWords(s: String): List<String> {
        val words = tokens(withoutApostrophes(fold(s)))
        val kept = words.filter { it != "and" }.ifEmpty { words }
        return if (kept.size > 1 && kept[0] == "the") kept.drop(1) else kept
    }

    /** Whether [run] is some consecutive [words] written together. */
    fun holdsRun(words: List<String>, run: String): Boolean {
        for (i in words.indices) {
            val joined = StringBuilder()
            for (word in words.subList(i, words.size)) {
                joined.append(word)
                val now = joined.toString()
                if (now == run) return true
                if (!run.startsWith(now)) break
            }
        }
        return false
    }

    /** Drop streaming services' version suffixes: remasters, live and acoustic versions, featurings, mixes... */
    fun cleanTitle(t: String): String {
        var prev: String? = null
        var cur = Py.strip(t)
        while (cur != prev) {
            prev = cur
            cur = parenFeat.sub(cur)
            cur = parenSuffix.sub(cur)
            cur = Py.strip(dashSuffix.sub(cur))
        }
        return cur.ifEmpty { Py.strip(t) }
    }

    /** "acoustic" or "live" when the source title says so ("Acústico", "En Vivo" too), else null. */
    fun titleVariant(t: String): String? {
        val suffix = Py.slice(t, Py.len(cleanTitle(t)), null)
        if (acousticWord.search(suffix)) return "acoustic"
        if (liveWord.search(suffix)) return "live"
        return null
    }

    /** Map equivalent labels together: an unplugged version is an acoustic one. */
    fun canonicalVariant(v: String): String = if (v == "unplugged") "acoustic" else v

    /** The canonical key of a name or title. */
    fun slugKey(s: String): String = canon(tokens(withoutApostrophes(fold(s))))

    /** The canonical key of an Ultimate Guitar URL slug such as `the-rifles`. */
    fun ugSlugKey(slug: String): String = canon(fold(slug).split("-"))

    /** A key with its hyphens removed, so `ac-dc` meets `acdc`. */
    fun compact(key: String): String = key.replace("-", "")

    /** Split a trailing variant label off a song key: `x-intro` → (`x`, `intro`). */
    fun splitVariant(key: String): Pair<String, String?> {
        val dash = key.lastIndexOf('-')
        if (dash < 0) return key to null
        val head = key.substring(0, dash)
        val last = key.substring(dash + 1)
        return if (head.isNotEmpty() && last in KeyTables.variantTokens) head to last else key to null
    }

    /** Whether an artist, as written, stands for an artist one doesn't know ("misc", "Various Artists"). */
    fun placeholderArtist(name: String): Boolean =
        tokens(withoutApostrophes(fold(name))).joinToString("-") in KeyTables.placeholderArtists

    // --- identity keys ---------------------------------------------------------------------------------------------

    /** The identity of a song: the same song from any source gets the same key. */
    fun identityKey(artist: String, title: String): String =
        identity(artist, artist = true) + "/" + identity(cleanTitle(title), artist = false)

    /** lacuerda_index.name_key: identity_key(romanize(name), "")'s artist side. */
    fun lacuerdaNameKey(name: String): String = identityKey(romanize(name), "").substringBefore('/')

    /** lacuerda_index.title_key. */
    fun lacuerdaTitleKey(title: String): String = identityKey("", romanize(title)).substringAfter('/', "")

    /** How a song is written in overrides.toml and on the to-do page. */
    fun displayKey(artist: String, title: String): String = Py.strip(artist) + " - " + cleanTitle(title)

    /** A text with its Traditional Chinese characters written as Simplified ones (斑馬 → 斑马). */
    fun simplified(s: String): String {
        if (!hasHan(s)) return s
        val t2s = KeyTables.t2s
        val out = StringBuilder(s.length)
        forEachCodePoint(s) { cp -> out.appendCodePoint(t2s[cp] ?: cp) }
        return out.toString()
    }

    /** Whether the text contains Chinese characters. */
    fun hasHan(s: String): Boolean {
        forEachCodePoint(s) { cp -> if (isHan(cp)) return true }
        return false
    }

    /** Whether the text has letters of a script other than Latin. */
    fun hasOtherScript(s: String): Boolean {
        forEachCodePoint(s) { cp -> if (foreign(cp)) return true }
        return false
    }

    /** Hanyu Pinyin for Chinese characters; text without them is returned unchanged. */
    fun romanize(s: String): String {
        if (!hasHan(s)) return s
        val words = Pinyin.lazyPinyin(s).map { Py.strip(it) }.filter { it.isNotEmpty() && !allSplit(it) }
        return Py.strip(collapseSpaces(words.joinToString(" ")))
    }

    private fun identity(name: String, artist: Boolean): String {
        val present = tokens(withoutApostrophes(simplified(fold(name))))
        val dropped = if (artist) KeyTables.artistDropped else KeyTables.titleDropped
        var tokens = present.filter { it !in dropped }.ifEmpty { present }
        val numbers = KeyTables.numberWords
        tokens = tokens.map { numbers[it] ?: it }
        if (tokens.size > 1 && (tokens[0] == "the" || (artist && tokens[0] in KeyTables.spanishArticles))) {
            tokens = tokens.drop(1)
        }
        return join(tokens)
    }

    // --- a name's forms --------------------------------------------------------------------------------------------

    /** The name without the artists it features; the name itself when it features nobody, or is nothing else. */
    fun withoutFeaturing(s: String): String = Py.strip(featuring.sub(s)).ifEmpty { Py.strip(s) }

    /** The keys a name is compared by wherever a name caracole didn't write meets yours (normalize.name_forms). */
    fun nameForms(name: String): List<String> = nameFormsCache.get(name) { n ->
        val core = withoutFeaturing(n)
        val forms = ownKeys(n).toMutableList()
        if (core != Py.strip(n)) forms += ownKeys(core)
        val parts = parts(core)
        for (i in parts.indices) forms += partForms(i, parts)
        forms.distinct().filter { it.isNotEmpty() }
    }

    /** The forms of a title as UG lists it on an artist page (normalize.listing_forms). */
    fun listingForms(title: String): List<String> = listingFormsCache.get(title) { t ->
        val forms = nameForms(t).toMutableList()
        if (!hasOtherScript(t)) {
            val outside = slugKey(bracketed.sub(t, " "))
            if (outside.isNotEmpty() && !generic(outside)) forms += outside
        }
        forms.distinct()
    }

    /** The part of a name UG writes in two scripts that is in the original one, else the name as it is. */
    fun originalPart(name: String): String {
        val core = withoutFeaturing(name)
        return parts(core).firstOrNull { p -> anyCodePoint(p) { foreign(it) } }?.let { Py.strip(it) } ?: core
    }

    private val nameFormsCache = Lru<String, List<String>>(8192)
    private val listingFormsCache = Lru<String, List<String>>(8192)
    private val readingsCache = Lru<String, List<Set<String>?>?>(4096)

    private fun ownKeys(name: String): List<String> =
        if (hasHan(name)) listOf(slugKey(name), slugKey(romanize(name)), slugKey(simplified(name))) else listOf(slugKey(name))

    private const val NONE = 0
    private const val LATIN = 1
    private const val CJK = 2
    private const val OTHER = 3
    private val scripts = java.util.concurrent.ConcurrentHashMap<Int, Int>()

    /** A letter's script as name forms tell parts apart (CJK, Latin or other); [NONE] for a non-letter. */
    private fun script(cp: Int): Int = scripts.getOrPut(cp) {
        when {
            !PyUnicode.isAlpha(cp) -> NONE
            isCjk(cp) -> CJK
            isAscii(fold(string(cp))) || PyUnicode.latinByName(cp) -> LATIN
            else -> OTHER
        }
    }

    /** Whether a character is a letter of a script other than Latin. */
    private fun foreign(cp: Int): Boolean = script(cp).let { it == CJK || it == OTHER }

    /** A piece of a name with nothing between its parts, cut where the original ends and its romanization starts. */
    private fun cut(piece: String): List<String> {
        val c = Py.codePoints(piece)
        val last = c.indices.lastOrNull { foreign(c[it]) } ?: return listOf(piece)
        for (i in last + 1 until c.size) {
            val ch = c[i]
            if (script(ch) == LATIN) return listOf(piece)
            if (PyUnicode.isSpace(ch) || PyUnicode.category(ch)[0] in "PSZ") {
                val restLatin = (i until c.size).any { script(c[it]) == LATIN }
                return if (restLatin) listOf(Py.string(c, 0, i), Py.string(c, i)) else listOf(piece)
            }
        }
        return listOf(piece)
    }

    /** The parts of a name written in two scripts or more, with one non-Latin part; else none. */
    private fun parts(name: String): List<String> {
        val text = withoutApostrophes(name)
        val seen = HashSet<Int>()
        forEachCodePoint(text) { cp -> script(cp).let { if (it != NONE) seen += it } }
        if (seen.size < 2) return emptyList()
        val parts = partBreak.split(text).flatMap { cut(it) }.filter { slugKey(it).isNotEmpty() }
        val foreignParts = parts.count { p -> anyCodePoint(p) { foreign(it) } }
        return if (parts.size > 1 && foreignParts == 1) parts else emptyList()
    }

    /** One part's forms: its key, then its Simplified and pinyin keys (Chinese), or the romanization of the name's
     * original part it holds and the rest apart (Latin). (Python's `other is not part` is another index here: the
     * one part with another script is the only one it can be.) */
    private fun partForms(index: Int, parts: List<String>): List<String> {
        val part = parts[index]
        val key = slugKey(part)
        if (generic(key)) return emptyList()
        val forms = mutableListOf(key)
        if (hasHan(part)) {
            forms += slugKey(simplified(part))
            forms += slugKey(romanize(part))
        } else {
            for ((j, other) in parts.withIndex()) if (j != index && hasOtherScript(other)) forms += romanized(key, other)
        }
        return forms.filter { !generic(it) }
    }

    /** A Latin part's key split where the romanization of [original] starts or ends it. */
    private fun romanized(key: String, original: String): List<String> {
        val readings = readings(original)
        if (readings.isNullOrEmpty()) return emptyList()
        val words = key.split("-")
        for (n in 1 until words.size) {
            if (readsAs(words.subList(0, n).joinToString(""), readings)) {
                return listOf(canon(words.subList(0, n)), canon(words.subList(n, words.size)))
            }
            if (readsAs(words.subList(words.size - n, words.size).joinToString(""), readings)) {
                return listOf(canon(words.subList(words.size - n, words.size)), canon(words.subList(0, words.size - n)))
            }
        }
        return emptyList()
    }

    /** Whether a key names no song or artist on its own. */
    private fun generic(key: String): Boolean {
        val words = key.split("-").filter { it.isNotEmpty() && it !in KeyTables.genericWords && !PyUnicode.allDigit(it) }
        if (words.any { w -> anyCodePoint(w) { foreign(it) } }) return false
        return words.sumOf { Py.len(it) } < 2
    }

    // --- reading an original, to tell its romanization from a translation after it -------------------------------

    /** An original part of a name read one syllable at a time, each the set of its romanizations (null for a kanji,
     * normalize's _KANJI); null when it has letters caracole can't read. */
    private fun readings(original: String): List<Set<String>?>? = readingsCache.get(original) { readingsOf(it) }

    private fun readingsOf(original: String): List<Set<String>?>? {
        val chars = Py.codePoints(original)
        val japanese = chars.any { kanaLetter(it) }
        val readings = ArrayList<Set<String>?>()
        val pinyin = if (hasHan(original) && !japanese) pinyinReadings(original).iterator() else emptyList<Set<String>>().iterator()
        val fixed = StringBuilder()
        for (c in chars) {
            val letter = fold(string(c))
            if (isAscii(letter) && letter.isNotEmpty() && PyUnicode.allAlnum(letter)) {
                fixed.append(letter)
                continue
            }
            if (fixed.isNotEmpty()) {
                readings.add(setOf(fixed.toString()))
                fixed.setLength(0)
            }
            when {
                isHan(c) -> readings.add(if (japanese) null else if (pinyin.hasNext()) pinyin.next() else emptySet())
                c == ITERATION_MARK && japanese -> readings.add(null)
                c in 0xAC00..0xD7A3 -> readings.add(hangul(c))
                kanaLetter(c) || c == LONG_MARK -> kana(readings, if (c in 0x30A1..0x30F6) c - 0x60 else c)
                foreign(c) -> return null
            }
        }
        if (fixed.isNotEmpty()) readings.add(setOf(fixed.toString()))
        return readings
    }

    private const val ITERATION_MARK = 0x3005  // 々
    private const val LONG_MARK = 0x30FC  // ー
    private const val SMALL_TSU = 0x3063  // っ
    private const val HIRAGANA_U = 0x3046  // う

    /** Each Chinese character's readings in pinyin, in order: all of them, and pypinyin's in context. */
    private fun pinyinReadings(text: String): List<Set<String>> {
        val chars = Py.codePoints(text).filter { isHan(it) }
        val inContext = Pinyin.lazyPinyin(text, Pinyin.Errors.IGNORE)
        return chars.mapIndexed { i, c ->
            val found = LinkedHashSet(Pinyin.heteronyms(c))
            if (inContext.size == chars.size) found += inContext[i]
            found.flatMap { listOf(it, it.replace("v", "u")) }.toSet()
        }
    }

    /** A Hangul syllable's romanizations, from its jamo. */
    private fun hangul(c: Int): Set<String> {
        val n = c - 0xAC00
        val out = HashSet<String>()
        for (i in KeyTables.hangulInitials[n / 588]) for (m in KeyTables.hangulMedials[n % 588 / 28]) {
            for (f in KeyTables.hangulFinals[n % 28]) out += i + m + f
        }
        return out
    }

    /** Add a kana (as hiragana) to [readings]: a small ya, yu, yo or vowel joins the kana before it. */
    private fun kana(readings: MutableList<Set<String>?>, c: Int) {
        val before = readings.lastOrNull()?.takeIf { it.isNotEmpty() }
        val smallY = KeyTables.smallY[c]
        val smallVowel = KeyTables.smallVowels[c]
        when {
            smallY != null && before != null -> {
                val joined = before.mapTo(HashSet()) { allButLast(it) + "y" + smallY }
                for (r in before) if (allButLast(r) in SH_CH_J) joined += allButLast(r) + smallY
                readings[readings.size - 1] = joined
            }
            smallVowel != null && before != null -> {
                val joined = before.mapTo(HashSet()) { allButLast(it) + smallVowel }
                for (r in before) joined += r + smallVowel
                if ("u" in before) joined += "w$smallVowel"
                readings[readings.size - 1] = joined
            }
            c == SMALL_TSU -> readings.add(KeyTables.geminate)
            c == LONG_MARK -> readings.add(KeyTables.long)
            smallVowel != null || smallY != null -> readings.add(setOf(smallVowel ?: "y$smallY"))
            else -> KeyTables.kana[c]?.let { spellings ->
                val found = spellings.toHashSet()
                if (c == HIRAGANA_U && before != null && before.any { it.endsWith("o") || it.endsWith("u") }) found += ""
                readings.add(found)
            }
        }
    }

    private val SH_CH_J = setOf("sh", "ch", "j")

    private fun allButLast(r: String): String = Py.slice(r, null, -1)

    /** Whether [text] (compact Latin letters) is [readings] romanized, syllable after syllable. Indexes are UTF-16
     * units throughout, which reads as Python's code points do: no reading starts inside a character. */
    private fun readsAs(text: String, readings: List<Set<String>?>): Boolean {
        val memo = HashMap<Long, Boolean>()
        fun at(i: Int, j: Int): Boolean {
            val key = i.toLong() shl 32 or j.toLong()
            memo[key]?.let { return it }
            val answer = when {
                j == readings.size -> i == text.length
                readings[j] == null -> {
                    var k = i
                    var found = false
                    for (step in 0 until 3) {
                        k = mora.matchEnd(text, k) ?: break
                        if (at(k, j + 1)) {
                            found = true
                            break
                        }
                    }
                    found
                }
                else -> readings[j]!!.any { r -> text.startsWith(r, i) && at(i + r.length, j + 1) }
            }
            memo[key] = answer
            return answer
        }
        return at(0, 0)
    }

    // --- the pieces ------------------------------------------------------------------------------------------------

    private val dashSuffix by lazy { KeyTables.pattern("_DASH_SUFFIX") }
    private val parenFeat by lazy { KeyTables.pattern("_PAREN_FEAT") }
    private val parenSuffix by lazy { KeyTables.pattern("_PAREN_SUFFIX") }
    private val acousticWord by lazy { KeyTables.pattern("_ACOUSTIC_WORD") }
    private val liveWord by lazy { KeyTables.pattern("_LIVE_WORD") }
    private val partBreak by lazy { KeyTables.pattern("_PART_BREAK") }
    private val featuring by lazy { KeyTables.pattern("_FEATURING") }
    private val bracketed by lazy { KeyTables.pattern("_BRACKETED") }
    private val mora by lazy { KeyTables.pattern("_MORA") }

    private fun isCjk(cp: Int): Boolean = cp in KeyTables.cjk
    private fun isHan(cp: Int): Boolean = cp in KeyTables.han
    private fun kanaLetter(cp: Int): Boolean = cp in 0x3041..0x3096 || cp in 0x30A1..0x30FA

    /** _APOSTROPHES.sub("", s). */
    private fun withoutApostrophes(s: String): String {
        val apostrophes = KeyTables.apostrophes
        if (!anyCodePoint(s) { it in apostrophes }) return s
        val out = StringBuilder(s.length)
        forEachCodePoint(s) { cp -> if (cp !in apostrophes) out.appendCodePoint(cp) }
        return out.toString()
    }

    /** [s] cut by _SPLIT (`[\W_]+`, Python's \w) into its non-empty pieces: its runs of word characters but `_`. */
    internal fun tokens(s: String): List<String> {
        val out = ArrayList<String>()
        var start = -1
        var i = 0
        while (i < s.length) {
            val cp = s.codePointAt(i)
            val inWord = PyUnicode.isWord(cp) && cp != '_'.code
            if (inWord && start < 0) start = i
            if (!inWord && start >= 0) {
                out += s.substring(start, i)
                start = -1
            }
            i += Character.charCount(cp)
        }
        if (start >= 0) out += s.substring(start)
        return out
    }

    /** `_SPLIT.fullmatch(s)`: [s] is all `[\W_]`, and not empty. */
    private fun allSplit(s: String): Boolean = s.isNotEmpty() && !anyCodePoint(s) { PyUnicode.isWord(it) && it != '_'.code }

    /** `re.sub(r"\s+", " ", s)`: each run of Python's whitespace one space. */
    internal fun collapseSpaces(s: String): String {
        val out = StringBuilder(s.length)
        var inSpace = false
        forEachCodePoint(s) { cp ->
            if (PyUnicode.isSpace(cp)) {
                if (!inSpace) out.append(' ')
                inSpace = true
            } else {
                out.appendCodePoint(cp)
                inSpace = false
            }
        }
        return out.toString()
    }

    private fun canon(tokens: List<String>): String {
        val present = tokens.filter { it.isNotEmpty() }
        // Drop "and", unless the name is nothing but "and" (the band "And And And").
        var kept = present.filter { it != "and" }.ifEmpty { present }
        if (kept.size > 1 && kept[0] == "the") kept = kept.drop(1)
        return join(kept)
    }

    /** Tokens joined by '-', but CJK ones together: by the last code point so far and the next token's first. */
    private fun join(tokens: List<String>): String {
        val out = StringBuilder()
        for (tok in tokens) {
            if (out.isNotEmpty() && isCjk(lastCodePoint(out)) && isCjk(tok.codePointAt(0))) out.append(tok)
            else if (out.isNotEmpty()) out.append('-').append(tok)
            else out.append(tok)
        }
        return out.toString()
    }

    private fun lastCodePoint(s: StringBuilder): Int {
        val n = s.length
        val c = s[n - 1]
        return if (Character.isLowSurrogate(c) && n >= 2 && Character.isHighSurrogate(s[n - 2])) s.codePointAt(n - 2) else c.code
    }

    private fun isAscii(s: String): Boolean = s.all { it.code < 0x80 }

    private fun string(cp: Int): String = String(Character.toChars(cp))

    private inline fun forEachCodePoint(s: String, action: (Int) -> Unit) {
        var i = 0
        while (i < s.length) {
            val cp = s.codePointAt(i)
            action(cp)
            i += Character.charCount(cp)
        }
    }

    private inline fun anyCodePoint(s: String, test: (Int) -> Boolean): Boolean {
        forEachCodePoint(s) { if (test(it)) return true }
        return false
    }
}
