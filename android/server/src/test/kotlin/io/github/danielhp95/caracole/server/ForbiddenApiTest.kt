package io.github.danielhp95.caracole.server

import io.github.danielhp95.caracole.core.testing.ForbiddenApis
import org.junit.Test
import java.io.File
import kotlin.test.assertTrue

/** :server never asks the JDK or ICU about text, as :core never does (core.testing.ForbiddenApis); the M1–3 files a
 * later lane ports are allowed until then, each with that lane. */
class ForbiddenApiTest {
    @Test fun serverNeverAsksTheJdkOrIcuAboutText() {
        val found = ForbiddenApis.check(File("src/main/kotlin"), ALLOWED)
        assertTrue(found.isEmpty(), "forbidden in :server (use core.py's Py, PyUnicode, PyRegex):\n" + found.joinToString("\n"))
    }

    private companion object {
        val ALLOWED: Map<String, String> = mapOf()
    }
}
