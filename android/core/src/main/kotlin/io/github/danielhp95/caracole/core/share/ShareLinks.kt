package io.github.danielhp95.caracole.core.share

import io.github.danielhp95.caracole.core.html.Html
import io.github.danielhp95.caracole.core.http.ProviderError
import io.github.danielhp95.caracole.core.http.Response
import io.github.danielhp95.caracole.core.http.UrlError
import io.github.danielhp95.caracole.core.http.Urls
import io.github.danielhp95.caracole.core.py.Py
import io.github.danielhp95.caracole.core.py.PyRegex
import io.github.danielhp95.caracole.core.py.PyUnicode
import io.github.danielhp95.caracole.core.py.PyUrl
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive

/**
 * A link shared to the phone whose text names no song, read by asking its service once: the owner's choice of
 * 2026-11-10 (AGENTS.md, Politeness: "A shared link read by asking its service once"). [of] reads what a link is with
 * no request; [answer] reads what the service answers it, through a [Get] (a client's get, or the cache alone); the
 * asking itself, its pace, budget, blocks and errors, is [ShareAsk]'s.
 *
 * - **Apple Music** (provider `itunes`): a song's link (`/{cc}/album/{slug}/{album}?i={id}`, `/{cc}/song/{slug}/{id}`,
 *   a music video's), asked of Apple's catalogue, `itunes.apple.com/lookup?id={id}&country={cc}`: its `artistName`
 *   and `trackName`. An album's link with no `?i=`, an artist's, a playlist's name no song, said with no request.
 * - **Spotify** (`spotify`): a track's link (`open.spotify.com/(intl-xx/)track/{id}`), asked as its page,
 *   `open.spotify.com/track/{id}`, which names the artist to caracole's own user agent (its `og:title` and
 *   `music:musician_description`, else its title, "{title} - song and lyrics by {artist} | Spotify"); a short link
 *   (`spotify.link`, `spotify.app.link`) first asked for the link it stands for, its redirect or its page's first
 *   link of Spotify's: one request more.
 * - **TIDAL** (`tidal`): a track's link (`tidal.com/(browse/)track/{id}`, `listen.tidal.com/…`), asked as its page,
 *   `tidal.com/track/{id}` (its title "{title} by {artist} on TIDAL", its `og:title` "{artist} - {title}"); a
 *   `tidal.link` short link as Spotify's.
 * - **YouTube** and **YouTube Music** (`youtube-oembed`, never yt-dlp's `youtube`): a video's link (`watch?v=`,
 *   `youtu.be`, `shorts`, `live`, `embed`, music.youtube.com's), asked of YouTube's oEmbed,
 *   `www.youtube.com/oembed?url=https://www.youtube.com/watch?v={id}&format=json`: its title and its channel, which
 *   read_names reads as it reads a pasted video's.
 *
 * Each asks the one URL its id names, whatever the link's own shape (a TIDAL link's `/browse/` form would cost a
 * redirect more). An answer that won't parse is a [ShareParseError], a provider's error: never a miss, never "this
 * link names no song".
 */
object ShareLinks {
    /** A service a shared link of its own is read from: its [provider], its [name] as the page says it, and the
     * [source] its names are read from ("Read from Spotify's page: …"). */
    data class Service(val provider: String, val name: String, val source: String)

    val APPLE = Service("itunes", "Apple Music", "Apple Music's catalogue")
    val SPOTIFY = Service("spotify", "Spotify", "Spotify's page")
    val TIDAL = Service("tidal", "TIDAL", "TIDAL's page")
    val YOUTUBE = Service("youtube-oembed", "YouTube", "the video's title on YouTube")
    val YOUTUBE_MUSIC = Service("youtube-oembed", "YouTube Music", "the video's title on YouTube Music")

    /** The providers a shared link is read from (config.SHARE_PROVIDERS). */
    val PROVIDERS: List<String> = listOf("itunes", "spotify", "tidal", "youtube-oembed")

    /** What a link of one of these services is, read with no request. */
    sealed interface Linked {
        val service: Service
        val link: String

        /** The requests reading it may send, at most. */
        val requests: Int
    }

    /** A song's link: [ask], the one URL whose answer names it ([id] its id there; [country], Apple's store). */
    data class Song(override val service: Service, override val link: String, val ask: String, val id: String,
                    val country: String? = null) : Linked {
        override val requests: Int get() = 1
    }

    /** A short link (spotify.link, tidal.link), asked for the link it stands for, then that link's answer. */
    data class Short(override val service: Service, override val link: String) : Linked {
        override val requests: Int get() = 2
    }

