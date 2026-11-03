package io.github.danielhp95.caracole

import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import java.io.ByteArrayInputStream
import java.io.File
import java.io.IOException
import java.io.InputStream
import java.security.MessageDigest
import kotlin.test.assertContentEquals
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith
import kotlin.test.assertFalse
import kotlin.test.assertTrue

/** The copy another app reads: the file the server answered, named for its song, under the cache's handoff/. */
class HandoffTest {
    @get:Rule val folder = TemporaryFolder()

    private fun fetched(bytes: ByteArray, type: String = "application/pdf") =
        Fetched.File(type, bytes.size.toLong()) { ByteArrayInputStream(bytes) }

    private fun sha256(bytes: ByteArray) = MessageDigest.getInstance("SHA-256").digest(bytes).joinToString("") { "%02x".format(it) }

    @Test
    fun `a file is copied under its bytes' hash, named for its path, and its bytes are the server's`() {
        val root = folder.newFolder("handoff")
        val pdf = "%PDF-1.7 Tu calorro".toByteArray()
        val copy = Handoff.copyInto(root, "Estopa/Tu calorro/sheet.pdf", fetched(pdf), now = 1_000L)
        assertEquals(File(File(root, sha256(pdf)), "Estopa - Tu calorro - sheet.pdf"), copy)
        assertContentEquals(pdf, copy.readBytes())
        assertEquals(listOf(sha256(pdf)), root.list()!!.toList(), "no temporary file left")
    }

    @Test
    fun `the same file again is the copy there is, and another is a copy of its own`() {
        val root = folder.newFolder("handoff")
        val one = Handoff.copyInto(root, "A/B/sheet.pdf", fetched("one".toByteArray()), now = 1_000L)
        val again = Handoff.copyInto(root, "A/B/sheet.pdf", fetched("one".toByteArray()), now = 2_000L)
        assertEquals(one, again)
        val other = Handoff.copyInto(root, "A/B/sheet.pdf", fetched("two".toByteArray()), now = 3_000L)
        assertTrue(other != one)
        assertContentEquals("two".toByteArray(), other.readBytes())
        assertTrue(one.isFile, "a copy another app may still be reading stays")
    }

    @Test
    fun `copies a day old go, and a copy cut short leaves nothing`() {
        val root = folder.newFolder("handoff")
        val old = Handoff.copyInto(root, "A/B/old.pdf", fetched("old".toByteArray()), now = 0L)
        old.parentFile!!.setLastModified(0L)
        Handoff.copyInto(root, "A/B/new.pdf", fetched("new".toByteArray()), now = 25 * 60 * 60 * 1000L)
        assertFalse(old.exists())

        val broken = Fetched.File("application/pdf", 10) {
            object : InputStream() {
                var sent = 0
                override fun read(): Int = if (sent++ < 3) 'x'.code else throw IOException("the file went")
            }
        }
        assertFailsWith<IOException> { Handoff.copyInto(root, "A/B/cut.pdf", broken, now = 25 * 60 * 60 * 1000L) }
        assertEquals(1, root.list()!!.size, "only the new copy: ${root.list()!!.toList()}")
    }

    @Test
    fun `a file's name is its path's parts, or its own name when they are too long`() {
        assertEquals("Estopa - Tu calorro - sheet.pdf", Handoff.fileName("Estopa/Tu calorro/sheet.pdf"))
        val long = "a".repeat(150) + "/" + "b".repeat(150) + "/guitar-1.gp5"
        assertEquals("guitar-1.gp5", Handoff.fileName(long))
    }
}
