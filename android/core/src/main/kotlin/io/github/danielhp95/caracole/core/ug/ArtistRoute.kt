package io.github.danielhp95.caracole.core.ug

import io.github.danielhp95.caracole.core.db.Db
import io.github.danielhp95.caracole.core.keys.Normalize
import io.github.danielhp95.caracole.core.library.Overrides
import io.github.danielhp95.caracole.core.library.SongRow
import io.github.danielhp95.caracole.core.ug.internal.fetch.ArtistPages

/**
 * ug/fetch.py's artist-page route (A6) as the rest of the phone reads it: a song the index can't place is looked up on
 * its artist's UG page by [UgFetch.processSong] (internal/fetch/ArtistPages.kt, the route itself), whose address comes
 * from `[artist_url]`, a learned one or a slugged tab of the artist; here, whether that page can be found
 * ([artistIsKnown], what a lookup's UG stages and the to-do words ask before they ask UG), and what is wrong with a
 * tab page you pasted under `[artist_url]` ([pastedPageProblem]).
 */
object ArtistRoute {
    /** ARTIST_PAGE_KINDS: the lists read, the sheet's first; UG's Guitar Pro lists are never read. */
    val ARTIST_PAGE_KINDS: List<String> = listOf("chords", "tabs")

    /** TITLE_MATCH: rapidfuzz's ratio of title keys a fuzzy title needs, the matcher's accept score. */
    const val TITLE_MATCH = 90

    /** TITLE_MARGIN: how far a fuzzy title must lead the next different title. */
    const val TITLE_MARGIN = 8

    /** LEARN_TRIES: slugged tabs read at most to learn an artist's page. */
    const val LEARN_TRIES = 3

    // What reading a tab page you pasted under [artist_url] can find instead of an artist page.
    const val PASTE_GONE = "UG answers 404 for it"
    const val PASTE_CLOSED = "robots.txt closes it to caracole"
    const val PASTE_NO_ARTIST = "it doesn't link to its artist's page"

    /** A tab page you pasted that won't parse, even fetched again: no verdict, asked for again on the tab-page rule's
     * dates. */
    const val PASTE_UNREADABLE = "UG's copy of it can't be read"

    /** `artist_keys`: the UG artist keys a song may be listed under: `[alias]` first, then each artist's own keys. */
    fun artistKeys(song: SongRow, overrides: Overrides): List<String> {
        val keys = ArrayList<String>()
        for (name in song.artists.ifEmpty { listOf(song.artist) }) {
            keys += overrides.alias[Normalize.slugKey(name)].orEmpty()
            keys += Normalize.nameForms(name)
        }
        return LinkedHashSet(keys).filter { it.isNotEmpty() }
    }

    /** `artist_is_known`: whether the song's artist page can be found: pasted under `[artist_url]` (a tab page there
     * counts until reading it shows it leads to no artist page), learned, or in the index. */
    fun artistIsKnown(db: Db, song: SongRow, overrides: Overrides): Boolean {
        val keys = artistKeys(song, overrides)
        if (overrides.artistUrlEntry(keys) != null && ArtistPages.failedPaste(db, keys, overrides) == null) return true
        return keys.any { !UgLookup.learnedArtistUrl(db, it).isNullOrEmpty() || UgLookup.artistKnown(db, it) }
    }

    /** `pasted_page_problem`: the tab page you pasted under `[artist_url]` for the song's artist and what is wrong with
     * it, when reading it gave no artist page ([PASTE_GONE], [PASTE_CLOSED], [PASTE_NO_ARTIST]) or it couldn't be
     * read ([PASTE_UNREADABLE], and when caracole asks for it again); else null. */
    fun pastedPageProblem(db: Db, song: SongRow, overrides: Overrides): Pair<String, String>? =
        ArtistPages.pasteProblem(db, artistKeys(song, overrides), overrides)
}
