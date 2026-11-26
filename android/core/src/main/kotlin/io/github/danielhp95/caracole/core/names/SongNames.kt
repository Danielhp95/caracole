package io.github.danielhp95.caracole.core.names

import io.github.danielhp95.caracole.core.db.Db
import io.github.danielhp95.caracole.core.keys.Normalize
import io.github.danielhp95.caracole.core.library.SongRow
import io.github.danielhp95.caracole.core.py.Py
import io.github.danielhp95.caracole.core.py.PyRe
import io.github.danielhp95.caracole.core.py.PyRegex
import io.github.danielhp95.caracole.core.py.PyUnicode

/**
 * song_names.py: the artist and the title a free text names, the one parser of it, for /api/search's `names` and the
 * phone's request form (lane song-names). Its rules and their order are song_names.py's module docstring; this file
 * keeps them in the same order, each regex Python's through [PyRegex] (an IGNORECASE one with sre's `(?i)`), each
 * word and key [Normalize]'s.
 *
 * The phone suggests no YouTube video for a query, so `read_names`' `video` (its rule 5) has no counterpart here.
 */
object SongNames {
    /** [text] without what a video's title adds to a song's name (a group of a video's or a lyric channel's words, a
     * lyric quoted, a last part of a video's words after a mark, such words loose at its end, quotes around it), its
     * spaces folded; its case, accents and marks kept as written. */
    fun clean(text: String): String {
        var t = Py.split(undecorated(Py.split(text).joinToString(" "))).joinToString(" ")
        while (true) { // "… | Official Video"
            val last = MARK.findAll(t).lastOrNull() ?: break
            if (!noise(t.substring(last.range.last + 1))) break
            t = t.substring(0, last.range.first)
        }
        looseAt(tokens(t))?.let { at -> t = Py.strip(t.substring(0, at)) }
        t = unquoted(t)
        return if (noise(t)) "" else t
    }

    /** Where a video's words loose at the end of [words] ([tokens]') begin: two or more, one strong among them, or one
     * of a format's ("HD"); null where there are none, or they stay (one alone: "Radio Video"). */
    private fun looseAt(words: List<Token>): Int? {
        var cut = words.size
        while (cut > 1 && !words[cut - 1].group && noiseWord(words[cut - 1].word)) cut -= 1
        val loose = words.subList(cut, words.size).map { it.word }
        if (loose.size > 1 && noise(loose.joinToString(" ")) ||
            loose.size == 1 && wordsOf(loose[0]).let { w -> w.isNotEmpty() && w.all { it in FORMAT } }
        ) {
            return words[cut].at
        }
        return null
    }

    /** A channel's name as an artist's: no " - Topic", no VEVO, Official or Oficial at its end. */
    fun cleanChannel(channel: String): String {
        val name = Py.split(channel).joinToString(" ")
        TOPIC.find(name)?.let { topic -> return Py.strip(topic.groupValues[1]) }
        val bare = Py.strip(LABEL.replace(name, ""))
        return bare.ifEmpty { name }
    }

    /**
     * The artist and the title [text] names (song_names.py's module docstring), or null for a text that doesn't say
     * who its artist is. [songs] are your library's; no database ([db] null) knows nothing but the channel given.
     * [channel]: [text] is the title of a video of that channel's, whose song it always names, "" for a part it can't
     * tell.
     */
    fun readNames(db: Db?, text: String, songs: List<SongRow>, channel: String? = null): Pair<String, String>? {
        val hints = listOfNotNull(channel).filter { it.isNotEmpty() }.map { cleanChannel(it) }.filter { it.isNotEmpty() }
        val known = Known(db, songs, hints)
        val cleaned = untagged(clean(text))
        val named = twoParts(cleaned, known) ?: bracketed(cleaned, known) ?: knownArtistIn(cleaned, known)
        if (named != null) return named
        if (channel != null) return cleanChannel(channel) to own(cleaned)
        return null
    }

    // --- the text, cleaned ---------------------------------------------------------------------------------------

    /** A video's words, no song's: a bracket of them alone goes, and so do they at the title's end. */
    private val NOISE = setOf(
        "official", "oficial", "officiel", "ufficiale", "music", "musical", "video", "v\u00eddeo", "videoclip", "clip",
        "audio", "lyric", "lyrics", "letra", "letras", "con", "with", "hd", "hq", "4k", "1080p", "720p", "mv", "m/v",
        "visualizer", "visualiser", "remastered", "remaster", "remasterizado", "remasterizada", "version", "versi\u00f3n",
        "pinyin", "karaoke", "ktv", "8d",
    )

