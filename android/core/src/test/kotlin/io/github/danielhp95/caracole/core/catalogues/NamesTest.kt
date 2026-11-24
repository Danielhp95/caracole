package io.github.danielhp95.caracole.core.catalogues

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test
import java.time.Instant

class NamesTest {
    @Test fun aNameHoldsTheSchemaAndTheMinute() {
        assertEquals(Named(17, Instant.parse("2026-11-24T03:12:00Z")), Names.read("indexes-s17-20261124T0312Z.sqlite.gz"))
    }

    @Test fun otherNamesReadAsNone() {
        for (name in listOf(
            "indexes.json",
            "indexes.json.prev",
            "indexes-s17-20261124T0312Z.sqlite.gz.next",
            "indexes2-s17-20261124T0312Z.sqlite.gz",
            "indexes-s17-20261340T0312Z.sqlite.gz",
            "indexes-sx-20261124T0312Z.sqlite.gz",
            "indexes-s-20261124T0312Z.sqlite.gz",
            "indexes-s017-20261124T0312Z.sqlite.gz",
            "indexes-s17-2026112T0312Z.sqlite.gz",
            "indexes-s17-20261124T031Z.sqlite.gz",
            "indexes-s17-20261124t0312Z.sqlite.gz",
            "indexes-s17-20261124T0312z.sqlite.gz",
            "indexes-s17-20261124T0312Z.sqlite",
            "Indexes-s17-20261124T0312Z.sqlite.gz",
            "indexes-s99999999999-20261124T0312Z.sqlite.gz",
            "indexes-s١٧-20261124T0312Z.sqlite.gz",
            "indexes-s17-٢٠٢٦1124T0312Z.sqlite.gz",
            "indexes-s17-00001124T0312Z.sqlite.gz",
            "",
        )) assertNull(name, Names.read(name))
    }

    @Test fun aDateMustBeOnTheCalendar() {
        assertEquals(Named(17, Instant.parse("2028-02-29T00:00:00Z")), Names.read("indexes-s17-20280229T0000Z.sqlite.gz"))
        assertNull(Names.read("indexes-s17-20270229T0000Z.sqlite.gz"))
        assertNull(Names.read("indexes-s17-20261131T0000Z.sqlite.gz"))
        assertNull(Names.read("indexes-s17-20261100T0000Z.sqlite.gz"))
    }

    @Test fun aTimeMustBeOnTheClock() {
        assertEquals(Named(1, Instant.parse("2026-11-24T23:59:00Z")), Names.read("indexes-s1-20261124T2359Z.sqlite.gz"))
        assertNull(Names.read("indexes-s17-20261124T2400Z.sqlite.gz"))
        assertNull(Names.read("indexes-s17-20261124T1260Z.sqlite.gz"))
    }
}
