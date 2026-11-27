package io.github.danielhp95.caracole.core.youtube

import io.github.danielhp95.caracole.core.db.Database
import io.github.danielhp95.caracole.core.py.PyRe
import io.github.danielhp95.caracole.core.py.PyRegex
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.boolean
import kotlinx.serialization.json.double
import kotlinx.serialization.json.int
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive

/**
 * youtube.py's rules for the phone, as tests/test_conformance_youtube.py wrote them: data/caracole/youtube/youtube.json.
 * No flag, pattern, prefix or word of yt-dlp's is typed in this package (NoLiteralsTest): each is read here.
 *
 * - [argv]: phone_argv, a run's arguments from its kind's template ([templates]), each element filled in one pass
 *   ([fillOnce]: the text before its placeholder, the value, the text after it; a value is never read again), after
 *   the refusals phone_argv makes ([Refused]): a value of `refuse.no_nul` that holds a NUL, an empty search, a
 *   download into an empty folder, a video's or a download's target that isn't exactly [watchUrl] of an id
 *   [videoId] matches whole, a kind there is no template of, and a folder given to any kind but the one whose
 *   template takes it.
 * - [searchTarget] and [watchUrl]: `ytsearch{n}:` and the watch address, filled the same way.
 * - [pattern]: a pattern of `patterns` (or of `choose`), compiled once by PyRegex, `(?i)` where it says ignorecase.
 */
class YouTubeData private constructor(val json: JsonObject) {
    /** A run phone_argv makes none of: its words are never the values (the proxy's holds the gate's secret). */
    class Refused(message: String) : IllegalArgumentException(message)

    /** The placeholders by name, in the data's order: `target`, `cache_dir`, `qjs`, `proxy`, `into`. */
    val placeholders: Map<String, String> =
        json.getValue("placeholders").jsonObject.mapValues { it.value.jsonPrimitive.content }

    /** Each kind's template (`phone_argv`): search, video, download. */
    val templates: Map<String, List<String>> = json.getValue("phone_argv").jsonObject.mapValues { (_, v) ->
        v.jsonArray.map { it.jsonPrimitive.content }
    }

    private val targets = json.getValue("targets").jsonObject
    private val refuse = json.getValue("refuse").jsonObject
    private val noNul: List<String> = refuse.getValue("no_nul").jsonArray.map { it.jsonPrimitive.content }
    private val nul: String = refuse.getValue("nul").jsonPrimitive.content

    /** youtube_urls' VIDEO_ID, matched whole (`video_id_matched`). */
    val videoId: Regex = compiled(targets.getValue("video_id").jsonObject)

    val searchResults: Int = json.getValue("search_results").jsonPrimitive.int

    init {
        check(targets.getValue("video_id_matched").jsonPrimitive.content == "whole") { "video_id is matched whole" }
        check(SEARCH in templates) { "youtube.json has no $SEARCH template" }
        check(refuse.getValue("empty_search").jsonPrimitive.boolean && refuse.getValue("empty_into").jsonPrimitive.boolean)
        for ((what, template) in templates) for (arg in template) {
            val marks = placeholders.values.sumOf { mark -> arg.windowed(mark.length).count { it == mark } }
            check(marks <= 1) { "youtube.json's $what template has an element of $marks placeholders" }
        }
    }

    private val compiledPatterns = HashMap<String, Regex>()

    /** A pattern of the data's `patterns` member (blocked, unavailable, status, outdated, pass_over, degraded, network). */
    fun pattern(name: String): Regex = synchronized(compiledPatterns) {
        compiledPatterns.getOrPut(name) { compiled(json.getValue("patterns").jsonObject.getValue(name).jsonObject) }
    }

    /** The `classify` member. */
    val classify: JsonObject get() = json.getValue("classify").jsonObject

    /** The `gate` member: the phone's gate's hosts and its refusal's words (youtube.py's PHONE_GATE). */
    val gate: JsonObject get() = json.getValue("gate").jsonObject

    /** The `runner` member: YtDlp's words and its cache folder. */
    val runner: JsonObject get() = json.getValue("runner").jsonObject

    /** A text of [within]. */
    fun text(name: String, within: JsonObject): String = within.getValue(name).jsonPrimitive.content

    /** A list of texts of [within]. */
    fun texts(name: String, within: JsonObject): List<String> = within.getValue(name).jsonArray.map { it.jsonPrimitive.content }

