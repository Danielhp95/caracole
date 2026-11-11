package io.github.danielhp95.caracole.server.pages

import io.github.danielhp95.caracole.core.config.RankPolicy
import io.github.danielhp95.caracole.core.db.Db
import io.github.danielhp95.caracole.core.keys.SafeName
import io.github.danielhp95.caracole.core.library.Kept
import io.github.danielhp95.caracole.core.library.Overrides
import io.github.danielhp95.caracole.core.library.SongRow
import io.github.danielhp95.caracole.core.library.Versions
import io.github.danielhp95.caracole.core.py.Py
import io.github.danielhp95.caracole.core.py.PyFormat
import io.github.danielhp95.caracole.core.py.PyUrl
import io.github.danielhp95.caracole.core.ug.SheetVersion
import io.github.danielhp95.caracole.core.ug.SheetVersions
import io.github.danielhp95.caracole.server.http.LibraryName
import io.github.danielhp95.caracole.server.http.Refused
import io.github.danielhp95.caracole.server.http.Response
import io.github.danielhp95.caracole.server.jobs.Command
import io.github.danielhp95.caracole.server.jobs.Job
import io.github.danielhp95.caracole.server.jobs.JobCommands
import io.github.danielhp95.caracole.server.jobs.Status
import io.github.danielhp95.caracole.server.pages.Choices.esc
import io.github.danielhp95.caracole.server.pages.Choices.quote
import io.github.danielhp95.caracole.server.routes.search.Looked
import io.github.danielhp95.caracole.viewer.render.RenderNames

/**
 * What a versions page or post names (versions_routes._Asked): the song, the viewer it came from (its library path;
 * a post by song, the song's sheet.html) and its folder (as a quoted address), the version (null for Back to
 * caracole's pick), every version, what the song's sheet is now in words ([theOne]), the song's `[pin]` tabs that
 * choose its sheet ([sheetPins], those `caracole versions --clear` takes out) and every one it has ([pins]), the tabs
 * under `[block]`, the viewer Back to the sheet opens ([back]), and the versions a keep may still keep ([toKeep]).
 */
internal class VersionsAsked(val song: SongRow, val sheet: String, val folder: String, val version: SheetVersion?,
                             val versions: List<SheetVersion>, val theOne: String?, val sheetPins: List<Long>,
                             val pins: List<Long>, val blocked: Set<Long>, val back: String,
                             val toKeep: List<SheetVersion>) {
    val pinned: Boolean get() = sheetPins.isNotEmpty()
}

/**
 * caracole serve's versions page on the phone (web/versions_routes.py), in its words: one of Ultimate Guitar's chords
 * versions of a song's sheet, made the one, kept beside the sheet, or the song taken back to caracole's pick. The
 * page is the server's own, with no script, its one form posting with the form token; with `&job=`, how the request
 * goes, read again from the song's state once it is done, never from the command's exit.
 *
 * A viewer is the phone's when the phone recorded writing it in the song's folder (render.written_file's kv
 * `render:files:<id>`): a path of any other names no sheet (404), the computer's pages the mirror serves among them.
 */
internal object VersionsPage {
    /** versions_routes.DOINGS: the versions page's. */
    val DOINGS = listOf("choose", "keep", "clear")

    /** versions_routes.TABLESS: what names no version. */
    val TABLESS = setOf("clear", "keep-more")

    /** versions_routes.MAX_TAB: digits (UG's tab ids are seven or eight). */
    const val MAX_TAB = 12

    private val NO_SHEET get() = Refused(404, "Not found", "No such sheet in the book.")

    /** songs.SHEET_OUTPUTS' viewers: render.HUMAN_OUTPUTS[2] and AUTO_OUTPUTS[2]. */
    private val VIEWERS = setOf(RenderNames.HUMAN_OUTPUTS[2], RenderNames.AUTO_OUTPUTS[2])

    private val SOURCES = mapOf("lacuerda" to "LaCuerda's sheet", "auto" to "the auto-chords sheet")

    // --- what a page or a post names ------------------------------------------------------------------------------

    /** _a_tab: Refused (400) when [doing] names a version and [tab] names no UG tab. */
    fun aTab(tab: String, doing: String) {
        if (doing !in TABLESS && !Choices.digits(tab, MAX_TAB)) {
            throw Refused(400, "Not a version", "Which version? The address names no UG tab.")
        }
    }

    /** web.app.version_page_tab: the UG tab of a kept version's viewer page by its name ("version-39144.html"). */
    fun versionPageTab(name: String): String? =
        SheetVersions.tabOf(name)?.takeIf { SheetVersions.versionNames(it).third == name }

