package io.github.danielhp95.caracole

import android.content.Context
import io.github.danielhp95.caracole.core.models.ModelFiles
import io.github.danielhp95.caracole.ml.MlChordModels
import io.github.danielhp95.caracole.viewer.autochords.ChordModels
import java.io.File

/**
 * The phone's chord models in the debug build (src/debug; src/release's PhoneChords has none, so that the release's
 * main source set names nothing of `:ml`, a debugImplementation): `:ml`'s [MlChordModels] over the folder the models'
 * job installs, `stateDir/models/c<contract>/` (ModelFiles.installed its judge, ModelsRunner.ready's one answer), its
 * checkpoints in `stateDir/cache/autochords/` and removed once a song is heard, the phone's own reasons not to hear
 * first (MlChordModels.deviceProblem: Android 13, the processor, 6 GB; none under a device test that sets
 * [Caracole.anyPhoneHearsForTests]). Null in a build that carries no pins (ModelFiles.carried).
 */
internal object PhoneChords {
    fun of(context: Context, stateDir: File): ChordModels? {
        val pins = ModelFiles.carried() ?: return null
        val folder = pins.folder(stateDir)
        return MlChordModels(context, folder, work(stateDir), installed = { ModelFiles.installed(folder, pins) },
                             device = { if (Caracole.anyPhoneHearsForTests) null else MlChordModels.deviceProblem(context) },
                             forgetHeard = true)
    }

    /** The checkpoints a hearing left a day or more ago (a killed app's), deleted as the phone starts. */
    fun sweep(stateDir: File): List<String> = MlChordModels.sweepOld(work(stateDir), System.currentTimeMillis())

    private fun work(stateDir: File) = File(stateDir, "cache/autochords")
}
