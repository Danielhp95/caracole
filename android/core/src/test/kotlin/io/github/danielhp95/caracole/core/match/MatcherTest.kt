package io.github.danielhp95.caracole.core.match

import io.github.danielhp95.caracole.core.config.MatchPolicy
import io.github.danielhp95.caracole.core.config.PhoneConfig
import io.github.danielhp95.caracole.core.db.Db
import io.github.danielhp95.caracole.core.health.Alerts
import io.github.danielhp95.caracole.core.http.Draws
import io.github.danielhp95.caracole.core.keys.Normalize
import io.github.danielhp95.caracole.core.library.LibraryStore
import io.github.danielhp95.caracole.core.library.Overrides
import io.github.danielhp95.caracole.core.library.SongRow
import io.github.danielhp95.caracole.core.library.Songs
import io.github.danielhp95.caracole.core.lookup.Clients
import io.github.danielhp95.caracole.core.lookup.InteractiveAsk
import io.github.danielhp95.caracole.core.lookup.Lookup
import io.github.danielhp95.caracole.core.lookup.LookupRequest
import io.github.danielhp95.caracole.core.lookup.Pacing
import io.github.danielhp95.caracole.core.lookup.Progress
import io.github.danielhp95.caracole.core.lookup.SiteStage
import io.github.danielhp95.caracole.core.lookup.SiteStages
import io.github.danielhp95.caracole.core.lookup.SongPages
import io.github.danielhp95.caracole.core.lookup.SongbookPages
import io.github.danielhp95.caracole.core.lookup.StageContext
import io.github.danielhp95.caracole.core.lookup.StageEnd
import io.github.danielhp95.caracole.core.lookup.sites.MatchStage
import io.github.danielhp95.caracole.core.testing.FakeAsking
import io.github.danielhp95.caracole.core.testing.Misses
import io.github.danielhp95.caracole.core.testing.RefusingTransport
import io.github.danielhp95.caracole.core.testing.TestDb
import io.github.danielhp95.caracole.core.testing.replays.MatchReplay
import io.github.danielhp95.caracole.core.ug.ArtistTabs
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import java.time.Instant
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertNull
import kotlin.test.assertTrue

/**
 * core.match as match.py answers it (vectors/match/: test_match.py's cases harvested and a seeded library, each
 * compared field for field, the rows match_all writes byte for byte), and the rules the phone keeps besides: what
 * loads when, an incomplete index, the lookup's stage.
 */
class MatcherTest {
    @get:Rule val tmp = TemporaryFolder()

    private val policy = MatchPolicy()
    private val now = "2026-11-04T09:30:00Z"

    private fun replayed(name: String, part: (Misses, Db) -> Unit) {
        val misses = Misses("match: $name")
        MatchReplay.withDatabase { db -> part(misses, db) }
        misses.assertNone()
    }

    @Test fun everyRungOfTheLadderIsMatchPys() = replayed("ladder", MatchReplay::ladder)

    @Test fun theIndexViewAnswersAsPythonsBeforeAndAfterItLoads() = replayed("view", MatchReplay::views)

    @Test fun matchAllWritesWhatPythonWritesOverTestMatchsDatabasesAndTheSeededLibrary() =
        replayed("match_all", MatchReplay::matchAll)

    @Test fun theLookupsStageSaysGetPysWords() = replayed("stage", MatchReplay::stage)

    // --- the phone's rules besides --------------------------------------------------------------------------

    private fun db(block: (Db) -> Unit) = MatchReplay.withDatabase(block)

    private fun index(db: Db, vararg rows: Triple<String, String, String>, built: Boolean = true) {
        rows.forEachIndexed { i, (artist, song, type) ->
            db.execute("INSERT INTO ug_index (tab_id, artist_key, song_key, type, sitemap, first_seen, path) " +
                           "VALUES (?, ?, ?, ?, '1', 'x', ?)", i + 1L, artist, song, type, "$artist/$song-$type-${i + 1}")
        }
        if (built) db.kvSet(Matcher.BUILT_KEY, "2026-10-18T03:30:00Z")
    }

    private fun song(db: Db, artist: String, title: String): SongRow =
        LibraryStore(tmp.root).add(db, artist, title, now = "2026-11-03T12:00:00Z")

