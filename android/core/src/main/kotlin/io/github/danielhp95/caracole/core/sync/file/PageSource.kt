package io.github.danielhp95.caracole.core.sync.file

import kotlinx.serialization.json.JsonObject
import java.io.InputStream

/**
 * The pages an export holds with the library (peer_file.Pages): the `GET /api/offline` manifest of the pages caracole
 * made of [units] (the units the file holds, by id, with their digests), each entry's `unit` and `digest` the unit it
 * is a page of as it was made, and a page's bytes by its SHA-256. The export keeps each page of a unit it holds at
 * that digest, and the start page, each read once and checked. null where there are none: the phone builds no page
 * of its own yet, so its export holds none until a PageSource is wired (the sync redesign's Task 33).
 */
interface PageSource {
    /** The manifest (`{"format": 1, "start", "files": [{path, url, size, sha256, type, headers, unit?, digest?}]}`),
     * or null for none. */
    fun manifest(units: Map<String, String>): JsonObject?

    /** A page's bytes, by its SHA-256; null when it can't be read. */
    fun open(sha256: String): InputStream?
}