    /** A link to what is no song ([what]: "an album", "a playlist"…), said with no request. */
    data class NoSong(override val service: Service, override val link: String, val what: String) : Linked {
        override val requests: Int get() = 0
    }

    /** What a shared link's service said of it, or why it said nothing. */
    sealed interface Read {
        val service: Service

        /** The song named: its [artist] and [title] as the service writes them; for a video ([video]), [title] is its
         * title and [artist] its channel, for read_names to read. */
        data class Named(override val service: Service, val artist: String, val title: String,
                         val video: Boolean = false) : Read

        /** The link names no song: [why], what it is ("a link to an album") or what the service answered ("Spotify
         * has no track at this link"). */
        data class NoSong(override val service: Service, val why: String) : Read

        /** The service couldn't be asked, or didn't answer: [why], in one line. Never a miss. */
        data class NotRead(override val service: Service, val why: String) : Read
    }

    /** A GET of [url] accepting [accept]'s statuses: a client's, or the cache's alone. */
    fun interface Get {
        fun get(url: String, accept: Set<Int>): Response
    }

    /** The statuses a short link's answer is read in: its page, none (404), or its one hop. */
    val SHORT_ACCEPT: Set<Int> = setOf(200, 404, 301, 302, 303, 307, 308)

    /** The statuses each song's answer is read in: Apple's lookup always answers 200, the pages 404 for none. */
    fun accept(song: Song): Set<Int> = if (song.service.provider == "itunes") setOf(200) else setOf(200, 404)

    // --- what a link is ----------------------------------------------------------------------------------------

    private val SPOTIFY_HOSTS = setOf("open.spotify.com", "play.spotify.com")
    private val SPOTIFY_SHORT = setOf("spotify.link", "spotify.app.link")
    private val APPLE_HOSTS = setOf("music.apple.com", "itunes.apple.com", "geo.music.apple.com")
    private val TIDAL_HOSTS = setOf("tidal.com", "www.tidal.com", "listen.tidal.com")
    private val TIDAL_SHORT = setOf("tidal.link")
    private val YOUTUBE_HOSTS = setOf("youtube.com", "www.youtube.com", "m.youtube.com")
    private val YOUTUBE_MUSIC_HOSTS = setOf("music.youtube.com")
    private val YOUTU_BE = setOf("youtu.be")

    private val SPOTIFY_PATH = PyRegex.compile(
        "^/(?:intl-[a-z]{2}(?:-[A-Za-z]{2,4})?/)?(?:embed/)?(?P<kind>[a-z-]+)/(?P<id>[0-9A-Za-z]{22})/?$",
    )
    private val SPOTIFY_KINDS = mapOf("album" to "an album", "artist" to "an artist", "playlist" to "a playlist",
                                      "episode" to "a podcast's episode", "show" to "a podcast", "user" to "a profile")

    private val APPLE_PATH = PyRegex.compile(
        "^/(?:(?P<cc>[a-z]{2})/)?(?P<kind>album|song|music-video|artist|playlist|station|curator|radio)" +
            "(?:/[^/]+)?/(?:id)?(?P<id>[0-9]+|pl\\.[0-9A-Za-z.-]+|ra\\.[0-9A-Za-z.-]+)/?$",
    )
    private val APPLE_KINDS = mapOf("album" to "an album", "artist" to "an artist", "playlist" to "a playlist",
                                    "station" to "a radio station", "radio" to "a radio station",
                                    "curator" to "a curator's page")

    private val TIDAL_TRACK = PyRegex.compile("^/(?:browse/)?(?:album/[0-9]+/)?track/(?P<id>[0-9]+)(?:/[^/]*)?/?$")
    private val TIDAL_OTHER = PyRegex.compile("^/(?:browse/)?(?P<kind>album|artist|playlist|mix|video)/")
    private val TIDAL_KINDS = mapOf("album" to "an album", "artist" to "an artist", "playlist" to "a playlist",
                                    "mix" to "a mix", "video" to "a video")

    private val VIDEO_ID = PyRegex.compile("^[0-9A-Za-z_-]{11}$")
    private val YOUTUBE_PATH = PyRegex.compile("^/(?:shorts|live|embed|v)/(?P<id>[0-9A-Za-z_-]{11})/?$")
    private val YOUTUBE_CHANNEL = PyRegex.compile("^/(?:channel/|c/|user/|@)")