    /** One of them makes words noise. */
    private val STRONG = NOISE - setOf("music", "musical", "con", "with", "version", "versi\u00f3n", "clip")

    /** Noise alone, even loose at a title's end. */
    private val FORMAT = setOf("hd", "hq", "4k", "1080p", "720p", "mv", "m/v")

    /** A lyric channel's words, no song's, in simplified and traditional characters, Japanese and Korean: noise as
     * [NOISE]'s. */
    private val CJK_NOISE = listOf(
        "动态歌词", "動態歌詞", "歌词", "歌詞", "字幕", "中英字幕", "拼音", "官方", "完整版", "高音质", "高音質", "高画质", "高畫質",
        "高清", "无损", "無損", "纯音乐", "純音樂", "抖音", "热门", "熱門", "循环", "循環", "版",
        "中文字幕", "繁體字幕", "简体字幕", "中字", "字幕版",
        "公式", "歌詞付き", "フル",
        "가사", "뮤직비디오", "공식",
    )

    /** A version's or an upload's tag, no title's: a bracket of them alone is never the title ("DJ版" is dj and 版). */
    private val TAGS = setOf(
        "live", "cover", "remix", "demo", "acoustic", "instrumental", "piano", "version", "ver", "dj",
        "翻唱", "现场", "現場", "现场版", "現場版", "伴奏", "纯享", "純享", "纯享版", "純享版", "合唱", "合唱版", "钢琴版", "鋼琴版",
        "吉他版", "女声版", "女聲版", "男声版", "男聲版", "加长版", "加長版", "重制版", "重製版", "原唱", "原版",
    )

    /** The longest first, then in code point order, as Python sorts `(-len(p), p)`. */
    private val CJK_NOISE_PHRASE = PyRegex.compile(
        CJK_NOISE.sortedWith(compareBy<String> { -Py.len(it) }.then(Py.CODE_POINT_ORDER)).joinToString("|"),
    )

    /** Hangul, kana and Han, as normalize.py's `_CJK`. */
    private const val CJK_LETTERS = "\\u1100-\\u11ff\\u3040-\\u30ff\\u3400-\\u4dbf\\u4e00-\\u9fff\\uac00-\\ud7af" +
        "\\uf900-\\ufaff\\U00020000-\\U0002ebef"
    private val CJK = PyRegex.compile("[$CJK_LETTERS]")

    /** A text holding CJK in words: runs of CJK, and of other letters and digits ("m/v" whole). */
    private val PIECE = PyRegex.compile("[$CJK_LETTERS]+|m/v(?![^\\W_$CJK_LETTERS])|[^\\W_$CJK_LETTERS]+")

    /** A space between two CJK characters: a sentence's. */
    private val CJK_GAP = PyRegex.compile("[$CJK_LETTERS]\\s+[$CJK_LETTERS]")

    /** A bracket pair, each opener closed by its own closer. */
    private val GROUPS = PyRegex.compile(
        "\\([^()]*\\)|\\[[^\\[\\]]*\\]|\uff08[^\uff08\uff09]*\uff09|\uff3b[^\uff3b\uff3d]*\uff3d" +
            "|\u3010[^\u3010\u3011]*\u3011|\u300c[^\u300c\u300d]*\u300d|\u300e[^\u300e\u300f]*\u300f" +
            "|\u300a[^\u300a\u300b]*\u300b" +
            "|\u3008[^\u3008\u3009]*\u3009|\u3016[^\u3016\u3017]*\u3017|\u3014[^\u3014\u3015]*\u3015",
    )

    /** A 「」 or 『』 group longer than this quotes a lyric, no title. */
    const val LYRIC_CHARS = 16

    /** The groups that quote a lyric. */
    private const val LYRIC_QUOTES = "\u300c\u300e"

    /** The groups that name a title: \u3010\u3011\u300a\u300b\u300c\u300d\u300e\u300f\u3008\u3009. */
    private const val TITLE_OPENERS = "\u3010\u300a\u300c\u300e\u3008"
    private val SENTENCE_END = Py.codePoints("\u3002\uff01\uff1f\u2026").toSet()

