package io.github.danielhp95.caracole.server.routes.sync

import java.io.File
import java.nio.file.Files
import java.nio.file.LinkOption
import java.nio.file.StandardCopyOption
import java.util.concurrent.atomic.AtomicBoolean

/**
 * The phone's exports, each a `.caracole` file of this library made for its one download (web/sync_file_routes.py's
 * `_made`, the sync redesign's §3.4.2): made in `stateDir/cache/peer/` ([folder], 0700; the file 0600), never in the
 * library, one at a time ([make]: [Busy] while another is), and sent once ([take]).
 *
 * - [make] writes one through the caller's writer (core.sync.file's export) at `export-<16 hex>.caracole`, and keeps
 *   its id with the name it downloads under, one at most: the one before it, never asked for, is deleted;
 * - [take] gives the file of an id once, never again: it is renamed out of the exports' names (`.sent-<id>…`), so a
 *   second GET finds nothing, and the route answers it streamed from there, its name deleted as the server opens it
 *   to send it (Body.FromFile's `once`: a file open is read whole after its name is gone), as caracole serve deletes
 *   its export as it opens it;
 * - [sweep] (as an export is made, its sizes asked or one taken) deletes an export never asked for an hour after it
 *   was made, a part a writer killed while it made one left (`.export-…`) as long after, and a file taken that no
 *   server opened (a download the app never read) [SENT] after it was taken; then it forgets the exports whose files
 *   are gone;
 * - [clear], as the phone's caracole starts (no export of an earlier one can be asked for: the ids were its), deletes
 *   every file of the exports' names, made, taken or half made.
 *
 * Times are [clock]'s, each file dated by it as it is made or taken.
 */
class Exports(cacheDir: File, private val clock: () -> Long = System::currentTimeMillis) {
    /** `cache/peer/`, as caracole serve makes its exports in its cache_dir's. */
    val folder = File(cacheDir, FOLDER)

    /** An export made: its [id], the [name] it downloads under, its [size] in bytes. */
    data class Made(val id: String, val name: String, val size: Long)

    /** Another export is being made: try again once it is. */
    class Busy : Exception(BUSY)

    private val making = AtomicBoolean(false)
    private val made = LinkedHashMap<String, Pair<File, String>>()

    /**
     * An export made by [write], which writes the file at the path it is given (a new file there: none is), to download
     * as [name]; [Busy] while another is made. What [write] throws is the caller's, with nothing kept.
     */
    fun make(name: String, write: (File) -> Unit): Made {
        if (!making.compareAndSet(false, true)) throw Busy()
        try {
            Imports.privateDir(folder)
            sweep()
            val id = Imports.token()
            val file = File(folder, "$PREFIX$id$SUFFIX")
            try {
                write(file)
                if (!Files.isRegularFile(file.toPath(), LinkOption.NOFOLLOW_LINKS)) throw java.io.IOException("no file was made")
                try {
                    Files.setPosixFilePermissions(file.toPath(), java.nio.file.attribute.PosixFilePermissions.fromString("rw-------"))
                } catch (e: UnsupportedOperationException) {
                    file.setReadable(false, false); file.setReadable(true, true)
                }
                file.setLastModified(clock())
            } catch (e: Throwable) {
                file.delete()
                throw e
            }
            synchronized(made) {
                for ((earlier, _) in made.values) earlier.delete()  // never asked for: this one takes its place
                made.clear()
                made[id] = file to name
            }
            return Made(id, name, file.length())
        } finally {
            making.set(false)
        }
    }

    /** The export [id] names, once: its file (renamed for its one download, deleted [SENT] after) and its name; null for
     * one taken already, swept, or never made. */
    fun take(id: String): Pair<File, String>? {
        sweep()
        if (!Imports.ID.matches(id)) return null
        val (file, name) = synchronized(made) { made.remove(id) } ?: return null
        val sent = File(folder, "$SENT_PREFIX$id$SUFFIX")
        return try {
            Files.move(file.toPath(), sent.toPath(), StandardCopyOption.ATOMIC_MOVE)
            sent.setLastModified(clock())
            sent to name
        } catch (e: java.io.IOException) {
            null
        }
    }

    /** Every file of the exports' names deleted (see the class), unless an export is being made now. */
    fun clear() {
        if (!making.compareAndSet(false, true)) return
        try {
            for (file in folder.listFiles().orEmpty()) {
                val ours = file.name.startsWith(SENT_PREFIX) || file.name.startsWith(".$PREFIX") ||
                    (file.name.startsWith(PREFIX) && file.name.endsWith(SUFFIX))
                if (ours && Files.isRegularFile(file.toPath(), LinkOption.NOFOLLOW_LINKS)) file.delete()
            }
            synchronized(made) { made.clear() }
        } finally {
            making.set(false)
        }
    }

    /** Deletes what [Exports] leaves behind it (see the class), and forgets the exports whose files are gone. */
    fun sweep() {
        val now = clock()
        for (file in folder.listFiles().orEmpty()) {
            val keep = when {
                file.name.startsWith(SENT_PREFIX) -> SENT
                file.name.startsWith(PREFIX) && file.name.endsWith(SUFFIX) -> EXPIRES
                file.name.startsWith(".$PREFIX") -> EXPIRES
                else -> continue
            }
            if (Files.isRegularFile(file.toPath(), LinkOption.NOFOLLOW_LINKS) && now - file.lastModified() > keep) file.delete()
        }
        synchronized(made) { made.entries.removeIf { (_, held) -> !held.first.exists() } }
    }

    companion object {
        const val FOLDER = "peer"
        const val PREFIX = "export-"
        const val SENT_PREFIX = ".sent-"

        /** peer_file.SUFFIX. */
        const val SUFFIX = ".caracole"

        /** An export never asked for, or a part left, is kept this long. */
        const val EXPIRES = 3_600_000L

        /** A file taken that no server opened is kept this long, for the download that opens it. */
        const val SENT = 600_000L

        const val BUSY = "Another export is being made: try again once it is."
    }
}
