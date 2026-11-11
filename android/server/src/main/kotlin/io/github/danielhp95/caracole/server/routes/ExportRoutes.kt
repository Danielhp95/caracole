package io.github.danielhp95.caracole.server.routes

import io.github.danielhp95.caracole.core.db.Db
import io.github.danielhp95.caracole.core.keys.Normalize
import io.github.danielhp95.caracole.core.keys.SafeName
import io.github.danielhp95.caracole.core.library.SongRow
import io.github.danielhp95.caracole.core.library.Songs
import io.github.danielhp95.caracole.core.py.PyRe
import io.github.danielhp95.caracole.core.py.PyRegex
import io.github.danielhp95.caracole.core.py.PyUrl
import io.github.danielhp95.caracole.core.ug.SheetVersions
import io.github.danielhp95.caracole.core.web.DownloadNames
import io.github.danielhp95.caracole.mirror.Mirror
import io.github.danielhp95.caracole.server.PhoneParts
import io.github.danielhp95.caracole.server.http.GetAnswer
import io.github.danielhp95.caracole.server.http.Refused
import io.github.danielhp95.caracole.server.http.Request
import io.github.danielhp95.caracole.server.http.Response
import io.github.danielhp95.caracole.server.http.Route
import io.github.danielhp95.caracole.server.http.RouteModule
import io.github.danielhp95.caracole.server.jobs.Command
import io.github.danielhp95.caracole.server.jobs.JobCommands
import io.github.danielhp95.caracole.server.jobs.JobSpec
import io.github.danielhp95.caracole.server.page.MirrorPageData
import io.github.danielhp95.caracole.server.page.PhonePageData
import io.github.danielhp95.caracole.server.page.SongCards
import io.github.danielhp95.caracole.server.routes.library.Answers
import io.github.danielhp95.caracole.server.routes.lookup.LookupForms
import io.github.danielhp95.caracole.viewer.render.WrittenPages
import io.github.danielhp95.caracole.viewer.version.Version
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive

/**
 * Export PDF on the phone (web/export_routes.py), which prints the viewer it shows (the app's Printer, Android's print
 * framework) and makes no PDF:
 *
 *     GET  /export.pdf?sheet=   the version a sheet viewer's address holds (`sheet`: the viewer's library path, then
 *                               its address after #), named: {"name", "label"}, the download name caracole serve's
 *                               PDF has and the version's label; with `mine=1`, Make this my version queued too
 *
 * Every check is caracole serve's, in its words ([asked]): an address that can't be read (400), a version that can't
 * be (400: past [MAX_QUERY] characters, a control character in a value), a viewer that is no sheet the library keeps
 * (404), the auto sheet's viewer kept beside a human sheet and a kept version's page (409: their export would be the
 * human sheet's, with another sheet's chords), a song's sheet the viewer's code can't read (404). A viewer is a
 * sheet's of the library where caracole wrote it ([written]): the phone's own page, as render.written_file reads its
 * record, or the computer's the mirror holds for the song. An address naming no version is the song's own (render.py
 * `export_version`); the label is the PDF's (`ExportSheet.label`), in Traditional characters where the address says
 * `trad=1` of a Chinese sheet. Making no PDF, the phone names any version the viewer's code can read: where caracole
 * serve refuses one whose PDF can't be made (500, "No PDF": chordpro failing, a CJK font missing, the version's text
 * that `_export_text` can't make), the phone, which prints the page, answers it; its own 500 is a label that can't be
 * made.
 *
 * With `mine=1` (a GET; a HEAD changes nothing) it queues `caracole render --song=… --version=… --mine` under
 * `export:<key>:<version>:mine` (jobs.EXPORTING, jobs.MINE), never the song's own key, which the render runner runs:
 * the song's `[version]` written as the key it plays in, then its pages made again. A plain link, with no form token
 * and no cross-origin check, as on the computer: the owner's one exception, the phone's one write without the token
 * (ExportRoutesTest checks every other is refused). A full queue refuses it (503), the version unnamed.
 *
 * vectors/web/export.jsonl holds every answer to caracole serve's (ExportReplay). [mirror] is the copy of the
 * computer's pages, the cards' (PhonePageData's), whose viewers are the library's as the phone's own are.
 */
