package io.github.danielhp95.caracole.viewer.render

import io.github.danielhp95.caracole.core.db.Database
import io.github.danielhp95.caracole.core.db.Db
import io.github.danielhp95.caracole.core.inbox.HarmonicaFiles
import io.github.danielhp95.caracole.core.json.Canonical
import io.github.danielhp95.caracole.core.library.Kept
import io.github.danielhp95.caracole.core.library.LibraryStore
import io.github.danielhp95.caracole.core.library.Songs
import io.github.danielhp95.caracole.core.lookup.RenderStats
import io.github.danielhp95.caracole.core.py.PyUrl
import io.github.danielhp95.caracole.core.sync.Units
import io.github.danielhp95.caracole.core.testing.Corpus
import io.github.danielhp95.caracole.core.testing.Fixtures
import io.github.danielhp95.caracole.core.testing.Misses
import io.github.danielhp95.caracole.core.testing.TestDb
import io.github.danielhp95.caracole.mirror.Mirror
import io.github.danielhp95.caracole.viewer.testing.replays.RenderReplay
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import java.io.File
import java.security.MessageDigest

class PhoneRenderTest {
    @get:Rule val tmp = TemporaryFolder()

    // --- render.py's page path, as Python wrote it ----------------------------------------------------------------

    @Test
    fun everyRecordIsRenderPysPagePathWithNoPdf() {
        val misses = Misses("viewer/render")
        RenderReplay.replay(misses)
        misses.assertNone()
    }

    @Test
    fun theLyricsOnAnAutoSheetAndEachInfoJsonAreThoseOfPythonsPass() {
        val misses = Misses("viewer/render facts")
        RenderReplay.facts(misses)
        misses.assertNone()
        assertTrue("${misses.checked} answers", misses.checked >= 20) // every info.json and unit of six of the cases
    }

    // --- the records --------------------------------------------------------------------------------------------

    private fun database(): Database = TestDb.fresh(tmp.newFolder())

    private fun song(db: Db, artist: String, title: String, added: String = "2026-11-01T00:00:00Z"): Long {
        db.execute("INSERT INTO songs (key, artist, title, artists, added_at, created_at, updated_at) " +
                       "VALUES (?, ?, ?, ?, ?, ?, ?)",
                   "${artist.lowercase()}/${title.lowercase().replace(' ', '-')}", artist, title, "[\"$artist\"]",
                   added, added, added)
        return db.lastRowid()
    }

    private fun version(db: Db, songId: Long, tab: String, kind: String, raw: String = "{}"): Long {
        db.execute("INSERT INTO versions (provider, tab_id, song_id, slot, kind, rating, votes, version, url, raw, " +
                       "fetched_at) VALUES ('harptabs', ?, ?, 'guitar', ?, 0, 0, 1, '', ?, '2026-11-01T00:00:00Z')",
                   tab, songId, kind, raw)
        return db.lastRowid()
    }

    private fun sha(bytes: ByteArray) = Canonical.sha256Hex(bytes)

    @Test
    fun aPageIsRecordedWithTheUnitItWasMadeAtAndIsCurrentUntilTheSongChanges() = database().use { database ->
        val library = tmp.newFolder("library")
        database.writeBlocking { db ->
            val id = song(db, "Soda Stereo", "Persiana Americana")
            val digest = Units.digestOf(db, "song/soda stereo/persiana-americana")!!
            val page = "<html>a page</html>".toByteArray()
            WrittenPages.note(db, id, "sheet.html", page, digest)
            assertEquals(Written(sha(page), page.size.toLong(), digest), WrittenPages.written(db, id, "sheet.html"))
            assertTrue(WrittenPages.current(db, id, "sheet.html"))
            val text = db.kvGet("render:files:$id")
            WrittenPages.note(db, id, "sheet.html", page, digest) // the same bytes at the same digest: nothing written
            assertEquals(text, db.kvGet("render:files:$id"))
            assertEquals("{\"sheet.html\": {\"sha256\": \"${sha(page)}\", \"size\": ${page.size}, \"unit\": \"$digest\"}}", text)
            // the song changes (a version found for it): the page is no longer of the song as it is
            version(db, id, "1", "chords")
            assertFalse(WrittenPages.current(db, id, "sheet.html"))
            val now = Units.digestOf(db, "song/soda stereo/persiana-americana")!!
            WrittenPages.restamp(db, id, now)
            assertTrue(WrittenPages.current(db, id, "sheet.html"))
            assertNull(WrittenPages.written(db, id, "version-1.html"))
            assertFalse(WrittenPages.current(db, id, "version-1.html"))
            assertNotEquals(digest, now)
        }
    }

