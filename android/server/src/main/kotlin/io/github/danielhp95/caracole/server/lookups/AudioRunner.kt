package io.github.danielhp95.caracole.server.lookups

import io.github.danielhp95.caracole.core.db.Db
import io.github.danielhp95.caracole.core.index.Stamps
import io.github.danielhp95.caracole.core.keys.Normalize
import io.github.danielhp95.caracole.core.library.AudioStore
import io.github.danielhp95.caracole.core.library.Kept
import io.github.danielhp95.caracole.core.library.OverrideUrls
import io.github.danielhp95.caracole.core.library.Overrides
import io.github.danielhp95.caracole.core.library.OverridesError
import io.github.danielhp95.caracole.core.library.SongRow
import io.github.danielhp95.caracole.core.library.Songs
import io.github.danielhp95.caracole.core.library.Versions
import io.github.danielhp95.caracole.core.lookup.Lookup
import io.github.danielhp95.caracole.core.lookup.LookupRequest
import io.github.danielhp95.caracole.core.lookup.LookupWords
import io.github.danielhp95.caracole.core.lookup.Progress
import io.github.danielhp95.caracole.core.lookup.SiteStages
import io.github.danielhp95.caracole.core.lookup.SongPages
import io.github.danielhp95.caracole.core.lyrics.lyricsFromJson
import io.github.danielhp95.caracole.core.py.Py
import io.github.danielhp95.caracole.core.py.PyFormat
import io.github.danielhp95.caracole.server.PhoneParts
import io.github.danielhp95.caracole.server.http.caracoleResource
import io.github.danielhp95.caracole.server.jobs.CommandExit
import io.github.danielhp95.caracole.server.jobs.CommandRunner
import io.github.danielhp95.caracole.server.jobs.JobCommands
import io.github.danielhp95.caracole.server.jobs.JobContext
import io.github.danielhp95.caracole.server.page.LibraryPage
import io.github.danielhp95.caracole.viewer.autochords.AudioUnreadable
import io.github.danielhp95.caracole.viewer.autochords.ChordModels
import io.github.danielhp95.caracole.viewer.autochords.ChordsUnavailable
import io.github.danielhp95.caracole.viewer.autochords.Heard
import io.github.danielhp95.caracole.viewer.autochords.Maker
import io.github.danielhp95.caracole.viewer.autochords.Relay
import io.github.danielhp95.caracole.viewer.autochords.SheetHalf
import io.github.danielhp95.caracole.viewer.render.InfoJson
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import java.io.File
import java.io.IOException
import java.security.MessageDigest
import java.time.temporal.ChronoUnit
import java.util.concurrent.CancellationException