    /** The first splits "Artist - Title". */
    private val MARK = PyRegex.compile("\\s+(?:-|\u2013|\u2014|\\||~|//|_)\\s+")
    private val YEAR = PyRegex.compile("(?:19|20)\\d\\d")
    private val QUOTES = Py.codePoints("\"'\u201c\u201d\u2018\u2019\u00ab\u00bb\u300c\u300d\u300e\u300f").toSet()
    private val WORDS_SPLIT = PyRegex.compile("[\\s,.:!\u00a1\u00bf?\\-\u2013\u2014]+")

    // re.IGNORECASE, as sre's (?i): its "i" is İ and ı too.
    /** "Title by Artist". */
    private val BY = PyRegex.compile("(?i)\\s+by\\s+")
    private val TOPIC = PyRegex.compile("(?i)^(.*\\S)\\s+-\\s+topic$")
    private val LABEL = PyRegex.compile("(?i)\\s*(?:vevo|official|oficial|officiel)(?:\\s+channel)?$")

    /** song_names._words: NFKC, casefolded, split at spaces and punctuation; in a text holding CJK, its runs of CJK
     * and of other letters ([PIECE]), marks left out. */
    private fun wordsOf(text: String): List<String> {
        val folded = PyUnicode.casefold(PyUnicode.nfkc(text))
        if (PyRe.search(CJK, folded) != null) return PyRe.findall(PIECE, folded)
        return WORDS_SPLIT.split(folded).filter { it.isNotEmpty() }
    }

    private fun isCjkRun(word: String): Boolean = PyRe.match(CJK, word) != null

    /** How many characters of a run of CJK its [CJK_NOISE] phrases cover. */
    private fun covered(run: String): Int = PyRe.finditer(CJK_NOISE_PHRASE, run).sumOf { Py.len(it.value) }

    /** Whether one of [wordsOf]' words is a video's: in [NOISE] or a year, or a run of CJK of noise phrases alone. */
    private fun isNoise(word: String): Boolean =
        if (isCjkRun(word)) covered(word) == Py.len(word) else word in NOISE || YEAR.matches(word)

    /** "m/v"'s two. */
    private fun letters(word: String): Int = Py.len(word) - word.count { it == '/' }

    /** How many of a word's letters are a video's. */
    private fun noiseLetters(word: String): Int =
        if (isCjkRun(word)) covered(word) else if (isNoise(word)) letters(word) else 0

    /** Whether words are a video's alone: one strong word at least, a year or a lyric channel's words beside them. */
    private fun noise(text: String): Boolean {
        val words = wordsOf(text)
        return words.isNotEmpty() && words.any { it in STRONG } && words.all { isNoise(it) }
    }

    private fun noiseWord(word: String): Boolean {
        val words = wordsOf(word)
        return words.isNotEmpty() && words.all { isNoise(it) }
    }

    /** Whether a bracket's words are a video's: Latin ones by [noise]; ones holding CJK when a video's and a lyric
     * channel's words are two thirds of their letters or more. */
    private fun noiseGroup(inner: String): Boolean {
        if (PyRe.search(CJK, PyUnicode.nfkc(inner)) == null) return noise(inner)
        val words = wordsOf(inner)
        val letters = words.sumOf { letters(it) }
        return letters > 0 && 3 * words.sumOf { noiseLetters(it) } >= 2 * letters
    }

    /** Whether a 「」 or 『』 group's words are a sentence: ending as one, a space between two CJK characters, or
     * longer than [LYRIC_CHARS]. */
    private fun lyric(inner: String): Boolean {
        val s = Py.strip(inner)
        if (s.isEmpty()) return false
        val points = Py.codePoints(s)
        return points.last() in SENTENCE_END || PyRe.search(CJK_GAP, s) != null || points.size > LYRIC_CHARS
    }

    /** Whether a group of [text] is a video's: its words noise, or a lyric quoted where it isn't the whole text. */
    private fun decoration(group: MatchResult, text: String): Boolean {
        val inner = group.value.substring(1, group.value.length - 1)
        return noiseGroup(inner) || group.value[0] in LYRIC_QUOTES && lyric(inner) &&
            !(group.range.first == 0 && group.range.last + 1 == text.length)
    }

    /** [text], whose spaces are folded, without its groups that are a video's, each with the spaces before it. */
    private fun undecorated(text: String): String {
        val out = StringBuilder()
        var at = 0
        for (group in PyRe.finditer(GROUPS, text)) {
            out.append(text, at, group.range.first)
            if (decoration(group, text)) {
                while (out.isNotEmpty() && out[out.length - 1] == ' ') out.setLength(out.length - 1)
            } else {
                out.append(group.value)
            }
            at = group.range.last + 1
        }
        return out.append(text, at, text.length).toString()
    }

