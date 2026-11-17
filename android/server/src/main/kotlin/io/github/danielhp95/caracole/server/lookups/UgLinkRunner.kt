package io.github.danielhp95.caracole.server.lookups

import io.github.danielhp95.caracole.core.lookup.sites.UgLinkCommands
import io.github.danielhp95.caracole.core.py.PyStr
import io.github.danielhp95.caracole.core.ug.UgUrls
import io.github.danielhp95.caracole.server.PhoneParts
import io.github.danielhp95.caracole.server.jobs.CommandExit
import io.github.danielhp95.caracole.server.jobs.CommandRunner
import io.github.danielhp95.caracole.server.jobs.JobContext
import java.io.File

/**
 * `caracole ug --link=URL [--progress]` on the phone (commands/ug.py): a UG link pasted into the library page's search
 * box read now, a lookup command ([UgLinkCommands]) run in one `database.writeBlocking` through LookupJobs.context at
 * the lookup pace, its stages the job's with `--progress`, its last line said. A command line with no link exits 2 as
 * typer refuses it, and one that names no UG tab or artist page as the command does; overrides.toml that can't be read
 * exits 2, as `load_ovr`.
 */
class UgLinkRunner(val parts: PhoneParts) : CommandRunner {
    override suspend fun run(args: List<String>, context: JobContext) {
        val line = LookupJobs.line(args, setOf("--link"))
        val o = line.options
        for (name in o.keys) {
            if (name !in KNOWN) throw CommandExit(2, "No such option: $name")
        }
        val url = o["--link"] ?: throw CommandExit(2, "Missing option '--link'.")
        val link = UgUrls.readLink(url)
            ?: throw CommandExit(2, "--link: not an Ultimate Guitar tab's or artist's page: ${PyStr.repr(url)}")
        val now = LookupJobs.now(parts)
        val config = parts.config()
        parts.database.writeBlocking { db ->
            val (c, ask) = LookupJobs.context(parts, db, args, context, now)
            val said = try {
                UgLinkCommands.link(c, config, File(parts.stateDir, "cache"), { LookupJobs.overrides(db) }, link,
                                    progress = "--progress" in o)
            } finally {
                ask.close()
            }
            context.say(said)
        }
    }

    private companion object {
        val KNOWN = setOf("--link", "--progress")
    }
}
