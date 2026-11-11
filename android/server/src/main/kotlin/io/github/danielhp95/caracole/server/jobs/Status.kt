package io.github.danielhp95.caracole.server.jobs

import io.github.danielhp95.caracole.core.keys.SafeName
import io.github.danielhp95.caracole.core.py.PyRegex
import io.github.danielhp95.caracole.core.py.PyText
import io.github.danielhp95.caracole.core.py.PyUrl
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import java.time.Instant

/** status.py's Line: how a request goes, in a word's tone (queued, running, ready, added, removed, review, waiting,
 * missing, failed, cancelled), its text, where to go next ([link]: label, address) and, for a line that ends in a
 * failure or a wait, the request's output in the Requests tab ([details]). */
data class Line(val tone: String, val text: String, val link: Pair<String, String>? = null,
                val details: String? = null) {
    fun asJson(): JsonObject = JsonObject(linkedMapOf(
        "tone" to JsonPrimitive(tone), "text" to JsonPrimitive(text),
        "link" to (link?.let { (label, href) ->
            JsonObject(linkedMapOf("label" to JsonPrimitive(label), "href" to JsonPrimitive(href)))
        } ?: JsonNull),
        "details" to (details?.let(::JsonPrimitive) ?: JsonNull),
    ))
}

/** One of a job's commands as status.py and outcome.py read it: its label, its command line, its state and what it
 * printed. */
internal data class Part(val label: String, val args: List<String>, val state: String, val output: List<String>)

/**
 * A job as status.py and outcome.py read caracole serve's: its commands ([steps]) and its stages, its key, whether it
 * fetches, when it started, the units a sync said, and what kind of sync it is ([peer], status.peer_kind's).
 *
 * A job of commands is read as it is. A job of the phone's own, a run and no command (an add, a removal, a sync, an
 * index import, PhoneKinds'), is read as caracole serve's job of the same request would be: an add's or a removal's one
 * stage stands for its one command (its label, its state, the job's output) and it has no stage, as `caracole add` has
 * none; a staged one (a sync, an index import, PhoneKinds') keeps its stages, under one command named by its title;
 * a sync's units are those its outcome lists (it sets its outcome where caracole serve's command says its units).
 */
internal class Shape(val job: Job) {
    /** No command: a job of the phone's own. */
    val own: Boolean = job.steps.isEmpty()

    /** A job of the phone's own whose view carries its stages (JobViews.STAGED), or one of PhoneKinds'. */
    val staged: Boolean = own && (job.spec.kind in JobViews.STAGED || job.spec.kind in PhoneKinds.ALL)

    val steps: List<Part> = when {
        !own -> job.steps.map { Part(it.label, it.args, it.state, it.output) }
        staged -> listOf(Part(job.title, emptyList(), stepState(job.state), job.output))
        else -> job.stages.map { Part(it.label, listOf(it.name), it.state, job.output) }
    }

    val stages: List<Stage> = if (own && !staged) emptyList() else job.stages

    /** status.peer_kind: sync, peer-push, peer-pull or index-merge; null for any other job. */
    val peer: String? = if (own) job.spec.kind.takeIf { it in Status.PEER_DONE } else Status.peerKind(job.steps)

    /** The units a sync took, gave and left: its command's (Job.units), else its outcome's. */
    val units: List<JobUnit> = job.units.ifEmpty { unitsOf(job.outcome) }

    val key: String get() = job.key
    val fetching: Boolean get() = job.fetching
    val state: String get() = job.state
    val id: Int get() = job.id
    val startedAt: Instant? get() = job.startedAt

    /** Whether a command looks its song up, or makes its sheet from a YouTube video. */
    val looksUp: Boolean get() = steps.any { JobCommands.looksUp(it.args) }
    val fromYoutube: Boolean get() = steps.any { JobCommands.sheetsFromYoutube(it.args) }

