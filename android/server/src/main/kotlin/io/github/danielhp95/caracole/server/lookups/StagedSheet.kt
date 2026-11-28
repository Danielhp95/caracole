package io.github.danielhp95.caracole.server.lookups

import io.github.danielhp95.caracole.core.db.Db
import io.github.danielhp95.caracole.core.index.Stamps
import io.github.danielhp95.caracole.core.keys.Normalize
import io.github.danielhp95.caracole.core.library.Kept
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
import io.github.danielhp95.caracole.core.lookup.SongbookPages
import io.github.danielhp95.caracole.core.py.PyFormat
import io.github.danielhp95.caracole.server.PhoneParts
import io.github.danielhp95.caracole.server.jobs.CommandExit
import io.github.danielhp95.caracole.server.jobs.JobContext
import io.github.danielhp95.caracole.server.lookups.AudioRunner.Words
import io.github.danielhp95.caracole.viewer.autochords.AudioUnreadable
import io.github.danielhp95.caracole.viewer.autochords.ChordModels
import io.github.danielhp95.caracole.viewer.autochords.ChordsUnavailable
import io.github.danielhp95.caracole.viewer.autochords.Heard
import io.github.danielhp95.caracole.viewer.autochords.Maker
import io.github.danielhp95.caracole.viewer.autochords.Relay
import kotlinx.serialization.json.JsonObject
import java.io.File
import java.time.temporal.ChronoUnit
import java.util.concurrent.CancellationException

/**
 * A job of stages over one song's auto sheet made from its audio now (staged.py's `StagedRun`, as youtube_sheet.py's
 * `_Sheet` and audio_sheet.py's `_AudioSheet` share it): the stages song, audio, lyrics, vocals, words, chords, pdf and
 * pages, each said as it starts and ends; every stage but the audio the same for a sheet from an audio file the owner
 * gave ([AudioRunner]) and for one from a YouTube video ([YouTubeSheetRunner]), which says where the audio comes from
 * ([audio]), whose the song still is ([stillOursHere]), what the song stage notes ([found]), and who made the sheet
 * ([maker], [source], [video]).
 *
 * The shared stages: `song`, found by its identity key or added ([album], [duration]), refused ignored or with a
 * human sheet (and as [stillOurs] says), in one write; `lyrics`, the lookup's lyrics stage asked with the audio's
 * length (the song's line's, else [keptLength]); `vocals` and `words` skipped, as the phone hears no words; `chords`,
 * the lookups queued meanwhile first, then the song read again and still this job's, a sheet of this audio up to date
 * or laid out again over its words, else [ChordModels.hear] holding no write, yielding each second, then the sheet kept
 * with its version; `pdf` and `pages`, the song's pages. A refusal fails the song stage and skips those left; the
 * command's last line is the computer's ("No sheet made: …." with exit 1, else "Done in N s: …").
 */
