package io.github.danielhp95.caracole.youtube

import android.os.Bundle
import androidx.test.runner.AndroidJUnitRunner

/**
 * :youtube's instrumentation runner: `caracole.network=loopback` before any test, as the app's CaracoleTestRunner
 * sets it (core.http.RealTransport's NETWORK, named here as :youtube has no :core), so that whatever comes to read the
 * mode in this test APK (the gate's, from Y0.4 on) finds the tests' own.
 */
class YoutubeTestRunner : AndroidJUnitRunner() {
    override fun onCreate(arguments: Bundle?) {
        System.setProperty("caracole.network", "loopback")
        super.onCreate(arguments)
    }
}
