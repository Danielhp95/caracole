package io.github.danielhp95.caracole.server.page

import io.github.danielhp95.caracole.core.json.PyJson
import io.github.danielhp95.caracole.core.keys.Normalize
import io.github.danielhp95.caracole.core.py.Py
import io.github.danielhp95.caracole.core.py.PyRe
import io.github.danielhp95.caracole.core.py.PyRegex
import io.github.danielhp95.caracole.core.py.PyUnicode
import io.github.danielhp95.caracole.core.py.PyUrl
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import java.math.BigInteger

/**
 * What library_page.py writes of a song's card for the page to sort, letter, filter and list it by, as the phone's
 * cards of its own songs carry it: `_sort_key`, `_letter`, `_initials` and `_haystack` exactly
 * (tests/conformance/vectors/web/cards.jsonl), on normalize.py's folds (core.keys.Normalize) and Python's notion of a
 * letter or a digit (core.py.PyUnicode.isAlnum, which `[^\W_]` and `[\W_]` rest on); and of a kept file, its label,
 * its place in the song's line, the one the line opens, where it came from with no record of its site, and its link
 * (`_label`, `_in_line_order`, `_primary`, icons.source_of, `_files`' href), cards.jsonl's too.
 */
internal object CardText {
    /** _sort_key: "The Beatles" under B, 宋冬野 under S (by pinyin). */
    fun sortKey(text: String): String = Normalize.slugKey(Normalize.romanize(text)).ifEmpty { Normalize.fold(text) }

