package io.github.danielhp95.caracole.server.page

import io.github.danielhp95.caracole.core.keys.Normalize
import io.github.danielhp95.caracole.core.py.PyUnicode

/**
 * What library_page.py writes of a song's card for the page to sort, letter, filter and list it by, as the phone's
 * cards of its own songs carry it: `_sort_key`, `_letter`, `_initials` and `_haystack` exactly
 * (tests/conformance/vectors/web/cards.jsonl), on normalize.py's folds (core.keys.Normalize) and Python's notion of a
 * letter or a digit (core.py.PyUnicode.isAlnum, which `[^\W_]` and `[\W_]` rest on); and a kept file's label, its
 * place in the song's line and its link (`_label`, `_in_line_order`, `_files`' href).
 */
internal object CardText {
    /** _sort_key: "The Beatles" under B, 宋冬野 under S (by pinyin). */
    fun sortKey(text: String): String = Normalize.slugKey(Normalize.romanize(text)).ifEmpty { Normalize.fold(text) }

    /** _letter: the A–Z strip's letter for a sort key, "#" for a digit or anything else. */
    fun letter(sortKey: String): String {
        val first = sortKey.firstOrNull()
        return if (first != null && first in 'a'..'z') first.uppercase() else "#"
    }

    /** _initials: "wywh" for Wish You Were Here (斑马斑马's by pinyin, "bmbm"); "" for a title of one word. */
    fun initials(title: String): String {
        val folded = Normalize.fold(if (Normalize.hasHan(title)) Normalize.romanize(title) else title)
        val words = runs(folded.filter { it !in APOSTROPHES })
        return if (words.size > 1) words.joinToString("") { String(Character.toChars(it.codePointAt(0))) } else ""
    }

    /** _haystack: what the page's filter looks in, folded, the same without punctuation, and pinyin. */
    fun haystack(texts: List<String>): String {
        val parts = LinkedHashSet<String>()
        for (text in texts) {
            val forms = mutableListOf(Normalize.fold(text))
            if (Normalize.hasHan(text)) forms.add(Normalize.fold(Normalize.romanize(text)))
            for (form in forms) {
                parts.add(form)
                parts.add(runs(form).joinToString(""))
            }
        }
        return parts.filter { it.isNotEmpty() }.joinToString(" | ")
    }

    /** The runs of letters and digits in [text] (re's `[^\W_]+`), in order. */
    private fun runs(text: String): List<String> {
        val found = ArrayList<String>()
        val run = StringBuilder()
        var i = 0
        while (i < text.length) {
            val cp = text.codePointAt(i)
            if (PyUnicode.isAlnum(cp)) {
                run.appendCodePoint(cp)
            } else if (run.isNotEmpty()) {
                found.add(run.toString())
                run.setLength(0)
            }
            i += Character.charCount(cp)
        }
        if (run.isNotEmpty()) found.add(run.toString())
        return found
    }

    /** library_page._APOSTROPHES: what a word holds that no initial counts. */
    private const val APOSTROPHES = "'’‘`´ʼ"

    // --- a kept file ------------------------------------------------------------------------------------------

    private val SHEET_PAGES = listOf("sheet.html", "sheet.pdf", "sheet (Traditional).pdf", "sheet (auto).html",
                                     "sheet (auto).pdf", "sheet (auto, Traditional).pdf")
    private val FIRST = SHEET_PAGES + listOf("sheet.txt", "sheet.cho", "lyrics.txt", "lyrics.lrc")
    private val LAST = listOf("tab.txt", "sheet (auto).txt", "sheet (auto).cho", "info.json")
    private val GUITAR = Regex("guitar-([0-9]+)(\\.[A-Za-z0-9]+)")
    private val SCORE = Regex("score-([0-9]+)(\\.[a-z]+)")
    private val HARMONICA = Regex("harmonica-([0-9]+)\\.txt")
    private val GAMETAB = Regex("gametab-([0-9]+)\\.txt")