/**
 * `caracole audio --progress --upload=ID --song="ARTIST - TITLE"` on the phone (commands/audio.py, audio_sheet.py):
 * one song's auto sheet from an audio file the owner gave, made now, a job of the queue's worker, its stages
 * audio_sheet.py's ([STAGES]: song, audio, lyrics, vocals, words, chords, pdf, pages), each said as it starts and
 * ends, so that its line, steps and outcome are the computer's for the same request (Status, Outcomes' AUDIO_STEPS).
 *
 * Before any stage, as the command does before it reads anything: a phone with no way to hear ([chords] null: the
 * release, or no `:ml` wired) or whose chord models aren't downloaded ([ready] not null) refuses in the command's
 * words ("caracole makes no sheet from an audio file here: …", exit 1); a name that isn't "Artist - Title" exits 2;
 * the upload is read as the command reads it ([AudioStore.staged]'s record, or the kept file its marker names, the
 * same job again past its audio stage): an id that isn't one exits 2, an upload gone 1. Then:
 *
 * - `song`: found by its identity key, or added ([io.github.danielhp95.caracole.core.library.LibraryStore.add], the
 *   file's album and length), get.py's [LookupWords.ADDED]; refused when it is ignored or has a human sheet (an upload
 *   always wins: no audio of its own refuses it), in one write;
 * - `audio`: the staged upload moved into place ([AudioStore.keep]) as the song's audio, "kept as its audio: MP3,
 *   3:18", the file given before named as what it replaces; the same job again goes on by the upload's marker, as
 *   audio_sheet.py's: done whole, "has this file's audio already"; cut off after the move, [AudioStore.adopt]; gone,
 *   refused in the store's words. In one write; a refusal of the store's fails the stage (exit 1), the stages after it
 *   going on as they can;
 * - `lyrics`: the lookup's lyrics stage ([Lookup.lyrics]: LRCLIB, Megalobiz, AZLyrics through its envelope, at the
 *   lookup pace and in get.py's words, where the computer's job asks at the bulk pace in youtube_sheet.py's), asked
 *   with the audio's length (the song's line's, else the file's), in one write;
 * - `vocals` and `words`: skipped, as the phone hears no words: where every lyrics site missed, "not transcribed here:
 *   the phone hears no words" (transcript.PHONE), else the offer's words of the song's lyrics ("not transcribed: its
 *   lyrics are found"); the words "no vocals";
 * - `chords`: the lookups queued meanwhile go first, then the song read again and still this job's ([stillOurs]);
 *   a sheet already made of this audio is up to date, or laid out again over its words (Relay.onto) where they
 *   changed; else [ChordModels.hear], holding no write while the models run, its steps said as the stage's running
 *   words and [JobContext.yieldToQueued] every second of it (a lookup of the song's own waits for the job: the
 *   queue's rule); then the song read again, still this job's and its audio still the file kept, and in one write
 *   the sheet laid out ([SheetHalf.make]) and kept with its version ([keep], run.py's `_keep`: who made it, [Maker],
 *   the phone with this side's kv `sync:id`, the models' [names], [ChordModels.runtime], the file's name and its
 *   hash), its end youtube_sheet.py's `holds`;
 * - `pdf` and `pages`: the song's pages ([PhoneParts.pages], PhoneRender, its re-lay first), get.py's words for a
 *   caracole that makes no PDF ([LookupWords.NO_PDFS] while there is none, [LookupWords.PAGES_MADE]) and
 *   [LookupWords.LIBRARY_PAGE].
 *
 * Failures, told apart as run.py tells them: audio the phone can't decode ([AudioUnreadable]) fails the chords "audio
 * the phone can't read: …"; the models' setup ([ChordsUnavailable]: missing, their process stopped, too hot, the
 * battery low) fails it in its words; a bug laying out the sheet fails it "a bug in caracole: …"; none records
 * anything against the song, so Try again tries them all again. A refusal (ignored, a human sheet, the song gone or
 * its audio replaced meanwhile) fails the song stage and skips the stages left. The command's last line is the
 * computer's ("No sheet made: …." with exit 1, else "Done in N s: …") and its exit status is the computer's: 0 once
 * the sheet is made, or for a site's wait; 1 for a refusal, a failure or a bug.
 */
