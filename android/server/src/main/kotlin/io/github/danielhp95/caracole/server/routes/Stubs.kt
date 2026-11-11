package io.github.danielhp95.caracole.server.routes

import io.github.danielhp95.caracole.core.py.PyUnicode
import io.github.danielhp95.caracole.core.py.PyText
import io.github.danielhp95.caracole.core.py.PyUrl
import io.github.danielhp95.caracole.server.http.Body
import io.github.danielhp95.caracole.server.http.GetAnswer
import io.github.danielhp95.caracole.server.http.PostAnswer
import io.github.danielhp95.caracole.server.http.Refused
import io.github.danielhp95.caracole.server.http.Response
import io.github.danielhp95.caracole.server.http.Route
import io.github.danielhp95.caracole.server.http.RouteModule
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive

/** What a route not on the phone yet answers: the message page, 409, "…: not on the phone yet." (a neutral route
 * module's until its lane lands, and every stub's). */
fun notYet(what: String): Nothing = throw Refused(409, "Not on the phone yet", "$what: not on the phone yet.")

/**
 * The routes of caracole serve the phone answers with no module of its own, for good (the plan's §5.4): YouTube's,
 * since the phone never runs yt-dlp, and `GET /lookup`, the computer's lookup page, whose work the library page's
 * search does on the phone. `GET /lookup` is the message page, 409, "…: not on the phone yet."; YouTube's forms are
 * refused, 409, once the form's own checks pass, which the library page says on the line; `GET /api/youtube/video`
 * answers as caracole serve does where YouTube is off: the video's id and address, "off", and no guess. Every other
 * route a lane will answer is its module's, neutral until then (LookupRoutes, RequestsRoutes, SongbookRoutes,
 * VersionsRoutes, HarmonicaRoutes, ReviewRoutes, ExportRoutes, GuitarRoutes), and a stub answers only where no module
 * does (App).
 */
class Stubs : RouteModule {
    override val routes: List<Route> = buildList {
        for ((path, what) in PAGES) {
            add(Route("GET", path, "$what: not on the phone yet", get = GetAnswer { notYet(what) }))
        }
        for ((path, what, page) in FORMS) {
            add(Route("POST", path, "$what: not on the phone yet", page = page, post = PostAnswer { _, _ -> notYet(what) }))
        }
        add(Route("GET", "/api/youtube/video", "a video pasted into the search box: YouTube is off on the phone",
                  get = GetAnswer { request -> youtubeOff(request.target) }))
    }


    /** youtube_routes.pasted_video's answer with YouTube off: the video's id (`id`, else read from `url`), its
     * plain address, its gate "off", no video and no guess; 400 for anything that names no video. */
    private fun youtubeOff(target: String): Response {
        val asked = PyUrl.query(target)
        val id = asked["id"].orEmpty()
        val video = if (id.isNotEmpty()) {
            id.takeIf { VIDEO_ID.matches(it) }
        } else {
            asked["url"].orEmpty().takeIf { it.codePointCount(0, it.length) <= VIDEO_LIMIT }
                ?.let { videoIdFromUrl(PyText.strip(it)) }
        } ?: throw Refused(400, "Not a video", "Not a YouTube video link.")
        val answer = JsonObject(mapOf(
            "id" to JsonPrimitive(video), "url" to JsonPrimitive("https://www.youtube.com/watch?v=$video"),
            "state" to JsonPrimitive("off"), "why" to JsonPrimitive("YouTube isn't on the phone."), "video" to JsonNull,
            "guess" to JsonObject(mapOf("artist" to JsonPrimitive(""), "title" to JsonPrimitive(""))), "song" to JsonNull,
        ))
        return Response(200, Body.Bytes(answer.toString().toByteArray()),
                        mutableListOf("Content-Type" to "application/json; charset=utf-8"))
    }

    /** youtube_urls.video_id_from_url: a video's id from its address as a browser shows it, else null. */
    private fun videoIdFromUrl(url: String): String? {
        val text = if (SCHEME.containsMatchIn(url)) url else "https://$url"
        val parts = try {
            PyUrl.urlsplit(text)
        } catch (e: PyUrl.Invalid) {
            return null
        }
        if (parts.scheme != "http" && parts.scheme != "https") return null
        val host = PyUnicode.lower(parts.netloc)
        val found = when {
            host == "youtu.be" -> parts.path.trim('/')
            HOSTS.matches(host) -> {
                val path = parts.path.trimEnd('/')
                val inPath = PATH_ID.matchEntire(path)
                when {
                    inPath != null -> inPath.groupValues[1]
                    path == "/watch" -> PyUrl.parseQs(parts.query)["v"]?.firstOrNull() ?: ""
                    else -> return null
                }
            }
            else -> return null
        }
        return found.takeIf { VIDEO_ID.matches(it) }
    }

    private companion object {
        const val VIDEO_LIMIT = 600
        val VIDEO_ID = Regex("[A-Za-z0-9_-]{11}")
        val HOSTS = Regex("(?:(?:www|m|music)\\.)?youtube\\.com")
        val PATH_ID = Regex("/(?:shorts|embed|live|v)/([A-Za-z0-9_-]{11})")
        val SCHEME = Regex("^[A-Za-z][A-Za-z0-9+.-]*://")

        /** The pages caracole serve writes itself that the phone has none of. */
        val PAGES = listOf(
            "/lookup" to "The lookup page",
        )

        /** YouTube's forms, and the page each comes from (its refusals'). */
        val FORMS = listOf(
            Triple("/youtube", "A sheet from a YouTube video", "the library"),
            Triple("/youtube/search", "YouTube's search", "the library"),
            Triple("/youtube/video", "Reading a YouTube video", "the library"),
        )
    }
}
