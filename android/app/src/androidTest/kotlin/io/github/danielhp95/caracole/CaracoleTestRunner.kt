package io.github.danielhp95.caracole

import android.os.Bundle
import androidx.test.runner.AndroidJUnitRunner
import io.github.danielhp95.caracole.core.http.RealTransport
import io.github.danielhp95.caracole.core.http.Transport
import io.github.danielhp95.caracole.core.http.TransportError
import java.net.URI

/**
 * The app's instrumentation runner (app/build.gradle.kts's testInstrumentationRunner): before Application.onCreate it
 * sets `caracole.network=loopback`, under which RealTransport refuses any host but loopback and 10.0.2.2, and makes
 * [Caracole.sitesForTests] a transport that refuses every site, and [Caracole.searchesLacuerdaForTests] false, so the
 * app under test sends no site a request. A test that means to reach the fake sites sets `sitesForTests` to a
 * RoutedTransport of its own. The site catalogues' job asks no GitHub but one an argument names ([CATALOGUES]) or a
 * test sets ([Caracole.cataloguesForTests]): under `caracole.network=loopback` GitHub's own is refused; the chord
 * models' job a test's on loopback ([Caracole.modelsForTests], [MODELS_PORT]).
 */
class CaracoleTestRunner : AndroidJUnitRunner() {
    override fun onCreate(arguments: Bundle?) {
        System.setProperty(RealTransport.NETWORK, "loopback")
        Caracole.sitesForTests = REFUSING
        Caracole.searchesLacuerdaForTests = false
        // `-e catalogues http://10.0.2.2:PORT`: a GitHub of the test's, which the site catalogues' job lists.
        arguments?.getString(CATALOGUES)?.takeIf { it.isNotBlank() }?.let { Caracole.cataloguesForTests = URI(it) }
        // The chord models' GitHub: SettingsChordsTest's own, on loopback at MODELS_PORT (nothing answers there else).
        Caracole.modelsForTests = URI("http://127.0.0.1:$MODELS_PORT")
        super.onCreate(arguments)
    }

    companion object {
        /** The port a device test's GitHub of the chord models listens on (SettingsChordsTest's). */
        const val MODELS_PORT = 8746

        /** The instrumentation argument that names a test's GitHub. */
        const val CATALOGUES = "catalogues"

        /** Every site refused: "refused", as a test's transport says it. */
        val REFUSING: Transport = Transport { request ->
            throw TransportError("refused", "no site from the app under test: ${request.url}")
        }
    }
}