    /**
     * _asked: the song a viewer's library path names, as the phone wrote that viewer for it, and its version [tab]
     * (none for clear); Refused. A version's page goes once the version is the one (its viewer is sheet.html then):
     * the page asked from it still names its song, and Back to the sheet opens sheet.html.
     */
    fun asked(db: Db, readOverrides: () -> Overrides, rank: RankPolicy, sheet: String, tab: String,
              doing: String): VersionsAsked {
        aTab(tab, doing)
        val parts = sheet.split('/')
        if (parts.size < 2 || parts.any { it == "" || it == "." || it == ".." } ||
            !(parts.last() in VIEWERS || versionPageTab(parts.last()) != null)) {
            throw NO_SHEET
        }
        val overrides = readOverrides()
        val pageTab = versionPageTab(parts.last())
        val folder = parts.dropLast(1)
        val songs = Choices.songsInFolder(db, folder)
        var song = songs.firstOrNull { Choices.written(db, it.id, parts.last()) }
        val back = if (song == null && pageTab != null) {
            song = songs.firstOrNull { s -> SheetVersions.inLibrary(db, s.id, rank).any { it.tabId == pageTab && it.chosen } }
            "${folder.joinToString("/")}/${SheetVersions.SHEET_PAGE}"
        } else {
            sheet
        }
        if (song == null) throw NO_SHEET
        return of(db, overrides, rank, song, tab, doing, sheet, folder.joinToString("/") { quote(it) }, back)
    }

    /** _asked_song: the song a post names by its id (the library page's card), and its version [tab]; Refused. */
    fun askedSong(db: Db, overrides: Overrides, rank: RankPolicy, song: SongRow, tab: String, doing: String): VersionsAsked {
        val folder = SafeName.songFolder(song.artist, song.title).toList()
        val sheet = (folder + SheetVersions.SHEET_PAGE).joinToString("/")
        return of(db, overrides, rank, song, tab, doing, sheet, folder.joinToString("/") { quote(it) }, sheet)
    }

    /** _of: what a page or a post names once its song is found; Refused (404) for a [tab] that is none of the song's
     * versions. */
    private fun of(db: Db, overrides: Overrides, rank: RankPolicy, song: SongRow, tab: String, doing: String,
                   sheet: String, folder: String, back: String): VersionsAsked {
        val versions = SheetVersions.inLibrary(db, song.id, rank)
        val theOne = theOne(db, song.id, versions)
        val songPins = overrides.pin[song.key].orEmpty()
        val sheetPins = SheetVersions.sheetPins(db, song.id, songPins)
        val toKeep = SheetVersions.mayKeep(db, song.id, versions, overrides.block)
        val version = if (doing in TABLESS) null else versions.firstOrNull { it.tabId == tab }
            ?: throw Refused(404, "No such version", "UG lists no such chords version of ${song.display}.")
        return VersionsAsked(song, sheet, folder, version, versions, theOne, sheetPins, songPins, overrides.block, back,
                             toKeep)
    }

    /** _the_one: the song's sheet now, in words: its UG version, else the site or the auto-chords sheet it is; null
     * for a song that keeps no sheet. */
    private fun theOne(db: Db, songId: Long, versions: List<SheetVersion>): String? {
        versions.firstOrNull { it.chosen }?.let { return line(it) }
        val files = Kept.keptFiles(db, songId).associateBy { it.name }
        files[RenderNames.HUMAN_SHEET]?.let { file ->
            val provider = Versions.get(db, file.versionId)?.provider.orEmpty()
            return SOURCES[provider] ?: "$provider's sheet"
        }
        return if (RenderNames.AUTO_SHEET in files) SOURCES.getValue("auto") else null
    }

    private fun tabNumber(v: SheetVersion): Long? = v.tabId.toLongOrNull()

    /** _cant: why [doing] can't be done for what the page names, in one sentence; null when it can. */
    fun cant(doing: String, asked: VersionsAsked): String? {
        val v = asked.version
        if (doing == "clear") {
            return if (asked.pinned) null else "We pick ${asked.song.display}'s sheet already: none of yours is pinned."
        }
        if (doing == "keep-more") {
            return if (asked.toKeep.isNotEmpty()) null else "Nothing left to keep of ${asked.song.display}: every UG " +
                "version we may keep is kept, or can't be."
        }
        checkNotNull(v)
        if (v.gone) return "Gone from UG. Listed until the next fetch drops it."
        if (tabNumber(v)?.let { it in asked.blocked } == true && !v.chosen) {
            return "Under [block] in overrides.toml: we never use it. Take it out of [block] first."
        }
        if (doing == "choose" && v.chosen) return "Already the one: the song's title opens it."
        if (doing == "keep" && v.kept) {
            return if (v.chosen) "Already the one: the song's title opens it."
            else "Kept already, beside the sheet."
        }
        return null
    }

