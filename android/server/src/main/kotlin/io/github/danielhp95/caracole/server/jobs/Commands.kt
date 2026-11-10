package io.github.danielhp95.caracole.server.jobs

import io.github.danielhp95.caracole.core.json.PyJson
import kotlinx.serialization.json.JsonObject
import java.math.BigDecimal
import java.math.RoundingMode

/** One of a job's commands: its step's [label] and its command line after `caracole` ([args]), as web/jobs.py's Step
 * spells it (JobCommands' builders). */
data class Command(val label: String, val args: List<String>)

/** What runs a command line on the phone, in-process: it throws when the step failed ([CommandExit] for an exit
 * status of its own, else 1), as caracole exits non-zero, its message the command's `error:` line. */
fun interface CommandRunner {
    suspend fun run(args: List<String>, context: JobContext)
}

/** The phone's runners, by a command line's first word (`get`, `versions`, `lacuerda`, `harptabs`…). */
class Commands(val runners: Map<String, CommandRunner>) {
    fun runnerFor(args: List<String>): CommandRunner? = args.firstOrNull()?.let { runners[it] }
}

/** A command that ended as caracole exits with [code] (2 for a refusal, say), [message] its `error:` line. */
class CommandExit(val code: Int, message: String) : Exception(message)

/**
 * web/jobs.py's command lines and its rules over them, on the phone (vectors/web/queue.jsonl holds both to Python's
 * answers):
 *
 * - the step builders, each a job's commands spelled exactly as caracole serve spells them ([lookupSteps]: `get
 *   --progress … -- ARTIST TITLE`, [versionSteps], [lacuerdaSearchSteps]…);
 * - the stages a job's commands report ([stages]: get.py's [GET_STAGES] for a lookup, Keep it's, a search's, a sheet
 *   from YouTube's, a sync's), as caracole serve's queue makes them;
 * - what a job's commands ask for ([pick]: a lookup's `--ug`, `--tab`, `--lacuerda`, `--harptabs`, `--gametabs`, a
 *   versions' `--choose`, `--keep`, `--keep-more`, `--clear`), whether one looks its song up ([looksUp]), fetches it
 *   ([fetches]) or writes progress lines ([reports]);
 * - the job keys' prefixes, and two rules of the phone's own: [isLookup] (the jobs a long job lets go first,
 *   JobContext.yieldToQueued) and [kindOf] (a job read back from the history, which keeps no kind).
 */
object JobCommands {
    const val LOOKUP = "get"  // the command of a lookup
    const val VERSIONS = "versions"  // a song's version made the one, kept, its versions fetched, or its pin taken out
    const val PEER = "peer"  // a sync with another caracole: `caracole peer take` a push, `peer sync`

    /** get.py's STAGES: a lookup's stages, in order. */
    val GET_STAGES: List<Pair<String, String>> = listOf(
        "song" to "Find the song",
        "match" to "Match on UG's index",
        "sheet" to "Sheet",
        "pdf" to "PDF",
        "lyrics" to "Lyrics",
        "ug" to "UG: versions scored, tab",
        "lacuerda" to "LaCuerda",
        "gtptabs" to "Guitar Pro file from gtptabs",
        "harptabs" to "Harmonica tab from harptabs",
        "gametabs" to "Game music tab from gametabs",
        "pages" to "The logbook page",
        "songbooks" to "Its songbooks",
    )

    /** Keep it's stages, as `caracole versions --keep --progress` reports them, and `--keep-more`'s. */
    val KEEP_STAGES: List<Pair<String, String>> = listOf(
        "song" to "Find the song",
        "version" to "Version from UG",
        "pdf" to "Version's page",
        "pages" to "The logbook page",
    )

    /** `caracole lacuerda --search --progress`'s one stage. */
    val SEARCH_STAGES: List<Pair<String, String>> = listOf("search" to "Search LaCuerda")

    /** `caracole youtube --search` and `--video`'s (caracole serve's alone: the phone never runs yt-dlp). */
    val YOUTUBE_SEARCH_STAGES: List<Pair<String, String>> = listOf("video" to "Search YouTube",
                                                                    "thumbnail" to "Thumbnail")

