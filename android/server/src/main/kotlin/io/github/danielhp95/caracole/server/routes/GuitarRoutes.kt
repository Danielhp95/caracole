package io.github.danielhp95.caracole.server.routes

import io.github.danielhp95.caracole.core.inbox.GuitarFiles
import io.github.danielhp95.caracole.core.keys.SafeName
import io.github.danielhp95.caracole.core.library.SongRow
import io.github.danielhp95.caracole.core.library.Songs
import io.github.danielhp95.caracole.core.py.Py
import io.github.danielhp95.caracole.core.py.PyPath
import io.github.danielhp95.caracole.core.py.PyText
import io.github.danielhp95.caracole.core.py.PyUrl
import io.github.danielhp95.caracole.mirror.Mirror
import io.github.danielhp95.caracole.server.PhoneParts
import io.github.danielhp95.caracole.server.files.FileTypes
import io.github.danielhp95.caracole.server.guitar.AlphaTab
import io.github.danielhp95.caracole.server.guitar.AlphaTabBundle
import io.github.danielhp95.caracole.server.guitar.GuitarPage
import io.github.danielhp95.caracole.server.http.App
import io.github.danielhp95.caracole.server.http.Body
import io.github.danielhp95.caracole.server.http.GetAnswer
import io.github.danielhp95.caracole.server.http.LibraryName
import io.github.danielhp95.caracole.server.http.MessagePage
import io.github.danielhp95.caracole.server.http.Refused
import io.github.danielhp95.caracole.server.http.Request
import io.github.danielhp95.caracole.server.http.Response
import io.github.danielhp95.caracole.server.http.Route
import io.github.danielhp95.caracole.server.http.RouteModule
import io.github.danielhp95.caracole.server.page.MirrorPageData
import io.github.danielhp95.caracole.server.page.PhonePageData
import java.io.File
import java.io.IOException
import java.nio.file.Files
import java.nio.file.InvalidPathException
import java.nio.file.LinkOption
import java.nio.file.Path
import java.nio.file.attribute.BasicFileAttributes

/**
 * web/guitar_routes.py on the phone: the Guitar Pro page, a song's kept Guitar Pro file drawn and played by alphaTab
 * (GuitarPage), answered as caracole serve answers it (vectors/web/guitar.jsonl).
 *
 *     GET /guitar?file=           the page of a Guitar Pro file caracole keeps (`file`: its path in the library)
 *     GET /assets/alphatab/<name> alphaTab's bundle, which that page loads: to any origin, kept for good
 *
 * `/guitar` shows only a file the phone's library records as a song's Guitar Pro file (GuitarFiles.of: a
 * `guitar-N.<ext>` in `files`) in a format alphaTab reads: any other path, a Power Tab file, a file gone, a link in its
 * place or a folder of the path that is one is refused (404); past 8 MiB, 413. The page is made for each request,
 * nothing is written, and it is served in a sandbox with its own policy.
 *
 * The bundle is [alphaTab]'s: on the phone the APK's (AlphaTabBundle.installed), which the app's WebView answers from
 * its assets before any request reaches the server (AlphaTabAssets), since the sandboxed page's request for it carries
 * no launch cookie; this route answers it only where it holds the bundle's bytes (the JVM's tests). Without a bundle
 * `/guitar` says so (503), as caracole serve without `CARACOLE_ALPHATAB_DIR` does, and the library page offers Guitar
 * Pro files as downloads ([available], ServerControls.guitar). The pages name the library as [libraryName] says.
 *
 * What the phone does beyond caracole serve: a path its library records no Guitar Pro file at, that the computer's
 * pages copied to the phone list as a file ([mirrored]: the mirror's, a song only the mirror has), is the file
 * itself, a 303 to its address, which the app hands to another app as it does any file of the library: the link a
 * mirrored viewer or library page gives it goes where it went before the phone had this page.
 */
