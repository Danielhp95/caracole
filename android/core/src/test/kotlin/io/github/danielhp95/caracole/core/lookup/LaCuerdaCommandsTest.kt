package io.github.danielhp95.caracole.core.lookup

import io.github.danielhp95.caracole.core.config.ProviderPolicy
import io.github.danielhp95.caracole.core.db.Db
import io.github.danielhp95.caracole.core.health.Health
import io.github.danielhp95.caracole.core.health.ProviderState
import io.github.danielhp95.caracole.core.http.Client
import io.github.danielhp95.caracole.core.http.ProviderBlocked
import io.github.danielhp95.caracole.core.http.ProviderError
import io.github.danielhp95.caracole.core.lacuerda.LaCuerdaSearch
import io.github.danielhp95.caracole.core.lookup.sites.LaCuerdaCommands
import io.github.danielhp95.caracole.core.testing.FakeAsking
import io.github.danielhp95.caracole.core.testing.Misses
import io.github.danielhp95.caracole.core.testing.TestDb
import io.github.danielhp95.caracole.core.testing.replays.LaCuerdaReplay
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import java.time.Instant
import kotlin.test.assertEquals
import kotlin.test.assertNull

/** `caracole lacuerda --artist` and `--search` on the phone against Python's lines and writes
 * (vectors/lookup/commands_lacuerda.jsonl), and what asking came to that a record can't make (a fake asking). */
class LaCuerdaCommandsTest {
    @get:Rule val folder = TemporaryFolder()

    private val now = Instant.parse("2026-11-03T12:00:00Z")

    /** Each command's last line ("Read: ", "Not found: ", "Not read: ", "Searched: ", "Found already: ", "Nothing
     * found: ", "Not searched: "), its search's progress lines before it, its writes, through lane lookup's
     * InteractiveAsk as LaCuerdaRunner asks. */
    @Test fun everyCommandRecordMatches() = Misses("lookup/commands_lacuerda.jsonl").also { LaCuerdaReplay.commands(it) }.assertNone()

    private class Context(override val db: Db, override val asking: Asking, override val now: Instant) : CommandContext {
        val said = ArrayList<String>()
        override fun say(line: String) {
            said += line
        }
    }

    private fun <T> world(block: (Db) -> T): T = TestDb.fresh(folder.root).use { it.writeBlocking(block) }

    /** An asking that comes to [asked] and sends nothing. */
    private fun asking(asked: Asked<Nothing>): Asking = object : Asking {
        override fun <T> ask(provider: String, policy: ProviderPolicy?, work: (Client) -> T): Asked<T> = asked
        override val requests: Map<String, Int> = emptyMap()
    }

    @Test fun anArtistsPageNotReadSaysWhy() = world { db ->
        fun line(asked: Asked<Nothing>) = LaCuerdaCommands.artist(Context(db, asking(asked), now), "Soda Stereo", null)
        assertEquals("Not read: this fetch's 6 asks of LaCuerda are spent. Ask again later.",
                     line(Asked.Spent(hour = false, keptForSheets = false)))
        assertEquals("Not read: no more asks of LaCuerda this hour (60 spent). Ask again later.",
                     line(Asked.Spent(hour = true, keptForSheets = false)))
        val blocked = ProviderBlocked("lacuerda", "https://acordes.lacuerda.net/soda_stereo/", 403, "HTTP 403")
        assertEquals("Not read: LaCuerda turned us back (lacuerda: 403: https://acordes.lacuerda.net/soda_stereo/: " +
                         "HTTP 403); no asks until 2026-11-04 14:00 UTC.",
                     line(Asked.Blocked(blocked, ProviderState("lacuerda", cooldownUntil = Instant.parse("2026-11-04T14:00:00Z")))))
        assertEquals("Not read: LaCuerda failed (lacuerda: 500: x). Try again later.",
                     line(Asked.Failed(ProviderError("lacuerda", "x", 500))))
        assertEquals("Not read: waiting out LaCuerda until " +
                         "2026-11-04 14:00 UTC.", line(Asked.Cooling(Instant.parse("2026-11-04T14:00:00Z"))))
        assertEquals("Not read: no client for lacuerda; nothing changed.",
                     LaCuerdaCommands.artist(Context(db, FakeAsking(emptyMap()), now), "Soda Stereo", null))
        assertNull(Health.state(db, "lacuerda").cooldownUntil)  // the asking records a block, never the command
    }

    @Test fun aSearchSaysItsStageThenItsLastLine() = world { db ->
        val none = Context(db, FakeAsking(emptyMap()), now)
        val line = LaCuerdaCommands.search(none, "sol y luz", auto = true)
        assertEquals("Not searched: LaCuerda needs a word of 4 letters or more; “sol y luz” has none.", line)
        assertEquals(listOf("caracole-progress: {\"stage\":\"search\",\"state\":\"skipped\",\"detail\":\"$line\"}"), none.said)

        val spent = Context(db, asking(Asked.Spent(hour = true, keptForSheets = false)), now)
        assertEquals("Not searched: the search's one ask is spent. Ask again later.",
                     LaCuerdaCommands.search(spent, "corazón de tiza", auto = false))
        assertEquals(listOf("running", "skipped"), spent.said.map { it.substringAfter("\"state\":\"").substringBefore('"') })
        assertNull(db.kvGet(LaCuerdaSearch.FAILED_KEY))

        val failed = Context(db, asking(Asked.Failed(ProviderError("lacuerda", "x", 500))), now)
        assertEquals("Not searched: LaCuerda failed (lacuerda: 500: x). Try again later.",
                     LaCuerdaCommands.search(failed, "corazón de tiza", auto = true))
        assertEquals("LaCuerda failed: lacuerda: 500: x", LaCuerdaSearch.failed(db, "corazon-tiza", now)?.error)
        assertEquals("Not searched: LaCuerda's search for “corazón de tiza” failed within the hour (LaCuerda failed: " +
                         "lacuerda: 500: x); not sent by itself before 2026-11-03 13:00 UTC. Ask LaCuerda or Try again " +
                         "asks now.",
                     LaCuerdaCommands.search(failed, "corazón de tiza", auto = true))
    }

    /** Without `--progress`, a search says its last line alone, as Python prints it. */
    @Test fun aSearchWithoutProgressSaysNothingButItsLastLine() = world { db ->
        val quiet = Context(db, asking(Asked.Spent(hour = true, keptForSheets = false)), now)
        assertEquals("Not searched: the search's one ask is spent. Ask again later.",
                     LaCuerdaCommands.search(quiet, "corazón de tiza", auto = false, progress = false))
        assertEquals(emptyList(), quiet.said)
    }
}
