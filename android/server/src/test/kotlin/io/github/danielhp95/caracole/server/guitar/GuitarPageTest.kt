package io.github.danielhp95.caracole.server.guitar

import io.github.danielhp95.caracole.core.inbox.GuitarFiles
import io.github.danielhp95.caracole.core.library.Kept
import io.github.danielhp95.caracole.core.library.LibraryStore
import io.github.danielhp95.caracole.core.library.Versions
import io.github.danielhp95.caracole.core.testing.Misses
import io.github.danielhp95.caracole.mirror.Mirror
import io.github.danielhp95.caracole.server.http.LibraryName
import io.github.danielhp95.caracole.server.page.MirrorPageData
import io.github.danielhp95.caracole.server.page.PhonePageData
import io.github.danielhp95.caracole.server.routes.GuitarRoutes
import io.github.danielhp95.caracole.server.testing.TestApp
import io.github.danielhp95.caracole.server.testing.TestParts
import io.github.danielhp95.caracole.server.testing.bytes
import io.github.danielhp95.caracole.server.testing.header
import io.github.danielhp95.caracole.server.testing.replays.GuitarReplay
import io.github.danielhp95.caracole.server.testing.text
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.jsonPrimitive
import org.junit.After
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import java.io.File
import java.net.URLEncoder
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith
import kotlin.test.assertFalse
import kotlin.test.assertNotNull
import kotlin.test.assertNull
import kotlin.test.assertTrue

/**
 * The Guitar Pro page on the phone (GuitarRoutes, GuitarPage, AlphaTabBundle, :core's GuitarFiles): caracole serve's
 * answers for the same library and files (GuitarReplay over vectors/web/guitar.jsonl, alphaTab 1.8.4's own bundle
 * among them), and what the phone does otherwise: the APK's bundle named by the app's resource, never served by the
 * server itself, and a name of N past an Int kept by its whole N, as Python's int keeps it.
 */
class GuitarPageTest {
    @get:Rule val tmp = TemporaryFolder()
    private val scope = CoroutineScope(SupervisorJob())

    @After fun stop() = scope.cancel()

    @Test fun everyRecordOfTheGuitarVectorAnswersAsCaracoleServeDid() {
        val misses = Misses("web/guitar")
        GuitarReplay.replay(misses)
        misses.assertNone()
        assertTrue(misses.checked > 150, "${misses.checked} answers checked")
    }

    @Test fun alphaTabsOwnFilesAreTheShellsAndMakeTheBundlePythonMade() {
        // `nix develop ./android` sets CARACOLE_ALPHATAB_DIR (android/flake.nix, ../nix/alphatab.nix): the replay of
        // the nix files' record is checked here, on the JVM; on the device GuitarPageTest checks the APK's.
        val dir = assertNotNull(GuitarReplay.alphaTabDir(), "CARACOLE_ALPHATAB_DIR names no folder: run the tests in " +
                                                             "nix develop ./android")
        val at = AlphaTabBundle.load(dir)
        assertTrue(Regex("alphatab-1\\.8\\.4-[0-9a-f]{16}\\.js").matches(at.name), at.name)
        assertTrue(at.body.size > 2_000_000, "${at.body.size} bytes")
        val text = at.body.toString(Charsets.UTF_8)
        assertTrue(text.startsWith("/* alphaTab 1.8.4 (MPL-2.0)") && text.endsWith("window.caracoleAlphaTab.library();\n"))
        for (licence in listOf("alphaTab-LICENSE", "Bravura-OFL.txt", "sonivox-LICENSE")) {
            assertTrue(File(File(dir, "licenses"), licence).isFile, licence)
        }
    }

    @Test fun withoutTheAppsResourceThereIsNoInstalledBundleAndThePageSaysSo() {
        // The JVM has no APK: the library page offers Guitar Pro files as downloads, and /guitar says why.
        assertNull(AlphaTabBundle.installed())
        assertFalse(GuitarRoutes.available())
        library { test, path ->
            val refused = test.get(target(path))
            assertEquals(503, refused.status)
            assertTrue("No alphaTab here" in refused.text)
        }
    }

    @Test fun theApksBundleIsNamedByItsRecordAndTheAppAnswersItNeverTheServer() {
        val at = AlphaTabBundle.fromRecord(JsonObject(mapOf(
            "name" to JsonPrimitive("alphatab-1.8.4-0123456789abcdef.js"), "integrity" to JsonPrimitive("sha256-x"),
            "script_source" to JsonPrimitive("'sha256-x'"), "font_face" to JsonPrimitive("'sha256-y'"),
        )))
        assertEquals("/assets/alphatab/alphatab-1.8.4-0123456789abcdef.js", at.href)
        assertEquals(0, at.body.size)
        library(alphaTab = at) { test, path ->
            val page = test.get(target(path))
            assertEquals(200, page.status)
            assertTrue("<script src=\"${at.href}\" integrity=\"sha256-x\" crossorigin=\"anonymous\"></script>" in page.text)
            assertTrue("script-src 'sha256-x' " in page.header("Content-Security-Policy")!!)
            // The server holds no bytes of it: the WebView's interceptor answers the page's request (AlphaTabAssets).
            assertEquals(404, test.get(at.href).status)
        }
    }

