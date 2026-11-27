package io.github.danielhp95.caracole.server.lookups

import io.github.danielhp95.caracole.core.library.AudioStore
import io.github.danielhp95.caracole.core.library.OverrideUrls
import io.github.danielhp95.caracole.core.library.OverridesError
import io.github.danielhp95.caracole.core.library.Songs
import io.github.danielhp95.caracole.core.py.Py
import io.github.danielhp95.caracole.core.lookup.sites.LyricsPickCommands
import io.github.danielhp95.caracole.core.lookup.sites.LyricsSearchCommands
import io.github.danielhp95.caracole.core.py.PyStr
import io.github.danielhp95.caracole.server.PhoneParts
import io.github.danielhp95.caracole.server.jobs.CommandExit
import io.github.danielhp95.caracole.server.jobs.CommandRunner
import io.github.danielhp95.caracole.server.jobs.JobContext
import io.github.danielhp95.caracole.viewer.autochords.ChordModels
import io.github.danielhp95.caracole.viewer.autochords.Heard
import java.io.File

/**
 * `caracole lyrics --song "Artist - Title" --as "A - T"` on the phone (commands/lyrics.py's `_lyrics_as`): what the
 * lyrics sites list under a name typed (lane lyrics-search's [LyricsSearchCommands]), a lookup command run in one
 * `database.writeBlocking` through LookupJobs.context at the lookup's run, its lines said, its last the one the
 * Journal reads. A lookup (JobCommands.isLookup), so a long job of the phone's own lets it go first. The name typed is
 * read as the command reads it (lyrics_search.typed_name), a text that names no artist and title refused (exit 2), as
 * a song not in the library or ignored is (LookupJobs.songNamed). `--record SITE:ID` (or `--pick N`) is the queue's
 * staged job of lyrics_pick.py ([LyricsPickJob]): its chords a re-lay where the auto sheet keeps what was heard, else
 * [chords] over the phone's own audio. The computer's bulk `caracole lyrics` (no --song) and its passes are the
 * nightly run's.
 */
class LyricsRunner(
    val parts: PhoneParts,
    private val chords: ChordModels? = null,
    private val store: AudioStore? = null,
    private val problem: () -> String? = { AudioRunner.problemOf(chords, null) },
    private val names: () -> Map<String, String> = { emptyMap() },
    private val hold: (() -> Heard) -> Heard = { it() },
) : CommandRunner {
    override suspend fun run(args: List<String>, context: JobContext) {
        val line = LookupJobs.line(args, setOf("--song", "--as", "--pick", "--record"))
        val o = line.options
        val asks = listOf("--as", "--pick", "--record", "--clear").filter { it in o }
        if ("--progress" in o && "--pick" !in o && "--record" !in o) {
            throw CommandExit(2, "--progress goes with --pick or --record")
        }
        val display = o["--song"]
        if (display == null && asks.isEmpty()) {
            throw CommandExit(2, "caracole lyrics asks every song's lyrics at night on the computer: on the phone, give " +
                                 "--song and one of --as, --pick, --record")
        }
        if (display == null || asks.isEmpty()) {
            throw CommandExit(2, "--song goes with one of --as, --pick, --record and --clear: caracole lyrics --song " +
                                 "\"Artist - Title\" --as \"Artist - Title\".")
        }
        if (asks.size > 1) throw CommandExit(2, "${asks.joinToString(" and ")} don't go together: give one.")
        when (asks.single()) {
            "--as" -> search(display, o.getValue("--as").orEmpty(), args, context)
            "--record", "--pick" -> pick(display, o["--record"], o["--pick"], args, context)
            else -> clear(display, context)
        }
    }

    /** music.read_audio's length of the song's own audio file, as lyrics_search.audio_length reads it: a regular
     * file alone, by the phone's examiner ([AudioStore.formatAndLength]), any failure none (a length is a hint). */
    private fun fileLength(path: String): Double? {
        val file = File(path).takeIf { it.isFile } ?: return null
        return runCatching { store?.formatAndLength(file)?.second }.getOrNull()
    }

    /** commands/lyrics.py's `_lyrics_pick`: the song's name checked, then the job of stages ([LyricsPickJob]). */
    private fun pick(display: String, record: String?, pick: String?, args: List<String>, context: JobContext) {
        try {
            OverrideUrls.overrideKey(display)
        } catch (e: OverridesError) {
            throw CommandExit(2, e.message.orEmpty())
        }
        val n = pick?.let { it.toIntOrNull()?.takeIf { v -> v >= 1 } ?: throw CommandExit(2, "--pick takes a row's number, 1 or more") }
        val artist = Py.strip(display.substringBefore(" - "))
        val title = Py.strip(display.substringAfter(" - "))
        LyricsPickJob(parts, args, context, artist, title, record, n, chords, problem, names, hold, store, ::fileLength).run()
    }

    /** commands/lyrics.py's `_lyrics_clear`: the record picked taken out (LyricsPickCommands.clearPick), with no
     * request; then the song's pages; exit 1 for a song with no record picked. */
    private fun clear(display: String, context: JobContext) {
        try {
            OverrideUrls.overrideKey(display)
        } catch (e: OverridesError) {
            throw CommandExit(2, e.message.orEmpty())
        }
        val said = parts.database.writeBlocking { db ->
            val overrides = LookupJobs.overrides(db)
            val song = LookupJobs.songNamed(parts, db, display, overrides)
            val said = LyricsPickCommands.clearPick(db, parts.store, song, overrides, LookupJobs.now(parts))
                ?: throw CommandExit(1, "${song.display} ${LyricsPickCommands.NOTHING_TO_CLEAR}")
            parts.pages.render(db, listOf(song.id), null)
            said
        }
        context.say(said)
    }

    /** commands/lyrics.py's `_lyrics_as`: the name read, the song found, the sites asked, the lines said. */
    private fun search(display: String, typed: String, args: List<String>, context: JobContext) {
        val name = parts.database.read { db -> LyricsSearchCommands.typedName(db, typed, Songs.list(db)) }
            ?: throw CommandExit(2, "--as: expected \"Artist - Title\", got ${PyStr.repr(typed)}")
        val now = LookupJobs.now(parts)
        parts.database.writeBlocking { db ->
            val overrides = LookupJobs.overrides(db)
            val song = LookupJobs.songNamed(parts, db, display, overrides)
            val (c, ask) = LookupJobs.context(parts, db, args, context, now)
            val lines = try {
                LyricsSearchCommands.lines(song, name, LyricsSearchCommands.search(c, song, name, parts.config(),
                                                                                  ::fileLength))
            } finally {
                ask.close()
            }
            for (said in lines) c.say(said)
        }
    }
}
