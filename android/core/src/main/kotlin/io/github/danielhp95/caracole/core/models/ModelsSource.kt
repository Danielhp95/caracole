package io.github.danielhp95.caracole.core.models

import io.github.danielhp95.caracole.core.catalogues.CatalogueError
import io.github.danielhp95.caracole.core.catalogues.CatalogueSource
import io.github.danielhp95.caracole.core.catalogues.Catalogues
import io.github.danielhp95.caracole.core.catalogues.Limited
import io.github.danielhp95.caracole.core.catalogues.Listed
import io.github.danielhp95.caracole.core.catalogues.NoRelease
import io.github.danielhp95.caracole.core.catalogues.download
import io.github.danielhp95.caracole.core.catalogues.refusal
import io.github.danielhp95.caracole.core.index.Sizes
import io.github.danielhp95.caracole.mirror.Http
import java.io.File
import java.io.FileOutputStream
import java.io.IOException
import java.io.InputStream
import java.net.URI
import java.nio.channels.FileChannel
import java.nio.file.Files
import java.nio.file.StandardCopyOption
import java.nio.file.StandardOpenOption
import java.security.SecureRandom

/** Why the chord models can't be downloaded, in words the app says as they are (a [Limited], GitHub's hourly share
 * spent, is the catalogues' own, its time for the caller to keep). */
class ModelsError(message: String, cause: Throwable? = null) : CatalogueError(message, cause)

/** What [ModelsSource.fetch] came to: the [pins] installed in [dir], [fetched] the files it downloaded (none for a
 * folder already whole), [bytes] downloaded. */
class Installed(val dir: File, val pins: Pins, val fetched: List<String>, val bytes: Long)

/**
 * The chord models downloaded at a tap (the design's §6), on core.catalogues' code: GitHub's REST API at [base]
 * alone, caracole's user agent (the [Http] given), a redirect followed only to one of [redirects]
 * (`release-assets.githubusercontent.com`, an asset's bytes), a 403 or 429 with none of the hour's requests left a
 * [Limited]. [pins] are models.json's, [free] the room on a disk, [app] the app's own files (BTC's graph). No BTC
 * weights are re-hosted: BTC's authors' file is read from their repository, unchanged.
 */
