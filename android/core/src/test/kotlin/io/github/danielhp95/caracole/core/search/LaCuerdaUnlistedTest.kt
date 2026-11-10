package io.github.danielhp95.caracole.core.search

import io.github.danielhp95.caracole.core.testing.TestDb
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import kotlin.test.assertEquals
import kotlin.test.assertNull

/**
 * search.lacuerda_unlisted's forms the search vectors don't reach (their every case is /api/search's, a query read
 * whole): `--artist NAME`'s, whose name is the query, and LaCuerda's own strong answer, a song as an artist, which
 * says there is nothing to offer. vectors/web/api_search*.jsonl hold the rest (the server's replays).
 */
class LaCuerdaUnlistedTest {
    @get:Rule val tmp = TemporaryFolder()

    private fun site(score: Double) = SiteHit("lacuerda", "Mariposa Tecknicolor", "https://acordes.lacuerda.net/x/y",
                                              score)

    private fun artist(score: Double) = SiteArtist("lacuerda", "Fito Paez", "fito_paez",
                                                   "https://acordes.lacuerda.net/fito_paez/", score)

    @Test fun `an artist asked for by name is that name, under the letter its page would be listed in`() {
        TestDb.fresh(tmp.root).use { database ->
            database.read { db ->
                // an empty index has read no letter: their page can tell
                assertEquals("Fito Páez" to "F", LaCuerdaUnlisted.of(db, "Fito Páez", artist = true))
            }
        }
    }

    @Test fun `once the listings are read whole the index can tell, and there is nothing to offer`() {
        TestDb.fresh(tmp.root).use { database ->
            database.writeBlocking { db -> db.kvSet("lacuerda:index:complete_at", "2026-10-21T00:00:00Z") }
            database.read { db -> assertNull(LaCuerdaUnlisted.of(db, "Fito Páez", artist = true)) }
        }
    }

    @Test fun `a strong answer of LaCuerda's own, a song or an artist, leaves nothing to offer`() {
        TestDb.fresh(tmp.root).use { database ->
            database.read { db ->
                val strong = SearchLimits.STRONG.toDouble()
                assertNull(LaCuerdaUnlisted.of(db, "fito paez", lacuerdaSongs = listOf(site(strong))))
                assertNull(LaCuerdaUnlisted.of(db, "fito paez", lacuerdaArtists = listOf(artist(strong))))
                assertNull(LaCuerdaUnlisted.of(db, "Fito Páez", lacuerdaSongs = listOf(site(strong)), artist = true))
                // a weak one says nothing: the query is the name
                assertEquals("fito paez" to "F",
                             LaCuerdaUnlisted.of(db, "fito paez", lacuerdaSongs = listOf(site(strong - 1))))
            }
        }
    }
}
