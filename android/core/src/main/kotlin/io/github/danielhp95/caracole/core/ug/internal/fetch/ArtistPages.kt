package io.github.danielhp95.caracole.core.ug.internal.fetch

import io.github.danielhp95.caracole.core.db.Db
import io.github.danielhp95.caracole.core.library.Overrides
import io.github.danielhp95.caracole.core.library.SongRow
import io.github.danielhp95.caracole.core.ug.IndexTab

/**
 * The artist-page route (A6), the seam [SongFetch.processSong] calls: lane ug-fetch-artist's, which follows this
 * lane on internal/fetch/ (ug/fetch.py's `_artist_page_route`, `_artist_page_versions`, `artist_is_known`). Until it
 * lands, the phone reads no artist page: a song the index can't place stays as it is, with no request and no write,
 * and a song whose versions come from its artist's page fetches the versions it has.
 */
internal object ArtistPages {
    /** `_artist_page_route`: a not-found song looked up on its artist's UG page; true when it was found and accepted
     * there ([SongRun.song] then its match). Neutral: not found, nothing written. */
    fun route(run: SongRun): Boolean = false

    /** `_artist_page_versions`: a matched song's entries in its artist's UG lists of [kinds] read as its versions,
     * [own] its index tabs to learn the page from; false when this run's page cap cut a list short. Neutral: read as
     * far as it goes, nothing written. */
    fun versions(run: SongRun, kinds: List<String>, own: List<IndexTab> = emptyList()): Boolean = true

    /** `artist_is_known`: whether the song's artist page can be found. Neutral: never. */
    fun artistIsKnown(db: Db, song: SongRow, overrides: Overrides): Boolean = false
}
