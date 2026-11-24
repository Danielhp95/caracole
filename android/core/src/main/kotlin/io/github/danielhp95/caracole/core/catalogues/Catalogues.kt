package io.github.danielhp95.caracole.core.catalogues

import java.time.Instant
import java.time.ZoneId
import java.time.temporal.ChronoUnit

/**
 * The site catalogues: every site's index, which the laptop publishes each week as a gzip of an index export in the
 * GitHub release [TAG] of [REPO] (`caracole index publish`, nix/publish-indexes.sh), read by a phone with no computer
 * (plan_host_index.md). This package is the one place on the phone that knows GitHub: [Names] reads a file's name,
 * [CatalogueSource] lists the release (GitHub's API, the owner's choice S1), [choose] picks this app's schema's newest
 * file and [download] streams, unpacks and checks it. The job that merges it is the server's.
 */
object Catalogues {
    const val REPO = "Danielhp95/caracole"
    const val TAG = "indexes"

    /** A file unpacks to at most this many times its `.gz` size; past it, it is no export. */
    const val CAP_FACTOR = 20

    /** The room a download needs, as times its `.gz` size: the unpacked file and the merge's (the spec's estimate,
     * not measured yet: plan's Task 0). */
    const val ROOM_FACTOR = 23

    /** kv: the name of the file last imported. */
    const val IMPORTED = "catalogues:imported"

    /** kv: when GitHub said to ask again (its `x-ratelimit-reset`), so the app doesn't ask before. */
    const val NOT_BEFORE = "catalogues:not-before"

    /** The hosts a download from GitHub's API may be redirected to (an asset's bytes). */
    val API_REDIRECTS: Set<String> = setOf("release-assets.githubusercontent.com")
}

/** Why the catalogues can't be listed or downloaded, in words the app says as they are. */
open class CatalogueError(message: String, cause: Throwable? = null) : Exception(message, cause)

/** The release has no files yet (it answers 404, or its manifest does). */
class NoRelease : CatalogueError("No catalogues are published yet.")

/**
 * GitHub has answered this network's share of requests for the hour (a 403 or 429 with `x-ratelimit-remaining: 0`):
 * [until] is its `x-ratelimit-reset`, said as the minute on the phone's clock ([zone]) at or after it.
 */
class Limited(val until: Instant, zone: ZoneId = ZoneId.systemDefault()) :
    CatalogueError("Try again after ${clock(until, zone)} — GitHub has answered this network's share of requests for the hour.")

/** [at] as "14:05" in [zone], a time within a minute said as the minute after it. */
private fun clock(at: Instant, zone: ZoneId): String {
    val whole = at.truncatedTo(ChronoUnit.MINUTES)
    val local = (if (whole == at) whole else whole.plus(1, ChronoUnit.MINUTES)).atZone(zone)
    return two(local.hour) + ":" + two(local.minute)
}

/** [n], 0 to 99, in two ASCII digits (never a locale's). */
internal fun two(n: Int): String = (if (n < 10) "0" else "") + n.toString()
