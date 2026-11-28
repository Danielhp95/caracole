package io.github.danielhp95.caracole.server.routes

import io.github.danielhp95.caracole.core.db.Db
import io.github.danielhp95.caracole.core.json.PyJson
import io.github.danielhp95.caracole.core.keys.Normalize
import io.github.danielhp95.caracole.core.library.AudioStore
import io.github.danielhp95.caracole.core.library.Overrides
import io.github.danielhp95.caracole.core.library.SongRow
import io.github.danielhp95.caracole.core.library.Songs
import io.github.danielhp95.caracole.core.names.SongNames
import io.github.danielhp95.caracole.core.py.Py
import io.github.danielhp95.caracole.core.py.PyFormat
import io.github.danielhp95.caracole.core.py.PyRegex
import io.github.danielhp95.caracole.core.py.PyUrl
import io.github.danielhp95.caracole.core.youtube.Records
import io.github.danielhp95.caracole.server.PhoneParts
import io.github.danielhp95.caracole.server.http.App
import io.github.danielhp95.caracole.server.http.DocumentAnswer
import io.github.danielhp95.caracole.server.http.PostAnswer
import io.github.danielhp95.caracole.server.http.Refused
import io.github.danielhp95.caracole.server.http.Request
import io.github.danielhp95.caracole.server.http.Response
import io.github.danielhp95.caracole.server.http.Route
import io.github.danielhp95.caracole.server.http.RouteModule
import io.github.danielhp95.caracole.server.jobs.JobCommands
import io.github.danielhp95.caracole.server.routes.library.Answers
import io.github.danielhp95.caracole.server.routes.library.SongForm
import io.github.danielhp95.caracole.server.routes.lookup.LookupForms
import io.github.danielhp95.caracole.server.routes.share.AudioShareView
import io.github.danielhp95.caracole.viewer.autochords.SheetHalf
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.booleanOrNull
import java.io.IOException
import java.io.InputStream
import java.time.Instant

/**
 * A sheet from an audio file, on the phone as on caracole serve (web/audio_routes.py; the chords-on-the-phone
 * design's §8.2): the library page's "+" and a card's Sheet from an audio file….
 *
 *     POST /audio/upload?name=   the file's bytes (`bytes`, spooled: never held whole, AudioStore.AUDIO_MAX at most,
 *                          refused unread past it by its Content-Length; the form token in its header), staged in
 *                          `stateDir/audio/` (AudioStore.stage, a chunk at a time): its id, name, size, format,
 *                          length and tags, the song they name (`guess`, audio_sheet.names_of: [namesOf]) and the
 *                          library's song of it (`song`: its human sheet and its link, and the audio the file
 *                          replaces, "purchase", "youtube", "upload" or null); a card's (`song`, `identity`), that
 *                          song, refused 404 for none and 409 for another's identity before a byte is read
 *     POST /audio           the song's auto sheet from a staged upload (`upload`): a song of the library (`song`,
 *                          `identity`) or one by name (`artist`, `title`, as wanted.txt's line would hold them: the
 *                          phone writes none, its AudioRunner adds the song with the file's album and length), with
 *                          `caracole audio --progress --upload=ID --song=…` queued under `audio:` and the song's key;
 *                          asked again while one waits or runs, that one is the answer and this file is let go
 *     POST /audio/drop      a staged upload deleted now (JSON `{"upload"}`: the dialog's Cancel)
 *
 * Refused as caracole serve refuses, in its words: a phone that makes no sheet from audio (409, "No sheets from audio
 * files here: …", [problem]: Phone.audioProblem, the one answer the job and the page's `server.audio` give too); the
 * store's refusals with its statuses (400, 413, 415, 422, 507; an upload not staged 400 or 404); a song an audio
 * sheet isn't for (409: ignored, a human sheet); a drop while a job names the upload (409).
 *
 * The store's lock (AudioStore.held) is held as caracole serve holds audio_store's: Make sheet from what it reads of
 * the upload to the job queued, a drop from its check of the queue to the drop, and an upload reads the jobs'
 * uploads under it alone (stage's and sweep's `named`, a function, JobCommands.uploadsNamed of the queue now), so an
 * upload from another tab never lets go of a file Make sheet is queueing, and no route waits for another's bytes.
 * Every upload sweeps the store first (AudioStore.sweep: what was left an hour). A refusal of the upload's (the
 * phone's, the card's, the store's at its first chunk that isn't audio) leaves the rest of its body unread: the
 * route closes the stream, and the answer says `Connection: close`, LocalServer dropping the rest, never resetting
 * the connection under a client still sending (which would lose the refusal it is to read).
 */
