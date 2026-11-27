package io.github.danielhp95.caracole

import android.content.Context
import io.github.danielhp95.caracole.viewer.autochords.ChordModels
import java.io.File

/** A build without :ml's chord models (outside the ml shell, a debug build alone: a release is never made so): none
 * (src/ml's PhoneChords is `:ml`'s), so the audio job and `Phone.audioProblem()` say auto-chords isn't on the phone. */
internal object PhoneChords {
    @Suppress("UNUSED_PARAMETER")
    fun of(context: Context, stateDir: File): ChordModels? = null

    @Suppress("UNUSED_PARAMETER")
    fun sweep(context: Context, stateDir: File): List<String> = emptyList()
}