    @Test fun thePageIsCaracoleServesWithThePhonesBadgeAndTheBundlesHash() {
        val at = AlphaTabBundle.load(STANDINS)
        library(alphaTab = at, name = LibraryName.phone("Music")) { test, path ->
            val page = test.get(target(path))
            assertEquals(200, page.status)
            assertEquals("sandbox allow-scripts allow-downloads; ${GuitarPage.policy(at)}; frame-ancestors 'none'",
                         page.header("Content-Security-Policy"))
            assertTrue("<title>Phone · Synthetic Étude · Guitar Pro 1 · caracole · Music</title>" in page.text)
            assertTrue("href=\"/caracole%20tests/Synthetic%20%C3%89tude/guitar-1.gp\" download>Download<" in page.text)
            val bundle = test.get(at.href)
            assertEquals(200, bundle.status)
            assertEquals("*", bundle.header("Access-Control-Allow-Origin"))
            assertEquals("text/javascript; charset=utf-8", bundle.header("Content-Type"))
            assertEquals("public, max-age=31536000, immutable", bundle.header("Cache-Control"))
            assertTrue(bundle.bytes.contentEquals(at.body))
        }
    }

    @Test fun aPathInThePhonesStateFolderIsNeverReadEvenWhereTheStateIsInTheLibrary() {
        val at = AlphaTabBundle.load(STANDINS)
        library(alphaTab = at, state = "library/caracole tests") { test, path ->
            val refused = test.get(target(path))
            assertEquals(404, refused.status)
            assertEquals(JsonPrimitive("That Guitar Pro file isn't in the library any more: the next caracole run " +
                                       "fetches it again, or files it from the inbox."), refused.data?.get("error"))
        }
    }

    @Test fun aFileOnlyTheMirrorHoldsIsTheFileItselfAndAnyOtherIsNoGuitarProFileTheLibraryKeeps() {
        // A song only the computer's pages copied to the phone have: its Guitar Pro link goes to the file, which the
        // app hands to another app, as before the phone had the page; a page of the mirror's is no file.
        val dir = tmp.newFolder()
        val mirror = Mirror(File(dir, "mirror")).apply { blobs.mkdirs() }
        val gp = "Traditional/Greensleeves/guitar-1.gp"
        val entries = listOf(gp to "application/octet-stream", "Traditional/Greensleeves/sheet.html" to "text/html; charset=utf-8",
                             "index.html" to "text/html; charset=utf-8")
            .map { (path, type) ->
                val bytes = path.toByteArray()
                val sha = java.security.MessageDigest.getInstance("SHA-256").digest(bytes).joinToString("") { "%02x".format(it) }
                File(mirror.blobs, sha).writeBytes(bytes)
                "{\"path\": \"$path\", \"url\": \"/$path\", \"size\": ${bytes.size}, \"sha256\": \"$sha\", \"type\": \"$type\", \"headers\": {}}"
            }
        mirror.manifestFile.writeText("{\"format\": 1, \"start\": \"index.html\", \"files\": [${entries.joinToString(", ")}]}")
        assertNotNull(mirror.reload())
        TestApp(dir, modules = { db ->
            val parts = TestParts.of(db, dir, scope)
            listOf(GuitarRoutes(io.github.danielhp95.caracole.server.PhoneParts(
                parts.database, parts.store, parts.stateDir, parts.config, parts.queue,
                PhonePageData(MirrorPageData(mirror), parts.store), parts.clients, parts.pages,
                parts.songbooks, parts.alerts, parts.pacing, parts.searchesLacuerda), alphaTab = { AlphaTabBundle.load(STANDINS) }))
        }).use { test ->
            val file = test.get(target(gp))
            assertEquals(303, file.status)
            assertEquals("/Traditional/Greensleeves/guitar-1.gp", file.header("Location"))
            for (other in listOf("Traditional/Greensleeves/sheet.html", "Traditional/Greensleeves/guitar-2.gp")) {
                val refused = test.get(target(other))
                assertEquals(404, refused.status, other)
                assertEquals(JsonPrimitive("Not a Guitar Pro file in the book."), refused.data?.get("error"))
            }
        }
    }

