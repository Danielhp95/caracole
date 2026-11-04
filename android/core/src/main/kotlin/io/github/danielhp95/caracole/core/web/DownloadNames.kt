package io.github.danielhp95.caracole.core.web

import io.github.danielhp95.caracole.core.py.PyPath
import io.github.danielhp95.caracole.core.py.PyUnicode
import io.github.danielhp95.caracole.core.py.PyUrl
import java.math.BigInteger

/** The Unicode a download's name is read with: Python's, core.py's (lane py-unicode). */
internal interface NameText {
    fun nfc(s: String): String
    fun nfkd(s: String): String
    fun category(cp: Int): String
    fun combining(cp: Int): Int
    fun isSpace(cp: Int): Boolean
    fun isDecimal(cp: Int): Boolean
    fun lower(s: String): String
}

internal object PythonText : NameText {
    override fun nfc(s: String) = PyUnicode.nfc(s)
    override fun nfkd(s: String) = PyUnicode.nfkd(s)
    override fun category(cp: Int) = PyUnicode.category(cp)
    override fun combining(cp: Int) = PyUnicode.combining(cp)
    override fun isSpace(cp: Int) = PyUnicode.isSpace(cp)
    override fun isDecimal(cp: Int) = PyUnicode.isDecimal(cp)
    override fun lower(s: String) = PyUnicode.lower(s)
}

/**
 * download_names.py: the name a file a song keeps is downloaded under ("Eagles - Hotel California (2).gp5"), and the
 * Content-Disposition that names it, in ASCII and in UTF-8 (vectors/web/downloads.jsonl), read with Python's Unicode.
 */
object DownloadNames {
    private val named = DownloadNamer(PythonText)

    /** The name the file [fileName] of the song [title] (clean_title's) by [artist] is downloaded under. */
    fun downloadName(artist: String, title: String, fileName: String): String = named.downloadName(artist, title, fileName)

    /** `attachment`, the file named [name]: in ASCII (accents dropped, any other letter `_`), then in UTF-8. */
    fun contentDisposition(name: String): String = named.contentDisposition(name)
}

/** download_names.py's rules, over [text]'s Unicode. */
internal class DownloadNamer(private val text: NameText) {
    /** The stem's most bytes of UTF-8. */
    private val maxBytes = 150
    private val refused = "/\\:*?\"<>|"

    /** The name the file [fileName] of the song [title] by [artist] is downloaded under. */
    fun downloadName(artist: String, title: String, fileName: String): String {
        val numbered = numbered(fileName)
        val number = numbered?.first ?: BigInteger.ONE
        val extension = text.lower(numbered?.second ?: PyPath.suffix(fileName))
        val parts = listOf(artist, title).map { ends(clean(it)) }.filter { it.isNotEmpty() }
        val stem = fit(parts).joinToString(" - ")
        if (stem.isEmpty()) return fileName
        return stem + (if (number > BigInteger.ONE) " ($number)" else "") + extension
    }

    /** `attachment`, the file named [name]: in ASCII (accents dropped, any other letter `_`), then in UTF-8. */
    fun contentDisposition(name: String): String {
        val plain = StringBuilder()
        text.nfkd(name).codePoints().forEach { cp ->
            if (text.combining(cp) != 0) return@forEach
            plain.append(if (cp in 0x20..0x7E && cp.toChar() !in "%\"\\") cp.toChar() else '_')
        }
        return "attachment; filename=\"$plain\"; filename*=UTF-8''${PyUrl.quote(name, safe = "")}"
    }

    /** `(?:guitar|score)-(\d+)(\.[A-Za-z0-9]+)` matched whole: its number (any decimal digits, as int() reads
     * them) and its extension. */
    private fun numbered(name: String): Pair<BigInteger, String>? {
        val rest = when {
            name.startsWith("guitar-") -> name.substring("guitar-".length)
            name.startsWith("score-") -> name.substring("score-".length)
            else -> return null
        }
        val cps = rest.codePoints().toArray()
        var i = 0
        val digits = StringBuilder()
        while (i < cps.size && text.isDecimal(cps[i])) digits.append('0' + digit(cps[i++]))
        if (digits.isEmpty() || i >= cps.size || cps[i] != '.'.code) return null
        val extension = rest.substring(rest.offsetByCodePoints(0, i))
        val alnum = extension.drop(1)
        if (alnum.isEmpty() || !alnum.all { it in 'A'..'Z' || it in 'a'..'z' || it in '0'..'9' }) return null
        return BigInteger(digits.toString()) to extension
    }

    /** A decimal digit's value: its place in its run of ten (Unicode's Nd come as runs of 0 to 9). */
    private fun digit(cp: Int): Int {
        var start = cp
        while (text.isDecimal(start - 1)) start--
        return (cp - start) % 10
    }

    /** A name with what a system refuses taken out, its spaces one each. */
    private fun clean(part: String): String {
        val kept = StringBuilder()
        text.nfc(part).codePoints().forEach { cp ->
            val kind = text.category(cp)
            when {
                text.isSpace(cp) -> kept.append(' ')
                kind == "Cf" -> Unit
                kind.startsWith("C") || (cp < 0x80 && cp.toChar() in refused) -> kept.append('_')
                else -> kept.appendCodePoint(cp)
            }
        }
        return kept.toString().replace(Regex(" +"), " ").trim(' ')
    }

    private fun ends(stem: String): String = stem.trim(' ', '.')

    /** The parts of a stem, joined by " - ", cut to [maxBytes] bytes of UTF-8 in all. */
    private fun fit(parts: List<String>): List<String> {
        if (parts.size < 2) return parts.map { ends(cut(it, maxBytes)) }
        val room = maxBytes - " - ".length
        val sizes = parts.map { it.toByteArray().size }
        if (sizes.sum() <= room) return parts
        val half = room / 2
        val budgets = when {
            sizes[0] <= half -> listOf(sizes[0], room - sizes[0])
            sizes[1] <= half -> listOf(room - sizes[1], sizes[1])
            else -> listOf(half, room - half)
        }
        return parts.zip(budgets).map { (part, budget) -> ends(cut(part, budget)) }.filter { it.isNotEmpty() }
    }

    /** [text] cut to [size] bytes of UTF-8 on a whole character. */
    private fun cut(text: String, size: Int): String {
        val data = text.toByteArray()
        if (data.size <= size) return text
        var end = size
        while (end > 0 && (data[end].toInt() and 0xC0) == 0x80) end--
        return String(data, 0, end, Charsets.UTF_8)
    }
}
