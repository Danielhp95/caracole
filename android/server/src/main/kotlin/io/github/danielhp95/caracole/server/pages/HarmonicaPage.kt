package io.github.danielhp95.caracole.server.pages

import io.github.danielhp95.caracole.core.db.Db
import io.github.danielhp95.caracole.core.inbox.HarmonicaFile
import io.github.danielhp95.caracole.core.inbox.HarmonicaFiles
import io.github.danielhp95.caracole.core.json.PyJson
import io.github.danielhp95.caracole.core.keys.Normalize
import io.github.danielhp95.caracole.core.library.Kept
import io.github.danielhp95.caracole.core.library.Overrides
import io.github.danielhp95.caracole.core.library.SongRow
import io.github.danielhp95.caracole.core.py.PyFormat
import io.github.danielhp95.caracole.core.py.PyRe
import io.github.danielhp95.caracole.core.py.PyText
import io.github.danielhp95.caracole.server.http.LibraryName
import io.github.danielhp95.caracole.server.http.Refused
import io.github.danielhp95.caracole.server.http.Response
import io.github.danielhp95.caracole.server.jobs.Job
import io.github.danielhp95.caracole.server.jobs.JobCommands
import io.github.danielhp95.caracole.server.jobs.Status
import io.github.danielhp95.caracole.server.pages.Choices.esc
import io.github.danielhp95.caracole.server.pages.Choices.quote
import io.github.danielhp95.caracole.viewer.harptab.HarpTabs
import io.github.danielhp95.caracole.viewer.harptab.Notation
import io.github.danielhp95.caracole.viewer.harptab.Reading
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import java.io.File

/**
 * What a page of a harmonica tab's readings or a post names (harmonica_routes._Asked): the song, the tab's page (its
 * library path) and its folder (quoted), the tab, its text, how overrides.toml has it read ([pin], null for caracole's
 * guess), and how it is read now.
 */
internal class HarmonicaAsked(val song: SongRow, val page: String, val folder: String, val tab: HarmonicaFile,
                              val text: String, val pin: JsonElement?, val now: Reading) {
    /** Its page's name in the song's folder ("harmonica-1.html"). */
    val pageName: String get() = page.substringAfterLast('/')
}

/**
 * caracole serve's page of how a harmonica tab is read, on the phone (web/harmonica_routes.py), in its words: the
 * readings caracole weighs for it, best first (HarpTabs.readings), each with its Q and a form that pins it in
 * overrides.toml's `[harmonica]`, harptabs.com's own notation among them, and Back to caracole's guess for a pinned
 * tab; with `&job=`, how the request goes, read again from the overrides once it is done.
 */
internal object HarmonicaPage {
    /** harmonica_routes.COMMAND: the command a post queues. */
    const val COMMAND = "harmonica"

    private val NO_TAB get() = Refused(404, "Not found", "There's no such harmonica tab in the library.")
    private val NOT_A_READING get() =
        Refused(400, "Not a reading", "How should it be read? The form names no notation caracole knows.")

    /** harmonica_cmd.SOURCES: where a reading came from, in words. */
    val SOURCES = mapOf("legend" to "from the tab's own legend", "pinned" to "as you set it", "guessed" to "guessed")

    // --- what a page or a post names ------------------------------------------------------------------------------

    /** _reading: the reading a form posts, a notation's name, "legend", or a table as JSON (HarpTabs.checkSpec's);
     * Refused (400) else. */
    fun reading(text: String): JsonElement {
        val spec: JsonElement = if (text.startsWith("{")) {
            try {
                PyJson.loads(text)
            } catch (_: PyJson.DecodeError) {
                throw NOT_A_READING
            }
        } else {
            JsonPrimitive(text)
        }
        try {
            HarpTabs.checkSpec(spec)
        } catch (_: IllegalArgumentException) {
            throw NOT_A_READING
        }
        return spec
    }

    /** harmonica_cmd.tab_text: the tab's text as the library holds it (read without following a link, its bytes
     * decoded with replacement), or null when it can't be read. */
    fun tabText(db: Db, libraryDir: File, song: SongRow, tab: HarmonicaFile): String? {
        val kept = Kept.keptFiles(db, song.id).firstOrNull { it.name == tab.name } ?: return null
        val bytes = Choices.readRegular(File(libraryDir, kept.path)) ?: return null
        return PyText.utf8(bytes, replace = true)
    }