    @Test
    fun aPageIsForgottenAndDeletedWhileItIsAsWrittenAndOneOfYoursStays() = database().use { database ->
        val folder = tmp.newFolder("song")
        database.writeBlocking { db ->
            val id = song(db, "Placeholder Band", "Synthetic Song")
            val mine = "caracole's".toByteArray()
            File(folder, "version-1.html").writeBytes(mine)
            File(folder, "version-2.html").writeBytes(mine)
            WrittenPages.note(db, id, "version-1.html", mine, "d")
            WrittenPages.note(db, id, "version-2.html", mine, "d")
            File(folder, "version-2.html").writeText("edited on a synced device")
            WrittenPages.forget(db, id, listOf("version-1.html", "version-2.html", "never-written.html"), folder)
            assertFalse(File(folder, "version-1.html").exists())
            assertEquals("edited on a synced device", File(folder, "version-2.html").readText())
            assertNull(db.kvGet("render:files:$id")) // its last entry gone, the record goes
            // an entry that says neither its SHA-256 nor its size is left out, as render.written_entry reads it
            db.kvSet("render:files:$id", "{\"a.html\": {\"sha256\": \"x\", \"size\": true}, \"b.html\": {\"size\": 1}}")
            assertTrue(WrittenPages.record(db, id).isEmpty())
        }
    }

    @Test
    fun thePhonesRecordOfASongNamesItsUnitBuildAndScriptAndTheCardsReadTheChineseOnes() = database().use { database ->
        database.writeBlocking { db ->
            val one = song(db, "李健", "月亮代表")
            val two = song(db, "Soda Stereo", "Persiana Americana")
            WrittenPages.noteRendered(db, one, Rendered("u1", "b", "simplified"))
            WrittenPages.noteRendered(db, two, Rendered("u2", "b", null))
            assertEquals("{\"unit\": \"u1\", \"build\": \"b\", \"script\": \"simplified\"}", db.kvGet("render:$one:phone"))
            assertEquals("{\"unit\": \"u2\", \"build\": \"b\"}", db.kvGet("render:$two:phone"))
            assertEquals(Rendered("u1", "b", "simplified"), WrittenPages.rendered(db, one))
            assertEquals(setOf(one), PhoneRender.chineseSongs(db))
        }
    }

    @Test
    fun aSongbooksFilesAreRecordedAsSongbookPyRecordsThem() = database().use { database ->
        database.writeBlocking { db ->
            val page = "<html>book</html>".toByteArray()
            WrittenPages.noteSongbook(db, "Campfire", "inputs-digest", mapOf("songbook.html" to page))
            assertEquals(mapOf("songbook.html" to (sha(page) to page.size.toLong())), WrittenPages.songbook(db, "Campfire"))
            assertEquals("{\"inputs\": {\"songbook.html\": \"inputs-digest\"}, \"files\": {\"songbook.html\": " +
                             "{\"sha256\": \"${sha(page)}\", \"size\": ${page.size}}}}", db.kvGet("songbook:Campfire"))
            assertTrue(WrittenPages.songbook(db, "Elsewhere").isEmpty())
        }
    }

    // --- the harmonica tabs a song keeps ----------------------------------------------------------------------------

