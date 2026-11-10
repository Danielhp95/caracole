package io.github.danielhp95.caracole.server.routes.share

import io.github.danielhp95.caracole.core.share.ShareAsk
import io.github.danielhp95.caracole.core.share.ShareLinks
import io.github.danielhp95.caracole.server.PhoneParts
import io.github.danielhp95.caracole.server.routes.ShareRoutes
import java.time.temporal.ChronoUnit

/**
 * The share page's reader of a link's service (ShareRoutes' [ShareRoutes.LinkReader]), the owner's choice of
 * 2026-11-10: a service turned off says so and asks nothing; the cache's answer, read with no request and no write;
 * else the service asked once ([ShareAsk.ask]) inside one write, as a lookup's runner asks a site (GetRunner: the
 * writes' one writer at a time, so a share that comes while a job writes waits for it), at the settings now, through
 * the phone's clients (its transport, its pace, caracole's user agent) and its alerts.
 */
internal class ShareReader(private val parts: PhoneParts) : ShareRoutes.LinkReader {
    override fun read(linked: ShareLinks.Linked): ShareLinks.Read {
        val cfg = parts.config()
        ShareAsk.off(linked, cfg)?.let { return it }
        val clients = parts.clients()
        ShareAsk.cached(linked, clients.cacheDir)?.let { return it }
        val now = parts.pacing.clock().truncatedTo(ChronoUnit.SECONDS)
        return parts.database.writeBlocking { db -> ShareAsk.ask(db, linked, clients, parts.alerts, cfg, now) }
    }
}
