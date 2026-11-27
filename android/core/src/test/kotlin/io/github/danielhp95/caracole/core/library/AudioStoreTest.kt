package io.github.danielhp95.caracole.core.library

import io.github.danielhp95.caracole.core.db.Db
import io.github.danielhp95.caracole.core.json.Canonical
import io.github.danielhp95.caracole.core.json.JsonText
import io.github.danielhp95.caracole.core.library.AudioStore.Audio
import io.github.danielhp95.caracole.core.library.AudioStore.AudioError
import io.github.danielhp95.caracole.core.library.internal.Removal
import io.github.danielhp95.caracole.core.testing.Misses
import io.github.danielhp95.caracole.core.testing.TestDb
import io.github.danielhp95.caracole.core.testing.replays.AudioStoreReplay
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import java.io.ByteArrayInputStream
import java.io.File
import java.io.IOException
import java.io.InputStream
import java.lang.management.ManagementFactory
import java.nio.file.Files
import java.nio.file.LinkOption
import java.nio.file.attribute.PosixFilePermissions
import java.security.MessageDigest
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith
import kotlin.test.assertFalse
import kotlin.test.assertNotNull
import kotlin.test.assertNull
import kotlin.test.assertTrue

/**
 * core.library.AudioStore against audio_store.py: the corpus's answers (AudioStoreReplay), and, case by case,
 * tests/test_audio_store.py's on the phone: a staged upload, its refusals, a keep and the states a keep cut off
 * leaves, tidy, a removal, and a stage of 100 MiB spooled through no buffer of its size.
 */
class AudioStoreTest {
    @get:Rule val tmp = TemporaryFolder()

    @Test
    fun theReplay() {
        val misses = Misses("library/audio_store")
        AudioStoreReplay.replay(misses)
        misses.assertNone()
        assertTrue(misses.checked >= 400, "${misses.checked} answers")
    }

    // --- the world --------------------------------------------------------------------------------------------------

    /** What the fake examiner says of each file: its length and tags, or what it throws. */
    private var length = 1.0
    private var tags: Map<String, List<String>> = emptyMap()
    private var throwing: Exception? = null
    private val examiner = AudioStore.Examiner { _, format ->
        throwing?.let { throw it }
        Audio(format, length, tags)
    }
    private var free = 1L shl 50
    private var clock = AudioStore.now()

    private inner class World(dir: File = tmp.newFolder()) {
        val state = File(dir, "state")
        val store = AudioStore(state, examiner, { free }, { clock })
        val database = TestDb.fresh(dir)
        val library = LibraryStore(File(dir, "library"), store.root)

        fun <T> db(block: (Db) -> T): T = database.writeBlocking(block)
        fun song(artist: String = "Radiohead", title: String = "Creep"): SongRow =
            db { library.add(it, artist, title, now = "2026-11-27T00:00:00Z") }
        fun row(song: SongRow): SongRow = db { Songs.byId(it, song.id)!! }
        fun names(): List<String> = store.root.list().orEmpty().filter { !it.endsWith(".kept") }.sorted()
        fun markers(): List<String> = store.root.list().orEmpty().filter { it.endsWith(".kept") }.sorted()
    }

    private fun bytes(head: String, size: Int = 200): ByteArray =
        head.toByteArray(Charsets.ISO_8859_1).copyOf(size)

    private val mp3 = bytes("ID3\u0004\u0000\u0000\u0000\u0000\u0000\u0000")
    private val wav = bytes("RIFF\u0000\u0000\u0000\u0000WAVEfmt ")
    private val flac = bytes("fLaC\u0000\u0000\u0000\u0022")

    private fun World.stage(data: ByteArray, name: String = "song.mp3", named: Set<String> = emptySet()) =
        store.stage(ByteArrayInputStream(data), name, named)

    private fun refused(status: Int, call: () -> Any?): AudioError {
        val e = assertFailsWith<AudioError> { call() }
        assertEquals(status, e.status, e.message)
        return e
    }

    private fun mode(file: File) = PosixFilePermissions.toString(Files.getPosixFilePermissions(file.toPath(), LinkOption.NOFOLLOW_LINKS))

    private fun sha256(data: ByteArray) = Canonical.sha256Hex(data)

    private fun Db.row(song: SongRow): SongRow = Songs.byId(this, song.id)!!

    // --- a staged upload --------------------------------------------------------------------------------------------