    /** _steps: the command [doing] queues, `caracole versions` (web/jobs.py's version_steps). */
    fun steps(doing: String, asked: VersionsAsked): List<Command> {
        val song = asked.song
        val tab = asked.version?.tabId
        return JobCommands.versionSteps(song.artist, song.title, keep = tab.takeIf { doing == "keep" },
                                        choose = tab.takeIf { doing == "choose" }, keepMore = doing == "keep-more")
    }

    /** _runs: whether the job runs these commands (another request of the song's may have joined it). */
    fun runs(job: Job, steps: List<Command>): Boolean {
        val held = job.steps.map { it.args }.toSet()
        return steps.all { it.args in held }
    }

    /** _query: the page's own address for [doing], with its [job]. */
    fun query(doing: String, asked: VersionsAsked, job: Int? = null): String {
        val fields = mutableListOf("sheet" to asked.sheet, "tab" to (asked.version?.tabId ?: ""), "do" to doing)
        if (job != null) fields += "job" to job.toString()
        return PyUrl.urlencode(fields)
    }

    /** A post's job's title. */
    fun title(doing: String, song: SongRow): String = when (doing) {
        "choose" -> "Choose a version: ${song.display}"
        "keep" -> "Keep a version of ${song.display}"
        "clear" -> "Back to our pick: ${song.display}"
        else -> "Fetch the other versions of ${song.display}"
    }

    // --- the page -------------------------------------------------------------------------------------------------

    /** _line: a version in a few words: "Ver 3 · 4.86★ (408)", or with [total], "Ver 3 of 13 · 4.86★ (408)". */
    fun line(v: SheetVersion, total: Int? = null): String {
        val first = (if (v.number != null && v.number != 0) "Ver ${v.number}" else "Tab ${v.tabId}") +
            (if (total != null && total != 0) " of $total" else "")
        val said = mutableListOf(first)
        v.rating?.let { rating -> said += "${PyFormat.general(rating)}★" + (v.votes?.let { " (${Looked.grouped(it.toLong())})" } ?: "") }
        return said.joinToString(" · ")
    }

    private val LABELS = mapOf("choose" to "Make this the one", "keep" to "Keep", "clear" to "Back to our pick")
    private val TELLS = mapOf(
        "choose" to "It becomes the song's sheet: the title opens it, its PDF and songbooks use it. We fetch the song " +
            "with this tab (<code>caracole versions --choose</code>) and note your choice in overrides.toml " +
            "(<code>[pin]</code>).",
        "keep" to "We fetch its page from UG (one ask) and keep it beside the song's sheet, with its own viewer. The " +
            "sheet stays as it is.",
        "clear" to "We take the song's <code>[pin]</code> out of overrides.toml and fetch it again: the title then " +
            "opens the version we rank first.",
    )
    private val RUNNING = mapOf("choose" to "Making it the one…", "keep" to "Fetching the version…",
                                "clear" to "Going back to our pick…")
    private val TITLES = mapOf("choose" to "Make this the one", "keep" to "Keep a version",
                               "clear" to "Back to our pick")

    /** _body: the page of [doing] for what [asked] names, [job] the request it follows, if any (once it is done,
     * what it came to is read from [db] again), its form carrying [csrf], the library named as [name]. */
    fun page(db: Db, doing: String, asked: VersionsAsked, job: Job?, csrf: String, name: LibraryName): Response {
        val song = asked.song
        val v = asked.version
        var lede = if (v != null) {
            "${esc(song.display)}: <strong>${esc(line(v, asked.versions.size))}</strong>." +
                (v.note?.takeIf { it.isNotEmpty() }?.let { " <q>${esc(it)}</q>" } ?: "")
        } else {
            "${esc(song.display)}."
        }
        lede = "<p class=\"lede\">$lede</p>\n"
        if (asked.theOne != null) lede += "<p>The one now: ${esc(asked.theOne)}.</p>\n"
        val why = cant(doing, asked)
        val form = if (why != null) {
            "<p>${esc(why)}</p>\n"
        } else {
            val hidden = listOf("csrf" to csrf, "sheet" to asked.sheet, "tab" to (v?.tabId ?: "")).joinToString("") {
                (field, value) -> "  <input type=\"hidden\" name=\"$field\" value=\"${esc(value)}\">\n"
            }
            "<form class=\"confirm\" method=\"post\" action=\"/versions/$doing\">\n$hidden" +
                "  <button class=\"btn primary\" type=\"submit\">${LABELS.getValue(doing)}</button>\n</form>\n" +
                "<p>${TELLS.getValue(doing)}</p>\n"
        }
        val (says, opens) = howItGoes(db, doing, asked, job)
        var links = opens
        val page = v?.page
        if (page != null && v.kept && !v.chosen && opens.isEmpty()) {
            links += "<a class=\"btn\" href=\"/${asked.folder}/${quote(page)}\">Open</a>\n"
        }
        links += "<a class=\"btn\" href=\"/${esc(quote(asked.back))}\">Back to sheet</a>"
        return Choices.page(200, "${TITLES.getValue(doing)} · ${song.display}",
                            "$lede$form$says<div class=\"confirm\">\n$links\n</div>", name, Choices.refresh(job))
    }

