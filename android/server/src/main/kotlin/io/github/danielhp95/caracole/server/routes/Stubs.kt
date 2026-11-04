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

/** What a route not on the phone yet answers: the message page, 409, "… isn't on the phone yet." (a neutral route
 * module's until its lane lands, and every stub's). */
fun notYet(what: String): Nothing = throw Refused(409, "Not on the phone yet", "$what isn't on the phone yet.")

/**
 * The routes of caracole serve no module of the phone answers yet (the plan's §5.3), each answering "… isn't on the
 * phone yet." where no module answers it (App: a stub's route answers only there). Their pages (the picker, a sheet's
 * versions, a harmonica tab's readings, the Guitar Pro page, the lookup page, Export PDF) are the message page, 409;
 * their forms are refused, 409, once the form's own checks pass, which the library page says on the line. A route a
 * lane will answer moves to its module, neutral until then (LookupRoutes, RequestsRoutes; skeleton-m5m6 moves M6's).
 * `GET /api/youtube/video` answers as caracole serve does where YouTube is off: the video's id and address, "off",
 * and no guess; YouTube's routes and `GET /lookup` stay here for good.
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

        /** The pages caracole serve writes itself that the phone hasn't yet. */
        val PAGES = listOf(
            "/review" to "Picking a song's match",
            "/versions" to "Choosing a sheet's version",
            "/harmonica" to "Choosing how a harmonica tab is read",
            "/guitar" to "The Guitar Pro page",
            "/lookup" to "The lookup page",
            "/export.pdf" to "Exporting a PDF",
        )

        /** The forms caracole serve reads that the phone doesn't yet, and the page each comes from (its refusals'). */
        val FORMS = listOf(
            Triple("/review", "Picking a song's match", "the library"),
            Triple("/versions/choose", "Choosing a sheet's version", "the version's page"),
            Triple("/versions/keep", "Keeping a sheet's version", "the version's page"),
            Triple("/versions/clear", "Going back to caracole's version", "the version's page"),
            Triple("/harmonica/pin", "Choosing how a harmonica tab is read", "the tab's page of readings"),
            Triple("/harmonica/clear", "Choosing how a harmonica tab is read", "the tab's page of readings"),
            Triple("/songbook/make", "Making a songbook", "the library"),
            Triple("/songbook/add", "Adding to a songbook", "the library"),
            Triple("/songbook/add-song", "Adding to a songbook", "the library"),
            Triple("/songbook/get", "Getting a songbook's songs", "the library"),
            Triple("/songbook/remove", "Taking a song out of a songbook", "the library"),
            Triple("/songbook/move", "Moving a song in a songbook", "the library"),
            Triple("/songbook/set", "Setting a song's key in a songbook", "the library"),
            Triple("/songbook/rename", "Renaming a songbook", "the library"),
            Triple("/songbook/delete", "Deleting a songbook", "the library"),
            Triple("/youtube", "A sheet from a YouTube video", "the library"),
            Triple("/youtube/search", "YouTube's search", "the library"),
            Triple("/youtube/video", "Reading a YouTube video", "the library"),
        )
    }
}
