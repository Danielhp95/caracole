package io.github.danielhp95.caracole.server.lookups

import io.github.danielhp95.caracole.core.db.Db
import io.github.danielhp95.caracole.core.json.PyJson
import io.github.danielhp95.caracole.core.library.OverrideUrls
import io.github.danielhp95.caracole.core.library.Overrides
import io.github.danielhp95.caracole.core.library.OverridesError
import io.github.danielhp95.caracole.core.library.SongRow
import io.github.danielhp95.caracole.core.library.Songs
import io.github.danielhp95.caracole.core.lookup.CommandContext
import io.github.danielhp95.caracole.core.lookup.InteractiveAsk
import io.github.danielhp95.caracole.core.lookup.Lookup
import io.github.danielhp95.caracole.core.lookup.LookupLines
import io.github.danielhp95.caracole.core.lookup.LookupRequest
import io.github.danielhp95.caracole.core.lookup.LookupResult
import io.github.danielhp95.caracole.core.lookup.LookupWords
import io.github.danielhp95.caracole.core.lookup.Pace
import io.github.danielhp95.caracole.core.lookup.Progress
import io.github.danielhp95.caracole.core.lookup.SiteStages
import io.github.danielhp95.caracole.core.lookup.SongPages
import io.github.danielhp95.caracole.core.names.SongNames
import io.github.danielhp95.caracole.core.py.Py
import io.github.danielhp95.caracole.core.py.PyStr
import io.github.danielhp95.caracole.server.PhoneParts
import io.github.danielhp95.caracole.server.jobs.CommandExit
import io.github.danielhp95.caracole.server.jobs.CommandRunner
import io.github.danielhp95.caracole.server.jobs.JobCommands
import io.github.danielhp95.caracole.server.jobs.JobContext
import io.github.danielhp95.caracole.server.routes.library.SongForm
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.doubleOrNull
import kotlinx.serialization.json.longOrNull
import java.time.Instant
import java.time.temporal.ChronoUnit
import java.util.concurrent.CancellationException

/**
 * `caracole get --progress -- ARTIST TITLE` on the phone (commands/get.py): one song looked up now, [Lookup] run in
 * one `database.writeBlocking` on the queue's worker, in autocommit, its stages its job's ([JobContext.stage]) and its
 * lines `caracole get`'s ([LookupLines], then [LookupWords.totals]). Its options are get.py's (`--album`, `--duration`,
 * `--ug`, `--tab`, `--lacuerda`, `--harptabs`, `--gametabs`, `--no-songbooks`), checked as commands/get.py checks
 * them (a usage error exits 2); a lookup refused or one a bug cut short fails its step (exit 1), a block or a spent
 * budget never. A queue that stops stops the lookup at its next stage. [readOverrides] and [stages] stand in for
 * the phone's overrides and its sites' stages, a test's.
 */
class GetRunner(val parts: PhoneParts, private val readOverrides: (Db) -> Overrides = Overrides::read,
                private val stages: SiteStages = SiteStages.ALL) : CommandRunner {
    override suspend fun run(args: List<String>, context: JobContext) {
        val request = LookupJobs.request(parts, args, context)
        val result = LookupJobs.lookUp(parts, request, context, readOverrides, stages)
        result.refused?.let { throw CommandExit(1, LookupWords.totals(result)) }
        context.say(LookupWords.totals(result))
        result.bug?.let { throw CommandExit(1, "a bug in caracole: $it") }
    }
}

/** What the lookup runners share: a command line read as typer reads it, a lookup run as a job's, the song a
 * command names, and the [CommandContext] a lookup command runs in. */
internal object LookupJobs {
    private const val SONG_SHAPE = "a song as \"Artist - Title\", or as ARTIST TITLE"

    /** A command line's options (before `--`), each `--name=value`, `--name value` or a flag, by name; and its
     * words (after `--`, or the rest). */
    class Line(val options: Map<String, String?>, val words: List<String>)

