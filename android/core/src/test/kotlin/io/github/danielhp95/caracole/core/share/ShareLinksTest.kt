package io.github.danielhp95.caracole.core.share

import io.github.danielhp95.caracole.core.http.Response
import io.github.danielhp95.caracole.core.names.SongNames
import io.github.danielhp95.caracole.core.share.ShareLinks.Read
import io.github.danielhp95.caracole.core.testing.Corpus
import org.junit.Test
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith
import kotlin.test.assertNull

/**
 * What a shared link of Apple Music, Spotify, TIDAL, YouTube or YouTube Music is, read with no request, and what its
 * service's answer says of it, read from the answers each gave caracole's own user agent on 2026-11-10, trimmed
 * (tests/fixtures/itunes/, spotify/, tidal/, youtube/): the song named, or what the link is when it names none.
 */
class ShareLinksTest {
    private fun fixture(path: String): ByteArray = Corpus.fixture(path)

    /** A [ShareLinks.Get] that answers each URL from [answers] (status, headers, body), and records what it was
     * asked. */
    private class Answers(val answers: Map<String, Triple<Int, Map<String, String>, ByteArray>>) : ShareLinks.Get {
        val asked = ArrayList<Pair<String, Set<Int>>>()

        override fun get(url: String, accept: Set<Int>): Response {
            asked += url to accept
            val (status, headers, body) = answers[url] ?: throw AssertionError("not asked for: $url")
            return Response(url, status, body, headers)
        }
    }

    private fun page(status: Int, body: ByteArray, headers: Map<String, String> = emptyMap()) = Triple(status, headers, body)

    private val apple = ShareLinks.APPLE
    private val spotify = ShareLinks.SPOTIFY
    private val tidal = ShareLinks.TIDAL
    private val youtube = ShareLinks.YOUTUBE

    private val oembed = "https://www.youtube.com/oembed?url=https%3A%2F%2Fwww.youtube.com%2Fwatch%3Fv%3DfJ9rUzIMcZQ&format=json"

    @Test fun `each service's song links are asked at the one URL their id names`() {
        val songs = mapOf(
            "https://music.apple.com/us/album/love-me-do/1440833098?i=1440833334" to
                ShareLinks.Song(apple, "", "https://itunes.apple.com/lookup?id=1440833334&country=us", "1440833334", "us"),
            "https://music.apple.com/gb/song/love-me-do/1440833334" to
                ShareLinks.Song(apple, "", "https://itunes.apple.com/lookup?id=1440833334&country=gb", "1440833334", "gb"),
            "https://itunes.apple.com/us/album/1/id1440833098?i=1440833334&uo=4" to
                ShareLinks.Song(apple, "", "https://itunes.apple.com/lookup?id=1440833334&country=us", "1440833334", "us"),
            "https://music.apple.com/album/love-me-do/1440833098?i=1440833334" to
                ShareLinks.Song(apple, "", "https://itunes.apple.com/lookup?id=1440833334", "1440833334"),
            "https://open.spotify.com/track/4u7EnebtmKWzUH433cf5Qv?si=0f3c1c4d5e6f4a7b" to
                ShareLinks.Song(spotify, "", "https://open.spotify.com/track/4u7EnebtmKWzUH433cf5Qv", "4u7EnebtmKWzUH433cf5Qv"),
            "https://open.spotify.com/intl-de/track/3RkrwOau4TphkM84H6ELPi" to
                ShareLinks.Song(spotify, "", "https://open.spotify.com/track/3RkrwOau4TphkM84H6ELPi", "3RkrwOau4TphkM84H6ELPi"),
            "https://tidal.com/track/196435445/u" to
                ShareLinks.Song(tidal, "", "https://tidal.com/track/196435445", "196435445"),
            "https://tidal.com/browse/track/196435445" to
                ShareLinks.Song(tidal, "", "https://tidal.com/track/196435445", "196435445"),
            "https://listen.tidal.com/album/196435440/track/196435445" to
                ShareLinks.Song(tidal, "", "https://tidal.com/track/196435445", "196435445"),
            "https://www.youtube.com/watch?v=fJ9rUzIMcZQ&list=PL1" to ShareLinks.Song(youtube, "", oembed, "fJ9rUzIMcZQ"),
            "https://youtu.be/fJ9rUzIMcZQ?si=x" to ShareLinks.Song(youtube, "", oembed, "fJ9rUzIMcZQ"),
            "https://m.youtube.com/shorts/fJ9rUzIMcZQ" to ShareLinks.Song(youtube, "", oembed, "fJ9rUzIMcZQ"),
            "https://music.youtube.com/watch?v=fJ9rUzIMcZQ&si=Qx1" to
                ShareLinks.Song(ShareLinks.YOUTUBE_MUSIC, "", oembed, "fJ9rUzIMcZQ"),
        )
        for ((link, want) in songs) assertEquals(want.copy(link = link), ShareLinks.of(link), link)
        assertEquals(ShareLinks.Short(spotify, "https://spotify.link/j7xk2xnhzDb"), ShareLinks.of("https://spotify.link/j7xk2xnhzDb"))
        assertEquals(ShareLinks.Short(tidal, "https://tidal.link/abc"), ShareLinks.of("https://tidal.link/abc"))
    }