    private companion object {
        fun stepState(state: String): String = when (state) {
            Job.QUEUED -> Job.WAITING
            Job.CANCELLED -> Job.SKIPPED
            else -> state
        }

        fun unitsOf(outcome: JsonObject?): List<JobUnit> {
            if (outcome == null) return emptyList()
            fun ids(name: String) = (outcome[name] as? JsonArray).orEmpty().mapNotNull { (it as? JsonPrimitive)?.content }
            val left = (outcome["left"] as? JsonArray).orEmpty().mapNotNull { item ->
                val pair = item as? JsonArray ?: return@mapNotNull null
                val unit = (pair.getOrNull(0) as? JsonPrimitive)?.content ?: return@mapNotNull null
                JobUnit(unit, "left", (pair.getOrNull(1) as? JsonPrimitive)?.content ?: "")
            }
            return ids("taken").map { JobUnit(it, "taken", "") } + ids("given").map { JobUnit(it, "given", "") } + left
        }
    }
}

/**
 * web/status.py on the phone: the one line a request shows (job_line), as a song's line says it (song_line), with no
 * to-do page ([jobLine]'s `todo` null: the phone has none, so a Not found or a review with nothing to pick says the
 * same words with no link). vectors/web/job_views*.jsonl and outcome.jsonl hold it to Python's, every kind and state.
 */
object Status {
    const val REQUESTS = "#tab=requests"
    const val READY = "Ready"
    private const val MAX_TEXT = 160  // characters of an error's sentence

    /** What a song's card says while a stage of a lookup (or another command's) runs (status.py's STAGE_LINES). */
    val STAGE_LINES: Map<String, String> = linkedMapOf(
        "song" to "Finding the song",
        "match" to "Matching",
        "sheet" to "Fetching from UG",
        "version" to "Fetching the version from UG",
        "pdf" to "Making the PDF",
        "lyrics" to "Fetching lyrics",
        "ug" to "Fetching from UG",
        "lacuerda" to "Fetching from LaCuerda",
        "gtptabs" to "Fetching from gtptabs",
        "harptabs" to "Fetching from harptabs",
        "gametabs" to "Fetching from gametabs",
        "pages" to "Writing the logbook page",
        "songbooks" to "Remaking its songbooks",
        "search" to "Searching LaCuerda",
        "audio" to "Getting the audio",
        "chords" to "Working out the chords",
        "video" to "Searching YouTube",
        "thumbnail" to "Getting the thumbnail",
        "compare" to "Comparing books",
        "take" to "Taking their entries",
        "give" to "Sharing our entries",
        "mirror" to "Copying the computer's pages",
        "agree" to "Noting where the books agree",
        "index" to "Updating the indexes",
        "check" to "Checking for changes since the compare",
        "render" to "Making pages of what was taken",
        "merge" to "Merging the other scribe's index pages",
    )

    /** A sync's or a take's command (its first step's `caracole peer` subcommand), as the page names its kind. */
    internal val PEER_KINDS = mapOf("sync" to "sync", "take" to "peer-push", "pull" to "peer-pull", "import" to "sync")
    const val INDEX_MERGE_KIND = "index-merge"

    /** How each says it is done (status.py's _PEER_DONE). */
    internal val PEER_DONE = mapOf("sync" to "Shared", "peer-push" to "Taken", "peer-pull" to "Taken",
                                   INDEX_MERGE_KIND to "Merged")
    private const val WAITING = "waiting for the book"  // get.py's song stage while the lock is held

    /** get.py's SHEET_FROM's words, a running sheet stage's line by its site. */
    internal val SHEET_LINES = listOf("from LaCuerda", "from UG").associateWith { "Fetching $it" }

    /** How `caracole lacuerda --artist` and `--search` (and `harptabs --artist`, `youtube --search`) end, by what
     * the site answered, and the line's tone. */
    internal val READ_TONES = linkedMapOf(
        "Read: " to "added", "Not found: " to "missing", "Not read: " to "waiting",
        "Searched: " to "added", "Found already: " to "added", "Nothing found: " to "missing",
        "Not searched: " to "waiting",
    )