class AudioRunner(
    val parts: PhoneParts,
    private val chords: ChordModels?,
    private val store: AudioStore,
    private val problem: () -> String? = { problemOf(chords, null) },
    private val names: () -> Map<String, String> = { emptyMap() },
    private val readOverrides: (Db) -> Overrides = Overrides::read,
    private val stages: SiteStages = SiteStages.ALL,
    private val hold: (() -> Heard) -> Heard = { it() },
) : CommandRunner {
    override suspend fun run(args: List<String>, context: JobContext) {
        val line = LookupJobs.line(args, setOf("--upload", "--song"))
        for (name in line.options.keys) {
            if (name !in KNOWN) throw CommandExit(2, "No such option: $name")
        }
        if (line.words.isNotEmpty()) throw CommandExit(2, ON_THE_PHONE)
        val upload = line.options["--upload"] ?: throw CommandExit(2, ON_THE_PHONE)
        val display = line.options["--song"] ?: throw CommandExit(2, ON_THE_PHONE)
        try {
            OverrideUrls.overrideKey(display)
        } catch (e: OverridesError) {
            throw CommandExit(2, e.message.orEmpty())
        }
        val problem = if (chords == null) LibraryPage.AUDIO_PROBLEM else problem()
        if (problem != null) throw CommandExit(1, Words.text("no_chords").replace("{problem}", problem))
        val given = try {
            given(upload)
        } catch (e: AudioStore.AudioError) {
            throw CommandExit(if (e.status == 400) 2 else 1, e.message.orEmpty())
        } catch (e: IOException) {  // commands/audio.py's OSError reading the file: exit 1, "can't read …"
            throw CommandExit(1, "can't read ${Words.text("the_upload")}: ${e.message ?: e.javaClass.simpleName}")
        }
        val artist = Py.strip(display.substringBefore(" - "))
        val title = Py.strip(display.substringAfter(" - ", ""))
        Job(parts, store, chords!!, context, upload, artist, title, given, names, readOverrides, stages, hold,
            this.problem).run()
    }

    /** What the command reads of the upload before any stage (commands/audio.py `_given_already`, then `staged`): the
     * kept file its marker names, for the same job again past its audio stage; else its staged record. */
    private fun given(upload: String): Given {
        val mark = if (store.gone(upload)) store.marked(upload) else null
        if (mark != null) return Given(null, store.formatAndLength(mark.file).second)
        val staged = store.staged(upload)
        return Given(staged.tags["album"], staged.durationS)
    }

    private class Given(val album: String?, val duration: Double)

    /** One run of the job: its stages, as audio_sheet.py's `_AudioSheet`. */
    private class Job(
        val parts: PhoneParts, val store: AudioStore, val chords: ChordModels, val context: JobContext,
        val upload: String, val artist: String, val title: String, val given: Given,
        val names: () -> Map<String, String>, val readOverrides: (Db) -> Overrides, val stages: SiteStages,
        val hold: (() -> Heard) -> Heard, val problem: () -> String?,
    ) {
        private val started = parts.pacing.monotonic()
        private val now = parts.pacing.clock().truncatedTo(ChronoUnit.SECONDS)
        private val stamp = Stamps.of(now)
        private val display = "$artist - $title"
        private val states = LinkedHashMap<String, String>()
        private val told = HashMap<String, String>()
        private val requests = LinkedHashMap<String, Int>()
        private var files: Map<String, String> = emptyMap()
        private var refused: String? = null
        private var failed: String? = null
        private var bug: String? = null
        private lateinit var overrides: Overrides
        private var song: SongRow? = null
        private var kept: File? = null  // the file the audio stage kept as the song's audio
        private var sheetKept = false  // the chords stage left the song a sheet of this audio, whatever it said after
        private var keptLength: Double? = null

        /** The job refused, said in the song stage, the stages not ended skipped (staged.py `_refuse`). */
        private class Stop(message: String) : Exception(message)

        fun run() {
            report("song", "running")
            try {
                overrides = try {
                    parts.database.read(readOverrides)
                } catch (e: OverridesError) {
                    throw Stop("Can't read overrides.toml: ${e.message}")
                }
                report("song", "done", parts.database.writeBlocking(::findSong))
                for ((name, _) in STAGES.drop(1)) stage(name)
            } catch (e: Stop) {
                refuse(e.message.orEmpty())
            }
            end()
        }

        // --- reporting --------------------------------------------------------------------------------------------

        private fun report(name: String, state: String, detail: String = "") {
            if (context.isCancelled) throw CancellationException("the queue stopped")
            states[name] = state
            told[name] = detail
            context.stage(name, state, detail)
        }

        /** What the running stage [name] is doing now, said once each time it changes (staged.py `_doing`). */
        private fun doing(name: String, detail: String) {
            if (states[name] == "running" && told[name] != detail) report(name, "running", detail)
        }

        private fun stage(name: String) {
            report(name, "running")
            val (state, detail) = try {
                when (name) {
                    "audio" -> audio()
                    "lyrics" -> lyrics()
                    "vocals" -> vocals()
                    "words" -> "skipped" to Words.text("no_vocals")
                    "chords" -> chords()
                    "pdf" -> pdf()
                    "pages" -> "done" to LookupWords.LIBRARY_PAGE
                    else -> error("no stage $name")
                }
            } catch (e: Stop) {
                throw e
            } catch (e: CancellationException) {
                throw e
            } catch (e: VirtualMachineError) {
                throw e
            } catch (e: Exception) {  // a bug: said, and the stages after it go on as they can
                val said = "${e::class.simpleName}: ${e.message.orEmpty()}"
                bug = bug ?: "$name: $said"
                "failed" to Words.text("bug").replace("{error}", said)
            }
            report(name, state, detail)
            checkReadable()
        }

        /** A stage's end that waiting won't mend: the command exits 1. */
        private fun fail(detail: String): Pair<String, String> {
            failed = failed ?: detail
            return "failed" to detail
        }

        private fun refuse(why: String) {
            refused = why
            report("song", "failed", why)
            for ((name, _) in STAGES.drop(1)) {
                if ((states[name] ?: "running") == "running") report(name, "skipped", "")
            }
        }

        /** The command's last line, and its exit status (commands/_common.staged_end). */
        private fun end() {
            val stopped = refused ?: failed ?: bug?.let { "a bug in caracole ($it)" }
            if (stopped != null) throw CommandExit(1, "${Words.text("refused")}: ${stopped.trimEnd('.')}.")
            val sent = requests.filterValues { it != 0 }.entries
                .joinToString(", ") { (p, n) -> "$n ${LookupWords.NAMES[p] ?: p} request" + if (n == 1) "" else "s" }
            val seconds = io.github.danielhp95.caracole.core.py.PyFormat.fixed(parts.pacing.monotonic() - started, 1)
            context.say("Done in $seconds s" + if (sent.isNotEmpty()) ": $sent." else ", asking nothing.")
        }

        /** The sheet said readable once the chords stage kept it (its info.json failing after or not), and again as its
         * viewer comes (get.readable_files). */
        private fun checkReadable() {
            val song = song ?: return
            if (!sheetKept) return
            val readable = parts.database.read { db -> readableFiles(db, song) }
            if (readable.isNotEmpty() && readable != files) {
                files = readable
                context.readable(readable, parts.pacing.monotonic() - started)
            }
        }

        private fun readableFiles(db: Db, song: SongRow): Map<String, String> {
            val kept = Kept.keptFiles(db, song.id).associateBy { it.name }
            val sheet = Versions.SHEET_FILE_NAMES.firstNotNullOfOrNull { kept[it] } ?: return emptyMap()
            val folder = parts.store.folderOf(song)
            val base = sheet.path.substringBeforeLast('/', "")
            val stem = sheet.name.substringBeforeLast('.')
            val out = linkedMapOf("sheet" to sheet.path)
            for ((name, file) in listOf("pdf" to "$stem.pdf", "viewer" to "$stem.html")) {
                if (File(folder, file).isFile) out[name] = if (base.isEmpty()) file else "$base/$file"
            }
            return out
        }

        // --- the song ---------------------------------------------------------------------------------------------

        /** youtube_sheet.py `_the_song` and audio_sheet.py `find_song`: the song found or added, then still ours. */
        private fun findSong(db: Db): String {
            parts.store.ensureCurrentKeys(db)
            val key = Normalize.identityKey(artist, title)
            if (key in overrides.ignore) throw Stop(Words.text("ignored").replace("{display}", display))
            var said = Words.text("in_book")
            val found = Songs.byKey(db, key) ?: run {
                said = LookupWords.ADDED
                val ms = given.duration.takeIf { it >= 1 }?.let { PyFormat.roundHalfEven(it * 1000) }
                try {
                    parts.store.add(db, artist, title, given.album, ms, now = stamp)
                } catch (e: IllegalArgumentException) {
                    throw Stop("Can't add this song: ${e.message}")
                }
            }
            stillOurs(db, found)
            song = found
            context.song(found.id, found.display)
            return said
        }

        /** The song read again; gone (removed, or merged into another), the job ends there (staged.py `_song_again`). */
        private fun again(db: Db): SongRow {
            val was = song!!
            val now = Songs.byId(db, was.id)
                ?: throw Stop(Words.text("left").replace("{display}", was.display).replace("{making}", Words.text("making")))
            song = now
            return now
        }

        /** audio_sheet.py `_still_ours` (`_unsheeted`): not ignored, with no human sheet; and, once the audio stage
         * kept a file, the song's audio still that file (the design's §3.2). */
        private fun stillOurs(db: Db, s: SongRow) {
            if (s.status == "ignored" || s.key in overrides.ignore) {
                throw Stop(Words.text("ignored").replace("{display}", s.display))
            }
            if (Kept.keptFiles(db, s.id).any { it.name == Versions.SHEET_FILE_NAMES[0] }) {
                throw Stop(Words.text("has_sheet").replace("{display}", s.display))
            }
            val kept = kept ?: return
            if (s.audioPath != kept.path) throw Stop(AUDIO_CHANGED.replace("{display}", s.display))
        }

        /** The song and the overrides read again after the lookups went first (staged.py `_after_a_lookup`), then
         * still ours. */
        private fun readAgain(): SongRow = parts.database.writeBlocking { db ->
            overrides = try {
                readOverrides(db)
            } catch (e: OverridesError) {
                overrides
            }
            again(db).also { stillOurs(db, it) }
        }

        // --- the audio --------------------------------------------------------------------------------------------

        /** audio_sheet.py `audio`. */
        private fun audio(): Pair<String, String> = parts.database.writeBlocking { db ->
            val current = again(db)
            val before = store.uploaded(current)
            val replaced = if (before != null) Words.text("given_before") else null
            val mark = if (store.gone(upload)) store.marked(upload) else null
            if (mark != null && mark.done && before == mark.file) {
                kept = mark.file
                keptLength = given.duration
                return@writeBlocking "done" to Words.text("same_file")
            }
            val file: File
            val found: Pair<String, Double>
            try {
                file = if (mark != null && !mark.done) store.adopt(db, current, upload)
                       else store.keep(db, current, store.staged(upload))
                // The kept file read again, as audio_sheet.py's `audio_store.examine(kept)`: should that fail, the stage
                // fails with the audio kept, and Try again goes on by the same-file path (the marker, done).
                found = store.formatAndLength(file)
            } catch (e: AudioStore.AudioError) {
                val said = e.message.orEmpty().trimEnd('.')
                val first = if (said.isEmpty()) 0 else said.offsetByCodePoints(0, 1)  // said[:1], a code point
                return@writeBlocking fail(io.github.danielhp95.caracole.core.py.PyUnicode.lower(said.substring(0, first)) +
                                              said.substring(first))
            } catch (e: IOException) {
                return@writeBlocking fail(Words.text("cant_keep").replace("{what}", Words.text("the_upload"))
                                              .replace("{why}", e.message ?: e.javaClass.simpleName))
            }
            again(db)
            kept = file
            keptLength = found.second
            if (file == before) return@writeBlocking "done" to Words.text("same_file")
            val said = Words.text("kept_as").replace("{format}", found.first)
                .replace("{length}", JobCommands.formatDuration(PyFormat.roundHalfEven(found.second * 1000)))
            "done" to said + (replaced?.let { Words.text("replaces").replace("{replaced}", it) } ?: "")
        }

        // --- the lyrics -------------------------------------------------------------------------------------------

        /** The lookup's lyrics stage over the song, asked with the audio's length (lyrics_search.audio_length: the
         * song's line's, else the file's, once the audio stage kept it). */
        private fun lyrics(): Pair<String, String> {
            val current = parts.database.writeBlocking { db -> again(db).also { stillOurs(db, it) } }
            val length = current.durationMs?.let { it / 1000.0 } ?: keptLength?.takeIf { states["audio"] == "done" }
            var end: Pair<String, String>? = null
            val progress = object : Progress {
                override fun stage(name: String, state: String, detail: String) {
                    if (name != "lyrics") return
                    if (state == "running") doing("lyrics", detail) else end = state to detail
                }
            }
            val lookup = Lookup(parts.config(), parts.database, parts.store, parts.clients(), SongPages.NONE,
                                io.github.danielhp95.caracole.core.lookup.SongbookPages.NONE, parts.alerts,
                                LookupRequest(artist, title), progress, parts.pacing, stages, readOverrides)
            val result = parts.database.writeBlocking { db -> lookup.lyrics(db, current.id, length) }
            for ((p, n) in result.requests) requests[p] = (requests[p] ?: 0) + n
            result.bug?.let { bug = bug ?: it }
            parts.database.writeBlocking { db -> again(db) }
            return end ?: ("skipped" to (result.refused ?: ""))
        }

        /** The phone hears no words: the vocals' skip in the offer's words where a site gave words or its verdict
         * (SITES_ANSWERED), else the phone's reason (lyrics missing, or pending after a site's error, block or spent
         * budget), as youtube_sheet.py's `_why_not_heard` orders them. */
        private fun vocals(): Pair<String, String> {
            if (states["audio"] != "done") return "skipped" to Words.text("no_audio")
            val status = song!!.lyricsStatus
            if (status in Words.sitesAnswered) {  // youtube_sheet.SITES_ANSWERED: said first, whatever the phone does
                return "skipped" to Words.text("not_offered")
                    .replace("{why}", Words.text("lyrics_are").replace("{status}", status))
            }
            return "skipped" to Words.text("not_here").replace("{reason}", Words.text("phone"))
        }

        // --- the chords -------------------------------------------------------------------------------------------

        private fun chords(): Pair<String, String> {
            if (states["audio"] != "done") return "skipped" to Words.text("no_audio")
            context.yieldToQueued()  // the models take a minute: the lookups queued meanwhile go first
            readAgain()
            parts.database.writeBlocking { db -> upToDate(db) }?.let { return it }
            val audio = kept ?: return fail(Words.text("no_audio"))
            val heard = try {
                // The models' files held while they hear (ModelsRunner.holding), asked about again under them: a
                // remove after the job was queued fails it here, in the one answer's words.
                hold {
                    problem()?.let { throw ChordsUnavailable(it) }
                    chords.hear(audio, { step -> doing("chords", step) }, { context.yieldToQueued() })
                }
            } catch (e: AudioUnreadable) {
                return fail(UNREADABLE + (e.message ?: e.javaClass.simpleName))
            } catch (e: ChordsUnavailable) {
                return fail(e.message ?: e.javaClass.simpleName)
            }
            context.yieldToQueued()
            readAgain()
            doing("chords", Words.steps[3])
            return try {
                parts.database.writeBlocking { db -> keepSheet(db, heard, audio) }
            } catch (e: Stop) {
                throw e
            } catch (e: CancellationException) {
                throw e
            } catch (e: Exception) {  // a bug laying it out or keeping it: caracole's, never the file's
                fail(Words.text("bug").replace("{error}", "${e::class.simpleName}: ${e.message.orEmpty()}"))
            } finally {
                // What the models kept to go on from goes once the sheet is kept, never before: a keep that failed
                // leaves it, for Try again to lay the sheet out with no hearing.
                if (sheetKept) chords.forget(audio)
            }
        }

        /** The sheet already made of this audio here: up to date, or laid out again over its words where they changed
         * (Relay.onto); null where the models are to hear it (no auto sheet, one of other audio, one another caracole
         * made: the job is the owner's ask, this side its maker). */
        private fun upToDate(db: Db): Pair<String, String>? {
            val s = again(db)
            val auto = Kept.keptFiles(db, s.id).firstOrNull { it.name == Versions.SHEET_FILE_NAMES[1] } ?: return null
            val version = Versions.get(db, auto.versionId) ?: return null
            if (s.autochordsMtime == null || s.autochordsMtime != s.audioMtime || Relay.madeElsewhere(db, version.raw)) {
                return null
            }
            if (Relay.due(s, version.raw, Relay.notedOf(db, s, version.raw)) == null) {
                sheetKept = true
                return "done" to Words.text("up_to_date").replace("{held}", holds(version.raw))
            }
            val relaid = Relay.onto(db, parts.store.libraryDir, overrides, listOf(s.id))
            relaid.failed[s.id]?.let { return fail(Words.text("relay_failed")) }
            val now = Kept.keptFiles(db, s.id).first { it.name == Versions.SHEET_FILE_NAMES[1] }
            sheetKept = true
            return "done" to holds(Versions.get(db, now.versionId)!!.raw)
        }

        /** run.py's `_generate` past the models and `_keep`: the sheet laid out from what was heard, over the song's
         * lyrics now, kept under the song's one auto version, the song found, its info.json, then its
         * `autochords_mtime` last; the chords stage's end. */
        private fun keepSheet(db: Db, heard: Heard, audio: File): Pair<String, String> {
            val s = again(db)
            stillOurs(db, s)
            val lyrics = lyricsFromJson(s.lyricsJson)
            val maker = Maker(MADE_ON, db.kvGet(SYNC_ID)?.ifEmpty { null }, names(), chords.runtime,
                              store.givenName(db, s), sha16(audio))
            val made = SheetHalf.make(s, lyrics, heard)
            val raw = SheetHalf.raw(s, lyrics, made, maker = maker)
            db.savepoint("audio_sheet") {
                val current = autoVersionOf(db, s.id)
                val versionId = Versions.upsert(db, PROVIDER, current ?: s.id.toString(), s.id, "sheet", "auto", 0.0, 0,
                                                1, null, "file://" + audio.absolutePath, raw, stamp)
                Kept.keepFile(db, parts.store, s, versionId, Versions.SHEET_FILE_NAMES[1],
                              made.text.toByteArray(Charsets.UTF_8), 1, stamp)
                db.execute("DELETE FROM versions WHERE song_id = ? AND provider = ? AND id != ? AND NOT EXISTS " +
                               "(SELECT 1 FROM files f WHERE f.version_id = versions.id)", s.id, PROVIDER, versionId)
                Versions.refreshStatus(db, s.id, ignored = false, now = stamp)
            }
            sheetKept = true
            val info = try {
                InfoJson.write(db, parts.store.libraryDir, Songs.byId(db, s.id) ?: s)
                null
            } catch (e: Exception) {  // the sheet is kept: said so, and made of this audio (no hearing again)
                if (e is CancellationException) throw e
                e.message ?: e.javaClass.simpleName
            }
            Versions.updateSong(db, s.id, mapOf("autochords_mtime" to s.audioMtime), stamp)
            again(db)
            info?.let { return fail(INFO_FAILED.replace("{held}", holds(raw)).replace("{why}", it)) }
            return "done" to holds(raw)
        }

        /** versions.auto_version_of: the tab id of the song's one auto version, the one a kept file names first. */
        private fun autoVersionOf(db: Db, songId: Long): String? =
            db.one("SELECT tab_id FROM versions v WHERE song_id = ? AND provider = ? ORDER BY EXISTS (SELECT 1 FROM " +
                       "files f WHERE f.version_id = v.id) DESC, id LIMIT 1", songId, PROVIDER) { it.text(0) }

        // --- the pages --------------------------------------------------------------------------------------------

        private fun pdf(): Pair<String, String> {
            if (!sheetKept) return "skipped" to Words.text("no_sheet")
            if (parts.pages === SongPages.NONE) return "skipped" to LookupWords.NO_PDFS
            val id = song!!.id
            val stats = parts.database.writeBlocking { db -> parts.pages.render(db, listOf(id), null) }
            val failed = stats.failed[id] ?: stats.failed.values.firstOrNull()
            if (failed != null) return "failed" to failed
            return "done" to if (stats.written > 0) LookupWords.PAGES_MADE else LookupWords.UP_TO_DATE
        }
    }

    /** audio_sheet.py's, transcript.py's, youtube_sheet.py's, staged.py's and commands/audio.py's words and run.py's
     * STEPS, from data/caracole/library/audio_sheet.json (tests/test_conformance_audio_sheet.py writes it from the
     * modules). */
    internal object Words {
        private val data: JsonObject by lazy { Json.parseToJsonElement(caracoleResource(DATA)).jsonObject }
        private val words: JsonObject by lazy { data.getValue("words").jsonObject }

        val stages: List<Pair<String, String>> by lazy {
            data.getValue("stages").jsonArray.map { it.jsonArray[0].jsonPrimitive.content to it.jsonArray[1].jsonPrimitive.content }
        }
        val steps: List<String> by lazy { data.getValue("steps").jsonArray.map { it.jsonPrimitive.content } }
        val sitesAnswered: Set<String> by lazy {
            data.getValue("sites_answered").jsonArray.map { it.jsonPrimitive.content }.toSet()
        }
        val holds: Map<String, String> by lazy {
            data.getValue("holds").jsonObject.mapValues { it.value.jsonPrimitive.content }
        }

        fun text(name: String): String = words.getValue(name).jsonPrimitive.content
    }

    companion object {
        const val COMMAND = "audio"
        const val DATA = "caracole/library/audio_sheet.json"
        private val KNOWN = setOf("--upload", "--song", "--progress")
        private const val PROVIDER = "auto"
        private const val SYNC_ID = "sync:id"

        /** sheet.Maker's side, an auto sheet's `raw["made_on"]` made here. */
        const val MADE_ON = "phone"

        /** audio_sheet.py's STAGES, its job's (name, label). */
        val STAGES: List<Pair<String, String>> get() = Words.stages

        /** The phone's own words, where the computer's have no case. */
        const val ON_THE_PHONE = "caracole audio on the phone takes --upload=ID and --song=\"ARTIST - TITLE\""
        const val NOT_DOWNLOADED = "the chord models aren't downloaded (Settings › Chords from audio)"
        const val UNREADABLE = "audio the phone can't read: "
        const val AUDIO_CHANGED = "{display}: its audio changed while its chords were worked out"
        const val INFO_FAILED = "the sheet was kept ({held}), but its info.json couldn't be written: {why}"

        /** Why this phone makes no sheet from an audio file now, or null: the one answer for the job and the audio
         * routes (server.audio's `why`). No [chords] (the release, nothing wired): [LibraryPage.AUDIO_PROBLEM]; the
         * models not installed ([modelsReady], ModelsRunner.ready's answer): [NOT_DOWNLOADED], the design's §8.1 words;
         * else the chords' own reason ([ChordModels.ready]: "chords from audio need Android 13 or later", …). */
        fun problemOf(chords: ChordModels?, modelsReady: String?): String? = when {
            chords == null -> LibraryPage.AUDIO_PROBLEM
            modelsReady != null -> NOT_DOWNLOADED
            else -> chords.ready()
        }

        /** youtube_sheet.holds: what the auto sheet's version (its [raw]) says the sheet holds. */
        fun holds(raw: JsonObject): String {
            fun text(member: String) = (raw[member] as? JsonPrimitive)?.takeIf { it.isString }?.content
            val nothing = raw["heard_nothing"].let { it is JsonPrimitive && !it.isString && it.content == "true" }
            val used = when {
                text("lyrics_source") == SheetHalf.LYRICS_SOURCE -> "transcript"
                nothing && text("lyrics") == "none" -> if (text("not_sung_by") == "you") "said" else "silent"
                else -> (raw["lyrics"] as? JsonPrimitive)?.content ?: "None"  // str(raw.get("lyrics"))
            }
            return Words.holds[used] ?: "chords"
        }

        /** audio.sha16: the first 16 hex digits of the file's SHA-256, read streamed. */
        fun sha16(file: File): String {
            val digest = MessageDigest.getInstance("SHA-256")
            file.inputStream().use { input ->
                val buffer = ByteArray(1 shl 16)
                while (true) {
                    val n = input.read(buffer)
                    if (n < 0) break
                    digest.update(buffer, 0, n)
                }
            }
            val hex = "0123456789abcdef"
            return digest.digest().take(8).joinToString("") { b -> "${hex[(b.toInt() shr 4) and 15]}${hex[b.toInt() and 15]}" }
        }
    }
}