    @Test
    fun anUploadIsStagedPrivatelyAndOneUnconfirmedAtATime() {
        val w = World()
        tags = mapOf("artist" to listOf("  ", " Radiohead "), "title" to listOf("Creep"), "album" to emptyList())
        val first = w.stage(mp3, "../../Music/01 Creep.mp3")
        assertEquals("rwx------", mode(w.store.root))
        assertTrue(AudioStore.ID.matches(first.id))
        assertEquals(File(w.store.root, ".upload-${first.id}.mp3"), first.file)
        assertEquals("rw-------", mode(first.file))
        assertEquals("rw-------", mode(File(w.store.root, ".upload-${first.id}.json")))
        assertTrue(first.file.readBytes().contentEquals(mp3))
        assertEquals("01 Creep.mp3", first.name)
        assertEquals(Triple(mp3.size.toLong(), sha256(mp3), "MP3"), Triple(first.size, first.sha256, first.format))
        assertEquals(mapOf("artist" to "Radiohead", "title" to "Creep", "album" to null), first.tags) // music._first
        assertEquals(first, w.store.staged(first.id))
        tags = emptyMap()
        val odd = w.stage(wav, "C:\\Users\\me\\a\u0000b\u001f\n" + "x".repeat(300) + ".wav", setOf(first.id))
        assertEquals(("ab" + "x".repeat(300)).take(255), odd.name)
        assertEquals(mapOf("artist" to null, "title" to null, "album" to null), odd.tags)
        assertEquals(first, w.store.staged(first.id))
        // A new one lets go of every earlier one no job names.
        val third = w.stage(flac, "c.flac", setOf(odd.id))
        refused(404) { w.store.staged(first.id) }
        assertEquals(odd, w.store.staged(odd.id))
        assertEquals(third, w.store.staged(third.id))
        assertEquals(listOf(odd.file.name, ".upload-${odd.id}.json", third.file.name, ".upload-${third.id}.json").sorted(),
                     w.names())
    }

    @Test
    fun namedIsAskedUnderTheStoresLockAsTheJobsAreThen() {
        val w = World()
        val first = w.stage(mp3)
        var asked = 0
        w.store.stage(ByteArrayInputStream(wav), "b.wav") {
            asked++
            assertTrue(w.store.held { true }) // re-entrant: the caller's own lock
            setOf(first.id)
        }
        assertEquals(1, asked)
        assertEquals(first, w.store.staged(first.id))
    }

    @Test
    fun theRefusalsAreAudioStoresAndLeaveNothing() {
        val w = World()
        val never = object : InputStream() {
            override fun read(): Int = throw AssertionError("read before the name was checked")
        }
        assertEquals(AudioStore.WORDS["no_name"], refused(400) { w.store.stage(never, "\u0000\u001f/", emptySet()) }.message)
        assertEquals(AudioStore.WORDS["empty"], refused(400) { w.stage(ByteArray(0)) }.message)
        assertEquals("Not an audio file caracole reads (MP3, M4A, FLAC, WAV, Ogg or AIFF).",
                     refused(415) { w.stage("not really audio".repeat(10).toByteArray()) }.message)
        for (fails in listOf(IllegalStateException("a reader's bug"), ArithmeticException("by zero"), IOException("bytes"))) {
            throwing = fails
            refused(415) { w.stage(wav, "song.wav") } // a stage's bytes: whatever the reader raises, a refusal
        }
        throwing = null
        for (bad in listOf(0.0, -1.0, Double.NaN, Double.POSITIVE_INFINITY)) {
            length = bad
            refused(415) { w.stage(wav) }
        }
        length = AudioStore.MAX_SECONDS + 1
        assertEquals("That file is longer than 30 minutes.", refused(422) { w.stage(flac) }.message)
        length = AudioStore.MAX_SECONDS
        assertEquals(AudioStore.MAX_SECONDS, w.stage(flac).durationS)
        assertEquals(1, w.names().count { it.endsWith(".flac") })
        val other = AudioStore(w.state, { _, _ -> Audio("WAV", 1.0, emptyMap()) }, { free }, { clock })
        refused(415) { other.stage(ByteArrayInputStream(mp3), "song.mp3", emptySet()) } // read as another format
        assertFalse(w.names().any { it.endsWith(".part") || it.endsWith(".mp3") || it.endsWith(".wav") })
    }

    @Test
    fun aWavNamedMp3IsAWav() {
        val w = World()
        val up = w.stage(wav, "song.mp3")
        assertEquals(Triple("WAV", ".upload-${up.id}.wav", "song.mp3"), Triple(up.format, up.file.name, up.name))
    }