class ExportRoutes(val parts: PhoneParts, private val mirror: () -> Mirror? = { mirrorOf(parts.cards) }) : RouteModule {
    /** What an export names: its song, and the version its address holds. */
    class Exported(val song: SongRow, val version: Version)

    override val routes: List<Route> = listOf(
        Route("GET", "/export.pdf", "a sheet's version named for its print (sheet, its address; mine)",
              get = GetAnswer { export(it) }),
    )

    /** export_routes.export_pdf: the version named, and with `mine=1` (unless a HEAD) Make this my version queued. */
    fun export(request: Request): Response {
        val change = request.method == "GET"
        val query = try {
            PyUrl.urlsplit(request.target).query
        } catch (e: PyUrl.Invalid) {
            throw NOT_AN_ADDRESS
        }
        val params = parseQsl(query)
        if (query.codePointCount(0, query.length) > MAX_QUERY || params.any { unreadable(it.second) }) {
            throw NOT_A_VERSION
        }
        val sheet = params.firstOrNull { it.first == "sheet" }?.second ?: ""
        val mine = params.firstOrNull { it.first == "mine" }?.second == "1"
        val asked = PyUrl.urlencode(params.filter { it.first != "sheet" && it.first != "mine" })
        val (exported, label) = parts.database.read { db ->
            val (found, export) = asked(db, sheet, asked)
            val label = try {
                export.label(found.version, traditional = Exports.traditional(asked))
            } catch (e: ExportError) {
                throw Refused(500, "No PDF", "Couldn't make the PDF: ${e.message}")
            }
            found to label
        }
        val song = exported.song
        if (mine && change) {
            val version = Exports.query(exported.version)
            parts.queue.submitOrRefuse(mineJob(song, version))
        }
        val name = DownloadNames.downloadName(song.artist, "${Normalize.cleanTitle(song.title)} ($label)", PDF_NAME)
        return Answers.json(JsonObject(linkedMapOf("name" to JsonPrimitive(name), "label" to JsonPrimitive(label))))
    }

    /**
     * export_routes._version: the song a viewer's path names and the version [query] holds, with the sheet its
     * exports are made from; refused as caracole serve refuses it.
     */
    fun asked(db: Db, sheet: String, query: String): Pair<Exported, ExportSheet> {
        val pieces = sheet.split('/')
        if (pieces.size < 2 || sheet.isEmpty() || pieces.any { it == "" || it == "." || it == ".." } ||
            !writtenPage(pieces.last())) {
            throw NOT_FOUND
        }
        val overrides = LookupForms.overrides(db)
        val folder = pieces.dropLast(1)
        val name = pieces.last()
        val song = Songs.list(db).firstOrNull { s ->
            SafeName.songFolder(s.artist, s.title).toList() == folder && written(db, s, folder, name)
        } ?: throw NOT_FOUND
        if (name != Exports.viewer(db, song.id)) {
            if (name == Exports.AUTO_VIEWER) throw Refused(409, "Not this sheet", BESIDE)
            if (versionPageTab(name) != null) throw Refused(409, "Not this sheet", VERSION)
            throw NOT_FOUND
        }
        return try {
            val export = Exports.sheet(db, parts.store.libraryDir, song)
            Exported(song, Exports.version(query, export.own(overrides))) to export
        } catch (e: ExportError) {
            throw Refused(404, "No sheet to export", e.message ?: "")
        }
    }

    /**
     * render.written_file on the phone: whether caracole wrote the viewer [name] in the song's [folder], the phone
     * (its record, kv `render:files:<id>`) or the computer (the mirror's page of it, listed under the song's unit).
     */
    private fun written(db: Db, song: SongRow, folder: List<String>, name: String): Boolean {
        if (WrittenPages.written(db, song.id, name) != null) return true
        val served = mirror()?.lookup((folder + name).joinToString("/")) ?: return false
        return served.entry.unit == "song/${song.key}"
    }

