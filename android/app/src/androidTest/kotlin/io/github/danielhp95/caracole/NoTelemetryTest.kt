package io.github.danielhp95.caracole

import android.content.pm.PackageManager
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith

/** The debug build carries ONNX Runtime (`:ml`, a debugImplementation) without what would make it phone home: its
 * AAR's `ai.onnxruntime.TelemetryInitializer`, a content provider that starts at the app's start and hands the
 * runtime's native telemetry an HTTP client, is removed by `:ml`'s manifest, so no provider of the runtime's is
 * declared by the app as installed. */
@RunWith(AndroidJUnit4::class)
class NoTelemetryTest {
    @Test fun theInstalledAppDeclaresNoProviderOfTheRuntimes() {
        val context = InstrumentationRegistry.getInstrumentation().targetContext
        // The runtime is in the app under test, or this test would pass for nothing.
        Class.forName("ai.onnxruntime.OrtEnvironment", false, context.classLoader)
        @Suppress("DEPRECATION")
        val info = context.packageManager.getPackageInfo(context.packageName, PackageManager.GET_PROVIDERS)
        assertEquals("$APP.debug", info.packageName)
        val providers = info.providers.orEmpty().map { it.name }
        assertTrue("the app's providers: $providers", providers.isNotEmpty())
        assertEquals(emptyList<String>(), providers.filter { it.startsWith("ai.onnxruntime.") })
    }

    private companion object {
        const val APP = "io.github.danielhp95.caracole"
    }
}
