package io.github.danielhp95.caracole.core.keys

import io.github.danielhp95.caracole.core.py.PyUnicode

/**
 * library.safe_name and song_folder: the folder names a song's files go under. Names keep their accents and
 * scripts but never hold a path separator or a reserved character, so a song can't escape the library.
 */
object SafeName {
    /** A single path component made from a name: no separators, no reserved characters. */
    fun safeName(s: String): String {
        var t = PyUnicode.nfc(s)
        t = t.replace("/", "-").replace("\\", "-")
        t = colon.sub(t, " - ")
        t = controls.sub(t, " ")
        t = reserved.sub(t, "")
        t = stripSpacesAndDots(Normalize.collapseSpaces(t))
        if (utf8Length(t) > KeyTables.maxNameBytes) t = stripSpacesAndDots(utf8Prefix(t, KeyTables.maxNameBytes), left = false)
        return t.ifEmpty { "_" }
    }

    /** The song's folder: its artist's and its title's safe names (`library_dir / artist / title`). */
    fun songFolder(artist: String, title: String): Pair<String, String> =
        safeName(artist) to safeName(Normalize.cleanTitle(title))

    private val colon by lazy { KeyPattern("""\s*:\s*""", ignoreCase = false) }
    private val controls by lazy { KeyPattern("""[\t\r\n\v\f]+""", ignoreCase = false) }
    private val reserved by lazy { KeyTables.pattern("_RESERVED") }

    /** `str.strip(" .")`, or its rstrip. */
    private fun stripSpacesAndDots(s: String, left: Boolean = true): String {
        var start = 0
        var end = s.length
        while (end > start && (s[end - 1] == ' ' || s[end - 1] == '.')) end--
        if (left) while (start < end && (s[start] == ' ' || s[start] == '.')) start++
        return s.substring(start, end)
    }

    /** The length of `s.encode("utf-8")`; a lone surrogate is Python's UnicodeEncodeError. */
    private fun utf8Length(s: String): Int {
        var n = 0
        var i = 0
        while (i < s.length) {
            val cp = s.codePointAt(i)
            require(!(cp in 0xD800..0xDFFF)) { "UnicodeEncodeError: a lone surrogate at $i" }
            n += utf8Size(cp)
            i += Character.charCount(cp)
        }
        return n
    }

    /** `s.encode("utf-8")[:max].decode("utf-8", errors="ignore")`: the code points whose bytes all fit. */
    private fun utf8Prefix(s: String, max: Int): String {
        var n = 0
        var i = 0
        while (i < s.length) {
            val cp = s.codePointAt(i)
            if (n + utf8Size(cp) > max) break
            n += utf8Size(cp)
            i += Character.charCount(cp)
        }
        return s.substring(0, i)
    }

    private fun utf8Size(cp: Int): Int = when {
        cp < 0x80 -> 1
        cp < 0x800 -> 2
        cp < 0x10000 -> 3
        else -> 4
    }
}
