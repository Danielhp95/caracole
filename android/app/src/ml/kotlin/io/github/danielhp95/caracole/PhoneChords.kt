package io.github.danielhp95.caracole

import android.content.Context
import io.github.danielhp95.caracole.core.models.ModelFiles
import io.github.danielhp95.caracole.ml.MlChordModels
import io.github.danielhp95.caracole.viewer.autochords.ChordModels
import java.io.File

/**
 * The phone's chord models, where :ml is in the build (src/ml, both builds of the ml shell; src/noMl's PhoneChords has
 * none, so that a build without :ml names nothing of it): `:ml`'s [MlChordModels] over the folder the models' job
 * installs, `stateDir/models/c<contract>/` (ModelFiles.installed its judge, ModelsRunner.ready's one answer), its
 * checkpoints in `stateDir/cache/autochords/` and removed once a song is heard, the phone's own reasons not to hear
 * first (MlChordModels.deviceProblem: Android 13, a processor this APK carries the libraries of, 6 GB; none under a
 * device test that sets [anyPhoneHearsForTests]). Null in a build that carries no pins (ModelFiles.carried).
 */
internal object PhoneChords {
    /** A device test's: the chord models hear on this phone whatever its own reasons not to (the emulator's 2 GB),
     * read each time [of]'s models are asked. */
    @Volatile var anyPhoneHearsForTests: Boolean = false

    fun of(context: Context, stateDir: File): ChordModels? {
        val pins = ModelFiles.carried() ?: return null
        val folder = pins.folder(stateDir)
        return MlChordModels(context, folder, work(stateDir), installed = { ModelFiles.installed(folder, pins) },
                             device = { if (anyPhoneHearsForTests) null else MlChordModels.deviceProblem(context, ABIS) },
                             forgetHeard = true)
    }

    /** The checkpoints a hearing left a day or more ago (a killed app's), deleted as the phone starts, under the
     * hearings' one turn (none while a hearing of another process holds it). */
    fun sweep(context: Context, stateDir: File): List<String> =
        MlChordModels.sweepOld(work(stateDir), System.currentTimeMillis(), File(context.filesDir, MlChordModels.TURN))

    private fun work(stateDir: File) = File(stateDir, "cache/autochords")

    /** The ABIs this APK carries the chord models' libraries of: arm64-v8a alone in the release, both in a debug build
     * (app/build.gradle.kts), so an x86_64 phone's release says "no chord models for this phone's processor". */
    private val ABIS: Set<String> = BuildConfig.ML_ABIS.split(",").toSet()
}
