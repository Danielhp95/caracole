package io.github.danielhp95.caracole.core.lacuerda

import org.junit.Test
import kotlin.test.assertEquals

/**
 * Whether stamps.parse reads a stored time, as lacuerda_index.complete_at asks it: each answer below was asked of
 * Python 3.14's `stamps.parse` (CPython's C `datetime.fromisoformat`), caracole's own stamps first, then the other
 * forms it reads and those it refuses, its quirks included.
 */
class IsoTimeTest {
    @Test fun caracolesOwnStampsAreTimes() = check(
        "2026-10-20T03:30:00Z" to true, "2026-10-20T03:30:00+00:00" to true, "2026-10-20 03:30:00" to true,
        "2026-10-20" to true, "2024-02-29T00:00:00Z" to true,
    )

    @Test fun theOtherFormsFromisoformatReadsAreTimesToo() = check(
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

    @Test fun itsQuirksAreKept() = check(
        "2026-10-21x03:30:00" to true, // any one character between the date and the time
        "2026-10-21é03:30" to true, // a non-ASCII one too
        "2026-10-21\ud80003:30" to true, // a lone surrogate there read as T
        "20261020+0100" to true, // the + as the separator: 01:00
        "2026-10-21T03:30:00x+01:00" to true, // one stray character before the offset
        "2026-10-21T03:30:00+05:60" to true, // an offset's fields unchecked, its total under a day
    )

    @Test fun whatItRefusesIsNoTime() = check(
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

    private fun check(vararg cases: Pair<String, Boolean>) {
        for ((text, reads) in cases) assertEquals(reads, IsoTime.reads(text), text)
    }
}