    fun line(args: List<String>, takesValue: Set<String>): Line {
        val options = LinkedHashMap<String, String?>()
        val words = ArrayList<String>()
        var i = 1  // after the command's own word
        while (i < args.size) {
            val arg = args[i]
            when {
                arg == "--" -> {
                    words += args.subList(i + 1, args.size)
                    break
                }
                arg.startsWith("--") && '=' in arg -> options[arg.substringBefore('=')] = arg.substringAfter('=')
                arg.startsWith("--") && arg in takesValue -> {
                    options[arg] = args.getOrNull(i + 1) ?: throw CommandExit(2, "Option '$arg' requires an argument.")
                    i++
                }
                arg.startsWith("--") -> options[arg] = null
                else -> words += arg
            }
            i++
        }
        return Line(options, words)
    }

    /** commands/get.py's `get`: the lookup its command line asks for, its options checked ([check]). */
    fun request(parts: PhoneParts, args: List<String>, context: JobContext): LookupRequest {
        val line = line(args, setOf("--album", "--duration", "--ug", "--tab", "--lacuerda", "--harptabs", "--gametabs"))
        val o = line.options
        for (name in o.keys) {
            if (name !in KNOWN) throw CommandExit(2, "No such option: $name")
        }
        check(o["--ug"], o["--tab"], o["--lacuerda"], o["--harptabs"], o["--gametabs"])
        val duration = o["--duration"]?.let(::duration)
        val (artist, title) = artistTitle(parts, line.words, context)
        return LookupRequest(artist, title, album = o["--album"], durationMs = duration, ug = o["--ug"], tab = o["--tab"],
                             lacuerda = o["--lacuerda"], harptabs = o["--harptabs"], gametabs = o["--gametabs"],
                             songbooks = "--no-songbooks" !in o)
    }

    private val KNOWN = setOf("--album", "--duration", "--ug", "--tab", "--lacuerda", "--harptabs", "--gametabs",
                              "--print", "--progress", "--songbooks", "--no-songbooks")

    /** commands/get.py's `_artist_title`: ARTIST TITLE as given; one text read as the pages read a query
     * (song_names.read_names, said when it isn't the text as written). */
    private fun artistTitle(parts: PhoneParts, words: List<String>, context: JobContext): Pair<String, String> {
        if (words.size == 2 && words.all { Py.strip(it).isNotEmpty() }) return Py.strip(words[0]) to Py.strip(words[1])
        val shown = PyStr.repr(words.joinToString(" "))
        if (words.size != 1) throw CommandExit(2, "caracole get takes $SONG_SHAPE, not $shown")
        val named = parts.database.read { db -> SongNames.readNames(db, words[0], Songs.list(db)) }
            ?: throw CommandExit(2, "caracole get takes $SONG_SHAPE, not $shown")
        val written = Py.split(words[0]).joinToString(" ")
        if ("${named.first} - ${named.second}" != written) context.say("Read “$written” as ${named.first} - ${named.second}.")
        return named
    }

    /** commands/get.py's `_check_pick`. */
    private fun check(ug: String?, tab: String?, lacuerda: String?, harptabs: String?, gametabs: String?) {
        if (ug != null) {
            val ref = Py.strip(ug)
            val slash = ref.indexOf('/')
            val artistKey = if (slash >= 0) ref.substring(0, slash) else ref
            val songKey = if (slash >= 0) ref.substring(slash + 1) else ""
            if (slash < 0 || artistKey.isEmpty() || songKey.isEmpty() || '/' in songKey) {
                throw CommandExit(2, "--ug takes an Ultimate Guitar song as artist-key/song-key (radiohead/creep), not " +
                                     PyStr.repr(ug))
            }
        }
        for ((option, value, read) in listOf<Triple<String, String?, (String) -> Unit>>(
            Triple("--tab", tab) { OverrideUrls.tabIdFromUrl(it) },
            Triple("--lacuerda", lacuerda) { OverrideUrls.lacuerdaPickFromUrl(it) },
            Triple("--harptabs", harptabs) { OverrideUrls.harptabsPickFromUrl(it) },
            Triple("--gametabs", gametabs) { OverrideUrls.gametabsPickFromUrl(it) },
        )) {
            if (value == null) continue
            try {
                read(value)
            } catch (e: OverridesError) {
                throw CommandExit(2, "$option: ${e.message}")
            }
        }
    }