    @Test fun `an album's, a playlist's or an artist's link names no song, said with no request`() {
        val none = mapOf(
            "https://music.apple.com/us/album/1/1440833098" to (apple to "an album"),
            "https://music.apple.com/us/artist/the-beatles/136975" to (apple to "an artist"),
            "https://music.apple.com/us/playlist/todays-hits/pl.f4d106fed2bd41149aaacabb233eb5eb" to (apple to "a playlist"),
            "https://open.spotify.com/album/1GbtB4zTqAsyfZEsm1RZfx?si=1" to (spotify to "an album"),
            "https://open.spotify.com/playlist/37i9dQZF1DXcBWIGoYBM5M" to (spotify to "a playlist"),
            "https://open.spotify.com/artist/1dfeR4HaWDbWqFHLkxsg1d" to (spotify to "an artist"),
            "https://open.spotify.com/episode/4rOoJ6Egrf8K2IrywzwOMk" to (spotify to "a podcast's episode"),
            "https://tidal.com/browse/album/196435440" to (tidal to "an album"),
            "https://tidal.com/playlist/0f1d2e3c-aaaa-bbbb-cccc-0123456789ab" to (tidal to "a playlist"),
            "https://www.youtube.com/playlist?list=PL1" to (youtube to "a playlist"),
            "https://www.youtube.com/@Queen" to (youtube to "a channel"),
            "https://music.youtube.com/browse/MPREb_9nqEki4ZDpp" to (ShareLinks.YOUTUBE_MUSIC to "an album or an artist's page"),
        )
        for ((link, want) in none) {
            val linked = ShareLinks.of(link)
            assertEquals(ShareLinks.NoSong(want.first, link, want.second), linked, link)
            val asked = Answers(emptyMap())
            assertEquals(Read.NoSong(want.first, "a link to ${want.second}"), ShareLinks.answer(linked!!, asked))
            assertEquals(emptyList(), asked.asked, "no request")
        }
    }

    @Test fun `a link of no service caracole asks is none of these`() {
        for (link in listOf("https://link.deezer.com/s/34URX4HSZ3LKo4ZRnW3Sm", "https://music.example.org/share/abc123XY",
                            "https://www.shazam.com/track/132815415/mad-gone", "ftp://open.spotify.com/track/x", "not a link")) {
            assertNull(ShareLinks.of(link), link)
        }
    }

    @Test fun `Apple's catalogue names the track it was asked, or says it has none`() {
        val linked = ShareLinks.of("https://music.apple.com/us/album/love-me-do/1440833098?i=1440833334")!!
        val ask = "https://itunes.apple.com/lookup?id=1440833334&country=us"
        val asked = Answers(mapOf(ask to page(200, fixture("itunes/lookup-song.json"))))
        assertEquals(Read.Named(apple, "The Beatles", "Love Me Do"), ShareLinks.answer(linked, asked))
        assertEquals(listOf(ask to setOf(200)), asked.asked)
        assertEquals(Read.NoSong(apple, "Apple Music's catalogue has no song 1440833334 in its US store"),
                     ShareLinks.answer(linked, Answers(mapOf(ask to page(200, fixture("itunes/lookup-none.json"))))))
        // An album's id where a song's should be: Apple answers the album, which is no song.
        val album = ShareLinks.of("https://music.apple.com/us/song/1/1440833098")!!
        assertEquals(Read.NoSong(apple, "Apple Music's catalogue says 1440833098 is no song"), ShareLinks.answer(album, Answers(
            mapOf("https://itunes.apple.com/lookup?id=1440833098&country=us" to page(200, fixture("itunes/lookup-album.json"))))))
        assertFailsWith<ShareParseError> {
            ShareLinks.answer(linked, Answers(mapOf(ask to page(200, "<html>busy</html>".toByteArray()))))
        }
    }