    /** _asked: the song and the harmonica tab a page's library path names, as the phone wrote that page for it;
     * Refused (404) for anything else. */
    fun asked(db: Db, readOverrides: () -> Overrides, libraryDir: File, page: String): HarmonicaAsked {
        val parts = page.split('/')
        if (parts.size != 3 || parts.any { it == "" || it == "." || it == ".." } ||
            PyRe.fullmatch(HarmonicaFiles.PAGE, parts.last()) == null) {
            throw NO_TAB
        }
        val overrides = readOverrides()
        val song = Choices.songsInFolder(db, parts.dropLast(1)).firstOrNull { Choices.written(db, it.id, parts.last()) }
            ?: throw NO_TAB
        val tab = HarmonicaFiles.of(db, song.id).firstOrNull { it.page == parts.last() }
            ?: throw NO_TAB
        val text = tabText(db, libraryDir, song, tab) ?: throw NO_TAB
        val pin = overrides.harmonica[song.key]?.get(tab.name)
        val notation: Notation? = pin?.let {
            try {
                HarpTabs.pinned(it, text)
            } catch (_: IllegalArgumentException) {
                null
            }
        }
        val now = HarpTabs.parse(text, tab.harp, notation).reading
        return HarmonicaAsked(song, page, parts.dropLast(1).joinToString("/") { quote(it) }, tab, text, pin, now)
    }

    /** Whether [job] is a request of this page's: the tab's reading (its key's prefix), `caracole harmonica`. */
    fun ofPage(job: Job, asked: HarmonicaAsked): Boolean =
        job.key.startsWith("${JobCommands.READING}${asked.song.key}:${asked.tab.name}:") &&
            job.steps.isNotEmpty() && job.steps[0].args.firstOrNull() == COMMAND

    // --- the page -------------------------------------------------------------------------------------------------

    private fun said(reading: Reading): String = reading.said().ifEmpty { "no hole read" }

    private fun source(reading: Reading): String = SOURCES.getValue(reading.source)

    private fun isText(spec: JsonElement): Boolean = spec is JsonPrimitive && spec.isString

    private fun button(spec: JsonElement, reading: Reading): String = when {
        spec == JsonPrimitive("legend") -> "Read it by its own legend"
        spec == JsonPrimitive("signs") -> "As harptabs.com writes it"
        isText(spec) -> "Read it as ${(spec as JsonPrimitive).content}"
        else -> "Read it so: ${said(reading)}"
    }

    /** A reading as a form posts it: a notation's name as it is, a table as `json.dumps(spec, ensure_ascii=False)`. */
    fun posted(spec: JsonElement): String = if (isText(spec)) (spec as JsonPrimitive).content else PyJson.dumps(spec)

    private fun form(asked: HarmonicaAsked, csrf: String, action: String, button: String, spec: JsonElement? = null): String {
        val fields = mutableListOf("csrf" to csrf, "page" to asked.page)
        if (spec != null) fields += "as" to posted(spec)
        val hidden = fields.joinToString("") { (name, value) ->
            "  <input type=\"hidden\" name=\"$name\" value=\"${esc(value)}\">\n"
        }
        return "<form class=\"confirm\" method=\"post\" action=\"$action\">\n$hidden" +
            "  <button class=\"btn\" type=\"submit\">${esc(button)}</button>\n</form>\n"
    }

    /** _body: the page of what [asked] names, [job] the request it follows, if any, its forms carrying [csrf], the
     * library named as [name]. */
    fun page(asked: HarmonicaAsked, job: Job?, csrf: String, name: LibraryName): Response {
        val song = asked.song
        val tab = asked.tab
        val now = asked.now
        val listed = HarpTabs.readings(asked.text, tab.harp).toMutableList()
        val specs = listed.map { HarpTabs.specOf(it) }.toMutableList()
        val current = asked.pin ?: specs[0]
        val at = specs.indexOf(current)
        val weighed = if (at >= 0) listed[at].q else now.q  // its Q among the others'
        val lede = "<p class=\"lede\">${esc(Normalize.cleanTitle(song.title))} · ${esc(song.artist)}, ${esc(tab.name)}</p>\n" +
            "<p>Now: ${esc(said(now))}, ${esc(source(now))} (Q ${PyFormat.fixed(weighed, 2)}).</p>\n"
        if (asked.pin != null && asked.pin !in specs) {  // a pin of yours caracole weighs no candidate for
            listed.add(0, now)
            specs.add(0, asked.pin)
        }
        val signs = JsonPrimitive("signs")
        if (signs !in specs) {  // harptabs.com's own key, always offered: a reading alike, but less common, took its place
            listed += HarpTabs.parse(asked.text, tab.harp, HarpTabs.pinned(signs, asked.text)).reading
            specs += signs
        }
        val items = listed.zip(specs).map { (reading, spec) ->
            val mine = spec == current
            val form = if (mine && asked.pin != null) "" else form(asked, csrf, "/harmonica/pin", button(spec, reading), spec)
            "<li class=\"reading${if (mine) " now" else ""}\"><span class=\"said\">${esc(said(reading))}</span> " +
                "<span class=\"q\">Q ${PyFormat.fixed(reading.q, 2)}${if (mine) " · now" else ""}</span>\n$form</li>"
        }
        var body = lede + "<h2 class=\"sub\">The ways caracole weighs, best first</h2>\n<ul class=\"readings\">\n" +
            items.joinToString("\n") + "\n</ul>\n"
        if (asked.pin != null) body += form(asked, csrf, "/harmonica/clear", "Back to caracole's guess")
        body += "<p>caracole reads a harmonica tab in each notation it knows and keeps the one that explains the most " +
            "of it as notes a harmonica plays (Q). One you choose here is kept in overrides.toml " +
            "(<code>[harmonica]</code>), and the tab's page is made again.</p>\n"
        body += howItGoes(asked, job)
        val back = "<a class=\"btn\" href=\"/${asked.folder}/${quote(asked.pageName)}\">Back to the tab</a>"
        return Choices.page(200, "How it's read · ${song.display}", "$body<div class=\"confirm\">\n$back\n</div>", name,
                            Choices.refresh(job))
    }