    // web/songbooks.py: a songbook job's key, and what its line says once done, by its action.
    private const val SONGBOOK_KEY = JobCommands.SONGBOOK
    private const val SEP = "\u001f"
    internal val DONE = mapOf("make" to "Made", "add" to "Added", "move" to "Moved", "remove" to "Taken out",
                             "set" to "Changed", "rename" to "Renamed", "delete" to "Deleted", "render" to "Made")
    internal val OPENS = setOf("make", "add", "render")

    /** A songbook's change a job's key names (songbooks.songbook_of): its action, its name, and its name once done
     * (the new one for a rename, null for a deletion). */
    data class SongbookChange(val action: String, val name: String, val after: String?) {
        fun asJson(): JsonObject = JsonObject(linkedMapOf(
            "action" to JsonPrimitive(action), "name" to JsonPrimitive(name),
            "after" to (after?.let(::JsonPrimitive) ?: JsonNull),
        ))
    }

    /** songbooks.songbook_of: the songbook a job's key changes; null for a job of anything else. */
    fun songbookOf(key: String): SongbookChange? {
        if (!key.startsWith(SONGBOOK_KEY)) return null
        val words = key.substring(SONGBOOK_KEY.length).split(SEP)
        if (words.size < 4 || words[0] != "songbook" || words[1] !in DONE || words[2] != "--") return null
        val action = words[1]
        val name = words[3]
        val after = if (action == "rename" && words.size > 4) words[4] else if (action == "delete") null else name
        return SongbookChange(action, name, after)
    }

    /** status.peer_kind over a job's commands: its first's `caracole peer` subcommand, or `index merge --progress`. */
    fun peerKind(steps: List<Step>): String? {
        val args = steps.firstOrNull()?.args ?: return null
        if (args.take(2) == JobCommands.INDEX_MERGE_COMMAND && "--progress" in args) return INDEX_MERGE_KIND
        return if (args.size > 1 && args[0] == JobCommands.PEER) PEER_KINDS[args[1]] else null
    }

    /** The job's output in the library page's Requests tab, open (status.details_href). */
    fun detailsHref(id: Int): String = "$REQUESTS&job=$id"

    /**
     * status.job_line: the job's line; [song], what the library knows of its song now (null while it has no such
     * song); [ahead], the jobs before a queued one; [songbookPage], a songbook's change's page; [todo], the to-do page
     * a Not found or a review with nothing to pick links (null: the phone has none, and the line has no link).
     */
    fun jobLine(job: Job, song: SongFacts?, ahead: Int = 0, songbookPage: String? = null, todo: String? = null): Line =
        line(Shape(job), song, ahead, songbookPage, todo)