    /** commands/get.py's `_duration`: m:ss, h:mm:ss or seconds. */
    private fun duration(text: String): Long {
        val ms = try {
            SongForm.parseDuration(text)
        } catch (e: IllegalArgumentException) {
            throw CommandExit(2, "--duration: ${e.message}")
        }
        return ms ?: throw CommandExit(2, "--duration: ${PyStr.repr(Py.strip(text))} isn't a duration: write m:ss, " +
                                          "h:mm:ss or seconds")
    }

    /** [request] looked up now as a job's: its stages, its song, what can be read, and `caracole get`'s lines but
     * the last ([LookupWords.totals], the caller's); the queue stopped, it stops at its next stage. */
    fun lookUp(parts: PhoneParts, request: LookupRequest, context: JobContext,
               readOverrides: (Db) -> Overrides = Overrides::read, stages: SiteStages = SiteStages.ALL): LookupResult {
        val lines = LookupLines(parts.store.libraryDir) { context.say(it) }
        val progress = object : Progress {
            override fun stage(name: String, state: String, detail: String) {
                if (context.isCancelled) throw CancellationException("the queue stopped")
                context.stage(name, state, detail)
                lines.stage(name, state, detail)
            }

            override fun song(id: Long, display: String) = context.song(id, display)

            override fun readable(files: Map<String, String>, seconds: Double) {
                context.readable(files, seconds)
                lines.readable(files, seconds)
            }
        }
        val cfg = parts.config()
        val lookup = Lookup(cfg, parts.database, parts.store, parts.clients(), parts.pages, parts.songbooks,
                            parts.alerts, request, progress, parts.pacing, stages, readOverrides)
        val result = parts.database.writeBlocking { lookup.run(it) }
        lines.flush()
        return result
    }

    /** The lookup's time, as `_common.utcnow` takes it: to the second. */
    fun now(parts: PhoneParts): Instant = parts.pacing.clock().truncatedTo(ChronoUnit.SECONDS)

    /** `_common.load_ovr`: the phone's overrides, or the command refused (exit 2). */
    fun overrides(db: Db, read: (Db) -> Overrides = Overrides::read): Overrides = try {
        read(db)
    } catch (e: OverridesError) {
        throw CommandExit(2, "overrides: ${e.message}")
    }

    /** `_common.song_named`: the song "Artist - Title" names, one not ignored; a name of another shape exits 2, a
     * song not in the library or ignored 1. */
    fun songNamed(parts: PhoneParts, db: Db, display: String, overrides: Overrides): SongRow {
        val key = try {
            OverrideUrls.overrideKey(display)
        } catch (e: OverridesError) {
            throw CommandExit(2, e.message.orEmpty())
        }
        parts.store.ensureCurrentKeys(db)
        val song = Songs.byKey(db, key)
            ?: throw CommandExit(1, "No song \"$display\" in the library. Add it with `caracole add` first.")
        if (song.status == "ignored" || key in overrides.ignore) {
            throw CommandExit(1, "\"${song.display}\" is ignored in overrides.toml.")
        }
        return song
    }

    /**
     * A lookup command's [CommandContext]: its database, its envelope at [runId] (the lookup pace's, or the command's
     * own run, LookupWords.lookupRunOf), its time, and its lines said as the job's ([CommandLines]): a progress line it
     * says (LookupWords.progressLine of its Python's events) is the job's event when the command reports them
     * ([JobCommands.reports], as web/jobs.py's emit reads them), else a line of its output; with [pages] (versions
     * --keep and --keep-more), the song's pages are made at its `pdf` and `pages` running events. The command records
     * its own good run, as its Python does (LookupWords' contract); the caller closes [asking].
     */
    fun context(parts: PhoneParts, db: Db, args: List<String>, context: JobContext, now: Instant,
                runId: String = Pace.lookupRunId(now), pages: CommandPages? = null): Pair<CommandContext, InteractiveAsk> {
        val ask = InteractiveAsk(parts.clients(), db, runId, now, parts.alerts, parts.config())
        val lines = CommandLines(context, JobCommands.reports(args), pages)
        val c = object : CommandContext {
            override val db: Db = db
            override val asking = ask
            override val now: Instant = now
            override fun say(line: String) = lines.say(line)
        }
        return c to ask
    }