    @Test
    fun anUploadPastTheLimitIsRefusedAtItsFirstBytePastItAndLeavesNothing() {
        val w = World()
        var read = 0L
        val tooBig = generated(AudioStore.AUDIO_MAX + 1) { read = it }
        assertEquals("That file is too big: an audio file is 128 MiB at most; `caracole audio FILE` takes any.",
                     refused(413) { w.store.stage(tooBig, "big.wav", emptySet()) }.message)
        assertEquals(AudioStore.AUDIO_MAX + 1, read) // nothing read past the byte that passes it
        assertEquals(emptyList(), w.names())
    }

    @Test
    fun aDiskThatFillsAsTheUploadComesIsRefusedNoRoomBeforeTheBodyIsWhole() {
        val w = World()
        var read = 0L
        val start = AudioStore.ROOM + (3L shl 20)
        val store = AudioStore(w.state, examiner, { start - read }, { clock }) // each byte spooled takes a byte of room
        val body = generated(10L shl 20) { read = it }
        assertEquals(AudioStore.WORDS["no_room"], refused(507) { store.stage(body, "big.wav", emptySet()) }.message)
        assertTrue(read < 5L shl 20, "read $read bytes of a body the disk can't hold") // refused as the room ran out
        assertEquals(emptyList(), w.names())
    }

    @Test
    fun theUploadsThatWouldGoAreRoomTheEarlyCheckCounts() {
        val w = World()
        val other = w.stage(mp3.copyOf(3 shl 20), "other.mp3")
        // Python lets the other go before it checks: what it frees is room an early check mustn't refuse for.
        free = AudioStore.ROOM + (2L shl 20)
        var read = 0L
        val store = AudioStore(w.state, examiner, {
            free - read + if (w.store.root.list()!!.any { it.startsWith(".upload-${other.id}.") }) 0 else (3L shl 20)
        }, { clock })
        val up = store.stage(generated(2L shl 20) { read = it }, "two.wav", emptySet())
        assertEquals(2L shl 20, up.size)
        refused(404) { w.store.staged(other.id) }
    }

    @Test
    fun anUploadAnotherTabStagesWhileThisOneSpoolsIsRoomTheEarlyCheckCountsToo() {
        val w = World()
        // Python's check passes for 4 MiB on a disk of ROOM and 8 MiB free once the other tab's 3 MiB go: every early
        // check must too, though those 3 MiB arrived after this upload's first MiB, and are let go only at its end.
        val start = AudioStore.ROOM + (8L shl 20)
        var read = 0L
        var other: String? = null
        fun there(id: String?) = id != null && w.store.root.list()!!.any { it.startsWith(".upload-$id.") }
        val store = AudioStore(w.state, examiner, { start - read - if (there(other)) 3L shl 20 else 0 }, { clock })
        val body = generated(4L shl 20) {
            read = it
            if (other == null && it > (1L shl 20) + (1L shl 16)) other = w.stage(mp3.copyOf(3 shl 20), "other.mp3").id
        }
        val up = store.stage(body, "four.wav", emptySet())
        assertEquals(4L shl 20, up.size)
        refused(404) { w.store.staged(other!!) }
    }

    @Test
    fun aBodyThatIsntAudioIsRefusedOnceItsHeadIsIn() {
        val w = World()
        var read = 0L
        val body = object : InputStream() {
            override fun read(): Int = throw AssertionError("read a chunk at a time")
            override fun read(b: ByteArray, off: Int, len: Int): Int {
                val n = minOf(len, 1 shl 16)
                b.fill('x'.code.toByte(), off, off + n)
                read += n
                return n
            }
        }
        assertEquals(AudioStore.WORDS["not_audio"], refused(415) { w.store.stage(body, "notes.mp3", emptySet()) }.message)
        assertTrue(read <= 1 shl 16, "read $read bytes of a body whose head says it isn't audio")
        assertEquals(emptyList(), w.names())
    }

    @Test(timeout = 10_000)
    fun aStreamThatReadsNothingForeverIsABrokenStreamNeverASpin() {
        val w = World()
        val stuck = object : InputStream() {
            override fun read(): Int = throw AssertionError("read a chunk at a time")
            override fun read(b: ByteArray, off: Int, len: Int): Int = 0
        }
        assertFailsWith<IOException> { w.store.stage(stuck, "stuck.mp3", emptySet()) }
        assertEquals(emptyList(), w.names())
    }

    @Test
    fun tooLittleRoomIsRefusedAsPythonsCheckForTheBytesStaged() {
        val w = World()
        // Python's check before writing: free < 2 * size + ROOM. The spooled bytes are on the disk by then, counted free.
        free = AudioStore.ROOM + mp3.size - 1
        assertEquals("No room to keep it here.", refused(507) { w.stage(mp3) }.message)
        assertEquals(emptyList(), w.names())
        free += 1
        assertNotNull(w.stage(mp3))
    }