    /** What [link] is, with no request: a song's link of one of the services, a short link, a link to what is no
     * song; null for a link of none of them (Deezer's, a Navidrome server's, any other site's). */
    fun of(link: String): Linked? {
        val split = try {
            PyUrl.urlsplit(link)
        } catch (e: PyUrl.Invalid) {
            return null
        }
        if (Py.asciiLower(split.scheme) !in setOf("http", "https")) return null
        val host = PyUnicode.lower(split.netloc.substringAfterLast('@').substringBefore(':'))
        val path = split.path
        val query = try {
            PyUrl.parseQs(split.query)
        } catch (e: PyUrl.Invalid) {
            LinkedHashMap()
        }
        return when (host) {
            in SPOTIFY_HOSTS -> spotify(link, path)
            in SPOTIFY_SHORT -> Short(SPOTIFY, link)
            in APPLE_HOSTS -> apple(link, path, query)
            in TIDAL_HOSTS -> tidal(link, path)
            in TIDAL_SHORT -> Short(TIDAL, link)
            in YOUTUBE_HOSTS -> youtube(YOUTUBE, link, path, query)
            in YOUTUBE_MUSIC_HOSTS -> youtube(YOUTUBE_MUSIC, link, path, query)
            in YOUTU_BE -> path.removePrefix("/").removeSuffix("/").let { id ->
                if (VIDEO_ID.matches(id)) video(YOUTUBE, link, id) else NoSong(YOUTUBE, link, "a page of YouTube's")
            }
            else -> null
        }
    }

    private fun spotify(link: String, path: String): Linked {
        val m = SPOTIFY_PATH.find(path) ?: return NoSong(SPOTIFY, link, "a page of Spotify's")
        val kind = m.groups["kind"]!!.value
        val id = m.groups["id"]!!.value
        if (kind == "track") return Song(SPOTIFY, link, "https://open.spotify.com/track/$id", id)
        return NoSong(SPOTIFY, link, SPOTIFY_KINDS[kind] ?: "a page of Spotify's")
    }

    private fun apple(link: String, path: String, query: Map<String, List<String>>): Linked {
        val m = APPLE_PATH.find(path) ?: return NoSong(APPLE, link, "a page of Apple Music's")
        val kind = m.groups["kind"]!!.value
        val cc = m.groups["cc"]?.value
        val song = when (kind) {
            "album" -> query["i"]?.firstOrNull()?.takeIf { it.isNotEmpty() && it.all { c -> c in '0'..'9' } }
            "song", "music-video" -> m.groups["id"]!!.value.takeIf { it.all { c -> c in '0'..'9' } }
            else -> null
        } ?: return NoSong(APPLE, link, APPLE_KINDS[kind] ?: "a page of Apple Music's")
        val ask = "https://itunes.apple.com/lookup?id=$song" + if (cc != null) "&country=$cc" else ""
        return Song(APPLE, link, ask, song, cc)
    }

    private fun tidal(link: String, path: String): Linked {
        TIDAL_TRACK.find(path)?.let { m ->
            val id = m.groups["id"]!!.value
            return Song(TIDAL, link, "https://tidal.com/track/$id", id)
        }
        val kind = TIDAL_OTHER.find(path)?.groups?.get("kind")?.value
        return NoSong(TIDAL, link, kind?.let { TIDAL_KINDS[it] } ?: "a page of TIDAL's")
    }

    private fun youtube(service: Service, link: String, path: String, query: Map<String, List<String>>): Linked {
        val asked = query["v"]?.firstOrNull()
        if (path.removeSuffix("/") == "/watch" && asked != null && VIDEO_ID.matches(asked)) return video(service, link, asked)
        YOUTUBE_PATH.find(path)?.let { return video(service, link, it.groups["id"]!!.value) }
        return NoSong(service, link, when {
            path.removeSuffix("/") == "/playlist" -> "a playlist"
            path.startsWith("/browse/") -> "an album or an artist's page"
            YOUTUBE_CHANNEL.find(path) != null -> "a channel"
            else -> "a page of ${service.name}'s"
        })
    }

    private fun video(service: Service, link: String, id: String): Song {
        val ask = Urls.withParams("https://www.youtube.com/oembed",
                                  listOf("url" to "https://www.youtube.com/watch?v=$id", "format" to "json"))
        return Song(service, link, ask, id)
    }

    // --- what the service answered ------------------------------------------------------------------------------

