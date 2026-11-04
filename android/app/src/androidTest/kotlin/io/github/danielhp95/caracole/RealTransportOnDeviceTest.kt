package io.github.danielhp95.caracole

import androidx.test.ext.junit.runners.AndroidJUnit4
import io.github.danielhp95.caracole.core.testing.replays.RealTransportChecks
import org.junit.Test
import org.junit.runner.RunWith

/**
 * RealTransport on the device, where HttpURLConnection is Android's OkHttp, against a ServerSocket on the emulator's
 * loopback: the checks RealTransportTest runs on the JVM (core.testing.replays.RealTransportChecks), httpx's header
 * set among them, under CaracoleTestRunner's caracole.network=loopback.
 *
 *     android/scripts/device-test.sh --area http RealTransportOnDeviceTest
 */
@RunWith(AndroidJUnit4::class)
class RealTransportOnDeviceTest {
    @Test fun itSendsHttpxsHeaderSetAndNoOther() = RealTransportChecks.httpxsHeaderSet()

    @Test fun itSendsTheRequestTargetHttpxSends() = RealTransportChecks.theRequestTargetIsHttpxs()

    @Test fun itFollowsNoRedirect() = RealTransportChecks.noRedirectIsFollowed()

    @Test fun itDecodesGzipAndDeflateAsHttpxDoes() = RealTransportChecks.gzipAndDeflateAreDecoded()

    @Test fun anErrorComesWithItsBodyAndItsHeadersInOrder() = RealTransportChecks.anErrorIsAnsweredWithItsBody()

    @Test fun aRefusedConnectionIsHttpxsConnectError() = RealTransportChecks.aRefusedConnectionIsAConnectError()

    @Test fun aProtocolHttpxRefusesIsRefusedAsHttpxDoes() = RealTransportChecks.aProtocolHttpxRefusesIsRefusedAsHttpxDoes()

    @Test fun routedRequestsCarryTheSitesUrlInTheQuery() = RealTransportChecks.routedRequestsCarryTheSitesUrlInTheQuery()

    @Test fun everySiteIsRefusedBeforeASocketOpens() = RealTransportChecks.everySiteIsRefusedUnderTheTests()
}
