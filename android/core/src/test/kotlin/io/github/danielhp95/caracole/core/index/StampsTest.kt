package io.github.danielhp95.caracole.core.index

import io.github.danielhp95.caracole.core.testing.Corpus
import io.github.danielhp95.caracole.core.testing.Misses
import io.github.danielhp95.caracole.core.testing.replays.IndexReplay
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.jsonPrimitive
import org.junit.Test
import java.time.Instant
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith
import kotlin.test.assertTrue

/** Stamps, the one port of stamps.py, against stamps.parse's vectors (tests/conformance/vectors/index/stamps.jsonl:
 * datetime.fromisoformat's C reading, its edges and a seeded sample around them, then the time in UTC; and
 * library/stamps.jsonl, a take's times), and what its callers write with it. */
class StampsTest {
    @Test fun parseIsStampsParseForEveryVector() = Misses(IndexReplay.STAMPS).also { IndexReplay.stamps(it) }.assertNone()

    @Test fun aStampIsWrittenToTheSecondInUtc() {
        val at = Stamps.parse("2026-10-18T05:30:00.75+02:00")!!
        assertEquals("2026-10-18T03:30:00Z", Stamps.stamp(at))
        assertEquals("2026-10-18T03:30:00.750000+00:00", Stamps.isoformat(at))
        assertEquals("0001-01-01T00:00:00Z", Stamps.stamp(Stamps.parse("0001-01-01")!!))
        assertEquals("9999-12-31T23:59:59Z", Stamps.stamp(Stamps.parse("9999-12-31T23:59:59.999999")!!))
        assertEquals(null, Stamps.parse(null as String?))
        assertEquals("2026-10-18T03:30:00Z", Stamps.stamp(Stamps.parse("2026-10-18T03:30:00Z".jsonPrimitiveOf())!!))
    }

    @Test fun theLibrarysTimesAreReadAsStampsParseReadsThemToo() {
        val records = Corpus.records("library/stamps.jsonl")
        assertTrue(records.size >= 30)
        for (r in records) {
            val value = r.args[0]
            val text = if (value is JsonNull) null else value.jsonPrimitive.content
            val want = (r.out as? JsonObject)?.let { it.getValue("iso").jsonPrimitive.content to
                it.getValue("stamp").jsonPrimitive.content }
            val got = Stamps.parse(text)?.let { Stamps.isoformat(it) to Stamps.stamp(it) }
            assertEquals(want, got, "stamps.parse($value)")
        }
    }

    @Test fun aTimeTheClockGivesIsStampedToTheSecond() {
        val at = Instant.parse("2026-10-18T03:30:00.987654321Z")
        assertEquals("2026-10-18T03:30:00Z", Stamps.of(at))
        assertEquals(Stamps.parse("2026-10-18T03:30:00.987654Z"), Stamps.micros(at))
        assertEquals(Instant.parse("2026-10-18T03:30:00.987654Z"), Stamps.instant(Stamps.micros(at)))
        assertEquals("1970-01-01T00:00:00Z", Stamps.of(Instant.EPOCH))
        assertEquals("1969-12-31T23:59:59Z", Stamps.of(Instant.parse("1969-12-31T23:59:59.5Z")))
        assertEquals(Instant.parse("0001-01-01T00:00:00Z"), Stamps.instant(0L))
        assertTrue(Regex("""\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ""").matches(Stamps.now()))
    }

    @Test fun aTimeThatIsNoneSaysSoInPythonsWords() {
        assertEquals("2026-10-31T00:00:00Z", Stamps.stampOf("2026-10-31T02:00:00+02:00"))
        assertEquals("2026-10-31T00:00:00Z", Stamps.stampOf("2026-10-31"))
        assertEquals("not a time: 'soon'", assertFailsWith<IllegalArgumentException> { Stamps.stampOf("soon") }.message)
        assertEquals("not a time: ''", assertFailsWith<IllegalArgumentException> { Stamps.stampOf("") }.message)
        assertFailsWith<ArithmeticException> { Stamps.stampOf("0001-01-01T00:00:00+01:00") } // Python's OverflowError
    }

