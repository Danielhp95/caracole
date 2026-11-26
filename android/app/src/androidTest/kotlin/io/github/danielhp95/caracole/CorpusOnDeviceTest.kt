package io.github.danielhp95.caracole

import android.os.Bundle
import androidx.test.platform.app.InstrumentationRegistry
import io.github.danielhp95.caracole.autochords.testing.AutochordsReplay
import io.github.danielhp95.caracole.autochords.testing.AutochordsReplays
import io.github.danielhp95.caracole.core.testing.AreaReplay
import io.github.danielhp95.caracole.core.testing.Corpus
import io.github.danielhp95.caracole.core.testing.Misses
import io.github.danielhp95.caracole.core.testing.Replays
import io.github.danielhp95.caracole.server.testing.ServerReplays
import io.github.danielhp95.caracole.viewer.testing.ViewerReplays
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith
import org.junit.runners.Parameterized

/**
 * The conformance corpus on the device: every area's replay (core.testing.Replays, server.testing.ServerReplays,
 * viewer.testing.ViewerReplays, autochords.testing.AutochordsReplays), each record answered under Android's runtime, its ICU-backed java.util.regex and its
 * own String, as the JVM's tests answer them on the computer; one test an area, so a failing area never hides
 * another. The vectors are the androidTest assets' `conformance/` and the fixtures they name its `fixtures/`
 * (app/build.gradle.kts copies both). The autochords area's scores (how close each front end came, not only that it
 * passed) are the instrumentation's output, which `am instrument -w` prints.
 *
 *     android/scripts/device-test.sh --area unicode,keys      # some areas; none named: every one
 *     adb shell am instrument -w -e class io.github.danielhp95.caracole.CorpusOnDeviceTest -e area unicode \
 *         io.github.danielhp95.caracole.debug.test/io.github.danielhp95.caracole.CaracoleTestRunner
 */
@RunWith(Parameterized::class)
class CorpusOnDeviceTest(private val area: String) {
    private val instrumentation = InstrumentationRegistry.getInstrumentation()

    @Before
    fun theVectorsAreTheTestsAssets() {
        val assets = instrumentation.context.assets
        Corpus.open = { name -> runCatching { assets.open("conformance/$name") }.getOrNull() }
        Corpus.openFixture = { name -> runCatching { assets.open("fixtures/$name") }.getOrNull() }
        AutochordsReplay.report = { line ->
            instrumentation.sendStatus(0, Bundle().apply { putString("stream", "$line\n") })
        }
    }

    @Test
    fun theAreaAnswersAsPythonDid() {
        val misses = Misses(area)
        ALL.getValue(area).replay(misses)
        misses.assertNone(required = false)
    }

    companion object {
        private val EVERY: List<AreaReplay> = Replays.all + ServerReplays.all + ViewerReplays.all +
            AutochordsReplays.all
        private val ALL: Map<String, AreaReplay> = EVERY.associateBy { it.area }

        /** The areas `-e area NAME[,NAME…]` names, else every one. */
        @JvmStatic
        @Parameterized.Parameters(name = "{0}")
        fun areas(): List<String> {
            val named = InstrumentationRegistry.getArguments().getString("area").orEmpty()
                .split(',').map { it.trim(' ') }.filter { it.isNotEmpty() }
            return Replays.named(named, EVERY).map { it.area }
        }
    }
}
