package io.github.danielhp95.caracole.mirror

import java.io.IOException
import java.security.MessageDigest

/** How far a sync is: [done] of the [total] files it downloads. */
data class Progress(val done: Int, val total: Int)

/** caracole's list as fetched: its [bytes], as the server sent them, and what they say. */
class Fetched(val bytes: ByteArray, val manifest: Manifest)

/**
 * What a sync did: the mirror now holds [files] files ([bytes] in all); [added], [changed] and [removed]
 * count paths against the list before, [downloaded] the files fetched, and [skipped] names the entries left
 * out for breaking the contract.
 */
data class SyncReport(
    val files: Int,
    val bytes: Long,
    val added: Int,
    val changed: Int,
    val removed: Int,
    val downloaded: Int,
    val skipped: List<String>,
) {
    /** "12 files new, 2 removed", or "nothing changed"; with the entries skipped, if any. */
    fun summary(): String {
        val parts = buildList {
            if (added > 0) add("$added ${if (added == 1) "file" else "files"} new")
            if (changed > 0) add("$changed changed")
            if (removed > 0) add("$removed removed")
        }
        val said = if (parts.isEmpty()) "nothing changed" else parts.joinToString(", ")
        return if (skipped.isEmpty()) said else "$said; ${skipped.size} left out (the server listed them wrong)"
    }
}

/**
 * Fills a [Mirror] from caracole serve's list (`GET /api/offline`).
 *
 * A sync gets the list; downloads each file whose blob the mirror lacks into a temporary file, checking its
 * size (a file longer than listed is cut off and fails) and its SHA-256 before renaming it to its blob; once
 * every entry has its blob, writes the list whole over `manifest.json` (a temporary file renamed), so a sync
 * cut short leaves the mirror before it whole and readable; then deletes the blobs no entry names and every
 * temporary file. A failed download fails the sync and keeps the mirror as it was.
 */
class SyncEngine(private val mirror: Mirror, private val http: Http = Http()) {

    /** caracole's list at [address], read and checked; [SyncError] when there is none to use. */
    fun fetchManifest(address: ServerAddress): Fetched {
        val bytes = http.get(address, address.manifest) { answer ->
            when {
                answer.status == 503 -> throw SyncError.Unavailable(address, unavailable(answer))
                answer.status == 404 -> throw SyncError.NotCaracole(address, "it has no ${ServerAddress.MANIFEST_PATH}")
                answer.status in 300..399 -> throw SyncError.NotCaracole(address, "it redirects ${ServerAddress.MANIFEST_PATH} elsewhere")
                answer.status != 200 -> throw SyncError.NotCaracole(address, "it answered HTTP ${answer.status}")
            }
            readAtMost(answer.body, MAX_MANIFEST_BYTES)
                ?: throw SyncError.BadManifest("it is longer than ${MAX_MANIFEST_BYTES / (1024 * 1024)} MB")
        }
        return Fetched(bytes, Manifest.parse(bytes, address))
    }

    /**
     * Syncs the mirror with [address]'s list, asked for once the sync holds the mirror's lock: a sync that waited
     * for another syncs the list as it is then, never one older than the other's. [progress] hears how many
     * files are downloaded; [cancelled] is asked between two pieces of work, and stops the sync when true.
     */
    fun sync(
        address: ServerAddress,
        progress: (Progress) -> Unit = {},
        cancelled: () -> Boolean = { false },
    ): SyncReport {
        mirror.syncLock.lock()
        try {
            val list = fetchManifest(address)
            val manifest = list.manifest
            val before = mirror.reload()
            var downloaded = 0
            try {
                mirror.blobs.mkdirs()
                mirror.removeTemporaries()
                if (!mirror.blobs.isDirectory) throw SyncError.Storage("the folder ${mirror.blobs} can't be made")

                // Each content once: two paths with the same bytes share a blob.
                val missing = manifest.entries.distinctBy { it.sha256 }.filter { !mirror.blob(it.sha256).isFile }
                progress(Progress(0, missing.size))
                missing.forEachIndexed { i, entry ->
                    if (cancelled()) throw SyncError.Cancelled()
                    download(address, entry)
                    downloaded++
                    progress(Progress(i + 1, missing.size))
                }
                if (cancelled()) throw SyncError.Cancelled()
                if (manifest.entries.any { !mirror.blob(it.sha256).isFile }) {
                    throw SyncError.Storage("a file downloaded is gone from the phone's storage")
                }
                mirror.swapManifest(list.bytes)
            } catch (e: IOException) {
                throw SyncError.Storage(e.message ?: e.javaClass.simpleName, e)
            } finally {
                mirror.removeTemporaries()
            }
            mirror.reload()
            mirror.cleanUp(manifest)

            val old = before?.byPath ?: emptyMap()
            return SyncReport(
                files = manifest.entries.size,
                bytes = manifest.bytes,
                added = manifest.entries.count { it.path !in old },
                changed = manifest.entries.count { e -> old[e.path]?.let { it.sha256 != e.sha256 } ?: false },
                removed = old.keys.count { it !in manifest.byPath },
                downloaded = downloaded,
                skipped = manifest.skipped,
            )
        } finally {
            mirror.syncLock.unlock()
        }
    }

