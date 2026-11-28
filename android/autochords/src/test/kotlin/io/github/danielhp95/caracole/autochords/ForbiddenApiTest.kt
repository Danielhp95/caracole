package io.github.danielhp95.caracole.autochords

import io.github.danielhp95.caracole.core.testing.ForbiddenApis
import org.junit.Test
import java.io.File
import kotlin.test.assertTrue

/** :autochords never asks the JDK or ICU about text, as :core never does (core.testing.ForbiddenApis): its labels
 * (btc.py's chord names, Labels) are read by characters. */
class ForbiddenApiTest {
    @Test fun autochordsNeverAsksTheJdkOrIcuAboutText() {
        val found = ForbiddenApis.check(File("src/main/kotlin"))
        assertTrue(found.isEmpty(), "forbidden in :autochords (use core.py's Py, PyUnicode, PyRegex):\n" + found.joinToString("\n"))
    }
}
