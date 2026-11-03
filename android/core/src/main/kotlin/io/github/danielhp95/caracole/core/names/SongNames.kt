package io.github.danielhp95.caracole.core.names

import io.github.danielhp95.caracole.core.db.Db
import io.github.danielhp95.caracole.core.keys.Normalize
import io.github.danielhp95.caracole.core.library.SongRow
import io.github.danielhp95.caracole.core.py.Py
import io.github.danielhp95.caracole.core.py.PyRegex
import io.github.danielhp95.caracole.core.py.PyUnicode

/**
 * song_names.py: the artist and the title a free text names, the one parser of it, for /api/search's `names` and the
 * phone's request form (lane song-names). Its rules and their order are song_names.py's module docstring; this file
 * keeps them in the same order, each regex Python's through [PyRegex] (an IGNORECASE one with sre's `(?i)`), each
 * word and key [Normalize]'s.
 *
 * The phone suggests no YouTube video for a query, so `read_names`' `video` (its rule 4) has no counterpart here.
 */
object SongNames {
    /** [text] without what a video's title adds to a song's name (a bracket of a video's words, a last part of them
     * after a mark, such words loose at its end, quotes around it), its spaces folded; its case, accents and marks
     * kept as written. */
    fun clean(text: String): String {
        var t = Py.split(BRACKETS.replace(Py.split(text).joinToString(" ")) { m ->
            if (noise(m.groupValues[1])) "" else m.value
        }).joinToString(" ")
        while (true) { // "… | Official Video"
            val last = MARK.findAll(t).lastOrNull() ?: break
            if (!noise(t.substring(last.range.last + 1))) break
            t = t.substring(0, last.range.first)
        }
        val words = Py.split(t)
        var cut = words.size
        while (cut > 1 && noiseWord(words[cut - 1])) cut -= 1
        val loose = words.subList(cut, words.size)
        if (loose.size > 1 && noise(loose.joinToString(" ")) ||
            loose.size == 1 && wordsOf(loose[0]).let { w -> w.isNotEmpty() && w.all { it in FORMAT } }
        ) {
            t = words.subList(0, cut).joinToString(" ")
        }
        t = unquoted(t)
        return if (noise(t)) "" else t
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
        val cleaned = clean(text)
        val named = twoParts(cleaned, known) ?: knownArtistIn(cleaned, known)
        if (named != null) return named
        if (channel != null) return cleanChannel(channel) to cleaned
        return null
    }

    // --- the text, cleaned ---------------------------------------------------------------------------------------

    /** A video's words, no song's: a bracket of them alone goes, and so do they at the title's end. */
    private val NOISE = setOf(
        "official", "oficial", "officiel", "ufficiale", "music", "musical", "video", "v\u00eddeo", "videoclip", "clip",
        "audio", "lyric", "lyrics", "letra", "letras", "con", "with", "hd", "hq", "4k", "1080p", "720p", "mv", "m/v",
        "visualizer", "visualiser", "remastered", "remaster", "remasterizado", "remasterizada", "version", "versi\u00f3n",
    )

    /** One of them makes words noise. */
    private val STRONG = NOISE - setOf("music", "musical", "con", "with", "version", "versi\u00f3n", "clip")

    /** Noise alone, even loose at a title's end. */
    private val FORMAT = setOf("hd", "hq", "4k", "1080p", "720p", "mv", "m/v")

    /** The first splits "Artist - Title". */
    private val MARK = PyRegex.compile("\\s+(?:-|\u2013|\u2014|\\||~|//)\\s+")
    private val YEAR = PyRegex.compile("(?:19|20)\\d\\d")
    private val BRACKETS = PyRegex.compile(
        "\\s*[(\\[\u3010\u300c]([^()\\[\\]\u3010\u3011\u300c\u300d]*)[)\\]\u3011\u300d]",
    )
    private val QUOTES = Py.codePoints("\"'\u201c\u201d\u2018\u2019\u00ab\u00bb\u300c\u300d\u300e\u300f").toSet()
    private val WORDS_SPLIT = PyRegex.compile("[\\s,.:!\u00a1\u00bf?\\-\u2013\u2014]+")

    // re.IGNORECASE, as sre's (?i): its "i" is İ and ı too.
    /** "Title by Artist". */
    private val BY = PyRegex.compile("(?i)\\s+by\\s+")
    private val TOPIC = PyRegex.compile("(?i)^(.*\\S)\\s+-\\s+topic$")
    private val LABEL = PyRegex.compile("(?i)\\s*(?:vevo|official|oficial|officiel)(?:\\s+channel)?$")

    /** song_names._words: NFKC, casefolded, split at spaces and punctuation. */
    private fun wordsOf(text: String): List<String> =
        WORDS_SPLIT.split(PyUnicode.casefold(PyUnicode.nfkc(text))).filter { it.isNotEmpty() }

    /** Whether words are a video's alone: one strong word at least, a year beside them too. */
    private fun noise(text: String): Boolean {
        val words = wordsOf(text)
        return words.isNotEmpty() && words.any { it in STRONG } && words.all { it in NOISE || YEAR.matches(it) }
    }

    private fun noiseWord(word: String): Boolean {
        val words = wordsOf(word)
        return words.isNotEmpty() && words.all { it in NOISE || YEAR.matches(it) }
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

    /** Rule 1: "A - B", turned round when only B is a known artist. */
    private fun twoParts(text: String, known: Known): Pair<String, String>? {
        val mark = MARK.find(text) ?: return null
        val first = unquoted(Py.strip(text.substring(0, mark.range.first)))
        val second = unquoted(Py.strip(text.substring(mark.range.last + 1)))
        if (Normalize.nameWords(first).isEmpty() || Normalize.nameWords(second).isEmpty()) return null
        if (known.artist(second) != null && known.artist(first) == null) return second to first
        return first to second
    }

    /** Rule 2: a known artist first, or after the last " by ", the one of more words; none for a title whole. */
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
