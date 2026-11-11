package io.github.danielhp95.caracole.core.inbox

import io.github.danielhp95.caracole.core.fuzz.Fuzz
import io.github.danielhp95.caracole.core.keys.Normalize

/**
 * music.Names: an artist's and a title's forms, as a download meets a song (inbox.py's `_match`, the phone's one
 * reader of it; the computer's Music/ folder is none of the phone's): slugs, plus pinyin slugs for Chinese names, and
 * each part of a name tagged in two scripts (Normalize.nameForms). The artist's are words, hyphens as spaces, for
 * token_set_ratio. Scores are rapidfuzz's (core.fuzz), 0 to 100.
 */
class MusicNames(val artists: List<String>, val titles: List<String>) {
    /** Names.title_score: how alike the titles are, the best of every pair of forms; 0 for none. */
    fun titleScore(other: MusicNames): Double {
        var best = 0.0
        var any = false
        for (x in titles) for (y in other.titles) {
            val score = Fuzz.ratio(x, y)
            if (!any || score > best) best = score
            any = true
        }
        return best
    }

    /** Names.artist_score: how alike the artists are, compared as words and whole; 0 for none. */
    fun artistScore(other: MusicNames): Double {
        var best = 0.0
        var any = false
        for (x in artists) for (y in other.artists) {
            val ratio = Fuzz.ratio(x, y)
            val words = Fuzz.tokenSetRatio(x, y)
            val score = if (words > ratio) words else ratio  // Python's max(a, b): the first of equals
            if (!any || score > best) best = score
            any = true
        }
        return best
    }

    /** Names.score: the lower of the artist and title scores; a title too far off for any decision (below
     * [CUTOFF] less [MARGIN]) is the score, the artists not compared. */
    fun score(other: MusicNames): Double {
        val title = titleScore(other)
        if (title < CUTOFF - MARGIN) return title
        val artist = artistScore(other)
        return if (title < artist) title else artist  // Python's min(artist, title): the first of equals
    }

    companion object {
        /** music.MATCH_CUTOFF. */
        const val CUTOFF = 90

        /** music.MATCH_MARGIN. */
        const val MARGIN = 8

        /** Names.of: [artist]'s forms, hyphens as spaces, and the forms of [title] cleaned (Normalize.cleanTitle). */
        fun of(artist: String, title: String): MusicNames = MusicNames(
            Normalize.nameForms(artist).map { it.replace("-", " ") },
            Normalize.nameForms(Normalize.cleanTitle(title)),
        )
    }
}