    /** The job Make this my version queues: `caracole render --song=… --version=… --mine` under the song's export key. */
    private fun mineJob(song: SongRow, version: String): JobSpec {
        val commands = listOf(Command(MAKING, listOf("render", "--song=${song.display}", "--version=$version", "--mine")))
        return JobSpec("Make ${song.display} your version", "${JobCommands.EXPORTING}${song.key}:$version${JobCommands.MINE}",
                       "export", JobCommands.stages(commands.map { it.args }), display = song.display,
                       songId = song.id, commands = commands)
    }

    companion object {
        /** export_routes.MAX_QUERY: a version with every chord's shape and swap is a few hundred characters. */
        const val MAX_QUERY = 2000

        /** parse_qsl's max_num_fields. */
        const val MAX_FIELDS = 60

        /** The step Make this my version's job runs, as caracole serve labels it. */
        const val MAKING = "Making it your version"

        /** The file name an export's download name is made from (download_names.download_name's). */
        private const val PDF_NAME = "sheet.pdf"

        private val NOT_AN_ADDRESS get() = Refused(400, "Not an address", "Can't read that address.")
        private val NOT_A_VERSION get() = Refused(400, "Not a version", "Can't read that version.")
        private val NOT_FOUND get() = Refused(404, "Not found", "No such sheet in the book.")
        private const val BESIDE = "This is the auto-chords sheet kept beside the song's own. A PDF in another " +
            "version comes from the song's own sheet: open that from the book and export it."
        private const val VERSION = "This is a version kept beside the song's own. A PDF in another version comes " +
            "from the song's own sheet: make this one the one first (Make this the one, under Versions), then export " +
            "from the song's sheet."

        /** app.written_pages' names: the sheets' viewers, a songbook's page and the library page. */
        private val WRITTEN = setOf(Exports.HUMAN_VIEWER, Exports.AUTO_VIEWER, "songbook.html", "index.html")

        /** inbox.HARMONICA_PAGE, Python's \d. */
        private val HARMONICA_PAGE: Regex by lazy { PyRegex.compile("""harmonica-(\d+)\.html""") }

        /** The mirror the cards read, PhonePageData's (the phone's) or MirrorPageData's (a test's); null for none. */
        fun mirrorOf(cards: SongCards): Mirror? = when (cards) {
            is PhonePageData -> cards.mirror.mirror
            is MirrorPageData -> cards.mirror
            else -> null
        }

        /** app.written_page: whether [name] is a page caracole writes into the library. */
        fun writtenPage(name: String): Boolean =
            name in WRITTEN || versionPageTab(name) != null || PyRe.fullmatch(HARMONICA_PAGE, name) != null

        /** app.version_page_tab: the UG tab of a kept version's viewer page by its name ("version-39144.html"). */
        fun versionPageTab(name: String): String? {
            val tab = SheetVersions.tabOf(name) ?: return null
            return if (SheetVersions.versionNames(tab).third == name) tab else null
        }

        /**
         * `parse_qsl(query, keep_blank_values=True, errors="strict", max_num_fields=60)`: each field's name and value,
         * in order, '+' a space; [NOT_AN_ADDRESS] for more than [MAX_FIELDS] fields (1 + its `&`s) or an escape that
         * isn't UTF-8.
         */
        fun parseQsl(query: String): List<Pair<String, String>> {
            if (query.isEmpty()) return emptyList()
            if (MAX_FIELDS < 1 + query.count { it == '&' }) throw NOT_AN_ADDRESS
            val out = ArrayList<Pair<String, String>>()
            for (field in query.split('&')) {
                if (field.isEmpty()) continue
                val at = field.indexOf('=')
                val name = if (at >= 0) field.substring(0, at) else field
                val value = if (at >= 0) field.substring(at + 1) else ""
                try {
                    out += PyUrl.unquote(name.replace('+', ' '), strict = true) to
                        PyUrl.unquote(value.replace('+', ' '), strict = true)
                } catch (e: PyUrl.Invalid) {
                    throw NOT_AN_ADDRESS
                }
            }
            return out
        }

        /** export_routes._unreadable: whether [text] holds a control character, which no sheet's address does. */
        fun unreadable(text: String): Boolean = text.any { it.code < 32 || it.code == 127 }
    }
}