    /** A word of a text whose spaces are folded, where it begins, and whether it is a group. */
    private class Token(val at: Int, val word: String, val group: Boolean)

    /** The words of [text]: a group whole, and each run of other characters between spaces and groups (a group's
     * edges are word edges). */
    private fun tokens(text: String): List<Token> {
        val out = ArrayList<Token>()
        var at = 0
        val groups = PyRe.finditer(GROUPS, text).toList()
        for (i in 0..groups.size) {
            val group = groups.getOrNull(i)
            val end = group?.range?.first ?: text.length
            for (word in text.substring(at, end).split(" ")) {
                if (word.isNotEmpty()) out += Token(at, word, false)
                at += word.length + 1
            }
            if (group != null) {
                out += Token(group.range.first, group.value, true)
                at = group.range.last + 1
            }
        }
        return out
    }

    private fun unquoted(text: String): String {
        var t = text
        while (Py.len(t) > 1) {
            val points = Py.codePoints(t)
            if (points.first() !in QUOTES || points.last() !in QUOTES) break
            t = Py.strip(Py.slice(t, 1, -1))
        }
        return t
    }

    // --- the rules -----------------------------------------------------------------------------------------------

    /** Rule 1: "A - B", each its own words, turned round when only B is a known artist. */
    private fun twoParts(text: String, known: Known): Pair<String, String>? {
        val mark = MARK.find(text) ?: return null
        val first = unquoted(own(Py.strip(text.substring(0, mark.range.first))))
        val second = unquoted(own(Py.strip(text.substring(mark.range.last + 1))))
        if (Normalize.nameWords(first).isEmpty() || Normalize.nameWords(second).isEmpty()) return null
        if (known.artist(second) != null && known.artist(first) == null) return second to first
        return first to second
    }

    /** Whether [wordsOf]' words are a version's or an upload's tag ([TAGS]) alone, a video's beside them. */
    private fun tagged(words: List<String>): Boolean =
        words.any { it in TAGS } && words.all { it in TAGS || isNoise(it) }

    /** Whether a group is a CJK title group of a tag's words alone ("【Live】", "【现场版】", "【DJ版】"): never a title. */
    private fun tag(group: MatchResult): Boolean = group.value[0] in TITLE_OPENERS && tagged(wordsOf(inner(group)))

    /** [text]'s CJK title groups (【】《》「」『』〈〉), in order, but a tag's ([tag]). */
    private fun titles(text: String): List<MatchResult> =
        PyRe.finditer(GROUPS, text).filter { it.value[0] in TITLE_OPENERS && !tag(it) }.toList()

    /** [text] less the tag groups that lead it where words follow them, the upload's ("【翻唱】大鱼" is 大鱼); a tag group
     * after the song's words is the song's, as written ("大鱼【Live】"). */
    private fun untagged(text: String): String {
        var t = text
        while (true) {
            val group = PyRe.match(GROUPS, t) ?: break
            if (!tag(group) || Normalize.nameWords(t.substring(group.range.last + 1)).isEmpty()) break
            t = t.substring(group.range.last + 1).trimStart(' ')
        }
        return t
    }

    /** A group's content, its spaces stripped. */
    private fun inner(group: MatchResult): String = Py.strip(group.value.substring(1, group.value.length - 1))

    /** [text] less every group, its spaces folded. */
    private fun ungrouped(text: String): String = Py.split(PyRe.sub(GROUPS, text) { " " }).joinToString(" ")

    /** Whether [text] has words of its own outside its groups: a video's or a tag's alone ("MV", "Live") are none. */
    private fun ownWords(text: String): Boolean {
        val words = ungrouped(text)
        val found = wordsOf(words)
        return Normalize.nameWords(words).isNotEmpty() &&
            !(found.isNotEmpty() && found.all { it in TAGS || isNoise(it) })
    }

    /** [tokens]' words of [text], one holding CJK cut where its runs of CJK meet other letters ("米津玄師MV" is 米津玄師
     * and MV). */
    private fun pieces(text: String): List<Token> {
        val out = ArrayList<Token>()
        for (token in tokens(text)) {
            if (!token.group && PyRe.search(CJK, token.word) != null) {
                for (piece in PyRe.finditer(PIECE, token.word)) {
                    out += Token(token.at + piece.range.first, piece.value, false)
                }
            } else {
                out += token
            }
        }
        return out
    }

