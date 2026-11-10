package io.github.danielhp95.caracole.core.lacuerda.internal.pages

import io.github.danielhp95.caracole.core.keys.Normalize
import io.github.danielhp95.caracole.core.py.Py
import io.github.danielhp95.caracole.core.py.PyRe
import io.github.danielhp95.caracole.core.py.PyRegex
import io.github.danielhp95.caracole.core.py.PyUnicode

/**
 * lacuerda.py's "is it Spanish?": a text's share of Spanish function words against English ones, accents folded,
 * each character of an unspaced script a word of its own; a title's marks when there are no lyrics. The word lists
 * are lacuerda.py's, word for word (vectors/sites/lacuerda_pages.jsonl's `_language_counts` record reads each alone).
 */
internal object Spanish {
    private val SPANISH_WORDS: Set<String> = """
        de la que el en y los se del las un por con una su para es al lo como mas pero
        sus le ya este si porque esta entre cuando muy sobre tambien hasta hay donde
        quien desde todo nos todos uno les ni otro ese eso esto mi yo tu te ti tus mis
        nada ella ellos algo nosotros estoy estas estan eres soy fue era voy vas va
        tengo tienes tiene quiero puedo aqui asi ahora nunca siempre otra vez cada cual
        mucho poco tan tanto aunque contigo conmigo esa aquel nuestro nuestra hoy sea
        ser estar hacer puede
    """.let { Py.split(it) }.toSet()

    private val ENGLISH_WORDS: Set<String> = """
        the and of to in is it its you your youre i im ive ill id my we our us be been
        on for with are was were this that these those but not all so what can cant
        just do dont does did didnt know like when will wont would could should now up
        out if there they them their she her his at have has had from by one yeah never
        ever every more how why where who here about into over than then too very an or
        as got get gonna wanna say said see go
    """.let { Py.split(it) }.toSet()

    private val TOKEN by lazy { PyRegex.compile("""[a-z]+|[^\W\da-z_]""") }
    private val APOSTROPHE by lazy { PyRegex.compile("['’‘`´ʼ]") }
    private const val MIN_SPANISH_SHARE = 0.15

    private val SPANISH_SIGNS by lazy { PyRegex.compile("(?i)[ñ¿¡]") }
    private val SPANISH_ACCENTS by lazy { PyRegex.compile("(?i)[áéíóú]|gü") }
    private val OTHER_ACCENTS by lazy { PyRegex.compile("(?i)[àèìòùâêîôûãõçëïöÿåøæœß]|(?<!g)ü") }

    /** _language_counts: (Spanish words, English words, all words) in [text]. */
    fun counts(text: String): Triple<Int, Int, Int> {
        val tokens = PyRe.findall(TOKEN, PyRe.sub(APOSTROPHE, Normalize.fold(text)) { "" })
        return Triple(tokens.count { it in SPANISH_WORDS }, tokens.count { it in ENGLISH_WORDS }, tokens.size)
    }

    fun isSpanish(text: String): Boolean {
        val (spanish, english, total) = counts(text)
        return spanish > english && spanish >= MIN_SPANISH_SHARE * total
    }

    fun looksSpanish(title: String, lyrics: String?): Boolean {
        if (lyrics != null && Py.strip(lyrics).isNotEmpty()) return isSpanish(lyrics)
        return spanishSpelling(title) || isSpanish(title)
    }

    private fun spanishSpelling(title: String): Boolean {
        val s = PyUnicode.nfc(title)
        if (PyRe.search(SPANISH_SIGNS, s) != null) return true
        if (PyRe.search(SPANISH_ACCENTS, s) == null || PyRe.search(OTHER_ACCENTS, s) != null) return false
        val (spanish, english, _) = counts(s)
        return english <= spanish
    }
}
