package io.github.danielhp95.caracole.core.index

import io.github.danielhp95.caracole.core.testing.TestDb
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import kotlin.test.assertEquals

/** The pages a lookup stored, noted until a push to that computer forgets them. */
class ReadsTest {
    @get:Rule val tmp = TemporaryFolder()

    @Test fun pagesNotedAreThoseSinceTheLastPush() {
        TestDb.fresh(tmp.root).use { database ->
            database.writeBlocking { db ->
                Reads.note(db, "ug", "/artist/oasis_1", "2026-11-03T10:00:00Z")
                Reads.note(db, "lacuerda", "estopa", "2026-11-03T10:00:01Z")
                assertEquals(mapOf("lacuerda" to listOf("estopa"), "ug" to listOf("/artist/oasis_1")), Reads.since(db, "pc"))
                Reads.forget(db, "pc", "2026-11-03T10:00:00Z")
                assertEquals(mapOf("lacuerda" to listOf("estopa")), Reads.since(db, "pc"))
                assertEquals(mapOf("lacuerda" to listOf("estopa")), Reads.since(db, "other"))
            }
        }
    }
}