    internal fun line(job: Shape, song: SongFacts?, ahead: Int, songbookPage: String?, todo: String?): Line {
        when (job.state) {
            Job.QUEUED -> return Line("queued", if (ahead > 0) "Queued · ${plural(ahead, "request")} ahead…" else "Queued…")
            Job.RUNNING -> {
                if (job.stages.isNotEmpty()) return Line("running", stageLine(job.stages, new = song == null))
                val step = job.steps.firstOrNull { it.state == Job.RUNNING } ?: job.steps.firstOrNull { it.state == Job.WAITING }
                return Line("running", if (step != null) "${step.label}…" else "Running…")
            }
            Job.CANCELLED -> return Line("cancelled", "Cancelled")
        }
        val details = detailsHref(job.id)
        if (job.state == Job.INTERRUPTED) return Line("waiting", "Interrupted", details = details)
        if (job.state == Job.FAILED) {
            if (job.fetching && song != null && song.sheet == null) {
                if (song.review) return Line("review", "Needs your pick", reviewLink(song, todo), details)
                if (song.notFound) return Line("missing", "Not on the sites", todoLink(todo), details)
            }
            return Line("failed", stageFailure(job.stages) ?: failure(job.steps), details = details)
        }
        val key = job.key
        job.peer?.let { return peerDone(job, it, details) }
        if (key.startsWith(JobCommands.REMOVING)) return Line("removed", "Removed")
        if (key.startsWith(JobCommands.EXPORTING)) {
            return Line("ready", "Your version", song?.sheet?.let { "Open" to it })
        }
        if (key.startsWith(JobCommands.READING)) {
            val page = harmonicaPage(job.steps)
            val said = if (job.steps.any { "--clear" in it.args }) "read as we guess" else "read as you set it"
            return Line("ready", "Tab $said", page?.let { "Open tab" to it })
        }
        songbookOf(key)?.let { book ->
            if (book.action == "delete") return Line("removed", DONE.getValue(book.action))
            val opens = if (book.action in OPENS) songbookPage else null
            return Line("ready", DONE.getValue(book.action), opens?.let { "Open songbook" to it })
        }
        if (JobCommands.INDEX_READS.any(key::startsWith)) return artistRead(job.steps, details)
        if (key.startsWith(JobCommands.YOUTUBE_SHEET)) {
            val made = job.stages.any { it.name == "chords" && it.state == Job.DONE }
            if (made && song?.sheet != null) return Line("ready", READY, "Open" to song.sheet)
            return Line("waiting", "Not made yet", details = details)
        }
        if (song?.sheet != null) return Line("ready", READY, "Open" to song.sheet)
        if (song != null && song.ignored) return Line("added", "Ignored · overrides.toml")
        if (song != null && song.review) return Line("review", "Needs your pick", reviewLink(song, todo))
        if (!job.fetching && song != null && song.lacuerda) {
            return Line("added", "Added · your LaCuerda pick comes tonight")
        }
        if (!job.fetching || song == null) return Line("added", "Added · fetched tonight")
        if (song.checkedNow) return Line("missing", "Not on the sites", todoLink(todo))
        return Line("waiting", "Not fetched yet", details = details)
    }

    /** status.song_line: the line under a song's line: "Ready" alone, with no link (the song's line opens its sheet
     * itself); any other as it is. */
    fun songLine(line: Line): Line = if (line.tone == "ready" && line.text == READY) line.copy(link = null) else line

    /** A harmonica tab's reading pinned or cleared: the tab's page (`--tab=`, the song after `--`), relative, each
     * name quoted (status._harmonica_page). */
    private fun harmonicaPage(steps: List<Part>): String? {
        val args = steps.firstOrNull()?.args ?: emptyList()
        val tab = args.firstOrNull { it.startsWith("--tab=") }?.substringAfter('=') ?: ""
        val page = harmonicaPageOf(tab)
        val end = args.indexOf("--")
        if (page == null || end < 0 || args.size < end + 3) return null
        val (artist, folder) = SafeName.songFolder(args[end + 1], args[end + 2])
        return listOf(artist, folder, page).joinToString("/") { PyUrl.quote(it) }
    }

    /** inbox.harmonica_page: "harmonica-1.txt" → "harmonica-1.html"; null for a name no kept tab has (inbox.py's
     * HARMONICA_FILE, fullmatch). */
    private fun harmonicaPageOf(name: String): String? =
        HARMONICA_FILE.matchEntire(name)?.let { "harmonica-${it.groupValues[1]}.html" }

    private val HARMONICA_FILE = PyRegex.compile("""harmonica-(\d+)\.txt""")

    /** A site's index read over: the sentence its command ends with, up to its first "; " or bracket (status.py's
     * _artist_read). */
    private fun artistRead(steps: List<Part>, details: String): Line {
        val said = steps.asReversed().firstNotNullOfOrNull { step ->
            step.output.asReversed().firstOrNull { line -> READ_TONES.keys.any(line::startsWith) }?.let(PyText::strip)
        } ?: return Line("added", "Done", details = details)
        val tone = READ_TONES.entries.first { said.startsWith(it.key) }.value
        val text = said.split("; ", limit = 2)[0].split(" (", limit = 2)[0].trimEnd('.') + "."
        return Line(tone, short(text), details = if (tone == "added") null else details)
    }

    /** A sync, a take or a pull that is done (status.py's _peer_done). */
    private fun peerDone(job: Shape, kind: String, details: String): Line {
        stageFailure(job.stages)?.let { return Line("waiting", it, details = details) }
        val left = job.units.count { it.outcome == "left" }
        if (left > 0) {
            return Line("waiting", "${PEER_DONE.getValue(kind)} · ${plural(left, "change")} left as " +
                                   (if (left == 1) "it was" else "they were"), details = details)
        }
        return Line("ready", PEER_DONE.getValue(kind))
    }