    @Test
    fun aStagedIdNamesOneRegularFileInTheStoreNeverAPathOrALink() {
        val w = World()
        for (bad in listOf("../../caracole.sqlite", "0123456789ABCDEF", "0123456789abcde", "0123456789abcdef0",
                           "0123456789abcdef/../x", "0123456789abcdef\n", "０１２３４５６７８９ａｂｃｄｅｆ")) {
            assertEquals(AudioStore.WORDS["which"], refused(400) { w.store.staged(bad) }.message)
            refused(400) { w.store.drop(bad) }
        }
        refused(404) { w.store.staged("0123456789abcdef") }
        val secret = tmp.newFile("secret").apply { writeBytes(mp3) }
        val up = w.stage(mp3, "a.mp3")
        up.file.delete()
        Files.createSymbolicLink(up.file.toPath(), secret.toPath())
        refused(404) { w.store.staged(up.id) }
        val song = w.song()
        refused(404) { w.db { w.store.keep(it, song, up) } }
        w.store.drop(up.id) // the link goes, never what it points at
        assertFalse(Files.exists(up.file.toPath(), LinkOption.NOFOLLOW_LINKS))
        assertTrue(secret.readBytes().contentEquals(mp3))
        val two = w.stage(mp3, "b.mp3")
        File(w.store.root, ".upload-${two.id}.wav").writeBytes(wav)
        refused(404) { w.store.staged(two.id) }
    }

    @Test
    fun aLinkInPlaceOfTheStoreIsRefused() {
        val w = World()
        val elsewhere = tmp.newFolder("elsewhere")
        w.state.mkdirs()
        Files.createSymbolicLink(w.store.root.toPath(), elsewhere.toPath())
        val said = refused(500) { w.stage(mp3) }
        assertEquals("${w.store.root} isn't a folder of caracole's own (a symbolic link, say): no audio file is kept there.",
                     said.message)
        assertEquals(emptyList(), elsewhere.list()!!.toList())
    }

    @Test
    fun aStagedUploadIsDroppedNowOrSweptAfterAnHourUnlessAJobNamesIt() {
        val w = World()
        val one = w.stage(mp3, "a.mp3")
        val two = w.stage(wav, "b.wav", setOf(one.id))
        File(w.store.root, ".upload-0123456789abcdef.ogg").writeBytes("what a stopped upload left".toByteArray())
        File(w.store.root, ".upload-fedcba9876543210.part").writeBytes("a spool a killed upload left".toByteArray())
        File(w.store.root, "notes.txt").writeText("not caracole's")
        val now = System.currentTimeMillis() / 1000.0
        assertEquals(emptyList(), w.store.sweep(emptySet(), now))
        val later = now + AudioStore.EXPIRES + 1
        assertEquals(listOf(one.id, "0123456789abcdef").sorted(), w.store.sweep(setOf(two.id), later))
        refused(404) { w.store.staged(one.id) }
        assertEquals(two, w.store.staged(two.id))
        w.store.drop(two.id)
        refused(404) { w.store.staged(two.id) }
        refused(404) { w.store.drop(two.id) }
        assertEquals(listOf("notes.txt"), w.names())
        assertTrue(w.store.gone(two.id) && !w.store.gone("nope") && !w.store.gone(null))
    }

    // --- a song's own audio -----------------------------------------------------------------------------------------

    @Test
    fun keepNamesItBySongAndDigestAndLinksIt() {
        val w = World()
        val song = w.song()
        val up = w.stage(flac, "creep.flac")
        val kept = w.db { w.store.keep(it, song, up) }
        assertEquals(File(w.store.root, "${song.id}-${sha256(flac).take(16)}.flac"), kept)
        assertTrue(kept.readBytes().contentEquals(flac))
        assertEquals("rw-------", mode(kept))
        val after = w.row(song)
        assertEquals(kept.path, after.audioPath)
        assertEquals(AudioStore.seconds(Files.getLastModifiedTime(kept.toPath())), after.audioMtime)
        assertEquals(kept, w.store.uploaded(after))
        refused(404) { w.store.staged(up.id) }
        assertEquals(listOf(kept.name), w.names()) // nothing left over
        assertEquals("creep.flac", w.db { w.store.givenName(it, after) })
        // The same file again is the song's audio already: nothing changes.
        val again = w.stage(flac, "C:\\Users\\me\\creep\u0007 take 2.flac")
        assertEquals(kept, w.db { w.store.keep(it, after, again) })
        assertEquals(after.audioMtime, w.row(song).audioMtime)
        assertEquals("creep take 2.flac", w.db { w.store.givenName(it, after) })
        assertEquals(listOf(kept.name), w.names())
        assertEquals(2, w.markers().size) // each moved upload's marker, its keep over
    }