    /** _how_it_goes: the job's state in a sentence, and once it is done, what it came to: the overrides, read
     * again. */
    private fun howItGoes(asked: HarmonicaAsked, job: Job?): String {
        if (job == null) return ""
        val details = esc(Status.detailsHref(job.id))
        when (job.state) {
            Job.FAILED -> {
                val last = Choices.lastLine(job)
                return "<p class=\"says failed\">Failed${if (last.isNotEmpty()) ": " + esc(last) else "."} " +
                    "<a href=\"/$details\">Output</a></p>\n"
            }
            Job.CANCELLED -> return "<p class=\"says cancelled\">Cancelled before it ran.</p>\n"
            Job.INTERRUPTED -> return "<p class=\"says waiting\">Interrupted: caracole serve stopped before it was " +
                "over. <a href=\"/$details\">Output</a></p>\n"
        }
        if (job.state != Job.DONE) {
            val state = if (job.state == Job.QUEUED) "Queued: it runs after the requests before it." else "Reading it as you set it…"
            return "<p class=\"says ${job.state}\">${esc(state)}</p>\n"
        }
        val clearing = "--clear" in job.steps[0].args
        if (clearing) {
            if (asked.pin == null) return "<p class=\"says done\">Done: caracole guesses how it is read again.</p>\n"
            return "<p class=\"says failed\">Done, but the [harmonica] entry is still there: see the request's " +
                "<a href=\"/$details\">output</a>.</p>\n"
        }
        if (asked.pin == null) {
            return "<p class=\"says failed\">Done, but no [harmonica] entry pins it: see the request's " +
                "<a href=\"/$details\">output</a>.</p>\n"
        }
        return "<p class=\"says done\">Done: read as ${esc(said(asked.now))}, as you set it.</p>\n"
    }

    /** The command a post queues, its title, its label, and the reading its key names: `caracole harmonica --tab=…
     * --as=… [--symbol=…]` or `--clear`. */
    fun command(asked: HarmonicaAsked, spec: JsonElement?): Triple<String, String, List<String>> {
        val song = asked.song
        val tab = asked.tab
        if (spec == null) {
            return Triple("Back to caracole's guess: ${tab.name} of ${song.display}", "Going back to caracole's guess",
                          listOf("--clear"))
        }
        val options = if (isText(spec)) {
            listOf("--as=${(spec as JsonPrimitive).content}")
        } else {
            val table = spec as JsonObject
            listOf("--as=${(table["as"] as? JsonPrimitive)?.content ?: "signs"}") +
                table.filterKeys { it != "as" }.map { (k, v) -> "--symbol=$k=${(v as JsonPrimitive).content}" }
        }
        return Triple("Read ${tab.name} of ${song.display} as you set it", "Reading the harmonica tab as you set it",
                      options)
    }

    /** The job's key: jobs.READING, the song's key, the tab, the reading as `json.dumps(spec, sort_keys=True,
     * ensure_ascii=False)` ("clear" for none), then jobs.MINE. */
    fun key(asked: HarmonicaAsked, spec: JsonElement?): String {
        val said = if (spec == null) "clear" else PyJson.dumps(spec, sortKeys = true)
        return "${JobCommands.READING}${asked.song.key}:${asked.tab.name}:$said${JobCommands.MINE}"
    }
}