    /** What [linked]'s service says of it, asked through [get]: a short link's link first, then the song's answer. */
    fun answer(linked: Linked, get: Get): Read = when (linked) {
        is NoSong -> Read.NoSong(linked.service, "a link to ${linked.what}")
        is Song -> song(linked, get.get(linked.ask, accept(linked)))
        is Short -> short(linked, get)
    }

    private fun short(linked: Short, get: Get): Read {
        val resp = get.get(linked.link, SHORT_ACCEPT)
        if (resp.status == 404) return Read.NoSong(linked.service, "${host(linked.link)} knows no such link")
        val to = shortTarget(linked, resp)
        val elsewhere = "${host(linked.link)}'s link goes to $to, no song of ${linked.service.name}'s"
        return when (val target = of(to)) {
            is Song -> if (target.service.provider == linked.service.provider) {
                song(target, get.get(target.ask, accept(target)))
            } else {
                Read.NoSong(linked.service, elsewhere)
            }
            is NoSong -> if (target.service.provider == linked.service.provider) {
                Read.NoSong(linked.service, "a link to ${target.what}")
            } else {
                Read.NoSong(linked.service, elsewhere)
            }
            is Short -> throw ShareParseError(linked.service.provider, linked.link, "a short link to another short link: $to")
            null -> Read.NoSong(linked.service, elsewhere)
        }
    }

    /** The address a short link's answer stands for: its redirect's Location, else its page's first link of the
     * service's (a page that names none won't parse). spotify.link answered caracole a 404 page for a code it doesn't
     * know (tests/fixtures/spotify/link-404.html); a known code's answer, a redirect or Branch's page with the link in
     * it, is read either way. */
    private fun shortTarget(short: Short, resp: Response): String {
        val location = resp.headers["location"]
        val target = if (resp.status != 200 && location != null) {
            try {
                Urls.resolve(short.link, location)
            } catch (e: UrlError) {
                throw ShareParseError(short.service.provider, short.link, "a redirect to no address: $location")
            }
        } else {
            val pattern = if (short.service.provider == "spotify") SPOTIFY_IN_PAGE else TIDAL_IN_PAGE
            pattern.find(resp.text.replace("\\/", "/"))?.value  // a script's JSON writes its slashes escaped
                ?: throw ShareParseError(short.service.provider, short.link, "its page names no link of ${short.service.name}'s")
        }
        return target
    }

    private val SPOTIFY_IN_PAGE = PyRegex.compile("https://open\\.spotify\\.com/(?:intl-[a-z-]+/)?(?:track|album|artist|playlist|episode|show)/[0-9A-Za-z]{22}")
    private val TIDAL_IN_PAGE = PyRegex.compile("https://(?:www\\.|listen\\.)?tidal\\.com/(?:browse/)?(?:album/[0-9]+/)?(?:track|album|artist|playlist|mix|video)/[0-9A-Za-z-]+")

    private fun song(song: Song, resp: Response): Read = when (song.service.provider) {
        "itunes" -> apple(song, resp)
        "spotify" -> if (resp.status == 404) Read.NoSong(song.service, "Spotify has no track at this link") else spotify(song, resp)
        "tidal" -> if (resp.status == 404) Read.NoSong(song.service, "TIDAL has no track at this link") else tidal(song, resp)
        else -> if (resp.status == 404) Read.NoSong(song.service, "YouTube has no such video") else oembed(song, resp)
    }

    /** Apple's lookup: the track of the id asked, its artist and its name; none, or no track, names no song. */
    private fun apple(song: Song, resp: Response): Read {
        val doc = try {
            resp.json()
        } catch (e: IllegalArgumentException) {
            throw ShareParseError(song.service.provider, resp.url, "unreadable answer: ${e.message}")
        }
        val results = ((doc as? JsonObject)?.get("results") as? JsonArray)
            ?: throw ShareParseError(song.service.provider, resp.url, "an answer with no results")
        val found = results.filterIsInstance<JsonObject>()
        val track = found.firstOrNull { it.text("wrapperType") == "track" && it.number("trackId") == song.id }
        if (track != null) {
            val artist = track.text("artistName")
            val title = track.text("trackName")
            if (artist.isNullOrEmpty() || title.isNullOrEmpty()) {
                throw ShareParseError(song.service.provider, resp.url, "a track with no artist or no name")
            }
            return Read.Named(song.service, artist, title)
        }
        val store = song.country?.let { cc -> " in its ${cc.map { if (it in 'a'..'z') it - 32 else it }.joinToString("")} store" }
            .orEmpty()
        if (found.isEmpty()) return Read.NoSong(song.service, "Apple Music's catalogue has no song ${song.id}$store")
        return Read.NoSong(song.service, "Apple Music's catalogue says ${song.id} is no song")
    }