    /** _how_it_goes: the job's state in a sentence, and once it is done, a link to what it made: the sheet, or the
     * kept version's page once the phone wrote it. */
    private fun howItGoes(db: Db, doing: String, asked: VersionsAsked, job: Job?): Pair<String, String> {
        if (job == null) return "" to ""
        val details = esc(Status.detailsHref(job.id))
        when (job.state) {
            Job.FAILED -> {
                val last = Choices.lastLine(job)
                return "<p class=\"says failed\">Failed${if (last.isNotEmpty()) ": " + esc(last) else "."} " +
                    "<a href=\"/$details\">Output</a></p>\n" to ""
            }
            Job.CANCELLED -> return "<p class=\"says cancelled\">Cancelled before it ran.</p>\n" to ""
            Job.INTERRUPTED -> return "<p class=\"says waiting\">Interrupted: the server stopped mid-way. " +
                "<a href=\"/$details\">Output</a></p>\n" to ""
        }
        if (job.state != Job.DONE) {
            val state = if (job.state == Job.QUEUED) "Queued · runs after those ahead." else RUNNING.getValue(doing)
            return "<p class=\"says ${job.state}\">${esc(state)}</p>\n" to ""
        }
        val output = "<a href=\"/$details\">output</a>"
        if (doing == "keep") {
            val v = checkNotNull(asked.version)
            val page = SheetVersions.versionNames(v.tabId).third
            if (!Choices.written(db, asked.song.id, page)) {
                val why = stageDetail(job, "version")
                return "<p class=\"says failed\">Done, not kept${if (why.isNotEmpty()) ": " + esc(why) else ""}. " +
                    "See the <a href=\"/$details\">output</a>.</p>\n" to ""
            }
            return "<p class=\"says done\">Done · kept beside the sheet.</p>\n" to
                "<a class=\"btn primary\" href=\"/${asked.folder}/${quote(page)}\">Open</a>\n"
        }
        // caracole get exits 0 on a block, a spent budget or the hour's cap, the sheet as it was: what the job did is
        // the song's state, read again, never the command's exit.
        val said = if (doing == "choose") {
            val v = checkNotNull(asked.version)
            if (!v.chosen) {
                val why = stageDetail(job, "sheet")
                val words = if (tabNumber(v)?.let { it in asked.pins } == true) {
                    "Done. Your choice is noted under [pin], but isn't the sheet yet: tonight's run or a later " +
                        "fetch makes it the one"
                } else {
                    "Done, but not the one"
                }
                return "<p class=\"says waiting\">${esc(words)}${if (why.isNotEmpty()) ": " + esc(why) else "."} See the " +
                    "$output.</p>\n" to ""
            }
            "Done · the one now."
        } else if (asked.pinned) {
            return "<p class=\"says failed\">Done, but the [pin] remains. See the $output.</p>\n" to ""
        } else {
            "Done · we pick the sheet again."
        }
        return "<p class=\"says done\">$said</p>\n" to
            "<a class=\"btn primary\" href=\"/${asked.folder}/${quote(SheetVersions.SHEET_PAGE)}\">Open sheet</a>\n"
    }

    /** _stage_detail: what the job's stage [stage] said when it ended, when it ended skipped or failed ("" else). */
    private fun stageDetail(job: Job, stage: String): String {
        val s = job.stages.firstOrNull { it.name == stage } ?: return ""
        return if (s.state == Job.SKIPPED || s.state == Job.FAILED) Py.strip(s.detail).trimEnd('.') else ""
    }
}
