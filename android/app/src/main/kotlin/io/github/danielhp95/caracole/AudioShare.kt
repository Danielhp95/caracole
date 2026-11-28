package io.github.danielhp95.caracole

/**
 * Which files the app takes as audio for a sheet (the chords-on-the-phone design's §8.2): the types ShareActivity's
 * filter names besides the inbox's ([TYPES], the manifest's list again), the page's file input that asks for audio
 * ([chooser]: the "+"'s), and a shared file read as audio ([isAudio]) rather than filed in the inbox.
 */
internal object AudioShare {
    /** The audio types of §8.2, as the manifest's share filter names them. */
    val TYPES: List<String> = listOf(
        "audio/mpeg", "audio/mp4", "audio/x-m4a", "audio/aac", "audio/flac", "audio/x-flac", "audio/ogg", "audio/opus",
        "audio/wav", "audio/x-wav", "audio/vnd.wave", "audio/aiff", "audio/x-aiff",
    )

    /** The extensions of the audio caracole keeps (audio_store.FORMATS', and AIFF's short one). */
    private val EXTENSIONS = setOf("mp3", "m4a", "flac", "wav", "ogg", "opus", "aif", "aiff", "aac")

    /** MIDI is a score's (the inbox's), though its type is audio's. */
    private val MIDI = setOf("audio/midi", "audio/x-midi", "audio/mid", "audio/sp-midi")

    /**
     * Whether a shared file of [type] (its provider's, else the share's) and display [name] is audio for a sheet: a
     * type of [TYPES] or any other `audio/` one but MIDI's; else, its type saying nothing of it (none, a wildcard,
     * `application/octet-stream`), a name with an audio extension.
     */
    fun isAudio(type: String?, name: String?): Boolean {
        val t = type?.lowercase()?.substringBefore(';')?.trim()
        if (t != null && t in MIDI) return false
        if (t != null && t.startsWith("audio/") && !t.endsWith("/*")) return true
        if (t != null && t != "application/octet-stream" && !t.endsWith("/*")) return false
        val ext = name?.substringAfterLast('.', "")?.lowercase().orEmpty()
        return ext in EXTENSIONS
    }

    /** The picker's types for a file input that accepts [accept] (FileChooserParams.acceptTypes: types or names'
     * extensions): the audio family and [TYPES] for one that asks for audio, else null (any file). */
    fun chooser(accept: Array<String>?): List<String>? =
        if (accept.orEmpty().any { it.trim().lowercase().startsWith("audio/") }) TYPES else null
}