class ModelsSource(
    private val base: URI = URI("https://api.github.com"),
    private val redirects: Set<String> = Catalogues.API_REDIRECTS,
    private val pins: () -> Pins = ModelFiles::read,
    private val free: (File) -> Long = File::getUsableSpace,
    private val app: (String) -> InputStream? = { ModelFiles.resource("caracole/autochords/$it") },
) {
    /**
     * [into] (a [Pins.folder]) made to hold every pinned file whole, [onProgress] told the bytes downloaded so far and
     * of how many. What a fetch cut off left beside it goes first ([ModelFiles.sweep]); a folder already
     * [ModelFiles.installed] asks nothing. Else each file already there whole (its SHA-256 hashed) is kept, the
     * graph copied from the app, and only the files missing asked for:
     *
     * 1. beat_this's: `GET /repos/{REPO}/releases/tags/models` (the release listed), then its asset's API address
     *    with `Accept: application/octet-stream`, redirected once to `release-assets.githubusercontent.com`;
     * 2. BTC's: `GET /repos/jayg996/BTC-ISMIR19/git/blobs/<sha>` with `Accept: application/vnd.github.raw+json`, the
     *    raw bytes answered by the API itself (a redirect is refused, never followed).
     *
     * Each downloaded exactly its pinned size and checked by its SHA-256 (the asset's as GitHub lists it too), into
     * a folder of its own beside [into], each file fsynced, the manifest last; then that folder renamed into place,
     * the old one put aside and deleted. Any refusal ([ModelsError], [Limited], a [CatalogueError] of the download's)
     * leaves [into] as it was and the folder being written deleted; no room for twice the download and [MARGIN] asks
     * nothing.
     */
    fun fetch(http: Http, into: File, onProgress: (Long, Long) -> Unit): Installed {
        val pins = pins()
        ModelFiles.sweep(into)
        if (ModelFiles.installed(into, pins) == null) return Installed(into, pins, emptyList(), 0)
        val whole = pins.files.filter { pin -> there(into, pin) }.toSet()
        // The release's first: one not published is said before BTC's 12 MB are asked for.
        val asked = pins.files.filter { it !in whole && it.from is From.Release } +
            pins.files.filter { it !in whole && it.from is From.Blob }
        val total = asked.sumOf { it.bytes }
        val parent = into.absoluteFile.parentFile
        storage { if (!parent.isDirectory) Files.createDirectories(parent.toPath()) }
        val room = free(parent)
        val needs = 2 * total + MARGIN
        if (asked.isNotEmpty() && room < needs) {
            throw ModelsError(NO_ROOM.replace("{needs}", Sizes.size(needs)).replace("{has}", Sizes.size(room)))
        }
        val part = File(parent, "." + into.name + "-" + token() + ModelFiles.PART)
        try {
            storage { Files.createDirectory(part.toPath()) }
            for (pin in whole) storage { keep(File(into, pin.name), File(part, pin.name)) }
            for (pin in pins.files.filter { it !in whole && it.from is From.App }) fromApp(pin, File(part, pin.name))
            var before = 0L
            for (pin in asked) {
                val to = File(part, pin.name)
                val progress: (Long) -> Unit = { got -> onProgress(before + got, total) }
                when (val from = pin.from) {
                    is From.Release -> fromRelease(http, pins.release, from, pin, to, progress)
                    is From.Blob -> fromBlob(http, from, pin, to, progress)
                    From.App -> Unit
                }
                before += pin.bytes
            }
            storage {
                ModelFiles.writeManifest(part, pins)
                sync(part)
            }
            check(ModelFiles.installed(part, pins) == null) { "the chord models' folder isn't whole as written" }
            place(part, into)
        } catch (e: Throwable) {
            part.deleteRecursively()
            throw e
        }
        return Installed(into, pins, asked.map { it.name }, total)
    }

    /** Whether [into] holds [pin]'s file whole: a regular file of its size and its SHA-256, hashed. */
    private fun there(into: File, pin: Pin): Boolean {
        val file = File(into, pin.name)
        return try {
            ModelFiles.regular(file) && file.length() == pin.bytes && ModelFiles.sha256(file) == pin.sha256
        } catch (e: IOException) {
            false
        }
    }

    /** [from], a file checked whole, kept in [to]: a hard link, else a copy, fsynced. */
    private fun keep(from: File, to: File) {
        try {
            Files.createLink(to.toPath(), from.toPath())
        } catch (e: UnsupportedOperationException) {
            copy(from, to)
        } catch (e: IOException) {
            copy(from, to)
        }
    }

    private fun copy(from: File, to: File) {
        Files.deleteIfExists(to.toPath())
        from.inputStream().use { input ->
            FileOutputStream(to).use { out ->
                input.copyTo(out, 1 shl 20)
                out.fd.sync()
            }
        }
    }

    /** BTC's graph, the app's own, written into [to] and checked: another than the pinned one is a bug. */
    private fun fromApp(pin: Pin, to: File) {
        val input = app(pin.name) ?: throw IllegalStateException("this build carries no ${pin.name}")
        storage { input.use { i -> FileOutputStream(to).use { out -> i.copyTo(out, 1 shl 20); out.fd.sync() } } }
        check(to.length() == pin.bytes && ModelFiles.sha256(to) == pin.sha256) {
            "this build's ${pin.name} isn't the one models.json pins"
        }
    }

    /** The release listed (one request), its asset found as pinned, then its bytes (one, and its redirect's hop). */
    private fun fromRelease(http: Http, tag: String, from: From.Release, pin: Pin, to: File, progress: (Long) -> Unit) {
        val listed = try {
            CatalogueSource.Api(http, base, redirects, tag).list()
        } catch (e: NoRelease) {
            throw ModelsError(NOT_PUBLISHED.replace("{tag}", tag))
        }
        val asset = listed.firstOrNull { it.name == from.asset }
            ?: throw ModelsError(NOT_LISTED.replace("{tag}", tag).replace("{name}", from.asset))
        if (!asset.uploaded) throw ModelsError(NOT_UPLOADED.replace("{tag}", tag))
        if (asset.bytes != pin.bytes || asset.sha256 != pin.sha256) throw ModelsError(OTHER_ASSET.replace("{tag}", tag))
        download(http, asset, to, redirects, gzip = false, onProgress = progress)
    }

    /** BTC's authors' file, its git blob asked of GitHub's API as its raw bytes (one request); a 404, a 403 that isn't
     * the hour's share spent, or a redirect (a repository renamed) is [BTC_GONE]. */
    private fun fromBlob(http: Http, from: From.Blob, pin: Pin, to: File, progress: (Long) -> Unit) {
        val url = base.toString().removeSuffix("/") + "/repos/${from.repository}/git/blobs/${from.blob}"
        val file = Listed(pin.name, pin.bytes, pin.sha256, true, url)
        download(http, file, to, emptySet(), gzip = false, accept = RAW, refused = { answer ->
            val gone = answer.status == 404 || answer.status in 300..399 ||
                (answer.status == 403 && refusal(answer) !is Limited)
            if (gone) {
                ModelsError(BTC_GONE.replace("{repository}", from.repository).replace("{status}", "${answer.status}"))
            } else {
                null
            }
        }, onProgress = progress)
    }

    /** [part] in [into]'s place: [into], when there, put aside first and deleted after; put back should the rename
     * fail. */
    private fun place(part: File, into: File) = storage {
        val aside = File(part.parentFile, "." + into.name + "-" + token() + ModelFiles.OLD)
        val had = into.exists()
        if (had) Files.move(into.toPath(), aside.toPath(), StandardCopyOption.ATOMIC_MOVE)
        try {
            Files.move(part.toPath(), into.toPath(), StandardCopyOption.ATOMIC_MOVE)
        } catch (e: IOException) {
            if (had) Files.move(aside.toPath(), into.toPath(), StandardCopyOption.ATOMIC_MOVE)
            throw e
        }
        sync(into.absoluteFile.parentFile)
        if (had) aside.deleteRecursively()
    }

    /** [dir]'s entries made durable, where the platform lets a folder be opened so (Linux, Android). */
    private fun sync(dir: File) {
        try {
            FileChannel.open(dir.toPath(), StandardOpenOption.READ).use { it.force(true) }
        } catch (e: IOException) {
            // A folder that can't be opened to be synced: its files are, each.
        }
    }

    private inline fun <T> storage(block: () -> T): T = try {
        block()
    } catch (e: IOException) {
        throw ModelsError("The phone's storage failed: ${e.message ?: e.javaClass.simpleName}.", e)
    }

    private fun token(): String = ModelFiles.hex(ByteArray(8).also(RANDOM::nextBytes))

    companion object {
        /** BTC's blob asked for as its raw bytes: GitHub's documented media type for "Get a blob" (up to 100 MB). */
        const val RAW = "application/vnd.github.raw+json"

        /** The room a download needs beyond twice its bytes: the folder being written and the one it replaces. */
        const val MARGIN = 32L shl 20

        private val RANDOM = SecureRandom()

        const val NO_ROOM = "The chord models need about {needs} free; the phone has {has}."
        const val NOT_PUBLISHED =
            "The chord models aren't published yet: caracole's GitHub release “{tag}” isn't there."
        const val NOT_LISTED =
            "The chord models aren't published yet: caracole's GitHub release “{tag}” has no {name}."
        const val NOT_UPLOADED = "beat_this's file on caracole's GitHub release “{tag}” isn't whole yet; nothing was " +
            "downloaded. Try again later."
        const val OTHER_ASSET = "beat_this's file on caracole's GitHub release “{tag}” isn't the one this caracole " +
            "works with; nothing was downloaded. Update the app."
        const val BTC_GONE = "BTC's weights aren't in their authors' repository on GitHub any more ({repository} " +
            "answered HTTP {status}); nothing was downloaded. Update the app; if it still says so, tell caracole's " +
            "author."
    }
}