    @Test
    fun aNewUploadReplacesTheSongsOldOneButNeverAFileAnotherSongNames() {
        val w = World()
        val song = w.song()
        val other = w.song("Oasis", "Wonderwall")
        val first = w.db { w.store.keep(it, song, w.stage(mp3)) }
        val theirs = w.db { w.store.keep(it, other, w.stage(wav, "w.wav", emptySet())) }
        val second = w.db { w.store.keep(it, it.row(song), w.stage(flac, "c.flac")) }
        assertTrue(!first.exists() && second.exists() && theirs.exists())
        assertEquals(theirs.path, w.row(other).audioPath)
        // Two rows naming one file: replacing one's audio leaves it the other's.
        w.db { Versions.updateSong(it, other.id, mapOf("audio_path" to second.path)) }
        w.db { w.store.keep(it, it.row(song), w.stage(mp3.copyOf(300))) }
        assertTrue(second.exists())
    }

    @Test
    fun theRowAndTheNameAreWrittenTogetherOrNotAtAll() {
        val w = World()
        val song = w.song()
        val first = w.db { w.store.keep(it, song, w.stage(mp3, "Creep (Live).mp3")) }
        val before = w.row(song)
        w.db { it.execute("CREATE TRIGGER no_name BEFORE INSERT ON kv WHEN NEW.key LIKE 'audio:name:%' " +
                             "BEGIN SELECT RAISE(ABORT, 'the name''s write fails'); END") }
        val up = w.stage(flac, "Creep (Studio).flac")
        assertFailsWith<Exception> { w.db { w.store.keep(it, before, up) } }
        val after = w.row(song)
        assertEquals(Pair(first.path, before.audioMtime), Pair(after.audioPath, after.audioMtime))
        assertEquals("Creep (Live).mp3", w.db { w.store.givenName(it, after) })
    }

    @Test
    fun keepRefusesASongNoLongerInTheBookAndLeavesTheUpload() {
        val w = World()
        val song = w.song()
        w.db { it.execute("DELETE FROM songs WHERE id = ?", song.id) }
        val up = w.stage(mp3, "creep.mp3")
        assertEquals("Radiohead - Creep isn't in the book any more.", refused(404) { w.db { w.store.keep(it, song, up) } }.message)
        assertEquals(up, w.store.staged(up.id))
        assertEquals(listOf(up.file.name, ".upload-${up.id}.json").sorted(), w.names())
    }

    @Test
    fun aSongsAudioIsAnUploadOnlyWhenItIsAKeptFileOfTheStore() {
        val w = World()
        val song = w.song()
        val kept = w.db { w.store.keep(it, song, w.stage(mp3)) }
        val music = tmp.newFolder("Music")
        for (path in listOf(File(music, "Creep.mp3"), File(w.store.root, "sub/${kept.name}"), File(w.store.root, "notes.mp3"))) {
            path.parentFile.mkdirs()
            path.writeBytes(mp3)
            w.db { Versions.updateSong(it, song.id, mapOf("audio_path" to path.path)) }
            assertNull(w.store.uploaded(w.row(song)), path.path)
        }
        val link = File(w.store.root, "${song.id}-${"0".repeat(16)}.mp3")
        Files.createSymbolicLink(link.toPath(), kept.toPath())
        w.db { Versions.updateSong(it, song.id, mapOf("audio_path" to link.path)) }
        assertNull(w.store.uploaded(w.row(song)))
        // Another spelling of the same folder is the same store.
        val alias = File(tmp.root, "alias")
        Files.createSymbolicLink(alias.toPath(), w.state.toPath())
        w.db { Versions.updateSong(it, song.id, mapOf("audio_path" to File(alias, "audio/${kept.name}").path)) }
        assertEquals(kept, w.store.uploaded(w.row(song)))
        assertEquals(1, w.db { w.store.tidy(it) }) // the link by a kept file's name, which no song names
        assertTrue(kept.exists() && !Files.exists(link.toPath(), LinkOption.NOFOLLOW_LINKS))
    }

