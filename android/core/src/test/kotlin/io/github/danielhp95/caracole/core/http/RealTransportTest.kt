package io.github.danielhp95.caracole.core.http

import io.github.danielhp95.caracole.core.testing.replays.RealTransportChecks
import org.junit.Test

/** RealTransport on the JVM against a site on 127.0.0.1 (core.testing.replays.RealTransportChecks; the device runs
 * the same checks in RealTransportOnDeviceTest). */
class RealTransportTest {
    @Test fun itSendsHttpxsHeaderSetAndNoOther() = RealTransportChecks.httpxsHeaderSet()

    @Test fun itFollowsNoRedirect() = RealTransportChecks.noRedirectIsFollowed()

    @Test fun itDecodesGzipAndDeflateAsHttpxDoes() = RealTransportChecks.gzipAndDeflateAreDecoded()

    @Test fun anErrorComesWithItsBodyAndItsHeadersInOrder() = RealTransportChecks.anErrorIsAnsweredWithItsBody()

    @Test fun aRefusedConnectionIsHttpxsConnectError() = RealTransportChecks.aRefusedConnectionIsAConnectError()

    @Test fun routedRequestsCarryTheSitesUrlInTheQuery() = RealTransportChecks.routedRequestsCarryTheSitesUrlInTheQuery()

    @Test fun everySiteIsRefusedBeforeASocketOpens() = RealTransportChecks.everySiteIsRefusedUnderTheTests()
}