    /** Downloads [entry] to its blob, checked: [SyncError.Changed] when its bytes aren't the listed ones. */
    private fun download(address: ServerAddress, entry: Entry) {
        val tmp = mirror.newTemporary()
        try {
            http.get(address, address.resolve(entry.url)) { answer ->
                if (answer.status != 200) throw SyncError.Changed(entry.path, "the server answered HTTP ${answer.status}")
                if (answer.contentLength >= 0 && answer.contentLength != entry.size) {
                    throw SyncError.Changed(entry.path, "it is ${answer.contentLength} bytes, not ${entry.size}")
                }
                val digest = MessageDigest.getInstance("SHA-256")
                var total = 0L
                // Reading fails as the connection does (Http's NoAnswer), writing as the phone's storage does.
                storage { tmp.outputStream() }.use { out ->
                    val buffer = ByteArray(64 * 1024)
                    while (true) {
                        // One byte more than listed at most: enough to know it is longer. (total is never more
                        // than the size here, so this never overflows, even for the largest size a list gives.)
                        val room = (entry.size - total).coerceAtMost(buffer.size.toLong() - 1).toInt() + 1
                        val n = answer.body.read(buffer, 0, room)
                        if (n < 0) break
                        total += n
                        if (total > entry.size) throw SyncError.Changed(entry.path, "it is longer than ${entry.size} bytes")
                        digest.update(buffer, 0, n)
                        storage { out.write(buffer, 0, n) }
                    }
                    storage { out.fd.sync() }
                }
                if (total != entry.size) throw SyncError.Changed(entry.path, "it is $total bytes, not ${entry.size}")
                val sha256 = digest.digest().joinToString("") { "%02x".format(it) }
                if (sha256 != entry.sha256) throw SyncError.Changed(entry.path, "its bytes aren't the ones listed")
            }
            Mirror.moveOver(tmp, mirror.blob(entry.sha256))
        } finally {
            tmp.delete()
        }
    }

    /** caracole's reason in a 503's `{"error": "..."}`, or the status alone. */
    private fun unavailable(answer: Http.Answer): String {
        val said = readAtMost(answer.body, 64 * 1024)?.let { bytes ->
            try {
                (Json.parse(String(bytes, Charsets.UTF_8)) as? Map<*, *>)?.get("error") as? String
            } catch (e: Json.Malformed) {
                null
            }
        }
        return said?.trim()?.takeIf { it.isNotEmpty() }?.take(500) ?: "it answered HTTP 503"
    }

    private inline fun <T> storage(write: () -> T): T = try {
        write()
    } catch (e: IOException) {
        throw SyncError.Storage(e.message ?: e.javaClass.simpleName, e)
    }

    companion object {
        const val MAX_MANIFEST_BYTES = 64 * 1024 * 1024

        /** The whole of [input] if it holds at most [limit] bytes, else null. */
        private fun readAtMost(input: java.io.InputStream, limit: Int): ByteArray? {
            val out = java.io.ByteArrayOutputStream()
            val buffer = ByteArray(64 * 1024)
            var total = 0L
            while (true) {
                val n = input.read(buffer)
                if (n < 0) return out.toByteArray()
                total += n
                if (total > limit) return null
                out.write(buffer, 0, n)
            }
        }
    }
}

