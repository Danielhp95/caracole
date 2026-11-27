package io.github.danielhp95.caracole.server.lookups

import io.github.danielhp95.caracole.core.library.AudioStore
import io.github.danielhp95.caracole.core.library.Songs
import io.github.danielhp95.caracole.core.lookup.sites.LyricsSearchCommands
import io.github.danielhp95.caracole.core.py.PyStr
import io.github.danielhp95.caracole.server.PhoneParts
import io.github.danielhp95.caracole.server.jobs.CommandExit
import io.github.danielhp95.caracole.server.jobs.CommandRunner
import io.github.danielhp95.caracole.server.jobs.JobContext
import java.io.File

/**
 * `caracole lyrics --song "Artist - Title" --as "A - T"` on the phone (commands/lyrics.py's `_lyrics_as`): what the
 * lyrics sites list under a name typed (lane lyrics-search's [LyricsSearchCommands]), a lookup command run in one
 * `database.writeBlocking` through LookupJobs.context at the lookup's run, its lines said, its last the one the
 * Journal reads. A lookup (JobCommands.isLookup), so a long job of the phone's own lets it go first. The name typed is
 * read as the command reads it (lyrics_search.typed_name), a text that names no artist and title refused (exit 2), as
 * a song not in the library or ignored is (LookupJobs.songNamed), and the audio's length is its own audio file's
 * where its line names none ([store]'s examiner). The computer's bulk `caracole lyrics` (no --song) and its passes are
 * the nightly run's.
 */
class LyricsRunner(val parts: PhoneParts, private val store: AudioStore? = null) : CommandRunner {
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
            else -> throw CommandExit(2, "caracole lyrics ${asks.single()} isn't on the phone yet")
        }
    }

    /** music.read_audio's length of the song's own audio file, as lyrics_search.audio_length reads it: a regular
     * file alone, by the phone's examiner ([AudioStore.formatAndLength]), any failure none (a length is a hint). */
    private fun fileLength(path: String): Double? {
        val file = File(path).takeIf { it.isFile } ?: return null
        return runCatching { store?.formatAndLength(file)?.second }.getOrNull()
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