internal abstract class StagedSheet(
    val parts: PhoneParts, val chords: ChordModels, val context: JobContext, val artist: String, val title: String,
    val names: () -> Map<String, String>, val readOverrides: (Db) -> Overrides, val stages: SiteStages,
    val hold: (() -> Heard) -> Heard, val problem: () -> String?,
) {
    protected val started = parts.pacing.monotonic()
    protected val now = parts.pacing.clock().truncatedTo(ChronoUnit.SECONDS)
    protected val stamp = Stamps.of(now)
    protected val display = "$artist - $title"
    protected val states = LinkedHashMap<String, String>()
    private val told = HashMap<String, String>()
    protected val requests = LinkedHashMap<String, Int>()
    private var files: Map<String, String> = emptyMap()
    private var refused: String? = null
    private var failed: String? = null
    private var bug: String? = null
    protected lateinit var overrides: Overrides
    protected var song: SongRow? = null
    protected var kept: File? = null  // the file the audio stage kept as the song's audio
    protected var sheetKept = false  // the chords stage left the song a sheet of this audio, whatever it said after
    protected var keptLength: Double? = null

    /** The job refused, said in the song stage, the stages not ended skipped (staged.py `_refuse`). */
    class Stop(message: String) : Exception(message)

    /** The stages' names, in order (each job's STAGES). */
    protected abstract val stageNames: List<String>

    /** The song's album and length, given a song this job adds. */
    protected open val album: String? get() = null
    protected open val duration: Double? get() = null

    /** The audio stage: the song's audio, from where the job takes it. */
    protected abstract fun audio(): Pair<String, String>

    /** The job's own rule of whose the song still is, after `_unsheeted`: a [Stop] to end the job there. */
    protected open fun stillOursHere(db: Db, s: SongRow) {}

    /** What the song stage says once [s] is found ([said]: in the book, or added), in the job's write; a [Stop] to
     * refuse it. */
    protected open fun found(db: Db, s: SongRow, said: String): String = said

    /** The sheet's maker, the credit line after the song's name, and the video, as run.py's `_keep` keeps them. */
    protected abstract fun maker(db: Db, s: SongRow, audio: File): Maker
    protected open fun source(): String? = null
    protected open fun video(): JsonObject? = null

    /** The auto version's address: the audio's file (run.py's `_keep`), or the video's. */
    protected open fun versionUrl(audio: File): String = "file://" + audio.absolutePath

    /** Whether the song's auto sheet was made of the audio the audio stage gave (run.py `_skip_reason`: its
     * `autochords_mtime` the audio's `audio_mtime`); a job may know it otherwise (YouTubeSheetRunner: a sheet of the
     * very video asked for, whose audio the phone let go). */
    protected open fun madeOfThisAudio(s: SongRow): Boolean = s.autochordsMtime != null && s.autochordsMtime == s.audioMtime

    /** After the pages stage, the sheet kept or not ([sheetKept]), in no write. */
    protected open fun afterPages() {}

    /** The requests the job sent, said in its last line: "2 LRCLIB requests". */
    protected open fun sent(provider: String, n: Int): String =
        "$n ${LookupWords.NAMES[provider] ?: provider} request" + if (n == 1) "" else "s"

    fun run() {
        report("song", "running")
        try {
            overrides = try {
                parts.database.read(readOverrides)
            } catch (e: OverridesError) {
                throw Stop("Can't read overrides.toml: ${e.message}")
            }
            report("song", "done", parts.database.writeBlocking(::findSong))
            for (name in stageNames.drop(1)) stage(name)
        } catch (e: Stop) {
            refuse(e.message.orEmpty())
        }
        end()
    }

    // --- reporting ----------------------------------------------------------------------------------------------------

    protected fun report(name: String, state: String, detail: String = "") {
        if (context.isCancelled) throw CancellationException("the queue stopped")
        states[name] = state
        told[name] = detail
        context.stage(name, state, detail)
    }

    /** What the running stage [name] is doing now, said once each time it changes (staged.py `_doing`). */
    protected fun doing(name: String, detail: String) {
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
                "pages" -> ("done" to LookupWords.LIBRARY_PAGE).also { afterPages() }
                else -> error("no stage $name")
            }
        } catch (e: Stop) {
            throw e
        } catch (e: CancellationException) {
            throw e
        } catch (e: InterruptedException) {
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
    protected fun fail(detail: String): Pair<String, String> {
        failed = failed ?: detail
        return "failed" to detail
    }

    private fun refuse(why: String) {
        refused = why
        report("song", "failed", why)
        for (name in stageNames.drop(1)) {
            if ((states[name] ?: "running") == "running") report(name, "skipped", "")
        }
    }

    /** The command's last line, and its exit status (commands/_common.staged_end). */
    private fun end() {
        val stopped = refused ?: failed ?: bug?.let { "a bug in caracole ($it)" }
        if (stopped != null) throw CommandExit(1, "${Words.text("refused")}: ${stopped.trimEnd('.')}.")
        val sent = requests.filterValues { it != 0 }.entries.joinToString(", ") { (p, n) -> sent(p, n) }
        val seconds = PyFormat.fixed(parts.pacing.monotonic() - started, 1)
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

    // --- the song -----------------------------------------------------------------------------------------------------

    /** youtube_sheet.py `_the_song` and audio_sheet.py `find_song`: the song found or added, then still ours. */
    private fun findSong(db: Db): String {
        parts.store.ensureCurrentKeys(db)
        val key = Normalize.identityKey(artist, title)
        if (key in overrides.ignore) throw Stop(Words.text("ignored").replace("{display}", display))
        var said = Words.text("in_book")
        val found = Songs.byKey(db, key) ?: run {
            said = LookupWords.ADDED
            val ms = duration?.takeIf { it >= 1 }?.let { PyFormat.roundHalfEven(it * 1000) }
            try {
                parts.store.add(db, artist, title, album, ms, now = stamp)
            } catch (e: IllegalArgumentException) {
                throw Stop("Can't add this song: ${e.message}")
            }
        }
        stillOurs(db, found)
        said = found(db, found, said)
        song = found
        context.song(found.id, found.display)
        return said
    }

    /** The song read again; gone (removed, or merged into another), the job ends there (staged.py `_song_again`). */
    protected fun again(db: Db): SongRow {
        val was = song!!
        val now = Songs.byId(db, was.id)
            ?: throw Stop(Words.text("left").replace("{display}", was.display).replace("{making}", Words.text("making")))
        song = now
        return now
    }

    /** `_still_ours`: `_unsheeted` (not ignored, with no human sheet); then the job's own rule ([stillOursHere]);
     * and, once the audio stage kept a file, the song's audio still that file (the design's §3.2). */
    private fun stillOurs(db: Db, s: SongRow) {
        AudioRunner.notOurs(db, s, overrides)?.let { throw Stop(it) }
        stillOursHere(db, s)
        val kept = kept ?: return
        if (s.audioPath != kept.path) throw Stop(AudioRunner.AUDIO_CHANGED.replace("{display}", s.display))
    }

    /** The song and the overrides read again after the lookups went first (staged.py `_after_a_lookup`), then
     * still ours. */
    protected fun readAgain(): SongRow = parts.database.writeBlocking { db ->
        overrides = try {
            readOverrides(db)
        } catch (e: OverridesError) {
            overrides
        }
        again(db).also { stillOurs(db, it) }
    }

    // --- the lyrics ---------------------------------------------------------------------------------------------------

    /** The lookup's lyrics stage over the song, asked with the audio's length (lyrics_search.audio_length: the
     * song's line's, else [keptLength], once the audio stage kept the audio): at the lookup pace for a job asked for
     * now; at the bulk pace, under a run of its own ([AUTO_RUN], the time and the song's id), for an automatic one
     * ([JobContext.automatic], the design's §5.3), so never within `lookup_per_hour`. */
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
                            SongbookPages.NONE, parts.alerts, LookupRequest(artist, title), progress, parts.pacing, stages,
                            readOverrides)
        val bulk = if (context.automatic) "$AUTO_RUN$stamp:${current.id}" else null  // nobody asked for it now
        val result = parts.database.writeBlocking { db -> lookup.lyrics(db, current.id, length, bulk) }
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

    // --- the chords ---------------------------------------------------------------------------------------------------

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
            return fail(AudioRunner.UNREADABLE + (e.message ?: e.javaClass.simpleName))
        } catch (e: ChordsUnavailable) {
            return fail(e.message ?: e.javaClass.simpleName)
        }
        heard(heard)
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
            // leaves it, for Try again to lay the sheet out with no hearing. A job refused after a whole hearing
            // (`stillOurs`: the song got a human sheet meanwhile) keeps no sheet and never calls `forget`: the
            // folder waits for the day-old sweep, and MlChordModels' entry of it stays for the process's life.
            if (sheetKept) chords.forget(audio)
        }
    }

    /** What the models heard, once they did, before the sheet is laid out. */
    protected open fun heard(heard: Heard) {}

    /** The sheet already made of this audio here: up to date, or laid out again over its words where they changed
     * (Relay.onto); null where the models are to hear it (no auto sheet, one of other audio, one another caracole
     * made: the job is the owner's ask, this side its maker). */
    private fun upToDate(db: Db): Pair<String, String>? {
        val s = again(db)
        val auto = Kept.keptFiles(db, s.id).firstOrNull { it.name == Versions.SHEET_FILE_NAMES[1] } ?: return null
        val version = Versions.get(db, auto.versionId) ?: return null
        if (!madeOfThisAudio(s) || Relay.madeElsewhere(db, version.raw)) {
            return null
        }
        if (Relay.due(s, version.raw, Relay.notedOf(db, s, version.raw)) == null) {
            sheetKept = true
            return "done" to Words.text("up_to_date").replace("{held}", AudioRunner.holds(version.raw))
        }
        val relaid = Relay.onto(db, parts.store.libraryDir, overrides, listOf(s.id))
        relaid.failed[s.id]?.let { return fail(Words.text("relay_failed")) }
        val now = Kept.keptFiles(db, s.id).first { it.name == Versions.SHEET_FILE_NAMES[1] }
        sheetKept = true
        return "done" to AudioRunner.holds(Versions.get(db, now.versionId)!!.raw)
    }

    /** run.py's `_generate` past the models and `_keep` (AudioRunner.keepAutoSheet, with this job's [maker],
     * [versionUrl], [source] and [video]): the sheet laid out from what was heard, over the song's lyrics now, kept
     * under the song's one auto version, the song found, its info.json, then its `autochords_mtime` last; the chords
     * stage's end. */
    private fun keepSheet(db: Db, heard: Heard, audio: File): Pair<String, String> {
        val s = again(db)
        stillOurs(db, s)
        val (ended, info) = AudioRunner.keepAutoSheet(parts, db, s, heard, stamp, maker(db, s, audio), versionUrl(audio),
                                                      source(), video())
        // Kept only now, the song's `autochords_mtime` its audio's (keepAutoSheet's last write): a write before it that
        // fails leaves the checkpoints (the chords stage's `finally`), for Try again, which finds no sheet of this audio
        // yet.
        sheetKept = true
        again(db)
        return info?.let { fail(it) } ?: ended
    }

    // --- the pages ----------------------------------------------------------------------------------------------------

    private fun pdf(): Pair<String, String> {
        if (!sheetKept) return "skipped" to Words.text("no_sheet")
        if (parts.pages === SongPages.NONE) return "skipped" to LookupWords.NO_PDFS
        val id = song!!.id
        val stats = parts.database.writeBlocking { db -> parts.pages.render(db, listOf(id), null) }
        val failed = stats.failed[id] ?: stats.failed.values.firstOrNull()
        if (failed != null) return "failed" to failed
        return "done" to if (stats.written > 0) LookupWords.PAGES_MADE else LookupWords.UP_TO_DATE
    }

    companion object {
        const val AUTO_PROVIDER = "auto"
        const val SYNC_ID = "sync:id"

        /** The run an automatic job's lyrics are asked under, the time and the song's id after it (never `lookup:`). */
        const val AUTO_RUN = "youtube-auto:"
    }
}
