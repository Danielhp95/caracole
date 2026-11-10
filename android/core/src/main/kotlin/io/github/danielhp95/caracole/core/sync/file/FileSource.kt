package io.github.danielhp95.caracole.core.sync.file

import io.github.danielhp95.caracole.core.db.Database
import io.github.danielhp95.caracole.core.json.Canonical
import io.github.danielhp95.caracole.core.json.CanonicalError
import io.github.danielhp95.caracole.core.sync.PeerError
import io.github.danielhp95.caracole.core.sync.Scope
import io.github.danielhp95.caracole.core.sync.UnitSource
import io.github.danielhp95.caracole.core.sync.internal.client.Give
import kotlinx.serialization.json.JsonObject
import java.io.ByteArrayInputStream
import java.io.File
import java.io.IOException
import java.io.InputStream
import java.nio.file.Files
import java.nio.file.StandardOpenOption

/**
 * peer_file.FileSource on the phone: a file's units as Take.applyUnits takes them, as it takes the computer's (its
 * [UnitSource], as PeerClient is): each unit's document from `units.jsonl`, each kept file from `files/`, else a copy
 * kept here (the phone's own files, by SHA-256: [database]'s, under [libraryDir]), checked by its SHA-256; and its
 * indexes ([indexes]) and pages ([pages], [page]). Every failure is a [PeerError] in the owner's words, which a take
 * leaves its unit for, never reads as a removal. Holds the file open until closed.
 */
class FileSource(val syncFile: SyncFile, private val database: Database?, private val libraryDir: File) :
    UnitSource, AutoCloseable {
    private var zip: Zip? = null
    private var read: Map<String, JsonObject>? = null

    private fun opened(): Zip = zip ?: try {
        Zip.open(syncFile.file).also { zip = it }
    } catch (e: Exception) {
        if (!Zip.unopened(e)) throw e
        throw PeerError(FileError.unreadable(e.message ?: e.javaClass.simpleName), cause = e)
    }

    /** A member's bytes, at most [most]; null for a member the file hasn't got. */
    private fun bytes(name: String, most: Long): ByteArray? {
        val member = opened().member(name) ?: return null
        if (member.size > most) throw PeerError(FileError.unreadable("$name is bigger than it may be"))
        return try {
            opened().read(member, most)
        } catch (e: Zip.Damaged) {
            throw PeerError(FileError.unreadable(if (e.tooBig) "$name is bigger than it may be" else "$name: ${e.message}"))
        }
    }

    /** The unit documents it holds, by unit id (`units.jsonl`'s, checked as SyncFiles.checkWhole checks them). */
    fun documents(): Map<String, JsonObject> {
        if (syncFile.indexOnly) return emptyMap()
        read?.let { return it }
        val found = try {
            SyncFiles.documents(opened(), syncFile.state!!)
        } catch (e: FileError) {
            throw PeerError(e.message!!, cause = e)
        }
        read = found
        return found
    }

    /** The unit's document, as `GET /api/peer/unit`'s `"unit"`; null for a unit of a part the file holds that its
     * state doesn't name (its caracole hasn't got it: a song it removed); a PeerError for a unit its state names that
     * it holds no document of (left out as it was exported) and for one of a part it doesn't hold, which a take must
     * leave as it is, never take as gone. */
    /** Whether [unit] answers [id] (its document, or none for a unit its library hasn't got), never a PeerError:
     * false for a unit the file names but left out as it was exported, or of a part it doesn't hold. */
    fun says(id: String): Boolean =
        id in documents() || (syncFile.state?.units?.containsKey(id) != true && Scope.partOf(id) in syncFile.holds)

    override fun unit(id: String): JsonObject? {
        documents()[id]?.let { return it["unit"] as JsonObject }
        val state = syncFile.state
        if (state != null && id in state.units) {
            throw PeerError("the file names it but doesn't hold it: it was left out as it was exported (a file it " +
                                "keeps had changed there, or was too big for it)")
        }
        if (Scope.partOf(id) in syncFile.holds && '/' in id) return null
        throw PeerError("the file doesn't hold that part of its library, so it says nothing of it")
    }

    /** A kept file of the song of [songKey], by its SHA-256: from the file, or kept here; a PeerError else. */
    override fun file(songKey: String, name: String, sha256: String): ByteArray {
        if (!SHA256.matches(sha256)) throw PeerError("$name: no SHA-256 to find it by")
        val data = bytes(SyncFiles.FILES + sha256, SyncFiles.FILE_MAX)
            ?: database?.let { Give.read(it, libraryDir, sha256) }
        if (data == null || Canonical.sha256Hex(data) != sha256) {
            throw PeerError("$name isn't in the file as its song says, nor kept here: the song is left as it was here.")
        }
        return data
    }

    /** Its indexes copied to [to] (a new file), in chunks; false, nothing written, when it holds none this database
     * can merge (SyncFile.holds). */
    fun indexes(to: File): Boolean {
        if (Scope.INDEXES !in syncFile.holds) return false
        try {
            Files.newOutputStream(to.toPath(), StandardOpenOption.CREATE_NEW, StandardOpenOption.WRITE).use { out ->
                if (syncFile.indexOnly) {
                    syncFile.file.inputStream().use { it.copyTo(out, Zip.CHUNK) }
                } else {
                    val member = opened().member(SyncFiles.INDEXES) ?: run {
                        out.close()
                        to.delete()
                        return false
                    }
                    try {
                        opened().copy(member, out)
                    } catch (e: Zip.Damaged) {
                        throw PeerError(FileError.unreadable("${SyncFiles.INDEXES}: ${e.message}"))
                    }
                }
            }
        } catch (e: Throwable) {
            to.delete()
            if (e is IOException) throw PeerError("The phone's storage failed: ${e.message ?: e.javaClass.simpleName}.", cause = e)
            throw e
        }
        return true
    }

    /** Its `pages.json`, the pages its caracole made of its units; null when it holds none. */
    fun pages(): JsonObject? {
        if (syncFile.indexOnly) return null
        val data = bytes(SyncFiles.PAGES, SyncFiles.JSON_MAX) ?: return null
        val found = try {
            SyncFiles.json(data)
        } catch (e: CanonicalError) {
            throw PeerError(FileError.unreadable("${SyncFiles.PAGES} is no JSON"))
        }
        return found as? JsonObject
    }

    /** A page's bytes, by its SHA-256: under `pages/`, else under `files/` (a page that is a kept file is held once,
     * there); a PeerError when the file holds none of it. */
    fun page(sha256: String): InputStream {
        if (!SHA256.matches(sha256)) throw PeerError("no SHA-256 to find that page by")
        for (folder in listOf(SyncFiles.PAGE_BLOBS, SyncFiles.FILES)) {
            val data = bytes(folder + sha256, SyncFiles.FILE_MAX) ?: continue
            if (Canonical.sha256Hex(data) != sha256) {
                throw PeerError(FileError.unreadable("$folder$sha256 isn't the page its name says"))
            }
            return ByteArrayInputStream(data)
        }
        throw PeerError("the file holds no such page")
    }

    override fun close() {
        zip?.close()
        zip = null
    }

    private companion object {
        val SHA256 = Regex("[0-9a-f]{64}")
    }
}
