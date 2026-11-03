package io.github.danielhp95.caracole.core.sync.internal.client

import io.github.danielhp95.caracole.core.json.Canonical
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import java.time.Instant
import java.time.LocalDate
import java.time.LocalDateTime
import java.time.OffsetDateTime
import java.time.ZoneOffset
import java.time.format.DateTimeFormatter
import java.time.format.DateTimeParseException
import java.time.temporal.ChronoUnit

/** stamps.py's times: stored as ISO 8601 UTC to the second ("2026-10-18T03:30:00Z"); one missing or unreadable is
 * older than any. */
internal object Stamps {
    private val FORMAT = DateTimeFormatter.ofPattern("yyyy-MM-dd'T'HH:mm:ss'Z'").withZone(ZoneOffset.UTC)

    /** stamps.stamp. */
    fun of(at: Instant): String = FORMAT.format(at.truncatedTo(ChronoUnit.SECONDS))

    /** stamps.parse: `datetime.fromisoformat`'s readings that matter here, a naive time in UTC; null when unreadable. */
    fun parse(text: String?): Instant? {
        if (text.isNullOrEmpty()) return null
        val iso = if (text.endsWith("Z") || text.endsWith("z")) text.dropLast(1) + "+00:00" else text
        return try {
            OffsetDateTime.parse(iso.replace(' ', 'T')).toInstant()
        } catch (e: DateTimeParseException) {
            try {
                LocalDateTime.parse(iso.replace(' ', 'T')).toInstant(ZoneOffset.UTC)
            } catch (e: DateTimeParseException) {
                try {
                    LocalDate.parse(iso).atStartOfDay().toInstant(ZoneOffset.UTC)
                } catch (e: DateTimeParseException) {
                    null
                }
            }
        }
    }

    /** Whether [stamp] is newer than [than]: never when it is unreadable, always when [than] is. */
    fun newer(stamp: String, than: String): Boolean {
        val a = parse(stamp) ?: return false
        val b = parse(than) ?: return true
        return a.isAfter(b)
    }

    /** kv's {site: stamp}, its odd entries left out; empty for none. */
    fun sites(value: JsonElement?): Map<String, String> =
        (value as? JsonObject)?.mapNotNull { (site, stamp) -> Documents.text(stamp)?.let { site to it } }?.toMap() ?: emptyMap()

    /** {site: stamp}, its keys in code-point order, as kv text. */
    fun json(sites: Map<String, String>): JsonObject =
        JsonObject(sites.toSortedMap(Canonical.KEY_ORDER).mapValues { JsonPrimitive(it.value) })
}
