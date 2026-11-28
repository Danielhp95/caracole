package io.github.danielhp95.caracole

import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/** The chord models' process is told apart by its name alone (a build without `:ml` has no class of it). */
class ModelsProcessTest {
    @Test fun theModelsProcessIsTheAppsNameAndMl() {
        val app = "io.github.danielhp95.caracole.debug"
        assertTrue(Caracole.isModelsProcess("$app:ml", app))
        assertFalse(Caracole.isModelsProcess(app, app))
        assertFalse(Caracole.isModelsProcess("$app:bench", app))
        assertFalse(Caracole.isModelsProcess("$app:mlx", app))
        assertFalse(Caracole.isModelsProcess("other.app:ml", app))
    }
}
