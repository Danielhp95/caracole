package io.github.danielhp95.caracole.core.py

/** Python 3.14's unicodedata (16.0.0) and str methods, from the tables in caracole/unicode/ (lane py-unicode). */
object PyUnicode {
    const val UNIDATA_VERSION = "16.0.0"

    fun isAlnum(cp: Int): Boolean = TODO("lane py-unicode")
    fun isAlpha(cp: Int): Boolean = TODO("lane py-unicode")
    fun isDecimal(cp: Int): Boolean = TODO("lane py-unicode")
    fun isDigit(cp: Int): Boolean = TODO("lane py-unicode")
    fun isNumeric(cp: Int): Boolean = TODO("lane py-unicode")
    fun isSpace(cp: Int): Boolean = TODO("lane py-unicode")

    /** re's \w: isalnum() or '_'. */
    fun isWord(cp: Int): Boolean = TODO("lane py-unicode")
    fun isPrintable(cp: Int): Boolean = TODO("lane py-unicode")

    /** "Lu", "Mn", … */
    fun category(cp: Int): String = TODO("lane py-unicode")
    fun combining(cp: Int): Int = TODO("lane py-unicode")

    /** "LATIN" in unicodedata.name(c). */
    fun latinByName(cp: Int): Boolean = TODO("lane py-unicode")

    fun lower(s: String): String = TODO("lane py-unicode")
    fun upper(s: String): String = TODO("lane py-unicode")
    fun casefold(s: String): String = TODO("lane py-unicode")
    fun nfc(s: String): String = TODO("lane py-unicode")
    fun nfkc(s: String): String = TODO("lane py-unicode")
    fun nfd(s: String): String = TODO("lane py-unicode")
    fun nfkd(s: String): String = TODO("lane py-unicode")

    /** sre's IGNORECASE class representative. */
    fun ignoreCaseKey(cp: Int): Int = TODO("lane py-unicode")

    fun allAlnum(s: String): Boolean = TODO("lane py-unicode")
    fun allDigit(s: String): Boolean = TODO("lane py-unicode")
    fun allAlpha(s: String): Boolean = TODO("lane py-unicode")
    fun allSpace(s: String): Boolean = TODO("lane py-unicode")
}
