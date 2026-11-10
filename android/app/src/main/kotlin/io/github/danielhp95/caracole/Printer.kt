package io.github.danielhp95.caracole

import android.app.Activity
import android.print.PrintAttributes
import android.print.PrintJob
import android.print.PrintManager
import android.webkit.WebView
import io.github.danielhp95.caracole.server.http.Body
import io.github.danielhp95.caracole.server.http.Request
import io.github.danielhp95.caracole.server.http.Response
import io.github.danielhp95.caracole.server.http.Security
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.contentOrNull
import java.net.URI

/**
 * The viewer's Export PDF on the phone, which MainActivity routes here (mirror.Route.Print, a navigation or a
 * download alike): the phone's server asked in this process for the version's name (`GET /export.pdf?…`, [ask], as
 * [LocalFiles] asks for a file, with the launch's cookie), which also queues Make this my version where the link says
 * `mine=1`; then Android's print framework prints the viewer shown, on the UI thread (`PrintManager.print(name,
 * web.createPrintDocumentAdapter(name), A4)`): a printer, or Save as PDF, the file named as caracole serve names its
 * download ("Soda Stereo - De Música Ligera (A Major, capo 0).pdf"). Nothing is kept in the library. The server's
 * refusal (a sheet the library hasn't, the auto sheet kept beside a human one, a full queue) is said in its words.
 */
object Printer {
    /** What the phone's server answered for the version a link names. */
    sealed interface Named {
        /** The version's file [name] (its download name) and its [label] ("A Major, capo 0"). */
        data class Version(val name: String, val label: String) : Named

        /** No version: the answer's [status], and the server's words for it when it gave some. */
        data class Refused(val status: Int, val message: String?) : Named
    }

    /** The attributes the print dialog starts with: an A4 page, the rest the printer's (or Save as PDF's). */
    val A4: PrintAttributes get() = PrintAttributes.Builder().setMediaSize(PrintAttributes.MediaSize.ISO_A4).build()

    /**
     * Prints the viewer [web] shows, its version named by the server for [url] (the viewer's `/export.pdf?…` link at
     * the phone's origin): asked off the UI thread, printed on it. [printed] gets the print job, or null when there
     * was none (the server refused, or the screen went meanwhile).
     */
    fun print(activity: Activity, web: WebView, url: String, printed: (PrintJob?) -> Unit = {}) {
        Caracole.background.launch {
            val named: Named? = try {
                withContext(Dispatchers.IO) {
                    val phone = Caracole.started() ?: Caracole.phone(activity)
                    ask(phone.app::handle, URI(phone.server.origin), Caracole.secret, url)
                }
            } catch (e: CancellationException) {
                throw e
            } catch (e: Exception) {
                withContext(Dispatchers.Main) {
                    Handoff.toast(activity, activity.getString(R.string.print_failed, e.message ?: e.javaClass.simpleName))
                }
                null
            }
            withContext(Dispatchers.Main) {
                printed(when (named) {
                    null -> null
                    is Named.Refused -> {
                        Handoff.toast(activity, named.message ?: activity.getString(R.string.print_refused, named.status))
                        null
                    }
                    is Named.Version -> if (activity.isFinishing || activity.isDestroyed) null else {
                        val manager = activity.getSystemService(PrintManager::class.java)
                        manager.print(named.name, web.createPrintDocumentAdapter(named.name), A4)
                    }
                })
            }
        }
    }

    /**
     * What the phone's server ([handle], at [origin]) names the version [url] holds: `GET` of its path and query, as
     * the WebView would ask it (the launch's cookie [secret], the server's host, from its own page), JSON back.
     */
    fun ask(handle: (Request) -> Response, origin: URI, secret: String, url: String): Named {
        val response = handle(Request("GET", target(url), mapOf(
            "host" to origin.rawAuthority,
            "cookie" to "${Security.SECRET_COOKIE}=$secret",
            "sec-fetch-site" to "same-origin",
            "accept" to "application/json",
        ), ByteArray(0)))
        val data = json(response)
        val name = (data?.get("name") as? JsonPrimitive)?.contentOrNull
        val label = (data?.get("label") as? JsonPrimitive)?.contentOrNull
        if (response.status == 200 && name != null && label != null) return Named.Version(name, label)
        return Named.Refused(response.status, (data?.get("error") as? JsonPrimitive)?.contentOrNull)
    }

    /** [url]'s path and query on its server ("/export.pdf?sheet=…"), its fragment left out. */
    fun target(url: String): String {
        val authority = url.indexOf("//").let { if (it < 0) -1 else url.indexOf('/', it + 2) }
        val path = if (authority < 0) "/" else url.substring(authority)
        return path.substringBefore('#')
    }

    private fun json(response: Response): JsonObject? {
        response.data?.let { return it }
        val bytes = (response.body as? Body.Bytes)?.bytes ?: return null
        return try {
            Json.parseToJsonElement(bytes.toString(Charsets.UTF_8)) as? JsonObject
        } catch (e: IllegalArgumentException) {
            null
        }
    }
}