    @Test
    fun tidyDeletesTheFilesNoSongNames() {
        val w = World()
        assertEquals(0, w.db { w.store.tidy(it) }) // no store
        assertFalse(w.store.root.exists())
        val song = w.song()
        val kept = w.db { w.store.keep(it, song, w.stage(mp3)) }
        val orphan = File(w.store.root, "999-${"a".repeat(16)}.mp3").apply { writeBytes(mp3) }
        val leftover = File(w.store.root, ".keep-0123456789abcdef.part").apply { writeBytes("half".toByteArray()) }
        val up = w.stage(wav, "b.wav", setOf("ffffffffffffffff"))
        val mine = File(w.store.root, "notes.txt").apply { writeText("not caracole's") }
        assertEquals(2, w.db { w.store.tidy(it) })
        assertTrue(kept.exists() && mine.exists() && !orphan.exists() && !leftover.exists())
        assertEquals(up, w.store.staged(up.id))
        w.db { it.execute("DELETE FROM songs WHERE id = ?", song.id) }
        assertEquals(1, w.db { w.store.tidy(it) })
        assertFalse(kept.exists())
    }

    // --- a keep cut off: each state the marker leaves, and the job asked again -------------------------------------

    /** A keep stopped after its marker and before the data's move: the state written as keep writes it then. */
    private fun World.stoppedBeforeTheMove(): Pair<SongRow, AudioStore.Staged> {
        val song = song()
        val up = stage(mp3, "creep.mp3")
        val kept = AudioStore.keptName(song.id, up.sha256, up.format)
        File(store.root, ".upload-${up.id}.kept").writeText(AudioStore.markerText(kept, song.id, clock))
        return song to up
    }

    @Test
    fun cutBeforeTheMoveTheMarkerAndTheDataStayAndTheJobAgainFinishes() {
        val w = World()
        val (song, up) = w.stoppedBeforeTheMove()
        assertNull(w.store.marked(up.id)) // its kept file isn't there yet
        w.store.sweep(emptySet(), clock)
        w.store.sweep(emptySet(), up.at + AudioStore.EXPIRES + 1) // no job holds it: still the keep's to finish
        assertEquals(listOf(".upload-${up.id}.kept"), w.markers())
        assertEquals(0, w.db { w.store.tidy(it) })
        w.stage(wav, "other.wav") // a stage lets go of no keep under way
        assertEquals(up, w.store.staged(up.id))
        val kept = w.db { w.store.keep(it, song, w.store.staged(up.id)) }
        assertEquals(kept.path, w.row(song).audioPath)
        assertTrue(w.store.marked(up.id)!!.done)
    }

    @Test
    fun cutAfterTheMoveTheMarkedFileIsSparedAndAdoptFinishesTheKeep() {
        val w = World()
        val song = w.song()
        val up = w.stage(mp3, "creep take 3.mp3")
        w.db { it.execute("CREATE TRIGGER killed BEFORE UPDATE OF audio_path ON songs BEGIN SELECT RAISE(ABORT, 'killed'); END") }
        assertFailsWith<Exception> { w.db { w.store.keep(it, song, up) } } // the job stopped between the move and the row
        w.db { it.execute("DROP TRIGGER killed") }
        val moved = File(w.store.root, AudioStore.keptName(song.id, up.sha256, "MP3"))
        assertTrue(moved.exists())
        assertNull(w.row(song).audioPath)
        assertEquals(listOf(".upload-${up.id}.kept"), w.markers())
        val marked = w.store.marked(up.id)!!
        assertEquals(moved, marked.file)
        assertFalse(marked.done)
        assertEquals(0, w.db { w.store.tidy(it) }) // its keep isn't over: the upload's still
        assertTrue(moved.exists())
        assertEquals(emptyList(), w.store.sweep(emptySet(), up.at + AudioStore.EXPIRES + 1)) // nor a staged upload
        refused(404) { w.store.staged(up.id) } // its data moved
        val another = w.song("Oasis", "Wonderwall")
        refused(404) { w.db { w.store.adopt(it, another, up.id) } } // another song's: never
        assertEquals(moved, w.db { w.store.adopt(it, song, up.id) })
        assertEquals(moved.path, w.row(song).audioPath)
        assertEquals("creep take 3.mp3", w.db { w.store.givenName(it, song) })
        assertTrue(w.store.marked(up.id)!!.done)
        refused(404) { w.db { w.store.adopt(it, song, up.id) } } // a keep already over
    }

