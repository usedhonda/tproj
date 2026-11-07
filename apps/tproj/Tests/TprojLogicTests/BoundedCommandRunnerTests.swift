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

    func testSigkillFallbackReapsThroughProcessLifecycle() {
        let start = Date()
        let r = BoundedCommandRunner(timeout: 0.1, eofGrace: 0.1).run("/bin/sh", ["-c", "trap '' TERM; exec /bin/sleep 5"])
        XCTAssertLessThan(Date().timeIntervalSince(start), 2)
        XCTAssertNotEqual(r.exitCode, 0)
    }

    func testIgnoresTermAndDoesNotWaitForInheritedPipe() {
        let start = Date()
        let r = BoundedCommandRunner(timeout: 0.1, eofGrace: 0.1).run("/bin/sh", ["-c", "trap '' TERM; (sleep 5) & exit 0"])
        XCTAssertLessThan(Date().timeIntervalSince(start), 2); XCTAssertEqual(r.exitCode, 0)
    }

    func testByteLimitInsideUTF8PreservesCapturedOutput() {
        // 13 bytes keeps "prefix日本" and the first byte of "語". A byte cap
        // must not turn the entire otherwise valid diagnostic into "".
        let r = BoundedCommandRunner(timeout: 2, maxOutput: 13).run(
            "/bin/sh", ["-c", "printf 'prefix日本語'; printf 'prefix日本語' >&2"])
        XCTAssertEqual(r.exitCode, 0)
        XCTAssertEqual(r.stdout, "prefix日本\u{FFFD}")
        XCTAssertEqual(r.stderr, "prefix日本\u{FFFD}")
    }

    func testRunsDoNotLeakPipeDescriptors() {
        // The GUI polls helpers for hours. Two leaked FIFO ends per run exhaust
        // the descriptor limit and the next launch aborts inside NSTask.
        func openFifos() -> Int {
            ((try? FileManager.default.contentsOfDirectory(atPath: "/dev/fd")) ?? []).filter { name in
                var st = stat(); return fstat(Int32(name) ?? -1, &st) == 0 && (st.st_mode & S_IFMT) == S_IFIFO
            }.count
        }
        let runner = BoundedCommandRunner(timeout: 2)
        _ = runner.run("/usr/bin/true", [])
        let baseline = openFifos()
        for _ in 0..<10 { _ = runner.run("/usr/bin/true", []) }
        XCTAssertEqual(openFifos(), baseline)
    }

    func testEmptyLaunchPathFailsInsteadOfRaising() {
        let r = BoundedCommandRunner(timeout: 2).run("", ["cache-status"])
        XCTAssertEqual(r.exitCode, 1)
        XCTAssertTrue(r.stderr.contains("absolute"))
    }

    func testMalformedByteDoesNotEraseSurroundingDiagnostics() {
        let r = BoundedCommandRunner(timeout: 2).run(
            "/bin/sh", ["-c", "printf 'before\\377after'; printf 'before\\377after' >&2"])
        XCTAssertEqual(r.exitCode, 0)
        XCTAssertEqual(r.stdout, "before\u{FFFD}after")
        XCTAssertEqual(r.stderr, "before\u{FFFD}after")
    }

}