    /** _letter: the A–Z strip's letter for a sort key, "#" for a digit or anything else. */
    fun letter(sortKey: String): String {
        val first = sortKey.firstOrNull()
        return if (first != null && first in 'a'..'z') (first - ('a' - 'A')).toString() else "#"
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

    // library_page.py's patterns, read as Python reads them: \d is any decimal digit, as int() reads it.
    private val GUITAR = PyRegex.compile("guitar-(\\d+)(\\.[A-Za-z0-9]+)")
    private val SCORE = PyRegex.compile("score-(\\d+)(\\.[a-z]+)")
    private val HARMONICA = PyRegex.compile("harmonica-(\\d+)\\.txt")
    private val GAMETAB = PyRegex.compile("gametab-(\\d+)\\.txt")

    /** inbox.SCORE_EXTENSIONS, in its order, and the format each names (library_page._SCORE_FORMATS). */
    private val SCORE_FORMATS = linkedMapOf(".mscz" to "MuseScore", ".mxl" to "MusicXML", ".musicxml" to "MusicXML",
                                            ".pdf" to "PDF", ".mid" to "MIDI", ".midi" to "MIDI")
    private val SCORE_EXTENSIONS = SCORE_FORMATS.keys.toList()
    private val LABELS = mapOf(
        "sheet.html" to "Sheet viewer", "sheet (auto).html" to "Auto sheet viewer", "sheet.pdf" to "Sheet PDF",
        "sheet (auto).pdf" to "Auto sheet PDF", "sheet (Traditional).pdf" to "Sheet PDF, Traditional",
        "sheet (auto, Traditional).pdf" to "Auto sheet PDF, Traditional", "sheet.txt" to "Sheet text",
        "sheet.cho" to "ChordPro", "lyrics.txt" to "Lyrics", "lyrics.lrc" to "Timed lyrics", "tab.txt" to "Tab",
        "sheet (auto).txt" to "Auto sheet text", "sheet (auto).cho" to "Auto ChordPro", "info.json" to "Info",
    )

    /** What a line opens (library_page._primary): a sheet's viewer or PDF, else a sheet's text. */
    private val VIEWERS = listOf("sheet.html", "sheet (auto).html", "sheet.pdf", "sheet (auto).pdf")
    private val SHEET_TEXTS = listOf("sheet.txt", "sheet (auto).txt")

    /** icons.py: lyrics.txt and lyrics.lrc are LRCLIB's (LYRICS), the auto sheet and what is made of it the audio
     * model's (AUTO: songs.SHEET_OUTPUTS' and TRADITIONAL_PDFS' of "sheet (auto).txt"). */
    private val LYRICS_FILES = listOf("lyrics.txt", "lyrics.lrc")
    private val AUTO_FILES = listOf("sheet (auto).txt", "sheet (auto).cho", "sheet (auto).pdf", "sheet (auto).html",
                                    "sheet (auto, Traditional).pdf")
    const val LYRICS = "lrclib"
    const val AUTO = "auto"

    /** _in_line_order: the kept files of [names] a song's line lists, in its order, the sheet's [exports] (as given)
     * after its viewers and PDFs; a name of none of its groups is left out, as the computer's page leaves it. */
    fun inLineOrder(names: Set<String>, exports: List<String> = emptyList()): List<String> =
        SHEET_PAGES.filter { it in names } + exports + FIRST.filter { it in names && it !in SHEET_PAGES } +
            numbered(GUITAR, names) + scores(names) + numbered(HARMONICA, names) + numbered(GAMETAB, names) +
            LAST.filter { it in names }

    /** _primary: the file a song's line opens, the first of [ordered] that is a sheet's viewer or PDF, else the
     * first that is a sheet's text; null for neither. */
    fun primary(ordered: List<String>): String? =
        ordered.firstOrNull { it in VIEWERS } ?: ordered.firstOrNull { it in SHEET_TEXTS }

    /** icons.source_of(name, {}): where a kept file came from, with no record of its version's site (the phone's
     * cards of its own songs): the lyrics LRCLIB's, an auto sheet's files the audio model's, null for the rest. */
    fun sourceOf(name: String): String? = when (name) {
        in LYRICS_FILES -> LYRICS
        in AUTO_FILES -> AUTO
        else -> null
    }

    /** Whether the file has a name it downloads under (library_page._files' `download`): a Guitar Pro or Power Tab
     * file, a score but its PDF. */
    fun downloads(name: String): Boolean =
        PyRe.fullmatch(GUITAR, name) != null || (PyRe.fullmatch(SCORE, name) != null && !name.endsWith(".pdf"))

    private val BY_NUMBER = compareBy<Pair<BigInteger, String>> { it.first }.thenComparator { a, b ->
        Py.CODE_POINT_ORDER.compare(a.second, b.second)
    }

    private fun numbered(pattern: Regex, names: Set<String>): List<String> =
        names.mapNotNull { n -> PyRe.fullmatch(pattern, n)?.let { int(it.groupValues[1]) to n } }
            .sortedWith(BY_NUMBER).map { it.second }

    private fun scores(names: Set<String>): List<String> =
        names.mapNotNull { n ->
            PyRe.fullmatch(SCORE, n)?.takeIf { it.groupValues[2] in SCORE_EXTENSIONS }
                ?.let { Triple(int(it.groupValues[1]), SCORE_EXTENSIONS.indexOf(it.groupValues[2]), n) }
        }.sortedWith(compareBy<Triple<BigInteger, Int, String>> { it.first }.thenBy { it.second }
                         .thenComparator { a, b -> Py.CODE_POINT_ORDER.compare(a.third, b.third) })
            .map { it.third }

    /** int() of a run of decimal digits, in any script: each its place in its run of ten (Unicode's Nd come as
     * runs of 0 to 9). */
    private fun int(digits: String): BigInteger {
        val ascii = StringBuilder()
        digits.codePoints().forEach { cp ->
            var start = cp
            while (PyUnicode.isDecimal(start - 1)) start--
            ascii.append('0' + (cp - start) % 10)
        }
        return BigInteger(ascii.toString())
    }

    /** _label of a file caracole kept: "Sheet text", "Guitar Pro 2", "Score 1 (MusicXML)"; a Guitar Pro, harmonica or
     * game music tab with the site it came from after it ([source]: "Guitar Pro 1 · gtptabs.com"). */
    fun label(name: String, source: String? = null): String {
        val from = if (source.isNullOrEmpty()) "" else " · $source"
        PyRe.fullmatch(GUITAR, name)?.let { m ->
            return (if (PyUnicode.lower(m.groupValues[2]) == ".ptb") "Power Tab" else "Guitar Pro") + " " +
                m.groupValues[1] + from
        }
        PyRe.fullmatch(SCORE, name)?.let { m -> SCORE_FORMATS[m.groupValues[2]]?.let { return "Score ${m.groupValues[1]} ($it)" } }
        PyRe.fullmatch(HARMONICA, name)?.let { return "Harmonica tab ${it.groupValues[1]}$from" }
        PyRe.fullmatch(GAMETAB, name)?.let { return "Game music tab ${it.groupValues[1]}$from" }
        return LABELS[name] ?: name
    }

    /** library_page._LABELS' label of a sheet's own file ([UKULELE_LABELLED]'s), for its Ukulele Chords label. */
    fun ownLabel(name: String): String = LABELS.getValue(name)

    /** library_page._UKULELE_LABELLED: the human sheet's files, which a sheet of UG's Ukulele Chords labels so. */
    val UKULELE_LABELLED: List<String> = listOf("sheet.html", "sheet.pdf", "sheet.txt", "sheet.cho")

    /** library_page.UKULELE_SHEET: what a sheet from UG's Ukulele Chords type is called on the page. */
    const val UKULELE_SHEET = "Ukulele Chords"

    /** Whether [name] is a kept Guitar Pro or Power Tab file's name (library_page._GUITAR). */
    fun isGuitar(name: String): Boolean = PyRe.fullmatch(GUITAR, name) != null

    /** Whether [name] is a kept harmonica tab's name (library_page._HARMONICA). */
    fun isHarmonica(name: String): Boolean = PyRe.fullmatch(HARMONICA, name) != null

    /** Whether [name] is a score filed from the inbox of a format the line lists (library_page._SCORE and
     * inbox.SCORE_EXTENSIONS). */
    fun isScore(name: String): Boolean = PyRe.fullmatch(SCORE, name)?.groupValues?.get(2) in SCORE_EXTENSIONS

    /**
     * library.lyrics_from: where a song's lyrics link back to, `{source, href}`, for a site of [LYRICS_PAGES] and a
     * page on it alone (its card's Lyrics tile links it); null for any other, or lyrics that can't be read. Read from
     * the stored JSON alone, as json.loads reads it.
     */
    fun lyricsFrom(lyricsStatus: String, lyricsJson: String?): JsonElement {
        val stored = lyricsJson?.let { runCatching { PyJson.loads(it) }.getOrNull() } as? JsonObject ?: return JsonNull
        if (lyricsStatus != "found") return JsonNull
        val provider = (stored["provider"] as? JsonPrimitive)?.takeIf { it.isString }?.content
        val url = (stored["url"] as? JsonPrimitive)?.takeIf { it.isString }?.content
        val site = provider?.let { LYRICS_PAGES[it] }
        if (site == null || url == null || !url.startsWith(site)) return JsonNull
        return JsonObject(linkedMapOf("source" to JsonPrimitive(provider), "href" to JsonPrimitive(url)))
    }

    /** library.LYRICS_PAGES: the lyrics sites whose fair use asks a link back, by provider, and where their pages are. */
    val LYRICS_PAGES = mapOf("megalobiz" to "https://megalobiz.com/", "azlyrics" to "https://www.azlyrics.com/")

    /** A path in the library as the page links it, relative to `/`: each part percent-encoded as urllib's
     * quote(part, safe="") encodes it. */
    fun href(path: String): String = path.split('/').joinToString("/") { PyUrl.quote(it, safe = "") }
}
