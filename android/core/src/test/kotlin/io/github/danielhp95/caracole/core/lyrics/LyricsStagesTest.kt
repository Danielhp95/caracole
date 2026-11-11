package io.github.danielhp95.caracole.core.lyrics

import io.github.danielhp95.caracole.core.config.PhoneConfig
import io.github.danielhp95.caracole.core.http.Client
import io.github.danielhp95.caracole.core.http.HttpAnswer
import io.github.danielhp95.caracole.core.index.Stamps
import io.github.danielhp95.caracole.core.library.OverrideUrls
import io.github.danielhp95.caracole.core.library.Overrides
import io.github.danielhp95.caracole.core.library.SongRow
import io.github.danielhp95.caracole.core.lookup.StageContext
import io.github.danielhp95.caracole.core.lookup.StageEnd
import io.github.danielhp95.caracole.core.lookup.sites.AzLyricsStage
import io.github.danielhp95.caracole.core.lookup.sites.LrclibStage
import io.github.danielhp95.caracole.core.lookup.sites.MegalobizStage
import io.github.danielhp95.caracole.core.testing.FakeAsking
import io.github.danielhp95.caracole.core.testing.FakeTransport
import io.github.danielhp95.caracole.core.testing.FakeTransport.Companion.answer
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import kotlin.test.assertEquals

/**
 * get.py's lyrics stages on the phone, each site's ([LrclibStage], [MegalobizStage], [AzLyricsStage]) through a test's
 * asking (FakeAsking: each error its Asked, as lane lookup's InteractiveAsk ends it): what the site's answer says, in
 * get.py's words, and the envelope's words for the rest. The frame puts the three together (`_then`, lane lookup's).
 */
class LyricsStagesTest {
    @get:Rule val tmp = TemporaryFolder()

    private val soda = "GET https://lrclib.net/api/get?artist_name=Soda+Stereo&track_name=De+M%C3%BAsica+Ligera&duration=213"
    private val sodaSearch = "GET https://lrclib.net/api/search?track_name=De+M%C3%BAsica+Ligera&artist_name=Soda+Stereo"
    private val eaglesSearch =
        "GET https://api.megalobiz.com/api/public/v1/search?title=Hotel+California&artist=Eagles&duration=391&limit=10"
    private val eaglesLrc = "GET https://api.megalobiz.com/api/public/v1/lrc/24519"
    private val pomme = "GET https://www.azlyrics.com/p/pomme.html"
    private val mononoke = "GET https://www.azlyrics.com/lyrics/pomme/mononoke.html"

    private fun fixture(path: String) = answer(200, LyricsWorld.fixture(path))

    private fun stage(w: LyricsWorld, run: (StageContext) -> StageEnd, song: SongRow, provider: String,
                      answers: Map<String, HttpAnswer>, config: PhoneConfig = PhoneConfig.DEFAULTS,
                      overrides: Overrides = Overrides(), budget: Long = 6): Pair<StageEnd, FakeTransport> {
        val (client, site) = w.client(provider, answers, budget)
        val asking = FakeAsking(mapOf<String, Client>(provider to client))
        val end = w.db { db -> run(StageContext(db, song, overrides, config, w.library, asking, w.now)) }
        return end to site
    }

    @Test fun lrclibsAnswerIsFoundNoneOrAnInstrumental() {
        LyricsWorld(tmp.newFolder()).use { w ->
            val song = w.song("Soda Stereo", "De Música Ligera", 213_000L)
            assertEquals(StageEnd("done", "found"),
                         stage(w, LrclibStage::run, song, "lrclib", mapOf(soda to fixture("lrclib/get_hit.json"))).first)
            val again = w.db { io.github.danielhp95.caracole.core.library.Songs.byId(it, song.id)!! }
            val (end, site) = stage(w, LrclibStage::run, again, "lrclib", emptyMap())
            assertEquals(StageEnd("done", "already there"), end)
            assertEquals(emptyList(), site.said)
        }
        LyricsWorld(tmp.newFolder()).use { w ->
            val song = w.song("Soda Stereo", "De Música Ligera", 213_000L)
            val none = mapOf(soda to answer(404, "{}"), sodaSearch to answer(200, "[]"))
            assertEquals(StageEnd("done", "LRCLIB has none"), stage(w, LrclibStage::run, song, "lrclib", none).first)
        }
        LyricsWorld(tmp.newFolder()).use { w ->
            val song = w.song("Conjunto de Prueba", "Interludio de Prueba", 184_000L)
            val get = "GET https://lrclib.net/api/get?artist_name=Conjunto+de+Prueba&track_name=Interludio+de+Prueba&duration=184"
            assertEquals(StageEnd("done", "an instrumental"),
                         stage(w, LrclibStage::run, song, "lrclib", mapOf(get to fixture("lrclib/get_instrumental.json"))).first)
        }
    }

