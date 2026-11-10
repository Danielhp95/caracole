package io.github.danielhp95.caracole.server.lookups

import io.github.danielhp95.caracole.core.db.Db
import io.github.danielhp95.caracole.core.library.OverrideWriters
import io.github.danielhp95.caracole.core.library.Overrides
import io.github.danielhp95.caracole.core.library.OverridesError
import io.github.danielhp95.caracole.core.library.Songs
import io.github.danielhp95.caracole.core.lookup.RenderStats
import io.github.danielhp95.caracole.server.PhoneParts
import io.github.danielhp95.caracole.server.jobs.CommandExit
import io.github.danielhp95.caracole.server.jobs.CommandRunner
import io.github.danielhp95.caracole.server.jobs.JobContext
import io.github.danielhp95.caracole.server.routes.ExportError
import io.github.danielhp95.caracole.server.routes.Exports
import io.github.danielhp95.caracole.viewer.version.Versions

/**
 * `caracole render` on the phone (commands/render.py), which makes no PDF: the pages of every song, or of one
 * (`--song`), made again by the phone's own render (PhoneParts.pages, PhoneRender's), then the songbooks'
 * (PhoneParts.songbooks); and with `--version QUERY --mine`, Make this my version first (`_make_mine`): the version
 * the address holds on the song's export sheet (Exports.sheet, `export_version` over its own version) becomes the
 * song's `[version]` (ExportSheet.kept: kept by the key it plays in, or taken out where it plays as the song does
 * without one), written through OverrideWriters.addVersion (checked by Versions.keyVersion), and its label said
 * ("Your version of Soda Stereo - De Música Ligera: A Major, capo 0").
 *
 * Its words and exits are commands/render.py's: `--version` needs `--song` and `--mine` needs `--version` (2); a song
 * `_common.song_named` refuses (2 for a name of another shape, 1 for none or an ignored one); no sheet to make a
 * version of (1); overrides that can't be read or written (2); then "N rendered, M up to date, F failed" and the
 * songbooks' line, and 1 when a song's pages couldn't be made. `--version` without `--mine`, an export to a PDF beside
 * the sheet, is the computer's alone: on the phone, Export PDF prints the viewer (2).
 *
 * With `--song`, the version, the song's pages and the songbooks in one write, as caracole's lock holds them on the
 * computer; the version is written (its own savepoint) before the pages are made, so a page that fails keeps it.
 * Every song's ([everySong]) each in a write of its own, the lookups queued meanwhile let go first between two, as
 * render_all hands the lock over, then the songbooks in a write of theirs. vectors/web/export.jsonl's `render --mine`
 * records hold what it says and writes (ExportReplay). [readOverrides] stands in for the phone's overrides, a test's.
 */
class RenderRunner(val parts: PhoneParts, private val readOverrides: (Db) -> Overrides = Overrides::read) : CommandRunner {
    override suspend fun run(args: List<String>, context: JobContext) {
        val line = LookupJobs.line(args, setOf("--song", "--version"))
        val o = line.options
        for (name in o.keys) {
            if (name !in KNOWN) throw CommandExit(2, "No such option: $name")
        }
        if (line.words.isNotEmpty()) throw CommandExit(2, "Got unexpected extra argument (${line.words.first()})")
        val song = o["--song"]
        val version = o["--version"]
        val mine = "--mine" in o
        if (version != null && song.isNullOrEmpty()) throw CommandExit(2, "--version needs --song: the version is one song's.")
        if (mine && version == null) throw CommandExit(2, "--mine needs --version: the version to make the song's own.")
        if (version != null && !mine) throw CommandExit(2, NO_PDF)
        val (stats, books) = if (!song.isNullOrEmpty()) {
            parts.database.writeBlocking { db ->
                var overrides = LookupJobs.overrides(db, readOverrides)
                if (mine) {
                    makeMine(db, overrides, song, version!!, context)
                    overrides = LookupJobs.overrides(db, readOverrides)
                }
                val id = LookupJobs.songNamed(parts, db, song, overrides).id
                parts.pages.render(db, listOf(id), null) to parts.songbooks.render(db, null)
            }
        } else {
            val stats = everySong(context)
            stats to parts.database.writeBlocking { db -> parts.songbooks.render(db, null) }
        }
        context.say("${stats.written} rendered, ${stats.unchanged} up to date, ${stats.failed.size} failed")
        if (books.error != null) {
            context.say("Songbooks: songbooks.toml can't be read: ${books.error}")
        } else if (books.rendered > 0 || books.skipped > 0 || books.failed.isNotEmpty()) {
            context.say("Songbooks: ${books.rendered} rendered, ${books.skipped} up to date, ${books.failed.size} failed")
        }
        if (stats.failed.isNotEmpty()) throw CommandExit(1, stats.failed.values.joinToString("; "))
        if (song.isNullOrEmpty() && (books.failed.isNotEmpty() || books.error != null)) {
            throw CommandExit(1, books.error?.let { "songbooks.toml can't be read: $it" }
                ?: "songbooks not made: ${books.failed.joinToString(", ")}")
        }
    }

    /**
     * render_all over every song, as `caracole render` hands caracole's lock over between two songs
     * (`between=…hand_over`): each song's pages made in a write of its own, the lookups queued meanwhile run between
     * two songs (JobContext.yieldToQueued, holding no write), a song gone meanwhile passed over.
     */
    private fun everySong(context: JobContext): RenderStats {
        val ids = parts.database.read { db -> Songs.list(db).map { it.id } }
        var written = 0
        var unchanged = 0
        val failed = LinkedHashMap<Long, String>()
        for ((n, id) in ids.withIndex()) {
            if (n > 0) context.yieldToQueued()
            val one = parts.database.writeBlocking { db ->
                if (Songs.byId(db, id) == null) RenderStats() else parts.pages.render(db, listOf(id), null)
            }
            written += one.written
            unchanged += one.unchanged
            failed += one.failed
        }
        return RenderStats(written, unchanged, failed)
    }

    /**
     * render.py's `_make_mine`: the version [query] holds becomes the song's own, kept by the key it plays in on the
     * song's sheet (ExportSheet.entry); one that plays that sheet where the song plays without one takes the song's
     * `[version]` out instead (ExportSheet.kept). Its label said.
     */
    private fun makeMine(db: Db, overrides: Overrides, name: String, query: String, context: JobContext) {
        val song = LookupJobs.songNamed(parts, db, name, overrides)
        val (label, entry) = try {
            val sheet = Exports.sheet(db, parts.store.libraryDir, song)
            val v = Exports.version(query, sheet.own(overrides))
            sheet.label(v) to sheet.kept(v, overrides)
        } catch (e: ExportError) {
            throw CommandExit(1, "no version of ${song.display}: ${e.message}")
        }
        try {
            OverrideWriters.addVersion(db, song.display, entry, Versions::keyVersion)
        } catch (e: OverridesError) {
            throw CommandExit(2, "overrides: ${e.message}")
        }
        context.say("Your version of ${song.display}: $label")
    }

    companion object {
        /** commands/render.py's options. */
        private val KNOWN = setOf("--song", "--version", "--mine", "--force")

        /** What `--version` without `--mine` says on the phone, which makes no PDF of its own. */
        const val NO_PDF = "caracole render --version exports a PDF beside the sheet on the computer: on the phone, " +
            "the viewer's Export PDF prints the sheet, and --mine makes the version the song's own"
    }
}
