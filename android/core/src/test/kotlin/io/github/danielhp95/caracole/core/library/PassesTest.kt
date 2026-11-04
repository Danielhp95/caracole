package io.github.danielhp95.caracole.core.library

import io.github.danielhp95.caracole.core.http.BudgetExhausted
import io.github.danielhp95.caracole.core.http.PagesNotFiles
import io.github.danielhp95.caracole.core.http.ProviderBlocked
import io.github.danielhp95.caracole.core.http.ProviderError
import io.github.danielhp95.caracole.core.http.ProviderUnavailable
import io.github.danielhp95.caracole.core.testing.Misses
import io.github.danielhp95.caracole.core.testing.replays.LibraryWritesReplay
import org.junit.Test
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith
import kotlin.test.assertFalse
import kotlin.test.assertSame
import kotlin.test.assertTrue

/**
 * provider_pass.each_song's ladder (vectors/library/writes.jsonl, and as tests/test_lyrics_pending.py and
 * test_gtptabs_fetch.py hold the passes to it): a block propagates, a spent budget ends the pass, Unavailable fails
 * the rest, any other error records a failure and moves on.
 */
class PassesTest {
    private fun songs(vararg names: String) = names.map(LibraryWritesReplay::stub)

    private fun error(name: String) = ProviderError("site", "https://s/$name", 500, "busy")

    @Test fun theLadderIsProviderPasss() {
        val misses = Misses("library-writes: provider_pass.py")
        LibraryWritesReplay.replay(misses) { it == "caracole.provider_pass.each_song" }
        misses.assertNone()
    }

    @Test fun aBlockPropagatesWithTheStatsAsFarAsThePassGot() {
        val stats = PassStats()
        val block = ProviderBlocked("site", status = 429)
        val raised = assertFailsWith<ProviderBlocked> {
            Passes.eachSong(songs("a", "b", "c"), stats, "site") { if (it.key == "b") throw block }
        }
        assertSame(block, raised)
        assertEquals(1, stats.tried)
        assertTrue(stats.failures.isEmpty())
    }

    @Test fun aSpentBudgetEndsThePassAndNoSongIsAMiss() {
        val turned = mutableListOf<String>()
        val stats = Passes.eachSong(songs("a", "b", "c"), PassStats(), "site") {
            turned += it.key
            if (it.key == "b") throw BudgetExhausted("site")
        }
        assertEquals(listOf("a", "b"), turned)
        assertTrue(stats.budgetExhausted)
        assertEquals(1, stats.tried)
        assertTrue(stats.failures.isEmpty())
    }

    @Test fun unavailableFailsEverySongLeftWithItsErrorNeverAskingAboutThem() {
        val gone = ProviderUnavailable("site", msg = "too many errors")
        val turned = mutableListOf<String>()
        val heard = mutableListOf<String>()
        val stats = Passes.eachSong(songs("a", "b", "c", "d"), PassStats(), "site", onError = { s, _ -> heard += s.key }) {
            turned += it.key
            if (it.key == "a") throw error("a")
            if (it.key == "b") throw gone
        }
        assertEquals(listOf("a", "b"), turned)
        assertEquals(listOf("a"), heard)
        assertEquals(listOf("a", "b", "c", "d"), stats.failures.map { it.first.key })
        assertEquals(listOf(gone, gone, gone), stats.failures.drop(1).map { it.second })
        assertEquals(1 to 1, stats.tried to stats.errors)
    }

    @Test fun anErrorStoppedOnIsCountedThenEndsThePassAndASubclassStopsItToo() {
        val stats = Passes.eachSong(songs("a", "b", "c"), PassStats(), "site", stopOn = setOf(ProviderError::class)) {
            if (it.key == "b") throw PagesNotFiles("site", msg = "a page, not a file")
        }
        assertEquals(2 to 1, stats.tried to stats.errors)
        assertEquals(listOf("b"), stats.failures.map { it.first.key })
    }

    @Test fun songsAreReadLazilySoAFilterSeesWhatTheTurnsBeforeDid() {
        val done = mutableSetOf<String>()
        val source = songs("a", "b", "a2")
        // "a2" is the same song as "a" by the filter's rule: the pass reads it after a's turn, and leaves it.
        val wanted = source.asSequence().filter { s -> s.key.take(1) !in done }
        val got = Passes.eachSong(wanted, PassStats(), "site") { done += it.key.take(1); it.key }.map { it.second }.toList()
        assertEquals(listOf("a", "b"), got)
    }

    @Test fun theCallersOwnWorkIsOutsideTheLadder() {
        val stats = PassStats()
        val raised = assertFailsWith<ProviderError> {
            for ((song, _) in Passes.eachSong(songs("a", "b").asSequence(), stats, "site") { it.key }) {
                if (song.key == "a") throw error("a") // the caller's, after the turn: never one of the pass's
            }
        }
        assertEquals("site: 500: https://s/a: busy", raised.message)
        assertEquals(1, stats.tried)
        assertFalse(stats.failures.isNotEmpty())
    }

    @Test fun aSubclassOfPassStatsComesBackAsItself() {
        class Counted(var kept: Int = 0) : PassStats()
        val stats: Counted = Passes.eachSong(songs("a", "b"), Counted(), "site") { }
        stats.kept++
        assertEquals(2 to 1, stats.tried to stats.kept)
    }
}
