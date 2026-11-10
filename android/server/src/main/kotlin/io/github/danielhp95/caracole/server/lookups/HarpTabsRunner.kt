package io.github.danielhp95.caracole.server.lookups

import io.github.danielhp95.caracole.core.lookup.sites.HarpTabsCommands
import io.github.danielhp95.caracole.server.PhoneParts
import io.github.danielhp95.caracole.server.jobs.CommandExit
import io.github.danielhp95.caracole.server.jobs.CommandRunner
import io.github.danielhp95.caracole.server.jobs.JobContext

/**
 * `caracole harptabs --artist=NAME` on the phone (commands/lyrics.py): one artist's page read now, at the lookup pace,
 * a lookup command (lane harptabs' [HarpTabsCommands]) run in one `database.writeBlocking` through LookupJobs.context,
 * the name or address with its whitespace folded, its last line said. Its index (`--index`) and its bulk pass aren't
 * on the phone.
 */
class HarpTabsRunner(val parts: PhoneParts) : CommandRunner {
    override suspend fun run(args: List<String>, context: JobContext) {
        val line = LookupJobs.line(args, setOf("--artist", "--budget"))
        val o = line.options
        val artist = o["--artist"]
        if ("--index" in o && artist != null) {
            throw CommandExit(2, "--index reads every artist's page and --artist one artist's: give one of them")
        }
        if ("--budget" in o && "--index" !in o) throw CommandExit(2, "--budget goes with --index")
        if (artist == null) {
            throw CommandExit(2, "caracole harptabs reads harptabs.com's index and tabs on the computer: on the phone, " +
                                 "give --artist")
        }
        parts.database.writeBlocking { db ->
            val (c, ask) = LookupJobs.context(parts, db, args, context, LookupJobs.now(parts))
            val said = try {
                HarpTabsCommands.artist(c, LookupJobs.folded(artist))
            } finally {
                ask.close()
            }
            context.say(said)
        }
    }
}