    @Test
    fun aSongsHarmonicaTabsAreItsKeptTabsByNumberWithTheirChips() = database().use { database ->
        database.writeBlocking { db ->
            val id = song(db, "Placeholder Band", "Synthetic Song")
            val other = song(db, "Placeholder Band", "Other Song")
            fun keep(songId: Long, name: String, raw: String) {
                val v = version(db, songId, name, "harmonica", raw)
                db.execute("INSERT INTO files (version_id, song_id, name, path, sha256, kept_rank, created_at) " +
                               "VALUES (?, ?, ?, ?, 'x', 1, '2026-11-01T00:00:00Z')", v, songId, name, "P/S/$name")
            }
            keep(id, "harmonica-10.txt", "{\"key\": \"C\", \"harp\": \"Diatonic\"}")
            keep(id, "harmonica-2.txt", "{\"key\": 7, \"harp\": null}")
            keep(id, "harmonica-x.txt", "{}")
            keep(other, "harmonica-1.txt", "not json")
            val tabs = HarmonicaFiles.of(db, id)
            assertEquals(listOf("harmonica-2.txt", "harmonica-10.txt"), tabs.map { it.name })
            assertEquals(listOf(2, 10), tabs.map { it.number })
            assertEquals(listOf(null, "C"), tabs.map { it.key })
            assertEquals(listOf(null, "Diatonic"), tabs.map { it.harp })
            assertEquals("harmonica-10.html", tabs[1].page)
            assertEquals(listOf(id, id, other), HarmonicaFiles.of(db).map { it.songId })
            assertNull(HarmonicaFiles.page("harmonica-1.html"))
        }
    }

    // --- the build ------------------------------------------------------------------------------------------------

    private val conformance get() = File(System.getProperty("caracole.conformance")!!).parentFile

    @Test
    fun theBuildHashesEveryFileThePageBuilderReads() {
        val viewer = File(conformance.parentFile.parentFile, "src/caracole/viewer")
        val assets = viewer.listFiles()!!.map { it.name }.filter {
            it.endsWith(".js") || it.endsWith(".css") || (it.startsWith("voicings") && it.endsWith(".json")) ||
                it == "LICENSE-chords-db"
        }
        assertEquals(assets.sorted(), RenderBuild.ASSETS.sorted())
        val data = File(conformance, "data/caracole")
        val read = RenderBuild.FOLDERS.flatMap { folder ->
            File(data, folder).listFiles()!!.filter { it.isFile }.map { "$folder/${it.name}" }
        } + listOf("page/empty_library.json", "page/icon.json")
        assertEquals(read.sorted(), RenderBuild.DATA.sorted())
        assertEquals(RenderBuild.of("0.1.0"), RenderBuild.of("0.1.0"))
        assertNotEquals(RenderBuild.of("0.1.0"), RenderBuild.of("0.1.1"))
    }

    /** An APK's entries, as a zip: each name with its bytes. */
    private fun apk(vararg entries: Pair<String, String>): File {
        val file = File(tmp.newFolder(), "base.apk")
        java.util.zip.ZipOutputStream(file.outputStream()).use { zip ->
            for ((name, text) in entries) {
                zip.putNextEntry(java.util.zip.ZipEntry(name))
                zip.write(text.toByteArray())
                zip.closeEntry()
            }
        }
        return file
    }

