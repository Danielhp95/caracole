package io.github.danielhp95.caracole.server.lookups

import io.github.danielhp95.caracole.core.db.Db
import io.github.danielhp95.caracole.core.index.Stamps
import io.github.danielhp95.caracole.core.library.Kept
import io.github.danielhp95.caracole.core.library.Overrides
import io.github.danielhp95.caracole.core.library.OverridesError
import io.github.danielhp95.caracole.core.library.SongRow
import io.github.danielhp95.caracole.core.library.Songs
import io.github.danielhp95.caracole.core.library.Versions
import io.github.danielhp95.caracole.core.lookup.LookupWords
import io.github.danielhp95.caracole.core.lookup.SongPages
import io.github.danielhp95.caracole.core.lookup.sites.LyricsPickCommands
import io.github.danielhp95.caracole.core.lookup.sites.LyricsSearchCommands
import io.github.danielhp95.caracole.core.py.PyFormat
import io.github.danielhp95.caracole.server.PhoneParts
import io.github.danielhp95.caracole.server.jobs.CommandExit
import io.github.danielhp95.caracole.server.jobs.JobContext
import io.github.danielhp95.caracole.core.library.AudioStore
import io.github.danielhp95.caracole.core.youtube.YouTubeAudio
import io.github.danielhp95.caracole.viewer.autochords.AudioUnreadable
import io.github.danielhp95.caracole.viewer.autochords.ChordModels
import io.github.danielhp95.caracole.viewer.autochords.ChordsUnavailable
import io.github.danielhp95.caracole.viewer.autochords.Heard
import io.github.danielhp95.caracole.viewer.autochords.Relay
import java.io.File
import java.util.concurrent.CancellationException

/**
 * `caracole lyrics --song X --record SITE:ID --progress` on the phone (lyrics_pick.py's `_Pick`): a record of the
 * song's kept search made its lyrics now, a staged job of the queue's ([LyricsPickCommands.STAGES]: song, lyrics,
 * chords, pdf, pages), each said as it starts and ends, so its line, steps and outcome are the computer's:
 *
 * - `song` and `lyrics`: [LyricsPickCommands.findSong] and [LyricsPickCommands.lyrics], in one write each, the lyrics'
 *   asking the command's (LookupJobs.context, the lookup's pace);
 * - `chords`: where the song's auto sheet keeps what was heard, laid out again over the words with no model
 *   ([Relay.onto], its end youtube_sheet.py's `holds`); one another caracole made whose `heard` this side can't read,
 *   or no audio of its own, a site's sheet: skipped in lyrics_pick.py's words; a phone that hears no chords now skips
 *   it in its own words (lyrics_pick.py's PHONE_NOT_HERE and PHONE_NOT_DOWNLOADED, read from audio_sheet.json: it has no nightly
 *   run); a sheet up to date of the
 *   audio as it is, run.py's UP_TO_DATE with no model; else the phone's own audio heard by [chords] (the lookups
 *   queued meanwhile going first) and the sheet kept as AudioRunner keeps one ([AudioRunner.keepAutoSheet]), or, where that audio is the phone's
 *   download of a YouTube video (YouTubeAudio.youtubeAudio, run.py's `youtube_audio`), as the YouTube job keeps one
 *   ([AudioRunner.keepVideoSheet]: the video credited, `raw.youtube`, its address), that audio let go after the pages
 *   (§5.4);
 * - `pdf` and `pages`: the song's pages (PhoneParts.pages, PhoneRender), get.py's words for a caracole that makes no
 *   PDF, [LookupWords.LIBRARY_PAGE].
 *
 * Its last line is commands/lyrics.py `_lyrics_pick`'s ("Done in N s." once lyrics were kept, "No lyrics kept: …."
 * otherwise; a refusal, a local failure or a bug exits 1 in staged_end's words).
 */