    /** youtube_sheet.py's STAGES, `caracole youtube --sheet --progress`'s (caracole serve's alone). */
    val YOUTUBE_SHEET_STAGES: List<Pair<String, String>> = listOf(
        "song" to "Find the song",
        "audio" to "Audio from YouTube",
        "lyrics" to "Lyrics",
        "chords" to "Chords from the audio",
        "pdf" to "PDF",
        "pages" to "The logbook page",
    )

    /** `caracole peer take --progress`'s stages, a push another caracole sent taken here. */
    val PEER_TAKE_STAGES: List<Pair<String, String>> = listOf(
        "check" to "What changed since compared",
        "take" to "Taking their entries",
        "render" to "Making pages of what was taken",
        "agree" to "Where the books agree",
    )

    /** `caracole peer sync --progress`'s. */
    val PEER_SYNC_STAGES: List<Pair<String, String>> = listOf(
        "compare" to "Comparing books",
        "take" to "Taking their entries",
        "give" to "Sharing our entries",
        "agree" to "Where the books agree",
    )

    /** `caracole index merge --delete --progress -- FILE`'s, the index pages another caracole's lookups read. */
    val INDEX_MERGE_COMMAND: List<String> = listOf("index", "merge")
    val INDEX_MERGE_STAGES: List<Pair<String, String>> = listOf("merge" to "Merging the other scribe's index pages")

    // The job keys' prefixes, what follows each a song's or a query's key.
    const val REMOVING = "remove:"  // a removal's: never joins the song's add or fetch
    const val EXPORTING = "export:"  // Make this my version's: the song's key and the version, then MINE
    const val MINE = ":mine"
    const val READING = "harmonica:"  // a harmonica tab's reading pinned: the song's key, the tab, the reading, MINE
    const val LACUERDA_ARTIST = "lacuerda-artist:"  // a LaCuerda artist page's read: the page's slug after it
    const val LACUERDA_SEARCH = "lacuerda-search:"  // a query of LaCuerda's search: the query's key after it
    const val HARPTABS_ARTIST = "harptabs-artist:"  // a harptabs.com artist page's read: the page's path after it
    const val YOUTUBE_SEARCH = "youtube-search:"  // a video suggested for a search
    const val YOUTUBE_SHEET = "youtube:"  // a sheet from a YouTube video: the song's identity key after it
    const val INDEX_MERGE = "index-merge:"  // an index export's merge
    const val SYNCING = "sync:"  // a sync's (sync_routes.SYNCING): the address it syncs with after it
    const val SONGBOOK = "songbook\u001f"  // a songbook's change (web/songbooks.py's KEY)

    /** What a site's index reads, and a search's suggestion: jobs of no song's. */
    val INDEX_READS: List<String> = listOf(LACUERDA_ARTIST, LACUERDA_SEARCH, HARPTABS_ARTIST, YOUTUBE_SEARCH)

    // --- the builders -------------------------------------------------------------------------------------------

    /** `caracole add`, as you'd type it; `--` ends the options, so a name may start with "-". */
    fun addSteps(artist: String, title: String, album: String? = null, durationMs: Long? = null,
                 lacuerda: String? = null): List<Command> {
        val args = mutableListOf("add")
        if (!album.isNullOrEmpty()) args += "--album=$album"
        if (durationMs != null) args += "--duration=${formatDuration(durationMs)}"
        if (!lacuerda.isNullOrEmpty()) args += "--lacuerda=$lacuerda"
        return listOf(Command("Adding to the book", args + listOf("--", artist, title)))
    }

    /** Fetch one song now: match it (offline), fetch it from UG, render its PDF (offline). */
    fun fetchSteps(display: String): List<Command> = listOf(
        Command("Matching", listOf("match")),
        Command("Fetching from UG", listOf("fetch", "--song=$display")),
        Command("Making the PDF", listOf("render", "--song=$display")),
    )

