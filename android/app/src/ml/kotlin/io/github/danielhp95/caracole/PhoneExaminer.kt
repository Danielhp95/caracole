package io.github.danielhp95.caracole

import android.media.MediaMetadataRetriever
import io.github.danielhp95.caracole.autochords.frontend.AudioLengths
import io.github.danielhp95.caracole.core.library.AudioStore
import java.io.File

/**
 * The app's reader of an audio file the owner gives (src/ml, beside `:ml`'s PhoneChords, both builds of the ml shell;
 * a build without :ml has none, src/noMl's): the audio store's [AudioStore.Examiner] (its contract there).
 *
 * - Its length is the computer's, by the format the store gives (a spool has no audio extension): `:autochords`'
 *   [AudioLengths], from the file's own headers, an MP3 whose first frame names no length its frames counted as
 *   mpeg_frames.py counts them, an M4A with no sound track none (refused). AudioLengthsTest holds it to the computer's
 *   store over the committed fixtures, to the bit.
 * - Its tags are Android's (MediaMetadataRetriever): `artist` its artist, then its album artist (music.py's keys
 *   begin so), `title`, `album`, each the one value Android gives. They may differ from mutagen's on a file of odd
 *   tags (the design's §8.2: the dialog's fields are editable); tags Android can't read are none, never a refusal:
 *   a WAV's and an AIFF's ID3 chunk among them (AudioRoutesOnDeviceTest), their guess then the file's name.
 */
internal object PhoneExaminer : AudioStore.Examiner {
    override fun examine(file: File, format: String): AudioStore.Audio {
        val length = AudioLengths.of(file, format) ?: throw IllegalArgumentException("no $format length in its headers")
        return AudioStore.Audio(format, length, tags(file))
    }

    private fun tags(file: File): Map<String, List<String>> = try {
        val retriever = MediaMetadataRetriever()
        try {
            retriever.setDataSource(file.path)
            fun read(key: Int) = retriever.extractMetadata(key)
            mapOf(
                "artist" to listOfNotNull(read(MediaMetadataRetriever.METADATA_KEY_ARTIST),
                                          read(MediaMetadataRetriever.METADATA_KEY_ALBUMARTIST)),
                "title" to listOfNotNull(read(MediaMetadataRetriever.METADATA_KEY_TITLE)),
                "album" to listOfNotNull(read(MediaMetadataRetriever.METADATA_KEY_ALBUM)),
            )
        } finally {
            retriever.release()
        }
    } catch (e: RuntimeException) {  // a file Android's extractors can't open: no tags, its length still read
        emptyMap()
    }
}
