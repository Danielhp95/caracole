package io.github.danielhp95.caracole.server.jobs

import io.github.danielhp95.caracole.core.testing.Corpus
import io.github.danielhp95.caracole.core.testing.Misses
import io.github.danielhp95.caracole.server.testing.replays.RequestsReplay
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import org.junit.Test
import java.time.Instant
import java.time.ZoneId
import kotlin.test.assertEquals
import kotlin.test.assertTrue

/** The Requests tab's feed is feed.py's, byte for byte (vectors/web/requests.jsonl, RequestsReplay), its times named
 * as Python's `%Z` names them. */
class FeedTest {
    private val names = ZoneNames.load()

    @Test
    fun `every record of requests jsonl is answered as caracole serve answered it`() {
        val misses = Misses(RequestsReplay.VECTOR)
        RequestsReplay.replay(misses)
        misses.assertNone()
        val fns = Corpus.records(RequestsReplay.VECTOR).map { it.fn }.toSet()
        assertEquals(setOf("tables", "caracole.web.feed._ordinal", "caracole.web.feed._ago", "caracole.stamps.shown",
                           "caracole.library_page._requests_tab", "caracole.web.feed.feed"), fns)
    }

    @Test
    fun `the feed is recorded under UTC and Madrid, each record's answer Feed's`() {
        val feeds = Corpus.records(RequestsReplay.VECTOR).filter { it.fn == "caracole.web.feed.feed" }
        assertEquals(setOf("UTC", "Europe/Madrid"), feeds.map(RequestsReplay::zone).toSet())
        for (r in feeds) assertEquals(r.out!!.jsonPrimitive.content, RequestsReplay.answer(r), "${r.extra["note"]}")
    }

    @Test
    fun `Madrid's clock is CET in winter and CEST in summer, as tzdata names it, never GMT+01 00`() {
        val madrid = ZoneId.of("Europe/Madrid")
        assertEquals("CET", names.label(madrid, Instant.parse("2026-01-15T12:00:00Z")))
        assertEquals("CEST", names.label(madrid, Instant.parse("2026-07-15T12:00:00Z")))
        assertEquals("CEST", names.label(madrid, Instant.parse("2026-10-25T00:59:59Z")))
        assertEquals("CET", names.label(madrid, Instant.parse("2026-10-25T01:00:00Z")))
        assertEquals("2026-11-04 00:27 CET", Feed.shown(Instant.parse("2026-11-03T23:27:00Z"), madrid))
        assertEquals("2026-10-25 02:30 CEST", Feed.shown(Instant.parse("2026-10-25T00:30:00Z"), madrid))
        assertEquals("2026-10-25 02:30 CET", Feed.shown(Instant.parse("2026-10-25T01:30:00Z"), madrid))
        assertEquals("2026-11-03 23:27 UTC", Feed.shown(Instant.parse("2026-11-03T23:27:00Z"), ZoneId.of("UTC")))
    }

    @Test
    fun `an offset tzdata names by its number is named so, and a label that changes changes at its second`() {
        assertEquals("-03", names.label(ZoneId.of("America/Sao_Paulo"), Instant.parse("2026-01-15T12:00:00Z")))
        assertEquals("+0545", names.label(ZoneId.of("Asia/Kathmandu"), Instant.parse("2026-01-15T12:00:00Z")))
        assertEquals(listOf("+00", "-03", "+0545", "-0930", "+14"),
                     listOf(0, -3 * 3600, 5 * 3600 + 45 * 60, -(9 * 3600 + 30 * 60), 14 * 3600).map(ZoneNames::numeric))
        // A label of an offset that changes (Edmonton's -06, MDT then CST in tzdata 2026d) changes at its second.
        val edmonton = ZoneId.of("America/Edmonton")
        val table = ZoneNames(mapOf(edmonton.id to listOf(ZoneNames.Entry(-25200, "MST", null),
                                                            ZoneNames.Entry(-21600, "MDT", null),
                                                            ZoneNames.Entry(-21600, "CST", 1793520000L))))
        val summer = Instant.parse("2026-07-15T12:00:00Z")
        assertEquals("MDT", table.label(edmonton, summer))
        assertEquals("MST", table.label(edmonton, Instant.parse("2026-01-15T12:00:00Z")))
        assertEquals("+00", ZoneNames(emptyMap()).label(ZoneId.of("Etc/UTC"), summer))
        val later = Instant.ofEpochSecond(1793520000L)
        if (edmonton.rules.getOffset(later).totalSeconds == -21600) {  // this JDK's tzdata has the change too
            assertEquals("CST", table.label(edmonton, later))
            assertEquals("CST", names.label(edmonton, later))
        }
    }

    @Test
    fun `no request is an empty feed`() {
        assertEquals(JsonObject(linkedMapOf("active" to JsonPrimitive(0), "groups" to JsonArray(emptyList()))),
                     Feed.feed(emptyList(), emptyMap(), now = Instant.parse("2026-11-03T12:00:00Z"), zone = ZoneId.of("UTC")))
    }

    @Test
    fun `a queued request's place and how long ago one started read as Python's`() {
        assertEquals(listOf("next", "next", "2nd", "3rd", "4th", "11th", "12th", "13th", "21st", "111th", "112th", "122nd"),
                     listOf(0L, 1, 2, 3, 4, 11, 12, 13, 21, 111, 112, 122).map(Feed::ordinal))
        val now = Instant.parse("2026-11-03T12:00:00.250Z")
        assertEquals("0 s ago", Feed.ago(now.plusSeconds(90), now))
        assertEquals("59 s ago", Feed.ago(now.minusMillis(59_999), now))
        assertEquals("1 min ago", Feed.ago(now.minusSeconds(60), now))
        assertEquals("59 min ago", Feed.ago(now.minusSeconds(3599), now))
        assertEquals("1 h ago", Feed.ago(now.minusSeconds(3600), now))
    }

    @Test
    fun `the tables are feed py's`() {
        val tables = Corpus.records(RequestsReplay.VECTOR).single { it.fn == "tables" }.out!!.jsonObject
        assertEquals(tables.getValue("SEARCH").jsonPrimitive.content, Feed.SEARCH)
        assertTrue(Feed.SEARCH in Feed.PRIMARY)
    }
}
