package io.github.danielhp95.caracole

import android.content.Context
import android.media.MediaCodec
import android.media.MediaExtractor
import android.media.MediaFormat
import android.net.ConnectivityManager
import android.net.NetworkCapabilities
import android.net.TrafficStats
import android.os.Build
import android.os.Process
import io.github.danielhp95.caracole.youtube.BenchRun
import io.github.danielhp95.caracole.youtube.YtDlpClient
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import java.io.File

/**
 * What the YouTube bench measures on the phone, in its own process (`:ytbench`): the device and the app (no name of
 * the owner's), the network's kind (no carrier, SSID or address), the uid's bytes (TrafficStats), the PSS of the
 * app's `:youtube` process and of qjs (their `/proc/<pid>/smaps_rollup`, which the app's uid reads of its own
 * processes), what MediaCodec decodes of a download, and the processes left after the kill check.
 */
internal class YouTubeBenchProbe(private val context: Context) : BenchRun.Probe {
    override fun device(): JsonObject {
        val info = context.packageManager.getPackageInfo(context.packageName, 0)
        val apk = File(context.applicationInfo.sourceDir)
        val installed = listOf(context.filesDir, context.cacheDir, File(context.applicationInfo.nativeLibraryDir))
            .sumOf { size(it) } + apk.length()
        return JsonObject(linkedMapOf(
            "device" to JsonPrimitive("${Build.MANUFACTURER} ${Build.MODEL}"),
            "soc" to JsonPrimitive(if (Build.VERSION.SDK_INT >= 31) "${Build.SOC_MANUFACTURER} ${Build.SOC_MODEL}" else Build.HARDWARE),
            "android" to JsonPrimitive("${Build.VERSION.RELEASE} (API ${Build.VERSION.SDK_INT})"),
            "app" to JsonPrimitive(info.versionName ?: ""),
            "apk_bytes" to JsonPrimitive(apk.length()),
            "installed_bytes" to JsonPrimitive(installed),
            "abi" to JsonPrimitive(Build.SUPPORTED_ABIS.firstOrNull() ?: ""),
        ))
    }

    private fun size(file: File): Long =
        if (file.isFile) file.length() else file.listFiles().orEmpty().sumOf { size(it) }

    override fun network(): JsonObject {
        val manager = context.getSystemService(ConnectivityManager::class.java)
        val caps = manager?.getNetworkCapabilities(manager.activeNetwork)
        val transport = when {
            caps == null -> null
            caps.hasTransport(NetworkCapabilities.TRANSPORT_WIFI) -> "wifi"
            caps.hasTransport(NetworkCapabilities.TRANSPORT_CELLULAR) -> "cellular"
            caps.hasTransport(NetworkCapabilities.TRANSPORT_ETHERNET) -> "ethernet"
            else -> "other"
        }
        return JsonObject(linkedMapOf(
            "transport" to (transport?.let(::JsonPrimitive) ?: JsonNull),
            "metered" to JsonPrimitive(manager?.isActiveNetworkMetered ?: true),
            "validated" to JsonPrimitive(caps?.hasCapability(NetworkCapabilities.NET_CAPABILITY_VALIDATED) == true),
        ))
    }

    override fun uidBytes(): Long? {
        val uid = Process.myUid()
        val rx = TrafficStats.getUidRxBytes(uid)
        val tx = TrafficStats.getUidTxBytes(uid)
        return if (rx < 0 || tx < 0) null else rx + tx
    }

    override fun sample(): () -> Map<String, Double> {
        val peaks = HashMap<String, Double>()
        val going = java.util.concurrent.atomic.AtomicBoolean(true)
        val thread = Thread({
            while (going.get()) {
                val now = pss()
                synchronized(peaks) { for ((name, kb) in now) peaks[name] = maxOf(peaks[name] ?: 0.0, kb / 1024.0) }
                Thread.sleep(500)
            }
        }, "ytbench-pss").apply { isDaemon = true; start() }
        return {
            going.set(false)
            thread.join(2_000)
            synchronized(peaks) { HashMap(peaks) }
        }
    }

