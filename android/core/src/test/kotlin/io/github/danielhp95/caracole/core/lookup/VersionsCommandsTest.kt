package io.github.danielhp95.caracole.core.lookup

import io.github.danielhp95.caracole.core.config.ProviderPolicy
import io.github.danielhp95.caracole.core.db.Db
import io.github.danielhp95.caracole.core.health.Health
import io.github.danielhp95.caracole.core.health.ProviderState
import io.github.danielhp95.caracole.core.http.Client
import io.github.danielhp95.caracole.core.http.ProviderBlocked
import io.github.danielhp95.caracole.core.http.ProviderError
import io.github.danielhp95.caracole.core.http.Response
import io.github.danielhp95.caracole.core.library.Kept
import io.github.danielhp95.caracole.core.library.LibraryStore
import io.github.danielhp95.caracole.core.library.SongRow
import io.github.danielhp95.caracole.core.library.Versions
import io.github.danielhp95.caracole.core.lookup.sites.VersionsCommands
import io.github.danielhp95.caracole.core.testing.FakeAsking
import io.github.danielhp95.caracole.core.testing.Misses
import io.github.danielhp95.caracole.core.testing.TestDb
import io.github.danielhp95.caracole.core.testing.replays.UgFetchReplay
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertThrows
import org.junit.Assert.assertTrue
import org.junit.Assume.assumeTrue
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import java.io.File
import java.time.Duration
import java.time.Instant

/**
 * VersionsCommands replays vectors/lookup/commands_versions.jsonl (versions_cmd.py's keep and keep_more in turn: every
 * answer and refusal, a block and its cooldown, keep-more through one client until a block or the lookup's budget,
 * nothing left), and says versions_cmd.py's words for what asking came to.
 */
class VersionsCommandsTest {
    @get:Rule val tmp = TemporaryFolder()

    @Test fun everyRecordOfTheVersionsCommandsReplays() {
        assumeTrue("waiting on ug-pages, rank-coverage and html-tree", UgFetchReplay.ready)
        val misses = Misses(UgFetchReplay.VERSIONS)
        UgFetchReplay.versions(misses)
        misses.assertNone()
    }

    @Test fun theVectorHoldsKeepsAndKeepMoresTurns() {
        val turns = UgFetchReplay.records(UgFetchReplay.VERSIONS).flatMap {
            it.getValue("out").jsonObject.getValue("result").jsonArray.map { t -> t.jsonObject }
        }
        assertTrue(turns.count { "error" in it } >= 3)
        assertTrue(turns.size >= 15)
    }

    private class Said(override val db: Db, override val asking: Asking, override val now: Instant = NOW) : CommandContext {
        val lines = ArrayList<String>()
        override fun say(line: String) {
            lines += line
        }
    }

    /** An asking that answers [asked] and sends nothing. */
    private class Answers(private val asked: Asked<Nothing>) : Asking {
        override fun <T> ask(provider: String, policy: ProviderPolicy?, work: (Client) -> T): Asked<T> = asked
        override val requests: Map<String, Int> = emptyMap()
    }

    /** A library of one song, its sheet tab 101 and tab 102 kept beside it, and tabs 103 and 104 not kept. */
    private fun withSong(check: (Db, LibraryStore, SongRow) -> Unit) {
        TestDb.fresh(tmp.newFolder()).use { database ->
            database.writeBlocking { db ->
                val library = LibraryStore(tmp.newFolder())
                val song = library.add(db, "Soda Stereo", "Persiana Americana", now = STAMP)
                val ids = (101L..104L).associateWith { tab ->
                    Versions.upsert(db, "ug", tab.toString(), song.id, "sheet", "chords", 4.5, 10, (tab - 100).toInt(),
                                    null, "https://tabs.ultimate-guitar.com/tab/$tab", JsonObject(emptyMap()), STAMP)
                }
                Kept.keepFile(db, library, song, ids.getValue(101), "sheet.txt", "sheet 101\n".toByteArray(), 1, STAMP)
                Kept.keepFile(db, library, song, ids.getValue(102), "version-102.txt", "sheet 102\n".toByteArray(), 2,
                              STAMP)
                db.execute("INSERT INTO phone_overrides (tbl, key, written, value) VALUES ('block', '104', '104', 'true')")
                check(db, library, song)
            }
        }
    }

    @Test fun aVersionTheSongHasntOrUgNoLongerHasOrYouBlockedIsRefused() = withSong { db, library, song ->
        val c = Said(db, FakeAsking(emptyMap()))
        assertEquals("Tab 999 isn't one of the Ultimate Guitar chords versions of Soda Stereo - Persiana Americana: " +
                         "caracole versions \"Soda Stereo - Persiana Americana\" lists them.",
                     assertThrows(VersionsCommands.KeepRefused::class.java) { VersionsCommands.keep(c, library, song, 999) }.message)
        assertEquals("Tab 104 is under [block] in overrides.toml: caracole never uses it.",
                     assertThrows(VersionsCommands.KeepRefused::class.java) { VersionsCommands.keep(c, library, song, 104) }.message)
        db.execute("UPDATE versions SET gone = ${Versions.GONE} WHERE tab_id = '103'")
        assertEquals("Ultimate Guitar no longer has tab 103 of Soda Stereo - Persiana Americana.",
                     assertThrows(VersionsCommands.KeepRefused::class.java) { VersionsCommands.keep(c, library, song, 103) }.message)
        assertEquals(emptyList<String>(), c.lines)
    }