    @Test
    fun onThePhoneTheBuildIsTheApksCodeAndDataSoANewApkMakesThePagesAgainAtTheSameVersion() {
        val one = apk("classes.dex" to "code", "caracole/viewer/viewer.css" to "css", "res/layout.xml" to "x")
        val fixed = apk("classes.dex" to "code fixed", "caracole/viewer/viewer.css" to "css", "res/layout.xml" to "x")
        val retabled = apk("classes.dex" to "code", "caracole/viewer/viewer.css" to "css",
                           "caracole/unicode/case.txt" to "more", "res/layout.xml" to "x")
        val other = apk("classes.dex" to "code", "caracole/viewer/viewer.css" to "css", "res/layout.xml" to "y")
        assertEquals(listOf("caracole/viewer/viewer.css 3 ${java.util.zip.CRC32().apply { update("css".toByteArray()) }.value.toString(16)}",
                            "classes.dex 4 ${java.util.zip.CRC32().apply { update("code".toByteArray()) }.value.toString(16)}"),
                     RenderBuild.packed(one))
        assertNotEquals(RenderBuild.of("0.1.0", one), RenderBuild.of("0.1.0", fixed))
        assertNotEquals(RenderBuild.of("0.1.0", one), RenderBuild.of("0.1.0", retabled))
        assertEquals(RenderBuild.of("0.1.0", one), RenderBuild.of("0.1.0", other)) // what no page is made from
        assertNotEquals(RenderBuild.of("0.1.0", one), RenderBuild.of("0.1.1", one))
        // a jar of classes (a JVM's) is no APK: the files the page builder reads are hashed, as with no archive
        val jar = apk("io/github/X.class" to "c", "caracole/viewer/viewer.css" to "css")
        assertNull(RenderBuild.packed(jar))
        assertEquals(RenderBuild.of("0.1.0", null), RenderBuild.of("0.1.0", jar))
        assertEquals(RenderBuild.of("0.1.0"), RenderBuild.of("0.1.0", null)) // the tests' classes are in a folder
    }

    // --- which songs the phone owes ---------------------------------------------------------------------------------

    @Test
    fun theSongsOwedAreThoseNeverMadeChangedSinceOrMadeByAnotherBuildButNeverAnIgnoredOne() = database().use { database ->
        val render = PhoneRender(database, tmp.newFolder("library"), null, "0.1.0")
        database.writeBlocking { db ->
            val one = song(db, "Soda Stereo", "Persiana Americana", "2026-11-01T00:00:00Z")
            val two = song(db, "Soda Stereo", "Cuando Pase El Temblor", "2026-11-02T00:00:00Z")
            val ignored = song(db, "Soda Stereo", "Ignored", "2026-11-03T00:00:00Z")
            db.execute("INSERT INTO phone_overrides (tbl, key, written, value) VALUES ('ignore', ?, ?, 'true')",
                       "soda stereo/ignored", "Soda Stereo - Ignored")
            assertEquals(listOf(two, one), render.owed(db).map { it.id })
            fun made(id: Long, build: String = render.build()) = WrittenPages.noteRendered(
                db, id, Rendered(Units.digestOf(db, "song/${Songs.byId(db, id)!!.key}")!!, build, null))
            made(one)
            made(two, build = "another build")
            assertEquals(listOf(two), render.owed(db).map { it.id })
            made(two)
            assertTrue(render.owed(db).isEmpty())
            version(db, one, "5", "chords") // the song changed since
            assertEquals(listOf(one), render.owed(db).map { it.id })
            assertFalse(ignored in render.owed(db).map { it.id })
        }
    }

    @Test
    fun atTheStartThePhoneOwesPagesForASongNoPassOfThisBuildMadeAndATakeFindsThoseThatMoved() = database().use { database ->
        val library = tmp.newFolder("library")
        val render = PhoneRender(database, library, null, "0.1.0")
        assertFalse("a library with no song owes no page", render.stale())
        load(database, library, "own_versions")
        assertTrue("songs no pass made", render.stale())
        assertTrue("a take that brought them owes their pages", render.afterSync())
        render.renderStale(between = {})
        assertFalse(render.stale())
        assertFalse(render.afterSync())
        // a change to a song moves its unit: the start doesn't read each song's digest, a take's check does, and
        // owes the pages until a pass ends, an app stopped before it ran included
        database.writeBlocking { db -> version(db, 1, "5", "chords") }
        assertFalse(render.stale())
        assertTrue(render.afterSync())
        assertTrue(render.stale())
        assertEquals(listOf(1L), database.read { db -> render.owed(db).map { it.id } })
        render.renderStale(between = {})
        assertFalse(render.stale())
        // owe: a change on the phone that makes no page of its song asks for the next pass
        database.writeBlocking { db -> render.owe(db) }
        assertTrue(render.stale())
        render.renderStale(between = {})
        assertFalse(render.stale())
        // a new build owes every page
        val next = object : PhoneRender(database, library, null, "0.1.0") {
            override fun build(): String = "another build"
        }
        assertTrue(next.stale())
        assertEquals(3, database.read { db -> next.owed(db).size })
    }

