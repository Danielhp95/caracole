package io.github.danielhp95.caracole.core.ug

import io.github.danielhp95.caracole.core.library.SongRow

/** What the artist-page route found for a song: its tabs of each kind (UG's bare-id tabs), or nothing. */
data class ArtistRouteFound(val tabs: List<UgVersion>, val requests: Int)

/**
 * ug/fetch.py's artist-page route (`artist_page`, A6): a song's chords found on its artist's UG page, the seam
 * [UgFetch.processSong] calls (lane ug-fetch-artist). Neutral: nothing found, no request sent.
 */
object ArtistRoute {
    fun find(ctx: FetchContext, song: SongRow): ArtistRouteFound? = null
}
