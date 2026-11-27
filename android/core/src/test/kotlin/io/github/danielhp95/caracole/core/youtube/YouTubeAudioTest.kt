package io.github.danielhp95.caracole.core.youtube

import io.github.danielhp95.caracole.core.db.Database
import io.github.danielhp95.caracole.core.index.Stamps
import io.github.danielhp95.caracole.core.library.AudioStore
import io.github.danielhp95.caracole.core.library.LibraryStore
import io.github.danielhp95.caracole.core.library.Songs
import io.github.danielhp95.caracole.core.library.Versions
import io.github.danielhp95.caracole.core.testing.TestDb
import org.junit.After
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import java.io.File
import java.time.Duration
import java.time.Instant
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertNull
import kotlin.test.assertTrue

/** The audio the phone takes from YouTube: kept [YouTubeAudio.KEPT_FOR] after its download, then swept, and deleted
 * with its song at a removal; a stopped job's own folder and a file nobody names swept; nothing outside the folder. */
class YouTubeAudioTest {
    @get:Rule val tmp = TemporaryFolder()
    private val opened = mutableListOf<Database>()

    @After fun close() = opened.forEach { it.close() }

    private val now = Instant.parse("2026-11-27T12:00:00Z")

    private class World(val database: Database, val store: LibraryStore, val folder: File)

    private fun world(): World {
        val dir = tmp.newFolder()
        val state = File(dir, "state")
        val folder = YouTubeAudio.folder(File(state, "cache")).apply { mkdirs() }
        return World(TestDb.fresh(dir).also { opened += it },
                     LibraryStore(File(dir, "library"), File(state, AudioStore.FOLDER), folder), folder)
    }

    /** A song whose audio is a video's, downloaded [ago] before [now]. */
    private fun downloaded(w: World, title: String, ago: Duration): File = w.database.writeBlocking { db ->
        val song = w.store.add(db, "Calla Lake", title, now = Stamps.now())
        val file = File(w.folder, YouTubeAudio.name(song.id, "RiverRoad0${song.id}", ".m4a")).apply { writeText("audio") }
        Versions.updateSong(db, song.id, mapOf("audio_path" to file.path, "audio_mtime" to 1.0))
        Records.save(db, song.id, Record(video = Video("RiverRoad0${song.id}"), source = "pasted", audio = file.path,
                                         downloadedAt = Stamps.of(now.minus(ago))))
        file
    }

    @Test fun theSweepLetsADownloadGoAtThreeDaysAndKeepsAYoungerOne() {
        val w = world()
        val old = downloaded(w, "River Road", Duration.ofDays(3))
        val young = downloaded(w, "Lanterns", Duration.ofDays(2))
        val part = File(w.folder, YouTubeAudio.partPrefix(1) + "abc").apply { mkdirs(); File(this, "audio.m4a").writeText("x") }
        val stray = File(w.folder, "9-Nobody00000.m4a").apply { writeText("x") }
        val ytdlpCache = File(w.folder, "yt-dlp").apply { mkdirs() }
        val gone = w.database.writeBlocking { db -> YouTubeAudio.sweep(db, w.folder, now, Stamps.of(now)) }
        assertEquals(2, gone)
        assertFalse(old.exists())
        assertTrue(young.exists())
        assertFalse(part.exists())
        assertFalse(stray.exists())
        assertTrue(ytdlpCache.isDirectory)  // a folder of yt-dlp's own is never the sweep's
        w.database.read { db ->
            val first = Songs.byKey(db, "calla-lake/river-road")!!
            assertNull(first.audioPath)
            assertNull(first.audioMtime)
            assertNull(Records.load(db, first.id).audio)
            assertEquals("RiverRoad01", Records.load(db, first.id).video?.id)
            assertEquals(young.path, Songs.byKey(db, "calla-lake/lanterns")!!.audioPath)
        }
    }

    @Test fun aRemovalDeletesTheSongsYouTubeAudioAndNothingOutsideItsFolder() {
        val w = world()
        val file = downloaded(w, "River Road", Duration.ofHours(1))
        val outside = File(tmp.newFolder(), "elsewhere.m4a").apply { writeText("keep") }
        w.database.writeBlocking { db ->
            val other = w.store.add(db, "Calla Lake", "Lanterns", now = Stamps.now())
            Records.save(db, other.id, Record(audio = outside.path))
        }
        w.database.writeBlocking { db -> w.store.remove(db, "calla-lake/river-road", Stamps.now()) }
        assertFalse(file.exists())
        w.database.writeBlocking { db -> w.store.remove(db, "calla-lake/lanterns", Stamps.now()) }
        assertTrue(outside.exists())
    }
}
