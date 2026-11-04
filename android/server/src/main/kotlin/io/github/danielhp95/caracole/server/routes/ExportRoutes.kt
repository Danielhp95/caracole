package io.github.danielhp95.caracole.server.routes

import io.github.danielhp95.caracole.server.PhoneParts
import io.github.danielhp95.caracole.server.http.GetAnswer
import io.github.danielhp95.caracole.server.http.Route
import io.github.danielhp95.caracole.server.http.RouteModule

/**
 * Export PDF on the phone (web/export_routes.py; lane export-print): the version checked and named, `{name, label}`,
 * which the app prints (mirror.Route.Print), and with `mine=1` Make this my version queued. Neutral: refused as not
 * on the phone yet, as Stubs refused it.
 */
class ExportRoutes(val parts: PhoneParts) : RouteModule {
    override val routes: List<Route> = listOf(
        Route("GET", "/export.pdf", "Exporting a PDF: not on the phone yet", get = GetAnswer { notYet("Exporting a PDF") }),
    )
}