    @Test fun anExactMatchLoadsNeitherEveryArtistNorEveryTitleNorTheCatchAlls() = db { db ->
        index(db, Triple("acdc", "highway-to-hell", "chords"), Triple("abba", "sos", "chords"))
        val view = IndexView(db)
        val r = Matcher.matchSong(song(db, "AC/DC", "Highway to Hell"), view, Overrides(), policy)
        assertEquals("accept" to "exact", r.decision to r.step)
        assertEquals(emptySet(), view.loaded)
    }

    @Test fun theTitlesAndTheCatchAllsLoadOnlyWhenTheLadderReachesThem() = db { db ->
        index(db, Triple("leonard-cohen", "hallelujah", "chords"), Triple("misc-musicals", "epic-the-musical-x", "chords"))
        val view = IndexView(db)
        val r = Matcher.matchSong(song(db, "Someone Else", "Hallelujah"), view, Overrides(), policy)
        assertEquals("review" to "title_only", r.decision to r.step)
        assertEquals(setOf("artists", "titles", "catch_all"), view.loaded)
        // A fuzzy accept under the song's own artist stops at step 2: nothing loads whole.
        val fuzzy = IndexView(db)
        assertEquals("accept", Matcher.matchSong(song(db, "Leonard Cohen", "Halleluja"), fuzzy, Overrides(), policy).decision)
        assertEquals(emptySet(), fuzzy.loaded)
    }

    @Test fun anIncompleteIndexNeverRecordsAMissAndKeepsWhatTheLadderFound() = db { db ->
        index(db, Triple("radiohead", "creep", "chords"), built = false)
        val creep = song(db, "Radiohead", "Creep")
        val missing = song(db, "Soda Stereo", "Signos")
        val changes = Matcher.matchAll(db, Overrides(), policy, Songs.list(db), now = now)
        assertEquals(mapOf(creep.id to "accept", missing.id to "not_found"), changes.associate { it.song.id to it.new.decision })
        assertEquals("accept", Songs.byId(db, creep.id)!!.matchDecision)
        assertNull(Songs.byId(db, missing.id)!!.matchDecision)
        assertEquals("partial", Matcher.indexState(db))
        // Emptied, it keeps the accept too.
        db.execute("DELETE FROM ug_index")
        val kept = Matcher.matchAll(db, Overrides(), policy, Songs.list(db), now = "2026-11-05T00:00:00Z")
        assertEquals("accept", kept.single { it.song.id == creep.id }.new.decision)
        assertEquals(now, Songs.byId(db, creep.id)!!.matchedAt)
    }

    @Test fun theCandidatesAreStoredAsPythonsJsonDumpsAndReadBack() = db { db ->
        index(db, Triple("oasis", "wonderwall", "chords"), Triple("oasis", "wonderwalls", "chords"))
        val s = song(db, "Oasis", "Wonderwal")
        Matcher.matchAll(db, Overrides(), policy, listOf(s), now = now)
        val stored = Songs.byId(db, s.id)!!
        assertEquals("[{\"artist_key\": \"oasis\", \"song_key\": \"wonderwall\", \"score\": 94.7, \"step\": \"fuzzy_title\"}, " +
                         "{\"artist_key\": \"oasis\", \"song_key\": \"wonderwalls\", \"score\": 90.0, \"step\": \"fuzzy_title\"}]",
                     stored.matchCandidates)
        assertTrue(stored.review && stored.ugDirty)
        assertEquals(listOf(MatchCandidate("oasis", "wonderwall", 94.7, "fuzzy_title"),
                            MatchCandidate("oasis", "wonderwalls", 90.0, "fuzzy_title")), Matcher.candidatesOf(stored))
        // A pin is one row that lists its tabs.
        Matcher.matchAll(db, Overrides(pin = mapOf(s.key to listOf(1L, 7L))), policy, listOf(stored), now = now)
        assertEquals("[{\"artist_key\": \"oasis\", \"song_key\": \"wonderwall\", \"score\": null, \"step\": \"pin\", " +
                         "\"tab_ids\": [1, 7]}]", Songs.byId(db, s.id)!!.matchCandidates)
    }