    @Test fun aNumberPastAnIntIsKeptInItsWholeOrderAndLabelAndOnePastPythonsDigitsRaisesAsInt() {
        // GuitarFiles.of (phone-render's port, this lane's declaration): Python's int has no bound, so a name past an
        // Int is a file still, ordered and labelled by its whole N; its Int `number` is Int.MAX_VALUE.
        val dir = tmp.newFolder()
        val at = AlphaTabBundle.load(STANDINS)
        TestApp(dir, modules = { db -> listOf(GuitarRoutes(TestParts.of(db, dir, scope), alphaTab = { at }, libraryName = { LibraryName.phone("") })) }).use { test ->
            val store = LibraryStore(test.libraryDir)
            test.database.writeBlocking { db ->
                val song = store.add(db, "caracole tests", "Numbers", now = STAMP)
                for ((tab, name) in listOf("1" to "guitar-2147483648.gp5", "2" to "guitar-2147483647.gp5", "3" to "guitar-1.gp")) {
                    val version = Versions.upsert(db, "gtptabs", tab, song.id, "guitar", "guitar-pro", 4.0, 0, 1, null,
                                                  "https://gtptabs.com/tabs/$tab.html", JsonObject(emptyMap()), STAMP)
                    Kept.keepFile(db, store, song, version, name, SYNTHETIC + name.toByteArray(), 1, STAMP)
                }
            }
            val found = test.database.read { db -> GuitarFiles.of(db) }
            assertEquals(listOf("guitar-1.gp", "guitar-2147483647.gp5", "guitar-2147483648.gp5"), found.map { it.name })
            assertEquals(listOf(1, Int.MAX_VALUE, Int.MAX_VALUE), found.map { it.number })
            assertEquals(listOf("1", "2147483647", "2147483648"), found.map { it.wholeNumber.toString() })
            val page = test.get(target(found.last().path))
            assertEquals(200, page.status)
            assertTrue("<title>Phone · Numbers · Guitar Pro 2147483648 · caracole</title>" in page.text, page.text.take(2000))
            test.database.writeBlocking { db ->
                val song = store.add(db, "caracole tests", "Too Many Digits", now = STAMP)
                val version = Versions.upsert(db, "gtptabs", "9", song.id, "guitar", "guitar-pro", 4.0, 0, 1, null,
                                              "https://gtptabs.com/tabs/9.html", JsonObject(emptyMap()), STAMP)
                db.execute("INSERT INTO files (version_id, song_id, name, path, sha256, kept_rank, created_at) " +
                           "VALUES (?, ?, ?, ?, ?, 1, ?)", version, song.id, "guitar-" + "1".repeat(4301) + ".gp5",
                           "caracole tests/Too Many Digits/x.gp5", "0".repeat(64), STAMP)
            }
            val raised = assertFailsWith<IllegalArgumentException> { test.database.read { db -> GuitarFiles.of(db) } }
            assertTrue("Exceeds the limit (4300 digits)" in raised.message!!, raised.message)
        }
    }

    /** A library of one song keeping the synthetic Guitar Pro file, served by GuitarRoutes alone with [alphaTab] (none:
     * the installed one, which the JVM hasn't got), the library named [name], the phone's state at [state]. */
    private fun library(alphaTab: AlphaTab? = null, name: LibraryName = LibraryName.phone(""), state: String = "state",
                        body: (TestApp, String) -> Unit) {
        val dir = tmp.newFolder()
        TestApp(dir, modules = { db ->
            val parts = TestParts.of(db, dir, scope)
            val withState = io.github.danielhp95.caracole.server.PhoneParts(
                parts.database, parts.store, File(dir, state).apply { mkdirs() }, parts.config, parts.queue, parts.cards,
                parts.clients, parts.pages, parts.songbooks, parts.alerts, parts.pacing, parts.searchesLacuerda)
            listOf(if (alphaTab == null) GuitarRoutes(withState, libraryName = { name })
                   else GuitarRoutes(withState, alphaTab = { alphaTab }, libraryName = { name }))
        }, libraryName = name.name).use { test ->
            val store = LibraryStore(test.libraryDir)
            val path = test.database.writeBlocking { db ->
                val song = store.add(db, "caracole tests", "Synthetic Étude", now = STAMP)
                val version = Versions.upsert(db, "gtptabs", "12", song.id, "guitar", "guitar-pro", 4.0, 0, 1, null,
                                              "https://gtptabs.com/tabs/12.html", JsonObject(emptyMap()), STAMP)
                Kept.keepFile(db, store, song, version, "guitar-1.gp", SYNTHETIC, 1, STAMP)
                db.one("SELECT path FROM files WHERE song_id = ?", song.id) { it.text(0)!! }!!
            }
            body(test, path)
        }
    }

    private fun target(path: String) = "/guitar?file=" + URLEncoder.encode(path, Charsets.UTF_8)

    private companion object {
        const val STAMP = "2026-10-01T00:00:00Z"
        val SYNTHETIC: ByteArray = File(System.getProperty("caracole.fixtures"), "guitar/synthetic.gp").readBytes()
        val STANDINS = mapOf(AlphaTabBundle.LIBRARY to "window.alphaTab = {};".toByteArray(),
                             AlphaTabBundle.FONT to byteArrayOf(1, 2, 3), AlphaTabBundle.SOUND_FONT to byteArrayOf(4, 5))
    }
}