    /** inbox.SCORE_EXTENSIONS, in its order, and the format each names. */
    private val SCORE_FORMATS = linkedMapOf(".mscz" to "MuseScore", ".mxl" to "MusicXML", ".musicxml" to "MusicXML",
                                            ".pdf" to "PDF", ".mid" to "MIDI", ".midi" to "MIDI")
    private val LABELS = mapOf(
        "sheet.html" to "Sheet viewer", "sheet (auto).html" to "Auto sheet viewer", "sheet.pdf" to "Sheet PDF",
        "sheet (auto).pdf" to "Auto sheet PDF", "sheet (Traditional).pdf" to "Sheet PDF, Traditional",
        "sheet (auto, Traditional).pdf" to "Auto sheet PDF, Traditional", "sheet.txt" to "Sheet text",
        "sheet.cho" to "ChordPro", "lyrics.txt" to "Lyrics", "lyrics.lrc" to "Timed lyrics", "tab.txt" to "Tab",
        "sheet (auto).txt" to "Auto sheet text", "sheet (auto).cho" to "Auto ChordPro", "info.json" to "Info",
    )

    /** _in_line_order with no exports: the kept files of [names] a song's line lists, in its order; a name of none of
     * its groups is left out, as the computer's page leaves it. */
    fun inLineOrder(names: Set<String>): List<String> =
        SHEET_PAGES.filter { it in names } + FIRST.filter { it in names && it !in SHEET_PAGES } +
            numbered(GUITAR, names) + scores(names) + numbered(HARMONICA, names) + numbered(GAMETAB, names) +
            LAST.filter { it in names }

    private fun numbered(pattern: Regex, names: Set<String>): List<String> =
        names.mapNotNull { n -> pattern.matchEntire(n)?.let { it.groupValues[1].toBigInteger() to n } }
            .sortedWith(compareBy<Pair<java.math.BigInteger, String>> { it.first }.thenBy { it.second })
            .map { it.second }

    private fun scores(names: Set<String>): List<String> {
        val order = SCORE_FORMATS.keys.toList()
        return names.mapNotNull { n ->
            SCORE.matchEntire(n)?.takeIf { it.groupValues[2] in order }?.let { Triple(it.groupValues[1].toBigInteger(), order.indexOf(it.groupValues[2]), n) }
        }.sortedWith(compareBy<Triple<java.math.BigInteger, Int, String>> { it.first }.thenBy { it.second }.thenBy { it.third })
            .map { it.third }
    }

    /** _label of a file caracole kept, with no source: "Sheet text", "Guitar Pro 2", "Score 1 (MusicXML)". */
    fun label(name: String): String {
        GUITAR.matchEntire(name)?.let { m ->
            return (if (m.groupValues[2].lowercase() == ".ptb") "Power Tab" else "Guitar Pro") + " " + m.groupValues[1]
        }
        SCORE.matchEntire(name)?.let { m -> SCORE_FORMATS[m.groupValues[2]]?.let { return "Score ${m.groupValues[1]} ($it)" } }
        HARMONICA.matchEntire(name)?.let { return "Harmonica tab ${it.groupValues[1]}" }
        GAMETAB.matchEntire(name)?.let { return "Game music tab ${it.groupValues[1]}" }
        return LABELS[name] ?: name
    }

    /** A path in the library as the page links it, relative to `/`: each part percent-encoded as urllib's
     * quote(part, safe="") encodes it. */
    fun href(path: String): String = path.split('/').joinToString("/") { quote(it) }

    private fun quote(part: String): String = buildString {
        for (byte in part.toByteArray(Charsets.UTF_8)) {
            val c = byte.toInt() and 0xff
            if (c in 'A'.code..'Z'.code || c in 'a'.code..'z'.code || c in '0'.code..'9'.code || c.toChar() in "_.-~") {
                append(c.toChar())
            } else {
                append('%').append("0123456789ABCDEF"[c shr 4]).append("0123456789ABCDEF"[c and 15])
            }
        }
    }
}
