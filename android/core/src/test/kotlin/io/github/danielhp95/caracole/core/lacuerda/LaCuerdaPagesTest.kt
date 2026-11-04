package io.github.danielhp95.caracole.core.lacuerda

import io.github.danielhp95.caracole.core.http.LaCuerdaParseError
import io.github.danielhp95.caracole.core.index.Reads
import io.github.danielhp95.caracole.core.testing.Misses
import io.github.danielhp95.caracole.core.testing.TestDb
import io.github.danielhp95.caracole.core.testing.replays.LaCuerdaReplay
import org.junit.Assume.assumeTrue
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith
import kotlin.test.assertFalse
import kotlin.test.assertNull
import kotlin.test.assertTrue

/** lacuerda.py's pages and lacuerda_index.py's store writers against Python's answers (vectors/sites/
 * lacuerda_pages.jsonl and lacuerda_store.jsonl), and the cases a corpus line can't hold. */
class LaCuerdaPagesTest {
    @get:Rule val folder = TemporaryFolder()

    @Test fun everyPageAndBatchAnswersAsPythonDid() = Misses("sites/lacuerda_pages.jsonl").also { LaCuerdaReplay.pages(it) }.assertNone()

    @Test fun everyStoreWritesThePythonRows() = Misses("sites/lacuerda_store.jsonl").also { LaCuerdaReplay.store(it) }.assertNone()

    @Test fun anLcdCodesRankingIsReadAsPythonsIntOfBase36ReadsEachCodePoint() {
        assertEquals("RHT" to listOf(3, 1, 2), LaCuerdaPages.parseLcd(" rht-312 "))
        assertEquals("RT" to listOf(2, 1), LaCuerdaPages.parseLcd("RT-٢١"))  // a decimal digit of any script
        assertEquals("R" to listOf(1), LaCuerdaPages.parseLcd("R-𝟏"))  // one code point beyond the BMP
        assertEquals("RT" to listOf(1, 2), LaCuerdaPages.parseLcd("RT-1²"))  // a digit, but no decimal one
        assertEquals("SSR" to listOf(1, 2, 3), LaCuerdaPages.parseLcd("ßR-12"))  // str.upper makes three letters
        assertEquals("RTRTRTRTRTR" to listOf(10, 1, 11, 2, 3, 4, 5, 6, 7, 8, 9), LaCuerdaPages.parseLcd("RTRTRTRTRTR-A1B23456789"))
        assertEquals("" to emptyList(), LaCuerdaPages.parseLcd(""))
    }

    @Test fun theBestAcordesVersionReadsTheLetterOfEachVersionNumber() {
        assertEquals(2, LaCuerdaPages.bestAcordesVersion(LaCuerdaSong("s", "t", "BR", listOf(2, 1))))
        assertEquals(2, LaCuerdaPages.bestAcordesVersion(LaCuerdaSong("s", "t", "TR", listOf(5, 2, 1))))
        assertNull(LaCuerdaPages.bestAcordesVersion(LaCuerdaSong("s", "t", "TT", listOf(2, 1))))
        assertNull(LaCuerdaPages.bestAcordesVersion(LaCuerdaSong("s", "t", "R", listOf(0))))
    }

    @Test fun aTitleMatchesTheSongWithAcordesOnATieThenTheFirst() {
        val songs = listOf(LaCuerdaSong("la_flaca_tab", "La Flaca", "T", listOf(1)),
                           LaCuerdaSong("la_flaca", "La Flaca", "TR", listOf(2, 1)),
                           LaCuerdaSong("la_flaca_2", "La flaca", "R", listOf(1)))
        assertEquals("la_flaca", LaCuerdaPages.matchTitle(songs, "La Flaca")?.slug)
        assertNull(LaCuerdaPages.matchTitle(songs, "!!!"))
        assertNull(LaCuerdaPages.matchTitle(emptyList(), "La Flaca"))
    }

    @Test fun theSoftNotFoundIsLaCuerdasShortBodyAlone() {
        assertTrue(LaCuerdaPages.isMissingArtistPage("aqui llega:../tabs/z/x/index.html"))
        assertTrue(LaCuerdaPages.isMissingArtistPage(" \n\tAQUÍ LLEGA:x"))
        assertTrue(LaCuerdaPages.isMissingArtistPage("aqui llega:" + "ñ".repeat(506)))  // 1023 bytes of UTF-8
        assertFalse(LaCuerdaPages.isMissingArtistPage("aqui llega:" + "ñ".repeat(507)))
        assertFalse(LaCuerdaPages.isMissingArtistPage(""))
    }

