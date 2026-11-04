package io.github.danielhp95.caracole.server.songbooks

import io.github.danielhp95.caracole.server.PhoneParts
import io.github.danielhp95.caracole.server.jobs.CommandRunner
import io.github.danielhp95.caracole.server.jobs.JobContext

/** `caracole songbook make|add|remove|move|set|rename|delete|render` on the phone: the change through Songbooks, then
 * the songbook made again (SongbookPagesImpl) and the search forgotten (lane songbook-routes). */
class SongbookRunner(val parts: PhoneParts) : CommandRunner {
    override suspend fun run(args: List<String>, context: JobContext): Unit = TODO("lane songbook-routes")
}
