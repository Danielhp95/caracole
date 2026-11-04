package io.github.danielhp95.caracole

import android.app.Activity
import android.webkit.WebView

/**
 * The viewer's Export PDF on the phone (lane export-print): the server asked in-process for the version's name
 * (`GET /export.pdf`, `{name, label}`), then Android's print framework prints the visible viewer
 * (`PrintManager.print(name, web.createPrintDocumentAdapter(name), A4)`, on the UI thread): a printer, or Save as
 * PDF; nothing is kept in the library. MainActivity routes mirror.Route.Print here, a navigation or a download.
 *
 * Until its lane lands it prints nothing, and says so as the server's stub did.
 */
object Printer {
    fun print(activity: Activity, web: WebView, url: String) {
        Handoff.toast(activity, activity.getString(R.string.print_not_built))
    }
}
