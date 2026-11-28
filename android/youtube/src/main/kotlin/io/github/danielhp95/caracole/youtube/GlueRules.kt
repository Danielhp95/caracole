package io.github.danielhp95.caracole.youtube

import io.github.danielhp95.caracole.core.youtube.HostGate
import io.github.danielhp95.caracole.core.youtube.YouTubeData
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.jsonObject

/**
 * What the glue's `refusal` judges an argv by, as one JSON text, each part from its one source: the phone's argv
 * templates, their placeholders and the targets' rules (youtube.json's `phone_argv`, `placeholders`, `targets` and
 * `runner.cache_folder`, and `search_counts`, the counts the phone's searches ask for, a sheet's `search_results` and a suggestion's
 * `search.results`, through [YouTubeData]), the gate's
 * `--proxy` shape and the loopback hosts ([HostGate]'s constants), and what only this process knows: the [mode]
 * (LOOPBACK or NETWORK, the main process's, as the request said it), the app's [qjs], and this run's own two folders
 * ([folders], as the client named them and [YtDlpService] checked them: in the app's storage, no link), the only
 * ones its argv may name; and [verbose], the bench's leave for yt-dlp's `-v` under NETWORK too (its request's
 * `verbose`: the bench measures by `-v`'s lines, and the client redacts the gate's secret its proxy map prints).
 */
object GlueRules {
    /** The two modes a request names, [HostGate.Mode]'s, by name. */
    val MODES: Set<String> = HostGate.Mode.entries.map { it.name }.toSet()

    fun of(mode: HostGate.Mode, qjs: String, folders: RunFolders, verbose: Boolean = false): String {
        val data = YouTubeData.read()
        val runner = data.json.getValue("runner").jsonObject
        return JsonObject(mapOf(
            "mode" to JsonPrimitive(mode.name),
            "templates" to data.json.getValue("phone_argv"),
            "placeholders" to data.json.getValue("placeholders"),
            "targets" to data.json.getValue("targets"),
            "cache_folder" to runner.getValue("cache_folder"),
            "proxy_pattern" to JsonPrimitive(HostGate.PROXY_PATTERN),
            "loopback_hosts" to JsonArray(HostGate.LOOPBACK_NAMES.map { JsonPrimitive(it) }),
            "qjs" to JsonPrimitive(qjs),
            "search_counts" to JsonArray(data.searchCounts.map { JsonPrimitive(it) }),
            "cache_dir" to JsonPrimitive(folders.cache?.path),
            "into" to JsonPrimitive(folders.into?.path),
            "verbose" to JsonPrimitive(verbose),
        )).toString()
    }
}

/** A run's own two folders, which its argv's `--cache-dir` and `-o` must be exactly: [cache] (its basename youtube.json's
 * `runner.cache_folder`) and a download's [into]; none for a run that names neither (`--version`). */
data class RunFolders(val cache: java.io.File? = null, val into: java.io.File? = null)