    /** The `choose` member. */
    val choose: JsonObject get() = json.getValue("choose").jsonObject

    /** A number of the data's top level (`search_timeout`…), or of [within]. */
    fun number(name: String, within: JsonObject = json): Double = within.getValue(name).jsonPrimitive.double

    /** A search's target: `search_prefix` with [n] its results, then [query] as it is. */
    fun searchTarget(query: String, n: Int = searchResults): String =
        fillOnce(targets.getValue("search_prefix").jsonPrimitive.content, "{n}", n.toString()) + query

    /** A video's plain address (youtube_urls.watch_url). */
    fun watchUrl(id: String): String = fillOnce(targets.getValue("watch_url").jsonPrimitive.content, "{id}", id)

    /**
     * phone_argv(what, target, cache_dir=, qjs=, proxy=, into=): its kind's template filled, or [Refused] where
     * phone_argv raises its ValueError. [into] is a download's folder alone, its trailing `/` taken off.
     */
    fun argv(what: String, target: String, cacheDir: String, qjs: String, proxy: String, into: String? = null): List<String> {
        val given = mapOf("target" to target, "cache_dir" to cacheDir, "qjs" to qjs, "proxy" to proxy, "into" to into)
        check(given.keys == placeholders.keys) { "youtube.json's placeholders aren't phone_argv's values" }
        for (name in noNul) if (given.getValue(name)?.contains(nul) == true) throw Refused("$name holds a NUL")
        val template = templates[what] ?: throw Refused("no template of a run of kind $what")
        val takesInto = template.any { placeholders.getValue(INTO) in it }
        if (what == SEARCH && target.isEmpty()) throw Refused("an empty search")
        if (takesInto && into != null && into.trimEnd('/').isEmpty()) throw Refused("an empty folder to download into")
        if (what != SEARCH && !isWatchUrl(target)) throw Refused("not a YouTube video's address")
        if (takesInto != (into != null)) throw Refused("a download, and it alone, is given the folder its audio goes into")
        return template.map { arg -> fill(arg, given) }
    }

    /** Whether [target] is exactly [watchUrl] of an id [videoId] matches whole. */
    fun isWatchUrl(target: String): Boolean {
        val prefix = watchUrl("")
        if (!target.startsWith(prefix)) return false
        val id = target.substring(prefix.length)
        return PyRe.fullmatch(videoId, id) != null && target == watchUrl(id)
    }

    /** One element of a template, `fill`'s rule: the first placeholder it holds, in the data's order, filled once. */
    private fun fill(arg: String, given: Map<String, String?>): String {
        for ((name, mark) in placeholders) {
            if (mark !in arg) continue
            val value = given.getValue(name) ?: throw Refused("no $name given")
            return fillOnce(arg, mark, if (name == INTO) value.trimEnd('/') else value)
        }
        return arg
    }

    companion object {
        private const val SEARCH = "search"
        private const val INTO = "into"

        private val DATA: YouTubeData by lazy {
            YouTubeData(Json.parseToJsonElement(Database.resource("caracole/youtube/youtube.json")).jsonObject)
        }

        fun read(): YouTubeData = DATA

        /** A YouTubeData of [json] in place of the corpus's: a test's, to show a data mistake fails at once. */
        internal fun of(json: JsonObject): YouTubeData = YouTubeData(json)

        /** A `{"pattern", "ignorecase"}` of the data, as PyRegex reads Python's pattern. */
        fun compiled(p: JsonObject): Regex {
            val pattern = p.getValue("pattern").jsonPrimitive.content
            return PyRegex.compile(if (p.getValue("ignorecase").jsonPrimitive.boolean) "(?i)$pattern" else pattern)
        }

        /** [template] with its first [mark] replaced by [value], in one pass: before + value + after. */
        fun fillOnce(template: String, mark: String, value: String): String {
            val at = template.indexOf(mark)
            if (at < 0) return template
            return template.substring(0, at) + value + template.substring(at + mark.length)
        }

        /** [template] with each `{name}` of [values] filled where it stands, left to right, a value never read again. */
        fun fillAll(template: String, values: Map<String, String>): String {
            val out = StringBuilder()
            var i = 0
            outer@ while (i < template.length) {
                for ((name, value) in values) {
                    val mark = "{$name}"
                    if (template.startsWith(mark, i)) {
                        out.append(value)
                        i += mark.length
                        continue@outer
                    }
                }
                out.append(template[i])
                i++
            }
            return out.toString()
        }
    }
}