    @Test fun anErrorOrASpentBudgetIsSaidAsTheEnvelopeSaysItNeverAMiss() {
        LyricsWorld(tmp.newFolder()).use { w ->
            val song = w.song("Soda Stereo", "De Música Ligera", 213_000L)
            val (failed, _) = stage(w, LrclibStage::run, song, "lrclib", mapOf(soda to answer(500, "oops")))
            assertEquals(StageEnd("failed", "LRCLIB failed (lrclib: 500: ${soda.removePrefix("GET ")}: HTTP 500); the nightly " +
                                      "run tries again"), failed)
            assertEquals("pending", w.db { io.github.danielhp95.caracole.core.library.Songs.byId(it, song.id)!! }.lyricsStatus)
            // Remembered for Megalobiz and AZLyrics before the stage says it failed: they ask about it after LRCLIB.
            assertEquals(Stamps.of(w.now), w.db { it.kvGet("${Lrclib.FAILED}${song.id}") })
            val (spent, _) = stage(w, LrclibStage::run, song, "lrclib", mapOf(soda to answer(404, "{}")), budget = 1)
            assertEquals(StageEnd("skipped", "this fetch's 6 asks of LRCLIB are spent; tonight's run does the rest"), spent)
        }
    }

    @Test fun megalobizIsAskedOnlyAboutASongLrclibLeftWithoutTimedLyrics() {
        LyricsWorld(tmp.newFolder()).use { w ->
            val pending = w.song("Eagles", "Hotel California", 391_000L)
            assertEquals(StageEnd("nothing", ""), stage(w, MegalobizStage::run, pending, "megalobiz", emptyMap()).first)
            val missed = w.song("Eagles", "Hotel California", 391_000L, "lyrics_status" to "missing")
            val off = PhoneConfig.DEFAULTS.copy(providers = PhoneConfig.DEFAULTS.providers +
                ("megalobiz" to PhoneConfig.DEFAULTS.provider("megalobiz").copy(enabled = false)))
            assertEquals(StageEnd("nothing", ""), stage(w, MegalobizStage::run, missed, "megalobiz", emptyMap(), off).first)
            val hit = mapOf(eaglesSearch to fixture("megalobiz/search_hotel_california.json"),
                            eaglesLrc to fixture("megalobiz/lrc_24519.json"))
            assertEquals(StageEnd("done", "timed lyrics from Megalobiz"), stage(w, MegalobizStage::run, missed, "megalobiz", hit).first)
            val stored = w.db { songLyrics(it, missed.id) }!!
            assertEquals("megalobiz" to "https://megalobiz.com/lrc/24519/hotel-california", stored.provider to stored.url)
        }
        LyricsWorld(tmp.newFolder()).use { w ->
            val missed = w.song("Eagles", "Hotel California", 391_000L, "lyrics_status" to "missing")
            assertEquals(StageEnd("done", "Megalobiz has no timed ones"), stage(w, MegalobizStage::run, missed, "megalobiz",
                mapOf(eaglesSearch to fixture("megalobiz/search_empty.json"))).first)
        }
    }

    @Test fun azlyricsGivesPlainLyricsOrNoneAndItsBlockIsSaidSo() {
        LyricsWorld(tmp.newFolder()).use { w ->
            val song = w.song("Pomme", "mononoke", null, "lyrics_status" to "missing")
            val (blocked, _) = stage(w, AzLyricsStage::run, song, "azlyrics", mapOf(pomme to fixture("azlyrics/block.html")))
            assertEquals(StageEnd("skipped", "AZLyrics turned us back (azlyrics: 200: https://www.azlyrics.com/p/pomme.html: " +
                                      "challenge page). No more asks until later. Nothing marked not on the sites."), blocked)
            val hit = mapOf(pomme to fixture("azlyrics/artist_pomme.html"), mononoke to fixture("azlyrics/lyrics_mononoke.html"))
            assertEquals(StageEnd("done", "lyrics from AZLyrics"), stage(w, AzLyricsStage::run, song, "azlyrics", hit).first)
            val again = w.db { io.github.danielhp95.caracole.core.library.Songs.byId(it, song.id)!! }
            assertEquals(StageEnd("nothing", ""), stage(w, AzLyricsStage::run, again, "azlyrics", emptyMap()).first)
        }
        LyricsWorld(tmp.newFolder()).use { w ->
            val song = w.song("Someone Else", "Mononoke")
            val picks = Overrides(azlyrics = mapOf(OverrideUrls.overrideKey(song.display) to mononoke.removePrefix("GET ")))
            assertEquals(StageEnd("nothing", ""), stage(w, AzLyricsStage::run, song, "azlyrics", emptyMap()).first)
            val (end, site) = stage(w, AzLyricsStage::run, song, "azlyrics",
                                    mapOf(mononoke to fixture("azlyrics/lyrics_mononoke.html")), overrides = picks)
            assertEquals(StageEnd("done", "lyrics from AZLyrics"), end)
            assertEquals(listOf(mononoke), site.said)
        }
        LyricsWorld(tmp.newFolder()).use { w ->
            val song = w.song("Pomme", "Grandiose", null, "lyrics_status" to "missing")
            assertEquals(StageEnd("done", "AZLyrics has none"),
                         stage(w, AzLyricsStage::run, song, "azlyrics", mapOf(pomme to fixture("azlyrics/artist_pomme.html"))).first)
        }
    }
}