class AudioRoutes(val parts: PhoneParts, val store: AudioStore, private val problem: () -> String?,
                  private val clock: () -> Instant = Instant::now) : RouteModule {
    override val routes: List<Route> = listOf(
        Route("POST", "/audio/upload", "an audio file uploaded for its song's auto sheet, staged (name; song, identity)",
              body = Route.BYTES, limit = AudioStore.AUDIO_MAX.toInt(), spool = true,
              document = DocumentAnswer { request, body -> (body as InputStream).use { upload(request, it) } }),
        Route("POST", "/audio", "a song's auto sheet from a staged upload, queued (upload; song, identity | artist, title)",
              post = PostAnswer { _, form -> sheetFromAudio(form) }),
        Route("POST", "/audio/drop", "a staged upload deleted now ({\"upload\"})", body = Route.JSON,
              limit = App.MAX_BODY, document = DocumentAnswer { _, doc -> drop(doc as JsonElement) }),
    )

    private fun canMake() {
        val reason = problem() ?: return
        throw Refused(409, "Not here", "$NOT_HERE: $reason.")
    }

    private fun named(): Set<String> = JobCommands.uploadsNamed(parts.queue.snapshot())

    /** upload: the file staged, and what it is and names. */
    private fun upload(request: Request, input: InputStream): Response {
        canMake()
        val params = PyUrl.query(request.target)
        val card = cardSong(params)
        val up = try {
            store.sweep(::named)
            store.stage(input, params["name"].orEmpty(), ::named)
        } catch (e: AudioStore.AudioError) {
            throw Refused(e.status, "Not taken", e.message.orEmpty())
        } catch (e: IOException) {
            throw Refused(503, "Not kept", "The file couldn't be kept: ${e.message ?: e.javaClass.simpleName}.")
        }
        val answer = parts.database.read { db ->
            val (artist, title) = namesOf(db, up.name, up.tags)
            val song = card ?: artist?.let { Songs.byKey(db, Normalize.identityKey(it, title)) }
            JsonObject(linkedMapOf(
                "upload" to JsonPrimitive(up.id), "name" to JsonPrimitive(up.name), "size" to JsonPrimitive(up.size),
                "format" to JsonPrimitive(up.format), "duration" to PyJson.float(up.durationS),
                "tags" to JsonObject(up.tags.mapValues { (_, v) -> v?.let(::JsonPrimitive) ?: JsonNull }),
                "guess" to JsonObject(linkedMapOf("artist" to JsonPrimitive(artist.orEmpty()), "title" to JsonPrimitive(title))),
                "song" to (song?.let { songJson(db, it) } ?: JsonNull),
            ))
        }
        return Answers.json(answer)
    }

    /** _card_song: the song a card's upload names (`song`, `identity` in the query); null for the "+". */
    private fun cardSong(params: Map<String, String>): SongRow? {
        val asked = Py.strip(params["song"].orEmpty())
        if (asked.isEmpty()) return null
        val id = LookupForms.songId(asked, where = "address")
        val song = parts.database.read { db -> LookupForms.song(db, id) }
        LookupForms.sameSong(song, mapOf("identity" to params["identity"].orEmpty()))
        return song
    }

    /** _song: the library's song of an upload as the dialog shows it. */
    private fun songJson(db: Db, song: SongRow): JsonObject {
        val sheet = hasSheet(db, song)
        return JsonObject(linkedMapOf(
            "id" to JsonPrimitive(song.id), "display" to JsonPrimitive(song.display), "identity" to JsonPrimitive(song.key),
            "has_sheet" to JsonPrimitive(sheet), "sheet" to ((if (sheet) sheetHref(db, song) else null)?.let(::JsonPrimitive) ?: JsonNull),
            "audio" to (audioOf(db, song)?.let(::JsonPrimitive) ?: JsonNull),
        ))
    }

    private fun hasSheet(db: Db, song: SongRow): Boolean =
        db.one("SELECT 1 FROM files WHERE song_id = ? AND name = ?", song.id, HUMAN_SHEET) { true } == true

    /** library_page.sheet_href on the phone: the song's card's primary file, as its line opens it. */
    private fun sheetHref(db: Db, song: SongRow): String? {
        val files = parts.cards.cards(db, listOf(song))[song.id]?.get("files") as? JsonArray ?: return null
        return files.filterIsInstance<JsonObject>().firstOrNull { (it["primary"] as? JsonPrimitive)?.booleanOrNull == true }
            ?.let { (it["href"] as? JsonPrimitive)?.content }
    }

    /** _audio_of: the song's audio as its source, "upload" (a file you gave), "youtube" (youtube_audio: its record's
     * file, of a video), "purchase", or none. */
    private fun audioOf(db: Db, song: SongRow): String? {
        val path = song.audioPath?.takeIf { it.isNotEmpty() } ?: return null
        if (store.uploaded(song) != null) return "upload"
        val record = Records.load(db, song.id)
        return if (record.audio != null && record.audio == path && record.video != null) "youtube" else "purchase"
    }

    /** audio_is_for: refused (409) for a song an audio sheet isn't for, in `caracole audio`'s words. */
    private fun audioIsFor(db: Db, song: SongRow, overrides: Overrides) {
        LookupForms.notIgnored(song, overrides)
        if (hasSheet(db, song)) throw Refused(409, "Has a sheet", "${song.display} already has a sheet.")
    }

    /** sheet_from_audio: the song's auto sheet from the staged upload, queued. */
    private fun sheetFromAudio(form: Map<String, String>): Response {
        canMake()
        // Held from the check to the job queued: an upload from another tab meanwhile would let go of this one.
        return store.held {
            val up = try {
                store.staged(Py.strip(form["upload"].orEmpty()))
            } catch (e: AudioStore.AudioError) {
                throw Refused(e.status, "Not made", e.message.orEmpty())
            }
            queueSheet(form, up)
        }
    }

    private fun queueSheet(form: Map<String, String>, up: AudioStore.Staged): Response {
        val (display, key) = if (Py.strip(form["song"].orEmpty()).isNotEmpty()) {
            val asked = LookupForms.songId(form.getValue("song"))
            val song = parts.database.read { db ->
                val overrides = LookupForms.overrides(db)
                LookupForms.song(db, asked).also { song ->
                    LookupForms.sameSong(song, form)
                    audioIsFor(db, song, overrides)
                }
            }
            song.display to song.key
        } else {
            val artist = Py.strip(form["artist"].orEmpty())
            val title = Py.strip(form["title"].orEmpty())
            if (artist.isNotEmpty() && title.isNotEmpty()) {  // one the library has: refused before anything else
                parts.database.read { db ->
                    val overrides = LookupForms.overrides(db)
                    Songs.byKey(db, Normalize.identityKey(artist, title))?.let { audioIsFor(db, it, overrides) }
                }
            }
            val fields = LinkedHashMap(form)
            if (Py.strip(fields["album"].orEmpty()).isEmpty()) fields["album"] = up.tags["album"].orEmpty()
            if (Py.strip(fields["duration"].orEmpty()).isEmpty() && up.durationS >= 1) {
                fields["duration"] = JobCommands.formatDuration(PyFormat.roundHalfEven(up.durationS * 1000))
            }
            val song = SongForm.song(fields, picks = false)  // as wanted.txt's line would hold it; the job adds it
            song.display to song.key
        }
        val spec = LookupForms.spec("Sheet from an audio file: $display", JobCommands.AUDIO_SHEET + key,
                                    JobCommands.audioSheetSteps(display, up.id), display = display)
        val (job, new) = parts.queue.submitOrRefuse(spec, FULL)
        if (!new && up.id !in named()) {  // that job is the answer: this file let go
            try {
                store.drop(up.id)
            } catch (_: AudioStore.AudioError) {
            }
        }
        return Answers.queued(LookupForms.view(parts.database, parts.queue, parts.cards, job, clock()))
    }

    // --- a file shared to the app (ShareActivity, ShareRoutes' /share/audio) -------------------------------------

    /**
     * An audio file shared to the app, staged as an upload is ([upload]'s): refused ([Refused] 409, the routes' words)
     * where no sheet is made here, before a byte is read; else the store swept and [input] staged a chunk at a time,
     * never held whole, every other upload no job names let go (AudioStore.stage); the store's refusals as they are
     * (AudioStore.AudioError). [input] is read once and left open: its caller closes it.
     */
    fun stageShared(input: InputStream, name: String): AudioStore.Staged {
        canMake()
        store.sweep(::named)
        return store.stage(input, name, ::named)
    }

    /**
     * What the share's page shows ([AudioShareView]): with [uploadId], the staged upload (its name, format and
     * length), the names it gives (audio_sheet.names_of, [namesOf]), the library's song of them, its sheet now and
     * the audio the file replaces (the upload's answer's `song.audio`, [audioOf]), and whether its auto sheet has words heard on the computer (its version's `lyrics_source`, a transcript); with
     * none, the file's [name] alone. Where no sheet is made here, why, in the routes' words; an upload its job kept as its
     * song's audio, that song and the job's line ([keptView]); any other upload that isn't there, the store's words
     * of it.
     */
    internal fun shareView(uploadId: String?, name: String): AudioShareView {
        val why = problem()?.let { "$NOT_HERE: $it." }
        val up = uploadId?.let {
            try {
                store.staged(it)
            } catch (e: AudioStore.AudioError) {
                return keptView(it, why) ?: AudioShareView(null, name, why = why, gone = e.message.orEmpty())
            }
        } ?: return AudioShareView(null, name, why = why ?: AudioStore.WORDS.getValue("gone"))
        val length = if (up.durationS > 0) JobCommands.formatDuration(PyFormat.roundHalfEven(up.durationS * 1000)) else ""
        return parts.database.read { db ->
            val (artist, title) = namesOf(db, up.name, up.tags)
            val song = artist?.let { Songs.byKey(db, Normalize.identityKey(it, title)) }
            val auto = song?.let { autoRaw(db, it) }
            AudioShareView(
                up.id, up.name, up.format, length, artist.orEmpty(), title, song?.display,
                sheet = when {
                    song == null -> AudioShareView.SHEET_NONE
                    hasSheet(db, song) -> AudioShareView.SHEET_SITES
                    auto != null -> AudioShareView.SHEET_AUTO
                    else -> AudioShareView.SHEET_NONE
                },
                heard = auto?.let { (it["lyrics_source"] as? JsonPrimitive)?.content == SheetHalf.LYRICS_SOURCE } == true,
                why = why, replaces = song?.let { audioOf(db, it) },
            )
        }
    }

    /** The raw record of the song's auto version that names a kept file (its sheet), or null for none. */
    /**
     * The share's page of an upload a keep moved into place ([AudioStore.marked]: Back from the Journal after Make
     * sheet loads it again): the song it is the audio of, while that song's row names the kept file, or its keep is
     * under way (the row not written yet), and the Journal's line of the newest job naming the upload; null for none
     * (no marker, the song gone, or its audio another since), the store's words then.
     */
    private fun keptView(uploadId: String, why: String?): AudioShareView? {
        val marked = store.marked(uploadId) ?: return null
        val song = parts.database.read { db -> Songs.byId(db, marked.song) } ?: return null
        if (marked.done && store.uploaded(song)?.path != marked.file.path) return null
        val job = parts.queue.snapshot().firstOrNull { j -> j.steps.any { "--upload=$uploadId" in it.args } }
        return AudioShareView(null, song.display, why = why, kept = song.display,
                              journal = job?.let { "/#tab=requests&job=${it.id}" })
    }

    private fun autoRaw(db: Db, song: SongRow): JsonObject? =
        db.one("SELECT v.raw FROM versions v WHERE v.song_id = ? AND v.provider = ? AND EXISTS (SELECT 1 FROM files f " +
                   "WHERE f.version_id = v.id) ORDER BY v.id LIMIT 1", song.id, AUTO) { it.text(0) }
            ?.let { runCatching { PyJson.loads(it) as? JsonObject }.getOrNull() }

    /** The share page's Cancel: the staged upload [uploadId] names deleted, whatever is left of it; 409 while a job
     * names it (its Make sheet was pressed), 400 for no id; one gone already is no refusal (the share is left). */
    internal fun cancelShared(uploadId: String) {
        store.held {
            if (uploadId in named()) throw Refused(409, "Not dropped", WAITS)
            try {
                store.drop(uploadId)
            } catch (e: AudioStore.AudioError) {
                if (e.status != 404) throw Refused(e.status, "Not dropped", e.message.orEmpty())
            }
        }
    }

    /** drop: the staged upload `upload` names deleted now; 409 while a job names it, 404 none, 400 no id. */
    private fun drop(doc: JsonElement): Response {
        val id = ((doc as? JsonObject)?.get("upload") as? JsonPrimitive)?.takeIf { it.isString }?.content
            ?: throw Refused(400, "Not dropped", NOT_NAMED)
        store.held {  // no job queued for it between the check and the drop
            if (id in named()) throw Refused(409, "Not dropped", WAITS)
            try {
                store.drop(id)
            } catch (e: AudioStore.AudioError) {
                throw Refused(e.status, "Not dropped", e.message.orEmpty())
            }
        }
        return Answers.json(JsonObject(mapOf("dropped" to JsonPrimitive(id))))
    }

    companion object {
        /** How a refusal begins where no sheet can be made (audio_routes.NOT_HERE). */
        const val NOT_HERE = "No sheets from audio files here"
        const val WAITS = "That file waits for its sheet: cancel its request in the Journal first."
        const val NOT_NAMED = "Which upload? {\"upload\": \"<its id>\"}, as POST /audio/upload named it."

        /** A full queue's words: the phone wrote nothing for the song (caracole serve's names its wanted.txt line). */
        const val FULL = "The queue is full: nothing queued. Ask again once it empties."

        private const val HUMAN_SHEET = "sheet.txt"

        /** The auto sheet's provider (AudioRunner's). */
        private const val AUTO = "auto"

        /** music._TRACK_PREFIX: a track number before a file's name. */
        private val TRACK_PREFIX = PyRegex.compile("""^\d{1,3}(?:\s*[-.]\s*|\s+)""")

        /**
         * audio_sheet.names_of: the artist and the title an audio file names: its artist and title tags, the title
         * cleaned as a video's is (SongNames.clean); else its [name] less its extension and its track number, read as
         * the pages read a query (SongNames.readNames); else that name as the title alone, its artist null.
         */
        fun namesOf(db: Db, name: String, tags: Map<String, String?>): Pair<String?, String> {
            val artist = Py.strip(tags["artist"].orEmpty())
            val title = Py.strip(tags["title"].orEmpty())
            if (artist.isNotEmpty() && title.isNotEmpty()) return artist to SongNames.clean(title).ifEmpty { title }
            val bare = bareName(name)
            return SongNames.readNames(db, bare, Songs.list(db)) ?: (null to SongNames.clean(bare).ifEmpty { bare })
        }

        /** A file's [name] less its extension (pathlib's `Path(name).stem`) and its track number (music.py's), as
         * names_of reads it: the name alone where nothing is left. */
        internal fun bareName(name: String): String {
            val stem = stem(name)
            return Py.strip(TRACK_PREFIX.replaceFirst(stem, "")).ifEmpty { stem }
        }

        /** pathlib's `Path(name).stem` of a name with no folder: less its last suffix, a stem of dots alone none. */
        private fun stem(name: String): String {
            val last = if (name == ".") "" else name
            val i = last.lastIndexOf('.')
            if (i != -1) {
                val stem = last.substring(0, i)
                if (stem.trimStart('.').isNotEmpty()) return stem
            }
            return last
        }
    }
}