    /** PSS in kB of `:youtube` and of the qjs processes together, by name. */
    private fun pss(): Map<String, Long> {
        val out = HashMap<String, Long>()
        for ((pid, cmd) in processes()) {
            val name = when {
                cmd.endsWith(YtDlpClient.PROCESS) -> YOUTUBE
                BenchRun.QJS in cmd -> QJS
                else -> continue
            }
            val kb = try {
                File("/proc/$pid/smaps_rollup").readLines().firstOrNull { it.startsWith("Pss:") }
                    ?.split(Regex("\\s+"))?.get(1)?.toLong()
            } catch (_: Exception) {
                null
            } ?: continue
            out[name] = (out[name] ?: 0) + kb
        }
        return out
    }

    override fun leftover(): List<String> = processes().values.filter {
        it.endsWith(YtDlpClient.PROCESS) || BenchRun.QJS in it
    }

    /** Every process of the app's uid but this one: pid to command line. */
    private fun processes(): Map<Int, String> {
        val mine = Process.myUid()
        val me = Process.myPid()
        val found = sortedMapOf<Int, String>()
        for (dir in File("/proc").listFiles().orEmpty()) {
            val pid = dir.name.toIntOrNull() ?: continue
            if (pid == me) continue
            try {
                val uid = File(dir, "status").readLines().firstOrNull { it.startsWith("Uid:") }
                    ?.split(Regex("\\s+"))?.get(1)?.toIntOrNull()
                if (uid != mine) continue
                found[pid] = File(dir, "cmdline").readBytes().decodeToString().replace('\u0000', ' ').trim()
            } catch (_: Exception) {
                continue
            }
        }
        return found
    }

    override fun decode(file: File): JsonObject? = try {
        val extractor = MediaExtractor()
        try {
            extractor.setDataSource(file.path)
            val track = (0 until extractor.trackCount).firstOrNull {
                extractor.getTrackFormat(it).getString(MediaFormat.KEY_MIME)?.startsWith("audio/") == true
            } ?: return null
            val format = extractor.getTrackFormat(track)
            val mime = format.getString(MediaFormat.KEY_MIME)!!
            extractor.selectTrack(track)
            val codec = MediaCodec.createDecoderByType(mime)
            var frames = 0L
            var rate = format.getInteger(MediaFormat.KEY_SAMPLE_RATE)
            var channels = format.getInteger(MediaFormat.KEY_CHANNEL_COUNT)
            try {
                codec.configure(format, null, null, 0)
                codec.start()
                val info = MediaCodec.BufferInfo()
                var inputDone = false
                while (true) {
                    if (!inputDone) {
                        val i = codec.dequeueInputBuffer(10_000)
                        if (i >= 0) {
                            val n = extractor.readSampleData(codec.getInputBuffer(i)!!, 0)
                            if (n < 0) {
                                codec.queueInputBuffer(i, 0, 0, 0, MediaCodec.BUFFER_FLAG_END_OF_STREAM)
                                inputDone = true
                            } else {
                                codec.queueInputBuffer(i, 0, n, extractor.sampleTime, 0)
                                extractor.advance()
                            }
                        }
                    }
                    val o = codec.dequeueOutputBuffer(info, 10_000)
                    if (o == MediaCodec.INFO_OUTPUT_FORMAT_CHANGED) {
                        rate = codec.outputFormat.getInteger(MediaFormat.KEY_SAMPLE_RATE)
                        channels = codec.outputFormat.getInteger(MediaFormat.KEY_CHANNEL_COUNT)
                    } else if (o >= 0) {
                        frames += info.size / (2L * channels) // 16-bit PCM
                        codec.releaseOutputBuffer(o, false)
                        if (info.flags and MediaCodec.BUFFER_FLAG_END_OF_STREAM != 0) break
                    }
                }
            } finally {
                codec.release()
            }
            JsonObject(linkedMapOf("mime" to JsonPrimitive(mime), "rate" to JsonPrimitive(rate),
                                   "channels" to JsonPrimitive(channels), "frames" to JsonPrimitive(frames)))
        } finally {
            extractor.release()
        }
    } catch (_: Exception) {
        null
    }

    override fun pythonExtracted(): Boolean = File(context.filesDir, "chaquopy").exists()

    companion object {
        const val YOUTUBE = "youtube"
        const val QJS = "qjs"
    }
}
