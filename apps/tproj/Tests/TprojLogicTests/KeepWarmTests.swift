import XCTest
@testable import TprojLogic

final class KeepWarmTests: XCTestCase {
    func testPokeEligibilityBoundaries() {
        let now = Date(timeIntervalSince1970: 1_800_000_000)
        func session(
            tty: String? = "/dev/ttys001",
            remaining: TimeInterval? = 90,
            idle: TimeInterval? = 3_599,
            pokeable: Bool = true
        ) -> KeepWarmSession {
            KeepWarmSession(
                tty: tty,
                cacheExpiresAt: remaining.map { now.addingTimeInterval($0) },
                lastUserPromptAt: idle.map { now.addingTimeInterval(-$0) },
                pokeable: pokeable
            )
        }

        XCTAssertTrue(KeepWarmDecision.shouldPoke(session: session(), now: now, hours: 1))
        XCTAssertTrue(KeepWarmDecision.shouldPoke(session: session(idle: 0), now: now, hours: 1))
        XCTAssertFalse(KeepWarmDecision.shouldPoke(session: session(remaining: 90.001), now: now, hours: 1))
        XCTAssertFalse(KeepWarmDecision.shouldPoke(session: session(remaining: 0), now: now, hours: 1))
        XCTAssertFalse(KeepWarmDecision.shouldPoke(session: session(idle: 3_600), now: now, hours: 1))
        XCTAssertFalse(KeepWarmDecision.shouldPoke(session: session(idle: -1), now: now, hours: 1))
        XCTAssertFalse(KeepWarmDecision.shouldPoke(session: session(pokeable: false), now: now, hours: 1))
        XCTAssertFalse(KeepWarmDecision.shouldPoke(session: session(tty: "  "), now: now, hours: 1))
        XCTAssertFalse(KeepWarmDecision.shouldPoke(session: session(remaining: nil), now: now, hours: 1))
        XCTAssertFalse(KeepWarmDecision.shouldPoke(session: session(idle: nil), now: now, hours: 1))
        XCTAssertFalse(KeepWarmDecision.shouldPoke(session: session(), now: now, hours: nil))
        XCTAssertFalse(KeepWarmDecision.shouldPoke(session: session(), now: now, hours: 2))
        for hours in [1, 3, 6, 12] {
            XCTAssertTrue(KeepWarmDecision.shouldPoke(session: session(idle: Double(hours * 3600 - 1)), now: now, hours: hours))
        }
    }
}