    // --- the whole pass ---------------------------------------------------------------------------------------------

    /** A case's fixture from vectors/viewer/render.jsonl, in [database] and [library]. */
    private fun load(database: Database, library: File, case: String) {
        val record = Corpus.records(RenderReplay.VECTOR).first { it.extra["case"] == JsonPrimitive(case) }
        database.writeBlocking { db -> Fixtures.loadRecords(db, record.args[0].jsonArray.map { it.jsonObject }, library) }
    }

    @Test
    fun aLookupsPdfStageMakesTheSongsPagesAndAgainWritesNothing() = database().use { database ->
        val library = tmp.newFolder("library")
        load(database, library, "ug_sheet")
        val render = PhoneRender(database, library, null, "0.1.0")
        val made = database.writeBlocking { db -> render.render(db, listOf(1L), null) }
        assertEquals(1, made.written)
        assertTrue(File(library, "Soda Stereo/De Música Ligera/sheet.html").isFile)
        assertTrue(database.read { db -> WrittenPages.current(db, 1, "sheet.html") })
        val again = database.writeBlocking { db -> render.render(db, listOf(1L), null) }
        assertEquals(0, again.written)
        assertEquals(1, again.unchanged)
        assertTrue(database.read { db -> render.owed(db).isEmpty() })
    }

    @Test
    fun theRenderJobYieldsBetweenSongsAndPassesOverOneALookupMadeMeanwhile() = database().use { database ->
        val library = tmp.newFolder("library")
        load(database, library, "own_versions")
        val render = PhoneRender(database, library, null, "0.1.0")
        assertEquals(3, database.read { db -> render.owed(db).size })
        val progress = ArrayList<Pair<Int, Int>>()
        var yields = 0
        val made = render.renderStale(between = {
            yields++
            if (yields == 1) database.writeBlocking { db -> render.render(db, listOf(1L), null) } // a lookup's
        }) { done, total -> progress.add(done to total) }
        assertEquals(2, yields)
        assertEquals(listOf(0 to 3, 1 to 3, 2 to 3, 3 to 3), progress)
        assertEquals(2, made.written) // the third, the lookup made
        assertTrue(database.read { db -> render.owed(db).isEmpty() })
        assertEquals(render.build(), database.read { db -> db.kvGet(RenderNames.BUILD_KEY) })
    }

    @Test
    fun aSongTheMirrorServesAtItsDigestGetsItsProgressionsAloneAndThePhonesOwnPagesGo() = database().use { database ->
        val library = tmp.newFolder("library")
        load(database, library, "ug_sheet")
        val folder = File(library, "Soda Stereo/De Música Ligera")
        // the phone made the song's pages (the mirror didn't serve them yet)
        database.writeBlocking { db -> PhoneRender(database, library, null, "0.1.0").render(db, listOf(1L), null) }
        assertTrue(File(folder, "sheet.html").isFile && File(folder, "sheet.cho").isFile)
        assertEquals(setOf("sheet.cho", "sheet.html"), database.read { db -> WrittenPages.record(db, 1).keys })
        // a sync brings the computer's pages of the song as the phone holds it: the phone's own go, as written
        val render = PhoneRender(database, library, mirror(database), "0.1.0")
        File(folder, "info.json").delete()
        database.writeBlocking { db -> render.render(db, listOf(1L), null) }
        assertFalse(File(folder, "sheet.html").exists())
        assertFalse(File(folder, "sheet.cho").exists())
        assertTrue("its info.json as the phone holds the song now", File(folder, "info.json").isFile)
        database.read { db ->
            assertTrue(WrittenPages.record(db, 1).isEmpty())
            assertTrue(db.kvGet("render:progressions:1") != null)
            assertEquals(Units.digestOf(db, RenderNames.unitOf(Songs.byId(db, 1)!!.key)), WrittenPages.rendered(db, 1)!!.unit)
        }
    }

