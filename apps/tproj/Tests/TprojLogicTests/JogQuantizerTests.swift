import XCTest
@testable import TprojLogic

final class JogQuantizerTests: XCTestCase {
    // Accumulating 30 ticks of clockwise rotation fires exactly one +1 step.
    func testAccumulatesToOneStep() {
        var q = JogQuantizer(ticksPerStep: 30, minStepInterval: 0.15)
        let t = Date()
        XCTAssertNil(q.feed(data2: 15, now: t))        // acc 15, below threshold
        XCTAssertEqual(q.feed(data2: 15, now: t), 1)   // acc 30 -> fire +1
    }

    // A single +30 delta reaching the threshold in one message also fires once.
    func testSingleDeltaAtThresholdFires() {
        var q = JogQuantizer(ticksPerStep: 30, minStepInterval: 0.15)
        XCTAssertEqual(q.feed(data2: 30, now: Date()), 1)
    }

    // Reversing direction drops the stale accumulation (does not carry over).
    func testDirectionReversalResetsAccumulator() {
        var q = JogQuantizer(ticksPerStep: 30, minStepInterval: 0.15)
        let t = Date()
        XCTAssertNil(q.feed(data2: 20, now: t))         // +20
        XCTAssertNil(q.feed(data2: 118, now: t))        // -10: reversal resets to 0, then -10
        // Only fires because the +20 was discarded; -10 + -20 = -30 reaches threshold.
        XCTAssertEqual(q.feed(data2: 108, now: t), -1)  // -20 -> acc -30 -> fire -1
    }

    // Two threshold crossings inside minStepInterval fire only once (rate limit).
    func testMinIntervalSuppressesRapidStep() {
        var q = JogQuantizer(ticksPerStep: 30, minStepInterval: 0.15)
        let t0 = Date()
        XCTAssertEqual(q.feed(data2: 30, now: t0), 1)                          // fires
        XCTAssertNil(q.feed(data2: 30, now: t0.addingTimeInterval(0.05)))      // within 0.15s -> suppressed
        XCTAssertEqual(q.feed(data2: 30, now: t0.addingTimeInterval(0.2)), 1)  // interval elapsed -> fires
    }

    // Relative-CC two's-complement decode: 127 -> -1 (ccw), 1 -> +1 (cw).
    func testRelativeCCDecode() {
        var q = JogQuantizer(ticksPerStep: 1, minStepInterval: 0.0)
        XCTAssertEqual(q.feed(data2: 127, now: Date()), -1)
        XCTAssertEqual(q.feed(data2: 1, now: Date()), 1)
    }
}