    /** Look one song up now: `caracole get --progress`, one process for every stage (get.py). */
    fun lookupSteps(artist: String, title: String, album: String? = null, durationMs: Long? = null,
                    ug: String? = null, tab: String? = null, lacuerda: String? = null, harptabs: String? = null,
                    gametabs: String? = null, songbooks: Boolean = true): List<Command> {
        val args = mutableListOf(LOOKUP, "--progress")
        if (!songbooks) args += "--no-songbooks"  // Get the missing songs makes the songbook once, after them all
        if (!album.isNullOrEmpty()) args += "--album=$album"
        if (durationMs != null) args += "--duration=${formatDuration(durationMs)}"
        if (!ug.isNullOrEmpty()) args += "--ug=$ug"
        if (!tab.isNullOrEmpty()) args += "--tab=$tab"
        if (!lacuerda.isNullOrEmpty()) args += "--lacuerda=$lacuerda"
        if (!harptabs.isNullOrEmpty()) args += "--harptabs=$harptabs"
        if (!gametabs.isNullOrEmpty()) args += "--gametabs=$gametabs"
        return listOf(Command("Fetching", args + listOf("--", artist, title)))
    }

    /** `caracole versions --progress`: the tab [choose] made the song's sheet (`--choose`, a lookup's stages), the tab
     * [keep] kept beside it, the versions not kept yet kept ([keepMore]), or, with none, the song's `[pin]` taken out
     * and the song looked up again (`--clear`). The song is its artist and title as two words. */
    fun versionSteps(artist: String, title: String, keep: String? = null, choose: String? = null,
                     keepMore: Boolean = false): List<Command> = listOf(when {
        choose != null -> Command("Making it the one",
                                  listOf(VERSIONS, "--choose=$choose", "--progress", "--", artist, title))
        keep != null -> Command("Fetching the version from UG",
                                listOf(VERSIONS, "--keep=$keep", "--progress", "--", artist, title))
        keepMore -> Command("Fetching versions from UG",
                            listOf(VERSIONS, "--keep-more", "--progress", "--", artist, title))
        else -> Command("Going back to our pick", listOf(VERSIONS, "--clear", "--progress", "--", artist, title))
    })

    /** Read a LaCuerda artist's page into its index now: `caracole lacuerda --artist`, one request. */
    fun lacuerdaArtistSteps(slug: String, name: String): List<Command> =
        listOf(Command("Reading $name's page on LaCuerda", listOf("lacuerda", "--artist=$slug")))

    /** Ask LaCuerda's search for a query's songs now: `caracole lacuerda --search --progress`, one request; [auto],
     * sent by the page by itself (`--auto`). */
    fun lacuerdaSearchSteps(query: String, auto: Boolean): List<Command> =
        listOf(Command("Searching LaCuerda",
                       listOf("lacuerda", "--search=$query", "--progress") + if (auto) listOf("--auto") else emptyList()))

    /** Read a harptabs.com artist's page into its index now: `caracole harptabs --artist`, one request. */
    fun harptabsArtistSteps(path: String, name: String): List<Command> =
        listOf(Command("Reading $name's page on harptabs", listOf("harptabs", "--artist=$path")))

    /** `caracole remove --yes`: the page asked already, and showed what goes. */
    fun removeSteps(display: String): List<Command> =
        listOf(Command("Removing from the book", listOf("remove", "--yes", "--", display)))

    /** Answer a song's review as `caracole review` does, with no question: [pick] (a candidate's ARTIST/SONG), or,
     * without it, none of the candidates [seen]. */
    fun reviewSteps(display: String, pick: String? = null, seen: List<String> = emptyList()): List<Command> {
        val answer = if (pick != null) listOf("--pick=$pick") else listOf("--none") + seen.map { "--seen=$it" }
        return listOf(Command("Noting your answer in overrides.toml", listOf("review", "--song=$display") + answer))
    }

    /** get.py's PROGRESS_PREFIX: a line of `caracole get --progress` (and the other commands' `--progress`). */
    const val PROGRESS_PREFIX = "caracole-progress: "

    /** get.py's progress_line: a progress event as a line a command with `--progress` prints, `json.dumps(event,
     * ensure_ascii=False, separators=(",", ":"))` after [PROGRESS_PREFIX]. */
    fun progressLine(event: JsonObject): String = PROGRESS_PREFIX + PyJson.dumps(event, compact = true)

