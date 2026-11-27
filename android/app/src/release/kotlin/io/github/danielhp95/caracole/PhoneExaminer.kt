package io.github.danielhp95.caracole

import io.github.danielhp95.caracole.core.library.AudioStore
import io.github.danielhp95.caracole.server.PhoneDeps
import java.io.File

/** The release's reader of an audio file: none (src/debug's reads with `:autochords`, the debug build's alone until
 * the owner's Gate R), so every file is refused as audio caracole doesn't read here; its routes refuse before any
 * file is read anyway, Phone.audioProblem saying auto-chords isn't on the phone. */
internal object PhoneExaminer : AudioStore.Examiner {
    override fun examine(file: File, format: String): AudioStore.Audio = PhoneDeps.NO_EXAMINER.examine(file, format)
}