    private fun reviewLink(song: SongFacts, todo: String?): Pair<String, String>? =
        song.picker?.let { "Pick" to it } ?: todoLink(todo)

    private fun todoLink(todo: String?): Pair<String, String>? = todo?.let { "To-do page" to it }

    /** A running staged job's line: its running stage's, else the next one's (status.py's _stage_line); [new], a song
     * the library doesn't have yet, which the song stage adds. */
    internal fun stageLine(stages: List<Stage>, new: Boolean = false, lines: Map<String, String> = STAGE_LINES): String {
        val stage = stages.firstOrNull { it.state == Job.RUNNING } ?: stages.firstOrNull { it.state == Job.WAITING }
            ?: return "Running…"
        val running = stage.state == Job.RUNNING
        if (running && stage.detail.startsWith(WAITING)) return "Waiting for the book…"
        if (stage.name == "song" && new) return "Adding to the book…"
        if (running && stage.name == "sheet" && stage.detail in SHEET_LINES) return "${SHEET_LINES.getValue(stage.detail)}…"
        if (running && stage.name == "songbooks" && stage.detail.isNotEmpty()) return "Remaking songbook ${stage.detail}…"
        return "${lines[stage.name] ?: stage.label}…"
    }

    /** A failure in its failed stage's words (status.py's _stage_failure): never what a stage the queue ended said
     * while it ran ([Stage.runningDetail]); null without one. */
    internal fun stageFailure(stages: List<Stage>): String? {
        val failed = stages.firstOrNull { it.state == Job.FAILED && it.detail.isNotEmpty() && it.detail != it.runningDetail }
            ?: return null
        val said = short(firstSentence(PyText.strip(failed.detail)))
        return if (listOf(".", "!", "?", "…").any(said::endsWith)) said else "$said."
    }

    /** status.py's _failure: the failed command's last `error:` line's first sentence, else "<label> failed."; with
     * no command failed, that it stopped. */
    internal fun failure(steps: List<Part>): String {
        val failed = steps.firstOrNull { it.state == Job.FAILED } ?: return "Stopped before the end."
        val said = failed.output.asReversed().firstNotNullOfOrNull(::errorOf)?.let(PyText::strip)
        if (said.isNullOrEmpty()) return "${failed.label} failed."
        return short(firstSentence(said))
    }

    /** What an `error:` line says (status.py's _ERROR, re.match: a journal priority may come before it); null for
     * any other line. */
    private fun errorOf(line: String): String? = ERROR.find(line)?.groupValues?.get(1)

    private val ERROR = PyRegex.compile("""^(?:<\d>)?error: (.+)$""")

    /** The text up to its first sentence's end: `(?<=[.!?])\s`, Python's whitespace. */
    private fun firstSentence(text: String): String {
        var i = 0
        var previous = -1
        while (i < text.length) {
            val cp = text.codePointAt(i)
            if (previous == '.'.code || previous == '!'.code || previous == '?'.code) {
                if (PyText.isSpace(cp)) return text.substring(0, i)
            }
            previous = cp
            i += Character.charCount(cp)
        }
        return text
    }

    /** status.py's _short: at most [MAX_TEXT] characters (code points), cut at a word with "…". */
    internal fun short(text: String): String {
        if (text.codePointCount(0, text.length) <= MAX_TEXT) return text
        val head = text.substring(0, text.offsetByCodePoints(0, MAX_TEXT - 1))
        val cut = (if (' ' in head) head.substringBeforeLast(' ') else head).trimEnd(' ', ',', ';', ':')
        return "$cut…"
    }

    internal fun plural(n: Int, noun: String): String = "$n ${if (n == 1) noun else noun + "s"}"

    /** The song's identity key in a job's key (jobs.song_key_of). */
    internal fun songKeyOf(key: String): String = JobCommands.songKeyOf(key)
}