    @Test fun `Spotify's page names the artist to caracole's user agent, by its meta tags or its title`() {
        val linked = ShareLinks.of("https://open.spotify.com/track/4u7EnebtmKWzUH433cf5Qv?si=1")!!
        val ask = "https://open.spotify.com/track/4u7EnebtmKWzUH433cf5Qv"
        val html = fixture("spotify/track.html")
        assertEquals(Read.Named(spotify, "Queen", "Bohemian Rhapsody - Remastered 2011"),
                     ShareLinks.answer(linked, Answers(mapOf(ask to page(200, html)))))
        // A page with its title alone ("… - song and lyrics by … | Spotify"), its meta tags gone.
        val titled = html.toString(Charsets.UTF_8).lines().filter { "<meta property=\"og:title\"" !in it && "musician" !in it }
            .joinToString("\n").toByteArray()
        assertEquals(Read.Named(spotify, "Queen", "Bohemian Rhapsody - Remastered 2011"),
                     ShareLinks.answer(linked, Answers(mapOf(ask to page(200, titled)))))
        assertEquals(Read.NoSong(spotify, "Spotify has no track at this link"),
                     ShareLinks.answer(linked, Answers(mapOf(ask to page(404, "<html>Page not found</html>".toByteArray())))))
        assertFailsWith<ShareParseError> {  // a page that names nothing is an error, never "no song"
            ShareLinks.answer(linked, Answers(mapOf(ask to page(200, "<html><title>Spotify</title></html>".toByteArray()))))
        }
    }

    @Test fun `a short link's one hop names the track, by its redirect or its page`() {
        val short = ShareLinks.of("https://spotify.link/j7xk2xnhzDb")!!
        val track = "https://open.spotify.com/track/4u7EnebtmKWzUH433cf5Qv"
        val html = fixture("spotify/track.html")
        val redirect = Answers(mapOf(
            short.link to page(307, ByteArray(0), mapOf("location" to "$track?si=a1&_branch_match_id=9")),
            track to page(200, html),
        ))
        assertEquals(Read.Named(spotify, "Queen", "Bohemian Rhapsody - Remastered 2011"), ShareLinks.answer(short, redirect))
        assertEquals(listOf(short.link to ShareLinks.SHORT_ACCEPT, track to setOf(200, 404)), redirect.asked)
        val interstitial = Answers(mapOf(
            short.link to page(200, "<html><a href=\"$track?si=b2\">Open in your browser</a></html>".toByteArray()),
            track to page(200, html),
        ))
        assertEquals(Read.Named(spotify, "Queen", "Bohemian Rhapsody - Remastered 2011"), ShareLinks.answer(short, interstitial))
        // spotify.link's own answer, live, for a code it doesn't know.
        assertEquals(Read.NoSong(spotify, "spotify.link knows no such link"),
                     ShareLinks.answer(short, Answers(mapOf(short.link to page(404, fixture("spotify/link-404.html"))))))
        assertEquals(Read.NoSong(spotify, "a link to an album"), ShareLinks.answer(short, Answers(mapOf(
            short.link to page(302, ByteArray(0), mapOf("location" to "https://open.spotify.com/album/1GbtB4zTqAsyfZEsm1RZfx")))),
        ))
        val elsewhere = Answers(mapOf(short.link to page(302, ByteArray(0), mapOf("location" to "https://example.com/x"))))
        assertEquals(Read.NoSong(spotify, "spotify.link's link goes to https://example.com/x, no song of Spotify's"),
                     ShareLinks.answer(short, elsewhere))
        assertEquals(1, elsewhere.asked.size, "nothing asked of another site")
    }

    @Test fun `TIDAL's page is split where its title and its og title agree`() {
        val linked = ShareLinks.of("https://tidal.com/browse/track/196435445")!!
        val asked = Answers(mapOf("https://tidal.com/track/196435445" to page(200, fixture("tidal/track.html"))))
        assertEquals(Read.Named(tidal, "Metallica", "Enter Sandman (Remastered 2021)"), ShareLinks.answer(linked, asked))
        // An artist whose name has a " - ", and a title with a " by ": the two agree on one cut alone.
        val both = "<html><head><title>Stand by Me by Ben E. King - Live on TIDAL</title>" +
            "<meta property=\"og:title\" content=\"Ben E. King - Live - Stand by Me\"></head></html>"
        assertEquals(Read.Named(tidal, "Ben E. King - Live", "Stand by Me"), ShareLinks.answer(linked, Answers(
            mapOf("https://tidal.com/track/196435445" to page(200, both.toByteArray())))))
    }

    @Test fun `YouTube's oEmbed gives the video's title and channel, which read_names reads as a pasted video's`() {
        val linked = ShareLinks.of("https://music.youtube.com/watch?v=fJ9rUzIMcZQ&si=Qx1")!!
        val read = ShareLinks.answer(linked, Answers(mapOf(oembed to page(200, fixture("youtube/oembed.json")))))
        assertEquals(Read.Named(ShareLinks.YOUTUBE_MUSIC, "Queen Official", "Queen – Bohemian Rhapsody (Official Video Remastered)",
                                video = true), read)
        read as Read.Named
        assertEquals("Queen" to "Bohemian Rhapsody", SongNames.readNames(null, read.title, emptyList(), channel = read.artist))
        assertEquals(Read.NoSong(ShareLinks.YOUTUBE_MUSIC, "YouTube has no such video"),
                     ShareLinks.answer(linked, Answers(mapOf(oembed to page(404, "Not Found".toByteArray())))))
    }
}
