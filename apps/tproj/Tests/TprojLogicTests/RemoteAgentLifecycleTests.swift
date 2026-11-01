import XCTest
@testable import TprojLogic

final class RemoteAgentLifecycleTests: XCTestCase {
    func testEndedAgentResumesButClosedViewOnlyReconnects() {
        XCTAssertEqual(RemoteAgentLifecycle.action(serverState: "stopped", viewClosed: false), "Resume")
        XCTAssertEqual(RemoteAgentLifecycle.action(serverState: "running", viewClosed: true), "Reconnect")
        XCTAssertEqual(RemoteAgentLifecycle.action(serverState: nil, viewClosed: true), "Reconnect")
        XCTAssertNil(RemoteAgentLifecycle.action(serverState: "running", viewClosed: false))
        XCTAssertEqual(RemoteAgentLifecycle.action(serverState: "unavailable", viewClosed: false), "Check")
        XCTAssertEqual(RemoteAgentLifecycle.action(serverState: nil, viewClosed: false), "Check")
    }
}
