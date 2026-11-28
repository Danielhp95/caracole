package io.github.danielhp95.caracole

import io.github.danielhp95.caracole.server.lookups.YouTubeSheetRunner
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertTrue

/** The app's yt-dlp on a phone of each processor (PhoneYouTube): the release carries Python and qjs for arm64-v8a
 * alone, a debug build for the emulator's x86_64 too; a phone whose first ABI the APK carries no yt-dlp for gets none,
 * which says "this phone's caracole has no yt-dlp" (YouTubeSheetRunner.NO_YTDLP). */
class PhoneYouTubeTest {
    @Test fun theReleaseCarriesArm64AloneAndADebugBuildBoth() {
        val expected = if (BuildConfig.BUILD_TYPE == "release") setOf("arm64-v8a") else setOf("arm64-v8a", "x86_64")
        assertEquals(expected, PhoneYouTube.ABIS)
    }

    @Test fun aPhoneWhoseFirstAbiTheApkCarriesHasItsYtDlp() {
        val release = setOf("arm64-v8a")
        assertTrue(PhoneYouTube.carries(listOf("arm64-v8a", "armeabi-v7a", "armeabi"), release))
        // An x86_64 phone (or emulator) whose arm64-v8a is translated runs the APK's x86_64 libraries: no Python there.
        assertFalse(PhoneYouTube.carries(listOf("x86_64", "arm64-v8a"), release))
        assertFalse(PhoneYouTube.carries(listOf("x86_64"), release))
        assertFalse(PhoneYouTube.carries(emptyList(), release))
        assertTrue(PhoneYouTube.carries(listOf("x86_64", "arm64-v8a"), setOf("arm64-v8a", "x86_64")))
    }

    @Test fun aPhoneWithNoYtDlpSaysSo() {
        assertEquals("this phone's caracole has no yt-dlp", YouTubeSheetRunner.NO_YTDLP)
    }
}