    /** [text], its spaces folded, less a video's words loose at its end as [clean] cuts them ([looseAt]), one glued to
     * a CJK name too: "米津玄師 MV" and "米津玄師MV" are 米津玄師, "Bethel Music" stays. */
    private fun artistWords(text: String): String {
        val t = Py.split(text).joinToString(" ")
        val at = looseAt(pieces(t)) ?: return t
        return Py.strip(t.substring(0, at))
    }

    /** [artist] less a leading "by", in any case, a whole word ("by 陈奕迅" is 陈奕迅). */
    private fun withoutBy(artist: String): String {
        val space = artist.indexOf(' ')
        val first = if (space < 0) artist else artist.substring(0, space)
        if (PyUnicode.casefold(first) != "by") return artist
        return if (space < 0) "" else artist.substring(space + 1)
    }

    /** A part's own words (rule 1): less the tag groups that lead it ([untagged]); then less its CJK title groups where
     * words of its own are outside its groups, else its first title group's content, its spaces folded; a part with
     * no title group as it is, its words a tag's or a video's or not ("Music「Live」"). */
    private fun own(text: String): String {
        val part = untagged(text)
        val titles = titles(part)
        if (titles.isEmpty()) return part
        if (!ownWords(part)) return inner(titles[0])
        val out = StringBuilder()
        var at = 0
        for (group in titles) {
            out.append(part, at, group.range.first).append(' ')
            at = group.range.last + 1
        }
        return Py.split(out.append(part, at, part.length).toString()).joinToString(" ")
    }

    /** Rule 2: a text no mark parts, its first CJK title group the title; the words before it the artist, less a
     * video's words loose at their end, but where they begin with an artist [known] knows and go on, those words the
     * title; else the words after it, less their groups; less a leading "by"; none for a title group alone. */
    private fun bracketed(text: String, known: Known): Pair<String, String>? {
        val titles = titles(text)
        if (PyRe.search(MARK, text) != null || titles.isEmpty()) return null
        val title = inner(titles[0])
        val before = artistWords(text.substring(0, titles[0].range.first))
        var artist: String
        if (ownWords(before)) {
            if (known.artist(before) == null && !known.title(before)) {
                first(before, known)?.let { return it } // "陈奕迅 孤勇者《英雄联盟：双城之战》" from 陈奕迅's channel
            }
            artist = before
        } else {
            artist = artistWords(ungrouped(text.substring(titles[0].range.last + 1)))
        }
        artist = withoutBy(artist)
        if (Normalize.nameWords(artist).isEmpty() || Normalize.nameWords(title).isEmpty()) return null
        return artist to title
    }

    /** Rule 3: a known artist first, or after the last " by ", the one of more words; none for a title whole. */
    private fun knownArtistIn(text: String, known: Known): Pair<String, String>? {
        val found = listOfNotNull(afterBy(text, known), first(text, known))
        if (found.isEmpty() || known.title(text)) return null
        // A tie: " by "'s, the first, as Python's max keeps it.
        var best = found[0]
        for (named in found.drop(1)) {
            if (Normalize.nameWords(named.first).size > Normalize.nameWords(best.first).size) best = named
        }
        return best
    }

    private fun afterBy(text: String, known: Known): Pair<String, String>? {
        for (by in BY.findAll(text).toList().asReversed()) {
            val title = text.substring(0, by.range.first)
            val artist = text.substring(by.range.last + 1)
            val name = if (Normalize.nameWords(title).isNotEmpty()) known.artist(artist) else null
            if (name != null) return name to title
        }
        return null
    }

    private fun first(text: String, known: Known): Pair<String, String>? {
        val words = Py.split(text)
        for (n in words.size - 1 downTo 1) {
            val artist = words.subList(0, n).joinToString(" ")
            val title = words.subList(n, words.size).joinToString(" ")
            if (n > 1 && Normalize.identityKey(artist, "") == Normalize.identityKey(words.subList(0, n - 1).joinToString(" "), "")) {
                continue // "Joaquín Sabina y nos dieron las diez": "y" ends no name
            }
            val name = if (Normalize.nameWords(title).isNotEmpty()) known.artist(artist) else null
            if (name != null) return name to title
        }
        return null
    }
}
