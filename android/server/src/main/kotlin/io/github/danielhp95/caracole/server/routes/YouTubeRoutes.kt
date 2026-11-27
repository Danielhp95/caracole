package io.github.danielhp95.caracole.server.routes

import io.github.danielhp95.caracole.core.db.Db
import io.github.danielhp95.caracole.core.health.Health
import io.github.danielhp95.caracole.core.json.PyJson
import io.github.danielhp95.caracole.core.keys.Normalize
import io.github.danielhp95.caracole.core.library.AudioStore
import io.github.danielhp95.caracole.core.library.OverrideUrls
import io.github.danielhp95.caracole.core.library.Overrides
import io.github.danielhp95.caracole.core.library.SongRow
import io.github.danielhp95.caracole.core.library.Songs
import io.github.danielhp95.caracole.core.names.SongNames
import io.github.danielhp95.caracole.core.py.Py
import io.github.danielhp95.caracole.core.py.PyRe
import io.github.danielhp95.caracole.core.py.PyText
import io.github.danielhp95.caracole.core.py.PyUrl
import io.github.danielhp95.caracole.core.youtube.Records
import io.github.danielhp95.caracole.core.youtube.SearchGate
import io.github.danielhp95.caracole.core.youtube.Thumbs
import io.github.danielhp95.caracole.core.youtube.Videos
import io.github.danielhp95.caracole.core.youtube.YouTubeAudio
import io.github.danielhp95.caracole.core.youtube.YouTubeData
import io.github.danielhp95.caracole.core.youtube.YtDlp
import io.github.danielhp95.caracole.server.PhoneParts
import io.github.danielhp95.caracole.server.http.Body
import io.github.danielhp95.caracole.server.http.GetAnswer
import io.github.danielhp95.caracole.server.http.PostAnswer
import io.github.danielhp95.caracole.server.http.Refused
import io.github.danielhp95.caracole.server.http.Request
import io.github.danielhp95.caracole.server.http.Response
import io.github.danielhp95.caracole.server.http.Route
import io.github.danielhp95.caracole.server.http.RouteModule
import io.github.danielhp95.caracole.server.jobs.JobCommands
import io.github.danielhp95.caracole.server.jobs.Status
import io.github.danielhp95.caracole.server.routes.library.Answers
import io.github.danielhp95.caracole.server.routes.library.SongForm
import io.github.danielhp95.caracole.server.routes.lookup.LookupForms
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.booleanOrNull
import kotlinx.serialization.json.jsonPrimitive
import java.io.File
import java.time.Instant

/**
 * A sheet from a YouTube video on the phone, as caracole serve's (web/youtube_routes.py):
 *
 *     POST /youtube         a song's auto sheet from the video `youtube` names: a song of the library (`song`, its
 *                           id, with its `identity`: a card's Sheet from a YouTube video), or one by name (`artist`,
 *                           `title`), `caracole youtube --sheet --progress --url=… --song=…` queued under `youtube:`
 *                           and the song's key (the job adds a song the library hasn't: the phone writes no
 *                           wanted.txt)
 *     GET  /api/youtube/video?url=|id=
 *                           a video pasted into the search box, with no request: its id and plain address, its gate
 *                           (SearchGate.videoGate) and why, its title, channel, length and thumbnail once read, the
 *                           song's name read from them (SongNames.readNames, the title with its channel), and the
 *                           library's song of it (by its audio, its `[youtube]`, or the name) with or without a sheet
 *     POST /youtube/video   that video read now (`url` or `id`): `caracole youtube --video=<id> --progress` queued under
 *                           `youtube-search:video:<id>`, a job of no song's, when its gate says `auto`; 202 {job, url}
 *                           to the page's script
 *     GET  /youtube/thumb/<id>.jpg
 *                           a kept thumbnail, checked again (Thumbs.read), with a policy that runs nothing; 404 else
 *
 * `POST /request` with `youtube` is the first (LibraryRoutes hands it over: [sheetFromYoutube]). Refused as caracole
 * serve refuses, before anything is queued: a link that is no video's (400); where this phone makes no sheet from a
 * video ([problem]: Phone.youtubeProblem, the design's §5.6, 409 "No sheets from YouTube here: …"); a song YouTube
 * isn't for (ignored, a human sheet, audio of its own: an upload of [audio]'s or an `audio_path` that isn't its
 * `youtube:` record's, 409); a pasted video read this month (409), off (409), cooling, the hour's 10 spent or failed
 * lately (429). The POSTs are form routes, so App's cross-origin check and form token hold; the GET under `/api/` is
 * App's own-page read alone. vectors/web/youtube_routes.jsonl holds them to caracole serve's (WebReplay).
 */
