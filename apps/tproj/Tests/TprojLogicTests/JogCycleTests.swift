import XCTest
@testable import TprojLogic

final class JogCycleTests: XCTestCase {
    // Order is role-major: codex left->right, then claude left->right.
    func testRoleMajorLeftToRight() {
        let panes: [(paneId: String, role: String, left: Int)] = [
            ("%3", "claude", 0),
            ("%1", "codex", 100),
            ("%2", "codex", 0),
            ("%4", "claude", 100),
        ]
        XCTAssertEqual(jogCycleOrder(panes: panes), ["%2", "%1", "%3", "%4"])
    }

    // Panes that are neither codex nor claude are excluded from the cycle.
    func testNonCodexClaudeExcluded() {
        let panes: [(paneId: String, role: String, left: Int)] = [
            ("%1", "codex", 0),
            ("%9", "agent", 50),
            ("%2", "claude", 0),
        ]
        XCTAssertEqual(jogCycleOrder(panes: panes), ["%1", "%2"])
    }

    // Forward/backward stepping wraps at the ends.
    func testStepWrapsAtEnds() {
        let order = ["%1", "%2", "%3"]
        XCTAssertEqual(nextPaneInCycle(order: order, active: "%1", direction: 1), "%2")
        XCTAssertEqual(nextPaneInCycle(order: order, active: "%3", direction: 1), "%1")   // wrap fwd
        XCTAssertEqual(nextPaneInCycle(order: order, active: "%1", direction: -1), "%3")  // wrap back
    }

    // If the active pane is not in the cycle (or nil), selection starts at the first.
    func testActiveOutsideListStartsAtFirst() {
        let order = ["%1", "%2"]
        XCTAssertEqual(nextPaneInCycle(order: order, active: "%9", direction: 1), "%1")
        XCTAssertEqual(nextPaneInCycle(order: order, active: nil, direction: -1), "%1")
    }

    // Empty cycle yields nil (caller keeps focus unchanged).
    func testEmptyOrderReturnsNil() {
        XCTAssertNil(nextPaneInCycle(order: [], active: nil, direction: 1))
    }
}