    @Test fun theSearchsWordsAndAddress() {
        assertEquals(listOf("fito", "fitipaldis", "boca", "vive"),
                     LaCuerdaPages.searchWords("Fito & Fitipaldis: ¿Por la boca vive el pez?"))
        assertEquals("${LaCuerdaPages.BASE_URL}/busca.php?exp=flaca&canc=0&ord=0&ini=0",
                     LaCuerdaPages.searchUrl("la flaca", songsOnly = false))
        val e = assertFailsWith<IllegalArgumentException> { LaCuerdaPages.searchUrl("el sol") }
        assertEquals("LaCuerda's search reads no word of 'el sol': none has 4 letters", e.message)
    }

    @Test fun spanishByItsWordsAndItsMarks() {
        assertTrue(LaCuerdaPages.looksSpanish("Señorita"))
        assertTrue(LaCuerdaPages.looksSpanish("Pingüino"))
        assertFalse(LaCuerdaPages.looksSpanish("Für Elise"))
        assertFalse(LaCuerdaPages.looksSpanish("Señorita", "I walk the long road when the city is asleep"))
        assertEquals(Triple(1, 1, 2), LaCuerdaPages.languageCounts("De THE"))
    }

    @Test fun aChordsPaddingMovesOutsideAndItsLinesStayAsWritten() {
        assumeTrue("waiting on html-tree", LaCuerdaReplay.htmlReady)
        val page = "<html><body><div id=t_body><PRE><A> Am </A>|<A></A>|\nla&nbsp;luz<br>del bar\n</PRE></div></body></html>"
        assertEquals(" [ch]Am[/ch] ||\nla luz\ndel bar\n", LaCuerdaPages.parseVersionPage(page))
        assertFailsWith<LaCuerdaParseError> { LaCuerdaPages.parseVersionPage("<div id=t_body><pre> \n</pre></div>") }
    }

    @Test fun aSearchPageCutShortIsAParseErrorNeverNoResults() {
        assumeTrue("waiting on html-tree", LaCuerdaReplay.htmlReady)
        val e = assertFailsWith<LaCuerdaParseError> {
            LaCuerdaPages.parseSearch("<div class=s_res>Buscando <b>\"x\"</b>. 1 resultados.</div><ul id=i_main class=s_blist>")
        }
        assertEquals("lacuerda: the list of artists isn't closed: the page was cut short", e.message)
    }

    @Test fun aStoreNotesThePageItWroteAtItsTime() {
        TestDb.fresh(folder.root).use { database ->
            database.writeBlocking { db ->
                LaCuerda.storeSongs(db, "estopa", "Estopa", listOf(LaCuerdaSong("como_camaron", "Como Camarón", "RT", listOf(1, 2))),
                                    at = "2026-11-03T12:00:00Z")
                LaCuerda.storeSearch(db, LaCuerdaSearchAnswer(), "2026-11-03T12:01:00Z")
                assertEquals(mapOf("lacuerda" to listOf("estopa/")), Reads.since(db, "computer"))
                LaCuerda.storeSearch(db, LaCuerdaSearchAnswer(artists = listOf(LaCuerdaArtist("gaviota", "Gaviota", 3)),
                                                              stated = 1), "2026-11-03T12:02:00Z")
                assertEquals(mapOf("lacuerda" to listOf("busca.php", "estopa/")), Reads.since(db, "computer"))
                assertEquals("2026-11-03T12:02:00Z", db.kvGet("${Reads.READ}lacuerda:busca.php"))
                val row = db.one("SELECT artist, artist_key, title_key, versions, CAST(acordes AS TEXT), page FROM lacuerda_index " +
                                     "WHERE path = 'estopa/como_camaron'") { r -> (0..5).map { r.text(it) } }
                assertEquals(listOf("Estopa", "estopa", "como-camaron", "RT", "1", "estopa/"), row)
            }
        }
    }

    @Test fun anUnnamedArtistIsTheirSlugsWordsCapitalized() {
        TestDb.fresh(folder.root).use { database ->
            database.writeBlocking { db ->
                LaCuerda.storeSongs(db, "los_del_rio_", null, listOf(LaCuerdaSong("x", "X", "R", listOf(1))), at = "2026-11-03T12:00:00Z")
                LaCuerda.storeSongs(db, "__", "", listOf(LaCuerdaSong("y", "Y", "R", listOf(1))), at = "2026-11-03T12:00:00Z")
                assertEquals("Los Del Rio", db.one("SELECT artist FROM lacuerda_index WHERE path = 'los_del_rio_/x'") { it.text(0) })
                assertEquals("__", db.one("SELECT artist FROM lacuerda_index WHERE path = '__/y'") { it.text(0) })
            }
        }
    }
}
