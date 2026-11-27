package io.github.danielhp95.caracole

import android.content.Context
import io.github.danielhp95.caracole.viewer.autochords.ChordModels
import java.io.File

/** The release's chord models: none (src/debug's PhoneChords is `:ml`'s, the debug build's alone until the owner's
 * Gate R), so the audio job and `Phone.audioProblem()` say auto-chords isn't on the phone. */
internal object PhoneChords {
    @Suppress("UNUSED_PARAMETER")
    fun of(context: Context, stateDir: File): ChordModels? = null

    @Suppress("UNUSED_PARAMETER")
    fun sweep(context: Context, stateDir: File): List<String> = emptyList()
}