    /** `round(seconds, 3)`, Python's: the double's exact value rounded half to even at the third decimal, then the
     * double nearest that (a NaN or an infinity as it is). */
    fun round3(seconds: Double): Double =
        if (!seconds.isFinite()) seconds else BigDecimal(seconds).setScale(3, RoundingMode.HALF_EVEN).toDouble()

    /** wanted.py's format_duration: `m:ss`, or `h:mm:ss` from an hour up, rounded to the nearest second. */
    fun formatDuration(durationMs: Long): String {
        val seconds = Math.floorDiv(durationMs + 500L, 1000L)
        val hours = Math.floorDiv(seconds, 3600L)
        val rest = Math.floorMod(seconds, 3600L)
        val minutes = rest / 60
        val secs = rest % 60
        return if (hours != 0L) "$hours:${two(minutes)}:${two(secs)}" else "$minutes:${two(secs)}"
    }

    private fun two(n: Long): String = if (n < 10) "0$n" else "$n"

    // --- the rules ----------------------------------------------------------------------------------------------

    /** A command line's options: what comes before its `--`, if any. */
    fun options(args: List<String>): List<String> = args.indexOf("--").let { if (it >= 0) args.subList(0, it) else args }

    private fun first(args: List<String>): String? = args.firstOrNull()

    /** Whether a command is a lookup of its song: `caracole get`, or `caracole versions --choose` or `--clear`, which
     * run one. */
    fun looksUp(args: List<String>): Boolean = first(args) == LOOKUP ||
        (first(args) == VERSIONS && options(args).any { it == "--clear" || it.startsWith("--choose=") })

    /** Whether a job of [commands] looks its song up or fetches it (`caracole fetch`): Keep it and Fetch them do
     * neither. */
    fun fetches(commands: List<List<String>>): Boolean = commands.any { looksUp(it) || first(it) == "fetch" }

    /** Whether a command writes `caracole get --progress` lines: a lookup, `caracole versions --progress`, `lacuerda
     * --search --progress`, `youtube … --progress`, `peer … --progress` or `index merge --progress`. */
    fun reports(args: List<String>): Boolean = first(args) == LOOKUP ||
        (first(args) in listOf(VERSIONS, "lacuerda", "youtube", PEER) && "--progress" in options(args)) ||
        (args.take(2) == INDEX_MERGE_COMMAND && "--progress" in options(args))

    /** Whether a command is a query of LaCuerda's search. */
    fun searches(args: List<String>): Boolean = first(args) == "lacuerda" && args.any { it.startsWith("--search=") }

    /** Whether a command makes a song's sheet from a YouTube video (`caracole youtube --sheet`). */
    fun sheetsFromYoutube(args: List<String>): Boolean = first(args) == "youtube" && "--sheet" in args

    private fun peerStages(args: List<String>): List<Pair<String, String>> {
        if (args.take(2) == INDEX_MERGE_COMMAND && "--progress" in options(args)) return INDEX_MERGE_STAGES
        if (first(args) != PEER || "--progress" !in options(args)) return emptyList()
        return when (args.getOrNull(1)) {
            "take" -> PEER_TAKE_STAGES
            "sync" -> PEER_SYNC_STAGES
            else -> emptyList()
        }
    }

    /** The song's identity key in a job's key: a removal's and a sheet from YouTube's have theirs after a prefix. */
    fun songKeyOf(jobKey: String): String = jobKey.removePrefix(REMOVING).removePrefix(YOUTUBE_SHEET)

    private val PICKED_BY_LOOKUP = listOf("--ug=", "--tab=", "--lacuerda=", "--harptabs=", "--gametabs=")

    /** The Ultimate Guitar song and tab, the LaCuerda song, the harptabs.com tab and the gametabs.net tab a lookup was
     * given, and what a `caracole versions` does (`--choose`, `--keep`, `--keep-more`, `--clear`), if any. */
    fun pick(commands: List<List<String>>): List<String> {
        val picked = mutableListOf<String>()
        for (args in commands) {
            val options = options(args)
            if (first(args) == LOOKUP) {
                picked += options.filter { arg -> PICKED_BY_LOOKUP.any { arg.startsWith(it) } }
            } else if (first(args) == VERSIONS) {
                picked += options.filter {
                    it.startsWith("--choose=") || it.startsWith("--keep=") || it == "--clear" || it == "--keep-more"
                }
            }
        }
        return picked
    }

