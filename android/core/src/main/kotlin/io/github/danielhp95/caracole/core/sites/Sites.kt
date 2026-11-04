package io.github.danielhp95.caracole.core.sites

import io.github.danielhp95.caracole.core.db.Db
import io.github.danielhp95.caracole.core.json.Canonical
import io.github.danielhp95.caracole.core.json.CanonicalError
import io.github.danielhp95.caracole.core.keys.Normalize
import io.github.danielhp95.caracole.core.library.Songs
import io.github.danielhp95.caracole.core.py.Py
import io.github.danielhp95.caracole.core.py.PyRegex
import io.github.danielhp95.caracole.core.py.PyUnicode
import io.github.danielhp95.caracole.core.search.Queries
import io.github.danielhp95.caracole.core.search.SearchLimits
import io.github.danielhp95.caracole.core.search.SiteHit
import io.github.danielhp95.caracole.core.search.internal.ug.UgHits
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonPrimitive

// What search reads of each site's module (harptabs.py, gametabs.py, musescore.py, gtptabs.py), and the helpers
// search.py shares between its sites (_title_words, no_ones, _titled_only, _known_song, _listed_names). Every word
// and key is Normalize's, every Unicode decision core.py's.

/** harptabs.py: its pages' addresses and the keys of its tabs. */
internal object HarpTabs {
    const val BASE_URL = "https://www.harptabs.com"
    const val TAB = "tab"
    const val ARTIST = "artist"

    // The slugs the sitemap lists are lowercase ASCII letters, digits and hyphens (harptabs.py _PAGE); \d is Python's.
    private val PAGE by lazy {
        PyRegex.compile("""https://(?:www\.)?harptabs\.com/((tab|artist)/(\d{1,9})/([a-z0-9-]{1,200}))""")
    }
    private val BRACKETED by lazy { PyRegex.compile("""\([^()]*\)|\[[^\[\]]*\]""") }
    private val BRACKET by lazy { PyRegex.compile("""[()\[\]]""") }
    private val CONTRACTED = setOf("t", "s", "ll", "re", "ve", "d", "m")

    /** The address of a page, from its path as the index keeps it (`tab/25/piano-man`). */
    fun pageUrl(path: String): String = "$BASE_URL/$path"

    /** parse_page_url's key of a page's address: a tab's slug's, its contractions [joined], an artist's; null for
     * any other address, or a slug without a key. */
    fun pageKey(url: String): String? {
        val m = PAGE.matchEntire(url) ?: return null
        val kind = m.groupValues[2]
        val slug = m.groupValues[4]
        val key = if (kind == TAB) joined(Normalize.ugSlugKey(slug)) else Normalize.ugSlugKey(slug)
        return key.ifEmpty { null }
    }

    /** A slug's key with each contraction's or possessive's end, a word of its own there ("can-t", "heaven-s",
     * "i-m"), joined to the word before it ("cant", "heavens", "im"). */
    fun joined(key: String): String {
        val words = ArrayList<String>()
        for (word in key.split("-")) {
            if (words.isNotEmpty() && word in CONTRACTED) words[words.size - 1] = words.last() + word else words.add(word)
        }
        return words.joinToString("-")
    }

    /** The key a song's title meets the tabs' titles with: its version suffixes go first (clean_title). */
    fun titleKey(title: String): String = Normalize.slugKey(Normalize.cleanTitle(title))

    /** The song a tab's title names: the title less what it says in brackets, which is the tab's own ("Piano Man (C
     * Harmonica)" is Piano Man), a bracket left open gone too; the title as it is when nothing else is left. */
    fun songTitle(title: String): String {
        var text = title
        var before: String? = null
        while (text != before) {
            before = text
            text = BRACKETED.replace(text, " ")
        }
        text = Py.split(BRACKET.replace(text, " ")).joinToString(" ")
        return if (Py.codePoints(text).any { PyUnicode.isAlnum(it) }) text else Py.strip(title)
    }

    /** The title part of the identity key of the song a tab's title names ([songTitle]), Chinese in pinyin. */
    fun songKey(title: String): String =
        Normalize.identityKey("", Normalize.romanize(songTitle(title))).substringAfter('/', "")
}

/** gametabs.py: its pages' addresses and its tabs' title keys. */
internal object GameTabs {
    const val BASE_URL = "https://gametabs.net"
    const val TAB = "tab"
    const val GAME = "game"

    fun pageUrl(path: String): String = "$BASE_URL/$path"

    /** The key a song's title meets the tabs' titles with: its version suffixes go first (clean_title). */
    fun titleKey(title: String): String = Normalize.slugKey(Normalize.cleanTitle(title))
}

/** musescore.py: its song pages' addresses and title keys. */
internal object MuseScore {
    const val BASE_URL = "https://musescore.com"

    fun pageUrl(path: String): String = "$BASE_URL/$path"

    fun titleKey(title: String): String = Normalize.slugKey(Normalize.cleanTitle(title))
}