internal class LyricsPickJob(
    private val parts: PhoneParts, private val args: List<String>, private val context: JobContext,
    private val artist: String, private val title: String, private val record: String?, private val pick: Int?,
    private val chords: ChordModels?, private val problem: () -> String?, private val names: () -> Map<String, String>,
    private val hold: (() -> Heard) -> Heard, private val store: AudioStore?,
    private val fileLength: (String) -> Double? = { null },
) {
    private val started = parts.pacing.monotonic()
    private val now = LookupJobs.now(parts)
    private val states = LinkedHashMap<String, String>()
    private val details = LinkedHashMap<String, String>()
    private var files: Map<String, String> = emptyMap()
    private var refused: String? = null
    private var failed: String? = null
    private var bug: String? = null
    private lateinit var overrides: Overrides
    private lateinit var picked: LyricsPickCommands.Picked
    private var song: SongRow? = null
    private var videoKept = false  // the chords stage kept a sheet of the audio this phone took from YouTube

    private class Stop(message: String) : Exception(message)

    fun run() {
        report("song", "running")
        try {
            overrides = try {
                parts.database.read { Overrides.read(it) }
            } catch (e: OverridesError) {
                throw Stop("Can't read overrides.toml: ${e.message}")
            }
            val found = parts.database.writeBlocking { db ->
                parts.store.ensureCurrentKeys(db)
                try {
                    LyricsPickCommands.findSong(db, artist, title, overrides, now, record, pick)
                } catch (e: LyricsPickCommands.Refused) {
                    throw Stop(e.message.orEmpty())
                }
            }
            picked = found
            song = found.song
            context.song(found.song.id, found.song.display)
            report("song", "done", LyricsPickCommands.found(found))
            for ((name, _) in LyricsPickCommands.STAGES.drop(1)) stage(name)
        } catch (e: Stop) {
            refuse(e.message.orEmpty())
        }
        end()
    }

    private fun report(name: String, state: String, detail: String = "") {
        if (context.isCancelled) throw CancellationException("the queue stopped")
        states[name] = state
        if (state != "running") details[name] = detail
        context.stage(name, state, detail)
    }

    private fun stage(name: String) {
        report(name, "running")
        val (state, detail) = try {
            when (name) {
                "lyrics" -> lyrics()
                "chords" -> chords()
                "pdf" -> pdf()
                "pages" -> ("done" to LookupWords.LIBRARY_PAGE).also { letGoVideoAudio() }
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
            "failed" to AudioRunner.Words.text("bug").replace("{error}", said)
        }
        report(name, state, detail)
        checkReadable()
    }

    private fun fail(detail: String): Pair<String, String> {
        failed = failed ?: detail
        return "failed" to detail
    }

    private fun refuse(why: String) {
        refused = why
        report("song", "failed", why)
        for ((name, _) in LyricsPickCommands.STAGES.drop(1)) {
            if ((states[name] ?: "running") == "running") report(name, "skipped", "")
        }
    }

    /** commands/lyrics.py `_lyrics_pick`'s last line through staged_end. */
    private fun end() {
        val kept = states["lyrics"] == "done"
        val stopped = refused ?: failed ?: bug?.let { "a bug in caracole ($it)" }
        if (stopped != null) {
            val prefix = if (kept) LyricsPickCommands.KEPT_FAILED_AFTER else LyricsPickCommands.NOTHING_KEPT_LINE
            throw CommandExit(1, "$prefix: ${stopped.trimEnd('.')}.")
        }
        val said = details["lyrics"].orEmpty().removeSuffix(LyricsPickCommands.NOTHING_KEPT)
        context.say(if (kept) "Done in ${PyFormat.fixed(parts.pacing.monotonic() - started, 1)} s."
                    else "${LyricsPickCommands.NOTHING_KEPT_LINE}: $said.")
    }

    /** lyrics_pick._Pick._check_readable: the sheet said readable once the lyrics were kept. */
    private fun checkReadable() {
        val s = song ?: return
        if (states["lyrics"] != "done") return
        val readable = parts.database.read { db -> readableFiles(db, s) }
        if (readable.isNotEmpty() && readable != files) {
            files = readable
            context.readable(readable, parts.pacing.monotonic() - started)
        }
    }

    private fun readableFiles(db: Db, s: SongRow): Map<String, String> {
        val kept = Kept.keptFiles(db, s.id).associateBy { it.name }
        val sheet = Versions.SHEET_FILE_NAMES.firstNotNullOfOrNull { kept[it] } ?: return emptyMap()
        val folder = parts.store.folderOf(s)
        val base = sheet.path.substringBeforeLast('/', "")
        val stem = sheet.name.substringBeforeLast('.')
        val out = linkedMapOf("sheet" to sheet.path)
        for ((name, file) in listOf("pdf" to "$stem.pdf", "viewer" to "$stem.html")) {
            if (File(folder, file).isFile) out[name] = if (base.isEmpty()) file else "$base/$file"
        }
        return out
    }

    private fun again(db: Db): SongRow {
        val was = song!!
        val now = Songs.byId(db, was.id) ?: throw Stop(AudioRunner.Words.text("left").replace("{display}", was.display)
                                                          .replace("{making}", MAKING))
        song = now
        return now
    }

    // --- the stages -----------------------------------------------------------------------------------------------

    private fun lyrics(): Pair<String, String> = parts.database.writeBlocking { db ->
        val s = again(db)
        val (c, ask) = LookupJobs.context(parts, db, args, context, now)
        val ended = try {
            LyricsPickCommands.lyrics(c, parts.config(), parts.clients().cacheDir, parts.store,
                                      LyricsPickCommands.Picked(s, picked.search, picked.row),
                                      LyricsSearchCommands.audioLength(db, s, fileLength))
        } catch (e: LyricsPickCommands.Refused) {
            throw Stop(e.message.orEmpty())
        } finally {
            ask.close()
        }
        again(db)
        overrides = LookupJobs.overrides(db)  // the record noted: Relay.onto is handed the pick's
        if (ended.failed) fail(ended.detail) else ended.state to ended.detail
    }

    private fun chords(): Pair<String, String> {
        if (states["lyrics"] != "done") return "skipped" to LyricsPickCommands.NO_NEW
        parts.database.writeBlocking { db -> relaid(db)?.also { videoKept = youtubeAudioHeld(db) } }?.let { return it }
        val why = parts.database.writeBlocking { db -> elsewhere(db) ?: whyNoChords(db) }
        if (why != null) return "skipped" to why
        val models = chords
        val problem = problem() ?: if (models == null || store == null) AudioRunner.problemOf(null, null) else null
        if (problem != null) {
            return "skipped" to if (problem == AudioRunner.NOT_DOWNLOADED) AudioRunner.Words.text("phone_not_downloaded")
                                else AudioRunner.Words.text("phone_not_here").replace("{problem}", problem)
        }
        context.yieldToQueued()  // the models take a minute: the lookups queued meanwhile go first
        parts.database.writeBlocking { db -> whyNoChords(db.also { again(it) }) }?.let { return "skipped" to it }
        parts.database.writeBlocking { db -> upToDate(db)?.also { videoKept = youtubeAudioHeld(db) } }?.let { return it }
        val audio = File(song!!.audioPath!!)
        val heard = try {
            hold {
                problem()?.let { throw ChordsUnavailable(it) }
                models!!.hear(audio, { step -> if (states["chords"] == "running") context.stage("chords", "running", step) },
                              { context.yieldToQueued() })
            }
        } catch (e: AudioUnreadable) {
            return fail(AudioRunner.UNREADABLE + (e.message ?: e.javaClass.simpleName))
        } catch (e: ChordsUnavailable) {
            return fail(e.message ?: e.javaClass.simpleName)
        }
        context.yieldToQueued()
        return parts.database.writeBlocking { db ->
            val s = again(db)
            overrides = LookupJobs.overrides(db)  // what the lookups that went first wrote: an `ignore`, say
            AudioRunner.notOurs(db, s, overrides)?.let { throw Stop(it) }
            if (s.audioPath != audio.path) throw Stop(AudioRunner.AUDIO_CHANGED.replace("{display}", s.display))
            // run.py `_generate`: audio the phone took from YouTube is kept as the YouTube job keeps its sheet.
            val video = YouTubeAudio.youtubeAudio(db, s)
            val (ended, info) = if (video != null) {
                AudioRunner.keepVideoSheet(parts, models!!, names, db, s, heard, audio, Stamps.of(now), video)
            } else {
                AudioRunner.keepAutoSheet(parts, store!!, models!!, names, db, s, heard, audio, Stamps.of(now))
            }
            videoKept = video != null
            models.forget(audio)
            again(db)
            info?.let { fail(it) } ?: ended
        }
    }

    /** Whether the song's audio is the file the phone took from YouTube: a sheet already made of it (re-laid, or up to
     * date) lets it go too, as a keep does ([letGoVideoAudio]). */
    private fun youtubeAudioHeld(db: Db): Boolean = YouTubeAudio.youtubeAudio(db, again(db)) != null

    /** The sheet kept of the audio this phone took from YouTube: that audio goes once the pages are made (the
     * design's §5.4), as YouTubeSheetRunner's `afterPages` lets it go; the song's link and its record's with it. */
    private fun letGoVideoAudio() {
        if (!videoKept) return
        parts.database.writeBlocking { db ->
            val s = Songs.byId(db, song!!.id) ?: return@writeBlocking
            YouTubeAudio.letGo(db, YouTubeAudio.folder(File(parts.stateDir, CACHE)), s, Stamps.of(now))
        }
        videoKept = false
    }

    /** run.py `_skip_reason`'s up to date: the auto sheet already made of the song's audio as it is now
     * (`autochords_mtime` its `audio_mtime`): no model runs, its end staged.py's UP_TO_DATE. A sheet whose words
     * changed was re-laid already ([relaid]), or made due at the keep (LyricsPickCommands.modelsRemake). */
    private fun upToDate(db: Db): Pair<String, String>? {
        val s = again(db)
        val auto = Kept.keptFiles(db, s.id).firstOrNull { it.name == Versions.SHEET_FILE_NAMES[1] } ?: return null
        if (s.autochordsMtime == null || s.autochordsMtime != s.audioMtime) return null
        val raw = Versions.get(db, auto.versionId)?.raw ?: return null
        return "done" to AudioRunner.Words.text("up_to_date").replace("{held}", AudioRunner.holds(raw))
    }

    /** staged.py `_relaid`: the auto sheet laid out again over the new words, where it keeps what was heard. */
    private fun relaid(db: Db): Pair<String, String>? {
        val s = again(db)
        val kept = Kept.keptFiles(db, s.id).map { it.name }
        if (Versions.SHEET_FILE_NAMES[1] !in kept || Versions.SHEET_FILE_NAMES[0] in kept) return null
        val relaid = Relay.onto(db, parts.store.libraryDir, overrides, listOf(s.id))
        if (relaid.failed.containsKey(s.id)) return fail(AudioRunner.Words.text("relay_failed"))
        if (relaid.songs.none { it.id == s.id }) return null
        val auto = Kept.keptFiles(db, again(db).id).first { it.name == Versions.SHEET_FILE_NAMES[1] }
        return "done" to AudioRunner.holds(Versions.get(db, auto.versionId)!!.raw)
    }

    /** lyrics_pick's words for an auto sheet another caracole made and no re-lay due: its `heard` unread, or its words
     * as they were (ELSEWHERE_SAME). */
    private fun elsewhere(db: Db): String? {
        val s = again(db)
        val auto = Kept.keptFiles(db, s.id).firstOrNull { it.name == Versions.SHEET_FILE_NAMES[1] } ?: return null
        val raw = Versions.get(db, auto.versionId)?.raw ?: return null
        if (!Relay.madeElsewhere(db, raw)) return null
        val reads = try {
            Heard.of(raw.getValue("heard"))
            true
        } catch (e: Exception) {
            false
        }
        return if (reads) "its auto sheet is $MADE_ELSEWHERE: $ELSEWHERE_SAME" else LyricsPickCommands.ELSEWHERE_UNREAD
    }

    /** lyrics_pick._Pick._why_no_chords. */
    private fun whyNoChords(db: Db): String? {
        val s = song!!
        if (Kept.keptFiles(db, s.id).any { it.name == Versions.SHEET_FILE_NAMES[0] }) {
            return "its sheet is a site's: no auto sheet to make again"
        }
        if (s.audioPath.isNullOrEmpty() || !File(s.audioPath).isFile) return "no audio to make an auto sheet from"
        return null
    }

    private fun pdf(): Pair<String, String> {
        if (states["lyrics"] != "done") return "skipped" to LyricsPickCommands.NO_NEW
        val s = song!!
        val sheets = parts.database.read { db -> Kept.keptFiles(db, s.id).map { it.name } }
        if (Versions.SHEET_FILE_NAMES.none { it in sheets }) return "skipped" to "no sheet"
        if (parts.pages === SongPages.NONE) return "skipped" to LookupWords.NO_PDFS
        val stats = parts.database.writeBlocking { db -> parts.pages.render(db, listOf(s.id), null) }
        stats.failed[s.id]?.let { return fail(it) }
        return "done" to if (stats.written > 0) LookupWords.PAGES_MADE else LookupWords.UP_TO_DATE
    }

    private companion object {
        const val CACHE = "cache"
        const val MAKING = "its lyrics were picked"
        const val MADE_ELSEWHERE = "made by another caracole from your audio there"
        const val ELSEWHERE_SAME = "its words are as they were, so nothing was laid out again, and no model runs on it"

    }
}