    @Test
    fun aSongWhosePassFailsOnABugCostsTheOthersNothingAndIsStampedAllTheSame() = database().use { database ->
        val library = tmp.newFolder("library")
        load(database, library, "own_versions")
        // the Moved Song's version holds a raw that is no JSON object: reading it is a bug (render.py's would stop)
        val broken = database.writeBlocking { db ->
            db.execute("UPDATE versions SET raw = '[]' WHERE tab_id = '85055'")
            db.one("SELECT song_id FROM versions WHERE tab_id = '85055'") { it.long(0)!! }!!
        }
        val render = PhoneRender(database, library, null, "0.1.0")
        var betweens = 0
        val made = render.renderStale(between = { betweens++ })
        assertEquals(2, betweens)
        assertEquals(setOf(broken), made.failed.keys)
        val why = made.failed.getValue(broken)
        assertTrue(why, why.startsWith("Placeholder Band - Moved Song: ${RenderNames.BUG}: "))
        assertEquals(2, made.written)
        assertTrue(File(library, "Eagles/Hotel California/sheet.html").isFile)
        assertTrue("the failed song too: a new build tries again", database.read { db -> render.owed(db).isEmpty() })
        assertFalse(render.stale())
    }

    @Test
    fun theLookupsPdfStageMakesItsSongsPagesThroughTheSeam() = database().use { database ->
        val library = tmp.newFolder("library")
        load(database, library, "ug_sheet")
        val render = PhoneRender(database, library, null, "0.1.0")
        val pages = render.seam
        assertTrue(pages === render)
        val made = database.writeBlocking { db -> pages.render(db, listOf(1L), null) }
        assertEquals(RenderStats(written = 1), made)
        assertEquals(RenderStats(unchanged = 1), database.writeBlocking { db -> pages.render(db, listOf(1L), null) })
    }

    /** A mirror holding the song's sheet.html at its unit's digest now, as a sync leaves one. */
    private fun mirror(database: Database): Mirror {
        val mirror = Mirror(tmp.newFolder())
        mirror.blobs.mkdirs()
        val unit = database.read { db -> RenderNames.unitOf(Songs.byId(db, 1)!!.key) }
        val digest = database.read { db -> Units.digestOf(db, unit)!! }
        val files = listOf(Triple("Soda Stereo/De Música Ligera/sheet.html", "<!doctype html>computer's", unit),
                           Triple("index.html", "<!doctype html>start", null))
        val entries = files.map { (path, content, of) ->
            val bytes = content.toByteArray()
            File(mirror.blobs, MessageDigest.getInstance("SHA-256").digest(bytes).joinToString("") { "%02x".format(it) })
                .writeBytes(bytes)
            JsonObject(buildMap {
                put("path", JsonPrimitive(path)); put("url", JsonPrimitive(PyUrl.quote("/$path")))
                put("size", JsonPrimitive(bytes.size)); put("sha256", JsonPrimitive(sha(bytes)))
                put("type", JsonPrimitive("text/html; charset=utf-8")); put("headers", JsonObject(emptyMap()))
                of?.let { put("unit", JsonPrimitive(it)); put("digest", JsonPrimitive(digest)) }
            })
        }
        mirror.manifestFile.writeText(JsonObject(mapOf("format" to JsonPrimitive(1), "start" to JsonPrimitive("index.html"),
                                                       "files" to JsonArray(entries))).toString())
        return mirror
    }
}
