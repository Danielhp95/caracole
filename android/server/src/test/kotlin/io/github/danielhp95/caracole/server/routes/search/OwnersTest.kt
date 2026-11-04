package io.github.danielhp95.caracole.server.routes.search

import io.github.danielhp95.caracole.core.testing.Misses
import io.github.danielhp95.caracole.server.testing.replays.WebReplay
import org.junit.Test

/**
 * A site's row names the song of yours it is (search_routes._owners, _Mine) as caracole serve names it: by an accepted
 * or pinned match (a cover, whose row is another artist's: `same_artist` false), by identity key, or by the compact
 * forms of its names (UG's "Billy Joel" is your "BillyJoel"), on every site's rows (Ultimate Guitar's, gtptabs.com's,
 * harptabs.com's, gametabs.net's, LaCuerda's) and every artist's most tabbed; a harptabs.com tab by its title alone
 * names none. The search corpus's own fixtures hold no such songs, so WebReplay.SONGS adds them by SQL; its ANSWERS
 * are caracole serve's over the same rows (WebApp.handle, its answer masked as the vectors are, then
 * WebReplay.ownersOf), which WebReplay.owners replays, on the device too.
 */
class OwnersTest {
    @Test
    fun every_sites_row_names_its_song_of_yours_and_whether_its_artist_is_yours() =
        Misses("the owners' answers").also { WebReplay.owners(it) }.assertNone()
}