    /** A Spotify track's page: its `og:title` and first `music:musician_description`, else its title's words. */
    private fun spotify(song: Song, resp: Response): Read {
        val doc = Html.parse(resp.content)
        val title = meta(doc, "og:title")
        val artist = meta(doc, "music:musician_description")
        if (!title.isNullOrEmpty() && !artist.isNullOrEmpty()) return Read.Named(song.service, artist, title)
        val words = doc.cssFirst("title")?.text()?.let { Py.strip(it) }.orEmpty()
        val m = SPOTIFY_TITLE.matchEntire(words)
            ?: throw ShareParseError(song.service.provider, resp.url, "a page that names no song")
        return Read.Named(song.service, Py.strip(m.groups["artist"]!!.value), Py.strip(m.groups["title"]!!.value))
    }

    private val SPOTIFY_TITLE = PyRegex.compile("(?s)^(?P<title>.+) - song(?: and lyrics)? by (?P<artist>.+?) \\| Spotify$")

    /** A TIDAL track's page: its title, "{title} by {artist} on TIDAL", split where its `og:title`, "{artist} -
     * {title}", agrees; else the title's last " by ", else the `og:title`'s first " - ". */
    private fun tidal(song: Song, resp: Response): Read {
        val doc = Html.parse(resp.content)
        val title = doc.cssFirst("title")?.text()?.let { Py.strip(it) }?.let { TIDAL_TITLE.matchEntire(it)?.groups?.get(1)?.value }
        val og = meta(doc, "og:title")
        if (title != null && og != null) {
            var at = og.indexOf(" - ")
            while (at > 0) {
                val artist = og.substring(0, at)
                val name = og.substring(at + 3)
                if (title == "$name by $artist" && name.isNotEmpty()) return Read.Named(song.service, artist, name)
                at = og.indexOf(" - ", at + 1)
            }
        }
        if (title != null) {
            val by = title.lastIndexOf(" by ")
            if (by > 0 && by + 4 < title.length) return Read.Named(song.service, title.substring(by + 4), title.substring(0, by))
        }
        if (og != null) {
            val dash = og.indexOf(" - ")
            if (dash > 0 && dash + 3 < og.length) return Read.Named(song.service, og.substring(0, dash), og.substring(dash + 3))
        }
        throw ShareParseError(song.service.provider, resp.url, "a page that names no song")
    }

    private val TIDAL_TITLE = PyRegex.compile("(?s)^(.+) on TIDAL$")

    /** YouTube's oEmbed: the video's title and its channel. */
    private fun oembed(song: Song, resp: Response): Read {
        val doc = try {
            resp.json()
        } catch (e: IllegalArgumentException) {
            throw ShareParseError(song.service.provider, resp.url, "unreadable answer: ${e.message}")
        }
        val o = doc as? JsonObject ?: throw ShareParseError(song.service.provider, resp.url, "an answer that isn't an object")
        val title = o.text("title")?.let { Py.strip(it) }
        if (title.isNullOrEmpty()) throw ShareParseError(song.service.provider, resp.url, "a video with no title")
        return Read.Named(song.service, Py.strip(o.text("author_name").orEmpty()), title, video = true)
    }

    /** A `<meta>`'s content by its `property` (Open Graph's) or its `name` (Spotify writes music:* so), stripped;
     * null for none or an empty one. */
    private fun meta(doc: io.github.danielhp95.caracole.core.html.HtmlDoc, key: String): String? =
        doc.css("meta[property=\"$key\"], meta[name=\"$key\"]").firstNotNullOfOrNull { node ->
            node.attr("content")?.let { Py.strip(it) }?.takeIf { it.isNotEmpty() }
        }

    private fun host(link: String): String = try {
        PyUnicode.lower(PyUrl.urlsplit(link).netloc)
    } catch (e: PyUrl.Invalid) {
        link
    }

    private fun JsonObject.text(key: String): String? = (this[key] as? JsonPrimitive)?.takeIf { it.isString }?.content

    /** A JSON number's literal, an id compared as its digits. */
    private fun JsonObject.number(key: String): String? = (this[key] as? JsonPrimitive)?.takeIf { !it.isString }?.content
}

/** A shared link's service answered what caracole can't read: a provider's error, never a miss. */
class ShareParseError(provider: String, url: String? = null, message: String) : ProviderError(provider, url, msg = message)
