package io.github.danielhp95.caracole.mirror

import java.net.URI
import java.net.URISyntaxException
import java.nio.ByteBuffer
import java.nio.charset.CharacterCodingException
import java.nio.charset.CodingErrorAction

/**
 * One file the phone mirrors, as `GET /api/offline` lists it: its [path] in the library (`/`-separated,
 * unescaped, as the written pages link to each other), the [url] on the server that answers its bytes, their
 * [size] and [sha256], the Content-Type the WebView gets for it ([type]), and the [headers] serve sends with
 * it that change how a page behaves (its Content-Security-Policy, with the sandbox).
 */
data class Entry(
    val path: String,
    val url: String,
    val size: Long,
    val sha256: String,
    val type: String,
    val headers: Map<String, String>,
) {
    val mimeType: String get() = ContentType.mimeType(type)
    val charset: String? get() = ContentType.charset(type)
    val isPage: Boolean get() = mimeType == "text/html" || mimeType == "application/xhtml+xml"

    /** The file's name, the last part of its path ("sheet.pdf"). */
    val name: String get() = path.substringAfterLast('/')
}

/**
 * caracole's offline list: the page to open first ([start]) and the files ([entries]); [skipped] says which
 * entries broke the contract and were left out, one line each.
 */
class Manifest(val start: String, val entries: List<Entry>, val skipped: List<String>) {
    val byPath: Map<String, Entry> = entries.associateBy { it.path }

    /** The bytes of every file listed. */
    val bytes: Long get() = entries.sumOf { it.size }

    companion object {
        const val FORMAT = 1

        /** The headers an entry may carry to the WebView; any other is ignored. */
        val HEADERS = listOf("Content-Security-Policy", "Referrer-Policy", "X-Content-Type-Options")

        private val SHA256 = Regex("[0-9a-f]{64}")
        private val MIME = Regex("[A-Za-z0-9][A-Za-z0-9!#$&^_.+-]*/[A-Za-z0-9][A-Za-z0-9!#$&^_.+-]*")

        /**
         * The list in [bytes], the server's answer as it came. [address] names the server in the errors:
         * [SyncError.NotCaracole] for anything that isn't caracole's list (no `format`), [SyncError.NewerFormat]
         * for a format other than [FORMAT], [SyncError.BadManifest] for a list the app can't use whole.
         */
        fun parse(bytes: ByteArray, address: ServerAddress? = null): Manifest {
            val where = address?.toString() ?: "the server"
            fun notCaracole(why: String): Nothing =
                if (address != null) throw SyncError.NotCaracole(address, why) else throw SyncError.BadManifest(why)

            val text = try {
                Charsets.UTF_8.newDecoder()
                    .onMalformedInput(CodingErrorAction.REPORT)
                    .onUnmappableCharacter(CodingErrorAction.REPORT)
                    .decode(ByteBuffer.wrap(bytes)).toString()
            } catch (e: CharacterCodingException) {
                notCaracole("its answer isn't UTF-8 text")
            }
            val root = try {
                Json.parse(text)
            } catch (e: Json.Malformed) {
                notCaracole("its answer isn't JSON: ${e.message}")
            }
            val format = (root as? Map<*, *>)?.get("format")
            if (format !is Long && format !is Double) notCaracole("its answer has no format")
            if (format != FORMAT.toLong()) throw SyncError.NewerFormat(format)
            root as Map<*, *>

            val start = root["start"] as? String ?: throw SyncError.BadManifest("it names no start page ($where)")
            val files = root["files"] as? List<*> ?: throw SyncError.BadManifest("it has no list of files")
            val entries = ArrayList<Entry>(files.size)
            val seen = HashSet<String>()
            val skipped = ArrayList<String>()
            files.forEachIndexed { i, item ->
                val entry = try {
                    entry(item)
                } catch (e: Invalid) {
                    skipped.add("file ${i + 1}: ${e.message}")
                    return@forEachIndexed
                }
                if (!seen.add(entry.path)) {
                    skipped.add("file ${i + 1}: “${entry.path}” is listed twice")
                    return@forEachIndexed
                }
                entries.add(entry)
            }
            if (start !in seen) throw SyncError.BadManifest("its start page “$start” isn't among its files")
            return Manifest(start, entries, skipped)
        }

        private class Invalid(message: String) : Exception(message)

        private fun entry(item: Any?): Entry {
            if (item !is Map<*, *>) throw Invalid("not an object")
            val path = item["path"] as? String ?: throw Invalid("no path")
            pathProblem(path)?.let { throw Invalid("the path “$path” $it") }
            val url = item["url"] as? String ?: throw Invalid("“$path” has no url")
            urlProblem(url)?.let { throw Invalid("the url of “$path” $it") }
            val size = item["size"] as? Long ?: throw Invalid("“$path” has no size")
            if (size < 0) throw Invalid("“$path” has a negative size")
            val sha256 = item["sha256"] as? String ?: throw Invalid("“$path” has no sha256")
            if (!SHA256.matches(sha256)) throw Invalid("the sha256 of “$path” isn't 64 lowercase hex digits")
            val type = item["type"] as? String ?: throw Invalid("“$path” has no type")
            if (!headerText(type) || !MIME.matches(ContentType.mimeType(type))) {
                throw Invalid("the type of “$path” isn't a Content-Type")
            }
            val headers = LinkedHashMap<String, String>()
            when (val given = item["headers"]) {
                null -> {}
                is Map<*, *> -> for ((name, value) in given) {
                    val known = HEADERS.firstOrNull { it.equals(name as? String, ignoreCase = true) } ?: continue
                    if (value !is String || !headerText(value)) throw Invalid("the $known of “$path” isn't a header's text")
                    headers[known] = value
                }
                else -> throw Invalid("the headers of “$path” aren't an object")
            }
            return Entry(path, url, size, sha256, type, headers)
        }

        /** What is wrong with [path] as the contract has it, or null. */
        fun pathProblem(path: String): String? = when {
            path.isEmpty() -> "is empty"
            path.startsWith("/") -> "starts with /"
            '\\' in path -> "has a backslash"
            '\u0000' in path -> "has a NUL"
            path.split('/').any { it == "." || it == ".." } -> "has a . or .. part"
            path.split('/').any { it.isEmpty() } -> "has an empty part"
            else -> null
        }

        /** What is wrong with [url] as the contract has it (a path on the server, percent-encoded), or null. */
        private fun urlProblem(url: String): String? {
            if (!url.startsWith("/") || url.startsWith("//")) return "isn't a path on the server"
            if (url.any { it <= ' ' || it == '\u007f' || it == '\\' }) return "has a character a URL can't"
            val uri = try {
                URI(url)
            } catch (e: URISyntaxException) {
                return "isn't a URL"
            }
            return if (uri.scheme != null || uri.rawAuthority != null || uri.rawFragment != null) "isn't a path on the server" else null
        }

        /** Whether [text] can go in a header as it is: printable ASCII (and tabs), no line break. */
        private fun headerText(text: String) = text.all { it == '\t' || it in ' '..'~' }
    }
}

/** A Content-Type split as Android's WebResourceResponse takes it: the mime type, and the charset if any. */
object ContentType {
    fun mimeType(type: String): String = type.substringBefore(';').trim().lowercase()

    fun charset(type: String): String? = type.split(';').drop(1)
        .map { it.trim() }
        .firstOrNull { it.startsWith("charset=", ignoreCase = true) }
        ?.substring("charset=".length)?.trim()?.trim('"')
        ?.takeIf { it.isNotEmpty() }
}