    // Whether stamps.parse reads a stored time, as lacuerda_index.complete_at asks it: each answer was asked of Python
    // 3.14's stamps.parse (CPython's C datetime.fromisoformat), caracole's own stamps first, then the other forms it
    // reads and those it refuses, its quirks included.

    @Test fun caracolesOwnStampsAreTimes() = reads(
        "2026-10-20T03:30:00Z" to true, "2026-10-20T03:30:00+00:00" to true, "2026-10-20 03:30:00" to true,
        "2026-10-20" to true, "2024-02-29T00:00:00Z" to true,
    )

    @Test fun theOtherFormsFromisoformatReadsAreTimesToo() = reads(
        "20261020" to true, "2026-10-20T03:30:00.123456Z" to true, "2026-10-20T03:30:00,5" to true,
        "2026-10-20T03:30" to true, "2026-10-21T03" to true, "2026-10-21T0330" to true, "2026-10-21T033000" to true,
        "2026-10-21T03:30:00-05:00" to true, "2026-10-21T03:30:00+0530" to true, "2026-10-21T03:30:00+05" to true,
        "2026-10-21T03:30:00-0530" to true, "2026-10-21T03:30:00+05:30:15" to true,
        "2026-10-21T03:30:00+05:30:15.5" to true, "2026-10-21T03:30:00+23:59" to true,
        "2026-10-21T03:30:00.1234567" to true, "2026-10-21T03:30:00,1234567Z" to true,
        "2026-W43-1" to true, "2026W431" to true, "2026-W43" to true, "2026W43" to true, "2026-W53-1" to true,
        "2020-W53-1" to true, "2026-W43-03:30" to true, "2026-W43-1T03" to true, "2026W43T03" to true,
        "2026W431203" to true, "20261020T0330Z" to true, "2026-10-21T24:00:00" to true, "2026-12-31T24:00" to true,
    )

    @Test fun itsQuirksAreKept() = reads(
        "2026-10-21x03:30:00" to true, // any one character between the date and the time
        "2026-10-21é03:30" to true, // a non-ASCII one too
        "2026-10-21\ud80003:30" to true, // a lone surrogate there read as T
        "20261020+0100" to true, // the + as the separator: 01:00
        "2026-10-21T03:30:00x+01:00" to true, // one stray character before the offset
        "2026-10-21T03:30:00+05:60" to true, // an offset's fields unchecked, its total under a day
    )

    @Test fun whatItRefusesIsNoTime() = reads(
        "" to false, "not a time" to false, "2026-10-2" to false, "2026-1-21" to false, "2026-13-01" to false,
        "2026-02-29" to false, "0000-01-01" to false, "2026-10-21T" to false, "2026-10-21T24:00:01" to false,
        "9999-12-31T24:00:00" to false, "2026-10-21T25:00" to false, "2026-10-21T03:60" to false,
        "2026-10-21T3:30" to false, "2026-10-21T03:3000" to false, "2026-10-21T0330:00" to false,
        "2026-10-21T1230005" to false, "2026-10-21T03,5" to false, "2026-10-21T03:30,5" to false,
        "2026-10-21T03:30.5" to false, "2026-10-21T03:30:00." to false, "2026-10-21T03:30:00.+01:00" to false,
        "2026-10-21T03:30:00 " to false, " 2026-10-21" to false, "２０２６-10-21" to false, "2026-10é21" to false,
        "2026-10-21T03:30:00ZZ" to false, "2026-10-21T03:30:00Z1" to false, "2026-10-21T03:30:00+01:00Z" to false,
        "2026-10-21T03:30:00+24:00" to false, "2026-10-21T03:30:00+1" to false, "2026-10-21T03:30\ud800" to false,
        "2025-W53-1" to false, "2026-W43-8" to false, "2026-W00-1" to false, "2026W4312" to false,
    )

    private fun reads(vararg cases: Pair<String, Boolean>) {
        for ((text, reads) in cases) assertEquals(reads, Stamps.parse(text) != null, text)
    }

    private fun String.jsonPrimitiveOf() = JsonPrimitive(this).jsonPrimitive
}