    @Test
    fun allDoneTheMarkerSaysSoUntilItsFileGoesOrItsThirtyDaysPass() {
        val w = World()
        val song = w.song()
        val up = w.stage(mp3, "creep.mp3")
        val kept = w.db { w.store.keep(it, song, up) }
        assertEquals(listOf(".upload-${up.id}.kept"), w.markers())
        val other = w.stage(wav, "other.wav") // every staged upload no job names goes, never a marker
        assertEquals(listOf(".upload-${up.id}.kept"), w.markers())
        assertEquals(listOf(other.id), w.store.sweep(emptySet(), other.at + AudioStore.EXPIRES + 1))
        assertEquals(kept, w.store.marked(up.id)!!.file)
        kept.delete()
        w.store.sweep(emptySet(), clock)
        assertEquals(emptyList(), w.markers())
        assertNull(w.store.marked(up.id))
        val two = w.stage(flac, "b.flac")
        w.db { w.store.keep(it, it.row(song), two) }
        w.store.sweep(emptySet(), clock + AudioStore.MARKED + 1) // past the Journal's history: Try again can't come
        assertEquals(emptyList(), w.markers())
    }

    @Test
    fun aMarkerBeforeTheMoveGoesWithItsDataPastItsWindow() {
        val w = World()
        val (_, up) = w.stoppedBeforeTheMove()
        w.store.sweep(emptySet(), clock + AudioStore.MARKED + 1)
        assertEquals(emptyList(), w.markers())
        assertEquals(emptyList(), w.names())
        assertTrue(w.store.gone(up.id))
    }

    @Test
    fun aMarkerAJobHoldsStaysAndOneWithNeitherFileNorDataGoesAtOnce() {
        val w = World()
        val (_, up) = w.stoppedBeforeTheMove()
        up.file.delete() // the data gone, no kept file: only a job naming it keeps the marker
        w.store.sweep(setOf(up.id), clock)
        assertEquals(listOf(".upload-${up.id}.kept"), w.markers())
        w.store.sweep(emptySet(), clock)
        assertEquals(emptyList(), w.markers())
        assertEquals(emptyList(), w.names())
    }

    @Test
    fun keepTakesAPurchasesPlaceAndLeavesItsFileInMusic() {
        // The owner's decision of 2026-11-25: a file given a song is its audio, whatever it had.
        val w = World()
        val song = w.song()
        val bought = File(tmp.newFolder("Music"), "Radiohead - Creep.wav").apply { writeBytes(wav) }
        w.db { Versions.updateSong(it, song.id, mapOf("audio_path" to bought.path, "audio_mtime" to 5.0)) }
        val kept = w.db { w.store.keep(it, it.row(song), w.stage(flac, "mine.flac")) }
        assertEquals(kept.path, w.row(song).audioPath)
        assertTrue(bought.readBytes().contentEquals(wav))
        assertEquals(listOf(bought.name), bought.parentFile.list()!!.toList())
    }

    /** Two songs an older normalizer kept apart (test_audio_store.py's _two_spellings), each given a file: the older
     * one's [olderAt] and the newer's [newerAt] their audio_mtime; their files. */
    private fun World.twoGiven(olderAt: Double, newerAt: Double): Pair<File, File> {
        val newer = song("Enanitos Verdes", "Lamento Boliviano")
        val olderFile = File(store.root, "${newer.id + 1}-${"1".repeat(16)}.mp3")
        val newerFile = File(store.root, "${newer.id}-${"2".repeat(16)}.wav")
        store.root.mkdirs()
        olderFile.writeBytes(mp3)
        newerFile.writeBytes(wav)
        db {
            it.execute("INSERT INTO songs (id, key, artist, title, artists, source_ids, added_at, created_at, updated_at, " +
                           "audio_path, audio_mtime) VALUES (?, 'los-enanitos-verdes/lamento-boliviano', 'Los Enanitos Verdes', " +
                           "'Lamento Boliviano', '[\"Los Enanitos Verdes\"]', '{}', '2026-09-01T00:00:00Z', " +
                           "'2026-09-01T00:00:00Z', '2026-09-01T00:00:00Z', ?, ?)", newer.id + 1, olderFile.path, olderAt)
            // The newer record keeps the lower id: it is the one the merge keeps.
            Versions.updateSong(it, newer.id, mapOf("audio_path" to newerFile.path, "audio_mtime" to newerAt))
            it.kvDelete("songs:key_version")
            library.ensureCurrentKeys(it)
        }
        return olderFile to newerFile
    }

    @Test
    fun aMergeKeepsTheFileGivenAndTidyLetsItBe() {
        val w = World()
        val (given, _) = w.twoGiven(olderAt = 9.0, newerAt = 5.0)
        val (song) = w.db { Songs.list(it) }
        assertEquals(given.path, song.audioPath)
        assertEquals(1, w.db { w.store.tidy(it) }) // the other upload, no song's now
        assertTrue(given.exists())
        assertEquals(given, w.store.uploaded(song))
    }

