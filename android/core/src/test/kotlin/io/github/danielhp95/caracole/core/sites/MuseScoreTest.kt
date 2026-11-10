package io.github.danielhp95.caracole.core.sites

import io.github.danielhp95.caracole.core.library.LibraryStore
import io.github.danielhp95.caracole.core.testing.Misses
import io.github.danielhp95.caracole.core.testing.TestDb
import io.github.danielhp95.caracole.core.testing.replays.TabFilesReplay
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import java.io.File
import kotlin.test.assertEquals
import kotlin.test.assertNull

/** musescore.py on the phone: every record of vectors/sites/musescore.jsonl answered as Python answered it, and its
 * rules by hand. MuseScore's links come from the index alone: nothing here has a client. */
class MuseScoreTest {
    @get:Rule val tmp = TemporaryFolder()

    @Test fun everyRecordIsMusescorePys() {
        val misses = Misses("tab-files: musescore.py")
        TabFilesReplay.museScore(misses)
        misses.assertNone()
    }

    @Test fun aSongPageIsItsIdItsPathAndItsTitlesKey() {
        assertEquals(MuseScorePage(123, "song/yesterday-123", "yesterday"),
                     MuseScorePages.parseSongUrl("https://musescore.com/song/yesterday-123"))
        assertEquals("https://musescore.com/song/a-b-c-12", MuseScorePages.parseSongUrl("https://musescore.com/song/a-b-c-12")?.url)
        assertNull(MuseScorePages.parseSongUrl("https://musescore.com/song/Yesterday-1"))
        assertNull(MuseScorePages.parseSongUrl("https://musescore.com/song/___-5"))
        assertEquals("18", MuseScorePages.sitemapName("https://musescore.com/sitemaps/song-index/sitemap_songs18.xml"))
    }

    @Test fun aSongsPagesAreTheIndexsByTitleOldestFirstThreeAtMost() {
        val dir = tmp.newFolder()
        TestDb.fresh(dir).use { database ->
            database.writeBlocking { db ->
                for (id in listOf(900L, 7, 1_000_000_000, 5, 44)) {
                    val slug = if (id == 44L) "here_comes_the_sun" else "yesterday"
                    db.execute("INSERT INTO musescore_index (page_id, path, title_key, sitemap) VALUES (?, ?, ?, '1')",
                               id, "song/$slug-$id", if (id == 44L) "here-comes-the-sun" else "yesterday")
                }
                val lib = LibraryStore(File(dir, "library"))
                val song = lib.add(db, "The Beatles", "Yesterday - Remastered 2009", now = "2026-10-01T00:00:00Z")
                assertEquals(listOf(5L, 7, 900), MuseScorePages.songPages(db, song).map { it.pageId })
                assertEquals(listOf(5L, 7, 900, 1_000_000_000), MuseScorePages.songPages(db, song, limit = 10).map { it.pageId })
                val none = lib.add(db, "Nobody", "!!!", now = "2026-10-01T00:00:00Z")
                assertEquals(emptyList(), MuseScorePages.songPages(db, none))
            }
        }
    }
}
