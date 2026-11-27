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
 * `runner.cache_folder`, through [YouTubeData]), the gate's `--proxy` shape and the loopback hosts ([HostGate]'s
 * constants), and what only this process knows: the [mode] (LOOPBACK or NETWORK, the main process's, as the request
 * said it), the app's [qjs] and the folders a run may write in ([roots], canonical).
 */
object GlueRules {
    /** The two modes a request names, [HostGate.Mode]'s, by name. */
    val MODES: Set<String> = HostGate.Mode.entries.map { it.name }.toSet()

    fun of(mode: HostGate.Mode, qjs: String, roots: List<String>): String {
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
            "roots" to JsonArray(roots.map { JsonPrimitive(it) }),
        )).toString()
    }
}
