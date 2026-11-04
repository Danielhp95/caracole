package io.github.danielhp95.caracole.core.lyrics

import io.github.danielhp95.caracole.core.http.AzLyricsParseError
import io.github.danielhp95.caracole.core.http.ProviderBlocked
import io.github.danielhp95.caracole.core.http.Response
import io.github.danielhp95.caracole.core.library.Overrides
import io.github.danielhp95.caracole.core.testing.FakeTransport.Companion.answer
import io.github.danielhp95.caracole.core.testing.Misses
import io.github.danielhp95.caracole.core.testing.replays.LyricsReplay
import kotlinx.serialization.json.jsonPrimitive
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import java.io.File
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith
import kotlin.test.assertFalse
import kotlin.test.assertNull
import kotlin.test.assertTrue

/** azlyrics.py and azlyrics_fetch.py on the phone: vectors/sites/azlyrics.jsonl and lookup/azlyrics.jsonl, and a few
 * cases by hand. */
class AzLyricsTest {
    @get:Rule val tmp = TemporaryFolder()

    @Test fun itsPagesReadAsAzLyricsPyReadsThem() {
        val misses = Misses("lyrics: ${LyricsReplay.AZLYRICS_SITES}")
        LyricsReplay.azlyricsSites(misses)
        misses.assertNone()
    }

    @Test fun aLookupsPassAsksDecidesAndWritesAsAzLyricsFetchPyDoes() {
        val misses = Misses("lyrics: ${LyricsReplay.AZLYRICS_LOOKUP}")
        LyricsReplay.azlyricsLookups(misses)
        misses.assertNone()
    }

    @Test fun anArtistsPageIsTheirNameInLettersAndDigitsUnderItsFirst() {
        assertEquals("https://www.azlyrics.com/b/beatles.html", AzLyrics.artistUrl("The Beatles"))
        assertEquals("https://www.azlyrics.com/19/50cent.html", AzLyrics.artistUrl("50 Cent"))
        assertEquals("https://www.azlyrics.com/b/bjork.html", AzLyrics.artistUrl("Björk"))
        assertNull(AzLyrics.artistUrl("宋冬野"))
    }

    private fun page(path: String) =
        Response("https://www.azlyrics.com/x.html", 200, File(System.getProperty("caracole.fixtures"), path).readBytes(), emptyMap())

    @Test fun pommesPageGivesTheSongsItLinksAndTheLyricsTheirLines() {
        val pomme = AzLyrics.parseArtist(page("azlyrics/artist_pomme.html"))
        assertEquals("Pomme", pomme.name)
        assertEquals("https://www.azlyrics.com/lyrics/pomme/mononoke.html", AzLyrics.pickSong(pomme, "Pomme", "Mononoke")?.url)
        assertNull(AzLyrics.pickSong(pomme, "Pomme", "Ma Meilleure Ennemie"))
        val text = AzLyrics.parseLyrics(page("azlyrics/lyrics_mononoke.html"))
        assertTrue(text.startsWith("[Couplet 1]\nDes mots inventés pour ce test\nRien & personne"), text)
        assertFailsWith<AzLyricsParseError> { AzLyrics.parseArtist(page("azlyrics/not_found.html")) }
    }

    @Test fun itsBlockPageIsABlockNeverKeptAndASongWaits() {
        LyricsWorld(tmp.newFolder()).use { w ->
            val song = w.song("Pomme", "mononoke", null, "lyrics_status" to "missing")
            val (client, _) = w.client("azlyrics", mapOf(
                "GET https://www.azlyrics.com/p/pomme.html" to answer(200, LyricsWorld.fixture("azlyrics/block.html"))))
            assertFailsWith<ProviderBlocked> {
                w.db { AzLyrics.azlyricsLyrics(it, client, w.library, w.now, Overrides(), setOf(song.id)) }
            }
            assertFalse(client.hasCached("https://www.azlyrics.com/p/pomme.html"))
            assertNull(w.db { it.kvGet("${AzLyrics.CHECKED}${song.id}") })
        }
    }

    @Test fun theVectorsHoldEveryParser() {
        val fns = LyricsReplay.records(LyricsReplay.AZLYRICS_SITES).map { it.getValue("fn").jsonPrimitive.content }.toSet()
        assertEquals(setOf("caracole.azlyrics.artist_url", "caracole.azlyrics.parse_artist", "caracole.azlyrics.parse_lyrics",
                           "caracole.azlyrics.pick_song"), fns)
        assertTrue(LyricsReplay.records(LyricsReplay.AZLYRICS_LOOKUP).size >= 15)
    }
}
