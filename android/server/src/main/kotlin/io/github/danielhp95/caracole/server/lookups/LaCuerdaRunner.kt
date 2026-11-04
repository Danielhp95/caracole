package io.github.danielhp95.caracole.server.lookups

import io.github.danielhp95.caracole.core.lookup.LookupWords
import io.github.danielhp95.caracole.core.lookup.sites.LaCuerdaCommands
import io.github.danielhp95.caracole.server.PhoneParts
import io.github.danielhp95.caracole.server.jobs.CommandExit
import io.github.danielhp95.caracole.server.jobs.CommandRunner
import io.github.danielhp95.caracole.server.jobs.JobContext

/**
 * `caracole lacuerda --artist=NAME` and `--search=QUERY [--progress] [--auto]` on the phone (commands/lyrics.py),
 * each a lookup command (lane lacuerda-sheets' [LaCuerdaCommands]) run in one `database.writeBlocking` through
 * LookupJobs.context, its name or query with its whitespace folded, its last line said: an artist's page at the lookup
 * pace, and LaCuerda's own search, whose run is `lookup:lacuerda-search:<time>` (LookupWords.searchRunId), as its
 * hour's searches are counted. Its listings (`--index`) and its bulk pass aren't on the phone.
 */
class LaCuerdaRunner(val parts: PhoneParts) : CommandRunner {
    override suspend fun run(args: List<String>, context: JobContext) {
        val line = LookupJobs.line(args, setOf("--artist", "--search"))
        val o = line.options
        val artist = o["--artist"]
        val search = o["--search"]
        if (listOf("--index" in o, artist != null, search != null).count { it } > 1) {
            throw CommandExit(2, "--index reads every artist's listing, --artist one artist's page and --search one " +
                                 "query of LaCuerda's search: give one of them")
        }
        if (("--auto" in o || "--progress" in o) && search == null) {
            throw CommandExit(2, "--auto and --progress go with --search")
        }
        if (artist == null && search == null) {
            throw CommandExit(2, "caracole lacuerda reads LaCuerda's listings and sheets on the computer: on the phone, " +
                                 "give --artist or --search")
        }
        val now = LookupJobs.now(parts)
        parts.database.writeBlocking { db ->
            val run = LookupWords.lookupRunOf(now, search = search != null)
            val (c, ask) = LookupJobs.context(parts, db, args, context, now, run)
            val said = try {
                if (search != null) LaCuerdaCommands.search(c, LookupJobs.folded(search), auto = "--auto" in o)
                else LaCuerdaCommands.artist(c, LookupJobs.folded(artist!!), first = null)
            } finally {
                ask.close()
            }
            context.say(said)
        }
    }
}
