package io.github.danielhp95.caracole

import android.os.Bundle
import androidx.test.runner.AndroidJUnitRunner
import io.github.danielhp95.caracole.core.http.RealTransport
import io.github.danielhp95.caracole.core.http.Transport
import io.github.danielhp95.caracole.core.http.TransportError

/**
 * The app's instrumentation runner (app/build.gradle.kts's testInstrumentationRunner): before Application.onCreate it
 * sets `caracole.network=loopback`, under which RealTransport refuses any host but loopback and 10.0.2.2, and makes
 * [Caracole.sitesForTests] a transport that refuses every site, and [Caracole.searchesLacuerdaForTests] false, so the
 * app under test sends no site a request. A test that means to reach the fake sites sets `sitesForTests` to a
 * RoutedTransport of its own.
 */
class CaracoleTestRunner : AndroidJUnitRunner() {
    override fun onCreate(arguments: Bundle?) {
        System.setProperty(RealTransport.NETWORK, "loopback")
        Caracole.sitesForTests = REFUSING
        Caracole.searchesLacuerdaForTests = false
        super.onCreate(arguments)
    }

    companion object {
        /** Every site refused: "refused", as a test's transport says it. */
        val REFUSING: Transport = Transport { request ->
            throw TransportError("refused", "no site from the app under test: ${request.url}")
        }
    }
}
