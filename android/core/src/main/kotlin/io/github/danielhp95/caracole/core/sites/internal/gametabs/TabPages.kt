package io.github.danielhp95.caracole.core.sites.internal.gametabs

import io.github.danielhp95.caracole.core.html.Html
import io.github.danielhp95.caracole.core.html.HtmlDoc
import io.github.danielhp95.caracole.core.html.HtmlNode
import io.github.danielhp95.caracole.core.http.GameTabsParseError
import io.github.danielhp95.caracole.core.json.PyJson
import io.github.danielhp95.caracole.core.py.Py
import io.github.danielhp95.caracole.core.py.PyRegex
import io.github.danielhp95.caracole.core.py.PyText
import io.github.danielhp95.caracole.core.py.PyUnicode
import io.github.danielhp95.caracole.core.sites.GameTab
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonObject
import java.math.BigInteger

/** What gametabs.py's two readers share: a node's text, a JSON list's names, a comma's list. */
internal object PageText {
    /** gametabs.TAB_HREF: a tab page's address, its path the group. */
    val TAB_HREF: Regex by lazy {
        PyRegex.compile("""https://(?:www\.)?gametabs\.net/(tabs/[a-z0-9_-]{1,200}/[a-z0-9_-]{1,200})/?""")
    }

    /** `_text`: the node's text, its whitespace made single spaces; "" for none. */
    fun text(node: HtmlNode?): String = if (node == null) "" else Values.collapse(node.text(deep = true))

    /** `_names`: the `name` of each of a JSON list's objects, its whitespace collapsed, those of none left out. */
    fun names(items: JsonElement?): List<String> {
        if (items !is JsonArray) return emptyList()
        return items.mapNotNull { i -> (i as? JsonObject)?.let { Values.collapsed(it["name"]) }?.ifEmpty { null } }
    }

    /** `_split`: a text's comma-separated parts, each's whitespace collapsed, the empty ones left out. */
    fun split(text: String): List<String> = text.split(",").map { Values.collapse(it) }.filter { it.isNotEmpty() }

    /** `json.loads(text or "")`, null where it raises ValueError or RecursionError. */
    fun loads(text: String?): JsonElement? = try {
        PyJson.loads(text ?: "")
    } catch (e: IllegalArgumentException) {  // PyJson.DecodeError and PyJson.RecursionError
        null
    }

    /** An attribute's value, "" for one written with none (selectolax's None) or not there. */
    fun attr(node: HtmlNode, name: String): String = node.attributes[name] ?: ""
}

/** gametabs.parse_tab_page, its helpers' names kept. */
internal object TabPages {
    fun parse(html: ByteArray, url: String?): GameTab = read(Html.parse(html), url)

    private fun read(tree: HtmlDoc, url: String?): GameTab {
        val pre = tree.cssFirst("pre#tab-text-view-text")
        val body = pre?.text(deep = true)
        if (body == null || Py.strip(body).isEmpty()) {
            throw GameTabsParseError("no tab (pre#tab-text-view-text) on the page", url = url)
        }
        val wrapper = tree.cssFirst("#tab-page-wrapper")
        val data = dataTab(wrapper)
        val game = data["game"] as? JsonObject ?: JsonObject(emptyMap())
        val work = wrapper?.cssFirst("[itemprop=\"recordingOf\"]")
        val album = wrapper?.cssFirst("[itemprop=\"inAlbum\"]")
        val details = details(tree)
        val title = Values.collapsed(data["name"]).ifEmpty { meta(work, "name") }
            .ifEmpty { PageText.text(tree.cssFirst("h1#tab-page-tab-name")) }
        val gameName = Values.collapsed(game["name"]).ifEmpty { meta(album, "name") }
        if (title.isEmpty() || gameName.isEmpty()) throw GameTabsParseError("no title or game on the page", url = url)
        val link = album?.cssFirst("link[itemprop=\"url\"]")
        val path = url?.let { PageText.TAB_HREF.matchEntire(it) }?.groupValues?.get(1) ?: ""
        var gameSlug = Values.strOr(game["slug"])
        if (gameSlug.isEmpty() && link != null) gameSlug = PageText.attr(link, "href").trimEnd('/').substringAfterLast('/')
        if (gameSlug.isEmpty() && path.isNotEmpty()) gameSlug = path.split("/")[1]
        val composers = PageText.names(data["composers"]).ifEmpty {
            work?.css("[itemprop=\"composer\"]").orEmpty().map { meta(it, "name") }.filter { it.isNotEmpty() }
        }
        val user = data["user"] as? JsonObject ?: JsonObject(emptyMap())
        val views = Values.number(data["views"])
        val ratings = Values.number(data["num_ratings_fun"])
        val created = data["created_at"]
        return GameTab(
            tabId = Values.int(data["id"]),
            title = title, game = gameName, gameSlug = gameSlug,
            slug = Values.strOr(data["slug"]).ifEmpty { path.substringAfterLast('/') },
            body = PyText.strip(body, "\n") + "\n",
            composers = composers,
            instruments = PageText.names(data["instruments"]).ifEmpty { PageText.split(details["instrument"] ?: "") },
            styles = PageText.names(data["styles"]).ifEmpty { PageText.split(details["style"] ?: "") },
            tuning = details["tuning"]?.ifEmpty { null },
            tabber = Values.collapsed(user["display_username"]).ifEmpty { null },
            views = if (views != null && views >= 0) Values.truncated(views) else BigInteger.ZERO,
            rating = Values.number(data["average_fun_rating"]),
            ratings = if (ratings != null && ratings >= 0) Values.truncated(ratings) else BigInteger.ZERO,
            created = Values.text(created),
        )
    }

    /** `_data_tab`: the page's `data-tab` JSON object, or {}. */
    private fun dataTab(wrapper: HtmlNode?): JsonObject {
        val text = wrapper?.attributes?.get("data-tab")
        return PageText.loads(text) as? JsonObject ?: JsonObject(emptyMap())
    }

    /** `_meta`: the content of the node's first `<meta itemprop=…>`, its whitespace collapsed; "" for none. */
    private fun meta(node: HtmlNode?, prop: String): String {
        val found = node?.cssFirst("meta[itemprop=\"$prop\"]") ?: return ""
        return Values.collapse(PageText.attr(found, "content"))
    }

    /** `_details`: the heading's details, "Tuning: EADGBE", by their label (stripped, lowercased), the last of a label
     * written twice. */
    private fun details(tree: HtmlDoc): Map<String, String> {
        val found = LinkedHashMap<String, String>()
        for (p in tree.css(".tab-page-grid-details p")) {
            val text = PageText.text(p)
            val at = text.indexOf(':')
            if (at < 0) continue
            found[PyUnicode.lower(Py.strip(text.substring(0, at)))] = Py.strip(text.substring(at + 1))
        }
        return found
    }
}
