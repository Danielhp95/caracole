package io.github.danielhp95.caracole.core.sync

import io.github.danielhp95.caracole.core.testing.Misses
import io.github.danielhp95.caracole.core.testing.replays.SyncReplay
import org.junit.Test
import kotlin.test.assertEquals

/** What a sync took and gave, a line a unit (SyncSaid), against vectors/sync/said.jsonl
 * (tests/test_conformance_sync_said.py): commands/peer.py's done_lines for each outcome, line for line. */
class SyncSaidTest {
    @Test fun everyRecordOfSaidJsonlReplays() = Misses(SyncReplay.SAID).also(SyncReplay::said).assertNone()

    @Test fun theWordsAreTheCorpusDatas() {
        assertEquals("Took Radiohead - Creep", SyncSaid.line(SyncSaid.TAKEN, "Radiohead -\n Creep"))
        assertEquals(20, SyncSaid.MOST)
    }
}
