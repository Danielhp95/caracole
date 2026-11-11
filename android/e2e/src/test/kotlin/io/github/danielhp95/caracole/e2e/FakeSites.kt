package io.github.danielhp95.caracole.e2e

import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import java.net.HttpURLConnection
import java.net.Proxy
import java.net.URI
import java.net.URL

/**
 * The fake sites server's own routes (tests/helpers/fake_sites.py), at [base]: what it was sent ([log], each request
 * `{n, url, provider, status, known, closed, user_agent}` in order). Asked straight, through no proxy, so that
 * [Requests], which counts the phone's requests, never counts these.
 */
class FakeSites(val base: String) {
    /** Where the phone's requests to a site go: the server's host and port, as [Requests.hosts] names one. */
    val hostPort: String = URI(base).let { "${it.host.lowercase()}:${it.port}" }

    /** The requests the server was sent after its [since]-th, in order. */
    fun log(since: Int = 0): List<JsonObject> {
        val connection = URL("${base.trimEnd('/')}/log?since=$since").openConnection(Proxy.NO_PROXY) as HttpURLConnection
        try {
            connection.connectTimeout = 30_000
            connection.readTimeout = 30_000
            if (connection.responseCode != 200) throw AssertionError("the fake sites' /log: HTTP ${connection.responseCode}")
            val text = connection.inputStream.use { it.readBytes().toString(Charsets.UTF_8) }
            return Json.parseToJsonElement(text).jsonObject["requests"]!!.jsonArray.map { it.jsonObject }
        } finally {
            connection.disconnect()
        }
    }

    /** How many requests the server was sent so far. */
    fun count(): Int = log().lastOrNull()?.let { it["n"]!!.jsonPrimitive.content.toInt() } ?: 0

    companion object {
        /** How many of [requests] went to each provider. */
        fun byProvider(requests: List<JsonObject>): Map<String, Int> =
            requests.groupingBy { it.text("provider") }.eachCount().toSortedMap()
    }
}