    /** A command's line: its progress event to the job, or output (web/jobs.py's emit). */
    fun said(context: JobContext, line: String, reports: Boolean) = CommandLines(context, reports).say(line)

    /** The song in [db] whose pages a command makes ([CommandLines]), [made] the pdf stage's words once they are. */
    class CommandPages(val parts: PhoneParts, val db: Db, val song: SongRow, val made: String)

    /**
     * What a lookup command says, as web/jobs.py's emit reads it: a progress line (LookupWords.PROGRESS_PREFIX) its
     * job's stage, song or readable files when [reports], else a line of its output, as any other line. With [pages],
     * the command's `pdf` and `pages` running events are where versions_cmd.py makes the song's pages: they are made
     * then (the pdf stage's SongPages, skipped with get.py's NO_PDFS while it is NONE; the library page, made as it is
     * asked for), both stages ended in the phone's words, and the command's own ends of them are not said.
     */
    class CommandLines(private val context: JobContext, private val reports: Boolean,
                       private val pages: CommandPages? = null) {
        fun say(line: String) {
            val event = if (line.startsWith(LookupWords.PROGRESS_PREFIX)) {
                runCatching { PyJson.loads(line.substring(LookupWords.PROGRESS_PREFIX.length)) }.getOrNull() as? JsonObject
            } else {
                null
            }
            if (event == null) return context.say(line)
            (event["stage"] as? JsonPrimitive)?.takeIf { it.isString }?.let { name ->
                val state = (event["state"] as? JsonPrimitive)?.content.orEmpty()
                val detail = (event["detail"] as? JsonPrimitive)?.takeIf { it.isString }?.content.orEmpty()
                if (pages != null && name.content in MADE_HERE) return made(pages, name.content, state)
                if (!reports) return context.say(line)
                return context.stage(name.content, state, detail)
            }
            if (!reports) return context.say(line)
            (event["song"] as? JsonObject)?.let { song ->
                val id = (song["id"] as? JsonPrimitive)?.longOrNull ?: return
                return context.song(id, (song["display"] as? JsonPrimitive)?.content.orEmpty())
            }
            (event["files"] as? JsonObject)?.let { files ->
                val seconds = (event["seconds"] as? JsonPrimitive)?.doubleOrNull ?: 0.0
                return context.readable(files.mapValues { (it.value as? JsonPrimitive)?.content.orEmpty() }, seconds)
            }
            // any other event (a command's `done`) is no line of its output, and nothing the job keeps
        }

        /** The `pdf` or `pages` stage [name] of [p]'s song: made at its running event, and ended there. */
        private fun made(p: CommandPages, name: String, state: String) {
            if (state != "running") return  // the command's own end: the phone's is said
            val (ended, words) = when {
                name == "pages" -> "done" to LookupWords.LIBRARY_PAGE
                p.parts.pages === SongPages.NONE -> "skipped" to LookupWords.NO_PDFS
                else -> p.parts.pages.render(p.db, listOf(p.song.id), null).failed[p.song.id]?.let { "failed" to it }
                    ?: ("done" to p.made)
            }
            if (!reports) return
            context.stage(name, "running", "")
            context.stage(name, ended, words)
        }

        private companion object {
            val MADE_HERE = setOf("pdf", "pages")
        }
    }

    /** `" ".join(text.split())`. */
    fun folded(text: String): String = Py.split(text).joinToString(" ")
}
