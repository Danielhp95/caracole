package io.github.danielhp95.caracole.server.page

import io.github.danielhp95.caracole.server.http.Inline
import io.github.danielhp95.caracole.server.http.LibraryName
import io.github.danielhp95.caracole.server.http.MessagePage
import io.github.danielhp95.caracole.server.http.PageIcon
import io.github.danielhp95.caracole.server.http.PyText
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.longOrNull

/** library_page.WebControls on the phone: what its server adds to the page; its badge the one every page the phone
 * writes itself shows (MessagePage.PHONE_BADGE). */
data class ServerControls(
    val csrf: String, val busy: Set<Long> = emptySet(), val active: Int = 0, val held: Set<Long> = emptySet(),
    val removing: Set<Long> = emptySet(), val jobs: List<JsonObject> = emptyList(),
    val timers: Map<String, Int>? = null, val badge: String? = MessagePage.PHONE_BADGE, val sync: Boolean = false,
)

/**
 * The library page the phone serves: library_page.assemble_page's served branch, the templates of library_assets/
 * filled in, its one stylesheet and one script inlined ([LibraryAssets]), its data as its JSON block. A pure function
 * of its arguments and the assets, so the phone's page for some data is caracole serve's for the same data, byte for
 * byte (tests/conformance/vectors/web/library_page.json), less the Requests tab, which the phone has not until M4:
 * `__TABREQUESTS__` and `__REQUESTS__` are filled with nothing.
 *
 * Each blank is replaced in assemble_page's order, every occurrence, in the text the replacements before it made, so
 * that what Python's chain of `str.replace` makes this makes too.
 */
class LibraryPage(val assets: LibraryAssets) {
    /** The page's policy, its meta tag's: as caracole serve's page, which may ask its server how its requests go
     * (connect-src) and show a thumbnail it serves (img-src 'self'); forms post to the server alone. */
    val csp: String by lazy {
        "default-src 'none'; script-src ${assets.scriptHash}; style-src ${assets.styleHash}; img-src data: 'self'; " +
            "base-uri 'none'; form-action 'self'; connect-src 'self'"
    }

    /** The page for [data] (the page's data, which its script reads: [PageData]'s, with the server's part), served
     * with [controls], for the library [libraryName] (AppConfig's: "Phone"), named as every page the phone writes
     * names it (library_name.py's LibraryName, server.http's). */
    fun served(data: JsonObject, controls: ServerControls, libraryName: String): String {
        val shown = LibraryName(libraryName, controls.badge)
        val sync = controls.sync
        return assets.template("head.html").replace("__CSP__", csp).replace("__ICON__", shown.icon())
            .replace("__STYLE__", assets.styles).replace("__TITLE__", PyText.escape(shown.title())) +
            assets.template("body.html").replace("__MARK__", PageIcon.mark).replace("__LIBRARY__", shown.markup("p"))
                .replace("__TABSYNC__", if (sync) assets.template("sync-tab.html") else "").replace("__TABREQUESTS__", "")
                .replace("__SYNC__", if (sync) assets.template("sync-panel.html") else "").replace("__REQUESTS__", "")
                .replace("__REQUEST__", requestForm(controls)).replace("__REQUESTED__", assets.template("requested.html")) +
            Inline.jsonBlock("songs", data) +
            "<script>${assets.scripts}</script>\n</body>\n</html>\n"
    }

    /**
     * build_library_page's part of the served page: [data] with the server's own member (`server`, where caracole
     * serve puts it: before the songbooks), the form token, the songs a request waits or runs for, the requests, no
     * Guitar Pro page and no sheet from YouTube on the phone, and the tests' timers if any; and each song's
     * `fetchable`, false for a song a review must come first for ([ServerControls.held]) and for a card of a song the
     * phone hasn't got (a negative id, [MirrorPageData]).
     */
    fun withServer(data: JsonObject, controls: ServerControls): JsonObject {
        val server = JsonObject(buildMap {
            put("csrf", JsonPrimitive(controls.csrf))
            put("busy", JsonArray(controls.busy.sorted().map { JsonPrimitive(it) }))
            put("active", JsonPrimitive(controls.active))
            put("removing", JsonArray(controls.removing.sorted().map { JsonPrimitive(it) }))
            put("jobs", JsonArray(controls.jobs))
            put("guitar", JsonPrimitive(false))
            put("youtube", JsonObject(mapOf("ok" to JsonPrimitive(false), "why" to JsonPrimitive(YOUTUBE_PROBLEM),
                                            "off" to JsonPrimitive(true))))
            controls.timers?.let { timers -> put("timers", JsonObject(timers.mapValues { JsonPrimitive(it.value) })) }
        })
        val out = LinkedHashMap<String, JsonElement>()
        for ((name, value) in data) {
            if (name == "songbooks" && "server" !in data) out["server"] = server
            out[name] = when (name) {
                "server" -> server
                "songs" -> JsonArray((value as? JsonArray).orEmpty().map { song -> fetchable(song, controls) })
                else -> value
            }
        }
        out.putIfAbsent("server", server)
        return JsonObject(out)
    }

    private fun fetchable(song: JsonElement, controls: ServerControls): JsonElement {
        if (song !is JsonObject) return song
        val id = (song["id"] as? JsonPrimitive)?.longOrNull
        return JsonObject(LinkedHashMap(song).apply { put("fetchable", JsonPrimitive(id != null && id > 0 && id !in controls.held)) })
    }

    /** request.html, with the form's token, and no YouTube video field: the line that says why there is none. */
    private fun requestForm(controls: ServerControls): String =
        assets.template("request.html").replace("__CSRF__", PyText.escape(controls.csrf)).replace("__YOUTUBE__", "")
            .replace("__YOUTUBEHINT__", "<p class=\"hint\">No sheets from YouTube here: ${PyText.escape(YOUTUBE_PROBLEM)}.</p>")

    companion object {
        /** Why the phone makes no sheet from a YouTube video, as youtube_fetch.route_reason says why a caracole makes
         * none: the request form's line, and the server member's `youtube.why`. */
        const val YOUTUBE_PROBLEM = "YouTube isn't on the phone"
    }
}