    @Test fun aStoredPinsTabIdsAreReadAsIntReadsThem() = db { db ->
        index(db, Triple("oasis", "wonderwall", "chords"))
        val s = song(db, "Oasis", "Wonderwall")
        db.execute("UPDATE songs SET match_decision = 'pinned', match_step = 'pin', match_artist_key = 'oasis', " +
                       "match_song_key = 'wonderwall', ug_dirty = 0, match_candidates = ? WHERE id = ?",
                   "[{\"artist_key\": \"oasis\", \"song_key\": \"wonderwall\", \"score\": null, \"step\": \"pin\", " +
                       "\"tab_ids\": [\"1\", \" 7_0\"]}]", s.id)
        Matcher.matchAll(db, Overrides(pin = mapOf(s.key to listOf(1L, 70L))), policy, listOf(Songs.byId(db, s.id)!!),
                         now = now)
        // The same pins (int(" 7_0") is 70): the row is written again, as Python writes it, and nothing is fetched.
        val stored = Songs.byId(db, s.id)!!
        assertEquals("[{\"artist_key\": \"oasis\", \"song_key\": \"wonderwall\", \"score\": null, \"step\": \"pin\", " +
                         "\"tab_ids\": [1, 70]}]", stored.matchCandidates)
        assertEquals(false, stored.ugDirty)
    }

    @Test fun aStageWithNoCacheMakesTheArtistTabsKeysCurrentAloneAndMatches() = db { db ->
        index(db, Triple("radiohead", "creep", "chords"))
        val s = song(db, "Radiohead", "Creep")
        assertNull(db.kvGet(ArtistTabs.KEYS_KEY))
        val ctx = StageContext(db, s, Overrides(), PhoneConfig.DEFAULTS, LibraryStore(tmp.root), FakeAsking(emptyMap()),
                               Instant.parse(now))
        assertEquals(StageEnd("done", "matched to radiohead/creep"), MatchStage.run(ctx))
        assertEquals(now, Songs.byId(db, s.id)!!.matchedAt)
        // backfill's first step, as Python's for a client that reads no cache; no cache read, so no kv record of one.
        assertEquals(Normalize.KEY_VERSION.toString(), db.kvGet(ArtistTabs.KEYS_KEY))
        assertNull(db.kvGet(ArtistTabs.BACKFILL_KEY))
    }

    @Test fun aLookupsMatchStageBackfillsFromItsCacheWhateverAskingTheFrameWrapsTheEnvelopeIn() {
        TestDb.fresh(tmp.newFolder()).use { database ->
            database.writeBlocking { db ->
                index(db, Triple("radiohead", "creep", "chords"))
                assertNull(db.kvGet(ArtistTabs.KEYS_KEY))
                val cache = tmp.newFolder("cache")
                val at = Instant.parse(now)
                val pacing = Pacing(sleep = {}, draws = Draws { a, _ -> a }, wallSeconds = { at.epochSecond.toDouble() },
                                    monotonic = { 0.0 }, clock = { at })
                // The lookup's clients, whose transport refuses every request: the stage sends none, nor makes a client.
                val clients = Clients(PhoneConfig.DEFAULTS, cache, { RefusingTransport }, pacing)
                val seen = ArrayList<StageContext>()
                val quiet = SiteStage { StageEnd("skipped", "nothing to do") }
                val stages = SiteStages(SiteStage { ctx -> seen += ctx; MatchStage.run(ctx) }, quiet, quiet, quiet,
                                        quiet, quiet, quiet, quiet, quiet, quiet, quiet)
                val progress = object : Progress {
                    override fun stage(name: String, state: String, detail: String) {}
                }
                val result = Lookup(PhoneConfig.DEFAULTS, database, LibraryStore(tmp.newFolder("library")), clients,
                                    SongPages.NONE, SongbookPages.NONE, Alerts.NONE,
                                    LookupRequest("Radiohead", "Creep"), progress, pacing, stages,
                                    readOverrides = { Overrides() }).run(db)
                assertEquals("done" to "matched to radiohead/creep", result.states["match"] to result.details["match"])
                // The frame asks through a wrapper of its envelope, never the envelope itself: the cache still comes.
                val ctx = seen.single()
                assertFalse(ctx.asking is InteractiveAsk)
                assertEquals(cache, ctx.cacheDir)
                // The backfill ran whole: its keys made current, then the cache read (nothing in it), recorded once.
                assertEquals(Normalize.KEY_VERSION.toString(), db.kvGet(ArtistTabs.KEYS_KEY))
                assertEquals("{\"pages\": 0, \"tabs\": 0}", db.kvGet(ArtistTabs.BACKFILL_KEY))
                assertEquals("accept", Songs.byId(db, result.songId!!)!!.matchDecision)
                assertEquals(0, db.one("SELECT COUNT(*) FROM events") { it.long(0)!!.toInt() })
            }
        }
    }
}