    /** A job's stages, all waiting, as (name, label): a lookup's, then Keep it's it hasn't, a search of LaCuerda's, a
     * sheet from a YouTube video's and a sync's with another caracole; none for other commands. */
    fun stages(commands: List<List<String>>): List<Pair<String, String>> {
        val names = LinkedHashMap<String, String>()  // as Python's dict: an update keeps a name where it was
        if (commands.any(::looksUp)) GET_STAGES.forEach { (name, label) -> names[name] = label }
        if (commands.any(::searches)) SEARCH_STAGES.forEach { (name, label) -> names[name] = label }
        if (commands.any { args -> first(args) == "youtube" &&
                               args.any { it.startsWith("--search=") || it.startsWith("--video=") } }) {
            YOUTUBE_SEARCH_STAGES.forEach { (name, label) -> names[name] = label }
        }
        if (commands.any { first(it) == VERSIONS && !looksUp(it) }) {
            KEEP_STAGES.forEach { (name, label) -> names.putIfAbsent(name, label) }
        }
        if (commands.any(::sheetsFromYoutube)) YOUTUBE_SHEET_STAGES.forEach { (name, label) -> names.putIfAbsent(name, label) }
        for (args in commands) peerStages(args).forEach { (name, label) -> names.putIfAbsent(name, label) }
        return names.map { (name, label) -> name to label }
    }

    /**
     * Whether a command is an interactive lookup (AGENTS.md's): `caracole get`, `versions` (keep, keep more, choose,
     * clear), `lacuerda --artist` or `--search`, `harptabs --artist`: the jobs of the lookup kinds (song, versions,
     * lacuerda-artist, lacuerda-search, harptabs-artist) a long job of the phone's own lets go first
     * (JobContext.yieldToQueued).
     */
    fun isLookup(args: List<String>): Boolean = when (first(args)) {
        LOOKUP, VERSIONS -> true
        "lacuerda" -> args.any { it.startsWith("--artist=") || it.startsWith("--search=") }
        "harptabs" -> args.any { it.startsWith("--artist=") }
        else -> false
    }

    /**
     * The kind (JobSpec.kind) of a job read back from the history, which keeps none (history.py's format 1) for a job
     * of commands: by its key, as jobs_routes.view tells them apart (a removal, an export, a songbook's change, a
     * site's index read, a sync), or a kind of the phone's own by its key's prefix ([phoneKinds], each prefix's kind,
     * PhoneKinds': the render job's `render:`…), else by its first command (`versions`, `review`); an add the phone
     * ran itself (no command, an `add` stage) is "add"; any other a song's ("song").
     */
    fun kindOf(key: String, commands: List<List<String>>, stageNames: List<String>,
               phoneKinds: Map<String, String> = PhoneKinds.ALL.values.associate { it.key to it.kind }): String = when {
        key.startsWith(REMOVING) -> "remove"
        key.startsWith(EXPORTING) -> "export"
        key.startsWith(READING) -> "harmonica"
        key.startsWith(SONGBOOK) -> "songbook"
        key.startsWith(LACUERDA_SEARCH) -> "lacuerda-search"
        key.startsWith(LACUERDA_ARTIST) -> "lacuerda-artist"
        key.startsWith(HARPTABS_ARTIST) -> "harptabs-artist"
        key.startsWith(YOUTUBE_SEARCH) -> "youtube-search"
        key.startsWith(YOUTUBE_SHEET) -> "youtube"
        key.startsWith(INDEX_MERGE) -> "index-merge"
        key.startsWith(SYNCING) -> "sync"
        key == "index" -> "index"
        phoneKinds.keys.any { key.startsWith(it) } -> phoneKinds.entries.first { key.startsWith(it.key) }.value
        commands.isEmpty() && "add" in stageNames -> "add"
        commands.firstOrNull()?.firstOrNull() == VERSIONS -> "versions"
        commands.firstOrNull()?.firstOrNull() == "review" -> "review"
        else -> "song"
    }
}
