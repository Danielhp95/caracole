package io.github.danielhp95.caracole.core.testing

import io.github.danielhp95.caracole.core.http.HttpAnswer
import io.github.danielhp95.caracole.core.http.HttpRequest
import io.github.danielhp95.caracole.core.http.Transport

/**
 * A site that answers what a test gave it: [answers] by "METHOD URL" (the full URL as httpx renders it), every request
 * recorded in [requests] in order, and one it wasn't given an AssertionError, so a test never sends anything else.
 */
class FakeTransport(private val answers: Map<String, HttpAnswer>) : Transport {
    private val sent = ArrayList<HttpRequest>()

    /** Every request sent, oldest first. */
    val requests: List<HttpRequest> get() = synchronized(sent) { sent.toList() }

    /** Each request as "METHOD URL". */
    val said: List<String> get() = requests.map { "${it.method} ${it.url}" }

    override fun send(request: HttpRequest): HttpAnswer {
        synchronized(sent) { sent.add(request) }
        return answers["${request.method} ${request.url}"]
            ?: throw AssertionError("the fake site has no answer for ${request.method} ${request.url}")
    }

    companion object {
        /** An answer of [status] with [body] as UTF-8 and [headers]. */
        fun answer(status: Int, body: String = "", headers: List<Pair<String, String>> = emptyList()): HttpAnswer =
            HttpAnswer(status, headers, body.toByteArray(Charsets.UTF_8))
    }
}

/** A transport that sends nothing: every request a [io.github.danielhp95.caracole.core.http.TransportError]
 * ("refused"), the one every `Phone` a test builds is given unless it means to reach a fake site. */
object RefusingTransport : Transport {
    override fun send(request: HttpRequest): HttpAnswer =
        throw io.github.danielhp95.caracole.core.http.TransportError("refused", "no site from a test: ${request.url}")
}
