import XCTest
@testable import TprojLogic

final class BoundedCommandRunnerTests: XCTestCase {
    func testDrainsConcurrentLargeOutput() {
        let r = BoundedCommandRunner(timeout: 2).run("/bin/sh", ["-c", "for i in $(seq 1 1000); do echo oooooooooooooooooooooooooooooooooooooooooooooooooooooooooooooooooooooooooooooooooooooooooo; echo eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee >&2; done"])
        XCTAssertEqual(r.exitCode, 0); XCTAssertEqual(r.stdout.utf8.count, 65536); XCTAssertEqual(r.stderr.utf8.count, 65536)
    }
    func testHungHelperTimesOut() {
        let start = Date(); let r = BoundedCommandRunner(timeout: 0.1, eofGrace: 0.1).run("/bin/sh", ["-c", "sleep 5"])
        XCTAssertLessThan(Date().timeIntervalSince(start), 2); XCTAssertNotEqual(r.exitCode, 0)
    }
}
