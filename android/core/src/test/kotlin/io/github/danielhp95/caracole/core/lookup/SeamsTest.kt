package io.github.danielhp95.caracole.core.lookup

import io.github.danielhp95.caracole.core.testing.TestDb
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import kotlin.test.assertEquals

/** The seams a lookup's later stages call are neutral until their milestones. */
class SeamsTest {
    @get:Rule val tmp = TemporaryFolder()

    @Test fun nonePagesMakeNothing() {
        TestDb.fresh(tmp.root).use { database ->
            database.read { db ->
                assertEquals(RenderStats(), SongPages.NONE.render(db, listOf(1L), null))
                assertEquals(SongbookStats(), SongbookPages.NONE.render(db, null))
            }
        }
    }
}