class GuitarRoutes(
    val parts: PhoneParts,
    private val alphaTab: () -> AlphaTab? = AlphaTabBundle::installed,
    private val libraryName: () -> LibraryName = { LibraryName.phone(parts.config().libraryName) },
    private val mirrored: (String) -> Boolean = { path -> mirrorOf(parts)?.lookup(path)?.entry?.isPage == false },
) : RouteModule {
    override val routes: List<Route> = listOf(
        Route("GET", "/guitar", "the page of a Guitar Pro file caracole keeps (file: its path in the library)",
              get = GetAnswer { guitar(it.target) }),
        Route("GET", ASSETS, "alphaTab's bundle, which that page loads: to any origin, kept for good", under = true,
              get = GetAnswer { asset(address(it).substring(ASSETS.length)) }),
    )

    /** guitar_routes.guitar: `GET /guitar?file=…`, the page of a song's Guitar Pro file. */
    fun guitar(target: String): Response {
        val fields = try {
            fields(PyUrl.urlsplit(target).query)
        } catch (e: PyUrl.Invalid) {
            throw Refused(400, "Not an address", "That address can't be read.")
        }
        val asked = fields["file"].orEmpty()
        if (asked.size != 1) throw notKept()
        val path = asked[0]
        if (path.isEmpty() || Py.len(path) > MAX_PATH || path.any { it.code < 32 }) throw notKept()
        val at = alphaTab() ?: throw Refused(503, "No alphaTab here", NO_ALPHATAB)
        val kept = parts.database.read { db ->
            GuitarFiles.of(db, path = path).firstOrNull()?.let { file ->
                if (!file.inBrowser) throw Refused(404, "A Power Tab file", POWER_TAB)
                file to (Songs.byId(db, file.songId) ?: throw Refused(404, "No such song", NO_SUCH_SONG))
            }
        }
        if (kept == null) {
            if (mirrored(path)) return Response(303, Body.Empty, mutableListOf("Location" to "/" + PyUrl.quote(path)))
            throw notKept()
        }
        val (file, song) = kept
        val data = readLibraryFile(path) ?: throw Refused(404, "Not in the library", GONE)
        if (data.size > MAX_FILE) throw Refused(413, "Too large", TOO_LARGE)
        val html = GuitarPage.build(
            title = song.title, artist = song.artists.ifEmpty { listOf(song.artist) }.joinToString(", "),
            songId = song.id, path = path, label = "Guitar Pro ${file.number}", data = data, at = at,
            sheet = viewerOf(song), libraryName = libraryName(),
        )
        // A sandbox, an origin of its own; downloads, for its Download link (the file is sent as an attachment).
        val csp = "sandbox allow-scripts allow-downloads; ${GuitarPage.policy(at)}; ${App.FRAMES}"
        return Response(200, Body.Bytes(html.toByteArray(Charsets.UTF_8)),
                        mutableListOf("Content-Type" to MessagePage.HTML, "Content-Security-Policy" to csp))
    }

    /** guitar_routes.asset: `GET /assets/alphatab/<name>`, the bundle by the name the page loads it by. */
    fun asset(name: String): Response {
        val at = alphaTab() ?: throw Refused(404, "Not found", "This caracole serve has no alphaTab " +
                                                              "(CARACOLE_ALPHATAB_DIR isn't set).")
        if (name != at.name || at.body.isEmpty()) throw Refused(404, "Not found", "There's no such file of alphaTab's here.")
        return Response(200, Body.Bytes(at.body), mutableListOf(
            "Content-Type" to "text/javascript; charset=utf-8",
            "Access-Control-Allow-Origin" to "*",
            "Cross-Origin-Resource-Policy" to "cross-origin",
            "Cache-Control" to "public, max-age=$ONE_YEAR, immutable",
            "Content-Security-Policy" to "default-src 'none'; ${App.FRAMES}",
        ))
    }

    /** parse_qs(query, errors="strict", max_num_fields=4): each name's values, blank ones left out; [PyUrl.Invalid]
     * for more than four fields or a name or value that isn't UTF-8 once unquoted. */
    private fun fields(query: String): Map<String, List<String>> {
        val found = LinkedHashMap<String, MutableList<String>>()
        if (query.isEmpty()) return found
        if (MAX_FIELDS < 1 + query.count { it == '&' }) throw PyUrl.Invalid("Max number of fields exceeded")
        for (field in query.split('&')) {
            val at = field.indexOf('=')
            if (at < 0) continue
            val value = field.substring(at + 1)
            if (value.isEmpty()) continue
            val name = unquotePlus(field.substring(0, at))
            found.getOrPut(name) { ArrayList() }.add(unquotePlus(value))
        }
        return found
    }

    private fun unquotePlus(text: String): String = PyUrl.unquote(text.replace('+', ' '), strict = true)

    /** app.address: the request's path, unquoted (the router has read it already, and refused one it couldn't). */
    private fun address(request: Request): String = PyUrl.unquote(PyUrl.urlsplit(request.target).path, strict = true)

    /**
     * files.read_library_file's bytes: the parts of the `/`-separated [path] checked (no empty part, `.`, `..`, hidden
     * name or NUL, nothing under the phone's state), a kind of file the library serves ([FileTypes]), each folder on
     * the way opened as no link, the file a regular file and no link, at most [FileTypes.MAX_BYTES]; null otherwise.
     */
    private fun readLibraryFile(path: String): ByteArray? {
        val names = path.split('/')
        if (names.any { it.isEmpty() || it == "." || it == ".." || it.startsWith(".") || '\u0000' in it }) return null
        if (hidden(names)) return null
        if (PyText.lower(PyPath.suffix(names.last())) !in FileTypes.TYPES) return null
        return try {
            var at: Path = parts.store.libraryDir.toPath()
            if (!Files.isDirectory(at)) return null
            for (name in names.dropLast(1)) {
                at = at.resolve(name)
                val folder = Files.readAttributes(at, BasicFileAttributes::class.java, LinkOption.NOFOLLOW_LINKS)
                if (!folder.isDirectory || folder.isSymbolicLink) return null
            }
            val file = at.resolve(names.last())
            val info = Files.readAttributes(file, BasicFileAttributes::class.java, LinkOption.NOFOLLOW_LINKS)
            if (!info.isRegularFile || info.size() > FileTypes.MAX_BYTES) return null
            Files.newInputStream(file, LinkOption.NOFOLLOW_LINKS).use { it.readBytes() }
        } catch (e: IOException) {
            null
        } catch (e: InvalidPathException) {
            null
        }
    }

    /** files._is_hidden: whether [names] is a path in the phone's state folder, where that is inside the library. */
    private fun hidden(names: List<String>): Boolean = try {
        val root = parts.store.libraryDir.toPath().toAbsolutePath().normalize().let { real(it) }
        val state = real(parts.stateDir.toPath().toAbsolutePath().normalize())
        if (!state.startsWith(root)) false else {
            val inside = root.relativize(state).map { it.toString() }.filter { it.isNotEmpty() }
            names.take(inside.size) == inside
        }
    } catch (e: IOException) {
        false
    }

    private fun real(path: Path): Path = if (Files.exists(path)) path.toRealPath() else path

    /**
     * library_page.sheet_href made a library path (guitar_routes._viewer_path): the song's sheet viewer, the first of
     * its folder's sheets a line opens that is a viewer (sheet.html, else sheet.pdf, else sheet (auto).html, else
     * sheet (auto).pdf: only the two pages are viewers), else null.
     */
    private fun viewerOf(song: SongRow): String? {
        val (artist, title) = SafeName.songFolder(song.artist, song.title)
        val folder = File(File(parts.store.libraryDir, artist), title)
        val names = folder.listFiles()?.filter { it.isFile && !it.name.startsWith(".") }?.map { it.name }?.toSet()
            ?: return null
        val primary = SHEETS.firstOrNull { it in names } ?: return null
        return if (primary.endsWith(".html")) "$artist/$title/$primary" else null
    }

    companion object {
        const val ASSETS = AlphaTabBundle.ASSETS

        /** Characters: two names of 120 bytes and a file name, percent-encoded at worst. */
        const val MAX_PATH = 1200

        /** Bytes: a Guitar Pro file is tens of kilobytes; the page holds it in base64. */
        const val MAX_FILE = 8 * 1024 * 1024
        const val ONE_YEAR = 365 * 24 * 3600
        private const val MAX_FIELDS = 4

        /** library_page._primary's viewers and PDFs, in a line's order (_SHEET_PAGES'). */
        private val SHEETS = listOf("sheet.html", "sheet.pdf", "sheet (auto).html", "sheet (auto).pdf")

        private const val NOT_KEPT = "That isn't a Guitar Pro file caracole keeps in the library."
        private const val POWER_TAB = "alphaTab can't read Power Tab files, so this one is a download alone: " +
            "find it under its song's ⋯ in the library."
        private const val NO_ALPHATAB = "This caracole serve has no alphaTab (CARACOLE_ALPHATAB_DIR isn't set), " +
            "so it can't show Guitar Pro files in the browser: download the file from its song's ⋯ in the library instead."
        private const val NO_SUCH_SONG = "That song isn't in the library."
        private const val GONE = "That Guitar Pro file isn't in the library any more: the next caracole run fetches " +
            "it again, or files it from the inbox."
        private const val TOO_LARGE = "That Guitar Pro file is too large to show here: download it instead."

        private fun notKept() = Refused(404, "Not a Guitar Pro file", NOT_KEPT)

        /** The mirror the phone's library page reads (its cards' copy of the computer's pages), if any. */
        private fun mirrorOf(parts: PhoneParts): Mirror? = when (val cards = parts.cards) {
            is PhonePageData -> cards.mirror.mirror
            is MirrorPageData -> cards.mirror
            else -> null
        }

        /** Whether the phone shows Guitar Pro files on this page (library_page.WebControls.guitar, `alphatab.available`):
         * whether the APK holds alphaTab's bundle, which its build never leaves out. */
        fun available(): Boolean = AlphaTabBundle.installed() != null
    }
}
