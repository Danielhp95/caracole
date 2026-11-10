package io.github.danielhp95.caracole.server.http

import io.github.danielhp95.caracole.core.py.PyText
import io.github.danielhp95.caracole.core.web.Inline
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive

/** A text of caracole's runtime data, on the classpath as caracole/<area>/… (:core's resource root). */
internal fun caracoleResource(name: String): String {
    val stream = MessagePage::class.java.classLoader?.getResourceAsStream(name)
        ?: throw IllegalStateException("the resource $name is missing")
    return stream.use { it.readBytes().toString(Charsets.UTF_8) }
}

/** page_icon.py's marks, from caracole/page/icon.json: the tab's icon ([link]; [scratchLink], its colour for a
 * library with a badge), the browser's /favicon.ico ([svg]) and the bar's "¿" ([mark]). */
object PageIcon {
    private val icons: JsonObject by lazy { Json.parseToJsonElement(caracoleResource("caracole/page/icon.json")).jsonObject }

    val link: String get() = icons.getValue("link").jsonPrimitive.content
    val scratchLink: String get() = icons.getValue("scratch_link").jsonPrimitive.content
    val svg: String get() = icons.getValue("svg").jsonPrimitive.content
    val mark: String get() = icons.getValue("mark").jsonPrimitive.content
}

/**
 * pages.py's message page: an error said plainly, and the way back; its style and policy from
 * caracole/page/message.json (pages.PAGE_STYLE and PAGE_CSP). The page names the library the phone shows, with the
 * phone's badge ([PHONE_BADGE]), as caracole serve's pages name its; [link], a page to go to instead, before the way
 * back. Its data is `{"error": message}`, what a page's script reads in its place.
 */
object MessagePage {
    /** The badge every page the phone writes itself shows beside the library's name (ServerControls.badge's). */
    const val PHONE_BADGE = LibraryName.PHONE_BADGE
    const val HTML = "text/html; charset=utf-8"

    private val page: JsonObject by lazy { Json.parseToJsonElement(caracoleResource("caracole/page/message.json")).jsonObject }

    /** pages.PAGE_STYLE: base.css and picker.css, and the message pages' own. */
    val style: String get() = page.getValue("style").jsonPrimitive.content

    /** pages.PAGE_CSP: no script, the style by its hash, the icon inline. */
    val csp: String by lazy {
        page.getValue("csp").jsonPrimitive.content.also {
            check(Inline.sha256Source(style) in it) { "message.json's policy allows another style" }
        }
    }

    /**
     * The message page of [status]. A route answers one through App.message (or by throwing Refused), which names the
     * library as the App is configured to (AppConfig.libraryName, read for each page); [name]'s default, the phone's
     * badge with no library's name, is the plan's signature's (§5.2) and names no other library.
     */
    fun page(status: Int, title: String, message: String, link: Pair<String, String>? = null,
             name: LibraryName = LibraryName.phone(null)): Response {
        val back = "<a class=\"btn\" href=\"/\">Back to the book</a>"
        val links = if (link != null) {
            "<a class=\"btn\" href=\"${PyText.escape(link.first)}\">${PyText.escape(link.second)}</a> $back"
        } else {
            back
        }
        val html = page(title, "<p class=\"message\">${PyText.escape(message)}</p>\n<p>$links</p>", name)
        return Response(status, Body.Bytes(html.toByteArray()),
                        mutableListOf("Content-Type" to HTML, "Content-Security-Policy" to csp),
                        JsonObject(mapOf("error" to JsonPrimitive(message))))
    }

    /** A page of the phone's own in this frame, style and policy ([csp]: no script): [body] under the header (the page
     * of a song shared to the app, ShareRoutes'). */
    internal fun html(title: String, body: String, name: LibraryName): String = page(title, body, name)

    /** pages.page: the head, the header (top.py's) and [body]. */
    private fun page(title: String, body: String, name: LibraryName): String =
        "<!doctype html>\n<html lang=\"en\">\n<head>\n<meta charset=\"utf-8\">\n" +
            "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">\n" +
            "<meta name=\"color-scheme\" content=\"light dark\">\n<meta name=\"referrer\" content=\"same-origin\">\n" +
            "${name.icon()}<title>${PyText.escape(name.title(title))}</title>\n<style>$style</style>\n</head>\n<body>\n" +
            "<div class=\"page\">\n${top(title, name)}$body\n</div>\n</body>\n</html>\n"

    /** top.py's header: the "¿" and caracole's name, which lead home, the library's, and the page's title. */
    private fun top(title: String, name: LibraryName): String =
        "<header class=\"top\">\n" +
            "  <a class=\"app\" href=\"/\">${PageIcon.mark}<span class=\"word\">caracole</span></a>\n" +
            "  ${name.markup()}\n" +
            "  <span class=\"sep\" aria-hidden=\"true\">›</span>\n" +
            "  <h1>${PyText.escape(title)}</h1>\n" +
            "  <nav class=\"links\" aria-label=\"Pages\"><a class=\"navlink\" href=\"/\">Logbook</a></nav>\n</header>\n"
}
