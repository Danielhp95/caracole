package io.github.danielhp95.caracole.server.lookups

import io.github.danielhp95.caracole.core.db.Db
import io.github.danielhp95.caracole.core.library.OverrideUrls
import io.github.danielhp95.caracole.core.library.Overrides
import io.github.danielhp95.caracole.core.library.OverrideWriters
import io.github.danielhp95.caracole.core.library.OverridesError
import io.github.danielhp95.caracole.core.lookup.LookupRequest
import io.github.danielhp95.caracole.core.lookup.LookupWords
import io.github.danielhp95.caracole.core.lookup.SiteStages
import io.github.danielhp95.caracole.core.lookup.sites.VersionsCommands
import io.github.danielhp95.caracole.core.py.Py
import io.github.danielhp95.caracole.core.py.PyStr
import io.github.danielhp95.caracole.core.ug.SheetVersions
import io.github.danielhp95.caracole.server.PhoneParts
import io.github.danielhp95.caracole.server.jobs.CommandExit
import io.github.danielhp95.caracole.server.jobs.CommandRunner
import io.github.danielhp95.caracole.server.jobs.JobContext

/**
 * `caracole versions --keep`, `--keep-more`, `--choose` and `--clear` on the phone (commands/versions.py and
 * versions_cmd.py), each one song's, `-- ARTIST TITLE`:
 *
 * - `--keep=TAB` and `--keep-more`: the `song` stage begun and the song found (`_common.song_named`), then
 *   [VersionsCommands.keep] or [VersionsCommands.keepMore] (lane ug-fetch-artist's) in one `database.writeBlocking`,
 *   through a lookup command's context (LookupJobs.context: the lookup pace, the command's progress lines its job's
 *   events), its last line said. The command says versions_cmd.py's events from `{"song": …}` on, and its `pdf` and
 *   `pages` running events where versions_cmd.py makes the song's pages (a version kept: pdf, then pages; any other
 *   outcome past its refusals: pages alone); at each the runner makes them (the pdf stage's SongPages, skipped with
 *   get.py's NO_PDFS while milestone 5's are none; the library page) and ends the stage in the phone's words
 *   (LookupJobs.CommandLines);
 * - `--choose=TAB`: `caracole get --tab` at the version's own address (a version of the song UG still has, not under
 *   `[block]`);
 * - `--clear`: the song's chords pins taken out of `[pin]` (OverrideWriters.removePin), then `caracole get`.
 *
 * The list (no option) isn't on the phone, whose versions are its pages' and the library page's. [readOverrides] and
 * [stages] stand in for the phone's overrides and its sites' stages, a test's.
 */
