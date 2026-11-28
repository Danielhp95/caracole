package io.github.danielhp95.caracole.core.youtube

import io.github.danielhp95.caracole.core.db.Db
import io.github.danielhp95.caracole.core.http.Client
import io.github.danielhp95.caracole.core.py.PyRe
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.int
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import java.io.File
import java.io.IOException
import java.nio.file.Files
import java.nio.file.LinkOption
import java.nio.file.StandardCopyOption
import java.time.Instant

/**
 * youtube_search.py's thumbnail on the phone: a video's `hqdefault.jpg` from YouTube's image host (provider `ytimg`,
 * youtube.json's `thumb` member: its address, its folder, its limits), asked once through the caller's PoliteClient
 * ([keep], then [note] in a write: robots.txt's rules, `/sb/` closed, the cache forever, the caller's budget and events), kept only when its
 * bytes are a JPEG ([checkedJpeg]) as `<cacheRoot>/youtube-thumbs/<id>.jpg`, never in the library, and read back
 * checked again ([get], [read]) for `GET /youtube/thumb/<id>.jpg`. vectors/youtube/video_cmd.jsonl's `checked_jpeg`
 * records hold [checkedJpeg] to Python's answers (YouTubeReplay).
 */
class Thumbs(private val cacheRoot: File) {
    /** thumb_path: where [videoId]'s thumbnail is kept. */
    fun path(videoId: String): File =
        File(File(cacheRoot, text("folder")), YouTubeData.fillOnce(text("name"), ID, videoId))

    /** The kept thumbnail of [videoId] as a file, when its bytes are a JPEG still; null for no such video or file. */
    fun get(videoId: String): File? = path(videoId).takeIf { read(videoId) != null }

    /** read_thumbnail: the kept thumbnail's bytes, checked again; null for no such video, file, or JPEG. */
    fun read(videoId: String): ByteArray? {
        if (PyRe.fullmatch(YouTubeData.read().videoId, videoId) == null) return null
        val file = path(videoId).toPath()
        if (!Files.isRegularFile(file, LinkOption.NOFOLLOW_LINKS)) return null
        val data = try {
            Files.readAllBytes(file)
        } catch (_: IOException) {
            return null
        }
        return checkedJpeg(data)
    }

    /**
     * fetch_thumbnail's request: [videoId]'s thumbnail, once (one request through [client]; none once it is kept),
     * kept when its bytes are a JPEG; whether it is kept now. A 404 or bytes that are no JPEG are none; a block or an
     * error propagates. It touches no database: the client logs its own events; [note] records what came of it.
     */
    fun keep(client: Client, videoId: String): Boolean {
        if (PyRe.fullmatch(YouTubeData.read().videoId, videoId) == null) return false
        val path = path(videoId)
        if (path.isFile) return true
        val resp = client.get(YouTubeData.fillOnce(text("url"), ID, videoId), accept = setOf(200, 404))
        val image = (if (resp.status == 200) checkedJpeg(resp.content) else null) ?: return false
        path.parentFile.mkdirs()
        val part = Files.createTempFile(path.parentFile.toPath(), text("part"), "-" + path.name)  // the phone's cache
        try {
            Files.write(part, image)
            Files.move(part, path.toPath(), StandardCopyOption.ATOMIC_MOVE)
        } finally {
            Files.deleteIfExists(part)
        }
        return true
    }

    /** fetch_thumbnail's record: the record of [key] (a pasted video's, a query's) said to have [videoId]'s thumbnail
     * when its video is this one, once [keep] kept it. */
    fun note(db: Db, videoId: String, key: String, now: Instant) {
        val said = SearchGate.searched(db, key, now)
        val video = said?.get("video") as? JsonObject
        if (said != null && video != null && video["id"] == JsonPrimitive(videoId)) {
            db.kvSetJson(SearchGate.kvKey(key), JsonObject(LinkedHashMap(said).apply { put("thumb", JsonPrimitive(true)) }))
        }
    }

    companion object {
        private const val ID = "{id}"
        private val thumb: JsonObject get() = YouTubeData.read().json.getValue("thumb").jsonObject
        private fun text(name: String): String = thumb.getValue(name).jsonPrimitive.content
        private fun number(name: String): Int = thumb.getValue(name).jsonPrimitive.int

        /** The provider a thumbnail is asked of (youtube_search.THUMBS_PROVIDER). */
        val PROVIDER: String get() = text("provider")

        private val frames: Set<Int> by lazy { thumb.getValue("frames").jsonArray.map { it.jsonPrimitive.int }.toSet() }

        /**
         * checked_jpeg: [data] when it is a JPEG image and nothing else: at most `max_bytes`, its start-of-image
         * marker, its segments walked (fill bytes passed over; a second start, an end, a restart or TEM marker before
         * the scan refused) to a frame (`frames`) of 1 to `max_side` pixels a side and on to the scan, whose data ends
         * with an end-of-image marker, trailing zeros aside; null otherwise.
         */
        fun checkedJpeg(data: ByteArray): ByteArray? {
            val most = number("max_bytes")
            val side = number("max_side")
            if (data.size < 4 || data.size > most || u(data, 0) != 0xFF || u(data, 1) != 0xD8) return null
            var i = 2
            var sized = false
            while (i + 4 <= data.size) {
                if (u(data, i) != 0xFF) return null
                val marker = u(data, i + 1)
                if (marker == 0xFF) {
                    i += 1
                    continue
                }
                if (marker == 0xD8 || marker == 0xD9 || marker in 0xD0..0xD7 || marker == 0x01) return null
                val length = (u(data, i + 2) shl 8) or u(data, i + 3)
                if (length < 2 || i + 2 + length > data.size) return null
                if (marker in frames) {
                    if (length < 7) return null
                    val height = (u(data, i + 5) shl 8) or u(data, i + 6)
                    val width = (u(data, i + 7) shl 8) or u(data, i + 8)
                    if (width !in 1..side || height !in 1..side) return null
                    sized = true
                }
                if (marker == 0xDA) {
                    var end = data.size
                    while (end > 0 && data[end - 1].toInt() == 0) end--
                    val closed = end >= 2 && u(data, end - 2) == 0xFF && u(data, end - 1) == 0xD9
                    return if (sized && closed) data else null
                }
                i += 2 + length
            }
            return null
        }

        private fun u(data: ByteArray, i: Int): Int = data[i].toInt() and 0xFF
    }
}