/** gtptabs.py: its pages' addresses. */
internal object GtpTabs {
    const val BASE_URL = "https://gtptabs.com"

    fun pageUrl(path: String): String = "$BASE_URL/$path"
}

/** What search.py's sites share. */
internal object SiteText {
    /** search.py `_title_words`: a key's words, each with its first letter as str.upper writes it. */
    fun titleWords(key: String): String = key.split("-").filter { it.isNotEmpty() }.joinToString(" ") {
        PyUnicode.upper(Py.slice(it, 0, 1)) + Py.slice(it, 1, null)
    }

    /** search.no_ones: an artist key that is no one's name, every `misc-…` of UG's (UgHits.noOnes). */
    fun noOnes(artistKey: String): Boolean = UgHits.noOnes(artistKey)

    /** search.py `_listed_names`: the names of a JSON array gametabs_game_tabs keeps; none of anything else, nor of
     * a text json.loads refuses (Canonical.parse reads what it reads, and nothing more). */
    fun listedNames(text: String?): List<String> {
        val names = try {
            Canonical.parse(text?.ifEmpty { null } ?: "[]")
        } catch (e: CanonicalError) {
            return emptyList()
        }
        if (names !is JsonArray) return emptyList()
        return names.mapNotNull { (it as? JsonPrimitive)?.takeIf { p -> p.isString }?.content }
    }

    /** search.py `_titled_only`: an artist's songs on another site, with [title] only those whose title it matches,
     * best first, each scored by its title; all of them, as they come, without. */
    fun titledOnly(hits: List<SiteHit>, title: String?): List<SiteHit> {
        val queries = Queries.of(title ?: "")
        if (queries.isEmpty()) return hits
        val scored = hits.mapIndexed { n, h ->
            Triple(queries.maxOf { it.score("", h.titleKey.replace("-", " ")) }, n, h)
        }
        return scored.filter { it.first >= SearchLimits.MIN_SCORE }
            .sortedWith(compareBy<Triple<Double, Int, SiteHit>>({ -it.first }, { it.second }))
            .map { (score, _, h) -> h.copy(score = Py.round(score, 1), via = "title") }
    }

    /** The artist keys gtptabs.com may file a key [form] under: the form, and the form with its last word first
     * ("Elton John" is `john-elton`), as gtptabs.artist_keys files them. */
    fun gtptabsFiled(form: String): List<String> {
        val words = form.split("-")
        return LinkedHashSet(listOf(form, (listOf(words.last()) + words.dropLast(1)).joinToString("-"))).toList()
    }

    /**
     * search.py `_known_song`: whether [artist] names the artist of a song titled [titleKey] (a MuseScore title key)
     * in the Ultimate Guitar index, gtptabs.com's (which files people last name first) or your library. [mine] caches
     * your songs' (artist form, title key) pairs, filled on the first call that needs them.
     */
    fun knownSong(db: Db, artist: String, titleKey: String, mine: Mine): Boolean {
        val forms = Normalize.nameForms(artist).filter { it.isNotEmpty() && !noOnes(it) && !Normalize.placeholderArtist(it) }
        for (form in forms) {
            if (db.one("SELECT 1 FROM ug_index WHERE artist_key = ? AND song_key = ? LIMIT 1", form, titleKey) { 1 } != null) {
                return true
            }
            val filed = gtptabsFiled(form)
            val marks = filed.joinToString(", ") { "?" }
            if (db.one("SELECT 1 FROM gtptabs_index WHERE artist_key IN ($marks) AND base_key = ? LIMIT 1",
                       *filed.toTypedArray(), titleKey) { 1 } != null) {
                return true
            }
        }
        if (forms.isEmpty()) return false
        val pairs = mine.pairs ?: HashSet<Pair<String, String>>().also { pairs ->
            for (song in Songs.list(db)) {
                val titles = linkedSetOf(MuseScore.titleKey(song.title), MuseScore.titleKey(Normalize.romanize(song.title)))
                titles.remove("")
                for (name in LinkedHashSet(song.artists.ifEmpty { listOf(song.artist) })) {
                    for (f in Normalize.nameForms(name)) for (t in titles) pairs.add(Normalize.compact(f) to t)
                }
            }
            mine.pairs = pairs
        }
        return forms.any { (Normalize.compact(it) to titleKey) in pairs }
    }

    /** Your songs' (artist form, title key) pairs, read once a search, when [knownSong] first needs them. */
    class Mine {
        var pairs: Set<Pair<String, String>>? = null
    }

    /** Python's `f"{n:,}"`: an integer's digits in threes, by commas. */
    fun grouped(n: Int): String {
        val digits = kotlin.math.abs(n.toLong()).toString()
        val out = StringBuilder()
        digits.forEachIndexed { i, c ->
            if (i > 0 && (digits.length - i) % 3 == 0) out.append(',')
            out.append(c)
        }
        return (if (n < 0) "-" else "") + out
    }
}