    @Test
    fun aMergeOfTwoUploadsKeepsTheNewerAndTidyLetsTheOtherGo() {
        val w = World()
        val (older, newer) = w.twoGiven(olderAt = 1.0, newerAt = 7.5)
        val (song) = w.db { Songs.list(it) }
        assertEquals(newer.path, song.audioPath)
        assertEquals(1, w.db { w.store.tidy(it) })
        assertTrue(newer.exists() && !older.exists())
    }

    // --- a removal --------------------------------------------------------------------------------------------------

    @Test
    fun aRemovalDeletesTheSongsFileAndSaysSo() {
        val w = World()
        val song = w.song()
        val kept = w.db { w.store.keep(it, song, w.stage(mp3)) }
        val plan = w.db { Removal.plan(it, w.library.libraryDir, it.row(song), w.store.root) }
        assertEquals(kept.path, plan.uploadedAudio)
        assertEquals(kept, w.db { w.library.givenAudio(it, it.row(song)) })
        assertEquals("the audio file you gave it, from caracole's own folder", AudioStore.REMOVAL_GOES)
        assertEquals("the audio file you gave it", AudioStore.REMOVAL_BRIEF)
        val done = w.db { Removal.remove(it, w.library.libraryDir, plan, "2026-11-27T00:00:00Z") }
        assertEquals(kept.path, done.audioDeleted)
        assertFalse(kept.exists())
        assertNull(w.db { it.kvGet("${AudioStore.NAME_KEY}${song.id}") })
    }

    @Test
    fun aRemovalLeavesAFileAnotherSongNames() {
        val w = World()
        val one = w.song()
        val two = w.song("Oasis", "Wonderwall")
        val shared = w.db { w.store.keep(it, one, w.stage(mp3)) }
        w.db { Versions.updateSong(it, two.id, mapOf("audio_path" to shared.path)) }
        assertNull(w.db { w.library.givenAudio(it, it.row(one)) })
        w.db { w.library.remove(it, one.key, "2026-11-27T00:00:00Z") }
        assertTrue(shared.exists())
        assertEquals(shared.path, w.row(two).audioPath)
        // And a library store with no audio folder deletes none.
        assertNull(w.db { LibraryStore(w.library.libraryDir).givenAudio(it, it.row(two)) })
    }

    // --- a stage of 100 MiB -----------------------------------------------------------------------------------------

    @Test
    fun aStageOf100MiBNeverHoldsTheBodyInTheHeap() {
        val w = World()
        val size = 100L shl 20
        val want = MessageDigest.getInstance("SHA-256").let { digest ->
            generated(size).use { input ->
                val buffer = ByteArray(1 shl 16)
                while (true) {
                    val n = input.read(buffer)
                    if (n < 0) break
                    digest.update(buffer, 0, n)
                }
            }
            JsonText.hex(digest.digest())
        }
        length = 60.0
        w.stage(mp3) // the store made, its lazy rules read and its classes loaded before the count
        val threads = ManagementFactory.getThreadMXBean() as com.sun.management.ThreadMXBean
        val me = Thread.currentThread().id
        val before = threads.getThreadAllocatedBytes(me)
        val up = w.store.stage(generated(size), "big.wav", emptySet())
        val allocated = threads.getThreadAllocatedBytes(me) - before
        assertEquals(size, up.size)
        assertEquals(size, up.file.length())
        assertEquals(want, up.sha256)
        // Buffering the body would allocate its 100 MiB at least; the spool reads it in 64 KiB chunks.
        assertTrue(allocated < 8L shl 20, "the stage allocated $allocated bytes in its thread")
    }

    /** [size] bytes of a WAV's head then a pattern, made as they are read: no array of their size. */
    private fun generated(size: Long, onRead: (Long) -> Unit = {}): InputStream = object : InputStream() {
        private val head = wav.copyOf(16)
        private var at = 0L
        override fun read(): Int {
            val one = ByteArray(1)
            return if (read(one, 0, 1) < 0) -1 else one[0].toInt() and 0xFF
        }
        override fun read(b: ByteArray, off: Int, len: Int): Int {
            if (at >= size) return -1
            val n = minOf(len.toLong(), size - at).toInt()
            for (k in 0 until n) {
                val i = at + k
                b[off + k] = if (i < head.size) head[i.toInt()] else (i * 31 % 251).toByte()
            }
            at += n
            onRead(at)
            return n
        }
    }
}
