package io.github.danielhp95.caracole

import android.content.ComponentName
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import io.github.danielhp95.caracole.ml.MlProtocol
import io.github.danielhp95.caracole.ml.MlService
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith

/** The installed debug app's manifest puts MlService in the process Caracole.kt tells apart by its name: the three
 * places ":ml" is written (the manifest, [Caracole.MODELS_PROCESS], [MlProtocol.PROCESS_SUFFIX]) agree, so the guard
 * that keeps the phone's caracole out of the models' process holds. */
@RunWith(AndroidJUnit4::class)
class MlProcessTest {
    @Test fun theModelsServiceRunsInTheProcessCaracoleKeepsItselfOutOf() {
        val app = InstrumentationRegistry.getInstrumentation().targetContext
        val info = app.packageManager.getServiceInfo(ComponentName(app, MlService::class.java), 0)
        assertEquals(app.packageName + Caracole.MODELS_PROCESS, info.processName)
        assertEquals(Caracole.MODELS_PROCESS, MlProtocol.PROCESS_SUFFIX)
        assertTrue(Caracole.isModelsProcess(info.processName, app.packageName))
    }
}