class VersionsRunner(val parts: PhoneParts, private val readOverrides: (Db) -> Overrides = Overrides::read,
                     private val stages: SiteStages = SiteStages.ALL) : CommandRunner {
    override suspend fun run(args: List<String>, context: JobContext) {
        val line = LookupJobs.line(args, setOf("--keep", "--choose"))
        val o = line.options
        val keep = o["--keep"]
        val choose = o["--choose"]
        val keepMore = "--keep-more" in o
        val clear = "--clear" in o
        if (listOf(keep != null, choose != null, keepMore, clear).count { it } > 1) {
            throw CommandExit(2, "caracole versions takes one of --keep, --keep-more, --choose and --clear")
        }
        val display = display(line.words)
        when {
            keep != null -> keep(display, tab(keep, "--keep"), args, context)
            keepMore -> keep(display, null, args, context)
            choose != null -> choose(display, tab(choose, "--choose"), context)
            clear -> clear(display, context)
            else -> throw CommandExit(2, "caracole versions lists a song's versions on the computer: on the phone, " +
                                         "give one of --keep, --keep-more, --choose and --clear")
        }
    }

    /** commands/versions.py's `_artist_title`: "Artist - Title", or ARTIST TITLE. */
    private fun display(words: List<String>): String {
        val (artist, title) = when (words.size) {
            1 -> words[0].indexOf(" - ").let { at ->
                if (at < 0) "" to "" else words[0].substring(0, at) to words[0].substring(at + 3)
            }
            2 -> words[0] to words[1]
            else -> "" to ""
        }
        if (Py.strip(artist).isEmpty() || Py.strip(title).isEmpty()) {
            throw CommandExit(2, "caracole versions takes a song as \"Artist - Title\", or as ARTIST TITLE, not " +
                                 PyStr.repr(words.joinToString(" ")))
        }
        return "${Py.strip(artist)} - ${Py.strip(title)}"
    }

    /** commands/versions.py's `_tab`. */
    private fun tab(text: String, option: String): Long = try {
        OverrideUrls.tabIdFromUrl(text)
    } catch (e: OverridesError) {
        throw CommandExit(2, "$option: ${e.message}")
    }

    /** `--keep` ([tab]) or `--keep-more` (no tab). */
    private fun keep(display: String, tab: Long?, args: List<String>, context: JobContext) {
        context.stage("song", "running")
        parts.database.writeBlocking { db ->
            val overrides = LookupJobs.overrides(db, readOverrides)
            val song = LookupJobs.songNamed(parts, db, display, overrides)
            val made = if (tab != null) "the version's page made" else "the versions' pages made"
            val (c, ask) = LookupJobs.context(parts, db, args, context, LookupJobs.now(parts),
                                              pages = LookupJobs.CommandPages(parts, db, song, made))
            val said = try {
                if (tab != null) VersionsCommands.keep(c, parts.store, song, tab)
                else VersionsCommands.keepMore(c, parts.store, song)
            } finally {
                ask.close()
            }
            context.say(said)
        }
    }

    /** versions_cmd.choose: `caracole get --tab` for one of the song's versions, at its own address (UG serves a
     * slugged tab there alone). */
    private fun choose(display: String, tab: Long, context: JobContext) {
        val song = parts.database.writeBlocking { db ->
            val overrides = LookupJobs.overrides(db, readOverrides)
            val song = LookupJobs.songNamed(parts, db, display, overrides)
            val v = SheetVersions.inLibrary(db, song.id, parts.config().rank).firstOrNull { it.tabId == tab.toString() }
                ?: throw CommandExit(1, "Tab $tab isn't one of the Ultimate Guitar chords versions of ${song.display}: " +
                                        "caracole versions \"${song.display}\" lists them.")
            if (v.gone) throw CommandExit(1, "Ultimate Guitar no longer has tab $tab of ${song.display}.")
            if (tab in overrides.block) {
                throw CommandExit(1, "Tab $tab is under [block] in overrides.toml: take it out first to make it the sheet.")
            }
            song to v.url
        }
        get(LookupRequest(song.first.artist, song.first.title, tab = song.second), context)
    }

    /** versions_cmd.clear: the song's chords pins out of `[pin]`, then the song looked up again. */
    private fun clear(display: String, context: JobContext) {
        val song = parts.database.writeBlocking { db ->
            val overrides = LookupJobs.overrides(db, readOverrides)
            val song = LookupJobs.songNamed(parts, db, display, overrides)
            val pins = SheetVersions.sheetPins(db, song.id, overrides.pin[song.key].orEmpty())
            if (pins.isEmpty()) {
                context.say("No [pin] chooses the sheet of ${song.display}: caracole's pick is the sheet already.")
                return@writeBlocking null
            }
            try {
                OverrideWriters.removePin(db, song.display, pins.toSet())
            } catch (e: OverridesError) {
                throw CommandExit(1, "overrides.toml can't be written: ${e.message}")
            }
            context.say("Took ${pins.joinToString(", ") { "tab $it" }} out of [pin] in overrides.toml; caracole's pick " +
                        "is the sheet again.")
            song
        } ?: return
        get(LookupRequest(song.artist, song.title), context)
    }

    /** commands/get.py's `_get`, as GetRunner runs it. */
    private fun get(request: LookupRequest, context: JobContext) {
        val result = LookupJobs.lookUp(parts, request, context, readOverrides, stages)
        result.refused?.let { throw CommandExit(1, LookupWords.totals(result)) }
        context.say(LookupWords.totals(result))
        result.bug?.let { throw CommandExit(1, "a bug in caracole: $it") }
    }
}
