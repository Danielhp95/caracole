package io.github.danielhp95.caracole.core.sync

import io.github.danielhp95.caracole.core.testing.Misses
import io.github.danielhp95.caracole.core.testing.replays.SyncReplay
import org.junit.Assume
import org.junit.Test
import kotlin.test.assertEquals
import kotlin.test.assertNull

/**
 * A sync's parts on the phone (the sync redesign's §3.2) against vectors/sync/scope.jsonl
 * (tests/test_conformance_sync_kept.py): in_scope, listed_songs, change_of and names_of, each record Python's answer
 * to the same call (SyncReplay's, which the device runs too).
 */
class ScopeTest {
    @Test fun everyRecordOfScopeJsonlReplays() = Misses(SyncReplay.SCOPE).also(SyncReplay::scope).assertNone()

    @Test fun theSongsSongbooksListAreThoseOfAnyCutOfAnEntry() {
        Assume.assumeTrue("waiting on songbook-writers: Songbooks.entryKeys", SyncReplay.listing())
        Misses("${SyncReplay.SCOPE} listed_songs").also(SyncReplay::listedSongs).assertNone()
    }

    @Test fun aFileThatHoldsNoLibraryNeverReadsASongItLacksAsRemoved() {
        fun d(id: String, mine: String?, theirs: String?, proposal: String) =
            Difference(id, id, mine?.let { SyncUnit(id, id, it) }, theirs?.let { SyncUnit(id, id, it) }, proposal, "")
        val found = listOf(
            d("song/a/only-here", "1", null, Compare.MINE),  // the file lacks it: never a removal
            d("song/a/listed", "1", "2", Compare.THEIRS),  // a song the file's songbook lists: comes along
            d("song/a/listed-gone-there", "1", null, Compare.THEIRS),  // would remove it here: left
            d("songbook/campfire", "1", "2", Compare.THEIRS),
            d("removed/a/b", null, "1", Compare.THEIRS),  // a tombstone is the library's
        )
        val listed = mapOf("song/a/listed" to listOf("songbook/campfire"), "song/a/listed-gone-there" to listOf("songbook/campfire"))
        val holds = listOf(Scope.SONGBOOKS)
        assertEquals(listOf("song/a/listed", "songbook/campfire"),
                     Scope.inScope(found, holds, listed, holds).map { it.id })
        // Every part asked of a songbooks-only file: still no song it lacks is removed.
        assertEquals(listOf("song/a/listed", "songbook/campfire", "removed/a/b"),
                     Scope.inScope(found, Scope.PARTS, listed, holds).map { it.id })
        assertEquals(listOf("song/a/only-here", "song/a/listed", "song/a/listed-gone-there", "songbook/campfire", "removed/a/b"),
                     Scope.inScope(found, Scope.PARTS, listed).map { it.id })
        assertNull(Scope.partOf("other/x"))
        assertNull(Scope.partOf("song"))
        assertEquals("library" to "songbooks", Scope.partOf("block/4242") to Scope.partOf("songbook/x"))
    }
}
