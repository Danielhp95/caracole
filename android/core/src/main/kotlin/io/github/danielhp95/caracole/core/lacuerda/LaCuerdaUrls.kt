package io.github.danielhp95.caracole.core.lacuerda

import io.github.danielhp95.caracole.core.keys.Normalize
import io.github.danielhp95.caracole.core.py.Py
import io.github.danielhp95.caracole.core.py.PyRegex
import io.github.danielhp95.caracole.core.py.PyUnicode

/** lacuerda.py's slugs and addresses, as search needs them: an artist's page, a song's, a version's, a listing's. */
internal object LaCuerdaUrls {
    const val BASE_URL = "https://acordes.lacuerda.net"

    /** LaCuerda's initials, as the menu of /tabs/ links them: "#" (a name that starts with a digit) is _num, and "ñ"
     * is nn. */
    val LETTERS: List<String> = listOf("_num") + "abcdefghijklmn".map { it.toString() } + "nn" +
        "opqrstuvwxyz".map { it.toString() }
    const val FIRST_PAGE = "index0.html"

    private val ARTICLES = setOf("el", "la", "los", "las", "the")
    private val NOT_SLUG by lazy { PyRegex.compile("[^a-z0-9 ]") }
    private val AND_WORD by lazy { PyRegex.compile("""(?i)(?<!\S)y(?!\S)""") }

    /** The name's slug words. Removed punctuation leaves an empty word behind. */
    private fun words(name: String): List<String> {
        val s = PyUnicode.lower(PyUnicode.nfc(name)).replace("ñ", "ni")
        val slug = Py.strip(NOT_SLUG.replace(Normalize.fold(Py.split(s).joinToString(" ")), ""))
        return if (slug.isEmpty()) emptyList() else slug.split(" ")
    }

    /** LaCuerda's slug for an artist: "Joaquín Sabina" is `joaquin_sabina`; "" when nothing of the name survives (a
     * name in Chinese characters, say). */
    fun artistSlug(name: String): String {
        var words = words(name)
        if (words.size > 1 && words[0] in ARTICLES) words = words.drop(1)
        return words.joinToString("_")
    }

    /** Slugs worth trying for an artist, best guess first: [artistSlug], then the slug that keeps a leading article,
     * and the slugs with "y" and "&" swapped ("Fito y Fitipaldis" is LaCuerda's `fito__fitipaldis`). */
    fun artistSlugCandidates(name: String): List<String> {
        val variants = mutableListOf(name)
        if (AND_WORD.containsMatchIn(name)) variants.add(AND_WORD.replace(name, "&"))
        if ("&" in name) variants.add(name.replace("&", " y "))
        val out = ArrayList<String>()
        for (variant in variants) {
            for (slug in listOf(artistSlug(variant), words(variant).joinToString("_"))) {
                if (slug.isNotEmpty() && slug !in out) out.add(slug)
            }
        }
        return out
    }

    /** The artist page: `.../soda_stereo/`. */
    fun artistUrl(slug: String): String {
        require(slug.isNotEmpty()) { "empty LaCuerda artist slug" }
        return "$BASE_URL/$slug/"
    }

    /** The page of version [n]: `{song}.shtml` for 1, `{song}-{n}.shtml` after that. */
    fun versionUrl(artist: String, song: String, n: Int): String {
        require(artist.isNotEmpty() && song.isNotEmpty()) { "empty LaCuerda artist or song slug" }
        require(n >= 1) { "LaCuerda version numbers start at 1, not $n" }
        return "$BASE_URL/$artist/$song${if (n == 1) "" else "-$n"}.shtml"
    }

    /** A song's own page, which lists its versions: `.../soda_stereo/de_musica_ligera`. */
    fun songUrl(artist: String, song: String): String {
        require(artist.isNotEmpty() && song.isNotEmpty()) { "empty LaCuerda artist or song slug" }
        return "$BASE_URL/$artist/$song"
    }

    /** The path of a page of a letter's listing of every artist: `tabs/e/index0.html`. */
    fun listingPath(letter: String, page: String = FIRST_PAGE): String = "tabs/$letter/$page"
}