class YouTubeRoutes(
    val parts: PhoneParts,
    private val audio: AudioStore?,
    private val problem: () -> String?,
    private val clock: () -> Instant = Instant::now,
) : RouteModule {
    override val routes: List<Route> = listOf(
        Route("POST", "/youtube", "a song's auto sheet from a YouTube video (youtube, song or artist and title)",
              post = PostAnswer { _, form -> sheetFromYoutube(form) }),
        Route("GET", "/api/youtube/video", "a video pasted into the search box: what caracole knows of it (url or id)",
              get = GetAnswer { request -> pastedVideo(request) }),
        Route("POST", "/youtube/video", "a video pasted into the search box read now (url or id)",
              post = PostAnswer { request, form -> readPastedVideo(request, form) }),
        Route("GET", THUMB, "a pasted or suggested video's thumbnail, as kept", under = true,
              get = GetAnswer { request -> thumbnail(request) }),
    )

    private val thumbs: Thumbs get() = Thumbs(File(parts.stateDir, CACHE))

    /** sheet_from_youtube: the song's auto sheet from the video in `youtube`, queued; [form] read already as a
     * request's (LibraryRoutes: SongForm.named). */
    fun sheetFromYoutube(form: Map<String, String>): Response {
        val url = videoField(form)
        problem()?.let { throw Refused(409, "Not here", "$NOT_HERE: $it.") }
        val (display, key, adds) = parts.database.read { db ->
            val overrides = LookupForms.overrides(db)
            if (Py.strip(form["song"].orEmpty()).isNotEmpty()) {
                val song = LookupForms.song(db, LookupForms.songId(form.getValue("song")))
                LookupForms.sameSong(song, form)
                youtubeIsFor(db, song, overrides)
                Triple(song.display, song.key, null)
            } else {
                val artist = Py.strip(form["artist"].orEmpty())
                val title = Py.strip(form["title"].orEmpty())
                if (artist.isNotEmpty() && title.isNotEmpty()) {  // one the library has: refused before anything
                    Songs.byKey(db, Normalize.identityKey(artist, title))?.let { youtubeIsFor(db, it, overrides) }
                }
                val line = SongForm.song(form, picks = false)
                Triple(line.display, line.key, line)
            }
        }
        // a song by name: its album and length on the spec, as wanted.txt's line keeps them there, for the job to add
        val spec = LookupForms.spec("Sheet from YouTube: $display", JobCommands.YOUTUBE_SHEET + key,
                                    JobCommands.youtubeSheetSteps(display, url), display = display).copy(song = adds)
        val job = parts.queue.submitOrRefuse(spec, FULL).first
        return Answers.queued(LookupForms.view(parts.database, parts.queue, parts.cards, job, clock()))
    }

    /** video_field: a form's `youtube`, the video's plain address; 400 for anything that is no video's. */
    private fun videoField(form: Map<String, String>): String {
        val value = Py.strip(form["youtube"].orEmpty())
        val video = if (Py.len(value) <= VIDEO_LIMIT) OverrideUrls.videoIdFromUrl(value) else null
        return YouTubeData.read().watchUrl(video ?: throw notAVideo())
    }

    /**
     * Why the share page offers no Make its sheet from this video for the song [names] names (the phone-youtube
     * design's §5.2), in the words this route would refuse it in, null where it offers one: the route not ready now
     * ([offered]: [problem], then YouTube cooling down, "No sheets from YouTube here: …"), no names read ([NO_NAMES]),
     * or a song of the library it isn't for (ignored, a human sheet, audio of its own: [youtubeIsFor]'s words). Asks
     * nothing and writes nothing.
     */
    fun whyNotFromVideo(names: Pair<String, String>?): String? {
        val why = problem()  // read before: no read nested in the one below
        return parts.database.read { db ->
            val notNow = offered(why, db, clock())
            when {
                notNow != null -> "$NOT_HERE: $notNow."
                names == null || Py.strip(names.first).isEmpty() || Py.strip(names.second).isEmpty() -> NO_NAMES
                else -> Songs.byKey(db, Normalize.identityKey(names.first, names.second))?.let { song ->
                    try {
                        youtubeIsFor(db, song, LookupForms.overrides(db))
                        null
                    } catch (e: Refused) {
                        e.message
                    }
                }
            }
        }
    }

    /** youtube_is_for: 409 for a song a sheet from YouTube isn't for, in `caracole youtube --sheet`'s words. */
    private fun youtubeIsFor(db: Db, song: SongRow, overrides: Overrides) {
        LookupForms.notIgnored(song, overrides)
        if (db.one("SELECT 1 FROM files WHERE song_id = ? AND name = ?", song.id, HUMAN_SHEET) { true } != null) {
            throw Refused(409, "Has a sheet", "${song.display} already has a sheet.")
        }
        val uploaded = audio?.uploaded(song) != null
        if (uploaded || (!song.audioPath.isNullOrEmpty() && YouTubeAudio.youtubeAudio(db, song) == null)) {
            throw Refused(409, "Has its audio", "${song.display} has its own audio (bought or given); auto-chords uses that.")
        }
    }

    // --- a video pasted into the search box ------------------------------------------------------------------------

    /** _pasted_id: the id of the video [link] names, or [id] itself; 400 for anything else. */
    private fun pastedId(link: String, id: String): String {
        val video = if (id.isNotEmpty()) {
            id.takeIf { PyRe.fullmatch(YouTubeData.read().videoId, it) != null }
        } else {
            if (Py.len(link) <= VIDEO_LIMIT) OverrideUrls.videoIdFromUrl(Py.strip(link)) else null
        }
        return video ?: throw notAVideo()
    }

    /** pasted_video (GET /api/youtube/video). */
    private fun pastedVideo(request: Request): Response {
        val asked = PyUrl.query(request.target)
        val videoId = pastedId(asked["url"].orEmpty(), asked["id"].orEmpty())
        val now = clock()
        val config = parts.config()
        val why = problem()  // read before: no read nested in the one below (the pool's four)
        val answer = parts.database.read { db ->
            val overrides = LookupForms.overrides(db)
            val said = SearchGate.videoGate(config, db, videoId, now, why)
            val video = said.asked?.get("video") as? JsonObject
            var (artist, title) = if (video != null) {
                SongNames.readNames(db, orEmpty(video["title"]), Songs.list(db), channel = orEmpty(video["channel"]))
                    ?: ("" to "")
            } else "" to ""
            var song = songOfVideo(db, overrides, videoId)
            if (song != null) {
                artist = song.artist
                title = song.title
            } else if (artist.isNotEmpty() && title.isNotEmpty()) {
                song = Songs.byKey(db, Normalize.identityKey(artist, title))
            }
            val hasSheet = song != null &&
                db.one("SELECT 1 FROM files WHERE song_id = ? AND name = ?", song.id, HUMAN_SHEET) { true } != null
            val shown = said.why.ifEmpty {
                if (said.state == NONE && said.asked != null) "YouTube won't give it (${Videos.shown(said.asked!!["unavailable"])})"
                else ""
            }
            val out = linkedMapOf<String, JsonElement>("id" to JsonPrimitive(videoId),
                "url" to JsonPrimitive(YouTubeData.read().watchUrl(videoId)), "state" to JsonPrimitive(said.state))
            if (shown.isNotEmpty()) out["why"] = JsonPrimitive(shown)
            out["video"] = if (video == null) JsonNull else JsonObject(linkedMapOf(
                "title" to (video["title"]?.takeIf(::truthy) ?: JsonPrimitive("")),
                "channel" to (video["channel"]?.takeIf(::truthy) ?: JsonPrimitive("")),
                "duration" to (video["duration"] ?: JsonNull),
                "thumb" to if (truthy(said.asked?.get("thumb"))) JsonPrimitive("$THUMB$videoId.jpg") else JsonNull,
            ))
            out["guess"] = JsonObject(linkedMapOf("artist" to JsonPrimitive(artist), "title" to JsonPrimitive(title)))
            out["song"] = if (song == null) JsonNull else JsonObject(linkedMapOf(
                "id" to JsonPrimitive(song.id), "display" to JsonPrimitive(song.display),
                "has_sheet" to JsonPrimitive(hasSheet),
                "sheet" to (if (hasSheet) sheetHref(db, song)?.let(::JsonPrimitive) ?: JsonNull else JsonNull),
            ))
            JsonObject(out)
        }
        return Answers.json(answer)
    }

    /** read_pasted_video (POST /youtube/video). */
    private fun readPastedVideo(request: Request, form: Map<String, String>): Response {
        val videoId = pastedId(form["url"].orEmpty(), form["id"].orEmpty())
        val now = clock()
        val config = parts.config()
        val why = problem()  // read before: no read nested in the one below
        val said = parts.database.read { db -> SearchGate.videoGate(config, db, videoId, now, why) }
        when (said.state) {
            FOUND, NONE -> throw Refused(409, "Read already", "Read already this month.")
            OFF -> throw Refused(409, "Not here", "$NOT_HERE: ${said.why}.")
            AUTO -> {}
            else -> throw Refused(429, "Not now", "Not now: ${said.why}.")
        }
        val spec = LookupForms.spec("Read YouTube video $videoId", JobCommands.YOUTUBE_SEARCH + said.key,
                                    JobCommands.youtubeVideoSteps(videoId), display = "YouTube video $videoId")
        val job = parts.queue.submitOrRefuse(spec).first
        if ("application/json" !in PyText.lower(request.headers["accept"].orEmpty())) {
            return Response(303, Body.Empty, mutableListOf("Location" to "/${Status.detailsHref(job.id)}"))
        }
        return Answers.json(JsonObject(linkedMapOf("job" to JsonPrimitive(job.id),
                                                   "url" to JsonPrimitive("/api/jobs/${job.id}"))), 202)
    }

    /** song_of_video: the library's song a video is the audio of (its `youtube:` record's), else under `[youtube]`
     * for (its paste's). */
    private fun songOfVideo(db: Db, overrides: Overrides, videoId: String): SongRow? {
        val prefix = (YouTubeData.read().json.getValue("record") as JsonObject).getValue("prefix").jsonPrimitive.content
        for (key in db.query("SELECT key FROM kv WHERE key LIKE ?", "$prefix%") { it.text(0)!! }) {
            val songId = key.removePrefix(prefix)
            if (songId.isEmpty() || !songId.all { it in '0'..'9' }) continue
            val id = songId.toLongOrNull() ?: continue
            if (Records.load(db, id).video?.id == videoId) Songs.byId(db, id)?.let { return it }
        }
        for ((key, pasted) in overrides.youtube) {
            if (pasted == videoId) Songs.byKey(db, key)?.let { return it }
        }
        return null
    }

    /** library_page.sheet_href on the phone: the song's card's primary file, as its line opens it. */
    private fun sheetHref(db: Db, song: SongRow): String? {
        val files = parts.cards.cards(db, listOf(song))[song.id]?.get("files") as? JsonArray ?: return null
        return files.filterIsInstance<JsonObject>().firstOrNull { (it["primary"] as? JsonPrimitive)?.booleanOrNull == true }
            ?.let { (it["href"] as? JsonPrimitive)?.content }
    }

    /** thumbnail (GET /youtube/thumb/<id>.jpg). */
    private fun thumbnail(request: Request): Response {
        val name = PyUrl.unquote(PyUrl.urlsplit(request.target).path, strict = true).removePrefix(THUMB)
        val data = (if (name.endsWith(JPG)) thumbs.read(name.removeSuffix(JPG)) else null)
            ?: return Answers.json(JsonObject(mapOf("error" to JsonPrimitive("No such thumbnail."))), 404)
        return Response(200, Body.Bytes(data), mutableListOf("Content-Type" to "image/jpeg",
                                                             "Content-Security-Policy" to "default-src 'none'; $FRAMES"))
    }

    private fun notAVideo() = Refused(400, "Not a video", "Not a YouTube video link.")

    /** Python's `str(v or "")` of a JSON value. */
    private fun orEmpty(v: JsonElement?): String = if (truthy(v)) Videos.shown(v) else ""

    /** Python's truth of a JSON value. */
    private fun truthy(v: JsonElement?): Boolean = when (v) {
        null, JsonNull -> false
        is JsonPrimitive -> if (v.isString) v.content.isNotEmpty() else v.content !in setOf("false", "0", "0.0", "-0.0")
        is JsonArray -> v.isNotEmpty()
        is JsonObject -> v.isNotEmpty()
    }

    companion object {
        /** The design's §5.6: `server.youtube.why` while YouTube cools down after a block, `{when}` the runner's. */
        const val COOLING = "YouTube refused caracole; asked again after {when}"

        /** Why the library page offers no sheet from a YouTube video now (`server.youtube.why`, the design's §5.6), null
         * where it does: [problem] (Phone.youtubeProblem: YouTube off in the computer's settings, the chords'
         * reasons, no yt-dlp, one that can't run), else YouTube cooling down after a block ([COOLING]). Out of date
         * offers it all the same: the audio stage says so. */
        fun offered(problem: String?, db: Db, now: Instant): String? = problem ?: if (Health.isCooling(db, YOUTUBE, now)) {
            COOLING.replace("{when}", YtDlp.coolingUntil(db))
        } else null

        private const val YOUTUBE = "youtube"

        /** youtube_routes.VIDEO_LIMIT: characters of a pasted address. */
        const val VIDEO_LIMIT = 600
        /** youtube_routes.NOT_HERE: how a refusal begins where no sheet from YouTube can be made. */
        const val NOT_HERE = "No sheets from YouTube here"
        /** The share page's hint for a video whose song's names caracole couldn't read: Edit's names make its sheet. */
        const val NO_NAMES = "Type the artist and the title (Edit) to make its sheet from this video."
        const val THUMB = "/youtube/thumb/"
        private const val JPG = ".jpg"
        private const val FRAMES = "frame-ancestors 'none'"
        private const val CACHE = "cache"
        private const val HUMAN_SHEET = "sheet.txt"
        private const val FULL = "The queue is full: nothing queued. Ask again once it empties."
        private const val FOUND = "found"
        private const val NONE = "none"
        private const val AUTO = "auto"
        private const val OFF = "off"
    }
}