    @Test fun theSheetAndAVersionKeptBesideItAskNothing() = withSong { db, library, song ->
        val c = Said(db, FakeAsking(emptyMap()))
        assertEquals("Tab 101 is the sheet of Soda Stereo - Persiana Americana already.",
                     VersionsCommands.keep(c, library, song, 101))
        assertEquals(listOf(
            """caracole-progress: {"song":{"id":${song.id},"display":"Soda Stereo - Persiana Americana"}}""",
            """caracole-progress: {"stage":"song","state":"done","detail":"in the library"}""",
            """caracole-progress: {"stage":"version","state":"running","detail":""}""",
            """caracole-progress: {"stage":"version","state":"skipped","detail":"Tab 101 is the sheet of Soda Stereo - """ +
                """Persiana Americana already."}""",
        ), c.lines)
        assertEquals("Tab 102 is kept beside the sheet of Soda Stereo - Persiana Americana already; it stays kept now.",
                     VersionsCommands.keep(c, library, song, 102))
        assertEquals("[\"102\"]", db.kvGet("sheet_versions:yours:${song.id}"))
    }

    @Test fun whatAskingCameToIsSaidAsVersionsCmdSaysIt() = withSong { db, library, song ->
        val until = Instant.parse("2026-11-04T14:00:00Z")
        val words = mapOf<Asked<Nothing>, String>(
            Asked.Cooling(until) to "Ultimate Guitar is cooling down after a block, until 2026-11-04 14:00 UTC; nothing kept.",
            Asked.Cooling(null) to "Ultimate Guitar is cooling down after a block, until later; nothing kept.",
            Asked.Blocked(ProviderBlocked("ug", "https://x", 403), ProviderState("ug", cooldownUntil = until)) to
                "Ultimate Guitar blocked caracole (ug: 403: https://x): no more requests to it until 2026-11-04 14:00 " +
                "UTC; nothing kept.",
            Asked.Failed(ProviderError("ug", "https://x", 500)) to
                "Ultimate Guitar failed (ug: 500: https://x); nothing kept. Ask again later.",
            Asked.Spent(hour = true, keptForSheets = false) to
                "The lookup requests to Ultimate Guitar are spent (6 a lookup, 60 an hour); nothing kept. Ask again later.",
        )
        for ((asked, said) in words) {
            assertEquals(said, VersionsCommands.keep(Said(db, Answers(asked)), library, song, 103))
            assertEquals(said, VersionsCommands.keepMore(Said(db, Answers(asked)), library, song))
        }
        assertEquals(null, db.kvGet("provider:ug"))  // nothing sent: no good run recorded
    }

    @Test fun aCooldownAsksNothingAndNothingLeftToKeepSaysSo() = withSong { db, library, song ->
        Health.recordBlock(db, "ug", NOW.minusSeconds(3600), "ug: 403")
        val cooling = VersionsCommands.keep(Said(db, UgFetchReplay.TurnAsking(db, NoClient, NOW)), library, song, 103)
        assertTrue(cooling, cooling.startsWith("Ultimate Guitar is cooling down after a block, until 2026-11-04 "))
        db.kvSet("sheet_versions:unkeepable:${song.id}", "[\"103\"]")
        assertEquals("Nothing more to keep of Soda Stereo - Persiana Americana: every Ultimate Guitar version caracole " +
                         "may keep is kept already, or can't be.",
                     VersionsCommands.keepMore(Said(db, FakeAsking(emptyMap())), library, song))
    }

    @Test fun aKeptVersionsPathIsInTheSongsFolder() = withSong { _, library, song ->
        assertEquals(File(File(File(library.libraryDir, "Soda Stereo"), "Persiana Americana"), "version-103.txt"),
                     File(library.folderOf(song), "version-103.txt"))
    }

    /** A client the cooldown never lets the command use. */
    private object NoClient : Client {
        override val provider = "ug"
        override val requestsMade = 0
        override var policy = ProviderPolicy(budget = 0, delay = 0.0 to 0.0)
        override fun get(url: String, params: List<Pair<String, String>>?, cache: Boolean, conditional: Boolean,
                         accept: Set<Int>, maxAge: Duration?): Response = throw AssertionError("asked for $url")
        override fun cached(url: String, accept: Set<Int>): Response? = null
        override fun hasCached(url: String, accept: Set<Int>): Boolean = false
    }

    companion object {
        val NOW: Instant = Instant.parse("2026-11-03T12:00:00Z")
        const val STAMP = "2026-11-03T12:00:00Z"
    }
}
